"""Small, page-owned components for the V4.1 Stock workflow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pandas as pd
from dash import dash_table, dcc, html
from dash.dash_table.Format import Format, Scheme

from rebirth.adapters.s08_stock import StockConnectorAdapter, StockSource
from rebirth.domain.s01_schema import PORTFOLIO_MAPPED_COLUMN
from rebirth.domain.s09_stock import map_stock_comparison_portfolios
from rebirth.ui.s03_filters import build_saved_filter_view_bar

from .s01_data import (
    STOCK_DISPLAY_COLUMNS,
    STOCK_FILTER_FIELDS,
    STOCK_FILTER_IDS,
    STOCK_FILTER_NOTE,
    STOCK_SAVED_VIEW_CONTROLS,
    StockPageData,
    default_stock_filter_values,
    load_stock_page_data,
    normalize_stock_date_pair,
    stock_display_rows,
    stock_filter_options,
)
from .s02_history import build_stock_history_empty_figure
from .s05_pivot import (
    STOCK_PIVOT_COLUMN_FIELDS,
    STOCK_PIVOT_DEFAULT_ROWS,
    STOCK_PIVOT_DEFAULT_VALUES,
    STOCK_PIVOT_ROW_FIELDS,
    STOCK_PIVOT_VALUES,
    build_stock_pivot,
)


STOCK_PERIODS = (
    ("WTD", "wtd"),
    ("MTD", "mtd"),
    ("YTD", "ytd"),
    ("1Y", "1y"),
    ("All", "all"),
    ("Custom", "custom"),
)


def _stock_table_columns() -> list[dict[str, object]]:
    numeric_format = Format(precision=2, scheme=Scheme.fixed, group=",")
    return [
        {
            "name": column,
            "id": column,
            **(
                {"type": "numeric", "format": numeric_format}
                if column in {"Quantity", "Stock", "dStock"}
                else {}
            ),
        }
        for column in STOCK_DISPLAY_COLUMNS
    ]


def stock_table_records(display: pd.DataFrame) -> list[dict[str, object]]:
    """Return JSON-safe rows with one compact CRDS + Activity row id."""

    missing = [column for column in STOCK_DISPLAY_COLUMNS if column not in display]
    if missing:
        raise ValueError(f"Stock display rows are missing columns: {missing}")
    safe = display.loc[:, list(STOCK_DISPLAY_COLUMNS)].astype(object)
    safe = safe.where(pd.notna(safe), None)
    records: list[dict[str, object]] = []
    for row in safe.to_dict("records"):
        row["id"] = json.dumps(
            [str(row["CRDS"]), str(row["Activity"])],
            separators=(",", ":"),
        )
        records.append(row)
    return records


def stock_pivot_columns(
    columns: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Attach compact number formats to page-owned dynamic pivot columns."""

    result: list[dict[str, object]] = []
    for source in columns:
        column = dict(source)
        if column.get("type") == "numeric":
            column["format"] = Format(
                precision=0 if column.get("id") == "Positions" else 2,
                scheme=Scheme.fixed,
                group=",",
            )
        result.append(column)
    return result


def build_stock_table(display: pd.DataFrame) -> dash_table.DataTable:
    """Build the compact expandable Stock pivot."""

    pivot = build_stock_pivot(display)

    return dash_table.DataTable(
        id="stock-current-table",
        columns=stock_pivot_columns(pivot.columns),
        data=pivot.records,
        active_cell=None,
        cell_selectable=True,
        sort_action="none",
        page_action="none",
        fixed_rows={"headers": True},
        merge_duplicate_headers=True,
        style_table={"overflowX": "auto", "maxHeight": "62vh"},
        style_cell={
            "padding": "8px 10px",
            "textAlign": "left",
            "minWidth": "120px",
            "whiteSpace": "nowrap",
        },
        style_cell_conditional=[
            {
                "if": {"column_id": "Hierarchy"},
                "minWidth": "280px",
                "width": "45%",
                "cursor": "pointer",
            },
            {
                "if": {"column_type": "numeric"},
                "textAlign": "right",
                "fontVariantNumeric": "tabular-nums",
            },
        ],
        style_data_conditional=[
            {
                "if": {"filter_query": '{Hierarchy} contains "▸"'},
                "fontWeight": 700,
            },
            {
                "if": {"filter_query": '{Hierarchy} contains "−"'},
                "fontWeight": 700,
                "backgroundColor": "var(--surface-soft)",
            },
        ],
    )


def build_stock_position_detail(display: pd.DataFrame) -> html.Details:
    """Keep connector and mapped metadata at its unaggregated row grain."""

    table = dash_table.DataTable(
        id="stock-position-detail-table",
        columns=_stock_table_columns(),
        data=stock_table_records(display),
        filter_action="native",
        filter_options={"case": "insensitive"},
        sort_action="native",
        sort_mode="multi",
        page_action="native",
        page_size=15,
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
    return html.Details(
        [
            html.Summary("Position detail · unaggregated connector rows"),
            html.P(
                "Static identifiers and Portfolio mappings are shown exactly as received.",
                className="page-note",
            ),
            table,
        ],
        className="stock-position-detail",
    )


def build_stock_filter_bar(
    *,
    options: Mapping[str, Sequence[Mapping[str, str]]] | None = None,
    selected: Mapping[str, Sequence[str]] | None = None,
    exclude_selected: bool = False,
) -> html.Div:
    """Build the five Stock-local governed reporting filters."""

    available = dict(options or {})
    values = dict(selected or {})
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Label(
                                field.label, htmlFor=STOCK_FILTER_IDS[field.key]
                            ),
                            dcc.Dropdown(
                                id=STOCK_FILTER_IDS[field.key],
                                options=list(available.get(field.key, ())),
                                value=list(values.get(field.key, ())),
                                multi=True,
                                clearable=True,
                                placeholder=f"All {field.label.casefold()} values",
                            ),
                        ],
                        className="control-field",
                    )
                    for field in STOCK_FILTER_FIELDS
                ],
                className="stock-filter-grid",
            ),
            dcc.Checklist(
                id=STOCK_SAVED_VIEW_CONTROLS.exclude_id,
                options=[
                    {
                        "label": "Exclude rows matching any selected value",
                        "value": "exclude",
                    }
                ],
                value=["exclude"] if exclude_selected else [],
                className="risk-filter-mode filter-mode-control",
            ),
        ],
        id="stock-filter-bar",
        className="stock-filter-bar",
    )


def build_stock_history_section(*, available: bool) -> html.Div:
    """Build the inline history controls without reading an archive."""

    status = (
        "Select CRDS and Activity, then load a period. Clicking a Stock row loads it immediately."
        if available
        else "Stock history is not configured for this application."
    )
    period_buttons = [
        html.Button(
            label,
            id=f"stock-period-{value}",
            n_clicks=0,
            type="button",
            disabled=not available,
            className=(
                "refresh-button stock-period-button stock-period-selected"
                if value == "1y"
                else "refresh-button stock-period-button"
            ),
        )
        for label, value in STOCK_PERIODS
    ]
    return html.Section(
        [
            html.Div(
                [
                    html.H2("Stock history"),
                    html.P(
                        "Stock is market value and dStock is its business-day "
                        "change. A leaf click loads the chart; period changes then "
                        "update it immediately.",
                        className="page-note",
                    ),
                ],
                className="stock-section-heading",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("CRDS", htmlFor="stock-history-crds"),
                            dcc.Dropdown(
                                id="stock-history-crds",
                                options=[],
                                value=None,
                                clearable=True,
                                searchable=True,
                                disabled=not available,
                                placeholder="Select CRDS",
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Activity", htmlFor="stock-history-activity"),
                            dcc.Dropdown(
                                id="stock-history-activity",
                                options=[],
                                value=None,
                                clearable=True,
                                searchable=True,
                                disabled=not available,
                                placeholder="Select Activity",
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Period"),
                            html.Div(
                                period_buttons,
                                id="stock-history-period-buttons",
                                className="saved-view-actions",
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label(
                                "Custom dates", htmlFor="stock-history-date-range"
                            ),
                            dcc.DatePickerRange(
                                id="stock-history-date-range",
                                minimum_nights=0,
                                display_format="YYYY-MM-DD",
                                clearable=False,
                                disabled=not available,
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Load", htmlFor="stock-history-load-button"),
                            html.Button(
                                "Load history",
                                id="stock-history-load-button",
                                n_clicks=0,
                                type="button",
                                disabled=not available,
                                className="refresh-button",
                            ),
                        ],
                        className="control-field stock-compare-action",
                    ),
                ],
                className="stock-history-controls",
            ),
            html.P(
                status,
                id="stock-history-status",
                className="page-note",
                role="status",
            ),
            dcc.Loading(
                dcc.Graph(
                    id="stock-history-chart",
                    figure=build_stock_history_empty_figure(status),
                    config={"displaylogo": False, "responsive": True},
                ),
                delay_show=120,
            ),
        ],
        id="stock-history-panel",
        className="page-card stock-section-card stock-history-section",
    )


def stock_summary_text(
    filtered: pd.DataFrame,
    *,
    total_rows: int,
    current_date: pd.Timestamp,
    prior_date: pd.Timestamp,
) -> tuple[str, str, str]:
    """Return simple row, mapped, and unmapped counters."""

    del prior_date
    mapped_count = int(filtered[PORTFOLIO_MAPPED_COLUMN].eq(True).sum())
    rows = (
        f"Rows: {len(filtered):,} of {total_rows:,} · As of "
        f"{current_date.date().isoformat()}"
    )
    return (
        rows,
        f"Mapped: {mapped_count:,}",
        f"Unmapped: {len(filtered) - mapped_count:,}",
    )


def _walk_components(component):
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if not isinstance(children, (list, tuple)):
        children = [children]
    for child in children:
        yield from _walk_components(child)


def _stock_page_layout(
    *,
    current_date: pd.Timestamp,
    prior_date: pd.Timestamp,
    history_available: bool,
    display: pd.DataFrame,
    filter_options: Mapping[str, Sequence[Mapping[str, str]]],
    selected_filters: Mapping[str, Sequence[str]],
    exclude_selected: bool,
) -> html.Main:
    current_end = current_date.date().isoformat()
    current_start = (
        (current_date - pd.DateOffset(years=1) + pd.offsets.BDay(1)).date().isoformat()
    )
    total_rows = len(display)
    mapped = int(display[PORTFOLIO_MAPPED_COLUMN].eq(True).sum()) if total_rows else 0
    page = html.Main(
        [
            dcc.Store(id="stock-loaded-snapshot", data=None),
            dcc.Store(
                id="stock-date-store",
                data={
                    "current_date": current_date.date().isoformat(),
                    "prior_date": prior_date.date().isoformat(),
                },
            ),
            dcc.Store(id="stock-history-period", data="1y"),
            dcc.Store(id="stock-history-autoload", data=None),
            dcc.Store(id="stock-pivot-open-paths", data=[]),
            dcc.Store(id="stock-filter-ready", data=False),
            dcc.Interval(
                id="stock-load-trigger", interval=100, n_intervals=0, max_intervals=1
            ),
            html.Header(
                [
                    html.P("CURRENT POSITIONS", className="page-eyebrow"),
                    html.H1("Stock", className="page-title"),
                    html.P(
                        "Review current Stock and dStock through one configurable "
                        "hierarchy. Expand a branch, then click a leaf to see its "
                        "history on this page.",
                        className="page-intro",
                    ),
                ],
                className="page-header",
            ),
            build_saved_filter_view_bar(STOCK_SAVED_VIEW_CONTROLS),
            html.Section(
                [
                    html.Div(
                        [
                            html.H2("Reporting filters"),
                            html.P(
                                "Base Review starts with Activity 1, 2 and 3. "
                                "Selections affect only this Stock page.",
                                className="page-note",
                            ),
                        ],
                        className="stock-section-heading",
                    ),
                    build_stock_filter_bar(
                        options=filter_options,
                        selected=selected_filters,
                        exclude_selected=exclude_selected,
                    ),
                    html.P(STOCK_FILTER_NOTE, className="stock-filter-note"),
                ],
                className="page-card stock-section-card stock-filter-section",
            ),
            html.Section(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2("Current Stock"),
                                    html.P(
                                        "Choose the hierarchy, optional column split "
                                        "and values. Category is labelled Bucket.",
                                        className="page-note",
                                    ),
                                ],
                                className="stock-section-heading",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Label(
                                                "Rows", htmlFor="stock-pivot-rows"
                                            ),
                                            dcc.Dropdown(
                                                id="stock-pivot-rows",
                                                options=[
                                                    {"label": label, "value": value}
                                                    for value, label in STOCK_PIVOT_ROW_FIELDS
                                                ],
                                                value=list(STOCK_PIVOT_DEFAULT_ROWS),
                                                multi=True,
                                                clearable=False,
                                            ),
                                        ],
                                        className="control-field stock-pivot-rows",
                                    ),
                                    html.Div(
                                        [
                                            html.Label(
                                                "Columns", htmlFor="stock-pivot-column"
                                            ),
                                            dcc.Dropdown(
                                                id="stock-pivot-column",
                                                options=[
                                                    {"label": label, "value": value}
                                                    for value, label in STOCK_PIVOT_COLUMN_FIELDS
                                                ],
                                                value="",
                                                clearable=False,
                                            ),
                                        ],
                                        className="control-field",
                                    ),
                                    html.Div(
                                        [
                                            html.Label(
                                                "Values", htmlFor="stock-pivot-values"
                                            ),
                                            dcc.Dropdown(
                                                id="stock-pivot-values",
                                                options=[
                                                    {"label": label, "value": value}
                                                    for value, label in STOCK_PIVOT_VALUES
                                                ],
                                                value=list(STOCK_PIVOT_DEFAULT_VALUES),
                                                multi=True,
                                                clearable=False,
                                            ),
                                        ],
                                        className="control-field",
                                    ),
                                ],
                                className="stock-pivot-controls",
                            ),
                        ],
                        className="stock-current-header",
                    ),
                    html.Div(
                        [
                            html.Span(
                                f"Rows: {total_rows:,}",
                                id="stock-row-count",
                                className="static-data-row-count",
                            ),
                            html.Span(
                                f"Mapped: {mapped:,}",
                                id="stock-mapped-count",
                                className="static-data-col-count",
                            ),
                            html.Span(
                                f"Unmapped: {total_rows - mapped:,}",
                                id="stock-unmapped-count",
                                className="static-data-col-count",
                            ),
                            html.Span(
                                "Loading latest Stock…"
                                if display.empty
                                else f"As of {current_end}",
                                id="stock-load-status",
                                className="static-data-col-count",
                                role="status",
                            ),
                        ],
                        className="static-data-meta",
                    ),
                    dcc.Loading(
                        html.Div(
                            [
                                build_stock_table(display),
                                build_stock_position_detail(display),
                            ],
                            id="stock-current-panel",
                            className="page-card static-data-panel stock-current-panel",
                        ),
                        delay_show=120,
                    ),
                ],
                className="page-card stock-section-card stock-current-section",
            ),
            build_stock_history_section(available=history_available),
        ],
        id="stock-page",
        className="page-frame stock-page",
    )
    date_range = next(
        component
        for component in _walk_components(page)
        if getattr(component, "id", None) == "stock-history-date-range"
    )
    date_range.start_date = current_start
    date_range.end_date = current_end
    return page


def build_stock_page_shell(
    *,
    current_date: object,
    prior_date: object,
    history_available: bool = False,
) -> html.Main:
    """Paint a stable one-page shell before connector or archive work."""

    current, prior = normalize_stock_date_pair(current_date, prior_date)
    empty = pd.DataFrame(columns=list(STOCK_DISPLAY_COLUMNS))
    return _stock_page_layout(
        current_date=current,
        prior_date=prior,
        history_available=history_available,
        display=empty,
        filter_options={field.key: [] for field in STOCK_FILTER_FIELDS},
        selected_filters={field.key: [] for field in STOCK_FILTER_FIELDS},
        exclude_selected=False,
    )


def build_stock_page_from_data(
    page_data: StockPageData,
    *,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = None,
) -> html.Main:
    """Build the pure V4.1 page from one mapped server snapshot."""

    del promotion_threshold
    selected = {
        field.key: list((selected_filters or {}).get(field.key) or ())
        for field in STOCK_FILTER_FIELDS
    }
    if not any(selected.values()):
        selected = default_stock_filter_values(page_data.mapped_stock)
    options, selected = stock_filter_options(page_data.mapped_stock, selected)
    display = stock_display_rows(
        page_data.mapped_stock,
        dimension_filters=selected,
        exclude_selected=exclude_selected,
    )
    return _stock_page_layout(
        current_date=page_data.current_date,
        prior_date=page_data.prior_date,
        history_available=False,
        display=display,
        filter_options=options,
        selected_filters=selected,
        exclude_selected=exclude_selected,
    )


def build_stock_page_placeholder(message: str, *, error: bool = False) -> list[object]:
    """Retained pure placeholder used by callers during feature-local failures."""

    return [
        html.P(
            str(message),
            id="stock-load-error" if error else "stock-load-placeholder",
            className="static-data-empty" if error else "static-data-page-note",
            role="alert" if error else "status",
        )
    ]


def build_stock_page(
    current_stock: pd.DataFrame,
    prior_stock: pd.DataFrame,
    portfolio_config: pd.DataFrame | str | Path,
    *,
    current_date: object,
    prior_date: object,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = None,
) -> html.Main:
    """Build the pure page from in-memory source frames."""

    current, prior = normalize_stock_date_pair(current_date, prior_date)
    page_data = StockPageData(
        mapped_stock=map_stock_comparison_portfolios(
            current_stock, prior_stock, portfolio_config
        ),
        current_date=current,
        prior_date=prior,
        portfolio_date=current,
    )
    return build_stock_page_from_data(
        page_data,
        selected_filters=selected_filters,
        exclude_selected=exclude_selected,
        promotion_threshold=promotion_threshold,
    )


def build_stock_page_from_sources(
    *,
    stock_source: StockSource | StockConnectorAdapter,
    portfolio_config_source: pd.DataFrame
    | str
    | Path
    | Callable[[pd.Timestamp], pd.DataFrame | str | Path],
    current_date: object,
    prior_date: object,
    portfolio_date: object | None = None,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = None,
) -> html.Main:
    """Load one latest comparison, then delegate to the pure builder."""

    page_data = load_stock_page_data(
        stock_source=stock_source,
        portfolio_config_source=portfolio_config_source,
        current_date=current_date,
        prior_date=prior_date,
        portfolio_date=portfolio_date,
    )
    return build_stock_page_from_data(
        page_data,
        selected_filters=selected_filters,
        exclude_selected=exclude_selected,
        promotion_threshold=promotion_threshold,
    )


__all__ = [
    "STOCK_PERIODS",
    "build_stock_history_section",
    "build_stock_page",
    "build_stock_page_from_data",
    "build_stock_page_from_sources",
    "build_stock_page_placeholder",
    "build_stock_page_shell",
    "build_stock_table",
    "stock_pivot_columns",
    "stock_summary_text",
    "stock_table_records",
]
