"""The current Stock feed is trusted; archive adaptation stays in the demo."""

import pandas as pd
import pytest

from cube.adapters import s08_stock as connector


def test_current_stock_boundary_preserves_the_exact_connector_result(monkeypatch):
    frame = pd.DataFrame({
        "CIDS": ["001", "001"],
        "Arbitrary extra field": ["keep me", "also keep me"],
        "Stock": [12.0, -4.0],
        "dStock": [-55.0, 1.0],
    }, index=[8, 8])
    frame.attrs["source_revision"] = "site-123"
    calls = []

    def source(value):
        calls.append(value)
        return frame

    monkeypatch.setattr(connector, "_temp_current_stock_source", source)
    monkeypatch.setattr(connector, "validate_stock_frame", lambda *_a, **_k: pytest.fail("No current-feed validation"))
    result = connector.get_current_stock("2026-09-12")
    assert calls == ["2026-09-12"]
    assert result is frame
    assert result.attrs["source_revision"] == "site-123"


def test_demo_current_stock_uses_actual_archive_date_and_true_change():
    result = connector.get_current_stock("2026-09-12")
    assert result.attrs == {
        "stock_date": "2026-08-21",
        "previous_stock_date": "2026-08-20",
        "notice": "TEMP_REPLACE_ME archive snapshot",
    }
    assert result.columns[:4].tolist() == [
        "Sign-off group", "Group", "Counterparty name", "CRDS",
    ]
    assert result.columns[-2:].tolist() == ["Stock", "dStock"]
    actual = connector.get_stock("2026-08-21")
    prior = connector.get_stock("2026-08-20")
    assert result["Stock"].sum() == pytest.approx(actual["Market Value"].sum())
    assert result["dStock"].sum() == pytest.approx(
        actual["Market Value"].sum() - prior["Market Value"].sum(),
    )
    assert result["CRDS"].str.contains("TEMP_REPLACE_ME").all()


def test_demo_does_not_present_future_archive_as_current():
    with pytest.raises(ValueError, match="No completed Stock archive"):
        connector.get_current_stock("2000-01-01")


def test_demo_single_date_leaves_change_unavailable(tmp_path, monkeypatch):
    leaf = tmp_path / "2026-08-21"
    leaf.mkdir()
    (leaf / connector.STOCK_SUCCESS_FILE_NAME).touch()
    (leaf / connector.STOCK_FILE_NAME).touch()
    monkeypatch.setattr(connector, "STOCK_ARCHIVE_ROOT", tmp_path)
    frame = pd.DataFrame([
        ["TEMP_REPLACE_ME - CRDS", "TEMP_REPLACE_ME - CPTY", "TEMP_REPLACE_ME - BOOK_A", "Instrument", "USD", 1.0, 100.0],
    ], columns=connector.STOCK_COLUMNS)
    monkeypatch.setattr(connector, "get_stock", lambda _date: frame)
    result = connector.get_current_stock("2026-09-12")
    assert result["Stock"].tolist() == [100.0]
    assert result["dStock"].isna().all()
    assert "previous_stock_date" not in result.attrs
