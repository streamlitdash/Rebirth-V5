"""Atomic refresh orchestration with fail-soft last-good reads."""

from __future__ import annotations

import logging
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timezone
from numbers import Real
from threading import Event, Lock, RLock, Thread
from typing import Callable, Hashable, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd

from cube.domain.s10_search import SearchCatalog
from cube.domain.s04_crossgamma import (
    CROSS_GAMMA_COLUMNS,
    build_cross_gamma_rows,
    cross_gamma_market_scope,
)
from cube.domain.s05_newtrades import (
    NEW_TRADE_COLUMNS,
    build_new_trade_rows,
    new_trade_market_scope,
)
from cube.domain.s03_calculations import (
    _as_timestamp,
    _merge_validated_market_legs,
    _require_market_status,
    _require_nonblank,
    _validate_multipliers,
    _with_dashboard_tenors,
    _with_supplemental_credit_sp01,
    checker_date_for,
    get_market_open,
    get_market_status,
    get_product_market_open,
    get_product_market_status,
    get_product_pl,
    get_product_risk,
    get_risk,
    market_date_for,
    risk_date_for,
)
from cube.domain.s07_governance import (
    _load_portfolio_config,
    load_config,
    load_reported_underlyings,
    load_thresholds,
)
from cube.domain.s02_products import (
    AGE,
    AGE_DEFAULTED,
    CANONICAL_PRODUCTS,
    CHECKER_DATE,
    CURRENT,
    EFFECTIVE_RISK_DATE,
    FORCE_RISK,
    GROUP,
    MARKET_AVAILABLE,
    MARKET_DATA_STATUS,
    MARKET_DATE,
    MARKET_MOVE,
    MARKET_STATUS,
    MRX_FILE,
    OPEN,
    OFFICIAL,
    PL,
    PORTFOLIO,
    PRODUCT,
    PRODUCT_SPECS,
    PRODUCT_SPECS_BY_SOURCE_TYPE,
    RISK_DATE,
    RISK,
    RISK_GREEK,
    RISK_TYPE,
    SOURCE_TYPE,
    SPLIT,
    SUGGESTED_RISK_DATE,
    UNDERLYING,
    VOL_SCORE,
    DRISK,
    DatedFrameLoader,
    GenericMarketConnector,
    GovernanceSource,
    MarketStatusResolver,
    PortfolioConfigSource,
    ProductConnectorAdapter,
    ProductSpec,
    ProductionIntegrationError,
    RiskCheckerResult,
)
from cube.services.s01_snapshots import (
    RefreshInProgressError,
    RefreshProgressSnapshot,
    RefreshSnapshot,
    StaleRefreshError,
    StaleResetGenerationError,
)
from cube.services.s02_state import (
    _RefreshStateMixin,
    _callable_name,
    _log_refresh_metrics,
    _product_progress_label,
    _safe_failure_location,
)


# Keep the operational logger name stable while V3 imports use the facade.
LOGGER = logging.getLogger("cube.services.s06_refresh")

_MARKET_MAX_WORKERS = 1
_MARKET_RETRIES = 0
_MARKET_RETRY_DELAY_SECONDS = 0.5
_CONNECTOR_CALL_TIMEOUT_SECONDS = 15.0
_CONNECTOR_REFRESH_BUDGET_SECONDS = 120.0
_CONNECTOR_MAX_OUTSTANDING_CALLS = 8
_AUTOMATIC_REFRESH_MIN_AGE_SECONDS = 14 * 60.0
_AUTOMATIC_REFRESH_REASON = "automatic 15-minute refresh"
_FAILURE_REASON_LIMIT = 500
_FAILURE_CONTEXT_VALUE_LIMIT = 120


def _bounded_failure_reason(error: BaseException) -> str:
    """Return the exception type and a bounded, single-line reason.

    Failure logs deliberately include no pandas frames or connector return
    values. The traceback is attached separately by ``LOGGER.exception`` so
    operators can diagnose the failing code path without this summary expanding
    into an unbounded log line.
    """

    detail = " ".join(str(error).split()) or "no detail"
    if len(detail) > _FAILURE_REASON_LIMIT:
        detail = f"{detail[: _FAILURE_REASON_LIMIT - 3]}..."
    return f"{type(error).__name__}: {detail}"


def _bounded_progress_value(value: object) -> str:
    """Render one internal progress label without allowing multiline logs."""

    text = " ".join(str(value).split())
    if len(text) > _FAILURE_CONTEXT_VALUE_LIMIT:
        text = f"{text[: _FAILURE_CONTEXT_VALUE_LIMIT - 3]}..."
    return text


def _failure_progress_context(progress: RefreshProgressSnapshot) -> str:
    """Describe only the bounded operational context of a failed refresh."""

    fields: list[str] = []
    for name, value in (
        ("stage", progress.stage),
        ("function", progress.function_name),
        ("source", progress.source_type),
        ("underlying", progress.underlying),
        ("product", progress.product_label),
    ):
        if value not in (None, ""):
            fields.append(f"{name}={_bounded_progress_value(value)}")
    if progress.product_index > 0 or progress.product_total > 0:
        fields.append(
            f"item={max(0, progress.product_index)}/{max(0, progress.product_total)}"
        )
    return " ".join(fields) or "unavailable"


def _failure_ui_message(
    error: BaseException,
    *,
    incident_id: str,
    progress: RefreshProgressSnapshot,
) -> str:
    """Show bounded failure context without exposing raw connector text."""

    labels: list[str] = []
    if progress.stage not in (None, "", "idle", "starting"):
        labels.append(_bounded_progress_value(progress.stage))
    if progress.source_type not in (None, ""):
        labels.append(_bounded_progress_value(progress.source_type))
    if progress.product_label not in (None, ""):
        labels.append(_bounded_progress_value(progress.product_label))
    context = f" during {' / '.join(labels)}" if labels else ""
    return (
        f"Refresh failed{context} ({type(error).__name__}; incident {incident_id}). "
        "Check the terminal for the exact reason."
    )


class ConnectorCallTimeoutError(TimeoutError):
    """Raised when one connector does not return inside its finite deadline."""


class ConnectorCallBusyError(TimeoutError):
    """Raised instead of duplicating a connector call which is still running."""


class ConnectorRefreshBudgetError(TimeoutError):
    """Raised when a refresh has spent its total external-call allowance."""


class _DaemonCallRecord:
    """One daemon-owned result slot retained only while its call is running."""

    def __init__(self) -> None:
        self.done = Event()
        self.result: object = None
        self.error: BaseException | None = None
        self.thread: Thread | None = None


class _DaemonConnectorCallGate:
    """Bound outstanding connector threads without waiting for timed-out work."""

    def __init__(self, *, max_outstanding: int) -> None:
        self._max_outstanding = int(max_outstanding)
        self._lock = RLock()
        self._active: dict[Hashable, _DaemonCallRecord] = {}
        self._sequence = 0

    def call(
        self,
        key: Hashable,
        function: Callable[[], object],
        *,
        timeout_seconds: float,
    ) -> object:
        """Run one call on a daemon thread and wait only for its deadline."""

        with self._lock:
            existing = self._active.get(key)
            if existing is not None and not existing.done.is_set():
                raise ConnectorCallBusyError(
                    "A matching connector call is still running after an earlier timeout."
                )
            if existing is not None:
                self._active.pop(key, None)
            if len(self._active) >= self._max_outstanding:
                raise ConnectorCallBusyError(
                    "The bounded connector call gate is full of still-running calls."
                )

            record = _DaemonCallRecord()
            self._sequence += 1

            def invoke() -> None:
                try:
                    record.result = function()
                except BaseException as error:  # re-raised on the refresh owner
                    record.error = error
                finally:
                    record.done.set()
                    with self._lock:
                        if self._active.get(key) is record:
                            self._active.pop(key, None)

            worker = Thread(
                target=invoke,
                name=f"cube-connector-{self._sequence}",
                daemon=True,
            )
            record.thread = worker
            self._active[key] = record
            worker.start()

        if not record.done.wait(timeout_seconds):
            raise ConnectorCallTimeoutError(
                f"Connector call exceeded its {timeout_seconds:g}-second deadline."
            )
        if record.error is not None:
            raise record.error
        return record.result


class _ConnectorRefreshBudget:
    """Thread-safe cumulative wall-time allowance for external connector calls."""

    def __init__(self, seconds: float) -> None:
        self._remaining = float(seconds)
        self._lock = RLock()

    def call_timeout(self, maximum: float) -> tuple[float, bool]:
        """Return this call's allowance and whether the total budget is tighter."""

        with self._lock:
            if self._remaining <= 0:
                raise ConnectorRefreshBudgetError(
                    "The refresh connector elapsed-time budget is exhausted."
                )
            timeout = min(float(maximum), self._remaining)
            return timeout, timeout < float(maximum)

    def consume(self, seconds: float) -> None:
        with self._lock:
            self._remaining = max(0.0, self._remaining - max(0.0, float(seconds)))

    @property
    def is_exhausted(self) -> bool:
        with self._lock:
            return self._remaining <= 0


class _OperationalCircuitBreaker:
    """One refresh-scoped latch opened by an operational connector failure."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._error: Exception | None = None

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._error is not None

    def trip(self, error: Exception) -> bool:
        """Open once and return whether this failure changed the circuit state."""

        with self._lock:
            if self._error is not None:
                return False
            self._error = error
            return True


class RiskRefreshManager(_RefreshStateMixin):
    """Transactional refresh cache with non-blocking last-good-snapshot reads.

    REAL CONNECTOR INTEGRATION POINT: supply the real portfolio ``config``,
    approved ``thresholds``, optional ``reported_underlyings``, combined
    ``risk_checker_loader``, and product connectors here. Prefer
    ``connector_adapters`` when product APIs or schemas differ; generic loaders
    cover any source types not present in that mapping. Construction fails
    closed if any required source is uncovered.
    """

    def __init__(
        self,
        config: PortfolioConfigSource,
        *,
        thresholds: GovernanceSource | None = None,
        reported_underlyings: GovernanceSource | None = None,
        # PRODUCTION INTEGRATION POINT: one call returns readiness then inventory.
        risk_checker_loader: Callable[[pd.Timestamp], RiskCheckerResult],
        # PRODUCTION INTEGRATION POINT: called exactly once for each refresh view.
        market_status_resolver: MarketStatusResolver,
        # PRODUCTION INTEGRATION POINT: generic fallbacks for uncovered products.
        risk_loader: Callable[[pd.Timestamp, str], pd.DataFrame] | None = None,
        cross_gamma_matrix_loader: DatedFrameLoader | None = None,
        new_trades_loader: DatedFrameLoader | None = None,
        market_open_loader: GenericMarketConnector | None = None,
        market_status_loader: GenericMarketConnector | None = None,
        # PRODUCTION INTEGRATION POINT: preferred per-source connector mapping.
        connector_adapters: Mapping[str, ProductConnectorAdapter] | None = None,
        multipliers: Mapping[str, float] | None = None,
        stage_delays: Mapping[str, float] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] | None = None,
        trading_timezone: str = "UTC",
        max_history_days: int = 3650,
        market_max_workers: int = _MARKET_MAX_WORKERS,
        market_retries: int = _MARKET_RETRIES,
        market_retry_delay_seconds: float = _MARKET_RETRY_DELAY_SECONDS,
        connector_call_timeout_seconds: float = _CONNECTOR_CALL_TIMEOUT_SECONDS,
        connector_refresh_budget_seconds: float = _CONNECTOR_REFRESH_BUDGET_SECONDS,
        automatic_refresh_min_age_seconds: float = (_AUTOMATIC_REFRESH_MIN_AGE_SECONDS),
    ) -> None:
        # Source-type keys here are the connector contracts (for example
        # ``fx/delta``), not dashboard product keys (for example ``fxdelta``).
        adapters = dict(connector_adapters or {})
        unknown_adapters = sorted(set(adapters) - set(PRODUCT_SPECS_BY_SOURCE_TYPE))
        if unknown_adapters:
            raise ValueError(
                f"unknown connector adapter source types: {unknown_adapters}"
            )
        for source_type, adapter in adapters.items():
            if not isinstance(adapter, ProductConnectorAdapter):
                raise TypeError(
                    f"connector adapter for {source_type!r} must be a "
                    "ProductConnectorAdapter"
                )
            invalid_hooks = [
                hook
                for hook in ("risk", "market_open", "market_status")
                if not callable(getattr(adapter, hook, None))
            ]
            if invalid_hooks:
                raise TypeError(
                    f"connector adapter for {source_type!r} has non-callable hooks: "
                    f"{invalid_hooks}"
                )
            bulk_hooks = {
                hook: getattr(adapter, hook, None)
                for hook in ("market_open_bulk", "market_status_bulk")
            }
            invalid_bulk_hooks = [
                hook
                for hook, connector in bulk_hooks.items()
                if connector is not None and not callable(connector)
            ]
            if invalid_bulk_hooks:
                raise TypeError(
                    f"connector adapter for {source_type!r} has non-callable hooks: "
                    f"{invalid_bulk_hooks}"
                )
            if source_type != "fx/delta" and any(bulk_hooks.values()):
                raise ValueError(
                    "bulk market connector hooks are supported only for 'fx/delta'; "
                    f"found bulk hook on {source_type!r}"
                )
        if thresholds is None:
            raise ProductionIntegrationError(
                "RiskRefreshManager requires an explicit approved threshold source"
            )
        if not callable(risk_checker_loader):
            raise TypeError("risk_checker_loader must be callable")
        if not callable(market_status_resolver):
            raise TypeError("market_status_resolver must be callable")
        uncovered = set(PRODUCT_SPECS_BY_SOURCE_TYPE) - set(adapters)
        generic_loaders = {
            "risk_loader": risk_loader,
            "market_open_loader": market_open_loader,
            "market_status_loader": market_status_loader,
        }
        missing_generic = [
            name for name, loader in generic_loaders.items() if loader is None
        ]
        if uncovered and missing_generic:
            raise ProductionIntegrationError(
                "Source types without ProductConnectorAdapter coverage require all "
                f"three generic loaders; uncovered={sorted(uncovered)}, "
                f"missing={missing_generic}"
            )
        invalid_generic = [
            name
            for name, loader in generic_loaders.items()
            if loader is not None and not callable(loader)
        ]
        if invalid_generic:
            raise TypeError(
                f"generic connector loaders must be callable: {invalid_generic}"
            )
        invalid_raw_loaders = [
            name
            for name, loader in (
                ("cross_gamma_matrix_loader", cross_gamma_matrix_loader),
                ("new_trades_loader", new_trades_loader),
            )
            if loader is not None and not callable(loader)
        ]
        if invalid_raw_loaders:
            raise TypeError(
                f"supplemental raw loaders must be callable: {invalid_raw_loaders}"
            )
        self._config_source = config
        self._threshold_source = thresholds
        self._reported_underlying_source = reported_underlyings
        # Callable governance boundaries are intentionally lazy. Production
        # passes a dated Portfolio connector and a zero-argument threshold
        # connector, so constructing the WSGI app performs no source I/O before
        # the browser sees the refresh hero.
        # Existing DataFrame/path callers retain their fail-fast validation.
        self._config = None if callable(config) else load_config(config)
        self._thresholds = None if callable(thresholds) else load_thresholds(thresholds)
        if callable(reported_underlyings):
            self._reported_underlyings = None
        else:
            self._reported_underlyings = load_reported_underlyings(reported_underlyings)
        self._risk_checker_loader = risk_checker_loader
        self._market_status_resolver = market_status_resolver
        self._risk_loader = risk_loader or get_risk
        self._cross_gamma_matrix_loader = cross_gamma_matrix_loader
        self._new_trades_loader = new_trades_loader
        self._market_open_loader = market_open_loader or get_market_open
        self._market_status_loader = market_status_loader or get_market_status
        self._connector_adapters = adapters
        self._multipliers = _validate_multipliers(multipliers)
        configured_delays = dict(stage_delays or {})
        unknown_delays = sorted(set(configured_delays) - {"risk_product"})
        if unknown_delays:
            raise ValueError(
                "Only the operator-visible 'risk_product' progress hold is "
                f"supported; unknown stage delays: {unknown_delays}"
            )
        raw_risk_product_delay = configured_delays.get("risk_product", 0.0)
        if isinstance(raw_risk_product_delay, (bool, np.bool_)) or not isinstance(
            raw_risk_product_delay, Real
        ):
            raise TypeError("stage delay 'risk_product' must be a real number")
        risk_product_delay = float(raw_risk_product_delay)
        if not np.isfinite(risk_product_delay):
            raise ValueError("stage delay 'risk_product' must be finite")
        if risk_product_delay < 0:
            raise ValueError("stage delays must be zero or greater")
        self._stage_delays = {"risk_product": risk_product_delay}
        for value, label, minimum in (
            (market_max_workers, "market_max_workers", 1),
            (market_retries, "market_retries", 0),
        ):
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, int):
                raise TypeError(f"{label} must be an integer")
            if value < minimum:
                comparator = "greater than zero" if minimum == 1 else "zero or greater"
                raise ValueError(f"{label} must be {comparator}")
        if isinstance(market_retry_delay_seconds, (bool, np.bool_)) or not isinstance(
            market_retry_delay_seconds, Real
        ):
            raise TypeError("market_retry_delay_seconds must be a real number")
        retry_delay = float(market_retry_delay_seconds)
        if not np.isfinite(retry_delay):
            raise ValueError("market_retry_delay_seconds must be finite")
        if retry_delay < 0:
            raise ValueError("market_retry_delay_seconds must be zero or greater")
        self._market_max_workers = market_max_workers
        self._market_retries = market_retries
        self._market_retry_delay_seconds = retry_delay
        timeout_settings = (
            (
                connector_call_timeout_seconds,
                "connector_call_timeout_seconds",
                False,
            ),
            (
                connector_refresh_budget_seconds,
                "connector_refresh_budget_seconds",
                False,
            ),
            (
                automatic_refresh_min_age_seconds,
                "automatic_refresh_min_age_seconds",
                True,
            ),
        )
        validated_timeouts: dict[str, float] = {}
        for value, label, allow_zero in timeout_settings:
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
                raise TypeError(f"{label} must be a real number")
            number = float(value)
            if not np.isfinite(number):
                raise ValueError(f"{label} must be finite")
            if number < 0 or (number == 0 and not allow_zero):
                requirement = "zero or greater" if allow_zero else "greater than zero"
                raise ValueError(f"{label} must be {requirement}")
            validated_timeouts[label] = number
        self._connector_call_timeout_seconds = validated_timeouts[
            "connector_call_timeout_seconds"
        ]
        self._connector_refresh_budget_seconds = validated_timeouts[
            "connector_refresh_budget_seconds"
        ]
        self._automatic_refresh_min_age_seconds = validated_timeouts[
            "automatic_refresh_min_age_seconds"
        ]
        self._connector_gate = _DaemonConnectorCallGate(
            max_outstanding=_CONNECTOR_MAX_OUTSTANDING_CALLS
        )
        if int(max_history_days) <= 0:
            raise ValueError("max_history_days must be greater than zero")
        self._max_history_days = int(max_history_days)
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        if not isinstance(trading_timezone, str) or not trading_timezone.strip():
            raise TypeError("trading_timezone must be a nonblank IANA timezone name")
        self._trading_timezone_name = trading_timezone.strip()
        try:
            self._trading_timezone = ZoneInfo(self._trading_timezone_name)
        except ZoneInfoNotFoundError as exc:
            raise ValueError(
                f"unknown IANA trading timezone {self._trading_timezone_name!r}"
            ) from exc
        # A refresh can be long-running, but only one writer may calculate at a
        # time. Committed state has its own short-held lock so readers can keep
        # using the last successful snapshot while that calculation is running.
        self._refresh_lock = RLock()
        self._state_lock = RLock()
        self._progress_lock = RLock()
        self._operational_warning_lock = RLock()
        self._operational_warnings: list[str] = []
        self._progress = RefreshProgressSnapshot(
            attempt_id=None,
            function_name=None,
            source_type=None,
            underlying=None,
            product_label=None,
            product_index=0,
            product_total=0,
            hold_seconds=0.0,
            stage="idle",
            current=0,
            total=0,
            message="No refresh has run.",
            running=False,
            error=None,
            started_at=None,
            updated_at=None,
            finished_at=None,
        )
        self._risk_frames: dict[str, pd.DataFrame] = {}
        self._market_open_frames: dict[str, pd.DataFrame] = {}
        self._market_status_frames: dict[str, pd.DataFrame] = {}
        self._market_frames: dict[str, pd.DataFrame] = {}
        self._pl_frames: dict[str, pd.DataFrame] = {}
        self._overlay_frames: dict[str, pd.DataFrame] = {}
        self._risk_dates: dict[str, pd.Timestamp] = {}
        self._market_date: pd.Timestamp | None = None
        self._search_catalog: SearchCatalog | None = None
        self._snapshot: RefreshSnapshot | None = None
        self._reset_generation = 0

    def _call_connector(
        self,
        key: Hashable,
        function: Callable[[], object],
        *,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> object:
        """Call one external boundary without exceeding its or the refresh deadline."""

        timeout = self._connector_call_timeout_seconds
        budget_limited = False
        if budget is not None:
            timeout, budget_limited = budget.call_timeout(timeout)
        started = time.monotonic()
        try:
            return self._connector_gate.call(
                key,
                function,
                timeout_seconds=timeout,
            )
        except ConnectorCallTimeoutError as error:
            if budget_limited:
                raise ConnectorRefreshBudgetError(
                    "The refresh connector elapsed-time budget was exhausted "
                    "while a connector was running."
                ) from error
            raise
        finally:
            if budget is not None:
                budget.consume(time.monotonic() - started)

    @staticmethod
    def _empty_product_risk(spec: ProductSpec) -> pd.DataFrame:
        """Return the validated Risk cache shape for an unavailable connector."""

        columns = [
            RISK_TYPE,
            RISK_GREEK,
            SPLIT,
            UNDERLYING,
            *spec.tenor_columns,
            PORTFOLIO,
            GROUP,
            RISK,
            DRISK,
            VOL_SCORE,
        ]
        frame = pd.DataFrame(columns=columns)
        return frame.astype(
            {
                RISK: "float64",
                DRISK: "float64",
                VOL_SCORE: "float64",
            }
        )

    @staticmethod
    def _is_operational_connector_error(error: BaseException) -> bool:
        """Distinguish availability failures from connector contract failures."""

        return isinstance(error, Exception) and not isinstance(
            error,
            (AssertionError, MemoryError, TypeError, ValueError),
        )

    def _reset_operational_warnings(self) -> None:
        """Start one refresh-scoped collection of fail-soft source warnings."""

        with self._operational_warning_lock:
            self._operational_warnings = []

    def _operational_warning_snapshot(self) -> tuple[str, ...]:
        """Return the bounded warnings produced by the active refresh."""

        with self._operational_warning_lock:
            return tuple(self._operational_warnings)

    def _log_operational_failure(
        self,
        *,
        boundary: str,
        error: Exception,
        source_type: str | None = None,
        product_label: str | None = None,
        stage: str | None = None,
    ) -> str:
        """Persist a safe UI warning and log the exact operational failure."""

        incident_id = uuid.uuid4().hex[:10]
        suffix = "" if source_type is None else f" for {source_type}"
        display_label = f"{boundary}{suffix}"
        if product_label:
            display_label = f"{product_label} {boundary}"
            if source_type is not None:
                display_label = f"{display_label} ({source_type})"
        warning = (
            f"{display_label} unavailable ({type(error).__name__}; incident "
            f"{incident_id}). Missing data retained. Check the terminal for the "
            "exact reason."
        )
        with self._operational_warning_lock:
            self._operational_warnings.append(warning)
        LOGGER.error(
            "%s connector unavailable%s; continuing with shaped missing data. "
            "incident=%s stage=%s product=%s reason=%s",
            boundary,
            suffix,
            incident_id,
            stage or "unknown",
            product_label or "unknown",
            _bounded_failure_reason(error),
            exc_info=(type(error), error, error.__traceback__),
        )
        return warning

    def _load_portfolio_config_source(
        self,
        portfolio_date: pd.Timestamp,
        *,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        if not callable(self._config_source):
            return _load_portfolio_config(self._config_source, portfolio_date)
        result = self._call_connector(
            ("governance", "portfolio_config"),
            lambda: _load_portfolio_config(self._config_source, portfolio_date),
            budget=budget,
        )
        return result

    def _load_threshold_source(
        self,
        *,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        if not callable(self._threshold_source):
            return load_thresholds(self._threshold_source)
        result = self._call_connector(
            ("governance", "thresholds"),
            lambda: load_thresholds(self._threshold_source),
            budget=budget,
        )
        return result

    def _load_reported_underlyings_with_deadline(
        self,
        *,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        if not callable(self._reported_underlying_source):
            return load_reported_underlyings(self._reported_underlying_source)
        result = self._call_connector(
            ("governance", "reported_underlyings"),
            lambda: load_reported_underlyings(self._reported_underlying_source),
            budget=budget,
        )
        return result

    @staticmethod
    def _validate_risk_readiness(raw_status: object) -> pd.DataFrame:
        """Validate pair readiness and synthesize absent catalogue pairs at Age 0."""
        if not isinstance(raw_status, pd.DataFrame):
            raise TypeError("risk_checker_loader readiness result must be a DataFrame")
        required = [RISK_TYPE, RISK_GREEK, AGE]
        if list(raw_status.columns) != required:
            raise ValueError(
                f"risk readiness columns must be exactly {required} in that order; "
                f"found {list(raw_status.columns)}"
            )
        status = raw_status.copy()
        status = _require_nonblank(status, [RISK_TYPE, RISK_GREEK], "risk readiness")
        if status[AGE].map(lambda value: isinstance(value, (bool, np.bool_))).any():
            raise ValueError("risk readiness Age must not contain booleans")
        age = pd.to_numeric(status[AGE], errors="coerce")
        invalid_age = age.isna() | ~np.isfinite(age) | age.lt(0) | age.mod(1).ne(0)
        if invalid_age.any():
            rows = status.index[invalid_age].tolist()[:5]
            raise ValueError(
                "risk readiness Age must contain only non-negative integers; "
                f"invalid rows {rows}"
            )
        status[AGE] = age.astype("int64")
        pair_columns = [RISK_TYPE, RISK_GREEK]
        if status.duplicated(pair_columns).any():
            raise ValueError(
                "risk readiness contains duplicate Risk Type/Risk Greek pairs"
            )

        catalogue = pd.DataFrame(
            [
                {
                    SOURCE_TYPE: spec.source_type,
                    RISK_TYPE: spec.risk_type,
                    RISK_GREEK: spec.risk_greek,
                }
                for spec in PRODUCT_SPECS.values()
            ]
        )
        known_pairs = set(catalogue[pair_columns].itertuples(index=False, name=None))
        supplied_pairs = set(status[pair_columns].itertuples(index=False, name=None))
        unknown_pairs = sorted(supplied_pairs - known_pairs)
        if unknown_pairs:
            raise ValueError(
                "risk readiness contains unknown Risk Type/Risk Greek pairs; "
                f"unknown={unknown_pairs}"
            )

        completed = catalogue.merge(
            status,
            on=pair_columns,
            how="left",
            validate="one_to_one",
        )
        completed[AGE_DEFAULTED] = completed[AGE].isna()
        completed[AGE] = completed[AGE].fillna(0).astype("int64")
        return completed[[SOURCE_TYPE, RISK_TYPE, RISK_GREEK, AGE, AGE_DEFAULTED]]

    @staticmethod
    def _validate_risk_checker(raw_checker: object) -> pd.DataFrame:
        """Validate the second DataFrame returned by the checker connector."""
        if not isinstance(raw_checker, pd.DataFrame):
            raise TypeError("risk_checker_loader inventory result must be a DataFrame")
        required = [RISK_TYPE, RISK_GREEK, MRX_FILE, PRODUCT]
        if list(raw_checker.columns) != required:
            raise ValueError(
                f"risk checker columns must be exactly {required} in that order; "
                f"found {list(raw_checker.columns)}"
            )
        checker = raw_checker.copy()
        checker = _require_nonblank(checker[required].copy(), required, "risk checker")
        if checker.duplicated(required).any():
            raise ValueError("risk checker contains duplicate inventory rows")
        expected_pairs = {
            (spec.risk_type, spec.risk_greek) for spec in PRODUCT_SPECS.values()
        }
        actual_pairs = set(
            checker[[RISK_TYPE, RISK_GREEK]].itertuples(index=False, name=None)
        )
        extra_pairs = sorted(actual_pairs - expected_pairs)
        if extra_pairs:
            raise ValueError(
                "risk checker contains unknown Risk Type/Risk Greek pairs; "
                f"unknown={extra_pairs}"
            )
        invalid_product = ~checker[PRODUCT].isin(CANONICAL_PRODUCTS)
        if invalid_product.any():
            rows = checker.index[invalid_product].tolist()[:5]
            raise ValueError(
                "risk checker Product must be exactly 'XVA' or 'Hedges'; "
                f"invalid rows {rows}"
            )
        return checker.sort_values(required, kind="stable").reset_index(drop=True)

    def _resolve_market_status(
        self,
        market_date: pd.Timestamp,
        *,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> str:
        """Resolve the authoritative market source through the finite call gate."""

        resolver = self._market_status_resolver
        self._progress_activity(
            _callable_name(resolver),
            "market_status",
            message=f"Resolving the market source for {market_date.date()}.",
        )
        result = self._call_connector(
            ("market_status_resolver",),
            lambda: resolver(market_date),
            budget=budget,
        )
        return _require_market_status(result)

    def _load_risk_checker(
        self,
        checker_date: pd.Timestamp,
        *,
        budget: _ConnectorRefreshBudget | None = None,
        fail_soft: bool = False,
    ) -> RiskCheckerResult:
        """Load readiness and MRX File inventory atomically from one dated connector."""
        self._progress_step(
            _callable_name(self._risk_checker_loader),
            "readiness",
            message="Loading risk readiness and checker inventory.",
        )
        try:
            result = self._call_connector(
                ("risk_checker",),
                lambda: self._risk_checker_loader(checker_date),
                budget=budget,
            )
        except Exception as error:
            if not fail_soft or not self._is_operational_connector_error(error):
                raise
            self._log_operational_failure(
                boundary="Risk checker",
                error=error,
                stage="readiness",
            )
            readiness = self._validate_risk_readiness(
                pd.DataFrame(columns=[RISK_TYPE, RISK_GREEK, AGE])
            )
            checker = self._validate_risk_checker(
                pd.DataFrame(columns=[RISK_TYPE, RISK_GREEK, MRX_FILE, PRODUCT])
            )
            return readiness, checker
        if not isinstance(result, tuple) or len(result) != 2:
            raise TypeError(
                "risk_checker_loader must return exactly "
                "(risk_readiness_df, risk_checker_df)"
            )
        readiness, checker = result
        return (
            self._validate_risk_readiness(readiness),
            self._validate_risk_checker(checker),
        )

    def _wait_for_stage(self, stage: str, *, has_snapshot: bool) -> None:
        """Apply an optional configured pause after the initial snapshot."""
        delay = self._stage_delays.get(stage, 0.0)
        if has_snapshot and delay > 0:
            sleep_name = (
                "time.sleep"
                if self._sleep is time.sleep
                else _callable_name(self._sleep)
            )
            self._progress_activity(
                sleep_name,
                f"{stage}_delay",
                message=f"Configured {stage} progress hold.",
            )
            self._sleep(delay)

    def _load_product_risk(
        self,
        spec: ProductSpec,
        risk_date: pd.Timestamp,
        *,
        product_index: int = 0,
        product_total: int = 0,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        # PRODUCTION INTEGRATION POINT: a per-source adapter wins; the generic
        # ``risk_loader(date, source_type)`` handles only uncovered source types.
        adapter = self._connector_adapters.get(spec.source_type)
        connector = adapter.risk if adapter is not None else self._risk_loader
        self._progress_step(
            _callable_name(connector),
            "risk",
            source_type=spec.source_type,
            product_label=_product_progress_label(spec),
            product_index=product_index,
            product_total=product_total,
            message="Loading connector risk.",
        )
        if adapter is not None:
            result = self._call_connector(
                ("risk", spec.source_type),
                lambda: adapter.risk(risk_date),
                budget=budget,
            )
        else:
            result = self._call_connector(
                ("risk", spec.source_type),
                lambda: self._risk_loader(risk_date, spec.source_type),
                budget=budget,
            )
        return result

    def _load_market_frames(
        self,
        spec: ProductSpec,
        underlyings: tuple[str, ...],
        *,
        connector: Callable[..., pd.DataFrame],
        stage: str,
        label: str,
        load_one: Callable[[str], object],
        circuit: _OperationalCircuitBreaker | None = None,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        """Load one product's market scope with bounded, stable execution."""
        if not underlyings or (circuit is not None and circuit.is_open):
            return self._empty_market_leg(spec, stage)
        connector_name = _callable_name(connector)
        failure_message = (
            "Opening market connector unavailable; continuing with missing data."
            if stage == "market_open"
            else "Current market connector unavailable; continuing with missing data."
        )
        failure_lock = Lock()
        failure_count = 0
        first_failure: Exception | None = None

        def record_failure(exc: Exception) -> None:
            nonlocal failure_count, first_failure
            with failure_lock:
                failure_count += 1
                if first_failure is None:
                    first_failure = exc

        def load_with_retry(item: tuple[int, str]) -> pd.DataFrame:
            index, underlying = item
            if circuit is not None and circuit.is_open:
                return self._empty_market_leg(spec, stage)
            for retry in range(self._market_retries + 1):
                retry_message = (
                    "" if retry == 0 else f" Retry {retry} of {self._market_retries}."
                )
                self._progress_activity(
                    connector_name,
                    stage,
                    source_type=spec.source_type,
                    underlying=underlying,
                    product_label=_product_progress_label(spec),
                    product_index=index,
                    product_total=len(underlyings),
                    message=f"Loading {label} for {underlying}.{retry_message}",
                )
                try:
                    frame = self._call_connector(
                        ("market", stage, spec.source_type, underlying),
                        lambda: load_one(underlying),
                        budget=budget,
                    )
                except (TypeError, ValueError):
                    self._progress_activity(
                        connector_name,
                        stage,
                        source_type=spec.source_type,
                        underlying=underlying,
                        product_label=_product_progress_label(spec),
                        product_index=index,
                        product_total=len(underlyings),
                        message=failure_message,
                    )
                    raise
                except Exception as exc:
                    if not self._is_operational_connector_error(exc):
                        raise
                    if circuit is not None:
                        if circuit.trip(exc):
                            self._log_operational_failure(
                                boundary=(
                                    "Opening market"
                                    if stage == "market_open"
                                    else "Current market"
                                ),
                                error=exc,
                                source_type=spec.source_type,
                                product_label=_product_progress_label(spec),
                                stage=stage,
                            )
                            LOGGER.warning(
                                "Market circuit opened after %s %s failed; all "
                                "remaining market calls in this refresh are skipped. %s",
                                spec.source_type,
                                stage,
                                self._bounded_market_error(exc),
                            )
                        self._progress_activity(
                            connector_name,
                            stage,
                            source_type=spec.source_type,
                            underlying=underlying,
                            product_label=_product_progress_label(spec),
                            product_index=index,
                            product_total=len(underlyings),
                            message=failure_message,
                        )
                        return self._empty_market_leg(spec, stage)
                    if retry == self._market_retries:
                        record_failure(exc)
                        self._progress_activity(
                            connector_name,
                            stage,
                            source_type=spec.source_type,
                            underlying=underlying,
                            product_label=_product_progress_label(spec),
                            product_index=index,
                            product_total=len(underlyings),
                            message=failure_message,
                        )
                        return self._empty_market_leg(spec, stage)
                    self._sleep(self._market_retry_delay_seconds)
                    continue
                if not isinstance(frame, pd.DataFrame):
                    kind = "market Open" if stage == "market_open" else "current market"
                    raise TypeError(f"{kind} connector must return a pandas DataFrame")
                return frame
            raise AssertionError("unreachable market retry state")

        items = tuple(enumerate(underlyings, start=1))
        if self._market_max_workers == 1 or circuit is not None:
            frames = [load_with_retry(item) for item in items]
        else:
            worker_count = min(self._market_max_workers, len(items))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                frames = list(executor.map(load_with_retry, items))
        if failure_count:
            LOGGER.warning(
                "Market connector unavailable for %d of %d %s %s calls; "
                "missing legs retained. First error: %s",
                failure_count,
                len(underlyings),
                spec.source_type,
                stage,
                self._bounded_market_error(first_failure),
            )
        return pd.concat(frames, ignore_index=True, sort=False)

    @staticmethod
    def _empty_market_leg(spec: ProductSpec, stage: str) -> pd.DataFrame:
        """Return the raw shape required by the market-leg validators."""

        if stage == "market_open":
            value_column = OPEN
        elif stage == "market_status":
            value_column = CURRENT
        else:
            raise ValueError(f"unknown market stage {stage!r}")
        return pd.DataFrame(
            columns=[
                UNDERLYING,
                *spec.tenor_columns,
                *spec.tenor_order_columns,
                value_column,
            ]
        )

    @staticmethod
    def _bounded_market_error(exc: Exception | None) -> str:
        """Return useful connector context without allowing unbounded log lines."""

        if exc is None:  # pragma: no cover - protected by the failure counter
            return "unknown operational error"
        detail = " ".join(str(exc).split()) or "no detail"
        if len(detail) > 240:
            detail = f"{detail[:237]}..."
        return f"{type(exc).__name__}: {detail}"

    def _load_bulk_market_frame(
        self,
        spec: ProductSpec,
        underlyings: tuple[str, ...],
        *,
        connector: Callable[..., pd.DataFrame],
        stage: str,
        label: str,
        load_bulk: Callable[[], object],
        circuit: _OperationalCircuitBreaker | None = None,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        """Call one optional FX-Delta bulk connector for a complete market leg."""

        if not underlyings or (circuit is not None and circuit.is_open):
            return self._empty_market_leg(spec, stage)
        connector_name = _callable_name(connector)
        for retry in range(self._market_retries + 1):
            retry_message = (
                "" if retry == 0 else f" Retry {retry} of {self._market_retries}."
            )
            self._progress_activity(
                connector_name,
                stage,
                source_type=spec.source_type,
                product_label=_product_progress_label(spec),
                product_index=1,
                product_total=1,
                message=f"Loading bulk {label}.{retry_message}",
            )
            try:
                frame = self._call_connector(
                    ("market", stage, spec.source_type, "__bulk__"),
                    load_bulk,
                    budget=budget,
                )
            except (TypeError, ValueError):
                self._progress_activity(
                    connector_name,
                    stage,
                    source_type=spec.source_type,
                    product_label=_product_progress_label(spec),
                    product_index=1,
                    product_total=1,
                    message="Bulk market connector contract failed.",
                )
                raise
            except Exception as exc:
                if not self._is_operational_connector_error(exc):
                    raise
                if circuit is not None:
                    if circuit.trip(exc):
                        self._log_operational_failure(
                            boundary=(
                                "Opening market"
                                if stage == "market_open"
                                else "Current market"
                            ),
                            error=exc,
                            source_type=spec.source_type,
                            product_label=_product_progress_label(spec),
                            stage=stage,
                        )
                        LOGGER.warning(
                            "Market circuit opened after bulk %s %s failed; all "
                            "remaining market calls in this refresh are skipped. %s",
                            spec.source_type,
                            stage,
                            self._bounded_market_error(exc),
                        )
                    self._progress_activity(
                        connector_name,
                        stage,
                        source_type=spec.source_type,
                        product_label=_product_progress_label(spec),
                        product_index=1,
                        product_total=1,
                        message=(
                            "Bulk market connector unavailable; continuing with "
                            "missing data."
                        ),
                    )
                    return self._empty_market_leg(spec, stage)
                if retry < self._market_retries:
                    self._sleep(self._market_retry_delay_seconds)
                    continue
                self._progress_activity(
                    connector_name,
                    stage,
                    source_type=spec.source_type,
                    product_label=_product_progress_label(spec),
                    product_index=1,
                    product_total=1,
                    message=(
                        "Bulk market connector unavailable; continuing with "
                        "missing data."
                    ),
                )
                LOGGER.warning(
                    "Bulk market connector unavailable for %s %s; missing leg "
                    "retained. First error: %s",
                    spec.source_type,
                    stage,
                    self._bounded_market_error(exc),
                )
                return self._empty_market_leg(spec, stage)
            if not isinstance(frame, pd.DataFrame):
                kind = "market Open" if stage == "market_open" else "current market"
                raise TypeError(f"bulk {kind} connector must return a pandas DataFrame")
            if UNDERLYING in frame:
                returned = frame[UNDERLYING].dropna().astype("string").str.strip()
                extras = sorted(
                    set(returned.loc[returned.ne("")].astype(str)) - set(underlyings)
                )
                if extras:
                    raise ValueError(
                        f"bulk {spec.key} {stage} returned Underlying values outside "
                        f"the requested scope: {extras[:5]}"
                    )
            return frame
        raise AssertionError("unreachable bulk market retry state")

    def _load_product_market_open(
        self,
        spec: ProductSpec,
        open_date: pd.Timestamp,
        underlyings: tuple[str, ...],
        *,
        market_status: str,
        circuit: _OperationalCircuitBreaker | None = None,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        # PRODUCTION INTEGRATION POINT: every Open adapter receives the one
        # authoritative T-1 business date. It is independent of any older
        # per-product Risk date produced by readiness Age or a force override.
        adapter = self._connector_adapters.get(spec.source_type)
        bulk_connector = adapter.market_open_bulk if adapter is not None else None
        selected_status = _require_market_status(market_status)
        if bulk_connector is not None:
            return self._load_bulk_market_frame(
                spec,
                underlyings,
                connector=bulk_connector,
                stage="market_open",
                label="Open",
                load_bulk=lambda: bulk_connector(
                    open_date,
                    underlyings,
                    market_status=selected_status,
                ),
                circuit=circuit,
                budget=budget,
            )
        connector = (
            adapter.market_open if adapter is not None else self._market_open_loader
        )

        def load_one(underlying: str) -> object:
            if adapter is not None:
                return adapter.market_open(
                    open_date, underlying, market_status=selected_status
                )
            return self._market_open_loader(
                spec.source_type,
                open_date,
                underlying,
                market_status=selected_status,
            )

        return self._load_market_frames(
            spec,
            underlyings,
            connector=connector,
            stage="market_open",
            label="Open",
            load_one=load_one,
            circuit=circuit,
            budget=budget,
        )

    def _load_product_market_status(
        self,
        spec: ProductSpec,
        market_date: pd.Timestamp,
        underlyings: tuple[str, ...],
        *,
        market_status: str,
        circuit: _OperationalCircuitBreaker | None = None,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        # PRODUCTION INTEGRATION POINT: the injected callable selects Live for
        # today and OFFICIAL for prior views, then returns the normalized leg.
        adapter = self._connector_adapters.get(spec.source_type)
        bulk_connector = adapter.market_status_bulk if adapter is not None else None
        selected_status = _require_market_status(market_status)
        if bulk_connector is not None:
            return self._load_bulk_market_frame(
                spec,
                underlyings,
                connector=bulk_connector,
                stage="market_status",
                label=selected_status,
                load_bulk=lambda: bulk_connector(
                    market_date,
                    underlyings,
                    market_status=selected_status,
                ),
                circuit=circuit,
                budget=budget,
            )
        connector = (
            adapter.market_status if adapter is not None else self._market_status_loader
        )

        def load_one(underlying: str) -> object:
            if adapter is not None:
                return adapter.market_status(
                    market_date, underlying, market_status=selected_status
                )
            return self._market_status_loader(
                spec.source_type,
                market_date,
                underlying,
                market_status=selected_status,
            )

        return self._load_market_frames(
            spec,
            underlyings,
            connector=connector,
            stage="market_status",
            label=selected_status,
            load_one=load_one,
            circuit=circuit,
            budget=budget,
        )

    @staticmethod
    def _disabled_market_sources(
        spec: ProductSpec,
        risk_frame: pd.DataFrame,
        *,
        market_status: str,
    ) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return zero quote legs without calling disabled Commodity connectors."""
        keys = risk_frame[spec.market_keys].drop_duplicates().reset_index(drop=True)
        for axis in spec.axes:
            tenor_column = axis.column
            order_column = axis.order_column
            keys[order_column] = keys.groupby(UNDERLYING, sort=False)[
                tenor_column
            ].transform(
                lambda values: pd.Series(
                    pd.factorize(values, sort=False)[0],
                    index=values.index,
                    dtype="Int64",
                )
            )
        market_open = keys.copy()
        market_open[OPEN] = 0.0
        market_status_frame = keys.copy()
        market_status_frame[CURRENT] = 0.0
        market_status_frame[MARKET_STATUS] = _require_market_status(market_status)
        return market_open, market_status_frame

    @staticmethod
    def _risk_underlyings(risk_frame: pd.DataFrame) -> tuple[str, ...]:
        """Return stable connector scope from an already validated Risk frame."""
        return tuple(risk_frame[UNDERLYING].drop_duplicates().tolist())

    @staticmethod
    def _requested_market_underlyings(
        risk_frame: pd.DataFrame,
        supplemental: Sequence[str] = (),
    ) -> tuple[str, ...]:
        """Union base Risk and supplemental scopes without changing order."""

        requested = list(RiskRefreshManager._risk_underlyings(risk_frame))
        for raw_underlying in supplemental:
            if not isinstance(raw_underlying, str) or not raw_underlying.strip():
                raise ValueError(
                    "supplemental market scope Underlying values must be nonblank text"
                )
            underlying = raw_underlying.strip()
            if underlying not in requested:
                requested.append(underlying)
        return tuple(requested)

    @staticmethod
    def _reject_unrequested_market_underlyings(
        frame: pd.DataFrame,
        requested: tuple[str, ...],
        *,
        label: str,
    ) -> None:
        extras = sorted(set(frame[UNDERLYING]) - set(requested))
        if extras:
            raise ValueError(
                f"{label} returned Underlying values outside validated Risk scope: "
                f"{extras[:5]}"
            )

    def reset_refresh(
        self, *, expected_reset_generation: int
    ) -> tuple[int, RefreshSnapshot]:
        """Advance the reset generation, then force one guarded full refresh."""
        self._validate_reset_generation(
            expected_reset_generation, name="expected_reset_generation"
        )
        with self._state_lock:
            actual_generation = self._reset_generation
            if expected_reset_generation != actual_generation:
                raise StaleResetGenerationError(
                    expected_reset_generation, actual_generation
                )
            base_snapshot = self._snapshot
            if base_snapshot is None:
                raise RuntimeError("cache cannot be reset before the initial snapshot")
            new_generation = actual_generation + 1
            self._reset_generation = new_generation
            commodity_market_enabled = bool(base_snapshot.commodity_market_enabled)
            risk_checker_enabled = bool(base_snapshot.risk_checker_enabled)

        # Incrementing before this wait invalidates any older writer. RLock
        # lets the reset own the gate while reusing the normal transaction.
        with self._refresh_lock:
            with self._state_lock:
                expected_revision = self._snapshot.revision
            snapshot = self.refresh(
                force_pl=True,
                force_risk=True,
                commodity_market_enabled=commodity_market_enabled,
                risk_checker_enabled=risk_checker_enabled,
                forced_dates={},
                view_date=None,
                reason="clear cache",
                expected_revision=expected_revision,
                expected_reset_generation=new_generation,
            )
        if snapshot is None:  # pragma: no cover - copy output remains enabled
            raise RuntimeError("cache reset did not return a snapshot")
        return new_generation, snapshot

    def refresh_portfolios(
        self,
        *,
        reason: str = "portfolio mapping",
        expected_revision: int | None = None,
        expected_reset_generation: int | None = None,
    ) -> RefreshSnapshot:
        """Reload only portfolio mapping and rebuild its dependent cached views.

        Risk, market, checker, and threshold connectors are deliberately not
        invoked. Portfolio and Reported Underlying mappings plus every derived
        table/search view are validated before one atomic commit; failures
        retain the last snapshot.
        """
        if not self._refresh_lock.acquire(blocking=False):
            raise RefreshInProgressError("a risk refresh is already in progress")
        try:
            attempted_at = self._now()
            with self._state_lock:
                attempt_reset_generation = self._capture_reset_generation(
                    expected_reset_generation
                )
                base_snapshot = self._snapshot
                if base_snapshot is None:
                    raise RuntimeError(
                        "portfolio mapping cannot refresh before the initial snapshot"
                    )
                if expected_revision is not None:
                    if isinstance(expected_revision, bool) or not isinstance(
                        expected_revision, int
                    ):
                        raise TypeError(
                            "expected_revision must be a non-negative integer"
                        )
                    if expected_revision < 0:
                        raise ValueError(
                            "expected_revision must be a non-negative integer"
                        )
                    if expected_revision != base_snapshot.revision:
                        raise StaleRefreshError(
                            expected_revision, base_snapshot.revision
                        )
                base_thresholds = self._thresholds
                risk_frames = dict(self._risk_frames)
                market_open_frames = dict(self._market_open_frames)
                market_status_frames = dict(self._market_status_frames)
                market_frames = dict(self._market_frames)
                pl_frames = dict(self._pl_frames)
                overlay_frames = dict(self._overlay_frames)
                risk_dates = dict(self._risk_dates)
                market_date = self._market_date
            if base_thresholds is None or market_date is None:
                raise RuntimeError("the committed snapshot cache is incomplete")

            connector_budget = _ConnectorRefreshBudget(
                self._connector_refresh_budget_seconds
            )
            self._start_progress(
                attempted_at,
                function_name="RiskRefreshManager.refresh_portfolios",
                stage="portfolio_config",
                message="Starting portfolio mapping refresh.",
            )
            try:
                self._set_progress_total(4)
                config_function = (
                    _callable_name(self._config_source)
                    if callable(self._config_source)
                    else "load_config"
                )
                portfolio_date = base_snapshot.checker_date
                self._progress_step(
                    config_function,
                    "portfolio_config",
                    message=(f"Loading portfolio mapping for {portfolio_date.date()}."),
                )
                next_config = self._load_portfolio_config_source(
                    portfolio_date,
                    budget=connector_budget,
                )

                mapping_function = (
                    _callable_name(self._reported_underlying_source)
                    if callable(self._reported_underlying_source)
                    else "load_reported_underlyings"
                )
                self._progress_step(
                    mapping_function,
                    "portfolio_config",
                    message="Loading Reported Underlying mapping.",
                )
                next_reported_underlyings = (
                    self._load_reported_underlyings_with_deadline(
                        budget=connector_budget
                    )
                )

                self._progress_step(
                    "_release_pl_views",
                    "final",
                    message="Rebuilding mapping-dependent dashboard views.",
                )
                enriched, dashboard, unmapped = self._release_pl_views(
                    pl_frames,
                    next_config,
                    base_thresholds,
                    next_reported_underlyings,
                    overlay_frames,
                )
                revision = base_snapshot.revision + 1
                search_catalog = self._build_snapshot_search_catalog(
                    revision=revision,
                    risk_frames=risk_frames,
                    market_frames=market_frames,
                    dashboard=dashboard,
                    risk_dates=risk_dates,
                    market_date=market_date,
                    market_status=base_snapshot.market_status,
                )
                completed_at = self._now()
                snapshot = replace(
                    base_snapshot,
                    revision=revision,
                    refreshed_at=completed_at,
                    last_attempt_at=attempted_at,
                    refresh_reason=reason,
                    changed_source_types=(),
                    open_refreshed_source_types=(),
                    market_refreshed_source_types=(),
                    combined_pl=enriched,
                    dashboard_frame=dashboard,
                    unmapped_frame=unmapped,
                    errors=(),
                )
                self._progress_step(
                    "_commit_full_snapshot",
                    "commit",
                    message="Publishing the new portfolio mapping atomically.",
                )
                self._commit_full_snapshot(
                    snapshot,
                    config=next_config,
                    thresholds=base_thresholds,
                    reported_underlyings=next_reported_underlyings,
                    risk_frames=risk_frames,
                    market_open_frames=market_open_frames,
                    market_status_frames=market_status_frames,
                    market_frames=market_frames,
                    pl_frames=pl_frames,
                    overlay_frames=overlay_frames,
                    risk_dates=risk_dates,
                    market_date=market_date,
                    search_catalog=search_catalog,
                    reset_generation=attempt_reset_generation,
                )
                self._finish_progress()
                return self._copy_snapshot(snapshot)
            except StaleResetGenerationError:
                raise
            except Exception as error:
                self._require_reset_generation(attempt_reset_generation)
                incident_id = uuid.uuid4().hex[:10]
                error_type = (
                    re.sub(r"[^A-Za-z0-9_.-]", "_", type(error).__name__) or "Exception"
                )
                failed_progress = self.progress
                failure_reason = _bounded_failure_reason(error)
                LOGGER.exception(
                    "Portfolio mapping refresh failed; incident=%s type=%s "
                    "reason=%s context=[%s] location=%s",
                    incident_id,
                    error_type,
                    failure_reason,
                    _failure_progress_context(failed_progress),
                    _safe_failure_location(error),
                )
                safe_error = _failure_ui_message(
                    error,
                    incident_id=incident_id,
                    progress=failed_progress,
                )
                message = (
                    f"{attempted_at.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
                    f"{safe_error} Last successful data retained."
                )
                retained = replace(
                    base_snapshot,
                    last_attempt_at=attempted_at,
                    refresh_reason=reason,
                    changed_source_types=(),
                    open_refreshed_source_types=(),
                    market_refreshed_source_types=(),
                    errors=(message,),
                )
                self._set_progress_total(self.progress.current + 1)
                self._progress_step(
                    "_commit_snapshot",
                    "commit",
                    message="Retaining the last successful snapshot.",
                )
                self._commit_snapshot(
                    retained, reset_generation=attempt_reset_generation
                )
                self._finish_progress(
                    error=safe_error,
                    failed_function_name=failed_progress.function_name,
                    failed_source_type=failed_progress.source_type,
                    failed_underlying=failed_progress.underlying,
                    failed_product_label=failed_progress.product_label,
                    failed_product_index=failed_progress.product_index,
                    failed_product_total=failed_progress.product_total,
                    failed_hold_seconds=failed_progress.hold_seconds,
                )
                return self._copy_snapshot(retained)
        finally:
            self._refresh_lock.release()

    def refresh(
        self,
        *,
        force_pl: bool = False,
        force_risk: bool = False,
        commodity_market_enabled: bool = False,
        risk_checker_enabled: bool | None = None,
        forced_dates: Mapping[str, date | datetime | str | pd.Timestamp] | None = None,
        view_date: date | datetime | str | pd.Timestamp | None = None,
        reason: str = "status",
        expected_revision: int | None = None,
        expected_reset_generation: int | None = None,
        copy_result: bool = True,
    ) -> RefreshSnapshot | None:
        """Refresh atomically; return a defensive copy unless copy output is disabled."""
        if not isinstance(copy_result, bool):
            raise TypeError("copy_result must be boolean")
        if not self._refresh_lock.acquire(blocking=False):
            raise RefreshInProgressError("a risk refresh is already in progress")
        try:
            attempted_at = self._now()
            with self._state_lock:
                attempt_reset_generation = self._capture_reset_generation(
                    expected_reset_generation
                )
                base_snapshot = self._snapshot
                actual_revision = 0 if base_snapshot is None else base_snapshot.revision
                if (
                    reason == _AUTOMATIC_REFRESH_REASON
                    and force_pl
                    and not force_risk
                    and base_snapshot is not None
                    and self._automatic_refresh_min_age_seconds > 0
                    and max(
                        0.0,
                        (attempted_at - base_snapshot.refreshed_at).total_seconds(),
                    )
                    < self._automatic_refresh_min_age_seconds
                ):
                    LOGGER.info(
                        "Coalesced automatic refresh onto committed revision %d.",
                        base_snapshot.revision,
                    )
                    return self._copy_snapshot(base_snapshot) if copy_result else None
                if expected_revision is not None:
                    if isinstance(expected_revision, bool) or not isinstance(
                        expected_revision, int
                    ):
                        raise TypeError(
                            "expected_revision must be a non-negative integer"
                        )
                    if expected_revision < 0:
                        raise ValueError(
                            "expected_revision must be a non-negative integer"
                        )
                    if expected_revision != actual_revision:
                        raise StaleRefreshError(expected_revision, actual_revision)
                base_config = self._config
                base_thresholds = self._thresholds
                base_risk_frames = dict(self._risk_frames)
                base_market_open_frames = dict(self._market_open_frames)
                base_market_status_frames = dict(self._market_status_frames)
                base_market_frames = dict(self._market_frames)
                base_pl_frames = dict(self._pl_frames)
                base_overlay_frames = dict(self._overlay_frames)
                base_risk_dates = dict(self._risk_dates)
                base_market_date = self._market_date
            connector_budget = _ConnectorRefreshBudget(
                self._connector_refresh_budget_seconds
            )
            risk_circuit = _OperationalCircuitBreaker()
            market_circuit = _OperationalCircuitBreaker()
            self._reset_operational_warnings()
            self._start_progress(attempted_at)
            refresh_started = time.monotonic()
            stage_durations: dict[str, float] = {}
            try:
                if not isinstance(commodity_market_enabled, bool):
                    raise TypeError("commodity_market_enabled must be boolean")
                checker_enabled = (
                    True if risk_checker_enabled is None else risk_checker_enabled
                )
                if not isinstance(checker_enabled, bool):
                    raise TypeError("risk_checker_enabled must be boolean")
                system_date = self._system_date(attempted_at)
                natural_market_date = market_date_for(system_date)
                forced_view_date = (
                    None if view_date in (None, "") else _as_timestamp(view_date)
                )
                if forced_view_date is not None:
                    if forced_view_date > system_date:
                        raise ValueError("view date must not be in the future")
                    if forced_view_date.weekday() >= 5:
                        raise ValueError("view date must be a business day")
                market_date = forced_view_date or natural_market_date
                if (natural_market_date - market_date).days > self._max_history_days:
                    raise ValueError(
                        f"view date exceeds the {self._max_history_days}-day retention window"
                    )

                try:
                    expected_market_status = self._resolve_market_status(
                        market_date,
                        budget=connector_budget,
                    )
                except Exception as error:
                    if (
                        base_snapshot is not None
                        or not self._is_operational_connector_error(error)
                    ):
                        raise
                    market_circuit.trip(error)
                    if isinstance(error, ConnectorRefreshBudgetError):
                        risk_circuit.trip(error)
                    expected_market_status = OFFICIAL
                    self._log_operational_failure(
                        boundary="Market status resolver",
                        error=error,
                        stage="market_status",
                    )
                    self._progress_activity(
                        _callable_name(self._market_status_resolver),
                        "market_status",
                        message=(
                            "Market source unavailable; using OFFICIAL identity and "
                            "skipping market connector calls."
                        ),
                    )

                checker_date = checker_date_for(market_date)
                if checker_enabled:
                    status, next_risk_checker = self._load_risk_checker(
                        checker_date,
                        budget=connector_budget,
                        fail_soft=base_snapshot is None,
                    )
                else:
                    status = self._validate_risk_readiness(
                        pd.DataFrame(columns=[RISK_TYPE, RISK_GREEK, AGE])
                    )
                    next_risk_checker = pd.DataFrame(
                        columns=[RISK_TYPE, RISK_GREEK, MRX_FILE, PRODUCT]
                    )
                age_by_source = status.set_index(SOURCE_TYPE)[AGE].to_dict()
                view_dates = {
                    source_type: risk_date_for(checker_date, age)
                    for source_type, age in age_by_source.items()
                }
                requested_overrides = dict(forced_dates or {})
                unknown_overrides = sorted(
                    set(requested_overrides) - set(PRODUCT_SPECS_BY_SOURCE_TYPE)
                )
                if unknown_overrides:
                    raise ValueError(
                        f"unknown forced-date source types: {unknown_overrides}"
                    )
                overrides: dict[str, pd.Timestamp] = {}
                for source_type, value in requested_overrides.items():
                    if value in (None, ""):
                        continue
                    forced_date = _as_timestamp(value)
                    if forced_date > system_date:
                        raise ValueError(
                            f"forced date for {source_type} must not be in the future"
                        )
                    if forced_date.weekday() >= 5:
                        raise ValueError(
                            f"forced date for {source_type} must be a business day"
                        )
                    if forced_date > checker_date:
                        raise ValueError(
                            f"forced date for {source_type} must not be after "
                            f"checker date {checker_date.date()} for market date "
                            f"{market_date.date()}"
                        )
                    if (
                        natural_market_date - forced_date
                    ).days > self._max_history_days:
                        raise ValueError(
                            f"forced date for {source_type} exceeds the {self._max_history_days}-day retention window"
                        )
                    overrides[source_type] = forced_date
                # Per-source Force Risk is the final override after readiness and
                # the selected Today view have established the derived dates.
                next_dates = {
                    source_type: overrides.get(source_type, risk_date)
                    for source_type, risk_date in view_dates.items()
                }
                status[CHECKER_DATE] = checker_date
                status[SUGGESTED_RISK_DATE] = status[SOURCE_TYPE].map(view_dates)
                status[EFFECTIVE_RISK_DATE] = status[SOURCE_TYPE].map(next_dates)
                status[FORCE_RISK] = status[SOURCE_TYPE].isin(overrides)
                status[MARKET_DATE] = market_date
                status[MARKET_STATUS] = expected_market_status

                changed_source_types = {
                    source_type
                    for source_type, risk_date in next_dates.items()
                    if base_risk_dates.get(source_type) != risk_date
                }
                if base_snapshot is None or force_risk:
                    changed_source_types = set(PRODUCT_SPECS_BY_SOURCE_TYPE)

                checker_state_changed = (
                    base_snapshot is not None
                    and base_snapshot.risk_checker_enabled != checker_enabled
                )
                checker_data_changed = (
                    checker_enabled
                    and base_snapshot is not None
                    and not next_risk_checker.equals(base_snapshot.risk_checker)
                )
                commodity_state_changed = (
                    base_snapshot is not None
                    and base_snapshot.commodity_market_enabled
                    != commodity_market_enabled
                )
                market_date_changed = base_market_date != market_date
                market_status_changed = (
                    base_snapshot is not None
                    and base_snapshot.market_status != expected_market_status
                )
                market_context_changed = market_date_changed or market_status_changed

                override_changed = (
                    base_snapshot is not None
                    and base_snapshot.forced_dates != overrides
                )
                forced_view_changed = (
                    base_snapshot is not None
                    and base_snapshot.forced_view_date != forced_view_date
                )
                if (
                    not changed_source_types
                    and not market_context_changed
                    and not force_pl
                    and not force_risk
                    and not override_changed
                    and not forced_view_changed
                    and not checker_state_changed
                    and not checker_data_changed
                    and not commodity_state_changed
                ):
                    self._set_progress_total(2)
                    snapshot = replace(
                        base_snapshot,
                        last_attempt_at=attempted_at,
                        refresh_reason=reason,
                        system_date=system_date,
                        market_date=market_date,
                        checker_date=checker_date,
                        forced_view_date=forced_view_date,
                        risk_status=status,
                        risk_checker=next_risk_checker,
                        risk_checker_enabled=checker_enabled,
                        changed_source_types=(),
                        open_refreshed_source_types=(),
                        market_refreshed_source_types=(),
                        errors=(),
                    )
                    self._progress_step(
                        "_commit_snapshot",
                        "commit",
                        message="Committing refresh metadata.",
                    )
                    self._commit_snapshot(
                        snapshot, reset_generation=attempt_reset_generation
                    )
                    result = self._copy_snapshot(snapshot) if copy_result else None
                    self._finish_progress()
                    return result

                all_types = set(PRODUCT_SPECS_BY_SOURCE_TYPE)
                open_source_types = set(changed_source_types)
                # Open is dated T-1 and independent of Live/OFFICIAL routing.
                # A status-only switch can therefore reuse the committed Open
                # legs and refresh only Current, avoiding half of the network
                # fan-out while preserving the same atomic snapshot commit.
                if market_date_changed:
                    open_source_types = set(all_types)
                market_status_source_types = (
                    set(all_types) if force_pl else set(changed_source_types)
                )
                if market_context_changed:
                    market_status_source_types = set(all_types)
                if base_snapshot is None or force_risk:
                    open_source_types = set(all_types)
                    market_status_source_types = set(all_types)
                if commodity_state_changed:
                    commodity_types = {
                        source_type
                        for source_type, spec in PRODUCT_SPECS_BY_SOURCE_TYPE.items()
                        if spec.risk_type == "Commo"
                    }
                    open_source_types.update(commodity_types)
                    market_status_source_types.update(commodity_types)

                if (
                    not changed_source_types
                    and not open_source_types
                    and not market_status_source_types
                    and (
                        override_changed or forced_view_changed or checker_state_changed
                    )
                    and not checker_data_changed
                ):
                    self._set_progress_total(2)
                    snapshot = replace(
                        base_snapshot,
                        last_attempt_at=attempted_at,
                        refresh_reason=reason,
                        system_date=system_date,
                        market_date=market_date,
                        checker_date=checker_date,
                        forced_view_date=forced_view_date,
                        risk_status=status,
                        risk_checker=next_risk_checker,
                        risk_checker_enabled=checker_enabled,
                        commodity_market_enabled=commodity_market_enabled,
                        forced_dates=overrides,
                        changed_source_types=(),
                        open_refreshed_source_types=(),
                        market_refreshed_source_types=(),
                        errors=(),
                    )
                    self._progress_step(
                        "_commit_snapshot",
                        "commit",
                        message="Committing forced-date metadata.",
                    )
                    self._commit_snapshot(
                        snapshot, reset_generation=attempt_reset_generation
                    )
                    result = self._copy_snapshot(snapshot) if copy_result else None
                    self._finish_progress()
                    return result

                # Governance frames are required to publish any snapshot. Load
                # their callable boundaries before the high-fan-out risk and
                # market stages so an exhausted connector budget can still
                # release a safely shaped partial cold-start result.
                if force_risk or market_date_changed or base_config is None:
                    next_config = self._load_portfolio_config_source(
                        checker_date,
                        budget=connector_budget,
                    )
                else:
                    next_config = base_config
                if force_risk or base_thresholds is None:
                    next_thresholds = self._load_threshold_source(
                        budget=connector_budget
                    )
                else:
                    next_thresholds = base_thresholds
                mapping_function = (
                    _callable_name(self._reported_underlying_source)
                    if callable(self._reported_underlying_source)
                    else "load_reported_underlyings"
                )
                self._progress_step(
                    mapping_function,
                    "reporting_mapping",
                    message="Loading Reported Underlying mapping.",
                )
                next_reported_underlyings = (
                    self._load_reported_underlyings_with_deadline(
                        budget=connector_budget
                    )
                )

                recalculate_source_types = (
                    changed_source_types
                    | open_source_types
                    | market_status_source_types
                )
                planned_total = (
                    3
                    + 2 * len(changed_source_types)
                    + int(bool(open_source_types))
                    + int(bool(market_status_source_types))
                    + int(bool(recalculate_source_types))
                    + int(self._cross_gamma_matrix_loader is not None)
                    + int(self._new_trades_loader is not None)
                )
                self._set_progress_total(planned_total)

                next_risk = {} if force_risk else base_risk_frames
                next_open = {} if force_risk else base_market_open_frames
                next_status = {} if force_risk else base_market_status_frames
                next_market = {} if force_risk else base_market_frames

                stage_durations["readiness"] = time.monotonic() - refresh_started
                risk_started = time.monotonic()
                if changed_source_types:
                    self._wait_for_stage("risk", has_snapshot=base_snapshot is not None)
                risk_specs = [
                    spec
                    for spec in PRODUCT_SPECS.values()
                    if spec.source_type in changed_source_types
                ]
                # Hold every post-startup Risk/dRisk product call long enough
                # for its function name to be read.  That includes selective
                # readiness 1 -> 0 reloads and view-date changes, not only the
                # explicit Reload All Risk path.  A P&L refresh whose risk
                # dates did not change has no risk calls and therefore no hold.
                risk_product_delay = (
                    self._stage_delays["risk_product"]
                    if base_snapshot is not None
                    else 0.0
                )
                risk_connector_calls = 0
                for product_index, spec in enumerate(risk_specs, start=1):
                    source_type = spec.source_type
                    risk_date = next_dates[source_type]
                    product_label = _product_progress_label(spec)
                    if connector_budget.is_exhausted and not risk_circuit.is_open:
                        budget_error = ConnectorRefreshBudgetError(
                            "The refresh connector elapsed-time budget is exhausted."
                        )
                        risk_circuit.trip(budget_error)
                        market_circuit.trip(budget_error)
                        self._log_operational_failure(
                            boundary="Connector budget",
                            error=budget_error,
                            stage="risk",
                        )
                        LOGGER.warning(
                            "Connector elapsed-time budget exhausted; all remaining "
                            "risk and market network calls are skipped."
                        )
                    if risk_circuit.is_open:
                        next_risk[source_type] = self._empty_product_risk(spec)
                        self._progress_step(
                            f"get_{spec.key}_risk",
                            "risk",
                            source_type=source_type,
                            product_label=product_label,
                            product_index=product_index,
                            product_total=len(risk_specs),
                            message=(
                                f"Skipping unavailable Risk/dRisk for {product_label}."
                            ),
                        )
                        continue
                    try:
                        risk_connector_calls += 1
                        raw_risk = self._load_product_risk(
                            spec,
                            risk_date,
                            product_index=product_index,
                            product_total=len(risk_specs),
                            budget=connector_budget,
                        )
                    except Exception as error:
                        if not self._is_operational_connector_error(error):
                            raise
                        if isinstance(error, ConnectorRefreshBudgetError):
                            risk_circuit.trip(error)
                            market_circuit.trip(error)
                        self._log_operational_failure(
                            boundary="Risk/dRisk",
                            source_type=source_type,
                            product_label=product_label,
                            stage="risk",
                            error=error,
                        )
                        next_risk[source_type] = self._empty_product_risk(spec)
                        self._progress_step(
                            f"get_{spec.key}_risk",
                            "risk",
                            source_type=source_type,
                            product_label=product_label,
                            product_index=product_index,
                            product_total=len(risk_specs),
                            message=(
                                f"Risk/dRisk unavailable for {product_label}; "
                                "retaining an empty product."
                            ),
                        )
                        continue
                    self._progress_step(
                        f"get_{spec.key}_risk",
                        "risk",
                        source_type=source_type,
                        product_label=product_label,
                        product_index=product_index,
                        product_total=len(risk_specs),
                        hold_seconds=risk_product_delay,
                        message=f"Loading and validating Risk/dRisk for {product_label}.",
                    )
                    next_risk[source_type] = get_product_risk(spec, risk_date, raw_risk)
                    if risk_product_delay > 0:
                        self._sleep(risk_product_delay)

                # Raw supplemental sources are loaded exactly once before
                # MarketBook calls. Their input/target identities expand the
                # connector scope without becoming ordinary aged Risk rows.
                raw_cross_gamma: pd.DataFrame | None = None
                raw_new_trades: pd.DataFrame | None = None
                supplemental_market_scope: dict[str, list[str]] = {}

                def add_supplemental_scope(
                    scope: Mapping[str, Sequence[str]],
                ) -> None:
                    for source_type, underlyings in scope.items():
                        if source_type not in PRODUCT_SPECS_BY_SOURCE_TYPE:
                            raise ValueError(
                                "supplemental market scope has unknown Source Type "
                                f"{source_type!r}"
                            )
                        values = supplemental_market_scope.setdefault(source_type, [])
                        for underlying in underlyings:
                            if underlying not in values:
                                values.append(underlying)

                if self._cross_gamma_matrix_loader is not None:
                    loader = self._cross_gamma_matrix_loader
                    self._progress_step(
                        _callable_name(loader),
                        "risk",
                        message="Loading portfolio XGAMMA sensitivities.",
                    )
                    try:
                        raw_cross_gamma = self._call_connector(
                            ("supplemental", "cross_gamma"),
                            lambda: loader(market_date),
                            budget=connector_budget,
                        )
                    except Exception as error:
                        if not self._is_operational_connector_error(error):
                            raise
                        if isinstance(error, ConnectorRefreshBudgetError):
                            risk_circuit.trip(error)
                            market_circuit.trip(error)
                        self._log_operational_failure(
                            boundary="Cross Gamma",
                            error=error,
                            stage="risk",
                        )
                        raw_cross_gamma = pd.DataFrame(
                            columns=list(CROSS_GAMMA_COLUMNS)
                        )
                    add_supplemental_scope(cross_gamma_market_scope(raw_cross_gamma))

                if self._new_trades_loader is not None:
                    loader = self._new_trades_loader
                    self._progress_step(
                        _callable_name(loader),
                        "risk",
                        message="Loading and validating New Trades.",
                    )
                    try:
                        raw_new_trades = self._call_connector(
                            ("supplemental", "new_trades"),
                            lambda: loader(market_date),
                            budget=connector_budget,
                        )
                    except Exception as error:
                        if not self._is_operational_connector_error(error):
                            raise
                        if isinstance(error, ConnectorRefreshBudgetError):
                            risk_circuit.trip(error)
                            market_circuit.trip(error)
                        self._log_operational_failure(
                            boundary="New Trades",
                            error=error,
                            stage="risk",
                        )
                        raw_new_trades = pd.DataFrame(columns=list(NEW_TRADE_COLUMNS))
                    add_supplemental_scope(new_trade_market_scope(raw_new_trades))

                # Supplemental identities may expand or shrink between
                # refreshes. Reuse a cached quote leg only when its Underlying
                # scope exactly matches base Risk plus the current raw sources;
                # otherwise an old XGAMMA/New Trades-only quote could linger in
                # Quick Market after its source row disappeared.
                if (
                    self._cross_gamma_matrix_loader is not None
                    or self._new_trades_loader is not None
                ):
                    for source_type in PRODUCT_SPECS_BY_SOURCE_TYPE:
                        requested_underlyings = self._requested_market_underlyings(
                            next_risk[source_type],
                            supplemental_market_scope.get(source_type, ()),
                        )
                        requested = set(requested_underlyings)
                        opened = next_open.get(source_type)
                        current_status = next_status.get(source_type)
                        opened_underlyings = (
                            set(opened[UNDERLYING]) if opened is not None else set()
                        )
                        status_underlyings = (
                            set(current_status[UNDERLYING])
                            if current_status is not None
                            else set()
                        )
                        if requested != opened_underlyings:
                            open_source_types.add(source_type)
                        if requested != status_underlyings:
                            market_status_source_types.add(source_type)

                stage_durations["risk"] = time.monotonic() - risk_started
                recalculate_source_types = (
                    changed_source_types
                    | open_source_types
                    | market_status_source_types
                )
                self._set_progress_total(
                    3
                    + 2 * len(changed_source_types)
                    + int(bool(open_source_types))
                    + int(bool(market_status_source_types))
                    + int(bool(recalculate_source_types))
                    + int(self._cross_gamma_matrix_loader is not None)
                    + int(self._new_trades_loader is not None)
                )

                if connector_budget.is_exhausted and not market_circuit.is_open:
                    budget_error = ConnectorRefreshBudgetError(
                        "The refresh connector elapsed-time budget is exhausted."
                    )
                    risk_circuit.trip(budget_error)
                    market_circuit.trip(budget_error)
                    self._log_operational_failure(
                        boundary="Connector budget",
                        error=budget_error,
                        stage="market",
                    )
                    LOGGER.warning(
                        "Connector elapsed-time budget exhausted; all remaining "
                        "risk and market network calls are skipped."
                    )
                market_started = time.monotonic()
                market_open_calls = 0
                market_status_calls = 0
                if open_source_types or market_status_source_types:
                    self._wait_for_stage(
                        "market", has_snapshot=base_snapshot is not None
                    )
                open_specs = [
                    spec
                    for spec in PRODUCT_SPECS.values()
                    if spec.source_type in open_source_types
                ]
                if open_specs:
                    self._progress_step(
                        "get_product_market_open",
                        "market_open",
                        message=f"Loading and validating {len(open_specs)} opening market snapshots.",
                    )
                for spec in open_specs:
                    source_type = spec.source_type
                    requested_underlyings = self._requested_market_underlyings(
                        next_risk[source_type],
                        supplemental_market_scope.get(source_type, ()),
                    )
                    if spec.risk_type == "Commo" and not commodity_market_enabled:
                        raw_open, _ = self._disabled_market_sources(
                            spec,
                            next_risk[source_type],
                            market_status=expected_market_status,
                        )
                    else:
                        adapter = self._connector_adapters.get(source_type)
                        uses_bulk = (
                            adapter is not None
                            and adapter.market_open_bulk is not None
                            and bool(requested_underlyings)
                        )
                        market_open_calls += (
                            1 if uses_bulk else len(requested_underlyings)
                        )
                        raw_open = self._load_product_market_open(
                            spec,
                            checker_date,
                            requested_underlyings,
                            market_status=expected_market_status,
                            circuit=market_circuit,
                            budget=connector_budget,
                        )
                    try:
                        validated_open = get_product_market_open(
                            spec, checker_date, raw_open
                        )
                        self._reject_unrequested_market_underlyings(
                            validated_open,
                            requested_underlyings,
                            label=f"{spec.key} market open",
                        )
                        next_open[source_type] = validated_open
                    except Exception:
                        self._progress_activity(
                            "get_product_market_open",
                            "market_open",
                            source_type=source_type,
                            message="Opening market validation failed.",
                        )
                        raise
                status_specs = [
                    spec
                    for spec in PRODUCT_SPECS.values()
                    if spec.source_type in market_status_source_types
                ]
                if status_specs:
                    self._progress_step(
                        "get_product_market_status",
                        "market_status",
                        message=(
                            f"Loading and validating {len(status_specs)} live or official "
                            "market snapshots."
                        ),
                    )
                for spec in status_specs:
                    source_type = spec.source_type
                    requested_underlyings = self._requested_market_underlyings(
                        next_risk[source_type],
                        supplemental_market_scope.get(source_type, ()),
                    )
                    if spec.risk_type == "Commo" and not commodity_market_enabled:
                        _, raw_status = self._disabled_market_sources(
                            spec,
                            next_risk[source_type],
                            market_status=expected_market_status,
                        )
                    else:
                        adapter = self._connector_adapters.get(source_type)
                        uses_bulk = (
                            adapter is not None
                            and adapter.market_status_bulk is not None
                            and bool(requested_underlyings)
                        )
                        market_status_calls += (
                            1 if uses_bulk else len(requested_underlyings)
                        )
                        raw_status = self._load_product_market_status(
                            spec,
                            market_date,
                            requested_underlyings,
                            market_status=expected_market_status,
                            circuit=market_circuit,
                            budget=connector_budget,
                        )
                    try:
                        validated_status = get_product_market_status(
                            spec,
                            market_date,
                            raw_status,
                            market_status=expected_market_status,
                        )
                        self._reject_unrequested_market_underlyings(
                            validated_status,
                            requested_underlyings,
                            label=f"{spec.key} market status",
                        )
                        next_status[source_type] = validated_status
                    except Exception:
                        self._progress_activity(
                            "get_product_market_status",
                            "market_status",
                            source_type=source_type,
                            message="Live or official market validation failed.",
                        )
                        raise

                market_merge_types = (
                    open_source_types
                    | market_status_source_types
                    | (set(PRODUCT_SPECS_BY_SOURCE_TYPE) - set(next_market))
                )
                for spec in PRODUCT_SPECS.values():
                    if spec.source_type not in market_merge_types:
                        continue
                    merged_market = _merge_validated_market_legs(
                        spec,
                        next_open[spec.source_type],
                        next_status[spec.source_type],
                        selected_status=expected_market_status,
                    )
                    if spec.risk_type == "Commo" and not commodity_market_enabled:
                        merged_market[MARKET_DATA_STATUS] = "Commodity market disabled"
                    next_market[spec.source_type] = merged_market
                stage_durations["market"] = time.monotonic() - market_started

                # Recalculate only products whose risk or market status changed.
                # The previous successful product frames remain immutable until
                # the whole refresh succeeds, preserving transactional fallback.
                pl_started = time.monotonic()
                if recalculate_source_types:
                    self._wait_for_stage("pl", has_snapshot=base_snapshot is not None)
                next_pl = {} if force_risk else base_pl_frames
                pl_specs = [
                    spec
                    for spec in PRODUCT_SPECS.values()
                    if spec.source_type in recalculate_source_types
                    or spec.source_type not in next_pl
                ]
                if pl_specs:
                    self._progress_step(
                        "get_product_pl",
                        "pl",
                        message=f"Calculating P&L for {len(pl_specs)} products.",
                    )
                for key, spec in PRODUCT_SPECS.items():
                    source_type = spec.source_type
                    if (
                        source_type not in recalculate_source_types
                        and source_type in next_pl
                    ):
                        continue
                    try:
                        pl_frame = get_product_pl(
                            spec,
                            next_dates[source_type],
                            multiplier=self._multipliers.get(key, 1.0),
                            validated_risk=next_risk[source_type],
                            validated_market=next_market[source_type],
                            market_date=market_date,
                            market_status=expected_market_status,
                        )
                        if spec.risk_type == "Commo" and not commodity_market_enabled:
                            pl_frame[OPEN] = 0.0
                            pl_frame[CURRENT] = 0.0
                            pl_frame[MARKET_MOVE] = 0.0
                            pl_frame[PL] = 0.0
                            pl_frame[MARKET_AVAILABLE] = True
                            pl_frame[MARKET_DATA_STATUS] = "Commodity market disabled"
                    except Exception:
                        self._progress_activity(
                            "get_product_pl",
                            "pl",
                            source_type=source_type,
                            message="Product P&L calculation failed.",
                        )
                        raise
                    pl_frame[SOURCE_TYPE] = source_type
                    pl_frame[RISK_DATE] = next_dates[source_type]
                    pl_frame[MARKET_DATE] = market_date
                    next_pl[source_type] = _with_dashboard_tenors(pl_frame, spec)

                next_overlay_frames = dict(base_overlay_frames)
                if raw_cross_gamma is not None:
                    self._progress_activity(
                        "build_cross_gamma_rows",
                        "pl",
                        message="Developing and aggregating XGAMMA output risk.",
                    )
                    cross_gamma = _with_supplemental_credit_sp01(
                        build_cross_gamma_rows(
                            raw_cross_gamma,
                            next_market,
                        )
                    )
                    if not cross_gamma.empty:
                        cross_gamma[RISK_DATE] = market_date
                        cross_gamma[MARKET_DATE] = market_date
                    next_overlay_frames["xgamma"] = cross_gamma

                if raw_new_trades is not None:
                    self._progress_activity(
                        "build_new_trade_rows",
                        "pl",
                        message=(
                            "Calculating New Trades from traded or opening reference "
                            "levels."
                        ),
                    )
                    new_trades = _with_supplemental_credit_sp01(
                        build_new_trade_rows(
                            raw_new_trades,
                            next_market,
                            multipliers=self._multipliers,
                        )
                    )
                    if not new_trades.empty:
                        new_trades[RISK_DATE] = market_date
                        new_trades[MARKET_DATE] = market_date
                    next_overlay_frames["new_trades"] = new_trades

                stage_durations["pl"] = time.monotonic() - pl_started
                final_started = time.monotonic()
                self._progress_step(
                    "_commit_full_snapshot",
                    "final",
                    message="Combining, validating and atomically publishing the snapshot.",
                )
                release_started = time.monotonic()
                enriched, dashboard, unmapped = self._release_pl_views(
                    next_pl,
                    next_config,
                    next_thresholds,
                    next_reported_underlyings,
                    next_overlay_frames,
                )
                stage_durations["release"] = time.monotonic() - release_started
                revision = 1 if base_snapshot is None else base_snapshot.revision + 1
                completed_at = self._now()
                snapshot = RefreshSnapshot(
                    revision=revision,
                    refreshed_at=completed_at,
                    last_attempt_at=attempted_at,
                    refresh_reason=reason,
                    system_date=system_date,
                    market_date=market_date,
                    checker_date=checker_date,
                    market_status=expected_market_status,
                    forced_view_date=forced_view_date,
                    risk_status=status,
                    risk_checker=next_risk_checker,
                    risk_checker_enabled=checker_enabled,
                    commodity_market_enabled=commodity_market_enabled,
                    risk_dates=next_dates,
                    forced_dates=overrides,
                    changed_source_types=tuple(sorted(changed_source_types)),
                    open_refreshed_source_types=tuple(sorted(open_source_types)),
                    market_refreshed_source_types=tuple(
                        sorted(market_status_source_types)
                    ),
                    combined_pl=enriched,
                    market_frame=self._combined_market_frame(next_market, market_date),
                    dashboard_frame=dashboard,
                    unmapped_frame=unmapped,
                    errors=self._operational_warning_snapshot(),
                )

                search_started = time.monotonic()
                search_catalog = self._build_snapshot_search_catalog(
                    revision=revision,
                    risk_frames=next_risk,
                    market_frames=next_market,
                    dashboard=dashboard,
                    risk_dates=next_dates,
                    market_date=market_date,
                    market_status=expected_market_status,
                )
                stage_durations["search"] = time.monotonic() - search_started

                commit_started = time.monotonic()
                self._commit_full_snapshot(
                    snapshot,
                    config=next_config,
                    thresholds=next_thresholds,
                    reported_underlyings=next_reported_underlyings,
                    risk_frames=next_risk,
                    market_open_frames=next_open,
                    market_status_frames=next_status,
                    market_frames=next_market,
                    pl_frames=next_pl,
                    overlay_frames=next_overlay_frames,
                    risk_dates=next_dates,
                    market_date=market_date,
                    search_catalog=search_catalog,
                    reset_generation=attempt_reset_generation,
                )
                stage_durations["commit"] = time.monotonic() - commit_started
                copy_started = time.monotonic()
                result = self._copy_snapshot(snapshot) if copy_result else None
                stage_durations["result_copy"] = (
                    time.monotonic() - copy_started if copy_result else 0.0
                )
                stage_durations["final"] = time.monotonic() - final_started
                stage_durations["total"] = time.monotonic() - refresh_started
                self._finish_progress()
                try:
                    _log_refresh_metrics(
                        reason=reason,
                        stage_durations_seconds=stage_durations,
                        call_counts={
                            "risk": risk_connector_calls,
                            "market_open": market_open_calls,
                            "market_status": market_status_calls,
                            "pl": len(pl_specs),
                            "result_copy": int(copy_result),
                        },
                        row_counts={
                            "risk": sum(
                                len(next_risk[spec.source_type]) for spec in risk_specs
                            ),
                            "market_open": sum(
                                len(next_open[spec.source_type]) for spec in open_specs
                            ),
                            "market_status": sum(
                                len(next_status[spec.source_type])
                                for spec in status_specs
                            ),
                            "pl": sum(
                                len(next_pl[spec.source_type]) for spec in pl_specs
                            ),
                            "combined_pl": len(snapshot.combined_pl),
                            "market": len(snapshot.market_frame),
                            "dashboard": len(snapshot.dashboard_frame),
                            "unmapped": len(snapshot.unmapped_frame),
                        },
                    )
                except Exception:
                    # Telemetry must never change a committed financial snapshot.
                    pass
                return result
            except StaleResetGenerationError:
                raise
            except Exception as error:
                self._require_reset_generation(attempt_reset_generation)
                incident_id = uuid.uuid4().hex[:10]
                error_type = (
                    re.sub(r"[^A-Za-z0-9_.-]", "_", type(error).__name__) or "Exception"
                )
                failed_progress = self.progress
                failure_reason = _bounded_failure_reason(error)
                LOGGER.exception(
                    "Risk refresh failed; incident=%s type=%s reason=%s "
                    "context=[%s] location=%s",
                    incident_id,
                    error_type,
                    failure_reason,
                    _failure_progress_context(failed_progress),
                    _safe_failure_location(error),
                )
                safe_error = _failure_ui_message(
                    error,
                    incident_id=incident_id,
                    progress=failed_progress,
                )
                if base_snapshot is None:
                    self._finish_progress(
                        error=safe_error,
                        failed_function_name=failed_progress.function_name,
                        failed_source_type=failed_progress.source_type,
                        failed_underlying=failed_progress.underlying,
                        failed_product_label=failed_progress.product_label,
                        failed_product_index=failed_progress.product_index,
                        failed_product_total=failed_progress.product_total,
                        failed_hold_seconds=failed_progress.hold_seconds,
                    )
                    raise
                message = (
                    f"{attempted_at.strftime('%Y-%m-%d %H:%M:%S UTC')} | "
                    f"{safe_error} Last successful data retained."
                )
                snapshot = replace(
                    base_snapshot,
                    last_attempt_at=attempted_at,
                    refresh_reason=reason,
                    changed_source_types=(),
                    open_refreshed_source_types=(),
                    market_refreshed_source_types=(),
                    errors=(message,),
                )
                self._set_progress_total(self.progress.current + 1)
                self._progress_step(
                    "_commit_snapshot",
                    "commit",
                    message="Retaining the last successful snapshot.",
                )
                self._commit_snapshot(
                    snapshot, reset_generation=attempt_reset_generation
                )
                result = self._copy_snapshot(snapshot) if copy_result else None
                self._finish_progress(
                    error=safe_error,
                    failed_function_name=failed_progress.function_name,
                    failed_source_type=failed_progress.source_type,
                    failed_underlying=failed_progress.underlying,
                    failed_product_label=failed_progress.product_label,
                    failed_product_index=failed_progress.product_index,
                    failed_product_total=failed_progress.product_total,
                    failed_hold_seconds=failed_progress.hold_seconds,
                )
                return result
        finally:
            self._refresh_lock.release()
