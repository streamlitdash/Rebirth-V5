"""Pinned-promotion and selectable Top Promotions contracts."""

from __future__ import annotations

import pandas as pd

from cube.domain.s07_governance import (
    apply_pinned_promotions,
    load_pinned_promotions,
)
from cube.pages.risk.s11_promotion import (
    PromotionBasis,
    apply_promotion_generation,
    calculate_current_view_promotion,
)
from cube.pages.risk.s13_workspacetables import (
    TOP_PROMOTION_SIGNALS,
    build_top_promotions_table,
    top_promotions_frame,
)
from cube.services.s05_sources import _load_temp_csv, get_pinned_promotions
from cube.ui.s02_aggregation import recompute_filtered_promotion
from cube.ui.s01_constants import FILTER_COLUMNS


def _governed_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Risk Type": ["IR", "IR", "IR"],
            "Risk Greek": ["Delta", "Delta", "Delta"],
            "Reported Underlying": ["KRx", "KRx", "Other"],
            "Underlying": ["KRW", "KRW NDF", "JPY"],
            "Portfolio Mapped": [True, True, True],
            "Display Bucket": ["Other", "Other", "Other"],
            "Promotion Reason": ["", "Big Risk", "Big PL"],
            "Promotion Score": [0.2, 1.5, 2.0],
        }
    )


def _lower_frame(*, pinned: bool) -> pd.DataFrame:
    reason = "*" if pinned else ""
    return pd.DataFrame(
        {
            "risk type": ["IR", "IR"],
            "risk greek": ["Delta", "Delta"],
            "reported underlying": ["KRx", "KRx"],
            "portfolio": ["A", "B"],
            "risk": [60.0, 60.0],
            "drisk": [0.0, 0.0],
            "pl": [0.0, 0.0],
            "risk threshold": [100.0, 100.0],
            "drisk threshold": [100.0, 100.0],
            "pl threshold": [100.0, 100.0],
            "display bucket": ["KRx" if pinned else "Other"] * 2,
            "promotion reason": [reason, reason],
            "promotion score": [0.0, 0.0],
        }
    )


def test_exact_raw_pin_marks_the_reported_parent_without_multiplying_rows() -> None:
    pins = pd.DataFrame(
        [["IR", "Delta", "KRx", "KRW"]],
        columns=["Risk Type", "Risk Greek", "Reported Underlying", "Underlying"],
    )

    result = apply_pinned_promotions(_governed_frame(), pins)
    repeated = apply_pinned_promotions(result, pins)

    assert len(result) == 3
    assert result["Promotion Score"].tolist() == [0.2, 1.5, 2.0]
    assert result["Promotion Reason"].tolist() == ["*", "*, Big Risk", "Big PL"]
    assert result["Display Bucket"].tolist() == ["KRx", "KRx", "Other"]
    assert repeated["Promotion Reason"].tolist() == result["Promotion Reason"].tolist()


def test_pinned_file_contract_is_exact_and_unique(tmp_path) -> None:
    valid = pd.DataFrame(
        [["IR", "Delta", "KRx", "KRW"]],
        columns=["Risk Type", "Risk Greek", "Reported Underlying", "Underlying"],
    )

    assert load_pinned_promotions(valid).equals(valid)

    duplicate = pd.concat([valid, valid], ignore_index=True)
    try:
        load_pinned_promotions(duplicate)
    except ValueError as error:
        assert "unique four-column keys" in str(error)
    else:  # pragma: no cover - contract assertion
        raise AssertionError("Duplicate pins should be rejected")

    supplied = get_pinned_promotions()
    assert supplied.columns.tolist() == valid.columns.tolist()
    # The file is intentionally user-editable.  Test its contract, not the
    # particular pins currently chosen by the operator.
    pd.testing.assert_frame_equal(
        load_pinned_promotions(supplied),
        supplied,
        check_dtype=False,
    )

    header_only = tmp_path / "s12_pinned.csv"
    header_only.write_text(
        "Risk Type,Risk Greek,Reported Underlying,Underlying\n",
        encoding="utf-8",
    )
    stat = header_only.stat()
    empty = _load_temp_csv(
        "pinned_promotions",
        str(header_only),
        stat.st_mtime_ns,
        stat.st_size,
    )
    assert empty.empty


def test_pin_survives_filtered_recompute_and_manual_generation() -> None:
    source = _lower_frame(pinned=True)
    recomputed = recompute_filtered_promotion(source)
    basis = PromotionBasis.build(
        4,
        risk_type="IR",
        ir_family="delta",
        splits=["Risk"],
        filters={column: [] for column in FILTER_COLUMNS},
    )
    generation = calculate_current_view_promotion(
        _lower_frame(pinned=False),
        basis,
        identifier="without-pin",
    )
    applied = apply_promotion_generation(source, generation, revision=4)

    assert recomputed["promotion reason"].eq("*, Big Risk").all()
    assert applied["promotion reason"].eq("*, Big Risk").all()
    assert recomputed["promotion score"].eq(1.2).all()
    assert applied["promotion score"].eq(1.2).all()


def test_top_promotions_orders_absolute_values_and_keeps_signed_display() -> None:
    frame = pd.DataFrame(
        [
            ["IR", "Delta", "KRx", "Big PL, *", 2.0, -10.0, 20.0, -30.0, -4.0],
            ["IR", "Delta", "KRx", "Big Risk", 2.0, -90.0, 5.0, -10.0, -2.0],
            ["FX", "Delta", "EUR/USD", "Big PL", 1.5, 70.0, -80.0, 60.0, 3.0],
            ["Credit", "Delta", "CDX", "*", 0.0, 50.0, 40.0, -100.0, 1.0],
        ],
        columns=[
            "risk type",
            "risk greek",
            "reported underlying",
            "promotion reason",
            "promotion score",
            "risk",
            "drisk",
            "pl",
            "vol score",
        ],
    )

    assert TOP_PROMOTION_SIGNALS == {
        "vol-score": "Vol Score",
        "risk": "Risk",
        "drisk": "dRisk",
        "pl": "P&L",
    }
    assert top_promotions_frame(frame, signal="risk")[
        "Reported Underlying"
    ].tolist() == ["KRx", "EUR/USD", "CDX"]
    assert top_promotions_frame(frame, signal="drisk")[
        "Reported Underlying"
    ].tolist() == ["EUR/USD", "CDX", "KRx"]
    by_pl = top_promotions_frame(frame, signal="pl")
    assert by_pl["Reported Underlying"].tolist() == ["CDX", "EUR/USD", "KRx"]
    assert by_pl.loc[0, "P&L"] == -100.0
    assert top_promotions_frame(frame, signal="vol-score")[
        "Reported Underlying"
    ].tolist() == ["KRx", "EUR/USD", "CDX"]
    assert (
        top_promotions_frame(frame, signal="risk").loc[0, "Promotion Reason"]
        == "*, Big Risk, Big PL"
    )

    component = build_top_promotions_table(frame, signal="risk")
    assert "detail-table-wrap" in component.className.split()
    table_wrap = component.children[1]
    assert "detail-table" in table_wrap.className.split()
    table = table_wrap.children
    assert table.style_header["fontWeight"] == 850
    assert table.style_cell["textAlign"] == "left"
