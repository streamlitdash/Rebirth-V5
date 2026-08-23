"""Generate deterministic connectors and streamed realistic history fixtures.

The small connector CSVs remain deliberately visible fake data. The annual
archive is a larger, realistic but still fake Parquet demonstration: every
daily leaf is generated, validated, written, and released before the next date
is built, so a full second annual tree or 262 object-heavy frames never exists.

Run from any directory::

    python tools/s01_fixtures.py
    python tools/s01_fixtures.py --check
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


FAKE_NOTICE = "FAKE_REPLACE_ME"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_ROOT / "data"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rebirth.domain.s01_schema import (  # noqa: E402 - support execution from any directory
    PORTFOLIO_CONFIG_REQUIRED_COLUMNS,
    PORTFOLIO_FIELD_BY_KEY,
    TENOR_COLUMNS,
    TENOR_OPTION,
    TENOR_OPTION_ORDER,
    TENOR_ORDER_COLUMNS,
    TENOR_SWAP,
    TENOR_SWAP_ORDER,
)
from rebirth.domain.s02_products import (  # noqa: E402 - support execution from any directory
    CREDIT_MEASURE_COLUMNS,
    CROSS_GAMMA_INPUT_RISK_PAIRS,
    CURRENT,
    DIRECT_PL_CLASSIFICATIONS,
    DRISK,
    MARKET_MOVE,
    MARKET_STATUS,
    OFFICIAL,
    OPEN,
    PL,
    PRODUCT_SPECS_BY_SOURCE_TYPE,
    RISK,
    SOURCE_TYPE,
    VOL_SCORE,
)
from rebirth.domain.s06_reporting import (  # noqa: E402 - support execution from any directory
    load_reported_underlying_mapping,
)
from rebirth.history import (  # noqa: E402 - support execution from any directory
    ARCHIVE_SCHEMA_VERSION,
    COLOSSUS_COLUMNS,
    MARKET_ARCHIVE_COLUMNS,
    MARKET_IDENTITY_COLUMNS,
    STOCK_ARCHIVE_FILE_NAMES,
    archive_official_snapshot,
    validate_colossus_frame,
    validate_market_archive_frame,
    validate_risk_archive_frame,
)
from rebirth.domain.s09_stock import (  # noqa: E402 - support execution from any directory
    STOCK_COLUMNS,
    STOCK_IDENTITY_COLUMNS,
    STOCK_NUMERIC_COLUMNS,
    STOCK_TEXT_COLUMNS,
    validate_stock_frame,
)

HISTORY_START_DATE = "2025-08-21"
HISTORY_END_DATE = "2026-08-21"
HISTORICAL_MARKET_DATES = tuple(
    value.date().isoformat()
    for value in pd.bdate_range(start=HISTORY_START_DATE, end=HISTORY_END_DATE)
)
FIXTURE_TAG = "deterministic-rebirth-v4"
LEGACY_FIXTURE_TAG = "deterministic-rebirth-v3"
HISTORY_RISK_ROWS = 10_000
HISTORY_MARKET_ROWS = 5_000
HISTORY_COLOSSUS_ROWS = 5_000
HISTORY_STOCK_ROWS = 5_000
HISTORY_MATCHED_COLOSSUS_ROWS = 2_000
CURRENT_RISK_ROWS = 10_000
CURRENT_PORTFOLIO_COUNT = 500
HISTORY_SOURCE_TYPES = tuple(PRODUCT_SPECS_BY_SOURCE_TYPE)
RISK_ARCHIVE_DIRECTORY = DATA_DIRECTORY / "histo"


@dataclass(frozen=True)
class FixtureSource:
    """Demo-only identity and quote scale for one canonical Source Type."""

    source_type: str
    underlyings: tuple[str, str, str]
    groups: tuple[str, str, str]
    market_kind: str


@dataclass(frozen=True)
class OfficialHistoryFixture:
    """One deterministic daily input to the live official archive writer."""

    market_date: str
    revision: int
    risk_dates: Mapping[str, pd.Timestamp]
    risk: pd.DataFrame
    colossus: pd.DataFrame
    market: pd.DataFrame
    stock: pd.DataFrame


@dataclass(frozen=True)
class _FixtureArchiveSnapshot:
    """Small snapshot implementing the archive writer's live protocol."""

    revision: int
    refreshed_at: datetime
    system_date: pd.Timestamp
    market_date: pd.Timestamp
    market_status: str
    risk_dates: Mapping[str, pd.Timestamp]
    dashboard_frame: pd.DataFrame
    market_frame: pd.DataFrame
    stock_frame: pd.DataFrame
    errors: tuple[str, ...]
    fixture: str


SOURCE_FIXTURES = (
    FixtureSource(
        "fx/delta",
        ("EUR/USD", "USD/JPY", "GBP/USD"),
        ("G10", "G10", "G10"),
        "fx",
    ),
    FixtureSource(
        "fx/gamma",
        ("EUR/USD", "USD/JPY", "GBP/USD"),
        ("G10", "G10", "G10"),
        "fx",
    ),
    FixtureSource(
        "fx/vega",
        ("EUR/USD Vol", "USD/JPY Vol", "GBP/USD Vol"),
        ("G10", "G10", "G10"),
        "vol",
    ),
    FixtureSource(
        "ir/delta",
        ("USD SOFR", "EUR ESTR", "GBP SONIA"),
        ("G10", "G10", "G10"),
        "rate",
    ),
    FixtureSource(
        "ir/gamma",
        ("USD SOFR", "EUR ESTR", "GBP SONIA"),
        ("G10", "G10", "G10"),
        "rate",
    ),
    FixtureSource(
        "ir/deltavega",
        ("USD SOFR Vol", "EUR ESTR Vol", "GBP SONIA Vol"),
        ("G10", "G10", "G10"),
        "vol",
    ),
    FixtureSource(
        "ir/xccy",
        ("EUR/USD XCCY", "GBP/USD XCCY", "USD/JPY XCCY"),
        ("G10", "G10", "G10"),
        "rate",
    ),
    FixtureSource(
        "ir/xccyvega",
        ("EUR/USD XCCY Vol", "GBP/USD XCCY Vol", "USD/JPY XCCY Vol"),
        ("G10", "G10", "G10"),
        "vol",
    ),
    FixtureSource(
        "ir/inflation",
        ("US CPI", "EU HICP", "UK RPI"),
        ("G10", "G10", "G10"),
        "rate",
    ),
    FixtureSource(
        "ir/inflationvega",
        ("US CPI Vol", "EU HICP Vol", "UK RPI Vol"),
        ("G10", "G10", "G10"),
        "vol",
    ),
    FixtureSource(
        "ir/basis",
        ("USD 3M/6M", "EUR 3M/6M", "GBP 3M/6M"),
        ("G10", "G10", "G10"),
        "rate",
    ),
    FixtureSource(
        "ir/bond",
        ("UST", "Bund", "Gilt"),
        ("G10", "G10", "G10"),
        "rate",
    ),
    FixtureSource(
        "credit/delta",
        ("CDX IG", "iTraxx Main", "Ford CDS"),
        ("Index", "Index", "Single Name"),
        "credit",
    ),
    FixtureSource(
        "credit/vega",
        ("CDX IG Vol", "iTraxx Main Vol", "Ford CDS Vol"),
        ("Index", "Index", "Single Name"),
        "credit",
    ),
    FixtureSource(
        "commo/delta",
        ("Brent", "Gold", "TTF Gas"),
        ("Oil", "Precious", "Gas"),
        "commodity",
    ),
    FixtureSource(
        "commo/vega",
        ("Brent Vol", "Gold Vol", "TTF Gas Vol"),
        ("Oil", "Precious", "Gas"),
        "vol",
    ),
)
SOURCE_BY_TYPE = {fixture.source_type: fixture for fixture in SOURCE_FIXTURES}
EXPECTED_SOURCE_TYPES = tuple(fixture.source_type for fixture in SOURCE_FIXTURES)

# This is the complete market-owned, ordered tenor structure for each product.
# Risk deliberately uses a proper subset, defined by ``_risk_axis_values``, so
# the fixtures exercise both the full MarketBook and the risk-only joined view.
FULL_AXIS_VALUES: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "fx/vega": {TENOR_SWAP: ("1M", "3M", "6M", "1Y")},
    "ir/delta": {TENOR_SWAP: ("6M", "1Y", "2Y", "5Y", "10Y", "30Y")},
    "ir/gamma": {TENOR_SWAP: ("1Y", "2Y", "5Y", "10Y")},
    "ir/deltavega": {
        TENOR_SWAP: ("6M", "1Y", "2Y", "5Y", "10Y"),
        TENOR_OPTION: ("1M", "3M", "6M", "1Y"),
    },
    "ir/xccy": {TENOR_SWAP: ("1Y", "2Y", "5Y", "10Y")},
    "ir/xccyvega": {
        TENOR_SWAP: ("1Y", "3Y", "5Y", "10Y", "30Y"),
        TENOR_OPTION: ("3M", "6M", "1Y", "2Y"),
    },
    "ir/inflation": {TENOR_SWAP: ("2Y", "5Y", "10Y", "20Y", "30Y")},
    "ir/inflationvega": {
        TENOR_SWAP: ("2Y", "5Y", "10Y", "20Y", "30Y"),
        TENOR_OPTION: ("6M", "1Y", "2Y"),
    },
    "ir/basis": {TENOR_SWAP: ("3M", "6M", "1Y", "2Y", "5Y")},
    "ir/bond": {TENOR_SWAP: ("2Y", "5Y", "10Y", "30Y")},
    "credit/delta": {TENOR_SWAP: ("1Y", "3Y", "5Y", "7Y", "10Y")},
    "credit/vega": {TENOR_SWAP: ("1M", "3M", "6M", "1Y")},
    "commo/delta": {TENOR_SWAP: ("1M", "3M", "6M", "1Y")},
    "commo/vega": {TENOR_SWAP: ("1M", "3M", "6M", "1Y")},
}

MAPPED_PORTFOLIOS = (
    ("BOOK_A", "XVA", "Activity 1", "SOG_ALPHA", "Core"),
    ("BOOK_B", "XVA", "Activity 1", "SOG_ALPHA", "Core"),
    ("BOOK_C", "XVA", "Activity 2", "SOG_BETA", "Flow"),
    ("BOOK_D", "Hedges", "Activity 3", "SOG_BETA", "Hedge"),
    ("BOOK_E", "Hedges", "Activity 3", "SOG_GAMMA", "Hedge"),
)
UNMAPPED_PORTFOLIO = "BOOK_UNMAPPED"
RISK_PORTFOLIOS = tuple(
    f"BOOK-{number + 1:04d} · TRADER-{(number // 2) % 160 + 1:03d}"
    for number in range(CURRENT_PORTFOLIO_COUNT)
)
HISTORY_PORTFOLIO_COUNT = 640
STOCK_PORTFOLIO_COUNT = 500

# Deliberate stale-readiness examples. Every other fake source is Age 0 and
# therefore uses the centralized Market Date - BDay(1) base; these governed
# Age-1 signals move one additional pandas business day back.
AGE_ONE_SOURCE_TYPES = frozenset({"ir/inflationvega", "credit/vega", "commo/vega"})
CREDIT_FACTORS = {
    "SP01": 1.0,
    "PSP01": 0.82,
    "PM01": 1.18,
    "PM01P": 0.011,
    "Theta": -0.08,
    "JTD": 0.35,
}

SCHEMAS = {
    "s01_readiness.csv": ("Risk Type", "Risk Greek", "Age"),
    "s02_checker.csv": ("Risk Type", "Risk Greek", "MMMFile", "Product"),
    "s03_risk.csv": (
        "Source Type",
        "Underlying",
        *TENOR_COLUMNS,
        "Portfolio",
        "Group",
        "Risk",
        "dRisk",
        VOL_SCORE,
        *CREDIT_MEASURE_COLUMNS,
    ),
    "s04_open.csv": (
        "Source Type",
        "Underlying",
        *TENOR_COLUMNS,
        *TENOR_ORDER_COLUMNS,
        "Open",
    ),
    "s05_current.csv": (
        "Source Type",
        "Underlying",
        *TENOR_COLUMNS,
        *TENOR_ORDER_COLUMNS,
        CURRENT,
    ),
    "s06_portfolios.csv": PORTFOLIO_CONFIG_REQUIRED_COLUMNS,
    "s07_thresholds.csv": ("Risk Type", "Risk Greek", "PL", "Risk", "dRisk"),
}


class FixtureValidationError(RuntimeError):
    """Raised when generated or checked fixture data violates its contract."""


def _fake(value: str) -> str:
    return f"{FAKE_NOTICE} - {value}"


def _history_portfolio_config_rows() -> list[dict[str, str]]:
    """Return the same 640-portfolio authority used by annual Risk history."""

    rows: list[dict[str, str]] = []
    for number in range(HISTORY_PORTFOLIO_COUNT):
        slot, leg = divmod(number, 2)
        rows.append(
            dict(
                zip(
                    PORTFOLIO_CONFIG_REQUIRED_COLUMNS,
                    (
                        _fake(f"BOOK-{number + 1:04d} · TRADER-{slot % 160 + 1:03d}"),
                        "XVA" if leg == 0 else "Hedges",
                        _fake(f"Activity {slot % 24 + 1}"),
                        _fake(f"SOG-{slot % 80 + 1:03d}"),
                        _fake(f"Business {slot % 18 + 1:02d}"),
                    ),
                    strict=True,
                )
            )
        )
    return rows


def _stable_int(*parts: object) -> int:
    payload = "|".join(str(part) for part in parts).encode("utf-8")
    return int(hashlib.sha256(payload).hexdigest()[:16], 16)


def _number(value: float, decimals: int = 6) -> str:
    rendered = f"{value:.{decimals}f}".rstrip("0").rstrip(".")
    return "0" if rendered in {"", "-0"} else rendered


def _full_axis_values(source_type: str) -> Mapping[str, tuple[str, ...]]:
    spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    expected_axes = tuple(spec.tenor_columns)
    configured = FULL_AXIS_VALUES.get(source_type, {})
    if tuple(configured) != expected_axes:
        raise FixtureValidationError(
            f"{source_type} fixture axes {tuple(configured)} do not match "
            f"ProductSpec axes {expected_axes}"
        )
    return configured


def _risk_axis_values(source_type: str) -> Mapping[str, tuple[str, ...]]:
    """Return several ordered risk layers while preserving market-only tenors."""
    return {
        axis: values[:-1] for axis, values in _full_axis_values(source_type).items()
    }


def _market_keys(source_type: str, *, risk_only: bool) -> list[tuple[str, ...]]:
    fixture = SOURCE_BY_TYPE[source_type]
    spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    axes = (
        _risk_axis_values(source_type) if risk_only else _full_axis_values(source_type)
    )
    keys: list[tuple[str, ...]] = []
    for raw_underlying in fixture.underlyings:
        underlying = _fake(raw_underlying)
        if not spec.axes:
            keys.append((underlying,))
        elif len(spec.axes) == 1:
            keys.extend(
                (underlying, _fake(tenor)) for tenor in axes[spec.axes[0].column]
            )
        elif len(spec.axes) == 2:
            first, second = spec.axes
            keys.extend(
                (underlying, _fake(first_value), _fake(second_value))
                for first_value in axes[first.column]
                for second_value in axes[second.column]
            )
        else:  # pragma: no cover - the registry validation rejects this first
            raise FixtureValidationError(f"{source_type} has unsupported axis count")
    return keys


def _key_fields(source_type: str, key: tuple[str, ...]) -> dict[str, str]:
    spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    return {
        "Underlying": key[0],
        **{axis.column: key[index + 1] for index, axis in enumerate(spec.axes)},
    }


def _risk_values(
    source_type: str,
    market_key: tuple[str, ...],
    portfolio: str,
) -> tuple[float, float]:
    risk_seed = _stable_int(source_type, *market_key, portfolio, "risk")
    drisk_seed = _stable_int(source_type, *market_key, portfolio, "drisk")
    risk_sign = -1.0 if risk_seed % 3 == 0 else 1.0
    drisk_sign = -1.0 if drisk_seed % 2 == 0 else 1.0
    risk = risk_sign * float(250_000 + risk_seed % 4_750_001)
    drisk = drisk_sign * float(10_000 + drisk_seed % 540_001)
    return risk, drisk


def _vol_score(
    source_type: str,
    market_key: tuple[str, ...],
    portfolio: str,
) -> float:
    """Return one stable connector-owned fake percentile-style score."""

    seed = _stable_int(source_type, *market_key, portfolio, "vol-score")
    return 5.0 + (seed % 95_001) / 1_000.0


def _fixture_group(source_type: str, underlying: str) -> str:
    """Return connector-owned demo Group metadata for one raw Underlying."""

    fixture = SOURCE_BY_TYPE[source_type]
    groups_by_underlying = {
        _fake(raw_underlying): group
        for raw_underlying, group in zip(fixture.underlyings, fixture.groups)
    }
    return groups_by_underlying[underlying]


def _market_values(
    source_type: str, market_key: tuple[str, ...]
) -> tuple[float, float]:
    fixture = SOURCE_BY_TYPE[source_type]
    seed = _stable_int(source_type, *market_key, "market")
    move_seed = _stable_int(source_type, *market_key, "move")
    fraction = (seed % 100_000) / 100_000.0
    sign = -1.0 if move_seed % 2 == 0 else 1.0
    step = 1 + move_seed % 25

    if fixture.market_kind == "fx":
        opening = 0.75 + 0.70 * fraction
        move = sign * step * 0.0001
    elif fixture.market_kind == "rate":
        opening = 0.005 + 0.075 * fraction
        move = sign * step * 0.00005
    elif fixture.market_kind == "vol":
        opening = 0.05 + 0.30 * fraction
        move = sign * step * 0.0005
    elif fixture.market_kind == "credit":
        opening = 40.0 + 400.0 * fraction
        move = sign * step * 0.10
    elif fixture.market_kind == "commodity":
        opening = 25.0 + 125.0 * fraction
        move = sign * step * 0.05
    else:  # pragma: no cover - static source validation covers this
        raise FixtureValidationError(f"Unsupported market kind {fixture.market_kind!r}")
    return opening, opening + move


def _build_risk_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    schema = SCHEMAS["s03_risk.csv"]
    risk_keys = [
        (source_type, market_key)
        for source_type in EXPECTED_SOURCE_TYPES
        for market_key in _market_keys(source_type, risk_only=True)
    ]
    for row_index in range(CURRENT_RISK_ROWS):
        source_type, market_key = risk_keys[row_index % len(risk_keys)]
        product = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
        raw_portfolio = RISK_PORTFOLIOS[row_index % CURRENT_PORTFOLIO_COUNT]
        risk, drisk = _risk_values(source_type, market_key, raw_portfolio)
        row = {column: "" for column in schema}
        row.update(
            {
                "Source Type": source_type,
                **_key_fields(source_type, market_key),
                "Portfolio": _fake(raw_portfolio),
                "Group": _fixture_group(source_type, market_key[0]),
                "Risk": _number(risk, 2),
                "dRisk": _number(drisk, 2),
                VOL_SCORE: _number(
                    _vol_score(source_type, market_key, raw_portfolio), 3
                ),
            }
        )
        if product.risk_type == "Credit":
            for measure, factor in CREDIT_FACTORS.items():
                row[f"Risk {measure}"] = _number(risk * factor, 2)
                row[f"dRisk {measure}"] = _number(drisk * factor, 2)
        rows.append(row)
    return rows


def _build_market_rows(value_column: str) -> list[dict[str, str]]:
    filename = "s04_open.csv" if value_column == "Open" else "s05_current.csv"
    rows: list[dict[str, str]] = []
    for source_type in EXPECTED_SOURCE_TYPES:
        product = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
        keys = _market_keys(source_type, risk_only=False)
        axis_orders: dict[str, dict[tuple[str, str], int]] = {}
        for axis in product.axes:
            configured = _full_axis_values(source_type)[axis.column]
            axis_orders[axis.column] = {
                (_fake(underlying), _fake(tenor)): rank
                for underlying in SOURCE_BY_TYPE[source_type].underlyings
                for rank, tenor in enumerate(configured)
            }
        for key in keys:
            opening, current = _market_values(source_type, key)
            fields = _key_fields(source_type, key)
            row = {column: "" for column in SCHEMAS[filename]}
            row.update({"Source Type": source_type, **fields})
            for axis in product.axes:
                row[axis.order_column] = str(
                    axis_orders[axis.column][
                        (fields["Underlying"], fields[axis.column])
                    ]
                )
            row[value_column] = _number(opening if value_column == "Open" else current)
            rows.append(row)
    return rows


def build_datasets() -> dict[str, list[dict[str, str]]]:
    readiness = [
        {
            "Risk Type": product.risk_type,
            "Risk Greek": product.risk_greek,
            "Age": "1" if product.source_type in AGE_ONE_SOURCE_TYPES else "0",
        }
        for product in PRODUCT_SPECS_BY_SOURCE_TYPE.values()
    ]
    checker = [
        {
            "Risk Type": product.risk_type,
            "Risk Greek": product.risk_greek,
            "MMMFile": _fake(
                f"{product.source_type.replace('/', '_')}_{position.casefold()}.mmm"
            ),
            "Product": position,
        }
        for product in PRODUCT_SPECS_BY_SOURCE_TYPE.values()
        for position in ("XVA", "Hedges")
    ]
    portfolio_config = [
        dict(
            zip(
                PORTFOLIO_CONFIG_REQUIRED_COLUMNS,
                (
                    _fake(portfolio),
                    product,
                    _fake(activity),
                    _fake(signoff_group),
                    _fake(category),
                ),
                strict=True,
            )
        )
        for portfolio, product, activity, signoff_group, category in MAPPED_PORTFOLIOS
    ]
    portfolio_config.extend(_history_portfolio_config_rows())
    thresholds = [
        {
            "Risk Type": product.risk_type,
            "Risk Greek": product.risk_greek,
            "PL": "25000",
            "Risk": "2500000",
            "dRisk": "250000",
        }
        for product in PRODUCT_SPECS_BY_SOURCE_TYPE.values()
    ]
    thresholds.extend(
        {
            "Risk Type": classification.risk_type,
            "Risk Greek": classification.risk_greek,
            "PL": "25000",
            "Risk": "2500000",
            "dRisk": "250000",
        }
        for classification in DIRECT_PL_CLASSIFICATIONS
    )
    thresholds.extend(
        {
            "Risk Type": risk_type,
            "Risk Greek": risk_greek,
            "PL": "25000",
            "Risk": "2500000",
            "dRisk": "250000",
        }
        for risk_type, risk_greek in sorted(CROSS_GAMMA_INPUT_RISK_PAIRS)
    )
    return {
        "s01_readiness.csv": readiness,
        "s02_checker.csv": checker,
        "s03_risk.csv": _build_risk_rows(),
        "s04_open.csv": _build_market_rows("Open"),
        "s05_current.csv": _build_market_rows(CURRENT),
        "s06_portfolios.csv": portfolio_config,
        "s07_thresholds.csv": thresholds,
    }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise FixtureValidationError(message)


def _finite_numeric(value: str, *, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FixtureValidationError(
            f"{label} must be numeric; found {value!r}"
        ) from exc
    if not math.isfinite(number):
        raise FixtureValidationError(f"{label} must be finite; found {value!r}")
    return number


def _row_key(source_type: str, row: Mapping[str, str]) -> tuple[str, ...]:
    spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    return (row["Underlying"], *(row[axis.column] for axis in spec.axes))


def _validate_static_contract() -> None:
    registered = set(PRODUCT_SPECS_BY_SOURCE_TYPE)
    fixture_sources = set(SOURCE_BY_TYPE)
    _require(
        fixture_sources == registered,
        "Fixture source metadata must exactly cover the ProductSpec registry",
    )
    _require(
        len(SOURCE_FIXTURES) == len(SOURCE_BY_TYPE),
        "Fixture Source Type values must be unique",
    )
    for source_type, spec in PRODUCT_SPECS_BY_SOURCE_TYPE.items():
        axes = tuple(spec.tenor_columns)
        _require(
            axes in {(), (TENOR_SWAP,), tuple(TENOR_COLUMNS)},
            f"{source_type} must be axisless, Tenor Swap-only, or a true surface",
        )
        configured = _full_axis_values(source_type)
        for axis, values in configured.items():
            _require(len(values) >= 3, f"{source_type} {axis} needs several layers")
            _require(
                len(values) == len(set(values)), f"{source_type} {axis} duplicates"
            )
        _require(
            len(set(SOURCE_BY_TYPE[source_type].underlyings)) == 3,
            f"{source_type} must have three unique Underlyings",
        )
    _require(
        PRODUCT_SPECS_BY_SOURCE_TYPE["ir/gamma"].tenor_columns == [TENOR_SWAP],
        "IR Gamma must be Tenor Swap-only",
    )
    _require(
        PRODUCT_SPECS_BY_SOURCE_TYPE["credit/vega"].tenor_columns == [TENOR_SWAP],
        "Credit Vega must be Tenor Swap-only",
    )


def validate_datasets(datasets: Mapping[str, Sequence[Mapping[str, str]]]) -> None:
    _validate_static_contract()
    _require(set(datasets) == set(SCHEMAS), "Generated file set does not match SCHEMAS")
    for filename, schema in SCHEMAS.items():
        rows = datasets[filename]
        _require(bool(rows), f"{filename} must contain rows")
        for index, row in enumerate(rows):
            _require(
                tuple(row) == schema,
                f"{filename} row {index} columns differ from exact schema {schema}",
            )

    product_pairs = {
        (spec.risk_type, spec.risk_greek)
        for spec in PRODUCT_SPECS_BY_SOURCE_TYPE.values()
    }
    readiness = datasets["s01_readiness.csv"]
    readiness_pairs = [(row["Risk Type"], row["Risk Greek"]) for row in readiness]
    _require(
        set(readiness_pairs) == product_pairs,
        "Readiness pair coverage is incomplete",
    )
    _require(len(readiness_pairs) == len(set(readiness_pairs)), "Readiness duplicates")
    _require(all(row["Age"] in {"0", "1"} for row in readiness), "Age must be 0 or 1")

    checker = datasets["s02_checker.csv"]
    checker_keys = [
        (row["Risk Type"], row["Risk Greek"], row["MMMFile"], row["Product"])
        for row in checker
    ]
    _require(len(checker_keys) == len(set(checker_keys)), "Checker rows must be unique")
    _require(
        {(row["Risk Type"], row["Risk Greek"]) for row in checker} == product_pairs,
        "Checker pair coverage is incomplete",
    )
    checker_products: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in checker:
        checker_products[(row["Risk Type"], row["Risk Greek"])].add(row["Product"])
        _require(FAKE_NOTICE in row["MMMFile"], "MMMFile must retain fake notice")
        _require(row["MMMFile"].endswith(".mmm"), "MMMFile must use .mmm")
    _require(
        all(products == {"XVA", "Hedges"} for products in checker_products.values()),
        "Every checker pair must cover XVA and Hedges",
    )

    risk = datasets["s03_risk.csv"]
    market_open = datasets["s04_open.csv"]
    market_current = datasets["s05_current.csv"]
    expected_sources = set(EXPECTED_SOURCE_TYPES)
    _require(len(risk) == CURRENT_RISK_ROWS, "Risk must contain 10,000 positions")
    _require(
        {row["Portfolio"] for row in risk}
        == {_fake(portfolio) for portfolio in RISK_PORTFOLIOS},
        "Risk must exercise exactly 500 governed Portfolios",
    )
    for label, rows in (
        ("Risk", risk),
        ("Open", market_open),
        (CURRENT, market_current),
    ):
        _require(
            {row["Source Type"] for row in rows} == expected_sources,
            f"{label} Source Type coverage is incomplete",
        )

    grouped_risk: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    grouped_open: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    grouped_current: dict[str, list[Mapping[str, str]]] = defaultdict(list)
    for row in risk:
        grouped_risk[row["Source Type"]].append(row)
    for row in market_open:
        grouped_open[row["Source Type"]].append(row)
    for row in market_current:
        grouped_current[row["Source Type"]].append(row)

    all_axis_columns = TENOR_COLUMNS
    all_order_columns = TENOR_ORDER_COLUMNS
    for source_type, product in PRODUCT_SPECS_BY_SOURCE_TYPE.items():
        risk_rows = grouped_risk[source_type]
        open_rows = grouped_open[source_type]
        current_rows = grouped_current[source_type]
        risk_keys = {_row_key(source_type, row) for row in risk_rows}
        open_keys = [_row_key(source_type, row) for row in open_rows]
        current_keys = [_row_key(source_type, row) for row in current_rows]
        positions = [
            (*_row_key(source_type, row), row["Portfolio"]) for row in risk_rows
        ]

        _require(
            len(open_keys) == len(set(open_keys)), f"{source_type} Open duplicates"
        )
        _require(
            len(current_keys) == len(set(current_keys)),
            f"{source_type} Current duplicates",
        )
        _require(
            len(positions) == len(set(positions)), f"{source_type} Risk duplicates"
        )
        _require(
            set(open_keys) == set(current_keys), f"{source_type} market legs differ"
        )
        _require(
            risk_keys <= set(open_keys), f"{source_type} Risk is outside MarketBook"
        )
        if product.axes:
            _require(
                risk_keys < set(open_keys),
                f"{source_type} must retain market-only tenor rows",
            )
        else:
            _require(risk_keys == set(open_keys), f"{source_type} axisless keys differ")
        _require(
            len({row["Portfolio"] for row in risk_rows}) >= 100,
            f"{source_type} must exercise a broad Portfolio sample",
        )

        for row in risk_rows:
            for column in ("Underlying", *product.tenor_columns, "Portfolio"):
                _require(
                    FAKE_NOTICE in row[column],
                    f"{source_type} Risk {column} lacks fake notice",
                )
            for column in set(all_axis_columns) - set(product.tenor_columns):
                _require(row[column] == "", f"{source_type} must leave {column} blank")
            _finite_numeric(row["Risk"], label=f"{source_type} Risk")
            _finite_numeric(row["dRisk"], label=f"{source_type} dRisk")
            vol_score = _finite_numeric(
                row[VOL_SCORE], label=f"{source_type} Vol Score"
            )
            _require(
                0.0 <= vol_score <= 100.0,
                f"{source_type} Vol Score must be between 0 and 100",
            )
            if product.risk_type == "Credit":
                for column in CREDIT_MEASURE_COLUMNS:
                    _finite_numeric(row[column], label=f"{source_type} {column}")
            else:
                _require(
                    all(row[column] == "" for column in CREDIT_MEASURE_COLUMNS),
                    f"{source_type} must leave Credit measures blank",
                )

        for label, rows, value_column in (
            ("Open", open_rows, "Open"),
            (CURRENT, current_rows, CURRENT),
        ):
            for row in rows:
                _finite_numeric(row[value_column], label=f"{source_type} {label}")
                for column in ("Underlying", *product.tenor_columns):
                    _require(
                        FAKE_NOTICE in row[column],
                        f"{source_type} {label} {column} lacks fake notice",
                    )
                for column in set(all_axis_columns) - set(product.tenor_columns):
                    _require(
                        row[column] == "",
                        f"{source_type} {label} must leave {column} blank",
                    )
                for column in set(all_order_columns) - set(product.tenor_order_columns):
                    _require(
                        row[column] == "",
                        f"{source_type} {label} must leave {column} blank",
                    )
            for axis in product.axes:
                expected_order = {
                    _fake(tenor): rank
                    for rank, tenor in enumerate(
                        _full_axis_values(source_type)[axis.column]
                    )
                }
                for row in rows:
                    order = _finite_numeric(
                        row[axis.order_column],
                        label=f"{source_type} {label} {axis.order_column}",
                    )
                    _require(
                        order.is_integer() and order >= 0,
                        f"{source_type} {label} rank must be a non-negative integer",
                    )
                    _require(
                        int(order) == expected_order[row[axis.column]],
                        f"{source_type} {label} does not preserve market tenor order",
                    )

    portfolio_config = datasets["s06_portfolios.csv"]
    portfolios = [row["Portfolio"] for row in portfolio_config]
    _require(
        len(portfolios) == len(set(portfolios)), "Config Portfolios must be unique"
    )
    product_column = PORTFOLIO_FIELD_BY_KEY["product"].external_name
    _require(
        {row[product_column] for row in portfolio_config} == {"XVA", "Hedges"},
        "Config needs XVA and Hedges",
    )
    for row in portfolio_config:
        for column in PORTFOLIO_CONFIG_REQUIRED_COLUMNS:
            if column != product_column:
                _require(
                    FAKE_NOTICE in row[column], f"Config {column} lacks fake notice"
                )

    thresholds = datasets["s07_thresholds.csv"]
    threshold_pairs = [(row["Risk Type"], row["Risk Greek"]) for row in thresholds]
    expected_threshold_pairs = (
        product_pairs
        | {
            (classification.risk_type, classification.risk_greek)
            for classification in DIRECT_PL_CLASSIFICATIONS
        }
        | set(CROSS_GAMMA_INPUT_RISK_PAIRS)
    )
    _require(
        set(threshold_pairs) == expected_threshold_pairs,
        "Threshold coverage is incomplete",
    )
    _require(len(threshold_pairs) == len(set(threshold_pairs)), "Thresholds duplicate")
    for row in thresholds:
        for column in ("PL", "Risk", "dRisk"):
            _require(
                _finite_numeric(row[column], label=f"threshold {column}") > 0,
                "Thresholds must be positive",
            )


def _validate_history_date_range(dates: Sequence[str]) -> None:
    _require(len(dates) >= 252, "History must contain at least 252 business dates")
    parsed = pd.DatetimeIndex(pd.to_datetime(list(dates), format="%Y-%m-%d"))
    _require(parsed.is_monotonic_increasing, "History dates must be ordered")
    _require(parsed.is_unique, "History dates must be unique")
    _require(bool((parsed.dayofweek < 5).all()), "History dates must be weekdays")
    _require(
        (parsed[-1] - parsed[0]).days >= 365,
        "History must span at least one full calendar year",
    )
    _require(
        parsed[0].date().isoformat() == HISTORY_START_DATE
        and parsed[-1].date().isoformat() == HISTORY_END_DATE,
        "History endpoints must match the governed fixture range",
    )


CURVE_HISTORY_TENORS = (
    "1M",
    "6M",
    "2Y",
    "5Y",
    "10Y",
    "30Y",
)
SURFACE_SWAP_HISTORY_TENORS = ("1Y", "5Y", "10Y", "30Y")
OPTION_HISTORY_TENORS = ("1M", "3M", "1Y")
RISK_HISTORY_COLUMNS = (
    "Source Type",
    "Risk Type",
    "Risk Greek",
    "Split",
    "Product",
    "Activity",
    "Display Bucket",
    "Group",
    "Reported Underlying",
    "Underlying",
    "Tenor Swap",
    "Tenor Option",
    "Tenor Swap Order",
    "Tenor Option Order",
    "Portfolio",
    "SignoffGroup",
    "Category",
    "Sub Category",
    "Portfolio Mapped",
    "Promotion Reason",
    "Promotion Score",
    "Risk Threshold",
    "dRisk Threshold",
    "PL Threshold",
    "Risk",
    "dRisk",
    "Open",
    "Current",
    "PL",
    "Move",
    "Market Available",
    "Market Data Status",
    *CREDIT_MEASURE_COLUMNS,
)
_MARKET_BASE_BY_KIND = {
    "fx": 1.05,
    "rate": 0.035,
    "vol": 0.18,
    "credit": 125.0,
    "commodity": 78.0,
}
_MARKET_MOVE_BY_KIND = {
    "fx": 0.0001,
    "rate": 0.00005,
    "vol": 0.0005,
    "credit": 0.10,
    "commodity": 0.05,
}
_STOCK_CURRENCIES = (
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CHF",
    "CAD",
    "AUD",
    "NZD",
    "SEK",
    "NOK",
    "DKK",
    "SGD",
)
_DERIVED_GAMMA_SOURCE = {
    "fx/gamma": "fx/delta",
    "ir/gamma": "ir/delta",
}


def _history_risk_dates(market_date: str) -> dict[str, pd.Timestamp]:
    selected = pd.Timestamp(market_date)
    source_offsets = {
        source_type: source_index % 3
        for source_index, source_type in enumerate(HISTORY_SOURCE_TYPES)
    }
    return {
        source_type: selected
        - pd.offsets.BDay(
            source_offsets[_DERIVED_GAMMA_SOURCE.get(source_type, source_type)]
        )
        for source_type in HISTORY_SOURCE_TYPES
    }


def _reported_underlying_lookup() -> dict[tuple[str, str, str], str]:
    """Load the one governed mapping used by both spot and history fixtures."""

    try:
        mapping = load_reported_underlying_mapping(DATA_DIRECTORY / "s09_reported.csv")
    except (OSError, TypeError, ValueError) as exc:
        raise FixtureValidationError(
            "Annual history requires the governed s09 Reported Underlying mapping"
        ) from exc
    return {
        (str(row["Risk Type"]), str(row["Risk Greek"]), str(row["Underlying"])): str(
            row["Reported Underlying"]
        )
        for row in mapping.to_dict("records")
    }


def _history_quote_catalog() -> pd.DataFrame:
    """Build the one small, date-independent 5,000-quote identity catalogue."""

    _require(
        HISTORY_SOURCE_TYPES == EXPECTED_SOURCE_TYPES,
        "Annual history must cover every live ProductSpec exactly once",
    )
    source_count = len(HISTORY_SOURCE_TYPES)
    base_count, extra = divmod(HISTORY_MARKET_ROWS, source_count)
    reported_lookup = _reported_underlying_lookup()
    rows: list[dict[str, object]] = []
    quote_index = 0
    for source_index, source_type in enumerate(HISTORY_SOURCE_TYPES):
        fixture = SOURCE_BY_TYPE[source_type]
        spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
        identity_fixture = SOURCE_BY_TYPE[
            _DERIVED_GAMMA_SOURCE.get(source_type, source_type)
        ]
        displayed_greek = (
            "Delta" if source_type in _DERIVED_GAMMA_SOURCE else spec.risk_greek
        )
        source_rows = base_count + int(source_index < extra)
        if len(spec.axes) == 2:
            cells_per_underlying = len(SURFACE_SWAP_HISTORY_TENORS) * len(
                OPTION_HISTORY_TENORS
            )
        elif len(spec.axes) == 1:
            cells_per_underlying = len(CURVE_HISTORY_TENORS)
        else:
            cells_per_underlying = 1
        for local_index in range(source_rows):
            underlying_index, cell_index = divmod(
                local_index,
                cells_per_underlying,
            )
            base_underlying = identity_fixture.underlyings[
                underlying_index % len(identity_fixture.underlyings)
            ]
            family_index = underlying_index // len(identity_fixture.underlyings)
            # Family zero is the exact live connector identity.  Extra Series
            # identities provide realistic archive scale without disconnecting
            # Quick Risk/Market from history.
            underlying = _fake(
                base_underlying
                if family_index == 0
                else f"{base_underlying} · Series {family_index:03d}"
            )
            if len(spec.axes) == 2:
                swap_rank, option_rank = divmod(
                    cell_index,
                    len(OPTION_HISTORY_TENORS),
                )
                tenor_swap = SURFACE_SWAP_HISTORY_TENORS[swap_rank]
                tenor_option = OPTION_HISTORY_TENORS[option_rank]
            elif len(spec.axes) == 1:
                swap_rank = cell_index
                option_rank = None
                tenor_swap = CURVE_HISTORY_TENORS[swap_rank]
                tenor_option = "N/A"
            else:
                swap_rank = None
                option_rank = None
                tenor_swap = "Spot" if spec.key == "fxdelta" else "N/A"
                tenor_option = "N/A"
            rows.append(
                {
                    "Quote Index": quote_index,
                    "Underlying Index": underlying_index,
                    SOURCE_TYPE: source_type,
                    "Risk Type": spec.risk_type,
                    "Risk Greek": spec.risk_greek,
                    "Underlying": underlying,
                    "Reported Underlying": reported_lookup.get(
                        (spec.risk_type, displayed_greek, underlying),
                        underlying,
                    ),
                    TENOR_SWAP: tenor_swap,
                    TENOR_OPTION: tenor_option,
                    TENOR_SWAP_ORDER: swap_rank,
                    TENOR_OPTION_ORDER: option_rank,
                    "Group": identity_fixture.groups[
                        underlying_index % len(identity_fixture.groups)
                    ],
                    "Market Kind": fixture.market_kind,
                }
            )
            quote_index += 1
    catalog = pd.DataFrame(rows)
    _require(len(catalog) == HISTORY_MARKET_ROWS, "Quote catalogue row count drift")
    return catalog


def _temporal_shock(date_index: int, identities: np.ndarray) -> np.ndarray:
    values = np.zeros(len(identities), dtype=float)
    for event, amplitude in ((43, 0.08), (121, -0.11), (198, 0.14), (238, -0.07)):
        distance = (date_index - event) / 3.5
        event_shape = math.exp(-(distance * distance))
        direction = np.where((identities + event) % 2 == 0, 1.0, -1.0)
        values += amplitude * event_shape * direction
    return values


def _build_history_market(
    catalog: pd.DataFrame,
    *,
    market_date: str,
    date_index: int,
) -> pd.DataFrame:
    quote_index = catalog["Quote Index"].to_numpy(dtype=np.int64)
    kinds = catalog["Market Kind"].astype(str)
    bases = kinds.map(_MARKET_BASE_BY_KIND).to_numpy(dtype=float)
    move_scales = kinds.map(_MARKET_MOVE_BY_KIND).to_numpy(dtype=float)
    identity_scale = 0.78 + ((quote_index * 7_919) % 10_000) / 20_000.0
    phase = (quote_index % 97) / 97.0 * 2.0 * math.pi
    trend = (date_index - 130) * 0.00018
    seasonality = 0.018 * np.sin((date_index * 2.0 * math.pi / 21.0) + phase)
    shock = _temporal_shock(date_index, quote_index)
    idiosyncratic = (
        ((quote_index * 104_729 + date_index * 15_485_863) % 2_003) - 1_001
    ) / 2_000_000.0
    opening = (
        bases * identity_scale * (1.0 + trend + seasonality + shock + idiosyncratic)
    )
    move = move_scales * (
        1.0 + 8.0 * np.sin((date_index * 2.0 * math.pi / 13.0) + phase) + 30.0 * shock
    )
    current = opening + move
    frame = catalog.loc[
        :,
        [
            SOURCE_TYPE,
            "Risk Type",
            "Risk Greek",
            "Underlying",
            TENOR_SWAP,
            TENOR_OPTION,
            TENOR_SWAP_ORDER,
            TENOR_OPTION_ORDER,
        ],
    ].copy()
    frame["Market Date"] = market_date
    frame[OPEN] = np.round(opening, 10)
    frame[CURRENT] = np.round(current, 10)
    frame[MARKET_MOVE] = frame[CURRENT] - frame[OPEN]
    frame[MARKET_STATUS] = OFFICIAL
    frame["Market Data Status"] = "Available"
    return validate_market_archive_frame(
        frame.loc[:, list(MARKET_ARCHIVE_COLUMNS)],
        market_date=market_date,
    )


def _build_history_risk(
    catalog: pd.DataFrame,
    market: pd.DataFrame,
    *,
    date_index: int,
) -> pd.DataFrame:
    quote_market = catalog.merge(
        market.loc[:, [*MARKET_IDENTITY_COLUMNS, OPEN, CURRENT, MARKET_MOVE]],
        on=list(MARKET_IDENTITY_COLUMNS),
        how="left",
        validate="one_to_one",
        sort=False,
    )
    _require(
        quote_market[[OPEN, CURRENT, MARKET_MOVE]].notna().all().all(),
        "Every governed quote must resolve to one MarketBook row",
    )
    repeated = quote_market.loc[quote_market.index.repeat(2)].reset_index(drop=True)
    legs = np.tile(np.array([0, 1], dtype=np.int64), len(catalog))
    quote_index = repeated["Quote Index"].to_numpy(dtype=np.int64)
    source_index = (
        repeated[SOURCE_TYPE]
        .map({source: index for index, source in enumerate(HISTORY_SOURCE_TYPES)})
        .to_numpy(dtype=np.int64)
    )
    underlying_index = repeated["Underlying Index"].to_numpy(dtype=np.int64)
    market_values = quote_market.loc[:, [OPEN, CURRENT, MARKET_MOVE]].to_numpy(
        dtype=float
    )
    opening = np.repeat(market_values[:, 0], 2)
    current = np.repeat(market_values[:, 1], 2)
    move = np.repeat(market_values[:, 2], 2)
    phase = ((quote_index * 13 + legs * 31) % 113) / 113.0 * 2.0 * math.pi
    sign = np.where((quote_index + legs + source_index) % 3 == 0, -1.0, 1.0)
    base = sign * (180_000.0 + ((quote_index * 9_973 + legs * 313) % 4_800_000))
    trend = 1.0 + (date_index - 130) * 0.00045
    seasonality = 1.0 + 0.055 * np.sin((date_index * 2.0 * math.pi / 34.0) + phase)
    shock = 1.0 + _temporal_shock(date_index, quote_index)
    risk = base * trend * seasonality * shock
    drisk = risk * (0.055 + 0.018 * np.cos((date_index * 2.0 * math.pi / 17.0) + phase))
    predict = risk * move * (0.2 + source_index * 0.015) + sign * (
        75.0 + ((quote_index + date_index + legs) % 211)
    )
    frame = pd.DataFrame(index=repeated.index, columns=list(RISK_HISTORY_COLUMNS))
    for column in (
        SOURCE_TYPE,
        "Risk Type",
        "Risk Greek",
        "Group",
        "Reported Underlying",
        "Underlying",
        TENOR_SWAP,
        TENOR_OPTION,
        TENOR_SWAP_ORDER,
        TENOR_OPTION_ORDER,
    ):
        frame[column] = repeated[column].to_numpy()
    frame["Split"] = "Risk"
    gamma_source = repeated[SOURCE_TYPE].isin(_DERIVED_GAMMA_SOURCE)
    sourced_gamma = gamma_source & (legs == 0)
    derived_gamma = gamma_source & (legs == 1)

    # A live Gamma connector contributes two selectable current identities:
    # its sourced Gamma/Risk rows and its developed Delta/Gamma rows.  Keep one
    # governed history position for each identity without increasing the fixed
    # 10,000-row archive grain.  Reported Underlying follows the same governed
    # mapping (with raw fallback) used by the live calculation for each row.
    reported_lookup = _reported_underlying_lookup()
    frame.loc[sourced_gamma, "Reported Underlying"] = [
        reported_lookup.get(
            (str(risk_type), str(risk_greek), str(underlying)),
            str(underlying),
        )
        for risk_type, risk_greek, underlying in frame.loc[
            sourced_gamma,
            ["Risk Type", "Risk Greek", "Underlying"],
        ].itertuples(index=False, name=None)
    ]
    frame.loc[derived_gamma, "Risk Greek"] = "Delta"
    frame.loc[derived_gamma, "Split"] = "Gamma"
    frame["Product"] = np.where(legs == 0, "XVA", "Hedges")
    book_slots = (source_index * 53 + underlying_index * 7) % 320
    portfolio_numbers = book_slots * 2 + legs
    frame["Activity"] = [_fake(f"Activity {value % 24 + 1}") for value in book_slots]
    frame["Display Bucket"] = np.where(
        np.abs(risk) >= 2_500_000.0,
        "Promoted",
        "Other",
    )
    frame["Portfolio"] = [
        _fake(f"BOOK-{number + 1:04d} · TRADER-{slot % 160 + 1:03d}")
        for number, slot in zip(portfolio_numbers, book_slots, strict=True)
    ]
    frame["SignoffGroup"] = [_fake(f"SOG-{value % 80 + 1:03d}") for value in book_slots]
    frame["Category"] = [
        _fake(f"Business {value % 18 + 1:02d}") for value in book_slots
    ]
    frame["Sub Category"] = [
        _fake(f"Strategy {(value * 7 + leg) % 42 + 1:02d}")
        for value, leg in zip(book_slots, legs, strict=True)
    ]
    frame["Portfolio Mapped"] = True
    frame["Promotion Reason"] = np.where(
        np.abs(risk) >= 2_500_000.0,
        "Risk threshold",
        "Below thresholds",
    )
    frame["Promotion Score"] = np.abs(risk) / 2_500_000.0
    frame["Risk Threshold"] = 2_500_000.0
    frame["dRisk Threshold"] = 250_000.0
    frame["PL Threshold"] = 25_000.0
    frame[RISK] = np.round(risk, 6)
    frame[DRISK] = np.round(drisk, 6)
    frame[OPEN] = opening
    frame[CURRENT] = current
    frame[PL] = np.round(predict, 6)
    frame[MARKET_MOVE] = move
    frame["Market Available"] = True
    frame["Market Data Status"] = "Available"
    for measure, factor in CREDIT_FACTORS.items():
        credit = frame["Risk Type"].eq("Credit")
        frame[f"Risk {measure}"] = np.where(credit, frame[RISK] * factor, np.nan)
        frame[f"dRisk {measure}"] = np.where(credit, frame[DRISK] * factor, np.nan)
    return validate_risk_archive_frame(frame.loc[:, list(RISK_HISTORY_COLUMNS)])


def _build_history_colossus(
    risk: pd.DataFrame,
    *,
    date_index: int,
) -> pd.DataFrame:
    predicted = (
        risk.groupby(
            list(COLOSSUS_COLUMNS[:-1]),
            as_index=False,
            sort=False,
            observed=True,
            dropna=False,
        )[PL]
        .sum(min_count=1)
        .sort_values(list(COLOSSUS_COLUMNS[:-1]), kind="stable")
        .reset_index(drop=True)
    )
    _require(
        len(predicted) > HISTORY_MATCHED_COLOSSUS_ROWS,
        "Predict aggregation must leave genuine Predict-only groups",
    )
    matched = predicted.iloc[:HISTORY_MATCHED_COLOSSUS_ROWS].copy()
    matched_index = np.arange(len(matched), dtype=np.int64)
    operational = (((matched_index * 65_537 + date_index * 257) % 4_001) - 2_000) * 0.17
    matched[PL] = (
        matched[PL].to_numpy(dtype=float)
        * (
            0.91
            + 0.025 * np.sin((date_index + matched_index % 29) * 2.0 * math.pi / 29.0)
        )
        + operational
    )
    colossus_only_count = HISTORY_COLOSSUS_ROWS - len(matched)
    authority = risk[["Portfolio", "Risk Type", "Risk Greek"]].drop_duplicates(
        "Portfolio"
    )
    authority = authority.sort_values("Portfolio", kind="stable").reset_index(drop=True)
    only_index = np.arange(colossus_only_count, dtype=np.int64)
    selected_authority = authority.iloc[only_index % len(authority)].reset_index(
        drop=True
    )
    colossus_only = pd.DataFrame(
        {
            "Portfolio": selected_authority["Portfolio"].to_numpy(),
            "Underlying": [
                _fake(f"Colossus-only adjustment {value + 1:04d}")
                for value in only_index
            ],
            "Risk Type": selected_authority["Risk Type"].to_numpy(),
            "Risk Greek": selected_authority["Risk Greek"].to_numpy(),
            PL: np.round(
                15_000.0 * np.sin((only_index + date_index) * 2.0 * math.pi / 37.0)
                + ((only_index * 313 + date_index * 19) % 7_001)
                - 3_500.0,
                6,
            ),
        },
        columns=list(COLOSSUS_COLUMNS),
    )
    matched[PL] = np.round(matched[PL], 6)
    frame = pd.concat([matched, colossus_only], ignore_index=True)
    return validate_colossus_frame(frame)


def _build_stock_history_frame(date_index: int) -> pd.DataFrame:
    stable = np.arange(4_800, dtype=np.int64)
    rotating = 4_800 + ((np.arange(200, dtype=np.int64) + date_index) % 600)
    identities = np.concatenate((stable, rotating))
    phase = (identities % 101) / 101.0 * 2.0 * math.pi
    sign = np.where(identities % 4 == 0, -1.0, 1.0)
    base_quantity = sign * (50_000.0 + (identities * 7_919) % 9_500_000)
    quantity = base_quantity * (
        1.0
        + date_index * 0.0007
        + 0.045 * np.sin((date_index * 2.0 * math.pi / 22.0) + phase)
        + _temporal_shock(date_index, identities)
    )
    price = 0.85 + ((identities * 104_729) % 15_000) / 10_000.0
    market_value = (
        quantity * price + (((identities + date_index * 37) % 2_003) - 1_001) * 11.0
    )
    instruments = tuple(
        f"{spec.risk_type} {spec.risk_greek} Position"
        for spec in PRODUCT_SPECS_BY_SOURCE_TYPE.values()
    )
    frame = pd.DataFrame(
        {
            "CRDS": [_fake(f"CRDS-{value:06d}") for value in identities],
            "CPTY": [_fake(f"CPTY-{value % 800 + 1:04d}") for value in identities],
            "Portfolio": [
                _fake(
                    f"BOOK-{value % STOCK_PORTFOLIO_COUNT + 1:04d} · "
                    f"TRADER-{(value % STOCK_PORTFOLIO_COUNT) // 2 % 160 + 1:03d}"
                )
                for value in identities
            ],
            "Instrument": [
                _fake(instruments[value % len(instruments)]) for value in identities
            ],
            "Currency": [
                _STOCK_CURRENCIES[value % len(_STOCK_CURRENCIES)]
                for value in identities
            ],
            "Quantity": np.round(quantity, 6),
            "Market Value": np.round(market_value, 6),
        },
        columns=list(STOCK_COLUMNS),
    )
    return validate_stock_frame(frame, label="annual Stock fixture")


def build_official_history_fixture(
    market_date: str,
    *,
    catalog: pd.DataFrame | None = None,
) -> OfficialHistoryFixture:
    """Build and validate exactly one realistic daily fixture in memory."""

    try:
        date_index = HISTORICAL_MARKET_DATES.index(market_date)
    except ValueError as exc:
        raise FixtureValidationError(
            f"History date is outside the governed range: {market_date}"
        ) from exc
    selected_catalog = _history_quote_catalog() if catalog is None else catalog
    market = _build_history_market(
        selected_catalog,
        market_date=market_date,
        date_index=date_index,
    )
    risk = _build_history_risk(selected_catalog, market, date_index=date_index)
    fixture = OfficialHistoryFixture(
        market_date=market_date,
        revision=date_index + 1,
        risk_dates=_history_risk_dates(market_date),
        risk=risk,
        colossus=_build_history_colossus(
            risk,
            date_index=date_index,
        ),
        market=market,
        stock=_build_stock_history_frame(date_index),
    )
    validate_official_history_fixture(fixture, date_index=date_index)
    return fixture


def iter_official_history_fixtures() -> Iterator[OfficialHistoryFixture]:
    """Yield one validated day at a time and retain only the quote catalogue."""

    catalog = _history_quote_catalog()
    for market_date in HISTORICAL_MARKET_DATES:
        yield build_official_history_fixture(market_date, catalog=catalog)


def validate_official_history_fixture(
    fixture: OfficialHistoryFixture,
    *,
    date_index: int,
) -> None:
    """Validate exact counts, grains, diversity, axes, and fake boundaries."""

    _require(
        fixture.market_date == HISTORICAL_MARKET_DATES[date_index],
        "History leaf date mismatch",
    )
    _require(fixture.revision == date_index + 1, "History revision mismatch")
    _require(
        set(fixture.risk_dates) == set(HISTORY_SOURCE_TYPES),
        "Risk Dates must exactly cover all ProductSpecs",
    )
    risk = validate_risk_archive_frame(fixture.risk)
    market = validate_market_archive_frame(
        fixture.market,
        market_date=fixture.market_date,
    )
    colossus = validate_colossus_frame(fixture.colossus)
    stock = validate_stock_frame(fixture.stock, label="annual Stock fixture")
    _require(len(risk) == HISTORY_RISK_ROWS, "Risk row count must be exactly 10,000")
    _require(
        len(market) == HISTORY_MARKET_ROWS,
        "Market row count must be exactly 5,000",
    )
    _require(
        len(colossus) == HISTORY_COLOSSUS_ROWS,
        "Colossus row count must be exactly 5,000",
    )
    _require(len(stock) == HISTORY_STOCK_ROWS, "Stock row count must be exactly 5,000")
    _require(
        set(risk[SOURCE_TYPE]) == set(HISTORY_SOURCE_TYPES)
        and set(market[SOURCE_TYPE]) == set(HISTORY_SOURCE_TYPES),
        "Annual history must cover all 16 ProductSpecs",
    )
    reported_lookup = _reported_underlying_lookup()
    for source_type in HISTORY_SOURCE_TYPES:
        identity_source = _DERIVED_GAMMA_SOURCE.get(source_type, source_type)
        spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
        displayed_greeks = (
            (spec.risk_greek, "Delta")
            if source_type in _DERIVED_GAMMA_SOURCE
            else (spec.risk_greek,)
        )
        live_underlyings = {
            _fake(value) for value in SOURCE_BY_TYPE[identity_source].underlyings
        }
        archived_market_underlyings = set(
            market.loc[market[SOURCE_TYPE].eq(source_type), "Underlying"]
        )
        _require(
            live_underlyings <= archived_market_underlyings,
            f"Annual {source_type} Market identities must include every live anchor",
        )
        expected_reported = {
            reported_lookup.get(
                (spec.risk_type, displayed_greek, underlying),
                underlying,
            )
            for displayed_greek in displayed_greeks
            for underlying in live_underlyings
        }
        archived_reported = set(
            risk.loc[risk[SOURCE_TYPE].eq(source_type), "Reported Underlying"]
        )
        _require(
            expected_reported <= archived_reported,
            f"Annual {source_type} Risk identities must include every live report",
        )
    for gamma_source, delta_source in _DERIVED_GAMMA_SOURCE.items():
        gamma_risk = risk.loc[risk[SOURCE_TYPE].eq(gamma_source)]
        sourced_gamma_risk = gamma_risk.loc[
            gamma_risk["Risk Greek"].eq("Gamma") & gamma_risk["Split"].eq("Risk")
        ]
        derived_gamma_risk = gamma_risk.loc[
            gamma_risk["Risk Greek"].eq("Delta") & gamma_risk["Split"].eq("Gamma")
        ]
        delta_risk = risk.loc[risk[SOURCE_TYPE].eq(delta_source)]
        gamma_market = market.loc[market[SOURCE_TYPE].eq(gamma_source)]
        _require(
            not sourced_gamma_risk.empty
            and not derived_gamma_risk.empty
            and len(sourced_gamma_risk) + len(derived_gamma_risk) == len(gamma_risk)
            and delta_risk["Risk Greek"].eq("Delta").all()
            and delta_risk["Split"].eq("Risk").all(),
            f"{gamma_source} history must retain Gamma/Risk and Delta/Gamma",
        )
        _require(
            gamma_market["Risk Greek"].eq("Gamma").all(),
            f"Raw {gamma_source} Market rows must retain ProductSpec Gamma",
        )
        _require(
            fixture.risk_dates[gamma_source] == fixture.risk_dates[delta_source],
            f"Derived {gamma_source} and {delta_source} must share one Risk Date",
        )
        shared_reported = set(derived_gamma_risk["Reported Underlying"]) & set(
            delta_risk["Reported Underlying"]
        )
        active_axes = [
            axis.column for axis in PRODUCT_SPECS_BY_SOURCE_TYPE[gamma_source].axes
        ]
        shared_raw_axes = set(
            derived_gamma_risk[["Underlying", *active_axes]].itertuples(
                index=False,
                name=None,
            )
        ) & set(
            delta_risk[["Underlying", *active_axes]].itertuples(
                index=False,
                name=None,
            )
        )
        _require(
            bool(shared_reported) and bool(shared_raw_axes),
            f"Derived {gamma_source} must overlap {delta_source} identities",
        )
    quote_keys = [SOURCE_TYPE, "Risk Type", "Underlying", *TENOR_COLUMNS]
    positions_per_quote = risk.groupby(quote_keys, dropna=False, observed=True).size()
    _require(
        len(positions_per_quote) == HISTORY_MARKET_ROWS
        and positions_per_quote.eq(2).all(),
        "Risk must contain exactly two governed positions per quote",
    )
    _require(
        risk["Portfolio"].nunique() == 640,
        "Risk must use the governed 640-portfolio pool",
    )
    portfolios_per_underlying = risk.groupby(
        [SOURCE_TYPE, "Underlying"],
        dropna=False,
        observed=True,
    )["Portfolio"].nunique()
    _require(
        portfolios_per_underlying.eq(2).all(),
        "Each source/underlying tenor grid must reuse one portfolio pair",
    )
    portfolio_governance = risk.groupby("Portfolio", observed=True)[
        ["Product", "Activity", "SignoffGroup", "Category", "Sub Category"]
    ].nunique()
    _require(
        portfolio_governance.eq(1).all().all(),
        "Each governed portfolio must retain one hierarchy authority",
    )
    _require(
        not stock.duplicated(list(STOCK_IDENTITY_COLUMNS)).any(),
        "Stock identities must be unique",
    )
    _require(
        stock["Portfolio"].nunique() == STOCK_PORTFOLIO_COUNT,
        "Stock must use exactly 500 governed portfolios",
    )
    _require(
        set(stock["Portfolio"]) <= set(risk["Portfolio"]),
        "Stock portfolios must reuse the governed Risk portfolio authority",
    )
    for frame, columns, label in (
        (risk, ("Portfolio", "Underlying", "Reported Underlying"), "Risk"),
        (market, ("Underlying",), "Market"),
        (colossus, ("Portfolio", "Underlying"), "Colossus"),
        (
            stock,
            tuple(column for column in STOCK_TEXT_COLUMNS if column != "Currency"),
            "Stock",
        ),
    ):
        _require(
            all(
                frame[column].str.contains(FAKE_NOTICE, regex=False).all()
                for column in columns
            ),
            f"{label} identities must retain the fake marker",
        )
    for frame, columns, label in (
        (risk, (RISK, DRISK, PL, OPEN, CURRENT, MARKET_MOVE), "Risk"),
        (market, (OPEN, CURRENT, MARKET_MOVE), "Market"),
        (colossus, (PL,), "Colossus"),
        (stock, STOCK_NUMERIC_COLUMNS, "Stock"),
    ):
        _require(
            bool(np.isfinite(frame.loc[:, list(columns)].to_numpy(dtype=float)).all()),
            f"{label} numeric values must be finite",
        )
    predict = risk.groupby(
        list(COLOSSUS_COLUMNS[:-1]),
        as_index=False,
        sort=False,
        observed=True,
        dropna=False,
    )[PL].sum(min_count=1)
    comparison = predict.merge(
        colossus,
        on=list(COLOSSUS_COLUMNS[:-1]),
        how="outer",
        validate="one_to_one",
        indicator=True,
        suffixes=(" Predict", " Colossus"),
    )
    match_counts = comparison["_merge"].value_counts()
    _require(
        len(predict) == 2_564
        and int(match_counts.get("both", 0)) == HISTORY_MATCHED_COLOSSUS_ROWS
        and int(match_counts.get("left_only", 0)) == 564
        and int(match_counts.get("right_only", 0)) == 3_000,
        "P&L fixture must retain Matched, Predict-only, and Colossus-only states",
    )
    matched = comparison.loc[comparison["_merge"].eq("both")]
    _require(
        not np.allclose(matched[f"{PL} Predict"], matched[f"{PL} Colossus"]),
        "Colossus Actual must remain distinct from Predict PL",
    )
    _require(
        {len(spec.axes) for spec in PRODUCT_SPECS_BY_SOURCE_TYPE.values()} == {0, 1, 2},
        "Annual fixture must exercise scalar, curve, and surface products",
    )


def _require_archive_schema_v4() -> None:
    _require(
        ARCHIVE_SCHEMA_VERSION == 4,
        "Annual archive generation requires live Risk archive schema v4",
    )
    _require(
        set(STOCK_ARCHIVE_FILE_NAMES)
        == {
            "risk.parquet",
            "colossus.parquet",
            "market.parquet",
            "stock.parquet",
            "_SUCCESS",
        },
        "Schema-v4 archive filenames are not stable",
    )


def _materialize_history_leaf(
    fixture: OfficialHistoryFixture,
    root: Path,
) -> Path:
    _require_archive_schema_v4()
    selected = pd.Timestamp(fixture.market_date)
    snapshot = _FixtureArchiveSnapshot(
        revision=fixture.revision,
        refreshed_at=datetime(
            selected.year,
            selected.month,
            selected.day,
            17,
            30,
            tzinfo=timezone.utc,
        ),
        system_date=selected,
        market_date=selected,
        market_status=OFFICIAL,
        risk_dates=fixture.risk_dates,
        dashboard_frame=fixture.risk,
        market_frame=fixture.market,
        stock_frame=fixture.stock,
        errors=(),
        fixture=FIXTURE_TAG,
    )
    result = archive_official_snapshot(
        snapshot,
        lambda _date: fixture.colossus,
        root,
    )
    _require(result.archived, f"Archive writer skipped {fixture.market_date}")
    marker = json.loads((result.path / "_SUCCESS").read_text(encoding="utf-8"))
    _require(
        marker.get("schema_version") == 4 and marker.get("fixture") == FIXTURE_TAG,
        "Archive writer must retain the deterministic schema-v4 fixture tag",
    )
    return result.path


def _require_direct_child(root: Path, leaf: Path) -> None:
    resolved_root = root.resolve()
    resolved_leaf = leaf.resolve()
    _require(
        resolved_leaf.parent == resolved_root
        and resolved_leaf.name in HISTORICAL_MARKET_DATES,
        f"Refusing fixture operation outside governed history root: {leaf}",
    )


def _read_leaf_marker(leaf: Path) -> dict[str, object]:
    try:
        marker = json.loads((leaf / "_SUCCESS").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FixtureValidationError(
            f"Refusing invalid fixture marker in {leaf}"
        ) from exc
    if not isinstance(marker, dict):
        raise FixtureValidationError(f"Refusing non-object fixture marker in {leaf}")
    return marker


def _recognize_replaceable_fixture_leaf(leaf: Path, market_date: str) -> None:
    _require_direct_child(RISK_ARCHIVE_DIRECTORY, leaf)
    _require(leaf.is_dir(), f"History leaf is not a directory: {leaf}")
    entries = {entry.name for entry in leaf.iterdir()}
    marker = _read_leaf_marker(leaf)
    legacy_entries = {
        "risk.csv",
        "colossus.csv",
        "market.csv",
        "stock.csv",
        "_SUCCESS",
    }
    current_entries = set(STOCK_ARCHIVE_FILE_NAMES)
    recognized = (
        entries == legacy_entries
        and marker.get("schema_version") == 3
        and marker.get("fixture") == LEGACY_FIXTURE_TAG
    ) or (
        entries == current_entries
        and marker.get("schema_version") == 4
        and marker.get("fixture") == FIXTURE_TAG
    )
    _require(
        recognized
        and marker.get("market_date") == market_date
        and marker.get("stock_date") == market_date,
        f"Refusing to replace unrecognized user/runtime history leaf {leaf}",
    )


def _preflight_history_destination() -> None:
    RISK_ARCHIVE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for market_date in HISTORICAL_MARKET_DATES:
        destination = RISK_ARCHIVE_DIRECTORY / market_date
        _require_direct_child(RISK_ARCHIVE_DIRECTORY, destination)
        for suffix in ("fixture-v4-pending", "fixture-v4-backup"):
            transaction = RISK_ARCHIVE_DIRECTORY / f".{market_date}.{suffix}"
            _require(
                not transaction.exists(),
                f"Refusing unfinished fixture transaction {transaction}",
            )
        if destination.exists():
            _recognize_replaceable_fixture_leaf(destination, market_date)


def _restore_windows_parent_acl(path: Path) -> None:
    """Make a moved leaf inherit the history root ACL before publication."""

    if sys.platform != "win32":
        return
    try:
        subprocess.run(
            ["icacls", str(path), "/reset", "/T", "/C"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise FixtureValidationError(
            f"Could not restore inherited permissions for staged history leaf {path}"
        ) from exc


def _install_history_leaf(staged: Path) -> None:
    market_date = staged.name
    destination = RISK_ARCHIVE_DIRECTORY / market_date
    _require_direct_child(RISK_ARCHIVE_DIRECTORY, destination)
    pending = RISK_ARCHIVE_DIRECTORY / f".{market_date}.fixture-v4-pending"
    backup = RISK_ARCHIVE_DIRECTORY / f".{market_date}.fixture-v4-backup"
    _require(
        not pending.exists() and not backup.exists(),
        f"Refusing unfinished fixture transaction for {market_date}",
    )
    staged.replace(pending)
    try:
        # Windows keeps the staging directory's DACL across a move. Reset the
        # still-hidden pending tree so Git, tests, and deployment inherit the
        # repository ACL as soon as the atomic destination swap completes.
        _restore_windows_parent_acl(pending)
    except BaseException:
        pending.replace(staged)
        raise
    if not destination.exists():
        pending.replace(destination)
        return
    destination.replace(backup)
    try:
        pending.replace(destination)
    except BaseException:
        backup.replace(destination)
        raise
    _require(
        backup.resolve().parent == RISK_ARCHIVE_DIRECTORY.resolve(),
        f"Refusing to remove fixture backup outside governed root: {backup}",
    )
    shutil.rmtree(backup)


def _stream_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _compare_leaf_bytes(expected: Path, actual: Path) -> None:
    _require(
        actual.is_dir(),
        f"Missing generated fixture leaf {actual}",
    )
    _require(
        {entry.name for entry in actual.iterdir()} == set(STOCK_ARCHIVE_FILE_NAMES),
        f"Generated fixture leaf has unexpected entries: {actual}",
    )
    marker = _read_leaf_marker(actual)
    _require(
        marker.get("schema_version") == 4
        and marker.get("fixture") == FIXTURE_TAG
        and marker.get("market_date") == actual.name
        and marker.get("stock_date") == actual.name,
        f"Checked-in fixture marker is not governed schema-v4: {actual}",
    )
    for file_name in STOCK_ARCHIVE_FILE_NAMES:
        _require(
            _stream_sha256(actual / file_name) == _stream_sha256(expected / file_name),
            f"Checked-in fixture differs from deterministic output: "
            f"{actual / file_name}",
        )


def _write_history_archives() -> None:
    _preflight_history_destination()
    for fixture in iter_official_history_fixtures():
        staging_root = Path(
            tempfile.mkdtemp(prefix=".rebirth-v4-stage-", dir=RISK_ARCHIVE_DIRECTORY)
        )
        try:
            staged = _materialize_history_leaf(fixture, staging_root)
            _install_history_leaf(staged)
        finally:
            if staging_root.exists():
                shutil.rmtree(staging_root)


def _check_history_archives() -> None:
    for fixture in iter_official_history_fixtures():
        with tempfile.TemporaryDirectory(prefix="rebirth-v4-check-") as temporary:
            expected = _materialize_history_leaf(fixture, Path(temporary))
            actual = RISK_ARCHIVE_DIRECTORY / fixture.market_date
            _compare_leaf_bytes(expected, actual)


def probe_representative_history_leaf() -> dict[str, int]:
    """Materialize one middle date and return compressed byte sizes."""

    market_date = HISTORICAL_MARKET_DATES[len(HISTORICAL_MARKET_DATES) // 2]
    fixture = build_official_history_fixture(market_date)
    with tempfile.TemporaryDirectory(prefix="rebirth-v4-probe-") as temporary:
        leaf = _materialize_history_leaf(fixture, Path(temporary))
        sizes = {
            file_name: (leaf / file_name).stat().st_size
            for file_name in STOCK_ARCHIVE_FILE_NAMES
        }
    sizes["projected_262_total"] = sum(sizes.values()) * len(HISTORICAL_MARKET_DATES)
    return sizes


def _write_files(datasets: Mapping[str, Sequence[Mapping[str, str]]]) -> None:
    DATA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary_paths: list[tuple[Path, Path]] = []
    try:
        for filename, schema in SCHEMAS.items():
            destination = DATA_DIRECTORY / filename
            temporary = destination.with_suffix(destination.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=schema, lineterminator="\n")
                writer.writeheader()
                writer.writerows(datasets[filename])
            temporary_paths.append((temporary, destination))
        for temporary, destination in temporary_paths:
            temporary.replace(destination)
    finally:
        for temporary, _destination in temporary_paths:
            if temporary.exists():
                temporary.unlink()


def _read_files() -> dict[str, list[dict[str, str]]]:
    datasets: dict[str, list[dict[str, str]]] = {}
    for filename, schema in SCHEMAS.items():
        path = DATA_DIRECTORY / filename
        if not path.is_file():
            raise FixtureValidationError(f"Missing generated fixture {path}")
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if tuple(reader.fieldnames or ()) != schema:
                raise FixtureValidationError(
                    f"{filename} has columns {reader.fieldnames}; expected {list(schema)}"
                )
            datasets[filename] = [dict(row) for row in reader]
    return datasets


def _print_report(
    datasets: Mapping[str, Sequence[Mapping[str, str]]],
    *,
    checked_only: bool,
) -> None:
    action = "Checked" if checked_only else "Generated and checked"
    print(f"{action} {len(datasets)} deterministic FAKE_ONLY connector CSVs.")
    for filename in SCHEMAS:
        path = DATA_DIRECTORY / filename
        digest = _stream_sha256(path)[:12]
        print(f"  {filename}: {len(datasets[filename])} rows, sha256={digest}")
    for market_date in (HISTORICAL_MARKET_DATES[0], HISTORICAL_MARKET_DATES[-1]):
        path = RISK_ARCHIVE_DIRECTORY / market_date / "_SUCCESS"
        digest = _stream_sha256(path)[:12]
        print(
            f"  histo/{market_date}/_SUCCESS: "
            f"risk={HISTORY_RISK_ROWS}, market={HISTORY_MARKET_ROWS}, "
            f"colossus={HISTORY_COLOSSUS_ROWS}, stock={HISTORY_STOCK_ROWS}, "
            f"sha256={digest}"
        )
    risk_rows = datasets["s03_risk.csv"]
    market_rows = datasets["s04_open.csv"]
    credit_rows = [row for row in risk_rows if row["Source Type"].startswith("credit/")]
    print(
        "Validation: "
        f"sources={len(EXPECTED_SOURCE_TYPES)}, "
        f"risk_rows={len(risk_rows)}, "
        f"full_market_keys={len(market_rows)}, "
        f"credit_rows_with_complete_measures={len(credit_rows)}, "
        f"history_dates={len(HISTORICAL_MARKET_DATES)}, "
        f"fixture={FIXTURE_TAG}."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check",
        action="store_true",
        help="Validate checked-in fixtures against exact deterministic generation.",
    )
    mode.add_argument(
        "--probe-size",
        action="store_true",
        help="Write one representative temp leaf and report projected annual size.",
    )
    args = parser.parse_args()

    _require_archive_schema_v4()
    _validate_history_date_range(HISTORICAL_MARKET_DATES)
    if args.probe_size:
        sizes = probe_representative_history_leaf()
        for file_name in STOCK_ARCHIVE_FILE_NAMES:
            print(f"  {file_name}: {sizes[file_name]:,} bytes")
        print(
            "  representative total: "
            f"{sum(sizes[name] for name in STOCK_ARCHIVE_FILE_NAMES):,} bytes"
        )
        print(
            "  projected 262-day total: "
            f"{sizes['projected_262_total']:,} bytes "
            f"({sizes['projected_262_total'] / (1024 * 1024):.2f} MiB)"
        )
        return 0

    expected = build_datasets()
    validate_datasets(expected)
    if not args.check:
        _write_files(expected)
        _write_history_archives()
    actual = _read_files()
    validate_datasets(actual)
    if actual != expected:
        raise FixtureValidationError(
            "Checked-in fixtures differ from deterministic output; rerun the generator."
        )
    _check_history_archives()
    _print_report(actual, checked_only=args.check)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
