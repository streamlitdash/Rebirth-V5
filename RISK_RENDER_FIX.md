# Simple fixes for Risk hierarchy work and Credit Multi

These instructions address the two performance findings: repeated work while expanding Risk rows, and repeated calculation of Credit Multi's six measure columns. Apply them to the code after adding Portfolio.

The change is limited to two existing Python files. It preserves the fifth filter, Portfolio grouping, expansion controls, financial calculations and connector tenor ordering.

For the hierarchy, prepare child-row groups once per expanded parent and group tenor ranks once per axis. For Credit Multi, calculate each usable measure column once per table build, then select the values belonging to each displayed branch. Partially missing measure columns retain the existing calculation so incomplete totals stay unavailable.

This reduces work inside each table build. The visible table and its aggregation index are still rebuilt for each click. Reusing the aggregation index across clicks would be a separate change; this guide adds no persistent cache.

## 1. Save copies of the two files

Using the JupyterHub file browser, download a copy of each file before editing:

- `cube/pages/risk/s06_explorertables.py`
- `cube/ui/s02_aggregation.py`

Work through the replacements below in order. Use the named functions to find the right location; line numbers can change. If an old block is absent, inspect that function before applying the replacement elsewhere.

## 2. Prepare each parent's child groups once

Open `cube/pages/risk/s06_explorertables.py`. Find `def build_tree_rows(`.

Inside that function, find this block:

```python
    for value in ordered_unique(
        frame,
        group_column,
        underlying_sort_metric=underlying_sort_metric,
    ):
```

Replace it with:

```python
    child_positions = frame.groupby(
        frame[group_column].astype(str), sort=False
    ).indices
    for value in ordered_unique(
        frame,
        group_column,
        underlying_sort_metric=underlying_sort_metric,
    ):
```

Keep the preceding `if group_column is None:` return. Keep `ordered_unique`: it still decides the visible row order. The new dictionary only records which source-row positions belong to each child.


## 3. Use those child positions

Stay inside `build_tree_rows` in the same file.

Find exactly:

```python
        scoped = tree_scope(frame, group_column, value)
```

Remove that block and replace it with:

```python
        if group_column == "display bucket" and value == "Other":
            scoped = tree_scope(frame, group_column, value)
        else:
            scoped = frame.iloc[child_positions[str(value)]]
```

Most children now select their already-grouped rows. Keep the `Other` exception exactly as shown: `tree_scope` excludes promoted underlyings from that branch. Keep the following `if scoped.empty:` check and the remaining function body, including the condition that only expands open branches.


## 4. Group tenor ranks once

Open `cube/ui/s02_aggregation.py`. Find `def tenor_axis_order(`.

Find exactly:

```python
    for label in labels.drop_duplicates():
        label_orders = orders.loc[labels.eq(label) & finite]
        if label_orders.empty:
            continue
```

Remove that block and replace it with:

```python
    grouped_orders = orders.loc[finite].groupby(
        labels.loc[finite], sort=False
    )
    for label, label_orders in grouped_orders:
```

Keep everything following this replacement, beginning with `counts = label_orders.value_counts()`. Keep the modal-rank calculation, smallest-rank tie breaker, ambiguity flags and final sorting. This replaces the repeated scan for each tenor with one grouping operation; it does not change connector rank authority. No imports need to change in this file.


## 5. Import the existing Credit helpers

Return to `cube/pages/risk/s06_explorertables.py`. At the top, find the import block beginning `from cube.ui.s02_aggregation import (`. Inside it, locate these two consecutive lines.

Find exactly:

```python
    aggregate_values,
    credit_measure_available,
```

Remove that block and replace it with:

```python
    _credit_cross_gamma_source_mask,
    aggregate_values,
    credit_measure_available,
    credit_measure_column,
```

Keep every other import, including `credit_measure_values`. Both added helpers already exist in `s02_aggregation.py`; do not create new helper functions or copy their implementations into this file.


## 6. Prepare the Credit measure columns once per build

In the same file, find `def build_credit_multi_table(`. Inside it, locate:

```python
    measure_completeness = {
        measure: credit_measure_available(frame, measure) for measure in CREDIT_MEASURES
    }
```

Keep that block. Immediately after it, and before the nested `def measure_cells(`, add:

```python
    row_position_column = "__cube_credit_row_position__"
    while row_position_column in frame.columns:
        row_position_column = f"_{row_position_column}"
    frame = frame.copy(deep=False)
    frame.insert(len(frame.columns), row_position_column, range(len(frame)))
    connector_mask = ~_credit_cross_gamma_source_mask(frame)
    prepared_measures = {}
    for measure in CREDIT_MEASURES:
        column = (
            credit_measure_column(selected_metric, measure)
            if selected_metric != "pl"
            else None
        )
        # A complete dRisk column can make a measure available while Risk is
        # incomplete (and vice versa). Keep the existing per-branch decision.
        partial_metric = (
            measure_completeness[measure]
            and column in frame.columns
            and frame.loc[connector_mask, column].isna().any()
        )
        prepared_measures[measure] = (
            None
            if partial_metric
            else credit_measure_values(
                frame,
                selected_metric,
                measure,
                connector_complete=measure_completeness[measure],
            )
        )
```

Use four spaces of indentation for the new outer statements, exactly as shown. Keep the preceding `selected_metric` assignment and empty-frame handling. Keep the nested `measure_cells` function and its parameters.

The temporary position column lets each branch select the correct values even if the original DataFrame index contains duplicate labels. It is added to a local shallow copy; existing data columns are shared and the caller's frame is not changed.

The small `partial_metric` condition is necessary. For example, dRisk can be complete while Risk is missing in one portfolio. The existing code can show a complete child's Risk while leaving an incomplete parent blank. For those partial columns, `None` means use the existing per-branch calculation. All other usable columns are prepared once for this build.

Keep this preparation inside `build_credit_multi_table`, outside `measure_cells` and its loop. The temporary values are local to this build.


## 7. Read the prepared values in each Credit row

Still inside `build_credit_multi_table`, find the nested `def measure_cells(`. At the start of that nested function, locate the following block.

Find exactly:

```python
        show_value = should_show_sum(selected_metric, context)
        cells: list[html.Td] = []
        for measure in CREDIT_MEASURES:
            series = credit_measure_values(
                scoped,
                selected_metric,
                measure,
                connector_complete=measure_completeness[measure],
            )
            value = float(series.sum(min_count=1))
```

Remove that block and replace it with:

```python
        show_value = should_show_sum(selected_metric, context)
        cells: list[html.Td] = []
        positions = scoped[row_position_column].to_numpy()
        for measure in CREDIT_MEASURES:
            prepared = prepared_measures[measure]
            series = (
                credit_measure_values(
                    scoped,
                    selected_metric,
                    measure,
                    connector_complete=measure_completeness[measure],
                )
                if prepared is None
                else prepared.take(positions)
            )
            value = float(series.sum(min_count=1))
```

Keep all formatting, button construction and cell appending after this block. Keep `sum(min_count=1)` exactly: an entirely unavailable series must remain blank. `prepared.take(positions)` reads the current branch by row position; do not replace it with label-based `.loc` selection. The fallback preserves the original missing-data behavior.


## 8. Reuse the existing availability result

Near the bottom of `build_credit_multi_table`, find the `missing_measures` assignment.

Find exactly:

```python
    missing_measures = [
        measure
        for measure in CREDIT_MEASURES
        if not credit_measure_available(frame, measure)
    ]
```

Remove that block and replace it with:

```python
    missing_measures = [
        measure for measure in CREDIT_MEASURES if not measure_completeness[measure]
    ]
```

Keep the warning/note construction that follows. It will display the same availability information without calculating it again.


## 9. Save and check Python syntax

Save both files. In a notebook whose working folder contains the `cube` folder, run this cell:

```python
import ast
from pathlib import Path

for filename in (
    "cube/pages/risk/s06_explorertables.py",
    "cube/ui/s02_aggregation.py",
):
    path = Path(filename)
    ast.parse(path.read_text(encoding="utf-8-sig"), filename=filename)
    print("Syntax OK:", filename)
```

This checks indentation and Python syntax without launching the app. If it reports a syntax error, correct the indicated block before restarting. It does not verify the running app's behavior.

## 10. Restart the app and check the visible result

Stop the existing app process or notebook cell and restart it using your usual launch command. Reload the browser page.

1. Open Risk Explorer and use the same data, filters and metric as before.
2. Select Portfolio as the grouping dimension, expand an underlying, expand a tenor and then its Portfolio branches. Confirm that the same portfolios and totals appear.
3. Collapse and reopen those branches. Confirm the buttons still work and the row order remains the same.
4. Switch between full and reduced tenors. Confirm connector tenor ordering remains correct in both modes.
5. If you use promotions, open a promoted underlying and the `Other` branch. Confirm the promoted underlying is excluded from `Other` as before.
6. Open Credit Multi. Switch through Risk, dRisk and P&L. Confirm all six measure columns retain their previous values and unavailable values remain blank.
7. If your data includes partially missing Credit measure columns or Cross Gamma source rows, inspect those branches too. Complete child values and unavailable parent totals should behave as before.
8. Apply a different Portfolio filter and then restore it. Confirm the table reflects each selection.

Keep the existing Portfolio filter, grouping dimension, Cross/Split VA/Credit controls, aggregation index, numeric aggregation functions, refresh logic and cache settings. Only the exact blocks above change. These edits do not add a row limit or reduce the data available to read.

Large expanded tables still contain the same number of browser rows. These changes reduce Python work; displaying hundreds of rows can still take time in the browser. Existing unrelated expansion or data-loading issues need their own diagnosis.

If a replacement causes a problem, restore the two copies saved in step 1 and restart the app.
