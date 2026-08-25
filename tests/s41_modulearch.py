"""Meaningful P&L and Stock page-module ownership guards."""

from __future__ import annotations

import ast
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
PAGES = PROJECT / "cube" / "pages"


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
    shell = (pnl / "s07_view.py").read_text(encoding="utf-8")
    summary = (pnl / "s10_summary.py").read_text(encoding="utf-8")
    send = (pnl / "s04_sender.py").read_text(encoding="utf-8")
    assert "def build_pl_page" in shell
    assert "def _pl_aggregate_section" in shell
    assert "def build_pl_summary_table" in summary
    assert "def build_pl_send_sections" not in shell
    assert "def build_pl_send_sections" in send
    assert "def _editor_table" in send
    assert len(shell.splitlines()) < 450
    assert len(send.splitlines()) < 800


def test_stock_projection_history_view_and_callbacks_have_page_owners() -> None:
    stock = PAGES / "stock"
    assert not (stock / "s05_tables.py").exists()
    assert not (stock / "s05_historycallbacks.py").exists()
    expected_symbols = {
        "s01_data.py": (
            "class StockPageData",
            "def load_stock_page_data",
            "def stock_display_rows",
            "def stock_history_identities",
        ),
        "s02_history.py": (
            "class SQLStockHistoryRepository",
            "def build_stock_value_history_figure",
        ),
        "s03_view.py": (
            "def build_stock_page_shell",
            "def build_stock_page_from_data",
            "def build_stock_table",
        ),
        "s04_callbacks.py": (
            "def register_callbacks",
            "def load_current_stock",
            "def render_current_stock",
            "def load_stock_history",
        ),
        "s05_pivot.py": (
            "class StockPivotResult",
            "def build_stock_pivot",
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
