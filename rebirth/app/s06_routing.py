"""Native Dash page catalogue for the V4 application shell."""

from dash import page_registry, register_page

from rebirth.pages.data import layout as data_page_layout
from rebirth.pages.s01_notfound import layout as not_found_page_layout
from rebirth.pages.pnl import layout as pnl_page_layout
from rebirth.pages.risk import layout as risk_page_layout
from rebirth.pages.static_data import layout as static_data_page_layout
from rebirth.pages.stock import layout as stock_page_layout


def register_native_pages() -> None:
    """Install one deterministic page catalogue with stable callables."""

    page_registry.clear()
    register_page(
        "rebirth.pages.risk",
        path="/",
        name="Risk",
        title="Cube — Risk",
        order=0,
        layout=risk_page_layout,
    )
    register_page(
        "rebirth.pages.data",
        path="/data",
        name="Data",
        title="Cube — Data",
        order=1,
        layout=data_page_layout,
    )
    register_page(
        "rebirth.pages.stock",
        path="/stock",
        name="Stock",
        title="Cube — Stock",
        order=2,
        layout=stock_page_layout,
    )
    register_page(
        "rebirth.pages.pnl",
        path="/pnl",
        name="P&L",
        title="Cube — P&L Sender",
        order=3,
        layout=pnl_page_layout,
    )
    register_page(
        "rebirth.pages.static_data",
        path="/static-data",
        name="Statics",
        title="Cube — Statics",
        order=4,
        layout=static_data_page_layout,
    )
    register_page(
        # Dash recognizes this registry key as the custom 404 handler. The
        # implementation remains in the ordered s01_notfound module above.
        "rebirth.pages.not_found_404",
        path="/404",
        name="Page not found",
        title="Cube — Page not found",
        order=99,
        layout=not_found_page_layout,
    )


__all__ = ["register_native_pages"]
