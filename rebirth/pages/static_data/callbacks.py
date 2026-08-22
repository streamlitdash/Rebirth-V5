"""Page-owned Dash callback registration for the V4 Statics page."""

from __future__ import annotations

from typing import Any

from dash import Input, Output, html

from .view import build_static_data_table


def register_callbacks(app: Any) -> None:
    """Register the callback owned exclusively by the Statics page."""

    @app.callback(
        Output("static-data-table-container", "children"),
        Input("static-data-file-selector", "value"),
    )
    def render_static_data_table(selected_file):
        if not selected_file:
            return html.Div("No file selected.", className="static-data-empty")
        return build_static_data_table(selected_file)


__all__ = ["register_callbacks"]
