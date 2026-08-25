"""Page-owned callbacks for Statics read and governed write modes."""

from __future__ import annotations

from typing import Any

from dash import Input, Output, State, ctx, html, no_update

from .s01_store import STATIC_FILE_LABELS, StaticDataStore
from .s02_view import _editable_columns, build_static_data_table


def _editable_payload(store: StaticDataStore, file_key: object):
    frame = store.read(file_key)
    columns = _editable_columns(list(frame.columns))
    return columns, frame.to_dict("records")


def register_callbacks(app: Any, *, store: StaticDataStore | None = None) -> None:
    """Register the callbacks owned exclusively by the Statics page."""

    static_store = store or StaticDataStore()

    @app.callback(
        Output("static-data-read-panel", "style"),
        Output("static-data-write-panel", "style"),
        Input("static-data-mode", "value"),
    )
    def switch_static_mode(mode):
        visible = {"display": "block"}
        hidden = {"display": "none"}
        return (hidden, visible) if mode == "write" else (visible, hidden)

    @app.callback(
        Output("static-data-table-container", "children"),
        Input("static-data-file-selector", "value"),
        Input("static-data-revision", "data"),
    )
    def render_static_data_table(selected_file, _revision):
        if not selected_file:
            return html.Div("No file selected.", className="static-data-empty")
        return build_static_data_table(selected_file, store=static_store)

    @app.callback(
        Output("static-data-write-table", "columns"),
        Output("static-data-write-table", "data"),
        Output("static-data-write-status", "children"),
        Output("static-data-revision", "data"),
        Input("static-data-write-selector", "value"),
        Input("static-data-add-row", "n_clicks"),
        Input("static-data-save", "n_clicks"),
        Input("static-data-cancel", "n_clicks"),
        State("static-data-write-table", "columns"),
        State("static-data-write-table", "data"),
        State("static-data-revision", "data"),
        prevent_initial_call=False,
        running=[
            (Output("static-data-save", "disabled"), True, False),
            (Output("static-data-cancel", "disabled"), True, False),
        ],
    )
    def edit_static_file(
        selected_file,
        _add_clicks,
        _save_clicks,
        _cancel_clicks,
        columns,
        rows,
        revision,
    ):
        if not selected_file:
            return [], [], "No writable file selected.", no_update
        trigger = ctx.triggered_id
        try:
            if trigger == "static-data-add-row":
                names = [str(column.get("id", "")) for column in (columns or [])]
                current = list(rows or [])
                current.append({name: "" for name in names})
                return (
                    columns or [],
                    current,
                    "New row added. Save or Cancel.",
                    no_update,
                )
            if trigger == "static-data-save":
                names = [str(column.get("id", "")) for column in (columns or [])]
                saved = static_store.write(selected_file, rows or [], names)
                label = STATIC_FILE_LABELS.get(str(selected_file), str(selected_file))
                return (
                    _editable_columns(list(saved.columns)),
                    saved.to_dict("records"),
                    f"Saved {label} atomically ({len(saved):,} rows). Refresh the "
                    "affected data source when you are ready to commit it to the app.",
                    int(revision or 0) + 1,
                )
            loaded_columns, loaded_rows = _editable_payload(
                static_store,
                selected_file,
            )
            message = (
                "Changes cancelled; the last saved file has been restored."
                if trigger == "static-data-cancel"
                else f"Editing {STATIC_FILE_LABELS.get(str(selected_file), selected_file)}."
            )
            return loaded_columns, loaded_rows, message, no_update
        except (TypeError, ValueError, OSError) as exc:
            return columns or [], rows or [], f"Not saved: {exc}", no_update


__all__ = ["register_callbacks"]
