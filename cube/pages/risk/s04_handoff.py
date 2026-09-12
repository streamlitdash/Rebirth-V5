"""Typed Quick Risk/Market handoff into the V5 native Data page."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from numbers import Integral
from uuid import uuid4

from dash import Dash, Input, Output, State, ctx, no_update

from cube.history import HistoryHandoff, RiskFilterView
from cube.ui.s01_constants import RISK_FILTER_DIMENSION_FIELDS
from cube.ui.s02_aggregation import parse_row_key
from cube.app.s02_contracts import RefreshManagerProtocol


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

    if len(dimension_values) != len(RISK_FILTER_DIMENSION_FIELDS):
        raise ValueError("Risk filter values do not match the reporting schema")
    filters = [("Split", _values(selected_splits))]
    filters.extend(
        (field.external_name, _values(raw_values))
        for field, raw_values in zip(
            RISK_FILTER_DIMENSION_FIELDS,
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


def explorer_identity(selection: object, active_risk_type: object = None) -> tuple[str, str] | None:
    """Resolve only explicit underlying rows; group labels are not identities."""
    if not isinstance(selection, Mapping):
        return None
    context = parse_row_key(selection.get("key"))
    underlying = context.get("underlying") or context.get("reported underlying")
    risk_type = context.get("risk type") or active_risk_type
    greek = context.get("risk greek")
    if not all((risk_type, greek, underlying)):
        return None
    mode = "underlying" if context.get("underlying") else "reported"
    return " | ".join((str(risk_type), greek, underlying)), mode


def register_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol | None,
    *,
    data_href: str,
) -> None:
    """Each tab owns its controls; inactive Dash tabs are not mounted."""

    def register_source(prefix, identity_id, kind, *, explorer=False):
        identity_property = "data" if explorer else "value"

        @app.callback(
            Output(f"{prefix}-open-data", "disabled"),
            Input(identity_id, identity_property),
            (Input if explorer else State)("risk-type-tabs", "value"),
        )
        def enable_open(identity, active_risk_type):
            selected = explorer_identity(identity, active_risk_type) if explorer else identity
            return not (refresh_manager is not None and selected)

        @app.callback(
            Output("data-history-handoff-store", "data", allow_duplicate=True),
            Output("data-route-location", "href", allow_duplicate=True),
            Output(f"{prefix}-data-status", "children"),
            Input(f"{prefix}-open-data", "n_clicks"),
            Input(identity_id, identity_property),
            State("split-filter", "value"),
            State("dimension-filter-values-store", "data"),
            State("risk-filter-exclude-applied-store", "data"),
            State("reset-generation-store", "data"),
            State("risk-type-tabs", "value"),
            prevent_initial_call=True,
        )
        def open_in_data(clicks, identity, splits, dimensions, exclude, reset, risk_type):
            # A remounted tab or changed selection must never navigate by itself.
            if ctx.triggered_id != f"{prefix}-open-data" or not clicks:
                return no_update, no_update, ""
            if refresh_manager is None:
                return no_update, no_update, "Data history is unavailable."
            try:
                mode = "underlying" if kind == "market" else "reported"
                if explorer:
                    resolved = explorer_identity(identity, risk_type)
                    if resolved is None:
                        raise ValueError("Select an underlying row with a risk type and Greek first")
                    identity, mode = resolved
                handoff = build_history_handoff(
                    refresh_manager, kind=kind, combine_udl=identity,
                    identity_mode=mode, reset_generation=reset,
                    selected_splits=splits, dimension_values=dimensions,
                    exclude_value=exclude,
                )
            except (AttributeError, LookupError, TypeError, ValueError, RuntimeError) as error:
                return no_update, no_update, f"Could not open Data: {error}"
            return _handoff_payload(handoff, kind), data_href, "Opening exact history…"

    register_source("quick-search", "quick-search-combine-udl", "risk")
    register_source("quick-market", "quick-market-combine-udl", "market")
    register_source("risk-explorer", "selected-cell-store", "risk", explorer=True)


__all__ = [
    "build_history_handoff",
    "build_risk_filter_view",
    "explorer_identity",
    "register_callbacks",
]
