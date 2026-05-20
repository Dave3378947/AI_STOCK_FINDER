import os
import random
import time
import requests
import http.server
import socketserver
import json
import threading
from pathlib import Path
import screener

# Cascading Gemini model fallbacks for resilience against 503/429 errors
MODELS_CASCADE = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.0-flash-lite"]
MAX_RETRIES_PER_MODEL = 3


def call_gemini_with_failover(prompt: str) -> dict:
    """Call Gemini with cascading model fallback + exponential backoff on 503/429."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY is not defined. Please add it to your .env file in the project root.")

    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }

    last_error: Exception | None = None
    for model in MODELS_CASCADE:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        for attempt in range(MAX_RETRIES_PER_MODEL):
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=30)
            except requests.RequestException as e:
                last_error = e
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"[Gemini] {model} network error: {e}; retry in {wait:.1f}s")
                time.sleep(wait)
                continue

            if response.status_code == 200:
                res_data = response.json()
                try:
                    text_content = res_data["candidates"][0]["content"]["parts"][0]["text"]
                    return json.loads(text_content.strip())
                except (KeyError, IndexError, ValueError) as e:
                    raise Exception(f"Failed to parse Gemini model response as JSON: {e}. Raw response: {response.text}")

            if response.status_code in (503, 429):
                last_error = Exception(f"{model} returned {response.status_code}: {response.text[:200]}")
                wait = (2 ** attempt) + random.uniform(0, 1)
                print(f"[Gemini] {model} status {response.status_code}; retry {attempt + 1}/{MAX_RETRIES_PER_MODEL} in {wait:.1f}s")
                time.sleep(wait)
                continue

            # Non-retryable error
            raise Exception(f"Gemini API ({model}) returned error code {response.status_code}: {response.text}")

        print(f"[Gemini] Exhausted retries on {model}; falling back to next model")

    raise Exception(f"All Gemini models exhausted. Last error: {last_error}")

PORT = 8080
ROOT = Path(__file__).resolve().parent

def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in open(env_path, "r", encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ[key.strip()] = val.strip().strip('"').strip("'")

load_env()


def run_ai_analysis(ticker: str) -> dict:
    import yfinance as yf
    
    # 1. Read technical indicators from results.json
    results_path = ROOT / "results.json"
    stock_record = {}
    if results_path.exists():
        try:
            with open(results_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            matches = data.get("matches", [])
            stock_record = next((s for s in matches if s["ticker"] == ticker), {})
        except Exception as e:
            print(f"Error reading results.json: {e}")
            
    # 2. Fetch fundamentals and news from yfinance dynamically
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        news = t.news or []
    except Exception as e:
        raise Exception(f"Failed to fetch real-time data from Yahoo Finance: {e}")

    # Extract technicals, defaulting gracefully if not in results.json
    company_name = stock_record.get("company_name") or info.get("shortName") or info.get("longName") or ticker
    sector = stock_record.get("sector") or info.get("sector") or "Unknown"
    price = stock_record.get("price") or info.get("currentPrice") or info.get("regularMarketPrice") or 0.0
    change_pct = stock_record.get("change_pct") or 0.0
    rsi = stock_record.get("rsi") or "N/A"
    trend = stock_record.get("trend") or "Neutral"
    volume_spike = stock_record.get("volume_spike") or 1.0
    beta = stock_record.get("beta") or info.get("beta") or 0.0
    fifty_two_high = stock_record.get("fifty_two_week_high") or info.get("fiftyTwoWeekHigh") or 0.0

    # Extract fundamentals
    pe_ratio = info.get("trailingPE") or info.get("forwardPE") or "N/A"
    profit_margin = round(info.get("profitMargins") * 100.0, 2) if info.get("profitMargins") is not None else "N/A"
    dividend_yield = round(info.get("dividendYield") * 100.0, 2) if info.get("dividendYield") is not None else "N/A"
    description = info.get("longBusinessSummary") or "No business summary available."

    # Extract top 5 news articles
    news_lines = []
    for item in news[:5]:
        title = item.get("title", "")
        publisher = item.get("publisher", "Unknown")
        if title:
            news_lines.append(f"- {title} ({publisher})")
    news_summary = "\n".join(news_lines) if news_lines else "No recent news headlines available."

    # 3. Build prompt and call Gemini with cascading failover
    prompt = f"""
You are an expert Wall Street financial analyst agent. Analyze the following stock market data, fundamentals, and recent news for ticker {ticker}.

--- COMPANY DATA ---
Company Name: {company_name}
Sector: {sector}
Business Description: {description}

--- TECHNICAL METRICS ---
Current Price: ${price}
24h Price Change: {change_pct}%
14-day RSI: {rsi}
EMA 20 vs 50 Trend: {trend}
Volume Spike Multiplier: {volume_spike}x
Beta (Volatility): {beta}
52-Week High: ${fifty_two_high}

--- FUNDAMENTAL METRICS ---
P/E Ratio: {pe_ratio}
Profit Margin: {profit_margin}%
Dividend Yield: {dividend_yield}%
Market Capitalization: ${stock_record.get('market_cap_million', 'N/A')}M

--- RECENT NEWS HEADLINES ---
{news_summary}

--- INSTRUCTIONS ---
Formulate a professional, objective stock analysis report.
You MUST respond with a JSON object containing the following keys (do not include markdown formatting or backticks around the JSON):
{{
  "company_situation": "A 2-3 sentence overview of the company's current situation based on news and fundamentals.",
  "bull_case": ["Detailed bullet point 1...", "Detailed bullet point 2...", "Detailed bullet point 3..."],
  "bear_case": ["Detailed bullet point 1...", "Detailed bullet point 2...", "Detailed bullet point 3..."],
  "verdict": "BULLISH" or "BEARISH" or "HOLD",
  "confidence": 75  // integer between 0 and 100 representing your confidence level
}}
"""

    report = call_gemini_with_failover(prompt)
    # Attach context so downstream consumers (e.g. background alerts) can render emails
    report["_ticker"] = ticker
    report["_company_name"] = company_name
    report["_price"] = price
    report["_sector"] = sector
    return report


class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        # Redirect root path / directly to /dashboard/ for seamless UX
        if self.path == "/" or self.path == "":
            self.send_response(301)
            self.send_header("Location", "/dashboard/")
            self.end_headers()
            return
            
        if self.path.startswith("/api/analyze"):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            ticker = params.get("ticker", [None])[0]
            
            if not ticker:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "Missing 'ticker' parameter"}).encode('utf-8'))
                return
                
            try:
                report = run_ai_analysis(ticker.upper())
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "report": report}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
            return
            
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/settings":
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                new_settings = json.loads(post_data.decode('utf-8'))
                config_path = ROOT / "config.json"
                with open(config_path, "r", encoding="utf-8") as f:
                    current_cfg = json.load(f)
                
                # Update user settings dynamically
                current_cfg["filters"]["min_beta"] = float(new_settings["min_beta"])
                current_cfg["filters"]["min_volume_spike"] = float(new_settings["min_volume_spike"])
                current_cfg["filters"]["min_price_change_pct"] = float(new_settings["min_price_change_pct"])
                current_cfg["filters"]["min_market_cap_million"] = float(new_settings["min_market_cap_million"])
                
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(current_cfg, f, indent=2)
                
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": "Settings updated successfully"}).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
                
        elif self.path == "/api/scan":
            # Fire the multi-threaded S&P 500 stock scan in a background thread
            # so the browser request does not timeout (scans take ~33s)
            def bg_scan():
                try:
                    screener.run_screener()
                except Exception as e:
                    print(f"Background scan error: {e}")
            
            scan_thread = threading.Thread(target=bg_scan, daemon=True)
            scan_thread.start()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "scanning", "message": "Screener scan started in background"}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    import socket
    
    # Try setting up dual-stack IPv6/IPv4 server first to support [::1] (IPv6 localhost) and 127.0.0.1 (IPv4)
    try:
        class DualStackThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            address_family = socket.AF_INET6
            
            def server_bind(self):
                # Allow accepting both IPv6 and IPv4 connections on dual-stack socket
                try:
                    self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
                except Exception:
                    pass
                super().server_bind()
                
        socketserver.TCPServer.allow_reuse_address = True
        print(f"Starting Dual-Stack Stock Screener Server on http://localhost:{PORT} (Supports IPv4 and IPv6)")
        with DualStackThreadingServer(("::", PORT), CustomHandler) as httpd:
            print("Server is fully active. Press Ctrl+C to shutdown.")
            httpd.serve_forever()
    except Exception as e:
        print(f"Dual-stack IPv6 startup failed ({e}). Falling back to IPv4 standard server...")
        # Fallback standard IPv4 server
        class IPv4ThreadingServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            address_family = socket.AF_INET
            
        socketserver.TCPServer.allow_reuse_address = True
        print(f"Starting IPv4-only Stock Screener Server on http://127.0.0.1:{PORT}")
        try:
            with IPv4ThreadingServer(("0.0.0.0", PORT), CustomHandler) as httpd:
                print("Server is fully active. Press Ctrl+C to shutdown.")
                httpd.serve_forever()
        except Exception as err:
            print(f"Server error: {err}")

if __name__ == "__main__":
    run_server()

