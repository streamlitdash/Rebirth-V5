"""Quick Risk charts: full-width figures, with no tenor-detail panel or tables."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from cube.ui.s02_aggregation import detail_frame, tenor_axis_order
from cube.ui.s09_plot_axes import center_dual_y_axes
from .s01_common import _meaningful_tenor_mask

RISK_SERIES = ("risk", "risk expo", "risk hedges")
RISK_LABELS = ("Total Risk", "Risk XVA", "Risk Hedges")
RISK_COLORS = ("#4C8A4A", "#4C87B9", "#C26464")
MAX_SURFACE_CELLS = 250_000


def _chart_style(figure, *, surface=False):
    figure.update_layout(
        template="plotly_white", autosize=True,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Arial, sans-serif", "size": 12, "color": "#48515C"},
        margin={"l": 75, "r": 80, "t": 45, "b": 85},
        hoverlabel={"font": {"size": 12}},
        legend={"orientation": "h", "y": 1.12, "x": 0},
        hovermode="closest" if surface else "x unified",
        bargap=0.3,
    )
    figure.update_xaxes(automargin=True, showgrid=False, tickfont={"size": 11})
    figure.update_yaxes(automargin=True, tickfont={"size": 11})
    return dcc.Graph(
        figure=figure, responsive=True, className="quick-risk-plot",
        style={"height": "560px" if surface else "500px", "width": "100%"},
        config={"displayModeBar": False, "responsive": True},
    )


def _order_note(ambiguous):
    return html.P(
        "Some underlying tenor ranks differ; the shared connector-order rule is used.",
        className="quick-risk-chart-note",
    ) if ambiguous else None


def _curve_chart(detail, axis):
    labels, ambiguous = tenor_axis_order(detail, axis, f"{axis} order")
    curve = detail.groupby(axis, sort=False)[list(RISK_SERIES)].sum(min_count=1)
    curve.index = curve.index.astype(str)
    curve = curve.reindex(labels)
    figure = go.Figure()
    figure.add_bar(
        name=RISK_LABELS[0], x=labels, y=curve[RISK_SERIES[0]],
        marker_color=RISK_COLORS[0], opacity=0.45,
        hovertemplate="Total Risk: %{y:,.2f}<extra></extra>",
    )
    for column, name, color in zip(RISK_SERIES[1:], RISK_LABELS[1:], RISK_COLORS[1:]):
        figure.add_scatter(
            name=name, x=labels, y=curve[column], mode="lines+markers",
            line={"color": color, "width": 2.5}, marker={"size": 5},
            connectgaps=False, yaxis="y2",
            hovertemplate=name + ": %{y:,.2f}<extra></extra>",
        )
    figure.update_xaxes(
        title_text=axis.title(), type="category", categoryorder="array",
        categoryarray=labels, tickangle=-30,
    )
    figure.update_yaxes(
        title_text="Total Risk", tickformat=",.0f",
        zeroline=True, zerolinecolor="#89939E", gridcolor="#E6EBF0",
    )
    figure.update_layout(yaxis2={
        "title": {"text": "Risk XVA / Hedges"}, "overlaying": "y", "side": "right",
        "tickformat": ",.0f", "showgrid": False,
    })
    center_dual_y_axes(figure)
    return html.Div([
        html.H3(axis.title(), className="quick-risk-chart-title"),
        _chart_style(figure), _order_note(ambiguous),
    ])


def _surface_chart(detail):
    swaps, swap_ambiguous = tenor_axis_order(detail, "tenor swap", "tenor swap order")
    options, option_ambiguous = tenor_axis_order(detail, "tenor option", "tenor option order")
    # Check before unstack allocates the rectangular plotting grid.
    if len(swaps) * len(options) > MAX_SURFACE_CELLS:
        return html.P(
            "This surface is too large to draw. Narrow the shared filters; the pivot totals still include all selected positions.",
            className="quick-risk-chart-note",
        )
    values = detail.groupby(["tenor option", "tenor swap"])["risk"].sum(min_count=1)
    matrix = values.unstack("tenor swap").reindex(index=options, columns=swaps)
    numeric = matrix.to_numpy(dtype=float, na_value=np.nan)
    finite = numeric[np.isfinite(numeric)]
    bound = max(float(np.abs(finite).max()), 1e-12) if finite.size else 1.0
    figure = go.Figure(go.Heatmap(
        x=swaps, y=options, z=numeric, zmin=-bound, zmax=bound, zmid=0,
        colorscale=[[0, "#C26464"], [0.5, "#FCFCFA"], [1, "#4C8A4A"]],
        xgap=1, ygap=1, hoverongaps=False,
        colorbar={"title": {"text": "Total Risk"}, "thickness": 12, "tickformat": ",.0f"},
        hovertemplate=("Swap: %{x}<br>Option: %{y}<br>Total Risk: %{z:,.2f}<extra></extra>"),
    ))
    figure.update_xaxes(
        title_text="Tenor Swap", type="category", categoryorder="array",
        categoryarray=swaps, tickangle=-30,
    )
    figure.update_yaxes(
        title_text="Tenor Option", type="category", categoryorder="array",
        categoryarray=options, autorange="reversed", showgrid=False,
    )
    return html.Div([
        html.H3("Total Risk surface", className="quick-risk-chart-title"),
        _chart_style(figure, surface=True), _order_note(swap_ambiguous or option_ambiguous),
    ])


def build_quick_risk_chart(scope: pd.DataFrame):
    """Plot each actual tenor shape once, without controls or duplicate tables.

    The same validated detail aggregation as the tenor selector keeps Risk XVA
    and hedge splits and connector tenor ranks. Spot rows stay in the pivot.
    """
    detail = detail_frame(scope, {}, "risk") if not scope.empty else pd.DataFrame()
    if detail.empty:
        return None
    for axis in ("tenor swap", "tenor option"):
        if axis in detail:
            detail[axis] = detail[axis].astype("string").str.strip()
    swap = _meaningful_tenor_mask(detail["tenor swap"])
    option = _meaningful_tenor_mask(detail["tenor option"])
    charts = []
    # Separate mixed row shapes so no position is counted in two charts.
    surface = swap & option
    if surface.any():
        charts.append(_surface_chart(detail.loc[surface]))
    for axis, mask in (("tenor swap", swap & ~option), ("tenor option", option & ~swap)):
        if mask.any():
            charts.append(_curve_chart(detail.loc[mask], axis))
    return html.Div(charts, className="quick-risk-chart-stack") if charts else None
