"""Stage the Rebirth V3 runtime and publish it with the Plotly Cloud CLI.

The repository keeps ``s01_app.py`` and ``s04_server.py`` as its canonical
sources.  Plotly's conventional filenames are created only inside a temporary
deployment directory; no forwarding modules are checked in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path


PROJECT = Path(__file__).resolve().parent
CONFIG = PROJECT / "plotly-cloud.toml"

RUNTIME_FILES = {
    "s01_app.py": "app.py",
    "s02_config.py": "s02_config.py",
    "s04_server.py": "gunicorn.conf.py",
    "requirements.txt": "requirements.txt",
}
RUNTIME_DIRECTORIES = (
    "adapters",
    "assets",
    "core",
    "data",
    "feeds",
    "pages",
    "shared",
)
IGNORED_NAMES = (
    "__pycache__",
    "_disabled",
    "*.pyc",
    "*.pyo",
    "*.log",
    ".write.lock",
    ".*.tmp",
)
_DETERMINISTIC_HISTORY_ARTIFACTS = {
    "risk.parquet",
    "colossus.parquet",
    "market.parquet",
    "stock.parquet",
    "_SUCCESS",
}
_DETERMINISTIC_HISTORY_ROWS = {
    "risk_rows": 10_000,
    "colossus_rows": 5_000,
    "market_rows": 5_000,
    "stock_rows": 5_000,
}
_DETERMINISTIC_HISTORY_FILES = _DETERMINISTIC_HISTORY_ARTIFACTS - {"_SUCCESS"}
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
DETERMINISTIC_HISTORY_FIXTURE = "deterministic-rebirth-v4"
_DATE_HISTORY_LEAF = re.compile(r"\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])")
_PENDING_HISTORY_LEAF = re.compile(
    r"\.\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])\.pending-.+"
)


def _is_deployable_fixture_history_leaf(
    candidate: Path,
    child_names: set[str],
) -> bool:
    """Allow only exact schema-v4 leaves from the deterministic generator."""

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

    marker = candidate / "_SUCCESS"
    try:
        manifest = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if (
        not isinstance(manifest, dict)
        or set(manifest) != _DETERMINISTIC_MANIFEST_FIELDS
    ):
        return False
    if (
        type(manifest.get("schema_version")) is not int
        or manifest["schema_version"] != 4
        or manifest.get("market_date") != candidate.name
        or manifest.get("stock_date") != candidate.name
        or manifest.get("market_status") != "OFFICIAL"
        or manifest.get("fixture") != DETERMINISTIC_HISTORY_FIXTURE
        or type(manifest.get("revision")) is not int
        or manifest["revision"] < 1
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
    if not isinstance(risk_dates, dict) or len(risk_dates) != 16:
        return False
    try:
        if any(
            not isinstance(source, str)
            or not source
            or not isinstance(value, str)
            or date.fromisoformat(value).isoformat() != value
            for source, value in risk_dates.items()
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
        digest = hashlib.sha256()
        try:
            with (candidate / file_name).open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
        except OSError:
            return False
        if digest.hexdigest() != expected:
            return False
    return True


def _deployment_ignore(directory: str, names: list[str]) -> set[str]:
    """Exclude caches and runtime-only official history date directories."""

    ignored = set(shutil.ignore_patterns(*IGNORED_NAMES)(directory, names))
    current = Path(directory).resolve()
    history_root = (PROJECT / "data" / "histo").resolve()
    if current != history_root:
        return ignored
    for name in names:
        candidate = current / name
        if _PENDING_HISTORY_LEAF.fullmatch(name):
            ignored.add(name)
            continue
        if not candidate.is_dir() or not _DATE_HISTORY_LEAF.fullmatch(name):
            ignored.add(name)
            continue
        try:
            child_names = {path.name for path in candidate.iterdir()}
        except OSError:
            # A scheduler may atomically rename its temporary leaf while the
            # bundle is staged. Omitting that transient entry is always safe.
            ignored.add(name)
            continue
        if not _is_deployable_fixture_history_leaf(candidate, child_names):
            ignored.add(name)
    return ignored


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
    """Create a minimal, self-contained Plotly runtime tree at *destination*."""
    destination = destination.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError(f"deployment destination must be empty: {destination}")
    destination.mkdir(parents=True, exist_ok=True)

    for source_name, staged_name in RUNTIME_FILES.items():
        shutil.copy2(_require_file(source_name), destination / staged_name)

    for directory_name in RUNTIME_DIRECTORIES:
        shutil.copytree(
            _require_directory(directory_name),
            destination / directory_name,
            ignore=_deployment_ignore,
        )

    return destination


def publish(*, keep_bundle: Path | None = None) -> None:
    """Publish a new app or update the app recorded by Plotly after first use."""
    _require_file(CONFIG.name)

    if keep_bundle is None:
        context = tempfile.TemporaryDirectory(prefix="rebirth-plotly-")
        temporary_root = Path(context.__enter__())
    else:
        context = None
        temporary_root = keep_bundle.resolve()

    try:
        staged = stage_bundle(temporary_root / "runtime")
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
            "rebirth-v3",
            "--poll-timeout",
            "300",
        ]
        subprocess.run(command, cwd=PROJECT, check=True)
    finally:
        if context is not None:
            context.__exit__(None, None, None)


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
