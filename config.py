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


POLYGON_API_KEY = _require("POLYGON_API_KEY")
CLAUDE_API_KEY = _require("CLAUDE_API_KEY")
NEWS_API_KEY = _require("NEWS_API_KEY")
SLACK_WEBHOOK_URL = _require("SLACK_WEBHOOK_URL")
SCHWAB_CLIENT_ID: str | None = os.environ.get("SCHWAB_CLIENT_ID") or None
SCHWAB_CLIENT_SECRET: str | None = os.environ.get("SCHWAB_CLIENT_SECRET") or None
QUIVER_API_KEY: str | None = os.environ.get("QUIVER_API_KEY") or None

EXCLUDED_TICKERS: frozenset[str] = frozenset({"FUBO"})


def is_excluded(ticker: str) -> bool:
    return ticker.strip().upper() in EXCLUDED_TICKERS


SIGNAL_WEIGHTS: dict[str, float] = {
    "technical": 0.20,
    "momentum": 0.25,
    "quality": 0.15,
    "smart_money": 0.15,
    "news_reaction": 0.10,
    "earnings": 0.15,
}
assert abs(sum(SIGNAL_WEIGHTS.values()) - 1.0) < 1e-9, (
    f"SIGNAL_WEIGHTS must sum to 1.0, got {sum(SIGNAL_WEIGHTS.values())}"
)

PHASE: int = 1
PHASE2_LIVE_CAPITAL: float = 2500.0
PHASE3_LIVE_CAPITAL: float = 5000.0
PHASE2_HARD_STOP: float = 2000.0
PHASE3_HARD_STOP: float = 4000.0
PHASE2_MIN_CONFIDENCE: float = 0.70
PHASE3_MIN_CONFIDENCE: float = 0.65
