"""Targeted committed-state reads avoid unrelated DataFrame copies."""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from feeds.s01_sources import build_production_refresh_manager


def test_targeted_manager_reads_copy_only_the_requested_frames(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    committed = manager._snapshot
    assert committed is not None

    original_copy = pd.DataFrame.copy
    copied_ids: list[int] = []

    def tracked_copy(frame: pd.DataFrame, deep: bool = True) -> pd.DataFrame:
        copied_ids.append(id(frame))
        return original_copy(frame, deep=deep)

    monkeypatch.setattr(pd.DataFrame, "copy", tracked_copy)

    control = manager.control_snapshot
    assert copied_ids == [id(committed.risk_status)]
    control.risk_status.iloc[0, 0] = "changed by caller"
    assert committed.risk_status.iloc[0, 0] != "changed by caller"
    assert control.risk_dates == committed.risk_dates
    changed_source = next(iter(control.risk_dates))
    control.risk_dates[changed_source] = pd.Timestamp("1900-01-01")
    assert committed.risk_dates[changed_source] != pd.Timestamp("1900-01-01")

    copied_ids.clear()
    pl = manager.pl_snapshot
    assert copied_ids == [id(committed.combined_pl)]
    pl.combined_pl.iloc[0, 0] = "changed by caller"
    assert committed.combined_pl.iloc[0, 0] != "changed by caller"

    copied_ids.clear()
    checker = manager.read_frame("risk_checker")
    assert copied_ids == [id(committed.risk_checker)]
    assert checker.revision == committed.revision
    checker.frame.iloc[0, 0] = "changed by caller"
    assert committed.risk_checker.iloc[0, 0] != "changed by caller"

    copied_ids.clear()
    dashboard = manager.read_frame("dashboard_frame")
    assert copied_ids == [id(committed.dashboard_frame)]
    assert dashboard.revision == committed.revision


def test_targeted_frame_read_rejects_unknown_names() -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)

    with pytest.raises(ValueError, match="unknown committed frame"):
        manager.read_frame("not_a_frame")  # type: ignore[arg-type]


def test_refresh_can_skip_its_result_copy_and_logs_bounded_metrics(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    manager = build_production_refresh_manager()
    original_copy = manager._copy_snapshot
    monkeypatch.setattr(
        manager,
        "_copy_snapshot",
        lambda _snapshot: pytest.fail("copy_result=False copied financial frames"),
    )
    caplog.set_level(logging.INFO, logger="core.s02_pipeline")

    assert manager.refresh(force_risk=True, force_pl=True, copy_result=False) is None

    record = next(
        item
        for item in caplog.records
        if item.getMessage().startswith("Cube refresh metrics:")
    )
    metrics = record.cube_metrics
    assert metrics["call_counts"]["risk"] == 16
    assert metrics["call_counts"]["pl"] == 16
    assert metrics["call_counts"]["result_copy"] == 0
    assert all(value >= 0 for value in metrics["stage_durations_seconds"].values())
    committed = manager._snapshot
    assert committed is not None
    assert metrics["row_counts"]["dashboard"] == len(committed.dashboard_frame)
    assert metrics["row_counts"]["market"] == len(committed.market_frame)
    assert not {"source_type", "underlying", "portfolio"} & set(metrics["call_counts"])

    monkeypatch.setattr(manager, "_copy_snapshot", original_copy)
    copied = manager.refresh(expected_revision=manager.health.revision)
    assert copied is not None
    assert copied.dashboard_frame is not committed.dashboard_frame

    revision = manager.health.revision
    previous_pl_frames = manager._pl_frames

    def fail_metrics(**_kwargs) -> None:
        raise RuntimeError("metrics sink unavailable")

    monkeypatch.setattr("core.s02_pipeline._log_refresh_metrics", fail_metrics)
    result = manager.refresh(force_pl=True)
    assert result is not None
    assert result.revision == revision + 1
    assert manager.health.revision == revision + 1
    assert manager._snapshot is not None
    assert manager._snapshot.revision == result.revision
    assert manager._pl_frames is not previous_pl_frames
    assert result.errors == ()
