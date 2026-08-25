"""Focused contracts for the pure reduced-Tenor Swap engine."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from cube.domain import s11_tenorreduction as reduction_module
from cube.domain.s11_tenorreduction import (
    MATRIX_NAME,
    REDUCED_TENOR_CATALOG_COLUMNS,
    ReducedTenorReducer,
    load_reduced_tenor_catalog,
    validate_reduction_matrix,
)


PROJECT = Path(__file__).resolve().parents[1]


def _catalog(underlying: str = "USD SOFR") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Risk Type": "IR",
                "Risk Greek": "Delta",
                "Underlying": underlying,
                MATRIX_NAME: "IR_STANDARD",
            }
        ],
        columns=REDUCED_TENOR_CATALOG_COLUMNS,
    )


def _matrix() -> pd.DataFrame:
    return pd.DataFrame(
        [[1.0, 1.0, 0.0], [0.0, 0.5, 1.0]],
        index=["2Y", "Long"],
        columns=["1Y", "2Y", "5Y"],
    )


def _full_frame() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    values = {
        "P1": ([10.0, 20.0, 30.0], [1.0, 2.0, 3.0], [100.0, 200.0, 300.0]),
        "P2": ([4.0, 5.0, 6.0], [0.4, 0.5, 0.6], [40.0, 50.0, 60.0]),
    }
    for portfolio, (risk, drisk, pl) in values.items():
        for order, tenor in enumerate(("1Y", "2Y", "5Y")):
            rows.append(
                {
                    "Source Type": "ir/delta",
                    "Risk Type": "IR",
                    "Risk Greek": "Delta",
                    "Underlying": "USD SOFR",
                    "Tenor Swap": tenor,
                    "Tenor Swap Order": order,
                    "Portfolio": portfolio,
                    "Risk": risk[order],
                    "dRisk": drisk[order],
                    "PL": pl[order],
                    "Risk Expo": risk[order] * 0.75,
                    "Risk Hedges": risk[order] * 0.25,
                    "PL Expo": pl[order] * 0.75,
                    "PL Hedges": pl[order] * 0.25,
                    "Open": float(order + 1),
                    "Current": float(order + 2),
                    "Move": 1.0,
                    "Market Available": True,
                    "Market Data Status": "Available",
                    "Vol Score": 42.0,
                }
            )
    return pd.DataFrame(rows)


def _market_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Source Type": ["ir/delta", "ir/delta", "ir/delta"],
            "Underlying": ["USD SOFR"] * 3,
            "Tenor Swap": ["1Y", "2Y", "5Y"],
            "Open": [1.0, 2.0, 5.0],
            "Current": [1.1, 2.2, 5.5],
            "Move": [0.1, 0.2, 0.5],
            "Market Available": [True, True, True],
            "Market Data Status": ["Available"] * 3,
        }
    )


def test_catalog_is_exact_unique_and_limited_to_one_axis_swap_products() -> None:
    loaded = load_reduced_tenor_catalog(_catalog())
    assert tuple(loaded.columns) == REDUCED_TENOR_CATALOG_COLUMNS

    duplicated = pd.concat([_catalog(), _catalog()], ignore_index=True)
    with pytest.raises(ValueError, match="identities must be unique"):
        load_reduced_tenor_catalog(duplicated)

    scalar = _catalog().assign(**{"Risk Type": "FX", "Risk Greek": "Delta"})
    with pytest.raises(ValueError, match="one-axis Tenor Swap"):
        load_reduced_tenor_catalog(scalar)

    surface = _catalog().assign(**{"Risk Greek": "DeltaVega"})
    with pytest.raises(ValueError, match="one-axis Tenor Swap"):
        load_reduced_tenor_catalog(surface)

    wrong_order = _catalog()[list(reversed(REDUCED_TENOR_CATALOG_COLUMNS))]
    with pytest.raises(ValueError, match="columns must be exactly"):
        load_reduced_tenor_catalog(wrong_order)


def test_matrix_contract_requires_finite_numeric_unique_labelled_axes() -> None:
    validated = validate_reduction_matrix(_matrix(), matrix_name="IR_STANDARD")
    assert validated.index.tolist() == ["2Y", "Long"]
    assert validated.columns.tolist() == ["1Y", "2Y", "5Y"]
    assert validated.dtypes.eq(float).all()

    duplicate_columns = _matrix()
    duplicate_columns.columns = ["1Y", "1Y", "5Y"]
    with pytest.raises(ValueError, match="column labels must be unique"):
        validate_reduction_matrix(duplicate_columns)

    nonfinite = _matrix()
    nonfinite.iloc[0, 0] = np.inf
    with pytest.raises(ValueError, match="finite numbers"):
        validate_reduction_matrix(nonfinite)


def test_reducer_batches_positions_and_transforms_all_additive_measures() -> None:
    calls: list[str] = []

    def provider(name: str) -> pd.DataFrame:
        calls.append(name)
        return _matrix()

    reducer = ReducedTenorReducer(_catalog(), provider)
    reduced = reducer.reduce(_full_frame(), market_frame=_market_frame())
    # A second reduction reuses the provider-owned matrix from the bounded cache.
    reducer.reduce(_full_frame(), market_frame=_market_frame())

    assert calls == ["IR_STANDARD"]
    assert reduced[["Portfolio", "Tenor Swap"]].to_records(index=False).tolist() == [
        ("P1", "2Y"),
        ("P1", "Long"),
        ("P2", "2Y"),
        ("P2", "Long"),
    ]
    assert reduced["Tenor Swap Order"].tolist() == [0, 1, 0, 1]

    by_position = reduced.set_index(["Portfolio", "Tenor Swap"])
    assert by_position.loc[("P1", "2Y"), "Risk"] == pytest.approx(30.0)
    assert by_position.loc[("P1", "Long"), "Risk"] == pytest.approx(40.0)
    assert by_position.loc[("P2", "2Y"), "Risk"] == pytest.approx(9.0)
    assert by_position.loc[("P2", "Long"), "Risk"] == pytest.approx(8.5)
    assert by_position.loc[("P1", "Long"), "dRisk"] == pytest.approx(4.0)
    assert by_position.loc[("P1", "Long"), "PL"] == pytest.approx(400.0)
    assert by_position.loc[("P1", "2Y"), "Risk Expo"] == pytest.approx(22.5)
    assert by_position.loc[("P1", "2Y"), "Risk Hedges"] == pytest.approx(7.5)
    assert by_position.loc[("P2", "Long"), "PL Expo"] == pytest.approx(63.75)
    assert by_position.loc[("P2", "Long"), "PL Hedges"] == pytest.approx(21.25)


def test_shared_matrix_name_batches_each_underlying_and_fetches_provider_once() -> None:
    second = _full_frame().assign(Underlying="EUR ESTR")
    frame = pd.concat([_full_frame(), second], ignore_index=True)
    catalog = pd.concat([_catalog(), _catalog("EUR ESTR")], ignore_index=True)
    market = pd.concat(
        [
            _market_frame(),
            _market_frame().assign(
                Underlying="EUR ESTR",
                Open=[10.0, 20.0, 50.0],
                Current=[11.0, 22.0, 55.0],
                Move=[1.0, 2.0, 5.0],
            ),
        ],
        ignore_index=True,
    )
    calls: list[str] = []
    reduced = ReducedTenorReducer(
        catalog, lambda name: calls.append(name) or _matrix()
    ).reduce(frame, market_frame=market)

    quotes = reduced.loc[
        reduced["Tenor Swap"].eq("2Y"), ["Underlying", "Open"]
    ].drop_duplicates()
    assert quotes.to_records(index=False).tolist() == [
        ("USD SOFR", 2.0),
        ("EUR ESTR", 20.0),
    ]
    assert calls == ["IR_STANDARD"]


def test_reducer_chunks_large_position_batches_without_changing_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = ReducedTenorReducer(_catalog(), lambda _: _matrix()).reduce(
        _full_frame(), market_frame=_market_frame()
    )
    monkeypatch.setattr(reduction_module, "_REDUCTION_WORKING_SET_BYTES", 1)

    chunked = ReducedTenorReducer(_catalog(), lambda _: _matrix()).reduce(
        _full_frame(), market_frame=_market_frame()
    )

    pd.testing.assert_frame_equal(chunked, expected)


def test_market_quotes_are_exact_label_matches_and_never_matrix_products() -> None:
    reduced = ReducedTenorReducer(_catalog(), lambda _: _matrix()).reduce(
        _full_frame(), market_frame=_market_frame()
    )
    matched = reduced[reduced["Tenor Swap"].eq("2Y")]
    assert matched["Open"].tolist() == [2.0, 2.0]
    assert matched["Current"].tolist() == [2.2, 2.2]
    assert matched["Move"].tolist() == [0.2, 0.2]
    assert matched["Market Available"].tolist() == [True, True]
    assert matched["Market Data Status"].tolist() == ["Available", "Available"]

    unmatched = reduced[reduced["Tenor Swap"].eq("Long")]
    assert unmatched["Open"].isna().all()
    assert unmatched["Current"].isna().all()
    assert unmatched["Move"].isna().all()
    assert unmatched["Market Available"].tolist() == [False, False]
    assert unmatched["Market Data Status"].tolist() == ["", ""]


def test_unmapped_and_non_one_axis_sources_pass_through_without_provider_calls() -> (
    None
):
    full = _full_frame()
    unmapped = full.iloc[[0]].assign(Underlying="EUR ESTR", Portfolio="U1")
    surface = full.iloc[[1]].assign(
        **{
            "Source Type": "ir/deltavega",
            "Portfolio": "S1",
            "Tenor Swap": "2Y",
        }
    )
    frame = pd.concat([unmapped, surface], ignore_index=True)
    calls: list[str] = []
    reducer = ReducedTenorReducer(
        _catalog(), lambda name: calls.append(name) or _matrix()
    )

    result = reducer.reduce(frame)

    pd.testing.assert_frame_equal(result, frame)
    assert calls == []


def test_incomplete_matrix_skips_mapped_source_group_without_losing_risk() -> None:
    incomplete = _matrix().drop(columns="5Y")
    frame = _full_frame()
    result = ReducedTenorReducer(_catalog(), lambda _: incomplete).reduce(frame)
    pd.testing.assert_frame_equal(result, frame)


@pytest.mark.parametrize(
    "failure",
    [RuntimeError("matrix service unavailable"), ValueError("malformed matrix")],
)
def test_unavailable_matrix_is_a_cached_full_tenor_passthrough(
    failure: Exception,
) -> None:
    calls: list[str] = []

    def provider(name: str) -> pd.DataFrame:
        calls.append(name)
        raise failure

    frame = _full_frame()
    reducer = ReducedTenorReducer(_catalog(), provider)

    first = reducer.reduce(frame)
    second = reducer.reduce(frame)

    pd.testing.assert_frame_equal(first, frame)
    pd.testing.assert_frame_equal(second, frame)
    assert calls == ["IR_STANDARD"]


def test_blank_additive_inputs_remain_blank_without_nonzero_matrix_support() -> None:
    frame = _full_frame().query("Portfolio == 'P1'").reset_index(drop=True)
    frame["dRisk"] = np.nan
    frame.loc[frame["Tenor Swap"].eq("1Y"), "PL"] = np.nan
    matrix = pd.DataFrame(
        [[1.0, 0.0, 0.0], [0.0, 1.0, 1.0]],
        index=["Front", "Back"],
        columns=["1Y", "2Y", "5Y"],
    )
    reduced = ReducedTenorReducer(_catalog(), lambda _: matrix).reduce(frame)
    by_tenor = reduced.set_index("Tenor Swap")

    assert pd.isna(by_tenor.loc["Front", "PL"])
    assert by_tenor.loc["Back", "PL"] == pytest.approx(500.0)
    assert reduced["dRisk"].isna().all()


def test_seed_catalog_has_only_the_governed_four_column_contract() -> None:
    seed = load_reduced_tenor_catalog(PROJECT / "data" / "s11_matrix.csv")
    assert tuple(seed.columns) == REDUCED_TENOR_CATALOG_COLUMNS
    assert not seed.empty
