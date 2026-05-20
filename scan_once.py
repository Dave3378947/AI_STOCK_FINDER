"""Single-pass scan entry point for GitHub Actions cron.

Runs one screener pass, AI-analyses any new matches, emails BULLISH verdicts,
then exits. State persists across runs because the workflow commits results.json
back to the repo.
"""
from __future__ import annotations

import logging
import sys

import scheduler
import server


def main() -> int:
    scheduler._setup_logging()
    logger = logging.getLogger("scan_once")
    server.load_env()  # picks up GEMINI_API_KEY (local .env or GitHub Actions env)
    logger.info("=== scan_once starting ===")
    try:
        scheduler.run_once()
    except Exception as e:
        logger.exception("scan_once failed: %s", e)
        return 1
    logger.info("=== scan_once finished ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
