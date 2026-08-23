"""Compose and run the Rebirth V4.1 Dash application."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from rebirth.adapters.s08_stock import get_stock
from rebirth.app.s07_factory import build_app
from rebirth.app.s03_logging import configure_runtime_logging, perf_span
from rebirth.app.s01_settings import RuntimeSettings, resolve_data_path
from rebirth.history import SQLPLHistoryRepository, build_market_history_loader
from rebirth.pages.pnl import PLSendConfig
from rebirth.pages.stock.s02_history import SQLStockHistoryRepository
from rebirth.services.s03_adjustments import LocalCsvAdjustmentRepository
from rebirth.services.s05_sources import (
    build_production_refresh_manager,
    get_portfolio_config,
    send_portfolio_pl,
    send_sog_pl,
)


configure_runtime_logging()
LOGGER = logging.getLogger(__name__)

_parser = argparse.ArgumentParser(description="Rebirth V4.1 Risk Cube")
_parser.add_argument("--port", type=int, help="Port (default: PORT or 8050).")
_parser.add_argument("--host", help="Host (default: HOST or 127.0.0.1).")
_parser.add_argument("--debug", action="store_true", help="Enable Dash debug mode.")


def create_app(settings: RuntimeSettings | None = None):
    """Build the shell and lazy service boundaries without reading source data."""
    settings = settings or RuntimeSettings.from_env()
    manager = build_production_refresh_manager(
        stage_delays={
            "risk_product": float(os.getenv("RISK_PRODUCT_DELAY_SECONDS", "0")),
        }
    )
    project_root = Path(__file__).resolve().parent
    mapping_path = resolve_data_path(
        os.getenv("CONCERTO_MAPPING_PATH"),
        Path("data/s08_concerto.csv"),
        root=project_root,
    )
    adjustment_path = resolve_data_path(
        os.getenv("PL_ADJUSTMENT_PATH"),
        Path("adjustments"),
        root=project_root,
    )
    history_path = resolve_data_path(
        os.getenv("PL_HISTORICAL_PATH"),
        Path("data/histo"),
        root=project_root,
    )
    saved_view_path = resolve_data_path(
        os.getenv("SAVED_FILTER_VIEWS_PATH"),
        Path("data/saved_views"),
        root=project_root,
    )
    pl_send_config = PLSendConfig(
        mapping_source=mapping_path,
        adjustment_repository=LocalCsvAdjustmentRepository(adjustment_path),
        send_sog_pl=send_sog_pl,
        send_portfolio_pl=send_portfolio_pl,
        history_source=SQLPLHistoryRepository(history_path),
    )
    with perf_span(LOGGER, "app.build", budget_ms=1_000):
        return build_app(
            refresh_manager=manager,
            pl_send_config=pl_send_config,
            stock_source=get_stock,
            stock_portfolio_source=get_portfolio_config,
            stock_history_source=SQLStockHistoryRepository(history_path),
            saved_view_root=saved_view_path,
            pl_history_root=history_path,
            market_history_loader=build_market_history_loader(history_path),
            dash_kwargs=settings.dash_kwargs,
        )


def parse_args():
    """Parse optional local and JupyterHub launch overrides."""
    return _parser.parse_args()


def _configure_cli_environment(args) -> None:
    if args.port is not None:
        os.environ["PORT"] = str(args.port)
    if args.host is not None:
        os.environ["HOST"] = args.host
    if args.debug:
        os.environ["DASH_DEBUG"] = "1"


if __name__ == "__main__":
    _configure_cli_environment(parse_args())


SETTINGS = RuntimeSettings.from_env()
app = create_app(SETTINGS)
server = app.server


def run_app() -> None:
    """Run the already-constructed local app without a duplicate reloader."""
    app.run(
        debug=SETTINGS.debug,
        host=SETTINGS.host,
        port=SETTINGS.port,
        use_reloader=False,
    )


if __name__ == "__main__":
    run_app()
