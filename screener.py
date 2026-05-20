"""Stock screener: fetches S&P 500 data via yfinance and applies user filters."""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
RESULTS_PATH = ROOT / "results.json"
LAST_RESULTS_PATH = ROOT / "last_results.json"
LOG_PATH = ROOT / "screener.log"

logger = logging.getLogger("screener")


def load_config() -> dict:
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_sp500_tickers() -> list[str]:
    """Scrape S&P 500 tickers from Wikipedia. Falls back to a small hardcoded list."""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    try:
        import io
        headers = {"User-Agent": "Mozilla/5.0 (stock-screener)"}
        html = requests.get(url, headers=headers, timeout=15).text
        tables = pd.read_html(io.StringIO(html))
        df = tables[0]
        tickers = [str(t).replace(".", "-") for t in df["Symbol"].tolist()]
        return tickers
    except Exception as e:
        logger.warning("Failed to fetch S&P 500 list (%s). Using fallback.", e)
        return [
            "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA", "AMD",
            "AVGO", "ORCL", "CRM", "ADBE", "NFLX", "INTC", "QCOM",
            "JNJ", "PFE", "UNH", "LLY", "MRK", "ABBV", "TMO", "ABT", "DHR",
        ]


def get_us_market_tickers() -> list[str]:
    """Fetch every NASDAQ + NYSE + AMEX listed common stock (~8,000) from NASDAQ Trader.

    Two pipe-delimited public files, no API key required:
      - nasdaqlisted.txt  → NASDAQ-listed symbols
      - otherlisted.txt   → NYSE, NYSE American (AMEX), NYSE Arca, BATS
    """
    sources = [
        ("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt", "Symbol", "Test Issue", "ETF"),
        ("https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt", "ACT Symbol", "Test Issue", "ETF"),
    ]
    headers = {"User-Agent": "Mozilla/5.0 (stock-screener)"}
    tickers: set[str] = set()

    for url, sym_col, test_col, etf_col in sources:
        try:
            text = requests.get(url, headers=headers, timeout=20).text
            lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation")]
            if len(lines) < 2:
                continue
            header = lines[0].split("|")
            sym_i = header.index(sym_col)
            test_i = header.index(test_col)
            etf_i = header.index(etf_col)
            for line in lines[1:]:
                parts = line.split("|")
                if len(parts) <= max(sym_i, test_i, etf_i):
                    continue
                if parts[test_i] == "Y" or parts[etf_i] == "Y":
                    continue
                sym = parts[sym_i].strip()
                # Skip warrants/units/preferreds/rights (contain $ or .) — yfinance handles - for B-shares
                if not sym or any(c in sym for c in "$.^"):
                    continue
                tickers.add(sym.replace(".", "-"))
        except Exception as e:
            logger.warning("Failed to fetch %s: %s", url, e)

    if not tickers:
        logger.warning("US market fetch returned nothing; falling back to S&P 500")
        return get_sp500_tickers()
    return sorted(tickers)


def get_tickers_for_universe(universe: str) -> list[str]:
    """Pick the ticker universe based on config: 'sp500' (default) or 'us_all'."""
    if universe == "us_all":
        return get_us_market_tickers()
    return get_sp500_tickers()


def _signal(change_pct: float, volume_spike: float) -> str:
    if change_pct > 8 and volume_spike > 3:
        return "Strong buy"
    if change_pct > 5 or volume_spike > 3:
        return "Breakout"
    return "Momentum"


def fetch_ticker_data(ticker: str) -> dict | None:
    """Fetch and assemble per-ticker fields needed by filters."""
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}

        # 3-month history provides enough data points for 14-day RSI and 20/50 EMAs
        hist = t.history(period="3mo", interval="1d", auto_adjust=False)
        if hist.empty or len(hist) < 2:
            return None

        last_close = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2])
        change_pct = (last_close - prev_close) / prev_close * 100.0 if prev_close else 0.0

        today_volume = float(hist["Volume"].iloc[-1])
        avg_volume = float(hist["Volume"].iloc[-21:-1].mean()) if len(hist) >= 21 else float(hist["Volume"].mean())
        volume_spike = today_volume / avg_volume if avg_volume > 0 else 0.0

        beta = info.get("beta") or info.get("beta3Year") or 0.0
        market_cap = info.get("marketCap") or 0
        sector = info.get("sector") or "Unknown"
        company_name = info.get("shortName") or info.get("longName") or ticker
        fifty_two_high = info.get("fiftyTwoWeekHigh") or float(hist["High"].max())

        # 14-day RSI (Relative Strength Index)
        rsi_val = 50.0
        if len(hist) >= 15:
            delta = hist["Close"].diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(window=14, min_periods=14).mean()
            avg_loss = loss.rolling(window=14, min_periods=14).mean()
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            rsi_val = float(rsi.iloc[-1])
            if pd.isna(rsi_val):
                rsi_val = 50.0

        # 20/50 EMA Trend Crossover
        trend = "Neutral"
        if len(hist) >= 50:
            ema_20 = hist["Close"].ewm(span=20, adjust=False).mean()
            ema_50 = hist["Close"].ewm(span=50, adjust=False).mean()
            last_ema_20 = float(ema_20.iloc[-1])
            last_ema_50 = float(ema_50.iloc[-1])
            trend = "Bullish" if last_ema_20 > last_ema_50 else "Bearish"

        # Extract last 20 daily closes for UI sparklines and trend charts
        recent_closes = hist["Close"].iloc[-20:].round(2).tolist()
        recent_dates = hist.index[-20:].strftime("%Y-%m-%d").tolist()

        return {
            "ticker": ticker,
            "company_name": company_name,
            "price": round(last_close, 2),
            "change_pct": round(change_pct, 2),
            "volume_spike": round(volume_spike, 2),
            "beta": round(float(beta), 2) if beta else 0.0,
            "market_cap_million": round(market_cap / 1_000_000, 1),
            "sector": sector,
            "fifty_two_week_high": round(float(fifty_two_high), 2),
            "at_52w_high": last_close >= float(fifty_two_high) * 0.995,
            "signal": _signal(change_pct, volume_spike),
            "rsi": round(rsi_val, 1),
            "trend": trend,
            "recent_closes": recent_closes,
            "recent_dates": recent_dates,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        logger.debug("Skipping %s: %s", ticker, e)
        return None


def passes_filters(stock: dict, cfg: dict) -> bool:
    f = cfg["filters"]
    sectors = cfg.get("sectors") or []
    if stock["beta"] < f["min_beta"]:
        return False
    if stock["volume_spike"] < f["min_volume_spike"]:
        return False
    if stock["change_pct"] < f["min_price_change_pct"]:
        return False
    if stock["market_cap_million"] < f["min_market_cap_million"]:
        return False
    if sectors and stock["sector"] not in sectors:
        return False
    return True


def load_last_results() -> list[dict]:
    if LAST_RESULTS_PATH.exists():
        try:
            with open(LAST_RESULTS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("matches", [])
        except Exception:
            return []
    return []


def run_screener() -> dict:
    """Run a full screening pass. Returns dict with matches and new_matches."""
    cfg = load_config()
    universe = cfg.get("universe", "sp500")
    tickers = get_tickers_for_universe(universe)
    logger.info("Scanning %d tickers from universe=%s...", len(tickers), universe)

    matches: list[dict] = []
    scanned = 0
    
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    # Use ThreadPoolExecutor for high-speed parallel network requests.
    # Scale workers up for the full US-market universe (~8k tickers).
    max_workers = 30 if len(tickers) > 1000 else 15
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ticker = {executor.submit(fetch_ticker_data, ticker): ticker for ticker in tickers}
        
        for future in as_completed(future_to_ticker):
            ticker = future_to_ticker[future]
            scanned += 1
            if scanned % 25 == 0:
                logger.info("Progress: %d/%d tickers scanned (%d matched so far)...", scanned, len(tickers), len(matches))
            try:
                data = future.result()
                if data is not None and passes_filters(data, cfg):
                    matches.append(data)
            except Exception as e:
                logger.debug("Error scanning %s: %s", ticker, e)

    previous = load_last_results()
    prev_tickers = {s["ticker"] for s in previous}
    new_matches = [s for s in matches if s["ticker"] not in prev_tickers]
    volume_spikes = [s for s in matches if s["volume_spike"] >= 3.0]
    breakouts = [s for s in matches if s.get("at_52w_high")]

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scanned": scanned,
        "matched": len(matches),
        "matches": matches,
    }

    # Rotate: current → last, new → current
    if RESULTS_PATH.exists():
        try:
            RESULTS_PATH.replace(LAST_RESULTS_PATH)
        except Exception:
            pass
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

    logger.info("Scan complete: %d matched, %d new", len(matches), len(new_matches))
    return {
        "matches": matches,
        "new_matches": new_matches,
        "volume_spikes": volume_spikes,
        "breakouts": breakouts,
        "scanned": scanned,
    }


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()],
    )


if __name__ == "__main__":
    _setup_logging()
    result = run_screener()
    print(f"Matched: {len(result['matches'])}, New: {len(result['new_matches'])}")
