"""V5 Dash components for governed P&L adjustment, send, and exploration."""

from __future__ import annotations

import pandas as pd
from dash import dcc, html

from cube.ui.s04_components import build_cube_loader
from cube.ui.s03_filters import build_saved_filter_view_bar

from .s01_common import (
    DISPLAY_COLUMNS,
    GRID_ROW_ID,
    PL_FILTER_EXCLUDE_ID,
    PL_FILTER_FIELDS,
    PL_FILTER_IDS,
    PL_FILTER_NOTE,
    PL_SAVED_VIEW_CONTROLS,
    pl_filter_map,
    pl_filter_options,
)
from .s04_sender import build_pl_send_sections


def build_pl_inline_history_section(*, available: bool) -> html.Section:
    """Build one lazy chart directly below the current Aggregate P&L."""

    if not available:
        return html.Section(
            [
                dcc.Store(id="pl-history-selection-store", data={}),
                html.P(
                    "P&L history is not configured for this application.",
                    className="static-data-empty",
                ),
            ],
            id="pnl-history-workspace",
            className="pnl-history-workspace",
        )
    period_options = [
        {"label": label, "value": value}
        for label, value in (
            ("WTD", "wtd"),
            ("MTD", "mtd"),
            ("YTD", "ytd"),
            ("1Y", "1y"),
            ("All", "all"),
            ("Custom", "custom"),
        )
    ]
    return html.Section(
        [
            dcc.Store(id="pl-history-selection-store", data={}),
            html.Div(
                [
                    html.H2("P&L history", className="page-title"),
                    html.P(
                        "Select any Aggregate P&L value above to plot its daily "
                        "Colossus and Predict history here.",
                        className="page-note",
                    ),
                ]
            ),
            html.Div(
                "No P&L value selected.",
                id="pl-history-selection-label",
                className="pl-history-selection-label",
                role="status",
                **{"aria-live": "polite"},
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Span("Range", className="pl-history-toolbar-label"),
                            dcc.RadioItems(
                                id="pl-history-period",
                                options=period_options,
                                value="1y",
                                inline=True,
                                className="pl-history-period-segments",
                            ),
                            html.Div(
                                dcc.DatePickerRange(
                                    id="pl-history-date-range",
                                    minimum_nights=0,
                                    display_format="YYYY-MM-DD",
                                    clearable=True,
                                    start_date_placeholder_text="Start date",
                                    end_date_placeholder_text="End date",
                                ),
                                id="pl-history-custom-range-control",
                                className="pl-history-custom-range-control",
                                style={"display": "none"},
                            ),
                        ],
                        className="pl-history-period-control",
                    ),
                    html.Div(
                        [
                            html.Label(
                                "Source",
                                htmlFor="pl-history-series-selector",
                                className="pl-history-toolbar-label",
                            ),
                            dcc.Dropdown(
                                id="pl-history-series-selector",
                                options=[
                                    {"label": "Both", "value": "both"},
                                    {"label": "Colossus", "value": "colossus"},
                                    {"label": "Predict", "value": "predict"},
                                ],
                                value="both",
                                clearable=False,
                                searchable=False,
                                className="pl-history-series-selector",
                            ),
                        ],
                        className="pl-history-series-control",
                    ),
                ],
                className="pl-history-range-toolbar",
            ),
            dcc.Loading(
                dcc.Graph(
                    id="pl-history-chart",
                    figure={
                        "data": [],
                        "layout": {
                            "title": "Select an Aggregate P&L value",
                            "xaxis": {"title": "Market Date"},
                            "yaxis": {"title": "P&L"},
                        },
                    },
                    config={"displaylogo": False, "responsive": True},
                    responsive=True,
                    style={"minHeight": "360px"},
                ),
                delay_show=120,
            ),
            html.Div(
                "History loads only after a P&L value is selected.",
                id="pl-history-plot-status",
                className="pl-send-status",
                role="status",
                **{"aria-live": "polite"},
            ),
        ],
        id="pnl-history-workspace",
        className="pnl-history-workspace pnl-inline-history",
        style={"display": "none"},
    )


def _pl_aggregate_section(
    initial_frame: pd.DataFrame | None = None,
) -> html.Section:
    """Build the page-owned live, MTD and YTD P&L hierarchy."""
    del initial_frame
    return html.Section(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.P("P&L OVERVIEW", className="section-eyebrow"),
                            html.H2("Current and historical P&L"),
                            html.P(
                                "Expand Risk Type, Greek and Underlying. Today uses "
                                "the latest Predict value; month-to-date and "
                                "year-to-date use official Colossus history.",
                                className="section-note",
                            ),
                        ],
                        className="section-heading",
                    ),
                ],
                className="section-header",
            ),
            html.Div(
                dcc.Loading(
                    html.Div(
                        html.Div(
                            "Loading current, month-to-date and year-to-date P&L…",
                            className="empty-state",
                            role="status",
                        ),
                        id="pnl-aggregate-pl-grid",
                    ),
                    custom_spinner=build_cube_loader("Loading P&L overview"),
                    delay_show=120,
                    className="cube-loading-boundary",
                ),
                className="pnl-summary-panel",
            ),
        ],
        className="page-card pnl-summary-section",
    )


def build_pl_filter_bar(initial_frame: pd.DataFrame | None = None) -> html.Div:
    """Build the single authoritative five-field P&L filter row."""
    options = (
        pl_filter_options(initial_frame)
        if initial_frame is not None and not initial_frame.empty
        else {field.key: [] for field in PL_FILTER_FIELDS}
    )
    controls = [
        html.Div(
            [
                html.Label(field.label, htmlFor=PL_FILTER_IDS[field.key]),
                dcc.Dropdown(
                    id=PL_FILTER_IDS[field.key],
                    options=options[field.key],
                    value=[],
                    multi=True,
                    placeholder=f"All {field.label.casefold()} values",
                ),
            ],
            className="control-field",
        )
        for field in PL_FILTER_FIELDS
    ]
    return html.Div(
        [
            html.Div(
                [
                    *controls,
                    dcc.Checklist(
                        id=PL_FILTER_EXCLUDE_ID,
                        options=[
                            {
                                "label": "Exclude rows matching any selected value",
                                "value": "exclude",
                            }
                        ],
                        value=[],
                        className="risk-filter-mode filter-mode-control",
                    ),
                ],
                className="controls pnl-filter-controls",
            ),
        ],
        id="pnl-filter-bar",
        className="dimension-filter-bar top-controls",
    )


def build_pl_page(
    *,
    start_initial_load: bool = False,
    send_workflow_available: bool = True,
    initial_aggregate_frame: pd.DataFrame | None = None,
    saved_view_bar: object | None = None,
) -> html.Main:
    """Build the native P&L page around one authoritative filter set."""
    if send_workflow_available:
        current_sections = build_pl_send_sections()
    else:
        current_sections = [
            html.P(
                "P&L sending is not configured for this application.",
                id="pnl-unavailable",
                className="static-data-empty",
            )
        ]
    return html.Main(
        html.Section(
            [
                (
                    dcc.Interval(
                        id="pnl-initial-load-trigger",
                        interval=2_000,
                        n_intervals=0,
                        max_intervals=1,
                    )
                    if start_initial_load
                    else None
                ),
                (
                    dcc.Store(id="pl-adjustment-revision-store", data=0)
                    if send_workflow_available
                    else None
                ),
                dcc.Store(id="pnl-summary-open-paths", data=[]),
                html.Header(
                    [
                        html.P("CONTROLLED P&L", className="page-eyebrow"),
                        html.H1("P&L", className="page-title"),
                    ],
                    className="page-header",
                ),
                html.P(
                    (
                        "Review current, month-to-date and year-to-date P&L, then "
                        "drill into daily history or use the governed send tools. "
                        "One saved-view filter governs the whole page."
                        if send_workflow_available
                        else "Review mapped Aggregate P&L from the latest committed "
                        "risk refresh."
                    ),
                    className="page-intro",
                ),
                (
                    saved_view_bar
                    if saved_view_bar is not None
                    else build_saved_filter_view_bar(
                        PL_SAVED_VIEW_CONTROLS,
                        filter_note=PL_FILTER_NOTE,
                        filter_bar=build_pl_filter_bar(initial_aggregate_frame),
                    )
                ),
                html.Div(
                    [
                        _pl_aggregate_section(initial_aggregate_frame),
                        build_pl_inline_history_section(
                            available=send_workflow_available
                        ),
                        *current_sections,
                    ],
                    id="pnl-current-workspace",
                    className="pnl-current-workspace",
                ),
            ],
            id="pnl-page",
            className="page-frame",
        ),
        id="pnl-page-container",
    )


__all__ = [
    "DISPLAY_COLUMNS",
    "GRID_ROW_ID",
    "PL_FILTER_FIELDS",
    "PL_FILTER_EXCLUDE_ID",
    "PL_FILTER_IDS",
    "PL_FILTER_NOTE",
    "PL_SAVED_VIEW_CONTROLS",
    "build_pl_filter_bar",
    "build_pl_inline_history_section",
    "build_pl_page",
    "build_pl_send_sections",
    "pl_filter_map",
    "pl_filter_options",
]
