# Hero: live progress, reliable completion, and usable pages

This is the complete replacement for the earlier Hero lifecycle instructions. Apply the latest Quick Risk/Quick Market function replacements from [quick risk fix.md](quick%20risk%20fix.md) first, then this guide. Keep the JTD fixes and the existing Data editor. [refreshinteract.md](refreshinteract.md) contains the separate interaction/dependency checks; it does not install another Hero owner.

**Later replacements win. Do not reapply the old Hero sections 1.8, 1.9 or 5D, the old Commo-only Hero patch, or an older revision publisher after this guide.** They address the same code and would restore conflicting lifecycle logic.

The problem was that progress, committing data, and displaying the completed result had become mixed together. A live progress response can legitimately have no finish timestamp. A committed revision can exist while the refresh callback is still preparing its return. A visible page can still be rendering after the callback returns. Checking only one of those events can either hide the Hero early or make it wait on work that cannot start.

The replacement follows three events: show live server progress; receive the result of this specific refresh request; then wait for the currently visible participating results to mount. Publication of a committed revision runs independently so those results can actually render. Cold start additionally waits for the startup worker to finish. Failed, rejected, busy and no-work responses have explicit outcomes instead of an indefinite spinner.

The Hero observes existing work. It does not add a job queue, copy financial frames into browser stores, or change connector calculations. Ordinary reading and navigation remain available while a refresh runs. Controls that would launch conflicting writes keep their existing disabled/single-writer protection.

## 1. Back up the touched files and remove duplicate lifecycle owners

Make a normal local backup of these existing files before editing:

- `assets/s12_refresh.js` and `assets/s13_risk.js`
- `cube/ui/s04_components.py`
- `cube/app/s05_progress.py`
- `cube/pages/risk/s15_refresh.py`
- `cube/pages/risk/s07_explorer.py`
- `cube/pages/risk/s14_workspacecallbacks.py`
- `cube/pages/pnl/s08_aggregate.py`
- `cube/pages/pnl/s05_sendcallbacks.py`

You will add `assets/refresh_views.js` and `cube/ui/s08_refresh_views.py`, or replace their contents if they already exist. Keep unrelated files and the current connector implementations.

Keep one `assets/s12_refresh.js` lifecycle owner. If you previously created a second asset solely to define the same `startRefreshProgress`, `beginRefreshRequest`, `receiveRefreshResult`, or revision-publication functions, remove that obsolete duplicate after identifying its definitions. Do not delete the shared utility assets: the replacement still uses their existing loader helpers.

In `s15_refresh.py`, remove the previous clientside revision publisher whose output is `data-revision-store.data`; section 6 supplies its replacement. Remove previous request/result bridge registrations only if they target `refresh-action-request.data` or `refresh-action-result-ack.children`; section 5 supplies their single replacements. Keep the ordinary Python callback outputs and their existing `allow_duplicate=True` settings.

## 2. Install the complete browser lifecycle

Replace the entire contents of `assets/s12_refresh.js` with this block. It includes the complete live-progress parsing, completion rules, stage rendering, bootstrap behavior, retry handling, and diagnostic functions; no classifier or placeholder function is left for you to implement.

```javascript
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
    attemptId: null, startupAttemptId: null, progress: null, observed: false,
    result: null, targetRevision: null, layoutReady: mode !== "bootstrap",
    viewsReady: false, owners: null, pageKey, stages: {}, error: "", message: "",
    finishedAt: null, handoffAt: null, callbackPending: Boolean(request),
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
    for (const stage of STAGES) {
      if (state.stages[stage] === "active") state.stages[stage] = phase === "complete" ? "complete" : "observed";
    }
    queuePaint();
  };
  const visibleTitle = () => {
    if (!state) return "Refresh";
    if (state.active && state.startError) return "Startup request unconfirmed — use Retry";
    if (state.active && transportError) return "Progress connection interrupted — retrying";
    const titles = {
      requested: "Refresh requested — waiting for server", data: "Refreshing data",
      finishing: "Finishing refresh", views: "Updating displayed tables",
      complete: "Refresh complete", failed: "Refresh failed", rejected: "Refresh not applied",
      busy: "Another refresh is running — this action did not start", no_work: "No refresh was needed",
      interrupted: "Server process changed — reload to reconnect", unconfirmed: "Refresh outcome unconfirmed",
    };
    const title = titles[state.phase] || "Refresh in progress";
    return state.targetRevision !== null && ["views", "complete"].includes(state.phase)
      ? `${title} — ${state.presentationSuperseded ? "display revision" : "revision"} ${state.targetRevision}` : title;
  };
  const paint = () => {
    paintQueued = false;
    if (!state || stopped) return;
    const panel = node("refresh-progress");
    if (!panel) return;
    panel.hidden = false;
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
    const fn = progress?.function_name || (state.mode === "bootstrap" ? "Starting server data load" : "Waiting for refresh callback");
    text("refresh-progress-function", state.active && (state.startError || transportError) ? state.startError || transportError : fn);
    text("refresh-progress-source", [progress?.source_type, progress?.underlying].filter(Boolean).join(" · "));
    let detail = state.message || progress?.message || progress?.product_label || "Waiting for confirmed work";
    if (state.phase === "views") {
      detail = `Waiting for ${pendingOwners().join(", ") || "the page render plan"}`;
      if (state.presentationSuperseded) detail = `This action committed revision ${state.result.revision}; newer revision ${state.targetRevision} superseded the displayed results. ${detail}`;
    }
    if (state.error) detail = state.error;
    if (state.active && transportError && lastSuccessAt) detail += ` · Last confirmed response ${Math.floor((Date.now() - lastSuccessAt) / 1000)}s ago`;
    if (state.observed && state.active && state.phase === "data") detail = `Observed server work · ${detail}`;
    text("refresh-progress-product", detail);
    const total = Number(progress?.product_total || 0);
    const current = Number(progress?.product_index || 0);
    text("refresh-progress-count", total > 0 ? `${Math.max(0, current)} of ${total}` : "");
    text("refresh-progress-hold", Number(progress?.hold_seconds || 0) > 0 ? `${progress.hold_seconds}s product hold` : "");
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
      const caption = outcome === "active" ? "Running" : outcome === "complete" ? "Observed" : outcome === "observed" ? "Last observed" : outcome === "error" ? "Failed" : outcome === "skipped" ? "Not called" : "Not observed";
      if (duration && duration.textContent !== caption) duration.textContent = caption;
    }
    // This is the existing small noninteractive loader, never a page lock.
    app.setGlobalLoaderVisible?.(state.active);
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
    const firstReady = !initialProgressSeen && progress.startup_phase === "succeeded" && revision(progress.revision) > 0;
    initialProgressSeen = true;
    if (!state && (progress.running || firstReady || node("refresh-progress")?.dataset.initialLoad === "true")) {
      const bootstrap = firstReady || node("refresh-progress")?.dataset.initialLoad === "true";
      state = newState(bootstrap ? "bootstrap" : "observed");
      state.observed = state.mode !== "bootstrap";
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
        state.observed = Boolean(state.request && !state.result);
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
    } else {
      state.progress = progress;
      state.phase = "unconfirmed";
      state.message = "Observed server work ended; no local action receipt is available";
      queuePaint();
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
```

The progress panel remains visible while its request or required visible results are pending. A temporarily unreachable progress endpoint is reported as a connection problem; it is not treated as successful completion. This cannot invent progress inside a connector that publishes no intermediate updates: in that case the last known step remains visible until the connector returns.

## 3. Add the shared browser and Python view helpers

Create or replace `assets/refresh_views.js` with this complete file. It publishes new revisions without waiting for the render receipts that publication will trigger. It also detects which supported result owners are currently visible, waits for their returned content to mount, and waits for Plotly graphs to be ready before accepting their receipt.

```javascript
/* The publisher never waits for renderers before publishing their revision. */
(() => {
    "use strict";
    const queued = new Map();
    let mountedPage = null;
    const node = (id) => document.getElementById(id);
    const open = (id) => Boolean(node(id)?.open);
    const editorOpen = (section) => Boolean(node(`pl-${section}-summary`)?.closest("details")?.open);
    const visibleOwners = (workspace) => {
        if (node("risk-type-tabs")) {
            const owners = ["risk-explorer"];
            if (open("ag-pl-details")) {
                if (workspace === "aggregate-pl") owners.push("aggregate-pl");
                if (workspace === "top-promotions") owners.push("top-promotions");
                if (workspace === "quick-risk") owners.push("quick-risk-options", "quick-risk-table", "quick-risk-chart");
                if (workspace === "quick-market") owners.push("quick-market-options", "quick-market");
            }
            if (open("unmapped-books-details")) owners.push("unmapped-books");
            return owners;
        }
        if (node("pnl-page-container")) {
            const owners = ["pnl-summary"];
            for (const section of ["sog", "portfolio"]) if (editorOpen(section)) owners.push(`pnl-editor-${section}`);
            return owners;
        }
        return [];
    };
    const pageMounted = () => {
        // During routing, the old page can still exist after pathname changes.
        // Wait for the requested root; a temporary DOM gap retires nothing.
        const tail = window.location.pathname.replace(/\/+$/, "").split("/").pop();
        const expected = {pnl: "pnl-page-container", data: "data-page", stock: "stock-page", "static-data": "static-data-page"}[tail];
        return expected ? Boolean(node(expected)) : Boolean(node("risk-type-tabs"));
    };
    const graphReady = (root) => {
        if (root.matches?.(".dash-graph--pending") || root.querySelector(".dash-graph--pending")) return false;
        const graphs = [...root.querySelectorAll(".dash-graph")];
        if (root.matches?.(".dash-graph")) graphs.push(root);
        return graphs.every(graph => Boolean(graph.querySelector(".js-plotly-plot")?._fullLayout));
    };
    const queueAck = (ack, pageKey) => {
        if (!ack?.owner) return;
        const signature = JSON.stringify(ack);
        const previous = queued.get(ack.owner);
        if (previous?.signature === signature && previous.pageKey === pageKey) return;
        const pending = {signature, pageKey, cancelled: false};
        if (previous) previous.cancelled = true;
        queued.set(ack.owner, pending);
        // Two frames let React mount the callback outputs and start Plotly.react.
        const check = () => {
            if (pending.cancelled || mountedPage !== pageKey) return;
            const roots = (ack.mounts || []).map(id => document.querySelector(`[data-refresh-render="${id}"]`));
            if (roots.some(root => !root || !graphReady(root))) {
                setTimeout(check, 100);
                return;
            }
            window.__cubeV5Assets?.receiveRefreshViewAck({...ack, pageKey});
        };
        requestAnimationFrame(() => requestAnimationFrame(check));
    };
    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.cubeRefresh = {
        publish(_tick, committed, published, workspace, ...acks) {
            const assets = window.__cubeV5Assets;
            const noUpdate = window.dash_clientside.no_update;
            if (!assets || !pageMounted()) return noUpdate;
            const owners = visibleOwners(workspace);
            // A real workspace/open-panel change explicitly supersedes the
            // former presentation targets; it never cancels backend work.
            const pageKey = JSON.stringify([window.location.pathname, owners]);
            if (mountedPage !== pageKey) {
                mountedPage = pageKey;
                for (const pending of queued.values()) pending.cancelled = true;
                queued.clear();
                assets.refreshPageChanged(pageKey, owners);
            }
            const current = Number(published || 0);
            assets.observedPublishedDataRevision = current;
            const revision = Math.max(Number(committed || 0), Number(assets.pendingCommittedDataRevision || 0), current);
            if (!Number.isSafeInteger(revision) || revision <= 0) return noUpdate;
            assets.prepareRefreshViews(revision, owners);
            const requestId = assets.refreshDiagnostics?.()?.request_id || null;
            for (const ack of acks) {
                if (ack && owners.includes(ack.owner)
                    && Number(ack.revision) === revision
                    && (ack.request_id || null) === requestId) queueAck(ack, pageKey);
            }
            assets.noteStartupLayoutReady();
            return revision > current ? revision : noUpdate;
        },
    };
})();
```

Create or replace `cube/ui/s08_refresh_views.py` with this complete file. The decorator appends a small completion receipt to the existing callback return. Existing calculations and result objects remain inside the original function body.

```python
"""Small completion receipts returned with the existing visible callback results."""

from functools import wraps
import inspect
import logging
import uuid
from collections.abc import Mapping

from dash import html, no_update
from dash.exceptions import PreventUpdate

LOGGER = logging.getLogger(__name__)


def _error_message(value):
    if isinstance(value, (list, tuple)):
        return next((message for item in value if (message := _error_message(item))), "")
    if not hasattr(value, "to_plotly_json"):
        return ""
    props = value.to_plotly_json().get("props", {})
    if props.get("role") == "alert" or "has-error" in str(props.get("className", "")).split():
        return str(props.get("children") or "The displayed result could not be loaded")[:1000]
    return _error_message(props.get("children"))


def refresh_view(owner, *, revision_arg, outputs, content, stamp=()):
    """Append one receipt; the final callback State is the browser request.

    This observes existing work. It neither starts work nor stores financial rows.
    Keep this decorator directly below @app.callback, which owns the extra Output.
    """
    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapped(*args, **kwargs):
            request = args[-1]
            original_args = args[:-1]
            values = signature.bind(*original_args, **kwargs).arguments
            revision_value = values.get(revision_arg)
            if isinstance(revision_value, Mapping):
                revision_value = revision_value.get("revision")
            try:
                revision = int(revision_value or 0)
            except (TypeError, ValueError):
                revision = 0
            receipt = {
                "owner": owner, "revision": revision,
                "request_id": request.get("id") if isinstance(request, Mapping) else None,
                "status": "rendered", "message": "",
            }
            try:
                result = function(*original_args, **kwargs)
            except PreventUpdate:
                raise
            except Exception as exc:
                LOGGER.exception("Refresh view %s failed", owner)
                receipt.update(status="failed", message=str(exc)[:1000])
                return (*([no_update] * outputs), receipt)
            result = tuple(result) if outputs > 1 else (result,)
            if len(result) != outputs:
                raise ValueError(f"{owner}: expected {outputs} outputs, got {len(result)}")
            # Hidden/inactive callbacks and refresh revision zero acknowledge nothing.
            if revision <= 0 or all(result[index] is no_update for index in content):
                return (*result, no_update)
            message = _error_message([result[index] for index in content])
            if message:
                receipt.update(status="failed", message=message)
            result = list(result)
            receipt["mounts"] = []
            for index in stamp:
                if result[index] is no_update:
                    continue
                render_id = f"refresh-render-{uuid.uuid4().hex}"
                result[index] = html.Div(result[index], **{"data-refresh-render": render_id})
                receipt["mounts"].append(render_id)
            return (*result, receipt)

        return wrapped
    return decorate
```

## 4. Add the shared stores and expose startup-worker liveness

Open `cube/ui/s04_components.py`. Inside `build_shared_refresh_shell`, find the existing `dcc.Store(id="refresh-busy-store", data=False)`. Keep it. Immediately after it, add the following block at the same list indentation. If any ID below already exists in this shared shell, update that existing entry instead of adding a duplicate. Each ID must occur once in the mounted shell.

```python
dcc.Store(id="refresh-action-request", data=None),
dcc.Store(id="refresh-action-result", data=None),
html.Span(id="refresh-action-result-ack", hidden=True),
dcc.Interval(id="committed-revision-poll", interval=1_000, n_intervals=0),
dcc.Store(id="refresh-view-risk-explorer", data=None),
dcc.Store(id="refresh-view-unmapped-books", data=None),
dcc.Store(id="refresh-view-aggregate-pl", data=None),
dcc.Store(id="refresh-view-top-promotions", data=None),
dcc.Store(id="refresh-view-quick-risk-options", data=None),
dcc.Store(id="refresh-view-quick-risk-table", data=None),
dcc.Store(id="refresh-view-quick-risk-chart", data=None),
dcc.Store(id="refresh-view-quick-market-options", data=None),
dcc.Store(id="refresh-view-quick-market", data=None),
dcc.Store(id="refresh-view-pnl-summary", data=None),
dcc.Store(id="refresh-view-pnl-editor-sog", data=None),
dcc.Store(id="refresh-view-pnl-editor-portfolio", data=None),
```

Keep the existing `data-revision-store`, `refresh-commit-revision`, startup intervals and Hero markup. The 12 view stores contain only small completion metadata; they contain no positions, markets or history rows. The two PL editor stores correspond to the existing SOG and Portfolio editor instances.

Open `cube/app/s05_progress.py`, find `progress_payload`, then its `payload.update(...)` block under `if startup_coordinator is not None:`. Add the worker-alive field immediately after the phase field. The start of that existing call must read:

```python
payload.update(
    startup_phase=startup.phase,
    startup_worker_alive=startup.worker_alive,
    startup_attempt=startup.attempt,
    startup_attempt_id=startup.attempt_id,
    server_boot_id=startup.server_boot_id,
    startup_elapsed_seconds=startup.elapsed_seconds,
    startup_timeout_seconds=startup_coordinator.timeout_seconds,
    startup_retryable=startup.retryable,
)
```

Keep the rest of `progress_payload` unchanged. This field matters because an initial revision may already be committed while the startup worker is still finishing its remaining code.

## 5. Make each warm action one identified request and one explicit result

Open `cube/pages/risk/s15_refresh.py`. Ensure its existing datetime import includes all three names below, and its typing import includes `Mapping`. Update those imports; do not add duplicate imports:

```python
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
```

Inside `register_refresh_callbacks`, in the existing `if refresh_manager is not None:` block, insert the following two clientside registrations immediately before the `@app.callback(...)` that belongs to `refresh_pipeline`. These statements have the same indentation as that decorator. There must be one owner for each bridge output.

The first callback creates the request identifier and starts the Hero before it returns that same request to the server callback. It avoids a race between a native click handler and a separate callback State. The second delivers the returned outcome to that exact request.

```python
app.clientside_callback(
    """
    function(autoTick, portfolios, pl, reload, apply, clear, commo, checker, autoEnabled) {
        const noUpdate = window.dash_clientside.no_update;
        const context = window.dash_clientside.callback_context;
        const changed = new Set((context.triggered || []).map(item => item.prop_id.split('.')[0]));
        const choices = [
            ['force-risk-apply-button', apply, 'dates'],
            ['clear-cache-button', clear, 'reset'],
            ['refresh-portfolios-button', portfolios, 'portfolios'],
            ['reload-risk-button', reload, 'reload'],
            ['refresh-pl-button', pl, 'pl'],
            ['commo-market-toggle', commo, 'commo'],
            ['risk-checker-toggle', checker, 'checker'],
            ['auto-refresh-interval', autoTick, 'automatic'],
        ];
        const selected = choices.find(([id, value]) => changed.has(id) && Number.isSafeInteger(value) && value > 0);
        if (!selected) return noUpdate;
        const [trigger, count, mode] = selected;
        if (mode === 'automatic' && autoEnabled === false) return noUpdate;
        const assets = window.__cubeV5Assets;
        if (typeof assets?.beginRefreshRequest !== 'function') {
            throw new Error('The refresh lifecycle asset is not ready. Reload the page before refreshing.');
        }
        const request = {
            id: window.crypto?.randomUUID?.() || `refresh-${Date.now()}-${Math.random().toString(36).slice(2)}`,
            trigger, count, mode, requested_at: Date.now(),
        };
        if (assets.beginRefreshRequest(request) === false) return noUpdate;
        return request;
    }
    """,
    Output("refresh-action-request", "data"),
    Input("auto-refresh-interval", "n_intervals"),
    Input("refresh-portfolios-button", "n_clicks"),
    Input("refresh-pl-button", "n_clicks"),
    Input("reload-risk-button", "n_clicks"),
    Input("force-risk-apply-button", "n_clicks", allow_optional=True),
    Input("clear-cache-button", "n_clicks"),
    Input("commo-market-toggle", "n_clicks"),
    Input("risk-checker-toggle", "n_clicks"),
    State(AUTO_REFRESH_STORE_ID, "data"),
    prevent_initial_call=True,
)


app.clientside_callback(
    """
    function(receipt) {
        if (!receipt) return window.dash_clientside.no_update;
        const assets = window.__cubeV5Assets;
        if (typeof assets?.receiveRefreshResult !== 'function') {
            throw new Error('The refresh lifecycle result handler is unavailable.');
        }
        assets.receiveRefreshResult(receipt);
        return receipt.request_id || '';
    }
    """,
    Output("refresh-action-result-ack", "children"),
    Input("refresh-action-result", "data"),
    prevent_initial_call=True,
)
```

Now replace the existing `refresh_pipeline` decorator **and the complete `refresh_pipeline` function**, ending before the next decorator, with the following block. Indent it to the same level as the old callback inside `if refresh_manager is not None:`. Do not leave a second version below it.

This keeps the existing financial action branches and appends one receipt to their nine existing outputs. `refresh-result-store` stays the existing numeric counter; it is not repurposed as the new result receipt. All unchanged-date, disabled automatic, busy, stale, validation, failure and success exits are handled explicitly.

```python
@app.callback(
    Output("refresh-commit-revision", "children"),
    Output(REFRESH_RESULT_STORE_ID, "data"),
    Output("refresh-status", "children"),
    Output("error-log", "children"),
    Output("error-log", "className"),
    Output(FORCE_STORE_ID, "data"),
    Output(VIEW_DATE_STORE_ID, "data"),
    Output(RESET_GENERATION_STORE_ID, "data"),
    Output(CLEAR_CACHE_COMPLETE_STORE_ID, "data"),
    Output("refresh-action-result", "data"),
    Input("refresh-action-request", "data"),
    State(FORCE_DRAFT_STORE_ID, "data"),
    State(AUTO_REFRESH_STORE_ID, "data"),
    State(REFRESH_RESULT_STORE_ID, "data"),
    State(RESET_GENERATION_STORE_ID, "data"),
    running=[
        (Output("refresh-portfolios-button", "disabled"), True, False),
        (Output("refresh-pl-button", "disabled"), True, False),
        (Output("reload-risk-button", "disabled"), True, False),
        (Output("auto-refresh-toggle", "disabled"), True, False),
        (Output("commo-market-toggle", "disabled"), True, False),
        (Output("risk-checker-toggle", "disabled"), True, False),
        (Output("refresh-busy-store", "data"), True, False),
        (
            Output("refresh-status", "className"),
            "refresh-status is-refreshing",
            "refresh-status",
        ),
    ],
    prevent_initial_call=True,
)
def refresh_pipeline(
    request_data,
    draft_state,
    auto_refresh_state,
    refresh_result_counter,
    reset_generation_state,
):
    """Execute one browser request and return an explicit callback receipt."""
    request = request_data if isinstance(request_data, Mapping) else {}
    request_id = request.get("id")
    trigger = request.get("trigger")
    modes = {
        "refresh-portfolios-button": "portfolios",
        "refresh-pl-button": "pl",
        "reload-risk-button": "reload",
        "force-risk-apply-button": "dates",
        "clear-cache-button": "reset",
        "commo-market-toggle": "commo",
        "risk-checker-toggle": "checker",
        "auto-refresh-interval": "automatic",
    }

    def _finish(outcome, values):
        values = tuple(values)
        if len(values) != 9:
            raise RuntimeError(
                "Refresh callback result must contain nine existing outputs"
            )
        try:
            revision = (
                int(values[0])
                if values[0] is not no_update
                else int(refresh_manager.health.revision)
            )
        except (TypeError, ValueError, AttributeError):
            revision = 0
        message = (
            values[2]
            if isinstance(values[2], str)
            else {
                "complete": "Refresh completed.",
                "failed": "Refresh failed; the last successful data remains available.",
                "rejected": "This refresh request was not applied.",
                "busy": "Another refresh is running; this action was not started.",
                "no_work": "No refresh was needed for this request.",
            }[outcome]
        )
        error = values[3] if isinstance(values[3], str) else ""
        receipt = {
            "request_id": request_id if isinstance(request_id, str) else "",
            "trigger": trigger if isinstance(trigger, str) else "",
            "mode": modes.get(trigger, "unknown")
            if isinstance(trigger, str)
            else "unknown",
            "outcome": outcome,
            "revision": max(0, revision),
            "server_boot_id": coordinator.status().server_boot_id,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "error": error,
        }
        return (*values, receipt)

    count = request.get("count")
    if (
        not isinstance(request_id, str)
        or not request_id
        or len(request_id) > 128
        or not isinstance(trigger, str)
        or trigger not in modes
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count <= 0
    ):
        return _finish(
            "rejected",
            (
                no_update,
                no_update,
                "Invalid refresh request; no work was started.",
                "",
                "error-log",
                no_update,
                no_update,
                no_update,
                no_update,
            ),
        )
    triggered_ids = {trigger}
    _auto_intervals = count if trigger == "auto-refresh-interval" else 0

    def _execute():
        current_snapshot = refresh_manager.control_snapshot
        current_applied = snapshot_forced_dates(current_snapshot)
        current_view_date = snapshot_forced_view_date(current_snapshot)
        current_revision = current_snapshot.revision
        committed_commodity = bool(current_snapshot.commodity_market_enabled)
        committed_checker = bool(current_snapshot.risk_checker_enabled)
        commodity_enabled = (
            not committed_commodity
            if "commo-market-toggle" in triggered_ids
            else committed_commodity
        )
        checker_enabled = (
            not committed_checker
            if "risk-checker-toggle" in triggered_ids
            else committed_checker
        )
        applying = "force-risk-apply-button" in triggered_ids
        clearing = "clear-cache-button" in triggered_ids
        browser_reset_generation = int(reset_generation_state or 0)
        apply_result: ForceApplyResult | None = None
        completed_reset_generation: int | None = None
        try:
            if applying:
                requested = draft_forced_dates(draft_state, fallback=current_applied)
                base = draft_base_dates(draft_state, fallback=current_applied)
                requested_view = draft_view_date(
                    draft_state, fallback=current_view_date
                )
                base_view = draft_base_view_date(
                    draft_state, fallback=current_view_date
                )
                if (base != current_applied or base_view != current_view_date) and (
                    requested != current_applied or requested_view != current_view_date
                ):
                    return _finish(
                        "rejected",
                        (
                            no_update,
                            no_update,
                            no_update,
                            "⚠ Applied force dates changed while you were editing. Cancel to reload them before applying.",
                            "error-log has-errors",
                            no_update,
                            no_update,
                            no_update,
                            no_update,
                        ),
                    )
                if requested == current_applied and requested_view == current_view_date:
                    return _finish("no_work", (no_update,) * 9)
                apply_result = apply_force_dates(
                    refresh_manager,
                    requested,
                    view_date=requested_view,
                    commodity_market=commodity_enabled,
                    risk_checker=checker_enabled,
                    expected_revision=int(
                        draft_state.get("base_revision", current_revision)
                        if isinstance(draft_state, Mapping)
                        else current_revision
                    ),
                    expected_reset_generation=browser_reset_generation,
                )
                snapshot = apply_result.snapshot
            elif clearing:
                completed_reset_generation, snapshot = refresh_manager.reset_refresh(
                    expected_reset_generation=browser_reset_generation
                )
                cache.clear_reconstructable()
            elif "refresh-portfolios-button" in triggered_ids:
                snapshot = refresh_manager.refresh_portfolios(
                    reason="portfolio mapping",
                    expected_revision=current_revision,
                    expected_reset_generation=browser_reset_generation,
                )
            elif "reload-risk-button" in triggered_ids:
                refresh_manager.refresh(
                    force_risk=True,
                    forced_dates=current_applied,
                    view_date=current_view_date,
                    commodity_market_enabled=commodity_enabled,
                    risk_checker_enabled=checker_enabled,
                    reason="reload all risk",
                    expected_revision=current_revision,
                    expected_reset_generation=browser_reset_generation,
                    copy_result=False,
                )
                snapshot = refresh_manager.control_snapshot
            elif "refresh-pl-button" in triggered_ids:
                refresh_manager.refresh(
                    force_pl=True,
                    forced_dates=current_applied,
                    view_date=current_view_date,
                    commodity_market_enabled=commodity_enabled,
                    risk_checker_enabled=checker_enabled,
                    reason="manual P&L",
                    expected_revision=current_revision,
                    expected_reset_generation=browser_reset_generation,
                    copy_result=False,
                )
                snapshot = refresh_manager.control_snapshot
            elif "auto-refresh-interval" in triggered_ids:
                if int(_auto_intervals or 0) <= 0 or not auto_refresh_enabled(
                    auto_refresh_state
                ):
                    return _finish("no_work", (no_update,) * 9)
                if not _automatic_refresh_due(current_snapshot):
                    return _finish("no_work", (no_update,) * 9)
                refresh_manager.refresh(
                    force_pl=True,
                    forced_dates=current_applied,
                    view_date=current_view_date,
                    commodity_market_enabled=commodity_enabled,
                    risk_checker_enabled=checker_enabled,
                    reason=_AUTOMATIC_REFRESH_REASON,
                    expected_revision=current_revision,
                    expected_reset_generation=browser_reset_generation,
                    copy_result=False,
                )
                snapshot = refresh_manager.control_snapshot
            elif (
                "commo-market-toggle" in triggered_ids
                or "risk-checker-toggle" in triggered_ids
            ):
                apply_result = apply_force_dates(
                    refresh_manager,
                    current_applied,
                    reason="dashboard settings updated",
                    view_date=current_view_date,
                    commodity_market=commodity_enabled,
                    risk_checker=checker_enabled,
                    expected_revision=current_revision,
                    expected_reset_generation=browser_reset_generation,
                )
                snapshot = apply_result.snapshot
            else:
                return _finish("no_work", (no_update,) * 9)
        except PreventUpdate:
            return _finish("no_work", (no_update,) * 9)
        except RefreshInProgressError:
            return _finish(
                "busy",
                (
                    no_update,
                    no_update,
                    "A refresh is already running; following its live progress.",
                    "",
                    "error-log",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                ),
            )
        except StaleResetGenerationError:
            return _finish(
                "rejected",
                (
                    no_update,
                    no_update,
                    "Failed · This browser cache generation is stale.",
                    "⚠ Reload the page, then Retry Clear Cache.",
                    "error-log has-errors",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                ),
            )
        except StaleRefreshError:
            return _finish(
                "rejected",
                (
                    no_update,
                    no_update,
                    "The data changed before this action could start.",
                    "⚠ The committed revision changed. Reload the staged controls and try again.",
                    "error-log has-errors",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                ),
            )
        except (TypeError, ValueError):
            return _finish(
                "rejected",
                (
                    no_update,
                    no_update,
                    no_update,
                    "⚠ Saved or staged force dates are invalid and were not applied.",
                    "error-log has-errors",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                ),
            )
        except Exception as error:
            incident_id = uuid.uuid4().hex[:10]
            app.logger.exception(
                "Unexpected refresh callback failure; incident=%s type=%s",
                incident_id,
                type(error).__name__,
            )
            return _finish(
                "failed",
                (
                    no_update,
                    no_update,
                    "The refresh action failed; the last successful data remains visible.",
                    f"⚠ Unexpected refresh failure (incident {incident_id}). Check the server log.",
                    "error-log has-errors",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                ),
            )
        snapshot, _prepared = synchronize_committed_dashboard(snapshot)
        status_text, error_text, error_class = _refresh_status(
            snapshot,
            action_committed=apply_result is None or bool(apply_result.committed),
        )
        if clearing and snapshot.errors:
            status_text = "Failed · Cache reset did not complete · Retry Clear Cache"
        if (
            apply_result is not None
            and (not apply_result.committed)
            and (not snapshot.errors)
        ):
            error_text = (
                "⚠ Date settings were not committed; the last successful settings remain applied."
                if applying
                else "⚠ Dashboard settings were not committed; the last successful settings remain applied."
            )
            error_class = "error-log has-errors"
        persisted = (
            persisted_force_dates(apply_result)
            if applying and apply_result is not None
            else None
        )
        return _finish(
            "failed"
            if snapshot.errors
            else "rejected"
            if apply_result is not None and (not apply_result.committed)
            else "complete",
            (
                snapshot.revision,
                _next_counter(refresh_result_counter),
                status_text,
                error_text,
                error_class,
                {}
                if clearing and (not snapshot.errors)
                else persisted
                if persisted is not None
                else no_update,
                None
                if clearing and (not snapshot.errors)
                else apply_result.requested_view_date
                if applying and apply_result is not None and apply_result.committed
                else no_update,
                completed_reset_generation
                if completed_reset_generation is not None
                else no_update,
                completed_reset_generation
                if completed_reset_generation is not None
                else no_update,
            ),
        )

    try:
        return _execute()
    except PreventUpdate:
        return _finish("no_work", (no_update,) * 9)
    except Exception as error:
        incident_id = uuid.uuid4().hex[:10]
        app.logger.exception(
            "Refresh callback did not finish preparing its response; incident=%s type=%s",
            incident_id,
            type(error).__name__,
        )
        return _finish(
            "failed",
            (
                no_update,
                no_update,
                "The refresh response failed; the last successful data remains available.",
                f"Unexpected refresh response failure (incident {incident_id}). Check the server log.",
                "error-log has-errors",
                no_update,
                no_update,
                no_update,
                no_update,
            ),
        )
```

Keep the refresh callback's existing `running` controls. They protect the write actions; they must not disable the entire page, its navigation, or its read-only filters. Keep the manager's existing atomic commit, last-good snapshot, stale-revision checks and single-writer guard.

## 6. Publish committed revisions independently and stop replacing the live shell

In the same `if refresh_manager is not None:` block, put this registration immediately before the existing `coordinator = ...` assignment. It replaces the older clientside publisher removed in section 1. It is the only clientside callback here that owns `data-revision-store.data`.

```python
app.clientside_callback(
    """
    function(...args) {
        return window.dash_clientside.cubeRefresh.publish(...args);
    }
    """,
    Output("data-revision-store", "data"),
    Input("committed-revision-poll", "n_intervals"),
    State("refresh-commit-revision", "children"),
    State("data-revision-store", "data"),
    State("risk-workspace-tabs", "value", allow_optional=True),
    State("refresh-view-risk-explorer", "data"),
    State("refresh-view-unmapped-books", "data"),
    State("refresh-view-aggregate-pl", "data"),
    State("refresh-view-top-promotions", "data"),
    State("refresh-view-quick-risk-options", "data"),
    State("refresh-view-quick-risk-table", "data"),
    State("refresh-view-quick-risk-chart", "data"),
    State("refresh-view-quick-market-options", "data"),
    State("refresh-view-quick-market", "data"),
    State("refresh-view-pnl-summary", "data"),
    State("refresh-view-pnl-editor-sog", "data"),
    State("refresh-view-pnl-editor-portfolio", "data"),
    prevent_initial_call=False,
)
```

The publisher must run during bootstrap as well as normal refreshes. Do not put it behind `refresh-busy-store`, a Hero completion check, a `mode !== "bootstrap"` condition, or a requirement that all view receipts already exist. Those conditions can prevent the very callbacks that need the new revision from starting.

Still in `s15_refresh.py`, find `hydrate_shared_refresh_shell`. Inside its successful-startup branch, keep the conversion of `displayed_revision` into `shell_revision`. Replace the following old shell-replacement condition, including any check of the refresh status class:

```python
if (
    shell_revision >= refresh_manager.health.revision
    and "is-refreshing" not in str(status_class or "").split()
):
    raise PreventUpdate
```
with:

```python
if shell_revision > 0:
    raise PreventUpdate
```

If you already have a shorter equivalent old condition, replace its complete `if` condition with the same two lines above. Leave the subsequent `return build_shared_refresh_shell(...)` block intact. Once the shared shell holds an initial committed revision, later refreshes update its existing nodes and stores. Rebuilding the whole shell during a normal refresh would discard the request and view receipts added above.

## 7. Add a receipt to each existing visible result callback

Add this import once, below `from __future__ import annotations` in each of the four files listed below. Keep every other import.

```python
from cube.ui.s08_refresh_views import refresh_view
```

- `cube/pages/risk/s07_explorer.py`
- `cube/pages/risk/s14_workspacecallbacks.py`
- `cube/pages/pnl/s08_aggregate.py`
- `cube/pages/pnl/s05_sendcallbacks.py`

For each function below, replace **only its existing `@app.callback(...)` block and any older `@refresh_view(...)` decorator** with the supplied decorators. Keep the original `def`, its parameters and its full body in place. Indent both decorators to the same level as that `def`. Do not add a request parameter to the original function: the wrapper consumes the final request State before calling it.

This preserves the all.md filtering, grouping, pagination, totals, history and JTD changes already in your function bodies. If a previous local change added another Output or changed the named revision parameter, reconcile that concrete signature before installing the wrapper: `outputs`, `content` and `stamp` refer to the displayed output order below, excluding the new receipt.

### 7.1. `cube/pages/risk/s07_explorer.py` — `reduce_and_render_risk_view`

```python
@app.callback(
    Output("split-filter", "options"),
    Output("split-filter", "value"),
    Output("open-rows-store", "data"),
    Output("selected-cell-store", "data"),
    Output("plot-measure", "value"),
    Output("risk-view-context-store", "data"),
    Output("plot-component", "options"),
    Output("plot-component", "value"),
    Output("detail-tenor-view", "options"),
    Output("detail-tenor-view", "value"),
    Output("expanded-metrics", "value"),
    Output("risk-grid", "children"),
    Output("alt-risk-grid", "children"),
    Output("detail-panel", "children"),
    Output('refresh-view-risk-explorer', "data"),
    Input("risk-type-tabs", "value"),
    Input("ir-family-tabs", "value"),
    Input("data-revision-store", "data"),
    Input("table-dimension", "value"),
    Input("table-view-tabs", "value"),
    Input("credit-view-tabs", "value"),
    Input("risk-row-action-store", "data"),
    Input("risk-cell-action-store", "data"),
    Input("risk-metric-action-store", "data"),
    Input("split-filter", "value"),
    Input("credit-measure", "value"),
    Input("credit-multi-metric", "value"),
    Input("alt-metric", "value"),
    Input("plot-measure", "value"),
    Input("plot-component", "value"),
    Input("detail-tenor-view", "value"),
    Input("dimension-filter-values-store", "data"),
    Input("risk-filter-exclude-applied-store", "data"),
    Input("risk-explorer-options", "value"),
    Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
    Input("underlying-identity-mode", "value"),
    Input("underlying-sort-metric", "value"),
    State("open-rows-store", "data"),
    State("expanded-metrics", "value"),
    State("risk-view-context-store", "data"),
    State("selected-cell-store", "data"),
    State("refresh-action-request", "data"),
)
@refresh_view('risk-explorer', revision_arg='data_revision', outputs=14, content=[11, 12, 13], stamp=[11, 12, 13])
```

### 7.2. `cube/pages/risk/s07_explorer.py` — `render_unmapped_books`

```python
@app.callback(
    Output("unmapped-books-details", "open"),
    Output("unmapped-books-grid", "children"),
    Output('refresh-view-unmapped-books', "data"),
    Input("unmapped-books-summary", "n_clicks"),
    Input("data-revision-store", "data"),
    State("unmapped-books-details", "open"),
    State("refresh-action-request", "data"),
    prevent_initial_call=True,
)
@refresh_view('unmapped-books', revision_arg='_revision', outputs=2, content=[1], stamp=[1])
```

### 7.3. `cube/pages/risk/s14_workspacecallbacks.py` — `reduce_and_render_aggregate_pl`

```python
@app.callback(
    Output("aggregate-open-risk-types", "data"),
    Output("aggregate-pl-grid", "children"),
    Output('refresh-view-aggregate-pl', "data"),
    Input("aggregate-pl-dimension", "value"),
    Input("data-revision-store", "data"),
    Input("risk-initial-render-ready", "data"),
    Input({"type": "aggregate-row-toggle", "risk_type": ALL}, "n_clicks"),
    Input("split-filter", "value"),
    Input("dimension-filter-values-store", "data"),
    Input("risk-filter-exclude-applied-store", "data"),
    State("aggregate-open-risk-types", "data"),
    State("refresh-action-request", "data"),
)
@refresh_view('aggregate-pl', revision_arg='_data_revision', outputs=2, content=[1], stamp=[1])
```

### 7.4. `cube/pages/risk/s14_workspacecallbacks.py` — `render_top_promotions`

```python
@app.callback(
    Output("top-promotions-grid", "children"),
    Output("top-promotions-status", "children"),
    Output('refresh-view-top-promotions', "data"),
    Input("risk-workspace-tabs", "value"),
    Input("data-revision-store", "data"),
    Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
    Input("split-filter", "value"),
    Input("dimension-filter-values-store", "data"),
    Input("risk-filter-exclude-applied-store", "data"),
    Input("top-promotions-signal", "value"),
    State("refresh-action-request", "data"),
)
@refresh_view('top-promotions', revision_arg='data_revision', outputs=2, content=[0], stamp=[0])
```

### 7.5. `cube/pages/risk/s14_workspacecallbacks.py` — `load_combine_udl_options`

```python
@app.callback(
    Output("quick-search-combine-udl", "options"),
    Output("quick-search-combine-udl", "value"),
    Output('refresh-view-quick-risk-options', "data"),
    Input("risk-workspace-tabs", "value"),
    Input("data-revision-store", "data"),
    Input("quick-search-combine-udl", "search_value"),
    Input("split-filter", "value"),
    Input("dimension-filter-values-store", "data"),
    Input("risk-filter-exclude-applied-store", "data"),
    State("quick-search-combine-udl", "value"),
    State("refresh-action-request", "data"),
    prevent_initial_call=False,
)
@refresh_view('quick-risk-options', revision_arg='_revision', outputs=2, content=[0], stamp=[])
```

### 7.6. `cube/pages/risk/s14_workspacecallbacks.py` — `render_current_pivot`

```python
@app.callback(
    Output("quick-search-results", "children"),
    Output("quick-search-dimensions", "value"),
    Output('refresh-view-quick-risk-table', "data"),
    Input("quick-search-combine-udl", "value"),
    Input("quick-search-dimensions", "value"),
    Input("risk-workspace-tabs", "value"),
    Input("data-revision-store", "data"),
    Input("split-filter", "value"),
    Input("dimension-filter-values-store", "data"),
    Input("risk-filter-exclude-applied-store", "data"),
    State("refresh-action-request", "data"),
    prevent_initial_call=True,
)
@refresh_view('quick-risk-table', revision_arg='_revision', outputs=2, content=[0], stamp=[0])
```

### 7.7. `cube/pages/risk/s14_workspacecallbacks.py` — `render_quick_risk_tenor`

```python
@app.callback(
    Output("quick-risk-tenor-result", "children"),
    Output("quick-risk-tenor-view", "options"),
    Output("quick-risk-tenor-view", "value"),
    Output('refresh-view-quick-risk-chart', "data"),
    Input("quick-search-combine-udl", "value"),
    Input("quick-risk-tenor-view", "value"),
    Input("risk-workspace-tabs", "value"),
    Input("data-revision-store", "data"),
    Input("split-filter", "value"),
    Input("dimension-filter-values-store", "data"),
    Input("risk-filter-exclude-applied-store", "data"),
    State("refresh-action-request", "data"),
)
@refresh_view('quick-risk-chart', revision_arg='revision', outputs=3, content=[0], stamp=[0])
```

### 7.8. `cube/pages/risk/s14_workspacecallbacks.py` — `load_market_udl_options`

```python
@app.callback(
    Output("quick-market-combine-udl", "options"),
    Output("quick-market-combine-udl", "value"),
    Output('refresh-view-quick-market-options', "data"),
    Input("risk-workspace-tabs", "value"),
    Input("data-revision-store", "data"),
    Input("quick-market-combine-udl", "search_value"),
    State("quick-market-combine-udl", "value"),
    State("refresh-action-request", "data"),
    prevent_initial_call=False,
)
@refresh_view('quick-market-options', revision_arg='_revision', outputs=2, content=[0], stamp=[])
```

### 7.9. `cube/pages/risk/s14_workspacecallbacks.py` — `render_market_search`

```python
@app.callback(
    Output("quick-market-results", "children"),
    Output("quick-market-view", "value"),
    Output("quick-market-view", "options"),
    Output("quick-market-surface-metric", "options"),
    Output("quick-market-values", "data"),
    Output("quick-market-values", "columns"),
    Output("quick-market-values", "page_count"),
    Output("quick-market-values", "page_current"),
    Output('refresh-view-quick-market', "data"),
    Input("quick-market-combine-udl", "value"),
    Input("quick-market-view", "value"),
    Input("quick-market-surface-metric", "value"),
    Input("risk-workspace-tabs", "value"),
    Input("data-revision-store", "data"),
    Input("quick-market-values", "page_current"),
    State("refresh-action-request", "data"),
    prevent_initial_call=True,
)
@refresh_view('quick-market', revision_arg='_revision', outputs=8, content=[0], stamp=[0])
```

### 7.10. `cube/pages/pnl/s08_aggregate.py` — `reduce_and_render_pl_summary`

```python
@app.callback(
    Output("pnl-summary-open-paths", "data"),
    Output("pnl-aggregate-pl-grid", "children"),
    Output('refresh-view-pnl-summary', "data"),
    Input("data-revision-store", "data"),
    Input({"type": PL_SUMMARY_TOGGLE_TYPE, "path": ALL}, "n_clicks"),
    Input(
        {"type": PL_SUMMARY_PAGE_TYPE, "path": ALL, "page": ALL},
        "n_clicks",
    ),
    Input(consumer_controls.committed_state_id, "data"),
    Input("clear-cache-complete-store", "data"),
    State("pnl-summary-open-paths", "data"),
    State("refresh-action-request", "data"),
)
@refresh_view('pnl-summary', revision_arg='_data_revision', outputs=2, content=[1], stamp=[1])
```

### 7.11. `cube/pages/pnl/s05_sendcallbacks.py` — `control_editor`

This callback is defined inside the existing editor registration that receives `section`; keep that structure. Its two normal registrations create the SOG and Portfolio receipt owners.

```python
@app.callback(
    Output(table_id, "data"),
    Output(table_id, "dropdown"),
    Output(table_id, "dropdown_conditional"),
    Output(draft_store_id, "data"),
    Output(active_scope_store_id, "data"),
    Output(f"{table_id}-data-status", "children"),
    Output(f"refresh-view-pnl-editor-{section}", "data"),
    Input("pl-send-effective-query-store", "data"),
    Input(filter_id, "value"),
    Input(add_id, "n_clicks"),
    Input(table_id, "data_timestamp"),
    State(table_id, "data"),
    State(table_id, "data_previous"),
    State(draft_store_id, "data"),
    State(active_scope_store_id, "data"),
    State("refresh-action-request", "data"),
    running=[
        (Output(add_id, "disabled"), True, False),
        (Output(save_id, "disabled"), True, False),
        (Output(send_id, "disabled"), True, False),
    ],
)
@refresh_view(f"pnl-editor-{section}", revision_arg='query', outputs=6, content=[0, 5], stamp=[5])
```

### 7.12. Preserve actual failures and reject stale chart output

Two small body changes are also needed in `cube/pages/risk/s14_workspacecallbacks.py`; the decorator cannot distinguish a deliberately hidden result from an error that the body silently swallows.

In `load_combine_udl_options`, find the exception handler immediately around `_combine_udl_dropdown_options(refresh_manager.search_combine_udl_options(...))`. Keep its exception types, but replace its `return no_update, no_update` with `raise`. The handler must be:

```python
except (
    AttributeError,
    LookupError,
    TypeError,
    ValueError,
    RuntimeError,
):
    raise
```

In `load_market_udl_options`, do the same for the handler around `refresh_manager.search_market_udl_options(...)`:

```python
except (AttributeError, LookupError, TypeError, ValueError, RuntimeError):
    raise
```

Keep the separate inactive-workspace `return no_update, no_update` at the top of both functions. Raising only these actual lookup failures lets `@refresh_view` return a failed receipt while retaining the prior display, instead of leaving the Hero waiting forever for a result that will never arrive.

In `render_quick_risk_tenor`, find the comparison between the callback revision, `identity.source_revision` and `cache.revision`. Keep that comparison and make its mismatch return exactly this:

```python
if not (
    int(revision or 0) == identity.source_revision == cache.revision
):
    return no_update, no_update, no_update
```

This preserves the current chart until matching-revision work returns. Do not acknowledge a temporary “refreshing” placeholder as the completed chart. Keep its actual exception handler returning an alert; the wrapper can report that as a failed view.

### 7.13. Mark a failed P&L editor preparation as an error

Open `cube/pages/pnl/s05_sendcallbacks.py`. Add `html` to its existing Dash import. In this version, the complete import is:

```python
from dash import Dash, Input, Output, Patch, State, ctx, html, no_update
```

Keep any additional Dash imports you already use. Inside `control_editor`, find the final `except Exception as exc:` handler that returns a message beginning `Could not prepare`. Replace only that handler with this complete block at its existing indentation:

```python
except Exception as exc:
    data_out = no_update if trigger in (table_id, add_id) else []
    return (
        data_out,
        no_update,
        no_update,
        no_update,
        no_update,
        html.Span(f"Could not prepare {scope_column} rows: {exc}", role="alert"),
    )
```

The message remains visible in the editor's existing status location. Its `role="alert"` now identifies this as failed preparation, so the wrapper reports a failed receipt instead of treating the plain error text as a successful render. Keep the normal editor body and the separate save/send exception handlers unchanged.

## 8. Remove only the duplicate native warm-start call

Open `assets/s13_risk.js`. In the document click listener, find the block beginning `const refreshTrigger = event.target.closest(`. Preserve the existing trigger selector, the mode calculation, and the Commo/checker status text.

First, find the `if` immediately after that selector. If it currently reads `if (refreshTrigger) {`, replace that line with:

```javascript
if (refreshTrigger && !refreshTrigger.disabled) {
```

Keep the existing closing brace. If that disabled-control guard is already present, keep it once. This prevents clicks on a disabled Retry/write control from starting a duplicate local Hero action.

At the end of that block, replace the unconditional warm-start call:

```javascript
startRefreshProgress(mode);
```
with:

```javascript
// Warm actions start atomically in the refresh-action-request dispatcher.
if (mode === "bootstrap") startRefreshProgress(mode);
```

If an earlier version called it through `app.startRefreshProgress(mode)`, apply the same `mode === "bootstrap"` condition to that one call. Do not retain another capture listener that independently starts warm actions.

Keep the bootstrap Retry call, Shift+F9/native button shortcut behavior, JTD row-label delegation, chevrons, keyboard navigation, cell selection, copy handling, and the rest of `s13_risk.js`. Do not replace that whole asset with an older file: it contains the latest JTD click repairs.

## 9. Restart and check the complete path

Restart the Python process after the changes and hard-reload the browser so the updated JavaScript is loaded. A hot-reloaded Python process with cached old assets is not a valid check of this change.

Check the following as ordinary user actions:

1. Cold start: progress is visible, stage text advances when the server reports work, the first real page becomes usable, and completion waits for the startup worker and visible results.
2. One Shift+F9: exactly one request starts; progress remains visible while that request runs; the result updates without needing extra presses.
3. Repeat PL refresh, reload Risk, refresh Portfolios, date Apply, Commo, Risk Checker and Clear Cache. Confirm each returns a clear completion or failure/no-work outcome.
4. During a deliberately slow refresh, expand a Risk branch, change a read-only filter, and move between pages. Check the selected visible page remains usable and receives the committed revision when it is ready.
5. Test Quick Risk with no selected identity and with a selected identity. Do the same for Quick Market. An intentionally empty selection must settle; an actual lookup error must be reported.
6. Open each supported panel: main/Cross Risk, unmapped books, Aggregate PL, Top Promotions, Quick Risk, Quick Market, P&L summary, and each P&L editor. Completion must follow the currently visible results. Closing or switching a panel changes the presentation being awaited; it does not cancel the backend request.
7. Briefly interrupt the progress endpoint during a slow request. The Hero must show the connection problem and retain the active state, then recover when polling succeeds. It must not fabricate “done”.
8. Click a JTD underlying and a higher hierarchy row. The table must still open with the corresponding scope; this confirms the small `s13_risk.js` edit preserved JTD delegation.

For a pending request, the browser console can display the small lifecycle diagnostic object:

```javascript
window.__cubeV5Assets.refreshDiagnostics()
```

`callback_pending` means the identified server callback has not returned its receipt. `pending_views` names the visible results still being awaited. `last_progress_age_ms` helps distinguish a slow calculation from lost progress polling. An active request is not proof that its connector is making progress; the server's reported stage and the diagnostic age provide that evidence.

These checks cover one refresh action and its supported visible results. They do not wait for unrelated background intervals forever, and they cannot certify third-party connector behavior. The financial readers, calculations, atomic snapshot rules, and current production-adapter contracts stay in their existing modules.

## 10. Verified implementation and limits

Verified locally with Python, Dash 4.4.0, Chrome, and invented CSV/synthetic sources:

- 27 backend request/receipt checks cover all eight refresh actions and success, stale, rejected, busy, no-work and failure exits. Six renderer-receipt tests cover matching, mounted markers, no-update, errors and editor query revisions.
- 23 complete-asset lifecycle scenarios cover live updates, stale results, repeated requests, connection failures, startup, retry and newer-revision display changes. Six real-Chrome bridge checks cover delayed graph drawing, route/workspace changes and stale receipts.
- Actual full Dash runs pass cold starts on Risk and direct `/pnl`, repeated one-click PL refreshes, one-press Shift+F9, usable ordinary controls, and a replaced hero. Holding real Aggregate P&L responses after the backend callback returns keeps the hero waiting; releasing them permits completion.
- Controlled real startup failure, one Retry with a new startup attempt, warm source failure and a subsequent one-press Shift+F9 recovery pass. The retry test found and corrected a race: the previous failed startup response must not finish the new attempt.
- With selected Quick Risk and Quick Market charts in the full app, one PL click advances the revision, draws the chart and finishes all expected receipts. These browser runs recorded no page errors or failed HTTP responses on their successful paths.
- The guide's complete asset/helper blocks, server replacement and all eleven callback decorator blocks are checked against the tested candidate, including their Output counts and final request State. The eleven registrations produce twelve owners because the P&L editor is registered for both SOG and Portfolio.

These tests reconstruct the affected cumulative guide paths. They do not claim that every historical prose-only feature, production connector, dataset or deployment has been reproduced. Keep your implemented history, Portfolio, JTD and other earlier changes; the decorator edits deliberately preserve their function bodies. This GitHub change publishes instructions, not a deployment of your app.

