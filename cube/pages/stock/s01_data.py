"""The Stock page consumes the connector frame without mapping or validation."""

from dataclasses import dataclass

import pandas as pd

from cube.domain.s03_calculations import market_date_for

STOCK_MEASURES = ("Stock", "dStock")
STOCK_PROMOTION_THRESHOLD = 20_000
# Display order only: the source's names, values and column order stay intact.
STOCK_INDEX_ALIASES = (
    ("Sign-off group", "SignoffGroup", "Signoff Group", "Sign-off Group"),
    ("Group", "group"),
    ("Counterparty name", "Counterparty Name", "CPTY", "Counterparty"),
    ("CIDS", "CRDS"),
)


@dataclass(frozen=True)
class StockPageData:
    raw: pd.DataFrame
    current_date: pd.Timestamp


def stock_index_columns(frame):
    dimensions = [c for c in frame.columns if c not in STOCK_MEASURES]
    ordered = [
        next((c for c in aliases if c in dimensions), None)
        for aliases in STOCK_INDEX_ALIASES
    ]
    return [c for c in ordered if c is not None] + [
        c for c in dimensions if c not in ordered
    ]


def stock_identifier(frame):
    return next((c for c in ("CIDS", "CRDS") if c in frame.columns), None)


def default_stock_dates(reference_date):
    current = market_date_for(pd.Timestamp(reference_date).normalize())
    return current, current - pd.offsets.BDay(1)


def load_stock_page_data(*, stock_source, current_date):
    """Call once. Keep every row/column; never calculate or overwrite supplied dStock."""
    requested = pd.Timestamp(current_date).normalize()
    frame = stock_source(requested)
    return StockPageData(frame, pd.Timestamp(frame.attrs.get("stock_date", requested)))
