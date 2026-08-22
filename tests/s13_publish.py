"""Deployment-bundle and Plotly Cloud command regression tests."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tomllib
from pathlib import Path

import s03_publish as publishing


def test_stage_bundle_uses_conventional_runtime_names(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_ignore = publishing._deployment_ignore
    history_root = (publishing.PROJECT / "data" / "histo").resolve()

    def skip_large_history(directory: str, names: list[str]) -> set[str]:
        if Path(directory).resolve() == history_root:
            return set(names)
        return original_ignore(directory, names)

    monkeypatch.setattr(publishing, "_deployment_ignore", skip_large_history)
    staged = publishing.stage_bundle(tmp_path / "runtime")

    assert (staged / "app.py").read_bytes() == (
        publishing.PROJECT / "s01_app.py"
    ).read_bytes()
    assert (staged / "gunicorn.conf.py").read_bytes() == (
        publishing.PROJECT / "s04_server.py"
    ).read_bytes()
    assert (staged / "requirements.txt").is_file()
    requirements = (staged / "requirements.txt").read_text(encoding="utf-8")
    assert "tzdata==" in requirements
    for page_module in (
        "__init__.py",
        "not_found_404.py",
    ):
        assert (staged / "pages" / page_module).read_bytes() == (
            publishing.PROJECT / "pages" / page_module
        ).read_bytes()
    assert (staged / "pages" / "risk" / "__init__.py").read_bytes() == (
        publishing.PROJECT / "pages" / "risk" / "__init__.py"
    ).read_bytes()
    assert (staged / "pages" / "static_data" / "__init__.py").read_bytes() == (
        publishing.PROJECT / "pages" / "static_data" / "__init__.py"
    ).read_bytes()
    for page_module in (
        "__init__.py",
        "aggregate_callbacks.py",
        "common.py",
        "editor.py",
        "history.py",
        "history_callbacks.py",
        "send_callbacks.py",
        "validation.py",
        "view.py",
    ):
        assert (staged / "pages" / "pnl" / page_module).read_bytes() == (
            publishing.PROJECT / "pages" / "pnl" / page_module
        ).read_bytes()
    for page_module in ("__init__.py", "callbacks.py", "view.py"):
        assert (staged / "pages" / "stock" / page_module).read_bytes() == (
            publishing.PROJECT / "pages" / "stock" / page_module
        ).read_bytes()
    for shared_module in (
        "__init__.py",
        "aggregation.py",
        "components.py",
        "constants.py",
        "contracts.py",
        "factory.py",
        "saved_views.py",
        "startup.py",
    ):
        assert (staged / "shared" / shared_module).read_bytes() == (
            publishing.PROJECT / "shared" / shared_module
        ).read_bytes()
    for relative_path in (
        Path("adapters/s01_common.py"),
        Path("adapters/s02_ir.py"),
        Path("adapters/s03_fx.py"),
        Path("adapters/s04_credit.py"),
        Path("adapters/s05_stock.py"),
        Path("adapters/s06_new_positions.py"),
        Path("adapters/s07_cross_gamma.py"),
        Path("adapters/s08_commo.py"),
        Path("core/s06_reporting.py"),
        Path("core/s07_stock.py"),
        Path("core/s08_saved_views.py"),
        Path("core/s09_cross_gamma.py"),
        Path("core/s10_new_trades.py"),
        Path("core/s11_risk_archive.py"),
        Path("feeds/s01_sources.py"),
    ):
        assert (staged / relative_path).read_bytes() == (
            publishing.PROJECT / relative_path
        ).read_bytes()
    assert "=== REAL IR CONNECTORS (COMMENTED OUT)" in (
        staged / "adapters" / "s02_ir.py"
    ).read_text(encoding="utf-8")
    assert "=== ACTIVE CSV FALLBACK" in (staged / "feeds" / "s01_sources.py").read_text(
        encoding="utf-8"
    )
    assert (staged / "data" / "histo").is_dir()
    assert not any((staged / "data" / "histo").iterdir())
    assert not any(path.name == "_disabled" for path in staged.rglob("_disabled"))
    assert not any(staged.rglob("*.disabled"))
    assert not (staged / "ui").exists()
    assert not any((staged / "pages").rglob("__pycache__"))
    assert not (staged / "s03_publish.py").exists()
    assert not (staged / "tests").exists()
    assert not (staged / "README.md").exists()


def test_markdown_documents_stay_in_governed_locations() -> None:
    ignored_directories = {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
    }
    markdown_files: list[Path] = []
    for directory, names, files in os.walk(publishing.PROJECT):
        names[:] = sorted(name for name in names if name not in ignored_directories)
        markdown_files.extend(
            (Path(directory) / name).relative_to(publishing.PROJECT)
            for name in files
            if Path(name).suffix.casefold() == ".md"
        )

    allowed_root_files = {
        Path("README.md"),
        Path("rebirth_cohesive_implementation_guide.md"),
        Path("rebirth_full_cold_start_and_performance_guide.md"),
    }
    v3_root = Path("docs/rebirth-v3")
    unexpected = [
        path
        for path in markdown_files
        if path not in allowed_root_files and not path.is_relative_to(v3_root)
    ]

    assert not unexpected
    assert allowed_root_files <= set(markdown_files)
    assert v3_root / "README.md" in markdown_files


def test_v3_readme_local_markdown_links_exist() -> None:
    v3_root = publishing.PROJECT / "docs" / "rebirth-v3"
    index = v3_root / "README.md"
    links = re.findall(r"\[[^]]+\]\(([^)]+)\)", index.read_text(encoding="utf-8"))

    for link in links:
        if link.startswith(("#", "http://", "https://")):
            continue
        relative_target = link.split("#", 1)[0]
        target = (index.parent / relative_target).resolve()
        assert target.is_relative_to(publishing.PROJECT.resolve())
        assert target.is_file(), f"Missing local V3 documentation link: {link}"


def _write_fixture_leaf(
    history_root: Path,
    market_date: str,
    *,
    fixture_tag: str = publishing.DETERMINISTIC_HISTORY_FIXTURE,
    schema_version: int = 4,
) -> Path:
    leaf = history_root / market_date
    leaf.mkdir(parents=True)
    digests: dict[str, str] = {}
    for file_name in (
        "risk.parquet",
        "colossus.parquet",
        "market.parquet",
        "stock.parquet",
    ):
        payload = f"synthetic {market_date} {file_name}\n".encode()
        (leaf / file_name).write_bytes(payload)
        digests[file_name] = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema_version": schema_version,
        "market_date": market_date,
        "market_status": "OFFICIAL",
        "revision": 1,
        "refreshed_at": f"{market_date}T17:30:00+00:00",
        "risk_rows": 10_000,
        "colossus_rows": 5_000,
        "risk_columns": ["Source Type", "Risk"],
        "colossus_columns": ["Portfolio", "PL"],
        "sha256": digests,
        "fixture": fixture_tag,
        "risk_dates": {f"source/{index}": market_date for index in range(16)},
        "market_rows": 5_000,
        "market_columns": ["Source Type", "Current"],
        "stock_date": market_date,
        "stock_rows": 5_000,
        "stock_columns": ["CRDS", "Market Value"],
    }
    (leaf / "_SUCCESS").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return leaf


def test_stage_bundle_includes_only_exact_tagged_v4_history_leaves(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    for source_name in publishing.RUNTIME_FILES:
        source = project / source_name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(f"fixture {source_name}\n", encoding="utf-8")
    for directory_name in publishing.RUNTIME_DIRECTORIES:
        (project / directory_name).mkdir(parents=True, exist_ok=True)
    history = project / "data" / "histo"

    fixture_date = "2026-08-10"
    _write_fixture_leaf(history, fixture_date)
    _write_fixture_leaf(history, "2026-08-11", schema_version=3)
    _write_fixture_leaf(history, "2026-08-12", fixture_tag="runtime-user-data")
    partial = _write_fixture_leaf(history, "2026-08-13")
    (partial / "stock.parquet").unlink()
    corrupt = _write_fixture_leaf(history, "2026-08-14")
    (corrupt / "market.parquet").write_bytes(b"changed")
    _write_fixture_leaf(history, "2026-02-31")
    legacy = history / "2026-08-15"
    legacy.mkdir()
    for name in ("risk.csv", "colossus.csv", "market.csv", "stock.csv"):
        (legacy / name).write_text("legacy\n", encoding="utf-8")
    (legacy / "_SUCCESS").write_text("{}", encoding="utf-8")
    pending = history / ".2026-08-16.pending-test"
    pending.mkdir()
    (pending / "risk.parquet").write_bytes(b"partial")
    notes = history / "notes"
    notes.mkdir()
    (notes / "README.txt").write_text("not a history leaf\n", encoding="utf-8")
    (history / "catalog.txt").write_text("root file\n", encoding="utf-8")

    monkeypatch.setattr(publishing, "PROJECT", project)
    staged = publishing.stage_bundle(tmp_path / "runtime")
    staged_history = staged / "data" / "histo"

    assert {path.name for path in staged_history.iterdir()} == {fixture_date}
    assert {path.name for path in (staged_history / fixture_date).iterdir()} == {
        "risk.parquet",
        "colossus.parquet",
        "market.parquet",
        "stock.parquet",
        "_SUCCESS",
    }


def test_publish_uses_plotly_native_entrypoint_discovery(
    tmp_path: Path, monkeypatch
) -> None:
    captured: dict[str, object] = {}

    def capture(command, *, cwd, check):
        captured.update(command=command, cwd=cwd, check=check)

    def stage_empty_bundle(destination: Path) -> Path:
        destination.mkdir(parents=True)
        return destination

    monkeypatch.setattr(publishing.subprocess, "run", capture)
    monkeypatch.setattr(publishing, "stage_bundle", stage_empty_bundle)
    publishing.publish(keep_bundle=tmp_path)

    command = captured["command"]
    assert isinstance(command, list)
    assert "--entrypoint-module" not in command
    assert command[command.index("--name") + 1] == "rebirth-v3"
    assert captured["cwd"] == publishing.PROJECT
    assert captured["check"] is True


def test_plotly_config_starts_without_an_inherited_application_identity() -> None:
    config = tomllib.loads(publishing.CONFIG.read_text(encoding="utf-8"))

    assert config == {"name": "rebirth-v3"}
