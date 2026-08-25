"""Strict Credit connector adapter."""

from __future__ import annotations

import pandas as pd

from cube.domain.s02_products import (
    CREDIT_MEASURE_COLUMNS,
    CREDIT_MEASURES,
    VOL_SCORE,
    ProductConnectorAdapter,
)
from cube.domain.s01_schema import TENOR_SWAP, TENOR_SWAP_ORDER

from .s01_common import MarketSource, RiskSource, market_frame


CREDIT_DELTA_RISK_BASE = (
    "Underlying",
    TENOR_SWAP,
    "Portfolio",
    "Group",
    "Risk",
    "dRisk",
    VOL_SCORE,
)
CREDIT_DELTA_RISK_REGION_BASE = (
    "Underlying",
    TENOR_SWAP,
    "Portfolio",
    "Group",
    "Region",
    "Risk",
    "dRisk",
    VOL_SCORE,
)
CREDIT_DELTA_RISK = (
    *CREDIT_DELTA_RISK_BASE,
    *CREDIT_MEASURE_COLUMNS,
)
CREDIT_DELTA_OPEN = ("Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, "Open")
CREDIT_DELTA_CURRENT = ("Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, "Current")


def build_credit_adapter(
    *,
    risk: RiskSource,
    open_market: MarketSource,
    current_market: MarketSource,
) -> ProductConnectorAdapter:
    """Bind a fixture or site-owned Credit Delta source to the public contract."""

    def get_risk(risk_date: pd.Timestamp) -> pd.DataFrame:
        value = risk(risk_date)
        if not isinstance(value, pd.DataFrame):
            raise TypeError("Credit Delta risk must return a pandas DataFrame")
        actual = tuple(value.columns)
        base_columns = (
            CREDIT_DELTA_RISK_REGION_BASE
            if "Region" in actual
            else CREDIT_DELTA_RISK_BASE
        )
        unexpected = [
            column
            for column in actual
            if column not in {*base_columns, *CREDIT_MEASURE_COLUMNS}
        ]
        selected_measures = tuple(
            column for column in CREDIT_MEASURE_COLUMNS if column in value
        )
        expected = (*base_columns, *selected_measures)
        if unexpected or actual != expected:
            raise ValueError(
                "Credit Delta risk columns must be the base columns followed by "
                "canonical optional Credit measure pairs; "
                f"found {list(actual)}"
            )
        for measure in CREDIT_MEASURES:
            risk_measure = f"Risk {measure}"
            drisk_measure = f"dRisk {measure}"
            if (risk_measure in value) != (drisk_measure in value):
                raise ValueError(
                    f"Credit Delta optional measure {measure!r} must supply both "
                    f"{risk_measure!r} and {drisk_measure!r}, or omit both"
                )
        return value.copy()

    def get_open(
        market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        return market_frame(
            open_market,
            market_date,
            underlying,
            market_status=market_status,
            columns=CREDIT_DELTA_OPEN,
            label="Credit Delta Open",
        )

    def get_current(
        market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        return market_frame(
            current_market,
            market_date,
            underlying,
            market_status=market_status,
            columns=CREDIT_DELTA_CURRENT,
            label="Credit Delta current",
            attach_status=True,
        )

    return ProductConnectorAdapter(
        risk=get_risk,
        market_open=get_open,
        market_status=get_current,
    )


__all__ = [
    "CREDIT_DELTA_CURRENT",
    "CREDIT_DELTA_OPEN",
    "CREDIT_DELTA_RISK",
    "CREDIT_DELTA_RISK_BASE",
    "CREDIT_DELTA_RISK_REGION_BASE",
    "build_credit_adapter",
]
