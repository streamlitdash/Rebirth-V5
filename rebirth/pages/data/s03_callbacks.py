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


def _stored_history_handoff(raw_handoff: object) -> HistoryHandoff:
    payload = (
        raw_handoff.get("handoff")
        if isinstance(raw_handoff, Mapping) and "handoff" in raw_handoff
        else raw_handoff
    )
    return HistoryHandoff.from_mapping(payload)


def _stored_handoff_nonce(raw_handoff: object) -> str:
    if isinstance(raw_handoff, Mapping):
        nonce = str(raw_handoff.get("nonce") or "").strip()
        if nonce:
            return nonce
    handoff = _stored_history_handoff(raw_handoff)
    return f"legacy-{handoff.kind}-{handoff.source_revision}"


def _pending_history_handoff(
    raw_handoff: object,
    consumed_nonce: object,
) -> HistoryHandoff:
    nonce = _stored_handoff_nonce(raw_handoff)
    if nonce == str(consumed_nonce or ""):
        raise HistoryValidationError("history handoff was already consumed")
    return _stored_history_handoff(raw_handoff)


def _requested_history_handoff(raw_request: object) -> HistoryHandoff:
    if not isinstance(raw_request, Mapping) or "handoff" not in raw_request:
        raise HistoryValidationError("history request has no identity")
    return HistoryHandoff.from_mapping(raw_request["handoff"])


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
    metric_column = bundle.metric_column
    browser_values = bundle.values
    if bundle.query.handoff.kind == "market" and metric_column == "Current":
        metric_column = "Official"
        browser_values = browser_values.rename(columns={"Current": metric_column})
    values, _columns = _frame_payload(
        browser_values,
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
        "metric_column": metric_column,
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


def history_breadcrumb(raw_handoff: object) -> str:
    """Return the loaded identity and its fixed page-owned series label."""

    try:
        handoff = HistoryHandoff.from_mapping(raw_handoff)
    except (HistoryValidationError, TypeError, ValueError):
        return "No history identity selected"
    identity = handoff.identity
    mode = "Reported" if identity.identity_mode == "reported" else "Underlying"
    series = "Risk" if handoff.kind == "risk" else "Official"
    sources = ", ".join(identity.source_types)
    return (
        f"{handoff.kind.title()} › {identity.risk_type} › {identity.risk_greek} "
        f"› {identity.underlying} · {series} · {mode} · {sources}"
    )


def _request_query(raw_request: object) -> HistoryQuery:
    if not isinstance(raw_request, Mapping):
        raise HistoryValidationError("history request must be a mapping")
    request_error = str(raw_request.get("error") or "").strip()
    if request_error:
        raise HistoryValidationError(request_error)
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
    period: object = "all",
    start_date: object = None,
    end_date: object = None,
    request_id: object = None,
) -> dict[str, object]:
    """Build the one immutable request consumed by the archive callback."""

    selected_metric = "risk" if handoff.kind == "risk" else "current"
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
        Input("data-history-handoff-store", "data"),
        Input("data-history-request-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
    )
    def sync_quick_handoff(raw_handoff, raw_request, consumed_nonce):
        try:
            handoff = _requested_history_handoff(raw_request)
        except (HistoryValidationError, TypeError, ValueError):
            try:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
            except (HistoryValidationError, TypeError, ValueError):
                return no_update
        return handoff.kind

    @app.callback(
        Output("data-identity-mode", "value"),
        Output("data-identity-mode", "disabled"),
        Input("data-history-kind-tabs", "value"),
        Input("data-history-handoff-store", "data"),
        Input("data-history-request-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
    )
    def configure_identity_mode(
        kind,
        raw_handoff,
        raw_request,
        consumed_nonce,
    ):
        selected_kind = str(kind or "risk").strip().casefold()
        if selected_kind == "market":
            return "underlying", True
        try:
            handoff = _requested_history_handoff(raw_request)
        except (HistoryValidationError, TypeError, ValueError):
            try:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
            except (HistoryValidationError, TypeError, ValueError):
                handoff = None
        preferred = (
            handoff.identity.identity_mode
            if handoff is not None and handoff.kind == selected_kind
            else "reported"
        )
        return (
            preferred if preferred in {"reported", "underlying"} else "reported"
        ), False

    @app.callback(
        Output("data-identity-breadcrumb", "children"),
        Input("data-history-request-store", "data"),
        Input("data-history-kind-tabs", "value"),
    )
    def configure_request(raw_request, kind):
        if isinstance(raw_request, Mapping) and "handoff" in raw_request:
            try:
                handoff = HistoryHandoff.from_mapping(raw_request["handoff"])
                if handoff.kind == str(kind or "risk").strip().casefold():
                    return history_breadcrumb(handoff.to_mapping())
            except (HistoryValidationError, TypeError, ValueError):
                pass
        return "Choose an exact identity, then load history"

    @app.callback(
        Output("data-history-catalog-store", "data"),
        Output("data-catalog-status", "children"),
        Input("data-history-cache-state-store", "data"),
        State("data-history-catalog-store", "data"),
    )
    def refresh_archive_catalog(cache_state, current):
        if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
            return None, "Preparing archive choices…"
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
        Input("data-history-request-store", "data"),
        State("data-risk-type", "value"),
        State("data-history-handoff-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
    )
    def choose_risk_type(
        raw_catalog,
        kind,
        identity_mode,
        raw_request,
        current,
        raw_handoff,
        consumed_nonce,
    ):
        if raw_catalog is None:
            try:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
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
            try:
                handoff = _requested_history_handoff(raw_request)
            except (HistoryValidationError, TypeError, ValueError):
                try:
                    handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                except (HistoryValidationError, TypeError, ValueError):
                    handoff = None
            if (
                handoff is not None
                and handoff.kind == str(kind or "risk").casefold()
                and handoff.identity.identity_mode
                == str(identity_mode or "reported").casefold()
            ):
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
        Input("data-history-request-store", "data"),
        State("data-risk-greek", "value"),
        State("data-history-handoff-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
    )
    def choose_risk_greek(
        raw_catalog,
        kind,
        identity_mode,
        risk_type,
        raw_request,
        current,
        raw_handoff,
        consumed_nonce,
    ):
        if risk_type is None:
            return [], None
        if raw_catalog is None:
            try:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
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
            try:
                handoff = _requested_history_handoff(raw_request)
            except (HistoryValidationError, TypeError, ValueError):
                try:
                    handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                except (HistoryValidationError, TypeError, ValueError):
                    handoff = None
            if (
                handoff is not None
                and handoff.kind == str(kind or "risk").casefold()
                and handoff.identity.identity_mode
                == str(identity_mode or "reported").casefold()
                and handoff.identity.risk_type == str(risk_type)
            ):
                preferred = handoff.identity.risk_greek
            return options, selected_value(options, current, preferred)
        except (HistoryValidationError, TypeError, ValueError):
            return [], None

    @app.callback(
        Output("data-underlying", "options"),
        Output("data-underlying", "value"),
        Output("data-load-history-button", "disabled"),
        Input("data-history-catalog-store", "data"),
        Input("data-history-kind-tabs", "value"),
        Input("data-identity-mode", "value"),
        Input("data-risk-type", "value"),
        Input("data-risk-greek", "value"),
        Input("data-history-request-store", "data"),
        State("data-underlying", "value"),
        State("data-history-handoff-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
    )
    def choose_underlying(
        raw_catalog,
        kind,
        identity_mode,
        risk_type,
        risk_greek,
        raw_request,
        current,
        raw_handoff,
        consumed_nonce,
    ):
        if risk_type is None or risk_greek is None:
            return [], None, True
        if raw_catalog is None:
            try:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                if (
                    handoff.kind == str(kind or "risk").casefold()
                    and handoff.identity.risk_type == str(risk_type)
                    and handoff.identity.risk_greek == str(risk_greek)
                ):
                    return (
                        [
                            {
                                "label": handoff.identity.underlying,
                                "value": QUICK_HANDOFF_ENTRY_KEY,
                            }
                        ],
                        QUICK_HANDOFF_ENTRY_KEY,
                        False,
                    )
            except (HistoryValidationError, TypeError, ValueError):
                pass
            return [], None, True
        try:
            options = underlying_options(
                raw_catalog,
                kind,
                identity_mode,
                risk_type,
                risk_greek,
            )
            preferred = None
            try:
                selected_handoff = _requested_history_handoff(raw_request)
            except (HistoryValidationError, TypeError, ValueError):
                try:
                    selected_handoff = _pending_history_handoff(
                        raw_handoff,
                        consumed_nonce,
                    )
                except (HistoryValidationError, TypeError, ValueError):
                    selected_handoff = None
            if (
                selected_handoff is not None
                and selected_handoff.kind == str(kind or "risk").casefold()
                and selected_handoff.identity.identity_mode
                == str(identity_mode or "reported").casefold()
                and selected_handoff.identity.risk_type == str(risk_type)
                and selected_handoff.identity.risk_greek == str(risk_greek)
            ):
                preferred = catalog_key_for_handoff(
                    raw_catalog,
                    selected_handoff.to_mapping(),
                )
            selected = selected_value(options, current, preferred)
            return options, selected, selected is None
        except (HistoryValidationError, TypeError, ValueError):
            return [], None, True

    @app.callback(
        Output("data-history-request-store", "data"),
        Output("data-history-handoff-consumed-store", "data"),
        Input("data-history-handoff-store", "data"),
        Input("data-load-history-button", "n_clicks", allow_optional=True),
        Input("reset-generation-store", "data"),
        State("data-history-kind-tabs", "value", allow_optional=True),
        State("data-history-catalog-store", "data", allow_optional=True),
        State("data-underlying", "value", allow_optional=True),
        State("data-period", "value", allow_optional=True),
        State("data-custom-range", "start_date", allow_optional=True),
        State("data-custom-range", "end_date", allow_optional=True),
        State("data-history-request-store", "data", allow_optional=True),
        State("data-history-handoff-consumed-store", "data"),
    )
    def choose_history_request(
        raw_handoff,
        load_clicks,
        reset_generation,
        kind,
        raw_catalog,
        entry_key,
        period,
        start_date,
        end_date,
        current_request,
        consumed_nonce,
    ):
        triggered = ctx.triggered_id
        if triggered is None and raw_handoff is None:
            return no_update, no_update
        if (
            triggered == "data-load-history-button"
            and int(load_clicks or 0) <= 0
            and raw_handoff is None
        ):
            return no_update, no_update
        if triggered == "data-history-handoff-store":
            if raw_handoff is None:
                return no_update, no_update
            try:
                handoff_nonce = _stored_handoff_nonce(raw_handoff)
            except (HistoryValidationError, TypeError, ValueError):
                handoff_nonce = ""
            if handoff_nonce and handoff_nonce == str(consumed_nonce or ""):
                return no_update, no_update
        try:
            reset = int(reset_generation or 0)
        except (TypeError, ValueError):
            reset = 0
        try:
            if triggered == "data-load-history-button" and int(load_clicks or 0) > 0:
                if entry_key == QUICK_HANDOFF_ENTRY_KEY:
                    handoff = _stored_history_handoff(raw_handoff)
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
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    request_id=f"load-{int(load_clicks or 0)}-{reset}",
                ), no_update
            if triggered == "reset-generation-store":
                if current_request is None:
                    return no_update, no_update
                query = _request_query(current_request)
                return history_request_payload(
                    replace(query.handoff, reset_generation=reset),
                    period=query.period,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    request_id=f"reset-{reset}",
                ), no_update
            handoff = _stored_history_handoff(raw_handoff)
            nonce = _stored_handoff_nonce(raw_handoff)
            return history_request_payload(
                replace(handoff, reset_generation=reset),
                period=period,
                start_date=start_date,
                end_date=end_date,
                request_id=f"quick-{nonce}-{reset}",
            ), nonce
        except (HistoryValidationError, TypeError, ValueError) as error:
            detail = " ".join(str(error).splitlines()).strip() or type(error).__name__
            return {
                "error": detail,
                "request_id": f"invalid-{triggered}-{int(load_clicks or 0)}-{reset}",
            }, no_update

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
        Input("data-history-request-store", "data"),
        Input("data-history-cache-state-store", "data"),
        Input("reset-generation-store", "data"),
        running=[
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
            return None, "Choose an exact identity, then load its history."
        try:
            payload, status = query_history_bundle(
                repository,
                raw_request,
                cache_state,
                reset_generation,
            )
            return payload, status
        except (OSError, HistoryValidationError, TypeError, ValueError) as error:
            return None, f"History request failed: {error}"

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
        Output("data-player-mode-pill", "children"),
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
    "history_breadcrumb",
    "poll_archive_generation",
    "query_history_bundle",
    "register_callbacks",
    "serialize_history_bundle",
]
