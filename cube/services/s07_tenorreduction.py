"""Temporary reduced-tenor catalogue and injectable matrix provider boundary."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from cube.domain.s11_tenorreduction import (
    CREDIT_STANDARD_MAPPING_NAME,
    CREDIT_TENOR_MAPPING_COLUMNS,
)


DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "data"
REDUCED_TENOR_CATALOG_SOURCE = DATA_DIRECTORY / "s11_matrix.csv"
_TEMP = "TEMP_REPLACE_ME - "


def _matrix(
    rows: list[list[float]],
    *,
    index: list[str],
    columns: list[str],
) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        index=[f"{_TEMP}{value}" for value in index],
        columns=[f"{_TEMP}{value}" for value in columns],
        dtype=float,
    )


def _tenor_mapping(pairs: list[tuple[str, str]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            (f"{_TEMP}{full_tenor}", f"{_TEMP}{reduced_tenor}")
            for full_tenor, reduced_tenor in pairs
        ],
        columns=CREDIT_TENOR_MAPPING_COLUMNS,
    )


_TEMP_REDUCTION_MATRICES = {
    "IR_DELTA_STANDARD": _matrix(
        [
            [1.0, 1.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0],
        ],
        index=["1Y", "5Y", "10Y"],
        columns=["6M", "1Y", "2Y", "5Y", "10Y"],
    ),
    "FX_VEGA_STANDARD": _matrix(
        [
            [1.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ],
        index=["3M", "6M"],
        columns=["1M", "3M", "6M"],
    ),
}
# Fixture example only. A real deployment replaces these exact labels with its
# common 15-full-tenor to 5-reduced-tenor Credit definition.
_TEMP_CREDIT_TENOR_MAPPINGS = {
    CREDIT_STANDARD_MAPPING_NAME: _tenor_mapping(
        [
            ("1Y", "1Y"),
            ("3Y", "3Y"),
            ("4Y", "5Y"),
            ("5Y", "5Y"),
            ("7Y", "7Y"),
            ("10Y", "10Y"),
        ]
    ),
}


def get_reduced_tenor_catalog_source() -> Path:
    """Return the governed four-column selector without reading it at startup."""

    return REDUCED_TENOR_CATALOG_SOURCE


def get_reduced_tenor_matrix(matrix_name: str) -> pd.DataFrame:
    """Return one caller-owned reduction definition selected by ``MatrixName``.

    The legacy function name is retained for compatibility. Non-Credit names
    return numeric matrices; Credit names return the two-column mapping used by
    the direct map-and-sum path.
    """

    if not isinstance(matrix_name, str) or not matrix_name.strip():
        raise ValueError("matrix_name must be nonblank text")
    normalized = matrix_name.strip()
    if normalized in _TEMP_CREDIT_TENOR_MAPPINGS:
        return get_credit_tenor_mapping(normalized)
    try:
        matrix = _TEMP_REDUCTION_MATRICES[normalized]
    except KeyError as exc:
        raise KeyError(f"Unknown reduced-tenor matrix {normalized!r}") from exc
    return matrix.copy()


def get_reduced_tenor_matrix_bundle() -> dict[str, pd.DataFrame]:
    """Return the fixture's one-response non-Credit matrix secondary file."""

    return {
        matrix_name: matrix.copy()
        for matrix_name, matrix in _TEMP_REDUCTION_MATRICES.items()
    }


def get_credit_tenor_mapping(mapping_name: str) -> pd.DataFrame:
    """Return one caller-owned Credit Full Tenor to Reduced Tenor mapping."""

    if not isinstance(mapping_name, str) or not mapping_name.strip():
        raise ValueError("mapping_name must be nonblank text")
    normalized = mapping_name.strip()
    try:
        mapping = _TEMP_CREDIT_TENOR_MAPPINGS[normalized]
    except KeyError as exc:
        raise KeyError(f"Unknown Credit tenor mapping {normalized!r}") from exc
    return mapping.copy()


__all__ = [
    "REDUCED_TENOR_CATALOG_SOURCE",
    "get_credit_tenor_mapping",
    "get_reduced_tenor_catalog_source",
    "get_reduced_tenor_matrix",
    "get_reduced_tenor_matrix_bundle",
]
