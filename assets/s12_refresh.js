/* Shared fail-soft startup and atomic refresh progress lifecycle. */
(() => {
  "use strict";

  const app = window.__cubeV5Assets = window.__cubeV5Assets || {};
  const { dashIsLoading, setGlobalLoaderVisible } = app;
  let syncRefreshLifecycleNodes = () => {};
  app.syncRefreshLifecycleNodes = (...args) => syncRefreshLifecycleNodes(...args);

    let refreshProgressState = null;
    let refreshProgressClock = null;
    let backendProgressRequest = null;
    let backendProgressNextPoll = 0;
    let backendProgressAvailable = null;
    let lastBackendProgress = null;
    let previousBackendProgress = null;
    let backendProgressFailures = 0;
    let backendProgressLastError = "";
    let backendProgressLastSuccessAt = 0;
    let backendStartRequest = null;
    let backendStartNextAttempt = 0;
    let backendStartFailures = 0;
    let refreshStatusObserver = null;
    let observedRefreshStatusNode = null;
    let lastPublishedDataRevision = 0;
    const BACKEND_PROGRESS_POLL_MS = 1000;
    const BACKEND_PROGRESS_REQUEST_TIMEOUT_MS = 30000;
    const BACKEND_PROGRESS_FAILURE_LIMIT = 2;
    const BACKEND_RETRY_MAX_MS = 30000;

    const clearRefreshProgressTimers = () => {
      if (refreshProgressClock) clearInterval(refreshProgressClock);
      refreshProgressClock = null;
    };

    const backendEndpointUrl = (name) => {
      try {
        const endpointNode = document.getElementById("backend-endpoints");
        const configured = name === "start"
          ? endpointNode?.dataset.startUrl
          : endpointNode?.dataset.progressUrl;
        if (configured) return new URL(configured, window.location.origin).toString();
        const configNode = document.getElementById("_dash-config");
        const config = configNode?.textContent ? JSON.parse(configNode.textContent) : {};
        const prefix = String(config.requests_pathname_prefix || window.location.pathname || "/");
        const normalizedPrefix = `${prefix.replace(/\/+$/, "")}/`;
        return new URL(`${normalizedPrefix}${name}`, window.location.origin).toString();
      } catch (_error) {
        return new URL(`${name}`, document.baseURI).toString();
      }
    };

    const progressEndpointUrl = () => backendEndpointUrl("progress");
    const startEndpointUrl = () => backendEndpointUrl("start");

    const transportErrorText = (error, endpoint) => {
      if (error?.name === "AbortError")
        return `${endpoint} timed out after ${BACKEND_PROGRESS_REQUEST_TIMEOUT_MS / 1000}s`;
      const detail = String(error?.message || error || "unknown transport error")
        .replace(/\s+/g, " ")
        .trim();
      return `${endpoint}: ${detail}`;
    };

    const REFRESH_STAGES = ["readiness", "risk", "market", "pl", "final"];

    const normalizeProgressStage = (stage, functionName = "") => {
      const value = `${stage || ""} ${functionName || ""}`
        .trim()
        .toLowerCase()
        .replace(/_/g, " ")
        .replace(/-/g, " ")
        .replace(/\//g, " ")
        .replace(/\s+/g, " ");
      if (!value) return null;
      if (/\b(final|publish|commit|validate|complete|combine|config|threshold|merge|group|aggregate|aggregation|dashboard)\b/.test(value)) return "final";
      if (/\b(p&l|pnl|pl|profit|calculate)\b/.test(value)) return "pl";
      if (/\b(market|official|open|live|current|price)\b/.test(value)) return "market";
      if (/\b(readiness|ready|status|starting|start)\b/.test(value)) return "readiness";
      if (/\b(risk|snapshot|connector|position)\b/.test(value)) return "risk";
      return null;
    };

    const progressStartedAt = (value) => {
      if (value === null || value === undefined || value === "") return null;
      if (typeof value === "number" || /^\d+(\.\d+)?$/.test(String(value))) {
        const numeric = Number(value);
        if (!Number.isFinite(numeric)) return null;
        return numeric < 10_000_000_000 ? numeric * 1000 : numeric;
      }
      const parsed = Date.parse(String(value));
      return Number.isFinite(parsed) ? parsed : null;
    };

    const progressStartedDuringAttempt = (progress, browserStartedAt) => {
      if (!progress || progress.started_at === null) return false;
      // Compare clocks using the server timestamp carried by the same
      // response. A user's computer and Plotly worker need not agree
      // within the old 500 ms window.
      const clockOffset = progress.server_time === null
        ? 0
        : progress.received_at - progress.server_time;
      return progress.started_at + clockOffset >= browserStartedAt - 1000;
    };

    const progressFingerprint = (progress) => progress ? JSON.stringify([
      progress.attempt_id,
      progress.started_at,
      progress.running,
      progress.function_name,
      progress.stage,
      progress.source_type,
      progress.underlying,
      progress.product_label,
      progress.product_index,
      progress.product_total,
      progress.hold_seconds,
      progress.current,
      progress.total,
      progress.message,
      progress.error,
      progress.updated_at,
      progress.revision,
      progress.startup_phase,
      progress.startup_attempt_id,
      progress.server_boot_id,
    ]) : "";

    const normalizedRevision = (value) => {
      if (
        (typeof value !== "number" && typeof value !== "string")
        || (typeof value === "string" && !value.trim())
      ) return null;
      const revision = Number(value);
      return Number.isSafeInteger(revision) && revision >= 0 ? revision : null;
    };

    const renderedDataRevisionFloor = () => {
      let floor = lastPublishedDataRevision;
      const store = document.getElementById("data-revision-store");
      [
        store?.data,
        store?.dataset?.revision,
        store?.getAttribute?.("data-revision"),
      ].forEach((value) => {
        const revision = normalizedRevision(value);
        if (revision !== null) floor = Math.max(floor, revision);
      });
      document.querySelectorAll("[data-risk-view-token]").forEach((node) => {
        try {
          const token = JSON.parse(node.dataset.riskViewToken || "{}");
          const revision = normalizedRevision(token.data_revision);
          if (revision !== null) floor = Math.max(floor, revision);
        } catch (_error) {
          // A malformed/stale table token must not block a newer valid revision.
        }
      });
      document.querySelectorAll("[data-snapshot-revision]").forEach((node) => {
        const revision = normalizedRevision(node.dataset.snapshotRevision);
        if (revision !== null) floor = Math.max(floor, revision);
      });
      const baseline = normalizedRevision(refreshProgressState?.baselineRevision);
      if (baseline !== null) floor = Math.max(floor, baseline);
      lastPublishedDataRevision = Math.max(lastPublishedDataRevision, floor);
      return floor;
    };

    const financialPageCanConsumeRevision = () => (
      (
        document.getElementById("cube-page-container")
        && document.getElementById("risk-type-tabs")
      )
      || document.getElementById("pnl-page-container")
    );

    const syncCommittedDataRevision = (progress) => {
      if (refreshProgressState?.mode === "bootstrap") return false;
      // Revision-driven callbacks target page-local outputs. Hold the common
      // signal until a warm Risk page or the configured P&L page can consume it.
      if (!financialPageCanConsumeRevision()) return false;
      const commitNode = document.getElementById("refresh-commit-revision");
      const progressRevision = progress?.running === false
        ? normalizedRevision(progress.revision)
        : null;
      const commitRevision = normalizedRevision(commitNode?.textContent);
      const candidates = [progressRevision, commitRevision]
        .filter((value) => value !== null);
      const revision = candidates.length ? Math.max(...candidates) : null;
      const setProps = window.dash_clientside?.set_props;
      // dcc.Store renders no DOM node; its colocated commit signal is the
      // mount sentinel before addressing the Store through Dash's registry.
      if (
        revision === null
        || !commitNode
        || revision <= renderedDataRevisionFloor()
        || typeof setProps !== "function"
      ) return false;
      try {
        setProps("data-revision-store", { data: revision });
        lastPublishedDataRevision = revision;
        return true;
      } catch (_error) {
        // A transient Dash mount race must not poison backend progress polling.
        return false;
      }
    };

    const claimSessionReload = (key) => {
      try {
        if (window.sessionStorage.getItem(key)) return false;
        window.sessionStorage.setItem(key, String(Date.now()));
        return true;
      } catch (_error) {
        // Without durable session state, reloading could recreate a loop.
        return false;
      }
    };

    const requestBackendProgress = async (force = false) => {
      const now = Date.now();
      if (!force && now < backendProgressNextPoll) {
        return backendProgressAvailable === false ? null : lastBackendProgress;
      }
      if (backendProgressRequest) return backendProgressRequest;
      backendProgressNextPoll = now + BACKEND_PROGRESS_POLL_MS;
      backendProgressRequest = (async () => {
        const controller = new AbortController();
        const timeout = setTimeout(
          () => controller.abort(),
          BACKEND_PROGRESS_REQUEST_TIMEOUT_MS,
        );
        try {
          const response = await fetch(progressEndpointUrl(), {
            cache: "no-store",
            credentials: "same-origin",
            headers: { Accept: "application/json" },
            signal: controller.signal,
          });
          if (!response.ok) throw new Error(`progressz returned ${response.status}`);
          const contentType = response.headers.get("content-type") || "";
          if (!contentType.toLowerCase().includes("application/json")) {
            throw new Error(`progressz returned ${contentType || "non-JSON content"}`);
          }
          const payload = await response.json();
          if (!payload || typeof payload !== "object") throw new Error("progressz did not return an object");
          const numberOrNull = (value) => {
            if (value === null || value === undefined || value === "") return null;
            const parsed = Number(value);
            return Number.isFinite(parsed) ? parsed : null;
          };
          const progress = {
        running: payload.running === true || payload.running === 1 || payload.running === "true",
            attempt_id: String(payload.attempt_id || ""),
            function_name: String(payload.function_name || ""),
            stage: String(payload.stage || ""),
            source_type: String(payload.source_type || ""),
            underlying: String(payload.underlying || ""),
            product_label: String(payload.product_label || ""),
            product_index: numberOrNull(payload.product_index),
            product_total: numberOrNull(payload.product_total),
            hold_seconds: numberOrNull(payload.hold_seconds),
            current: numberOrNull(payload.current),
            total: numberOrNull(payload.total),
            message: String(payload.message || ""),
            started_at: progressStartedAt(payload.started_at),
            updated_at: progressStartedAt(payload.updated_at),
            revision: numberOrNull(payload.revision) || 0,
            startup_phase: String(payload.startup_phase || ""),
            startup_attempt_id: String(payload.startup_attempt_id || ""),
            server_boot_id: String(payload.server_boot_id || ""),
            server_time: progressStartedAt(payload.server_time),
            received_at: Date.now(),
            error: typeof payload.error === "string"
              ? payload.error
              : payload.error ? String(payload.message || "Backend refresh failed") : "",
          };
          backendProgressFailures = 0;
          backendProgressAvailable = true;
          backendProgressLastError = "";
          backendProgressLastSuccessAt = Date.now();
          backendProgressNextPoll = Date.now() + BACKEND_PROGRESS_POLL_MS;
          previousBackendProgress = lastBackendProgress;
          lastBackendProgress = progress;
          syncCommittedDataRevision(progress);
          return progress;
        } catch (error) {
          backendProgressFailures += 1;
          backendProgressLastError = transportErrorText(error, "progressz");
          const retryDelay = Math.min(
            BACKEND_RETRY_MAX_MS,
            BACKEND_PROGRESS_POLL_MS * (2 ** Math.min(backendProgressFailures - 1, 3)),
          );
          backendProgressNextPoll = Date.now() + retryDelay;
          if (backendProgressFailures >= BACKEND_PROGRESS_FAILURE_LIMIT) {
            backendProgressAvailable = false;
            return null;
          }
          return lastBackendProgress;
        } finally {
          clearTimeout(timeout);
          backendProgressRequest = null;
        }
      })();
      return backendProgressRequest;
    };

    const requestBackendStart = async (force = false) => {
      const now = Date.now();
      if (!force && now < backendStartNextAttempt) return null;
      if (backendStartRequest) return backendStartRequest;
      backendStartNextAttempt = now + BACKEND_PROGRESS_POLL_MS;
      backendStartRequest = (async () => {
        const controller = new AbortController();
        const timeout = setTimeout(
          () => controller.abort(),
          BACKEND_PROGRESS_REQUEST_TIMEOUT_MS,
        );
        try {
          const response = await fetch(startEndpointUrl(), {
            method: "POST",
            cache: "no-store",
            credentials: "same-origin",
            headers: { Accept: "application/json" },
            signal: controller.signal,
          });
          if (!response.ok) throw new Error(`startz returned ${response.status}`);
          const contentType = response.headers.get("content-type") || "";
          if (!contentType.toLowerCase().includes("application/json")) {
            throw new Error(`startz returned ${contentType || "non-JSON content"}`);
          }
          await response.json();
          backendStartFailures = 0;
          backendStartNextAttempt = Date.now() + 5000;
          return true;
        } catch (error) {
          backendStartFailures += 1;
          backendProgressLastError = transportErrorText(error, "startz");
          backendStartNextAttempt = Date.now() + Math.min(
            BACKEND_RETRY_MAX_MS,
            BACKEND_PROGRESS_POLL_MS * (2 ** Math.min(backendStartFailures, 3)),
          );
          return false;
        } finally {
          clearTimeout(timeout);
          backendStartRequest = null;
        }
      })();
      return backendStartRequest;
    };

    const setRefreshStageState = (stage, state) => {
      const row = document.getElementById(`refresh-stage-${stage}`);
      if (!row) return;
      row.classList.remove("is-active", "is-complete", "is-skipped", "is-error");
      if (state) row.classList.add(`is-${state}`);
    };

    const configureRefreshStage = (stage, _functionName, progressText = "", _sourceType = "") => {
      const row = document.getElementById(`refresh-stage-${stage}`);
      if (!row) return;
      const duration = row.querySelector(".refresh-stage-duration");
      if (duration) duration.textContent = progressText;
    };

    const setProgressDetail = (id, value) => {
      const node = document.getElementById(id);
      const nextValue = value || "";
      if (node && node.textContent !== nextValue) node.textContent = nextValue;
    };

    const refreshStatusNode = () => (
      document.getElementById("refresh-status")
      || document.getElementById("bootstrap-refresh-status")
    );

    const refreshLifecycleVisible = () => {
      const shell = document.getElementById("shared-refresh-shell");
      if (!shell) return true;
      const style = window.getComputedStyle(shell);
      return style.display !== "none"
        && style.visibility !== "hidden"
        && shell.getClientRects().length > 0;
    };

    const refreshErrorNode = () => (
      document.getElementById("error-log")
      || document.getElementById("bootstrap-error-log")
    );

    const displayFunctionName = (functionName) => {
      const value = String(functionName || "");
      return /^[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*$/.test(value)
        ? `${value}()`
        : value;
    };

    const renderBackendProgress = (progress) => {
      if (!progress || !refreshProgressState) return;
      const panel = document.getElementById("refresh-progress");
      if (panel) {
        panel.dataset.progressSource = "backend";
        if (!progress.error)
          panel.classList.remove("is-error");
        panel.classList.add("is-running");
      }

      const functionName = progress.function_name || "Backend task";
      const stage = normalizeProgressStage(progress.stage, functionName);
      const hasProduct = progress.product_index !== null
        && progress.product_total !== null
        && progress.product_total > 0;
      const isUnderlyingLoop = ["market", "market_open", "market_status"]
        .includes(stage);
      const unitLabel = isUnderlyingLoop ? "Underlying" : "Product";
      const countText = hasProduct
        ? `${unitLabel} ${Math.max(0, progress.product_index)} of ${progress.product_total}`
        : "";
      const holdText = hasProduct && progress.hold_seconds > 0
        ? `${progress.hold_seconds}s Risk/dRisk hold`
        : "";
      const percent = hasProduct
        ? Math.max(0, Math.min(100, (progress.product_index / progress.product_total) * 100))
        : 0;
      setProgressDetail("refresh-progress-function", displayFunctionName(functionName));
      setProgressDetail(
        "refresh-progress-source",
        [progress.source_type, progress.underlying].filter(Boolean).join(" - "),
      );
      setProgressDetail("refresh-progress-count", countText);
      setProgressDetail("refresh-progress-hold", holdText);
      setProgressDetail(
        "refresh-progress-product",
        hasProduct
          ? isUnderlyingLoop
            ? `${progress.underlying || "Market underlying"} - ${progress.error ? "market call failed" : "loading market data"}`
            : `${progress.product_label || "Risk product"} - ${progress.error ? "Risk & dRisk failed" : "loading Risk & dRisk"}`
          : progress.message || progress.product_label || "Refresh pipeline",
      );

      const meter = document.getElementById("refresh-progress-bar-track");
      const bar = document.getElementById("refresh-progress-bar");
      if (bar && hasProduct) bar.style.width = `${percent}%`;
      if (meter) {
        meter.hidden = !["reload", "bootstrap"].includes(refreshProgressState.mode);
        if (hasProduct) {
          meter.setAttribute("role", "progressbar");
          meter.setAttribute("aria-valuemin", "0");
          meter.setAttribute("aria-valuenow", String(progress.product_index));
          meter.setAttribute("aria-valuemax", String(progress.product_total));
          meter.setAttribute("aria-label", countText);
          meter.setAttribute(
            "aria-valuetext",
            `${progress.underlying || progress.product_label || unitLabel}, ${countText}`,
          );
        } else {
          meter.removeAttribute("role");
          meter.removeAttribute("aria-valuemin");
          meter.removeAttribute("aria-valuenow");
          meter.removeAttribute("aria-valuemax");
          meter.removeAttribute("aria-label");
          meter.removeAttribute("aria-valuetext");
        }
      }

      const title = document.getElementById("refresh-progress-title");
      if (progress.error) {
        refreshProgressState.backendError = progress.error;
        refreshProgressState.backendErrorStage = stage;
        if (title) title.textContent = progress.error;
      }
      if (!stage) return;

      const stages = REFRESH_STAGES;
      const activeIndex = stages.indexOf(stage);
      stages.forEach((candidate, index) => {
        const row = document.getElementById(`refresh-stage-${candidate}`);
        if (!row || row.classList.contains("is-skipped")) return;
        if (index < activeIndex) {
          setRefreshStageState(candidate, "complete");
          if (candidate !== "risk") configureRefreshStage(candidate, "", "Complete");
        }
        else if (index === activeIndex) setRefreshStageState(candidate, progress.error ? "error" : progress.running ? "active" : "complete");
        else setRefreshStageState(candidate, null);
        if (index !== activeIndex) {
          row.style.removeProperty("--stage-progress");
          row.removeAttribute("role");
          row.removeAttribute("aria-valuemin");
          row.removeAttribute("aria-valuenow");
          row.removeAttribute("aria-valuemax");
        }
      });

      const activeRow = document.getElementById(`refresh-stage-${stage}`);
      if (activeRow) {
        activeRow.style.setProperty("--stage-progress", `${percent}%`);
      }
      configureRefreshStage(
        stage,
        functionName,
        hasProduct ? countText : progress.running ? "Running" : "Complete",
        progress.source_type,
      );
    };

    const recoverReadyBootstrap = (progress) => {
      if (
        !refreshProgressState
        || refreshProgressState.mode !== "bootstrap"
        || Number(progress?.revision || 0) < 1
      ) return false;
      const state = refreshProgressState;
      if (state.serverReplaced) {
        // The replacement process has now published a valid revision. The
        // restart remains diagnostic history, not a terminal dashboard error.
        state.serverReplaced = false;
        state.backendError = "";
        state.backendErrorStage = null;
      }
      if (refreshProgressState.reloadRequested) return true;
      state.reloadRequested = true;
      const title = document.getElementById("refresh-progress-title");
      if (title) title.textContent = "Opening validated dashboard";
      setProgressDetail(
        "refresh-progress-function",
        "Server refresh completed; synchronising this browser",
      );
      setProgressDetail(
        "refresh-progress-product",
        "Revision is ready",
      );
      const handoffDeadline = Date.now() + 15000;
      const recoverMount = () => {
        if (!refreshProgressState || refreshProgressState !== state) return;
        if (!document.querySelector(".cube-initial-load-shell")) {
          finishRefreshProgress();
          return;
        }
        // Never interrupt Dash while it is materialising the validated tree.
        if (dashIsLoading() || Date.now() < handoffDeadline) {
          setTimeout(recoverMount, 1000);
          return;
        }
        const latestProgress = lastBackendProgress || progress;
        const bootId = String(latestProgress.server_boot_id || "unknown");
        const revision = normalizedRevision(latestProgress.revision) || 0;
        const recoveryKey = `cube-bootstrap-ready-reload:${bootId}:${revision}`;
        if (claimSessionReload(recoveryKey)) {
          window.location.reload();
          return;
        }
        setProgressDetail(
          "refresh-progress-function",
          "Dashboard handoff is still pending; polling continues without repeated reloads",
        );
        setTimeout(recoverMount, 1000);
      };
      setTimeout(recoverMount, 3000);
      return true;
    };

    const startRefreshProgress = (mode) => {
      const panel = document.getElementById("refresh-progress");
      if (!panel) return;
      setGlobalLoaderVisible(true);
      clearRefreshProgressTimers();
      const reloadAll = mode === "reload";
      const bootstrap = mode === "bootstrap";
      const portfolioOnly = mode === "portfolios";
      const commoditySetting = mode === "commo";
      const checkerSetting = mode === "checker";
      const dateSettings = mode === "dates";
      const cacheReset = mode === "reset";
      const settingsOnly = commoditySetting || checkerSetting || dateSettings;
      const fullRiskLoad = reloadAll || bootstrap || cacheReset;
      const automatic = mode === "automatic";
      const requestedFunction = bootstrap
        ? "RiskRefreshManager.refresh(initial_load)"
        : cacheReset ? "RiskRefreshManager.reset_refresh()"
        : reloadAll ? "RiskRefreshManager.refresh(force_risk=True)"
        : portfolioOnly ? "RiskRefreshManager.refresh_portfolios()"
        : commoditySetting ? "RiskRefreshManager.refresh(commodity_market)"
        : checkerSetting ? "RiskRefreshManager.refresh(risk_checker)"
        : dateSettings ? "RiskRefreshManager.refresh(forced_dates)"
        : "RiskRefreshManager.refresh(force_pl=True)";
      const requestedSource = fullRiskLoad
        ? cacheReset ? "cleared caches and all connector sources" : "all connector sources"
        : portfolioOnly ? "portfolio mapping connector only"
        : commoditySetting ? "commodity market setting"
        : checkerSetting ? "risk checker setting"
        : dateSettings ? "staged risk and market dates"
        : automatic ? "automatic 15-minute refresh" : "manual P&L refresh";
      const riskProductDelay = Number(panel.dataset.riskProductDelay || 0);
      const title = document.getElementById("refresh-progress-title");
      const elapsed = document.getElementById("refresh-progress-elapsed");
      const operationTitle = bootstrap
        ? "Loading Cube data"
        : cacheReset ? "Resetting cache"
        : reloadAll ? "Reloading all risk"
        : portfolioOnly ? "Refreshing portfolios"
        : commoditySetting ? "Updating Commo market"
        : checkerSetting ? "Updating RiskChecker"
        : dateSettings ? "Applying date settings"
        : automatic ? "Automatic refresh"
        : "Refreshing P&L";
      if (title) title.textContent = bootstrap
        ? operationTitle
        : `${operationTitle} · Current snapshot remains usable`;
      panel.hidden = false;
      panel.classList.remove("is-complete", "is-error");
      panel.classList.add("is-running");
      panel.dataset.progressSource = "pending";
      REFRESH_STAGES.forEach((stage) => {
        setRefreshStageState(stage, null);
        const row = document.getElementById(`refresh-stage-${stage}`);
        row?.style.removeProperty("--stage-progress");
        row?.removeAttribute("role");
        row?.removeAttribute("aria-valuemin");
        row?.removeAttribute("aria-valuenow");
        row?.removeAttribute("aria-valuemax");
      });
      configureRefreshStage("readiness", "get_risk_checker", portfolioOnly ? "Not called" : "queued");
      configureRefreshStage(
        "risk",
        fullRiskLoad ? requestedFunction : "Conditional on changed readiness dates",
        fullRiskLoad && riskProductDelay > 0
          ? `Risk products / ${riskProductDelay}s each`
          : fullRiskLoad ? "queued" : "Conditional",
      );
      configureRefreshStage("market", requestedFunction, "queued", requestedSource);
      configureRefreshStage("pl", requestedFunction, "queued", requestedSource);
      configureRefreshStage("final", "_commit_full_snapshot", "queued");
      setProgressDetail("refresh-progress-function", requestedFunction);
      setProgressDetail("refresh-progress-source", requestedSource);
      setProgressDetail("refresh-progress-count", "");
      setProgressDetail("refresh-progress-hold", "");
      setProgressDetail(
        "refresh-progress-product",
        portfolioOnly
          ? "Reloading portfolio mapping and rebuilding dependent views"
          : settingsOnly
            ? "Applying settings through one atomic refresh"
          : fullRiskLoad
            ? "Preparing Risk & dRisk product calls"
            : "Checking readiness before conditional risk and market/P&L refresh",
      );
      const progressBar = document.getElementById("refresh-progress-bar");
      if (progressBar) progressBar.style.width = "0%";
      const progressTrack = document.getElementById("refresh-progress-bar-track");
      if (progressTrack) progressTrack.hidden = !fullRiskLoad;
      if (portfolioOnly) {
        ["readiness", "risk", "market", "pl"].forEach((stage) => {
          setRefreshStageState(stage, "skipped");
          configureRefreshStage(stage, "", "Not called");
        });
        setRefreshStageState("final", "active");
      } else {
        setRefreshStageState("readiness", "active");
      }

      const startedAt = Date.now();
      refreshProgressState = {
        mode,
        panel,
        startedAt,
        sawRunning: false,
        sawDashRunning: false,
        dashCallbackComplete: false,
        dashStatusNode: null,
        followingExistingWriter: false,
        sawBackendRunning: false,
        sawBackendAttempt: false,
        baselineProgressKey: null,
        baselineRefreshAttemptId: lastBackendProgress?.attempt_id || null,
        baselineRevision: lastBackendProgress
          ? Number(lastBackendProgress.revision || 0)
          : null,
        baselineAttemptId: null,
        serverBootId: null,
        serverReplaced: false,
        reloadRequested: false,
        transportLostAt: null,
        backendError: "",
        backendErrorStage: null,
        initialErrorText: (refreshErrorNode()?.textContent || "").trim(),
        initialStatusText: (refreshStatusNode()?.textContent || "").trim(),
      };
      // This listener runs in the capture phase. Disabling Apply here used to
      // mutate the click target before Dash's own handler received the same
      // event. The progress hero would open, but the n_clicks request could be
      // lost, leaving no callback transition capable of closing it. Defer the
      // lock until the click has fully propagated; the Python busy Store
      // remains authoritative for the rest of the transaction.
      const stateForDateActionLock = refreshProgressState;
      setTimeout(() => {
        if (refreshProgressState !== stateForDateActionLock) return;
        if (cacheReset) {
          const clearButton = document.getElementById("clear-cache-button");
          if (clearButton) {
            clearButton.textContent = "Resetting…";
            clearButton.title = "Resetting · Reloading Risk and P&L";
          }
        }
        const setProps = window.dash_clientside?.set_props;
        ["force-risk-apply-button", "force-risk-cancel-button"].forEach((id) => {
          const action = document.getElementById(id);
          if (!action) return;
          try {
            if (typeof setProps === "function") setProps(id, { disabled: true });
            else action.disabled = true;
          } catch (_error) {
            action.disabled = true;
          }
        });
      }, 0);
      syncRefreshLifecycleNodes();
      const updateElapsed = () => {
        if (elapsed && refreshProgressState) {
          elapsed.textContent = `${Math.floor((Date.now() - startedAt) / 1000)}s elapsed`;
        }
      };
      updateElapsed();
      refreshProgressClock = setInterval(updateElapsed, 1000);
      backendProgressNextPoll = 0;
      if (bootstrap) void requestBackendStart(true);
      void requestBackendProgress(true).then((progress) => {
        if (!progress || !refreshProgressState || refreshProgressState.startedAt !== startedAt) return;
        refreshProgressState.serverBootId = progress.server_boot_id || null;
        const refreshAttemptChanged = Boolean(
          progress.attempt_id
          && refreshProgressState.baselineRefreshAttemptId
          && progress.attempt_id !== refreshProgressState.baselineRefreshAttemptId
        );
        const revisionAdvanced = (
          refreshProgressState.baselineRevision !== null
          && progress.revision > refreshProgressState.baselineRevision
        );
        const belongsToAttempt = (
          (
            bootstrap
            && Boolean(progress.startup_attempt_id)
            && progress.startup_attempt_id !== refreshProgressState.baselineAttemptId
          )
          || refreshAttemptChanged
          || revisionAdvanced
          || progressStartedDuringAttempt(progress, startedAt)
        );
        if (recoverReadyBootstrap(progress)) return;
        if (progress.running) {
          refreshProgressState.sawBackendRunning = true;
          refreshProgressState.sawBackendAttempt = true;
          renderBackendProgress(progress);
        } else if (belongsToAttempt) {
          refreshProgressState.sawBackendAttempt = true;
          renderBackendProgress(progress);
        } else {
          refreshProgressState.baselineProgressKey = progressFingerprint(progress);
          refreshProgressState.baselineRefreshAttemptId = progress.attempt_id || null;
          refreshProgressState.baselineRevision = progress.revision;
          refreshProgressState.baselineAttemptId = progress.startup_attempt_id || null;
        }
      });
  };

  const finishRefreshProgress = () => {
    if (!refreshProgressState) return;
    const panel = document.getElementById("refresh-progress");
    const title = document.getElementById("refresh-progress-title");
    const state = refreshProgressState;
    const errorText = (refreshErrorNode()?.textContent || "").trim();
    const backendError = state.backendError || "";
    const hasNewError = Boolean(backendError || (errorText && errorText !== state.initialErrorText));
    if (state.mode === "reset") {
      const clearButton = document.getElementById("clear-cache-button");
      if (clearButton) {
        clearButton.textContent = hasNewError ? "Clear Cache · Retry" : "Clear Cache";
        clearButton.title = hasNewError
          ? "Failed · Retry Clear Cache"
          : "Ready · Clear cached views and reload Risk and P&L";
      }
    }
    clearRefreshProgressTimers();
    panel?.classList.remove("is-running");
    panel?.classList.add(hasNewError ? "is-error" : "is-complete");
    const errorStage = hasNewError ? state.backendErrorStage : null;
    const stages = REFRESH_STAGES;
    stages.forEach((stage, index) => {
      const row = document.getElementById(`refresh-stage-${stage}`);
      if (row) {
        row.style.removeProperty("--stage-progress");
        row.removeAttribute("role");
        row.removeAttribute("aria-valuemin");
        row.removeAttribute("aria-valuenow");
        row.removeAttribute("aria-valuemax");
        if (stage === errorStage) {
          setRefreshStageState(stage, "error");
          configureRefreshStage(stage, "", "Failed");
        }
        else if (row.classList.contains("is-skipped")) return;
        else if (errorStage) {
          const errorIndex = stages.indexOf(errorStage);
          const completed = index < errorIndex;
          setRefreshStageState(stage, completed ? "complete" : null);
          if (completed && stage !== "risk") configureRefreshStage(stage, "", "Complete");
        } else {
          setRefreshStageState(stage, "complete");
          if (stage !== "risk") configureRefreshStage(stage, "", "Complete");
        }
      }
    });
    if (title) title.textContent = hasNewError
      ? `Refresh failed - ${backendError || "last successful data retained"}`
      : "Refresh complete";
    setProgressDetail(
      "refresh-progress-product",
      hasNewError
        ? state.serverReplaced
          ? "Server process changed; reload this page to reconnect before using refreshed data"
          : (state.mode === "bootstrap" ? "No financial snapshot was published" : "Previous validated snapshot retained")
        : "Validated snapshot is live",
    );
    setProgressDetail("refresh-progress-hold", "");
    const progressBar = document.getElementById("refresh-progress-bar");
    if (progressBar) progressBar.style.width = hasNewError ? "0%" : "100%";
    const progressTrack = document.getElementById("refresh-progress-bar-track");
    if (progressTrack) progressTrack.hidden = hasNewError || !["reload", "bootstrap", "reset"].includes(state.mode);
    refreshProgressState = null;
    setGlobalLoaderVisible(false);
    // With no last-good snapshot, the startup incident and its
    // failed stage stay visible beside Retry. Later refresh errors
    // still collapse back to the usable committed dashboard.
    if (!(hasNewError && (state.mode === "bootstrap" || state.serverReplaced))) {
      setTimeout(() => {
        if (!refreshProgressState && panel) panel.hidden = true;
      }, hasNewError ? 5000 : 300);
    }
  };

  const abandonRefreshProgress = (state) => {
    if (!state || refreshProgressState !== state) return;
    clearRefreshProgressTimers();
    refreshProgressState = null;
    setGlobalLoaderVisible(false);
  };

  const handleRefreshStatusTransition = (node) => {
    const state = refreshProgressState;
    if (!state || !node) return;
    const running = node.classList.contains("is-refreshing");
    if (running) {
      state.sawDashRunning = true;
      state.sawRunning = true;
      state.dashCallbackComplete = false;
      state.dashStatusNode = node;
      return;
    }
    if (
      state.mode === "bootstrap"
      || !state.sawDashRunning
      || state.dashStatusNode !== node
      || state.dashCallbackComplete
    ) return;

    // Dash's `running` output is applied before the request and removed only
    // after its response. Observing both class states closes the sub-second
    // race where the one-second poll never sees a fast refresh in flight.
    state.dashCallbackComplete = true;
    const statusText = (node.textContent || "").trim();
    state.followingExistingWriter = /already running; following its live progress/i
      .test(statusText);
    if (state.followingExistingWriter) {
      // This callback has ended, but another browser/task still owns the
      // financial writer. Keep following real backend progress without an
      // invented timeout or an unconfirmed success state.
      void requestBackendProgress(true).then((progress) => {
        if (!refreshProgressState || refreshProgressState !== state) return;
        if (progress?.running) {
          state.sawBackendRunning = true;
          state.sawBackendAttempt = true;
          renderBackendProgress(progress);
        } else if (progress) {
          finishRefreshProgress();
        }
      });
      return;
    }

    syncCommittedDataRevision(lastBackendProgress);
    finishRefreshProgress();
  };

  const syncRefreshStatusObserver = () => {
    const node = refreshStatusNode();
    if (node === observedRefreshStatusNode) {
      handleRefreshStatusTransition(node);
      return;
    }
    refreshStatusObserver?.disconnect();
    observedRefreshStatusNode = node;
    refreshStatusObserver = null;
    if (!node) return;
    refreshStatusObserver = new MutationObserver((mutations) => {
      if (mutations.some((mutation) => mutation.attributeName === "class")) {
        const state = refreshProgressState;
        const transitionedFromRunning = mutations.some((mutation) => (
          /(^|\s)is-refreshing(?:\s|$)/.test(mutation.oldValue || "")
        ));
        if (state && transitionedFromRunning) {
          state.sawDashRunning = true;
          state.sawRunning = true;
          state.dashStatusNode = node;
        }
        handleRefreshStatusTransition(node);
      }
    });
    refreshStatusObserver.observe(node, {
      attributes: true,
      attributeFilter: ["class"],
      attributeOldValue: true,
    });
    // Automatic refreshes can already be running when the poll first creates
    // their progress state; seed that confirmed DOM state immediately.
    handleRefreshStatusTransition(node);
  };

  syncRefreshLifecycleNodes = () => {
    syncRefreshStatusObserver();
    if (financialPageCanConsumeRevision()) {
      syncCommittedDataRevision(lastBackendProgress);
    }
    const state = refreshProgressState;
    if (!state || state.panel?.isConnected) return;
    const replacement = document.getElementById("refresh-progress");
    if (state.mode === "bootstrap") {
      // The cold shell is expected to be replaced by the validated layout.
      // Preserve bootstrap recovery and follow the newly mounted panel.
      if (replacement) state.panel = replacement;
      return;
    }
    // A normal page unmount must not leave clocks, loaders, or stale state
    // alive against a detached hero.
    abandonRefreshProgress(state);
  };
  syncRefreshLifecycleNodes();

  let refreshProgressTickRunning = false;
  const refreshProgressPoll = setInterval(async () => {
    if (refreshProgressTickRunning) return;
    refreshProgressTickRunning = true;
    try {
      syncRefreshLifecycleNodes();
      const running = refreshStatusNode()?.classList.contains("is-refreshing") || false;
      const lifecycleVisible = refreshLifecycleVisible();
      // Checking Dash's global loading tree is only useful during a
      // refresh attempt. In particular, an ordinary Risk Explorer
      // tab callback must not activate the cube loader.
      const dashLoading = (running || Boolean(refreshProgressState))
        ? dashIsLoading()
        : false;
      if (running && !refreshProgressState && lifecycleVisible) {
        const initialLoad = document.getElementById("refresh-progress")?.dataset.initialLoad === "true";
        startRefreshProgress(initialLoad ? "bootstrap" : "automatic");
      }
      setGlobalLoaderVisible(Boolean(refreshProgressState) || (running && lifecycleVisible));
      if (!refreshProgressState) return;

      if (running || dashLoading) refreshProgressState.sawRunning = true;
      const progress = await requestBackendProgress();
      if (!refreshProgressState) return;
      const statusText = (refreshStatusNode()?.textContent || "").trim();
      const statusChanged = Boolean(statusText && statusText !== refreshProgressState.initialStatusText);
      if (progress) {
        refreshProgressState.transportLostAt = null;
        const previousBootId = refreshProgressState.serverBootId;
        const serverWasReplaced = Boolean(
          previousBootId
          && progress.server_boot_id
          && previousBootId !== progress.server_boot_id
        );
        refreshProgressState.serverBootId = progress.server_boot_id || previousBootId;
        if (serverWasReplaced) {
          const previous = previousBackendProgress || {};
          const previousContext = [
            previous.stage,
            previous.source_type,
            previous.product_label || previous.underlying,
          ].filter(Boolean).join(" · ");
          refreshProgressState.sawBackendRunning = false;
          refreshProgressState.sawBackendAttempt = false;
          refreshProgressState.sawRunning = false;
          refreshProgressState.baselineProgressKey = null;
          refreshProgressState.baselineRefreshAttemptId = null;
          refreshProgressState.baselineRevision = null;
          refreshProgressState.baselineAttemptId = null;
          refreshProgressState.backendError = (
            "Server process restarted; the previous attempt ended before Python could report an error."
          );
          refreshProgressState.serverReplaced = true;
          const title = document.getElementById("refresh-progress-title");
          if (title) title.textContent = "Server process restarted during refresh";
          setProgressDetail(
            "refresh-progress-function",
            previousContext
              ? `Last confirmed work: ${previousContext}`
              : "No final Python error was available from the previous process",
          );
          setProgressDetail(
            "refresh-progress-product",
            refreshProgressState.mode === "bootstrap"
              ? "Automatic recovery will start one new process-owned attempt"
              : "Reload this page to reconnect to the replacement server process",
          );
          document.getElementById("refresh-progress")?.classList.add("is-error");
          if (refreshProgressState.mode === "bootstrap") {
            void requestBackendStart();
          }
          // Do not let the old DOM's running marker finish the newly reset
          // follower in this same tick. The next response owns recovery.
          return;
        }
        if (recoverReadyBootstrap(progress)) return;
        if (
          refreshProgressState.mode === "bootstrap"
          && Number(progress.revision || 0) === 0
          && ["", "idle"].includes(progress.startup_phase)
        ) {
          void requestBackendStart();
        }
        const isBaselineSnapshot = Boolean(
          refreshProgressState.baselineProgressKey
          && progressFingerprint(progress) === refreshProgressState.baselineProgressKey
        );
        const startupAttemptMatches = (
          refreshProgressState.mode === "bootstrap"
          && Boolean(progress.startup_attempt_id)
          && progress.startup_attempt_id !== refreshProgressState.baselineAttemptId
        );
        const refreshAttemptMatches = Boolean(
          progress.attempt_id
          && refreshProgressState.baselineRefreshAttemptId
          && progress.attempt_id !== refreshProgressState.baselineRefreshAttemptId
        );
        const revisionAdvanced = (
          refreshProgressState.baselineRevision !== null
          && progress.revision > refreshProgressState.baselineRevision
        );
        const attemptMatches = (
          startupAttemptMatches || refreshAttemptMatches || revisionAdvanced
        );
        const timestampMatchesAttempt = (
          progressStartedDuringAttempt(progress, refreshProgressState.startedAt)
          && !isBaselineSnapshot
        );
        if (progress.running) {
          refreshProgressState.sawBackendRunning = true;
          refreshProgressState.sawBackendAttempt = true;
          renderBackendProgress(progress);
        } else if (
          refreshProgressState.sawBackendAttempt
          || refreshProgressState.sawBackendRunning
          || attemptMatches
          || timestampMatchesAttempt
        ) {
          refreshProgressState.sawBackendAttempt = true;
          renderBackendProgress(progress);
          // Only the refresh callback's running state gates this
          // panel. Revision-driven table callbacks may legitimately
          // retain unrelated Dash loading markers while they render.
          if (!running) finishRefreshProgress();
        } else if (!running && !dashLoading && (refreshProgressState.sawRunning || statusChanged)) {
          if (!isBaselineSnapshot) renderBackendProgress(progress);
          finishRefreshProgress();
        }
      } else {
        const panel = document.getElementById("refresh-progress");
        if (panel) panel.dataset.progressSource = backendProgressAvailable === false ? "fallback" : "pending";
        if (backendProgressAvailable === false) {
          if (!refreshProgressState.transportLostAt) {
            refreshProgressState.transportLostAt = Date.now();
          }
          if (refreshProgressState.mode === "bootstrap") {
            void requestBackendStart();
          }
          const disconnectedFor = Date.now() - refreshProgressState.transportLostAt;
          const sinceSuccess = backendProgressLastSuccessAt
            ? `Last response ${Math.max(1, Math.floor((Date.now() - backendProgressLastSuccessAt) / 1000))}s ago.`
            : "";
          setProgressDetail(
            "refresh-progress-function",
            `Reconnecting to server progress. ${backendProgressLastError || "No JSON response."}${sinceSuccess}`,
          );
          if (disconnectedFor >= 15000) {
            const title = document.getElementById("refresh-progress-title");
            if (title) title.textContent = "Server connection interrupted - retrying";
            setProgressDetail(
              "refresh-progress-product",
              "Refresh state is not confirmed; automatic recovery is active",
            );
            panel?.classList.add("is-error");
          }
          if (
            disconnectedFor >= 45000
            && refreshProgressState.mode === "bootstrap"
          ) {
            const bootId = String(refreshProgressState.serverBootId || "unknown");
            const recoveryKey = `cube-progress-transport-reload:${bootId}`;
            if (claimSessionReload(recoveryKey)) {
              window.location.reload();
              return;
            }
            setProgressDetail(
              "refresh-progress-product",
              "Automatic reload is unavailable or already attempted; progress polling continues",
            );
          }
        }
        if (
          !refreshProgressState.followingExistingWriter
          && !running
          && !dashLoading
          && (refreshProgressState.sawRunning || statusChanged)
        ) {
          finishRefreshProgress();
        }
      }
    } finally {
      refreshProgressTickRunning = false;
    }
  }, BACKEND_PROGRESS_POLL_MS);

  const stopRefreshLifecycle = () => {
    clearRefreshProgressTimers();
    refreshProgressState = null;
    setGlobalLoaderVisible(false);
    refreshStatusObserver?.disconnect();
    refreshStatusObserver = null;
    observedRefreshStatusNode = null;
    clearInterval(refreshProgressPoll);
  };

  app.startRefreshProgress = startRefreshProgress;
  app.stopRefreshLifecycle = stopRefreshLifecycle;
})();
