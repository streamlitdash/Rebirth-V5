"""Structured V5 performance logging contracts."""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest

from cube.app.s03_logging import (
    clear_application_logs,
    configure_runtime_logging,
    perf_span,
    recent_application_log_text,
    reset_performance_warnings,
)


def test_perf_span_logs_bounded_identity_free_metrics() -> None:
    logger = Mock()
    with perf_span(
        logger,
        "history.read",
        revision=4,
        kind="risk",
        underlying="must-not-be-logged",
    ) as metrics:
        metrics.update(rows=100, cells=40, bytes=2_000)

    payload = logger.info.call_args.kwargs["extra"]["cube_performance"]
    assert payload["event"] == "history.read"
    assert payload["revision"] == 4
    assert payload["kind"] == "risk"
    assert payload["rows"] == 100
    assert payload["cells"] == 40
    assert payload["bytes"] == 2_000
    assert payload["status"] == "ok"
    assert "underlying" not in payload
    assert payload["duration_ms"] >= 0


def test_perf_span_warns_only_once_per_event_and_revision() -> None:
    reset_performance_warnings()
    logger = Mock()
    for _index in range(2):
        with perf_span(logger, "page.build", budget_ms=0.000001, revision=9):
            sum(range(10_000))

    assert logger.warning.call_count == 1
    assert logger.info.call_count == 1


def test_perf_span_logs_error_and_reraises() -> None:
    logger = Mock()
    with pytest.raises(RuntimeError, match="broken"):
        with perf_span(logger, "history.query"):
            raise RuntimeError("broken")

    payload = logger.info.call_args.kwargs["extra"]["cube_performance"]
    assert payload["status"] == "error"


@pytest.mark.parametrize("value", [0, -1])
def test_perf_span_rejects_nonpositive_budget(value: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        with perf_span(Mock(), "event", budget_ms=value):
            pass


def test_configure_runtime_logging_defaults_invalid_level_to_info(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUBE_LOG_LEVEL", "not-a-level")

    assert configure_runtime_logging() == logging.INFO


def test_configure_runtime_logging_resolves_level_without_python_311_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CUBE_LOG_LEVEL", "debug")

    assert configure_runtime_logging() == logging.DEBUG


def test_application_log_copy_exposes_sanitized_structured_errors() -> None:
    clear_application_logs()
    configure_runtime_logging()
    logger = logging.getLogger("cube.tests.browser_logs")

    try:
        raise KeyError("credit delta mapping is absent")
    except KeyError:
        logger.exception(
            "password=not-for-browser %s",
            {"Authorization": "Bearer also-not-for-browser", "token": "TOPSECRET"},
            extra={
                "cube_operator_event": {
                    "event": "Connector unavailable",
                    "status": "degraded",
                    "incident": "abc123",
                    "stage": "risk",
                    "source": "credit/delta",
                    "product": "Credit Delta",
                    "error_type": "KeyError",
                }
            },
        )
    logging.getLogger("urllib3.connectionpool").error("third-party-noise")

    rendered = recent_application_log_text()
    assert "Connector unavailable" in rendered
    assert "incident=abc123" in rendered
    assert "source=credit/delta" in rendered
    assert "product=Credit Delta" in rendered
    assert "error_type=KeyError" in rendered
    assert "credit delta mapping is absent" in rendered
    assert "Traceback (most recent call last)" in rendered
    assert "password=[redacted]" in rendered
    assert "Authorization" in rendered
    assert "[redacted]" in rendered
    assert "not-for-browser" not in rendered
    assert "TOPSECRET" not in rendered
    assert "third-party-noise" in rendered
    clear_application_logs()


def test_application_log_handler_is_idempotent_and_response_bounded() -> None:
    clear_application_logs()
    configure_runtime_logging()
    configure_runtime_logging()
    logger = logging.getLogger("cube.tests.browser_logs")

    logger.error(
        "raw-idempotent-message",
        extra={"cube_operator_event": {"event": "one-idempotent-record"}},
    )
    assert recent_application_log_text().count("one-idempotent-record") == 1
    assert recent_application_log_text().count("raw-idempotent-message") == 1
    for index in range(230):
        logger.info(
            "raw bounded payload %s",
            "x" * 500,
            extra={
                "cube_operator_event": {
                    "event": f"bounded-record-{index:03d}",
                    "revision": index,
                }
            },
        )

    rendered = recent_application_log_text()
    assert "bounded-record-229" in rendered
    assert "earlier application log record(s) omitted" in rendered
    assert len(rendered) <= 64_000
    clear_application_logs()
