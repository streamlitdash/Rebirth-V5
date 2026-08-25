"""MarketBook, status routing, risk join, and tenor-order tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cube.domain.s01_schema import (
    TENOR_OPTION,
    TENOR_OPTION_ORDER,
    TENOR_SWAP,
    TENOR_SWAP_ORDER,
)
from cube.domain.s03_calculations import (
    get_product_market,
    get_product_market_status,
    get_product_pl,
    get_product_risk,
)
from cube.domain.s07_governance import apply_thresholds
from cube.domain.s02_products import (
    CURRENT,
    MARKET_AVAILABLE,
    MARKET_STATUS,
    OFFICIAL,
    OPEN,
    PL,
    PRODUCT_SPECS,
)
from cube.domain.s10_search import build_search_catalog


SPEC = PRODUCT_SPECS["irdelta"]


def _risk() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["USD-SOFR", "2Y", "BOOK_A", "Connector Rates", 20.0, 2.0, 40.0],
            ["USD-SOFR", "10Y", "BOOK_A", "Connector Rates", 10.0, 1.0, 65.0],
        ],
        columns=[
            "Underlying",
            TENOR_SWAP,
            "Portfolio",
            "Group",
            "Risk",
            "dRisk",
            "Vol Score",
        ],
    )


def _open() -> pd.DataFrame:
    # The market deliberately owns a non-lexical tenor order.
    return pd.DataFrame(
        [
            ["USD-SOFR", "10Y", 0, 4.00],
            ["USD-SOFR", "2Y", 1, 4.10],
            ["USD-SOFR", "30Y", 2, 4.20],
        ],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, OPEN],
    )


def _current(status: str = OFFICIAL) -> pd.DataFrame:
    frame = pd.DataFrame(
        [
            ["USD-SOFR", "10Y", 0, 4.05],
            ["USD-SOFR", "2Y", 1, 4.20],
            ["USD-SOFR", "30Y", 2, 4.35],
        ],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, CURRENT],
    )
    frame[MARKET_STATUS] = status
    return frame


def test_risk_group_is_required_but_its_value_is_connector_owned() -> None:
    raw = _risk()
    raw["Group"] = ["Anything I Want", 17]

    result = get_product_risk(SPEC, "2026-07-17", raw)

    assert result["Group"].tolist() == ["Anything I Want", 17]

    with pytest.raises(ValueError, match="missing required columns: \\['Group'\\]"):
        get_product_risk(SPEC, "2026-07-17", raw.drop(columns="Group"))


@pytest.mark.parametrize("value", [-0.001, 100.001])
def test_risk_vol_score_is_connector_owned_and_bounded(value: float) -> None:
    raw = _risk()
    raw.loc[0, "Vol Score"] = value

    with pytest.raises(ValueError, match="Vol Score.*between 0 and 100"):
        get_product_risk(SPEC, "2026-07-17", raw)


def test_risk_measures_zero_explicit_nonfinite_and_preserve_true_blanks() -> None:
    raw = pd.DataFrame(
        [
            ["USD-SOFR", "1Y", "BOOK_INF", "Rates", np.inf, "-Infinity", 40.0],
            ["USD-SOFR", "2Y", "BOOK_NA", "Rates", "NA", "N/A", 40.0],
            ["USD-SOFR", "3Y", "BOOK_BLANK_RISK", "Rates", "", 3.0, 40.0],
            ["USD-SOFR", "5Y", "BOOK_BLANK_DRISK", "Rates", 5.0, "", 40.0],
            ["USD-SOFR", "10Y", "BOOK_NAN", "Rates", "NaN", np.nan, 40.0],
        ],
        columns=[
            "Underlying",
            TENOR_SWAP,
            "Portfolio",
            "Group",
            "Risk",
            "dRisk",
            "Vol Score",
        ],
    )

    result = get_product_risk(SPEC, "2026-07-17", raw).set_index("Portfolio")

    assert "BOOK_BLANK_RISK" not in result.index
    assert result.loc["BOOK_INF", ["Risk", "dRisk"]].tolist() == [0.0, 0.0]
    assert result.loc["BOOK_NA", ["Risk", "dRisk"]].tolist() == [0.0, 0.0]
    assert result.loc["BOOK_NAN", "Risk"] == 0.0
    assert pd.isna(result.loc["BOOK_NAN", "dRisk"])
    assert pd.isna(result.loc["BOOK_BLANK_DRISK", "dRisk"])


def test_risk_measure_still_rejects_unrecognized_non_numeric_text() -> None:
    raw = _risk()
    raw["Risk"] = raw["Risk"].astype(object)
    raw.loc[0, "Risk"] = "not-a-number"

    with pytest.raises(ValueError, match="Risk.*non-numeric"):
        get_product_risk(SPEC, "2026-07-17", raw)


def test_market_book_keeps_market_only_tenors_and_dynamic_status() -> None:
    market = get_product_market(
        SPEC,
        "2026-07-20",
        _open(),
        _current(),
        market_status=OFFICIAL,
    )

    assert market[TENOR_SWAP].tolist() == ["10Y", "2Y", "30Y"]
    assert market[MARKET_STATUS].eq(OFFICIAL).all()
    assert market[MARKET_AVAILABLE].eq(True).all()
    assert market["Move"].round(8).tolist() == [0.05, 0.10, 0.15]


@pytest.mark.parametrize("status", ["Live", OFFICIAL])
def test_market_status_is_selected_by_the_caller_not_renamed(status: str) -> None:
    raw = _current(status)

    result = get_product_market_status(
        SPEC,
        "2026-07-20",
        raw,
        market_status=status,
    )

    assert CURRENT in result
    assert "Live/Official" not in result
    assert result[MARKET_STATUS].eq(status).all()


def test_market_status_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="must be exactly 'Live'"):
        get_product_market_status(
            SPEC,
            "2026-07-20",
            _current(OFFICIAL),
            market_status="Live",
        )


def test_open_order_wins_when_current_disagrees_on_the_same_tenor() -> None:
    current = _current()
    current.loc[current[TENOR_SWAP].eq("10Y"), TENOR_SWAP_ORDER] = 9

    market = get_product_market(
        SPEC,
        "2026-07-20",
        _open(),
        current,
        market_status=OFFICIAL,
    )

    assert market.set_index(TENOR_SWAP)[TENOR_SWAP_ORDER].to_dict() == {
        "10Y": 0,
        "2Y": 1,
        "30Y": 2,
    }


def test_disjoint_market_legs_with_the_same_rank_are_numbered_together() -> None:
    open_frame = pd.DataFrame(
        [["USD-SOFR", "1Y", 0, 100.0]],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, OPEN],
    )
    current_frame = pd.DataFrame(
        [["USD-SOFR", "2Y", 0, 101.0]],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, CURRENT],
    )

    market = get_product_market(
        SPEC,
        "2026-07-20",
        open_frame,
        current_frame,
        market_status=OFFICIAL,
    ).set_index(TENOR_SWAP)

    assert market[TENOR_SWAP_ORDER].to_dict() == {"1Y": 0, "2Y": 1}
    assert market.loc["1Y", [OPEN, CURRENT, "Move"]].tolist() == [100.0, 100.0, 0.0]
    assert market.loc["2Y", [OPEN, CURRENT, "Move"]].tolist() == [101.0, 101.0, 0.0]


def test_colliding_swap_and_option_orders_are_numbered_deterministically() -> None:
    spec = PRODUCT_SPECS["irdeltavega"]
    keys = [
        ["USD-SWAPTION", "1Y", "1M", 0, 0],
        ["USD-SWAPTION", "1Y", "3M", 0, 0],
        ["USD-SWAPTION", "2Y", "1M", 0, 0],
        ["USD-SWAPTION", "2Y", "3M", 0, 0],
    ]
    open_frame = pd.DataFrame(
        [[*row, 100.0] for row in keys],
        columns=[
            "Underlying",
            TENOR_SWAP,
            TENOR_OPTION,
            TENOR_SWAP_ORDER,
            TENOR_OPTION_ORDER,
            OPEN,
        ],
    )
    current_frame = pd.DataFrame(
        [
            [row[0], row[1], row[2], 9 if row[1] == "1Y" else 8, 7, 101.0]
            for row in keys
        ],
        columns=[
            "Underlying",
            TENOR_SWAP,
            TENOR_OPTION,
            TENOR_SWAP_ORDER,
            TENOR_OPTION_ORDER,
            CURRENT,
        ],
    )

    market = get_product_market(
        spec,
        "2026-07-20",
        open_frame,
        current_frame,
        market_status=OFFICIAL,
    )

    swap_orders = (
        market[[TENOR_SWAP, TENOR_SWAP_ORDER]].drop_duplicates().set_index(TENOR_SWAP)
    )
    option_orders = (
        market[[TENOR_OPTION, TENOR_OPTION_ORDER]]
        .drop_duplicates()
        .set_index(TENOR_OPTION)
    )
    assert swap_orders[TENOR_SWAP_ORDER].to_dict() == {"1Y": 0, "2Y": 1}
    assert option_orders[TENOR_OPTION_ORDER].to_dict() == {"1M": 0, "3M": 1}


def test_risk_join_shows_only_risk_tenors_in_market_order() -> None:
    market = get_product_market(
        SPEC,
        "2026-07-20",
        _open(),
        _current(),
        market_status=OFFICIAL,
    )
    risk = get_product_risk(SPEC, "2026-07-17", _risk())

    joined = get_product_pl(
        SPEC,
        "2026-07-17",
        validated_risk=risk,
        validated_market=market,
        market_date="2026-07-20",
        market_status=OFFICIAL,
    )

    assert joined[TENOR_SWAP].tolist() == ["10Y", "2Y"]
    assert "30Y" not in set(joined[TENOR_SWAP])
    assert joined["Group"].tolist() == ["Connector Rates", "Connector Rates"]
    assert joined[PL].round(8).tolist() == [0.5, 2.0]

    joined["Portfolio Mapped"] = True
    thresholds = pd.DataFrame(
        [["IR", "Delta", 1_000.0, 1_000.0, 1_000.0]],
        columns=["Risk Type", "Risk Greek", "PL", "Risk", "dRisk"],
    )
    enriched = apply_thresholds(joined, thresholds)
    assert enriched["Group"].tolist() == ["Connector Rates", "Connector Rates"]


def test_quick_risk_intersects_tenors_but_quick_market_reads_full_market_book() -> None:
    market = get_product_market(
        SPEC,
        "2026-07-20",
        _open(),
        _current(),
        market_status=OFFICIAL,
    )
    risk = get_product_risk(SPEC, "2026-07-17", _risk())
    catalog = build_search_catalog(
        revision=7,
        risk_frames={SPEC.source_type: risk},
        market_frames={SPEC.source_type: market},
        risk_dates={SPEC.source_type: pd.Timestamp("2026-07-17")},
        market_date=pd.Timestamp("2026-07-20"),
    )
    identity = "IR | Delta | USD-SOFR"

    risk_view = catalog.pivot_combined(identity, index_columns=(TENOR_SWAP,))
    market_view = catalog.pivot_market_exact(identity, index_columns=(TENOR_SWAP,))

    assert catalog.combine_udl_options() == (identity,)
    assert catalog.market_udl_options() == (identity,)
    assert risk_view.frame[TENOR_SWAP].tolist() == ["10Y", "2Y"]
    assert market_view.frame[TENOR_SWAP].tolist() == ["10Y", "2Y", "30Y"]
    assert market_view.frame[TENOR_SWAP_ORDER].tolist() == [0, 1, 2]
    assert market_view.frame[MARKET_STATUS].eq(OFFICIAL).all()
    assert market_view.frame[CURRENT].round(8).tolist() == [4.05, 4.20, 4.35]


def test_exact_market_surface_keeps_every_ranked_connector_tenor() -> None:
    spec = PRODUCT_SPECS["irdeltavega"]
    swaps = [f"SWAP-{index:02d}" for index in range(30)]
    options = [f"OPT-{index:02d}" for index in range(30)]
    open_rows = [
        ["USD-SWAPTION", swap, option, swap_rank, option_rank, 100.0]
        for swap_rank, swap in enumerate(reversed(swaps))
        for option_rank, option in enumerate(reversed(options))
    ]
    current_rows = [
        ["USD-SWAPTION", swap, option, swap_rank, option_rank, 101.0]
        for swap_rank, swap in enumerate(reversed(swaps))
        for option_rank, option in enumerate(reversed(options))
    ]
    open_frame = pd.DataFrame(
        open_rows,
        columns=[
            "Underlying",
            TENOR_SWAP,
            TENOR_OPTION,
            TENOR_SWAP_ORDER,
            TENOR_OPTION_ORDER,
            OPEN,
        ],
    )
    current_frame = pd.DataFrame(
        current_rows,
        columns=[
            "Underlying",
            TENOR_SWAP,
            TENOR_OPTION,
            TENOR_SWAP_ORDER,
            TENOR_OPTION_ORDER,
            CURRENT,
        ],
    )
    current_frame[MARKET_STATUS] = OFFICIAL
    market = get_product_market(
        spec,
        "2026-07-20",
        open_frame,
        current_frame,
        market_status=OFFICIAL,
    )
    catalog = build_search_catalog(
        revision=1,
        risk_frames={},
        market_frames={spec.source_type: market},
        risk_dates={},
        market_date=pd.Timestamp("2026-07-20"),
    )

    result = catalog.pivot_market_exact(
        "IR | DeltaVega | USD-SWAPTION",
        index_columns=(TENOR_SWAP, TENOR_OPTION),
    )

    assert result.total == 900
    assert len(result.frame) == 900
    assert result.frame[TENOR_SWAP_ORDER].min() == 0
    assert result.frame[TENOR_SWAP_ORDER].max() == 29
    assert result.frame[TENOR_OPTION_ORDER].min() == 0
    assert result.frame[TENOR_OPTION_ORDER].max() == 29


def test_market_dropdown_search_is_tokenized_but_selection_is_exact() -> None:
    market = get_product_market(
        SPEC,
        "2026-07-20",
        _open(),
        _current(),
        market_status=OFFICIAL,
    )
    risk = get_product_risk(SPEC, "2026-07-17", _risk())
    catalog = build_search_catalog(
        revision=1,
        risk_frames={SPEC.source_type: risk},
        market_frames={SPEC.source_type: market},
        risk_dates={SPEC.source_type: pd.Timestamp("2026-07-17")},
        market_date=pd.Timestamp("2026-07-20"),
    )

    for typed_query in ("ir delta usd", "IR DELTA USD", "Ir DeLtA UsD"):
        assert catalog.search_market_udl_options(typed_query) == (
            "IR | Delta | USD-SOFR",
        )
    assert catalog.pivot_market_exact(
        "ir delta usd", index_columns=(TENOR_SWAP,)
    ).frame.empty


def test_search_catalog_keeps_exact_indexes_without_row_level_postings() -> None:
    market = get_product_market(
        SPEC,
        "2026-07-20",
        _open(),
        _current(),
        market_status=OFFICIAL,
    )
    risk = get_product_risk(SPEC, "2026-07-17", _risk())
    catalog = build_search_catalog(
        revision=1,
        risk_frames={SPEC.source_type: risk},
        market_frames={SPEC.source_type: market},
        risk_dates={SPEC.source_type: pd.Timestamp("2026-07-17")},
        market_date=pd.Timestamp("2026-07-20"),
    )

    for typed_query in ("ir delta usd", "IR DELTA USD", "Ir DeLtA UsD"):
        assert catalog.search_combine_udl_options(typed_query) == (
            "IR | Delta | USD-SOFR",
        )
    assert catalog.pivot_combined(
        "ir delta usd", index_columns=(TENOR_SWAP,)
    ).frame.empty
    assert not hasattr(catalog, "_risk_postings")
    assert not hasattr(catalog, "_market_postings")
    assert not hasattr(catalog, "_risk_pivot_postings")
    assert not hasattr(catalog, "search_risk")
    assert not hasattr(catalog, "search_market")


def test_quick_risk_identity_options_follow_the_active_governed_filters() -> None:
    market = get_product_market(
        SPEC,
        "2026-07-20",
        _open(),
        _current(),
        market_status=OFFICIAL,
    )
    risk = get_product_risk(SPEC, "2026-07-17", _risk())
    catalog = build_search_catalog(
        revision=1,
        risk_frames={SPEC.source_type: risk},
        market_frames={SPEC.source_type: market},
        risk_dates={SPEC.source_type: pd.Timestamp("2026-07-17")},
        market_date=pd.Timestamp("2026-07-20"),
    )
    identity = "IR | Delta | USD-SOFR"

    assert catalog.search_combine_udl_options(
        None,
        risk_filters={"Portfolio": ["Unspecified"]},
    ) == (identity,)
    assert (
        catalog.search_combine_udl_options(
            None,
            risk_filters={"Portfolio": ["BOOK_MISSING"]},
        )
        == ()
    )
    assert (
        catalog.search_combine_udl_options(
            None,
            include=identity,
            risk_filters={"Portfolio": ["Unspecified"]},
            exclude_selected=True,
        )
        == ()
    )


def test_market_rollup_copies_each_available_single_leg_for_continuity() -> None:
    open_frame = pd.DataFrame(
        [
            ["USD-SOFR", "1Y", 0, 100.0],
            ["USD-SOFR", "2Y", 1, 1_000.0],
        ],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, OPEN],
    )
    current_frame = pd.DataFrame(
        [
            ["USD-SOFR", "1Y", 0, 110.0],
            ["USD-SOFR", "3Y", 2, 3_000.0],
        ],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, CURRENT],
    )
    current_frame[MARKET_STATUS] = OFFICIAL
    market = get_product_market(
        SPEC,
        "2026-07-20",
        open_frame,
        current_frame,
        market_status=OFFICIAL,
    )
    catalog = build_search_catalog(
        revision=1,
        risk_frames={},
        market_frames={SPEC.source_type: market},
        risk_dates={},
        market_date=pd.Timestamp("2026-07-20"),
    )

    parent = catalog.pivot_market_exact(
        "IR | Delta | USD-SOFR",
        index_columns=("Underlying",),
    ).frame.iloc[0]
    leaves = catalog.pivot_market_exact(
        "IR | Delta | USD-SOFR",
        index_columns=(TENOR_SWAP,),
    ).frame.set_index(TENOR_SWAP)

    assert parent[OPEN] == pytest.approx((100.0 + 1_000.0 + 3_000.0) / 3.0)
    assert parent[CURRENT] == pytest.approx((110.0 + 1_000.0 + 3_000.0) / 3.0)
    assert parent["Move"] == pytest.approx(parent[CURRENT] - parent[OPEN])
    assert leaves.loc["1Y", [OPEN, CURRENT, "Move"]].tolist() == [100.0, 110.0, 10.0]
    assert leaves.loc["2Y", [OPEN, CURRENT, "Move"]].tolist() == [
        1_000.0,
        1_000.0,
        0.0,
    ]
    assert leaves.loc["3Y", [OPEN, CURRENT, "Move"]].tolist() == [
        3_000.0,
        3_000.0,
        0.0,
    ]


def test_blank_quote_cells_are_completed_from_the_other_market_leg() -> None:
    open_frame = pd.DataFrame(
        [
            ["USD-SOFR", "1Y", 0, ""],
            ["USD-SOFR", "2Y", 1, 101.0],
            ["USD-SOFR", "3Y", 2, ""],
        ],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, OPEN],
    )
    current_frame = pd.DataFrame(
        [
            ["USD-SOFR", "1Y", 0, 100.0],
            ["USD-SOFR", "2Y", 1, ""],
            ["USD-SOFR", "3Y", 2, ""],
        ],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, CURRENT],
    )

    market = get_product_market(
        SPEC,
        "2026-07-20",
        open_frame,
        current_frame,
        market_status=OFFICIAL,
    ).set_index(TENOR_SWAP)

    assert market.loc["1Y", [OPEN, CURRENT, "Move"]].tolist() == [100.0, 100.0, 0.0]
    assert market.loc["2Y", [OPEN, CURRENT, "Move"]].tolist() == [101.0, 101.0, 0.0]
    assert market.loc["1Y", "Market Data Status"] == (
        "Available; Open copied from Current"
    )
    assert market.loc["2Y", "Market Data Status"] == (
        "Available; Current copied from Open"
    )
    assert market.loc["3Y", [OPEN, CURRENT, "Move"]].isna().all()
    assert not bool(market.loc["3Y", MARKET_AVAILABLE])


def test_nonfinite_calculated_pl_becomes_zero_but_unavailable_pl_stays_blank() -> None:
    spec = PRODUCT_SPECS["fxdelta"]
    risk = pd.DataFrame(
        [
            ["DIV_ZERO", "BOOK_A", "FX", 10.0, 1.0, 40.0],
            ["COPIED_ZERO", "BOOK_A", "FX", 10.0, 1.0, 40.0],
            ["NO_MARKET", "BOOK_A", "FX", 10.0, 1.0, 40.0],
        ],
        columns=["Underlying", "Portfolio", "Group", "Risk", "dRisk", "Vol Score"],
    )
    open_frame = pd.DataFrame(
        [["DIV_ZERO", 0.0], ["COPIED_ZERO", ""]],
        columns=["Underlying", OPEN],
    )
    current_frame = pd.DataFrame(
        [["DIV_ZERO", 1.0], ["COPIED_ZERO", 0.0]],
        columns=["Underlying", CURRENT],
    )

    result = get_product_pl(
        spec,
        "2026-07-17",
        risk_source=risk,
        open_source=open_frame,
        status_source=current_frame,
        market_date="2026-07-20",
        market_status=OFFICIAL,
    ).set_index("Underlying")

    assert result.loc["DIV_ZERO", PL] == 0.0
    assert result.loc["DIV_ZERO", "Market Data Status"] == (
        "Open is zero; nonfinite percentage P&L normalized to zero"
    )
    assert result.loc["COPIED_ZERO", PL] == 0.0
    assert result.loc["COPIED_ZERO", "Market Data Status"] == (
        "Available; Open copied from Current"
    )
    assert pd.isna(result.loc["NO_MARKET", PL])
    assert not bool(result.loc["NO_MARKET", MARKET_AVAILABLE])


def test_overflowing_absolute_pl_is_normalized_to_zero() -> None:
    risk = pd.DataFrame(
        [["USD-SOFR", "1Y", "BOOK_BIG", "Rates", 1e308, 0.0, 40.0]],
        columns=[
            "Underlying",
            TENOR_SWAP,
            "Portfolio",
            "Group",
            "Risk",
            "dRisk",
            "Vol Score",
        ],
    )
    open_frame = pd.DataFrame(
        [["USD-SOFR", "1Y", 0, 0.0]],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, OPEN],
    )
    current_frame = pd.DataFrame(
        [["USD-SOFR", "1Y", 0, 1e308]],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, CURRENT],
    )

    result = get_product_pl(
        SPEC,
        "2026-07-17",
        risk_source=risk,
        open_source=open_frame,
        status_source=current_frame,
        market_date="2026-07-20",
        market_status=OFFICIAL,
    )

    assert result.loc[0, PL] == 0.0


def test_overflowing_taylor_risk_and_pl_are_normalized_to_zero() -> None:
    spec = PRODUCT_SPECS["irgamma"]
    risk = pd.DataFrame(
        [["USD-SOFR", "1Y", "BOOK_BIG", "Rates", 1e308, 0.0, 40.0]],
        columns=[
            "Underlying",
            TENOR_SWAP,
            "Portfolio",
            "Group",
            "Risk",
            "dRisk",
            "Vol Score",
        ],
    )
    open_frame = pd.DataFrame(
        [["USD-SOFR", "1Y", 0, 0.0]],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, OPEN],
    )
    current_frame = pd.DataFrame(
        [["USD-SOFR", "1Y", 0, 1e308]],
        columns=["Underlying", TENOR_SWAP, TENOR_SWAP_ORDER, CURRENT],
    )

    result = get_product_pl(
        spec,
        "2026-07-17",
        risk_source=risk,
        open_source=open_frame,
        status_source=current_frame,
        market_date="2026-07-20",
        market_status=OFFICIAL,
    )

    sourced = result.loc[result["Split"].eq("Risk")].iloc[0]
    derived = result.loc[result["Split"].eq("Gamma")].iloc[0]
    assert sourced[PL] == 0.0
    assert derived["Risk"] == 0.0
    assert derived[PL] == 0.0
