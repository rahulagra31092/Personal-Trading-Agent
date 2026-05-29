import os
from dotenv import load_dotenv

load_dotenv()

POLYGON_API_KEY = os.environ["POLYGON_API_KEY"]
CLAUDE_API_KEY = os.environ["CLAUDE_API_KEY"]
NEWS_API_KEY = os.environ["NEWS_API_KEY"]
SLACK_WEBHOOK_URL = os.environ["SLACK_WEBHOOK_URL"]
SCHWAB_CLIENT_ID = os.environ.get("SCHWAB_CLIENT_ID", "")
SCHWAB_CLIENT_SECRET = os.environ.get("SCHWAB_CLIENT_SECRET", "")

EXCLUDED_TICKERS: set[str] = {"FUBO"}

SIGNAL_WEIGHTS: dict[str, float] = {
    "technical": 0.30,
    "arima": 0.20,
    "smart_money": 0.20,
    "news_reaction": 0.15,
    "earnings": 0.15,
}

PHASE: int = 1
PHASE2_LIVE_CAPITAL: float = 2500.0
PHASE3_LIVE_CAPITAL: float = 5000.0
PHASE2_HARD_STOP: float = 2000.0
PHASE3_HARD_STOP: float = 4000.0
PHASE2_MIN_CONFIDENCE: float = 0.70
PHASE3_MIN_CONFIDENCE: float = 0.65
