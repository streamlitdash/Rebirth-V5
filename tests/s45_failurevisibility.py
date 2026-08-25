"""Cold-start failure reasons remain visible in progress and terminal logs."""

from __future__ import annotations

from io import StringIO
import logging
import time
from types import SimpleNamespace

import pandas as pd
import pytest

from cube.app.s04_startup import StartupCoordinator
from cube.app.s05_progress import progress_payload
from cube.app.s07_factory import build_app
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


def test_credit_delta_soft_failure_is_visible_and_keeps_startup_usable(
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = build_production_refresh_manager()
    adapter = manager._connector_adapters["credit/delta"]

    def unavailable_credit_risk(_date: pd.Timestamp) -> pd.DataFrame:
        raise ConnectionError("credit risk service refused the request")

    manager._connector_adapters["credit/delta"] = ProductConnectorAdapter(
        risk=unavailable_credit_risk,
        market_open=adapter.market_open,
        market_status=adapter.market_status,
    )

    with caplog.at_level(logging.ERROR, logger="cube.services.s06_refresh"):
        snapshot = manager.refresh(force_risk=True, force_pl=True)

    assert snapshot.revision == 1
    assert not snapshot.dashboard_frame.empty
    assert manager._risk_frames["credit/delta"].empty
    assert len(snapshot.errors) == 1
    warning = snapshot.errors[0]
    assert "Credit Delta Risk/dRisk (credit/delta) unavailable" in warning
    assert "ConnectionError" in warning
    assert "Check the terminal for the exact reason" in warning
    assert "credit risk service refused the request" not in warning
    assert manager.control_snapshot.errors == snapshot.errors
    assert manager.health.active_error_count == 1

    record = next(
        item
        for item in caplog.records
        if "Risk/dRisk connector unavailable for credit/delta" in item.getMessage()
    )
    assert "reason=ConnectionError: credit risk service refused the request" in (
        record.getMessage()
    )
    assert record.exc_info is not None
    assert record.exc_info[0] is ConnectionError
    assert "Traceback (most recent call last)" in caplog.text

    app = build_app(refresh_manager=manager)
    metadata = next(
        item
        for item in app.callback_map.values()
        if "global-warning-summary.children" in str(item["output"])
    )
    assert metadata["inputs"] == [
        {"id": "refresh-commit-revision", "property": "children"}
    ]
    render_warning = metadata["callback"].__wrapped__
    children, class_name = render_warning(snapshot.revision)
    assert class_name == "global-warning-summary has-warnings"
    assert children.open is True
    assert "Loaded with 1 data warning(s)" in str(children)
    assert "Credit Delta Risk/dRisk (credit/delta) unavailable" in str(children)


def test_refresh_manager_can_route_exact_connector_traceback_to_preview_logger() -> (
    None
):
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    preview_logger = logging.Logger("dash.dash.preview-test", level=logging.INFO)
    preview_logger.addHandler(handler)
    manager = build_production_refresh_manager(logger=preview_logger)

    try:
        raise KeyError("credit delta mapping is absent")
    except KeyError as error:
        warning = manager._log_operational_failure(
            boundary="Risk/dRisk",
            error=error,
            source_type="credit/delta",
            product_label="Credit Delta",
            stage="risk",
        )

    terminal = stream.getvalue()
    assert "Credit Delta Risk/dRisk (credit/delta) unavailable" in warning
    assert "Risk/dRisk connector unavailable for credit/delta" in terminal
    assert "reason=KeyError: 'credit delta mapping is absent'" in terminal
    assert "Traceback (most recent call last)" in terminal
