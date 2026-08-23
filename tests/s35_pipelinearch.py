"""Final V4.1 pipeline ownership and legacy-boundary guards."""

from pathlib import Path

from rebirth.domain import (
    s03_calculations as calculations,
    s07_governance as governance,
    s02_products as products,
)
from rebirth.services import (
    s06_refresh as refresh,
    s02_state as refresh_state,
    s01_snapshots as snapshots,
)


PROJECT = Path(__file__).resolve().parents[1]
LEGACY_ROOTS = ("adapters", "core", "feeds", "shared")
LEGACY_ROOT_FILES = ("s01_app.py", "s02_config.py", "s03_publish.py", "s04_server.py")
LEGACY_TOOL_FILES = (
    "fixtures.py",
    "manual.py",
    "archive_snapshot.py",
    "benchmark.py",
    "s02_manual.py",
    "s03_archive_official_risk.py",
    "s04_benchmark_v4.py",
)


def test_pipeline_implementations_have_one_v4_owner() -> None:
    assert products.ProductSpec.__module__ == "rebirth.domain.s02_products"
    assert calculations.get_product_pl.__module__ == "rebirth.domain.s03_calculations"
    assert governance.apply_thresholds.__module__ == "rebirth.domain.s07_governance"
    assert snapshots.RefreshSnapshot.__module__ == "rebirth.services.s01_snapshots"
    assert refresh.RiskRefreshManager.__module__ == "rebirth.services.s06_refresh"
    assert issubclass(refresh.RiskRefreshManager, refresh_state._RefreshStateMixin)


def test_legacy_compatibility_boundaries_are_removed() -> None:
    for directory in LEGACY_ROOTS:
        legacy_root = PROJECT / directory
        assert not list(legacy_root.glob("*.py")), directory
        assert not (legacy_root / "__init__.py").exists(), directory
    for filename in LEGACY_ROOT_FILES:
        assert not (PROJECT / filename).exists(), filename
    for filename in LEGACY_TOOL_FILES:
        assert not (PROJECT / "tools" / filename).exists(), filename

    assert (PROJECT / "app.py").is_file()
    assert (PROJECT / "publish.py").is_file()
    assert (PROJECT / "gunicorn.conf.py").is_file()
    assert {path.name for path in (PROJECT / "tools").glob("*.py")} == {
        "__init__.py",
        "s01_fixtures.py",
        "s02_archive.py",
        "s03_benchmark.py",
    }
