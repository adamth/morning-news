(() => {
  const modelInput = document.getElementById("openrouter_model");
  const suggestionsEl = document.getElementById("openrouter-model-suggestions");

  if (!modelInput || !modelInput.dataset.modelAutocomplete || !suggestionsEl) {
    return;
  }

  let debounceTimer = null;
  let activeIndex = -1;
  let currentResults = [];
  let selectedModelId = modelInput.value.trim();

  const hideSuggestions = () => {
    suggestionsEl.hidden = true;
    suggestionsEl.innerHTML = "";
    activeIndex = -1;
    currentResults = [];
  };

  const applySelection = (item) => {
    modelInput.value = item.id;
    selectedModelId = item.id;
    hideSuggestions();
  };

  const renderSuggestions = (results) => {
    currentResults = results;
    activeIndex = -1;
    suggestionsEl.innerHTML = "";
    if (!results.length) {
      suggestionsEl.hidden = true;
      return;
    }
    results.forEach((item, index) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "location-suggestion";
      button.textContent = item.label;
      button.addEventListener("mousedown", (event) => {
        event.preventDefault();
        applySelection(item);
      });
      button.dataset.index = String(index);
      suggestionsEl.appendChild(button);
    });
    suggestionsEl.hidden = false;
  };

  const fetchSuggestions = async (query) => {
    try {
      const response = await fetch(
        `/api/openrouter/models?q=${encodeURIComponent(query)}`,
        { credentials: "same-origin", headers: { Accept: "application/json" } },
      );
      if (!response.ok) {
        hideSuggestions();
        return;
      }
      const results = await response.json();
      renderSuggestions(results);
    } catch {
      hideSuggestions();
    }
  };

  modelInput.addEventListener("focus", () => {
    fetchSuggestions(modelInput.value.trim());
  });

  modelInput.addEventListener("input", () => {
    if (modelInput.value.trim() !== selectedModelId) {
      selectedModelId = "";
    }
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => fetchSuggestions(modelInput.value.trim()), 200);
  });

  modelInput.addEventListener("keydown", (event) => {
    if (suggestionsEl.hidden || !currentResults.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      activeIndex = Math.min(activeIndex + 1, currentResults.length - 1);
      highlightActive();
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
      highlightActive();
    } else if (event.key === "Enter" && activeIndex >= 0) {
      event.preventDefault();
      applySelection(currentResults[activeIndex]);
    } else if (event.key === "Escape") {
      hideSuggestions();
    }
  });

  const highlightActive = () => {
    suggestionsEl.querySelectorAll(".location-suggestion").forEach((element, index) => {
      element.classList.toggle("active", index === activeIndex);
    });
  };

  document.addEventListener("click", (event) => {
    if (!event.target.closest(".location-field")?.contains(modelInput)) {
      hideSuggestions();
    }
  });
})();
