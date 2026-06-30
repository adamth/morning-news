(() => {
  const addressInput = document.getElementById("address");
  const suggestionsEl = document.getElementById("location-suggestions");
  const statusEl = document.getElementById("location-status");
  const newsDisplayEl = document.getElementById("news-edition-display");

  if (!addressInput || !suggestionsEl) {
    return;
  }

  const fields = {
    confirmed: document.getElementById("location_confirmed"),
    latitude: document.getElementById("latitude"),
    longitude: document.getElementById("longitude"),
    locality: document.getElementById("locality"),
    countryCode: document.getElementById("country_code"),
    admin1: document.getElementById("admin1"),
    country: document.getElementById("country"),
    timezone: document.getElementById("timezone"),
    newsHl: document.getElementById("news_hl"),
    newsGl: document.getElementById("news_gl"),
    newsCeid: document.getElementById("news_ceid"),
  };

  let debounceTimer = null;
  let activeIndex = -1;
  let currentResults = [];
  const initialAddress = addressInput.dataset.initialAddress || "";

  const clearSelection = () => {
    fields.confirmed.value = "";
    fields.latitude.value = "";
    fields.longitude.value = "";
    fields.locality.value = "";
    fields.countryCode.value = "";
    fields.admin1.value = "";
    fields.country.value = "";
    updateStatus("Choose your town from the list before saving.", "warn");
    updateNewsDisplay();
  };

  const applySelection = (item) => {
    addressInput.value = item.label;
    fields.confirmed.value = "1";
    fields.latitude.value = String(item.latitude);
    fields.longitude.value = String(item.longitude);
    fields.locality.value = item.locality;
    fields.countryCode.value = item.country_code;
    fields.admin1.value = item.admin1 || "";
    fields.country.value = item.country || "";
    if (fields.timezone && item.timezone) {
      fields.timezone.value = item.timezone;
    }
    if (fields.newsHl) fields.newsHl.value = item.news_hl;
    if (fields.newsGl) fields.newsGl.value = item.news_gl;
    if (fields.newsCeid) fields.newsCeid.value = item.news_ceid;
    hideSuggestions();
    updateStatus(
      `Weather and local news will use ${item.locality} (${fields.timezone?.value || item.timezone || "UTC"}).`,
      "ok",
    );
    updateNewsDisplay();
  };

  const updateStatus = (text, tone) => {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.dataset.tone = tone || "";
  };

  const updateNewsDisplay = () => {
    if (!newsDisplayEl || !fields.newsHl) return;
    if (fields.confirmed.value === "1" && fields.newsHl.value) {
      newsDisplayEl.textContent = `Local news region: ${fields.newsHl.value} / ${fields.newsGl.value}`;
    } else {
      newsDisplayEl.textContent = "";
    }
  };

  const hideSuggestions = () => {
    suggestionsEl.hidden = true;
    suggestionsEl.innerHTML = "";
    activeIndex = -1;
    currentResults = [];
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
    if (query.length < 2) {
      hideSuggestions();
      return;
    }
    try {
      const response = await fetch(
        `/api/locations/search?q=${encodeURIComponent(query)}`,
        { credentials: "same-origin", headers: { Accept: "application/json" } },
      );
      if (!response.ok) {
        updateStatus("Could not load town suggestions. Try refreshing the page.", "warn");
        hideSuggestions();
        return;
      }
      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("application/json")) {
        updateStatus("Session expired — please sign in again.", "warn");
        hideSuggestions();
        return;
      }
      const results = await response.json();
      if (!results.length) {
        updateStatus("No matching towns. Try a nearby city or a shorter spelling.", "warn");
        hideSuggestions();
        return;
      }
      renderSuggestions(results);
    } catch {
      updateStatus("Could not load town suggestions.", "warn");
      hideSuggestions();
    }
  };

  addressInput.addEventListener("input", () => {
    if (!addressInput.value.trim()) {
      clearSelection();
      hideSuggestions();
      updateStatus("Type a few letters, then choose your town from the list.", "");
      return;
    }
    if (addressInput.value.trim() !== initialAddress) {
      clearSelection();
    }
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => fetchSuggestions(addressInput.value.trim()), 250);
  });

  addressInput.addEventListener("keydown", (event) => {
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
    if (!event.target.closest(".location-field")) {
      hideSuggestions();
    }
  });

  if (fields.confirmed.value === "1") {
    updateNewsDisplay();
  }
})();
