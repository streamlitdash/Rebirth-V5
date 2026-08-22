"""Compose the Dash application from its connector and storage boundaries."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from adapters.s05_stock import get_stock, load_stock_history
from core.archive_sql import SQLPLHistoryRepository
from core.s05_storage import LocalCsvAdjustmentRepository
from core.s11_risk_archive import (
    build_market_history_loader,
)
from feeds.s01_sources import (
    build_production_refresh_manager,
    get_portfolio_config,
    send_portfolio_pl,
    send_sog_pl,
)
from s02_config import RuntimeSettings, resolve_data_path
from pages.pnl import PLSendConfig
from shared.factory import build_app


_parser = argparse.ArgumentParser(description="Risk Cube Dashboard")
_parser.add_argument(
    "--port",
    type=int,
    default=None,
    help="Port to bind (default: PORT or 8050).",
)
_parser.add_argument(
    "--host",
    type=str,
    default=None,
    help="Host to bind (default: HOST or 127.0.0.1).",
)
_parser.add_argument(
    "--debug",
    action="store_true",
    help="Enable Dash debug mode.",
)


def create_app(settings: RuntimeSettings | None = None):
    """Build the application without loading connector data.

    The checked-in feeds read clearly labelled fake CSV fixtures. Replace the
    connector bodies in ``feeds/s01_sources.py`` before production use.
    """
    settings = settings or RuntimeSettings.from_env()
    manager = build_production_refresh_manager(
        stage_delays={
            "risk_product": float(os.getenv("RISK_PRODUCT_DELAY_SECONDS", "1")),
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
    historical_pl_path = resolve_data_path(
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
        history_source=SQLPLHistoryRepository(historical_pl_path),
    )
    return build_app(
        refresh_manager=manager,
        pl_send_config=pl_send_config,
        stock_source=get_stock,
        stock_portfolio_source=get_portfolio_config,
        stock_history_source=lambda identity, start_date, end_date: load_stock_history(
            historical_pl_path,
            start_date,
            end_date,
            identity=identity,
        ),
        saved_view_root=saved_view_path,
        pl_history_root=historical_pl_path,
        market_history_loader=build_market_history_loader(historical_pl_path),
        dash_kwargs=settings.dash_kwargs,
    )


def parse_args():
    """Parse the optional local/JupyterHub launch overrides."""
    return _parser.parse_args()


def _configure_cli_environment(args) -> None:
    """Apply command-line overrides before constructing the one Dash app."""
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
    """Run the already-constructed local app without enabling a reloader."""
    app.run(
        debug=SETTINGS.debug,
        host=SETTINGS.host,
        port=SETTINGS.port,
        use_reloader=False,
    )


if __name__ == "__main__":
    run_app()
