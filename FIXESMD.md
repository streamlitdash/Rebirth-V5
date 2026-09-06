# FIXESMD — exact changes, operation and next implementation steps

Reviewed and assembled on **6 September 2026**. Repository: `streamlitdash/Rebirth-V5`. GitHub `main` was rechecked today and still points to **`8f65a1124e54702597347967c7064eb4f7edf133`** (`Cache reduced tenor by revision`).

## 0. Read this distinction first

This file records the work from the 4–6 September review session and the subsequent local Risk-cache implementation. The larger page redesigns remain **proposals**. The delivered changes and their exact reproduction instructions are distinguished from work that is still proposed.

The delivered local version consists of:

1. The existing two-file **Statics Write picker fix**, implemented and browser-tested.
2. **`tools/s04_chart_previews.py`**, an optional standalone Plotly preview generator, plus generated `docs/chart-previews/index.html` and `data.json`. The Dash app does not import this tool.
3. **`tools/s05_demo_history.py` and `tools/s06_read_demo_history.py`**, optional synthetic-history generation/read tools. They use existing archive and reader contracts. They do not install a scheduler or real-data connector.
4. **`FIXESMD.md` and `NEWTESTS.md`**, the requested manuals. `NEWTESTS.md` contains the complete component/file inventory, architecture and test map.
5. The Portfolio proposal and review reproductions, included below. The main Risk grouping is **not changed** in this local app version.
6. The exact tool-file manifest in `tests/s35_pipelinearch.py` now includes the three new optional tools. The legacy-boundary assertions remain in place.
7. The **Risk Explorer cache change** in four application modules, with regressions in `tests/s19_riskfilters.py`: reuse a bounded numeric/quote index across expansion states, stop retaining Explorer component trees, and guard refresh/clear publication. Exact placement is in Steps B4–B5 and every diff hunk is in Appendix A.

The earlier Statics/tools delivery passed **672 tests**. The additional Risk cache patch now passes the full suite: **686 tests, 56 warnings, 116.04 seconds**. Whole-repository Ruff and all 11 changed/added Python file formatting checks passed. Part H records the verification scope and the synthetic scale comparison.

**Capacity clarification:** the user reports roughly 100k rows and 300–400 portfolios. Part C recommends a paged Portfolio breakdown or bounded inline expansion. The reusable-index patch is now implemented, but it does not add pagination or a displayed-row limit. The two-file inline Portfolio proposal is still insufficient by itself for a production rollout at that volume.

**Publication destination:** `streamlitdash/Rebirth-V5`, branch `v4`. The application, test and optional tool changes described here remain local; this publication adds the manuals only. The reviewed and tested snapshot is the stated `main` baseline plus those local changes, not the destination branch. No application deployment, scheduled task, static-data save or downstream P&L send has been performed. Synthetic history was generated into a separate workspace directory; it was not mixed into the repository's checked-in archive. The original reviews below include historical verification statements that apply to their stated date; this opening ledger is the authority for the delivered state.

The three optional tool sources are reproduced in this manual's appendices. Their Python files, generated preview gallery and workspace logs/results are not included in this documentation-only publication. Follow the reproduction instructions to create them locally and adapt example workspace paths to your checkout.

## 1. How to use this manual

Navigation: [Baseline](#part-a--establish-the-exact-starting-point) · [Statics](#part-b--reproduce-the-implemented-statics-and-risk-cache-fixes) · [Risk cache](#step-b4-implement-the-reusable-risk-index) · [Portfolio](#part-c--portfolio-on-the-main-risk-page) · [Charts](#part-d--the-new-chart-results-and-how-to-reproduce-them) · [History and Stock columns](#part-e--history-daily-capture-adjustments-logging-and-stock-columns) · [Remaining migration](#part-f--exact-migration-order-for-the-other-reviewed-issues) · [Current usage](#part-g--what-is-currently-implemented-and-how-to-use-it) · [Validation](#part-h--validation-delivery-and-rollback) · [Full applied patch](#appendix-a--complete-applied-applicationtest-patch).

Follow Parts A–E in order to reproduce the delivered version. Part F is the explicit migration plan for reviewed issues that remain unimplemented. Do not treat a proposal as a tested patch. The appendices include full source for every new Python tool and the full applied application diff, so the delivered version can be reconstructed without omitted code.

The Portfolio and history/Stock sections include their own numbered instructions. They distinguish a currently supported action, a tested proposal, and a future feature needing integration. Locations use **file path + function/constant name**; line numbers in earlier evidence are baseline pointers and can move after edits.

## Part A — establish the exact starting point

### Step A1. Preserve your existing work

Run from your repository checkout:

```powershell
git status --short
git rev-parse HEAD
git diff --stat
```

Do not reset or overwrite an existing checkout to follow this guide. If it has unrelated edits, use a separate checkout. For a new directory:

```powershell
git clone https://github.com/streamlitdash/Rebirth-V5.git Rebirth-V5-review
Set-Location Rebirth-V5-review
git switch -c review-guided-fixes 8f65a1124e54702597347967c7064eb4f7edf133
```

These are user-run reproduction commands; this review has not created or pushed that branch. If your intended `main` has advanced, compare its changes before applying the exact baseline snippets. Do not assume an old line number still identifies the right code.

### Step A2. Install the repository's pinned dependencies

For a new Windows environment:

```powershell
py -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt -r requirements-dev.txt
& '.\.venv\Scripts\python.exe' -m pytest -q
```

For this review workspace, the existing interpreter is `..\.review-venv\Scripts\python.exe` when running from `repo`. Substitute that path for `.\.venv\Scripts\python.exe` in the commands below if working here. No dependency upgrade is part of these changes.

The baseline full suite passed **668 tests** during the earlier review. That is a dated baseline result, not a promise that a different environment or production connector will pass.

## Part B — reproduce the implemented Statics and Risk cache fixes

### Step B1. Locate the callback insertion point

Open `cube/pages/static_data/s03_callbacks.py`, function `register_callbacks`. Find `render_static_data_table`, whose final statement returns `build_static_data_table(selected_file, store=static_store)`. Insert the following callback immediately after that function and immediately before the existing callback that outputs the Write table's `columns` and `data`.

```python
    @app.callback(
        Output("static-data-write-table", "filter_query"),
        Output("static-data-write-table", "sort_by"),
        Output("static-data-write-table", "page_current"),
        Output("static-data-write-table", "hidden_columns"),
        Output("static-data-write-table", "active_cell"),
        Output("static-data-write-table", "selected_cells"),
        Input("static-data-write-selector", "value"),
    )
    def reset_static_table_view(_selected_file):
        # DataTable retains view state when its data and schema are replaced.
        # A filter on a column from the previous file can hide every new row.
        return "", [], 0, [], None, []
```

No new imports are needed: `Input` and `Output` are already imported. Remove nothing from the data-loading/editing callback. Do not reset this state on every Save or Add Row; this callback is triggered by choosing a different dataframe.

### Step B2. Add the regression test

In `tests/s42_statics.py`, place the exact new parametrized test from Appendix A after `test_statics_empty_editor_mounts_without_fixed_header_crash` and before `test_static_store_writes_validated_csv_atomically`. All of its imports/helpers already exist in that module. Appendix A is the complete applied diff, including the test; it contains no elided sections.

### Step B3. Run focused checks

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/s42_statics.py -q
& '.\.venv\Scripts\python.exe' -m ruff check cube/pages/static_data/s03_callbacks.py tests/s42_statics.py
& '.\.venv\Scripts\python.exe' -m ruff format --check cube/pages/static_data/s03_callbacks.py tests/s42_statics.py
git diff --check
```

Verified result in this workspace: **13 passed**, lint/format passed. Dash DataTable deprecation warnings remain; migrating the entire table system is not necessary for this bug fix.

### Step B4. Check the actual failing interaction

1. Start the app with `python app.py --port 8057` using your environment's Python.
2. Open Statics → Write → Portfolio Mapping.
3. Filter its Portfolio column to one displayed value; `BOOK_A` was the review's test value.
4. Change the picker to Top Thresholds.
5. Confirm the filter is cleared and the new dataframe's rows are visible.
6. Change to Concerto Mapping and Reported Underlying Mapping; confirm each schema and its rows match the selection.
7. Return to Portfolio Mapping and confirm it still loads.

This browser sequence was executed successfully. No Save is needed. The original failure was retained view state: the picker and new columns changed, but the old Portfolio filter hid the new rows. The fix changes no static data. Switching dataframes already replaced unsaved table rows before this patch; the patch adds no new draft-discard behavior.

### Step B5. Roll back only this change if necessary

If no subsequent changes touched these blocks, remove `reset_static_table_view` and its decorator, then remove the added parametrized test. Alternatively reverse the exact Appendix A patch with `git apply -R --check` followed by `git apply -R` against a saved patch file. Do not use a whole-file reset if the files contain other changes.

### Step B4. Implement the reusable Risk index

This is now an **applied local change**, following the cache discussion. The original `main` creates `HierarchyAggregationIndex` inside each new Cross table build and caches up to 24 finished table variants. The delivered Explorer instead reuses the numeric/quote index for the same filtered data and Credit measure, and renders the requested visible rows without retaining complete Explorer tables.

The code changes are in four existing files; tests are in one existing module. **Appendix A contains every exact added/removed line, including all imports and regression tests.** Follow the numbered placement instructions below with those hunks, or apply the complete Appendix A patch once to the stated baseline. Do not apply it twice if the Statics or cache changes are already present.

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
12. **Validate and use:** run the focused command below, then the full delivered-tree checks in Part H. Restart the local application normally. No new UI setting is required. Open/close Risk branches and metric breakdowns as before; the unchanged data scope reuses the index. Change filters/measure or refresh and the corresponding data/index is used. Clear Cache drops retained indexes. Do not add Portfolio to shared registries as part of this change.

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/s06_ui.py tests/s19_riskfilters.py tests/s33_riskstate.py tests/s34_riskpivot.py tests/s36_riskarch.py -q
```

The 256 MiB budget bounds accounted retained index data in one cache instance. Other application data, the existing filtered-frame cache, workspace component caches, Python object overhead and temporary build allocations also consume memory. Oversized scopes still calculate without retention, so they can rebuild on subsequent expansion. Do not present the budget as a guarantee against out-of-memory failures.

This patch improves **index reuse**, not every part of table rendering. Visible rows are still rebuilt/serialized on each request, and returning to an identical view can cost more HTML construction than the old finished-table hit. SplitVA and Credit Multi stop retaining Explorer component trees but still use their existing per-render reductions; they do not gain the Cross numeric index. No row pagination, branch insertion protocol, new Portfolio filter or total visible-row cap was implemented. Those remain necessary follow-up work for unrestricted Portfolio display at the reported scale.

### Step B5. Reproduce the scoped capacity comparison

Appendix H contains the complete `cache-scale-probe.py` diagnostic. Save it next to a checkout named `repo`, then run it with that checkout's dependency environment. It constructs labelled synthetic **100,000 raw positions across 400 portfolios**, sharing 250 quotes; it does not read or write production sources. Its output is `cache-scale-results.json` beside the script. If your checkout has another name, update only its `ROOT / 'repo'` path references first.

```powershell
& '.\.review-venv\Scripts\python.exe' cache-scale-probe.py
```

The script compares the existing standalone fresh-index renderer with the new supplied-index path for four small visible scopes, and asserts exact serialized table equality and conserved Risk/P&L/quote values. It retains one index and no Explorer component trees. The output includes every measured time and accounted byte count. This is a controlled server-side comparison, not a browser benchmark, process-memory profile or approval to expand 100k grouped rows into books. Its full results are recorded in Part H.

To roll back this cache change independently, reverse only the four Risk/aggregation file hunks and the new s19 imports/tests in Appendix A. Keep the unrelated Statics fix and optional tools. Restart and rerun the focused tests. The cache patch changes no archive, connector or persisted financial data.


## Part C — Portfolio on the main Risk page

**Portfolio is already part of position identity. Adding a display grouping should not require changing Risk or Market connector schemas.** The detailed tested recipe below covers the relevant allowlists and the failure caused by registering Portfolio globally without following its existing data projection.

The old crash cannot be conclusively attributed without its traceback. This review reproduces current failure modes that plausibly explain it and tests a smaller implementation. Large unrestricted expansions can still become slow; a correct grouping implementation is not an unlimited performance guarantee.

### Portfolio on main Risk: diagnosis and a scoped implementation recipe

Portfolio was initially reviewed against `8f65a11`, with the local Statics picker patch present. Those source/callback probes changed no Risk application source and used temporary in-process substitutions only; their Portfolio patch remains unapplied. **Subsequently, the Risk cache change in Steps B4–B5 was implemented locally.** Earlier failure/capacity measurements below describe their original probe state; the current cache behavior is identified separately.

#### Answer

Portfolio can be shown on main Risk without changing the financial calculation grain. It is already part of every position and survives into the prepared Risk frame. The current UI intentionally excludes it from Risk filters and the shared view-dimension controls. A partial change at the wrong layer can throw an exception or silently lose book-level detail.

The smallest main Risk change is **an extra Portfolio leaf below the existing hierarchy**, plus a Portfolio entry in the row-identity allowlist. It is not a connector/schema change. Do not add Portfolio to the shared view-dimension registry just to obtain these rows: that registry also controls Split VA and Aggregate PL columns.

I cannot identify the historical crash conclusively without its traceback/version. I reproduced specific failures against this checkout that explain why a casual 'add Portfolio' edit is unsafe.

#### Production-volume clarification — 100k rows and 300–400 portfolios

The user subsequently reported approximately **100,000 rows before adding Portfolio to the view, across 300–400 portfolios**, and that the previous crash was reportedly caused by data volume. The exact meaning of the 100,000 count (raw positions or already grouped rows) remains unconfirmed. This changes the production recommendation: **the two-file leaf patch below is a functional recipe, not a sufficient production rollout for this volume.** A volume failure is credible independently of the separate duplicate-column exception reproduced earlier. No production crash trace or memory profile establishes which resource was exhausted.

Distinguish the two possible counts:

- If 100,000 is the raw position count across all books, Portfolio is already retained on those rows. Grouping by it does not inherently multiply the source into 30–40 million rows. It reveals more of the existing positions as separate display groups, plus hierarchy parents.
- If 100,000 is the number of groups after books have been combined, splitting each group into its contributing books can increase displayed leaves substantially. A fully populated case with 300–400 books in every group would contain 30–40 million group/book combinations; this is an illustrative dense upper case, not an estimate of this dataset. Count the actual distinct existing hierarchy keys plus Portfolio before attempting a render. Do not build a cross join or fill nonexistent position combinations.

The renderer skips descendants of closed rows (`cube/pages/risk/s06_explorertables.py::build_tree_rows`). Before the applied cache change, every new table state created a `HierarchyAggregationIndex` over the full filtered frame and `_RiskDataCache.rendered` retained up to **24 complete component trees**, bounded by count rather than size. **Current local behavior:** standard Cross/Credit Single reuses a bounded index for the same data scope/measure; all Explorer views stop retaining full component trees. Separate Aggregate P&L/Top Promotions caches still use `rendered`. Every Explorer request still builds its visible HTML and returns the complete visible table; there is no visible-row limit or pagination. Index retention, server construction, response size and browser load remain distinct quantities. Neither the historical nor current code establishes the original crash cause without its logs.

##### Revised minimal production design

1. Keep the default main Risk hierarchy aggregated across Portfolio. Display a portfolio count or a **View portfolios** action for an exact selected row.
2. Resolve that row's structured context, committed filters, product/measure, identity mode and data revision on the server. Reuse the existing scope and aggregation functions. Preserve independent unique-quote aggregation; adding books must not multiply Open/Current values.
3. Group only that selected scope by Portfolio. Show a searchable detail table with **50 portfolios per page as an initial policy**, subject to measurement. Perform search, sorting and pagination before constructing/sending browser rows. Sending every position and paginating in the browser does not provide this bound.
4. Calculate the selected-scope parent totals over all matching positions before slicing the display page. Label `Showing 1–50 of N portfolios` and keep those totals distinct from any displayed-page subtotal. A selected book can then open its tenor chart or positions.
5. If Portfolio must appear inline in the main hierarchy, add a shared displayed-row budget and branch continuation before enabling it. Count/limit nodes before allocating their components, including all already-open branches. Start collapsed; an unrestricted expansion is not a supported fallback.
6. **Implemented for Explorer in Step B4:** complete Explorer table variants are no longer retained, and standard Cross/Credit Single uses an index cache bounded by entries and accounted bytes. Workspace caches remain separate. This does not replace bounded output. A server-side Portfolio filter can further narrow the scope, but needs the complete filter integration described below.
7. Measure the real raw/prepared/filtered row counts, distinct group/book combinations, visible rows/cells, callback time, serialized response size, worker peak memory, and browser responsiveness. Exercise repeated scope/page changes as well as one initial load. Begin with a small scope and increase it progressively; do not construct the presumed worst case merely to discover that it fails.

This plan reuses the current pandas/Dash application. It does not require a new database, queue, or grid framework. A paged selected-scope detail is the recommended Portfolio implementation at the reported volume. The inline leaf patch below remains unapplied and its earlier small-data checks are not production capacity evidence. The initial capacity clarification changed documentation only; subsequent Steps B4–B5 implemented cache reuse and measured a synthetic 100k-raw-position/400-book fixture with small visible scopes. That comparison is not a fully expanded production capacity test.

#### What “add Portfolio” means here

| Requested behavior | Current behavior | Required change |
|---|---|---|
| Expand a main Cross row to see books | Portfolio is retained internally, but absent from tree groups and allowed row keys | Two-file leaf-row recipe below |
| Add Portfolio to Quick Risk's Rows selector | Domain pivot supports Portfolio, UI selector rejects it | Add the option locally; correct the existing footer issue before treating it as an authoritative total |
| Put one Portfolio label in every aggregate table row | A parent row often contains many portfolios | Show a book count/“Multiple (N)” or expand to book leaves; choosing the first book would mislabel the aggregate |
| Pivot Portfolio into horizontal Split VA columns | Global dimension selection currently falls back to Activity | A separate, capped portfolio-column design, including unique prepared-column projection and valid detail keys |
| Filter the whole Risk page by Portfolio | Risk registry excludes Portfolio, while Stock/P&L retain it | End-to-end filter-registry, saved-view, handoff, callback, and test change; adding a dropdown alone is insufficient |
| Add a new portfolio to connector/config data | Position schema already requires Portfolio | Supply a normal portfolio position and its governed config; do not duplicate Portfolio as metadata or add it to market quote keys |

There is no existing Statics switch that changes the Risk tree hierarchy. The Statics picker fix does not alter any of these contracts.

#### Reproduced current failure modes

1. **Shared view-dimension edit creates duplicate prepared columns.** `cube/ui/s02_aggregation.py::prepare_risk_data`, lines 453–471, explicitly emits `"portfolio"` and then expands `*VIEW_DIMENSIONS`. Temporarily adding `"portfolio"` to `VIEW_DIMENSIONS` produced two identically named output columns. Calling `build_alt_risk_table(..., dimension="portfolio")` raised `AttributeError: 'DataFrame' object has no attribute 'unique'` inside `ordered_unique` (line 884). A direct group-by on the duplicate label would also receive a DataFrame instead of a Series. The input duplicate check at lines 325–327 cannot catch a duplicate created later by the output projection.
2. **Hierarchy-only edit loses the leaves.** `ROW_KEY_COLUMNS` at `cube/ui/s01_constants.py:126` excludes Portfolio. `row_key` drops it, while `frame_for_context` rejects it (`cube/ui/s02_aggregation.py:899`, `:930`). Rendering groups `["risk greek", "portfolio"]` on two books displayed only `Delta`. Different book contexts also serialized to the same underlying-only key.
3. **Filter-only edit fails validation.** Passing `{ "portfolio": ["BOOK-A"] }` into `apply_filters` raised `ValueError: Unknown reporting-dimension filters: ['portfolio']`. See `cube/ui/s02_aggregation.py:474` and `cube/ui/s01_constants.py:45`.
4. **A selector value alone does not enable Portfolio.** The actual registered `reduce_and_render_risk_view` callback accepted `dimension="portfolio"` without crashing, but `selected_dimension` normalized it to Activity. Cross retained its fixed hierarchy; Split VA used Activity columns. See `cube/ui/s02_aggregation.py:887`, `cube/pages/risk/s07_explorer.py:596`, and `cube/pages/risk/s06_explorertables.py:414`.

These are different failure mechanisms. Removing a validator or adding the same field to several registries is not a complete repair.

#### Complete minimal main Risk recipe

Proposed patch: `portfolio-main-risk-proposed.patch` beside this guide. It passed `git apply --check` against this checkout. It adds book leaves to the shared main Risk hierarchy helper used by Cross, Split VA's row hierarchy, and Credit Multi. Existing promotion/region/identity logic and Activity remain in place; Portfolio comes last.

**1. `cube/ui/s01_constants.py`, `ROW_KEY_COLUMNS`, line 126**

Before:

```python
ROW_KEY_COLUMNS = ["label", "risk type", *ALT_GROUPS, *VIEW_DIMENSIONS]
```

After:

```python
ROW_KEY_COLUMNS = ["label", "risk type", *ALT_GROUPS, *VIEW_DIMENSIONS, "portfolio"]
```

This makes book row keys distinct and lets existing scope/detail callbacks filter the selected book. A group name without this change is incomplete.

**2. `cube/pages/risk/s06_explorertables.py`, `_active_groups_for_frame`, lines 42–67**

Replace its final return expression with:

```python
    groups = [
        group
        for group in get_active_groups(
            promotion_enabled,
            region_enabled,
            region_available=region_available,
        )
        if group not in {"reported underlying", "underlying"} or group == identity_group
    ]
    # Keep position identity local to the tree; shared view dimensions pivot columns.
    return [*groups, "portfolio"]
```

This helper is called by all three main Risk table builders. It preserves their current hierarchy and adds only the deepest book level. The existing lazy expansion means a closed parent does not render its Portfolio descendants.

**3. Preserve the schema/preparation boundaries.** This particular implementation does not edit `PORTFOLIO_FIELDS`, `PORTFOLIO_UI_FIELD`, `VIEW_DIMENSION_FIELDS`, `VIEW_DIMENSIONS`, `BASE_GROUPS`, `ALT_GROUPS`, `prepare_risk_data`, or connector keys. Because the extra group is local to rendering, the prepared column projection still emits exactly one Portfolio column. No column deduplication change is required for this recipe. Verify `prepared.columns.is_unique` and `list(prepared.columns).count("portfolio") == 1` in a regression test.

If a future feature deliberately puts Portfolio into shared `VIEW_DIMENSIONS` or `ALT_GROUPS`, its output projection must instead construct an ordered unique list of **column names** before indexing, e.g. `output_columns = list(dict.fromkeys([...]))`. Do not deduplicate position rows. That alternative also needs registry, labels, dimension-control, pivot-width, detail-key, saved-state and Aggregate PL tests. It is larger than the two-file leaf-row feature.

**4. Add focused regressions to `tests/s19_riskfilters.py`.** Keep the existing no-Portfolio-filter/no-shared-dimension tests: they remain correct with this scoped design. Add cases using `_raw_risk_frame` and `_reducible_raw_frame` that assert:

- Exactly one prepared Portfolio column; two input books remain two positions.
- Expanded main Cross shows BOOK-A and BOOK-B with distinct `data-risk-key` values. Expand using real visible tree levels, because scalar/curve placeholder tenor levels are skipped.
- `row_key`/`parse_row_key` round-trip a Portfolio context; `frame_for_context` selects the correct book; `detail_frame(..., {"portfolio": "BOOK-A"}, "risk")` returns Risk 10 and PL 4 in the two-book fixture.
- Parent Risk = 30 and PL = 10; parent Open = 3 and Current = 4 despite two book rows. Adding position detail must not multiply quotes.
- Region on/off, promotion on/off and reported/raw identity modes show book leaves without duplicate keys. Include scalar, curve, surface and Credit Multi branches.
- The actual registered main callback renders expanded leaves; the detail callback renders a selected book. A source helper test alone does not prove callback integration.

The two executable reproduction scripts beside this guide already exercise the runtime equivalents of these changes and retain their outputs. Port their focused assertions into the repository suite when implementing. Then run the applicable focused suite and `git diff --check`, and browser-test expansion/cell click after restarting the server.

**5. Review and apply only when implementing.** From the repo, check the patch with `git apply --check ../portfolio-main-risk-proposed.patch`; applying it is a separate step. Restart the app after an implementation, then select one Risk type/underlying and expand down through Activity to Portfolio. Reversing the same two-file patch removes the additional tree level; it changes no saved financial data.

If a UI on/off control is wanted instead of always-available leaf expansion, add explicit hierarchy state and include it in `risk_generation_state`/`risk_action_view_token`, cache keys, callback inputs, and selection reset behavior. A module-global per-user toggle would be incorrect. That optional control is not part of the minimal patch.

#### Validation and performance evidence

The local demo refresh completed with 10,572 dashboard rows, 502 portfolios, and 17 source families including scalar FX, curves, surfaces, Credit, Commo, and the cash-flow overlay. Tests used the current checkout and its real production demo refresh manager; nothing was sent externally.

Fixture results:

- Two books: Risk 10 + 20 = 30; PL 4 + 6 = 10.
- Book A detail remained Risk 10 and PL 4 after a valid Portfolio context was enabled.
- Parent market remained Open 3 / Current 4; both book leaves correctly reference the same quote.
- A correctly allowlisted direct tree rendered `Delta > USD-SOFR > 1Y > BOOK-A/BOOK-B` with distinct keys.

A synthetic 100-book × 10-tenor fixture, with two metric columns, measured:

| Tree placement/state | Rendered rows | Serialized component size | Server build time |
|---|---:|---:|---:|
| Portfolio last, collapsed | 1 | 1.8 KB | ~0.001 s |
| Portfolio last, all expanded | 1,012 | 1.84 MB | ~0.90 s |
| Portfolio above Underlying, all expanded | 1,201 | 2.18 MB | ~1.65 s |
| Split VA with 100 Portfolio columns, collapsed hierarchy | 3 including header | 91.6 KB | ~0.01 s |

The last case already creates 102 columns: index, 100 books, Total. Width/cell count increases even with a closed hierarchy. Tree figures are serialized Dash components and Python timings, not browser measurements or capacity guarantees. More visible metrics and broadly expanded books increase the payload further. Main Risk has no visible-row cap at `build_tree_rows` (`cube/pages/risk/s06_explorertables.py:138`). Keep Portfolio deepest, start collapsed, and add branch paging or a displayed-row budget before offering “expand all” on a large production book. Preserve full parent totals if children are paged, and state how many children are visible.

The scoped main-tree implementation also passed the actual registered main/detail callback fixture: BOOK-A and BOOK-B rendered under Activity with distinct Portfolio-bearing row keys; selected Book A detail rendered. All 17 demo source families were rendered under both reported and raw identity modes, with book leaves present in every nonempty case. Split VA with Activity columns and Credit Multi also rendered successfully.

For a deliberately broad direct-render stress test, all demo rows of each Risk type were expanded with promotion and region enabled:

| Direct-render scope | Source positions | Table rows including header/total | Serialized component size | Server build time |
|---|---:|---:|---:|---:|
| FX | 846 | 1,102 | 3.14 MB | 1.92 s |
| IR | 7,924 | 10,333 | 30.00 MB | 62.91 s |
| Credit | 973 | 1,317 | 3.80 MB | 2.73 s |
| Commo | 828 | 1,090 | 3.11 MB | 1.77 s |
| Cash Flow | 1 | 7 | 0.02 MB | 0.02 s |

**The all-IR row is an upper-bound stress probe, not a normal page timing.** The registered page callback applies `filter_ir_family` (`cube/ui/s02_aggregation.py:653`) before rendering, so ordinary UI requests contain only the selected IR family. Both filters and lazy expansion usually reduce scope further. Nevertheless, the broad test shows why successful rendering must not be described as an unlimited safety guarantee. Credit Multi over all demo Credit produced 1,314 table rows and 5.99 MB; its runtime was not separately recorded.

A second probe used the same IR family restriction as the page before fully expanding all remaining rows (all books, promotion and region enabled):

| IR family | Source positions | Table rows | Serialized size | Server build time |
|---|---:|---:|---:|---:|
| delta | 2,517 | 3,232 | 9.28 MB | 3.75 s |
| basis | 966 | 1,270 | 3.65 MB | 1.51 s |
| vega | 4,441 | 5,835 | 17.07 MB | 6.97 s |

Those family-scoped figures are relevant to the current page's possible scope, though they still force all branches open and are not browser timings. They support starting Portfolio leaves collapsed and bounding wide expansion. The family probe is `portfolio-ir-family-repro.py`.

One source-based optimization candidate is `build_tree_rows:156`: every recursive invocation recreates `set(open_rows or [])`, then passes the full list into its children. Construct the set once per render and reuse it. This repeated allocation is visible in source; its share of the measured time was not profiled. A rendering budget/paging design remains necessary even after that optimization because the final DOM/payload still grows.

See `portfolio-main-callback-results.json` for full-demo Cross/identity-mode and registered-callback results; `portfolio-risk-repro-results.json` contains baseline failures, financial fixtures, Quick Risk and synthetic size probes. These artifacts are more precise than a blanket statement that Portfolio “cannot crash.”

#### Quick Risk is an alternative, with a current totals caveat

The backend already accepts Portfolio in `SearchCatalog.pivot_combined_hierarchy` (`cube/domain/s10_search.py:1313`) and caps visible leaves. A local option could be added to `QUICK_SEARCH_INDEX_OPTIONS` at `cube/pages/risk/s08_quickrisk.py:29`:

```python
QUICK_SEARCH_INDEX_OPTIONS = (
    *_QUICK_SEARCH_IDENTITY_OPTIONS,
    ("Portfolio", "Portfolio"),
    *((field.label, field.external_name) for field in PORTFOLIO_FIELDS),
)
```

The actual Quick Risk rendering helper with that option rendered examples from all 17 demo source families without an exception. `cube/pages/risk/s10_search.py:178` reshapes selected rows to `Underlying > chosen non-tenor fields > product tenor axes`; selecting Underlying/Tenor/Portfolio therefore becomes Underlying/Portfolio/Tenor for curves. Scalar products have no tenor axis. The UI cap remains 250 leaf groups (`s08_quickrisk.py:18`), and parent domain aggregates use full matching source data.

However, `build_quick_search_pivot` currently sums every metric from the visible leaves for its footer (`s08_quickrisk.py:474–529`). That means:

- 300 identical Risk-10 books produce a full parent Risk of 3,000 but a footer labeled Total of 2,500 at the 250-leaf cap.
- With Open 3 / Current 4 per book, that footer shows Open 750 / Current 1,000 / Move 250. Quotes are not additive across portfolios.
- On the demo IR Delta grouped identity, 632 leaf groups were available; the 250 visible leaves summed to Risk ~161.8m against the complete identity Risk ~303.5m. The status text states a leaf count, but the generic Total label still invites the wrong reading.

Fix this footer before promoting Portfolio Rows as an authoritative workflow: label the visible-leaf subtotal, show full additive identity totals separately, and derive market summaries from unique quotes/full parent aggregation (or leave total market cells blank). The chart is also built from visible leaves, so disclose its same scope. Portfolio is a sensible Quick Risk addition, but the main tree recipe avoids exposing this existing footer defect as its primary path.

#### Financial/schema boundaries to preserve

`cube/domain/s03_calculations.py:535` includes Portfolio in position keys; line 577 validates unique position keys. `ProductSpec.market_keys` at `cube/domain/s02_products.py:171` deliberately excludes Portfolio. The Risk/market join at `cube/domain/s03_calculations.py:873` is `many_to_one`: many portfolio positions share an authoritative quote. Keep it that way.

`PORTFOLIO_FIELDS` contains config metadata; `Portfolio` is the separate identity at `cube/domain/s01_schema.py:15`. `PORTFOLIO_CONFIG_COLUMNS` line 124 already prepends it. Adding Portfolio as another metadata entry would duplicate the config identity as well as affecting downstream display registries.

The main tree's independent market aggregation (`cube/ui/s02_aggregation.py:941`, `HierarchyAggregationIndex`) and selected-book detail (`:1324`) already separate quote and position aggregation. Preserve those implementations. Quick Market explicitly rejects Portfolio as a Risk-only index (`cube/domain/s10_search.py:1200`); adding books to quote keys is not a solution.

No historical traceback, production load test, browser memory profile, or arbitrary custom connector dataset was available for this probe. The verified conclusion is narrower and useful: Portfolio is supported at position grain; the scoped main-tree change works through existing aggregation/callback contracts on the tested fixtures/demo; partial registry edits and unrestricted rendering remain concrete failure risks.

##### Exact unapplied Portfolio patch

Save this as `portfolio-main-risk-proposed.patch` outside the checkout if using the patch commands above. These bytes are not part of the applied application diff.

```diff
--- a/cube/ui/s01_constants.py
+++ b/cube/ui/s01_constants.py
@@ -123,7 +123,7 @@
 
 TOP_EXPOSURE_LABELS = ("Big Risk", "Big dRisk", "Big PL")
 TOP_EXPOSURE_GROUPS = ["label", "risk type", "risk greek", "reported underlying"]
-ROW_KEY_COLUMNS = ["label", "risk type", *ALT_GROUPS, *VIEW_DIMENSIONS]
+ROW_KEY_COLUMNS = ["label", "risk type", *ALT_GROUPS, *VIEW_DIMENSIONS, "portfolio"]
 METRIC_COLUMNS = ["risk", "drisk", "pl"]
 UNDERLYING_SORT_METRICS = tuple(METRIC_COLUMNS)
 DEFAULT_UNDERLYING_SORT_METRIC = "pl"
--- a/cube/pages/risk/s06_explorertables.py
+++ b/cube/pages/risk/s06_explorertables.py
@@ -54,7 +54,7 @@
         if str(underlying_identity_mode).strip().casefold() == "underlying"
         else "reported underlying"
     )
-    return [
+    groups = [
         group
         for group in get_active_groups(
             promotion_enabled,
@@ -63,6 +63,8 @@
         )
         if group not in {"reported underlying", "underlying"} or group == identity_group
     ]
+    # Keep position identity local to the tree; shared view dimensions pivot columns.
+    return [*groups, "portfolio"]
 
 
 def metric_class(column: str, expanded_metrics: list[str] | None = None) -> str:
```


## Part D — the new chart results and how to reproduce them

### Step D1. Add the optional generator

Create **`tools/s04_chart_previews.py`** with the complete source in Appendix B. The filename is already present in the delivered local version. Do not put it in `assets/`: Python tools are not browser assets. Do not import it from `app.py` or register new callbacks merely to preview charts.

### Step D2. Run it

```powershell
& '.\.venv\Scripts\python.exe' -m tools.s04_chart_previews --date 2026-08-21 --output docs/chart-previews
```

Optional `--archive` selects an archive root, but the preview intentionally expects the exact shipped synthetic USD SOFR / USD SOFR Vol identities. It is not a generic production report. A missing identity raises a clear error rather than silently selecting a different book.

It creates:

```text
docs/chart-previews/index.html   # offline Plotly gallery; the JS library is embedded
docs/chart-previews/data.json    # compact synthetic provenance and plotted values
```

Open `index.html` directly in a browser, or run `python -m http.server 8060 --bind 127.0.0.1` from the repo and visit `/docs/chart-previews/index.html`. Stop the temporary server when finished. No server or production account is needed to use the generated file.

### Step D3. Inspect all three proposals

1. **Risk curve:** exposure and hedge bars, plus net diamonds on the same y-axis. Negative exposure remains negative. The net is validated against exposure + hedges. A secondary axis no longer changes their apparent relative magnitude.
2. **Market curve:** Open and Current rate lines above a separate signed Move panel. The axes share tenor order; the two panels have explicit units. For this demo IR source only, decimal rates are displayed as percent and decimal changes as basis points. Do not apply those multipliers indiscriminately to FX, volatility, price or credit products.
3. **Surface:** a zero-centered signed heatmap with values in cells, plus an expiry profile. Click a heatmap cell or choose an expiry to update the profile. The plotted surface total is checked against the input risk total. All axes use existing connector ranks.

These are design previews. The application still uses its existing chart functions. The inline conversation preview uses the same synthetic values for comparison; its presentation code is not a dependency to install into Dash. Production implementation should use the existing Plotly/Dash stack.

### Step D4. The smallest first application chart change, if selected later

The missing Market Move graph and unattractive chart design are separate issues.

For the missing graph: in `cube/pages/risk/s05_charts.py::build_line_chart`, move the final `return dcc.Graph(...)` **out of the non-market `else` branch** so it executes for Open, Current, Move and Risk metrics. Keep the return's `figure` and config. This is a proposed code change, not part of the delivered app patch. Verify `open`, `current`, `move`, `risk`, `drisk` and `pl` each returns a Graph.

For the Risk design, edit only the non-market branch initially:

1. Keep `tenor_axis_order`, the grouping keys, `.sum(min_count=1)` and the ordered `curve` preparation.
2. Remove the secondary `yaxis2` layout and every `yaxis="y2"` trace assignment from that branch.
3. When breakdown columns exist, render Exposure and Hedges as grouped signed bars on `y`; render Net as a diamond marker on the same `y`. The trace patterns are fully implemented in Appendix B's `risk_curve`.
4. For a metric without a breakdown, render one signed bar series on `y` rather than inventing Exposure/Hedges columns.
5. Use raw application values and the active metric's units. The preview's division by one million is a labelled display choice, not a change to the calculation or export.
6. Keep source tenor order, missing observations, ambiguous-order annotations, callback return type and the matrix/table beside the graph.
7. Use a single legend, visible zero line, restrained grid, readable 12–13px labels, and responsive dimensions. Do not replace the existing table when changing the chart.

For the Market design, use separate Plotly subplots within `build_line_chart` when Move is selected. Preserve its existing unique-quote aggregation before plotting. Rates and moves require ProductSpec-aware display metadata; the fixed synthetic conversions in the preview are not a production-wide contract. Open/Current alone can be simple lines.

For the surface, edit `build_tenor_heatmap`: keep `_tenor_surface_pivot`, connector order and missing-cell values; replace the red/green scale with a clear signed scale, make the chart responsive, and put sparse-cell values in hover or in cells when the matrix is small. Add the linked row/column profile only after its selection is shared with the detail table. Do not sum market quotes merely to reuse a Risk slice.

### Step D5. Chart acceptance checks before application rollout

Check scalar, swap-only, option-only and two-axis selections; Risk/dRisk/P&L and all three market metrics; positive, negative and missing values; long labels; narrowed and combined-underlying scopes; full/reduced tenor views. Confirm totals and row counts stay unchanged. Test the displayed chart and table together in the browser at normal and narrow widths. Preview appearance does not prove these production branches have been implemented.

## Part E — history, daily capture, adjustments, logging and Stock columns

### History, daily capture, adjustment records, and Stock columns

Source section for FIXESMD. Reviewed Rebirth v5 at `8f65a11`, 2026-09-06. No application source was changed by this work. Existing Statics edits belong to the parent task. Older workspace helper commands are retained as the execution ledger. Prefer the portable repository tools in section 11 and the full source in this manual’s appendices; those have no workspace-name dependency.

#### 1. What already exists, and what is missing

| Need | Current producer / storage | Current reader | Required work |
|---|---|---|---|
| Daily official Risk | `archive_official_snapshot()` writes committed `dashboard_frame` to `risk.parquet` | Data `ArchiveHistoryRepository`; SQL `risk_history` | Connect real dated Risk/market sources and schedule capture. A browser refresh does not automatically archive. |
| Daily Market | Same writer writes the complete `market_frame` to `market.parquet` | Data history; `market_history` | Keep full quote grain, including market-only tenors. |
| Predict P&L | Already contained in `risk.parquet` as `PL` | `SQLPLHistoryRepository` derives Predict | Do not add a second independently calculated predicted.csv for v4. |
| Actual/Colossus P&L | Dated `colossus_loader` writes `colossus.parquet` | `SQLPLHistoryRepository`, P&L Validate | Replace the demo Colossus function with a real dated source. |
| Stock | Writer supports optional `stock_frame` and writes `stock.parquet` | `SQLStockHistoryRepository`; offline SQL `stock_history` | **Stock is missing from the normal manager/scheduled capture path.** Add a wrapper that fetches/validates same-date Stock before the archive is committed. |
| Active saved P&L adjustments | `LocalCsvAdjustmentRepository`, date/portfolio CSVs | P&L editors/effective-send rows | Already persists current state. This is not an immutable edit history. |
| Every adjustment change / who changed it | None | None | Add a durable versioned adjustment/audit store. |
| Exact P&L payload sent, recipient outcome, receipt | None; callbacks invoke send functions and display status | None | Add a durable send-attempt/outcome ledger and retain payload hashes/bodies. Demo send functions intentionally reject delivery. |
| Every intraday risk revision / raw feed payload | None; refresh owns in-memory snapshots | No replay reader | Separate capture store keyed date/run/revision, with snapshot metadata. Do not overload one-leaf-per-day official archive. |
| Application timings and errors | Python logging + bounded in-memory Application Logs | UI log panel / process output | Route process output to durable rotating/platform logs; logs do not replace financial payload history. |

Evidence: `cube/history/s03_io.py:779–976`; `cube/services/s01_snapshots.py:41–64` has no Stock field; `tools/s02_archive.py:57–69`; `app.py:69–91`; `cube/services/s03_adjustments.py`; `cube/pages/pnl/s05_sendcallbacks.py:713–807`; `cube/app/s03_logging.py:32–36,279–307`.

#### 2. Generate safe synthetic history now

The checked-in application data is synthetic. Generating more dates with its fixture builders demonstrates readers; it does not create real financial history. The fixture builder only accepts its governed date range. It does not backfill arbitrary real dates.

The repository fixture command has only `--check` and `--probe-size`. Running it without either flag rewrites repository CSVs and the full fixture archive (`tools/s01_fixtures.py:2109–2152`). There is no `--output`, `--start`, or `--end` option on the existing fixture CLI. `tools.s02_archive` has no argparse date/output CLI at all.

Use the supplied **new** helper `generate_demo_history.py`. It calls the real public fixture builder and official writer, requires an output directory, and rejects any path inside `repo`. From this workspace:

```powershell
Set-Location 'C:\Users\cheny\Documents\Codex\2026-09-04\look-at-rebirth-v5-on-github'
& '.\.review-venv\Scripts\python.exe' '.\generate_demo_history.py' --start 2026-08-19 --end 2026-08-21 --output '.\demo-history-sep06'
& '.\.review-venv\Scripts\python.exe' '.\read_demo_history.py'
```

Both commands were executed successfully. They create/read only the isolated demo directory. The helper builds each day with `tools.s01_fixtures.build_official_history_fixture(day)` and passes a synthetic snapshot carrying `fixture="deterministic-rebirth-v4"` to `cube.history.archive_official_snapshot`. It does not send P&L.

Observed per day:

```text
2026-08-19 archived risk 10000 market 5000 colossus 5000 stock 5000
2026-08-20 archived risk 10000 market 5000 colossus 5000 stock 5000
2026-08-21 archived risk 10000 market 5000 colossus 5000 stock 5000
Validated completed schema-v4 days and all payload hashes: 3
risk_history 30000
market_history 15000
colossus_history 15000
stock_history 15000
```

Rerun one day to prove idempotence:

```powershell
& '.\.review-venv\Scripts\python.exe' '.\generate_demo_history.py' --start 2026-08-21 --end 2026-08-21 --output '.\demo-history-sep06'
```

Verified output: `2026-08-21 already_archived ...`; all payload hashes still passed. Completed dates are not overwritten.

##### Resulting files and contracts

```text
demo-history-sep06/
  2026-08-19/
    risk.parquet
    market.parquet
    colossus.parquet
    stock.parquet
    _SUCCESS
  2026-08-20/...
  2026-08-21/...
```

`_SUCCESS` is JSON, not an empty marker. It records schema version 4, official Market Date/status, revision, refresh timestamp, risk source dates, row counts, exact columns, optional Stock metadata, and SHA256 for every payload. The writer writes a temporary sibling leaf, writes `_SUCCESS` last, and renames the leaf into place (`s03_io.py:872–943`). Do not create the marker by hand, add unrelated files to completed leaves, or overwrite parquet files underneath existing hashes.

Exact fixed payload schemas:

```text
Colossus: Portfolio, Underlying, Risk Type, Risk Greek, PL
Stock: CRDS, CPTY, Portfolio, Instrument, Currency, Quantity, Market Value
Market: Source Type, Risk Type, Risk Greek, Underlying,
        Tenor Swap, Tenor Option, Tenor Swap Order, Tenor Option Order,
        Market Date, Open, Current, Move, Market Status, Market Data Status
```

Risk is the committed flat dashboard frame, including Portfolio/reporting identity, tenor axes and order, Risk/dRisk/PL, market status, promotion fields, and applicable Credit measures. Keep the validated frame; do not substitute a grouped display tree. Colossus grain is its first four columns; Stock currently uses its first five text columns as identity. Risk source dates may differ from the archive Market Date; the manifest's `risk_dates` map preserves that fact.

#### 3. Read the archive with the current APIs

The supplied `read_demo_history.py` is an executed example. Equivalent code from a process whose import path includes `repo`:

```python
from pathlib import Path
from cube.history import (
    ArchiveHistoryRepository, HistoryQuery, SQLPLHistoryRepository,
    list_completed_v4_archive_days, open_history_database,
)
from cube.pages.stock.s02_history import (
    SQLStockHistoryRepository, stock_history_identity_from_token,
)

root = Path(r'C:\Users\cheny\Documents\Codex\2026-09-04\look-at-rebirth-v5-on-github\demo-history-sep06')
days = list_completed_v4_archive_days(root)  # strict completed-leaf validation

pl = SQLPLHistoryRepository(root)
print(pl.series(preset='all').series)
# Other supported selection arguments: path, history_types,
# preset='custom', start_date, end_date, filters, criteria, exclude_selected.

data = ArchiveHistoryRepository(root)
entry = next(e for e in data.catalog().entries
             if e.kind == 'market' and len(e.identity.axes) == 0)
bundle = data.read(HistoryQuery(handoff=entry.to_handoff(), period='all'))
print(bundle.values)

stock = SQLStockHistoryRepository(root)
choice = stock.catalog(limit=1).options[0]
identity = stock_history_identity_from_token(choice['value'])
print(stock.rows(identity, '2026-08-19', '2026-08-21'))

db = open_history_database(root)
try:
    print(db.execute('SELECT * FROM archive_days ORDER BY "Snapshot Date"').df())
    print(db.execute('SELECT count(*) FROM stock_history').fetchone())
finally:
    db.close()
pl.clear()
stock.clear()
```

Verified: P&L reader returns six daily points (Predict and Colossus for each of three dates); Data scalar Risk/Market each returns three canonical values; Stock returns three observations with Quantity and Market Value. These are existing API names, not proposed API.

##### Point the local app at this archive

```powershell
$env:PL_HISTORICAL_PATH = 'C:\Users\cheny\Documents\Codex\2026-09-04\look-at-rebirth-v5-on-github\demo-history-sep06'
$env:PL_ADJUSTMENT_PATH = 'C:\Users\cheny\Documents\Codex\2026-09-04\look-at-rebirth-v5-on-github\demo-adjustments-sep06'
Set-Location 'C:\Users\cheny\Documents\Codex\2026-09-04\look-at-rebirth-v5-on-github\repo'
& '..\.review-venv\Scripts\python.exe' '.\app.py' --port 8052
```

`PL_HISTORICAL_PATH` feeds all three history readers via `app.py:63–91`, despite its PL-specific name. Choose **All** or the explicit three-day custom range when testing. Data lets you select an archive-backed identity directly. Stock's inline history still starts from an identity in the current Stock book (`stock/s04_callbacks.py:562–573`), so an archived-only identity is not directly discoverable through that page yet; the reader API can still query it.

This environment variable does **not** replace current feeds: demo `GetStock` still reads its hardcoded fixture root (`adapters/s08_stock.py:42,231–246`), and demo Colossus still reads `data/histo` in `services/s05_sources.py:636–642`. Configure those current/source boundaries separately for a real deployment. An `S3://` URI is not a drop-in substitute for the local Path root; sync complete governed leaves to a local mounted directory first, or implement a supported remote storage adapter.

#### 4. Real end-of-day capture

##### Preconditions

1. Replace the personal Risk/Open/Current connectors and dated Portfolio/reporting config using the existing adapter boundaries. Fetch actual dates from authoritative systems.
2. Replace `cube.services.s05_sources.get_colossus_pl(market_date)`, or set `COLOSSUS_LOADER=your_importable_module:function`. It must return the exact five-column schema above with unique four-key identity. This environment variable is consumed by `tools/s02_archive.py:35–54`.
3. Replace the Stock callable at app composition with a real `GetStock(date)` returning the exact seven-column contract. Use `build_stock_adapter(stock=your_get_stock)` to validate it. Merely changing a display table cannot add an upstream field.
4. Decide which daily timestamp is official, where the persistent archive root lives, and how failures will be retried/reconciled.

Existing command, **after real connector integration**:

```powershell
$env:PL_HISTORICAL_PATH = 'D:\Rebirth\history'
$env:COLOSSUS_LOADER = 'your_site_module:get_colossus_pl'
& 'C:\path\to\venv\Scripts\python.exe' -m tools.s02_archive
```

That command currently captures Risk, Market, and Colossus. It does not capture Stock because the manager snapshot has no `stock_frame`. The writer will skip non-OFFICIAL snapshots, forced/non-natural Market Dates, or snapshots carrying refresh errors (`history/s03_io.py:793–817`). A same-date rerun returns `already_archived`.

##### Minimum new Stock capture addition

Add a small job composition wrapper, rather than making the Risk refresh manager own the Stock UI. The following is a **proposed new function**, assembled from current interfaces:

```python
from types import SimpleNamespace
from pathlib import Path
import pandas as pd
from cube.adapters.s08_stock import build_stock_adapter
from cube.domain.s03_calculations import market_date_for
from cube.history import archive_official_snapshot

def archive_with_stock(manager, colossus_loader, get_stock, root):
    snapshot = manager.refresh(
        force_risk=True, force_pl=True, reason='scheduled_official_archive'
    )
    stock_date = pd.Timestamp(snapshot.market_date).normalize()
    natural_date = market_date_for(snapshot.system_date).normalize()
    if (str(snapshot.market_status).strip() != 'OFFICIAL'
            or snapshot.errors or stock_date != natural_date):
        return archive_official_snapshot(snapshot, colossus_loader, root)
    leaf = Path(root).expanduser().resolve() / stock_date.date().isoformat()
    if leaf.exists():
        # Validates the existing leaf before taking the idempotent return.
        result = archive_official_snapshot(snapshot, colossus_loader, root)
        if not (leaf / 'stock.parquet').is_file():
            raise ValueError('Completed daily leaf lacks Stock; governed repair required')
        return result
    stock = build_stock_adapter(stock=get_stock).get_stock(stock_date)
    capture = SimpleNamespace(
        revision=snapshot.revision,
        refreshed_at=snapshot.refreshed_at,
        system_date=snapshot.system_date,
        market_date=snapshot.market_date,
        market_status=snapshot.market_status,
        risk_dates=snapshot.risk_dates,
        dashboard_frame=snapshot.dashboard_frame,
        market_frame=snapshot.market_frame,
        errors=snapshot.errors,
        stock_date=stock_date,
        stock_frame=stock,
    )
    return archive_official_snapshot(capture, colossus_loader, root)
```

Pass the same real Stock callable used by `app.py` into this wrapper. Do not attach the synthetic `fixture` tag to real captures. The Stock read must succeed before publishing the completed daily leaf. Stock Date must equal Market Date (`s03_io.py:855–864`). If a completed leaf already lacks Stock, rerunning the writer will not append it: create a deliberate governed repair/migration process with validation rather than editing that leaf ad hoc.

The proposed wrapper was exercised with synthetic inputs and successfully wrote 5,000 Stock rows into a separate demo leaf. It is not installed in the application or invoked by the existing CLI. Recommended finishing checks for the wrapper: return distinct exit status/structured run result for skipped versus failed attempts; validate that the completed leaf includes all expected payloads; record the capture date, revision, row counts and path. Keep actual source-system timestamps, receipt identifiers and data-cutoff policy in operational metadata. If Colossus is not ready when Risk becomes OFFICIAL, the job should retry later; one dated leaf is a coherent daily cut, not a place to mix arbitrary source vintages.

##### External scheduling, without creating an automation here

Use Task Scheduler, the existing Jupyter Scheduler notebook, or the deployment runner. `jobs/s01_archive.ipynb` already invokes `tools.s02_archive.run_from_env()`; it needs updating to the Stock wrapper if Stock is required.

Configure the runner with the absolute Python path, repository working directory, environment/root paths, service credentials, and an end-of-day trigger **after the real source's official cut**. Do not assume a universal 17:30 cutoff. Use one capture attempt at a time; retry transient failures and not-yet-OFFICIAL responses. Alert if the expected `_SUCCESS` leaf is still absent by the agreed deadline. Ordinary successful execution is insufficient if the result says `skipped`.

There is currently no real historical-range CLI. Do not force the live system date or mislabel current data to invent a backfill. A real backfill requires dated source APIs, historical Portfolio/reporting authority and source risk dates, then the same validation/writer contract. The synthetic helper is not that backfill integration.

#### 5. Daily Risk snapshots versus every-revision logging

The official archive is one completed cut per Market Date. It stores the committed flat financial result, not every raw feed response, every refresh attempt, or every browser filter. If daily official Risk is the goal, use that existing archive.

If the goal is “reconstruct every intraday decision,” add a separate store such as:

```text
capture_events/YYYY-MM-DD/<run-id>/
  risk.parquet
  market.parquet
  unmapped.parquet
  metadata.json
```

Proposed metadata: run ID, UTC captured-at, market/source risk dates, revision, refresh reason, source status, connector version, mapping version/hash, errors and payload hashes. Key by a unique run ID plus revision; process revision alone restarts with the process. Capture only committed revisions, and record failed refresh attempts separately without presenting retained last-good values as a new successful snapshot. If raw feed auditing is required, retain raw connector payloads before transformation in a separate governed data zone.

Do not put these extra files inside a completed schema-v4 daily leaf: strict readers validate its expected entries. Build a separate intraday reader/UI only if that workflow is needed. Current code has no automatic append-on-refresh persistence hook.

#### 6. Adjustments: current values exist; the audit trail does not

Existing layout:

```text
adjustments/YYYY-MM-DD/<safe-portfolio-name>--<12-char-hash>.csv
```

Exact persisted columns:

```text
Market Date, Risk Type, Risk Greek, Portfolio, SignoffGroup,
ConcertoField, PL, Adjustment, Base Revision, Saved At UTC, Adjustment ID
```

The business key is Market Date + Portfolio + ConcertoField. `save()` validates rows, replaces complete files for the selected portfolios, preserves unrelated portfolios, rejects a lower base revision, and generates new Adjustment IDs (`services/s03_adjustments.py:228 onward`). Empty replacement for a named portfolio clears its saved rows. This is current active state, not a sequence of all edits.

Executed in isolated `demo-adjustments-sep06`: saved one adjustment 125, then 150 under the same date/key. `load()` returned one row containing 150; the Adjustment ID changed. The prior 125 value was no longer stored by that repository. `Saved At UTC` and `Base Revision` alone cannot reconstruct who changed what.

##### Minimal extension for auditability

Add a durable append-only event/version store with these explicit fields:

```text
event_id, occurred_at_utc, actor, action,
market_date, base_revision, portfolio, concerto_field,
before_payload, after_payload, payload_sha256,
reason, request_id, outcome
```

Use an authenticated actor from the deployment identity boundary; the current app does not supply one. Do not quietly treat a browser-entered name or operating-system account as authenticated identity. Require a reason if the business workflow requires one.

Put the integration at the repository boundary, so both SOG and Portfolio Save use it. A separate logger call after `LocalCsvAdjustmentRepository.save()` is not a transactional audit design: the CSV can change while audit writing fails. The clean small deployment option is one SQLite transaction that appends the version/event and updates active adjustment state; the CSV format can remain an export/import boundary. A shared multi-process deployment should use an appropriate shared database. Preserve the repository's `load` and `save` interface for the editors.

Before replacing storage, write tests for create/change/clear, same-revision competing edits, rollback, date/portfolio scope, old revision rejection and actor/reason presence. Do not describe the existing CSV save timestamp as a complete audit trail.

##### Sending is a separate record

P&L history currently shows Predict/Colossus; it does not show an immutable effective-P&L series incorporating every saved adjustment or every sent payload. For reconciliation, retain four distinct concepts: base Predict, adjustment versions, effective approved value, and actually sent payload/receipt. Do not silently add saved adjustments to historical Predict and rename the result Predict.

For each destination, persist the exact governed payload and hash with a request/idempotency key before sending; record accepted/rejected/unknown status and provider receipt afterward. The hook points are `pnl/s05_sendcallbacks.py:752` for selected scope and `:789–797` for Send All. A crash after delivery but before receipt recording must remain “unknown,” with retry governed by destination idempotency, rather than being called “failed” and blindly resent. The existing demo send functions at `services/s05_sources.py:676–693` intentionally reject all delivery. No P&L was sent during this review.

Application Logs are a bounded in-memory console (200 records), with timing logs deliberately excluding financial values (`app/s03_logging.py:32–36,304–307`). Configure persistent process logs separately, for diagnosis. They do not substitute for the financial audit records above.

#### 7. Stock columns already available in the UI

Before adding fields, open **Position detail · unaggregated connector rows** (`pages/stock/s03_view.py:153–191`). It already exposes:

```text
CRDS, CPTY, Portfolio, Activity, SignoffGroup, Category, SubCategory,
Product, Instrument, Currency, Quantity, Stock, dStock, Portfolio Mapped
```

These are not missing from the connector. The main pivot intentionally shows a subset. Its row selector already supports Activity, Category/Bucket, CRDS, CPTY, Portfolio, SignoffGroup, SubCategory, Product, Currency and Instrument. Column splits currently support Currency/Product; values support Stock/dStock (`stock/s05_pivot.py:17–36`). The detail table has horizontal scrolling, sorting/filtering and paging.

`Quantity` is already a finite numeric connector and archive column. `Stock` is current Market Value; `dStock` is current minus prior Market Value. Prior/Current Quantity and Quantity Change already exist in the comparison frame (`domain/s09_stock.py:36–45,436–499`). Do not rename or repurpose Risk fields to display them.

#### 8. Worked numeric change: expose Quantity and dQuantity

##### A. Quantity in the pivot, with no schema change

In `cube/pages/stock/s05_pivot.py`, replace the values tuple at line 35 with:

```python
STOCK_PIVOT_VALUES = (
    ('Stock', 'Stock'),
    ('dStock', 'dStock'),
    ('Quantity', 'Quantity'),
)
```

Keep `STOCK_PIVOT_DEFAULT_VALUES` unchanged if Stock/dStock should remain the default. The layout derives options from this tuple. `Quantity` already reaches the display frame and numeric detail formatting.

Quantities should not be blindly totaled across unrelated instruments/contract units. For a conservative first implementation, replace `_metric_value` at `s05_pivot.py:143–145` with:

```python
def _metric_value(frame: pd.DataFrame, metric: str) -> float | None:
    if metric in {'Quantity', 'dQuantity'}:
        if len(frame[['Instrument', 'Currency']].drop_duplicates()) != 1:
            return None
    value = pd.to_numeric(frame[metric], errors='coerce').sum(min_count=1)
    return None if pd.isna(value) else float(value)
```

This displays quantities at compatible instrument/currency scopes and leaves heterogeneous parent totals unavailable. If the real source defines another compatible unit identity, use that explicit authority instead.

##### B. dQuantity in detail and pivot

1. In `pages/stock/s01_data.py`, import `QUANTITY_CHANGE_COLUMN` from `cube.domain.s09_stock`.
2. Add `'dQuantity'` after `'Quantity'` in `STOCK_DISPLAY_COLUMNS` (`:63–78`).
3. Add `QUANTITY_CHANGE_COLUMN` beside `CURRENT_QUANTITY_COLUMN` in the explicit display projection (`:175–190`).
4. Add `QUANTITY_CHANGE_COLUMN: 'dQuantity'` to the rename mapping (`:193–198`).
5. Add `('dQuantity', 'dQuantity')` to `STOCK_PIVOT_VALUES`.
6. Add `'dQuantity'` to both numeric sets in `pages/stock/s03_view.py:60,176`.

Expected example: prior Quantity 100, current 125 -> Quantity 125, dQuantity 25. Added/removed leg handling should follow `compare_stock_snapshots`, not a new calculation in the table. The current detail display excludes prior-only removed positions (`s01_data.py:172`); if removed positions should be reviewable, add a separate Added/Changed/Removed comparison view instead of pretending all rows are current positions.

##### C. Quantity history

The archive and `SQLStockHistoryRepository.rows()` already return Quantity. The figure is hardcoded to Market Value in `pages/stock/s02_history.py:414–455`. To add a Quantity history mode:

1. Add a visible metric selector with exact options Market Value / Quantity in `build_stock_history_section`.
2. Add its value as an Input to the Stock history callback at `pages/stock/s04_callbacks.py:508 onward`.
3. Parameterize `stock_value_history_frame` and `build_stock_value_history_figure` with a validated metric from `STOCK_HISTORY_METRICS` (`s02_history.py:36`); use the selected source column and label the output Quantity/dQuantity when chosen.
4. Preserve the extra preceding-business-day read already present at `s04_callbacks.py:591–608`, so the first visible delta can be computed.
5. Before summing Quantity, verify that the selected identities have one compatible Instrument/Currency unit, or require selection of one exact position/instrument. The current chart combines identities under CRDS + Activity; that scope can include heterogeneous quantities.
6. Test missing dates: a missing observation remains unavailable; do not manufacture a zero holding or a change over a missing previous business day.

#### 9. Worked metadata change: add ISIN without changing position identity

Do **not** just append ISIN to `STOCK_TEXT_COLUMNS`. In current code `STOCK_IDENTITY_COLUMNS = STOCK_TEXT_COLUMNS` (`domain/s09_stock.py:21–30`). Doing that would change comparison keys, history identity tokens, archive schema and every old schema-v4 leaf. `validate_stock_frame` requires exact ordered columns (`:365–398`). It also makes a metadata correction look like an Added/Removed position.

For an optional display-only ISIN, retain the current seven-column Stock source/archive and join an authoritative dated instrument lookup after financial comparison. Example lookup:

```text
Instrument,ISIN
Bond A,GB0000000001
Bond B,US0000000002
```

The values above are illustrative metadata, not claims about actual securities. Resolve metadata as of the displayed Stock date if historical interpretation matters. Keep dated files outside completed archive leaves, for example `stock_metadata/2026-08-21/instruments.csv`. Do not use today's mapping to imply historical metadata was the same.

##### Exact pure enrichment helper for a new `pages/stock/s06_metadata.py`

```python
import pandas as pd

def enrich_stock_isin(display: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    required = ['Instrument', 'ISIN']
    if list(metadata.columns) != required:
        raise ValueError('Instrument metadata must be exactly Instrument, ISIN')
    lookup = metadata.copy()
    for column in required:
        valid = lookup[column].map(lambda value: isinstance(value, str) and bool(value.strip()))
        if not valid.all():
            raise ValueError(f'{column} must contain nonblank text')
        lookup[column] = lookup[column].astype('string').str.strip()
    if lookup['Instrument'].duplicated().any():
        raise ValueError('Instrument metadata must have one row per Instrument')
    result = display.merge(lookup, on='Instrument', how='left',
                           sort=False, validate='many_to_one')
    if len(result) != len(display):
        raise AssertionError('Metadata join changed Stock row count')
    return result
```

Do not use `drop_duplicates()` to hide conflicting Instrument->ISIN mappings. Missing lookup rows remain null. Do not aggregate ISIN text in numeric totals.

##### Wire it through the existing current-view flow

1. Add an optional `instrument_metadata: pd.DataFrame` field to `StockPageData` in `pages/stock/s01_data.py:82–89`, with an empty two-column default via `dataclasses.field(default_factory=...)` for old fixtures/callers.
2. Add optional `instrument_metadata_source` to `load_stock_page_data` (`:306`), accepting a dated callable or DataFrame. Resolve it once for `current` after source reads, validate it, and include it in the returned `StockPageData`. Do not fetch it on each expand/click.
3. Add `instrument_metadata=None` to `stock_display_rows`. Build the existing display projection first, then call `enrich_stock_isin(display, metadata)` before the final output-column selection. If no source is configured, supply an empty `Instrument,ISIN` frame. Add `'ISIN'` after `'Instrument'` in `STOCK_DISPLAY_COLUMNS`.
4. Pass `page_data.instrument_metadata` to display calls in `pages/stock/s04_callbacks.py:198,361,393` and `pages/stock/s03_view.py:638`. This keeps direct component and live callback paths aligned.
5. Add the optional metadata source to Stock callback registration (`s04_callbacks.py:104–112`), and pass it into the load call at `:183–189`.
6. Thread that source through `cube/app/s07_factory.py::build_app` to Stock callback registration (`:732 onward`) and through Stock direct-source helpers if used. In `app.py::create_app`, pass the dated site metadata source alongside `stock_source` and `stock_portfolio_source`. This is a new explicit injection, not an existing environment variable.
7. Position detail automatically derives columns from `STOCK_DISPLAY_COLUMNS`; optionally add `('ISIN','ISIN')` to pivot row fields if grouping by it is useful. It remains metadata, not a value metric or source identity.

Acceptance checks: before/after numeric totals and row counts identical; two positions in different Portfolios retain two rows; duplicate lookup Instrument rejected; missing ISIN remains blank; changing ISIN alone does not change Added/Removed classification; existing schema-v4 history still loads unchanged. If a future requirement is to embed new fields directly in `stock.parquet`, introduce a versioned archive contract and backward-compatible reader deliberately instead of changing the meaning of existing v4.

Executed the helper above on three synthetic display rows: row count stayed three, Quantity/Stock/dStock values were byte-for-byte unchanged at DataFrame comparison, one missing ISIN stayed null, and a duplicate Instrument lookup raised the specified error. The full UI wiring is a proposed change, not an implemented feature.

#### 10. Validation and rollout checklist

Run focused existing tests from repo using the review environment:

```powershell
& '..\.review-venv\Scripts\python.exe' -m pytest -q tests/s17_stock.py tests/s31_data.py
```

Locate archive/adjustment test modules with `rg --files tests` before naming further paths; add targeted behavioral tests alongside existing cases. Required capture checks: non-OFFICIAL skip, error snapshot skip, repeated date no-op, complete Stock payload when requested, mismatched Stock Date rejection, exact schemas, SHA mismatch rejection, and no reader visibility before `_SUCCESS` publication. Test the writer and real readers together, as the supplied synthetic helper does.

Keep demonstration output, production archive root, audit store and process logs distinct. Use persistent storage with backups for production. After adding new official leaves while an app is running, Clear Cache or let the existing generation check discover the change; restart if necessary. Do not replace the committed demonstration archive to test one small feature.

#### 11. Portable optional tools now included in the reviewed patch

The review-only helpers described earlier have now been ported into two optional repository tools. They are implemented additions to this patch, separate from the existing production scheduling entry point. They do not change or run the Dash app, call live connectors, send P&L, or edit existing completed archives.

From the repository root, using the project's activated Python environment:

```powershell
python -m tools.s05_demo_history --start 2026-08-19 --end 2026-08-21 --output ../demo-history
python -m tools.s06_read_demo_history --archive ../demo-history
```

For this review environment specifically, `python` can be replaced with `& '..\.review-venv\Scripts\python.exe'`. The tool paths and imports are portable; there are no hardcoded user or workspace paths.

`s05_demo_history.py` requires `--output` outside the repository. It rejects the full request before writing if the requested date range extends beyond the governed synthetic range (2025-08-21 through 2026-08-21), is reversed, or contains no business days. The dates are generated using the existing deterministic fixture builder, with the original source-specific Risk Dates retained. Market/Stock dates are the synthetic archive date. The entire existing output root must be empty or contain only complete `deterministic-rebirth-v4` fixture days; real/untagged, incomplete, legacy or unrelated contents are refused before generation. Existing tagged days are checked against their completion markers, payload hashes, ordered schemas and row counts. The existing schema-v4 immutable writer creates new days and returns `already_archived` for existing ones.

`s06_read_demo_history.py` requires `--archive`, verifies synthetic provenance, derives its start/end from available completed days, and uses the real P&L, Data and Stock readers. It prints a prominent `SYNTHETIC` label, P&L daily values, scalar Risk/Market history counts, and Quantity/Market Value history for one exact Stock identity. It is read-only. This is a smoke-test/read example, not a comprehensive business reconciliation report.

Executed validation:

- Re-ran all three existing isolated days (2026-08-19 through 2026-08-21): `already_archived` for each, and every pre-existing manifest/payload hash remained unchanged.
- Strict schemas and SHA-256 verification passed: Risk 30,000 rows; Market, Colossus and Stock 15,000 rows each across those three days.
- Actual readers returned six P&L rows (Predict/Colossus × three dates), three Risk and three Market observations, and three Stock observations.
- A fresh isolated two-day generation succeeded and the reader automatically reported 2026-08-20 through 2026-08-21.
- Requests extending beyond the fixture range, a reversed range, a weekend-only range, output inside the repository, and a copied complete archive with its synthetic marker removed all failed before new archive writes. The untagged archive copy's hashes remained unchanged.
- Ruff check and Ruff format check pass for both new tool files.

To display the isolated history in the application, set the existing reader setting before launch:

```powershell
$env:PL_HISTORICAL_PATH = (Resolve-Path '../demo-history').Path
python app.py
```

This setting controls the historical readers. The current Stock/source adapters retain their existing configuration; a history root does not create or replace today's live positions. Restore or remove the environment variable after the demo session if the same terminal will be used for another environment.


### Exact placement for the proposed Stock archive wrapper

This subsection completes the job wiring for the `archive_with_stock` function shown above. It remains a proposal; the delivered CLI has not been changed to capture real Stock.

1. Open **`tools/s02_archive.py`**. Put `archive_with_stock` immediately after `_default_manager_factory` and before `run_scheduled_archive`. Copy its complete body from the history section above.
2. Add `from types import SimpleNamespace`, `import pandas as pd`, `from cube.adapters.s08_stock import build_stock_adapter`, and `from cube.domain.s03_calculations import market_date_for` with the imports. `Path` is already imported; do not add it twice. In the `cube.history` import list replace `archive_from_manager` with `archive_official_snapshot`, because the new wrapper now owns the refresh/Stock attachment.
3. In `run_scheduled_archive`, add the optional keyword argument `stock_loader: Callable | None = None` after `colossus_loader`.
4. Keep the existing environment/root/Colossus resolution and manager construction. Replace its final statement `return archive_from_manager(manager, loader, root, refresh=True)` with:

   ```python
       if stock_loader is None:
           from cube.adapters.s08_stock import get_stock

           stock_loader = get_stock
       return archive_with_stock(manager, loader, stock_loader, root)
   ```

5. The default is the same `get_stock` boundary currently injected by `app.py`. Replace that site's implementation with the real dated source before relying on it for production. For injected jobs/tests, pass `stock_loader=your_dated_callable`. Do not invent an existing `STOCK_LOADER` environment variable; this baseline has none.
6. `run_from_env()` can stay unchanged because it already delegates to `run_scheduled_archive()`. **`jobs/s01_archive.ipynb` can also stay unchanged under this exact same-module implementation**, because it already calls `run_from_env()`. If you instead put the wrapper in a new job module, change the notebook import explicitly; do not do both variants.
7. In `main()`, include `stock_rows={result.stock_rows}` in the printed result beside the existing row counts. Do not interpret an ordinary process exit as an archived date if `result.status` is skipped. Configure the runner to distinguish skipped/not-yet-official from completed and failed.
8. Update the scheduler fixtures in `tests/s29_archive.py`, especially `test_manager_and_scheduler_wrapper_force_one_coherent_refresh`, to pass an exact seven-column same-date Stock fixture. Keep the legacy-leaf rejection test. Add mismatch-date, Stock-loader failure, valid complete Stock manifest, existing leaf without Stock, non-OFFICIAL skip and idempotent completed-day cases. Verify the actual Stock reader sees the resulting date before enabling scheduling.
9. Run `python -m pytest tests/s29_archive.py tests/s17_stock.py -q`, then the full suite and `git diff --check`. The existing fixture publisher checks its specific synthetic archive; do not run it to publish newly captured real financial history without adapting that release contract.

## Part F — exact migration order for the other reviewed issues

The following changes are **pending**. They are included to preserve every finding and its implementation boundary, not to claim that a new financial workflow has already been installed. Where the change needs a business decision, the decision is named explicitly rather than filled with guessed semantics.

### Step F1. Make P&L effective-value arithmetic consistent

Files: `cube/domain/s08_pnl.py`, `cube/pages/pnl/s02_editor.py`, `cube/pages/pnl/s05_sendcallbacks.py`, `cube/services/s03_adjustments.py`.

1. Decide whether an entered adjustment is a replacement value or a delta. Current persisted overlay is replacement; the added-row editor can instead sum with the base.
2. For the smallest compatible correction, retain **replacement** persistence and label the UI accordingly. Add/modify rows through one full business key: Market Date + Portfolio + ConcertoField, with Risk Type/Greek and SOG governed by mapping.
3. In the scoped-send path of `s05_sendcallbacks.py`, replace the independent collapse of all displayed rows with the same base-plus-adjustment overlay used for the saved effective result. Reuse `apply_adjustment_overlay`; do not add a second financial calculator in a callback.
4. In Save, load the complete active adjustment set for each touched portfolio before replacing its file. Upsert edited keys; preserve keys not edited, even when Show adjustments is off. A deletion must be explicit rather than inferred from the hidden subset.
5. If a whole-portfolio replacement remains the repository API, supply the complete updated portfolio set to it. Keep its atomic file replacement and validation.
6. Use an adjustment-store version for concurrent editing; the risk snapshot's Base Revision alone cannot distinguish two saves against the same snapshot. The audit/storage section describes a single transactional store if this is required.
7. Make preview, Save, scoped Send and Send filtered book display/use the same effective result. Distinguish pending draft changes from persisted changes before sending.
8. Add regression cases: base 100 plus entered replacement 10 previews/saves/sends 10; explicit delta mode, if added, consistently produces 110; editing IR preserves existing FX; explicit clear works; a stale concurrent save cannot silently overwrite the newer adjustment.

### Step F2. Preserve Data's query scope and loaded-state identity

Files: `cube/pages/data/s02_view.py`, `s03_callbacks.py`, `cube/history/s01_models.py`, `assets/s09_playback.js`.

1. Keep one draft containing kind, exact identity, imported Risk contributor filters and period/dates. Populate it once when consuming a Quick handoff.
2. In `choose_history_request`, stop rebuilding the same imported identity through a filter-free catalog `to_handoff()` when Load or period changes should preserve its scope. Reuse the imported filter view when its identity still matches. Clearing scope must be visible and explicit.
3. Move Load after the full query control set in `s02_view.py`.
4. Build the loaded caption from the committed request/bundle, not from uncommitted selector values. Include filter include/exclude semantics and actual date range.
5. When the active kind changes, either restore that kind's own loaded result or clear the incompatible result. Preserve a prior result during draft editing only with its own caption and a pending-changes label.
6. Hydrate the period/custom dates alongside identity when returning to the page; shell request persistence without matching control hydration caused MTD data beneath All.
7. Keep dataset identity separate from view/slice/date state in `s09_playback.js`. Remove view/slice/compare dates from the key that resets the player to its last observation. Preserve/clamp the selected date only when the dataset changes.
8. Compute single-series bounds from the selected projection. Share bounds only when a comparison or explicit scale lock requires them.
9. Test the actual journeys: Quick Risk Activity 1 → Data → reload; Risk load → Market tab; MTD → another page → return; chosen date → different chart view.

### Step F3. Correct quote aggregation before redesigning Data charts

Files: `assets/s09_playback.js` and `cube/pages/risk/s08_quickrisk.py`.

1. Use `bundle.kind` to distinguish additive Risk from Market quote levels in the history view choices.
2. Remove the generic Market Sum choice; select an exact fixed tenor. Add a defined average/basket only when constituents, weighting, units and coverage are explicit.
3. In the Quick Risk footer, do not sum Open/Current/Move across Portfolio rows. Use an available authoritative quote aggregate only where it has a meaning, or leave the footer unavailable. All-missing quotes must not become zero.
4. Distinguish complete hierarchy totals from a capped visible-leaf subtotal. Either calculate from the full filtered population or label the visible subset and its coverage. Do not relabel 250 shown books as the total of 300.
5. Regressions: duplicate positions sharing one quote do not multiply its value; 20 + missing does not masquerade as a market fall from a previously summed 50; missing quote totals remain missing; capped display and full population are distinguishable.

### Step F4. Preserve Stock selected scope and complete totals

Files: `cube/pages/stock/s05_pivot.py`, `s01_data.py`, `s04_callbacks.py`, `s02_history.py`.

1. Replace the clicked-history population represented only by CRDS + Activity with the exact constituent identities resolved from the applied filters and clicked row/column. Retain the selected path and revision in the selection payload.
2. Resolve a row click against that filtered population, not the unfiltered current snapshot. Manual broad search remains a separate explicit action.
3. Remove silent first-eight column truncation. Page columns or show an explicit remainder and compatible totals. Do not mix currencies to make a convenient grand total.
4. Add Current positions / Changes as separate projections over the existing outer comparison. Include prior-only exits in Changes and retain current-only semantics in Current positions.
5. Re-derive route-default dates when the relevant snapshot/date authority changes; invalidate dependent history when its source revision changes.
6. Replace a missing-leaf internal-path error with requested date, latest available date and an explicit load-latest action. Do not silently use old data under a current label.
7. Regressions: clicked 100 cannot broaden to 1,000; nine currency columns cannot omit the ninth silently; a 500 exit reconciles whole-book change −390 rather than current-only +110; refresh and missing-date states retain truthful captions.

### Step F5. Normalize the demo/current/archive identity boundary

Files: `cube/adapters/s08_stock.py`, `cube/pages/stock/s02_history.py`, `cube/history/s07_sql.py`, and the current CSV normalization in `cube/services/s05_sources.py`.

1. Define one explicit demo alias translation for `FAKE_REPLACE_ME` / `TEMP_REPLACE_ME` at a read boundary. Keep raw historical identity as provenance; use canonical identity consistently in matching.
2. Apply it to filter values and archive identity values in the relevant Stock/P&L reads; do not merely clear the user's filters until values appear.
3. Preserve all remaining exact keys, dates and cardinality checks. Do not add prefix heuristics for unrelated real identifiers.
4. Verify a current canonical identity finds its archived equivalent without matching another portfolio; missing identities still return no result.
5. Do not rewrite completed schema-v4 parquet files beneath existing manifests to solve a presentation alias mismatch.

### Step F6. Make P&L reconciliation complete and actionable

Files: `cube/pages/pnl/s06_validation.py`, `s08_aggregate.py`, `s10_summary.py`, `cube/history/s07_sql.py`.

1. Retain missing leaf Predict/Colossus values and attach coverage/status before hierarchy aggregation.
2. Compare matched Predict and Colossus totals over the same population; show unmatched amounts/counts separately. Partial Predict 10 versus complete Colossus 24 is not a complete residual.
3. Replace the per-branch ten-child cap with paging/load-more plus Underlying search. Sorting should surface missing and discrepant rows; do not sort solely by absolute Predict when it can be absent.
4. Add Difference and Status beside Predict/Colossus. Use explicit Missing Predict/Missing Colossus/Matched/Mismatch statuses.
5. Rename archive-derived Today using its actual date; display current base/effective-to-send separately.
6. Carry the clicked Today/MTD/YTD metric and period into history. Add daily/cumulative presentation without changing the underlying PL calculation.
7. Include historical-only filter options in history mode; do not silently discard a selected portfolio absent from the current snapshot.
8. Test missing one side, all missing, eleven+ children, old portfolios, month/year boundaries and the date/metric drill-through.

### Step F7. Keep refresh degradation and tenor reduction truthful

Files: `cube/domain/s03_calculations.py`, `cube/domain/s11_tenorreduction.py`, `cube/pages/risk/s02_state.py`.

1. Give empty and nonempty Open/Current frames the same canonical numeric dtypes before joining. Avoid assigning an object-typed empty Series into a float column. Keep `many_to_one` Risk→Market validation.
2. Test Open-only, Current-only, both empty, connector outage and last-good-state behavior. Missing market values remain unavailable, never zero.
3. When Clear Cache is an explicit request to retry a repaired reduction provider, clear/recreate the reducer's matrix/catalog/failure caches as well as derived frames.
4. Replace the reduction support count's eight-bit accumulator with a safe integer or boolean-support operation. Verify 255, 256 and 257 contributing tenors.
5. Do not assume a Risk transformation conserves monetary P&L. Keep authoritative full-tenor P&L totals or require an explicitly conservative PL allocation contract. Test total invariance for each portfolio and retained missing coverage.
6. Preserve pinned promotion reasons and threshold/reporting authority. Do not solve a display problem by weakening financial validation or inventing promotion scores.

### Step F8. Reduce unnecessary implementation layers after behavior is covered

1. Consolidate Data handoff/draft ownership rather than adding another state store to reconcile existing stores.
2. Consolidate SOG/Portfolio P&L editors around one draft/effective-result model rather than duplicating callbacks again.
3. Keep the current page-owned Stock pivot; remove the obsolete hierarchy/promotion route only after proving no live imports need it. Update or retire tests that exist solely for the removed route.
4. Load Stock's unaggregated detail only when requested; batch selected history identities in one bounded read when measurements justify it.
5. Keep the bounded archive reader/cache and immutable published snapshot. Measure larger supported selections before adding workers, queues, databases or a generic chart framework.

## Part G — what is currently implemented and how to use it

| Area | Current use | Important boundary |
|---|---|---|
| Startup/refresh | Start `app.py`; let the browser request the first refresh; inspect progress and last-good revision | App construction is lazy; runtime refresh is not an automatic daily archive |
| Main Risk | Apply the governed filters; expand a Risk row; click a metric cell for tenor detail; choose the available tenor view | Portfolio exists in data, but main Portfolio leaf support is a proposal below |
| Quick Risk | Search a reported risk identity; inspect its bounded pivot; send a history handoff to Data | It uses position scope; market footer/cap findings remain pending |
| Quick Market | Search raw quote identity and inspect tenors | Portfolio metadata does not belong in quote identity |
| Full/reduced tenors | Use the existing tenor-view controls/provider-backed reduction | Provider failure fallback exists; invalidation and conservation findings remain pending |
| Data | Choose Risk/Market identity and period, press Load, then inspect/play/compare archive dates | Existing state/quote issues are documented; preview layout is not installed |
| Stock | Use current comparison/pivot and open Position detail for existing fields; select a row for history | Current dates/identity names must match available archive; clicked scope finding remains pending |
| P&L | Review overview/history; Validate against Colossus; edit and save adjustments; configured send functions are the destination boundary | Demo sends deliberately reject delivery; arithmetic/save issues must be resolved before relying on a changed workflow |
| Statics Read | Choose a source table to inspect | Read display does not save data |
| Statics Write | Choose one of four writable static tables, edit, use existing validation/save controls | The picker now clears stale table view state; source validation remains |
| Cash Flow | Inspect the direct-PL New Trades overlay in Risk and its trade detail | This is an auxiliary classification, not a sixth native route; see NEWTESTS module map |
| Saved views | Save/reapply governed filter views through the existing saved-view controls | This is view configuration, not an archive of the financial data displayed at save time |
| Application Logs | Open the logs control for bounded recent process records | In-memory log display is not a durable financial audit history |
| Official history | Use the archive writer/job after dated source integration; query completed v4 leaves | Writer is idempotent per date; Stock needs the additional job composition shown above |
| Adjustments | Active values are stored under date/portfolio files and reloaded by editors | Older versions/actor/reason/send receipts need the explicit audit extension |

Detailed source ownership, protocol boundaries, product formulas, callback interaction and every source/test/config file are in **NEWTESTS.md**. The findings appendices preserve all earlier review items rather than silently dropping issues that were not the focus of today's question.

## Part H — validation, delivery and rollback

### Step H1. Reproduce the new tools

Create the Python files exactly as shown in the appendices. Run the chart generator, isolated synthetic-history generator, and actual history readers. Verify the schema-v4 completion markers/hashes and the printed counts. The synthetic history tools do not replace real dated connectors.

### Step H2. Validate the delivered tree

Before the broad run, update `tests/s35_pipelinearch.py::test_legacy_compatibility_boundaries_are_removed`. In its final expected `tools/*.py` filename set, add `"s04_chart_previews.py"`, `"s05_demo_history.py"`, and `"s06_read_demo_history.py"` immediately after `"s03_benchmark.py"`. Remove none of the existing names or legacy checks. The exact diff is in Appendix A. This test intentionally enumerates tools, so an optional tool addition requires updating that manifest.

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m ruff check .
& '.\.venv\Scripts\python.exe' -m ruff format --check tools/s04_chart_previews.py tools/s05_demo_history.py tools/s06_read_demo_history.py cube/pages/static_data/s03_callbacks.py tests/s42_statics.py tests/s35_pipelinearch.py cube/ui/s02_aggregation.py cube/pages/risk/s02_state.py cube/pages/risk/s06_explorertables.py cube/pages/risk/s07_explorer.py tests/s19_riskfilters.py
git diff --check
git status --short
```

Run the broad suite once after assembling the final files; do not infer success from a previous baseline run. The final validation record below gives the checks actually executed in this review. Production connector checks require the real integration environment and were not run here.

### Step H3. Review changes before promotion

The runtime patch contains the Statics callback plus the four Risk cache/aggregation modules from Step B4. Tests are the Statics regression, Risk cache regressions and the three new tool names in the existing manifest. New tools/manuals/previews are separate additions. Portfolio, page redesign, Stock metadata, adjustment audit storage and real scheduled capture must not appear as installed features until their proposed changes are implemented and tested.

Generated Plotly HTML embeds a sizeable JavaScript library. It is a review output, not an asset to load on every application page. Keep it out of the production bundle if the bundle does not need design documentation; the Python generator can recreate it.

### Step H4. Rollback

Reverse the isolated Statics or cache hunks independently if needed; Step B5 identifies the cache rollback scope. The optional tools and generated previews have no app imports; excluding them from a deployment changes no runtime behavior. Keep generated demo archives outside production archive roots. Do not delete or modify a real completed leaf as a rollback shortcut. If you later apply a proposed financial change, retain the prior version and validate restored totals/coverage before returning to service.

## Session work ledger

1. Reconfirmed GitHub main and preserved the existing local Statics change.
2. Re-read live definitions rather than using old guide paths as authority.
3. Traced Portfolio from its position contract into prepared data, row keys, hierarchy and callbacks; reproduced incomplete-edit failures and tested the smaller proposal.
4. Inspected existing tenor renderers and produced concrete replacements using the checked-in synthetic archive.
5. Verified preview Risk decomposition and surface totals; exercised chart selection in the browser.
6. Traced daily Risk/Market/Colossus/Stock production and readers; identified the missing Stock attachment in standard scheduled capture.
7. Generated and hash-validated three isolated synthetic daily leaves; exercised real Data, P&L and Stock readers and idempotent recapture.
8. Distinguished current adjustment values, immutable audit versions, sent payload receipts and runtime logs.
9. Traced existing Stock fields and documented Quantity/dQuantity plus optional metadata enrichment without changing position identity.
10. Produced the complete architecture/test inventory and this manual, including exact applied diff, full helper source, proposals and all previous review findings.
11. Recorded final checks below. These review checks preceded GitHub documentation publication; no financial sends occurred.
12. After the user clarified production size and questioned cache design, traced the original per-render index and component cache, then implemented bounded index reuse and Explorer component non-retention locally.
13. Added financial, registered callback, eviction and concurrency regressions; compared exact visible output with a synthetic 100k-position/400-portfolio fixture; updated both manuals with the final applied state.

## Final executed verification — Risk cache patch, 6 September 2026

- **Full current-tree pytest: 686 passed, 56 warnings, 116.04 seconds.** Workspace log: `final-cache-tests-sep06.log`. This supersedes the earlier 672-test delivery as the current full-suite result. The warnings remain Dash DataTable deprecations.
- **Whole-repository Ruff checks passed; formatting checks passed for all 11 changed/added Python files.** The applied patch now covers eight tracked application/test files: five application files, two regression modules and the tool manifest. The three optional Python tools remain separate additions.
- **Risk regressions:** the focused s19 run passed 55 collected cases. Its 12 new test functions cover registered callback reuse across expansion/metric changes, exact scope/Credit isolation, unchanged source data and independent quotes, entry/byte budgets, concurrent construction, invalidation and stale publication. The complete suite includes these regressions.
- **Controlled scale comparison:** synthetic 100,000 raw positions across 400 portfolios share 250 quote identities. Four small visible views contained 3, 4, 9 and 4 rendered rows, including headers/totals. The fresh-index and reused-index outputs were byte-for-byte equal after consistent JSON serialization. Risk was 400,000, P&L was 40 within floating-point tolerance, and the shared quote move remained 0.0001.
- **Measured retention:** one index, 51,981,132 bytes of conservatively accounted retained data, and zero retained Explorer component trees. This is not process RSS or a limit on transient allocations. The separate prepared frame measured 39,957,132 bytes and shares some underlying storage with the index.
- **Measured server timings:** first build 134.1 ms with a fresh standalone index versus 131.2 ms through the new cache path; subsequent scopes were 137.2/20.7 ms, 181.8/64.4 ms and 138.8/20.7 ms for fresh/reused paths. These are illustrative measurements from `cache-scale-probe.py`, not a production speed guarantee. No browser timing, memory profile or fully expanded book was measured. The fixture represents 100k raw positions, not 100k aggregate rows multiplied by every book.
- **Remaining limits:** every request still constructs/serializes visible HTML; an exact repeated view can cost more than an old complete-table cache hit. SplitVA/Credit Multi keep their existing reductions. The Aggregate P&L/Top Promotions component cache remains separate at 24 entries, now protected from publication after a concurrent clear/refresh. No global row budget or Portfolio integration was added.

The chart, Statics browser and history results below remain the earlier executed checks; cache changes did not modify those paths. The nine older isolated benchmark budgets were not rerun as part of this targeted cache comparison. No production source, scheduler, downstream sender or deployment was exercised.

## Earlier executed verification — Statics/tools delivery, 6 September 2026

- **Full delivered-tree pytest suite: 672 passed, 56 warnings, 114.75 seconds.** Log: workspace `final-tests-sep06.log`. Warnings are Dash DataTable deprecations. The first assembled run found the exact tool-filename manifest did not include the three new tools; its list was updated without removing any legacy checks, then the entire suite was rerun successfully.
- **`ruff check .`: passed.** **Ruff format check for all six changed/new Python files: passed.** **`git diff --check`: passed.** No application/test file other than the three shown in Appendix A was modified; the optional tools and documentation are additions.
- **Statics:** 13 focused tests passed in the earlier narrow run; the final full suite includes them. The failing old-filter/file-switch browser sequence and all four writable dataframe choices were verified after the fix.
- **Portfolio proposal:** exact two-file patch passed `git apply --check` and remained unapplied. Real registered main/detail callbacks and all 17 synthetic source families rendered with the temporary proposal, including reported/raw, Credit Multi and Split VA paths. Risk/P&L totals and unique quote values were preserved in the two-book fixture. Capacity measurements in Part C are server build/component-size observations, not production or browser guarantees.
- **Charts:** the offline Plotly gallery rendered all four figures; the expiry selector updated the profile. The inline proposal was inspected in light/dark at 736px and 360px; series toggling and expiry selection changed the displayed result. The actual application charts were not replaced. Risk decomposition and surface totals were asserted; duplicated position rows were checked not to change quotes. Sparse JSON values remain null. Caption/source data distinguish the 21 August market cut from DeltaVega's 19 August Risk source date.
- **Synthetic history:** three isolated dates produced 30,000 Risk rows and 15,000 rows each for Market, Colossus and Stock. Complete schema-v4 manifests and SHA-256 hashes passed. Existing-date reruns retained all hashes. The portable tools also generated a fresh two-day archive and rejected bad ranges/repository output/untagged data before writing. Actual P&L, Data and Stock readers queried the isolated history successfully; the final root read returned six P&L observations and three dates each for scalar Risk, Market and one exact Stock identity.
- **Documentation:** source inventory/fence/link checks were performed; current implementation, tested proposals and future integration remain labelled separately. Exact applied patch and complete new-tool source are embedded below.

The nine benchmark budgets passed in the earlier isolated baseline review. They were not rerun for this documentation/optional-tool turn; do not interpret that older result as a new production load test. No private production feed, actual P&L sender, scheduler or deployment was exercised.


## Appendix A — complete applied application/test patch

This is the exact `git diff` for all eight modified application/test files: Statics, four Risk cache/aggregation modules, the two regression modules, and the tool-file manifest. Apply this patch OR follow Steps B1–B4 and H2 manually, not both.

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
diff --git a/cube/pages/static_data/s03_callbacks.py b/cube/pages/static_data/s03_callbacks.py
index de04418..00ddad9 100644
--- a/cube/pages/static_data/s03_callbacks.py
+++ b/cube/pages/static_data/s03_callbacks.py
@@ -41,6 +41,20 @@ def register_callbacks(app: Any, *, store: StaticDataStore | None = None) -> Non
             return html.Div("No file selected.", className="static-data-empty")
         return build_static_data_table(selected_file, store=static_store)
 
+    @app.callback(
+        Output("static-data-write-table", "filter_query"),
+        Output("static-data-write-table", "sort_by"),
+        Output("static-data-write-table", "page_current"),
+        Output("static-data-write-table", "hidden_columns"),
+        Output("static-data-write-table", "active_cell"),
+        Output("static-data-write-table", "selected_cells"),
+        Input("static-data-write-selector", "value"),
+    )
+    def reset_static_table_view(_selected_file):
+        # DataTable retains view state when its data and schema are replaced.
+        # A filter on a column from the previous file can hide every new row.
+        return "", [], 0, [], None, []
+
     @app.callback(
         Output("static-data-write-table", "columns"),
         Output("static-data-write-table", "data"),
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
diff --git a/tests/s35_pipelinearch.py b/tests/s35_pipelinearch.py
index 604e548..807e2f3 100644
--- a/tests/s35_pipelinearch.py
+++ b/tests/s35_pipelinearch.py
@@ -55,4 +55,7 @@ def test_legacy_compatibility_boundaries_are_removed() -> None:
         "s01_fixtures.py",
         "s02_archive.py",
         "s03_benchmark.py",
+        "s04_chart_previews.py",
+        "s05_demo_history.py",
+        "s06_read_demo_history.py",
     }
diff --git a/tests/s42_statics.py b/tests/s42_statics.py
index 701b976..ea5d969 100644
--- a/tests/s42_statics.py
+++ b/tests/s42_statics.py
@@ -140,6 +140,43 @@ def test_statics_empty_editor_mounts_without_fixed_header_crash() -> None:
     assert "fixed_rows" not in _table_style()
 
 
+@pytest.mark.parametrize("selected_file", WRITABLE_STATIC_FILES)
+def test_statics_file_switch_replaces_schema_and_clears_previous_view(
+    selected_file: str,
+    tmp_path: Path,
+    monkeypatch: pytest.MonkeyPatch,
+) -> None:
+    store = _store(tmp_path)
+    app = Dash(__name__, suppress_callback_exceptions=True)
+    app.layout = build_static_data_page()
+    register_callbacks(app, store=store)
+    edit = _callback_for_output(app, "static-data-write-table", "data")
+    reset = _callback_for_output(app, "static-data-write-table", "filter_query")
+    previous = store.read("s06_portfolios.csv")
+    monkeypatch.setattr(
+        static_callbacks,
+        "ctx",
+        SimpleNamespace(triggered_id="static-data-write-selector"),
+    )
+
+    columns, rows, status, revision = edit(
+        selected_file,
+        0,
+        0,
+        0,
+        _editable_columns(list(previous.columns)),
+        previous.to_dict("records"),
+        0,
+    )
+
+    expected = store.read(selected_file)
+    assert columns == _editable_columns(list(expected.columns))
+    assert rows == expected.to_dict("records")
+    assert status.startswith("Editing ")
+    assert revision is no_update
+    assert reset(selected_file) == ("", [], 0, [], None, [])
+
+
 def test_static_store_writes_validated_csv_atomically(tmp_path: Path) -> None:
     store = _store(tmp_path)
     frame = store.read("s09_reported.csv")
```


## Appendix B — complete new chart generator source

Create `tools/s04_chart_previews.py` with this entire block; there are no omitted helper definitions.

```python
"""Build standalone tenor-design previews from the shipped synthetic archive.

Run from the repository root:
    python -m tools.s04_chart_previews --output docs/chart-previews

This optional tool reads archive files and writes only the selected output
directory. It is not imported by the Dash app and changes no financial data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from cube.history import load_risk_archive
from cube.ui.s02_aggregation import detail_frame, prepare_risk_data, tenor_axis_order


ROOT = Path(__file__).resolve().parents[1]
BLUE = "#2976B8"
ORANGE = "#C37726"
INK = "#263948"
GRID = "#DDE3E8"
WHITE = "#FFFFFF"
DIVERGING = [[0, BLUE], [0.5, "#F4F5F6"], [1, ORANGE]]


def _json_number(value: float, digits: int = 5) -> float | None:
    return round(float(value), digits) if np.isfinite(value) else None


def _style(figure: go.Figure, *, title: str, height: int) -> go.Figure:
    figure.update_layout(
        title={"text": title, "font": {"size": 18}, "x": 0.025},
        template="plotly_white",
        font={"family": "Arial, sans-serif", "size": 13, "color": INK},
        paper_bgcolor=WHITE,
        plot_bgcolor=WHITE,
        height=height,
        margin={"l": 76, "r": 38, "t": 94, "b": 62},
        legend={"orientation": "h", "y": 1.1, "x": 0},
        hoverlabel={"font": {"size": 13}, "namelength": -1},
        hovermode="x unified",
        bargap=0.24,
    )
    figure.update_xaxes(
        showgrid=False, linecolor=GRID, ticks="outside", automargin=True
    )
    figure.update_yaxes(gridcolor=GRID, zerolinecolor=INK, automargin=True)
    return figure


def _ordered_curve(detail: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    order, ambiguous = tenor_axis_order(detail, "tenor swap", "tenor swap order")
    if ambiguous:
        raise ValueError("Preview requires one authoritative tenor order")
    return (
        detail.groupby("tenor swap")[metrics]
        .sum(min_count=1)
        .reindex(order)
        .reset_index()
    )


def risk_curve(curve: pd.DataFrame) -> go.Figure:
    """Use one numeric scale for exposures, hedges and the net position."""
    figure = go.Figure()
    for metric, label, color in (
        ("risk expo", "Exposure", BLUE),
        ("risk hedges", "Hedges", ORANGE),
    ):
        figure.add_bar(
            x=curve["tenor swap"],
            y=curve[metric] / 1_000_000,
            name=label,
            marker_color=color,
            hovertemplate="%{x}: %{y:+.3f}m<extra>" + label + "</extra>",
        )
    figure.add_scatter(
        x=curve["tenor swap"],
        y=curve["risk"] / 1_000_000,
        name="Net",
        mode="markers",
        marker={"color": INK, "size": 10, "symbol": "diamond"},
        hovertemplate="%{x}: %{y:+.3f}m<extra>Net</extra>",
    )
    figure.update_layout(barmode="group")
    figure.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=curve["tenor swap"],
        title="Swap tenor",
    )
    figure.update_yaxes(
        title="Risk · millions of source units", tickformat="+.1f", rangemode="tozero"
    )
    return _style(figure, title="Exposure, hedges & net", height=430)


def market_curve(detail: pd.DataFrame) -> go.Figure:
    """Keep rate levels and their move in aligned, separate panels.

    The selected demo IR source stores decimal rates. The transformations below
    are display-only: decimal * 100 = percent; decimal change * 10,000 = bp.
    They must not be applied to every ProductSpec without checking its units.
    """
    order, ambiguous = tenor_axis_order(detail, "tenor swap", "tenor swap order")
    if ambiguous or detail["underlying"].nunique() != 1:
        raise ValueError("Select one exact underlying with authoritative tenor order")
    quotes = detail.set_index("tenor swap")[["open", "current", "move"]].reindex(order)
    if not quotes.index.is_unique:
        raise ValueError("Market preview expects one quote per tenor")
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        row_heights=[0.65, 0.35],
    )
    for metric, label, color, dash in (
        ("open", "Open", ORANGE, "dash"),
        ("current", "Current", BLUE, "solid"),
    ):
        figure.add_scatter(
            x=order,
            y=quotes[metric] * 100,
            name=label,
            mode="lines+markers",
            line={"color": color, "width": 2.5, "dash": dash},
            marker={"size": 6},
            hovertemplate="%{x}: %{y:.3f}%<extra>" + label + "</extra>",
            row=1,
            col=1,
        )
    figure.add_bar(
        x=order,
        y=quotes["move"] * 10_000,
        name="Move",
        showlegend=False,
        marker_color=[BLUE if value >= 0 else ORANGE for value in quotes["move"]],
        hovertemplate="%{x}: %{y:+.2f} bp<extra>Move</extra>",
        row=2,
        col=1,
    )
    figure.update_xaxes(type="category", categoryorder="array", categoryarray=order)
    figure.update_xaxes(title="Swap tenor", row=2, col=1)
    figure.update_yaxes(title="Rate (%)", row=1, col=1)
    figure.update_yaxes(title="Move (bp)", rangemode="tozero", row=2, col=1)
    return _style(figure, title="Rates and daily move", height=510)


def risk_surface(detail: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """Show signed tenor risk on a symmetric scale; preserve missing cells."""
    swaps, swap_ambiguous = tenor_axis_order(detail, "tenor swap", "tenor swap order")
    options, option_ambiguous = tenor_axis_order(
        detail, "tenor option", "tenor option order"
    )
    if swap_ambiguous or option_ambiguous:
        raise ValueError("Preview requires authoritative axis orders")
    matrix = (
        detail.groupby(["tenor option", "tenor swap"])["risk"]
        .sum(min_count=1)
        .unstack("tenor swap")
        .reindex(index=options, columns=swaps)
        / 1_000_000
    )
    finite = matrix.to_numpy()[np.isfinite(matrix.to_numpy())]
    limit = float(np.abs(finite).max()) if finite.size else 1.0
    limit = limit or 1.0
    figure = go.Figure(
        go.Heatmap(
            x=swaps,
            y=options,
            z=matrix.to_numpy(),
            zmin=-limit,
            zmax=limit,
            zmid=0,
            colorscale=DIVERGING,
            xgap=2,
            ygap=2,
            hoverongaps=False,
            texttemplate="%{z:.2f}",
            textfont={"size": 12},
            colorbar={"title": "Risk (m)", "thickness": 12, "len": 0.85},
            hovertemplate="Expiry %{y} · Swap %{x}<br>Risk %{z:+.3f}m<extra></extra>",
        )
    )
    figure.update_xaxes(
        title="Swap tenor", type="category", categoryorder="array", categoryarray=swaps
    )
    figure.update_yaxes(
        title="Option tenor",
        type="category",
        categoryorder="array",
        categoryarray=options,
        autorange="reversed",
    )
    _style(figure, title="Risk by option and swap tenor", height=430)
    figure.update_layout(
        hovermode="closest", margin={"l": 76, "r": 75, "t": 68, "b": 62}
    )
    return figure, matrix


def surface_slice(matrix: pd.DataFrame, option: str) -> go.Figure:
    values = matrix.loc[option]
    figure = go.Figure(
        go.Bar(
            x=matrix.columns,
            y=values,
            marker_color=[BLUE if value >= 0 else ORANGE for value in values],
            hovertemplate="%{x}: %{y:+.3f}m<extra>Selected expiry</extra>",
        )
    )
    figure.update_xaxes(
        title="Swap tenor",
        type="category",
        categoryorder="array",
        categoryarray=list(matrix.columns),
    )
    figure.update_yaxes(title="Risk · millions of source units", rangemode="tozero")
    return _style(figure, title=f"Selected expiry · {option}", height=310)


def build_previews(archive: Path, selected_date: str, output: Path) -> dict:
    archive, output = archive.resolve(), output.resolve()
    if output == archive or output.is_relative_to(archive):
        raise ValueError("Preview output must be outside the input archive")
    loaded = load_risk_archive(archive, selected_date)
    marker = json.loads((loaded.path / "_SUCCESS").read_text(encoding="utf-8"))
    if (
        loaded.schema_version != 4
        or marker.get("fixture") != "deterministic-rebirth-v4"
    ):
        raise ValueError(
            "Preview tool accepts only completed synthetic schema-v4 fixtures"
        )
    selected_date = loaded.market_date
    source_path = loaded.path / "risk.parquet"
    raw = loaded.risk
    prepared = prepare_risk_data(raw)
    curve_scope = {
        "source type": "ir/delta",
        "underlying": "FAKE_REPLACE_ME - USD SOFR",
    }
    surface_scope = {
        "source type": "ir/deltavega",
        "underlying": "FAKE_REPLACE_ME - USD SOFR Vol",
    }

    def exact_scope(identity: dict[str, str]) -> pd.DataFrame:
        mask = pd.Series(True, index=prepared.index)
        for column, value in identity.items():
            mask &= prepared[column].eq(value)
        return prepared.loc[mask]

    curve_detail = detail_frame(exact_scope(curve_scope), {}, "risk")
    market_detail = detail_frame(exact_scope(curve_scope), {}, "move")
    surface_detail = detail_frame(exact_scope(surface_scope), {}, "risk")
    if curve_detail.empty or market_detail.empty or surface_detail.empty:
        raise ValueError(
            "Selected archive lacks the exact synthetic preview identities"
        )
    curve = _ordered_curve(curve_detail, ["risk", "risk expo", "risk hedges"])
    np.testing.assert_allclose(curve["risk"], curve["risk expo"] + curve["risk hedges"])
    figures = [risk_curve(curve), market_curve(market_detail)]
    heatmap, matrix = risk_surface(surface_detail)
    figures += [heatmap, surface_slice(matrix, str(matrix.index[0]))]
    np.testing.assert_allclose(
        matrix.sum().sum() * 1_000_000, surface_detail["risk"].sum()
    )
    output.mkdir(parents=True, exist_ok=True)
    fragments = [
        figure.to_html(
            full_html=False,
            include_plotlyjs=True if index == 0 else False,
            div_id=f"design-{index}",
            config={"responsive": True, "displaylogo": False},
        )
        for index, figure in enumerate(figures)
    ]
    select_options = "".join(
        f'<option value="{option}">{option}</option>' for option in matrix.index
    )
    slice_values = {
        str(option): [_json_number(value) for value in matrix.loc[option]]
        for option in matrix.index
    }
    surface_json = json.dumps(slice_values, allow_nan=False)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rebirth tenor chart proposals</title><style>
body{{margin:0;background:#f3f5f7;color:#263948;font:15px/1.5 Arial,sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:24px 16px}}h1{{font-size:25px;margin:0 0 6px}}
.caption{{margin:0 0 20px;color:#4b5d6b}}section{{background:#fff;margin:0 0 22px;padding:8px 6px}}
label{{display:block;padding:12px 18px}}select{{font:inherit;padding:7px 16px}}
.note{{padding:0 20px 14px;margin:0}}.plotly-graph-div{{width:100%}}
</style></head><body><main>
<h1>Rebirth · tenor chart proposals</h1><p class="caption">Synthetic market cut · {selected_date} · USD SOFR / USD SOFR Vol · Full tenors · Proposals, not the live app<br>Risk dates: Delta {loaded.risk_dates["ir/delta"]} · DeltaVega {loaded.risk_dates["ir/deltavega"]}</p>
<section>{fragments[0]}<p class="note">All three series use the same scale. Diamonds show net risk without covering the exposure and hedge bars.</p></section>
<section>{fragments[1]}<p class="note">Levels and changes have their own units and aligned tenor axes. Rate conversion is specific to this decimal-rate demo source.</p></section>
<section>{fragments[2]}<label>Inspect expiry <select id="expiry">{select_options}</select></label>{fragments[3]}<p class="note">Click a heatmap cell or choose an expiry. Missing cells remain unavailable; zero stays neutral.</p></section>
</main><script>
const rows={surface_json};
function chooseExpiry(value){{
document.getElementById('expiry').value=value;
Plotly.restyle('design-3',{{y:[rows[value]],'marker.color':[rows[value].map(v=>v>=0?'{BLUE}':'{ORANGE}')]}});
Plotly.relayout('design-3',{{'title.text':'Selected expiry · '+value}});
}}
document.getElementById('expiry').addEventListener('change',event=>chooseExpiry(event.target.value));
document.getElementById('design-2').on('plotly_click',event=>chooseExpiry(String(event.points[0].y)));
</script></body></html>"""
    (output / "index.html").write_text(document, encoding="utf-8")
    curve_rows = [
        {
            "tenor": row["tenor swap"],
            "net": _json_number(row["risk"] / 1_000_000),
            "exposure": _json_number(row["risk expo"] / 1_000_000),
            "hedges": _json_number(row["risk hedges"] / 1_000_000),
        }
        for row in curve.to_dict("records")
    ]
    payload = {
        "source": str(source_path.relative_to(ROOT))
        if source_path.is_relative_to(ROOT)
        else str(source_path),
        "synthetic": True,
        "date": selected_date,
        "risk_dates": {
            source: loaded.risk_dates[source] for source in ("ir/delta", "ir/deltavega")
        },
        "curve": curve_rows,
        "surface": {
            "swaps": list(matrix.columns),
            "options": list(matrix.index),
            "values": [
                [_json_number(value) for value in row] for row in matrix.to_numpy()
            ],
        },
    }
    (output / "data.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "data/histo")
    parser.add_argument("--date", default="2026-08-21")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/chart-previews")
    args = parser.parse_args()
    result = build_previews(args.archive.resolve(), args.date, args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve() / "index.html"),
                "curve_tenors": len(result["curve"]),
                "surface_shape": [
                    len(result["surface"]["options"]),
                    len(result["surface"]["swaps"]),
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
```


## Appendix C — complete new isolated demo-history generator source

Create `tools/s05_demo_history.py` with this entire block.

```python
"""Generate SYNTHETIC schema-v4 history in a required directory outside this repo.

Run from the repository root:
    python -m tools.s05_demo_history --start 2026-08-19 --end 2026-08-21 \
        --output ../demo-history

This optional tool uses deterministic fixtures and the existing immutable archive
writer. It never calls live connectors or sends P&L. Existing completed synthetic
days are validated and retained. Real, incomplete, or unrelated output contents
are rejected before any archive is written.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from cube.history import (
    CompletedArchiveDay,
    archive_official_snapshot,
    list_completed_v4_archive_days,
    open_history_database,
)
from tools.s01_fixtures import (
    FIXTURE_TAG,
    HISTORICAL_MARKET_DATES,
    build_official_history_fixture,
)


ROOT = Path(__file__).resolve().parents[1]


def fixture_dates(start: str, end: str) -> tuple[str, ...]:
    """Validate the entire requested range before generating its first day."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.isoformat() != start or last.isoformat() != end:
        raise ValueError("Use ISO dates in YYYY-MM-DD format.")
    if first > last:
        raise ValueError("--start must be on or before --end.")
    if start < HISTORICAL_MARKET_DATES[0] or end > HISTORICAL_MARKET_DATES[-1]:
        raise ValueError(
            "The entire range must stay within the SYNTHETIC fixture range "
            f"{HISTORICAL_MARKET_DATES[0]} to {HISTORICAL_MARKET_DATES[-1]}."
        )
    days = tuple(day for day in HISTORICAL_MARKET_DATES if start <= day <= end)
    if not days:
        raise ValueError("The range must contain at least one fixture business day.")
    return days


def validate_synthetic_root(root: Path) -> tuple[CompletedArchiveDay, ...]:
    """Read-only preflight: accept an empty root or only complete tagged fixtures.

    The shared archive validator checks _SUCCESS, all payload hashes, ordered
    schemas and row counts. Checking every entry first also rejects incomplete
    leaves that the general history reader intentionally hides.
    """
    if not root.exists():
        return ()
    if not root.is_dir():
        raise ValueError(f"Archive root must be a directory: {root}")
    entries = tuple(root.iterdir())
    for leaf in entries:
        if (
            not leaf.is_dir()
            or leaf.resolve() != leaf
            or leaf.name not in HISTORICAL_MARKET_DATES
            or not (leaf / "_SUCCESS").is_file()
        ):
            raise ValueError(f"Refusing unrelated or incomplete archive entry: {leaf}")
        marker = json.loads((leaf / "_SUCCESS").read_text(encoding="utf-8"))
        if not isinstance(marker, dict) or marker.get("fixture") != FIXTURE_TAG:
            raise ValueError(
                f"Refusing to mix SYNTHETIC data with untagged data: {leaf}"
            )
    days = list_completed_v4_archive_days(root)
    if len(days) != len(entries):
        raise ValueError("Every existing output entry must be a completed v4 fixture.")
    return days


def generate_history(start: str, end: str, output: Path) -> None:
    days = fixture_dates(start, end)
    root = output.expanduser().resolve()
    if root == ROOT or ROOT in root.parents:
        raise ValueError("Use an isolated --output directory outside the repository.")
    validate_synthetic_root(root)
    print(f"SYNTHETIC fixture history only; output: {root}", flush=True)
    for day in days:
        selected = pd.Timestamp(day)
        fixture = build_official_history_fixture(day)
        snapshot = SimpleNamespace(
            revision=fixture.revision,
            refreshed_at=datetime(
                selected.year, selected.month, selected.day, 17, 30, tzinfo=timezone.utc
            ),
            system_date=selected,
            market_date=selected,
            market_status="OFFICIAL",
            risk_dates=fixture.risk_dates,
            dashboard_frame=fixture.risk,
            market_frame=fixture.market,
            stock_frame=fixture.stock,
            stock_date=selected,
            errors=(),
            fixture=FIXTURE_TAG,
        )
        result = archive_official_snapshot(
            snapshot, lambda _date: fixture.colossus, root
        )
        if result.status not in {"archived", "already_archived"}:
            raise RuntimeError(f"Unexpected archive result: {result}")
        print(
            day,
            result.status,
            "risk",
            result.risk_rows,
            "market",
            result.market_rows,
            "colossus",
            result.colossus_rows,
            "stock",
            result.stock_rows,
            flush=True,
        )

    completed = validate_synthetic_root(root)
    print(
        "Validated SYNTHETIC schema-v4 days, payload hashes and schemas:",
        len(completed),
    )
    connection = open_history_database(root)
    try:
        for view in (
            "risk_history",
            "market_history",
            "colossus_history",
            "stock_history",
        ):
            print(
                view, connection.execute(f'SELECT count(*) FROM "{view}"').fetchone()[0]
            )
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start", required=True, help="First date, YYYY-MM-DD (inclusive)."
    )
    parser.add_argument(
        "--end", required=True, help="Last date, YYYY-MM-DD (inclusive)."
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Isolated path outside repo."
    )
    args = parser.parse_args()
    try:
        generate_history(args.start, args.end, args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
```


## Appendix D — complete new reader demonstration source

Create `tools/s06_read_demo_history.py` with this entire block.

```python
"""Read SYNTHETIC history through the real Data, P&L and Stock repositories.

Run from the repository root:
    python -m tools.s06_read_demo_history --archive ../demo-history

Dates come from the available completed archive days. This read-only example
rejects untagged/real archives so its output cannot be mistaken for live results.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cube.history import (
    ArchiveHistoryRepository,
    HistoryQuery,
    SQLPLHistoryRepository,
)
from cube.pages.stock.s02_history import (
    SQLStockHistoryRepository,
    stock_history_identity_from_token,
)
from tools.s05_demo_history import validate_synthetic_root


def read_history(archive: Path) -> None:
    root = archive.expanduser().resolve()
    days = validate_synthetic_root(root)
    if not days:
        raise ValueError(f"No completed SYNTHETIC archive days in {root}")
    dates = sorted(day.snapshot_date for day in days)
    start, end = dates[0], dates[-1]
    print(f"SYNTHETIC results only; {start} to {end}; {len(days)} completed days")
    print(f"Archive: {root}")
    pl = SQLPLHistoryRepository(root)
    stock = SQLStockHistoryRepository(root)
    try:
        print("P&L history:")
        print(pl.series(preset="all").series.to_string(index=False))

        data = ArchiveHistoryRepository(root)
        catalog = data.catalog()
        for kind in ("risk", "market"):
            entry = next(
                (
                    item
                    for item in catalog.entries
                    if item.kind == kind and not item.identity.axes
                ),
                None,
            )
            if entry is None:
                print(kind, "has no scalar identity in this archive")
                continue
            result = data.read(HistoryQuery(handoff=entry.to_handoff(), period="all"))
            print(
                kind,
                "dates",
                len(result.dates),
                "canonical values",
                len(result.values),
                "source rows",
                len(result.raw_rows),
            )

        catalog = stock.catalog(limit=1)
        if not catalog.options:
            print("No Stock identity is available.")
        else:
            identity = stock_history_identity_from_token(catalog.options[0]["value"])
            rows = stock.rows(identity, start, end)
            print("Stock history (one exact identity):")
            print(
                rows[["Stock Date", "Quantity", "Market Value"]].to_string(index=False)
            )
    finally:
        pl.clear()
        stock.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args()
    try:
        read_history(args.archive)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
```


## Appendix E — full original repository review, retained with its original date

The following is the complete 4 September review. Its “source unchanged/clean tree” statements describe that earlier review, before the Statics patch and today's optional artifacts. Its findings remain proposals unless marked implemented in this manual's opening ledger.

Rebirth V5 review — 4 September 2026

Reviewed `streamlitdash/Rebirth-V5`, default branch `main`, commit `8f65a1124e54702597347967c7064eb4f7edf133`. This is a diagnosis and design review; application source was not changed. The local runtime uses the repository's synthetic connectors and archive. Findings do not establish the behavior of private production integrations.

The priority is to make displayed values trustworthy, then unify the small number of chart and cache contracts that currently disagree. Keep the financial validators, authoritative tenor order, separate quote/position grain, bounded history payloads, atomic refresh, and last-good snapshot. These solve real problems.

**Verification**

- Installed the repository's exact direct dependency pins in a separate local environment, including pandas 3.0.3, NumPy 2.5.1, Dash 4.4.0 and Plotly 6.9.0.
- Full pytest suite: **668 passed, 52 warnings, 120.26 seconds**. Warnings concern Dash DataTable deprecation.
- `ruff check .`: passed.
- Local browser: loaded the Risk page, opened Ford CDS tenor detail, changed Risk to Move, and verified the Move detail contains no graph and a visibly empty chart card.
- Targeted Python and JavaScript reproductions confirm the edge cases below; these are outside the checked-in test suite.
- All nine enforced benchmark checks passed on an isolated rerun. The first run overlapped testing and exceeded the Risk history budget; that is not sufficient evidence of an application regression. On the isolated rerun: app import/build 1.25 seconds, spot refresh 1.46 seconds, Risk history 1.27 seconds, P&L overview 1.49 seconds. Results are local measurements, not production guarantees.
- Git working tree remained clean.

**Fixes, in suggested order**

1. **Normalize empty market-leg dtypes before merging. Confirmed bug.**

   A nonempty floating-point Open leg plus an ordinary empty Current DataFrame raises `TypeError: Invalid value '[]' for dtype 'float64'`. Either missing leg reproduces the error for FX Delta, IR Delta and IR DeltaVega. Both legs empty succeeds.

   The market validators return early before quote/order normalization on empty inputs. The merge then attempts an assignment between object and float columns, including an empty mask. The refresh manager itself constructs this empty schema when an external market call fails, so the issue affects the intended degradation path.

   Fix: canonical dtypes for empty and nonempty inputs; skip assignments with no matching rows. Add a manager-level regression for one quote leg succeeding while the other has an operational outage. Keep strict schema/cardinality validation.

   Evidence: [empty Open validation](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s03_calculations.py#L622), [empty Current validation](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s03_calculations.py#L667), [assignments](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s03_calculations.py#L727), [manager fallback shape](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/services/s06_refresh.py#L1205).

2. **Separate additive risk/P&L from market quotes in display aggregation. Confirmed arithmetic.**

   Quick Risk's footer sums Open, Current and Move using the same loop as Risk/P&L. Two quote levels 3 and 4 become a Total quote of 7. Two missing quotes become a Total of 0. This overrides the backend's deliberate treatment of quote totals.

   Data's Market History also offers Sum across a surface's fixed tenor axis. Quotes 20 and 30 become 50. If the second quote is missing on the next date, the plot becomes 20: a coverage change looks like a market fall of 30. The Sum feature is documented behavior, but its financial definition should be revised for markets.

   Fix: sum additive measures; leave quote totals blank where no meaningful aggregation exists. Market History should default to an exact fixed tenor. Any basket/mean must have an explicit definition, stable constituents and coverage. Risk can keep its additive Sum view. Produce chart aggregates before paginating detail rows: Quick Risk currently builds its chart/footer from capped leaves even though its ancestor totals describe the full selection.

   Evidence: [Quick Risk totals](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/risk/s08_quickrisk.py#L475), [history summation](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/assets/s09_playback.js#L372), [backend full totals and leaf cap](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s10_search.py#L1323).

3. **Return the market line charts. Confirmed bug, also observed in the browser.**

   `build_line_chart()` returns a Graph only from its nonmarket branch. Open, Current and Move construct a figure but return `None`. The UI still renders their empty chart card.

   Fix: move the common Graph return outside the branch, and cover all metric branches with meaningful component checks plus one browser journey.

   Evidence: [market branch](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/risk/s05_charts.py#L299), [misplaced return](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/risk/s05_charts.py#L482).

4. **Make Clear Cache recover failed reduced-tenor lookups. Confirmed bug.**

   The reducer remembers matrices, catalogue entries and failures for its lifetime. Clear Cache removes derived frames but retains the reducer. A repaired provider is therefore not retried. A targeted reproduction returned six full-tenor rows after failure, still six after provider repair and cache clear, and the expected four reduced rows only after constructing a fresh reducer.

   Fix: invalidate/recreate the reducer on explicit reset or a governed matrix revision. Preserve its full-tenor fallback and avoid retrying an unavailable provider on every render.

   Evidence: [cache clear](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/risk/s02_state.py#L701), [persistent reducer caches](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s11_tenorreduction.py#L375).

5. **Keep authoritative P&L invariant when changing tenor presentation. Confirmed provider-contract issue.**

   The reducer applies the same arbitrary finite matrix to risk and monetary P&L. A valid risk transformation need not conserve a monetary total. Using the repository's own test matrix, portfolio P1 changes from PL 600 to 700; P2 changes from 150 to 175. Current shipped placeholder matrices are conservative; the accepted provider contract permits this failure.

   Fix: separate risk transformation from conservative P&L allocation, or keep full-book P&L totals authoritative and explicitly describe any projected quantity. A display toggle should not silently redefine actual P&L. Add conservation checks for monetary allocations.

   A separate, smaller reducer bug uses an eight-bit support counter. Exactly 256 contributing tenors wrap to zero and produce missing Risk/dRisk/PL; 255 and 257 work. Use a safe accumulator or boolean support operation.

   Evidence: [matrix validator](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s11_tenorreduction.py#L228), [transformation and support counting](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s11_tenorreduction.py#L616).

6. **Carry observed/estimated/missing status through totals and P&L sending. Confirmed policy gap.**

   Copying one quote leg to the other is an explicit continuity policy in FIX1.md. Preserve it if that is operationally useful. However, it sets Market Available to true and creates zero Move/P&L. The send base accepts that zero and drops the copied-quote provenance. It cannot then distinguish an estimated zero from an observed unchanged market.

   Separately, the dashboard zero-fills unavailable dRisk/P&L/Move, and some invalid/nonfinite risk inputs become zero. These are implemented policies, not accidental typos.

   Fix: structured quality status and coverage counts carried from source to display/export. Show known-value subtotals with explicit incomplete coverage. Define which quality states are allowed for an official submission. Keep invalid-input and omitted-position diagnostics visible.

   Evidence: [continuity status](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s03_calculations.py#L725), [dashboard zero-fill](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s07_governance.py#L511), [send aggregation](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s08_pnl.py#L1081).

**Where to simplify**

- **One small chart-data contract.** Explorer, Quick Risk, Quick Market and browser history independently decide aggregation, units, axes and missingness. Use common prepared series with metric kind, units, authoritative axis order and quality; keep a few straightforward renderers. Do not build a general chart framework. The inconsistent quote totals and disappearing plots show the cost of current duplication.
- **One owner for prepared revision data and cache invalidation.** The factory and `_RiskDataCache` both manage preparation/revision lifecycles. They do not necessarily duplicate every DataFrame allocation. Consolidate ownership before deleting measured performance caches. [Factory](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/app/s07_factory.py#L167), [Risk cache](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/risk/s02_state.py#L636).
- **Bound P&L history cache memory.** `_risk_summary_cache` and `_stats_cache` are ordinary dictionaries without eviction across distinct filter combinations. Add a simple LRU and a byte budget for frames. This is a source-confirmed growth risk, not a measured out-of-memory incident. [Cache declarations](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/history/s07_sql.py#L1002).
- **Reduce schema translation.** UI preparation lowercases/aliases the full frame; reduction translates it back into domain names and then back again. Keep stable field keys and separate display labels. Migrate the reducer boundary first, without a mass repository rename. [Preparation](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/ui/s02_aggregation.py#L296), [reverse conversion](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/risk/s02_state.py#L90).
- **Test behavior rather than file shape.** Keep dependency-direction and financial-contract tests. Relax exact module inventories and source line caps. JavaScript delimiter counts do not verify playback or filtering. Add a small browser suite for chart metric changes, filter application, expanded-state refresh, history comparison, and failure recovery. [Asset tests](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/tests/s39_assets.py#L115).
- **Retire compatibility only when no longer needed.** Runtime signature inspection silently drops unsupported filter arguments; current adapters should implement the declared protocol. Old archive support chooses a fallback by matching exception text. If old archives remain required, isolate/version that reader explicitly; otherwise move migration offline. [Search compatibility](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/risk/s10_search.py#L259), [archive fallback](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/history/s06_repository.py#L336).

There is no `.github` workflow in this commit. Automating the existing test/lint gate would make the substantial test investment more useful. The checked-in data occupies about 252 MiB across 1,322 files; consider a small everyday fixture plus a versioned full benchmark archive, while preserving deterministic reproducibility. Neither observation justifies a runtime rewrite.

**Plot changes and their purpose**

| Decision the plot should support | Suggested display | Reason |
|---|---|---|
| Where is exposure, and how much does the hedge offset it? | Signed XVA/Hedge bars plus a net marker, one shared axis and zero line | Current Explorer puts total and components on independently scaled axes, making size comparison harder. |
| Which tenors moved? | Open/Current lines above, signed Move bars below, aligned tenor axes and hover | Separates quote levels from changes without overlapping units. |
| Where is surface risk concentrated? | 2D heatmap with selected row/column profile; optional 3D | Negative pockets and far-side tenors remain visible without rotation. Reuse existing heatmap code. |
| What changed between dates? | A, B and B−A heatmaps | Share A/B color bounds; use symmetric zero-centered difference bounds. Fixed bounds during playback prevent artificial visual change. |
| Where do Predict and Colossus disagree? | Existing history lines plus a residual panel and ranked driver bars | Shows the gap directly and connects it to an underlying rather than requiring mental subtraction. |

Use sequential scales for level-only quantities and diverging scales for signed risk/moves/P&L. Do not make missing cells look like zero. Keep connector-owned tenor ordering, numeric matrices, and precise hover. A compact matrix toggle can work on narrow screens; selecting a cell should preserve its exact context.

Give every chart units, currency where applicable, raw/reported identity, as-of date and quality. `ProductSpec.market_unit` already supplies part of this; risk-unit metadata needs explicit definition. Use stable series colors and line styles across pages. Replace conflicting 500/600/800px height rules with one sizing policy based on tenor count and available width. These changes fit the current Plotly stack; [Plotly's heatmap support](https://plotly.com/python/heatmaps/) already provides categorical axes, labels, cell text and missing-cell behavior.

**New capabilities that fit this application**

1. **What changed since the previous committed snapshot?** Rank underlying/tenor changes; distinguish available evidence for market moves, new positions, adjustments and mapping changes. Keep an explicitly unexplained remainder. Existing snapshots, history and overlays are foundations, but provenance must be persisted to support reliable attribution. Start with measured changes before attempting causal explanations.
2. **Exception inbox.** Combine incomplete quotes, invalid/omitted risk, unmapped books, material Predict–Colossus residuals and newly crossed promotion thresholds. Open the exact affected slice with one click. Add ownership/acknowledgement only if this is a shared operational workflow. This makes existing diagnostics actionable.
3. **Controlled scenario workspace.** Apply explicit shocks in product units to a selected snapshot, show approximate P&L by tenor/underlying, and compare entered hypothetical hedges. Start with supported Delta/Gamma calculations and a few named shocks. Keep assumptions, unsupported products and missing inputs visible; isolate scenarios from official snapshots and send actions.

Saved views, history, playback, A/B date comparison, promotions, Stock/dStock and Predict–Colossus validation already exist. The additions above extend those workflows rather than duplicating them.

Suggested sequence: repair the empty-leg, aggregation and missing-chart bugs; fix cache recovery and monetary conservation; carry quality through outputs; consolidate chart preparation and redesign the chart families; then build the change-explanation and exception workflows. Add scenario analysis after units and quality contracts are reliable.


## Appendix F — full Data/Stock/P&L review, retained with its original date

The following is the complete 5 September page review. Its Statics result is included above; the other identified changes remain pending. It records reasoning and evidence that should not be lost when following the migration order.

Rebirth V5 — Data, Stock, P&L and Statics review

Reviewed 5 September 2026 against `streamlitdash/Rebirth-V5` main at `8f65a1124e54702597347967c7064eb4f7edf133`.

The strongest improvement would be to make the date, selected population and saved state of every result explicit. The pages have useful capabilities, but controls and results can disagree. Simplifying the appearance without fixing those disagreements would leave the hardest usability problems in place.

This review combines source inspection, a local browser using the shipped synthetic data, and targeted executions of the actual Python and JavaScript functions. Production integrations were not exercised. Only the Statics picker fix described below has been implemented, locally. Nothing has been committed, pushed, deployed or sent to downstream P&L destinations.

**Data: the underlying problem**

The page mixes three jobs: choosing what to load, inspecting what has already loaded, and moving through dates. Those jobs need distinct state and a clearer visual order. Currently, even an experienced user has to infer which controls produced the visible result.

1. **Risk and Market selections can disagree with the displayed result.** In the browser, I loaded Risk / Commo Delta / Brent, then switched to Market History without pressing Load. The Market tab and selectors changed, the breadcrumb asked me to choose an identity, but the existing Risk chart, playback and Risk-value table remained visible. Keeping a prior result while editing a query is useful only when its loaded identity remains unmistakable. Here it looks as though the new tab owns the old result. The loading and playback callbacks do not depend on the active tab or draft identity. [Loading and playback dependencies](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/data/s03_callbacks.py#L746).

2. **Navigation restores only part of the state.** I loaded Market / Brent / MTD: 15 dates from 3–21 August 2026. After visiting Stock and returning to Data, the result still had those 15 dates, but All was selected. The committed request persists in the application shell, while the remounted period control defaults to All. The visible controls therefore describe a different range from the result. Hydrate all query controls from the saved request, or clear both together. [Persistent request](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/app/s07_factory.py#L598), [period defaults](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/data/s02_view.py#L181).

3. **Reloading an imported Quick Risk selection can silently broaden its scope.** Executing the actual callback with an Activity 1 handoff and then loading the same identity changed its contributor filter from Activity 1 to none. The breadcrumb stayed identical. This is more serious than clutter: a user can believe they are continuing to inspect one activity while now viewing a broader population. The normal Load path reconstructs a catalog handoff without the imported filters. Preserve the scope on reload and period changes; show its include/exclude chips next to the loaded identity. Removing it should be an explicit, visible action. [Quick Risk filter capture](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/risk/s04_handoff.py#L24), [Data Load path](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/data/s03_callbacks.py#L669), [filter-free catalog conversion](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/history/s01_models.py#L520).

4. **Market quote summation can manufacture a move.** The surface-history Sum option adds quote levels across tenors. In an executed JavaScript case, quotes 20 and 30 became 50; on the next date, 20 and missing became 20. The observed quote had not moved, but the chart appeared to fall by 30. Default Market to an exact tenor. A basket or average needs a stated definition and coverage; adding risk remains valid where the measure is additive. [Summation implementation](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/assets/s09_playback.js#L372).

5. **Changing the view disrupts the analysis.** The playback identity includes view and slice, so switching views resets the selected date to the latest observation. A reproduction moved from September 1 to September 3 simply by changing the view. Separately, the single-tenor plot uses bounds from the entire bundle: a selected series of 10 inherited a 10–1,000 scale from another tenor. Preserve the selected date across presentation changes. Use bounds for the selected projection, with an explicit Lock scale option for comparisons. [Playback reset](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/assets/s09_playback.js#L641), [bundle-wide bounds](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/assets/s09_playback.js#L513).

**Data: the layout I would build**

Use one compact query strip in this order: **Risk / Market → exact identity → contributor scope for Risk → period/custom dates → Load**. The commit action belongs after all query inputs. Keep advanced identity options in a disclosure where practical. Show the latest available date and preserve the user's last period.

Immediately below, put an authoritative result caption containing the loaded kind, identity, contributor scope, actual date range and units. If controls have changed, show “Changes not loaded” beside Load. Switching Risk/Market should either restore that kind's last result or show its empty state. A result should never appear to belong to a different tab.

Then offer **Snapshot / Over time / Compare**. These are questions users can recognize. Reveal only the tenor/date controls needed for the active question. Preserve the date and selected tenor between compatible views.

| Data shape | Snapshot | Over time | Compare |
|---|---|---|---|
| Scalar | Value, previous observation, change, date and coverage | Line with a selected-date marker | A, B and B−A, with timeline context |
| One tenor axis | Signed risk bars or a market curve, in authoritative tenor order | Tenor × date heatmap, linked to a tenor line and date profile | A/B profiles on the same axis, with an aligned difference panel |
| Two tenor axes | Heatmap plus row/column slices and numeric matrix | Fix one tenor dimension, then show the other against time | A, B and B−A heatmaps with aligned axes |

Keep 3D available as an optional view. It is useful for some shapes, but the default should support accurate comparisons without rotation or occlusion. Use common bounds for A and B, and a zero-centered diverging scale for differences and signed risk. Use a sequential scale for market levels. Color should communicate sign/magnitude rather than imply that positive exposure is automatically good.

The detail table must follow the chart selection. At present it filters the date but not the selected slice; comparison shows Date B values without A or the difference. Provide exactly the displayed tenors, with A/B/B−A columns in Compare. Hide internal tenor-order columns from the main table, and format values with meaningful units and precision. The browser currently exposes raw tails such as `1364506.4233960002`. Preserve precision in exports and useful hover details. [Detail-table selection](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/assets/s09_playback.js#L675).

Make the two comparison dates searchable or use date pickers constrained to available observations. Default a comparison to the previous available observation unless the user has chosen another baseline. Reduce playback to previous/next observation, date, Play and speed; make looping explicit. Do not intercept ordinary page scrolling over the whole control card. Date axes should make archive gaps visible, with trading-day spacing as an explicit option where useful. [Date dropdowns](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/data/s02_view.py#L256), [wheel interception](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/assets/s09_playback.js#L726).

Move implementation details such as exact-row counts, cache generations and schema terminology into Diagnostics. The primary status should answer: what is selected, how much is covered, when was it observed, and why is something unavailable?

**Data: simplify the implementation around that flow**

Keep a draft query, a committed query, its loaded bundle and a small presentation state. Consume a Quick Risk/Market handoff once into the draft. Several selector callbacks currently arbitrate among the request, pending handoff, consumed nonce and current value; that creates competing sources of truth. Put units, allowed aggregations and coverage in the bundle contract so a generic JavaScript Sum branch cannot decide financial semantics.

Retain typed identities, strict input validation, authoritative tenor order, bounded archive reads and browser-local playback. Those are useful engineering. Improve behavioral coverage for the actual journeys above; source-substring assertions cannot catch a scope disappearing or a date jumping. Cache prepared arrays per bundle/projection if profiling demonstrates a need, before introducing more infrastructure.

**Stock: correctness before more pivot controls**

1. **History can broaden the clicked selection.** An executed fixture displayed a filtered Counterparty A / Portfolio P1 row worth 100. Clicking it resolved a CRDS + Activity key against the unfiltered snapshot and included Portfolio P2 / Counterparty B worth 900 as well. The history population became 1,000. Preserve the clicked row path, applied filters, currency/column selection and exact constituent identities. Show a breadcrumb and position count above the resulting history. Manual broad search can remain independent, but a row click must mean the selected row. [History key](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/stock/s05_pivot.py#L161), [history population resolution](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/stock/s04_callbacks.py#L567).

2. **The pivot silently omits columns beyond eight.** Nine currency groups of 100 produced eight visible groups totaling 800, while the position count still included all nine. A display cap must not drop part of a financial result. Offer column paging or an explicit remainder, with a complete total only where units are compatible. [Column cap](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/stock/s05_pivot.py#L193).

3. **Current holdings and whole-book changes need different views.** The current table deliberately excludes prior-only positions. In a fixture with a 500 exit, the displayed dStock summed to +110 while the whole-book change was −390. That is a valid current-holdings projection, but cannot serve as the whole-book movement. Use **Current positions / Changes**, with Added, Removed and Continuing entries in Changes and previous/current/difference columns. The domain comparison already computes the exits; expose it. [Current-only projection](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/stock/s01_data.py#L149), [outer comparison](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s09_stock.py#L436).

4. **The shipped demo's current and historical names disagree.** Current data normalizes `FAKE_REPLACE_ME` to `TEMP_REPLACE_ME`; the SQL archive lookup compares raw names. A current exact identity returned zero rows where the equivalent archived identity returned two. Normalize aliases consistently at the read boundary, preserving exact identity validation. This is confirmed for the repository's demo data, not evidence about private production names. [Current normalization](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/adapters/s08_stock.py#L48), [archive lookup](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/stock/s02_history.py#L344).

5. **Unavailable dates need a usable empty state.** In my browser run, Stock requested 4 September while the shipped archive ended 21 August. It displayed an internal “leaf has invalid entries” path error. Show “No Stock snapshot for this date,” the latest available date, and an explicit action to load it. Do not silently present an older snapshot as current. Also re-derive default dates and invalidate dependent history when the source snapshot changes; the current date store is initialized on page entry and refresh retains its date state. This refresh observation is from source inspection. [Page date initialization](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/app/s07_factory.py#L457), [refresh dependencies](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/stock/s04_callbacks.py#L140).

**Stock: a clearer page and better plots**

Start with **As of / Compared with / Applied view / Reporting currency**, plus freshness. Then show Current positions or Changes. Put custom Rows/Columns/Values behind Customize; give users a useful default hierarchy first. Let the selected row open a compact history/detail area with its exact scope.

Replace the overlaid Stock/dStock axes with two aligned panels: Stock as a line, dStock as signed bars beneath it. Separate scales are still appropriate, but separate panels make their different meanings explicit. Preserve archive gaps and annotate dates with partial constituent coverage. [Current dual-axis chart](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/stock/s02_history.py#L475).

A useful new chart is a reconciliation waterfall: previous value → additions → exits → change in continuing positions → current value. The final amount should tie to the table. Do not describe continuing-position valuation change as market P&L without the required attribution inputs. Add a movers/concentration view with a visible remainder, rather than silently truncating contributors.

Clarify whether a history means “today's selected holdings followed backward” or “the holdings that belonged to this group on each historical date.” Current identities/current mapping answer the first question. If the second is useful, it needs dated membership/mapping support. Also establish whether Market Value is already in a common reporting currency before allowing mixed-currency totals; otherwise partition by currency or use dated FX conversion. These are contract/design decisions, not claims that the current production values are definitely mixed.

Keep the page-owned pivot. Remove the unused older hierarchy/promotion route after checking its remaining imports and tests. Load detailed position rows only when their disclosure opens, and batch history reads for a selected basket instead of issuing one query per identity. There is no need for a second generic pivot framework.

**P&L: resolve the financial workflow inconsistencies first**

1. **Adding, saving and sending do not share the same arithmetic.** Using the actual editor/governance functions, a base row of 100 plus an added adjustment row of 10 for the same financial key produced an outbound calculation of 110. Saving the adjustment and applying the persisted overlay produced an effective value of 10. The editor collapses the rows additively, while saved adjustments replace the corresponding base value. No send was performed. Define explicit “Add delta” versus “Replace value” semantics, and compute one canonical effective result used by preview, save and every send path. [Save filtering and collapse](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/pnl/s05_sendcallbacks.py#L640), [replacement overlay](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/domain/s08_pnl.py#L1214).

2. **Saving one field can remove another saved adjustment.** With Show adjustments off, the save path sends the newly edited rows while replacing the entire affected portfolio file. In a temporary repository, an existing FXPL adjustment of 105 disappeared after saving an IRPL adjustment of 210 for the same portfolio. Use updates by full adjustment key and explicit deletions; a hidden row should not imply deletion. Add adjustment-store version checking, because a snapshot revision alone cannot distinguish two writers editing the same snapshot. This latter concurrency concern is source-based. The existing atomic file replacement is useful and should be retained. [Portfolio replacement selection](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/pnl/s05_sendcallbacks.py#L651), [persistence semantics](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/services/s03_adjustments.py#L248).

3. **The overview and outbound editor represent different states.** “Today” in the overview comes from the latest archived Predict summary, while sending uses the current risk snapshot and applicable saved adjustments. Both can be valid, but the page must distinguish them with dates and labels. Show live base P&L, the monetary effect of saved adjustments, and effective P&L to send. Put dated official history and MTD/YTD beside those with a clearly identified source/date. Do not use an undated Today label for whichever archive happens to be latest. [Today label](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/pnl/s10_summary.py#L26), [archived summary query](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/history/s07_sql.py#L1393), [current editor base](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/pnl/s02_editor.py#L453).

4. **The shipped demo also has an alias mismatch in the P&L overview.** The browser showed blank TOTAL values under the default current filters. The latest archive was 21 August. Querying it with the current `TEMP_REPLACE_ME` Activity 1 name returned no values; the equivalent archived `FAKE_REPLACE_ME` Activity 1 returned Current P&L of 4,401,992.03. Fix the common identity-normalization boundary, rather than clearing filters until a number appears. [Raw SQL filter matching](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/history/s07_sql.py#L258).

5. **Reconciliation totals can compare unequal coverage.** With one missing Predict portfolio and one complete portfolio, the parent displayed Predict 10 against Colossus 24. The Predict total covered only the complete portfolio; Colossus covered both. Missing leaf values are preserved, but parent summation skips them. Display Missing Predict / Missing Colossus / Matched / Mismatch statuses and coverage counts. Compute a matched residual on the same population, with unmatched amounts visible separately. Do not present a partial sum as a complete reconciliation total. [Missing leaf handling](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/pnl/s06_validation.py#L249), [hierarchy totals](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/pnl/s06_validation.py#L374).

6. **Some reconciliation items cannot be reached.** Each branch renders only ten children. Eleven underlyings within otherwise identical filter dimensions rendered only the first ten; there is no Underlying filter to reach the omitted one. Add search and load-more/paging, and order missing or materially discrepant entries first. Show Predict, Colossus, Difference and Status directly. Sorting only by absolute Predict can bury a large Colossus value whose Predict is absent. [Child cap](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/pnl/s06_validation.py#L428).

**P&L: a workflow users can follow**

Organize the page as **Review → Explain → Reconcile → Adjust → Send**, with a shared scope/date caption throughout.

- **Review:** live base, saved-adjustment effect and effective amount to send, alongside clearly dated official totals. Count missing inputs and unresolved differences.
- **Explain:** daily signed P&L bars and a separate cumulative line; contribution bars or a waterfall for the selected period. Clicking MTD/YTD should select the corresponding period and cumulative metric. The current click handler retains the hierarchy identity but discards which metric was clicked. [Click handling](https://github.com/streamlitdash/Rebirth-V5/blob/8f65a1124e54702597347967c7064eb4f7edf133/cube/pages/pnl/s08_aggregate.py#L435).
- **Reconcile:** a searchable exception table and horizontal residual bars, with missing inputs distinct from numerical differences. A zero-centered residual heatmap across SOG/product can locate clusters; the table remains the audit detail.
- **Adjust:** one editor with Group by SOG / Portfolio, rather than two independent copies of draft state. Show Base, Proposed, Difference, Reason and Saved/Unsaved status. Preserve stale drafts for explicit review/rebase when the source changes.
- **Send:** preview the exact effective rows, total, date, scope, revisions and destinations that will be sent. Rename Send All to Send filtered book when it follows the active filters. Scoped send currently uses the current draft while Send All reconstructs persisted data; those choices need consistent semantics and a visible warning when a different draft is excluded. No new destinations or automatic sending are needed.

Historical filters should include historical-only identities. Building options solely from the live snapshot and discarding selections that are absent today can make an old portfolio inaccessible. Use an archive/live option union appropriate to the selected mode, and keep the chosen scope visible.

The highest-value new features here are an adjustment change log with before/after/reason, reconciliation coverage, and an immutable local record of the reviewed outbound payload and its result. These support the existing financial workflow. They should follow the arithmetic fixes rather than sit on top of inconsistent previews.

**Statics: the reported picker problem is reproduced and fixed locally**

The selector itself changes the selected file and schema. A retained table filter can make it appear broken: filter Portfolio Mapping by `BOOK_A`, then choose Top Thresholds. The columns change, but the old Portfolio filter survives and hides every row in the new dataframe.

The fix clears filter, sorting, page, hidden columns and cell selection when the writable dataframe changes. It does not save or alter static source data. The same browser sequence now displays the threshold rows, and Portfolio Mapping, Top Thresholds, Concerto Mapping and Reported Underlying Mapping all display their correct schemas and data.

Changed files: `repo/cube/pages/static_data/s03_callbacks.py` and `repo/tests/s42_statics.py`. Focused validation: 13 Statics tests passed, Ruff lint/format checks passed, and `git diff --check` passed. A second code review found no blocker. The earlier repository-wide review ran 668 passing tests on the unmodified baseline; the full suite was not rerun after this narrow patch. Dash DataTable deprecation warnings remain a separate maintenance item.

**Suggested delivery order**

1. Apply the small Statics fix. Correct P&L adjustment save/effective-value semantics and preservation of existing adjustments.
2. Fix Data scope/result mismatches and Market quote aggregation; fix Stock clicked-history scope and silent column omission. Normalize demo/archive identities at the shared boundary.
3. Make dates, coverage and source state explicit across the three pages. Give Stock a Changes view and P&L matched reconciliation totals.
4. Reorganize Data into Snapshot / Over time / Compare, replace 3D defaults and align chart detail. Simplify Stock controls and consolidate P&L editors.
5. Add the useful extensions: pinned comparison baselines and saved Data views, a Stock change waterfall, and P&L adjustment/payload history. Profile the actual larger datasets before adding infrastructure.

This order ties every refactor to an observable problem or a concrete user question. It preserves the existing domain safeguards and avoids another layer of controls before the results are trustworthy.


## Appendix G — full Portfolio verification scripts

These are optional diagnostic scripts, not application modules. They make temporary in-process substitutions and do not modify the Risk source. Some explicitly expand large trees; run them outside a production worker. To reproduce their original layout, save them in a workspace containing a `repo/` checkout and run with the project environment. They write their JSON results beside the script. For a differently named checkout, change only the `REPO` path assignment before running. Full application tests belong in `tests/` when the Portfolio feature is actually implemented.

### portfolio-risk-repro.py

```python
"""Read-only runtime Portfolio probes; all hypothetical edits are in-memory only."""
from pathlib import Path
import sys, importlib.util, json, time
from types import SimpleNamespace
import pandas as pd
from plotly.utils import PlotlyJSONEncoder
ROOT = Path(__file__).parent
REPO = ROOT / 'repo'
sys.path.insert(0, str(REPO))
spec = importlib.util.spec_from_file_location('risk_fixtures', REPO/'tests/s19_riskfilters.py')
f = importlib.util.module_from_spec(spec); spec.loader.exec_module(f)
from cube.ui import s02_aggregation as agg
from cube.pages.risk import s06_explorertables as tree
from cube.pages.risk import s08_quickrisk as quick
from cube.pages.risk import s10_search as search
from cube.pages.risk import s07_explorer as events
from cube.services.s05_sources import build_production_refresh_manager
from cube.domain.s10_search import SearchCatalog
from cube.app.s07_factory import build_app
from dash import no_update
results={}
def record(name, run):
    start=time.perf_counter()
    try: value=run()
    except Exception as exc: value={'error':type(exc).__name__, 'message':str(exc)}
    results[name]={'seconds':round(time.perf_counter()-start,4),'result':value}
    print(name, json.dumps(results[name],default=str),flush=True)
    (ROOT/'portfolio-risk-repro-results.json').write_text(json.dumps(results,indent=2,default=str),encoding='utf8')
def walk(x):
    if x is None:return
    if isinstance(x,(list,tuple)):
        for y in x:yield from walk(y)
        return
    yield x
    yield from walk(getattr(x,'children',None))
def stats(x):
    nodes=list(walk(x)); return {'tr':sum(type(n).__name__=='Tr' for n in nodes),'th':sum(type(n).__name__=='Th' for n in nodes),'td':sum(type(n).__name__=='Td' for n in nodes),'json_bytes':len(json.dumps(x,cls=PlotlyJSONEncoder))}
def row_labels(x):
    return [n.children for n in walk(x) if getattr(n,'className','')=='row-label-text']
raw=f._raw_risk_frame(); prepared=agg.prepare_risk_data(raw)
record('baseline_contract',lambda:{'rows':len(prepared),'portfolio_columns':list(prepared.columns).count('portfolio'),'books':prepared.portfolio.tolist(),'selected_dimension':agg.selected_dimension('portfolio'),'quick_normalized':search._normalise_quick_search_index(['Underlying','Portfolio']),'portfolio_row_key':agg.row_key({'underlying':'USD-SOFR','portfolio':'BOOK-A'}),'portfolio_scope_rows':len(agg.frame_for_context(prepared,{'portfolio':'BOOK-A'}))})
record('filter_only_failure',lambda:agg.apply_filters(prepared,['IR'],['Risk'],{'portfolio':['BOOK-A']}))
record('hierarchy_only_failure',lambda:{'labels':row_labels(tree.build_tree_rows(prepared,['risk','pl'],[agg.row_key({'risk greek':'Delta'})],[],groups=['risk greek','portfolio']))})
old_dims=agg.VIEW_DIMENSIONS
agg.VIEW_DIMENSIONS=(*old_dims,'portfolio')
def naive_dimension():
    duplicate=agg.prepare_risk_data(raw)
    result={'portfolio_columns':list(duplicate.columns).count('portfolio')}
    try:tree.build_alt_risk_table(duplicate,'risk',[],dimension='portfolio')
    except Exception as exc:result.update(error=type(exc).__name__,message=str(exc))
    return result
record('global_dimension_edit_failure',naive_dimension)
agg.VIEW_DIMENSIONS=old_dims
# Exercise registered main page callback without HTTP: same wrapped callback body used by Dash.
def callback_probe():
    app=build_app(refresh_manager=f._warm_manager())
    cb=next(item['callback'].__wrapped__ for item in app.callback_map.values() if 'callback' in item and item['callback'].__wrapped__.__name__=='reduce_and_render_risk_view')
    old_ctx=events.ctx; events.ctx=SimpleNamespace(triggered_prop_ids={'table-dimension.value':'table-dimension'})
    try:
        out={}
        for view in ('main','alt'):
            data=cb('IR','Delta',1,'portfolio',view,'single',None,None,None,['Risk'],'cs01','risk','risk','risk','total','auto',[[],[],[],[]],[],[],None,'reported',None,[],[],{'risk_type':'IR','ir_family':'Delta','data_revision':1},None)
            comps=[x for x in data if x is not no_update and hasattr(x,'to_plotly_json')]
            out[view]=[{'labels':row_labels(x),**stats(x)} for x in comps]
        return out
    finally: events.ctx=old_ctx
record('main_callback_portfolio_value_only',callback_probe)
# Bounded Quick Risk option addition, using actual domain pivot and UI rendering helper.
old_options=search.QUICK_SEARCH_INDEX_OPTIONS
search.QUICK_SEARCH_INDEX_OPTIONS=(*old_options,('Portfolio','Portfolio'))
quick.QUICK_SEARCH_INDEX_OPTIONS=search.QUICK_SEARCH_INDEX_OPTIONS
catalog=f._quick_catalog()
def fixture_pivot():
    out={}
    for indexes in [('Portfolio',),('Underlying','Portfolio'),('Underlying','Tenor Swap','Portfolio')]:
        r=catalog.pivot_combined_hierarchy('IR | Delta | USD-SOFR',index_columns=indexes,leaf_limit=250)
        out[' > '.join(indexes)]={'total_leaves':r.total,'frame':r.frame.to_dict('records')}
    manager=SimpleNamespace(pivot_combined_hierarchy=catalog.pivot_combined_hierarchy,resolve_history_identity=lambda *a,**kw:SimpleNamespace(source_types=('ir/delta',)))
    component, update=search._render_quick_search_pivot(manager,combine_udl='IR | Delta | USD-SOFR',index_columns=['Underlying','Tenor Swap','Portfolio'],is_open=True)
    out['actual_renderer']={'class':component.className,'effective_rows':update,'labels':row_labels(component),**stats(component)}
    return out
record('quick_risk_fixture_support',fixture_pivot)
manager=build_production_refresh_manager(stage_delays={})
def load_demo():
    snap=manager.refresh(force_risk=True,force_pl=True)
    return {'revision':snap.revision,'dashboard_rows':len(snap.dashboard_frame),'portfolios':snap.dashboard_frame.Portfolio.nunique(),'source_types':snap.dashboard_frame['Source Type'].unique().tolist()}
record('demo_refresh',load_demo)
def demo_quick():
    rawdemo=manager.snapshot.dashboard_frame
    picks=rawdemo.drop_duplicates('Source Type')[['Source Type','Risk Type','Risk Greek','Reported Underlying']]
    out=[]
    for _,row in picks.iterrows():
        identity=' | '.join([row['Risk Type'],row['Risk Greek'],row['Reported Underlying']])
        component, update=search._render_quick_search_pivot(manager,combine_udl=identity,index_columns=['Underlying','Tenor Swap','Tenor Option','Portfolio'],is_open=True)
        effective=list(update) if update is not no_update else ['Underlying','Tenor Swap','Tenor Option','Portfolio']
        r=manager.pivot_combined_hierarchy(identity,index_columns=effective,leaf_limit=250)
        leaves=r.frame.loc[r.frame['__Hierarchy Depth__']==len(effective)]
        base=manager.pivot_combined_hierarchy(identity,index_columns=['Underlying'],leaf_limit=250)
        out.append({'source':row['Source Type'],'identity':identity,'effective_rows':effective,'leaf_count':r.total,'class':component.className,'risk_sum':float(leaves.Risk.sum()),'base_risk_sum':float(base.frame.Risk.sum()),'pl_sum':float(leaves.PL.sum()),'base_pl_sum':float(base.frame.PL.sum()),**stats(component)})
    return out
record('demo_quick_all_products',demo_quick)
# Valid row identity allowlist addition; no schema/view registry changes.
agg.ROW_KEY_COLUMNS.append('portfolio')
def tree_support():
    groups=['risk greek','underlying','tenor swap','portfolio']
    opens=[agg.row_key({'risk greek':'Delta'}),agg.row_key({'risk greek':'Delta','underlying':'USD-SOFR'}),agg.row_key({'risk greek':'Delta','underlying':'USD-SOFR','tenor swap':'1Y'})]
    rows=tree.build_tree_rows(prepared,['risk','pl','open','current'],opens,[],groups=groups)
    scope=agg.frame_for_context(prepared,{'portfolio':'BOOK-A'})
    return {'labels':row_labels(rows),'unique_row_keys':len(set(n.id['key'] for n in walk(rows) if isinstance(getattr(n,'id',None),dict) and 'key' in n.id)),'book_a_risk':float(scope.risk.sum()),'book_a_pl':float(scope.pl.sum()),'detail_book_a':agg.detail_frame(prepared,{'portfolio':'BOOK-A'},'risk').to_dict('records'),'parent_market':{c:agg.hierarchical_market_value(prepared,c) for c in ['open','current']},**stats(rows)}
record('allowlisted_hierarchy_and_detail',tree_support)
# Main tree payload is unbounded once branches expanded; quote identity independent of books.
def all_open(frame,groups):
    return [agg.row_key(row) for depth in range(1,len(groups)) for row in frame[groups[:depth]].drop_duplicates().to_dict('records')]
def size_probe():
    rows=[]; base=raw.iloc[0].to_dict()
    for b in range(100):
        for t in range(10):rows.append({**base,'Portfolio':f'BOOK-{b:03d}','Tenor Swap':f'{t+1}Y','Tenor Swap Order':t,'Risk':10.,'dRisk':1.,'PL':4.})
    index=agg.HierarchyAggregationIndex(agg.prepare_risk_data(pd.DataFrame(rows))); big=index.frame; out={}
    for groups in [['risk greek','underlying','tenor swap','portfolio'],['risk greek','portfolio','underlying','tenor swap']]:
        for expanded in [False,True]:
            start=time.perf_counter(); rendered=tree.build_tree_rows(big,['risk','pl'],all_open(big,groups) if expanded else [],[],groups=groups,aggregation_index=index)
            out[' > '.join(groups)+(' expanded' if expanded else ' collapsed')]={'render_seconds':round(time.perf_counter()-start,3),**stats(rendered)}
    agg.VIEW_DIMENSIONS=(*old_dims,'portfolio'); agg.DIMENSION_LABELS['portfolio']='Portfolio'
    start=time.perf_counter(); rendered=tree.build_alt_risk_table(big,'risk',[],dimension='portfolio'); out['Split VA 100 portfolios collapsed']={'render_seconds':round(time.perf_counter()-start,3),**stats(rendered)}
    agg.VIEW_DIMENSIONS=old_dims
    return out
record('size_comparison_100_books_10_tenors',size_probe)
def cap_probe():
    books=pd.concat([catalog._risk_pivot_frame.iloc[[0]].assign(Portfolio=f'BOOK-{i:03d}') for i in range(300)],ignore_index=True)
    capped=SearchCatalog(revision=3,risk_dates=dict(catalog.risk_dates),market_date=catalog.market_date,market_frame=catalog._market_frame,risk_pivot_frame=books)
    r=capped.pivot_combined_hierarchy('IR | Delta | USD-SOFR',index_columns=['Underlying','Portfolio'],leaf_limit=250)
    component=quick.build_quick_search_pivot(r.frame,combine_udl='IR | Delta | USD-SOFR',index_columns=['Underlying','Portfolio'],total=r.total,revision=3)
    footer=next(n for n in walk(component) if getattr(n,'className','')=='quick-search-total-row')
    values={n.to_plotly_json()['props'].get('data-metric'):n.to_plotly_json()['props'].get('data-copy-value') for n in walk(footer) if type(n).__name__=='Td'}
    return {'total_leaves':r.total,'rendered_rows':len(r.frame),'visible_leaf_risk':r.frame.loc[r.frame['__Hierarchy Depth__']==2,'Risk'].sum(),'parent_risk':r.frame.loc[r.frame['__Hierarchy Depth__']==1,'Risk'].sum(),'footer':values}
record('quick_risk_250_leaf_cap',cap_probe)
```
### portfolio-main-callback-repro.py

```python
from pathlib import Path
import importlib.util,sys,json,time
from types import SimpleNamespace
from plotly.utils import PlotlyJSONEncoder
ROOT=Path(__file__).parent; REPO=ROOT/'repo';sys.path.insert(0,str(REPO))
spec=importlib.util.spec_from_file_location('risk_fixtures',REPO/'tests/s19_riskfilters.py');f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
from cube.ui import s02_aggregation as a
from cube.pages.risk import s06_explorertables as t
from cube.pages.risk import s07_explorer as e
from cube.app.s07_factory import build_app
from cube.services.s05_sources import build_production_refresh_manager
from dash import no_update
out={}
def walk(x):
    if x is None:return
    if isinstance(x,(list,tuple)):
        for y in x:yield from walk(y)
        return
    yield x
    yield from walk(getattr(x,'children',None))
def stats(x):return {'rows':sum(type(n).__name__=='Tr' for n in walk(x)),'json_bytes':len(json.dumps(x,cls=PlotlyJSONEncoder))}
def opens(frame,groups):
    keys=[]
    def visit(scoped,level,context):
        level=a.visible_tree_level(scoped,level,context,groups)
        if level>=len(groups):return
        column=groups[level]
        for value in a.ordered_unique(scoped,column):
            child=a.tree_scope(scoped,column,value)
            if child.empty:continue
            nextcontext={**context,column:value}
            nextlevel=a.visible_tree_level(child,level+1,nextcontext,groups)
            if nextlevel<len(groups):keys.append(a.row_key(nextcontext));visit(child,nextlevel,nextcontext)
    visit(frame,0,{})
    return keys
a.ROW_KEY_COLUMNS.append('portfolio'); original=t._active_groups_for_frame
t._active_groups_for_frame=lambda *args,**kwargs:[*original(*args,**kwargs),'portfolio']
prepared=a.prepare_risk_data(f._raw_risk_frame());groups=t._active_groups_for_frame(prepared,False,False,'reported')
app=build_app(refresh_manager=f._warm_manager())
cb=next(item['callback'].__wrapped__ for item in app.callback_map.values() if 'callback' in item and item['callback'].__wrapped__.__name__=='reduce_and_render_risk_view')
e.ctx=SimpleNamespace(triggered_prop_ids={'table-dimension.value':'table-dimension'})
args=['IR','Delta',1,'activity','main','single',None,None,None,['Risk'],'cs01','risk','risk','risk','total','auto',[[],[],[],[]],[],[],None,'reported',None,opens(prepared,groups),[],{'risk_type':'IR','ir_family':'Delta','data_revision':1},None]
r=cb(*args);main=r[11]
labels=[n.children for n in walk(main) if getattr(n,'className','')=='row-label-text']
keys=[n.to_plotly_json()['props'].get('data-risk-key') for n in walk(main) if type(n).__name__=='Tr']
out['actual_main_callback_appended_portfolio']={'groups':groups,'labels':labels,'portfolio_keys':[k for k in keys if k and 'portfolio' in k],**stats(main)}
# Same registered callback re-renders selected portfolio detail on plot measure change.
e.ctx=SimpleNamespace(triggered_prop_ids={'plot-measure.value':'plot-measure'},triggered_id='plot-measure')
args[-1]={'key':a.row_key({'portfolio':'BOOK-A','underlying':'USD-SOFR'}),'metric':'risk','source':'main'}
r=cb(*args)
out['actual_detail_callback_book_a']={'component_class':getattr(r[-1],'className',None),**stats(r[-1])}
m=build_production_refresh_manager(stage_delays={});snap=m.refresh(force_risk=True,force_pl=True)
frame=a.prepare_risk_data(snap.dashboard_frame)
rows=[]
for source, subset in frame.groupby('source type',sort=False):
    identity=subset['reported underlying'].iloc[0];subset=subset.loc[subset['reported underlying']==identity]
    for mode in ['reported','underlying']:
        g=t._active_groups_for_frame(subset,False,False,mode)
        # Expand through first Portfolio leaves for one exact raw/reporting identity.
        start=time.perf_counter();component=t.build_risk_table(subset,[],opens(subset,g),promotion_enabled=False,region_enabled=False,underlying_identity_mode=mode)
        labels=[n.children for n in walk(component) if getattr(n,'className','')=='row-label-text']
        rows.append({'source':source,'identity_mode':mode,'source_rows':len(subset),'books':subset.portfolio.nunique(),'book_labels_rendered':sum(label in set(subset.portfolio) for label in labels),'seconds':round(time.perf_counter()-start,3),**stats(component)})
out['all_demo_sources_main_cross']=rows
full=[]
for risk_type,subset in frame.groupby('risk type',sort=False):
    g=t._active_groups_for_frame(subset,True,True,'reported');open_keys=opens(subset,g)
    start=time.perf_counter();component=t.build_risk_table(subset,[],open_keys,promotion_enabled=True,region_enabled=True,underlying_identity_mode='reported')
    labels=[n.children for n in walk(component) if getattr(n,'className','')=='row-label-text']
    record={'risk_type':risk_type,'source_rows':len(subset),'book_labels_rendered':sum(label in set(subset.portfolio) for label in labels),'seconds':round(time.perf_counter()-start,3),**stats(component)}
    assert record['book_labels_rendered']>0
    full.append(record)
out['full_demo_all_open_cross_with_promotion_region']=full
# Both other presentation builders share the same runtime hierarchy helper.
credit=frame.loc[frame['risk type']=='Credit'];g=t._active_groups_for_frame(credit,False,False,'reported');open_keys=opens(credit,g)
out['credit_multi']=stats(t.build_credit_multi_table(credit,'risk',open_keys,promotion_enabled=False,region_enabled=False))
out['split_va_activity']=stats(t.build_alt_risk_table(prepared,'risk',opens(prepared,groups),dimension='activity',promotion_enabled=False,region_enabled=False))
assert 'BOOK-A' in out['actual_main_callback_appended_portfolio']['labels']
assert 'BOOK-B' in out['actual_main_callback_appended_portfolio']['labels']
assert all(row['book_labels_rendered']>0 for row in rows)
(ROOT/'portfolio-main-callback-results.json').write_text(json.dumps(out,indent=2,default=str),encoding='utf8')
print(json.dumps(out,indent=2,default=str))
```
### portfolio-ir-family-repro.py

```python
from pathlib import Path
exec(Path('portfolio-main-callback-repro.py').read_text().split('app=build_app')[0])
from cube.ui.s01_constants import IR_GREEK_FAMILIES
m=build_production_refresh_manager(stage_delays={});snap=m.refresh(force_risk=True,force_pl=True);frame=a.prepare_risk_data(snap.dashboard_frame)
records=[]
for family in IR_GREEK_FAMILIES:
    subset=a.filter_ir_family(frame.loc[frame['risk type']=='IR'],'IR',family)
    if subset.empty:continue
    groups=t._active_groups_for_frame(subset,True,True,'reported');open_keys=opens(subset,groups)
    start=time.perf_counter();component=t.build_risk_table(subset,[],open_keys,promotion_enabled=True,region_enabled=True,underlying_identity_mode='reported')
    item={'family':family,'source_rows':len(subset),'seconds':round(time.perf_counter()-start,3),**stats(component)};records.append(item);print(json.dumps(item),flush=True)
p=Path('portfolio-main-callback-results.json');data=json.loads(p.read_text());data['full_demo_ir_family_all_open']=records;p.write_text(json.dumps(data,indent=2),encoding='utf8')
```

## Appendix H — complete scoped cache comparison script

This is an optional synthetic diagnostic outside the application package. Follow Step B5 for placement and interpretation.

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
