"""Native V4 page entry and callback facade for the governed P&L workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rebirth.app.s02_contracts import RefreshManagerProtocol
from rebirth.ui.s03_filters import SavedFilterViewControls

from .. import page_services
from .s08_aggregate import register_pl_aggregate_callbacks
from .s01_common import (
    PL_FILTER_NOTE,
    PL_SAVED_VIEW_CONTROLS,
    PLSendConfig,
)
from .s09_drilldown import register_pl_history_callbacks
from .s05_sendcallbacks import register_pl_send_callbacks
from .s06_validation import register_validate_pl_callbacks
from .s07_view import build_pl_filter_bar, build_pl_page


def layout(**_kwargs: Any):
    """Build the P&L page through this Dash app's injected page service."""
    builder = page_services()["pnl_page_builder"]
    if not callable(builder):
        raise RuntimeError("The P&L page builder is not callable")
    return builder()


def register_callbacks(
    app,
    refresh_manager: RefreshManagerProtocol,
    *,
    history_root: str | Path,
    config: PLSendConfig | None = None,
    prepared_frame_loader=None,
    saved_view_controls: SavedFilterViewControls | None = None,
) -> None:
    """Register the page-owned callbacks once with factory-owned dependencies."""

    register_pl_aggregate_callbacks(
        app,
        refresh_manager,
        history_source=config.history_source if config is not None else None,
        prepared_frame_loader=prepared_frame_loader,
        saved_view_controls=saved_view_controls,
    )
    if config is None:
        return
    register_validate_pl_callbacks(app, history_root)
    register_pl_history_callbacks(app, config)
    register_pl_send_callbacks(app, refresh_manager, config)


__all__ = [
    "PL_FILTER_NOTE",
    "PL_SAVED_VIEW_CONTROLS",
    "PLSendConfig",
    "build_pl_filter_bar",
    "build_pl_page",
    "layout",
    "register_callbacks",
]
