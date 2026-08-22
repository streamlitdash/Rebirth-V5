"""Meaningful P&L and Stock page-module ownership guards."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
PAGES = PROJECT / "rebirth" / "pages"


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


def test_pnl_shell_and_send_editor_layout_have_distinct_owners() -> None:
    pnl = PAGES / "pnl"
    shell = (pnl / "view.py").read_text(encoding="utf-8")
    send = (pnl / "send_view.py").read_text(encoding="utf-8")
    assert "def build_pl_page" in shell
    assert "def build_pl_aggregate_table" in shell
    assert "def build_pl_send_sections" not in shell
    assert "def build_pl_send_sections" in send
    assert "def _editor_table" in send
    assert len(shell.splitlines()) < 350
    assert 500 < len(send.splitlines()) < 800


def test_stock_data_tables_history_shell_and_callbacks_are_separate() -> None:
    stock = PAGES / "stock"
    expected_symbols = {
        "data.py": ("class StockPageData", "def load_stock_page_data"),
        "tables.py": ("def build_stock_hierarchy", "def build_stock_table"),
        "history.py": (
            "class SQLStockHistoryRepository",
            "def build_stock_history_figure",
        ),
        "view.py": ("def build_stock_page_shell", "def build_stock_page_from_data"),
        "callbacks.py": ("def register_callbacks", "def coordinate_stock_load"),
        "history_callbacks.py": (
            "def register_stock_history_callbacks",
            "def load_stock_history_rows",
        ),
    }
    for filename, symbols in expected_symbols.items():
        source = (stock / filename).read_text(encoding="utf-8")
        for symbol in symbols:
            assert symbol in source, (filename, symbol)
        assert len(source.splitlines()) < 800, filename


def test_final_pages_use_only_canonical_v4_dependencies() -> None:
    forbidden = ("pages", "shared", "core", "adapters", "feeds")
    for owner in ("pnl", "stock"):
        for path in (PAGES / owner).glob("*.py"):
            for module in _imports(path):
                assert not any(
                    module == prefix or module.startswith(f"{prefix}.")
                    for prefix in forbidden
                ), (path.relative_to(PROJECT), module)
