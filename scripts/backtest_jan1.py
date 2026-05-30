#!/usr/bin/env python3
"""
Forward test: $100K capital, $1K per stock, signal date 2026-01-01.
Model uses only data available before market open on 1/2 (Jan 1 is closed; first bar = Jan 2).
Entry at first trading day of Jan 2026 close, exit at 5/29/2026 close.
"""
import sys, warnings
import pandas as pd
import yfinance as yf

sys.path.insert(0, r"C:\Claude\Trading Analyst")
warnings.filterwarnings("ignore")

from quant.indicators import compute_indicators
from quant.forecast import compute_arima_score, compute_garch_volatility
from quant.signals import compute_signal
from quant.confidence import run_monte_carlo
from quant.trade_setup import compute_trade_setup
from smart_money.congress import compute_congress_score
from smart_money.news_scorer import compute_news_score
from smart_money.earnings_scorer import compute_earnings_score

# -- Config ---------------------------------------------------------------------
SIGNAL_CUTOFF = "2026-01-01"   # exclusive: model sees data through 12/31/2025
ENTRY_DATE    = "2026-01-01"   # perf window starts here (first bar = Jan 2, market closed Jan 1)
EXIT_DATE     = "2026-05-29"   # sell at this day's close
POSITION_SIZE = 1_000
MAX_POSITIONS = 100

# -- Universe: ~200 liquid US equities across all sectors ----------------------
UNIVERSE = list(dict.fromkeys([
    # Mega-cap tech
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AVGO","ORCL","CRM",
    "ADBE","AMD","QCOM","TXN","INTC","MU","AMAT","LRCX","KLAC","MRVL",
    "NOW","PLTR","PANW","FTNT","CRWD","ZS","NET","DDOG","MDB","ARM",
    "CSCO","IBM","DELL","ANET","HPE","SMCI","CDNS","SNPS","ANSS","EPAM",
    # Financials
    "JPM","BAC","WFC","GS","MS","BLK","C","AXP","COF","USB",
    "TFC","PNC","SCHW","CME","ICE","MCO","SPGI","V","MA","PYPL",
    "KKR","APO","BX","CG","ARES",
    # Healthcare
    "LLY","UNH","JNJ","ABBV","MRK","PFE","BMY","AMGN","GILD","ISRG",
    "MDT","ABT","TMO","DHR","SYK","BSX","ELV","CVS","CI","HUM",
    "VRTX","REGN","BIIB","MRNA","ZBH",
    # Consumer discretionary
    "HD","LOW","TGT","WMT","COST","MCD","SBUX","NKE","TJX","BKNG",
    "MAR","HLT","LVS","WYNN","MGM","F","GM","RIVN","LCID","POOL",
    # Consumer staples
    "PG","KO","PEP","PM","MO","CL","MDLZ","GIS","K","STZ",
    # Energy
    "XOM","CVX","COP","EOG","SLB","MPC","VLO","PSX","DVN","HAL",
    # Industrials
    "GE","HON","UPS","FDX","CAT","DE","LMT","RTX","NOC","GD",
    "BA","MMM","EMR","ETN","PH","ROK","ITW","IR","AME","CARR",
    "UBER","LYFT","DASH","ABNB",
    # Materials / commodities
    "FCX","NEM","APD","LIN","SHW","ECL","DD","DOW","ALB","MP",
    # Real estate
    "AMT","PLD","EQIX","SPG","CBRE","WELL","O","DLR","PSA","AVB",
    # Utilities
    "NEE","DUK","SO","AEP","EXC","SRE","PCG","XEL","WEC","ES",
    # Comm services
    "T","VZ","TMUS","CHTR","CMCSA","DIS","NFLX","SPOT","SNAP","PINS",
]))

# -- Helper ---------------------------------------------------------------------
def to_bars(df: pd.DataFrame) -> list[dict]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    bars = []
    for ts, row in df.iterrows():
        try:
            bars.append({
                "t": int(pd.Timestamp(ts).timestamp() * 1000),
                "o": float(row["Open"]),
                "h": float(row["High"]),
                "l": float(row["Low"]),
                "c": float(row["Close"]),
                "v": int(row["Volume"]),
            })
        except Exception:
            continue
    return [b for b in bars if b["h"] > 0 and b["v"] > 0]


# -- Screening ------------------------------------------------------------------
print(f"Screening {len(UNIVERSE)} tickers -- signal date {SIGNAL_CUTOFF}")
print(f"Full 5-layer pipeline: Technical + ARIMA + Congress(Quiver) + News(NewsAPI) + Earnings")
print(f"Thresholds: BUY>0.58  AVOID<0.42  (recalibrated)")
print(f"EMA fix: oversold (RSI<35) bearish stocks score 0.35 not 0.0\n")
print(f"{'#':>4}  {'Ticker':<6}  {'Signal':<6}  {'Score':>6}  {'C':>5} {'N':>5} {'E':>5}  {'Entry':>8}  {'Exit':>8}  {'Return':>8}")
print("-" * 80)

results = []

for idx, ticker in enumerate(UNIVERSE, 1):
    try:
        # Model data: everything through 12/31/2025
        hist = yf.download(ticker, start="2023-01-01", end=SIGNAL_CUTOFF,
                           progress=False, auto_adjust=True)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        if hist.empty or len(hist) < 60:
            continue

        bars = to_bars(hist)
        if len(bars) < 60:
            continue

        # Performance window: Jan 2, 2026 close → 5/29/2026 close
        perf = yf.download(ticker, start=ENTRY_DATE, end="2026-05-30",
                           progress=False, auto_adjust=True)
        if isinstance(perf.columns, pd.MultiIndex):
            perf.columns = perf.columns.get_level_values(0)
        if perf.empty or len(perf) < 2:
            continue

        entry_price = float(perf["Close"].iloc[0])   # first trading day of Jan 2026
        exit_price  = float(perf["Close"].iloc[-1])  # 5/29 close
        return_pct  = (exit_price - entry_price) / entry_price * 100

        # Run the full 5-layer model
        ind   = compute_indicators(bars)
        fcast = compute_arima_score([b["c"] for b in bars])
        garch = compute_garch_volatility([b["c"] for b in bars])

        congress_score = compute_congress_score(ticker)
        news_score     = compute_news_score(ticker)
        earnings_score = compute_earnings_score(ticker)

        sig = compute_signal(
            technical_score=ind["technical_score"],
            arima_score=fcast["arima_score"],
            smart_money_score=congress_score,
            news_score=news_score,
            earnings_score=earnings_score,
        )
        mc         = run_monte_carlo(entry_price, max(garch["daily_vol"], 0.001), seed=42)
        trade_card = compute_trade_setup(entry_price, ind["atr_stop"])

        row = {
            "ticker":          ticker,
            "label":           sig["label"],
            "composite_score": sig["composite_score"],
            "prob_success":    mc["prob_success"],
            "entry_price":     round(entry_price, 2),
            "exit_price":      round(exit_price, 2),
            "return_pct":      round(return_pct, 2),
            "rsi":             ind["rsi"],
            "trend_regime":    ind["ema_trend"],
            "vol_regime":      garch["vol_regime"],
            "atr_stop":        ind["atr_stop"],
            "take_profit":     trade_card["take_profit"],
            "risk_reward":     trade_card["risk_reward_ratio"],
            "lower_80":        mc["lower_80"],
            "upper_80":        mc["upper_80"],
            "congress":        round(congress_score, 3),
            "news":            round(news_score, 3),
            "earnings":        round(earnings_score, 3),
        }
        results.append(row)

        print(f"{idx:>4}  {ticker:<6}  {sig['label']:<6}  {sig['composite_score']:>6.3f}  "
              f"C:{congress_score:.2f} N:{news_score:.2f} E:{earnings_score:.2f}  "
              f"${entry_price:>7.2f}  ${exit_price:>7.2f}  {return_pct:>+7.2f}%")

    except Exception as e:
        print(f"{idx:>4}  {ticker:<6}  ERROR: {e}")
        continue

# -- Portfolio: top 100 by composite score (model ranking regardless of label) --
ranked = sorted(results, key=lambda x: x["composite_score"], reverse=True)
portfolio   = ranked[:MAX_POSITIONS]   # top 100 = model's picks
avoided     = ranked[MAX_POSITIONS:]   # bottom = model passed on

# -- Benchmark -----------------------------------------------------------------
spy_data = yf.download("SPY", start=ENTRY_DATE, end="2026-05-30",
                        progress=False, auto_adjust=True)
if isinstance(spy_data.columns, pd.MultiIndex):
    spy_data.columns = spy_data.columns.get_level_values(0)
spy_entry  = float(spy_data["Close"].iloc[0])
spy_exit   = float(spy_data["Close"].iloc[-1])
spy_return = (spy_exit - spy_entry) / spy_entry * 100

# -- Results --------------------------------------------------------------------
import statistics

def port_stats(positions):
    rets = [r["return_pct"] for r in positions]
    total_pnl = sum(r["return_pct"] / 100 * POSITION_SIZE for r in positions)
    port_ret  = total_pnl / (len(positions) * POSITION_SIZE) * 100
    win_rate  = sum(1 for r in positions if r["return_pct"] > 0) / len(positions)
    return rets, total_pnl, port_ret, win_rate

print(f"\n{'='*68}")
print(f"  FORWARD TEST: {ENTRY_DATE} (first bar = Jan 2) to {EXIT_DATE}")
print(f"{'='*68}")
print(f"  Tickers screened     : {len(results)}")
print(f"  BUY labels (>0.58)   : {sum(1 for r in results if r['label']=='BUY')}")
print(f"  WATCH labels         : {sum(1 for r in results if r['label']=='WATCH')}")
print(f"  AVOID labels (<0.42) : {sum(1 for r in results if r['label']=='AVOID')}")
print()
print(f"  EMA fix active: oversold bearish stocks score 0.35 (not 0.0)")
print(f"  Portfolio = top {MAX_POSITIONS} ranked by composite score.")

rets_port, pnl_port, ret_port, wr_port = port_stats(portfolio)
rets_skip, pnl_skip, ret_skip, wr_skip = port_stats(avoided)
best  = max(portfolio, key=lambda x: x["return_pct"])
worst = min(portfolio, key=lambda x: x["return_pct"])

print(f"\n{'='*68}")
print(f"  PORTFOLIO (top {MAX_POSITIONS} by score)         vs  AVOIDED (bottom {len(avoided)})")
print(f"{'='*68}")
print(f"  Capital invested  : ${len(portfolio)*POSITION_SIZE:>10,.0f}")
print(f"  Total P&L         : ${pnl_port:>+10,.2f}   |  avoided avg return: {ret_skip:>+.2f}%")
print(f"  Portfolio return  : {ret_port:>+10.2f}%")
print(f"  S&P 500 return    : {spy_return:>+10.2f}%  (SPY {spy_entry:.2f} -> {spy_exit:.2f})")
print(f"  Alpha vs S&P 500  : {ret_port - spy_return:>+10.2f}%")
print()
print(f"  Win rate (port)   : {wr_port:.1%}  ({sum(1 for r in portfolio if r['return_pct']>0)}/{len(portfolio)})")
print(f"  Win rate (avoided): {wr_skip:.1%}  ({sum(1 for r in avoided if r['return_pct']>0)}/{len(avoided)})")
print(f"  Best pick         : {best['ticker']:<6} {best['return_pct']:+.2f}%")
print(f"  Worst pick        : {worst['ticker']:<6} {worst['return_pct']:+.2f}%")
print(f"  Median return     : {statistics.median(rets_port):+.2f}%")
print(f"  Std dev           : {statistics.stdev(rets_port):.2f}%")

# Quintile breakdown
print(f"\n--- Score quintile breakdown (signal quality test) ---")
q_size = len(ranked) // 5
for q in range(5):
    q_slice = ranked[q*q_size:(q+1)*q_size]
    avg_ret   = sum(r["return_pct"] for r in q_slice) / len(q_slice)
    avg_score = sum(r["composite_score"] for r in q_slice) / len(q_slice)
    wr        = sum(1 for r in q_slice if r["return_pct"] > 0) / len(q_slice)
    label     = f"Q{q+1} (top)" if q == 0 else (f"Q{q+1} (bot)" if q == 4 else f"Q{q+1}     ")
    print(f"  {label}: avg score={avg_score:.3f}  avg return={avg_ret:>+6.2f}%  win rate={wr:.0%}")

# Spearman rank correlation
score_ranks  = [sorted(results, key=lambda x: -x["composite_score"]).index(r) for r in results]
return_ranks = [sorted(results, key=lambda x: -x["return_pct"]).index(r) for r in results]
n = len(results)
d2 = sum((sr - rr)**2 for sr, rr in zip(score_ranks, return_ranks))
spearman = 1 - 6 * d2 / (n * (n**2 - 1))
print(f"\n  Spearman rank corr (score vs return): {spearman:+.3f}")
print(f"  (>0 = model ranks winners higher; closer to 1.0 = stronger signal)")

# Trade cards for BUY signals
buy_signals = [r for r in portfolio if r["label"] == "BUY"]
if buy_signals:
    print(f"\n--- Trade cards for BUY signals in portfolio ({len(buy_signals)} picks) ---")
    print(f"  {'TICKER':<6}  {'ENTRY':>8}  {'STOP':>8}  {'TARGET':>8}  {'R:R':>5}  {'ACTUAL':>8}")
    for r in sorted(buy_signals, key=lambda x: x["composite_score"], reverse=True)[:20]:
        print(f"  {r['ticker']:<6}  ${r['entry_price']:>7.2f}  ${r['atr_stop']:>7.2f}  "
              f"${r['take_profit']:>7.2f}  {r['risk_reward']:>5.1f}x  {r['return_pct']:>+7.2f}%")

# Full sorted table
print(f"\n{'='*100}")
print(f"  {'#':>3}  {'TICKER':<6}  {'SCORE':>6}  {'RSI':>6}  {'TREND':>8}  {'C':>5}{'N':>5}{'E':>5}  {'ENTRY':>8}  {'EXIT':>8}  {'RETURN':>8}  PICK")
print(f"{'='*100}")
for i, r in enumerate(ranked, 1):
    pick = "BUY " if i <= MAX_POSITIONS else "skip"
    marker = "W" if r["return_pct"] > 0 else "L"
    print(f"  {i:>3}  {r['ticker']:<6}  {r['composite_score']:>6.3f}  "
          f"{r['rsi']:>6.1f}  {r['trend_regime']:>8}  "
          f"{r['congress']:>5.2f}{r['news']:>5.2f}{r['earnings']:>5.2f}  "
          f"${r['entry_price']:>7.2f}  ${r['exit_price']:>7.2f}  "
          f"{r['return_pct']:>+7.2f}%  {pick} {marker}")

print(f"\n{'='*68}\n")
