# Fix 23 — Paginate and format the JTD reference table

**Status:** Revised implementation guide for `v4` after confirming the four
financial columns are `Risk JTD`, `EaD`, `EPE`, and `CVA`. Adding or updating
this document does not change runtime behavior.

## Final recommendation

Now that the exact fields and comma-formatting requirement are known, the
easiest correct implementation is:

1. make a presentation copy of the selected JTD rows;
2. convert exactly `Risk JTD`, `EaD`, `EPE`, and `CVA` from CSV strings to real
   numeric values in that copy;
3. render the copy with a native-paginated Dash DataTable;
4. give those four columns the same grouped number presentation used by the
   app's other native financial tables; and
5. add one `< 0` conditional-color rule for each of the four columns.

```python
JTD_REFERENCE_NUMERIC_COLUMNS = (
    "Risk JTD",
    "EaD",
    "EPE",
    "CVA",
)
```

```python
page_action="native",
page_current=0,
page_size=10,
```

```python
{
    "if": {
        "filter_query": f"{{{column}}} < 0",
        "column_id": column,
    },
    "color": "var(--negative)",
}
```

This version needs no hidden marker fields, `row_index` rules, custom page
buttons, callback, store, UUID, connector, promotion recalculation, or
reduced-tenor change.

## Number-format decision

The app consistently uses comma grouping and right-aligned financial values.
It also defines the theme-aware `var(--negative)` semantic token; using that
token here avoids the hard-coded-red plus dark-mode override used by some older
DataTables. The intended treatment is:

- commas for thousands and millions;
- right-aligned financial columns;
- tabular numerals; and
- semantic red for negative values.

The business contract is now explicit: all four values are integers. Use the
same whole-number comma format already used by the app's P&L editor and
unmapped financial table:

```python
JTD_REFERENCE_NUMBER_FORMAT = Format(
    group=",",
    precision=0,
    scheme=Scheme.fixed,
)
```

That serializes to the d3 specifier `,.0f`:

| Numeric value | Display |
|---:|---:|
| `1234` | `1,234` |
| `1234567` | `1,234,567` |
| `-2500000` | `-2,500,000` in semantic red |

This uses literal comma grouping, not compact SI labels such as `1.2M` or
`500K`. Fractional values and non-integer source syntax are invalid under this
contract and must produce an actionable card error; do not silently round or
reinterpret them as integers.

## Why this is simpler than the earlier marker design

The earlier draft preserved all four financial values as strings. That made
comma formatting impossible through DataTable and required separate sign
markers so red cells would remain correct across native pages.

The clarified requirement explicitly wants those four fields formatted as
financial numbers. Once their presentation payload is numeric:

- DataTable applies comma formatting natively;
- `{Risk JTD} < 0`, `{EaD} < 0`, `{EPE} < 0`, and `{CVA} < 0` evaluate correctly;
- each rule follows its record across every native page;
- only four conditional rules are needed; and
- there is no internal marker data or Toggle Columns side effect.

Do not use `row_index` for sign styling. In pinned Dash 4.4.0, `row_index` is
evaluated within the current native page, so a page-one style can affect the
wrong page-two row.

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
| Lazy file read, cache and exact issuer lookup | `cube/services/s08_jtd.py` |
| Decide whether Credit/JTD detail should load | `cube/pages/risk/s07_explorer.py::render_active_detail()` |
| Carry JTD reference rows into detail | `cube/pages/risk/s05_charts.py::build_detail_panel_with_state()` |
| Render the current flat HTML table | `cube/pages/risk/s13_workspacetables.py::build_jtd_reference_table()` |
| JTD card and scroll styling | `assets/s03_risk.css` |
| JTD regressions | `tests/s48_jtd.py` |

The current service reads every CSV value with `dtype="string"`, requires only
`Underlying`, preserves all additional columns dynamically, exact-matches the
selected issuer, and returns a caller-owned filtered copy.

## Scope which must remain unchanged

This patch changes only JTD reference presentation.

- The service continues to read and cache the file as strings.
- Conversion happens only in a copy of the rows for the currently selected
  issuer; the cached source frame is never mutated.
- JTD reference remains available only for Credit JTD in the Cross/main table;
  the current `table_view != "alt"` guard continues to exclude SplitVA.
- Raw Underlying still wins over Reported Underlying, which wins over an
  eligible promoted Display Bucket; `Other` remains ineligible.
- `s13_jtd.csv` remains absent from the Static Data page's read/write allowlists.
- Reference values never feed financial Risk/dRisk, P&L, promotion, row
  ordering, recalculation, or tenor reduction.
- Missing files, no matches, missing required financial headers, and invalid
  selected-issuer numeric values produce
  a detail-card message rather than crashing the page.

The auxiliary CSV column named `Risk JTD` is reference presentation data. It
must not be confused with or fed into the dashboard's calculated Credit
Risk/dRisk JTD measure pair.

## Intended result

| Behavior | Intended contract |
|---|---|
| Component | Dash DataTable inside the existing JTD card |
| Pagination | Native/client-side, 10 rows per page |
| Browser payload | Every matching row for one exact Underlying |
| Numeric fields | Required on every non-empty JTD reference result: `Risk JTD`, `EaD`, `EPE`, `CVA` |
| Number display | Comma-grouped integers (`,.0f`) |
| Negative color | `var(--negative)` in the negative cell only |
| Zero/positive color | Normal text color |
| Other fields | Preserved as text and never sign-colored |
| Row/column order | Same as the selected source frame |
| Empty/error behavior | Existing card, with no DataTable |
| Callback/store work | None |

Native pagination limits the rows rendered at once but still sends every
matching issuer row to the browser. If one issuer can contain thousands of
rows, true server-side pagination is a separate feature requiring a sliced
service query and callback.

## Files to change

The minimal verified patch changes four files:

1. `cube/pages/risk/s13_workspacetables.py` — numeric presentation copy,
   grouped DataTable columns, native pagination and negative rules;
2. `assets/s03_risk.css` — remove the fixed height which can clip the pager;
3. `tests/s48_jtd.py` — lock the four-column numeric/pagination contract; and
4. `tests/s39_assets.py` — lock the pager-safe JTD wrapper CSS.

Do not change `cube/services/s08_jtd.py`, the CSV schema, callback wiring,
promotion code, recalculation code, or reduced-tenor code.

## Step 1 — add the exact numeric presentation contract

In `cube/pages/risk/s13_workspacetables.py`, add these constants near the other
module constants:

```python
JTD_REFERENCE_NUMERIC_COLUMNS: tuple[str, str, str, str] = (
    "Risk JTD",
    "EaD",
    "EPE",
    "CVA",
)
JTD_REFERENCE_PAGE_SIZE = 10
JTD_REFERENCE_NUMBER_FORMAT = Format(
    group=",",
    precision=0,
    scheme=Scheme.fixed,
)
_JTD_REFERENCE_SAFE_INTEGER_MAX = (2**53) - 1
```

`Format` and `Scheme` are already imported in this module. Add the three
constants to its existing `__all__` list so tests and future callers share one
authority. Keep `_JTD_REFERENCE_SAFE_INTEGER_MAX` private; it protects the
integer payload from JavaScript precision loss.

Header matching remains exact and case-sensitive. `EAD`, `Ead`, `Cva`, and
headers with surrounding spaces are different fields and must not be guessed.

## Step 2 — create a numeric presentation copy

Add a private helper in `s13_workspacetables.py` immediately above
`build_jtd_reference_table()`:

```python
def _jtd_numeric_display_frame(frame: pd.DataFrame) -> pd.DataFrame:
    display = frame.copy()
    missing = [
        column
        for column in JTD_REFERENCE_NUMERIC_COLUMNS
        if column not in display.columns
    ]
    if missing:
        raise ValueError(
            "JTD reference is missing required financial column(s): "
            + ", ".join(missing)
            + "."
        )

    for column in JTD_REFERENCE_NUMERIC_COLUMNS:
        raw = display[column].astype("string").str.strip()
        blank = raw.isna() | raw.eq("").fillna(False)
        integer_token = raw.str.fullmatch(r"[+-]?\d+", na=False)
        invalid = ((~blank) & ~integer_token).to_numpy(dtype=bool)
        parsed: list[object] = []

        for position, value in enumerate(raw):
            if bool(blank.iloc[position]) or invalid[position]:
                parsed.append(pd.NA)
                continue

            integer = int(str(value), 10)
            if abs(integer) > _JTD_REFERENCE_SAFE_INTEGER_MAX:
                invalid[position] = True
                parsed.append(pd.NA)
                continue

            parsed.append(integer)

        if invalid.any():
            rows = [
                str(int(position))
                for position in np.flatnonzero(invalid)[:5] + 1
            ]
            raise ValueError(
                f"JTD reference column {column!r} contains a non-integer "
                f"token or unsafe integer at selected data row(s) "
                f"{', '.join(rows)}."
            )

        display[column] = pd.array(parsed, dtype="Int64")
    return display
```

For a non-empty result, all four exact headers are required. This catches a
misspelled or stale production header instead of silently omitting formatting.
The checked-in header-only sample still follows the existing empty-result path.

The helper accepts blanks and signed or unsigned base-10 integer tokens. It
rejects decimal points, exponent notation, populated malformed values, `NaN`,
`inf`, `-inf`, and integers outside `±9,007,199,254,740,991` for the selected
issuer. That bound is the largest integer a browser can represent exactly.
Positional row reporting does not depend on the caller's DataFrame index
labels.

The source CSV should contain raw integer values such as `1234567`; DataTable
adds display commas. The strict parser intentionally rejects a source token
such as `"1,234"`. If the deployed source already stores display commas, add
an explicit, tested normalization rule before parsing rather than silently
stripping arbitrary punctuation.

Why validate in this presentation helper rather than the file service?

- only the selected issuer's rows need numeric presentation;
- one malformed value for an unrelated issuer cannot disable every JTD detail;
- the cached source frame remains unchanged and string-preserving; and
- an invalid selected value can use the existing detail-card error treatment.

## Step 3 — replace only the non-empty HTML-table branch

Keep the current title, missing-file, empty-match, outer card, and ARIA behavior.
Replace only the current `headers`, `rows`, and `html.Table` block.

The non-empty branch should have this shape:

```python
else:
    try:
        display = _jtd_numeric_display_frame(frame)
    except ValueError as numeric_error:
        content = html.Div(
            str(numeric_error),
            className="empty-state",
            role="status",
        )
    else:
        numeric_columns = JTD_REFERENCE_NUMERIC_COLUMNS
        records = (
            display.astype(object)
            .where(pd.notna(display), None)
            .to_dict("records")
        )
        columns = [
            {
                "name": str(column),
                "id": str(column),
                **(
                    {
                        "type": "numeric",
                        "format": JTD_REFERENCE_NUMBER_FORMAT,
                    }
                    if column in numeric_columns
                    else {}
                ),
            }
            for column in display.columns
        ]

        content = html.Div(
            html.Div(
                dash_table.DataTable(
                    id="jtd-reference-table",
                    columns=columns,
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
                                "if": {"column_id": list(numeric_columns)},
                                "fontVariant": "tabular-nums",
                                "textAlign": "right",
                            }
                        ]
                        if numeric_columns
                        else []
                    ),
                    style_data_conditional=[
                        {
                            "if": {
                                "filter_query": f"{{{column}}} < 0",
                                "column_id": column,
                            },
                            "color": "var(--negative)",
                        }
                        for column in numeric_columns
                    ],
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

- all matching records—not only the first ten—go into `data`;
- the four configured fields become real Python numbers or `None`;
- other dynamic fields remain strings and keep their source order;
- the `Format` object adds commas in the browser without converting values
  back to strings;
- each red rule contains both the numeric comparison and one `column_id`;
- filter queries follow records across native pages, unlike `row_index` rules;
- `fontVariant: tabular-nums` is accepted by pinned Dash 4.4;
- `var(--negative)` uses the existing light/dark semantic color token; and
- the labelled region replaces the native table caption's accessible name.

## Step 4 — ensure the pager is not clipped

The current JTD wrapper is capped at `320px`. A ten-row DataTable plus its pager
can be clipped or trapped inside a nested vertical scroller.

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

/* Dash 4.4 hard-codes black current-page text and removes focus outlines. */
:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container,
:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container .page-number {
  color: var(--text);
}

:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container .current-page-shadow,
:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container input.current-page {
  border-bottom-color: var(--outline) !important;
  background: var(--surface) !important;
  color: var(--text) !important;
}

:root[data-theme="dark"]
  .jtd-reference-table-wrap
  .previous-next-container input.current-page::placeholder {
  color: var(--text) !important;
}

:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container button.first-page,
:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container button.previous-page,
:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container button.next-page,
:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container button.last-page {
  background: transparent;
  color: var(--text);
}

:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container button.first-page:disabled,
:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container button.previous-page:disabled,
:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container button.next-page:disabled,
:root[data-theme="dark"]
  .jtd-reference-table-wrap .previous-next-container button.last-page:disabled {
  color: var(--text-muted);
}

.jtd-reference-table-wrap
  .previous-next-container button.first-page:focus-visible,
.jtd-reference-table-wrap
  .previous-next-container button.previous-page:focus-visible,
.jtd-reference-table-wrap
  .previous-next-container button.next-page:focus-visible,
.jtd-reference-table-wrap
  .previous-next-container button.last-page:focus-visible,
.jtd-reference-table-wrap
  .previous-next-container input.current-page:focus-visible {
  outline: 2px solid var(--focus) !important;
  outline-offset: 2px;
}
```

Horizontal scrolling remains owned by `style_table`; the native pager stays
outside a fixed-height vertical scroller.

The actual Dash 4.4 page controls are `.first-page`, `.previous-page`,
`.next-page`, `.last-page`, and `input.current-page` inside
`.previous-next-container`. Do not copy `.dash-pagination` or
`.dash-pagination-btn` selectors from another page; they are not the contract
for this pinned component. The `!important` focus rule intentionally overrides
Dash's more-specific built-in `outline: none`.

## Step 5 — update the regressions

In `tests/s48_jtd.py`, import DataTable and the new renderer constants:

```python
from dash import dash_table, html

from cube.pages.risk.s13_workspacetables import (
    JTD_REFERENCE_NUMBER_FORMAT,
    JTD_REFERENCE_NUMERIC_COLUMNS,
    JTD_REFERENCE_PAGE_SIZE,
    build_jtd_reference_table,
)
```

Keep the current exact-lookup, file-error, empty-file, and promoted-identity
tests. Replace the flat HTML-table test with a 12-row DataTable test which
asserts:

```python
assert JTD_REFERENCE_NUMERIC_COLUMNS == (
    "Risk JTD",
    "EaD",
    "EPE",
    "CVA",
)
assert JTD_REFERENCE_PAGE_SIZE == 10
assert JTD_REFERENCE_NUMBER_FORMAT.to_plotly_json()["specifier"] == ",.0f"

assert table.page_action == "native"
assert table.page_current == 0
assert table.page_size == 10
assert table.filter_action == "none"
assert table.sort_action == "none"
assert len(table.data) == 12
```

Use staggered negative integers across the four columns, including a negative
in source row 11 so page 2 is exercised manually. Include positive integers,
zero, blank, `1234`, `1234567`, and a negative numeric-looking value in a
non-allowlisted text column. Assert the four financial values in `table.data`
are Python integers or `None`, never strings, floats, pandas scalars, or pandas
null sentinels.

For each of the exact four column definitions, assert:

```python
definition["type"] == "numeric"
assert definition["format"].to_plotly_json()["specifier"] == ",.0f"
```

Assert the presentation payload contains Python numbers and `None`, not numeric
strings or pandas null sentinels. Assert every other column remains text and
the complete row/column order is preserved.

Lock the exact four red rules:

```python
assert table.style_data_conditional == [
    {
        "if": {
            "filter_query": f"{{{column}}} < 0",
            "column_id": column,
        },
        "color": "var(--negative)",
    }
    for column in JTD_REFERENCE_NUMERIC_COLUMNS
]
```

Also add tests for:

1. empty and explicit-error states containing no DataTable;
2. exact issuer no-match returning an empty frame;
3. each missing required financial header producing a status error rather than
   a partially formatted table;
4. blank numeric cells becoming `None`;
5. `"1.0"`, `"1.0000000000000001"`, `"1e3"`, `"-0.004"`, `"bad"`,
   `"NaN"`, `"inf"`, `"-inf"`, and the documented-invalid `"1,234"`
   source token producing the integer error state;
6. `"9007199254740991"` and `"-9007199254740991"` remaining exact, while
   either adjacent out-of-range value produces the integer error state;
7. an unrelated numeric-looking text field remaining unformatted and uncolored;
8. right alignment plus `fontVariant: tabular-nums` targeting only the four
   financial columns;
9. a non-default DataFrame index still reporting the correct selected-row
   position, with no DataTable and `role="status"` in the error branch;
10. the caller frame remaining unchanged after both successful and failed
   presentation conversion; and
11. the existing wrapper/card classes and labelled-region accessibility.

In `tests/s39_assets.py`, add a required regression proving that the scoped JTD
wrapper contains `max-height: none` and `overflow: visible`, the nested
`.dash-table-container` rule exists, and the old scoped `max-height: 320px` rule
is gone. Also lock the real `.previous-next-container`, `.current-page`, four
page-button, dark-theme, disabled-state, and `:focus-visible` selectors. Assert
that stale `.dash-pagination` and `.dash-pagination-btn` selectors are not added
to the JTD scope.

Python component tests can inspect numeric payloads, format specifiers, page
settings, and style rules. They cannot execute browser formatting or pagination,
so the page-two color and visible commas remain mandatory live checks.

## Step 6 — run focused verification

Baseline before implementing this guide:

```text
tests/s48_jtd.py + tests/s39_assets.py
12 passed
```

Run the relevant set after implementation:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest `
  tests\s48_jtd.py `
  tests\s06_ui.py `
  tests\s39_assets.py `
  -q -p no:cacheprovider
```

Then compile the changed renderer and run the repository's normal full checks:

```powershell
& '.\.venv\Scripts\python.exe' -m py_compile `
  cube\pages\risk\s13_workspacetables.py
```

## Step 7 — live acceptance

Use a controlled test file with at least 12 rows for one exact Underlying. The
four fields must include staggered negatives, zero, positive, blank, thousands,
and millions.

1. Open Risk Explorer and select Credit.
2. In the Cross/main table, choose JTD and select an Underlying row.
3. Confirm the reference card remains above the normal detail grid.
4. Confirm page 1 shows ten rows and page 2 shows the remaining rows.
5. Confirm paging does not make a new server request.
6. Confirm `1234` displays as `1,234`.
7. Confirm `1234567` displays as `1,234,567`.
8. Confirm a negative in each of `Risk JTD`, `EaD`, `EPE`, and `CVA` is red.
9. Confirm a page-two negative stays red and does not repeat a page-one pattern.
10. Confirm zero, positive, blank, Underlying, and other text cells are not red.
11. Confirm only the four numeric columns are right-aligned/tabular.
12. Confirm source row and visible column order are unchanged.
13. Confirm no internal marker or Toggle Columns control appears.
14. Repeat in light and dark themes; current-page text must remain readable.
15. Repeat at 200% browser zoom and confirm the pager is visible and usable.
16. Tab through first/previous/current/next/last page controls and confirm a
    visible focus outline in both themes.
17. Perform a screen-reader check of the labelled region and pager.
18. Select another issuer and confirm its rebuilt table starts on page 1.
19. Test a fractional or malformed selected value and confirm a readable card
    error.
20. Remove one required financial header and confirm a readable card error.
21. Switch to SplitVA or away from JTD and confirm the reference card disappears.
22. Confirm the Static Data page still cannot read or write `s13_jtd.csv`.

This sequence does not test promotion recalculation or tenor reduction. A
correct paginated JTD reference table is not evidence that those separate flows
are fixed.

## Common mistakes

### Leaving the four values as strings

Dash formats only real numeric payloads. Adding `type="numeric"` or a `Format`
object does not convert `"1234567"`; it remains an unformatted string and
`< 0` styling is unreliable.

### Pre-formatting with `format_number()`

`format_number()` returns strings. It is correct for the app's native HTML risk
cells, but using it here would undo the numeric DataTable payload needed for
pagination-safe `< 0` queries. Use DataTable `Format` instead.

### Using `row_index` for negative color

Dash 4.4 evaluates it within each native page. Use a filter query on the numeric
record value so the color follows the row.

### Keeping hidden sign markers

They were necessary only while preserving the four values as strings. Numeric
payloads make them redundant and substantially complicate the table.

### Silently blanking bad populated values

Blank is allowed. A populated fractional, non-integer, or out-of-safe-range
token should produce an actionable selected-issuer error, not silently become
zero, be rounded, or disappear.

### Parsing the whole cached file

Convert a copy of the selected issuer rows. Do not mutate the cached source or
let an unrelated issuer's bad token disable the current selection.

### Applying one broad red rule

Create one rule per column with both `filter_query` and `column_id`; otherwise a
negative in one field can color unintended cells.

### Forgetting comma grouping

`precision=0` alone gives whole values but no separators. Include `group=","`
and test the resulting `,.0f` specifier.

### Allowing decimal source values

The confirmed JTD reference contract is a base-10 integer token. Validate its
syntax and exact browser-safe range before creating `Int64`; do not route it
through floating point or rely on the display format to round fractional data.

### Slicing to ten rows before DataTable

Native pagination needs all matching records. Pre-slicing leaves no second page.

### Adding a page callback

Native pagination already owns page state. A callback is needed only for future
server-side pagination.

### Leaving the 320px wrapper

It can clip the pager. Remove the cap and verify at enlarged zoom.

### Hard-coding red

Use `var(--negative)` so the value remains legible in both themes.

## Expected chain after the change

```text
data/s13_jtd.csv
  -> existing lazy cached string-preserving read
  -> existing exact Underlying lookup
  -> copy selected issuer rows
  -> parse four exact integer fields without a floating-point round trip
  -> DataTable receives all selected rows
  -> Format adds comma grouping with zero decimals
  -> four numeric < 0 rules add semantic red
  -> browser renders ten rows per page
```

No financial calculation authority or callback contract changes.

## Rollout and rollback

Deploy the renderer, CSS, and tests together. Do not add proprietary JTD rows
to the checked-in header-only sample.

Restart the app as part of the normal deployment and run the 22-step live
acceptance sequence with controlled data.

Rollback is local and stateless: restore the previous HTML-table branch and the
prior wrapper height. There is no database migration, callback state, UUID,
service schema, promotion generation, or reduced-tenor state to unwind.
