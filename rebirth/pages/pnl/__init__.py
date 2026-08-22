"""Native V4 page entry and callback facade for the governed P&L workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rebirth.app.contracts import RefreshManagerProtocol
from rebirth.ui.filter_views import SavedFilterViewControls

from .. import page_services
from .aggregate_callbacks import register_pl_aggregate_callbacks
from .common import (
    PL_FILTER_NOTE,
    PL_SAVED_VIEW_CONTROLS,
    PLSendConfig,
)
from .history_callbacks import register_pl_history_callbacks
from .send_callbacks import register_pl_send_callbacks
from .validation import register_validate_pl_callbacks
from .view import build_pl_filter_bar, build_pl_page


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
