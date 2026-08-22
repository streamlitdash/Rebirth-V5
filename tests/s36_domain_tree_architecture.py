"""V4 domain/service ownership without numbered compatibility modules."""

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
            "calculations.py",
            "cross_gamma.py",
            "governance.py",
            "new_trades.py",
            "pnl.py",
            "products.py",
            "reporting.py",
            "risk_views.py",
            "schema.py",
            "search.py",
            "stock.py",
        },
        "services": {
            "adjustments.py",
            "refresh.py",
            "refresh_state.py",
            "saved_views.py",
            "snapshots.py",
            "sources.py",
        },
        "adapters": {
            "commodities.py",
            "common.py",
            "credit.py",
            "cross_gamma.py",
            "fx.py",
            "ir.py",
            "new_positions.py",
            "stock.py",
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
