# Quick Risk charts and faster Data choices

This is an implementation guide, not a claim that the live app has been changed. It targets the application code at `2220a3f4839318863a9131e3fef8118d0f82fb7d`, the source used for `v7`.

Implement Part A, check the charts, then implement Part B. The two changes do not depend on each other or on `Hero.md` or `JTD.md`.

**Check your Data layout first.** This GitHub baseline has Risk History / Market History tabs and three selectors with IDs `data-risk-type`, `data-risk-greek`, and `data-underlying`. If your running copy instead has the newer Risk / Market / Both workspace and a “Choose series” editor, you already applied a later guide locally. Do not paste Part B's callback replacements over that different layout: its exact callback IDs and contracts must first be compared with your deployed source. The bounded-search and server-owned-catalog rules below still apply. The repository does not contain that deployed implementation, so this guide does not pretend to provide verified replacements for unseen code.

## Part A — make Quick Risk use the tenor-selector presentation

### 1. Understand what stays and what changes

Keep the exact-identity search, shared filters, the hierarchy table, and “Open in Data”. Replace only the standalone Risk/dRisk chart with the existing tenor-detail panel. This also supplies its small supporting table or surface matrix; the existing expandable hierarchy remains below it.

The current code builds its chart from the hierarchy's **displayed leaves**, which have a 250-leaf limit. Those rows contain Risk/dRisk but not the complete Risk XVA and Risk Hedges fields. A chart drawn from that table can therefore describe only the displayed subset when the result is truncated. Do not solve that by merely renaming dRisk to XVA or raising the table limit.

The new chart reads the existing prepared dashboard in `_RiskDataCache`, scopes it to the exact reported identity, applies the shared filters, and calls the same renderer used after a Risk-table click. It performs no connector refresh and creates no second full-snapshot cache. The chart covers the complete selected identity; the separate hierarchy keeps its existing 250-leaf display limit.

The financial meanings stay the same:

| Display | Existing prepared field | Meaning |
|---|---|---|
| Risk / Total | `risk` | Net risk for the selected positions |
| Risk XVA | `risk expo` | Existing XVA component |
| Risk Hedges | `risk hedges` | Existing hedging component |

The existing validator checks `risk = risk expo + risk hedges`. In `cube/ui/s02_aggregation.py::_derive_and_validate_breakdowns`, supplied components are retained and checked; when both are absent, Product values `Hedge`/`Hedges` contribute to the hedge component and other Product values contribute to the legacy `expo` component. The app displays that component as XVA. Keep your Product classification accurate; this chart does not infer or repair an incorrect mapping. dRisk is a different metric. No connector schema or financial calculation changes are needed here.

### 2. Remove the old chart, then add the view picker

Open `cube/pages/risk/s08_quickrisk.py`.

Remove:

1. The entire `build_quick_risk_figure(...)` function.
2. Its `"build_quick_risk_figure",` entry in `__all__`.
3. `import plotly.graph_objects as go` — it is used only by that removed function.
4. `leaf_frame = pd.DataFrame(leaf_rows)` inside `build_quick_search_pivot` — it becomes unused.
5. This graph from the return value of `build_quick_search_pivot`:

```python
            dcc.Graph(
                figure=build_quick_risk_figure(leaf_frame, selected_indexes),
                config={"displaylogo": False, "responsive": True},
                className="quick-risk-current-chart",
            ),
```

Keep the total-row calculation, `leaf_rows`, table, status, formatting, and all the other imports. Change the nearby comment from “Compute totals and the current chart” to “Compute totals”.

Inside `build_quick_search`, insert the following as a sibling immediately **before** the existing `dcc.Loading` containing `id="quick-search-results"`. Indent it to the same level as that `dcc.Loading`.

```python
html.Div(
    [
        html.Label("Chart view", htmlFor="quick-risk-tenor-view"),
        dcc.Dropdown(
            id="quick-risk-tenor-view",
            options=[
                {"label": "Auto", "value": "auto"},
                {"label": "Tenor Swap", "value": "swap"},
                {"label": "Tenor Option", "value": "option"},
                {"label": "Surface", "value": "surface"},
            ],
            value="auto",
            clearable=False,
            searchable=False,
        ),
        dcc.Loading(
            html.Div(id="quick-risk-tenor-result"),
            type="dot",
            delay_show=160,
        ),
    ],
    className="quick-search-dimension-control",
),
```

### 3. Wire the picker to the existing tenor renderer

Open `cube/pages/risk/s14_workspacecallbacks.py`.

Replace:

```python
from cube.ui.s02_aggregation import apply_filters
```

with:

```python
from cube.ui.s02_aggregation import apply_filters, row_key
from .s05_charts import build_detail_panel_with_state
```

Inside `register_workspace_callbacks`, inside the existing `if refresh_manager is not None:` block, add this callback after `render_current_pivot` and before the callback owning `quick-market-combine-udl.options`. Keep `render_current_pivot` and all Quick Market callbacks unchanged.

```python
        @app.callback(
            Output("quick-risk-tenor-result", "children"),
            Output("quick-risk-tenor-view", "options"),
            Output("quick-risk-tenor-view", "value"),
            Input("quick-search-combine-udl", "value"),
            Input("quick-risk-tenor-view", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("split-filter", "value"),
            Input("dimension-filter-values-store", "data"),
            Input("risk-filter-exclude-applied-store", "data"),
        )
        def render_quick_risk_tenor(
            combine_udl, tenor_view, active_workspace, revision,
            selected_splits, dimension_values, exclude_value,
        ):
            if active_workspace != "quick-risk":
                return None, no_update, no_update
            if not combine_udl:
                return "Choose a Search Risk identity.", no_update, no_update
            try:
                identity = refresh_manager.resolve_history_identity(
                    "risk", str(combine_udl), identity_mode="reported",
                )
                committed = cache.current(refresh_manager)
                if not (
                    int(revision or 0) == identity.source_revision == cache.revision
                ):
                    return "Snapshot changed; waiting for the current revision…", no_update, no_update
                # Scope before filtering/copying. Never mutate the shared cache.
                scope = committed.loc[
                    committed["source type"].isin(identity.source_types)
                    & committed["risk type"].eq(identity.risk_type)
                    & committed["risk greek"].eq(identity.risk_greek)
                    & committed["reported underlying"].eq(identity.underlying)
                ]
                scope = apply_filters(
                    scope, [], list(selected_splits or []),
                    reporting_filter_map(dimension_values),
                    exclude_selected=risk_exclude_selected(exclude_value),
                )
                if scope.empty:
                    return "No positions match this identity and the shared filters.", no_update, no_update
                # Public renderer used by the clicked tenor-selector detail.
                panel, options, _resolved = build_detail_panel_with_state(
                    scope,
                    {"key": row_key({}), "metric": "risk"},
                    "risk",
                    str(tenor_view or "auto"),
                )
                return html.Div([
                    html.H3(str(combine_udl)),
                    html.P(f"Complete selected identity · snapshot {identity.source_revision}"),
                    panel,
                ]), options, (_resolved if _resolved != tenor_view else no_update)
            except (AttributeError, KeyError, LookupError, TypeError, ValueError, RuntimeError) as error:
                app.logger.exception("Quick Risk tenor detail failed")
                return html.Div(
                    f"Quick Risk chart unavailable: {error}", role="alert",
                ), no_update, no_update
```

`row_key({})` is deliberate: the frame has already been scoped to the resolved exact identity. The empty context tells the existing detail renderer to include all of that scoped frame. The display label is never split on `|` to reconstruct an identity.

The revision check prevents combining an identity resolved from one snapshot with rows from another. The normal `data-revision-store` update triggers the chart again when a refresh commits.

### 4. Know what the choices do

Part A requires no changes to `cube/pages/risk/s05_charts.py` or its renderer behavior. Keep any independent type-annotation edits required by `JTD.md` if implementing both guides. No second Plotly implementation is needed.

| Selected data / view | Result |
|---|---|
| Two meaningful axes, Auto | Existing 2D heatmap plus matrix of total Risk |
| Two meaningful axes, Surface | Same heatmap and matrix |
| Tenor Swap | Existing swap chart, summing additive risk across the option axis |
| Tenor Option | Existing option chart, summing additive risk across the swap axis |
| One meaningful swap axis | Risk/Total, Risk XVA and Risk Hedges on the existing tenor chart |
| One meaningful option axis | The same three components against option tenor |
| No meaningful tenor axis | Existing no-tenor explanation and numeric table |

Here “Surface” means the existing **2D heatmap**, not the old Quick Risk 3D surface. Axis availability and ordering come from existing tenor-detail code and connector ranks. Unsupported options are disabled; switching identity resets an invalid view to Auto. A mixed population uses the existing Auto partitioning rather than throwing away rows.

The existing line renderer displays net Risk as a bar named “Total”, with XVA and Hedges as lines. This is the requested tenor-selector presentation, including its existing scale choices. If you later want all three as same-scale lines, change the shared renderer once so Quick Risk and clicked detail remain consistent; that redesign is not required for this fix.

### 5. Check Part A before proceeding

1. Compare one ordinary swap identity in Quick Risk with the same identity opened from the Risk table using identical filters. Check each tenor's Risk, XVA, and Hedges, not just the grand total.
2. Check a two-axis identity: Auto/Surface produces a heatmap and matrix; Swap and Option produce the correct aggregate curves.
3. Check a scalar identity and one with missing tenor labels. Unavailable axes must not create an empty 3D surface.
4. Apply both include and exclude filters. Check that every parent/total still reconciles and that the chart does not retain excluded positions.
5. Add hierarchy dimensions so there are more than 250 leaves. The hierarchy may remain bounded; the chart must still include the complete selected identity. Do not compare its complete totals to a truncated hierarchy without reading that table's coverage notice.
6. Refresh while the chart is open. It must either show one committed revision or the short revision-change message, never a mixture.
7. Confirm Quick Market and “Open in Data” still work. The new chart is current-snapshot presentation; historical playback remains in Data.

## Part B — stop Data choices from blocking the interface

### 1. Fix the actual hot path

Quick Risk/Quick Market search a committed identity catalog and send at most 100 options, keeping the selected value included. They do not send all positions or rebuild a connector on every keystroke.

Data needs an **archive** identity catalog because an instrument may exist in history but no longer exist today. Replacing it with today's Quick Risk catalog would silently remove historical-only instruments.

The pinned code already builds an archive-free page shell. Afterwards it does this:

```text
archive metadata check
  -> repository.catalog()
  -> cold archive validation + DISTINCT identity queries, if needed
  -> serialize every catalog entry into data-history-catalog-store
  -> three dependent server selector callbacks receive that catalog
  -> recreate/validate its typed entries and send all matching underlyings
```

There are two different delays: the first archive scan can be expensive, and shipping/rebuilding/rendering all choices creates avoidable work. This fix removes the latter and leaves the already-cached archive catalog on the server. Cold archive preparation can still take seconds; do not label the first archive load instant without measuring it.

Keep navigation independent and show “Preparing archive choices…” in the Data controls while that work runs. Do not add a global loading overlay around Data, poll all data frames, call the live connectors, or introduce another cache of full histories. The existing global-loader code already says generic Dash callbacks should not create refresh feedback.

### 2. Keep the catalog on the server; store only its generation

Open `cube/pages/data/s03_callbacks.py`.

In `load_archive_catalog`, replace its final line:

```python
return catalog.to_mapping(), status
```

with:

```python
return {"generation": catalog.generation}, status
```

The return type remains a dictionary plus status. `data-history-catalog-store` now means “the catalog is ready for this generation”; it no longer contains identities. Keep that store and its ID.

In `refresh_archive_catalog`, remove only this condition from the existing cache-hit `if`:

```python
and isinstance(current.get("entries"), list)
```

Keep the mapping check and generation equality check. Keep `repository.catalog()` and its existing cache/invalidation machinery. Do not cache a mutable selection globally.

### 3. Make the two small selectors use the server's catalog

Still in `s03_callbacks.py`, in `choose_risk_type`, replace:

```python
options = risk_type_options(raw_catalog, kind, identity_mode)
```

with:

```python
options = risk_type_options(repository.catalog(), kind, identity_mode)
```

In `choose_risk_greek`, change only the first argument to `risk_greek_options` from `raw_catalog` to `repository.catalog()`.

In both functions, widen the **outer final** `except (HistoryValidationError, TypeError, ValueError):` to include `OSError`. Keep their existing `raw_catalog is None` branches: those allow a Quick handoff to prefill the controls before archive choices are ready. Keep the existing small Risk Type and Greek dropdowns; they are useful context and do not need to become another application architecture.

### 4. Cache each immutable identity's key once

Open `cube/history/s01_models.py`. Add:

```python
from functools import cached_property
```

Find `class HistoryCatalogEntry`, then its `key` property. Replace **only that property's decorator**:

```python
@property
def key(self) -> str:
```

with:

```python
@cached_property
def key(self) -> str:
```

Keep the entire key body unchanged. A catalog entry is a frozen dataclass; its identity does not change. The generated SHA key is therefore unchanged, but repeated searches no longer repeat JSON serialization and SHA calculation for the same entry. This is one cached string per existing identity, discarded with that catalog; it is not another frame/history cache.

### 5. Bound the Underlying choices and reuse Quick search normalization

Open `cube/pages/data/s01_selection.py`. Add these imports:

```python
from cube.domain.s10_search import _dropdown_search_terms, _dropdown_search_label
from cube.pages.risk.s10_search import _combine_udl_browser_search
```

These are the existing Quick-search normalizers. Reusing them preserves punctuation/case handling and Dash's browser search aliases. No new package is needed.

Replace the entire `underlying_options(...)` function with:

```python
def underlying_options(
    raw_catalog: object,
    kind: object,
    identity_mode: object,
    risk_type: object,
    risk_greek: object,
    *,
    search_value: str | None = None,
    limit: int = 100,
    include: object = None,
) -> list[dict[str, str]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("option limit must be a positive integer")
    entries = matching_entries(
        raw_catalog, kind=kind, identity_mode=identity_mode,
        risk_type=risk_type, risk_greek=risk_greek,
    )
    terms = _dropdown_search_terms(search_value)
    counts = Counter(entry.identity.underlying for entry in entries)
    options = []
    selected_option = None
    for entry in entries:
        if len(options) >= limit and (include is None or selected_option is not None):
            break
        label = entry.identity.underlying
        if counts[label] > 1:
            label = f"{label} · {', '.join(entry.identity.source_types)}"
        search = _dropdown_search_label(label)
        matches = all(term in search for term in terms)
        selected = entry.key == include
        if not selected and (len(options) >= limit or not matches):
            continue
        option = {
            "label": label, "value": entry.key,
            "search": _combine_udl_browser_search(label),
        }
        if selected:
            selected_option = option
        if len(options) < limit and matches:
            options.append(option)
    if selected_option is not None and not any(
        option["value"] == selected_option["value"] for option in options
    ):
        options = options[:limit - 1] + [selected_option]
    return options
```

The maximum is **100 total options including a retained selection**, not 100 rows of financial data. Every archive identity remains searchable. Empty search shows the first page of choices; type more letters to reach another identity. Duplicate names retain their Source Type label and exact opaque key. A selected item may stay visible even when it does not match the typed text, as in Quick search.

### 6. Wire Underlying typing into the existing callback

In `cube/pages/data/s03_callbacks.py`, find the decorator directly above `choose_underlying`. Add this `Input` immediately before `State("data-underlying", "value")`:

```python
Input("data-underlying", "search_value"),
```

Keep the other Inputs/States and all three Outputs in their current order. Replace the whole `choose_underlying` function, leaving its decorator in place, with:

```python
    def choose_underlying(
        raw_catalog, kind, identity_mode, risk_type, risk_greek,
        raw_request, search_value, current, raw_handoff, consumed_nonce,
    ):
        if risk_type is None or risk_greek is None:
            return [], None, True
        if raw_catalog is None:
            try:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                if (
                    handoff.kind == str(kind or "risk").casefold()
                    and handoff.identity.identity_mode == str(identity_mode or "reported").casefold()
                    and handoff.identity.risk_type == str(risk_type)
                    and handoff.identity.risk_greek == str(risk_greek)
                ):
                    return [
                        {"label": handoff.identity.underlying, "value": QUICK_HANDOFF_ENTRY_KEY}
                    ], QUICK_HANDOFF_ENTRY_KEY, False
            except (HistoryValidationError, TypeError, ValueError):
                pass
            return [], None, True
        try:
            catalog = repository.catalog()
            preferred = None
            try:
                handoff = _requested_history_handoff(raw_request)
            except (HistoryValidationError, TypeError, ValueError):
                try:
                    handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                except (HistoryValidationError, TypeError, ValueError):
                    handoff = None
            if (
                handoff is not None
                and handoff.kind == str(kind or "risk").casefold()
                and handoff.identity.identity_mode == str(identity_mode or "reported").casefold()
                and handoff.identity.risk_type == str(risk_type)
                and handoff.identity.risk_greek == str(risk_greek)
            ):
                preferred = catalog_key_for_handoff(catalog, handoff.to_mapping())
            use_preferred = (
                ctx.triggered_id == "data-history-request-store"
                or (
                    ctx.triggered_id == "data-history-catalog-store"
                    and current in (None, QUICK_HANDOFF_ENTRY_KEY)
                )
            )
            if not use_preferred:
                preferred = None
            options = underlying_options(
                catalog, kind, identity_mode, risk_type, risk_greek,
                search_value=search_value, limit=100,
                include=preferred or current,
            )
            selected = selected_value(options, current, preferred)
            return options, selected, selected is None
        except (OSError, HistoryValidationError, TypeError, ValueError):
            return [], None, True
```

The added `search_value` argument is between `raw_request` and `current`, matching the new Input position. Selection is retained while typing. A previous loaded request must not keep forcing its preferred instrument back into the dropdown on every search keystroke.

In `cube/pages/data/s02_view.py`, keep `data-underlying` searchable and initially `options=[]`. Add this placeholder to that dropdown:

```python
placeholder="Type an underlying — up to 100 matches",
```

Keep the existing `data-catalog-status` beside the controls; change its initial text to “Preparing archive choices…”. If adding `dcc.Loading`, wrap only the identity-control block, with `delay_show=160`; never wrap the shared navigation or whole page in a blocking overlay. The textual status alone is sufficient for this minimal patch.

### 7. Resolve a chosen key on the server when loading history

In `choose_history_request` in `s03_callbacks.py`, find:

```python
handoff = direct_history_handoff(
    raw_catalog,
    entry_key,
    kind=kind,
    reset_generation=reset,
)
```

Change only `raw_catalog` to `repository.catalog()`. Widen that function's outer final `except (HistoryValidationError, TypeError, ValueError) as error:` to include `OSError`.

Keep the `QUICK_HANDOFF_ENTRY_KEY` branch, nonce handling, reset handling, strict identity validation, archive row limits, and player callbacks unchanged. The browser sends an identity key and a generation marker; the server resolves the key in the real catalog before building the same existing `HistoryQuery`.

### 8. Check every catalog consumer

Run from the repository root:

```powershell
rg -n 'data-history-catalog-store|raw_catalog|catalog.to_mapping' cube/pages/data
```

For this baseline, verify these six consumers:

| Function | After the change |
|---|---|
| `load_archive_catalog` | Returns only generation + status |
| `refresh_archive_catalog` | Compares generation only |
| `choose_risk_type` | Uses typed `repository.catalog()` |
| `choose_risk_greek` | Uses typed `repository.catalog()` |
| `choose_underlying` | Uses typed catalog + bounded search |
| `choose_history_request` | Resolves the selected key against the typed catalog |

Do not pass the generation-only dictionary into `HistoryIdentityCatalog.from_mapping` or `direct_history_handoff`. Those functions still correctly require actual catalog entries. Do not loosen their validators to accept the new marker.

### 9. Verify behavior and measure the remaining delay

1. Restart, open Data without loading history, and immediately navigate back to Risk. Navigation must stay usable while choices prepare. Check a cold start and a second visit separately.
2. In browser Network, inspect responses for `data-history-catalog-store`: they should contain generation/status only, never a giant `entries` array. Underlying option responses must contain at most 100 choices.
3. Test case differences, punctuation (`EUR/USD` versus `eurusd`), multiword typing, a selected value beyond the first 100, and two identities with the same display name but different Source Types.
4. Choose an archived-only identity that is absent from today's Quick Risk search. It must still be discoverable and load normally.
5. Test Risk Reported/Raw modes, Market, direct entry, Quick Risk/Quick Market handoff, browser back/forward, cache clear, and a newly completed archive generation. A metadata refresh must not erase an unrelated user's in-browser selection.
6. After choosing a different instrument, type again: the previous loaded request must not restore its old instrument.
7. Verify that no history bundle loads merely because Underlying search text changed. Existing explicit Load history and Quick handoff are the query triggers.
8. For residual slowness, inspect existing log spans `history.archive.open` and `history.catalog.query`. The first measures opening/validating the archive generation; the second measures the distinct-identity queries. Compare those durations with the browser's response size and rendering time.

If the **server** is still occupied for five seconds on a cold catalog, this patch has not accelerated that scan. If navigation requests queue behind it, inspect CPU/storage contention and whether the deployed server matches `gunicorn.conf.py`: one `gthread` worker, with `GUNICORN_THREADS` defaulting to four threads. Keep one worker: snapshot/progress state is process-local, so adding workers is not a safe shortcut for this UI issue. No thread tuning is required by this patch. If requests finish but the **browser** stalls, inspect JSON size and component/Plotly rendering. These are different problems; another unmeasured cache or a renamed spinner does not fix both. This guide removes the proven eager-catalog transfer/reconstruction and unbounded-dropdown work first.

## Verification and rollback

The guide's candidate replacements were applied to an isolated copy of the pinned source. Local checks verified Python syntax and registered callback arguments; a 300-tenor identity retained all 300 chart points and correct XVA/hedge totals; heatmap, swap and option views kept connector order and sums; invalid views reset; shared filters and revision mismatch were handled. A 501-identity archive fixture verified the 100-option cap, retained selection outside the first 100, exact archive-only selection, metadata-only payload and typing without restoring the previous loaded request. These are local correctness checks, not a production latency measurement. Update existing tests that expected a full catalog in the browser or imported the deliberately removed `build_quick_risk_figure`.

For implementation, run your current Quick Risk, Data, and tenor-detail tests. Add regression cases for the complete chart above the 250-leaf table limit, shared filters, empty/scalar/swap/option/surface shapes, 100-option cap, selected-value retention, and historical-only identities. Check `git diff --check` before committing.

Rollback Part A by reverting only its edits to `s08_quickrisk.py` and `s14_workspacecallbacks.py`; the shared chart code remains unchanged. Rollback Part B as one group across `s01_models.py`, Data `s01_selection.py`, `s02_view.py`, and `s03_callbacks.py`. Do not revert only the generation store or only a consumer, because their contracts must match. Both parts change presentation/selection only; they do not rewrite archived data, risk values, or connectors.
