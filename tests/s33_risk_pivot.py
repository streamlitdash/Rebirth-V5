"""Focused Rebirth V4 native-pivot and Custom Risk View tests."""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import dcc

from rebirth.domain import risk_views as risk_views_module
from rebirth.domain.risk_views import CROSS_PIVOT_SPEC, PivotSpec, RiskViewRepository
from rebirth.pages.risk.pivot import (
    build_native_pivot_table,
    compute_native_pivot,
    pivot_spec_from_controls,
)
from rebirth.pages.risk.pivot_callbacks import mutate_risk_view, pivot_spec_from_command
from rebirth.pages.risk.view import build_layout
from rebirth.ui.aggregation import prepare_risk_data


def _walk(component: object) -> Iterable[object]:
    yield component
    children = getattr(component, "children", None)
    if children is None:
        return
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    else:
        yield from _walk(children)


def _raw_frame(portfolios: int = 15) -> pd.DataFrame:
    rows = []
    for index in range(portfolios):
        product = "XVA" if index % 2 == 0 else "Hedges"
        risk = float(index + 1)
        rows.append(
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
                "Product": product,
                "Activity": "Activity 1" if index % 2 == 0 else "Activity 2",
                "SignoffGroup": "SOG-A",
                "Portfolio": f"BOOK-{index:03d}",
                "Category": "Core",
                "Sub Category": "Rates",
                "Risk": risk,
                "dRisk": risk / 10.0,
                "PL": risk / 2.0,
                "Open": 3.0,
                "Current": 4.0,
                "Risk Threshold": 1_000.0,
                "dRisk Threshold": 1_000.0,
                "PL Threshold": 1_000.0,
            }
        )
    return pd.DataFrame(rows)


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


def test_native_pivot_computes_full_shape_but_returns_bounded_pages() -> None:
    frame = prepare_risk_data(_raw_frame())
    spec = PivotSpec.from_dict(
        {
            "rows": ["portfolio"],
            "columns": ["activity"],
            "measures": ["risk", "move"],
            "filters": {},
            "sort": [{"field": "portfolio", "direction": "asc"}],
            "totals": {"rows": True, "columns": True, "grand": True},
            "display": {
                "row_limit": 10,
                "column_limit": 1,
                "density": "compact",
                "show_zeros": False,
                "sticky_headers": True,
            },
        }
    )

    result = compute_native_pivot(frame, spec, row_page=2, column_page=2)

    assert result.row_count == 15
    assert result.column_count == 2
    assert len(result.row_keys) == 5
    assert len(result.column_keys) == 1
    assert result.row_offset == 10
    assert result.column_offset == 1
    # The repeated portfolio quote is one market identity, not a position-weighted sum.
    assert result.grand_totals["move"] == pytest.approx(1.0)
    assert result.row_page_count == 2
    assert result.column_page_count == 2
    table = build_native_pivot_table(result)
    assert "risk-native-pivot-wrap" in table.className


def test_compact_editor_validates_overlap_and_applies_local_filter() -> None:
    with pytest.raises(ValueError, match="must not overlap"):
        pivot_spec_from_controls(
            rows=["portfolio"],
            columns=["portfolio"],
            measures=["pl"],
            filter_field=None,
            filter_values=[],
            sort_field=None,
            sort_direction="asc",
            totals=["grand"],
            row_limit=20,
            column_limit=10,
            density="compact",
            display_flags=["sticky"],
        )

    spec = pivot_spec_from_controls(
        rows=["portfolio"],
        columns=[],
        measures=["pl"],
        filter_field="activity",
        filter_values=["Activity 1"],
        sort_field="pl",
        sort_direction="desc",
        totals=["grand"],
        row_limit=10,
        column_limit=10,
        density="compact",
        display_flags=["sticky"],
    )
    result = compute_native_pivot(prepare_risk_data(_raw_frame()), spec)
    assert result.row_count == 8
    assert all(int(key[0].split("-")[-1]) % 2 == 0 for key in result.row_keys)


def test_custom_view_actions_persist_only_validated_presentation(tmp_path) -> None:
    repository = RiskViewRepository(tmp_path / "risk_views")
    cloned = mutate_risk_view(repository, "clone-cross", name="Morning")
    assert cloned.selected is not None
    assert pivot_spec_from_command(cloned.command) == CROSS_PIVOT_SPEC

    changed_payload = CROSS_PIVOT_SPEC.to_dict()
    changed_payload["display"]["row_limit"] = 100
    edited = mutate_risk_view(
        repository,
        "edit",
        selected=cloned.selected,
        pivot=changed_payload,
    )
    assert repository.get(edited.selected).pivot.row_limit == 100

    copied = mutate_risk_view(
        repository,
        "save-copy",
        name="Afternoon",
        pivot=changed_payload,
    )
    renamed = mutate_risk_view(
        repository,
        "rename",
        selected=copied.selected,
        name="Close",
        pivot=changed_payload,
    )
    assert [option["label"] for option in renamed.options] == ["Close", "Morning"]
    deleted = mutate_risk_view(
        repository,
        "delete",
        selected=renamed.selected,
        pivot=changed_payload,
    )
    assert deleted.selected is None
    documents = list((tmp_path / "risk_views").glob("*.json"))
    assert len(documents) == 1
    assert "financial" not in documents[0].read_text(encoding="utf-8").casefold()


def test_custom_repository_has_a_hard_document_cap(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(risk_views_module, "MAX_RISK_VIEWS", 2)
    repository = RiskViewRepository(tmp_path)
    repository.save_new("One", CROSS_PIVOT_SPEC)
    repository.save_new("Two", CROSS_PIVOT_SPEC)
    with pytest.raises(ValueError, match="limited to 2"):
        repository.save_new("Three", CROSS_PIVOT_SPEC)


def test_risk_explorer_has_exact_v4_tabs_and_page_owned_custom_controls() -> None:
    raw = _raw_frame(3)
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
        ("Custom", "custom"),
    ]
    component_ids = {
        component_id
        for item in components
        if isinstance((component_id := getattr(item, "id", None)), str)
    }
    assert {
        "custom-risk-panel",
        "risk-custom-view-selector",
        "risk-pivot-rows",
        "risk-pivot-columns",
        "risk-pivot-measures",
        "risk-pivot-apply",
        "risk-custom-grid",
    } <= component_ids
