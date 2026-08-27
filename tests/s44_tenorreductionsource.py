"""Temporary matrix-provider boundary checks."""

from __future__ import annotations

from cube.domain.s11_tenorreduction import (
    load_reduced_tenor_catalog,
    validate_credit_tenor_mapping,
    validate_reduction_matrix,
)
from cube.services.s07_tenorreduction import (
    get_credit_tenor_mapping,
    get_reduced_tenor_catalog_source,
    get_reduced_tenor_matrix,
)


def test_temp_provider_covers_every_seed_reduction_name() -> None:
    catalog = load_reduced_tenor_catalog(get_reduced_tenor_catalog_source())

    for row in catalog.drop_duplicates("MatrixName").to_dict("records"):
        name = row["MatrixName"]
        definition = get_reduced_tenor_matrix(name)
        if row["Risk Type"] == "Credit":
            validate_credit_tenor_mapping(
                definition,
                mapping_name=name,
            )
        else:
            validate_reduction_matrix(definition, matrix_name=name)


def test_temp_provider_returns_caller_owned_matrices() -> None:
    first = get_reduced_tenor_matrix("IR_DELTA_STANDARD")
    first.iloc[0, 0] = 999.0

    second = get_reduced_tenor_matrix("IR_DELTA_STANDARD")
    assert second.iloc[0, 0] == 1.0


def test_temp_provider_returns_caller_owned_credit_mappings() -> None:
    first = get_credit_tenor_mapping("CREDIT_STANDARD")
    first.iloc[0, 1] = "changed"

    second = get_credit_tenor_mapping("CREDIT_STANDARD")
    assert second.iloc[0, 1] != "changed"
