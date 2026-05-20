"""Gmail SMTP alert sender. Reads credentials from config.json."""
from __future__ import annotations

import json
import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"

logger = logging.getLogger("alerts")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _load_email_cfg() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["email"]


def _table_html(stocks: list[dict]) -> str:
    if not stocks:
        return "<p>No stocks.</p>"
    rows = "".join(
        f"<tr>"
        f"<td><b>{s['ticker']}</b></td>"
        f"<td>{s['company_name']}</td>"
        f"<td>${s['price']}</td>"
        f"<td style='color:{'green' if s['change_pct']>=0 else 'red'}'>{s['change_pct']:+.2f}%</td>"
        f"<td>{s['volume_spike']:.2f}x</td>"
        f"<td>{s['beta']}</td>"
        f"<td>{s['signal']}</td>"
        f"<td>{s['sector']}</td>"
        f"</tr>"
        for s in stocks
    )
    return (
        "<table style='border-collapse:collapse;font-family:Arial,sans-serif;font-size:14px' border='1' cellpadding='6'>"
        "<thead style='background:#f0f0f0'><tr>"
        "<th>Ticker</th><th>Company</th><th>Price</th><th>24h %</th>"
        "<th>Volume Spike</th><th>Beta</th><th>Signal</th><th>Sector</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def _send(subject: str, html_body: str) -> bool:
    cfg = _load_email_cfg()
    # Env vars take precedence (GitHub Actions / production); config.json is fallback for local dev
    sender = os.environ.get("EMAIL_SENDER") or cfg.get("sender", "")
    password = os.environ.get("EMAIL_PASSWORD") or cfg.get("password", "")
    recipient = os.environ.get("EMAIL_RECIPIENT") or cfg.get("recipient", "")

    if not password or password == "your_app_password":
        logger.warning("Email password not configured; skipping send: %s", subject)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(sender, password)
            server.sendmail(sender, [recipient], msg.as_string())
        logger.info("Sent email: %s", subject)
        return True
    except Exception as e:
        logger.error("Failed to send email '%s': %s", subject, e)
        return False


def new_match_alert(stocks: list[dict]) -> bool:
    if not stocks:
        return False
    body = (
        f"<h2>New stocks matched your screener ({len(stocks)})</h2>"
        + _table_html(stocks)
    )
    return _send(f"[Screener] {len(stocks)} new match(es)", body)


def volume_spike_alert(stocks: list[dict]) -> bool:
    if not stocks:
        return False
    body = (
        f"<h2>Volume spike detected ({len(stocks)})</h2>"
        "<p>These stocks have volume &ge; 3x their 20-day average.</p>"
        + _table_html(stocks)
    )
    return _send(f"[Screener] Volume spike: {len(stocks)} stock(s)", body)


def price_breakout_alert(stocks: list[dict]) -> bool:
    if not stocks:
        return False
    body = (
        f"<h2>52-week high breakout ({len(stocks)})</h2>"
        + _table_html(stocks)
    )
    return _send(f"[Screener] 52w high breakout: {len(stocks)} stock(s)", body)


def daily_digest(all_matches: list[dict]) -> bool:
    body = (
        f"<h2>Daily screener digest — {len(all_matches)} matches</h2>"
        "<p>Summary of all stocks matching your criteria at market close.</p>"
        + _table_html(all_matches)
    )
    return _send(f"[Screener] Daily digest — {len(all_matches)} matches", body)


def send_ai_buy_alert(ticker: str, company_name: str, price: float, sector: str, report: dict) -> bool:
    """Send a premium HTML alert when the AI scanner returns a BULLISH verdict."""
    confidence = report.get("confidence", "N/A")
    situation = report.get("company_situation", "")
    bull = report.get("bull_case", []) or []
    bear = report.get("bear_case", []) or []

    bull_items = "".join(f"<li style='margin:6px 0'>{b}</li>" for b in bull)
    bear_items = "".join(f"<li style='margin:6px 0'>{b}</li>" for b in bear)

    html = f"""
    <div style="background:#0b1220;color:#e6edf3;font-family:Inter,Arial,sans-serif;padding:32px;border-radius:12px;max-width:680px;margin:auto">
      <div style="background:linear-gradient(90deg,#10b981,#34d399);color:#04130d;padding:10px 18px;border-radius:999px;display:inline-block;font-weight:700;letter-spacing:.5px;box-shadow:0 0 24px rgba(16,185,129,.55)">
        AI BUY RECOMMENDATION
      </div>
      <h1 style="margin:20px 0 4px;font-size:32px">{ticker} <span style="color:#9ca3af;font-weight:400;font-size:20px">— {company_name}</span></h1>
      <div style="color:#9ca3af;margin-bottom:18px">{sector} &middot; ${price}</div>

      <div style="background:#111a2e;border:1px solid #1f2a44;border-radius:10px;padding:16px 18px;margin-bottom:18px">
        <div style="font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:1px">AI Confidence</div>
        <div style="font-size:28px;font-weight:700;color:#34d399">{confidence}%</div>
      </div>

      <h3 style="color:#e6edf3;border-left:3px solid #34d399;padding-left:10px">Situation</h3>
      <p style="color:#cbd5e1;line-height:1.6">{situation}</p>

      <h3 style="color:#34d399;border-left:3px solid #34d399;padding-left:10px">Bull Case</h3>
      <ul style="color:#cbd5e1;line-height:1.6;padding-left:22px">{bull_items}</ul>

      <h3 style="color:#f87171;border-left:3px solid #f87171;padding-left:10px">Bear Case</h3>
      <ul style="color:#cbd5e1;line-height:1.6;padding-left:22px">{bear_items}</ul>

      <div style="margin-top:24px;font-size:12px;color:#6b7280;border-top:1px solid #1f2a44;padding-top:14px">
        Generated by the 24/7 AI Stock Screener &middot; This is not financial advice.
      </div>
    </div>
    """
    return _send(f"[AI BUY] {ticker} — {company_name} (BULLISH, {confidence}%)", html)


def test_email() -> bool:
    return _send("[Screener] Test email", "<p>Your stock screener email is configured correctly.</p>")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    ok = test_email()
    print("Sent" if ok else "Failed/skipped")
