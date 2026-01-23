const form = document.getElementById("monitor-form");
const urlInput = document.getElementById("endpoint-url");
const startButton = document.getElementById("start-button");
const inputError = document.getElementById("input-error");

const statusEmpty = document.getElementById("status-empty");
const statusGrid = document.getElementById("status-grid");
const statusPill = document.getElementById("status-pill");
const metricUptime = document.getElementById("metric-uptime");
const metricLatency = document.getElementById("metric-latency");
const metricLastCheck = document.getElementById("metric-last-check");

const endpointLabel = document.getElementById("endpoint-label");
const latencyEmpty = document.getElementById("latency-empty");
const latencyPanel = document.getElementById("latency-panel");
const latencyBars = document.getElementById("latency-bars");
const latencyRange = document.getElementById("latency-range");

const incidentsEmpty = document.getElementById("incidents-empty");
const incidentsPanel = document.getElementById("incidents-panel");
const incidentsBody = document.getElementById("incidents-body");

const alertLast = document.getElementById("alert-last");

const API_BASE = "https://xihi7lu6jh.execute-api.af-south-1.amazonaws.com/prod";

let currentUrl = null;
let pollId = null;

form.addEventListener("submit", (e) => {
  e.preventDefault();
  inputError.textContent = "";

  const value = urlInput.value.trim();
  if (!isValidHttpUrl(value)) {
    inputError.textContent = "Please enter a valid http/https URL.";
    return;
  }

  startMonitoring(value);
});

function isValidHttpUrl(value) {
  try {
    const u = new URL(value);
    return u.protocol === "http:" || u.protocol === "https:";
  } catch {
    return false;
  }
}

function startMonitoring(url) {
  currentUrl = url;
  endpointLabel.textContent = url;

  urlInput.disabled = true;
  startButton.disabled = true;
  startButton.textContent = "Starting...";

  statusEmpty.classList.add("hidden");
  latencyEmpty.classList.add("hidden");

  //load backend
  fetchInitial(url)
    .then((data) => {
      updateView(data);
      startButton.textContent = "Monitoring...";
    })
    .catch((err) => {
      console.error(err);
      inputError.textContent =
        "Could not start monitoring. Please try again or check the API.";
      urlInput.disabled = false;
      startButton.disabled = false;
      startButton.textContent = "Start Monitoring";
    });

  //clear previous intervals
  if (pollId) clearInterval(pollId);

  //poll every 15s
  pollId = setInterval(() => {
    if (!currentUrl) return;
    fetchPoll(currentUrl)
      .then(updateView)
      .catch((err) => {
        console.error("Poll error:", err);
      });
  }, 15000);
}

function updateView(data) {
  statusGrid.classList.remove("hidden");
  setStatusPill(data.status || "UNKNOWN");

  if (typeof data.uptime_30d === "number") {
    metricUptime.textContent = data.uptime_30d.toFixed(2) + "%";
  } else {
    metricUptime.textContent = "–";
  }

  if (typeof data.latest_latency_ms === "number") {
    metricLatency.textContent = Math.round(data.latest_latency_ms) + " ms";
  } else {
    metricLatency.textContent = "–";
  }

  if (data.last_check) {
    metricLastCheck.textContent = new Date(data.last_check).toLocaleString();
  } else {
    metricLastCheck.textContent = "–";
  }

  //latency chart
  latencyPanel.classList.remove("hidden");
  renderLatency(data.recent_latencies || []);

  //incidents
  const incidents = data.incidents || [];
  if (incidents.length === 0) {
    incidentsPanel.classList.add("hidden");
    incidentsEmpty.classList.remove("hidden");
  } else {
    incidentsEmpty.classList.add("hidden");
    incidentsPanel.classList.remove("hidden");
    renderIncidents(incidents);
  }

  //alerts
  if (data.last_alert_sent) {
    alertLast.textContent = new Date(data.last_alert_sent).toLocaleString();
  } else {
    alertLast.textContent = "No alerts sent yet";
  }
}

function setStatusPill(status) {
  statusPill.className = "pill pill-unknown";

  if (status === "UP") {
    statusPill.className = "pill pill-up";
    statusPill.textContent = "Up";
  } else if (status === "DEGRADED") {
    statusPill.className = "pill pill-degraded";
    statusPill.textContent = "Degraded";
  } else if (status === "DOWN") {
    statusPill.className = "pill pill-down";
    statusPill.textContent = "Down";
  } else {
    statusPill.textContent = "Unknown";
  }
}

function renderLatency(points) {
  if (!points || points.length === 0) {
    latencyBars.innerHTML = "";
    latencyRange.textContent = "No latency data";
    return;
  }

  const maxMs = Math.max(...points.map((p) => p.ms || 0));
  const top = Math.max(100, Math.ceil(maxMs / 50) * 50);
  latencyRange.textContent = `0–${top} ms (last ${points.length} checks)`;

  latencyBars.innerHTML = "";
  points.forEach((p) => {
    const ms = p.ms || 0;
    const h = Math.max(10, (ms / top) * 100);

    const bar = document.createElement("div");
    bar.classList.add("bar");

    if (p.status === "UP") bar.classList.add("ok");
    else if (p.status === "DEGRADED") bar.classList.add("warn");
    else bar.classList.add("err");

    bar.style.height = h + "%";
    latencyBars.appendChild(bar);
  });
}

function renderIncidents(list) {
  incidentsBody.innerHTML = "";
  list.forEach((inc) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${inc.start_time ? fmt(inc.start_time) : "—"}</td>
      <td>${inc.end_time ? fmt(inc.end_time) : "—"}</td>
      <td>${inc.duration || "—"}</td>
      <td>${inc.resolved ? "Resolved" : "Open"}</td>
    `;
    incidentsBody.appendChild(tr);
  });
}

function fmt(iso) {
  return new Date(iso).toLocaleString();
}

//backend calls

function fetchInitial(url) {

  return fetch(`${API_BASE}/monitor`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url }),
  }).then(checkResponseJson);
}

function fetchPoll(url) {
  const encoded = encodeURIComponent(url);
  return fetch(`${API_BASE}/checks?url=${encoded}`).then(checkResponseJson);
}


function checkResponseJson(res) {
  if (!res.ok) {
    return res.text().then((t) => {
      throw new Error(`HTTP ${res.status}: ${t}`);
    });
  }
  return res.json();
}