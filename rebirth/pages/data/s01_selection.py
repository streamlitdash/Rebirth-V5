"""Pure direct-selection helpers owned by the V4 Data page."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from rebirth.history import (
    HistoryCatalogEntry,
    HistoryHandoff,
    HistoryIdentityCatalog,
    HistoryValidationError,
)


def _catalog(value: object) -> HistoryIdentityCatalog:
    return (
        value
        if isinstance(value, HistoryIdentityCatalog)
        else HistoryIdentityCatalog.from_mapping(value)
    )


def effective_identity_mode(kind: object, mode: object) -> str:
    """Market always uses raw Underlying; Risk defaults to reported identity."""

    if str(kind or "risk").strip().casefold() == "market":
        return "underlying"
    selected = str(mode or "reported").strip().casefold()
    return selected if selected in {"reported", "underlying"} else "reported"


def matching_entries(
    raw_catalog: object,
    *,
    kind: object,
    identity_mode: object,
    risk_type: object = None,
    risk_greek: object = None,
) -> tuple[HistoryCatalogEntry, ...]:
    catalog = _catalog(raw_catalog)
    selected_kind = str(kind or "risk").strip().casefold()
    selected_mode = effective_identity_mode(selected_kind, identity_mode)
    selected_type = str(risk_type or "").strip()
    selected_greek = str(risk_greek or "").strip()
    return tuple(
        entry
        for entry in catalog.entries
        if entry.kind == selected_kind
        and entry.identity.identity_mode == selected_mode
        and (not selected_type or entry.identity.risk_type == selected_type)
        and (not selected_greek or entry.identity.risk_greek == selected_greek)
    )


def risk_type_options(
    raw_catalog: object, kind: object, identity_mode: object
) -> list[dict[str, str]]:
    values = sorted(
        {
            entry.identity.risk_type
            for entry in matching_entries(
                raw_catalog,
                kind=kind,
                identity_mode=identity_mode,
            )
        },
        key=str.casefold,
    )
    return [{"label": value, "value": value} for value in values]


def risk_greek_options(
    raw_catalog: object,
    kind: object,
    identity_mode: object,
    risk_type: object,
) -> list[dict[str, str]]:
    values = sorted(
        {
            entry.identity.risk_greek
            for entry in matching_entries(
                raw_catalog,
                kind=kind,
                identity_mode=identity_mode,
                risk_type=risk_type,
            )
        },
        key=str.casefold,
    )
    return [{"label": value, "value": value} for value in values]


def underlying_options(
    raw_catalog: object,
    kind: object,
    identity_mode: object,
    risk_type: object,
    risk_greek: object,
) -> list[dict[str, str]]:
    entries = matching_entries(
        raw_catalog,
        kind=kind,
        identity_mode=identity_mode,
        risk_type=risk_type,
        risk_greek=risk_greek,
    )
    counts = Counter(entry.identity.underlying for entry in entries)
    options = []
    for entry in entries:
        label = entry.identity.underlying
        if counts[label] > 1:
            label = f"{label} · {', '.join(entry.identity.source_types)}"
        options.append({"label": label, "value": entry.key})
    return options


def selected_value(
    options: Sequence[dict[str, str]],
    current: object = None,
    preferred: object = None,
) -> str | None:
    """Keep a valid current/preferred choice, otherwise choose the first option."""

    values = [option["value"] for option in options]
    for candidate in (preferred, current):
        if candidate in values:
            return str(candidate)
    return values[0] if values else None


def catalog_key_for_handoff(raw_catalog: object, raw_handoff: object) -> str | None:
    try:
        catalog = _catalog(raw_catalog)
        handoff = HistoryHandoff.from_mapping(raw_handoff)
    except (HistoryValidationError, TypeError, ValueError):
        return None
    for entry in catalog.entries:
        if entry.kind == handoff.kind and entry.identity == handoff.identity:
            return entry.key
    return None


def direct_history_handoff(
    raw_catalog: object,
    entry_key: object,
    *,
    kind: object,
    reset_generation: object,
) -> HistoryHandoff:
    catalog = _catalog(raw_catalog)
    entry = catalog.resolve(entry_key)
    selected_kind = str(kind or "risk").strip().casefold()
    if entry.kind != selected_kind:
        raise HistoryValidationError("selected identity belongs to another history tab")
    if isinstance(reset_generation, bool):
        raise HistoryValidationError("reset generation must be an integer")
    try:
        reset = int(reset_generation or 0)
    except (TypeError, ValueError) as exc:
        raise HistoryValidationError("reset generation must be an integer") from exc
    return entry.to_handoff(reset_generation=reset)


__all__ = [
    "catalog_key_for_handoff",
    "direct_history_handoff",
    "effective_identity_mode",
    "matching_entries",
    "risk_greek_options",
    "risk_type_options",
    "selected_value",
    "underlying_options",
]
