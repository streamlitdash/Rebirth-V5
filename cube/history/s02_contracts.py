"""Flat, atomic archives for one official Risk Explorer snapshot per date.

The archive deliberately stores the committed dashboard frame without turning
it into a hierarchy.  A reader can rebuild the Risk Explorer hierarchy at
display time.  Colossus P&L is stored at its separate, explicit four-key grain;
it is never copied across tenor or Product rows. Canonical schema-v4 leaves use
compressed Parquet; schema-v1/v2/v3 CSV leaves remain fully readable.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

import numpy as np
import pandas as pd

from cube.domain.s01_schema import (
    TENOR_OPTION,
    TENOR_OPTION_ORDER,
    TENOR_SWAP,
    TENOR_SWAP_ORDER,
)
from cube.domain.s02_products import PRODUCT_SPECS_BY_SOURCE_TYPE
from cube.domain.s10_search import (
    CURRENT,
    MARKET_DATA_STATUS,
    MARKET_RESULT_COLUMNS,
    MARKET_STATUS,
    OPEN,
    SOURCE_TYPE,
)
from cube.domain.s08_pnl import (
    ACTIVITY,
    CATEGORY,
    HISTORY_MAPPING_STATUS,
    MARKET_DATE,
    PL,
    PRODUCT,
    RISK_GREEK,
    RISK_TYPE,
    SIGNOFF_GROUP,
    SUB_CATEGORY,
    UNDERLYING,
)
from cube.domain.s09_stock import (
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


__all__ = [
    "ALL_ARCHIVE_FILE_NAMES",
    "ARCHIVE_FILE_NAMES",
    "ARCHIVE_SCHEMA_VERSION",
    "ArchiveResult",
    "BASE_ARCHIVE_FILE_NAMES",
    "COLOSSUS_COLUMNS",
    "COLOSSUS_FILE_NAME",
    "COLOSSUS_KEY",
    "ColossusLoader",
    "CompletedArchiveDay",
    "MARKET_ARCHIVE_COLUMNS",
    "MARKET_FILE_NAME",
    "MARKET_HISTORY_COLUMNS",
    "MARKET_IDENTITY_COLUMNS",
    "MAPPED_HISTORY_VALUE",
    "MAPPING_STATUS",
    "PORTFOLIO",
    "PORTFOLIO_AUTHORITY_COLUMNS",
    "REVISION",
    "RISK",
    "RISK_DATE",
    "DRISK",
    "RISK_FILE_NAME",
    "RISK_HISTORY_METADATA_COLUMNS",
    "RISK_PROJECTION_COLUMNS",
    "RiskArchive",
    "RiskArchiveValidationError",
    "SNAPSHOT_DATE",
    "STOCK_ARCHIVE_FILE_NAMES",
    "STOCK_FILE_NAME",
    "SUCCESS_FILE_NAME",
    "archive_leaf_path",
    "validate_colossus_frame",
    "validate_market_archive_frame",
    "validate_risk_archive_frame",
    "validate_stock_archive_frame",
]
