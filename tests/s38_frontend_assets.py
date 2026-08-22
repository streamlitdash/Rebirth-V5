"""Deterministic ownership and content parity for the V4 frontend assets."""

from __future__ import annotations

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
CSS_FILES = (
    "10_shared_shell.css",
    "20_controls_tables.css",
    "30_risk_workspace.css",
    "40_pnl_tables.css",
    "50_shared_responsive.css",
    "60_data_and_visuals.css",
    "70_data_history.css",
    "80_risk_pivot.css",
)
JS_FILES = (
    "10_data_playback.js",
    "20_shell_theme.js",
    "30_table_interactions.js",
    "40_refresh_lifecycle.js",
    "50_risk_events.js",
    "60_pnl_selection.js",
)


def _read(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def test_assets_have_one_clean_deterministic_v4_manifest() -> None:
    assert tuple(path.name for path in sorted(ASSETS.glob("*.css"))) == CSS_FILES
    assert tuple(path.name for path in sorted(ASSETS.glob("*.js"))) == JS_FILES
    assert not any(path.name.startswith("s0") for path in ASSETS.iterdir())
    assert not (ASSETS / "s01_style.css").exists()
    assert not (ASSETS / "s02_app.js").exists()


def test_css_split_is_byte_for_byte_equivalent_to_the_v4_monolith() -> None:
    combined = "".join(_read(name) for name in CSS_FILES)
    assert len(combined) == 83_656
    assert hashlib.sha256(combined.encode()).hexdigest() == (
        "7e23ece30047af614b67b38c77e002ed50edb1c843b9561ecb0e09ea2aff83a7"
    )
    assert combined.count("{") == combined.count("}")


def test_javascript_behaviors_have_one_page_or_shared_owner() -> None:
    sources = {name: _read(name) for name in JS_FILES}
    ownership = {
        "const dataHistoryFigure": "10_data_playback.js",
        "const dataPlayback = (": "10_data_playback.js",
        "const dataProjectionBase": "10_data_playback.js",
        "const dataProjectionSlice": "10_data_playback.js",
        "const registerCubeRollers": "20_shell_theme.js",
        "const applyTheme": "20_shell_theme.js",
        "const setGlobalLoaderVisible": "20_shell_theme.js",
        "const selectedCellsAsTsv": "30_table_interactions.js",
        "const attachResizeHandles": "30_table_interactions.js",
        "const syncUiHooks": "30_table_interactions.js",
        "const startRefreshProgress": "40_refresh_lifecycle.js",
        "const finishRefreshProgress": "40_refresh_lifecycle.js",
        "const syncRefreshStatusObserver": "40_refresh_lifecycle.js",
        "const refreshProgressPoll": "40_refresh_lifecycle.js",
        "const syncQuickSearchHierarchy": "50_risk_events.js",
        "const publishRiskAction": "50_risk_events.js",
        "const metricCellFromTarget": "50_risk_events.js",
        "const dispatchNativeSelectionClick": "60_pnl_selection.js",
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
    ):
        assert combined.count(behavior) == 1


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
    assert line_counts["40_refresh_lifecycle.js"] < 1_200
    assert line_counts["10_data_playback.js"] < 650
    assert all(
        count < 600
        for name, count in line_counts.items()
        if name not in {"10_data_playback.js", "40_refresh_lifecycle.js"}
    )
    assert all(len(_read(name).splitlines()) < 700 for name in CSS_FILES)
