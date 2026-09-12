"""Trusted Stock hierarchy, column filters, and committed refresh ownership."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import Dash, dash_table, html, no_update
from dash._callback_context import context_value
from dash._utils import AttributeDict
from dash.exceptions import PreventUpdate

from cube.pages.stock.s01_data import StockPageData, load_stock_page_data, stock_index_columns
from cube.pages.stock.s03_view import build_stock_page_shell, stock_number_styles, stock_table_columns
from cube.pages.stock.s04_callbacks import register_callbacks, stock_history_result, stock_raw_page
from cube.pages.stock.s05_pivot import build_stock_tree


@pytest.fixture
def raw():
    return pd.DataFrame([
        ["S1", "G1", "Alpha", "000A", 1, 100.0, 15_000.0],
        ["S1", "G2", "Alpha", "000A", 2, -20.0, 10_000.0],
        ["S1", "G1", "Beta", "000B", 1, 30.0, 30_000.0],
        ["S1", "G2", "Beta", "000B", 1, 40.0, -28_000.0],
        ["S1", "G1", "Gamma", "000C", 1, -50.0, -20_001.0],
        ["S1", "G2", "Delta", "000D", 1, 60.0, 20_000.0],
        ["S2", "G1", "Alpha", "000A", 1, 70.0, 20_000.0],
        ["S2", "G1", "Phi", "000F", 1, 80.0, -30_000.0],
    ], columns=["Sign-off group", "Group", "Counterparty name", "CRDS", "Custom numeric index", "Stock", "dStock"])


def payload(row):
    return json.loads(row["id"])


def walk(node):
    yield node
    children = getattr(node, "children", None)
    for child in children if isinstance(children, (list, tuple)) else [children]:
        if child is not None:
            yield from walk(child)


def expanded_rows(frame):
    opened = set()
    for _ in range(20):
        records = build_stock_tree(frame, list(opened))
        found = {payload(row)["path"] for row in records if payload(row)["branch"]}
        if found <= opened:
            return records
        opened |= found
    pytest.fail("Stock hierarchy did not terminate")


def invoke(function, *args, trigger=None):
    triggers = trigger if isinstance(trigger, (list, tuple)) else ([trigger] if trigger else [])
    updated = {}
    token = context_value.set(AttributeDict(updated_props=updated, triggered_inputs=(
        [{"prop_id": value, "value": None} for value in triggers]
    )))
    try:
        result = function(*args)
        if function.__name__ == "render_current_stock":
            receipt = updated.get("refresh-view-stock-current", {}).get("data", no_update)
            return (*result, receipt)
        return result
    finally:
        context_value.reset(token)


def callbacks(raw, *, source=None, history=None):
    manager = SimpleNamespace(health=SimpleNamespace(revision=1),
                              control_snapshot=SimpleNamespace(market_date=pd.Timestamp("2026-09-11")))
    calls = []

    def connector(day):
        calls.append(day)
        return source(day) if source else raw

    app = Dash(__name__, suppress_callback_exceptions=True)
    register_callbacks(app, refresh_manager=manager, stock_source=connector, stock_history_source=history)

    def callback(output):
        return next(item["callback"].__wrapped__ for key, item in app.callback_map.items() if output in key)

    return manager, calls, callback("stock-loaded-snapshot.data"), callback("stock-tree-rows.data")


def load(fn, revision=1, *, trigger="stock-load-trigger.n_intervals"):
    return invoke(fn, 1, revision, None, "2026-09-10", {"id": f"refresh-{revision}"}, trigger=trigger)


def render(fn, token, *, opened=None, raw_open=False, selection=None,
           trigger="stock-loaded-snapshot.data", request="refresh-1"):
    return invoke(fn, token, opened, raw_open, 0, [], None, "", selection, "all", None, None, 25,
                  {"id": request}, trigger=trigger)


def test_current_connector_object_columns_index_and_supplied_change_are_preserved(raw):
    raw.index = [7] * len(raw)
    raw.attrs["stock_date"] = "2026-09-09"
    before = raw.copy(deep=True)
    page = load_stock_page_data(stock_source=lambda _day: raw, current_date="2026-09-11")
    assert page.raw is raw
    assert page.current_date == pd.Timestamp("2026-09-09")
    assert stock_index_columns(raw) == list(raw.columns[:-2])
    build_stock_tree(raw)
    pd.testing.assert_frame_equal(raw, before)


def test_initial_view_shows_signoff_promotions_and_other_with_net_threshold(raw):
    records = build_stock_tree(raw)
    top = [row for row in records if len(json.loads(payload(row)["path"])) == 1]
    assert len(top) == 2 and all(payload(row)["open"] for row in top)
    promoted = [row for row in records if row["Promoted"]]
    assert [(json.loads(payload(row)["path"])[0][1], payload(row)["selection"]["value"], row["dStock"])
            for row in promoted] == [("S1", "000A", 25_000), ("S1", "000C", -20_001), ("S2", "000F", -30_000)]
    # 000B nets to only 2k, 000D is exactly 20k, and S2's 000A stays separate.
    others = [row for row in records if json.loads(payload(row)["path"])[-1][0] == "other"]
    assert [row["dStock"] for row in others] == [22_000, 20_000]
    assert all(not payload(row)["open"] for row in others + promoted)
    assert len(records) == 7


def test_full_expansion_keeps_extra_numeric_dimensions_and_counts_every_source_once(raw):
    records = expanded_rows(raw)
    leaves = [row for row in records if not payload(row)["branch"]]
    assert len(leaves) == len(raw)
    assert sum(row["Stock"] for row in leaves) == raw["Stock"].sum()
    assert sum(row["dStock"] for row in leaves) == raw["dStock"].sum()
    assert all(json.loads(payload(row)["path"])[-1][0] == "Custom numeric index" for row in leaves)


@pytest.mark.parametrize("identifier", ["CRDS", "CIDS"])
def test_row_ids_contain_selection_and_expansion_for_browser_clicks(raw, identifier):
    frame = raw.rename(columns={"CRDS": identifier})
    records = build_stock_tree(frame)
    row = next(row for row in records if row["Promoted"])
    selected = payload(row)
    assert selected["selection"] == {"column": identifier, "value": "000A"}
    opened = [payload(item)["path"] for item in records if payload(item)["open"]]
    opened.append(selected["path"])
    assert len(opened) == 3
    visible = build_stock_tree(frame, opened)
    assert any("G1" in row["Hierarchy"] for row in visible)
    # An ordinary identifier below Other also opens history.
    all_rows = expanded_rows(frame)
    ordinary = next(row for row in all_rows if payload(row)["selection"] == {"column": identifier, "value": "000B"})
    assert payload(ordinary)["selection"] == {"column": identifier, "value": "000B"}


def test_one_collapsed_raw_area_and_only_stock_measures_in_main_table():
    shell = build_stock_page_shell(current_date=pd.Timestamp("2026-09-11"), history_available=True)
    nodes = list(walk(shell))
    assert len([node for node in nodes if isinstance(node, html.Details)]) == 1
    raw = next(node for node in nodes if getattr(node, "id", None) == "stock-raw-panel")
    assert raw.open is False
    tables = {node.id: node for node in nodes if isinstance(node, dash_table.DataTable)}
    assert "stock-current-table" not in tables  # native Risk Explorer hierarchy, no pages
    assert any(getattr(node, "id", None) == "stock-tree-rows" for node in nodes)
    assert tables["stock-raw-table"].filter_action == "custom"
    assert tables["stock-raw-table"].page_action == "custom"
    assert tables["stock-raw-table"].style_table["width"] == "100%"


def test_numeric_source_columns_have_commas_red_negatives_and_black_positives(raw):
    columns = stock_table_columns(raw)
    numeric = [column for column in columns if column.get("type") == "numeric"]
    assert {column["id"] for column in numeric} == {"Stock", "dStock", "Custom numeric index"}
    assert all(column["format"].to_plotly_json()["specifier"] == ",.2f" for column in numeric)
    styles = stock_number_styles(columns)
    assert all(rule["if"]["filter_query"].endswith("< 0") and rule["color"] == "#c5221f" for rule in styles)


def test_raw_filter_uses_all_rows_then_sorts_and_pages_without_mutating_source():
    frame = pd.DataFrame({"CRDS": [f"{i:06d}" for i in range(100_001)],
                          "Stock": range(100_001), "dStock": [-1.0] * 100_001})
    before = frame.copy(deep=True)
    records, pages, total, page = stock_raw_page(frame, 0, 25, [], None, "")
    assert len(records) == 25 and (pages, total, page) == (4001, 100_001, 0)
    tree = {"type": "relational-operator", "subType": "=", "value": "i=",
            "left": {"subType": "field", "value": "CRDS"}, "right": {"subType": "value", "value": "100000"}}
    records, pages, total, page = stock_raw_page(frame, 999, 25, [], tree, '{CRDS} = "100000"')
    assert (pages, total, page) == (1, 1, 0) and records[0]["CRDS"] == "100000"
    records, _, _, _ = stock_raw_page(frame, 0, 25, [{"column_id": "Stock", "direction": "desc"}], None, "")
    assert records[0]["Stock"] == 100_000
    pd.testing.assert_frame_equal(frame, before)


def test_loading_reuses_one_revision_and_clicks_do_not_call_connector(raw):
    manager, calls, loader, renderer = callbacks(raw)
    token, _ = load(loader)
    assert load(loader)[0] == token and len(calls) == 1
    first = render(renderer, token)
    assert len(first) == 13 and first[-1]["status"] == "rendered"
    assert first[-1]["revision"] == 1 and first[-1]["request_id"] == "refresh-1"
    assert first[1].to_plotly_json()["props"]["data-refresh-render"] == first[-1]["mounts"][0]
    assert all(value is no_update for value in first[2:7])  # raw data stays lazy
    render(renderer, token, opened=[], trigger="stock-pivot-open-paths.data")
    assert len(calls) == 1
    manager.health.revision = 2
    next_token, _ = load(loader, 2, trigger="refresh-commit-revision.children")
    assert next_token["revision"] == 2 and len(calls) == 2


def test_load_failure_retains_display_then_same_revision_retry_recovers(raw):
    fail = [False]

    def source(_day):
        if fail[0]:
            raise RuntimeError("Connector offline")
        return raw

    manager, calls, loader, renderer = callbacks(raw, source=source)
    good, _ = load(loader)
    assert render(renderer, good)[-1]["status"] == "rendered"
    manager.health.revision = 2
    fail[0] = True
    failed, status = load(loader, 2)
    assert failed is no_update
    assert "Connector offline" in str(status)
    # A failed refresh keeps last-good rows clickable instead of replacing
    # their token with an error that rejects every subsequent click.
    result = render(renderer, good, opened=[], trigger="stock-pivot-open-paths.data", request="refresh-2")
    assert result[0] is not no_update
    fail[0] = False
    recovered, _ = load(loader, 2)
    assert render(renderer, recovered, request="refresh-2")[-1]["status"] == "rendered"
    assert len(calls) == 3


def test_clear_cache_reloads_current_stock_and_invalidates_history(raw):
    history = SimpleNamespace(cleared=0)
    history.clear = lambda: setattr(history, "cleared", history.cleared + 1)
    _, calls, loader, _ = callbacks(raw, history=history)
    load(loader)
    load(loader, trigger="clear-cache-complete-store.modified_timestamp")
    assert len(calls) == 2 and history.cleared == 1


@pytest.mark.parametrize("old_error", [None, "Obsolete connector error"])
def test_render_does_not_restore_a_previous_revision_after_a_new_commit(raw, old_error):
    manager, _, loader, renderer = callbacks(raw)
    old, _ = load(loader)
    manager.health.revision = 2
    load(loader, 2)
    if old_error:
        old = {**old, "error": old_error}
    with pytest.raises(PreventUpdate):
        render(renderer, old)


def test_load_result_is_ignored_when_commit_advances_during_the_connector(raw):
    holder = {}

    def source(_day):
        holder["manager"].health.revision = 2
        return raw

    manager, _, loader, _ = callbacks(raw, source=source)
    holder["manager"] = manager
    assert load(loader) == (no_update, no_update)


def test_render_result_is_ignored_when_commit_advances_during_history(raw):
    holder = {}

    def history(_identity, _start, _end):
        holder["manager"].health.revision = 2
        return pd.DataFrame({"Stock Date": [pd.Timestamp("2026-09-10")], "Stock": [50.0], "dStock": [4.0]})

    manager, _, loader, renderer = callbacks(raw, history=history)
    holder["manager"] = manager
    token, _ = load(loader)
    with pytest.raises(PreventUpdate):
        render(renderer, token, selection={"column": "CRDS", "value": "000A"})


def test_history_failure_retains_last_chart_and_reports_failure_then_recovers(raw):
    fail = [True]

    def history(_identity, _start, _end):
        if fail[0]:
            raise RuntimeError("History offline")
        return pd.DataFrame({"Stock Date": [pd.Timestamp("2026-09-10")], "Stock": [50.0], "dStock": [4.0]})

    _, _, loader, renderer = callbacks(raw, history=history)
    token, _ = load(loader)
    result = render(renderer, token, selection={"column": "CRDS", "value": "000A"})
    assert result[7] is no_update
    assert result[-1]["status"] == "failed" and "History offline" in result[-1]["message"]
    fail[0] = False
    assert render(renderer, token, selection={"column": "CRDS", "value": "000A"})[-1]["status"] == "rendered"


def test_expanding_branches_and_raw_rows_do_not_query_history_again(raw):
    history_calls = []

    def history(identity, start, end):
        history_calls.append((identity, start, end))
        return pd.DataFrame({"Stock Date": [pd.Timestamp("2026-09-10")], "Stock": [50.0], "dStock": [4.0]})

    _, source_calls, loader, renderer = callbacks(raw, history=history)
    token, _ = load(loader)
    selection = {"column": "CRDS", "value": "000A"}
    render(renderer, token, selection=selection)
    tree_result = render(renderer, token, selection=selection, opened=[], trigger="stock-pivot-open-paths.data")
    raw_result = render(renderer, token, selection=selection, raw_open=True, trigger="stock-raw-panel.open")
    assert tree_result[7] is no_update and raw_result[7] is no_update
    assert len(raw_result[2]) == len(raw)
    assert len(source_calls) == len(history_calls) == 1


def test_one_identifier_click_updates_tree_and_history_when_both_stores_change(raw):
    history_calls = []

    def history(identity, _start, _end):
        history_calls.append(identity)
        return pd.DataFrame({"Stock Date": [pd.Timestamp("2026-09-10")], "Stock": [50.0], "dStock": [4.0]})

    _, _, loader, renderer = callbacks(raw, history=history)
    token, _ = load(loader)
    for value in ("000A", "000F"):
        # One promoted-row click emits both outputs in the same Dash transaction.
        result = render(renderer, token, opened=[], selection={"column": "CRDS", "value": value},
                        trigger=["stock-pivot-open-paths.data", "stock-history-selection.data"])
        assert result[0] is not no_update
        assert result[7] is not no_update and result[9] == {}
        assert value in result[10]
    assert history_calls == [{"CRDS": "000A"}, {"CRDS": "000F"}]


@pytest.mark.parametrize("identifier", ["CRDS", "CIDS"])
def test_history_uses_identifier_all_dates_and_current_observation_wins(raw, identifier):
    raw = raw.rename(columns={"CRDS": identifier})
    page = StockPageData(raw, pd.Timestamp("2026-09-11"))
    calls = []
    rows = pd.DataFrame({"Stock Date": pd.to_datetime(["2025-01-01", "2026-09-10", "2026-09-11"]),
                         "Stock": [10.0, 25.0, -999.0], "dStock": [3.0, 4.0, -999.0]})
    before = rows.copy(deep=True)

    def source(identity, start, end):
        calls.append((identity, start, end))
        return rows

    figure, status, style, title = stock_history_result(source, {"column": identifier, "value": "000A"},
                                                       page, "all", None, None)
    assert calls == [({identifier: "000A"}, None, page.current_date)]
    assert "3 available dates" in status and style == {} and "000A" in title
    stock = next(trace for trace in figure.data if trace.name == "Stock")
    change = next(trace for trace in figure.data if trace.name == "dStock")
    # Missing business days deliberately break the line; they do not become zero.
    assert pd.Series(stock.y).dropna().tolist() == [10.0, 25.0, 150.0]
    assert pd.Series(change.y).dropna().tolist() == [3.0, 4.0, 45_000.0]  # supplied change
    assert stock.connectgaps is False
    pd.testing.assert_frame_equal(rows, before)


def test_stock_picker_date_reaches_connector_without_main_risk_date_override(raw):
    _, calls, loader, _ = callbacks(raw)
    invoke(loader, 1, 1, None, "2026-08-04", None, trigger="stock-input-date.date")
    assert calls == [pd.Timestamp("2026-08-04")]
    invoke(loader, 1, 1, None, "2026-08-05", None, trigger="stock-input-date.date")
    assert calls[-1] == pd.Timestamp("2026-08-05")
