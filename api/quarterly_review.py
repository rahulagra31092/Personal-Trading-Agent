"""
Quarterly model regression — runs on Jan 1, Apr 1, Jul 1, Oct 1.

Reads closed paper positions from signal_outcomes, computes Spearman rank
correlation between each factor's entry score and realized return, and
generates weight recommendations + a Slack report card.
"""
import logging
import math
from datetime import datetime
from zoneinfo import ZoneInfo

from api.paper_portfolio import get_closed_outcomes, log_weight_change, get_annual_weight_delta
import config

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# ── Factor list matches signal_outcomes columns ──────────────────────────────
FACTORS: list[tuple[str, str]] = [
    ("score_technical",    "Technical"),
    ("score_momentum",     "Momentum"),
    ("score_quality",      "Quality"),
    ("score_congress",     "Congress"),
    ("score_trump_policy", "Trump Policy"),
    ("score_news",         "News"),
    ("score_earnings",     "Earnings"),
]

# Weight update constraints
_MIN_WEIGHT = 0.04
_MAX_WEIGHT = 0.35
_MAX_DELTA  = 0.05   # no factor changes by more than 5pp per quarter


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _spearman(xs: list[float], ys: list[float]) -> float:
    """Spearman rank correlation — robust to outliers like MU +208%."""
    n = len(xs)
    if n < 5:
        return 0.0

    def _rank(vals: list[float]) -> list[float]:
        indexed = sorted(enumerate(vals), key=lambda t: t[1])
        ranks = [0.0] * n
        for rank, (i, _) in enumerate(indexed, 1):
            ranks[i] = float(rank)
        return ranks

    rx = _rank(xs)
    ry = _rank(ys)
    d_sq = sum((rx[i] - ry[i]) ** 2 for i in range(n))
    return 1.0 - (6.0 * d_sq) / (n * (n * n - 1))


def _significance(r: float, n: int) -> str:
    """Rough significance label without scipy."""
    if n < 5:
        return "ns"
    t_stat = r * math.sqrt(n - 2) / math.sqrt(max(1 - r * r, 1e-9))
    abs_t = abs(t_stat)
    if abs_t > 3.5:
        return "***"
    if abs_t > 2.5:
        return "**"
    if abs_t > 1.8:
        return "*"
    return "ns"


# ---------------------------------------------------------------------------
# Weight recommendation engine
# ---------------------------------------------------------------------------

def _recommend_weights(
    correlations: dict[str, float],
    holdout_correlations: dict[str, float] | None = None,
    annual_deltas: dict[str, float] | None = None,
) -> dict[str, float]:
    """
    Nudge current weights toward factors that predicted returns.
    Constraints:
      - No weight below _MIN_WEIGHT or above _MAX_WEIGHT
      - No weight changes more than _MAX_DELTA per quarter
      - If holdout_correlations provided: halve nudge when holdout sign disagrees
      - If annual_deltas provided: cap cumulative annual shift at 0.08 per factor
      - Weights sum to exactly 1.0
    """
    current = dict(config.SIGNAL_WEIGHTS)

    col_to_cfg: dict[str, str] = {}
    for col, _ in FACTORS:
        stub = col.replace("score_", "")
        for cfg_key in current:
            if stub in cfg_key:
                col_to_cfg[col] = cfg_key
                break

    nudges: dict[str, float] = {}
    for col, cfg_key in col_to_cfg.items():
        r = correlations.get(col, 0.0)
        nudge = round(r * 0.04, 4)
        nudge = max(-_MAX_DELTA, min(_MAX_DELTA, nudge))

        # Holdout validation: halve nudge if holdout direction disagrees
        if holdout_correlations and nudge != 0.0:
            h_r = holdout_correlations.get(col, 0.0)
            if r * h_r < 0 and abs(h_r) > 0.10:
                nudge = nudge * 0.5

        # Annual cap: limit cumulative signed drift per factor to ±8pp per year
        if annual_deltas is not None:
            annual_used = annual_deltas.get(cfg_key, 0.0)
            remaining = max(0.0, 0.08 - abs(annual_used))
            if abs(nudge) > remaining:
                nudge = math.copysign(remaining, nudge)

        nudges[cfg_key] = nudge

    raw: dict[str, float] = {}
    for key, w in current.items():
        delta = nudges.get(key, 0.0)
        raw[key] = max(_MIN_WEIGHT, min(_MAX_WEIGHT, round(w + delta, 4)))

    total = sum(raw.values())
    return {k: round(v / total, 4) for k, v in raw.items()}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_quarterly_review(min_closed: int = 40) -> dict:
    """
    Compute regression, return report dict with:
      correlations, n, win_rate, avg_winner, avg_loser, recommended_weights,
      on_track_18pct, summary_lines (for Slack)
    """
    closed = get_closed_outcomes(min_closed=min_closed)
    n = len(closed)

    if n < min_closed:
        return {
            "n": n,
            "skipped": True,
            "reason": f"Only {n} closed positions — need {min_closed} for regression.",
        }

    # 75/25 temporal split — older positions train, newer validate
    closed_sorted = sorted(closed, key=lambda r: r.get("exit_date") or "")
    holdout_n = max(1, n // 4)
    holdout = closed_sorted[-holdout_n:]
    training = closed_sorted[:-holdout_n]

    returns_train = [r["realized_return_pct"] for r in training]
    returns_hold  = [r["realized_return_pct"] for r in holdout]

    def _compute_correlations(rows: list[dict], returns: list[float]) -> dict[str, float]:
        result = {}
        for col, label in FACTORS:
            scores = [r.get(col) for r in rows]
            pairs = [(s, ret) for s, ret in zip(scores, returns) if s is not None]
            if len(pairs) < 5:
                result[col] = 0.0
            else:
                xs, ys = zip(*pairs)
                result[col] = round(_spearman(list(xs), list(ys)), 4)
        return result

    correlations         = _compute_correlations(training, returns_train)
    holdout_correlations = _compute_correlations(holdout,  returns_hold)

    # Build holdout warning list (factors where direction disagrees meaningfully)
    holdout_warnings = [
        col for col in correlations
        if correlations[col] * holdout_correlations.get(col, 0.0) < 0
        and abs(holdout_correlations.get(col, 0.0)) > 0.10
    ]

    returns = [r["realized_return_pct"] for r in closed]
    winners = [r for r in returns if r > 0]
    losers  = [r for r in returns if r <= 0]
    win_rate = round(len(winners) / n * 100, 1) if n else 0.0
    avg_winner = round(sum(winners) / len(winners), 2) if winners else 0.0
    avg_loser  = round(sum(losers)  / len(losers),  2) if losers  else 0.0

    best  = max(closed, key=lambda r: r["realized_return_pct"] or 0)
    worst = min(closed, key=lambda r: r["realized_return_pct"] or 0)

    # Gather annual drift for each factor
    annual_deltas: dict[str, float] = {}
    for col, _ in FACTORS:
        stub = col.replace("score_", "")
        for cfg_key in config.SIGNAL_WEIGHTS:
            if stub in cfg_key:
                annual_deltas[cfg_key] = get_annual_weight_delta(cfg_key)
                break

    recommended_weights = _recommend_weights(correlations, holdout_correlations, annual_deltas)
    current_weights = dict(config.SIGNAL_WEIGHTS)

    # Log weight changes that differ from current by at least 0.005
    for key, new_w in recommended_weights.items():
        cur_w = current_weights.get(key, new_w)
        if abs(new_w - cur_w) >= 0.005:
            log_weight_change(key, cur_w, new_w)

    avg_days = sum(r.get("days_held") or 30 for r in closed) / n
    avg_ret  = sum(returns) / n
    ann_ret  = round(avg_ret * (365 / max(avg_days, 1)), 1) if avg_days else 0.0
    on_track = ann_ret >= 18.0

    return {
        "n": n,
        "skipped": False,
        "correlations": correlations,
        "holdout_n": holdout_n,
        "holdout_warnings": holdout_warnings,
        "win_rate": win_rate,
        "avg_winner": avg_winner,
        "avg_loser": avg_loser,
        "best": {"ticker": best["ticker"], "return": best["realized_return_pct"]},
        "worst": {"ticker": worst["ticker"], "return": worst["realized_return_pct"]},
        "annualised_return_est": ann_ret,
        "on_track_18pct": on_track,
        "current_weights": current_weights,
        "recommended_weights": recommended_weights,
    }


# ---------------------------------------------------------------------------
# Slack block builder
# ---------------------------------------------------------------------------

def build_quarterly_slack_blocks(report: dict, now: datetime) -> list[dict]:
    quarter_label = f"Q{((now.month - 1) // 3) + 1} {now.year}"
    date_str = now.strftime("%b %d, %Y")

    if report.get("skipped"):
        return [{
            "type": "section",
            "text": {"type": "mrkdwn", "text": (
                f"*Model Report Card — {quarter_label}*\n"
                f"_{report['reason']}_\n"
                "Regression will run automatically once sufficient data is collected."
            )},
        }]

    n            = report["n"]
    correlations = report["correlations"]
    rw           = report["recommended_weights"]
    cw           = report["current_weights"]
    ann_ret      = report["annualised_return_est"]
    on_track     = report["on_track_18pct"]
    track_label  = f"ON TRACK ({ann_ret:+.1f}% est. annualised)" if on_track else f"BELOW TARGET ({ann_ret:+.1f}% est.)"

    # Factor correlation table
    factor_lines = ["*Factor Correlations vs Realized Returns*"]
    for col, label in FACTORS:
        r = correlations.get(col, 0.0)
        sig = _significance(r, n)
        cfg_key = col.replace("score_", "").replace("_", "")
        # Find config key match
        new_w = next((v for k, v in rw.items() if k.replace("_", "") in cfg_key or cfg_key in k.replace("_", "")), None)
        cur_w = next((v for k, v in cw.items() if k.replace("_", "") in cfg_key or cfg_key in k.replace("_", "")), None)
        if new_w is not None and cur_w is not None:
            delta = round(new_w - cur_w, 4)
            delta_str = f"{delta:+.0%}" if delta != 0 else "no change"
            weight_str = f"  weight: {cur_w:.0%} → {new_w:.0%} ({delta_str})"
        else:
            weight_str = ""

        bar = "+" if r > 0.15 else ("-" if r < -0.05 else "~")
        factor_lines.append(
            f"  {bar} *{label}*  r={r:+.3f} {sig}{weight_str}"
        )

    perf_lines = [
        f"*Win rate:* {report['win_rate']}% ({n} closed positions)",
        f"*Avg winner:* +{report['avg_winner']:.1f}%  |  *Avg loser:* {report['avg_loser']:.1f}%",
        f"*Best:* {report['best']['ticker']} {report['best']['return']:+.1f}%  "
        f"|  *Worst:* {report['worst']['ticker']} {report['worst']['return']:+.1f}%",
        f"*18% CAGR target:* {track_label}",
    ]

    weight_change_lines = ["*Recommended weight changes (pending your approval):*"]
    for k, new_w in rw.items():
        cur_w = cw.get(k, new_w)
        delta = round(new_w - cur_w, 4)
        if abs(delta) >= 0.005:
            weight_change_lines.append(f"  • {k}: {cur_w:.0%} → {new_w:.0%}")
    if len(weight_change_lines) == 1:
        weight_change_lines.append("  No changes recommended — model weights remain optimal.")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Model Report Card — {quarter_label}"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(perf_lines)}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(factor_lines)}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(weight_change_lines)}},
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": (
                "Weights auto-update at next monthly rebalance if approved. "
                "Correlations use Spearman rank (robust to outliers). "
                f"Generated {date_str}."
            )}],
        },
    ]
    return blocks


def is_quarter_start(now: datetime) -> bool:
    """Returns True if today is the 1st of Jan, Apr, Jul, or Oct."""
    return now.day == 1 and now.month in (1, 4, 7, 10)
