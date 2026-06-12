"""Warren B API routes for trade decision approval."""
import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from api.warren_b_decision import get_warren_decision, format_decision_for_slack
from api.paper_portfolio import log_warren_decision

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/warren-b", tags=["warren-b"])


class DecisionRequest(BaseModel):
    """Trade decision request for Warren B approval."""
    ticker: str
    action: str  # "BUY" or "SELL"
    signal_score: float  # 0.0-1.0
    position_size: int
    signal_rationale: str
    market_regime: str = "normal"
    portfolio_beta: float = 1.0


class DecisionResponse(BaseModel):
    """Warren B decision response."""
    approved: bool
    confidence: float
    reasoning: str
    recommendation: str  # "PROCEED", "REDUCE_SIZE", "SKIP", "HALT"
    slack_formatted: str


@router.post("/decide")
async def decide_trade(request: DecisionRequest) -> DecisionResponse:
    """
    Get Warren B's approval for a trade.

    Args:
        ticker: Stock ticker
        action: "BUY" or "SELL"
        signal_score: Composite signal score (0.0-1.0)
        position_size: Number of shares
        signal_rationale: Why the signal was generated
        market_regime: Market condition ("normal", "elevated", "crisis", "low_vol")
        portfolio_beta: Current portfolio beta

    Returns:
        Warren B's decision with approval, confidence, and reasoning.
    """

    try:
        decision = await get_warren_decision(
            ticker=request.ticker,
            action=request.action,
            signal_score=request.signal_score,
            position_size=request.position_size,
            signal_rationale=request.signal_rationale,
            market_regime=request.market_regime,
            portfolio_beta=request.portfolio_beta,
        )

        slack_msg = format_decision_for_slack(request.ticker, request.action, decision)

        # Log decision to database
        try:
            log_warren_decision(
                ticker=request.ticker,
                decision_type=request.action,
                recommendation=decision.get("recommendation", "SKIP"),
                rationale=decision.get("reasoning", ""),
                model_score=request.signal_score,
                outcome=decision.get("reasoning", ""),
            )
        except Exception as e:
            logger.warning(f"Failed to log Warren B decision: {e}")

        return DecisionResponse(
            approved=decision.get("approved", False),
            confidence=decision.get("confidence", 0.5),
            reasoning=decision.get("reasoning", ""),
            recommendation=decision.get("recommendation", "SKIP"),
            slack_formatted=slack_msg,
        )

    except Exception as e:
        logger.error(f"Warren B decision error for {request.ticker}: {e}")
        raise HTTPException(status_code=500, detail=f"Warren B decision error: {str(e)}")
