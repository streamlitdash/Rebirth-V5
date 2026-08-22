"""Focused native Data handoff, lazy query, and playback tests."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from dash import no_update

from rebirth.history import repository as history_module
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
from rebirth.domain.search import ResolvedHistoryIdentity
from rebirth.services.sources import build_production_refresh_manager
from rebirth.pages.data.callbacks import (
    load_archive_catalog,
    poll_archive_generation,
    query_history_bundle,
    serialize_history_bundle,
)
from rebirth.pages.data.selection import (
    catalog_key_for_handoff,
    direct_history_handoff,
    risk_greek_options,
    risk_type_options,
    underlying_options,
)
from rebirth.pages.data.view import build_data_page
from rebirth.pages.risk.handoff import build_history_handoff
from rebirth.ui.constants import FILTER_DIMENSION_FIELDS
from rebirth.app.factory import build_app


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
    assert payload == {
        "generation": "generation-a",
        "risk_count": 1,
        "market_count": 1,
    }
    assert "1 Risk and 1 Market" in status
    assert set(payload) == {"generation", "risk_count", "market_count"}


def test_query_reads_once_and_rejects_a_stale_reset_before_read() -> None:
    bundle = _bundle()
    repository = _Repository(bundle)
    payload, raw_rows, raw_columns, status = query_history_bundle(
        repository,
        bundle.query.handoff.to_mapping(),
        "risk",
        "all",
        None,
        None,
        {"generation": "generation-a", "reset_generation": 3},
        3,
    )

    assert len(repository.calls) == 1
    assert payload is not None
    assert "raw_rows" not in payload
    assert "raw_columns" not in payload
    assert len(raw_rows) == 4
    assert raw_columns[-1]["id"] == "Portfolio"
    assert "2 dates" in status

    with pytest.raises(HistoryValidationError, match="predates Clear Cache"):
        query_history_bundle(
            repository,
            bundle.query.handoff.to_mapping(),
            "risk",
            "all",
            None,
            None,
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
        ("data-raw-table", "data"),
        ("data-raw-table", "columns"),
        ("data-player-visibility-store", "data"),
    } <= input_ids
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
        Path(__file__).resolve().parents[1] / "assets" / "10_data_playback.js"
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
        "record[dateColumn]",
        "document.hidden",
        '"data-history-chart", String(bundle.key || "")',
        "selectedProjection, selectedSlice, selectedA, selectedB",
        "if (changedIdentity)",
        "playing = false",
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
    request = _callback_metadata(app, "data-history-request-store", "data")
    request_inputs = {(item["id"], item["property"]) for item in request["inputs"]}
    assert {
        ("data-history-handoff-store", "data"),
        ("data-load-history-button", "n_clicks"),
        ("data-unlock-identity-button", "n_clicks"),
        ("data-history-kind-tabs", "value"),
    } <= request_inputs

    load = _callback_metadata(app, "data-history-bundle-store", "data")
    load_inputs = {(item["id"], item["property"]) for item in load["inputs"]}
    assert ("data-history-request-store", "data") in load_inputs
    assert ("data-history-handoff-store", "data") not in load_inputs
    assert {
        ("data-history-projection", "value"),
        ("data-history-slice", "value"),
        ("data-history-date-a", "value"),
        ("data-history-date-b", "value"),
        ("data-player-slider", "value"),
    }.isdisjoint(load_inputs)


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

    assert {"data-route-location", "data-history-handoff-store"} <= root_ids
    assert handoff_store.storage_type == "session"
    assert _callback_for_output(app, "data-history-bundle-store", "data")
    assert _callback_for_output(app, "data-history-handoff-store", "data")

    page = build_data_page(
        cube_href="/proxy/",
        pnl_href="/proxy/pnl",
        stock_href="/proxy/stock",
    )
    page_ids = {getattr(component, "id", None) for component in _walk(page)}
    hrefs = {
        getattr(component, "href", None)
        for component in _walk(page)
        if getattr(component, "href", None)
    }
    assert {
        "data-page",
        "data-history-kind-tabs",
        "data-risk-type",
        "data-risk-greek",
        "data-underlying",
        "data-load-history-button",
        "data-unlock-identity-button",
        "data-history-chart",
        "data-history-projection",
        "data-history-slice",
        "data-history-date-a",
        "data-history-date-b",
        "data-selected-table",
        "data-raw-table",
        "data-player-visibility-store",
    } <= page_ids
    assert {"/proxy/", "/proxy/pnl", "/proxy/stock"} <= hrefs
