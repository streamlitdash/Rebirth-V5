"""Explorer navigation resolves actual row keys using the active Risk tab."""

from types import SimpleNamespace

import pandas as pd
import pytest
from dash import Dash, html

from cube.domain.s10_search import ResolvedHistoryIdentity
from cube.pages.risk import s04_handoff as handoff_module
from cube.pages.risk.s06_explorertables import build_risk_table
from cube.ui.s01_constants import RISK_FILTER_DIMENSION_FIELDS
from cube.ui.s02_aggregation import parse_row_key, prepare_risk_data


def walk(node):
    yield node
    children = getattr(node, "children", None)
    for child in children if isinstance(children, (list, tuple)) else [children]:
        if child is not None:
            yield from walk(child)


def actual_underlying_selection(mode):
    base = {"source type": "credit/delta", "risk type": "Credit", "risk greek": "Delta",
            "display bucket": "Other", "region": "Europe", "group": "Energy",
            "reported underlying": "Alias", "underlying": "therm",
            "tenor swap": "1Y", "tenor swap order": 1, "tenor option": "N/A", "tenor option order": 0,
            "split": "Risk", "product": "XVA", "activity": "A", "signoffgroup": "S1",
            "category": "Core", "subcategory": "C1", "portfolio": "P1",
            "open": 3.0, "current": 4.0, "risk": 10.0, "drisk": 1.0, "pl": 10.0,
            "risk jtd": 25.0, "drisk jtd": 2.0,
            "risk threshold": 1000, "drisk threshold": 1000, "pl threshold": 1000}
    frame = prepare_risk_data(pd.DataFrame([base]))
    opened = []
    for _ in range(10):
        table = build_risk_table(frame, [], opened, promotion_enabled=False,
                                 region_enabled=False, underlying_identity_mode=mode,
                                 view_token="committed-revision-7")
        available = [node.to_plotly_json()["props"]["data-risk-key"] for node in walk(table)
                     if isinstance(node, html.Tr) and node.to_plotly_json()["props"].get("data-risk-key")]
        expanded = sorted(set(opened + available))
        if expanded == opened:
            break
        opened = expanded
    label = "therm" if mode == "underlying" else "Alias"
    button = next(node for node in walk(table) if isinstance(node, html.Button)
                  and "row-detail-button" in str(node.className) and node.children == label)
    # Delegated JavaScript uses the containing row when the label has no key.
    row = next(node for node in walk(table) if isinstance(node, html.Tr)
               and any(child is button for child in walk(node)))
    key = row.to_plotly_json()["props"]["data-risk-key"]
    assert "risk type" not in parse_row_key(key)  # The page tab owns it.
    return {"key": key, "metric": "risk", "source": "main-risk-cell"}


@pytest.mark.parametrize("mode,label", [("reported", "Alias"), ("underlying", "therm")])
def test_actual_row_label_resolves_with_current_risk_tab(mode, label):
    selection = actual_underlying_selection(mode)
    assert handoff_module.explorer_identity(selection, "Credit") == (f"Credit | Delta | {label}", mode)
    assert handoff_module.explorer_identity(selection) is None


def test_group_and_total_are_not_misinterpreted_as_underlyings():
    assert handoff_module.explorer_identity({"key": '{"risk greek":"Delta","group":"Energy"}'}, "Credit") is None
    assert handoff_module.explorer_identity({"key": ""}, "Credit") is None


@pytest.mark.parametrize("mode,label", [("reported", "Alias"), ("underlying", "therm")])
def test_explorer_button_callback_carries_typed_identity_and_shared_filters(monkeypatch, mode, label):
    calls = []

    class Manager:
        def resolve_history_identity(self, kind, combine_udl, *, identity_mode):
            calls.append((kind, combine_udl, identity_mode))
            return ResolvedHistoryIdentity(kind="risk", source_types=("credit/delta",),
                risk_type="Credit", risk_greek="Delta", underlying=label,
                identity_mode=identity_mode, source_revision=7, snapshot_date=pd.Timestamp("2026-09-11"))

    app = Dash(__name__, suppress_callback_exceptions=True)
    handoff_module.register_callbacks(app, Manager(), data_href="/data")
    button = app.callback_map["risk-explorer-open-data.disabled"]["callback"].__wrapped__
    callback = next(meta["callback"].__wrapped__ for key, meta in app.callback_map.items()
                    if "risk-explorer-data-status.children" in key)
    selection = actual_underlying_selection(mode)
    assert button(selection, "Credit") is False
    values = [["P1"] if field.key == "portfolio" else [] for field in RISK_FILTER_DIMENSION_FIELDS]
    monkeypatch.setattr(handoff_module, "ctx", SimpleNamespace(triggered_id="risk-explorer-open-data"))
    result = callback(1, selection, ["Risk"], values, [], 3, "Credit")
    payload, href, explorer_status = result
    assert calls == [("risk", f"Credit | Delta | {label}", mode)]
    assert href == "/data" and explorer_status
    raw = payload["handoff"]
    assert raw["identity"]["underlying"] == label
    assert raw["identity"]["identity_mode"] == mode
    assert raw["source_revision"] == 7 and raw["reset_generation"] == 3
    assert raw["filter_view"]["filters"] == {"Split": ["Risk"], "Portfolio": ["P1"]}
    assert raw["filter_view"]["exclude_selected"] is False
