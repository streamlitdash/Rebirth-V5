"""V4.1 domain/service ownership through ordered implementation modules."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
V4_ROOTS = (
    PROJECT / "rebirth" / "domain",
    PROJECT / "rebirth" / "services",
    PROJECT / "rebirth" / "adapters",
)
FORBIDDEN_IMPORT_ROOTS = {"adapters", "core", "feeds", "shared"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    modules.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    )
    return modules


def test_v4_domain_service_and_adapter_modules_have_descriptive_owners() -> None:
    expected = {
        "domain": {
            "s01_schema.py",
            "s02_products.py",
            "s03_calculations.py",
            "s04_crossgamma.py",
            "s05_newtrades.py",
            "s06_reporting.py",
            "s07_governance.py",
            "s08_pnl.py",
            "s09_stock.py",
            "s10_search.py",
        },
        "services": {
            "s01_snapshots.py",
            "s02_state.py",
            "s03_adjustments.py",
            "s04_savedviews.py",
            "s05_sources.py",
            "s06_refresh.py",
        },
        "adapters": {
            "s01_common.py",
            "s02_ir.py",
            "s03_fx.py",
            "s04_credit.py",
            "s05_commodities.py",
            "s06_crossgamma.py",
            "s07_newpositions.py",
            "s08_stock.py",
        },
    }
    for root in V4_ROOTS:
        actual = {path.name for path in root.glob("*.py") if path.name != "__init__.py"}
        assert actual == expected[root.name]


def test_v4_implementations_never_import_removed_root_packages() -> None:
    for root in V4_ROOTS:
        for path in root.glob("*.py"):
            imported_roots = {module.partition(".")[0] for module in _imports(path)}
            assert not (imported_roots & FORBIDDEN_IMPORT_ROOTS), path.relative_to(
                PROJECT
            )
