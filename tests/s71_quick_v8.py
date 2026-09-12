"""Quick search keeps typing local and charts follow actual tenor coordinates."""
import ast
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from dash import dcc

from cube.domain.s10_search import SearchCatalog
from cube.pages.risk.s08_quickrisk import build_quick_search
from cube.pages.risk.s09_quickmarket import build_quick_market_search
from cube.pages.risk.s16_quickriskcharts import build_quick_risk_chart
from cube.ui.s02_aggregation import prepare_risk_data


def walk(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from walk(item)
    elif hasattr(value, "to_plotly_json"):
        yield value
        yield from walk(getattr(value, "children", None))


def fixture_rows():
    rows = []
    for name, greek, axes in (
        ("SPOT", "Delta", [("Spot", "N/A", 0, 0)]),
        ("CURVE", "Delta", [("2Y", "N/A", 9, 0), ("10Y", "N/A", 2, 0)]),
        ("OPTION", "Vega", [("N/A", "1Y", 0, 3)]),
        ("SURFACE", "Vega", [("2Y", "1Y", 9, 3), ("10Y", "1Y", 2, 3), ("10Y", "2Y", 2, 4)]),
    ):
        for swap, option, swap_order, option_order in axes:
            for portfolio, product, risk in (("A", "XVA", 10.), ("B", "Hedges", -2.)):
                rows.append({
                    "Source Type": "ir/vega" if greek == "Vega" else "ir/delta",
                    "Risk Type": "IR", "Risk Greek": greek, "Underlying": name,
                    "Reported Underlying": name, "Tenor Swap": swap, "Tenor Option": option,
                    "Tenor Swap Order": swap_order, "Tenor Option Order": option_order,
                    "Portfolio": portfolio, "Product": product, "Split": "Risk",
                    "Risk": risk, "dRisk": 1., "PL": risk, "Open": 3., "Current": 4., "Move": 1.,
                    "Group": "G10", "Activity": "Rates", "Category": "Core", "Sub Category": "Rates",
                    "SignoffGroup": "Rates", "Region": "Europe", "Display Bucket": "Other",
                    "Risk Threshold": 1000., "dRisk Threshold": 1000., "PL Threshold": 1000.,
                    "Market Date": pd.Timestamp("2026-09-11"), "Market Status": "LIVE",
                    "Market Data Status": "Available",
                })
    return pd.DataFrame(rows)


def catalog_for(rows):
    keys = ["Source Type", "Risk Type", "Risk Greek", "Underlying", "Tenor Swap", "Tenor Option"]
    market = rows.drop_duplicates(keys)[[
        *keys, "Tenor Swap Order", "Tenor Option Order", "Market Date", "Open", "Current", "Move",
        "Market Status", "Market Data Status",
    ]]
    return SearchCatalog(revision=3, risk_dates={"ir/delta": pd.Timestamp("2026-09-10"), "ir/vega": pd.Timestamp("2026-09-10")},
                         market_date=pd.Timestamp("2026-09-11"), market_frame=market, risk_pivot_frame=rows)


@pytest.mark.parametrize("name,kind", [("SPOT", None), ("CURVE", "scatter"), ("OPTION", "scatter"), ("SURFACE", "heatmap")])
def test_automatic_chart_shapes_and_full_width(name, kind):
    prepared = prepare_risk_data(fixture_rows())
    result = build_quick_risk_chart(prepared.loc[prepared.underlying.eq(name)])
    graphs = [item for item in walk(result) if isinstance(item, dcc.Graph)]
    if kind is None:
        assert result is None
        return
    assert len(graphs) == 1
    graph = graphs[0]
    assert graph.responsive and graph.style["width"] == "100%"
    assert graph.figure.data[0].type == kind
    assert not any(isinstance(item, dcc.Dropdown) for item in walk(result))
    if name == "CURVE":
        assert list(graph.figure.data[0].x) == ["10Y", "2Y"]  # connector rank, not label sorting
        assert list(graph.figure.data[0].y) == [8., 8.]
        assert len(graph.figure.data) == 3  # total, XVA and hedge on one scale
    if name == "SURFACE":
        matrix = np.asarray(graph.figure.data[0].z, dtype=float)
        assert matrix.shape == (2, 2)
        assert np.isnan(matrix[1, 1])  # missing tenor cell stays missing
        assert np.nansum(matrix) == 24.


def test_scoped_label_catalog_matches_existing_search_for_all_filter_modes():
    catalog = catalog_for(fixture_rows())
    for filters in ({}, {"Portfolio": ["A"]}, {"Portfolio": ["MISSING"]}, {"Split": ["Risk"], "Portfolio": ["B"]}):
        for exclude in (False, True):
            assert catalog.combine_udl_options(risk_filters=filters, exclude_selected=exclude) == catalog.search_combine_udl_options(
                None, limit=100, risk_filters=filters, exclude_selected=exclude,
            )


def test_search_indexes_mounted_and_no_chart_view_picker():
    for embedded in (False, True):
        risk = list(walk(build_quick_search(embedded=embedded)))
        market = list(walk(build_quick_market_search(embedded=embedded)))
        assert sum(getattr(item, "id", None) == "quick-risk-search-index" for item in risk) == 1
        assert sum(getattr(item, "id", None) == "quick-market-search-index" for item in market) == 1
        assert not any(getattr(item, "id", None) == "quick-risk-tenor-view" for item in risk)


def test_typing_does_not_trigger_server_callback_or_financial_render():
    module = ast.parse((Path(__file__).parents[1] / "cube/pages/risk/s14_workspacecallbacks.py").read_text())
    definitions = {node.name: node for node in ast.walk(module) if isinstance(node, ast.FunctionDef)}
    for name in ("load_combine_udl_options", "load_market_udl_options", "render_current_pivot", "render_quick_risk_tenor", "render_market_search"):
        assert '"search_value"' not in ast.unparse(definitions[name]).replace("'", '"')

