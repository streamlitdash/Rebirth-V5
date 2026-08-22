"""Risk-page constants, controls, labels, and common presentation helpers."""

from __future__ import annotations

import pandas as pd

from shared.constants import DIMENSION_FILTER_IDS, FILTER_DIMENSION_FIELDS
from shared.saved_views import SavedFilterViewControls


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
)
RISK_FILTER_NOTE = (
    "Include mode uses OR within one filter (B or D) and AND across filters "
    "(Credit and Portfolio B or D). Exclude mode removes a row if it matches "
    "any selected value in any populated filter. Leave a filter blank for all "
    "values; Risk selections remain independent from Stock and P&L."
)


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
]
