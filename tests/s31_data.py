"""Focused native Data handoff, lazy query, and playback tests."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import dcc, no_update

from rebirth.history import s06_repository as history_module
from rebirth.history import (
    HISTORY_CANONICAL_CELL_BUDGET,
    HISTORY_HANDOFF_SCHEMA_VERSION,
    HISTORY_RAW_ROW_BUDGET,
    ORDERED,
    ArchiveHistoryRepository,
    HistoryCatalogEntry,
    HistoryAxisOrder,
    HistoryBundle,
    HistoryHandoff,
    HistoryIdentity,
    HistoryIdentityCatalog,
    HistoryOrdering,
    HistoryQuery,
    HistoryValidationError,
    RiskFilterView,
)
from rebirth.domain.s10_search import ResolvedHistoryIdentity
from rebirth.services.s05_sources import build_production_refresh_manager
from rebirth.pages.data.s03_callbacks import (
    history_request_payload,
    load_archive_catalog,
    poll_archive_generation,
    query_history_bundle,
    serialize_history_bundle,
)
from rebirth.pages.data import s03_callbacks as data_callbacks_module
from rebirth.pages.risk import s04_handoff as handoff_callbacks_module
from rebirth.pages.data.s01_selection import (
    catalog_key_for_handoff,
    direct_history_handoff,
    risk_greek_options,
    risk_type_options,
    underlying_options,
)
from rebirth.pages.data.s02_view import build_data_page
from rebirth.pages.risk.s04_handoff import _handoff_payload, build_history_handoff
from rebirth.ui.s01_constants import DIMENSION_FILTER_IDS, FILTER_DIMENSION_FIELDS
from rebirth.app.s07_factory import build_app


def _walk(component: object) -> Iterable[object]:
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None:
        yield from _walk(children)


def _callback_metadata(app, component_id: str, component_property: str):
    for metadata in app.callback_map.values():
        output = metadata["output"]
        outputs = list(output) if isinstance(output, (list, tuple)) else [output]
        if any(
            item.component_id == component_id
            and item.component_property == component_property
            for item in outputs
        ):
            return metadata
    raise AssertionError(f"No callback owns {component_id}.{component_property}")


def _callback_for_output(app, component_id: str, component_property: str):
    return _callback_metadata(app, component_id, component_property)[
        "callback"
    ].__wrapped__


def _handoff(source_type: str, *, reset: int = 3) -> HistoryHandoff:
    specs = {
        "fx/delta": ("FX", "Delta"),
        "ir/delta": ("IR", "Delta"),
        "ir/deltavega": ("IR", "DeltaVega"),
    }
    risk_type, risk_greek = specs[source_type]
    return HistoryHandoff(
        schema_version=HISTORY_HANDOFF_SCHEMA_VERSION,
        kind="risk",
        identity=HistoryIdentity(
            source_types=(source_type,),
            risk_type=risk_type,
            risk_greek=risk_greek,
            underlying="EUR",
        ),
        metric="risk",
        source_revision=11,
        snapshot_date=date(2026, 8, 21),
        filter_view=RiskFilterView(),
        reset_generation=reset,
    )


def test_quick_handoff_nonce_is_unique_after_a_risk_page_remount() -> None:
    handoff = _handoff("ir/delta")
    first = _handoff_payload(handoff, "risk")
    second = _handoff_payload(handoff, "risk")

    assert first["handoff"] == second["handoff"] == handoff.to_mapping()
    assert first["nonce"] != second["nonce"]
    assert str(first["nonce"]).startswith(f"risk-{handoff.source_revision}-")


def test_quick_identity_change_clears_a_stale_open_in_data_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    callback = _callback_for_output(app, "data-history-handoff-store", "data")
    metadata = _callback_metadata(app, "data-history-handoff-store", "data")
    states = {(item["id"], item["property"]) for item in metadata["state"]}
    assert ("dimension-filter-values-store", "data") in states
    assert ("risk-filter-exclude-applied-store", "data") in states
    assert ("risk-filter-exclude-selected", "value") not in states
    assert (
        not {(component_id, "value") for component_id in DIMENSION_FILTER_IDS.values()}
        & states
    )
    monkeypatch.setattr(
        handoff_callbacks_module,
        "ctx",
        SimpleNamespace(triggered_id="quick-search-combine-udl"),
    )

    result = callback(
        0,
        0,
        "selected-risk",
        None,
        [],
        [[] for _field in FILTER_DIMENSION_FIELDS],
        [],
        0,
    )

    assert result == (no_update, no_update, "", no_update)


def _bundle(source_type: str = "ir/delta") -> HistoryBundle:
    handoff = _handoff(source_type)
    query = HistoryQuery(handoff, period="all")
    dates = (date(2026, 8, 20), date(2026, 8, 21))
    if source_type == "fx/delta":
        axes = ()
        values = pd.DataFrame(
            {
                "Risk Date": ["2026-08-20", "2026-08-21"],
                "Risk": [10.0, 12.0],
            }
        )
    elif source_type == "ir/delta":
        axes = (
            HistoryAxisOrder(
                "Tenor Swap",
                "Tenor Swap Order",
                ("1Y", "5Y"),
                (1, 2),
                ORDERED,
            ),
        )
        values = pd.DataFrame(
            {
                "Risk Date": [
                    "2026-08-20",
                    "2026-08-20",
                    "2026-08-21",
                    "2026-08-21",
                ],
                "Tenor Swap": ["1Y", "5Y", "1Y", "5Y"],
                "Tenor Swap Order": [1, 2, 1, 2],
                "Risk": [1.0, None, 3.0, 4.0],
            }
        )
    else:
        axes = (
            HistoryAxisOrder(
                "Tenor Swap",
                "Tenor Swap Order",
                ("1Y", "5Y"),
                (1, 2),
                ORDERED,
            ),
            HistoryAxisOrder(
                "Tenor Option",
                "Tenor Option Order",
                ("1M", "6M"),
                (1, 2),
                ORDERED,
            ),
        )
        rows = []
        for selected_date in ("2026-08-20", "2026-08-21"):
            for swap_order, swap in enumerate(("1Y", "5Y"), 1):
                for option_order, option in enumerate(("1M", "6M"), 1):
                    rows.append(
                        {
                            "Risk Date": selected_date,
                            "Tenor Swap": swap,
                            "Tenor Swap Order": swap_order,
                            "Tenor Option": option,
                            "Tenor Option Order": option_order,
                            "Risk": float(swap_order * 10 + option_order),
                        }
                    )
        values = pd.DataFrame(rows)
    raw = values.copy()
    raw["Portfolio"] = "BOOK-A"
    selected = raw.loc[raw["Risk Date"].eq("2026-08-21")]
    return HistoryBundle(
        query=query,
        date_column="Risk Date",
        dates=dates,
        resolved_start=dates[0],
        resolved_end=dates[-1],
        selected_date=dates[-1],
        metric_column="Risk",
        ordering=HistoryOrdering(axes=axes, status=ORDERED),
        values=values,
        selected_rows=selected,
        raw_rows=raw,
        generation="generation-a",
    )


class _Resolver:
    def __init__(self, resolved: ResolvedHistoryIdentity):
        self.resolved = resolved
        self.calls: list[tuple[str, str, str]] = []

    def resolve_history_identity(self, kind, combine_udl, *, identity_mode):
        self.calls.append((kind, combine_udl, identity_mode))
        return replace(self.resolved, kind=kind, identity_mode=identity_mode)


class _Repository:
    def __init__(self, bundle: HistoryBundle):
        self.bundle = bundle
        self.calls: list[HistoryQuery] = []

    def read(self, query: HistoryQuery) -> HistoryBundle:
        self.calls.append(query)
        return replace(self.bundle, query=query)


def _catalog() -> HistoryIdentityCatalog:
    return HistoryIdentityCatalog(
        generation="generation-a",
        entries=(
            HistoryCatalogEntry(
                kind="risk",
                identity=HistoryIdentity(
                    source_types=("ir/delta", "ir/gamma"),
                    risk_type="IR",
                    risk_greek="Delta",
                    underlying="EUR",
                    identity_mode="reported",
                ),
                source_revision=11,
                snapshot_date=date(2026, 8, 21),
            ),
            HistoryCatalogEntry(
                kind="market",
                identity=HistoryIdentity(
                    source_types=("ir/delta",),
                    risk_type="IR",
                    risk_greek="Delta",
                    underlying="EUR",
                    identity_mode="underlying",
                ),
                source_revision=11,
                snapshot_date=date(2026, 8, 21),
            ),
        ),
    )


def test_quick_handoff_uses_catalog_identity_and_active_filter_view() -> None:
    resolved = ResolvedHistoryIdentity(
        kind="risk",
        source_types=("ir/delta",),
        risk_type="IR",
        risk_greek="Delta",
        underlying="EUR",
        identity_mode="reported",
        source_revision=11,
        snapshot_date=pd.Timestamp("2026-08-21"),
    )
    manager = _Resolver(resolved)
    dimension_values = [[f"VALUE-{index}"] for index in range(5)]

    handoff = build_history_handoff(
        manager,
        kind="risk",
        combine_udl="IR | Delta | EUR DISPLAY LABEL",
        identity_mode="reported",
        reset_generation=3,
        selected_splits=["Risk", "Gamma"],
        dimension_values=dimension_values,
        exclude_value=["exclude"],
    )

    assert manager.calls == [("risk", "IR | Delta | EUR DISPLAY LABEL", "reported")]
    assert handoff.metric == "risk"
    assert handoff.filter_view is not None
    filters = dict(handoff.filter_view.filters)
    assert filters["Split"] == ("Risk", "Gamma")
    assert filters[FILTER_DIMENSION_FIELDS[0].external_name] == ("VALUE-0",)
    assert handoff.filter_view.exclude_selected is True
    assert HistoryHandoff.from_mapping(handoff.to_mapping()) == handoff

    market = build_history_handoff(
        manager,
        kind="market",
        combine_udl="IR | Delta | EUR MARKET LABEL",
        identity_mode="underlying",
        reset_generation=3,
    )
    assert manager.calls[-1] == (
        "market",
        "IR | Delta | EUR MARKET LABEL",
        "underlying",
    )
    assert market.metric == "current"
    assert market.filter_view is None


def test_real_fx_quick_handoff_resolves_and_loads_checked_in_history() -> None:
    manager = build_production_refresh_manager(stage_delays={"risk_product": 0.0})
    manager.refresh(
        force_risk=True,
        reason="quick-history-integration",
        copy_result=False,
    )
    selected = "FX | Delta | FAKE_REPLACE_ME - G10 FX"
    assert selected in manager.combine_udl_options(identity_mode="reported")
    handoff = build_history_handoff(
        manager,
        kind="risk",
        combine_udl=selected,
        identity_mode="reported",
        reset_generation=0,
        dimension_values=[[] for _field in FILTER_DIMENSION_FIELDS],
    )
    assert handoff.identity.source_types == ("fx/delta", "fx/gamma")
    assert handoff.identity.underlying == "FAKE_REPLACE_ME - G10 FX"

    history_root = Path(__file__).resolve().parents[1] / "data" / "histo"
    repository = ArchiveHistoryRepository(history_root)
    catalog = repository.catalog()
    entry_key = catalog_key_for_handoff(catalog.to_mapping(), handoff.to_mapping())
    assert entry_key is not None
    assert (
        direct_history_handoff(
            catalog.to_mapping(),
            entry_key,
            kind="risk",
            reset_generation=0,
        ).identity
        == handoff.identity
    )

    request = history_request_payload(
        handoff,
        period="custom",
        start_date="2026-08-21",
        end_date="2026-08-21",
    )
    payload, status = query_history_bundle(
        repository,
        request,
        {"generation": repository.generation(), "reset_generation": 0},
        0,
    )

    assert payload is not None
    assert payload["dates"] == ["2026-08-21"]
    assert payload["values"]
    assert payload["handoff"]["identity"]["underlying"] == ("FAKE_REPLACE_ME - G10 FX")
    assert "Loaded 1 dates" in status


def test_direct_selectors_build_the_same_strict_handoff_contract() -> None:
    catalog = _catalog()
    raw_catalog = catalog.to_mapping()
    risk_entry = catalog.entries[0]

    assert risk_type_options(raw_catalog, "risk", "reported") == [
        {"label": "IR", "value": "IR"}
    ]
    assert risk_greek_options(raw_catalog, "risk", "reported", "IR") == [
        {"label": "Delta", "value": "Delta"}
    ]
    assert underlying_options(
        raw_catalog,
        "risk",
        "reported",
        "IR",
        "Delta",
    ) == [{"label": "EUR", "value": risk_entry.key}]

    handoff = direct_history_handoff(
        raw_catalog,
        risk_entry.key,
        kind="risk",
        reset_generation=7,
    )

    assert isinstance(handoff, HistoryHandoff)
    assert handoff.identity.source_types == ("ir/delta", "ir/gamma")
    assert handoff.metric == "risk"
    assert handoff.filter_view is None
    assert handoff.reset_generation == 7
    assert HistoryHandoff.from_mapping(handoff.to_mapping()) == handoff
    assert catalog_key_for_handoff(raw_catalog, handoff.to_mapping()) == risk_entry.key


def test_catalog_loading_is_bounded_to_identity_metadata() -> None:
    catalog = _catalog()

    class CatalogRepository:
        def __init__(self):
            self.calls = 0

        def catalog(self):
            self.calls += 1
            return catalog

    repository = CatalogRepository()
    payload, status = load_archive_catalog(
        repository,
        {"generation": "generation-a", "reset_generation": 0},
    )

    assert repository.calls == 1
    assert payload == catalog.to_mapping()
    assert "1 Risk and 1 Market" in status
    assert set(payload) == {"generation", "entries"}
    assert all("Risk" not in entry for entry in payload["entries"])


def test_query_reads_once_and_rejects_a_stale_reset_before_read() -> None:
    bundle = _bundle()
    repository = _Repository(bundle)
    request = history_request_payload(bundle.query.handoff, period="all")
    payload, status = query_history_bundle(
        repository,
        request,
        {"generation": "generation-a", "reset_generation": 3},
        3,
    )

    assert len(repository.calls) == 1

    with pytest.raises(HistoryValidationError, match="Select an exact identity"):
        query_history_bundle(
            repository,
            {"error": "Select an exact identity before loading history."},
            {"generation": "generation-a", "reset_generation": 3},
            3,
        )
    assert len(repository.calls) == 1
    assert payload is not None
    assert "raw_rows" not in payload
    assert "raw_columns" not in payload
    assert "2 dates" in status

    with pytest.raises(HistoryValidationError, match="predates Clear Cache"):
        query_history_bundle(
            repository,
            request,
            {"generation": "generation-a", "reset_generation": 4},
            4,
        )
    assert len(repository.calls) == 1


@pytest.mark.parametrize(
    ("source_type", "axis_count"),
    [
        ("fx/delta", 0),
        ("ir/delta", 1),
        ("ir/deltavega", 2),
    ],
)
def test_product_axes_own_the_bounded_clientside_payload(
    source_type,
    axis_count,
) -> None:
    payload = serialize_history_bundle(_bundle(source_type))
    assert len(payload["axes"]) == axis_count
    assert payload["uirevision"].startswith("data-history-")
    assert "raw_rows" not in payload
    assert "raw_columns" not in payload
    if source_type == "ir/delta":
        assert any(row["Risk"] is None for row in payload["values"])


def test_fixed_data_series_and_official_market_label() -> None:
    risk_request = history_request_payload(
        replace(_handoff("ir/delta"), metric="pl"),
    )
    risk_handoff = HistoryHandoff.from_mapping(risk_request["handoff"])
    assert risk_handoff.metric == "risk"

    risk_bundle = _bundle("fx/delta")
    market_identity = replace(
        risk_bundle.query.handoff.identity,
        identity_mode="underlying",
    )
    market_handoff = replace(
        risk_bundle.query.handoff,
        kind="market",
        identity=market_identity,
        metric="open",
        filter_view=None,
    )
    market_request = history_request_payload(market_handoff)
    canonical_market_handoff = HistoryHandoff.from_mapping(market_request["handoff"])
    assert canonical_market_handoff.metric == "current"

    market_query = HistoryQuery(canonical_market_handoff, period="all")
    market_values = risk_bundle.values.rename(
        columns={"Risk Date": "Market Date", "Risk": "Current"}
    )
    market_raw = risk_bundle.raw_rows.rename(
        columns={"Risk Date": "Market Date", "Risk": "Current"}
    )
    payload = serialize_history_bundle(
        replace(
            risk_bundle,
            query=market_query,
            date_column="Market Date",
            metric_column="Current",
            values=market_values,
            raw_rows=market_raw,
        )
    )
    assert payload["metric_column"] == "Official"
    assert all("Official" in row and "Current" not in row for row in payload["values"])


def test_browser_payload_budgets_fail_without_silent_truncation() -> None:
    bundle = _bundle("ir/delta")
    raw = pd.concat(
        [bundle.raw_rows] * ((HISTORY_RAW_ROW_BUDGET // len(bundle.raw_rows)) + 1),
        ignore_index=True,
    ).iloc[: HISTORY_RAW_ROW_BUDGET + 1]
    with pytest.raises(HistoryValidationError, match="narrower period"):
        serialize_history_bundle(replace(bundle, raw_rows=raw))

    values = pd.concat(
        [bundle.values] * ((HISTORY_CANONICAL_CELL_BUDGET // len(bundle.values)) + 1),
        ignore_index=True,
    ).iloc[: HISTORY_CANONICAL_CELL_BUDGET + 1]
    with pytest.raises(HistoryValidationError, match="exact identity"):
        serialize_history_bundle(replace(bundle, values=values))


def test_reset_generation_clears_process_cache_once_thread_safely(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def counted_clear() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(history_module, "clear_archive_caches", counted_clear)
    monkeypatch.setattr(
        ArchiveHistoryRepository,
        "_cleared_reset_generations",
        {},
    )
    repositories = [ArchiveHistoryRepository(tmp_path) for _index in range(8)]
    assert repositories[0].clear_for_reset_generation(0) is False
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda repository: repository.clear_for_reset_generation(7),
                repositories,
            )
        )
    assert results.count(True) == 1
    assert calls == 1
    assert repositories[0].clear_for_reset_generation(6) is False
    assert repositories[0].clear_for_reset_generation(8) is True
    assert calls == 2


def test_reset_generation_is_tracked_per_archive_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def counted_clear() -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(history_module, "clear_archive_caches", counted_clear)
    monkeypatch.setattr(
        ArchiveHistoryRepository,
        "_cleared_reset_generations",
        {},
    )
    first = ArchiveHistoryRepository(tmp_path / "first")
    second = ArchiveHistoryRepository(tmp_path / "second")

    assert first.clear_for_reset_generation(1) is True
    assert first.clear_for_reset_generation(1) is False
    assert second.clear_for_reset_generation(1) is True
    assert second.clear_for_reset_generation(1) is False
    assert calls == 2


def test_unchanged_generation_poll_is_no_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ArchiveHistoryRepository(tmp_path)
    generation_calls = 0

    def generation() -> str:
        nonlocal generation_calls
        generation_calls += 1
        return "generation-a"

    monkeypatch.setattr(repository, "generation", generation)
    monkeypatch.setattr(
        repository,
        "clear_for_reset_generation",
        lambda reset: False,
    )
    state, status = poll_archive_generation(
        repository,
        _bundle().query.handoff.to_mapping(),
        {"generation": "generation-a", "reset_generation": 3},
        3,
    )
    assert state is no_update
    assert status == ""
    assert generation_calls == 1


def test_direct_data_route_initializes_generation_without_a_quick_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = ArchiveHistoryRepository(tmp_path)
    monkeypatch.setattr(repository, "generation", lambda: "generation-direct")
    monkeypatch.setattr(repository, "clear_for_reset_generation", lambda _reset: False)

    state, status = poll_archive_generation(
        repository,
        None,
        {"generation": None, "reset_generation": None},
        0,
    )

    assert state == {"generation": "generation-direct", "reset_generation": 0}
    assert status == ""


def test_playback_and_selected_date_filter_are_clientside() -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    metadata = _callback_metadata(app, "data-history-chart", "figure")
    input_ids = {(item["id"], item["property"]) for item in metadata["inputs"]}
    output = metadata["output"]
    outputs = list(output) if isinstance(output, (list, tuple)) else [output]

    assert "callback" not in metadata
    assert {
        ("data-history-bundle-store", "data"),
        ("data-history-projection", "value"),
        ("data-history-slice", "value"),
        ("data-history-date-a", "value"),
        ("data-history-date-b", "value"),
        ("data-player-interval", "n_intervals"),
        ("data-player-visibility-store", "data"),
    } <= input_ids
    assert ("data-raw-table", "data") not in input_ids
    assert ("data-raw-table", "columns") not in input_ids
    assert all(item.component_id.startswith("data-") for item in outputs)

    base = _callback_metadata(app, "data-history-projection", "options")
    assert "callback" not in base
    assert {(item["id"], item["property"]) for item in base["inputs"]} == {
        ("data-history-bundle-store", "data")
    }
    slices = _callback_metadata(app, "data-history-slice", "options")
    assert "callback" not in slices
    assert {(item["id"], item["property"]) for item in slices["inputs"]} == {
        ("data-history-bundle-store", "data"),
        ("data-history-projection", "value"),
    }

    source = (
        Path(__file__).resolve().parents[1] / "assets" / "s09_playback.js"
    ).read_text(encoding="utf-8")
    for projection in (
        "zero_timeline",
        "one_surface",
        "one_tenor",
        "one_compare",
        "two_surface",
        "two_swap",
        "two_option",
        "two_compare",
    ):
        assert projection in source
    for behavior in (
        "dataProjectionBase",
        "dataProjectionSlice",
        "dataHistoryBounds",
        "dataDifference",
        "const records = Array.isArray(bundle.values)",
        "Object.keys(records[0] || {})",
        "record[dateColumn]",
        "document.hidden",
        '"data-history-chart", String(bundle.key || "")',
        "selectedProjection, selectedSlice, selectedA, selectedB",
        "if (changedIdentity)",
        "playing = false",
        'playing ? "Playing" : "Static"',
        'const SUM_SLICE = "__sum__"',
        "dataNullSafeSum",
        "values: [SUM_SLICE, ...dataLabels(axes[1])]",
        "values: [SUM_SLICE, ...dataLabels(axes[0])]",
        "const hasPlayer = dates.length > 1 && !compare",
        'setProps("data-player-slider", { value: next })',
        "const direction = event.deltaY > 0 ? 1",
        "connectgaps: false",
        'categoryorder: "array"',
        "camera: CAMERA",
        "cmin: bounds[0], cmax: bounds[1]",
        "uirevision: playerKey",
        'scene: "scene2"',
        'scene: "scene3"',
    ):
        assert behavior in source


def test_data_callbacks_use_one_effective_request_for_quick_and_direct_paths() -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    show_custom = _callback_for_output(app, "data-custom-range-control", "hidden")
    assert show_custom("custom") is False
    assert all(
        show_custom(period) is True
        for period in ("wtd", "mtd", "ytd", "1y", "5y", "all")
    )
    choose_underlying = _callback_for_output(app, "data-underlying", "options")
    assert choose_underlying(
        None,
        "risk",
        "reported",
        None,
        None,
        None,
        None,
        None,
        None,
    ) == ([], None, True)
    options, selected, disabled = choose_underlying(
        _catalog().to_mapping(),
        "risk",
        "reported",
        "IR",
        "Delta",
        None,
        None,
        None,
        None,
    )
    assert options
    assert selected is not None
    assert disabled is False

    request = _callback_metadata(app, "data-history-request-store", "data")
    request_inputs = {(item["id"], item["property"]) for item in request["inputs"]}
    assert {
        ("data-history-handoff-store", "data"),
        ("data-load-history-button", "n_clicks"),
        ("reset-generation-store", "data"),
    } <= request_inputs
    load_input = next(
        item for item in request["inputs"] if item["id"] == "data-load-history-button"
    )
    assert load_input.get("allow_optional") is True
    assert ("data-unlock-identity-button", "n_clicks") not in request_inputs
    assert ("data-history-kind-tabs", "value") not in request_inputs

    load = _callback_metadata(app, "data-history-bundle-store", "data")
    load_inputs = {(item["id"], item["property"]) for item in load["inputs"]}
    assert load_inputs == {
        ("data-history-request-store", "data"),
        ("data-history-cache-state-store", "data"),
        ("reset-generation-store", "data"),
    }
    assert ("data-history-handoff-store", "data") not in load_inputs
    assert {
        ("data-history-projection", "value"),
        ("data-history-slice", "value"),
        ("data-history-date-a", "value"),
        ("data-history-date-b", "value"),
        ("data-player-slider", "value"),
    }.isdisjoint(load_inputs)

    registration = next(
        item
        for item in app._callback_list
        if "data-history-bundle-store.data" in item["output"]
    )
    assert "data-load-history-button.disabled" not in registration["running"]["running"]
    assert (
        registration["running"]["running"]["data-load-history-button.children"]
        == "Loading history…"
    )


def test_quick_handoff_prefills_controls_while_full_catalogue_remains_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    handoff = _handoff("ir/delta")
    stored_handoff = {
        "handoff": handoff.to_mapping(),
        "nonce": "risk-2-11",
    }
    catalog_calls = 0

    def read_catalog(_repository):
        nonlocal catalog_calls
        catalog_calls += 1
        return _catalog()

    sync = _callback_for_output(app, "data-history-kind-tabs", "value")
    assert sync(stored_handoff, None, None) == "risk"
    assert sync(stored_handoff, None, "risk-2-11") is no_update
    identity = _callback_for_output(app, "data-identity-mode", "value")
    assert identity("risk", stored_handoff, None, None) == (
        "underlying",
        False,
    )
    assert identity("market", None, None, None) == (
        "underlying",
        True,
    )

    monkeypatch.setattr(
        ArchiveHistoryRepository,
        "catalog",
        read_catalog,
    )
    monkeypatch.setattr(
        data_callbacks_module,
        "ctx",
        SimpleNamespace(triggered_id="data-history-handoff-store"),
    )
    request = _callback_for_output(app, "data-history-request-store", "data")
    monkeypatch.setattr(
        data_callbacks_module,
        "ctx",
        SimpleNamespace(triggered_id="data-load-history-button"),
    )
    mounted_payload, mounted_consumed = request(
        stored_handoff,
        0,
        3,
        "risk",
        None,
        None,
        "all",
        None,
        None,
        None,
        None,
    )
    assert "error" not in mounted_payload
    assert mounted_consumed == "risk-2-11"
    assert sync(stored_handoff, mounted_payload, mounted_consumed) == "risk"

    monkeypatch.setattr(
        data_callbacks_module,
        "ctx",
        SimpleNamespace(triggered_id=None),
    )
    assert request(
        None,
        0,
        3,
        "risk",
        None,
        None,
        "all",
        None,
        None,
        None,
        None,
    ) == (no_update, no_update)

    monkeypatch.setattr(
        data_callbacks_module,
        "ctx",
        SimpleNamespace(triggered_id="data-load-history-button"),
    )
    assert request(
        None,
        0,
        3,
        "risk",
        None,
        None,
        "all",
        None,
        None,
        None,
        None,
    ) == (no_update, no_update)

    monkeypatch.setattr(
        data_callbacks_module,
        "ctx",
        SimpleNamespace(triggered_id="data-history-handoff-store"),
    )
    payload, consumed = request(
        stored_handoff,
        0,
        3,
        "risk",
        None,
        None,
        "all",
        None,
        None,
        None,
        None,
    )
    assert HistoryHandoff.from_mapping(payload["handoff"]) == handoff
    assert consumed == "risk-2-11"

    monkeypatch.setattr(
        data_callbacks_module,
        "ctx",
        SimpleNamespace(triggered_id="reset-generation-store"),
    )
    assert request(
        None,
        0,
        4,
        "risk",
        None,
        None,
        "all",
        None,
        None,
        None,
        None,
    ) == (no_update, no_update)

    refresh_catalogue = _callback_for_output(
        app,
        "data-history-catalog-store",
        "data",
    )
    catalog_payload, catalog_status = refresh_catalogue(
        {"generation": "generation-a", "reset_generation": 3},
        None,
    )
    assert catalog_payload == _catalog().to_mapping()
    assert "Archive ready" in catalog_status
    assert catalog_calls == 1

    callback_outputs = "\n".join(
        str(metadata["output"]) for metadata in app.callback_map.values()
    )
    assert "data-risk-type.disabled" not in callback_outputs
    assert "data-risk-greek.disabled" not in callback_outputs
    assert "data-underlying.disabled" not in callback_outputs

    slider = next(
        component
        for component in _walk(build_data_page())
        if getattr(component, "id", None) == "data-player-slider"
    )
    assert slider.updatemode == "drag"

    monkeypatch.setattr(
        data_callbacks_module,
        "ctx",
        SimpleNamespace(triggered_id="data-history-handoff-store"),
    )
    repeated = request(
        stored_handoff,
        0,
        3,
        "risk",
        None,
        None,
        "all",
        None,
        None,
        payload,
        consumed,
    )
    assert repeated == (no_update, no_update)


def test_data_route_and_factory_layout_are_archive_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args, **_kwargs):
        raise AssertionError("archive I/O occurred during layout construction")

    monkeypatch.setattr(ArchiveHistoryRepository, "read", forbidden)
    monkeypatch.setattr(ArchiveHistoryRepository, "generation", forbidden)
    monkeypatch.setattr(ArchiveHistoryRepository, "catalog", forbidden)
    app = build_app(refresh_manager=build_production_refresh_manager())
    root = app.layout() if callable(app.layout) else app.layout
    root_components = list(_walk(root))
    root_ids = {getattr(component, "id", None) for component in root_components}
    handoff_store = next(
        component
        for component in root_components
        if getattr(component, "id", None) == "data-history-handoff-store"
    )

    assert {
        "data-route-location",
        "data-history-handoff-store",
        "data-history-handoff-consumed-store",
        "data-history-request-store",
    } <= root_ids
    assert handoff_store.storage_type == "session"
    assert _callback_for_output(app, "data-history-bundle-store", "data")
    assert _callback_for_output(app, "data-history-handoff-store", "data")

    page = build_data_page(
        cube_href="/proxy/",
        pnl_href="/proxy/pnl",
        stock_href="/proxy/stock",
    )
    page_ids = {getattr(component, "id", None) for component in _walk(page)}
    identity_mode = next(
        component
        for component in _walk(page)
        if getattr(component, "id", None) == "data-identity-mode"
    )
    period = next(
        component
        for component in _walk(page)
        if getattr(component, "id", None) == "data-period"
    )
    load_button = next(
        component
        for component in _walk(page)
        if getattr(component, "id", None) == "data-load-history-button"
    )
    assert {
        "data-page",
        "data-history-kind-tabs",
        "data-risk-type",
        "data-risk-greek",
        "data-underlying",
        "data-load-history-button",
        "data-history-chart",
        "data-history-projection",
        "data-history-slice",
        "data-history-date-a",
        "data-history-date-b",
        "data-selected-table",
        "data-player-visibility-store",
    } <= page_ids
    assert load_button.disabled is True
    assert isinstance(identity_mode, dcc.Dropdown)
    assert [option["value"] for option in identity_mode.options] == [
        "reported",
        "underlying",
    ]
    assert isinstance(period, dcc.RadioItems)
    assert [option["value"] for option in period.options] == [
        "wtd",
        "mtd",
        "ytd",
        "1y",
        "5y",
        "all",
        "custom",
    ]
    assert "data-period-segmented" in str(period.className).split()
    assert "data-metric" not in page_ids
    assert "data-history-request-store" not in page_ids
    assert "data-unlock-identity-button" not in page_ids
    assert "data-history-lock-store" not in page_ids
    assert "data-raw-table" not in page_ids
    assert not {
        getattr(component, "href", None)
        for component in _walk(page)
        if getattr(component, "href", None)
    }
