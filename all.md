# Three changes: Commo loading, Portfolio and independent Data

Start with the unchanged application. This guide contains all required edits for these three changes; no earlier implementation is required. Apply chapters 1, 2 and 3 in order, then restart once.

The result is:

1. The Commo loading hero follows the complete backend refresh and reports failures.
2. Risk Explorer has a Portfolio filter and a Portfolio grouping choice.
3. Data opens independently, with searchable, scrollable dropdowns for current and archived Risk or Market data. Quick Risk and Quick Market can still prefill the selection.

## Before editing

1. Stop the running application.
2. In the JupyterHub file browser, open the application folder containing `app.py`, `assets` and `cube`.
3. Create a folder called `manual-backup` alongside `assets` and `cube`. If that name already exists, use a new name. Keep it outside `assets` so the app does not load backup JavaScript.
4. Copy each existing file below into that backup, keeping its folder structure. Files marked **Add new file** have no original to copy.
5. Make every replacement in its numbered order. Search for the shown text or function name. Keep everything outside the specified block. If an old block is missing or occurs more than once, stop that edit and check the file; do not guess or duplicate a callback.

| Application file | Action |
|---|---|
| `assets/s12_refresh.js` | Edit existing file |
| `cube/ui/s01_constants.py` | Edit existing file |
| `cube/ui/s02_aggregation.py` | Edit existing file |
| `cube/pages/risk/s06_explorertables.py` | Edit existing file |
| `cube/pages/risk/s02_state.py` | Edit existing file |
| `cube/pages/risk/s01_common.py` | Edit existing file |
| `cube/pages/risk/s16_view.py` | Edit existing file |
| `cube/services/s02_state.py` | Edit existing file |
| `cube/app/s02_contracts.py` | Edit existing file |
| `cube/history/s06_repository.py` | Edit existing file |
| `cube/pages/data/s03_callbacks.py` | Edit existing file |
| `cube/pages/data/s02_view.py` | Edit existing file |
| `cube/app/s07_factory.py` | Edit existing file |

Leave the connectors, source data, archives and financial calculation rules in place.

## 1. Keep the Commodity loading hero visible until the refresh finishes

The hero must stay visible while Commodity quotes load and while the app calculates, validates, and commits the result. It may finish with a reported error if the refresh fails. The existing Python manager already reports completion after committing its snapshot; this change makes the browser follow that report.

Edit only `assets/s12_refresh.js` for this chapter. Keep your Commodity providers, tenors, calculations, backend progress endpoint, and refresh intervals unchanged. No Python imports are needed.

### 1.1 Prevent a page update from declaring Commo complete

Find this exact function opening. Replace only these two lines; keep the rest of the function underneath it.

Remove:

```javascript
  const finishRefreshProgress = () => {
    if (!refreshProgressState) return;
```

Add in the same place:

```javascript
  const finishRefreshProgress = (backendConfirmed = false) => {
    if (!refreshProgressState) return;
    if (refreshProgressState.mode === "commo" && !backendConfirmed) return;
```

### 1.2 Let confirmed backend completion close the hero

Inside the `refreshProgressPoll` interval, find this exact line. It occurs once. Replace only this occurrence. Keep the surrounding checks that recognise the backend attempt and wait for the refresh callback to end. The new condition rejects an old progress request that was already in flight when the callback ended. Steps 1.3 and 1.4 add its timestamps; finish all edits before restarting.

Remove:

```javascript
          if (!running) finishRefreshProgress();
```

Add in the same place:

```javascript
          const completionResponseIsCurrent = (
            refreshProgressState.mode !== "commo"
            || progress.requested_at > (
              refreshProgressState.dashCallbackCompletedAt || refreshProgressState.startedAt
            )
          );
          if (!running && completionResponseIsCurrent) finishRefreshProgress(true);
```

### 1.3 Record when the refresh callback ends

Inside `handleRefreshStatusTransition`, replace these two lines with the following three. This timestamp lets the browser distinguish a new progress response from an old cached response.

Remove:

```javascript
    state.dashCallbackComplete = true;
    const statusText = (node.textContent || "").trim();
```

Add in the same place:

```javascript
    state.dashCallbackComplete = true;
    state.dashCallbackCompletedAt = Date.now();
    const statusText = (node.textContent || "").trim();
```

### 1.4 Record when each progress request starts

Inside `requestBackendProgress`, replace these two lines with the following three. Keep its existing `const now = Date.now();` line near the start of that function. The new field records when the browser requested progress, so a late response from an earlier request cannot pretend to confirm that a later callback finished.

Remove:

```javascript
            server_time: progressStartedAt(payload.server_time),
            received_at: Date.now(),
```

Add in the same place:

```javascript
            server_time: progressStartedAt(payload.server_time),
            requested_at: now,
            received_at: Date.now(),
```

### 1.5 Do not mistake a recent previous refresh for this Commo refresh

Inside `startRefreshProgress`, find these two lines at the end of `belongsToAttempt`. Replace them with the following block. Keep the preceding checks for a changed refresh attempt and an increased committed revision. This excludes a known previous attempt even if it finished just before you clicked Commo.

Remove:

```javascript
          || progressStartedDuringAttempt(progress, startedAt)
        );
```

Add in the same place:

```javascript
          || (
            progressStartedDuringAttempt(progress, startedAt)
            && (
              mode !== "commo"
              || !refreshProgressState.baselineRefreshAttemptId
              || progress.attempt_id !== refreshProgressState.baselineRefreshAttemptId
            )
          )
        );
```

### 1.6 Handle a request rejected before its data call starts

Back inside `refreshProgressPoll`, find the following complete `else if` block. Replace the whole block. This prevents an invalid or stale request from leaving the hero open forever: a progress request started after the callback ends must confirm the backend is idle, and the callback must report an error. It also preserves the existing behaviour of following a refresh already started elsewhere. A missing progress response still means the result is unconfirmed, so the existing reconnecting display remains active.

Remove:

```javascript
        } else if (!running && !dashLoading && (refreshProgressState.sawRunning || statusChanged)) {
          if (!isBaselineSnapshot) renderBackendProgress(progress);
          finishRefreshProgress();
        }
```

Add in the same place:

```javascript
        } else if (!running && !dashLoading && (refreshProgressState.sawRunning || statusChanged)) {
          if (refreshProgressState.mode === "commo") {
            const errorNode = refreshErrorNode();
            const callbackError = (errorNode?.textContent || "").trim();
            // A rejected callback may create no new backend attempt. Require
            // an idle progress request started after that callback ended.
            const callbackEndConfirmed = (
              refreshProgressState.dashCallbackComplete
              && progress.requested_at > refreshProgressState.dashCallbackCompletedAt
            );
            if (callbackEndConfirmed && refreshProgressState.followingExistingWriter) {
              renderBackendProgress(progress);
              finishRefreshProgress(true);
            } else if (
              callbackEndConfirmed
              && errorNode?.classList.contains("has-errors")
              && callbackError
            ) {
              refreshProgressState.backendError = callbackError;
              finishRefreshProgress(true);
            }
          } else {
            if (!isBaselineSnapshot) renderBackendProgress(progress);
            finishRefreshProgress();
          }
        }
```

### 1.7 Keep the active hero when Dash redraws its panel

Inside `syncRefreshLifecycleNodes`, replace the exact four-line block below. Keep all the existing bootstrap handling and `abandonRefreshProgress` code underneath it. This also covers Dash hiding the existing panel without replacing the DOM node.

Remove:

```javascript
    const state = refreshProgressState;
    if (!state || state.panel?.isConnected) return;
    const replacement = document.getElementById("refresh-progress");
    if (state.mode === "bootstrap") {
```

Add in the same place:

```javascript
    const state = refreshProgressState;
    if (!state) return;
    const replacement = document.getElementById("refresh-progress");
    if (state.mode === "commo" && refreshLifecycleVisible()) {
      // Dash can replace the panel or restore its hidden property in place.
      // Keep following the same refresh, including a gap before remounting.
      if (replacement) {
        state.panel = replacement;
        replacement.hidden = false;
        replacement.classList.remove("is-complete");
        replacement.classList.add("is-running");
      }
      return;
    }
    if (state.panel?.isConnected) return;
    if (state.mode === "bootstrap") {
```

### 1.8 Save and check the behaviour

1. Save `assets/s12_refresh.js`.
2. Restart the app using your usual JupyterHub launch cell.
3. Hard-refresh the app browser with Ctrl+Shift+R so it loads the updated JavaScript.
4. Enable Commo Market and remain on the Risk page. The hero should remain visible through the last Commodity quote call, calculations, validation, and snapshot commit. It should then show completion and close.
5. Disable and re-enable Commo Market. A fast cached refresh may close quickly, but a slow refresh must keep its hero visible.
6. If a refresh fails, read the error log: it should show a failure and retain the last successful data. A disconnected progress endpoint should show reconnection status, not claim success. Do not deliberately damage your data or providers to create an error.
7. Leave every other `finishRefreshProgress()` call unchanged. Keep the existing percentage-bar behaviour; the Commo hero does not need an invented percentage to remain visible.

## 2. Add Portfolio to Risk Explorer

This uses the Portfolio column already present in the current risk data. It adds a searchable, multiple-selection Portfolio filter and a Portfolio choice beside Product, Activity and the other Explorer dimensions. No connector or market-data change is needed.

All three pages should offer these five filters: **Activity, Signoff Group, Portfolio, Category and Sub Category**.

| Page | Starting code | Action in this chapter |
|---|---|---|
| Risk | Four visible filters; Portfolio is excluded | Add Portfolio as the fifth filter |
| Stock | All five filters are already built | Keep its existing Portfolio filter |
| P&L | All five filters are already built | Keep its existing Portfolio filter |

The filters are inside each page's **Saved views** section. Each page keeps its own applied selection. The extra Portfolio grouping choice described below is a separate Risk Explorer feature.

With **Cross → Dimension: Portfolio**, Portfolio replaces Activity as the final hierarchy level, after the existing tenor and Split levels. It is not inserted above every underlying. Expand a branch to see its books; parent values still sum all positions within the applied filters. Activity remains the default dimension.

With **SplitVA → Dimension: Portfolio**, selected portfolios become columns. More than 20 matching portfolios produces a message asking you to use Cross or narrow the Portfolio filter. This is a display-width limit, not a data-loading limit.

Apply every step below before restarting the app. Keep the existing lazy expansion condition `if can_expand and is_open:` in `build_tree_rows`; do not generate closed branches or expand all branches on startup. Keep all raw risk rows, quote keys, market joins, reduced-tenor logic and connector code.

### 2.1. Register Portfolio as a selectable dimension

File: `cube/ui/s01_constants.py`.

Replace this entire block. Keep the existing Portfolio field; do not add another field to the connector schema.

Find:

```python
    # Stock and P&L still use Portfolio as a filter. Risk deliberately keeps
    # this shared saved-view field internal and aggregates across it.
    roles=frozenset({"filter_dimension"}),
```

Replace with:

```python
    roles=frozenset({"filter_dimension", "view_dimension"}),
```

### 2.2. Include that field in the dimension list

File: `cube/ui/s01_constants.py`.

Replace this assignment. Product and the existing dimensions remain available, and Activity remains the default.

Find:

```python
VIEW_DIMENSION_FIELDS = tuple(
    field for field in PORTFOLIO_FIELDS if "view_dimension" in field.roles
)
```

Replace with:

```python
VIEW_DIMENSION_FIELDS = tuple(
    field
    for field in (*PORTFOLIO_FIELDS, PORTFOLIO_UI_FIELD)
    if "view_dimension" in field.roles
)
```

### 2.3. Enable the existing Portfolio filter on Risk

File: `cube/ui/s01_constants.py`.

Replace this assignment. The existing layout and callbacks already build their controls from this list, so do not add a separate dropdown or callback.

Find:

```python
RISK_FILTER_DIMENSION_FIELDS = tuple(
    field for field in FILTER_DIMENSION_FIELDS if field.key != "portfolio"
)
```

Replace with:

```python
RISK_FILTER_DIMENSION_FIELDS = FILTER_DIMENSION_FIELDS
```

### 2.4. Remove the duplicate Portfolio preparation

File: `cube/ui/s02_aggregation.py`.

Portfolio is now handled by the existing `for column in FILTER_COLUMNS` loop immediately above. Delete only the following block; keep that loop.

Find:

```python
    # Portfolio remains part of the prepared position data for P&L, Stock,
    # history, and diagnostics even though Risk has no Portfolio filter or
    # grouping. Keep its historical string contract (including named books).
    if "portfolio" not in frame:
        frame["portfolio"] = "Unspecified"
    else:
        frame["portfolio"] = frame["portfolio"].fillna("Unspecified").astype(str)
```

Remove that block entirely. Add nothing in its place.

### 2.5. Keep exactly one Portfolio column in the prepared frame

File: `cube/ui/s02_aggregation.py`.

Near the end of `prepare_risk_data`, replace this part of the returned column list. `VIEW_DIMENSIONS` now contains `portfolio`; leaving the explicit line creates duplicate column names and can break pandas operations. This removes a repeated column selection, not Portfolio data.

Find:

```python
            # P&L and history reuse this prepared frame and still require the
            # position identity. Risk has no Portfolio control or grouping,
            # so its table group-bys aggregate across this retained column.
            "portfolio",
            *VIEW_DIMENSIONS,
```

Replace with:

```python
            *VIEW_DIMENSIONS,
```

### 2.6. Let the row hierarchy use the selected dimension

File: `cube/pages/risk/s06_explorertables.py`.

Replace the whole `_active_groups_for_frame` function, stopping before `def metric_class`. All required names are already imported in this file.

Find the function starting with:

```python
def _active_groups_for_frame(
```

Replace with:

```python
def _active_groups_for_frame(
    frame: pd.DataFrame,
    promotion_enabled: bool,
    region_enabled: bool,
    underlying_identity_mode: str = "reported",
    dimension: str | None = None,
) -> list[str]:
    """Resolve the existing hierarchy and its final reporting dimension."""
    region_available = bool(
        "region" in frame
        and frame["region"].fillna("").astype(str).str.strip().ne("").any()
    )
    identity_group = (
        "underlying"
        if str(underlying_identity_mode).strip().casefold() == "underlying"
        else "reported underlying"
    )
    groups = [
        group
        for group in get_active_groups(
            promotion_enabled,
            region_enabled,
            region_available=region_available,
        )
        if group not in {"reported underlying", "underlying"} or group == identity_group
    ]
    if dimension is not None:
        groups[-1] = selected_dimension(dimension)
    return groups
```

### 2.7. Pass the dimension into the Cross hierarchy

File: `cube/pages/risk/s06_explorertables.py`.

Inside `build_risk_table` only, replace this block. Keep `HierarchyAggregationIndex`, which already sums positions separately from distinct market quotes.

Find:

```python
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                    underlying_identity_mode,
                ),
                toggle_type=toggle_type,
```

Replace with:

```python
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                    underlying_identity_mode,
                    dimension=dimension,
                ),
                toggle_type=toggle_type,
```

### 2.8. Avoid a 400-column Portfolio pivot

File: `cube/pages/risk/s06_explorertables.py`.

Inside `build_alt_risk_table`, replace the following block with the version below. The check runs before building any cells. It limits only the width of the Portfolio SplitVA display; Cross and the Portfolio filter can still use every portfolio and all source rows.

Find:

```python
    dimension_values = (
        ordered_unique(frame, dimension_column) if not frame.empty else []
    )

    def dimension_cells
```

Replace with:

```python
    dimension_values = (
        ordered_unique(frame, dimension_column) if not frame.empty else []
    )
    if dimension_column == "portfolio" and len(dimension_values) > 20:
        return html.Div(
            [
                html.Strong("Too many portfolio columns for SplitVA"),
                html.Span(
                    "Use Cross to explore all portfolios, or choose at most "
                    "20 portfolios in Filter View and click Apply filters."
                ),
            ],
            className="empty-state",
            role="status",
        )

    def dimension_cells
```

### 2.9. Keep the pivot dimension out of the SplitVA row hierarchy

File: `cube/pages/risk/s06_explorertables.py`.

Still inside `build_alt_risk_table`, replace this block. `[:-1]` removes the final Activity row level, since this view already shows the selected dimension as columns.

Find:

```python
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                    underlying_identity_mode,
                ),
                cell_builder=dimension_cells,
```

Replace with:

```python
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                    underlying_identity_mode,
                )[:-1],
                cell_builder=dimension_cells,
```

### 2.10. Pass the dimension into Credit Multi too

File: `cube/pages/risk/s06_explorertables.py`.

Inside `build_credit_multi_table`, replace this block. The Credit measure columns stay unchanged; Portfolio becomes the final row level when selected.

Find:

```python
            groups=_active_groups_for_frame(
                frame,
                promotion_enabled,
                region_enabled,
                underlying_identity_mode,
            ),
            cell_builder=measure_cells,
```

Replace with:

```python
            groups=_active_groups_for_frame(
                frame,
                promotion_enabled,
                region_enabled,
                underlying_identity_mode,
                dimension=dimension,
            ),
            cell_builder=measure_cells,
```

### 2.11. Stop retaining 24 full HTML table versions

File: `cube/pages/risk/s02_state.py`.

Inside `_RiskDataCache`, replace the whole `rendered` method, stopping before `def _next_counter`. Keep the method name and arguments so its callers do not change. The existing prepared and filtered data caches remain. This rebuilds the requested visible table when needed, with one build at a time; it does not retain previous expanded HTML trees.

Find the method starting with:

```python
    def rendered(self, key: str, build: Callable[[], Any]) -> Any:
```

Replace with:

```python
    def rendered(self, key: str, build: Callable[[], Any]) -> Any:
        """Build the visible table without retaining prior component trees."""
        with self._render_compute_lock:
            return build()
```

### 2.12. Remove the unused HTML-cache field

File: `cube/pages/risk/s02_state.py`.

Inside `_RiskDataCache.__init__`, delete only this line. Keep `_filtered`, `_filtered_bytes` and `_render_compute_lock`.

Find:

```python
        self._rendered: OrderedDict[str, Any] = OrderedDict()
```

Remove that block entirely. Add nothing in its place.

### 2.13. Remove HTML-cache clearing from revision replacement

File: `cube/pages/risk/s02_state.py`.

Inside `replace_frame`, replace this short block. Keep the surrounding code and the other cache invalidation.

Find:

```python
                self._rendered.clear()
                self._promotion_generations.clear()
                self._reduced_frames.clear()
                self._market_quote_revision = None
                self._market_quotes = None
                return prepared
```

Replace with:

```python
                self._promotion_generations.clear()
                self._reduced_frames.clear()
                self._market_quote_revision = None
                self._market_quotes = None
                return prepared
```

### 2.14. Remove the other HTML-cache clearing line

File: `cube/pages/risk/s02_state.py`.

Inside `clear_reconstructable`, delete only this line. It is now the only remaining occurrence. Do not delete `_UNSET`; unrelated date controls still use it.

Find:

```python
                self._rendered.clear()
```

Remove that block entirely. Add nothing in its place.

### 2.15. Update the filter explanation shown on the page

File: `cube/pages/risk/s01_common.py`.

Inside `RISK_FILTER_NOTE`, replace these strings so the page describes the new controls correctly.

Find:

```python
    "values. Risk is aggregated across Portfolio; Stock and P&L keep their "
    "own Portfolio filters."
```

Replace with:

```python
    "values. Portfolio filters Risk Explorer, Aggregate P&L and Quick Risk. "
    "Click Apply filters to use your selection. Stock and P&L keep their "
    "own Portfolio filters."
```

### 2.16. Keep the new grouping choice in Risk Explorer

File: `cube/pages/risk/s16_view.py`.

Inside the `dcc.RadioItems` whose ID is `aggregate-pl-dimension`, replace this block. This preserves the existing Aggregate P&L dimension choices; the Explorer control with ID `table-dimension` keeps the complete list, including Portfolio. The shared Portfolio filter still applies to Aggregate P&L and Quick Risk.

Find:

```python
                                                    id="aggregate-pl-dimension",
                                                    options=view_dimension_options,
```

Replace with:

```python
                                                    id="aggregate-pl-dimension",
                                                    options=[
                                                        option
                                                        for option in view_dimension_options
                                                        if option["value"] != "portfolio"
                                                    ],
```

### 2.17. Use the Portfolio controls after the final restart

1. Open Risk's **Saved views**, type a known book into **Portfolio**, select it, and press **Apply filters**. Choosing a value only edits the draft until you apply it.
2. Open **Risk explorer → Cross** and choose **Portfolio** under **Dimension**. Open one underlying through its tenor and Split levels. The final rows should be portfolios rather than Activity values. A Spot or unused tenor axis may be skipped, as before.
3. Apply two books that share an underlying and tenor. Their Risk, dRisk and P&L must add to the corresponding parent within the same Greek. Open, Current and Move remain quote values, not sums multiplied by two books. A missing quote stays unavailable.
4. Clear only the Portfolio selection and press **Apply filters**. Broader totals should return, subject to your other active filters. Clearing Portfolio does not clear Activity or category filters.
5. Choose **SplitVA → Portfolio**. With at most 20 matching books, each book should have a column and a Total column should remain. With more than 20, the explanatory message should appear. Use Cross to explore all 300–400 books.
6. Check **Credit → Multi** with Portfolio selected; its final row level should also be Portfolio. Switch back to Activity to recover the original final grouping.
7. Close and reopen a few branches. Closed children should disappear and return with the same figures. The existing prepared/filtered data cache remains, so this does not reread connectors on every click.

There is no source-row cap in this change. It removes the repeated HTML retention and avoids a 400-column pivot, but opening a very large number of branches at once still creates a large page. It cannot guarantee that an unknown server memory allowance will accommodate every expansion of 100,000 rows.

### 2.18. Keep and check the fifth filter on Stock and P&L

1. Open `cube/pages/stock/s01_data.py`. Keep this existing assignment unchanged:

   ```python
   STOCK_FILTER_FIELDS = FILTER_DIMENSION_FIELDS
   ```

2. Open `cube/pages/pnl/s01_common.py`. Keep this existing assignment unchanged:

   ```python
   PL_FILTER_FIELDS = FILTER_DIMENSION_FIELDS
   ```

3. Keep the existing `for field in STOCK_FILTER_FIELDS` loop in `build_stock_filter_bar` in `cube/pages/stock/s03_view.py`, and the `for field in PL_FILTER_FIELDS` loop in `build_pl_filter_bar` in `cube/pages/pnl/s07_view.py`. These already build all five dropdowns from the shared list. Keep their existing callbacks and component IDs: `stock-portfolio-filter` and `pnl-portfolio-filter`. Add no duplicate dropdown or callback.
4. After the final restart, open **Saved views** on Stock. Confirm all five filter labels appear, select a known Portfolio, and press **Apply filters**. Its displayed positions should follow that Portfolio selection. Clear Portfolio and apply again to restore the broader view within the other active filters.
5. Repeat on the P&L page. Its P&L view should follow its own applied Portfolio selection. This is the page's main Portfolio filter, separate from any Portfolio selector inside the sending controls.
6. Return to Risk and confirm its fifth filter is also present. Changing the Stock or P&L selection should not silently change Risk's selection.

## 3. Make Data work on its own with a searchable, scrollable dropdown

Keep the existing Risk History and Market History tabs, period controls, charts, playback and Load history button. The same page will work when opened directly. Quick Risk and Quick Market still prefill the selection, and you can then select something else.

The current code builds dropdown choices only from completed archives. This change also uses the already committed current identities and loads current data even when no archive exists. Current Market uses its real committed Market Date, as the final observation in this current view; it is not relabelled with the computer date. Risk uses each source’s actual Risk Date. Custom periods still exclude observations outside the selected range.

Apply the steps below in order. Paths are relative to the folder containing `app.py`.

### 3.1. Add two read methods to the refresh manager

Open `cube/services/s02_state.py`.

Insert these methods immediately above `def combine_udl_options`. Keep that existing method and all methods below it. These reads use committed data; they do not call connectors or copy every table.



Add this code, indented at the same level as the other methods:

```python
    def data_history_identities(self) -> tuple[ResolvedHistoryIdentity, ...]:
        """Read compact Data choices from one committed search catalog."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            return ()
        identities = []
        for kind, mode in (
            ("risk", "reported"), ("risk", "underlying"), ("market", "underlying")
        ):
            labels = (
                catalog.market_udl_options()
                if kind == "market"
                else catalog.combine_udl_options(identity_mode=mode)
            )
            for label in labels:
                identities.append(catalog.resolve_history_identity(
                    kind, label, identity_mode=mode
                ))
        return tuple(identities)

    def read_data_history(self, handoff) -> tuple[int, pd.DataFrame]:
        """Copy only the selected current identity from one committed snapshot."""
        with self._state_lock:
            committed = self._snapshot
        if committed is None:
            return 0, pd.DataFrame()
        identity = handoff.identity
        frame = (
            committed.dashboard_frame if handoff.kind == "risk"
            else committed.market_frame
        )
        column = (
            "Reported Underlying" if identity.identity_mode == "reported"
            else "Underlying"
        )
        mask = (
            frame["Source Type"].isin(identity.source_types)
            & frame["Risk Type"].eq(identity.risk_type)
            & frame["Risk Greek"].eq(identity.risk_greek)
            & frame[column].eq(identity.underlying)
        )
        rows = frame.loc[mask].copy()
        rows["Revision"] = committed.revision
        rows["Snapshot Date"] = committed.market_date
        if handoff.kind == "risk":
            rows["Risk Date"] = rows["Source Type"].map(committed.risk_dates)
            if rows["Risk Date"].isna().any():
                raise ValueError("Current Risk has no committed source Risk Date")
            rows["Mapping Status"] = "Mapped"
        else:
            rows["Market Date"] = committed.market_date
        return committed.revision, rows
```

### 3.2. Declare the two manager reads at the app boundary

Open `cube/app/s02_contracts.py`.



Find:

```python
    def read_frame(self, name: FrameName) -> FrameReadProtocol: ...
```

Replace with:

```python
    def read_frame(self, name: FrameName) -> FrameReadProtocol: ...

    def data_history_identities(self) -> tuple[object, ...]: ...

    def read_data_history(self, handoff) -> tuple[int, pd.DataFrame]: ...
```

### 3.3. Allow the existing history reader to receive current rows

Open `cube/history/s06_repository.py`.



Find:

```python
    def read(self, query: HistoryQuery) -> HistoryBundle:
```

Replace with:

```python
    def read(
        self,
        query: HistoryQuery,
        *,
        current_rows: pd.DataFrame | None = None,
        current_revision: int = 0,
    ) -> HistoryBundle:
```

### 3.4. Include actual current dates before resolving the requested period

Open `cube/history/s06_repository.py`.



Find:

```python
        dates = resolve_actual_period_dates(available_dates, query)
```

Replace with:

```python
        live = current_rows.copy() if current_rows is not None else pd.DataFrame()
        if handoff.kind == "risk" and not live.empty:
            live = _apply_risk_filters(live, handoff.filter_view)
        if not live.empty:
            live[date_column] = live[date_column].map(
                lambda value: _date(value, label=date_column)
            )
            live_dates = tuple(sorted(set(live[date_column])))
            # The committed Market date is the end of this current view.
            if handoff.kind == "market":
                available_dates = tuple(
                    value for value in available_dates if value <= live_dates[-1]
                )
            available_dates = tuple(sorted(set(available_dates).union(live_dates)))
        dates = resolve_actual_period_dates(available_dates, query)
```

### 3.5. Add current values and replace same-day archive observations

Open `cube/history/s06_repository.py`.



Find:

```python
        if handoff.kind == "risk":
            period_rows = _apply_risk_filters(period_rows, handoff.filter_view)
```

Replace with:

```python
        if not live.empty:
            live = live.loc[live[date_column].isin(dates)].copy()
        if not live.empty:
            if not period_rows.empty:
                archived_dates = period_rows[date_column].map(
                    lambda value: _date(value, label=date_column)
                )
                # Replace the whole selected source/day, not individual tenor cells.
                # This also removes tenors that no longer exist in the current view.
                live_keys = set(zip(live[SOURCE_TYPE], live[date_column]))
                keep = [
                    (source, day) not in live_keys
                    for source, day in zip(period_rows[SOURCE_TYPE], archived_dates)
                ]
                period_rows = period_rows.loc[keep]
            if len(period_rows) + len(live) > self._max_raw_rows:
                raise HistoryValidationError(
                    "Current plus archived data is too large; narrow the period or Risk filters."
                )
            period_rows = pd.concat([period_rows, live], ignore_index=True, sort=False)
        if handoff.kind == "risk":
            period_rows = _apply_risk_filters(period_rows, handoff.filter_view)
```

### 3.6. Include the current revision in the returned playback identity

Open `cube/history/s06_repository.py`.



Find:

```python
            raw_rows=period_rows.reset_index(drop=True),
            generation=generation,
```

Replace with:

```python
            raw_rows=period_rows.reset_index(drop=True),
            generation=f"{generation}:current:{current_revision}",
```

### 3.7. Import the existing catalog types

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    HistoryBundle,
```

Replace with:

```python
    HistoryBundle,
    HistoryCatalogEntry,
    HistoryIdentityCatalog,
```

### 3.8. Remove the unused old selection import

Open `cube/pages/data/s03_callbacks.py`.



Remove:

```python
    catalog_key_for_handoff,
```

### 3.9. Keep the truthful Current label

Open `cube/pages/data/s03_callbacks.py`.

Delete this entire block. Keep `metric_column = bundle.metric_column` and `browser_values = bundle.values` directly above it.



Remove:

```python
    if bundle.query.handoff.kind == "market" and metric_column == "Current":
        metric_column = "Official"
        browser_values = browser_values.rename(columns={"Current": metric_column})
```

### 3.10. Use the same label in the breadcrumb

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    series = "Risk" if handoff.kind == "risk" else "Official"
```

Replace with:

```python
    series = "Risk" if handoff.kind == "risk" else "Current"
```

### 3.11. Pass the manager into the existing query helper

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    reset_generation: object,
) -> tuple[dict[str, object] | None, str]:
```

Replace with:

```python
    reset_generation: object,
    refresh_manager=None,
) -> tuple[dict[str, object] | None, str]:
```

### 3.12. Read the selected current rows when Load history is clicked

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    bundle = repository.read(query)
```

Replace with:

```python
    revision, rows = (
        refresh_manager.read_data_history(handoff)
        if refresh_manager is not None else (0, pd.DataFrame())
    )
    bundle = repository.read(query, current_rows=rows, current_revision=revision)
```

### 3.13. Update the empty-result explanation

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
        status = "No archived rows match this exact identity and period."
```

Replace with:

```python
        status = "No current or archived rows match this identity and period."
```

### 3.14. Replace the archive-only catalog helper

Open `cube/pages/data/s03_callbacks.py`.

Replace the entire top-level `load_archive_catalog` function. Stop before `def register_callbacks`; keep that next function.



Find:

```python
def load_archive_catalog(
    repository: ArchiveHistoryRepository,
    cache_state: object,
) -> tuple[dict[str, object] | None, str]:
    """Load the tiny direct-selector catalog after the Data route is mounted."""

    if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
        return None, "Preparing archive choices…"
    catalog = repository.catalog()
    risk_count = sum(entry.kind == "risk" for entry in catalog.entries)
    market_count = sum(entry.kind == "market" for entry in catalog.entries)
    if not catalog.entries:
        status = (
            "No completed schema-v4 Risk or Market archive identities are available."
        )
    else:
        status = (
            f"Archive ready: {risk_count:,} Risk and {market_count:,} Market choices."
        )
    return catalog.to_mapping(), status
```

Replace with:

```python
def load_archive_catalog(
    repository: ArchiveHistoryRepository,
    cache_state: object,
    refresh_manager=None,
) -> tuple[dict[str, object] | None, str]:
    """Combine archive identities with compact committed current choices."""
    if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
        return None, "Preparing Data choices…"
    archive = repository.catalog()
    entries = {entry.key: entry for entry in archive.entries}
    revision = 0
    if refresh_manager is not None:
        for resolved in refresh_manager.data_history_identities():
            handoff = HistoryHandoff.from_resolved_identity(
                resolved, metric="risk" if resolved.kind == "risk" else "current"
            )
            entry = HistoryCatalogEntry(
                kind=handoff.kind, identity=handoff.identity,
                source_revision=handoff.source_revision,
                snapshot_date=handoff.snapshot_date,
            )
            entries[entry.key] = entry
            revision = max(revision, entry.source_revision)
    ordered = tuple(sorted(entries.values(), key=lambda entry: (
        entry.kind, entry.identity.risk_type, entry.identity.risk_greek,
        entry.identity.underlying.casefold(), entry.identity.identity_mode,
        entry.identity.source_types,
    )))
    catalog = HistoryIdentityCatalog(
        generation=f"{archive.generation}:current:{revision}", entries=ordered
    )
    status = (
        f"Ready: {len(ordered):,} current/archive identity choices."
        if ordered else "No choices yet. Wait for the initial data refresh to finish."
    )
    return catalog.to_mapping(), status
```

### 3.15. Let Data callbacks use the existing refresh manager

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
def register_callbacks(
    app: Dash,
    repository: ArchiveHistoryRepository,
) -> None:
```

Replace with:

```python
def register_callbacks(
    app: Dash,
    repository: ArchiveHistoryRepository,
    refresh_manager=None,
) -> None:
```

### 3.16. Give the dropdowns one owner

Open `cube/pages/data/s03_callbacks.py`.

Delete both complete callbacks `sync_quick_handoff` and `configure_identity_mode`, including their `@app.callback(...)` decorators. Insert the callback below in their place. Stop before the decorator for `configure_request`, whose first Output is `data-identity-breadcrumb`; keep that breadcrumb callback. The dropdown values are intentionally Inputs and Outputs of this one callback; do not split it back into mutually dependent callbacks.



Paste this complete replacement block:

```python
    @app.callback(
        Output("data-history-kind-tabs", "value"),
        Output("data-identity-mode", "value"),
        Output("data-identity-mode", "disabled"),
        Output("data-risk-type", "options"),
        Output("data-risk-type", "value"),
        Output("data-risk-greek", "options"),
        Output("data-risk-greek", "value"),
        Output("data-underlying", "options"),
        Output("data-underlying", "value"),
        Output("data-load-history-button", "disabled"),
        Input("data-history-catalog-store", "data"),
        Input("data-history-kind-tabs", "value"),
        Input("data-identity-mode", "value"),
        Input("data-risk-type", "value"),
        Input("data-risk-greek", "value"),
        Input("data-underlying", "value"),
        Input("data-history-handoff-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
        State("data-history-request-store", "data"),
    )
    def choose_data_identity(
        raw_catalog, kind, mode, risk_type, greek, underlying,
        raw_handoff, consumed_nonce, raw_request,
    ):
        # One callback owns the dependent selectors. User changes remain selected.
        # A new Quick navigation prefills them once, without locking them later.
        handoff = None
        try:
            if ctx.triggered_id == "data-history-handoff-store":
                handoff = _stored_history_handoff(raw_handoff)
            elif ctx.triggered_id is None:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
        except (HistoryValidationError, TypeError, ValueError):
            if ctx.triggered_id is None:
                try:
                    handoff = _requested_history_handoff(raw_request)
                except (HistoryValidationError, TypeError, ValueError):
                    pass
        kind = handoff.kind if handoff else str(kind or "risk").casefold()
        mode = handoff.identity.identity_mode if handoff else str(mode or "reported")
        if kind == "market":
            mode = "underlying"
        try:
            catalog = HistoryIdentityCatalog.from_mapping(raw_catalog)
        except (HistoryValidationError, TypeError, ValueError):
            catalog = HistoryIdentityCatalog(generation="pending", entries=())
        if handoff:
            risk_type = handoff.identity.risk_type
            greek = handoff.identity.risk_greek
        try:
            fallback = handoff or _stored_history_handoff(raw_handoff)
            entry = HistoryCatalogEntry(
                kind=fallback.kind, identity=fallback.identity,
                source_revision=fallback.source_revision,
                snapshot_date=fallback.snapshot_date,
            )
            if handoff:
                underlying = entry.key
            if (
                underlying == entry.key and kind == fallback.kind
                and mode == fallback.identity.identity_mode
                and risk_type == fallback.identity.risk_type
                and greek == fallback.identity.risk_greek
            ):
                entries = {item.key: item for item in catalog.entries}
                entries.setdefault(entry.key, entry)
                catalog = HistoryIdentityCatalog(
                    generation=catalog.generation, entries=tuple(entries.values())
                )
        except (HistoryValidationError, TypeError, ValueError):
            pass
        type_options = risk_type_options(catalog, kind, mode)
        risk_type = selected_value(type_options, risk_type)
        greek_options = (
            risk_greek_options(catalog, kind, mode, risk_type) if risk_type else []
        )
        greek = selected_value(greek_options, greek)
        options = (
            underlying_options(catalog, kind, mode, risk_type, greek)
            if risk_type and greek else []
        )
        underlying = selected_value(options, underlying)
        return (
            kind, mode, kind == "market", type_options, risk_type,
            greek_options, greek, options, underlying, underlying is None,
        )
```

### 3.17. Replace catalog refresh and remove the three old dropdown callbacks

Open `cube/pages/data/s03_callbacks.py`.

Delete the complete `refresh_archive_catalog`, `choose_risk_type`, `choose_risk_greek`, and `choose_underlying` callbacks, including their decorators. This contiguous block starts with the decorator whose first Output is `data-history-catalog-store` and ends immediately before the decorator whose first Output is `data-history-request-store`. Insert the callback below. Keep `choose_history_request` and its decorator unchanged for now; the next steps adjust only specified lines.



Paste this complete replacement block:

```python
    @app.callback(
        Output("data-history-catalog-store", "data"),
        Output("data-catalog-status", "children"),
        Input("data-history-cache-state-store", "data"),
        Input("refresh-commit-revision", "children"),
        State("data-history-catalog-store", "data"),
    )
    def refresh_archive_catalog(cache_state, _committed_revision, current):
        if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
            return None, "Preparing Data choices…"
        revision = int(refresh_manager.health.revision) if refresh_manager else 0
        generation = f"{cache_state['generation']}:current:{revision}"
        if isinstance(current, Mapping) and current.get("generation") == generation:
            return no_update, no_update
        try:
            return load_archive_catalog(repository, cache_state, refresh_manager)
        except (OSError, HistoryValidationError, TypeError, ValueError) as error:
            return None, f"Data choices failed: {error}"
```

### 3.18. Keep a Quick selection loadable while its catalog is preparing

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
                    handoff = direct_history_handoff(
                        raw_catalog,
                        entry_key,
                        kind=kind,
                        reset_generation=reset,
                    )
```

Replace with:

```python
                    try:
                        handoff = direct_history_handoff(
                            raw_catalog, entry_key, kind=kind, reset_generation=reset
                        )
                    except HistoryValidationError:
                        # Preserve an exact Quick identity while the catalog loads.
                        fallback = _stored_history_handoff(raw_handoff)
                        entry = HistoryCatalogEntry(
                            kind=fallback.kind, identity=fallback.identity,
                            source_revision=fallback.source_revision,
                            snapshot_date=fallback.snapshot_date,
                        )
                        if entry.key != entry_key or fallback.kind != kind:
                            raise
                        handoff = replace(fallback, reset_generation=reset)
```

### 3.19. Preserve Quick Risk filters when reloading the same identity

Open `cube/pages/data/s03_callbacks.py`.

Inside `choose_history_request`, replace this exact Load-button return block. Choosing a different identity creates a fresh direct selection. Reloading the same identity, including after changing period, keeps its existing Quick Risk filters.



Find:

```python
                return history_request_payload(
                    handoff,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    request_id=f"load-{int(load_clicks or 0)}-{reset}",
                ), no_update
```

Replace with:

```python
                try:
                    previous_handoff = _requested_history_handoff(current_request)
                except (HistoryValidationError, TypeError, ValueError):
                    previous_handoff = None
                if (
                    previous_handoff is not None
                    and previous_handoff.kind == handoff.kind
                    and previous_handoff.identity == handoff.identity
                ):
                    handoff = replace(
                        handoff, filter_view=previous_handoff.filter_view,
                        metric=previous_handoff.metric,
                    )
                return history_request_payload(
                    handoff,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    request_id=f"load-{int(load_clicks or 0)}-{reset}",
                ), no_update
```

### 3.20. Stop a request from re-triggering catalog preparation

Open `cube/pages/data/s03_callbacks.py`.

This occurrence is in the decorator immediately above `refresh_archive_generation`. Keep the same function parameters.



Find:

```python
        Input("data-history-request-store", "data"),
        State("data-history-cache-state-store", "data"),
```

Replace with:

```python
        State("data-history-request-store", "data"),
        State("data-history-cache-state-store", "data"),
```

### 3.21. Refresh the selected view after a committed data refresh

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
        Input("reset-generation-store", "data"),
        running=[
```

Replace with:

```python
        Input("reset-generation-store", "data"),
        Input("refresh-commit-revision", "children"),
        running=[
```

### 3.22. Accept the committed revision signal in the loading callback

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    def load_history(
        raw_request,
        cache_state,
        reset_generation,
    ):
```

Replace with:

```python
    def load_history(
        raw_request,
        cache_state,
        reset_generation,
        _committed_revision,
    ):
```

### 3.23. Supply the manager when the loading callback queries history

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
                cache_state,
                reset_generation,
            )
```

Replace with:

```python
                cache_state,
                reset_generation,
                refresh_manager,
            )
```

### 3.24. Make the Underlying dropdown explicitly searchable and scrollable

Open `cube/pages/data/s02_view.py`.



Find:

```python
                                        id="data-underlying",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        searchable=True,
```

Replace with:

```python
                                        id="data-underlying",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        searchable=True,
                                        maxHeight=300,
                                        optionHeight=36,
                                        placeholder="Type or scroll to choose an underlying",
```

### 3.25. Update the initial dropdown description

Open `cube/pages/data/s02_view.py`.



Find:

```python
                                "Archive choices load only on this page.",
```

Replace with:

```python
                                "Current and archived choices load on this page.",
```

### 3.26. Start normal data loading on a direct Data visit

Open `cube/app/s07_factory.py`.



Find:

```python
    def data_page_body():
        """Build the archive-free Data shell with prefix-correct links."""

        return build_data_page(
```

Replace with:

```python
    def data_page_body():
        """Build Data immediately and start the shared refresh if it is cold."""
        schedule_cold_start()
        return build_data_page(
```

### 3.27. Connect the Data callbacks to the existing manager

Open `cube/app/s07_factory.py`.



Find:

```python
    register_data_callbacks(app, history_repository)
```

Replace with:

```python
    register_data_callbacks(app, history_repository, refresh_manager)
```

### 3.28. Use the standalone page

After saving and restarting the app, open `/data` directly in a fresh browser tab. Wait for the ordinary initial data refresh. Choose Risk History or Market History, choose Identity, Risk Type and Risk Greek, then type in or scroll the Underlying dropdown. Choose the period and click **Load history**.

With no archive, the current observation still appears. With archives, earlier observations appear before the current Market observation. Same-day current data replaces that day’s archived selection, so it is not counted twice. Missing quotes remain missing. With only one date, there is nothing for Play to advance through.

Open Data from Quick Risk and Quick Market once each, then change the dropdown to a different identity and click Load history. The new choice must remain selected. A Quick Risk selection keeps its existing filters when the same identity is reloaded or its period is changed. Selecting a different identity starts a fresh Data-page selection.

## Finish and use the changes

1. Save every edited file.
2. In a notebook opened in the application folder, run this Python cell. It checks syntax without starting the app or calling any connector:

```python
from pathlib import Path

files = [
    "cube/ui/s01_constants.py",
    "cube/ui/s02_aggregation.py",
    "cube/pages/risk/s06_explorertables.py",
    "cube/pages/risk/s02_state.py",
    "cube/pages/risk/s01_common.py",
    "cube/pages/risk/s16_view.py",
    "cube/services/s02_state.py",
    "cube/app/s02_contracts.py",
    "cube/history/s06_repository.py",
    "cube/pages/data/s03_callbacks.py",
    "cube/pages/data/s02_view.py",
    "cube/app/s07_factory.py",
]
for name in files:
    compile(Path(name).read_text(encoding="utf-8-sig"), name, "exec")
print("Python syntax is valid.")
```

3. Start the app using your normal command. Hard-refresh its browser tab with **Ctrl+Shift+R** to load the edited JavaScript.
4. Perform the short browser checks at the end of each chapter. A syntax check cannot establish that a dropdown or refresh behaves correctly in the running app.
5. If an edit needs to be undone, stop the app, restore all the copied application files from the same backup, and remove only the new application files listed above. Start the app and hard-refresh again. Keep all source data and archive files.
