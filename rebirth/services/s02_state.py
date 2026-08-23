"""Committed refresh state, defensive reads, progress, and atomic commits."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import pandas as pd

from rebirth.domain.s01_schema import TENOR_COLUMNS
from rebirth.domain.s10_search import (
    ResolvedHistoryIdentity,
    SearchCatalog,
    SearchResult,
    build_search_catalog,
)
from rebirth.domain.s06_reporting import attach_reported_underlying
from rebirth.domain.s03_calculations import (
    _require_market_status,
    _with_dashboard_tenors,
)
from rebirth.domain.s07_governance import (
    _merge_validated_config,
    _validate_dashboard_release,
    apply_baseline_promotions,
    to_dashboard_frame,
)
from rebirth.domain.s02_products import (
    MARKET_DATE,
    PORTFOLIO_MAPPED,
    PRODUCT_SPECS,
    PRODUCT_SPECS_BY_SOURCE_TYPE,
    RELEASE_RISK_PAIRS,
    SOURCE_TYPE,
    UNDERLYING,
    FrameName,
    ProductSpec,
)
from rebirth.services.s01_snapshots import (
    ControlSnapshot,
    FrameRead,
    PLSnapshot,
    RefreshHealthSnapshot,
    RefreshProgressSnapshot,
    RefreshSnapshot,
    StaleResetGenerationError,
)


LOGGER = logging.getLogger("rebirth.services.s06_refresh")


def _callable_name(callback: object) -> str:
    """Return a stable callable name without rendering bound arguments or data."""
    name = getattr(callback, "__name__", None)
    return str(name) if name else type(callback).__name__


def _product_progress_label(spec: ProductSpec) -> str:
    """Return a concise human-facing label without changing connector contracts."""
    risk_type = "Commodity" if spec.risk_type == "Commo" else spec.risk_type
    greek = {
        "DeltaVega": "Delta Vega",
        "XCCYVega": "XCCY Vega",
        "InflationVega": "Inflation Vega",
    }.get(spec.risk_greek, spec.risk_greek)
    return f"{risk_type} {greek}"


def _safe_failure_location(error: BaseException) -> str:
    """Describe only the final code location, never exception text or arguments."""
    traceback = error.__traceback__
    if traceback is None:
        return "unknown"
    while traceback.tb_next is not None:
        traceback = traceback.tb_next
    filename = Path(traceback.tb_frame.f_code.co_filename).name
    function_name = traceback.tb_frame.f_code.co_name
    safe_filename = re.sub(r"[^A-Za-z0-9_.-]", "_", filename) or "unknown"
    safe_function = re.sub(r"[^A-Za-z0-9_.<>-]", "_", function_name) or "unknown"
    return f"{safe_filename}:{traceback.tb_lineno}:{safe_function}"


def _log_refresh_metrics(
    *,
    stage_durations_seconds: Mapping[str, float],
    call_counts: Mapping[str, int],
    row_counts: Mapping[str, int],
) -> None:
    """Publish one bounded, identity-free metrics record for a completed refresh."""
    metrics = {
        "stage_durations_seconds": dict(stage_durations_seconds),
        "call_counts": dict(call_counts),
        "row_counts": dict(row_counts),
    }
    LOGGER.info(
        "Cube refresh metrics: %s",
        metrics,
        extra={"cube_metrics": metrics},
    )


class _RefreshStateMixin:
    @property
    def snapshot(self) -> RefreshSnapshot:
        with self._state_lock:
            if self._snapshot is None:
                raise RuntimeError("RiskRefreshManager has not been refreshed yet")
            committed = self._snapshot
        return self._copy_snapshot(committed)

    @property
    def control_snapshot(self) -> ControlSnapshot:
        """Return control metadata while copying only the readiness frame."""
        with self._state_lock:
            if self._snapshot is None:
                raise RuntimeError("RiskRefreshManager has not been refreshed yet")
            committed = self._snapshot
        return ControlSnapshot(
            revision=committed.revision,
            refreshed_at=committed.refreshed_at,
            system_date=committed.system_date,
            market_date=committed.market_date,
            checker_date=committed.checker_date,
            market_status=committed.market_status,
            forced_view_date=committed.forced_view_date,
            risk_status=committed.risk_status.copy(deep=True),
            risk_checker_enabled=committed.risk_checker_enabled,
            commodity_market_enabled=committed.commodity_market_enabled,
            risk_dates=dict(committed.risk_dates),
            forced_dates=dict(committed.forced_dates),
            errors=committed.errors,
        )

    @property
    def pl_snapshot(self) -> PLSnapshot:
        """Return the one large frame required by the PL workflow."""
        with self._state_lock:
            if self._snapshot is None:
                raise RuntimeError("RiskRefreshManager has not been refreshed yet")
            committed = self._snapshot
        return PLSnapshot(
            revision=committed.revision,
            market_date=committed.market_date,
            combined_pl=committed.combined_pl.copy(deep=True),
        )

    def read_frame(self, name: FrameName) -> FrameRead:
        """Defensively copy exactly one named committed frame.

        The metadata is captured from the same immutable snapshot reference, so
        callers can reject stale UI work without first copying every other frame.
        """
        frame_names = {
            "risk_status",
            "risk_checker",
            "combined_pl",
            "market_frame",
            "dashboard_frame",
            "unmapped_frame",
        }
        if name not in frame_names:
            raise ValueError(f"unknown committed frame {name!r}")
        with self._state_lock:
            if self._snapshot is None:
                raise RuntimeError("RiskRefreshManager has not been refreshed yet")
            committed = self._snapshot
            frame = getattr(committed, name)
        return FrameRead(
            revision=committed.revision,
            market_date=committed.market_date,
            checker_date=committed.checker_date,
            risk_checker_enabled=committed.risk_checker_enabled,
            frame=frame.copy(deep=True),
        )

    def combine_udl_options(
        self,
        *,
        identity_mode: str = "reported",
    ) -> tuple[str, ...]:
        """Return exact Quick Risk identities for the selected authority."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            raise RuntimeError("RiskRefreshManager has not been refreshed yet")
        return catalog.combine_udl_options(identity_mode=identity_mode)

    def market_udl_options(self) -> tuple[str, ...]:
        """Return identities from the complete committed MarketBook."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            raise RuntimeError("RiskRefreshManager has not been refreshed yet")
        return catalog.market_udl_options()

    def resolve_history_identity(
        self,
        kind: str,
        combine_udl: str,
        *,
        identity_mode: str = "reported",
    ) -> ResolvedHistoryIdentity:
        """Resolve one current catalog identity without parsing its label."""

        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            raise RuntimeError("RiskRefreshManager has not been refreshed yet")
        return catalog.resolve_history_identity(
            kind,
            combine_udl,
            identity_mode=identity_mode,
        )

    def search_market_udl_options(
        self,
        search_value: str | None,
        *,
        limit: int = 100,
        include: str | None = None,
    ) -> tuple[str, ...]:
        """Return bounded full-MarketBook identity choices."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            raise RuntimeError("RiskRefreshManager has not been refreshed yet")
        return catalog.search_market_udl_options(
            search_value, limit=limit, include=include
        )

    def search_combine_udl_options(
        self,
        search_value: str | None,
        *,
        identity_mode: str = "reported",
        limit: int = 100,
        include: str | None = None,
        risk_filters: Mapping[str, Sequence[str] | None] | None = None,
        exclude_selected: bool = False,
    ) -> tuple[str, ...]:
        """Return bounded current-revision dropdown choices without connector I/O."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            raise RuntimeError("RiskRefreshManager has not been refreshed yet")
        return catalog.search_combine_udl_options(
            search_value,
            identity_mode=identity_mode,
            limit=limit,
            include=include,
            risk_filters=risk_filters,
            exclude_selected=exclude_selected,
        )

    def pivot_market_exact(
        self,
        combine_udl: str,
        *,
        index_columns: Sequence[str] = (UNDERLYING, *TENOR_COLUMNS),
        limit: int | None = None,
    ) -> SearchResult:
        """Pivot one exact identity from the complete MarketBook."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            raise RuntimeError("RiskRefreshManager has not been refreshed yet")
        return catalog.pivot_market_exact(
            combine_udl, index_columns=index_columns, limit=limit
        )

    def pivot_combined(
        self,
        combine_udl: str,
        *,
        index_columns: Sequence[str] = (UNDERLYING, *TENOR_COLUMNS),
        limit: int = 500,
        identity_mode: str = "reported",
        risk_filters: Mapping[str, Sequence[str] | None] | None = None,
        exclude_selected: bool = False,
    ) -> SearchResult:
        """Build one exact-selection pivot from the current committed catalog."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            raise RuntimeError("RiskRefreshManager has not been refreshed yet")
        return catalog.pivot_combined(
            combine_udl,
            index_columns=index_columns,
            limit=limit,
            identity_mode=identity_mode,
            risk_filters=risk_filters,
            exclude_selected=exclude_selected,
        )

    def pivot_combined_hierarchy(
        self,
        combine_udl: str,
        *,
        index_columns: Sequence[str] = (UNDERLYING, *TENOR_COLUMNS),
        leaf_limit: int = 500,
        identity_mode: str = "reported",
        risk_filters: Mapping[str, Sequence[str] | None] | None = None,
        exclude_selected: bool = False,
    ) -> SearchResult:
        """Return all independently aggregated prefix levels for one identity."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            raise RuntimeError("RiskRefreshManager has not been refreshed yet")
        return catalog.pivot_combined_hierarchy(
            combine_udl,
            index_columns=index_columns,
            leaf_limit=leaf_limit,
            identity_mode=identity_mode,
            risk_filters=risk_filters,
            exclude_selected=exclude_selected,
        )

    @property
    def progress(self) -> RefreshProgressSnapshot:
        """Return progress without waiting for the transactional refresh lock."""
        with self._progress_lock:
            return replace(self._progress)

    @property
    def health(self) -> RefreshHealthSnapshot:
        """Return lightweight committed health without copying any cached frame."""
        with self._state_lock:
            snapshot = self._snapshot
            if snapshot is None:
                return RefreshHealthSnapshot(
                    revision=0,
                    refreshed_at=None,
                    last_attempt_at=None,
                    active_error_count=0,
                )
            return RefreshHealthSnapshot(
                revision=snapshot.revision,
                refreshed_at=snapshot.refreshed_at,
                last_attempt_at=snapshot.last_attempt_at,
                active_error_count=len(snapshot.errors),
            )

    @property
    def reset_generation(self) -> int:
        """Return the lightweight cache-reset generation without copying frames."""
        with self._state_lock:
            return self._reset_generation

    def _start_progress(
        self,
        started_at: datetime,
        *,
        function_name: str = "RiskRefreshManager.refresh",
        stage: str = "starting",
        message: str = "Starting refresh.",
    ) -> None:
        with self._progress_lock:
            self._progress = RefreshProgressSnapshot(
                attempt_id=uuid.uuid4().hex,
                function_name=function_name,
                source_type=None,
                underlying=None,
                product_label=None,
                product_index=0,
                product_total=0,
                hold_seconds=0.0,
                stage=stage,
                current=0,
                total=1,
                message=message,
                running=True,
                error=None,
                started_at=started_at,
                updated_at=started_at,
                finished_at=None,
            )

    def _set_progress_total(self, total: int) -> None:
        with self._progress_lock:
            planned_total = max(
                int(total), self._progress.current, self._progress.total
            )
            self._progress = replace(
                self._progress,
                total=planned_total,
                updated_at=datetime.now(timezone.utc),
            )

    def _progress_step(
        self,
        function_name: str,
        stage: str,
        *,
        source_type: str | None = None,
        underlying: str | None = None,
        product_label: str | None = None,
        product_index: int = 0,
        product_total: int = 0,
        hold_seconds: float = 0.0,
        message: str,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._progress_lock:
            current = self._progress.current + 1
            self._progress = replace(
                self._progress,
                function_name=function_name,
                source_type=source_type,
                underlying=underlying,
                product_label=product_label,
                product_index=max(0, int(product_index)),
                product_total=max(0, int(product_total)),
                hold_seconds=max(0.0, float(hold_seconds)),
                stage=stage,
                current=current,
                total=max(self._progress.total, current),
                message=message,
                running=True,
                error=None,
                updated_at=now,
                finished_at=None,
            )

    def _progress_activity(
        self,
        function_name: str,
        stage: str,
        *,
        source_type: str | None = None,
        underlying: str | None = None,
        product_label: str | None = None,
        product_index: int = 0,
        product_total: int = 0,
        hold_seconds: float = 0.0,
        message: str,
    ) -> None:
        """Report real non-work-unit activity without changing current/total."""
        now = datetime.now(timezone.utc)
        with self._progress_lock:
            self._progress = replace(
                self._progress,
                function_name=function_name,
                source_type=source_type,
                underlying=underlying,
                product_label=product_label,
                product_index=max(0, int(product_index)),
                product_total=max(0, int(product_total)),
                hold_seconds=max(0.0, float(hold_seconds)),
                stage=stage,
                message=message,
                running=True,
                error=None,
                updated_at=now,
                finished_at=None,
            )

    def _finish_progress(
        self,
        *,
        error: str | None = None,
        failed_function_name: str | None = None,
        failed_source_type: str | None = None,
        failed_underlying: str | None = None,
        failed_product_label: str | None = None,
        failed_product_index: int = 0,
        failed_product_total: int = 0,
        failed_hold_seconds: float = 0.0,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._progress_lock:
            self._progress = replace(
                self._progress,
                function_name=(
                    failed_function_name if error else self._progress.function_name
                ),
                source_type=(
                    failed_source_type if error else self._progress.source_type
                ),
                underlying=(failed_underlying if error else self._progress.underlying),
                product_label=(
                    failed_product_label if error else self._progress.product_label
                ),
                product_index=(
                    max(0, int(failed_product_index))
                    if error
                    else self._progress.product_index
                ),
                product_total=(
                    max(0, int(failed_product_total))
                    if error
                    else self._progress.product_total
                ),
                hold_seconds=(
                    max(0.0, float(failed_hold_seconds))
                    if error
                    else self._progress.hold_seconds
                ),
                stage="error" if error else "complete",
                current=(
                    self._progress.current
                    if error
                    else max(self._progress.current, self._progress.total)
                ),
                message=error or "Refresh complete.",
                running=False,
                error=error,
                updated_at=now,
                finished_at=now,
            )

    @staticmethod
    def _copy_snapshot(snapshot: RefreshSnapshot) -> RefreshSnapshot:
        """Return a defensive copy so callers cannot mutate the committed cache."""
        return replace(
            snapshot,
            risk_status=snapshot.risk_status.copy(deep=True),
            risk_checker=snapshot.risk_checker.copy(deep=True),
            risk_dates=dict(snapshot.risk_dates),
            forced_dates=dict(snapshot.forced_dates),
            combined_pl=snapshot.combined_pl.copy(deep=True),
            market_frame=snapshot.market_frame.copy(deep=True),
            dashboard_frame=snapshot.dashboard_frame.copy(deep=True),
            unmapped_frame=snapshot.unmapped_frame.copy(deep=True),
        )

    @property
    def stage_delays(self) -> dict[str, float]:
        """Return configured operator-visible refresh-stage delays."""
        return dict(self._stage_delays)

    def _now(self) -> datetime:
        """Return one timezone-aware UTC clock reading for refresh metadata."""
        value = self._clock()
        if not isinstance(value, datetime):
            raise TypeError("clock must return a datetime")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def _system_date(self, attempted_at: datetime) -> pd.Timestamp:
        """Return the refresh calendar date in the configured trading timezone."""

        return pd.Timestamp(attempted_at.astimezone(self._trading_timezone).date())

    def _resolve_market_status(self, market_date: pd.Timestamp) -> str:
        """Call the one authoritative status boundary once and validate its result."""

        self._progress_activity(
            _callable_name(self._market_status_resolver),
            "market_status",
            message=f"Resolving the market source for {market_date.date()}.",
        )
        return _require_market_status(self._market_status_resolver(market_date))

    @staticmethod
    def _release_pl_views(
        pl_frames: Mapping[str, pd.DataFrame],
        config: pd.DataFrame,
        thresholds: pd.DataFrame,
        reported_underlyings: pd.DataFrame,
        overlay_frames: Mapping[str, pd.DataFrame] | None = None,
    ) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Apply reporting governance and return enriched, dashboard, unmapped."""
        missing = set(PRODUCT_SPECS_BY_SOURCE_TYPE) - set(pl_frames)
        if missing:
            raise RuntimeError(f"P&L cache is missing product types: {sorted(missing)}")
        release_frames = [
            pl_frames[spec.source_type] for spec in PRODUCT_SPECS.values()
        ]
        release_frames.extend(
            frame for frame in (overlay_frames or {}).values() if not frame.empty
        )
        combined = pd.concat(release_frames, ignore_index=True, sort=False)
        configured = _merge_validated_config(combined, config)
        reported = attach_reported_underlying(
            configured,
            reported_underlyings,
            allowed_pairs=RELEASE_RISK_PAIRS,
        )
        enriched = apply_baseline_promotions(reported, thresholds)
        mapped = enriched.loc[enriched[PORTFOLIO_MAPPED].eq(True)].copy()
        unmapped = enriched.loc[enriched[PORTFOLIO_MAPPED].eq(False)].copy()
        dashboard = to_dashboard_frame(mapped)
        _validate_dashboard_release(dashboard)
        return enriched, dashboard, unmapped

    @staticmethod
    def _build_snapshot_search_catalog(
        *,
        revision: int,
        risk_frames: Mapping[str, pd.DataFrame],
        market_frames: Mapping[str, pd.DataFrame],
        dashboard: pd.DataFrame,
        risk_dates: Mapping[str, pd.Timestamp],
        market_date: pd.Timestamp,
        market_status: str,
    ) -> SearchCatalog:
        """Build Risk search from Risk/P&L and Market search from full quotes."""
        _require_market_status(market_status)
        return build_search_catalog(
            revision=revision,
            risk_frames=risk_frames,
            market_frames=market_frames,
            risk_pivot_frame=dashboard,
            risk_dates=risk_dates,
            market_date=market_date,
        )

    @staticmethod
    def _combined_market_frame(
        market_frames: Mapping[str, pd.DataFrame],
        market_date: pd.Timestamp,
    ) -> pd.DataFrame:
        """Return an isolated full MarketBook with all market-only tenors."""

        rows: list[pd.DataFrame] = []
        for spec in PRODUCT_SPECS.values():
            if spec.source_type not in market_frames:
                raise RuntimeError(f"full MarketBook is missing {spec.source_type!r}")
            frame = _with_dashboard_tenors(market_frames[spec.source_type], spec)
            frame[SOURCE_TYPE] = spec.source_type
            frame[MARKET_DATE] = market_date
            frame = frame.sort_values(
                [
                    UNDERLYING,
                    *spec.tenor_order_columns,
                    *spec.tenor_columns,
                ],
                kind="stable",
                na_position="last",
            ).reset_index(drop=True)
            rows.append(frame)
        return pd.concat(rows, ignore_index=True, sort=False)

    @staticmethod
    def _validate_reset_generation(value: int, *, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"{name} must be a non-negative integer")
        if value < 0:
            raise ValueError(f"{name} must be a non-negative integer")
        return value

    def _capture_reset_generation(self, expected_reset_generation: int | None) -> int:
        if expected_reset_generation is not None:
            self._validate_reset_generation(
                expected_reset_generation, name="expected_reset_generation"
            )
        with self._state_lock:
            actual_generation = self._reset_generation
        if (
            expected_reset_generation is not None
            and expected_reset_generation != actual_generation
        ):
            raise StaleResetGenerationError(
                expected_reset_generation, actual_generation
            )
        return actual_generation

    def _require_reset_generation(self, expected_generation: int) -> None:
        with self._state_lock:
            actual_generation = self._reset_generation
        if expected_generation != actual_generation:
            raise StaleResetGenerationError(expected_generation, actual_generation)

    def _commit_snapshot(
        self, snapshot: RefreshSnapshot, *, reset_generation: int
    ) -> None:
        """Commit metadata-only state without holding readers for calculation."""
        with self._state_lock:
            if reset_generation != self._reset_generation:
                raise StaleResetGenerationError(
                    reset_generation, self._reset_generation
                )
            self._snapshot = snapshot

    def _commit_full_snapshot(
        self,
        snapshot: RefreshSnapshot,
        *,
        config: pd.DataFrame,
        thresholds: pd.DataFrame,
        reported_underlyings: pd.DataFrame,
        risk_frames: dict[str, pd.DataFrame],
        market_open_frames: dict[str, pd.DataFrame],
        market_status_frames: dict[str, pd.DataFrame],
        market_frames: dict[str, pd.DataFrame],
        pl_frames: dict[str, pd.DataFrame],
        overlay_frames: dict[str, pd.DataFrame],
        risk_dates: dict[str, pd.Timestamp],
        market_date: pd.Timestamp,
        search_catalog: SearchCatalog,
        reset_generation: int,
    ) -> None:
        """Atomically publish every newly calculated cache after all work succeeds."""
        with self._state_lock:
            if reset_generation != self._reset_generation:
                raise StaleResetGenerationError(
                    reset_generation, self._reset_generation
                )
            self._config = config
            self._thresholds = thresholds
            self._reported_underlyings = reported_underlyings
            self._risk_frames = risk_frames
            self._market_open_frames = market_open_frames
            self._market_status_frames = market_status_frames
            self._market_frames = market_frames
            self._pl_frames = pl_frames
            self._overlay_frames = overlay_frames
            self._risk_dates = risk_dates
            self._market_date = market_date
            self._search_catalog = search_catalog
            self._snapshot = snapshot
