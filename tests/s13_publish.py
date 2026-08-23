"""V4.1 runtime bundle and Plotly publish boundary regression tests."""

from __future__ import annotations

import hashlib
import json
import shutil
import tomllib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import publish as publishing


def _write_fixture_leaf(
    history_root: Path,
    market_date: str,
    *,
    revision: int = 1,
) -> Path:
    leaf = history_root / market_date
    leaf.mkdir(parents=True)
    digests: dict[str, str] = {}
    for file_name in publishing._DETERMINISTIC_HISTORY_FILES:
        payload = f"fixture {market_date} {file_name}\n".encode()
        (leaf / file_name).write_bytes(payload)
        digests[file_name] = hashlib.sha256(payload).hexdigest()
    marker = {
        "schema_version": 4,
        "market_date": market_date,
        "market_status": "OFFICIAL",
        "revision": revision,
        "refreshed_at": f"{market_date}T17:30:00+00:00",
        "risk_rows": 10_000,
        "colossus_rows": 5_000,
        "risk_columns": ["Source Type", "Risk"],
        "colossus_columns": ["Portfolio", "PL"],
        "sha256": digests,
        "fixture": publishing.DETERMINISTIC_HISTORY_FIXTURE,
        "risk_dates": {
            source: market_date for source in publishing._DETERMINISTIC_RISK_SOURCES
        },
        "market_rows": 5_000,
        "market_columns": ["Source Type", "Current"],
        "stock_date": market_date,
        "stock_rows": 5_000,
        "stock_columns": ["CRDS", "Market Value"],
    }
    (leaf / "_SUCCESS").write_text(
        json.dumps(marker, sort_keys=True),
        encoding="utf-8",
    )
    return leaf


def test_project_release_boundary_is_conventional_and_v41_owned() -> None:
    assert publishing.APP_NAME == "rebirth-v4-1"
    assert publishing.RUNTIME_FILES == (
        "app.py",
        "gunicorn.conf.py",
        "requirements.txt",
    )
    assert publishing.RUNTIME_DIRECTORIES == ("rebirth", "assets", "data")
    for relative_path in (*publishing.RUNTIME_FILES, *publishing.RUNTIME_DIRECTORIES):
        assert (publishing.PROJECT / relative_path).exists()
    assert tomllib.loads(publishing.CONFIG.read_text(encoding="utf-8")) == {
        "name": "rebirth-v4-1"
    }


def test_checked_in_history_is_the_exact_262_day_schema_v4_archive() -> None:
    assert len(publishing.EXPECTED_HISTORY_DATES) == 262
    assert publishing.EXPECTED_HISTORY_DATES[0] == "2025-08-21"
    assert publishing.EXPECTED_HISTORY_DATES[-1] == "2026-08-21"
    leaves = publishing._validate_history_archive(publishing.PROJECT / "data" / "histo")
    assert len(leaves) == 262


def test_archive_validation_rejects_partial_corrupt_or_reordered_revisions(
    tmp_path: Path,
) -> None:
    dates = ("2026-08-20", "2026-08-21")
    history = tmp_path / "histo"
    _write_fixture_leaf(history, dates[0], revision=1)
    second = _write_fixture_leaf(history, dates[1], revision=2)
    assert len(publishing._validate_history_archive(history, expected_dates=dates)) == 2

    (second / "risk.parquet").write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="failed validation"):
        publishing._validate_history_archive(history, expected_dates=dates)

    shutil.rmtree(second)
    with pytest.raises(ValueError, match="exactly 2 dated leaves"):
        publishing._validate_history_archive(history, expected_dates=dates)

    _write_fixture_leaf(history, dates[1], revision=1)
    with pytest.raises(ValueError, match="failed validation"):
        publishing._validate_history_archive(history, expected_dates=dates)


def test_stage_bundle_contains_only_the_minimal_v41_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    for name in publishing.RUNTIME_FILES:
        (project / name).write_text(f"{name}\n", encoding="utf-8")
    (project / "rebirth").mkdir()
    (project / "rebirth" / "__init__.py").write_text("", encoding="utf-8")
    (project / "rebirth" / "__pycache__").mkdir()
    (project / "rebirth" / "__pycache__" / "stale.pyc").write_bytes(b"stale")
    (project / "assets").mkdir()
    (project / "assets" / "ui.js").write_text("// ui\n", encoding="utf-8")
    (project / "data").mkdir()
    (project / "data" / "spot.csv").write_text("value\n1\n", encoding="utf-8")
    history_date = "2026-08-21"
    _write_fixture_leaf(project / "data" / "histo", history_date)
    (project / "tests").mkdir()
    (project / "legacy.py").write_text("legacy\n", encoding="utf-8")

    monkeypatch.setattr(publishing, "PROJECT", project)
    monkeypatch.setattr(publishing, "EXPECTED_HISTORY_DATES", (history_date,))
    staged = publishing.stage_bundle(tmp_path / "runtime")

    assert {path.name for path in staged.iterdir()} == {
        *publishing.RUNTIME_FILES,
        *publishing.RUNTIME_DIRECTORIES,
    }
    assert not (staged / "tests").exists()
    assert not (staged / "legacy.py").exists()
    assert not any(staged.rglob("__pycache__"))
    assert (staged / "data" / "histo" / history_date / "_SUCCESS").is_file()


def test_cloud_optimization_preserves_source_rows_and_updates_staged_hashes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    history_date = "2026-08-21"
    source = tmp_path / "source"
    leaf = _write_fixture_leaf(source / "data" / "histo", history_date)
    table = pa.table(
        {
            "Identity": [f"ID-{index % 20:02d}" for index in range(6_001)],
            "Value": [float(index) / 3.0 for index in range(6_001)],
        }
    )
    for file_name in publishing._DETERMINISTIC_HISTORY_FILES:
        pq.write_table(table, leaf / file_name, compression=None, row_group_size=1_000)
    marker_path = leaf / "_SUCCESS"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["sha256"] = {
        name: publishing._file_sha256(leaf / name)
        for name in publishing._DETERMINISTIC_HISTORY_FILES
    }
    marker_path.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")
    original = {
        path.relative_to(source): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    runtime = tmp_path / "runtime"
    shutil.copytree(source, runtime)
    monkeypatch.setattr(publishing, "EXPECTED_HISTORY_DATES", (history_date,))

    publishing._optimize_cloud_history(runtime)

    assert all(
        (source / path).read_bytes() == payload for path, payload in original.items()
    )
    optimized_leaf = runtime / "data" / "histo" / history_date
    optimized_marker = json.loads(
        (optimized_leaf / "_SUCCESS").read_text(encoding="utf-8")
    )
    for file_name in publishing._DETERMINISTIC_HISTORY_FILES:
        path = optimized_leaf / file_name
        parquet = pq.ParquetFile(path)
        assert parquet.metadata.num_rows == len(table)
        assert parquet.metadata.num_row_groups == 1
        assert optimized_marker["sha256"][file_name] == publishing._file_sha256(path)
    assert not list(optimized_leaf.glob(".*.cloud.tmp"))


def test_publish_uses_native_v41_entrypoint_discovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    project = tmp_path / "project"
    project.mkdir()
    config = project / "plotly-cloud.toml"
    config.write_text('name = "rebirth-v4-1"\n', encoding="utf-8")

    def stage(destination: Path) -> Path:
        destination.mkdir(parents=True)
        return destination

    def optimize(staged: Path) -> None:
        captured["optimized"] = staged

    def run(command, *, cwd, check) -> None:
        captured.update(command=command, cwd=cwd, check=check)

    monkeypatch.setattr(publishing, "PROJECT", project)
    monkeypatch.setattr(publishing, "CONFIG", config)
    monkeypatch.setattr(publishing, "stage_bundle", stage)
    monkeypatch.setattr(publishing, "_optimize_cloud_history", optimize)
    monkeypatch.setattr(publishing.subprocess, "run", run)
    publishing.publish(keep_bundle=tmp_path / "kept")

    command = captured["command"]
    assert isinstance(command, list)
    assert command[command.index("--name") + 1] == "rebirth-v4-1"
    assert command[command.index("--project-path") + 1] == str(captured["optimized"])
    assert "--entrypoint-module" not in command
    assert captured["cwd"] == project
    assert captured["check"] is True
