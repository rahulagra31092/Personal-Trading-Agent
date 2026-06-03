import re
import logging
from datetime import datetime, timezone

from data.news import get_ticker_news

logger = logging.getLogger(__name__)

# Single-word signals — matched with full word boundaries (\b...\b)
_BULLISH = frozenset({
    "upgrade", "upgraded", "upgrades",
    "beat", "beats", "beating",
    "strong", "stronger",
    "bullish",
    "buy", "buying",
    "outperform", "outperformed", "outperforms",
    "growth", "growing", "grew",
    "surge", "surged", "surges", "surging",
    "rally", "rallied", "rallies", "rallying",
    "profit", "profits", "profitable",
    "record",
    "approval", "approved",
    "buyback",
    "dividend",
    "expansion", "expanding", "expanded",
    "momentum",
    "partnership",
})

_BEARISH = frozenset({
    "downgrade", "downgraded", "downgrades",
    "miss", "misses", "missed",
    "weak", "weaker", "weakness",
    "bearish",
    "sell", "selling",
    "underperform", "underperformed", "underperforms",
    "decline", "declined", "declines", "declining",
    "loss", "losses",
    "crash", "crashed", "crashing",
    "cut",
    "layoff", "layoffs",
    "investigation",
    "lawsuit",
    "recall",
    "bankruptcy",
    "fraud",
    "resignation",
    "default",
    "warning",
})

# Multi-word phrases — matched as substrings (word boundaries already implied by context)
_BULLISH_PHRASES = frozenset({
    "beat expectations", "raised guidance", "above expectations",
    "raised price target", "price target increase",
})

_BEARISH_PHRASES = frozenset({
    "below expectations", "missed expectations", "cut guidance",
    "lowered guidance", "guidance cut", "going concern",
    "price target cut", "price target decrease",
})


_NEGATIONS = frozenset({
    "not", "no", "never", "neither", "nor",
    "failed", "unable", "won't", "cannot", "can't", "didn't", "doesn't", "don't",
})


def _has_negation(text: str, match_start: int, window: int = 5) -> bool:
    """
    Return True if a negation word appears within `window` words before `match_start`.
    Operates on pre-tokenized words to avoid partial matches.
    """
    prefix = text[max(0, match_start - 60):match_start]
    words = prefix.split()[-window:]
    return any(w.rstrip(".,;:") in _NEGATIONS for w in words)


def _count_keywords(text: str) -> tuple[int, int]:
    """Count bullish and bearish signals in lowercased article text, with negation detection."""
    bull = 0
    bear = 0

    for w in _BULLISH:
        m = re.search(rf"\b{re.escape(w)}\b", text)
        if m:
            if _has_negation(text, m.start()):
                bear += 1   # negated bullish → bearish flip
            else:
                bull += 1

    for w in _BEARISH:
        m = re.search(rf"\b{re.escape(w)}\b", text)
        if m:
            if _has_negation(text, m.start()):
                bull += 1   # negated bearish → bullish flip
            else:
                bear += 1

    for p in _BULLISH_PHRASES:
        idx = text.find(p)
        if idx != -1:
            if _has_negation(text, idx):
                bear += 1   # negated bullish phrase → bearish flip
            else:
                bull += 1

    for p in _BEARISH_PHRASES:
        idx = text.find(p)
        if idx != -1:
            if _has_negation(text, idx):
                bull += 1   # negated bearish phrase → bullish flip
            else:
                bear += 1

    return bull, bear


def _recency_weight(published_at: str) -> float:
    """Decay weight: < 12h = 1.0, < 24h = 0.85, < 48h = 0.70, older = 0.50."""
    if not published_at:
        return 0.75
    try:
        dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        hours_ago = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if hours_ago < 12:
            return 1.0
        if hours_ago < 24:
            return 0.85
        if hours_ago < 48:
            return 0.70
        return 0.50
    except Exception:
        return 0.75


def compute_news_score(ticker: str, days: int = 3) -> float:
    """
    Sentiment score [0, 1] from recent ticker news.
    Each article is weighted by keyword signal intensity × recency.
    Articles with no keyword hits contribute a small neutral weight (0.3)
    so they don't silently swamp a strongly-worded article.
    """
    try:
        articles = get_ticker_news(ticker, days=days)
    except Exception as exc:
        logger.warning("News fetch failed for %s: %s", ticker, exc)
        return 0.5

    if not articles:
        return 0.5

    total_weight = 0.0
    weighted_sum = 0.0

    for article in articles:
        text = (
            (article.get("title") or "") + " " + (article.get("description") or "")
        ).lower()
        bull, bear = _count_keywords(text)
        pub = (article.get("publishedAt") or article.get("pubDate")
               or article.get("published_at") or "")
        recency = _recency_weight(pub)

        intensity = bull + bear
        if intensity == 0:
            article_score = 0.5
            weight = 0.3   # neutral article: small weight, doesn't drown out signal
        else:
            article_score = bull / intensity
            weight = intensity  # more keywords = more confident signal

        total_weight += recency * weight
        weighted_sum += recency * weight * article_score

    if total_weight == 0:
        return 0.5

    return round(min(1.0, max(0.0, weighted_sum / total_weight)), 4)
