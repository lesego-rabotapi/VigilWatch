"use strict";

// req: VW-026
// Sign-in with the authorization code flow and PKCE (ADR 0007). The token lives in memory only.

const test = require("node:test");
const assert = require("node:assert/strict");
const { webcrypto, createHash } = require("node:crypto");
const { JSDOM } = require("jsdom");

const VigilAuth = require("../auth.js");

const HOSTED_UI = "https://vigilwatch-dev-123456789012.auth.af-south-1.amazoncognito.com";
const CONFIG = { hostedUiUrl: HOSTED_UI, clientId: "dashboardclient" };

/** A browser window at `url`, with a fake network and a recorded navigation. */
function browser(url = "https://dashboard.test/", tokenReply = { access_token: "the-token" }) {
  const dom = new JSDOM("<!DOCTYPE html><p></p>", { url });
  const { window } = dom;
  Object.defineProperty(window, "crypto", { value: webcrypto });
  const requests = [];
  const visits = [];
  window.fetch = (target, options) => {
    requests.push({ target, options });
    const ok = !tokenReply.error;
    return Promise.resolve({ ok, status: ok ? 200 : 400, json: async () => tokenReply });
  };
  return { window, requests, visits, navigate: (target) => visits.push(new URL(target)) };
}

const base64url = (buffer) =>
  Buffer.from(buffer).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

test("signing in sends the browser to the hosted UI with a PKCE challenge", async () => {
  const b = browser();
  const auth = VigilAuth.createAuth(b.window, CONFIG, { navigate: b.navigate });
  await auth.signIn();

  const visit = b.visits[0];
  assert.equal(visit.origin + visit.pathname, `${HOSTED_UI}/oauth2/authorize`);
  const params = visit.searchParams;
  assert.equal(params.get("response_type"), "code");
  assert.equal(params.get("client_id"), "dashboardclient");
  assert.equal(params.get("redirect_uri"), "https://dashboard.test");
  assert.equal(params.get("scope"), "openid email");
  assert.equal(params.get("code_challenge_method"), "S256");

  const saved = JSON.parse(b.window.sessionStorage.getItem("vigilwatch.pkce"));
  assert.equal(params.get("state"), saved.state);
  const expected = base64url(createHash("sha256").update(saved.verifier).digest());
  assert.equal(params.get("code_challenge"), expected, "the challenge is the verifier's SHA-256");
  assert.ok(saved.verifier.length >= 43, "a verifier of at least 43 characters (RFC 7636)");
});

test("coming back with a code exchanges it, keeps the token in memory and cleans up", async () => {
  const start = browser();
  const first = VigilAuth.createAuth(start.window, CONFIG, { navigate: start.navigate });
  await first.signIn();
  const saved = start.window.sessionStorage.getItem("vigilwatch.pkce");
  const { state, verifier } = JSON.parse(saved);

  const back = browser(`https://dashboard.test/?code=the-code&state=${state}`);
  back.window.sessionStorage.setItem("vigilwatch.pkce", saved);
  const auth = VigilAuth.createAuth(back.window, CONFIG, { navigate: back.navigate });
  assert.equal(await auth.handleRedirect(), true);

  assert.equal(auth.token(), "the-token");
  const { target, options } = back.requests[0];
  assert.equal(target, `${HOSTED_UI}/oauth2/token`);
  assert.equal(options.method, "POST");
  assert.equal(options.headers["Content-Type"], "application/x-www-form-urlencoded");
  const form = new URLSearchParams(options.body);
  assert.equal(form.get("grant_type"), "authorization_code");
  assert.equal(form.get("code"), "the-code");
  assert.equal(form.get("code_verifier"), verifier);
  assert.equal(form.get("client_id"), "dashboardclient");
  assert.equal(form.get("redirect_uri"), "https://dashboard.test");

  assert.equal(back.window.location.search, "", "the code is removed from the address bar");
  assert.equal(back.window.sessionStorage.getItem("vigilwatch.pkce"), null, "used once");
  const stored = JSON.stringify({ ...back.window.localStorage, ...back.window.sessionStorage });
  assert.ok(!stored.includes("the-token") && !back.window.document.cookie.includes("the-token"),
    "the token is never written to storage or a cookie");
});

test("a page without a code is simply signed out", async () => {
  const b = browser();
  const auth = VigilAuth.createAuth(b.window, CONFIG, { navigate: b.navigate });
  assert.equal(await auth.handleRedirect(), false);
  assert.equal(auth.token(), null);
  assert.equal(b.requests.length, 0);
});

test("a code whose state was not issued here is refused, and nothing is exchanged", async () => {
  const b = browser("https://dashboard.test/?code=stolen&state=forged");
  b.window.sessionStorage.setItem("vigilwatch.pkce", JSON.stringify({ state: "mine", verifier: "v".repeat(43) }));
  const auth = VigilAuth.createAuth(b.window, CONFIG, { navigate: b.navigate });
  await assert.rejects(auth.handleRedirect(), /not started here/);
  assert.equal(b.requests.length, 0, "a forged redirect must not be redeemed");
  assert.equal(auth.token(), null);
});

test("a code with no sign-in started here is refused", async () => {
  const b = browser("https://dashboard.test/?code=x&state=y");
  const auth = VigilAuth.createAuth(b.window, CONFIG, { navigate: b.navigate });
  await assert.rejects(auth.handleRedirect(), /not started here/);
  assert.equal(b.requests.length, 0);
});

test("an error from the hosted UI is reported", async () => {
  const b = browser("https://dashboard.test/?error=access_denied&error_description=Denied");
  const auth = VigilAuth.createAuth(b.window, CONFIG, { navigate: b.navigate });
  await assert.rejects(auth.handleRedirect(), /Denied/);
  assert.equal(b.window.location.search, "", "the error is removed from the address bar too");
});

test("a refused code exchange leaves the page signed out", async () => {
  const start = browser();
  const first = VigilAuth.createAuth(start.window, CONFIG, { navigate: start.navigate });
  await first.signIn();
  const saved = start.window.sessionStorage.getItem("vigilwatch.pkce");
  const back = browser(`https://dashboard.test/?code=c&state=${JSON.parse(saved).state}`, { error: "invalid_grant" });
  back.window.sessionStorage.setItem("vigilwatch.pkce", saved);
  const auth = VigilAuth.createAuth(back.window, CONFIG, { navigate: back.navigate });
  await assert.rejects(auth.handleRedirect(), /sign-in failed/);
  assert.equal(auth.token(), null);
});

test("signing out forgets the token and ends the hosted UI session", async () => {
  const start = browser();
  const first = VigilAuth.createAuth(start.window, CONFIG, { navigate: start.navigate });
  await first.signIn();
  const saved = start.window.sessionStorage.getItem("vigilwatch.pkce");
  const back = browser(`https://dashboard.test/?code=c&state=${JSON.parse(saved).state}`);
  back.window.sessionStorage.setItem("vigilwatch.pkce", saved);
  const auth = VigilAuth.createAuth(back.window, CONFIG, { navigate: back.navigate });
  await auth.handleRedirect();

  auth.signOut();
  assert.equal(auth.token(), null);
  const visit = back.visits[0];
  assert.equal(visit.origin + visit.pathname, `${HOSTED_UI}/logout`);
  assert.equal(visit.searchParams.get("client_id"), "dashboardclient");
  assert.equal(visit.searchParams.get("logout_uri"), "https://dashboard.test");
});

test("without sign-in settings (the local stack) sign-in is off", () => {
  const b = browser();
  const auth = VigilAuth.createAuth(b.window, undefined, { navigate: b.navigate });
  assert.equal(auth.enabled, false);
  assert.equal(auth.token(), null);
});

test("sign-in settings that are not https are refused", () => {
  const b = browser();
  assert.throws(
    () => VigilAuth.createAuth(b.window, { hostedUiUrl: "http://evil.test", clientId: "x" }),
    /https/,
  );
});

test("with sign-in off every operation is a harmless no-op", async () => {
  const b = browser();
  const auth = VigilAuth.createAuth(b.window, undefined, { navigate: b.navigate });
  assert.equal(await auth.handleRedirect(), false);
  await auth.signIn();
  auth.signOut();
  auth.forget();
  assert.deepEqual(b.visits, [], "nothing navigates");
  assert.equal(b.window.sessionStorage.length, 0, "nothing is stored");
});

test("forgetting the token signs the page out without leaving it", async () => {
  const start = browser();
  const first = VigilAuth.createAuth(start.window, CONFIG, { navigate: start.navigate });
  await first.signIn();
  const saved = start.window.sessionStorage.getItem("vigilwatch.pkce");
  const back = browser(`https://dashboard.test/?code=c&state=${JSON.parse(saved).state}`);
  back.window.sessionStorage.setItem("vigilwatch.pkce", saved);
  const auth = VigilAuth.createAuth(back.window, CONFIG, { navigate: back.navigate });
  await auth.handleRedirect();
  auth.forget();
  assert.equal(auth.token(), null);
  assert.deepEqual(back.visits, [], "no redirect: the user chooses when to sign in again");
});
