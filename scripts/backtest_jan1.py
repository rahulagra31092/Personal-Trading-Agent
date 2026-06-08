#!/usr/bin/env python3
"""
6-layer forward test: TOP 20, $5,000 flat each, no intra-period stops.
Exit rule: hold to 2026-05-29 OR sell at quarter-end if score drops below rank 40.
Signal date 2026-01-01. Entry Jan 2. Exit 2026-05-29.
"""
import sys, warnings, statistics
import pandas as pd
import yfinance as yf

sys.path.insert(0, r"C:\Claude\Trading Analyst")
warnings.filterwarnings("ignore")

from quant.indicators import compute_indicators
from quant.forecast import compute_garch_volatility
from quant.signals import compute_signal
from quant.momentum import compute_momentum_score_from_bars
from quant.quality import compute_quality_score
from quant.regime import get_market_regime
from quant.sector import apply_concentration_cap
from smart_money.congress import compute_congress_score
from smart_money.earnings_scorer import compute_earnings_score
from data.news import prefetch_sector_news

# -- Config -------------------------------------------------------------------
SIGNAL_CUTOFF  = "2026-01-01"
ENTRY_DATE     = "2026-01-01"
EXIT_DATE      = "2026-05-29"
CAPITAL        = 100_000
N_POSITIONS    = 20
POSITION_SIZE  = CAPITAL / N_POSITIONS   # $5,000 flat
REBAL_RANK_CUT = 40    # sell at quarter-end if position falls below this rank

# -- Universe -----------------------------------------------------------------
UNIVERSE = list(dict.fromkeys([
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AVGO","ORCL","CRM",
    "ADBE","AMD","QCOM","TXN","INTC","MU","AMAT","LRCX","KLAC","MRVL",
    "NOW","PLTR","PANW","FTNT","CRWD","ZS","NET","DDOG","MDB","ARM",
    "CSCO","IBM","DELL","ANET","HPE","SMCI","CDNS","SNPS","ANSS","EPAM",
    "JPM","BAC","WFC","GS","MS","BLK","C","AXP","COF","USB",
    "TFC","PNC","SCHW","CME","ICE","MCO","SPGI","V","MA","PYPL",
    "KKR","APO","BX","CG","ARES",
    "LLY","UNH","JNJ","ABBV","MRK","PFE","BMY","AMGN","GILD","ISRG",
    "MDT","ABT","TMO","DHR","SYK","BSX","ELV","CVS","CI","HUM",
    "VRTX","REGN","BIIB","MRNA","ZBH",
    "HD","LOW","TGT","WMT","COST","MCD","SBUX","NKE","TJX","BKNG",
    "MAR","HLT","LVS","WYNN","MGM","F","GM","RIVN","LCID","POOL",
    "PG","KO","PEP","PM","MO","CL","MDLZ","GIS","K","STZ",
    "XOM","CVX","COP","EOG","SLB","MPC","VLO","PSX","DVN","HAL",
    "GE","HON","UPS","FDX","CAT","DE","LMT","RTX","NOC","GD",
    "BA","MMM","EMR","ETN","PH","ROK","ITW","IR","AME","CARR",
    "UBER","LYFT","DASH","ABNB",
    "FCX","NEM","APD","LIN","SHW","ECL","DD","DOW","ALB","MP",
    "AMT","PLD","EQIX","SPG","CBRE","WELL","O","DLR","PSA","AVB",
    "NEE","DUK","SO","AEP","EXC","SRE","PCG","XEL","WEC","ES",
    "T","VZ","TMUS","CHTR","CMCSA","DIS","NFLX","SPOT","SNAP","PINS",
]))

SECTOR_GROUPS: dict[str, list[str]] = {
    "tech": ["AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AVGO","ORCL","CRM",
             "ADBE","AMD","QCOM","TXN","INTC","MU","AMAT","LRCX","KLAC","MRVL",
             "NOW","PLTR","PANW","FTNT","CRWD","ZS","NET","DDOG","MDB","ARM",
             "CSCO","IBM","DELL","ANET","HPE","SMCI","CDNS","SNPS","ANSS","EPAM"],
    "financials": ["JPM","BAC","WFC","GS","MS","BLK","C","AXP","COF","USB",
                   "TFC","PNC","SCHW","CME","ICE","MCO","SPGI","V","MA","PYPL",
                   "KKR","APO","BX","CG","ARES"],
    "healthcare": ["LLY","UNH","JNJ","ABBV","MRK","PFE","BMY","AMGN","GILD","ISRG",
                   "MDT","ABT","TMO","DHR","SYK","BSX","ELV","CVS","CI","HUM",
                   "VRTX","REGN","BIIB","MRNA","ZBH"],
    "consumer_discretionary": ["HD","LOW","TGT","WMT","COST","MCD","SBUX","NKE","TJX","BKNG",
                                "MAR","HLT","LVS","WYNN","MGM","F","GM","RIVN","LCID","POOL"],
    "consumer_staples": ["PG","KO","PEP","PM","MO","CL","MDLZ","GIS","K","STZ"],
    "energy": ["XOM","CVX","COP","EOG","SLB","MPC","VLO","PSX","DVN","HAL"],
    "industrials": ["GE","HON","UPS","FDX","CAT","DE","LMT","RTX","NOC","GD",
                    "BA","MMM","EMR","ETN","PH","ROK","ITW","IR","AME","CARR",
                    "UBER","LYFT","DASH","ABNB"],
    "materials": ["FCX","NEM","APD","LIN","SHW","ECL","DD","DOW","ALB","MP"],
    "real_estate": ["AMT","PLD","EQIX","SPG","CBRE","WELL","O","DLR","PSA","AVB"],
    "utilities": ["NEE","DUK","SO","AEP","EXC","SRE","PCG","XEL","WEC","ES"],
    "comm_services": ["T","VZ","TMUS","CHTR","CMCSA","DIS","NFLX","SPOT","SNAP","PINS"],
}

# -- Helpers ------------------------------------------------------------------
def to_bars(df: pd.DataFrame) -> list[dict]:
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    bars = []
    for ts, row in df.iterrows():
        try:
            bars.append({"t": int(pd.Timestamp(ts).timestamp() * 1000),
                         "o": float(row["Open"]), "h": float(row["High"]),
                         "l": float(row["Low"]),  "c": float(row["Close"]),
                         "v": int(row["Volume"])})
        except Exception:
            continue
    return [b for b in bars if b["h"] > 0 and b["v"] > 0]


def quarter_end_prices(perf_df: pd.DataFrame) -> dict[str, float]:
    """Return close prices at each quarter-end within the perf window."""
    perf_df = perf_df.copy()
    perf_df.index = pd.to_datetime(perf_df.index)
    # Quarter boundaries within our window (Mar 31 and Jun 30)
    quarters = {}
    for label, cutoff in [("Q1_end", "2026-03-31"), ("Q2_end", "2026-06-30")]:
        rows = perf_df[perf_df.index <= cutoff]
        if not rows.empty:
            quarters[label] = float(rows["Close"].iloc[-1])
    return quarters


# -- Regime -------------------------------------------------------------------
print("Checking market regime (VIX) as of Jan 2, 2026...")
regime = get_market_regime("2026-01-03")
print(f"  {regime['regime'].upper()}  VIX={regime['vix']}  pos_factor={regime['position_factor']}\n")

# -- Prefetch news ------------------------------------------------------------
print("Prefetching sector news...")
prefetch_sector_news(SECTOR_GROUPS, days=3)
print("Done.\n")

# -- Screening ----------------------------------------------------------------
print(f"Scoring {len(UNIVERSE)} tickers | 6-layer model | signal date {SIGNAL_CUTOFF}")
print(f"{'#':>4}  {'Tick':<6}  {'Sig':<5}  {'Sc':>5}  "
      f"{'Mo':>4}  {'Qu':>4}  {'C':>4}  {'N':>4}  {'E':>4}")
print("-" * 55)

results = []

for idx, ticker in enumerate(UNIVERSE, 1):
    try:
        hist = yf.download(ticker, start="2023-01-01", end=SIGNAL_CUTOFF,
                           progress=False, auto_adjust=True)
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        if hist.empty or len(hist) < 60:
            continue
        bars = to_bars(hist)
        if len(bars) < 60:
            continue

        perf = yf.download(ticker, start=ENTRY_DATE, end="2026-05-30",
                           progress=False, auto_adjust=True)
        if isinstance(perf.columns, pd.MultiIndex):
            perf.columns = perf.columns.get_level_values(0)
        if perf.empty or len(perf) < 2:
            continue

        entry_price = float(perf["Close"].iloc[0])
        exit_price  = float(perf["Close"].iloc[-1])   # hold to end, no stops
        return_pct  = (exit_price - entry_price) / entry_price * 100

        ind            = compute_indicators(bars)
        garch          = compute_garch_volatility([b["c"] for b in bars])
        momentum_score = compute_momentum_score_from_bars(bars)
        quality_score  = compute_quality_score(ticker)
        congress_score = compute_congress_score(ticker)
        news_score     = compute_news_score(ticker)
        earnings_score = compute_earnings_score(ticker)

        sig = compute_signal(
            technical_score   = ind["technical_score"],
            momentum_score    = momentum_score,
            quality_score     = quality_score,
            smart_money_score = congress_score,
            news_score        = news_score,
            earnings_score    = earnings_score,
        )

        q_prices = quarter_end_prices(perf)

        row = {
            "ticker":          ticker,
            "label":           sig["label"],
            "composite_score": sig["composite_score"],
            "momentum_score":  round(momentum_score, 3),
            "quality_score":   round(quality_score, 3),
            "congress":        round(congress_score, 3),
            "news":            round(news_score, 3),
            "earnings":        round(earnings_score, 3),
            "entry_price":     round(entry_price, 2),
            "exit_price":      round(exit_price, 2),
            "return_pct":      round(return_pct, 2),
            "rsi":             ind["rsi"],
            "daily_vol":       round(max(garch["daily_vol"], 0.001), 4),
            "q1_price":        q_prices.get("Q1_end"),
            "layer_scores":    sig["layer_scores"],
        }
        results.append(row)

        print(f"{idx:>4}  {ticker:<6}  {sig['label']:<5}  {sig['composite_score']:>5.3f}  "
              f"{momentum_score:>4.2f}  {quality_score:>4.2f}  "
              f"{congress_score:>4.2f}  {news_score:>4.2f}  {earnings_score:>4.2f}")

    except Exception as e:
        print(f"{idx:>4}  {ticker:<6}  ERROR: {e}")
        continue

# -- Portfolio construction ---------------------------------------------------
ranked = sorted(results, key=lambda x: x["composite_score"], reverse=True)

# Apply concentration cap then take top 20
capped_set = set(apply_concentration_cap([r["ticker"] for r in ranked]))
portfolio  = [r for r in ranked if r["ticker"] in capped_set][:N_POSITIONS]
avoided    = [r for r in ranked if r not in portfolio]

# Rebalancing simulation: at Q1 end (Mar 31), would we have exited anything?
# Rule: sell at Q1-end close if rank has dropped below REBAL_RANK_CUT
# (In this forward test, scores are fixed at Jan 1 — real system would re-score)
# We flag which positions WOULD trigger the exit rule if their Q1 return < -15%
# as a proxy for score deterioration (negative momentum = likely rank drop)
rebal_exits = []
for r in portfolio:
    q1 = r.get("q1_price")
    if q1 and r["entry_price"] > 0:
        q1_ret = (q1 - r["entry_price"]) / r["entry_price"] * 100
        if q1_ret < -15:
            rebal_exits.append((r["ticker"], round(q1_ret, 2)))

# -- Benchmark ----------------------------------------------------------------
spy_data = yf.download("SPY", start=ENTRY_DATE, end="2026-05-30",
                        progress=False, auto_adjust=True)
if isinstance(spy_data.columns, pd.MultiIndex):
    spy_data.columns = spy_data.columns.get_level_values(0)
spy_entry  = float(spy_data["Close"].iloc[0])
spy_exit   = float(spy_data["Close"].iloc[-1])
spy_return = (spy_exit - spy_entry) / spy_entry * 100

# -- P&L ----------------------------------------------------------------------
total_pnl  = sum(POSITION_SIZE * r["return_pct"] / 100 for r in portfolio)
port_return = total_pnl / CAPITAL * 100
wins  = sum(1 for r in portfolio if r["return_pct"] > 0)
rets  = [r["return_pct"] for r in portfolio]
best  = max(portfolio, key=lambda x: x["return_pct"])
worst = min(portfolio, key=lambda x: x["return_pct"])

# Annualized (148 calendar days ≈ 0.405 years)
holding_years = 148 / 365
annualized = ((1 + port_return / 100) ** (1 / holding_years) - 1) * 100
spy_annualized = ((1 + spy_return / 100) ** (1 / holding_years) - 1) * 100

# -- Output -------------------------------------------------------------------
print(f"\n{'='*68}")
print(f"  FORWARD TEST: Jan 2, 2026 -> May 29, 2026  ({int(holding_years*365)} days)")
print(f"  Strategy: TOP {N_POSITIONS} by score  |  ${POSITION_SIZE:,.0f} flat each  |  No stops  |  Hold")
print(f"  Regime: {regime['regime'].upper()}  VIX {regime['vix']}")
print(f"{'='*68}")

print(f"\n  {'#':>2}  {'Ticker':<6}  {'Score':>6}  {'Mom':>5}  {'Qual':>5}  "
      f"{'Entry':>8}  {'Exit':>8}  {'Return':>8}  {'P&L':>8}")
print(f"  {'-'*72}")
for i, r in enumerate(portfolio, 1):
    pnl = POSITION_SIZE * r["return_pct"] / 100
    marker = "+" if r["return_pct"] > spy_return else " "
    print(f"  {i:>2}  {r['ticker']:<6}  {r['composite_score']:>6.3f}  "
          f"{r['momentum_score']:>5.2f}  {r['quality_score']:>5.2f}  "
          f"${r['entry_price']:>7.2f}  ${r['exit_price']:>7.2f}  "
          f"{r['return_pct']:>+7.2f}%{marker} ${pnl:>+7,.0f}")

print(f"\n  Note: {marker} = beat SPY ({spy_return:+.2f}%) on this position")

print(f"\n{'='*68}")
print(f"  PERFORMANCE SUMMARY")
print(f"{'='*68}")
print(f"  Capital deployed   : ${CAPITAL:>10,.0f}  ({N_POSITIONS} x ${POSITION_SIZE:,.0f})")
print(f"  Total P&L          : ${total_pnl:>+10,.2f}")
print(f"  Portfolio return   : {port_return:>+10.2f}%  (5-month)")
print(f"  Annualized return  : {annualized:>+10.1f}%  (projected full-year)")
print(f"  S&P 500 return     : {spy_return:>+10.2f}%  (SPY ${spy_entry:.2f} -> ${spy_exit:.2f})")
print(f"  S&P 500 annualized : {spy_annualized:>+10.1f}%")
print(f"  Alpha vs S&P 500   : {port_return - spy_return:>+10.2f}%  ({annualized - spy_annualized:>+.1f}% annualized)")
print()
print(f"  Win rate           : {wins/len(portfolio):.1%}  ({wins}/{len(portfolio)} positions positive)")
print(f"  Median return      : {statistics.median(rets):>+.2f}%")
print(f"  Std deviation      : {statistics.stdev(rets):.2f}%")
print(f"  Best pick          : {best['ticker']:<6}  {best['return_pct']:>+.2f}%  (${POSITION_SIZE * best['return_pct']/100:>+,.0f})")
print(f"  Worst pick         : {worst['ticker']:<6}  {worst['return_pct']:>+.2f}%  (${POSITION_SIZE * worst['return_pct']/100:>+,.0f})")

print(f"\n{'='*68}")
print(f"  REBALANCING SIGNAL (Q1 end Mar 31)")
print(f"{'='*68}")
if rebal_exits:
    print(f"  These positions were down >15% at Q1-end — would trigger a re-score:")
    for ticker, q1ret in rebal_exits:
        print(f"    {ticker:<6}  Q1 return: {q1ret:>+.2f}%")
    print(f"  Action: re-score universe Mar 31, replace with next highest-ranked stocks")
else:
    print(f"  No positions triggered the rebalancing rule at Q1-end (Mar 31).")
    print(f"  All held into Q2.")

# -- Quintile breakdown -------------------------------------------------------
print(f"\n{'='*68}")
print(f"  FULL UNIVERSE RANKING QUALITY CHECK")
print(f"{'='*68}")
q_size = max(1, len(ranked) // 5)
for q in range(5):
    q_slice = ranked[q*q_size:(q+1)*q_size]
    if not q_slice:
        continue
    avg_ret   = sum(r["return_pct"] for r in q_slice) / len(q_slice)
    avg_score = sum(r["composite_score"] for r in q_slice) / len(q_slice)
    wr        = sum(1 for r in q_slice if r["return_pct"] > 0) / len(q_slice)
    label     = f"Q{q+1} (top {N_POSITIONS})" if q == 0 else (f"Q{q+1} (bottom)" if q == 4 else f"Q{q+1}         ")
    print(f"  {label}: score={avg_score:.3f}  avg return={avg_ret:>+6.2f}%  win={wr:.0%}")

score_ranks  = [sorted(results, key=lambda x: -x["composite_score"]).index(r) for r in results]
return_ranks = [sorted(results, key=lambda x: -x["return_pct"]).index(r) for r in results]
n  = len(results)
d2 = sum((sr - rr)**2 for sr, rr in zip(score_ranks, return_ranks))
spearman = 1 - 6 * d2 / (n * (n**2 - 1))
print(f"\n  Spearman rank corr : {spearman:>+.3f}")
print(f"  (>0 = model ranks winners higher | closer to 1.0 = stronger signal)")

# -- Miss analysis ------------------------------------------------------------
missed = sorted(avoided, key=lambda x: x["return_pct"], reverse=True)[:10]
print(f"\n{'='*68}")
print(f"  TOP 10 MISSED PICKS (in universe but outside top {N_POSITIONS})")
print(f"{'='*68}")
print(f"  {'Ticker':<6}  {'Score':>6}  {'Rank':>5}  {'Return':>8}  Why missed")
for r in missed:
    rank = ranked.index(r) + 1
    reason = "concentration cap" if r["ticker"] not in capped_set else f"ranked #{rank}"
    print(f"  {r['ticker']:<6}  {r['composite_score']:>6.3f}  #{rank:>4}  {r['return_pct']:>+7.2f}%  {reason}")

print(f"\n{'='*68}\n")
