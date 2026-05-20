# Stock Screener

Automated S&P 500 stock screener that fetches market data via Yahoo Finance, applies volatility + momentum filters, sends Gmail email alerts, and serves a self-contained web dashboard.

> Research/screening tool only. **Not financial advice.**

---

## 1. Install

```bash
pip install -r requirements.txt
```

Python 3.10+ recommended.

---

## 2. Gmail App Password setup

Gmail will **not** accept your normal account password from scripts. You need an **App Password**:

1. Enable **2-Step Verification** on your Google account: <https://myaccount.google.com/security>
2. Visit <https://myaccount.google.com/apppasswords>
3. Generate a new App Password (e.g. "Stock Screener").
4. Copy the 16-character password.
5. Paste it into `config.json` → `email.password`.

Set `email.sender` and `email.recipient` to your Gmail address.

---

## 3. Configure

Edit `config.json`:

```json
{
  "email": {
    "sender": "your@gmail.com",
    "password": "abcd efgh ijkl mnop",
    "recipient": "your@gmail.com"
  },
  "filters": {
    "min_beta": 1.5,
    "min_volume_spike": 2.0,
    "min_price_change_pct": 3.0,
    "min_market_cap_million": 500
  },
  "sectors": ["Technology", "Healthcare"],
  "alerts": {
    "new_match": true,
    "volume_spike": true,
    "price_breakout": false,
    "daily_digest": true
  }
}
```

Test email sending:

```bash
python alerts.py
```

---

## 4. Run

One-shot scan (writes `results.json`):

```bash
python screener.py
```

Continuous mode (scans every 30 min during US market hours, sends alerts):

```bash
python scheduler.py
```

---

## 5. Dashboard

Open `dashboard/index.html` in your browser. It auto-refreshes every 60 seconds from `results.json`.

> If your browser blocks `fetch()` on local files, serve the folder with `python -m http.server 8000` from the project root and open <http://localhost:8000/dashboard/>.

---

## 6. Run on a schedule automatically

### Windows (Task Scheduler)

Create a task that runs at logon:

```powershell
schtasks /Create /SC ONLOGON /TN "StockScreener" `
  /TR "python C:\path\to\stock-screener\scheduler.py" /RL HIGHEST
```

### macOS / Linux (cron)

```cron
@reboot /usr/bin/python3 /path/to/stock-screener/scheduler.py >> /path/to/stock-screener/cron.log 2>&1
```

---

## Files

| File | Purpose |
|------|---------|
| `screener.py` | Fetch + filter logic, writes `results.json` |
| `alerts.py` | Gmail SMTP email sender |
| `scheduler.py` | Runs screener on a schedule, triggers alerts |
| `dashboard/` | Self-contained HTML/CSS/JS dashboard |
| `config.json` | User settings |
| `results.json` | Latest scan results (generated) |
| `last_results.json` | Previous scan (for new-match detection) |
| `screener.log` | Log file |

---

## Disclaimer

This software is for research and educational purposes only. It does not provide financial advice, and no output should be construed as a buy/sell recommendation. Use at your own risk.
