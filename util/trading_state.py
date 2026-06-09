"""
Trading state management for daily P&L tracking and circuit breaker.

Tracks:
- Daily cumulative P&L
- Consecutive loss streak
- Circuit breaker status
- Alerts on trigger
"""
import logging
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Optional, List

logger = logging.getLogger(__name__)

# Delayed import to avoid circular dependency
_alert_module = None

def _get_alert_module():
    global _alert_module
    if _alert_module is None:
        try:
            from api import circuit_breaker_alerts
            _alert_module = circuit_breaker_alerts
        except ImportError:
            _alert_module = False  # Mark as unavailable
    return _alert_module if _alert_module else None

_ET = timezone(timedelta(hours=-5))


@dataclass
class Trade:
    """Single trade record."""
    entry_price: float
    exit_price: float
    timestamp: str

    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) / self.entry_price


@dataclass
class TradingState:
    """Daily trading state and circuit breaker management."""

    daily_trades: List[Trade] = field(default_factory=list)
    daily_pnl: float = 0.0  # Sum of all trade returns today
    daily_loss_pct: float = 0.0  # daily_pnl / initial_capital
    consecutive_losses: int = 0
    circuit_breaker_open: bool = False

    # Config
    max_daily_loss: float = 0.025  # 2.5% of capital
    max_consecutive_losses: int = 3
    initial_capital: float = 100000.0  # Base capital for loss % calculation

    def record_trade(self, entry_price: float, exit_price: float) -> None:
        """Record a completed trade and update state."""
        trade = Trade(entry_price=entry_price, exit_price=exit_price, timestamp=datetime.now(_ET).isoformat())
        self.daily_trades.append(trade)

        # Update daily P&L
        trade_return = (exit_price - entry_price) / entry_price
        self.daily_pnl += trade_return
        self.daily_loss_pct = self.daily_pnl / self.initial_capital

        # Update consecutive loss streak
        if trade_return < 0:
            self.consecutive_losses += 1
            logger.warning(
                "Trade closed at loss: %.2f%% | Consecutive losses: %d | Daily P&L: %.2f%%",
                trade_return * 100, self.consecutive_losses, self.daily_pnl * 100
            )
        else:
            self.consecutive_losses = 0
            logger.info(
                "Trade closed at profit: %.2f%% | Daily P&L: %.2f%%",
                trade_return * 100, self.daily_pnl * 100
            )

        # Check circuit breaker
        if self._should_open_circuit_breaker():
            self.circuit_breaker_open = True
            logger.error(
                "CIRCUIT BREAKER OPEN: daily_loss=%.2f%%, consecutive_losses=%d",
                self.daily_loss_pct * 100, self.consecutive_losses
            )

    def is_circuit_breaker_open(self) -> bool:
        """Check if circuit breaker is open (halt trading)."""
        return self.circuit_breaker_open

    def _should_open_circuit_breaker(self) -> bool:
        """Check if circuit breaker conditions are met and send alerts."""
        if self.daily_loss_pct <= -self.max_daily_loss:
            logger.error(
                "Circuit breaker condition: daily_loss %.2f%% >= max %.2f%%",
                -self.daily_loss_pct * 100, self.max_daily_loss * 100
            )
            # Send Slack alert
            alerts = _get_alert_module()
            if alerts:
                alerts.send_circuit_breaker_alert(
                    reason="daily_loss",
                    daily_loss_pct=self.daily_loss_pct,
                    consecutive_losses=self.consecutive_losses,
                    max_daily_loss=self.max_daily_loss,
                    max_consecutive_losses=self.max_consecutive_losses,
                )
            return True

        if self.consecutive_losses >= self.max_consecutive_losses:
            logger.error(
                "Circuit breaker condition: consecutive_losses %d >= max %d",
                self.consecutive_losses, self.max_consecutive_losses
            )
            # Send Slack alert
            alerts = _get_alert_module()
            if alerts:
                alerts.send_circuit_breaker_alert(
                    reason="consecutive_losses",
                    daily_loss_pct=self.daily_loss_pct,
                    consecutive_losses=self.consecutive_losses,
                    max_daily_loss=self.max_daily_loss,
                    max_consecutive_losses=self.max_consecutive_losses,
                )
            return True

        return False

    def reset_daily(self) -> None:
        """Reset daily state at market open."""
        self.daily_trades = []
        self.daily_pnl = 0.0
        self.daily_loss_pct = 0.0
        self.consecutive_losses = 0
        self.circuit_breaker_open = False
        logger.info("Daily trading state reset")

    def to_dict(self) -> dict:
        """Serialize to dict for API response."""
        return {
            "daily_trades": len(self.daily_trades),
            "daily_pnl": round(self.daily_pnl, 4),
            "daily_loss_pct": round(self.daily_loss_pct, 4),
            "consecutive_losses": self.consecutive_losses,
            "circuit_breaker_open": self.circuit_breaker_open,
            "max_daily_loss_pct": round(self.max_daily_loss, 4),
            "max_consecutive_losses": self.max_consecutive_losses,
        }


# Global trading state (reset at market open each day)
_trading_state = TradingState()


def get_trading_state() -> TradingState:
    """Get global trading state."""
    global _trading_state
    return _trading_state


def reset_daily_state() -> None:
    """Reset trading state at market open."""
    global _trading_state
    _trading_state.reset_daily()


def record_trade(entry_price: float, exit_price: float) -> None:
    """Record a completed trade."""
    global _trading_state
    _trading_state.record_trade(entry_price, exit_price)
