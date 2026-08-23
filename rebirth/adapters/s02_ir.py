"""Strict IR connector adapters."""

from __future__ import annotations

import pandas as pd

from rebirth.domain.s02_products import ProductConnectorAdapter
from rebirth.domain.s01_schema import (
    TENOR_OPTION,
    TENOR_OPTION_ORDER,
    TENOR_SWAP,
    TENOR_SWAP_ORDER,
)

from .s01_common import MarketSource, RiskSource, exact_frame, market_frame


IR_DELTA_RISK = (
    "Underlying",
    TENOR_SWAP,
    "Portfolio",
    "Group",
    "Risk",
    "dRisk",
)
IR_DELTA_OPEN = ("Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, "Open")
IR_DELTA_CURRENT = ("Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, "Current")

IR_DELTAVEGA_RISK = (
    "Underlying",
    TENOR_SWAP,
    TENOR_OPTION,
    "Portfolio",
    "Group",
    "Risk",
    "dRisk",
)
IR_DELTAVEGA_OPEN = (
    "Underlying",
    TENOR_SWAP,
    TENOR_OPTION,
    TENOR_SWAP_ORDER,
    TENOR_OPTION_ORDER,
    "Open",
)
IR_DELTAVEGA_CURRENT = (
    "Underlying",
    TENOR_SWAP,
    TENOR_OPTION,
    TENOR_SWAP_ORDER,
    TENOR_OPTION_ORDER,
    "Current",
)


def build_ir_adapters(
    *,
    delta_risk: RiskSource,
    delta_open: MarketSource,
    delta_current: MarketSource,
    deltavega_risk: RiskSource,
    deltavega_open: MarketSource,
    deltavega_current: MarketSource,
) -> dict[str, ProductConnectorAdapter]:
    """Bind six sources to the IR Delta and DeltaVega contracts."""

    def get_delta_risk(risk_date: pd.Timestamp) -> pd.DataFrame:
        return exact_frame(
            delta_risk(risk_date), columns=IR_DELTA_RISK, label="IR Delta risk"
        )

    def get_delta_open(
        market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        return market_frame(
            delta_open,
            market_date,
            underlying,
            market_status=market_status,
            columns=IR_DELTA_OPEN,
            label="IR Delta Open",
        )

    def get_delta_current(
        market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        return market_frame(
            delta_current,
            market_date,
            underlying,
            market_status=market_status,
            columns=IR_DELTA_CURRENT,
            label="IR Delta current",
            attach_status=True,
        )

    def get_deltavega_risk(risk_date: pd.Timestamp) -> pd.DataFrame:
        return exact_frame(
            deltavega_risk(risk_date),
            columns=IR_DELTAVEGA_RISK,
            label="IR DeltaVega risk",
        )

    def get_deltavega_open(
        market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        return market_frame(
            deltavega_open,
            market_date,
            underlying,
            market_status=market_status,
            columns=IR_DELTAVEGA_OPEN,
            label="IR DeltaVega Open",
        )

    def get_deltavega_current(
        market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        return market_frame(
            deltavega_current,
            market_date,
            underlying,
            market_status=market_status,
            columns=IR_DELTAVEGA_CURRENT,
            label="IR DeltaVega current",
            attach_status=True,
        )

    return {
        "ir/delta": ProductConnectorAdapter(
            risk=get_delta_risk,
            market_open=get_delta_open,
            market_status=get_delta_current,
        ),
        "ir/deltavega": ProductConnectorAdapter(
            risk=get_deltavega_risk,
            market_open=get_deltavega_open,
            market_status=get_deltavega_current,
        ),
    }


__all__ = [
    "IR_DELTA_CURRENT",
    "IR_DELTA_OPEN",
    "IR_DELTA_RISK",
    "IR_DELTAVEGA_CURRENT",
    "IR_DELTAVEGA_OPEN",
    "IR_DELTAVEGA_RISK",
    "build_ir_adapters",
]
