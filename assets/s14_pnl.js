/* P&L native DataTable range-selection bridge. */
(() => {
  "use strict";

  let gesture = null;
  let suppressTrustedClickUntil = 0;

  const syncValidateHierarchy = (table) => {
    if (!table?.matches?.(".validate-pl-table")) return;
    const rows = Array.from(
      table.querySelectorAll("tbody tr.validate-pl-hierarchy-row"),
    );
    const rowsByPath = new Map(
      rows.map((row) => [row.dataset.validatePath, row]),
    );
    rows.forEach((row) => {
      const depth = Number(row.dataset.validateDepth);
      const parent = rowsByPath.get(row.dataset.validateParentPath);
      row.hidden = depth > 0 && !Boolean(
        parent
        && !parent.hidden
        && parent.dataset.validateOpen === "true"
      );

      const toggle = row.querySelector(".validate-pl-row-toggle");
      if (!toggle) return;
      const expanded = row.dataset.validateOpen === "true";
      const label = row.querySelector(".row-label-text")?.textContent?.trim()
        || "row";
      const action = expanded ? "Collapse" : "Expand";
      toggle.textContent = expanded ? "\u2212" : "\u25b8";
      row.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-label", `${action} ${label}`);
      toggle.title = `${action} ${label}`;
    });
  };

  const toggleValidateHierarchy = (toggle) => {
    if (!toggle || toggle.disabled) return false;
    const row = toggle.closest("tr.validate-pl-hierarchy-row");
    const table = toggle.closest("table.validate-pl-table");
    if (!row || !table) return false;
    const opening = row.dataset.validateOpen !== "true";
    row.dataset.validateOpen = String(opening);
    if (!opening) {
      const rows = Array.from(
        table.querySelectorAll("tbody tr.validate-pl-hierarchy-row"),
      );
      const rowsByPath = new Map(
        rows.map((candidate) => [candidate.dataset.validatePath, candidate]),
      );
      rows.forEach((candidate) => {
        let parent = rowsByPath.get(candidate.dataset.validateParentPath);
        while (parent) {
          if (parent === row) {
            candidate.dataset.validateOpen = "false";
            break;
          }
          parent = rowsByPath.get(parent.dataset.validateParentPath);
        }
      });
    }
    syncValidateHierarchy(table);
    window.__rebirthV4Assets?.clearSelection?.();
    return true;
  };

  const cellFromTarget = (target) =>
    target?.closest?.(".pl-send-editor-table td.dash-cell") || null;

  const cellCenter = (cell) => {
    const rect = cell.getBoundingClientRect();
    return {
      clientX: rect.left + (rect.width / 2),
      clientY: rect.top + (rect.height / 2),
    };
  };

  const dispatchNativeSelectionClick = (cell, shiftKey) => {
    const point = cellCenter(cell);
    cell.dispatchEvent(new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      view: window,
      button: 0,
      shiftKey,
      ...point,
    }));
  };

  const cancelGesture = () => {
    gesture = null;
    document.body.classList.remove("is-pl-datatable-range-dragging");
  };

  const clearSelection = (table) => {
    if (!table?.id) return;
    if (table.querySelectorAll("td.cell--selected").length < 2) return;
    document.getElementById(`${table.id}-selection-clear`)?.click();
  };

  const clearOtherSelections = (keptTable = null) => {
    document.querySelectorAll(
      ".pl-send-editor-table .dash-table-container[id]",
    ).forEach((table) => {
      if (table !== keptTable) clearSelection(table);
    });
  };

  document.addEventListener("mousedown", (event) => {
    const cell = cellFromTarget(event.target);
    if (!cell || event.button !== 0) {
      if (!event.target?.closest?.(".pl-editor-selection-summary")) {
        clearOtherSelections();
      }
      return;
    }
    const table = cell.closest(".dash-table-container");
    clearOtherSelections(table);
    gesture = {
      start: cell,
      end: cell,
      table,
      startX: event.clientX,
      startY: event.clientY,
      moved: false,
    };
  }, true);

  document.addEventListener("mousemove", (event) => {
    if (!gesture) return;
    const cell = cellFromTarget(event.target);
    if (!cell || cell.closest(".dash-table-container") !== gesture.table) return;
    const distance = Math.hypot(
      event.clientX - gesture.startX,
      event.clientY - gesture.startY,
    );
    if (distance < 6 && cell === gesture.start) return;
    gesture.moved = true;
    gesture.end = cell;
    document.body.classList.add("is-pl-datatable-range-dragging");
    event.preventDefault();
  }, true);

  document.addEventListener("mouseup", (event) => {
    if (!gesture) return;
    const finished = gesture;
    const endCell = cellFromTarget(event.target);
    if (
      endCell
      && endCell.closest(".dash-table-container") === finished.table
    ) {
      finished.end = endCell;
    }
    cancelGesture();
    if (!finished.moved || finished.start === finished.end) return;

    event.preventDefault();
    suppressTrustedClickUntil = Date.now() + 250;
    window.setTimeout(() => {
      if (
        !document.body.contains(finished.start)
        || !document.body.contains(finished.end)
      ) return;
      dispatchNativeSelectionClick(finished.start, false);
      window.setTimeout(() => {
        if (document.body.contains(finished.end)) {
          dispatchNativeSelectionClick(finished.end, true);
        }
      }, 0);
    }, 0);
  }, true);

  document.addEventListener("click", (event) => {
    const validateToggle = event.target?.closest?.(".validate-pl-row-toggle");
    if (validateToggle) {
      event.preventDefault();
      event.stopImmediatePropagation();
      toggleValidateHierarchy(validateToggle);
      return;
    }
    if (
      event.isTrusted
      && Date.now() < suppressTrustedClickUntil
      && cellFromTarget(event.target)
    ) {
      event.preventDefault();
      event.stopImmediatePropagation();
    }
  }, true);

  document.addEventListener("dragstart", (event) => {
    if (gesture?.moved && cellFromTarget(event.target)) event.preventDefault();
  }, true);
  document.addEventListener("copy", () => {
    window.setTimeout(() => clearOtherSelections(), 0);
  }, true);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      cancelGesture();
      clearOtherSelections();
    }
  }, true);
  window.addEventListener("blur", () => {
    cancelGesture();
    clearOtherSelections();
  });
})();
