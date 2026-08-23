"""Native Dash Pages entry for the V4 Risk dashboard."""

from __future__ import annotations

from typing import Any

from .. import page_services


def layout(**_kwargs: Any):
    """Build the current app's cold shell or committed Risk dashboard."""
    builder = page_services()["risk_page_builder"]
    if not callable(builder):
        raise RuntimeError("The Risk page builder is not callable")
    return builder()


def register_callbacks(*args: Any, **kwargs: Any) -> None:
    """Register Risk behavior without loading callback modules during page discovery."""
    from .s19_callbacks import register_callbacks as register

    register(*args, **kwargs)


__all__ = ["layout", "register_callbacks"]
