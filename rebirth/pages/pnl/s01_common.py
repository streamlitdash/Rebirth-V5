"""Shared contracts for the single authoritative V4 P&L page."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol, runtime_checkable

import pandas as pd

from rebirth.app.s02_contracts import AdjustmentRepositoryProtocol
from rebirth.ui.s01_constants import FILTER_DIMENSION_FIELDS
from rebirth.ui.s03_filters import SavedFilterViewControls


DISPLAY_COLUMNS = (
    "Risk Type",
    "Risk Greek",
    "Portfolio",
    "SignoffGroup",
    "ConcertoField",
    "PL",
    "Adjustment",
)
GRID_ROW_ID = "id"
PL_AGGREGATE_TOGGLE_TYPE = "pnl-aggregate-row-toggle"
PL_AGGREGATE_HISTORY_CELL_TYPE = "pnl-aggregate-history-cell"
PL_FILTER_FIELDS = FILTER_DIMENSION_FIELDS
PL_FILTER_IDS = {
    field.key: f"pnl-{field.key}-filter" for field in FILTER_DIMENSION_FIELDS
}
PL_FILTER_EXCLUDE_ID = "pnl-filter-exclude-selected"
PL_SAVED_VIEW_CONTROLS = SavedFilterViewControls(
    scope="pnl",
    prefix="pnl",
    fields=PL_FILTER_FIELDS,
    filter_ids=PL_FILTER_IDS,
    exclude_id=PL_FILTER_EXCLUDE_ID,
)
PL_FILTER_NOTE = (
    "Include mode uses OR within one filter (for example B or D) and AND across "
    "filters. Exclude mode removes a row if it matches any selected value in any "
    "populated filter. Leave blank for all values; live P&L selections remain "
    "independent from Risk and Stock."
)

SendFunction = Callable[[pd.DataFrame], None]
PLHistoryFunction = Callable[[], pd.DataFrame]


@runtime_checkable
class PLHistoryQueryProtocol(Protocol):
    """Bounded history source used by the scalable disclosure callbacks."""

    def clear(self) -> None: ...

    def hierarchy(
        self,
        *,
        open_paths: object = None,
        filters: Mapping[str, Sequence[object] | None] | None = None,
        exclude_selected: bool = False,
    ) -> object: ...

    def series(
        self,
        *,
        path: Sequence[object] = (),
        history_types: Sequence[str] = (),
        preset: str = "all",
        start_date: object = None,
        end_date: object = None,
        filters: Mapping[str, Sequence[object] | None] | None = None,
        criteria: Mapping[str, Sequence[object] | None] | None = None,
        exclude_selected: bool = False,
    ) -> object: ...


@dataclass(frozen=True)
class PLSendConfig:
    mapping_source: str | Path
    adjustment_repository: AdjustmentRepositoryProtocol
    send_sog_pl: SendFunction
    send_portfolio_pl: SendFunction
    # Legacy DataFrame/callable sources remain injectable; production prefers
    # the lazy SQL repository over completed unified schema-v4 Parquet leaves.
    history_source: (
        str | Path | pd.DataFrame | PLHistoryFunction | PLHistoryQueryProtocol | None
    ) = None


def pl_filter_map(
    values: Sequence[Sequence[str] | None],
) -> dict[str, list[str]]:
    """Normalize P&L-local reporting filters without sharing Risk/Stock state."""
    if len(values) != len(PL_FILTER_FIELDS):
        raise ValueError(
            f"Expected {len(PL_FILTER_FIELDS)} P&L filters; found {len(values)}"
        )
    return {
        field.key: [str(value) for value in (selected or []) if str(value).strip()]
        for field, selected in zip(PL_FILTER_FIELDS, values, strict=True)
    }


def pl_filter_options(frame: pd.DataFrame) -> dict[str, list[dict[str, str]]]:
    """Return stable options for each independent P&L reporting filter."""
    result: dict[str, list[dict[str, str]]] = {}
    for field in PL_FILTER_FIELDS:
        canonical: dict[str, str] = {}
        for raw in frame[field.key].dropna().tolist():
            value = str(raw).strip()
            if value:
                canonical.setdefault(value.casefold(), value)
        values = sorted(canonical.values(), key=str.casefold)
        result[field.key] = [{"label": value, "value": value} for value in values]
    return result


def pl_external_filter_map(
    values: Sequence[Sequence[object] | None],
) -> dict[str, list[str]]:
    """Normalize the five P&L selectors to canonical external columns."""

    if len(values) != len(FILTER_DIMENSION_FIELDS):
        raise ValueError(
            f"Expected {len(FILTER_DIMENSION_FIELDS)} P&L filters; found {len(values)}"
        )
    return {
        field.external_name: [
            text for value in (selected or []) if (text := str(value).strip())
        ]
        for field, selected in zip(FILTER_DIMENSION_FIELDS, values, strict=True)
    }


def apply_pl_filters(
    frame: pd.DataFrame,
    selections: Mapping[str, Sequence[object] | None] | None,
    *,
    exclude_selected: bool = False,
) -> pd.DataFrame:
    """Apply OR within a selector and include-AND/exclude-OR across selectors."""

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("P&L filter source must be a pandas DataFrame")
    normalized = {
        str(column): {
            text.casefold() for value in (values or []) if (text := str(value).strip())
        }
        for column, values in (selections or {}).items()
    }
    populated = {column: values for column, values in normalized.items() if values}
    if not populated or frame.empty:
        return frame.copy(deep=True)
    missing = sorted(column for column in populated if column not in frame)
    if missing:
        raise ValueError(f"P&L filter source is missing filter columns: {missing}")

    if exclude_selected:
        matched = pd.Series(False, index=frame.index)
        for column, selected in populated.items():
            values = frame[column].astype("string").str.strip().str.casefold()
            matched |= values.isin(selected).fillna(False)
        keep = ~matched
    else:
        keep = pd.Series(True, index=frame.index)
        for column, selected in populated.items():
            values = frame[column].astype("string").str.strip().str.casefold()
            keep &= values.isin(selected).fillna(False)
    return frame.loc[keep].copy(deep=True)


__all__ = [
    "DISPLAY_COLUMNS",
    "GRID_ROW_ID",
    "PL_AGGREGATE_TOGGLE_TYPE",
    "PL_AGGREGATE_HISTORY_CELL_TYPE",
    "PL_FILTER_FIELDS",
    "PL_FILTER_EXCLUDE_ID",
    "PL_FILTER_IDS",
    "PL_FILTER_NOTE",
    "PL_SAVED_VIEW_CONTROLS",
    "PLHistoryFunction",
    "PLHistoryQueryProtocol",
    "PLSendConfig",
    "SendFunction",
    "apply_pl_filters",
    "pl_external_filter_map",
    "pl_filter_map",
    "pl_filter_options",
]
