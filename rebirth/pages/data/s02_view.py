"""Layout and ProductSpec-shaped figures owned by the native Data page."""

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

    # Navigation belongs to the shared application shell.  Keep these keyword
    # arguments for the factory boundary while the V4.1 tree is being renamed.
    del cube_href, pnl_href, stock_href

    return html.Main(
        [
            dcc.Store(id="data-history-catalog-store", storage_type="memory"),
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
                interval=60_000,
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
                    html.P("Historical explorer", className="page-eyebrow"),
                    html.H1("Data", className="page-title"),
                    html.P(
                        "Explore Risk and Market history with the same identity "
                        "controls. Quick Risk and Quick Market only prefill them.",
                        className="page-intro",
                    ),
                ],
                className="page-header",
            ),
            html.Section(
                [
                    dcc.Tabs(
                        id="data-history-kind-tabs",
                        value="risk",
                        children=[
                            dcc.Tab(label="Risk History", value="risk"),
                            dcc.Tab(label="Market History", value="market"),
                        ],
                        className="data-history-kind-tabs",
                    ),
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label(
                                        "Identity", htmlFor="data-identity-mode"
                                    ),
                                    dcc.RadioItems(
                                        id="data-identity-mode",
                                        options=[
                                            {
                                                "label": "Reported underlying",
                                                "value": "reported",
                                            },
                                            {
                                                "label": "Raw underlying",
                                                "value": "underlying",
                                            },
                                        ],
                                        value="reported",
                                        inline=True,
                                    ),
                                ],
                                className="data-control",
                            ),
                            html.Div(
                                [
                                    html.Label("Risk Type", htmlFor="data-risk-type"),
                                    dcc.Dropdown(
                                        id="data-risk-type",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                    ),
                                ],
                                className="data-control",
                            ),
                            html.Div(
                                [
                                    html.Label("Risk Greek", htmlFor="data-risk-greek"),
                                    dcc.Dropdown(
                                        id="data-risk-greek",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                    ),
                                ],
                                className="data-control",
                            ),
                            html.Div(
                                [
                                    html.Label("Underlying", htmlFor="data-underlying"),
                                    dcc.Dropdown(
                                        id="data-underlying",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        searchable=True,
                                    ),
                                ],
                                className="data-control data-underlying-control",
                            ),
                        ],
                        className="data-controls data-identity-controls",
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Load history",
                                id="data-load-history-button",
                                n_clicks=0,
                                className="data-player-button",
                            ),
                            html.Span(
                                "Archive choices load only on this page.",
                                id="data-catalog-status",
                                className="data-history-status",
                            ),
                        ],
                        className="data-selection-actions",
                    ),
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
                        [
                            html.Div(
                                [
                                    html.Label(
                                        "View",
                                        htmlFor="data-history-projection",
                                    ),
                                    dcc.Dropdown(
                                        id="data-history-projection",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        searchable=False,
                                        disabled=True,
                                    ),
                                ],
                                className="data-control",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Slice",
                                        id="data-history-slice-label",
                                        htmlFor="data-history-slice",
                                    ),
                                    dcc.Dropdown(
                                        id="data-history-slice",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        searchable=False,
                                        disabled=True,
                                    ),
                                ],
                                id="data-history-slice-control",
                                className="data-control",
                                style={"display": "none"},
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Label(
                                                "Date A",
                                                htmlFor="data-history-date-a",
                                            ),
                                            dcc.Dropdown(
                                                id="data-history-date-a",
                                                options=[],
                                                value=None,
                                                clearable=False,
                                                searchable=False,
                                            ),
                                        ],
                                        className="data-control",
                                    ),
                                    html.Div(
                                        [
                                            html.Label(
                                                "Date B",
                                                htmlFor="data-history-date-b",
                                            ),
                                            dcc.Dropdown(
                                                id="data-history-date-b",
                                                options=[],
                                                value=None,
                                                clearable=False,
                                                searchable=False,
                                            ),
                                        ],
                                        className="data-control",
                                    ),
                                ],
                                id="data-history-comparison-dates",
                                className="data-controls",
                                style={"display": "none"},
                            ),
                        ],
                        id="data-history-projection-controls",
                        className="data-controls",
                    ),
                    html.Div(
                        "Choose an exact identity, then load its history.",
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
                className="page-card data-request-panel",
            ),
            html.Section(
                [
                    html.Div(
                        [
                            html.Span(
                                "Static view",
                                id="data-player-mode-pill",
                                className="data-player-mode-pill",
                            ),
                            html.Button(
                                "▶  Play",
                                id="data-player-button",
                                n_clicks=0,
                                disabled=True,
                                className="data-player-button",
                                title="Play through archive dates",
                                **{"aria-label": "Play through archive dates"},
                            ),
                            dcc.Slider(
                                id="data-player-slider",
                                min=0,
                                max=0,
                                step=1,
                                value=0,
                                marks={},
                                disabled=True,
                                updatemode="drag",
                                tooltip={
                                    "placement": "bottom",
                                    "always_visible": False,
                                },
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
                className="page-card data-chart-panel",
            ),
            html.Section(
                [
                    html.Div(
                        [
                            html.H2("Selected date values"),
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
                        className="page-card data-table-panel",
                    ),
                ],
                className="data-tables",
            ),
        ],
        id="data-page",
        className="page-frame data-page",
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
