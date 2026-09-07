# Portfolio preflight — checks before restoring Risk filtering and grouping

Use this guide before restoring Portfolio on the main Risk page. It is a readiness checklist and a plan for later acceptance, not a command to enable every Portfolio branch immediately. The changes already made in your JupyterHub are not directly visible here: inspect the files actually launched and record the outcomes on that running application.

The intended first result is two independent controls: a Portfolio filter selects contributing positions, and an optional Portfolio grouping in Cross categorises those selected positions using the existing reporting-dimension control. Product, Category and Sub Category keep their existing meanings and choices. Keep the previous default grouping. A simultaneous Category → Sub Category → Portfolio hierarchy is a separate layout decision; it is not required to restore Portfolio as another available dimension.

At roughly 100k positions and 300–400 portfolios, the dropdown options alone are small. Portfolio is already part of position identity. The risks to investigate are incorrect joins, duplicate columns, mismatched filter state, unnecessary retained table versions, repeated grouping and the number of rendered rows **and columns**. No row count alone establishes that an app will or will not crash.

Follow the chapters in this order:

1. [Locate the running copy](#portfolio-start) and establish the scope of the checks.
2. [Check data and financial identity](#portfolio-data), including mappings and a narrow baseline.
3. [Check filter wiring](#portfolio-filters), including Apply, saved views and history handoffs.
4. [Check hierarchy and memory safeguards](#portfolio-hierarchy), including the existing cold Full-tenor problem.
5. [Measure the current app](#portfolio-measurement), then keep the staged acceptance plan for later.
6. [Complete the readiness record](#portfolio-readiness) and identify the exact small implementation jobs that remain.

Mark each check **observed and acceptable**, **failed**, or **not observed**. A missing observation is not a pass. Checks involving a Portfolio control that is still absent must be marked **pending implementation**, not performed by editing browser storage.

<a id="portfolio-start"></a>

## Chapter 1 — Locate the actual source and avoid changing scope during diagnosis

1. Find the existing notebook or launcher used to start your application. Identify the folder it launches, containing `app.py`, `cube` and `assets`. A second uploaded folder with the same name is not necessarily the running copy.
2. Save unrelated work. Keep the app's existing source data, daily archives, saved views, adjustments and logs. These checks do not require deleting any of them or triggering an outbound financial action.
3. Open a Python notebook and run the following source-only setup. Replace only the folder expression as needed. If the notebook is already in the application folder, use `APP_ROOT = Path.cwd().resolve()` instead. The cell does not import or start the app.

```python
from pathlib import Path
import ast
import hashlib

APP_ROOT = (Path.cwd() / "Rebirth").resolve()  # Point to the folder actually launched.
for required in ("app.py", "cube", "assets"):
    if not (APP_ROOT / required).exists():
        raise ValueError(f"Application folder is missing {required}: {APP_ROOT}")
print("Application folder:", APP_ROOT)

PORTFOLIO_PREFLIGHT_SOURCE_FILES = [
    "cube/domain/s01_schema.py",
    "cube/domain/s07_governance.py",
    "cube/ui/s01_constants.py",
    "cube/ui/s02_aggregation.py",
    "cube/ui/s03_filters.py",
    "cube/pages/risk/s01_common.py",
    "cube/pages/risk/s02_state.py",
    "cube/pages/risk/s03_defaults.py",
    "cube/pages/risk/s04_handoff.py",
    "cube/pages/risk/s06_explorertables.py",
    "cube/pages/risk/s07_explorer.py",
    "cube/pages/risk/s14_workspacecallbacks.py",
    "cube/pages/risk/s16_view.py",
    "cube/pages/risk/s17_callbacks.py",
]
for relative in PORTFOLIO_PREFLIGHT_SOURCE_FILES:
    path = APP_ROOT / relative
    if not path.is_file():
        print("NOT FOUND; locate the current equivalent:", relative)
        continue
    raw = path.read_bytes()
    ast.parse(raw.decode("utf-8-sig"), filename=str(path))
    print("Syntax OK:", relative, "saved-source SHA256:", hashlib.sha256(raw).hexdigest())
```

4. Keep the printed source identities in your notes. They identify the saved files, not the code already loaded by an old process. Restart the existing app with the same launcher if the running source is stale; do not start a second server to compare it.
5. Record the existing default filter view and any explicit saved view you are using. Keep the selected Risk Type, Greek, Product partition, dates, revision, promotion setting and raw/reported identity mode fixed for numerical comparisons.
6. Do not refresh source data halfway through a before/after display comparison. If a normal refresh completes, record the new revision and establish a fresh baseline. A changed market or position set can legitimately change the figures.
7. The following chapters use ordinary Python source/metadata/count checks and browser observations. Run a fenced cell only when its step says to run it. File/function names are inspection locations; they are not an instruction to overwrite the complete module.

**Keep now:** the current Portfolio data, existing Stock/P&L Portfolio controls, the completed cache and row-budget work, unified standalone Data, full source tenors, and the existing default Risk grouping.

**Do not add yet:** a second Portfolio schema field, another filter-state writer, a new full-table cache, or unrestricted Portfolio expansion. First identify the particular missing UI connections and the actual available headroom.

<a id="portfolio-data"></a>

## Chapter 2 — Check the Portfolio data and financial scope

Adding a Portfolio filter selects rows that already exist. Adding Portfolio as a view dimension separates those same rows into Portfolio groups. Neither operation should multiply 100,000 positions by 300–400 portfolios. The expensive part can be the number of displayed hierarchy nodes, repeated aggregation, retained frames and rendered components. First prove that the existing position data already contains the correct Portfolio identity.

### Data step 1 — Confirm the field names and their ownership

1. Open `cube/domain/s01_schema.py` in the JupyterHub file editor.
2. Find `PORTFOLIO_COLUMN`, `PORTFOLIO_FIELDS` and `PORTFOLIO_CONFIG_REQUIRED_COLUMNS`.
3. Confirm the following case-sensitive mapping. Use the external name in connector/configuration frames and the internal name in prepared Risk frames and UI filter dictionaries.

| Meaning | External column | Prepared UI key |
| --- | --- | --- |
| Position's Portfolio identity | `Portfolio` | `portfolio` |
| Exposure/Hedges partition | `Product` | `product` |
| Activity | `Activity` | `activity` |
| Signoff group | `SignoffGroup` | `signoffgroup` |
| Category | `Category` | `category` |
| Sub category | `Sub Category` | `subcategory` |

4. Open `cube/ui/s01_constants.py` and find `PORTFOLIO_UI_FIELD`. Portfolio already has its own UI field definition. The configuration registry describes metadata attached to a Portfolio; it does not need a second metadata entry also named Portfolio.
5. Open `cube/ui/s02_aggregation.py` and find `prepare_risk_data`. Confirm that its returned position frame retains one `portfolio` column even though the existing Risk controls exclude Portfolio.

**Expected:** Portfolio identity already travels with positions; Product, Category and Sub Category are existing metadata. Product means the existing `XVA`/`Hedges` partition here, not `Risk Type` such as IR, FX or Commodity.

**If this differs:** record the actual local definitions before changing any lists. Do not add both `sub category` and `subcategory`, insert a second Portfolio field, rename raw Underlying to Portfolio, or repurpose Product to mean an instrument family. Fix the first missing projection or incorrect rename in the existing data path. Remove nothing from the connector schema for this check.

### Data step 2 — Identify which running data you can inspect

1. Use the notebook/kernel that already owns the running app's data, if that is how the app was started.
2. Record the current displayed revision, Market Date, Risk Date for the chosen product, tenor mode and whether a refresh is running. Wait for a normal refresh already in progress to finish before comparing values.
3. Run this ordinary Python cell. It lists at most 20 existing DataFrame variable names and dimensions. It does not load data, start the app or print position rows.

```python
import pandas as pd

portfolio_candidates = []
for portfolio_name, portfolio_value in list(globals().items()):
    if isinstance(portfolio_value, pd.DataFrame):
        portfolio_candidates.append({
            "variable": portfolio_name,
            "rows": len(portfolio_value),
            "columns": len(portfolio_value.columns),
            "has_prepared_portfolio": "portfolio" in portfolio_value.columns,
            "has_external_portfolio": "Portfolio" in portfolio_value.columns,
        })
for portfolio_item in sorted(
    portfolio_candidates, key=lambda item: item["variable"]
)[:20]:
    print(portfolio_item)
if not portfolio_candidates:
    print("No existing DataFrames are available in this notebook kernel.")
del portfolio_candidates
```

4. Identify an **already prepared, unfiltered, Full-tenor position frame** belonging to the same committed revision. Confirm its origin from the cell or function that produced it. A row count or matching column name alone does not establish that it is the correct frame.
5. If that frame is available, replace the one quoted placeholder in this cell with its existing notebook variable name, then run the cell. It creates another reference to that frame; it does not copy the full DataFrame.

```python
PORTFOLIO_PREPARED_VARIABLE = "REPLACE_WITH_EXISTING_PREPARED_FRAME_VARIABLE"

def portfolio_bind_existing_frame(variable_name, required_columns):
    value = globals().get(variable_name)
    if not isinstance(value, pd.DataFrame):
        raise RuntimeError(
            "Use the name of an existing DataFrame in this kernel. "
            "Do not start another app or load another source to create it."
        )
    if not value.columns.is_unique:
        raise RuntimeError("The selected frame contains duplicate column names.")
    missing = [column for column in required_columns if column not in value]
    if missing:
        raise RuntimeError(f"The selected frame is missing columns: {missing}")
    return value

portfolio_frame = portfolio_bind_existing_frame(
    PORTFOLIO_PREPARED_VARIABLE,
    ["portfolio", "product", "activity", "signoffgroup", "category",
     "subcategory", "risk type", "risk greek", "split", "risk", "drisk", "pl"],
)
print({"rows": len(portfolio_frame), "portfolio_column_count":
       list(portfolio_frame.columns).count("portfolio")})
```

**Expected:** exactly one Portfolio column, and the same complete position scope you intend to filter. The remaining frame-based instructions use this `portfolio_frame` reference. Treat it as read-only. Do not assign into it, rename its columns in place or change its dtypes.

**If the app runs in a different process:** notebook variables cannot inspect that process's frames. Do not call `build_app`, `build_production_refresh_manager`, a connector, `manager.snapshot` or `read_frame` to manufacture a second diagnostic dataset. `snapshot` copies multiple large frames; `read_frame` copies the named large frame. Use the source checks and the existing app's Statics, warnings, logs and narrow detail views described below. Mark unavailable frame checks as **not observed**, not passed. A saved export is useful only when its date, revision and data boundary are known; a historical or aggregated export is not a substitute for the current prepared position frame.

### Data step 3 — Check Portfolio identity survived preparation

1. Run the following only after Data step 2 bound `portfolio_frame` to the correct existing frame.
2. Read the printed counts. This cell builds a Portfolio Series and a small metadata summary, not a second full position frame.

```python
portfolio_names = portfolio_frame["portfolio"].astype("string")
portfolio_blank = portfolio_names.isna() | portfolio_names.str.strip().eq("").fillna(False)
portfolio_distinct_names = pd.Series(portfolio_names.dropna().unique(), dtype="string")
portfolio_normalized_name_counts = (
    portfolio_distinct_names.str.strip().str.casefold().value_counts(dropna=False)
)
portfolio_metadata = ["product", "activity", "signoffgroup", "category", "subcategory"]
portfolio_metadata_counts = portfolio_frame.groupby(
    "portfolio", observed=True, sort=False, dropna=False
)[portfolio_metadata].nunique(dropna=False)
print({
    "position_rows": len(portfolio_frame),
    "distinct_portfolios": int(portfolio_names.nunique(dropna=True)),
    "blank_portfolio_rows": int(portfolio_blank.sum()),
    "literal_unspecified_portfolio_rows": int(portfolio_names.eq("Unspecified").fillna(False).sum()),
    "portfolio_rows_with_surrounding_space": int(
        portfolio_names.ne(portfolio_names.str.strip()).fillna(False).sum()
    ),
    "ambiguous_normalized_portfolio_groups": int(
        portfolio_normalized_name_counts.gt(1).sum()
    ),
    "distinct_identifiers_in_ambiguous_groups": int(
        portfolio_normalized_name_counts.loc[portfolio_normalized_name_counts.gt(1)].sum()
    ),
    "portfolios_with_conflicting_metadata": int(
        portfolio_metadata_counts.gt(1).any(axis=1).sum()
    ),
})
del portfolio_names, portfolio_blank, portfolio_metadata_counts
del portfolio_distinct_names, portfolio_normalized_name_counts
```

3. Compare the distinct Portfolio count with the expected mapped books present in this revision. It need not equal all 300–400 configured portfolios: some may have no positions in the current product/date or be excluded from the released dashboard because their mapping is missing.
4. If the frame contains only `Unspecified` for Portfolio, trace `to_dashboard_frame` in `cube/domain/s07_governance.py`, followed by `prepare_risk_data` in `cube/ui/s02_aggregation.py`. The preparation fallback can keep an old frame usable without proving genuine Portfolio identity exists. A placeholder cannot support a meaningful Portfolio filter.
5. Check the two ambiguity counts. These examine distinct original names, such as `Book A` and `book a`, after whitespace/case normalization for diagnosis only. Repeated position rows in the same original Portfolio do not count as a collision. Nonzero counts identify books that a case-insensitive path could combine while an exact-match Quick or history path treats them separately. Keep the original names and resolve the intended identity/matching policy before enabling the filter.

**Expected:** no blank identities or unresolved normalized-name collisions; one metadata value per Portfolio in this revision; any literal `Unspecified` Portfolio is explained against the authoritative source. The same Portfolio can occur on many position rows. That repetition is normal.

**If failed:** fix the missing source column, wrong projection or inconsistent mapping before adding UI controls. Do not repair Portfolio names by globally lowercasing them, stripping meaningful characters or filling every missing identity with a real Portfolio. Investigate whitespace at the connector boundary using the existing validation policy. Do not aggregate positions merely to force one row per Portfolio.

### Data step 4 — Check the existing Portfolio mapping

1. Open `cube/domain/s07_governance.py` and locate `load_config`.
2. Check that the active mapping supplies `Portfolio`, `Product`, `Activity`, `SignoffGroup` and `Category`.
3. Check `Sub Category`: an absent optional column is filled with `Unspecified` by the current validator; a supplied blank value is rejected. Supplying Sub Category is useful if you want that view to distinguish books.
4. Confirm one mapping row per Portfolio for the effective mapping date. The existing dated source receives the Portfolio date from the manager; `cube/services/s05_sources.py::get_portfolio_config` documents it as one pandas business day before Market Date. Retain the app's existing date policy instead of loading today's mapping into every historical view.
5. Confirm Product values resolve to `XVA` or `Hedges`. Other metadata may not use the reserved literal `Unmapped`; that label belongs to missing mappings.
6. If the exact already loaded mapping exists in this notebook, use its variable name below. Otherwise inspect the existing Statics configuration view for these columns, duplicate Portfolio identities and missing values; do not call the Portfolio source again for this check.

```python
PORTFOLIO_CONFIG_VARIABLE = "REPLACE_WITH_EXISTING_CONFIG_FRAME_VARIABLE"
portfolio_config_frame = portfolio_bind_existing_frame(
    PORTFOLIO_CONFIG_VARIABLE,
    ["Portfolio", "Product", "Activity", "SignoffGroup", "Category"],
)

# This validator copies only the small Portfolio mapping supplied here.
# Confirm the imported module belongs to the application folder before calling it.
from pathlib import Path
import cube.domain.s07_governance as portfolio_governance_module

portfolio_governance_path = Path(portfolio_governance_module.__file__).resolve()
portfolio_expected_governance_path = (
    Path(APP_ROOT) / "cube" / "domain" / "s07_governance.py"
).resolve()
if portfolio_governance_path != portfolio_expected_governance_path:
    raise RuntimeError(
        "The notebook imported a different application copy. "
        "Do not call its validator or continue with a misleading result."
    )
portfolio_checked_config = portfolio_governance_module.load_config(portfolio_config_frame)
print({
    "mapping_rows": len(portfolio_checked_config),
    "unique_portfolios": int(portfolio_checked_config["Portfolio"].nunique()),
    "subcategory_unspecified": int(
        portfolio_checked_config["Sub Category"].eq("Unspecified").sum()
    ),
})
```

7. The cell uses the `APP_ROOT` established at the start of this guide. If the module is unavailable, or its path differs, stop this optional cell and use the matching source plus Statics. Do not import a second app, rewrite `sys.path`, reload live modules or interpret a result from another application copy. Correct the notebook's normal startup environment separately before rerunning a live-data check.

**Expected:** the existing validator accepts the mapping; row count equals unique Portfolio count. Repeated Category/Sub Category labels across different portfolios are normal. They are groups, not join keys.

**If failed:** correct the authoritative mapping row or its connector rename. Keep the validator. Do not apply `drop_duplicates("Portfolio")` and choose whichever conflicting row happens to be first. Do not join positions to configuration on Category, Sub Category, Product or Underlying: those values are shared by many books and can multiply rows.

### Data step 5 — Distinguish unmapped books from a broken filter

1. Open `cube/services/s02_state.py` and find `_release_pl_views`.
2. Follow `_merge_validated_config` in `cube/domain/s07_governance.py`. It left-joins on `Portfolio` with `validate="many_to_one"`; missing matches receive `Portfolio Mapped=False` and metadata `Unmapped`.
3. Return to `_release_pl_views`. Confirm that `combined_pl` retains enriched rows, `unmapped_frame` retains unmapped rows, and only mapped rows enter `dashboard_frame`.
4. Use the existing unmapped/warning display to identify a missing book before blaming the new picker. Compare the mapping's effective date with the data date.
5. If `portfolio_checked_config` and `portfolio_frame` are available from the same revision/date context, run this narrow consistency check. It prints counts, not Portfolio names.

```python
portfolio_released_names = pd.Index(portfolio_frame["portfolio"].dropna().unique())
portfolio_configured_names = pd.Index(portfolio_checked_config["Portfolio"])
print({
    "released_portfolios_absent_from_mapping": int(
        (~portfolio_released_names.isin(portfolio_configured_names)).sum()
    ),
    "configured_portfolios_without_released_positions": int(
        (~portfolio_configured_names.isin(portfolio_released_names)).sum()
    ),
})
del portfolio_released_names, portfolio_configured_names
```

**Expected:** zero released portfolios absent from the same mapping. Configured books without released positions can be legitimate. This check cannot detect all unmapped source books because they are absent from the prepared dashboard by design; inspect the existing unmapped output as well.

**If failed:** resolve date/revision mismatches first, then the missing mapping. Reintroducing a Portfolio control does not, by itself, change which unmapped books are released. Do not silently expose unmapped positions by deleting the mapped-row selection; that would change existing financial scope and Product classification.

### Data step 6 — Preserve position grain and quote grain

1. Open `cube/domain/s02_products.py` and find `ProductSpec.market_keys`.
2. Confirm the market identity is `Risk Type`, `Risk Greek`, raw `Underlying`, followed by that product's declared tenor axes. Portfolio, Product, Category and Sub Category are not quote keys.
3. Open `cube/domain/s03_calculations.py` and find `get_product_risk`. Its ordinary product position identity includes the market keys plus `Portfolio`, and also `Region` when supplied for Credit. A repeated quote key across different portfolios is expected; a repeated full ordinary position key is rejected.
4. In the same file, find `get_product_pl`. Keep the Risk-to-MarketBook left join with `validate="many_to_one"`. Confirm no proposed Portfolio UI change adds Portfolio to that join or merges each quote with all configured books.
5. Find `_merge_validated_config`. Keep its separate many-to-one mapping join on Portfolio. Immediately around this mapping join, row count should remain unchanged. It attaches metadata; it does not create positions.
6. Keep the complete MarketBook, including market-only tenors. Filtering positions by Portfolio must not delete other quotes from the manager's MarketBook or change bulk market request identity into a Portfolio request.

**Expected:** filtering/grouping changes displayed scope only. Two books holding the same quote can show separate Risk/PL, while the quote's Open and Current remain the same single authoritative values. Risk 10 and 20 can total 30 within the same units; two positions sharing Open 3 and Current 4 do not make Open 6 and Current 8.

**If failed:** stop the Portfolio change at the data boundary. Repair the exact incorrect join or duplicate market authority. Do not remove `validate=`, globally deduplicate positions, shrink the MarketBook to the selected book, average quotes over position rows or create every Portfolio/Underlying/tenor combination. A metadata filter should not require a second connector pipeline.

### Data step 7 — Include supplemental positions in the same Portfolio scope

1. Open `cube/domain/s03_calculations.py::get_product_pl` and inspect Gamma development. Derived Delta rows preserve the source Portfolio; they intentionally add calculated exposure rows when market is available. Their `Split` is `Gamma`, their dRisk is unavailable and their PL is zero because Taylor PL stays on the sourced Gamma row.
2. Open `cube/domain/s04_crossgamma.py::build_cross_gamma_rows`. Confirm Portfolio is preserved in source sensitivities and in the grouping of developed output contributions. Do not drop it when aggregating contributions from multiple input cells.
3. Open `cube/domain/s05_newtrades.py`. Confirm the source blotter already has `Portfolio`, and both MARKET and CASHFLOW rows retain their own Portfolio through the existing release path.
4. Return to `cube/services/s02_state.py::_release_pl_views`. Confirm ordinary product PL and supplemental overlay frames receive the same authoritative Portfolio mapping before dashboard release.
5. In the current browser, note a narrow known example from each enabled Split: Risk, New Trades, Gamma and XGAMMA. Record the book and the financial amount privately for comparison when the control is later added. Include an example where multiple input cells contribute to one developed output.

**Expected:** the eventual Portfolio filter applies to every released split using that split's actual Portfolio identity. Derived exposures and supplemental rows explain legitimate differences between raw connector row count and released dashboard row count.

**If failed:** repair the missing Portfolio projection in that specific supplemental path. Do not treat every increase in released rows as a Portfolio multiplication defect, apply the ordinary product duplicate-key rule to the entire combined release, or suppress Gamma/New Trades/XGAMMA to make totals appear to match.

### Data step 8 — Record a financial baseline without adding unlike units

1. Keep all existing controls unchanged and record one current narrow scope for each product/Greek/split you actually use. Select one known Risk Type, one Risk Greek and one **raw Underlying**. Include the existing Product partition when comparing exposure and Hedges. Do not use a reported identity that combines several raw underlyings for this baseline.
2. Record parent Risk, dRisk and PL together with any unavailable-value indicators. Also record the selected quote's Open, Current and tenor identity from the existing quote detail.
3. In the cell below, replace the three quoted selection placeholders with exact existing values. Keep the tenor filter dictionary empty initially. If the chosen scope exceeds 5,000 rows, add one exact `tenor swap` and, for a surface when needed, `tenor option` value from the existing detail view. The 5,000-row guard bounds this temporary diagnostic projection only; it does not limit app data or hide portfolios.
4. Run the cell after confirming that `portfolio_frame` belongs to the recorded revision. It copies only the selected key and metric columns, then reports amounts separately for the available tenor axes, split and Product. It does not aggregate across raw underlyings or sum quote values. Missing inputs are counted; a sum with missing inputs is reported as unavailable rather than a complete amount. If your feed expresses a metric in different units or currencies even within this exact identity, resolve the established unit/conversion rule first; this cell introduces no conversion.

```python
PORTFOLIO_BASELINE_RISK_TYPE = "REPLACE_WITH_EXACT_RISK_TYPE"
PORTFOLIO_BASELINE_RISK_GREEK = "REPLACE_WITH_EXACT_RISK_GREEK"
PORTFOLIO_BASELINE_UNDERLYING = "REPLACE_WITH_EXACT_RAW_UNDERLYING"
PORTFOLIO_BASELINE_TENOR_FILTERS = {}
# Optional narrow selection, using exact values already visible in the app:
# PORTFOLIO_BASELINE_TENOR_FILTERS = {"tenor swap": "EXACT_EXISTING_LABEL"}

portfolio_baseline_selection = {
    "risk type": PORTFOLIO_BASELINE_RISK_TYPE,
    "risk greek": PORTFOLIO_BASELINE_RISK_GREEK,
    "underlying": PORTFOLIO_BASELINE_UNDERLYING,
}
portfolio_baseline_axes = [
    column for column in ("tenor swap", "tenor option")
    if column in portfolio_frame.columns
]
if set(PORTFOLIO_BASELINE_TENOR_FILTERS) - set(portfolio_baseline_axes):
    raise RuntimeError("A tenor filter names an axis absent from this prepared frame.")
portfolio_baseline_selection.update(PORTFOLIO_BASELINE_TENOR_FILTERS)
portfolio_baseline_mask = pd.Series(True, index=portfolio_frame.index)
for portfolio_column, portfolio_value in portfolio_baseline_selection.items():
    if portfolio_column not in portfolio_frame:
        raise RuntimeError(f"The prepared frame is missing {portfolio_column!r}.")
    portfolio_baseline_mask &= portfolio_frame[portfolio_column].eq(portfolio_value).fillna(False)
portfolio_baseline_selected_rows = int(portfolio_baseline_mask.sum())
if portfolio_baseline_selected_rows == 0:
    raise RuntimeError("No positions match. Correct the exact selection; do not broaden it silently.")
if portfolio_baseline_selected_rows > 5000:
    raise RuntimeError(
        "More than 5,000 rows match this diagnostic scope. "
        "Select an exact tenor using PORTFOLIO_BASELINE_TENOR_FILTERS and rerun."
    )

portfolio_baseline_keys = [
    "risk type", "risk greek", "underlying", *portfolio_baseline_axes,
    "split", "product",
]
portfolio_metrics = ["risk", "drisk", "pl"]
portfolio_baseline_projection = portfolio_frame.loc[
    portfolio_baseline_mask, [*portfolio_baseline_keys, *portfolio_metrics]
].copy()
portfolio_baseline_groups = portfolio_baseline_projection.groupby(
    portfolio_baseline_keys, observed=True, sort=False, dropna=False
)
portfolio_baseline_rows = portfolio_baseline_groups.size()
portfolio_baseline_counts = portfolio_baseline_groups[portfolio_metrics].count()
portfolio_baseline_sums = portfolio_baseline_groups[portfolio_metrics].sum(min_count=1)
portfolio_baseline_missing = portfolio_baseline_counts.rsub(
    portfolio_baseline_rows, axis="index"
)
portfolio_baseline_sums = portfolio_baseline_sums.mask(portfolio_baseline_missing.gt(0))
print("First 12 financial groups within the exact selected identity:")
print(portfolio_baseline_sums.head(12).to_string())
print("Missing input counts for those groups:")
print(portfolio_baseline_missing.head(12).to_string())
print({"financial_groups": len(portfolio_baseline_rows),
       "position_rows": int(portfolio_baseline_rows.sum())})
del portfolio_baseline_groups, portfolio_baseline_counts
del portfolio_baseline_projection, portfolio_baseline_mask
```

5. Keep the small `portfolio_baseline_sums`, `portfolio_baseline_missing` and `portfolio_baseline_rows` summaries, the exact `portfolio_baseline_selection`, and the recorded revision/date for the later comparison. The row count printed here is the selected identity's count, not the entire book's. Do not compare it with a newer financial refresh and attribute genuine market changes to the UI. Repeat a separate narrow baseline for another raw Underlying; do not add the two unless the established financial logic explicitly converts them to compatible units.

**Expected:** hierarchy presentation does not change the complete selected scope's amounts or missing-input state. Clearing an eventual Portfolio filter returns to the same complete scope. Selecting two portfolios should reconcile to their parent for the same metric units, with existing unavailable-value rules preserved.

**If failed:** identify whether the first disagreement is scope filtering, duplicate row creation, missing-data handling, Product partitioning or display aggregation. The current dashboard boundary has its own metric normalization, so this prepared-frame summary describes the published UI data only; it does not prove source-level market completeness. Do not treat dashboard zero normalization as proof that unavailable raw quotes became valid. Keep the raw MarketBook availability fields and existing financial rules.

### Data step 9 — Record the result before proceeding

1. Record whether Portfolio exists exactly once in the prepared frame.
2. Record the loaded position-row count, distinct released Portfolio count, known unmapped books and mapping date.
3. Record whether configuration uniqueness, metadata consistency and the two many-to-one joins are intact.
4. Record whether all enabled supplemental splits preserve Portfolio and whether the financial baseline is available for the same revision.
5. Mark each item **observed**, **failed** or **not observed**. A source-only inspection is useful evidence of intended behavior, but it does not establish what happened in a different running JupyterHub process.

**Ready for the UI/cache checks:** the data already owns Portfolio at position grain and the existing financial scope is understood. Keep that pipeline. The next changes should connect the existing field to filter, view and state handling; they should not recreate the positions for every Portfolio.

<a id="portfolio-filters"></a>

## Chapter 3 — Check the filter contract and every consumer

This chapter is a preflight. It does not add a dropdown or change financial data. Use the actual application files in `APP_ROOT`; the files running in your notebook environment may already differ from the inspected source. A check of source text establishes what is written on disk. It does not establish which process is serving the browser.

### F1. Record what is already registered

1. Keep the existing application running normally. Do not create a second app, refresh manager, or copy of the Risk snapshot for this inspection.
2. In the notebook, use the `APP_ROOT` directory selected in the opening steps of this document. Run the following read-only helper cell. It reads Python source without importing the application.

```python
import ast
from pathlib import Path

APP_ROOT = Path(APP_ROOT).expanduser().resolve()
if not (APP_ROOT / "cube").is_dir():
    raise ValueError("APP_ROOT must contain the application's cube directory")

def portfolio_source_matches(relative_path, needles, context=3):
    path = APP_ROOT / relative_path
    if not path.is_file():
        print(f"MISSING: {relative_path}")
        return
    source = path.read_text(encoding="utf-8-sig")
    ast.parse(source, filename=str(path))
    lines = source.splitlines()
    selected = set()
    for index, line in enumerate(lines):
        if any(needle in line for needle in needles):
            selected.update(range(max(0, index - context),
                                  min(len(lines), index + context + 1)))
    print(f"\n{relative_path}")
    if not selected:
        print("No matching source text; inspect the equivalent implementation.")
        return
    previous = -2
    for index in sorted(selected):
        if index != previous + 1:
            print("...")
        print(f"{index + 1:4}: {lines[index]}")
        previous = index

portfolio_source_matches(
    "cube/domain/s01_schema.py",
    ["PORTFOLIO_COLUMN =", "PORTFOLIO_FIELDS =", '"Product",',
     '"Activity",', '"SignoffGroup",', '"Category",', '"Sub Category",'],
    context=6,
)
portfolio_source_matches(
    "cube/ui/s01_constants.py",
    ["PORTFOLIO_UI_FIELD =", "VIEW_DIMENSION_FIELDS =",
     "FILTER_DIMENSION_ORDER =", "FILTER_DIMENSION_FIELDS =",
     "RISK_FILTER_DIMENSION_FIELDS =", "FILTER_COLUMNS =",
     "DIMENSION_FILTER_IDS =", "VIEW_DIMENSIONS ="],
    context=5,
)
```

3. Record the names exactly. The inspected source has this contract:

| Meaning | External data column | Internal UI key | Current Risk status |
|---|---|---|---|
| Book identity | `Portfolio` | `portfolio` | Retained in position data; excluded from Risk's filter and grouping registries |
| XVA/Hedges classification | `Product` | `product` | Grouping dimension; a governed XVA/Hedges classification |
| Activity classification | `Activity` | `activity` | Filter and grouping dimension |
| Signoff classification | `SignoffGroup` | `signoffgroup` | Filter and grouping dimension |
| Category classification | `Category` | `category` | Filter and grouping dimension |
| Subcategory classification | `Sub Category` | `subcategory` | Filter and grouping dimension |

4. Check whether your current `RISK_FILTER_DIMENSION_FIELDS` still contains `if field.key != "portfolio"`. If it does, the absence of the Risk dropdown is deliberate in that version. A Portfolio field in the shared `FILTER_DIMENSION_FIELDS` does not by itself mean Risk exposes it.
5. Check whether `VIEW_DIMENSION_FIELDS` contains Portfolio. The inspected source derives this tuple from `PORTFOLIO_FIELDS`, which contains reporting metadata and does not include the separate Portfolio identity field. Adding Portfolio as a filter and adding it as a grouping choice are two separate changes.
6. Record one of these outcomes in your notes: `Risk filter absent`, `Risk filter already present`, or `registry differs; trace the local equivalent`. Do the same separately for `Portfolio grouping`.
7. If the source differs, follow its actual definitions through the later checks. Do not replace the file with the inspected version.

**Keep:** the separate `Portfolio` identity; existing Product values `XVA` and `Hedges`; existing Activity, SignoffGroup, Category and Sub Category fields. Do not add a second `Portfolio` entry to the business metadata schema merely to obtain another UI choice. Do not rename `Sub Category` to `Subcategory` in stored data.

### F2. Check that one ordered filter registry reaches every consumer

1. Inspect the following source locations with the helper:

```python
portfolio_source_matches(
    "cube/pages/risk/s01_common.py",
    ["RISK_SAVED_VIEW_CONTROLS =", "def reporting_filter_map",
     "def quick_risk_filter_map", "RISK_FILTER_DIMENSION_FIELDS"],
    context=6,
)
portfolio_source_matches(
    "cube/pages/risk/s03_defaults.py",
    ["def default_risk_filter_values", "def default_risk_filter_payload",
     "RISK_FILTER_DIMENSION_FIELDS"],
    context=7,
)
portfolio_source_matches(
    "cube/pages/risk/s16_view.py",
    ["initial_filter_values =", "dimension_filter_controls =",
     "RISK_FILTER_DIMENSION_FIELDS", 'id="dimension-filter-values-store"',
     'id="risk-filter-exclude-applied-store"'],
    context=8,
)
portfolio_source_matches(
    "cube/pages/risk/s17_callbacks.py",
    ["dimension_filter_ids =", "RISK_FILTER_DIMENSION_FIELDS"],
    context=5,
)
portfolio_source_matches(
    "cube/pages/risk/s07_explorer.py",
    ["def sync_dimension_filters", "def update_dimension_filters",
     "dimension_filter_ids", "RISK_FILTER_DIMENSION_FIELDS",
     'Output("dimension-filter-values-store"',
     'Output("risk-filter-exclude-applied-store"'],
    context=5,
)
```

2. Write down the current Risk field order. In the inspected version it is `activity`, `signoffgroup`, `category`, `subcategory`. The shared five-field order is `activity`, `signoffgroup`, `portfolio`, `category`, `subcategory`.
3. Verify that dropdown generation, default values, saved-view controls, callback arguments, and `reporting_filter_map` all derive their order from the same Risk registry. The `dimension-filter-values-store` is a list of lists in this order, not a dictionary and not a list of field names.
4. Check every local edit for a fixed four-item list, an unpacking statement with four values, or a positional slice that assumes Portfolio is absent. Read the nearby source; a literal number elsewhere is not automatically an error.
5. Record every place that would need to grow from four values to five when the filter is restored. An empty Portfolio selection should be `[]`. It should not be omitted from the positional store once Portfolio is a registered Risk field.
6. Check the default helper. Portfolio should start unrestricted while the existing Activity 1–3 default remains intact. The label `Default - Activities 1-3` describes an Activity restriction; it does not mean that the whole application is unfiltered.
7. If any producer or consumer has a different order or length, mark the Portfolio filter as **not ready to expose**. Reconcile that single registry path as part of implementation before adding the control to the visible layout.

**Expected:** a single generated filter path, with matching names, lengths and order. A future fifth selector must not shift Category selections into Portfolio or Sub Category selections into Category.

**Keep:** `zip(..., strict=True)` guards, the existing default resolver, and the typed mapping helpers. A mismatch is useful evidence; deleting the strict guard hides a broken scope.

### F3. Check Apply, Cancel and saved-view behaviour before changing shared controls

1. Inspect `register_saved_filter_view_callbacks` in `cube/ui/s03_filters.py`, specifically `page_view`, `repository_filters`, `stage_saved_view`, and `commit_filter_draft`.
2. Inspect `sync_dimension_filters` in `cube/pages/risk/s07_explorer.py`. It should publish the committed filter state to `dimension-filter-values-store` and `risk-filter-exclude-applied-store`. Expensive Risk consumers should read these applied stores, as your current workflow intends.
3. Open Risk's existing Saved views section. Without saving or updating a named view, change an existing Activity or Category selection. Observe whether the table changes before Apply. In the inspected design, editing creates a draft; Apply activates it and Cancel restores the committed selection.
4. If your currently implemented controls change the table immediately, record that actual behaviour. Do not assume adding Portfolio will fix it. Decide whether your local Apply/Cancel implementation is complete before extending it.
5. Use the notebook helper to inspect the existing callback owners:

```python
portfolio_source_matches(
    "cube/ui/s03_filters.py",
    ["def page_view", "def repository_filters", "def stage_saved_view",
     "def commit_filter_draft", "Output(controls.committed_state_id",
     "Output(controls.apply_request_id"],
    context=10,
)
portfolio_source_matches(
    "cube/pages/risk/s07_explorer.py",
    ["def sync_dimension_filters", "def update_dimension_filters"],
    context=16,
)
portfolio_source_matches(
    "cube/app/s07_factory.py",
    ["SavedFilterViewRepository(", "FILTER_DIMENSION_FIELDS"],
    context=6,
)
```

6. Check the existing named-view contract. The shared repository already has a `portfolio` key because Stock and P&L use it. Currently, Risk's `page_view` projects a named view onto Risk's visible fields and can ignore that stored Portfolio selection. `repository_filters` preserves fields that another page owns when an existing view is updated.
7. Before restoring the Risk control, inspect a representative existing named view through the current read-only UI or existing repository object. Record whether it has a non-empty Portfolio selection. Do not call `save_new`, `update`, or `delete` for this inspection.
8. Record the consequence: after Portfolio becomes a Risk field, applying that same named view may narrow Risk to its previously stored Portfolio selection. This is expected scope becoming active, but the dropdown and applied-view summary must make it visible.
9. Do not delete or recreate named views to avoid this change. Do not clear Portfolio values from saved files. An older view with an empty Portfolio list should remain unrestricted on that dimension.
10. Check Stock and P&L after navigating away and back. Their live selections should remain their own page state. Sharing named view definitions does not require one page's current selection to overwrite another page's current selection.

**Expected:** one owner writes each applied store; one existing workflow stages and commits filter drafts. Portfolio should extend that workflow, rather than introducing an additional callback that competes to write the same values.

**If this fails:** identify the existing competing writer or stale positional payload first. Adding `allow_duplicate=True` solely to silence a duplicate-output error is not a resolution of callback ownership.

### F4. Check the meaning and spelling of filter values

1. Inspect `apply_filters` in `cube/ui/s02_aggregation.py`, `_filter_risk_positions` in `cube/domain/s10_search.py`, and `_apply_risk_filters` in `cube/history/s01_models.py`.
2. Confirm the intended semantics with one example: selecting Portfolio B and Portfolio D means `B OR D`. Selecting Category Credit at the same time means `(B OR D) AND Credit`.
3. Confirm Exclude mode separately: selecting Portfolio B and Category Credit removes rows belonging to B **or** Credit. It is not restricted to the overlap of B and Credit. Empty selections impose no restriction.
4. Keep Risk Type and Split as inclusion controls. The shared Exclude switch applies to Portfolio/reporting dimensions, not to every navigation control on the page.
5. Inspect the exact Portfolio identifiers already present in the committed data. Use the compact identity and mapping checks elsewhere in this document. Do not print all position rows.
6. Specifically look for blank IDs and IDs that differ only by surrounding spaces or letter case. In the inspected implementation, main Risk's `apply_filters` strips and case-folds selected values and frame values, while Quick Risk and history use exact membership. Therefore `Book A` and `book a` can produce inconsistent scopes if they are separate source identifiers.
7. If such collisions exist, record the original identifiers and identify their source authority. Do not automatically lowercase or merge them. Resolve the identifier contract at the existing normalization boundary, then ensure all consumers apply the same intended identity rule.
8. Inspect `prepare_risk_data` in `cube/ui/s02_aggregation.py`. It currently preserves a `portfolio` column and can fall back to `Unspecified` when it is missing. That fallback allows a display to exist; it does not prove that usable Portfolio identity survived the pipeline. If the expected 300–400 distinct books become one `Unspecified` value, stop the restoration until the lost identity is traced upstream.
9. Check the return-column list in that same function. It explicitly contains `"portfolio"` before `*VIEW_DIMENSIONS`. If later implementation adds Portfolio to `VIEW_DIMENSIONS`, that projection must still contain the column exactly once. The existing duplicate-input guard runs earlier and does not, by itself, protect against a duplicate introduced in this final projection.

**Expected:** the same selection identifies the same positions in main Risk, Quick Risk and Risk history. `portfolio` remains one column, with real book identity.

**Keep:** original identifiers, the existing null policy, and strict duplicate-column detection. Do not deduplicate position rows merely because several rows have the same Portfolio; a book legitimately contains many positions.

### F5. Check every Risk consumer and the Data handoff

1. Read the following path before implementing the filter:

| Consumer | Exact source location to inspect | Required scope after restoration |
|---|---|---|
| Main Risk hierarchy and detail | `cube/pages/risk/s07_explorer.py`: `reporting_filter_map` call sites and calls to `cache.filtered` | Applied Portfolio scope before totals, grouping and detail selection |
| Aggregate P&L on Risk | `cube/pages/risk/s14_workspacecallbacks.py`: `reduce_and_render_aggregate_pl` | Same applied reporting filters and Split selection; its broader Risk Type/IR-family policy remains explicit |
| Top Promotions | `cube/pages/risk/s14_workspacecallbacks.py`: `render_top_promotions` | Applied contributor scope while keeping the existing promotion-generation policy |
| Quick Risk dropdown | `cube/pages/risk/s14_workspacecallbacks.py`: `load_combine_udl_options` | Forward `quick_risk_filter_map` and `exclude_selected` to the search catalogue |
| Quick Risk displayed result | `cube/pages/risk/s14_workspacecallbacks.py`: `render_current_pivot` | Forward the same applied filters as its dropdown |
| Quick Risk → Data | `cube/pages/risk/s04_handoff.py`: `build_risk_filter_view`, `build_history_handoff`, `open_in_data` | Capture Portfolio using the external name `Portfolio` from the applied state |
| Archived Risk filtering | `cube/history/s01_models.py`: `RiskFilterView`, `_apply_risk_filters` | Retain the requested Portfolio scope and report a missing archive column clearly |
| Quick Market / Market history | Quick Market callbacks in `s14_workspacecallbacks.py`; market branch of `build_history_handoff` | Use quote identity; do not attach a Portfolio filter to quotes |

2. Use the source helper for a compact trace:

```python
portfolio_source_matches(
    "cube/pages/risk/s14_workspacecallbacks.py",
    ["def reduce_and_render_aggregate_pl", "def render_top_promotions",
     "def load_combine_udl_options", "def render_current_pivot",
     "quick_risk_filter_map(", "reporting_filter_map(",
     "risk_filters=", "exclude_selected="],
    context=5,
)
portfolio_source_matches(
    "cube/pages/risk/s04_handoff.py",
    ["def build_risk_filter_view", "def build_history_handoff",
     "field.external_name", 'if kind == "risk"',
     'State("dimension-filter-values-store"',
     'State("risk-filter-exclude-applied-store"'],
    context=7,
)
portfolio_source_matches(
    "cube/domain/s10_search.py",
    ["QUICK_RISK_FILTER_COLUMNS =", "def _filter_risk_positions"],
    context=13,
)
portfolio_source_matches(
    "cube/history/s01_models.py",
    ["class RiskFilterView", "def _apply_risk_filters",
     "Market history does not accept Portfolio/reporting filters"],
    context=9,
)
```

3. Record whether every Risk consumer receives the same applied scope. A dropdown that lists filtered identities but displays an unfiltered result is incomplete. A Risk chart filtered correctly while Aggregate P&L remains broad is also incomplete.
4. Check your updated Data request/reducer code for any list of allowed Risk filter names. It must preserve `Portfolio` when a Risk handoff supplies it. Do not invent a replacement callback from the older source if your Data implementation now has different functions.
5. Confirm that a Market-only Data request has no Portfolio filter. In a Both display, the Risk side can be scoped to selected portfolios while the Market side still uses unique underlying/tenor quotes. Selecting two books must not duplicate or average a quote twice.
6. Check archived Risk capability using existing archive metadata or a bounded previously loaded archive slice. A historical Portfolio filter requires that the relevant archived position data actually retains `Portfolio`. Adding a selector cannot reconstruct identity that was never stored. Missing history should remain an explained empty/unavailable result, not silently broaden to all portfolios.
7. Record the Portfolio scope and source date/revision in your comparison notes. Main Risk today and an archive from another date need not have equal numeric totals.

**Keep:** reported identity for Quick Risk, raw quote identity for Quick Market, exact tenor axes and authoritative tenor order, and the standalone Data selection workflow. Restoring Portfolio to Risk does not make Data depend on a Risk click.

### F6. Decide the unmapped-book behaviour explicitly

1. Inspect `render_unmapped_books` in `cube/pages/risk/s07_explorer.py` and `filter_unmapped_portfolios` in `cube/pages/risk/s02_state.py`.
2. Record the actual behaviour. In the inspected source, `render_unmapped_books` reads and displays the complete unmapped inventory when opened. The separate helper can filter it by Portfolio, but the callback does not call that helper.
3. Keep the complete diagnostic inventory during the initial Portfolio restoration unless you deliberately choose to make its scope follow Portfolio. An unmapped book has no reliable governed Category, Activity or SignoffGroup; applying those mapped-only dimensions can hide the very rows this section exists to reveal.
4. If Portfolio-scoped diagnostics are wanted later, write that as a separate small implementation job: use the applied Portfolio selection, forward Exclude mode, call the existing helper, and make the diagnostic scope visible. Do not apply all reporting filters to unmapped rows.
5. In either choice, ensure unmapped rows remain visible somewhere and retain the existing financial treatment of mapped versus unmapped totals. A new filter must not silently turn an unmapped book into a mapped one.

**Expected:** the diagnostic panel's scope is intentional and understandable. It is acceptable for a clearly labelled complete inventory to show more books than the filtered Risk table.

### F7. Record the later browser acceptance sequence without pretending the control exists today

Run the applicable existing-control checks now. If Risk has no Portfolio dropdown or Portfolio grouping choice yet, mark the corresponding action `pending implementation`; do not attempt to manufacture the state by editing browser storage. After the readiness checks in this document pass and the control is implemented, use this exact sequence:

1. Open Risk directly in a fresh browser session and explicitly choose the existing default view for this first check. Confirm the existing Activity default and an empty Portfolio selection. A deliberately restored named view may legitimately contain Portfolio values; check that separately in step 6. Confirm there is one Portfolio dropdown, not a duplicate created by two layouts.
2. Keep grouping unchanged. Choose one known Portfolio as a draft. Confirm the existing Apply/Cancel behaviour. Apply it and compare main Risk, detail, Quick Risk, and Aggregate P&L on the same source revision and comparable scope.
3. Select a second Portfolio and Apply. Confirm the union of the two books is used. Confirm existing Category/Activity restrictions still intersect that union.
4. Clear the Portfolio selection and Apply. Confirm it removes only the Portfolio restriction; it does not clear the Activity default or other selected dimensions.
5. Choose a Portfolio in Exclude mode and Apply. Confirm it is removed. Add a Category exclusion and confirm the union-removal rule described in F4.
6. Choose a named view that already stores Portfolio values. Confirm those values appear and become active only through the intended apply workflow. Cancel a subsequent draft and confirm the committed Portfolio selection returns. Use an existing view without updating or deleting it merely for this check.
7. Open Quick Risk for a known contributor and navigate to Data. Confirm the Risk request/breadcrumb or visible scope retains Portfolio. Choose Market, select the corresponding raw quote identity if requested, and Load. Confirm its quote series remains valid without Portfolio weighting; a reported Risk identity may correspond to several raw quote identities. Confirm opening Data directly still allows its own selection.
8. Only after the filter behaves correctly, select Portfolio as the Cross grouping dimension on a deliberately small scope. Expand and collapse one branch in Reduced and Full tenor modes independently. Include other layouts only when their Portfolio support was deliberately implemented and checked. Changing grouping alone should change categorisation, not the selected source positions or the additive total for the same scope.
9. Return to Product, Category and Sub Category grouping. Confirm those existing choices still work and that old expansion keys do not open an unrelated Portfolio branch.
10. Move to Stock and P&L. Confirm their existing Portfolio controls and independent live selections still behave as before. Changing a Risk display filter must not invoke a P&L send, adjustment-save or logging action.
11. Stop widening the scope if any functional mismatch appears. Record the page, action, applied values, source revision, visible message and affected callback before investigating. Do not compensate by deleting history, weakening validators or returning unfiltered data.

**Keep:** the existing app process, saved views, daily snapshots, adjustments and logging records. This sequence exercises display and selection only; it does not require sending financial data or changing saved business records.

<a id="portfolio-hierarchy"></a>

## Chapter 4 — Check the grouping path and construction safeguards

### H1 — Separate the proposed row grouping from the existing filter

Do these checks before adding a Portfolio option to the running Risk page. A filter chooses which positions contribute. A grouping changes how those selected positions are displayed. Adding Portfolio as a grouping does not require adding more positions or repeating the market feed.

1. Write down the first intended behavior: **Portfolio is an optional reporting dimension in Cross, alongside Product, Category and Sub Category.** Selecting it replaces the existing final reporting dimension; it does not insert 300–400 portfolios above every Underlying by default.
2. Keep the current default reporting dimension. Keep the existing Product, Category and Sub Category choices. Keep Portfolio as a retained position column throughout the pipeline.
3. Treat “Portfolio before Underlying” or “Category → Sub Category → Portfolio simultaneously” as a separate later layout change. Those change the hierarchy structure and its action keys. They are not needed to restore an optional Portfolio dimension.
4. Record the intended behavior in SplitVA separately. In that view the selected reporting dimension becomes **columns**, so 400 Portfolio values can mean about 400 metric columns for every visible row. A row limit does not control this width.
5. For the first implementation, plan to offer Portfolio grouping in Cross only. Keep Portfolio filtering available independently. Do not enable Portfolio in SplitVA until its column scope has an explicit bound and a clear message asking for a smaller Portfolio selection when needed. Do not silently choose the first few portfolios, combine the rest into an invented “Other” book, or change financial totals to fit the screen.

**Pass:** the intended first change is an optional Cross row grouping, and the wide SplitVA case cannot activate accidentally. **Hold:** the requirement is still “show every portfolio everywhere”. Decide the desired layout and bounded navigation before editing the grouping constants.

### H2 — Inspect every place that must recognize a Portfolio grouping

This is a source inspection now, not an instruction to add the field yet. The running notebook installation is the authority. A source file that was used to write instructions does not prove that the same change is in your running process.

1. Open `cube/domain/s01_schema.py`. Find `PORTFOLIO_COLUMN`, `PortfolioField` and `PORTFOLIO_FIELDS`. Confirm that Portfolio is the position identifier and Product, Activity, SignoffGroup, Category and Sub Category are metadata attached to that identifier. **Keep that distinction.** Do not add Portfolio again to the metadata mapping merely to get a new UI option.
2. Open `cube/ui/s01_constants.py`. Find `PORTFOLIO_UI_FIELD`, `VIEW_DIMENSION_FIELDS`, `VIEW_DIMENSIONS`, `DIMENSION_LABELS`, `BASE_GROUPS`, `BASE_GROUPS_NO_PROMOTION` and `ROW_KEY_COLUMNS`. Record how the current values are built. In the inspected source, Portfolio has a separate UI field with only the `filter_dimension` role, and the view dimensions derive from `PORTFOLIO_FIELDS`. Therefore adding a visible label alone does not make Portfolio a supported grouping.
3. In the same file, confirm how the chosen final dimension is represented. Both `BASE_GROUPS` lists currently end with `DEFAULT_VIEW_DIMENSION`; `ALT_GROUPS` derives from the base list without that final entry. A future optional dimension change must replace that final choice deliberately. Do not append Portfolio to every list or repeat it in both a base level and the selected dimension.
4. Open `cube/ui/s02_aggregation.py`. Find the final column selection returned by `prepare_risk_data`. In the inspected source it selects an explicit `"portfolio"` and later expands `*VIEW_DIMENSIONS`. If Portfolio is later added to `VIEW_DIMENSIONS`, that selection can produce **two columns with the same name**. Record this as a required companion change: remove only the redundant selection entry, or build a deliberately unique column list. Keep the actual Portfolio data and its normalization. Do not solve duplicate labels by dropping Portfolio from the frame.
5. In the same module, inspect `selected_dimension`, `dimension_title`, `row_key`, `parse_row_key`, `frame_for_context` and `tree_scope`. The new canonical key must be lowercase `"portfolio"`, and the same value must survive serialization, parsing and filtering. Keep the JSON key format and the allowed-column check. Do not encode a Portfolio row using only its visible label or a row number.
6. Open `cube/pages/risk/s16_view.py::build_layout`. Find `view_dimension_options` and the `table-dimension` control. In the inspected source it is a row of `dcc.RadioItems`; its options derive from `VIEW_DIMENSION_FIELDS`. Record where the future Portfolio choice will originate so it cannot exist in the label list but be rejected by `selected_dimension`.
7. Open `cube/pages/risk/s07_explorer.py`. Find `render_active_risk_table` and `reduce_and_render_risk_view`. Follow the `dimension` argument from the `table-dimension.value` input into the selected table builder. Confirm a dimension change participates in the existing view-state/reset rules. Keep a single existing callback owner for that state; do not add a second callback that competes to set the same open rows.
8. Open `cube/pages/risk/s06_explorertables.py`. Inspect `_active_groups_for_frame`, `build_risk_table`, `build_alt_risk_table` and `build_credit_multi_table`. Follow the actual `groups=` list passed to `build_tree_rows`, rather than assuming the `dimension` parameter is used because it appears in a signature. In the inspected source, `build_risk_table` accepts `dimension`, but `_active_groups_for_frame` does not accept it and gets a list ending in the default dimension. That is a specific wiring gap to check in your installed version before promising that a new Cross selector works.
9. Check Credit Multi separately. Its rows and measure columns use a different builder. Do not enable a new Portfolio choice in that view merely because the ordinary Cross builder has been updated.
10. In `cube/pages/risk/s02_state.py`, inspect `risk_action_view_token` and `_valid_delegated_row_key`. The current dimension is part of the action token. Portfolio row contexts must be accepted through the normal `ROW_KEY_COLUMNS` path, while actions from an old dimension or old data revision remain rejectable.

**Pass:** there is a written list of the exact definitions that need a companion change, with no duplicate frame columns and no ignored dimension argument. **Hold:** a Portfolio label would be added without tracing one of these paths. Keep the current grouping options until the missing path is understood.

#### Check unique prepared columns without printing positions

Run this ordinary Python cell only after the earlier data checks have bound `portfolio_frame` to the existing prepared dashboard frame. It reads that object; it does not construct another app or fetch another snapshot.

```python
duplicate_names = portfolio_frame.columns[
    portfolio_frame.columns.duplicated()
].tolist()
print("Duplicate column names:", duplicate_names)
print("Portfolio column count:", list(portfolio_frame.columns).count("portfolio"))
if duplicate_names:
    raise ValueError("Resolve duplicate prepared column names before grouping.")
if list(portfolio_frame.columns).count("portfolio") != 1:
    raise ValueError("The prepared frame must contain exactly one portfolio column.")
```

Expected result: no duplicate names and exactly one Portfolio column. If the check fails, return to the projection in step 4 and the data-contract checks. Do not weaken a groupby or select the first duplicate column to conceal it.

### H3 — Count actual Portfolio branches before asking the browser to build them

100,000 position rows and 400 portfolios do not automatically mean 40 million new rows. The input already contains the Portfolio on each position. The extra display cost depends on the distinct Portfolio branches within each scope, the number of branches you open, the number of columns, and the work retained in memory.

1. Use the same `portfolio_frame` already inspected. Do not concatenate a second copy per Portfolio, make a date/tenor/Portfolio Cartesian product, or create an index for every filter combination.
2. Run this small summary. It returns counts and an estimate of this DataFrame's retained memory, not financial values or a claim about total process memory.

```python
required = ["risk type", "risk greek", "portfolio"]
missing = [column for column in required if column not in portfolio_frame]
if missing:
    raise ValueError(f"Prepared frame missing required columns: {missing}")
print("Prepared position rows:", len(portfolio_frame))
print("Distinct portfolios:", portfolio_frame["portfolio"].nunique(dropna=False))
print(
    "Prepared frame MiB:",
    round(portfolio_frame.memory_usage(index=True, deep=True).sum() / 1024**2, 1),
)
counts_by_product = (
    portfolio_frame.groupby(
        ["risk type", "risk greek"], observed=True, dropna=False, sort=False
    )["portfolio"]
    .nunique(dropna=False)
)
print("Risk Type/Greek scopes:", len(counts_by_product))
print("Largest portfolio count in one Risk Type/Greek:", int(counts_by_product.max())
      if len(counts_by_product) else 0)
```

3. Choose one known small Risk Type, Greek and **raw** Underlying from the current page. Enter their exact values below. This is a diagnostic scope only; it does not modify the app's saved filters or remove positions from its data.

```python
chosen_risk_type = ""   # Enter one exact Risk Type from your own data.
chosen_risk_greek = ""  # Enter its exact Greek.
chosen_underlying = ""  # Enter one exact raw Underlying for that pair.
if not all([chosen_risk_type, chosen_risk_greek, chosen_underlying]):
    raise ValueError("Fill all three diagnostic selections before running.")
if "underlying" not in portfolio_frame:
    raise ValueError("Use the prepared position frame retaining raw Underlying.")
scope_mask = (
    portfolio_frame["risk type"].eq(chosen_risk_type)
    & portfolio_frame["risk greek"].eq(chosen_risk_greek)
    & portfolio_frame["underlying"].eq(chosen_underlying)
)
# Copy only key columns for compact counting; keep the source frame untouched.
key_columns = [
    column for column in (
        "risk greek", "display bucket", "region", "group",
        "reported underlying", "underlying", "tenor swap", "tenor option",
        "split", "product", "activity", "category", "subcategory", "portfolio",
    ) if column in portfolio_frame
]
scope_keys = portfolio_frame.loc[scope_mask, key_columns].copy()
if scope_keys.empty:
    raise ValueError("The chosen exact scope has no positions; correct the selection.")
print("Diagnostic position rows:", len(scope_keys))
print("Diagnostic portfolios:", scope_keys["portfolio"].nunique(dropna=False))
```

4. Before running the next cell, inspect `_active_groups_for_frame` as in H2 and copy the effective hierarchy order for the chosen settings. The example below uses Reported Underlying, promotion on and region on. Remove `"region"` when that level is off or unavailable; remove `"display bucket"` when promotion is off; substitute `"underlying"` for `"reported underlying"` for raw identity. The final `"portfolio"` represents the **proposed** optional terminal dimension. Do not include both identity levels if the actual selected mode uses only one.

```python
proposed_groups = [
    "risk greek", "display bucket", "region", "group",
    "reported underlying", "tenor swap", "tenor option", "split", "portfolio",
]
missing_groups = [column for column in proposed_groups if column not in scope_keys]
if missing_groups:
    raise ValueError(f"Match the effective hierarchy before counting: {missing_groups}")
if len(proposed_groups) != len(set(proposed_groups)):
    raise ValueError("A hierarchy column must not appear twice.")
prefix_counts = []
for stop in range(1, len(proposed_groups) + 1):
    prefix = proposed_groups[:stop]
    count = scope_keys.groupby(
        prefix, observed=True, dropna=False, sort=False
    ).ngroups
    prefix_counts.append((prefix[-1], int(count)))
print("Distinct source prefixes if every level were represented:", prefix_counts)
print("Sum of those prefix counts:", sum(count for _, count in prefix_counts))
parent_groups = proposed_groups[:-1]
fanout = scope_keys.groupby(
    parent_groups, observed=True, dropna=False, sort=False
)["portfolio"].nunique(dropna=False)
print("Largest Portfolio child count in this diagnostic scope:", int(fanout.max()))
```

5. Read these numbers as **source-prefix counts**, not an exact rendered-row forecast. `visible_tree_level` skips placeholder tenor levels and some repeated reporting levels. `tree_scope` applies promotion rules. Closed branches have no descendant rows in the rendered table. The cell deliberately does not build the table or expand everything to calculate an exact total.
6. Repeat the compact count with one larger relevant Underlying only if the first result is manageable. Do not begin browser work with the largest scope or all expanded branches. A high Portfolio child count under one parent tells you that one expansion alone may use a large part of the display budget.
7. The raw-Underlying selection above measures one contributor. A Reported Underlying can combine several raw Underlyings, so that first count can understate the full reported branch. If you intend to use reported mode, enter one known small reported identity below. The same Risk Type/Greek selection remains in force. Run this cell, then rerun the prefix-count cell in step 4 with the actual reported-mode hierarchy. This replaces only the small diagnostic key frame; it does not change the application's filters.

```python
chosen_reported_underlying = ""  # Enter one exact, known small reported identity.
if not chosen_reported_underlying:
    raise ValueError("Choose a reported identity before counting its whole scope.")
if "reported underlying" not in portfolio_frame:
    raise ValueError("The existing prepared frame has no reported identity column.")
scope_mask = (
    portfolio_frame["risk type"].eq(chosen_risk_type)
    & portfolio_frame["risk greek"].eq(chosen_risk_greek)
    & portfolio_frame["reported underlying"].eq(chosen_reported_underlying)
)
scope_keys = portfolio_frame.loc[scope_mask, key_columns].copy()
if scope_keys.empty:
    raise ValueError("No positions match that exact reported scope.")
print("Reported-scope position rows:", len(scope_keys))
print("Contributing raw Underlyings:", scope_keys["underlying"].nunique(dropna=False))
print("Reported-scope portfolios:", scope_keys["portfolio"].nunique(dropna=False))
```

Do not describe the earlier single-raw count as the complete reported branch. The actual applied Activity/Category/Portfolio restrictions can narrow it further; record which scope was counted.

**Pass:** you know both the full frame size and at least one real local branch's Portfolio count. **Hold:** a proposed path repeats Portfolio or creates combinations that never existed in the source. Correct the grouping design before any UI change.

### H4 — Confirm the memory and construction safeguards are actually active

These checks are prerequisites, even when earlier changes have already been applied. They concern work retained or sent to the browser; they do not reduce the permitted number of positions in the underlying data.

1. Open `cube/pages/risk/s07_explorer.py::render_active_risk_table`. Inspect the final Cross and SplitVA render calls. After the cache simplification they should use `cache.render_explorer(...)`. If they still call `cache.rendered(render_key, ...)`, record that the main Explorer is still retaining full component trees for different open states. Do not enable broad Portfolio grouping until that path is brought into line with the intended compact-index design.
2. Open `cube/pages/risk/s02_state.py::_RiskDataCache.render_explorer`. It should serialize a build with the existing render lock and return the result without inserting it into `_rendered`. **Keep** the lock. Do not remove every use of `rendered` globally: other consumers need separate review.
3. Inspect `_RiskDataCache.hierarchy_index` and the `HierarchyAggregationIndex` passed into `build_risk_table`. The reusable object should belong to the same filtered frame and revision, and opening another branch should not create a separately retained whole-table component tree. Credit's numeric measure transformation may need its own index key; keep it.
4. Inspect `_HIERARCHY_CACHE_MAX_ENTRIES`, `_HIERARCHY_CACHE_MAX_BYTES`, `_hierarchy_bytes`, and cache invalidation on revision change and Clear Cache. Confirm both an entry limit and estimated-byte limit are enforced when retaining indexes. A result too large to retain may still need memory while it is calculated. Therefore these constants alone cannot guarantee the app will fit its process limit.
5. Open `cube/ui/s02_aggregation.py::HierarchyAggregationIndex.memory_bytes`. Keep its accounting for the retained frame, sum arrays and quote indexes. Do not use DataFrame size alone as the total cost of the app: the active snapshot, filtered frames, indexes, temporary allocations and browser output all coexist.
6. Open `cube/pages/risk/s06_explorertables.py`. Find `_EXPLORER_TREE_ROW_LIMIT`, `_tree_limit_notice` and the `render_budget` argument to `build_tree_rows`. Confirm the guard runs **before constructing the next row**, rather than slicing `body_rows` after every component already exists.
7. Confirm each of `build_risk_table`, `build_alt_risk_table` and `build_credit_multi_table` creates one new local budget for each render, passes that same object into every descendant call, and includes the final `_tree_limit_notice` in its visible wrapper. A fresh budget per child is ineffective; a shared budget from the previous render can make new clicks appear broken.
8. Confirm the recursion remains inside `if can_expand and is_open`. Closed branches must not build all their Portfolio descendants and then hide them with CSS. Keep this rule when adding the extra grouping.
9. Confirm TOTAL and parent metrics still aggregate the **whole filtered frame**. Do not add `.head(...)`, a Portfolio count cap, or a tenor slice to the financial source to satisfy a row budget. The notice must disclose omitted display rows and tell the user to collapse branches or narrow filters.
10. Record the app process memory limit, number of app worker processes and current available headroom from the existing service/resource display. Each worker has its own retained caches. The notebook's memory display can describe a different process from the running web app, so identify which process it measures. Do not start another app merely to inspect it.
11. Keep the current measured limits for the first Portfolio change. Do not raise the row limit or index budget at the same time. A configured limit such as 1,999 tree rows plus TOTAL is an initial display choice, not proof that every browser can render that many rows with hundreds of columns.

**Pass:** Explorer does not retain a component tree per expansion state, indexes have bounded retention, closed children are not built, the shared row limit is active, and the app has understood memory headroom. **Hold:** any of those safeguards is absent, the active process cannot be identified, or the process is already near its limit. Keep grouping off and address that specific gap first. A Portfolio filter may still be considered separately after its own contract and callback checks pass.

### H5 — Resolve the cold Full-tenor expansion behavior before adding another hierarchy level

The existing symptom matters here: opening a branch in Reduced mode and then switching to Full proves that Full can render those children in that sequence. It does not prove that a fresh Full-mode click is received, accepted or rendered correctly. Adding Portfolio while that boundary is unexplained makes diagnosis harder.

1. Use one small existing Risk Type/Greek/Underlying selection. Keep Portfolio grouping absent. Record the current data revision, identity mode, promotion setting and region setting so the two sequences use the same scope.
2. In a fresh page session, choose Full before opening the Underlying. Open just the parents needed to reach it, then click its expand control once. Record whether the arrow changes and whether tenor rows appear.
3. In another fresh page session with the same scope, choose Reduced, open the same Underlying, then switch to Full. Record the same observations. Do not rapidly click repeatedly while a response is in flight.
4. If only the second sequence works, trace the existing action path in order: delegated browser row action → `reduce_and_render_risk_view` → `_valid_delegated_row_key` and current view-token validation → `effective_open_rows` → `build_tree_rows` → `visible_tree_level` and `render_budget`.
5. Distinguish four cases before editing anything: no action reaches the server; the action is rejected as stale or invalid; the valid key does not enter the effective open set; or the renderer receives the open key but skips children or reaches its budget. Save the relevant compact error/diagnostic observation for the failing boundary. Do not bypass stale-action validation or force every row open.
6. Check `row_key(next_context)` against the emitted `data-risk-key`, and retain the canonical serialized context. Check that the Full/Reduced setting changes the view generation consistently between rendered token and event validation. Check that the row budget is new for this render and has space for children.
7. If the same small Full branch still fails, stop the grouping rollout. Correct that specific action or rendering issue first. Do not use “open Reduced and switch” as the normal way Portfolio navigation is expected to work.
8. Once the cold Full sequence works, repeat it once after a collapse, once after switching away and back, and once after the next normal data refresh has completed. Use the ordinary refresh timing; do not trigger a burst of source loads.

**Pass:** a cold Full click and a cold Reduced click both open the same appropriate branch, and switching modes does not leave broken action keys. **Hold:** only the warm Reduced → Full sequence works. That is an existing hierarchy issue to resolve before introducing Portfolio grouping, not evidence that the dataset must be reduced.

### H6 — Check where Portfolio grouping could alter the displayed meaning

1. In `cube/ui/s02_aggregation.py`, inspect `_is_semantic_underlying`, `should_show_sum`, `hierarchical_market_value` and the quote index used by `HierarchyAggregationIndex`. Market quote keys must continue to exclude Portfolio. Keep the existing equal-child quote aggregation and the raw Underlying/tenor identity; repeated positions in different portfolios must not weight a quote more heavily.
2. Keep the first Portfolio grouping below the semantic Underlying and tenor branch as described in H1. The inspected `_is_semantic_underlying` treats a reporting-dimension context as a descendant. If Portfolio were moved above Underlying, merely adding it to `VIEW_DIMENSIONS` could cause market values to appear at a broad Portfolio parent where they previously remained blank. Do not make that structural move without updating and reviewing that display rule explicitly.
3. Keep Risk, dRisk and PL aggregation at position grain. Portfolio grouping partitions the same selected positions; it must not recalculate PL using Portfolio-averaged market values. Keep missing Open/Current values unavailable.
4. Inspect the detail click route in `s07_explorer.py::render_active_detail`. Confirm its `parse_row_key` → filtered frame → scoped detail path can carry a future Portfolio context. Otherwise a Portfolio row could show one book's number but open details for all books.
5. Inspect promotion and `tree_scope` behavior with both promoted and `Other` branches. Keep Portfolio as a subdivision of the existing filtered promotion result. Do not duplicate promoted positions under both the named exposure and `Other` just to make Portfolio visible.
6. Record any view where Portfolio cannot be supported yet, such as Credit Multi or SplitVA, and keep its Portfolio grouping option unavailable until its builder and click route are covered. Do not silently accept a selection that the renderer ignores.

**Pass:** grouping affects display subdivisions and scoped detail, while the market join, quote identity, PL calculation and promotion ownership stay consistent. **Hold:** Portfolio is proposed as a market key, a source-row multiplier, or an earlier parent without a reviewed market-display rule.

### H7 — Prepare the acceptance sequence for the later small implementation

The following actions are **after** a future minimal Portfolio implementation in a separate running copy or scheduled safe window. They are written now so the implementation has a clear acceptance target. They are not actions available before the new controls exist. Use the current source backup and normal app startup method; do not create a second refresh manager inside an already running app.

1. Start with Portfolio filtering only, while the existing reporting dimension remains selected. Follow the filter checks in this document. Record one known Risk Type/Greek/Underlying's current totals and a known quote. Do not enable grouping until the filter itself behaves correctly.
2. Select one Portfolio and the same small Underlying scope. Select Portfolio as the Cross reporting dimension. Open one path to its final grouping. Confirm one Portfolio child appears, with the appropriate scoped values and a detail click confined to that book.
3. Select two known portfolios that both have positions in that branch. Open that same path. Confirm distinct canonical row keys and separate children. Compare the parent with the same scope under the previous reporting dimension. The financial parent should represent the same positions; changing grouping alone cannot change the number.
4. Collapse the parent and reopen it once. Confirm the children disappear and return, with no duplicate labels or accumulated hidden descendants. Repeat once in cold Full mode and once in Reduced mode.
5. Change the reporting dimension from Portfolio to Product, then Category, then back to Portfolio. Confirm the final grouping actually changes. A stale row key must not open the wrong book or old dimension. Product, Category and Sub Category must remain usable.
6. Repeat with raw Underlying and Reported Underlying modes. Use one known many-raw-to-one-reported identity if available. The displayed parent can cover several raw identities, but the detailed quote must still use its correct raw keys.
7. Broaden to a small named set of portfolios, such as five, only when the previous steps are responsive and the app resource display remains within its available headroom. Expand one branch at a time. Record response behavior and resource readings after an expansion and after a collapse. Do not expect process memory to fall immediately after collapse; allocators and bounded caches may retain memory for reuse.
8. Only then consider one normal wider scope. Keep unrelated branches collapsed. Stop widening if the visible-row notice appears, responses slow materially, the worker restarts or available memory becomes small. Return to the previous usable scope. Do not raise the guard or open every branch to find a crash point.
9. Keep Portfolio grouping unavailable in SplitVA unless its explicit width guard is implemented. Keep ordinary SplitVA available with its existing supported dimensions. If Portfolio support is later added, begin with the same one- and two-portfolio selections. Reject or ask for narrower scope **before constructing columns** when the planned width limit would be exceeded. Choosing the single Portfolio dimension with 400 distinct books must not cause roughly 400 value columns to be built and then hidden or sliced.
10. Perform the Credit Multi sequence only if that builder was included in the future change. Otherwise keep the option unavailable there and record that limitation clearly.
11. End by returning to the ordinary default grouping and clearing the temporary Portfolio selection. Confirm the ordinary Risk page remains usable. If any acceptance item fails, restore only the future Portfolio UI/grouping change from its backup; keep the data-contract corrections, compact-index retention and visible-row safeguards already established.

**Ready for the minimal implementation:** H1–H6 pass and the later sequence has a small known dataset scope to use. **Ready for wider use:** the applicable H7 actions also pass on the actual running app. Neither status is a guarantee that arbitrary expansion of 100,000 positions across hundreds of books will fit every process or browser.

<a id="portfolio-measurement"></a>

## Chapter 5 — Measure the current app and plan bounded acceptance

This section adds no application feature. Record a baseline now, while the current controls and grouping choices are unchanged. The later Portfolio acceptance sequence is explicitly for after a separate, small implementation.

### M1. Identify the actual application process and memory allowance

1. Find the notebook cell or launcher that currently starts the application. Record the application folder and its launch method. Keep one running application instance.
2. Find the memory allowance shown by your JupyterHub resource display or supplied for your application session. Record whether that allowance covers the application alone or the whole notebook/session. If it is unknown, record **unknown**; do not substitute the computer's total installed memory.
3. If the launcher starts a subprocess and retains its process handle, read that existing handle's `.pid`. For example, `existing_process.pid` is appropriate only when `existing_process` is the actual variable in the launch cell. Do not paste that example name unless it exists. If the app runs inside the same notebook kernel, the notebook PID applies only after confirming that launch arrangement. A notebook supervising a separate server is not the server.
4. If the launcher uses several workers, record the parent and worker PIDs from that existing launcher/process display. Do not assume there is only one worker. Each worker may retain its own snapshots and caches.
5. The following optional ordinary Python cell reads Linux process metadata only. Replace the empty list with the exact application PIDs obtained above. It neither imports the app nor reads positions. On a host without `/proc`, use the existing resource display instead; there is no package to install for this check.

```python
from pathlib import Path
from datetime import datetime, timezone

PORTFOLIO_APP_PIDS = []  # Enter the known server/worker PIDs, for example [12345].

def portfolio_memory_reading(action_label):
    if not PORTFOLIO_APP_PIDS:
        print("No application PID supplied; use the existing resource display.")
        return
    print(datetime.now(timezone.utc).isoformat(), action_label)
    for pid in PORTFOLIO_APP_PIDS:
        if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
            raise ValueError("Each PID must be the actual positive application process ID")
        status_path = Path("/proc") / str(pid) / "status"
        try:
            status_text = status_path.read_text(encoding="utf-8")
        except (FileNotFoundError, PermissionError, OSError) as error:
            print(pid, "reading unavailable:", type(error).__name__)
            continue
        values = {}
        for line in status_text.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                values[key] = value.strip()
        def memory_mib(name):
            value = values.get(name, "").split()
            if len(value) == 2 and value[1] == "kB":
                return round(int(value[0]) / 1024, 1)
            return "unavailable"
        print({
            "pid": pid,
            "process": values.get("Name", "unavailable"),
            "resident_MiB": memory_mib("VmRSS"),
            "peak_since_process_start_MiB": memory_mib("VmHWM"),
            "threads": values.get("Threads", "unavailable"),
        })

portfolio_memory_reading("Current application, before interaction")
```

6. Record the result without interpreting unavailable readings as zero. Resident memory describes that process now. The peak is since process startup, not just the last click. Adding several processes' resident figures can count shared memory more than once; use the Hub/session display when assessing a shared allowance. Browser memory is separate again.
7. If the current application already approaches its allowance, has recently restarted unexpectedly, or has an out-of-memory message in its existing logs, hold the Portfolio hierarchy change. Identify the current allocation problem first. Increasing callback timeouts does not increase memory capacity.

**Ready to continue:** the application PID/worker arrangement is understood, a baseline is recorded, and there is a way to observe the relevant memory allowance. An unknown allowance means this check remains incomplete; it does not mean the feature will crash.

### M2. Record one ordinary interaction with the existing hierarchy

1. Keep one unchanged data revision, Risk Type, Greek, filter scope and display mode. Use an existing small Underlying branch. Do not expand the whole book to produce a baseline.
2. In a fresh browser session, choose Full first and open that Underlying once. It must open without first passing through Reduced. If the reported Full-mode failure remains, stop here and complete the click/state/render diagnosis before adding a new dimension. Portfolio would otherwise add a second variable to an unresolved interaction fault.
3. Record current resident/peak memory or the resource display, the approximate wait until the row finishes updating, and any visible row-limit notice. If using the cell above, call `portfolio_memory_reading("Small Full branch open")` after the action.
4. In the browser's developer tools, open Network before repeating that one click. Look only at the relevant `_dash-update-component` request: record status, duration and transferred/decoded response size when the browser exposes them. A response's network size is not its full Python or browser memory cost. Do not export the full response or its position data.
5. The following optional Console expression counts existing Risk table elements only. It does not expand a branch or modify the page. The counts include retained hidden rows if the implementation has them, which also occupy browser memory.

```javascript
(() => {
  const countTable = (selector) => {
    const container = document.querySelector(selector);
    if (!container) return { mounted: false };
    let rows = 0;
    let widestRow = 0;
    for (const row of container.querySelectorAll("tr")) {
      rows += 1;
      let cells = 0;
      for (const cell of row.cells) cells += cell.colSpan || 1;
      widestRow = Math.max(widestRow, cells);
    }
    return { mounted: true, rows, widest_row_including_colspans: widestRow };
  };
  return { main: countTable("#risk-grid"), alternative: countTable("#alt-risk-grid") };
})()
```

6. Collapse and reopen the same small branch a few times. Record whether the process memory settles into a bounded range and whether old rendered tables accumulate. Some memory remaining allocated after collapse is normal Python/browser reuse; an immediate return to the starting number is not required. Monotonically growing retained component versions need investigation.
7. Repeat the same small scope in Reduced. Compare the action path and response sizes. Reduced working successfully is not evidence that Full, an alternative layout or a wide pivot is safe.
8. Keep the resulting compact record: mode, applied scope, action, completion/error, row/column count, response size and process/Hub memory. No positions or complete DataFrames belong in this record.

**Ready to continue:** the existing cold Full and Reduced clicks work, each action returns without unexpected server restarts, and the current budget/cache behaviour is understood. If a narrow branch fails, do not proceed to a broader Portfolio experiment.

### M3. Plan gradual acceptance after the future implementation

These steps are a plan to use **after** the separate filter/grouping restoration. They do not instruct you to find a Portfolio grouping choice that has not been added yet.

1. Restore and verify the existing Portfolio filter path first. Begin with one known mapped Portfolio, one Risk Type and one small Underlying scope. A filter reduces the selected position population; it does not require grouping by Portfolio.
2. Only after filter behaviour and all preflight gates pass, expose Portfolio as an optional grouping choice in the existing dimension control. Keep the previous default. Start with Portfolio at the intended terminal position in the existing tree, not repeated before every Underlying and tenor by default.
3. Keep Portfolio grouping unavailable in SplitVA for this first grouping check unless its separate column-width check has passed. Keep ordinary SplitVA working with its existing dimensions. Confirm that choosing Portfolio reaches the Cross builder selected for this first rollout; verify alternative and Credit builders only if they are deliberately included in the supported scope.
4. Open one small branch. Confirm its labels, complete parent totals, exact Portfolio scope and quote values. Then collapse it and repeat from a cold Full view. Record the same measures as M2.
5. Increase the selection to a few Portfolios, for example five, while keeping the same other filters. Proceed only if the previous step behaved correctly and left acceptable headroom in the observed environment. Next consider another modest scope, such as twenty. These are convenient increments, not capacity guarantees or required limits.
6. Do not jump straight from one Portfolio to all 300–400 with every branch open. The important quantity is populated Portfolio–Underlying–tenor combinations and rendered cells, not the number of dropdown options alone. The source can contain 100k rows while its fully expanded display has a very different shape.
7. Stop expansion if the row-limit notice appears, the column count exceeds the agreed view policy, response size/latency becomes unacceptable, the browser becomes unresponsive, memory approaches the observed allowance, or a process restarts. Keep the notice and narrow the scope. Do not remove portfolios from source data, truncate positions, disable the budget, or raise a limit blindly to get past the symptom.
8. If the broad tree cannot fit, keep the Portfolio filter useful and require a narrower selection for the hierarchy. Add branch paging or column paging only when an observed, normal workflow needs it. A new grid/backend/cache service is not a prerequisite for restoring one existing dimension.
9. Repeat the narrow acceptance scope after removing temporary diagnostics. A successful syntax check or a successful one-Portfolio example alone is not proof that an unrestricted book will fit.

**Ready for broader use:** the filter is exact, the grouping reaches the intended builders, duplicate columns and keys are absent, financial totals and quote identity are preserved, and representative bounded scopes fit the actual environment. Record the largest scope actually observed to work; do not present an unmeasured maximum as supported capacity.

<a id="portfolio-readiness"></a>

## Chapter 6 — Complete the readiness record before implementing

### R1. Record the outcome of the checks

1. Copy this small table into your working notes. Fill in the observed result, evidence and the next action. Do not put whole datasets or confidential position lists into it.

| Check | Result to record | Where to resolve a failure |
|---|---|---|
| Active source/process | Correct launched folder, revision and process/worker arrangement | Chapter 1 and M1 |
| Existing Portfolio identity | Exactly one real position column, no unexplained identity collisions | Data steps 1–3; F4 |
| Mapping and unmapped scope | One effective mapping per Portfolio; missing books explained | Data steps 4–5; F6 |
| Financial grain | Many positions to one quote; metadata join does not multiply rows | Data steps 6–8 |
| Filter state | One ordered registry, matching positional stores, one applied-state owner | F1–F3 |
| Saved views and history | Previously stored Portfolio scope understood; Risk scope retained; Market independent | F3–F5 |
| Optional grouping | Chosen dimension actually reaches Cross; prepared columns and row keys stay unique | H1–H2 |
| Detail and quote meaning | Portfolio detail remains confined to that book; quotes are not position-weighted | H6 |
| Cold tenor expansion | Fresh Full and fresh Reduced clicks both work | H5 and M2 |
| Retained work | Compact bounded indexes; no retained Explorer tree per open-state combination | H4 |
| Render size | Closed children are not built; shared row budget and any required column bound apply before construction | H3–H4 |
| Environment headroom | Actual memory allowance and ordinary response/browser behaviour observed | M1–M2 |
| Later acceptance | One/two/few Portfolio scope chosen; unsupported layouts remain explicit | F7, H7 and M3 |

2. Mark the filter and grouping separately. It is possible for **the filter to be ready for a small implementation** while **grouping remains held** because the existing Full click or a rendering safeguard is unresolved.
3. A source-only check can identify exactly what implementation is missing. It cannot establish that the running browser processed the correct source, that a live provider returned the intended data, or that an unrestricted hierarchy fits in memory.
4. Resolve failed financial-scope checks before either UI change. Resolve the cold Full interaction and construction/width checks before exposing Portfolio grouping. If the memory allowance is unknown, keep capacity status unconfirmed and use only the current ordinary small-scope observations while obtaining that information.

### R2. Identify the later minimal implementation jobs

This is the implementation map to prepare after the checks. It deliberately contains no blind patch for unseen local source. Record the actual definitions and companion edits needed in your application before writing changes.

1. **Make a source backup immediately before that later change.** Back up only the files you will edit to a new dated folder, recording their paths and the preflight source identities. Keep this backup separate from financial archives. Do not overwrite it after applying the change.
2. **Restore the Risk filter through its existing field.** In `cube/ui/s01_constants.py`, reuse `PORTFOLIO_UI_FIELD` and the shared ordered registry. Remove only the Risk-specific exclusion when the related consumers are ready. Keep the business metadata schema unchanged. Follow the generated control, default, saved-view and callback paths in F2 so that every positional payload has the same field order.
3. **Preserve applied filter scope end to end.** Keep the existing Apply/Cancel owner and existing typed mapping helpers. Forward the applied Portfolio selection and Exclude flag through the Risk consumers identified in F5. Keep Market requests at quote grain. Handle a restored named view's existing Portfolio selection visibly; do not erase the saved value.
4. **Add the optional Cross grouping as one coordinated change.** Update the existing UI dimension registry, dimension selector, actual group-list construction, canonical key parsing and scoped detail path together. In `prepare_risk_data`, remove only a now-redundant selection entry so `portfolio` appears once. Keep Portfolio data, the current default, Product/Category/Sub Category and the existing financial aggregators.
5. **Keep unsupported layouts explicit.** Preserve ordinary SplitVA and Credit Multi. Do not allow their Portfolio grouping option to activate until their builder, detail route and relevant size bound are implemented. For a wide dimension, check the number of columns before creating them and ask for narrower scope when necessary; do not discard source rows or silently omit books.
6. **Keep the existing safeguards.** Reuse the bounded hierarchy index for its correct frame and measure scope, generate only open branches, and retain the shared row budget and its notice. Do not simultaneously raise memory limits, increase the row limit, change tenor reduction or alter the source connector. Those would make a regression difficult to attribute.
7. **Validate in the staged order already written.** Save the source, parse the changed Python files, restart the existing process with the normal launcher, verify the filter first, and then use one/two/few Portfolio Cross scopes. Record the largest actual scope checked rather than claiming that all 100k positions can be expanded.
8. **If an acceptance check fails, restore only that later source change.** Stop the app, restore the backed-up implementation files while preserving unrelated later work, parse them and restart. Keep financial data, saved views, history, adjustments and logging records. Preserve earlier verified data-contract and memory corrections.

The useful first outcome is a Portfolio filter that selects the right existing positions and a bounded optional grouping that shows them clearly. Neither requires duplicating the book, rebuilding the market feed per Portfolio, or replacing the application architecture.
