"""Bounded application-log drawer regressions."""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace

from dash import Dash, dcc, html, no_update

from cube.app import s08_applogs
from cube.app.s08_applogs import build_app_log_panel, register_app_log_callbacks


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


def _callback_for_output(app: Dash, component_id: str, component_property: str):
    return next(
        metadata
        for metadata in app.callback_map.values()
        if any(
            output.component_id == component_id
            and output.component_property == component_property
            for output in (
                metadata["output"]
                if isinstance(metadata["output"], (list, tuple))
                else [metadata["output"]]
            )
        )
    )


def test_app_log_panel_is_text_only_and_does_not_poll() -> None:
    panel = build_app_log_panel()
    ids = {getattr(item, "id", None) for item in _walk(panel)}

    assert panel.hidden is True
    assert panel.role == "dialog"
    assert {
        "app-log-panel",
        "app-log-content",
        "app-log-refresh-button",
        "app-log-close-button",
    } <= ids
    assert not any(isinstance(item, dcc.Interval) for item in _walk(panel))
    content = next(
        item for item in _walk(panel) if getattr(item, "id", None) == "app-log-content"
    )
    assert isinstance(content, html.Pre)


def test_app_log_callback_opens_refreshes_and_closes_explicitly(monkeypatch) -> None:
    app = Dash(__name__)
    app.layout = html.Div(
        [
            html.Button(id="app-log-toggle", n_clicks=0),
            build_app_log_panel(),
        ]
    )
    reads: list[str] = []

    def source() -> str:
        value = f"bounded logs {len(reads) + 1}"
        reads.append(value)
        return value

    register_app_log_callbacks(app, log_source=source)
    metadata = _callback_for_output(app, "app-log-panel", "hidden")
    callback = metadata["callback"].__wrapped__

    monkeypatch.setattr(
        s08_applogs, "ctx", SimpleNamespace(triggered_id="app-log-toggle")
    )
    assert callback(1, 0, 0, True) == (False, "bounded logs 1", "true")

    monkeypatch.setattr(
        s08_applogs,
        "ctx",
        SimpleNamespace(triggered_id="app-log-refresh-button"),
    )
    assert callback(1, 1, 0, False) == (False, "bounded logs 2", "true")

    monkeypatch.setattr(
        s08_applogs,
        "ctx",
        SimpleNamespace(triggered_id="app-log-close-button"),
    )
    assert callback(1, 1, 1, False) == (True, no_update, "false")
    assert reads == ["bounded logs 1", "bounded logs 2"]
