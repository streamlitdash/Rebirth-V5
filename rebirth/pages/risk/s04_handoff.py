"""Typed Quick Risk/Market handoff into the V4 native Data page."""

from __future__ import annotations

from collections.abc import Sequence
from numbers import Integral
from uuid import uuid4

from dash import Dash, Input, Output, State, ctx, no_update

from rebirth.history import HistoryHandoff, RiskFilterView
from rebirth.ui.s01_constants import FILTER_DIMENSION_FIELDS
from rebirth.app.s02_contracts import RefreshManagerProtocol


def _values(raw: object) -> tuple[str, ...]:
    if raw is None:
        return ()
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
        raise TypeError("Risk filter selections must be sequences")
    return tuple(str(value).strip() for value in raw if str(value).strip())


def build_risk_filter_view(
    selected_splits: object,
    dimension_values: Sequence[object],
    exclude_value: object,
) -> RiskFilterView:
    """Capture the visible Risk Filter View using archive column names."""

    if len(dimension_values) != len(FILTER_DIMENSION_FIELDS):
        raise ValueError("Risk filter values do not match the reporting schema")
    filters = [("Split", _values(selected_splits))]
    filters.extend(
        (field.external_name, _values(raw_values))
        for field, raw_values in zip(
            FILTER_DIMENSION_FIELDS,
            dimension_values,
            strict=True,
        )
    )
    excluded = "exclude" in _values(exclude_value)
    return RiskFilterView(
        filters=tuple((column, values) for column, values in filters if values),
        exclude_selected=excluded,
    )


def build_history_handoff(
    refresh_manager: RefreshManagerProtocol,
    *,
    kind: str,
    combine_udl: object,
    identity_mode: str,
    reset_generation: object,
    selected_splits: object = None,
    dimension_values: Sequence[object] = (),
    exclude_value: object = None,
) -> HistoryHandoff:
    """Resolve a selected catalog key and produce a strict session handoff."""

    selected = str(combine_udl or "").strip()
    if not selected:
        raise ValueError("Select an exact identity first")
    if reset_generation is None:
        reset = 0
    elif isinstance(reset_generation, bool) or not isinstance(
        reset_generation, Integral
    ):
        raise ValueError("reset generation must be an integer")
    else:
        reset = int(reset_generation)
    resolved = refresh_manager.resolve_history_identity(
        kind,
        selected,
        identity_mode=identity_mode,
    )
    filter_view = (
        build_risk_filter_view(
            selected_splits,
            dimension_values,
            exclude_value,
        )
        if kind == "risk"
        else None
    )
    return HistoryHandoff.from_resolved_identity(
        resolved,
        metric="risk" if kind == "risk" else "current",
        filter_view=filter_view,
        reset_generation=reset,
    )


def _handoff_payload(handoff: HistoryHandoff, kind: str) -> dict[str, object]:
    """Give every navigation a fresh identity, even after a page remount."""

    return {
        "handoff": handoff.to_mapping(),
        "nonce": f"{kind}-{handoff.source_revision}-{uuid4().hex}",
    }


def register_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol | None,
    *,
    data_href: str,
) -> None:
    """Register the only cross-page writer for the session handoff store."""

    @app.callback(
        Output("quick-search-open-data", "disabled"),
        Output("quick-market-open-data", "disabled"),
        Input("quick-search-combine-udl", "value"),
        Input("quick-market-combine-udl", "value"),
    )
    def enable_open_buttons(risk_identity, market_identity):
        available = refresh_manager is not None
        return not (available and risk_identity), not (available and market_identity)

    @app.callback(
        Output("data-history-handoff-store", "data"),
        Output("data-route-location", "href"),
        Output("quick-search-data-status", "children"),
        Output("quick-market-data-status", "children"),
        Input("quick-search-open-data", "n_clicks"),
        Input("quick-market-open-data", "n_clicks"),
        Input("quick-search-combine-udl", "value"),
        Input("quick-market-combine-udl", "value"),
        State("split-filter", "value"),
        State("dimension-filter-values-store", "data"),
        State("risk-filter-exclude-applied-store", "data"),
        State("reset-generation-store", "data"),
        prevent_initial_call=True,
    )
    def open_in_data(
        _risk_clicks,
        _market_clicks,
        risk_identity,
        market_identity,
        selected_splits,
        dimension_values,
        exclude_value,
        reset_generation,
    ):
        if refresh_manager is None:
            return no_update, no_update, "Data history is unavailable.", no_update
        if ctx.triggered_id == "quick-search-combine-udl":
            return no_update, no_update, "", no_update
        if ctx.triggered_id == "quick-market-combine-udl":
            return no_update, no_update, no_update, ""
        kind = "market" if ctx.triggered_id == "quick-market-open-data" else "risk"
        try:
            handoff = build_history_handoff(
                refresh_manager,
                kind=kind,
                combine_udl=(market_identity if kind == "market" else risk_identity),
                identity_mode=("underlying" if kind == "market" else "reported"),
                reset_generation=reset_generation,
                selected_splits=selected_splits,
                dimension_values=dimension_values,
                exclude_value=exclude_value,
            )
        except (
            AttributeError,
            LookupError,
            TypeError,
            ValueError,
            RuntimeError,
        ) as error:
            message = f"Could not open Data: {error}"
            if kind == "market":
                return no_update, no_update, no_update, message
            return no_update, no_update, message, no_update
        message = "Opening exact history…"
        payload = _handoff_payload(handoff, kind)
        if kind == "market":
            return payload, data_href, no_update, message
        return payload, data_href, message, no_update


__all__ = [
    "build_history_handoff",
    "build_risk_filter_view",
    "register_callbacks",
]
