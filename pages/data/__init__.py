"""Native V3.2 Risk and Market history page."""

from __future__ import annotations

from typing import Any

from .. import page_services
from .callbacks import register_callbacks
from .view import build_data_page


def layout(**_kwargs: Any):
    """Build the Data route without reading archive files."""

    builder = page_services()["data_page_builder"]
    if not callable(builder):
        raise RuntimeError("The Data page builder is not callable")
    return builder()


__all__ = ["build_data_page", "layout", "register_callbacks"]
