"""Native V4 route and composition boundary for the Stock page."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from dash import dcc, html

from .. import page_services
from .s04_callbacks import register_callbacks
from .s01_data import default_stock_dates
from .s03_view import build_stock_page_shell


def build_stock_page_route(
    reference_date: object | None,
    *,
    available: bool,
    history_available: bool = False,
):
    """Build the Stock route without reaching into shared application state."""

    if not available:
        return html.Main(
            [
                html.H1("Stock", className="static-data-page-title"),
                html.P(
                    "GetStock and its Portfolio mapping are not configured.",
                    id="stock-unavailable",
                    className="static-data-empty",
                ),
            ],
            id="stock-page",
            className="static-data-page",
        )
    if reference_date is None:
        raise ValueError("An available Stock page requires a reference date")

    current_date, prior_date = default_stock_dates(reference_date)
    page = build_stock_page_shell(
        current_date=current_date,
        prior_date=prior_date,
        history_available=history_available,
    )
    page.children = [
        dcc.Store(id="stock-request-scope", data=uuid4().hex),
        *page.children,
    ]
    return page


def layout(**_kwargs: Any):
    """Build Stock only when its native URL is active."""

    builder = page_services()["stock_page_builder"]
    if not callable(builder):
        raise RuntimeError("The Stock page builder is not callable")
    return builder()


__all__ = ["build_stock_page_route", "layout", "register_callbacks"]
