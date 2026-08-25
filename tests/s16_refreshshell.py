"""Persistent refresh lifecycle checks for native Dash Pages."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from dash import no_update
from dash.exceptions import PreventUpdate
from cube.services.s05_sources import build_production_refresh_manager
from cube.pages.risk import s15_refresh as risk_callbacks
from cube.pages.risk import s02_state as risk_state
from cube.app.s04_startup import STARTUP_COORDINATOR_CONFIG_KEY
from cube.ui.s04_components import (
    build_initial_load_layout,
    build_shared_refresh_shell,
)
from cube.app.s07_factory import build_app


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
    action_ids = {
        component_id
        for item in _walk(_by_id(neutral, "refresh-control-strip"))
        if isinstance((component_id := getattr(item, "id", None)), str)
    }
    assert {"theme-toggle", "refresh-status"} <= action_ids
    callback_target_ids = {
        "refresh-portfolios-button",
        "reload-risk-button",
        "refresh-pl-button",
        "commo-market-toggle",
        "risk-checker-toggle",
        "auto-refresh-toggle",
        "clear-cache-button",
        "operating-date-banner",
    }
    assert callback_target_ids <= action_ids
    callback_targets = next(
        item
        for item in _walk(_by_id(neutral, "refresh-control-strip"))
        if getattr(item, "className", None) == "cold-refresh-callback-targets"
    )
    assert callback_targets.hidden is True
    assert _by_id(neutral, "reset-generation-store").data == 0
    assert _by_id(neutral, "clear-cache-complete-store").data == 0
    assert _by_id(neutral, "refresh-busy-store").data is False

    composed = build_shared_refresh_shell(
        None,
        refresh_enabled=True,
        initial_loading=True,
        include_header_utilities=False,
    )
    composed_ids = {getattr(item, "id", None) for item in _walk(composed)}
    assert "theme-toggle" not in composed_ids
    assert "clear-cache-button" not in composed_ids

    loading = build_shared_refresh_shell(
        None,
        refresh_enabled=True,
        initial_loading=True,
    )
    assert "is-refreshing" in _by_id(loading, "refresh-status").className
    assert _by_id(loading, "refresh-progress").hidden is False
    assert _by_id(loading, "shared-refresh-bootstrap-interval").disabled is False
    assert (
        _by_id(loading, "refresh-progress-function").children
        == "Waiting for the server-started refresh"
    )
    assert not any(
        getattr(item, "className", None) == "refresh-progress-note"
        for item in _walk(loading)
    )
    for component_id in (
        "refresh-progress-source",
        "refresh-progress-count",
        "refresh-progress-hold",
        "refresh-stage-readiness",
        "refresh-stage-risk",
        "refresh-stage-market",
        "refresh-stage-pl",
        "refresh-stage-final",
    ):
        assert _by_id(loading, component_id) is not None

    stalled = build_shared_refresh_shell(
        None,
        refresh_enabled=True,
        initial_error="Connector is still running",
        keep_polling=True,
    )
    assert "is-error" in _by_id(stalled, "refresh-status").className
    assert "is-error" in _by_id(stalled, "refresh-progress").className
    assert _by_id(stalled, "refresh-progress-title").children == (
        "Initial data load failed"
    )
    assert _by_id(stalled, "refresh-progress-product").children == (
        "No financial snapshot was published"
    )
    assert _by_id(stalled, "refresh-progress-function").children == (
        "Use Retry after checking the connector error"
    )
    assert not any(
        getattr(item, "className", None) == "refresh-progress-note"
        for item in _walk(stalled)
    )
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


def test_remounted_zero_click_controls_do_not_start_another_refresh(
    monkeypatch,
) -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    app = build_app(refresh_manager=manager)
    callback = _callback_for_output(app, "refresh-commit-revision", "children")[
        "callback"
    ].__wrapped__
    baseline_revision = manager.health.revision
    click_ids = (
        "refresh-portfolios-button",
        "refresh-pl-button",
        "reload-risk-button",
        "force-risk-apply-button",
        "clear-cache-button",
        "commo-market-toggle",
        "risk-checker-toggle",
    )

    for component_id in click_ids:
        monkeypatch.setattr(
            risk_callbacks,
            "ctx",
            SimpleNamespace(
                triggered_id=component_id,
                triggered_prop_ids={f"{component_id}.n_clicks": component_id},
            ),
        )
        try:
            callback(0, 0, 0, 0, 0, 0, 0, 0, {}, True, 0, 0)
        except PreventUpdate:
            pass
        else:  # pragma: no cover - explicit failure keeps the callback contract clear
            raise AssertionError(f"{component_id} accepted a zero-click mount event")

    assert manager.health.revision == baseline_revision


def test_positive_pl_click_still_runs_one_manual_refresh(monkeypatch) -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    app = build_app(refresh_manager=manager)
    callback = _callback_for_output(app, "refresh-commit-revision", "children")[
        "callback"
    ].__wrapped__
    baseline_revision = manager.health.revision
    monkeypatch.setattr(
        risk_callbacks,
        "ctx",
        SimpleNamespace(
            triggered_id="refresh-pl-button",
            triggered_prop_ids={"refresh-pl-button.n_clicks": "refresh-pl-button"},
        ),
    )

    result = callback(0, 0, 1, 0, 0, 0, 0, 0, {}, True, 0, 0)

    assert manager.health.revision == baseline_revision + 1
    assert manager.snapshot.refresh_reason == "manual P&L"
    assert result[0] == manager.health.revision


def test_manual_pl_callback_copies_only_the_new_dashboard_frame(monkeypatch) -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    app = build_app(refresh_manager=manager)
    callback = _callback_for_output(app, "refresh-commit-revision", "children")[
        "callback"
    ].__wrapped__
    reads: list[str] = []
    original_read_frame = manager.read_frame

    def tracked_read_frame(name: str):
        reads.append(name)
        return original_read_frame(name)

    def reject_full_snapshot_copy(_snapshot):
        raise AssertionError("refresh callback requested a full snapshot copy")

    monkeypatch.setattr(manager, "read_frame", tracked_read_frame)
    monkeypatch.setattr(manager, "_copy_snapshot", reject_full_snapshot_copy)
    monkeypatch.setattr(
        risk_callbacks,
        "ctx",
        SimpleNamespace(
            triggered_id="refresh-pl-button",
            triggered_prop_ids={"refresh-pl-button.n_clicks": "refresh-pl-button"},
        ),
    )

    result = callback(0, 0, 1, 0, 0, 0, 0, 0, {}, True, 0, 0)

    assert result[0] == manager.health.revision
    assert reads == ["dashboard_frame"]


def test_browser_auto_ticks_coalesce_after_another_browser_auto_attempt(
    monkeypatch,
) -> None:
    manager = build_production_refresh_manager()
    manager.refresh(
        force_risk=True,
        force_pl=True,
        reason="automatic 15-minute refresh",
    )
    app = build_app(refresh_manager=manager)
    callback = _callback_for_output(app, "refresh-commit-revision", "children")[
        "callback"
    ].__wrapped__
    baseline_revision = manager.health.revision

    def reject_duplicate_auto_refresh(**_kwargs):
        raise AssertionError("coalesced browser tick reached the refresh manager")

    monkeypatch.setattr(
        manager,
        "refresh",
        reject_duplicate_auto_refresh,
    )
    monkeypatch.setattr(
        risk_callbacks,
        "ctx",
        SimpleNamespace(
            triggered_id="auto-refresh-interval",
            triggered_prop_ids={
                "auto-refresh-interval.n_intervals": "auto-refresh-interval"
            },
        ),
    )

    try:
        callback(1, 0, 0, 0, 0, 0, 0, 0, {}, True, 0, 0)
    except PreventUpdate:
        pass
    else:  # pragma: no cover - explicit failure documents the callback contract
        raise AssertionError("a recent automatic refresh was not coalesced")

    assert manager.health.revision == baseline_revision


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
        "clear-cache-button.disabled" not in refresh_registration["running"]["running"]
    )
    clear_cache_state = _callback_for_output(app, "clear-cache-button", "disabled")
    assert {(item["id"], item["property"]) for item in clear_cache_state["inputs"]} == {
        ("refresh-busy-store", "data"),
        ("refresh-commit-revision", "children"),
    }
    sync_clear_cache = clear_cache_state["callback"].__wrapped__
    assert sync_clear_cache(False, 0) is True
    assert sync_clear_cache(True, 1) is True
    assert sync_clear_cache(False, 1) is False

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

    stale_clean = dict(clean)
    stale_clean["base_revision"] = snapshot.revision - 1
    reconciling = callback(stale_clean, 2, False, "force-risk-apply-button")
    assert reconciling == (
        True,
        True,
        "Reconciling applied date settings…",
        "force-risk-edit-status",
    )

    genuine_conflict = dict(stale_clean)
    genuine_conflict["conflict"] = True
    conflicted = callback(genuine_conflict, 2, False, "force-risk-apply-button")
    assert conflicted[:2] == (True, False)
    assert "changed while you were editing" in conflicted[2]
    assert "is-error" in conflicted[3]


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
    auto_on = auto_callback(True)
    auto_off = auto_callback(False)
    assert auto_on[1] == "Auto P&L: On · 15 min"
    assert "Next automatic P&L run" in auto_on[6]
    assert auto_off[1] == "Auto P&L: Off · 15 min"
    assert "No automatic run" in auto_off[6]
    assert commo_callback(False)[0] == "Commodity quotes: Disabled"
    assert commo_callback(True)[0] == "Commodity quotes: Loaded"
    assert checker_callback(False)[0] == "Risk dates: Today"
    assert checker_callback(True)[0] == "Risk dates: Checker"
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
