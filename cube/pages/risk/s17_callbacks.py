"""Public V5 Risk-page callback composition boundary."""

from __future__ import annotations

from typing import Callable

import pandas as pd
from dash import Dash

from cube.domain.s11_tenorreduction import CatalogSource, MatrixProviderLike
from cube.app.s02_contracts import (
    ControlSnapshotProtocol,
    RefreshManagerProtocol,
    RefreshSnapshotProtocol,
)
from cube.ui.s01_constants import (
    DIMENSION_FILTER_IDS,
    RISK_FILTER_DIMENSION_FIELDS,
)
from cube.app.s04_startup import StartupCoordinator

from .s07_explorer import register_explorer_callbacks
from .s12_promotecallbacks import register_promotion_callbacks
from .s15_refresh import register_refresh_callbacks
from .s02_state import _RiskDataCache
from .s14_workspacecallbacks import register_workspace_callbacks


def register_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol | None,
    initial_snapshot: ControlSnapshotProtocol | RefreshSnapshotProtocol | None,
    risk_data: pd.DataFrame,
    *,
    route_prefix: str = "/",
    startup_coordinator: StartupCoordinator | None = None,
    prepared_frame_loader: Callable[..., pd.DataFrame | None] | None = None,
    reduced_tenor_catalog: CatalogSource | None = None,
    matrix_provider: MatrixProviderLike | None = None,
) -> None:
    """Compose the independently owned Risk-page callback groups."""
    del route_prefix  # Retained at the public boundary for deployment compatibility.
    cache = _RiskDataCache(
        risk_data,
        initial_snapshot.revision if initial_snapshot is not None else 0,
        prepared_frame_loader=prepared_frame_loader,
        reduced_tenor_catalog=reduced_tenor_catalog,
        matrix_provider=matrix_provider,
    )
    dimension_filter_ids = [
        DIMENSION_FILTER_IDS[field.key] for field in RISK_FILTER_DIMENSION_FIELDS
    ]
    register_promotion_callbacks(
        app,
        cache,
        refresh_manager,
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
    )
    register_explorer_callbacks(
        app,
        refresh_manager,
        cache,
        dimension_filter_ids,
    )


__all__ = ["register_callbacks"]
