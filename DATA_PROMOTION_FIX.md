# Data and promotion: one step-by-step guide

This guide collects the smallest verified source changes for slow Data choices and repeated promotion work. It also gives the exact information needed to finish the Quick Risk / Quick Market prefill correction and identify the remaining 25-second delay.

Use the existing application files in JupyterHub. Keep the completed Portfolio work and the unified Risk / Market / Both page. The source and running browser in your JupyterHub have not been inspected directly; match the named functions before editing.

| Item | What is ready here |
| --- | --- |
| Slow preparation of available Data choices | Complete two-file implementation in steps 3–5 |
| Unnecessary promotion sums and copying | Complete implementation in steps 6–10 |
| View in Data no longer prefills | A reproduced initialization failure path; step 11 extracts the actual callback needed for an exact replacement. This guide does not yet contain that replacement. |
| Full reported 25-second wait | Steps 1 and 13 distinguish calculation/preparation from subsequent rendering. The full delay has not been reproduced, so the arithmetic changes are not a guaranteed complete fix. |

Implement the ready changes in order. They add no new cache, service, data limit or selection control. Faster catalogue preparation does not remove the full catalogue from browser callback requests. Keep current-plus-archive discovery and the existing current observation reader.

## 1. Record the promotion delay before changing code

1. In the running app, keep the same filters, data revision and Full/Reduced setting.
2. Click Recalculate and record the completion message ending in `... ms`, together with the approximate time until the page finishes redrawing.
3. Without changing filters, data or tenor mode, click Recalculate once more and record both times again. If a data refresh occurs between clicks, the comparison does not isolate cache reuse.
4. Save the two millisecond values and whether Reduced mode was enabled.

The displayed milliseconds include obtaining/filtering/reducing the frame, promotion calculation and publication. They exclude the subsequent Risk table redraw and browser layout. About `25,000 ms` points inside the former path; a small displayed duration with a long visible wait points to work around or after it, including callback queuing.

In Reduced mode, Recalculate requests all Risk types. Viewing reduced IR only prepares the IR-specific cache; the first all-Risk request can reduce the entire book separately, before Portfolio filtering. An unchanged second request can reuse that all-Risk result. Keep the selected tenor basis throughout these changes.

## 2. Save copies of the files you will edit

Stop the app process using your usual notebook or process control. Download copies of these five files using the JupyterHub file browser:

- `cube/domain/s10_search.py`
- `cube/services/s02_state.py`
- `cube/ui/s02_aggregation.py`
- `cube/pages/risk/s11_promotion.py`
- `cube/pages/risk/s02_state.py`

Only the named blocks below change. If the new block is already present, keep it once. If neither the original block nor its replacement matches your code, inspect the named function before attempting that edit. Do not replace whole modules with another version.

## 3. Add one bulk identity method to SearchCatalog

Open `cube/domain/s10_search.py`. Find `class SearchCatalog`, then its existing `def resolve_history_identity(` method.

Immediately before that existing method, add this complete method at the same indentation:

```python
    def history_identities(self) -> tuple[ResolvedHistoryIdentity, ...]:
        """List current Data choices using identity metadata only."""
        identities = []
        for kind, mode, frame, column in (
            ("risk", "reported", self._risk_pivot_frame, REPORTED_UNDERLYING),
            ("risk", "underlying", self._risk_pivot_frame, UNDERLYING),
            ("market", "underlying", self._market_frame, UNDERLYING),
        ):
            # These are dropdown identities, not position rows or market quotes.
            # Repeated identity metadata does not need repeated row validation.
            columns = [RISK_TYPE, RISK_GREEK, column, SOURCE_TYPE]
            metadata = frame.loc[:, columns].drop_duplicates()
            for name in columns:
                invalid = metadata[name].map(
                    lambda value: not isinstance(value, str) or not value.strip()
                )
                if invalid.any():
                    raise ValueError(f"history identity contains invalid {name!r}")
            grouped = {}
            for risk_type, greek, underlying, source in metadata.itertuples(
                index=False, name=None
            ):
                key = (risk_type.strip(), greek.strip(), underlying.strip())
                grouped.setdefault(key, {})[source.strip()] = None
            for (risk_type, greek, underlying), sources in grouped.items():
                source_types = tuple(sources)
                if kind == "market" and len(source_types) != 1:
                    raise ValueError(
                        "exact Market history identity resolves to multiple Source Types"
                    )
                identities.append(ResolvedHistoryIdentity(
                    kind=kind,
                    source_types=source_types,
                    risk_type=risk_type,
                    risk_greek=greek,
                    underlying=underlying,
                    identity_mode=mode,
                    source_revision=self.revision,
                    snapshot_date=self.market_date,
                ))
        return tuple(identities)
```

Keep `resolve_history_identity` and its whole body unchanged: the Quick controls still use it to resolve the selected identity. All names used by the new method already exist in this module; add no imports.

The old Data discovery loop selects and checks position/quote rows separately for each dropdown identity. This method reads only four identity columns together. Removing repeated metadata here does not delete positions or quotes. Risk retains its reported/raw identities and permitted source combinations; Market retains its single-source rule.

## 4. Replace the manager's per-identity discovery loop

Open `cube/services/s02_state.py`. Find the complete method beginning `def data_history_identities(`.

Remove that entire method, stopping before the next method definition. Replace it with:

```python
    def data_history_identities(self) -> tuple[ResolvedHistoryIdentity, ...]:
        """Read current Data choices from the committed search catalog."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            return ()
        return catalog.history_identities()
```

Keep `read_data_history` and all other methods unchanged. Keep the Data callbacks that merge current identities with archive identities and load current observations. This optimisation requires no changes to the Both picker, its keys or its callback registrations.

## 5. Save, check syntax and inspect Data choices

Save both edited files. In a Python notebook whose working directory contains the `cube` folder, run:

```python
import ast
from pathlib import Path

for filename in (
    "cube/domain/s10_search.py",
    "cube/services/s02_state.py",
):
    ast.parse(Path(filename).read_text(encoding="utf-8-sig"), filename=filename)
    print("Syntax OK:", filename)
```

Correct any reported syntax or indentation error. Restart using your usual launcher and reload the browser.

1. Open Data directly. Allow the initial financial refresh to finish if the app has just started.
2. Confirm that current Risk and Market choices appear, including an identity with no archive observations.
3. Confirm that an archive-only identity remains available when the archive contains one.
4. Select Both and confirm the primary and companion controls still work.
5. Load a known identity and check its caption and current observation.

The choices should be the same. This change speeds up their preparation; a slow catalogue transfer, archive access or lost Quick selection may still need its separate correction below.

Stop the running app again before proceeding with the promotion edits.

## 6. Replace the first promotion aggregation

Open `cube/ui/s02_aggregation.py`. Find `def recompute_filtered_promotion(`.

Inside it, find this entire assignment:

```python
    summary = base.groupby(
        PROMOTION_KEYS,
        as_index=False,
        dropna=False,
        sort=False,
    ).agg(
        {
            "risk": lambda values: values.sum(min_count=1),
            "drisk": lambda values: values.sum(min_count=1),
            "pl": lambda values: values.sum(min_count=1),
            "risk threshold": "first",
            "drisk threshold": "first",
            "pl threshold": "first",
        }
    )
```

Remove only that assignment and replace it with:

```python
    grouped = base.groupby(
        PROMOTION_KEYS,
        dropna=False,
        sort=False,
        observed=True,
    )
    summary = pd.concat(
        [
            grouped[["risk", "drisk", "pl"]].sum(min_count=1),
            grouped[["risk threshold", "drisk threshold", "pl threshold"]].first(),
        ],
        axis=1,
    ).reset_index()
```

Keep everything before it and everything starting with `risk_ratio = ...` afterward. In particular, keep promotion reasons, pinned underlyings, the merge and `validate="many_to_one"`.

`sum(min_count=1)` preserves wholly missing amounts. Thresholds use `first()` because the same threshold is repeated on position rows and must not be summed. `observed=True` avoids unused combinations when grouping keys are categorical.

## 7. Replace the second promotion aggregation

Open `cube/pages/risk/s11_promotion.py`. Find `def _summary(`.

Remove that complete function, stopping immediately before `def _rows_from_summary(`. Insert this complete replacement at the same top-level indentation:

```python
def _summary(classified: pd.DataFrame) -> pd.DataFrame:
    required = set(
        (*PROMOTION_KEYS, *PROMOTION_VALUE_COLUMNS, *PROMOTION_CLASSIFICATION_COLUMNS)
    )
    missing = sorted(required - set(classified))
    if missing:
        raise ValueError("Promotion source is missing columns: " + ", ".join(missing))
    if classified.empty:
        return classified.reindex(
            columns=[
                *PROMOTION_KEYS,
                *PROMOTION_VALUE_COLUMNS,
                *PROMOTION_CLASSIFICATION_COLUMNS,
            ]
        )
    grouped = classified.groupby(
        list(PROMOTION_KEYS), dropna=False, observed=True
    )
    consistency = grouped[list(PROMOTION_CLASSIFICATION_COLUMNS)].nunique(
        dropna=False
    )
    if consistency.gt(1).any().any():
        raise ValueError("Promotion source has inconsistent baseline classifications")
    return (
        pd.concat(
            [
                grouped[["risk", "drisk", "pl"]].sum(min_count=1),
                grouped[
                    [
                        "risk threshold", "drisk threshold", "pl threshold",
                        "display bucket", "promotion reason", "promotion score",
                    ]
                ].first(),
            ],
            axis=1,
        )
        .reset_index()
        .sort_values(
            ["promotion score", "risk type", "risk greek", "reported underlying"],
            ascending=[False, True, True, True],
            kind="stable",
        )
        .reset_index(drop=True)
    )
```

Keep `_rows_from_summary` and the functions below it unchanged. The replacement retains required-column validation, classification-consistency validation and the final ordering. It reuses one grouping object and uses grouped sums instead of a separate Python sum callback for every identity and metric.

## 8. Carry only the columns needed for promotion

In the same file, find `def calculate_current_view_promotion(`.

Find exactly:

```python
    classified = recompute_filtered_promotion(frame)
```

Replace that line with:

```python
    columns = [
        *PROMOTION_KEYS,
        *PROMOTION_VALUE_COLUMNS,
        *PROMOTION_CLASSIFICATION_COLUMNS,
    ]
    classified = recompute_filtered_promotion(frame.loc[:, columns])
```

Keep the rest of the function unchanged. This selects columns for the temporary calculation; it does not delete columns from the app's data. The original prepared input must still contain the promotion keys, amounts, thresholds and classifications listed by these existing constants.

## 9. Remove one redundant baseline frame copy

Open `cube/pages/risk/s02_state.py`. Find `class _RiskDataCache`, then its `def filtered(` method.

After the existing call to `apply_filters`, find this block:

```python
                filtered = apply_promotion_generation(
                    filtered,
                    parsed_generation,
                    revision=revision,
                )
```

Replace that block with:

```python
                if parsed_generation is not None and parsed_generation.kind == "current-view":
                    filtered = apply_promotion_generation(
                        filtered,
                        parsed_generation,
                        revision=revision,
                    )
```

Keep the preceding `apply_filters` call and everything afterward. Keep the actual `apply_promotion_generation` function elsewhere.

`apply_filters` has already returned an owned copy. Applying no manual generation or a baseline generation only copies it again. The new condition removes that extra copy while retaining the existing manual `current-view` classification path. It does not remove filtering, refresh handling or the reduced-tenor cache.

## 10. Save, check syntax and compare promotion

Save the three promotion-related files. Run this cell in the notebook with `cube` in its working directory:

```python
import ast
from pathlib import Path

for filename in (
    "cube/ui/s02_aggregation.py",
    "cube/pages/risk/s11_promotion.py",
    "cube/pages/risk/s02_state.py",
):
    ast.parse(Path(filename).read_text(encoding="utf-8-sig"), filename=filename)
    print("Syntax OK:", filename)
```

Correct any syntax error, restart the app, then reload the browser.

1. Apply the same filters and tenor setting used in step 1, with the same financial data where available.
2. Recalculate twice without an intervening change and record the displayed milliseconds and total visible wait.
3. Compare promoted underlyings, Risk/dRisk/P&L totals, thresholds and pinned underlyings.
4. Confirm entirely missing totals remain unavailable and thresholds are not multiplied by the number of portfolios.
5. Confirm manual promotion still affects the Risk display and Reset promotion restores the baseline.

Grouped floating-point sums can differ in final rounding from individual Series sums. Inspect exposures exactly at a promotion threshold when comparing results; these changes introduce no new tolerance or threshold policy.

These edits reduce calculation and copying work. They do not bypass the whole-book reduction or eliminate the table redraw, so use step 13 if the 25-second delay remains.

## 11. Extract the actual callback before changing Quick prefill

This is the part that is not yet a complete source replacement. The unified Risk / Market / Both workspace uses an `edit_workspace` callback whose actual implemented body is needed. A separate-tab callback has different outputs and must not be pasted over it.

The reproduced failure is that the initial empty picker can be interpreted as a new user selection, or catalogue arrival can be processed before the saved selection is restored. Quick already contains the exact identity and scope; it can prefill before the complete catalogue is ready.

Run this read-only notebook cell from the folder containing `cube`. It prints the complete callback and its decorator without importing or launching the app:

```python
import ast
from pathlib import Path

path = Path("cube/pages/data/s03_callbacks.py")
source = path.read_text(encoding="utf-8-sig")
tree = ast.parse(source, filename=str(path))
lines = source.splitlines()
matches = [
    node for node in ast.walk(tree)
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    and node.name == "edit_workspace"
]
if len(matches) != 1:
    print("Expected one edit_workspace; found", len(matches))
    print("Inspect the actual Data callback names before changing this file.")
else:
    node = matches[0]
    start = min([node.lineno] + [item.lineno for item in node.decorator_list])
    print("\n".join(lines[start - 1:node.end_lineno]))
```

Send that printed callback, including its decorator, together with the timing values from step 1 or 10. Keep the Data callback source unchanged until the replacement has been matched to that implementation. The ready changes above do not depend on that replacement.

## 12. Required behaviour for the prefill correction

These are the acceptance requirements for the eventual small dispatch correction, not instructions to invent a replacement callback:

1. A valid new Quick selection takes priority over catalogue and ordinary picker events.
2. First page initialization restores the saved request before interpreting the layout's empty defaults as edits. An intentionally cleared picker must remain distinguishable from a page that has not initialized.
3. Event dispatch examines all `ctx.triggered_prop_ids`, because several properties can change together.
4. Catalogue arrival updates options while retaining the effective selection.
5. The Quick nonce is consumed only after its request validates. An old Quick selection must not overwrite subsequent manual choices.
6. The existing one callback remains owner of the picker, draft and request outputs. Keep Load, reset, date, Risk scope and Both companion rules.

Once that exact correction is supplied and applied, confirm Quick Risk and Quick Market each prefill and auto-load their incoming kind; a later manual selection stays selected; and entering Both retains the intended primary while requiring the appropriate companion.

## 13. Decide what remains if promotion still takes 25 seconds

Use the already displayed calculation duration rather than assuming the sum operation is the whole delay:

| Observation | Next action |
| --- | --- |
| First Reduced calculation is slow; unchanged second calculation is much faster | Report both durations and the data revision. This is consistent with initial all-Risk reduced-view preparation; verify that path before changing cache reuse. |
| Both calculations display about 25,000 ms | Report both values and Full/Reduced mode. The next inspection is frame preparation/reduction and waits inside the calculation callback. |
| Displayed calculation duration is small but the browser takes much longer | Inspect subsequent table construction, serialization and browser rendering. The calculation changes above cannot remove that separate delay. |

Keep `reduced_tenor` tied to the chosen setting and keep the calculation's existing all-Risk filtered scope. Forcing Full mode or restricting the calculation to the currently visible Risk type would change what is calculated. Increasing a timeout does not speed it up.

## Recovery only if an edit causes a problem

Restore the affected source files from the copies saved in step 2, then restart the app. This is a recovery action, not a routine final implementation step.
