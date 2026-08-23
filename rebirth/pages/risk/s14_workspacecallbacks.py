"""V4 Risk-page workspace callback ownership."""

from __future__ import annotations

import json

from dash import ALL, Dash, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from rebirth.app.s03_logging import perf_span
from rebirth.ui.s02_aggregation import apply_filters
from rebirth.ui.s04_components import build_aggregate_pl_table
from rebirth.ui.s01_constants import (
    RISK_TYPE_ORDER,
)
from rebirth.app.s02_contracts import RefreshManagerProtocol

from .s01_common import quick_risk_filter_map, reporting_filter_map
from .s11_promotion import PROMOTION_GENERATION_STORE_ID, apply_promotion_generation
from .s09_quickmarket import (
    QUICK_MARKET_DEFAULT_INDEX,
    build_quick_market_result,
)
from .s10_search import (
    _combine_udl_dropdown_options,
    _render_quick_search_pivot,
)
from .s02_state import (
    _RiskDataCache,
    risk_exclude_selected,
)
from .s13_workspacetables import build_top_promotions_table


def register_workspace_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol | None,
    cache: _RiskDataCache,
) -> None:
    """Register the four Risk workspace tabs and their lazy searches."""

    @app.callback(
        Output("aggregate-open-risk-types", "data"),
        Output("aggregate-pl-grid", "children"),
        Input("aggregate-pl-dimension", "value"),
        Input("data-revision-store", "data"),
        Input({"type": "aggregate-row-toggle", "risk_type": ALL}, "n_clicks"),
        Input("split-filter", "value"),
        Input("dimension-filter-values-store", "data"),
        Input("risk-filter-exclude-applied-store", "data"),
        State("aggregate-open-risk-types", "data"),
    )
    def reduce_and_render_aggregate_pl(
        dimension,
        _data_revision,
        row_clicks,
        selected_splits,
        dimension_values,
        exclude_value,
        open_risk_types,
    ):
        """Apply shared filters, reduce a chevron, and render Aggregate P&L."""
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
        Input("data-revision-store", "data"),
        Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
        Input("split-filter", "value"),
        Input("dimension-filter-values-store", "data"),
        Input("risk-filter-exclude-applied-store", "data"),
        Input("top-promotions-signal", "value"),
    )
    def render_top_promotions(
        active_workspace,
        data_revision,
        promotion_generation,
        selected_splits,
        dimension_values,
        exclude_value,
        signal,
    ):
        """Lazily present the committed promotion rank as a flat table."""
        if active_workspace != "top-promotions":
            return None, "Select Top Promotions to read the committed rank."

        revision = int(data_revision or cache.revision)
        selected_signal = str(signal or "vol-score")
        with perf_span(
            app.logger,
            "risk.top_promotions.render",
            budget_ms=500,
            revision=revision,
            kind=selected_signal,
        ) as metrics:
            reporting_filters = reporting_filter_map(dimension_values)
            committed = cache.current(refresh_manager)
            filtered = apply_filters(
                committed,
                [],
                list(selected_splits or []),
                reporting_filters,
                exclude_selected=risk_exclude_selected(exclude_value),
            )
            active_generation = cache.resolve_promotion_generation(promotion_generation)
            filtered = apply_promotion_generation(
                filtered,
                active_generation,
                revision=revision,
            )
            metrics["rows"] = len(filtered)
            cache_key = json.dumps(
                {
                    "revision": revision,
                    "promotion_generation": (
                        active_generation.identifier
                        if active_generation is not None
                        and active_generation.kind == "current-view"
                        else None
                    ),
                    "splits": sorted(selected_splits or []),
                    "filters": {
                        key: sorted(selected or [])
                        for key, selected in sorted(reporting_filters.items())
                    },
                    "exclude_selected": risk_exclude_selected(exclude_value),
                    "signal": selected_signal,
                    "view": "top-promotions",
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            table = cache.rendered(
                cache_key,
                lambda: build_top_promotions_table(
                    filtered,
                    signal=selected_signal,
                ),
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
            Input("quick-search-combine-udl", "search_value"),
            Input("split-filter", "value"),
            Input("dimension-filter-values-store", "data"),
            Input("risk-filter-exclude-applied-store", "data"),
            State("quick-search-combine-udl", "value"),
            prevent_initial_call=False,
        )
        def load_combine_udl_options(
            active_workspace,
            _revision,
            search_value,
            selected_splits,
            dimension_values,
            exclude_value,
            current_value,
        ):
            if active_workspace != "quick-risk":
                return no_update, no_update
            selected_mode = "reported"

            try:
                options = _combine_udl_dropdown_options(
                    refresh_manager.search_combine_udl_options(
                        search_value,
                        identity_mode=selected_mode,
                        limit=100,
                        include=(str(current_value) if current_value else None),
                        risk_filters=quick_risk_filter_map(
                            selected_splits,
                            dimension_values,
                        ),
                        exclude_selected=risk_exclude_selected(exclude_value),
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

            values = {option["value"] for option in options}
            selected = str(current_value or "").strip()
            if selected in values:
                return options, no_update
            return options, (options[0]["value"] if options else None)

        @app.callback(
            Output("quick-search-results", "children"),
            Output("quick-search-dimensions", "value"),
            Input("quick-search-combine-udl", "value"),
            Input("quick-search-dimensions", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("split-filter", "value"),
            Input("dimension-filter-values-store", "data"),
            Input("risk-filter-exclude-applied-store", "data"),
            prevent_initial_call=True,
        )
        def render_current_pivot(
            combine_udl,
            index_columns,
            active_workspace,
            _revision,
            selected_splits,
            dimension_values,
            exclude_value,
        ):
            rendered, index_update = _render_quick_search_pivot(
                refresh_manager,
                combine_udl=combine_udl,
                identity_mode="reported",
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
            Input("quick-market-combine-udl", "value"),
            Input("quick-market-view", "value"),
            Input("quick-market-surface-metric", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            prevent_initial_call=True,
        )
        def render_market_search(
            combine_udl,
            requested_view,
            surface_metric,
            active_workspace,
            _revision,
        ):
            if active_workspace != "quick-market":
                return (
                    None,
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
                return (
                    rendered,
                    resolved,
                    options,
                    surface_options,
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
                )


__all__ = ["register_workspace_callbacks"]
