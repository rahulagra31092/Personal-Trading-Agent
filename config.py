import os
from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"Missing required environment variable: {name}. "
            f"Add it to your .env file (see .env.example)."
        )
    return val


POLYGON_API_KEY: str | None = os.environ.get("POLYGON_API_KEY") or None
CLAUDE_API_KEY = _require("CLAUDE_API_KEY")
NEWS_API_KEY: str | None = os.environ.get("NEWS_API_KEY") or None
NEWSDATA_API_KEY: str | None = os.environ.get("NEWSDATA_API_KEY") or None
SLACK_WEBHOOK_URL: str | None = os.environ.get("SLACK_WEBHOOK_URL") or None
SCHWAB_CLIENT_ID: str | None = os.environ.get("SCHWAB_CLIENT_ID") or None
SCHWAB_CLIENT_SECRET: str | None = os.environ.get("SCHWAB_CLIENT_SECRET") or None
QUIVER_API_KEY: str | None = os.environ.get("QUIVER_API_KEY") or None
GOOGLE_SHEET_ID: str | None = os.environ.get("GOOGLE_SHEET_ID") or None

EXCLUDED_TICKERS: frozenset[str] = frozenset()


def is_excluded(ticker: str) -> bool:
    return ticker.strip().upper() in EXCLUDED_TICKERS


SIGNAL_WEIGHTS: dict[str, float] = {
    "technical": 0.15,
    "momentum": 0.30,
    "quality": 0.15,
    "congress": 0.08,
    "estimate_revisions": 0.07,
    "news_reaction": 0.10,
    "earnings": 0.15,
}
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9, (
    f"SIGNAL_WEIGHTS must sum to 1.0, got {sum(SIGNAL_WEIGHTS.values())}"
)

# Regime-adaptive weight overrides — applied by signals.py based on live VIX.
# VIX thresholds (from quant/regime.py _THRESHOLDS):
#   low_vol:  VIX < 15   — calm bull market, momentum rewarded
#   normal:   VIX 15-20  — baseline
#   elevated: VIX 20-25  — mild concern; quality/earnings start to matter more
#   high:     VIX 25-30  — meaningful stress; momentum unreliable
#   crisis:   VIX >= 30  — capital preservation; only quality + earnings predict
REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "low_vol": {          # VIX < 15 — bull market, momentum heavily rewarded
        "technical": 0.13, "momentum": 0.37, "quality": 0.12,
        "congress": 0.08, "estimate_revisions": 0.07, "news_reaction": 0.08, "earnings": 0.15,
    },
    "normal": SIGNAL_WEIGHTS,  # VIX 15-20 — baseline weights
    "elevated": {         # VIX 20-25 — momentum falters, quality/earnings take over
        "technical": 0.10, "momentum": 0.23, "quality": 0.22,
        "congress": 0.08, "estimate_revisions": 0.07, "news_reaction": 0.10, "earnings": 0.20,
    },
    "high": {             # VIX 25-30 — preserve capital; quality + earnings dominate
        "technical": 0.08, "momentum": 0.12, "quality": 0.28,
        "congress": 0.07, "estimate_revisions": 0.05, "news_reaction": 0.10, "earnings": 0.30,
    },
    "crisis": {           # VIX >= 30 — extreme stress; cash is valid
        "technical": 0.06, "momentum": 0.10, "quality": 0.32,
        "congress": 0.05, "estimate_revisions": 0.05, "news_reaction": 0.10, "earnings": 0.32,
    },
}
for _regime, _w in REGIME_WEIGHTS.items():
    if _w is not SIGNAL_WEIGHTS:
        assert abs(sum(_w.values()) - 1.0) < 1e-9, (
            f"REGIME_WEIGHTS[{_regime!r}] must sum to 1.0"
        )

PHASE: int = 1
PHASE2_LIVE_CAPITAL: float = 2500.0
PHASE3_LIVE_CAPITAL: float = 5000.0
PHASE2_HARD_STOP: float = 2000.0
PHASE3_HARD_STOP: float = 4000.0
PHASE2_MIN_CONFIDENCE: float = 0.70
PHASE3_MIN_CONFIDENCE: float = 0.65
