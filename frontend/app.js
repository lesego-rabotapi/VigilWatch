/* VigilWatch dashboard wiring. Rendering lives in view.js; the API URL comes
 * from config.js, which Terraform generates at deploy time.
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

  const form = doc.getElementById("monitor-form");
  const urlInput = doc.getElementById("endpoint-url");
  const startButton = doc.getElementById("start-button");
  const inputError = doc.getElementById("input-error");

  let api;
  try {
    api = View.apiBase(win.VIGILWATCH_CONFIG);
  } catch (err) {
    inputError.textContent = err.message;
    startButton.disabled = true;
    return;
  }

  const poller = View.createPoller(win, POLL_MS);

  function setIdle(label) {
    urlInput.disabled = false;
    startButton.disabled = false;
    startButton.textContent = label;
  }

  function register(url) {
    return win
      .fetch(`${api}/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      })
      .then(View.readJson);
  }

  function poll(url) {
    return win.fetch(`${api}/checks?url=${encodeURIComponent(url)}`).then(View.readJson);
  }

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
        View.updateView(doc, data);
        setIdle("Monitor another URL");
        // Poll with the canonical URL the API stored.
        poller.start(() => {
          poll(data.url)
            .then((latest) => View.updateView(doc, latest))
            .catch((err) => console.error("Poll error:", err));
        });
      })
      .catch((err) => {
        console.error(err);
        inputError.textContent = `Could not start monitoring: ${err.message}`;
        setIdle("Start Monitoring");
      });
  });
});
