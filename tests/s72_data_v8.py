"""V8 Data search, cross-page scope and current-plus-archive regression tests."""
from datetime import date, datetime, timezone
from threading import RLock
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import Dash, dcc, html

from cube.domain.s10_search import ResolvedHistoryIdentity
from cube.history import ArchiveHistoryRepository, HistoryHandoff, HistoryIdentity, HistoryQuery, RiskFilterView, archive_official_snapshot
from cube.pages.data.s02_view import build_data_page
from cube.pages.data.s03_callbacks import register_callbacks, serialize_history_bundle
from cube.pages.data.s04_workspace import DataChoices, encode_choice, selection_for_handoff, workspace_request
from cube.services.s02_state import _RefreshStateMixin


def risk_rows():
    rows = []
    for raw, portfolio, amount in [("EUR", "BOOK-A", -1200.), ("USD", "BOOK-B", 2500.)]:
        rows.append({"Source Type": "ir/delta", "Risk Type": "IR", "Risk Greek": "Delta",
                     "Underlying": raw, "Reported Underlying": "Rates", "Portfolio": portfolio,
                     "Product": "XVA", "Activity": "A", "SignoffGroup": "SOG-A", "Category": "Core",
                     "Sub Category": "Rates", "Region": "EMEA", "Group": "Rates", "Split": "Risk",
                     "Tenor Swap": "1Y", "Tenor Option": "N/A", "Tenor Swap Order": 1,
                     "Tenor Option Order": pd.NA, "Risk": amount, "dRisk": amount / 10, "PL": 0.})
    return pd.DataFrame(rows)


def market_rows(day="2026-09-11", amount=5.):
    return pd.DataFrame([{"Source Type": "ir/delta", "Risk Type": "IR", "Risk Greek": "Delta", "Underlying": "EUR",
                         "Tenor Swap": "1Y", "Tenor Option": "N/A", "Tenor Swap Order": 1, "Tenor Option Order": pd.NA,
                         "Market Date": day, "Open": amount - 1, "Current": amount, "Move": 1.,
                         "Market Status": "OFFICIAL", "Market Data Status": "Available"}])


class Manager(_RefreshStateMixin):
    def __init__(self, day="2026-09-11", amount=5.):
        self._state_lock = RLock()
        self._snapshot = SimpleNamespace(revision=7, market_date=pd.Timestamp(day), dashboard_frame=risk_rows(),
                                        market_frame=market_rows(day, amount), risk_dates={"ir/delta": pd.Timestamp("2026-09-10")})

    @property
    def health(self): return SimpleNamespace(revision=7)

    def combine_udl_options(self): return ("IR | Delta | Rates",)
    def market_udl_options(self): return ("IR | Delta | EUR",)
    def data_history_identities(self): raise AssertionError("Never resolve the entire catalog to build labels")
    def resolve_history_identity(self, kind, label, identity_mode="reported"):
        return ResolvedHistoryIdentity(kind=kind, source_types=("ir/delta",), risk_type="IR", risk_greek="Delta",
            underlying="Rates" if kind == "risk" else "EUR", identity_mode=identity_mode,
            source_revision=7, snapshot_date=self._snapshot.market_date)


def handoff(kind="risk", scope=None):
    return HistoryHandoff(schema_version=1, kind=kind,
        identity=HistoryIdentity(("ir/delta",), "IR", "Delta", "Rates" if kind == "risk" else "EUR", "reported" if kind == "risk" else "underlying"),
        metric="risk" if kind == "risk" else "current", source_revision=7,
        snapshot_date=date(2026, 9, 11), filter_view=scope)


def archive_day(root, day, amount):
    snapshot = SimpleNamespace(revision=1, refreshed_at=datetime(2026, 9, 10, 22, tzinfo=timezone.utc),
        system_date=pd.Timestamp(day), market_date=pd.Timestamp(day), market_status="OFFICIAL", errors=(),
        dashboard_frame=risk_rows(), market_frame=market_rows(day, amount), risk_dates={"ir/delta": pd.Timestamp(day)})
    colossus = risk_rows()[["Portfolio", "Underlying", "Risk Type", "Risk Greek", "PL"]]
    archive_official_snapshot(snapshot, lambda _day: colossus, root)


def test_current_search_reads_only_label_catalog(tmp_path):
    choices = DataChoices(Manager(), ArchiveHistoryRepository(tmp_path))
    choices.repository.catalog = lambda: (_ for _ in ()).throw(AssertionError("Archive must load independently"))
    assert choices.metadata()["risk"] == ["IR | Delta | Rates"]
    assert choices.resolve(encode_choice("risk", "IR | Delta | Rates")).identity.underlying == "Rates"


def test_reported_selection_keeps_scope_and_separate_raw_quotes(tmp_path):
    selection = selection_for_handoff(handoff(), Manager(), ArchiveHistoryRepository(tmp_path))
    assert selection["risk"]["identity"]["identity_mode"] == "reported"
    assert {item["identity"]["underlying"] for item in selection["markets"]} == {"EUR", "USD"}
    assert all(item["filter_view"] is None for item in selection["markets"])
    scoped = handoff(scope=RiskFilterView(filters=(("Portfolio", ("BOOK-A",)),)))
    narrowed = selection_for_handoff(scoped, Manager(), ArchiveHistoryRepository(tmp_path))
    assert len(narrowed["markets"]) == 1
    assert narrowed["risk"]["filter_view"] == scoped.filter_view.to_mapping()


def test_excluded_risk_scope_does_not_reach_market_quotes(tmp_path):
    scoped = handoff(scope=RiskFilterView(filters=(("Portfolio", ("BOOK-A",)),), exclude_selected=True))
    selection = selection_for_handoff(scoped, Manager(), ArchiveHistoryRepository(tmp_path))
    assert selection["markets"][0]["identity"]["underlying"] == "USD"
    assert selection["markets"][0]["filter_view"] is None


def test_both_and_mode_switch_use_same_underlying_selection(tmp_path):
    selection = selection_for_handoff(handoff(), Manager(), ArchiveHistoryRepository(tmp_path))
    both = workspace_request(selection, "both", "1", "all", None, None, 0)
    assert set(both["handoffs"]) == {"risk", "market"}
    assert both["handoffs"]["market"]["identity"]["underlying"] == "USD"
    risk = workspace_request(selection, "risk", "1", "all", None, None, 0)
    assert risk["handoffs"]["risk"] == both["handoffs"]["risk"]


def test_market_selected_counterpart_is_raw_risk(tmp_path):
    selection = selection_for_handoff(handoff("market"), Manager(), ArchiveHistoryRepository(tmp_path))
    assert selection["risk"]["identity"]["identity_mode"] == "underlying"
    assert selection["risk"]["identity"]["underlying"] == "EUR"


def test_current_live_market_appends_today_and_replaces_same_day_archive(tmp_path):
    archive_day(tmp_path, "2026-09-10", 1.)
    archive_day(tmp_path, "2026-09-11", 2.)
    manager = Manager("2026-09-11", 5.)
    revision, current = manager.read_data_history(handoff("market"))
    bundle = ArchiveHistoryRepository(tmp_path).read(HistoryQuery(handoff("market")), current_rows=current, current_revision=revision)
    assert bundle.dates == (date(2026, 9, 10), date(2026, 9, 11))
    assert bundle.values["Current"].tolist() == [1., 5.]
    assert len(bundle.raw_rows) == 2
    assert serialize_history_bundle(bundle)["dates"][-1] == "2026-09-11"


def test_forced_market_date_stays_historical_and_risk_date_is_independent(tmp_path):
    archive_day(tmp_path, "2026-09-09", 1.)
    archive_day(tmp_path, "2026-09-11", 9.)
    manager = Manager("2026-09-10", 4.)
    revision, rows = manager.read_data_history(handoff("market"))
    bundle = ArchiveHistoryRepository(tmp_path).read(HistoryQuery(handoff("market")), current_rows=rows, current_revision=revision)
    assert bundle.dates[-1] == date(2026, 9, 10)
    assert bundle.values["Current"].tolist() == [1., 4.]
    manager = Manager("2026-09-11")
    _revision, risk = manager.read_data_history(handoff())
    assert set(risk["Risk Date"]) == {pd.Timestamp("2026-09-10")}


def test_cell_budget_rejects_before_cartesian_allocation(tmp_path, monkeypatch):
    import cube.history.s06_repository as repository_module
    manager = Manager()
    _revision, rows = manager.read_data_history(handoff("market"))
    duplicate = rows.iloc[0].copy()
    duplicate["Tenor Swap"], duplicate["Tenor Swap Order"] = "5Y", 2
    rows = pd.concat([rows, duplicate.to_frame().T], ignore_index=True)
    monkeypatch.setattr(repository_module, "_canonical_values", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Too early")))
    with pytest.raises(ValueError, match="would have 2 cells"):
        ArchiveHistoryRepository(tmp_path, max_cells=1).read(HistoryQuery(handoff("market")), current_rows=rows)


def test_filtered_current_scope_cleared_does_not_resurrect_same_day_archive(tmp_path):
    archive_day(tmp_path, "2026-09-09", 1.)
    archive_day(tmp_path, "2026-09-10", 2.)
    manager = Manager()
    manager._snapshot.dashboard_frame = risk_rows().query("Portfolio == 'BOOK-B'").copy()
    scoped = handoff(scope=RiskFilterView(filters=(("Portfolio", ("BOOK-A",)),)))
    revision, rows = manager.read_data_history(scoped)
    assert len(rows) == 1  # Unfiltered committed identity still proves today's authority.
    bundle = ArchiveHistoryRepository(tmp_path).read(HistoryQuery(scoped), current_rows=rows, current_revision=revision)
    assert bundle.raw_rows["Risk Date"].tolist() == ["2026-09-09"]
    today = bundle.values.loc[bundle.values["Risk Date"].eq("2026-09-10"), "Risk"]
    assert today.isna().all()  # Missing, not old risk or invented zero.


def test_empty_data_selection_still_receipts_refresh_and_failure_does_not_succeed(tmp_path, monkeypatch):
    app = Dash(__name__)
    register_callbacks(app, ArchiveHistoryRepository(tmp_path), Manager())
    metadata = next(item for key, item in app.callback_map.items() if "data-history-bundle-store.data" in key)
    callback = metadata["callback"].__wrapped__
    payload, _message = callback(None, 12, 0, {"id": "refresh-12"})
    assert payload["refresh"] == {"owner": "data-history", "revision": 12, "request_id": "refresh-12", "status": "rendered", "message": ""}
    assert payload["key"]
    failed, _message = callback({"error": "Bad dates", "display_mode": "risk"}, 12, 0, {"id": "refresh-12"})
    assert failed["refresh"]["status"] == "failed"
    assert failed["key"] != payload["key"]


@pytest.mark.parametrize("scoped,period,market_index", [(True, "mtd", "0"), (False, "custom", "1")])
def test_remount_empty_value_retains_scope_mode_period_and_raw_market(tmp_path, monkeypatch, scoped, period, market_index):
    import cube.pages.data.s03_callbacks as callbacks
    from dash import no_update
    manager, repository = Manager(), ArchiveHistoryRepository(tmp_path)
    selected_handoff = handoff(scope=RiskFilterView(filters=(("Portfolio", ("BOOK-A",)),)) if scoped else None)
    selection = selection_for_handoff(selected_handoff, manager, repository)
    selection["token"] = encode_choice("handoff", selected_handoff.to_mapping())
    saved = workspace_request(selection, "both", market_index, period,
                              "2026-09-01" if period == "custom" else None,
                              "2026-09-11" if period == "custom" else None, 0)
    saved["selection"] = selection
    app = Dash(__name__)
    register_callbacks(app, repository, manager)
    metadata = next(item for key, item in app.callback_map.items() if "data-selection-store.data" in key)
    callback = metadata["callback"].__wrapped__
    # Dash can emit an empty dropdown value while re-mounting the page, with
    # the previous local selection still sampled as State. This is not Clear.
    monkeypatch.setattr(callbacks, "ctx", SimpleNamespace(triggered_id="data-underlying"))
    result = callback(None, None, 0, selection, "risk", "consumed", saved)
    assert result[0]["risk"]["filter_view"] == selected_handoff.to_mapping()["filter_view"]
    assert result[1] == selection["token"]
    assert result[4] == market_index
    assert result[5] == "both"
    assert result[8:11] == (period, saved["start_date"], saved["end_date"])
    if scoped:
        assert "preserved" in result[7]
    followup = callback(result[1], None, 0, result[0], "both", "consumed", saved)
    assert followup == (no_update,) * 12


def test_layout_and_callbacks_use_one_search_without_old_catalog_or_picker(tmp_path):
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.layout = html.Div([dcc.Store(id="data-history-handoff-store"), dcc.Store(id="reset-generation-store", data=0),
        dcc.Store(id="refresh-action-request"), dcc.Store(id="refresh-view-data-history"),
        dcc.Interval(id="committed-revision-poll", interval=1000),
        dcc.Store(id="clear-cache-complete-store", data=0), html.Span("7", id="refresh-commit-revision"), build_data_page()])
    register_callbacks(app, ArchiveHistoryRepository(tmp_path), Manager())
    client = app.server.test_client()
    assert client.get("/_dash-layout").status_code == 200
    dependencies = client.get("/_dash-dependencies").json
    assert sum(item.get("clientside_function", {}).get("function_name") == "searchCurrent" for item in dependencies if item.get("clientside_function")) == 1
    initial_search = next(item for item in dependencies if (item.get("clientside_function") or {}).get("function_name") == "searchCurrent")
    assert "data-archive-choices" not in {item["id"] for item in initial_search["inputs"]}
    layout = client.get("/_dash-layout").text
    assert '"id":"data-underlying"' in layout
    assert "data-risk-type" not in layout and "data-history-projection" not in layout
    server_search_inputs = [item for item in dependencies if not item.get("clientside_function") and any(i["property"] == "search_value" for i in item["inputs"])]
    assert server_search_inputs == []


def test_chart_query_aggregates_large_position_history_before_browser_budget(tmp_path):
    frame = pd.concat([risk_rows()] * 6000, ignore_index=True)
    frame["Portfolio"] = [f"BOOK-{index}" for index in range(len(frame))]
    snapshot = SimpleNamespace(revision=1, refreshed_at=datetime(2026, 9, 10, 22, tzinfo=timezone.utc),
        system_date=pd.Timestamp("2026-09-10"), market_date=pd.Timestamp("2026-09-10"), market_status="OFFICIAL", errors=(),
        dashboard_frame=frame, market_frame=market_rows("2026-09-10"), risk_dates={"ir/delta": pd.Timestamp("2026-09-10")})
    archive_official_snapshot(snapshot, lambda _day: frame[["Portfolio", "Underlying", "Risk Type", "Risk Greek", "PL"]], tmp_path)
    repository = ArchiveHistoryRepository(tmp_path)
    chart = repository.read(HistoryQuery(handoff()), chart_only=True)
    assert chart.raw_rows.empty and len(chart.values) == 1
    assert chart.values["Risk"].tolist() == [frame["Risk"].sum()]
    with pytest.raises(ValueError, match="browser budget"):
        repository.read(HistoryQuery(handoff()))
    for exclude, expected in [(False, frame.iloc[0]["Risk"]), (True, frame["Risk"].sum() - frame.iloc[0]["Risk"])]:
        scoped = handoff(scope=RiskFilterView(filters=(("Portfolio", ("BOOK-0",)),), exclude_selected=exclude))
        assert repository.read(HistoryQuery(scoped), chart_only=True).values["Risk"].tolist() == [expected]
    # An archived-only selection discovers raw markets through DISTINCT keys,
    # without reading 12,000 contributors or building the playback grid.
    selection = selection_for_handoff(handoff(), None, repository)
    assert {item["identity"]["underlying"] for item in selection["markets"]} == {"EUR", "USD"}


def test_current_chart_aggregates_100k_rows_and_same_date_overwrites_archive(tmp_path):
    archive_day(tmp_path, "2026-09-10", 1.)
    manager = Manager()
    manager._snapshot.dashboard_frame = pd.concat([risk_rows()] * 50_001, ignore_index=True)
    revision, rows = manager.read_data_history(handoff())
    chart = ArchiveHistoryRepository(tmp_path).read(HistoryQuery(handoff()), current_rows=rows,
                                                   current_revision=revision, chart_only=True)
    assert len(chart.values) == 1 and chart.raw_rows.empty
    assert chart.values["Risk"].tolist() == [1300. * 50_001]


def test_rank_authority_is_per_dated_source_underlying(tmp_path):
    from cube.history.s06_repository import _chart_axis_order
    axis = handoff().identity.axes[0]
    frame = pd.DataFrame({"Source Type": ["ir/delta"] * 4, "Underlying": ["EUR"] * 4,
                          "Risk Date": ["2026-09-10"] * 2 + ["2026-09-11"] * 2,
                          "Tenor Swap": ["1Y", "5Y", "1Y", "5Y"], "Tenor Swap Order": [1, 2, 2, 3]})
    order = _chart_axis_order(frame, axis, "Risk Date")
    assert order.labels == ("1Y", "5Y")
    invalid = frame.copy()
    invalid["Risk Date"] = "2026-09-11"
    with pytest.raises(ValueError, match="within one dated"):
        _chart_axis_order(invalid, axis, "Risk Date")


def test_selection_and_its_option_arrive_together_and_empty_hydration_keeps_them(tmp_path, monkeypatch):
    import cube.pages.data.s03_callbacks as callbacks
    from dash import no_update
    app = Dash(__name__)
    register_callbacks(app, ArchiveHistoryRepository(tmp_path), Manager())
    callback = next(item["callback"].__wrapped__ for key, item in app.callback_map.items() if "data-selection-store.data" in key)
    monkeypatch.setattr(callbacks, "ctx", SimpleNamespace(triggered_id="data-underlying"))
    token = encode_choice("risk", "IR | Delta | Rates")
    result = callback(token, None, 0, None, "risk", None, None)
    assert result[11] == [result[2]] and result[11][0]["value"] == result[1] == token
    hydrated = callback(None, None, 0, result[0], "risk", None, None)
    assert hydrated[0]["token"] == token and hydrated[11][0]["value"] == token
    assert callback(token, None, 0, hydrated[0], "risk", None, None) == (no_update,) * 12


def test_full_year_market_surface_fits_but_cell_guard_still_precedes_grid(tmp_path, monkeypatch):
    from cube.history.s01_models import HISTORY_CANONICAL_CELL_BUDGET
    assert HISTORY_CANONICAL_CELL_BUDGET == 64_000
    identity = HistoryIdentity(("ir/deltavega",), "IR", "DeltaVega", "EUR", "underlying")
    selected = HistoryHandoff(schema_version=1, kind="market", identity=identity, metric="current",
                              source_revision=7, snapshot_date=date(2026, 9, 11))
    dates = pd.bdate_range(end="2026-09-11", periods=263)
    frame = pd.DataFrame([{"Source Type": "ir/deltavega", "Underlying": "EUR", "Market Date": day, "Snapshot Date": day,
                           "Tenor Swap": f"S{s}", "Tenor Swap Order": s,
                           "Tenor Option": f"O{o}", "Tenor Option Order": o, "Current": float(s-o)}
                          for day in dates for s in range(9) for o in range(7)])
    bundle = ArchiveHistoryRepository(tmp_path).read(HistoryQuery(selected), current_rows=frame, chart_only=True)
    assert len(bundle.values) == 16_569 and bundle.raw_rows.empty
    import cube.history.s06_repository as module
    monkeypatch.setattr(module, "_canonical_values", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Allocated too early")))
    with pytest.raises(ValueError, match="cell browser budget"):
        ArchiveHistoryRepository(tmp_path, max_cells=16_000).read(HistoryQuery(selected), current_rows=frame, chart_only=True)
