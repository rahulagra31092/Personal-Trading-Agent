#!/usr/bin/env python3
"""
Entry point for n8n to call at 7am ET on weekdays.
n8n command: python C:\Claude\Trading Analyst\scripts\slack_briefing.py
"""
import sys

sys.path.insert(0, r"C:\Claude\Trading Analyst")

from api.briefing import BRIEFING_TICKERS, send_slack_briefing

if __name__ == "__main__":
    send_slack_briefing(BRIEFING_TICKERS)
