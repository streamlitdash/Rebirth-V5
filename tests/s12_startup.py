"""Cold-start shell, worker ownership, watchdog, and failure tests."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from threading import Barrier, Event, Thread
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import page_registry
from dash.exceptions import UnsupportedRelativePath

from cube.services.s05_sources import build_production_refresh_manager
from cube.pages.static_data import (
    STATIC_FILE_OPTIONS,
    build_static_data_page,
    build_static_data_table,
)
from cube.pages.risk import s02_state as risk_state
from cube.app import s07_factory as factory
from cube.app import s04_startup as events
from cube.app.s07_factory import build_app
from cube.app.s04_startup import STARTUP_COORDINATOR_CONFIG_KEY, StartupCoordinator


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


def _component_id_key(component_id: object) -> str:
    if isinstance(component_id, dict):
        return json.dumps(
            component_id,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
    return str(component_id)


def _callback_outputs(metadata: dict) -> list[object]:
    output = metadata["output"]
    return list(output) if isinstance(output, (list, tuple)) else [output]


def _callback_for_output(app, component_id: str, component_property: str):
    metadata = next(
        metadata
        for metadata in app.callback_map.values()
        if any(
            output.component_id == component_id
            and output.component_property == component_property
            for output in _callback_outputs(metadata)
        )
    )
    return metadata["callback"].__wrapped__


def _native_page(
    app,
    page_path: str = "/",
    *,
    browser_path: str | None = None,
):
    """Materialize one native page using this app's Flask service context."""
    routes_prefix = app.config.routes_pathname_prefix
    layout_path = f"{routes_prefix}_dash-layout"
    response = app.server.test_client().get(layout_path)
    assert response.status_code == 200

    route = _callback_for_output(app, "_pages_content", "children")
    pathname = (
        app.get_relative_path(page_path) if browser_path is None else browser_path
    )
    with app.server.test_request_context(layout_path):
        return route(pathname, "")


def _wait_for_phase(
    coordinator: StartupCoordinator,
    phase: str,
    *,
    timeout: float = 3.0,
):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = coordinator.status()
        if status.phase == phase:
            return status
        time.sleep(0.01)
    raise AssertionError(
        f"startup phase did not become {phase!r}; last={coordinator.status()}"
    )


class _StartupManager:
    def __init__(self, *, blocker: Event | None = None, error: Exception | None = None):
        self._blocker = blocker
        self._error = error
        self.calls = 0
        self.refresh_kwargs = None
        self.stage_delays = {}
        self.health = SimpleNamespace(
            revision=0,
            refreshed_at=None,
            last_attempt_at=None,
            active_error_count=0,
        )
        self.progress = SimpleNamespace(
            attempt_id="refresh-attempt-1",
            function_name="get_ir_delta_market_status",
            source_type="ir/delta",
            underlying="USD SOFR",
            product_label="IR Delta",
            product_index=1,
            product_total=16,
            hold_seconds=0.0,
            stage="market_status",
            current=1,
            total=16,
            message="Waiting for current market connector.",
            running=True,
            error=None,
            started_at=None,
            updated_at=None,
            finished_at=None,
        )

    def refresh(self, **kwargs):
        self.calls += 1
        self.refresh_kwargs = kwargs
        if self._blocker is not None:
            assert self._blocker.wait(timeout=2.0)
        if self._error is not None:
            raise self._error
        self.health.revision = 1


def test_manager_backed_risk_page_mounts_server_owned_loading_shell(
    request,
) -> None:
    blocker = Event()
    request.addfinalizer(blocker.set)
    manager = _StartupManager(blocker=blocker)

    app = build_app(refresh_manager=manager)
    response = app.server.test_client().get("/_dash-layout")
    health = app.server.test_client().get("/healthz").get_json()
    base_layout = app.layout() if callable(app.layout) else app.layout
    base_components = list(_walk(base_layout))
    base_ids = {
        component_id
        for item in base_components
        if isinstance((component_id := getattr(item, "id", None)), str)
    }
    risk_page, _metadata = _native_page(app)
    risk_ids = {getattr(item, "id", None) for item in _walk(risk_page)}
    shared_shell = next(
        item
        for item in base_components
        if getattr(item, "id", None) == "shared-refresh-shell"
    )
    refresh_progress = next(
        item
        for item in base_components
        if getattr(item, "id", None) == "refresh-progress"
    )
    refresh_product = next(
        item
        for item in base_components
        if getattr(item, "id", None) == "refresh-progress-product"
    )
    bootstrap_interval = next(
        item
        for item in base_components
        if getattr(item, "id", None) == "shared-refresh-bootstrap-interval"
    )
    initial_trigger = next(
        item
        for item in _walk(risk_page)
        if getattr(item, "id", None) == "initial-load-trigger"
    )
    mounted_ids = [
        _component_id_key(component_id)
        for item in [*base_components, *_walk(risk_page)]
        if (component_id := getattr(item, "id", None)) is not None
    ]

    assert response.status_code == 200
    assert b'"id":"_pages_content"' in response.data
    assert b"initial-load-trigger" not in response.data
    assert b'"id":"static-data-page"' not in response.data
    assert {
        "_pages_location",
        "shared-refresh-shell",
        "refresh-progress-product",
    } <= base_ids
    assert "app-location" not in base_ids
    assert shared_shell.style == {"display": "none"}
    assert refresh_progress.hidden is False
    assert refresh_progress.to_plotly_json()["props"]["data-initial-load"] == "true"
    assert refresh_product.children == "Preparing the first validated snapshot"
    assert {
        "refresh-progress-function",
        "refresh-progress-source",
        "refresh-progress-count",
        "refresh-progress-hold",
        "refresh-stage-readiness",
        "refresh-stage-risk",
        "refresh-stage-market",
        "refresh-stage-pl",
        "refresh-stage-final",
    } <= base_ids
    # The router reveals this shell after resolving the URL. Its follower must
    # already be live so direct Data/Stock/Statics visits receive revision 1.
    assert bootstrap_interval.disabled is False
    assert bootstrap_interval.interval == 2_000
    assert initial_trigger.interval == 2_000
    assert initial_trigger.max_intervals == -1
    assert {"cube-page-container", "initial-load-trigger"} <= risk_ids
    # The factory-level shared shell owns the progress IDs; the cold Risk body
    # must not mount a duplicate copy.
    assert "refresh-progress-function" not in risk_ids
    assert len(mounted_ids) == len(set(mounted_ids))
    assert manager.health.revision == 0
    assert health["status"] == "starting"
    coordinator = app.server.config[STARTUP_COORDINATOR_CONFIG_KEY]
    # The mounted Risk page already owns the one pending start.
    assert coordinator.schedule_start() is False
    _wait_for_phase(coordinator, "running")
    assert manager.calls == 1
    blocker.set()
    _wait_for_phase(coordinator, "succeeded")


def test_startup_coordinator_deduplicates_visitors_and_commits_once() -> None:
    manager = _StartupManager()
    coordinator = StartupCoordinator(manager)

    assert coordinator.start() is True
    assert coordinator.start() is False
    status = _wait_for_phase(coordinator, "succeeded")

    assert status.attempt == 1
    assert manager.calls == 1
    assert manager.refresh_kwargs["copy_result"] is False
    assert manager.health.revision == 1


def test_startup_watchdog_names_active_call_without_starting_second_writer(
    monkeypatch,
) -> None:
    blocker = Event()
    manager = _StartupManager(blocker=blocker)
    clock = [10.0]
    monkeypatch.setattr(events, "monotonic", lambda: clock[0])
    coordinator = StartupCoordinator(manager, timeout_seconds=1.0)

    assert coordinator.start() is True
    clock[0] = 12.0
    status = coordinator.status()

    assert status.phase == "stalled"
    assert status.retryable is False
    assert "get_ir_delta_market_status" in str(status.error)
    assert coordinator.start(retry=True) is False
    assert manager.calls == 1

    blocker.set()
    _wait_for_phase(coordinator, "succeeded")


def test_startup_schedule_allows_only_one_pending_timer() -> None:
    blocker = Event()
    manager = _StartupManager(blocker=blocker)
    coordinator = StartupCoordinator(manager)

    assert coordinator.schedule_start(delay_seconds=0.01) is True
    assert all(
        coordinator.schedule_start(delay_seconds=0.01) is False for _ in range(50)
    )

    blocker.set()
    _wait_for_phase(coordinator, "succeeded")
    assert manager.calls == 1


def test_startup_failure_is_visible_and_retryable() -> None:
    manager = _StartupManager(error=RuntimeError("checker service unavailable"))
    coordinator = StartupCoordinator(manager)

    assert coordinator.start() is True
    status = _wait_for_phase(coordinator, "failed")

    assert status.retryable is True
    assert "RuntimeError" in str(status.error)
    assert "Check the terminal for the exact reason" in str(status.error)
    assert "checker service unavailable" not in str(status.error)


def test_lightweight_endpoints_and_pages_stay_passive_until_financial_page(
    request,
) -> None:
    blocker = Event()
    request.addfinalizer(blocker.set)
    manager = _StartupManager(blocker=blocker)
    app = build_app(refresh_manager=manager)
    client = app.server.test_client()

    assert client.get("/healthz").status_code == 200
    assert client.get("/progressz").status_code == 200
    assert manager.calls == 0
    assert manager.health.revision == 0
    coordinator = app.server.config[STARTUP_COORDINATOR_CONFIG_KEY]
    assert coordinator.status().phase == "idle"

    base = client.get("/_dash-layout")
    static_page, _metadata = _native_page(app, "/static-data")
    static_ids = {getattr(item, "id", None) for item in _walk(static_page)}
    time.sleep(0.6)

    assert base.status_code == 200
    assert b"initial-load-trigger" not in base.data
    assert "static-data-page" in static_ids
    assert "initial-load-trigger" not in static_ids
    assert manager.calls == 0
    assert coordinator.status().phase == "idle"

    risk_page, _metadata = _native_page(app)
    risk_ids = {getattr(item, "id", None) for item in _walk(risk_page)}
    assert "initial-load-trigger" in risk_ids
    _wait_for_phase(coordinator, "running")
    assert manager.calls == 1
    blocker.set()
    _wait_for_phase(coordinator, "succeeded")


def test_start_endpoint_is_idempotent_and_progress_has_attempt_identity() -> None:
    blocker = Event()
    manager = _StartupManager(blocker=blocker)
    app = build_app(refresh_manager=manager)
    client = app.server.test_client()

    first = client.post("/startz")
    second = client.post("/startz")
    first_payload = first.get_json()
    second_payload = second.get_json()

    assert first.status_code == 200
    assert second.status_code == 200
    assert first_payload["started_new_worker"] is True
    assert second_payload["started_new_worker"] is False
    assert first_payload["revision"] == 0
    assert first_payload["startup_phase"] == "running"
    assert first_payload["startup_attempt_id"]
    assert first_payload["server_boot_id"]
    assert second_payload["startup_attempt_id"] == first_payload["startup_attempt_id"]
    assert second_payload["server_boot_id"] == first_payload["server_boot_id"]

    blocker.set()
    coordinator = app.server.config[STARTUP_COORDINATOR_CONFIG_KEY]
    _wait_for_phase(coordinator, "succeeded")
    complete = client.get("/progressz").get_json()
    assert complete["revision"] == 1
    assert complete["startup_phase"] == "succeeded"
    assert complete["attempt_id"] == "refresh-attempt-1"


def test_public_endpoint_urls_do_not_reuse_internal_route_prefix() -> None:
    manager = build_production_refresh_manager()
    app = build_app(
        refresh_manager=manager,
        dash_kwargs={
            "routes_pathname_prefix": "/internal/",
            "requests_pathname_prefix": "/proxy/internal/",
        },
    )
    client = app.server.test_client()

    layout = client.get("/internal/_dash-layout")

    assert layout.status_code == 200
    layout_component = app.layout() if callable(app.layout) else app.layout
    endpoint = next(
        item
        for item in _walk(layout_component)
        if getattr(item, "id", None) == "backend-endpoints"
    )
    endpoint_props = endpoint.to_plotly_json()["props"]
    assert endpoint_props["data-progress-url"] == "/proxy/internal/progressz"
    assert endpoint_props["data-start-url"] == "/proxy/internal/startz"
    assert client.get("/internal/progressz").status_code == 200
    assert client.post("/internal/startz").status_code == 200


def test_browser_progress_copy_never_claims_an_unconfirmed_refresh() -> None:
    source = (
        Path(__file__).resolve().parent.parent / "assets" / "s12_refresh.js"
    ).read_text(encoding="utf-8")

    assert "the refresh is still being followed" not in source
    assert "Refresh state is not confirmed" in source
    assert "startup_attempt_id" in source
    assert "baselineRefreshAttemptId" in source
    assert "refreshAttemptMatches" in source
    assert "revisionAdvanced" in source
    assert "progressStartedDuringAttempt" in source
    assert "server_boot_id" in source
    assert "previousBackendProgress" in source
    assert "Server process restarted during refresh" in source
    assert "previous attempt ended before Python could report an error" in source
    assert "Last confirmed work:" in source
    assert 'refreshProgressState.mode === "bootstrap"' in source
    assert "serverReplaced: false" in source
    assert "refreshProgressState.serverReplaced = true" in source
    assert "state.serverReplaced" in source
    assert "state.serverReplaced = false" in source
    assert 'state.backendError = ""' in source
    assert "reload this page to reconnect before using refreshed data" in source
    assert "const startupAttemptMatches" in source
    assert "attributeOldValue: true" in source
    assert "transitionedFromRunning" in source
    assert 'state.mode === "bootstrap"' in source
    assert "hasNewError ? 5000 : 300" in source
    assert "revision <= renderedDataRevisionFloor()" in source
    assert 'setProps("data-revision-store", { data: revision })' in source
    revision_sync = source.index("const syncCommittedDataRevision")
    assert (
        'refreshProgressState?.mode === "bootstrap"'
        in source[revision_sync : revision_sync + 500]
    )
    revision_sync_source = source[revision_sync : revision_sync + 1_300]
    assert (
        'const commitNode = document.getElementById("refresh-commit-revision")'
        in revision_sync_source
    )
    assert "normalizedRevision(commitNode?.textContent)" in revision_sync_source
    assert "progress?.running === false" in revision_sync_source
    assert "|| !commitNode" in revision_sync_source
    assert "Math.max" in revision_sync_source
    assert 'document.getElementById("data-revision-store")' not in (
        revision_sync_source
    )
    assert "const claimSessionReload" in source
    assert "dashIsLoading() || Date.now() < handoffDeadline" in source
    assert "cube-bootstrap-ready-reload:${bootId}:${revision}" in source
    assert "cube-progress-transport-reload:${bootId}" in source
    assert "cube-progress-recovery-reload-at" not in source
    assert "Date.now() - lastRecovery >= 60000" not in source
    reload_guard = source.index("disconnectedFor >= 45000")
    assert (
        'refreshProgressState.mode === "bootstrap"'
        in source[reload_guard : reload_guard + 180]
    )
    completion_guard = source.index(
        "// Only the refresh callback's running state gates this"
    )
    assert (
        "if (!running) finishRefreshProgress();"
        in source[completion_guard : completion_guard + 400]
    )


def test_warm_manager_keeps_the_shell_recovery_callback_registered() -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)

    app = build_app(refresh_manager=manager)
    coordinator = app.server.config[STARTUP_COORDINATOR_CONFIG_KEY]
    operating_dates = _callback_for_output(app, "operating-date-banner", "children")(
        manager.health.revision
    )
    risk_page, _metadata = _native_page(app)
    base_layout = app.layout() if callable(app.layout) else app.layout
    components = [*list(_walk(base_layout)), *list(_walk(risk_page))]
    ids = {
        component_id
        for item in components
        if isinstance((component_id := getattr(item, "id", None)), str)
    }
    auto_interval = next(
        item
        for item in components
        if getattr(item, "id", None) == "auto-refresh-interval"
    )

    assert coordinator is not None
    assert coordinator.status().phase == "succeeded"
    assert "cube-page-container.children" in app.callback_map
    assert manager.snapshot.market_date.date().isoformat() in str(operating_dates)
    assert auto_interval.interval == 15 * 60_000
    assert "operating-date-banner" in ids
    assert "unmapped-books-summary" in ids
    assert "raw-data-summary" not in ids


def test_long_financial_callback_cannot_own_live_revision() -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    app = build_app(refresh_manager=manager)
    metadata = next(
        metadata
        for metadata in app.callback_map.values()
        if any(
            output.component_id == "refresh-commit-revision"
            for output in _callback_outputs(metadata)
        )
    )
    inputs = {(item["id"], item["property"]) for item in metadata["inputs"]}
    outputs = {
        (output.component_id, output.component_property)
        for output in _callback_outputs(metadata)
    }

    assert inputs == {
        ("auto-refresh-interval", "n_intervals"),
        ("refresh-portfolios-button", "n_clicks"),
        ("refresh-pl-button", "n_clicks"),
        ("reload-risk-button", "n_clicks"),
        ("force-risk-apply-button", "n_clicks"),
        ("clear-cache-button", "n_clicks"),
        ("commo-market-toggle", "n_clicks"),
        ("risk-checker-toggle", "n_clicks"),
    }
    assert (
        "perspective-risk-cube-commodity-market-v1",
        "data",
    ) not in outputs
    assert ("perspective-risk-cube-risk-checker-v1", "data") not in outputs
    assert ("refresh-commit-revision", "children") in outputs
    assert ("reset-generation-store", "data") in outputs
    assert ("clear-cache-complete-store", "data") in outputs
    assert ("data-revision-store", "data") not in outputs

    layout = app.layout() if callable(app.layout) else app.layout
    commit_revision = next(
        item
        for item in _walk(layout)
        if getattr(item, "id", None) == "refresh-commit-revision"
    )
    assert commit_revision.hidden is True
    assert commit_revision.children == manager.health.revision


def test_composed_app_defaults_to_no_artificial_risk_product_hold(monkeypatch) -> None:
    monkeypatch.delenv("RISK_PRODUCT_DELAY_SECONDS", raising=False)
    from app import create_app

    app = create_app()
    coordinator = app.server.config[STARTUP_COORDINATOR_CONFIG_KEY]

    assert coordinator._manager.stage_delays == {"risk_product": 0.0}


def test_composed_cold_shell_does_not_catalog_or_read_annual_history(
    monkeypatch,
) -> None:
    from cube.history import s07_sql as archive_sql_module
    import app as app_module

    history_root = (Path(app_module.__file__).parent / "data" / "histo").resolve()
    archive_access: list[tuple[str, Path]] = []
    source_calls: list[str] = []
    original_iterdir = Path.iterdir
    original_read_text = Path.read_text
    original_read_csv = pd.read_csv
    original_read_parquet = pd.read_parquet
    original_get_stock = app_module.get_stock
    original_stock_history_repository = app_module.SQLStockHistoryRepository
    stock_history_repositories: list[object] = []

    def is_history_path(value: object) -> bool:
        try:
            resolved = Path(value).resolve()
        except TypeError:
            return False
        return resolved == history_root or history_root in resolved.parents

    def tracked_iterdir(path: Path):
        if is_history_path(path):
            archive_access.append(("iterdir", path.resolve()))
        return original_iterdir(path)

    def tracked_read_text(path: Path, *args, **kwargs):
        if is_history_path(path):
            archive_access.append(("read_text", path.resolve()))
        return original_read_text(path, *args, **kwargs)

    def tracked_read_csv(source, *args, **kwargs):
        if is_history_path(source):
            archive_access.append(("read_csv", Path(source).resolve()))
        return original_read_csv(source, *args, **kwargs)

    def tracked_read_parquet(source, *args, **kwargs):
        if is_history_path(source):
            archive_access.append(("read_parquet", Path(source).resolve()))
        return original_read_parquet(source, *args, **kwargs)

    def tracked_get_stock(stock_date):
        source_calls.append("stock")
        return original_get_stock(stock_date)

    def tracked_stock_history_repository(root):
        repository = original_stock_history_repository(root)
        stock_history_repositories.append(repository)
        return repository

    monkeypatch.setattr(Path, "iterdir", tracked_iterdir)
    monkeypatch.setattr(Path, "read_text", tracked_read_text)
    monkeypatch.setattr(pd, "read_csv", tracked_read_csv)
    monkeypatch.setattr(pd, "read_parquet", tracked_read_parquet)
    monkeypatch.setattr(app_module, "get_stock", tracked_get_stock)
    monkeypatch.setattr(
        app_module,
        "SQLStockHistoryRepository",
        tracked_stock_history_repository,
    )
    monkeypatch.setattr(
        archive_sql_module,
        "list_completed_v4_archive_days",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cold app cataloged SQL history")
        ),
    )

    app = app_module.create_app()
    response = app.server.test_client().get("/_dash-layout")
    layout = app.layout() if callable(app.layout) else app.layout
    layout_ids = {getattr(component, "id", None) for component in _walk(layout)}
    coordinator = app.server.config[STARTUP_COORDINATOR_CONFIG_KEY]

    assert response.status_code == 200
    assert "shared-refresh-shell" in layout_ids
    assert coordinator._manager.health.revision == 0
    assert archive_access == []
    assert source_calls == []
    assert len(stock_history_repositories) == 1
    assert stock_history_repositories[0]._root.resolve() == history_root


def test_composed_app_uses_data_page_as_the_only_market_history_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app as app_module

    captured: dict[str, object] = {}
    expected_stock_history = object()

    def capture_app(**kwargs):
        captured["app_kwargs"] = kwargs
        return SimpleNamespace()

    def bind_stock_history(root):
        captured["stock_history_root"] = root
        return expected_stock_history

    monkeypatch.setenv("PL_HISTORICAL_PATH", str(tmp_path))
    monkeypatch.setattr(app_module, "SQLStockHistoryRepository", bind_stock_history)
    monkeypatch.setattr(app_module, "build_app", capture_app)

    result = app_module.create_app()

    assert isinstance(result, SimpleNamespace)
    app_kwargs = captured["app_kwargs"]
    assert isinstance(app_kwargs, dict)
    assert app_kwargs["pl_history_root"] == tmp_path.resolve()
    history_repository = app_kwargs["pl_send_config"].history_source
    assert isinstance(history_repository, app_module.SQLPLHistoryRepository)
    assert history_repository.root == tmp_path.resolve()
    assert "market_history_loader" not in app_kwargs
    assert app_kwargs["stock_history_source"] is expected_stock_history
    assert captured["stock_history_root"] == tmp_path.resolve()


def test_every_callback_output_has_one_nonduplicate_owner() -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    _native_page(app)
    owners: dict[tuple[str, str], list[str]] = defaultdict(list)

    for callback_key, metadata in app.callback_map.items():
        for output in _callback_outputs(metadata):
            identity = (
                _component_id_key(output.component_id),
                output.component_property,
            )
            owners[identity].append(callback_key)
            assert output.allow_duplicate is False

    duplicates = {
        f"{component_id}.{component_property}": callbacks
        for (component_id, component_property), callbacks in owners.items()
        if len(callbacks) != 1
    }
    assert duplicates == {}
    assert len(owners[("risk-grid", "children")]) == 1
    assert ("data-revision-store", "data") not in owners
    assert len(owners[("refresh-commit-revision", "children")]) == 1
    assert len(owners[("cube-page-container", "children")]) == 1
    assert len(owners[("_pages_content", "children")]) == 1
    assert len(owners[("shared-refresh-shell", "children")]) == 1
    assert len(owners[("shared-refresh-shell", "style")]) == 1
    assert len(owners[("static-data-table-container", "children")]) == 1
    assert ("app-page-container", "children") not in owners
    assert ("cube-page-container", "style") not in owners
    assert ("static-data-page-container", "style") not in owners


def test_native_pages_mount_one_exact_page_and_explicit_404() -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    nav = _callback_for_output(app, "cube-nav-link", "className")
    app_layout = app.layout() if callable(app.layout) else app.layout
    primary_navigation = next(
        item
        for item in _walk(app_layout)
        if getattr(item, "className", None) == "cube-nav"
    )
    header_actions = next(
        item
        for item in _walk(app_layout)
        if getattr(item, "className", None) == "cube-header-actions"
    )
    header_utilities = header_actions.children[0]
    layout_ids = [getattr(item, "id", None) for item in _walk(app_layout)]

    assert [link.children for link in primary_navigation.children] == [
        "Risk",
        "Data",
        "Stock",
        "P&L",
        "Statics",
    ]
    assert primary_navigation.children[-1].refresh is True
    assert header_actions.children[1] is primary_navigation
    assert [item.id for item in header_utilities.children] == [
        "theme-toggle",
        "clear-cache-button",
        "app-log-toggle",
    ]
    assert layout_ids.count("theme-toggle") == 1
    assert layout_ids.count("clear-cache-button") == 1
    assert layout_ids.count("app-log-toggle") == 1
    assert layout_ids.count("app-log-panel") == 1
    assert app.logger.propagate is False

    static_page, metadata = _native_page(app, "/static-data")
    static_ids = {getattr(item, "id", None) for item in _walk(static_page)}
    cube_class, data_class, pnl_class, stock_class, static_class, shell_style = nav(
        app.get_relative_path("/static-data/")
    )
    assert metadata == {"title": "Cube — Statics"}
    assert cube_class == "app-nav-link cube-nav-link"
    assert data_class == "app-nav-link cube-nav-link"
    assert pnl_class == "app-nav-link cube-nav-link"
    assert stock_class == "app-nav-link cube-nav-link"
    assert static_class == "app-nav-link cube-nav-link is-active"
    assert shell_style == {}
    assert {"static-data-page", "static-data-file-selector"} <= static_ids
    assert any(
        getattr(item, "children", None) == "Statics" for item in _walk(static_page)
    )
    assert "cube-page-container" not in static_ids
    assert "initial-load-trigger" not in static_ids

    cube_page, metadata = _native_page(app)
    cube_ids = {getattr(item, "id", None) for item in _walk(cube_page)}
    cube_class, data_class, pnl_class, stock_class, static_class, shell_style = nav(
        app.get_relative_path("/")
    )
    assert metadata == {"title": "Cube — Risk"}
    assert cube_class == "app-nav-link cube-nav-link is-active"
    assert data_class == "app-nav-link cube-nav-link"
    assert pnl_class == "app-nav-link cube-nav-link"
    assert stock_class == "app-nav-link cube-nav-link"
    assert static_class == "app-nav-link cube-nav-link"
    assert shell_style == {}
    assert {"cube-page-container", "initial-load-trigger"} <= cube_ids
    assert "static-data-page" not in cube_ids

    data_page, metadata = _native_page(app, "/data")
    data_ids = {getattr(item, "id", None) for item in _walk(data_page)}
    cube_class, data_class, pnl_class, stock_class, static_class, shell_style = nav(
        app.get_relative_path("/data")
    )
    assert metadata == {"title": "Cube — Data"}
    assert cube_class == "app-nav-link cube-nav-link"
    assert data_class == "app-nav-link cube-nav-link is-active"
    assert pnl_class == "app-nav-link cube-nav-link"
    assert stock_class == "app-nav-link cube-nav-link"
    assert static_class == "app-nav-link cube-nav-link"
    assert shell_style == {}
    assert {
        "data-page",
        "data-history-chart",
        "data-load-history-button",
        "data-underlying",
    } <= data_ids
    assert "data-raw-table" not in data_ids
    assert "cube-page-container" not in data_ids

    pnl_page, metadata = _native_page(app, "/pnl")
    pnl_ids = {getattr(item, "id", None) for item in _walk(pnl_page)}
    cube_class, data_class, pnl_class, stock_class, static_class, shell_style = nav(
        app.get_relative_path("/pnl")
    )
    assert metadata == {"title": "Cube — P&L Sender"}
    assert cube_class == "app-nav-link cube-nav-link"
    assert data_class == "app-nav-link cube-nav-link"
    assert pnl_class == "app-nav-link cube-nav-link is-active"
    assert stock_class == "app-nav-link cube-nav-link"
    assert static_class == "app-nav-link cube-nav-link"
    assert shell_style == {}
    assert {"pnl-page", "pnl-unavailable"} <= pnl_ids
    assert "cube-page-container" not in pnl_ids

    stock_page, metadata = _native_page(app, "/stock")
    stock_ids = {getattr(item, "id", None) for item in _walk(stock_page)}
    cube_class, data_class, pnl_class, stock_class, static_class, shell_style = nav(
        app.get_relative_path("/stock")
    )
    assert metadata == {"title": "Cube — Stock"}
    assert cube_class == "app-nav-link cube-nav-link"
    assert data_class == "app-nav-link cube-nav-link"
    assert pnl_class == "app-nav-link cube-nav-link"
    assert stock_class == "app-nav-link cube-nav-link is-active"
    assert static_class == "app-nav-link cube-nav-link"
    assert shell_style == {}
    assert {"stock-page", "stock-unavailable"} <= stock_ids
    assert "cube-page-container" not in stock_ids

    not_found, metadata = _native_page(app, "/nested/static-data")
    not_found_ids = {getattr(item, "id", None) for item in _walk(not_found)}
    cube_class, data_class, pnl_class, stock_class, static_class, shell_style = nav(
        app.get_relative_path("/nested/static-data")
    )
    return_link = next(
        item
        for item in _walk(not_found)
        if getattr(item, "children", None) == "Return to Risk"
    )
    assert metadata == {"title": "Cube — Page not found"}
    assert cube_class == "app-nav-link cube-nav-link"
    assert data_class == "app-nav-link cube-nav-link"
    assert pnl_class == "app-nav-link cube-nav-link"
    assert stock_class == "app-nav-link cube-nav-link"
    assert static_class == "app-nav-link cube-nav-link"
    assert shell_style == {"display": "none"}
    assert {"not-found-page", "not-found-page-container"} <= not_found_ids
    assert return_link.href == app.get_relative_path("/")


def test_risk_and_pnl_navigation_share_one_prepared_frame_per_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = build_production_refresh_manager()
    app = build_app(refresh_manager=manager)
    manager.refresh(force_risk=True, force_pl=True)
    calls = 0
    original = factory.prepare_risk_data

    def counted_prepare(frame):
        nonlocal calls
        calls += 1
        return original(frame)

    monkeypatch.setattr(factory, "prepare_risk_data", counted_prepare)
    monkeypatch.setattr(risk_state, "prepare_risk_data", counted_prepare)

    _native_page(app, "/")
    _native_page(app, "/pnl")
    _native_page(app, "/")
    _native_page(app, "/pnl")
    aggregate = _callback_for_output(app, "pnl-aggregate-pl-grid", "children")
    aggregate(
        manager.health.revision,
        [],
        [],
        None,
        None,
        [],
    )

    assert calls == 1


def test_prepared_dashboard_cache_honours_an_older_requested_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    original_register = factory.register_callbacks

    def capture_loader(*args, **kwargs):
        captured["loader"] = kwargs["prepared_frame_loader"]
        return original_register(*args, **kwargs)

    monkeypatch.setattr(factory, "register_callbacks", capture_loader)
    manager = build_production_refresh_manager()
    build_app(refresh_manager=manager)
    manager.refresh(force_risk=True, force_pl=True)
    source = manager.read_frame("dashboard_frame").frame
    newer = source.assign(Activity="NEWER")
    older = source.assign(Activity="OLDER")
    loader = captured["loader"]

    newest_prepared = loader(revision=2, frame=newer)
    requested_older = loader(revision=1, frame=older)

    assert set(newest_prepared["activity"]) == {"NEWER"}
    assert set(requested_older["activity"]) == {"OLDER"}
    assert loader(revision=2, frame=newer) is newest_prepared


def test_warm_risk_route_uses_prepared_cache_before_reading_manager(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    app = build_app(refresh_manager=manager)
    reads: list[str] = []
    original_read_frame = manager.read_frame

    def tracked_read_frame(name: str):
        reads.append(name)
        return original_read_frame(name)

    monkeypatch.setattr(manager, "read_frame", tracked_read_frame)

    _native_page(app, "/")
    _native_page(app, "/")

    assert reads == []


def test_prepared_dashboard_cache_miss_is_single_flight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    original_register = factory.register_callbacks

    def capture_loader(*args, **kwargs):
        captured["loader"] = kwargs["prepared_frame_loader"]
        return original_register(*args, **kwargs)

    monkeypatch.setattr(factory, "register_callbacks", capture_loader)
    manager = build_production_refresh_manager()
    build_app(refresh_manager=manager)
    manager.refresh(force_risk=True, force_pl=True)
    revision = manager.health.revision
    reads: list[str] = []
    original_read_frame = manager.read_frame

    def tracked_read_frame(name: str):
        reads.append(name)
        time.sleep(0.05)
        return original_read_frame(name)

    monkeypatch.setattr(manager, "read_frame", tracked_read_frame)
    loader = captured["loader"]
    barrier = Barrier(3)
    results: list[pd.DataFrame | None] = []
    errors: list[BaseException] = []

    def load() -> None:
        try:
            barrier.wait(timeout=2)
            results.append(loader(revision=revision))
        except BaseException as error:  # pragma: no cover - asserted below
            errors.append(error)

    workers = [Thread(target=load), Thread(target=load)]
    for worker in workers:
        worker.start()
    barrier.wait(timeout=2)
    for worker in workers:
        worker.join(timeout=3)

    assert errors == []
    assert all(not worker.is_alive() for worker in workers)
    assert reads == ["dashboard_frame"]
    assert len(results) == 2
    assert results[0] is results[1]
    assert loader(revision=revision) is results[0]
    assert reads == ["dashboard_frame"]


def test_native_pages_match_the_public_prefix_exactly() -> None:
    app = build_app(
        refresh_manager=build_production_refresh_manager(),
        dash_kwargs={
            "routes_pathname_prefix": "/internal/",
            "requests_pathname_prefix": "/proxy/internal/",
        },
    )
    nav = _callback_for_output(app, "cube-nav-link", "className")

    static_page, _metadata = _native_page(app, "/static-data")
    static_ids = {getattr(item, "id", None) for item in _walk(static_page)}
    cube_class, data_class, pnl_class, stock_class, static_class, shell_style = nav(
        "/proxy/internal/static-data/"
    )
    assert cube_class == "app-nav-link cube-nav-link"
    assert data_class == "app-nav-link cube-nav-link"
    assert pnl_class == "app-nav-link cube-nav-link"
    assert stock_class == "app-nav-link cube-nav-link"
    assert static_class == "app-nav-link cube-nav-link is-active"
    assert shell_style == {}
    assert "static-data-page" in static_ids

    not_found, _metadata = _native_page(app, "/nested/static-data")
    not_found_ids = {getattr(item, "id", None) for item in _walk(not_found)}
    cube_class, data_class, pnl_class, stock_class, static_class, shell_style = nav(
        "/proxy/internal/nested/static-data"
    )
    assert cube_class == "app-nav-link cube-nav-link"
    assert data_class == "app-nav-link cube-nav-link"
    assert pnl_class == "app-nav-link cube-nav-link"
    assert stock_class == "app-nav-link cube-nav-link"
    assert static_class == "app-nav-link cube-nav-link"
    assert shell_style == {"display": "none"}
    assert "not-found-page" in not_found_ids

    with pytest.raises(UnsupportedRelativePath):
        _native_page(app, browser_path="/internal/static-data")


def test_repeated_apps_keep_native_page_services_isolated() -> None:
    cold_manager = build_production_refresh_manager()
    warm_manager = build_production_refresh_manager()
    warm_manager.refresh(force_risk=True, force_pl=True)

    cold_app = build_app(
        refresh_manager=cold_manager,
        dash_kwargs={
            "routes_pathname_prefix": "/cold-internal/",
            "requests_pathname_prefix": "/cold/",
        },
    )
    warm_app = build_app(
        refresh_manager=warm_manager,
        dash_kwargs={
            "routes_pathname_prefix": "/warm-internal/",
            "requests_pathname_prefix": "/warm/",
        },
    )

    assert tuple(page_registry) == (
        "cube.pages.risk",
        "cube.pages.data",
        "cube.pages.stock",
        "cube.pages.pnl",
        "cube.pages.static_data",
        "cube.pages.not_found_404",
    )
    assert page_registry["cube.pages.static_data"]["name"] == "Statics"
    assert page_registry["cube.pages.static_data"]["title"] == "Cube — Statics"
    assert page_registry["cube.pages.pnl"]["relative_path"] == "/warm/pnl"
    assert page_registry["cube.pages.data"]["relative_path"] == "/warm/data"
    assert page_registry["cube.pages.stock"]["relative_path"] == "/warm/stock"
    assert (
        page_registry["cube.pages.static_data"]["relative_path"] == "/warm/static-data"
    )
    assert cold_app.get_relative_path("/pnl") == "/cold/pnl"
    assert cold_app.get_relative_path("/data") == "/cold/data"
    assert warm_app.get_relative_path("/stock") == "/warm/stock"
    assert cold_app.get_relative_path("/static-data") == "/cold/static-data"
    assert warm_app.get_relative_path("/static-data") == "/warm/static-data"

    # Route the older app after the newer factory reset/re-registered Dash's
    # process-global catalogue. Stable layouts must still resolve the active
    # Flask app's manager rather than capture the latest factory closure.
    cold_page, _metadata = _native_page(cold_app)
    warm_page, _metadata = _native_page(warm_app)
    cold_ids = {
        component_id
        for item in _walk(cold_page)
        if isinstance((component_id := getattr(item, "id", None)), str)
    }
    warm_ids = {
        component_id
        for item in _walk(warm_page)
        if isinstance((component_id := getattr(item, "id", None)), str)
    }

    assert "initial-load-trigger" in cold_ids
    assert "risk-type-tabs" not in cold_ids
    assert "initial-load-trigger" not in warm_ids
    assert "risk-type-tabs" in warm_ids
    assert cold_manager.health.revision == 0
    assert warm_manager.health.revision == 1


def test_static_data_page_defers_its_default_csv_until_callback_mount() -> None:
    page = build_static_data_page()
    page_ids = {getattr(item, "id", None) for item in _walk(page)}
    table_container = next(
        item
        for item in _walk(page)
        if getattr(item, "id", None) == "static-data-table-container"
    )

    assert {"static-data-page", "static-data-file-selector"} <= page_ids
    assert table_container.children is None
    assert not any(
        str(component_id).startswith("static-data-table-")
        and component_id != "static-data-table-container"
        for component_id in page_ids
        if component_id is not None
    )

    options = {option["value"] for option in STATIC_FILE_OPTIONS}
    assert "s08_concerto.csv" in options
    assert "s10_historical_pl.csv" not in options
    assert "s08_plsend.csv" not in options


def test_static_data_columns_use_only_supported_dash_properties() -> None:
    table_layout = build_static_data_table("s01_readiness.csv")
    table = next(
        item
        for item in _walk(table_layout)
        if getattr(item, "id", None) == "static-data-table-s01_readiness"
    )

    assert table.columns
    assert all("resizable" not in column for column in table.columns)


def test_static_data_native_filters_are_case_insensitive() -> None:
    table_layout = build_static_data_table("s01_readiness.csv")
    table = next(
        item
        for item in _walk(table_layout)
        if getattr(item, "id", None) == "static-data-table-s01_readiness"
    )

    assert table.filter_action == "native"
    assert table.filter_options == {"case": "insensitive"}
