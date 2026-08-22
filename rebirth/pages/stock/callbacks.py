"""V4 page-owned callbacks for the dated Stock comparison."""

from __future__ import annotations

from threading import Lock
from typing import Any, Mapping, Sequence

import pandas as pd
from dash import ALL, Input, Output, State, ctx, html, no_update
from dash.exceptions import MissingCallbackContextException

from rebirth.app.contracts import RefreshManagerProtocol
from rebirth.domain.stock import (
    filter_stock_comparison,
    normalize_stock_promotion_threshold,
)
from rebirth.services.saved_views import SavedFilterViewRepository
from rebirth.ui.filter_views import (
    register_saved_filter_view_callbacks,
    saved_view_request_id,
    saved_view_request_matches_base,
    saved_view_request_values,
)

from .data import (
    STOCK_FILTER_FIELDS,
    STOCK_FILTER_IDS,
    STOCK_SAVED_VIEW_CONTROLS,
    StockPageData,
    load_stock_page_data,
    normalize_stock_date_pair,
    stock_exclude_selected,
    stock_filter_map,
    stock_filter_options,
)
from .history_callbacks import register_stock_history_callbacks
from .tables import (
    STOCK_HIERARCHY_TOGGLE_TYPE,
    build_stock_hierarchy_panel_with_state,
    build_stock_table_panel,
    normalize_stock_hierarchy_open_tokens,
    toggle_stock_hierarchy_open_tokens,
)
from .view import (
    build_stock_page_from_data,
    build_stock_page_placeholder,
    stock_summary_text,
)


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
    stock_intent_lock = Lock()
    stock_intent_sequence = 0
    stock_latest_intent: dict[str, tuple[int, tuple[object, ...]]] = {}

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

    @app.callback(
        Output("stock-current-workspace", "style"),
        Output("stock-history-workspace", "style"),
        Input("stock-workspace-tabs", "value"),
    )
    def switch_stock_workspace(value):
        """Show one mounted workspace; changing tabs never reads an archive."""

        history_selected = value == "history"
        return (
            {"display": "none"} if history_selected else {},
            {} if history_selected else {"display": "none"},
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

    def claim_stock_intent(
        request_scope: object,
        signature: tuple[object, ...],
    ) -> tuple[str, int]:
        """Record the newest load request for one mounted Stock page."""

        nonlocal stock_intent_sequence
        scope = str(request_scope or "stock-unscoped")
        with stock_intent_lock:
            current = stock_latest_intent.get(scope)
            if current is not None and current[1] == signature:
                return scope, current[0]
            stock_intent_sequence += 1
            sequence = stock_intent_sequence
            stock_latest_intent[scope] = (sequence, signature)
        return scope, sequence

    def stock_intent_is_current(scope: str, sequence: int) -> bool:
        with stock_intent_lock:
            current = stock_latest_intent.get(scope)
            return current is not None and current[0] == sequence

    def finish_stock_intent(scope: str, sequence: int) -> None:
        with stock_intent_lock:
            current = stock_latest_intent.get(scope)
            if current is not None and current[0] == sequence:
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

        committed_revision = committed_stock_revision()
        intent_signature = (
            committed_revision,
            str(current_date),
            str(prior_date),
            tuple(tuple(map(str, values or ())) for values in selected_filter_values),
            tuple(map(str, exclude_value or ())),
            bool(force_render),
        )
        scope, intent_sequence = claim_stock_intent(
            request_scope,
            intent_signature,
        )
        try:
            current, prior = normalize_stock_date_pair(current_date, prior_date)
        except Exception as error:
            # Invalid picker state needs a user edit, not a one-second
            # automatic retry loop.
            finish_stock_intent(scope, intent_sequence)
            return stock_error_result(error, retryable=False)
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
        running=[(Output("stock-load-trigger", "interval"), 60_000, 1_000)],
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

    register_stock_history_callbacks(
        app,
        stock_history_source=stock_history_source,
        stock_cached_pages=stock_cached_pages,
        stock_cache_key=stock_cache_key,
    )


__all__ = ["register_callbacks"]
