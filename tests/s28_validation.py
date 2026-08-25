"""Official historical Risk comparison and Validate P&L regressions."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import Dash, dcc, html
from dash.exceptions import PreventUpdate

from cube.history import archive_official_snapshot
from cube.domain.s08_pnl import HISTORY_MAPPING_STATUS
from cube.domain.s01_schema import UNMAPPED_VALUE
from cube.pages.pnl import s06_validation as validate_pl_module
from cube.pages.pnl.s01_common import (
    PL_FILTER_FIELDS,
    PL_SAVED_VIEW_CONTROLS,
    apply_pl_filters,
    pl_external_filter_map,
)
from cube.pages.pnl.s06_validation import (
    VALIDATE_PL_CHILD_LIMIT,
    build_validate_pl_comparison,
    build_validate_pl_table,
    build_validate_pl_section,
    normalize_validate_pl_open_paths,
    register_validate_pl_callbacks,
)
from cube.pages.pnl.s07_view import build_pl_filter_bar, build_pl_send_sections
from tools.s01_fixtures import HISTORICAL_MARKET_DATES, HISTORY_END_DATE


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


def _raw_risk() -> pd.DataFrame:
    base = {
        "Source Type": "ir/delta",
        "Risk Type": "IR",
        "Risk Greek": "Delta",
        "Display Bucket": "Other",
        "Region": "Americas",
        "Group": "G10",
        "Reported Underlying": "USD-SOFR",
        "Underlying": "USD-SOFR",
        "Tenor Option": "N/A",
        "Split": "Risk",
        "Product": "XVA",
        "Portfolio": "BOOK-A",
        "Activity": "1111",
        "SignoffGroup": "SOG-A",
        "Category": "Core",
        "Sub Category": "Rates",
        "Open": 3.0,
        "Current": 4.0,
        "Risk Threshold": 1_000.0,
        "dRisk Threshold": 1_000.0,
        "PL Threshold": 1_000.0,
    }
    return pd.DataFrame(
        [
            {
                **base,
                "Tenor Swap": "1Y",
                "Risk": 10.0,
                "dRisk": 1.0,
                "PL": 4.0,
            },
            {
                **base,
                "Tenor Swap": "2Y",
                "Risk": 20.0,
                "dRisk": 2.0,
                "PL": 6.0,
            },
        ]
    )


def _colossus(*, duplicate: bool = False) -> pd.DataFrame:
    rows = [["BOOK-A", "USD-SOFR", "IR", "Delta", 12.0]]
    if duplicate:
        rows.append(rows[0])
    return pd.DataFrame(
        rows,
        columns=["Portfolio", "Underlying", "Risk Type", "Risk Greek", "PL"],
    )


def _token(**values: str) -> str:
    return json.dumps(values, sort_keys=True, separators=(",", ":"))


def _committed(
    *,
    portfolio: list[str] | None = None,
    exclude_selected: bool = False,
) -> dict[str, object]:
    return {
        "scope": "pnl",
        "view_id": "__base__",
        "filters": {
            field.key: list(portfolio or []) if field.key == "portfolio" else []
            for field in PL_FILTER_FIELDS
        },
        "exclude_selected": exclude_selected,
    }


def test_comparison_aggregates_predict_before_one_to_one_colossus_join() -> None:
    comparison = build_validate_pl_comparison(_raw_risk(), _colossus())

    assert len(comparison) == 1
    assert comparison.loc[0, ["risk", "drisk", "pl", "colossus"]].tolist() == [
        30.0,
        3.0,
        10.0,
        12.0,
    ]
    assert comparison.loc[0, "comparison status"] == "Matched"


def test_comparison_rejects_duplicate_colossus_grain_instead_of_multiplying_it() -> (
    None
):
    with pytest.raises(ValueError, match="duplicate comparison keys"):
        build_validate_pl_comparison(_raw_risk(), _colossus(duplicate=True))


def test_comparison_never_presents_a_partial_predict_total() -> None:
    risk = _raw_risk()
    risk.loc[1, "PL"] = float("nan")

    comparison = build_validate_pl_comparison(risk, _colossus())

    assert pd.isna(comparison.loc[0, "pl"])
    assert comparison.loc[0, "colossus"] == 12.0


def test_comparison_vectorized_totals_keep_all_missing_drisk_unavailable() -> None:
    risk = _raw_risk()
    risk["dRisk"] = float("nan")

    comparison = build_validate_pl_comparison(risk, _colossus())

    assert comparison.loc[0, "risk"] == 30.0
    assert pd.isna(comparison.loc[0, "drisk"])
    assert comparison.loc[0, "pl"] == 10.0


def test_comparison_maps_known_colossus_only_and_audits_unknown_once() -> None:
    colossus = pd.concat(
        [
            _colossus(),
            pd.DataFrame(
                [
                    ["BOOK-A", "JPY-SOFR", "IR", "Delta", 3.0],
                    ["BOOK-Z", "GBP-SONIA", "IR", "Delta", 7.0],
                ],
                columns=["Portfolio", "Underlying", "Risk Type", "Risk Greek", "PL"],
            ),
        ],
        ignore_index=True,
    )

    comparison = build_validate_pl_comparison(_raw_risk(), colossus)

    known = comparison.loc[comparison["Underlying"].eq("JPY-SOFR")].iloc[0]
    assert known["SignoffGroup"] == "SOG-A"
    assert known["Product"] == "XVA"
    assert known["comparison status"] == "Colossus only"
    assert pd.isna(known["pl"])
    unknown = comparison.loc[comparison["Portfolio"].eq("BOOK-Z")]
    assert len(unknown) == 1
    assert unknown.iloc[0][HISTORY_MAPPING_STATUS] == UNMAPPED_VALUE
    assert unknown.iloc[0]["comparison status"] == "Colossus unmapped"
    assert unknown.iloc[0]["colossus"] == 7.0


def test_comparison_never_copies_colossus_across_ambiguous_products() -> None:
    ambiguous_risk = pd.concat(
        [
            _raw_risk(),
            _raw_risk().iloc[[0]].assign(Product="Hedges", PL=1.0),
        ],
        ignore_index=True,
    )

    comparison = build_validate_pl_comparison(ambiguous_risk, _colossus())

    colossus_rows = comparison.loc[comparison["colossus"].notna()]
    assert len(colossus_rows) == 1
    assert colossus_rows.iloc[0][HISTORY_MAPPING_STATUS] == UNMAPPED_VALUE
    assert colossus_rows.iloc[0]["Product"] == UNMAPPED_VALUE
    assert comparison.loc[comparison["pl"].notna(), "Product"].tolist() == [
        "Hedges",
        "XVA",
    ]


def test_shared_pl_filters_are_case_insensitive_with_documented_boolean_logic() -> None:
    frame = pd.DataFrame(
        [
            ["Credit", "SOG-A", "BOOK-A", "Core", "IG"],
            ["credit", "SOG-B", "BOOK-B", "Core", "HY"],
            ["Rates", "SOG-A", "BOOK-C", "Macro", "G10"],
        ],
        columns=[
            "Activity",
            "SignoffGroup",
            "Portfolio",
            "Category",
            "Sub Category",
        ],
    )
    original = frame.copy(deep=True)
    selections = pl_external_filter_map([["CREDIT", "rates"], ["sog-a"], [], [], []])
    included = apply_pl_filters(frame, selections)
    excluded = apply_pl_filters(
        frame,
        pl_external_filter_map([["credit"], ["sog-a"], [], [], []]),
        exclude_selected=True,
    )

    # Include is OR inside Activity, then AND with Signoff Group.
    assert included["Portfolio"].tolist() == ["BOOK-A", "BOOK-C"]
    # Exclude removes a row matching Activity OR Signoff Group.
    assert excluded["Portfolio"].tolist() == []
    pd.testing.assert_frame_equal(
        apply_pl_filters(frame, pl_external_filter_map([[], [], [], [], []])),
        original,
    )
    pd.testing.assert_frame_equal(frame, original)


def test_validate_pl_table_uses_risk_explorer_chevrons_at_truthful_comparison_grain() -> (
    None
):
    comparison = build_validate_pl_comparison(_raw_risk(), _colossus())
    open_paths = [
        _token(**{"SignoffGroup": "SOG-A"}),
        _token(**{"SignoffGroup": "SOG-A", "Risk Type": "IR"}),
        _token(
            **{
                "SignoffGroup": "SOG-A",
                "Risk Type": "IR",
                "Risk Greek": "Delta",
            }
        ),
        _token(
            **{
                "SignoffGroup": "SOG-A",
                "Risk Type": "IR",
                "Risk Greek": "Delta",
                "Underlying": "USD-SOFR",
            }
        ),
        _token(
            **{
                "SignoffGroup": "SOG-A",
                "Risk Type": "IR",
                "Risk Greek": "Delta",
                "Underlying": "USD-SOFR",
                "Product": "XVA",
            }
        ),
    ]

    table = build_validate_pl_table(comparison, open_paths=open_paths)
    headers = [
        component.children
        for component in _walk(table)
        if isinstance(component, html.Th) and component.scope == "col"
    ]
    row_labels = [
        component.children
        for component in _walk(table)
        if isinstance(component, html.Span)
        and getattr(component, "className", None) == "row-label-text"
    ]
    toggles = [
        component
        for component in _walk(table)
        if isinstance(component, html.Button)
        and "row-toggle" in str(getattr(component, "className", "")).split()
    ]

    assert headers == ["Index", "Risk", "dRisk", "P", "C"]
    assert row_labels == [
        "TOTAL",
        "SOG-A",
        "IR",
        "Delta",
        "USD-SOFR",
        "XVA",
        "BOOK-A",
    ]
    assert [toggle.children for toggle in toggles] == ["−"] * 5 + [""]
    colossus_cells = [
        component.to_plotly_json()["props"]
        for component in _walk(table)
        if isinstance(component, html.Td)
        and component.to_plotly_json()["props"].get("data-metric") == "colossus"
    ]
    assert [float(props["data-copy-value"]) for props in colossus_cells] == [12.0] * 7
    # C appears once at each visible hierarchy level, never once per archived
    # 1Y and 2Y tenor row.
    assert not any(label in {"1Y", "2Y"} for label in row_labels)


def test_validate_pl_table_keeps_unmapped_colossus_out_of_mapped_total() -> None:
    colossus = pd.concat(
        [
            _colossus(),
            pd.DataFrame(
                [["BOOK-Z", "GBP-SONIA", "IR", "Delta", 7.0]],
                columns=["Portfolio", "Underlying", "Risk Type", "Risk Greek", "PL"],
            ),
        ],
        ignore_index=True,
    )
    table = build_validate_pl_table(build_validate_pl_comparison(_raw_risk(), colossus))

    summaries = [
        item.children for item in _walk(table) if isinstance(item, html.Summary)
    ]
    assert summaries == ["Unmapped Colossus (1)"]
    mapped_table = next(
        item
        for item in _walk(table)
        if isinstance(item, html.Table)
        and getattr(item, "className", None) == "risk-table validate-pl-table"
    )
    mapped_total_c = next(
        item
        for item in _walk(mapped_table)
        if isinstance(item, html.Td)
        and item.to_plotly_json()["props"].get("data-metric") == "colossus"
    )
    assert float(mapped_total_c.to_plotly_json()["props"]["data-copy-value"]) == 12.0
    unmapped_table = next(
        item
        for item in _walk(table)
        if isinstance(item, html.Table)
        and getattr(item, "className", None) == "risk-table validate-pl-unmapped-table"
    )
    unmapped_metrics = [
        item.to_plotly_json()["props"]
        for item in _walk(unmapped_table)
        if isinstance(item, html.Td)
        and item.to_plotly_json()["props"].get("data-metric") in {"pl", "colossus"}
    ]
    assert [item["data-copy-value"] for item in unmapped_metrics] == ["", "7.0"]


def test_validate_pl_open_state_is_page_local_and_rows_are_browser_owned() -> None:
    risk_type = _token(**{"SignoffGroup": "SOG-A", "Risk Type": "IR"})
    greek = _token(
        **{
            "SignoffGroup": "SOG-A",
            "Risk Type": "IR",
            "Risk Greek": "Delta",
        }
    )
    malformed = '{"tenor swap":"1Y"}'

    assert normalize_validate_pl_open_paths([greek, malformed, greek]) == [greek]
    table = build_validate_pl_table(
        build_validate_pl_comparison(_raw_risk(), _colossus())
    )
    rows = [
        item
        for item in _walk(table)
        if isinstance(item, html.Tr)
        and "validate-pl-hierarchy-row" in str(getattr(item, "className", "")).split()
    ]
    toggles = [
        item
        for item in _walk(table)
        if isinstance(item, html.Button)
        and "validate-pl-row-toggle" in str(getattr(item, "className", "")).split()
    ]

    assert risk_type != greek
    assert rows[0].hidden is False
    assert all(row.hidden is True for row in rows[1:])
    assert toggles
    assert all(
        "data-validate-path" in toggle.to_plotly_json()["props"] for toggle in toggles
    )


def test_validate_pl_stays_lazy_and_history_remains_page_owned() -> None:
    section = build_validate_pl_section()
    picker = next(
        component
        for component in _walk(section)
        if isinstance(component, dcc.Dropdown) and component.id == "pl-validate-date"
    )
    sections = build_pl_send_sections()
    summaries = [
        component.children
        for component in _walk(html.Div(sections))
        if isinstance(component, html.Summary)
    ]
    explorer_index = next(
        index
        for index, component in enumerate(sections)
        if getattr(component, "id", None) == "pnl-explorer"
    )

    assert isinstance(section, html.Details)
    assert section.children[0].children == "Validate P&L"
    assert picker.options == []
    assert picker.value is None
    assert picker.disabled is True
    assert any(
        isinstance(component, dcc.Store) and component.id == "pl-validate-render-key"
        for component in _walk(section)
    )
    assert "Validate P&L" in summaries
    assert "Histo P&L" not in summaries
    assert all(
        getattr(component, "id", None) != "pnl-history-workspace"
        for component in sections
    )
    assert explorer_index == len(sections) - 1


def test_validate_pl_discovers_and_renders_only_completed_dates_when_opened(
    tmp_path,
    monkeypatch,
) -> None:
    snapshot = SimpleNamespace(
        revision=1,
        refreshed_at=datetime(2026, 8, 14, 22, 5, tzinfo=timezone.utc),
        system_date=pd.Timestamp("2026-08-14"),
        market_date=pd.Timestamp("2026-08-14"),
        market_status="OFFICIAL",
        dashboard_frame=_raw_risk(),
        errors=(),
    )
    archive_official_snapshot(snapshot, lambda _date: _colossus(), tmp_path)
    incomplete = tmp_path / "2026-08-15"
    incomplete.mkdir(parents=True)

    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id=PL_SAVED_VIEW_CONTROLS.committed_state_id),
            dcc.Store(id="clear-cache-complete-store"),
            build_pl_filter_bar(),
            build_validate_pl_section(),
        ]
    )
    register_validate_pl_callbacks(app, tmp_path)
    key = next(key for key in app.callback_map if "pl-validate-date.options" in key)
    discover = app.callback_map[key]["callback"].__wrapped__

    options, selected, disabled, status = discover(1, None, None)

    assert options == [{"label": "2026-08-14", "value": "2026-08-14"}]
    assert selected == "2026-08-14"
    assert disabled is False
    assert status == ""
    monkeypatch.setattr(
        validate_pl_module,
        "_available_dates",
        lambda _root: (_ for _ in ()).throw(
            AssertionError("cached catalog was rediscovered")
        ),
    )
    assert discover(3, None, selected) == (options, selected, False, "")

    render_key = next(
        key for key in app.callback_map if "pl-validate-table.children" in key
    )
    render = app.callback_map[render_key]["callback"].__wrapped__
    table, render_status, render_key = render(selected, None, 1, None, None)

    assert "Official 2026-08-14" in render_status
    assert '"market_date":"2026-08-14"' in render_key
    assert any(
        isinstance(component, html.Table)
        and getattr(component, "className", None) == "risk-table validate-pl-table"
        for component in _walk(table)
    )
    original_load = validate_pl_module.load_risk_colossus_archive
    reloads = 0

    def counted_load(*args, **kwargs):
        nonlocal reloads
        reloads += 1
        return original_load(*args, **kwargs)

    monkeypatch.setattr(
        validate_pl_module,
        "load_risk_colossus_archive",
        counted_load,
    )
    _table, _status, refreshed_key = render(selected, None, 1, 1, render_key)
    assert reloads == 1
    assert '"cache_generation":1' in refreshed_key
    _table, _status, newest_key = render(selected, None, 1, 2, refreshed_key)
    assert reloads == 2
    assert '"cache_generation":2' in newest_key
    with pytest.raises(PreventUpdate):
        render(selected, None, 1, 1, refreshed_key)

    monkeypatch.setattr(
        validate_pl_module,
        "load_risk_colossus_archive",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("unchanged or closed validation reloaded its archive")
        ),
    )
    with pytest.raises(PreventUpdate):
        render(selected, None, 3, 2, newest_key)
    with pytest.raises(PreventUpdate):
        render(selected, None, 2, 2, None)


def test_validate_pl_bounds_comparison_cache_to_eight_dates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id=PL_SAVED_VIEW_CONTROLS.committed_state_id),
            dcc.Store(id="clear-cache-complete-store"),
            build_pl_filter_bar(),
            build_validate_pl_section(),
        ]
    )
    register_validate_pl_callbacks(app, tmp_path)
    render = next(
        metadata["callback"].__wrapped__
        for metadata in app.callback_map.values()
        if "pl-validate-table.children" in str(metadata["output"])
    )
    loaded_dates: list[str] = []
    archive = SimpleNamespace(risk=_raw_risk(), colossus=_colossus())

    def load_archive(_root, market_date):
        loaded_dates.append(str(market_date))
        return archive

    monkeypatch.setattr(
        validate_pl_module,
        "load_risk_colossus_archive",
        load_archive,
    )
    dates = [f"2026-08-{day:02d}" for day in range(1, 10)]
    for market_date in dates:
        render(market_date, None, 1, None, None)

    render(dates[-1], None, 1, None, None)
    render(dates[0], None, 1, None, None)

    assert loaded_dates == [*dates, dates[0]]


def test_checked_in_annual_archive_is_discoverable_and_renders_validate_pl() -> None:
    history_root = Path(__file__).resolve().parents[1] / "data" / "histo"
    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id=PL_SAVED_VIEW_CONTROLS.committed_state_id),
            dcc.Store(id="clear-cache-complete-store"),
            build_pl_filter_bar(),
            build_validate_pl_section(),
        ]
    )
    register_validate_pl_callbacks(app, history_root)
    catalog_key = next(
        key for key in app.callback_map if "pl-validate-date.options" in key
    )
    discover = app.callback_map[catalog_key]["callback"].__wrapped__

    options, selected, disabled, status = discover(1, None, None)

    assert {option["value"] for option in options} == set(HISTORICAL_MARKET_DATES)
    assert selected == HISTORY_END_DATE
    assert disabled is False
    assert status == ""

    render_key = next(
        key for key in app.callback_map if "pl-validate-table.children" in key
    )
    render = app.callback_map[render_key]["callback"].__wrapped__
    table, render_status, render_key = render(selected, None, 1, None, None)

    assert f"Official {HISTORY_END_DATE}" in render_status
    assert "matched" in render_status
    assert f'"market_date":"{HISTORY_END_DATE}"' in render_key
    labels = [
        component.children
        for component in _walk(table)
        if isinstance(component, html.Span)
        and getattr(component, "className", None) == "row-label-text"
    ]
    assert labels[0] == "TOTAL"
    assert any("TEMP_REPLACE_ME" in str(label) for label in labels[1:])


def test_validate_callback_uses_committed_page_filter(tmp_path) -> None:
    snapshot = SimpleNamespace(
        revision=1,
        refreshed_at=datetime(2026, 8, 14, 22, 5, tzinfo=timezone.utc),
        system_date=pd.Timestamp("2026-08-14"),
        market_date=pd.Timestamp("2026-08-14"),
        market_status="OFFICIAL",
        dashboard_frame=_raw_risk(),
        errors=(),
    )
    colossus = pd.concat(
        [
            _colossus(),
            pd.DataFrame(
                [["BOOK-Z", "GBP-SONIA", "IR", "Delta", 7.0]],
                columns=["Portfolio", "Underlying", "Risk Type", "Risk Greek", "PL"],
            ),
        ],
        ignore_index=True,
    )
    archive_official_snapshot(snapshot, lambda _date: colossus, tmp_path)
    app = Dash(__name__)
    app.layout = html.Div(
        [
            dcc.Store(id=PL_SAVED_VIEW_CONTROLS.committed_state_id),
            dcc.Store(id="clear-cache-complete-store"),
            build_pl_filter_bar(),
            build_validate_pl_section(),
        ]
    )
    register_validate_pl_callbacks(app, tmp_path)
    render = next(
        metadata["callback"].__wrapped__
        for metadata in app.callback_map.values()
        if "pl-validate-table.children" in str(metadata["output"])
    )
    table, status, render_key = render(
        "2026-08-14",
        _committed(portfolio=["book-z"]),
        1,
        None,
        None,
    )

    assert "1 filtered rows" in status
    assert "0 mapped" in status
    assert "1 Unmapped Colossus" in status
    assert '"Portfolio":["book-z"]' in render_key
    assert "Unmapped Colossus (1)" in [
        item.children for item in _walk(table) if isinstance(item, html.Summary)
    ]


def test_validate_pl_caps_browser_tree_without_changing_total() -> None:
    risk = pd.concat(
        [
            _raw_risk().assign(
                SignoffGroup=f"SOG-{index:02d}",
                Portfolio=f"BOOK-{index:02d}",
            )
            for index in range(VALIDATE_PL_CHILD_LIMIT + 4)
        ],
        ignore_index=True,
    )
    colossus = pd.DataFrame(
        [
            [f"BOOK-{index:02d}", "USD-SOFR", "IR", "Delta", 12.0]
            for index in range(VALIDATE_PL_CHILD_LIMIT + 4)
        ],
        columns=["Portfolio", "Underlying", "Risk Type", "Risk Greek", "PL"],
    )
    table = build_validate_pl_table(build_validate_pl_comparison(risk, colossus))
    labels = [
        item.children
        for item in _walk(table)
        if isinstance(item, html.Span)
        and getattr(item, "className", None) == "row-label-text"
    ]
    total_predict = next(
        item
        for item in _walk(table)
        if isinstance(item, html.Td)
        and item.to_plotly_json()["props"].get("data-metric") == "pl"
    )

    assert labels[0] == "TOTAL"
    assert (
        len([label for label in labels if str(label).startswith("SOG-")])
        == VALIDATE_PL_CHILD_LIMIT
    )
    assert float(total_predict.to_plotly_json()["props"]["data-copy-value"]) == (
        10.0 * (VALIDATE_PL_CHILD_LIMIT + 4)
    )


def test_validate_pl_chevron_handler_scans_only_clicked_subtree() -> None:
    script = (Path(__file__).resolve().parents[1] / "assets" / "s14_pnl.js").read_text(
        encoding="utf-8"
    )

    assert "row.nextElementSibling" in script
    assert "validateLastToggleMs" in script
    assert 'querySelectorAll("tbody tr.validate-pl-hierarchy-row")' not in script
    assert "rowsByPath" not in script
