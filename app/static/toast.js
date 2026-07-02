// Transient alerts from redirect query params (?msg= / ?err=), sessionStorage
// fallbacks, and scroll restoration after form submissions.
(() => {
  const SCROLL_KEY = "mn-scroll-y";
  const PENDING_KEY = "mn-toast-pending";
  const TOAST_DURATION_MS = 5000;
  const EXIT_MS = 220;

  const SUCCESS_ICON = `
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="10" cy="10" r="8.25" stroke="currentColor" stroke-width="1.5"/>
      <path d="M6.5 10.2 8.8 12.5 13.5 7.8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>`;

  const ERROR_ICON = `
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <circle cx="10" cy="10" r="8.25" stroke="currentColor" stroke-width="1.5"/>
      <path d="M10 6.6v4.2M10 13.8h.01" stroke="currentColor" stroke-width="1.75" stroke-linecap="round"/>
    </svg>`;

  const isPostSubmitRedirect = () =>
    /[?&](msg|err)=/.test(window.location.search);

  const readSavedScrollY = () => {
    const raw = sessionStorage.getItem(SCROLL_KEY);
    if (raw === null) return null;
    sessionStorage.removeItem(SCROLL_KEY);
    const scrollY = Number.parseInt(raw, 10);
    return Number.isFinite(scrollY) ? scrollY : null;
  };

  const readPendingToast = () => {
    const raw = sessionStorage.getItem(PENDING_KEY);
    if (raw === null) return null;
    sessionStorage.removeItem(PENDING_KEY);
    try {
      const pending = JSON.parse(raw);
      if (
        pending &&
        typeof pending.message === "string" &&
        pending.message.length > 0
      ) {
        return {
          message: pending.message,
          type: pending.type === "error" ? "error" : "success",
        };
      }
    } catch {
      return null;
    }
    return null;
  };

  const stripRedirectQueryParams = () => {
    const url = new URL(window.location.href);
    const hadMsg = url.searchParams.has("msg");
    const hadErr = url.searchParams.has("err");
    if (!hadMsg && !hadErr) return;

    url.searchParams.delete("msg");
    url.searchParams.delete("err");
    window.history.replaceState(
      {},
      "",
      `${url.pathname}${url.search}${url.hash}`,
    );
  };

  const restoreScrollPosition = (scrollY) => {
    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }

    const scrollToSaved = () => {
      window.scrollTo({ top: scrollY, left: 0, behavior: "instant" });
    };

    scrollToSaved();
    requestAnimationFrame(scrollToSaved);
    window.addEventListener("load", scrollToSaved, { once: true });
  };

  const prepareScrollRestore = () => {
    if (!isPostSubmitRedirect()) return;

    const scrollY = readSavedScrollY();
    if (scrollY === null) return;

    if (window.location.hash) {
      window.history.replaceState(
        {},
        "",
        window.location.pathname + window.location.search,
      );
    }

    if ("scrollRestoration" in window.history) {
      window.history.scrollRestoration = "manual";
    }

    restoreScrollPosition(scrollY);
  };

  let toastRoot = null;
  let activeToast = null;
  let dismissTimer = null;
  let dismissAt = null;

  const ensureToastRoot = () => {
    if (toastRoot) return toastRoot;
    toastRoot = document.createElement("div");
    toastRoot.id = "toast-root";
    toastRoot.className = "toast-root";
    toastRoot.setAttribute("aria-live", "polite");
    toastRoot.setAttribute("aria-atomic", "true");
    document.body.appendChild(toastRoot);
    return toastRoot;
  };

  const clearDismissTimer = () => {
    if (dismissTimer !== null) {
      window.clearTimeout(dismissTimer);
      dismissTimer = null;
    }
    dismissAt = null;
  };

  const removeToast = (toast) => {
    toast.remove();
    if (activeToast === toast) {
      activeToast = null;
    }
  };

  const dismissToast = () => {
    clearDismissTimer();
    if (!activeToast) return;

    const toast = activeToast;
    toast.classList.remove("toast-visible");
    toast.classList.add("toast-leaving");

    window.setTimeout(() => {
      removeToast(toast);
    }, EXIT_MS);
  };

  const scheduleDismiss = (durationMs = TOAST_DURATION_MS) => {
    clearDismissTimer();
    dismissAt = Date.now() + durationMs;
    dismissTimer = window.setTimeout(dismissToast, durationMs);
  };

  const pauseDismiss = () => {
    if (!activeToast || dismissTimer === null || dismissAt === null) return;

    window.clearTimeout(dismissTimer);
    dismissTimer = null;
    const remainingMs = Math.max(0, dismissAt - Date.now());
    activeToast.dataset.remainingMs = String(remainingMs);
    activeToast.querySelector(".toast-progress")?.classList.add("is-paused");
  };

  const resumeDismiss = () => {
    if (!activeToast || dismissTimer !== null) return;

    const remainingMs = Number.parseInt(
      activeToast.dataset.remainingMs || "0",
      10,
    );
    activeToast.querySelector(".toast-progress")?.classList.remove("is-paused");

    if (remainingMs <= 0) {
      dismissToast();
      return;
    }

    scheduleDismiss(remainingMs);
  };

  const showToast = (message, type) => {
    if (!message) return;

    if (activeToast) {
      clearDismissTimer();
      removeToast(activeToast);
    }

    const root = ensureToastRoot();
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");

    const icon = document.createElement("span");
    icon.className = "toast-icon";
    icon.innerHTML = type === "error" ? ERROR_ICON : SUCCESS_ICON;

    const body = document.createElement("div");
    body.className = "toast-body";

    const text = document.createElement("p");
    text.className = "toast-message";
    text.textContent = message;

    const closeButton = document.createElement("button");
    closeButton.type = "button";
    closeButton.className = "toast-dismiss";
    closeButton.setAttribute("aria-label", "Dismiss notification");
    closeButton.innerHTML = `
      <svg viewBox="0 0 20 20" fill="none" aria-hidden="true">
        <path d="M6 6l8 8M14 6l-8 8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      </svg>`;
    closeButton.addEventListener("click", dismissToast);

    body.append(text);
    toast.append(icon, body, closeButton);

    const progress = document.createElement("div");
    progress.className = "toast-progress";
    progress.style.animationDuration = `${TOAST_DURATION_MS}ms`;
    toast.appendChild(progress);

    root.appendChild(toast);
    activeToast = toast;

    toast.addEventListener("mouseenter", pauseDismiss);
    toast.addEventListener("mouseleave", resumeDismiss);

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        toast.classList.add("toast-visible");
        scheduleDismiss(TOAST_DURATION_MS);
      });
    });
  };

  const queueToast = (message, type = "success") => {
    sessionStorage.setItem(
      PENDING_KEY,
      JSON.stringify({ message, type }),
    );
  };

  const readRedirectToast = () => {
    const params = new URLSearchParams(window.location.search);
    const message = params.get("msg");
    const error = params.get("err");

    if (message) {
      return { message, type: "success" };
    }
    if (error) {
      return { message: error, type: "error" };
    }
    return readPendingToast();
  };

  const init = () => {
    prepareScrollRestore();

    const redirectToast = readRedirectToast();
    if (redirectToast) {
      showToast(redirectToast.message, redirectToast.type);
      stripRedirectQueryParams();
    }
  };

  window.MorningNewsToast = { show: showToast, queue: queueToast };

  init();
})();
