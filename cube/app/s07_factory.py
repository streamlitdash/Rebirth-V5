"""Dash application factory and HTTP boundary configuration."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any, Mapping

import pandas as pd
from dash import (
    Dash,
    Input,
    Output,
    dcc,
    html,
    page_container,
)
from flask import jsonify, request

from cube.history import ArchiveHistoryRepository
from cube.domain.s11_tenorreduction import CatalogSource, MatrixProviderLike
from cube.services.s04_savedviews import SavedFilterViewRepository

from cube.pages import PAGE_SERVICES_CONFIG_KEY
from cube.pages.data import (
    build_data_page,
    register_callbacks as register_data_callbacks,
)
from cube.pages.pnl import (
    PL_FILTER_NOTE,
    PL_SAVED_VIEW_CONTROLS,
    PLSendConfig,
    build_pl_filter_bar,
    build_pl_page,
    register_callbacks as register_pnl_callbacks,
)
from cube.pages.risk.s17_callbacks import register_callbacks
from cube.pages.risk.s01_common import RISK_SAVED_VIEW_CONTROLS
from cube.pages.risk.s04_handoff import (
    register_callbacks as register_history_handoff_callbacks,
)
from cube.pages.risk.s16_view import build_layout
from cube.pages.static_data import (
    register_callbacks as register_static_data_callbacks,
)
from cube.pages.stock import (
    build_stock_page_route,
    register_callbacks as register_stock_callbacks,
)

from cube.app.s05_progress import progress_payload
from cube.app.s06_routing import register_native_pages
from cube.app.s03_logging import attach_application_log_handler
from cube.app.s08_applogs import build_app_log_panel, register_app_log_callbacks

from cube.ui.s02_aggregation import prepare_risk_data
from cube.ui.s01_constants import FILTER_DIMENSION_FIELDS
from cube.app.s02_contracts import RefreshManagerProtocol
from cube.ui.s03_filters import (
    build_saved_filter_view_bar,
    register_saved_filter_view_callbacks,
)
from cube.ui.s04_components import (
    build_header_utilities,
    build_initial_load_layout,
    build_shared_refresh_shell,
)
from cube.app.s04_startup import (
    STARTUP_COORDINATOR_CONFIG_KEY,
    STARTUP_UI_ERROR_CONFIG_KEY,
    StartupCoordinator,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_app(
    data: pd.DataFrame | None = None,
    refresh_manager: RefreshManagerProtocol | None = None,
    *,
    pl_send_config: PLSendConfig | None = None,
    stock_source: Any | None = None,
    stock_portfolio_source: Any | None = None,
    stock_history_source: Any | None = None,
    saved_view_root: str | Path | None = None,
    pl_history_root: str | Path | None = None,
    reduced_tenor_catalog: CatalogSource | None = None,
    reduced_tenor_matrix_provider: MatrixProviderLike | None = None,
    dash_kwargs: Mapping[str, Any] | None = None,
) -> Dash:
    """Create the Dash app from static data or a server-side refresh manager."""
    if data is not None and refresh_manager is not None:
        raise ValueError("Pass either data or refresh_manager, not both")
    if data is None and refresh_manager is None:
        raise ValueError(
            "No real dashboard data source was supplied. Pass a validated DataFrame "
            "or a refresh manager backed by configured real connectors."
        )
    if pl_send_config is not None and refresh_manager is None:
        raise ValueError("PL send configuration requires a refresh manager")
    if (stock_source is None) != (stock_portfolio_source is None):
        raise ValueError(
            "Stock requires both stock_source and stock_portfolio_source, or neither"
        )
    if stock_history_source is not None and stock_source is None:
        raise ValueError("Stock history requires the Stock page sources")
    if (reduced_tenor_catalog is None) != (reduced_tenor_matrix_provider is None):
        raise ValueError(
            "Reduced tenor requires both its catalogue and matrix provider"
        )
    saved_view_repository = SavedFilterViewRepository(
        saved_view_root
        if saved_view_root is not None
        else PROJECT_ROOT / "data" / "saved_views",
        tuple(field.key for field in FILTER_DIMENSION_FIELDS),
    )
    resolved_pl_history_root = Path(
        pl_history_root
        if pl_history_root is not None
        else PROJECT_ROOT / "data" / "histo"
    )
    history_repository = ArchiveHistoryRepository(resolved_pl_history_root)
    # A manager-backed app must become reachable before it calls any source.
    # Reuse an already committed snapshot (for example in a warm worker), but
    # leave a cold manager untouched until the server has returned the loading
    # shell and scheduled the one process-wide startup writer.
    initial_snapshot = None
    if refresh_manager is not None and refresh_manager.health.revision > 0:
        initial_snapshot = refresh_manager.control_snapshot
        dashboard_read = refresh_manager.read_frame("dashboard_frame")
        if int(dashboard_read.revision) != int(initial_snapshot.revision):
            initial_snapshot = refresh_manager.control_snapshot
            dashboard_read = refresh_manager.read_frame("dashboard_frame")
        if int(dashboard_read.revision) != int(initial_snapshot.revision):
            raise RuntimeError("Committed dashboard and control revisions disagree")
        risk_data = prepare_risk_data(dashboard_read.frame)
    elif refresh_manager is not None:
        risk_data = pd.DataFrame()
    else:
        if data is None:
            raise RuntimeError("A static app requires a DataFrame")
        risk_data = prepare_risk_data(data)

    prepared_dashboard_lock = Lock()
    prepared_dashboard_revision = (
        int(initial_snapshot.revision) if initial_snapshot is not None else -1
    )
    prepared_dashboard_frame: pd.DataFrame | None = (
        risk_data if initial_snapshot is not None else None
    )

    dash_options = dict(dash_kwargs or {})
    # Only the active URL's page body is mounted. Page-specific callback
    # targets therefore enter and leave the layout as navigation occurs.
    dash_options["suppress_callback_exceptions"] = True
    dash_options["use_pages"] = True
    dash_options["pages_folder"] = ""
    app = Dash(
        __name__,
        assets_folder=str(PROJECT_ROOT / "assets"),
        **dash_options,
    )
    # Dash's logger owns the stdout stream shown by Plotly Preview. Dash resets
    # it to INFO during construction, so restore the configured runtime level
    # before routing connector records through it. Keep it from duplicating the
    # same record through the root stderr handler, and retain a bounded safe
    # operator-event copy for the in-app drawer.
    app.logger.setLevel(logging.getLogger().getEffectiveLevel())
    app.logger.propagate = False
    attach_application_log_handler(app.logger)
    app.title = "Cube"
    register_native_pages()
    app.server.config.setdefault(STARTUP_UI_ERROR_CONFIG_KEY, None)
    startup_coordinator: StartupCoordinator | None = None
    if refresh_manager is not None:
        raw_timeout = os.getenv("CUBE_STARTUP_TIMEOUT_SECONDS", "2400")
        try:
            startup_timeout = float(raw_timeout)
            if startup_timeout <= 0:
                raise ValueError
        except (TypeError, ValueError):
            app.logger.warning(
                "Invalid CUBE_STARTUP_TIMEOUT_SECONDS=%r; using 2400 seconds.",
                raw_timeout,
            )
            startup_timeout = 2400.0
        startup_coordinator = StartupCoordinator(
            refresh_manager,
            timeout_seconds=startup_timeout,
            logger=app.logger,
        )
    app.server.config[STARTUP_COORDINATOR_CONFIG_KEY] = startup_coordinator

    def schedule_cold_start() -> None:
        """Schedule one delayed writer after a cold financial page is requested."""
        if refresh_manager is None or startup_coordinator is None:
            return
        try:
            revision = int(refresh_manager.health.revision)
        except Exception:
            revision = 0
        if revision <= 0:
            startup_coordinator.schedule_start(delay_seconds=0.5)

    route_prefix = app.config.routes_pathname_prefix or "/"
    request_prefix = app.config.requests_pathname_prefix or route_prefix
    health_path = f"{route_prefix.rstrip('/')}/healthz" or "/healthz"
    progress_path = f"{route_prefix.rstrip('/')}/progressz" or "/progressz"
    start_path = f"{route_prefix.rstrip('/')}/startz" or "/startz"
    public_progress_path = f"{request_prefix.rstrip('/')}/progressz" or "/progressz"
    public_start_path = f"{request_prefix.rstrip('/')}/startz" or "/startz"

    @app.server.get(health_path)
    def health_check():
        health = refresh_manager.health if refresh_manager is not None else None
        progress = progress_payload(refresh_manager, startup_coordinator)
        startup_ui_error = app.server.config.get(STARTUP_UI_ERROR_CONFIG_KEY)
        startup_phase = progress.get("startup_phase")
        if health is not None and health.revision == 0:
            health_status = (
                "degraded"
                if progress["error"] or startup_phase in {"failed", "stalled"}
                else "starting"
            )
        elif startup_ui_error or (health is not None and health.active_error_count):
            health_status = "degraded"
        else:
            health_status = "ok"
        return jsonify(
            status=health_status,
            revision=health.revision if health is not None else 0,
            last_success=(
                health.refreshed_at.isoformat()
                if health is not None and health.refreshed_at is not None
                else None
            ),
            last_attempt=(
                health.last_attempt_at.isoformat()
                if health is not None and health.last_attempt_at is not None
                else progress["started_at"]
            ),
            active_error_count=(
                (
                    1
                    if health is not None and health.revision == 0 and progress["error"]
                    else health.active_error_count + int(bool(startup_ui_error))
                )
                if health is not None
                else 0
            ),
        )

    @app.server.get(progress_path)
    def refresh_progress():
        return jsonify(progress_payload(refresh_manager, startup_coordinator))

    @app.server.post(start_path)
    def start_initial_refresh():
        """Idempotently recover a cold worker after first paint or a pod restart."""
        started = False
        if startup_coordinator is not None:
            started = startup_coordinator.start()
        payload = progress_payload(refresh_manager, startup_coordinator)
        payload["start_requested"] = True
        payload["started_new_worker"] = started
        return jsonify(payload)

    @app.server.after_request
    def secure_dashboard_responses(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if (
            request.path in {health_path, progress_path, start_path}
            or request.path.endswith("_dash-layout")
            or request.path.endswith("_dash-update-component")
            or response.mimetype == "application/json"
        ):
            response.headers["Cache-Control"] = "no-store, private"
        return response

    stage_delays = refresh_manager.stage_delays if refresh_manager is not None else None
    cube_href = app.get_relative_path("/")
    data_href = app.get_relative_path("/data")
    pnl_href = app.get_relative_path("/pnl")
    stock_href = app.get_relative_path("/stock")
    static_data_href = app.get_relative_path("/static-data")

    def prepared_committed_dashboard(
        *,
        revision: int | None = None,
        frame: pd.DataFrame | None = None,
    ) -> pd.DataFrame | None:
        """Prepare the mapped dashboard at most once per committed revision."""

        nonlocal prepared_dashboard_frame, prepared_dashboard_revision
        if refresh_manager is None:
            return risk_data
        if frame is None:
            if revision is None:
                try:
                    requested_revision = int(refresh_manager.health.revision)
                except Exception:
                    requested_revision = -1
            else:
                requested_revision = int(revision)
            if requested_revision <= 0:
                return None
        elif revision is None:
            raise ValueError("revision is required when a dashboard frame is supplied")
        else:
            requested_revision = int(revision)

        # Keep the cache check, defensive manager read, and preparation behind
        # one lock. Concurrent callers for the same revision then share one
        # read/copy and one prepared frame.
        with prepared_dashboard_lock:
            if (
                prepared_dashboard_frame is not None
                and prepared_dashboard_revision == requested_revision
            ):
                return prepared_dashboard_frame
            if frame is None:
                dashboard_read = refresh_manager.read_frame("dashboard_frame")
                selected_revision = int(dashboard_read.revision)
                selected_frame = dashboard_read.frame
                if (
                    prepared_dashboard_frame is not None
                    and prepared_dashboard_revision == selected_revision
                ):
                    return prepared_dashboard_frame
            else:
                selected_revision = requested_revision
                selected_frame = frame
            prepared = (
                prepare_risk_data(selected_frame)
                if not selected_frame.empty
                else selected_frame.copy()
            )
            if selected_revision >= prepared_dashboard_revision:
                prepared_dashboard_revision = selected_revision
                prepared_dashboard_frame = prepared
                return prepared_dashboard_frame
            # An out-of-order caller must receive the frame it requested, not
            # a newer cached frame mislabeled with the older revision.
            return prepared

    def current_cube_page():
        """Serve the shell cold and the complete dashboard after revision 1."""
        if refresh_manager is not None:
            try:
                revision = int(refresh_manager.health.revision)
                if revision > 0:
                    # The first iteration normally succeeds. Retry once only
                    # when a new commit lands while this route is reading it.
                    for _attempt in range(2):
                        snapshot = refresh_manager.control_snapshot
                        expected_revision = int(snapshot.revision)
                        prepared = prepared_committed_dashboard(
                            revision=expected_revision
                        )
                        if expected_revision == int(refresh_manager.health.revision):
                            break
                    else:
                        raise RuntimeError(
                            "Committed dashboard and control revisions disagree"
                        )
                    if prepared is None:
                        raise RuntimeError("Committed dashboard frame is unavailable")
                    return build_layout(
                        prepared,
                        snapshot,
                        refresh_enabled=True,
                        stage_delays=stage_delays,
                        include_shared_refresh_shell=False,
                    )
            except Exception as error:
                app.logger.exception(
                    "Could not materialize the committed startup snapshot: %s",
                    type(error).__name__,
                )
                return build_initial_load_layout(
                    stage_delays=stage_delays,
                    include_shared_refresh_shell=False,
                    error=(
                        "The validated data loaded, but the dashboard could not be "
                        "rendered. Check the server log and retry."
                    ),
                )
            return build_initial_load_layout(
                stage_delays=stage_delays,
                include_shared_refresh_shell=False,
            )
        return build_layout(
            risk_data,
            initial_snapshot,
            refresh_enabled=False,
            stage_delays=stage_delays,
            include_shared_refresh_shell=False,
        )

    def cube_page_body() -> html.Main:
        """Mount the revision-aware Risk page and schedule one cold writer."""
        schedule_cold_start()
        return html.Main(current_cube_page(), id="cube-page-container")

    def current_shared_snapshot():
        """Return the compact committed view used by the shared page shell."""
        if refresh_manager is not None:
            try:
                if refresh_manager.health.revision > 0:
                    return refresh_manager.control_snapshot
            except Exception:
                return initial_snapshot
        return initial_snapshot

    def pnl_page_body():
        """Mount Aggregate P&L and the optional sender on the native P&L route."""
        schedule_cold_start()
        if refresh_manager is not None:
            initial_aggregate_frame = None
            try:
                start_initial_load = int(refresh_manager.health.revision) <= 0
                if not start_initial_load:
                    initial_aggregate_frame = prepared_committed_dashboard()
            except Exception:
                start_initial_load = True
                app.logger.exception(
                    "Could not pre-render committed Aggregate P&L on the P&L page"
                )
            return build_pl_page(
                start_initial_load=start_initial_load,
                send_workflow_available=pl_send_config is not None,
                initial_aggregate_frame=initial_aggregate_frame,
                saved_view_bar=build_saved_filter_view_bar(
                    PL_SAVED_VIEW_CONTROLS,
                    filter_note=PL_FILTER_NOTE,
                    filter_bar=build_pl_filter_bar(initial_aggregate_frame),
                ),
            )
        return html.Main(
            [
                html.H1("P&L Sender", className="page-title"),
                html.P(
                    "P&L sending is not configured for this application.",
                    id="pnl-unavailable",
                    className="static-data-empty",
                ),
            ],
            id="pnl-page",
            className="page-frame",
        )

    def stock_page_body():
        """Paint Stock immediately; its page-local callback owns source I/O."""
        if stock_source is None or stock_portfolio_source is None:
            return build_stock_page_route(None, available=False)

        snapshot = current_shared_snapshot()
        reference_date = (
            snapshot.market_date
            if snapshot is not None
            else pd.Timestamp.now().normalize()
        )
        return build_stock_page_route(
            reference_date,
            available=True,
            history_available=stock_history_source is not None,
        )

    def data_page_body():
        """Build the archive-free Data shell with prefix-correct links."""

        return build_data_page(
            cube_href=cube_href,
            pnl_href=pnl_href,
            stock_href=stock_href,
        )

    app.server.config[PAGE_SERVICES_CONFIG_KEY] = {
        "cube_href": cube_href,
        "risk_page_builder": cube_page_body,
        "data_page_builder": data_page_body,
        "pnl_page_builder": pnl_page_body,
        "stock_page_builder": stock_page_body,
    }

    def serve_layout():
        """Build a request-fresh router so reconnecting browsers recover cleanly."""
        shared_snapshot = current_shared_snapshot()
        shared_initial_loading = refresh_manager is not None and shared_snapshot is None
        return html.Div(
            [
                html.Div(
                    id="backend-endpoints",
                    hidden=True,
                    **{
                        "data-progress-url": public_progress_path,
                        "data-start-url": public_start_path,
                    },
                ),
                html.Header(
                    [
                        dcc.Link(
                            [
                                html.Span("Cube", className="cube-wordmark"),
                                html.Span("Risk & PL", className="cube-wordmark-note"),
                            ],
                            href=cube_href,
                            className="cube-brand",
                            title="Cube Risk and PL home",
                        ),
                        html.Div(
                            [
                                build_header_utilities(
                                    refresh_enabled=refresh_manager is not None,
                                    cache_enabled=shared_snapshot is not None,
                                ),
                                html.Nav(
                                    [
                                        dcc.Link(
                                            "Risk",
                                            href=cube_href,
                                            id="cube-nav-link",
                                            className=(
                                                "app-nav-link cube-nav-link is-active"
                                            ),
                                        ),
                                        dcc.Link(
                                            "Data",
                                            href=data_href,
                                            id="data-nav-link",
                                            className="app-nav-link cube-nav-link",
                                        ),
                                        dcc.Link(
                                            "Stock",
                                            href=stock_href,
                                            id="stock-nav-link",
                                            className="app-nav-link cube-nav-link",
                                        ),
                                        dcc.Link(
                                            "P&L",
                                            href=pnl_href,
                                            id="pnl-nav-link",
                                            className="app-nav-link cube-nav-link",
                                        ),
                                        dcc.Link(
                                            "Statics",
                                            href=static_data_href,
                                            refresh=True,
                                            id="static-data-nav-link",
                                            className="app-nav-link cube-nav-link",
                                        ),
                                    ],
                                    className="cube-nav",
                                    **{"aria-label": "Primary navigation"},
                                ),
                            ],
                            className="cube-header-actions",
                        ),
                    ],
                    className="cube-app-header",
                ),
                build_app_log_panel(),
                build_shared_refresh_shell(
                    shared_snapshot,
                    refresh_enabled=refresh_manager is not None,
                    stage_delays=stage_delays,
                    initial_loading=shared_initial_loading,
                    reset_generation=(
                        int(getattr(refresh_manager, "reset_generation", 0))
                        if refresh_manager is not None
                        else 0
                    ),
                    style={"display": "none"},
                    include_header_utilities=False,
                ),
                html.Div(
                    id="global-warning-summary",
                    className="global-warning-summary",
                    role="status",
                    **{"aria-live": "polite"},
                ),
                dcc.Location(id="data-route-location", refresh="callback-nav"),
                dcc.Store(
                    id="data-history-handoff-store",
                    storage_type="session",
                ),
                dcc.Store(
                    id="data-history-handoff-consumed-store",
                    storage_type="session",
                ),
                # The handoff callback is registered globally, so its request
                # output must exist before the Data page is mounted.
                dcc.Store(id="data-history-request-store", storage_type="memory"),
                page_container,
            ],
            className="app-router-shell",
        )

    app.layout = serve_layout

    @app.callback(
        Output("cube-nav-link", "className"),
        Output("data-nav-link", "className"),
        Output("pnl-nav-link", "className"),
        Output("stock-nav-link", "className"),
        Output("static-data-nav-link", "className"),
        Output("shared-refresh-shell", "style"),
        Input("_pages_location", "pathname"),
    )
    def update_navigation(pathname):
        """Reflect the native page route without taking ownership of content."""
        selected_path = app.strip_relative_path(pathname)
        cube_class = "app-nav-link cube-nav-link"
        data_class = "app-nav-link cube-nav-link"
        pnl_class = "app-nav-link cube-nav-link"
        stock_class = "app-nav-link cube-nav-link"
        static_class = "app-nav-link cube-nav-link"
        shared_shell_style = {"display": "none"}
        if selected_path == "":
            cube_class = f"{cube_class} is-active"
            shared_shell_style = {}
        elif selected_path == "data":
            data_class = f"{data_class} is-active"
            if refresh_manager is not None:
                shared_shell_style = {}
        elif selected_path == "pnl":
            pnl_class = f"{pnl_class} is-active"
            if refresh_manager is not None:
                shared_shell_style = {}
        elif selected_path == "stock":
            stock_class = f"{stock_class} is-active"
            if refresh_manager is not None:
                shared_shell_style = {}
        elif selected_path == "static-data":
            static_class = f"{static_class} is-active"
            if refresh_manager is not None:
                shared_shell_style = {}
        return (
            cube_class,
            data_class,
            pnl_class,
            stock_class,
            static_class,
            shared_shell_style,
        )

    @app.callback(
        Output("global-warning-summary", "children"),
        Output("global-warning-summary", "className"),
        Input("refresh-commit-revision", "children"),
    )
    def show_global_warnings(_revision):
        """Expose committed source warnings without blocking unaffected pages."""

        if refresh_manager is None:
            return "", "global-warning-summary"
        try:
            if int(refresh_manager.health.revision) <= 0:
                return "", "global-warning-summary"
            warnings = tuple(refresh_manager.control_snapshot.errors)
        except Exception:
            app.logger.exception("Could not read the committed warning summary")
            return (
                "Warning status is temporarily unavailable; the application remains usable.",
                "global-warning-summary has-warnings",
            )
        if not warnings:
            return "", "global-warning-summary"
        visible = warnings[:10]
        remainder = len(warnings) - len(visible)
        details = [html.Li(message) for message in visible]
        if remainder:
            details.append(
                html.Li(f"{remainder} additional warning(s) are in the log.")
            )
        return (
            html.Details(
                [
                    html.Summary(f"Loaded with {len(warnings)} data warning(s)"),
                    html.Ul(details),
                ],
                open=True,
            ),
            "global-warning-summary has-warnings",
        )

    register_callbacks(
        app,
        refresh_manager,
        initial_snapshot,
        risk_data,
        route_prefix=request_prefix,
        startup_coordinator=startup_coordinator,
        prepared_frame_loader=prepared_committed_dashboard,
        reduced_tenor_catalog=reduced_tenor_catalog,
        matrix_provider=reduced_tenor_matrix_provider,
    )
    register_history_handoff_callbacks(
        app,
        refresh_manager,
        data_href=data_href,
    )
    register_data_callbacks(app, history_repository)
    register_static_data_callbacks(app)
    if refresh_manager is not None:
        register_pnl_callbacks(
            app,
            refresh_manager,
            history_root=resolved_pl_history_root,
            config=pl_send_config,
            prepared_frame_loader=prepared_committed_dashboard,
            saved_view_controls=PL_SAVED_VIEW_CONTROLS,
        )
        register_saved_filter_view_callbacks(
            app,
            saved_view_repository,
            RISK_SAVED_VIEW_CONTROLS,
        )
        register_saved_filter_view_callbacks(
            app,
            saved_view_repository,
            PL_SAVED_VIEW_CONTROLS,
        )
    register_stock_callbacks(
        app,
        refresh_manager=refresh_manager,
        stock_source=stock_source,
        stock_portfolio_source=stock_portfolio_source,
        saved_view_repository=saved_view_repository,
        stock_history_source=stock_history_source,
    )
    register_app_log_callbacks(app)
    return app


__all__ = ["build_app"]
