/* Generic native-table selection, copy, resize, and UI hook discovery. */
(() => {
  "use strict";

  const app = window.__rebirthV4Assets = window.__rebirthV4Assets || {};
  const {
    applyTheme,
    registerCubeRollers,
    savedTheme,
    schedulePlotlyTheme,
    updateThemeButton,
  } = app;
  const selectedCells = new Set();
  let selectionSummaryTimer = null;
  const SELECTION_SUMMARY_TIMEOUT_MS = 4000;
  app.selectedCells = selectedCells;
  app.rangeGesture = null;
  app.suppressedMetricClick = null;

  const numberFromCell = (cell) => {
    const raw = (
      cell.dataset.copyValue
      ?? cell.querySelector(".copy-value, .metric-cell-button")?.textContent
      ?? ""
    ).replace(/[$£€¥,\s]/g, "");
    if (!raw) return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  };

  const formatNumber = (value, decimals, minimumDecimals = decimals) => {
    return value.toLocaleString(undefined, {
      minimumFractionDigits: minimumDecimals,
      maximumFractionDigits: decimals,
    });
  };

  const setSelected = (cell, selected, update = true) => {
    if (!cell) return;
    if (selected) {
      selectedCells.add(cell);
      cell.classList.add("risk-cell-selected");
    } else {
      selectedCells.delete(cell);
      cell.classList.remove("risk-cell-selected");
    }
    if (update) updateSelectionSummary();
  };

  const clearSelection = (update = true) => {
    selectedCells.forEach((cell) => cell.classList.remove("risk-cell-selected"));
    selectedCells.clear();
    if (update) updateSelectionSummary();
  };

  const hideSelectionSummaries = (clearText = false) => {
    if (selectionSummaryTimer) clearTimeout(selectionSummaryTimer);
    selectionSummaryTimer = null;
    document.querySelectorAll(".selection-summary").forEach((box) => {
      box.classList.remove("is-visible");
      if (clearText) box.textContent = "";
    });
  };

  const scheduleSelectionSummaryDismiss = () => {
    if (selectionSummaryTimer) clearTimeout(selectionSummaryTimer);
    selectionSummaryTimer = setTimeout(() => {
      selectionSummaryTimer = null;
      document.querySelectorAll(".selection-summary").forEach((box) => {
        box.classList.remove("is-visible");
      });
    }, SELECTION_SUMMARY_TIMEOUT_MS);
  };

  const updateSelectionSummary = () => {
    for (const cell of Array.from(selectedCells)) {
      if (!document.body.contains(cell) || cell.closest("tr")?.hidden) {
        selectedCells.delete(cell);
        cell.classList.remove("risk-cell-selected");
      }
    }
    hideSelectionSummaries(true);
    const selectionsByWrap = new Map();
    selectedCells.forEach((cell) => {
      const wrap = cell.closest(".risk-table-wrap");
      const metric = cell.dataset.metric || "value";
      const value = numberFromCell(cell);
      if (!wrap || value === null) return;
      if (!selectionsByWrap.has(wrap)) selectionsByWrap.set(wrap, { metrics: new Set(), values: [] });
      const selection = selectionsByWrap.get(wrap);
      selection.metrics.add(metric);
      selection.values.push(value);
    });
    selectionsByWrap.forEach(({ metrics, values }, wrap) => {
      const box = wrap.querySelector(".selection-summary");
      if (!box) return;
      const sum = values.reduce((total, value) => total + value, 0);
      const average = sum / values.length;
      const minimum = Math.min(...values);
      const maximum = Math.max(...values);
      const baseMetrics = Array.from(metrics, (metric) => metric.toLowerCase().split(":", 1)[0]);
      const decimals = baseMetrics.some((metric) => metric === "move")
        ? 6
        : baseMetrics.some((metric) => metric === "open" || metric === "current")
          ? 4
          : 2;
      const label = metrics.size === 1 ? Array.from(metrics)[0] : "Selection";
      box.textContent = `${label} | Count ${values.length} · Sum ${formatNumber(sum, decimals, 0)} · Average ${formatNumber(average, decimals, 0)} · Min ${formatNumber(minimum, decimals, 0)} · Max ${formatNumber(maximum, decimals, 0)} · Ctrl/Cmd+C to copy · Esc to clear`;
      box.classList.add("is-visible");
    });
    if (selectionsByWrap.size) scheduleSelectionSummaryDismiss();
  };

  const clipboardValueFromCell = (cell) => {
    if (!cell) return "";
    const explicitValue = cell.dataset.copyValue;
    let displayed = explicitValue === undefined
      ? (cell.querySelector(".copy-value, .row-label-text, .metric-cell-button")?.textContent || "").trim()
      : explicitValue.trim();
    if (!displayed) {
      const copy = cell.cloneNode(true);
      copy.querySelectorAll("button, .promotion-badge").forEach((node) => node.remove());
      displayed = (copy.textContent || "").trim();
    }
    if (!displayed) return "";
    const normalized = displayed
      .replace(/\u2212/g, "-")
      .replace(/[$£€¥,\s]/g, "");
    return normalized && Number.isFinite(Number(normalized))
      ? normalized
      : displayed.replace(/[\t\r\n]+/g, " ");
  };

  const selectedCellsAsTsv = () => {
    const selected = new Set(
      Array.from(selectedCells).filter(
        (cell) => document.body.contains(cell) && !cell.closest("tr")?.hidden,
      ),
    );
    if (!selected.size) return "";
    return Array.from(document.querySelectorAll(".risk-table, .cell-selection-table"))
      .map((table) => {
        const tableCells = Array.from(selected).filter(
          (cell) => cell.closest(".risk-table, .cell-selection-table") === table,
        );
        if (!tableCells.length) return null;
        const rowIndexes = tableCells.map((cell) => cell.parentElement?.rowIndex);
        const columnIndexes = tableCells.map((cell) => cell.cellIndex);
        const rowMin = Math.min(...rowIndexes);
        const rowMax = Math.max(...rowIndexes);
        const columnMin = Math.min(...columnIndexes);
        const columnMax = Math.max(...columnIndexes);
        const cellByPosition = new Map(
          tableCells.map((cell) => [
            `${cell.parentElement?.rowIndex}:${cell.cellIndex}`,
            cell,
          ]),
        );
        const visibleRowIndexes = Array.from(
          table.querySelectorAll("tbody tr"),
        ).filter((row) => (
          !row.hidden
          && row.rowIndex >= rowMin
          && row.rowIndex <= rowMax
        )).map((row) => row.rowIndex);
        const rows = [];
        for (const row of visibleRowIndexes) {
          const values = [];
          for (let column = columnMin; column <= columnMax; column += 1) {
            values.push(
              clipboardValueFromCell(cellByPosition.get(`${row}:${column}`)),
            );
          }
          rows.push(values.join("\t"));
        }
        return rows.join("\r\n");
      })
      .filter(Boolean)
      .join("\r\n\r\n");
  };

  const isEditableClipboardTarget = (target) => Boolean(
    target?.closest?.(
      "input, textarea, [contenteditable]:not([contenteditable='false'])",
    ),
  );

  const cellsInRectangle = (start, end) => {
    const table = start?.closest?.(".risk-table, .cell-selection-table");
    if (!table || end?.closest?.(".risk-table, .cell-selection-table") !== table) return [];
    const startRow = start.parentElement?.rowIndex;
    const endRow = end.parentElement?.rowIndex;
    if (!Number.isInteger(startRow) || !Number.isInteger(endRow)) return [];
    const rowMin = Math.min(startRow, endRow);
    const rowMax = Math.max(startRow, endRow);
    const columnMin = Math.min(start.cellIndex, end.cellIndex);
    const columnMax = Math.max(start.cellIndex, end.cellIndex);
    return Array.from(table.querySelectorAll(
      "tbody td.metric-cell, tbody th.index-cell, tbody th.aggregate-index",
    )).filter((cell) => {
      const row = cell.parentElement?.rowIndex;
      return !cell.parentElement?.hidden
        && Number.isInteger(row)
        && row >= rowMin
        && row <= rowMax
        && cell.cellIndex >= columnMin
        && cell.cellIndex <= columnMax
        && clipboardValueFromCell(cell) !== "";
    });
  };

  const applyRangeSelection = (gesture, end) => {
    clearSelection(false);
    gesture.base.forEach((cell) => {
      if (document.body.contains(cell)) setSelected(cell, true, false);
    });
    cellsInRectangle(gesture.start, end).forEach((cell) => setSelected(cell, true, false));
    updateSelectionSummary();
  };

  const finishRangeGesture = () => {
    if (!app.rangeGesture) return;
    if (!app.rangeGesture.moved && app.rangeGesture.toggleSingle) {
      clearSelection(false);
      app.rangeGesture.base.forEach((cell) => {
        if (document.body.contains(cell)) setSelected(cell, true, false);
      });
      setSelected(
        app.rangeGesture.start,
        !app.rangeGesture.base.has(app.rangeGesture.start),
        false,
      );
      updateSelectionSummary();
    }
    if (app.rangeGesture.moved || app.rangeGesture.append) {
      app.suppressedMetricClick = {
        cells: new Set([app.rangeGesture.start, app.rangeGesture.end]),
        expires: Date.now() + 250,
      };
    }
    app.rangeGesture = null;
    document.body.classList.remove("is-range-selecting");
  };

  const selectVisibleColumn = (metric, append, table) => {
    if (!table) return;
    if (!append) clearSelection(false);
    table.querySelectorAll(
      "tbody td.metric-cell, tbody th.index-cell, tbody th.aggregate-index",
    ).forEach((cell) => {
      if (
        !cell.closest("tr")?.hidden
        && cell.dataset.metric === metric
        && clipboardValueFromCell(cell) !== ""
      ) {
        setSelected(cell, true, false);
      }
      });
      updateSelectionSummary();
    };

    const riskTablesWithin = (scope) => {
      const tables = [];
      if (scope?.matches?.(".risk-table")) tables.push(scope);
      scope?.querySelectorAll?.(".risk-table").forEach((table) => tables.push(table));
      return tables;
    };

    const attachResizeHandles = (scope = document) => {
      riskTablesWithin(scope).forEach((table) => table.querySelectorAll("thead th").forEach((header, index) => {
        if (Array.from(header.children).some((child) => child.classList.contains("col-resize-handle"))) return;
        const handle = document.createElement("span");
        handle.className = "col-resize-handle";
        handle.tabIndex = 0;
        handle.setAttribute("role", "separator");
        handle.setAttribute("aria-orientation", "vertical");
        handle.setAttribute("aria-label", `Resize column ${header.textContent.trim() || index + 1}`);
        handle.title = "Drag or use arrow keys to resize; double-click to reset";
        header.appendChild(handle);
        const resizeColumn = (width) => {
          table.querySelectorAll(`tr > *:nth-child(${index + 1})`).forEach((cell) => {
            cell.style.width = `${width}px`;
            cell.style.minWidth = `${width}px`;
            cell.style.maxWidth = `${width}px`;
          });
        };
        handle.addEventListener("mousedown", (event) => {
          event.preventDefault();
          event.stopPropagation();
          const startX = event.clientX;
          const startWidth = header.getBoundingClientRect().width;

          const onMove = (moveEvent) => {
            const width = Math.max(82, startWidth + moveEvent.clientX - startX);
            resizeColumn(width);
          };

          const onUp = () => {
            document.removeEventListener("mousemove", onMove, true);
            document.removeEventListener("mouseup", onUp, true);
          };

          document.addEventListener("mousemove", onMove, true);
          document.addEventListener("mouseup", onUp, true);
        });
        handle.addEventListener("keydown", (event) => {
          if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
          event.preventDefault();
          const step = event.shiftKey ? 24 : 8;
          const direction = event.key === "ArrowRight" ? 1 : -1;
          resizeColumn(Math.max(82, header.getBoundingClientRect().width + direction * step));
        });
        handle.addEventListener("dblclick", () => {
          table.querySelectorAll(`tr > *:nth-child(${index + 1})`).forEach((cell) => {
            cell.style.removeProperty("width");
            cell.style.removeProperty("min-width");
            cell.style.removeProperty("max-width");
          });
        });
      }));
    };

    let uiHookTimer = null;
    // Assigned by the refresh controller below. Keeping DOM discovery in the
    // existing observer avoids adding another document-wide MutationObserver.
    if (typeof app.syncRefreshLifecycleNodes !== "function") app.syncRefreshLifecycleNodes = () => {};
    const syncUiHooks = () => {
      if (uiHookTimer) clearTimeout(uiHookTimer);
      uiHookTimer = setTimeout(() => {
        uiHookTimer = null;
        document.body.dataset.theme = app.activeTheme;
        updateThemeButton(app.activeTheme);
      }, 30);
    };

    let cubeHookTimer = null;
    const scheduleCubeRegistration = () => {
      if (cubeHookTimer) clearTimeout(cubeHookTimer);
      cubeHookTimer = setTimeout(() => {
        cubeHookTimer = null;
        registerCubeRollers();
      }, 30);
    };

    const uiHookObserver = new MutationObserver((mutations) => {
      let themeButtonAdded = false;
      let cubeAdded = false;
      let refreshLifecycleChanged = false;
      const plotlyGraphsAdded = new Set();
      const inspectHook = (element) => {
        if (element.matches?.("#theme-toggle")) themeButtonAdded = true;
        if (element.matches?.(".cube-motion")) cubeAdded = true;
        if (element.matches?.(".js-plotly-plot")) plotlyGraphsAdded.add(element);
        if (
          element.matches?.("#refresh-status, #bootstrap-refresh-status, #refresh-progress")
          || element.querySelector?.("#refresh-status, #bootstrap-refresh-status, #refresh-progress")
        ) refreshLifecycleChanged = true;
      };

      mutations.forEach((mutation) => {
        Array.from(mutation.addedNodes).forEach((node) => {
          if (node.nodeType !== 1) return;
          inspectHook(node);
          node.querySelectorAll?.("#theme-toggle, .cube-motion, .js-plotly-plot")
            .forEach(inspectHook);
        });
        Array.from(mutation.removedNodes).forEach((node) => {
          if (node.nodeType === 1) inspectHook(node);
        });
      });

      if (themeButtonAdded) syncUiHooks();
      if (cubeAdded) scheduleCubeRegistration();
      if (refreshLifecycleChanged) app.syncRefreshLifecycleNodes();
      if (plotlyGraphsAdded.size)
        schedulePlotlyTheme(app.activeTheme, plotlyGraphsAdded, 40);
    });
    uiHookObserver.observe(document.body, { childList: true, subtree: true });
    syncUiHooks();
    scheduleCubeRegistration();
    const initialPlotlyGraphs = document.querySelectorAll(".js-plotly-plot");
    if (initialPlotlyGraphs.length) {
      schedulePlotlyTheme(app.activeTheme, initialPlotlyGraphs, 40);
    }

    const systemThemeQuery = window.matchMedia?.("(prefers-color-scheme: dark)");
    systemThemeQuery?.addEventListener?.("change", (event) => {
      if (savedTheme()) return;
      app.activeTheme = applyTheme(event.matches ? "dark" : "light", false, true);
    });

    const pendingResizeScopes = new Set();
    let resizeRefreshFrame = null;
    const scheduleResizeRefresh = (scope = document) => {
      pendingResizeScopes.add(scope);
      if (resizeRefreshFrame !== null) return;
      resizeRefreshFrame = requestAnimationFrame(() => {
        resizeRefreshFrame = null;
        pendingResizeScopes.forEach((pendingScope) => {
          if (pendingScope === document || pendingScope?.isConnected) {
            attachResizeHandles(pendingScope);
          }
        });
        pendingResizeScopes.clear();
        updateSelectionSummary();
      });
    };

    // The two hierarchy output nodes are stable Dash components.  A
    // scoped observer on each is enough to enhance a replacement table;
    // observing every mutation under document.body caused thousands of
    // callbacks while React mounted an IR hierarchy.
    const riskGridObservers = new Map();
    let riskGridObserverAttempts = 0;
    let riskGridObserverRetry = null;

    const connectRiskGridObservers = () => {
      riskGridObserverRetry = null;
      ["risk-grid", "alt-risk-grid"].forEach((id) => {
        const grid = document.getElementById(id);
        if (!grid || riskGridObservers.has(grid)) return;
        const observer = new MutationObserver((mutations) => {
          const tableChanged = mutations.some((mutation) => Array.from(mutation.addedNodes).some((node) => {
            if (node.nodeType !== 1 || node.matches?.(".col-resize-handle")) return false;
            return Boolean(
              node.matches?.(".risk-table")
              || node.closest?.(".risk-table")
              || node.querySelector?.(".risk-table")
            );
          }));
          if (tableChanged) scheduleResizeRefresh(grid);
        });
        observer.observe(grid, { childList: true, subtree: true });
        riskGridObservers.set(grid, observer);
        scheduleResizeRefresh(grid);
      });

      riskGridObserverAttempts += 1;
      if (riskGridObservers.size < 2 && riskGridObserverAttempts < 40) {
        riskGridObserverRetry = setTimeout(connectRiskGridObservers, 100);
      }
    };
    connectRiskGridObservers();

  const stopResizeAndRiskRetry = () => {
    if (resizeRefreshFrame !== null) cancelAnimationFrame(resizeRefreshFrame);
    if (riskGridObserverRetry) clearTimeout(riskGridObserverRetry);
  };

  const stopUiHookTimers = () => {
    if (uiHookTimer) clearTimeout(uiHookTimer);
    if (cubeHookTimer) clearTimeout(cubeHookTimer);
  };

  const disconnectInteractionObservers = () => {
    riskGridObservers.forEach((observer) => observer.disconnect());
    riskGridObservers.clear();
    uiHookObserver.disconnect();
  };

  const resumeInteractionHooks = () => {
    connectRiskGridObservers();
    syncUiHooks();
  };

  Object.assign(app, {
    applyRangeSelection,
    clearSelection,
    disconnectInteractionObservers,
    finishRangeGesture,
    hideSelectionSummaries,
    isEditableClipboardTarget,
    resumeInteractionHooks,
    scheduleResizeRefresh,
    selectedCellsAsTsv,
    selectVisibleColumn,
    setSelected,
    stopResizeAndRiskRetry,
    stopUiHookTimers,
  });
})();
