"""Cross-surface visual contracts for expandable hierarchy controls."""

from __future__ import annotations

import re
from pathlib import Path

from rebirth.ui.constants import ROW_TOGGLE_CLOSED_GLYPH, ROW_TOGGLE_OPEN_GLYPH


_ROOT = Path(__file__).resolve().parents[1]


def _stylesheet() -> str:
    return "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((_ROOT / "assets").glob("*.css"))
    )


def test_python_table_toggles_share_one_authoritative_glyph_contract() -> None:
    assert ROW_TOGGLE_OPEN_GLYPH == "−"
    assert ROW_TOGGLE_CLOSED_GLYPH == "▸"

    for relative_path in (
        Path("rebirth/pages/risk/quick_risk.py"),
        Path("rebirth/pages/risk/explorer_tables.py"),
        Path("rebirth/ui/components.py"),
        Path("rebirth/pages/stock/tables.py"),
        Path("rebirth/pages/pnl/history.py"),
    ):
        source = (_ROOT / relative_path).read_text(encoding="utf-8")
        assert "ROW_TOGGLE_OPEN_GLYPH" in source
        assert "ROW_TOGGLE_CLOSED_GLYPH" in source
        assert '"−"' not in source
        assert '"▸"' not in source


def _css_rule(source: str, selector: str) -> str:
    start = source.index(selector)
    opening = source.index("{", start)
    closing = source.index("}", opening)
    return source[opening + 1 : closing]


def test_row_toggles_share_fixed_glyph_geometry() -> None:
    source = _stylesheet()
    rule = _css_rule(
        source,
        ".row-toggle,\n.aggregate-row-toggle,\n.quick-search-hierarchy-toggle",
    )

    for declaration in (
        "width: 20px",
        "height: 20px",
        "margin: 0 6px 0 0",
        "font-family: inherit",
        "font-size: 14px",
        "font-weight: 900",
        "line-height: 1",
    ):
        assert declaration in rule

    spacer = _css_rule(source, ".quick-search-hierarchy-toggle-spacer")
    assert "width: 20px" in spacer
    assert "height: 20px" in spacer
    assert "margin: 0 6px 0 0" in spacer
    assert ".stock-hierarchy-level-label" not in source


def test_table_borders_are_solid_and_hierarchy_uses_width_for_emphasis() -> None:
    stylesheet = _stylesheet()
    semantic_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for root in (_ROOT / "rebirth" / "pages", _ROOT / "pages", _ROOT / "shared")
        for path in sorted(root.rglob("*.py"))
    )
    border_pattern = re.compile(
        r"border[^\n;,]*\b(?:dotted|dashed)\b",
        re.IGNORECASE,
    )

    assert border_pattern.search(stylesheet) is None
    assert border_pattern.search(semantic_sources) is None
    assert "border-top: 2px solid #111111" in stylesheet
    assert "border-top: 1px solid #111111" in stylesheet
    assert "border-left: 2px solid #111111" in stylesheet


def test_dark_theme_styles_date_inputs_and_calendar_surface() -> None:
    stylesheet = _stylesheet()

    for selector in (
        ".SingleDatePickerInput",
        ".DateRangePickerInput",
        ".DateInput_input",
        ".DayPicker_transitionContainer",
        ".CalendarDay__default",
        ".CalendarDay__selected",
    ):
        assert selector in stylesheet
    assert "background: var(--surface-raised) !important" in stylesheet
    assert "color: var(--text) !important" in stylesheet


def test_quick_risk_client_sync_preserves_canonical_disclosure_state() -> None:
    source = (_ROOT / "assets" / "50_risk_events.js").read_text(encoding="utf-8")
    start = source.index("const syncQuickSearchHierarchy")
    end = source.index("const toggleQuickSearchHierarchy", start)
    sync = source[start:end]

    assert 'toggle.textContent = expanded ? "\\u2212" : "\\u25b8";' in sync
    assert 'row.setAttribute("aria-expanded", String(expanded));' in sync
    assert 'toggle.setAttribute("aria-expanded", String(expanded));' in sync
    assert "\\u25be" not in sync
    assert "\\u203a" not in sync
