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

from .s01_data import (
    STOCK_DISPLAY_COLUMNS,
    StockPageData,
    default_stock_activities,
    load_stock_page_data,
    normalize_stock_date_pair,
    stock_activity_options,
    stock_display_rows,
)
from .s02_history import build_stock_history_empty_figure


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


def build_stock_table(display: pd.DataFrame) -> dash_table.DataTable:
    """Build the latest row-level Stock table; metadata is never aggregated."""

    return dash_table.DataTable(
        id="stock-current-table",
        columns=_stock_table_columns(),
        data=stock_table_records(display),
        active_cell=None,
        cell_selectable=True,
        filter_action="native",
        filter_options={"case": "insensitive"},
        sort_action="native",
        sort_mode="multi",
        page_action="native",
        page_size=25,
        fixed_rows={"headers": True},
        style_table={"overflowX": "auto", "maxHeight": "62vh"},
        style_cell={
            "padding": "8px 10px",
            "textAlign": "left",
            "minWidth": "105px",
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
            html.H2("Stock history", className="static-data-page-title"),
            html.P(
                "Stock is market value; dStock is the business-day change. History is read only on request.",
                className="static-data-page-note",
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
                className="controls top-controls",
            ),
            html.P(
                status,
                id="stock-history-status",
                className="static-data-page-note",
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
        className="static-data-panel",
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
    activity_options: list[dict[str, str]],
    selected_activities: Sequence[str],
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
            dcc.Interval(
                id="stock-load-trigger", interval=100, n_intervals=0, max_intervals=1
            ),
            html.H1("Stock", className="static-data-page-title"),
            html.P(
                "Latest mapped positions. Use the Activity control or the table filters, then click any row for inline history.",
                className="static-data-page-note",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Activity", htmlFor="stock-current-activity"),
                            dcc.Dropdown(
                                id="stock-current-activity",
                                options=activity_options,
                                value=list(selected_activities),
                                multi=True,
                                clearable=True,
                                placeholder="All activities",
                            ),
                        ],
                        className="control-field",
                    )
                ],
                className="controls top-controls",
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
                    build_stock_table(display),
                    id="stock-current-panel",
                    className="static-data-panel",
                ),
                delay_show=120,
            ),
            html.Hr(className="static-data-divider"),
            build_stock_history_section(available=history_available),
        ],
        id="stock-page",
        className="static-data-page",
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
        activity_options=[],
        selected_activities=[],
    )


def build_stock_page_from_data(
    page_data: StockPageData,
    *,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = None,
) -> html.Main:
    """Build the pure V4.1 page from one mapped server snapshot."""

    del exclude_selected, promotion_threshold
    selected = list((selected_filters or {}).get("activity") or ())
    if not selected:
        selected = default_stock_activities(page_data.mapped_stock)
    display = stock_display_rows(page_data.mapped_stock, selected)
    return _stock_page_layout(
        current_date=page_data.current_date,
        prior_date=page_data.prior_date,
        history_available=False,
        display=display,
        activity_options=stock_activity_options(page_data.mapped_stock),
        selected_activities=selected,
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
    "stock_summary_text",
    "stock_table_records",
]
