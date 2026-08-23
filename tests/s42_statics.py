"""V4.1 Statics read/write contracts."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import Dash, no_update

from rebirth.pages.static_data.s01_store import (
    WRITABLE_STATIC_FILES,
    StaticDataStore,
)
from rebirth.pages.static_data.s02_view import (
    _editable_columns,
    _table_style,
    build_static_data_page,
)
from rebirth.pages.static_data import s03_callbacks as static_callbacks
from rebirth.pages.static_data.s03_callbacks import register_callbacks
from rebirth.services.s05_sources import build_production_refresh_manager
from rebirth.app.s07_factory import build_app


def _walk(component: object):
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None:
        yield from _walk(children)


def _store(tmp_path: Path) -> StaticDataStore:
    source = Path("data")
    for file_key in WRITABLE_STATIC_FILES:
        shutil.copy2(source / file_key, tmp_path / file_key)
    return StaticDataStore(tmp_path)


def _callback_outputs(metadata: dict) -> list[object]:
    output = metadata["output"]
    return list(output) if isinstance(output, (list, tuple)) else [output]


def _callback_for_output(app: Dash, component_id: str, component_property: str):
    return next(
        metadata["callback"].__wrapped__
        for metadata in app.callback_map.values()
        if any(
            output.component_id == component_id
            and output.component_property == component_property
            for output in _callback_outputs(metadata)
        )
    )


def test_statics_page_has_plain_read_and_write_workspaces() -> None:
    page = build_static_data_page()
    ids = {
        component_id
        for item in _walk(page)
        if isinstance((component_id := getattr(item, "id", None)), str)
    }
    assert {
        "static-data-mode",
        "static-data-read-panel",
        "static-data-file-selector",
        "static-data-table-container",
        "static-data-write-panel",
        "static-data-write-selector",
        "static-data-write-table",
        "static-data-add-row",
        "static-data-save",
        "static-data-cancel",
        "static-data-write-status",
        "static-data-revision",
    } <= ids
    write_table = next(
        item
        for item in _walk(page)
        if getattr(item, "id", None) == "static-data-write-table"
    )
    assert write_table.editable is True
    assert write_table.row_deletable is True


def test_statics_tabs_explicitly_show_one_workspace() -> None:
    app = build_app(refresh_manager=build_production_refresh_manager())
    callback = next(
        metadata["callback"].__wrapped__
        for metadata in app.callback_map.values()
        if "static-data-read-panel.style" in str(metadata["output"])
    )

    assert callback("read") == ({"display": "block"}, {"display": "none"})
    assert callback("write") == ({"display": "none"}, {"display": "block"})


def test_statics_editor_hides_columns_without_breaking_governed_schema() -> None:
    columns = _editable_columns(["Risk Type", "Risk Greek"])

    assert columns == [
        {
            "name": "Risk Type",
            "id": "Risk Type",
            "hideable": True,
            "renamable": False,
            "deletable": False,
        },
        {
            "name": "Risk Greek",
            "id": "Risk Greek",
            "hideable": True,
            "renamable": False,
            "deletable": False,
        },
    ]


def test_statics_empty_editor_mounts_without_fixed_header_crash() -> None:
    assert "fixed_rows" not in _table_style()


def test_static_store_writes_validated_csv_atomically(tmp_path: Path) -> None:
    store = _store(tmp_path)
    frame = store.read("s09_reported.csv")
    appended = pd.concat(
        [
            frame,
            pd.DataFrame(
                [
                    {
                        "Risk Type": "IR",
                        "Risk Greek": "Delta",
                        "Underlying": "TEST NEW CURVE",
                        "Reported Underlying": "TEST RATES",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    saved = store.write(
        "s09_reported.csv",
        appended.to_dict("records"),
        list(appended.columns),
    )
    assert len(saved) == len(frame) + 1
    assert not list(tmp_path.glob("*.tmp"))
    assert StaticDataStore(tmp_path).read("s09_reported.csv").equals(saved)


def test_statics_save_refreshes_read_view_and_reopens_saved_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _store(tmp_path)
    app = Dash(__name__, suppress_callback_exceptions=True)
    app.layout = build_static_data_page()
    register_callbacks(app, store=store)
    edit = _callback_for_output(app, "static-data-write-table", "data")
    read = _callback_for_output(app, "static-data-table-container", "children")
    frame = store.read("s09_reported.csv")
    appended = pd.concat(
        [
            frame,
            pd.DataFrame(
                [
                    {
                        "Risk Type": "IR",
                        "Risk Greek": "Delta",
                        "Underlying": "CALLBACK NEW CURVE",
                        "Reported Underlying": "CALLBACK RATES",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    columns = _editable_columns(list(appended.columns))

    monkeypatch.setattr(
        static_callbacks,
        "ctx",
        SimpleNamespace(triggered_id="static-data-save"),
    )
    saved_columns, saved_rows, status, revision = edit(
        "s09_reported.csv",
        0,
        1,
        0,
        columns,
        appended.to_dict("records"),
        0,
    )

    assert revision == 1
    assert len(saved_rows) == len(appended)
    assert "Saved Reported Underlying Mapping atomically" in status
    table_panel = read("s09_reported.csv", revision)
    table = next(
        item
        for item in _walk(table_panel)
        if getattr(item, "id", None) == "static-data-table-s09_reported"
    )
    assert table.data[-1]["Underlying"] == "CALLBACK NEW CURVE"

    monkeypatch.setattr(
        static_callbacks,
        "ctx",
        SimpleNamespace(triggered_id="static-data-write-selector"),
    )
    reopened_columns, reopened_rows, _message, next_revision = edit(
        "s09_reported.csv",
        0,
        0,
        0,
        [],
        [],
        revision,
    )
    assert reopened_columns == saved_columns
    assert reopened_rows == saved_rows
    assert next_revision is no_update


def test_static_store_rejects_invalid_rows_without_replacing_file(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    before = (tmp_path / "s08_concerto.csv").read_bytes()
    frame = store.read("s08_concerto.csv")
    duplicate = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate"):
        store.write(
            "s08_concerto.csv",
            duplicate.to_dict("records"),
            list(duplicate.columns),
        )
    assert (tmp_path / "s08_concerto.csv").read_bytes() == before


def test_static_store_write_allowlist_excludes_operational_snapshots(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError, match="not approved"):
        store.write("s03_risk.csv", [], [])
