"""Warren B Decision Layer — AI-powered trade approval system."""
import logging
from anthropic import Anthropic
from config import CLAUDE_API_KEY, CLAUDE_MODEL_SONNET

logger = logging.getLogger(__name__)

client = Anthropic(api_key=CLAUDE_API_KEY)


async def get_warren_decision(
    ticker: str,
    action: str,
    signal_score: float,
    position_size: int,
    signal_rationale: str,
    market_regime: str = "normal",
    portfolio_beta: float = 1.0,
) -> dict:
    """
    Get Warren B's approval for a trade decision.

    Uses Claude to analyze trade signals and provide AI-powered approval/rejection
    with reasoning and risk assessment.

    Args:
        ticker: Stock ticker (e.g., "AAPL")
        action: "BUY" or "SELL"
        signal_score: Composite signal score (0.0-1.0)
        position_size: Number of shares
        signal_rationale: Explanation from signal model
        market_regime: "normal", "elevated", "crisis", "low_vol"
        portfolio_beta: Current portfolio beta

    Returns:
        {
            "approved": bool,
            "confidence": 0.0-1.0,
            "reasoning": str,
            "recommendation": "PROCEED" | "REDUCE_SIZE" | "SKIP" | "HALT"
        }
    """

    prompt = f"""You are Warren B, an AI financial advisor reviewing a trading signal.

TRADE REQUEST:
- Ticker: {ticker}
- Action: {action}
- Signal Score: {signal_score:.2f} (0.0=avoid, 0.5=neutral, 1.0=very high)
- Position Size: {position_size} shares
- Signal Rationale: {signal_rationale}

MARKET CONDITIONS:
- Regime: {market_regime}
- Portfolio Beta: {portfolio_beta:.2f}

DECISION FRAMEWORK:
1. Is the signal score strong enough? (BUY needs >0.65, SELL needs <0.35)
2. Does the position size match the conviction? (weak=reduce, strong=proceed)
3. Is portfolio beta too high? (>1.25 = reduce entry size)
4. Any regime-specific concerns? (crisis = reduce, low_vol = can be aggressive)

RESPOND IN JSON:
{{
    "approved": true/false,
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation",
    "recommendation": "PROCEED|REDUCE_SIZE|SKIP|HALT"
}}

Be concise. Consider both upside and downside risk."""

    try:
        response = client.messages.create(
            model=CLAUDE_MODEL_SONNET,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )

        text = response.content[0].text

        # Parse JSON response
        import json
        try:
            decision = json.loads(text)
        except json.JSONDecodeError:
            # Fallback if Claude didn't return valid JSON
            logger.warning(f"Failed to parse Warren B response for {ticker}: {text}")
            decision = {
                "approved": signal_score > 0.65 if action == "BUY" else signal_score < 0.35,
                "confidence": signal_score,
                "reasoning": "Claude response parsing failed, using signal score fallback",
                "recommendation": "PROCEED" if signal_score > 0.65 else "SKIP"
            }

        return decision

    except Exception as e:
        logger.error(f"Warren B decision error for {ticker}: {e}")
        # Fallback: approve only strong signals
        return {
            "approved": signal_score > 0.70,
            "confidence": 0.5,
            "reasoning": f"Warren B error: {str(e)}, using conservative fallback",
            "recommendation": "PROCEED" if signal_score > 0.70 else "SKIP"
        }


def format_decision_for_slack(ticker: str, action: str, decision: dict) -> str:
    """Format Warren B decision for Slack notification."""
    status = "APPROVED" if decision["approved"] else "REJECTED"
    conf = decision.get("confidence", 0)
    rec = decision.get("recommendation", "SKIP")
    reason = decision.get("reasoning", "No reasoning provided")

    return f"""
{status} | {ticker} {action}
Confidence: {conf:.0%}
Recommendation: {rec}
Reasoning: {reason}
"""
