"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const view = require("../view.js");

const schema = JSON.parse(
  fs.readFileSync(path.join(__dirname, "../../tests/contract/checks_response.schema.json"), "utf8"),
);
const html = fs.readFileSync(path.join(__dirname, "../index.html"), "utf8");

function dom() {
  const { window } = new JSDOM(html);
  return window.document;
}

const payload = {
  endpoint_id: "0123456789abcdef",
  url: "https://example.com/",
  status: "UP",
  uptime_30d: 99.5,
  latest_latency_ms: 120,
  last_check: "2026-10-02T12:00:00Z",
  last_alert_sent: null,
  recent_latencies: [
    { ms: 100, status: "UP", checked_at: "2026-10-02T11:50:00Z" },
    { ms: null, status: "DOWN", checked_at: "2026-10-02T11:55:00Z" },
    { ms: 1500, status: "DEGRADED", checked_at: "2026-10-02T12:00:00Z" },
  ],
  incidents: [
    {
      start_time: "2026-10-02T10:00:00Z",
      end_time: "2026-10-02T10:05:00Z",
      duration: "5m 0s",
      duration_s: 300,
      resolved: true,
    },
  ],
};

test("fixture payload satisfies every required field of the API contract", () => {
  for (const key of schema.required) assert.ok(key in payload, `missing ${key}`);
  assert.deepEqual(Object.keys(payload).sort(), Object.keys(schema.properties).sort());
});

test("updateView renders a healthy endpoint", () => {
  const doc = dom();
  view.updateView(doc, payload);
  assert.equal(doc.getElementById("status-pill").textContent, "Up");
  assert.ok(doc.getElementById("status-pill").classList.contains("pill-up"));
  assert.equal(doc.getElementById("metric-uptime").textContent, "99.50%");
  assert.equal(doc.getElementById("metric-latency").textContent, "120 ms");
  assert.ok(!doc.getElementById("status-grid").classList.contains("hidden"));
  const bars = doc.querySelectorAll("#latency-bars .bar");
  assert.equal(bars.length, 3);
  assert.deepEqual(
    [...bars].map((b) => [...b.classList].filter((c) => c !== "bar")[0]),
    ["ok", "err", "warn"],
  );
  assert.equal(doc.querySelectorAll("#incidents-body tr").length, 1);
  assert.equal(doc.getElementById("alert-last").textContent, "No alerts sent yet");
});

test("updateView tolerates a brand-new endpoint with no data", () => {
  const doc = dom();
  view.updateView(doc, {
    ...payload,
    status: "UNKNOWN",
    uptime_30d: null,
    latest_latency_ms: null,
    last_check: null,
    recent_latencies: [],
    incidents: [],
  });
  assert.equal(doc.getElementById("status-pill").textContent, "Unknown");
  assert.equal(doc.getElementById("metric-uptime").textContent, "–");
  assert.equal(doc.getElementById("metric-latency").textContent, "–");
  assert.equal(doc.getElementById("metric-last-check").textContent, "–");
  assert.equal(doc.getElementById("latency-range").textContent, "No latency data");
  assert.ok(doc.getElementById("incidents-panel").classList.contains("hidden"));
  assert.ok(!doc.getElementById("incidents-empty").classList.contains("hidden"));
});

test("incident rows are rendered as text, never as HTML (XSS)", () => {
  const doc = dom();
  const evil = '<img src=x onerror="window.pwned=1">';
  view.renderIncidents(doc.getElementById("incidents-body"), [
    { start_time: null, end_time: null, duration: evil, duration_s: null, resolved: false },
  ]);
  const body = doc.getElementById("incidents-body");
  assert.equal(body.querySelector("img"), null);
  assert.ok(body.textContent.includes(evil));
  assert.ok(body.textContent.includes("Open"));
});

test("endpoint label is set as text", () => {
  const doc = dom();
  view.updateView(doc, { ...payload, url: "https://example.com/<b>x</b>" });
  assert.equal(doc.querySelector("#endpoint-label b"), null);
  assert.equal(doc.getElementById("endpoint-label").textContent, "https://example.com/<b>x</b>");
});

test("apiBase comes from runtime config and drops trailing slashes", () => {
  assert.equal(view.apiBase({ apiBase: "https://abc.execute-api.af-south-1.amazonaws.com/" }),
    "https://abc.execute-api.af-south-1.amazonaws.com");
  assert.throws(() => view.apiBase(undefined), /config\.js/);
  assert.throws(() => view.apiBase({ apiBase: "" }), /config\.js/);
});

test("isValidHttpUrl accepts only http(s)", () => {
  assert.equal(view.isValidHttpUrl("https://example.com"), true);
  assert.equal(view.isValidHttpUrl("http://example.com/x"), true);
  assert.equal(view.isValidHttpUrl("javascript:alert(1)"), false);
  assert.equal(view.isValidHttpUrl("ftp://example.com"), false);
  assert.equal(view.isValidHttpUrl("not a url"), false);
});

test("restarting polling clears the previous interval", () => {
  const cleared = [];
  let next = 1;
  const timers = {
    setInterval: () => next++,
    clearInterval: (id) => cleared.push(id),
  };
  const poller = view.createPoller(timers, 15000);
  poller.start(() => {});
  poller.start(() => {});
  assert.deepEqual(cleared, [1]);
  poller.stop();
  assert.deepEqual(cleared, [1, 2]);
});

test("API error messages are surfaced from the JSON body", async () => {
  const res = {
    ok: false,
    status: 400,
    text: async () => JSON.stringify({ message: "only http and https URLs can be monitored" }),
  };
  await assert.rejects(view.readJson(res), /only http and https URLs can be monitored/);
  const ok = { ok: true, status: 200, json: async () => ({ a: 1 }) };
  assert.deepEqual(await view.readJson(ok), { a: 1 });
});

test("index.html loads config before the app and has no inline script", () => {
  const doc = dom();
  const srcs = [...doc.querySelectorAll("script")].map((s) => s.getAttribute("src"));
  assert.deepEqual(srcs, ["config.js", "view.js", "app.js"]);
});
