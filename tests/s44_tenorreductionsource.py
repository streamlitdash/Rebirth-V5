"""Temporary matrix-provider boundary checks."""

from __future__ import annotations

from cube.domain.s11_tenorreduction import load_reduced_tenor_catalog
from cube.services.s07_tenorreduction import (
    get_reduced_tenor_catalog_source,
    get_reduced_tenor_matrix,
)


def test_temp_provider_covers_every_seed_matrix_name() -> None:
    catalog = load_reduced_tenor_catalog(get_reduced_tenor_catalog_source())

    for name in catalog["MatrixName"].drop_duplicates():
        matrix = get_reduced_tenor_matrix(name)
        assert not matrix.empty
        assert matrix.index.is_unique
        assert matrix.columns.is_unique


def test_temp_provider_returns_caller_owned_matrices() -> None:
    first = get_reduced_tenor_matrix("IR_DELTA_STANDARD")
    first.iloc[0, 0] = 999.0

    second = get_reduced_tenor_matrix("IR_DELTA_STANDARD")
    assert second.iloc[0, 0] == 1.0
