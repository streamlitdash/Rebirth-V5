"""Stock filter contracts, date normalization, and source loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence
import unicodedata

import pandas as pd

from cube.adapters.s08_stock import (
    StockConnectorAdapter,
    StockSource,
    build_stock_adapter,
    normalize_stock_date,
)
from cube.domain.s03_calculations import market_date_for
from cube.domain.s09_stock import (
    CURRENT_MARKET_VALUE_COLUMN,
    CURRENT_QUANTITY_COLUMN,
    MAPPED_STOCK_COMPARISON_COLUMNS,
    MARKET_VALUE_CHANGE_COLUMN,
    STOCK_FILTER_COLUMN_BY_KEY,
    STOCK_IDENTITY_COLUMNS,
    filter_stock_comparison,
    map_stock_comparison_portfolios,
)
from cube.ui.s01_constants import FILTER_DIMENSION_FIELDS
from cube.ui.s03_filters import SavedFilterViewControls


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
    base_label="Base Review",
)
STOCK_FILTER_NOTE = (
    "Base Review starts with Activity 1, 2 and 3. Include mode uses OR within "
    "one filter (B or D) and AND across filters "
    "(Credit and Portfolio B or D). Exclude mode removes a row if it matches any "
    "selected value in any populated filter. Leave a filter blank for all values; "
    "Stock selections remain independent from Risk and P&L."
)

STOCK_DEFAULT_ACTIVITIES = ("Activity 1", "Activity 2", "Activity 3")
STOCK_DEFAULT_ACTIVITY_ALIASES = {
    "Activity 1": ("Activity 1", "Macro"),
    "Activity 2": ("Activity 2", "Credit"),
    "Activity 3": ("Activity 3", "Hedge"),
}
STOCK_DISPLAY_COLUMNS = (
    "CRDS",
    "CPTY",
    "Portfolio",
    "Activity",
    "SignoffGroup",
    "Category",
    "SubCategory",
    "Product",
    "Instrument",
    "Currency",
    "Quantity",
    "Stock",
    "dStock",
    "Portfolio Mapped",
)
_TEMP_ACTIVITY_PREFIX = "temp_replace_me - "


@dataclass(frozen=True)
class StockPageData:
    """One server-owned, mapped comparison and the dates that produced it."""

    mapped_stock: pd.DataFrame
    current_date: pd.Timestamp
    prior_date: pd.Timestamp
    portfolio_date: pd.Timestamp


def _activity_key(value: object) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()
    if normalized.startswith(_TEMP_ACTIVITY_PREFIX):
        normalized = normalized[len(_TEMP_ACTIVITY_PREFIX) :]
    return normalized


def default_stock_activities(mapped_stock: pd.DataFrame) -> list[str]:
    """Resolve the governed Activity 1-3 default against current labels."""

    if not isinstance(mapped_stock, pd.DataFrame):
        raise TypeError("mapped_stock must be a pandas DataFrame")
    if "Activity" not in mapped_stock:
        raise ValueError("mapped_stock is missing Activity")
    alias_owner = {
        _activity_key(alias): canonical
        for canonical, aliases in STOCK_DEFAULT_ACTIVITY_ALIASES.items()
        for alias in aliases
    }
    matches: dict[str, list[str]] = {
        canonical: [] for canonical in STOCK_DEFAULT_ACTIVITIES
    }
    seen: set[str] = set()
    for raw_value in mapped_stock["Activity"].dropna():
        value = str(raw_value).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        canonical = alias_owner.get(_activity_key(value))
        if canonical is not None:
            matches[canonical].append(value)
    return [
        value for canonical in STOCK_DEFAULT_ACTIVITIES for value in matches[canonical]
    ]


def stock_activity_options(mapped_stock: pd.DataFrame) -> list[dict[str, str]]:
    """Return stable Activity options without collapsing Stock rows."""

    if not isinstance(mapped_stock, pd.DataFrame):
        raise TypeError("mapped_stock must be a pandas DataFrame")
    if "Activity" not in mapped_stock:
        raise ValueError("mapped_stock is missing Activity")
    values = sorted(
        mapped_stock["Activity"].dropna().astype(str).unique().tolist(),
        key=str.casefold,
    )
    return [{"label": value, "value": value} for value in values]


def stock_display_rows(
    mapped_stock: pd.DataFrame,
    activities: Sequence[str] | None = None,
    *,
    dimension_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
) -> pd.DataFrame:
    """Project latest Stock rows for display without aggregating metadata.

    Prior-only identities are excluded because this is the current Stock table.
    Every current source row remains independent, including unmapped Portfolios.
    """

    if not isinstance(mapped_stock, pd.DataFrame):
        raise TypeError("mapped_stock must be a pandas DataFrame")
    missing = [
        column
        for column in MAPPED_STOCK_COMPARISON_COLUMNS
        if column not in mapped_stock
    ]
    if missing:
        raise ValueError(f"mapped_stock is missing required columns: {missing}")
    filters = dict(dimension_filters or {})
    if activities and "activity" not in filters:
        filters["activity"] = [str(value) for value in activities if value is not None]
    filtered = filter_stock_comparison(
        mapped_stock,
        filters,
        exclude_selected=exclude_selected,
    )
    current = filtered.loc[filtered[CURRENT_MARKET_VALUE_COLUMN].notna()].copy()
    display = current.loc[
        :,
        [
            "CRDS",
            "CPTY",
            "Portfolio",
            "Activity",
            "SignoffGroup",
            "Category",
            "Sub Category",
            "Product",
            "Instrument",
            "Currency",
            CURRENT_QUANTITY_COLUMN,
            CURRENT_MARKET_VALUE_COLUMN,
            MARKET_VALUE_CHANGE_COLUMN,
            "Portfolio Mapped",
        ],
    ].copy()
    display.rename(
        columns={
            "Sub Category": "SubCategory",
            CURRENT_QUANTITY_COLUMN: "Quantity",
            CURRENT_MARKET_VALUE_COLUMN: "Stock",
            MARKET_VALUE_CHANGE_COLUMN: "dStock",
        },
        inplace=True,
    )
    return display.loc[:, list(STOCK_DISPLAY_COLUMNS)].reset_index(drop=True)


def default_stock_filter_values(mapped_stock: pd.DataFrame) -> dict[str, list[str]]:
    """Return the Stock Base Review: Activity 1-3 and all other dimensions."""

    return {
        field.key: (
            default_stock_activities(mapped_stock) if field.key == "activity" else []
        )
        for field in STOCK_FILTER_FIELDS
    }


def stock_history_identities(
    mapped_stock: pd.DataFrame,
    *,
    crds: object,
    activity: object,
) -> list[dict[str, str]]:
    """Resolve a CRDS + Activity selection to exact archive identities."""

    crds_value = str(crds or "").strip()
    activity_value = str(activity or "").strip()
    if not crds_value or not activity_value:
        raise ValueError("Select both CRDS and Activity")
    current = mapped_stock.loc[mapped_stock[CURRENT_MARKET_VALUE_COLUMN].notna()]
    selected = current.loc[
        current["CRDS"].astype(str).eq(crds_value)
        & current["Activity"].astype(str).eq(activity_value),
        list(STOCK_IDENTITY_COLUMNS),
    ].drop_duplicates()
    return [
        {column: str(row[column]) for column in STOCK_IDENTITY_COLUMNS}
        for row in selected.to_dict("records")
    ]


def default_stock_dates(reference_date: object) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Use the reference Market Date and its preceding business day."""

    reference = normalize_stock_date(reference_date)
    current_date = market_date_for(reference)
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
    current = mapped_stock.loc[mapped_stock[CURRENT_MARKET_VALUE_COLUMN].notna()]
    for field in STOCK_FILTER_FIELDS:
        column = field.external_name
        available = sorted(
            current[column].dropna().astype(str).unique().tolist(),
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
    "STOCK_DEFAULT_ACTIVITIES",
    "STOCK_DISPLAY_COLUMNS",
    "STOCK_FILTER_FIELDS",
    "STOCK_FILTER_IDS",
    "STOCK_FILTER_NOTE",
    "STOCK_SAVED_VIEW_CONTROLS",
    "StockPageData",
    "default_stock_activities",
    "default_stock_filter_values",
    "default_stock_dates",
    "load_stock_page_data",
    "normalize_stock_date_pair",
    "stock_activity_options",
    "stock_display_rows",
    "stock_exclude_selected",
    "stock_filter_map",
    "stock_filter_options",
    "stock_history_identities",
]
