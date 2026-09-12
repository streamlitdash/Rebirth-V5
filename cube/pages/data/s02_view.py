"""Data: one search, one selection, then Risk, Market or both."""

from __future__ import annotations

import plotly.graph_objects as go
from dash import dash_table, dcc, html

PERIOD_OPTIONS = (("WTD", "wtd"), ("MTD", "mtd"), ("YTD", "ytd"),
                  ("1Y", "1y"), ("5Y", "5y"), ("All", "all"), ("Custom", "custom"))


def empty_history_figure(message):
    figure = go.Figure()
    figure.add_annotation(text=message, x=.5, y=.5, xref="paper", yref="paper", showarrow=False)
    figure.update_layout(template="plotly_white", margin=dict(l=55, r=25, t=40, b=50))
    return figure


def _panel(kind):
    return html.Section([
        html.H2(kind.title(), id=f"data-{kind}-title"),
        dcc.Graph(id=f"data-{kind}-chart", figure=empty_history_figure("Choose an underlying above."),
                  config={"displaylogo": False, "responsive": True}, style={"height": "430px"}),
        html.Details([html.Summary("Selected date values"), dash_table.DataTable(
            id=f"data-{kind}-table", data=[], columns=[], page_size=15,
            page_action="native", sort_action="native", filter_action="native",
            style_table={"overflowX": "auto"},
            style_cell={"fontFamily": "inherit", "padding": "8px"},
        )]),
    ], id=f"data-{kind}-panel", className="page-card data-series-panel")


def build_data_page(*, cube_href="/", pnl_href="/pnl", stock_href="/stock"):
    del cube_href, pnl_href, stock_href
    return html.Main([
        dcc.Store(id="data-current-choices", data={}),
        dcc.Store(id="data-archive-choices", data={}),
        dcc.Store(id="data-selection-store"),
        dcc.Store(id="data-selected-option"),
        dcc.Store(id="data-history-bundle-store"),
        dcc.Store(id="data-player-state-store"),
        dcc.Store(id="data-player-visibility-store", data={"hidden": False, "sequence": 0}),
        dcc.Interval(id="data-history-generation-interval", interval=60_000, n_intervals=0),
        dcc.Interval(id="data-player-interval", interval=900, n_intervals=0, disabled=True),
        html.Header([html.P("History", className="page-eyebrow"), html.H1("Data", className="page-title"),
                     html.P("Find an underlying, then view its Risk, Market or both. Open in Data carries the selected underlying and page filters here.", className="page-intro")], className="page-header"),
        html.Section([
            html.Label("Underlying", htmlFor="data-underlying"),
            dcc.Dropdown(id="data-underlying", options=[], value=None, searchable=True,
                         clearable=False, maxHeight=320, optionHeight=38,
                         placeholder="Search underlyings, risk types or Greeks…"),
            html.Div(id="data-search-status", className="data-history-status"),
            dcc.Loading(html.Span(id="data-archive-status", className="data-history-status"),
                        type="dot", delay_show=250),
            dcc.RadioItems(id="data-history-kind-tabs", options=[
                {"label": "Risk", "value": "risk"}, {"label": "Market", "value": "market"},
                {"label": "Both", "value": "both"}], value="risk", inline=True,
                className="data-mode-choice"),
            html.Div([
                html.Label("Market series", htmlFor="data-market-choice"),
                dcc.Dropdown(id="data-market-choice", options=[], value=None, clearable=False),
                html.Small("This reported underlying contains several raw Market series. Choose the quote to compare; Risk keeps the complete selected scope."),
            ], id="data-market-choice-control", hidden=True),
            html.Div(id="data-selection-status", role="status", className="data-history-status"),
            html.Div(id="data-identity-breadcrumb", className="data-identity-breadcrumb"),
            html.Div([
                html.Label("Period", htmlFor="data-period"),
                dcc.RadioItems(id="data-period", options=[{"label": label, "value": value} for label, value in PERIOD_OPTIONS],
                               value="all", inline=True, className="data-period-segmented"),
                html.Div(dcc.DatePickerRange(id="data-custom-range", minimum_nights=0,
                                            display_format="YYYY-MM-DD"), id="data-custom-range-control", hidden=True),
            ], className="data-period-control"),
            html.Div(id="data-history-status", role="status", className="data-history-status"),
        ], className="page-card data-request-panel"),
        html.Div([
            html.Button("Play", id="data-player-button", n_clicks=0, disabled=True, className="data-player-button"),
            dcc.Slider(id="data-player-slider", min=0, max=0, value=0, step=1, marks={},
                       disabled=True, updatemode="drag", className="data-player-slider"),
            html.Span("No date", id="data-player-date-pill", className="data-date-pill"),
        ], id="data-player-controls", className="data-player-controls"),
        html.Div([_panel("risk"), _panel("market")], id="data-history-results", className="data-series-grid", **{"data-refresh-render": ""}),
    ], id="data-page", className="page-frame data-page")


__all__ = ["PERIOD_OPTIONS", "build_data_page", "empty_history_figure"]
