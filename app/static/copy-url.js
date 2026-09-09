// Copy buttons for the feed and latest-episode addresses. Delegated so any
// number of .url-row blocks work without per-instance wiring.
(() => {
  const announce = (row, message) => {
    const feedback = row.querySelector(".url-copy-feedback");
    if (!feedback) return;
    feedback.textContent = message;
    window.setTimeout(() => {
      feedback.textContent = "";
    }, 2000);
  };

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-url]");
    if (!button) return;

    const row = button.closest(".url-row");
    const url = row?.querySelector(".url-text")?.innerText?.trim();
    if (!url) {
      announce(row, "Nothing to copy.");
      return;
    }

    const label = button.getAttribute("aria-label") ?? "Copy";
    try {
      await navigator.clipboard.writeText(url);
      announce(row, "Copied to clipboard.");
      button.classList.add("is-copied");
      button.setAttribute("aria-label", "Copied");
      window.setTimeout(() => {
        button.classList.remove("is-copied");
        button.setAttribute("aria-label", label);
      }, 2000);
    } catch {
      announce(row, "Copy failed — select the URL and copy manually.");
    }
  });
})();
