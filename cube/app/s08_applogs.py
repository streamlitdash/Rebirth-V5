"""Bounded, process-local application log drawer for operators."""

from __future__ import annotations

from collections.abc import Callable

from dash import Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from cube.app.s03_logging import recent_application_log_text


ApplicationLogSource = Callable[[], str]


def build_app_log_panel() -> html.Aside:
    """Return the shared log drawer without polling or browser persistence."""

    return html.Aside(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H2(
                                "Application log summary", className="app-log-title"
                            ),
                            html.P(
                                "Safe events from this server process only. Exact messages "
                                "and tracebacks remain in Preview/terminal; operating-system "
                                "output is not exposed here.",
                                className="app-log-note",
                            ),
                        ]
                    ),
                    html.Div(
                        [
                            html.Button(
                                "Refresh",
                                id="app-log-refresh-button",
                                n_clicks=0,
                                type="button",
                                className="app-log-action",
                            ),
                            html.Button(
                                "Close",
                                id="app-log-close-button",
                                n_clicks=0,
                                type="button",
                                className="app-log-action",
                            ),
                        ],
                        className="app-log-actions",
                    ),
                ],
                className="app-log-panel-header",
            ),
            html.Pre(
                "Open App Logs to read the latest safe application events.",
                id="app-log-content",
                className="app-log-content",
                **{"aria-live": "off"},
            ),
        ],
        id="app-log-panel",
        className="app-log-panel",
        hidden=True,
        role="dialog",
        **{
            "aria-label": "Application logs",
            "aria-modal": "false",
        },
    )


def register_app_log_callbacks(
    app,
    *,
    log_source: ApplicationLogSource = recent_application_log_text,
) -> None:
    """Register one explicit open/refresh/close callback for the shared drawer."""

    @app.callback(
        Output("app-log-panel", "hidden"),
        Output("app-log-content", "children"),
        Output("app-log-toggle", "aria-expanded"),
        Input("app-log-toggle", "n_clicks"),
        Input("app-log-refresh-button", "n_clicks"),
        Input("app-log-close-button", "n_clicks"),
        State("app-log-panel", "hidden"),
        prevent_initial_call=True,
    )
    def update_app_log_panel(
        _toggle_clicks,
        _refresh_clicks,
        _close_clicks,
        panel_hidden,
    ):
        triggered = ctx.triggered_id
        if triggered == "app-log-close-button":
            return True, no_update, "false"
        if triggered == "app-log-refresh-button":
            return False, log_source(), "true"
        if triggered != "app-log-toggle":
            raise PreventUpdate
        next_hidden = not bool(panel_hidden)
        return (
            next_hidden,
            no_update if next_hidden else log_source(),
            str(not next_hidden).lower(),
        )


__all__ = ["build_app_log_panel", "register_app_log_callbacks"]
