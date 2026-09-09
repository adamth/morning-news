(() => {
  const button = document.getElementById("copy-feed-button");
  const feedback = document.getElementById("copy-feed-feedback");
  const urlElement = document.getElementById("feed-url");
  if (!button) return;

  const announce = (message) => {
    if (!feedback) return;
    feedback.textContent = message;
    window.setTimeout(() => {
      feedback.textContent = "";
    }, 2000);
  };

  button.addEventListener("click", async () => {
    const feedUrl = urlElement?.innerText?.trim();
    if (!feedUrl) {
      announce("Nothing to copy.");
      return;
    }
    try {
      await navigator.clipboard.writeText(feedUrl);
      announce("Copied to clipboard.");
      button.classList.add("is-copied");
      button.setAttribute("aria-label", "Copied");
      window.setTimeout(() => {
        button.classList.remove("is-copied");
        button.setAttribute("aria-label", "Copy feed URL");
      }, 2000);
    } catch {
      announce("Copy failed — select the URL and copy manually.");
    }
  });
})();
