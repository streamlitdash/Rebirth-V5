"""Immutable product contracts and the authoritative product catalogue."""

from __future__ import annotations

from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Callable, Literal, Mapping, Protocol

import numpy as np
import pandas as pd

from rebirth.domain.schema import (
    PORTFOLIO_COLUMN,
    PORTFOLIO_FIELD_BY_KEY,
    PORTFOLIO_MAPPED_COLUMN,
    TENOR_OPTION,
    TENOR_OPTION_ORDER,
    TENOR_SWAP,
    TENOR_SWAP_ORDER,
)
from rebirth.domain.cross_gamma import XGAMMA_SOURCE_RISK_GREEKS
from rebirth.domain.new_trades import NEW_TRADES_SPLIT

RISK_TYPE = "Risk Type"
SOURCE_TYPE = "Source Type"
RISK_GREEK = "Risk Greek"
SPLIT = "Split"
UNDERLYING = "Underlying"
PORTFOLIO = PORTFOLIO_COLUMN
RISK = "Risk"
DRISK = "dRisk"
OPEN = "Open"
CURRENT = "Current"
LIVE = "Live"
OFFICIAL = "OFFICIAL"
MARKET_STATUS = "Market Status"
MARKET_DATE = "Market Date"
MARKET_MOVE = "Move"
MARKET_AVAILABLE = "Market Available"
MARKET_DATA_STATUS = "Market Data Status"
PL = "PL"
PRODUCT = PORTFOLIO_FIELD_BY_KEY["product"].external_name
PRODUCT_LABELS = {
    value.casefold(): value
    for value in PORTFOLIO_FIELD_BY_KEY["product"].allowed_values
}
CANONICAL_PRODUCTS = frozenset(PRODUCT_LABELS.values())
ACTIVITY = PORTFOLIO_FIELD_BY_KEY["activity"].external_name
SIGNOFF_GROUP = PORTFOLIO_FIELD_BY_KEY["signoffgroup"].external_name
CATEGORY = PORTFOLIO_FIELD_BY_KEY["category"].external_name
SUBCATEGORY = PORTFOLIO_FIELD_BY_KEY["subcategory"].external_name
PORTFOLIO_MAPPED = PORTFOLIO_MAPPED_COLUMN
GROUP = "Group"
REGION = "Region"
DISPLAY_BUCKET = "Display Bucket"
PROMOTION_REASON = "Promotion Reason"
PROMOTION_SCORE = "Promotion Score"
RISK_THRESHOLD = "Risk Threshold"
DRISK_THRESHOLD = "dRisk Threshold"
PL_THRESHOLD = "PL Threshold"
RISK_DATE = "Risk Date"
AGE = "Age"
# === RECOVERED ORIGINAL RISK-CHECKER FIELD (COMMENTED OUT) ==================
# SWITCH TO THE RECOVERED CONNECTOR CONTRACT: uncomment the line below, comment
# the active CSV-compatible line beneath it, then remove the matching
# ``MRX File`` -> ``MMMFile`` shim in ``rebirth.services.sources``.
# MRX_FILE = "MRX File"
# === ACTIVE CSV-COMPATIBLE FIELD =============================================
MMM_FILE = "MMMFile"
EFFECTIVE_RISK_DATE = "Effective Risk Date"
FORCE_RISK = "Force Risk"
CHECKER_DATE = "Checker Date"
SUGGESTED_RISK_DATE = "Suggested Risk Date"
AGE_DEFAULTED = "Age Defaulted"

CREDIT_MEASURES = ("SP01", "PSP01", "PM01", "PM01P", "Theta", "JTD")
# === RECOVERED ORIGINAL CREDIT COLUMN EXPRESSION (COMMENTED OUT) ============
# The original fragment literally generated ``Risk (measure)`` and
# ``dRisk (measure)`` repeatedly.  It is retained for provenance, but activating
# it would create duplicate column names and is therefore not a valid switch.
# CREDIT_MEASURE_COLUMNS = tuple(
#     f"{metric} (measure)"
#     for measure in CREDIT_MEASURES
#     for metric in (RISK, DRISK)
# )
# === ACTIVE UNIQUE CREDIT MEASURE COLUMNS ====================================
CREDIT_MEASURE_COLUMNS = tuple(
    f"{metric} {measure}" for measure in CREDIT_MEASURES for metric in (RISK, DRISK)
)

MarketUnit = Literal["pips", "outright", "vol_points", "bp"]
# === RECOVERED ORIGINAL FORMULA NAMES (COMMENTED OUT) ========================
# The recovered ProductSpec metadata used two extra formula names.  Their
# original calculation implementation was not present in the recovered source,
# so this is reference material rather than a safe one-line activation switch.
# PlFormula = Literal[
#     "absolute",
#     "minusabsolute",
#     "percentage",
#     "percentage_vega",
#     "taylor_gamma",
# ]
# === ACTIVE VALIDATED FORMULA ENGINE =========================================
PlFormula = Literal["absolute", "percentage", "taylor_gamma", "identity"]
FrameSource = pd.DataFrame | Callable[[], pd.DataFrame] | None
DataFrameSource = pd.DataFrame | str | Path
GovernanceSource = DataFrameSource | Callable[[], pd.DataFrame]
PortfolioConfigSource = DataFrameSource | Callable[[pd.Timestamp], pd.DataFrame]
ProductSources = Mapping[str, Mapping[str, FrameSource]]
RiskCheckerResult = tuple[pd.DataFrame, pd.DataFrame]
MarketStatusResolver = Callable[[pd.Timestamp], str]
DatedFrameLoader = Callable[[pd.Timestamp], pd.DataFrame]
FrameName = Literal[
    "risk_status",
    "risk_checker",
    "combined_pl",
    "market_frame",
    "dashboard_frame",
    "unmapped_frame",
]


class ProductMarketConnector(Protocol):
    """One source-bound, one-Underlying market connector."""

    def __call__(
        self,
        source_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame: ...


class GenericMarketConnector(Protocol):
    """Generic market connector whose first argument selects the source."""

    def __call__(
        self,
        source_type: str,
        source_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame: ...


class ProductionIntegrationError(RuntimeError):
    """Raised when a required real-data integration has not been configured."""


@dataclass(frozen=True)
class AxisSpec:
    """One market-owned categorical axis and its authoritative rank column."""

    column: str
    order_column: str


SWAP_AXIS = AxisSpec(TENOR_SWAP, TENOR_SWAP_ORDER)
OPTION_AXIS = AxisSpec(TENOR_OPTION, TENOR_OPTION_ORDER)


@dataclass(frozen=True)
class ProductSpec:
    key: str
    source_type: str
    risk_type: str
    risk_greek: str
    axes: tuple[AxisSpec, ...]
    market_unit: MarketUnit
    pl_formula: PlFormula
    gamma_move_scale: float = 1.0
    gamma_risk_step: float = 1.0

    @property
    def tenor_columns(self) -> list[str]:
        return [axis.column for axis in self.axes]

    @property
    def tenor_order_columns(self) -> list[str]:
        return [axis.order_column for axis in self.axes]

    @property
    def market_keys(self) -> list[str]:
        return [RISK_TYPE, RISK_GREEK, UNDERLYING, *self.tenor_columns]


@dataclass(frozen=True)
class DirectPLClassification:
    """One ProductSpec-backed identity that deliberately has no MarketBook."""

    product_spec: ProductSpec
    source_type: str
    risk_type: str
    risk_greek: str
    split: str
    underlying: str
    group: str
    market_data_status: str


# === RECOVERED ORIGINAL PRODUCT METADATA (COMMENTED OUT) ====================
# This is the formula metadata recovered from the original fragment.  It is
# intentionally adjacent to the active table, but it must not be uncommented
# until ``minusabsolute`` and ``percentage_vega`` are implemented and tested in
# the P&L engine.  The recovered ``commoddelta`` spelling also differs from the
# active, fixture-backed ``commodelta`` source key.
# PRODUCT_SPECS: dict[str, ProductSpec] = {
#     "fxdelta": ProductSpec(
#         "fxdelta", "fx/delta", "FX", "Delta", (), "pips", "percentage"
#     ),
#     "fxgamma": ProductSpec(
#         "fxgamma", "fx/gamma", "FX", "Gamma", (), "outright", "taylor_gamma", 1, 1
#     ),
#     "fxvega": ProductSpec(
#         "fxvega", "fx/vega", "FX", "Vega", (SWAP_AXIS,), "vol_points", "absolute"
#     ),
#     "irdelta": ProductSpec(
#         "irdelta", "ir/delta", "IR", "Delta", (SWAP_AXIS,), "bp", "minusabsolute"
#     ),
#     "irgamma": ProductSpec(
#         "irgamma", "ir/gamma", "IR", "Gamma", (SWAP_AXIS,), "bp", "taylor_gamma", 1, 1
#     ),
#     "irdeltavega": ProductSpec(
#         "irdeltavega", "ir/deltavega", "IR", "DeltaVega", (SWAP_AXIS, OPTION_AXIS), "bp", "percentage_vega"
#     ),
#     "xccy": ProductSpec(
#         "xccy", "ir/xccy", "IR", "XCCY", (SWAP_AXIS,), "bp", "minusabsolute"
#     ),
#     "xccyvega": ProductSpec(
#         "xccyvega", "ir/xccyvega", "IR", "XCCYVega", (SWAP_AXIS, OPTION_AXIS), "bp", "percentage_vega",
#     ),
#     "inflation": ProductSpec(
#         "inflation", "ir/inflation", "IR", "Inflation", (SWAP_AXIS,), "bp", "absolute",
#     ),
#     "inflationvega": ProductSpec(
#         "inflationvega", "ir/inflationvega", "IR", "InflationVega", (SWAP_AXIS, OPTION_AXIS), "bp", "percentage_vega",
#     ),
#     "basis": ProductSpec(
#         "basis", "ir/basis", "IR", "Basis", (SWAP_AXIS,), "bp", "minusabsolute"
#     ),
#     "bond": ProductSpec(
#         "bond", "ir/bond", "IR", "Bond", (SWAP_AXIS,), "bp", "minusabsolute"
#     ),
#     "creditdelta": ProductSpec(
#         "creditdelta", "credit/delta", "Credit", "Delta", (SWAP_AXIS,), "bp", "absolute",
#     ),
#     "creditvega": ProductSpec(
#         "creditvega", "credit/vega", "Credit", "Vega", (SWAP_AXIS,), "bp", "absolute",
#     ),
#     "commoddelta": ProductSpec(
#         "commoddelta", "commo/delta", "Commo", "Delta", (SWAP_AXIS,), "outright", "percentage",
#     ),
#     "commovega": ProductSpec(
#         "commovega", "commo/vega", "Commo", "Vega", (SWAP_AXIS,), "vol_points", "absolute",
#     ),
# }
# === ACTIVE FIXTURE-VALIDATED PRODUCT METADATA ===============================
PRODUCT_SPECS: dict[str, ProductSpec] = {
    "fxdelta": ProductSpec(
        "fxdelta", "fx/delta", "FX", "Delta", (), "pips", "percentage"
    ),
    "fxgamma": ProductSpec(
        "fxgamma", "fx/gamma", "FX", "Gamma", (), "outright", "taylor_gamma"
    ),
    "fxvega": ProductSpec(
        "fxvega", "fx/vega", "FX", "Vega", (SWAP_AXIS,), "vol_points", "absolute"
    ),
    "irdelta": ProductSpec(
        "irdelta", "ir/delta", "IR", "Delta", (SWAP_AXIS,), "bp", "absolute"
    ),
    "irgamma": ProductSpec(
        "irgamma",
        "ir/gamma",
        "IR",
        "Gamma",
        (SWAP_AXIS,),
        "bp",
        "taylor_gamma",
        10_000.0,
        10.0,
    ),
    "irdeltavega": ProductSpec(
        "irdeltavega",
        "ir/deltavega",
        "IR",
        "DeltaVega",
        (SWAP_AXIS, OPTION_AXIS),
        "bp",
        "percentage",
    ),
    "xccy": ProductSpec(
        "xccy", "ir/xccy", "IR", "XCCY", (SWAP_AXIS,), "bp", "absolute"
    ),
    "xccyvega": ProductSpec(
        "xccyvega",
        "ir/xccyvega",
        "IR",
        "XCCYVega",
        (SWAP_AXIS, OPTION_AXIS),
        "bp",
        "percentage",
    ),
    "inflation": ProductSpec(
        "inflation",
        "ir/inflation",
        "IR",
        "Inflation",
        (SWAP_AXIS,),
        "bp",
        "absolute",
    ),
    "inflationvega": ProductSpec(
        "inflationvega",
        "ir/inflationvega",
        "IR",
        "InflationVega",
        (SWAP_AXIS, OPTION_AXIS),
        "bp",
        "percentage",
    ),
    "basis": ProductSpec(
        "basis", "ir/basis", "IR", "Basis", (SWAP_AXIS,), "bp", "absolute"
    ),
    "bond": ProductSpec(
        "bond", "ir/bond", "IR", "Bond", (SWAP_AXIS,), "bp", "absolute"
    ),
    "creditdelta": ProductSpec(
        "creditdelta",
        "credit/delta",
        "Credit",
        "Delta",
        (SWAP_AXIS,),
        "bp",
        "absolute",
    ),
    "creditvega": ProductSpec(
        "creditvega",
        "credit/vega",
        "Credit",
        "Vega",
        (SWAP_AXIS,),
        "bp",
        "absolute",
    ),
    "commodelta": ProductSpec(
        "commodelta",
        "commo/delta",
        "Commo",
        "Delta",
        (SWAP_AXIS,),
        "outright",
        "percentage",
    ),
    "commovega": ProductSpec(
        "commovega",
        "commo/vega",
        "Commo",
        "Vega",
        (SWAP_AXIS,),
        "vol_points",
        "absolute",
    ),
}

# Cash Flow is a real ProductSpec-backed calculation, but it is deliberately an
# auxiliary New Trades product rather than part of the aged Risk/MarketBook
# inventory.  Its identity formula is ``Risk x 1``; no synthetic quote is
# published to Quick Market and no readiness row is manufactured.
CASH_FLOW_PRODUCT_SPEC = ProductSpec(
    "cashflownew",
    "new-position/cash-flow",
    "Cash Flow",
    "New",
    (),
    "outright",
    "identity",
)

# Auxiliary classifications stay separate from ``PRODUCT_SPECS`` so they do
# not acquire normal Risk connectors, RiskChecker ageing, or market quotes.
NEW_POSITION_CASH_FLOW_CLASSIFICATION = DirectPLClassification(
    product_spec=CASH_FLOW_PRODUCT_SPEC,
    source_type=CASH_FLOW_PRODUCT_SPEC.source_type,
    risk_type=CASH_FLOW_PRODUCT_SPEC.risk_type,
    risk_greek=CASH_FLOW_PRODUCT_SPEC.risk_greek,
    split=NEW_TRADES_SPLIT,
    underlying="Cash Flow",
    group="Cash Flow",
    market_data_status="Identity P&L; market data not applicable",
)
DIRECT_PL_CLASSIFICATIONS = (NEW_POSITION_CASH_FLOW_CLASSIFICATION,)
DIRECT_PL_CLASSIFICATIONS_BY_SOURCE_TYPE = {
    classification.source_type: classification
    for classification in DIRECT_PL_CLASSIFICATIONS
}
if len(DIRECT_PL_CLASSIFICATIONS_BY_SOURCE_TYPE) != len(DIRECT_PL_CLASSIFICATIONS):
    raise RuntimeError("Direct P&L classification Source Type values must be unique")
for classification in DIRECT_PL_CLASSIFICATIONS:
    if (
        classification.source_type != classification.product_spec.source_type
        or classification.risk_type != classification.product_spec.risk_type
        or classification.risk_greek != classification.product_spec.risk_greek
        or classification.product_spec.pl_formula != "identity"
    ):
        raise RuntimeError(
            "Direct P&L classification identity must match an identity ProductSpec"
        )


def _validate_multiplier(value: object, *, label: str) -> float:
    """Return a finite real multiplier while rejecting bool and string coercion."""
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise TypeError(f"{label} must be a non-boolean real number")
    multiplier = float(value)
    if not np.isfinite(multiplier):
        raise ValueError(f"{label} must be finite")
    return multiplier


def _validate_multipliers(
    multipliers: Mapping[str, float] | None,
) -> dict[str, float]:
    """Validate product multiplier keys and values at a public API boundary."""
    if multipliers is None:
        return {}
    if not isinstance(multipliers, Mapping):
        raise TypeError("multipliers must be a mapping of product keys to numbers")
    unknown_keys = sorted(
        set(multipliers) - set(PRODUCT_SPECS), key=lambda key: str(key)
    )
    if unknown_keys:
        raise ValueError(f"unknown product multiplier keys: {unknown_keys}")
    return {
        key: _validate_multiplier(value, label=f"multiplier for {key!r}")
        for key, value in multipliers.items()
    }


@dataclass(frozen=True)
class ProductConnectorAdapter:
    """Product-specific connector hooks for sources with different APIs/shapes.

    Each callable is already bound to its product/source, so FX delta can call a
    completely different service from credit detail while the validated output
    contract below remains common.

    REAL CONNECTOR INTEGRATION POINT
    --------------------------------
    Construct one adapter per source type and pass the mapping to
    ``RiskRefreshManager(connector_adapters=...)``. Every callable must return a
    ``pandas.DataFrame``; returning ``None``, dictionaries, or lists is rejected.

    ``risk(risk_date)``
        ``risk_date`` is a normalized, timezone-naive ``pandas.Timestamp``.
        Return one authoritative position row per product key with columns
        ``Underlying``, the source's required tenor columns, ``Portfolio``,
        connector-owned ``Group``, ``Risk``, and ``dRisk``. ``Group`` passes
        through unchanged: the framework does not classify, normalize, or
        restrict its values. ``Risk Type`` and ``Risk Greek`` may be supplied
        and are checked when present. Credit sources may also return the
        optional ``Risk/ dRisk`` measure columns listed in
        ``CREDIT_MEASURE_COLUMNS``.

    ``market_open(open_date, underlying, *, market_status)``
        ``open_date`` is exactly one pandas business day before the resolved
        Market Date. It is independent of any older source Risk date produced
        by readiness Age or a force override. Return unique market keys plus
        numeric ``Open`` and the applicable market-owned tenor-order columns.
        ``underlying`` is one member of the ordered, unique scope from validated
        Risk. The framework calls once per Underlying and concatenates only
        after every call succeeds. An empty
        DataFrame with the correct columns is allowed and means that the opening
        leg is unavailable. ``market_status`` is supplied by the manager and is
        exactly ``Live`` or ``OFFICIAL``; connectors must not infer it again.

    ``market_status(market_date, underlying, *, market_status)``
        Return the same market keys plus numeric ``Current``. ``Market Status`` may
        be supplied, but if present it must exactly match the explicit
        ``market_status`` argument. An empty, correctly shaped frame is allowed
        and is surfaced as unavailable market data, never as zero.

    The normalized market keys are ``Risk Type``, ``Risk Greek``, ``Underlying``,
    and the tenor columns declared by the corresponding ``ProductSpec``. The
    validators below enforce uniqueness, numeric types, finite values, and the
    source-specific identity before anything reaches aggregation or P&L.
    """

    risk: Callable[[pd.Timestamp], pd.DataFrame]
    # Open receives T-1; Current receives the resolved Market Date. Neither
    # receives a product's potentially older readiness/forced Risk date.
    market_open: ProductMarketConnector
    market_status: ProductMarketConnector


PRODUCT_SPECS_BY_SOURCE_TYPE = {
    spec.source_type: spec for spec in PRODUCT_SPECS.values()
}
if len(PRODUCT_SPECS_BY_SOURCE_TYPE) != len(PRODUCT_SPECS):
    raise RuntimeError("Product catalogue Source Type values must be unique")
_PRODUCT_PAIRS = {(spec.risk_type, spec.risk_greek) for spec in PRODUCT_SPECS.values()}
if len(_PRODUCT_PAIRS) != len(PRODUCT_SPECS):
    raise RuntimeError("Product catalogue Risk Type/Risk Greek pairs must be unique")
DIRECT_PL_RISK_PAIRS = frozenset(
    (classification.risk_type, classification.risk_greek)
    for classification in DIRECT_PL_CLASSIFICATIONS
)
if len(DIRECT_PL_RISK_PAIRS) != len(DIRECT_PL_CLASSIFICATIONS):
    raise RuntimeError("Direct P&L Risk Type/Risk Greek pairs must be unique")
if _PRODUCT_PAIRS & DIRECT_PL_RISK_PAIRS:
    raise RuntimeError("Direct P&L identities must not also be ProductSpecs")
CROSS_GAMMA_INPUT_RISK_PAIRS = frozenset(
    (risk_type, source_risk_greek)
    for risk_type in {spec.risk_type for spec in PRODUCT_SPECS.values()}
    for source_risk_greek in XGAMMA_SOURCE_RISK_GREEKS
)
if (_PRODUCT_PAIRS | DIRECT_PL_RISK_PAIRS) & CROSS_GAMMA_INPUT_RISK_PAIRS:
    raise RuntimeError("Cross Gamma input identities must be release-only pairs")
RELEASE_RISK_PAIRS = frozenset(
    _PRODUCT_PAIRS | DIRECT_PL_RISK_PAIRS | CROSS_GAMMA_INPUT_RISK_PAIRS
)
