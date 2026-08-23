"""Plotly figure for the inline, lazy Aggregate P&L history view."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
import plotly.graph_objects as go

from rebirth.domain.s08_pnl import (
    COLOSSUS_TYPE,
    HISTORY_TYPE,
    MARKET_DATE,
    PL,
    PREDICT_TYPE,
)


def build_pl_history_figure(
    series: pd.DataFrame,
    *,
    path: Sequence[str] = (),
) -> go.Figure:
    """Plot observed Colossus and/or Predict daily series without filling gaps."""

    figure = go.Figure()
    label = " → ".join(str(value) for value in path) or "TOTAL"
    required_columns = {MARKET_DATE, HISTORY_TYPE, PL}
    if not isinstance(series, pd.DataFrame):
        raise TypeError("series must be a pandas DataFrame")
    if not required_columns.issubset(series.columns):
        if not series.empty:
            missing = sorted(required_columns - set(series.columns))
            raise ValueError(f"P&L history series is missing columns: {missing}")
        series = pd.DataFrame(columns=[MARKET_DATE, HISTORY_TYPE, PL])
    styles = {
        COLOSSUS_TYPE: {"color": "#1f77b4", "dash": "solid", "symbol": "circle"},
        PREDICT_TYPE: {"color": "#ff7f0e", "dash": "dash", "symbol": "diamond"},
    }
    for history_type in (COLOSSUS_TYPE, PREDICT_TYPE):
        scoped = series.loc[series[HISTORY_TYPE].eq(history_type)].sort_values(
            MARKET_DATE,
            kind="stable",
        )
        if scoped.empty:
            continue
        style = styles[history_type]
        figure.add_trace(
            go.Scatter(
                x=scoped[MARKET_DATE],
                y=scoped[PL],
                mode="lines+markers",
                name=history_type,
                line={"color": style["color"], "dash": style["dash"]},
                marker={"symbol": style["symbol"]},
                customdata=[[history_type, label] for _index in scoped.index],
                hovertemplate=(
                    "Market Date %{x}<br>P&L Type %{customdata[0]}<br>"
                    "Scope %{customdata[1]}<br>P&L %{y:,.0f}<extra></extra>"
                ),
            )
        )
    if not figure.data:
        figure.add_annotation(
            text="Select a P&L cell to plot its observed daily series.",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
        )
    figure.update_layout(
        title=f"Colossus / Predict P&L · {label}",
        xaxis_title="Market Date",
        yaxis_title="P&L",
        hovermode="x unified",
        margin={"l": 70, "r": 30, "t": 60, "b": 70},
        template="plotly_white",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
    )
    figure.update_xaxes(type="date", automargin=True)
    figure.update_yaxes(automargin=True, tickformat=",.0f", zeroline=True)
    return figure


__all__ = ["build_pl_history_figure"]
