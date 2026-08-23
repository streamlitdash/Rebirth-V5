"""P&L send/editor layout owned independently from the page shell."""

from __future__ import annotations

from dash import dash_table, dcc, html

from .s01_common import DISPLAY_COLUMNS
from .s06_validation import build_validate_pl_section


def _editor_columns(*, portfolio_editable: bool) -> list[dict[str, object]]:
    """Return native DataTable columns with explicitly governed editability."""
    editable_columns = {"Risk Type", "Risk Greek", "PL"}
    if portfolio_editable:
        editable_columns.add("Portfolio")
    return [
        {
            "name": column,
            "id": column,
            "editable": column in editable_columns,
            **(
                {
                    "type": "numeric",
                    "on_change": {"action": "coerce", "failure": "reject"},
                }
                if column == "PL"
                else {}
            ),
            **(
                {"presentation": "dropdown"}
                if column in {"Risk Type", "Risk Greek", "Portfolio"}
                and column in editable_columns
                else {}
            ),
        }
        for column in DISPLAY_COLUMNS
    ]


def _editor_table(table_id: str, *, portfolio_editable: bool) -> dash_table.DataTable:
    """Build a native spreadsheet editor that patches only changed cells."""
    return dash_table.DataTable(
        id=table_id,
        columns=_editor_columns(portfolio_editable=portfolio_editable),
        data=[],
        editable=True,
        dropdown={},
        dropdown_conditional=[],
        sort_action="none",
        filter_action="none",
        page_action="none",
        cell_selectable=True,
        include_headers_on_copy_paste=True,
        fill_width=False,
        markdown_options={"html": True},
        style_table={
            "height": "460px",
            "overflowX": "auto",
            "overflowY": "auto",
            "border": "1px solid #D9DEE5",
            "borderRadius": "8px",
        },
        style_header={
            "height": "40px",
            "backgroundColor": "#F7F8FA",
            "color": "#111111",
            "border": "1px solid #D9DEE5",
            "fontFamily": '"Segoe UI Variable Text", "Segoe UI", Arial, sans-serif',
            "fontSize": "12px",
            "fontWeight": "850",
            "textAlign": "left",
        },
        style_cell={
            "height": "38px",
            "backgroundColor": "#FFFFFF",
            "color": "#111111",
            "border": "1px solid #E2E6EA",
            "fontFamily": '"Segoe UI Variable Text", "Segoe UI", Arial, sans-serif',
            "fontSize": "13px",
            "lineHeight": "1.35",
            "padding": "8px 10px",
            "textAlign": "left",
            "whiteSpace": "nowrap",
            "overflow": "hidden",
            "textOverflow": "ellipsis",
        },
        style_cell_conditional=[
            {
                "if": {"column_id": "Risk Type"},
                "width": "126px",
                "minWidth": "126px",
                "maxWidth": "126px",
                "backgroundColor": "#C4DEF5",
                "color": "#111111",
                "fontWeight": "850",
                "borderLeft": "2px solid #111111",
                "borderRight": "2px solid #111111",
            },
            {
                "if": {"column_id": "Risk Greek"},
                "width": "132px",
                "minWidth": "132px",
                "maxWidth": "132px",
            },
            {
                "if": {"column_id": "Portfolio"},
                "width": "188px",
                "minWidth": "188px",
                "maxWidth": "188px",
            },
            {
                "if": {"column_id": "SignoffGroup"},
                "width": "188px",
                "minWidth": "188px",
                "maxWidth": "188px",
                "backgroundColor": "#F2F4F6",
                "color": "#4D5965",
            },
            {
                "if": {"column_id": "ConcertoField"},
                "width": "202px",
                "minWidth": "202px",
                "maxWidth": "202px",
                "backgroundColor": "#F2F4F6",
                "color": "#4D5965",
            },
            {
                "if": {"column_id": "PL"},
                "width": "146px",
                "minWidth": "146px",
                "maxWidth": "146px",
                "backgroundColor": "#FFFFE0",
                "color": "#111111",
                "fontWeight": "850",
                "fontVariantNumeric": "tabular-nums",
                "textAlign": "right",
                "borderLeft": "2px solid #111111",
                "borderRight": "2px solid #111111",
            },
            {
                "if": {"column_id": "Adjustment"},
                "width": "118px",
                "minWidth": "118px",
                "maxWidth": "118px",
                "textAlign": "center",
            },
        ],
        style_header_conditional=[
            {
                "if": {"column_id": "Risk Type"},
                "backgroundColor": "#C4DEF5",
                "color": "#111111",
                "borderLeft": "2px solid #111111",
                "borderRight": "2px solid #111111",
            },
            {
                "if": {"column_id": "PL"},
                "backgroundColor": "#FFFFE0",
                "color": "#111111",
                "borderLeft": "2px solid #111111",
                "borderRight": "2px solid #111111",
            },
        ],
        style_data_conditional=[
            {"if": {"filter_query": "{PL} < 0", "column_id": "PL"}, "color": "#B42318"},
            {
                "if": {"state": "active"},
                "boxShadow": "inset 0 0 0 2px #111111",
            },
            {
                "if": {"state": "selected"},
                "backgroundColor": "#EAF2FA",
                "boxShadow": "inset 0 0 0 1px #111111",
            },
        ],
        tooltip_header={
            "SignoffGroup": "Derived from the governed Portfolio registry",
            "ConcertoField": "Derived from the Risk Type + Risk Greek mapping",
        },
        css=[
            {
                "selector": ".Select-menu-outer",
                "rule": "display: block !important; z-index: 1200 !important;",
            },
            {
                "selector": "td.dropdown .Select-control",
                "rule": "height: 36px; border: 0; border-radius: 0; box-shadow: none; font: 600 13px 'Segoe UI Variable Text', 'Segoe UI', Arial, sans-serif;",
            },
        ],
    )


def build_pl_send_sections() -> list[html.Div | html.Details | html.Section]:
    """Return the current governed P&L send, edit, and validation sections."""
    send_all = html.Div(
        html.Div(
            [
                html.Div(
                    [
                        html.H2("Send All P&L", className="section-title"),
                        html.P(
                            "Send the complete governed effective P&L, including "
                            "saved adjustments, to both the SOG and Portfolio "
                            "destinations in one action.",
                            className="unmapped-note",
                        ),
                    ]
                ),
                html.Div(
                    [
                        html.Button(
                            "Send All P&L",
                            id="send-all-pl-button",
                            n_clicks=0,
                            className="pl-action-send",
                            type="button",
                        ),
                        html.Div(
                            id="pl-send-all-status",
                            className="pl-send-status",
                            role="status",
                            **{"aria-live": "polite"},
                        ),
                    ],
                    className="pl-send-actions",
                ),
            ],
            className="pl-send-panel pl-editor-toolbar",
        ),
        id="pl-send-all-panel",
        className="aux-details",
    )
    by_sog = html.Details(
        [
            html.Summary(
                "SOG P&L",
                id="pl-sog-summary",
                n_clicks=0,
                className="aux-summary",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label(
                                        "SignoffGroup", htmlFor="pl-send-sog-filter"
                                    ),
                                    dcc.Dropdown(
                                        id="pl-send-sog-filter",
                                        options=[],
                                        clearable=False,
                                    ),
                                ],
                                className="pl-editor-filter",
                            ),
                            dcc.Checklist(
                                id="pl-sog-include-adjustments",
                                options=[
                                    {"label": "Show adjustments", "value": "include"}
                                ],
                                value=[],
                                className="pl-adjustment-toggle",
                            ),
                        ],
                        className="pl-editor-toolbar",
                    ),
                    html.P(
                        "Single-click Risk Type, Risk Greek, Portfolio or PL to edit. "
                        "Derived fields are locked; every changed or new row is "
                        "automatically marked as an adjustment. Enter commits and "
                        "Escape cancels the active edit.",
                        className="pl-editor-guide",
                    ),
                    html.Div(
                        "Waiting for SOG rows...",
                        id="pl-send-sog-grid-data-status",
                        className="pl-editor-statuses",
                        role="status",
                        **{"aria-live": "polite"},
                    ),
                    html.Div(
                        _editor_table("pl-send-sog-grid", portfolio_editable=True),
                        className="pl-send-editor-table pl-send-table--editor",
                    ),
                    html.Div(
                        [
                            html.Span(
                                id="pl-send-sog-grid-selection-summary-text",
                                className="pl-editor-selection-summary-text",
                            ),
                            html.Button(
                                "×",
                                id="pl-send-sog-grid-selection-clear",
                                className="pl-editor-selection-summary-dismiss",
                                type="button",
                                title="Clear selection",
                                **{"aria-label": "Clear selected cells"},
                            ),
                        ],
                        id="pl-send-sog-grid-selection-summary",
                        className="pl-editor-selection-summary",
                        role="status",
                        hidden=True,
                        **{"aria-live": "polite"},
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Add row",
                                id="add-sog-pl-row",
                                n_clicks=0,
                                className="pl-action-secondary",
                            ),
                            html.Button(
                                "Save Adjustments",
                                id="save-sog-adjustments-button",
                                n_clicks=0,
                                className="pl-action-primary",
                            ),
                            html.Button(
                                "Send SOG PL",
                                id="send-sog-pl-button",
                                n_clicks=0,
                                className="pl-action-send",
                            ),
                        ],
                        className="pl-send-actions",
                    ),
                    html.Div(
                        id="pl-save-sog-adjustments-status",
                        className="pl-send-status",
                        role="status",
                    ),
                    html.Div(
                        id="pl-send-sog-status",
                        className="pl-send-status",
                        role="status",
                    ),
                ],
                className="pl-send-panel",
            ),
        ],
        className="aux-details",
    )
    by_portfolio = html.Details(
        [
            html.Summary(
                "Portfolio P&L",
                id="pl-portfolio-summary",
                n_clicks=0,
                className="aux-summary",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label(
                                        "Portfolio", htmlFor="pl-send-portfolio-filter"
                                    ),
                                    dcc.Dropdown(
                                        id="pl-send-portfolio-filter",
                                        options=[],
                                        clearable=False,
                                    ),
                                ],
                                className="pl-editor-filter",
                            ),
                            dcc.Checklist(
                                id="pl-portfolio-include-adjustments",
                                options=[
                                    {"label": "Show adjustments", "value": "include"}
                                ],
                                value=[],
                                className="pl-adjustment-toggle",
                            ),
                        ],
                        className="pl-editor-toolbar",
                    ),
                    html.P(
                        "Single-click Risk Type, Risk Greek or PL to edit. Portfolio, "
                        "SignoffGroup and ConcertoField stay locked to this governed "
                        "scope. Duplicate ConcertoField rows are aggregated before sending.",
                        className="pl-editor-guide",
                    ),
                    html.Div(
                        "Waiting for Portfolio rows...",
                        id="pl-send-portfolio-grid-data-status",
                        className="pl-editor-statuses",
                        role="status",
                        **{"aria-live": "polite"},
                    ),
                    html.Div(
                        _editor_table(
                            "pl-send-portfolio-grid", portfolio_editable=False
                        ),
                        className="pl-send-editor-table pl-send-table--editor",
                    ),
                    html.Div(
                        [
                            html.Span(
                                id="pl-send-portfolio-grid-selection-summary-text",
                                className="pl-editor-selection-summary-text",
                            ),
                            html.Button(
                                "×",
                                id="pl-send-portfolio-grid-selection-clear",
                                className="pl-editor-selection-summary-dismiss",
                                type="button",
                                title="Clear selection",
                                **{"aria-label": "Clear selected cells"},
                            ),
                        ],
                        id="pl-send-portfolio-grid-selection-summary",
                        className="pl-editor-selection-summary",
                        role="status",
                        hidden=True,
                        **{"aria-live": "polite"},
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Add row",
                                id="add-portfolio-pl-row",
                                n_clicks=0,
                                className="pl-action-secondary",
                            ),
                            html.Button(
                                "Save Adjustments",
                                id="save-portfolio-adjustments-button",
                                n_clicks=0,
                                className="pl-action-primary",
                            ),
                            html.Button(
                                "Send Portfolio PL",
                                id="send-portfolio-pl-button",
                                n_clicks=0,
                                className="pl-action-send",
                            ),
                        ],
                        className="pl-send-actions",
                    ),
                    html.Div(
                        id="pl-save-portfolio-adjustments-status",
                        className="pl-send-status",
                        role="status",
                    ),
                    html.Div(
                        id="pl-send-portfolio-status",
                        className="pl-send-status",
                        role="status",
                    ),
                ],
                className="pl-send-panel",
            ),
        ],
        className="aux-details",
    )
    validate_pl = build_validate_pl_section()
    explorer = html.Section(
        [
            html.H2("P&L Explorer", className="static-data-page-title"),
            html.P(
                "The page filter also governs Validate P&L and History. Missing "
                "Predict or Colossus values remain unavailable rather than zero.",
                className="static-data-page-note",
            ),
            validate_pl,
        ],
        id="pnl-explorer",
        className="pnl-explorer",
    )
    state = html.Div(
        [
            dcc.Store(id="pl-send-sog-effective-store", data={}),
            dcc.Store(id="pl-send-portfolio-effective-store", data={}),
            dcc.Store(id="pl-send-sog-drafts-store", data={}),
            dcc.Store(id="pl-send-portfolio-drafts-store", data={}),
            dcc.Store(id="pl-send-sog-active-scope-store", data={}),
            dcc.Store(id="pl-send-portfolio-active-scope-store", data={}),
            dcc.Store(id="pl-sog-adjustment-revision-store", data=0),
            dcc.Store(id="pl-portfolio-adjustment-revision-store", data=0),
        ],
        id="pl-workflow-state",
        hidden=True,
    )
    return [
        state,
        send_all,
        by_sog,
        by_portfolio,
        explorer,
    ]


__all__ = ["build_pl_send_sections"]
