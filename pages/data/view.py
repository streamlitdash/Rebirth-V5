"""Layout and ProductSpec-shaped figures for the native Data page."""

from __future__ import annotations

import plotly.graph_objects as go
from dash import dash_table, dcc, html


PERIOD_OPTIONS = (
    ("WTD", "wtd"),
    ("MTD", "mtd"),
    ("YTD", "ytd"),
    ("1Y", "1y"),
    ("5Y", "5y"),
    ("All", "all"),
    ("Custom", "custom"),
)


def build_data_page(
    *,
    cube_href: str = "/",
    pnl_href: str = "/pnl",
    stock_href: str = "/stock",
) -> html.Main:
    """Build one lazy history workspace; no archive access occurs here."""

    return html.Main(
        [
            dcc.Store(id="data-history-bundle-store", storage_type="memory"),
            dcc.Store(
                id="data-history-cache-state-store",
                data={"generation": None, "reset_generation": None},
            ),
            dcc.Store(
                id="data-player-state-store",
                data={"playing": False, "index": 0, "key": None},
            ),
            dcc.Store(
                id="data-player-visibility-store",
                data={"hidden": False, "sequence": 0},
            ),
            dcc.Interval(
                id="data-history-generation-interval",
                interval=15_000,
                n_intervals=0,
            ),
            dcc.Interval(
                id="data-player-interval",
                interval=900,
                n_intervals=0,
                disabled=True,
            ),
            html.Header(
                [
                    html.Div(
                        [
                            html.P("V3.2 history", className="data-page-eyebrow"),
                            html.H1("Data", className="static-data-page-title"),
                            html.P(
                                "Open an exact identity from Quick Risk or Quick Market.",
                                className="data-page-intro",
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            dcc.Link(
                                "Risk", href=cube_href, className="data-page-link"
                            ),
                            dcc.Link("P&L", href=pnl_href, className="data-page-link"),
                            dcc.Link(
                                "Stock", href=stock_href, className="data-page-link"
                            ),
                        ],
                        className="data-page-links",
                    ),
                ],
                className="data-page-header",
            ),
            html.Section(
                [
                    html.Div(
                        "No history identity selected",
                        id="data-identity-breadcrumb",
                        className="data-identity-breadcrumb",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Metric", htmlFor="data-metric"),
                                    dcc.Dropdown(
                                        id="data-metric",
                                        options=[{"label": "Risk", "value": "risk"}],
                                        value="risk",
                                        clearable=False,
                                    ),
                                ],
                                className="data-control",
                            ),
                            html.Div(
                                [
                                    html.Label("Period", htmlFor="data-period"),
                                    dcc.RadioItems(
                                        id="data-period",
                                        options=[
                                            {"label": label, "value": value}
                                            for label, value in PERIOD_OPTIONS
                                        ],
                                        value="all",
                                        inline=True,
                                        className="detail-tenor-view-radio",
                                    ),
                                ],
                                className="data-control data-period-control",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Custom dates", htmlFor="data-custom-range"
                                    ),
                                    dcc.DatePickerRange(
                                        id="data-custom-range",
                                        start_date=None,
                                        end_date=None,
                                        display_format="YYYY-MM-DD",
                                        minimum_nights=0,
                                        clearable=True,
                                    ),
                                ],
                                id="data-custom-range-control",
                                className="data-control",
                                hidden=True,
                            ),
                        ],
                        className="data-controls",
                    ),
                    html.Div(
                        "Open an identity from the Risk page to load history.",
                        id="data-history-status",
                        className="data-history-status",
                        role="status",
                        **{"aria-live": "polite"},
                    ),
                    html.Div(
                        "",
                        id="data-clear-status",
                        className="data-clear-status",
                        role="status",
                        **{"aria-live": "polite"},
                    ),
                ],
                className="data-request-panel",
            ),
            html.Section(
                [
                    html.Div(
                        [
                            html.Button(
                                "Play",
                                id="data-player-button",
                                n_clicks=0,
                                disabled=True,
                                className="data-player-button",
                            ),
                            dcc.Slider(
                                id="data-player-slider",
                                min=0,
                                max=0,
                                step=1,
                                value=0,
                                marks={},
                                disabled=True,
                                className="data-player-slider",
                            ),
                            html.Span(
                                "No date",
                                id="data-player-date-pill",
                                className="data-date-pill",
                            ),
                        ],
                        id="data-player-controls",
                        className="data-player-controls",
                    ),
                    dcc.Loading(
                        dcc.Graph(
                            id="data-history-chart",
                            figure=empty_history_figure(
                                "Open an identity to load its history."
                            ),
                            config={"displaylogo": False, "responsive": True},
                            className="data-history-chart",
                        ),
                        type="dot",
                        delay_show=160,
                    ),
                ],
                className="data-chart-panel",
            ),
            html.Section(
                [
                    html.Div(
                        [
                            html.H2("Selected date — exact rows"),
                            dash_table.DataTable(
                                id="data-selected-table",
                                data=[],
                                columns=[],
                                page_size=12,
                                page_action="native",
                                sort_action="native",
                                filter_action="none",
                                style_table={"overflowX": "auto"},
                            ),
                        ],
                        className="data-table-panel",
                    ),
                    html.Div(
                        [
                            html.H2("Raw period rows"),
                            dash_table.DataTable(
                                id="data-raw-table",
                                data=[],
                                columns=[],
                                page_size=20,
                                page_action="native",
                                sort_action="native",
                                filter_action="none",
                                style_table={"overflowX": "auto"},
                            ),
                        ],
                        className="data-table-panel",
                    ),
                ],
                className="data-tables",
            ),
        ],
        id="data-page",
        className="data-page",
    )


def empty_history_figure(message: str) -> go.Figure:
    """Return a stable empty chart rather than a misleading zero series."""

    figure = go.Figure()
    figure.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
    )
    figure.update_layout(
        template="plotly_white",
        margin={"l": 48, "r": 24, "t": 48, "b": 48},
        uirevision="data-empty",
    )
    return figure


__all__ = [
    "PERIOD_OPTIONS",
    "build_data_page",
    "empty_history_figure",
]
