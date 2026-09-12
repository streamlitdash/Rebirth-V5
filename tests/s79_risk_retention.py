"""Risk navigation retains one browser view and gates hidden refresh work."""

from dash import html, no_update

from cube.app import s07_factory as factory
from cube.app.s07_factory import build_app
from cube.pages.risk import layout
from cube.services.s05_sources import build_production_refresh_manager


def _callback(app, component_id):
    for metadata in app.callback_map.values():
        outputs = metadata["output"]
        outputs = outputs if isinstance(outputs, (list, tuple)) else [outputs]
        if any(output.component_id == component_id for output in outputs):
            return metadata["callback"].__wrapped__
    raise AssertionError(f"Missing callback for {component_id}")


def test_risk_route_does_not_rebuild_the_retained_page():
    assert layout().id == "risk-route-marker"
    assert getattr(layout(), "children", None) is None


def test_risk_is_lazy_and_navigation_keeps_the_same_browser_tree(monkeypatch):
    manager = build_production_refresh_manager()
    app = build_app(refresh_manager=manager)
    builds = []

    def cold_body(**kwargs):
        builds.append(kwargs)
        return html.Div(id="test-cold-risk")

    monkeypatch.setattr(factory, "build_initial_load_layout", cold_body)
    monkeypatch.setattr(
        factory.StartupCoordinator, "schedule_start", lambda *_args, **_kwargs: None
    )
    mount = _callback(app, "risk-page-host")
    assert mount(app.get_relative_path("/data"), False) == (
        no_update,
        {"display": "none"},
        no_update,
    )
    assert builds == []

    body, style, mounted = mount(app.get_relative_path("/"), False)
    assert body.id == "cube-page-container"
    assert body.children.id == "test-cold-risk"
    assert (style, mounted) == ({}, True)
    assert len(builds) == 1

    for path in ("/data", "/pnl", "/stock", "/static-data", "/"):
        next_body, _style, next_mounted = mount(app.get_relative_path(path), True)
        assert next_body is no_update  # Do not replace/resend the current tree.
        assert next_mounted is no_update
    assert len(builds) == 1


def test_retained_risk_callbacks_receive_only_the_visible_revision():
    app = build_app(refresh_manager=build_production_refresh_manager())
    owners = {"risk-grid", "aggregate-pl-grid", "promotion-generation-store"}
    for metadata in app.callback_map.values():
        outputs = metadata["output"]
        outputs = outputs if isinstance(outputs, (list, tuple)) else [outputs]
        if owners.intersection(
            output.component_id
            for output in outputs
            if isinstance(output.component_id, str)
        ):
            inputs = {item["id"] for item in metadata["inputs"]}
            assert "risk-page-revision" in inputs
            assert "data-revision-store" not in inputs
            assert "_pages_location" not in inputs


def test_retained_host_handles_public_route_prefix():
    app = build_app(
        refresh_manager=build_production_refresh_manager(),
        dash_kwargs={
            "requests_pathname_prefix": "/cube/",
            "routes_pathname_prefix": "/cube/",
        },
    )
    mount = _callback(app, "risk-page-host")
    assert mount("/cube/", True) == (no_update, {}, no_update)
    assert mount("/cube/data", True) == (no_update, {"display": "none"}, no_update)
