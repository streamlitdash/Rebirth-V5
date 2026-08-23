"""V4 Dash components for governed P&L adjustment, send, and exploration."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
from dash import dcc, html

from rebirth.ui.s04_components import build_aggregate_pl_table, build_cube_loader
from rebirth.ui.s01_constants import DEFAULT_VIEW_DIMENSION, VIEW_DIMENSION_FIELDS
from rebirth.ui.s03_filters import build_saved_filter_view_bar

from .s01_common import (
    DISPLAY_COLUMNS,
    GRID_ROW_ID,
    PL_AGGREGATE_HISTORY_CELL_TYPE,
    PL_AGGREGATE_TOGGLE_TYPE,
    PL_FILTER_EXCLUDE_ID,
    PL_FILTER_FIELDS,
    PL_FILTER_IDS,
    PL_FILTER_NOTE,
    PL_SAVED_VIEW_CONTROLS,
    pl_filter_map,
    pl_filter_options,
)
from .s04_sender import build_pl_send_sections


def _walk_components(component: object) -> Iterable[object]:
    """Yield a Dash component tree without relying on private Dash helpers."""
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk_components(child)
    else:
        yield from _walk_components(children)


def build_pl_aggregate_table(
    frame: pd.DataFrame,
    dimension: str,
    open_risk_types: list[str] | None,
) -> html.Div:
    """Render Aggregate P&L with page-owned, collision-free chevron IDs."""
    table = build_aggregate_pl_table(
        frame,
        dimension,
        open_risk_types,
        metric_cell_type=PL_AGGREGATE_HISTORY_CELL_TYPE,
    )
    for component in _walk_components(table):
        component_id = getattr(component, "id", None)
        if not isinstance(component_id, dict):
            continue
        if component_id.get("type") != "aggregate-row-toggle":
            continue
        risk_type = component_id.get("risk_type", component_id.get("risk type"))
        component.id = {
            "type": PL_AGGREGATE_TOGGLE_TYPE,
            "risk_type": str(risk_type),
        }
    return table


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
                    html.H2("P&L history", className="static-data-page-title"),
                    html.P(
                        "Select any Aggregate P&L value above to plot its daily "
                        "Colossus and Predict history here.",
                        className="static-data-page-note",
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
                    dcc.RadioItems(
                        id="pl-history-period",
                        options=period_options,
                        value="1y",
                        inline=True,
                        className="detail-tenor-view-radio pl-history-period",
                    ),
                    dcc.RadioItems(
                        id="pl-history-series-selector",
                        options=[
                            {"label": "Both", "value": "both"},
                            {"label": "Colossus", "value": "colossus"},
                            {"label": "Predict", "value": "predict"},
                        ],
                        value="both",
                        inline=True,
                        className="detail-tenor-view-radio pl-history-series-selector",
                    ),
                    dcc.DatePickerRange(
                        id="pl-history-date-range",
                        minimum_nights=0,
                        display_format="YYYY-MM-DD",
                        clearable=True,
                        start_date_placeholder_text="Start date",
                        end_date_placeholder_text="End date",
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
    )


def _pl_aggregate_section(
    initial_frame: pd.DataFrame | None = None,
) -> html.Section:
    """Build an always-visible, P&L-local mapped Aggregate P&L section."""
    view_dimension_options = [
        {"label": field.label, "value": field.key} for field in VIEW_DIMENSION_FIELDS
    ]
    return html.Section(
        [
            html.H2(
                "Aggregate P&L",
                className="aux-summary aggregate-pl-summary pnl-static-heading",
            ),
            html.Div(
                [
                    html.Div("View by", className="aggregate-pl-title"),
                    dcc.RadioItems(
                        id="pnl-aggregate-pl-dimension",
                        options=view_dimension_options,
                        value=DEFAULT_VIEW_DIMENSION,
                        inline=True,
                        className="aggregate-pl-selector",
                    ),
                ],
                className="aggregate-pl-header",
            ),
            html.Div(
                dcc.Loading(
                    html.Div(
                        (
                            build_pl_aggregate_table(
                                initial_frame,
                                DEFAULT_VIEW_DIMENSION,
                                [],
                            )
                            if initial_frame is not None
                            else html.Div(
                                "P&L data is still loading. Aggregate P&L will "
                                "update after the first committed refresh.",
                                className="empty-state",
                                role="status",
                            )
                        ),
                        id="pnl-aggregate-pl-grid",
                    ),
                    custom_spinner=build_cube_loader("Loading aggregate P&L"),
                    delay_show=120,
                    className="cube-loading-boundary",
                ),
                className="aggregate-pl-panel",
            ),
        ],
        className="aux-details aggregate-pl-details pnl-always-open-section",
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
                        interval=500,
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
                dcc.Store(id="pnl-aggregate-open-risk-types", data=[]),
                html.H1("P&L Sender", className="static-data-page-title"),
                html.P(
                    (
                        "Review mapped Aggregate P&L, edit and send it by SOG or "
                        "Portfolio, and explore official Predict versus Colossus "
                        "P&L. The one saved-view filter governs every section."
                        if send_workflow_available
                        else "Review mapped Aggregate P&L from the latest committed "
                        "risk refresh."
                    ),
                    className="static-data-page-note",
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
            className="static-data-page",
        ),
        id="pnl-page-container",
    )


__all__ = [
    "DISPLAY_COLUMNS",
    "GRID_ROW_ID",
    "PL_AGGREGATE_TOGGLE_TYPE",
    "PL_FILTER_FIELDS",
    "PL_FILTER_EXCLUDE_ID",
    "PL_FILTER_IDS",
    "PL_FILTER_NOTE",
    "PL_SAVED_VIEW_CONTROLS",
    "build_pl_aggregate_table",
    "build_pl_filter_bar",
    "build_pl_inline_history_section",
    "build_pl_page",
    "build_pl_send_sections",
    "pl_filter_map",
    "pl_filter_options",
]
