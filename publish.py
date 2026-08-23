"""Validate, stage, and publish the minimal Rebirth V4.1 Plotly runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

import pyarrow as pa
import pyarrow.parquet as pq


PROJECT = Path(__file__).resolve().parent
CONFIG = PROJECT / "plotly-cloud.toml"
APP_NAME = "rebirth-v4-1"
RUNTIME_FILES = ("app.py", "gunicorn.conf.py", "requirements.txt")
RUNTIME_DIRECTORIES = ("rebirth", "assets", "data")
IGNORED_NAMES = (
    "__pycache__",
    "_disabled",
    "*.pyc",
    "*.pyo",
    "*.log",
    ".write.lock",
    ".*.tmp",
)

_HISTORY_START = date(2025, 8, 21)
_HISTORY_END = date(2026, 8, 21)
_HISTORY_DAY_COUNT = 262
_DATE_HISTORY_LEAF = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])")
_DETERMINISTIC_HISTORY_ARTIFACTS = {
    "risk.parquet",
    "colossus.parquet",
    "market.parquet",
    "stock.parquet",
    "_SUCCESS",
}
_DETERMINISTIC_HISTORY_FILES = _DETERMINISTIC_HISTORY_ARTIFACTS - {"_SUCCESS"}
_DETERMINISTIC_HISTORY_ROWS = {
    "risk_rows": 10_000,
    "colossus_rows": 5_000,
    "market_rows": 5_000,
    "stock_rows": 5_000,
}
_DETERMINISTIC_MANIFEST_FIELDS = {
    "schema_version",
    "market_date",
    "market_status",
    "revision",
    "refreshed_at",
    "risk_rows",
    "colossus_rows",
    "risk_columns",
    "colossus_columns",
    "sha256",
    "fixture",
    "risk_dates",
    "market_rows",
    "market_columns",
    "stock_date",
    "stock_rows",
    "stock_columns",
}
_DETERMINISTIC_RISK_SOURCES = {
    "commo/delta",
    "commo/vega",
    "credit/delta",
    "credit/vega",
    "fx/delta",
    "fx/gamma",
    "fx/vega",
    "ir/basis",
    "ir/bond",
    "ir/delta",
    "ir/deltavega",
    "ir/gamma",
    "ir/inflation",
    "ir/inflationvega",
    "ir/xccy",
    "ir/xccyvega",
}
DETERMINISTIC_HISTORY_FIXTURE = "deterministic-rebirth-v4"
_CLOUD_PARQUET_COMPRESSION_LEVEL = 9
_CLOUD_PARQUET_ROW_GROUP_SIZE = 10_000


def _business_dates(start: date, end: date) -> tuple[str, ...]:
    current = start
    result: list[str] = []
    while current <= end:
        if current.weekday() < 5:
            result.append(current.isoformat())
        current += timedelta(days=1)
    return tuple(result)


EXPECTED_HISTORY_DATES = _business_dates(_HISTORY_START, _HISTORY_END)
if len(EXPECTED_HISTORY_DATES) != _HISTORY_DAY_COUNT:
    raise RuntimeError("The configured V4.1 history window must contain 262 weekdays")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_manifest(leaf: Path) -> dict[str, object] | None:
    try:
        value = json.loads((leaf / "_SUCCESS").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _is_deployable_fixture_history_leaf(
    candidate: Path,
    child_names: set[str],
    *,
    expected_revision: int | None = None,
) -> bool:
    """Return whether one archive day matches the immutable schema-v4 fixture."""
    if (
        child_names != _DETERMINISTIC_HISTORY_ARTIFACTS
        or not _DATE_HISTORY_LEAF.fullmatch(candidate.name)
    ):
        return False
    try:
        if date.fromisoformat(candidate.name).isoformat() != candidate.name:
            return False
    except ValueError:
        return False

    manifest = _read_manifest(candidate)
    if manifest is None or set(manifest) != _DETERMINISTIC_MANIFEST_FIELDS:
        return False
    revision = manifest.get("revision")
    if (
        type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 4
        or manifest.get("market_date") != candidate.name
        or manifest.get("stock_date") != candidate.name
        or manifest.get("market_status") != "OFFICIAL"
        or manifest.get("fixture") != DETERMINISTIC_HISTORY_FIXTURE
        or type(revision) is not int
        or revision < 1
        or (expected_revision is not None and revision != expected_revision)
        or not isinstance(manifest.get("refreshed_at"), str)
        or not manifest["refreshed_at"]
        or any(
            manifest.get(field) != rows
            for field, rows in _DETERMINISTIC_HISTORY_ROWS.items()
        )
    ):
        return False
    if any(
        not isinstance(manifest.get(field), list) or not manifest[field]
        for field in (
            "risk_columns",
            "colossus_columns",
            "market_columns",
            "stock_columns",
        )
    ):
        return False

    risk_dates = manifest.get("risk_dates")
    if (
        not isinstance(risk_dates, dict)
        or set(risk_dates) != _DETERMINISTIC_RISK_SOURCES
    ):
        return False
    try:
        if any(
            not isinstance(value, str) or date.fromisoformat(value).isoformat() != value
            for value in risk_dates.values()
        ):
            return False
    except ValueError:
        return False

    digests = manifest.get("sha256")
    if not isinstance(digests, dict) or set(digests) != _DETERMINISTIC_HISTORY_FILES:
        return False
    for file_name in _DETERMINISTIC_HISTORY_FILES:
        expected = digests.get(file_name)
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            return False
        try:
            if _file_sha256(candidate / file_name) != expected:
                return False
        except OSError:
            return False
    return True


def _validate_history_archive(
    history_root: Path,
    *,
    expected_dates: Sequence[str] | None = None,
) -> tuple[Path, ...]:
    """Require the complete deterministic archive; never publish a partial year."""
    if not history_root.is_dir():
        raise FileNotFoundError(f"history archive is missing: {history_root}")
    expected = tuple(expected_dates or EXPECTED_HISTORY_DATES)
    entries = tuple(sorted(history_root.iterdir(), key=lambda path: path.name))
    actual = tuple(path.name for path in entries)
    if actual != expected:
        missing = sorted(set(expected) - set(actual))
        unexpected = sorted(set(actual) - set(expected))
        raise ValueError(
            "V4.1 history must contain exactly "
            f"{len(expected)} dated leaves; missing={missing[:3]}, "
            f"unexpected={unexpected[:3]}"
        )
    for revision, leaf in enumerate(entries, start=1):
        try:
            child_names = {path.name for path in leaf.iterdir()}
        except OSError as error:
            raise ValueError(f"could not inspect V4.1 history leaf: {leaf}") from error
        if not _is_deployable_fixture_history_leaf(
            leaf,
            child_names,
            expected_revision=revision,
        ):
            raise ValueError(f"V4.1 history leaf failed validation: {leaf}")
    return entries


def _deployment_ignore(directory: str, names: list[str]) -> set[str]:
    del directory
    return set(shutil.ignore_patterns(*IGNORED_NAMES)("", names))


def _require_file(relative_path: str) -> Path:
    source = PROJECT / relative_path
    if not source.is_file():
        raise FileNotFoundError(f"required deployment file is missing: {relative_path}")
    return source


def _require_directory(relative_path: str) -> Path:
    source = PROJECT / relative_path
    if not source.is_dir():
        raise FileNotFoundError(
            f"required deployment directory is missing: {relative_path}"
        )
    return source


def stage_bundle(destination: Path) -> Path:
    """Create a validated, minimal Plotly runtime tree at *destination*."""
    sources = {name: _require_file(name) for name in RUNTIME_FILES}
    directories = {name: _require_directory(name) for name in RUNTIME_DIRECTORIES}
    _validate_history_archive(directories["data"] / "histo")

    destination = destination.resolve()
    if destination.exists() and (
        not destination.is_dir() or any(destination.iterdir())
    ):
        raise ValueError(f"deployment destination must be empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        shutil.copy2(source, destination / name)
    for name, source in directories.items():
        shutil.copytree(source, destination / name, ignore=_deployment_ignore)
    _validate_history_archive(destination / "data" / "histo")
    return destination


def _optimize_cloud_history(runtime_root: Path) -> None:
    """Re-encode only the staged Parquet copies and refresh their SHA-256 map."""
    history_root = runtime_root / "data" / "histo"
    leaves = _validate_history_archive(history_root)
    for leaf in leaves:
        marker_path = leaf / "_SUCCESS"
        marker = _read_manifest(leaf)
        if marker is None:
            raise ValueError(f"staged history marker is invalid: {marker_path}")
        digests: dict[str, str] = {}
        for file_name in sorted(_DETERMINISTIC_HISTORY_FILES):
            path = leaf / file_name
            temporary = leaf / f".{file_name}.cloud.tmp"
            try:
                table = pq.read_table(path).replace_schema_metadata()
                dictionary_columns = [
                    field.name
                    for field in table.schema
                    if pa.types.is_string(field.type)
                    or pa.types.is_large_string(field.type)
                    or pa.types.is_boolean(field.type)
                ]
                floating_columns = [
                    field.name
                    for field in table.schema
                    if pa.types.is_floating(field.type)
                ]
                pq.write_table(
                    table,
                    temporary,
                    compression="zstd",
                    compression_level=_CLOUD_PARQUET_COMPRESSION_LEVEL,
                    use_dictionary=dictionary_columns or False,
                    use_byte_stream_split=floating_columns or False,
                    write_statistics=True,
                    version="2.6",
                    data_page_version="2.0",
                    row_group_size=_CLOUD_PARQUET_ROW_GROUP_SIZE,
                )
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
            digests[file_name] = _file_sha256(path)
        marker["sha256"] = digests
        temporary_marker = leaf / "._SUCCESS.cloud.tmp"
        try:
            temporary_marker.write_text(
                json.dumps(marker, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary_marker, marker_path)
        finally:
            temporary_marker.unlink(missing_ok=True)
    _validate_history_archive(history_root)


def _publish_staged(staged: Path) -> None:
    _optimize_cloud_history(staged)
    command = [
        sys.executable,
        "-m",
        "plotly_cloud.cli",
        "app",
        "publish",
        "--project-path",
        str(staged),
        "--config",
        str(CONFIG),
        "--name",
        APP_NAME,
        "--poll-timeout",
        "300",
    ]
    subprocess.run(command, cwd=PROJECT, check=True)


def publish(*, keep_bundle: Path | None = None) -> None:
    """Publish the V4.1 app, retaining an optional bundle for inspection."""
    _require_file(CONFIG.name)
    if keep_bundle is not None:
        _publish_staged(stage_bundle(keep_bundle.resolve() / "runtime"))
        return
    with tempfile.TemporaryDirectory(prefix="rebirth-v4-1-plotly-") as temporary:
        _publish_staged(stage_bundle(Path(temporary) / "runtime"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-bundle",
        type=Path,
        help="keep the staged runtime in this directory for inspection",
    )
    args = parser.parse_args()
    publish(keep_bundle=args.keep_bundle)


if __name__ == "__main__":
    main()
