"""One fast end-to-end refresh over the explicit temp connector boundaries."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from threading import Barrier, BrokenBarrierError, Event, Lock, Thread
from time import monotonic, sleep

import pandas as pd
import pytest

from cube.domain.s02_products import PRODUCT_SPECS, ProductConnectorAdapter
from cube.services.s06_refresh import (
    RiskRefreshManager,
    _ConnectorRefreshBudget,
    _OperationalCircuitBreaker,
)
from cube.services.s01_snapshots import StaleResetGenerationError
from cube.services.s05_sources import (
    build_production_refresh_manager,
    get_portfolio_config,
    get_product_connector_adapters,
    get_risk_checker,
    get_risk_thresholds,
)


def _market_test_manager(
    loader: Callable[..., object],
    *,
    wait: Callable[[float], None] = lambda _seconds: None,
    **manager_options: object,
) -> RiskRefreshManager:
    return RiskRefreshManager(
        lambda _date: pd.DataFrame(),
        thresholds=lambda: pd.DataFrame(),
        risk_checker_loader=lambda _date: (pd.DataFrame(), pd.DataFrame()),
        market_status_resolver=lambda _date: "OFFICIAL",
        risk_loader=lambda _date, _source: pd.DataFrame(),
        market_open_loader=loader,
        market_status_loader=loader,
        sleep=wait,
        **manager_options,
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
    assert sorted(
        (source, underlying, status) for source, _, underlying, status in open_calls
    ) == sorted(
        (source, underlying, status) for source, _, underlying, status in current_calls
    )
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
    first_current_count = len(current_calls)
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
    assert open_calls[first_open_count:] == []
    assert official_snapshot.open_refreshed_source_types == ()
    refreshed_current = current_calls[first_current_count:]
    assert refreshed_current
    assert all(call[1] == expected_market_date for call in refreshed_current)
    assert all(call[3] == "OFFICIAL" for call in refreshed_current)

    portfolio_snapshot = manager.refresh_portfolios(
        expected_revision=official_snapshot.revision
    )
    assert portfolio_snapshot.market_status == "OFFICIAL"
    assert len(market_status_calls) == 2


def test_configured_market_calls_overlap_and_keep_underlying_result_order() -> None:
    underlyings = ("CREDIT_A", "CREDIT_B", "CREDIT_C", "CREDIT_D")
    barrier = Barrier(len(underlyings))

    def loader(
        _source_type: str,
        _market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        try:
            barrier.wait(timeout=2)
        except BrokenBarrierError as exc:
            raise ValueError("market calls did not overlap") from exc
        return pd.DataFrame(
            {"Underlying": [underlying], "Market Status": [market_status]}
        )

    manager = _market_test_manager(loader, market_max_workers=len(underlyings))
    spec = PRODUCT_SPECS["creditdelta"]
    opened = manager._load_product_market_open(
        spec,
        pd.Timestamp("2026-08-20"),
        underlyings,
        market_status="OFFICIAL",
    )
    current = manager._load_product_market_status(
        spec,
        pd.Timestamp("2026-08-21"),
        underlyings,
        market_status="OFFICIAL",
    )

    assert opened["Underlying"].tolist() == list(underlyings)
    assert current["Underlying"].tolist() == list(underlyings)


def test_market_calls_are_serial_by_default() -> None:
    underlyings = ("CREDIT_A", "CREDIT_B", "CREDIT_C")
    lock = Lock()
    active = 0
    peak_active = 0

    def loader(
        _source_type: str,
        _market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        nonlocal active, peak_active
        with lock:
            active += 1
            peak_active = max(peak_active, active)
        sleep(0.01)
        with lock:
            active -= 1
        return pd.DataFrame(
            {"Underlying": [underlying], "Market Status": [market_status]}
        )

    result = _market_test_manager(loader)._load_product_market_status(
        PRODUCT_SPECS["creditdelta"],
        pd.Timestamp("2026-08-21"),
        underlyings,
        market_status="OFFICIAL",
    )

    assert peak_active == 1
    assert result["Underlying"].tolist() == list(underlyings)


def test_market_call_retries_four_times_then_succeeds() -> None:
    calls = 0
    waits: list[float] = []

    def loader(
        _source_type: str,
        _market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        if calls <= 4:
            raise ConnectionError("temporary market failure")
        return pd.DataFrame(
            {"Underlying": [underlying], "Market Status": [market_status]}
        )

    manager = _market_test_manager(
        loader,
        wait=waits.append,
        market_retries=4,
    )
    result = manager._load_product_market_status(
        PRODUCT_SPECS["creditdelta"],
        pd.Timestamp("2026-08-21"),
        ("CREDIT_A",),
        market_status="OFFICIAL",
    )

    assert calls == 5
    assert waits == [0.5, 0.5, 0.5, 0.5]
    assert result["Underlying"].tolist() == ["CREDIT_A"]


def test_operational_market_failures_are_soft_and_warn_once(caplog) -> None:
    calls: list[str] = []

    def loader(
        _source_type: str,
        _market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        del market_status
        calls.append(underlying)
        raise ConnectionError("upstream market service timed out")

    manager = _market_test_manager(loader)
    with caplog.at_level("WARNING", logger="cube.services.s06_refresh"):
        result = manager._load_product_market_status(
            PRODUCT_SPECS["creditdelta"],
            pd.Timestamp("2026-08-21"),
            ("CREDIT_A", "CREDIT_B", "CREDIT_C"),
            market_status="OFFICIAL",
        )

    warnings = [
        record
        for record in caplog.records
        if "Market connector unavailable for" in record.getMessage()
    ]
    assert calls == ["CREDIT_A", "CREDIT_B", "CREDIT_C"]
    assert result.empty
    assert result.columns.tolist() == [
        "Underlying",
        "Tenor Swap",
        "Tenor Swap Order",
        "Current",
    ]
    assert len(warnings) == 1
    assert "3 of 3 credit/delta market_status calls" in warnings[0].getMessage()


def test_blocking_connector_returns_by_deadline_and_same_key_is_not_relaunched() -> (
    None
):
    entered = Event()
    release = Event()
    calls = 0

    def loader(
        _source_type: str,
        _market_date: pd.Timestamp,
        _underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        nonlocal calls
        del market_status
        calls += 1
        entered.set()
        release.wait(10)
        return pd.DataFrame()

    manager = _market_test_manager(
        loader,
        connector_call_timeout_seconds=0.05,
    )
    started = monotonic()
    try:
        first = manager._load_product_market_status(
            PRODUCT_SPECS["creditdelta"],
            pd.Timestamp("2026-08-21"),
            ("CREDIT_A",),
            market_status="OFFICIAL",
        )
        first_elapsed = monotonic() - started
        assert entered.is_set()

        second_started = monotonic()
        second = manager._load_product_market_status(
            PRODUCT_SPECS["creditdelta"],
            pd.Timestamp("2026-08-21"),
            ("CREDIT_A",),
            market_status="OFFICIAL",
        )
        second_elapsed = monotonic() - second_started
    finally:
        release.set()

    assert first.empty
    assert second.empty
    assert calls == 1
    assert first_elapsed < 0.5
    assert second_elapsed < 0.2


def test_total_connector_budget_opens_market_circuit_before_callback_timeout() -> None:
    calls: list[str] = []

    def loader(
        _source_type: str,
        _market_date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        calls.append(underlying)
        sleep(0.04)
        return pd.DataFrame(
            {
                "Underlying": [underlying],
                "Current": [1.0],
                "Market Status": [market_status],
            }
        )

    manager = _market_test_manager(
        loader,
        connector_call_timeout_seconds=1.0,
    )
    circuit = _OperationalCircuitBreaker()
    budget = _ConnectorRefreshBudget(0.09)
    started = monotonic()
    result = manager._load_product_market_status(
        PRODUCT_SPECS["creditdelta"],
        pd.Timestamp("2026-08-21"),
        ("A", "B", "C", "D", "E"),
        market_status="OFFICIAL",
        circuit=circuit,
        budget=budget,
    )
    elapsed = monotonic() - started

    assert calls == ["A", "B", "C", "D", "E"][: len(calls)]
    assert 2 <= len(calls) < 5
    assert result["Underlying"].tolist() == calls[: len(result)]
    assert circuit.is_open
    assert elapsed < 0.5


def test_cold_start_commits_after_total_connector_budget_is_exhausted() -> None:
    risk_calls: list[str] = []
    wrapped: dict[str, ProductConnectorAdapter] = {}
    for source_type, adapter in get_product_connector_adapters().items():

        def slow_risk(
            risk_date: pd.Timestamp,
            *,
            _source_type: str = source_type,
            _adapter: ProductConnectorAdapter = adapter,
        ) -> pd.DataFrame:
            risk_calls.append(_source_type)
            sleep(0.03)
            return _adapter.risk(risk_date)

        wrapped[source_type] = ProductConnectorAdapter(
            risk=slow_risk,
            market_open=adapter.market_open,
            market_status=adapter.market_status,
            market_open_bulk=adapter.market_open_bulk,
            market_status_bulk=adapter.market_status_bulk,
        )

    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=get_risk_checker,
        market_status_resolver=lambda _date: "OFFICIAL",
        connector_adapters=wrapped,
        connector_call_timeout_seconds=0.5,
        connector_refresh_budget_seconds=0.14,
        clock=lambda: datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        trading_timezone="Europe/London",
    )

    started = monotonic()
    snapshot = manager.refresh(force_risk=True, force_pl=True)
    elapsed = monotonic() - started

    assert snapshot.revision == 1
    assert snapshot.errors == ()
    assert 1 <= len(risk_calls) < len(wrapped)
    assert not snapshot.dashboard_frame.empty
    assert elapsed < 5


def test_market_contract_failures_still_surface() -> None:
    def loader(
        _source_type: str,
        _market_date: pd.Timestamp,
        _underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        del market_status
        raise ValueError("invalid connector schema")

    manager = _market_test_manager(loader)
    with pytest.raises(ValueError, match="invalid connector schema"):
        manager._load_product_market_status(
            PRODUCT_SPECS["creditdelta"],
            pd.Timestamp("2026-08-21"),
            ("CREDIT_A",),
            market_status="OFFICIAL",
        )


def test_fx_delta_bulk_connectors_are_called_once_per_leg() -> None:
    per_underlying_calls: list[str] = []
    bulk_calls: list[tuple[str, tuple[str, ...]]] = []
    underlyings = ("EURUSD", "USDJPY", "GBPUSD")

    def per_underlying(
        _date: pd.Timestamp,
        underlying: str,
        *,
        market_status: str,
    ) -> pd.DataFrame:
        del market_status
        per_underlying_calls.append(underlying)
        raise AssertionError("per-Underlying hook must not be used")

    def bulk_open(
        _date: pd.Timestamp,
        requested: tuple[str, ...],
        *,
        market_status: str,
    ) -> pd.DataFrame:
        bulk_calls.append(("open", requested))
        return pd.DataFrame({"Underlying": requested, "Open": [1.0] * len(requested)})

    def bulk_status(
        _date: pd.Timestamp,
        requested: tuple[str, ...],
        *,
        market_status: str,
    ) -> pd.DataFrame:
        bulk_calls.append((market_status, requested))
        return pd.DataFrame(
            {
                "Underlying": requested,
                "Current": [1.1] * len(requested),
                "Market Status": [market_status] * len(requested),
            }
        )

    adapter = ProductConnectorAdapter(
        risk=lambda _date: pd.DataFrame(),
        market_open=per_underlying,
        market_status=per_underlying,
        market_open_bulk=bulk_open,
        market_status_bulk=bulk_status,
    )
    manager = _market_test_manager(
        lambda *_args, **_kwargs: pd.DataFrame(),
        connector_adapters={"fx/delta": adapter},
    )

    opened = manager._load_product_market_open(
        PRODUCT_SPECS["fxdelta"],
        pd.Timestamp("2026-08-20"),
        underlyings,
        market_status="OFFICIAL",
    )
    current = manager._load_product_market_status(
        PRODUCT_SPECS["fxdelta"],
        pd.Timestamp("2026-08-21"),
        underlyings,
        market_status="OFFICIAL",
    )

    assert bulk_calls == [("open", underlyings), ("OFFICIAL", underlyings)]
    assert per_underlying_calls == []
    assert opened["Underlying"].tolist() == list(underlyings)
    assert current["Underlying"].tolist() == list(underlyings)


def test_fx_delta_bulk_connector_rejects_unrequested_underlyings() -> None:
    def connector(*_args, **_kwargs) -> pd.DataFrame:
        return pd.DataFrame()

    def bulk_open(
        _date: pd.Timestamp,
        _underlyings: tuple[str, ...],
        *,
        market_status: str,
    ) -> pd.DataFrame:
        del market_status
        return pd.DataFrame(
            {"Underlying": ["EURUSD", "UNREQUESTED"], "Open": [1.0, 2.0]}
        )

    adapter = ProductConnectorAdapter(
        risk=lambda _date: pd.DataFrame(),
        market_open=connector,
        market_status=connector,
        market_open_bulk=bulk_open,
    )
    manager = _market_test_manager(
        connector,
        connector_adapters={"fx/delta": adapter},
    )

    with pytest.raises(ValueError, match="outside the requested scope"):
        manager._load_product_market_open(
            PRODUCT_SPECS["fxdelta"],
            pd.Timestamp("2026-08-20"),
            ("EURUSD",),
            market_status="OFFICIAL",
        )


def test_bulk_market_hooks_are_rejected_outside_fx_delta() -> None:
    def connector(*_args, **_kwargs) -> pd.DataFrame:
        return pd.DataFrame()

    adapter = ProductConnectorAdapter(
        risk=lambda _date: pd.DataFrame(),
        market_open=connector,
        market_status=connector,
        market_open_bulk=connector,
    )

    with pytest.raises(ValueError, match="only for 'fx/delta'"):
        _market_test_manager(
            connector,
            connector_adapters={"credit/delta": adapter},
        )


def test_cold_start_commits_when_market_service_is_operationally_unavailable(
    caplog,
) -> None:
    adapters = dict(get_product_connector_adapters())
    fx_delta = adapters["fx/delta"]
    unavailable_calls: list[str] = []

    def unavailable_bulk(
        _date: pd.Timestamp,
        _underlyings: tuple[str, ...],
        *,
        market_status: str,
    ) -> pd.DataFrame:
        del market_status
        unavailable_calls.append("called")
        raise TimeoutError("market service deadline exceeded")

    adapters["fx/delta"] = ProductConnectorAdapter(
        risk=fx_delta.risk,
        market_open=fx_delta.market_open,
        market_status=fx_delta.market_status,
        market_open_bulk=unavailable_bulk,
        market_status_bulk=unavailable_bulk,
    )
    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=get_risk_checker,
        market_status_resolver=lambda _date: "OFFICIAL",
        connector_adapters=adapters,
        clock=lambda: datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        trading_timezone="Europe/London",
    )

    with caplog.at_level("WARNING", logger="cube.services.s06_refresh"):
        snapshot = manager.refresh(force_risk=True, force_pl=True)

    fx_dashboard = snapshot.dashboard_frame.loc[
        snapshot.dashboard_frame["Source Type"].eq("fx/delta")
    ]
    circuit_warnings = [
        record
        for record in caplog.records
        if "Market circuit opened after bulk fx/delta" in record.getMessage()
    ]
    assert snapshot.revision == 1
    assert snapshot.errors == ()
    assert not fx_dashboard.empty
    assert fx_dashboard["Market Available"].eq(False).all()
    assert unavailable_calls == ["called"]
    assert len(circuit_warnings) == 1


def test_cold_start_commits_partial_snapshot_when_one_risk_connector_is_down() -> None:
    adapters = dict(get_product_connector_adapters())
    ir_delta = adapters["ir/delta"]
    risk_calls = 0

    def unavailable_risk(_date: pd.Timestamp) -> pd.DataFrame:
        nonlocal risk_calls
        risk_calls += 1
        raise ConnectionError("risk service unavailable")

    adapters["ir/delta"] = ProductConnectorAdapter(
        risk=unavailable_risk,
        market_open=ir_delta.market_open,
        market_status=ir_delta.market_status,
    )
    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=get_risk_checker,
        market_status_resolver=lambda _date: "OFFICIAL",
        connector_adapters=adapters,
        clock=lambda: datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        trading_timezone="Europe/London",
    )

    snapshot = manager.refresh(force_risk=True, force_pl=True)

    assert snapshot.revision == 1
    assert snapshot.errors == ()
    assert risk_calls == 1
    assert not snapshot.dashboard_frame.empty
    assert not snapshot.dashboard_frame["Source Type"].eq("ir/delta").any()
    assert manager._risk_frames["ir/delta"].empty


def test_cold_start_uses_default_readiness_when_checker_is_unavailable() -> None:
    def unavailable_checker(_date: pd.Timestamp):
        raise ConnectionError("checker service unavailable")

    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=unavailable_checker,
        market_status_resolver=lambda _date: "OFFICIAL",
        connector_adapters=get_product_connector_adapters(),
        clock=lambda: datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        trading_timezone="Europe/London",
    )

    snapshot = manager.refresh(force_risk=True, force_pl=True)

    assert snapshot.revision == 1
    assert snapshot.errors == ()
    assert snapshot.risk_checker.empty
    assert snapshot.risk_status["Age"].eq(0).all()
    assert snapshot.risk_status["Age Defaulted"].eq(True).all()
    assert not snapshot.dashboard_frame.empty


def test_cold_start_commits_risk_when_market_status_resolver_blocks() -> None:
    entered = Event()
    release = Event()

    def blocking_resolver(_date: pd.Timestamp) -> str:
        entered.set()
        release.wait(10)
        return "OFFICIAL"

    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=get_risk_checker,
        market_status_resolver=blocking_resolver,
        connector_adapters=get_product_connector_adapters(),
        connector_call_timeout_seconds=0.05,
        clock=lambda: datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        trading_timezone="Europe/London",
    )

    started = monotonic()
    try:
        snapshot = manager.refresh(force_risk=True, force_pl=True)
    finally:
        release.set()
    elapsed = monotonic() - started

    assert entered.is_set()
    assert elapsed < 5
    assert snapshot.revision == 1
    assert snapshot.errors == ()
    assert snapshot.market_status == "OFFICIAL"
    assert not snapshot.dashboard_frame.empty
    network_market_rows = snapshot.dashboard_frame.loc[
        ~snapshot.dashboard_frame["Source Type"].str.startswith("commo/")
    ]
    assert network_market_rows["Market Available"].eq(False).all()


def test_sequential_browser_auto_ticks_coalesce_to_one_connector_refresh() -> None:
    current_time = [datetime(2026, 8, 16, 12, tzinfo=timezone.utc)]
    resolver_calls: list[pd.Timestamp] = []

    def clock() -> datetime:
        return current_time[0]

    def resolver(market_date: pd.Timestamp) -> str:
        resolver_calls.append(pd.Timestamp(market_date))
        return "OFFICIAL"

    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=get_risk_checker,
        market_status_resolver=resolver,
        connector_adapters=get_product_connector_adapters(),
        clock=clock,
        trading_timezone="Europe/London",
    )
    initial = manager.refresh(force_risk=True, force_pl=True)
    calls_after_initial = len(resolver_calls)

    current_time[0] += timedelta(minutes=15)
    first_tick = manager.refresh(
        force_pl=True,
        reason="automatic 15-minute refresh",
        expected_revision=initial.revision,
    )
    current_time[0] += timedelta(seconds=1)
    second_tick = manager.refresh(
        force_pl=True,
        reason="automatic 15-minute refresh",
        # Simulate another browser whose revision has not observed first_tick.
        expected_revision=initial.revision,
    )

    assert first_tick.revision == initial.revision + 1
    assert second_tick.revision == first_tick.revision
    assert len(resolver_calls) == calls_after_initial + 1


def test_market_contract_failure_retains_the_atomic_last_good_snapshot() -> None:
    manager = RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        risk_checker_loader=get_risk_checker,
        market_status_resolver=lambda _date: "OFFICIAL",
        connector_adapters=get_product_connector_adapters(),
        clock=lambda: datetime(2026, 8, 16, 12, tzinfo=timezone.utc),
        trading_timezone="Europe/London",
    )
    baseline = manager.refresh(force_risk=True, force_pl=True)
    fx_delta = manager._connector_adapters["fx/delta"]

    def invalid_bulk(
        _date: pd.Timestamp,
        _underlyings: tuple[str, ...],
        *,
        market_status: str,
    ) -> pd.DataFrame:
        del market_status
        raise ValueError("connector returned an invalid market contract")

    manager._connector_adapters["fx/delta"] = ProductConnectorAdapter(
        risk=fx_delta.risk,
        market_open=fx_delta.market_open,
        market_status=fx_delta.market_status,
        market_open_bulk=fx_delta.market_open_bulk,
        market_status_bulk=invalid_bulk,
    )

    retained = manager.refresh(
        force_pl=True,
        expected_revision=baseline.revision,
    )

    assert retained.revision == baseline.revision
    assert retained.errors
    pd.testing.assert_frame_equal(retained.market_frame, baseline.market_frame)
    pd.testing.assert_frame_equal(retained.dashboard_frame, baseline.dashboard_frame)


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
