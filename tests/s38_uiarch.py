"""V5 shared-UI ownership and page-isolation guards."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
UI_PACKAGE = PROJECT / "cube" / "ui"
FORBIDDEN_ROOTS = {"adapters", "core", "feeds", "pages", "shared"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.add(node.module)
    return imports


def test_shared_ui_has_one_ordered_v5_tree() -> None:
    assert {
        path.name for path in UI_PACKAGE.glob("*.py") if path.name != "__init__.py"
    } == {
        "s01_constants.py",
        "s02_aggregation.py",
        "s03_filters.py",
        "s04_components.py",
    }


def test_v4_ui_never_reaches_into_pages_or_data_sources() -> None:
    for path in UI_PACKAGE.glob("*.py"):
        imported_roots = {module.partition(".")[0] for module in _imports(path)}
        assert not (imported_roots & FORBIDDEN_ROOTS), path.relative_to(PROJECT)


def test_completed_v4_owners_do_not_use_removed_root_packages() -> None:
    roots = (
        PROJECT / "cube" / "app",
        PROJECT / "cube" / "pages" / "risk",
        PROJECT / "cube" / "pages" / "data",
        PROJECT / "cube" / "pages" / "pnl",
        PROJECT / "cube" / "pages" / "static_data",
        PROJECT / "cube" / "pages" / "stock",
    )
    for root in roots:
        for path in root.glob("*.py"):
            imported_roots = {module.partition(".")[0] for module in _imports(path)}
            assert not (imported_roots & FORBIDDEN_ROOTS), path.relative_to(PROJECT)


def test_pages_do_not_import_sibling_page_packages() -> None:
    pages_root = PROJECT / "cube" / "pages"
    for path in pages_root.rglob("*.py"):
        relative = path.relative_to(pages_root)
        owner = relative.parts[0] if len(relative.parts) > 1 else None
        for module in _imports(path):
            if not module.startswith("cube.pages."):
                continue
            imported_owner = module.split(".", maxsplit=3)[2]
            assert owner is not None and imported_owner == owner, (
                relative,
                module,
            )
