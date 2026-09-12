/* One refresh lifecycle: live work, callback result, then visible render acknowledgements. */
(() => {
  "use strict";
  const app = window.__cubeV5Assets = window.__cubeV5Assets || {};
  const STAGES = ["readiness", "risk", "market", "pl", "final"];
  const POLL_MS = 1000;
  const TIMEOUT_MS = 30000;
  let state = null;
  let lastProgress = null;
  let pollPromise = null;
  let startPromise = null;
  let nextPoll = 0;
  let nextStart = 0;
  let failures = 0;
  let lastSuccessAt = 0;
  let transportError = "";
  let stopped = false;
  let paintQueued = false;
  let observer = null;
  let pageKey = window.location.pathname;
  let lastStartupLayout = null;
  let initialProgressSeen = false;
  const viewAcks = new Map();
  const preparedViews = new Map();
  const node = (id) => document.getElementById(id);
  const revision = (value) => {
    if (value === null || value === undefined || String(value).trim() === "") return null;
    const result = Number(value);
    return Number.isSafeInteger(result) && result >= 0 ? result : null;
  };
  const text = (id, value) => {
    const element = node(id);
    const next = String(value ?? "");
    if (element && element.textContent !== next) element.textContent = next;
  };
  const stageOf = (progress) => {
    const value = `${progress.stage || ""} ${progress.function_name || ""}`.toLowerCase().replace(/[_/-]/g, " ");
    if (/\b(final|publish|commit|validate|complete|combine|config|threshold|merge|group|aggregate|dashboard)\b/.test(value)) return "final";
    if (/\b(p&l|pnl|pl|profit|calculate)\b/.test(value)) return "pl";
    if (/\b(market|official|open|live|current|price)\b/.test(value)) return "market";
    if (/\b(readiness|ready|status|starting|start)\b/.test(value)) return "readiness";
    if (/\b(risk|snapshot|connector|position)\b/.test(value)) return "risk";
    return null;
  };
  const modeOf = (trigger) => ({
    "reload-risk-button": "reload", "refresh-portfolios-button": "portfolios",
    "commo-market-toggle": "commo", "risk-checker-toggle": "checker",
    "force-risk-apply-button": "dates", "clear-cache-button": "reset",
    "auto-refresh-interval": "automatic",
  }[trigger] || "pl");
  const endpoint = (kind) => {
    const configured = node("backend-endpoints")?.dataset[kind === "start" ? "startUrl" : "progressUrl"];
    if (configured) return new URL(configured, window.location.origin).toString();
    try {
      const config = JSON.parse(node("_dash-config")?.textContent || "{}");
      const prefix = String(config.requests_pathname_prefix || "/").replace(/\/+$/, "");
      return new URL(`${prefix}/${kind}`, window.location.origin).toString();
    } catch (_) { return new URL(kind, document.baseURI).toString(); }
  };
  app.pendingCommittedDataRevision = Number(app.pendingCommittedDataRevision || 0);
  app.observedPublishedDataRevision = Number(app.observedPublishedDataRevision || 0);
  app.canPublishDataRevision = () => Boolean(
    (node("cube-page-container") && node("risk-type-tabs")) || node("pnl-page-container")
    || node("data-page") || node("stock-page") || node("static-data-page")
  );
  const knownRevision = () => Math.max(0,
    revision(app.pendingCommittedDataRevision) || 0,
    revision(app.observedPublishedDataRevision) || 0,
    revision(node("refresh-commit-revision")?.textContent) || 0);
  const offerRevision = (value) => {
    const candidate = revision(value);
    if (candidate !== null) app.pendingCommittedDataRevision = Math.max(app.pendingCommittedDataRevision, candidate);
  };
  const newState = (mode, request = null) => ({
    mode, request, startedAt: Date.now(), active: true, phase: "requested",
    baseline: knownRevision(), bootId: lastProgress?.server_boot_id || null,
    attemptId: null, startupAttemptId: null, progress: null,
    result: null, targetRevision: null, layoutReady: mode !== "bootstrap",
    viewsReady: false, owners: null, pageKey, stages: {}, error: "", message: "",
    finishedAt: null, hideAt: null, handoffAt: null, callbackPending: Boolean(request),
    startError: "",
  });
  const terminal = (phase, message, error = "") => {
    if (!state) return;
    state.phase = phase;
    state.message = message;
    state.error = error;
    state.active = false;
    state.callbackPending = false;
    state.finishedAt = Date.now();
    // Match the original hero: brief success, longer warm errors, persistent
    // startup/reconnect errors. A timer for an old action cannot hide a new one.
    const keepVisible = phase === "interrupted" || phase === "unconfirmed"
      || (phase === "failed" && state.mode === "bootstrap");
    state.hideAt = keepVisible ? null : state.finishedAt + (["complete", "no_work"].includes(phase) ? 300 : 5000);
    if (state.hideAt !== null) {
      const completed = state;
      setTimeout(() => { if (state === completed && !state.active) queuePaint(); }, state.hideAt - state.finishedAt);
    }
    for (const stage of STAGES) {
      if (state.stages[stage] === "active") state.stages[stage] = phase === "complete" ? "complete" : "observed";
    }
    queuePaint();
  };
  const visibleTitle = () => {
    if (!state) return "Refresh";
    if (state.active && state.startError) return "Startup request unconfirmed — use Retry";
    if (state.active && transportError) return "Progress connection interrupted — retrying";
    const operation = {
      bootstrap: "Loading Cube data", reset: "Resetting cache", reload: "Reloading all risk",
      portfolios: "Refreshing portfolios", commo: "Updating Commo market",
      checker: "Updating RiskChecker", dates: "Applying date settings",
      automatic: "Automatic refresh", pl: "Refreshing P&L",
    }[state.mode] || "Refreshing Cube data";
    const titles = {
      requested: operation, data: operation,
      finishing: operation, views: operation,
      complete: "Refresh complete", failed: "Refresh failed", rejected: "Refresh not applied",
      busy: "Another refresh is running — this action did not start", no_work: "No refresh was needed",
      interrupted: "Server process changed — reload to reconnect", unconfirmed: "Refresh outcome unconfirmed",
    };
    return titles[state.phase] || operation;
  };
  const paint = () => {
    paintQueued = false;
    if (!state || stopped) return;
    const panel = node("refresh-progress");
    if (!panel) return;
    panel.hidden = !state.active && state.hideAt !== null && Date.now() >= state.hideAt;
    panel.classList.toggle("is-running", state.active);
    panel.classList.toggle("is-complete", state.phase === "complete" || state.phase === "no_work");
    panel.classList.toggle("is-error", Boolean(state.error) || state.phase === "interrupted");
    panel.dataset.progressSource = state.progress ? "backend" : "pending";
    panel.dataset.refreshPhase = state.phase;
    panel.dataset.refreshRequest = state.request?.id || "";
    panel.dataset.refreshAttempt = state.attemptId || "";
    text("refresh-progress-title", visibleTitle());
    const elapsedEnd = state.finishedAt || Date.now();
    text("refresh-progress-elapsed", `${Math.max(0, Math.floor((elapsedEnd - state.startedAt) / 1000))}s elapsed`);
    const progress = state.progress;
    const rendering = state.phase === "views";
    const callFinished = rendering || !state.active;
    const fn = !state.active ? "" : rendering ? "Updating tables and charts" : progress?.function_name || (state.mode === "bootstrap" ? "Starting server data load" : "Waiting for refresh callback");
    text("refresh-progress-function", state.active && (state.startError || transportError) ? state.startError || transportError : fn);
    text("refresh-progress-source", callFinished ? "" : [progress?.source_type, progress?.underlying].filter(Boolean).join(" · "));
    const callLabel = panel.querySelector(".refresh-function-label");
    if (callLabel) callLabel.hidden = !state.active;
    let detail = state.message || progress?.message || progress?.product_label || "Preparing refresh";
    if (state.phase === "views") {
      detail = "Updating tables and charts";
    }
    if (state.phase === "complete") detail = "Validated snapshot is live";
    if (state.error) detail = state.error;
    if (state.active && transportError && lastSuccessAt) detail += ` · Last confirmed response ${Math.floor((Date.now() - lastSuccessAt) / 1000)}s ago`;
    text("refresh-progress-product", detail);
    const total = callFinished ? 0 : Number(progress?.product_total || 0);
    const current = Number(progress?.product_index || 0);
    text("refresh-progress-count", total > 0 ? `${Math.max(0, current)} of ${total}` : "");
    text("refresh-progress-hold", !callFinished && Number(progress?.hold_seconds || 0) > 0 ? `${progress.hold_seconds}s product hold` : "");
    const track = node("refresh-progress-bar-track");
    const bar = node("refresh-progress-bar");
    if (track) track.hidden = !(state.active && total > 0);
    if (bar) bar.style.width = `${total > 0 ? Math.max(0, Math.min(100, current / total * 100)) : 0}%`;
    for (const stage of STAGES) {
      const row = node(`refresh-stage-${stage}`);
      if (!row) continue;
      const outcome = state.stages[stage] || "";
      for (const name of ["active", "complete", "skipped", "error"]) row.classList.toggle(`is-${name}`, outcome === name);
      row.style.removeProperty("--stage-progress");
      const duration = row.querySelector(".refresh-stage-duration");
      const caption = outcome === "active" ? "Running" : outcome === "complete" ? "Complete" : outcome === "error" ? "Failed" : outcome === "skipped" ? "Not called" : state.active && !rendering ? "queued" : "";
      if (duration && duration.textContent !== caption) duration.textContent = caption;
    }
    // The original hero already contains its cube. Do not add a second overlay.
    app.setGlobalLoaderVisible?.(false);
  };
  function queuePaint() {
    if (paintQueued || stopped) return;
    paintQueued = true;
    window.requestAnimationFrame(paint);
  }
  const pendingOwners = () => {
    if (!state?.owners) return [];
    return state.owners.filter((owner) => {
      const ack = viewAcks.get(owner);
      return !ack || ack.revision !== state.targetRevision || !["rendered", "failed"].includes(ack.status)
        || ack.pageKey !== state.pageKey || (ack.request_id || null) !== (state.request?.id || null);
    });
  };
  const advance = () => {
    if (!state?.active) { queuePaint(); return; }
    if (!state.result || state.callbackPending) { queuePaint(); return; }
    if (state.result.outcome !== "complete") {
      terminal(state.result.outcome, state.result.message || "The requested action did not publish a new snapshot", state.result.error || "");
      return;
    }
    if (!state.layoutReady) { state.phase = "finishing"; queuePaint(); return; }
    state.phase = "views";
    // The callback has finished. Stop showing its last sampled connector as
    // still running; final remains active until the visible outputs are ready.
    for (const stage of STAGES) if (state.stages[stage] === "active") state.stages[stage] = "complete";
    state.stages.final = "active";
    if (state.owners === null && preparedViews.has(state.targetRevision)) {
      const plan = preparedViews.get(state.targetRevision);
      if (plan.pageKey === state.pageKey) state.owners = [...plan.owners];
    }
    if (state.owners === null) { queuePaint(); return; }
    const viewErrors = [];
    for (const owner of state.owners) {
      const ack = viewAcks.get(owner);
      if (ack?.revision === state.targetRevision && ack.pageKey === state.pageKey
          && (ack.request_id || null) === (state.request?.id || null) && ack.status === "failed") {
        viewErrors.push(`${owner}: ${ack.message || "render failed"}`);
      }
    }
    if (viewErrors.length) state.error = viewErrors.join(" · ");
    if (pendingOwners().length) { queuePaint(); return; }
    if (viewErrors.length) { terminal("failed", "Server data committed, but a visible result failed", state.error); return; }
    state.viewsReady = true;
    terminal("complete", state.presentationSuperseded
      ? `This action committed revision ${state.result.revision}; visible updates triggered by newer revision ${state.targetRevision} have finished`
      : `Visible updates triggered by revision ${state.targetRevision} have finished`);
  };
  const setTarget = (value) => {
    const target = revision(value);
    if (!state || target === null) return false;
    state.targetRevision = target;
    offerRevision(target); // Never wait for view acknowledgements before offering publication.
    const plan = preparedViews.get(target);
    state.owners = plan?.pageKey === state.pageKey ? [...plan.owners] : null;
    return true;
  };
  const observeProgress = (progress) => {
    lastProgress = progress;
    if (!progress.running) offerRevision(progress.revision);
    const firstReady = !initialProgressSeen && !progress.running && progress.startup_phase === "succeeded" && revision(progress.revision) > 0;
    initialProgressSeen = true;
    if (!state && (firstReady || node("refresh-progress")?.dataset.initialLoad === "true")) {
      // Only startup or a local request owns this browser's hero. A different
      // browser's warm refresh cannot deliver a local callback receipt.
      state = newState("bootstrap");
    }
    if (!state?.active) return;
    if (state.bootId && progress.server_boot_id && state.bootId !== progress.server_boot_id) {
      if (state.mode === "bootstrap") {
        state = newState("bootstrap");
        state.bootId = progress.server_boot_id;
        app.pendingCommittedDataRevision = 0;
        app.observedPublishedDataRevision = 0;
      } else {
        terminal("interrupted", "The previous process cannot confirm this refresh", "Reload the page to reconnect; the action was not automatically retried.");
        return;
      }
    }
    state.bootId ||= progress.server_boot_id || null;
    if (state.mode === "bootstrap") {
      if (state.retryBaseline && (!progress.startup_attempt_id || progress.startup_attempt_id === state.retryBaseline)) {
        state.message = state.startError
          ? "The startup request could not be confirmed. Use Retry; progress checks continue."
          : "Retry requested — waiting for a new startup attempt";
        queuePaint();
        return;
      }
      state.retryBaseline = null;
      if (progress.startup_attempt_id && ["running", "succeeded", "stalled"].includes(progress.startup_phase)) state.startError = "";
      if (progress.startup_attempt_id) state.startupAttemptId ||= progress.startup_attempt_id;
      if (state.startupAttemptId && progress.startup_attempt_id !== state.startupAttemptId) return;
      // Coordinator failure after its worker exits is authoritative even if
      // a final exception left the inner financial progress marker running.
      if (progress.startup_phase === "failed" && progress.startup_worker_alive === false) {
        state.progress = progress;
        terminal("failed", "Initial data load failed", progress.error || progress.message || "Use Retry after checking the error");
        return;
      }
    }
    if (state.result && state.mode !== "bootstrap") { advance(); return; }
    if (progress.running) {
      // Live painting is independent of callback and terminal confirmation.
      if (!state.result) {
        if (state.attemptId && state.attemptId !== progress.attempt_id) state.stages = {};
        state.attemptId = progress.attempt_id || null;
        state.progress = progress;
        state.phase = "data";
        const stage = stageOf(progress);
        if (stage) {
          for (const previous of STAGES) if (state.stages[previous] === "active" && previous !== stage) state.stages[previous] = "complete";
          state.stages[stage] = progress.error ? "error" : "active";
        }
      }
      queuePaint();
      return;
    }
    if (state.attemptId && progress.attempt_id !== state.attemptId) return;
    if (state.mode === "bootstrap") {
      const phase = progress.startup_phase;
      state.progress = progress;
      state.phase = "finishing";
      state.message = progress.startup_worker_alive
        ? "Finishing the startup worker before opening the validated dashboard"
        : "Waiting for the validated dashboard to mount";
      if (phase === "failed" && !progress.startup_worker_alive) {
        terminal("failed", "Initial data load failed", progress.error || progress.message || "Use Retry after checking the error");
        return;
      }
      if (phase === "succeeded" && progress.startup_worker_alive === false && revision(progress.revision) > 0) {
        state.progress = progress;
        state.result = {outcome: "complete", revision: progress.revision};
        state.callbackPending = false;
        state.handoffAt ||= Date.now();
        setTarget(progress.revision);
        if (lastStartupLayout?.server_boot_id === state.bootId
            && lastStartupLayout?.startup_attempt_id === state.startupAttemptId
            && revision(lastStartupLayout?.revision) === state.targetRevision
            && lastStartupLayout.status === "rendered") state.layoutReady = true;
        advance();
      } else if (["idle", ""].includes(phase)) void requestStart();
    } else if (state.request) {
      if (!state.attemptId) return; // An old idle sample is not evidence that the new request started.
      // A sampled backend finish is only an intermediate milestone.
      state.progress = progress;
      if (!state.result) state.phase = "finishing";
      advance();
    }
  };
  async function requestStart(force = false) {
    if (startPromise || (!force && Date.now() < nextStart)) return startPromise;
    nextStart = Date.now() + 5000;
    if (state?.mode === "bootstrap") state.startError = "";
    startPromise = (async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
      try {
        const response = await fetch(endpoint("start"), {method: "POST", cache: "no-store", credentials: "same-origin", headers: {Accept: "application/json"}, signal: controller.signal});
        if (!response.ok) throw new Error(`Start returned ${response.status}`);
        await response.json();
      } catch (error) {
        transportError = String(error.message || error);
        if (state?.mode === "bootstrap") state.startError = transportError;
      } finally { clearTimeout(timeout); startPromise = null; queuePaint(); }
    })();
    return startPromise;
  }
  async function poll(force = false) {
    if (stopped || pollPromise || (!force && Date.now() < nextPoll)) return pollPromise;
    nextPoll = Date.now() + POLL_MS;
    pollPromise = (async () => {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
      try {
        const response = await fetch(endpoint("progress"), {cache: "no-store", credentials: "same-origin", headers: {Accept: "application/json"}, signal: controller.signal});
        if (!response.ok || !(response.headers.get("content-type") || "").includes("application/json")) throw new Error(`Progress returned ${response.status} without a valid JSON response`);
        const progress = await response.json();
        if (!progress || typeof progress !== "object") throw new Error("Progress response was not an object");
        progress.running = progress.running === true || progress.running === 1 || progress.running === "true";
        failures = 0; transportError = ""; lastSuccessAt = Date.now();
        observeProgress(progress);
      } catch (error) {
        failures += 1;
        transportError = error.name === "AbortError" ? "Progress request timed out; work status is not confirmed" : String(error.message || error);
        nextPoll = Date.now() + Math.min(30000, POLL_MS * (2 ** Math.min(failures, 5)));
        queuePaint();
      } finally { clearTimeout(timeout); pollPromise = null; }
    })();
    return pollPromise;
  }
  app.beginRefreshRequest = (request) => {
    if (!request?.id || !request.trigger) return false;
    if (state?.request?.id === request.id) return false;
    // Suppress the dispatch itself, not just its hero, while our prior writer request is unanswered.
    if (state?.active && state.callbackPending && state.request) {
      const busyNode = node("refresh-status") || node("bootstrap-refresh-status");
      const freshIdle = lastProgress?.running === false && !transportError
        && Date.now() - lastSuccessAt < POLL_MS * 3 && busyNode
        && !busyNode.classList.contains("is-refreshing");
      if (request.trigger === "auto-refresh-interval" || !freshIdle) {
        state.message = "The previous refresh request is still awaiting its result";
        queuePaint();
        return false;
      }
      // A deliberate new action after reconnect is allowed; this does not
      // convert the unanswered preceding request into a success or retry it automatically.
    }
    state = newState(request.mode || modeOf(request.trigger), {...request});
    if (state.mode === "portfolios") for (const stage of ["readiness", "risk", "market", "pl"]) state.stages[stage] = "skipped";
    queuePaint(); void poll(true);
    return true;
  };
  app.receiveRefreshResult = (result) => {
    if (!state?.request || result?.request_id !== state.request.id) return false;
    if (state.bootId && result.server_boot_id && state.bootId !== result.server_boot_id) {
      terminal("interrupted", "The refresh result came from a replacement process", "Reload to reconnect.");
      return false;
    }
    state.bootId ||= result.server_boot_id || null;
    state.callbackPending = false;
    state.result = {...result};
    state.result.outcome = ({committed: "complete", unchanged: "no_work"})[result.outcome] || result.outcome;
    if (!["complete", "failed", "rejected", "busy", "no_work"].includes(state.result.outcome)) {
      state.phase = "unconfirmed";
      state.message = "The refresh callback returned an unrecognised outcome";
      queuePaint();
      return false;
    }
    if (result.attempt_id) state.attemptId = result.attempt_id;
    if (state.result.outcome === "complete" && (!(revision(result.revision) > 0) || !setTarget(result.revision))) {
      state.phase = "unconfirmed"; state.message = "The result did not identify its committed revision"; queuePaint(); return false;
    }
    state.error = String(result.error || "");
    advance();
    return true;
  };
  app.prepareRefreshViews = (value, owners) => {
    const target = revision(value);
    if (target === null || !Array.isArray(owners)) return false;
    const unique = [...new Set(owners.map(String))];
    preparedViews.set(target, {owners: unique, pageKey});
    while (preparedViews.size > 4) preparedViews.delete(preparedViews.keys().next().value);
    if (state?.active && state.result?.outcome === "complete" && state.phase === "views"
        && state.targetRevision !== null && target > state.targetRevision && state.pageKey === pageKey) {
      // The request receipt remains immutable. Only its visible presentation
      // target is replaced when a newer publication supersedes pending draws.
      state.targetRevision = target;
      state.presentationSuperseded = true;
      state.error = "";
    }
    if (state?.active && state.targetRevision === target) { state.owners = unique; advance(); }
    return true;
  };
  app.receiveRefreshViewAck = (ack) => {
    if (!ack?.owner || !["rendered", "failed"].includes(ack.status)) return false;
    const target = revision(ack.revision);
    if (target === null) return false;
    if (state?.active && (ack.request_id || null) !== (state.request?.id || null)) return false;
    const previous = viewAcks.get(String(ack.owner));
    if (previous && previous.pageKey === pageKey && previous.revision > target) return false;
    viewAcks.set(String(ack.owner), {...ack, revision: target, pageKey: ack.pageKey || pageKey});
    advance();
    return true;
  };
  app.receiveStartupLayout = (ack) => {
    if (ack) lastStartupLayout = {...ack};
    if (!state || state.mode !== "bootstrap" || !ack) return false;
    if (ack.server_boot_id !== state.bootId || ack.startup_attempt_id !== state.startupAttemptId) return false;
    if (ack.status === "failed") { terminal("failed", "Initial dashboard rendering failed", String(ack.message || "Render failed")); return true; }
    if (ack.status !== "rendered" || revision(ack.revision) !== state.targetRevision) return false;
    state.layoutReady = true; advance(); return true;
  };
  app.noteStartupLayoutReady = () => {
    if (!app.canPublishDataRevision() || !lastProgress?.startup_attempt_id || !lastProgress.server_boot_id) return false;
    return app.receiveStartupLayout({
      startup_attempt_id: lastProgress.startup_attempt_id,
      server_boot_id: lastProgress.server_boot_id,
      revision: revision(lastProgress.revision), status: "rendered",
    });
  };
  app.refreshPageChanged = (nextPage, owners) => {
    if (!Array.isArray(owners)) return false;
    if (pageKey === String(nextPage)) return true;
    pageKey = String(nextPage);
    viewAcks.clear(); preparedViews.clear();
    if (state?.active) {
      state.pageKey = pageKey;
      state.owners = null;
      if (state.targetRevision !== null) app.prepareRefreshViews(state.targetRevision, owners);
    }
    queuePaint(); return true;
  };
  app.startRefreshProgress = (mode) => {
    // Native warm actions are owned by beginRefreshRequest's atomic dispatcher.
    if (mode !== "bootstrap") { queuePaint(); return; }
    if (!state?.active || state.mode !== "bootstrap") {
      const retryBaseline = state?.mode === "bootstrap" && state.phase === "failed"
        ? state.startupAttemptId || lastProgress?.startup_attempt_id || null : null;
      state = newState("bootstrap");
      state.retryBaseline = retryBaseline;
    }
    queuePaint(); void requestStart(true); void poll(true);
  };
  app.syncRefreshLifecycleNodes = () => {
    for (const element of document.querySelectorAll("[data-refresh-view-ack]")) {
      try { app.receiveRefreshViewAck(JSON.parse(element.dataset.refreshViewAck)); } catch (_) { /* Partial DOM writes wait for the next observation. */ }
    }
    offerRevision(node("refresh-commit-revision")?.textContent);
    queuePaint();
  };
  app.refreshDiagnostics = () => state ? {
    active: state.active, phase: state.phase, request_id: state.request?.id || null,
    attempt_id: state.attemptId, server_boot_id: state.bootId, startup_attempt_id: state.startupAttemptId,
    target_revision: state.targetRevision,
    callback_pending: state.callbackPending, layout_ready: state.layoutReady,
    participants_established: state.owners !== null, pending_views: pendingOwners(),
    last_progress_age_ms: lastSuccessAt ? Date.now() - lastSuccessAt : null,
  } : null;
  const clock = setInterval(() => {
    if (stopped) return;
    if (!state && node("refresh-progress")?.dataset.initialLoad === "true") app.startRefreshProgress("bootstrap");
    app.syncRefreshLifecycleNodes(); void poll();
  }, POLL_MS);
  const installObserver = () => {
    if (!document.body || observer || stopped) return;
    observer = new MutationObserver((changes) => {
      if (changes.some((change) => change.type === "childList" || change.attributeName === "data-refresh-view-ack")) app.syncRefreshLifecycleNodes();
    });
    observer.observe(document.body, {subtree: true, childList: true, attributes: true, attributeFilter: ["data-refresh-view-ack"]});
    app.syncRefreshLifecycleNodes();
  };
  app.stopRefreshLifecycle = () => {
    stopped = true; clearInterval(clock); observer?.disconnect(); observer = null;
    app.setGlobalLoaderVisible?.(false);
  };
  if (document.body) installObserver();
  else document.addEventListener("DOMContentLoaded", installObserver, {once: true});
})();
