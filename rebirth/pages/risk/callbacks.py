"""Public V4 Risk-page callback composition boundary."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from dash import Dash, Input

from rebirth.app.contracts import (
    MarketHistoryLoaderProtocol,
    RefreshManagerProtocol,
    RefreshSnapshotProtocol,
)
from rebirth.domain.risk_views import RiskViewRepository
from rebirth.ui.constants import DIMENSION_FILTER_IDS, FILTER_DIMENSION_FIELDS
from rebirth.app.startup import StartupCoordinator

from .explorer_callbacks import register_explorer_callbacks
from .pivot_callbacks import register_pivot_callbacks
from .promotion_callbacks import register_promotion_callbacks
from .refresh_callbacks import register_refresh_callbacks
from .state import _RiskDataCache
from .workspace_callbacks import register_workspace_callbacks


def register_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol | None,
    initial_snapshot: RefreshSnapshotProtocol | None,
    risk_data: pd.DataFrame,
    *,
    route_prefix: str = "/",
    startup_coordinator: StartupCoordinator | None = None,
    market_history_loader: MarketHistoryLoaderProtocol | None = None,
    risk_view_repository: RiskViewRepository | None = None,
) -> None:
    """Compose the independently owned Risk-page callback groups."""
    del route_prefix  # Retained at the public boundary for deployment compatibility.
    cache = _RiskDataCache(
        risk_data,
        initial_snapshot.revision if initial_snapshot is not None else 0,
    )
    custom_view_repository = risk_view_repository or RiskViewRepository(
        Path(__file__).resolve().parents[3] / "data" / "risk_views"
    )
    dimension_filter_ids = [
        DIMENSION_FILTER_IDS[field.key] for field in FILTER_DIMENSION_FIELDS
    ]
    dimension_filter_inputs = [
        Input(component_id, "value") for component_id in dimension_filter_ids
    ]

    register_promotion_callbacks(
        app,
        cache,
        refresh_manager,
        dimension_filter_ids,
    )
    register_pivot_callbacks(
        app,
        cache,
        refresh_manager,
        custom_view_repository,
    )
    register_refresh_callbacks(
        app,
        refresh_manager,
        initial_snapshot,
        cache,
        startup_coordinator=startup_coordinator,
    )
    register_workspace_callbacks(
        app,
        refresh_manager,
        cache,
        dimension_filter_ids,
        dimension_filter_inputs,
        market_history_loader=market_history_loader,
    )
    register_explorer_callbacks(
        app,
        refresh_manager,
        cache,
        dimension_filter_ids,
        dimension_filter_inputs,
    )


__all__ = ["register_callbacks"]
