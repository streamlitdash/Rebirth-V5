"""One hierarchy, click-to-open history, and one collapsed raw connector table."""

import pandas as pd
from dash import dash_table, dcc, html
from dash.dash_table.Format import Format, Scheme

from .s02_history import build_stock_history_empty_figure

STOCK_PERIODS = (
    ("WTD", "wtd"),
    ("MTD", "mtd"),
    ("YTD", "ytd"),
    ("1Y", "1y"),
    ("All", "all"),
    ("Custom", "custom"),
)
TABLE_CELL = {
    "padding": "8px 12px",
    "textAlign": "left",
    "color": "#111111",
    "minWidth": "120px",
    "fontVariantNumeric": "tabular-nums",
}


def stock_table_columns(frame):
    """Format numeric source columns without changing their values or names."""
    return [
        {
            "id": c,
            "name": c,
            **(
                {
                    "type": "numeric",
                    "format": Format(precision=2, scheme=Scheme.fixed, group=","),
                }
                if pd.api.types.is_numeric_dtype(frame[c])
                and not pd.api.types.is_bool_dtype(frame[c])
                else {"type": "text"}
            ),
        }
        for c in frame.columns
    ]


def stock_number_styles(columns):
    return [
        {
            "if": {"column_id": c["id"], "filter_query": "{" + c["id"] + "} < 0"},
            "color": "#c5221f",
        }
        for c in columns
        if c.get("type") == "numeric"
    ]


def stock_table_records(frame):
    return frame.astype(object).where(pd.notna(frame), None).to_dict("records")


def build_stock_page_shell(*, current_date, prior_date=None, history_available=False):
    del prior_date
    return html.Main(
        [
            html.H1("Stock", className="page-title"),
            html.Div(
                [
                    html.Label("Stock date", htmlFor="stock-input-date"),
                    dcc.DatePickerSingle(
                        id="stock-input-date",
                        date=pd.Timestamp(current_date).date().isoformat(),
                        display_format="YYYY-MM-DD",
                        clearable=False,
                        persistence=True,
                        persistence_type="session",
                    ),
                ],
                className="stock-simple-history-controls",
            ),
            dcc.Store(id="stock-loaded-snapshot"),
            dcc.Store(id="stock-pivot-open-paths", data=None),
            dcc.Store(id="stock-row-action"),
            dcc.Store(id="stock-tree-rows"),
            html.Span(id="stock-tree-rendered", hidden=True),
            dcc.Store(id="stock-history-selection"),
            dcc.Interval(id="stock-load-trigger", interval=100, max_intervals=1),
            html.P(
                "Loading Stock…",
                id="stock-load-status",
                role="status",
                className="page-note",
            ),
            html.Section(
                [
                    html.P(
                        "Click a branch to expand it. Click CRDS / CIDS to see its history.",
                        className="page-note",
                    ),
                    html.P(id="stock-row-count", className="page-note"),
                    html.Div(id="stock-current-table", className="risk-table-wrap stock-hierarchy-table-wrap"),
                ],
                className="page-card stock-simple-table",
            ),
            html.Section(
                [
                    html.H2("Stock history", id="stock-history-title"),
                    html.Div(
                        [
                            html.Label("Period", htmlFor="stock-history-period"),
                            dcc.Dropdown(
                                id="stock-history-period",
                                options=[
                                    {"label": label, "value": value}
                                    for label, value in STOCK_PERIODS
                                ],
                                value="all",
                                clearable=False,
                                searchable=False,
                                style={"width": "180px"},
                            ),
                            html.Div(
                                dcc.DatePickerRange(
                                    id="stock-history-date-range",
                                    minimum_nights=0,
                                    display_format="YYYY-MM-DD",
                                    clearable=False,
                                ),
                                id="stock-history-custom-range-control",
                                style={"display": "none"},
                            ),
                        ],
                        className="stock-simple-history-controls",
                    ),
                    html.P(
                        id="stock-history-status", className="page-note", role="status"
                    ),
                    dcc.Loading(
                        dcc.Graph(
                            id="stock-history-chart",
                            figure=build_stock_history_empty_figure(
                                "Click CRDS / CIDS in the table."
                            ),
                            config={"displaylogo": False, "responsive": True},
                        ),
                        delay_show=120,
                    ),
                ],
                id="stock-history-panel",
                style={"display": "none"},
                className="page-card stock-simple-history",
                **{"data-history-available": str(history_available).lower()},
            ),
            html.Details(
                [
                    html.Summary(
                        "Raw connector data", id="stock-raw-summary", n_clicks=0
                    ),
                    html.P(id="stock-raw-status", className="page-note", role="status"),
                    dash_table.DataTable(
                        id="stock-raw-table",
                        data=[],
                        columns=[],
                        page_action="custom",
                        page_current=0,
                        page_size=25,
                        page_count=0,
                        filter_action="custom",
                        filter_query="",
                        filter_options={"case": "insensitive"},
                        sort_action="custom",
                        sort_mode="multi",
                        sort_by=[],
                        cell_selectable=False,
                        style_table={"overflowX": "auto", "width": "100%"},
                        style_cell=TABLE_CELL,
                        style_cell_conditional=[
                            {"if": {"column_type": "numeric"}, "textAlign": "right"}
                        ],
                        css=[
                            {"selector": "table", "rule": "width:100%;min-width:100%;"},
                        ],
                    ),
                ],
                id="stock-raw-panel",
                open=False,
                className="page-card stock-simple-raw",
            ),
        ],
        id="stock-page",
        className="page-frame stock-simple-page",
    )
