const copyFeedButton = document.getElementById("copy-feed-button");
const copyFeedFeedback = document.getElementById("copy-feed-feedback");
const feedUrlElement = document.getElementById("feed-url");
const generateForm = document.getElementById("generate-form");
const generateButton = document.getElementById("generate-button");
const showHero = document.getElementById("show-hero");
const copyFeedLabel = "Copy feed URL";

const showCopyFeedback = (message) => {
  if (!copyFeedFeedback) {
    return;
  }
  copyFeedFeedback.textContent = message;
  window.setTimeout(() => {
    copyFeedFeedback.textContent = "";
  }, 2000);
};

copyFeedButton?.addEventListener("click", async () => {
  const feedUrl = feedUrlElement?.innerText?.trim();
  if (!feedUrl) {
    showCopyFeedback("Nothing to copy.");
    return;
  }
  try {
    await navigator.clipboard.writeText(feedUrl);
    showCopyFeedback("Copied to clipboard.");
    copyFeedButton.setAttribute("aria-label", "Copied");
    copyFeedButton.classList.add("is-copied");
    window.setTimeout(() => {
      copyFeedButton.setAttribute("aria-label", copyFeedLabel);
      copyFeedButton.classList.remove("is-copied");
    }, 2000);
  } catch {
    showCopyFeedback("Copy failed — select the URL and copy manually.");
  }
});

generateForm?.addEventListener("submit", () => {
  if (!generateButton) {
    return;
  }
  generateButton.disabled = true;
  generateButton.textContent = "Starting…";
});

const pollLatestEpisode = async () => {
  try {
    const response = await fetch("/api/episodes/latest", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    const status = payload.episode?.status;
    if (status && status !== "generating") {
      window.location.reload();
    }
  } catch {
    /* ignore transient network errors while polling */
  }
};

if (showHero?.dataset.pollGenerating === "true") {
  window.setInterval(pollLatestEpisode, 4000);
}
