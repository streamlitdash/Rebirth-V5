"""V5 Risk-page constants, controls, labels, and common presentation helpers."""

from __future__ import annotations

from typing import Sequence

import pandas as pd

from cube.ui.s01_constants import DIMENSION_FILTER_IDS, FILTER_DIMENSION_FIELDS
from cube.ui.s03_filters import SavedFilterViewControls

from .s03_defaults import DEFAULT_RISK_FILTER_LABEL


_ABSENT_TENOR_LABELS = frozenset(("", "n/a", "na", "spot", "unspecified"))
DETAIL_TENOR_VIEW_LABELS = {
    "auto": "Auto",
    "swap": "Tenor Swap line",
    "option": "Tenor Option line",
    "surface": "Surface",
}
RISK_SAVED_VIEW_CONTROLS = SavedFilterViewControls(
    scope="risk",
    prefix="risk",
    fields=FILTER_DIMENSION_FIELDS,
    filter_ids=DIMENSION_FILTER_IDS,
    exclude_id="risk-filter-exclude-selected",
    base_label=DEFAULT_RISK_FILTER_LABEL,
)
RISK_FILTER_NOTE = (
    "Include mode uses OR within one filter (B or D) and AND across filters "
    "(Credit and Portfolio B or D). Exclude mode removes a row if it matches "
    "any selected value in any populated filter. Leave a filter blank for all "
    "values; Risk selections remain independent from Stock and P&L."
)


def reporting_filter_map(
    values: Sequence[Sequence[str] | None],
) -> dict[str, list[str]]:
    """Bind callback values to the authoritative portfolio schema."""
    return {
        field.key: list(selected or [])
        for field, selected in zip(FILTER_DIMENSION_FIELDS, values, strict=True)
    }


def quick_risk_filter_map(
    splits: Sequence[str] | None,
    dimension_values: Sequence[Sequence[str] | None],
) -> dict[str, list[str]]:
    """Map the shared filters to SearchCatalog column names."""
    return {
        "Split": list(splits or []),
        **{
            field.external_name: list(selected or [])
            for field, selected in zip(
                FILTER_DIMENSION_FIELDS,
                dimension_values,
                strict=True,
            )
        },
    }


def _meaningful_tenor_mask(values: pd.Series) -> pd.Series:
    labels = values.astype("string").str.strip().fillna("")
    return ~labels.str.casefold().isin(_ABSENT_TENOR_LABELS)


def metric_title(metric: str) -> str:
    return {
        "risk": "Risk",
        "risk expo": "Risk XVA",
        "risk hedges": "Risk Hedges",
        "drisk": "dRisk",
        "drisk expo": "dRisk XVA",
        "drisk hedges": "dRisk Hedges",
        "pl": "P&L",
        "pl expo": "P&L XVA",
        "pl hedges": "P&L Hedges",
        "open": "Open",
        "current": "Market Status",
        "move": "Move",
    }.get(metric, metric)


__all__ = [
    "DETAIL_TENOR_VIEW_LABELS",
    "RISK_FILTER_NOTE",
    "RISK_SAVED_VIEW_CONTROLS",
    "metric_title",
    "quick_risk_filter_map",
    "reporting_filter_map",
]
