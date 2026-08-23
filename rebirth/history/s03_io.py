"""Atomic archive persistence, manifest validation, and date discovery."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from rebirth.domain.s03_calculations import market_date_for
from rebirth.domain.s09_stock import STOCK_COLUMNS, STOCK_IDENTITY_COLUMNS

from .s02_contracts import (
    ARCHIVE_SCHEMA_VERSION,
    ArchiveResult,
    COLOSSUS_COLUMNS,
    COLOSSUS_FILE_NAME,
    ColossusLoader,
    CompletedArchiveDay,
    MARKET_ARCHIVE_COLUMNS,
    MARKET_FILE_NAME,
    OFFICIAL,
    OfficialSnapshot,
    RISK_FILE_NAME,
    RISK_PROJECTION_COLUMNS,
    RiskArchive,
    RiskArchiveValidationError,
    STOCK_FILE_NAME,
    SUCCESS_FILE_NAME,
    _CSV_STOCK_FILE_NAME,
    _DATE_PATTERN,
    _MARKET_SCHEMA_VERSIONS,
    _PARQUET_COMPRESSION,
    _PARQUET_COMPRESSION_LEVEL,
    _PARQUET_ROW_GROUP_SIZE,
    _SHA256_PATTERN,
    _STOCK_SCHEMA_VERSIONS,
    _SUPPORTED_ARCHIVE_SCHEMA_VERSIONS,
    _V3_FIXTURE_TAG,
    _V4_FIXTURE_TAG,
    _VERSIONED_METADATA_SCHEMA_VERSIONS,
    _archive_file_name,
    _archive_file_names,
    _manifest_versioned_metadata,
    _normalize_date,
    _snapshot_versioned_metadata,
    _source_types_in_risk,
    _uses_parquet,
    archive_leaf_path,
    validate_colossus_frame,
    validate_market_archive_frame,
    validate_risk_archive_frame,
    validate_stock_archive_frame,
)


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
    verify_digests: bool,
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
            if verify_digests:
                try:
                    digest = _file_sha256(path)
                except OSError as exc:
                    raise RiskArchiveValidationError(
                        f"Could not hash completed archive file {path}: {exc}"
                    ) from exc
                if digest != digests[file_name]:
                    raise RiskArchiveValidationError(
                        "Risk archive file does not match its completion marker: "
                        f"{path}"
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
    return _completed_v4_archive_days_cached(str(directory), signature, True)


def list_queryable_v4_archive_days(
    root: str | Path,
) -> tuple[CompletedArchiveDay, ...]:
    """Return schema-checked V4 leaves for optional interactive history.

    The interactive path validates completion manifests, file presence, Parquet
    schemas, and row counts once per generation. Expensive whole-file digest
    verification remains authoritative in ``list_completed_v4_archive_days``
    and the publish/test gates, so an optional Data-page query cannot delay app
    startup merely to repeat those checks.
    """

    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Risk archive root must be a directory: {directory}"
        )
    signature = _completed_archive_root_signature(directory)
    return _completed_v4_archive_days_cached(str(directory), signature, False)


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


__all__ = [
    "archive_from_manager",
    "archive_official_snapshot",
    "list_completed_market_dates",
    "list_completed_v4_archive_days",
    "list_queryable_v4_archive_days",
    "load_risk_archive",
    "load_stock_archive_frame",
]
