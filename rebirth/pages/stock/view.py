"""Pure V4 components and source boundary for the Stock comparison page."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping, Sequence

import pandas as pd
from dash import dcc, html

from rebirth.adapters.stock import StockConnectorAdapter, StockSource
from rebirth.domain.schema import PORTFOLIO_MAPPED_COLUMN
from rebirth.domain.stock import (
    STOCK_COLUMNS,
    STOCK_PROMOTION_THRESHOLD_DEFAULT,
    filter_stock_comparison,
    map_stock_comparison_portfolios,
)
from rebirth.ui.filter_views import build_saved_filter_view_bar

from .data import (
    STOCK_FILTER_FIELDS,
    STOCK_FILTER_IDS,
    STOCK_FILTER_NOTE,
    STOCK_SAVED_VIEW_CONTROLS,
    StockPageData,
    load_stock_page_data,
    normalize_stock_date_pair,
)
from .history import STOCK_HISTORY_METRICS, build_stock_history_empty_figure
from .tables import build_stock_hierarchy_panel, build_stock_source_rows_section


def build_stock_history_section(*, available: bool) -> html.Div:
    """Build the stable page-owned History workspace without reading archives."""

    status = (
        "History is not loaded. Search and load one exact identity when needed."
        if available
        else "Stock history is not configured for this application."
    )
    return html.Div(
        [
            dcc.Store(id="stock-history-loaded-range", data=None),
            dcc.Store(id="stock-history-catalog", data=None),
            html.H2("Historical Stock", className="static-data-page-title"),
            html.P(
                "Archive-backed exact identity history. Searches return at most "
                "50 identities and rows are read only after Load history.",
                className="static-data-page-note",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label(
                                "Stock identity", htmlFor="stock-history-identity"
                            ),
                            dcc.Dropdown(
                                id="stock-history-identity",
                                options=[],
                                value=None,
                                clearable=False,
                                disabled=not available,
                                placeholder="Type to search the Stock archive",
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Metric", htmlFor="stock-history-metric"),
                            dcc.Dropdown(
                                id="stock-history-metric",
                                options=[
                                    {"label": metric, "value": metric}
                                    for metric in STOCK_HISTORY_METRICS
                                ],
                                value="Market Value",
                                clearable=False,
                                disabled=not available,
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Period", htmlFor="stock-history-period"),
                            dcc.Dropdown(
                                id="stock-history-period",
                                options=[
                                    {"label": label, "value": value}
                                    for label, value in (
                                        ("WTD", "wtd"),
                                        ("MTD", "mtd"),
                                        ("YTD", "ytd"),
                                        ("1Y", "1y"),
                                        ("All", "all"),
                                        ("Custom", "custom"),
                                    )
                                ],
                                value="1y",
                                clearable=False,
                                disabled=not available,
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
                                disabled=True,
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
                html.Div(
                    [
                        dcc.Graph(
                            id="stock-history-chart",
                            figure=build_stock_history_empty_figure(status),
                            config={"displaylogo": False, "responsive": True},
                        ),
                        html.Div(
                            html.P(status, className="static-data-page-note"),
                            id="stock-history-table-panel",
                            className="static-data-panel",
                        ),
                    ]
                ),
                delay_show=120,
            ),
        ],
        id="stock-history-workspace",
        className="stock-history-workspace",
        style={"display": "none"},
    )


def stock_summary_text(
    filtered: pd.DataFrame,
    *,
    total_rows: int,
    current_date: pd.Timestamp,
    prior_date: pd.Timestamp,
) -> tuple[str, str, str]:
    """Return the three page counters for one filtered Stock view."""

    mapped_count = int(filtered[PORTFOLIO_MAPPED_COLUMN].eq(True).sum())
    unmapped_count = len(filtered) - mapped_count
    rows = (
        f"Rows: {len(filtered):,} of {total_rows:,} · Current "
        f"{current_date.date().isoformat()} · Prior {prior_date.date().isoformat()}"
    )
    return rows, f"Mapped: {mapped_count:,}", f"Unmapped: {unmapped_count:,}"


def build_stock_page_from_data(
    page_data: StockPageData,
    *,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
) -> html.Main:
    """Build Stock comparison content from one server-owned page snapshot."""

    filtered = filter_stock_comparison(
        page_data.mapped_stock,
        dict(selected_filters or {}),
        exclude_selected=exclude_selected,
    )
    rows, mapped, unmapped = stock_summary_text(
        filtered,
        total_rows=len(page_data.mapped_stock),
        current_date=page_data.current_date,
        prior_date=page_data.prior_date,
    )
    return html.Main(
        [
            html.Div(
                [
                    html.Span(
                        rows,
                        id="stock-row-count",
                        className="static-data-row-count",
                    ),
                    html.Span(
                        mapped,
                        id="stock-mapped-count",
                        className="static-data-col-count",
                    ),
                    html.Span(
                        unmapped,
                        id="stock-unmapped-count",
                        className="static-data-col-count",
                    ),
                ],
                className="static-data-meta",
            ),
            html.Div(
                [
                    html.H3("Stacked Stock", className="static-data-page-title"),
                    html.P(
                        "Activity → Promotion Bucket → Group (Temporary Fixture) → CPTY → CRDS. "
                        "The temporary Group is currency-based; promotion uses absolute net current market value at the displayed Stock-name identity after filters. Every level is ordered by absolute current Stock descending.",
                        id="stock-hierarchy-rule-note",
                        className="static-data-page-note",
                    ),
                    html.Div(
                        build_stock_hierarchy_panel(
                            filtered,
                            has_unfiltered_rows=not page_data.mapped_stock.empty,
                            promotion_threshold=promotion_threshold,
                        ),
                        id="stock-hierarchy-view",
                    ),
                ],
                id="stock-hierarchy-panel",
                className="static-data-panel",
            ),
            build_stock_source_rows_section(),
        ],
        id="stock-comparison-view",
        **{
            "data-stock-columns": ",".join(STOCK_COLUMNS),
            "data-current-date": page_data.current_date.date().isoformat(),
            "data-prior-date": page_data.prior_date.date().isoformat(),
        },
    )


def build_stock_page_placeholder(
    message: str,
    *,
    error: bool = False,
) -> list[object]:
    """Keep every Stock callback target mounted before data is available.

    Native Dash Pages can remount Stock while a dated load from an earlier
    mount is completing. The filter callback therefore targets only nodes
    that exist in loading, error, and loaded states.
    """

    status = str(message).strip() or "Stock data is not available yet."
    return [
        (
            html.P(
                status,
                id="stock-load-error",
                className="static-data-empty",
                role="alert",
            )
            if error
            else None
        ),
        html.Div(
            [
                html.Span(
                    "Rows: loading…",
                    id="stock-row-count",
                    className="static-data-row-count",
                ),
                html.Span(
                    "Mapped: loading…",
                    id="stock-mapped-count",
                    className="static-data-col-count",
                ),
                html.Span(
                    "Unmapped: loading…",
                    id="stock-unmapped-count",
                    className="static-data-col-count",
                ),
            ],
            className="static-data-meta",
        ),
        html.Div(
            [
                html.H3("Stacked Stock", className="static-data-page-title"),
                html.P(
                    "Activity → Promotion Bucket → Group (Temporary Fixture) → CPTY → CRDS. "
                    "The temporary Group is currency-based; promotion uses absolute net current market value at the displayed Stock-name identity after filters. Every level is ordered by absolute current Stock descending.",
                    id="stock-hierarchy-rule-note",
                    className="static-data-page-note",
                ),
                html.Div(
                    html.P(status, className="static-data-page-note"),
                    id="stock-hierarchy-view",
                ),
            ],
            id="stock-hierarchy-panel",
            className="static-data-panel",
        ),
        build_stock_source_rows_section(status),
    ]


def build_stock_page_shell(
    *,
    current_date: object,
    prior_date: object,
    history_available: bool = False,
) -> html.Main:
    """Paint the complete Stock control shell before any connector work."""

    current, prior = normalize_stock_date_pair(current_date, prior_date)
    filter_controls = [
        html.Div(
            [
                html.Label(field.label, htmlFor=STOCK_FILTER_IDS[field.key]),
                dcc.Dropdown(
                    id=STOCK_FILTER_IDS[field.key],
                    options=[],
                    multi=True,
                    placeholder=f"All {field.label.casefold()} values",
                    value=[],
                ),
            ],
            className="control-field",
        )
        for field in STOCK_FILTER_FIELDS
    ]
    return html.Main(
        [
            dcc.Store(id="stock-loaded-revision", data=-1),
            dcc.Store(id="stock-loaded-dates", data=None),
            dcc.Store(id="stock-hierarchy-open-paths", data=[]),
            dcc.Store(
                id="stock-source-rows-state",
                data={"requested": False, "loaded_dates": None},
            ),
            dcc.Store(
                id="stock-dimension-filter-store",
                data={
                    "filters": {field.key: [] for field in STOCK_FILTER_FIELDS},
                    "exclude_selected": False,
                    "promotion_threshold": STOCK_PROMOTION_THRESHOLD_DEFAULT,
                },
            ),
            dcc.Interval(
                id="stock-load-trigger",
                interval=1_000,
                n_intervals=0,
                disabled=False,
            ),
            html.Div(
                [
                    html.H2("Stock", className="static-data-page-title"),
                    html.P(
                        "Compare two dated Stock snapshots, enriched through the authoritative Portfolio mapping.",
                        className="static-data-page-note",
                    ),
                ],
                className="static-data-header",
            ),
            dcc.Tabs(
                id="stock-workspace-tabs",
                value="current",
                children=[
                    dcc.Tab(label="Current", value="current"),
                    dcc.Tab(label="History", value="history"),
                ],
                className="v4-workspace-tabs",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label(
                                        "Current stock date",
                                        htmlFor="stock-current-date",
                                    ),
                                    dcc.DatePickerSingle(
                                        id="stock-current-date",
                                        date=current.date().isoformat(),
                                        display_format="YYYY-MM-DD",
                                        clearable=False,
                                    ),
                                ],
                                className="control-field",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Prior stock date", htmlFor="stock-prior-date"
                                    ),
                                    dcc.DatePickerSingle(
                                        id="stock-prior-date",
                                        date=prior.date().isoformat(),
                                        display_format="YYYY-MM-DD",
                                        clearable=False,
                                    ),
                                ],
                                className="control-field",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Compare", htmlFor="stock-compare-button"
                                    ),
                                    html.Button(
                                        "Compare dates",
                                        id="stock-compare-button",
                                        n_clicks=0,
                                        type="button",
                                        className="refresh-button stock-compare-button",
                                    ),
                                ],
                                className="control-field stock-compare-action",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Promotion threshold",
                                        htmlFor="stock-promotion-threshold",
                                    ),
                                    dcc.Input(
                                        id="stock-promotion-threshold",
                                        type="number",
                                        min=0,
                                        step=1_000,
                                        value=STOCK_PROMOTION_THRESHOLD_DEFAULT,
                                        debounce=True,
                                    ),
                                    html.Small(
                                        "Promote when |Current Market Value| is greater than or equal to this amount.",
                                        id="stock-promotion-threshold-note",
                                        className="static-data-page-note",
                                    ),
                                ],
                                className="control-field",
                            ),
                        ],
                        className="controls top-controls",
                    ),
                    build_saved_filter_view_bar(
                        STOCK_SAVED_VIEW_CONTROLS,
                        filter_note=STOCK_FILTER_NOTE,
                        filter_bar=html.Div(
                            [
                                html.Div(
                                    [
                                        *filter_controls,
                                        dcc.Checklist(
                                            id="stock-filter-exclude-selected",
                                            options=[
                                                {
                                                    "label": (
                                                        "Exclude rows matching any selected value"
                                                    ),
                                                    "value": "exclude",
                                                }
                                            ],
                                            value=[],
                                            className=(
                                                "stock-filter-mode filter-mode-control"
                                            ),
                                        ),
                                    ],
                                    className="controls filter-controls",
                                ),
                            ],
                            className="dimension-filter-bar top-controls",
                        ),
                    ),
                    dcc.Loading(
                        html.Div(
                            build_stock_page_placeholder(
                                "Loading both GetStock dates and the Portfolio mapping…"
                            ),
                            id="stock-page-content",
                        ),
                        delay_show=120,
                    ),
                ],
                id="stock-current-workspace",
                className="stock-current-workspace",
            ),
            build_stock_history_section(available=history_available),
        ],
        id="stock-page",
        className="static-data-page",
    )


def build_stock_page(
    current_stock: pd.DataFrame,
    prior_stock: pd.DataFrame,
    portfolio_config: pd.DataFrame | str | Path,
    *,
    current_date: object,
    prior_date: object,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
) -> html.Main:
    """Build the pure mapped comparison page from in-memory inputs."""

    current, prior = normalize_stock_date_pair(current_date, prior_date)
    data = StockPageData(
        mapped_stock=map_stock_comparison_portfolios(
            current_stock,
            prior_stock,
            portfolio_config,
        ),
        current_date=current,
        prior_date=prior,
        portfolio_date=current,
    )
    return build_stock_page_from_data(
        data,
        selected_filters=selected_filters,
        exclude_selected=exclude_selected,
        promotion_threshold=promotion_threshold,
    )


def build_stock_page_from_sources(
    *,
    stock_source: StockSource | StockConnectorAdapter,
    portfolio_config_source: (
        pd.DataFrame | str | Path | Callable[[pd.Timestamp], pd.DataFrame | str | Path]
    ),
    current_date: object,
    prior_date: object,
    portfolio_date: object | None = None,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
) -> html.Main:
    """Load both snapshots, then delegate to the pure Stock page builder."""

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
    "build_stock_history_section",
    "build_stock_page",
    "build_stock_page_from_data",
    "build_stock_page_from_sources",
    "build_stock_page_placeholder",
    "build_stock_page_shell",
    "stock_summary_text",
]
