"""PL disclosure laziness and application-factory boundary checks."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import Dash, dcc, html, no_update

from rebirth.history import (
    PL_RISK_SUMMARY_COLUMNS,
    PLHistorySeriesResult,
    PLRiskSummaryResult,
)
from rebirth.domain.s08_pnl import (
    COLOSSUS_TYPE,
    HISTORY_FILE_COLUMNS,
    PL_SEND_COLUMNS,
    PREDICT_TYPE,
    load_pl_history,
)
from rebirth.services.s03_adjustments import LocalCsvAdjustmentRepository
from rebirth.services.s05_sources import build_production_refresh_manager
from rebirth.pages.pnl import s08_aggregate as pl_aggregate_events
from rebirth.pages.pnl import s02_editor as pl_editor
from rebirth.pages.pnl import s09_drilldown as pl_history_events
from rebirth.pages.pnl import s05_sendcallbacks as pl_send_events
from rebirth.pages.pnl.s08_aggregate import register_pl_aggregate_callbacks
from rebirth.pages.pnl.s01_common import (
    DISPLAY_COLUMNS,
    PL_FILTER_EXCLUDE_ID,
    PL_FILTER_FIELDS,
    PL_FILTER_IDS,
    PL_FILTER_NOTE,
    PL_SAVED_VIEW_CONTROLS,
    PL_SUMMARY_HISTORY_CELL_TYPE,
    PL_SUMMARY_TOGGLE_TYPE,
    PLSendConfig,
)
from rebirth.pages.pnl.s06_validation import register_validate_pl_callbacks
from rebirth.pages.pnl.s07_view import (
    build_pl_filter_bar,
    build_pl_page,
    build_pl_send_sections,
)
from rebirth.pages.pnl.s10_summary import (
    PL_SUMMARY_LEAF_PAGE_SIZE,
    PL_SUMMARY_PAGE_TYPE,
    build_pl_summary_table,
    path_token,
)
from rebirth.ui.s02_aggregation import prepare_risk_data
from rebirth.app.s07_factory import build_app
from rebirth.ui.s03_filters import build_saved_filter_view_bar


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


def _text(component: object) -> str:
    if component is None:
        return ""
    if isinstance(component, (str, int, float)):
        return str(component)
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        return "".join(_text(child) for child in children)
    return _text(children)


def _history_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["2026-07-18", "IR", "Delta", "EUR", "XVA", "BOOK-A", 10.0],
            ["2026-07-19", "IR", "Delta", "EUR", "XVA", "BOOK-A", 12.0],
            ["2026-07-19", "FX", "Delta", "EUR/USD", "XVA", "BOOK-A", -3.0],
            ["2026-07-19", "IR", "Delta", "EUR", "XVA", "BOOK-B", 7.0],
        ],
        columns=["Market Date", *HISTORY_FILE_COLUMNS],
    )


def _committed(
    filter_values: list[list[str]] | None = None,
    *,
    exclude_selected: bool = False,
) -> dict[str, object]:
    values = filter_values or [[] for _field in PL_FILTER_FIELDS]
    return {
        "scope": "pnl",
        "view_id": "__base__",
        "filters": {
            field.key: list(selected)
            for field, selected in zip(PL_FILTER_FIELDS, values, strict=True)
        },
        "exclude_selected": exclude_selected,
    }


def _config(tmp_path: Path) -> PLSendConfig:
    history_source = tmp_path / "histo"
    for market_date, daily in _history_frame().groupby("Market Date", sort=True):
        leaf = history_source / str(market_date)
        leaf.mkdir(parents=True)
        actual = daily[list(HISTORY_FILE_COLUMNS)]
        predicted = actual.copy()
        predicted["PL"] = predicted["PL"] * 0.9
        actual.to_csv(leaf / "histo.csv", index=False)
        predicted.to_csv(leaf / "predicted.csv", index=False)
    return PLSendConfig(
        mapping_source=tmp_path / "mapping.csv",
        adjustment_repository=LocalCsvAdjustmentRepository(tmp_path / "adjustments"),
        send_sog_pl=lambda _frame: None,
        send_portfolio_pl=lambda _frame: None,
        history_source=history_source,
    )


def _registered_pl_app(
    tmp_path: Path,
    *,
    config: PLSendConfig | None = None,
) -> tuple[Dash, SimpleNamespace]:
    snapshot = SimpleNamespace(revision=7, market_date=pd.Timestamp("2026-07-20"))
    manager = SimpleNamespace(pl_snapshot=snapshot)
    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id="data-revision-store", data=7),
            dcc.Store(id="clear-cache-complete-store"),
            dcc.Store(id="pl-adjustment-revision-store", data=0),
            dcc.Store(id=PL_SAVED_VIEW_CONTROLS.committed_state_id),
            dcc.Store(id="pl-history-selection-store", data={}),
            build_pl_filter_bar(),
            *build_pl_send_sections(),
        ]
    )
    effective_config = config or _config(tmp_path)
    pl_history_events.register_pl_history_callbacks(app, effective_config)
    pl_send_events.register_pl_send_callbacks(app, manager, effective_config)
    return app, manager


def _callback(app: Dash, output_fragment: str):
    key = next(key for key in app.callback_map if output_fragment in key)
    return app.callback_map[key]["callback"].__wrapped__


def _callback_metadata(app: Dash, output_fragment: str) -> dict[str, object]:
    key = next(key for key in app.callback_map if output_fragment in key)
    return app.callback_map[key]


def _native_page(app: Dash, pathname: str = "/"):
    """Materialize one Dash Pages route through its registered router."""
    routes_prefix = app.config.routes_pathname_prefix
    layout_path = f"{routes_prefix}_dash-layout"
    response = app.server.test_client().get(layout_path)
    assert response.status_code == 200

    route = _callback(app, "_pages_content.children")
    with app.server.test_request_context(layout_path):
        page, _metadata = route(app.get_relative_path(pathname), "")
    return page


def _string_ids(component: object) -> set[str]:
    return {
        component_id
        for item in _walk(component)
        if isinstance((component_id := getattr(item, "id", None)), str)
    }


def _effective_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Market Date": "2026-07-20",
                "Risk Type": "IR",
                "Risk Greek": "Delta",
                "Portfolio": "BOOK-B",
                "SignoffGroup": "SOG-B",
                "ConcertoField": "irdeltaeffect",
                "PL": 20.0,
                "Adjustment": False,
            },
            {
                "Market Date": "2026-07-20",
                "Risk Type": "FX",
                "Risk Greek": "Delta",
                "Portfolio": "BOOK-A",
                "SignoffGroup": "SOG-A",
                "ConcertoField": "fxdeltaeffect",
                "PL": -5.0,
                "Adjustment": True,
            },
        ]
    )


def test_closed_pl_sections_never_build_or_serialize_effective_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _manager = _registered_pl_app(tmp_path)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("closed PL disclosure performed row work")

    monkeypatch.setattr(pl_send_events, "_effective_rows", forbidden)
    monkeypatch.setattr(pl_send_events, "_effective_store", forbidden)
    monkeypatch.setattr(pl_editor, "_display_records", forbidden)

    callback = _callback(app, "pl-send-effective-query-store.data")
    result = callback(
        0,
        0,
        7,
        [],
        [],
        0,
        0,
        0,
        None,
        None,
        None,
    )
    assert result == ({}, no_update, no_update, no_update, no_update)
    result = callback(
        2,
        2,
        8,
        ["include"],
        ["include"],
        1,
        1,
        1,
        None,
        "stale",
        "stale",
    )
    assert result == ({}, no_update, no_update, no_update, no_update)


def test_open_pl_sections_load_on_odd_parity_and_initialize_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app, _manager = _registered_pl_app(tmp_path)
    effective = pd.concat([_effective_frame()] * 3_346, ignore_index=True).iloc[:6_691]
    calls: list[bool] = []

    def effective_rows(
        _snapshot,
        _config,
        *,
        include_adjustments: bool,
        filter_values,
        exclude_value,
    ):
        calls.append(include_adjustments)
        assert filter_values == [[]] * len(PL_FILTER_FIELDS)
        assert exclude_value == []
        governance = effective[["Portfolio"]].drop_duplicates()
        return effective.copy(deep=True), pd.DataFrame(), governance

    monkeypatch.setattr(pl_send_events, "_effective_rows", effective_rows)
    callback = _callback(app, "pl-send-effective-query-store.data")
    query, sog_options, selected_sog, portfolio_options, selected_portfolio = callback(
        1,
        1,
        7,
        [],
        [],
        0,
        4,
        5,
        None,
        None,
        "BOOK-B",
    )
    assert [option["value"] for option in sog_options] == ["SOG-A", "SOG-B"]
    assert selected_sog == "SOG-A"
    assert [option["value"] for option in portfolio_options] == [
        "BOOK-A",
        "BOOK-B",
    ]
    assert selected_portfolio == "BOOK-B"
    assert "rows" not in query
    assert len(json.dumps(query)) < 2_048
    assert query["sections"]["sog"] == {
        "open": True,
        "include_adjustments": False,
        "editor_epoch": 4,
    }
    assert query["sections"]["portfolio"] == {
        "open": True,
        "include_adjustments": False,
        "editor_epoch": 5,
    }
    assert calls == [False]

    callback(
        1,
        1,
        7,
        [],
        ["include"],
        0,
        4,
        5,
        None,
        selected_sog,
        selected_portfolio,
    )
    assert calls == [False, True]


def test_pl_sections_are_independent_top_level_disclosures() -> None:
    sections = build_pl_send_sections()
    details = [section for section in sections if isinstance(section, html.Details)]

    assert getattr(sections[0], "id", None) == "pl-workflow-state"
    assert getattr(sections[1], "id", None) == "pl-send-all-panel"
    assert (
        next(
            item
            for item in _walk(sections[1])
            if getattr(item, "id", None) == "send-all-pl-button"
        ).children
        == "Send All P&L"
    )
    assert getattr(sections[2], "id", None) is None
    assert (
        next(
            item for item in _walk(sections[2]) if isinstance(item, html.Summary)
        ).children
        == "SOG P&L"
    )
    assert [
        next(item for item in _walk(detail) if isinstance(item, html.Summary)).children
        for detail in details
    ] == [
        "SOG P&L",
        "Portfolio P&L",
    ]
    assert all(
        [item for item in _walk(detail) if isinstance(item, html.Details)] == [detail]
        for detail in details
    )
    assert "pl-workflow-summary" not in _string_ids(html.Div(sections))
    explorer = next(
        item
        for item in _walk(html.Div(sections))
        if getattr(item, "id", None) == "pnl-explorer"
    )
    assert [
        item.children for item in _walk(explorer) if isinstance(item, html.Summary)
    ] == ["Validate P&L"]
    explorer_ids = _string_ids(explorer)
    assert set(PL_FILTER_IDS.values()).isdisjoint(explorer_ids)
    assert PL_FILTER_EXCLUDE_ID not in explorer_ids
    assert not any("preview" in component_id for component_id in explorer_ids)


def test_native_pl_page_owns_workflow_and_adjustment_state() -> None:
    page = build_pl_page(
        saved_view_bar=build_saved_filter_view_bar(
            PL_SAVED_VIEW_CONTROLS,
            filter_note=PL_FILTER_NOTE,
            filter_bar=build_pl_filter_bar(),
        )
    )
    ids = _string_ids(page)

    assert getattr(page, "id", None) == "pnl-page-container"
    assert {
        "pnl-page",
        "pnl-summary-open-paths",
        "pnl-aggregate-pl-grid",
        "pnl-filter-bar",
        "pnl-filter-exclude-selected",
        "pl-adjustment-revision-store",
        "pl-workflow-state",
        "pl-send-all-panel",
        "send-all-pl-button",
        "pl-send-all-status",
        "pnl-explorer",
        "pl-sog-summary",
        "pl-portfolio-summary",
        "pl-validate-summary",
        "pnl-current-workspace",
        "pnl-history-workspace",
        "pl-history-selection-store",
        "pl-history-period",
        "pl-history-series-selector",
        "pl-history-date-range",
        "pl-history-chart",
        "pl-history-plot-status",
    } <= ids
    mounted_filter_ids = [
        getattr(item, "id", None)
        for item in _walk(page)
        if getattr(item, "id", None) in set(PL_FILTER_IDS.values())
    ]
    assert mounted_filter_ids == [
        PL_FILTER_IDS[field.key] for field in PL_FILTER_FIELDS
    ]
    assert PL_FILTER_EXCLUDE_ID in ids
    assert "save-pl-button" not in ids
    assert "save-pl-download" not in ids
    assert "save-pl-status" not in ids
    assert "pl-preview-summary" not in ids

    filters = [
        item.id
        for item in _walk(page)
        if isinstance(item, dcc.Dropdown) and item.id in set(PL_FILTER_IDS.values())
    ]
    assert filters == [PL_FILTER_IDS[field.key] for field in PL_FILTER_FIELDS]
    filter_row = next(
        item
        for item in _walk(page)
        if isinstance(item, html.Div)
        and "pnl-filter-controls" in set(str(getattr(item, "className", "")).split())
    )
    assert filter_row.children[-1].id == "pnl-filter-exclude-selected"
    assert "filter-mode-control" in str(filter_row.children[-1].className).split()
    saved_view_bar = next(
        item
        for item in _walk(page)
        if isinstance(item, html.Details)
        and getattr(item, "id", None) == "pnl-saved-view-bar"
    )
    saved_view_notes = [
        item
        for item in _walk(saved_view_bar)
        if isinstance(item, html.Div)
        and "saved-view-filter-note" in set(str(getattr(item, "className", "")).split())
    ]
    assert len(saved_view_notes) == 1
    assert "P&L selections remain independent" in saved_view_notes[0].children
    assert set(PL_FILTER_IDS.values()) <= _string_ids(saved_view_bar)
    assert PL_FILTER_EXCLUDE_ID in _string_ids(saved_view_bar)
    assert PL_SAVED_VIEW_CONTROLS.scope == "pnl"
    assert PL_SAVED_VIEW_CONTROLS.apply_request_id == "pnl-saved-view-apply-request"
    aggregate_heading = next(
        item
        for item in _walk(page)
        if isinstance(item, html.H2) and item.children == "Current and historical P&L"
    )
    assert not any(
        isinstance(item, html.Summary) and item.children == "Current and historical P&L"
        for item in _walk(page)
    )
    assert aggregate_heading is not None
    assert {
        "pnl-workspace-tabs",
        "pl-history-grid",
        "pl-history-open-paths",
        "pl-history-open-comparisons",
        "pl-history-observations-table",
        "pl-history-raw-table",
        "pl-history-raw-details",
    }.isdisjoint(ids)
    period = next(
        item
        for item in _walk(page)
        if isinstance(item, dcc.RadioItems) and item.id == "pl-history-period"
    )
    assert period.value == "1y"
    assert [option["value"] for option in period.options] == [
        "wtd",
        "mtd",
        "ytd",
        "1y",
        "all",
        "custom",
    ]
    series_selector = next(
        item
        for item in _walk(page)
        if isinstance(item, dcc.Dropdown) and item.id == "pl-history-series-selector"
    )
    assert series_selector.value == "both"
    assert [option["label"] for option in series_selector.options] == [
        "Both",
        COLOSSUS_TYPE,
        PREDICT_TYPE,
    ]
    custom_range = next(
        item
        for item in _walk(page)
        if getattr(item, "id", None) == "pl-history-custom-range-control"
    )
    assert custom_range.style == {"display": "none"}

    cold_page = build_pl_page(start_initial_load=True)
    assert "pnl-initial-load-trigger" in _string_ids(cold_page)


def test_one_filter_dependency_set_governs_every_pl_consumer(tmp_path: Path) -> None:
    app, manager = _registered_pl_app(tmp_path)
    register_pl_aggregate_callbacks(app, manager)
    register_validate_pl_callbacks(app, tmp_path / "histo")
    committed = {(PL_SAVED_VIEW_CONTROLS.committed_state_id, "data")}
    draft = {(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS} | {
        (PL_FILTER_EXCLUDE_ID, "value")
    }

    for output_fragment in (
        "pnl-aggregate-pl-grid.children",
        "pl-send-effective-query-store.data",
        "pl-validate-table.children",
        "pl-history-chart.figure",
    ):
        metadata = _callback_metadata(app, output_fragment)
        dependencies = {(item["id"], item["property"]) for item in metadata["inputs"]}
        assert committed <= dependencies, output_fragment
        assert draft.isdisjoint(dependencies), output_fragment

    for output_fragment in (
        "pl-send-all-status.children",
        "pl-send-sog-status.children",
        "pl-send-portfolio-status.children",
        "pl-save-sog-adjustments-status.children",
    ):
        metadata = _callback_metadata(app, output_fragment)
        dependencies = {(item["id"], item["property"]) for item in metadata["state"]}
        assert committed <= dependencies, output_fragment
        assert draft.isdisjoint(dependencies), output_fragment


def test_send_all_builds_once_and_sends_independent_defensive_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[str, pd.DataFrame]] = []

    def send_sog(frame: pd.DataFrame) -> None:
        sent.append(("SOG", frame))
        frame.loc[:, "PL"] = 999.0

    def send_portfolio(frame: pd.DataFrame) -> None:
        sent.append(("Portfolio", frame))

    config = replace(
        _config(tmp_path),
        send_sog_pl=send_sog,
        send_portfolio_pl=send_portfolio,
    )
    app, _manager = _registered_pl_app(tmp_path, config=config)
    effective = _effective_frame()
    build_calls: list[bool] = []
    collapse_calls: list[int] = []

    def effective_rows(
        _snapshot,
        _config,
        *,
        include_adjustments: bool,
        filter_values,
        exclude_value,
    ):
        build_calls.append(include_adjustments)
        assert filter_values[2] == ["BOOK-A"]
        assert exclude_value == []
        return effective.copy(deep=True), pd.DataFrame(), pd.DataFrame()

    def collapse(rows, _mapping, _governance):
        collapse_calls.append(len(rows))
        return rows.copy(deep=True)

    monkeypatch.setattr(pl_send_events, "_effective_rows", effective_rows)
    monkeypatch.setattr(pl_send_events, "collapse_pl_send_rows", collapse)

    send_all = _callback(app, "pl-send-all-status.children")
    status = send_all(1, _committed([[], [], ["BOOK-A"], [], []]))

    assert status == "success · sent 2 governed rows to SOG and Portfolio"
    assert build_calls == [True]
    assert collapse_calls == [2]
    assert [label for label, _frame in sent] == ["SOG", "Portfolio"]
    assert sent[0][1] is not sent[1][1]
    assert list(sent[0][1].columns) == list(DISPLAY_COLUMNS)
    assert sent[1][1]["PL"].tolist() == [20.0, -5.0]
    assert effective["PL"].tolist() == [20.0, -5.0]

    callback_spec = next(
        item
        for item in app._callback_list
        if item["output"] == "pl-send-all-status.children"
    )
    assert callback_spec["running"] == {
        "running": {"send-all-pl-button.disabled": True},
        "runningOff": {"send-all-pl-button.disabled": False},
    }


def test_effective_rows_filters_base_and_adjustments_by_governed_portfolio(
    tmp_path: Path,
) -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    snapshot = manager.pl_snapshot
    empty_adjustments = pd.DataFrame(columns=list(PL_SEND_COLUMNS))
    empty_repository = SimpleNamespace(
        load=lambda _market_date: empty_adjustments.copy(deep=True)
    )
    config = PLSendConfig(
        mapping_source=Path("data/s08_concerto.csv"),
        adjustment_repository=empty_repository,
        send_sog_pl=lambda _frame: None,
        send_portfolio_pl=lambda _frame: None,
    )
    base, _mapping, governance = pl_editor._effective_rows(
        snapshot,
        config,
        include_adjustments=False,
    )
    portfolios = sorted(base["Portfolio"].astype(str).unique())
    assert len(portfolios) > 1
    selected_portfolio = portfolios[0]
    selected_base = base.loc[base["Portfolio"].eq(selected_portfolio)]
    adjustment = selected_base.iloc[[0]].copy(deep=True)
    adjustment["PL"] = 123456.0
    adjustment["Adjustment"] = True
    repository = SimpleNamespace(load=lambda _market_date: adjustment.copy(deep=True))
    config = replace(config, adjustment_repository=repository)
    selected_filters = [[], [], [selected_portfolio], [], []]

    included, _mapping, included_governance = pl_editor._effective_rows(
        snapshot,
        config,
        include_adjustments=True,
        filter_values=selected_filters,
        exclude_value=[],
    )
    assert set(included["Portfolio"]) == {selected_portfolio}
    assert set(included_governance["Portfolio"]) == {selected_portfolio}
    assert included.loc[included["Adjustment"].eq(True), "PL"].tolist() == [123456.0]

    excluded, _mapping, excluded_governance = pl_editor._effective_rows(
        snapshot,
        config,
        include_adjustments=True,
        filter_values=selected_filters,
        exclude_value=["exclude"],
    )
    assert selected_portfolio not in set(excluded["Portfolio"])
    assert selected_portfolio not in set(excluded_governance["Portfolio"])
    assert 123456.0 not in excluded["PL"].tolist()
    assert set(governance["Portfolio"]) >= set(included_governance["Portfolio"])


def test_send_all_reports_partial_failure_and_attempts_both_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def send_sog(_frame: pd.DataFrame) -> None:
        calls.append("SOG")
        raise RuntimeError("SOG unavailable")

    def send_portfolio(_frame: pd.DataFrame) -> None:
        calls.append("Portfolio")

    config = replace(
        _config(tmp_path),
        send_sog_pl=send_sog,
        send_portfolio_pl=send_portfolio,
    )
    app, _manager = _registered_pl_app(tmp_path, config=config)
    monkeypatch.setattr(
        pl_send_events,
        "_effective_rows",
        lambda _snapshot, _config, *, include_adjustments, filter_values, exclude_value: (
            _effective_frame(),
            pd.DataFrame(),
            pd.DataFrame(),
        ),
    )
    monkeypatch.setattr(
        pl_send_events,
        "collapse_pl_send_rows",
        lambda rows, _mapping, _governance: rows.copy(deep=True),
    )

    send_all = _callback(app, "pl-send-all-status.children")
    status = send_all(1, None)

    assert calls == ["SOG", "Portfolio"]
    assert (
        status == "Partially sent · Portfolio succeeded; SOG failed (SOG unavailable)"
    )

    def fail_build(*_args, **_kwargs):
        raise RuntimeError("mapping unavailable")

    monkeypatch.setattr(pl_send_events, "_effective_rows", fail_build)
    assert send_all(2, None) == (
        "Not sent: could not build governed P&L: mapping unavailable"
    )
    assert calls == ["SOG", "Portfolio"]


def _summary_result() -> PLRiskSummaryResult:
    rows = [
        [0, "TOTAL", (), False, 15.0, 110.0, 1010.0],
        [1, "IR", ("IR",), False, 15.0, 110.0, 1010.0],
        [2, "Delta", ("IR", "Delta"), False, 15.0, 110.0, 1010.0],
        [3, "EUR", ("IR", "Delta", "EUR"), True, 15.0, 110.0, 1010.0],
    ]
    return PLRiskSummaryResult(
        pd.DataFrame(rows, columns=list(PL_RISK_SUMMARY_COLUMNS)),
        "2026-07-19",
        len(rows),
    )


def test_pl_summary_table_is_page_owned_three_level_chevron() -> None:
    result = _summary_result()
    table = build_pl_summary_table(
        result.summary,
        [path_token(("IR",)), path_token(("IR", "Delta"))],
        as_of_date=result.as_of_date,
    )
    pattern_ids = [
        component_id
        for item in _walk(table)
        if isinstance((component_id := getattr(item, "id", None)), dict)
    ]
    toggles = [item for item in pattern_ids if item["type"] == PL_SUMMARY_TOGGLE_TYPE]
    history_cells = [
        item for item in pattern_ids if item["type"] == PL_SUMMARY_HISTORY_CELL_TYPE
    ]

    assert {item["path"] for item in toggles} == {
        path_token(("IR",)),
        path_token(("IR", "Delta")),
    }
    assert len(history_cells) == 12
    assert {item["metric"] for item in history_cells} == {
        "Current P&L",
        "Month to Date",
        "Year to Date",
    }
    assert {
        (item["risk_type"], item["risk_greek"], item["underlying"])
        for item in history_cells
    } == {
        ("", "", ""),
        ("IR", "", ""),
        ("IR", "Delta", ""),
        ("IR", "Delta", "EUR"),
    }
    assert "Risk Type › Greek › Underlying" in _text(table)
    assert "Month to date" in _text(table)
    assert "Year to date" in _text(table)


def test_pl_summary_underlyings_are_bounded_and_pageable() -> None:
    rows = [
        [0, "TOTAL", (), False, 1.0, 2.0, 3.0],
        [1, "FX", ("FX",), False, 1.0, 2.0, 3.0],
        [2, "Delta", ("FX", "Delta"), False, 1.0, 2.0, 3.0],
        *[
            [
                3,
                f"U{index:03d}",
                ("FX", "Delta", f"U{index:03d}"),
                True,
                float(index),
                float(index),
                float(index),
            ]
            for index in range(250)
        ],
    ]
    summary = pd.DataFrame(rows, columns=list(PL_RISK_SUMMARY_COLUMNS))
    opened = [path_token(("FX",)), path_token(("FX", "Delta"))]

    first = build_pl_summary_table(summary, opened)
    first_ids = [
        component_id
        for item in _walk(first)
        if isinstance((component_id := getattr(item, "id", None)), dict)
    ]
    first_cells = [
        item for item in first_ids if item["type"] == PL_SUMMARY_HISTORY_CELL_TYPE
    ]
    pages = [item for item in first_ids if item["type"] == PL_SUMMARY_PAGE_TYPE]

    assert len(first_cells) == (PL_SUMMARY_LEAF_PAGE_SIZE + 3) * 3
    leaf_cells = [item for item in first_cells if item["underlying"]]
    assert {item["underlying"] for item in leaf_cells} == {
        f"U{index:03d}" for index in range(PL_SUMMARY_LEAF_PAGE_SIZE)
    }
    assert {item["page"] for item in pages} == {0, 1}
    assert f"1–{PL_SUMMARY_LEAF_PAGE_SIZE} of 250" in _text(first)
    assert len(list(_walk(first))) < 1_200

    second = build_pl_summary_table(
        summary,
        opened,
        page_by_parent={path_token(("FX", "Delta")): 1},
    )
    second_ids = [
        component_id
        for item in _walk(second)
        if isinstance((component_id := getattr(item, "id", None)), dict)
    ]
    second_cells = [
        item for item in second_ids if item["type"] == PL_SUMMARY_HISTORY_CELL_TYPE
    ]
    assert {item["underlying"] for item in second_cells if item["underlying"]} == {
        f"U{index:03d}"
        for index in range(
            PL_SUMMARY_LEAF_PAGE_SIZE,
            PL_SUMMARY_LEAF_PAGE_SIZE * 2,
        )
    }
    assert (
        f"{PL_SUMMARY_LEAF_PAGE_SIZE + 1}–{PL_SUMMARY_LEAF_PAGE_SIZE * 2} of 250"
        in _text(second)
    )


def test_pl_summary_callback_uses_history_and_governed_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SummarySource:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def clear(self) -> None:
            pass

        def risk_summary(self, **kwargs) -> PLRiskSummaryResult:
            self.calls.append(kwargs)
            return _summary_result()

    source = SummarySource()
    manager = SimpleNamespace(health=SimpleNamespace(revision=0))
    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id="data-revision-store"),
            dcc.Store(id="clear-cache-complete-store"),
            dcc.Store(id="pnl-summary-open-paths", data=[]),
            dcc.Store(id="pl-history-selection-store", data={}),
            dcc.Store(id=PL_SAVED_VIEW_CONTROLS.committed_state_id),
            build_pl_filter_bar(),
            html.Div(id="pnl-aggregate-pl-grid"),
        ]
    )
    register_pl_aggregate_callbacks(app, manager, history_source=source)
    aggregate = _callback(app, "pnl-aggregate-pl-grid.children")
    monkeypatch.setattr(pl_aggregate_events, "ctx", SimpleNamespace(triggered_id=None))

    open_state, table = aggregate(
        7,
        [],
        [],
        _committed(
            [["XVA"], ["SOG-A"], ["BOOK-A"], ["Rates"], ["Vanilla"]],
            exclude_selected=True,
        ),
        None,
        [],
    )

    assert open_state is no_update
    assert "Today" in _text(table)
    assert source.calls == [
        {
            "filters": {
                "Activity": ["XVA"],
                "SignoffGroup": ["SOG-A"],
                "Portfolio": ["BOOK-A"],
                "Category": ["Rates"],
                "Sub Category": ["Vanilla"],
            },
            "exclude_selected": True,
        }
    ]
    metadata = _callback_metadata(app, "pnl-aggregate-pl-grid.children")
    assert any(PL_SUMMARY_TOGGLE_TYPE in item["id"] for item in metadata["inputs"])
    assert any(PL_SUMMARY_PAGE_TYPE in item["id"] for item in metadata["inputs"])
    dependencies = {(item["id"], item["property"]) for item in metadata["inputs"]}
    assert (PL_SAVED_VIEW_CONTROLS.committed_state_id, "data") in dependencies
    assert {
        (PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS
    }.isdisjoint(dependencies)


def test_pl_filter_owner_applies_pending_saved_view_after_coalesced_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)
    prepared = prepare_risk_data(manager.read_frame("dashboard_frame").frame)
    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id="data-revision-store", data=manager.health.revision),
            build_pl_page(
                initial_aggregate_frame=prepared,
                saved_view_bar=build_saved_filter_view_bar(
                    PL_SAVED_VIEW_CONTROLS,
                    filter_bar=build_pl_filter_bar(prepared),
                ),
            ),
        ]
    )
    register_pl_aggregate_callbacks(
        app,
        manager,
        prepared_frame_loader=lambda: prepared,
        saved_view_controls=PL_SAVED_VIEW_CONTROLS,
    )
    owner_key = next(
        key for key in app.callback_map if f"{PL_FILTER_IDS['activity']}.options" in key
    )
    owner_metadata = app.callback_map[owner_key]
    owner = owner_metadata["callback"].__wrapped__
    assert (
        PL_SAVED_VIEW_CONTROLS.applied_request_id,
        "data",
    ) in {(item["id"], item["property"]) for item in owner_metadata["state"]}
    activities = sorted(prepared["activity"].astype(str).unique())
    saved_activity, manual_activity = activities[:2]
    request = {
        "request_id": "a" * 32,
        "view_id": "saved-view",
        "scope": "pnl",
        "filters": {
            field.key: ([saved_activity] if field.key == "activity" else [])
            for field in PL_FILTER_FIELDS
        },
        "exclude_selected": True,
        "base_filters": {field.key: [] for field in PL_FILTER_FIELDS},
        "base_exclude_selected": False,
    }
    blank = [[] for _field in PL_FILTER_FIELDS]
    monkeypatch.setattr(
        pl_aggregate_events,
        "ctx",
        SimpleNamespace(triggered_id=PL_SAVED_VIEW_CONTROLS.apply_request_id),
    )
    applied = owner(manager.health.revision, request, *blank, [], None)
    assert applied[1] == [saved_activity]
    assert applied[-1] == ["exclude"]

    monkeypatch.setattr(
        pl_aggregate_events,
        "ctx",
        SimpleNamespace(triggered_id="data-revision-store"),
    )
    coalesced = owner(manager.health.revision + 1, request, *blank, [], None)
    assert coalesced[1] == [saved_activity]
    assert coalesced[-1] == ["exclude"]

    manual = [[] for _field in PL_FILTER_FIELDS]
    manual[0] = [manual_activity]
    refreshed = owner(manager.health.revision + 2, request, *manual, [], None)
    assert refreshed[1] == [manual_activity]
    assert refreshed[-1] == []

    acknowledged = owner(
        manager.health.revision + 3,
        request,
        *blank,
        [],
        request["request_id"],
    )
    assert acknowledged[1::2][:5] == ([], [], [], [], [])
    assert acknowledged[-1] == []


def test_clicking_aggregate_value_stores_complete_history_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SimpleNamespace(health=SimpleNamespace(revision=0))
    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id="data-revision-store"),
            dcc.Store(id="clear-cache-complete-store"),
            dcc.Store(id="pnl-summary-open-paths", data=[]),
            dcc.Store(id="pl-history-selection-store", data={}),
            build_pl_filter_bar(),
            html.Div(id="pnl-aggregate-pl-grid"),
        ]
    )
    register_pl_aggregate_callbacks(
        app,
        manager,
        prepared_frame_loader=lambda: pd.DataFrame(),
    )
    select_cell = _callback(app, "pl-history-selection-store.data")

    monkeypatch.setattr(
        pl_aggregate_events,
        "ctx",
        SimpleNamespace(triggered_id=None),
    )
    assert select_cell([0, None]) is no_update

    cell_id = {
        "type": PL_SUMMARY_HISTORY_CELL_TYPE,
        "risk_type": "IR",
        "risk_greek": "Delta",
        "underlying": "EUR",
        "metric": "Year to Date",
    }
    monkeypatch.setattr(
        pl_aggregate_events,
        "ctx",
        SimpleNamespace(triggered_id=cell_id),
    )
    assert select_cell([0, 2]) == {
        "risk_type": "IR",
        "risk_greek": "Delta",
        "underlying": "EUR",
    }

    total_id = {
        "type": PL_SUMMARY_HISTORY_CELL_TYPE,
        "risk_type": "",
        "risk_greek": "",
        "underlying": "",
        "metric": "Current P&L",
    }
    monkeypatch.setattr(
        pl_aggregate_events,
        "ctx",
        SimpleNamespace(triggered_id=total_id),
    )
    assert select_cell([3]) == {
        "risk_type": "",
        "risk_greek": "",
        "underlying": "",
    }

    metadata = _callback_metadata(app, "pl-history-selection-store.data")
    pattern_id = metadata["inputs"][0]["id"]
    assert metadata["inputs"][0]["property"] == "n_clicks"
    assert PL_SUMMARY_HISTORY_CELL_TYPE in pattern_id
    assert all(
        f'"{key}"' in pattern_id
        for key in ("risk_type", "risk_greek", "underlying", "metric")
    )


def test_inline_histo_is_lazy_and_reuses_canonical_history_function(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_config = _config(tmp_path)
    expected = load_pl_history(file_config.history_source)
    calls = 0

    def history_source() -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return expected.copy(deep=True)

    app, _manager = _registered_pl_app(
        tmp_path,
        config=replace(file_config, history_source=history_source),
    )
    chart = _callback(app, "pl-history-chart.figure")
    monkeypatch.setattr(
        pl_history_events,
        "ctx",
        SimpleNamespace(triggered_id="pl-history-selection-store"),
    )

    empty_figure, empty_status, empty_label, empty_style = chart(
        {},
        "both",
        "all",
        None,
        None,
        None,
        None,
    )
    assert calls == 0
    assert not empty_figure.data
    assert empty_status == "History loads only after a P&L value is selected."
    assert empty_label == "No P&L value selected."
    assert empty_style == {"display": "none"}

    selection = {
        "risk_type": "IR",
        "risk_greek": "Delta",
        "underlying": "EUR",
    }
    both_figure, both_status, label, visible_style = chart(
        selection,
        "both",
        "all",
        None,
        None,
        None,
        None,
    )
    assert calls == 1
    assert [trace.name for trace in both_figure.data] == [
        COLOSSUS_TYPE,
        PREDICT_TYPE,
    ]
    assert [list(trace.x) for trace in both_figure.data] == [
        ["2026-07-18", "2026-07-19"],
        ["2026-07-18", "2026-07-19"],
    ]
    assert [list(trace.y) for trace in both_figure.data] == [
        [10.0, 19.0],
        [9.0, pytest.approx(17.1)],
    ]
    assert "4 observed points" in both_status
    assert label == "IR · Delta · EUR"
    assert visible_style == {}

    colossus_figure, _status, _label, _style = chart(
        selection,
        "colossus",
        "wtd",
        None,
        None,
        None,
        None,
    )
    assert calls == 1
    assert [trace.name for trace in colossus_figure.data] == [COLOSSUS_TYPE]

    monkeypatch.setattr(
        pl_history_events,
        "ctx",
        SimpleNamespace(triggered_id="clear-cache-complete-store"),
    )
    chart(
        selection,
        "predict",
        "all",
        None,
        None,
        None,
        {"generation": 2},
    )
    assert calls == 2


def test_inline_histo_bounded_query_combines_filters_and_positive_cell_criteria(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_config = _config(tmp_path)

    class BoundedHistory:
        def __init__(self) -> None:
            self.series_calls: list[dict[str, object]] = []
            self.clear_calls = 0

        def clear(self) -> None:
            self.clear_calls += 1

        def hierarchy(self, **_kwargs):
            raise AssertionError("inline history must not run a hierarchy query")

        def series(self, **kwargs) -> PLHistorySeriesResult:
            self.series_calls.append(kwargs)
            history_types = tuple(kwargs["history_types"])
            rows = pd.DataFrame(
                [
                    {
                        "Market Date": "2026-07-18",
                        "P&L Type": COLOSSUS_TYPE,
                        "PL": 10.0,
                    },
                    {
                        "Market Date": "2026-07-19",
                        "P&L Type": PREDICT_TYPE,
                        "PL": 9.0,
                    },
                ]
            )
            rows = rows.loc[rows["P&L Type"].isin(history_types)].reset_index(drop=True)
            return PLHistorySeriesResult(
                rows,
                "2026-07-18",
                "2026-07-19",
                "2026-07-18",
                "2026-07-19",
            )

    source = BoundedHistory()
    app, _manager = _registered_pl_app(
        tmp_path,
        config=replace(file_config, history_source=source),
    )
    chart = _callback(app, "pl-history-chart.figure")
    monkeypatch.setattr(
        pl_history_events,
        "load_pl_history",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("bounded history fell back to a full archive load")
        ),
    )
    monkeypatch.setattr(
        pl_history_events,
        "ctx",
        SimpleNamespace(triggered_id="pl-history-period"),
    )

    selection = {
        "risk_type": "IR",
        "risk_greek": "Delta",
        "underlying": "EUR",
    }
    figure, status, label, style = chart(
        selection,
        "predict",
        "custom",
        "2026-07-18",
        "2026-07-19",
        _committed(
            [["XVA"], ["SOG-A"], ["BOOK-A"], ["Rates"], ["Vanilla"]],
            exclude_selected=True,
        ),
        None,
    )

    assert [trace.name for trace in figure.data] == [PREDICT_TYPE]
    assert "1 observed points" in status
    assert label == "IR · Delta · EUR"
    assert style == {}
    assert source.series_calls == [
        {
            "path": (),
            "history_types": (PREDICT_TYPE,),
            "preset": "custom",
            "start_date": "2026-07-18",
            "end_date": "2026-07-19",
            "filters": {
                "Activity": ["XVA"],
                "SignoffGroup": ["SOG-A"],
                "Portfolio": ["BOOK-A"],
                "Category": ["Rates"],
                "Sub Category": ["Vanilla"],
            },
            "criteria": {
                "Risk Type": ["IR"],
                "Risk Greek": ["Delta"],
                "Underlying": ["EUR"],
            },
            "exclude_selected": True,
        }
    ]

    chart(
        {"risk_type": "IR", "risk_greek": "", "underlying": ""},
        "both",
        "all",
        None,
        None,
        None,
        None,
    )
    assert source.series_calls[-1]["criteria"] == {"Risk Type": ["IR"]}

    monkeypatch.setattr(
        pl_history_events,
        "ctx",
        SimpleNamespace(triggered_id="clear-cache-complete-store"),
    )
    chart(
        {},
        "both",
        "1y",
        None,
        None,
        None,
        {"generation": 3},
    )
    assert source.clear_calls == 1
    assert len(source.series_calls) == 2


def test_inline_histo_callback_metadata_has_no_tree_or_raw_contract(
    tmp_path: Path,
) -> None:
    app, _manager = _registered_pl_app(tmp_path)
    chart = _callback_metadata(app, "pl-history-chart.figure")
    assert [str(output) for output in chart["output"]] == [
        "pl-history-chart.figure",
        "pl-history-plot-status.children",
        "pl-history-selection-label.children",
        "pnl-history-workspace.style",
    ]
    assert {(item["id"], item["property"]) for item in chart["inputs"]} == {
        ("pl-history-selection-store", "data"),
        ("pl-history-series-selector", "value"),
        ("pl-history-period", "value"),
        ("pl-history-date-range", "start_date"),
        ("pl-history-date-range", "end_date"),
        (PL_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
        ("clear-cache-complete-store", "data"),
    }
    callback_contract = " ".join(app.callback_map)
    assert all(
        retired not in callback_contract
        for retired in (
            "pnl-workspace-tabs",
            "pl-history-grid",
            "pl-history-open-paths",
            "pl-history-open-comparisons",
            "pl-history-observations-table",
            "pl-history-raw-table",
        )
    )


def test_manager_app_without_pl_config_omits_inert_workflow(tmp_path: Path) -> None:
    manager = build_production_refresh_manager()
    manager.refresh(force_risk=True, force_pl=True)

    without_pl = build_app(refresh_manager=manager)
    without_page = _native_page(without_pl)
    without_ids = _string_ids(without_page)
    assert "pl-preview-summary" not in without_ids
    assert "pl-sog-summary" not in without_ids
    assert "pl-portfolio-summary" not in without_ids
    assert "pl-validate-summary" not in without_ids
    assert "pl-history-summary" not in without_ids
    assert "pl-adjustment-revision-store" not in without_ids
    assert not any("pl-send-preview" in key for key in without_pl.callback_map)
    without_pnl_page = _native_page(without_pl, "/pnl")
    without_pnl_ids = _string_ids(without_pnl_page)
    assert {
        "pnl-summary-open-paths",
        "pnl-aggregate-pl-grid",
        "pnl-unavailable",
    } <= without_pnl_ids
    assert any(
        "pnl-aggregate-pl-grid.children" in key for key in without_pl.callback_map
    )

    config = PLSendConfig(
        mapping_source=Path("data/s08_concerto.csv"),
        adjustment_repository=LocalCsvAdjustmentRepository(tmp_path / "adjustments"),
        send_sog_pl=lambda _frame: None,
        send_portfolio_pl=lambda _frame: None,
    )
    with_pl = build_app(refresh_manager=manager, pl_send_config=config)
    with_risk_page = _native_page(with_pl)
    with_risk_ids = _string_ids(with_risk_page)
    assert "pl-preview-summary" not in with_risk_ids
    assert "pl-adjustment-revision-store" not in with_risk_ids

    with_page = _native_page(with_pl, "/pnl")
    with_ids = _string_ids(with_page)
    assert {
        "pnl-explorer",
        "pl-sog-summary",
        "pl-portfolio-summary",
        "pl-validate-summary",
        "pnl-history-workspace",
        "pl-history-selection-store",
        "pl-history-chart",
        "pl-adjustment-revision-store",
    } <= with_ids
    assert {
        "pnl-workspace-tabs",
        "pl-history-grid",
        "pl-history-raw-table",
    }.isdisjoint(with_ids)
    assert "pl-preview-summary" not in with_ids
    assert "pl-workflow-summary" not in with_ids
    assert not any("pl-send-preview" in key for key in with_pl.callback_map)


def test_cold_native_pnl_is_safe_before_commit_without_history_source(
    tmp_path: Path,
) -> None:
    manager = build_production_refresh_manager()
    config = PLSendConfig(
        mapping_source=Path("data/s08_concerto.csv"),
        adjustment_repository=LocalCsvAdjustmentRepository(tmp_path / "adjustments"),
        send_sog_pl=lambda _frame: None,
        send_portfolio_pl=lambda _frame: None,
    )
    app = build_app(refresh_manager=manager, pl_send_config=config)
    page = _native_page(app, "/pnl")

    assert "pnl-initial-load-trigger" in _string_ids(page)
    assert manager.health.revision == 0
    aggregate = _callback(app, "pnl-aggregate-pl-grid.children")
    _open_state, aggregate_view = aggregate(
        0,
        [],
        [],
        None,
        None,
        [],
    )
    assert "not configured" in str(aggregate_view.children)
    effective_query = _callback(app, "pl-send-effective-query-store.data")
    result = effective_query(
        1,
        0,
        0,
        [],
        [],
        0,
        0,
        0,
        None,
        None,
        None,
    )
    assert result == ({}, [], None, no_update, no_update)

    manager.refresh(force_risk=True, force_pl=True)
    _open_state, aggregate_view = aggregate(
        manager.health.revision,
        [],
        [],
        None,
        None,
        [],
    )
    assert "not configured" in str(aggregate_view.children)
    assert not any("pl-send-preview" in key for key in app.callback_map)


def test_static_app_rejects_inert_pl_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="PL send configuration requires"):
        build_app(data=pd.DataFrame(), pl_send_config=_config(tmp_path))
