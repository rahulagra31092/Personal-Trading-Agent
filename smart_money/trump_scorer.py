# DEPRECATED: trump_scorer.py is no longer called in the live pipeline.
# The 7% weight slot is now filled by smart_money/estimate_revisions.py.
# This file is kept for reference only.
import re
import logging
from datetime import date, timedelta

import requests

import config
from data.cache import get_cache, set_cache

logger = logging.getLogger(__name__)

_TTL = 21600  # 6 hours — policy moves fast

# ---------------------------------------------------------------------------
# Policy tag definitions: tag -> keywords that signal this policy is active
# ---------------------------------------------------------------------------
POLICY_TAGS: dict[str, list[str]] = {
    "tariff":          ["tariff", "import duty", "trade war", "trade barrier",
                        "trade deal", "reciprocal tax"],
    "china_tension":   ["china", "beijing", "huawei", "export control",
                        "chip ban", "tiktok", "de-coupling", "decoupling"],
    "energy_boost":    ["drill", "lng", "keystone", "oil permit",
                        "energy independence", "offshore drilling",
                        "fossil fuel", "natural gas export"],
    "deregulation":    ["deregulate", "rollback", "dodd-frank", "epa rollback",
                        "regulation cut", "regulatory relief"],
    "defense_spend":   ["defense spending", "military budget", "pentagon",
                        "nato", "weapons system", "army", "navy", "air force"],
    "ai_invest":       ["artificial intelligence", "stargate", "ai investment",
                        "technology investment", "data center"],
    "pharma_pressure": ["drug price", "prescription drug",
                        "pharmaceutical price", "medicare drug",
                        "drug negotiation"],
    "crypto_positive": ["bitcoin", "crypto", "digital asset",
                        "strategic reserve", "blockchain"],
}

# ---------------------------------------------------------------------------
# Per-ticker policy impact map
# Each entry: (policy_tag, direction, base_modifier)
#   direction "tailwind"  → tag being active HELPS this stock
#   direction "headwind"  → tag being active HURTS this stock
#   base_modifier         → max raw impact at full signal strength
# ---------------------------------------------------------------------------
TICKER_POLICY: dict[str, list[tuple[str, str, float]]] = {
    # Semiconductors — hurt by China tension + tariffs, helped by AI investment
    "NVDA": [("china_tension","headwind",-0.09),("ai_invest","tailwind",+0.06),
             ("tariff","headwind",-0.05)],
    "AMD":  [("china_tension","headwind",-0.07),("ai_invest","tailwind",+0.05),
             ("tariff","headwind",-0.04)],
    "AMAT": [("china_tension","headwind",-0.08),("tariff","headwind",-0.05)],
    "LRCX": [("china_tension","headwind",-0.08),("tariff","headwind",-0.05)],
    "KLAC": [("china_tension","headwind",-0.07),("tariff","headwind",-0.04)],
    "INTC": [("china_tension","headwind",-0.06),("tariff","headwind",-0.04)],
    "MU":   [("china_tension","headwind",-0.07),("tariff","headwind",-0.04)],
    "QCOM": [("china_tension","headwind",-0.07),("tariff","headwind",-0.05)],
    "MRVL": [("china_tension","headwind",-0.06),("ai_invest","tailwind",+0.04)],
    "ARM":  [("china_tension","headwind",-0.05),("ai_invest","tailwind",+0.05)],
    # Big tech
    "AAPL":  [("tariff","headwind",-0.08),("china_tension","headwind",-0.07),
              ("ai_invest","tailwind",+0.03)],
    "MSFT":  [("ai_invest","tailwind",+0.06),("deregulation","tailwind",+0.03)],
    "GOOGL": [("ai_invest","tailwind",+0.05),("deregulation","tailwind",+0.03)],
    "META":  [("ai_invest","tailwind",+0.04),("deregulation","tailwind",+0.03)],
    "AMZN":  [("tariff","headwind",-0.04),("ai_invest","tailwind",+0.04),
              ("deregulation","tailwind",+0.03)],
    "TSLA":  [("deregulation","tailwind",+0.07),("energy_boost","tailwind",+0.03),
              ("tariff","tailwind",+0.03)],   # domestic EV, benefits from import tariffs on foreign EVs
    "ORCL":  [("ai_invest","tailwind",+0.05)],
    "CRM":   [("ai_invest","tailwind",+0.04)],
    "IBM":   [("ai_invest","tailwind",+0.04),("deregulation","tailwind",+0.03)],
    "CSCO":  [("deregulation","tailwind",+0.03),("china_tension","headwind",-0.03)],
    "NOW":   [("ai_invest","tailwind",+0.04)],
    "PLTR":  [("defense_spend","tailwind",+0.07),("ai_invest","tailwind",+0.05)],
    "CRWD":  [("deregulation","tailwind",+0.03)],
    "PANW":  [("deregulation","tailwind",+0.03)],
    "DDOG":  [("ai_invest","tailwind",+0.04)],
    "MDB":   [("ai_invest","tailwind",+0.03)],
    "NET":   [("deregulation","tailwind",+0.03)],
    # Financials — big beneficiary of deregulation
    "JPM":  [("deregulation","tailwind",+0.08)],
    "GS":   [("deregulation","tailwind",+0.09),("crypto_positive","tailwind",+0.05)],
    "MS":   [("deregulation","tailwind",+0.08),("crypto_positive","tailwind",+0.04)],
    "BAC":  [("deregulation","tailwind",+0.07)],
    "WFC":  [("deregulation","tailwind",+0.07)],
    "C":    [("deregulation","tailwind",+0.07)],
    "BLK":  [("deregulation","tailwind",+0.06),("crypto_positive","tailwind",+0.04)],
    "SCHW": [("deregulation","tailwind",+0.06),("crypto_positive","tailwind",+0.04)],
    "V":    [("deregulation","tailwind",+0.04)],
    "MA":   [("deregulation","tailwind",+0.04)],
    "PYPL": [("crypto_positive","tailwind",+0.06),("deregulation","tailwind",+0.04)],
    "CME":  [("crypto_positive","tailwind",+0.05)],
    "KKR":  [("deregulation","tailwind",+0.06)],
    "APO":  [("deregulation","tailwind",+0.06)],
    "BX":   [("deregulation","tailwind",+0.06)],
    "ARES": [("deregulation","tailwind",+0.05)],
    "AXP":  [("deregulation","tailwind",+0.04)],
    "COF":  [("deregulation","tailwind",+0.05)],
    # Energy — primary beneficiary of Trump energy policy
    "XOM": [("energy_boost","tailwind",+0.09),("deregulation","tailwind",+0.06)],
    "CVX": [("energy_boost","tailwind",+0.09),("deregulation","tailwind",+0.06)],
    "COP": [("energy_boost","tailwind",+0.08),("deregulation","tailwind",+0.05)],
    "EOG": [("energy_boost","tailwind",+0.08),("deregulation","tailwind",+0.05)],
    "SLB": [("energy_boost","tailwind",+0.07)],
    "MPC": [("energy_boost","tailwind",+0.07),("tariff","tailwind",+0.04)],
    "VLO": [("energy_boost","tailwind",+0.07),("tariff","tailwind",+0.04)],
    "PSX": [("energy_boost","tailwind",+0.07),("tariff","tailwind",+0.04)],
    "DVN": [("energy_boost","tailwind",+0.08),("deregulation","tailwind",+0.05)],
    "HAL": [("energy_boost","tailwind",+0.07)],
    # Defense — direct beneficiary of defense spending push
    "LMT": [("defense_spend","tailwind",+0.09)],
    "RTX": [("defense_spend","tailwind",+0.09)],
    "NOC": [("defense_spend","tailwind",+0.09)],
    "GD":  [("defense_spend","tailwind",+0.08)],
    "BA":  [("defense_spend","tailwind",+0.07),("tariff","tailwind",+0.04)],
    # Industrials — domestic tariff winners
    "CAT": [("tariff","tailwind",+0.06),("deregulation","tailwind",+0.04)],
    "DE":  [("tariff","tailwind",+0.05),("deregulation","tailwind",+0.03)],
    "GE":  [("defense_spend","tailwind",+0.05),("energy_boost","tailwind",+0.04)],
    "HON": [("deregulation","tailwind",+0.04)],
    "ETN": [("deregulation","tailwind",+0.05),("energy_boost","tailwind",+0.03)],
    "ROK": [("tariff","tailwind",+0.05)],
    "AME": [("defense_spend","tailwind",+0.04),("tariff","tailwind",+0.03)],
    "ITW": [("tariff","tailwind",+0.04)],
    "PH":  [("tariff","tailwind",+0.04)],
    "EMR": [("energy_boost","tailwind",+0.04)],
    "MMM": [("tariff","tailwind",+0.04)],
    "UPS": [("tariff","headwind",-0.03)],
    "FDX": [("tariff","headwind",-0.03)],
    "UBER":[("deregulation","tailwind",+0.05)],
    # Materials — domestic tariff protection; rare earths especially
    "FCX": [("tariff","tailwind",+0.06),("china_tension","tailwind",+0.05)],
    "NEM": [("tariff","tailwind",+0.04)],
    "ALB": [("tariff","tailwind",+0.05),("china_tension","tailwind",+0.05)],
    "MP":  [("tariff","tailwind",+0.10),("china_tension","tailwind",+0.10)],
    "DD":  [("tariff","tailwind",+0.05),("deregulation","tailwind",+0.04)],
    "DOW": [("tariff","tailwind",+0.04),("energy_boost","tailwind",+0.04)],
    "LIN": [("energy_boost","tailwind",+0.03)],
    "APD": [("energy_boost","tailwind",+0.03)],
    # Healthcare / Pharma — hurt by drug pricing pressure
    "LLY":  [("pharma_pressure","headwind",-0.08)],
    "PFE":  [("pharma_pressure","headwind",-0.06)],
    "MRK":  [("pharma_pressure","headwind",-0.06)],
    "ABBV": [("pharma_pressure","headwind",-0.06)],
    "BMY":  [("pharma_pressure","headwind",-0.05)],
    "AMGN": [("pharma_pressure","headwind",-0.05)],
    "GILD": [("pharma_pressure","headwind",-0.05)],
    "REGN": [("pharma_pressure","headwind",-0.06)],
    "VRTX": [("pharma_pressure","headwind",-0.05)],
    "MRNA": [("pharma_pressure","headwind",-0.05)],
    "BIIB": [("pharma_pressure","headwind",-0.04)],
    "ISRG": [("deregulation","tailwind",+0.03)],
    # Managed care — hurt indirectly
    "UNH": [("pharma_pressure","headwind",-0.04)],
    "ELV": [("pharma_pressure","headwind",-0.04)],
    "HUM": [("pharma_pressure","headwind",-0.04)],
    "CVS": [("pharma_pressure","headwind",-0.04)],
    "CI":  [("pharma_pressure","headwind",-0.04)],
    # Consumer / Retail — hurt by tariffs on imported goods
    "WMT":  [("tariff","headwind",-0.06)],
    "TGT":  [("tariff","headwind",-0.07)],
    "COST": [("tariff","headwind",-0.05)],
    "HD":   [("tariff","headwind",-0.05)],
    "LOW":  [("tariff","headwind",-0.04)],
    "NKE":  [("tariff","headwind",-0.07),("china_tension","headwind",-0.06)],
    "MCD":  [("tariff","headwind",-0.03)],
    "SBUX": [("tariff","headwind",-0.03)],
    "TJX":  [("tariff","headwind",-0.04)],
    # Hotels / Gaming — tariff neutral, deregulation mild positive
    "MAR":  [("deregulation","tailwind",+0.03)],
    "HLT":  [("deregulation","tailwind",+0.03)],
    "LVS":  [("china_tension","headwind",-0.04)],
    "WYNN": [("china_tension","headwind",-0.04)],
    # Real estate — rate sensitive, limited direct policy exposure
    "EQIX": [("ai_invest","tailwind",+0.05)],
    "DLR":  [("ai_invest","tailwind",+0.04)],
    "PLD":  [("tariff","headwind",-0.03)],
    # Utilities — energy deregulation mild headwind for renewables
    "NEE":  [("deregulation","headwind",-0.04),("energy_boost","headwind",-0.03)],
    "DUK":  [("deregulation","tailwind",+0.02)],
    # Telecom
    "TMUS": [("deregulation","tailwind",+0.04)],
    "VZ":   [("deregulation","tailwind",+0.03)],
    "T":    [("deregulation","tailwind",+0.03)],
    # Streaming / Media
    "NFLX": [("deregulation","tailwind",+0.03)],
    "DIS":  [("china_tension","headwind",-0.03)],
    # Autos
    "F":    [("tariff","tailwind",+0.05)],
    "GM":   [("tariff","tailwind",+0.05)],
    # Semiconductors — additions for universe completeness
    "AVGO": [("china_tension","headwind",-0.06),("ai_invest","tailwind",+0.08),
             ("tariff","headwind",-0.04)],
    "DELL": [("tariff","tailwind",+0.04),("ai_invest","tailwind",+0.05)],
    # Cybersecurity — China tension increases demand; deregulation eases compliance costs
    "ZS":   [("china_tension","tailwind",+0.04),("deregulation","tailwind",+0.03)],
    # Data / cloud platforms — AI investment tailwind
    "SNOW": [("ai_invest","tailwind",+0.05)],
    "WDAY": [("ai_invest","tailwind",+0.03),("deregulation","tailwind",+0.02)],
    "HUBS": [("ai_invest","tailwind",+0.03),("deregulation","tailwind",+0.02)],
}


def _fetch_trump_policy_news(days: int = 7) -> list[str]:
    """Fetch recent Trump policy headlines + descriptions. Returns list of lowercased text blobs."""
    cache_key = f"trump_news:{days}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    from_date = (date.today() - timedelta(days=days)).isoformat()
    params = {
        "q": ('Trump AND (tariff OR "executive order" OR deregulation OR energy '
              'OR defense OR China OR pharmaceutical OR "artificial intelligence" '
              'OR crypto OR bitcoin)'),
        "language": "en",
        "sortBy":   "publishedAt",
        "pageSize": 100,
        "from":     from_date,
        "apiKey":   config.NEWS_API_KEY,
    }
    try:
        resp = requests.get("https://newsapi.org/v2/everything",
                            params=params, timeout=10)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        texts = [
            f"{a.get('title','') or ''} {a.get('description','') or ''}".lower()
            for a in articles
        ]
        set_cache(cache_key, texts, ttl_seconds=_TTL)
        return texts
    except Exception as exc:
        logger.warning("Trump policy news fetch failed: %s", exc)
        set_cache(cache_key, [], ttl_seconds=3600)  # cache failures to avoid re-hitting rate limit
        return []


def score_active_tags(texts: list[str]) -> dict[str, float]:
    """
    Returns signal strength [0.0, 1.0] per policy tag.
    Strength = fraction of articles that contain at least one tag keyword.
    """
    hits = {tag: 0 for tag in POLICY_TAGS}
    for text in texts:
        for tag, keywords in POLICY_TAGS.items():
            for kw in keywords:
                if re.search(rf"\b{re.escape(kw)}\b", text):
                    hits[tag] += 1
                    break
    total = max(len(texts), 1)
    return {tag: min(hits[tag] / total, 1.0) for tag in POLICY_TAGS}


def compute_trump_policy_score(ticker: str, days: int = 7) -> float:
    """
    Standalone [0, 1] factor score for White House policy exposure.
    0.5 = neutral / no mapped policy. >0.5 = net tailwind. <0.5 = net headwind.
    """
    modifier = compute_trump_modifier(ticker, days)
    # modifier in [-0.15, +0.15]; map to [0.0, 1.0] with 0.5 as neutral
    score = 0.5 + modifier / 0.15 * 0.5
    return round(max(0.10, min(0.90, score)), 4)


def compute_trump_modifier(ticker: str, days: int = 7) -> float:
    """
    Policy modifier for the given ticker in [-0.15, +0.15].
    Positive = White House policy is a net tailwind.
    Negative = net headwind.
    Returns 0.0 if ticker has no mapped policy exposure or news unavailable.
    """
    cache_key = f"trump_mod:{ticker.upper()}:{days}"
    cached = get_cache(cache_key)
    if cached is not None:
        return cached

    policies = TICKER_POLICY.get(ticker.upper())
    if not policies:
        return 0.0

    texts = _fetch_trump_policy_news(days)
    if not texts:
        set_cache(cache_key, 0.0, ttl_seconds=_TTL)
        return 0.0

    tag_strength = score_active_tags(texts)

    modifier = 0.0
    for tag, direction, base_mod in policies:
        strength = tag_strength.get(tag, 0.0)
        if strength < 0.03:  # require >3% article hit rate for signal
            continue
        # Scale up to 1.5× for a very strong signal (>30% hit rate)
        scale = min(1.0 + strength * 1.67, 1.5)
        modifier += base_mod * scale

    result = round(max(-0.15, min(0.15, modifier)), 4)
    set_cache(cache_key, result, ttl_seconds=_TTL)
    return result
