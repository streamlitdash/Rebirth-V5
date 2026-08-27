"""Immutable refresh errors, committed views, progress, and health models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pandas as pd


class RefreshInProgressError(RuntimeError):
    """Raised when a refresh writer already owns the manager's refresh gate."""


class StaleRefreshError(RuntimeError):
    """Raised when a caller attempts to refresh from an obsolete revision."""

    def __init__(self, expected_revision: int, actual_revision: int) -> None:
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        super().__init__(
            "refresh revision is stale: "
            f"expected {expected_revision}, current revision is {actual_revision}"
        )


class StaleResetGenerationError(RuntimeError):
    """Raised when a refresh belongs to an obsolete cache-reset generation."""

    def __init__(self, expected_generation: int, actual_generation: int) -> None:
        self.expected_reset_generation = expected_generation
        self.actual_reset_generation = actual_generation
        super().__init__(
            "refresh reset generation is stale: "
            f"expected {expected_generation}, current generation is "
            f"{actual_generation}"
        )


@dataclass(frozen=True)
class RefreshSnapshot:
    revision: int
    refreshed_at: datetime
    last_attempt_at: datetime
    refresh_reason: str
    system_date: pd.Timestamp
    market_date: pd.Timestamp
    checker_date: pd.Timestamp
    market_status: str
    forced_view_date: pd.Timestamp | None
    risk_status: pd.DataFrame
    risk_checker: pd.DataFrame
    risk_checker_enabled: bool
    commodity_market_enabled: bool
    risk_dates: dict[str, pd.Timestamp]
    forced_dates: dict[str, pd.Timestamp]
    changed_source_types: tuple[str, ...]
    open_refreshed_source_types: tuple[str, ...]
    market_refreshed_source_types: tuple[str, ...]
    combined_pl: pd.DataFrame
    market_frame: pd.DataFrame
    dashboard_frame: pd.DataFrame
    unmapped_frame: pd.DataFrame
    errors: tuple[str, ...]


@dataclass(frozen=True)
class ControlSnapshot:
    """Small committed view for refresh controls and the dated editor.

    Only the compact readiness frame is copied.  Large P&L, dashboard, market,
    unmapped, and checker-inventory frames remain untouched in the manager.
    """

    revision: int
    refreshed_at: datetime
    last_attempt_at: datetime
    refresh_reason: str
    system_date: pd.Timestamp
    market_date: pd.Timestamp
    checker_date: pd.Timestamp
    market_status: str
    forced_view_date: pd.Timestamp | None
    risk_status: pd.DataFrame
    risk_checker_enabled: bool
    commodity_market_enabled: bool
    risk_dates: dict[str, pd.Timestamp]
    forced_dates: dict[str, pd.Timestamp]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class PLSnapshot:
    """Committed P&L view copied only when a PL workflow needs it."""

    revision: int
    market_date: pd.Timestamp
    combined_pl: pd.DataFrame


@dataclass(frozen=True)
class FrameRead:
    """One defensive frame read tied to the metadata of the same revision."""

    revision: int
    market_date: pd.Timestamp
    checker_date: pd.Timestamp
    risk_checker_enabled: bool
    frame: pd.DataFrame


@dataclass(frozen=True)
class ReductionMatrixRead:
    """Small dated matrix book published with one committed Risk revision."""

    revision: int
    matrices: dict[tuple[str, str], pd.DataFrame]
    authoritative_source_types: frozenset[str]


@dataclass(frozen=True)
class RefreshProgressSnapshot:
    """Non-sensitive, independently readable progress for one refresh attempt."""

    attempt_id: str | None
    function_name: str | None
    source_type: str | None
    underlying: str | None
    product_label: str | None
    product_index: int
    product_total: int
    hold_seconds: float
    stage: str
    current: int
    total: int
    message: str
    running: bool
    error: str | None
    started_at: datetime | None
    updated_at: datetime | None
    finished_at: datetime | None


@dataclass(frozen=True)
class RefreshHealthSnapshot:
    """Small immutable refresh health view that never copies cached DataFrames."""

    revision: int
    refreshed_at: datetime | None
    last_attempt_at: datetime | None
    active_error_count: int
