"""Risk-local Portfolio and include/exclude filter regressions."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterable
from pathlib import Path
from threading import Event, Lock
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import dcc, html, no_update
from dash.exceptions import PreventUpdate

from cube.services.s04_savedviews import SavedFilterView
from cube.domain.s07_governance import (
    _validate_dashboard_release,
    to_dashboard_frame,
)
from cube.domain.s10_search import MARKET_RESULT_COLUMNS, SearchCatalog
from cube.pages.risk import s07_explorer as events_module
from cube.pages.risk import s14_workspacecallbacks as workspace_callbacks
from cube.ui.s01_constants import (
    DEFAULT_VIEW_DIMENSION,
    DIMENSION_FILTER_IDS,
    FILTER_DIMENSION_FIELDS as SHARED_FILTER_DIMENSION_FIELDS,
    RISK_FILTER_DIMENSION_FIELDS,
    VIEW_DIMENSION_FIELDS,
)
from cube.ui.s02_aggregation import (
    apply_filters,
    credit_measure_values,
    detail_frame,
    dimension_title,
    filter_ir_family,
    prepare_risk_data,
    row_key,
    selected_dimension,
)
from cube.pages.risk.s01_common import RISK_SAVED_VIEW_CONTROLS
from cube.pages.risk.s06_explorertables import build_risk_table
from cube.pages.risk.s11_promotion import (
    PromotionBasis,
    calculate_current_view_promotion,
)
from cube.pages.risk.s16_view import build_layout
from cube.ui.s04_components import build_aggregate_pl_table
from cube.app.s07_factory import build_app
from cube.pages.risk.s10_search import _render_quick_search_pivot
from cube.pages.risk.s02_state import (
    _RiskDataCache,
    _top_book_action_view_token,
    filter_unmapped_portfolios,
)
from cube.ui.s03_filters import saved_view_apply_request


FILTER_DIMENSION_FIELDS = RISK_FILTER_DIMENSION_FIELDS


def _raw_risk_frame() -> pd.DataFrame:
    base = {
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
        "Activity": "1111",
        "SignoffGroup": "SOG-A",
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
                "Portfolio": "BOOK-A",
                "Category": "Core",
                "Risk": 10.0,
                "dRisk": 1.0,
                "PL": 4.0,
            },
            {
                **base,
                "Portfolio": "BOOK-B",
                "Category": "Hedge",
                "Risk": 20.0,
                "dRisk": 2.0,
                "PL": 6.0,
            },
        ]
    )


def _reducible_raw_frame() -> pd.DataFrame:
    base = _raw_risk_frame().iloc[0].to_dict()
    rows: list[dict[str, object]] = []
    for portfolio, risks in (("BOOK-A", (10.0, 20.0)), ("BOOK-B", (4.0, 5.0))):
        for order, tenor in enumerate(("1Y", "2Y")):
            rows.append(
                {
                    **base,
                    "Portfolio": portfolio,
                    "Category": "Core" if portfolio == "BOOK-A" else "Hedge",
                    "Tenor Swap": tenor,
                    "Tenor Swap Order": order,
                    "Risk": risks[order],
                    "dRisk": risks[order] / 10.0,
                    "PL": risks[order] * 2.0,
                    "Open": float(order + 1),
                    "Current": float(order + 2),
                    "Market Available": True,
                    "Market Data Status": "Available",
                }
            )
    return pd.DataFrame(rows)


def _reduced_tenor_catalog() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Risk Type": "IR",
                "Risk Greek": "Delta",
                "Underlying": "USD-SOFR",
                "MatrixName": "IR_STANDARD",
            }
        ]
    )


def _reduced_tenor_matrix() -> pd.DataFrame:
    return pd.DataFrame(
        [[0.0, 1.0], [1.0, 1.0]],
        index=["2Y", "Long"],
        columns=["1Y", "2Y"],
    )


def _automatic_credit_raw_frame() -> pd.DataFrame:
    return _reducible_raw_frame().assign(
        **{
            "Source Type": "credit/delta",
            "Risk Type": "Credit",
            "Risk Greek": "Delta",
            "Underlying": "RAW-CREDIT",
            "Reported Underlying": "Reported Credit",
        }
    )


def _automatic_credit_mapping() -> pd.DataFrame:
    return pd.DataFrame(
        [("1Y", "2Y"), ("2Y", "2Y")],
        columns=["Full Tenor", "Reduced Tenor"],
    )


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


def _snapshot() -> SimpleNamespace:
    risk_status = pd.DataFrame(
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
        risk_status=risk_status,
        forced_dates={},
        forced_view_date=None,
        commodity_market_enabled=False,
        risk_checker_enabled=True,
        dashboard_frame=_raw_risk_frame(),
        market_frame=_raw_risk_frame(),
    )


def _warm_manager() -> SimpleNamespace:
    snapshot = _snapshot()

    def read_frame(name: str) -> SimpleNamespace:
        return SimpleNamespace(
            revision=snapshot.revision, frame=getattr(snapshot, name)
        )

    return SimpleNamespace(
        snapshot=snapshot,
        control_snapshot=snapshot,
        read_frame=read_frame,
        stage_delays={},
        health=SimpleNamespace(
            revision=1,
            refreshed_at=snapshot.refreshed_at,
            last_attempt_at=snapshot.refreshed_at,
            active_error_count=0,
        ),
    )


def _callback_outputs(metadata: dict) -> list[object]:
    output = metadata["output"]
    return list(output) if isinstance(output, (list, tuple)) else [output]


def _callback_inputs_for_output(
    app, component_id: str, component_property: str
) -> set[tuple[object, str]]:
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            output.component_id == component_id
            and output.component_property == component_property
            for output in _callback_outputs(item)
        )
    )
    return {(item["id"], item["property"]) for item in metadata["inputs"]}


def test_portfolio_is_internal_but_not_a_risk_filter_or_view() -> None:
    assert [field.key for field in SHARED_FILTER_DIMENSION_FIELDS] == [
        "activity",
        "signoffgroup",
        "portfolio",
        "category",
        "subcategory",
    ]
    assert [field.key for field in FILTER_DIMENSION_FIELDS] == [
        "activity",
        "signoffgroup",
        "category",
        "subcategory",
    ]
    assert [field.key for field in VIEW_DIMENSION_FIELDS] == [
        "product",
        "activity",
        "signoffgroup",
        "category",
        "subcategory",
    ]
    assert "portfolio" not in DIMENSION_FILTER_IDS
    assert DEFAULT_VIEW_DIMENSION == "activity"
    assert selected_dimension("portfolio") == "activity"
    assert dimension_title("portfolio") == "Activity"


def test_prepare_retains_portfolio_but_risk_filters_use_reporting_fields() -> None:
    prepared = prepare_risk_data(_raw_risk_frame())

    assert prepared["portfolio"].tolist() == ["BOOK-A", "BOOK-B"]
    included = apply_filters(
        prepared,
        ["IR"],
        ["Risk"],
        {"category": ["Core"], "activity": ["1111"]},
    )
    excluded = apply_filters(
        prepared,
        ["IR"],
        ["Risk"],
        {"category": ["Core"]},
        exclude_selected=True,
    )
    unrestricted = apply_filters(
        prepared,
        ["IR"],
        ["Risk"],
        {"category": None},
        exclude_selected=True,
    )

    assert included["portfolio"].tolist() == ["BOOK-A"]
    # Exclusion is AND across the per-dimension complements.
    assert excluded["portfolio"].tolist() == ["BOOK-B"]
    assert unrestricted["portfolio"].tolist() == ["BOOK-A", "BOOK-B"]


def test_risk_explorer_hides_raw_underlyings_without_losing_detail_identity() -> None:
    raw = _raw_risk_frame()
    raw["Reported Underlying"] = "G10-RATES"
    raw["Underlying"] = ["USD-SOFR", "EUR-ESTR"]
    raw["Risk"] = [10.0, 20.0]
    raw["dRisk"] = [1.0, 2.0]
    raw["PL"] = [4.0, 6.0]
    raw["Open"] = [3.0, 5.0]
    raw["Current"] = [4.0, 7.0]
    prepared = prepare_risk_data(raw)
    contexts = [
        {"risk greek": "Delta"},
        {"risk greek": "Delta", "region": "Americas"},
        {"risk greek": "Delta", "region": "Americas", "group": "G10"},
        {
            "risk greek": "Delta",
            "region": "Americas",
            "group": "G10",
            "reported underlying": "G10-RATES",
        },
    ]

    component = build_risk_table(
        prepared,
        expanded_metrics=[],
        open_rows=[row_key(context) for context in contexts],
        promotion_enabled=False,
        region_enabled=True,
        underlying_identity_mode="reported",
    )
    rows = [item for item in _walk(component) if isinstance(item, html.Tr)]
    row_classes = [str(getattr(row, "className", "")) for row in rows]
    labels = [
        str(item.children)
        for item in _walk(component)
        if isinstance(item, html.Span) and item.className == "row-label-text"
    ]

    assert any("group-kind-reported-underlying" in value for value in row_classes)
    assert not any("group-kind-underlying" in value for value in row_classes)
    assert "G10-RATES" in labels
    assert "USD-SOFR" not in labels
    assert "EUR-ESTR" not in labels

    reported_row = next(
        row
        for row in rows
        if "group-kind-reported-underlying" in str(getattr(row, "className", ""))
    )
    risk_cell = next(
        cell
        for cell in reported_row.children
        if getattr(cell, "data-metric", None) == "risk"
    )
    assert risk_cell.children.children == "30.0"

    tenor_row = next(
        row
        for row in rows
        if "group-kind-tenor-swap" in str(getattr(row, "className", ""))
    )
    move_cell = next(
        cell
        for cell in tenor_row.children
        if getattr(cell, "data-metric", None) == "move"
    )
    assert move_cell.children.children == "1.5"

    core = apply_filters(
        prepared,
        ["IR"],
        ["Risk"],
        {"category": ["Core"]},
    )
    core_component = build_risk_table(
        core,
        expanded_metrics=[],
        open_rows=[row_key(context) for context in contexts],
        promotion_enabled=False,
        region_enabled=True,
        underlying_identity_mode="reported",
    )
    core_tenor_row = next(
        row
        for row in _walk(core_component)
        if isinstance(row, html.Tr)
        and "group-kind-tenor-swap" in str(getattr(row, "className", ""))
    )
    core_move_cell = next(
        cell
        for cell in core_tenor_row.children
        if getattr(cell, "data-metric", None) == "move"
    )
    assert core_move_cell.children.children == "1"

    detail = detail_frame(prepared, contexts[-1], "risk")
    assert set(detail["underlying"]) == {"USD-SOFR", "EUR-ESTR"}

    raw_component = build_risk_table(
        prepared,
        expanded_metrics=[],
        open_rows=[row_key(context) for context in contexts],
        promotion_enabled=False,
        region_enabled=True,
        underlying_identity_mode="underlying",
    )
    raw_rows = [item for item in _walk(raw_component) if isinstance(item, html.Tr)]
    raw_row_classes = [str(getattr(row, "className", "")) for row in raw_rows]
    raw_labels = [
        str(item.children)
        for item in _walk(raw_component)
        if isinstance(item, html.Span) and item.className == "row-label-text"
    ]
    assert any("group-kind-underlying" in value for value in raw_row_classes)
    assert not any(
        "group-kind-reported-underlying" in value for value in raw_row_classes
    )
    assert {"USD-SOFR", "EUR-ESTR"} <= set(raw_labels)
    assert "G10-RATES" not in raw_labels


def test_prepare_keeps_numeric_and_named_portfolios_as_internal_text() -> None:
    mixed = _raw_risk_frame()
    mixed["Portfolio"] = [20222, "DLCDA"]

    prepared = prepare_risk_data(mixed)
    missing_value = prepare_risk_data(
        _raw_risk_frame().assign(Portfolio=[pd.NA, "DLCDA"])
    )
    absent_column = prepare_risk_data(_raw_risk_frame().drop(columns="Portfolio"))

    assert prepared["portfolio"].tolist() == ["20222", "DLCDA"]
    assert missing_value["portfolio"].tolist() == ["Unspecified", "DLCDA"]
    assert absent_column["portfolio"].eq("Unspecified").all()


def test_prepare_zero_fills_a_missing_neutral_promotion_score() -> None:
    raw = _raw_risk_frame()
    raw["Promotion Score"] = [pd.NA, 0.5]

    prepared = prepare_risk_data(raw)

    assert prepared["promotion score"].tolist() == pytest.approx([0.0, 0.5])


@pytest.mark.parametrize("values", ([True, False], [10.0, True]))
def test_prepare_rejects_boolean_numeric_values_for_native_and_mixed_dtypes(
    values,
) -> None:
    raw = _raw_risk_frame()
    raw["Risk"] = values

    with pytest.raises(ValueError, match="must not contain booleans"):
        prepare_risk_data(raw)


def test_dashboard_release_zero_fills_one_missing_metric_without_blanking_view() -> (
    None
):
    source = _raw_risk_frame().assign(
        **{
            "Portfolio Mapped": True,
            "Tenor Swap Order": 0,
            "Tenor Option Order": 0,
            "Promotion Reason": "",
            "Promotion Score": 0.0,
            "Vol Score": 0.0,
            "Risk": [10.0, float("inf")],
            "dRisk": [1.0, pd.NA],
            "PL": [4.0, "N/A"],
            "Open": [3.0, pd.NA],
            "Current": [4.0, pd.NA],
            "Move": [1.0, "-inf"],
            "Market Available": [True, False],
            "Market Data Status": ["Available", "Missing Open and Current"],
            "Risk SP01": [10.0, 20.0],
            "dRisk SP01": [1.0, pd.NA],
        }
    )

    released = to_dashboard_frame(source)
    prepared = prepare_risk_data(released)

    assert released.loc[1, ["Risk", "dRisk", "PL", "Move", "dRisk SP01"]].eq(0.0).all()
    assert released.loc[1, ["Open", "Current"]].isna().all()
    assert "dRisk PSP01" not in released
    assert prepared.loc[1, ["risk", "risk expo", "risk hedges"]].eq(0.0).all()
    assert prepared.loc[1, ["drisk", "drisk expo", "drisk hedges"]].eq(0.0).all()
    assert prepared.loc[1, ["pl", "pl expo", "pl hedges", "move"]].eq(0.0).all()
    assert credit_measure_values(prepared, "drisk", "SP01").tolist() == [1.0, 0.0]

    invalid_release = released.copy()
    invalid_release.loc[0, "Promotion Score"] = pd.NA
    with pytest.raises(ValueError, match="'Promotion Score'.*missing"):
        _validate_dashboard_release(invalid_release)


def test_dashboard_release_accepts_zero_filled_move_with_available_quotes() -> None:
    source = _raw_risk_frame().assign(
        **{
            "Portfolio Mapped": True,
            "Tenor Swap Order": 0,
            "Tenor Option Order": 0,
            "Promotion Reason": "",
            "Promotion Score": 0.0,
            "Vol Score": 0.0,
            "Risk": [10.0, 20.0],
            "dRisk": [1.0, 2.0],
            "PL": [4.0, 5.0],
            "Open": [3.0, 10.0],
            "Current": [4.0, 12.0],
            "Move": [1.0, pd.NA],
            "Market Available": [True, True],
            "Market Data Status": ["Available", "Available"],
        }
    )

    released = to_dashboard_frame(source)
    _validate_dashboard_release(released)

    assert released.loc[1, "Move"] == 0.0
    assert released.loc[1, ["Open", "Current"]].tolist() == [10.0, 12.0]


def test_dashboard_release_rejects_supplied_nonzero_move_quote_mismatch() -> None:
    source = _raw_risk_frame().assign(
        **{
            "Portfolio Mapped": True,
            "Tenor Swap Order": 0,
            "Tenor Option Order": 0,
            "Promotion Reason": "",
            "Promotion Score": 0.0,
            "Vol Score": 0.0,
            "Risk": [10.0, 20.0],
            "dRisk": [1.0, 2.0],
            "PL": [4.0, 5.0],
            "Open": [3.0, 10.0],
            "Current": [4.0, 12.0],
            "Move": [1.0, 99.0],
            "Market Available": [True, True],
            "Market Data Status": ["Available", "Available"],
        }
    )

    released = to_dashboard_frame(source)

    with pytest.raises(ValueError, match="non-zero Move must equal"):
        _validate_dashboard_release(released)


def test_include_and_exclude_modes_have_explicit_boolean_semantics() -> None:
    frame = pd.DataFrame(
        {
            "row": [
                "Credit / B",
                "Credit / D",
                "Credit / C",
                "Rates / B",
                "Rates / C",
            ],
            "risk type": ["IR"] * 5,
            "split": ["Risk"] * 5,
            "activity": ["Credit", "Credit", "Credit", "Rates", "Rates"],
            "portfolio": ["B", "D", "C", "B", "C"],
            "pl": [1.0] * 5,
        }
    )
    frame["category"] = frame["portfolio"]
    selections = {"activity": ["Credit"], "category": ["B", "D"]}

    included = apply_filters(frame, None, None, selections)
    excluded = apply_filters(
        frame,
        None,
        None,
        selections,
        exclude_selected=True,
    )

    assert included["row"].tolist() == ["Credit / B", "Credit / D"]
    # Exclude mode is (NOT Credit) AND (NOT B or D), not merely the inverse
    # of the included intersection.
    assert excluded["row"].tolist() == ["Rates / C"]


def test_ir_family_tabs_keep_xgamma_sources_inside_delta_and_vega() -> None:
    prepared = prepare_risk_data(_raw_risk_frame())
    layout = build_layout(prepared, _snapshot(), refresh_enabled=True)
    tabs = next(
        item
        for item in _walk(layout)
        if isinstance(item, dcc.Tabs) and item.id == "ir-family-tabs"
    )

    assert [(tab.label, tab.value) for tab in tabs.children] == [
        ("Delta", "delta"),
        ("Basis", "basis"),
        ("Vega", "vega"),
    ]


def test_filtered_cache_distinguishes_include_and_exclude_generations() -> None:
    prepared = prepare_risk_data(_raw_risk_frame())
    cache = _RiskDataCache(prepared, revision=7)
    selected = {"category": ["Core"]}

    included = cache.filtered(None, "IR", None, ["Risk"], selected)
    excluded = cache.filtered(
        None,
        "IR",
        None,
        ["Risk"],
        selected,
        exclude_selected=True,
    )

    assert included["portfolio"].tolist() == ["BOOK-A"]
    assert excluded["portfolio"].tolist() == ["BOOK-B"]


def test_clear_cache_drops_only_reconstructable_risk_views() -> None:
    prepared = prepare_risk_data(_raw_risk_frame())
    cache = _RiskDataCache(prepared, revision=7)
    selected = {"category": ["Core"]}
    filtered = cache.filtered(None, "IR", None, ["Risk"], selected)
    builds: list[int] = []

    def build_rendered() -> object:
        builds.append(len(builds) + 1)
        return object()

    rendered = cache.rendered("risk-table", build_rendered)
    assert cache.filtered(None, "IR", None, ["Risk"], selected) is filtered
    assert cache.rendered("risk-table", build_rendered) is rendered

    cache.clear_reconstructable()

    assert cache.current(None) is prepared
    assert cache.filtered(None, "IR", None, ["Risk"], selected) is not filtered
    assert cache.rendered("risk-table", build_rendered) is not rendered
    assert builds == [1, 2]


def test_render_cache_serializes_and_deduplicates_concurrent_builds() -> None:
    cache = _RiskDataCache(prepare_risk_data(_raw_risk_frame()), revision=7)
    entered = Event()
    release = Event()
    counts_lock = Lock()
    builds = 0
    active = 0
    max_active = 0

    def build_rendered() -> object:
        nonlocal active, builds, max_active
        with counts_lock:
            builds += 1
            active += 1
            max_active = max(max_active, active)
        entered.set()
        assert release.wait(timeout=2.0)
        with counts_lock:
            active -= 1
        return object()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(cache.rendered, "same-table", build_rendered)
        assert entered.wait(timeout=2.0)
        second = executor.submit(cache.rendered, "same-table", build_rendered)
        release.set()
        first_result = first.result(timeout=2.0)
        second_result = second.result(timeout=2.0)

    assert first_result is second_result
    assert builds == 1
    assert max_active == 1


def test_full_tenor_mode_does_not_read_catalog_or_call_matrix_provider() -> None:
    prepared = prepare_risk_data(_reducible_raw_frame())
    calls: list[str] = []
    cache = _RiskDataCache(
        prepared,
        revision=7,
        # Deliberately absent: construction and a full-tenor read must not try
        # to open this production-style Path source before first paint.
        reduced_tenor_catalog="catalog-must-stay-lazy.csv",
        matrix_provider=lambda name: calls.append(name) or _reduced_tenor_matrix(),
    )

    full = cache.filtered(None, "IR", "delta", ["Risk"], {})

    assert len(full) == 4
    assert calls == []


def test_reduced_tenor_book_is_built_once_then_reused_across_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prepared = prepare_risk_data(_reducible_raw_frame())
    calls: list[str] = []
    cache = _RiskDataCache(
        prepared,
        revision=7,
        reduced_tenor_catalog=_reduced_tenor_catalog(),
        matrix_provider=lambda name: calls.append(name) or _reduced_tenor_matrix(),
    )
    reducer = cache._reducer()
    assert reducer is not None
    reduce_calls = 0
    original_reduce = reducer.reduce

    def counted_reduce(*args, **kwargs):
        nonlocal reduce_calls
        reduce_calls += 1
        return original_reduce(*args, **kwargs)

    monkeypatch.setattr(reducer, "reduce", counted_reduce)

    full = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Core"]},
    )
    assert calls == []
    assert full["tenor swap"].tolist() == ["1Y", "2Y"]

    reduced = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Core"]},
        reduced_tenor=True,
    )
    assert calls == ["IR_STANDARD"]
    assert reduced["portfolio"].tolist() == ["BOOK-A", "BOOK-A"]
    assert reduced["tenor swap"].tolist() == ["2Y", "Long"]
    assert reduced["risk"].tolist() == [20.0, 30.0]
    assert reduced["risk expo"].tolist() == [20.0, 30.0]
    assert reduced["open"].iloc[0] == 2.0
    assert pd.isna(reduced["open"].iloc[1])
    assert reduced["market available"].tolist() == [True, False]
    assert reduced["market data status"].tolist() == ["Available", ""]
    assert "Source Type" not in reduced
    assert "source type" in reduced
    hedge = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Hedge"]},
        reduced_tenor=True,
    )
    assert hedge["portfolio"].tolist() == ["BOOK-B", "BOOK-B"]
    assert hedge["risk"].tolist() == [5.0, 9.0]
    excluded = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Core"]},
        exclude_selected=True,
        reduced_tenor=True,
    )
    pd.testing.assert_frame_equal(excluded, hedge)
    assert reduce_calls == 1
    assert (
        cache.filtered(
            None,
            "IR",
            "delta",
            ["Risk"],
            {"category": ["Core"]},
            reduced_tenor=True,
        )
        is reduced
    )
    assert (
        cache.filtered(
            None,
            "IR",
            "delta",
            ["Risk"],
            {"category": ["Core"]},
        )
        is full
    )


def test_reduced_click_uses_committed_matrix_memory_without_provider_calls() -> None:
    prepared = prepare_risk_data(_reducible_raw_frame())
    provider_calls: list[str] = []
    matrix_reads = 0
    health = SimpleNamespace(revision=7)

    def read_matrices() -> SimpleNamespace:
        nonlocal matrix_reads
        matrix_reads += 1
        return SimpleNamespace(
            revision=7,
            matrices={("ir/delta", "IR_STANDARD"): _reduced_tenor_matrix()},
            authoritative_source_types=frozenset({"ir/delta"}),
        )

    manager = SimpleNamespace(
        health=health,
        read_frame=lambda _name: SimpleNamespace(
            revision=7,
            frame=_reducible_raw_frame(),
        ),
        read_reduction_matrices=read_matrices,
    )
    cache = _RiskDataCache(
        prepared,
        revision=7,
        reduced_tenor_catalog=_reduced_tenor_catalog(),
        matrix_provider=lambda name: (
            provider_calls.append(name) or _reduced_tenor_matrix()
        ),
    )

    first = cache.filtered(
        manager,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Core"]},
        reduced_tenor=True,
    )
    second = cache.filtered(
        manager,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Hedge"]},
        reduced_tenor=True,
    )

    assert first["tenor swap"].tolist() == ["2Y", "Long"]
    assert second["tenor swap"].tolist() == ["2Y", "Long"]
    assert matrix_reads == 1
    assert provider_calls == []


def test_shared_reduced_book_matches_filter_then_reduce_with_unmapped_rows() -> None:
    raw = _reducible_raw_frame()
    unmapped = raw.loc[raw["Portfolio"].eq("BOOK-A")].copy()
    unmapped["Portfolio"] = "BOOK-C"
    unmapped["Category"] = "Satellite"
    unmapped["Underlying"] = "UNMAPPED"
    unmapped["Reported Underlying"] = "Unmapped Reported"
    prepared = prepare_risk_data(pd.concat([raw, unmapped], ignore_index=True))
    filters = {"category": ["Core"]}

    # This is the former order: filter the positions, then reduce that subset.
    reference = _RiskDataCache(
        prepared,
        revision=7,
        reduced_tenor_catalog=_reduced_tenor_catalog(),
        matrix_provider=lambda _name: _reduced_tenor_matrix(),
    )
    filtered_first = apply_filters(
        filter_ir_family(prepared, "IR", "delta"),
        ["IR"],
        ["Risk"],
        filters,
        exclude_selected=True,
    )
    expected = reference._reduce_filtered(
        filtered_first,
        None,
        revision=7,
        fallback=prepared,
    )
    assert expected is not None

    # The cached order reduces once, then applies the same filter.
    cache = _RiskDataCache(
        prepared,
        revision=7,
        reduced_tenor_catalog=_reduced_tenor_catalog(),
        matrix_provider=lambda _name: _reduced_tenor_matrix(),
    )
    actual = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        filters,
        exclude_selected=True,
        reduced_tenor=True,
    )

    pd.testing.assert_frame_equal(
        actual.reset_index(drop=True),
        expected.reset_index(drop=True),
    )


def test_reduced_book_and_marketbook_are_invalidated_on_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _reducible_raw_frame()
    prepared = prepare_risk_data(raw)
    calls: list[str] = []
    cache = _RiskDataCache(
        prepared,
        revision=7,
        reduced_tenor_catalog=_reduced_tenor_catalog(),
        matrix_provider=lambda name: calls.append(name) or _reduced_tenor_matrix(),
    )
    reducer = cache._reducer()
    assert reducer is not None
    reduce_calls = 0
    original_reduce = reducer.reduce

    def counted_reduce(*args, **kwargs):
        nonlocal reduce_calls
        reduce_calls += 1
        return original_reduce(*args, **kwargs)

    monkeypatch.setattr(reducer, "reduce", counted_reduce)
    health = SimpleNamespace(revision=7)
    reads: list[tuple[str, int]] = []

    def market_for_revision(revision: int) -> pd.DataFrame:
        open_2y = 200.0 if revision == 7 else 300.0
        return pd.DataFrame(
            {
                "Source Type": ["ir/delta", "ir/delta"],
                "Underlying": ["USD-SOFR", "USD-SOFR"],
                "Tenor Swap": ["1Y", "2Y"],
                "Open": [100.0, open_2y],
                "Current": [101.0, open_2y + 2.0],
                "Move": [1.0, 2.0],
                "Market Available": [True, True],
                "Market Data Status": ["Available", "Available"],
            }
        )

    def read_frame(name: str) -> SimpleNamespace:
        reads.append((name, health.revision))
        return SimpleNamespace(
            revision=health.revision,
            frame=market_for_revision(health.revision),
        )

    manager = SimpleNamespace(health=health, read_frame=read_frame)
    global_view = cache.filtered(
        manager, "IR", "delta", ["Risk"], {}, reduced_tenor=True
    )
    book_view = cache.filtered(
        manager,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Core"]},
        reduced_tenor=True,
    )
    assert global_view.loc[global_view["tenor swap"].eq("2Y"), "open"].eq(200).all()
    assert book_view.loc[book_view["tenor swap"].eq("2Y"), "open"].eq(200).all()
    assert reads == [("market_frame", 7)]
    assert calls == ["IR_STANDARD"]
    assert reduce_calls == 1

    cache.clear_reconstructable()
    cache.filtered(manager, "IR", "delta", ["Risk"], {}, reduced_tenor=True)
    assert reads == [("market_frame", 7), ("market_frame", 7)]
    assert reduce_calls == 2

    health.revision = 8
    cache.replace_frame(raw, revision=8)
    revised = cache.filtered(manager, "IR", "delta", ["Risk"], {}, reduced_tenor=True)
    assert revised.loc[revised["tenor swap"].eq("2Y"), "open"].eq(300).all()
    assert reads[-1] == ("market_frame", 8)
    assert reduce_calls == 3


def test_automatic_credit_reduction_never_reads_catalog_and_keeps_market_quotes(
    tmp_path: Path,
) -> None:
    # The committed book also contains IR. Scoping the canonical reduced book
    # to the active Credit tab must still avoid opening the non-Credit CSV.
    raw = pd.concat(
        [_automatic_credit_raw_frame(), _reducible_raw_frame()],
        ignore_index=True,
    )
    prepared = prepare_risk_data(raw)
    calls: list[str] = []
    cache = _RiskDataCache(
        prepared,
        revision=7,
        # A Credit-only request must not even try to open the non-Credit CSV.
        reduced_tenor_catalog=tmp_path / "missing-s11-matrix.csv",
        matrix_provider=lambda name: calls.append(name) or _automatic_credit_mapping(),
    )
    health = SimpleNamespace(revision=7)
    market = pd.DataFrame(
        {
            "Source Type": ["credit/delta", "credit/delta"],
            "Underlying": ["RAW-CREDIT", "RAW-CREDIT"],
            "Tenor Swap": ["1Y", "2Y"],
            "Open": [100.0, 200.0],
            "Current": [101.0, 202.0],
            "Move": [1.0, 2.0],
            "Market Available": [True, True],
            "Market Data Status": ["Available", "Available"],
        }
    )
    manager = SimpleNamespace(
        health=health,
        read_frame=lambda name: SimpleNamespace(revision=7, frame=market),
    )

    reduced = cache.filtered(
        manager,
        "Credit",
        None,
        ["Risk"],
        {},
        reduced_tenor=True,
    )

    assert calls == ["CREDIT_STANDARD"]
    assert reduced["tenor swap"].tolist() == ["2Y", "2Y"]
    assert reduced["risk"].tolist() == [30.0, 9.0]
    assert reduced["open"].tolist() == [200.0, 200.0]
    assert reduced["current"].tolist() == [202.0, 202.0]
    assert reduced["move"].tolist() == [2.0, 2.0]


def test_reduced_book_does_not_cache_a_session_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _reducible_raw_frame()
    raw[["Risk Threshold", "dRisk Threshold", "PL Threshold"]] = 1.0
    cache = _RiskDataCache(
        prepare_risk_data(raw),
        revision=7,
        reduced_tenor_catalog=_reduced_tenor_catalog(),
        matrix_provider=lambda _name: _reduced_tenor_matrix(),
    )
    reducer = cache._reducer()
    assert reducer is not None
    reduce_calls = 0
    original_reduce = reducer.reduce

    def counted_reduce(*args, **kwargs):
        nonlocal reduce_calls
        reduce_calls += 1
        return original_reduce(*args, **kwargs)

    monkeypatch.setattr(reducer, "reduce", counted_reduce)
    baseline = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {},
        reduced_tenor=True,
    )
    basis = PromotionBasis.build(
        7,
        risk_type="IR",
        ir_family="delta",
        splits=["Risk"],
        filters={field.key: [] for field in FILTER_DIMENSION_FIELDS},
        reduced_tenor=True,
    )
    generation = calculate_current_view_promotion(
        baseline,
        basis,
        identifier="reduced-generation",
    )
    generation_store = cache.publish_promotion_generation(generation)

    promoted = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Core"]},
        promotion_generation=generation_store,
        reduced_tenor=True,
    )
    baseline_again = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Hedge"]},
        reduced_tenor=True,
    )

    assert promoted["display bucket"].eq("USD-SOFR").all()
    assert promoted["promotion reason"].str.contains("Big Risk").all()
    assert baseline_again["display bucket"].eq("Other").all()
    assert baseline_again["promotion reason"].eq("").all()
    assert reduce_calls == 1


def test_risk_promotion_changes_only_after_explicit_generation() -> None:
    """Ordinary filters retain baseline; one explicit generation is immutable."""

    raw = _raw_risk_frame()
    raw["Risk"] = [600.0, 600.0]
    raw["dRisk"] = [0.0, 0.0]
    raw["PL"] = [0.0, 0.0]
    cache = _RiskDataCache(prepare_risk_data(raw), revision=7)

    global_view = cache.filtered(None, "IR", "delta", ["Risk"], {})
    baseline_book_view = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Core"]},
    )

    assert global_view["risk"].sum() == 1_200.0
    assert global_view["display bucket"].eq("Other").all()
    assert baseline_book_view["risk"].sum() == 600.0
    assert baseline_book_view["display bucket"].eq("Other").all()

    basis = PromotionBasis.build(
        7,
        risk_type="IR",
        ir_family="delta",
        splits=["Risk"],
        filters={field.key: [] for field in FILTER_DIMENSION_FIELDS},
    )
    generation = calculate_current_view_promotion(
        global_view,
        basis,
        identifier="test-generation",
    )
    generation_store = cache.publish_promotion_generation(generation)
    generated_global = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {},
        promotion_generation=generation_store,
    )
    generated_book = cache.filtered(
        None,
        "IR",
        "delta",
        ["Risk"],
        {"category": ["Core"]},
        promotion_generation=generation_store,
    )

    assert generated_global["display bucket"].eq("USD-SOFR").all()
    assert generated_global["promotion reason"].eq("Big Risk").all()
    # Filtering does not silently calculate a new 600/1000 classification.
    assert generated_book["display bucket"].eq("USD-SOFR").all()
    assert generated_book["promotion reason"].eq("Big Risk").all()


def test_risk_filter_owner_applies_pending_saved_view_without_losing_manual_edits(
    monkeypatch,
) -> None:
    app = build_app(refresh_manager=_warm_manager())
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            output.component_id == DIMENSION_FILTER_IDS["activity"]
            and output.component_property == "value"
            for output in _callback_outputs(item)
        )
    )
    callback = metadata["callback"].__wrapped__
    assert (
        RISK_SAVED_VIEW_CONTROLS.applied_request_id,
        "data",
    ) in {(item["id"], item["property"]) for item in metadata["state"]}
    view = SavedFilterView(
        identifier="morning--0123456789ab",
        scope="risk",
        name="Morning",
        filters={
            "activity": ("1111",),
            "signoffgroup": ("SOG-A",),
            "category": ("Core",),
            "subcategory": ("Rates",),
        },
        exclude_selected=True,
    )
    request = saved_view_apply_request(
        view,
        base_filters={field.key: [] for field in FILTER_DIMENSION_FIELDS},
        base_exclude_selected=False,
    )
    monkeypatch.setattr(
        events_module,
        "ctx",
        SimpleNamespace(triggered_id=RISK_SAVED_VIEW_CONTROLS.apply_request_id),
    )

    result = callback(
        1,
        request,
        None,
        *([[]] * len(FILTER_DIMENSION_FIELDS)),
        [],
        None,
        False,
    )

    assert result[1::2][:4] == (
        ["1111"],
        ["SOG-A"],
        ["Core"],
        ["Rates"],
    )
    assert result[-1] == ["exclude"]

    # Dash may coalesce the request Store and a financial revision update, in
    # which case triggered_id is the revision. The pending request still owns
    # the unchanged base controls and must not be stranded forever.
    monkeypatch.setattr(
        events_module,
        "ctx",
        SimpleNamespace(triggered_id="data-revision-store"),
    )
    coalesced = callback(
        2,
        request,
        None,
        *([[]] * len(FILTER_DIMENSION_FIELDS)),
        [],
        None,
        True,
    )
    assert coalesced[1::2][:4] == result[1::2][:4]
    assert coalesced[-1] == ["exclude"]

    manual = [[] for _field in FILTER_DIMENSION_FIELDS]
    manual[2] = ["Hedge"]
    superseded = callback(3, request, None, *manual, [], None, True)
    assert superseded[5] == ["Hedge"]
    assert superseded[-1] == []

    acknowledged = callback(
        4,
        request,
        None,
        *([[]] * len(FILTER_DIMENSION_FIELDS)),
        [],
        request["request_id"],
        True,
    )
    assert acknowledged[1::2][:4] == ([], [], [], [])
    assert acknowledged[-1] == []


def test_risk_filter_owner_initializes_base_activities_without_apply(
    monkeypatch,
) -> None:
    manager = _warm_manager()
    base = _raw_risk_frame().iloc[[0]].copy()
    manager.snapshot.dashboard_frame = pd.concat(
        [
            base.assign(Activity=activity)
            for activity in ("Activity 1", "Activity 2", "Activity 3")
        ],
        ignore_index=True,
    )
    app = build_app(refresh_manager=manager)
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            output.component_id == DIMENSION_FILTER_IDS["activity"]
            and output.component_property == "value"
            for output in _callback_outputs(item)
        )
    )
    owner = metadata["callback"].__wrapped__
    monkeypatch.setattr(
        events_module,
        "ctx",
        SimpleNamespace(triggered_id="data-revision-store"),
    )

    result = owner(
        1,
        None,
        None,
        *([[]] * len(FILTER_DIMENSION_FIELDS)),
        [],
        None,
        False,
    )

    assert result[1] == ["Activity 1", "Activity 2", "Activity 3"]
    assert result[-2] is True
    assert result[-1] == []


def test_risk_clear_cache_preserves_the_committed_filter_draft(monkeypatch) -> None:
    app = build_app(refresh_manager=_warm_manager())
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            output.component_id == DIMENSION_FILTER_IDS["activity"]
            and output.component_property == "value"
            for output in _callback_outputs(item)
        )
    )
    owner = metadata["callback"].__wrapped__
    selected = [["1111"], ["SOG-A"], ["Core"], ["Rates"]]
    monkeypatch.setattr(
        events_module,
        "ctx",
        SimpleNamespace(triggered_id="clear-cache-complete-store"),
    )

    result = owner(2, None, 1, *selected, ["exclude"], None, True)

    assert result[1::2][:4] == tuple(selected)
    assert result[-2] is True
    assert result[-1] == ["exclude"]


def test_risk_filter_values_and_mode_have_one_callback_owner() -> None:
    app = build_app(refresh_manager=_warm_manager())
    governed = {
        *((component_id, "value") for component_id in DIMENSION_FILTER_IDS.values()),
        ("risk-filter-exclude-selected", "value"),
    }
    owners = {identity: 0 for identity in governed}
    for metadata in app.callback_map.values():
        for output in _callback_outputs(metadata):
            identity = (str(output.component_id), output.component_property)
            if identity in owners:
                owners[identity] += 1

    assert set(owners.values()) == {1}


def test_only_the_committed_risk_filter_state_reaches_applied_stores() -> None:
    app = build_app(refresh_manager=_warm_manager())
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            output.component_id == "dimension-filter-values-store"
            for output in _callback_outputs(item)
        )
    )
    inputs = {(item["id"], item["property"]) for item in metadata["inputs"]}
    callback = metadata["callback"].__wrapped__
    values = [
        [f"VALUE-{index}"] for index, _field in enumerate(FILTER_DIMENSION_FIELDS)
    ]
    committed = {
        "scope": "risk",
        "view_id": "base",
        "filters": {
            field.key: selected
            for field, selected in zip(FILTER_DIMENSION_FIELDS, values, strict=True)
        },
        "exclude_selected": True,
    }

    applied_values, applied_exclude = callback(committed, 1)

    assert applied_values == values
    assert applied_exclude == ["exclude"]
    assert inputs == {
        (RISK_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
        ("data-revision-store", "data"),
    }


def test_split_selection_only_publishes_when_context_prunes_it() -> None:
    effective, value_update = events_module._pruned_split_selection(
        ["Risk", "New Trades"],
        ["Risk", "New Trades"],
    )
    assert effective == ["Risk", "New Trades"]
    assert value_update is no_update

    effective, value_update = events_module._pruned_split_selection(
        ["Risk", "Unavailable"],
        ["Risk", "New Trades"],
    )
    assert effective == ["Risk"]
    assert value_update == ["Risk"]


def test_quick_market_uses_data_as_its_only_history_workspace() -> None:
    app = build_app(refresh_manager=_warm_manager())
    layout_ids = {
        str(getattr(component, "id", ""))
        for component in _walk(
            build_layout(
                prepare_risk_data(_raw_risk_frame()),
                _snapshot(),
                refresh_enabled=True,
            )
        )
    }
    assert "quick-market-open-data" in layout_ids
    assert not any(value.startswith("quick-market-history-") for value in layout_ids)
    callback_outputs = {
        (str(output.component_id), output.component_property)
        for metadata in app.callback_map.values()
        for output in _callback_outputs(metadata)
    }
    assert not any(
        component_id.startswith("quick-market-history-")
        for component_id, _property in callback_outputs
    )


def test_quick_risk_identity_choices_follow_the_governed_filter_view() -> None:
    app = build_app(refresh_manager=_warm_manager())
    inputs = _callback_inputs_for_output(
        app,
        "quick-search-combine-udl",
        "options",
    )
    assert {
        ("split-filter", "value"),
        ("dimension-filter-values-store", "data"),
        ("risk-filter-exclude-applied-store", "data"),
    } <= inputs
    assert ("quick-search-identity-mode", "value") not in inputs
    assert ("risk-filter-exclude-selected", "value") not in inputs
    assert (
        not {(component_id, "value") for component_id in DIMENSION_FILTER_IDS.values()}
        & inputs
    )


def test_portfolio_is_not_rendered_as_a_risk_filter_or_dimension() -> None:
    prepared = prepare_risk_data(_raw_risk_frame())
    layout = build_layout(prepared, _snapshot(), refresh_enabled=True)
    components = list(_walk(layout))

    exclude_mode = next(
        item
        for item in components
        if isinstance(item, dcc.Checklist) and item.id == "risk-filter-exclude-selected"
    )
    filter_row = next(
        item
        for item in components
        if isinstance(item, html.Div)
        and {"controls", "filter-controls"}
        <= set(str(getattr(item, "className", "")).split())
    )
    saved_view_bar = next(
        item
        for item in components
        if isinstance(item, html.Details)
        and getattr(item, "id", None) == "risk-saved-view-bar"
    )
    aggregate_dimension = next(
        item
        for item in components
        if isinstance(item, dcc.RadioItems) and item.id == "aggregate-pl-dimension"
    )
    table_dimension = next(
        item
        for item in components
        if isinstance(item, dcc.RadioItems) and item.id == "table-dimension"
    )

    assert not any(
        isinstance(item, dcc.Dropdown) and item.id == "portfolio-filter"
        for item in components
    )
    assert exclude_mode.options == [
        {
            "label": "Exclude rows matching any selected value",
            "value": "exclude",
        }
    ]
    assert exclude_mode.value == []
    filter_fields = filter_row.children[: len(FILTER_DIMENSION_FIELDS)]
    assert [control.children[0].children for control in filter_fields] == [
        "Activity",
        "Signoff Group",
        "Category",
        "Sub Category",
    ]
    assert filter_row.children[-1].id == "risk-filter-exclude-selected"
    assert "filter-mode-control" in str(filter_row.children[-1].className).split()
    saved_view_notes = [
        item
        for item in _walk(saved_view_bar)
        if isinstance(item, html.Div)
        and "saved-view-filter-note" in set(str(getattr(item, "className", "")).split())
    ]
    assert len(saved_view_notes) == 1
    assert "Risk is aggregated across Portfolio" in saved_view_notes[0].children
    assert filter_row in list(_walk(saved_view_bar))
    for selector in (aggregate_dimension, table_dimension):
        assert "portfolio" not in {option["value"] for option in selector.options}
        assert selector.value == "activity"


def test_warm_risk_layout_defers_tables_and_preserves_filter_state() -> None:
    prepared = prepare_risk_data(_raw_risk_frame())
    layout = build_layout(prepared, _snapshot(), refresh_enabled=True)
    components = list(_walk(layout))

    risk_grid = next(
        item for item in components if getattr(item, "id", None) == "risk-grid"
    )
    aggregate_grid = next(
        item for item in components if getattr(item, "id", None) == "aggregate-pl-grid"
    )
    filter_values = next(
        item
        for item in components
        if getattr(item, "id", None) == "dimension-filter-values-store"
    )
    render_ready = next(
        item
        for item in components
        if getattr(item, "id", None) == "risk-initial-render-ready"
    )

    assert not any(isinstance(item, html.Table) for item in _walk(risk_grid.children))
    assert not any(
        isinstance(item, html.Table) for item in _walk(aggregate_grid.children)
    )
    assert risk_grid.children.children == "Loading Risk Explorer…"
    assert aggregate_grid.children.children == "Loading Aggregate P&L…"
    assert filter_values.data == [[] for _field in FILTER_DIMENSION_FIELDS]
    assert render_ready.data is None


def test_risk_top_workspace_uses_four_ordered_tabs_with_aggregate_default() -> None:
    prepared = prepare_risk_data(_raw_risk_frame())
    layout = build_layout(prepared, _snapshot(), refresh_enabled=True)
    components = list(_walk(layout))
    workspace = next(
        item
        for item in components
        if isinstance(item, dcc.Tabs) and item.id == "risk-workspace-tabs"
    )
    disclosure = next(
        item
        for item in components
        if isinstance(item, html.Details)
        and getattr(item, "id", None) == "ag-pl-details"
    )

    assert disclosure.open is True
    assert workspace in list(_walk(disclosure))
    assert workspace.value == "aggregate-pl"
    assert [(tab.label, tab.value) for tab in workspace.children] == [
        ("Aggregate P&L", "aggregate-pl"),
        ("· Quick Risk", "quick-risk"),
        ("· Quick Market", "quick-market"),
        ("· Top Promotions", "top-promotions"),
    ]
    ids = {str(getattr(item, "id", "")) for item in components}
    assert {
        "aggregate-pl-grid",
        "quick-search-details",
        "quick-market-details",
        "top-promotions-grid",
    } <= ids
    signal = next(
        item
        for item in components
        if isinstance(item, dcc.Dropdown) and item.id == "top-promotions-signal"
    )
    assert signal.value == "vol-score"
    assert signal.options == [
        {"label": "Vol Score", "value": "vol-score"},
        {"label": "Risk", "value": "risk"},
        {"label": "dRisk", "value": "drisk"},
        {"label": "P&L", "value": "pl"},
    ]
    assert "top-book-details" not in ids
    assert "top-book-grid" not in ids
    assert "top-book-summary" not in ids


def test_top_promotions_callback_is_lazy_and_has_no_tree_inputs() -> None:
    app = build_app(refresh_manager=_warm_manager())
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            output.component_id == "top-promotions-grid"
            and output.component_property == "children"
            for output in _callback_outputs(item)
        )
    )
    inputs = {(item["id"], item["property"]) for item in metadata["inputs"]}
    callback = metadata["callback"].__wrapped__

    closed_grid, closed_status = callback(
        "aggregate-pl",
        1,
        None,
        [],
        [[] for _field in FILTER_DIMENSION_FIELDS],
        [],
        "vol-score",
    )

    assert closed_grid is None
    assert "Select Top Promotions" in closed_status
    assert ("risk-workspace-tabs", "value") in inputs
    assert ("top-promotions-signal", "value") in inputs
    assert ("promotion-generation-store", "data") in inputs
    assert not any(
        str(component_id).startswith("top-book") for component_id, _ in inputs
    )


def test_promotion_recalculation_is_shared_across_risk_tabs() -> None:
    app = build_app(refresh_manager=_warm_manager())
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            output.component_id == "promotion-generation-store"
            and output.component_property == "data"
            for output in _callback_outputs(item)
        )
    )
    inputs = {(item["id"], item["property"]) for item in metadata["inputs"]}
    states = {(item["id"], item["property"]) for item in metadata["state"]}

    assert ("split-filter", "value") not in inputs
    assert ("split-filter", "value") in states
    assert ("risk-type-tabs", "value") not in inputs
    assert ("ir-family-tabs", "value") not in inputs
    assert ("dimension-filter-values-store", "data") in inputs
    assert ("risk-filter-exclude-applied-store", "data") in inputs
    assert ("risk-filter-exclude-selected", "value") not in inputs


def test_aggregate_toggle_ids_match_the_registered_pattern_callback() -> None:
    prepared = prepare_risk_data(_raw_risk_frame())
    table = build_aggregate_pl_table(prepared, "activity", [])
    toggles = [
        item
        for item in _walk(table)
        if isinstance(getattr(item, "id", None), dict)
        and item.id.get("type") == "aggregate-row-toggle"
    ]
    toggle_ids = [item.id for item in toggles]

    assert toggle_ids
    assert all(
        set(component_id) == {"type", "risk_type"} for component_id in toggle_ids
    )
    assert all(toggle.children == "▸" for toggle in toggles)
    assert all(
        {"row-toggle", "aggregate-row-toggle"} <= set(str(toggle.className).split())
        for toggle in toggles
    )
    assert all(
        toggle.to_plotly_json()["props"]["aria-expanded"] == "false"
        for toggle in toggles
    )
    assert all(
        toggle.title == toggle.to_plotly_json()["props"]["aria-label"]
        and str(toggle.title).startswith("Expand ")
        for toggle in toggles
    )
    aggregate_table = next(
        item for item in _walk(table) if isinstance(item, html.Table)
    )
    risk_rows = [
        item
        for item in _walk(aggregate_table)
        if isinstance(item, html.Tr)
        and getattr(item, "className", None) == "aggregate-risk-row"
    ]
    assert aggregate_table.role == "treegrid"
    assert all(
        row.to_plotly_json()["props"]["aria-level"] == "1"
        and row.to_plotly_json()["props"]["aria-expanded"] == "false"
        for row in risk_rows
    )

    expanded_table = build_aggregate_pl_table(prepared, "activity", ["IR"])
    ir_toggle = next(
        item
        for item in _walk(expanded_table)
        if isinstance(getattr(item, "id", None), dict)
        and item.id == {"type": "aggregate-row-toggle", "risk_type": "IR"}
    )
    assert ir_toggle.title == "Collapse IR greeks"
    assert ir_toggle.to_plotly_json()["props"]["aria-label"] == ir_toggle.title
    greek_rows = [
        item
        for item in _walk(expanded_table)
        if isinstance(item, html.Tr)
        and getattr(item, "className", None) == "aggregate-greek-row"
    ]
    assert ir_toggle.children == "−"
    assert ir_toggle.to_plotly_json()["props"]["aria-expanded"] == "true"
    assert greek_rows
    assert all(
        row.to_plotly_json()["props"]["aria-level"] == "2"
        and "aria-expanded" not in row.to_plotly_json()["props"]
        for row in greek_rows
    )

    app = build_app(refresh_manager=_warm_manager())
    aggregate_inputs = _callback_inputs_for_output(
        app,
        "aggregate-pl-grid",
        "children",
    )
    assert ("promotion-generation-store", "data") not in aggregate_inputs
    assert ("risk-initial-render-ready", "data") in aggregate_inputs
    assert (
        '{"risk_type":["ALL"],"type":"aggregate-row-toggle"}',
        "n_clicks",
    ) in aggregate_inputs


def test_aggregate_pl_falls_back_from_portfolio_and_aggregates_books() -> None:
    prepared = prepare_risk_data(_raw_risk_frame())
    component = build_aggregate_pl_table(prepared, "portfolio", [])
    header = next(item for item in _walk(component) if isinstance(item, html.Thead))
    labels = [str(item.children) for item in _walk(header) if isinstance(item, html.Th)]

    assert labels == ["Index", "1111", "Total"]


def test_aggregate_waits_for_the_matching_risk_render_revision(monkeypatch) -> None:
    app = build_app(data=_raw_risk_frame())
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            output.component_id == "aggregate-pl-grid"
            and output.component_property == "children"
            for output in _callback_outputs(item)
        )
    )
    callback = metadata["callback"].__wrapped__
    arguments = ("activity", 0, None, [], [], [[], [], [], []], [], [])

    with pytest.raises(PreventUpdate):
        callback(*arguments)

    monkeypatch.setattr(workspace_callbacks, "ctx", SimpleNamespace(triggered_id=None))
    _open_rows, component = callback(
        "activity",
        0,
        0,
        [],
        [],
        [[], [], [], []],
        [],
        [],
    )

    assert any(isinstance(item, html.Table) for item in _walk(component))


def test_risk_consumers_use_applied_filters_but_unmapped_inventory_is_complete() -> (
    None
):
    app = build_app(refresh_manager=_warm_manager())
    applied_exclusion = ("risk-filter-exclude-applied-store", "data")
    applied_filters = ("dimension-filter-values-store", "data")

    for output_id in (
        "aggregate-pl-grid",
        "top-promotions-grid",
        "quick-search-results",
    ):
        inputs = _callback_inputs_for_output(app, output_id, "children")
        assert applied_exclusion in inputs
        assert applied_filters in inputs
        assert ("risk-filter-exclude-selected", "value") not in inputs
        assert ("portfolio-filter", "value") not in inputs

    unmapped_inputs = _callback_inputs_for_output(
        app, "unmapped-books-grid", "children"
    )
    assert applied_exclusion not in unmapped_inputs
    assert applied_filters not in unmapped_inputs

    explorer_inputs = _callback_inputs_for_output(app, "risk-grid", "children")
    assert applied_exclusion in explorer_inputs
    assert applied_filters in explorer_inputs
    sync_inputs = _callback_inputs_for_output(
        app, "dimension-filter-values-store", "data"
    )
    assert ("risk-saved-view-committed", "data") in sync_inputs
    assert ("portfolio-filter", "value") not in sync_inputs


def test_unmapped_inventory_applies_only_its_meaningful_portfolio_dimension() -> None:
    frame = pd.DataFrame(
        {
            "Portfolio": ["BOOK-A", "BOOK-B"],
            "Activity": ["Unmapped", "Unmapped"],
        }
    )

    included = filter_unmapped_portfolios(frame, ["BOOK-A"])
    excluded = filter_unmapped_portfolios(
        frame,
        ["BOOK-A"],
        exclude_selected=True,
    )

    assert included["Portfolio"].tolist() == ["BOOK-A"]
    assert excluded["Portfolio"].tolist() == ["BOOK-B"]


def _quick_catalog() -> SearchCatalog:
    market = pd.DataFrame(
        [
            [
                "ir/delta",
                "IR",
                "Delta",
                "USD-SOFR",
                "1Y",
                "N/A",
                0,
                pd.NA,
                pd.Timestamp("2026-08-14"),
                3.0,
                4.0,
                1.0,
                "OFFICIAL",
                "Available",
            ]
        ],
        columns=list(MARKET_RESULT_COLUMNS),
    )
    risk = pd.DataFrame(
        [
            ["BOOK-A", 10.0, 1.0, 4.0],
            ["BOOK-B", 20.0, 2.0, 6.0],
        ],
        columns=["Portfolio", "Risk", "dRisk", "PL"],
    )
    for column, value in {
        "Source Type": "ir/delta",
        "Risk Type": "IR",
        "Risk Greek": "Delta",
        "Split": "Risk",
        "Reported Underlying": "USD-SOFR",
        "Underlying": "USD-SOFR",
        "Tenor Swap": "1Y",
        "Tenor Option": "N/A",
        "Tenor Swap Order": 0,
        "Tenor Option Order": pd.NA,
        "Activity": "1111",
    }.items():
        risk[column] = value
    return SearchCatalog(
        revision=3,
        risk_dates={"ir/delta": pd.Timestamp("2026-08-13")},
        market_date=pd.Timestamp("2026-08-14"),
        market_frame=market,
        risk_pivot_frame=risk,
    )


def test_search_catalog_retains_portfolio_but_risk_dashboard_rejects_it() -> None:
    catalog = _quick_catalog()
    kwargs = {
        "index_columns": ("Portfolio",),
        "risk_filters": {"Split": ["Risk"], "Portfolio": ["BOOK-A"]},
    }

    included = catalog.pivot_combined_hierarchy(
        "IR | Delta | USD-SOFR",
        **kwargs,
    ).frame
    excluded = catalog.pivot_combined_hierarchy(
        "IR | Delta | USD-SOFR",
        exclude_selected=True,
        **kwargs,
    ).frame
    prepared = prepare_risk_data(_raw_risk_frame())
    with pytest.raises(ValueError, match="Unknown reporting-dimension"):
        apply_filters(
            prepared,
            ["IR"],
            ["Risk"],
            {"portfolio": ["BOOK-A"]},
        )
    dashboard = apply_filters(prepared, ["IR"], ["Risk"], {})

    assert included[["Portfolio", "Risk"]].values.tolist() == [["BOOK-A", 10.0]]
    assert excluded[["Portfolio", "Risk"]].values.tolist() == [["BOOK-B", 20.0]]
    assert dashboard["portfolio"].tolist() == ["BOOK-A", "BOOK-B"]
    assert dashboard["risk"].sum() == 30.0


def test_quick_risk_helper_forwards_exclusion_and_action_tokens_bind_the_mode() -> None:
    class Manager:
        def __init__(self) -> None:
            self.exclude_values: list[bool] = []

        def pivot_combined_hierarchy(
            self,
            _identity: str,
            *,
            index_columns,
            leaf_limit: int,
            identity_mode: str,
            risk_filters,
            exclude_selected: bool,
        ) -> SimpleNamespace:
            assert leaf_limit > 0
            assert identity_mode == "reported"
            assert risk_filters == {"Portfolio": ["BOOK-A"]}
            self.exclude_values.append(exclude_selected)
            return SimpleNamespace(
                frame=pd.DataFrame(
                    [
                        {
                            "__Hierarchy Depth__": 1,
                            "Portfolio": "BOOK-B",
                            "Risk": 20.0,
                            "dRisk": 2.0,
                            "PL": 6.0,
                            "Open": pd.NA,
                            "Current": pd.NA,
                            "Move": pd.NA,
                        }
                    ]
                ),
                total=1,
                revision=9,
            )

    manager = Manager()
    rendered, index_update = _render_quick_search_pivot(
        manager,
        combine_udl="IR | Delta | USD-SOFR",
        index_columns=("Portfolio",),
        is_open=True,
        risk_filters={"Portfolio": ["BOOK-A"]},
        exclude_selected=True,
    )
    include_token = _top_book_action_view_token(
        9,
        dimension_filters={"portfolio": ["BOOK-A"]},
    )
    exclude_token = _top_book_action_view_token(
        9,
        dimension_filters={"portfolio": ["BOOK-A"]},
        exclude_selected=True,
    )

    assert isinstance(rendered, html.Div)
    assert index_update is not None
    assert manager.exclude_values == [True]
    assert include_token != exclude_token
    assert json.loads(exclude_token)["exclude_selected"] is True
