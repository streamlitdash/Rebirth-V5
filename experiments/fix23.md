# Fix 23 — Paginate the JTD reference table and color negative values

**Status:** Implementation guide for `v4` at
`cad45db58854df4893c0f1ab1b869a303db2f7a8`. Adding this document does not
change runtime behavior.

## Short answer

The easiest safe change is presentation-only:

1. list the exact four signed JTD reference column headers;
2. replace the non-empty `html.Table` in
   `build_jtd_reference_table()` with `dash_table.DataTable`;
3. enable native pagination at ten rows per page;
4. parse only those four columns for sign detection while preserving the
   original displayed CSV strings; and
5. apply `color: var(--negative)` to each negative cell.

The essential DataTable settings are:

```python
page_action="native",
page_current=0,
page_size=10,
```

This needs no new callback, store, UUID, connector, cache, promotion
recalculation, or reduced-tenor work.

## One required input before implementation

The repository does **not** contain the names of the four numeric JTD
reference columns. The checked-in file contains only:

```csv
Underlying
```

The current contract requires only `Underlying`; every other CSV field is
optional and application-owned. Neither the code, tests, experiment history,
nor Git history establishes a four-column numeric schema. The four descriptive
example fields in Fix 15 are not numeric and must not be reused.

Before implementing the change, replace these placeholders with the exact,
case-sensitive production headers:

```python
JTD_REFERENCE_SIGNED_COLUMNS: tuple[str, str, str, str] = (
    "<exact production header 1>",
    "<exact production header 2>",
    "<exact production header 3>",
    "<exact production header 4>",
)
```

Do not infer the fields by testing every column for numeric-looking values.
Identifiers, dates, ratings and text codes may also look numeric. The explicit
tuple ensures that only the intended four columns can become red.

To inspect the deployed header without loading or publishing its rows:

```powershell
Get-Content data\s13_jtd.csv -TotalCount 1
```

The implementation is not complete until the placeholders are replaced and a
test proves the tuple contains four unique, nonblank, real headers.

## Current chain

The JTD reference table is a lazy local-file detail in Risk Explorer. Although
the CSV is static, this is **not** the `/static-data` page.

```text
Credit JTD measure plus an existing/clicked hierarchy selection
  -> Risk Explorer detail callback
  -> resolve clicked raw/reported/promoted Underlying
  -> jtd_reference_rows(underlying)
  -> exact match in data/s13_jtd.csv
  -> build_jtd_reference_table(...)
  -> plain html.Table containing every matching row
```

| Responsibility | Current location |
|---|---|
| Lazy file read, cache, validation and exact issuer lookup | `cube/services/s08_jtd.py` |
| Decide whether Credit/JTD detail should load | `cube/pages/risk/s07_explorer.py::render_active_detail()` |
| Carry the reference data into the detail card | `cube/pages/risk/s05_charts.py::build_detail_panel_with_state()` |
| Render every matched row as plain HTML | `cube/pages/risk/s13_workspacetables.py::build_jtd_reference_table()` |
| JTD card and scroll styling | `assets/s03_risk.css` |
| JTD regressions | `tests/s48_jtd.py` |

The current service deliberately:

- reads the file lazily with `dtype="string"`;
- caches one file revision by path, modification time and size;
- requires only `Underlying` and rejects duplicate headers;
- compares Underlying exactly, including case and whitespace;
- preserves every CSV column and matching row in source order; and
- returns a caller-owned filtered copy.

The current renderer stringifies every value and emits all rows as
`html.Tr`/`html.Td`. It has no pagination or sign styling.

## Scope which must not change

This patch changes only the non-empty JTD reference renderer.

- JTD reference remains available only for Credit JTD in the Cross/main table;
  the current `table_view != "alt"` guard continues to exclude SplitVA.
- Raw Underlying still wins over Reported Underlying, which wins over an
  eligible promoted Display Bucket; `Other` remains ineligible.
- `s13_jtd.csv` remains absent from the Static Data page's read and write
  allowlists. This patch does not expose it or make it editable there.
- The reference values never feed financial `Risk JTD`, `dRisk JTD`, P&L,
  promotion, row ordering, recalculation, or tenor reduction.
- Missing/unreadable files and empty matches retain their current detail-card
  messages.
- Changing Credit measure or clicked issuer still rebuilds the detail card in
  the existing callback; there is no separate pagination callback.

This distinction matters: the auxiliary JTD CSV is not the financial
Risk/dRisk JTD measure pair.

## Intended result

| Behavior | Intended contract |
|---|---|
| Component | Dash `DataTable` in the existing JTD reference card |
| Pagination | Native/client-side, 10 rows per page |
| Data sent to browser | All selected rows plus up to four internal `0`/`1` marker keys |
| Display values | Original CSV strings, unchanged |
| Column and row order | Same as the filtered source frame |
| Signed columns | Exactly the configured four headers when present |
| Negative color | `var(--negative)` in the negative cells only |
| Zero, positive, blank or invalid text | Normal text color |
| Other columns | Preserved and never sign-colored |
| Empty/error behavior | Unchanged |
| Callback/store work | None |

Native pagination reduces the number of rows rendered at once, but it still
sends every matching issuer row to the browser. That is the smallest change
for the current reference-file design. If a single issuer can contain
thousands of rows, true server-side pagination is a separate feature requiring
a sliced service query and page callback.

## Files to change

The minimal verified patch changes four files:

1. `cube/pages/risk/s13_workspacetables.py` — define the four headers, derive
   negative-cell rules, and replace the non-empty HTML table with a DataTable;
2. `assets/s03_risk.css` — remove the fixed JTD height which can clip the pager;
   and
3. `tests/s48_jtd.py` — lock pagination, data preservation, accessibility and
   the four-column negative styling; and
4. `tests/s39_assets.py` — prove the old JTD height cap is gone and the new
   wrapper rules remain present.

Do not change `s08_jtd.py`, `s07_explorer.py`, `s05_charts.py`, the CSV schema, the
promotion code, reduced-tenor code, or the recalculate callback.

## Step 1 — define the exact four signed columns

In `cube/pages/risk/s13_workspacetables.py`, add the real four headers near the
other module constants:

```python
JTD_REFERENCE_SIGNED_COLUMNS: tuple[str, str, str, str] = (
    "<exact production header 1>",
    "<exact production header 2>",
    "<exact production header 3>",
    "<exact production header 4>",
)
JTD_REFERENCE_PAGE_SIZE = 10
```

This is a presentation allowlist, not a new required-file schema. The
header-only checked-in CSV and valid deployments with extra descriptive fields
continue to work. A configured column is aligned and sign-colored only when it
is present in the returned frame.

Header spelling is exact. Case changes and leading/trailing spaces create a
different CSV column and must fail the deployment smoke check rather than be
guessed away.

Add both constants to this module's existing `__all__` list so the renderer
contract and its tests have one public authority. Keep the sign helper private.

## Step 2 — attach internal sign markers without changing display data

The JTD service intentionally returns strings. Keep that contract and parse a
temporary series only to decide whether a displayed cell is negative.

Do **not** use DataTable `row_index` conditions for a paginated table. In the
pinned Dash 4.4.0 client, row indexes are evaluated within the current native
page. A rule intended for source row 0 can therefore affect the first row of a
later page, while a rule for source row 11 may never match.

Instead, attach one internal numeric sign marker for each configured field to
every record, leave those keys out of the visible column definitions, and make
the red rule query the marker:

```python
def _jtd_table_payload(
    frame: pd.DataFrame,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
]:
    records = (
        frame.astype(object)
        .where(pd.notna(frame), None)
        .to_dict("records")
    )
    styles: list[dict[str, object]] = []
    occupied = {str(column) for column in frame.columns}

    for marker_number, column in enumerate(JTD_REFERENCE_SIGNED_COLUMNS):
        if column not in frame.columns:
            continue

        marker = f"__jtd_negative_{marker_number}__"
        while marker in occupied:
            marker = f"_{marker}"
        occupied.add(marker)

        numeric = pd.to_numeric(
            frame[column].astype("string").str.strip(),
            errors="coerce",
        )
        for record, value in zip(records, numeric):
            record[marker] = int(
                pd.notna(value)
                and np.isfinite(float(value))
                and float(value) < 0
            )

        styles.append(
            {
                "if": {
                    "filter_query": f"{{{marker}}} = 1",
                    "column_id": column,
                },
                "color": "var(--negative)",
            }
        )

    return records, styles
```

`numpy` and `pandas` are already imported in this module. The collision loop
ensures an arbitrary source header cannot overwrite an internal marker.

Why use internal sign markers?

- the current visible payload remains intentionally string-valued;
- merely declaring a visible column `type="numeric"` does not convert it;
- marker values travel with their records across every native page;
- the renderer needs only four conditional rules rather than one per negative
  cell;
- displayed precision, scientific notation and source lexemes stay unchanged;
- the four formerly optional fields do not become a required file schema; and
- one malformed value cannot disable JTD reference for every issuer.

Dash's conditional-style evaluator reads keys from the row datum even when
they are not declared in `columns`. Deliberately leave marker keys undeclared.
Using DataTable's `hidden_columns` property would make pinned Dash 4.4 display
a useless Toggle Columns control for these internal-only fields.

The parser accepts the plain numeric syntax supported by `pd.to_numeric`,
including signs, decimals and scientific notation. Blank, malformed and
non-finite values remain visible but receive marker `0`. If production uses
commas, currency symbols, percentages or accounting parentheses, define and
test that lexical contract before extending the parser. Do not silently strip
punctuation based on guesses.

## Step 3 — replace only the non-empty renderer branch

`s13_workspacetables.py` already imports `dash_table`; no dependency is needed.
Keep the current title, error branch, empty branch and outer card. Replace only
the current `headers`, `rows` and `html.Table` block inside
`build_jtd_reference_table()`:

```python
else:
    display = frame.copy()
    signed_columns = tuple(
        column
        for column in JTD_REFERENCE_SIGNED_COLUMNS
        if column in display.columns
    )
    records, negative_styles = _jtd_table_payload(display)
    visible_columns = [
        {"name": str(column), "id": str(column)}
        for column in display.columns
    ]

    content = html.Div(
        html.Div(
            dash_table.DataTable(
                id="jtd-reference-table",
                columns=visible_columns,
                data=records,
                editable=False,
                cell_selectable=False,
                filter_action="none",
                sort_action="none",
                page_action="native",
                page_current=0,
                page_size=JTD_REFERENCE_PAGE_SIZE,
                style_table={"overflowX": "auto"},
                style_cell={
                    "padding": "8px 10px",
                    "borderBottom": "1px solid var(--outline-soft)",
                    "backgroundColor": "var(--surface)",
                    "color": "var(--text)",
                    "fontFamily": "inherit",
                    "fontSize": "12px",
                    "lineHeight": "1.3",
                    "textAlign": "left",
                    "whiteSpace": "nowrap",
                },
                style_header={
                    "backgroundColor": "var(--surface-muted)",
                    "color": "var(--text)",
                    "fontWeight": 850,
                },
                style_cell_conditional=(
                    [
                        {
                            "if": {"column_id": list(signed_columns)},
                            "fontVariant": "tabular-nums",
                            "textAlign": "right",
                        }
                    ]
                    if signed_columns
                    else []
                ),
                style_data_conditional=negative_styles,
            ),
            className="detail-table jtd-reference-table",
        ),
        className="detail-table-wrap jtd-reference-table-wrap",
        tabIndex=0,
        role="region",
        **{"aria-label": title},
    )
```

Important details:

- `data` receives every matching row; do not pre-slice the first ten;
- `page_action="native"` makes the browser own Previous/Next state;
- `page_current=0` starts a newly rebuilt issuer table on its first page;
- `page_size=10` matches the nearby Top Promotions table convention;
- the original strings remain in `data`, so display precision is preserved;
- nulls become JSON-safe `None` values;
- only the four present allowlisted columns are right-aligned;
- each negative style queries one internal sign marker and targets one visible
  column, so it follows the record across pages without coloring a whole row;
- `var(--negative)` is readable in both light and dark themes; and
- the labelled `region` replaces the native table's screen-reader caption and
  keeps an accessible name for the DataTable region.

The outer `jtd-reference-card` and its existing `aria-label` remain unchanged.
Do not add filter or sort actions in this patch; they are not needed for the
requested pagination and would expand the behavior to verify.

## Step 4 — ensure the pager is not clipped

The current native-table wrapper is capped at `320px`. A ten-row DataTable plus
its pager can be clipped or placed inside a nested vertical scroller.

In `assets/s03_risk.css`, replace:

```css
.jtd-reference-table-wrap { max-height: 320px; }
```

with:

```css
.jtd-reference-table-wrap {
  max-height: none;
  overflow: visible;
}

.jtd-reference-table-wrap .dash-table-container {
  width: 100%;
}
```

Horizontal scrolling remains owned by `style_table`, while the pager stays
outside a fixed-height vertical scroller.

Do not copy the existing `.dash-pagination-btn` override from another page
without inspecting the live DOM: that selector is not provided by the pinned
Dash 4.4.0 bundle. If visual QA finds that pager controls need explicit dark
styling, inspect the rendered `.previous-next-container` and add a narrowly
scoped JTD rule against the actual button/input classes. The DataTable cells
and headers already use semantic theme variables in the renderer.

## Step 5 — update the JTD regressions

In `tests/s48_jtd.py`, import DataTable and the two renderer constants:

```python
from dash import dash_table, html

from cube.pages.risk.s13_workspacetables import (
    JTD_REFERENCE_PAGE_SIZE,
    JTD_REFERENCE_SIGNED_COLUMNS,
    build_jtd_reference_table,
)
```

Keep the existing service, file-error and identity tests. Replace
`test_jtd_table_is_flat_and_uses_the_detail_table_style()` with a DataTable
test using more than one page of records:

```python
def _jtd_data_table(component: object) -> dash_table.DataTable:
    return next(
        item
        for item in _walk(component)
        if isinstance(item, dash_table.DataTable)
    )


def test_jtd_table_paginates_and_colors_only_negative_signed_cells() -> None:
    assert JTD_REFERENCE_SIGNED_COLUMNS == (
        "<exact production header 1>",
        "<exact production header 2>",
        "<exact production header 3>",
        "<exact production header 4>",
    )
    assert len(JTD_REFERENCE_SIGNED_COLUMNS) == 4
    assert len(set(JTD_REFERENCE_SIGNED_COLUMNS)) == 4
    assert all(column.strip() for column in JTD_REFERENCE_SIGNED_COLUMNS)
    assert all(
        column == column.strip()
        for column in JTD_REFERENCE_SIGNED_COLUMNS
    )
    assert all(
        "<exact production" not in column
        for column in JTD_REFERENCE_SIGNED_COLUMNS
    )

    negative_rows = (0, 3, 7, 11)

    def signed_values(negative_row: int) -> list[object]:
        values: list[object] = ["1.2500"] * 12
        values[negative_row] = "-1.25"
        values[(negative_row + 1) % 12] = "0"
        values[(negative_row + 2) % 12] = pd.NA
        return values

    frame = pd.DataFrame(
        {
            "Underlying": ["ACME"] * 12,
            "Desk": [f"Desk {index}" for index in range(12)],
            "Numeric-looking text": ["-999"] * 12,
            **{
                column: signed_values(negative_row)
                for column, negative_row in zip(
                    JTD_REFERENCE_SIGNED_COLUMNS,
                    negative_rows,
                )
            },
        }
    )
    expected_records = (
        frame.astype(object)
        .where(pd.notna(frame), None)
        .to_dict("records")
    )

    component = build_jtd_reference_table(frame, "ACME")
    table = _jtd_data_table(component)

    assert component.className == "jtd-reference-card"
    assert (
        component.to_plotly_json()["props"]["aria-label"]
        == "JTD reference — ACME"
    )
    assert table.id == "jtd-reference-table"
    assert table.page_action == "native"
    assert table.page_current == 0
    assert table.page_size == JTD_REFERENCE_PAGE_SIZE == 10
    assert table.cell_selectable is False
    assert table.editable is False
    assert table.filter_action == "none"
    assert table.sort_action == "none"
    assert len(table.data) == 12
    visible_columns = [
        {"name": column, "id": column}
        for column in frame.columns
    ]
    marker_keys = [
        f"__jtd_negative_{index}__"
        for index in range(4)
    ]
    assert getattr(table, "hidden_columns", None) is None
    assert table.columns == visible_columns
    assert [
        {
            column: record[column]
            for column in frame.columns
        }
        for record in table.data
    ] == expected_records

    for marker, negative_row in zip(marker_keys, negative_rows):
        assert [record[marker] for record in table.data] == [
            int(row_index == negative_row)
            for row_index in range(12)
        ]

    assert table.style_cell_conditional == [
        {
            "if": {"column_id": list(JTD_REFERENCE_SIGNED_COLUMNS)},
            "fontVariant": "tabular-nums",
            "textAlign": "right",
        }
    ]
    assert table.style_data_conditional == [
        {
            "if": {
                "filter_query": f"{{{marker}}} = 1",
                "column_id": column,
            },
            "color": "var(--negative)",
        }
        for column, marker in zip(
            JTD_REFERENCE_SIGNED_COLUMNS,
            marker_keys,
        )
    ]

    classes = {
        getattr(item, "className", None)
        for item in _walk(component)
        if isinstance(item, html.Div)
    }
    assert "detail-table jtd-reference-table" in classes
    assert "detail-table-wrap jtd-reference-table-wrap" in classes

    labelled_region = next(
        item
        for item in _walk(component)
        if isinstance(item, html.Div)
        and getattr(item, "role", None) == "region"
    )
    assert (
        labelled_region.to_plotly_json()["props"]["aria-label"]
        == "JTD reference — ACME"
    )
```

Replace the four literal test placeholders with the same four agreed business
headers, reviewed independently of the implementation tuple. This literal
assertion deliberately duplicates the external contract so an accidental
rename in production code cannot make a self-derived test pass.

The test proves all records—not only the first page—reach the browser, source
lexemes such as `"1.2500"` remain unchanged, nulls become `None`, row/column
order is stable, a negative numeric-looking unconfigured field stays
uncolored, marker values follow their records, and exactly one rule maps each
allowlisted visible column to its own internal sign marker.

Add these new tests as well:

1. a non-empty dynamic JTD frame with none of the configured fields still
   renders all text columns, has no marker keys in `data`, leaves
   `hidden_columns` unset, and sets both conditional-style lists to `[]`;
2. values `"bad"`, `""`, `pd.NA`, `"NaN"`, `"inf"` and `"-inf"` in one
   configured field remain displayed and receive marker `0`, while a valid
   `"-1"` control receives marker `1`; the one generic marker-query style rule
   still exists and rendering does not crash;
3. a no-match service lookup returns an empty frame;
4. empty and explicit-error renderer states contain no DataTable and retain
   their current `empty-state` message/role; and
5. a source column colliding with an initial internal marker name is preserved
   while the helper chooses a different marker key; and
6. the main 12-row fixture gives row 11 marker value `1`; the manual live
   acceptance in Step 7 then confirms its visible cell is red on page 2 and
   page 1 is unchanged.

Those are additions; the current test file does not yet assert no-match or the
absence of a DataTable in empty/error states.

In `tests/s39_assets.py`, add a required focused regression proving the JTD
wrapper contains `max-height: none` and `overflow: visible`, its nested
`.dash-table-container` rule exists, and the old scoped `max-height: 320px`
rule is absent. A component unit test cannot prove the pager is visually
unclipped or execute conditional styling, so live browser QA remains required.

## Step 6 — run focused verification

Baseline before implementation:

```text
tests/s48_jtd.py + tests/s39_assets.py
12 passed
```

Run the relevant set after the code change:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest `
  tests\s48_jtd.py `
  tests\s06_ui.py `
  tests\s39_assets.py `
  -q -p no:cacheprovider
```

Then compile the changed Python renderer and run the repository's normal full
checks before publishing runtime code:

```powershell
& '.\.venv\Scripts\python.exe' -m py_compile `
  cube\pages\risk\s13_workspacetables.py
```

## Step 7 — perform live acceptance checks

Use a test copy of `s13_jtd.csv` with at least 12 rows for one exact Underlying.
Each of the four configured columns should include a negative value, zero,
positive value and blank in the same lexical form used by production.

1. Open Risk Explorer and select Credit.
2. In the Cross/main table, select JTD in Single view or click a JTD cell in
   Multi view.
3. Click the matching Underlying row.
4. Confirm the JTD reference card still appears above the normal detail grid.
5. Confirm page 1 shows ten rows and the remaining rows appear on page 2.
6. Confirm paging does not invoke a new server callback.
7. Confirm only negative cells in the exact four configured columns are red.
8. On page 2, confirm the red state follows that page's records and does not
   repeat the sign pattern from page 1.
9. Confirm zero, positive, blank, invalid text, Underlying and other text cells
   use normal color.
10. Confirm the four signed columns are right-aligned.
11. Confirm displayed precision, source column order and source row order are
    unchanged.
12. Confirm internal marker columns are not visible in either page.
13. Repeat in light and dark themes.
14. Repeat at 200% browser zoom and confirm the pager is visible and usable.
15. Perform a keyboard and screen-reader check of the labelled table region,
    page controls, visible heading and page changes.
16. Select another issuer and confirm the rebuilt table starts on page 1.
17. Test an issuer with no matching rows and confirm the current empty message.
18. Switch to SplitVA or away from JTD and confirm the reference card is not
    shown, as before.
19. Confirm the Static Data page still neither reads nor writes `s13_jtd.csv`.

This acceptance sequence does not exercise promotion recalculation or tenor
reduction. A correct paginated reference table is not evidence that those
separate flows are fixed.

## Common mistakes

### Adding pagination properties to `html.Table`

An HTML table has no Dash pagination behavior. Replace the non-empty component
with DataTable and set `page_action="native"`.

### Passing only the first ten records

Native pagination needs all matching rows in `data`. If the renderer slices to
ten first, the browser has no second page.

### Querying the visible string fields directly

The service intentionally returns strings. Do not assume `type="numeric"`
converts them. Derive numeric internal markers from a temporary parsed series,
then query the markers while leaving displayed data untouched.

### Coloring a whole row or column

Each rule must query one internal sign marker and target one visible `column_id`.
Do not use page-relative `row_index`, and do not omit `column_id`, which would
broaden the visual effect.

### Guessing the four fields

Do not color every parseable column and do not reuse unrelated Fix 15 example
fields. Copy the exact deployed headers into one shared tuple.

### Silently normalizing business formats

Do not strip commas, currency symbols, percentages or parentheses until their
meaning is agreed and covered by representative tests.

### Mutating or tightening the service contract

This feature does not require changing `dtype="string"`, making extra columns
mandatory, or validating the entire cached file as numeric. Those changes can
alter display precision and let one unrelated bad row disable every issuer.

### Adding a pagination callback

Native pagination owns page state inside DataTable. A new callback is needed
only for a future server-side paging design.

### Leaving the 320px wrapper unchanged

The pager can be clipped or trapped inside nested scrolling. Remove the cap and
verify at normal and enlarged zoom.

### Copying stale pagination CSS selectors

Use live Dash 4.4 DOM classes if explicit pager styling is needed. Do not assume
another page's `.dash-pagination-btn` rule matches the installed component.

### Hard-coding a light-theme red

Use `var(--negative)` so the color stays legible in both themes.

## Expected chain after the change

```text
data/s13_jtd.csv
  -> existing lazy cached string-preserving read
  -> existing exact Underlying lookup
  -> existing Risk Explorer detail callback
  -> preserve every selected string and source order
  -> parse only four allowlisted columns temporarily for sign
  -> attach up to four undeclared per-record sign-marker keys
  -> create up to four marker-query rules targeting visible columns
  -> DataTable receives every selected record
  -> browser renders ten records per page
```

No calculation authority or data contract changes.

## Rollout and rollback

Deploy the renderer, CSS and tests together after replacing the four placeholder
headers. Do not publish proprietary JTD rows merely to populate the checked-in
sample.

Restart the application as part of the normal code deployment, then run the
19-step acceptance sequence with a controlled test file. The existing JTD file
cache continues to detect changes by modification time and size.

Rollback is local and stateless: restore the previous
`build_jtd_reference_table()` HTML branch and the prior wrapper height. There
is no database migration, callback state, UUID, service schema, or promotion
generation to unwind.
