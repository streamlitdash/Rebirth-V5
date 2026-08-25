"""Public facade for the V5 Statics Dash page."""

from .s03_callbacks import register_callbacks
from .s01_store import StaticDataStore
from .s02_view import (
    STATIC_FILE_OPTIONS,
    STATIC_WRITE_OPTIONS,
    build_static_data_page,
    build_static_data_table,
    layout,
)


__all__ = [
    "STATIC_FILE_OPTIONS",
    "STATIC_WRITE_OPTIONS",
    "StaticDataStore",
    "build_static_data_page",
    "build_static_data_table",
    "layout",
    "register_callbacks",
]
