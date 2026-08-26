"""Bounded application-log modal regressions."""

from __future__ import annotations

from collections.abc import Iterable
from io import StringIO
import logging
import sys
from types import SimpleNamespace

from dash import Dash, dcc, html, no_update

from cube.app import s08_applogs
from cube.app import s03_logging
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
    assert getattr(panel, "aria-modal") == "true"
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


def test_application_log_keeps_external_errors_and_redacts_secrets() -> None:
    handler = s03_logging._BoundedApplicationLogHandler()
    try:
        raise RuntimeError("connector failed")
    except RuntimeError:
        record = logging.LogRecord(
            "external.connector.client",
            logging.ERROR,
            __file__,
            1,
            "request failed Authorization: Bearer private-value",
            (),
            sys.exc_info(),
        )

    handler.emit(record)
    rendered = "\n".join(handler.snapshot())

    assert "request failed Authorization: [redacted]" in rendered
    assert "private-value" not in rendered
    assert "RuntimeError: connector failed" in rendered


def test_terminal_tee_forwards_print_text_and_copies_complete_lines() -> None:
    target = StringIO()
    s03_logging.clear_application_logs()
    try:
        tee = s03_logging._TerminalTee(target, "STDOUT")
        tee.write("manual connector note\n")

        assert target.getvalue() == "manual connector note\n"
        assert "STDOUT manual connector note" in (
            s03_logging.recent_application_log_text()
        )
    finally:
        s03_logging.clear_application_logs()


def test_attached_logger_bypasses_stdout_mirror_to_avoid_duplicates() -> None:
    target = StringIO()
    terminal_handler = logging.StreamHandler(s03_logging._TerminalTee(target, "STDOUT"))
    logger = logging.getLogger("dash.dash.app_logs_duplicate_test")
    previous_handlers = list(logger.handlers)
    previous_level = logger.level
    previous_propagate = logger.propagate
    s03_logging.clear_application_logs()
    try:
        logger.handlers = [terminal_handler]
        logger.setLevel(logging.ERROR)
        logger.propagate = False
        s03_logging.attach_application_log_handler(logger)

        logger.error("unique-dash-error")

        assert "unique-dash-error" in target.getvalue()
        assert s03_logging.recent_application_log_text().count("unique-dash-error") == 1
    finally:
        logger.handlers = previous_handlers
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        s03_logging.clear_application_logs()


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
