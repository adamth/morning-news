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
  window.MorningNewsToast?.queue(
    "Generating episode in the background",
    "success",
  );
  window.MorningNewsToast?.show(
    "Generating episode in the background",
    "success",
  );
  generateButton.disabled = true;
  generateButton.textContent = "Starting…";
});

const stripTransientQueryParams = () => {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("generating")) {
    return;
  }
  url.searchParams.delete("generating");
  const clean = url.pathname + (url.search ? url.search : "") + url.hash;
  history.replaceState(null, "", clean);
};

let sawGenerating = showHero?.dataset.episodeGenerating === "true";

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
    if (status === "generating") {
      sawGenerating = true;
      return;
    }
    if (!sawGenerating) {
      return;
    }
    window.location.replace(window.location.pathname);
  } catch {
    /* ignore transient network errors while polling */
  }
};

if (showHero?.dataset.pollGenerating === "true") {
  stripTransientQueryParams();
  window.setInterval(pollLatestEpisode, 4000);
}
