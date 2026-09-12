"""JTD: exact branch scope, column filters, full totals, and bounded pages."""

import json
import ast
from pathlib import Path
from functools import partial

import pandas as pd
import pytest
from dash import Dash, dash_table

from cube.pages.risk.s07_explorer import register_explorer_callbacks
from cube.pages.risk.s13_workspacetables import build_jtd_reference_table
from cube.services.s08_jtd import JTDReferenceError, JTD_PAGE_SIZE, jtd_page, jtd_reference_rows


def walk(node):
    yield node
    children = getattr(node, "children", None)
    for child in children if isinstance(children, (list, tuple)) else [children]:
        if child is not None:
            yield from walk(child)


def query(column, operation, value):
    return {"type": "relational-operator", "subType": operation,
            "left": {"type": "expression", "subType": "field", "value": column},
            "right": {"type": "expression", "subType": "value", "value": value}}


@pytest.fixture
def frame():
    return pd.DataFrame({"Underlying": ["therm"] * 60,
                         "CRDS": [f"{n:06d}" for n in range(60)],
                         "Risk JTD": [-9000, 8000] + list(range(58)),
                         "EAD": [-1200.5] + [2000] * 59})


def test_lookup_matches_raw_names_once_preserves_identifiers_and_measures(tmp_path):
    path = tmp_path / "jtd.csv"
    pd.DataFrame({"Underlying": ["therm", "therm-more", "other", "therm"],
                  "CRDS": ["0001", "0002", "0003", "0004"],
                  "Risk JTD": ["-9,000", "8000", "10000", "100"],
                  "EAD": ["-1200.50", "2000", "", "1"]}).to_csv(path, index=False)
    result = jtd_reference_rows(["therm", "therm-more", "therm"], path=path)
    assert result["CRDS"].tolist() == ["0001", "0002", "0004"]
    assert result["Risk JTD"].tolist() == [-9000, 8000, 100]
    assert result["EAD"].tolist() == [-1200.5, 2000, 1]
    assert jtd_reference_rows("therm", path=path)["CRDS"].tolist() == ["0001", "0004"]


@pytest.mark.parametrize("content,match", [
    ("", "Could not read"), ("Issuer\ntherm\n", "Underlying"),
    ("Underlying\ntherm\n", "Risk JTD"),
    ("Underlying,Risk JTD\ntherm,oops\n", "invalid numbers"),
    ("Underlying,Risk JTD\ntherm,inf\n", "invalid numbers"),
])
def test_bad_reference_has_useful_error(tmp_path, content, match):
    path = tmp_path / "jtd.csv"
    path.write_text(content)
    with pytest.raises(JTDReferenceError, match=match):
        jtd_reference_rows("therm", path=path)


def test_full_total_stays_first_on_every_page_and_never_changes_source(frame):
    before = frame.copy(deep=True)
    first, count, page, _ = jtd_page(frame)
    second, _, _, _ = jtd_page(frame, 1)
    assert count == 3 and page == 0
    assert len(first) == len(second) == JTD_PAGE_SIZE + 1
    assert first[0] == second[0]
    assert first[0]["CRDS"] is None
    assert first[0]["Risk JTD"] == frame["Risk JTD"].sum()
    assert first[0]["EAD"] == frame["EAD"].sum()
    assert first[1]["Risk JTD"] == -9000
    assert first[2]["Risk JTD"] == 8000
    pd.testing.assert_frame_equal(frame, before)


def test_column_filter_searches_beyond_first_page_and_recalculates_total(frame):
    records, count, page, _ = jtd_page(frame, 9, query("CRDS", "contains", "000059"))
    assert (count, page) == (1, 0)
    assert records[1]["CRDS"] == "000059"
    assert records[0]["Risk JTD"] == records[1]["Risk JTD"] == 57
    assert records[0]["EAD"] == 2000


@pytest.mark.parametrize("operation,value,expected", [
    ("<", "0", [-9000]), (">=", "8,000", [8000]), ("=", 8000, [8000]),
    ("!=", -9000, [8000] + list(range(57, 33, -1))),
])
def test_numeric_filters(frame, operation, value, expected):
    records, _, _, _ = jtd_page(frame, filter_tree=query("Risk JTD", operation, value))
    assert [row["Risk JTD"] for row in records[1:]] == expected


def test_case_insensitive_literal_text_and_combined_column_filters(frame):
    tree = {"type": "logical-operator", "subType": "&&",
            "left": query("Underlying", "icontains", "THERM"),
            "right": query("EAD", "<", "0")}
    assert jtd_page(frame, filter_tree=tree)[0][1]["CRDS"] == "000000"
    assert len(jtd_page(frame, filter_tree=query("Underlying", "contains", ".*"))[0]) == 1


def test_explicit_sort_is_full_result_and_total_cannot_move(frame):
    records, _, _, _ = jtd_page(frame, sort_by=[{"column_id": "CRDS", "direction": "desc"}])
    assert records[0]["Underlying"] == "Total (filtered rows)"
    assert records[1]["CRDS"] == "000059"
    assert records[0]["Risk JTD"] == frame["Risk JTD"].sum()


def test_missing_values_remain_missing_in_total_and_json(frame):
    frame["EAD"] = float("nan")
    records, _, _, _ = jtd_page(frame)
    assert records[0]["EAD"] is None
    json.dumps(records, allow_nan=False)
    records, count, page, note = jtd_page(frame, filter_tree=query("CRDS", "=", "missing"))
    assert len(records) == 1 and records[0]["Risk JTD"] is None
    assert count == page == 0 and "No matching" in note


def test_invalid_or_unknown_filter_is_not_silently_ignored(frame):
    with pytest.raises(JTDReferenceError, match="incomplete"):
        jtd_page(frame, filter_query="{Risk JTD} >")
    with pytest.raises(JTDReferenceError, match="shown"):
        jtd_page(frame, filter_tree=query("missing", "=", "x"))


def test_100k_row_selection_only_serializes_one_page(frame):
    large = pd.concat([frame] * 1667, ignore_index=True)
    records, pages, _, _ = jtd_page(large)
    assert len(large) > 100000
    assert len(records) == 26 and pages > 4000
    assert records[0]["Risk JTD"] == large["Risk JTD"].sum()


def test_table_has_normal_filters_top_total_and_sign_formatting(frame):
    component = build_jtd_reference_table(frame, ["therm"])
    table = next(node for node in walk(component) if isinstance(node, dash_table.DataTable))
    ids = {getattr(node, "id", None) for node in walk(component)}
    assert "jtd-search" not in ids and "jtd-search-column" not in ids
    assert table.filter_action == "custom" and table.page_action == "custom"
    assert table.filter_options["case"] == "insensitive"
    assert table.data[0]["Underlying"] == "Total (filtered rows)"
    assert table.style_cell["color"] == "#111111"
    for name in ["Risk JTD", "EAD"]:
        column = next(column for column in table.columns if column["id"] == name)
        assert column["format"].to_plotly_json()["specifier"] == ",.2f"
        assert any(rule["if"].get("column_id") == name and rule["color"] == "#b91c1c"
                   for rule in table.style_data_conditional if "color" in rule)


def test_only_one_callback_owns_jtd_paging_and_filtering():
    app = Dash(__name__, suppress_callback_exceptions=True)
    register_explorer_callbacks(app, None, None, [])
    callbacks = [value for key, value in app.callback_map.items() if "jtd-table.data" in key]
    assert len(callbacks) == 1
    assert [(item["id"], item["property"]) for item in callbacks[0]["inputs"]] == [
        ("jtd-scope", "data"), ("jtd-table", "page_current"),
        ("jtd-table", "derived_filter_query_structure"), ("jtd-table", "sort_by")]


@pytest.mark.parametrize("table_view,credit_view", [
    ("main", "single"), ("main", "multi"), ("alt", "single"), ("alt", "multi")])
@pytest.mark.parametrize("context,expected", [
    ({"underlying": "therm"}, {"therm"}),
    ({"group": "Energy"}, {"therm", "therm-more"}),
    ({"reported underlying": "Alias"}, {"RAW_A", "RAW_B"}),
    ({}, {"therm", "therm-more", "RAW_A", "RAW_B"}),
])
def test_detail_renderer_preserves_clicked_scope_in_cross_and_splitva(tmp_path, table_view, credit_view, context, expected):
    """Exercise the existing nested detail renderer, without calling a connector."""
    from cube.pages.risk import s07_explorer as explorer
    from cube.pages.risk.s02_state import _RiskDataCache
    from cube.ui.s02_aggregation import prepare_risk_data, row_key

    base = {"source type": "credit/delta", "risk type": "Credit", "risk greek": "Delta",
            "display bucket": "Other", "region": "Europe", "group": "Energy",
            "reported underlying": "therm", "underlying": "therm",
            "tenor swap": "1Y", "tenor swap order": 1, "tenor option": "N/A", "tenor option order": 0,
            "split": "Risk", "product": "XVA", "activity": "A", "signoffgroup": "S1",
            "category": "Core", "subcategory": "C1", "portfolio": "P1",
            "open": 3.0, "current": 4.0, "risk": 10.0, "drisk": 1.0, "pl": 10.0,
            "risk jtd": 25.0, "drisk jtd": 2.0,
            "risk threshold": 1000, "drisk threshold": 1000, "pl threshold": 1000}
    risk = prepare_risk_data(pd.DataFrame([
        base, {**base, "underlying": "therm-more", "reported underlying": "therm-more"},
        {**base, "underlying": "RAW_A", "reported underlying": "Alias", "group": "OtherGroup"},
        {**base, "underlying": "RAW_B", "reported underlying": "Alias", "group": "OtherGroup"},
    ]))
    source = tmp_path / "jtd.csv"
    pd.DataFrame({"Underlying": ["therm", "therm-more", "RAW_A", "RAW_B", "absent"],
                  "Risk JTD": [-9000, 5000, 100, 200, 99999],
                  "EAD": [1, 2, 3, 4, 5]}).to_csv(source, index=False)
    tree = ast.parse(Path(explorer.__file__).read_text(encoding="utf-8"))
    function = next(node for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "render_active_detail")
    function.decorator_list = []
    env = {**vars(explorer), "cache": _RiskDataCache(risk, 1), "refresh_manager": None,
           "jtd_reference_rows": partial(jtd_reference_rows, path=source)}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), explorer.__file__, "exec"), env)
    selection = {"key": row_key(context) if context else "", "metric": "risk",
                 "source": "alt-risk-cell" if table_view == "alt" else "main-risk-cell"}
    if table_view == "main" and credit_view == "multi":
        selection.update(source="credit-risk-cell", credit_measure="JTD")
    panel, _, _ = env["render_active_detail"](
        active_risk_type="Credit", ir_family=None, splits=["Risk"], table_view=table_view,
        credit_view=credit_view, credit_measure="JTD", selection=selection,
        plot_measure="risk", plot_component="total", tenor_view="auto",
        dimension_values=[[] for _ in explorer.RISK_FILTER_DIMENSION_FIELDS])
    scope = next(node.data for node in walk(panel) if getattr(node, "id", None) == "jtd-scope")
    assert set(scope) == expected
    table = next(node for node in walk(panel) if isinstance(node, dash_table.DataTable))
    assert set(row["Underlying"] for row in table.data[1:]) == expected
