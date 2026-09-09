// Settings page behaviour: the section rail's active state, the weekly-focus
// rows that only show a notes box when the segment wants one, and the voice
// controls that reload from the narration service when it changes.
(() => {
  const railLinks = [...document.querySelectorAll("[data-rail-target]")];
  const sections = railLinks
    .map((link) => document.getElementById(link.dataset.railTarget))
    .filter(Boolean);

  if (railLinks.length && sections.length && "IntersectionObserver" in window) {
    const setActive = (anchor) => {
      for (const link of railLinks) {
        link.classList.toggle("is-active", link.dataset.railTarget === anchor);
      }
    };

    const visible = new Set();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        }
        const topmost = sections.find((section) => visible.has(section.id));
        if (topmost) setActive(topmost.id);
      },
      { rootMargin: "-84px 0px -55% 0px" },
    );
    for (const section of sections) observer.observe(section);
    setActive(location.hash.slice(1) || sections[0].id);
  }
})();

(() => {
  const metaScript = document.getElementById("report-type-meta");
  if (!metaScript) return;

  let reportTypes = {};
  try {
    reportTypes = JSON.parse(metaScript.textContent);
  } catch {
    return;
  }

  const syncRow = (row) => {
    const select = row.querySelector("select");
    const inputWrap = row.querySelector(".weekly-input");
    const textarea = row.querySelector("textarea");
    if (!select || !inputWrap || !textarea) return;

    const meta = reportTypes[select.value.trim()];
    inputWrap.dataset.empty = meta?.wants_input ? "false" : "true";
    textarea.placeholder = meta ? meta.placeholder || meta.hint || "" : "";
  };

  for (const row of document.querySelectorAll(".weekly-row")) {
    syncRow(row);
    row.querySelector("select")?.addEventListener("change", () => syncRow(row));
  }
})();

(() => {
  const ttsProvider = document.getElementById("tts_provider");
  const randomize = document.getElementById("voice_randomize");
  const pickerRow = document.getElementById("voice-picker-row");
  const voiceModel = document.getElementById("voice_model");
  const voiceControl = document.getElementById("voice-id-control");
  const voiceHint = document.getElementById("voice-id-hint");
  const toneRow = document.getElementById("speechify-tone-row");
  const toneSelect = document.getElementById("speechify_emotion");
  const previewRow = document.getElementById("voice-preview-row");
  const previewAudio = document.getElementById("voice-preview-audio");
  const previewById = new Map();

  if (!ttsProvider) return;

  const formatAccent = (accent) =>
    accent.replace(/-/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());

  const currentVoiceId = () => voiceControl?.querySelector("#voice_id")?.value ?? "";

  const fillSelect = (select, items, selectedValue) => {
    select.replaceChildren();
    for (const item of items) {
      const option = document.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      if (item.value === selectedValue) option.selected = true;
      select.appendChild(option);
    }
  };

  const syncTone = (visible) => {
    if (toneRow) toneRow.hidden = !visible;
  };

  const syncPicker = () => {
    if (randomize && pickerRow) pickerRow.hidden = randomize.checked;
  };

  const indexPreviews = (voices) => {
    previewById.clear();
    for (const voice of voices ?? []) {
      const url = voice.preview_url?.trim();
      if (url) previewById.set(voice.voice_id, url);
    }
  };

  const indexPreviewsFromMarkup = () => {
    previewById.clear();
    for (const option of voiceControl?.querySelectorAll("select#voice_id option") ?? []) {
      const url = option.dataset.previewUrl?.trim();
      if (url) previewById.set(option.value, url);
    }
  };

  const syncPreview = () => {
    if (!previewRow || !previewAudio) return;
    const url = ttsProvider.value === "speechify" ? previewById.get(currentVoiceId()) : "";
    if (!url) {
      previewRow.hidden = true;
      previewAudio.removeAttribute("src");
      previewAudio.load();
      return;
    }
    previewRow.hidden = false;
    if (previewAudio.getAttribute("src") !== url) {
      previewAudio.src = url;
      previewAudio.load();
    }
  };

  const renderVoiceControl = (voices, selectedVoiceId) => {
    if (!voiceControl) return;
    if (voices.length > 0) {
      const select = document.createElement("select");
      select.id = "voice_id";
      select.name = "voice_id";
      fillSelect(
        select,
        voices.map((voice) => ({
          value: voice.voice_id,
          label: voice.accent ? `${voice.name} (${formatAccent(voice.accent)})` : voice.name,
        })),
        selectedVoiceId,
      );
      for (const [index, voice] of voices.entries()) {
        const url = voice.preview_url?.trim();
        if (url && select.options[index]) select.options[index].dataset.previewUrl = url;
      }
      voiceControl.replaceChildren(select);
      if (voiceHint) voiceHint.hidden = true;
      indexPreviews(voices);
      syncPreview();
      return;
    }

    previewById.clear();
    syncPreview();

    const input = document.createElement("input");
    input.type = "text";
    input.id = "voice_id";
    input.name = "voice_id";
    input.value = selectedVoiceId;
    input.placeholder = "Voice ID from your narration provider";
    voiceControl.replaceChildren(input);
    if (voiceHint) voiceHint.hidden = false;
  };

  const reloadForProvider = async () => {
    try {
      const response = await fetch(`/api/tts/voices?provider=${encodeURIComponent(ttsProvider.value)}`);
      if (!response.ok) return;
      const data = await response.json();

      if (voiceModel) {
        fillSelect(
          voiceModel,
          (data.voice_models ?? []).map((model) => ({ value: model.id, label: model.label })),
          data.default_voice_model,
        );
      }
      renderVoiceControl(data.voices ?? [], data.default_voice_id);
      syncTone(Boolean(data.show_speechify_tone));
      if (data.show_speechify_tone && toneSelect) {
        fillSelect(
          toneSelect,
          (data.speechify_emotions ?? []).map((emotion) => ({
            value: emotion.id,
            label: emotion.label,
          })),
          "",
        );
      }
    } catch {
      // Keep the existing controls if the request fails.
    }
  };

  ttsProvider.addEventListener("change", () => {
    syncTone(ttsProvider.value === "speechify");
    reloadForProvider();
  });
  randomize?.addEventListener("change", syncPicker);
  voiceControl?.addEventListener("change", (event) => {
    if (event.target.id === "voice_id") syncPreview();
  });

  syncPicker();
  syncTone(ttsProvider.value === "speechify");
  indexPreviewsFromMarkup();
  syncPreview();
})();
