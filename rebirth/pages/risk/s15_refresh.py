"""V4 Risk-page startup and refresh callback ownership."""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from dash import ALL, MATCH, Dash, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from rebirth.services.s01_snapshots import (
    RefreshInProgressError,
    StaleRefreshError,
    StaleResetGenerationError,
)
from rebirth.ui.s04_components import (
    build_initial_load_layout,
    build_operating_date_content,
    build_shared_refresh_shell,
)
from rebirth.app.s02_contracts import (
    RefreshManagerProtocol,
    RefreshSnapshotProtocol,
)
from rebirth.app.s04_startup import (
    STARTUP_UI_ERROR_CONFIG_KEY,
    StartupCoordinator,
    StartupStatus,
)

from .s02_state import (
    AUTO_REFRESH_STORE_ID,
    CLEAR_CACHE_COMPLETE_STORE_ID,
    COMMODITY_MARKET_STORE_ID,
    FORCE_DRAFT_STORE_ID,
    FORCE_RENDER_STORE_ID,
    FORCE_STORE_ID,
    REFRESH_RESULT_STORE_ID,
    RESET_GENERATION_STORE_ID,
    RISK_CHECKER_STORE_ID,
    VIEW_DATE_STORE_ID,
    ForceApplyResult,
    _next_counter,
    _refresh_status,
    _RiskDataCache,
    apply_force_dates,
    auto_refresh_enabled,
    cancel_force_dates,
    collect_forced_dates,
    commodity_market_enabled,
    draft_base_dates,
    draft_base_view_date,
    draft_forced_dates,
    draft_view_date,
    make_force_draft,
    normalize_forced_dates,
    normalize_view_date,
    persisted_force_dates,
    rebase_force_draft,
    risk_checker_enabled,
    snapshot_forced_dates,
    snapshot_forced_view_date,
)
from .s16_view import (
    build_layout,
    build_risk_checker_inventory,
    build_risk_date_editor,
)


def _auto_refresh_status(
    refresh_manager: RefreshManagerProtocol,
    enabled: bool,
) -> str:
    """Describe browser-local scheduling without claiming a server timer."""

    if not enabled:
        return "Automatic P&L paused · No automatic run is scheduled"
    message = "Next automatic P&L run: within 15 min while this browser is open"
    try:
        refreshed_at = refresh_manager.control_snapshot.refreshed_at
    except (AttributeError, RuntimeError):
        return message
    return f"{message} · Last committed refresh {refreshed_at:%H:%M:%S UTC}"


def register_refresh_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol | None,
    initial_snapshot: RefreshSnapshotProtocol | None,
    cache: _RiskDataCache,
    *,
    startup_coordinator: StartupCoordinator | None = None,
) -> None:
    """Register cold-start, refresh, settings, and date-control callbacks."""

    def materialize_initial_dashboard(
        snapshot: RefreshSnapshotProtocol,
    ) -> html.Div:
        """Build the full page or retain a safe, retryable startup shell."""
        try:
            prepared = cache.replace(snapshot)
            layout = build_layout(
                prepared,
                snapshot,
                refresh_enabled=True,
                stage_delays=refresh_manager.stage_delays,
                include_shared_refresh_shell=False,
            )
        except Exception as error:
            incident_id = uuid.uuid4().hex[:10]
            app.logger.error(
                "Cube startup UI preparation failed; incident=%s type=%s",
                incident_id,
                type(error).__name__,
                exc_info=True,
            )
            safe_error = (
                f"Dashboard preparation failed (incident {incident_id}). "
                "No dashboard was published; retry after checking the server log."
            )
            app.server.config[STARTUP_UI_ERROR_CONFIG_KEY] = safe_error
            return build_initial_load_layout(
                stage_delays=refresh_manager.stage_delays,
                error=safe_error,
                include_shared_refresh_shell=False,
            )
        app.server.config[STARTUP_UI_ERROR_CONFIG_KEY] = None
        return layout

    if refresh_manager is not None:
        coordinator = startup_coordinator or StartupCoordinator(
            refresh_manager,
            logger=app.logger,
        )

        def start_or_follow_initial_snapshot(
            triggered: Any,
            load_intervals: Any,
            retry_clicks: Any,
            pnl_intervals: Any = 0,
        ) -> StartupStatus:
            """Apply one idempotent startup signal and return its current state."""
            if triggered in {"initial-load-trigger", "pnl-initial-load-trigger"}:
                intervals = (
                    pnl_intervals
                    if triggered == "pnl-initial-load-trigger"
                    else load_intervals
                )
                if int(intervals or 0) <= 0:
                    raise PreventUpdate
                # n_intervals=1 is delivered only after the cold Risk page has
                # or the cold P&L page has painted. Static/Stock never own one.
                coordinator.start()
            elif triggered == "initial-load-retry":
                if int(retry_clicks or 0) <= 0:
                    raise PreventUpdate
                coordinator.start(retry=True)
            return coordinator.status()

        @app.callback(
            Output("cube-page-container", "children"),
            Input("initial-load-trigger", "n_intervals", allow_optional=True),
            Input("initial-load-retry", "n_clicks", allow_optional=True),
            State("initial-load-message", "children", allow_optional=True),
            prevent_initial_call=True,
        )
        def load_initial_snapshot_after_first_paint(
            load_intervals,
            retry_clicks,
            displayed_error="",
        ):
            """Hydrate only the cold Risk page; it may safely unmount mid-call."""
            startup = start_or_follow_initial_snapshot(
                ctx.triggered_id,
                load_intervals,
                retry_clicks,
            )
            if startup.phase == "succeeded" and refresh_manager.health.revision > 0:
                return materialize_initial_dashboard(refresh_manager.snapshot)
            if startup.phase == "failed":
                return build_initial_load_layout(
                    stage_delays=refresh_manager.stage_delays,
                    error=startup.error
                    or "Initial data load failed. Check the server log and retry.",
                    retry_enabled=startup.retryable,
                    include_shared_refresh_shell=False,
                )
            if startup.phase == "stalled":
                # Retain the page poll so a late connector return can still
                # publish. Never offer a second writer while this one is alive.
                if str(displayed_error or "") != str(startup.error or ""):
                    return build_initial_load_layout(
                        stage_delays=refresh_manager.stage_delays,
                        error=startup.error,
                        retry_enabled=False,
                        keep_polling=True,
                        include_shared_refresh_shell=False,
                    )
            if ctx.triggered_id == "initial-load-retry":
                return build_initial_load_layout(
                    stage_delays=refresh_manager.stage_delays,
                    include_shared_refresh_shell=False,
                )
            raise PreventUpdate

        @app.callback(
            Output("shared-refresh-shell", "children"),
            Input("initial-load-trigger", "n_intervals", allow_optional=True),
            Input("initial-load-retry", "n_clicks", allow_optional=True),
            Input("pnl-initial-load-trigger", "n_intervals", allow_optional=True),
            Input("shared-refresh-bootstrap-interval", "n_intervals"),
            State("refresh-status", "className", allow_optional=True),
            State("error-log", "children", allow_optional=True),
            State("refresh-commit-revision", "children", allow_optional=True),
            prevent_initial_call=True,
        )
        def hydrate_shared_refresh_shell(
            load_intervals,
            retry_clicks,
            pnl_intervals,
            _shared_intervals,
            status_class="",
            displayed_error="",
            displayed_revision=0,
        ):
            """Follow revision 1 independently of the mounted Dash page."""
            if (
                ctx.triggered_id == "shared-refresh-bootstrap-interval"
                and int(_shared_intervals or 0) <= 0
            ):
                raise PreventUpdate
            startup = start_or_follow_initial_snapshot(
                ctx.triggered_id,
                load_intervals,
                retry_clicks,
                pnl_intervals,
            )
            common_options = {
                "refresh_enabled": True,
                "stage_delays": refresh_manager.stage_delays,
                "reset_generation": int(
                    getattr(refresh_manager, "reset_generation", 0)
                ),
            }
            if startup.phase == "succeeded" and refresh_manager.health.revision > 0:
                try:
                    shell_revision = int(displayed_revision or 0)
                except (TypeError, ValueError):
                    shell_revision = 0
                if (
                    shell_revision >= refresh_manager.health.revision
                    and "is-refreshing" not in str(status_class or "").split()
                ):
                    raise PreventUpdate
                return build_shared_refresh_shell(
                    refresh_manager.snapshot,
                    # The committed marker may advance on any page, but the
                    # live revision Store is released only after a consuming
                    # financial page (warm Risk or P&L) mounts.
                    data_revision=shell_revision,
                    **common_options,
                ).children
            if startup.phase == "failed":
                error_text = startup.error or (
                    "Initial data load failed. Check the server log and retry."
                )
                if (
                    str(displayed_error or "") == str(error_text)
                    and "is-error" in str(status_class or "").split()
                ):
                    raise PreventUpdate
                return build_shared_refresh_shell(
                    None,
                    initial_error=error_text,
                    **common_options,
                ).children
            if startup.phase == "stalled":
                if str(displayed_error or "") != str(startup.error or ""):
                    return build_shared_refresh_shell(
                        None,
                        initial_error=startup.error,
                        keep_polling=True,
                        **common_options,
                    ).children
                raise PreventUpdate
            if ctx.triggered_id in {
                "initial-load-trigger",
                "pnl-initial-load-trigger",
            }:
                # The base shell carries cold hero markup but is hidden and
                # passive. A mounted financial page hands polling to the
                # persistent shell so navigation cannot strand the handoff.
                return build_shared_refresh_shell(
                    None,
                    initial_loading=True,
                    **common_options,
                ).children
            if "is-refreshing" not in str(status_class or "").split():
                return build_shared_refresh_shell(
                    None,
                    initial_loading=True,
                    **common_options,
                ).children
            raise PreventUpdate

        @app.callback(
            Output(AUTO_REFRESH_STORE_ID, "data"),
            Input("auto-refresh-toggle", "n_clicks"),
            State(AUTO_REFRESH_STORE_ID, "data"),
            prevent_initial_call=True,
        )
        def toggle_auto_refresh(n_clicks, stored_value):
            if not n_clicks:
                raise PreventUpdate
            return not auto_refresh_enabled(stored_value)

        @app.callback(
            Output("auto-refresh-interval", "disabled"),
            Output("auto-refresh-toggle", "children"),
            Output("auto-refresh-toggle", "title"),
            Output("auto-refresh-toggle", "aria-label"),
            Output("auto-refresh-toggle", "aria-pressed"),
            Output("auto-refresh-toggle", "className"),
            Output("auto-refresh-status", "children"),
            Input(AUTO_REFRESH_STORE_ID, "data"),
            Input(REFRESH_RESULT_STORE_ID, "data"),
        )
        def sync_auto_refresh(stored_value, _refresh_result=None):
            enabled = auto_refresh_enabled(stored_value)
            state = "On" if enabled else "Off"
            action = "Off" if enabled else "On"
            title = (
                f"Automatic 15-minute P&L refresh is {state}. "
                f"Activate to turn it {action}."
            )
            return (
                not enabled,
                f"Auto P&L: {state} · 15 min",
                title,
                f"Automatic P&L refresh is {state}",
                str(enabled).lower(),
                f"data-source-toggle auto-refresh-toggle {'is-on' if enabled else 'is-off'}",
                _auto_refresh_status(refresh_manager, enabled),
            )

        @app.callback(
            Output("commo-market-toggle", "children"),
            Output("commo-market-toggle", "title"),
            Output("commo-market-toggle", "aria-pressed"),
            Output("commo-market-toggle", "className"),
            Input(COMMODITY_MARKET_STORE_ID, "data"),
        )
        def sync_commodity_market(stored_value):
            enabled = commodity_market_enabled(stored_value)
            return (
                (
                    "Commodity quotes: Loaded"
                    if enabled
                    else "Commodity quotes: Disabled"
                ),
                (
                    "Commodity quote connectors are loaded."
                    if enabled
                    else "Commodity Risk remains visible; its quotes are disabled."
                ),
                str(enabled).lower(),
                f"data-source-toggle {'is-on' if enabled else 'is-off'}",
            )

        # Promotion toggle callbacks
        @app.callback(
            Output("promotion-toggle-store", "data"),
            Input("promotion-toggle", "n_clicks"),
            State("promotion-toggle-store", "data"),
            prevent_initial_call=True,
        )
        def toggle_promotion(n_clicks, stored_value):
            if not n_clicks:
                raise PreventUpdate
            return not bool(stored_value)

        @app.callback(
            Output("promotion-toggle", "disabled"),
            Output("promotion-toggle", "children"),
            Output("promotion-toggle", "title"),
            Output("promotion-toggle", "aria-pressed"),
            Output("promotion-toggle", "className"),
            Input("promotion-toggle-store", "data"),
        )
        def sync_promotion(stored_value):
            enabled = bool(stored_value)
            state = "On" if enabled else "Off"
            action = "Off" if enabled else "On"
            return (
                False,
                f"Promotion: {state}",
                f"Underlying promotion is {state}. Click to turn it {action} (show group immediately).",
                str(enabled).lower(),
                f"data-source-toggle promotion-toggle {'is-on' if enabled else 'is-off'}",
            )

        # Region toggle callbacks
        @app.callback(
            Output("region-toggle-store", "data"),
            Input("region-toggle", "n_clicks"),
            State("region-toggle-store", "data"),
            prevent_initial_call=True,
        )
        def toggle_region(n_clicks, stored_value):
            if not n_clicks:
                raise PreventUpdate
            return not bool(stored_value)

        @app.callback(
            Output("region-toggle", "disabled"),
            Output("region-toggle", "children"),
            Output("region-toggle", "title"),
            Output("region-toggle", "aria-pressed"),
            Output("region-toggle", "className"),
            Input("region-toggle-store", "data"),
        )
        def sync_region(stored_value):
            enabled = bool(stored_value)
            state = "On" if enabled else "Off"
            action = "Off" if enabled else "On"
            return (
                False,
                f"Region: {state}",
                f"Region is {state}. Click to {action}.",
                str(enabled).lower(),
                f"data-source-toggle region-toggle {'is-on' if enabled else 'is-off'}",
            )

        @app.callback(
            Output("risk-checker-toggle", "children"),
            Output("risk-checker-toggle", "title"),
            Output("risk-checker-toggle", "aria-pressed"),
            Output("risk-checker-toggle", "className"),
            Input(RISK_CHECKER_STORE_ID, "data"),
        )
        def sync_risk_checker(stored_value):
            enabled = risk_checker_enabled(stored_value)
            return (
                "Risk dates: Checker" if enabled else "Risk dates: Today",
                (
                    "Risk dates follow RiskChecker readiness."
                    if enabled
                    else "RiskChecker is bypassed; every product uses the checker date."
                ),
                str(enabled).lower(),
                f"data-source-toggle {'is-on' if enabled else 'is-off'}",
            )

        @app.callback(
            Output("data-settings-status", "children"),
            Input(COMMODITY_MARKET_STORE_ID, "data"),
            Input(RISK_CHECKER_STORE_ID, "data"),
        )
        def sync_data_settings_status(commodity_value, checker_value):
            commodity = (
                "loaded" if commodity_market_enabled(commodity_value) else "disabled"
            )
            dates = "RiskChecker" if risk_checker_enabled(checker_value) else "Today"
            return f"Committed · Commodity quotes {commodity} · Risk dates {dates}"

        @app.callback(
            # Keep the long financial request outside the live-data callback
            # graph. Browser progress publishes the committed revision only
            # after the manager's atomic transaction finishes, so readers can
            # continue interacting with the previous immutable snapshot.
            Output("refresh-commit-revision", "children"),
            Output(REFRESH_RESULT_STORE_ID, "data"),
            Output("refresh-status", "children"),
            Output("error-log", "children"),
            Output("error-log", "className"),
            Output(FORCE_STORE_ID, "data"),
            Output(VIEW_DATE_STORE_ID, "data"),
            Output(RESET_GENERATION_STORE_ID, "data"),
            Output(CLEAR_CACHE_COMPLETE_STORE_ID, "data"),
            Input("auto-refresh-interval", "n_intervals"),
            Input("refresh-portfolios-button", "n_clicks"),
            Input("refresh-pl-button", "n_clicks"),
            Input("reload-risk-button", "n_clicks"),
            Input("force-risk-apply-button", "n_clicks", allow_optional=True),
            Input("clear-cache-button", "n_clicks"),
            Input("commo-market-toggle", "n_clicks"),
            Input("risk-checker-toggle", "n_clicks"),
            State(FORCE_DRAFT_STORE_ID, "data"),
            State(AUTO_REFRESH_STORE_ID, "data"),
            State(REFRESH_RESULT_STORE_ID, "data"),
            State(RESET_GENERATION_STORE_ID, "data"),
            running=[
                (Output("refresh-portfolios-button", "disabled"), True, False),
                (Output("refresh-pl-button", "disabled"), True, False),
                (Output("reload-risk-button", "disabled"), True, False),
                (Output("clear-cache-button", "disabled"), True, False),
                (Output("auto-refresh-toggle", "disabled"), True, False),
                (Output("commo-market-toggle", "disabled"), True, False),
                (Output("risk-checker-toggle", "disabled"), True, False),
                (Output("refresh-busy-store", "data"), True, False),
                (
                    Output("refresh-status", "className"),
                    "refresh-status is-refreshing",
                    "refresh-status",
                ),
            ],
            prevent_initial_call=True,
        )
        def refresh_pipeline(
            _auto_intervals,
            _portfolio_clicks,
            _pl_clicks,
            _risk_clicks,
            _apply_clicks,
            _clear_clicks,
            _commodity_clicks,
            _checker_clicks,
            draft_state,
            auto_refresh_state,
            refresh_result_counter,
            reset_generation_state,
        ):
            triggered_ids = {
                value
                for value in ctx.triggered_prop_ids.values()
                if isinstance(value, str)
            }
            triggered = ctx.triggered_id
            if isinstance(triggered, str):
                triggered_ids.add(triggered)
            click_counts = {
                "refresh-portfolios-button": _portfolio_clicks,
                "refresh-pl-button": _pl_clicks,
                "reload-risk-button": _risk_clicks,
                "force-risk-apply-button": _apply_clicks,
                "clear-cache-button": _clear_clicks,
                "commo-market-toggle": _commodity_clicks,
                "risk-checker-toggle": _checker_clicks,
            }
            triggered_ids = {
                component_id
                for component_id in triggered_ids
                if component_id not in click_counts
                or int(click_counts[component_id] or 0) > 0
            }

            current_snapshot = refresh_manager.control_snapshot
            current_applied = snapshot_forced_dates(current_snapshot)
            current_view_date = snapshot_forced_view_date(current_snapshot)
            current_revision = current_snapshot.revision
            committed_commodity = bool(current_snapshot.commodity_market_enabled)
            committed_checker = bool(current_snapshot.risk_checker_enabled)
            commodity_enabled = (
                not committed_commodity
                if "commo-market-toggle" in triggered_ids
                else committed_commodity
            )
            checker_enabled = (
                not committed_checker
                if "risk-checker-toggle" in triggered_ids
                else committed_checker
            )
            applying = "force-risk-apply-button" in triggered_ids
            clearing = "clear-cache-button" in triggered_ids
            browser_reset_generation = int(reset_generation_state or 0)
            apply_result: ForceApplyResult | None = None
            completed_reset_generation: int | None = None

            try:
                if applying:
                    requested = draft_forced_dates(
                        draft_state, fallback=current_applied
                    )
                    base = draft_base_dates(draft_state, fallback=current_applied)
                    requested_view = draft_view_date(
                        draft_state, fallback=current_view_date
                    )
                    base_view = draft_base_view_date(
                        draft_state, fallback=current_view_date
                    )
                    if (base != current_applied or base_view != current_view_date) and (
                        requested != current_applied
                        or requested_view != current_view_date
                    ):
                        return (
                            no_update,
                            no_update,
                            no_update,
                            "⚠ Applied force dates changed while you were editing. Cancel to reload them before applying.",
                            "error-log has-errors",
                            no_update,
                            no_update,
                            no_update,
                            no_update,
                        )
                    if (
                        requested == current_applied
                        and requested_view == current_view_date
                    ):
                        raise PreventUpdate
                    apply_result = apply_force_dates(
                        refresh_manager,
                        requested,
                        view_date=requested_view,
                        commodity_market=commodity_enabled,
                        risk_checker=checker_enabled,
                        expected_revision=int(
                            draft_state.get("base_revision", current_revision)
                            if isinstance(draft_state, Mapping)
                            else current_revision
                        ),
                        expected_reset_generation=browser_reset_generation,
                    )
                    snapshot = apply_result.snapshot
                elif clearing:
                    completed_reset_generation, snapshot = (
                        refresh_manager.reset_refresh(
                            expected_reset_generation=browser_reset_generation
                        )
                    )
                    cache.clear_reconstructable()
                elif "refresh-portfolios-button" in triggered_ids:
                    snapshot = refresh_manager.refresh_portfolios(
                        reason="portfolio mapping",
                        expected_revision=current_revision,
                        expected_reset_generation=browser_reset_generation,
                    )
                elif "reload-risk-button" in triggered_ids:
                    snapshot = refresh_manager.refresh(
                        force_risk=True,
                        forced_dates=current_applied,
                        view_date=current_view_date,
                        commodity_market_enabled=commodity_enabled,
                        risk_checker_enabled=checker_enabled,
                        reason="reload all risk",
                        expected_revision=current_revision,
                        expected_reset_generation=browser_reset_generation,
                    )
                elif "refresh-pl-button" in triggered_ids:
                    snapshot = refresh_manager.refresh(
                        force_pl=True,
                        forced_dates=current_applied,
                        view_date=current_view_date,
                        commodity_market_enabled=commodity_enabled,
                        risk_checker_enabled=checker_enabled,
                        reason="manual P&L",
                        expected_revision=current_revision,
                        expected_reset_generation=browser_reset_generation,
                    )
                elif "auto-refresh-interval" in triggered_ids:
                    if int(_auto_intervals or 0) <= 0 or not auto_refresh_enabled(
                        auto_refresh_state
                    ):
                        raise PreventUpdate
                    snapshot = refresh_manager.refresh(
                        force_pl=True,
                        forced_dates=current_applied,
                        view_date=current_view_date,
                        commodity_market_enabled=commodity_enabled,
                        risk_checker_enabled=checker_enabled,
                        reason="automatic 15-minute refresh",
                        expected_revision=current_revision,
                        expected_reset_generation=browser_reset_generation,
                    )
                elif (
                    "commo-market-toggle" in triggered_ids
                    or "risk-checker-toggle" in triggered_ids
                ):
                    apply_result = apply_force_dates(
                        refresh_manager,
                        current_applied,
                        reason="dashboard settings updated",
                        view_date=current_view_date,
                        commodity_market=commodity_enabled,
                        risk_checker=checker_enabled,
                        expected_revision=current_revision,
                        expected_reset_generation=browser_reset_generation,
                    )
                    snapshot = apply_result.snapshot
                else:
                    raise PreventUpdate
            except PreventUpdate:
                raise
            except RefreshInProgressError:
                return (
                    no_update,
                    no_update,
                    "A refresh is already running; following its live progress.",
                    "",
                    "error-log",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )
            except StaleResetGenerationError:
                return (
                    no_update,
                    no_update,
                    "Failed · This browser cache generation is stale.",
                    "⚠ Reload the page, then Retry Clear Cache.",
                    "error-log has-errors",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )
            except StaleRefreshError:
                return (
                    no_update,
                    no_update,
                    "The data changed before this action could start.",
                    "⚠ The committed revision changed. Reload the staged controls and try again.",
                    "error-log has-errors",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )
            except (TypeError, ValueError):
                return (
                    no_update,
                    no_update,
                    no_update,
                    "⚠ Saved or staged force dates are invalid and were not applied.",
                    "error-log has-errors",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )
            except Exception as error:
                incident_id = uuid.uuid4().hex[:10]
                app.logger.exception(
                    "Unexpected refresh callback failure; incident=%s type=%s",
                    incident_id,
                    type(error).__name__,
                )
                return (
                    no_update,
                    no_update,
                    "The refresh action failed; the last successful data remains visible.",
                    f"⚠ Unexpected refresh failure (incident {incident_id}). Check the server log.",
                    "error-log has-errors",
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )

            cache.replace(snapshot)
            status_text, error_text, error_class = _refresh_status(
                snapshot,
                action_committed=(apply_result is None or bool(apply_result.committed)),
            )
            if clearing and snapshot.errors:
                status_text = (
                    "Failed · Cache reset did not complete · Retry Clear Cache"
                )
            if (
                apply_result is not None
                and not apply_result.committed
                and not snapshot.errors
            ):
                error_text = (
                    "⚠ Date settings were not committed; the last successful "
                    "settings remain applied."
                    if applying
                    else "⚠ Dashboard settings were not committed; the last "
                    "successful settings remain applied."
                )
                error_class = "error-log has-errors"

            persisted = (
                persisted_force_dates(apply_result)
                if applying and apply_result is not None
                else None
            )
            return (
                snapshot.revision,
                _next_counter(refresh_result_counter),
                status_text,
                error_text,
                error_class,
                (
                    {}
                    if clearing and not snapshot.errors
                    else persisted
                    if persisted is not None
                    else no_update
                ),
                (
                    None
                    if clearing and not snapshot.errors
                    else apply_result.requested_view_date
                    if applying and apply_result is not None and apply_result.committed
                    else no_update
                ),
                (
                    completed_reset_generation
                    if completed_reset_generation is not None
                    else no_update
                ),
                (
                    completed_reset_generation
                    if completed_reset_generation is not None
                    else no_update
                ),
            )

        @app.callback(
            Output("operating-date-banner", "children"),
            Input("data-revision-store", "data"),
        )
        def sync_operating_dates(_revision):
            """Keep the prominent dates aligned with the committed snapshot."""
            if not _revision or refresh_manager.health.revision <= 0:
                return no_update
            return build_operating_date_content(refresh_manager.control_snapshot)

        @app.callback(
            Output(COMMODITY_MARKET_STORE_ID, "data"),
            Output(RISK_CHECKER_STORE_ID, "data"),
            Input("data-revision-store", "data"),
            Input(REFRESH_RESULT_STORE_ID, "data"),
            prevent_initial_call=True,
        )
        def sync_committed_dashboard_settings(_revision, _refresh_result):
            """Rebase settings after data or same-revision metadata commits."""
            if refresh_manager.health.revision <= 0:
                raise PreventUpdate
            committed = refresh_manager.control_snapshot
            return (
                bool(committed.commodity_market_enabled),
                bool(committed.risk_checker_enabled),
            )

        @app.callback(
            Output(FORCE_DRAFT_STORE_ID, "data"),
            Output(FORCE_RENDER_STORE_ID, "data"),
            Input(FORCE_STORE_ID, "modified_timestamp"),
            Input(VIEW_DATE_STORE_ID, "modified_timestamp"),
            Input("force-risk-cancel-button", "n_clicks", allow_optional=True),
            Input(REFRESH_RESULT_STORE_ID, "data"),
            Input("risk-date-editor", "id", allow_optional=True),
            Input({"type": "force-risk-checkbox", "source": ALL}, "value"),
            Input({"type": "forced-risk-date", "source": ALL}, "date"),
            # These controls are rendered inside `risk-date-editor` by a
            # callback. Mark them optional so Dash can build the initial
            # callback graph before that editor has mounted.
            Input("force-view-date-checkbox", "value", allow_optional=True),
            Input("forced-view-date", "date", allow_optional=True),
            Input("force-all-risk-checkbox", "value", allow_optional=True),
            Input("forced-all-risk-date", "date", allow_optional=True),
            State(FORCE_STORE_ID, "data"),
            State(VIEW_DATE_STORE_ID, "data"),
            State({"type": "force-risk-checkbox", "source": ALL}, "id"),
            State({"type": "forced-risk-date", "source": ALL}, "id"),
            State(FORCE_DRAFT_STORE_ID, "data"),
            State(FORCE_RENDER_STORE_ID, "data"),
            prevent_initial_call=False,
        )
        def manage_force_risk_draft(
            saved_modified,
            saved_view_modified,
            _cancel_clicks,
            _refresh_result,
            risk_date_editor_id,
            check_values,
            dates,
            force_view_values,
            forced_view_date,
            force_all_risk_values,
            forced_all_risk_date,
            saved_dates,
            saved_view_date,
            check_ids,
            date_ids,
            current_draft,
            render_counter,
        ):
            if risk_date_editor_id != "risk-date-editor":
                raise PreventUpdate
            triggered_ids = list(ctx.triggered_prop_ids.values())
            manager_snapshot = refresh_manager.control_snapshot
            applied = snapshot_forced_dates(manager_snapshot)
            applied_view = snapshot_forced_view_date(manager_snapshot)
            revision = manager_snapshot.revision

            if "force-risk-cancel-button" in triggered_ids:
                cancelled = cancel_force_dates(applied)
                return make_force_draft(
                    cancelled,
                    cancelled,
                    revision=revision,
                    applied_view_date=applied_view,
                    view_date=applied_view,
                ), _next_counter(render_counter)

            if REFRESH_RESULT_STORE_ID in triggered_ids:
                rebased = rebase_force_draft(
                    current_draft,
                    applied,
                    revision=revision,
                    applied_view_date=applied_view,
                )
                return rebased, _next_counter(render_counter)

            if (
                ctx.triggered_id is None
                or FORCE_STORE_ID in triggered_ids
                or VIEW_DATE_STORE_ID in triggered_ids
                or "risk-date-editor" in triggered_ids
            ):
                try:
                    proposal = (
                        normalize_forced_dates(saved_dates)
                        if saved_modified not in (None, -1) or saved_dates
                        else applied
                    )
                    proposal_view = (
                        normalize_view_date(saved_view_date)
                        if saved_view_modified not in (None, -1)
                        or saved_view_date not in (None, "")
                        else applied_view
                    )
                except (TypeError, ValueError):
                    proposal = applied
                    proposal_view = applied_view
                return make_force_draft(
                    applied,
                    proposal,
                    revision=revision,
                    applied_view_date=applied_view,
                    view_date=proposal_view,
                ), _next_counter(render_counter)

            if (
                any(isinstance(value, dict) for value in triggered_ids)
                or "force-view-date-checkbox" in triggered_ids
                or "forced-view-date" in triggered_ids
                or "force-all-risk-checkbox" in triggered_ids
                or "forced-all-risk-date" in triggered_ids
            ):
                proposal = collect_forced_dates(
                    check_values, dates, check_ids, date_ids
                )
                if "force-all-risk-checkbox" in triggered_ids and "force" not in (
                    force_all_risk_values or []
                ):
                    proposal = {}
                elif "force" in (force_all_risk_values or []):
                    selected_all_date = normalize_view_date(forced_all_risk_date)
                    if selected_all_date is None:
                        raise ValueError("forced all-risk date is missing")
                    proposal = {
                        source_type: selected_all_date
                        for source_type in manager_snapshot.risk_status[
                            "Source Type"
                        ].astype(str)
                    }
                proposal_view = (
                    normalize_view_date(forced_view_date)
                    if "force" in (force_view_values or [])
                    else None
                )
                previous = draft_forced_dates(current_draft, fallback=applied)
                previous_view = draft_view_date(current_draft, fallback=applied_view)
                if proposal == previous and proposal_view == previous_view:
                    raise PreventUpdate
                base = draft_base_dates(current_draft, fallback=applied)
                base_view = draft_base_view_date(current_draft, fallback=applied_view)
                return (
                    {
                        "base_revision": int(
                            current_draft.get("base_revision", revision)
                            if isinstance(current_draft, Mapping)
                            else revision
                        ),
                        "base_overrides": base,
                        "overrides": proposal,
                        "base_view_date": base_view,
                        "view_date": proposal_view,
                        "conflict": (
                            (base != applied or base_view != applied_view)
                            and (proposal != applied or proposal_view != applied_view)
                        ),
                    },
                    (
                        _next_counter(render_counter)
                        if "force-view-date-checkbox" in triggered_ids
                        or "forced-view-date" in triggered_ids
                        else no_update
                    ),
                )
            raise PreventUpdate

        @app.callback(
            Output("risk-date-editor", "children"),
            Input(FORCE_RENDER_STORE_ID, "data"),
            State(FORCE_DRAFT_STORE_ID, "data"),
            State("risk-date-editor", "id", allow_optional=True),
        )
        def render_risk_dates(_render_revision, draft_state, risk_date_editor_id):
            if risk_date_editor_id != "risk-date-editor":
                raise PreventUpdate
            snapshot = refresh_manager.control_snapshot
            applied = snapshot_forced_dates(snapshot)
            applied_view = snapshot_forced_view_date(snapshot)
            draft = draft_forced_dates(draft_state, fallback=applied)
            view_draft = draft_view_date(draft_state, fallback=applied_view)
            return build_risk_date_editor(
                snapshot,
                applied,
                draft,
                applied_view,
                view_draft,
            )

        @app.callback(
            Output("risk-checker-inventory", "children"),
            Input(
                "risk-checker-inventory-summary",
                "n_clicks",
                allow_optional=True,
            ),
            Input(REFRESH_RESULT_STORE_ID, "data"),
            prevent_initial_call=True,
        )
        def render_risk_checker_inventory(summary_clicks, _refresh_result):
            """Serialise the checker inventory only after its chevron opens."""
            if not int(summary_clicks or 0) % 2:
                raise PreventUpdate
            checker = refresh_manager.read_frame("risk_checker")
            return build_risk_checker_inventory(
                checker.frame,
                checker.checker_date,
                enabled=checker.risk_checker_enabled,
            )

        @app.callback(
            Output({"type": "forced-risk-date", "source": MATCH}, "disabled"),
            Input({"type": "force-risk-checkbox", "source": MATCH}, "value"),
        )
        def toggle_forced_date_picker(check_value):
            return "force" not in (check_value or [])

        @app.callback(
            Output("forced-view-date", "disabled"),
            Input("force-view-date-checkbox", "value", allow_optional=True),
        )
        def toggle_forced_view_date_picker(check_value):
            return "force" not in (check_value or [])

        @app.callback(
            Output("forced-all-risk-date", "disabled"),
            Input("force-all-risk-checkbox", "value", allow_optional=True),
        )
        def toggle_forced_all_risk_date_picker(check_value):
            return "force" not in (check_value or [])

        @app.callback(
            Output("force-risk-apply-button", "disabled"),
            Output("force-risk-cancel-button", "disabled"),
            Output("force-risk-edit-status", "children"),
            Output("force-risk-edit-status", "className"),
            Input(FORCE_DRAFT_STORE_ID, "data"),
            Input(REFRESH_RESULT_STORE_ID, "data"),
            Input("refresh-busy-store", "data"),
            Input("force-risk-apply-button", "id", allow_optional=True),
        )
        def update_force_risk_actions(
            draft_state,
            _refresh_result,
            refresh_busy,
            force_apply_button_id,
        ):
            if force_apply_button_id != "force-risk-apply-button":
                raise PreventUpdate
            if bool(refresh_busy):
                return (
                    True,
                    True,
                    "Refresh in progress. Apply and Cancel are temporarily unavailable.",
                    "force-risk-edit-status",
                )
            manager_snapshot = refresh_manager.control_snapshot
            applied = snapshot_forced_dates(manager_snapshot)
            applied_view = snapshot_forced_view_date(manager_snapshot)
            try:
                proposal = draft_forced_dates(draft_state, fallback=applied)
                base = draft_base_dates(draft_state, fallback=applied)
                proposal_view = draft_view_date(draft_state, fallback=applied_view)
                base_view = draft_base_view_date(draft_state, fallback=applied_view)
            except (TypeError, ValueError):
                return (
                    True,
                    False,
                    "The staged date settings are invalid. Cancel to restore applied dates.",
                    "force-risk-edit-status is-error",
                )

            # A successful Apply advances the manager before the draft callback
            # can rebase its browser Store.  During that short hand-off the old
            # draft is neither a new edit nor a conflict, so keep both actions
            # inert and describe the reconciliation instead of flashing the
            # stale "Apply to refresh" message.  A draft already marked as a
            # conflict remains actionable through Cancel below.
            try:
                draft_revision = int(
                    draft_state.get("base_revision", manager_snapshot.revision)
                    if isinstance(draft_state, Mapping)
                    else manager_snapshot.revision
                )
            except (TypeError, ValueError):
                draft_revision = manager_snapshot.revision
            draft_has_conflict = bool(
                draft_state.get("conflict", False)
                if isinstance(draft_state, Mapping)
                else False
            )
            if (
                draft_revision != int(manager_snapshot.revision)
                and not draft_has_conflict
            ):
                return (
                    True,
                    True,
                    "Reconciling applied date settings…",
                    "force-risk-edit-status",
                )

            dirty = proposal != applied or proposal_view != applied_view
            conflict = draft_has_conflict or (
                dirty and (base != applied or base_view != applied_view)
            )
            if conflict:
                return (
                    True,
                    False,
                    (
                        "Applied date settings changed while you were editing. "
                        "Cancel to reload them before applying."
                    ),
                    "force-risk-edit-status is-error",
                )
            if dirty:
                changed = sum(
                    1
                    for source in set(applied) | set(proposal)
                    if applied.get(source) != proposal.get(source)
                )
                changed += int(proposal_view != applied_view)
                noun = "change" if changed == 1 else "changes"
                return (
                    False,
                    False,
                    f"{changed} staged date {noun}. Apply to refresh, or Cancel to discard.",
                    "force-risk-edit-status is-dirty",
                )
            return (
                True,
                True,
                "All date settings are applied.",
                "force-risk-edit-status",
            )


__all__ = ["register_refresh_callbacks"]
