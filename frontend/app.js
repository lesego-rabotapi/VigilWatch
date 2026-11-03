/* VigilWatch dashboard wiring. Rendering lives in view.js and sign-in in auth.js; the API URL
 * and the sign-in settings come from config.js, which Terraform generates at deploy time.
 *
 * In a browser this file starts itself. Under Node (tests) it exports init(window)
 * so the whole flow can be driven against a jsdom window. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory;
  } else {
    factory(root);
  }
})(typeof self !== "undefined" ? self : this, function init(win) {
  "use strict";

  const View = win.VigilView;
  const doc = win.document;
  const POLL_MS = 15000;
  const SESSION_ENDED = "Your session has ended. Sign in again.";

  const form = doc.getElementById("monitor-form");
  const urlInput = doc.getElementById("endpoint-url");
  const startButton = doc.getElementById("start-button");
  const inputError = doc.getElementById("input-error");
  const signInButton = doc.getElementById("sign-in");
  const signOutButton = doc.getElementById("sign-out");

  let api;
  let auth;
  try {
    api = View.apiBase(win.VIGILWATCH_CONFIG);
    auth = win.VigilAuth.createAuth(win, win.VIGILWATCH_CONFIG.auth);
  } catch (err) {
    inputError.textContent = err.message;
    startButton.disabled = true;
    return Promise.resolve();
  }

  const poller = View.createPoller(win, POLL_MS);

  /** Thrown when the API refused the token: the page is already signed out by then. */
  class SignedOut extends Error {}

  function setIdle(label) {
    urlInput.disabled = false;
    startButton.disabled = false;
    startButton.textContent = label;
  }

  function showSignedIn() {
    signInButton.classList.add("hidden");
    signOutButton.classList.remove("hidden");
    setIdle("Start Monitoring");
  }

  /** False once signed out: a reply that arrives after that must not touch the page. */
  function stillSignedIn() {
    return !auth.enabled || Boolean(auth.token());
  }

  function showSignedOut(message) {
    poller.stop();
    View.clearView(doc);
    urlInput.value = "";
    urlInput.disabled = true;
    startButton.disabled = true;
    signOutButton.classList.add("hidden");
    signInButton.classList.remove("hidden");
    if (message) inputError.textContent = message;
  }

  function headers(extra = {}) {
    const token = auth.token();
    return token ? { ...extra, Authorization: `Bearer ${token}` } : extra;
  }

  function call(url, options = {}) {
    return win.fetch(url, { ...options, headers: headers(options.headers) }).then((res) => {
      if (res.status === 401 && auth.enabled) {
        auth.forget();
        showSignedOut(SESSION_ENDED);
        throw new SignedOut(SESSION_ENDED);
      }
      return View.readJson(res);
    });
  }

  function register(url) {
    return call(`${api}/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
  }

  function poll(url) {
    return call(`${api}/checks?url=${encodeURIComponent(url)}`);
  }

  signInButton.addEventListener("click", () => {
    auth.signIn().catch((err) => {
      inputError.textContent = `Could not start the sign-in: ${err.message}`;
    });
  });

  signOutButton.addEventListener("click", () => {
    showSignedOut();
    auth.signOut();
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    inputError.textContent = "";

    const value = urlInput.value.trim();
    if (!View.isValidHttpUrl(value)) {
      inputError.textContent = "Please enter a valid http/https URL.";
      return;
    }

    urlInput.disabled = true;
    startButton.disabled = true;
    startButton.textContent = "Starting...";
    poller.stop();

    return register(value)
      .then((data) => {
        if (!stillSignedIn()) return; // signed out while the request was in flight
        View.updateView(doc, data);
        setIdle("Monitor another URL");
        // Poll with the canonical URL the API stored.
        poller.start(() => {
          poll(data.url)
            .then((latest) => {
              if (stillSignedIn()) View.updateView(doc, latest);
            })
            .catch((err) => {
              if (!(err instanceof SignedOut)) console.error("Poll error:", err);
            });
        });
      })
      .catch((err) => {
        if (err instanceof SignedOut || !stillSignedIn()) return; // signed out, reason shown
        console.error(err);
        inputError.textContent = `Could not start monitoring: ${err.message}`;
        setIdle("Start Monitoring");
      });
  });

  // The local stack has no sign-in: the page is open, with no session buttons.
  if (!auth.enabled) return Promise.resolve();

  urlInput.disabled = true;
  startButton.disabled = true;
  return auth
    .handleRedirect()
    .then((signedIn) => (signedIn ? showSignedIn() : showSignedOut()))
    .catch((err) => showSignedOut(err.message));
});
