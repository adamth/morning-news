// Form safety for settings pages: dirty-state indicators, an unsaved-changes
// warning when leaving the page, confirmation on destructive actions, and
// double-submit prevention.
(() => {
  const dirtyForms = new Set();
  let submittingForm = null;

  const isTrackableForm = (form) =>
    form.method.toLowerCase() === "post" && !form.hasAttribute("data-confirm");

  const indicatorFor = (form) => {
    const actions = form.querySelector(".form-actions");
    if (!actions) return null;
    let indicator = actions.querySelector(".form-unsaved");
    if (!indicator) {
      indicator = document.createElement("span");
      indicator.className = "form-unsaved";
      indicator.setAttribute("role", "status");
      indicator.textContent = "Unsaved changes";
      indicator.hidden = true;
      actions.appendChild(indicator);
    }
    return indicator;
  };

  const markDirty = (form) => {
    if (dirtyForms.has(form)) return;
    dirtyForms.add(form);
    const indicator = indicatorFor(form);
    if (indicator) indicator.hidden = false;
  };

  const markClean = (form) => {
    dirtyForms.delete(form);
    const indicator = form.querySelector(".form-unsaved");
    if (indicator) indicator.hidden = true;
  };

  // Inputs can live outside their form element (form="..." association),
  // so track ownership through the input's .form property.
  const ownerForm = (element) => (element && element.form) || null;

  document.addEventListener("input", (event) => {
    const form = ownerForm(event.target);
    if (form && isTrackableForm(form)) markDirty(form);
  });

  document.addEventListener("change", (event) => {
    const form = ownerForm(event.target);
    if (form && isTrackableForm(form)) markDirty(form);
  });

  document.addEventListener("submit", (event) => {
    const form = event.target;

    const confirmMessage = form.getAttribute("data-confirm");
    if (confirmMessage && !window.confirm(confirmMessage)) {
      event.preventDefault();
      return;
    }

    submittingForm = form;
    markClean(form);
    sessionStorage.setItem("mn-scroll-y", String(window.scrollY));

    // Disable submit buttons after this tick so the click still submits,
    // then guard against a second click while the request is in flight.
    const submitButtons = form.id
      ? document.querySelectorAll(`button[type="submit"][form="${form.id}"], #${form.id} button[type="submit"]`)
      : form.querySelectorAll('button[type="submit"]');
    window.setTimeout(() => {
      submitButtons.forEach((button) => {
        button.disabled = true;
      });
    }, 0);

    // If the request never navigates (e.g. server hiccup), re-enable
    // so the user is not stuck with a dead button.
    window.setTimeout(() => {
      submitButtons.forEach((button) => {
        button.disabled = false;
      });
      submittingForm = null;
    }, 15000);
  });

  window.addEventListener("beforeunload", (event) => {
    // Warn when any form other than the one being submitted still has edits.
    const unsavedElsewhere = [...dirtyForms].some((form) => form !== submittingForm);
    if (unsavedElsewhere) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
})();
