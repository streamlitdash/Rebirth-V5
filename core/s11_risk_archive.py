"""Flat, atomic archives for one official Risk Explorer snapshot per date.

The archive deliberately stores the committed dashboard frame without turning
it into a hierarchy.  A reader can rebuild the Risk Explorer hierarchy at
display time.  Colossus P&L is stored at its separate, explicit four-key grain;
it is never copied across tenor or Product rows. Canonical schema-v4 leaves use
compressed Parquet; schema-v1/v2/v3 CSV leaves remain fully readable.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from core.s01_schema import (
    TENOR_OPTION,
    TENOR_OPTION_ORDER,
    TENOR_SWAP,
    TENOR_SWAP_ORDER,
    UNMAPPED_VALUE,
)
from core.s02_pipeline import PRODUCT_SPECS_BY_SOURCE_TYPE, market_date_for
from core.s03_search import (
    CURRENT,
    MARKET_DATA_STATUS,
    MARKET_RESULT_COLUMNS,
    MARKET_STATUS,
    OPEN,
    REPORTED_UNDERLYING,
    SOURCE_TYPE,
)
from core.s04_pl import (
    ACTIVITY,
    CATEGORY,
    COLOSSUS_TYPE,
    HISTORY_MAPPING_STATUS,
    HISTORY_TYPE,
    MARKET_DATE,
    PL,
    PL_HISTORY_COLUMNS,
    PL_HISTORY_KEY,
    PREDICT_TYPE,
    PRODUCT,
    PLSendValidationError,
    RISK_GREEK,
    RISK_TYPE,
    SIGNOFF_GROUP,
    SUB_CATEGORY,
    UNDERLYING,
    load_legacy_pl_history_leaf,
    validate_pl_history_frame,
)
from core.s07_stock import (
    STOCK_COLUMNS,
    STOCK_IDENTITY_COLUMNS,
    validate_stock_frame,
)


PORTFOLIO = "Portfolio"
RISK = "Risk"
DRISK = "dRisk"
OFFICIAL = "OFFICIAL"
RISK_FILE_NAME = "risk.parquet"
COLOSSUS_FILE_NAME = "colossus.parquet"
MARKET_FILE_NAME = "market.parquet"
STOCK_FILE_NAME = "stock.parquet"
SUCCESS_FILE_NAME = "_SUCCESS"
BASE_ARCHIVE_FILE_NAMES = (RISK_FILE_NAME, COLOSSUS_FILE_NAME, SUCCESS_FILE_NAME)
ARCHIVE_FILE_NAMES = (
    RISK_FILE_NAME,
    COLOSSUS_FILE_NAME,
    MARKET_FILE_NAME,
    SUCCESS_FILE_NAME,
)
STOCK_ARCHIVE_FILE_NAMES = (
    RISK_FILE_NAME,
    COLOSSUS_FILE_NAME,
    MARKET_FILE_NAME,
    STOCK_FILE_NAME,
    SUCCESS_FILE_NAME,
)
_CSV_RISK_FILE_NAME = "risk.csv"
_CSV_COLOSSUS_FILE_NAME = "colossus.csv"
_CSV_MARKET_FILE_NAME = "market.csv"
_CSV_STOCK_FILE_NAME = "stock.csv"
_V1_ARCHIVE_FILE_NAMES = (
    _CSV_RISK_FILE_NAME,
    _CSV_COLOSSUS_FILE_NAME,
    SUCCESS_FILE_NAME,
)
_V2_ARCHIVE_FILE_NAMES = (
    _CSV_RISK_FILE_NAME,
    _CSV_COLOSSUS_FILE_NAME,
    _CSV_MARKET_FILE_NAME,
    SUCCESS_FILE_NAME,
)
_V3_STOCK_ARCHIVE_FILE_NAMES = (
    _CSV_RISK_FILE_NAME,
    _CSV_COLOSSUS_FILE_NAME,
    _CSV_MARKET_FILE_NAME,
    _CSV_STOCK_FILE_NAME,
    SUCCESS_FILE_NAME,
)
ALL_ARCHIVE_FILE_NAMES = tuple(
    dict.fromkeys((*_V3_STOCK_ARCHIVE_FILE_NAMES, *STOCK_ARCHIVE_FILE_NAMES))
)
COLOSSUS_COLUMNS = (PORTFOLIO, UNDERLYING, RISK_TYPE, RISK_GREEK, PL)
COLOSSUS_KEY = COLOSSUS_COLUMNS[:-1]
RISK_PROJECTION_COLUMNS = (
    PORTFOLIO,
    UNDERLYING,
    RISK_TYPE,
    RISK_GREEK,
    PRODUCT,
    RISK,
    DRISK,
    PL,
)
MARKET_ARCHIVE_COLUMNS = tuple(MARKET_RESULT_COLUMNS)
MARKET_IDENTITY_COLUMNS = (
    SOURCE_TYPE,
    RISK_TYPE,
    RISK_GREEK,
    UNDERLYING,
    TENOR_SWAP,
    TENOR_OPTION,
)
MARKET_HISTORY_COLUMNS = (
    MARKET_DATE,
    TENOR_SWAP,
    TENOR_OPTION,
    TENOR_SWAP_ORDER,
    TENOR_OPTION_ORDER,
    CURRENT,
)
SNAPSHOT_DATE = "Snapshot Date"
REVISION = "Revision"
RISK_DATE = "Risk Date"
MAPPING_STATUS = "Mapping Status"
RISK_HISTORY_METADATA_COLUMNS = (
    SNAPSHOT_DATE,
    REVISION,
    RISK_DATE,
    MAPPING_STATUS,
)
PORTFOLIO_AUTHORITY_COLUMNS = (
    PORTFOLIO,
    SIGNOFF_GROUP,
    PRODUCT,
    ACTIVITY,
    CATEGORY,
    SUB_CATEGORY,
    HISTORY_MAPPING_STATUS,
)
MAPPED_HISTORY_VALUE = "Mapped"
ARCHIVE_SCHEMA_VERSION = 4
_SUPPORTED_ARCHIVE_SCHEMA_VERSIONS = frozenset((1, 2, 3, ARCHIVE_SCHEMA_VERSION))
_MARKET_SCHEMA_VERSIONS = frozenset((2, 3, ARCHIVE_SCHEMA_VERSION))
_VERSIONED_METADATA_SCHEMA_VERSIONS = frozenset((3, ARCHIVE_SCHEMA_VERSION))
_STOCK_SCHEMA_VERSIONS = frozenset((3, ARCHIVE_SCHEMA_VERSION))
_V3_FIXTURE_TAG = "deterministic-rebirth-v3"
_V4_FIXTURE_TAG = "deterministic-rebirth-v4"
_PARQUET_COMPRESSION = "zstd"
_PARQUET_COMPRESSION_LEVEL = 9
_PARQUET_ROW_GROUP_SIZE = 2_048

_DATE_PATTERN = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])")
_PENDING_LEAF_PATTERN = re.compile(
    r"\.\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\.pending-.+"
)
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_LEGACY_HISTORY_FILE_NAMES = frozenset(("histo.csv", "predicted.csv"))
_OFFICIAL_HISTORY_FILE_NAMES = frozenset(
    (
        _CSV_RISK_FILE_NAME,
        _CSV_COLOSSUS_FILE_NAME,
        _CSV_STOCK_FILE_NAME,
        RISK_FILE_NAME,
        COLOSSUS_FILE_NAME,
        MARKET_FILE_NAME,
        STOCK_FILE_NAME,
        SUCCESS_FILE_NAME,
    )
)


def _uses_parquet(schema_version: int) -> bool:
    return schema_version == ARCHIVE_SCHEMA_VERSION


def _archive_file_name(schema_version: int, domain: str) -> str:
    names = {
        "risk": RISK_FILE_NAME
        if _uses_parquet(schema_version)
        else _CSV_RISK_FILE_NAME,
        "colossus": (
            COLOSSUS_FILE_NAME
            if _uses_parquet(schema_version)
            else _CSV_COLOSSUS_FILE_NAME
        ),
        "market": (
            MARKET_FILE_NAME if _uses_parquet(schema_version) else _CSV_MARKET_FILE_NAME
        ),
        "stock": (
            STOCK_FILE_NAME if _uses_parquet(schema_version) else _CSV_STOCK_FILE_NAME
        ),
    }
    try:
        return names[domain]
    except KeyError as exc:  # pragma: no cover - internal invariant
        raise AssertionError(f"unknown archive domain {domain!r}") from exc


def _archive_file_names(schema_version: int, *, has_stock: bool) -> tuple[str, ...]:
    if schema_version == 1:
        return _V1_ARCHIVE_FILE_NAMES
    if schema_version == 2:
        return _V2_ARCHIVE_FILE_NAMES
    if schema_version == 3:
        return _V3_STOCK_ARCHIVE_FILE_NAMES if has_stock else _V2_ARCHIVE_FILE_NAMES
    if schema_version == ARCHIVE_SCHEMA_VERSION:
        return STOCK_ARCHIVE_FILE_NAMES if has_stock else ARCHIVE_FILE_NAMES
    raise AssertionError(f"unsupported archive schema version {schema_version}")


class RiskArchiveValidationError(ValueError):
    """Raised when an archive request or completed leaf is not trustworthy."""


class OfficialSnapshot(Protocol):
    """The committed manager fields required by the archive boundary."""

    revision: int
    refreshed_at: datetime
    system_date: pd.Timestamp
    market_date: pd.Timestamp
    market_status: str
    dashboard_frame: pd.DataFrame
    market_frame: pd.DataFrame
    risk_dates: Mapping[str, pd.Timestamp]
    errors: tuple[str, ...]


ColossusLoader = Callable[[pd.Timestamp], pd.DataFrame]


@dataclass(frozen=True)
class RiskArchive:
    """One validated, completed daily archive."""

    market_date: str
    path: Path
    risk: pd.DataFrame
    colossus: pd.DataFrame
    market: pd.DataFrame | None = None
    schema_version: int = 1
    revision: int | None = None
    risk_dates: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    stock_rows: int = 0


@dataclass(frozen=True)
class CompletedArchiveDay:
    """Validated schema-v4 paths and manifest metadata for one immutable day."""

    snapshot_date: str
    revision: int
    risk_dates: Mapping[str, str]
    path: Path
    risk_path: Path
    colossus_path: Path
    market_path: Path
    stock_path: Path | None
    stock_date: str | None
    risk_rows: int
    colossus_rows: int
    market_rows: int
    stock_rows: int


@dataclass(frozen=True)
class ArchiveResult:
    """Small scheduler-friendly outcome that does not include archived frames."""

    status: str
    reason: str
    market_date: str
    path: Path
    risk_rows: int = 0
    colossus_rows: int = 0
    market_rows: int = 0
    stock_rows: int = 0

    @property
    def archived(self) -> bool:
        return self.status == "archived"


def _normalize_date(value: object, *, label: str) -> str:
    if value is None or isinstance(value, (bool, np.bool_)):
        raise RiskArchiveValidationError(f"{label} must be a valid date")
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise RiskArchiveValidationError(f"{label} must be a valid date") from exc
    if pd.isna(timestamp):
        raise RiskArchiveValidationError(f"{label} must be a valid date")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.date().isoformat()


def _strict_iso_date(value: object, *, label: str) -> str:
    """Return an exact ``YYYY-MM-DD`` string without permissive coercion."""

    if not isinstance(value, str) or not _DATE_PATTERN.fullmatch(value):
        raise RiskArchiveValidationError(f"{label} must be an ISO YYYY-MM-DD date")
    try:
        normalized = datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise RiskArchiveValidationError(
            f"{label} must be an ISO YYYY-MM-DD date"
        ) from exc
    if normalized != value:
        raise RiskArchiveValidationError(f"{label} must be an ISO YYYY-MM-DD date")
    return value


def _strict_revision(value: object, *, label: str = "Revision") -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise RiskArchiveValidationError(f"{label} must be a non-negative integer")
    revision = int(value)
    if revision < 0:
        raise RiskArchiveValidationError(f"{label} must be a non-negative integer")
    return revision


def _source_types_in_risk(risk: pd.DataFrame) -> tuple[str, ...]:
    if SOURCE_TYPE not in risk:
        raise RiskArchiveValidationError(
            "versioned Risk archive must contain 'Source Type'"
        )
    normalized = _validate_text_columns(
        risk,
        (SOURCE_TYPE,),
        label="versioned Risk archive",
    )
    return tuple(sorted(normalized[SOURCE_TYPE].drop_duplicates().tolist()))


def _snapshot_versioned_metadata(
    snapshot: OfficialSnapshot,
    risk: pd.DataFrame,
) -> tuple[int, dict[str, str]]:
    revision = _strict_revision(getattr(snapshot, "revision", None))
    raw_risk_dates = getattr(snapshot, "risk_dates", None)
    if not isinstance(raw_risk_dates, Mapping):
        raise RiskArchiveValidationError(
            "versioned Risk archive risk_dates must be a mapping"
        )
    source_types = _source_types_in_risk(risk)
    if any(
        not isinstance(key, str) or not key.strip() or key != key.strip()
        for key in raw_risk_dates
    ):
        raise RiskArchiveValidationError(
            "versioned Risk archive risk_dates keys must be nonblank text"
        )
    normalized_keys = {str(key).strip() for key in raw_risk_dates}
    if normalized_keys != set(source_types) or len(normalized_keys) != len(
        raw_risk_dates
    ):
        raise RiskArchiveValidationError(
            "versioned Risk archive risk_dates must be keyed exactly by "
            f"the Risk Source Type values; expected={list(source_types)}, "
            f"found={sorted(normalized_keys)}"
        )
    risk_dates = {
        source_type: _normalize_date(
            raw_risk_dates[source_type],
            label=f"Risk Date for {source_type!r}",
        )
        for source_type in source_types
    }
    return revision, risk_dates


def _manifest_versioned_metadata(
    manifest: Mapping[str, object],
    *,
    leaf: Path,
) -> tuple[int, dict[str, str]]:
    revision = _strict_revision(
        manifest.get("revision"),
        label=f"Risk archive Revision in {leaf}",
    )
    raw_risk_dates = manifest.get("risk_dates")
    if not isinstance(raw_risk_dates, dict) or not raw_risk_dates:
        raise RiskArchiveValidationError(
            f"Risk archive risk_dates are missing or invalid in {leaf}"
        )
    risk_dates: dict[str, str] = {}
    for source_type, risk_date in raw_risk_dates.items():
        if not isinstance(source_type, str) or not source_type.strip():
            raise RiskArchiveValidationError(
                f"Risk archive risk_dates keys are invalid in {leaf}"
            )
        normalized_source = source_type.strip()
        if normalized_source != source_type or normalized_source in risk_dates:
            raise RiskArchiveValidationError(
                f"Risk archive risk_dates keys are invalid in {leaf}"
            )
        risk_dates[normalized_source] = _strict_iso_date(
            risk_date,
            label=f"Risk Date for {source_type!r} in {leaf}",
        )
    return revision, risk_dates


def archive_leaf_path(root: str | Path, market_date: object) -> Path:
    """Return the authoritative flat ``YYYY-MM-DD`` leaf for one market date."""

    normalized = _normalize_date(market_date, label="Market Date")
    return Path(root).expanduser().resolve() / normalized


def _require_frame(value: object, *, label: str) -> pd.DataFrame:
    if not isinstance(value, pd.DataFrame):
        raise TypeError(f"{label} must return a pandas DataFrame")
    frame = value.copy(deep=True)
    duplicate_columns = frame.columns[frame.columns.duplicated()].tolist()
    if duplicate_columns:
        raise RiskArchiveValidationError(
            f"{label} contains duplicate columns: {duplicate_columns}"
        )
    if any(not isinstance(column, str) or not column.strip() for column in frame):
        raise RiskArchiveValidationError(
            f"{label} columns must be nonblank text labels"
        )
    return frame


def _validate_text_columns(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    *,
    label: str,
) -> pd.DataFrame:
    result = frame.copy(deep=True)
    for column in columns:
        values = result[column]
        is_text = values.map(lambda value: isinstance(value, str)).astype(bool)
        invalid = values.isna() | ~is_text | values.astype("string").str.strip().eq("")
        if invalid.any():
            rows = result.index[invalid].tolist()[:5]
            raise RiskArchiveValidationError(
                f"{label} column {column!r} must contain nonblank text; "
                f"invalid rows {rows}"
            )
        result[column] = values.astype(str).str.strip()
    return result


def _nullable_numeric(
    values: pd.Series,
    *,
    label: str,
    allow_missing: bool,
) -> pd.Series:
    boolean = values.map(lambda value: isinstance(value, (bool, np.bool_)))
    blank = values.isna() | values.astype("string").str.strip().eq("")
    numeric = pd.to_numeric(values, errors="coerce")
    invalid = boolean | (~blank & numeric.isna())
    if not allow_missing:
        invalid |= blank | numeric.isna()
    invalid |= numeric.notna() & ~np.isfinite(numeric)
    if invalid.any():
        rows = values.index[invalid].tolist()[:5]
        qualifier = (
            "finite numbers or missing values" if allow_missing else "finite numbers"
        )
        raise RiskArchiveValidationError(
            f"{label} must contain {qualifier}; invalid rows {rows}"
        )
    return numeric.astype(float)


def validate_risk_archive_frame(value: object) -> pd.DataFrame:
    """Validate the minimum identities needed to retain and project Predict P&L."""

    frame = _require_frame(value, label="official Risk Explorer snapshot")
    if frame.empty:
        raise RiskArchiveValidationError(
            "official Risk Explorer snapshot must contain at least one row"
        )
    missing = [column for column in RISK_PROJECTION_COLUMNS if column not in frame]
    if missing:
        raise RiskArchiveValidationError(
            f"official Risk Explorer snapshot is missing required columns: {missing}"
        )
    normalized = _validate_text_columns(
        frame,
        (PORTFOLIO, UNDERLYING, RISK_TYPE, RISK_GREEK, PRODUCT),
        label="official Risk Explorer snapshot",
    )
    identity_columns = (PORTFOLIO, UNDERLYING, RISK_TYPE, RISK_GREEK, PRODUCT)
    frame.loc[:, list(identity_columns)] = normalized.loc[:, list(identity_columns)]
    frame[PL] = _nullable_numeric(
        frame[PL],
        label="official Risk Explorer snapshot column 'PL'",
        allow_missing=True,
    )
    frame[RISK] = _nullable_numeric(
        frame[RISK],
        label="official Risk Explorer snapshot column 'Risk'",
        allow_missing=False,
    )
    frame[DRISK] = _nullable_numeric(
        frame[DRISK],
        label="official Risk Explorer snapshot column 'dRisk'",
        allow_missing=True,
    )
    return frame


def validate_colossus_frame(value: object) -> pd.DataFrame:
    """Return strict Colossus P&L at Portfolio/Underlying/Risk pair grain."""

    frame = _require_frame(value, label="Colossus loader")
    actual = tuple(frame.columns)
    if actual != COLOSSUS_COLUMNS:
        raise RiskArchiveValidationError(
            "Colossus loader must return exactly these columns in order: "
            f"{list(COLOSSUS_COLUMNS)}; found {list(actual)}"
        )
    if frame.empty:
        raise RiskArchiveValidationError(
            "Colossus loader must return at least one official P&L row"
        )
    frame = _validate_text_columns(
        frame,
        COLOSSUS_KEY,
        label="Colossus loader",
    )
    frame[PL] = _nullable_numeric(
        frame[PL],
        label="Colossus loader column 'PL'",
        allow_missing=False,
    )
    duplicates = frame.duplicated(list(COLOSSUS_KEY), keep=False)
    if duplicates.any():
        keys = (
            frame.loc[duplicates, list(COLOSSUS_KEY)]
            .drop_duplicates()
            .to_dict("records")
        )
        raise RiskArchiveValidationError(
            f"Colossus loader contains duplicate four-key rows: {keys}"
        )
    return frame.sort_values(list(COLOSSUS_KEY), kind="stable").reset_index(drop=True)


def _market_order_column(
    values: pd.Series,
    *,
    label: str,
) -> pd.Series:
    """Return nullable, non-negative integer connector-owned ranks."""

    boolean = values.map(lambda value: isinstance(value, (bool, np.bool_)))
    blank = values.isna() | values.astype("string").str.strip().eq("")
    numeric = pd.to_numeric(values, errors="coerce")
    invalid = boolean | (~blank & numeric.isna())
    invalid |= numeric.notna() & (
        ~np.isfinite(numeric) | numeric.lt(0) | numeric.mod(1).ne(0)
    )
    if invalid.any():
        rows = values.index[invalid].tolist()[:5]
        raise RiskArchiveValidationError(
            f"{label} must contain non-negative integer market orders or missing "
            f"values; invalid rows {rows}"
        )
    return numeric.astype("Int64")


def validate_market_archive_frame(
    value: object,
    *,
    market_date: object | None = None,
) -> pd.DataFrame:
    """Validate and canonicalize one daily full MarketBook archive.

    The persisted schema deliberately mirrors ``MARKET_RESULT_COLUMNS`` used by
    current Quick Market.  Input snapshots may contain additional manager-only
    fields, but the returned frame is always the exact closed archive schema at
    unique raw quote grain.  Portfolio and reporting fields are never accepted
    into the persisted projection.
    """

    frame = _require_frame(value, label="official MarketBook snapshot")
    if frame.empty:
        raise RiskArchiveValidationError(
            "official MarketBook snapshot must contain at least one quote"
        )
    missing = [column for column in MARKET_ARCHIVE_COLUMNS if column not in frame]
    if missing:
        raise RiskArchiveValidationError(
            f"official MarketBook snapshot is missing required columns: {missing}"
        )
    frame = frame.loc[:, list(MARKET_ARCHIVE_COLUMNS)].copy()
    frame = _validate_text_columns(
        frame,
        (
            SOURCE_TYPE,
            RISK_TYPE,
            RISK_GREEK,
            UNDERLYING,
            TENOR_SWAP,
            TENOR_OPTION,
            MARKET_STATUS,
            MARKET_DATA_STATUS,
        ),
        label="official MarketBook snapshot",
    )

    normalized_dates: list[str] = []
    for row, value_date in frame[MARKET_DATE].items():
        try:
            normalized_dates.append(
                _normalize_date(value_date, label=f"Market Date at row {row}")
            )
        except RiskArchiveValidationError as exc:
            raise RiskArchiveValidationError(
                f"official MarketBook snapshot contains an invalid Market Date: {exc}"
            ) from exc
    frame[MARKET_DATE] = normalized_dates
    expected_date = (
        _normalize_date(market_date, label="Market Date")
        if market_date is not None
        else None
    )
    unique_dates = frame[MARKET_DATE].drop_duplicates().tolist()
    if len(unique_dates) != 1:
        raise RiskArchiveValidationError(
            "official MarketBook snapshot must contain exactly one Market Date; "
            f"found {unique_dates}"
        )
    if expected_date is not None and unique_dates != [expected_date]:
        raise RiskArchiveValidationError(
            "official MarketBook snapshot Market Date does not match its archive "
            f"leaf: expected {expected_date}, found {unique_dates[0]}"
        )
    if not frame[MARKET_STATUS].eq(OFFICIAL).all():
        statuses = sorted(frame[MARKET_STATUS].drop_duplicates().tolist())
        raise RiskArchiveValidationError(
            "official MarketBook snapshot Market Status must be exactly "
            f"{OFFICIAL!r}; found {statuses}"
        )

    for column in (OPEN, CURRENT, "Move"):
        frame[column] = _nullable_numeric(
            frame[column],
            label=f"official MarketBook snapshot column {column!r}",
            allow_missing=True,
        )
    for column in (TENOR_SWAP_ORDER, TENOR_OPTION_ORDER):
        frame[column] = _market_order_column(
            frame[column],
            label=f"official MarketBook snapshot column {column!r}",
        )

    complete = frame[OPEN].notna() & frame[CURRENT].notna()
    inconsistent_availability = frame["Move"].notna().ne(complete)
    if inconsistent_availability.any():
        rows = frame.index[inconsistent_availability].tolist()[:5]
        raise RiskArchiveValidationError(
            "official MarketBook snapshot Move must be present exactly when Open "
            f"and Current are both present; invalid rows {rows}"
        )
    if complete.any():
        expected_move = frame.loc[complete, CURRENT] - frame.loc[complete, OPEN]
        inconsistent_move = ~np.isclose(
            frame.loc[complete, "Move"],
            expected_move,
            rtol=1e-10,
            atol=1e-12,
        )
        if inconsistent_move.any():
            rows = expected_move.index[inconsistent_move].tolist()[:5]
            raise RiskArchiveValidationError(
                "official MarketBook snapshot Move must equal Current minus Open; "
                f"invalid rows {rows}"
            )

    for source_type, source_rows in frame.groupby(
        SOURCE_TYPE, sort=False, observed=True, dropna=False
    ):
        try:
            spec = PRODUCT_SPECS_BY_SOURCE_TYPE[str(source_type)]
        except KeyError as exc:
            raise RiskArchiveValidationError(
                f"official MarketBook snapshot contains unknown Source Type "
                f"{source_type!r}"
            ) from exc
        wrong_pair = source_rows[RISK_TYPE].ne(spec.risk_type) | source_rows[
            RISK_GREEK
        ].ne(spec.risk_greek)
        if wrong_pair.any():
            rows = source_rows.index[wrong_pair].tolist()[:5]
            raise RiskArchiveValidationError(
                f"official MarketBook Source Type {source_type!r} must use Risk "
                f"Type={spec.risk_type!r}, Risk Greek={spec.risk_greek!r}; "
                f"invalid rows {rows}"
            )

        declared_axes = set(spec.tenor_columns)
        for tenor_column, order_column in (
            (TENOR_SWAP, TENOR_SWAP_ORDER),
            (TENOR_OPTION, TENOR_OPTION_ORDER),
        ):
            if tenor_column not in declared_axes:
                expected_tenor = (
                    "Spot"
                    if spec.key == "fxdelta" and tenor_column == TENOR_SWAP
                    else "N/A"
                )
                invalid_tenor = source_rows[tenor_column].ne(expected_tenor)
                invalid_order = source_rows[order_column].notna()
                invalid = invalid_tenor | invalid_order
                if invalid.any():
                    rows = source_rows.index[invalid].tolist()[:5]
                    raise RiskArchiveValidationError(
                        f"official MarketBook Source Type {source_type!r} does not "
                        f"declare {tenor_column!r}; expected {expected_tenor!r} and "
                        f"a missing {order_column!r} at rows {rows}"
                    )
                continue

            missing_order = source_rows[order_column].isna()
            if missing_order.any():
                rows = source_rows.index[missing_order].tolist()[:5]
                raise RiskArchiveValidationError(
                    f"official MarketBook Source Type {source_type!r} requires "
                    f"{order_column!r} at rows {rows}"
                )
            tenor_to_order = source_rows.groupby(
                [UNDERLYING, tenor_column], dropna=False, observed=True
            )[order_column].nunique(dropna=False)
            if tenor_to_order.gt(1).any():
                raise RiskArchiveValidationError(
                    f"official MarketBook has conflicting {order_column!r} values "
                    f"per Source Type + Underlying + {tenor_column}"
                )
            order_to_tenor = source_rows.groupby(
                [UNDERLYING, order_column], dropna=False, observed=True
            )[tenor_column].nunique(dropna=False)
            if order_to_tenor.gt(1).any():
                raise RiskArchiveValidationError(
                    f"official MarketBook maps more than one {tenor_column!r} to "
                    f"the same {order_column!r} per Source Type + Underlying"
                )

    duplicates = frame.duplicated(list(MARKET_IDENTITY_COLUMNS), keep=False)
    if duplicates.any():
        keys = (
            frame.loc[duplicates, list(MARKET_IDENTITY_COLUMNS)]
            .drop_duplicates()
            .to_dict("records")
        )
        raise RiskArchiveValidationError(
            f"official MarketBook snapshot contains duplicate quote identities: {keys}"
        )

    return frame.sort_values(
        [
            SOURCE_TYPE,
            UNDERLYING,
            TENOR_SWAP_ORDER,
            TENOR_OPTION_ORDER,
            TENOR_SWAP,
            TENOR_OPTION,
        ],
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)


def validate_stock_archive_frame(value: object) -> pd.DataFrame:
    """Validate one optional daily Stock extension at exact source identity."""

    try:
        frame = validate_stock_frame(value, label="official Stock snapshot")
    except (TypeError, ValueError) as exc:
        raise RiskArchiveValidationError(str(exc)) from exc
    if frame.empty:
        raise RiskArchiveValidationError(
            "official Stock snapshot must contain at least one row"
        )
    duplicates = frame.duplicated(list(STOCK_IDENTITY_COLUMNS), keep=False)
    if duplicates.any():
        keys = (
            frame.loc[duplicates, list(STOCK_IDENTITY_COLUMNS)]
            .drop_duplicates()
            .head(5)
            .to_dict("records")
        )
        raise RiskArchiveValidationError(
            f"official Stock snapshot contains duplicate Stock identities: {keys}"
        )
    return frame.sort_values(
        list(STOCK_IDENTITY_COLUMNS),
        kind="stable",
    ).reset_index(drop=True)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        frame.to_csv(stream, index=False, lineterminator="\n")
        stream.flush()
        os.fsync(stream.fileno())


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    table = pa.Table.from_pandas(frame, preserve_index=False).replace_schema_metadata()
    pq.write_table(
        table,
        path,
        compression=_PARQUET_COMPRESSION,
        compression_level=_PARQUET_COMPRESSION_LEVEL,
        use_dictionary=True,
        write_statistics=True,
        version="2.6",
        data_page_version="2.0",
        row_group_size=_PARQUET_ROW_GROUP_SIZE,
    )
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _write_archive_frame(
    frame: pd.DataFrame,
    path: Path,
    *,
    schema_version: int,
) -> None:
    if _uses_parquet(schema_version):
        _write_parquet(frame, path)
    else:
        _write_csv(frame, path)


def _validate_parquet_contract(
    path: Path,
    *,
    expected_columns: list[str],
    expected_rows: int,
) -> None:
    try:
        parquet = pq.ParquetFile(path)
    except (OSError, pa.ArrowException) as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect completed Parquet archive {path}: {exc}"
        ) from exc
    if parquet.schema_arrow.names != expected_columns:
        raise RiskArchiveValidationError(
            f"Parquet archive columns do not match its completion marker: {path}"
        )
    if parquet.metadata.num_rows != expected_rows:
        raise RiskArchiveValidationError(
            f"Parquet archive row count does not match its completion marker: {path}"
        )


def _read_archive_frame(
    path: Path,
    *,
    schema_version: int,
    columns: list[str] | None = None,
    filters: list[tuple[str, str, object]] | None = None,
) -> pd.DataFrame:
    try:
        if _uses_parquet(schema_version):
            return pq.read_table(
                path,
                columns=columns,
                filters=filters or None,
            ).to_pandas()
        frame = pd.read_csv(
            path,
            encoding="utf-8",
            keep_default_na=False,
            dtype="string",
            usecols=columns,
        )
    except (OSError, UnicodeError, pd.errors.ParserError, pa.ArrowException) as exc:
        raise RiskArchiveValidationError(
            f"Could not read completed archive frame {path}: {exc}"
        ) from exc
    if filters:
        for column, operator, value in filters:
            if operator != "==":  # pragma: no cover - internal invariant
                raise AssertionError(f"unsupported archive filter {operator!r}")
            frame = frame.loc[frame[column].eq(value)]
    return frame.reset_index(drop=True)


def _write_json(value: dict[str, object], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(leaf: Path) -> dict[str, object]:
    marker = leaf / SUCCESS_FILE_NAME
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RiskArchiveValidationError(
            f"Could not read completed archive marker {marker}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise RiskArchiveValidationError(
            f"Completed archive marker {marker} must contain a JSON object"
        )
    return value


def _completed_leaf_date(leaf: Path) -> str:
    value = leaf.name
    if not _DATE_PATTERN.fullmatch(value):
        raise RiskArchiveValidationError(
            f"Risk archive leaf must use YYYY-MM-DD; found {value!r}"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except ValueError as exc:
        raise RiskArchiveValidationError(
            f"Risk archive leaf is not a valid date: {value}"
        ) from exc


def _completed_leaf_contract(
    leaf: Path,
    manifest: dict[str, object],
    market_date: str,
) -> tuple[str, ...]:
    """Validate completion metadata and return its exact expected file set."""

    schema_version = manifest.get("schema_version")
    if (
        isinstance(schema_version, (bool, np.bool_))
        or not isinstance(schema_version, (int, np.integer))
        or int(schema_version) not in _SUPPORTED_ARCHIVE_SCHEMA_VERSIONS
    ):
        raise RiskArchiveValidationError(
            f"Risk archive leaf {leaf} has an unsupported schema version"
        )
    schema_version = int(schema_version)
    if manifest.get("market_date") != market_date:
        raise RiskArchiveValidationError(
            f"Risk archive marker date does not match its leaf: {leaf}"
        )
    if manifest.get("market_status") != OFFICIAL:
        raise RiskArchiveValidationError(f"Risk archive marker is not OFFICIAL: {leaf}")
    if schema_version in _VERSIONED_METADATA_SCHEMA_VERSIONS:
        _manifest_versioned_metadata(manifest, leaf=leaf)
    risk_file_name = _archive_file_name(schema_version, "risk")
    colossus_file_name = _archive_file_name(schema_version, "colossus")
    market_file_name = _archive_file_name(schema_version, "market")
    stock_file_name = _archive_file_name(schema_version, "stock")
    risk_columns = manifest.get("risk_columns")
    if not (
        isinstance(risk_columns, list)
        and all(
            isinstance(column, str) and bool(column.strip()) for column in risk_columns
        )
        and set(RISK_PROJECTION_COLUMNS).issubset(risk_columns)
    ):
        raise RiskArchiveValidationError(
            f"Risk archive columns are invalid in its completion marker: {leaf}"
        )
    if manifest.get("colossus_columns") != list(COLOSSUS_COLUMNS):
        raise RiskArchiveValidationError(
            f"Colossus archive columns do not match its completion marker: {leaf}"
        )
    for row_field in ("risk_rows", "colossus_rows"):
        value = manifest.get(row_field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise RiskArchiveValidationError(
                f"Risk archive row counts are invalid in its completion marker: {leaf}"
            )

    digests = manifest.get("sha256")
    if not isinstance(digests, dict):
        raise RiskArchiveValidationError(
            f"Risk archive digests are invalid in its completion marker: {leaf}"
        )
    for file_name in (risk_file_name, colossus_file_name):
        digest = digests.get(file_name)
        if not isinstance(digest, str) or not _SHA256_PATTERN.fullmatch(digest):
            raise RiskArchiveValidationError(
                f"Risk archive digests are invalid in its completion marker: {leaf}"
            )

    market_metadata = (
        manifest.get("market_rows"),
        manifest.get("market_columns"),
        digests.get(market_file_name),
    )
    has_any_market_metadata = any(value is not None for value in market_metadata)
    has_complete_market_metadata = (
        isinstance(market_metadata[0], int)
        and not isinstance(market_metadata[0], bool)
        and market_metadata[0] > 0
        and market_metadata[1] == list(MARKET_ARCHIVE_COLUMNS)
        and isinstance(market_metadata[2], str)
        and bool(_SHA256_PATTERN.fullmatch(market_metadata[2]))
    )
    market_required = schema_version in _MARKET_SCHEMA_VERSIONS
    if schema_version == 1 and has_any_market_metadata:
        raise RiskArchiveValidationError(
            f"Schema version 1 archive must not declare Market data: {leaf}"
        )
    if market_required and not has_complete_market_metadata:
        raise RiskArchiveValidationError(
            f"Market archive metadata is missing or invalid in completion marker: "
            f"{leaf}"
        )
    if has_any_market_metadata and not has_complete_market_metadata:
        raise RiskArchiveValidationError(
            f"Market archive metadata is incomplete in completion marker: {leaf}"
        )
    stock_metadata = (
        manifest.get("stock_date"),
        manifest.get("stock_rows"),
        manifest.get("stock_columns"),
        digests.get(stock_file_name),
    )
    has_any_stock_metadata = any(value is not None for value in stock_metadata)
    has_complete_stock_metadata = (
        stock_metadata[0] == market_date
        and isinstance(stock_metadata[1], int)
        and not isinstance(stock_metadata[1], bool)
        and stock_metadata[1] > 0
        and stock_metadata[2] == list(STOCK_COLUMNS)
        and isinstance(stock_metadata[3], str)
        and bool(_SHA256_PATTERN.fullmatch(stock_metadata[3]))
    )
    if schema_version not in _STOCK_SCHEMA_VERSIONS and has_any_stock_metadata:
        raise RiskArchiveValidationError(
            f"Archive schema {schema_version} may not declare Stock data: {leaf}"
        )
    if has_any_stock_metadata and not has_complete_stock_metadata:
        raise RiskArchiveValidationError(
            f"Stock archive metadata is incomplete or invalid in completion marker: "
            f"{leaf}"
        )
    fixture = manifest.get("fixture")
    if fixture == _V3_FIXTURE_TAG and schema_version != 3:
        raise RiskArchiveValidationError(
            f"Deterministic Rebirth v3 fixture must use schema version 3: {leaf}"
        )
    if fixture == _V4_FIXTURE_TAG and schema_version != ARCHIVE_SCHEMA_VERSION:
        raise RiskArchiveValidationError(
            f"Deterministic Rebirth v4 fixture must use schema version 4: {leaf}"
        )
    if (
        fixture == _V3_FIXTURE_TAG or fixture == _V4_FIXTURE_TAG
    ) and not has_complete_stock_metadata:
        raise RiskArchiveValidationError(
            f"Deterministic fixture archive must declare Stock data: {leaf}"
        )
    expected_files = _archive_file_names(
        schema_version,
        has_stock=has_complete_stock_metadata,
    )
    actual_entries = {path.name for path in leaf.iterdir()}
    if actual_entries != set(expected_files):
        missing = sorted(set(expected_files) - actual_entries)
        extra = sorted(actual_entries - set(expected_files))
        raise RiskArchiveValidationError(
            f"Risk archive leaf {leaf} is incomplete or invalid; "
            f"missing={missing}, extra={extra}"
        )
    return expected_files


def _load_completed_leaf(leaf: Path) -> RiskArchive:
    if not leaf.exists() or not leaf.is_dir():
        raise RiskArchiveValidationError(f"Risk archive leaf does not exist: {leaf}")
    actual_entries = {path.name for path in leaf.iterdir()}
    if SUCCESS_FILE_NAME not in actual_entries:
        raise RiskArchiveValidationError(
            f"Risk archive leaf {leaf} is incomplete or invalid; "
            f"missing={[SUCCESS_FILE_NAME]}"
        )
    market_date = _completed_leaf_date(leaf)
    manifest = _read_manifest(leaf)
    expected_files = _completed_leaf_contract(leaf, manifest, market_date)
    schema_version = int(manifest["schema_version"])
    domain_contracts = [
        (
            "risk",
            list(manifest["risk_columns"]),
            int(manifest["risk_rows"]),
        ),
        ("colossus", list(COLOSSUS_COLUMNS), int(manifest["colossus_rows"])),
    ]
    market_file_name = _archive_file_name(schema_version, "market")
    if market_file_name in expected_files:
        domain_contracts.append(
            ("market", list(MARKET_ARCHIVE_COLUMNS), int(manifest["market_rows"]))
        )
    frames: dict[str, pd.DataFrame] = {}
    for domain, expected_columns, expected_rows in domain_contracts:
        file_name = _archive_file_name(schema_version, domain)
        path = leaf / file_name
        expected_digest = (
            manifest.get("sha256", {}).get(file_name)
            if isinstance(manifest.get("sha256"), dict)
            else None
        )
        if expected_digest != _file_sha256(path):
            raise RiskArchiveValidationError(
                f"Risk archive file does not match its completion marker: {path}"
            )
        if _uses_parquet(schema_version):
            _validate_parquet_contract(
                path,
                expected_columns=expected_columns,
                expected_rows=expected_rows,
            )
        frames[domain] = _read_archive_frame(
            path,
            schema_version=schema_version,
            columns=expected_columns if _uses_parquet(schema_version) else None,
        )
    risk = validate_risk_archive_frame(frames["risk"])
    colossus = validate_colossus_frame(frames["colossus"])
    market = frames.get("market")
    if market is not None:
        market = validate_market_archive_frame(market, market_date=market_date)
    expected_columns = manifest.get("risk_columns")
    if expected_columns != list(risk.columns):
        raise RiskArchiveValidationError(
            f"Risk archive columns do not match its completion marker: {leaf}"
        )
    if manifest.get("risk_rows") != len(risk) or manifest.get("colossus_rows") != len(
        colossus
    ):
        raise RiskArchiveValidationError(
            f"Risk archive row counts do not match its completion marker: {leaf}"
        )
    if market is not None and manifest.get("market_rows") != len(market):
        raise RiskArchiveValidationError(
            f"Market archive row count does not match its completion marker: {leaf}"
        )
    revision: int | None = None
    risk_dates: Mapping[str, str] = MappingProxyType({})
    if schema_version in _VERSIONED_METADATA_SCHEMA_VERSIONS:
        revision, validated_risk_dates = _manifest_versioned_metadata(
            manifest, leaf=leaf
        )
        source_types = _source_types_in_risk(risk)
        if set(validated_risk_dates) != set(source_types):
            raise RiskArchiveValidationError(
                "versioned Risk archive risk_dates must be keyed exactly by "
                f"the Risk Source Type values in {leaf}; expected={list(source_types)}, "
                f"found={sorted(validated_risk_dates)}"
            )
        risk_dates = MappingProxyType(dict(validated_risk_dates))
    return RiskArchive(
        market_date=market_date,
        path=leaf,
        risk=risk,
        colossus=colossus,
        market=market,
        schema_version=schema_version,
        revision=revision,
        risk_dates=risk_dates,
        stock_rows=(
            int(manifest["stock_rows"])
            if _archive_file_name(schema_version, "stock") in expected_files
            else 0
        ),
    )


def load_risk_archive(root: str | Path, market_date: object) -> RiskArchive:
    """Load and validate one completed official daily archive."""

    return _load_completed_leaf(archive_leaf_path(root, market_date))


def _stock_leaf_fingerprint(leaf: Path) -> tuple[tuple[str, int, int], ...]:
    try:
        return tuple(
            (file_name, path.stat().st_size, path.stat().st_mtime_ns)
            for file_name in (_CSV_STOCK_FILE_NAME, STOCK_FILE_NAME, SUCCESS_FILE_NAME)
            if (path := leaf / file_name).is_file()
        )
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical Stock leaf {leaf}: {exc}"
        ) from exc


@lru_cache(maxsize=512)
def _load_stock_leaf_cached(
    leaf_text: str,
    fingerprint: tuple[tuple[str, int, int], ...],
    identity_items: tuple[tuple[str, str], ...],
) -> pd.DataFrame:
    """Validate and load only Stock, never unrelated Risk/P&L frames."""

    del fingerprint
    leaf = Path(leaf_text)
    market_date = _completed_leaf_date(leaf)
    manifest = _read_manifest(leaf)
    expected_files = _completed_leaf_contract(leaf, manifest, market_date)
    schema_version = int(manifest["schema_version"])
    stock_file_name = _archive_file_name(schema_version, "stock")
    if stock_file_name not in expected_files:
        return pd.DataFrame(columns=list(STOCK_COLUMNS))
    digests = manifest.get("sha256")
    expected_digest = (
        digests.get(stock_file_name) if isinstance(digests, dict) else None
    )
    stock_path = leaf / stock_file_name
    if expected_digest != _file_sha256(stock_path):
        raise RiskArchiveValidationError(
            f"Stock archive file does not match its completion marker: {stock_path}"
        )
    expected_rows = int(manifest["stock_rows"])
    filters = [(column, "==", value) for column, value in identity_items]
    if _uses_parquet(schema_version):
        _validate_parquet_contract(
            stock_path,
            expected_columns=list(STOCK_COLUMNS),
            expected_rows=expected_rows,
        )
    stock = _read_archive_frame(
        stock_path,
        schema_version=schema_version,
        columns=list(STOCK_COLUMNS) if _uses_parquet(schema_version) else None,
        filters=filters if _uses_parquet(schema_version) else None,
    )
    if stock.empty and identity_items:
        return pd.DataFrame(columns=list(STOCK_COLUMNS))
    stock = validate_stock_archive_frame(stock)
    if not _uses_parquet(schema_version) and len(stock) != expected_rows:
        raise RiskArchiveValidationError(
            f"Stock archive row count does not match its completion marker: {leaf}"
        )
    if not identity_items and len(stock) != expected_rows:
        raise RiskArchiveValidationError(
            f"Stock archive row count does not match its completion marker: {leaf}"
        )
    if identity_items and not _uses_parquet(schema_version):
        for column, value in identity_items:
            stock = stock.loc[stock[column].eq(value)]
    return stock.reset_index(drop=True)


def _stock_identity_items(
    identity: Mapping[str, str] | None,
) -> tuple[tuple[str, str], ...]:
    if identity is None:
        return ()
    if not isinstance(identity, Mapping) or set(identity) != set(
        STOCK_IDENTITY_COLUMNS
    ):
        raise RiskArchiveValidationError(
            "Stock archive identity must contain exactly "
            f"{list(STOCK_IDENTITY_COLUMNS)}"
        )
    values: list[tuple[str, str]] = []
    for column in STOCK_IDENTITY_COLUMNS:
        value = identity[column]
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise RiskArchiveValidationError(
                f"Stock archive identity {column!r} must be exact nonblank text"
            )
        values.append((column, value))
    return tuple(values)


def load_stock_archive_frame(
    root: str | Path,
    market_date: object,
    *,
    identity: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Load one optional Stock extension without materializing Risk/Market/P&L."""

    leaf = archive_leaf_path(root, market_date)
    if not leaf.exists() or not leaf.is_dir():
        raise RiskArchiveValidationError(f"Risk archive leaf does not exist: {leaf}")
    return _load_stock_leaf_cached(
        str(leaf),
        _stock_leaf_fingerprint(leaf),
        _stock_identity_items(identity),
    ).copy(deep=True)


def _completed_archive_root_signature(
    directory: Path,
) -> tuple[tuple[str, tuple[tuple[str, bool, int, int], ...]], ...]:
    """Fingerprint date leaves without reading any financial frame."""

    try:
        leaves = []
        for leaf in sorted(directory.iterdir(), key=lambda path: path.name):
            if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
                continue
            entries = []
            for entry in sorted(leaf.iterdir(), key=lambda path: path.name):
                stat = entry.stat()
                entries.append(
                    (entry.name, entry.is_file(), stat.st_size, stat.st_mtime_ns)
                )
            leaves.append((leaf.name, tuple(entries)))
        return tuple(leaves)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect Risk archive root {directory}: {exc}"
        ) from exc


@lru_cache(maxsize=16)
def _completed_v4_archive_days_cached(
    root_text: str,
    signature: tuple[tuple[str, tuple[tuple[str, bool, int, int], ...]], ...],
) -> tuple[CompletedArchiveDay, ...]:
    """Validate immutable v4 files once per process and return metadata only."""

    directory = Path(root_text)
    days: list[CompletedArchiveDay] = []
    for leaf_name, entries in signature:
        names = {name for name, is_file, _size, _mtime in entries if is_file}
        if SUCCESS_FILE_NAME not in names:
            continue
        leaf = directory / leaf_name
        market_date = _completed_leaf_date(leaf)
        manifest = _read_manifest(leaf)
        expected_files = _completed_leaf_contract(leaf, manifest, market_date)
        if manifest.get("schema_version") != ARCHIVE_SCHEMA_VERSION:
            raise RiskArchiveValidationError(
                "DuckDB archive history requires completed schema-v4 Parquet "
                f"leaves; found schema {manifest.get('schema_version')!r} in {leaf}"
            )
        revision, risk_dates = _manifest_versioned_metadata(manifest, leaf=leaf)
        stock_present = STOCK_FILE_NAME in expected_files
        contracts = {
            RISK_FILE_NAME: (
                list(manifest["risk_columns"]),
                int(manifest["risk_rows"]),
            ),
            COLOSSUS_FILE_NAME: (
                list(COLOSSUS_COLUMNS),
                int(manifest["colossus_rows"]),
            ),
            MARKET_FILE_NAME: (
                list(MARKET_ARCHIVE_COLUMNS),
                int(manifest["market_rows"]),
            ),
        }
        if stock_present:
            contracts[STOCK_FILE_NAME] = (
                list(STOCK_COLUMNS),
                int(manifest["stock_rows"]),
            )
        digests = manifest["sha256"]
        if not isinstance(digests, dict):  # pragma: no cover - contract checked above
            raise AssertionError("archive manifest sha256 must be a dictionary")
        for file_name, (columns, rows) in contracts.items():
            path = leaf / file_name
            try:
                digest = _file_sha256(path)
            except OSError as exc:
                raise RiskArchiveValidationError(
                    f"Could not hash completed archive file {path}: {exc}"
                ) from exc
            if digest != digests[file_name]:
                raise RiskArchiveValidationError(
                    f"Risk archive file does not match its completion marker: {path}"
                )
            _validate_parquet_contract(
                path,
                expected_columns=columns,
                expected_rows=rows,
            )
        days.append(
            CompletedArchiveDay(
                snapshot_date=market_date,
                revision=revision,
                risk_dates=MappingProxyType(dict(risk_dates)),
                path=leaf,
                risk_path=leaf / RISK_FILE_NAME,
                colossus_path=leaf / COLOSSUS_FILE_NAME,
                market_path=leaf / MARKET_FILE_NAME,
                stock_path=(leaf / STOCK_FILE_NAME if stock_present else None),
                stock_date=(str(manifest["stock_date"]) if stock_present else None),
                risk_rows=int(manifest["risk_rows"]),
                colossus_rows=int(manifest["colossus_rows"]),
                market_rows=int(manifest["market_rows"]),
                stock_rows=(int(manifest["stock_rows"]) if stock_present else 0),
            )
        )
    return tuple(days)


def list_completed_v4_archive_days(
    root: str | Path,
) -> tuple[CompletedArchiveDay, ...]:
    """Return explicitly validated completed v4 leaves without loading frames.

    In-progress date directories remain hidden. A completed legacy leaf fails
    explicitly so SQL callers cannot mistake a partial v4-only view for the
    complete archive; legacy readers remain available through the existing APIs.
    """

    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Risk archive root must be a directory: {directory}"
        )
    signature = _completed_archive_root_signature(directory)
    return _completed_v4_archive_days_cached(str(directory), signature)


def list_completed_market_dates(root: str | Path) -> tuple[str, ...]:
    """Hide partial leaves and fail closed on any invalid completed marker."""

    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Risk archive root must be a directory: {directory}"
        )
    dates: list[str] = []
    for leaf in directory.iterdir():
        if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
            continue
        if not (leaf / SUCCESS_FILE_NAME).is_file():
            continue
        market_date = _completed_leaf_date(leaf)
        manifest = _read_manifest(leaf)
        try:
            _completed_leaf_contract(leaf, manifest, market_date)
        except RiskArchiveValidationError as exc:
            raise RiskArchiveValidationError(
                f"Completed risk archive marker is invalid: {leaf / SUCCESS_FILE_NAME}"
            ) from exc
        dates.append(market_date)
    return tuple(sorted(set(dates)))


def _already_archived_result(archive: RiskArchive) -> ArchiveResult:
    return ArchiveResult(
        status="already_archived",
        reason="A completed official archive already exists for this Market Date.",
        market_date=archive.market_date,
        path=archive.path,
        risk_rows=len(archive.risk),
        colossus_rows=len(archive.colossus),
        market_rows=0 if archive.market is None else len(archive.market),
        stock_rows=archive.stock_rows,
    )


def archive_official_snapshot(
    snapshot: OfficialSnapshot,
    colossus_loader: ColossusLoader,
    root: str | Path,
) -> ArchiveResult:
    """Atomically write one eligible committed snapshot and its Colossus P&L.

    Eligibility is deliberately narrow: the selected Market Date must be the
    manager's naturally resolved business Market Date, the committed source
    must be exactly ``OFFICIAL``, and the snapshot must not be a retained
    last-good revision carrying refresh errors. Re-running a completed date is
    a no-op.
    """

    market_date = _normalize_date(snapshot.market_date, label="Market Date")
    system_date = _normalize_date(snapshot.system_date, label="System Date")
    natural_market_date = market_date_for(system_date).date().isoformat()
    leaf = archive_leaf_path(root, market_date)
    status = str(snapshot.market_status).strip()
    if market_date != natural_market_date:
        return ArchiveResult(
            status="skipped",
            reason="Selected Market Date is not the current natural Market Date.",
            market_date=market_date,
            path=leaf,
        )
    if status != OFFICIAL:
        return ArchiveResult(
            status="skipped",
            reason="Market source is not OFFICIAL yet.",
            market_date=market_date,
            path=leaf,
        )
    if tuple(snapshot.errors):
        return ArchiveResult(
            status="skipped",
            reason="The committed snapshot reports refresh errors.",
            market_date=market_date,
            path=leaf,
        )
    if leaf.exists():
        return _already_archived_result(_load_completed_leaf(leaf))
    if not callable(colossus_loader):
        raise TypeError("colossus_loader must be callable")

    risk = validate_risk_archive_frame(snapshot.dashboard_frame)
    colossus = validate_colossus_frame(colossus_loader(pd.Timestamp(market_date)))
    raw_market = getattr(snapshot, "market_frame", None)
    market = (
        None
        if raw_market is None
        else validate_market_archive_frame(raw_market, market_date=market_date)
    )
    fixture = getattr(snapshot, "fixture", None)
    if fixture is not None:
        if not isinstance(fixture, str) or not fixture.strip() or len(fixture) > 128:
            raise RiskArchiveValidationError(
                "optional archive fixture tag must be nonblank text of at most "
                "128 characters"
            )
        fixture = fixture.strip()
    raw_stock = getattr(snapshot, "stock_frame", None)
    stock = None if raw_stock is None else validate_stock_archive_frame(raw_stock)
    schema_version = ARCHIVE_SCHEMA_VERSION if market is not None else 1
    if stock is not None and schema_version != ARCHIVE_SCHEMA_VERSION:
        raise RiskArchiveValidationError(
            "Stock may be archived only with a canonical MarketBook"
        )
    if fixture == _V3_FIXTURE_TAG:
        raise RiskArchiveValidationError(
            "new fixture snapshots must use deterministic-rebirth-v4"
        )
    if fixture == _V4_FIXTURE_TAG and stock is None:
        raise RiskArchiveValidationError(
            "deterministic-rebirth-v4 fixture snapshots must provide stock_frame"
        )
    stock_date = market_date
    if stock is not None:
        stock_date = _normalize_date(
            getattr(snapshot, "stock_date", snapshot.market_date),
            label="Stock Date",
        )
        if stock_date != market_date:
            raise RiskArchiveValidationError(
                "Stock Date must match the archive Market Date"
            )
    if schema_version in _VERSIONED_METADATA_SCHEMA_VERSIONS:
        archive_revision, archive_risk_dates = _snapshot_versioned_metadata(
            snapshot, risk
        )
    else:
        archive_revision = int(snapshot.revision)
        archive_risk_dates = {}
    root_directory = leaf.parent
    root_directory.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{leaf.name}.pending-", dir=root_directory)
    )
    try:
        risk_file_name = _archive_file_name(schema_version, "risk")
        colossus_file_name = _archive_file_name(schema_version, "colossus")
        market_file_name = _archive_file_name(schema_version, "market")
        stock_file_name = _archive_file_name(schema_version, "stock")
        risk_path = temporary / risk_file_name
        colossus_path = temporary / colossus_file_name
        _write_archive_frame(risk, risk_path, schema_version=schema_version)
        _write_archive_frame(colossus, colossus_path, schema_version=schema_version)
        market_path: Path | None = None
        if market is not None:
            market_path = temporary / market_file_name
            _write_archive_frame(market, market_path, schema_version=schema_version)
        stock_path: Path | None = None
        if stock is not None:
            stock_path = temporary / stock_file_name
            _write_archive_frame(stock, stock_path, schema_version=schema_version)
        refreshed_at = getattr(snapshot, "refreshed_at", None)
        refreshed_text = (
            refreshed_at.isoformat()
            if isinstance(refreshed_at, datetime)
            else str(refreshed_at or "")
        )
        manifest: dict[str, object] = {
            "schema_version": schema_version,
            "market_date": market_date,
            "market_status": OFFICIAL,
            "revision": archive_revision,
            "refreshed_at": refreshed_text,
            "risk_rows": len(risk),
            "colossus_rows": len(colossus),
            "risk_columns": list(risk.columns),
            "colossus_columns": list(COLOSSUS_COLUMNS),
            "sha256": {
                risk_file_name: _file_sha256(risk_path),
                colossus_file_name: _file_sha256(colossus_path),
            },
        }
        if fixture is not None:
            manifest["fixture"] = fixture
        if market is not None and market_path is not None:
            manifest["risk_dates"] = archive_risk_dates
            manifest["market_rows"] = len(market)
            manifest["market_columns"] = list(MARKET_ARCHIVE_COLUMNS)
            manifest_sha256 = manifest["sha256"]
            if not isinstance(manifest_sha256, dict):  # pragma: no cover - local
                raise AssertionError("manifest sha256 must be a dictionary")
            manifest_sha256[market_file_name] = _file_sha256(market_path)
        if stock is not None and stock_path is not None:
            manifest["stock_date"] = stock_date
            manifest["stock_rows"] = len(stock)
            manifest["stock_columns"] = list(STOCK_COLUMNS)
            manifest_sha256 = manifest["sha256"]
            if not isinstance(manifest_sha256, dict):  # pragma: no cover - local
                raise AssertionError("manifest sha256 must be a dictionary")
            manifest_sha256[stock_file_name] = _file_sha256(stock_path)
        _write_json(manifest, temporary / SUCCESS_FILE_NAME)
        try:
            temporary.rename(leaf)
        except OSError:
            if leaf.exists():
                existing = _load_completed_leaf(leaf)
                return _already_archived_result(existing)
            raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return ArchiveResult(
        status="archived",
        reason="Official Risk Explorer and Colossus P&L archived.",
        market_date=market_date,
        path=leaf,
        risk_rows=len(risk),
        colossus_rows=len(colossus),
        market_rows=0 if market is None else len(market),
        stock_rows=0 if stock is None else len(stock),
    )


def archive_from_manager(
    manager: object,
    colossus_loader: ColossusLoader,
    root: str | Path,
    *,
    refresh: bool = True,
) -> ArchiveResult:
    """Refresh once for a scheduled job, then archive that coherent snapshot."""

    if refresh:
        refresh_method = getattr(manager, "refresh", None)
        if not callable(refresh_method):
            raise TypeError("manager must expose a callable refresh method")
        snapshot = refresh_method(
            force_risk=True,
            force_pl=True,
            reason="scheduled_official_archive",
        )
    else:
        snapshot = getattr(manager, "snapshot")
    return archive_official_snapshot(snapshot, colossus_loader, root)


def build_history_portfolio_authority(risk: pd.DataFrame) -> pd.DataFrame:
    """Return one nonduplicating Portfolio authority for historical P&L.

    Colossus owns no Product or SignoffGroup.  Those two fields are authoritative
    only when the archived Predict snapshot has exactly one distinct
    ``(SignoffGroup, Product)`` pair for the Portfolio.  Ambiguous Portfolios are
    retained once and labelled ``Unmapped`` so callers can expose them without
    guessing or duplicating Colossus rows.  The remaining filter metadata is
    independently retained only when unique for that Portfolio.
    """

    validated = validate_risk_archive_frame(risk)
    required = (
        PORTFOLIO,
        SIGNOFF_GROUP,
        PRODUCT,
        ACTIVITY,
        CATEGORY,
        SUB_CATEGORY,
    )
    missing = [column for column in required if column not in validated]
    if missing:
        raise RiskArchiveValidationError(
            "official Risk Explorer snapshot is missing historical P&L authority "
            f"columns: {missing}"
        )
    normalized = _validate_text_columns(
        validated,
        required,
        label="official Risk Explorer snapshot",
    )
    portfolios = (
        normalized[[PORTFOLIO]]
        .drop_duplicates()
        .sort_values(PORTFOLIO, kind="stable")
        .reset_index(drop=True)
    )
    pairs = normalized[[PORTFOLIO, SIGNOFF_GROUP, PRODUCT]].drop_duplicates()
    pair_counts = pairs.groupby(PORTFOLIO, sort=False).size()
    valid_portfolios = set(pair_counts.loc[pair_counts.eq(1)].index.astype(str))
    unique_pairs = pairs.loc[pairs[PORTFOLIO].isin(valid_portfolios)]
    authority = portfolios.merge(
        unique_pairs,
        on=PORTFOLIO,
        how="left",
        validate="one_to_one",
    )
    mapped = authority[PORTFOLIO].isin(valid_portfolios)
    authority[HISTORY_MAPPING_STATUS] = np.where(
        mapped,
        MAPPED_HISTORY_VALUE,
        UNMAPPED_VALUE,
    )
    authority.loc[~mapped, [SIGNOFF_GROUP, PRODUCT]] = UNMAPPED_VALUE

    for column in (ACTIVITY, CATEGORY, SUB_CATEGORY):
        values = normalized[[PORTFOLIO, column]].drop_duplicates()
        counts = values.groupby(PORTFOLIO, sort=False).size()
        unique_portfolios = set(counts.loc[counts.eq(1)].index.astype(str))
        unique_values = values.loc[values[PORTFOLIO].isin(unique_portfolios)]
        authority = authority.merge(
            unique_values,
            on=PORTFOLIO,
            how="left",
            validate="one_to_one",
        )
        authority[column] = authority[column].fillna(UNMAPPED_VALUE)

    return authority.loc[:, list(PORTFOLIO_AUTHORITY_COLUMNS)].reset_index(drop=True)


def project_archive_to_pl_history(archive: RiskArchive) -> pd.DataFrame:
    """Project one archive into the existing canonical Colossus/Predict grain.

    Predict is summed from position rows only after grouping to SignoffGroup +
    Risk Type + Risk Greek + Underlying + Product + Portfolio. A partially
    missing PL group is omitted rather than treated as a partial or zero total.
    Colossus receives SignoffGroup and Product only from the strict archived
    Portfolio authority. Unknown or ambiguous Portfolios are retained once in
    the explicit Unmapped hierarchy instead of failing or being duplicated.
    """

    market_date = _normalize_date(archive.market_date, label="Market Date")
    risk = validate_risk_archive_frame(archive.risk)
    colossus = validate_colossus_frame(archive.colossus)
    authority_dimensions = (
        SIGNOFF_GROUP,
        ACTIVITY,
        CATEGORY,
        SUB_CATEGORY,
    )
    missing = [column for column in authority_dimensions if column not in risk]
    if missing:
        raise RiskArchiveValidationError(
            "official Risk Explorer snapshot is missing historical P&L authority "
            f"columns: {missing}"
        )
    normalized_risk = _validate_text_columns(
        risk,
        (
            PORTFOLIO,
            UNDERLYING,
            RISK_TYPE,
            RISK_GREEK,
            PRODUCT,
            SIGNOFF_GROUP,
            ACTIVITY,
            CATEGORY,
            SUB_CATEGORY,
        ),
        label="official Risk Explorer snapshot",
    )
    normalized_risk[PL] = _nullable_numeric(
        normalized_risk[PL],
        label="official Risk Explorer snapshot column 'PL'",
        allow_missing=True,
    )

    portfolio_authority = build_history_portfolio_authority(normalized_risk)
    predict_keys = [
        SIGNOFF_GROUP,
        RISK_TYPE,
        RISK_GREEK,
        UNDERLYING,
        PRODUCT,
        PORTFOLIO,
    ]
    predicted = (
        normalized_risk[predict_keys + [PL]]
        .groupby(
            predict_keys,
            as_index=False,
            sort=False,
            observed=True,
            dropna=False,
        )[PL]
        .agg(lambda values: values.sum(min_count=len(values)))
        .dropna(subset=[PL])
    )
    predicted = predicted.merge(
        portfolio_authority[[PORTFOLIO, ACTIVITY, CATEGORY, SUB_CATEGORY]],
        on=PORTFOLIO,
        how="left",
        validate="many_to_one",
    )
    predicted[HISTORY_MAPPING_STATUS] = MAPPED_HISTORY_VALUE
    predicted.insert(0, HISTORY_TYPE, PREDICT_TYPE)
    predicted.insert(0, MARKET_DATE, market_date)

    actual = colossus.merge(
        portfolio_authority,
        on=PORTFOLIO,
        how="left",
        validate="many_to_one",
    )
    authority_columns = (
        SIGNOFF_GROUP,
        PRODUCT,
        ACTIVITY,
        CATEGORY,
        SUB_CATEGORY,
        HISTORY_MAPPING_STATUS,
    )
    for column in authority_columns:
        actual[column] = actual[column].fillna(UNMAPPED_VALUE)
    actual.insert(0, HISTORY_TYPE, COLOSSUS_TYPE)
    actual.insert(0, MARKET_DATE, market_date)

    history = pd.concat(
        [
            actual[list(PL_HISTORY_COLUMNS)],
            predicted[list(PL_HISTORY_COLUMNS)],
        ],
        ignore_index=True,
    )
    duplicates = history.duplicated(list(PL_HISTORY_KEY), keep=False)
    if duplicates.any():
        keys = (
            history.loc[duplicates, list(PL_HISTORY_KEY)]
            .drop_duplicates()
            .to_dict("records")
        )
        raise RiskArchiveValidationError(
            f"Projected P&L history contains duplicate hierarchy keys: {keys}"
        )
    return history.sort_values(list(PL_HISTORY_KEY), kind="stable").reset_index(
        drop=True
    )


def _leaf_fingerprint(leaf: Path) -> tuple[tuple[str, int, int], ...]:
    """Return a cheap immutable-leaf cache key without rereading data frames."""

    return tuple(
        (file_name, path.stat().st_size, path.stat().st_mtime_ns)
        for file_name in ALL_ARCHIVE_FILE_NAMES
        if (path := leaf / file_name).is_file()
    )


@lru_cache(maxsize=512)
def _project_completed_leaf_cached(
    leaf_text: str,
    fingerprint: tuple[tuple[str, int, int], ...],
) -> pd.DataFrame:
    """Validate/hash one immutable leaf once per worker and cache its projection."""

    del fingerprint
    return project_archive_to_pl_history(_load_completed_leaf(Path(leaf_text)))


def _legacy_leaf_fingerprint(leaf: Path) -> tuple[tuple[str, int, int], ...]:
    """Fingerprint one immutable checked-in legacy date leaf."""

    try:
        fingerprint = []
        for file_name in sorted(_LEGACY_HISTORY_FILE_NAMES):
            stat = (leaf / file_name).stat()
            fingerprint.append((file_name, stat.st_size, stat.st_mtime_ns))
        return tuple(fingerprint)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect legacy P&L history leaf {leaf}: {exc}"
        ) from exc


@lru_cache(maxsize=512)
def _load_legacy_leaf_cached(
    leaf_text: str,
    fingerprint: tuple[tuple[str, int, int], ...],
) -> pd.DataFrame:
    """Parse one unchanged legacy date leaf at most once per worker."""

    del fingerprint
    try:
        return load_legacy_pl_history_leaf(Path(leaf_text))
    except PLSendValidationError as exc:
        raise RiskArchiveValidationError(str(exc)) from exc


def load_shared_pl_history(root: str | Path) -> pd.DataFrame:
    """Load one ``data/histo`` root containing legacy and official dates.

    Legacy demo leaves contain the old ``histo.csv``/``predicted.csv`` pair.
    Completed official leaves contain sole Predict Risk plus Colossus authority.
    A date leaf may use exactly one versioned contract. Partial
    official leaves without ``_SUCCESS`` are hidden; completed leaves are
    validated against their manifest before any rows are returned.
    """

    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return pd.DataFrame(columns=list(PL_HISTORY_COLUMNS))
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Shared P&L history root must be a directory: {directory}"
        )

    frames: list[pd.DataFrame] = []
    try:
        leaf_entries = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect shared P&L history root {directory}: {exc}"
        ) from exc
    for leaf in leaf_entries:
        if _PENDING_LEAF_PATTERN.fullmatch(leaf.name):
            continue
        if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
            raise RiskArchiveValidationError(
                "Shared P&L history root may contain only YYYY-MM-DD leaves; "
                f"found {leaf}"
            )
        market_date = _completed_leaf_date(leaf)
        try:
            entries = tuple(leaf.iterdir())
        except OSError as exc:
            raise RiskArchiveValidationError(
                f"Could not inspect shared P&L history leaf {leaf}: {exc}"
            ) from exc
        names = {path.name for path in entries}
        legacy_artifacts = names & _LEGACY_HISTORY_FILE_NAMES
        official_artifacts = names & _OFFICIAL_HISTORY_FILE_NAMES
        if legacy_artifacts and official_artifacts:
            raise RiskArchiveValidationError(
                f"P&L history date {market_date} mixes legacy and official files"
            )
        if official_artifacts:
            if SUCCESS_FILE_NAME not in names:
                continue
            projected = _project_completed_leaf_cached(
                str(leaf),
                _leaf_fingerprint(leaf),
            )
            frames.append(projected.copy(deep=True))
            continue
        legacy = _load_legacy_leaf_cached(
            str(leaf),
            _legacy_leaf_fingerprint(leaf),
        )
        frames.append(legacy.copy(deep=True))

    if not frames:
        return pd.DataFrame(columns=list(PL_HISTORY_COLUMNS))
    try:
        history = validate_pl_history_frame(pd.concat(frames, ignore_index=True))
    except PLSendValidationError as exc:
        raise RiskArchiveValidationError(str(exc)) from exc
    duplicates = history.duplicated(list(PL_HISTORY_KEY), keep=False)
    if duplicates.any():
        raise RiskArchiveValidationError(
            "Shared P&L history contains duplicate date/type/hierarchy keys"
        )
    return history


def _risk_leaf_fingerprint(leaf: Path) -> tuple[tuple[str, int, int], ...]:
    """Fingerprint only immutable files needed by an exact Risk-history read."""

    try:
        return tuple(
            (file_name, path.stat().st_size, path.stat().st_mtime_ns)
            for file_name in (_CSV_RISK_FILE_NAME, RISK_FILE_NAME, SUCCESS_FILE_NAME)
            if (path := leaf / file_name).is_file()
        )
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical Risk leaf {leaf}: {exc}"
        ) from exc


@lru_cache(maxsize=4096)
def _load_risk_identity_leaf_cached(
    leaf_text: str,
    fingerprint: tuple[tuple[str, int, int], ...],
    source_type: str,
    risk_type: str,
    risk_greek: str,
    identity_value: str,
    identity_mode: str,
) -> pd.DataFrame:
    """Validate versioned Risk authority and cache one exact history identity."""

    del fingerprint
    leaf = Path(leaf_text)
    market_date = _completed_leaf_date(leaf)
    names = {path.name for path in leaf.iterdir()}
    if SUCCESS_FILE_NAME not in names:
        return pd.DataFrame(columns=list(RISK_HISTORY_METADATA_COLUMNS))
    manifest = _read_manifest(leaf)
    _completed_leaf_contract(leaf, manifest, market_date)
    schema_version = int(manifest["schema_version"])
    if schema_version not in _VERSIONED_METADATA_SCHEMA_VERSIONS:
        return pd.DataFrame(columns=list(RISK_HISTORY_METADATA_COLUMNS))
    risk_file_name = _archive_file_name(schema_version, "risk")
    risk_path = leaf / risk_file_name
    digests = manifest.get("sha256")
    expected_digest = digests.get(risk_file_name) if isinstance(digests, dict) else None
    if expected_digest != _file_sha256(risk_path):
        raise RiskArchiveValidationError(
            f"Historical Risk does not match its completion marker: {risk_path}"
        )
    risk_columns = list(manifest["risk_columns"])
    risk_rows = int(manifest["risk_rows"])
    identity_column = REPORTED_UNDERLYING if identity_mode == "reported" else UNDERLYING
    if identity_column not in risk_columns:
        raise RiskArchiveValidationError(
            f"Historical Risk is missing identity column {identity_column!r}: {leaf}"
        )
    filters = [
        (SOURCE_TYPE, "==", source_type),
        (RISK_TYPE, "==", risk_type),
        (RISK_GREEK, "==", risk_greek),
        (identity_column, "==", identity_value),
    ]
    if _uses_parquet(schema_version):
        _validate_parquet_contract(
            risk_path,
            expected_columns=risk_columns,
            expected_rows=risk_rows,
        )
        source_frame = _read_archive_frame(
            risk_path,
            schema_version=schema_version,
            columns=[SOURCE_TYPE],
        )
        source_types = _source_types_in_risk(source_frame)
        selected = _read_archive_frame(
            risk_path,
            schema_version=schema_version,
            columns=risk_columns,
            filters=filters,
        )
        if not selected.empty:
            selected = validate_risk_archive_frame(selected)
    else:
        risk = validate_risk_archive_frame(
            _read_archive_frame(risk_path, schema_version=schema_version)
        )
        if risk_columns != list(risk.columns):
            raise RiskArchiveValidationError(
                f"Risk archive columns do not match its completion marker: {leaf}"
            )
        if risk_rows != len(risk):
            raise RiskArchiveValidationError(
                f"Risk archive row count does not match its completion marker: {leaf}"
            )
        source_types = _source_types_in_risk(risk)
        selected = risk
        for column, _operator, value in filters:
            selected = selected.loc[selected[column].eq(value)]
        selected = selected.copy()
    revision, risk_dates = _manifest_versioned_metadata(manifest, leaf=leaf)
    if set(risk_dates) != set(source_types):
        raise RiskArchiveValidationError(
            "versioned Risk archive risk_dates must be keyed exactly by "
            f"the Risk Source Type values in {leaf}; expected={list(source_types)}, "
            f"found={sorted(risk_dates)}"
        )
    if selected.empty:
        return pd.DataFrame(columns=[*RISK_HISTORY_METADATA_COLUMNS, *risk_columns])
    metadata_overlap = set(RISK_HISTORY_METADATA_COLUMNS) & set(selected.columns)
    if metadata_overlap:
        raise RiskArchiveValidationError(
            f"Historical Risk contains archive-owned metadata columns: "
            f"{sorted(metadata_overlap)}"
        )
    selected.insert(0, MAPPING_STATUS, MAPPED_HISTORY_VALUE)
    selected.insert(0, RISK_DATE, risk_dates[source_type])
    selected.insert(0, REVISION, revision)
    selected.insert(0, SNAPSHOT_DATE, market_date)
    return selected.reset_index(drop=True)


def _bounded_row_limit(value: object, *, label: str = "history row limit") -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise RiskArchiveValidationError(f"{label} must be a positive integer")
    selected = int(value)
    if selected < 1:
        raise RiskArchiveValidationError(f"{label} must be a positive integer")
    return selected


def load_risk_history_for_identity(
    root: str | Path,
    source_type: str,
    risk_type: str,
    risk_greek: str,
    underlying: str,
    *,
    identity_mode: str = "underlying",
    max_rows: int = 100_000,
) -> pd.DataFrame:
    """Return exact v3/v4 Risk rows with truthful daily metadata."""

    selected_source = _identity_argument(source_type, label=SOURCE_TYPE)
    selected_risk_type = _identity_argument(risk_type, label=RISK_TYPE)
    selected_risk_greek = _identity_argument(risk_greek, label=RISK_GREEK)
    selected_underlying = _identity_argument(underlying, label=UNDERLYING)
    if not isinstance(identity_mode, str):
        raise RiskArchiveValidationError("Risk identity mode must be text")
    selected_mode = identity_mode.strip().casefold()
    if selected_mode not in {"reported", "underlying"}:
        raise RiskArchiveValidationError(
            "Risk identity mode must be 'reported' or 'underlying'"
        )
    row_limit = _bounded_row_limit(max_rows)
    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return pd.DataFrame(columns=list(RISK_HISTORY_METADATA_COLUMNS))
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Historical Risk root must be a directory: {directory}"
        )

    frames: list[pd.DataFrame] = []
    row_count = 0
    try:
        leaves = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical Risk root {directory}: {exc}"
        ) from exc
    for leaf in leaves:
        if _PENDING_LEAF_PATTERN.fullmatch(leaf.name):
            continue
        if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
            raise RiskArchiveValidationError(
                f"Historical Risk root may contain only YYYY-MM-DD leaves; found {leaf}"
            )
        selected = _load_risk_identity_leaf_cached(
            str(leaf),
            _risk_leaf_fingerprint(leaf),
            selected_source,
            selected_risk_type,
            selected_risk_greek,
            selected_underlying,
            selected_mode,
        ).copy(deep=True)
        if selected.empty:
            continue
        row_count += len(selected)
        if row_count > row_limit:
            raise RiskArchiveValidationError(
                f"Historical Risk query exceeds its {row_limit}-row bound"
            )
        frames.append(selected)
    if not frames:
        return pd.DataFrame(columns=list(RISK_HISTORY_METADATA_COLUMNS))
    return pd.concat(frames, ignore_index=True, sort=False).reset_index(drop=True)


def _market_leaf_fingerprint(leaf: Path) -> tuple[tuple[str, int, int], ...]:
    """Fingerprint only files needed to establish historical market authority."""

    names = sorted(
        {_CSV_MARKET_FILE_NAME, MARKET_FILE_NAME, SUCCESS_FILE_NAME}
        | set(_LEGACY_HISTORY_FILE_NAMES)
    )
    try:
        return tuple(
            (file_name, path.stat().st_size, path.stat().st_mtime_ns)
            for file_name in names
            if (path := leaf / file_name).is_file()
        )
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical MarketBook leaf {leaf}: {exc}"
        ) from exc


@lru_cache(maxsize=4096)
def _load_market_identity_leaf_cached(
    leaf_text: str,
    fingerprint: tuple[tuple[str, int, int], ...],
    risk_type: str,
    risk_greek: str,
    underlying: str,
) -> pd.DataFrame:
    """Validate one unchanged market file and cache only one raw identity."""

    del fingerprint
    leaf = Path(leaf_text)
    market_date = _completed_leaf_date(leaf)
    names = {path.name for path in leaf.iterdir()}
    if SUCCESS_FILE_NAME in names:
        manifest = _read_manifest(leaf)
        expected_files = _completed_leaf_contract(leaf, manifest, market_date)
        schema_version = int(manifest["schema_version"])
        market_file_name = _archive_file_name(schema_version, "market")
        if market_file_name not in expected_files:
            return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
        digests = manifest.get("sha256")
        expected_digest = (
            digests.get(market_file_name) if isinstance(digests, dict) else None
        )
        market_path = leaf / market_file_name
        if expected_digest != _file_sha256(market_path):
            raise RiskArchiveValidationError(
                "Historical MarketBook does not match its completion marker: "
                f"{market_path}"
            )
        if _uses_parquet(schema_version):
            _validate_parquet_contract(
                market_path,
                expected_columns=list(MARKET_ARCHIVE_COLUMNS),
                expected_rows=int(manifest["market_rows"]),
            )
            archived_dates = _read_archive_frame(
                market_path,
                schema_version=schema_version,
                columns=[MARKET_DATE],
            )[MARKET_DATE].map(
                lambda value: _normalize_date(value, label="Market Date")
            )
            if archived_dates.drop_duplicates().tolist() != [market_date]:
                raise RiskArchiveValidationError(
                    "Historical MarketBook dates do not match its archive leaf: "
                    f"{market_path}"
                )
            market = _read_archive_frame(
                market_path,
                schema_version=schema_version,
                columns=list(MARKET_ARCHIVE_COLUMNS),
                filters=[
                    (RISK_TYPE, "==", risk_type),
                    (RISK_GREEK, "==", risk_greek),
                    (UNDERLYING, "==", underlying),
                ],
            )
            if market.empty:
                return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
            return validate_market_archive_frame(market, market_date=market_date)
    else:
        schema_version = 1
        market_file_name = _CSV_MARKET_FILE_NAME
        market_path = leaf / market_file_name
        missing_legacy = sorted(_LEGACY_HISTORY_FILE_NAMES - names)
        official_artifacts = names & _OFFICIAL_HISTORY_FILE_NAMES
        if official_artifacts:
            # A partial official write is never historical authority, even if a
            # market file happened to reach the target directory independently.
            return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
        if missing_legacy:
            raise RiskArchiveValidationError(
                f"Historical MarketBook date {market_date} is not a completed "
                f"legacy P&L leaf; missing={missing_legacy}"
            )
        if market_file_name not in names:
            return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
    market = _read_archive_frame(market_path, schema_version=schema_version)
    market = validate_market_archive_frame(market, market_date=market_date)
    return market.loc[
        market[RISK_TYPE].eq(risk_type)
        & market[RISK_GREEK].eq(risk_greek)
        & market[UNDERLYING].eq(underlying)
    ].reset_index(drop=True)


def _identity_argument(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RiskArchiveValidationError(f"{label} must be nonblank text")
    return value.strip()


def load_market_history_for_identity(
    root: str | Path,
    risk_type: str,
    risk_greek: str,
    underlying: str,
) -> pd.DataFrame:
    """Return one raw Quick Market identity across completed archive dates.

    Selection is the structured Risk Type/Risk Greek/raw Underlying triple,
    never a parsed display label.  Every stored quote cell is retained at its
    connector-owned tenor grain; no Portfolio join, aggregation, or weighting
    occurs.  Callers can therefore select one explicit tenor cell for a daily
    series, or render the complete historical curve/surface for each date.
    """

    selected_risk_type = _identity_argument(risk_type, label=RISK_TYPE)
    selected_risk_greek = _identity_argument(risk_greek, label=RISK_GREEK)
    selected_underlying = _identity_argument(underlying, label=UNDERLYING)
    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return pd.DataFrame(columns=list(MARKET_HISTORY_COLUMNS))
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Historical MarketBook root must be a directory: {directory}"
        )

    frames: list[pd.DataFrame] = []
    try:
        leaves = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical MarketBook root {directory}: {exc}"
        ) from exc
    for leaf in leaves:
        if _PENDING_LEAF_PATTERN.fullmatch(leaf.name):
            continue
        if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
            raise RiskArchiveValidationError(
                "Historical MarketBook root may contain only YYYY-MM-DD leaves; "
                f"found {leaf}"
            )
        selected = _load_market_identity_leaf_cached(
            str(leaf),
            _market_leaf_fingerprint(leaf),
            selected_risk_type,
            selected_risk_greek,
            selected_underlying,
        ).copy(deep=True)
        if not selected.empty:
            frames.append(selected)

    if not frames:
        return pd.DataFrame(columns=list(MARKET_HISTORY_COLUMNS))
    selected_history = pd.concat(frames, ignore_index=True, sort=False)
    source_types = selected_history[SOURCE_TYPE].drop_duplicates().tolist()
    if len(source_types) != 1:
        raise RiskArchiveValidationError(
            "Historical MarketBook identity resolves to multiple Source Types: "
            f"{source_types}"
        )
    duplicates = selected_history.duplicated(
        [MARKET_DATE, TENOR_SWAP, TENOR_OPTION], keep=False
    )
    if duplicates.any():
        keys = (
            selected_history.loc[duplicates, [MARKET_DATE, TENOR_SWAP, TENOR_OPTION]]
            .drop_duplicates()
            .to_dict("records")
        )
        raise RiskArchiveValidationError(
            f"Historical MarketBook identity contains duplicate daily quote cells: "
            f"{keys}"
        )
    return (
        selected_history.loc[:, list(MARKET_HISTORY_COLUMNS)]
        .sort_values(
            [
                MARKET_DATE,
                TENOR_SWAP_ORDER,
                TENOR_OPTION_ORDER,
                TENOR_SWAP,
                TENOR_OPTION,
            ],
            kind="stable",
            na_position="last",
        )
        .reset_index(drop=True)
    )


def load_full_market_history_for_identity(
    root: str | Path,
    source_type: str,
    risk_type: str,
    risk_greek: str,
    underlying: str,
    *,
    max_rows: int = 100_000,
) -> pd.DataFrame:
    """Return exact full-schema MarketBook rows across completed dates.

    Unlike the compact Quick Market loader, this Data-page boundary retains
    Source Type, Open, Current, Move, Market Status, and Market Data Status.
    V1/V2/V3/V4 completed market leaves and complete legacy market files remain
    readable; no Portfolio/reporting fields are joined onto quote grain.
    """

    selected_source = _identity_argument(source_type, label=SOURCE_TYPE)
    selected_risk_type = _identity_argument(risk_type, label=RISK_TYPE)
    selected_risk_greek = _identity_argument(risk_greek, label=RISK_GREEK)
    selected_underlying = _identity_argument(underlying, label=UNDERLYING)
    row_limit = _bounded_row_limit(max_rows)
    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Historical MarketBook root must be a directory: {directory}"
        )

    frames: list[pd.DataFrame] = []
    row_count = 0
    try:
        leaves = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical MarketBook root {directory}: {exc}"
        ) from exc
    for leaf in leaves:
        if _PENDING_LEAF_PATTERN.fullmatch(leaf.name):
            continue
        if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
            raise RiskArchiveValidationError(
                "Historical MarketBook root may contain only YYYY-MM-DD leaves; "
                f"found {leaf}"
            )
        selected = _load_market_identity_leaf_cached(
            str(leaf),
            _market_leaf_fingerprint(leaf),
            selected_risk_type,
            selected_risk_greek,
            selected_underlying,
        ).copy(deep=True)
        selected = selected.loc[selected[SOURCE_TYPE].eq(selected_source)]
        if selected.empty:
            continue
        row_count += len(selected)
        if row_count > row_limit:
            raise RiskArchiveValidationError(
                f"Historical MarketBook query exceeds its {row_limit}-row bound"
            )
        frames.append(selected)
    if not frames:
        return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
    history = pd.concat(frames, ignore_index=True, sort=False)
    duplicates = history.duplicated([MARKET_DATE, TENOR_SWAP, TENOR_OPTION], keep=False)
    if duplicates.any():
        keys = (
            history.loc[duplicates, [MARKET_DATE, TENOR_SWAP, TENOR_OPTION]]
            .drop_duplicates()
            .to_dict("records")
        )
        raise RiskArchiveValidationError(
            "Historical MarketBook identity contains duplicate daily quote cells: "
            f"{keys}"
        )
    return (
        history.loc[:, list(MARKET_ARCHIVE_COLUMNS)]
        .sort_values(
            [
                MARKET_DATE,
                TENOR_SWAP_ORDER,
                TENOR_OPTION_ORDER,
                TENOR_SWAP,
                TENOR_OPTION,
            ],
            kind="stable",
            na_position="last",
        )
        .reset_index(drop=True)
    )


def clear_archive_caches() -> None:
    """Clear only in-process, reconstructable archive reader caches."""

    _completed_v4_archive_days_cached.cache_clear()
    _project_completed_leaf_cached.cache_clear()
    _load_legacy_leaf_cached.cache_clear()
    _load_market_identity_leaf_cached.cache_clear()
    _load_risk_identity_leaf_cached.cache_clear()
    _load_stock_leaf_cached.cache_clear()


def build_market_history_loader(
    root: str | Path,
) -> Callable[[str, str, str], pd.DataFrame]:
    """Bind a shared history root for dependency injection into Quick Market."""

    resolved_root = Path(root).expanduser().resolve()

    def load(risk_type: str, risk_greek: str, underlying: str) -> pd.DataFrame:
        return load_market_history_for_identity(
            resolved_root,
            risk_type,
            risk_greek,
            underlying,
        )

    return load


__all__ = [
    "ALL_ARCHIVE_FILE_NAMES",
    "ARCHIVE_FILE_NAMES",
    "ARCHIVE_SCHEMA_VERSION",
    "ArchiveResult",
    "BASE_ARCHIVE_FILE_NAMES",
    "CompletedArchiveDay",
    "COLOSSUS_COLUMNS",
    "COLOSSUS_FILE_NAME",
    "COLOSSUS_KEY",
    "ColossusLoader",
    "MARKET_ARCHIVE_COLUMNS",
    "MARKET_FILE_NAME",
    "MARKET_HISTORY_COLUMNS",
    "MARKET_IDENTITY_COLUMNS",
    "MAPPED_HISTORY_VALUE",
    "MAPPING_STATUS",
    "REVISION",
    "RISK_DATE",
    "RISK_FILE_NAME",
    "RISK_HISTORY_METADATA_COLUMNS",
    "SNAPSHOT_DATE",
    "PORTFOLIO_AUTHORITY_COLUMNS",
    "RiskArchive",
    "RiskArchiveValidationError",
    "SUCCESS_FILE_NAME",
    "STOCK_ARCHIVE_FILE_NAMES",
    "STOCK_FILE_NAME",
    "archive_from_manager",
    "archive_leaf_path",
    "archive_official_snapshot",
    "build_history_portfolio_authority",
    "build_market_history_loader",
    "clear_archive_caches",
    "list_completed_market_dates",
    "list_completed_v4_archive_days",
    "load_risk_archive",
    "load_risk_history_for_identity",
    "load_full_market_history_for_identity",
    "load_stock_archive_frame",
    "load_market_history_for_identity",
    "load_shared_pl_history",
    "project_archive_to_pl_history",
    "validate_colossus_frame",
    "validate_market_archive_frame",
    "validate_risk_archive_frame",
    "validate_stock_archive_frame",
]
