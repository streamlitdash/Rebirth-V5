"""Pure native-pivot calculation and components for V4 Custom views."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from dash import dcc, html

from rebirth.domain.s11_riskviews import (
    CROSS_PIVOT_SPEC,
    RISK_VIEW_DIMENSIONS,
    RISK_VIEW_MEASURES,
    PivotSpec,
)
from rebirth.ui.s02_aggregation import format_number

from .s06_explorertables import build_tree_rows


_MARKET_MEASURES = frozenset({"open", "current", "move"})
_FIELD_LABELS = {
    "drisk": "dRisk",
    "pl": "P&L",
    "splitva": "SplitVA",
    "signoffgroup": "Signoff Group",
}


def pivot_field_label(value: object) -> str:
    """Return a compact label without changing the persisted canonical key."""

    key = str(value).strip().casefold()
    return _FIELD_LABELS.get(key, key.title())


def _options(values: Sequence[str]) -> list[dict[str, str]]:
    return [{"label": pivot_field_label(value), "value": value} for value in values]


def build_custom_risk_pivot_workspace() -> html.Div:
    """Build stable Custom-view stores, controls, and the lazy result panel."""

    initial = CROSS_PIVOT_SPEC.to_dict()
    return html.Div(
        [
            dcc.Store(id="risk-custom-pivot-applied", data=initial),
            dcc.Store(id="risk-custom-pivot-command", data=None),
            dcc.Store(id="risk-custom-open-rows", data=[]),
            dcc.Store(id="risk-custom-view-token", data=None),
            dcc.Store(id="risk-pivot-filter-command-values", data=[]),
            dcc.Interval(
                id="risk-custom-view-refresh",
                interval=100,
                max_intervals=1,
                n_intervals=0,
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label(
                                "Saved Custom view", htmlFor="risk-custom-view-selector"
                            ),
                            dcc.Dropdown(
                                id="risk-custom-view-selector",
                                options=[],
                                value=None,
                                placeholder="Choose a saved view",
                                clearable=True,
                            ),
                        ],
                        className="control-field risk-custom-view-selector",
                    ),
                    html.Div(
                        [
                            html.Label("View name", htmlFor="risk-custom-view-name"),
                            dcc.Input(
                                id="risk-custom-view-name",
                                type="text",
                                value="",
                                debounce=False,
                                placeholder="For save, clone, or rename",
                            ),
                        ],
                        className="control-field risk-custom-view-name",
                    ),
                    html.Div(
                        [
                            html.Button("New", id="risk-custom-view-new", n_clicks=0),
                            html.Button(
                                "Clone Cross",
                                id="risk-custom-view-clone-cross",
                                n_clicks=0,
                            ),
                            html.Button(
                                "Clone SplitVA",
                                id="risk-custom-view-clone-splitva",
                                n_clicks=0,
                            ),
                            html.Button("Edit", id="risk-custom-view-edit", n_clicks=0),
                            html.Button(
                                "Save copy",
                                id="risk-custom-view-save-copy",
                                n_clicks=0,
                            ),
                            html.Button(
                                "Rename",
                                id="risk-custom-view-rename",
                                n_clicks=0,
                            ),
                            html.Button(
                                "Delete",
                                id="risk-custom-view-delete",
                                n_clicks=0,
                                className="risk-custom-view-delete",
                            ),
                        ],
                        className="risk-custom-view-actions",
                    ),
                    html.Div(
                        "Custom Risk Views store presentation settings only.",
                        id="risk-custom-view-status",
                        className="risk-custom-view-status",
                        role="status",
                    ),
                ],
                className="risk-custom-view-bar",
            ),
            html.Details(
                [
                    html.Summary(
                        "Build this view", className="risk-pivot-drawer-summary"
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label(
                                        "Group rows by", htmlFor="risk-pivot-rows"
                                    ),
                                    dcc.Dropdown(
                                        id="risk-pivot-rows",
                                        options=_options(RISK_VIEW_DIMENSIONS),
                                        value=list(CROSS_PIVOT_SPEC.rows),
                                        multi=True,
                                        clearable=False,
                                    ),
                                ],
                                className="control-field",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Split columns by (optional)",
                                        htmlFor="risk-pivot-columns",
                                    ),
                                    dcc.Dropdown(
                                        id="risk-pivot-columns",
                                        options=_options(RISK_VIEW_DIMENSIONS),
                                        value=list(CROSS_PIVOT_SPEC.columns),
                                        multi=True,
                                    ),
                                ],
                                className="control-field",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Show values", htmlFor="risk-pivot-measures"
                                    ),
                                    dcc.Dropdown(
                                        id="risk-pivot-measures",
                                        options=_options(RISK_VIEW_MEASURES),
                                        value=list(CROSS_PIVOT_SPEC.measures),
                                        multi=True,
                                        clearable=False,
                                    ),
                                ],
                                className="control-field",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Limit to", htmlFor="risk-pivot-filter-field"
                                    ),
                                    dcc.Dropdown(
                                        id="risk-pivot-filter-field",
                                        options=_options(RISK_VIEW_DIMENSIONS),
                                        value=None,
                                        placeholder="Optional field",
                                    ),
                                    dcc.Dropdown(
                                        id="risk-pivot-filter-values",
                                        options=[],
                                        value=[],
                                        multi=True,
                                        placeholder="All values",
                                    ),
                                    html.Span(
                                        "Choose a field, then select values.",
                                        id="risk-pivot-filter-status",
                                        className="risk-pivot-filter-status",
                                        role="status",
                                    ),
                                ],
                                className="control-field risk-pivot-filter-control",
                            ),
                            html.Details(
                                [
                                    html.Summary("More options"),
                                    html.Div(
                                        [
                                            html.Div(
                                                [
                                                    html.Label(
                                                        "Sort",
                                                        htmlFor="risk-pivot-sort-field",
                                                    ),
                                                    dcc.Dropdown(
                                                        id="risk-pivot-sort-field",
                                                        options=_options(
                                                            (
                                                                *RISK_VIEW_DIMENSIONS,
                                                                *RISK_VIEW_MEASURES,
                                                            )
                                                        ),
                                                        value=None,
                                                        placeholder="Natural order",
                                                    ),
                                                    dcc.RadioItems(
                                                        id="risk-pivot-sort-direction",
                                                        options=[
                                                            {
                                                                "label": "Ascending",
                                                                "value": "asc",
                                                            },
                                                            {
                                                                "label": "Descending",
                                                                "value": "desc",
                                                            },
                                                        ],
                                                        value="asc",
                                                        inline=True,
                                                    ),
                                                ],
                                                className="control-field",
                                            ),
                                            html.Div(
                                                [
                                                    html.Label("Totals"),
                                                    dcc.Checklist(
                                                        id="risk-pivot-totals",
                                                        options=[
                                                            {
                                                                "label": "Rows",
                                                                "value": "rows",
                                                            },
                                                            {
                                                                "label": "Columns",
                                                                "value": "columns",
                                                            },
                                                            {
                                                                "label": "Grand",
                                                                "value": "grand",
                                                            },
                                                        ],
                                                        value=["rows", "grand"],
                                                        inline=True,
                                                    ),
                                                ],
                                                className="control-field",
                                            ),
                                            html.Div(
                                                [
                                                    html.Label("Display"),
                                                    html.Div(
                                                        [
                                                            dcc.Input(
                                                                id="risk-pivot-row-limit",
                                                                type="number",
                                                                min=10,
                                                                max=500,
                                                                step=10,
                                                                value=CROSS_PIVOT_SPEC.row_limit,
                                                            ),
                                                            dcc.Input(
                                                                id="risk-pivot-column-limit",
                                                                type="number",
                                                                min=1,
                                                                max=50,
                                                                step=1,
                                                                value=CROSS_PIVOT_SPEC.column_limit,
                                                            ),
                                                            dcc.Dropdown(
                                                                id="risk-pivot-density",
                                                                options=[
                                                                    {
                                                                        "label": "Compact",
                                                                        "value": "compact",
                                                                    },
                                                                    {
                                                                        "label": "Comfortable",
                                                                        "value": "comfortable",
                                                                    },
                                                                ],
                                                                value=CROSS_PIVOT_SPEC.density,
                                                                clearable=False,
                                                            ),
                                                        ],
                                                        className="risk-pivot-display-grid",
                                                    ),
                                                    dcc.Checklist(
                                                        id="risk-pivot-display-flags",
                                                        options=[
                                                            {
                                                                "label": "Show zeros",
                                                                "value": "zeros",
                                                            },
                                                            {
                                                                "label": "Sticky headers",
                                                                "value": "sticky",
                                                            },
                                                        ],
                                                        value=["sticky"],
                                                        inline=True,
                                                    ),
                                                ],
                                                className="control-field",
                                            ),
                                            html.Div(
                                                [
                                                    html.Label(
                                                        "Presets",
                                                        htmlFor="risk-pivot-preset",
                                                    ),
                                                    dcc.Dropdown(
                                                        id="risk-pivot-preset",
                                                        options=[
                                                            {
                                                                "label": "Cross",
                                                                "value": "cross",
                                                            },
                                                            {
                                                                "label": "SplitVA",
                                                                "value": "splitva",
                                                            },
                                                        ],
                                                        value="cross",
                                                        clearable=False,
                                                    ),
                                                    html.Button(
                                                        "Use preset",
                                                        id="risk-pivot-use-preset",
                                                        n_clicks=0,
                                                    ),
                                                ],
                                                className="control-field",
                                            ),
                                        ],
                                        className="risk-pivot-advanced-grid",
                                    ),
                                ],
                                className="risk-pivot-more-options",
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Update table",
                                        id="risk-pivot-apply",
                                        n_clicks=0,
                                        className="refresh-button",
                                    ),
                                    html.Span(
                                        "Cross preset is active.",
                                        id="risk-pivot-editor-status",
                                        role="status",
                                    ),
                                    html.Span(
                                        "Table is up to date.",
                                        id="risk-pivot-dirty-status",
                                        className="risk-pivot-dirty-status",
                                        role="status",
                                    ),
                                ],
                                className="risk-pivot-apply-row",
                            ),
                        ],
                        className="risk-pivot-field-grid",
                    ),
                ],
                open=True,
                className="risk-pivot-field-drawer",
            ),
            html.Div(
                [
                    html.Label("Row batch", htmlFor="risk-pivot-row-page"),
                    dcc.Input(
                        id="risk-pivot-row-page",
                        type="number",
                        min=1,
                        max=1,
                        step=1,
                        value=1,
                    ),
                    html.Label("Column batch", htmlFor="risk-pivot-column-page"),
                    dcc.Input(
                        id="risk-pivot-column-page",
                        type="number",
                        min=1,
                        max=1,
                        step=1,
                        value=1,
                    ),
                    html.Span(
                        "Custom pivot loads only when this tab is selected.",
                        id="risk-pivot-viewport-status",
                        role="status",
                    ),
                ],
                className="risk-pivot-viewport-controls",
            ),
            html.Div(id="risk-custom-grid", className="risk-grid"),
        ],
        id="custom-risk-panel",
        className="risk-panel risk-custom-panel",
        style={"display": "none"},
    )


def pivot_spec_from_controls(
    *,
    rows: Sequence[str] | None,
    columns: Sequence[str] | None,
    measures: Sequence[str] | None,
    filter_field: str | None,
    filter_values: Sequence[str] | None,
    sort_field: str | None,
    sort_direction: str | None,
    totals: Sequence[str] | None,
    row_limit: object,
    column_limit: object,
    density: str | None,
    display_flags: Sequence[str] | None,
) -> PivotSpec:
    """Validate the compact editor through the authoritative PivotSpec parser."""

    selected_filter = str(filter_field or "").strip().casefold()
    filters = {selected_filter: list(filter_values or ())} if selected_filter else {}
    selected_sort = str(sort_field or "").strip().casefold()
    sort = (
        [
            {
                "field": selected_sort,
                "direction": str(sort_direction or "asc").strip().casefold(),
            }
        ]
        if selected_sort
        else []
    )
    selected_totals = set(totals or ())
    flags = set(display_flags or ())
    payload = {
        "rows": list(rows or ()),
        "columns": list(columns or ()),
        "measures": list(measures or ()),
        "filters": filters,
        "sort": sort,
        "totals": {
            "rows": "rows" in selected_totals,
            "columns": "columns" in selected_totals,
            "grand": "grand" in selected_totals,
        },
        "display": {
            "row_limit": int(row_limit),
            "column_limit": int(column_limit),
            "density": str(density or "compact"),
            "show_zeros": "zeros" in flags,
            "sticky_headers": "sticky" in flags,
        },
    }
    return PivotSpec.from_dict(payload)


def pivot_control_values(spec: PivotSpec) -> tuple[object, ...]:
    """Return editor values for a validated persisted specification."""

    first_filter = spec.filters[0] if spec.filters else (None, ())
    first_sort = spec.sort[0] if spec.sort else (None, "asc")
    totals = [
        value
        for value, enabled in (
            ("rows", spec.row_totals),
            ("columns", spec.column_totals),
            ("grand", spec.grand_total),
        )
        if enabled
    ]
    flags = [
        value
        for value, enabled in (
            ("zeros", spec.show_zeros),
            ("sticky", spec.sticky_headers),
        )
        if enabled
    ]
    return (
        list(spec.rows),
        list(spec.columns),
        list(spec.measures),
        first_filter[0],
        list(first_filter[1]),
        first_sort[0],
        first_sort[1],
        totals,
        spec.row_limit,
        spec.column_limit,
        spec.density,
        flags,
    )


@dataclass(frozen=True)
class NativePivotResult:
    """One complete logical pivot narrowed to a browser-safe viewport."""

    spec: PivotSpec
    row_keys: tuple[tuple[str, ...], ...]
    column_keys: tuple[tuple[str, ...], ...]
    values: Mapping[tuple[tuple[str, ...], tuple[str, ...], str], float]
    row_totals: Mapping[tuple[tuple[str, ...], str], float]
    column_totals: Mapping[tuple[tuple[str, ...], str], float]
    grand_totals: Mapping[str, float]
    row_count: int
    column_count: int
    row_offset: int
    column_offset: int

    @property
    def row_page_count(self) -> int:
        return max(1, math.ceil(self.row_count / self.spec.row_limit))

    @property
    def column_page_count(self) -> int:
        return max(1, math.ceil(self.column_count / self.spec.column_limit))


def _text_frame(frame: pd.DataFrame, fields: Sequence[str]) -> pd.DataFrame:
    scoped = frame.copy(deep=False)
    if not fields:
        return scoped
    scoped = scoped.copy()
    for field in fields:
        scoped[field] = scoped[field].fillna("Unspecified").astype(str)
    return scoped


def _filter_frame(frame: pd.DataFrame, spec: PivotSpec) -> pd.DataFrame:
    scoped = frame
    for field, selected in spec.filters:
        if not selected:
            continue
        wanted = {value.strip().casefold() for value in selected}
        values = scoped[field].astype("string").str.strip().str.casefold()
        scoped = scoped.loc[values.isin(wanted).fillna(False)]
    return scoped


def _key(value: object, width: int) -> tuple[str, ...]:
    if width == 0:
        return ()
    values = value if isinstance(value, tuple) else (value,)
    return tuple(str(item) for item in values)


def _group_values(
    frame: pd.DataFrame,
    fields: Sequence[str],
    measures: Sequence[str],
) -> dict[tuple[str, ...], dict[str, float]]:
    """Aggregate additive values quickly and quotes once per market identity."""

    if frame.empty:
        return {}
    selected = tuple(measures)
    additive = tuple(measure for measure in selected if measure not in _MARKET_MEASURES)
    market = tuple(measure for measure in selected if measure in _MARKET_MEASURES)
    result: dict[tuple[str, ...], dict[str, float]] = {}
    if additive:
        if fields:
            sums = frame.groupby(list(fields), dropna=False, sort=False)[
                list(additive)
            ].sum(min_count=1)
            for raw_key, record in sums.iterrows():
                key = _key(raw_key, len(fields))
                result[key] = {measure: float(record[measure]) for measure in additive}
        else:
            sums = frame.loc[:, list(additive)].sum(min_count=1)
            result[()] = {measure: float(sums[measure]) for measure in additive}

    if market:

        def unique_fields(*groups: Sequence[str]) -> list[str]:
            return list(dict.fromkeys(field for group in groups for field in group))

        identity = (
            "risk type",
            "risk greek",
            "underlying",
            "tenor swap",
            "tenor option",
        )
        quote_dimensions = unique_fields(fields, identity)
        quotes = frame.loc[:, [*quote_dimensions, *market]].drop_duplicates()
        option_dimensions = unique_fields(
            fields,
            ("underlying", "tenor swap", "tenor option"),
        )
        option_values = quotes.groupby(
            option_dimensions,
            as_index=False,
            dropna=False,
            sort=False,
        )[list(market)].mean()
        swap_dimensions = unique_fields(fields, ("underlying", "tenor swap"))
        swap_values = option_values.groupby(
            swap_dimensions,
            as_index=False,
            dropna=False,
            sort=False,
        )[list(market)].mean()
        underlying_dimensions = unique_fields(fields, ("underlying",))
        underlying_values = swap_values.groupby(
            underlying_dimensions,
            as_index=False,
            dropna=False,
            sort=False,
        )[list(market)].mean()
        if fields:
            market_values = underlying_values.groupby(
                list(fields),
                dropna=False,
                sort=False,
            )[list(market)].mean()
            for raw_key, record in market_values.iterrows():
                key = _key(raw_key, len(fields))
                result.setdefault(key, {}).update(
                    {measure: float(record[measure]) for measure in market}
                )
        else:
            means = underlying_values.loc[:, list(market)].mean()
            result.setdefault((), {}).update(
                {measure: float(means[measure]) for measure in market}
            )
    return result


def _ordered_keys(
    keys: Sequence[tuple[str, ...]],
    fields: Sequence[str],
    sort: Sequence[tuple[str, str]],
    measure_totals: Mapping[tuple[tuple[str, ...], str], float],
) -> list[tuple[str, ...]]:
    ordered = list(dict.fromkeys(keys))
    for field, direction in reversed(tuple(sort)):
        reverse = direction == "desc"
        if field in fields:
            position = tuple(fields).index(field)
            ordered.sort(
                key=lambda value: value[position].casefold(),
                reverse=reverse,
            )
        elif field in RISK_VIEW_MEASURES:

            def measure_key(value: tuple[str, ...]) -> tuple[bool, float]:
                numeric = measure_totals.get((value, field), float("nan"))
                return (bool(pd.isna(numeric)), -numeric if reverse else numeric)

            ordered.sort(key=measure_key)
    return ordered


def compute_native_pivot(
    frame: pd.DataFrame,
    spec: PivotSpec | Mapping[str, object],
    *,
    row_page: int = 1,
    column_page: int = 1,
) -> NativePivotResult:
    """Compute the full logical pivot and return one bounded row/column page."""

    selected = spec if isinstance(spec, PivotSpec) else PivotSpec.from_dict(spec)
    required = set((*selected.rows, *selected.columns, *selected.measures))
    required.update(field for field, _values in selected.filters)
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Custom pivot source is missing fields: {missing}")

    fields = tuple(dict.fromkeys((*selected.rows, *selected.columns)))
    scoped = _filter_frame(_text_frame(frame, fields), selected)
    cell_groups = _group_values(scoped, fields, selected.measures)
    row_groups = _group_values(scoped, selected.rows, selected.measures)
    column_groups = (
        _group_values(scoped, selected.columns, selected.measures)
        if selected.columns
        else {}
    )
    grand_group = _group_values(scoped, (), selected.measures)

    row_total_lookup = {
        (key, measure): value
        for key, values in row_groups.items()
        for measure, value in values.items()
    }
    row_keys = _ordered_keys(
        list(row_groups),
        selected.rows,
        selected.sort,
        row_total_lookup,
    )
    if selected.columns:
        column_keys = _ordered_keys(
            list(column_groups),
            selected.columns,
            selected.sort,
            {
                (key, measure): value
                for key, values in column_groups.items()
                for measure, value in values.items()
            },
        )
    else:
        column_keys = [()]

    requested_row_page = max(1, int(row_page or 1))
    requested_column_page = max(1, int(column_page or 1))
    row_pages = max(1, math.ceil(len(row_keys) / selected.row_limit))
    column_pages = max(1, math.ceil(len(column_keys) / selected.column_limit))
    effective_row_page = min(requested_row_page, row_pages)
    effective_column_page = min(requested_column_page, column_pages)
    row_offset = (effective_row_page - 1) * selected.row_limit
    column_offset = (effective_column_page - 1) * selected.column_limit
    visible_rows = tuple(row_keys[row_offset : row_offset + selected.row_limit])
    visible_columns = tuple(
        column_keys[column_offset : column_offset + selected.column_limit]
    )

    values: dict[tuple[tuple[str, ...], tuple[str, ...], str], float] = {}
    for compound_key, record in cell_groups.items():
        row_key = compound_key[: len(selected.rows)]
        column_key = compound_key[len(selected.rows) :]
        if row_key not in visible_rows or column_key not in visible_columns:
            continue
        for measure, value in record.items():
            values[(row_key, column_key, measure)] = value

    row_totals = {
        key: value for key, value in row_total_lookup.items() if key[0] in visible_rows
    }
    column_totals = {
        (key, measure): value
        for key, record in column_groups.items()
        if key in visible_columns
        for measure, value in record.items()
    }
    return NativePivotResult(
        spec=selected,
        row_keys=visible_rows,
        column_keys=visible_columns,
        values=values,
        row_totals=row_totals,
        column_totals=column_totals,
        grand_totals=grand_group.get((), {}),
        row_count=len(row_keys),
        column_count=len(column_keys),
        row_offset=row_offset,
        column_offset=column_offset,
    )


def _display_value(value: float | None, measure: str, *, show_zeros: bool) -> str:
    if value is None or pd.isna(value):
        return ""
    if not show_zeros and bool(np.isclose(float(value), 0.0)):
        return ""
    return format_number(float(value), column=measure)


def _metric_cell(value: float | None, measure: str, *, show_zeros: bool) -> html.Td:
    rendered = _display_value(value, measure, show_zeros=show_zeros)
    sign = ""
    if value is not None and not pd.isna(value):
        sign = " number-negative" if float(value) < 0 else " number-positive"
    return html.Td(rendered, className=f"risk-native-pivot-value{sign}")


def build_native_pivot_table(result: NativePivotResult) -> html.Div:
    """Render a semantic table containing only the bounded result viewport."""

    if result.row_count == 0:
        return html.Div(
            "No rows match this Custom pivot.",
            className="empty-state",
            role="status",
        )
    spec = result.spec
    header_cells = [
        html.Th(
            pivot_field_label(field), scope="col", className="risk-pivot-row-header"
        )
        for field in spec.rows
    ]
    if spec.columns:
        for column_key in result.column_keys:
            column_label = " · ".join(column_key)
            for measure in spec.measures:
                header_cells.append(
                    html.Th(
                        f"{column_label} · {pivot_field_label(measure)}",
                        scope="col",
                        title=column_label,
                    )
                )
        if spec.row_totals:
            header_cells.extend(
                html.Th(
                    f"Total · {pivot_field_label(measure)}",
                    scope="col",
                    className="total-column",
                )
                for measure in spec.measures
            )
    else:
        header_cells.extend(
            html.Th(pivot_field_label(measure), scope="col")
            for measure in spec.measures
        )

    rows: list[html.Tr] = []
    for row_key in result.row_keys:
        cells: list[object] = [
            html.Th(value, scope="row" if position == 0 else None)
            if position == 0
            else html.Td(value)
            for position, value in enumerate(row_key)
        ]
        for column_key in result.column_keys:
            cells.extend(
                _metric_cell(
                    result.values.get((row_key, column_key, measure)),
                    measure,
                    show_zeros=spec.show_zeros,
                )
                for measure in spec.measures
            )
        if spec.columns and spec.row_totals:
            cells.extend(
                _metric_cell(
                    result.row_totals.get((row_key, measure)),
                    measure,
                    show_zeros=spec.show_zeros,
                )
                for measure in spec.measures
            )
        rows.append(html.Tr(cells))

    if spec.column_totals or spec.grand_total:
        label = "Grand total" if spec.grand_total else "Column total"
        total_cells: list[object] = [
            html.Th(label, scope="row", colSpan=len(spec.rows), className="total-index")
        ]
        if spec.columns:
            for column_key in result.column_keys:
                total_cells.extend(
                    _metric_cell(
                        result.column_totals.get((column_key, measure)),
                        measure,
                        show_zeros=spec.show_zeros,
                    )
                    for measure in spec.measures
                )
        else:
            total_cells.extend(
                _metric_cell(
                    result.grand_totals.get(measure),
                    measure,
                    show_zeros=spec.show_zeros,
                )
                for measure in spec.measures
            )
        if spec.columns and spec.row_totals:
            total_cells.extend(
                _metric_cell(
                    result.grand_totals.get(measure),
                    measure,
                    show_zeros=spec.show_zeros,
                )
                for measure in spec.measures
            )
        rows.append(html.Tr(total_cells, className="total-row"))

    table_classes = ["risk-native-pivot-table"]
    if spec.density == "comfortable":
        table_classes.append("is-comfortable")
    if spec.sticky_headers:
        table_classes.append("has-sticky-headers")
    return html.Div(
        html.Table(
            [html.Thead(html.Tr(header_cells)), html.Tbody(rows)],
            className=" ".join(table_classes),
            **{"aria-label": "Custom Risk pivot"},
        ),
        className="risk-native-pivot-wrap",
    )


def build_hierarchical_pivot_table(
    frame: pd.DataFrame,
    result: NativePivotResult,
    *,
    open_rows: Sequence[str] | None,
    view_token: str,
) -> html.Div:
    """Render the existing bounded pivot as an expandable row hierarchy."""

    if result.row_count == 0:
        return html.Div(
            "No rows match this Custom view.",
            className="empty-state",
            role="status",
        )
    spec = result.spec
    text_fields = tuple(
        dict.fromkeys(
            (
                *spec.rows,
                *spec.columns,
                *(field for field, _selected in spec.filters),
            )
        )
    )
    scoped = _filter_frame(_text_frame(frame, text_fields), spec)
    row_index = pd.MultiIndex.from_frame(scoped.loc[:, list(spec.rows)])
    visible_rows = pd.MultiIndex.from_tuples(
        result.row_keys,
        names=list(spec.rows),
    )
    scoped = scoped.loc[row_index.isin(visible_rows)]

    def measure_cells(node: pd.DataFrame, _context: dict[str, str]) -> list[html.Td]:
        grouped = _group_values(node, spec.columns, spec.measures)
        cells = [
            _metric_cell(
                grouped.get(column_key, {}).get(measure),
                measure,
                show_zeros=spec.show_zeros,
            )
            for column_key in result.column_keys
            for measure in spec.measures
        ]
        if spec.columns and spec.row_totals:
            totals = _group_values(node, (), spec.measures).get((), {})
            cells.extend(
                _metric_cell(
                    totals.get(measure),
                    measure,
                    show_zeros=spec.show_zeros,
                )
                for measure in spec.measures
            )
        return cells

    header_cells: list[html.Th] = [
        html.Th(
            "Group: " + " › ".join(pivot_field_label(field) for field in spec.rows),
            scope="col",
            className="index-header",
            **{"data-metric": "index"},
        )
    ]
    if spec.columns:
        for column_key in result.column_keys:
            label = " · ".join(column_key)
            header_cells.extend(
                html.Th(
                    f"{label} · {pivot_field_label(measure)}",
                    scope="col",
                    title=label,
                    className="metric-header",
                )
                for measure in spec.measures
            )
        if spec.row_totals:
            header_cells.extend(
                html.Th(
                    f"Total · {pivot_field_label(measure)}",
                    scope="col",
                    className="metric-header total-column",
                )
                for measure in spec.measures
            )
    else:
        header_cells.extend(
            html.Th(
                pivot_field_label(measure),
                scope="col",
                className="metric-header",
            )
            for measure in spec.measures
        )

    body_rows: list[html.Tr] = []
    if spec.column_totals or spec.grand_total:
        total_cells: list[object] = [
            html.Th(
                "TOTAL",
                scope="row",
                className="index-cell total-index",
                **{"data-metric": "index", "data-copy-value": "TOTAL"},
            )
        ]
        if spec.columns:
            total_cells.extend(
                _metric_cell(
                    result.column_totals.get((column_key, measure)),
                    measure,
                    show_zeros=spec.show_zeros,
                )
                for column_key in result.column_keys
                for measure in spec.measures
            )
            if spec.row_totals:
                total_cells.extend(
                    _metric_cell(
                        result.grand_totals.get(measure),
                        measure,
                        show_zeros=spec.show_zeros,
                    )
                    for measure in spec.measures
                )
        else:
            total_cells.extend(
                _metric_cell(
                    result.grand_totals.get(measure),
                    measure,
                    show_zeros=spec.show_zeros,
                )
                for measure in spec.measures
            )
        body_rows.append(html.Tr(total_cells, className="total-row"))
    body_rows.extend(
        build_tree_rows(
            scoped,
            [],
            list(open_rows or ()),
            [],
            groups=list(spec.rows),
            cell_builder=measure_cells,
            toggle_type="custom-row-toggle",
            delegated_actions=True,
        )
    )

    table_classes = ["risk-table", "risk-custom-hierarchy-table"]
    if spec.density == "comfortable":
        table_classes.append("is-comfortable")
    if spec.sticky_headers:
        table_classes.append("has-sticky-headers")
    return html.Div(
        html.Table(
            [html.Thead(html.Tr(header_cells)), html.Tbody(body_rows)],
            className=" ".join(table_classes),
            role="treegrid",
            **{"aria-label": "Custom Risk hierarchy"},
        ),
        className="risk-table-wrap risk-custom-hierarchy-wrap",
        **{
            "data-risk-view-token": view_token,
            "data-risk-open-rows": json.dumps(
                sorted(set(open_rows or ())), separators=(",", ":")
            ),
        },
    )


__all__ = [
    "NativePivotResult",
    "build_custom_risk_pivot_workspace",
    "build_hierarchical_pivot_table",
    "build_native_pivot_table",
    "compute_native_pivot",
    "pivot_control_values",
    "pivot_field_label",
    "pivot_spec_from_controls",
]
