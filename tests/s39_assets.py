"""Deterministic ownership and content integrity for V4.1 frontend assets."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
CSS_FILES = (
    "s01_shell.css",
    "s02_controls.css",
    "s03_risk.css",
    "s04_pnl.css",
    "s05_responsive.css",
    "s06_visuals.css",
    "s07_history.css",
    "s08_pivot.css",
)
JS_FILES = (
    "s09_playback.js",
    "s10_theme.js",
    "s11_tables.js",
    "s12_refresh.js",
    "s13_risk.js",
    "s14_pnl.js",
)


def _read(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def test_assets_have_one_clean_ordered_v41_manifest() -> None:
    assert tuple(path.name for path in sorted(ASSETS.glob("*.css"))) == CSS_FILES
    assert tuple(path.name for path in sorted(ASSETS.glob("*.js"))) == JS_FILES


def test_css_manifest_has_stable_integrity() -> None:
    combined = "".join(_read(name) for name in CSS_FILES)
    assert len(combined) == 87_434
    assert hashlib.sha256(combined.encode()).hexdigest() == (
        "f2f755160c1497710f0fdd188f3672eb5cbb653cb8872739b21592ee8daa7656"
    )
    assert combined.count("{") == combined.count("}")


def test_javascript_behaviors_have_one_page_or_shared_owner() -> None:
    sources = {name: _read(name) for name in JS_FILES}
    ownership = {
        "const dataHistoryFigure": "s09_playback.js",
        "const dataPlayback = (": "s09_playback.js",
        "const dataProjectionBase": "s09_playback.js",
        "const dataProjectionSlice": "s09_playback.js",
        "const registerCubeRollers": "s10_theme.js",
        "const applyTheme": "s10_theme.js",
        "const setGlobalLoaderVisible": "s10_theme.js",
        "const selectedCellsAsTsv": "s11_tables.js",
        "const attachResizeHandles": "s11_tables.js",
        "const syncUiHooks": "s11_tables.js",
        "const startRefreshProgress": "s12_refresh.js",
        "const finishRefreshProgress": "s12_refresh.js",
        "const syncRefreshStatusObserver": "s12_refresh.js",
        "const refreshProgressPoll": "s12_refresh.js",
        "const syncQuickSearchHierarchy": "s13_risk.js",
        "const publishRiskAction": "s13_risk.js",
        "const metricCellFromTarget": "s13_risk.js",
        "const dispatchNativeSelectionClick": "s14_pnl.js",
    }
    combined = "\n".join(sources.values())
    for anchor, owner in ownership.items():
        assert anchor in sources[owner]
        assert combined.count(anchor) == 1

    for behavior in (
        'event.code === "F9"',
        'event.code === "F8"',
        'refreshTrigger.id === "clear-cache-button"',
        'setProps("data-player-visibility-store"',
        'window.addEventListener("pagehide"',
        '"#risk-custom-grid .row-toggle',
        'children: "Recalculating…"',
        'setProps("data-settings-status"',
    ):
        assert combined.count(behavior) == 1


def test_dark_semantic_tokens_keep_status_and_financial_rules_readable() -> None:
    shell = _read("s01_shell.css")
    tables = _read("s02_controls.css")

    assert "--negative: #FF9B91;" in shell
    assert "--negative-on-pastel: #8A1510;" in shell
    assert "--semantic-rule: #DDE3EA;" in shell
    assert "2px solid var(--semantic-rule)" in tables
    assert "color: var(--negative-on-pastel)" in tables


def test_each_script_has_basic_delimiter_integrity() -> None:
    for name in JS_FILES:
        source = _read(name)
        assert source.startswith("/*")
        assert source.rstrip().endswith("})();")
        assert source.count("{") == source.count("}")
        assert source.count("(") == source.count(")")
        assert source.count("[") == source.count("]")


def test_asset_slices_remain_compact_except_for_refresh_state_machine() -> None:
    line_counts = {name: len(_read(name).splitlines()) for name in JS_FILES}
    assert line_counts["s12_refresh.js"] < 1_200
    assert line_counts["s09_playback.js"] < 650
    assert all(
        count < 600
        for name, count in line_counts.items()
        if name not in {"s09_playback.js", "s12_refresh.js"}
    )
    assert all(len(_read(name).splitlines()) < 700 for name in CSS_FILES)
