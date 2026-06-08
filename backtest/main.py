#!/usr/bin/env python3
"""
Main entry point for backtest execution.
"""
import logging
import json
import sys
import io
from backtest.runner import run_portfolio_backtest
from backtest.report import format_backtest_report, save_backtest_report
from backtest.diagnostics import analyze_data_quality

# Set UTF-8 encoding for console output on Windows
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    logger.info("Starting portfolio backtest...")

    portfolio_result = run_portfolio_backtest()

    # Print report
    report_text = format_backtest_report(portfolio_result)
    print(report_text)

    # Run diagnostics for all 10 stocks
    logger.info("\n" + "="*80)
    logger.info("Running data quality diagnostics for all portfolio stocks...")
    logger.info("="*80)

    portfolio_stocks = ["AAPL", "MSFT", "NVDA", "TSLA", "META", "GOOGL", "AMZN", "JPM", "V", "JNJ"]
    diagnostics_summary = []

    for ticker in portfolio_stocks:
        logger.info(f"\nAnalyzing {ticker}...")
        try:
            diag = analyze_data_quality(ticker)
            diagnostics_summary.append(diag)

            # Print recommendation for each stock
            recommendation = diag.get("recommendation", "No issues detected")
            if recommendation != "Data quality is healthy":
                logger.warning(f"  {ticker}: {recommendation}")
            else:
                logger.info(f"  {ticker}: OK")

        except Exception as e:
            logger.error(f"Failed to analyze {ticker}: {e}")

    # Save diagnostics
    with open("diagnostics_results.json", "w") as f:
        json.dump(diagnostics_summary, f, indent=2, default=str)
    logger.info("\nDiagnostics saved to diagnostics_results.json")

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
