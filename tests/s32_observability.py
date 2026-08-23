"""Structured V4 performance logging contracts."""

from __future__ import annotations

import logging
from unittest.mock import Mock

import pytest

from rebirth.app.s03_logging import (
    configure_runtime_logging,
    perf_span,
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
