"""Read and governed-write layout for the Statics page."""

from __future__ import annotations

from typing import Any

from dash import dash_table, dcc, html

from .s01_store import STATIC_FILE_LABELS, StaticDataStore


_STORE = StaticDataStore()
STATIC_FILE_OPTIONS = _STORE.options()
STATIC_WRITE_OPTIONS = _STORE.options(writable=True)


def _table_style() -> dict[str, object]:
    return {
        "filter_action": "native",
        "filter_options": {"case": "insensitive"},
        "sort_action": "native",
        "sort_mode": "multi",
        "page_action": "native",
        "page_size": 50,
        "style_table": {"overflowX": "auto", "maxHeight": "68vh"},
        "style_header": {
            "backgroundColor": "var(--surface-muted)",
            "color": "var(--text)",
            "fontWeight": "700",
            "border": "1px solid var(--outline)",
            "fontSize": "12px",
        },
        "style_cell": {
            "backgroundColor": "var(--surface)",
            "color": "var(--text)",
            "border": "1px solid var(--outline)",
            "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
            "fontSize": "12px",
            "padding": "8px 10px",
            "textAlign": "left",
            "whiteSpace": "normal",
            "minWidth": "100px",
            "width": "150px",
        },
    }


def _editable_columns(columns: list[str]) -> list[dict[str, object]]:
    """Keep governed schema names fixed while allowing columns to be hidden."""

    return [
        {
            "name": column,
            "id": column,
            "hideable": True,
            "renamable": False,
            "deletable": False,
        }
        for column in columns
    ]


def build_static_data_table(
    file_key: str,
    *,
    store: StaticDataStore = _STORE,
) -> html.Div:
    """Build one bounded read-only table from an approved file."""

    try:
        frame = store.read(file_key)
    except ValueError as exc:
        return html.Div(str(exc), className="static-data-empty", role="alert")
    label = STATIC_FILE_LABELS.get(file_key, file_key)
    return html.Div(
        [
            html.Div(
                [
                    html.Span(f"File: {label}", className="static-data-file-label"),
                    html.Span(
                        f"Rows: {len(frame):,}", className="static-data-row-count"
                    ),
                    html.Span(
                        f"Columns: {len(frame.columns)}",
                        className="static-data-col-count",
                    ),
                ],
                className="static-data-meta",
            ),
            dash_table.DataTable(
                id=f"static-data-table-{file_key.removesuffix('.csv')}",
                columns=[{"name": column, "id": column} for column in frame.columns],
                data=frame.to_dict("records"),
                editable=False,
                **_table_style(),
            ),
        ],
        className="page-card static-data-panel",
    )


def build_static_data_page() -> html.Div:
    """Build two plain Statics workspaces; all file reads remain callback-lazy."""

    if not STATIC_FILE_OPTIONS:
        return html.Div(
            "No approved static data files are available.",
            id="static-data-page",
            className="page-frame static-data-empty",
        )
    write_value = STATIC_WRITE_OPTIONS[0]["value"] if STATIC_WRITE_OPTIONS else None
    return html.Div(
        [
            dcc.Store(id="static-data-revision", data=0),
            html.Header(
                [
                    html.P("REFERENCE DATA", className="page-eyebrow"),
                    html.H1("Statics", className="page-title"),
                    html.P(
                        "Read reference data, or edit the small governed mapping files.",
                        className="page-intro",
                    ),
                ],
                className="page-header",
            ),
            dcc.Tabs(
                id="static-data-mode",
                value="read",
                children=[
                    dcc.Tab(label="Read", value="read"),
                    dcc.Tab(label="Write", value="write"),
                ],
                className="workspace-tabs static-data-tabs",
            ),
            html.Section(
                [
                    dcc.Dropdown(
                        id="static-data-file-selector",
                        options=STATIC_FILE_OPTIONS,
                        value=STATIC_FILE_OPTIONS[0]["value"],
                        clearable=False,
                        className="static-data-selector",
                    ),
                    html.Div(
                        id="static-data-table-container",
                        className="static-data-container",
                    ),
                ],
                id="static-data-read-panel",
                className="static-data-workspace",
            ),
            html.Section(
                [
                    html.Div(
                        [
                            dcc.Dropdown(
                                id="static-data-write-selector",
                                options=STATIC_WRITE_OPTIONS,
                                value=write_value,
                                clearable=False,
                                className="static-data-selector",
                            ),
                            html.Button(
                                "Add row",
                                id="static-data-add-row",
                                n_clicks=0,
                                className="action-button action-secondary",
                                type="button",
                            ),
                            html.Button(
                                "Save",
                                id="static-data-save",
                                n_clicks=0,
                                className="action-button action-primary",
                                type="button",
                            ),
                            html.Button(
                                "Cancel",
                                id="static-data-cancel",
                                n_clicks=0,
                                className="action-button action-secondary",
                                type="button",
                            ),
                        ],
                        className="static-data-write-actions",
                    ),
                    html.P(
                        "Edit cells directly, remove rows with the row action, and hide "
                        "columns from the header menu. Governed connector columns stay "
                        "locked so a saved edit cannot break the application. Save "
                        "validates the complete table and replaces the CSV atomically. "
                        "Saved rows are read back when this page is reopened; Plotly "
                        "runtime files may still reset after a restart or redeploy.",
                        className="page-note",
                    ),
                    dash_table.DataTable(
                        id="static-data-write-table",
                        columns=[],
                        data=[],
                        editable=True,
                        row_deletable=True,
                        **_table_style(),
                    ),
                    html.Div(
                        id="static-data-write-status",
                        className="pl-send-status",
                        role="status",
                        **{"aria-live": "polite"},
                    ),
                ],
                id="static-data-write-panel",
                className="static-data-workspace",
                style={"display": "none"},
            ),
        ],
        id="static-data-page",
        className="page-frame",
    )


def layout(**_kwargs: Any) -> html.Div:
    return build_static_data_page()


__all__ = [
    "STATIC_FILE_OPTIONS",
    "STATIC_WRITE_OPTIONS",
    "_editable_columns",
    "build_static_data_page",
    "build_static_data_table",
    "layout",
]
