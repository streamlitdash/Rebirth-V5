"""Keep two independently scaled vertical axes on one shared zero baseline."""

from __future__ import annotations

from math import isfinite

import plotly.graph_objects as go


def center_dual_y_axes(figure: go.Figure) -> go.Figure:
    """Center y and y2 on zero without changing their values or ownership.

    Each axis includes all of its finite trace values with 10% headroom. An
    empty or all-zero axis uses [-1, 1]. Vertical zoom is fixed so interaction
    cannot move one zero away from the other; horizontal zoom still works.
    Call after adding the traces and the overlaid secondary-axis layout.
    """
    maxima = {"y": 0.0, "y2": 0.0}
    for trace in figure.data:
        axis = getattr(trace, "yaxis", None) or "y"
        if axis not in maxima:
            continue
        values = getattr(trace, "y", None)
        for value in values if values is not None else ():
            try:
                number = float(value)
            except (TypeError, ValueError, OverflowError):
                continue
            if isfinite(number):
                maxima[axis] = max(maxima[axis], abs(number))

    for axis, maximum in maxima.items():
        bound = maximum * 1.1 if maximum else 1.0
        if not isfinite(bound):
            bound = maximum
        figure.update_layout(
            **{
                "yaxis" if axis == "y" else "yaxis2": {
                    "range": [-bound, bound],
                    "autorange": False,
                    "fixedrange": True,
                    "zeroline": axis == "y",
                }
            }
        )
    return figure
