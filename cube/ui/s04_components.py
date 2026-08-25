"""Cross-page Dash components for tables, loading, and refresh lifecycle."""

from __future__ import annotations

from typing import Mapping

import pandas as pd
from dash import dcc, html

from cube.app.s02_contracts import ControlSnapshotProtocol, RefreshSnapshotProtocol
from cube.ui.s02_aggregation import (
    dimension_title,
    format_number,
    number_sign_class,
    ordered_unique,
    selected_dimension,
)
from cube.ui.s01_constants import ROW_TOGGLE_CLOSED_GLYPH, ROW_TOGGLE_OPEN_GLYPH


def build_aggregate_pl_table(
    frame: pd.DataFrame,
    dimension: str,
    open_risk_types: list[str] | None,
    *,
    metric_cell_type: str | None = None,
) -> html.Div:
    """Build the global P&L pivot, collapsed to Risk Type on first load."""
    if frame.empty:
        return html.Div(
            "No P&L rows are available.", className="empty-state", role="status"
        )
    column = selected_dimension(dimension)
    dimension_values = ordered_unique(frame, column)
    open_set = set(open_risk_types or [])

    def pl_cells(
        scoped: pd.DataFrame,
        *,
        risk_type: str = "",
        risk_greek: str = "",
    ) -> list[html.Td]:
        values = scoped.groupby(column)["pl"].sum(min_count=1).reindex(dimension_values)
        numbers = [float(values[value]) for value in dimension_values]
        numbers.append(float(scoped["pl"].sum(min_count=1)))
        cells: list[html.Td] = []
        for index, value in enumerate(numbers):
            dimension_value = (
                str(dimension_values[index])
                if index < len(dimension_values)
                else "__total__"
            )
            content = html.Span(format_number(value), className="copy-value")
            if metric_cell_type:
                content = html.Button(
                    content,
                    id={
                        "type": metric_cell_type,
                        "risk_type": str(risk_type),
                        "risk_greek": str(risk_greek),
                        "dimension": str(dimension),
                        "value": dimension_value,
                    },
                    n_clicks=0,
                    className="aggregate-pl-history-button",
                    title="Show this P&L history below",
                    type="button",
                )
            cells.append(
                html.Td(
                    content,
                    className=(
                        f"aggregate-pl-number metric-cell {number_sign_class(value)}"
                        + (" pl-cell total-column" if index == len(numbers) - 1 else "")
                    ),
                    **{
                        "data-metric": (
                            f"pl:{dimension_values[index]}"
                            if index < len(dimension_values)
                            else "pl:Total"
                        )
                    },
                )
            )
        return cells

    rows: list[html.Tr] = []
    for risk_type in ordered_unique(frame, "risk type"):
        scoped_type = frame.loc[frame["risk type"].eq(risk_type)]
        is_open = risk_type in open_set
        toggle_action = "Collapse" if is_open else "Expand"
        toggle_label = f"{toggle_action} {risk_type} greeks"
        rows.append(
            html.Tr(
                [
                    html.Th(
                        [
                            html.Button(
                                (
                                    ROW_TOGGLE_OPEN_GLYPH
                                    if is_open
                                    else ROW_TOGGLE_CLOSED_GLYPH
                                ),
                                id={
                                    "type": "aggregate-row-toggle",
                                    "risk_type": risk_type,
                                },
                                n_clicks=0,
                                className="row-toggle aggregate-row-toggle",
                                title=toggle_label,
                                **{
                                    "aria-label": toggle_label,
                                    "aria-expanded": str(is_open).lower(),
                                },
                            ),
                            html.Span(risk_type),
                        ],
                        scope="row",
                        className="aggregate-index aggregate-risk-type",
                        **{"data-metric": "index", "data-copy-value": str(risk_type)},
                    ),
                    *pl_cells(scoped_type, risk_type=str(risk_type)),
                ],
                className="aggregate-risk-row",
                **{
                    "aria-level": "1",
                    "aria-expanded": str(is_open).lower(),
                },
            )
        )
        if is_open:
            for greek in ordered_unique(scoped_type, "risk greek"):
                scoped_greek = scoped_type.loc[scoped_type["risk greek"].eq(greek)]
                rows.append(
                    html.Tr(
                        [
                            html.Th(
                                html.Span(greek, className="row-label-text"),
                                scope="row",
                                className="aggregate-index aggregate-greek",
                                **{
                                    "data-metric": "index",
                                    "data-copy-value": str(greek),
                                },
                            ),
                            *pl_cells(
                                scoped_greek,
                                risk_type=str(risk_type),
                                risk_greek=str(greek),
                            ),
                        ],
                        className="aggregate-greek-row",
                        **{"aria-level": "2"},
                    )
                )

    rows.append(
        html.Tr(
            [
                html.Th(
                    "TOTAL",
                    scope="row",
                    className="aggregate-index aggregate-total-index",
                    **{"data-metric": "index", "data-copy-value": "TOTAL"},
                ),
                *pl_cells(frame),
            ],
            className="aggregate-total-row",
        )
    )

    headers = ["Index", *dimension_values, "Total"]
    return html.Div(
        [
            html.Div("", className="selection-summary", **{"aria-live": "polite"}),
            html.Table(
                [
                    html.Caption(
                        f"Aggregate P&L by {dimension_title(dimension)}",
                        className="sr-only",
                    ),
                    html.Thead(
                        html.Tr(
                            [
                                html.Th(
                                    value,
                                    scope="col",
                                    className=(
                                        "index-header"
                                        if value == "Index"
                                        else "metric-header total-column"
                                        if value == "Total"
                                        else "metric-header"
                                    ),
                                    **{
                                        "data-metric": (
                                            f"pl:{value}"
                                            if value != "Index"
                                            else "index"
                                        )
                                    },
                                )
                                for value in headers
                            ]
                        )
                    ),
                    html.Tbody(rows),
                ],
                className="cell-selection-table aggregate-pl-table",
                role="treegrid",
                **{"aria-label": "Aggregate P&L hierarchy"},
            ),
        ],
        className="risk-table-wrap aggregate-pl-table-wrap",
    )


def _cube_mark(class_name: str) -> html.Span:
    """Return the shared six-face cube and compact rolling layers."""
    return html.Span(
        html.Span(
            html.Span(
                [
                    html.Span(className="cube-motion__shadow"),
                    html.Span(
                        html.Span(
                            html.Span(
                                html.Span(
                                    [
                                        html.I(
                                            className=(
                                                "cube-motion__face "
                                                f"cube-motion__face--{face}"
                                            )
                                        )
                                        for face in (
                                            "front",
                                            "back",
                                            "right",
                                            "left",
                                            "top",
                                            "bottom",
                                        )
                                    ],
                                    className="cube-motion__solid",
                                ),
                                className="cube-motion__view",
                            ),
                            className="cube-motion__roller",
                        ),
                        className="cube-motion__lift",
                    ),
                ],
                className="cube-motion__traveller",
            ),
            className="cube-motion__scene",
        ),
        className=f"cube-motion {class_name}",
        **{"aria-hidden": "true"},
    )


def build_cube_loader(
    label: str = "Loading Cube data", *, announce: bool = True
) -> html.Div:
    """Accessible wrapper around the calm six-face Cube loading mark."""
    accessibility = {"role": "status"} if announce else {"aria-hidden": "true"}
    return html.Div(
        [
            _cube_mark("cube-motion--loader"),
            html.Span(label, className="sr-only"),
        ],
        className="cube-risk-loader",
        **accessibility,
    )


def _build_theme_toggle() -> html.Button:
    """Return the theme button shared by the loading shell and full page."""
    return html.Button(
        "",
        id="theme-toggle",
        n_clicks=0,
        className="theme-toggle",
        title="Switch to dark mode",
        type="button",
        **{"aria-label": "Switch to dark mode", "aria-pressed": "false"},
    )


def build_operating_date_content(
    snapshot: ControlSnapshotProtocol | RefreshSnapshotProtocol | None,
) -> list[html.Div]:
    """Return the prominent committed Market/Risk date cards."""
    if snapshot is None:
        market_date = "Loading…"
        market_status = "Cold start"
        grouped_risk_dates: list[tuple[str, list[str]]] = []
    else:
        market_date = pd.Timestamp(snapshot.market_date).date().isoformat()
        market_status = str(snapshot.market_status)
        grouped: dict[str, list[str]] = {}
        for source_type, value in sorted(snapshot.risk_dates.items()):
            date_value = pd.Timestamp(value).date().isoformat()
            grouped.setdefault(date_value, []).append(str(source_type))
        grouped_risk_dates = sorted(grouped.items(), reverse=True)

    risk_values = (
        [
            html.Span(
                [
                    html.Strong(date_value, className="operating-date-value"),
                    html.Small(
                        f"{len(source_types)} source"
                        + ("s" if len(source_types) != 1 else ""),
                        className="operating-date-scope",
                    ),
                ],
                className="operating-risk-date",
                title=", ".join(source_types),
            )
            for date_value, source_types in grouped_risk_dates
        ]
        if grouped_risk_dates
        else [
            html.Strong(
                "Loading…",
                className="operating-date-value",
            )
        ]
    )
    return [
        html.Div(
            [
                html.Span("MARKET DATE", className="operating-date-label"),
                html.Strong(market_date, className="operating-date-value"),
                html.Small(market_status, className="operating-date-scope"),
            ],
            className="operating-date-card operating-market-date",
        ),
        html.Div(
            [
                html.Span("RISK DATES", className="operating-date-label"),
                html.Div(risk_values, className="operating-risk-date-values"),
            ],
            className="operating-date-card",
        ),
    ]


def _build_refresh_controls(
    initial_snapshot: ControlSnapshotProtocol | RefreshSnapshotProtocol | None,
    *,
    refresh_enabled: bool,
    initial_loading: bool = False,
    initial_error: bool = False,
    id_prefix: str = "",
) -> html.Div:
    """Build the stable dashboard control strip for startup and operation."""
    theme_toggle = _build_theme_toggle()
    if not refresh_enabled:
        return html.Div(
            html.Div(
                theme_toggle,
                className="refresh-control-actions",
                **{"aria-label": "Display controls"},
            ),
            className="refresh-controls",
        )

    # The first load is deliberately quiet.  Before revision 1 exists none of
    # the operational actions can do useful work, and mounting a strip full of
    # disabled controls made cold start look busier (and more broken) than it
    # is.  Keep only the stable status target used by the startup follower and
    # the browser-local display control. Callback output targets remain mounted
    # in one hidden group: Dash resolves outputs against the live layout, so
    # removing them during this transient shell produces browser-side
    # "nonexistent object" errors before the full strip is installed.
    if initial_snapshot is None:
        if initial_error:
            status_text = "Initial data load failed"
            status_class = "refresh-status is-error"
        elif initial_loading:
            status_text = "Opening Cube"
            status_class = "refresh-status is-refreshing"
        else:
            status_text = "Open Risk to load Cube"
            status_class = "refresh-status"
        return html.Div(
            [
                html.Div(
                    theme_toggle,
                    className="refresh-control-actions",
                    **{"aria-label": "Display controls"},
                ),
                html.Div(
                    status_text,
                    id=f"{id_prefix}refresh-status",
                    className=status_class,
                    **{"aria-live": "polite", "aria-atomic": "true"},
                ),
                html.Div(
                    [
                        html.Button(
                            id=f"{id_prefix}refresh-portfolios-button",
                            n_clicks=0,
                            disabled=True,
                        ),
                        html.Button(
                            id=f"{id_prefix}reload-risk-button",
                            n_clicks=0,
                            disabled=True,
                        ),
                        html.Button(
                            id=f"{id_prefix}refresh-pl-button",
                            n_clicks=0,
                            disabled=True,
                        ),
                        html.Button(
                            id=f"{id_prefix}commo-market-toggle",
                            n_clicks=0,
                            disabled=True,
                        ),
                        html.Button(
                            id=f"{id_prefix}risk-checker-toggle",
                            n_clicks=0,
                            disabled=True,
                        ),
                        html.Button(
                            id=f"{id_prefix}auto-refresh-toggle",
                            n_clicks=0,
                            disabled=True,
                        ),
                        html.Button(
                            id=f"{id_prefix}clear-cache-button",
                            n_clicks=0,
                            disabled=True,
                        ),
                        html.Span(id=f"{id_prefix}data-settings-status"),
                        html.Span(id=f"{id_prefix}auto-refresh-status"),
                        html.Div(id=f"{id_prefix}operating-date-banner"),
                    ],
                    className="cold-refresh-callback-targets",
                    hidden=True,
                ),
            ],
            className=(
                "refresh-controls is-initial-loading"
                if initial_loading
                else "refresh-controls"
            ),
        )

    controls_disabled = False
    commodity_enabled = bool(
        initial_snapshot.commodity_market_enabled
        if initial_snapshot is not None
        else False
    )
    checker_enabled = bool(
        initial_snapshot.risk_checker_enabled if initial_snapshot is not None else True
    )
    last_auto_text = ""
    if (
        initial_snapshot is not None
        and str(getattr(initial_snapshot, "refresh_reason", ""))
        == "automatic 15-minute refresh"
    ):
        last_auto_text = (
            " · Last automatic run "
            + initial_snapshot.refreshed_at.strftime("%H:%M:%S UTC")
        )
    if initial_snapshot is not None:
        refreshed_at = initial_snapshot.refreshed_at.strftime("%H:%M:%S UTC")
        status_text = (
            f"Last success {refreshed_at} · "
            f"T-1 risk {int(((initial_snapshot.risk_status['Age'] == 0) & ~initial_snapshot.risk_status['Force Risk'].astype(bool)).sum())} · "
            f"Forced risk {int((initial_snapshot.risk_status['Force Risk'].astype(bool)).sum())}"
        )
        status_class = "refresh-status"
    elif initial_error:
        status_text = "Initial data load failed · no snapshot was published"
        status_class = "refresh-status is-error"
    elif initial_loading:
        status_text = "Opening Cube · loading the first validated snapshot"
        status_class = "refresh-status is-refreshing"
    else:
        status_text = "Open Risk to load the first validated snapshot"
        status_class = "refresh-status"

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.Button(
                                "Refresh Portfolios",
                                id=f"{id_prefix}refresh-portfolios-button",
                                n_clicks=0,
                                disabled=controls_disabled,
                                className="refresh-portfolios-button",
                                title="Reload the portfolio mapping only",
                                type="button",
                            ),
                            html.Button(
                                "Refresh Risk",
                                id=f"{id_prefix}reload-risk-button",
                                n_clicks=0,
                                disabled=controls_disabled,
                                className="reload-risk-button",
                                title="Refresh Risk (Shift+F8)",
                                type="button",
                                **{"aria-keyshortcuts": "Shift+F8"},
                            ),
                            html.Button(
                                "Refresh PL",
                                id=f"{id_prefix}refresh-pl-button",
                                n_clicks=0,
                                disabled=controls_disabled,
                                className="refresh-pl-button",
                                title="Refresh PL (Shift+F9)",
                                type="button",
                                **{"aria-keyshortcuts": "Shift+F9"},
                            ),
                            html.Button(
                                (
                                    "Commodity quotes: Loaded"
                                    if commodity_enabled
                                    else "Commodity quotes: Disabled"
                                ),
                                id=f"{id_prefix}commo-market-toggle",
                                n_clicks=0,
                                disabled=controls_disabled,
                                className=(
                                    "data-source-toggle is-on"
                                    if commodity_enabled
                                    else "data-source-toggle is-off"
                                ),
                                title=(
                                    "Commodity quote connectors are loaded"
                                    if commodity_enabled
                                    else "Commodity Risk remains visible; its quotes are disabled"
                                ),
                                type="button",
                                **{"aria-pressed": str(commodity_enabled).lower()},
                            ),
                            html.Button(
                                (
                                    "Risk dates: Checker"
                                    if checker_enabled
                                    else "Risk dates: Today"
                                ),
                                id=f"{id_prefix}risk-checker-toggle",
                                n_clicks=0,
                                disabled=controls_disabled,
                                className=(
                                    "data-source-toggle is-on"
                                    if checker_enabled
                                    else "data-source-toggle is-off"
                                ),
                                title=(
                                    "Risk dates follow RiskChecker readiness"
                                    if checker_enabled
                                    else "RiskChecker is bypassed and every product uses the checker date"
                                ),
                                type="button",
                                **{"aria-pressed": str(checker_enabled).lower()},
                            ),
                            html.Button(
                                "Auto P&L: On · 15 min",
                                id=f"{id_prefix}auto-refresh-toggle",
                                n_clicks=0,
                                disabled=controls_disabled,
                                className="data-source-toggle auto-refresh-toggle is-on",
                                title="Refresh P&L every 15 minutes while this browser is open.",
                                type="button",
                                **{
                                    "aria-label": "Automatic P&L refresh is On",
                                    "aria-pressed": "true",
                                },
                            ),
                            html.Span(
                                "",
                                id=f"{id_prefix}data-settings-status",
                                className="data-settings-status",
                                role="status",
                                **{"aria-live": "polite"},
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Clear Cache",
                                        id=f"{id_prefix}clear-cache-button",
                                        n_clicks=0,
                                        disabled=controls_disabled,
                                        className=(
                                            "refresh-pl-button clear-cache-button"
                                        ),
                                        title=(
                                            "Ready · Clear cached views and reload Risk and P&L"
                                        ),
                                        type="button",
                                    ),
                                    theme_toggle,
                                ],
                                className="header-utility-pair",
                                **{"aria-label": "Cache and display controls"},
                            ),
                        ],
                        className="refresh-control-actions",
                        role="group",
                        **{"aria-label": "Dashboard controls"},
                    ),
                    html.Div(
                        build_operating_date_content(initial_snapshot),
                        id=f"{id_prefix}operating-date-banner",
                        className="operating-date-banner",
                        **{"aria-label": "Committed market and risk dates"},
                    ),
                ],
                className="refresh-control-topline",
            ),
            html.Div(
                (
                    "Automatic P&L runs within 15 minutes while this browser is open"
                    + last_auto_text
                ),
                id=f"{id_prefix}auto-refresh-status",
                className="auto-refresh-status",
                role="status",
            ),
            html.Div(
                status_text,
                id=f"{id_prefix}refresh-status",
                className=status_class,
                **{"aria-live": "polite", "aria-atomic": "true"},
            ),
        ],
        className=(
            "refresh-controls is-initial-loading"
            if initial_loading
            else "refresh-controls"
        ),
    )


def _build_refresh_progress(
    stage_delays: Mapping[str, float] | None,
    *,
    initial_loading: bool = False,
    initial_error: bool = False,
) -> html.Div:
    """Build the shared progress hero without performing any source work."""
    stage_delay_values = dict(stage_delays or {})
    visible = initial_loading or initial_error
    if initial_error:
        title = "Initial data load failed"
        product = "No financial snapshot was published"
        function_name = "Use Retry after checking the connector error"
        class_name = "refresh-progress is-error"
    elif initial_loading:
        title = "Loading Cube data"
        product = "Preparing the first validated snapshot"
        function_name = "Waiting for the server-started refresh"
        class_name = "refresh-progress is-running"
    else:
        title = "Refresh pipeline"
        product = "Preparing product queue"
        function_name = "Waiting for refresh request"
        class_name = "refresh-progress"

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            build_cube_loader("Refreshing Cube data", announce=False),
                            html.Span(
                                title,
                                id="refresh-progress-title",
                                className="refresh-progress-title",
                            ),
                        ],
                        className="refresh-progress-title-wrap",
                    ),
                    html.Span(
                        "",
                        id="refresh-progress-elapsed",
                        className="refresh-progress-elapsed",
                        **{"aria-hidden": "true"},
                    ),
                ],
                className="refresh-progress-header",
            ),
            html.Div(
                [
                    html.Strong(
                        product,
                        id="refresh-progress-product",
                        className="refresh-product-name",
                    ),
                    html.Span("Active call", className="refresh-function-label"),
                    html.Code(
                        function_name,
                        id="refresh-progress-function",
                        className="refresh-function-name",
                    ),
                    html.Span(
                        "",
                        id="refresh-progress-source",
                        className="refresh-function-source",
                    ),
                    html.Span(
                        "",
                        id="refresh-progress-count",
                        className="refresh-function-count",
                    ),
                    html.Span(
                        "",
                        id="refresh-progress-hold",
                        className="refresh-function-hold",
                    ),
                    html.Span(
                        html.Span(
                            id="refresh-progress-bar",
                            className="refresh-progress-bar-fill",
                        ),
                        id="refresh-progress-bar-track",
                        className="refresh-progress-bar-track",
                    ),
                ],
                className="refresh-function-live refresh-product-card",
                role="status",
                **{"aria-live": "polite", "aria-atomic": "true"},
            ),
            (
                None
                if initial_loading or initial_error
                else html.P(
                    "The current committed snapshot stays usable while a staged refresh runs; refresh controls are locked until it finishes.",
                    className="refresh-progress-note",
                )
            ),
            html.Ol(
                [
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Load RiskChecker readiness",
                                className="refresh-stage-function",
                            ),
                            html.Span(className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-readiness",
                        className="refresh-stage",
                    ),
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Risk & @risk product calls (if dates changed)",
                                className="refresh-stage-function",
                            ),
                            html.Span(className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-risk",
                        className="refresh-stage",
                    ),
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Open + Current market",
                                className="refresh-stage-function",
                            ),
                            html.Span(className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-market",
                        className="refresh-stage",
                    ),
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Calculate product P&L",
                                className="refresh-stage-function",
                            ),
                            html.Span(className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-pl",
                        className="refresh-stage",
                    ),
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Validate + publish snapshot",
                                className="refresh-stage-function",
                            ),
                            html.Span("Finalising", className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-final",
                        className="refresh-stage",
                    ),
                ],
                className="refresh-stage-list",
            ),
        ],
        id="refresh-progress",
        className=class_name,
        hidden=not visible,
        **{
            "data-risk-product-delay": str(
                0.0
                if initial_loading or initial_error
                else stage_delay_values.get("risk_product", 0.0)
            ),
            "data-initial-load": "true" if visible else "false",
        },
    )


def build_shared_refresh_shell(
    initial_snapshot: ControlSnapshotProtocol | RefreshSnapshotProtocol | None,
    *,
    refresh_enabled: bool,
    stage_delays: Mapping[str, float] | None = None,
    initial_loading: bool = False,
    initial_error: str | None = None,
    keep_polling: bool = False,
    data_revision: int | None = None,
    reset_generation: int = 0,
    style: Mapping[str, str] | None = None,
) -> html.Div:
    """Build the one persistent refresh lifecycle mounted above Dash Pages."""
    # The router initially hides this persistent shell and reveals it after
    # resolving the active page. Keep the cold-start follower alive while
    # hidden so direct visits to Data, Stock, or Statics can receive revision 1.
    bootstrap_polling = initial_loading or keep_polling
    applied_forced_dates = (
        {
            str(source): pd.Timestamp(value).date().isoformat()
            for source, value in initial_snapshot.forced_dates.items()
        }
        if initial_snapshot is not None
        else {}
    )
    applied_view_date = (
        pd.Timestamp(initial_snapshot.forced_view_date).date().isoformat()
        if initial_snapshot is not None
        and initial_snapshot.forced_view_date is not None
        else None
    )
    applied_commodity_market = bool(
        initial_snapshot.commodity_market_enabled
        if initial_snapshot is not None
        else False
    )
    applied_risk_checker = bool(
        initial_snapshot.risk_checker_enabled if initial_snapshot is not None else True
    )
    revision = initial_snapshot.revision if initial_snapshot is not None else 0
    rendered_revision = (
        revision if data_revision is None else max(0, int(data_revision))
    )
    rendered_reset_generation = max(0, int(reset_generation))
    error = str(initial_error or "")

    return html.Div(
        [
            dcc.Store(id="data-revision-store", data=rendered_revision),
            dcc.Store(id="reset-generation-store", data=rendered_reset_generation),
            dcc.Store(id="clear-cache-complete-store", data=rendered_reset_generation),
            html.Span(revision, id="refresh-commit-revision", hidden=True),
            # Backend-affecting settings mirror the one process-wide committed
            # snapshot. AutoPL alone is browser-local scheduling state.
            dcc.Store(
                id="perspective-risk-cube-forced-risk-v1",
                data=applied_forced_dates,
            ),
            dcc.Store(
                id="perspective-risk-cube-view-date-v1",
                data=applied_view_date,
            ),
            dcc.Store(
                id="perspective-risk-cube-auto-refresh-v1",
                data=True,
                storage_type="local",
            ),
            dcc.Store(
                id="perspective-risk-cube-commodity-market-v1",
                data=applied_commodity_market,
            ),
            dcc.Store(
                id="perspective-risk-cube-risk-checker-v1",
                data=applied_risk_checker,
            ),
            dcc.Store(id="force-risk-draft-store", data={}),
            dcc.Store(id="force-risk-render-store", data={}),
            dcc.Store(id="refresh-result-store", data=0),
            dcc.Store(id="refresh-busy-store", data=False),
            dcc.Interval(
                id="auto-refresh-interval",
                interval=15 * 60_000,
                n_intervals=0,
                disabled=True,
            ),
            # Once Risk starts revision 1 this common poll survives navigation,
            # allowing the shell to receive the terminal snapshot even if the
            # cold page and its own interval unmount.
            dcc.Interval(
                id="shared-refresh-bootstrap-interval",
                interval=500,
                n_intervals=0,
                disabled=not bootstrap_polling,
            ),
            html.Section(
                _build_refresh_controls(
                    initial_snapshot,
                    refresh_enabled=refresh_enabled,
                    initial_loading=initial_loading,
                    initial_error=bool(error),
                ),
                id="refresh-control-strip",
                className="cube-refresh-strip",
                **{"aria-label": "Dashboard controls"},
            ),
            (
                _build_refresh_progress(
                    stage_delays,
                    initial_loading=initial_loading,
                    initial_error=bool(error),
                )
                if refresh_enabled
                else None
            ),
            html.Div(
                error,
                id="error-log",
                className="error-log has-errors" if error else "error-log",
                **{"aria-live": "polite"},
            ),
        ],
        id="shared-refresh-shell",
        style=dict(style) if style is not None else None,
    )


def build_initial_load_layout(
    *,
    stage_delays: Mapping[str, float] | None = None,
    error: str | None = None,
    retry_enabled: bool = True,
    keep_polling: bool = False,
    include_shared_refresh_shell: bool = True,
) -> html.Div:
    """Render the usable app shell before the first connector call begins."""
    loading = error is None
    return html.Div(
        [
            (
                build_shared_refresh_shell(
                    None,
                    refresh_enabled=True,
                    stage_delays=stage_delays,
                    initial_loading=loading,
                    initial_error=error,
                    keep_polling=keep_polling,
                )
                if include_shared_refresh_shell
                else None
            ),
            dcc.Interval(
                id="initial-load-trigger",
                interval=500,
                n_intervals=0,
                # Keep polling while another browser owns the first writer.
                # Replacing this shell with the full layout removes it.
                max_intervals=-1,
                # A failed transaction waits for Retry. A watchdog warning can
                # keep polling the same owned writer without starting another.
                disabled=error is not None and not keep_polling,
            ),
            html.H1("Cube Risk & PL", className="sr-only"),
            html.Div(
                [
                    html.P(
                        error or "Cube is preparing its first validated snapshot.",
                        id="initial-load-message",
                        className="initial-load-message",
                    ),
                    html.Button(
                        "Retry initial load",
                        id="initial-load-retry",
                        n_clicks=0,
                        hidden=error is None,
                        disabled=error is None or not retry_enabled,
                        className="reload-risk-button initial-load-retry",
                        type="button",
                    ),
                ],
                className="initial-load-actions",
                hidden=error is None,
            ),
        ],
        className="app-shell cube-app-shell cube-initial-load-shell",
    )


__all__ = [
    "build_aggregate_pl_table",
    "build_cube_loader",
    "build_initial_load_layout",
    "build_operating_date_content",
    "build_shared_refresh_shell",
]
