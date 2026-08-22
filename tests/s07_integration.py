"""One fast end-to-end refresh over the explicit fake connector boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Event, Thread
from time import monotonic, sleep

import pandas as pd
import pytest

from rebirth.domain.products import ProductConnectorAdapter
from rebirth.services.refresh import RiskRefreshManager
from rebirth.services.snapshots import StaleResetGenerationError
from rebirth.services.sources import (
    build_production_refresh_manager,
    get_portfolio_config,
    get_product_connector_adapters,
    get_risk_checker,
    get_risk_thresholds,
)


def test_refresh_uses_one_checker_date_for_checker_portfolios_and_risk_plan() -> None:
    checker_calls: list[pd.Timestamp] = []
    portfolio_calls: list[pd.Timestamp] = []
    risk_calls: list[tuple[str, pd.Timestamp]] = []
    open_calls: list[tuple[str, pd.Timestamp, str, str]] = []
    current_calls: list[tuple[str, pd.Timestamp, str, str]] = []
    market_status_calls: list[pd.Timestamp] = []

    def checker(checker_date: pd.Timestamp):
        checker_calls.append(pd.Timestamp(checker_date))
        return get_risk_checker(checker_date)

    def portfolios(portfolio_date: pd.Timestamp):
        portfolio_calls.append(pd.Timestamp(portfolio_date))
        return get_portfolio_config(portfolio_date)

    def market_status(market_date: pd.Timestamp) -> str:
        market_status_calls.append(pd.Timestamp(market_date))
        # The authoritative service can switch today's source independently of
        # the calendar date (for example after an official close is published).
        return "Live" if len(market_status_calls) == 1 else "OFFICIAL"

    wrapped: dict[str, ProductConnectorAdapter] = {}
    for source_type, adapter in get_product_connector_adapters().items():

        def risk(
            risk_date: pd.Timestamp,
            *,
            _source: str = source_type,
            _adapter: ProductConnectorAdapter = adapter,
        ) -> pd.DataFrame:
            risk_calls.append((_source, pd.Timestamp(risk_date)))
            return _adapter.risk(risk_date)

        def opened(
            open_date: pd.Timestamp,
            underlying: str,
            *,
            market_status: str,
            _source: str = source_type,
            _adapter: ProductConnectorAdapter = adapter,
        ) -> pd.DataFrame:
            open_calls.append(
                (_source, pd.Timestamp(open_date), underlying, market_status)
            )
            return _adapter.market_open(
                open_date, underlying, market_status=market_status
            )

        def current(
            market_date: pd.Timestamp,
            underlying: str,
            *,
            market_status: str,
            _source: str = source_type,
            _adapter: ProductConnectorAdapter = adapter,
        ) -> pd.DataFrame:
            current_calls.append(
                (_source, pd.Timestamp(market_date), underlying, market_status)
            )
            return _adapter.market_status(
                market_date, underlying, market_status=market_status
            )

        wrapped[source_type] = ProductConnectorAdapter(risk, opened, current)

    manager = RiskRefreshManager(
        portfolios,
        thresholds=get_risk_thresholds,
        risk_checker_loader=checker,
        market_status_resolver=market_status,
        connector_adapters=wrapped,
        # Sunday defaults to Friday Market Date and Thursday T-1 sources.
        clock=lambda: datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        trading_timezone="Europe/London",
        # The natural weekend rollback is age zero for retention purposes.
        max_history_days=1,
    )

    snapshot = manager.refresh(force_risk=True, force_pl=True)
    first_attempt_id = manager.progress.attempt_id

    expected_market_date = pd.Timestamp("2026-08-14")
    expected_checker_date = pd.Timestamp("2026-08-13")
    assert snapshot.errors == ()
    assert snapshot.revision == 1
    assert snapshot.system_date == pd.Timestamp("2026-08-16")
    assert snapshot.market_date == expected_market_date
    assert snapshot.checker_date == expected_checker_date
    assert snapshot.market_status == "Live"
    assert market_status_calls == [expected_market_date]
    assert checker_calls == [expected_checker_date]
    assert portfolio_calls == [expected_checker_date]
    assert len(risk_calls) == len(snapshot.risk_dates)
    assert {
        source: risk_date for source, risk_date in risk_calls
    } == snapshot.risk_dates
    assert [
        (source, underlying, status) for source, _, underlying, status in open_calls
    ] == [
        (source, underlying, status) for source, _, underlying, status in current_calls
    ]
    assert all(call[1] == expected_checker_date for call in open_calls)
    assert all(call[1] == expected_market_date for call in current_calls)
    assert all(call[3] == "Live" for call in open_calls)
    assert all(call[2].strip() for call in open_calls)
    assert all(not call[0].startswith("commo/") for call in open_calls)
    assert not snapshot.dashboard_frame.empty
    assert not snapshot.market_frame.empty
    assert first_attempt_id
    assert manager.progress.running is False
    commodity_market = snapshot.market_frame.loc[
        snapshot.market_frame["Source Type"].str.startswith("commo/")
    ]
    commodity_dashboard = snapshot.dashboard_frame.loc[
        snapshot.dashboard_frame["Source Type"].str.startswith("commo/")
    ]
    assert not commodity_market.empty
    assert commodity_market["Open"].eq(0.0).all()
    assert commodity_market["Current"].eq(0.0).all()
    assert commodity_market["Market Data Status"].eq("Commodity market disabled").all()
    assert (
        commodity_dashboard["Market Data Status"].eq("Commodity market disabled").all()
    )

    first_open_count = len(open_calls)
    official_snapshot = manager.refresh(
        force_pl=True,
        expected_revision=snapshot.revision,
    )
    assert manager.progress.attempt_id
    assert manager.progress.attempt_id != first_attempt_id
    assert official_snapshot.market_status == "OFFICIAL"
    assert market_status_calls == [
        expected_market_date,
        expected_market_date,
    ]
    assert [
        (source, underlying, status)
        for source, _, underlying, status in open_calls[first_open_count:]
    ] == [
        (source, underlying, status)
        for source, _, underlying, status in current_calls[first_open_count:]
    ]
    assert all(
        call[1] == expected_checker_date for call in open_calls[first_open_count:]
    )
    assert all(
        call[1] == expected_market_date for call in current_calls[first_open_count:]
    )
    assert all(call[3] == "OFFICIAL" for call in open_calls[first_open_count:])

    portfolio_snapshot = manager.refresh_portfolios(
        expected_revision=official_snapshot.revision
    )
    assert portfolio_snapshot.market_status == "OFFICIAL"
    assert len(market_status_calls) == 2


def test_historical_view_rejects_forced_risk_after_checker_date() -> None:
    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=get_risk_checker,
        market_status_resolver=lambda _date: "OFFICIAL",
        connector_adapters=get_product_connector_adapters(),
        clock=lambda: datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
    )

    with pytest.raises(
        ValueError,
        match=r"must not be after checker date 2026-06-30.*market date 2026-07-01",
    ):
        manager.refresh(
            view_date="2026-07-01",
            forced_dates={"ir/delta": "2026-07-01"},
        )


@pytest.mark.parametrize(
    ("refresh_kwargs", "message"),
    [
        ({"view_date": "2026-07-18"}, "view date must be a business day"),
        (
            {"forced_dates": {"ir/delta": "2026-07-18"}},
            "forced date for ir/delta must be a business day",
        ),
    ],
)
def test_explicit_weekend_dates_remain_invalid(
    refresh_kwargs: dict[str, object],
    message: str,
) -> None:
    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=get_risk_checker,
        market_status_resolver=lambda _date: "OFFICIAL",
        connector_adapters=get_product_connector_adapters(),
        clock=lambda: datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
    )

    with pytest.raises(ValueError, match=message):
        manager.refresh(**refresh_kwargs)


def test_market_status_resolver_rejects_ambiguous_values_before_other_sources() -> None:
    checker_calls: list[pd.Timestamp] = []

    def checker(checker_date: pd.Timestamp):
        checker_calls.append(checker_date)
        return get_risk_checker(checker_date)

    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=checker,
        market_status_resolver=lambda _date: "official",
        connector_adapters=get_product_connector_adapters(),
        clock=lambda: datetime(2026, 7, 20, 12, tzinfo=timezone.utc),
        trading_timezone="Europe/London",
    )

    with pytest.raises(ValueError, match="exactly 'Live' or 'OFFICIAL'"):
        manager.refresh()

    assert checker_calls == []


def test_reset_rejects_a_slow_old_commit_then_publishes_the_new_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = build_production_refresh_manager()
    baseline = manager.refresh(force_risk=True, force_pl=True)
    forced = manager.refresh(
        forced_dates={"ir/delta": baseline.risk_dates["ir/delta"]},
        view_date=baseline.market_date,
        commodity_market_enabled=baseline.commodity_market_enabled,
        risk_checker_enabled=baseline.risk_checker_enabled,
    )
    original_checker = manager._risk_checker_loader
    entered = Event()
    release = Event()
    checker_calls = 0

    def block_first_checker(checker_date: pd.Timestamp):
        nonlocal checker_calls
        checker_calls += 1
        if checker_calls == 1:
            entered.set()
            assert release.wait(10)
        return original_checker(checker_date)

    monkeypatch.setattr(manager, "_risk_checker_loader", block_first_checker)
    old_errors: list[BaseException] = []
    reset_results: list[tuple[int, object]] = []

    def run_old_refresh() -> None:
        try:
            manager.refresh(force_risk=True, expected_reset_generation=0)
        except BaseException as error:  # captured for an assertion in this thread
            old_errors.append(error)

    def run_reset() -> None:
        reset_results.append(manager.reset_refresh(expected_reset_generation=0))

    old_thread = Thread(target=run_old_refresh)
    reset_thread = Thread(target=run_reset)
    old_thread.start()
    assert entered.wait(10)
    reset_thread.start()
    deadline = monotonic() + 10
    while manager.reset_generation != 1 and monotonic() < deadline:
        sleep(0.01)
    assert manager.reset_generation == 1
    release.set()
    old_thread.join(10)
    reset_thread.join(10)

    assert not old_thread.is_alive()
    assert not reset_thread.is_alive()
    assert len(old_errors) == 1
    assert isinstance(old_errors[0], StaleResetGenerationError)
    assert len(reset_results) == 1
    generation, reset_snapshot = reset_results[0]
    assert generation == 1
    assert reset_snapshot.revision == forced.revision + 1
    assert reset_snapshot.errors == ()
    assert reset_snapshot.refresh_reason == "clear cache"
    assert reset_snapshot.forced_dates == {}
    assert reset_snapshot.forced_view_date is None
    assert reset_snapshot.commodity_market_enabled is forced.commodity_market_enabled
    assert reset_snapshot.risk_checker_enabled is forced.risk_checker_enabled


def test_failed_reset_retains_frames_and_stale_generation_avoids_source_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = build_production_refresh_manager()
    before = manager.refresh(force_risk=True, force_pl=True)

    def fail_checker(_checker_date: pd.Timestamp):
        raise RuntimeError("reset connector failure")

    monkeypatch.setattr(manager, "_risk_checker_loader", fail_checker)
    generation, failed = manager.reset_refresh(expected_reset_generation=0)

    assert generation == manager.reset_generation == 1
    assert failed.errors
    assert failed.refresh_reason == "clear cache"
    for name in (
        "combined_pl",
        "market_frame",
        "dashboard_frame",
        "unmapped_frame",
    ):
        pd.testing.assert_frame_equal(getattr(failed, name), getattr(before, name))
    assert failed.forced_dates == before.forced_dates
    assert failed.forced_view_date == before.forced_view_date
    assert failed.commodity_market_enabled is before.commodity_market_enabled
    assert failed.risk_checker_enabled is before.risk_checker_enabled

    source_calls: list[str] = []

    def unexpected_source(*_args, **_kwargs):
        source_calls.append("called")
        raise AssertionError("stale generation reached connector I/O")

    monkeypatch.setattr(manager, "_market_status_resolver", unexpected_source)
    monkeypatch.setattr(manager, "_risk_checker_loader", unexpected_source)
    monkeypatch.setattr(manager, "_config_source", unexpected_source)
    with pytest.raises(StaleResetGenerationError):
        manager.refresh(expected_reset_generation=0)
    with pytest.raises(StaleResetGenerationError):
        manager.refresh_portfolios(expected_reset_generation=0)
    with pytest.raises(StaleResetGenerationError):
        manager.reset_refresh(expected_reset_generation=0)
    assert source_calls == []
