"""Page-local saved filter-view storage and component contracts."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import Dash, dcc, html, no_update

from cube.services.s04_savedviews import (
    SHARED_SAVED_VIEW_SCOPE,
    SavedFilterViewRepository,
    SavedViewConflictError,
    SavedViewValidationError,
)
from cube.services.s05_sources import build_production_refresh_manager
from cube.pages.pnl.s01_common import PL_SAVED_VIEW_CONTROLS
from cube.pages.stock.s01_data import STOCK_SAVED_VIEW_CONTROLS
from cube.pages.risk.s01_common import RISK_SAVED_VIEW_CONTROLS
from cube.pages.risk.s03_defaults import DEFAULT_RISK_FILTER_LABEL
from cube.app import s07_factory as factory_module
from cube.ui import s03_filters as saved_views_module
from cube.ui.s01_constants import (
    FILTER_DIMENSION_FIELDS,
    RISK_FILTER_DIMENSION_FIELDS,
)
from cube.ui.s03_filters import (
    BASE_SAVED_VIEW_ID,
    BASE_SAVED_VIEW_LABEL,
    CUSTOM_SAVED_VIEW_ID,
    CUSTOM_SAVED_VIEW_LABEL,
    base_saved_filter_view,
    build_saved_filter_view_bar,
    committed_filter_state_values,
    matches_activity_1_to_3_base,
    register_saved_filter_view_callbacks,
    saved_view_apply_request,
    saved_view_request_matches_base,
    saved_view_request_values,
    selected_saved_view_label,
)


FILTER_KEYS = tuple(field.key for field in FILTER_DIMENSION_FIELDS)
RISK_FILTER_KEYS = tuple(field.key for field in RISK_FILTER_DIMENSION_FIELDS)


def _filters(activity: str = "Macro") -> dict[str, list[str]]:
    return {
        "activity": [activity],
        "signoffgroup": ["SOG-A"],
        "portfolio": ["BOOK-A"],
        "category": ["Core"],
        "subcategory": ["Rates"],
    }


def _walk(component: object) -> Iterable[object]:
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None:
        yield from _walk(children)


def _outputs(metadata: dict) -> list[object]:
    output = metadata["output"]
    return list(output) if isinstance(output, (list, tuple)) else [output]


def _callback_for_output(app: Dash, component_id: str, component_property: str):
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            str(output.component_id) == component_id
            and output.component_property == component_property
            for output in _outputs(item)
        )
    )
    return metadata["callback"].__wrapped__


def test_risk_omits_portfolio_while_stock_and_pnl_keep_shared_contract() -> None:
    assert FILTER_KEYS == (
        "activity",
        "signoffgroup",
        "portfolio",
        "category",
        "subcategory",
    )
    assert tuple(field.label for field in FILTER_DIMENSION_FIELDS) == (
        "Activity",
        "Signoff Group",
        "Portfolio",
        "Category",
        "Sub Category",
    )
    assert tuple(field.key for field in STOCK_SAVED_VIEW_CONTROLS.fields) == FILTER_KEYS
    assert tuple(field.key for field in RISK_SAVED_VIEW_CONTROLS.fields) == (
        "activity",
        "signoffgroup",
        "category",
        "subcategory",
    )
    assert tuple(field.key for field in PL_SAVED_VIEW_CONTROLS.fields) == FILTER_KEYS
    assert {
        RISK_SAVED_VIEW_CONTROLS.selector_id,
        STOCK_SAVED_VIEW_CONTROLS.selector_id,
        PL_SAVED_VIEW_CONTROLS.selector_id,
    } == {
        "risk-saved-view-selector",
        "stock-saved-view-selector",
        "pnl-saved-view-selector",
    }
    css = (Path(__file__).parents[1] / "assets" / "s02_controls.css").read_text()
    assert ".controls.filter-controls" in css
    assert "grid-template-columns: repeat(5, minmax(120px, 1fr));" in css
    assert ".saved-filter-view-disclosure[open]" in css
    assert ".saved-filter-view-panel" in css
    assert ".saved-view-filter-note" in css
    assert ".saved-view-form-actions" in css
    assert ".filter-mode-control" in css


def test_repository_is_shared_deterministic_and_atomic(tmp_path: Path) -> None:
    root = tmp_path / "saved_views"
    repository = SavedFilterViewRepository(root, FILTER_KEYS)

    later = repository.save_new(
        "risk",
        "Zulu view",
        _filters(),
        exclude_selected=False,
    )
    first = repository.save_new(
        "risk",
        " alpha   view ",
        {**_filters(), "portfolio": ["BOOK-B", "BOOK-A", "BOOK-A"]},
        exclude_selected=True,
    )
    hedge = repository.save_new(
        "stock",
        "Hedge view",
        _filters("Hedge"),
        exclude_selected=False,
    )

    expected_names = [
        "alpha view",
        "Hedge view",
        "Zulu view",
    ]
    assert [view.name for view in repository.list("risk")] == expected_names
    assert [view.name for view in repository.list("stock")] == expected_names
    assert [view.name for view in repository.list("pnl")] == expected_names
    assert repository.get("risk", first.identifier).filters["portfolio"] == (
        "BOOK-A",
        "BOOK-B",
    )
    stock_view = repository.get("stock", first.identifier)
    assert stock_view.scope == "stock"
    assert stock_view.filters == first.filters
    assert repository.get("pnl", hedge.identifier).filters["activity"] == ("Hedge",)
    assert later.identifier != first.identifier
    assert {path.parent.name for path in root.rglob("*.json")} == {
        SHARED_SAVED_VIEW_SCOPE
    }
    assert not list(root.rglob("*.tmp"))
    assert {path.parent.name for path in root.rglob(".write.lock")} == {
        SHARED_SAVED_VIEW_SCOPE,
    }

    document = json.loads(
        (root / SHARED_SAVED_VIEW_SCOPE / f"{first.identifier}.json").read_text()
    )
    assert document == {
        "version": 1,
        "id": first.identifier,
        "scope": SHARED_SAVED_VIEW_SCOPE,
        "name": "alpha view",
        "filters": {
            "activity": ["Macro"],
            "signoffgroup": ["SOG-A"],
            "portfolio": ["BOOK-A", "BOOK-B"],
            "category": ["Core"],
            "subcategory": ["Rates"],
        },
        "exclude_selected": True,
    }


def test_repository_update_is_shared_atomic_and_preserves_identity(
    tmp_path: Path,
) -> None:
    repository = SavedFilterViewRepository(tmp_path, FILTER_KEYS)
    created = repository.save_new(
        "risk",
        "Morning",
        _filters(),
        exclude_selected=False,
    )

    updated = repository.update(
        "pnl",
        created.identifier,
        _filters("Updated"),
        exclude_selected=True,
    )

    assert updated.identifier == created.identifier
    assert updated.name == created.name
    assert updated.scope == "pnl"
    assert repository.get("risk", created.identifier).filters["activity"] == (
        "Updated",
    )
    assert repository.get("stock", created.identifier).exclude_selected is True
    assert not list(tmp_path.rglob("*.tmp"))

    errors: list[BaseException] = []

    def update(index: int) -> None:
        try:
            repository.update(
                ("risk", "stock", "pnl")[index % 3],
                created.identifier,
                _filters(f"Concurrent {index}"),
                exclude_selected=bool(index % 2),
            )
        except BaseException as error:  # pragma: no cover - thread handoff
            errors.append(error)

    threads = [Thread(target=update, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    final = repository.get("risk", created.identifier)
    assert final.filters["activity"][0].startswith("Concurrent ")
    assert len(repository.list("pnl")) == 1
    assert not list(tmp_path.rglob("*.tmp"))


def test_repository_rejects_duplicates_paths_and_invalid_documents(
    tmp_path: Path,
) -> None:
    repository = SavedFilterViewRepository(tmp_path, FILTER_KEYS)
    view = repository.save_new(
        "risk",
        "Morning",
        _filters(),
        exclude_selected=False,
    )

    with pytest.raises(SavedViewConflictError, match="already exists"):
        repository.save_new(
            "stock",
            " morning ",
            _filters(),
            exclude_selected=False,
        )
    with pytest.raises(SavedViewValidationError, match="path"):
        repository.save_new(
            "risk",
            "../escape",
            _filters(),
            exclude_selected=False,
        )
    with pytest.raises(SavedViewValidationError, match="scope"):
        repository.list("../risk")
    with pytest.raises(SavedViewValidationError, match="identifier"):
        repository.get("risk", "../escape")

    path = tmp_path / SHARED_SAVED_VIEW_SCOPE / f"{view.identifier}.json"
    payload = json.loads(path.read_text())
    payload["filters"]["unknown"] = []
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(SavedViewValidationError, match="configured keys"):
        repository.list("risk")


def test_repository_serializes_concurrent_writers(tmp_path: Path) -> None:
    repository = SavedFilterViewRepository(tmp_path, FILTER_KEYS)
    errors: list[BaseException] = []

    def save(index: int) -> None:
        try:
            repository.save_new(
                ("risk", "stock", "pnl")[index % 3],
                f"View {index:02d}",
                _filters(str(index)),
                exclude_selected=bool(index % 2),
            )
        except BaseException as error:  # pragma: no cover - thread handoff
            errors.append(error)

    threads = [Thread(target=save, args=(index,)) for index in range(12)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert [view.name for view in repository.list("risk")] == [
        f"View {index:02d}" for index in range(12)
    ]
    assert [view.identifier for view in repository.list("stock")] == [
        view.identifier for view in repository.list("pnl")
    ]


def test_saved_view_editor_is_collapsed_with_an_always_present_base() -> None:
    filter_note = "Include mode help stays inside this disclosure."
    filter_bar = html.Div(
        dcc.Dropdown(id="test-authoritative-filter", value=[]),
        id="test-authoritative-filter-bar",
    )
    bar = build_saved_filter_view_bar(
        RISK_SAVED_VIEW_CONTROLS,
        filter_note=filter_note,
        filter_bar=filter_bar,
    )
    components = list(_walk(bar))
    selector = next(
        item
        for item in components
        if isinstance(item, dcc.Dropdown)
        and item.id == RISK_SAVED_VIEW_CONTROLS.selector_id
    )
    name = next(
        item
        for item in components
        if isinstance(item, dcc.Input) and item.id == RISK_SAVED_VIEW_CONTROLS.name_id
    )
    copy = " ".join(str(getattr(item, "children", "")) for item in components)

    assert isinstance(bar, html.Details)
    assert bar.open is False
    assert any(isinstance(item, html.Summary) for item in components)
    current_label = next(
        item
        for item in components
        if getattr(item, "id", None) == RISK_SAVED_VIEW_CONTROLS.current_label_id
    )
    assert current_label.children == DEFAULT_RISK_FILTER_LABEL
    assert selector.value == BASE_SAVED_VIEW_ID
    assert selector.clearable is False
    assert selector.options[0] == {
        "label": DEFAULT_RISK_FILTER_LABEL,
        "value": BASE_SAVED_VIEW_ID,
    }
    assert name.debounce is False
    assert RISK_SAVED_VIEW_CONTROLS.apply_request_id in {
        getattr(item, "id", None) for item in components
    }
    assert RISK_SAVED_VIEW_CONTROLS.applied_request_id in {
        getattr(item, "id", None) for item in components
    }
    assert {
        RISK_SAVED_VIEW_CONTROLS.committed_state_id,
        RISK_SAVED_VIEW_CONTROLS.initialized_id,
        RISK_SAVED_VIEW_CONTROLS.apply_id,
        RISK_SAVED_VIEW_CONTROLS.cancel_id,
    } <= {getattr(item, "id", None) for item in components}
    assert "Draft changes affect the page only after Apply" in copy
    assert "shared across Risk, Stock, and P&L" in copy
    assert "restart or redeploy" in copy
    notes = [
        item
        for item in components
        if isinstance(item, html.Div)
        and "saved-view-filter-note" in str(getattr(item, "className", "")).split()
    ]
    assert [note.children for note in notes] == [filter_note]
    assert {
        "test-authoritative-filter-bar",
        "test-authoritative-filter",
    } <= {getattr(item, "id", None) for item in components}
    filter_wrapper = next(
        item
        for item in components
        if "saved-view-filter-bar" in str(getattr(item, "className", "")).split()
    )
    assert filter_wrapper.children is filter_bar


def test_selected_saved_view_label_uses_name_and_recovers_to_base() -> None:
    options = [
        {"label": BASE_SAVED_VIEW_LABEL, "value": BASE_SAVED_VIEW_ID},
        {"label": "Credit books", "value": "credit-books"},
    ]

    assert selected_saved_view_label(BASE_SAVED_VIEW_ID, options) == (
        BASE_SAVED_VIEW_LABEL
    )
    assert selected_saved_view_label(CUSTOM_SAVED_VIEW_ID, options) == (
        CUSTOM_SAVED_VIEW_LABEL
    )
    assert selected_saved_view_label("credit-books", options) == "Credit books"
    assert selected_saved_view_label("deleted-view", options) == BASE_SAVED_VIEW_LABEL


def test_activity_base_matcher_distinguishes_exact_base_from_manual_filters() -> None:
    exact = {
        "activity": ["Macro", "Credit", "Hedge"],
        "signoffgroup": [],
        "category": [],
        "subcategory": [],
    }
    temp = {
        **exact,
        "activity": [
            "TEMP_REPLACE_ME - Activity 1",
            "TEMP_REPLACE_ME - Activity 2",
            "TEMP_REPLACE_ME - Activity 3",
        ],
    }

    assert matches_activity_1_to_3_base(exact, False)
    assert matches_activity_1_to_3_base(temp, False)
    assert not matches_activity_1_to_3_base(
        {**exact, "category": ["Core"]},
        False,
    )
    assert not matches_activity_1_to_3_base(
        {**exact, "activity": ["Macro", "Credit"]},
        False,
    )
    assert not matches_activity_1_to_3_base(exact, True)

    incomplete_options = [
        {"label": "Macro", "value": "Macro"},
        {"label": "Credit", "value": "Credit"},
        {"label": "Other", "value": "Other"},
    ]
    incomplete = {**exact, "activity": ["Macro", "Credit"]}
    assert matches_activity_1_to_3_base(
        incomplete,
        False,
        incomplete_options,
    )
    assert not matches_activity_1_to_3_base(
        {**exact, "activity": ["Macro"]},
        False,
        incomplete_options,
    )
    assert not matches_activity_1_to_3_base(
        {**exact, "activity": []},
        False,
        incomplete_options,
    )
    assert not matches_activity_1_to_3_base(
        {**exact, "activity": []},
        False,
        [{"label": "Other", "value": "Other"}],
    )


def test_request_store_is_validated_and_detects_later_manual_edits(
    tmp_path: Path,
) -> None:
    repository = SavedFilterViewRepository(tmp_path, FILTER_KEYS)
    view = repository.save_new(
        "stock",
        "Macro",
        _filters(),
        exclude_selected=True,
    )
    base = {key: [] for key in FILTER_KEYS}
    request = saved_view_apply_request(
        view,
        base_filters=base,
        base_exclude_selected=False,
    )

    values, exclude = saved_view_request_values(request, STOCK_SAVED_VIEW_CONTROLS)
    assert values[0] == ["Macro"]
    assert exclude == ["exclude"]
    assert saved_view_request_matches_base(
        request,
        STOCK_SAVED_VIEW_CONTROLS,
        tuple([] for _key in FILTER_KEYS),
        [],
    )
    manually_edited = [[], [], ["BOOK-B"], [], []]
    assert not saved_view_request_matches_base(
        request,
        STOCK_SAVED_VIEW_CONTROLS,
        manually_edited,
        [],
    )

    request["scope"] = "risk"
    with pytest.raises(ValueError, match="another page"):
        saved_view_request_values(request, STOCK_SAVED_VIEW_CONTROLS)

    current = _filters("Manual")
    base_request = saved_view_apply_request(
        base_saved_filter_view(STOCK_SAVED_VIEW_CONTROLS),
        base_filters=current,
        base_exclude_selected=True,
    )
    base_values, base_exclude = saved_view_request_values(
        base_request,
        STOCK_SAVED_VIEW_CONTROLS,
    )
    assert base_values == ([], [], [], [], [])
    assert base_exclude == []
    assert saved_view_request_matches_base(
        base_request,
        STOCK_SAVED_VIEW_CONTROLS,
        tuple(current[key] for key in FILTER_KEYS),
        ["exclude"],
    )


def test_generic_callbacks_never_own_filter_dropdown_values(tmp_path: Path) -> None:
    repository = SavedFilterViewRepository(tmp_path, FILTER_KEYS)
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.layout = html.Div(
        [
            build_saved_filter_view_bar(RISK_SAVED_VIEW_CONTROLS),
            *[
                dcc.Dropdown(id=RISK_SAVED_VIEW_CONTROLS.filter_ids[field.key])
                for field in RISK_FILTER_DIMENSION_FIELDS
            ],
            dcc.Checklist(id=RISK_SAVED_VIEW_CONTROLS.exclude_id),
        ]
    )
    register_saved_filter_view_callbacks(
        app,
        repository,
        RISK_SAVED_VIEW_CONTROLS,
    )

    outputs = [
        (str(output.component_id), output.component_property)
        for metadata in app.callback_map.values()
        for output in _outputs(metadata)
    ]
    assert (RISK_SAVED_VIEW_CONTROLS.apply_request_id, "data") in outputs
    assert (RISK_SAVED_VIEW_CONTROLS.applied_request_id, "data") in outputs
    assert (RISK_SAVED_VIEW_CONTROLS.committed_state_id, "data") in outputs
    assert (RISK_SAVED_VIEW_CONTROLS.current_label_id, "children") in outputs
    assert not any(
        (component_id, "value") in outputs
        for component_id in RISK_SAVED_VIEW_CONTROLS.filter_ids.values()
    )
    assert (RISK_SAVED_VIEW_CONTROLS.exclude_id, "value") not in outputs
    selector_owner = next(
        metadata
        for metadata in app.callback_map.values()
        if any(
            output.component_id == RISK_SAVED_VIEW_CONTROLS.selector_id
            and output.component_property == "options"
            for output in _outputs(metadata)
        )
    )
    selector_inputs = {
        (item["id"], item["property"]) for item in selector_owner["inputs"]
    }
    selector_state = {
        (item["id"], item["property"]) for item in selector_owner["state"]
    }
    assert (RISK_SAVED_VIEW_CONTROLS.apply_id, "n_clicks") in selector_inputs
    assert (
        RISK_SAVED_VIEW_CONTROLS.committed_state_id,
        "data",
    ) not in selector_inputs
    assert (
        RISK_SAVED_VIEW_CONTROLS.committed_state_id,
        "data",
    ) in selector_state
    activity_options = (
        RISK_SAVED_VIEW_CONTROLS.filter_ids["activity"],
        "options",
    )
    assert activity_options not in selector_inputs
    assert activity_options in selector_state

    committed_owner = next(
        metadata
        for metadata in app.callback_map.values()
        if any(
            output.component_id == RISK_SAVED_VIEW_CONTROLS.committed_state_id
            and output.component_property == "data"
            for output in _outputs(metadata)
        )
    )
    committed_inputs = {
        (item["id"], item["property"]) for item in committed_owner["inputs"]
    }
    committed_state = {
        (item["id"], item["property"]) for item in committed_owner["state"]
    }
    assert activity_options not in committed_inputs
    assert activity_options in committed_state


def test_page_readiness_commits_base_without_treating_drafts_as_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    controls = RISK_SAVED_VIEW_CONTROLS
    repository = SavedFilterViewRepository(tmp_path, FILTER_KEYS)
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.layout = html.Div(
        [
            build_saved_filter_view_bar(controls),
            *[
                dcc.Dropdown(id=controls.filter_ids[field.key], value=[])
                for field in controls.fields
            ],
            dcc.Checklist(id=controls.exclude_id, value=[]),
        ]
    )
    register_saved_filter_view_callbacks(app, repository, controls)
    metadata = next(
        item
        for item in app.callback_map.values()
        if any(
            output.component_id == controls.committed_state_id
            for output in _outputs(item)
        )
    )
    commit = metadata["callback"].__wrapped__
    base_values = [["Activity 1", "Activity 2", "Activity 3"], [], [], []]
    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.initialized_id),
    )

    committed = commit(
        0,
        True,
        "unapplied-draft",
        *base_values,
        [],
        None,
    )

    assert committed["view_id"] == BASE_SAVED_VIEW_ID
    assert committed_filter_state_values(committed, controls) == (
        tuple(base_values),
        [],
    )
    assert {(item["id"], item["property"]) for item in metadata["inputs"]} == {
        (controls.apply_id, "n_clicks"),
        (controls.initialized_id, "data"),
    }
    assert {(controls.filter_ids[field.key], "value") for field in controls.fields} <= {
        (item["id"], item["property"]) for item in metadata["state"]
    }


def test_factory_shares_one_catalogue_without_sharing_live_page_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SavedFilterViewRepository(tmp_path, FILTER_KEYS)
    named = repository.save_new(
        "risk",
        "Credit books",
        {
            **_filters("Credit"),
            "portfolio": ["BOOK-B", "BOOK-D"],
        },
        exclude_selected=True,
    )
    registered: list[tuple[SavedFilterViewRepository, object]] = []
    register = factory_module.register_saved_filter_view_callbacks

    def capture_registration(app, shared_repository, controls) -> None:
        registered.append((shared_repository, controls))
        register(app, shared_repository, controls)

    monkeypatch.setattr(
        factory_module,
        "register_saved_filter_view_callbacks",
        capture_registration,
    )
    app = factory_module.build_app(
        refresh_manager=build_production_refresh_manager(),
        stock_source=lambda _date: pd.DataFrame(),
        stock_portfolio_source=lambda _date: pd.DataFrame(),
        saved_view_root=tmp_path,
    )

    assert [controls for _repository, controls in registered] == [
        RISK_SAVED_VIEW_CONTROLS,
        PL_SAVED_VIEW_CONTROLS,
    ]
    assert (
        len({id(shared_repository) for shared_repository, _controls in registered}) == 1
    )
    assert registered[0][0]._root == tmp_path.resolve()

    for controls in (
        RISK_SAVED_VIEW_CONTROLS,
        PL_SAVED_VIEW_CONTROLS,
    ):
        refresh_catalogue = _callback_for_output(
            app,
            controls.selector_id,
            "options",
        )
        options, selected, _name, _status = refresh_catalogue(
            1,
            0,
            0,
            0,
            0,
            BASE_SAVED_VIEW_ID,
            "",
            None,
            *([[]] * len(controls.fields)),
            [],
        )
        assert options == [
            {"label": controls.base_label, "value": BASE_SAVED_VIEW_ID},
            {"label": named.name, "value": named.identifier},
        ]
        # Catalogue refreshes must not overwrite a newer browser selection.
        assert selected is no_update

    risk_apply = _callback_for_output(
        app,
        RISK_SAVED_VIEW_CONTROLS.apply_request_id,
        "data",
    )
    risk_request = risk_apply(
        named.identifier,
        0,
        None,
        *([[]] * len(RISK_FILTER_KEYS)),
        [],
    )
    risk_values, risk_exclude = saved_view_request_values(
        risk_request,
        RISK_SAVED_VIEW_CONTROLS,
    )
    assert risk_values == (
        ["Credit"],
        ["SOG-A"],
        ["Core"],
        ["Rates"],
    )
    assert risk_exclude == ["exclude"]
    with pytest.raises(ValueError, match="another page"):
        saved_view_request_values(risk_request, STOCK_SAVED_VIEW_CONTROLS)

    pnl_apply = _callback_for_output(
        app,
        PL_SAVED_VIEW_CONTROLS.apply_request_id,
        "data",
    )
    pnl_request = pnl_apply(
        BASE_SAVED_VIEW_ID,
        0,
        None,
        *(["pnl-local"] for _key in FILTER_KEYS),
        [],
    )
    pnl_values, pnl_exclude = saved_view_request_values(
        pnl_request,
        PL_SAVED_VIEW_CONTROLS,
    )
    assert pnl_values == ([], [], [], [], [])
    assert pnl_exclude == []
    assert {
        RISK_SAVED_VIEW_CONTROLS.apply_request_id,
        PL_SAVED_VIEW_CONTROLS.apply_request_id,
    } == {
        "risk-saved-view-apply-request",
        "pnl-saved-view-apply-request",
    }


def test_callbacks_save_update_delete_and_apply_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = SavedFilterViewRepository(tmp_path, FILTER_KEYS)
    controls = RISK_SAVED_VIEW_CONTROLS
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.layout = html.Div(
        [
            build_saved_filter_view_bar(controls),
            *[
                dcc.Dropdown(id=controls.filter_ids[field.key], value=[])
                for field in controls.fields
            ],
            dcc.Checklist(id=controls.exclude_id, value=[]),
        ]
    )
    register_saved_filter_view_callbacks(app, repository, controls)
    mutate = _callback_for_output(app, controls.selector_id, "options")
    stage = _callback_for_output(app, controls.apply_request_id, "data")
    commit = _callback_for_output(app, controls.committed_state_id, "data")
    actions = _callback_for_output(app, controls.save_id, "children")
    current_label = _callback_for_output(app, controls.current_label_id, "children")
    selected_values = [_filters()[key] for key in RISK_FILTER_KEYS]

    assert actions(BASE_SAVED_VIEW_ID) == ("Save New", True, False)
    assert (
        current_label(
            None,
            [{"label": BASE_SAVED_VIEW_LABEL, "value": BASE_SAVED_VIEW_ID}],
        )
        == DEFAULT_RISK_FILTER_LABEL
    )
    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.save_id),
    )
    saved = mutate(
        0,
        1,
        0,
        0,
        0,
        BASE_SAVED_VIEW_ID,
        "Morning",
        None,
        *selected_values,
        ["exclude"],
    )
    identifier = saved[1]
    assert saved[0][0]["value"] == BASE_SAVED_VIEW_ID
    assert saved[2] == ""
    assert "Saved new view: Morning" in saved[3]
    assert actions(identifier) == ("Update View", False, True)
    # Selecting or saving a draft must not claim it is active before Apply.
    assert current_label(None, saved[0]) == DEFAULT_RISK_FILTER_LABEL
    assert repository.get("stock", identifier).exclude_selected is True

    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.selector_id),
    )
    named_draft = stage(
        identifier,
        0,
        None,
        *([[]] * len(RISK_FILTER_KEYS)),
        [],
    )
    draft_values, draft_exclude = saved_view_request_values(named_draft, controls)
    assert draft_values == tuple(selected_values)
    assert draft_exclude == ["exclude"]

    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.apply_id),
    )
    committed = commit(
        1,
        True,
        identifier,
        *selected_values,
        ["exclude"],
        None,
    )
    assert committed_filter_state_values(committed, controls) == (
        tuple(selected_values),
        ["exclude"],
    )
    assert current_label(committed, saved[0]) == "Morning"
    assert repository.get("stock", identifier).filters["portfolio"] == ()

    # An Apply arriving with the one-time initialization update still owns the
    # commit; initialization must not force the identifier back to Base.
    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(
            triggered_id=controls.initialized_id,
            triggered_prop_ids={
                f"{controls.apply_id}.n_clicks": controls.apply_id,
                f"{controls.initialized_id}.data": controls.initialized_id,
            },
        ),
    )
    coalesced_apply = commit(
        1,
        True,
        identifier,
        *selected_values,
        ["exclude"],
        None,
    )
    assert coalesced_apply["view_id"] == identifier

    # A later initialization-only event is not another Apply merely because
    # the button retains a historical non-zero click count.
    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(
            triggered_id=controls.initialized_id,
            triggered_prop_ids={
                f"{controls.initialized_id}.data": controls.initialized_id
            },
        ),
    )
    with pytest.raises(saved_views_module.PreventUpdate):
        commit(
            1,
            True,
            identifier,
            *selected_values,
            ["exclude"],
            committed,
        )

    manual_values = [["Manual"], *selected_values[1:]]
    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.apply_id),
    )
    custom_committed = commit(
        2,
        True,
        identifier,
        *manual_values,
        ["exclude"],
        committed,
    )
    assert custom_committed["view_id"] == CUSTOM_SAVED_VIEW_ID
    assert current_label(custom_committed, saved[0]) == CUSTOM_SAVED_VIEW_LABEL
    assert repository.get("risk", identifier).filters["activity"] == ("Macro",)

    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(
            triggered_id=controls.refresh_id,
            triggered_prop_ids={
                f"{controls.refresh_id}.n_intervals": controls.refresh_id,
                f"{controls.apply_id}.n_clicks": controls.apply_id,
            },
        ),
    )
    custom_mode = mutate(
        0,
        1,
        0,
        0,
        2,
        identifier,
        "",
        committed,
        *manual_values,
        ["exclude"],
    )
    assert custom_mode[1] == CUSTOM_SAVED_VIEW_ID
    assert {option["value"]: option for option in custom_mode[0]}[
        CUSTOM_SAVED_VIEW_ID
    ] == {
        "label": CUSTOM_SAVED_VIEW_LABEL,
        "value": CUSTOM_SAVED_VIEW_ID,
        "disabled": True,
    }
    assert actions(CUSTOM_SAVED_VIEW_ID) == ("Save New", True, False)
    assert "Save New" in custom_mode[3]

    # Refreshing the catalogue must retain the synthetic Custom Mode option
    # while leaving the browser's current selector value untouched.
    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.refresh_id),
    )
    refreshed_custom = mutate(
        1,
        1,
        0,
        0,
        2,
        CUSTOM_SAVED_VIEW_ID,
        "",
        custom_committed,
        *manual_values,
        ["exclude"],
    )
    assert refreshed_custom[1] is no_update
    assert CUSTOM_SAVED_VIEW_ID in {option["value"] for option in refreshed_custom[0]}

    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.cancel_id),
    )
    custom_restore_request = stage(
        CUSTOM_SAVED_VIEW_ID,
        1,
        custom_committed,
        *selected_values,
        [],
    )
    restored_custom_values, restored_custom_exclude = saved_view_request_values(
        custom_restore_request,
        controls,
    )
    assert restored_custom_values == tuple(manual_values)
    assert restored_custom_exclude == ["exclude"]
    cancelled_custom = mutate(
        0,
        1,
        0,
        1,
        2,
        CUSTOM_SAVED_VIEW_ID,
        "",
        custom_committed,
        *selected_values,
        [],
    )
    assert cancelled_custom[1] == CUSTOM_SAVED_VIEW_ID

    risk_base_values = [["Activity 1", "Activity 2", "Activity 3"], [], [], []]
    edited_base_values = [*risk_base_values]
    edited_base_values[2] = ["Core"]
    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.apply_id),
    )
    edited_base_from_custom = commit(
        3,
        True,
        BASE_SAVED_VIEW_ID,
        *edited_base_values,
        [],
        custom_committed,
    )
    assert edited_base_from_custom["view_id"] == CUSTOM_SAVED_VIEW_ID

    base_from_custom = commit(
        4,
        True,
        BASE_SAVED_VIEW_ID,
        *risk_base_values,
        [],
        custom_committed,
    )
    assert base_from_custom["view_id"] == BASE_SAVED_VIEW_ID

    incomplete_base_values = [["Macro", "Credit"], [], [], []]
    incomplete_activity_options = [
        {"label": "Macro", "value": "Macro"},
        {"label": "Credit", "value": "Credit"},
    ]
    incomplete_base_from_custom = commit(
        5,
        True,
        BASE_SAVED_VIEW_ID,
        *incomplete_base_values,
        [],
        custom_committed,
        incomplete_activity_options,
    )
    assert incomplete_base_from_custom["view_id"] == BASE_SAVED_VIEW_ID

    incomplete_manual_from_base = commit(
        6,
        True,
        BASE_SAVED_VIEW_ID,
        ["Macro"],
        *incomplete_base_values[1:],
        [],
        incomplete_base_from_custom,
        incomplete_activity_options,
    )
    assert incomplete_manual_from_base["view_id"] == CUSTOM_SAVED_VIEW_ID

    incomplete_base_mode = mutate(
        0,
        1,
        0,
        0,
        5,
        BASE_SAVED_VIEW_ID,
        "",
        custom_committed,
        *incomplete_base_values,
        [],
        incomplete_activity_options,
    )
    assert incomplete_base_mode[1] == BASE_SAVED_VIEW_ID

    updated_filters = _filters("Updated")
    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.save_id),
    )
    updated = mutate(
        0,
        2,
        0,
        0,
        0,
        identifier,
        "Ignored while updating",
        committed,
        *(updated_filters[key] for key in RISK_FILTER_KEYS),
        [],
    )
    assert updated[1] == identifier
    assert updated[2] is no_update
    assert "Updated view: Morning" in updated[3]
    assert current_label(committed, updated[0]) == "Morning"
    assert repository.get("pnl", identifier).filters["activity"] == ("Updated",)
    assert repository.get("risk", identifier).name == "Morning"

    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.selector_id),
    )
    updated_draft = stage(
        identifier,
        0,
        committed,
        *selected_values,
        ["exclude"],
    )
    staged_values, staged_exclude = saved_view_request_values(
        updated_draft,
        controls,
    )
    assert staged_values == tuple(updated_filters[key] for key in RISK_FILTER_KEYS)
    assert staged_exclude == []

    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.selector_id),
    )
    base_request = stage(
        BASE_SAVED_VIEW_ID,
        0,
        committed,
        *(updated_filters[key] for key in RISK_FILTER_KEYS),
        ["exclude"],
    )
    base_values, exclude = saved_view_request_values(base_request, controls)
    assert base_values == ([], [], [], [])
    assert exclude == []

    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.cancel_id),
    )
    restore_request = stage(
        BASE_SAVED_VIEW_ID,
        1,
        committed,
        *(updated_filters[key] for key in RISK_FILTER_KEYS),
        [],
    )
    restored_values, restored_exclude = saved_view_request_values(
        restore_request,
        controls,
    )
    assert restored_values == tuple(selected_values)
    assert restored_exclude == ["exclude"]
    cancelled = mutate(
        0,
        2,
        0,
        1,
        0,
        BASE_SAVED_VIEW_ID,
        "",
        committed,
        *(updated_filters[key] for key in RISK_FILTER_KEYS),
        [],
    )
    assert cancelled[1] == identifier
    assert "committed filters restored" in cancelled[3]

    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.delete_id),
    )
    deleted = mutate(
        0,
        2,
        1,
        1,
        0,
        identifier,
        "",
        committed,
        *(updated_filters[key] for key in RISK_FILTER_KEYS),
        [],
    )
    assert deleted[1] is no_update
    assert "Apply Base or another view" in deleted[3]
    assert repository.get("risk", identifier).name == "Morning"

    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.apply_id),
    )
    cleared_default = commit(
        2,
        True,
        BASE_SAVED_VIEW_ID,
        *([[]] * len(RISK_FILTER_KEYS)),
        [],
        committed,
        [],
    )
    assert cleared_default["view_id"] == CUSTOM_SAVED_VIEW_ID
    monkeypatch.setattr(
        saved_views_module,
        "ctx",
        SimpleNamespace(triggered_id=controls.delete_id),
    )
    deleted = mutate(
        0,
        2,
        2,
        1,
        0,
        identifier,
        "",
        cleared_default,
        *(updated_filters[key] for key in RISK_FILTER_KEYS),
        [],
    )
    assert deleted[0] == [
        {"label": DEFAULT_RISK_FILTER_LABEL, "value": BASE_SAVED_VIEW_ID}
    ]
    assert deleted[1] == BASE_SAVED_VIEW_ID
    assert current_label(cleared_default, deleted[0]) == CUSTOM_SAVED_VIEW_LABEL
    assert "Deleted view: Morning" in deleted[3]
    assert repository.list("stock") == ()


def test_repository_delete_is_exact_and_shared(tmp_path: Path) -> None:
    repository = SavedFilterViewRepository(tmp_path, FILTER_KEYS)
    risk = repository.save_new(
        "risk",
        "Shared label",
        _filters(),
        exclude_selected=False,
    )
    assert repository.get("stock", risk.identifier).name == "Shared label"

    deleted = repository.delete("pnl", risk.identifier)

    assert deleted.identifier == risk.identifier
    assert deleted.scope == "pnl"
    assert repository.list("risk") == ()
    assert repository.list("stock") == ()
    assert repository.list("pnl") == ()
