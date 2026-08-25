"""V5 Risk-only immutable Filter View defaults.

The V5 demo retains the legacy fixture labels (Macro/Credit/Hedge) without
rewriting the annual archive.  They are explicit aliases for the product
names Activity 1/2/3, not fuzzy matches.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

import pandas as pd

from cube.ui.s01_constants import RISK_FILTER_DIMENSION_FIELDS


DEFAULT_RISK_FILTER_LABEL: Final = "Default - Activities 1-3"
DEFAULT_RISK_ACTIVITIES: Final = ("Activity 1", "Activity 2", "Activity 3")
DEFAULT_RISK_ACTIVITY_ALIASES: Final = {
    "Activity 1": ("Activity 1", "Macro"),
    "Activity 2": ("Activity 2", "Credit"),
    "Activity 3": ("Activity 3", "Hedge"),
}
_TEMP_PREFIX: Final = "temp_replace_me - "


@dataclass(frozen=True)
class DefaultRiskFilterSelection:
    """Resolved current-data values plus any unavailable canonical activity."""

    activities: tuple[str, ...]
    missing: tuple[str, ...]

    @property
    def warning(self) -> str:
        if not self.missing:
            return ""
        return "Default Risk activities are unavailable: " + ", ".join(self.missing)


def _activity_key(value: object) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()
    if normalized.startswith(_TEMP_PREFIX):
        normalized = normalized[len(_TEMP_PREFIX) :]
    return normalized


def resolve_default_risk_activities(
    available: Sequence[object],
    *,
    aliases: Mapping[str, Sequence[str]] = DEFAULT_RISK_ACTIVITY_ALIASES,
) -> DefaultRiskFilterSelection:
    """Resolve exact configured aliases against one committed Activity column."""

    if tuple(aliases) != DEFAULT_RISK_ACTIVITIES:
        raise ValueError(
            "Default Risk activity aliases must cover Activity 1-3 in order"
        )
    alias_owner: dict[str, str] = {}
    for canonical, configured in aliases.items():
        if isinstance(configured, (str, bytes)) or not configured:
            raise ValueError(f"Aliases for {canonical!r} must be a non-empty sequence")
        for alias in configured:
            key = _activity_key(alias)
            if not key:
                raise ValueError(f"Aliases for {canonical!r} must not be blank")
            previous = alias_owner.setdefault(key, canonical)
            if previous != canonical:
                raise ValueError(f"Activity alias {alias!r} belongs to two defaults")

    values_by_activity: dict[str, list[str]] = {
        canonical: [] for canonical in DEFAULT_RISK_ACTIVITIES
    }
    seen_values: set[str] = set()
    for raw_value in available:
        value = str(raw_value).strip()
        if not value or value in seen_values:
            continue
        seen_values.add(value)
        canonical = alias_owner.get(_activity_key(value))
        if canonical is not None:
            values_by_activity[canonical].append(value)

    missing = tuple(
        canonical
        for canonical in DEFAULT_RISK_ACTIVITIES
        if not values_by_activity[canonical]
    )
    activities = tuple(
        value
        for canonical in DEFAULT_RISK_ACTIVITIES
        for value in values_by_activity[canonical]
    )
    return DefaultRiskFilterSelection(activities=activities, missing=missing)


def default_risk_filter_values(frame: pd.DataFrame) -> tuple[list[str], ...]:
    """Return dropdown values aligned to the governed Risk filter registry."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Risk Filter View source must be a pandas DataFrame")
    if "activity" not in frame:
        raise ValueError("Risk Filter View source is missing Activity")
    resolved = resolve_default_risk_activities(
        frame["activity"].dropna().astype(str).tolist()
    )
    return tuple(
        list(resolved.activities) if field.key == "activity" else []
        for field in RISK_FILTER_DIMENSION_FIELDS
    )


def default_risk_filter_payload(frame: pd.DataFrame) -> dict[str, list[str]]:
    """Return the immutable default as the ordinary Risk filter payload."""

    values = default_risk_filter_values(frame)
    return {
        field.key: selected
        for field, selected in zip(RISK_FILTER_DIMENSION_FIELDS, values, strict=True)
    }


__all__ = [
    "DEFAULT_RISK_ACTIVITIES",
    "DEFAULT_RISK_ACTIVITY_ALIASES",
    "DEFAULT_RISK_FILTER_LABEL",
    "DefaultRiskFilterSelection",
    "default_risk_filter_payload",
    "default_risk_filter_values",
    "resolve_default_risk_activities",
]
