"""Dual-axis charts keep truthful values and a common centered zero line."""

import math
import sys

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pytest
from dash import dcc

from cube.adapters.s08_stock import STOCK_DATE_COLUMN
from cube.pages.risk.s05_charts import build_line_chart
from cube.pages.risk.s09_quickmarket import _market_line_chart
from cube.pages.stock.s02_history import build_stock_value_history_figure
from cube.ui.s09_plot_axes import center_dual_y_axes


def assert_centered(figure, primary_bound, secondary_bound):
    for axis, bound in (
        (figure.layout.yaxis, primary_bound),
        (figure.layout.yaxis2, secondary_bound),
    ):
        assert list(axis.range) == pytest.approx([-bound, bound])
        assert axis.autorange is False
        assert axis.fixedrange is True
        # Zero has the same normalized pixel position on each vertical axis.
        low, high = axis.range
        assert -low / (high - low) == 0.5
    assert figure.layout.yaxis2.overlaying == "y"
    assert figure.layout.xaxis.fixedrange is not True


@pytest.mark.parametrize(
    "primary,secondary,expected",
    [
        ([100, -3], [-200000, 20], (110, 220000)),
        ([2, 3], [-100, -200], (3.3, 220)),
        ([-20, -30], [1, 2], (33, 2.2)),
        ([0, 0], [0], (1, 1)),
        ([], [], (1, 1)),
        ([None, np.nan, np.inf, -np.inf], [None, np.nan], (1, 1)),
        ([1e-20], [-3e-20], (1.1e-20, 3.3e-20)),
    ],
)
def test_independent_axes_center_with_unbalanced_signs_and_missing_values(
    primary, secondary, expected
):
    figure = go.Figure([
        go.Bar(name="Total", y=primary),
        go.Scatter(name="Component", y=secondary, yaxis="y2"),
    ])
    figure.update_layout(yaxis2={"overlaying": "y", "side": "right"})
    assert center_dual_y_axes(figure) is figure
    assert_centered(figure, *expected)
    assert [trace.yaxis or "y" for trace in figure.data] == ["y", "y2"]


def test_all_secondary_series_contribute_without_modifying_values_or_axis_titles():
    figure = go.Figure([
        go.Bar(name="Total", y=[2, -1]),
        go.Scatter(name="XVA", y=[40, None], yaxis="y2"),
        go.Scatter(name="Hedges", y=[-300, 20], yaxis="y2", visible="legendonly"),
    ])
    figure.update_layout(
        yaxis={"title": "Total Risk"},
        yaxis2={"title": "XVA / Hedges", "overlaying": "y", "side": "right"},
    )
    center_dual_y_axes(figure)
    assert_centered(figure, 2.2, 330)
    assert list(figure.data[1].y) == [40, None]
    assert list(figure.data[2].y) == [-300, 20]
    assert figure.layout.yaxis.title.text == "Total Risk"
    assert figure.layout.yaxis2.title.text == "XVA / Hedges"


def test_largest_finite_value_does_not_create_infinite_range():
    figure = go.Figure([
        go.Bar(y=[sys.float_info.max]),
        go.Scatter(y=[1], yaxis="y2"),
    ])
    figure.update_layout(yaxis2={"overlaying": "y"})
    center_dual_y_axes(figure)
    assert all(math.isfinite(value) for value in figure.layout.yaxis.range)
    assert figure.layout.yaxis.range == (-sys.float_info.max, sys.float_info.max)


def detail_rows():
    return pd.DataFrame({
        "tenor swap": ["1Y", "2Y"],
        "tenor swap order": [0, 1],
        "risk": [1000., -100.],
        "risk expo": [20000., -4000.],
        "risk hedges": [-19000., 3900.],
        "open": [1000., 2000.],
        "current": [1010., 1980.],
        "move": [10., -20.],
    })


def test_tenor_selector_risk_keeps_total_bars_primary_and_components_secondary():
    graph = build_line_chart(
        detail_rows(), "tenor swap", "tenor swap order", "risk", "Risk", "Swap"
    )
    assert isinstance(graph, dcc.Graph)
    figure = graph.figure
    assert [trace.type for trace in figure.data] == ["bar", "scatter", "scatter"]
    assert [trace.yaxis or "y" for trace in figure.data] == ["y", "y2", "y2"]
    assert list(figure.data[0].y) == [1000., -100.]
    assert_centered(figure, 1100, 22000)


def test_tenor_selector_market_move_returns_graph_and_aligns_both_axes():
    graph = build_line_chart(
        detail_rows(), "tenor swap", "tenor swap order", "move", "Market", "Swap"
    )
    assert isinstance(graph, dcc.Graph)
    figure = graph.figure
    assert [trace.type for trace in figure.data] == ["bar", "scatter", "scatter"]
    assert [trace.yaxis or "y" for trace in figure.data] == ["y", "y2", "y2"]
    assert list(figure.data[0].y) == [10., -20.]
    assert_centered(figure, 22, 2200)


@pytest.mark.parametrize("metric", ["open", "current"])
def test_tenor_selector_single_market_metric_still_returns_graph(metric):
    graph = build_line_chart(
        detail_rows(), "tenor swap", "tenor swap order", metric, "Market", "Swap"
    )
    assert isinstance(graph, dcc.Graph)
    assert len(graph.figure.data) == 1
    assert list(graph.figure.data[0].y) == detail_rows()[metric].tolist()
    assert graph.figure.layout.yaxis.fixedrange is not True


def test_quick_market_preserves_quote_and_move_axis_ownership():
    rows = pd.DataFrame({
        "Tenor Swap": ["1Y", "2Y"],
        "Tenor Swap Order": [0, 1],
        "Open": [1000., 2000.],
        "Current": [1010., 1980.],
    })
    figure = _market_line_chart(rows, axis="Tenor Swap", market_status="LIVE").figure
    assert [trace.name for trace in figure.data] == ["Market Move", "Open", "LIVE"]
    assert [trace.yaxis or "y" for trace in figure.data] == ["y2", "y", "y"]
    assert list(figure.data[0].y) == [10., -20.]
    assert_centered(figure, 2200, 22)


def test_stock_history_keeps_level_and_change_values_on_their_existing_axes():
    history = pd.DataFrame({
        STOCK_DATE_COLUMN: ["2026-09-08", "2026-09-09", "2026-09-10"],
        "Market Value": [1000., 1005., 1001.],
    })
    figure = build_stock_value_history_figure(
        history, crds="001", activity="Trading", start_date="2026-09-09",
        end_date="2026-09-10",
    )
    assert [trace.name for trace in figure.data] == ["Stock", "dStock"]
    assert [trace.yaxis or "y" for trace in figure.data] == ["y", "y2"]
    assert list(figure.data[0].y) == [1005., 1001.]
    assert list(figure.data[1].y) == [5., -4.]
    assert_centered(figure, 1105.5, 5.5)
