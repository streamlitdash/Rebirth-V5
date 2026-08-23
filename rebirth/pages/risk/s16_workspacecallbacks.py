"""V4 Risk-page workspace callback ownership."""

from __future__ import annotations

import json
from typing import Any, Sequence

import pandas as pd
from dash import ALL, Dash, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from rebirth.ui.s02_aggregation import apply_filters
from rebirth.ui.s04_components import build_aggregate_pl_table
from rebirth.ui.s01_constants import (
    RISK_TYPE_ORDER,
)
from rebirth.app.s02_contracts import (
    MarketHistoryLoaderProtocol,
    RefreshManagerProtocol,
)

from .s01_common import quick_risk_filter_map, reporting_filter_map
from .s11_promotion import PROMOTION_GENERATION_STORE_ID, apply_promotion_generation
from .s09_quickmarket import (
    QUICK_MARKET_DEFAULT_INDEX,
    build_quick_market_history_result,
    build_quick_market_result,
    quick_market_history_cell_state,
    quick_market_history_identity,
)
from .s10_search import (
    _combine_udl_dropdown_options,
    _render_quick_search_pivot,
)
from .s02_state import (
    _RiskDataCache,
    risk_exclude_selected,
)
from .s15_workspacetables import build_top_promotions_table


def register_workspace_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol | None,
    cache: _RiskDataCache,
    dimension_filter_ids: Sequence[str],
    dimension_filter_inputs: Sequence[Any],
    *,
    market_history_loader: MarketHistoryLoaderProtocol | None = None,
) -> None:
    """Register the four Risk workspace tabs and their lazy searches."""

    @app.callback(
        Output("aggregate-open-risk-types", "data"),
        Output("aggregate-pl-grid", "children"),
        Input("aggregate-pl-dimension", "value"),
        Input("data-revision-store", "data"),
        Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
        Input({"type": "aggregate-row-toggle", "risk_type": ALL}, "n_clicks"),
        Input("split-filter", "value"),
        *dimension_filter_inputs,
        Input("risk-filter-exclude-selected", "value"),
        State("aggregate-open-risk-types", "data"),
    )
    def reduce_and_render_aggregate_pl(
        dimension,
        _data_revision,
        promotion_generation,
        row_clicks,
        selected_splits,
        *values,
    ):
        """Apply shared filters, reduce a chevron, and render Aggregate P&L."""
        dimension_count = len(dimension_filter_ids)
        dimension_values = values[:dimension_count]
        exclude_value = (
            values[dimension_count] if len(values) > dimension_count else None
        )
        open_risk_types = (
            values[dimension_count + 1] if len(values) > dimension_count + 1 else None
        )

        updated_open_risk_types = no_update
        effective_open_risk_types = list(open_risk_types or [])
        triggered = ctx.triggered_id

        if isinstance(triggered, dict):
            if not row_clicks or max(row_clicks) == 0:
                raise PreventUpdate

            risk_type = triggered.get("risk_type")
            opened = set(effective_open_risk_types)

            if risk_type in opened:
                opened.remove(risk_type)
            else:
                opened.add(risk_type)

            effective_open_risk_types = sorted(
                opened,
                key=lambda value: (RISK_TYPE_ORDER.get(value, 99), value),
            )
            updated_open_risk_types = effective_open_risk_types

        aggregate_frame = cache.filtered(
            refresh_manager,
            None,  # Do not limit Aggregate P&L to the active Risk Explorer tab.
            None,  # Do not apply the active IR-family tab.
            selected_splits,
            reporting_filter_map(dimension_values),
            exclude_selected=risk_exclude_selected(exclude_value),
            promotion_generation=promotion_generation,
        )

        return (
            updated_open_risk_types,
            build_aggregate_pl_table(
                aggregate_frame,
                dimension,
                effective_open_risk_types,
            ),
        )

    @app.callback(
        Output("top-promotions-grid", "children"),
        Output("top-promotions-status", "children"),
        Input("risk-workspace-tabs", "value"),
        Input("top-promotions-rank-by", "value"),
        Input("data-revision-store", "data"),
        Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
        Input("split-filter", "value"),
        *dimension_filter_inputs,
        Input("risk-filter-exclude-selected", "value"),
    )
    def render_top_promotions(
        active_workspace,
        rank_by,
        data_revision,
        promotion_generation,
        selected_splits,
        *values,
    ):
        """Lazily present the committed promotion rank as a flat table."""
        if active_workspace != "top-promotions":
            return None, "Select Top Promotions to read the committed rank."

        dimension_count = len(dimension_filter_ids)
        dimension_values = values[:dimension_count]
        exclude_value = (
            values[dimension_count] if len(values) > dimension_count else None
        )
        reporting_filters = reporting_filter_map(dimension_values)
        committed = cache.current(refresh_manager)
        filtered = apply_filters(
            committed,
            [],
            list(selected_splits or []),
            reporting_filters,
            exclude_selected=risk_exclude_selected(exclude_value),
        )
        revision = int(data_revision or cache.revision)
        active_generation = cache.resolve_promotion_generation(promotion_generation)
        filtered = apply_promotion_generation(
            filtered,
            active_generation,
            revision=revision,
        )
        selected_rank = str(rank_by or "score")
        cache_key = json.dumps(
            {
                "revision": revision,
                "promotion_generation": (
                    active_generation.identifier
                    if active_generation is not None
                    and active_generation.kind == "current-view"
                    else None
                ),
                "rank_by": selected_rank,
                "splits": sorted(selected_splits or []),
                "filters": {
                    key: sorted(selected or [])
                    for key, selected in sorted(reporting_filters.items())
                },
                "exclude_selected": risk_exclude_selected(exclude_value),
                "view": "top-promotions",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        table = cache.rendered(
            cache_key,
            lambda: build_top_promotions_table(filtered, rank_by=selected_rank),
        )
        generation_label = (
            "Current-view promotion generation"
            if active_generation is not None
            and active_generation.kind == "current-view"
            else "Committed baseline promotion generation"
        )
        return (
            table,
            f"{generation_label} · revision {revision}",
        )

    if refresh_manager is not None:

        @app.callback(
            Output("quick-search-combine-udl", "options"),
            Output("quick-search-combine-udl", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("quick-search-identity-mode", "value"),
            Input("quick-search-combine-udl", "search_value"),
            State("quick-search-combine-udl", "value"),
            prevent_initial_call=False,
        )
        def load_combine_udl_options(
            active_workspace, _revision, identity_mode, search_value, current_value
        ):
            if active_workspace != "quick-risk":
                return no_update, no_update
            selected_mode = str(identity_mode or "reported").strip().casefold()

            try:
                options = _combine_udl_dropdown_options(
                    refresh_manager.search_combine_udl_options(
                        search_value,
                        identity_mode=selected_mode,
                        limit=100,
                        include=(str(current_value) if current_value else None),
                    )
                )
            except (
                AttributeError,
                LookupError,
                TypeError,
                ValueError,
                RuntimeError,
            ):
                return no_update, no_update

            # A mode change starts a fresh exact search rather than silently using
            # a selection created under the other identity authority.
            if ctx.triggered_id == "quick-search-identity-mode":
                return options, None

            values = {option["value"] for option in options}
            selected = str(current_value or "").strip()
            if selected in values:
                return options, no_update
            return options, (options[0]["value"] if options else None)

        @app.callback(
            Output("quick-search-results", "children"),
            Output("quick-search-dimensions", "value"),
            Input("quick-search-combine-udl", "value"),
            Input("quick-search-identity-mode", "value"),
            Input("quick-search-dimensions", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("split-filter", "value"),
            Input("risk-filter-exclude-selected", "value"),
            *dimension_filter_inputs,
            prevent_initial_call=True,
        )
        def render_current_pivot(
            combine_udl,
            identity_mode,
            index_columns,
            active_workspace,
            _revision,
            selected_splits,
            exclude_value,
            *dimension_values,
        ):
            rendered, index_update = _render_quick_search_pivot(
                refresh_manager,
                combine_udl=combine_udl,
                identity_mode=identity_mode,
                index_columns=index_columns,
                is_open=active_workspace == "quick-risk",
                risk_filters=quick_risk_filter_map(
                    selected_splits,
                    dimension_values,
                ),
                exclude_selected=risk_exclude_selected(exclude_value),
            )
            return rendered, index_update

        @app.callback(
            Output("quick-market-combine-udl", "options"),
            Output("quick-market-combine-udl", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("quick-market-combine-udl", "search_value"),
            State("quick-market-combine-udl", "value"),
            prevent_initial_call=False,
        )
        def load_market_udl_options(
            active_workspace, _revision, search_value, current_value
        ):
            if active_workspace != "quick-market":
                return no_update, no_update
            try:
                options = _combine_udl_dropdown_options(
                    refresh_manager.search_market_udl_options(
                        search_value,
                        limit=100,
                        include=(str(current_value) if current_value else None),
                    )
                )
            except (AttributeError, LookupError, TypeError, ValueError, RuntimeError):
                return no_update, no_update

            values = {option["value"] for option in options}
            selected = str(current_value or "").strip()
            if selected in values:
                return options, no_update
            return options, (options[0]["value"] if options else None)

        @app.callback(
            Output("quick-market-surface-metric-control", "hidden"),
            Input("quick-market-view", "value"),
        )
        def show_market_surface_metric(requested_view):
            return str(requested_view or "auto") != "surface"

        @app.callback(
            Output("quick-market-results", "children"),
            Output("quick-market-view", "value"),
            Output("quick-market-view", "options"),
            Output("quick-market-surface-metric", "options"),
            Output("quick-market-history-cell", "options"),
            Output("quick-market-history-cell", "value"),
            Output("quick-market-history-cell", "disabled"),
            Input("quick-market-combine-udl", "value"),
            Input("quick-market-view", "value"),
            Input("quick-market-surface-metric", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            State("quick-market-history-cell", "value"),
            prevent_initial_call=True,
        )
        def render_market_search(
            combine_udl,
            requested_view,
            surface_metric,
            active_workspace,
            _revision,
            requested_history_cell,
        ):
            if active_workspace != "quick-market":
                return (
                    None,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )
            selected = str(combine_udl or "").strip()
            if not selected:
                return (
                    html.Div(
                        "Select a Market identity to build its full tenor view.",
                        className="quick-search-hint",
                    ),
                    no_update,
                    no_update,
                    no_update,
                    [],
                    None,
                    True,
                )
            try:
                result = refresh_manager.pivot_market_exact(
                    selected,
                    index_columns=QUICK_MARKET_DEFAULT_INDEX,
                )
                if result.frame.empty:
                    selected_status = "Current"
                else:
                    statuses = result.frame["Market Status"].dropna().unique()
                    if len(statuses) != 1:
                        raise ValueError(
                            "exact MarketBook result has an ambiguous Market Status"
                        )
                    selected_status = str(statuses[0])
                rendered, resolved, options, surface_options = (
                    build_quick_market_result(
                        result.frame,
                        combine_udl=selected,
                        requested_view=str(requested_view or "auto"),
                        surface_metric=str(surface_metric or "current"),
                        market_status=selected_status,
                        revision=int(result.revision),
                    )
                )
                history_options, history_cell, history_disabled = (
                    quick_market_history_cell_state(
                        result.frame,
                        str(requested_history_cell or "") or None,
                    )
                )
                return (
                    rendered,
                    resolved,
                    options,
                    surface_options,
                    history_options,
                    history_cell,
                    history_disabled,
                )
            except (
                AttributeError,
                KeyError,
                LookupError,
                TypeError,
                ValueError,
                RuntimeError,
            ) as error:
                app.logger.exception("Quick Market Search render failed")
                detail = (
                    " ".join(str(error).splitlines()).strip() or type(error).__name__
                )
                return (
                    html.Div(
                        f"Quick Market Search failed: {type(error).__name__}: {detail[:400]}",
                        className="quick-search-error",
                        role="alert",
                    ),
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                )

        @app.callback(
            Output("quick-market-history-chart", "children"),
            Output("quick-market-history-status", "children"),
            Input("quick-market-combine-udl", "value"),
            Input("quick-market-history-cell", "value"),
            Input("quick-market-history-summary", "n_clicks"),
            Input("quick-market-history-period", "value"),
            Input("quick-market-history-date-range", "start_date"),
            Input("quick-market-history-date-range", "end_date"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            prevent_initial_call=True,
        )
        def render_market_history(
            combine_udl,
            requested_history_cell,
            history_summary_clicks,
            history_period,
            history_start_date,
            history_end_date,
            active_workspace,
            _revision,
        ):
            if (
                active_workspace != "quick-market"
                or not int(history_summary_clicks or 0) % 2
            ):
                return no_update, no_update
            selected = str(combine_udl or "").strip()
            if not selected:
                return (
                    html.Div(
                        "Select a Market identity to show its daily history.",
                        className="quick-search-hint",
                    ),
                    "Historical values use one exact raw MarketBook quote cell.",
                )
            try:
                result = refresh_manager.pivot_market_exact(
                    selected,
                    index_columns=QUICK_MARKET_DEFAULT_INDEX,
                )
                if result.frame.empty:
                    return (
                        html.Div(
                            f"No MarketBook rows match '{selected}'.",
                            className="quick-search-empty",
                        ),
                        "No current quote is available to match against history.",
                    )
                statuses = result.frame["Market Status"].dropna().unique()
                if len(statuses) != 1:
                    raise ValueError(
                        "exact MarketBook result has an ambiguous Market Status"
                    )
                history_options, history_cell, _disabled = (
                    quick_market_history_cell_state(
                        result.frame,
                        str(requested_history_cell or "") or None,
                    )
                )
                if not history_options or history_cell is None:
                    raise ValueError("exact MarketBook result has no quote cell")
                risk_type, risk_greek, underlying = quick_market_history_identity(
                    result.frame
                )
                history_error = ""
                if market_history_loader is None:
                    history = pd.DataFrame()
                    history_error = "Historical archive is not configured; showing today's point only."
                else:
                    try:
                        history = market_history_loader(
                            risk_type,
                            risk_greek,
                            underlying,
                        )
                        if not isinstance(history, pd.DataFrame):
                            raise TypeError(
                                "market history loader must return a pandas DataFrame"
                            )
                    except (
                        KeyError,
                        LookupError,
                        OSError,
                        TypeError,
                        ValueError,
                        RuntimeError,
                    ) as error:
                        app.logger.exception("Quick Market history load failed")
                        history = pd.DataFrame()
                        detail = (
                            " ".join(str(error).splitlines()).strip()
                            or type(error).__name__
                        )
                        history_error = (
                            "Historical archive unavailable: "
                            f"{type(error).__name__}: {detail[:280]}. "
                            "Showing today's point only."
                        )
                chart, status = build_quick_market_history_result(
                    history,
                    result.frame,
                    selected_cell=history_cell,
                    market_date=result.market_date,
                    market_status=str(statuses[0]),
                    period=str(history_period or "all"),
                    start_date=history_start_date,
                    end_date=history_end_date,
                )
                return chart, (history_error or status)
            except (
                AttributeError,
                KeyError,
                LookupError,
                TypeError,
                ValueError,
                RuntimeError,
            ) as error:
                app.logger.exception("Quick Market history render failed")
                detail = (
                    " ".join(str(error).splitlines()).strip() or type(error).__name__
                )
                return (
                    html.Div(
                        f"Historical market failed: {type(error).__name__}: {detail[:400]}",
                        className="quick-search-error",
                        role="alert",
                    ),
                    "Historical market could not be rendered.",
                )


__all__ = ["register_workspace_callbacks"]
