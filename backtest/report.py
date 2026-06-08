"""
Backtest reporting and formatting.
"""
import json
from datetime import datetime


def format_backtest_report(portfolio_result: dict) -> str:
    """
    Format portfolio backtest as human-readable report.
    """
    lines = []

    summary = portfolio_result.get("summary", {})
    timestamp = portfolio_result.get("timestamp", "unknown")

    lines.append("=" * 80)
    lines.append("WARREN B TRADING MODEL - BACKTEST REPORT")
    lines.append("=" * 80)
    lines.append(f"Timestamp: {timestamp}")
    lines.append("")

    # Summary
    lines.append("EXECUTIVE SUMMARY")
    lines.append("-" * 80)
    lines.append(f"Decision: {summary.get('go_nogo', 'UNKNOWN')}")
    lines.append(f"Pass Rate: {summary.get('pass_rate', 0)*100:.0f}% ({summary.get('passed', 0)}/{len(portfolio_result.get('portfolio', []))} stocks)")
    lines.append(f"Avg Confidence: {summary.get('avg_confidence', 0):.2f}")
    lines.append(f"Failed: {summary.get('failed', 0)}, Errored: {summary.get('errored', 0)}")
    lines.append("")

    # Rationale
    lines.append("DECISION RATIONALE")
    lines.append("-" * 80)

    go_nogo = summary.get('go_nogo', 'UNKNOWN')
    if go_nogo == 'GO':
        lines.append("✓ Model PASSES walk-forward validation")
        lines.append("✓ Sufficient pass rate for paper trading")
        lines.append("✓ Backtest confidence meets threshold")
        lines.append("")
        lines.append("NEXT STEPS:")
        lines.append("1. Start paper trading with $10-25K capital")
        lines.append("2. Monitor daily P&L vs SPY benchmark")
        lines.append("3. Validate signal quality (target: 55%+ win rate)")
        lines.append("4. If 2+ week validation passes, move to Phase 2 (live capital)")
    else:
        lines.append("✗ Model FAILS walk-forward validation")
        lines.append("✗ Insufficient pass rate or confidence")
        lines.append("")
        lines.append("INVESTIGATION REQUIRED:")
        lines.append("1. Review failing stocks - identify common issues")
        lines.append("2. Check if signals are too aggressive or too conservative")
        lines.append("3. Validate data quality (earnings, analyst revisions)")
        lines.append("4. Consider tuning entry threshold (currently 0.65)")

    lines.append("")

    # Individual results
    lines.append("INDIVIDUAL STOCK RESULTS")
    lines.append("-" * 80)

    for result in portfolio_result.get("results", []):
        ticker = result.get("ticker", "?")
        status = result.get("status", "?")
        confidence = result.get("confidence", 0)
        notes = result.get("notes", "")

        status_symbol = "✓" if status == "PASS" else "✗" if status == "FAIL" else "!"

        lines.append(f"{status_symbol} {ticker:6} ({status:6}) [Conf: {confidence:.2f}] {notes}")

    lines.append("")
    lines.append("=" * 80)

    return "\n".join(lines)


def save_backtest_report(portfolio_result: dict, filepath: str):
    """Save backtest report to JSON file."""
    with open(filepath, "w") as f:
        json.dump(portfolio_result, f, indent=2)
