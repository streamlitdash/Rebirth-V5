"""V4 P&L filter ownership and aggregate-table callbacks."""

from __future__ import annotations

from threading import RLock
from typing import Callable

import pandas as pd
from dash import ALL, Dash, Input, Output, State, ctx, html, no_update

from rebirth.app.s02_contracts import RefreshManagerProtocol
from rebirth.ui.s02_aggregation import apply_filters, prepare_risk_data
from rebirth.ui.s01_constants import RISK_TYPE_ORDER
from rebirth.ui.s03_filters import (
    SavedFilterViewControls,
    saved_view_request_id,
    saved_view_request_matches_base,
    saved_view_request_values,
)

from .s01_common import (
    PL_AGGREGATE_HISTORY_CELL_TYPE,
    PL_AGGREGATE_TOGGLE_TYPE,
    PL_FILTER_FIELDS,
    PL_FILTER_IDS,
    pl_filter_map,
    pl_filter_options,
)
from .s07_view import build_pl_aggregate_table


def register_pl_aggregate_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol,
    *,
    prepared_frame_loader: Callable[[], pd.DataFrame | None] | None = None,
    saved_view_controls: SavedFilterViewControls | None = None,
) -> None:
    """Register P&L-local filters and the always-visible Aggregate P&L."""
    cache_lock = RLock()
    cached_revision = -1
    cached_frame: pd.DataFrame | None = None

    def current_aggregate_frame() -> pd.DataFrame | None:
        """Read only the mapped dashboard frame and prepare it once per revision."""
        nonlocal cached_frame, cached_revision
        if prepared_frame_loader is not None:
            return prepared_frame_loader()
        try:
            manager_revision = int(refresh_manager.health.revision)
        except Exception:
            manager_revision = -1
        if manager_revision <= 0:
            return None
        with cache_lock:
            if cached_frame is not None and cached_revision == manager_revision:
                return cached_frame

        try:
            dashboard = refresh_manager.read_frame("dashboard_frame")
        except RuntimeError:
            return None
        if dashboard.frame.empty:
            prepared = dashboard.frame.copy(deep=True)
        else:
            prepared = prepare_risk_data(dashboard.frame)
        with cache_lock:
            if int(dashboard.revision) >= cached_revision:
                cached_revision = int(dashboard.revision)
                cached_frame = prepared
            return cached_frame

    filter_outputs = [
        output
        for field in PL_FILTER_FIELDS
        for output in (
            Output(PL_FILTER_IDS[field.key], "options"),
            Output(PL_FILTER_IDS[field.key], "value"),
        )
    ]
    apply_inputs = (
        [Input(saved_view_controls.apply_request_id, "data")]
        if saved_view_controls is not None
        else []
    )
    apply_states = (
        [State(saved_view_controls.applied_request_id, "data")]
        if saved_view_controls is not None
        else []
    )

    @app.callback(
        *filter_outputs,
        Output("pnl-filter-exclude-selected", "value"),
        Input("data-revision-store", "data"),
        *apply_inputs,
        *[State(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        State("pnl-filter-exclude-selected", "value"),
        *apply_states,
    )
    def update_pl_filter_controls(_data_revision, *values):
        """Own all P&L filter values, including validated saved-view requests."""
        offset = 0
        request = None
        if saved_view_controls is not None:
            request = values[0]
            offset = 1
        selected_values = [
            list(selected or [])
            for selected in values[offset : offset + len(PL_FILTER_FIELDS)]
        ]
        exclude_value = list(values[offset + len(PL_FILTER_FIELDS)] or [])
        applied_saved_view_request = (
            values[offset + len(PL_FILTER_FIELDS) + 1]
            if saved_view_controls is not None
            else None
        )
        try:
            trigger = ctx.triggered_id
        except Exception:
            trigger = None
        request_id = saved_view_request_id(request)
        saved_view_pending = bool(
            request_id and request_id != applied_saved_view_request
        )
        request_matches_base = False
        if saved_view_pending and saved_view_controls is not None:
            try:
                request_matches_base = saved_view_request_matches_base(
                    request,
                    saved_view_controls,
                    selected_values,
                    exclude_value,
                )
            except ValueError:
                request_matches_base = False
        apply_pending = (
            saved_view_pending
            and saved_view_controls is not None
            and (
                trigger == saved_view_controls.apply_request_id or request_matches_base
            )
        )
        if apply_pending:
            try:
                applied = saved_view_request_values(request, saved_view_controls)
            except ValueError:
                applied = None
            if applied is not None:
                applied_values, exclude_value = applied
                selected_values = [list(selected) for selected in applied_values]

        frame = current_aggregate_frame()
        if frame is None:
            options = {field.key: [] for field in PL_FILTER_FIELDS}
            valid_values = selected_values
        else:
            options = pl_filter_options(frame)
            valid_values = []
            for field, selected in zip(
                PL_FILTER_FIELDS,
                selected_values,
                strict=True,
            ):
                available = {
                    str(option["value"]).casefold(): str(option["value"])
                    for option in options[field.key]
                }
                retained: list[str] = []
                for raw in selected:
                    value = available.get(str(raw).strip().casefold())
                    if value is not None and value not in retained:
                        retained.append(value)
                valid_values.append(retained)

        result: list[object] = []
        for field, selected in zip(
            PL_FILTER_FIELDS,
            valid_values,
            strict=True,
        ):
            result.extend((options[field.key], selected))
        result.append(exclude_value)
        return tuple(result)

    @app.callback(
        Output("pnl-aggregate-open-risk-types", "data"),
        Output("pnl-aggregate-pl-grid", "children"),
        Input("pnl-aggregate-pl-dimension", "value"),
        Input("data-revision-store", "data"),
        Input(
            {"type": PL_AGGREGATE_TOGGLE_TYPE, "risk_type": ALL},
            "n_clicks",
        ),
        *[Input(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        Input("pnl-filter-exclude-selected", "value"),
        State("pnl-aggregate-open-risk-types", "data"),
    )
    def reduce_and_render_pl_aggregate(
        dimension,
        _data_revision,
        row_clicks,
        *filter_values_mode_and_open,
    ):
        """Filter at position grain and reduce one P&L-local chevron."""
        selected_values = filter_values_mode_and_open[: len(PL_FILTER_FIELDS)]
        exclude_value = filter_values_mode_and_open[len(PL_FILTER_FIELDS)]
        effective_open = list(filter_values_mode_and_open[-1] or [])
        updated_open = no_update
        if row_clicks and max(int(value or 0) for value in row_clicks) > 0:
            triggered = ctx.triggered_id
            if isinstance(triggered, dict):
                risk_type = str(triggered.get("risk_type", "")).strip()
                if risk_type:
                    opened = set(effective_open)
                    if risk_type in opened:
                        opened.remove(risk_type)
                    else:
                        opened.add(risk_type)
                    effective_open = sorted(
                        opened,
                        key=lambda value: (RISK_TYPE_ORDER.get(value, 99), value),
                    )
                    updated_open = effective_open

        frame = current_aggregate_frame()
        if frame is None:
            return (
                updated_open,
                html.Div(
                    "P&L data is still loading. Aggregate P&L will update after the first committed refresh.",
                    className="empty-state",
                    role="status",
                ),
            )
        filtered = apply_filters(
            frame,
            None,
            None,
            pl_filter_map(selected_values),
            exclude_selected="exclude" in (exclude_value or []),
        )
        valid_types = (
            set(filtered["risk type"].astype(str)) if not filtered.empty else set()
        )
        valid_open = [value for value in effective_open if value in valid_types]
        if valid_open != effective_open:
            effective_open = valid_open
            updated_open = effective_open
        return (
            updated_open,
            build_pl_aggregate_table(filtered, dimension, effective_open),
        )

    @app.callback(
        Output("pl-history-selection-store", "data"),
        Input(
            {
                "type": PL_AGGREGATE_HISTORY_CELL_TYPE,
                "risk_type": ALL,
                "risk_greek": ALL,
                "dimension": ALL,
                "value": ALL,
            },
            "n_clicks",
        ),
        prevent_initial_call=True,
    )
    def select_pl_history_cell(clicks):
        """Turn a current Aggregate P&L cell into one lazy history request."""

        if not clicks or max(int(value or 0) for value in clicks) <= 0:
            return no_update
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            return no_update
        return {
            "risk_type": str(triggered.get("risk_type", "")).strip(),
            "risk_greek": str(triggered.get("risk_greek", "")).strip(),
            "dimension": str(triggered.get("dimension", "")).strip(),
            "value": str(triggered.get("value", "")).strip(),
        }


__all__ = ["register_pl_aggregate_callbacks"]
