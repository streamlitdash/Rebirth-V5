"""V5 Risk-page workspace callback ownership."""

from __future__ import annotations

from cube.ui.s08_refresh_views import refresh_view

import json

from dash import ALL, ClientsideFunction, Dash, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from cube.app.s03_logging import perf_span
from cube.ui.s02_aggregation import apply_filters
from .s16_quickriskcharts import build_quick_risk_chart
from cube.ui.s04_components import build_aggregate_pl_table
from cube.ui.s01_constants import (
    RISK_TYPE_ORDER,
)
from cube.app.s02_contracts import RefreshManagerProtocol

from .s01_common import quick_risk_filter_map, reporting_filter_map
from .s11_promotion import PROMOTION_GENERATION_STORE_ID, apply_promotion_generation
from .s09_quickmarket import (
    QUICK_MARKET_DEFAULT_INDEX,
    build_quick_market_result,
    quick_market_values_page,
)
from .s10_search import (
    _quick_search_label_index,
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
        Output('refresh-view-aggregate-pl', "data"),
        Input("aggregate-pl-dimension", "value"),
        Input("data-revision-store", "data"),
        Input("risk-initial-render-ready", "data"),
        Input({"type": "aggregate-row-toggle", "risk_type": ALL}, "n_clicks"),
        Input("split-filter", "value"),
        Input("dimension-filter-values-store", "data"),
        Input("risk-filter-exclude-applied-store", "data"),
        State("aggregate-open-risk-types", "data"),
        State("refresh-action-request", "data"),
    )
    @refresh_view('aggregate-pl', revision_arg='_data_revision', outputs=2, content=[1], stamp=[1])
    def reduce_and_render_aggregate_pl(
        dimension,
        _data_revision,
        risk_initial_render_ready,
        row_clicks,
        selected_splits,
        dimension_values,
        exclude_value,
        open_risk_types,
    ):
        """Apply shared filters, reduce a chevron, and render Aggregate P&L."""
        try:
            risk_render_revision = int(risk_initial_render_ready)
            data_revision = int(_data_revision or 0)
        except (TypeError, ValueError):
            raise PreventUpdate from None
        if risk_render_revision != data_revision:
            raise PreventUpdate
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

        filter_map = reporting_filter_map(dimension_values)
        render_key = json.dumps(
            {
                "view": "aggregate-pl",
                "revision": cache.revision,
                "dimension": dimension,
                "splits": sorted(selected_splits or []),
                "filters": {
                    key: sorted(selected or [])
                    for key, selected in sorted(filter_map.items())
                },
                "exclude_selected": risk_exclude_selected(exclude_value),
                "open_risk_types": effective_open_risk_types,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

        return (
            updated_open_risk_types,
            cache.rendered(
                render_key,
                lambda: build_aggregate_pl_table(
                    cache.filtered(
                        refresh_manager,
                        None,  # Aggregate includes every Risk Explorer tab.
                        None,  # Aggregate includes every IR family.
                        selected_splits,
                        filter_map,
                        exclude_selected=risk_exclude_selected(exclude_value),
                    ),
                    dimension,
                    effective_open_risk_types,
                ),
            ),
        )

    @app.callback(
        Output("top-promotions-grid", "children"),
        Output("top-promotions-status", "children"),
        Output('refresh-view-top-promotions', "data"),
        Input("risk-workspace-tabs", "value"),
        Input("data-revision-store", "data"),
        Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
        Input("split-filter", "value"),
        Input("dimension-filter-values-store", "data"),
        Input("risk-filter-exclude-applied-store", "data"),
        Input("top-promotions-signal", "value"),
        State("refresh-action-request", "data"),
    )
    @refresh_view('top-promotions', revision_arg='data_revision', outputs=2, content=[0], stamp=[0])
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

        # Only identity labels cross this boundary. Typing never calls Python.
        @app.callback(
            Output("quick-risk-search-index", "data"),
            Output("refresh-view-quick-risk-options", "data"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("split-filter", "value"),
            Input("dimension-filter-values-store", "data"),
            Input("risk-filter-exclude-applied-store", "data"),
            State("quick-risk-search-index", "data"),
            State("refresh-action-request", "data"),
        )
        @refresh_view('quick-risk-options', revision_arg='_revision', outputs=1, content=[0])
        def load_combine_udl_options(
            active_workspace, _revision, selected_splits, dimension_values,
            exclude_value, previous,
        ):
            if active_workspace != "quick-risk":
                return no_update
            filters = quick_risk_filter_map(selected_splits, dimension_values)
            exclude = risk_exclude_selected(exclude_value)
            key = json.dumps([_revision, filters, exclude], sort_keys=True)
            if isinstance(previous, dict) and previous.get("key") == key:
                return no_update
            labels = refresh_manager.combine_udl_options(
                identity_mode="reported", risk_filters=filters,
                exclude_selected=exclude,
            )
            if int(refresh_manager.health.revision) != int(_revision or 0):
                return no_update
            return {"key": key, "rows": _quick_search_label_index(labels)}

        app.clientside_callback(
            ClientsideFunction(namespace="quickSearch", function_name="options"),
            Output("quick-search-combine-udl", "options"),
            Output("quick-search-combine-udl", "value"),
            Input("quick-risk-search-index", "data"),
            Input("quick-search-combine-udl", "search_value"),
            State("quick-search-combine-udl", "value"),
        )

        @app.callback(
            Output("quick-search-results", "children"),
            Output("quick-search-dimensions", "value"),
            Output('refresh-view-quick-risk-table', "data"),
            Input("quick-search-combine-udl", "value"),
            Input("quick-search-dimensions", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("split-filter", "value"),
            Input("dimension-filter-values-store", "data"),
            Input("risk-filter-exclude-applied-store", "data"),
            State("refresh-action-request", "data"),
            prevent_initial_call=True,
        )
        @refresh_view('quick-risk-table', revision_arg='_revision', outputs=2, content=[0], stamp=[0])
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
            Output("quick-risk-tenor-result", "children"),
            Output('refresh-view-quick-risk-chart', "data"),
            Input("quick-search-combine-udl", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("split-filter", "value"),
            Input("dimension-filter-values-store", "data"),
            Input("risk-filter-exclude-applied-store", "data"),
            State("refresh-action-request", "data"),
        )
        @refresh_view('quick-risk-chart', revision_arg='revision', outputs=1, content=[0], stamp=[0])
        def render_quick_risk_tenor(
            combine_udl, active_workspace, revision,
            selected_splits, dimension_values, exclude_value,
        ):
            if active_workspace != "quick-risk":
                return None
            if not combine_udl:
                return None
            try:
                identity = refresh_manager.resolve_history_identity(
                    "risk", str(combine_udl), identity_mode="reported",
                )
                committed = cache.current(refresh_manager)
                if not (
                    int(revision or 0) == identity.source_revision == cache.revision
                ):
                    return no_update
                # Scope before filtering/copying. Never mutate the shared cache.
                scope = committed.loc[
                    committed["source type"].isin(identity.source_types)
                    & committed["risk type"].eq(identity.risk_type)
                    & committed["risk greek"].eq(identity.risk_greek)
                    & committed["reported underlying"].eq(identity.underlying)
                ]
                scope = apply_filters(
                    scope, [], list(selected_splits or []),
                    reporting_filter_map(dimension_values),
                    exclude_selected=risk_exclude_selected(exclude_value),
                )
                return build_quick_risk_chart(scope)
            except (AttributeError, KeyError, LookupError, TypeError, ValueError, RuntimeError) as error:
                app.logger.exception("Quick Risk chart failed")
                return html.Div(
                    f"Quick Risk chart unavailable: {error}", role="alert",
                )

        @app.callback(
            Output("quick-market-search-index", "data"),
            Output("refresh-view-quick-market-options", "data"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            State("quick-market-search-index", "data"),
            State("refresh-action-request", "data"),
        )
        @refresh_view('quick-market-options', revision_arg='_revision', outputs=1, content=[0])
        def load_market_udl_options(active_workspace, _revision, previous):
            if active_workspace != "quick-market":
                return no_update
            if isinstance(previous, dict) and previous.get("key") == _revision:
                return no_update
            labels = refresh_manager.market_udl_options()
            if int(refresh_manager.health.revision) != int(_revision or 0):
                return no_update
            return {"key": _revision, "rows": _quick_search_label_index(labels)}

        app.clientside_callback(
            ClientsideFunction(namespace="quickSearch", function_name="options"),
            Output("quick-market-combine-udl", "options"),
            Output("quick-market-combine-udl", "value"),
            Input("quick-market-search-index", "data"),
            Input("quick-market-combine-udl", "search_value"),
            State("quick-market-combine-udl", "value"),
        )

        @app.callback(
            Output("quick-market-surface-metric-control", "hidden"),
            Input("quick-market-view", "value"),
            Input("quick-market-view", "options"),
        )
        def show_market_surface_metric(requested_view, options):
            surface_available = any(
                option.get("value") == "surface" and not option.get("disabled", False)
                for option in (options or [])
            )
            return not (requested_view == "surface" or (requested_view == "auto" and surface_available))

        @app.callback(
            Output("quick-market-results", "children"),
            Output("quick-market-view", "value"),
            Output("quick-market-view", "options"),
            Output("quick-market-surface-metric", "options"),
            Output("quick-market-values", "data"),
            Output("quick-market-values", "columns"),
            Output("quick-market-values", "page_count"),
            Output("quick-market-values", "page_current"),
            Output('refresh-view-quick-market', "data"),
            Input("quick-market-combine-udl", "value"),
            Input("quick-market-view", "value"),
            Input("quick-market-surface-metric", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("quick-market-values", "page_current"),
            State("refresh-action-request", "data"),
            prevent_initial_call=True,
        )
        @refresh_view('quick-market', revision_arg='_revision', outputs=8, content=[0], stamp=[0])
        def render_market_search(
            combine_udl, requested_view, surface_metric, active_workspace,
            _revision, page_current,
        ):
            if active_workspace != "quick-market":
                return None, no_update, no_update, no_update, [], [], 0, 0
            selected = str(combine_udl or "").strip()
            if not selected:
                return (
                    html.Div("Select a Market identity to build its full tenor view.", className="quick-search-hint"),
                    no_update, no_update, no_update, [], [], 0, 0,
                )
            try:
                result = refresh_manager.pivot_market_exact(selected, index_columns=QUICK_MARKET_DEFAULT_INDEX)
                if int(result.revision) != int(_revision or 0):
                    # The independent revision publisher will request a coherent redraw.
                    return (no_update,) * 8
                statuses = result.frame["Market Status"].dropna().unique() if not result.frame.empty else []
                if not result.frame.empty and len(statuses) != 1:
                    raise ValueError("exact MarketBook result has an ambiguous Market Status")
                selected_status = str(statuses[0]) if len(statuses) else "Current"
                page_only = set(ctx.triggered_prop_ids) == {"quick-market-values.page_current"}
                requested_page = page_current if page_only else 0
                records, columns, pages, resolved_page = quick_market_values_page(
                    result.frame, requested_page, market_status=selected_status,
                )
                if page_only:
                    return no_update, no_update, no_update, no_update, records, columns, pages, resolved_page
                rendered, resolved, options, surface_options = build_quick_market_result(
                    result.frame, combine_udl=selected,
                    requested_view=str(requested_view or "auto"),
                    surface_metric=str(surface_metric or "current"),
                    market_status=selected_status, revision=int(result.revision),
                    include_values=False,
                )
                # Resolving Auto is internal; changing this Input would render twice.
                control = "auto" if requested_view == "auto" else resolved
                control_update = no_update if control == requested_view else control
                return rendered, control_update, options, surface_options, records, columns, pages, resolved_page
            except (AttributeError, KeyError, LookupError, TypeError, ValueError, RuntimeError) as error:
                app.logger.exception("Quick Market Search render failed")
                detail = " ".join(str(error).splitlines()).strip() or type(error).__name__
                return (
                    html.Div(f"Quick Market Search failed: {type(error).__name__}: {detail[:400]}", className="quick-search-error", role="alert"),
                    no_update, no_update, no_update, [], [], 0, 0,
                )

__all__ = ["register_workspace_callbacks"]
