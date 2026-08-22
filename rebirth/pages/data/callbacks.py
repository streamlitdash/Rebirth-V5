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
from .selection import (
    catalog_key_for_handoff,
    direct_history_handoff,
    risk_greek_options,
    risk_type_options,
    selected_value,
    underlying_options,
)


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


def query_history_bundle(
    repository: ArchiveHistoryRepository,
    raw_handoff: object,
    metric: object,
    period: object,
    start_date: object,
    end_date: object,
    cache_state: object,
    reset_generation: object,
) -> tuple[
    dict[str, object] | None, list[dict[str, object]], list[dict[str, str]], str
]:
    """Validate one browser request and perform exactly one repository read."""

    handoff = HistoryHandoff.from_mapping(raw_handoff)
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
        return None, [], [], "Preparing the archive index…"
    selected_metric = str(metric or "").strip().casefold()
    allowed = RISK_METRICS if handoff.kind == "risk" else MARKET_METRICS
    if selected_metric not in allowed:
        raise HistoryValidationError(
            f"{handoff.kind.title()} metric must be one of {sorted(allowed)}"
        )
    selected_period = str(period or "all").strip().casefold()
    handoff = replace(handoff, metric=selected_metric)
    query = HistoryQuery(
        handoff=handoff,
        period=selected_period,
        start_date=(start_date if selected_period == "custom" else None),
        end_date=(end_date if selected_period == "custom" else None),
    )
    bundle = repository.read(query)
    payload = serialize_history_bundle(bundle)
    raw_rows, raw_columns = _frame_payload(
        bundle.raw_rows,
        date_column=bundle.date_column,
    )
    if bundle.empty:
        status = "No archived rows match this exact identity and period."
    else:
        status = (
            f"Loaded {len(bundle.dates):,} dates and {len(bundle.raw_rows):,} exact "
            f"rows ({bundle.resolved_start} to {bundle.resolved_end})."
        )
        if bundle.ordering.status != "ORDERED":
            status += " Tenor order is a deterministic fallback (ORDER_AMBIGUOUS)."
    return payload, raw_rows, raw_columns, status


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
    return {
        "generation": catalog.generation,
        "risk_count": risk_count,
        "market_count": market_count,
    }, status


def register_callbacks(
    app: Dash,
    repository: ArchiveHistoryRepository,
) -> None:
    """Register the Data page's lazy query and isolated playback graph."""

    @app.callback(
        Output("data-history-lock-store", "data"),
        Output("data-history-kind-tabs", "value"),
        Output("data-identity-mode", "value"),
        Input("data-history-handoff-store", "data"),
        Input("data-unlock-identity-button", "n_clicks"),
    )
    def sync_quick_handoff(raw_handoff, _unlock_clicks):
        if ctx.triggered_id == "data-unlock-identity-button":
            return {"locked": False}, no_update, no_update
        try:
            handoff = HistoryHandoff.from_mapping(raw_handoff)
        except (HistoryValidationError, TypeError, ValueError):
            return {"locked": False}, no_update, no_update
        return (
            {"locked": True},
            handoff.kind,
            handoff.identity.identity_mode,
        )

    @app.callback(
        Output("data-risk-type", "disabled"),
        Output("data-risk-greek", "disabled"),
        Output("data-underlying", "disabled"),
        Output("data-identity-mode", "disabled"),
        Output("data-unlock-identity-button", "disabled"),
        Input("data-history-lock-store", "data"),
        Input("data-history-kind-tabs", "value"),
    )
    def lock_identity_controls(lock_state, kind):
        locked = bool(
            isinstance(lock_state, Mapping) and lock_state.get("locked") is True
        )
        market = str(kind or "risk").strip().casefold() == "market"
        return locked, locked, locked, locked or market, not locked

    @app.callback(
        Output("data-metric", "options"),
        Output("data-metric", "value"),
        Output("data-identity-breadcrumb", "children"),
        Input("data-history-request-store", "data"),
    )
    def configure_request(raw_handoff):
        return metric_controls(raw_handoff)

    @app.callback(
        Output("data-history-catalog-store", "data"),
        Output("data-catalog-status", "children"),
        Input("data-history-cache-state-store", "data"),
    )
    def refresh_archive_catalog(cache_state):
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
        Input("data-history-lock-store", "data"),
        State("data-risk-type", "value"),
        State("data-history-handoff-store", "data"),
    )
    def choose_risk_type(
        raw_catalog,
        kind,
        identity_mode,
        lock_state,
        current,
        raw_handoff,
    ):
        if raw_catalog is None:
            return [], None
        try:
            catalog = repository.catalog()
            options = risk_type_options(catalog, kind, identity_mode)
            preferred = None
            if isinstance(lock_state, Mapping) and lock_state.get("locked"):
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
        Input("data-history-lock-store", "data"),
        State("data-risk-greek", "value"),
        State("data-history-handoff-store", "data"),
    )
    def choose_risk_greek(
        raw_catalog,
        kind,
        identity_mode,
        risk_type,
        lock_state,
        current,
        raw_handoff,
    ):
        if raw_catalog is None or risk_type is None:
            return [], None
        try:
            catalog = repository.catalog()
            options = risk_greek_options(
                catalog,
                kind,
                identity_mode,
                risk_type,
            )
            preferred = None
            if isinstance(lock_state, Mapping) and lock_state.get("locked"):
                handoff = HistoryHandoff.from_mapping(raw_handoff)
                if handoff.kind == str(kind or "risk").casefold():
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
        Input("data-history-lock-store", "data"),
        State("data-underlying", "value"),
        State("data-history-handoff-store", "data"),
    )
    def choose_underlying(
        raw_catalog,
        kind,
        identity_mode,
        risk_type,
        risk_greek,
        lock_state,
        current,
        raw_handoff,
    ):
        if raw_catalog is None or risk_type is None or risk_greek is None:
            return [], None
        try:
            catalog = repository.catalog()
            options = underlying_options(
                catalog,
                kind,
                identity_mode,
                risk_type,
                risk_greek,
            )
            preferred = None
            locked = isinstance(lock_state, Mapping) and lock_state.get("locked")
            if locked:
                handoff = HistoryHandoff.from_mapping(raw_handoff)
                preferred = catalog_key_for_handoff(catalog, raw_handoff)
                if preferred is None and handoff.kind == str(kind or "risk").casefold():
                    preferred = "locked-handoff"
                    options = [
                        {
                            "label": handoff.identity.underlying,
                            "value": preferred,
                        },
                        *options,
                    ]
            return options, selected_value(options, current, preferred)
        except (HistoryValidationError, TypeError, ValueError):
            return [], None

    @app.callback(
        Output("data-history-request-store", "data"),
        Input("data-history-handoff-store", "data"),
        Input("data-load-history-button", "n_clicks"),
        Input("data-unlock-identity-button", "n_clicks"),
        Input("data-history-kind-tabs", "value"),
        Input("reset-generation-store", "data"),
        State("data-history-lock-store", "data"),
        State("data-history-catalog-store", "data"),
        State("data-underlying", "value"),
    )
    def choose_history_request(
        raw_handoff,
        _load_clicks,
        _unlock_clicks,
        kind,
        reset_generation,
        lock_state,
        raw_catalog,
        entry_key,
    ):
        triggered = ctx.triggered_id
        if triggered == "data-unlock-identity-button":
            return None
        if triggered == "data-load-history-button":
            try:
                catalog = repository.catalog()
                return direct_history_handoff(
                    catalog,
                    entry_key,
                    kind=kind,
                    reset_generation=reset_generation,
                ).to_mapping()
            except (HistoryValidationError, TypeError, ValueError):
                return None
        locked = isinstance(lock_state, Mapping) and lock_state.get("locked") is True
        if triggered == "reset-generation-store" and not locked:
            try:
                return direct_history_handoff(
                    repository.catalog(),
                    entry_key,
                    kind=kind,
                    reset_generation=reset_generation,
                ).to_mapping()
            except (HistoryValidationError, TypeError, ValueError):
                return None
        try:
            handoff = HistoryHandoff.from_mapping(raw_handoff)
        except (HistoryValidationError, TypeError, ValueError):
            return None
        if triggered == "data-history-kind-tabs" and not locked:
            return None
        if handoff.kind != str(kind or handoff.kind).strip().casefold():
            return None
        try:
            reset = int(reset_generation or 0)
        except (TypeError, ValueError):
            reset = handoff.reset_generation
        return replace(handoff, reset_generation=reset).to_mapping()

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
        Output("data-raw-table", "data"),
        Output("data-raw-table", "columns"),
        Output("data-history-status", "children"),
        Input("data-history-request-store", "data"),
        Input("data-metric", "value"),
        Input("data-period", "value"),
        Input("data-custom-range", "start_date"),
        Input("data-custom-range", "end_date"),
        Input("data-history-cache-state-store", "data"),
        Input("reset-generation-store", "data"),
    )
    def load_history(
        raw_handoff,
        metric,
        period,
        start_date,
        end_date,
        cache_state,
        reset_generation,
    ):
        if raw_handoff is None:
            return (
                None,
                [],
                [],
                "Choose an exact identity, then load its history.",
            )
        try:
            return query_history_bundle(
                repository,
                raw_handoff,
                metric,
                period,
                start_date,
                end_date,
                cache_state,
                reset_generation,
            )
        except (OSError, HistoryValidationError, TypeError, ValueError) as error:
            return None, [], [], f"History request failed: {error}"

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
        Input("data-raw-table", "data"),
        Input("data-raw-table", "columns"),
        Input("data-player-visibility-store", "data"),
        State("data-player-state-store", "data"),
    )


__all__ = [
    "load_archive_catalog",
    "metric_controls",
    "poll_archive_generation",
    "query_history_bundle",
    "register_callbacks",
    "serialize_history_bundle",
]
