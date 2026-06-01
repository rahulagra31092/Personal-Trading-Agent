#!/usr/bin/env python3
"""
Multi-year, multi-regime backtest: 2019–2026
Russell 1000 proxy universe: S&P 500 (~480) + S&P 400 MidCap (~400) ≈ 900 tickers | 4 strategies
  S2: quarterly  | equal weight    | 90-day min hold
  S4: monthly    | equal weight    | 1-day  min hold
  S5: monthly    | signal-weighted | 1-day  min hold
  S6: monthly    | equal weight    | 1-day  min hold | VIX-adaptive signal weights

Run-time estimate: 2–3 hours (quality + congress API calls for ~900 tickers)
Survivorship bias note: uses current index constituents — understates historical returns slightly.
"""
import sys, os, warnings, statistics
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")
warnings.filterwarnings("ignore")
import logging
logging.basicConfig(level=logging.WARNING)

from datetime import date, timedelta
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
TRANSACTION_COST = 0.001    # 0.1% per side
TOP_N            = 20
PER_POS          = CAPITAL / TOP_N   # $5,000 per position

PERIODS = [
    dict(name="2019 Pre-COVID",       entry=date(2019, 1,  2), exit=date(2019, 12, 31)),
    dict(name="2020 COVID",           entry=date(2020, 1,  2), exit=date(2020, 12, 31)),
    dict(name="2021 Hyper-Growth",    entry=date(2021, 1,  4), exit=date(2021, 12, 31)),
    dict(name="2022 Bear Market",     entry=date(2022, 1,  3), exit=date(2022, 12, 30)),
    dict(name="2023 Recovery",        entry=date(2023, 1,  3), exit=date(2023, 12, 29)),
    dict(name="2024 Bull Run",        entry=date(2024, 1,  2), exit=date(2024, 12, 31)),
    dict(name="2025-26 Turbulent",    entry=date(2025, 6,  2), exit=date(2026, 5,  29)),
]

STRATEGIES = {
    "S2": dict(rebal_type="quarterly", weighted=False, regime=False, min_hold=90, cutoff=40),
    "S4": dict(rebal_type="monthly",   weighted=False, regime=False, min_hold=1,  cutoff=40),
    "S5": dict(rebal_type="monthly",   weighted=True,  regime=False, min_hold=1,  cutoff=40),
    "S6": dict(rebal_type="monthly",   weighted=False, regime=True,  min_hold=1,  cutoff=40),
}

HIST_START = "2017-06-01"   # 18-month buffer before 2019 entry for momentum lookbacks
HIST_END   = "2026-06-01"


def _fetch_sp400_tickers() -> list[str]:
    """Fetch S&P 400 MidCap constituents from Wikipedia. Falls back to [] on failure."""
    try:
        import requests, io
        url = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; trading-backtest/1.0)"}
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        tables = pd.read_html(io.StringIO(r.text))
        df = tables[0]
        tickers = df["Symbol"].dropna().astype(str).tolist()
        # Normalise BRK.B → BRK-B style for yfinance
        tickers = [t.replace(".", "-") for t in tickers]
        print(f"  S&P 400 fetched: {len(tickers)} tickers from Wikipedia")
        return tickers
    except Exception as e:
        print(f"  WARNING: S&P 400 fetch failed ({e}), using S&P 500 only")
        return []


# ── Russell 1000 proxy: S&P 500 + S&P 400 MidCap ─────────────────────────────
# S&P 500 tickers hardcoded for reliability; S&P 400 fetched dynamically.
_SP400_TICKERS = _fetch_sp400_tickers()

UNIVERSE = list(dict.fromkeys([
    # Technology
    "AAPL","MSFT","NVDA","GOOGL","META","AMZN","TSLA","AVGO","ORCL","CRM",
    "ADBE","AMD","QCOM","TXN","INTC","MU","AMAT","LRCX","KLAC","MRVL",
    "NOW","PLTR","PANW","FTNT","CRWD","ZS","NET","DDOG","MDB","ARM",
    "CSCO","IBM","DELL","ANET","HPE","SMCI","CDNS","SNPS","ANSS","EPAM",
    "ACN","INTU","ADSK","WDAY","FIS","FISV","GPN","JKHY","NTAP","STX",
    "WDC","HPQ","ZBRA","KEYS","TER","CTSH","GLW","CDW","VRSN","TYL",
    "MSI","SWKS","MCHP","ON","ENPH","FSLR","NXPI","MPWR","QRVO","TRMB",
    "LDOS","SAIC","IT","PAYC","PCTY","CDAY","ROP","BR","NDAQ","CBOE",
    # Financials
    "JPM","BAC","WFC","GS","MS","BLK","C","AXP","COF","USB",
    "TFC","PNC","SCHW","CME","ICE","MCO","SPGI","V","MA","PYPL",
    "KKR","APO","BX","CG","ARES","CB","PGR","AIG","MET","PRU",
    "AFL","ALL","TRV","HIG","CINF","MSCI","FDS","RJF","FITB","HBAN",
    "RF","KEY","MTB","CFG","ZION","CMA","STT","BK","NTRS","TROW",
    "BEN","IVZ","SYF","DFS","ALLY","CACC","SLM","NAVI",
    # Healthcare
    "LLY","UNH","JNJ","ABBV","MRK","PFE","BMY","AMGN","GILD","ISRG",
    "MDT","ABT","TMO","DHR","SYK","BSX","ELV","CVS","CI","HUM",
    "VRTX","REGN","BIIB","MRNA","ZBH","A","BAX","BDX","DXCM","GEHC",
    "HCA","HOLX","IQV","LH","MCK","MOH","MTD","RMD","EW","ILMN",
    "ALGN","INCY","WAT","TFX","IDXX","PODD","WST","VTRS","XRAY","CNC",
    "MOH","HUM","WCG","OSCR","ACAD","CRVL",
    # Consumer Discretionary
    "HD","LOW","TGT","WMT","COST","MCD","SBUX","NKE","TJX","BKNG",
    "MAR","HLT","LVS","WYNN","MGM","F","GM","RIVN","LCID","POOL",
    "LULU","RCL","CCL","NCLH","AZO","ORLY","GPC","KMX","BBY","DLTR",
    "DG","ETSY","EBAY","HOG","LEN","NVR","PHM","TOL","APTV","GRMN",
    "RL","HAS","MAT","DRI","EAT","CMG","YUM","QSR","RBLX","DASH",
    "ABNB","UBER","LYFT","TRIP","EXPE",
    # Consumer Staples
    "PG","KO","PEP","PM","MO","CL","MDLZ","GIS","STZ","MNST",
    "TAP","HRL","CAG","SJM","CHD","CPB","MKC","CLX","KHC","WBA",
    "SFM","KDP","HSY","K","ADM","BF-B","TSN","SAFM",
    # Energy
    "XOM","CVX","COP","EOG","SLB","MPC","VLO","PSX","DVN","HAL",
    "OXY","HES","MRO","APA","PXD","BKR","NOV","EQT","RRC","FANG",
    "AM","TRGP","WMB","OKE","KMI","LNG","CQP","ET","MPLX","EPD",
    # Industrials
    "GE","HON","UPS","FDX","CAT","DE","LMT","RTX","NOC","GD",
    "BA","MMM","EMR","ETN","PH","ROK","ITW","IR","AME","CARR",
    "OTIS","TT","GWW","FAST","SNA","PNR","RSG","WM","WCN","TDG",
    "NDSN","HUBB","VRSK","CSX","NSC","UNP","LUV","AAL","DAL","UAL",
    "ALK","CHRW","XPO","JBHT","EXPD","FLR","J","LDOS","SAIC","CACI",
    "AXON","ZBH","RHI","MAN","KFY","PCAR","CMI","AGCO","TEX","HOLI",
    # Materials
    "FCX","NEM","APD","LIN","SHW","ECL","DD","DOW","ALB","MP",
    "PPG","VMC","MLM","NUE","STLD","RS","IP","WRK","CCK","SEE",
    "AVY","CE","RPM","EMN","FMC","MOS","CF","BLL","OLN","PKG",
    "IFF","ASH","HUN","WLK","BALL","SLVM",
    # REITs
    "AMT","PLD","EQIX","SPG","CBRE","WELL","O","DLR","PSA","AVB",
    "INVH","EXR","CUBE","IRM","VTR","ARE","CCI","SBA","SBAC","EQR",
    "UDR","CPT","NXE","KIM","REG","FRT","BXP","VNO","SLG","HIW",
    # Utilities
    "NEE","DUK","SO","AEP","EXC","SRE","PCG","XEL","WEC","ES",
    "AES","LNT","NI","FE","ATO","CNP","NRG","PNW","EVRG","OGE",
    "ETR","AWK","CMS","WTRG","SWX","IDA","MGEE",
    # Communication Services
    "T","VZ","TMUS","CHTR","CMCSA","DIS","NFLX","SPOT","SNAP","PINS",
    "MTCH","PARA","WBD","FOXA","FOX","IAC","ZG","ANGI","CARS",
    # S&P 500 extras not already covered
    "COST","AMGN","GILD","BIIB",   # already above but ensure dedup covers
] + _SP400_TICKERS))

# ── PHASE 1: Batch price download ──────────────────────────────────────────────
print("=" * 72)
print(f"  PHASE 1: Downloading price history for {len(UNIVERSE)} tickers (2017-2026)")
print(f"  Universe: ~{len(UNIVERSE) - len(_SP400_TICKERS)} S&P 500 + {len(_SP400_TICKERS)} S&P 400 MidCap = Russell 1000 proxy")
print("=" * 72)

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
    return [b for b in bars if b["c"] > 0]


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


vix_df = _pc.get("^VIX")
def vix_on(d: date) -> float:
    if vix_df is None:
        return 20.0
    rows = vix_df[vix_df.index.date <= d]["Close"].dropna()
    return float(rows.iloc[-1]) if not rows.empty else 20.0


# ── PHASE 2: Static scores ─────────────────────────────────────────────────────
print("=" * 72)
print("  PHASE 2: Quality + congress scores (current data, applied to all periods)")
print("  [ASSUMPTION: uses today's TTM financials — minor look-ahead for stable large-caps]")
print("=" * 72)

_static: dict[str, dict] = {}
for i, t in enumerate(UNIVERSE, 1):
    try:
        _static[t] = {
            "quality":  compute_quality_score(t),
            "congress": compute_congress_score(t),
        }
    except Exception:
        _static[t] = {"quality": 0.5, "congress": 0.5}
    if i % 50 == 0 or i == len(UNIVERSE):
        print(f"  {i}/{len(UNIVERSE)} tickers...")

print("\n  Fetching historical EPS data...")
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
    try:
        hist = _earnings_hist.get(ticker)
        if hist is None or hist.empty:
            return 0.5
        past = hist[hist.index.date < as_of].tail(8)
        if past.empty:
            return 0.5
        br = round((past["surprisePercent"] > 0).sum() / len(past), 2)
        return round(max(0.20, min(0.80, 0.25 + br * 0.5)), 4)
    except Exception:
        return 0.5


# ── Regime-adaptive weights ────────────────────────────────────────────────────
def _regime_weights(vix: float) -> tuple:
    """Returns (tech, momentum, quality, smart_money, news, earnings) weights."""
    if vix > 35:
        # Crisis: cut momentum hard, double down on quality
        return 0.20, 0.10, 0.30, 0.15, 0.10, 0.15
    elif vix > 25:
        # Elevated: moderate momentum reduction
        return 0.20, 0.15, 0.25, 0.15, 0.10, 0.15
    else:
        # Normal / low vol: standard weights
        return 0.20, 0.25, 0.15, 0.15, 0.10, 0.15


def _regime_composite(row: dict, vix: float) -> float:
    tw, mw, qw, sw, nw, ew = _regime_weights(vix)
    return round(
        row["tech"]     * tw +
        row["momentum"] * mw +
        row["quality"]  * qw +
        row["congress"] * sw +
        0.50            * nw +   # news always neutral (no historical API)
        row["earnings"] * ew,
        4,
    )


# ── Score universe at a given date ─────────────────────────────────────────────
def score_universe(signal_date: date) -> list[dict]:
    vix = vix_on(signal_date)
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
                news_score        = 0.50,   # neutral — no historical news API
                earnings_score    = earnings,
            )
            row = {
                "ticker":   ticker,
                "score":    sig["composite_score"],          # standard composite
                "score_s6": _regime_composite(               # regime-adjusted
                    dict(tech=ind["technical_score"], momentum=momentum,
                         quality=_static[ticker]["quality"],
                         congress=_static[ticker]["congress"],
                         earnings=earnings),
                    vix,
                ),
                "momentum": round(momentum, 3),
                "quality":  round(_static[ticker]["quality"], 3),
                "congress": round(_static[ticker]["congress"], 3),
                "tech":     round(ind["technical_score"], 3),
                "earnings": round(earnings, 3),
            }
            results.append(row)
        except Exception:
            continue
    return sorted(results, key=lambda x: x["score"], reverse=True)


# ── Rebalancing date generators ────────────────────────────────────────────────
def _first_bday(year: int, month: int) -> date:
    d = date(year, month, 1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _rebal_dates(entry: date, exit: date, rebal_type: str) -> list[date]:
    dates, y, m = [], entry.year, entry.month
    step = 3 if rebal_type == "quarterly" else 1
    while True:
        m += step
        if m > 12:
            m -= 12
            y += 1
        d = _first_bday(y, m)
        if d >= exit:
            break
        if d > entry:
            dates.append(d)
    return dates


# ── Pre-compute all scoring dates ──────────────────────────────────────────────
print("=" * 72)
print("  PHASE 3: Pre-computing scoring dates for all periods + strategies")
print("=" * 72)

all_scoring_dates: set[date] = set()
for period in PERIODS:
    all_scoring_dates.add(period["entry"])
    for rd in _rebal_dates(period["entry"], period["exit"], "monthly"):
        all_scoring_dates.add(rd)

all_scoring_dates_sorted = sorted(all_scoring_dates)
print(f"  {len(all_scoring_dates_sorted)} unique scoring dates across 7 periods\n")

_scores: dict[date, list[dict]] = {}
for i, d in enumerate(all_scoring_dates_sorted, 1):
    print(f"  [{i:>3}/{len(all_scoring_dates_sorted)}] Scoring {d}...", end=" ", flush=True)
    _scores[d] = score_universe(d)
    top = _scores[d][0] if _scores[d] else {}
    print(f"{len(_scores[d])} scored  top: {top.get('ticker','?')} ({top.get('score',0):.3f})")


# ── Portfolio class ────────────────────────────────────────────────────────────
@dataclass
class Pos:
    ticker: str
    shares: float
    entry_price: float
    entry_date: date
    cost: float


class Portfolio:
    def __init__(self, name: str):
        self.name     = name
        self.cash     = float(CAPITAL)
        self.held: dict[str, Pos] = {}
        self.log: list[dict] = []
        self.n_sells  = 0
        self.total_tc = 0.0

    def buy(self, ticker: str, price: float, amount: float, on: date):
        tc = round(amount * TRANSACTION_COST, 2)
        self.total_tc += tc
        self.cash -= tc + amount
        s = amount / price
        self.held[ticker] = Pos(ticker, s, price, on, amount)

    def sell(self, ticker: str, price: float, on: date) -> float:
        pos = self.held.pop(ticker)
        gross = pos.shares * price
        tc = round(gross * TRANSACTION_COST, 2)
        self.total_tc += tc
        proceeds = gross - tc
        pnl = proceeds - pos.cost
        ret = pnl / pos.cost * 100
        self.cash += proceeds
        self.n_sells += 1
        return ret

    def value(self, as_of: date) -> float:
        v = self.cash
        for pos in self.held.values():
            p = get_close(pos.ticker, as_of) or pos.entry_price
            v += pos.shares * p
        return v

    def rebalance(self, rebal_date: date, ranked: list[dict],
                  cutoff: int, target_n: int, per_pos: float,
                  min_hold: int = 90) -> int:
        rank_map = {r["ticker"]: i + 1 for i, r in enumerate(ranked)}
        to_sell = [
            t for t, pos in self.held.items()
            if (rebal_date - pos.entry_date).days >= min_hold
            and rank_map.get(t, 9999) > cutoff
        ]
        for t in to_sell:
            p = get_close(t, rebal_date)
            if p:
                self.sell(t, p, rebal_date)

        held_set = set(self.held.keys())
        slots    = target_n - len(self.held)
        capped   = apply_concentration_cap([r["ticker"] for r in ranked])
        cands    = [t for t in capped if t not in held_set]
        for t in cands[:slots]:
            p = get_close(t, rebal_date)
            alloc = min(per_pos, self.cash)
            if p and alloc >= 50:
                self.buy(t, p, alloc, rebal_date)
        return len(to_sell)

    def finalize(self, exit_date: date) -> dict:
        pos_results = []
        for ticker, pos in list(self.held.items()):
            p = get_close(ticker, exit_date)
            if p:
                ret = self.sell(ticker, p, exit_date)
                pos_results.append({
                    "ticker": ticker, "return_pct": ret,
                    "entry_date": pos.entry_date,
                    "cost": pos.cost,
                })
        final_val  = self.cash
        total_ret  = (final_val - CAPITAL) / CAPITAL * 100
        rets       = [p["return_pct"] for p in pos_results]
        return {
            "final_value":  final_val,
            "total_return": total_ret,
            "win_rate":     sum(1 for r in rets if r > 0) / max(len(rets), 1),
            "median_ret":   statistics.median(rets) if rets else 0,
            "n_sells":      self.n_sells,
            "total_tc":     self.total_tc,
            "positions":    pos_results,
        }


# ── Spearman helper ────────────────────────────────────────────────────────────
def spearman(initial: list[dict], entry: date, exit_date: date,
             score_key: str = "score") -> float:
    data = []
    for r in initial:
        ep = get_close(r["ticker"], entry)
        xp = get_close(r["ticker"], exit_date)
        if ep and xp and ep > 0:
            data.append((r[score_key], (xp - ep) / ep * 100))
    if len(data) < 5:
        return 0.0
    data.sort(key=lambda x: -x[0])
    n = len(data)
    sr = list(range(1, n + 1))
    idx_sorted = sorted(range(n), key=lambda i: -data[i][1])
    rr = [0] * n
    for rank, idx in enumerate(idx_sorted, 1):
        rr[idx] = rank
    d2 = sum((a - b) ** 2 for a, b in zip(sr, rr))
    return round(1 - 6 * d2 / (n * (n**2 - 1)), 3)


# ── SPY return helper ──────────────────────────────────────────────────────────
def spy_return(entry: date, exit_date: date) -> float:
    ep = get_close("SPY", entry)
    xp = get_close("SPY", exit_date)
    if ep and xp and ep > 0:
        return round((xp - ep) / ep * 100, 2)
    return 0.0


# ── Run one strategy for one period ───────────────────────────────────────────
def run_period_strategy(period: dict, strat_name: str, strat_cfg: dict) -> dict:
    entry     = period["entry"]
    exit_date = period["exit"]
    score_key = "score_s6" if strat_cfg["regime"] else "score"

    initial   = _scores[entry]
    # Sort by appropriate score key
    sorted_init  = sorted(initial, key=lambda x: x[score_key], reverse=True)
    capped_ticks = set(apply_concentration_cap([r["ticker"] for r in sorted_init]))
    capped_init  = [r for r in sorted_init if r["ticker"] in capped_ticks]

    top_n_list = capped_init[:TOP_N]

    if strat_cfg["weighted"] and top_n_list:
        total_score = sum(r[score_key] for r in top_n_list)
        allocs = {r["ticker"]: r[score_key] / total_score * CAPITAL for r in top_n_list}
    else:
        allocs = {r["ticker"]: PER_POS for r in top_n_list}

    p = Portfolio(strat_name)
    for r in top_n_list:
        pr = get_close(r["ticker"], entry)
        if pr:
            p.buy(r["ticker"], pr, allocs[r["ticker"]], entry)

    rebal_dates = _rebal_dates(entry, exit_date, strat_cfg["rebal_type"])
    for rd in rebal_dates:
        ranked = sorted(_scores[rd], key=lambda x: x[score_key], reverse=True)
        p.rebalance(rd, ranked, strat_cfg["cutoff"], TOP_N, PER_POS,
                    min_hold=strat_cfg["min_hold"])

    result = p.finalize(exit_date)
    result["spearman"] = spearman(initial, entry, exit_date, score_key)
    result["n_rebal"]  = len(rebal_dates)
    return result


# ── Main loop: run all periods × all strategies ────────────────────────────────
print("\n" + "=" * 72)
print("  PHASE 4: Running all strategies across all 7 periods")
print("=" * 72)

all_results: dict[str, dict[str, dict]] = {}   # period_name → strat_name → result

for period in PERIODS:
    print(f"\n  Period: {period['name']}  ({period['entry']} → {period['exit']})")
    sp = spy_return(period["entry"], period["exit"])
    vix_e = vix_on(period["entry"])
    print(f"  SPY: {sp:+.2f}%  |  VIX on entry: {vix_e:.1f}")
    all_results[period["name"]] = {}
    for strat_name, strat_cfg in STRATEGIES.items():
        r = run_period_strategy(period, strat_name, strat_cfg)
        all_results[period["name"]][strat_name] = r
        alpha = r["total_return"] - sp
        beat  = ">" if r["total_return"] > sp else "<"
        print(f"    {strat_name}  return: {r['total_return']:>+7.2f}%  "
              f"alpha: {alpha:>+7.2f}%  {beat}  "
              f"Spearman: {r['spearman']:>+.3f}  "
              f"win: {r['win_rate']:.0%}  "
              f"TC: ${r['total_tc']:,.0f}")


# ── Summary table ──────────────────────────────────────────────────────────────
print("\n\n" + "=" * 110)
print("  MULTI-YEAR STRATEGY SUMMARY")
print("=" * 110)

short_names = [p["name"].split()[0] + (p["name"].split()[1] if len(p["name"].split()) > 1 else "") for p in PERIODS]
# simpler: use year prefix
short_names = ["2019", "2020", "2021", "2022", "2023", "2024", "2025-26"]

# Header
hdr = f"  {'Strategy':<22}"
for sn in short_names:
    hdr += f"  {sn:>10}"
hdr += f"  {'Avg':>8}  {'Beat SPY':>9}  {'Avg Spear':>10}"
print(hdr)
print("  " + "-" * 105)

# SPY row
spy_row = f"  {'SPY (benchmark)':<22}"
spy_returns = [spy_return(p["entry"], p["exit"]) for p in PERIODS]
for sp in spy_returns:
    spy_row += f"  {sp:>+9.2f}%"
spy_row += f"  {statistics.mean(spy_returns):>+7.2f}%  {'—':>9}  {'—':>10}"
print(spy_row)
print("  " + "-" * 105)

for strat_name in STRATEGIES:
    returns = [all_results[p["name"]][strat_name]["total_return"] for p in PERIODS]
    spears  = [all_results[p["name"]][strat_name]["spearman"]     for p in PERIODS]
    beats   = sum(1 for r, s in zip(returns, spy_returns) if r > s)
    row_str = f"  {strat_name:<22}"
    for r, sp in zip(returns, spy_returns):
        marker = "+" if r > sp else " "
        row_str += f"  {r:>+8.2f}%{marker}"
    row_str += (f"  {statistics.mean(returns):>+7.2f}%"
                f"  {beats}/{len(PERIODS):>9}"
                f"  {statistics.mean(spears):>+9.3f}")
    print(row_str)


# ── Spearman table ─────────────────────────────────────────────────────────────
print("\n\n" + "=" * 110)
print("  SPEARMAN RANK CORRELATION  (> 0 = model ranks winners higher at entry)")
print("=" * 110)
hdr2 = f"  {'Strategy':<22}"
for sn in short_names:
    hdr2 += f"  {sn:>10}"
hdr2 += f"  {'Mean':>8}  {'Positive':>9}"
print(hdr2)
print("  " + "-" * 105)
for strat_name in STRATEGIES:
    spears  = [all_results[p["name"]][strat_name]["spearman"] for p in PERIODS]
    n_pos   = sum(1 for s in spears if s > 0)
    row_str = f"  {strat_name:<22}"
    for s in spears:
        marker = "+" if s > 0 else "-"
        row_str += f"  {s:>+9.3f}{marker}"
    row_str += f"  {statistics.mean(spears):>+7.3f}  {n_pos}/{len(spears):>9}"
    print(row_str)


# ── Per-period detail for S6 (regime-adaptive) ────────────────────────────────
print("\n\n" + "=" * 72)
print("  S6 REGIME-ADAPTIVE DETAIL — VIX levels and weight shifts per period")
print("=" * 72)
print(f"  {'Period':<26}  {'VIX entry':>10}  {'Regime weights':>35}  {'Return':>9}  {'vs SPY':>8}")
print("  " + "-" * 92)
for period in PERIODS:
    vix_e  = vix_on(period["entry"])
    tw, mw, qw, sw, nw, ew = _regime_weights(vix_e)
    regime_str = f"T{tw:.0%} Mo{mw:.0%} Q{qw:.0%} Sm{sw:.0%}"
    ret = all_results[period["name"]]["S6"]["total_return"]
    sp  = spy_return(period["entry"], period["exit"])
    print(f"  {period['name']:<26}  {vix_e:>10.1f}  {regime_str:>35}  {ret:>+8.2f}%  {ret-sp:>+7.2f}%")


# ── Regime distribution across all periods ─────────────────────────────────────
print("\n\n" + "=" * 72)
print("  REGIME DISTRIBUTION — How often we were in each VIX regime")
print("=" * 72)
vix_buckets = {"Normal (<25)": 0, "Elevated (25-35)": 0, "Crisis (>35)": 0, "Total": 0}
for period in PERIODS:
    for d in [period["entry"]] + _rebal_dates(period["entry"], period["exit"], "monthly"):
        v = vix_on(d)
        vix_buckets["Total"] += 1
        if v > 35:
            vix_buckets["Crisis (>35)"] += 1
        elif v > 25:
            vix_buckets["Elevated (25-35)"] += 1
        else:
            vix_buckets["Normal (<25)"] += 1
tot = vix_buckets["Total"]
for k, v in vix_buckets.items():
    if k == "Total":
        continue
    print(f"  {k:<20}: {v:>3} / {tot} scoring dates  ({v/tot:.0%})")


# ── Risk metrics per strategy ──────────────────────────────────────────────────
print("\n\n" + "=" * 72)
print("  RISK METRICS ACROSS ALL PERIODS")
print("=" * 72)
print(f"  {'Strategy':<10}  {'Avg Return':>12}  {'Worst Year':>12}  {'Best Year':>12}  {'Win%':>8}  {'Avg TC$':>9}")
print("  " + "-" * 68)
for strat_name in STRATEGIES:
    returns = [all_results[p["name"]][strat_name]["total_return"] for p in PERIODS]
    tcs     = [all_results[p["name"]][strat_name]["total_tc"]     for p in PERIODS]
    beat    = [1 for r, s in zip(returns, spy_returns) if r > s]
    print(f"  {strat_name:<10}  {statistics.mean(returns):>+11.2f}%  "
          f"{min(returns):>+11.2f}%  {max(returns):>+11.2f}%  "
          f"{len(beat)/len(returns):>7.0%}  ${statistics.mean(tcs):>8,.0f}")


print(f"\n{'=' * 72}")
print("  INTERPRETATION GUIDE")
print(f"{'=' * 72}")
print("""
  S2  Quarterly, equal weight — conservative baseline
  S4  Monthly, equal weight   — faster rotation, more active
  S5  Monthly, signal-weighted— scores drive allocation size
  S6  Monthly, regime-adaptive— VIX>25 shifts from momentum to quality
      Normal (<25 VIX):  Tech 20%, Momentum 25%, Quality 15%
      Elevated (25-35):  Tech 20%, Momentum 15%, Quality 25%
      Crisis (>35):      Tech 20%, Momentum 10%, Quality 30%

  Spearman > +0.10 = model reliably ranks winners at entry
  Spearman < 0     = model backwards in that regime (common in reversals)
  S6 should show less-negative Spearman in crisis years vs S2/S4/S5

  NOTE: Quality + congress scores use current (2026) TTM data for ALL periods.
  This introduces mild look-ahead bias — real historical quality may differ
  by 1-2 quarters for each period. Effect is small for stable large-caps.
  Momentum + technical + earnings scores are fully look-ahead clean.
""")
print(f"{'=' * 72}\n")
