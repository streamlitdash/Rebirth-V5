"""Page-owned lazy query and playback callbacks for V5 Data history."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from typing import Mapping

import numpy as np
import pandas as pd
from dash import ClientsideFunction, Dash, Input, Output, State, ctx, no_update

from cube.history import (
    HISTORY_CANONICAL_CELL_BUDGET,
    HISTORY_RAW_ROW_BUDGET,
    ArchiveHistoryRepository,
    HistoryBundle,
    HistoryCatalogEntry,
    HistoryIdentityCatalog,
    HistoryHandoff,
    HistoryQuery,
    HistoryValidationError,
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
    series = "Risk" if handoff.kind == "risk" else "Current"
    sources = ", ".join(identity.source_types)
    return (
        f"{handoff.kind.title()}  >  {identity.risk_type}  >  {identity.risk_greek} "
        f" >  {identity.underlying}  |  {series}  |  {mode}  |  {sources}"
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
    refresh_manager=None,
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
        return None, "Preparing the archive index..."
    revision, rows = (
        refresh_manager.read_data_history(handoff)
        if refresh_manager is not None else (0, pd.DataFrame())
    )
    bundle = repository.read(query, current_rows=rows, current_revision=revision,
                             chart_only=True)
    payload = serialize_history_bundle(bundle)
    if bundle.empty:
        status = "No current or archived rows match this identity and period."
    else:
        status = (
            f"Loaded {len(bundle.dates):,} dates and {len(bundle.values):,} plotted "
            f"values ({bundle.resolved_start} to {bundle.resolved_end})."
        )
        if bundle.ordering.status != "ORDERED":
            status += " Shared tenor order is used where dated underlyings have different ranks."
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
    refresh_manager=None,
) -> tuple[dict[str, object] | None, str]:
    """Combine archive identities with compact committed current choices."""
    if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
        return None, "Preparing Data choices..."
    archive = repository.catalog()
    entries = {entry.key: entry for entry in archive.entries}
    revision = 0
    if refresh_manager is not None:
        for resolved in refresh_manager.data_history_identities():
            handoff = HistoryHandoff.from_resolved_identity(
                resolved, metric="risk" if resolved.kind == "risk" else "current"
            )
            entry = HistoryCatalogEntry(
                kind=handoff.kind, identity=handoff.identity,
                source_revision=handoff.source_revision,
                snapshot_date=handoff.snapshot_date,
            )
            entries[entry.key] = entry
            revision = max(revision, entry.source_revision)
    ordered = tuple(sorted(entries.values(), key=lambda entry: (
        entry.kind, entry.identity.risk_type, entry.identity.risk_greek,
        entry.identity.underlying.casefold(), entry.identity.identity_mode,
        entry.identity.source_types,
    )))
    catalog = HistoryIdentityCatalog(
        generation=f"{archive.generation}:current:{revision}", entries=ordered
    )
    status = (
        f"Ready: {len(ordered):,} current/archive identity choices."
        if ordered else "No choices yet. Wait for the initial data refresh to finish."
    )
    return catalog.to_mapping(), status


def register_callbacks(app: Dash, repository: ArchiveHistoryRepository, refresh_manager=None) -> None:
    """Register independent search metadata, one selection and one history load."""
    from .s04_workspace import DataChoices, describe, encode_choice, selection_for_handoff, workspace_request
    choices = DataChoices(refresh_manager, repository)

    @app.callback(
        Output("data-current-choices", "data"),
        Input("refresh-commit-revision", "children"),
        Input("reset-generation-store", "data"),
    )
    def current_choices(_revision, reset):
        return choices.metadata(reset)

    @app.callback(
        Output("data-archive-choices", "data"), Output("data-archive-status", "children"),
        Input("data-history-generation-interval", "n_intervals"),
        Input("clear-cache-complete-store", "data"),
    )
    def archive_choices(_tick, reset):
        try:
            repository.clear_for_reset_generation(int(reset or 0))
            metadata = choices.archive_metadata()
            return metadata, f"{len(metadata['choices']):,} archived series available."
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            return {"choices": []}, f"Archive unavailable: {error}. Current data is still available."

    app.clientside_callback(
        ClientsideFunction(namespace="cubeData", function_name="searchCurrent"),
        Output("data-underlying", "options", allow_duplicate=True), Output("data-search-status", "children"),
        Input("data-underlying", "search_value"), Input("data-selected-option", "data"),
        Input("committed-revision-poll", "n_intervals"),
        State("data-current-choices", "data"),
        State("data-archive-choices", "data"),
        State("data-underlying", "value"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("data-selection-store", "data"), Output("data-underlying", "value"),
        Output("data-selected-option", "data"), Output("data-market-choice", "options"),
        Output("data-market-choice", "value"), Output("data-history-kind-tabs", "value"),
        Output("data-history-handoff-consumed-store", "data"),
        Output("data-selection-status", "children"),
        Output("data-period", "value"), Output("data-custom-range", "start_date"),
        Output("data-custom-range", "end_date"),
        Output("data-underlying", "options"),
        Input("data-underlying", "value"), Input("data-history-handoff-store", "data"),
        Input("reset-generation-store", "data"),
        State("data-selection-store", "data"), State("data-history-kind-tabs", "value"),
        State("data-history-handoff-consumed-store", "data"),
        State("data-history-request-store", "data"),
    )
    def choose_identity(token, raw_handoff, reset, selected, mode, consumed, saved):
        trigger = ctx.triggered_id
        unchanged = (no_update,) * 12
        restored = False
        try:
            nonce = _stored_handoff_nonce(raw_handoff) if raw_handoff else ""
            incoming = raw_handoff and nonce != str(consumed or "")
            if incoming:
                handoff = replace(_stored_history_handoff(raw_handoff), reset_generation=int(reset or 0))
                token = encode_choice("handoff", handoff.to_mapping())
                mode = handoff.kind
            elif (not token and isinstance(saved, Mapping) and saved.get("selection")
                  and (not selected or selected.get("token") == saved["selection"].get("token"))):
                selected = saved["selection"]
                token = selected["token"]
                mode = saved.get("display_mode", "risk")
                handoff = choices.resolve(token, reset)
                restored = True
            elif not token and isinstance(selected, Mapping) and selected.get("token"):
                # Empty dropdown hydration must not clear a newer selection.
                token = selected["token"]
                handoff = choices.resolve(token, reset)
            elif token:
                if selected and selected.get("token") == token and trigger != "reset-generation-store":
                    return unchanged
                handoff = choices.resolve(token, reset)
            else:
                return None, None, None, [], None, no_update, no_update, "Choose an underlying above.", no_update, no_update, no_update, no_update
            selection = selection_for_handoff(handoff, refresh_manager, repository)
            selection["token"] = token
            options = [{"label": describe(HistoryHandoff.from_mapping(raw)), "value": str(index)}
                       for index, raw in enumerate(selection["markets"])]
            label = f"{handoff.kind.title()}  |  {describe(handoff)}"
            scope = ""
            if handoff.filter_view and handoff.filter_view.filters:
                scope = "Risk Explorer filters are preserved. Market quotes use their raw identity."
            market_value = "0" if options else None
            if restored and options:
                saved_market = saved.get("handoffs", {}).get("market", {}).get("identity")
                market_value = next((str(index) for index, market in enumerate(selection["markets"])
                                     if market["identity"] == saved_market), market_value)
            period_values = (saved.get("period", "all"), saved.get("start_date"), saved.get("end_date")) if restored else (no_update,) * 3
            selected_option = {"label": label, "value": token}
            return (selection, token, selected_option, options, market_value,
                    mode or handoff.kind, (nonce if incoming else no_update), scope, *period_values,
                    [selected_option])
        except (OSError, RuntimeError, LookupError, TypeError, ValueError) as error:
            return (None, no_update, no_update, [], None, no_update, no_update,
                    f"Could not select this identity: {error}", no_update, no_update, no_update, no_update)

    @app.callback(
        Output("data-history-request-store", "data"),
        Output("data-identity-breadcrumb", "children"),
        Output("data-market-choice-control", "hidden"), Output("data-custom-range-control", "hidden"),
        Input("data-selection-store", "data"), Input("data-history-kind-tabs", "value"),
        Input("data-market-choice", "value"), Input("data-period", "value"),
        Input("data-custom-range", "start_date"), Input("data-custom-range", "end_date"),
        Input("reset-generation-store", "data"),
    )
    def choose_request(selection, mode, market_index, period, start, end, reset):
        show_market = bool(selection and len(selection.get("markets", [])) > 1 and mode in {"market", "both"})
        try:
            request = workspace_request(selection, mode, market_index, period, start, end, reset)
            if request is not None:
                request["selection"] = selection
            label = selection.get("label", "") if selection else ""
            return request, label, not show_market, period != "custom"
        except (TypeError, ValueError) as error:
            return {"error": str(error), "display_mode": mode}, "Choose a valid period.", not show_market, period != "custom"

    @app.callback(
        Output("data-history-bundle-store", "data"), Output("data-history-status", "children"),
        Input("data-history-request-store", "data"),
        Input("refresh-commit-revision", "children"), Input("reset-generation-store", "data"),
        State("refresh-action-request", "data"),
    )
    def load_workspace(request, _revision, reset, refresh_request):
        receipt = {
            "owner": "data-history", "revision": int(_revision or 0),
            "request_id": refresh_request.get("id") if isinstance(refresh_request, Mapping) else None,
            "status": "rendered", "message": "",
        }
        def finish(payload, message):
            payload["refresh"] = receipt
            key_parts = [receipt, payload.get("mode"), payload.get("errors"),
                         {kind: bundle.get("key") for kind, bundle in payload["bundles"].items()}]
            payload["key"] = hashlib.sha256(json.dumps(key_parts, sort_keys=True).encode()).hexdigest()
            return payload, message
        if not request:
            return finish({"mode": "risk", "bundles": {}, "errors": {}}, "Choose an underlying; its data loads automatically.")
        mode = request.get("display_mode", "risk")
        payload = {"mode": mode, "bundles": {}, "errors": {}}
        if request.get("error"):
            receipt.update(status="failed", message=request["error"])
            return finish(payload, request["error"])
        messages = []
        for kind in (["risk", "market"] if mode == "both" else [mode]):
            handoff = request.get("handoffs", {}).get(kind)
            if not handoff:
                payload["errors"][kind] = "No exact Market series is available for this Risk selection."
                continue
            try:
                single = {"handoff": handoff, "period": request.get("period", "all"),
                          "start_date": request.get("start_date"), "end_date": request.get("end_date")}
                # No archive-selector dependency: an incoming exact selection can
                # load immediately while the separate archive label index builds.
                bundle, status = query_history_bundle(repository, single,
                    {"generation": "selected-query"}, reset, refresh_manager)
                payload["bundles"][kind] = bundle
                messages.append(f"{kind.title()}: {status}")
            except (OSError, RuntimeError, TypeError, ValueError) as error:
                payload["errors"][kind] = str(error)
                messages.append(f"{kind.title()}: {error}")
                receipt.update(status="failed", message=str(error))
        return finish(payload, " ".join(messages))

    app.clientside_callback(
        ClientsideFunction(namespace="cubeData", function_name="play"),
        Output("data-risk-chart", "figure"), Output("data-market-chart", "figure"),
        Output("data-risk-table", "data"), Output("data-risk-table", "columns"),
        Output("data-market-table", "data"), Output("data-market-table", "columns"),
        Output("data-risk-table", "style_data_conditional"), Output("data-market-table", "style_data_conditional"),
        Output("data-risk-panel", "style"), Output("data-market-panel", "style"),
        Output("data-risk-title", "children"), Output("data-market-title", "children"),
        Output("data-player-slider", "max"), Output("data-player-slider", "marks"),
        Output("data-player-slider", "value"), Output("data-player-slider", "disabled"),
        Output("data-player-date-pill", "children"), Output("data-player-button", "children"),
        Output("data-player-button", "disabled"), Output("data-player-interval", "disabled"),
        Output("data-player-state-store", "data"),
        Output("data-history-results", "data-refresh-render"),
        Input("data-history-bundle-store", "data"), Input("data-player-button", "n_clicks"),
        Input("data-player-interval", "n_intervals"), Input("data-player-slider", "value"),
        Input("data-player-visibility-store", "data"), State("data-player-state-store", "data"),
    )


__all__ = ["history_request_payload", "history_breadcrumb", "query_history_bundle",
           "serialize_history_bundle", "register_callbacks"]
