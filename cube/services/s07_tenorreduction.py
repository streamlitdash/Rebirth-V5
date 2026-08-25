"""Temporary reduced-tenor catalogue and injectable matrix provider boundary."""

from __future__ import annotations

from pathlib import Path

import pandas as pd


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


def get_reduced_tenor_catalog_source() -> Path:
    """Return the governed four-column selector without reading it at startup."""

    return REDUCED_TENOR_CATALOG_SOURCE


def get_reduced_tenor_matrix(matrix_name: str) -> pd.DataFrame:
    """Return one caller-owned matrix selected by ``MatrixName``.

    Production deployments replace this function with the real matrix service;
    the Risk Explorer and reducer keep the same provider contract.
    """

    if not isinstance(matrix_name, str) or not matrix_name.strip():
        raise ValueError("matrix_name must be nonblank text")
    normalized = matrix_name.strip()
    try:
        matrix = _TEMP_REDUCTION_MATRICES[normalized]
    except KeyError as exc:
        raise KeyError(f"Unknown reduced-tenor matrix {normalized!r}") from exc
    return matrix.copy()


__all__ = [
    "REDUCED_TENOR_CATALOG_SOURCE",
    "get_reduced_tenor_catalog_source",
    "get_reduced_tenor_matrix",
]
