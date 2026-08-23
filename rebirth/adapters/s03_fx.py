"""Strict FX connector adapters."""

from __future__ import annotations

import pandas as pd

from rebirth.domain.s02_products import VOL_SCORE, ProductConnectorAdapter
from rebirth.domain.s01_schema import TENOR_SWAP, TENOR_SWAP_ORDER

from .s01_common import MarketSource, RiskSource, exact_frame, market_frame


FX_DELTA_RISK = ("Underlying", "Portfolio", "Group", "Risk", "dRisk", VOL_SCORE)
FX_DELTA_OPEN = ("Underlying", "Open")
FX_DELTA_CURRENT = ("Underlying", "Current")

FX_GAMMA_RISK = ("Underlying", "Portfolio", "Group", "Risk", "dRisk", VOL_SCORE)
FX_GAMMA_OPEN = ("Underlying", "Open")
FX_GAMMA_CURRENT = ("Underlying", "Current")

FX_VEGA_RISK = (
    "Underlying",
    TENOR_SWAP,
    "Portfolio",
    "Group",
    "Risk",
    "dRisk",
    VOL_SCORE,
)
FX_VEGA_OPEN = ("Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, "Open")
FX_VEGA_CURRENT = ("Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, "Current")


def _scalar_adapter(
    *,
    risk_source: RiskSource,
    open_source: MarketSource,
    current_source: MarketSource,
    risk_columns: tuple[str, ...],
    open_columns: tuple[str, ...],
    current_columns: tuple[str, ...],
    label: str,
) -> ProductConnectorAdapter:
    def get_risk(risk_date: pd.Timestamp) -> pd.DataFrame:
        return exact_frame(
            risk_source(risk_date), columns=risk_columns, label=f"{label} risk"
        )

    def get_open(
        market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        return market_frame(
            open_source,
            market_date,
            underlying,
            market_status=market_status,
            columns=open_columns,
            label=f"{label} Open",
        )

    def get_current(
        market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        return market_frame(
            current_source,
            market_date,
            underlying,
            market_status=market_status,
            columns=current_columns,
            label=f"{label} current",
            attach_status=True,
        )

    return ProductConnectorAdapter(
        risk=get_risk,
        market_open=get_open,
        market_status=get_current,
    )


def build_fx_adapters(
    *,
    delta_risk: RiskSource,
    delta_open: MarketSource,
    delta_current: MarketSource,
    gamma_risk: RiskSource,
    gamma_open: MarketSource,
    gamma_current: MarketSource,
    vega_risk: RiskSource,
    vega_open: MarketSource,
    vega_current: MarketSource,
) -> dict[str, ProductConnectorAdapter]:
    """Bind fixture or site-owned sources to the three FX contracts."""

    return {
        "fx/delta": _scalar_adapter(
            risk_source=delta_risk,
            open_source=delta_open,
            current_source=delta_current,
            risk_columns=FX_DELTA_RISK,
            open_columns=FX_DELTA_OPEN,
            current_columns=FX_DELTA_CURRENT,
            label="FX Delta",
        ),
        "fx/gamma": _scalar_adapter(
            risk_source=gamma_risk,
            open_source=gamma_open,
            current_source=gamma_current,
            risk_columns=FX_GAMMA_RISK,
            open_columns=FX_GAMMA_OPEN,
            current_columns=FX_GAMMA_CURRENT,
            label="FX Gamma",
        ),
        "fx/vega": _scalar_adapter(
            risk_source=vega_risk,
            open_source=vega_open,
            current_source=vega_current,
            risk_columns=FX_VEGA_RISK,
            open_columns=FX_VEGA_OPEN,
            current_columns=FX_VEGA_CURRENT,
            label="FX Vega",
        ),
    }


__all__ = [
    "FX_DELTA_CURRENT",
    "FX_DELTA_OPEN",
    "FX_DELTA_RISK",
    "FX_GAMMA_CURRENT",
    "FX_GAMMA_OPEN",
    "FX_GAMMA_RISK",
    "FX_VEGA_CURRENT",
    "FX_VEGA_OPEN",
    "FX_VEGA_RISK",
    "build_fx_adapters",
]
