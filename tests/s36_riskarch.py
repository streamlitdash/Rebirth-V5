"""Ownership guards for the modular V4.1 Risk page."""

from __future__ import annotations

import ast
from pathlib import Path


RISK_PACKAGE = Path(__file__).resolve().parents[1] / "rebirth" / "pages" / "risk"
CALLBACK_OWNERS = {
    "s15_refresh.py": ("refresh-commit-revision", "risk-date-editor"),
    "s14_workspacecallbacks.py": ("aggregate-pl-grid", "quick-market-results"),
    "s07_explorer.py": ("risk-grid", "table-view-tabs"),
}
PRESENTATION_OWNERS = (
    "s08_quickrisk.py",
    "s09_quickmarket.py",
    "s06_explorertables.py",
    "s13_workspacetables.py",
)


def _source(filename: str) -> str:
    return (RISK_PACKAGE / filename).read_text(encoding="utf-8")


def _imported_modules(filename: str) -> set[str]:
    tree = ast.parse(_source(filename))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.add(node.module)
    return modules


def test_risk_callback_facade_only_composes_owned_callback_groups() -> None:
    source = _source("s17_callbacks.py")
    assert "@app.callback" not in source
    assert "clientside_callback" not in source
    for registrar in (
        "register_refresh_callbacks",
        "register_workspace_callbacks",
        "register_explorer_callbacks",
        "register_promotion_callbacks",
    ):
        assert registrar in source
    assert "register_pivot_callbacks" not in source
    assert len(source.splitlines()) < 120


def test_public_page_boundary_keeps_callback_loading_lazy() -> None:
    source = _source("__init__.py")
    tree = ast.parse(source)
    top_level_imports = {
        node.module
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert "s17_callbacks" not in top_level_imports
    assert '__all__ = ["layout", "register_callbacks"]' in source


def test_risk_callback_groups_keep_distinct_component_ownership() -> None:
    for filename, owned_ids in CALLBACK_OWNERS.items():
        source = _source(filename)
        assert len(source.splitlines()) <= 1_200
        for component_id in owned_ids:
            assert component_id in source


def test_risk_presentation_is_split_into_meaningful_owners() -> None:
    for filename in PRESENTATION_OWNERS:
        line_count = len(_source(filename).splitlines())
        assert line_count <= 1_200
    assert not (RISK_PACKAGE / "search.py").exists()
    assert not (RISK_PACKAGE / "tables.py").exists()


def test_risk_modules_do_not_reach_into_other_pages_or_source_adapters() -> None:
    filenames = (*CALLBACK_OWNERS, *PRESENTATION_OWNERS)
    for filename in filenames:
        imported = _imported_modules(filename)
        assert not any(
            module == "pages" or module.startswith("pages.") for module in imported
        )
        assert not any(
            module.startswith("rebirth.pages.")
            and not module.startswith("rebirth.pages.risk")
            for module in imported
        )
        assert not any(
            module == prefix or module.startswith(f"{prefix}.")
            for module in imported
            for prefix in ("adapters", "feeds")
        )


def test_workspace_and_explorer_tab_contracts_remain_ordered() -> None:
    source = _source("s16_view.py")
    workspace_values = (
        'value="aggregate-pl"',
        'value="quick-risk"',
        'value="quick-market"',
        'value="top-promotions"',
    )
    explorer_values = ('value="main"', 'value="alt"')
    assert [source.index(value) for value in workspace_values] == sorted(
        source.index(value) for value in workspace_values
    )
    assert [
        source.index(value, source.index('id="table-view-tabs"'))
        for value in explorer_values
    ] == sorted(
        source.index(value, source.index('id="table-view-tabs"'))
        for value in explorer_values
    )
    assert 'value="custom"' not in source[source.index('id="table-view-tabs"') :]
