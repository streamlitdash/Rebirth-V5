"""Final V4.1 page-tree ownership with no compatibility package."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
V4_PAGES = PROJECT / "rebirth" / "pages"
LEGACY_PAGES = PROJECT / "pages"
PAGE_OWNERS = ("risk", "data", "stock", "pnl", "static_data")


def _absolute_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
    )
    return imports


def test_pages_have_one_v4_owner_and_no_legacy_tree() -> None:
    assert (V4_PAGES / "s01_notfound.py").is_file()
    assert not LEGACY_PAGES.exists()
    for owner in PAGE_OWNERS:
        assert (V4_PAGES / owner / "__init__.py").is_file()


def test_v4_pages_do_not_import_legacy_or_sibling_pages() -> None:
    for owner in PAGE_OWNERS:
        for path in (V4_PAGES / owner).glob("*.py"):
            for module in _absolute_imports(path):
                assert module != "pages" and not module.startswith("pages."), (
                    path.relative_to(PROJECT),
                    module,
                )
                if module.startswith("rebirth.pages."):
                    assert module.startswith(f"rebirth.pages.{owner}"), (
                        path.relative_to(PROJECT),
                        module,
                    )


def test_app_composition_imports_pages_only_from_v4_tree() -> None:
    for relative in ("app/s07_factory.py", "app/s06_routing.py"):
        imports = _absolute_imports(PROJECT / "rebirth" / relative)
        assert not any(
            module == "pages" or module.startswith("pages.") for module in imports
        )
        assert any(module.startswith("rebirth.pages") for module in imports)


def test_no_python_or_notebook_imports_root_pages_package() -> None:
    checked = [*PROJECT.rglob("*.py"), *PROJECT.rglob("*.ipynb")]
    legacy_from = "from " + "pages"
    legacy_import = "import " + "pages"
    for path in checked:
        if any(part in {".git", "__pycache__"} for part in path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        assert legacy_from not in source, path.relative_to(PROJECT)
        assert legacy_import not in source, path.relative_to(PROJECT)
