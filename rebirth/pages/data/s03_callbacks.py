"""Page-owned lazy query and playback callbacks for V4 Data history."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from typing import Mapping

import numpy as np
import pandas as pd
from dash import ClientsideFunction, Dash, Input, Output, State, ctx, no_update

from rebirth.history import (
    HISTORY_CANONICAL_CELL_BUDGET,
    HISTORY_RAW_ROW_BUDGET,
    MARKET_METRICS,
    RISK_METRICS,
    ArchiveHistoryRepository,
    HistoryBundle,
    HistoryHandoff,
    HistoryQuery,
    HistoryValidationError,
)
from .s01_selection import (
    catalog_key_for_handoff,
    direct_history_handoff,
    risk_greek_options,
    risk_type_options,
    selected_value,
    underlying_options,
)


QUICK_HANDOFF_ENTRY_KEY = "__quick_handoff__"


def _json_value(value: object) -> object:
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        timestamp = pd.Timestamp(value)
        if pd.isna(timestamp):
            return None
        if timestamp.hour == timestamp.minute == timestamp.second == 0:
            return timestamp.date().isoformat()
        return timestamp.isoformat()
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        selected = float(value)
        return selected if np.isfinite(selected) else None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _frame_payload(
    frame: pd.DataFrame,
    *,
    date_column: str | None = None,
) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
    columns = [str(column) for column in frame.columns]
    rows: list[dict[str, object]] = []
    for raw_record in frame.to_dict("records"):
        record = {
            str(column): _json_value(value) for column, value in raw_record.items()
        }
        if date_column and date_column in record and record[date_column] is not None:
            record[date_column] = pd.Timestamp(record[date_column]).date().isoformat()
        rows.append(record)
    return rows, [{"name": column, "id": column} for column in columns]


def serialize_history_bundle(bundle: HistoryBundle) -> dict[str, object]:
    """Convert one immutable query result into a browser-local playback bundle."""

    if len(bundle.raw_rows) > HISTORY_RAW_ROW_BUDGET:
        raise HistoryValidationError(
            f"Raw history has {len(bundle.raw_rows):,} exact rows and exceeds the "
            f"{HISTORY_RAW_ROW_BUDGET:,}-row browser budget. Choose a narrower "
            "period or more selective Risk filters."
        )
    if len(bundle.values) > HISTORY_CANONICAL_CELL_BUDGET:
        raise HistoryValidationError(
            f"Canonical history has {len(bundle.values):,} cells and exceeds the "
            f"{HISTORY_CANONICAL_CELL_BUDGET:,}-cell browser budget. Choose a "
            "narrower period or exact identity."
        )
    values, _columns = _frame_payload(
        bundle.values,
        date_column=bundle.date_column,
    )
    key_payload = {
        "handoff": bundle.query.handoff.to_mapping(),
        "period": bundle.query.period,
        "start": (
            bundle.query.start_date.isoformat()
            if bundle.query.start_date is not None
            else None
        ),
        "end": (
            bundle.query.end_date.isoformat()
            if bundle.query.end_date is not None
            else None
        ),
        "generation": bundle.generation,
    }
    key = hashlib.sha256(
        json.dumps(key_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "key": key,
        "uirevision": f"data-history-{key}",
        "kind": bundle.query.handoff.kind,
        "handoff": bundle.query.handoff.to_mapping(),
        "period": bundle.query.period,
        "date_column": bundle.date_column,
        "dates": [value.isoformat() for value in bundle.dates],
        "metric_column": bundle.metric_column,
        "axes": [
            {
                "column": axis.column,
                "order_column": axis.order_column,
                "labels": list(axis.labels),
                "ranks": list(axis.ranks),
                "status": axis.status,
            }
            for axis in bundle.ordering.axes
        ],
        "ordering_status": bundle.ordering.status,
        "values": values,
        "generation": bundle.generation,
        "reset_generation": bundle.query.handoff.reset_generation,
    }


def metric_controls(
    raw_handoff: object,
) -> tuple[list[dict[str, str]], str, str]:
    """Return strict metric choices and a locked identity breadcrumb."""

    try:
        handoff = HistoryHandoff.from_mapping(raw_handoff)
    except (HistoryValidationError, TypeError, ValueError):
        return (
            [{"label": "Risk", "value": "risk"}],
            "risk",
            "No history identity selected",
        )
    metrics = RISK_METRICS if handoff.kind == "risk" else MARKET_METRICS
    options = [{"label": label, "value": key} for key, label in metrics.items()]
    identity = handoff.identity
    mode = "Reported" if identity.identity_mode == "reported" else "Underlying"
    sources = ", ".join(identity.source_types)
    breadcrumb = (
        f"{handoff.kind.title()} › {identity.risk_type} › {identity.risk_greek} "
        f"› {identity.underlying} · {mode} · {sources}"
    )
    return options, handoff.metric, breadcrumb


def _request_query(raw_request: object) -> HistoryQuery:
    if not isinstance(raw_request, Mapping):
        raise HistoryValidationError("history request must be a mapping")
    handoff = HistoryHandoff.from_mapping(raw_request.get("handoff"))
    period = str(raw_request.get("period") or "all").strip().casefold()
    return HistoryQuery(
        handoff=handoff,
        period=period,
        start_date=(raw_request.get("start_date") if period == "custom" else None),
        end_date=(raw_request.get("end_date") if period == "custom" else None),
    )


def history_request_payload(
    handoff: HistoryHandoff,
    *,
    metric: object = None,
    period: object = "all",
    start_date: object = None,
    end_date: object = None,
    request_id: object = None,
) -> dict[str, object]:
    """Build the one immutable request consumed by the archive callback."""

    selected_metric = str(metric or handoff.metric).strip().casefold()
    allowed = RISK_METRICS if handoff.kind == "risk" else MARKET_METRICS
    if selected_metric not in allowed:
        raise HistoryValidationError(
            f"{handoff.kind.title()} metric must be one of {sorted(allowed)}"
        )
    selected_handoff = replace(handoff, metric=selected_metric)
    selected_period = str(period or "all").strip().casefold()
    query = HistoryQuery(
        handoff=selected_handoff,
        period=selected_period,
        start_date=(start_date if selected_period == "custom" else None),
        end_date=(end_date if selected_period == "custom" else None),
    )
    return {
        "handoff": selected_handoff.to_mapping(),
        "period": query.period,
        "start_date": (
            query.start_date.isoformat() if query.start_date is not None else None
        ),
        "end_date": query.end_date.isoformat() if query.end_date is not None else None,
        "request_id": None if request_id is None else str(request_id),
    }


def query_history_bundle(
    repository: ArchiveHistoryRepository,
    raw_request: object,
    cache_state: object,
    reset_generation: object,
) -> tuple[dict[str, object] | None, str]:
    """Validate one browser request and perform exactly one repository read."""

    query = _request_query(raw_request)
    handoff = query.handoff
    if reset_generation is None:
        current_reset = 0
    elif isinstance(reset_generation, bool) or not isinstance(
        reset_generation, (int, np.integer)
    ):
        raise HistoryValidationError("reset generation must be an integer")
    else:
        current_reset = int(reset_generation)
    if current_reset != handoff.reset_generation:
        raise HistoryValidationError(
            "This history request predates Clear Cache. Reopen it from Quick Risk "
            "or Quick Market."
        )
    if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
        return None, "Preparing the archive index…"
    bundle = repository.read(query)
    payload = serialize_history_bundle(bundle)
    if bundle.empty:
        status = "No archived rows match this exact identity and period."
    else:
        status = (
            f"Loaded {len(bundle.dates):,} dates and {len(bundle.raw_rows):,} exact "
            f"rows ({bundle.resolved_start} to {bundle.resolved_end})."
        )
        if bundle.ordering.status != "ORDERED":
            status += " Tenor order is a deterministic fallback (ORDER_AMBIGUOUS)."
    return payload, status


def poll_archive_generation(
    repository: ArchiveHistoryRepository,
    raw_handoff: object,
    previous_state: object,
    reset_generation: object,
) -> tuple[object, str]:
    """Refresh lightweight archive metadata without producing false changes."""

    del raw_handoff
    previous = previous_state if isinstance(previous_state, Mapping) else {}
    try:
        cleared = repository.clear_for_reset_generation(reset_generation or 0)
        reset = int(reset_generation or 0)
        generation = repository.generation()
    except (OSError, HistoryValidationError, TypeError, ValueError) as error:
        return no_update, f"History cache check failed: {error}"
    status = f"History cache cleared for reset {reset}." if cleared else ""
    state = {"generation": generation, "reset_generation": reset}
    if state == previous:
        return no_update, status
    return state, status


def load_archive_catalog(
    repository: ArchiveHistoryRepository,
    cache_state: object,
) -> tuple[dict[str, object] | None, str]:
    """Load the tiny direct-selector catalog after the Data route is mounted."""

    if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
        return None, "Preparing archive choices…"
    catalog = repository.catalog()
    risk_count = sum(entry.kind == "risk" for entry in catalog.entries)
    market_count = sum(entry.kind == "market" for entry in catalog.entries)
    if not catalog.entries:
        status = "No completed V4 Risk or Market archive identities are available."
    else:
        status = (
            f"Archive ready: {risk_count:,} Risk and {market_count:,} Market choices."
        )
    return catalog.to_mapping(), status


def register_callbacks(
    app: Dash,
    repository: ArchiveHistoryRepository,
) -> None:
    """Register the Data page's lazy query and isolated playback graph."""

    @app.callback(
        Output("data-history-kind-tabs", "value"),
        Output("data-identity-mode", "value"),
        Input("data-history-handoff-store", "data"),
    )
    def sync_quick_handoff(raw_handoff):
        try:
            handoff = HistoryHandoff.from_mapping(raw_handoff)
        except (HistoryValidationError, TypeError, ValueError):
            return no_update, no_update
        return handoff.kind, handoff.identity.identity_mode

    @app.callback(
        Output("data-identity-mode", "disabled"),
        Input("data-history-kind-tabs", "value"),
    )
    def configure_identity_mode(kind):
        return str(kind or "risk").strip().casefold() == "market"

    @app.callback(
        Output("data-metric", "options"),
        Output("data-metric", "value"),
        Output("data-identity-breadcrumb", "children"),
        Input("data-history-request-store", "data"),
        Input("data-history-kind-tabs", "value"),
    )
    def configure_request(raw_request, kind):
        if isinstance(raw_request, Mapping) and "handoff" in raw_request:
            try:
                handoff = HistoryHandoff.from_mapping(raw_request["handoff"])
                if handoff.kind == str(kind or "risk").strip().casefold():
                    return metric_controls(handoff.to_mapping())
            except (HistoryValidationError, TypeError, ValueError):
                pass
        selected_kind = str(kind or "risk").strip().casefold()
        metrics = MARKET_METRICS if selected_kind == "market" else RISK_METRICS
        options = [{"label": label, "value": key} for key, label in metrics.items()]
        value = "current" if selected_kind == "market" else "risk"
        return options, value, "Choose an exact identity, then load history"

    @app.callback(
        Output("data-history-catalog-store", "data"),
        Output("data-catalog-status", "children"),
        Input("data-history-cache-state-store", "data"),
        Input("data-history-query-state-store", "data"),
        State("data-history-handoff-store", "data"),
        State("data-history-catalog-store", "data"),
    )
    def refresh_archive_catalog(cache_state, query_state, raw_handoff, current):
        if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
            return None, "Preparing archive choices…"
        try:
            HistoryHandoff.from_mapping(raw_handoff)
            has_quick_handoff = True
        except (HistoryValidationError, TypeError, ValueError):
            has_quick_handoff = False
        query_status = (
            str(query_state.get("status") or "idle")
            if isinstance(query_state, Mapping)
            else "idle"
        )
        if has_quick_handoff and query_status not in {"complete", "error"}:
            return no_update, "Loading selected history before archive choices…"
        if (
            isinstance(current, Mapping)
            and current.get("generation") == cache_state.get("generation")
            and isinstance(current.get("entries"), list)
        ):
            return no_update, no_update
        try:
            return load_archive_catalog(repository, cache_state)
        except (OSError, HistoryValidationError, TypeError, ValueError) as error:
            return None, f"Archive choices failed: {error}"

    @app.callback(
        Output("data-risk-type", "options"),
        Output("data-risk-type", "value"),
        Input("data-history-catalog-store", "data"),
        Input("data-history-kind-tabs", "value"),
        Input("data-identity-mode", "value"),
        State("data-risk-type", "value"),
        State("data-history-handoff-store", "data"),
    )
    def choose_risk_type(
        raw_catalog,
        kind,
        identity_mode,
        current,
        raw_handoff,
    ):
        if raw_catalog is None:
            try:
                handoff = HistoryHandoff.from_mapping(raw_handoff)
                if (
                    handoff.kind == str(kind or "risk").casefold()
                    and handoff.identity.identity_mode
                    == str(identity_mode or "reported").casefold()
                ):
                    value = handoff.identity.risk_type
                    return [{"label": value, "value": value}], value
            except (HistoryValidationError, TypeError, ValueError):
                pass
            return [], None
        try:
            options = risk_type_options(raw_catalog, kind, identity_mode)
            preferred = None
            if current is None:
                handoff = HistoryHandoff.from_mapping(raw_handoff)
                if handoff.kind == str(kind or "risk").casefold():
                    preferred = handoff.identity.risk_type
            return options, selected_value(options, current, preferred)
        except (HistoryValidationError, TypeError, ValueError):
            return [], None

    @app.callback(
        Output("data-risk-greek", "options"),
        Output("data-risk-greek", "value"),
        Input("data-history-catalog-store", "data"),
        Input("data-history-kind-tabs", "value"),
        Input("data-identity-mode", "value"),
        Input("data-risk-type", "value"),
        State("data-risk-greek", "value"),
        State("data-history-handoff-store", "data"),
    )
    def choose_risk_greek(
        raw_catalog,
        kind,
        identity_mode,
        risk_type,
        current,
        raw_handoff,
    ):
        if risk_type is None:
            return [], None
        if raw_catalog is None:
            try:
                handoff = HistoryHandoff.from_mapping(raw_handoff)
                if handoff.kind == str(
                    kind or "risk"
                ).casefold() and handoff.identity.risk_type == str(risk_type):
                    value = handoff.identity.risk_greek
                    return [{"label": value, "value": value}], value
            except (HistoryValidationError, TypeError, ValueError):
                pass
            return [], None
        try:
            options = risk_greek_options(
                raw_catalog,
                kind,
                identity_mode,
                risk_type,
            )
            preferred = None
            if current is None:
                handoff = HistoryHandoff.from_mapping(raw_handoff)
                if handoff.kind == str(
                    kind or "risk"
                ).casefold() and handoff.identity.risk_type == str(risk_type):
                    preferred = handoff.identity.risk_greek
            return options, selected_value(options, current, preferred)
        except (HistoryValidationError, TypeError, ValueError):
            return [], None

    @app.callback(
        Output("data-underlying", "options"),
        Output("data-underlying", "value"),
        Input("data-history-catalog-store", "data"),
        Input("data-history-kind-tabs", "value"),
        Input("data-identity-mode", "value"),
        Input("data-risk-type", "value"),
        Input("data-risk-greek", "value"),
        State("data-underlying", "value"),
        State("data-history-handoff-store", "data"),
    )
    def choose_underlying(
        raw_catalog,
        kind,
        identity_mode,
        risk_type,
        risk_greek,
        current,
        raw_handoff,
    ):
        if risk_type is None or risk_greek is None:
            return [], None
        if raw_catalog is None:
            try:
                handoff = HistoryHandoff.from_mapping(raw_handoff)
                if (
                    handoff.kind == str(kind or "risk").casefold()
                    and handoff.identity.risk_type == str(risk_type)
                    and handoff.identity.risk_greek == str(risk_greek)
                ):
                    return [
                        {
                            "label": handoff.identity.underlying,
                            "value": QUICK_HANDOFF_ENTRY_KEY,
                        }
                    ], QUICK_HANDOFF_ENTRY_KEY
            except (HistoryValidationError, TypeError, ValueError):
                pass
            return [], None
        try:
            options = underlying_options(
                raw_catalog,
                kind,
                identity_mode,
                risk_type,
                risk_greek,
            )
            preferred = None
            if current in {None, QUICK_HANDOFF_ENTRY_KEY}:
                preferred = catalog_key_for_handoff(raw_catalog, raw_handoff)
            return options, selected_value(options, current, preferred)
        except (HistoryValidationError, TypeError, ValueError):
            return [], None

    @app.callback(
        Output("data-history-request-store", "data"),
        Input("data-history-handoff-store", "data"),
        Input("data-load-history-button", "n_clicks"),
        Input("reset-generation-store", "data"),
        State("data-history-kind-tabs", "value"),
        State("data-history-catalog-store", "data"),
        State("data-underlying", "value"),
        State("data-metric", "value"),
        State("data-period", "value"),
        State("data-custom-range", "start_date"),
        State("data-custom-range", "end_date"),
        State("data-history-request-store", "data"),
    )
    def choose_history_request(
        raw_handoff,
        load_clicks,
        reset_generation,
        kind,
        raw_catalog,
        entry_key,
        metric,
        period,
        start_date,
        end_date,
        current_request,
    ):
        triggered = ctx.triggered_id
        try:
            reset = int(reset_generation or 0)
        except (TypeError, ValueError):
            reset = 0
        try:
            if triggered == "data-load-history-button":
                if entry_key == QUICK_HANDOFF_ENTRY_KEY:
                    handoff = HistoryHandoff.from_mapping(raw_handoff)
                    if handoff.kind != str(kind or "risk").strip().casefold():
                        raise HistoryValidationError(
                            "Quick history identity belongs to another tab"
                        )
                    handoff = replace(handoff, reset_generation=reset)
                else:
                    handoff = direct_history_handoff(
                        raw_catalog,
                        entry_key,
                        kind=kind,
                        reset_generation=reset,
                    )
                return history_request_payload(
                    handoff,
                    metric=metric,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    request_id=f"load-{int(load_clicks or 0)}-{reset}",
                )
            if triggered == "reset-generation-store" and current_request is not None:
                query = _request_query(current_request)
                return history_request_payload(
                    replace(query.handoff, reset_generation=reset),
                    period=query.period,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    request_id=f"reset-{reset}",
                )
            handoff = HistoryHandoff.from_mapping(raw_handoff)
            return history_request_payload(
                replace(handoff, reset_generation=reset),
                period=period,
                start_date=start_date,
                end_date=end_date,
                request_id=f"quick-{handoff.source_revision}-{reset}",
            )
        except (HistoryValidationError, TypeError, ValueError):
            return None

    @app.callback(
        Output("data-custom-range-control", "hidden"),
        Input("data-period", "value"),
    )
    def show_custom_range(period):
        return str(period or "all").casefold() != "custom"

    @app.callback(
        Output("data-history-cache-state-store", "data"),
        Output("data-clear-status", "children"),
        Input("data-history-generation-interval", "n_intervals"),
        Input("clear-cache-complete-store", "data"),
        Input("data-history-request-store", "data"),
        State("data-history-cache-state-store", "data"),
    )
    def refresh_archive_generation(
        _intervals,
        reset_generation,
        raw_handoff,
        previous_state,
    ):
        return poll_archive_generation(
            repository,
            raw_handoff,
            previous_state,
            reset_generation,
        )

    @app.callback(
        Output("data-history-bundle-store", "data"),
        Output("data-history-status", "children"),
        Output("data-history-query-state-store", "data"),
        Input("data-history-request-store", "data"),
        Input("data-history-cache-state-store", "data"),
        Input("reset-generation-store", "data"),
        running=[
            (Output("data-load-history-button", "disabled"), True, False),
            (
                Output("data-load-history-button", "children"),
                "Loading history…",
                "Load history",
            ),
        ],
    )
    def load_history(
        raw_request,
        cache_state,
        reset_generation,
    ):
        if raw_request is None:
            return (
                None,
                "Choose an exact identity, then load its history.",
                {"status": "idle"},
            )
        try:
            payload, status = query_history_bundle(
                repository,
                raw_request,
                cache_state,
                reset_generation,
            )
            return (
                payload,
                status,
                {"status": "waiting" if payload is None else "complete"},
            )
        except (OSError, HistoryValidationError, TypeError, ValueError) as error:
            return (
                None,
                f"History request failed: {error}",
                {"status": "error"},
            )

    app.clientside_callback(
        ClientsideFunction(namespace="cube", function_name="dataProjectionBase"),
        Output("data-history-projection", "options"),
        Output("data-history-projection", "value"),
        Output("data-history-projection", "disabled"),
        Output("data-history-date-a", "options"),
        Output("data-history-date-a", "value"),
        Output("data-history-date-b", "options"),
        Output("data-history-date-b", "value"),
        Input("data-history-bundle-store", "data"),
        State("data-history-projection", "value"),
        State("data-history-date-a", "value"),
        State("data-history-date-b", "value"),
    )

    app.clientside_callback(
        ClientsideFunction(namespace="cube", function_name="dataProjectionSlice"),
        Output("data-history-slice-label", "children"),
        Output("data-history-slice", "options"),
        Output("data-history-slice", "value"),
        Output("data-history-slice", "disabled"),
        Output("data-history-slice-control", "style"),
        Output("data-history-comparison-dates", "style"),
        Input("data-history-bundle-store", "data"),
        Input("data-history-projection", "value"),
        State("data-history-slice", "value"),
    )

    app.clientside_callback(
        ClientsideFunction(namespace="cube", function_name="dataPlayback"),
        Output("data-history-chart", "figure"),
        Output("data-selected-table", "data"),
        Output("data-selected-table", "columns"),
        Output("data-player-slider", "min"),
        Output("data-player-slider", "max"),
        Output("data-player-slider", "marks"),
        Output("data-player-slider", "value"),
        Output("data-player-slider", "disabled"),
        Output("data-player-date-pill", "children"),
        Output("data-player-button", "children"),
        Output("data-player-button", "disabled"),
        Output("data-player-interval", "disabled"),
        Output("data-player-state-store", "data"),
        Output("data-player-controls", "style"),
        Input("data-history-bundle-store", "data"),
        Input("data-history-projection", "value"),
        Input("data-history-slice", "value"),
        Input("data-history-date-a", "value"),
        Input("data-history-date-b", "value"),
        Input("data-player-button", "n_clicks"),
        Input("data-player-interval", "n_intervals"),
        Input("data-player-slider", "value"),
        Input("reset-generation-store", "data"),
        Input("data-history-cache-state-store", "data"),
        Input("data-player-visibility-store", "data"),
        State("data-player-state-store", "data"),
    )


__all__ = [
    "load_archive_catalog",
    "history_request_payload",
    "metric_controls",
    "poll_archive_generation",
    "query_history_bundle",
    "register_callbacks",
    "serialize_history_bundle",
]
