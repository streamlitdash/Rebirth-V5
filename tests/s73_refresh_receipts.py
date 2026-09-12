"""Regression tests for the complete callback replacement and its exits."""
from pathlib import Path
import ast
import importlib
from types import SimpleNamespace

import pytest
from dash import no_update
from dash.exceptions import PreventUpdate

baseline = importlib.import_module("cube.pages.risk.s15_refresh")


class Manager:
    def __init__(self):
        self.health = SimpleNamespace(revision=7)
        self.snapshot = SimpleNamespace(revision=7, commodity_market_enabled=False,
                                        risk_checker_enabled=True, errors=())
        self.calls = []
        self.error = None
        self.return_errors = False

    @property
    def control_snapshot(self):
        return self.snapshot

    @property
    def progress(self):
        raise AssertionError("Callback receipt must not infer ownership from global progress")

    def refresh(self, **kwargs):
        self.calls.append(("refresh", kwargs))
        if self.error:
            raise self.error
        if self.return_errors:
            self.snapshot.errors = ("Connector failed; old revision retained",)
        else:
            self.snapshot.revision += 1
            self.health.revision = self.snapshot.revision

    def refresh_portfolios(self, **kwargs):
        self.refresh(**kwargs)
        self.calls[-1] = ("portfolios", kwargs)
        return self.snapshot

    def reset_refresh(self, **kwargs):
        self.refresh(**kwargs)
        self.calls[-1] = ("reset", kwargs)
        return 3, self.snapshot


def fixture():
    manager = Manager()
    cache = SimpleNamespace(cleared=False)
    cache.clear_reconstructable = lambda: setattr(cache, "cleared", True)
    source = Path(baseline.__file__).read_text(encoding="utf-8")
    parsed = ast.parse(source)
    fn = next(node for node in ast.walk(parsed) if isinstance(node, ast.FunctionDef) and node.name == "refresh_pipeline")
    tree = ast.Module(body=[fn], type_ignores=[])
    fn.decorator_list = []
    scope = dict(vars(baseline))

    def apply(manager, requested, **kwargs):
        manager.refresh(**kwargs)
        return SimpleNamespace(snapshot=manager.snapshot, committed=True,
                               requested_view_date=kwargs.get("view_date"))

    scope.update(
        refresh_manager=manager, cache=cache,
        coordinator=SimpleNamespace(status=lambda: SimpleNamespace(server_boot_id="test-boot")),
        app=SimpleNamespace(logger=SimpleNamespace(exception=lambda *args, **kwargs: None)),
        snapshot_forced_dates=lambda snapshot: {}, snapshot_forced_view_date=lambda snapshot: None,
        synchronize_committed_dashboard=lambda snapshot: (snapshot, object()),
        _refresh_status=lambda snapshot, **kwargs: ("Committed" if not snapshot.errors else "Failed", "" if not snapshot.errors else snapshot.errors[0], "error-log"),
        _automatic_refresh_due=lambda snapshot: True,
        apply_force_dates=apply,
        draft_forced_dates=lambda draft, **kwargs: draft.get("dates", {}),
        draft_base_dates=lambda draft, **kwargs: draft.get("base", {}),
        draft_view_date=lambda draft, **kwargs: draft.get("view"),
        draft_base_view_date=lambda draft, **kwargs: draft.get("base_view"),
        persisted_force_dates=lambda result: {"IR": "2026-09-10"},
    )
    exec(compile(tree, "complete_refresh_pipeline", "exec"), scope)
    return scope["refresh_pipeline"], manager, cache, scope


def request(trigger="refresh-pl-button", **updates):
    return dict(id="browser-request-1", trigger=trigger, count=1, **updates)


@pytest.mark.parametrize("trigger,mode,operation,flag", [
    ("refresh-pl-button", "pl", "refresh", "force_pl"),
    ("reload-risk-button", "reload", "refresh", "force_risk"),
    ("refresh-portfolios-button", "portfolios", "portfolios", None),
    ("clear-cache-button", "reset", "reset", None),
    ("auto-refresh-interval", "automatic", "refresh", "force_pl"),
    ("commo-market-toggle", "commo", "refresh", "commodity_market"),
    ("risk-checker-toggle", "checker", "refresh", None),
    ("force-risk-apply-button", "dates", "refresh", None),
])
def test_all_eight_actions_return_matching_complete_receipt(trigger, mode, operation, flag):
    fn, manager, cache, _scope = fixture()
    result = fn(request(trigger), {"dates": {"IR": "2026-09-10"}}, True, 5, 2)
    assert len(result) == 10
    assert result[0:2] == (8, 6)
    receipt = result[-1]
    assert receipt["request_id"] == "browser-request-1"
    assert receipt["mode"] == mode
    assert receipt["outcome"] == "complete"
    assert receipt["revision"] == 8
    assert receipt["server_boot_id"] == "test-boot"
    assert receipt["finished_at"]
    assert len(manager.calls) == 1 and manager.calls[0][0] == operation
    if flag:
        assert manager.calls[0][1][flag] is True
    if trigger in ("refresh-pl-button", "reload-risk-button", "auto-refresh-interval"):
        assert manager.calls[0][1]["copy_result"] is False
    if trigger == "clear-cache-button":
        assert result[7:9] == (3, 3)
        assert cache.cleared


@pytest.mark.parametrize("error,outcome", [
    (baseline.RefreshInProgressError("busy"), "busy"),
    (baseline.StaleRefreshError(6, 7), "rejected"),
    (baseline.StaleResetGenerationError(1, 2), "rejected"),
    (ValueError("invalid staged date"), "rejected"),
    (RuntimeError("adapter error"), "failed"),
])
def test_failure_and_rejection_always_return_receipt(error, outcome):
    fn, manager, _cache, _scope = fixture()
    manager.error = error
    result = fn(request(), {}, True, 5, 2)
    assert len(result) == 10 and result[0] is no_update and result[1] is no_update
    assert result[-1]["outcome"] == outcome
    assert result[-1]["revision"] == 7


@pytest.mark.parametrize("kind", ["unchanged_dates", "auto_disabled", "auto_not_due"])
def test_no_work_is_an_explicit_result(kind):
    fn, manager, _cache, scope = fixture()
    trigger = "force-risk-apply-button" if kind == "unchanged_dates" else "auto-refresh-interval"
    if kind == "auto_not_due":
        scope["_automatic_refresh_due"] = lambda snapshot: False
    result = fn(request(trigger), {}, kind != "auto_disabled", 5, 2)
    assert all(value is no_update for value in result[:9])
    assert result[-1]["outcome"] == "no_work"
    assert not manager.calls


def test_stale_draft_rejected_without_starting_writer():
    fn, manager, _cache, _scope = fixture()
    result = fn(request("force-risk-apply-button"), {"base": {"old": "date"}, "dates": {"new": "date"}}, True, 5, 2)
    assert result[-1]["outcome"] == "rejected"
    assert not manager.calls


def test_manager_failure_keeps_revision_and_reports_failed():
    fn, manager, _cache, _scope = fixture()
    manager.return_errors = True
    result = fn(request(), {}, True, 5, 2)
    assert result[0] == 7 and result[-1]["outcome"] == "failed"


def test_response_preparation_failure_is_not_lost_after_manager_finishes():
    fn, manager, _cache, scope = fixture()
    def fail(_snapshot):
        raise RuntimeError("held renderer preparation failed")
    scope["synchronize_committed_dashboard"] = fail
    result = fn(request(), {}, True, 5, 2)
    assert manager.health.revision == 8
    assert result[-1]["outcome"] == "failed"
    assert result[-1]["revision"] == 8


def test_empty_request_store_on_mount_does_not_replace_the_refresh_status():
    fn, manager, _cache, _scope = fixture()
    with pytest.raises(PreventUpdate):
        fn(None, {}, True, 5, 2)
    assert not manager.calls


@pytest.mark.parametrize("bad_request", [{}, {"id": "x", "trigger": "bad", "count": 1},
                                      {"id": "x", "trigger": "refresh-pl-button", "count": 0},
                                      {"id": "x", "trigger": "refresh-pl-button", "count": True}])
def test_invalid_request_never_calls_sources(bad_request):
    fn, manager, _cache, _scope = fixture()
    result = fn(bad_request, {}, True, 5, 2)
    assert result[-1]["outcome"] == "rejected" and not manager.calls


def test_dispatch_and_receipt_have_one_owner_and_keep_original_counter():
    from cube.app.s07_factory import build_app
    from cube.services.s05_sources import build_production_refresh_manager
    app = build_app(refresh_manager=build_production_refresh_manager())
    dispatch = next(item for item in app._callback_list if item["output"] == "refresh-action-request.data")
    bridge = next(item for item in app._callback_list if item["output"] == "refresh-action-result-ack.children")
    server = next(item for item in app._callback_list if "refresh-commit-revision.children" in item["output"])
    assert len(dispatch["inputs"]) == 8 and len(dispatch["state"]) == 1
    assert dispatch["output"] == "refresh-action-request.data"
    assert bridge["inputs"] == [{"id": "refresh-action-result", "property": "data"}]
    assert server["inputs"] == [{"id": "refresh-action-request", "property": "data"}]
    metadata = next(value for key, value in app.callback_map.items() if "refresh-commit-revision" in key)
    assert len(metadata["output"]) == 10
    assert metadata["output"][1].component_id == "refresh-result-store"
    assert metadata["output"][-1].component_id == "refresh-action-result"


@pytest.mark.parametrize("alive", [True, False])
def test_startup_worker_liveness_is_serialized_separately_from_success(alive):
    module = importlib.import_module("cube.app.s05_progress")
    scope = dict(vars(module))
    path = Path(module.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "progress_payload")
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), "exec"), scope)
    startup = SimpleNamespace(phase="succeeded", worker_alive=alive, attempt=1,
                              attempt_id="boot:1", server_boot_id="boot", elapsed_seconds=1,
                              retryable=False, error=None)
    coordinator = SimpleNamespace(status=lambda: startup, timeout_seconds=2400)
    manager = SimpleNamespace(progress=SimpleNamespace(running=False, stage="complete"),
                              health=SimpleNamespace(revision=1))
    payload = scope["progress_payload"](manager, coordinator)
    assert payload["startup_phase"] == "succeeded"
    assert payload["startup_worker_alive"] is alive
