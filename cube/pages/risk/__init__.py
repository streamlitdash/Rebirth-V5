"""Native Dash Pages entry for the V5 Risk dashboard."""

from __future__ import annotations

from typing import Any

from dash import html


def layout(**_kwargs: Any):
    """Mark the active native route; the shared shell retains the Risk body."""
    return html.Div(id="risk-route-marker")


def register_callbacks(*args: Any, **kwargs: Any) -> None:
    """Register Risk behavior without loading callback modules during page discovery."""
    from .s17_callbacks import register_callbacks as register

    register(*args, **kwargs)


__all__ = ["layout", "register_callbacks"]
