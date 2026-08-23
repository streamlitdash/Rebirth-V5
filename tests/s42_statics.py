"""V4.1 Statics read/write contracts."""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import pytest

from rebirth.pages.static_data.s01_store import (
    WRITABLE_STATIC_FILES,
    StaticDataStore,
)
from rebirth.pages.static_data.s02_view import build_static_data_page


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
    } <= ids


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
