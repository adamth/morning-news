// Sticky bottom player. Every [data-play-episode] button on the page feeds the
// single <audio> element in the bar, so starting one episode stops the last.
(() => {
  const bar = document.getElementById("player");
  const audio = document.getElementById("player-audio");
  const toggle = document.getElementById("player-toggle");
  const titleEl = document.getElementById("player-title");
  const scrub = document.getElementById("player-scrub");
  const timeEl = document.getElementById("player-time");
  const closeButton = document.getElementById("player-close");

  if (!bar || !audio || !toggle) return;

  let currentId = null;
  let isScrubbing = false;

  const triggers = () => document.querySelectorAll("[data-play-episode]");

  const formatTime = (seconds) => {
    if (!Number.isFinite(seconds)) return "0:00";
    const whole = Math.floor(seconds);
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
  };

  const paintScrub = (percent) => {
    scrub?.style.setProperty("--played", `${percent}%`);
  };

  const syncButtons = () => {
    const playing = !audio.paused && currentId !== null;
    toggle.classList.toggle("is-playing", playing);
    toggle.setAttribute("aria-label", playing ? "Pause" : "Play");
    for (const trigger of triggers()) {
      const isCurrent = trigger.dataset.playEpisode === currentId;
      trigger.classList.toggle("is-playing", isCurrent && playing);
      trigger.setAttribute(
        "aria-label",
        `${isCurrent && playing ? "Pause" : "Play"} ${trigger.dataset.episodeTitle || "episode"}`,
      );
    }
  };

  const load = (episodeId, title) => {
    currentId = episodeId;
    audio.src = `/media/${episodeId}.mp3`;
    titleEl.textContent = title || `Episode ${episodeId}`;
    bar.hidden = false;
    document.body.classList.add("player-open");
    if (scrub) scrub.value = "0";
    paintScrub(0);
    if (timeEl) timeEl.textContent = "0:00";
  };

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-play-episode]");
    if (!trigger || trigger.disabled) return;
    event.preventDefault();

    const episodeId = trigger.dataset.playEpisode;
    if (episodeId === currentId) {
      if (audio.paused) audio.play().catch(() => {});
      else audio.pause();
      return;
    }
    load(episodeId, trigger.dataset.episodeTitle);
    audio.play().catch(() => {});
  });

  toggle.addEventListener("click", () => {
    if (currentId === null) return;
    if (audio.paused) audio.play().catch(() => {});
    else audio.pause();
  });

  closeButton?.addEventListener("click", () => {
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    currentId = null;
    bar.hidden = true;
    document.body.classList.remove("player-open");
    syncButtons();
  });

  audio.addEventListener("play", syncButtons);
  audio.addEventListener("pause", syncButtons);
  audio.addEventListener("ended", syncButtons);

  audio.addEventListener("timeupdate", () => {
    if (isScrubbing || !Number.isFinite(audio.duration)) return;
    const percent = (audio.currentTime / audio.duration) * 100;
    if (scrub) scrub.value = String(percent);
    paintScrub(percent);
    if (timeEl) {
      timeEl.textContent = `${formatTime(audio.currentTime)} / ${formatTime(audio.duration)}`;
    }
  });

  scrub?.addEventListener("input", () => {
    isScrubbing = true;
    paintScrub(Number(scrub.value));
  });

  scrub?.addEventListener("change", () => {
    if (Number.isFinite(audio.duration)) {
      audio.currentTime = (Number(scrub.value) / 100) * audio.duration;
    }
    isScrubbing = false;
  });
})();
