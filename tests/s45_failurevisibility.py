"""Cold-start failure reasons remain visible in progress and terminal logs."""

from __future__ import annotations

import logging
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from cube.app.s04_startup import StartupCoordinator
from cube.app.s05_progress import progress_payload
from cube.domain.s02_products import ProductConnectorAdapter
from cube.services.s05_sources import build_production_refresh_manager


class _FailingStartupManager:
    def __init__(self) -> None:
        self.stage_delays = {}
        self.health = SimpleNamespace(
            revision=0,
            refreshed_at=None,
            last_attempt_at=None,
            active_error_count=0,
        )
        # ``error`` mirrors the terminal state emitted by RiskRefreshManager;
        # the original financial stage must not be misreported as "error".
        self.progress = SimpleNamespace(
            attempt_id="refresh-1",
            function_name="get_ir_delta_market_status",
            source_type="ir/delta",
            underlying="USD SOFR",
            product_label="IR Delta",
            product_index=1,
            product_total=16,
            hold_seconds=0.0,
            stage="error",
            current=3,
            total=16,
            message="Refresh failed.",
            running=False,
            error=(
                "Refresh failed during market_status / ir/delta / IR Delta "
                "(RuntimeError; incident example123). Check the terminal for the "
                "exact reason."
            ),
            started_at=None,
            updated_at=None,
            finished_at=None,
        )

    def refresh(self, **_kwargs: object) -> None:
        raise RuntimeError("market gateway refused the request")


def _wait_for_failure(coordinator: StartupCoordinator) -> None:
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        if coordinator.status().phase == "failed":
            return
        time.sleep(0.01)
    raise AssertionError(f"startup did not fail: {coordinator.status()}")


def test_startup_failure_payload_and_terminal_keep_reason_and_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = _FailingStartupManager()
    logger = logging.getLogger("cube.tests.startup_failure")
    coordinator = StartupCoordinator(manager, logger=logger)

    with caplog.at_level(logging.ERROR, logger=logger.name):
        assert coordinator.start() is True
        _wait_for_failure(coordinator)
        deadline = time.monotonic() + 1.0
        while (
            not any(
                "Cube initial data load failed" in item.getMessage()
                for item in caplog.records
            )
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

    payload = progress_payload(manager, coordinator)
    assert payload["startup_phase"] == "failed"
    assert payload["startup_retryable"] is True
    assert "Initial data load failed" in payload["error"]
    assert "market_status / ir/delta / IR Delta" in payload["error"]
    assert "Check the terminal for the exact reason" in payload["error"]
    assert "market gateway refused the request" not in payload["error"]
    assert "during error" not in payload["error"]
    assert "ir/delta" in payload["error"]
    assert "IR Delta" in payload["error"]

    record = next(
        item
        for item in caplog.records
        if "Cube initial data load failed" in item.getMessage()
    )
    message = record.getMessage()
    assert "reason=RuntimeError: market gateway refused the request" in message
    assert "function=get_ir_delta_market_status" in message
    assert "source=ir/delta" in message
    assert "underlying=USD SOFR" in message
    assert "product=IR Delta" in message
    assert "item=1/16" in message
    assert "stage=error" not in message
    assert record.exc_info is not None
    assert record.exc_info[0] is RuntimeError
    assert "Traceback (most recent call last)" in caplog.text


def test_cold_refresh_error_logs_true_stage_and_populates_actionable_progress(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = build_production_refresh_manager()
    adapter = manager._connector_adapters["ir/delta"]

    def invalid_open(
        _date: pd.Timestamp,
        _underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        del market_status
        raise ValueError("open connector returned an invalid tenor contract")

    manager._connector_adapters["ir/delta"] = ProductConnectorAdapter(
        risk=adapter.risk,
        market_open=invalid_open,
        market_status=adapter.market_status,
    )

    with caplog.at_level(logging.ERROR, logger="cube.services.s06_refresh"):
        with pytest.raises(
            ValueError,
            match="open connector returned an invalid tenor contract",
        ):
            manager.refresh(force_risk=True, force_pl=True)

    record = next(
        item for item in caplog.records if "Risk refresh failed" in item.getMessage()
    )
    message = record.getMessage()
    assert (
        "reason=ValueError: open connector returned an invalid tenor contract"
        in message
    )
    assert "stage=market_open" in message
    assert "function=invalid_open" in message
    assert "source=ir/delta" in message
    assert "underlying=" in message
    assert "product=IR Delta" in message
    assert "item=1/" in message
    assert record.exc_info is not None
    assert record.exc_info[0] is ValueError
    assert "Traceback (most recent call last)" in caplog.text

    progress = manager.progress
    payload = progress_payload(manager)
    assert manager.health.revision == 0
    assert progress.stage == "error"
    assert progress.source_type == "ir/delta"
    assert progress.underlying
    assert progress.product_label == "IR Delta"
    assert progress.product_index == 1
    assert progress.product_total > 1
    assert "Refresh failed during market_open / ir/delta / IR Delta" in progress.error
    assert "ValueError" in progress.error
    assert "Check the terminal for the exact reason" in progress.error
    assert "open connector returned an invalid tenor contract" not in progress.error
    assert payload["error"] == progress.error
