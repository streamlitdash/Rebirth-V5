"""P&L-page filter ownership and historical summary callbacks."""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping
from threading import RLock
from typing import Callable

import pandas as pd
from dash import ALL, Dash, Input, Output, State, ctx, html, no_update
from dash.exceptions import PreventUpdate

from cube.app.s02_contracts import RefreshManagerProtocol
from cube.domain.s08_pnl import PLSendValidationError
from cube.history import PLRiskSummaryResult
from cube.ui.s02_aggregation import prepare_risk_data
from cube.ui.s03_filters import (
    BASE_SAVED_VIEW_ID,
    SavedFilterViewControls,
    saved_view_request_id,
    saved_view_request_matches_base,
    saved_view_request_values,
)

from .s01_common import (
    PL_FILTER_FIELDS,
    PL_FILTER_IDS,
    PL_SUMMARY_HISTORY_CELL_TYPE,
    PL_SUMMARY_TOGGLE_TYPE,
    PL_SAVED_VIEW_CONTROLS,
    PLRiskSummaryQueryProtocol,
    committed_pl_filter_values,
    pl_cache_generation,
    pl_external_filter_map,
    pl_filter_options,
)
from .s10_summary import (
    PL_SUMMARY_PAGE_TYPE,
    build_pl_summary_table,
    decode_open_paths,
)


_BASE_ACTIVITY_ALIASES = (
    ("activity 1", "macro"),
    ("activity 2", "credit"),
    ("activity 3", "hedge"),
)
_TEMP_ACTIVITY_PREFIX = "temp_replace_me - "


def _base_pl_filter_values(frame: pd.DataFrame) -> list[list[str]]:
    """Resolve the P&L Base view against the current Activity labels."""

    matches = {alias: [] for aliases in _BASE_ACTIVITY_ALIASES for alias in aliases}
    for raw in frame["activity"].dropna().astype(str).unique():
        value = str(raw).strip()
        key = " ".join(unicodedata.normalize("NFKC", value).split()).casefold()
        if key.startswith(_TEMP_ACTIVITY_PREFIX):
            key = key[len(_TEMP_ACTIVITY_PREFIX) :]
        if key in matches:
            matches[key].append(value)
    activities = [
        value
        for aliases in _BASE_ACTIVITY_ALIASES
        for alias in aliases
        for value in matches[alias]
    ]
    return [activities if field.key == "activity" else [] for field in PL_FILTER_FIELDS]


def _ordered_open_tokens(raw: object) -> list[str]:
    """Return validated, stable browser-owned hierarchy tokens."""

    return sorted(
        (
            json.dumps(list(path), separators=(",", ":"))
            for path in decode_open_paths(raw)
        ),
        key=str.casefold,
    )


def register_pl_aggregate_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol,
    *,
    history_source: object = None,
    prepared_frame_loader: Callable[[], pd.DataFrame | None] | None = None,
    saved_view_controls: SavedFilterViewControls | None = None,
) -> None:
    """Register the P&L page's filters and independent historical hierarchy."""

    cache_lock = RLock()
    cached_revision = -1
    cached_frame: pd.DataFrame | None = None
    cleared_cache_generation = 0
    query_source = (
        history_source
        if isinstance(history_source, PLRiskSummaryQueryProtocol)
        else None
    )
    consumer_controls = saved_view_controls or PL_SAVED_VIEW_CONTROLS

    def current_filter_frame() -> pd.DataFrame | None:
        """Read mapped live data only to populate the five filter selectors."""

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
        prepared = (
            dashboard.frame.copy(deep=True)
            if dashboard.frame.empty
            else prepare_risk_data(dashboard.frame)
        )
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
    initialization_outputs = (
        [Output(saved_view_controls.initialized_id, "data")]
        if saved_view_controls is not None
        else []
    )
    initialization_states = (
        [State(saved_view_controls.initialized_id, "data")]
        if saved_view_controls is not None
        else []
    )

    @app.callback(
        *filter_outputs,
        *initialization_outputs,
        Output("pnl-filter-exclude-selected", "value"),
        Input("data-revision-store", "data"),
        *apply_inputs,
        *[State(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        State("pnl-filter-exclude-selected", "value"),
        *apply_states,
        *initialization_states,
    )
    def update_pl_filter_controls(_data_revision, *values):
        """Own all P&L selector values, including saved-view application."""

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
        applied_request = (
            values[offset + len(PL_FILTER_FIELDS) + 1]
            if saved_view_controls is not None
            else None
        )
        initialized = bool(values[-1]) if saved_view_controls is not None else True
        try:
            trigger = ctx.triggered_id
        except Exception:
            trigger = None
        request_id = saved_view_request_id(request)
        pending = bool(request_id and request_id != applied_request)
        matches_base = False
        if pending and saved_view_controls is not None:
            try:
                matches_base = saved_view_request_matches_base(
                    request,
                    saved_view_controls,
                    selected_values,
                    exclude_value,
                )
            except ValueError:
                matches_base = False
        if (
            pending
            and saved_view_controls is not None
            and (trigger == saved_view_controls.apply_request_id or matches_base)
        ):
            try:
                applied = saved_view_request_values(request, saved_view_controls)
            except ValueError:
                applied = None
            if applied is not None:
                applied_values, exclude_value = applied
                selected_values = [list(selected) for selected in applied_values]

        frame = current_filter_frame()
        has_filter_data = frame is not None and not frame.empty
        use_base = has_filter_data and (
            (not initialized and not pending)
            or (
                pending
                and isinstance(request, Mapping)
                and request.get("view_id") == BASE_SAVED_VIEW_ID
            )
        )
        if use_base:
            selected_values = _base_pl_filter_values(frame)
            exclude_value = []
        if frame is None:
            options = {field.key: [] for field in PL_FILTER_FIELDS}
            valid_values = selected_values
        else:
            options = pl_filter_options(frame)
            valid_values: list[list[str]] = []
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
        for field, selected in zip(PL_FILTER_FIELDS, valid_values, strict=True):
            result.extend((options[field.key], selected))
        if saved_view_controls is not None:
            result.append(initialized or has_filter_data)
        result.append(exclude_value)
        return tuple(result)

    @app.callback(
        Output("pnl-summary-open-paths", "data"),
        Output("pnl-aggregate-pl-grid", "children"),
        Input("data-revision-store", "data"),
        Input({"type": PL_SUMMARY_TOGGLE_TYPE, "path": ALL}, "n_clicks"),
        Input(
            {"type": PL_SUMMARY_PAGE_TYPE, "path": ALL, "page": ALL},
            "n_clicks",
        ),
        Input(consumer_controls.committed_state_id, "data"),
        Input("clear-cache-complete-store", "data"),
        State("pnl-summary-open-paths", "data"),
    )
    def reduce_and_render_pl_summary(
        _data_revision,
        row_clicks,
        page_clicks,
        committed_filter_state,
        _cache_generation,
        open_raw,
    ):
        """Query one page-owned summary and reveal only expanded branches."""

        nonlocal cleared_cache_generation

        effective_tokens = _ordered_open_tokens(open_raw)
        updated_open = no_update
        try:
            trigger = ctx.triggered_id
        except Exception:
            trigger = None
        page_by_parent: dict[str, int] = {}
        if (
            isinstance(trigger, Mapping)
            and trigger.get("type") == PL_SUMMARY_TOGGLE_TYPE
        ):
            token = str(trigger.get("path", ""))
            if (
                token
                and row_clicks
                and max(int(value or 0) for value in row_clicks) > 0
            ):
                requested = next(iter(decode_open_paths([token])), None)
                opened = {
                    current: path
                    for current in effective_tokens
                    if (path := next(iter(decode_open_paths([current])), None))
                    is not None
                }
                if requested is not None and token in opened:
                    opened = {
                        current: path
                        for current, path in opened.items()
                        if path[: len(requested)] != requested
                    }
                elif requested is not None:
                    if len(requested) == 2:
                        opened = {
                            current: path
                            for current, path in opened.items()
                            if len(path) != 2
                        }
                    opened[token] = requested
                effective_tokens = sorted(opened, key=str.casefold)
                updated_open = effective_tokens
        elif (
            isinstance(trigger, Mapping)
            and trigger.get("type") == PL_SUMMARY_PAGE_TYPE
            and page_clicks
            and max(int(value or 0) for value in page_clicks) > 0
        ):
            token = str(trigger.get("path", ""))
            requested = next(iter(decode_open_paths([token])), None)
            page = trigger.get("page")
            if (
                requested is not None
                and len(requested) == 2
                and token in effective_tokens
                and isinstance(page, int)
                and not isinstance(page, bool)
            ):
                page_by_parent[token] = max(page, 0)

        if query_source is None:
            return (
                updated_open,
                html.Div(
                    "Historical P&L is not configured for this application.",
                    className="empty-state",
                    role="status",
                ),
            )
        if committed_filter_state is None:
            raise PreventUpdate
        if trigger == "clear-cache-complete-store":
            requested_generation = pl_cache_generation(_cache_generation)
            if requested_generation > cleared_cache_generation:
                with cache_lock:
                    if requested_generation > cleared_cache_generation:
                        query_source.clear()
                        cleared_cache_generation = requested_generation
        try:
            selected_values, exclude_value = committed_pl_filter_values(
                committed_filter_state
            )
            result = query_source.risk_summary(
                filters=pl_external_filter_map(selected_values),
                exclude_selected="exclude" in (exclude_value or []),
            )
            if not isinstance(result, PLRiskSummaryResult):
                raise TypeError("P&L history source returned an invalid summary")
            valid_paths = {
                tuple(str(value) for value in path)
                for path in result.summary.get("Hierarchy Path", [])
                if isinstance(path, tuple) and 1 <= len(path) <= 2
            }
            retained_tokens = [
                token
                for token in effective_tokens
                if next(iter(decode_open_paths([token])), ()) in valid_paths
            ]
            if retained_tokens != effective_tokens:
                effective_tokens = retained_tokens
                updated_open = retained_tokens
            content = build_pl_summary_table(
                result.summary,
                effective_tokens,
                as_of_date=result.as_of_date,
                page_by_parent=page_by_parent,
            )
        except (PLSendValidationError, TypeError, ValueError, OSError) as exc:
            content = html.Div(
                f"Historical P&L could not be loaded: {exc}",
                className="empty-state has-error",
                role="alert",
            )
        return updated_open, content

    @app.callback(
        Output("pl-history-selection-store", "data"),
        Input(
            {
                "type": PL_SUMMARY_HISTORY_CELL_TYPE,
                "risk_type": ALL,
                "risk_greek": ALL,
                "underlying": ALL,
                "metric": ALL,
            },
            "n_clicks",
        ),
        prevent_initial_call=True,
    )
    def select_pl_history_cell(clicks):
        """Turn one summary value into an inline aggregated-history request."""

        if not clicks or max(int(value or 0) for value in clicks) <= 0:
            return no_update
        try:
            triggered = ctx.triggered_id
        except Exception:
            triggered = None
        if not isinstance(triggered, Mapping):
            return no_update
        return {
            "risk_type": str(triggered.get("risk_type", "")).strip(),
            "risk_greek": str(triggered.get("risk_greek", "")).strip(),
            "underlying": str(triggered.get("underlying", "")).strip(),
        }


__all__ = ["register_pl_aggregate_callbacks"]
