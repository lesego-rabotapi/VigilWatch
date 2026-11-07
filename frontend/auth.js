/* VigilWatch sign-in: Cognito's hosted UI with the authorization code flow and PKCE (ADR 0007).
 *
 * The access token is held in this closure only, never in localStorage, sessionStorage or a
 * cookie. Only the PKCE verifier and the state value are kept in sessionStorage, for the length of
 * the redirect, and removed as soon as they are read. Reloading the page means signing in again;
 * Cognito's own session makes that a redirect, not a password.
 *
 * Loaded in the browser as window.VigilAuth and in Node tests via require(). */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.VigilAuth = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const PENDING = "vigilwatch.pkce";
  const SCOPE = "openid email";

  function base64url(bytes) {
    let text = "";
    for (const byte of new Uint8Array(bytes)) text += String.fromCharCode(byte);
    return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  function randomString(win, length) {
    return base64url(win.crypto.getRandomValues(new Uint8Array(length)));
  }

  async function challengeFor(win, verifier) {
    const digest = await win.crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
    return base64url(digest);
  }

  function signedOff() {
    return {
      enabled: false,
      token: () => null,
      handleRedirect: () => Promise.resolve(false),
      signIn: () => Promise.resolve(),
      signOut: () => {},
      forget: () => {},
    };
  }

  /** Sign-in for `config` ({hostedUiUrl, clientId}); without config sign-in is off. */
  function createAuth(win, config, options = {}) {
    if (!config) return signedOff();
    const base = String(config.hostedUiUrl || "").replace(/\/+$/, "");
    if (!base.startsWith("https://") || !config.clientId) {
      throw new Error("Sign-in settings need an https hostedUiUrl and a clientId (config.js)");
    }
    const navigate = options.navigate || ((target) => win.location.assign(target));
    const redirectUri = win.location.origin; // the client's callback and sign-out URL
    let accessToken = null;

    function clearAddressBar() {
      win.history.replaceState(null, "", win.location.pathname);
    }

    async function signIn() {
      const verifier = randomString(win, 48); // 64 characters, within RFC 7636's 43 to 128
      const state = randomString(win, 24);
      win.sessionStorage.setItem(PENDING, JSON.stringify({ verifier, state }));
      const query = new URLSearchParams({
        response_type: "code",
        client_id: config.clientId,
        redirect_uri: redirectUri,
        scope: SCOPE,
        state,
        code_challenge: await challengeFor(win, verifier),
        code_challenge_method: "S256",
      });
      navigate(`${base}/oauth2/authorize?${query}`);
    }

    /** Finish a sign-in the hosted UI sent the browser back from. True if now signed in. */
    async function handleRedirect() {
      const params = new URLSearchParams(win.location.search);
      if (params.has("error")) {
        clearAddressBar();
        win.sessionStorage.removeItem(PENDING);
        throw new Error(params.get("error_description") || params.get("error"));
      }
      const code = params.get("code");
      if (!code) return false;
      clearAddressBar();
      let pending = null;
      try {
        pending = JSON.parse(win.sessionStorage.getItem(PENDING) || "null");
      } catch {
        /* a truncated value is the same as none: ask to sign in again */
      }
      win.sessionStorage.removeItem(PENDING); // a code is redeemed once, or not at all
      if (!pending || pending.state !== params.get("state")) {
        throw new Error("This sign-in was not started here. Sign in again.");
      }
      const response = await win.fetch(`${base}/oauth2/token`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({
          grant_type: "authorization_code",
          client_id: config.clientId,
          code,
          redirect_uri: redirectUri,
          code_verifier: pending.verifier,
        }).toString(),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok || !body.access_token) {
        throw new Error(`The sign-in failed (${body.error || response.status}). Sign in again.`);
      }
      accessToken = body.access_token;
      return true;
    }

    return {
      enabled: true,
      token: () => accessToken,
      handleRedirect,
      signIn,
      /** Forget the token here, e.g. when the API no longer accepts it. */
      forget: () => {
        accessToken = null;
      },
      /** Forget the token and end the hosted UI's session too. */
      signOut: () => {
        accessToken = null;
        const query = new URLSearchParams({ client_id: config.clientId, logout_uri: redirectUri });
        navigate(`${base}/logout?${query}`);
      },
    };
  }

  return { createAuth };
});
