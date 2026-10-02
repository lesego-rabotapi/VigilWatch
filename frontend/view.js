/* VigilWatch dashboard rendering. Pure DOM helpers, loaded in the browser as
 * window.VigilView and in Node tests via require(). All server data is written
 * with textContent, never innerHTML. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.VigilView = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const DASH = "–";
  const PILLS = {
    UP: ["pill-up", "Up"],
    DEGRADED: ["pill-degraded", "Degraded"],
    DOWN: ["pill-down", "Down"],
  };
  const BAR_CLASS = { UP: "ok", DEGRADED: "warn" };

  function apiBase(config) {
    const base = config && typeof config.apiBase === "string" ? config.apiBase.trim() : "";
    if (!base) {
      throw new Error("API URL missing: config.js was not loaded (see frontend/config.example.js)");
    }
    return base.replace(/\/+$/, "");
  }

  function isValidHttpUrl(value) {
    try {
      const u = new URL(value);
      return u.protocol === "http:" || u.protocol === "https:";
    } catch {
      return false;
    }
  }

  function fmtTime(iso) {
    return iso ? new Date(iso).toLocaleString() : DASH;
  }

  function setStatusPill(el, status) {
    const [cls, label] = PILLS[status] || ["pill-unknown", "Unknown"];
    el.className = "pill " + cls;
    el.textContent = label;
  }

  function renderLatency(barsEl, rangeEl, points) {
    barsEl.replaceChildren();
    if (!points || points.length === 0) {
      rangeEl.textContent = "No latency data";
      return;
    }
    const maxMs = Math.max(...points.map((p) => p.ms || 0));
    const top = Math.max(100, Math.ceil(maxMs / 50) * 50);
    rangeEl.textContent = `0–${top} ms (last ${points.length} checks)`;

    const doc = barsEl.ownerDocument;
    for (const p of points) {
      const bar = doc.createElement("div");
      bar.classList.add("bar", BAR_CLASS[p.status] || "err");
      bar.style.height = Math.max(10, ((p.ms || 0) / top) * 100) + "%";
      bar.title = `${p.ms == null ? "no response" : p.ms + " ms"} · ${p.status}`;
      barsEl.appendChild(bar);
    }
  }

  function renderIncidents(tbody, list) {
    const doc = tbody.ownerDocument;
    tbody.replaceChildren();
    for (const inc of list) {
      const tr = doc.createElement("tr");
      const cells = [
        fmtTime(inc.start_time),
        fmtTime(inc.end_time),
        inc.duration || DASH,
        inc.resolved ? "Resolved" : "Open",
      ];
      for (const text of cells) {
        const td = doc.createElement("td");
        td.textContent = text;
        tr.appendChild(td);
      }
      tbody.appendChild(tr);
    }
  }

  function updateView(doc, data) {
    const $ = (id) => doc.getElementById(id);

    $("endpoint-label").textContent = data.url || "No endpoint selected";
    $("status-empty").classList.add("hidden");
    $("latency-empty").classList.add("hidden");
    $("status-grid").classList.remove("hidden");
    setStatusPill($("status-pill"), data.status);

    $("metric-uptime").textContent =
      typeof data.uptime_30d === "number" ? data.uptime_30d.toFixed(2) + "%" : DASH;
    $("metric-latency").textContent =
      typeof data.latest_latency_ms === "number"
        ? Math.round(data.latest_latency_ms) + " ms"
        : DASH;
    $("metric-last-check").textContent = fmtTime(data.last_check);

    $("latency-panel").classList.remove("hidden");
    renderLatency($("latency-bars"), $("latency-range"), data.recent_latencies || []);

    const incidents = data.incidents || [];
    $("incidents-panel").classList.toggle("hidden", incidents.length === 0);
    $("incidents-empty").classList.toggle("hidden", incidents.length !== 0);
    renderIncidents($("incidents-body"), incidents);

    $("alert-last").textContent = data.last_alert_sent
      ? fmtTime(data.last_alert_sent)
      : "No alerts sent yet";
  }

  function createPoller(timers, intervalMs) {
    let id = null;
    return {
      start(fn) {
        if (id !== null) timers.clearInterval(id);
        id = timers.setInterval(fn, intervalMs);
      },
      stop() {
        if (id !== null) timers.clearInterval(id);
        id = null;
      },
    };
  }

  async function readJson(res) {
    if (res.ok) return res.json();
    const text = await res.text();
    let message = text;
    try {
      message = JSON.parse(text).message || text;
    } catch {
      /* not JSON: use the raw text */
    }
    throw new Error(message || `HTTP ${res.status}`);
  }

  return {
    apiBase,
    isValidHttpUrl,
    setStatusPill,
    renderLatency,
    renderIncidents,
    updateView,
    createPoller,
    readJson,
  };
});
