"""Public facade for the V4 Statics Dash page."""

from .callbacks import register_callbacks
from .view import (
    STATIC_FILE_OPTIONS,
    build_static_data_page,
    build_static_data_table,
    layout,
)


__all__ = [
    "STATIC_FILE_OPTIONS",
    "build_static_data_page",
    "build_static_data_table",
    "layout",
    "register_callbacks",
]
