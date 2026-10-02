/* VigilWatch dashboard wiring. Rendering lives in view.js; the API URL comes
 * from config.js, which Terraform generates at deploy time. */
(function () {
  "use strict";

  const View = window.VigilView;
  const POLL_MS = 15000;

  const form = document.getElementById("monitor-form");
  const urlInput = document.getElementById("endpoint-url");
  const startButton = document.getElementById("start-button");
  const inputError = document.getElementById("input-error");

  let api;
  try {
    api = View.apiBase(window.VIGILWATCH_CONFIG);
  } catch (err) {
    inputError.textContent = err.message;
    startButton.disabled = true;
    return;
  }

  const poller = View.createPoller(window, POLL_MS);

  function setIdle(label) {
    urlInput.disabled = false;
    startButton.disabled = false;
    startButton.textContent = label;
  }

  function register(url) {
    return fetch(`${api}/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    }).then(View.readJson);
  }

  function poll(url) {
    return fetch(`${api}/checks?url=${encodeURIComponent(url)}`).then(View.readJson);
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

    register(value)
      .then((data) => {
        View.updateView(document, data);
        setIdle("Monitor another URL");
        // Poll with the canonical URL the API stored.
        poller.start(() => {
          poll(data.url)
            .then((latest) => View.updateView(document, latest))
            .catch((err) => console.error("Poll error:", err));
        });
      })
      .catch((err) => {
        console.error(err);
        inputError.textContent = `Could not start monitoring: ${err.message}`;
        setIdle("Start Monitoring");
      });
  });
})();
