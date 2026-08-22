"""Stock filter contracts, date normalization, and source loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pandas as pd

from rebirth.adapters.stock import (
    StockConnectorAdapter,
    StockSource,
    build_stock_adapter,
    normalize_stock_date,
)
from rebirth.domain.stock import (
    STOCK_FILTER_COLUMN_BY_KEY,
    map_stock_comparison_portfolios,
)
from rebirth.ui.constants import FILTER_DIMENSION_FIELDS
from rebirth.ui.filter_views import SavedFilterViewControls


STOCK_FILTER_FIELDS = FILTER_DIMENSION_FIELDS
STOCK_FILTER_IDS = {
    field.key: f"stock-{field.dash_filter_id}" for field in STOCK_FILTER_FIELDS
}
STOCK_SAVED_VIEW_CONTROLS = SavedFilterViewControls(
    scope="stock",
    prefix="stock",
    fields=STOCK_FILTER_FIELDS,
    filter_ids=STOCK_FILTER_IDS,
    exclude_id="stock-filter-exclude-selected",
)
STOCK_FILTER_NOTE = (
    "Include mode uses OR within one filter (B or D) and AND across filters "
    "(Credit and Portfolio B or D). Exclude mode removes a row if it matches any "
    "selected value in any populated filter. Leave a filter blank for all values; "
    "Stock selections remain independent from Risk and P&L."
)


@dataclass(frozen=True)
class StockPageData:
    """One server-owned, mapped comparison and the dates that produced it."""

    mapped_stock: pd.DataFrame
    current_date: pd.Timestamp
    prior_date: pd.Timestamp
    portfolio_date: pd.Timestamp


def default_stock_dates(reference_date: object) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the prior two business dates relative to a market/reference date."""

    reference = normalize_stock_date(reference_date)
    current_date = reference - pd.offsets.BDay(1)
    prior_date = current_date - pd.offsets.BDay(1)
    return current_date, prior_date


def normalize_stock_date_pair(
    current_date: object,
    prior_date: object,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Validate two distinct, ordered Stock comparison dates."""

    current = normalize_stock_date(current_date)
    prior = normalize_stock_date(prior_date)
    if prior >= current:
        raise ValueError("Prior Stock date must be earlier than current Stock date")
    return current, prior


def stock_filter_map(
    values: Sequence[Sequence[str] | None],
) -> dict[str, list[str]]:
    """Bind Stock-only dropdown values to governed reporting keys."""

    return {
        field.key: list(selected or [])
        for field, selected in zip(STOCK_FILTER_FIELDS, values, strict=True)
    }


def stock_exclude_selected(value: Sequence[str] | None) -> bool:
    """Normalize the Stock-local exclusion checklist value."""

    return "exclude" in (value or [])


def stock_filter_options(
    mapped_stock: pd.DataFrame,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[str]]]:
    """Return full-snapshot options and selected values that remain valid."""

    selected = dict(selected_filters or {})
    unknown = sorted(set(selected) - set(STOCK_FILTER_COLUMN_BY_KEY))
    if unknown:
        raise ValueError(f"Unknown Stock reporting-dimension filters: {unknown}")
    options: dict[str, list[dict[str, str]]] = {}
    valid: dict[str, list[str]] = {}
    for field in STOCK_FILTER_FIELDS:
        column = field.external_name
        available = sorted(
            mapped_stock[column].dropna().astype(str).unique().tolist(),
            key=str.casefold,
        )
        options[field.key] = [{"label": value, "value": value} for value in available]
        valid[field.key] = [
            str(value)
            for value in (selected.get(field.key) or [])
            if str(value) in available
        ]
    return options, valid


def load_stock_page_data(
    *,
    stock_source: StockSource | StockConnectorAdapter,
    portfolio_config_source: (
        pd.DataFrame | str | Path | Callable[[pd.Timestamp], pd.DataFrame | str | Path]
    ),
    current_date: object,
    prior_date: object,
    portfolio_date: object | None = None,
) -> StockPageData:
    """Resolve both dated Stock legs and one current Portfolio authority."""

    current, prior = normalize_stock_date_pair(current_date, prior_date)
    selected_portfolio_date = normalize_stock_date(
        current if portfolio_date is None else portfolio_date
    )
    adapter = (
        stock_source
        if isinstance(stock_source, StockConnectorAdapter)
        else build_stock_adapter(stock=stock_source)
    )
    current_stock = adapter.get_stock(current)
    prior_stock = adapter.get_stock(prior)
    portfolio_config = (
        portfolio_config_source(selected_portfolio_date)
        if callable(portfolio_config_source)
        else portfolio_config_source
    )
    mapped = map_stock_comparison_portfolios(
        current_stock,
        prior_stock,
        portfolio_config,
    )
    return StockPageData(
        mapped_stock=mapped,
        current_date=current,
        prior_date=prior,
        portfolio_date=selected_portfolio_date,
    )


__all__ = [
    "STOCK_FILTER_FIELDS",
    "STOCK_FILTER_IDS",
    "STOCK_FILTER_NOTE",
    "STOCK_SAVED_VIEW_CONTROLS",
    "StockPageData",
    "default_stock_dates",
    "load_stock_page_data",
    "normalize_stock_date_pair",
    "stock_exclude_selected",
    "stock_filter_map",
    "stock_filter_options",
]
