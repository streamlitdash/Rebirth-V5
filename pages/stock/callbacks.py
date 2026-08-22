"""Page-owned callbacks for the dated Stock comparison."""

from __future__ import annotations

from threading import Lock
from typing import Any, Mapping, Sequence

import pandas as pd
from dash import ALL, Input, Output, State, ctx, html, no_update
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from core.s07_stock import filter_stock_comparison, normalize_stock_promotion_threshold
from core.s08_saved_views import SavedFilterViewRepository
from shared.contracts import RefreshManagerProtocol
from shared.saved_views import (
    register_saved_filter_view_callbacks,
    saved_view_request_id,
    saved_view_request_matches_base,
    saved_view_request_values,
)

from .view import (
    STOCK_FILTER_FIELDS,
    STOCK_FILTER_IDS,
    STOCK_HIERARCHY_TOGGLE_TYPE,
    STOCK_SAVED_VIEW_CONTROLS,
    StockPageData,
    build_stock_history_empty_figure,
    build_stock_history_figure,
    build_stock_history_table,
    build_stock_hierarchy_panel_with_state,
    build_stock_page_from_data,
    build_stock_page_placeholder,
    build_stock_table_panel,
    load_stock_page_data,
    normalize_stock_date_pair,
    normalize_stock_history_frame,
    normalize_stock_hierarchy_open_tokens,
    stock_exclude_selected,
    stock_filter_map,
    stock_filter_options,
    stock_history_date_range,
    stock_history_identity_from_token,
    stock_history_identity_options,
    stock_summary_text,
    toggle_stock_hierarchy_open_tokens,
)


STOCK_HISTORY_SELECTOR_LIMIT = 50


def register_callbacks(
    app: Any,
    *,
    refresh_manager: RefreshManagerProtocol | None,
    stock_source: Any | None,
    stock_portfolio_source: Any | None,
    saved_view_repository: SavedFilterViewRepository,
    stock_history_source: Any | None = None,
) -> None:
    """Register Stock callbacks with app-owned services and page-owned caches."""

    if stock_source is None or stock_portfolio_source is None:
        return

    stock_load_lock = Lock()
    stock_cached_pages: dict[tuple[int, str, str, str], StockPageData] = {}
    stock_history_lock = Lock()
    stock_history_cache: dict[tuple[str, str, str, str], pd.DataFrame] = {}
    stock_intent_lock = Lock()
    stock_intent_sequence = 0
    stock_latest_intent: dict[str, int] = {}

    def loaded_stock_page(current_date: object, prior_date: object) -> StockPageData:
        """Resolve two dated Stock legs behind the mounted page shell."""

        return load_stock_page_data(
            stock_source=stock_source,
            portfolio_config_source=stock_portfolio_source,
            current_date=current_date,
            prior_date=prior_date,
            # The current selected Stock date owns the mapping authority.
            portfolio_date=current_date,
        )

    register_saved_filter_view_callbacks(
        app,
        saved_view_repository,
        STOCK_SAVED_VIEW_CONTROLS,
    )

    def committed_stock_revision() -> int:
        try:
            return (
                int(refresh_manager.health.revision)
                if refresh_manager is not None
                else 0
            )
        except Exception:
            return 0

    def stock_filter_outputs():
        outputs = [
            output
            for field in STOCK_FILTER_FIELDS
            for output in (
                Output(STOCK_FILTER_IDS[field.key], "options"),
                Output(STOCK_FILTER_IDS[field.key], "value"),
            )
        ]
        outputs.append(Output("stock-filter-exclude-selected", "value"))
        return outputs

    def stock_filter_states():
        return [
            State(STOCK_FILTER_IDS[field.key], "value") for field in STOCK_FILTER_FIELDS
        ]

    def stock_cache_token(
        revision: int,
        current_date: pd.Timestamp,
        prior_date: pd.Timestamp,
        portfolio_date: pd.Timestamp,
    ) -> dict[str, Any]:
        return {
            "revision": revision,
            "current_date": current_date.date().isoformat(),
            "prior_date": prior_date.date().isoformat(),
            "portfolio_date": portfolio_date.date().isoformat(),
        }

    def stock_cache_key(token: object) -> tuple[int, str, str, str] | None:
        if not isinstance(token, Mapping):
            return None
        try:
            return (
                int(token["revision"]),
                str(token["current_date"]),
                str(token["prior_date"]),
                str(token["portfolio_date"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def stock_history_cache_key(token: object) -> tuple[str, str, str, str] | None:
        if not isinstance(token, Mapping):
            return None
        try:
            return (
                str(token["request_scope"]),
                str(token["identity"]),
                str(token["start_date"]),
                str(token["end_date"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    def stock_error_result(error: Exception, *, retryable: bool):
        return (
            build_stock_page_placeholder(
                f"Stock could not be loaded: {error}",
                error=True,
            ),
            no_update,
            None,
            not retryable,
            *([no_update] * ((2 * len(STOCK_FILTER_FIELDS)) + 1)),
        )

    def claim_stock_intent(request_scope: object) -> tuple[str, int]:
        """Record the newest load request for one mounted Stock page."""

        nonlocal stock_intent_sequence
        scope = str(request_scope or "stock-unscoped")
        with stock_intent_lock:
            stock_intent_sequence += 1
            sequence = stock_intent_sequence
            stock_latest_intent[scope] = sequence
        return scope, sequence

    def stock_intent_is_current(scope: str, sequence: int) -> bool:
        with stock_intent_lock:
            return stock_latest_intent.get(scope) == sequence

    def finish_stock_intent(scope: str, sequence: int) -> None:
        with stock_intent_lock:
            if stock_latest_intent.get(scope) == sequence:
                stock_latest_intent.pop(scope, None)

    def stale_stock_result():
        """Ignore a response superseded by newer date intent in the browser."""

        return (no_update,) * (5 + (2 * len(STOCK_FILTER_FIELDS)))

    def render_stock_result(
        page_data: StockPageData,
        selected_filter_values: Sequence[Sequence[str] | None],
        exclude_value: Sequence[str] | None,
    ) -> tuple[Any, list[Any]]:
        selected_filters = stock_filter_map(selected_filter_values)
        options, valid = stock_filter_options(
            page_data.mapped_stock,
            selected_filters,
        )
        page = build_stock_page_from_data(
            page_data,
            selected_filters=valid,
            exclude_selected=stock_exclude_selected(exclude_value),
        )
        filter_payload: list[Any] = []
        for field in STOCK_FILTER_FIELDS:
            filter_payload.extend((options[field.key], valid[field.key]))
        filter_payload.append(list(exclude_value or []))
        return page.children, filter_payload

    def load_stock_revision(
        current_date: object,
        prior_date: object,
        loaded_revision: object,
        loaded_dates: object,
        selected_filter_values: Sequence[Sequence[str] | None],
        exclude_value: Sequence[str] | None,
        request_scope: object,
        *,
        force_render: bool = False,
    ):
        """Coalesce dated loads and retain retryability after failures."""

        scope, intent_sequence = claim_stock_intent(request_scope)
        try:
            current, prior = normalize_stock_date_pair(current_date, prior_date)
        except Exception as error:
            # Invalid picker state needs a user edit, not a one-second
            # automatic retry loop.
            finish_stock_intent(scope, intent_sequence)
            return stock_error_result(error, retryable=False)
        committed_revision = committed_stock_revision()
        token = stock_cache_token(
            committed_revision,
            current,
            prior,
            current,
        )
        key = stock_cache_key(token)
        if (
            loaded_revision == committed_revision
            and stock_cache_key(loaded_dates) == key
            and key in stock_cached_pages
            and not force_render
        ):
            finish_stock_intent(scope, intent_sequence)
            return (
                no_update,
                no_update,
                no_update,
                True,
                *([no_update] * ((2 * len(STOCK_FILTER_FIELDS)) + 1)),
            )
        if not stock_load_lock.acquire(blocking=False):
            return (
                no_update,
                no_update,
                no_update,
                False,
                *([no_update] * ((2 * len(STOCK_FILTER_FIELDS)) + 1)),
            )
        try:
            page_data = stock_cached_pages.get(key)
            if page_data is None:
                try:
                    page_data = loaded_stock_page(current, prior)
                except Exception as error:
                    app.logger.exception("Could not load the Stock page")
                    if not stock_intent_is_current(scope, intent_sequence):
                        return stale_stock_result()
                    finish_stock_intent(scope, intent_sequence)
                    return stock_error_result(error, retryable=True)
                if key is None:
                    raise RuntimeError("Stock cache key could not be constructed")
                stock_cached_pages[key] = page_data
                if len(stock_cached_pages) > 8:
                    stock_cached_pages.pop(next(iter(stock_cached_pages)))
            if not stock_intent_is_current(scope, intent_sequence):
                return stale_stock_result()
            children, filter_payload = render_stock_result(
                page_data,
                selected_filter_values,
                exclude_value,
            )
            if committed_stock_revision() != committed_revision:
                # A commit landed while a dated connector was in flight.
                # The completed result may paint, but its revision/date
                # token is not released and the timer remains retryable.
                return (
                    children,
                    no_update,
                    no_update,
                    False,
                    *filter_payload,
                )
            finish_stock_intent(scope, intent_sequence)
            return (
                children,
                committed_revision,
                token,
                True,
                *filter_payload,
            )
        finally:
            stock_load_lock.release()

    @app.callback(
        Output("stock-page-content", "children"),
        Output("stock-loaded-revision", "data"),
        Output("stock-loaded-dates", "data"),
        Output("stock-load-trigger", "disabled"),
        *stock_filter_outputs(),
        Input("stock-load-trigger", "n_intervals"),
        Input("refresh-commit-revision", "children"),
        Input("stock-compare-button", "n_clicks"),
        Input(STOCK_SAVED_VIEW_CONTROLS.apply_request_id, "data"),
        State("stock-loaded-revision", "data"),
        State("stock-loaded-dates", "data"),
        State("stock-current-date", "date"),
        State("stock-prior-date", "date"),
        State("stock-filter-exclude-selected", "value"),
        *stock_filter_states(),
        State("stock-request-scope", "data"),
        State(STOCK_SAVED_VIEW_CONTROLS.applied_request_id, "data"),
        prevent_initial_call=True,
    )
    def coordinate_stock_load(
        _ticks,
        _committed_revision,
        _compare_clicks,
        *callback_values,
    ):
        """Own mount, Compare, retry, and financial-commit Stock loads."""

        # The optional fallback keeps direct-library callers from before
        # saved views source-compatible; Dash always supplies the request
        # Input in the new callback graph.
        legacy_value_count = 6 + len(STOCK_FILTER_FIELDS)
        if len(callback_values) == legacy_value_count:
            saved_view_request = None
            state_values = callback_values
            applied_saved_view_request = None
        else:
            saved_view_request = callback_values[0]
            state_values = callback_values[1:-1]
            applied_saved_view_request = callback_values[-1]
        (
            loaded_revision,
            loaded_dates,
            current_date,
            prior_date,
            exclude_value,
            *filter_values_and_scope,
        ) = state_values

        selected_filter_values = filter_values_and_scope[: len(STOCK_FILTER_FIELDS)]
        request_scope = filter_values_and_scope[-1]
        try:
            saved_view_triggered = (
                ctx.triggered_id == STOCK_SAVED_VIEW_CONTROLS.apply_request_id
            )
        except (LookupError, MissingCallbackContextException):
            saved_view_triggered = False
        request_id = saved_view_request_id(saved_view_request)
        saved_view_pending = bool(
            request_id and request_id != applied_saved_view_request
        )
        request_matches_base = False
        if saved_view_pending:
            try:
                request_matches_base = saved_view_request_matches_base(
                    saved_view_request,
                    STOCK_SAVED_VIEW_CONTROLS,
                    selected_filter_values,
                    exclude_value,
                )
            except ValueError:
                request_matches_base = False
        apply_pending = saved_view_pending and (
            saved_view_triggered or request_matches_base
        )
        if apply_pending:
            try:
                requested = saved_view_request_values(
                    saved_view_request,
                    STOCK_SAVED_VIEW_CONTROLS,
                )
            except ValueError:
                requested = None
            if requested is not None:
                selected_filter_values, exclude_value = requested
        return load_stock_revision(
            current_date,
            prior_date,
            loaded_revision,
            loaded_dates,
            selected_filter_values,
            exclude_value,
            request_scope,
            force_render=apply_pending,
        )

    @app.callback(
        Output("stock-row-count", "children"),
        Output("stock-mapped-count", "children"),
        Output("stock-unmapped-count", "children"),
        Output("stock-dimension-filter-store", "data"),
        Output("stock-hierarchy-open-paths", "data"),
        Output("stock-hierarchy-view", "children"),
        *[Input(STOCK_FILTER_IDS[field.key], "value") for field in STOCK_FILTER_FIELDS],
        Input("stock-filter-exclude-selected", "value"),
        Input("stock-promotion-threshold", "value"),
        Input("stock-loaded-dates", "data"),
        Input(
            {"type": STOCK_HIERARCHY_TOGGLE_TYPE, "path": ALL},
            "n_clicks",
        ),
        State("stock-hierarchy-open-paths", "data"),
        prevent_initial_call=True,
    )
    def filter_stock_table(*values):
        """Rebuild the Stock stack and source rows from the server cache."""
        selected_filter_values = values[: len(STOCK_FILTER_FIELDS)]
        exclude_value = values[len(STOCK_FILTER_FIELDS)]
        promotion_threshold = values[len(STOCK_FILTER_FIELDS) + 1]
        loaded_dates = values[len(STOCK_FILTER_FIELDS) + 2]
        _row_clicks = values[len(STOCK_FILTER_FIELDS) + 3]
        current_open_paths = values[-1]
        selected_filters = stock_filter_map(selected_filter_values)
        key = stock_cache_key(loaded_dates)
        page_data = stock_cached_pages.get(key)
        if page_data is None:
            return (no_update,) * 6
        filtered = filter_stock_comparison(
            page_data.mapped_stock,
            selected_filters,
            exclude_selected=stock_exclude_selected(exclude_value),
        )
        effective_threshold = normalize_stock_promotion_threshold(promotion_threshold)
        rows, mapped, unmapped = stock_summary_text(
            filtered,
            total_rows=len(page_data.mapped_stock),
            current_date=page_data.current_date,
            prior_date=page_data.prior_date,
        )
        requested_open_paths = normalize_stock_hierarchy_open_tokens(current_open_paths)
        try:
            triggered = ctx.triggered_id
            triggered_clicks = ctx.triggered[0].get("value") if ctx.triggered else 0
        except MissingCallbackContextException:
            triggered = None
            triggered_clicks = 0
        if (
            isinstance(triggered, dict)
            and triggered.get("type") == STOCK_HIERARCHY_TOGGLE_TYPE
            and int(triggered_clicks or 0) > 0
        ):
            requested_open_paths = toggle_stock_hierarchy_open_tokens(
                requested_open_paths,
                triggered.get("path"),
            )
        hierarchy, effective_open_paths = build_stock_hierarchy_panel_with_state(
            filtered,
            has_unfiltered_rows=not page_data.mapped_stock.empty,
            promotion_threshold=effective_threshold,
            open_path_tokens=requested_open_paths,
        )
        hierarchy_triggered = (
            isinstance(triggered, dict)
            and triggered.get("type") == STOCK_HIERARCHY_TOGGLE_TYPE
            and int(triggered_clicks or 0) > 0
        )
        if hierarchy_triggered:
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                effective_open_paths,
                hierarchy,
            )
        return (
            rows,
            mapped,
            unmapped,
            {
                "filters": selected_filters,
                "exclude_selected": stock_exclude_selected(exclude_value),
                "promotion_threshold": effective_threshold,
            },
            effective_open_paths,
            hierarchy,
        )

    @app.callback(
        Output("stock-table-panel", "children"),
        Output("stock-source-rows-state", "data"),
        Output("stock-source-rows-button", "children"),
        Output("stock-source-comparison-details", "open"),
        Input("stock-source-rows-button", "n_clicks"),
        Input("stock-loaded-dates", "data"),
        *[Input(STOCK_FILTER_IDS[field.key], "value") for field in STOCK_FILTER_FIELDS],
        Input("stock-filter-exclude-selected", "value"),
        State("stock-source-rows-state", "data"),
        prevent_initial_call=True,
    )
    def render_stock_source_rows(
        _button_clicks,
        loaded_dates,
        *filter_values_exclude_and_state,
    ):
        """Load filtered raw rows only after an explicit page-local request."""

        selected_filter_values = filter_values_exclude_and_state[
            : len(STOCK_FILTER_FIELDS)
        ]
        exclude_value = filter_values_exclude_and_state[len(STOCK_FILTER_FIELDS)]
        current_state = filter_values_exclude_and_state[-1]
        key = stock_cache_key(loaded_dates)
        page_data = stock_cached_pages.get(key)
        state = current_state if isinstance(current_state, Mapping) else {}
        same_snapshot = stock_cache_key(state.get("loaded_dates")) == key
        requested = bool(state.get("requested")) and same_snapshot
        try:
            triggered = ctx.triggered_id
            triggered_clicks = ctx.triggered[0].get("value") if ctx.triggered else 0
        except MissingCallbackContextException:
            triggered = None
            triggered_clicks = 0
        if triggered == "stock-source-rows-button" and int(triggered_clicks or 0) > 0:
            requested = not requested

        state_payload = {
            "requested": requested,
            "loaded_dates": loaded_dates if key is not None else None,
        }
        if page_data is None or not requested:
            return (
                html.P(
                    "Source comparison rows are not loaded. Load them only when needed.",
                    className="static-data-page-note",
                ),
                {**state_payload, "requested": False},
                "Load filtered source rows",
                False,
            )

        selected_filters = stock_filter_map(selected_filter_values)
        filtered = filter_stock_comparison(
            page_data.mapped_stock,
            selected_filters,
            exclude_selected=stock_exclude_selected(exclude_value),
        )
        return (
            build_stock_table_panel(
                filtered,
                has_unfiltered_rows=not page_data.mapped_stock.empty,
            ),
            state_payload,
            "Hide source rows",
            True,
        )

    if stock_history_source is None:
        return

    @app.callback(
        Output("stock-history-identity", "options"),
        Output("stock-history-identity", "value"),
        Output("stock-history-load-button", "disabled"),
        Input("stock-loaded-dates", "data"),
        Input("stock-history-identity", "search_value"),
        State("stock-history-identity", "value"),
        prevent_initial_call=True,
    )
    def sync_stock_history_identities(
        loaded_dates,
        search_value,
        selected_identity,
    ):
        """Derive exact selector values from the cached comparison only."""

        page_data = stock_cached_pages.get(stock_cache_key(loaded_dates))
        if page_data is None:
            return [], None, True
        all_options = stock_history_identity_options(page_data.mapped_stock)
        search = str(search_value or "").strip().casefold()
        options = [
            option
            for option in all_options
            if not search or search in option["label"].casefold()
        ][:STOCK_HISTORY_SELECTOR_LIMIT]
        option_by_value = {option["value"]: option for option in all_options}
        selected_option = option_by_value.get(selected_identity)
        if selected_option is not None and selected_option not in options:
            options = [selected_option, *options[: STOCK_HISTORY_SELECTOR_LIMIT - 1]]
        selected = (
            selected_identity
            if selected_option is not None
            else (options[0]["value"] if options else None)
        )
        return options, selected, not bool(options)

    @app.callback(
        Output("stock-history-loaded-range", "data"),
        Output("stock-history-status", "children"),
        Input("stock-history-load-button", "n_clicks"),
        State("stock-current-date", "date"),
        State("stock-request-scope", "data"),
        State("stock-history-identity", "value"),
        prevent_initial_call=True,
    )
    def load_stock_history_rows(
        n_clicks,
        current_date,
        request_scope,
        identity_token,
    ):
        """Load the bounded history only after the explicit page-local request."""

        if int(n_clicks or 0) <= 0:
            raise PreventUpdate
        try:
            start_date, end_date = stock_history_date_range(current_date)
            identity = stock_history_identity_from_token(identity_token)
            with stock_history_lock:
                history = normalize_stock_history_frame(
                    stock_history_source(identity, start_date, end_date),
                    identity=identity,
                    start_date=start_date,
                    end_date=end_date,
                )
                token = {
                    "request_scope": str(request_scope or "stock-unscoped"),
                    "identity": identity_token,
                    "start_date": start_date.date().isoformat(),
                    "end_date": end_date.date().isoformat(),
                }
                key = stock_history_cache_key(token)
                if key is None:
                    raise RuntimeError(
                        "Stock history cache key could not be constructed"
                    )
                stock_history_cache[key] = history
                if len(stock_history_cache) > 4:
                    stock_history_cache.pop(next(iter(stock_history_cache)))
            return (
                token,
                (
                    f"Loaded {len(history):,} historical observations "
                    f"from {token['start_date']} through {token['end_date']}."
                ),
            )
        except Exception as error:
            app.logger.exception("Could not load Stock history")
            return (
                None,
                f"Stock history could not be loaded: {error}",
            )

    @app.callback(
        Output("stock-history-chart", "figure"),
        Output("stock-history-table-panel", "children"),
        Input("stock-history-identity", "value"),
        Input("stock-history-metric", "value"),
        Input("stock-history-loaded-range", "data"),
        Input("stock-loaded-dates", "data"),
        prevent_initial_call=True,
    )
    def render_stock_history(identity_token, metric, loaded_range, loaded_dates):
        """Render one cached exact identity without another archive read."""

        key = stock_history_cache_key(loaded_range)
        history = stock_history_cache.get(key)
        comparison_key = stock_cache_key(loaded_dates)
        selected_current_date = (
            comparison_key[1] if comparison_key is not None else None
        )
        selection_matches = (
            isinstance(loaded_range, Mapping)
            and loaded_range.get("identity") == identity_token
            and loaded_range.get("end_date") == selected_current_date
        )
        if history is None or not selection_matches:
            message = "Load the trailing 1Y history for the selected Stock identity."
            return (
                build_stock_history_empty_figure(message),
                html.P(message, className="static-data-page-note"),
            )
        try:
            return (
                build_stock_history_figure(
                    history,
                    identity_token=identity_token,
                    metric=metric,
                    start_date=loaded_range["start_date"],
                    end_date=loaded_range["end_date"],
                ),
                build_stock_history_table(
                    history,
                    identity_token=identity_token,
                ),
            )
        except Exception as error:
            message = f"Stock history selection could not be rendered: {error}"
            return (
                build_stock_history_empty_figure(message),
                html.P(message, className="static-data-empty", role="alert"),
            )


__all__ = ["register_callbacks"]
