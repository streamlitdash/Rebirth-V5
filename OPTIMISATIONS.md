# OPTIMISATIONS — Rebirth V5 performance audit and exact change guide

Reviewed **6 September 2026** against `streamlitdash/Rebirth-V5` main commit **`8f65a1124e54702597347967c7064eb4f7edf133`**, plus the local Statics and Risk index-cache changes recorded below. Publication destination: **`streamlitdash/Rebirth-V5`, branch `v4`**. The repository and this branch are public. The review, patch and test results remain based on the identified main commit plus the stated local changes; `v4` was not the tested baseline.

Read in order or jump to the [existing cache fix](#2-the-cache-fix-repeated-in-full), [Risk/UI changes](#3-risk-search-charts-and-browser-work), [Data/Stock/P&L history](#4-data-stock-pl-and-history-access), [pipeline/runtime changes](#5-startup-refresh-financial-preparation-and-operations), [implementation order](#7-recommended-order-and-changes-to-avoid), or [validation and rollback](#8-validation-rollout-and-rollback). The appendices include the full cache diff, its complete diagnostic and the source inventory.

## 1. Status, scope and the first decisions

This is a source-wide audit of the main execution paths: startup, refresh, adapters/validation/calculations, reporting, tenor reduction, search, Risk, Data, Stock, P&L, Statics, history/archive access, browser rendering, logging and deployment. It identifies concrete remaining opportunities and also records existing optimisations worth preserving. It cannot certify that no other bottleneck exists in a private connector or a production workload that was not supplied.

**Publication scope:** this Markdown guide, including the exact cache patch as text. Publishing the guide does not apply that patch to the destination branch, merge application code into `main`, or deploy the application. Future sections are implementation proposals unless explicitly marked **implemented locally**. **Measured** identifies an isolated probe, not an integrated application change.

**Implemented locally before this audit:** the Statics Write picker reset and the Risk Explorer index-cache change. The cache patch is reproduced in full in Appendix A and explained step by step in section 2. It preserves the numeric/quote calculation rules while changing reuse and retention. The full local tree passed **686 tests, 56 warnings in 116.04 seconds**; that tree also contains the earlier Statics/tool additions. This count is evidence for that exact local tree, not a promised test count for applying the cache patch alone to an older checkout.

**Reported production scale:** approximately 100k rows and 300–400 portfolios. It remains unconfirmed whether 100k means raw positions across books or already aggregated groups before books are split. Those are materially different sizes. No recommendation assumes a dense 100k × 400 cross join, and no benchmark below claims to reproduce that case.

The highest-value direction is to bound allocations and browser output first, then remove repeated work for the same validated data. Do not replace the application with a new backend, add a queue for ordinary clicks, or cache every possible display combination. Keep one financial source of truth and make each display request small.

### 1.1 How to read and apply the recommendations

Each proposal gives the source function, the current trigger/cost, exact placement and replacement instructions, and validation requirements. A complete code block marked proposed is not a claim that it has been integrated. Broader UI proposals require all listed callback/state/schema changes together; a short helper alone is not the finished feature.

Blocks that replace only a signature, expression or branch are fragments for the named existing location. Complete functions and callbacks are identified explicitly. Do not execute every block as a standalone script or replace a whole module with a fragment.

Apply one coherent change at a time. Preserve the existing index-cache patch before following recommendations that refer to it. Use file path plus function name as the authority; line numbers describe the audited checkout and move after edits. Validate totals, unavailable values, row identity and source revision before judging timings.

The audit and guide introduce no additional runtime changes beyond those already implemented in the prior cache turn. Temporary probe scripts use synthetic/checked-in data and live outside the application package. Their measurements distinguish component bytes, accounted retained data and process/browser memory rather than equating them.

### 1.2 Current benchmark evidence

The existing `tools/s03_benchmark.py` was run again during this audit, without changing thresholds. All nine reported budgets passed:

| Existing benchmark | Time | Budget | Actual scope |
|---|---:|---:|---|
| Fresh process import | 1,276.588 ms | 2,000 ms | No data reads/network during import |
| Spot refresh | 1,449.467 ms | 2,000 ms | 10,572 dashboard rows, 502 portfolios |
| Prepare scaled data | 344.282 ms | 2,500 ms | 100,000 raw rows, 500 portfolios |
| Default filter | 30.723 ms | 500 ms | 100,000 rows |
| Cross render labelled `100k` | 52.545 ms | 1,500 ms | **8,460 scoped input rows**, default expansion |
| First Risk history | 1,275.784 ms | 2,500 ms | 524 rows, 262 dates |
| First Market history | 385.802 ms | 2,000 ms | 1,572 rows, 262 dates |
| First Stock history | 757.702 ms | 2,500 ms | One exact identity, 262 dates |
| First P&L overview | 1,527.570 ms | 3,500 ms | 4,303 summary rows |

These are fixture measurements on the review machine. They do not show browser layout time, peak RSS, an all-open 100k-row tree, hundreds of exact Stock identity queries, or production connector latency. The `interaction.cross_render_100k` name describes the originating fixture; `run_benchmarks` filters it to one Risk type before the table operation. The `rows` result is the actual table input and must accompany the name.

**Exact measurement improvement:** in `tools/s03_benchmark.py::run_benchmarks`, rename that label to `interaction.cross_render_scoped` or preserve the label with an explicit scoped-row field in reports. Add a separate test operation using the actual `_RiskDataCache`/registered callback path, repeated open-state changes, and actual filtered row count. Reuse the complete synthetic comparison script in Appendix B as the starting point. Record visible rows and serialized response bytes as well as elapsed time. Do not silently change the fixture distribution or raise a threshold to make a failed production sample appear acceptable.

For production investigation, record four separate observations: (1) input/prepared/filtered rows and distinct hierarchy-book combinations; (2) index construction versus visible-component construction time; (3) response bytes and visible row/cell count; (4) worker memory and browser responsiveness. The existing `perf_span` helper can emit bounded counts; there is no need for a new monitoring system. Do not serialize a complete table a second time on every request just to log its size—capture actual response bytes or use an isolated probe.

## 2. The cache fix, repeated in full

The original design prepared numeric/quote indexes once per table build, then cached the finished component tree by display state. That avoided repeated work within a render, but changing open rows could still rebuild the same index and retain another complete table. The new local design retains the compact index for an unchanged data/measure scope and constructs only the requested visible table without retaining Explorer display variants.

The scope is deliberately precise: standard Cross, including Credit Single, gains numeric-index reuse. SplitVA and Credit Multi stop retaining Explorer component trees but still use their existing reductions. Aggregate P&L and Top Promotions keep their separate 24-entry workspace component cache. This is not yet a displayed-row cap or a guarantee against very large visible tables.

### 2.1 Implement the reusable Risk index

This is now an **applied local change**, following the cache discussion. The original `main` creates `HierarchyAggregationIndex` inside each new Cross table build and caches up to 24 finished table variants. The delivered Explorer instead reuses the numeric/quote index for the same filtered data and Credit measure, and renders the requested visible rows without retaining complete Explorer tables.

The code changes are in four existing files; tests are in one existing module. **Appendix A contains every exact added/removed line, including all imports and regression tests.** Follow the numbered placement instructions below with those hunks, or apply the complete Appendix A patch once to the stated baseline. Do not apply it twice if the cache changes are already present.

1. **`cube/ui/s02_aggregation.py`, `_MarketQuoteIndex`:** immediately after `_means_by_group` and before `value`, add the `memory_bytes` property from Appendix A. It counts `_row_quote_codes`, `_quote_values`, `_quote_to_option`, `_option_to_swap` and `_swap_to_underlying`. Remove none of the quote identity or hierarchical averaging code.
2. **Same file, `HierarchyAggregationIndex`:** replace its request-local docstring with the read-only reusable-scope contract. Immediately after `__init__` and before `aggregate`, add its `memory_bytes` property. Account for the retained frame, numeric array and all three quote indexes. Leave `aggregate` and the financial validation logic unchanged. The accounting is conservative retained-data accounting, not a measurement or cap of process RSS or construction peaks.
3. **`cube/pages/risk/s02_state.py`, imports/constants:** add `HierarchyAggregationIndex` and `apply_credit_measure` to the aggregation imports, import `CREDIT_MEASURES`, and add `_HIERARCHY_CACHE_MAX_ENTRIES = 4` and `_HIERARCHY_CACHE_MAX_BYTES = 256 * 1024 * 1024` after the existing filter-cache limits. These are internal initial budgets, not claims that every production worker can spare that memory.
4. **Same file, `_RiskDataCache.__init__`:** immediately after `_filtered_bytes`, initialize `_cache_epoch`, `_hierarchies` and `_hierarchy_bytes` exactly as shown. Each index entry retains the source frame, the index and its accounted size. Strong source references make `id(frame)` keys safe from object-ID reuse while retained.
5. **Same class, `replace_frame` and `clear_reconstructable`:** after clearing filter bytes, increment `_cache_epoch`, clear `_hierarchies`, and zero `_hierarchy_bytes`. Preserve all existing invalidation of market/reduction/promotion/workspace caches. This includes Clear Cache even when the financial revision has not changed.
6. **Same class, `filtered`:** after `current(manager)`, check under `_lock` that the returned frame is still `_frame`; retry if refresh replaced it. Capture both revision and epoch under that same lock. Before publishing a newly filtered result, retain the existing revision check and add the epoch check. A result whose clear epoch changed can finish its request but is not retained. This closes the old frame/new revision pairing window.
7. **Same class, immediately before `rendered`:** add `hierarchy_index` and `render_explorer` from the complete patch. The key is the exact immutable filtered-frame identity plus normalized Credit measure. Existing filter keys already distinguish data revision, filters, exclusion, splits, product/family, promotion generation and tenor reduction; do not create a parallel manual copy of those keys. Display expansion, metric visibility, sort and reported/raw presentation do not change this numeric index. Build under the existing reentrant computation lock, publish only in the unchanged epoch for an owned source frame, bypass retention for oversized/unowned results, and evict oldest entries until both limits hold. `render_explorer` keeps serialized construction but retains no component tree.
8. **Same class, `rendered`:** capture the epoch before starting a workspace build and check it before retaining the result. Keep this method for Aggregate P&L and Top Promotions. Their existing 24-entry component cache is separate and remains in use; this change is not a claim that all rendered caches across the application have been removed.
9. **`cube/pages/risk/s06_explorertables.py`, `build_risk_table`:** append the optional keyword `aggregation_index` to the signature. A supplied index's `frame` is authoritative for both row membership and metrics. Only construct a new index when none was supplied, preserving standalone callers. Keep the existing row renderer, quote treatment, number formatting and breakdowns.
10. **`cube/pages/risk/s07_explorer.py`, `render_active_risk_table`:** remove both `render_key = json.dumps(...)` blocks and the now-unused `json` import. Replace the two `cache.rendered(render_key, builder)` calls with `cache.render_explorer(builder)`. In `build_main_component`, preserve the Credit Multi early return. For standard Cross/Credit Single, replace the direct Credit frame transformation with `cache.hierarchy_index(filtered, credit_measure=...)`, using the selected/default Credit measure only on Credit. Pass that index into `build_risk_table`. Leave SplitVA's existing Credit transformation and aggregation rules intact.
11. **`tests/s19_riskfilters.py`:** add the two module imports and all cache regressions in Appendix A immediately after `test_render_cache_serializes_and_deduplicates_concurrent_builds`, before `test_full_tenor_mode_does_not_read_catalog_or_call_matrix_provider`. Keep the pre-existing tests. The new cases exercise real registered callback reuse, display membership, unchanged source data, independent quotes, Credit/filter scope, memory eviction, concurrency, refresh/clear and workspace stale publication.
12. **Validate and use:** run the focused command below, then the full delivered-tree checks in section 8. Restart the local application normally. No new UI setting is required. Open/close Risk branches and metric breakdowns as before; the unchanged data scope reuses the index. Change filters/measure or refresh and the corresponding data/index is used. Clear Cache drops retained indexes. Do not add Portfolio to shared registries as part of this change.

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/s06_ui.py tests/s19_riskfilters.py tests/s33_riskstate.py tests/s34_riskpivot.py tests/s36_riskarch.py -q
```

The 256 MiB budget bounds accounted retained index data in one cache instance. Other application data, the existing filtered-frame cache, workspace component caches, Python object overhead and temporary build allocations also consume memory. Oversized scopes still calculate without retention, so they can rebuild on subsequent expansion. Do not present the budget as a guarantee against out-of-memory failures.

This patch improves **index reuse**, not every part of table rendering. Visible rows are still rebuilt/serialized on each request, and returning to an identical view can cost more HTML construction than the old finished-table hit. SplitVA and Credit Multi stop retaining Explorer component trees but still use their existing per-render reductions; they do not gain the Cross numeric index. No row pagination, branch insertion protocol, new Portfolio filter or total visible-row cap was implemented. Those remain necessary follow-up work for unrestricted Portfolio display at the reported scale.

### 2.2 Reproduce the scoped capacity comparison

Appendix B contains the complete `cache-scale-probe.py` diagnostic. Save it next to a checkout named `repo`, then run it with that checkout's dependency environment. It constructs labelled synthetic **100,000 raw positions across 400 portfolios**, sharing 250 quotes; it does not read or write production sources. Its output is `cache-scale-results.json` beside the script. If your checkout has another name, update only its `ROOT / 'repo'` path references first.

```powershell
& '.\.review-venv\Scripts\python.exe' cache-scale-probe.py
```

The script compares the existing standalone fresh-index renderer with the new supplied-index path for four small visible scopes, and asserts exact serialized table equality and conserved Risk/P&L/quote values. It retains one index and no Explorer component trees. The output includes every measured time and accounted byte count. This is a controlled server-side comparison, not a browser benchmark, process-memory profile or approval to expand 100k grouped rows into books. Its full results are recorded in section 8.

To roll back this cache change independently, reverse only the four Risk/aggregation file hunks and the new s19 imports/tests in Appendix A. Keep the unrelated Statics fix and optional tools. Restart and rerun the focused tests. The cache patch changes no archive, connector or persisted financial data.

## 3. Risk, search, charts and browser work

### Risk, UI, Search and browser performance audit

Audit date: 2026-09-06. Source: the current local Rebirth-V5 checkout, including the already-applied hierarchy-index reuse patch. This section is read-only: every change below is a **proposal**, except the existing optimisation inventory. The row-scoping and detail-scoping probes ran outside the repository. They are not full application benchmarks.

#### What to prioritise

| Order | Finding | Confidence | Main benefit |
| --- | --- | --- | --- |
| 1 | Put a server-side visible-row budget on all three Explorer renderers before Portfolio expansion | High: unbounded recursion is explicit | Bound Python component creation, response size and browser DOM size |
| 2 | Group siblings once instead of scanning the same parent frame once per child | High; bounded 100k-row/400-sibling probe | Avoid repeated string conversion and whole-parent boolean scans |
| 3 | Stop building undisplayed Credit Multi/Split VA totals | High: visibility is known before calculation | Avoid full-scope calculation for cells deliberately left blank |
| 4 | Reuse one surface pivot for the Risk chart and its matrix | High: the same function is called twice | Remove duplicated grouping, ordering and allocations |
| 5 | Reuse the already-selected detail scope | High; 18 direct comparisons passed | Remove a repeated full-frame/context scan |
| 6 | Filter Search using only the selected columns | High structural confidence; performance unmeasured | Avoid copying all position columns per candidate identity |
| 7 | Batch column resizing and restrict rectangle selection to requested rows | High structural confidence; browser timing still required | Reduce main-thread work during mouse gestures |
| 8 | Profile the remaining per-node sums and shared render lock before introducing more caches | Confirmed remaining work, uncertain benefit of replacement | Avoid building a second overcomplicated caching system |

The first item addresses capacity. The others reduce avoidable work. None establishes that a 100k-row dataset expanded into hundreds of portfolios is safe to send in one response. A row count is not a count of source positions: the same source positions can contribute to many displayed parent/child rows.

#### 1. Bound the visible Explorer tree before constructing more HTML

Current source: `cube/pages/risk/s06_explorertables.py::build_tree_rows` at line 138; recursive call around line 316. `build_risk_table` starts at 335, `build_alt_risk_table` at 477, and `build_credit_multi_table` at 646. Closed branches already skip their descendants. There is no shared limit across the branches that are open. Each visible row constructs a label, buttons, cells, attributes and styles. The new index cache does not remove that output cost.

The smallest useful intermediate safeguard is a shared **render budget**, with a visible warning. It must be applied while constructing rows. Calling `body_rows[:2000]` after building everything is not a capacity fix. Do not truncate the source frame: financial totals must use the full filtered scope.

Exact proposed steps:

1. In `s06_explorertables.py`, immediately above `build_tree_rows`, add:

```python
_EXPLORER_TREE_ROW_LIMIT = 1999  # Plus the existing TOTAL row.


def _tree_limit_notice(budget: dict[str, int | bool]) -> list[html.Div]:
    if not budget["truncated"]:
        return []
    return [
        html.Div(
            f"Showing at most {_EXPLORER_TREE_ROW_LIMIT + 1:,} hierarchy rows. "
            "Some hierarchy rows are "
            "omitted. Totals include the full filtered scope. Collapse a "
            "branch or narrow the filters to see the remaining rows.",
            className="detail-note",
            role="status",
        )
    ]
```

2. Append this parameter to `build_tree_rows` after `underlying_sort_metric`:

```python
    render_budget: dict[str, int | bool] | None = None,
```

3. Inside its `for value in ordered_unique(...)` loop, before `next_context = ...`, add:

```python
        if render_budget is not None and int(render_budget["remaining"]) <= 0:
            render_budget["truncated"] = True
            break
```

4. Immediately after the existing `rows.append(html.Tr(...))` statement completes, before `if can_expand and is_open:`, add:

```python
        if render_budget is not None:
            render_budget["remaining"] = int(render_budget["remaining"]) - 1
```

5. In the recursive call to `build_tree_rows`, add `render_budget=render_budget`. The **same object** must be passed to all descendants; resetting 1,999 for each child would not bound the tree. Do not initialise a new budget inside `build_tree_rows`; initialise it only in each top-level builder as in step 6.

6. In each of `build_risk_table`, `build_alt_risk_table` and `build_credit_multi_table`, after the empty-frame return and before building the TOTAL row, add:

```python
    render_budget: dict[str, int | bool] = {
        "remaining": _EXPLORER_TREE_ROW_LIMIT,
        "truncated": False,
    }
```

7. Pass `render_budget=render_budget` into that builder's top-level `build_tree_rows(...)` call.

8. In each builder's final `html.Div([...], className="risk-table-wrap...", ...)`, add `*_tree_limit_notice(render_budget),` as the first item in the child list. Evaluate this after the tree has been built, as those functions already do.

9. Leave the default `render_budget=None` for direct callers until their separate presentation requirements are reviewed. One such caller exists in `cube/pages/risk/s13_workspacetables.py::build_top_book_exposures` at line 438; it is a separate Top Book helper, not the current ranked Top Promotions table. This change explicitly covers the three Explorer views and does not claim to bound every table in the application.

10. Keep Portfolio itself out of the hierarchy until this bound is tested. If inline Portfolio is then added, use the already-documented deepest-leaf approach and include it in row identity. Prefer a 50-row server-paged Portfolio breakdown for large scopes. That pagination is a separate feature; the budget above does not pretend to implement it.

Correctness rules: TOTAL and every displayed parent still aggregate all matching positions; omitted rows must be disclosed; no summary should be labelled as a total of only the visible rows; stale action-token validation must remain; the row-budget mechanism cannot alter quote aggregation or source data. The warning deliberately does not claim an exact omitted-row count because calculating that would require walking the unrendered tree.

Regression/measurement: extend `tests/s06_ui.py` with a small patched limit (for example 8 tree rows), two open sibling branches and grandchildren. Count `html.Tr` in the final body: at most nine including TOTAL. Verify the warning appears only when a further row was suppressed, the grand total is unchanged, and collapsing a branch frees budget for later branches. Repeat for Cross, Split VA and Credit Multi. Run `tests/s19_riskfilters.py` to retain action/callback correctness. On representative 100k-row/400-portfolio data measure server build time, JSON bytes, process RSS, browser response transfer and browser mount time at 500, 1,000 and 2,000 displayed rows. The suggested 2,000 is an initial guard, not a measured universal safe limit.

Rollback: remove the helper, budget argument and the three caller additions together. Do not disable the warning while keeping truncation.

#### 2. Group siblings once instead of repeatedly rescanning their parent

Current source: `build_tree_rows`, especially `scoped = tree_scope(frame, group_column, value)` at line 170. `cube/ui/s02_aggregation.py::tree_scope` calls `frame_for_context`, which converts the group column to strings and builds a full-length comparison mask for each child. With 400 children of a 100k-row parent this repeatedly inspects the same parent. The reusable numeric index accelerates the sums **after** this scoping step; it does not currently index branch membership.

The minimal change does not need a new persistent hierarchy cache. Build child-position groups once per visited parent and retain the existing special handling for the promoted `Other` branch.

Exact proposed steps:

1. In `build_tree_rows`, after `if group_column is None: return rows` and before the `for value in ordered_unique(...)` loop, add:

```python
    positions_by_value = frame.groupby(
        frame[group_column].astype(str),
        sort=False,
        dropna=False,
    ).indices
```

2. Replace only `scoped = tree_scope(frame, group_column, value)` with:

```python
        scoped = (
            tree_scope(frame, group_column, value)
            if group_column == "display bucket" and value == "Other"
            else frame.iloc[positions_by_value[value]]
        )
```

3. Keep `ordered_unique(...)`, `visible_tree_level(...)`, `next_context`, `row_key(...)` and the existing recursion unchanged. Authoritative tenor sorting and promotion rules remain their responsibility. The row budget in item 1 should be checked before creating each child scope.

4. Do not replace the promoted `Other` fallback with a plain group lookup: `tree_scope` excludes reported identities that are already promoted elsewhere in the same parent. That is financial membership logic, not incidental overhead.

A bounded local probe using 100,000 rows and 400 ordinary group labels produced identical group sums: repeated `tree_scope` took **0.3030 s**, grouped positions took **0.04065 s**, about **7.46× faster for this scoping-only loop**. This is one run on synthetic data, not a claimed sevenfold speed-up of the entire app. Mixed integer/text label comparisons also matched for visible labels. The probe is `probe-risk-ui-optimisations.py` outside the repo.

Before implementation, add a component-level old/new comparison covering reported/raw identity, sparse tenor levels, promotion enabled/disabled and `Other`. Include duplicate DataFrame indices and mixed `1`/`"1"` labels; positions must be positional (`iloc`), never assumed to be the DataFrame's index labels. The existing 100k-row performance fixture should compare cold and repeated expanded views with the same numeric cache. No new cache invalidation is needed for this local-per-parent grouping.

#### 3. Skip Credit Multi and Split VA computation when the cells are intentionally blank

Current source: `build_alt_risk_table::dimension_cells` at line 505 calculates a pandas groupby and total before `should_show_sum` decides whether anything may be displayed. `build_credit_multi_table::measure_cells` at line 672 calls `credit_measure_values` six times even when `should_show_sum` is false. The helper allocates masks and series and checks connector completeness; the unused TOTAL Risk row alone can touch the entire selected frame six times. `build_credit_multi_table` also recomputes measure availability at line 755 despite having `measure_completeness` already.

Exact proposed steps for Credit Multi:

1. Immediately after `show_value = should_show_sum(selected_metric, context)` in `measure_cells`, add:

```python
        if not show_value:
            return [
                html.Td(
                    "",
                    className=(
                        "metric-cell credit-measure-cell metric-cell-inert "
                        "number-positive"
                    ),
                    **{"data-metric": f"{selected_metric}:{measure}"},
                )
                for measure in CREDIT_MEASURES
            ]
```

2. Replace the `missing_measures = [...]` expression with:

```python
    missing_measures = [
        measure for measure in CREDIT_MEASURES if not measure_completeness[measure]
    ]
```

3. Keep the existing helper for displayed cells. Do not replace all calls with precomputed full-frame numbers without testing partial connector availability and Cross Gamma sources. `credit_measure_values` makes a local completeness decision as well as accepting the outer completeness flag. A naive precompute can blank a locally complete subgroup or leak partial values. P&L is intentionally repeated across measures; summing the six measure columns would double-count it.

Exact proposed steps for Split VA:

1. Add the following at the start of `dimension_cells`, before its groupby:

```python
        show_value = should_show_sum(selected_metric, context)
        if not show_value:
            return [
                html.Td(
                    "",
                    className=(
                        "metric-cell alt-dimension-cell metric-cell-inert"
                        + (" total-column" if value == "Total" else "")
                        + " number-positive"
                    ),
                    **{"data-metric": f"{selected_metric}:{value}"},
                )
                for value in [*dimension_values, "Total"]
            ]
```

2. Remove the later duplicate `show_value = should_show_sum(selected_metric, context)` assignment. Retain all existing groupby/sum code for displayed cells.

These snippets deliberately change only the meaningless sign class of an empty inert cell to neutral-positive. They do not remove a displayed value. If CSS later uses signed backgrounds on inert cells, change the inert styling explicitly rather than computing invisible financial totals for colour.

Tests: patch/spyon `credit_measure_values` and pandas grouping at a hidden total scope to assert they are not called for those cells; compare all displayed text, action attributes, available-measure notes and P&L totals before/after. Include all six measures, absent measures, generic XGamma risk and one genuinely incomplete connector pair. Existing relevant coverage: `tests/s25_crossgamma.py::test_credit_cross_gamma_source_uses_generic_risk_without_measure_pollution` and the Risk component/callback suites. Measure Credit Multi separately; the already-delivered hierarchy-index cache covers standard Cross/Credit Single, not these per-measure calculations.

#### 4. Build the Risk surface pivot once and share it with chart and matrix

Current source: `cube/pages/risk/s05_charts.py::_tenor_surface_pivot` line 95; `build_tenor_heatmap` line 488; `_build_detail_panel_from_frame` line 625, especially the second pivot at lines 809–813. In surface/auto mode the heatmap builds the pivot, and the adjacent matrix builds it again from the same detail and metric. Quick Market already returns its pivot with the chart (`s09_quickmarket.py::_market_surface_chart`, line 647), demonstrating the same sharing pattern without a global cache.

Exact proposed steps:

1. Rename the existing heatmap implementation to `_build_tenor_heatmap_from_pivot` and replace its signature with:

```python
def _build_tenor_heatmap_from_pivot(
    pivot: pd.DataFrame,
    metric: str,
    title: str = "Swap x option surface",
    *,
    ambiguous_option_order: bool = False,
    ambiguous_swap_order: bool = False,
) -> dcc.Graph:
```

2. Remove only its initial `_tenor_surface_pivot(detail, metric)` assignment. Keep the rest of the existing trace, axis, colour, annotation and Graph code unchanged.

3. Immediately before that private function, add a public compatibility wrapper with the original signature:

```python
def build_tenor_heatmap(
    detail: pd.DataFrame,
    metric: str,
    title: str = "Swap x option surface",
) -> dcc.Graph:
    pivot, option_ambiguous, swap_ambiguous = _tenor_surface_pivot(detail, metric)
    return _build_tenor_heatmap_from_pivot(
        pivot,
        metric,
        title,
        ambiguous_option_order=option_ambiguous,
        ambiguous_swap_order=swap_ambiguous,
    )
```

4. In `_build_detail_panel_from_frame`, immediately after `matrix_detail: pd.DataFrame | None = None`, add:

```python
    matrix_pivot: pd.DataFrame | None = None

    def surface_chart(surface_detail: pd.DataFrame) -> dcc.Graph:
        nonlocal matrix_pivot
        matrix_pivot, option_ambiguous, swap_ambiguous = _tenor_surface_pivot(
            surface_detail, metric
        )
        return _build_tenor_heatmap_from_pivot(
            matrix_pivot,
            metric,
            title="Swap x option surface",
            ambiguous_option_order=option_ambiguous,
            ambiguous_swap_order=swap_ambiguous,
        )
```

5. Replace the surface branch's `build_tenor_heatmap(displayed_detail, metric, title=...)` call with `surface_chart(displayed_detail)`.

6. Replace the auto branch's `build_tenor_heatmap(detail.loc[paired], metric, title=...)` call with `surface_chart(matrix_detail)`; this branch already sets `matrix_detail = detail.loc[paired]`.

7. At the bottom, replace the block beginning `if matrix_detail is not None and not matrix_detail.empty:` with:

```python
    if matrix_pivot is not None:
        detail_table = build_surface_matrix_table(matrix_pivot, metric)
    else:
        detail_table = build_small_table(displayed_detail, metric)
```

8. Keep `build_tenor_heatmap` in `__all__`; the private helper need not be exported.

Tests: spy on `_tenor_surface_pivot` and assert exactly one call for surface mode and one for an auto panel with paired rows. Compare figure arrays/axis order and the displayed matrix values for a sparse 2×3 and non-square larger grid; absent cells remain absent, not zero. Include conflicting connector-order annotations. Surface market values still use their existing mean, risk/P&L still use `sum(min_count=1)`; this optimisation does not resolve unrelated market-move identity/design issues.

#### 5. Do not select the same detail context twice

Current source: `s05_charts.py::build_detail_panel_with_state` line 881 selects `scoped = frame_for_context(frame, context)`, then line 882 calls `detail_frame(frame, context, metric)`, which repeats the same selection internally.

Exact proposed change: replace

```python
    detail = detail_frame(frame, context, metric)
```

with

```python
    detail = detail_frame(scoped, {}, metric)
```

Leave the preceding `scoped = ...`, context/title handling and all aggregation rules in `detail_frame` unchanged. The latter still copies its selected frame before adding the `rows` column, so this does not mutate shared cached data.

A bounded outside-repo probe compared both forms for three contexts and six metrics (`risk`, `drisk`, `pl`, `move`, `open`, `current`): **18 exact DataFrame comparisons passed**. Add an empty selection and a multi-key context as regression cases before implementing. The likely saving grows with the input frame and depth of the selected context; there is no claimed whole-page timing here.

#### 6. Filter Search without copying every position column

Current source: `cube/domain/s10_search.py::_filter_risk_positions` line 154. It constructs `candidates = frame.iloc[positions]` before checking whether any filter selections are nonempty. That copies/slices all available columns, although filtering needs only a small subset. `search_combine_udl_options` at line 1054 calls this once per candidate exact identity; a dictionary containing empty selections still incurs the broad slice.

Replace the complete `_filter_risk_positions` function with:

```python
def _filter_risk_positions(
    frame: pd.DataFrame,
    positions: np.ndarray,
    risk_filters: Mapping[str, Sequence[str] | None] | None,
    *,
    exclude_selected: bool = False,
) -> np.ndarray:
    """Filter exact position numbers using only active filter columns."""
    selected_filters = dict(risk_filters or {})
    unknown = sorted(set(selected_filters) - set(QUICK_RISK_FILTER_COLUMNS))
    if unknown:
        raise ValueError(f"Unknown Quick Risk filters: {unknown}")
    if len(positions) == 0 or not selected_filters:
        return positions

    active_filters: list[tuple[str, list[str]]] = []
    for column in QUICK_RISK_FILTER_COLUMNS:
        raw_selected = selected_filters.get(column)
        if isinstance(raw_selected, (str, bytes)):
            raise TypeError(
                f"Quick Risk filter {column!r} must be a sequence of values"
            )
        selected = list(raw_selected or [])
        if selected:
            active_filters.append((column, selected))
    if not active_filters:
        return positions

    keep = np.ones(len(positions), dtype=bool)
    for column, selected in active_filters:
        matches = frame[column].iloc[positions].isin(selected).to_numpy()
        keep &= ~matches if exclude_selected and column != SPLIT else matches
    return positions[keep]
```

No import changes are required: `Mapping`, `Sequence`, `pd` and `np` already exist. This keeps OR within a filter, AND between filters, and the special always-include Split rule. Exact row positions and their order remain unchanged; quote resolution still occurs after Risk filtering. Unknown-filter and text-instead-of-list rejection remain. A malformed frame/filter combination could raise a different first error because validation now precedes slicing; ordinary validated callers should not depend on that ordering.

An outside-repo probe compiled this exact replacement and compared **36** old/new filter outputs (including duplicate/out-of-order positions, no rows, inclusion/exclusion, empty selections and combined Portfolio/Split filters), plus **three** matching error type/message comparisons for unknown dimensions and malformed text selections. All matched. Before implementation, extend that check to every registered filter and compare `SearchCatalog.search_combine_udl_options` results including retention/removal of the currently selected identity. Relevant existing tests live in `tests/s19_riskfilters.py` and the Search suites discovered by `rg -n 'search_combine_udl_options|_filter_risk_positions' tests`.

Do not automatically replace this with a full-frame filter on every keystroke. A narrow text query can touch only one small identity, so a mandatory scan of all 100k positions could be slower. A cache of filter masks is a later measured option; it needs canonical filter/revision keys and a memory bound.

#### 7. Reduce browser work during resize and rectangular selection

Current source: `assets/s11_tables.js::attachResizeHandles` line 269. Every mousemove calls `resizeColumn`, which queries all cells in the column and writes three style properties per cell. `cellsInRectangle` at line 188 queries all selectable cells and filters them even when the requested rectangle is tiny. These are local browser costs, independent of the Python numeric cache.

##### Resize: retain the current table implementation and batch the gesture

Replace only the entire `handle.addEventListener("mousedown", ...)` block at lines 287–305 with:

```javascript
        handle.addEventListener("mousedown", (event) => {
          event.preventDefault();
          event.stopPropagation();
          const startX = event.clientX;
          const startWidth = header.getBoundingClientRect().width;
          const columnCells = Array.from(
            table.querySelectorAll(`tr > *:nth-child(${index + 1})`),
          );
          let pendingWidth = startWidth;
          let frameId = null;

          const applyPendingWidth = () => {
            frameId = null;
            if (!table.isConnected) return;
            columnCells.forEach((cell) => {
              cell.style.width = `${pendingWidth}px`;
              cell.style.minWidth = `${pendingWidth}px`;
              cell.style.maxWidth = `${pendingWidth}px`;
            });
          };
          const onMove = (moveEvent) => {
            pendingWidth = Math.max(82, startWidth + moveEvent.clientX - startX);
            if (frameId === null) {
              frameId = requestAnimationFrame(applyPendingWidth);
            }
          };
          const onUp = () => {
            document.removeEventListener("mousemove", onMove, true);
            document.removeEventListener("mouseup", onUp, true);
            window.removeEventListener("blur", onUp);
            if (frameId !== null) cancelAnimationFrame(frameId);
            applyPendingWidth();
          };

          document.addEventListener("mousemove", onMove, true);
          document.addEventListener("mouseup", onUp, true);
          window.addEventListener("blur", onUp);
        });
```

The existing `resizeColumn` remains for keyboard resizing and the double-click reset remains. This is an incremental improvement: it still writes all cells in the column once per animation frame. A CSS `<colgroup>` redesign could reduce writes further but is a larger table-layout change and is not required for the initial fix.

##### Rectangle: visit only the requested table rows/columns

Inside `cellsInRectangle`, keep all existing start/end/table checks and row/column range calculations. Replace the final `return Array.from(table.querySelectorAll(...)).filter(...)` expression with:

```javascript
    const cells = [];
    for (let rowIndex = rowMin; rowIndex <= rowMax; rowIndex += 1) {
      const row = table.rows[rowIndex];
      if (!row || row.hidden || row.parentElement?.tagName !== "TBODY") continue;
      for (let columnIndex = columnMin; columnIndex <= columnMax; columnIndex += 1) {
        const cell = row.cells[columnIndex];
        if (
          cell?.matches("td.metric-cell, th.index-cell, th.aggregate-index")
          && clipboardValueFromCell(cell) !== ""
        ) cells.push(cell);
      }
    }
    return cells;
```

This uses `rowIndex` and `cellIndex`, matching the original function's coordinate system. It does not reinterpret hidden rows or invent spreadsheet coordinates for colspans. Test selection/copy across hidden Quick Risk descendants, totals, keyboard modifiers, blank cells and multiple tables; resize via mouse and keyboard, double-click reset, blur during drag and table replacement during drag. Use DevTools Performance on a representative bounded table; compare long tasks and style/layout work. Syntax alone is not sufficient browser validation. No runtime JS changes have been applied by this audit.

#### 8. Confirmed remaining work that should be profiled, not prematurely abstracted

1. **Per-node aggregate reductions still run.** `HierarchyAggregationIndex.aggregate` in `cube/ui/s02_aggregation.py` (around line 1179) receives each scoped frame, gathers its rows from numeric arrays and calculates sums; market indexes deduplicate quote codes and calculate the existing hierarchy of means. The delivered cache avoids rebuilding these arrays/quote indexes across expansion, not every reduction. A small per-node numeric-result cache might help repeated expansions, but it needs a node-membership key including hierarchy identity, promotion/filter scope and market visibility. Reusing a result based only on the displayed label is wrong. Do items 1–2 and measure first; do not precompute every possible dimension hierarchy for 100k rows.

2. **Split VA and Credit Multi still do per-node calculations for visible cells.** The blank-cell change above is safe and small. A reusable measure-array index could help, but validate Cross Gamma overlays, missingness and source completeness first. Do not force these special tables through the standard index by silently changing their numbers. Their payoff should be reported separately from standard Cross.

3. **Explorer rendering is serialised.** `_RiskDataCache.render_explorer` at line 1093 uses the same `_render_compute_lock` as index creation/workspace builds. This bounds simultaneous large Python component allocations, but one large render can delay another user's request. Do not simply remove the lock or add parallel workers to hide latency: peak memory can multiply. Bound rows first, measure concurrent-user queue delay and RSS, then consider separate locks for index single-flight and bounded render execution if evidence justifies it.

4. **Workspace component caching remains.** `_RiskDataCache.rendered` at line 1098 retains up to 24 rendered results for Aggregate P&L/Top Promotions. It is separate from the removed Explorer component cache. Top Promotions is already bounded; Aggregate size depends on the chosen reporting dimension. Measure its maximum response and retained size before changing it. Lowering every cache limit blindly can just move work back into repeated rendering. The hierarchy cache is capped at four entries/256 MiB of retained-data accounting; filtered frames at 32 entries/512 MiB. Those are separate caches, not a 256 MiB total process-memory guarantee.

5. **Quick Risk parent pivots are independently recomputed for each prefix.** `SearchCatalog.pivot_combined_hierarchy` at line 1313 does this deliberately to preserve non-additive quote aggregation. It already caps leaves and payload (`250 × number of selected levels` from UI). Never derive market parent values by summing children, and never aggregate parent totals from the visible leaf cap. A risk-only rollup could reuse deepest additive totals; market parents still require the correct quote authority. This is a later measured optimisation, not the first capacity fix.

6. **Detail output can still be large.** `build_small_table` at `s06_explorertables.py:829` emits all grouped detail rows, and surfaces display both all cells in a Plotly figure and an HTML matrix. Typically this is far smaller than positions after grouping, but a broad multi-underlying selection can still be large. Measure actual detail cardinality; if excessive, add server paging for the table and require an exact underlying for a meaningful market surface. Do not silently drop tenor coordinates or downsample a risk heatmap: isolated exposures would disappear.

7. **Avoid waste on invisible workspace views.** The main reducer at `s07_explorer.py:591` already returns `no_update` for detail-only versus table-only events and renders only the active Cross/alt branch. Workspace tabs also gate their work. This is existing good behaviour. A request to split the large callback into several callbacks should not undo the one-request state-plus-render path.

#### Existing good optimisations to preserve

- `_RiskDataCache.filtered` uses a bounded LRU with data-byte accounting and single-flight computation; reduced tenor books and exact quote caches are revision-aware. Do not duplicate those frames in browser Stores.
- The newly implemented `hierarchy_index` shares numeric/quote state across display changes, distinguishes Credit measure, uses strong source references, and refuses oversized/unowned frames. Refresh and clear invalidate it. Explorer does not retain full component trees any more.
- Main Explorer uses delegated `data-risk-*` actions and view tokens, avoiding thousands of pattern-matching Dash inputs. The callback rejects stale generation actions.
- `reduce_and_render_risk_view` owns state and display atomically, removing the previous extra network round-trip. Row expansion does not rerender detail; detail metric changes do not rerender the table.
- `SearchCatalog` constructs immutable exact-identity position indexes and a Risk-to-quote bridge at publication. The dropdown stops at a bounded number of matching options, and market quotes do not depend on portfolio count.
- Quick Risk resolves ProductSpec axes before pivoting. Do not reintroduce the discarded pattern of building an expensive generic pivot first and then doing the normal second pivot to discover its shape.
- Quick Market already shares the surface pivot with its matrix. Native Quick Risk collapse is acceptable because its hierarchy is already bounded; it does not establish that an unrestricted main Risk tree can be hidden in the DOM safely.
- The browser code already moved Risk table enhancement to scoped output-node observers, uses delegated document interactions and disconnects relevant hooks on lifecycle changes. Do not add more whole-document observers per table or per cell.
- Theme changes adjust Plotly layout instead of rebuilding the data pipeline. Animation/playback code already checks visibility and reduced motion. These are not the principal 100k-position bottlenecks.

#### Focused execution order

Apply and validate each proposal independently: row budget → sibling scoping → invisible-cell work → shared surface pivot → single detail scope → narrow Search filter slices → browser gestures. Keep each commit small enough to revert. Do not combine a metric correctness fix with a performance change and call all output differences an optimisation. Record baseline/final rendered rows, serialized bytes, cold/warm callback time and peak process memory for the same revision, same selected scope and same open-row state.

The already-delivered index-cache fix belongs before these steps and should be repeated verbatim from the root audit's actual git diff. This section intentionally does not fabricate that diff or claim these proposals were applied.

## 4. Data, Stock, P&L and history access

### Data, Stock, P&L and archive-history optimisation audit

This section is based on the checked-out source on 6 September 2026, after the local Risk index-cache change. It is a read-only audit. The code below is an implementation proposal unless a measurement explicitly says it was exercised in a temporary in-process probe. None of these page or history changes was applied. The accompanying small probe is `optimisations-history-probe.py` outside the repository. It uses generated Stock rows and the existing read-only archive; no real data was modified.

#### Priorities and measured evidence

| Finding | Priority | Confidence | Main reason |
| --- | --- | --- | --- |
| Check canonical history size before allocating its Cartesian grid | P1 capacity guard | Confirmed from source | The current 16,000-cell guard runs after allocating the potentially huge grid. |
| Move Risk history contributor filters into SQL before `LIMIT` | P1 correctness and performance | Confirmed from source | A small selected book can currently be rejected because unrelated books exceed the 100,000-row database bound first. |
| Page Stock position detail on the server and load it only when opened | P1 payload reduction | Confirmed; synthetic serialization measured | Native pagination sends every row to the browser, even inside closed `<details>`. |
| Bound the complete hidden P&L Validate tree | P1 capacity guard | Confirmed from source | All descendants are built with `hidden=True`; ten children per parent is not a total-row bound. |
| Bound P&L history result caches by entries and estimated bytes | P1 memory retention | Confirmed from source | `_stats_cache` and `_risk_summary_cache` have no eviction within an archive generation. |
| Group Stock children in one pass | P2 inexpensive algorithm change | Output equality and timing measured on a generated 100k-row case | Replaces one full scope scan per sibling with one grouping pass. |
| Batch exact Stock history identities and separate bounds from search | P2 repeated reads | Confirmed execution path; benefit depends on identity count | One CRDS + Activity can fan out to many identities and queries. |
| Stop repeated metadata discovery within one history action | P2 archive I/O | Measured on 262 local completed dates | Warm discovery still stats every file; network shares may cost more. |
| Build P&L summary child lookup once per render | P3 local simplification | Confirmed source; not benchmarked | `_children` scans all summary paths each time. |

Measured synthetic example, not a production guarantee: 100,000 generated current Stock positions spread over 400 portfolios, with some null Stock values. Three repetitions of the current single-level Portfolio pivot had a median **634.2 ms**. Replacing only `_ordered_children` with the groupby version below had a median **328.8 ms**, with exactly equal `StockPivotResult` records, columns and position count. This does not measure deeper trees, callback transport, rendering, or the source load.

The same generated Stock detail produced **33,761,127 UTF-8 bytes** of compact JSON, before HTTP compression. Serializing its full records took a median **520.1 ms**. Its first 50 rows produced **16,734 bytes**. Real identifiers, columns and values will change these numbers. Native `page_size=15` currently does not prevent the full payload.

Existing local archive metadata probe, five calls over 262 completed dates: `ArchiveHistoryRepository.generation()` median **107.3 ms**; `list_queryable_v4_archive_days()` first call **417.5 ms**, warm calls about **65 ms**. These are metadata/schema discovery measurements on this local machine, not whole-file hash timings, not SQL query timings, and not a network-share forecast.

#### 1. Reject oversized Data history grids before allocation

**Evidence.** `cube/history/s06_repository.py`, `ArchiveHistoryRepository.read`, around lines 424–454, calculates axis orders, calls `_canonical_values`, and only then checks `len(values) > self._max_cells`. `cube/history/s01_models.py`, `_canonical_values`, around lines 871–920, creates `pd.MultiIndex.from_product([dates, *axis_labels])`. The raw-row cap is 10,000 and the canonical-cell cap is 16,000, but sparse source rows can have many distinct dates and axis labels. For example, 1,000 dates and 100 labels on each of two axes imply 10,000,000 grid cells even with far fewer observed rows. A post-allocation guard cannot protect the allocation itself.

This is a capacity fix. It should preserve the same error/limit semantics for already rejected requests and avoid changing valid charts.

1. In `cube/history/s06_repository.py`, add `from math import prod` with the standard-library imports.
2. In `ArchiveHistoryRepository.read`, immediately after the `ordering = HistoryOrdering(...)` block and **before** `values = _canonical_values(...)`, add:

```python
        expected_cells = len(dates) * prod(
            len(axis.labels) for axis in ordering.axes
        )
        if expected_cells > self._max_cells:
            raise HistoryValidationError(
                f"Canonical history has {expected_cells:,} cells and exceeds the "
                f"{self._max_cells:,}-cell browser budget. Choose a narrower period "
                "or exact identity."
            )
```

3. Keep the existing post-build `len(values)` guard as a cheap defensive check. It also catches future changes to canonicalization whose size formula might differ.
4. Do not reduce a requested grid by silently dropping tenor/date cells. Missing cells must still become null for requests within budget.
5. Add a regression to `tests/s30_history.py`: construct a sparse two-axis query whose raw-row count is below 10,000 but whose expected grid exceeds the configured cap; replace `_canonical_values` with a function that fails if called, and verify the preflight raises the correct `HistoryValidationError` first. Also cover scalar data (`prod([]) == 1`), empty dates, an empty axis and exactly-at-limit data.
6. Re-run the existing one-axis, two-axis, cross-date order and browser budget tests in `tests/s30_history.py` and `tests/s31_data.py`. Measure peak memory only on a safe bounded synthetic grid; do not allocate an enormous production-like grid merely to demonstrate a known hazard.

No cache or new subsystem is required. Rollback consists only of removing the import and preflight block.

#### 2. Apply Data Risk contributor filters before the SQL row bound

**Evidence.** `cube/history/s05_store.py`, `ArchiveSQLStore.rows`, lines 258–339, filters identity and dates, orders, then uses `LIMIT max_rows + 1`. `cube/history/s06_repository.py`, `ArchiveHistoryRepository.read`, lines 375–402, rejects over 100,000 rows before `_apply_risk_filters(period_rows, handoff.filter_view)` executes. At the user's size, a selected Portfolio could have only a few thousand relevant rows but fail because other portfolios are read first. This is a correctness-of-query-bound improvement as well as less transport from DuckDB to pandas.

The exact existing semantics matter: `RiskFilterView` validates an allowlisted tuple of filters; values are OR within one field and AND across fields. Exclusion negates each populated reporting field, while **Split always remains inclusive**. The current Data store converts legacy `FAKE_REPLACE_ME` text to `TEMP_REPLACE_ME` before pandas filtering; preserve that existing behaviour until the separate alias correctness change is approved. The exact helper below was executed against DuckDB in eight small read-only cases and matched the current normalized pandas selection, including nulls, exclusion with Split, both fixture-label spellings and a quoted value. This validates the predicate only; the repository/callback integration remains unapplied and needs the tests listed below.

1. In `cube/history/s05_store.py`, import `RiskFilterView` from `.s01_models`.
2. Add this helper after `_quoted`. It interpolates only identifiers previously validated by `RiskFilterView` and quoted by `_quoted`; all selected values and legacy-label text remain SQL parameters:

```python
def _risk_filter_clause(view: RiskFilterView | None) -> tuple[str, list[object]]:
    if view is None:
        return "TRUE", []
    if not isinstance(view, RiskFilterView):
        raise TypeError("filter_view must be a RiskFilterView or None")
    clauses: list[str] = []
    parameters: list[object] = []
    for column, selected in view.filters:
        placeholders = ", ".join("?" for _value in selected)
        expression = f"replace(CAST({_quoted(column)} AS VARCHAR), ?, ?)"
        matches = f"coalesce({expression} IN ({placeholders}), FALSE)"
        negate = view.exclude_selected and column != "Split"
        clauses.append(f"NOT ({matches})" if negate else matches)
        parameters.extend((_LEGACY_ARCHIVE_NOTICE, _TEMP_NOTICE, *selected))
    return " AND ".join(clauses) or "TRUE", parameters
```

3. Add the keyword parameter `filter_view: RiskFilterView | None = None` to `ArchiveSQLStore.rows`. Before building `parameters`, calculate:

```python
        if kind != "risk" and filter_view is not None:
            raise ValueError("Market history does not accept Risk contributor filters")
        filter_clause, filter_parameters = _risk_filter_clause(filter_view)
```

4. In its SQL, add `AND ({filter_clause})` **after** the exact-underlying predicate and **before** the date predicate. Insert `*filter_parameters` into the bound parameter list after `*identities` and before `start_date`. Keep the `LIMIT max_rows + 1` parameter last.
5. In `ArchiveHistoryRepository.read`, add `filter_view=handoff.filter_view` to the `_store.rows(...)` call, immediately after its existing `max_rows=self._max_rows` argument. `HistoryHandoff.filter_view` is a real field in `s01_models.py`; its `__post_init__` explicitly rejects non-None filters for `kind == "market"` (around lines 357–365). Consequently valid Market requests pass `None`, and the store's new guard still rejects an invalid direct caller. No conditional is required or desirable to conceal invalid Market filters. Keep `_apply_risk_filters(...)` in place initially: it remains necessary for the legacy CSV fallback and provides a parity check while this change is introduced. Do not add contributor filters to Market queries.
6. Leave `available_dates` unchanged in this patch. That preserves current period resolution and visible gaps across the identity's observed dates. Filtering available dates too would alter which dates presets resolve to, and deserves a separate product decision.
7. Add tests to `tests/s30_history.py` using a lowered `max_rows` rather than a giant fixture: an identity with six source rows, a limit of three, and a selected Portfolio with two rows must now load exactly those two. Verify unfiltered requests still fail, selected requests above their own bound still fail, include/exclude multi-field parity, null values, Split inclusion, and the existing fixture-label mapping.
8. Compare the new SQL selection against `_apply_risk_filters` on the full small reference frame. Test typed malicious/invalid column names are rejected by `RiskFilterView` and quoted values remain parameters.

This proposal does not deduplicate positions, change quote grain, fill nulls, or bypass archive validation. Rollback removes the new argument/clause while retaining the established pandas filter.

#### 3. Make Stock position detail lazy and server-paged

**Evidence.** `cube/pages/stock/s03_view.py`, `build_stock_position_detail`, lines 167–218, uses `data=stock_table_records(display)`, `filter_action="native"`, `sort_action="native"`, `page_action="native"`, `page_size=15`, inside an `html.Details`. `cube/pages/stock/s04_callbacks.py`, `render_current_stock`, lines 300–410, outputs `stock_table_records(display)` for the entire filtered current frame. A closed Details element changes visibility, not the data transmitted. `stock_table_records` materializes object columns, dictionaries and a JSON ID for every row.

The related Statics Read table has the same native-pagination payload issue. Keep its solution separate from the small editable mapping tables, which need whole-frame validation.

The practical minimal Stock change is one page callback over the already server-owned `StockPageData`. It does not need a database or a cache of HTML tables. There is a UX choice: the snippet below replaces the native column-query language with an explicit plain-text search box. If the native filter syntax must remain, implement and test a small allowlisted parser instead; do not use `eval`, and do not claim native filtering works across rows the browser never receives.

##### Exact Stock edits, in order

1. In `cube/pages/stock/s03_view.py`, add `from math import ceil` with the standard-library imports. Add `stock_detail_page` to the module's existing `__all__` list.
2. Replace the complete `build_stock_position_detail` function, from its `def` through its return and before `build_stock_filter_bar`, with this function. It retains the existing argument for current builder call sites, and creates no position records during layout construction. Use an explicit button and callback-owned `Div.hidden`, as below: the installed Dash HTML component only reports Details clicks and does not synchronize a native Summary toggle back to `Details.open`. An `Input(..., "open")` alone would therefore not reliably load the detail:

```python
def build_stock_position_detail(display: pd.DataFrame) -> html.Div:
    """Create a lazy, server-paged view of unaggregated connector rows."""
    del display
    table = dash_table.DataTable(
        id="stock-position-detail-table",
        columns=_stock_table_columns(),
        data=[],
        filter_action="none",
        sort_action="custom",
        sort_mode="multi",
        sort_by=[],
        page_action="custom",
        page_current=0,
        page_size=50,
        page_count=0,
        active_cell=None,
        fixed_rows={"headers": True},
        style_table={"overflowX": "auto", "maxHeight": "52vh"},
        style_cell={
            "padding": "7px 9px",
            "textAlign": "left",
            "minWidth": "100px",
            "whiteSpace": "nowrap",
        },
        style_cell_conditional=[
            {
                "if": {"column_id": ["Quantity", "Stock", "dStock"]},
                "textAlign": "right",
                "fontVariantNumeric": "tabular-nums",
            }
        ],
    )
    content = html.Div(
        [
            html.P(
                "Static identifiers and Portfolio mappings are shown exactly as received.",
                className="page-note",
            ),
            html.Label("Search position detail", htmlFor="stock-detail-search"),
            dcc.Input(
                id="stock-detail-search",
                type="text",
                debounce=True,
                value="",
                maxLength=200,
            ),
            html.P(id="stock-detail-status", className="page-note", role="status"),
            table,
        ],
        id="stock-position-detail",
        hidden=True,
    )
    return html.Div(
        [
            html.Button(
                "Show position detail",
                id="stock-detail-toggle",
                type="button",
                n_clicks=0,
                **{"aria-expanded": "false", "aria-controls": "stock-position-detail"},
            ),
            content,
        ],
        className="stock-position-detail",
    )
```

3. In the same module, add this complete helper **after** `stock_table_records` and **before** `stock_pivot_columns`. It searches/sorts the full filtered frame, then serializes only the selected slice. Invalid browser page/sort values fail explicitly; no filter expression is evaluated:

```python
def stock_detail_page(display, *, search="", page_current=0, page_size=50, sort_by=()):
    text = str(search or "").strip()
    if len(text) > 200:
        raise ValueError("Stock detail search is limited to 200 characters")
    if isinstance(page_size, bool) or page_size not in {15, 25, 50, 100}:
        raise ValueError("Unsupported Stock detail page size")
    size = int(page_size)
    if isinstance(page_current, bool) or not isinstance(page_current, int) or page_current < 0:
        raise ValueError("Invalid Stock detail page number")
    if not isinstance(sort_by, (list, tuple)):
        raise ValueError("Invalid Stock detail sort")
    work = display
    if text:
        matches = pd.Series(False, index=work.index)
        for column in STOCK_DISPLAY_COLUMNS:
            matches |= work[column].astype("string").str.contains(
                text, case=False, regex=False, na=False
            )
        work = work.loc[matches]
    columns, ascending = [], []
    for item in sort_by or ():
        if not isinstance(item, Mapping):
            raise ValueError("Invalid Stock detail sort")
        column, direction = item.get("column_id"), item.get("direction")
        if column not in STOCK_DISPLAY_COLUMNS or direction not in {"asc", "desc"}:
            raise ValueError("Invalid Stock detail sort")
        if column not in columns:
            columns.append(column)
            ascending.append(direction == "asc")
    if columns:
        work = work.sort_values(columns, ascending=ascending, kind="stable")
    pages = ceil(len(work) / size)
    page = min(page_current, max(pages - 1, 0))
    return stock_table_records(work.iloc[page * size : (page + 1) * size]), pages
```

4. In `cube/pages/stock/s04_callbacks.py`, replace the current import `from .s03_view import STOCK_PERIODS, stock_pivot_columns, stock_table_records` with:

```python
from .s03_view import STOCK_PERIODS, stock_detail_page, stock_pivot_columns
```

5. Inside `register_callbacks`, immediately after the existing local `cached_page` helper and before the callback decorated with `Output("stock-loaded-snapshot", "data")`, insert this helper. This is the **exact existing filter-resolution block**, moved to one location; it uses the already imported functions and retains the prior fallback and logging:

```python
    def selected_display(page_data: StockPageData, committed_filter_state) -> pd.DataFrame:
        try:
            committed_values = committed_filter_state_values(
                committed_filter_state,
                STOCK_SAVED_VIEW_CONTROLS,
            )
        except ValueError as error:
            app.logger.warning("Ignoring invalid committed Stock filters: %s", error)
            committed_values = None
        if committed_values is None:
            defaults = default_stock_filter_values(page_data.mapped_stock)
            filter_values = [defaults[field.key] for field in STOCK_FILTER_FIELDS]
            exclude_value: list[str] = []
        else:
            filter_values, exclude_value = committed_values
        return stock_display_rows(
            page_data.mapped_stock,
            dimension_filters=stock_filter_map(filter_values),
            exclude_selected=stock_exclude_selected(exclude_value),
        )
```

6. Replace the complete `render_current_stock` callback, **including its decorator**, from `@app.callback(Output("stock-current-table", "data"), ...)` through the end of the function and before `toggle_stock_branch`, with the following. Its inputs stay the same. Its output tuple changes from eight to **seven** everywhere because position detail now has its own callback. This includes the empty, pivot-only and full-update return branches:

```python
    @app.callback(
        Output("stock-current-table", "data"),
        Output("stock-current-table", "columns"),
        Output("stock-row-count", "children"),
        Output("stock-mapped-count", "children"),
        Output("stock-unmapped-count", "children"),
        Output("stock-history-crds", "options"),
        Output("stock-history-activity", "options"),
        Input("stock-loaded-snapshot", "data"),
        Input(STOCK_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
        Input("stock-pivot-rows", "value"),
        Input("stock-pivot-column", "value"),
        Input("stock-pivot-values", "value"),
        Input("stock-pivot-open-paths", "data"),
        prevent_initial_call=True,
    )
    def render_current_stock(
        loaded_snapshot,
        committed_filter_state,
        pivot_rows,
        pivot_column,
        pivot_values,
        open_paths,
    ):
        page_data = cached_page(loaded_snapshot)
        if page_data is None:
            empty = pd.DataFrame(columns=list(STOCK_DISPLAY_COLUMNS))
            pivot = build_stock_pivot(
                empty,
                row_fields=pivot_rows,
                column_field=pivot_column,
                value_fields=pivot_values,
                open_paths=open_paths,
            )
            return (
                [], stock_pivot_columns(pivot.columns),
                "Rows: 0", "Mapped: 0", "Unmapped: 0", [], [],
            )
        display = selected_display(page_data, committed_filter_state)
        pivot = build_stock_pivot(
            display,
            row_fields=pivot_rows,
            column_field=pivot_column,
            value_fields=pivot_values,
            open_paths=open_paths,
        )
        try:
            trigger = ctx.triggered_id
        except MissingCallbackContextException:
            trigger = None
        if trigger in {
            "stock-pivot-open-paths", "stock-pivot-rows",
            "stock-pivot-column", "stock-pivot-values",
        }:
            return (
                pivot.records, stock_pivot_columns(pivot.columns),
                no_update, no_update, no_update, no_update, no_update,
            )
        all_rows = stock_display_rows(page_data.mapped_stock)
        crds_values = sorted(
            all_rows["CRDS"].astype(str).unique().tolist(), key=str.casefold
        )
        activity_values = sorted(
            all_rows["Activity"].astype(str).unique().tolist(), key=str.casefold
        )
        mapped = int(display["Portfolio Mapped"].eq(True).sum())
        return (
            pivot.records,
            stock_pivot_columns(pivot.columns),
            f"Rows: {len(display):,} of {len(all_rows):,}",
            f"Mapped: {mapped:,}",
            f"Unmapped: {len(display) - mapped:,}",
            [{"label": value, "value": value} for value in crds_values],
            [{"label": value, "value": value} for value in activity_values],
        )
```

7. Immediately after that replacement callback, still **inside** `register_callbacks` and before `toggle_stock_branch`, add these three complete callbacks. The explicit button owns visibility; the detail renderer owns data/page count/status; the reset callback owns page reset/active cell. There are no duplicate outputs and no connector reads. Button clicks produce a real Dash property update, so visibility and loading remain synchronized. Do not add the entire frame to a `dcc.Store`:

```python
    @app.callback(
        Output("stock-position-detail", "hidden"),
        Output("stock-detail-toggle", "children"),
        Output("stock-detail-toggle", "aria-expanded"),
        Input("stock-detail-toggle", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_stock_detail(clicks):
        opened = bool(int(clicks or 0) % 2)
        return (
            not opened,
            "Hide position detail" if opened else "Show position detail",
            str(opened).lower(),
        )

    @app.callback(
        Output("stock-position-detail-table", "data"),
        Output("stock-position-detail-table", "page_count"),
        Output("stock-detail-status", "children"),
        Input("stock-position-detail", "hidden"),
        Input("stock-loaded-snapshot", "data"),
        Input(STOCK_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
        Input("stock-detail-search", "value"),
        Input("stock-position-detail-table", "page_current"),
        Input("stock-position-detail-table", "page_size"),
        Input("stock-position-detail-table", "sort_by"),
        prevent_initial_call=True,
    )
    def render_stock_detail(
        detail_hidden,
        loaded_snapshot,
        committed_filter_state,
        search,
        page_current,
        page_size,
        sort_by,
    ):
        if detail_hidden is not False:
            return [], 0, ""
        page_data = cached_page(loaded_snapshot)
        if page_data is None:
            return [], 0, "Load current Stock to inspect position detail."
        try:
            display = selected_display(page_data, committed_filter_state)
            records, pages = stock_detail_page(
                display,
                search=search,
                page_current=page_current,
                page_size=page_size,
                sort_by=sort_by,
            )
        except (TypeError, ValueError) as error:
            app.logger.warning("Could not render Stock detail: %s", error)
            return [], 0, f"Position detail could not be shown: {error}"
        if not pages:
            return [], 0, "No positions match this search and the applied filters."
        return records, pages, f"{len(records):,} positions on this page · {pages:,} pages."

    @app.callback(
        Output("stock-position-detail-table", "page_current"),
        Output("stock-position-detail-table", "active_cell"),
        Input("stock-loaded-snapshot", "data"),
        Input(STOCK_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
        Input("stock-detail-search", "value"),
        Input("stock-position-detail-table", "sort_by"),
        Input("stock-position-detail-table", "page_size"),
        prevent_initial_call=True,
    )
    def reset_stock_detail_page(
        _loaded_snapshot, _committed_filter_state, _search, _sort_by, _page_size
    ):
        return 0, None
```

The reset callback may cause an additional small page projection when filters/search change; it avoids leaving the browser on a stale page number. The full source remains server-owned. This proposal intentionally does not introduce a cache to eliminate that second projection before measuring it.

8. Keep `toggle_stock_branch` and `select_stock_row` unchanged. The existing history row-click callback listens to `stock-current-table.active_cell` (the pivot). The position-detail table does **not** currently have its own history-click callback, and this pagination change does not silently add one. Its compact row IDs are preserved.
9. Update the existing assertions in `tests/s17_stock.py` for the deliberately changed seven-value callback contract. In `test_v5_current_load_is_lazy_cached_and_defaults_activities_one_to_three`, replace `assert rendered[3] == "Rows: 3 of 3"` with `assert rendered[2] == "Rows: 3 of 3"`. In `test_v5_filter_and_row_click_use_cache_then_prefill_history`, remove `detail` from the eight-value unpacking, leaving `(rows, _columns, row_count, mapped, unmapped, crds_options, _activity_options)`. Immediately after that `render(...)` call, query the new callback explicitly:

```python
    render_detail = _callback_for_output(app, "stock-position-detail-table", "data")
    detail, page_count, _detail_status = render_detail(
        False, token, committed, "", 0, 50, []
    )
    assert page_count == 1
```

Keep the existing `assert len(detail) == 1`, no-extra-connector-calls checks and pivot-only `no_update` assertions. Add these regressions to that test module: hidden detail returns no positions before the projection helper is called; button click 1 returns `(False, "Hide position detail", "true")` and click 2 returns `(True, "Show position detail", "false")`; more than 100k synthetic source rows still return at most requested page_size; searching/sorting finds records outside the original first page; invalid page/sort input is rejected; clearing filters/search resets page zero; nulls and connector metadata remain exact; pivot history selection remains unchanged. The test that checks enabled callback output ownership and shell IDs must continue to pass with the four added IDs (`stock-position-detail`, `stock-detail-toggle`, `stock-detail-search`, `stock-detail-status`).
10. Keep summary counts calculated from the **full filtered current Stock frame**. Do not replace full-scope counts or pivot totals with page totals. If export is added later, perform it from the same server query and clearly distinguish “this page” from “all matching rows”.
11. Format the two Python modules and changed Stock tests, run `tests/s17_stock.py`, then browser-check opening/closing detail, multi-column sorting, search debounce, next/previous pages, saved-filter application, and refresh. These are proposed edits: the audit has not applied this callback wiring or claimed it passed those integration tests.

This eliminates the major payload without introducing a second full-data cache. Sorting/filtering 100k rows still has a server cost; measure it before adding any filtered-view cache. Rollback restores the native table and its original output ownership.

The complete Stock snippets above received a limited read-only smoke check in `optimisations-stock-wiring-probe.py`: all five function/callback blocks parse, the proposed layout instantiates with empty custom-paged data behind a hidden Div, the explicit toggle returns the correct visibility/text/ARIA properties on both clicks, the missing-snapshot renderer returns seven outputs, the proposed callback outputs are unique, and small helper examples page/search/sort correctly. The installed Dash frontend was inspected to confirm why the native Details approach was unsuitable. This does not replace the requested real app/browser and existing Stock test integration checks, which remain pending because this is a guide-only publication.

#### 4. Bound the hidden P&L Validate tree

**Evidence.** `cube/pages/pnl/s06_validation.py`, `_tree_rows`, lines 413–500, recurses into `path in nodes` regardless of whether the path is open. Closed descendants receive `hidden=True`. `VALIDATE_PL_CHILD_LIMIT = 10` limits siblings, but many parents at up to six levels can still produce a large component tree. `build_validate_pl_table` is lazy at the section level and date comparisons are cached, which helps. It does not limit the entire tree once requested. `_validate_unmapped_table` also materializes every unmapped record and should share a display budget or gain its own paging.

This is the exact situation discussed in the Portfolio conversation: caching numeric leaf data is useful; building every descendant's HTML and hiding it is still expensive. The current local JavaScript toggles depend on descendants being present, so simply changing `if can_expand:` to `if can_expand and is_open:` would break expansion. Do not make that isolated edit.

Recommended staged change:

1. First add a global build budget, for example `_VALIDATE_PL_MAX_RENDERED_ROWS = 1_000`, next to `VALIDATE_PL_CHILD_LIMIT`. Keep the ten-child limit too. Treat the number as an initial measured UI budget, not a financial limit.
2. Add an optional shared mutable counter argument to `_tree_rows`, initialized once at the root, passed to recursive calls, decremented before creating each `html.Tr`. Return immediately if it reaches zero. Use the same counter across all branches rather than resetting it per recursion. Do not change `_hierarchy_nodes` or its full-scope aggregates.

```python
# Add to _tree_rows' keyword parameters:
remaining: list[int] | None = None,

# Add at the beginning of _tree_rows:
if remaining is None:
    remaining = [_VALIDATE_PL_MAX_RENDERED_ROWS]

# Add at the start of the for-path loop, before creating components:
if remaining[0] <= 0:
    break
remaining[0] -= 1

# Pass through to its existing recursive _tree_rows(...) call:
remaining=remaining,
```

3. Update the visible limit note in `_validate_tree_table`: “Totals include every filtered row. The tree shows up to 10 children per branch and up to 1,000 hierarchy rows in this view. Narrow the page filters to inspect other rows.” This is honest truncation disclosure; do not imply a hidden child was absent from source data.
4. A bounded tree can still hide some children due to depth-first allocation. Treat the hard bound as immediate crash protection, not the final browse experience. The subsequent functional change should reuse the current comparison/numeric hierarchy and render requested branches on the server, with a 50-row child page. Add a browser store for open paths and parent pages, replace only the Validate toggle's local DOM handler with a Dash callback, and build descendants only when opened. This is a coupled Python/JavaScript change and requires a browser regression; it is not supplied as a one-line patch.
5. For `_validate_unmapped_table`, add a bounded server-paged detail or at minimum an explicit first-N preview/count. Preserve full unmapped totals and allow narrowing by page filters. Avoid creating a second unbounded HTML table beside the newly bounded main tree.
6. Add a test in the existing Validate P&L test module (locate with `rg -n 'build_validate_pl_table' tests`) with multiple ten-way branches: assert the **total hierarchy-row** count is bounded (header/root rows are additional), full root totals equal all input rows, and the limit note is present. Include closed branches because they are the current hidden payload. After the server-expansion change, verify expanding/collapsing works in the browser and counts include only actually built visible rows.

Rollback of stage one is only the budget/counter/note. Do not remove the existing date comparison cache, hierarchy prefix grouping, stale-generation checks, or authoritative archive hash validation.

#### 5. Give P&L history numeric caches real retention bounds

**Evidence.** `cube/history/s07_sql.py`, `SQLPLHistoryRepository.__init__`, lines 996–1008, initializes two ordinary dictionaries. `_cached_stats` (1129–1140), `_remember_hierarchy_stats` (1142–1163), and `risk_summary` (1356–1578) add one entry per filter scope. They clear on connection/generation replacement, but there is no within-generation eviction. Repeated saved views or many users can retain many summary DataFrames. These are numeric results, not HTML, so they are much smaller than the former Risk table cache; they still need a bound.

Do not replace this with a general distributed cache. A process-local LRU is sufficient for this reconstructable state. Each worker owns its own budget; deployment memory budgeting must multiply by worker count and include live query memory.

1. Add `from collections import OrderedDict` and `import sys` to `s07_sql.py`.
2. Keep the existing key/value type annotations, but initialize `_stats_cache` and `_risk_summary_cache` as `OrderedDict()` instead of `{}`. Optionally annotate them as OrderedDict explicitly for clarity.
3. Add `_PL_STATS_CACHE_ENTRIES = 128`, `_PL_RISK_CACHE_ENTRIES = 16`, and `_PL_RISK_CACHE_BYTES = 16 * 1024 * 1024` beside other private query limits. These are initial tunable retention budgets, not hard process-RSS guarantees.
4. Add this size helper near `_empty_summary`. `deep=True` covers DataFrame text but tuple paths may own nested strings, so count those conservatively as well:

```python
def _risk_summary_cache_bytes(result: PLRiskSummaryResult) -> int:
    frame = result.summary
    paths = frame.get(PL_RISK_SUMMARY_PATH, ())
    nested = sum(
        sys.getsizeof(part)
        for path in paths
        if isinstance(path, tuple)
        for part in path
    )
    return int(frame.memory_usage(index=True, deep=True).sum()) + nested
```

5. Add these two methods to `SQLPLHistoryRepository`, and call them only while its existing `RLock` is held:

```python
    def _remember_stats(self, key, value) -> None:
        self._stats_cache[key] = value
        self._stats_cache.move_to_end(key)
        while len(self._stats_cache) > _PL_STATS_CACHE_ENTRIES:
            self._stats_cache.popitem(last=False)

    def _remember_risk_summary(self, key, result) -> None:
        if _risk_summary_cache_bytes(result) > _PL_RISK_CACHE_BYTES:
            return
        self._risk_summary_cache[key] = result
        self._risk_summary_cache.move_to_end(key)
        while (
            len(self._risk_summary_cache) > _PL_RISK_CACHE_ENTRIES
            or sum(_risk_summary_cache_bytes(item)
                   for item in self._risk_summary_cache.values()) > _PL_RISK_CACHE_BYTES
        ):
            self._risk_summary_cache.popitem(last=False)
```

6. Replace `self._stats_cache[key] = cached` in `_cached_stats` with `self._remember_stats(key, cached)`. On a hit call `move_to_end(key)`.
7. Replace the direct assignment in `_remember_hierarchy_stats` with `self._remember_stats((clause, tuple(parameters)), (...existing tuple...))`.
8. In `risk_summary`, on an existing cache hit call `self._risk_summary_cache.move_to_end(cache_key)` before returning its defensive copy. Replace `self._risk_summary_cache[cache_key] = result` with `self._remember_risk_summary(cache_key, result)`.
9. Keep both clear operations in `_close_connection`. Keep returned defensive DataFrame copies: callers must not mutate retained results. An oversized result can still be returned to the current caller; it simply must not remain cached.
10. Cap total selected filter values separately if profiling or abuse hardening needs it. The current `_normalized_filters` caps each text length but not count; a 128-entry stats cache alone is not a strict byte bound for arbitrarily large key tuples. A simple key-byte check can skip caching a key whose UTF-8 text estimate exceeds 16 KiB, without rejecting the underlying valid query. If applied, use it in both remember methods.
11. Add focused repository tests for entry eviction, hit recency, oversized-summary bypass, total estimated byte budget, Clear Cache and new archive generation, defensive-copy isolation and equivalent totals after eviction/recompute. This change should only alter reuse, not SQL or financial aggregation.

The DataFrame byte estimate is accounting, not exact RSS; Python and DuckDB overhead, temporary copies and active queries remain separate. Use an RSS measurement during representative repeated-filter use to select final values.

#### 6. Replace Stock's sibling rescans with one grouping pass

**Evidence.** `cube/pages/stock/s05_pivot.py`, `_ordered_children`, lines 148–158, obtains distinct labels and then scans `frame.loc[labels.eq(label)]` for each label. With 400 portfolios in a 100k-position scope, those sibling masks scan the same frame repeatedly. Each recursive level repeats the pattern.

The following exact function replacement was exercised in-process by the synthetic probe and produced identical output for that fixture. It is not yet an app patch and needs the existing Stock regression tests plus null/duplicate-index variants before integration.

1. Replace `_ordered_children` in `s05_pivot.py` with:

```python
def _ordered_children(
    frame: pd.DataFrame, field: str
) -> Iterable[tuple[str, pd.DataFrame]]:
    labels = frame[field].fillna("Unmapped").astype(str)
    children = [
        (str(label), child, abs(_metric_value(child, "Stock") or 0.0))
        for label, child in frame.groupby(
            labels, sort=False, observed=True, dropna=False
        )
    ]
    children.sort(key=lambda item: (-item[2], item[0].casefold()))
    return ((label, child) for label, child, _magnitude in children)
```

2. Keep `_metric_value(...).sum(min_count=1)`, ordering by absolute **net Stock**, tie-breaking, and the full child frames. Do not change the ordering to sum of absolute position values; that would change behaviour.
3. Test the existing pivot default, toggle, column split and totals tests in `tests/s17_stock.py`; add null labels, all-null metrics, cancellation to zero, duplicate indices, empty data and multiple expanded levels. Compare old/new complete output on small fixtures rather than writing an implementation-mirroring test.
4. Measure the 100k/400-book case and a representative deeper hierarchy. Expect less sibling scanning, not a fix for unbounded rendered rows.
5. Only after that simple change, consider reusing the Stock display projection across expand/collapse. `render_current_stock` calls `stock_display_rows` on every pivot change even though `loaded_snapshot` and committed filters are unchanged. A prepared projection may be keyed by the snapshot token, canonical committed filters and exclusion mode; do not include open paths in that key. Retain it only with a small entry/byte budget and clear it with the owning `cached_pages` store. Do not implement this additional cache unless measured projection time justifies it.

This is the same principle as the Risk fix but at a smaller scope. The first change removes an avoidable algorithmic cost without adding retention at all.

#### 7. Batch Stock history and obtain bounds without a catalog search

**Evidence.** `cube/pages/stock/s04_callbacks.py`, `load_stock_history`, lines 565–612, resolves CRDS + Activity to a list of exact source identities, calls `query_source.catalog(crds, limit=1)` only to obtain global min/max dates, then loops `query_source.rows(identity, ...)` for every identity. `cube/pages/stock/s02_history.py`, `SQLStockHistoryRepository.catalog`, lines 286–338, executes both a bounds aggregate and a `SELECT DISTINCT` search. `rows`, lines 340–402, discovers the archive and executes an exact query each time. It returns an already normalized frame; the callback then normalizes it again.

At 400 identities, this can mean 400 metadata scans and 400 SQL statements for one chart. It is not always 400: the fan-out is the number of exact `STOCK_IDENTITY_COLUMNS` combinations for the selected CRDS + Activity, which must be measured.

1. Keep the existing `StockHistoryQueryProtocol` and callable fallback working. Introduce an optional `@runtime_checkable` `StockHistoryBatchQueryProtocol` in `s02_history.py` with two methods: `bounds()` returning min/max/date count and `rows_many(identities, start_date, end_date)`. Do not add required methods to the current protocol and silently break external implementations.
2. Implement the optional methods on `SQLStockHistoryRepository`. In `_current_connection`, calculate and retain the tiny global bounds once when a new completed-days tuple opens. Clear them in `clear()`. The existing `catalog` can reuse these same bounds and perform its search only when options are actually requested.
3. In `rows_many`, validate every identity through the current `stock_history_identity_token`/`from_token` contract, deduplicate only **identical selected keys**, normalize dates and reject reversed dates. Never deduplicate archive positions to hide an invalid duplicate.
4. Hold the existing repository lock for registration, query, and unregistration. Register the small requested-key DataFrame as `_stock_selected_keys`; semijoin it to `stock_history` on **all** `STOCK_IDENTITY_COLUMNS`. A portable SQL core is:

```python
        selected = pd.DataFrame(validated_identities, columns=STOCK_IDENTITY_COLUMNS)
        selected = selected.drop_duplicates().reset_index(drop=True)
        predicates = " AND ".join(
            f'h."{column}" = s."{column}"' for column in STOCK_IDENTITY_COLUMNS
        )
        projection = ", ".join(
            f'h."{column}"' for column in STOCK_HISTORY_COLUMNS
        )
        connection.register("_stock_selected_keys", selected)
        try:
            frame = connection.execute(
                f'''SELECT {projection} FROM stock_history h
                    SEMI JOIN _stock_selected_keys s ON {predicates}
                    WHERE h."{STOCK_DATE_COLUMN}" BETWEEN ? AND ?
                    ORDER BY h."{STOCK_DATE_COLUMN}"
                    LIMIT ?''',
                [start.date().isoformat(), end.date().isoformat(), max_rows + 1],
            ).df()
        finally:
            connection.unregister("_stock_selected_keys")
```

The snippet assumes the method has established `connection = self._current_connection()` inside the lock, validated `max_rows` as a positive bound, and handled an empty identity list by returning an empty `STOCK_HISTORY_COLUMNS` frame. Use a configured bound such as 100,000 exact history rows and explicitly raise if exceeded; do not silently truncate a chart. The registered column identifiers are constants, not browser strings.

5. Rename returned columns to the exact `STOCK_HISTORY_COLUMNS` order. Validate duplicate dated identities and unexpected keys. Group by the exact identity only to apply the existing `normalize_stock_history_frame` boundary if reusing it; preserve every valid row for later Stock summation. Keep the existing single-identity method as an adapter to this implementation or keep it unchanged initially.
6. In `load_stock_history`, detect `isinstance(stock_history_source, StockHistoryBatchQueryProtocol)`. For the batch implementation use `bounds()` instead of `catalog(...limit=1)` and call `rows_many` once. Keep the original per-identity path for custom/callable providers. Do not remove the legacy boundary validation without an explicit validated-result contract; a small repeated validation is preferable to trusting an arbitrary external source.
7. Preserve the look-back business day needed for `dStock`, actual archive gaps, and per-date summation of Market Value. No zero filling or forward filling. Quantity requires its own compatible-unit policy and should not be added to a combined CRDS history by simply summing unrelated units.
8. Add tests to `tests/s17_stock.py`: two exact identities with the same CRDS/Activity match the concatenated old result, query count is one, archive discovery is one for the batch, duplicate requested keys do not double values, unexpected/duplicate returned identities fail, prior business day is retained, missing dates stay missing, and the old provider protocol still works. Benchmark identity counts 1, 10 and 400 using small dated fixtures.

This adds one narrow optional repository capability, not a new storage format or persistent database.

#### 8. Reduce redundant archive metadata work without weakening validation

**Evidence.** `cube/history/s03_io.py`, `_completed_archive_root_signature`, lines 583–606, enumerates all date leaves and stats all entries on every call to `list_queryable_v4_archive_days`. The completed-day validation result is already cached at `_completed_v4_archive_days_cached(maxsize=16)`. P&L and Stock call discovery from `_current_connection` on every query. Data has a separate `ArchiveHistoryRepository.generation` scan, lines 231–255, using `is_file` plus separate `stat()` calls for size and mtime. Its 60-second page interval is not a query interval; request callbacks also trigger generation checks.

Do **not** claim that interactive history rehashes every financial file on every click. It does not. The code deliberately keeps digest-verified `list_completed_v4_archive_days` and publish/test gates separate from the interactive schema/manifest/row-count path. Preserve both paths and all immutable-leaf contracts.

1. First make each fingerprint scan cheaper without changing its observable cadence. In `ArchiveHistoryRepository.generation`, replace the file comprehension with a loop that obtains each file's `stat()` once, uses `stat.S_ISREG(stat_result.st_mode)` for the existing regular-file check, and stores size/mtime from the same result. Add `from stat import S_ISREG`.
2. Apply the same single-stat approach to `_completed_archive_root_signature`: it already stores `stat = entry.stat()` but then calls `entry.is_file()` separately. Use `S_ISREG(stat.st_mode)` for that boolean. Keep all entries in the signature, including unexpected files/directories, so the completion contract still detects them.
3. Preserve existing treatment of absent files, concurrent creation and error handling. Catch only `FileNotFoundError` if a formerly absent expected file vanishes between enumeration and stat; do not swallow permission errors or completed-marker corruption. The full validation routine must still fail a completed leaf whose required file is missing.
4. Remove **intra-action** repeated discovery first: the Stock batch operation above must reuse one `_current_connection()` result for all its SQL statements. Bounds must be generation-scoped. Likewise any P&L action running multiple SQL statements should acquire the current connection once and pass that local handle.
5. Do not memoize archive discovery forever or key it solely on the root directory mtime. Existing date files and `_SUCCESS` metadata participate in validation, and new or invalid completed leaves must be detected.
6. A short worker-local discovery TTL is an optional later optimization for slow network shares only after these changes are measured. If adopted, make the freshness delay explicit (for example, five seconds), force refresh on Clear Cache and official publication, and clear the memo on error. Do not use that memo for strict digest verification/publish gates. This audit does **not** recommend a background filesystem watcher or new catalog service for this purpose.
7. Verify missing/in-progress leaves, new completed dates, changed manifests, unexpected files, non-directory roots and permission errors all retain their previous outcomes. Preserve `test_repository_is_lazy_bounded_and_generation_includes_new_leaves` and `test_catalog_and_exact_reads_share_one_validated_generation` in `tests/s30_history.py`.

On the measured local archive this is a secondary optimisation: a warm ~65–107 ms scan is real, but sending a 34 MB Stock detail and rebuilding a large hidden table are larger risks. On a high-latency share, reassess using timed spans.

#### 9. Index P&L summary children once, with no retained HTML cache

**Evidence.** `cube/pages/pnl/s10_summary.py`, `_children`, lines 77–85, scans the complete `rows` mapping for every parent whose children are requested. `build_pl_summary_table` already converts the summary DataFrame to a `rows` dictionary. The underlying SQL summary is cached, and leaf display is already paged; keep those strengths.

1. In `build_pl_summary_table`, immediately after its existing loop that fills `rows`, build a parent lookup once:

```python
    children_by_parent: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for path in rows:
        if path:
            children_by_parent.setdefault(path[:-1], []).append(path)
    for children in children_by_parent.values():
        children.sort(key=_sort_key)
```

2. In the nested `append_row`, replace `children = _children(rows, path)` with `children = children_by_parent.get(path, [])`.
3. Remove `_children` if `rg -n '_children\(' cube/pages/pnl/s10_summary.py tests` proves there are no other callers; update any test that directly targeted that private helper to assert rendered business order instead.
4. Preserve `_sort_key`, open-path reduction, the existing 75-leaf paging size (`PL_SUMMARY_LEAF_PAGE_SIZE = 75`), history cell IDs, and whole-scope totals. Do not introduce a cross-request table cache for this small lookup.
5. Compare rendered output for collapsed, expanded and paged summaries, including ties. Only keep the change if representative summary timings warrant it; this is P3 compared with the capacity items above.

#### Existing optimisations and contracts to retain

| Area inspected | What already works | Why it should remain |
| --- | --- | --- |
| Data `s01_selection`, `s02_view`, `s03_callbacks` | Exact typed identities, lazy catalog/query, canonical-only browser bundle; browser-side projection/playback and generation/reset checks | Slider/playback does not reread archive data. Raw history is not serialized into the bundle. |
| Data `ArchiveSQLStore` | One lazy connection per generation, distinct identity catalog cached, exact identity/column/date pushdown, query spans | Do not replace with full pandas reads of all history. Add the missing contributor pushdown. |
| History contracts/I/O/query modules | Atomic `_SUCCESS` publication, strict manifests, schema/row checks, digest-verified strict reader, bounded legacy caches, defensive results | Speed does not justify weakening immutable financial source authority. |
| Current Stock loader | Lazy two-date load, mapped comparison cached for up to four snapshot/date keys, committed filters, raw detail grain | Paging should reuse this source; do not refetch connectors per click or sum static metadata. |
| Stock pivot | Only requested open paths recurse; metric sums use `min_count=1`; small column-split cap | Keep missing metrics null and full-scope sums. Split truncation/visibility is a separate correctness/UX decision, not a free performance change. |
| P&L summary | SQL numeric summary reused per filter generation; three-level tree, only one Greek-level leaf branch open, leaf pagination | Expansion should continue reusing calculated summaries, rather than rescanning the archive or retaining HTML tables. |
| P&L historical series | Lazy selected-cell query, bounded SQL result, observed dates only, optional legacy reader fallback | Preserve honest gaps. A chart-style selector should not become a reason to load all archive rows. |
| Validate P&L | Lazy date discovery, limited-date comparison LRU, full-scope prefix aggregation, stale generation protection, same-render-key `PreventUpdate` | Add total output bounds without removing its correctness safeguards. |
| P&L editor/sender | Browser holds a compact query, effective frames retained server-side with an eight-entry limit, snapshot/filter/adjustment revisions in keys, sender payload copied | Do not cache or bypass authorization/validation side effects to save microseconds. Edits and sends require current revision checks. |

#### Separate correctness and UX work, not disguised as optimisation

- The current Data legacy identity substitution is broader than ideal and Stock/P&L fixture identities can differ. Resolve provenance-aware aliases explicitly; do not use a performance patch to broaden production identity matching.
- Stock pivot displays only the first eight split labels. If omitted splits are possible, expose their count or a governed “Other” total, or require a narrower filter. Removing them silently is not an optimization. Keep metric totals reconciled.
- Stock column additions must classify numeric measures, units, source identifiers and mapping metadata separately. Adding ISIN to financial comparison identity can change row cardinality and the archive contract; attach it through a validated metadata join instead.
- Runtime log rings, official archives and mutable adjustment state are different records. Do not compress or remove business audit events under a performance label. Add an immutable adjustment/send ledger only if the separately described history requirement is implemented.
- P&L plotting currently has a server-backed series selector. Using Plotly's existing legend for visibility could avoid a SQL call if both bounded series are loaded once, but it changes the interaction. Measure that specific call before introducing a browser store; the chart has at most the governed series-row cap, not 100k positions.

#### Verification order for these proposals

1. Land independent small changes first: Data pre-allocation guard; Data filter pushdown with parity tests; Stock groupby replacement; bounded P&L caches.
2. Then change payload ownership: Stock lazy detail/server paging, followed by Validate P&L total bounds and its coupled server-expansion work if needed.
3. Then batch Stock history and reduce metadata repetition. Benchmark exact-identity fan-out and filesystem location explicitly.
4. Run the focused existing test files for changed layers, add regression cases proving the actual previous behaviour, and test UI output ownership/browser interactions for callback edits. Existing root-reported 686 tests belong to the already implemented Risk cache patch; this audit does not claim those tests validate these unimplemented proposals.
5. For capacity checks record raw rows, unique source/quote/portfolio counts, grouped rows, visible and hidden rendered rows, uncompressed JSON bytes, elapsed callback time, process peak RSS and retained cache accounting. Check both cold and warm behaviour. Do not report pandas frame bytes as process RSS.
6. Compare numbers against an unoptimized reference on small deterministic fixtures: Risk/PL sums, quote independence, Stock prior-day differences, filters, nulls, exact identities and archive generation transitions. On larger synthetic data compare outputs or hashes before publishing any speed claim.
7. Avoid permanent benchmarks that mirror each implementation loop. Add a handful of representative capacity/reuse cases to the existing benchmark harness after identifying live entry points, then keep ordinary tests fast and deterministic.

## 5. Startup, refresh, financial preparation and operations

### Refresh, calculation, reduction, connector and runtime optimisation audit

This section is **a proposed implementation guide, not an applied patch**. It was checked against the current local source after the Risk aggregation-index cache change. Existing financial validation, connector ownership and atomic commits remain requirements. Timings below are isolated synthetic microbenchmarks on the review machine, not a claim about production capacity or crash diagnosis.

#### Priority order for this part of the codebase

| Priority | Change | Evidence and applicability |
|---|---|---|
| P2 | Avoid the full snapshot copy after Refresh Portfolios | Confirmed redundant work for that callback; follows the already implemented Risk/PL refresh pattern |
| P2 if supplemental books are large | Validate each New Trade/Cross Gamma frame once per manager attempt | Confirmed two domain validations of the same connector result; preserve public validation wrappers |
| P2 if supplemental books are large | Check product/tenor rules in groups instead of `iterrows()` | Measured New Trades validator improvement; Cross Gamma adaptation is proposed, not benchmarked |
| P3, small and low risk | Replace scalar `map(np.isfinite)` with the NumPy ufunc | Measured improvement with equivalent boolean results |
| P3 | Scope tenor-reduction quotes once per matrix batch | Confirmed five full-book masks per batch; measured modest benefit in the sample |
| P3 robustness | Bound performance-warning history and incomplete stdout lines | Confirmed two process-local accumulators lack bounds; not evidence of the user's crash |
| P4 | Remove redundant copies of tiny temporary-source frames | Real duplication but usually tiny benefit; optional housekeeping only |

The user's 100k Risk rows and 300–400 portfolios make visible-row limits and reusable Risk aggregates more urgent than most of these items. In particular, 100k Risk positions does **not** imply 100k New Trades or Cross Gamma matrix cells.

#### R1. Avoid a full result copy after Refresh Portfolios

**Location:** `cube/services/s06_refresh.py::RiskRefreshManager.refresh_portfolios` at line 1577, success return at line 1748 and retained-snapshot return at line 1817; `cube/pages/risk/s15_refresh.py::register_refresh_callbacks.refresh_pipeline` branch around line 646; `cube/app/s02_contracts.py::RefreshManagerProtocol.refresh_portfolios` around line 420. Use the symbols as anchors if preceding changes shift line numbers.

**Current cause:** `refresh_portfolios()` rebuilds the governed views, commits them, then `_copy_snapshot()` copies six frames, including combined P&L, dashboard, MarketBook and unmapped rows. The callback mainly needs the control metadata at this point and uses the established prepared-dashboard path for the actual display. Normal Risk/PL refresh already supports `copy_result=False` and then obtains `control_snapshot`; Portfolio refresh does not.

**Status/confidence:** proposed, high confidence in redundant copying; no production memory reduction has been measured. This optimises the return path, not the necessary recalculation after changed Portfolio mapping.

##### Exact changes

1. In the service method signature add `copy_result: bool = True` after `expected_reset_generation`. Replace its return annotation with `RefreshSnapshot | None`:

   ```python
   def refresh_portfolios(
       self,
       *,
       reason: str = "portfolio mapping",
       expected_revision: int | None = None,
       expected_reset_generation: int | None = None,
       copy_result: bool = True,
   ) -> RefreshSnapshot | None:
   ```

2. Immediately after the method's existing docstring and before acquiring `_refresh_lock`, add:

   ```python
   if not isinstance(copy_result, bool):
       raise TypeError("copy_result must be boolean")
   ```

3. In **this method only**, replace its success return:

   ```python
   return self._copy_snapshot(snapshot) if copy_result else None
   ```

4. In the same method, replace the failure/last-good return:

   ```python
   return self._copy_snapshot(retained) if copy_result else None
   ```

   Do not remove `_commit_snapshot`, `_commit_full_snapshot`, stale-revision checks, `finally` lock release, or any failure handling.

5. Update the protocol declaration in `cube/app/s02_contracts.py` to match:

   ```python
   def refresh_portfolios(
       self,
       *,
       reason: str = "portfolio mapping",
       expected_revision: int | None = None,
       expected_reset_generation: int | None = None,
       copy_result: bool = True,
   ) -> RefreshSnapshotProtocol | None: ...
   ```

6. In `cube/pages/risk/s15_refresh.py`, replace the complete `elif "refresh-portfolios-button" in triggered_ids:` branch with:

   ```python
   elif "refresh-portfolios-button" in triggered_ids:
       refresh_manager.refresh_portfolios(
           reason="portfolio mapping",
           expected_revision=current_revision,
           expected_reset_generation=browser_reset_generation,
           copy_result=False,
       )
       snapshot = refresh_manager.control_snapshot
   ```

7. In test doubles implementing `refresh_portfolios`, accept the new optional keyword if the callback test invokes them. Find these with `rg -n "def refresh_portfolios|refresh-portfolios-button" tests`.

8. Extend `tests/s07_integration.py` with a regression using the existing manager fixture: first create revision 1, spy on `_copy_snapshot`, invoke `refresh_portfolios(copy_result=False)`, assert the return is `None`, assert no `_copy_snapshot` call, and assert `control_snapshot` describes the successfully committed revision. Repeat with a deliberately failing mapping source and assert the retained snapshot/error behaviour remains intact without the large copy. Keep an existing default-call test proving `copy_result=True` still returns an isolated full snapshot.

9. Run the integration and refresh/callback tests selected by the changed symbols, then the full suite before adopting. Measure refresh return duration and peak process memory separately from the necessary mapping/release/search work.

**Invariants:** default public behaviour remains backward compatible; callers cannot mutate committed frames; same error and atomicity semantics; no connector is skipped merely to save time. Rollback is limited to those three production files and the focused regression.

#### R2. Validate supplemental connector results once inside each refresh

**Location:** `cube/domain/s05_newtrades.py::new_trade_market_scope` (line 323) and `build_new_trade_rows` (line 519); `cube/domain/s04_crossgamma.py::cross_gamma_market_scope` (line 302) and `build_cross_gamma_rows` (line 493); calls in `cube/services/s06_refresh.py` around lines 2376, 2403, 2701 and 2721.

**Current cause:** the manager deliberately fetches each supplemental source once before fetching market quotes. It calls the scope function, which validates and copies the complete frame, then later calls the build function, which validates and copies the same raw result again. The adapter may also validate its external schema, but that is a distinct boundary and should stay. The avoidable duplication is specifically the **two domain validations within one refresh attempt**.

**Status/confidence:** proposed, high confidence in call duplication. No proposed public `skip_validation=True` flag is needed. Use small private functions for frames already validated by the manager, as other core paths already distinguish validated internal inputs from external inputs.

##### Exact changes for New Trades

1. In `cube/domain/s05_newtrades.py`, rename the current scope function to:

   ```python
   def _new_trade_market_scope_validated(
       rows: pd.DataFrame,
   ) -> dict[str, tuple[str, ...]]:
   ```

   Delete only `rows = validate_new_trade_rows(raw_or_validated)` from its body. Keep the remaining scope computation. Adjust its docstring to state that its input is already validated and it does not mutate it.

2. Rename the current builder to:

   ```python
   def _build_new_trade_rows_validated(
       rows: pd.DataFrame,
       market_frames: Mapping[str, pd.DataFrame],
       *,
       multipliers: Mapping[str, float] | None = None,
   ) -> pd.DataFrame:
   ```

   Delete only `rows = validate_new_trade_rows(raw_or_validated)` from its body. Keep the MarketBook mapping guard, multiplier validation, market join, unavailable-data handling, Gamma calculation, cashflows and audit columns.

3. Before `__all__`, add the two original public names as validating wrappers:

   ```python
   def new_trade_market_scope(
       raw_or_validated: object,
   ) -> dict[str, tuple[str, ...]]:
       """Validate an external frame and return its required quote scope."""
       return _new_trade_market_scope_validated(
           validate_new_trade_rows(raw_or_validated)
       )


   def build_new_trade_rows(
       raw_or_validated: object,
       market_frames: Mapping[str, pd.DataFrame],
       *,
       multipliers: Mapping[str, float] | None = None,
   ) -> pd.DataFrame:
       """Validate an external frame and release New Trades."""
       if not isinstance(market_frames, Mapping):
           raise TypeError(
               "market_frames must map Source Type to validated MarketBooks"
           )
       return _build_new_trade_rows_validated(
           validate_new_trade_rows(raw_or_validated),
           market_frames,
           multipliers=multipliers,
       )
   ```

4. Keep the existing public names in `__all__`; do not export the private helpers.

##### Exact changes for Cross Gamma

5. In `cube/domain/s04_crossgamma.py`, rename the current scope function to:

   ```python
   def _cross_gamma_market_scope_validated(
       rows: pd.DataFrame,
   ) -> dict[str, tuple[str, ...]]:
   ```

   Delete its single `rows = validate_cross_gamma_rows(raw_or_validated)` line. Preserve scope ordering and input/output quote identities.

6. Rename the current builder to:

   ```python
   def _build_cross_gamma_rows_validated(
       rows: pd.DataFrame,
       market_frames: Mapping[str, pd.DataFrame],
   ) -> pd.DataFrame:
   ```

   Delete its single validator call. Keep the mapping guard, empty-frame schema, source sensitivity rows, portfolio/input/output grain, contribution sums and output-quote handling.

7. Add the original public names before `__all__`:

   ```python
   def cross_gamma_market_scope(
       raw_or_validated: object,
   ) -> dict[str, tuple[str, ...]]:
       """Validate an external frame and return its required quote scope."""
       return _cross_gamma_market_scope_validated(
           validate_cross_gamma_rows(raw_or_validated)
       )


   def build_cross_gamma_rows(
       raw_or_validated: object,
       market_frames: Mapping[str, pd.DataFrame],
   ) -> pd.DataFrame:
       """Validate an external frame and release Cross Gamma positions."""
       if not isinstance(market_frames, Mapping):
           raise TypeError(
               "market_frames must map Source Type to validated MarketBooks"
           )
       return _build_cross_gamma_rows_validated(
           validate_cross_gamma_rows(raw_or_validated), market_frames
       )
   ```

##### Exact manager wiring

8. In `cube/services/s06_refresh.py`, replace the imported supplemental scope/build names with the corresponding private helpers and add the two validator imports. Preserve the column constants:

   ```python
   from cube.domain.s04_crossgamma import (
       CROSS_GAMMA_COLUMNS,
       _build_cross_gamma_rows_validated,
       _cross_gamma_market_scope_validated,
       validate_cross_gamma_rows,
   )
   from cube.domain.s05_newtrades import (
       NEW_TRADE_COLUMNS,
       _build_new_trade_rows_validated,
       _new_trade_market_scope_validated,
       validate_new_trade_rows,
   )
   ```

9. Replace the existing `add_supplemental_scope(cross_gamma_market_scope(raw_cross_gamma))` statement with:

   ```python
   raw_cross_gamma = validate_cross_gamma_rows(raw_cross_gamma)
   add_supplemental_scope(
       _cross_gamma_market_scope_validated(raw_cross_gamma)
   )
   ```

   Place this after the existing loader `try/except`, so the operational-error empty-frame fallback is also validated. Keep it inside the existing loader-enabled branch.

10. Replace the New Trades scope statement with:

    ```python
    raw_new_trades = validate_new_trade_rows(raw_new_trades)
    add_supplemental_scope(_new_trade_market_scope_validated(raw_new_trades))
    ```

11. In the later P&L stage, replace only the function names of `build_cross_gamma_rows(...)` and `build_new_trade_rows(...)` calls with `_build_cross_gamma_rows_validated(...)` and `_build_new_trade_rows_validated(...)`. Keep their arguments, multiplier handling and `_with_supplemental_credit_sp01` wrapper. Change the matching progress `function_name` string to the new helper name so diagnostic locations remain accurate.

12. Extend `tests/s25_crossgamma.py`, `tests/s26_newtrades.py` and the manager integration tests. Prove external callers still reject duplicate identity, invalid axes, nonfinite sensitivity and malformed schemas; prove the manager calls each domain validator once in a successful attempt; assert public builder output equals private-builder output for validated frames; and assert input frames remain unchanged. Recheck missing quote behaviour, cashflows, Gamma developed Delta, and the same totals per portfolio/output identity.

**Do not do:** remove adapter validation, use a mutable global cache of supplemental frames, cache them across dates without a source revision, or trust that an arbitrary DataFrame is validated because its columns look right. This change reuses only the result within one already isolated refresh attempt.

#### R3. Replace row-wise product/tenor checks with grouped checks

**Location:** `cube/domain/s05_newtrades.py::validate_new_trade_rows`, loop at line 311; `cube/domain/s04_crossgamma.py::validate_cross_gamma_rows`, loop at line 252.

**Current cause:** the allowed tenor axes depend on ProductSpec, but the code resolves the same product pair and performs scalar `.at` checks for every row. With many rows of the same product, that repeats the same rule lookup thousands of times. It is the rule that is grouped, not the financial positions: no rows are aggregated or removed.

**Measured:** a synthetic frame of 100,000 valid MARKET New Trade rows took a median **3,724.943 ms** with the original validator and **585.828 ms** with the grouped axes block below, across three runs. `assert_frame_equal` passed for valid output; both versions rejected a missing required tenor, a populated unused tenor and an unknown Greek. This is not a full regression suite and is not an end-to-end refresh timing.

##### New Trades replacement

1. Inside `validate_new_trade_rows`, keep everything before `pairs, _ = _product_catalogue()` exactly as it is.
2. Replace the block from that assignment through `_validate_axes(rows, row_index=row_index, spec=spec)` with:

   ```python
   pairs, _ = _product_catalogue()
   market_rows = rows.loc[market]
   for pair, group in market_rows.groupby(
       [RISK_TYPE, RISK_GREEK], sort=False, dropna=False
   ):
       try:
           spec = pairs[pair]
       except KeyError as exc:
           row_index = group.index[0]
           raise ValueError(
               f"New Trades pair {pair!r} is not in PRODUCT_SPECS at row {row_index}"
           ) from exc
       for column in (TENOR_SWAP, TENOR_OPTION):
           blank = group[column].eq("")
           invalid = blank if column in spec.tenor_columns else ~blank
           if invalid.any():
               _validate_axes(
                   rows, row_index=group.index[invalid][0], spec=spec
               )
   ```

3. Keep the final `return rows.reset_index(drop=True)`. Keep `_validate_axes` because the grouped block uses it to produce the authoritative error for an invalid row.

##### Cross Gamma replacement

4. Inside `validate_cross_gamma_rows`, replace the block beginning `pair_catalogue = _product_by_pair()` and ending with `_validate_axes(result, row_index=row_index, spec=spec, side=side)` with:

   ```python
   pair_catalogue = _product_by_pair()
   for side, type_column, greek_column in (
       ("Input", INPUT_RISK_TYPE, INPUT_RISK_GREEK),
       ("Output", OUTPUT_RISK_TYPE, OUTPUT_RISK_GREEK),
   ):
       for pair, group in result.groupby(
           [type_column, greek_column], sort=False, dropna=False
       ):
           row_index = group.index[0]
           if pair == ("Cash Flow", "New"):
               raise ValueError(
                   f"Cross Gamma {side} cannot use Cash Flow/New at row {row_index}"
               )
           try:
               spec = pair_catalogue[pair]
           except KeyError as exc:
               raise ValueError(
                   f"Cross Gamma {side} pair {pair!r} is not in PRODUCT_SPECS "
                   f"at row {row_index}"
               ) from exc
           columns = (
               _INPUT_COLUMNS_BY_AXIS
               if side == "Input"
               else _OUTPUT_COLUMNS_BY_AXIS
           )
           for axis, column in columns.items():
               blank = group[column].eq("")
               invalid = blank if axis in spec.tenor_columns else ~blank
               if invalid.any():
                   _validate_axes(
                       result,
                       row_index=group.index[invalid][0],
                       spec=spec,
                       side=side,
                   )
   ```

5. Keep all checks after this block, particularly expected XGamma/XGamma Vega classification and duplicate full matrix cells. The Cross Gamma replacement is a reviewed proposal but was **not** benchmarked or adopted in this audit.

6. Add regression examples for mixed scalar/curve/surface products on both Input and Output sides, blank/forbidden tenor cells, cashflow rejection, unknown pairs, empty frames and duplicate cells. Error ordering can change when several different invalid rows exist: grouping may report a different valid diagnostic first. Do not assert identical first-error ordering unless that is an intentional API requirement; assert the same malformed rows are rejected and valid results remain identical.

**Why this is not overengineering:** it replaces a per-row loop with a per-product loop inside the existing validators. It does not add another data model, framework, cache or validation engine.

#### R4. Use NumPy's vectorised finite-number check

**Locations:** `cube/domain/s05_newtrades.py` lines 150, 176 and 304; `cube/domain/s04_crossgamma.py` lines 242 and 414.

**Cause:** `.map(np.isfinite)` invokes a scalar function for each value. The operands here have already gone through `pd.to_numeric`; `np.isfinite(series)` performs the same finite-number operation as an array operation and preserves a Series index.

**Measured:** on 100,000 float values including NaN and positive/negative infinity, median `fillna(0.0).map(np.isfinite)` was **68.248 ms** versus **0.358 ms** for `np.isfinite(series.fillna(0.0))`, across three runs. The resulting Series were equal. This is a local operation, not a prediction of whole-app speedup.

##### Exact replacements

1. In `_finite_numeric` and `_optional_finite_numeric`, replace:

   ```python
   invalid = booleans | numeric.isna() | ~numeric.fillna(0.0).map(np.isfinite)
   ```

   with:

   ```python
   invalid = booleans | numeric.isna() | ~np.isfinite(numeric.fillna(0.0))
   ```

2. In `validate_new_trade_rows`, replace:

   ```python
   nonfinite_traded = known & ~traded_numeric.fillna(0.0).map(np.isfinite)
   ```

   with:

   ```python
   nonfinite_traded = known & ~np.isfinite(traded_numeric.fillna(0.0))
   ```

3. In `validate_cross_gamma_rows`, replace only the finite-check operand:

   ```python
   | ~converted_sensitivity.map(np.isfinite)
   ```

   with:

   ```python
   | ~np.isfinite(converted_sensitivity)
   ```

4. In `_build_input_legs` in the same file, replace:

   ```python
   | ~invalid_move.fillna(0.0).map(np.isfinite)
   ```

   with:

   ```python
   | ~np.isfinite(invalid_move.fillna(0.0))
   ```

5. NumPy is already imported in both files. Add no dependency. Do not remove the separate boolean, `isna`, known-trade or market-availability guards. The intermediate `fillna(0.0)` is only part of a validation mask; this change does **not** turn missing financial data into zero.

6. Run `tests/s25_crossgamma.py` and `tests/s26_newtrades.py`. Add parametrized dtype/value checks covering float64, nullable numeric inputs, NaN, infinity, booleans, numeric strings, blank optional fields, and nonnumeric text. Compare acceptance and outputs with the current implementation before merging.

#### R5. Avoid five full-MarketBook filters per tenor-reduction batch

**Location:** `cube/domain/s11_tenorreduction.py::ReducedTenorReducer._quote_values` (line 510), `_reduce_batch` quote comprehension (line 603), `_reduce_credit_batch` quote loop (line 757).

**Cause:** `_quote_values` selects the same Source Type + Underlying from the full MarketBook each time it is called. Each batch calls it for up to five quote columns. Quote scope does not change between those calls.

**Status:** proposed, modest measured benefit. On 100k synthetic quotes and a five-column lookup, preselecting one 1k-row underlying subset reduced median time from **28.780 ms** to **25.406 ms**. There is no basis for claiming a fivefold whole-reduction speedup. For a small MarketBook this can be deferred.

##### Minimal exact change

1. In `_reduce_batch`, immediately before the `quote_values_by_column = {` comprehension, insert:

   ```python
   batch_market = market_frame
   if not market_frame.empty:
       batch_market = market_frame.loc[
           market_frame[SOURCE_TYPE].eq(source_type)
           & market_frame[UNDERLYING].eq(underlying)
       ]
   ```

2. Inside that comprehension, replace only the first argument to `self._quote_values` from `market_frame` to `batch_market`. Keep all remaining arguments and the `if column in batch` clause.

3. In `_reduce_credit_batch`, immediately before `for column in MARKET_QUOTE_COLUMNS:`, insert the same `batch_market` block. In that loop replace only the first `_quote_values` argument with `batch_market`.

4. Keep `_quote_values` unchanged. It still verifies scope on a much smaller frame, retains the existing missing-value defaults and resolves connector labels in the same way. Keeping its private signature avoids unnecessary interface changes.

5. Extend `tests/s43_reducedtenor.py` with an explicit MarketBook containing unrelated products/underlyings and all five quote columns. Compare complete reduced frames before/after; verify missing quotes, market-only tenors, Credit reduction, multiple portfolios and chunked versus unchunked output.

**Limits:** this does not address the existing first-occurrence quote choice if someone passes conflicting duplicate quotes to this private lookup. Do not treat selecting an arbitrary duplicate as a new optimisation; preserve the authoritative upstream quote uniqueness checks. Matrix/provider caching and the 32 MiB transient tensor budget already exist and should remain.

#### R6. Bound the two small runtime accumulators that are currently unbounded

**Location:** `cube/app/s03_logging.py::_warned` at line 38, `perf_span` around line 385, and `_TerminalTee.write` around line 251.

The published App Logs buffer is already bounded to 200 records with per-record and response character limits. Two adjacent details are different:

- `_warned` stores one `(event, revision)` key for every revision that exceeded a timing budget, without eviction. Usually small, but it grows across a long-lived process.
- `_TerminalTee._pending` accumulates text until a newline arrives. Repeated `print(..., end="")` or a source writing a very long unterminated line can grow this string without a bound. The later per-record truncation does not apply until a completed line is emitted.

Neither is confirmed as a cause of the user's Portfolio crash. They are worthwhile bounded-memory hygiene, not a reason to replace the logging system.

##### Bound warning de-duplication

1. Extend the existing collections import:

   ```python
   from collections import OrderedDict, deque
   ```

2. Replace `_warned: set[tuple[str, object]] = set()` with:

   ```python
   _PERFORMANCE_WARNING_KEY_LIMIT = 512
   _warned: OrderedDict[tuple[str, object], None] = OrderedDict()
   _warned_lock = RLock()
   ```

3. Immediately before the `@contextmanager` decorator above `perf_span`, add the following helper. Keep that decorator attached to `perf_span`, not to the new helper:

   ```python
   def _first_performance_warning(key: tuple[str, object]) -> bool:
       with _warned_lock:
           if key in _warned:
               _warned.move_to_end(key)
               return False
           _warned[key] = None
           while len(_warned) > _PERFORMANCE_WARNING_KEY_LIMIT:
               _warned.popitem(last=False)
           return True
   ```

4. Replace `if over_budget and warning_key not in _warned:` with `if over_budget and _first_performance_warning(warning_key):` and delete the immediately following `_warned.add(warning_key)` line. Keep the actual warning/info emissions unchanged.

5. Replace the body of `reset_performance_warnings` with:

   ```python
   with _warned_lock:
       _warned.clear()
   ```

   An evicted ancient revision may warn again if revisited. That is acceptable for bounded operational diagnostics; if the business needs immutable event history, this logger is not that store.

##### Bound incomplete stdout text

6. Add `_TERMINAL_PENDING_CHAR_LIMIT = 16_384` next to the other logging size constants.

7. In `_TerminalTee.write`, after the existing loop that handles all completed lines, still inside `with self._lock`, add:

   ```python
   if len(self._pending) > _TERMINAL_PENDING_CHAR_LIMIT:
       _APPLICATION_LOG_HANDLER.append_terminal_text(
           self._source,
           self._pending[:_TERMINAL_PENDING_CHAR_LIMIT]
           + " ... [unterminated output truncated]",
       )
       self._pending = ""
   ```

   The original stdout stream has already received the complete text. Only the bounded browser mirror discards the excess. Keep redaction in `append_terminal_text` and the existing output-record cap. One exceptionally large `write()` argument can still exist transiently; this stops accumulation across repeated writes.

8. Extend `tests/s32_observability.py` and `tests/s46_applogs.py`: generate more than 512 distinct revision warnings and assert the bound; repeat a retained key and assert no repeated warning; concurrently claim the same warning key and assert one warning; write repeated chunks without a newline and assert bounded `_pending`, unchanged underlying stream content and bounded browser output. Check normal complete-line behaviour and redaction.

#### R7. Optional: remove duplicate copies of small temporary source results

**Location:** `cube/services/s05_sources.py::_read_temp_csv` (line 183), `get_risk_checker` (line 317), `get_portfolio_config` (line 564), `get_risk_thresholds` (line 587), `get_reported_underlyings` (line 596), `get_pinned_promotions` (line 613).

`_read_temp_csv()` already returns `frame.copy(deep=True)`. Several public temporary loaders immediately copy that caller-owned result again. These files are typically small, so this is housekeeping after higher-impact work.

1. Keep the defensive copy in `_read_temp_csv`. It protects the `lru_cache`'s stored source frame.
2. In `get_risk_checker`, replace `return readiness.copy(), checker.copy()` with `return readiness, checker`.
3. In `get_portfolio_config` and `get_reported_underlyings`, replace only their final `return frame.copy()` with `return frame`. Keep their date/notice/schema checks.
4. Replace `return _read_temp_csv("risk_thresholds").copy()` with `return _read_temp_csv("risk_thresholds")`.
5. Replace `return _read_temp_csv("pinned_promotions").copy()` with `return _read_temp_csv("pinned_promotions")`.
6. In the source tests, mutate a returned frame, call the source again and assert the cached original remains unchanged. Confirm changed file revision still invalidates the loader.

Do not copy this advice into real site-owned connectors blindly: a real connector may return a shared frame. The proof here depends specifically on the checked-in `_read_temp_csv` boundary.

#### Optimisations already present that should be retained

1. **Lazy import/startup:** `app.py::create_app` passes loaders by reference. `cube/app/s04_startup.py::_run` performs refresh in the startup worker with `copy_result=False`. Adding a preload during import would recreate the startup bottleneck.
2. **Prepared dashboard per committed revision:** `cube/app/s07_factory.py::prepared_committed_dashboard` (line 292) already uses a lock to share one defensive read and preparation for a revision, with checks for an out-of-order caller. This is related to, but distinct from, the new reusable per-scope Risk aggregation index.
3. **Narrow defensive reads:** `cube/services/s02_state.py` provides `health`, `progress`, `control_snapshot`, `pl_snapshot` and `read_frame`. Health/progress do not copy large DataFrames. Use these instead of `manager.snapshot` for metadata-only work; do not weaken the full snapshot's ownership guarantee.
4. **Selective refresh:** `cube/services/s06_refresh.py` reuses unchanged per-product Risk and Market caches. A Live/OFFICIAL status-only transition retains Open and reloads Current; a changed quote scope invalidates that reuse. A no-change attempt can commit metadata without rebuilding financial data.
5. **Transactional reuse:** the refresh writer takes shallow copies of frame dictionaries, reuses immutable-by-convention committed frame references and stages replacements outside the state lock. Do not replace this with a deep copy of every product at the start of each refresh.
6. **Bounded connector concurrency:** `_load_market_frames` uses a bounded executor, time budgets, retry handling and a connector-call gate; FX Delta supports bulk hooks. These are network-boundary safeguards, not unnecessary abstractions. Increasing threads without observing connector call latency, service limits and memory is not an optimisation plan.
7. **Tenor matrix reuse and working-set limit:** `ReducedTenorReducer` caches validated matrices/catalogue entries by name and chunks its transient NumPy tensors around a 32 MiB working-set target. The implementation already applies matrix calculations in batches. Do not replace it with a per-position DataFrame loop or one huge whole-book tensor.
8. **Lazy, revision-aware local reference loaders:** source CSV and JTD caches use path/mtime/size keys and return isolated caller rows. They are not the same as the problematic cache of multiple rendered tables. File-revision keys remain necessary for refresh visibility.
9. **Single Gunicorn worker:** `gunicorn.conf.py` explicitly uses one worker because refresh, revision and progress state are process-local. More workers would create independent managers and consume multiple copies of the dataset. Retain the current worker count until there is an actual requirement for a shared state architecture.
10. **Deployment staging isolation:** `publish.py` copies only the runtime files/directories and re-encodes only staged historical fixture Parquet files. Source archives remain unchanged. History hash/manifest checks protect the immutable fixture contract. Repeated deployment verification costs build time, not ordinary Risk interaction latency.

#### Ideas deliberately deferred or rejected

- **Blanket removal of `.copy()`:** `cube/domain/s03_calculations.py`, governance and adapter boundaries make multiple copies. Some may be reducible, but many establish ownership before normalization or separate source versus developed Gamma rows. Profile the refresh's existing `readiness`, `risk`, `market`, `pl`, `release`, `search` and `result_copy` timings first. A mass replacement with `copy=False` has correctness risk and no measured business benefit in this audit.
- **Deleting schema, duplicate, many-to-one or release validation:** rejected. The safe optimisation reuses a known validation result inside one attempt. It does not permit duplicate quotes to multiply Risk/P&L.
- **Disabling all validators because the adapter validated:** rejected. Site-owned adapters can differ, and public domain functions are directly callable. Adapter and public domain validation have distinct responsibilities.
- **Caching every refresh input indefinitely:** rejected. Risk dates, market status, source scope, governance mapping and connector freshness all matter. Existing selective reuse is more appropriate than a global DataFrame cache without a revision contract.
- **Global string categorisation of all frames:** potentially useful only after measurement. It changes dtype/`groupby(observed=...)` behaviour and can introduce phantom category combinations. The application already uses `observed=True` where intended. Do not change the external schema to categoricals merely for this review.
- **Changing financial floats to float32:** rejected as a default. The performance problem does not justify reducing numerical precision of risk, market moves or P&L.
- **Parallelising every product/calculation:** deferred. Source access and pandas work have different bottlenecks, and simultaneous large frame merges can raise peak memory. Existing bounded market concurrency is deliberate. Measure the network/CPU split before adding concurrency.
- **Caching cloud-compressed archive copies persistently:** deferred. `publish.py` does reread/validate/re-encode the synthetic history during publication. A content-addressed packaging cache would add manifests, invalidation and cleanup logic for occasional build work; no evidence justifies it yet. Do not remove archive hashes to make publishing faster.
- **Replacing process-local state with Redis/queues/databases solely for this optimisation:** rejected at present. The current single-process app can be improved with smaller caches, bounded rendering, narrower reads and existing NumPy/pandas operations.
- **Lengthening timeouts or setting them to zero:** does not reduce repeated computation or memory. Tune only from an observed request/connector budget, and keep the startup, connector and publish-poll timeouts conceptually separate.

#### Measurement protocol for these proposals

1. Keep the current Risk index-cache patch as a separate baseline and record the exact revision/dirty diff being measured.
2. Use the existing `cube.app.s03_logging::perf_span` and refresh stage metrics before introducing new observability infrastructure. Record row count, product count, portfolio count, quote count, cache-hit state, wall time and process memory; avoid logging financial identities/values unnecessarily.
3. Apply one proposal at a time. Record cold and warm runs separately and compare medians across several repetitions using the same input and no connector delays.
4. Compare full outputs with `pd.testing.assert_frame_equal` or a documented tolerance for an intentionally changed numerical reduction order. These proposals do not intentionally change arithmetic order or precision, so prefer exact comparisons first.
5. Preserve real failure cases: unavailable quotes, malformed source schemas, duplicate market identity, stale revisions, failed refresh retaining last-good data, and an input frame being mutated by a caller.
6. The read-only audit probe is `optimisation_pipeline_probe.py` in the review workspace, outside the repository. It measured the three operations reported above without editing source, refreshing production connectors or writing archive history. A full test suite must be run after an implementation; these proposed edits have not been applied by this audit.

## 6. Statics: avoid work for the hidden Read panel

**Priority: P2. Evidence: source and measured payload. Status: proposed.** `cube/pages/static_data/s03_callbacks.py::render_static_data_table` depends on selected file and static revision, but does not check which mode is visible. Saving a mapping while in Write increments the revision and rebuilds the hidden Read table. `s02_view.py::build_static_data_table` serializes every row; native `page_size=50` only controls the browser display.

Measured checked-in payloads were: All Risks 10,000 rows/21 columns → **5,086,175 component bytes**; Open 318 rows → 71,244 bytes; Current 318 rows → 72,212 bytes; Portfolio Mapping 645 rows → 142,211 bytes. No production values were used for this probe. These are serialized component sizes, not process RSS.

The smallest change is to stop rebuilding the Read panel while Write is selected:

1. In `s03_callbacks.py`, locate the callback with `Output("static-data-table-container", "children")`.
2. Add `Input("static-data-mode", "value")` after the revision input. `Input` and `no_update` are already imported.
3. Replace only that callback function with the following complete definition. Keep the existing Statics Write picker reset and editor/save callback unchanged.

```python
    def render_static_data_table(selected_file, _revision, mode):
        if mode != "read":
            return no_update
        if not selected_file:
            return html.Div("No file selected.", className="static-data-empty")
        return build_static_data_table(selected_file, store=static_store)
```

4. In `tests/s42_statics.py`, update direct calls to this callback for the third `mode` argument. Add a counting store regression: hidden Write mode returns `no_update` and performs zero reads when revision changes; switching to Read triggers exactly one read and displays the latest saved revision.
5. Validate entering Write, saving, switching back to Read, changing files, and keeping an unsaved Write draft when switching modes. This proposal does not add a mode-triggered editor reload, which could discard such a draft.

This avoids unnecessary hidden work but still sends the full file when Read is used. If real `s03_risk.csv` is much larger, implement **read-only server pagination** as a separate UI change using the same principles as Stock position detail: filter and sort the full permitted source before selecting the page; show total count and page scope; whitelist fields; reset page state on file/scope change. Changing `page_size` alone does not solve network/memory use. Do not page the writable mapping buffer and then save only that page through the current whole-file replacement API. Small governed Write files should retain whole-table validation and atomic saving.

## 7. Recommended order and changes to avoid

### 7.1 A practical implementation sequence

The audit contains 25 numbered proposals or grouped investigations: eight Risk/UI items, nine history/page items, seven pipeline/runtime items and the Statics Read guard. Several small changes are independent. Use the following order to keep each review understandable; do not put all proposals into a single application commit.

| Batch | Exact scope | Why this comes here | Completion evidence |
|---|---|---|---|
| 0 — existing fix | Section 2 and Appendix A: reusable Risk index, bounded retention, refresh/clear race tests | Establish the already verified baseline | Focused Risk tests, identical scoped output, refresh/clear checks |
| 1 — prevent large allocations | Section 4 item 1: canonical-grid preflight; section 3 item 1: Explorer output budget; section 4 item 4 stage one: total Validate tree budget and bounded unmapped preview | These protect allocation/output directly; faster arithmetic does not make unlimited HTML safe | Guards run before allocation; component counts bounded; full-scope totals unchanged; limits visibly disclosed |
| 2 — reduce large payloads | Section 4 item 3: lazy server-paged Stock detail | Removes full-position serialization from ordinary pivot interactions | Closed detail has no row payload; pages/search/sort/history selection work; registered callback outputs have one owner |
| 3 — query the selected scope | Section 4 item 2: parameterized Risk contributor pushdown | Avoid rejecting a small selected book because unrelated positions hit the SQL limit | Exact pandas/SQL parity, Split exclusion rules, selected-scope row-bound tests |
| 4 — bound retained history | Section 4 item 5: P&L statistics/summary retention limits | Prevent growth across repeated filter scopes within one archive generation | Entry/estimated-byte limits, eviction/recompute equality, refresh/clear and defensive-copy tests |
| 5 — remove repeated local work | Section 3 items 2–6; section 4 item 6; section 5 R1; section 6 | Sibling grouping, hidden-cell skip, shared pivot, single detail scope, narrow Search slicing, Stock grouping, Portfolio return-copy avoidance, hidden Statics guard | Same displayed numbers/order/nulls/actions; compare identical cold/warm scopes |
| 6 — history fan-out | Section 4 items 7–8 | One selected CRDS/Activity may issue many exact-identity queries and repeated metadata scans | One batch query with old-provider fallback; same history and look-back dates; generation freshness preserved |
| 7 — conditional refinements | Section 5 R2–R7; section 3 item 7; section 4 item 9 | Supplemental validation, finite masks, tenor scope, logging bounds, temporary copies, browser gestures, summary child lookup | Relevant regressions and representative measured benefit; browser QA for JavaScript |
| 8 — only if still needed | Section 3 item 8; Validate server expansion after its first-stage guard; optional Stock prepared projection and metadata TTL | These introduce more state or interaction changes | A demonstrated remaining bottleneck plus explicit memory/freshness and callback contracts |

R4's finite-mask replacement and the logging bounds are small enough to land independently; their order above reflects expected impact, not a dependency. R2 and R3 are especially relevant only if the supplemental New Trades/Cross Gamma sources themselves are large.

### 7.2 Portfolio on the main Risk page

The implemented cache change is not a capacity certificate for adding Portfolio. It avoids rebuilding the numeric index on every display change and stops retaining Explorer HTML variants. It does not bound how much visible HTML a user can request, and an oversized index can still be built transiently without retention.

1. Establish whether the reported 100k is raw position rows or an already grouped dataset. Record distinct rows for the actual intended hierarchy after adding Portfolio. Do not estimate that by multiplying every group by 400 unless the source really contains that dense combination.
2. Apply and verify the visible-row budget before enabling a new high-cardinality level.
3. Prefer Portfolio as the deepest optional position breakdown or a 50-row detail page. Keep ProductSpec tenor ownership and exact action-token identities. Do not add Portfolio to every shared dimension registry: some groupby/join paths already include it and can produce duplicate column keys.
4. Keep quote identities independent of Portfolio. Adding a book level must partition Risk/P&L positions while preserving the original market quote authority; a replicated quote is not an additional observation.
5. Measure 300–400 real-shaped portfolios with narrow, broad, collapsed and expanded scopes. Compare grouped rows, visible cells, callback response bytes, peak worker memory and browser responsiveness before enabling it in production.

No Portfolio hierarchy patch or production-scale safety result is included in this documentation publication. The exact existing cache patch is supplied; the subsequent Portfolio UX decision should follow the measured output limit.

### 7.3 Keep chart design separate from speed claims

The chart work here removes duplicate selection/pivot construction. It does not claim to fix the market-move plotting issue or make a chart attractive by itself. Keep a separate visual review: preserve contractual tenor order, show nulls as missing, use units in axis/hover labels, and compare a zero-centred diverging risk surface with a restrained line/bar tenor view on the same data. Use a stable comparable colour range when comparing dates and clearly disclose any per-view rescaling.

The prior chart-preview tool and FIXESMD/NEWTESTS describe those visual alternatives. Do not apply that optional tool or fabricate historical observations as part of these performance patches. Authentic daily archives and an adjustment audit ledger remain separate business features, with their own provenance and persistence requirements.

Keep these existing choices unless measurement and a deliberate contract change justify otherwise:

- Connector uniqueness, merge-cardinality and breakdown validation. Removing checks can turn a visible failure into a wrong total.
- Separate position identity and quote identity. Portfolio is a position key, not a market quote key.
- Last-good refresh state and atomic commits; immutable completed archive leaves and their integrity checks.
- Lazy startup/import, active-page/query loading, existing filtered-data/index bounds, and product-owned tenor ordering.
- One worker while financial snapshot/progress state is process-local. Extra worker processes duplicate state and memory; increasing worker count is not a free throughput switch.
- Existing DuckDB/Parquet/pandas/Dash boundaries. No new database or frontend framework is required by the findings here.
- Clear distinction between active adjustments, historical snapshots and audit events. Do not trade away provenance to make history appear faster.

Do not eagerly build every combination of filter, measure, tenor and portfolio. Do not send a complete giant component tree and assume CSS hiding or virtual scrolling will remove its server/network cost. Do not truncate financial data before aggregation or label a displayed-page subtotal as the complete book. Do not sum child market averages, invent zero for unavailable data, or use arbitrary duplicate removal.

## 8. Validation, rollout and rollback

### 8.1 Record the actual baseline first

1. In a V5 checkout, record `git rev-parse HEAD` and `git status --short`. The patch in Appendix A was generated against `8f65a1124e54702597347967c7064eb4f7edf133`; account for any newer changes before applying it. Preserve existing uncommitted work independently.
2. Reuse the project's Python environment and pinned requirements. In the commands below, `.venv` means that environment; the review machine used the sibling `.review-venv` instead. Do not introduce new infrastructure to reproduce this audit.
3. If the cache change is absent, save Appendix A to `risk-index-cache.patch`, run `git apply --check risk-index-cache.patch`, then apply it. If the check fails, inspect the conflicting source; do not force the patch into a different repository generation.
4. Run the focused tests in section 2. Then run the full suite and existing benchmark before starting the remaining proposals. Avoid production connectors when validating a UI/cache refactor.

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m ruff check .
& '.\.venv\Scripts\python.exe' tools/s03_benchmark.py
git diff --check
```

The previous full local application verification was **686 passed, 56 warnings, 116.04 seconds**, plus Ruff and diff checks. During this documentation-only audit the nine existing benchmark operations were rerun and all budgets passed. This guide does **not** claim that the proposed page/pipeline edits passed the full suite: they have not been applied.

### 8.2 Compare the cache change on its stated scope

Appendix B contains the complete synthetic probe. It compares a fresh index per standalone render with a reused supplied index on 100,000 raw positions, 400 portfolios and 250 shared quotes. The visible views are deliberately small.

| View | Visible rows including total | Fresh index path | Reused index path |
|---|---:|---:|---:|
| Initial collapsed scope, cold | 3 | 134.1 ms | 131.2 ms |
| First expansion, warm | 4 | 137.2 ms | 20.7 ms |
| Further expansion, warm | 9 | 181.8 ms | 64.4 ms |
| Earlier expansion with Risk/P&L breakdowns, warm | 4 | 138.8 ms | 20.7 ms |

All four serialized component outputs matched exactly. The generated scope retained Risk = 400,000, P&L = 40 within floating-point tolerance, and Move = 0.0001. Source-frame accounting was 39,957,132 bytes; the single retained index accounted for 51,981,132 bytes. No Explorer component tree was retained. These byte values overlap through shared frame references and must not be blindly added as disjoint process allocations.

The fresh-path comparison deliberately calls the standalone current renderer without supplying an index; it is not a benchmark of an old finished-table cache hit. An identical finished view previously could return cached HTML faster. The improvement trades that HTML retention for numeric-index reuse across different views. The first index construction still costs time and memory.

### 8.3 Validate each new proposal independently

1. Apply the complete file/signature/callback changes for one numbered proposal, including all named import and return-shape adjustments. Do not paste a fragment without its surrounding instructions.
2. Add regressions for the actual defect or contract: a grid guard before allocation, a page-sized payload, an unfiltered versus selected SQL row bound, a retained-cache budget, or unchanged source/quote identities. Avoid tests that simply copy the new implementation loop.
3. Run the relevant existing suites named in that section. For callback changes also inspect registered output ownership and shell component IDs, then exercise real interactions in the browser. Python syntax and component serialization do not prove a browser gesture works.
4. Compare outputs against the unchanged reference on deterministic small fixtures. Keep Risk/P&L sums, quote independence, missing-data semantics, exact identity, order, adjustment revision and last-good-refresh behaviour. These proposals do not intentionally reduce financial precision.
5. Repeat a bounded synthetic workload with the same row distribution and selection. Separate first construction, warm reuse, serialization and browser rendering. Report median repeated timings where available; preserve the distinction where this guide reports only one run.
6. Observe peak process RSS and retained memory after several filter/expand/clear/refresh cycles. A pandas `memory_usage` result, response byte count and worker RSS measure different things. Include simultaneous requests if multi-user concurrency is the remaining concern.
7. Run the full suite before integrating the tested change. Keep code review, merge and deployment as explicit steps in the actual implementation; publishing this guide alone performs none of them.

### 8.4 Roll back without losing financial state

For an individual proposed change, reverse that proposal's application and regression hunks together, preserving unrelated work. For the already applied cache fix, reverse only the four runtime files and added s19 regressions in Appendix A. Restart the application and repeat the focused tests. These source changes do not require deleting an archive, clearing persisted adjustments or resetting financial history.

Do not restore all of `cube/` from `main` just to undo one optimisation. If a new callback protocol is rolled back, restore its producer, consumer and output ownership together. Keep an output-truncation warning for as long as the corresponding hard display limit remains active.

## Appendix A — exact locally implemented cache patch

The following is the complete diff for the **four cache/aggregation application modules and their s19 regressions** against the reviewed V5 baseline. It excludes the separate Statics fix and optional chart/history tools. Save the block as `risk-index-cache.patch` if applying it, then run `git apply --check risk-index-cache.patch` before `git apply risk-index-cache.patch`. If the patch is already present, do not apply it again. Applying a patch is a local source change; publishing this Markdown has not done that in the destination repository.

```diff
diff --git a/cube/pages/risk/s02_state.py b/cube/pages/risk/s02_state.py
index 53bac35..1220586 100644
--- a/cube/pages/risk/s02_state.py
+++ b/cube/pages/risk/s02_state.py
@@ -32,12 +32,15 @@ from cube.domain.s11_tenorreduction import (
     ReducedTenorReducer,
 )
 from cube.ui.s02_aggregation import (
+    HierarchyAggregationIndex,
+    apply_credit_measure,
     apply_filters,
     filter_ir_family,
     frame_for_context,
     parse_row_key,
     prepare_risk_data,
 )
+from cube.ui.s01_constants import CREDIT_MEASURES
 from cube.app.s02_contracts import (
     ControlSnapshotProtocol,
     RefreshManagerProtocol,
@@ -61,6 +64,8 @@ CLEAR_CACHE_COMPLETE_STORE_ID = "clear-cache-complete-store"
 _UNSET = object()
 _FILTER_CACHE_MAX_ENTRIES = 32
 _FILTER_CACHE_MAX_BYTES = 512 * 1024 * 1024
+_HIERARCHY_CACHE_MAX_ENTRIES = 4
+_HIERARCHY_CACHE_MAX_BYTES = 256 * 1024 * 1024
 
 _REDUCER_CANONICAL_COLUMNS = (
     SOURCE_TYPE,
@@ -651,6 +656,11 @@ class _RiskDataCache:
             OrderedDict()
         )
         self._filtered_bytes = 0
+        self._cache_epoch = 0
+        self._hierarchies: OrderedDict[
+            tuple[int, str | None], tuple[pd.DataFrame, HierarchyAggregationIndex, int]
+        ] = OrderedDict()
+        self._hierarchy_bytes = 0
         self._rendered: OrderedDict[str, Any] = OrderedDict()
         self._promotion_generations: OrderedDict[str, PromotionGeneration] = (
             OrderedDict()
@@ -691,6 +701,9 @@ class _RiskDataCache:
                 self._revision = int(revision)
                 self._filtered.clear()
                 self._filtered_bytes = 0
+                self._cache_epoch += 1
+                self._hierarchies.clear()
+                self._hierarchy_bytes = 0
                 self._rendered.clear()
                 self._promotion_generations.clear()
                 self._reduced_frames.clear()
@@ -704,6 +717,9 @@ class _RiskDataCache:
             with self._lock:
                 self._filtered.clear()
                 self._filtered_bytes = 0
+                self._cache_epoch += 1
+                self._hierarchies.clear()
+                self._hierarchy_bytes = 0
                 self._rendered.clear()
                 self._promotion_generations.clear()
                 self._reduced_frames.clear()
@@ -933,7 +949,10 @@ class _RiskDataCache:
         while True:
             frame = self.current(manager)
             with self._lock:
+                if frame is not self._frame:
+                    continue
                 revision = self._revision
+                epoch = self._cache_epoch
             key = (
                 revision,
                 active_risk_type,
@@ -992,6 +1011,8 @@ class _RiskDataCache:
                 with self._lock:
                     if self._revision != revision:
                         continue
+                    if self._cache_epoch != epoch:
+                        return filtered
                     cached = self._filtered.get(key)
                     if cached is not None:
                         self._filtered.move_to_end(key)
@@ -1011,9 +1032,73 @@ class _RiskDataCache:
                         self._filtered_bytes -= old_size
                     return filtered
 
+    def hierarchy_index(
+        self, frame: pd.DataFrame, *, credit_measure: str | None = None
+    ) -> HierarchyAggregationIndex:
+        """Reuse one read-only index across display states of an owned frame.
+
+        Filter/reduction/promotion scope is represented by the exact cached
+        frame. Credit's measure transform is the only additional numeric key.
+        Strong source references prevent object-id reuse while entries live.
+        """
+        measure = (
+            (
+                credit_measure
+                if credit_measure in CREDIT_MEASURES
+                else CREDIT_MEASURES[0]
+            )
+            if credit_measure is not None
+            else None
+        )
+        key = (id(frame), measure)
+        with self._lock:
+            epoch = self._cache_epoch
+            cached = self._hierarchies.get(key)
+            if cached is not None:
+                self._hierarchies.move_to_end(key)
+                return cached[1]
+        with self._render_compute_lock:
+            with self._lock:
+                cached = self._hierarchies.get(key)
+                if cached is not None:
+                    self._hierarchies.move_to_end(key)
+                    return cached[1]
+            selected = apply_credit_measure(frame, measure) if measure else frame
+            index = HierarchyAggregationIndex(selected)
+            size = index.memory_bytes
+            if selected is not frame:
+                size += int(frame.memory_usage(index=True, deep=True).sum())
+            with self._lock:
+                owned = frame is self._frame or any(
+                    frame is entry[0] for entry in self._filtered.values()
+                )
+                if (
+                    self._cache_epoch != epoch
+                    or not owned
+                    or size > _HIERARCHY_CACHE_MAX_BYTES
+                ):
+                    return index
+                self._hierarchies[key] = (frame, index, size)
+                self._hierarchy_bytes += size
+                while (
+                    len(self._hierarchies) > _HIERARCHY_CACHE_MAX_ENTRIES
+                    or self._hierarchy_bytes > _HIERARCHY_CACHE_MAX_BYTES
+                ):
+                    _old_key, (_source, _index, old_size) = self._hierarchies.popitem(
+                        last=False
+                    )
+                    self._hierarchy_bytes -= old_size
+                return index
+
+    def render_explorer(self, build: Callable[[], Any]) -> Any:
+        """Serialize visible-table builds without retaining component trees."""
+        with self._render_compute_lock:
+            return build()
+
     def rendered(self, key: str, build: Callable[[], Any]) -> Any:
         """Return one exact immutable table tree from a bounded thread-safe LRU."""
         with self._lock:
+            epoch = self._cache_epoch
             cached = self._rendered.get(key, _UNSET)
             if cached is not _UNSET:
                 self._rendered.move_to_end(key)
@@ -1029,6 +1114,8 @@ class _RiskDataCache:
                     return existing
             component = build()
             with self._lock:
+                if self._cache_epoch != epoch:
+                    return component
                 self._rendered[key] = component
                 while len(self._rendered) > 24:
                     self._rendered.popitem(last=False)
diff --git a/cube/pages/risk/s06_explorertables.py b/cube/pages/risk/s06_explorertables.py
index dea40eb..234394e 100644
--- a/cube/pages/risk/s06_explorertables.py
+++ b/cube/pages/risk/s06_explorertables.py
@@ -346,7 +346,12 @@ def build_risk_table(
     region_enabled: bool = True,
     underlying_identity_mode: str = "reported",
     underlying_sort_metric: str | None = None,
+    aggregation_index: HierarchyAggregationIndex | None = None,
 ) -> html.Div:
+    # A supplied index owns both row membership and numeric/quote values.
+    # Never mix its row positions with a separately transformed frame.
+    if aggregation_index is not None:
+        frame = aggregation_index.frame
     if frame.empty:
         return html.Div(
             [
@@ -357,7 +362,8 @@ def build_risk_table(
             role="status",
         )
     columns = build_columns(expanded_metrics)
-    aggregation_index = HierarchyAggregationIndex(frame)
+    if aggregation_index is None:
+        aggregation_index = HierarchyAggregationIndex(frame)
     frame = aggregation_index.frame
     total_metrics = aggregation_index.aggregate(frame, include_market=False)
     total_cells = [
diff --git a/cube/pages/risk/s07_explorer.py b/cube/pages/risk/s07_explorer.py
index 0bb27f7..4dca395 100644
--- a/cube/pages/risk/s07_explorer.py
+++ b/cube/pages/risk/s07_explorer.py
@@ -2,7 +2,6 @@
 
 from __future__ import annotations
 
-import json
 import logging
 from typing import Any, Mapping, Sequence
 
@@ -368,10 +367,6 @@ def register_explorer_callbacks(
                 None,
                 generation_state=generation_state,
             )
-            render_key = json.dumps(
-                [view_token, sorted(open_rows or [])],
-                separators=(",", ":"),
-            )
 
             def build_alt_component():
                 filtered = filtered_frame()
@@ -390,7 +385,7 @@ def register_explorer_callbacks(
                     underlying_sort_metric=selected_sort_metric,
                 )
 
-            return no_update, cache.rendered(render_key, build_alt_component)
+            return no_update, cache.render_explorer(build_alt_component)
 
         view_token = risk_action_view_token(
             risk_context,
@@ -399,10 +394,6 @@ def register_explorer_callbacks(
             credit_view,
             generation_state=generation_state,
         )
-        render_key = json.dumps(
-            [view_token, sorted(open_rows or []), promotion_enabled, region_enabled],
-            separators=(",", ":"),
-        )
 
         def build_main_component():
             filtered = filtered_frame()
@@ -418,8 +409,14 @@ def register_explorer_callbacks(
                     underlying_identity_mode=selected_identity_mode,
                     underlying_sort_metric=selected_sort_metric,
                 )
-            if active_risk_type == "Credit":
-                filtered = apply_credit_measure(filtered, credit_measure)
+            aggregation_index = cache.hierarchy_index(
+                filtered,
+                credit_measure=(
+                    credit_measure or CREDIT_MEASURES[0]
+                    if active_risk_type == "Credit"
+                    else None
+                ),
+            )
             return build_risk_table(
                 filtered,
                 expanded_metrics,
@@ -433,9 +430,10 @@ def register_explorer_callbacks(
                 region_enabled=region_enabled,
                 underlying_identity_mode=selected_identity_mode,
                 underlying_sort_metric=selected_sort_metric,
+                aggregation_index=aggregation_index,
             )
 
-        return cache.rendered(render_key, build_main_component), no_update
+        return cache.render_explorer(build_main_component), no_update
 
     def render_active_detail(
         *,
diff --git a/cube/ui/s02_aggregation.py b/cube/ui/s02_aggregation.py
index 56f4e8e..67bcd0c 100644
--- a/cube/ui/s02_aggregation.py
+++ b/cube/ui/s02_aggregation.py
@@ -1093,6 +1093,20 @@ class _MarketQuoteIndex:
         totals = np.bincount(inverse, weights=values)
         return groups, totals / counts
 
+    @property
+    def memory_bytes(self) -> int:
+        """Array storage retained by this quote index."""
+        return sum(
+            values.nbytes
+            for values in (
+                self._row_quote_codes,
+                self._quote_values,
+                self._quote_to_option,
+                self._option_to_swap,
+                self._swap_to_underlying,
+            )
+        )
+
     def value(self, row_positions: np.ndarray) -> float:
         """Evaluate the existing option -> swap -> underlying mean hierarchy."""
         if not len(row_positions) or not len(self._quote_values):
@@ -1118,13 +1132,14 @@ class _MarketQuoteIndex:
 
 
 class HierarchyAggregationIndex:
-    """Precomputed numeric and quote state for one hierarchy render.
+    """Reusable numeric and quote state for one immutable data scope.
 
     The previous renderer rebuilt three pandas grouping pipelines and three
     validation DataFrames for every visible node. This index factorizes quote
     identities once, stores numeric measures in contiguous arrays, and then
-    evaluates each scoped node with small NumPy reductions. It is deliberately
-    request-local: no caller-owned DataFrame or cross-user state is mutated.
+    evaluates each scoped node with small NumPy reductions. Callers may share
+    the index across renders of the same scope, but must not mutate its frame
+    or the source frame. Aggregation itself only reads the retained state.
     """
 
     _ROW_POSITION_BASE = "__cube_aggregation_row_position__"
@@ -1144,6 +1159,19 @@ class HierarchyAggregationIndex:
             column: _MarketQuoteIndex(frame, column) for column in _MARKET_COLUMNS
         }
 
+    @property
+    def memory_bytes(self) -> int:
+        """Conservative retained-data accounting, not total process memory.
+
+        Count the whole frame even when its blocks are shared with the source;
+        retaining an index can outlive the filtered-frame cache entry.
+        """
+        return (
+            int(self.frame.memory_usage(index=True, deep=True).sum())
+            + self._sum_values.nbytes
+            + sum(index.memory_bytes for index in self._market_indexes.values())
+        )
+
     def aggregate(
         self,
         scoped: pd.DataFrame,
diff --git a/tests/s19_riskfilters.py b/tests/s19_riskfilters.py
index 558b3bf..9ee16e2 100644
--- a/tests/s19_riskfilters.py
+++ b/tests/s19_riskfilters.py
@@ -21,6 +21,8 @@ from cube.domain.s07_governance import (
 )
 from cube.domain.s10_search import MARKET_RESULT_COLUMNS, SearchCatalog
 from cube.pages.risk import s07_explorer as events_module
+from cube.pages.risk import s02_state as risk_state
+from cube.pages.risk import s06_explorertables as explorer_tables
 from cube.pages.risk import s14_workspacecallbacks as workspace_callbacks
 from cube.ui.s01_constants import (
     DEFAULT_VIEW_DIMENSION,
@@ -675,6 +677,445 @@ def test_render_cache_serializes_and_deduplicates_concurrent_builds() -> None:
     assert max_active == 1
 
 
+def test_hierarchy_index_reused_across_expansion_and_metric_views(monkeypatch) -> None:
+    # Uneven portfolio duplication must not weight the shared market quotes.
+    raw = _reducible_raw_frame()
+    duplicate = raw.iloc[[0]].assign(Risk=100.0, dRisk=10.0, PL=200.0)
+    prepared = prepare_risk_data(pd.concat([raw, duplicate], ignore_index=True))
+    original = prepared.copy(deep=True)
+    cache = _RiskDataCache(prepared, revision=7)
+    constructor = risk_state.HierarchyAggregationIndex
+    builds = []
+
+    def build_index(frame):
+        builds.append(frame)
+        return constructor(frame)
+
+    def unexpected_render_index(_frame):
+        pytest.fail("Expand/collapse must use the supplied aggregation index")
+
+    monkeypatch.setattr(risk_state, "HierarchyAggregationIndex", build_index)
+    monkeypatch.setattr(
+        explorer_tables, "HierarchyAggregationIndex", unexpected_render_index
+    )
+    states = [
+        ([], []),
+        ([row_key({"risk greek": "Delta"})], []),
+        (
+            [
+                row_key({"risk greek": "Delta"}),
+                row_key({"risk greek": "Delta", "region": "Americas"}),
+            ],
+            ["risk", "pl"],
+        ),
+        ([], ["drisk"]),
+    ]
+    components = []
+    indexes = []
+    for open_rows, expanded_metrics in states:
+        index = cache.hierarchy_index(prepared)
+        indexes.append(index)
+        components.append(
+            cache.render_explorer(
+                lambda: build_risk_table(
+                    prepared,
+                    expanded_metrics=expanded_metrics,
+                    open_rows=open_rows,
+                    promotion_enabled=False,
+                    aggregation_index=index,
+                )
+            )
+        )
+
+    assert len(builds) == 1
+    assert all(index is indexes[0] for index in indexes)
+    assert len({id(component) for component in components}) == len(states)
+    row_counts = [
+        sum(isinstance(item, html.Tr) for item in _walk(component))
+        for component in components
+    ]
+    assert row_counts[0] < row_counts[1] < row_counts[2]
+    assert row_counts[0] == row_counts[3]
+    for component in components:
+        greek = next(
+            item
+            for item in _walk(component)
+            if isinstance(item, html.Tr)
+            and "group-kind-risk-greek" in getattr(item, "className", "")
+        )
+        risk_cell = next(
+            cell
+            for cell in greek.children
+            if getattr(cell, "data-metric", "") == "risk"
+        )
+        assert risk_cell.children.children == "139.0"
+    metrics = indexes[0].aggregate(indexes[0].frame)
+    assert metrics["risk"] == 139.0
+    assert metrics["pl"] == 278.0
+    assert metrics["open"] == 1.5
+    assert metrics["current"] == 2.5
+    assert metrics["move"] == 1.0
+    assert not cache._rendered
+    pd.testing.assert_frame_equal(prepared, original)
+
+
+def test_registered_risk_callback_reuses_index_across_display_states(
+    monkeypatch,
+) -> None:
+    constructor = risk_state.HierarchyAggregationIndex
+    original_lookup = _RiskDataCache.hierarchy_index
+    builds = []
+    caches = []
+
+    def build_index(frame):
+        builds.append(frame)
+        return constructor(frame)
+
+    def lookup(cache, frame, *, credit_measure=None):
+        caches.append(cache)
+        return original_lookup(cache, frame, credit_measure=credit_measure)
+
+    monkeypatch.setattr(risk_state, "HierarchyAggregationIndex", build_index)
+    monkeypatch.setattr(_RiskDataCache, "hierarchy_index", lookup)
+    app = build_app(refresh_manager=_warm_manager())
+    callback = next(
+        metadata["callback"].__wrapped__
+        for metadata in app.callback_map.values()
+        if "callback" in metadata
+        and metadata["callback"].__wrapped__.__name__ == "reduce_and_render_risk_view"
+    )
+    monkeypatch.setattr(
+        events_module,
+        "ctx",
+        SimpleNamespace(
+            triggered_prop_ids={"table-dimension.value": "table-dimension"},
+            triggered_id="table-dimension",
+        ),
+    )
+    args = [
+        "IR",
+        "delta",
+        1,
+        "activity",
+        "main",
+        "single",
+        None,
+        None,
+        None,
+        ["Risk"],
+        "SP01",
+        "risk",
+        "risk",
+        "risk",
+        "total",
+        "auto",
+        [[], [], [], []],
+        [],
+        [],
+        None,
+        "reported",
+        None,
+        [],
+        [],
+        {"risk_type": "IR", "ir_family": "delta", "data_revision": 1},
+        None,
+    ]
+    collapsed = callback(*args)[11]
+    args[22] = [row_key({"risk greek": "Delta"})]
+    expanded = callback(*args)[11]
+    args[23] = ["risk", "pl"]
+    metrics_expanded = callback(*args)[11]
+
+    assert len(builds) == 1
+    assert len(caches) == 3
+    assert all(cache is caches[0] for cache in caches)
+    assert not caches[0]._rendered
+    assert collapsed is not expanded and expanded is not metrics_expanded
+    collapsed_rows = sum(isinstance(item, html.Tr) for item in _walk(collapsed))
+    expanded_rows = sum(isinstance(item, html.Tr) for item in _walk(expanded))
+    assert expanded_rows > collapsed_rows
+
+
+def test_hierarchy_index_separates_filter_scopes() -> None:
+    cache = _RiskDataCache(prepare_risk_data(_raw_risk_frame()), revision=7)
+    core = cache.filtered(None, "IR", "delta", ["Risk"], {"category": ["Core"]})
+    hedge = cache.filtered(None, "IR", "delta", ["Risk"], {"category": ["Hedge"]})
+    core_index = cache.hierarchy_index(core)
+    hedge_index = cache.hierarchy_index(hedge)
+
+    assert core_index is not hedge_index
+    assert cache.hierarchy_index(core) is core_index
+    assert core_index.aggregate(core_index.frame)["risk"] == 10.0
+    assert hedge_index.aggregate(hedge_index.frame)["risk"] == 20.0
+    assert core_index.aggregate(core_index.frame)["open"] == 3.0
+    assert hedge_index.aggregate(hedge_index.frame)["open"] == 3.0
+
+
+def test_hierarchy_index_separates_credit_measures_without_mutating_source() -> None:
+    raw = _raw_risk_frame().assign(
+        **{
+            "Source Type": "credit/delta",
+            "Risk Type": "Credit",
+            "Risk SP01": [100.0, 200.0],
+            "dRisk SP01": [10.0, 20.0],
+            "Risk PSP01": [1.0, 2.0],
+            "dRisk PSP01": [0.1, 0.2],
+        }
+    )
+    prepared = prepare_risk_data(raw)
+    original = prepared.copy(deep=True)
+    cache = _RiskDataCache(prepared, revision=7)
+    native = cache.hierarchy_index(prepared)
+    sp01 = cache.hierarchy_index(prepared, credit_measure="SP01")
+    psp01 = cache.hierarchy_index(prepared, credit_measure="PSP01")
+
+    assert len({id(native), id(sp01), id(psp01)}) == 3
+    assert cache.hierarchy_index(prepared, credit_measure="SP01") is sp01
+    assert cache.hierarchy_index(prepared, credit_measure="invalid") is sp01
+    for index, expected in ((native, 30.0), (sp01, 300.0), (psp01, 3.0)):
+        metrics = index.aggregate(index.frame)
+        assert metrics["risk"] == expected
+        assert metrics["risk expo"] == expected
+        assert metrics["risk hedges"] == 0.0
+        assert metrics["pl"] == 10.0
+        assert metrics["open"] == 3.0
+        assert metrics["current"] == 4.0
+    component = build_risk_table(
+        prepared, [], [], aggregation_index=sp01, promotion_enabled=False
+    )
+    greek = next(
+        item
+        for item in _walk(component)
+        if isinstance(item, html.Tr)
+        and "group-kind-risk-greek" in getattr(item, "className", "")
+    )
+    risk_cell = next(
+        cell for cell in greek.children if getattr(cell, "data-metric", "") == "risk"
+    )
+    assert risk_cell.children.children == "300.0"
+    pd.testing.assert_frame_equal(prepared, original)
+
+
+@pytest.mark.parametrize("invalidate", ["clear", "refresh"])
+def test_hierarchy_index_invalidated_with_its_data_generation(invalidate) -> None:
+    cache = _RiskDataCache(prepare_risk_data(_raw_risk_frame()), revision=7)
+    previous_frame = cache.filtered(None, "IR", "delta", ["Risk"], {})
+    previous = cache.hierarchy_index(previous_frame)
+    if invalidate == "clear":
+        cache.clear_reconstructable()
+        expected = 30.0
+    else:
+        cache.replace_frame(_raw_risk_frame().assign(Risk=[40.0, 50.0]), revision=8)
+        expected = 90.0
+
+    assert not cache._hierarchies
+    assert cache._hierarchy_bytes == 0
+    # A callback already holding the old frame can finish, but cannot repopulate
+    # the shared cache with a view invalidated by refresh or Clear Cache.
+    old_result = cache.hierarchy_index(previous_frame)
+    assert old_result.aggregate(old_result.frame)["risk"] == 30.0
+    assert not cache._hierarchies
+    current_frame = cache.filtered(None, "IR", "delta", ["Risk"], {})
+    current = cache.hierarchy_index(current_frame)
+    assert current is not previous
+    assert current.aggregate(current.frame)["risk"] == expected
+    assert cache.hierarchy_index(current_frame) is current
+
+
+def test_hierarchy_index_does_not_retain_unowned_frames() -> None:
+    prepared = prepare_risk_data(_raw_risk_frame())
+    cache = _RiskDataCache(prepared, revision=7)
+    unowned = prepared.copy()
+
+    first = cache.hierarchy_index(unowned)
+    second = cache.hierarchy_index(unowned)
+
+    assert first is not second
+    assert first.aggregate(first.frame)["risk"] == 30.0
+    assert not cache._hierarchies
+    assert cache._hierarchy_bytes == 0
+
+
+def test_hierarchy_index_lru_evicts_by_entries_and_counts_all_buffers(
+    monkeypatch,
+) -> None:
+    monkeypatch.setattr(risk_state, "_HIERARCHY_CACHE_MAX_ENTRIES", 2)
+    cache = _RiskDataCache(prepare_risk_data(_raw_risk_frame()), revision=7)
+    core = cache.filtered(None, "IR", "delta", ["Risk"], {"category": ["Core"]})
+    hedge = cache.filtered(None, "IR", "delta", ["Risk"], {"category": ["Hedge"]})
+    whole = cache.filtered(None, "IR", "delta", ["Risk"], {})
+    core_index = cache.hierarchy_index(core)
+    hedge_index = cache.hierarchy_index(hedge)
+    assert cache.hierarchy_index(core) is core_index
+    whole_index = cache.hierarchy_index(whole)
+
+    assert len(cache._hierarchies) == 2
+    assert cache.hierarchy_index(core) is core_index
+    assert cache.hierarchy_index(whole) is whole_index
+    quote_bytes = sum(
+        value.nbytes
+        for quote_index in vars(whole_index)["_market_indexes"].values()
+        for value in vars(quote_index).values()
+    )
+    expected_minimum = (
+        int(whole_index.frame.memory_usage(index=True, deep=True).sum())
+        + whole_index._sum_values.nbytes
+        + quote_bytes
+    )
+    assert whole_index.memory_bytes >= expected_minimum
+    assert cache._hierarchy_bytes == core_index.memory_bytes + whole_index.memory_bytes
+    assert cache.hierarchy_index(hedge) is not hedge_index
+    assert len(cache._hierarchies) == 2
+
+
+def test_hierarchy_index_byte_limit_evicts_and_oversize_is_not_retained(
+    monkeypatch,
+) -> None:
+    cache = _RiskDataCache(prepare_risk_data(_raw_risk_frame()), revision=7)
+    core = cache.filtered(None, "IR", "delta", ["Risk"], {"category": ["Core"]})
+    hedge = cache.filtered(None, "IR", "delta", ["Risk"], {"category": ["Hedge"]})
+    core_index = cache.hierarchy_index(core)
+    hedge_index = cache.hierarchy_index(hedge)
+    limit = max(core_index.memory_bytes, hedge_index.memory_bytes)
+    cache.clear_reconstructable()
+    monkeypatch.setattr(risk_state, "_HIERARCHY_CACHE_MAX_BYTES", limit)
+    core = cache.filtered(None, "IR", "delta", ["Risk"], {"category": ["Core"]})
+    hedge = cache.filtered(None, "IR", "delta", ["Risk"], {"category": ["Hedge"]})
+    core_index = cache.hierarchy_index(core)
+    cache.hierarchy_index(hedge)
+
+    assert len(cache._hierarchies) == 1
+    assert 0 < cache._hierarchy_bytes <= limit
+    assert cache.hierarchy_index(core) is not core_index
+    cache.clear_reconstructable()
+    monkeypatch.setattr(risk_state, "_HIERARCHY_CACHE_MAX_BYTES", 1)
+    frame = cache.current(None)
+    first = cache.hierarchy_index(frame)
+    second = cache.hierarchy_index(frame)
+    assert first is not second
+    assert first.aggregate(first.frame)["risk"] == 30.0
+    assert not cache._hierarchies
+    assert cache._hierarchy_bytes == 0
+
+
+@pytest.mark.parametrize("invalidate", ["clear", "refresh"])
+def test_inflight_hierarchy_build_cannot_publish_after_invalidation(
+    monkeypatch, invalidate
+) -> None:
+    frame = prepare_risk_data(_raw_risk_frame())
+    cache = _RiskDataCache(frame, revision=7)
+    constructor = risk_state.HierarchyAggregationIndex
+    entered = Event()
+    release = Event()
+
+    def slow_index(source):
+        entered.set()
+        assert release.wait(timeout=5.0)
+        return constructor(source)
+
+    monkeypatch.setattr(risk_state, "HierarchyAggregationIndex", slow_index)
+    with ThreadPoolExecutor(max_workers=1) as executor:
+        pending = executor.submit(cache.hierarchy_index, frame)
+        assert entered.wait(timeout=5.0)
+        if invalidate == "clear":
+            cache.clear_reconstructable()
+        else:
+            cache.replace_frame(_raw_risk_frame().assign(Risk=[40.0, 50.0]), revision=8)
+        release.set()
+        result = pending.result(timeout=5.0)
+
+    assert result.aggregate(result.frame)["risk"] == 30.0
+    assert not cache._hierarchies
+    assert cache._hierarchy_bytes == 0
+    current = cache.hierarchy_index(cache.current(None))
+    assert current is not result
+    assert current.aggregate(current.frame)["risk"] == (
+        30.0 if invalidate == "clear" else 90.0
+    )
+
+
+def test_concurrent_hierarchy_requests_build_one_index(monkeypatch) -> None:
+    frame = prepare_risk_data(_raw_risk_frame())
+    cache = _RiskDataCache(frame, revision=7)
+    constructor = risk_state.HierarchyAggregationIndex
+    entered = Event()
+    release = Event()
+    builds = []
+
+    def slow_index(source):
+        builds.append(source)
+        entered.set()
+        assert release.wait(timeout=5.0)
+        return constructor(source)
+
+    monkeypatch.setattr(risk_state, "HierarchyAggregationIndex", slow_index)
+    with ThreadPoolExecutor(max_workers=2) as executor:
+        first = executor.submit(cache.hierarchy_index, frame)
+        assert entered.wait(timeout=5.0)
+        second = executor.submit(cache.hierarchy_index, frame)
+        release.set()
+        first_result = first.result(timeout=5.0)
+        second_result = second.result(timeout=5.0)
+
+    assert first_result is second_result
+    assert len(builds) == 1
+
+
+def test_explorer_renders_are_serialized_without_retaining_component_trees() -> None:
+    cache = _RiskDataCache(prepare_risk_data(_raw_risk_frame()), revision=7)
+    entered = Event()
+    release = Event()
+    counts_lock = Lock()
+    active = 0
+    max_active = 0
+    builds = 0
+
+    def build():
+        nonlocal active, max_active, builds
+        with counts_lock:
+            builds += 1
+            active += 1
+            max_active = max(max_active, active)
+        entered.set()
+        assert release.wait(timeout=5.0)
+        with counts_lock:
+            active -= 1
+        return html.Div("Risk rows")
+
+    with ThreadPoolExecutor(max_workers=2) as executor:
+        first = executor.submit(cache.render_explorer, build)
+        assert entered.wait(timeout=5.0)
+        second = executor.submit(cache.render_explorer, build)
+        release.set()
+        first_result = first.result(timeout=5.0)
+        second_result = second.result(timeout=5.0)
+
+    assert first_result is not second_result
+    assert builds == 2
+    assert max_active == 1
+    assert not cache._rendered
+
+
+def test_inflight_workspace_render_does_not_repopulate_cleared_cache() -> None:
+    cache = _RiskDataCache(prepare_risk_data(_raw_risk_frame()), revision=7)
+    entered = Event()
+    release = Event()
+
+    def build():
+        entered.set()
+        assert release.wait(timeout=5.0)
+        return html.Div("Workspace rows")
+
+    with ThreadPoolExecutor(max_workers=1) as executor:
+        pending = executor.submit(cache.rendered, "workspace", build)
+        assert entered.wait(timeout=5.0)
+        cache.clear_reconstructable()
+        release.set()
+        pending.result(timeout=5.0)
+
+    assert not cache._rendered
+
+
 def test_full_tenor_mode_does_not_read_catalog_or_call_matrix_provider() -> None:
     prepared = prepare_risk_data(_reducible_raw_frame())
     calls: list[str] = []
```

## Appendix B — complete synthetic index-reuse comparison

Save this diagnostic next to a checkout named `repo` and run with its dependency environment. It writes only the JSON result beside itself. The code and fixture assumptions are explicit so the measured small visible scopes cannot be mistaken for a fully expanded production book.

```python
"""Synthetic scoped render comparison; never expands the complete book."""
from pathlib import Path
import importlib.util
import json
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'repo'))
import numpy as np
import pandas as pd
from plotly.utils import PlotlyJSONEncoder
from cube.ui.s02_aggregation import prepare_risk_data, row_key
from cube.pages.risk.s02_state import _RiskDataCache
from cube.pages.risk.s06_explorertables import build_risk_table

spec = importlib.util.spec_from_file_location('fixtures', ROOT / 'repo/tests/s19_riskfilters.py')
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)

raw = pd.DataFrame(fixtures._raw_risk_frame().iloc[0].to_dict(), index=range(100_000))
positions = np.arange(len(raw))
quotes = positions % 250
raw['Portfolio'] = [f'BOOK-{i:03d}' for i in positions // 250]
raw['Underlying'] = [f'SYNTHETIC-USD-{i}' for i in quotes // 50]
raw['Reported Underlying'] = raw['Underlying']
raw['Tenor Swap'] = [f'{i + 1}M' for i in quotes % 50]
raw['Tenor Swap Order'] = quotes % 50
raw['Open'] = 0.03 + quotes / 100_000
raw['Current'] = raw['Open'] + 0.0001
raw['Risk'] = np.where(positions % 2, -2.0, 10.0)
raw['dRisk'] = raw['Risk'] / 10
raw['PL'] = raw['Risk'] * 0.0001
print('Preparing synthetic 100k-row fixture', flush=True)
frame = prepare_risk_data(raw)
cache = _RiskDataCache(frame, revision=1)
scope = cache.filtered(None, 'IR', 'delta', ['Risk'], {})
assert len(scope) == 100_000 and scope.portfolio.nunique() == 400

states = [
    ([], []),
    ([row_key({'risk greek': 'Delta'})], []),
    ([row_key({'risk greek': 'Delta'}), row_key({'risk greek': 'Delta', 'group': 'G10'})], []),
    ([row_key({'risk greek': 'Delta'})], ['risk', 'pl']),
]

def walk(component):
    if isinstance(component, (tuple, list)):
        for child in component:
            yield from walk(child)
        return
    if component is None:
        return
    yield component
    yield from walk(getattr(component, 'children', None))

def render(opened, metrics, *, reuse):
    index = cache.hierarchy_index(scope) if reuse else None
    return build_risk_table(
        scope, metrics, opened, promotion_enabled=False, region_enabled=False,
        aggregation_index=index,
    )

records = []
for opened, metrics in states:
    print(f'Measuring state with {len(opened)} open keys', flush=True)
    start = time.perf_counter()
    old = render(opened, metrics, reuse=False)
    old_seconds = time.perf_counter() - start
    start = time.perf_counter()
    new = render(opened, metrics, reuse=True)
    new_seconds = time.perf_counter() - start
    old_json = json.dumps(old, cls=PlotlyJSONEncoder, sort_keys=True)
    new_json = json.dumps(new, cls=PlotlyJSONEncoder, sort_keys=True)
    assert old_json == new_json
    records.append({
        'open_keys': len(opened), 'expanded_metrics': metrics,
        'rows_rendered': sum(type(node).__name__ == 'Tr' for node in walk(new)),
        'json_bytes': len(new_json.encode()),
        'fresh_index_seconds': round(old_seconds, 4),
        'reused_index_seconds': round(new_seconds, 4),
    })

index = cache.hierarchy_index(scope)
metrics = index.aggregate(index.frame)
assert np.isclose(metrics['risk'], frame.risk.sum())
assert np.isclose(metrics['pl'], frame.pl.sum())
assert np.isclose(metrics['move'], 0.0001)
assert len(cache._hierarchies) == 1 and not cache._rendered
result = {
    'fixture': 'Synthetic 100k raw positions across 400 books; 250 shared quotes. Not production data.',
    'source_rows': len(scope), 'portfolios': scope.portfolio.nunique(),
    'prepared_frame_bytes': int(frame.memory_usage(index=True, deep=True).sum()),
    'retained_index_accounted_bytes': cache._hierarchy_bytes,
    'index_entries': len(cache._hierarchies), 'retained_explorer_trees': len(cache._rendered),
    'records': records,
    'warm_median_fresh_seconds': statistics.median(r['fresh_index_seconds'] for r in records[1:]),
    'warm_median_reused_seconds': statistics.median(r['reused_index_seconds'] for r in records[1:]),
    'risk_total': metrics['risk'], 'pl_total': metrics['pl'], 'move': metrics['move'],
    'verification': 'Serialized visible tables exactly equal; totals conserved; one retained index. Server timings only; no browser/RSS/production capacity claim.',
}
(ROOT / 'cache-scale-results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
print(json.dumps(result, indent=2))
```

## Appendix C — audit evidence and coverage

### Evidence and limitations

The audit used the local V5 source, GitHub repository/default-branch metadata, the existing benchmark, read-only archive metadata, and bounded synthetic probes. Production source credentials, production connector latencies, worker memory logs and a real browser crash trace were not provided. Source-confirmed allocation and duplication hazards are not proof of which one caused the reported crash.

Documentation validation applies the embedded cache patch to isolated copies of the five baseline files and compares the results with the current local files. It also verifies the embedded diagnostic, navigation links, Markdown fences and standalone Python block syntax. Targeted signature/branch/expression fragments require the stated surrounding code. These checks validate the guide and exact patch, not the runtime behaviour of every unapplied proposal.

| Evidence | What it establishes | What it does not establish |
|---|---|---|
| Exact local git diff in Appendix A | Every line of the implemented Risk cache change and its regression additions | That publishing Markdown has applied code remotely |
| Prior full-tree 686-test result | Existing local cache/Statics/tool tree passes the repository suite | That unapplied proposals or a 100k expanded browser workload pass |
| Nine-operation benchmark rerun | Current fixture budgets pass with stated scopes | Production capacity or browser layout performance |
| Appendix B cache comparison | Identical output and index reuse on four small views of 100k synthetic positions | Old cached-HTML hit latency or all-open Portfolio safety |
| Risk grouping/detail/Search probes | Same checked outputs; sibling grouping avoids repeated scope scans | Every promotion/connector/null edge case or browser timings |
| Stock pivot/detail probe | Exact fixture pivot equality, lower grouped build time, large full-detail JSON cost | Real Stock source cardinality or performance of the unapplied page callback |
| Eight DuckDB filter predicate comparisons | Predicate matches tested current pandas/legacy-label semantics | Full repository integration or an approved new alias policy |
| Supplemental validator/finite/tenor probes | Reported isolated timings and tested valid/rejected outputs | A proportionate full-refresh improvement for the user's Risk data |
| Statics serialized fixture tables | Native pagination retains a full data payload | Actual worker RSS or source-file production sizes |
| Archive metadata timings | Repeated local fingerprint/discovery has measurable cost | Whole-file rehashing per click or network-share timing |

Temporary audit scripts were kept outside `cube/` and did not alter real connectors or completed archives. Their workspace names are `cache-scale-probe.py`, `probe-risk-ui-optimisations.py`, `optimisations-history-probe.py`, `optimisations-history-sql-probe.py`, `optimisations-stock-wiring-probe.py`, `optimisation_pipeline_probe.py`, and `optimisations-root-probes.py`. Appendix B embeds the complete cache comparison required to reproduce the repeated fix. The numbered sections contain the actual proposed replacements used for the documented local comparisons; additional cases there are explicitly required before integration.

### Area-by-area coverage

| Area | Source boundary searched/reviewed | Outcome |
|---|---|---|
| Entry point and app assembly | `app.py`, `cube/app/`, page shell, startup worker, service protocols | Preserve lazy import, prepared revision and narrow snapshot access; one Portfolio callback return-copy gap |
| Product/schema/source boundaries | `cube/app/s02_contracts.py`, `cube/history/s02_contracts.py`, `cube/domain/`, `cube/services/`, adapters and product registry | Preserve strict quote/position contracts; grouped supplemental validation and safe within-attempt reuse |
| Refresh and financial release | Refresh manager, state, calculations, governance, mappings, search publication | Preserve atomic last-good state and selective caches; profile stage costs before removing copies |
| Risk | Every module in `cube/pages/risk/`, shared aggregation/tree helpers | Implemented cache included; output bounds, sibling groups, hidden cells, detail reuse and remaining workspace retention |
| Search/Quick Risk/Quick Market | Search catalog, quote bridge, callbacks/pivots | Narrow filter slices; retain bounded quick views and independent market rollups |
| Data/history | All `cube/history/`, Data selection/view/callbacks | Grid preflight and filter pushdown first; existing canonical browser playback remains |
| Stock | Loader/display, pivot, current/history callbacks and SQL source | Lazy detail/pagination, sibling grouping and batched exact history; preserve metadata versus measure grain |
| P&L | Layout/callbacks, summary, Validate, editor/sender/history | Bound hidden tree and numeric cache; child lookup; preserve revision-aware mutation boundaries |
| Statics | Store/view/callbacks | Retain picker reset and atomic writes; avoid hidden Read work; read paging separate from editable buffers |
| Browser assets | All tracked JavaScript/CSS, particularly table gestures and chart/playback lifecycle | Resize/selection work; retain scoped observers, token actions and theme-only Plotly updates |
| Runtime and persistence | Logging, jobs, archives, gunicorn, cloud config, publish script | Bound small accumulators; retain single worker, integrity checks and isolated publish staging |
| Tests, benchmarks, fixtures | All tracked test modules, tools, requirements, pytest config and read-only sample data | Use representative existing harness; add missing visible/payload/concurrency scope rather than more generic infrastructure |

`experiments/` and the prior optional chart-preview artifacts are development/reference material, not active startup or request paths. Their presence should not be blamed for the user's live table rendering without an import/deployment reference. This audit intentionally does not rewrite historical Parquet/CSV data for a source performance review.

### Complete tracked source/test/asset inventory

The baseline inventory below contains 168 tracked Python, JavaScript and CSS paths outside `experiments/`. Listing is coverage of the source search, not a claim that each line has a measured performance defect. Numbered findings identify the executed or directly inspected paths. Optional tools added during the earlier review are listed separately. Historical fixture files are data, not an optimisation target to rewrite.

#### Root runtime/publication

- `app.py`
- `gunicorn.conf.py`
- `publish.py`

#### assets

- `assets/s01_shell.css`
- `assets/s02_controls.css`
- `assets/s03_risk.css`
- `assets/s04_pnl.css`
- `assets/s05_responsive.css`
- `assets/s06_visuals.css`
- `assets/s07_history.css`
- `assets/s08_promotions.css`
- `assets/s09_playback.js`
- `assets/s10_theme.js`
- `assets/s11_tables.js`
- `assets/s12_refresh.js`
- `assets/s13_risk.js`
- `assets/s14_app_logs.css`
- `assets/s14_pnl.js`

#### cube/__init__.py

- `cube/__init__.py`

#### cube/adapters

- `cube/adapters/__init__.py`
- `cube/adapters/s01_common.py`
- `cube/adapters/s02_ir.py`
- `cube/adapters/s03_fx.py`
- `cube/adapters/s04_credit.py`
- `cube/adapters/s05_commodities.py`
- `cube/adapters/s06_crossgamma.py`
- `cube/adapters/s07_newpositions.py`
- `cube/adapters/s08_stock.py`

#### cube/app

- `cube/app/__init__.py`
- `cube/app/s01_settings.py`
- `cube/app/s02_contracts.py`
- `cube/app/s03_logging.py`
- `cube/app/s04_startup.py`
- `cube/app/s05_progress.py`
- `cube/app/s06_routing.py`
- `cube/app/s07_factory.py`
- `cube/app/s08_applogs.py`

#### cube/domain

- `cube/domain/__init__.py`
- `cube/domain/s01_schema.py`
- `cube/domain/s02_products.py`
- `cube/domain/s03_calculations.py`
- `cube/domain/s04_crossgamma.py`
- `cube/domain/s05_newtrades.py`
- `cube/domain/s06_reporting.py`
- `cube/domain/s07_governance.py`
- `cube/domain/s08_pnl.py`
- `cube/domain/s09_stock.py`
- `cube/domain/s10_search.py`
- `cube/domain/s11_tenorreduction.py`

#### cube/history

- `cube/history/__init__.py`
- `cube/history/s01_models.py`
- `cube/history/s02_contracts.py`
- `cube/history/s03_io.py`
- `cube/history/s04_queries.py`
- `cube/history/s05_store.py`
- `cube/history/s06_repository.py`
- `cube/history/s07_sql.py`

#### cube/pages/__init__.py

- `cube/pages/__init__.py`

#### cube/pages/data

- `cube/pages/data/__init__.py`
- `cube/pages/data/s01_selection.py`
- `cube/pages/data/s02_view.py`
- `cube/pages/data/s03_callbacks.py`

#### cube/pages/pnl

- `cube/pages/pnl/__init__.py`
- `cube/pages/pnl/s01_common.py`
- `cube/pages/pnl/s02_editor.py`
- `cube/pages/pnl/s03_history.py`
- `cube/pages/pnl/s04_sender.py`
- `cube/pages/pnl/s05_sendcallbacks.py`
- `cube/pages/pnl/s06_validation.py`
- `cube/pages/pnl/s07_view.py`
- `cube/pages/pnl/s08_aggregate.py`
- `cube/pages/pnl/s09_drilldown.py`
- `cube/pages/pnl/s10_summary.py`

#### cube/pages/risk

- `cube/pages/risk/__init__.py`
- `cube/pages/risk/s01_common.py`
- `cube/pages/risk/s02_state.py`
- `cube/pages/risk/s03_defaults.py`
- `cube/pages/risk/s04_handoff.py`
- `cube/pages/risk/s05_charts.py`
- `cube/pages/risk/s06_explorertables.py`
- `cube/pages/risk/s07_explorer.py`
- `cube/pages/risk/s08_quickrisk.py`
- `cube/pages/risk/s09_quickmarket.py`
- `cube/pages/risk/s10_search.py`
- `cube/pages/risk/s11_promotion.py`
- `cube/pages/risk/s12_promotecallbacks.py`
- `cube/pages/risk/s13_workspacetables.py`
- `cube/pages/risk/s14_workspacecallbacks.py`
- `cube/pages/risk/s15_refresh.py`
- `cube/pages/risk/s16_view.py`
- `cube/pages/risk/s17_callbacks.py`

#### cube/pages/s01_notfound.py

- `cube/pages/s01_notfound.py`

#### cube/pages/static_data

- `cube/pages/static_data/__init__.py`
- `cube/pages/static_data/s01_store.py`
- `cube/pages/static_data/s02_view.py`
- `cube/pages/static_data/s03_callbacks.py`

#### cube/pages/stock

- `cube/pages/stock/__init__.py`
- `cube/pages/stock/s01_data.py`
- `cube/pages/stock/s02_history.py`
- `cube/pages/stock/s03_view.py`
- `cube/pages/stock/s04_callbacks.py`
- `cube/pages/stock/s05_pivot.py`

#### cube/services

- `cube/services/__init__.py`
- `cube/services/s01_snapshots.py`
- `cube/services/s02_state.py`
- `cube/services/s03_adjustments.py`
- `cube/services/s04_savedviews.py`
- `cube/services/s05_sources.py`
- `cube/services/s06_refresh.py`
- `cube/services/s07_tenorreduction.py`
- `cube/services/s08_jtd.py`

#### cube/ui

- `cube/ui/__init__.py`
- `cube/ui/s01_constants.py`
- `cube/ui/s02_aggregation.py`
- `cube/ui/s03_filters.py`
- `cube/ui/s04_components.py`

#### tests

- `tests/s01_schema.py`
- `tests/s02_checker.py`
- `tests/s03_adapters.py`
- `tests/s04_market.py`
- `tests/s05_pl.py`
- `tests/s06_ui.py`
- `tests/s07_integration.py`
- `tests/s08_feeds.py`
- `tests/s09_plui.py`
- `tests/s10_reads.py`
- `tests/s11_fixtures.py`
- `tests/s12_startup.py`
- `tests/s13_publish.py`
- `tests/s14_reporting.py`
- `tests/s15_overlays.py`
- `tests/s16_refreshshell.py`
- `tests/s17_stock.py`
- `tests/s18_newpositions.py`
- `tests/s19_riskfilters.py`
- `tests/s20_connectors.py`
- `tests/s21_provenance.py`
- `tests/s22_refreshdates.py`
- `tests/s23_savedviews.py`
- `tests/s24_plhistory.py`
- `tests/s25_crossgamma.py`
- `tests/s26_newtrades.py`
- `tests/s27_expandable.py`
- `tests/s28_validation.py`
- `tests/s29_archive.py`
- `tests/s30_history.py`
- `tests/s31_data.py`
- `tests/s32_observability.py`
- `tests/s33_riskstate.py`
- `tests/s34_riskpivot.py`
- `tests/s35_pipelinearch.py`
- `tests/s36_riskarch.py`
- `tests/s37_domainarch.py`
- `tests/s38_uiarch.py`
- `tests/s39_assets.py`
- `tests/s40_pagearch.py`
- `tests/s41_modulearch.py`
- `tests/s42_statics.py`
- `tests/s43_reducedtenor.py`
- `tests/s44_tenorreductionsource.py`
- `tests/s45_failurevisibility.py`
- `tests/s46_applogs.py`
- `tests/s48_jtd.py`
- `tests/s48_pinnedpromotions.py`

#### tools

- `tools/__init__.py`
- `tools/s01_fixtures.py`
- `tools/s02_archive.py`
- `tools/s03_benchmark.py`

#### Earlier optional review tools, outside baseline

- `tools/s04_chart_previews.py`
- `tools/s05_demo_history.py`
- `tools/s06_read_demo_history.py`

