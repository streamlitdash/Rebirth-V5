"""Jump-to-Default reference-table regressions."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import pytest
from dash import html

from cube.pages.risk.s02_state import _jtd_underlying_for_context
from cube.pages.risk.s13_workspacetables import build_jtd_reference_table
from cube.services.s08_jtd import JTDReferenceError, jtd_reference_rows


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


def test_jtd_lookup_is_exact_and_preserves_all_columns(tmp_path) -> None:
    source = tmp_path / "s13_jtd.csv"
    pd.DataFrame(
        {
            "Underlying": ["ACME", "Acme", "ACME"],
            "Seniority": ["Senior", "Sub", "Senior"],
            "Recovery": ["40", "20", "35"],
        }
    ).to_csv(source, index=False)

    result = jtd_reference_rows("ACME", path=source)

    assert result.columns.tolist() == ["Underlying", "Seniority", "Recovery"]
    assert result.to_dict("records") == [
        {"Underlying": "ACME", "Seniority": "Senior", "Recovery": "40"},
        {"Underlying": "ACME", "Seniority": "Senior", "Recovery": "35"},
    ]


def test_jtd_lookup_reports_a_missing_required_header(tmp_path) -> None:
    source = tmp_path / "s13_jtd.csv"
    pd.DataFrame({"Issuer": ["ACME"]}).to_csv(source, index=False)

    with pytest.raises(JTDReferenceError, match="Underlying"):
        jtd_reference_rows("ACME", path=source)


def test_jtd_lookup_reports_an_entirely_empty_file(tmp_path) -> None:
    source = tmp_path / "s13_jtd.csv"
    source.write_text("", encoding="utf-8")

    with pytest.raises(JTDReferenceError, match="Could not read"):
        jtd_reference_rows("ACME", path=source)


def test_jtd_table_is_flat_and_uses_the_detail_table_style() -> None:
    frame = pd.DataFrame(
        {
            "Underlying": ["ACME"],
            "Sector": ["Industrials"],
            "Comment": ["Watch"],
        }
    )

    component = build_jtd_reference_table(frame, "ACME")
    table = next(item for item in _walk(component) if isinstance(item, html.Table))
    headers = [item.children for item in _walk(table) if isinstance(item, html.Th)]
    cells = [item.children for item in _walk(table) if isinstance(item, html.Td)]

    assert component.className == "jtd-reference-card"
    assert "detail-table" in table.className
    assert headers == ["Underlying", "Sector", "Comment"]
    assert cells == ["ACME", "Industrials", "Watch"]


def test_jtd_identity_accepts_a_promoted_issuer_row() -> None:
    assert _jtd_underlying_for_context({"display bucket": "ACME"}) == "ACME"
    assert _jtd_underlying_for_context({"display bucket": "Other"}) is None
    assert (
        _jtd_underlying_for_context(
            {"display bucket": "PROMOTED", "reported underlying": "REPORTED"}
        )
        == "REPORTED"
    )
    assert (
        _jtd_underlying_for_context(
            {
                "display bucket": "PROMOTED",
                "reported underlying": "REPORTED",
                "underlying": "RAW",
            }
        )
        == "RAW"
    )
