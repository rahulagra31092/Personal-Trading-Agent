#!/usr/bin/env python3
"""
12-month backtest: June 2, 2025 -> May 29, 2026
3 scenarios | 3-month minimum hold | quarterly rebalancing
$100,000 starting capital
"""
import sys, os, warnings, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
warnings.filterwarnings("ignore")
import logging
logging.basicConfig(level=logging.WARNING)

from datetime import date
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd
import yfinance as yf

from quant.indicators import compute_indicators
from quant.signals import compute_signal
from quant.momentum import compute_momentum_score_from_bars
from quant.quality import compute_quality_score
from quant.sector import apply_concentration_cap
from smart_money.congress import compute_congress_score
from smart_money.news_scorer import compute_news_score
from data.earnings import get_earnings_calendar

# ── Constants ──────────────────────────────────────────────────────────────────
CAPITAL          = 100_000
TRANSACTION_COST = 0.001   # 0.1% per side (bid-ask + market impact, no commission)
ENTRY     = date(2025, 6, 2)    # Monday — June 1 is Sunday
EXIT      = date(2026, 5, 29)   # Friday — May 31 is Sunday
REBAL     = [date(2025, 9, 2), date(2025, 12, 1), date(2026, 3, 2)]
MIN_HOLD  = 90   # days

N1, N2, N3, N4 = 100, 20, 20, 20
CUT1, CUT2, CUT3, CUT4 = 150, 40, 40, 40   # sell if rank > cutoff at rebalance

# S4: monthly rebalancing, no minimum hold (only rule: no same-day trading)
MIN_HOLD_S4 = 1
S4_REBAL = [
    date(2025, 7, 1),
    date(2025, 8, 1),
    date(2025, 9, 2),   # overlaps quarterly rebal
    date(2025, 10, 1),
    date(2025, 11, 3),
    date(2025, 12, 1),  # overlaps quarterly rebal
    date(2026, 1, 2),
    date(2026, 2, 2),
    date(2026, 3, 2),   # overlaps quarterly rebal
    date(2026, 4, 1),
    date(2026, 5, 1),
]

HIST_START = "2024-03-01"   # 15-month lookback for 12-1 momentum
HIST_END   = "2026-06-01"

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
    "PG","KO","PEP","PM","MO","CL","MDLZ","GIS","STZ",
    "XOM","CVX","COP","EOG","SLB","MPC","VLO","PSX","DVN","HAL",
    "GE","HON","UPS","FDX","CAT","DE","LMT","RTX","NOC","GD",
    "BA","MMM","EMR","ETN","PH","ROK","ITW","IR","AME","CARR",
    "UBER","LYFT","DASH","ABNB",
    "FCX","NEM","APD","LIN","SHW","ECL","DD","DOW","ALB","MP",
    "AMT","PLD","EQIX","SPG","CBRE","WELL","O","DLR","PSA","AVB",
    "NEE","DUK","SO","AEP","EXC","SRE","PCG","XEL","WEC","ES",
    "T","VZ","TMUS","CHTR","CMCSA","DIS","NFLX","SPOT","SNAP","PINS",
]))

# ──────────────────────────────────────────────────────────────────────────────
# PHASE 1: Batch price download
# ──────────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("  PHASE 1: Batch downloading price history (Mar 2024 -> Jun 2026)")
print("=" * 70)

_raw = yf.download(
    " ".join(UNIVERSE + ["SPY", "^VIX"]),
    start=HIST_START,
    end=HIST_END,
    auto_adjust=True,
    progress=True,
    group_by="ticker",
)
_pc: dict[str, pd.DataFrame] = {}
for t in UNIVERSE + ["SPY", "^VIX"]:
    try:
        df = _raw[t].dropna(how="all")
        df.index = pd.to_datetime(df.index)
        if not df.empty and "Close" in df.columns and len(df) > 30:
            _pc[t] = df
    except Exception:
        pass
print(f"\n  Price data loaded: {len(_pc) - 2} universe tickers + SPY + VIX\n")


def _to_bars(df: pd.DataFrame) -> list[dict]:
    bars = []
    for ts, row in df.iterrows():
        try:
            bars.append({
                "t": int(pd.Timestamp(ts).timestamp() * 1000),
                "o": float(row.get("Open", row["Close"])),
                "h": float(row.get("High", row["Close"])),
                "l": float(row.get("Low",  row["Close"])),
                "c": float(row["Close"]),
                "v": int(row.get("Volume", 0)),
            })
        except Exception:
            continue
    return [b for b in bars if b["c"] > 0 and b["h"] > 0]


def get_bars(ticker: str, as_of: date) -> list[dict]:
    df = _pc.get(ticker)
    if df is None:
        return []
    return _to_bars(df[df.index.date <= as_of])


def get_close(ticker: str, as_of: date) -> Optional[float]:
    df = _pc.get(ticker)
    if df is None:
        return None
    rows = df[df.index.date <= as_of]["Close"].dropna()
    return float(rows.iloc[-1]) if not rows.empty else None


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 2: Static scores — quality + congress (computed once for all dates)
# ──────────────────────────────────────────────────────────────────────────────
print("=" * 70)
print("  PHASE 2: Quality + congress scores (one-time, reused at all dates)")
print("  [See ASSUMPTIONS for why these are computed from current data]")
print("=" * 70)

_static: dict[str, dict] = {}
for i, t in enumerate(UNIVERSE, 1):
    try:
        _static[t] = {
            "quality":  compute_quality_score(t),
            "congress": compute_congress_score(t),
        }
    except Exception:
        _static[t] = {"quality": 0.5, "congress": 0.5}
    if i % 25 == 0 or i == len(UNIVERSE):
        print(f"  {i}/{len(UNIVERSE)} tickers processed...")

print("\n  Fetching historical EPS data (date-filtered, no look-ahead)...")
_earnings_hist: dict[str, pd.DataFrame] = {}
for t in UNIVERSE:
    try:
        hist = yf.Ticker(t).earnings_history
        if hist is not None and not hist.empty:
            hist.index = pd.to_datetime(hist.index)
            _earnings_hist[t] = hist
    except Exception:
        pass
print(f"  EPS history loaded for {len(_earnings_hist)}/{len(UNIVERSE)} tickers\n")


def _earnings_score(ticker: str, as_of: date) -> float:
    """Beat-rate from EPS quarters completed BEFORE signal date — no look-ahead bias."""
    try:
        hist = _earnings_hist.get(ticker)
        if hist is None or hist.empty:
            return 0.5
        past = hist[hist.index.date < as_of].tail(8)
        if past.empty:
            return 0.5
        total = len(past)
        beats = int((past["surprisePercent"] > 0).sum())
        br = round(beats / total, 2)
        return round(max(0.20, min(0.80, 0.25 + br * 0.5)), 4)
    except Exception:
        return 0.5


# ──────────────────────────────────────────────────────────────────────────────
# PHASE 3: Score universe at a given date
# ──────────────────────────────────────────────────────────────────────────────
def score_universe(signal_date: date) -> list[dict]:
    results = []
    for ticker in UNIVERSE:
        try:
            bars = get_bars(ticker, as_of=signal_date)
            if len(bars) < 60:
                continue
            ind      = compute_indicators(bars)
            momentum = compute_momentum_score_from_bars(bars)
            earnings = _earnings_score(ticker, signal_date)
            sig = compute_signal(
                technical_score   = ind["technical_score"],
                momentum_score    = momentum,
                quality_score     = _static[ticker]["quality"],
                smart_money_score = _static[ticker]["congress"],
                news_score        = compute_news_score(ticker),
                earnings_score    = earnings,
            )
            results.append({
                "ticker":   ticker,
                "score":    sig["composite_score"],
                "label":    sig["label"],
                "momentum": round(momentum, 3),
                "quality":  round(_static[ticker]["quality"], 3),
                "congress": round(_static[ticker]["congress"], 3),
                "tech":     round(ind["technical_score"], 3),
                "earnings": round(earnings, 3),
            })
        except Exception:
            continue
    return sorted(results, key=lambda x: x["score"], reverse=True)


print("=" * 70)
print("  PHASE 3: Scoring universe at all rebalance checkpoints (S1-S4)")
print("=" * 70)

all_dates = sorted(set([ENTRY] + REBAL + S4_REBAL))
scores: dict[date, list[dict]] = {}
for d in all_dates:
    print(f"  Scoring as of {d}...", end=" ", flush=True)
    scores[d] = score_universe(d)
    print(f"  {len(scores[d])} tickers scored. Top: {scores[d][0]['ticker']} ({scores[d][0]['score']:.3f})")

initial = scores[ENTRY]


# ──────────────────────────────────────────────────────────────────────────────
# Market context
# ──────────────────────────────────────────────────────────────────────────────
def spy_return_for(from_date: date, to_date: date) -> tuple[float, float, float]:
    ep = get_close("SPY", from_date)
    xp = get_close("SPY", to_date)
    if ep and xp:
        return ep, xp, (xp - ep) / ep * 100
    return 0.0, 0.0, 0.0

spy_ep, spy_xp, spy_12m = spy_return_for(ENTRY, EXIT)

vix_df = _pc.get("^VIX")
def vix_on(d: date) -> float:
    if vix_df is None:
        return 20.0
    rows = vix_df[vix_df.index.date <= d]["Close"].dropna()
    return float(rows.iloc[-1]) if not rows.empty else 20.0

vix_entry = vix_on(ENTRY)
vix_exit  = vix_on(EXIT)


# ──────────────────────────────────────────────────────────────────────────────
# Portfolio class
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Pos:
    ticker: str
    shares: float
    entry_price: float
    entry_date: date
    cost: float

class Portfolio:
    def __init__(self, name: str):
        self.name    = name
        self.cash    = float(CAPITAL)
        self.held: dict[str, Pos] = {}
        self.log: list[dict] = []
        self.n_sells = 0
        self.total_transaction_costs = 0.0

    def buy(self, ticker: str, price: float, amount: float, on: date):
        tc = round(amount * TRANSACTION_COST, 2)
        self.total_transaction_costs += tc
        self.cash -= tc          # friction paid before acquiring shares
        s = amount / price
        self.held[ticker] = Pos(ticker, s, price, on, amount)
        self.cash -= amount
        self.log.append({"date": on, "act": "BUY", "ticker": ticker,
                         "price": price, "amount": amount, "tc": tc})

    def sell(self, ticker: str, price: float, on: date) -> tuple[float, float]:
        pos = self.held.pop(ticker)
        gross = pos.shares * price
        tc = round(gross * TRANSACTION_COST, 2)
        self.total_transaction_costs += tc
        proceeds = gross - tc    # net proceeds after sell-side friction
        pnl = proceeds - pos.cost
        ret = pnl / pos.cost * 100
        self.cash += proceeds
        self.n_sells += 1
        self.log.append({"date": on, "act": "SELL", "ticker": ticker,
                         "price": price, "proceeds": proceeds, "pnl": pnl,
                         "return_pct": ret, "days_held": (on - pos.entry_date).days})
        return proceeds, ret

    def value(self, as_of: date) -> float:
        v = self.cash
        for pos in self.held.values():
            p = get_close(pos.ticker, as_of) or pos.entry_price
            v += pos.shares * p
        return v

    def rebalance(self, rebal_date: date, ranked: list[dict],
                  cutoff: int, target_n: int, per_pos: float,
                  min_hold: int = MIN_HOLD) -> tuple[list, list]:
        rank_map = {r["ticker"]: i + 1 for i, r in enumerate(ranked)}

        # Sell eligible positions that dropped below rank cutoff
        to_sell = [
            t for t, pos in self.held.items()
            if (rebal_date - pos.entry_date).days >= min_hold
            and rank_map.get(t, 9999) > cutoff
        ]
        sold_info = []
        for t in to_sell:
            p = get_close(t, rebal_date)
            if p:
                _, ret = self.sell(t, p, rebal_date)
                sold_info.append((t, rank_map.get(t, 9999), ret))

        # Buy top-ranked replacements (concentration-capped)
        held_set  = set(self.held.keys())
        slots     = target_n - len(self.held)
        capped    = apply_concentration_cap([r["ticker"] for r in ranked])
        cands     = [t for t in capped if t not in held_set]
        bought_info = []

        for t in cands[:slots]:
            p = get_close(t, rebal_date)
            alloc = min(per_pos, self.cash)
            if p and alloc >= 50:
                self.buy(t, p, alloc, rebal_date)
                bought_info.append((t, rank_map.get(t, 9999)))

        return sold_info, bought_info

    def finalize(self) -> dict:
        """Sell all held positions at EXIT and compute final stats."""
        pos_results = []
        for ticker, pos in list(self.held.items()):
            p = get_close(ticker, EXIT)
            if p:
                _, ret = self.sell(ticker, p, EXIT)
                pos_results.append({
                    "ticker":      ticker,
                    "entry_date":  pos.entry_date,
                    "entry_price": pos.entry_price,
                    "exit_price":  p,
                    "cost":        pos.cost,
                    "return_pct":  ret,
                    "pnl":         pos.cost * ret / 100,
                })
        final_val   = self.cash
        total_ret   = (final_val - CAPITAL) / CAPITAL * 100
        rets        = [p["return_pct"] for p in pos_results]
        return {
            "final_value":             final_val,
            "total_return":            total_ret,
            "total_pnl":               final_val - CAPITAL,
            "total_transaction_costs": self.total_transaction_costs,
            "positions":               sorted(pos_results, key=lambda x: x["return_pct"], reverse=True),
            "n":                       len(pos_results),
            "wins":                    sum(1 for r in rets if r > 0),
            "win_rate":                sum(1 for r in rets if r > 0) / max(len(rets), 1),
            "median_ret":              statistics.median(rets) if rets else 0,
            "best":                    max(pos_results, key=lambda x: x["return_pct"], default={}),
            "worst":                   min(pos_results, key=lambda x: x["return_pct"], default={}),
            "n_sells":                 self.n_sells,
        }


# ──────────────────────────────────────────────────────────────────────────────
# Build initial capped universe
# ──────────────────────────────────────────────────────────────────────────────
capped_initial = set(apply_concentration_cap([r["ticker"] for r in initial]))
initial_capped = [r for r in initial if r["ticker"] in capped_initial]


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 1: 100 stocks, $1,000 each equal weight
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'=' * 70}")
print(f"  SCENARIO 1: Top 100 | $1,000 each | equal weight | quarterly rebal")
print(f"{'=' * 70}")

p1 = Portfolio("S1")
PER1 = CAPITAL / N1

top100 = initial_capped[:N1]
for r in top100:
    pr = get_close(r["ticker"], ENTRY)
    if pr:
        p1.buy(r["ticker"], pr, PER1, ENTRY)

print(f"  Entered: {len(p1.held)} positions  | Cash: ${p1.cash:,.0f}")

for rd in REBAL:
    ranked_r = scores[rd]
    sold, bought = p1.rebalance(rd, ranked_r, CUT1, N1, PER1)
    val = p1.value(rd)
    spy_r = (get_close("SPY", rd) - spy_ep) / spy_ep * 100
    vix_r = vix_on(rd)
    print(f"\n  Rebal {rd}  |  SPY {spy_r:+.1f}%  VIX {vix_r:.1f}  |  Sold {len(sold)}  Bought {len(bought)}  |  Port ${val:,.0f}")
    for t, rank, ret in sold[:8]:
        print(f"    SELL {t:<6} rank #{rank:>3}  {ret:>+6.1f}%")
    for t, rank in bought[:8]:
        print(f"    BUY  {t:<6} rank #{rank:>3}")


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 2: 20 stocks, $5,000 each equal weight
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'=' * 70}")
print(f"  SCENARIO 2: Top 20 | $5,000 each | equal weight | quarterly rebal")
print(f"{'=' * 70}")

p2 = Portfolio("S2")
PER2 = CAPITAL / N2

top20 = initial_capped[:N2]
for r in top20:
    pr = get_close(r["ticker"], ENTRY)
    if pr:
        p2.buy(r["ticker"], pr, PER2, ENTRY)

print(f"  Entered: {len(p2.held)} positions  | Cash: ${p2.cash:,.0f}")
print(f"  Initial top 20:")
print(f"  {'#':>3}  {'Ticker':<6}  {'Score':>6}  {'Mo':>5}  {'Qu':>5}  {'C':>5}  {'E':>5}")
for i, r in enumerate(top20, 1):
    print(f"  {i:>3}  {r['ticker']:<6}  {r['score']:>6.3f}  {r['momentum']:>5.2f}  "
          f"{r['quality']:>5.2f}  {r['congress']:>5.2f}  {r['earnings']:>5.2f}")

for rd in REBAL:
    ranked_r = scores[rd]
    sold, bought = p2.rebalance(rd, ranked_r, CUT2, N2, PER2)
    val = p2.value(rd)
    spy_r = (get_close("SPY", rd) - spy_ep) / spy_ep * 100
    vix_r = vix_on(rd)
    print(f"\n  Rebal {rd}  |  SPY {spy_r:+.1f}%  VIX {vix_r:.1f}  |  Sold {len(sold)}  Bought {len(bought)}  |  Port ${val:,.0f}")
    for t, rank, ret in sold:
        print(f"    SELL {t:<6} rank #{rank:>3}  {ret:>+6.1f}%")
    for t, rank in bought:
        print(f"    BUY  {t:<6} rank #{rank:>3}")


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 3: 20 stocks, signal-strength weighted
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'=' * 70}")
print(f"  SCENARIO 3: Top 20 | signal-weighted | quarterly rebal")
print(f"{'=' * 70}")

p3 = Portfolio("S3")
PER3 = CAPITAL / N3   # equal for rebalancing new entries

top20_s3 = initial_capped[:N3]
total_score = sum(r["score"] for r in top20_s3)
allocs = {r["ticker"]: r["score"] / total_score * CAPITAL for r in top20_s3}

print(f"  Allocation range: ${min(allocs.values()):,.0f} - ${max(allocs.values()):,.0f}")
print(f"  {'#':>3}  {'Ticker':<6}  {'Score':>6}  {'Alloc':>9}  {'Weight':>7}")
for i, r in enumerate(top20_s3, 1):
    a = allocs[r["ticker"]]
    print(f"  {i:>3}  {r['ticker']:<6}  {r['score']:>6.3f}  ${a:>8,.0f}  {a/CAPITAL:>6.1%}")

for r in top20_s3:
    pr = get_close(r["ticker"], ENTRY)
    if pr:
        p3.buy(r["ticker"], pr, allocs[r["ticker"]], ENTRY)

print(f"\n  Entered: {len(p3.held)} positions  | Cash: ${p3.cash:,.0f}")

for rd in REBAL:
    ranked_r = scores[rd]
    sold, bought = p3.rebalance(rd, ranked_r, CUT3, N3, PER3)
    val = p3.value(rd)
    spy_r = (get_close("SPY", rd) - spy_ep) / spy_ep * 100
    vix_r = vix_on(rd)
    print(f"\n  Rebal {rd}  |  SPY {spy_r:+.1f}%  VIX {vix_r:.1f}  |  Sold {len(sold)}  Bought {len(bought)}  |  Port ${val:,.0f}")
    for t, rank, ret in sold:
        print(f"    SELL {t:<6} rank #{rank:>3}  {ret:>+6.1f}%")
    for t, rank in bought:
        print(f"    BUY  {t:<6} rank #{rank:>3}")


# ──────────────────────────────────────────────────────────────────────────────
# SCENARIO 4: 20 stocks, monthly rebalancing, no minimum hold
# ──────────────────────────────────────────────────────────────────────────────
print(f"\n{'=' * 70}")
print(f"  SCENARIO 4: Top 20 | $5,000 each | MONTHLY rebal | no min hold")
print(f"  (only rule: no same-day trading)")
print(f"{'=' * 70}")

p4 = Portfolio("S4")
PER4 = CAPITAL / N4

top20_s4 = initial_capped[:N4]
for r in top20_s4:
    pr = get_close(r["ticker"], ENTRY)
    if pr:
        p4.buy(r["ticker"], pr, PER4, ENTRY)

print(f"  Entered: {len(p4.held)} positions  | Cash: ${p4.cash:,.0f}")

for rd in S4_REBAL:
    ranked_r = scores[rd]
    sold, bought = p4.rebalance(rd, ranked_r, CUT4, N4, PER4, min_hold=MIN_HOLD_S4)
    val = p4.value(rd)
    spy_r = (get_close("SPY", rd) - spy_ep) / spy_ep * 100
    vix_r = vix_on(rd)
    print(f"\n  Rebal {rd}  |  SPY {spy_r:+.1f}%  VIX {vix_r:.1f}  |  Sold {len(sold)}  Bought {len(bought)}  |  Port ${val:,.0f}")
    for t, rank, ret in sold[:6]:
        print(f"    SELL {t:<6} rank #{rank:>3}  {ret:>+6.1f}%")
    for t, rank in bought[:6]:
        print(f"    BUY  {t:<6} rank #{rank:>3}")


# ──────────────────────────────────────────────────────────────────────────────
# Finalize all portfolios
# ──────────────────────────────────────────────────────────────────────────────
r1 = p1.finalize()
r2 = p2.finalize()
r3 = p3.finalize()
r4 = p4.finalize()


# ──────────────────────────────────────────────────────────────────────────────
# Spearman rank correlation (initial scores vs 12-month actual returns)
# ──────────────────────────────────────────────────────────────────────────────
universe_rets = []
for r in initial:
    ep = get_close(r["ticker"], ENTRY)
    xp = get_close(r["ticker"], EXIT)
    if ep and xp:
        universe_rets.append({"ticker": r["ticker"], "score": r["score"],
                              "ret12m": (xp - ep) / ep * 100})

universe_rets.sort(key=lambda x: -x["score"])  # best score first
n = len(universe_rets)
score_ranks  = list(range(1, n + 1))
ret_sorted   = sorted(range(n), key=lambda i: -universe_rets[i]["ret12m"])
return_ranks = [0] * n
for rank, idx in enumerate(ret_sorted, 1):
    return_ranks[idx] = rank

d2 = sum((sr - rr) ** 2 for sr, rr in zip(score_ranks, return_ranks))
spearman = 1 - 6 * d2 / (n * (n ** 2 - 1)) if n > 1 else 0.0

# Quintile breakdown
q_size = n // 5
print(f"\n{'=' * 70}")
print(f"  FULL UNIVERSE RANKING QUALITY (initial Jun 2025 scores vs 12m actual return)")
print(f"{'=' * 70}")
for q in range(5):
    sl = universe_rets[q * q_size: (q + 1) * q_size]
    if not sl:
        continue
    avg_sc  = sum(x["score"] for x in sl) / len(sl)
    avg_ret = sum(x["ret12m"] for x in sl) / len(sl)
    wr      = sum(1 for x in sl if x["ret12m"] > 0) / len(sl)
    lbl     = f"Q{q+1} (top 20)" if q == 0 else (f"Q{q+1} (bottom)" if q == 4 else f"Q{q+1}         ")
    print(f"  {lbl}: score={avg_sc:.3f}  avg return={avg_ret:>+6.2f}%  win={wr:.0%}")
print(f"\n  Spearman rank corr: {spearman:>+.3f}")
print(f"  (>0 = model ranks winners higher | target > +0.10)")


# ──────────────────────────────────────────────────────────────────────────────
# FINAL REPORT
# ──────────────────────────────────────────────────────────────────────────────
holding_days = (EXIT - ENTRY).days   # 361 days ≈ 1 year

print(f"\n{'=' * 70}")
print(f"  FINAL REPORT: Jun 2, 2025 -> May 29, 2026  ({holding_days} days)")
print(f"{'=' * 70}")
print(f"\n  MARKET CONTEXT")
print(f"  VIX on entry (Jun 2, 2025) : {vix_entry:.1f}")
print(f"  VIX on exit  (May 29, 2026): {vix_exit:.1f}")
print(f"  SPY entry                  : ${spy_ep:.2f}")
print(f"  SPY exit                   : ${spy_xp:.2f}")
print(f"  SPY 12-month return        : {spy_12m:>+.2f}%  (this IS the CAGR)")

# Annualize (actual days)
yr = holding_days / 365.0

def ann(ret_pct):
    return ((1 + ret_pct / 100) ** (1 / yr) - 1) * 100

print(f"\n{'=' * 70}")
print(f"  COMPARATIVE SUMMARY")
print(f"{'=' * 70}")
hdr = f"  {'Metric':<30} {'S1:100-Eq':>11} {'S2:20-Eq':>11} {'S3:20-Wt':>11} {'S4:Monthly':>11} {'SPY':>9}"
print(hdr)
print(f"  {'-' * 83}")

def row(label, v1, v2, v3, v4, vs, fmt="{:>+.2f}%"):
    def f(v): return fmt.format(v) if v is not None else "  N/A"
    print(f"  {label:<30} {f(v1):>11} {f(v2):>11} {f(v3):>11} {f(v4):>11} {f(vs):>9}")

row("Final value ($)",
    r1["final_value"], r2["final_value"], r3["final_value"], r4["final_value"], None,
    fmt="${:>,.0f}")
row("12-month return (= CAGR)",
    r1["total_return"], r2["total_return"], r3["total_return"], r4["total_return"], spy_12m)
row("Alpha vs SPY",
    r1["total_return"] - spy_12m, r2["total_return"] - spy_12m,
    r3["total_return"] - spy_12m, r4["total_return"] - spy_12m, 0.0)
row("Win rate",
    r1["win_rate"] * 100, r2["win_rate"] * 100, r3["win_rate"] * 100,
    r4["win_rate"] * 100, None, fmt="{:>+.1f}%")
row("Median position return",
    r1["median_ret"], r2["median_ret"], r3["median_ret"], r4["median_ret"], None)
row("Rebalancing sells (total)",
    r1["n_sells"], r2["n_sells"], r3["n_sells"], r4["n_sells"], None, fmt="{:>.0f}  ")
row("Transaction costs ($)",
    r1["total_transaction_costs"], r2["total_transaction_costs"],
    r3["total_transaction_costs"], r4["total_transaction_costs"], None, fmt="${:>,.0f}")

print(f"\n  Best / Worst picks:")
for name, res in [("S1", r1), ("S2", r2), ("S3", r3), ("S4", r4)]:
    b = res["best"]
    w = res["worst"]
    print(f"  {name}  Best:  {b.get('ticker','?'):<6} {b.get('return_pct',0):>+7.1f}%"
          f"   Worst: {w.get('ticker','?'):<6} {w.get('return_pct',0):>+7.1f}%")

# ── Detailed position lists for S2, S3, S4 ───────────────────────────────────
for label, res in [("SCENARIO 2 — 20 Equal ($5,000 each)", r2),
                    ("SCENARIO 3 — 20 Signal-Weighted", r3),
                    ("SCENARIO 4 — Monthly Rebal, No Min Hold", r4)]:
    print(f"\n{'=' * 70}")
    print(f"  {label}  |  FINAL POSITIONS")
    print(f"{'=' * 70}")
    print(f"  {'#':>3}  {'Ticker':<6}  {'EntryDate':<12}  {'Entry$':>7}  {'Exit$':>7}  "
          f"{'Return':>8}  {'P&L':>8}  {'Cost$':>8}")
    for i, p in enumerate(res["positions"], 1):
        marker = "+" if p["return_pct"] > spy_12m else " "
        print(f"  {i:>3}  {p['ticker']:<6}  {str(p['entry_date']):<12}  "
              f"${p['entry_price']:>6.2f}  ${p['exit_price']:>6.2f}  "
              f"{p['return_pct']:>+7.2f}%{marker} ${p['pnl']:>+7,.0f}  ${p['cost']:>7,.0f}")
    print(f"  Note: + = beat SPY ({spy_12m:+.2f}%)")

# ── Portfolio value progression ────────────────────────────────────────────────
print(f"\n{'=' * 70}")
print(f"  PORTFOLIO VALUE PROGRESSION")
print(f"{'=' * 70}")
print(f"  {'Date':<14} {'S1':>10} {'S2':>10} {'S3':>10} {'S4':>10} {'SPY':>10}")
for d in sorted(set([ENTRY] + REBAL + S4_REBAL + [EXIT])):
    v1 = CAPITAL if d == ENTRY else r1["final_value"] if d == EXIT else p1.value(d)
    v2 = CAPITAL if d == ENTRY else r2["final_value"] if d == EXIT else p2.value(d)
    v3 = CAPITAL if d == ENTRY else r3["final_value"] if d == EXIT else p3.value(d)
    v4 = CAPITAL if d == ENTRY else r4["final_value"] if d == EXIT else p4.value(d)
    spy_v = CAPITAL * (get_close("SPY", d) / spy_ep) if spy_ep else CAPITAL
    print(f"  {str(d):<14} ${v1:>8,.0f}  ${v2:>8,.0f}  ${v3:>8,.0f}  ${v4:>8,.0f}  ${spy_v:>8,.0f}")


# ──────────────────────────────────────────────────────────────────────────────
# VERDICT
# ──────────────────────────────────────────────────────────────────────────────
TARGET = 25.0
print(f"\n{'=' * 70}")
print(f"  VERDICT  (target CAGR: {TARGET}% | fired if < SPY {spy_12m:+.2f}%)")
print(f"{'=' * 70}")
for name, res in [("S1 (100 equal)", r1), ("S2 (20 equal)", r2),
                  ("S3 (20 weighted)", r3), ("S4 (monthly rebal)", r4)]:
    cagr = res["total_return"]  # already 12 months = CAGR
    if cagr >= TARGET:
        verdict = "BONUS EARNED  -- beat 25% CAGR target"
    elif cagr > spy_12m:
        verdict = f"Employed  -- beats SPY by {cagr - spy_12m:+.2f}% but misses 25% CAGR"
    else:
        verdict = f"FIRED  -- underperforms SPY by {cagr - spy_12m:.2f}%"
    print(f"  {name:<20}  CAGR {cagr:>+7.2f}%  ->  {verdict}")


# ──────────────────────────────────────────────────────────────────────────────
# ASSUMPTIONS & WHAT WE'RE MISSING
# ──────────────────────────────────────────────────────────────────────────────
print(f"""
{'=' * 70}
  ASSUMPTIONS (what differs from a real investment)
{'=' * 70}

  EXECUTION:
  1. Entry/exit at adjusted closing price on the signal date
     (real-world: bid-ask spread ~0.01-0.05% per side; large orders move price)
  2. Full position filled at close — no partial fills, no market impact
  3. Transaction costs: MODELED at 0.1% per side (0.2% round-trip)
     Covers bid-ask spread + minor market impact. Commission is $0 at retail brokers.
  4. Dividends: INCLUDED via auto_adjust=True in yfinance price data
  5. Cash earns 0% between rebalances (conservative; real T-bills ~4-5% in 2025)

  SIGNAL DATA (look-ahead limitations):
  6. Quality scores (ROE + gross margin): computed from TODAY's TTM financials
     Actual June 2025 financials could differ by 1-2 quarters. For stable large-
     caps this is a minor bias; more impactful for fast-growing or cyclical names.
  7. Congressional trading data: 180-day lookback from TODAY, not June 2025
     Trades between Dec 2024 and May 2025 that would have informed the signal
     may not match what Quiver returns for current 180-day window.
  8. News scores: Defaulted to 0.5 (neutral) — NewsAPI free tier rate-limits
     at this volume. Both the news layer (10% weight) and trump modifier (part
     of congress 15% weight) are neutralized.
  9. Earnings beat rate: Date-filtered — only EPS quarters completed BEFORE each
     signal date are included. Last 8 quarters max. No look-ahead bias.
     PEAD modifier still disabled (next earnings date unknowable for historical signal).
  10. Rebalancing assumes same-day fill at closing price on checkpoint date.

{'=' * 70}
  WHAT WE'RE NOT MODELING (known gaps)
{'=' * 70}

  1. INTRA-QUARTER EARNINGS SURPRISES: EPS beat-rate is now date-filtered, but the
     model can't react to a surprise until the next rebalance. A big beat or miss
     (LLY, NVDA, etc.) within a quarter impacts the 3-month return window before
     we can rotate.

  2. MACRO REGIME SHIFTS: This period included the tariff shock of Jan-Apr 2026,
     significant VIX spikes, and potential rate decisions. The model holds fixed
     scores between rebalances — it can't react to intra-quarter news.

  3. SECTOR ROTATION: No dynamic sector tilts based on macro environment.
     The sector concentration cap is static (max 2 per cluster).

  4. SHORT INTEREST / SQUEEZE RISK: High short interest names (RIVN, MRNA, etc.)
     can move 50%+ on short squeezes — not captured.

  5. M&A ACTIVITY: Unexpected deals (acquisitions, spinoffs, delistings) during
     the period are not predicted. Affects price continuity.

  6. ANALYST ESTIMATE REVISIONS: EPS estimate cuts/raises move stocks 5-15%
     without a formal earnings event — not in the model.

  7. TAX OPTIMIZATION: Short-term vs long-term cap gains treatment not modeled.
     Positions held < 1 year taxed at higher rates; affects after-tax return.

  8. POSITION-LEVEL VOLATILITY TARGETING: Using flat equal allocation for S1/S2.
     A vol-targeting approach (like position_sizing.py) would reduce drawdown
     on high-vol positions but reduce return on low-vol winners.

  9. REBALANCING COSTS: NOW MODELED at 0.1% per side. See transaction costs row
     in the summary above for actual drag per scenario.

  10. LIQUIDITY CONSTRAINTS: Assumes unlimited liquidity at close price. For
      small-cap or low-volume names, large orders move the price.
""")
print(f"{'=' * 70}\n")
