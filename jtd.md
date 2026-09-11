# JTD: make the clicked branch show its reference table

This corrects the previous `JTD.md` guide. It assumes you already implemented its CSV service, paginated table and search callback. Apply the small repairs below to your working implementation; do not replace your app with the older GitHub application code.

The previous selection block was too restrictive: it required an `underlying` or `reported underlying` key. A displayed name such as `therm` can actually be a promoted **Display Bucket**, and a **Group** has no underlying key at all. Those valid selections were incorrectly sent to “Select an Underlying row.” That mistake was in my guide. I cannot inspect your separately edited production copy, so the checks below also cover missing imports, omitted arguments and incorrect callback wiring.

There is a second distinction in the inspected code: the small arrow expands a branch, the numeric cells select detail, and the row name was only a text span. This repair makes the **name itself selectable**, while keeping the arrow for expanding and collapsing.

## The result you should get

| Click | JTD reference rows to show |
|---|---|
| Raw `therm` name | Every reference row whose raw `Underlying` is exactly `therm` |
| Reported `therm` name | Every reference row for the raw names mapped to that displayed identity |
| Promoted `therm` bucket | Every raw identity in that bucket, even when redundant underlying levels are hidden |
| Its parent Group | All raw identities in that Group and its descendants |
| Risk Greek | All raw identities under that Greek |
| TOTAL | All raw identities in the currently filtered Credit view |

“All” respects the Risk page's active filters and selected branch. It does not load unrelated names just because the selection is high in the tree. `therm` must not match `therm-more` by substring. The `Other` branch keeps the tree's existing exclusion of separately promoted names.

Row-name clicks open **Risk** detail. In **Credit Multi**, a name click explicitly selects **JTD**. In **Cross Single** and **SplitVA**, choose **JTD** in the existing credit-measure selector first. Clicking a numeric cell keeps its existing metric/measure behavior; clicking a specific SplitVA numeric column keeps that column's narrower scope. A SplitVA **name** click covers its whole row.

No new callback, dataframe cache, database or table library is needed for the click repair. Keep the existing 25-row server pagination, full-result search, absolute Risk JTD ordering, numeric commas and sign colors.

## Step 1 — Check that the earlier implementation is present

Save a copy of the files you will edit, then check these exact pieces:

| File | What should already exist |
|---|---|
| `cube/services/s08_jtd.py` | `jtd_reference_rows()` accepts a raw-name string **or list**; `jtd_page()` returns `(records, page_count, page_current, note)`; `JTD_PAGE_SIZE = 25` |
| `cube/pages/risk/s13_workspacetables.py` | One `build_jtd_reference_table()` using `dash_table.DataTable`, with IDs `jtd-scope`, `jtd-search-column`, `jtd-search`, `jtd-page-note`, `jtd-table` |
| `cube/pages/risk/s07_explorer.py` | One `update_jtd_page()` inside `register_explorer_callbacks()`; the existing `render_active_detail()` and main reducer remain there |
| `cube/pages/risk/s05_charts.py` | Both detail functions accept and forward `jtd_reference`, `jtd_underlying` and `jtd_error` |
| `assets/s13_risk.js` | One existing `publishRiskAction()` and one delegated risk-click handler; do not create a second script containing a copy |

For missing formatting/paging pieces only, recover the exact code from the [previous guide at its fixed GitHub revision](https://github.com/streamlitdash/Rebirth-V5/blob/caaa96fe325d520b3fbcc8f2eae36c709ffc4f2a/JTD.md): its Steps 1–3, Step 4.2, Step 5 and Step 6 contain the original data, service, table, paging and test code. **Do not restore its Step 4.3 selection block.** Step 2 below replaces that block. Step 5 below also supersedes its numeric debounce setting.

Keep production CSV contents. In `data/s13_jtd.csv`, `Underlying` must be the exact **raw** identity; `Risk JTD` and `EAD` are numeric measures and `CRDS` remains text. Additional numeric measures belong in `JTD_NUMERIC_COLUMNS`; do not put identifier columns in that tuple.

To separate a file/identity problem from a click problem, run this from the app repository root, replacing `therm` with a known **raw** name from your feed:

```powershell
python -c "from cube.services.s08_jtd import jtd_reference_rows; f=jtd_reference_rows('therm'); print('Matching reference rows:', len(f)); print('Columns:', list(f.columns))"
```

If that returns zero, verify the raw identity, case and current source file before debugging the click. If the display name is an alias, test its raw member instead. This lookup does not need a new live refresh.

The existing CSV is scoped by Underlying, not by Portfolio or tenor. Risk filters determine which raw names qualify; the reference then shows all its rows for those names. Do not interpret it as a portfolio-total reconciliation unless you separately add such a source-data contract.

## Step 2 — Replace the restrictive selection block

**File: `cube/pages/risk/s07_explorer.py`.**

### 2.1 Check imports

In the existing import from `cube.ui.s02_aggregation`, keep the other imported names and add any missing names from this list:

```python
    frame_for_context,
    tree_scope,
```

In the existing import from `cube.ui.s01_constants`, add `BASE_GROUPS,` if absent. This is the existing hierarchy constant, not a new list to define elsewhere.

The JTD service import must be:

```python
from cube.services.s08_jtd import JTDReferenceError, jtd_page, jtd_reference_rows
```

### 2.2 Replace this one block

Inside the existing nested `render_active_detail()`, find:

```python
        effective_credit_measure = selected_credit_measure
```

Replace from that line up to, but **not including**, the next `return build_detail_panel_with_state(...)` with the following. Keep the preceding filtered-frame/new-trades code and the return call.

```python
        effective_credit_measure = selected_credit_measure
        if effective_credit_measure is None and (
            table_view == "alt" or credit_view == "single"
        ):
            effective_credit_measure = credit_measure
        jtd_reference = None
        jtd_underlying = None
        jtd_error = None
        if detail_risk_type == "Credit" and effective_credit_measure == "JTD":
            # A displayed name can be a bucket, group, reported name or raw name.
            # Follow the same branch rules as the Risk tree, including Other.
            scoped = filtered
            for column in ("risk type", *BASE_GROUPS):
                if column in selected_context:
                    scoped = tree_scope(scoped, column, selected_context[column])
            scoped = frame_for_context(scoped, selected_context)
            jtd_underlying = (
                scoped["underlying"].dropna().astype(str).drop_duplicates().tolist()
                if "underlying" in scoped else []
            )
            if jtd_underlying:
                try:
                    jtd_reference = jtd_reference_rows(jtd_underlying)
                except JTDReferenceError as error:
                    LOGGER.exception("Could not load JTD reference")
                    jtd_error = str(error)
            else:
                jtd_error = "No raw Underlying values remain in this selected branch."
```

The essential change is that every valid selected context is scoped first, then all its raw names are collected. There is no requirement for a leaf-level key. The short `tree_scope` loop follows the existing hierarchy rules before applying any extra pivot-column context. It avoids reintroducing promoted names into `Other`.

A TOTAL click intentionally has an empty string key, which the existing reducer already accepts for total cells. A malformed JSON key is different: keep `_valid_delegated_row_key()` and `_is_current_risk_action()` checks. Do not make malformed keys fall back to all data or remove revision/view-token checks.

### 2.3 Check the existing measure selection and return call

Earlier in that same function, this existing branch must still be present:

```python
        selected_credit_measure = selection.get("credit_measure")
        if detail_risk_type == "Credit" and selected_credit_measure:
            filtered = apply_credit_measure(filtered, selected_credit_measure)
        elif detail_risk_type == "Credit" and (
            table_view == "alt" or credit_view == "single"
        ):
            filtered = apply_credit_measure(filtered, credit_measure)
```

At the end, keep all existing arguments and verify the three JTD arguments are passed:

```python
        return build_detail_panel_with_state(
            filtered,
            detail_selection,
            compose_detail_metric(plot_measure, plot_component),
            tenor_view,
            new_trade_details=new_trade_details,
            jtd_reference=jtd_reference,
            jtd_underlying=jtd_underlying,
            jtd_error=jtd_error,
        )
```

There must be no remaining `table_view != "alt"` gate around JTD loading and no instruction to choose an Underlying when a valid Group or bucket is selected. Cross is `main` and SplitVA is `alt` in this source. The existing Credit Multi reducer translates the incoming action's `measure` to selection's `credit_measure`; keep that translation.

## Step 3 — Make the row names clickable

**File: `cube/pages/risk/s06_explorertables.py`.**

### 3.1 Add this small helper

Place it immediately before the existing `def metric_class(` at module level. Keep the existing Dash `html` import.

```python
def _risk_row_label(value: object, *, key: str | None = None) -> html.Button:
    """A row name opens detail; the separate chevron still expands the tree."""
    return html.Button(
        str(value), type="button", className="row-label-text row-detail-button",
        title="Open this branch's detail; Credit Multi uses JTD",
        **({"data-risk-key": key} if key is not None else {}),
    )
```

### 3.2 Replace the hierarchy name span

Inside `build_tree_rows()`, find the `index_children` list. Replace only:

```python
            html.Span(str(value), className="row-label-text"),
```

with:

```python
            (
                _risk_row_label(value)
                if delegated_actions and cell_type != "top-book-risk-cell"
                else html.Span(str(value), className="row-label-text")
            ),
```

Keep the separate `label` variable immediately before it: that is the expand/collapse arrow. The conditional preserves the Top Book and nondelegated uses of this shared helper.

### 3.3 Replace the three TOTAL name spans

In **each** of `build_risk_table()`, `build_alt_risk_table()` and `build_credit_multi_table()`, replace:

```python
html.Span("TOTAL", className="row-label-text")
```

with:

```python
_risk_row_label("TOTAL", key="")
```

Keep the `html.Th` and row around it. The explicit empty key matters because the SplitVA TOTAL row does not have its own row-key attribute. Do not add or expose a made-up Risk total: some total metric cells are intentionally blank. The label can still select the entire branch.

## Step 4 — Send name clicks through the existing action path

**File: `assets/s13_risk.js`.** Make both edits below in that existing file. Keep its keyboard shortcuts, refresh code, modifier gestures and other event handling.

### 4.1 Replace `publishRiskAction`

Replace the entire existing function starting `const publishRiskAction = (node) => {` through its closing `};`, stopping immediately before `const metricCellFromTarget = ...`.

This full copy retains the existing row/metric/Top Book actions and adds native row-label recognition. It uses the existing row key, view token and sequence number. Label clicks do not depend on a numeric button being present, so TOTAL works even when its Risk cells are blank.

```javascript
  const publishRiskAction = (node) => {
    if (!node || node.disabled) return false;
    const isRowLabel = node.classList.contains("row-detail-button");
    const isCreditLabel = isRowLabel && !node.closest("#alt-risk-grid")
      && Boolean(node.closest("tr")?.querySelector(".credit-measure-cell"));
    const isTopBookCell = node.classList.contains("top-book-metric-cell-button");
    const isTopBookRow = node.classList.contains("row-toggle")
      && Boolean(node.closest("#top-book-grid"));
    const kind = node.classList.contains("row-toggle")
      ? "row"
      : node.classList.contains("metric-header-button")
        ? "metric"
        : node.classList.contains("metric-cell-button") || isRowLabel
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
          : node.classList.contains("credit-measure-cell-button") || isCreditLabel
            ? "credit-risk-cell"
            : node.closest("#alt-risk-grid")
              ? "alt-risk-cell"
              : "main-risk-cell");
    }
    if (isRowLabel) {
      // A branch label selects its complete scope, even when sums are blank.
      action.metric = "risk";
      if (isCreditLabel) action.measure = "JTD";
    }
    if (nodeRiskKey !== undefined) action.key = nodeRiskKey;
    if (node.dataset.riskMetric !== undefined) action.metric = node.dataset.riskMetric;
    if (node.dataset.riskMeasure !== undefined) action.measure = node.dataset.riskMeasure;
    setProps(storeId, { data: action });
    return true;
  };
```

### 4.2 Add one branch inside the existing click handler

Within the existing `document.addEventListener("click", ...)`, find the comment:

```javascript
    // Risk Explorer tables can contain hundreds of interactive
```

Insert this block immediately **before** that comment. It must come after the existing modifier/suppressed-click handling. Do not register another document click listener and do not replace the existing `riskAction` branch below the comment.

```javascript
    const rowLabel = event.target.closest(
      "#risk-grid .row-detail-button, #alt-risk-grid .row-detail-button"
    );
    if (rowLabel) {
      event.preventDefault();
      publishRiskAction(rowLabel);
      return;
    }
```

The direct label action uses its row context. It never chooses the first SplitVA Activity/Product column. Arrow clicks still reach the existing `row-toggle` path; numeric cell clicks still carry their original metric and optional measure.

### 4.3 Add the small label style

**File: `assets/s03_risk.css`.** Append this once at the end. It styles only the two main Risk grids.

```css
/* Risk row names open detail; the separate chevron expands/collapses. */
#risk-grid .row-detail-button,
#alt-risk-grid .row-detail-button {
  border: 0;
  padding: 0;
  background: transparent;
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
}
#risk-grid .row-detail-button:hover,
#alt-risk-grid .row-detail-button:hover { text-decoration: underline; }
#risk-grid .row-detail-button:focus-visible,
#alt-risk-grid .row-detail-button:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 2px;
}
```

## Step 5 — Remove the search timer that can outlive a rebuilt card

**File: `cube/pages/risk/s13_workspacetables.py`, function `build_jtd_reference_table()`.**

In its existing `dcc.Input(id="jtd-search", ...)`, replace only these two argument values:

```python
debounce=True,
placeholder="Search CRDS or any column, then press Enter…",
```

This replaces the old `debounce=0.3` and old placeholder. Leave `type="search"`, `value=""` and the ID as they are. Search now applies when you **press Enter or leave the search field**. Clearing the field and pressing Enter restores all matching rows.

Why: in a local browser check on the pinned Dash 4.4.0, the numeric debounce timer could run after a new branch replaced the old card, then try to read an input that no longer existed. Boolean debounce avoids that delayed timer using the same callback. The search still covers every row in the selected scope before pagination.

## Step 6 — Check the table and callback wiring

Keep the existing paginated table builder. It should receive actual `frame`, raw-name list and error arguments, rather than being called with `(None, None)` after each selection.

In `cube/pages/risk/s05_charts.py`, both `build_detail_panel_with_state()` and `_build_detail_panel_from_frame()` must accept:

```python
    jtd_reference: pd.DataFrame | None = None,
    jtd_underlying: str | list[str] | None = None,
    jtd_error: str | None = None,
```

The first function passes those three values to the second. The second builds the reference card with:

```python
        build_jtd_reference_table(
            jtd_reference,
            jtd_underlying,
            error=jtd_error,
        )
```

Keep its existing condition `if jtd_reference is not None or jtd_underlying is not None or jtd_error` and keep the resulting `jtd_table` in the returned children. The tenor charts and other detail sections stay in place.

There must be **one** owner for the JTD page outputs: `update_jtd_page()` inside `register_explorer_callbacks()`. It reads:

```python
        Input("jtd-scope", "data"),
        Input("jtd-table", "page_current"),
        Input("jtd-search", "value"),
        Input("jtd-search-column", "value"),
```

and writes, in this order:

```python
        Output("jtd-table", "data"),
        Output("jtd-table", "page_count"),
        Output("jtd-table", "page_current"),
        Output("jtd-page-note", "children"),
```

Do not add a second callback to `selected-cell-store` or `detail-panel` for this repair. The existing reducer continues to own them. `jtd-scope` contains only a list of raw names, not the full reference dataframe.

Check these retained table properties:

- `page_action="custom"`, `page_size=JTD_PAGE_SIZE`, with `JTD_PAGE_SIZE = 25`.
- `sort_action="none"` and `filter_action="none"`; the service sorts the complete selected reference by descending absolute Risk JTD before paging.
- Changing scope or search resets `page_current` to zero. Next/previous page keeps the search.
- Numeric columns keep their numeric values and `Format(precision=2, scheme=Scheme.fixed, group=True, nully="—")`.
- Default text is black (`#111111`); each numeric column has a conditional rule for values `< 0` using red (`#b91c1c`). Risk JTD and EAD are included. Missing values display a dash.
- `CRDS` remains text so leading zeros survive. The search-column dropdown includes **All columns** and every reference column.

## Step 7 — Restart and run these checks in order

From the repository root, using the same Python environment as the app:

```powershell
python -m compileall -q cube/pages/risk/s07_explorer.py cube/pages/risk/s06_explorertables.py cube/pages/risk/s13_workspacetables.py
python -m pytest tests/s48_jtd.py -q
git diff --check
```

If Node is installed, also run:

```powershell
node --check assets/s13_risk.js
```

Restart the Python app and hard-refresh the browser so it uses the changed JavaScript and CSS.

1. **Cross Single:** select Credit and JTD, then click the `therm` **name**, not its arrow. Its reference table must appear. Click the numeric Risk cell too; that still works.
2. **Move upward:** click the name of its parent Group. It includes every raw name under that Group. Click the Greek, then TOTAL. Each scope expands as expected while active page filters remain applied. TOTAL must work even if the risk total cells are blank.
3. **Promoted name:** with promotion enabled, click a displayed `therm` bucket that has no separate raw/reported child. The reference still appears. `Other` must not reintroduce identities excluded by the tree's promotion rule.
4. **Reported mapping:** a displayed alias containing two raw names shows rows for both, without duplicating the CSV rows. Raw `therm` does not include `therm-more`.
5. **Credit Multi:** click a name; it opens JTD. Click a numeric JTD cell; it also opens JTD. Clicking another measure's numeric cell still selects that other measure normally.
6. **SplitVA:** select JTD, click the Group/name, then TOTAL. The name includes all that row's Activity/Product columns. Clicking a specific numeric column retains the narrower column selection. This also works after you previously used Credit Multi.
7. **Search and pages:** select a name with more than 25 reference rows. Search a CRDS on a later page and press Enter; it must be found on page one. Test All columns, CRDS and EAD. Clear the search and press Enter, then navigate to page two. Check `-9,000.00` is red and comes before `8,000.00`; EAD follows the same sign/color rule.
8. **Interaction:** Tab to a row name and press Enter. The same table appears. Click its arrow: only expansion/collapse changes. Existing Shift/Ctrl/Command selection gestures keep their previous behavior.
9. **Refresh and changes:** change the active filter or committed revision, then click a current row. The table reflects the new scope. A stale click from a replaced tree should still be rejected. Search, immediately choose another branch and repeat: the browser console must not report a missing input `value` error.

## If it still shows the selection prompt

Follow the route in order:

```text
row name or metric button
  -> publishRiskAction
  -> risk-cell-action-store
  -> existing reducer validates key/source/view token
  -> selected-cell-store
  -> render_active_detail
  -> clicked branch -> raw Underlying list
  -> jtd_reference_rows -> build_detail_panel_with_state
  -> build_jtd_reference_table -> update_jtd_page
```

| Symptom | Check |
|---|---|
| Arrow works, name does nothing | Steps 3 and 4; the name must be a `row-detail-button`, and the new asset must have loaded |
| Numeric JTD click works, label does not | Label publication, not CSV or paging; do not add another Python callback |
| A displayed bucket/Group gives the old “Select an Underlying” text | The restrictive old block still exists somewhere, or the running process did not restart |
| No selected-cell update after a click | Inspect `risk-cell-action-store` payload and the reducer's expected source/view token; preserve the validation checks |
| JTD does not appear in Credit Multi | Incoming action needs `measure: "JTD"`; reducer must set `selection["credit_measure"]` from it |
| JTD does not appear in SplitVA | Keep the `table_view == "alt"` selector fallback; remove only the old gate forbidding alternate JTD |
| It says “No raw Underlying values remain…” | The clicked context and active filters have no matching risk rows, or a context column was renamed/dropped |
| It says “No JTD reference rows for this selection” | Valid selection, but its raw names did not match the reference CSV |
| Reference lookup succeeds in Python, but card is empty | Check the three arguments are forwarded through both chart functions and into the table builder |
| Duplicate-output error | Remove the extra JTD callback copy; keep one `update_jtd_page()` owner |

When inspecting the clicked DOM row, `data-risk-key` is structured JSON, for example `{"risk greek":"Delta","display bucket":"therm"}`. That is a valid promoted selection even without an `underlying` key. Do not change the logic to read the visible text and guess a raw name.

## What stays unchanged and rollback

Keep the existing service/file cache, all source columns, exact raw matching, numeric parsing, pagination, formatting, main callback ownership, tenor charts, refresh lifecycle and live connector contracts. No financial aggregation or merge changes are part of this repair.

To undo the new click behavior, restore your saved versions of `s07_explorer.py`, `s06_explorertables.py`, `s13_risk.js` and `s03_risk.css` together, then restart and hard-refresh. The separate `debounce=True` change can remain. Do not roll back production reference data while reverting a UI change.

## Validation of these instructions

The exact replacements were applied to an isolated copy of the earlier guide's implementation. Validation covered the real detail renderer, filter cache, hierarchy scoping, reference lookup and table builder: raw and reported names, promoted buckets, Group, Greek, TOTAL, Cross Single/Multi, SplitVA, active filters, `Other` before pivot scoping, unchanged action validation, paging/search/formatting and Top Book isolation. The focused Python suite passed **32 tests**.

A local Chrome/Dash 4.4.0 fixture using the real table builders, updated risk-click JavaScript and detail renderer also passed actual name clicks, Group/TOTAL expansion of reference scope, promoted-name selection, Credit Multi JTD payloads, SplitVA whole-row selection, Enter activation, arrow-only actions, shared filters and search beyond the first page, with **no browser page errors**. That fixture substitutes synthetic risk/reference data and a small selection-callback wrapper; it is not a test against your production feeds or every app callback. Run the checks above in your implemented app.

This file is an implementation guide. Publishing it does not modify your running application.
