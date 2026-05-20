"""24/7 background scanner. Triggers an instant email the moment the AI flags a BULLISH buy."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import schedule

import alerts
import screener
import server  # for call_gemini_with_failover / run_ai_analysis

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
LOG_PATH = ROOT / "screener.log"

logger = logging.getLogger("scheduler")

# Pace AI requests to avoid rate-limit spikes
AI_REQUEST_DELAY_SEC = 2


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_and_alert(stock: dict, ai_alerts_enabled: bool) -> None:
    """Run AI analysis on a single stock. If verdict is BULLISH, email IMMEDIATELY."""
    ticker = stock["ticker"]
    try:
        report = server.run_ai_analysis(ticker)
    except Exception as e:
        logger.warning("AI analysis failed for %s: %s", ticker, e)
        return

    verdict = (report.get("verdict") or "").upper()
    confidence = report.get("confidence", "N/A")
    logger.info("AI verdict for %s: %s (confidence=%s)", ticker, verdict, confidence)

    if verdict == "BULLISH" and ai_alerts_enabled:
        ok = alerts.send_ai_buy_alert(
            ticker=ticker,
            company_name=stock.get("company_name", ticker),
            price=stock.get("price", report.get("_price", 0.0)),
            sector=stock.get("sector", report.get("_sector", "Unknown")),
            report=report,
        )
        if ok:
            logger.info("🚀 Sent AI BUY alert for %s", ticker)
        else:
            logger.error("Failed to send AI BUY alert for %s", ticker)


def run_once() -> None:
    logger.info("Starting 24/7 scan...")
    result = screener.run_screener()
    cfg = load_config()
    alert_cfg = cfg.get("alerts", {})
    ai_alerts_enabled = bool(alert_cfg.get("ai_buy_alerts", True))

    # Standard non-AI alerts (kept for parity)
    if alert_cfg.get("volume_spike") and result["volume_spikes"]:
        alerts.volume_spike_alert(result["volume_spikes"])
    if alert_cfg.get("price_breakout") and result["breakouts"]:
        alerts.price_breakout_alert(result["breakouts"])

    new_matches = result.get("new_matches", [])
    logger.info(
        "Scan complete: scanned=%d matched=%d new=%d — running AI on new matches",
        result["scanned"], len(result["matches"]), len(new_matches),
    )

    # Event-driven AI evaluation: any new match gets analyzed; BULLISH ones email instantly
    for stock in new_matches:
        analyze_and_alert(stock, ai_alerts_enabled)
        time.sleep(AI_REQUEST_DELAY_SEC)


def daily_digest_job() -> None:
    cfg = load_config()
    if not cfg.get("alerts", {}).get("daily_digest"):
        return
    logger.info("Sending daily digest...")
    result = screener.run_screener()
    alerts.daily_digest(result["matches"])


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )


def main() -> None:
    _setup_logging()
    # Load .env so GEMINI_API_KEY is available to server.run_ai_analysis
    server.load_env()
    logger.info("24/7 stock screener scheduler starting...")

    try:
        run_once()
    except Exception as e:
        logger.exception("Initial run failed: %s", e)

    # Run continuously, 24/7 — no market-hours gating
    schedule.every(30).minutes.do(run_once)
    schedule.every().day.at("16:05").do(daily_digest_job)

    print("Scheduler running 24/7. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
