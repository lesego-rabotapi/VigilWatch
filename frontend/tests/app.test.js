"use strict";

// req: VW-001 VW-014

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const view = require("../view.js");
const initApp = require("../app.js");

const html = fs.readFileSync(path.join(__dirname, "../index.html"), "utf8");
const API = "https://api.test";

const payload = (overrides = {}) => ({
  endpoint_id: "0123456789abcdef",
  url: "https://example.com/",
  status: "UP",
  uptime_30d: 100,
  latest_latency_ms: 80,
  last_check: "2026-10-02T12:00:00Z",
  last_alert_sent: null,
  recent_latencies: [{ ms: 80, status: "UP", checked_at: "2026-10-02T12:00:00Z" }],
  incidents: [],
  ...overrides,
});

const reply = (status, body) => ({
  ok: status >= 200 && status < 300,
  status,
  json: async () => body,
  text: async () => JSON.stringify(body),
});

/** A dashboard page with fakes for the network, timers and console. */
function setup({ config = { apiBase: API }, responses = [] } = {}) {
  const dom = new JSDOM(html, { url: "https://dashboard.test/" });
  const { window } = dom;
  const calls = [];
  const timers = [];
  const cleared = [];
  const errors = [];
  window.VigilView = view;
  if (config) window.VIGILWATCH_CONFIG = config;
  window.fetch = (url, options) => {
    calls.push({ url, options });
    return Promise.resolve(responses.shift());
  };
  window.setInterval = (fn, ms) => timers.push({ fn, ms });
  window.clearInterval = (id) => cleared.push(id);
  const originalError = console.error;
  console.error = (...args) => errors.push(args);

  const $ = (id) => window.document.getElementById(id);
  const submit = async (value) => {
    $("endpoint-url").value = value;
    $("monitor-form").dispatchEvent(new window.Event("submit", { cancelable: true, bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
  };
  return {
    window, $, calls, timers, cleared, errors, submit,
    start: () => initApp(window),
    done: () => { console.error = originalError; },
  };
}

test("without runtime config the form is disabled and explains why", () => {
  const page = setup({ config: null });
  try {
    page.start();
    assert.match(page.$("input-error").textContent, /config\.js/);
    assert.equal(page.$("start-button").disabled, true);
  } finally {
    page.done();
  }
});

test("an invalid URL is rejected locally without calling the API", async () => {
  const page = setup();
  try {
    page.start();
    await page.submit("ftp://example.com");
    assert.equal(page.$("input-error").textContent, "Please enter a valid http/https URL.");
    assert.equal(page.calls.length, 0);
  } finally {
    page.done();
  }
});

test("a valid URL is registered, rendered, and polling starts on the canonical URL", async () => {
  const page = setup({ responses: [reply(201, payload())] });
  try {
    page.start();
    const pending = page.submit("  https://example.com  ");
    assert.equal(page.$("start-button").textContent, "Starting...");
    assert.equal(page.$("start-button").disabled, true);
    await pending;

    assert.equal(page.calls.length, 1);
    assert.equal(page.calls[0].url, `${API}/register`);
    assert.equal(page.calls[0].options.method, "POST");
    assert.deepEqual(JSON.parse(page.calls[0].options.body), { url: "https://example.com" });
    assert.equal(page.$("status-pill").textContent, "Up");
    assert.equal(page.$("start-button").textContent, "Monitor another URL");
    assert.equal(page.$("start-button").disabled, false);
    assert.equal(page.$("endpoint-url").disabled, false);
    assert.equal(page.timers.length, 1);
    assert.equal(page.timers[0].ms, 15000);
  } finally {
    page.done();
  }
});

test("each poll asks for the canonical URL and refreshes the view", async () => {
  const page = setup({
    responses: [reply(201, payload()), reply(200, payload({ status: "DOWN", uptime_30d: 50 }))],
  });
  try {
    page.start();
    await page.submit("https://example.com");
    page.timers[0].fn();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(page.calls[1].url, `${API}/checks?url=https%3A%2F%2Fexample.com%2F`);
    assert.equal(page.$("status-pill").textContent, "Down");
    assert.equal(page.$("metric-uptime").textContent, "50.00%");
  } finally {
    page.done();
  }
});

test("a failed poll is logged and leaves the last good view in place", async () => {
  const page = setup({ responses: [reply(201, payload()), reply(500, { message: "boom" })] });
  try {
    page.start();
    await page.submit("https://example.com");
    page.timers[0].fn();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(page.$("status-pill").textContent, "Up");
    assert.ok(page.errors.some((args) => String(args[0]).includes("Poll error")));
  } finally {
    page.done();
  }
});

test("a rejected registration shows the server's message and re-enables the form", async () => {
  const page = setup({
    responses: [reply(400, { message: "url resolves to a private or reserved address", code: "unsafe_url" })],
  });
  try {
    page.start();
    await page.submit("http://169.254.169.254/");
    assert.equal(
      page.$("input-error").textContent,
      "Could not start monitoring: url resolves to a private or reserved address",
    );
    assert.equal(page.$("start-button").textContent, "Start Monitoring");
    assert.equal(page.$("start-button").disabled, false);
    assert.equal(page.timers.length, 0, "no polling after a failed registration");
  } finally {
    page.done();
  }
});

test("monitoring another URL stops the previous poller first", async () => {
  const page = setup({ responses: [reply(201, payload()), reply(201, payload({ url: "https://other.com/" }))] });
  try {
    page.start();
    await page.submit("https://example.com");
    await page.submit("https://other.com");
    assert.equal(page.cleared.length, 1, "the first interval must be cleared");
    assert.equal(page.timers.length, 2);
  } finally {
    page.done();
  }
});

test("loaded as a plain browser script it starts itself without a module system", async () => {
  const dom = new JSDOM(html, { url: "https://dashboard.test/", runScripts: "outside-only" });
  const { window } = dom;
  const calls = [];
  window.fetch = (url) => {
    calls.push(url);
    return Promise.resolve(reply(201, payload()));
  };
  window.VIGILWATCH_CONFIG = { apiBase: API };
  window.eval(fs.readFileSync(path.join(__dirname, "../view.js"), "utf8"));
  window.eval(fs.readFileSync(path.join(__dirname, "../app.js"), "utf8"));

  window.document.getElementById("endpoint-url").value = "https://example.com";
  window.document
    .getElementById("monitor-form")
    .dispatchEvent(new window.Event("submit", { cancelable: true, bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.deepEqual(calls, [`${API}/register`]);
});
