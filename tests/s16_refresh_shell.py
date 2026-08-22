"""Persistent refresh lifecycle checks for native Dash Pages."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from dash import no_update
from rebirth.services.sources import build_production_refresh_manager
from rebirth.pages.risk import refresh_callbacks as risk_callbacks
from rebirth.pages.risk import state as risk_state
from rebirth.app.startup import STARTUP_COORDINATOR_CONFIG_KEY
from rebirth.ui.components import (
    build_initial_load_layout,
    build_shared_refresh_shell,
)
from rebirth.app.factory import build_app


def _walk(component: object) -> Iterable[object]:
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    else:
        yield from _walk(children)


def _by_id(component: object, component_id: str) -> object:
    return next(
        item for item in _walk(component) if getattr(item, "id", None) == component_id
    )


def _callback_outputs(metadata: dict) -> list[object]:
    output = metadata["output"]
    return list(output) if isinstance(output, (list, tuple)) else [output]


def _callback_for_output(app, component_id: str, component_property: str) -> dict:
    return next(
        metadata
        for metadata in app.callback_map.values()
        if any(
            output.component_id == component_id
            and output.component_property == component_property
            for output in _callback_outputs(metadata)
        )
    )


def test_shared_shell_has_neutral_bootstrap_and_error_modes() -> None:
    neutral = build_shared_refresh_shell(
        None,
        refresh_enabled=True,
        initial_loading=False,
        style={"display": "none"},
    )
    assert neutral.id == "shared-refresh-shell"
    assert neutral.style == {"display": "none"}
    assert _by_id(neutral, "refresh-status").className == "refresh-status"
    assert _by_id(neutral, "refresh-progress").hidden is True
    assert _by_id(neutral, "shared-refresh-bootstrap-interval").disabled is True
    assert _by_id(neutral, "commo-market-toggle").children == "Commo: Off"
    assert _by_id(neutral, "risk-checker-toggle").children == "RiskChecker: On"
    assert _by_id(neutral, "auto-refresh-toggle").children == "AutoPL: On"
    action_ids = [
        component_id
        for item in _walk(_by_id(neutral, "refresh-control-strip"))
        if isinstance((component_id := getattr(item, "id", None)), str)
    ]
    assert action_ids.index("clear-cache-button") + 1 == action_ids.index(
        "theme-toggle"
    )
    assert _by_id(neutral, "clear-cache-button").title.startswith("Ready")
    assert _by_id(neutral, "reset-generation-store").data == 0
    assert _by_id(neutral, "clear-cache-complete-store").data == 0
    assert _by_id(neutral, "refresh-busy-store").data is False

    loading = build_shared_refresh_shell(
        None,
        refresh_enabled=True,
        initial_loading=True,
    )
    assert "is-refreshing" in _by_id(loading, "refresh-status").className
    assert _by_id(loading, "refresh-progress").hidden is False
    assert _by_id(loading, "shared-refresh-bootstrap-interval").disabled is False

    stalled = build_shared_refresh_shell(
        None,
        refresh_enabled=True,
        initial_error="Connector is still running",
        keep_polling=True,
    )
    assert "is-error" in _by_id(stalled, "refresh-status").className
    assert _by_id(stalled, "error-log").children == "Connector is still running"
    assert _by_id(stalled, "shared-refresh-bootstrap-interval").disabled is False

    committed = SimpleNamespace(
        revision=4,
        refreshed_at=datetime.now(timezone.utc),
        forced_dates={},
        forced_view_date=None,
        market_date=pd.Timestamp("2026-08-14"),
        market_status="ready",
        risk_dates={"ir/delta": pd.Timestamp("2026-08-14")},
        commodity_market_enabled=False,
        risk_checker_enabled=True,
        risk_status=pd.DataFrame({"Age": [0], "Force Risk": [False]}),
    )
    deferred = build_shared_refresh_shell(
        committed,
        refresh_enabled=True,
        data_revision=2,
        reset_generation=7,
    )
    assert _by_id(deferred, "data-revision-store").data == 2
    assert _by_id(deferred, "reset-generation-store").data == 7
    assert _by_id(deferred, "clear-cache-complete-store").data == 7
    assert _by_id(deferred, "refresh-commit-revision").children == 4


def test_clear_cache_reuses_the_refresh_progress_lifecycle() -> None:
    assets = Path(__file__).parents[1] / "assets"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(assets.glob("*.js"))
    )

    assert 'refreshTrigger.id === "clear-cache-button" ? "reset"' in source
    assert 'clearButton.textContent = "Resetting…"' in source
    assert '"Clear Cache · Retry"' in source
    assert '"Ready · Clear cached views and reload Risk and P&L"' in source


def test_clear_cache_callback_publishes_generation_and_clears_date_state(
    monkeypatch,
) -> None:
    manager = build_production_refresh_manager()
    baseline = manager.refresh(force_risk=True, force_pl=True)
    manager.refresh(
        forced_dates={"ir/delta": baseline.risk_dates["ir/delta"]},
        view_date=baseline.market_date,
        commodity_market_enabled=baseline.commodity_market_enabled,
        risk_checker_enabled=baseline.risk_checker_enabled,
    )
    app = build_app(refresh_manager=manager)
    callback = _callback_for_output(app, "refresh-commit-revision", "children")[
        "callback"
    ].__wrapped__
    monkeypatch.setattr(
        risk_callbacks,
        "ctx",
        SimpleNamespace(
            triggered_id="clear-cache-button",
            triggered_prop_ids={"clear-cache-button.n_clicks": "clear-cache-button"},
        ),
    )

    result = callback(0, 0, 0, 0, 0, 1, 0, 0, {}, True, 4, 0)

    assert len(result) == 9
    assert result[0] == manager.health.revision
    assert result[1] == 5
    assert str(result[2]).startswith("Ready · Cache cleared")
    assert result[3:5] == ("", "error-log")
    assert result[5:7] == ({}, None)
    assert result[7:] == (1, 1)
    assert manager.snapshot.forced_dates == {}
    assert manager.snapshot.forced_view_date is None


def test_cold_risk_body_can_exclude_every_shared_lifecycle_id() -> None:
    page = build_initial_load_layout(include_shared_refresh_shell=False)
    page_ids = {getattr(item, "id", None) for item in _walk(page)}
    assert {
        "initial-load-trigger",
        "initial-load-retry",
        "initial-load-message",
    } <= page_ids
    assert {
        "shared-refresh-shell",
        "data-revision-store",
        "refresh-commit-revision",
        "refresh-control-strip",
        "refresh-progress",
        "refresh-busy-store",
        "error-log",
        "auto-refresh-interval",
        "shared-refresh-bootstrap-interval",
    }.isdisjoint(page_ids)

    # The default remains a standalone-compatible composition for existing
    # callers that do not mount a factory-level shell.
    standalone = build_initial_load_layout()
    standalone_ids = [getattr(item, "id", None) for item in _walk(standalone)]
    assert standalone_ids.count("shared-refresh-shell") == 1
    assert standalone_ids.count("refresh-progress") == 1


def test_startup_page_and_shared_shell_have_independent_callback_outputs() -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    page_callback = _callback_for_output(app, "cube-page-container", "children")
    shell_callback = _callback_for_output(app, "shared-refresh-shell", "children")
    refresh_callback = _callback_for_output(app, "refresh-commit-revision", "children")
    refresh_registration = next(
        registration
        for registration in app._callback_list
        if "refresh-commit-revision.children" in registration["output"]
    )

    assert page_callback is not shell_callback
    assert [
        (output.component_id, output.component_property)
        for output in _callback_outputs(page_callback)
    ] == [("cube-page-container", "children")]
    assert [
        (output.component_id, output.component_property)
        for output in _callback_outputs(shell_callback)
    ] == [("shared-refresh-shell", "children")]
    assert {(item["id"], item["property"]) for item in shell_callback["inputs"]} == {
        ("initial-load-trigger", "n_intervals"),
        ("initial-load-retry", "n_clicks"),
        ("pnl-initial-load-trigger", "n_intervals"),
        ("shared-refresh-bootstrap-interval", "n_intervals"),
    }
    assert all(
        item.get("allow_optional") is True
        for item in shell_callback["inputs"]
        if item["id"]
        in {
            "initial-load-trigger",
            "initial-load-retry",
            "pnl-initial-load-trigger",
        }
    )
    force_apply = next(
        item
        for item in refresh_callback["inputs"]
        if item["id"] == "force-risk-apply-button"
    )
    assert force_apply.get("allow_optional") is True
    assert ("clear-cache-button", "n_clicks") in {
        (item["id"], item["property"]) for item in refresh_callback["inputs"]
    }
    assert refresh_registration["running"]["running"]["refresh-busy-store.data"] is True
    assert (
        refresh_registration["running"]["runningOff"]["refresh-busy-store.data"]
        is False
    )
    assert (
        refresh_registration["running"]["running"]["clear-cache-button.disabled"]
        is True
    )

    draft_callback = _callback_for_output(app, "force-risk-draft-store", "data")
    draft_mount = next(
        item for item in draft_callback["inputs"] if item["id"] == "risk-date-editor"
    )
    assert draft_mount.get("allow_optional") is True

    actions_callback = _callback_for_output(app, "force-risk-edit-status", "children")
    actions_mount = next(
        item
        for item in actions_callback["inputs"]
        if item["id"] == "force-risk-apply-button" and item["property"] == "id"
    )
    assert actions_mount.get("allow_optional") is True
    assert ("refresh-busy-store", "data") in {
        (item["id"], item["property"]) for item in actions_callback["inputs"]
    }


def test_financial_page_tick_hands_polling_to_the_persistent_shell(monkeypatch) -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    coordinator = app.server.config[STARTUP_COORDINATOR_CONFIG_KEY]
    monkeypatch.setattr(coordinator, "start", lambda **_kwargs: False)
    monkeypatch.setattr(
        risk_callbacks,
        "ctx",
        SimpleNamespace(triggered_id="initial-load-trigger"),
    )
    callback = _callback_for_output(
        app,
        "shared-refresh-shell",
        "children",
    )["callback"].__wrapped__

    children = callback(1, 0, 0, 0, "refresh-status is-refreshing", "", 0)
    shell = SimpleNamespace(children=children)

    assert _by_id(shell, "shared-refresh-bootstrap-interval").disabled is False


def test_force_actions_disable_for_busy_and_clean_states() -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    app = build_app(refresh_manager=manager)
    metadata = _callback_for_output(app, "force-risk-edit-status", "children")
    callback = metadata["callback"].__wrapped__
    snapshot = manager.control_snapshot
    applied = risk_state.snapshot_forced_dates(snapshot)
    applied_view = risk_state.snapshot_forced_view_date(snapshot)
    proposal = dict(applied)
    proposal["ir/delta"] = "2026-08-01"
    dirty = risk_state.make_force_draft(
        applied,
        proposal,
        revision=snapshot.revision,
        applied_view_date=applied_view,
        view_date=applied_view,
    )
    clean = risk_state.make_force_draft(
        applied,
        applied,
        revision=snapshot.revision,
        applied_view_date=applied_view,
        view_date=applied_view,
    )

    assert callback(dirty, 0, False, "force-risk-apply-button")[:2] == (
        False,
        False,
    )
    busy = callback(dirty, 0, True, "force-risk-apply-button")
    assert busy[:2] == (True, True)
    assert "Refresh in progress" in busy[2]
    assert callback(clean, 1, False, "force-risk-apply-button")[:2] == (
        True,
        True,
    )


def test_control_labels_and_committed_settings_are_unambiguous() -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    app = build_app(refresh_manager=manager)

    auto_callback = _callback_for_output(app, "auto-refresh-toggle", "children")[
        "callback"
    ].__wrapped__
    commo_callback = _callback_for_output(app, "commo-market-toggle", "children")[
        "callback"
    ].__wrapped__
    checker_callback = _callback_for_output(app, "risk-checker-toggle", "children")[
        "callback"
    ].__wrapped__
    assert auto_callback(True)[1] == "AutoPL: On"
    assert auto_callback(False)[1] == "AutoPL: Off"
    assert commo_callback(False)[0] == "Commo: Off"
    assert commo_callback(True)[0] == "Commo: On"
    assert checker_callback(False)[0] == "RiskChecker: Off"
    assert checker_callback(True)[0] == "RiskChecker: On"

    settings_callback = next(
        metadata
        for metadata in app.callback_map.values()
        if {
            (output.component_id, output.component_property)
            for output in _callback_outputs(metadata)
        }
        == {
            ("perspective-risk-cube-commodity-market-v1", "data"),
            ("perspective-risk-cube-risk-checker-v1", "data"),
        }
    )
    assert {(item["id"], item["property"]) for item in settings_callback["inputs"]} == {
        ("data-revision-store", "data"),
        ("refresh-result-store", "data"),
    }
    assert settings_callback["callback"].__wrapped__(manager.health.revision, 1) == (
        False,
        True,
    )

    revision = manager.health.revision
    forced_dates = {
        source_type: pd.Timestamp(risk_date).date().isoformat()
        for source_type, risk_date in manager.snapshot.risk_dates.items()
    }
    manager.refresh(
        forced_dates=forced_dates,
        commodity_market_enabled=False,
        risk_checker_enabled=False,
        reason="same-revision settings test",
        expected_revision=revision,
    )
    assert manager.health.revision == revision
    assert settings_callback["callback"].__wrapped__(revision, 2) == (False, False)


def test_refresh_status_names_the_completed_action() -> None:
    status_frame = pd.DataFrame({"Age": [0], "Force Risk": [False]})
    labels = {
        "portfolio mapping": "Portfolios refreshed",
        "reload all risk": "Risk refreshed",
        "manual P&L": "P&L refreshed",
        "automatic 15-minute refresh": "AutoPL refreshed",
        "dashboard settings updated": "Settings applied",
        "apply forced risk dates": "Date settings applied",
        "clear cache": "Ready · Cache cleared",
    }
    for reason, label in labels.items():
        snapshot = SimpleNamespace(
            refreshed_at=datetime(2026, 8, 15, 16, tzinfo=timezone.utc),
            last_attempt_at=datetime(2026, 8, 15, 17, tzinfo=timezone.utc),
            risk_status=status_frame,
            refresh_reason=reason,
            errors=(),
        )
        assert risk_state._refresh_status(snapshot)[0].startswith(
            f"{label} 17:00:00 UTC"
        )

    failed = SimpleNamespace(
        refreshed_at=datetime(2026, 8, 15, 16, tzinfo=timezone.utc),
        last_attempt_at=datetime(2026, 8, 15, 17, tzinfo=timezone.utc),
        risk_status=status_frame,
        refresh_reason="reload all risk",
        errors=("retained",),
    )
    assert risk_state._refresh_status(failed)[0].startswith("Last success 16:00:00 UTC")

    completed = SimpleNamespace(
        refreshed_at=datetime(2026, 8, 15, 18, tzinfo=timezone.utc),
        last_attempt_at=datetime(2026, 8, 15, 17, tzinfo=timezone.utc),
        risk_status=status_frame,
        refresh_reason="reload all risk",
        errors=(),
    )
    assert risk_state._refresh_status(completed)[0].startswith(
        "Risk refreshed 18:00:00 UTC"
    )

    not_committed = SimpleNamespace(
        refreshed_at=datetime(2026, 8, 15, 16, tzinfo=timezone.utc),
        last_attempt_at=datetime(2026, 8, 15, 17, tzinfo=timezone.utc),
        risk_status=status_frame,
        refresh_reason="dashboard settings updated",
        errors=(),
    )
    assert risk_state._refresh_status(not_committed, action_committed=False)[
        0
    ].startswith("Last success 16:00:00 UTC")


def test_operating_dates_stay_neutral_before_the_cold_start_commits() -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    metadata = _callback_for_output(app, "operating-date-banner", "children")

    assert metadata["callback"].__wrapped__(0) is no_update


def test_browser_defers_revision_until_a_financial_page_can_consume_it() -> None:
    assets = Path(__file__).parents[1] / "assets"
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(assets.glob("*.js"))
    )
    assert 'document.getElementById("shared-refresh-shell")' in source
    assert "shell.getClientRects().length > 0" in source
    assert "running && !refreshProgressState && lifecycleVisible" in source
    assert "const financialPageCanConsumeRevision" in source
    assert 'document.getElementById("cube-page-container")' in source
    assert 'document.getElementById("risk-type-tabs")' in source
    assert 'document.getElementById("pnl-page-container")' in source
    assert "if (!financialPageCanConsumeRevision()) return false;" in source
    assert "syncCommittedDataRevision(lastBackendProgress);" in source
    trigger_start = source.index("const refreshTrigger = event.target.closest")
    trigger_end = source.index("const header = event.target.closest", trigger_start)
    trigger_source = source[trigger_start:trigger_end]
    for selector in (
        "#refresh-portfolios-button",
        "#refresh-pl-button",
        "#reload-risk-button",
        "#commo-market-toggle",
        "#risk-checker-toggle",
        "#force-risk-apply-button",
    ):
        assert selector in trigger_source
    assert "#auto-refresh-toggle" not in trigger_source
    assert '"commo"' in trigger_source
    assert '"checker"' in trigger_source
    assert '"dates"' in trigger_source
    assert "Updating Commo market" in source
    assert "Updating RiskChecker" in source
    assert "Applying date settings" in source
    assert '["force-risk-apply-button", "force-risk-cancel-button"]' in source
    assert "setProps(id, { disabled: true })" in source
