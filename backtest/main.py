#!/usr/bin/env python3
"""
Main entry point for backtest execution.
"""
import logging
import json
from backtest.runner import run_portfolio_backtest
from backtest.report import format_backtest_report, save_backtest_report

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info("Starting portfolio backtest...")

    portfolio_result = run_portfolio_backtest()

    # Print report
    report_text = format_backtest_report(portfolio_result)
    print(report_text)

    # Save result
    save_backtest_report(portfolio_result, "backtest_results.json")
    logger.info("Results saved to backtest_results.json")

    # Decision
    decision = portfolio_result["summary"]["go_nogo"]
    if decision == "GO":
        logger.info("✓ DECISION: GO - Paper trading approved for June 9")
        exit(0)
    else:
        logger.warning("✗ DECISION: NO-GO - Investigation required")
        exit(1)
