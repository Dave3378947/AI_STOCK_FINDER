const REFRESH_MS = 60_000;
let alertsCount = 0;
let lastTickers = new Set();
let currentMatches = [];
let chartInstance = null;

const $ = (id) => document.getElementById(id);

function signalPill(signal) {
  const cls = signal === "Strong buy" ? "strong" : signal === "Breakout" ? "breakout" : "momentum";
  return `<span class="pill ${cls}">${signal}</span>`;
}

function trendBadge(trend) {
  const cls = trend === "Bullish" ? "pos" : trend === "Bearish" ? "neg" : "neutral";
  const icon = trend === "Bullish" ? "▲" : trend === "Bearish" ? "▼" : "■";
  return `<span class="${cls}" style="font-weight:700;">${icon} ${trend}</span>`;
}

function renderRows(matches) {
  const body = $("results-body");
  const query = ($("search").value || "").toLowerCase();
  const sigFilter = $("signal-filter").value;

  const filtered = matches.filter((s) => {
    const hay = `${s.ticker} ${s.company_name} ${s.sector} ${s.trend}`.toLowerCase();
    if (query && !hay.includes(query)) return false;
    if (sigFilter && s.signal !== sigFilter) return false;
    return true;
  });

  if (!filtered.length) {
    body.innerHTML = `<tr><td colspan="11" class="empty">No matches found. Adjust filters or run a scan.</td></tr>`;
    return;
  }

  body.innerHTML = filtered.map((s) => {
    const chCls = s.change_pct >= 0 ? "pos" : "neg";
    const sign = s.change_pct >= 0 ? "+" : "";
    
    // Check if indicators exist, default gracefully if not scanned yet
    const rsiVal = s.rsi !== undefined ? s.rsi.toFixed(1) : "—";
    const rsiCls = s.rsi >= 70 ? "neg" : s.rsi <= 30 ? "pos" : "";
    const trendText = s.trend || "Neutral";

    return `<tr>
      <td><b>${s.ticker}</b></td>
      <td>${s.company_name}</td>
      <td>$${s.price.toFixed(2)}</td>
      <td class="${chCls}">${sign}${s.change_pct.toFixed(2)}%</td>
      <td>${s.volume_spike.toFixed(2)}x</td>
      <td>${s.beta.toFixed(2)}</td>
      <td class="${rsiCls}"><b>${rsiVal}</b></td>
      <td>${trendBadge(trendText)}</td>
      <td>${signalPill(s.signal)}</td>
      <td>${s.sector}</td>
      <td>
        <div style="display: flex; gap: 8px;">
          <button onclick="openChart('${s.ticker}')" class="badge open" style="cursor:pointer; font-weight:700; border:none; text-transform:none; margin:0;">
            📈 Chart
          </button>
          <button onclick="openAIAnalysis('${s.ticker}')" class="badge open" style="cursor:pointer; font-weight:700; border:none; text-transform:none; margin:0; background: rgba(99, 102, 241, 0.15); color: #a5b4fc; border-color: rgba(99, 102, 241, 0.3); box-shadow: 0 0 12px rgba(99, 102, 241, 0.15);">
            🤖 AI Agent
          </button>
        </div>
      </td>
    </tr>`;
  }).join("");
}

function openChart(ticker) {
  const stock = currentMatches.find((s) => s.ticker === ticker);
  if (!stock || !stock.recent_closes) {
    alert("Historical price chart data not available for " + ticker);
    return;
  }

  $("chart-title").textContent = `${stock.ticker} — ${stock.company_name}`;
  $("chart-subtitle").textContent = `${stock.sector} | 20-Day Close Price Trend`;

  const options = {
    series: [{
      name: 'Close Price',
      data: stock.recent_closes
    }],
    chart: {
      type: 'area',
      height: 320,
      background: 'transparent',
      foreColor: '#94a3b8',
      toolbar: { show: false },
      zoom: { enabled: false }
    },
    colors: [stock.change_pct >= 0 ? '#34d399' : '#f87171'],
    fill: {
      type: 'gradient',
      gradient: {
        shadeIntensity: 1,
        opacityFrom: 0.45,
        opacityTo: 0.05,
        stops: [0, 100]
      }
    },
    stroke: {
      curve: 'smooth',
      width: 3
    },
    grid: {
      borderColor: 'rgba(255, 255, 255, 0.05)',
      xaxis: { lines: { show: false } },
      yaxis: { lines: { show: true } }
    },
    dataLabels: { enabled: false },
    xaxis: {
      categories: stock.recent_dates ? stock.recent_dates.map(d => d.slice(5)) : Array.from({length: 20}, (_, i) => i + 1),
      axisBorder: { show: false },
      axisTicks: { show: false }
    },
    yaxis: {
      labels: {
        formatter: (val) => `$${val.toFixed(2)}`
      }
    },
    theme: {
      mode: 'dark'
    },
    tooltip: {
      theme: 'dark',
      x: { format: 'dd MMM' }
    }
  };

  const chartArea = $("chart-area");
  chartArea.innerHTML = ""; // Clear old canvas element
  
  if (chartInstance) {
    chartInstance.destroy();
  }
  
  chartInstance = new ApexCharts(chartArea, options);
  chartInstance.render();
  
  $("chart-dialog").showModal();
}

async function openAIAnalysis(ticker) {
  const stock = currentMatches.find((s) => s.ticker === ticker);
  
  $("ai-title").innerHTML = `<span>🤖</span> AI Financial Analyst — ${ticker}`;
  $("ai-subtitle").textContent = `${stock ? stock.sector : ''} | Generative insights & recommendation engine`;
  
  // Toggle loading and content displays
  $("ai-loading").style.display = "flex";
  $("ai-report-body").style.display = "none";
  $("ai-dialog").showModal();
  
  try {
    const res = await fetch(`/api/analyze?ticker=${ticker}`);
    const data = await res.json();
    
    if (data.status === "success" && data.report) {
      const rep = data.report;
      
      // Populate overview
      $("ai-situation").textContent = rep.company_situation;
      
      // Populate verdict & class
      const badge = $("ai-verdict-badge");
      badge.textContent = rep.verdict;
      badge.className = ""; // clear old classes
      if (rep.verdict === "BULLISH") {
        badge.classList.add("verdict-bullish");
      } else if (rep.verdict === "BEARISH") {
        badge.classList.add("verdict-bearish");
      } else {
        badge.classList.add("verdict-hold");
      }
      
      // Populate confidence
      $("ai-confidence-value").textContent = `${rep.confidence}%`;
      
      // Populate lists
      $("ai-bull-list").innerHTML = rep.bull_case.map(pt => `<li>${pt}</li>`).join("");
      $("ai-bear-list").innerHTML = rep.bear_case.map(pt => `<li>${pt}</li>`).join("");
      
      // Switch visibility
      $("ai-loading").style.display = "none";
      $("ai-report-body").style.display = "block";
    } else {
      throw new Error(data.message || "Failed to retrieve analysis.");
    }
  } catch (err) {
    $("ai-loading").style.display = "none";
    $("ai-report-body").style.display = "none";
    
    // Show a user-friendly message instead of raw API errors
    let msg = err.message || "Unknown error";
    if (msg.includes("429") || msg.includes("quota") || msg.includes("exhausted")) {
      msg = "⏳ Gemini free-tier rate limit reached. Please wait 1-2 minutes and try again — quotas reset automatically.";
    } else if (msg.includes("503") || msg.includes("UNAVAILABLE")) {
      msg = "⏳ Gemini servers are temporarily busy. Please try again in a moment.";
    }
    
    $(("ai-situation")).textContent = msg;
    $(("ai-verdict-badge")).textContent = "—";
    $(("ai-verdict-badge")).className = "verdict-hold";
    $(("ai-confidence-value")).textContent = "—";
    $(("ai-bull-list")).innerHTML = "";
    $(("ai-bear-list")).innerHTML = "";
    $(("ai-report-body")).style.display = "block";
  }
}

function updateMarketStatus() {
  const now = new Date();
  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York", weekday: "short", hour: "numeric",
    minute: "numeric", hour12: false,
  }).formatToParts(now);
  const parts = Object.fromEntries(fmt.map((p) => [p.type, p.value]));
  const dow = parts.weekday;
  const hh = parseInt(parts.hour, 10);
  const mm = parseInt(parts.minute, 10);
  const minutes = hh * 60 + mm;
  const weekday = !["Sat", "Sun"].includes(dow);
  const open = weekday && minutes >= 9 * 60 + 30 && minutes <= 16 * 60;
  
  const badge = $("market-status");
  badge.textContent = open ? "Market Open" : "Market Closed";
  badge.className = "badge " + (open ? "open" : "closed");
  $("m-market").textContent = open ? "Open" : "Closed";
}

async function loadResults() {
  try {
    const res = await fetch("../results.json?_=" + Date.now());
    if (!res.ok) throw new Error("no results.json yet");
    const data = await res.json();
    const matches = data.matches || [];
    currentMatches = matches;

    $("m-matched").textContent = matches.length;
    $("m-scanned").textContent = data.scanned ?? "—";
    $("last-scan").textContent = "Last scan: " + new Date(data.generated_at).toLocaleString();

    // Count new tickers as session alerts
    const currentTickers = new Set(matches.map((m) => m.ticker));
    if (lastTickers.size) {
      for (const t of currentTickers) if (!lastTickers.has(t)) alertsCount++;
    }
    lastTickers = currentTickers;
    $("m-alerts").textContent = alertsCount;

    renderRows(matches);
  } catch (e) {
    $("results-body").innerHTML =
      `<tr><td colspan="11" class="empty">No results yet. Click <b>Scan Now</b> to execute S&P 500 scanner.</td></tr>`;
  }
}

async function loadConfigIntoDialog() {
  try {
    const res = await fetch("../config.json?_=" + Date.now());
    const cfg = await res.json();
    $("cfg-beta").value = cfg.filters.min_beta;
    $("cfg-vol").value = cfg.filters.min_volume_spike;
    $("cfg-change").value = cfg.filters.min_price_change_pct;
    $("cfg-mcap").value = cfg.filters.min_market_cap_million;
  } catch (err) {
    console.error("Failed to load settings configuration: ", err);
  }
}

async function triggerScan() {
  const btn = $("refresh-btn");
  const origText = btn.textContent;
  btn.textContent = "Scanning (33s)...";
  btn.disabled = true;
  btn.style.filter = "grayscale(0.6)";

  try {
    const res = await fetch("/api/scan", { method: "POST" });
    if (res.ok) {
      let secondsLeft = 33;
      const interval = setInterval(() => {
        secondsLeft--;
        btn.textContent = `Scanning (${secondsLeft}s)...`;
        if (secondsLeft <= 0) {
          clearInterval(interval);
          btn.textContent = origText;
          btn.disabled = false;
          btn.style.filter = "none";
          loadResults();
        }
      }, 1000);
    } else {
      alert("Failed to start scanner.");
      btn.textContent = origText;
      btn.disabled = false;
      btn.style.filter = "none";
    }
  } catch (err) {
    alert("Connection error: " + err.message);
    btn.textContent = origText;
    btn.disabled = false;
    btn.style.filter = "none";
  }
}

document.addEventListener("DOMContentLoaded", () => {
  updateMarketStatus();
  loadResults();
  
  // Auto refresh data every 60 seconds
  setInterval(() => { updateMarketStatus(); loadResults(); }, REFRESH_MS);

  $("refresh-btn").addEventListener("click", triggerScan);
  $("search").addEventListener("input", () => renderRows(currentMatches));
  $("signal-filter").addEventListener("change", () => renderRows(currentMatches));
  
  $("settings-btn").addEventListener("click", async () => {
    await loadConfigIntoDialog();
    $("settings-dialog").showModal();
  });

  $("cancel-settings").addEventListener("click", () => {
    $("settings-dialog").close();
  });

  $("close-chart-btn").addEventListener("click", () => {
    $("chart-dialog").close();
  });

  $("close-ai-btn").addEventListener("click", () => {
    $("ai-dialog").close();
  });

  // Settings Save API handler
  $("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const payload = {
      min_beta: parseFloat($("cfg-beta").value),
      min_volume_spike: parseFloat($("cfg-vol").value),
      min_price_change_pct: parseFloat($("cfg-change").value),
      min_market_cap_million: parseFloat($("cfg-mcap").value)
    };

    try {
      const res = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        $("settings-dialog").close();
        alert("Settings saved successfully! Launching a fresh scan to update matches.");
        triggerScan();
      } else {
        const errorData = await res.json();
        alert("Failed to save settings: " + (errorData.message || "Unknown error"));
      }
    } catch (err) {
      alert("Error contacting API backend: " + err.message);
    }
  });
});
