/* Risk hierarchy delegation, keyboard shortcuts, and native interaction events. */
(() => {
  "use strict";

  const app = window.__rebirthV4Assets = window.__rebirthV4Assets || {};
  const {
    applyRangeSelection,
    applyTheme,
    clearSelection,
    disconnectInteractionObservers,
    finishRangeGesture,
    hideSelectionSummaries,
    isEditableClipboardTarget,
    refreshCubeRollSizes,
    registerCubeRollers,
    resetCubeRollers,
    resumeInteractionHooks,
    selectedCells,
    selectedCellsAsTsv,
    selectVisibleColumn,
    setGlobalLoaderVisible,
    setSelected,
    startRefreshProgress,
    stopCubeMotion,
    stopPlotlyTheme,
    stopRefreshLifecycle,
    stopResizeAndRiskRetry,
    stopUiHookTimers,
  } = app;
  let riskActionSequence = 0;
  let pendingRiskRowState = null;

  const hasAggregationModifier = (event) => event.shiftKey || event.ctrlKey || event.metaKey;
  const syncQuickSearchHierarchy = (table) => {
    if (!table?.matches?.(".quick-search-pivot-table")) return;
    const rows = Array.from(
      table.querySelectorAll("tbody tr.quick-search-hierarchy-row"),
    );
    const rowsByPath = new Map(
      rows.map((row) => [row.dataset.quickSearchPath, row]),
    );
    rows.forEach((row) => {
      const depth = Number(row.dataset.quickSearchDepth);
      const parent = rowsByPath.get(row.dataset.quickSearchParentPath);
      const visible = depth === 1 || Boolean(
        parent
        && !parent.hidden
        && parent.dataset.quickSearchOpen === "true"
      );
      row.hidden = !visible;

      const toggle = row.querySelector(".quick-search-hierarchy-toggle");
      if (!toggle) return;
      const expanded = row.dataset.quickSearchOpen === "true";
      const action = expanded ? "Collapse" : "Expand";
      const dimension = row.dataset.quickSearchDimension || "level";
      const label = row.dataset.quickSearchLabel || "group";
      toggle.textContent = expanded ? "\u2212" : "\u25b8";
      row.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-label", `${action} ${dimension}: ${label}`);
      toggle.title = `${action} ${dimension}: ${label}`;
    });
  };

  const toggleQuickSearchHierarchy = (toggle) => {
    if (!toggle || toggle.disabled) return false;
    const row = toggle.closest("tr.quick-search-hierarchy-row");
    const table = toggle.closest("table.quick-search-pivot-table");
    if (!row || !table) return false;
    row.dataset.quickSearchOpen = String(
      row.dataset.quickSearchOpen !== "true",
    );
    syncQuickSearchHierarchy(table);
    // Hidden descendants must never remain in spreadsheet copy or
    // aggregation state after an instantaneous client-side collapse.
    clearSelection();
    return true;
  };

  const riskActionStore = Object.freeze({
    row: "risk-row-action-store",
    cell: "risk-cell-action-store",
    metric: "risk-metric-action-store",
  });
  const publishRiskAction = (node) => {
    if (!node || node.disabled) return false;
    const isTopBookCell = node.classList.contains("top-book-metric-cell-button");
    const isTopBookRow = node.classList.contains("row-toggle")
      && Boolean(node.closest("#top-book-grid"));
    const kind = node.classList.contains("row-toggle")
      ? "row"
      : node.classList.contains("metric-header-button")
        ? "metric"
        : node.classList.contains("metric-cell-button")
          ? "cell"
          : null;
    const storeId = isTopBookCell
      ? "top-book-cell-action-store"
      : isTopBookRow
        ? "top-book-row-action-store"
        : riskActionStore[kind];
    const setProps = window.dash_clientside?.set_props;
    if (!storeId || typeof setProps !== "function") return false;
    const viewRoot = node.closest("[data-risk-view-token]");
    const viewToken = viewRoot?.dataset.riskViewToken;
    if (!viewToken && !isTopBookCell) return false;

    riskActionSequence += 1;
    const action = {
      kind,
      sequence: riskActionSequence,
    };
    if (viewToken) action.view_token = viewToken;
    const nodeRiskKey = node.dataset.riskKey
      ?? node.closest("tr")?.dataset.riskKey;
    if (kind === "row") {
      action.source = node.dataset.riskSource
        || (isTopBookRow
          ? "top-book-row-toggle"
          : node.closest("#alt-risk-grid")
            ? "alt-row-toggle"
            : "main-row-toggle");
      const renderedRows = viewRoot.dataset.riskOpenRows || "[]";
      if (
        !pendingRiskRowState
        || pendingRiskRowState.viewToken !== viewToken
        || pendingRiskRowState.renderedRows !== renderedRows
      ) {
        let parsedRows = [];
        try {
          const value = JSON.parse(renderedRows);
          if (Array.isArray(value) && value.every((item) => typeof item === "string")) {
            parsedRows = value;
          }
        } catch (_error) {
          parsedRows = [];
        }
        pendingRiskRowState = {
          viewToken,
          renderedRows,
          rows: new Set(parsedRows),
        };
      }
      const key = nodeRiskKey;
      if (!key) return false;
      if (pendingRiskRowState.rows.has(key)) pendingRiskRowState.rows.delete(key);
      else pendingRiskRowState.rows.add(key);
      action.open_rows = Array.from(pendingRiskRowState.rows).sort();
    } else if (kind === "cell") {
      action.source = node.dataset.riskSource
        || (isTopBookCell
          ? "top-book-risk-cell"
          : node.classList.contains("credit-measure-cell-button")
            ? "credit-risk-cell"
            : node.closest("#alt-risk-grid")
              ? "alt-risk-cell"
              : "main-risk-cell");
    }
    if (nodeRiskKey !== undefined) action.key = nodeRiskKey;
    if (node.dataset.riskMetric !== undefined) action.metric = node.dataset.riskMetric;
    if (node.dataset.riskMeasure !== undefined) action.measure = node.dataset.riskMeasure;
    setProps(storeId, { data: action });
    return true;
  };
  const metricCellFromTarget = (target) => {
    if (target?.closest?.(".row-toggle, .aggregate-row-toggle")) return null;
    return target?.closest?.(
      ".risk-table tbody td.metric-cell, .risk-table tbody th.index-cell, "
      + ".cell-selection-table tbody td.metric-cell, "
      + ".cell-selection-table tbody th.index-cell, "
      + ".cell-selection-table tbody th.aggregate-index"
    ) || null;
  };

  document.addEventListener("keydown", (event) => {
    const readonlyRadio = event.target?.closest?.(
      ".aggregate-pl-selector input[type='radio'][readonly], .table-dimension-selector input[type='radio'][readonly]"
    );
    if (readonlyRadio && ["Enter", " ", "ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(event.key)) {
      event.preventDefault();
      event.stopPropagation();
      if (event.key === "Enter" || event.key === " ") {
        readonlyRadio.click();
        return;
      }
      const group = readonlyRadio.closest(".aggregate-pl-selector, .table-dimension-selector");
      const radios = Array.from(group?.querySelectorAll("input[type='radio'][readonly]:not(:disabled)") || []);
      const current = radios.indexOf(readonlyRadio);
      if (current < 0 || radios.length < 2) return;
      const direction = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : -1;
      const target = radios[(current + direction + radios.length) % radios.length];
      target.focus();
      target.click();
      return;
    }

    const isF9 = event.code === "F9" || event.key === "F9";
    if (isF9 && event.shiftKey && !event.repeat) {
      const refreshButton = document.getElementById("refresh-pl-button");
      if (!refreshButton || refreshButton.disabled) return;
      event.preventDefault();
      event.stopPropagation();
      refreshButton.click();
      return;
    }

    const isF8 = event.code === "F8" || event.key === "F8";
    if (isF8 && event.shiftKey && !event.repeat) {
      const riskButton = document.getElementById("reload-risk-button");
      if (!riskButton || riskButton.disabled) return;
      event.preventDefault();
      event.stopPropagation();
      riskButton.click();
      return;
    }

    if (event.key === "Escape" && selectedCells.size) {
      event.preventDefault();
      clearSelection();
      return;
    }

    const cell = metricCellFromTarget(event.target);
    if (!cell || !hasAggregationModifier(event) || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    setSelected(cell, !selectedCells.has(cell));
    app.suppressedMetricClick = {
      cells: new Set([cell]),
      expires: Number.POSITIVE_INFINITY,
      keyboardOnly: true,
    };
  }, true);

  document.addEventListener("keyup", (event) => {
    if (
      (event.key !== "Enter" && event.key !== " ")
      || !app.suppressedMetricClick?.keyboardOnly
    ) return;
    const pendingSuppression = app.suppressedMetricClick;
    setTimeout(() => {
      if (app.suppressedMetricClick === pendingSuppression) app.suppressedMetricClick = null;
    }, 0);
  }, true);

  document.addEventListener("copy", (event) => {
    if (!selectedCells.size || isEditableClipboardTarget(event.target)) return;
    const text = selectedCellsAsTsv();
    if (!text || !event.clipboardData) return;
    event.clipboardData.setData("text/plain", text);
    event.clipboardData.setData("text/tab-separated-values", text);
    event.preventDefault();
    hideSelectionSummaries();
  }, true);

  document.addEventListener("click", (event) => {
    const themeButton = event.target.closest("#theme-toggle");
    if (themeButton) {
      event.preventDefault();
      if (selectedCells.size) clearSelection();
      app.activeTheme = applyTheme(
        app.activeTheme === "dark" ? "light" : "dark",
        true,
        true,
      );
      return;
    }

    const quickSearchToggle = event.target.closest(
      ".quick-search-hierarchy-toggle",
    );
    if (quickSearchToggle) {
      event.preventDefault();
      event.stopImmediatePropagation();
      toggleQuickSearchHierarchy(quickSearchToggle);
      return;
    }

    const aggregationCell = metricCellFromTarget(event.target);
    const selectionHeader = event.target.closest(
      ".risk-table thead th.metric-header, .risk-table thead th.index-header, "
      + ".cell-selection-table thead th.metric-header, .cell-selection-table thead th.index-header"
    );
    if (
      selectedCells.size
      && !aggregationCell
      && !event.target.closest(".selection-summary")
      && !(selectionHeader && hasAggregationModifier(event))
    ) {
      clearSelection();
    }
    const matchesSuppressedCell = aggregationCell
      && app.suppressedMetricClick
      && app.suppressedMetricClick.expires > Date.now()
      && (!app.suppressedMetricClick.keyboardOnly || event.detail === 0)
      && app.suppressedMetricClick.cells.has(aggregationCell);
    if (aggregationCell && (hasAggregationModifier(event) || matchesSuppressedCell)) {
      event.preventDefault();
      event.stopImmediatePropagation();
      app.suppressedMetricClick = null;
      return;
    }
    if (aggregationCell) app.suppressedMetricClick = null;
    if (aggregationCell?.closest(".cell-selection-table")) {
      event.preventDefault();
      clearSelection(false);
      setSelected(aggregationCell, true);
      return;
    }

    // Risk Explorer tables can contain hundreds of interactive
    // controls. They deliberately have no Dash pattern IDs: one
    // delegated event publishes a compact action through a stable
    // Store, so replacing a hierarchy does not remount hundreds of
    // callback endpoints. Modifier gestures remain reserved for
    // spreadsheet-style selection and are handled below.
    const riskAction = event.target.closest(
      "#risk-grid .row-toggle, "
      + "#risk-grid .metric-cell-button[data-risk-metric], "
      + "#risk-grid .metric-header-button[data-risk-metric], "
      + "#alt-risk-grid .row-toggle, "
      + "#alt-risk-grid .metric-cell-button[data-risk-metric], "
      + "#top-book-grid .row-toggle, "
      + "#top-book-grid .top-book-metric-cell-button[data-risk-metric]"
    );
    if (riskAction && !(selectionHeader && hasAggregationModifier(event))) {
      event.preventDefault();
      if (publishRiskAction(riskAction)) return;
    }

    const refreshTrigger = event.target.closest(
      "#refresh-portfolios-button, #refresh-pl-button, #reload-risk-button, "
      + "#commo-market-toggle, #risk-checker-toggle, #force-risk-apply-button, "
      + "#clear-cache-button, #initial-load-retry"
    );
    if (refreshTrigger) {
      const mode = refreshTrigger.id === "reload-risk-button"
        ? "reload"
        : refreshTrigger.id === "refresh-portfolios-button" ? "portfolios"
        : refreshTrigger.id === "commo-market-toggle" ? "commo"
        : refreshTrigger.id === "risk-checker-toggle" ? "checker"
        : refreshTrigger.id === "force-risk-apply-button" ? "dates"
        : refreshTrigger.id === "clear-cache-button" ? "reset"
        : refreshTrigger.id === "initial-load-retry" ? "bootstrap" : "pl";
      startRefreshProgress(mode);
    }
    const header = event.target.closest(
      ".risk-table thead th.metric-header, .risk-table thead th.index-header, "
      + ".cell-selection-table thead th.metric-header, .cell-selection-table thead th.index-header"
    );
    if (!header || !(event.ctrlKey || event.metaKey || event.shiftKey)) return;
    const metric = header.dataset.metric;
    if (!metric) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    selectVisibleColumn(
      metric,
      event.ctrlKey || event.metaKey || event.shiftKey,
      header.closest(".risk-table, .cell-selection-table")
    );
  }, true);

  document.addEventListener("mousedown", (event) => {
    const cell = metricCellFromTarget(event.target);
    if (!cell || event.button !== 0) return;
    const append = hasAggregationModifier(event);
    if (!append && selectedCells.size) clearSelection();
    if (append) event.preventDefault();
    app.rangeGesture = {
      start: cell,
      end: cell,
      append,
      base: append ? new Set(selectedCells) : new Set(),
      moved: false,
      toggleSingle: !event.shiftKey && (event.ctrlKey || event.metaKey),
    };
    if (append) applyRangeSelection(app.rangeGesture, cell);
  }, true);

  document.addEventListener("mouseover", (event) => {
    if (!app.rangeGesture) return;
    const cell = metricCellFromTarget(event.target);
    if (!cell || cell.closest(".risk-table, .cell-selection-table") !== app.rangeGesture.start.closest(".risk-table, .cell-selection-table")) return;
    if (cell !== app.rangeGesture.end) {
      event.preventDefault();
      app.rangeGesture.end = cell;
      app.rangeGesture.moved = app.rangeGesture.moved || cell !== app.rangeGesture.start;
      document.body.classList.toggle("is-range-selecting", app.rangeGesture.moved);
      applyRangeSelection(app.rangeGesture, cell);
    }
  }, true);

  document.addEventListener("mousemove", (event) => {
    if (!app.rangeGesture) return;
    const cell = metricCellFromTarget(event.target);
    if (!cell || cell.closest(".risk-table, .cell-selection-table") !== app.rangeGesture.start.closest(".risk-table, .cell-selection-table")) return;
    if (cell !== app.rangeGesture.end) {
      event.preventDefault();
      app.rangeGesture.end = cell;
      app.rangeGesture.moved = app.rangeGesture.moved || cell !== app.rangeGesture.start;
      document.body.classList.toggle("is-range-selecting", app.rangeGesture.moved);
      applyRangeSelection(app.rangeGesture, cell);
    }
  }, true);

  document.addEventListener("mouseup", finishRangeGesture, true);
  window.addEventListener("blur", () => {
    finishRangeGesture();
    app.suppressedMetricClick = null;
    hideSelectionSummaries();
  });
  document.addEventListener("visibilitychange", () => {
    if (document.getElementById("data-page")) {
      const setProps = window.dash_clientside?.set_props;
      try {
        if (typeof setProps === "function") {
          setProps("data-player-visibility-store", {
            data: { hidden: document.hidden, sequence: Date.now() },
          });
        }
      } catch (_error) {
        // Navigation may unmount the Data page during this browser event.
      }
    }
    resetCubeRollers();
  });
  window.addEventListener("pagehide", (event) => {
    if (event.persisted) return;
    stopCubeMotion();
    stopResizeAndRiskRetry();
    stopPlotlyTheme();
    stopUiHookTimers();
    stopRefreshLifecycle();
    disconnectInteractionObservers();
  });
  window.addEventListener("pageshow", (event) => {
    if (!event.persisted) return;
    resetCubeRollers();
    resumeInteractionHooks();
  });

  document.addEventListener("DOMContentLoaded", () => {
    app.activeTheme = applyTheme(app.activeTheme);
    registerCubeRollers();
    resumeInteractionHooks();
  });
  window.addEventListener("load", () => {
    resumeInteractionHooks();
  });
  window.addEventListener("resize", () => {
    refreshCubeRollSizes();
  });

})();
