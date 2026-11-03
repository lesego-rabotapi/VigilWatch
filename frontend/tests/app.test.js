"use strict";

// req: VW-001 VW-014 VW-026

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");

const view = require("../view.js");
const VigilAuth = require("../auth.js");
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
function setup({ config = { apiBase: API }, responses = [], auth = VigilAuth } = {}) {
  const dom = new JSDOM(html, { url: "https://dashboard.test/" });
  const { window } = dom;
  const calls = [];
  const timers = [];
  const cleared = [];
  const errors = [];
  window.VigilView = view;
  window.VigilAuth = auth;
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
    done: () => {
      console.error = originalError;
      window.close(); // clears any timers so the test process can exit
    },
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
  window.eval(fs.readFileSync(path.join(__dirname, "../auth.js"), "utf8"));
  window.eval(fs.readFileSync(path.join(__dirname, "../app.js"), "utf8"));

  try {
    window.document.getElementById("endpoint-url").value = "https://example.com";
    window.document
      .getElementById("monitor-form")
      .dispatchEvent(new window.Event("submit", { cancelable: true, bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.deepEqual(calls, [`${API}/register`]);
  } finally {
    window.close(); // the poller started a real 15 s interval; closing clears it
  }
});

// ---- Sign-in (ADR 0007) -----------------------------------------------------------------------

const SIGNED = { apiBase: API, auth: { hostedUiUrl: "https://x.auth.af-south-1.amazoncognito.com", clientId: "c" } };

/** A stand-in for auth.js: signed in with `token`, or signed out when it is null. */
function fakeAuth({ token = null, redirectError = null } = {}) {
  const log = [];
  let current = token;
  return {
    log,
    createAuth: () => ({
      enabled: true,
      token: () => current,
      handleRedirect: () => (redirectError ? Promise.reject(new Error(redirectError)) : Promise.resolve(Boolean(current))),
      signIn: () => { log.push("signIn"); return Promise.resolve(); },
      signOut: () => { log.push("signOut"); current = null; },
      forget: () => { log.push("forget"); current = null; },
    }),
  };
}

test("signed out, the form is closed and the only way on is to sign in", async () => {
  const auth = fakeAuth();
  const page = setup({ config: SIGNED, auth });
  try {
    await page.start();
    assert.equal(page.$("start-button").disabled, true);
    assert.equal(page.$("endpoint-url").disabled, true);
    assert.equal(page.$("sign-in").classList.contains("hidden"), false);
    assert.equal(page.$("sign-out").classList.contains("hidden"), true);
    page.$("sign-in").click();
    assert.deepEqual(auth.log, ["signIn"]);
  } finally {
    page.done();
  }
});

test("signed in, every request carries the token and the form is open", async () => {
  const auth = fakeAuth({ token: "tok" });
  const page = setup({ config: SIGNED, auth, responses: [reply(201, payload()), reply(200, payload())] });
  try {
    await page.start();
    assert.equal(page.$("start-button").disabled, false);
    assert.equal(page.$("sign-out").classList.contains("hidden"), false);
    await page.submit("https://example.com");
    page.timers[0].fn();
    await new Promise((resolve) => setTimeout(resolve, 0));
    for (const call of page.calls) {
      assert.equal(call.options.headers.Authorization, "Bearer tok", call.url);
    }
    page.$("sign-out").click();
    assert.ok(auth.log.includes("signOut"));
  } finally {
    page.done();
  }
});

test("a session the API no longer accepts returns the page to signed out", async () => {
  const auth = fakeAuth({ token: "expired" });
  const page = setup({ config: SIGNED, auth, responses: [reply(401, { message: "Unauthorized", code: "unauthorized" })] });
  try {
    await page.start();
    await page.submit("https://example.com");
    assert.ok(auth.log.includes("forget"));
    assert.match(page.$("input-error").textContent, /sign in again/i);
    assert.equal(page.$("sign-in").classList.contains("hidden"), false);
    assert.equal(page.$("start-button").disabled, true);
  } finally {
    page.done();
  }
});

test("a failed sign-in is explained and leaves the page signed out", async () => {
  const auth = fakeAuth({ redirectError: "Denied by the user" });
  const page = setup({ config: SIGNED, auth });
  try {
    await page.start();
    assert.match(page.$("input-error").textContent, /Denied by the user/);
    assert.equal(page.$("sign-in").classList.contains("hidden"), false);
  } finally {
    page.done();
  }
});

test("on the local stack (no sign-in settings) requests go without a token and no session buttons show", async () => {
  const page = setup({ responses: [reply(201, payload())] });
  try {
    await page.start();
    await page.submit("https://example.com");
    assert.equal(page.calls[0].options.headers.Authorization, undefined);
    assert.equal(page.$("sign-in").classList.contains("hidden"), true);
    assert.equal(page.$("sign-out").classList.contains("hidden"), true);
  } finally {
    page.done();
  }
});

test("a sign-in that cannot start says so", async () => {
  const auth = fakeAuth();
  const broken = { createAuth: (...args) => ({ ...auth.createAuth(...args), signIn: () => Promise.reject(new Error("no crypto")) }) };
  const page = setup({ config: SIGNED, auth: broken });
  try {
    await page.start();
    page.$("sign-in").click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.match(page.$("input-error").textContent, /Could not start the sign-in: no crypto/);
  } finally {
    page.done();
  }
});

test("a poll the API refuses signs the page out quietly", async () => {
  const auth = fakeAuth({ token: "tok" });
  const page = setup({
    config: SIGNED,
    auth,
    responses: [reply(201, payload()), reply(401, { message: "Unauthorized", code: "unauthorized" })],
  });
  try {
    await page.start();
    await page.submit("https://example.com");
    page.timers[0].fn();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.deepEqual(page.errors, [], "a signed-out poll is not an error to log");
    assert.match(page.$("input-error").textContent, /sign in again/i);
  } finally {
    page.done();
  }
});

test("signing out clears the previous user's data from the page", async () => {
  const auth = fakeAuth({ token: "tok" });
  const page = setup({ config: SIGNED, auth, responses: [reply(201, payload())] });
  try {
    await page.start();
    await page.submit("https://example.com");
    assert.equal(page.$("status-grid").classList.contains("hidden"), false);
    page.$("sign-out").click();
    assert.equal(page.$("status-grid").classList.contains("hidden"), true);
    assert.equal(page.$("status-empty").classList.contains("hidden"), false);
    assert.equal(page.$("endpoint-label").textContent, "No endpoint selected");
    assert.equal(page.$("endpoint-url").value, "");
    assert.equal(page.$("latency-bars").children.length, 0);
    assert.equal(page.$("incidents-body").children.length, 0);
  } finally {
    page.done();
  }
});

test("a session the API ends also clears the data", async () => {
  const auth = fakeAuth({ token: "tok" });
  const page = setup({
    config: SIGNED,
    auth,
    responses: [reply(201, payload()), reply(401, { message: "Unauthorized", code: "unauthorized" })],
  });
  try {
    await page.start();
    await page.submit("https://example.com");
    page.timers[0].fn();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(page.$("status-grid").classList.contains("hidden"), true);
  } finally {
    page.done();
  }
});

test("a registration that finishes after sign-out changes nothing", async () => {
  const auth = fakeAuth({ token: "tok" });
  let finish;
  const late = new Promise((resolve) => (finish = resolve));
  const page = setup({ config: SIGNED, auth, responses: [late] });
  try {
    await page.start();
    const submitted = page.submit("https://example.com");
    page.$("sign-out").click();
    finish(reply(201, payload()));
    await submitted;
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(page.$("start-button").disabled, true, "the form stays closed");
    assert.equal(page.$("endpoint-url").disabled, true);
    assert.equal(page.$("status-grid").classList.contains("hidden"), true, "no data for nobody");
    assert.deepEqual(page.timers, [], "no poller on a signed-out page");
  } finally {
    page.done();
  }
});

test("a poll that finishes after sign-out changes nothing", async () => {
  const auth = fakeAuth({ token: "tok" });
  let finish;
  const late = new Promise((resolve) => (finish = resolve));
  const page = setup({ config: SIGNED, auth, responses: [reply(201, payload()), late] });
  try {
    await page.start();
    await page.submit("https://example.com");
    page.timers[0].fn();
    page.$("sign-out").click();
    finish(reply(200, payload({ status: "DOWN" })));
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(page.$("status-grid").classList.contains("hidden"), true);
  } finally {
    page.done();
  }
});

test("signing out leaves no error text or half-finished label behind", async () => {
  const auth = fakeAuth({ token: "tok" });
  let finish;
  const late = new Promise((resolve) => (finish = resolve));
  const page = setup({ config: SIGNED, auth, responses: [late] });
  try {
    await page.start();
    page.$("input-error").textContent = "Could not start monitoring: https://private.example refused";
    const submitted = page.submit("https://example.com");
    assert.equal(page.$("start-button").textContent, "Starting...");
    page.$("sign-out").click();
    assert.equal(page.$("input-error").textContent, "");
    assert.equal(page.$("start-button").textContent, "Start Monitoring");
    finish(reply(201, payload()));
    await submitted;
  } finally {
    page.done();
  }
});
