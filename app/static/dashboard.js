const generateForm = document.getElementById("generate-form");
const generateButton = document.getElementById("generate-button");
const hero = document.getElementById("hero");

generateForm?.addEventListener("submit", () => {
  if (!generateButton) return;
  window.MorningNewsToast?.queue("Generating episode in the background", "success");
  window.MorningNewsToast?.show("Generating episode in the background", "success");
  generateButton.disabled = true;
  generateButton.textContent = "Starting…";
});

const stripTransientQueryParams = () => {
  const url = new URL(window.location.href);
  if (!url.searchParams.has("generating")) return;
  url.searchParams.delete("generating");
  history.replaceState(null, "", url.pathname + url.search + url.hash);
};

let sawGenerating = hero?.dataset.episodeGenerating === "true";

const pollLatestEpisode = async () => {
  try {
    const response = await fetch("/api/episodes/latest", {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) return;
    const payload = await response.json();
    if (payload.episode?.status === "generating") {
      sawGenerating = true;
      return;
    }
    if (!sawGenerating) return;
    window.location.replace(window.location.pathname);
  } catch {
    /* ignore transient network errors while polling */
  }
};

if (hero?.dataset.pollGenerating === "true") {
  stripTransientQueryParams();
  window.setInterval(pollLatestEpisode, 4000);
}
