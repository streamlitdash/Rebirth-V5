# Jump to Default: readable, searchable pages

This is an independent implementation guide, not an application patch. It is based on `streamlitdash/Rebirth-V5` commit `2220a3f4839318863a9131e3fef8118d0f82fb7d`. Apply the steps below together, then restart. No earlier guide is required.

## What changes

- The JTD reference shown in the tenor-detail area becomes a table with 25 rows per page.
- One search box searches all columns, or just the column selected next to it. Choose **CRDS** to restrict a search to CRDS. Searching applies to every matching row, including other pages.
- Rows always start with the largest **absolute Risk JTD**: `-9,000` comes before `+8,000`. The sign of the actual number stays unchanged.
- Numeric measures, including Risk JTD and EAD, display commas and two decimal places. Negative numbers are red; positive numbers and zero are black. Missing numbers show a dash.
- The existing Cross and SplitVA detail paths can both show JTD. Reported display names are resolved back to the raw Underlying names used by the CSV.

This keeps the existing CSV reader, one-file cache and Dash DataTable already used elsewhere. The browser receives only the current page and a small list of selected raw identities. There is no new database, whole-table browser Store, grid package or filtering-expression parser. The search is a case-insensitive literal substring search; mathematical filter expressions are not part of this change.

## Why the current table behaves this way

1. [`cube/services/s08_jtd.py`](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/services/s08_jtd.py) reads every column as text. That correctly protects identifiers, but leaves financial measures untyped.
2. `build_jtd_reference_table()` in `cube/pages/risk/s13_workspacetables.py` creates an HTML row for every match and writes each value with `str(value)`. There is no pagination, search, numeric sort or numeric formatting in that function.
3. `render_active_detail()` in `cube/pages/risk/s07_explorer.py` explicitly requires `table_view != "alt"` before loading JTD. This blocks the alternate table even if JTD is selected. It also only takes the fallback credit measure from the selector when `credit_view == "single"`; the alternate table needs that fallback regardless of the hidden single/multi setting.
4. The current lookup sometimes passes a **Reported Underlying** label to a CSV reader expecting an exact raw **Underlying**. An alias or an aggregate label will then match nothing.

**About “Cross VA”:** the source labels its tabs **Cross** (`main`) and **SplitVA** (`alt`), not “Cross VA”. The explicit gate proves why **SplitVA** omits the JTD reference. Actual Cross already has a JTD path; for that tab, check the selected credit measure, raw/reported identity mismatch and missing CSV rows. This guide repairs the confirmed gate and identity issues in both paths. It does not claim to have reproduced your production screen.

## Step 1 — Put the real JTD reference columns in the existing CSV

Use `data/s13_jtd.csv`. The file committed in this baseline contains only the `Underlying` header: GitHub does not contain your populated CRDS, Risk JTD or EAD columns. Therefore the production field spellings cannot be inferred from this repository.

Use this header shape; values below illustrate formatting only:

```csv
Underlying,CRDS,Risk JTD,EAD,Comment
RAW_NAME_A,000123,-9000,1234.5,Example
RAW_NAME_A,000456,8000,-25,Example
RAW_NAME_B,000789,125,0,Example
```

Keep these rules:

- `Underlying` is the exact raw identity used by the Risk feed, including case. It is not the displayed Reported Underlying label. Multiple rows for the same Underlying are allowed.
- `CRDS` stays text, including leading zeros. Other identifier columns also stay text.
- Use `Risk JTD` and `EAD` as the measure headers. The parser below tolerates capitalization differences for those two names; it does not guess aliases such as `JTD_RISK`. Rename an actual feed alias at your CSV export boundary.
- Empty numeric cells mean missing. Do not write `N/A`, currency symbols or percentages into numeric cells. Prefer plain numeric values. A quoted comma-formatted number such as `"1,234.50"` is also accepted.
- Keep every useful additional column. Add each additional **numeric measure** to `JTD_NUMERIC_COLUMNS` in Step 2. For example, change the tuple to `("Risk JTD", "EAD", "Notional", "Recovery")` if those are your actual measure headers. All listed measures receive the same parsing, commas and sign colors. Do not add numeric-looking IDs such as CRDS, Portfolio or trade IDs to that tuple.

This small explicit measure list prevents `000123` from silently becoming the number `123`. Because the source reads strings, it cannot safely determine which digit-only columns are identifiers without this declaration. There is no need to list text columns: they appear and become searchable automatically.

The JTD CSV is a reference dataset. The existing lookup is scoped by Underlying, not Portfolio. The repair uses the active risk filters and clicked row to determine the correct raw Underlying names, then shows all reference rows for those names. If the reference holds several portfolios for the same name, those rows remain visible; do not assume its displayed amounts equal the clicked portfolio total. Adding a Portfolio reconciliation contract is a separate data change.

## Step 2 — Replace the small JTD service

**File:** `cube/services/s08_jtd.py`.

Replace the entire file with the following. Keep the CSV in its existing location. The numeric conversion and absolute ordering happen once per file version inside the existing one-entry cache. Search and paging happen on the server after selecting the raw names.

```python
"""Lazy, typed and paged Jump-to-Default reference data."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Sequence

import pandas as pd

JTD_REFERENCE_PATH = Path(__file__).resolve().parents[2] / "data" / "s13_jtd.csv"
JTD_NUMERIC_COLUMNS = ("Risk JTD", "EAD")  # Add every other measure here.
JTD_PAGE_SIZE = 25


class JTDReferenceError(RuntimeError):
    """The optional reference file cannot be used."""


@lru_cache(maxsize=1)
def _read_jtd_reference(path_text: str, modified_ns: int, size: int) -> pd.DataFrame:
    del modified_ns, size  # These values invalidate the one-file cache.
    path = Path(path_text)
    try:
        frame = pd.read_csv(
            path, dtype="string", encoding="utf-8-sig", keep_default_na=False
        )
    except (OSError, UnicodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as error:
        raise JTDReferenceError(f"Could not read {path.name}: {error}") from error
    if "Underlying" not in frame.columns:
        raise JTDReferenceError(f"{path.name} must contain a column named 'Underlying'.")
    if frame.columns.duplicated().any():
        raise JTDReferenceError(f"{path.name} contains duplicate column names.")

    numeric_names = {name.casefold() for name in JTD_NUMERIC_COLUMNS}
    for column in frame.columns:
        if column.casefold() not in numeric_names:
            continue
        text = frame[column].str.strip().str.replace(",", "", regex=False)
        values = pd.to_numeric(text.mask(text.eq("")), errors="coerce")
        invalid = (text.ne("") & values.isna()) | values.isin([float("inf"), -float("inf")])
        if invalid.any():
            raise JTDReferenceError(f"{column} contains invalid numbers; fix the CSV.")
        frame[column] = values

    risk_column = next((c for c in frame if c.casefold() == "risk jtd"), None)
    if risk_column is None and not frame.empty:
        raise JTDReferenceError("JTD reference requires a 'Risk JTD' column for ordering.")
    if risk_column is not None:
        frame = frame.sort_values(
            risk_column, key=lambda values: values.abs(), ascending=False,
            kind="stable", na_position="last",
        )
    return frame.reset_index(drop=True)


def jtd_reference_rows(
    underlying: str | Sequence[str], *, path: str | Path = JTD_REFERENCE_PATH
) -> pd.DataFrame:
    """Match raw identities exactly, retaining each CSV row once and all columns."""
    selected = [underlying] if isinstance(underlying, str) else list(underlying)
    source = Path(path)
    try:
        stat = source.stat()
    except OSError as error:
        raise JTDReferenceError(f"JTD reference file is missing: {source}") from error
    frame = _read_jtd_reference(str(source.resolve()), stat.st_mtime_ns, stat.st_size)
    return frame.loc[frame["Underlying"].isin(selected)].reset_index(drop=True).copy()


def jtd_page(frame, page_current=0, search="", column="__all__"):
    """Search the whole selected result, then serialize at most 25 rows."""
    selected = frame
    query = str(search or "").strip()
    if column != "__all__" and column not in frame:
        raise JTDReferenceError("That search column changed; select the JTD row again.")
    if query:
        columns = list(frame.columns) if column == "__all__" else [column]
        matches = pd.Series(False, index=frame.index)
        for name in columns:
            needle = query
            if pd.api.types.is_numeric_dtype(frame[name]):
                needle = needle.replace(",", "")
                if "." in needle:
                    needle = needle.rstrip("0").rstrip(".")
            matches |= frame[name].astype("string").str.contains(
                needle, case=False, regex=False, na=False
            )
        selected = frame.loc[matches]
    count = len(selected)
    page_count = (count + JTD_PAGE_SIZE - 1) // JTD_PAGE_SIZE
    page_current = min(max(int(page_current or 0), 0), max(page_count - 1, 0))
    start = page_current * JTD_PAGE_SIZE
    page = selected.iloc[start:start + JTD_PAGE_SIZE]
    records = page.astype(object).where(page.notna(), None).to_dict("records")
    note = (
        f"{start + 1:,}–{start + len(page):,} of {count:,} matching rows · |Risk JTD| largest first"
        if count else "No matching JTD reference rows."
    )
    return records, page_count, page_current, note


__all__ = [
    "JTD_REFERENCE_PATH", "JTD_NUMERIC_COLUMNS", "JTD_PAGE_SIZE",
    "JTDReferenceError", "jtd_reference_rows", "jtd_page",
]
```

The cache still holds one complete reference file. Pagination reduces browser payload and HTML size; it does not remove the server's need to read that CSV. Updating its modification time or size invalidates the cached version. Use the normal file-writing process rather than preserving an old modification timestamp on a changed file.

## Step 3 — Replace only the JTD table builder

**File:** `cube/pages/risk/s13_workspacetables.py`.

1. Replace `from dash import dash_table, html` with:

```python
from dash import dash_table, dcc, html
```

2. Add this import beside the existing `cube.*` imports:

```python
from cube.services.s08_jtd import JTD_PAGE_SIZE, jtd_page
```

3. Keep the existing `from dash.dash_table.Format import Format, Scheme` import. Replace the entire `build_jtd_reference_table()` function, stopping immediately before `def build_new_trade_detail_table(`, with this function. Keep all other table builders unchanged.

```python
def build_jtd_reference_table(
    frame: pd.DataFrame | None,
    underlying: str | list[str] | None,
    *,
    error: str | None = None,
) -> html.Div:
    keys = [underlying] if isinstance(underlying, str) else list(underlying or [])
    label = keys[0] if len(keys) == 1 else f"{len(keys):,} underlyings"
    title = f"JTD reference — {label}" if keys else "JTD reference"
    if error:
        content = html.Div(error, className="empty-state", role="status")
    elif frame is None or frame.empty:
        content = html.Div(
            "No JTD reference rows for this selection." if keys
            else "Select an Underlying row to show its JTD reference.",
            className="empty-state", role="status",
        )
    else:
        numeric = [c for c in frame if pd.api.types.is_numeric_dtype(frame[c])]
        columns = [
            {"name": column, "id": column, "type": "numeric",
             "format": Format(precision=2, scheme=Scheme.fixed, group=True, nully="—")}
            if column in numeric else {"name": column, "id": column, "type": "text"}
            for column in frame
        ]
        records, page_count, page_current, note = jtd_page(frame)
        content = html.Div([
            dcc.Store(id="jtd-scope", data=keys),
            html.Div([
                dcc.Dropdown(
                    id="jtd-search-column",
                    options=[{"label": "All columns", "value": "__all__"}]
                    + [{"label": c, "value": c} for c in frame],
                    value="__all__", clearable=False,
                    style={"minWidth": "190px", "flex": "1"},
                ),
                dcc.Input(
                    id="jtd-search", type="search", value="", debounce=0.3,
                    placeholder="Search CRDS or any column…",
                    style={"minWidth": "200px", "flex": "2", "padding": "8px"},
                ),
            ], style={"display": "flex", "gap": "8px", "flexWrap": "wrap", "marginBottom": "8px"}),
            html.Div(note, id="jtd-page-note", role="status", style={"marginBottom": "8px"}),
            dcc.Loading(dash_table.DataTable(
                id="jtd-table", columns=columns, data=records,
                page_action="custom", page_current=page_current,
                page_size=JTD_PAGE_SIZE, page_count=page_count,
                sort_action="none", filter_action="none",
                style_table={"overflowX": "auto"},
                style_cell={"padding": "7px 10px", "fontSize": 13, "textAlign": "left",
                            "backgroundColor": "white", "color": "#111111"},
                style_header={"fontWeight": "600", "backgroundColor": "#f3f4f6"},
                style_cell_conditional=[
                    {"if": {"column_id": c}, "textAlign": "right"} for c in numeric
                ],
                style_data_conditional=[
                    {"if": {"column_id": c, "filter_query": "{" + c + "} < 0"},
                     "color": "#b91c1c"} for c in numeric
                ],
            )),
        ])
    return html.Div(
        [html.H3(title, className="jtd-reference-title"), content],
        className="jtd-reference-card", **{"aria-label": title},
    )
```

The default order is deliberately fixed to absolute Risk JTD. Header sorting is disabled so a native page-only sort cannot misleadingly rearrange just 25 rows. The requested search and default ranking work across the complete selected result. Clear the search box to return to that default view.

## Step 4 — Connect paging and repair the missing detail path

**File:** `cube/pages/risk/s07_explorer.py`.

### 4.1 Add the two needed helpers to existing imports

Add `frame_for_context,` to the existing parenthesized import from `cube.ui.s02_aggregation`.

Replace this import:

```python
from cube.services.s08_jtd import JTDReferenceError, jtd_reference_rows
```

with:

```python
from cube.services.s08_jtd import JTDReferenceError, jtd_page, jtd_reference_rows
```

Keep the existing imports for `Input`, `Output` and `ctx`.

### 4.2 Add the page/search callback once

Inside `register_explorer_callbacks()`, immediately after its docstring and before the first existing `app.clientside_callback(...)`, insert the following. The four-space indentation is intentional: this callback belongs inside the registration function. Do not add a second callback for these outputs.

```python
    @app.callback(
        Output("jtd-table", "data"),
        Output("jtd-table", "page_count"),
        Output("jtd-table", "page_current"),
        Output("jtd-page-note", "children"),
        Input("jtd-scope", "data"),
        Input("jtd-table", "page_current"),
        Input("jtd-search", "value"),
        Input("jtd-search-column", "value"),
    )
    def update_jtd_page(underlyings, page_current, search, column):
        reset_inputs = {"jtd-scope.data", "jtd-search.value", "jtd-search-column.value"}
        if reset_inputs.intersection(ctx.triggered_prop_ids):
            page_current = 0
        try:
            frame = jtd_reference_rows(underlyings or [])
            return jtd_page(frame, page_current, search, column or "__all__")
        except JTDReferenceError as error:
            return [], 0, 0, str(error)
```

Changing the selection, search text or search column returns to page one. Page navigation keeps the search. The same callback both reads and returns `page_current` so a shortened result cannot leave the user on a now-nonexistent page; this is one callback, not a circular chain between callbacks.

### 4.3 Replace the old JTD selection block

Inside the nested `render_active_detail()` function, find the block starting:

```python
        effective_credit_measure = selected_credit_measure
```

Replace that block through the end of its JTD-loading `if` statement, stopping immediately **before** the existing `return build_detail_panel_with_state(...)`. Insert:

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
            if "underlying" in selected_context or "reported underlying" in selected_context:
                scoped = frame_for_context(filtered, selected_context)
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
                    jtd_error = "No raw Underlying values remain in this selection."
            else:
                jtd_error = "Select an Underlying row to show its JTD reference."
```

Keep the existing return call, including `jtd_reference=`, `jtd_underlying=` and `jtd_error=`. Here `jtd_underlying` now carries a list of raw names. A raw row normally produces one name. A reported row can produce several; `isin()` returns each matching CSV row once, even if that raw identity occurs in many risk positions. No summing or deduplication of the reference's financial rows is introduced.

The rest of `render_active_detail()`, including new-trade detail and the existing Risk frame filtering, stays in place. Do not loosen the delegated click validation or remove the current view-token checks to make clicks appear to work.

## Step 5 — Widen the two existing type annotations

**File:** `cube/pages/risk/s05_charts.py`.

There are exactly two JTD argument declarations, in `_build_detail_panel_from_frame()` and `build_detail_panel_with_state()`. In both functions replace:

```python
    jtd_underlying: str | None = None,
```

with:

```python
    jtd_underlying: str | list[str] | None = None,
```

Keep the existing call to `build_jtd_reference_table()` and every chart/table branch. The JTD reference remains a sibling above the normal tenor chart and detail table. No other plot changes are needed for this guide.

## Step 6 — Replace the obsolete HTML-table test and check the result

**File:** `tests/s48_jtd.py`.

The old last test specifically requires `html.Table`; it must change because the requested paging table is now a `dash_table.DataTable`. Replace this small test file with:

```python
"""JTD lookup, paging and display contract regressions."""
from collections.abc import Iterable

import pandas as pd
import pytest
from dash import dash_table

from cube.pages.risk.s13_workspacetables import build_jtd_reference_table
from cube.services.s08_jtd import JTDReferenceError, jtd_page, jtd_reference_rows


def _walk(component: object) -> Iterable[object]:
    yield component
    children = getattr(component, "children", None)
    for child in children if isinstance(children, (list, tuple)) else [children]:
        if child is not None:
            yield from _walk(child)


def test_exact_identity_keeps_columns_and_identifier_text(tmp_path):
    path = tmp_path / "s13_jtd.csv"
    pd.DataFrame({
        "Underlying": ["ACME", "Acme", "ACME"],
        "CRDS": ["000001", "000002", "000003"],
        "Risk JTD": ["-9,000", "99999", "8000"],
        "EAD": ["1,234.50", "0", "-25"],
        "Comment": ["Watch", "Excluded", "Other"],
    }).to_csv(path, index=False)
    result = jtd_reference_rows("ACME", path=path)
    assert list(result.columns) == ["Underlying", "CRDS", "Risk JTD", "EAD", "Comment"]
    assert result["CRDS"].tolist() == ["000001", "000003"]
    assert result["Risk JTD"].tolist() == [-9000, 8000]
    assert result["EAD"].tolist() == [1234.5, -25]


@pytest.mark.parametrize("body, message", [
    ("Issuer\nX\n", "Underlying"),
    ("", "Could not read"),
    ("Underlying,Risk JTD\nX,bad\n", "invalid numbers"),
    ("Underlying,Risk JTD\nX,inf\n", "invalid numbers"),
    ("Underlying,EAD\nX,1\n", "Risk JTD"),
])
def test_bad_files_fail_clearly(tmp_path, body, message):
    path = tmp_path / "s13_jtd.csv"
    path.write_text(body, encoding="utf-8")
    with pytest.raises(JTDReferenceError, match=message):
        jtd_reference_rows("X", path=path)


def test_page_search_and_numeric_display(tmp_path):
    path = tmp_path / "s13_jtd.csv"
    pd.DataFrame({
        "Underlying": ["ACME"] * 61,
        "CRDS": [f"{i:06d}" for i in range(61)],
        "Risk JTD": [-9000, 8000, None] + list(range(58)),
        "EAD": ["1,234.50", "-12.25", ""] + ["0"] * 58,
        "Comment": ["literal[match"] + ["ordinary"] * 60,
    }).to_csv(path, index=False)
    frame = jtd_reference_rows(["ACME", "ACME"], path=path)
    assert len(frame) == 61  # Repeated identities must not duplicate CSV rows.
    records, count, page, _ = jtd_page(frame)
    assert len(records) == 25 and count == 3 and page == 0
    assert [r["Risk JTD"] for r in records[:2]] == [-9000, 8000]
    records, count, page, _ = jtd_page(frame, 999)
    assert len(records) == 11 and page == 2 and records[-1]["Risk JTD"] is None
    assert jtd_page(frame, 2, "000059", "CRDS")[0][0]["CRDS"] == "000059"
    assert len(jtd_page(frame, 0, "literal[match")[0]) == 1
    assert len(jtd_page(frame, 0, "1,234", "EAD")[0]) == 1
    assert len(jtd_page(frame, 0, "1,234.50", "EAD")[0]) == 1
    assert jtd_page(frame, 2, "missing")[0:3] == ([], 0, 0)
    component = build_jtd_reference_table(frame, "ACME")
    table = next(item for item in _walk(component) if isinstance(item, dash_table.DataTable))
    assert table.page_action == "custom" and len(table.data) == 25
    assert table.style_cell["color"] == "#111111"
    assert {rule["if"]["column_id"] for rule in table.style_data_conditional} == {"Risk JTD", "EAD"}
    assert all(rule["color"] == "#b91c1c" for rule in table.style_data_conditional)
    ead = next(c for c in table.columns if c["id"] == "EAD")
    assert ead["type"] == "numeric"
    assert ead["format"].to_plotly_json()["specifier"] == ",.2f"
    assert next(c for c in table.columns if c["id"] == "CRDS")["type"] == "text"
```

Run from the repository root with your existing app environment:

```powershell
python -m pytest tests/s48_jtd.py -q
python -m compileall -q cube/services/s08_jtd.py cube/pages/risk/s13_workspacetables.py cube/pages/risk/s07_explorer.py cube/pages/risk/s05_charts.py
git diff --check
```

Restart the app after completing every step. Then check:

1. **Credit → Cross → JTD:** click an Underlying metric cell. Check the reference card appears above the tenor content. In multi-measure mode, click the JTD column specifically.
2. **Credit → SplitVA:** select JTD using its credit-measure selector, then click an Underlying cell. Check the reference appears here too, including when the retained Credit view setting was previously multi.
3. Test raw identity mode and reported identity mode. A reported label different from the raw feed name must still find the correct rows. A reported label containing two raw names must show each CSV row once.
4. Use a reference selection with more than 50 rows. Check page one, next page, last page and direct page navigation. The browser callback response must contain at most 25 records, even though the matching-row count is larger.
5. From a later page, search for a CRDS that was not on that page. It must be found and the table must return to page one. Test **All columns**, then choose **CRDS**, a text column and **EAD** individually.
6. Check `-9000`, `8000`, `0` and a blank. The initial order uses absolute Risk JTD; numbers display as `-9,000.00`, `8,000.00`, `0.00` and a dash. Negative EAD must be red too. CRDS `000123` must retain its zeros.
7. Clear the search, choose another risk row, change the active risk filters and refresh the data. Each rebuilt card must represent the current selection and start on page one.
8. A missing source file, missing Risk JTD header in a populated file, or invalid numeric data must produce a readable message instead of a falsely complete table. An empty or unmatched selection must produce an empty-state message.

**Validation performed while writing this guide:** the exact snippets were applied to a separate copy of the pinned source. The replacement test file passed **7 tests**. A further isolated check verified callback registration, exact Cross/alternate selection-block execution, active-context filtering and reported-to-raw identity resolution. The four modified Python modules compiled. The DataTable column definitions and conditional colors were inspected in those checks; a live production browser and your populated JTD feed were not available, so the eight UI checks above are still required after implementation. The existing Dash DataTable emitted its deprecation warning; this guide adds no dependency and stays on the repository's pinned Dash version.

## What to keep, and how to undo this change

Keep the normal Risk calculations, credit measure definitions, tenor charts, refresh logic, data revision handling and all other table builders. Do not convert the complete reference to a browser Store. Do not replace custom paging with native pagination while sending every row.

To undo the UI change, restore your pre-change versions of these four Python modules and `tests/s48_jtd.py` together, then restart. Restore `data/s13_jtd.csv` only if you also want to undo your source-data change; do not overwrite newer production data as part of a UI rollback.

The implementation uses the existing Dash support for [server paging](https://dash.plotly.com/datatable/callbacks), [numeric display formats](https://dash.plotly.com/datatable/data-formatting) and [conditional text color](https://dash.plotly.com/datatable/conditional-formatting). Filtering happens before slicing a page, so search covers the complete selected result.
