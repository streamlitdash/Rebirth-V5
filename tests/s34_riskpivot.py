"""Focused Risk Explorer layout regressions."""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace

import pandas as pd
from dash import dcc

from cube.pages.risk.s16_view import build_layout
from cube.ui.s02_aggregation import prepare_risk_data


def _walk(component: object) -> Iterable[object]:
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None:
        yield from _walk(children)


def _raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Source Type": "ir/delta",
                "Risk Type": "IR",
                "Risk Greek": "Delta",
                "Display Bucket": "Other",
                "Region": "Americas",
                "Group": "G10",
                "Reported Underlying": "USD-SOFR",
                "Underlying": "USD-SOFR",
                "Tenor Swap": "1Y",
                "Tenor Option": "N/A",
                "Split": "Risk",
                "Product": "XVA",
                "Activity": "Activity 1",
                "SignoffGroup": "SOG-A",
                "Portfolio": "BOOK-001",
                "Category": "Core",
                "Sub Category": "Rates",
                "Risk": 1.0,
                "dRisk": 0.1,
                "PL": 0.5,
                "Open": 3.0,
                "Current": 4.0,
                "Risk Threshold": 1_000.0,
                "dRisk Threshold": 1_000.0,
                "PL Threshold": 1_000.0,
                "Vol Score": 42.0,
            }
        ]
    )


def _snapshot(frame: pd.DataFrame) -> SimpleNamespace:
    status = pd.DataFrame(
        [
            {
                "Source Type": "ir/delta",
                "Suggested Risk Date": pd.Timestamp("2026-08-13"),
                "Effective Risk Date": pd.Timestamp("2026-08-13"),
                "Age": 0,
                "Age Defaulted": False,
                "Force Risk": False,
            }
        ]
    )
    return SimpleNamespace(
        revision=1,
        refreshed_at=pd.Timestamp("2026-08-14 08:00", tz="UTC").to_pydatetime(),
        system_date=pd.Timestamp("2026-08-14"),
        market_date=pd.Timestamp("2026-08-14"),
        market_status="OFFICIAL",
        checker_date=pd.Timestamp("2026-08-13"),
        risk_dates={"ir/delta": pd.Timestamp("2026-08-13")},
        risk_status=status,
        forced_dates={},
        forced_view_date=None,
        commodity_market_enabled=False,
        risk_checker_enabled=True,
        dashboard_frame=frame,
    )


def test_risk_explorer_keeps_only_cross_and_splitva_with_inline_actions() -> None:
    raw = _raw_frame()
    layout = build_layout(prepare_risk_data(raw), _snapshot(raw), refresh_enabled=True)
    components = list(_walk(layout))
    tabs = next(
        item
        for item in components
        if isinstance(item, dcc.Tabs) and item.id == "table-view-tabs"
    )
    assert [(tab.label, tab.value) for tab in tabs.children] == [
        ("Cross", "main"),
        ("SplitVA", "alt"),
    ]

    component_ids = {
        component_id
        for item in components
        if isinstance((component_id := getattr(item, "id", None)), str)
    }
    assert not any("custom" in component_id for component_id in component_ids)

    options = next(
        item
        for item in components
        if getattr(item, "id", None) == "risk-explorer-options"
    )
    assert options.value == ["promotion"]
    assert [option["value"] for option in options.options] == [
        "region",
        "promotion",
        "reduced-tenor",
    ]
    assert {
        "split-filter",
        "underlying-identity-mode",
        "underlying-sort-metric",
        "risk-explorer-options",
        "promotion-recalculate-current-view",
        "promotion-reset-baseline",
        "promotion-generation-status",
    } <= component_ids
    explorer_fields = [
        item
        for item in components
        if "control-field" in set(str(getattr(item, "className", "")).split())
        and any(
            getattr(child, "id", None)
            in {
                "split-filter",
                "underlying-identity-mode",
                "underlying-sort-metric",
                "risk-explorer-options",
                "promotion-recalculate-current-view",
            }
            for child in _walk(item)
        )
    ]
    assert len(explorer_fields) == 4

    identity_mode = next(
        item
        for item in components
        if getattr(item, "id", None) == "underlying-identity-mode"
    )
    assert identity_mode.value == "reported"
    assert [option["value"] for option in identity_mode.options] == [
        "reported",
        "underlying",
    ]
    options_field = next(
        item
        for item in components
        if "risk-explorer-option-field"
        in set(str(getattr(item, "className", "")).split())
    )
    options_field_ids = {getattr(item, "id", None) for item in _walk(options_field)}
    assert {"risk-explorer-options", "underlying-identity-mode"} <= options_field_ids
