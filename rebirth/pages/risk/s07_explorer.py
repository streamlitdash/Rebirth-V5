"""V4 Risk Explorer callback ownership."""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

import pandas as pd
from dash import Dash, Input, Output, State, ctx, dcc, no_update
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from rebirth.ui.s02_aggregation import (
    apply_credit_measure,
    default_open_rows,
    filter_ir_family,
    ordered_unique,
    parse_row_key,
    row_key,
    selected_underlying_sort_metric,
)
from rebirth.ui.s01_constants import (
    CREDIT_MEASURES,
    DETAIL_COMPONENT_LABELS,
    DETAIL_COMPONENTS,
    DIMENSION_FILTER_IDS,
    EXPANDABLE_METRICS,
    FILTER_DIMENSION_FIELDS,
    METRIC_COLUMNS,
    PLOT_METRICS,
    compose_detail_metric,
    split_detail_metric,
)
from rebirth.app.s02_contracts import RefreshManagerProtocol
from rebirth.ui.s03_filters import (
    BASE_SAVED_VIEW_ID,
    saved_view_request_id,
    saved_view_request_matches_base,
    saved_view_request_values,
)

from .s05_charts import build_detail_panel_with_state
from .s01_common import RISK_SAVED_VIEW_CONTROLS, reporting_filter_map
from .s03_defaults import default_risk_filter_values
from .s11_promotion import PROMOTION_GENERATION_STORE_ID
from .s02_state import (
    CLEAR_CACHE_COMPLETE_STORE_ID,
    _is_current_risk_action,
    _new_trade_detail_requested,
    _new_trade_details_for_selection,
    _RiskDataCache,
    _valid_delegated_row_key,
    filter_unmapped_portfolios,
    risk_action_view_token,
    risk_exclude_selected,
)
from .s06_explorertables import (
    build_alt_risk_table,
    build_credit_multi_table,
    build_risk_table,
)
from .s15_workspacetables import NEW_TRADE_SPLIT
from .s18_view import build_unmapped_books_table


def register_explorer_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol | None,
    cache: _RiskDataCache,
    dimension_filter_ids: Sequence[str],
    dimension_filter_inputs: Sequence[Any],
) -> None:
    """Register Cross, Split VA, detail, filters, and tree interactions."""

    @app.callback(
        Output("dimension-filter-store", "data"),
        Output("dimension-filter-values-store", "data"),
        *dimension_filter_inputs,
    )
    def sync_dimension_filters(*filter_values):
        """Sync filter dropdown values to both filter stores."""
        return (
            dict(
                zip(
                    (field.key for field in FILTER_DIMENSION_FIELDS),
                    filter_values,
                    strict=True,
                )
            ),
            list(filter_values),
        )

    @app.callback(
        Output("risk-type-tabs", "children"),
        Output("risk-type-tabs", "value"),
        Input("data-revision-store", "data"),
        State("risk-type-tabs", "value"),
    )
    def update_risk_type_tabs(_revision, selected_risk_type):
        available = ordered_unique(cache.current(refresh_manager), "risk type")
        if not available:
            return [], None
        selected = (
            selected_risk_type if selected_risk_type in available else available[0]
        )
        return [dcc.Tab(label=value, value=value) for value in available], selected

    @app.callback(
        *[
            output
            for component_id in dimension_filter_ids
            for output in (
                Output(component_id, "options"),
                Output(component_id, "value"),
            )
        ],
        Output("risk-filter-exclude-selected", "value"),
        Input("data-revision-store", "data"),
        Input(RISK_SAVED_VIEW_CONTROLS.apply_request_id, "data"),
        Input(CLEAR_CACHE_COMPLETE_STORE_ID, "data", allow_optional=True),
        *[State(component_id, "value") for component_id in dimension_filter_ids],
        State("risk-filter-exclude-selected", "value"),
        State(RISK_SAVED_VIEW_CONTROLS.applied_request_id, "data"),
    )
    def update_dimension_filters(
        _revision,
        saved_view_request,
        _clear_cache_complete,
        *values,
    ):
        frame = cache.current(refresh_manager)
        selected_values = values[: len(dimension_filter_ids)]
        exclude_value = values[len(dimension_filter_ids)]
        applied_saved_view_request = values[len(dimension_filter_ids) + 1]
        try:
            saved_view_triggered = (
                ctx.triggered_id == RISK_SAVED_VIEW_CONTROLS.apply_request_id
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
                    RISK_SAVED_VIEW_CONTROLS,
                    selected_values,
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
                    RISK_SAVED_VIEW_CONTROLS,
                )
            except ValueError:
                requested = None
            if requested is not None:
                selected_values, exclude_value = requested
        try:
            filter_triggered_ids = set(ctx.triggered_prop_ids.values())
        except (AttributeError, LookupError, MissingCallbackContextException):
            filter_triggered_ids = {ctx.triggered_id}
        use_default = CLEAR_CACHE_COMPLETE_STORE_ID in filter_triggered_ids or (
            apply_pending
            and isinstance(saved_view_request, Mapping)
            and saved_view_request.get("view_id") == BASE_SAVED_VIEW_ID
        )
        if use_default:
            selected_values = default_risk_filter_values(frame)
            exclude_value = []

        def options_and_valid(column, selected):
            available = ordered_unique(frame, column)
            valid = [value for value in (selected or []) if value in available]
            return [{"label": value, "value": value} for value in available], valid

        result = []
        for field, selected in zip(
            FILTER_DIMENSION_FIELDS,
            selected_values,
            strict=True,
        ):
            options, valid = options_and_valid(field.key, selected)
            result.extend((options, valid))
        return (*result, exclude_value or [])

    app.clientside_callback(
        """
        function (activeRiskType) {
            return activeRiskType === "IR" ? {} : {display: "none"};
        }
        """,
        Output("ir-family-tabs", "style"),
        Input("risk-type-tabs", "value"),
    )

    def risk_generation_state(
        *,
        splits,
        dimension_values,
        exclude_selected,
        credit_measure,
        credit_multi_metric,
        alt_metric,
        expanded_metrics,
        promotion_enabled,
        promotion_generation,
        region_enabled,
        underlying_sort_metric,
    ) -> dict[str, Any]:
        """Return every value-affecting input embedded in delegated actions."""
        filters = reporting_filter_map(dimension_values)
        return {
            "alt_metric": alt_metric,
            "credit_measure": credit_measure,
            "credit_multi_metric": credit_multi_metric,
            "expanded_metrics": sorted(expanded_metrics or []),
            "filters": {key: sorted(values) for key, values in sorted(filters.items())},
            "exclude_selected": bool(exclude_selected),
            "splits": sorted(splits or []),
            "promotion_enabled": bool(promotion_enabled),
            "promotion_generation": (
                promotion_generation.get("id")
                if isinstance(promotion_generation, Mapping)
                else None
            ),
            "region_enabled": bool(region_enabled),
            "underlying_sort_metric": selected_underlying_sort_metric(
                underlying_sort_metric
            ),
        }

    def render_active_risk_table(
        *,
        active_risk_type,
        ir_family,
        data_revision,
        table_view,
        dimension,
        underlying_sort_metric,
        splits,
        expanded_metrics,
        credit_view,
        credit_measure,
        credit_multi_metric,
        alt_metric,
        open_rows,
        dimension_values,
        exclude_selected=False,
        promotion_enabled=True,
        promotion_generation=None,
        region_enabled=True,
    ):
        """Build only the visible Risk Explorer table for the current state."""
        normalized_ir_family = ir_family if active_risk_type == "IR" else None
        selected_sort_metric = selected_underlying_sort_metric(underlying_sort_metric)
        risk_context = {
            "risk_type": active_risk_type,
            "ir_family": normalized_ir_family,
            "data_revision": data_revision,
        }
        reporting_filters = reporting_filter_map(dimension_values)
        generation_state = risk_generation_state(
            splits=splits,
            dimension_values=dimension_values,
            credit_measure=credit_measure,
            credit_multi_metric=credit_multi_metric,
            alt_metric=alt_metric,
            expanded_metrics=expanded_metrics,
            exclude_selected=exclude_selected,
            promotion_enabled=promotion_enabled,
            promotion_generation=promotion_generation,
            region_enabled=region_enabled,
            underlying_sort_metric=selected_sort_metric,
        )

        def filtered_frame() -> pd.DataFrame:
            return cache.filtered(
                refresh_manager,
                active_risk_type,
                normalized_ir_family,
                splits,
                reporting_filters,
                exclude_selected=exclude_selected,
                promotion_generation=promotion_generation,
            )

        if table_view == "custom":
            return no_update, no_update

        if table_view == "alt":
            view_token = risk_action_view_token(
                risk_context,
                table_view,
                dimension,
                None,
                generation_state=generation_state,
            )
            render_key = json.dumps(
                [view_token, sorted(open_rows or [])],
                separators=(",", ":"),
            )

            def build_alt_component():
                filtered = filtered_frame()
                if active_risk_type == "Credit":
                    filtered = apply_credit_measure(filtered, credit_measure)
                return build_alt_risk_table(
                    filtered,
                    alt_metric,
                    open_rows,
                    dimension,
                    index_label=active_risk_type,
                    view_token=view_token,
                    promotion_enabled=promotion_enabled,
                    region_enabled=region_enabled,
                    underlying_sort_metric=selected_sort_metric,
                )

            return no_update, cache.rendered(render_key, build_alt_component)

        view_token = risk_action_view_token(
            risk_context,
            table_view,
            dimension,
            credit_view,
            generation_state=generation_state,
        )
        render_key = json.dumps(
            [view_token, sorted(open_rows or []), promotion_enabled, region_enabled],
            separators=(",", ":"),
        )

        def build_main_component():
            filtered = filtered_frame()
            if active_risk_type == "Credit" and credit_view == "multi":
                return build_credit_multi_table(
                    filtered,
                    credit_multi_metric,
                    open_rows,
                    dimension,
                    view_token,
                    promotion_enabled=promotion_enabled,
                    region_enabled=region_enabled,
                    underlying_sort_metric=selected_sort_metric,
                )
            if active_risk_type == "Credit":
                filtered = apply_credit_measure(filtered, credit_measure)
            return build_risk_table(
                filtered,
                expanded_metrics,
                open_rows,
                dimension=dimension,
                toggle_type="main-row-toggle",
                cell_type="main-risk-cell",
                index_label=active_risk_type,
                view_token=view_token,
                promotion_enabled=promotion_enabled,
                region_enabled=region_enabled,
                underlying_sort_metric=selected_sort_metric,
            )

        return cache.rendered(render_key, build_main_component), no_update

    def render_active_detail(
        *,
        active_risk_type,
        ir_family,
        splits,
        table_view,
        credit_view,
        credit_measure,
        selection,
        plot_measure,
        plot_component,
        tenor_view,
        dimension_values,
        exclude_selected=False,
        promotion_generation=None,
    ):
        """Build the current detail, short-circuiting the empty state."""
        if not selection:
            return build_detail_panel_with_state(
                pd.DataFrame(),
                None,
                compose_detail_metric(plot_measure, plot_component),
                tenor_view,
            )
        selected_context = parse_row_key(selection.get("key"))
        detail_risk_type = selected_context.get("risk type", active_risk_type)
        filtered = cache.filtered(
            refresh_manager,
            detail_risk_type,
            ir_family,
            splits,
            reporting_filter_map(dimension_values),
            exclude_selected=exclude_selected,
            promotion_generation=promotion_generation,
        )
        selected_credit_measure = selection.get("credit_measure")
        if detail_risk_type == "Credit" and selected_credit_measure:
            filtered = apply_credit_measure(filtered, selected_credit_measure)
        elif detail_risk_type == "Credit" and (
            table_view == "alt" or credit_view == "single"
        ):
            filtered = apply_credit_measure(filtered, credit_measure)

        filtered_splits = (
            set(filtered["split"].dropna().astype(str))
            if "split" in filtered
            else set()
        )
        new_trades_selected = _new_trade_detail_requested(
            selected_context, splits
        ) or filtered_splits == {NEW_TRADE_SPLIT}
        detail_selection = selection
        if new_trades_selected and "split" not in selected_context:
            detail_selection = dict(selection)
            detail_selection["key"] = row_key(
                {**selected_context, "split": NEW_TRADE_SPLIT}
            )

        new_trade_details = None
        if new_trades_selected:
            combined = refresh_manager.read_frame("combined_pl").frame
            detail_context = parse_row_key(detail_selection.get("key"))
            new_trade_details = _new_trade_details_for_selection(
                combined,
                detail_context,
                detail_risk_type,
                ir_family,
                splits,
                reporting_filter_map(dimension_values),
                exclude_selected=exclude_selected,
                promotion_generation=promotion_generation,
                revision=int(cache.revision),
            )
        return build_detail_panel_with_state(
            filtered,
            detail_selection,
            compose_detail_metric(plot_measure, plot_component),
            tenor_view,
            new_trade_details=new_trade_details,
        )

    @app.callback(
        Output("split-filter", "options"),
        Output("split-filter", "value"),
        Output("open-rows-store", "data"),
        Output("selected-cell-store", "data"),
        Output("plot-measure", "value"),
        Output("detail-component-request-store", "data"),
        Output("risk-view-context-store", "data"),
        Output("plot-component", "options"),
        Output("plot-component", "value"),
        Output("detail-tenor-view", "options"),
        Output("detail-tenor-view", "value"),
        Output("expanded-metrics", "value"),
        Output("risk-grid", "children"),
        Output("alt-risk-grid", "children"),
        Output("detail-panel", "children"),
        Input("risk-type-tabs", "value"),
        Input("ir-family-tabs", "value"),
        Input("data-revision-store", "data"),
        Input("table-dimension", "value"),
        Input("table-view-tabs", "value"),
        Input("credit-view-tabs", "value"),
        Input("risk-row-action-store", "data"),
        Input("risk-cell-action-store", "data"),
        Input("risk-metric-action-store", "data"),
        Input("split-filter", "value"),
        Input("credit-measure", "value"),
        Input("credit-multi-metric", "value"),
        Input("alt-metric", "value"),
        Input("plot-measure", "value"),
        Input("plot-component", "value"),
        Input("detail-tenor-view", "value"),
        Input("dimension-filter-values-store", "data"),
        Input("risk-filter-exclude-selected", "value"),
        Input("promotion-toggle-store", "data"),
        Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
        Input("region-toggle-store", "data"),
        Input("underlying-sort-metric", "value"),
        State("open-rows-store", "data"),
        State("expanded-metrics", "value"),
        State("risk-view-context-store", "data"),
        State("selected-cell-store", "data"),
    )
    def reduce_and_render_risk_view(
        active_risk_type,
        ir_family,
        data_revision,
        dimension,
        table_view,
        credit_view,
        row_action,
        cell_action,
        metric_action,
        selected_splits,
        credit_measure,
        credit_multi_metric,
        alt_metric,
        plot_measure,
        plot_component,
        tenor_view,
        dimension_values,
        exclude_value,
        promotion_enabled,
        promotion_generation,
        region_enabled,
        underlying_sort_metric,
        current_open_rows,
        current_expanded_metrics,
        previous_context,
        current_selection,
    ):
        """Atomically reduce an interaction and return its visible table.

        Dash Cloud latency used to be paid twice: once to update a Store and
        again to render the table from that Store.  This callback is the sole
        owner of Risk Explorer state *and* its two table containers, so tab,
        row, metric and filter interactions each require one server request.
        """
        dimension_values = dimension_values or []
        exclude_selected = risk_exclude_selected(exclude_value)
        normalized_ir_family = ir_family if active_risk_type == "IR" else None
        context = {
            "risk_type": active_risk_type,
            "ir_family": normalized_ir_family,
            "data_revision": data_revision,
        }
        triggered = set(ctx.triggered_prop_ids)
        context_inputs = {
            "risk-type-tabs.value",
            "ir-family-tabs.value",
            "data-revision-store.data",
        }
        view_inputs = {
            "table-dimension.value",
            "table-view-tabs.value",
            "credit-view-tabs.value",
        }
        table_inputs = {
            "split-filter.value",
            "credit-measure.value",
            "credit-multi-metric.value",
            "alt-metric.value",
            "dimension-filter-values-store.data",
            "risk-filter-exclude-selected.value",
            "promotion-toggle-store.data",
            f"{PROMOTION_GENERATION_STORE_ID}.data",
            "region-toggle-store.data",
            "underlying-sort-metric.value",
        }
        detail_inputs = {
            "plot-measure.value",
            "plot-component.value",
            "detail-tenor-view.value",
        }

        updates = [no_update] * 12
        effective_splits = list(selected_splits or [])
        effective_open_rows = list(current_open_rows or [])
        effective_expanded_metrics = list(current_expanded_metrics or [])
        effective_selection = current_selection
        effective_plot_measure = (
            plot_measure if plot_measure in DETAIL_COMPONENTS else "risk"
        )
        allowed_components = DETAIL_COMPONENTS[effective_plot_measure]
        default_component = "move" if effective_plot_measure == "move" else "total"
        effective_plot_component = (
            plot_component
            if plot_component in allowed_components
            else default_component
        )
        effective_tenor_view = (
            tenor_view
            if tenor_view in {"auto", "tenor", "swap", "option", "surface"}
            else "auto"
        )
        should_render_table = False
        should_render_detail = False

        if triggered & context_inputs or not isinstance(previous_context, Mapping):
            frame = cache.current(refresh_manager)
            frame = frame.loc[frame["risk type"].eq(active_risk_type)]
            frame = filter_ir_family(frame, active_risk_type, normalized_ir_family)
            available = ordered_unique(frame, "split")
            effective_splits = [
                split for split in effective_splits if split in available
            ]
            context_changed = (
                not isinstance(previous_context, Mapping)
                or previous_context.get("risk_type") != active_risk_type
                or previous_context.get("ir_family") != normalized_ir_family
            )
            updates[0] = [{"label": split, "value": split} for split in available]
            updates[1] = effective_splits
            if context_changed:
                effective_open_rows = default_open_rows(frame, active_risk_type)
                effective_selection = None
                effective_plot_measure = "risk"
                effective_plot_component = "total"
                effective_tenor_view = "auto"
                updates[2] = effective_open_rows
                updates[3] = None
                updates[4] = "risk"
                updates[5] = {"measure": "risk", "component": "total"}
                updates[7] = [
                    {
                        "label": DETAIL_COMPONENT_LABELS[value],
                        "value": value,
                    }
                    for value in DETAIL_COMPONENTS["risk"]
                ]
                updates[8] = "total"
            updates[6] = context
            should_render_table = True
            should_render_detail = True

        elif triggered & view_inputs:
            effective_selection = None
            effective_plot_measure = "risk"
            effective_plot_component = "total"
            effective_tenor_view = "auto"
            updates[3] = None
            updates[4] = "risk"
            updates[5] = {"measure": "risk", "component": "total"}
            updates[7] = [
                {"label": DETAIL_COMPONENT_LABELS[value], "value": value}
                for value in DETAIL_COMPONENTS["risk"]
            ]
            updates[8] = "total"
            should_render_table = True
            should_render_detail = True

        else:
            expected_token = risk_action_view_token(
                context,
                table_view,
                dimension,
                credit_view,
                generation_state=risk_generation_state(
                    splits=effective_splits,
                    dimension_values=dimension_values,
                    exclude_selected=exclude_selected,
                    credit_measure=credit_measure,
                    credit_multi_metric=credit_multi_metric,
                    alt_metric=alt_metric,
                    expanded_metrics=effective_expanded_metrics,
                    promotion_enabled=bool(promotion_enabled),
                    promotion_generation=promotion_generation,
                    region_enabled=bool(region_enabled),
                    underlying_sort_metric=selected_underlying_sort_metric(
                        underlying_sort_metric
                    ),
                ),
            )
            if ctx.triggered_id == "risk-row-action-store":
                if not _is_current_risk_action(
                    row_action,
                    kind="row",
                    expected_view_token=expected_token,
                ):
                    raise PreventUpdate
                expected_source = (
                    "alt-row-toggle" if table_view == "alt" else "main-row-toggle"
                )
                key = row_action.get("key")
                opened = row_action.get("open_rows")
                if (
                    row_action.get("source") != expected_source
                    or not _valid_delegated_row_key(key, allow_total=False)
                    or not isinstance(opened, list)
                    or any(
                        not _valid_delegated_row_key(item, allow_total=False)
                        for item in opened
                    )
                ):
                    raise PreventUpdate
                effective_open_rows = sorted(set(opened))
                updates[2] = effective_open_rows
                should_render_table = True

            elif ctx.triggered_id == "risk-metric-action-store":
                if not _is_current_risk_action(
                    metric_action,
                    kind="metric",
                    expected_view_token=expected_token,
                ):
                    raise PreventUpdate
                metric = metric_action.get("metric")
                if table_view != "main" or metric not in EXPANDABLE_METRICS:
                    raise PreventUpdate
                expanded = set(effective_expanded_metrics)
                if metric in expanded:
                    expanded.remove(metric)
                else:
                    expanded.add(metric)
                effective_expanded_metrics = [
                    name for name in EXPANDABLE_METRICS if name in expanded
                ]
                updates[11] = effective_expanded_metrics
                should_render_table = True

            elif ctx.triggered_id == "risk-cell-action-store":
                action = cell_action
                source = action.get("source") if isinstance(action, Mapping) else None
                if not _is_current_risk_action(
                    action,
                    kind="cell",
                    expected_view_token=expected_token,
                ):
                    raise PreventUpdate
                if table_view == "alt":
                    expected_source = "alt-risk-cell"
                elif active_risk_type == "Credit" and credit_view == "multi":
                    expected_source = "credit-risk-cell"
                else:
                    expected_source = "main-risk-cell"
                if source != expected_source:
                    raise PreventUpdate
                allowed_metrics = (
                    METRIC_COLUMNS
                    if source in {"alt-risk-cell", "credit-risk-cell"}
                    else PLOT_METRICS
                )

                metric = action.get("metric")
                key = action.get("key")
                if metric not in allowed_metrics or not _valid_delegated_row_key(
                    key,
                    allow_total=True,
                ):
                    raise PreventUpdate
                selection = {"key": key, "metric": metric, "source": source}
                if source == "credit-risk-cell":
                    selected_credit_measure = action.get("measure")
                    if selected_credit_measure not in CREDIT_MEASURES:
                        raise PreventUpdate
                    selection["credit_measure"] = selected_credit_measure
                elif action.get("measure") is not None:
                    raise PreventUpdate
                measure, component = split_detail_metric(metric)
                effective_selection = selection
                effective_plot_measure = measure
                effective_plot_component = component
                effective_tenor_view = "auto"
                updates[3] = selection
                updates[4] = measure
                updates[5] = {"measure": measure, "component": component}
                updates[7] = [
                    {
                        "label": DETAIL_COMPONENT_LABELS[value],
                        "value": value,
                    }
                    for value in DETAIL_COMPONENTS[measure]
                ]
                updates[8] = component
                should_render_detail = True

            elif "plot-measure.value" in triggered:
                effective_plot_measure = (
                    plot_measure if plot_measure in DETAIL_COMPONENTS else "risk"
                )
                effective_plot_component = (
                    "move" if effective_plot_measure == "move" else "total"
                )
                updates[7] = [
                    {
                        "label": DETAIL_COMPONENT_LABELS[value],
                        "value": value,
                    }
                    for value in DETAIL_COMPONENTS[effective_plot_measure]
                ]
                updates[8] = effective_plot_component
                should_render_detail = True

            elif "plot-component.value" in triggered:
                should_render_detail = True

            elif triggered & table_inputs:
                should_render_table = True
                should_render_detail = bool(effective_selection)
            elif triggered & detail_inputs:
                should_render_detail = True
            else:
                raise PreventUpdate

        main_grid = no_update
        alt_grid = no_update
        if should_render_table:
            main_grid, alt_grid = render_active_risk_table(
                active_risk_type=active_risk_type,
                ir_family=normalized_ir_family,
                data_revision=data_revision,
                table_view=table_view,
                dimension=dimension,
                underlying_sort_metric=underlying_sort_metric,
                splits=effective_splits,
                expanded_metrics=effective_expanded_metrics,
                credit_view=credit_view,
                credit_measure=credit_measure,
                credit_multi_metric=credit_multi_metric,
                alt_metric=alt_metric,
                open_rows=effective_open_rows,
                dimension_values=dimension_values,
                exclude_selected=exclude_selected,
                promotion_enabled=bool(promotion_enabled),
                promotion_generation=promotion_generation,
                region_enabled=bool(region_enabled),
            )
        detail_panel = no_update
        if should_render_detail:
            (
                detail_panel,
                detail_tenor_options,
                effective_tenor_view,
            ) = render_active_detail(
                active_risk_type=active_risk_type,
                ir_family=normalized_ir_family,
                splits=effective_splits,
                table_view=table_view,
                credit_view=credit_view,
                credit_measure=credit_measure,
                selection=effective_selection,
                plot_measure=effective_plot_measure,
                plot_component=effective_plot_component,
                tenor_view=effective_tenor_view,
                dimension_values=dimension_values,
                exclude_selected=exclude_selected,
                promotion_generation=promotion_generation,
            )
            updates[9] = detail_tenor_options
            updates[10] = effective_tenor_view
        return (
            *updates,
            main_grid,
            alt_grid,
            detail_panel,
        )

    @app.callback(
        Output("unmapped-books-details", "open"),
        Output("unmapped-books-grid", "children"),
        Input("unmapped-books-summary", "n_clicks"),
        Input("data-revision-store", "data"),
        Input(DIMENSION_FILTER_IDS["portfolio"], "value"),
        Input("risk-filter-exclude-selected", "value"),
        State("unmapped-books-details", "open"),
        prevent_initial_call=True,
    )
    def render_unmapped_books(
        _summary_clicks,
        _revision,
        selected_portfolios,
        exclude_value,
        is_open,
    ):
        """Load the complete unmapped-book inventory only while it is open."""
        open_update = (
            not bool(is_open)
            if ctx.triggered_id == "unmapped-books-summary"
            else bool(is_open)
        )
        if not open_update:
            return False, None
        frame = (
            refresh_manager.read_frame("unmapped_frame").frame
            if refresh_manager is not None
            else pd.DataFrame()
        )
        frame = filter_unmapped_portfolios(
            frame,
            selected_portfolios,
            exclude_selected=risk_exclude_selected(exclude_value),
        )
        return True, build_unmapped_books_table(frame)

    app.clientside_callback(
        """
        function (view) {
            if (view === "alt") {
                return [{display: "none"}, {}, {display: "none"}, {}];
            }
            if (view === "custom") {
                return [{display: "none"}, {display: "none"}, {}, {display: "none"}];
            }
            return [{}, {display: "none"}, {display: "none"}, {display: "none"}];
        }
        """,
        Output("main-risk-panel", "style"),
        Output("alt-risk-panel", "style"),
        Output("custom-risk-panel", "style"),
        Output("alt-metric-control", "style"),
        Input("table-view-tabs", "value"),
    )

    app.clientside_callback(
        """
        function (activeRiskType, tableView, creditView) {
            const hidden = {display: "none"};
            if (activeRiskType !== "Credit") {
                return [hidden, hidden, hidden, hidden];
            }
            if (tableView === "alt") {
                return [{}, hidden, {}, hidden];
            }
            if (creditView === "multi") {
                return [{}, {}, hidden, {}];
            }
            return [{}, {}, {}, hidden];
        }
        """,
        Output("credit-view-controls", "style"),
        Output("credit-view-tabs", "style"),
        Output("credit-single-control", "style"),
        Output("credit-multi-control", "style"),
        Input("risk-type-tabs", "value"),
        Input("table-view-tabs", "value"),
        Input("credit-view-tabs", "value"),
    )


__all__ = ["register_explorer_callbacks"]
