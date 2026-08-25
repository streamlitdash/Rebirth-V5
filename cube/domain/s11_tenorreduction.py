"""Pure post-P&L reduction of one-axis Tenor Swap risk vectors.

The matrix catalogue selects a named matrix by the reported risk identity.  A
matrix provider owns how that named matrix is obtained; this module only
validates the matrix contract and applies it.  Matrix rows are reduced tenors,
matrix columns are the full tenors, and only additive risk measures are
multiplied.  Market quotes are never multiplied: a reduced tenor receives an
existing quote only when its label exactly matches a full-tenor quote.
"""

from __future__ import annotations

import logging
from pathlib import Path
from threading import RLock
from typing import Callable, Protocol

import numpy as np
import pandas as pd

from cube.domain.s01_schema import TENOR_SWAP, TENOR_SWAP_ORDER
from cube.domain.s02_products import (
    CREDIT_MEASURE_COLUMNS,
    CURRENT,
    DRISK,
    DRISK_THRESHOLD,
    MARKET_AVAILABLE,
    MARKET_DATA_STATUS,
    MARKET_MOVE,
    OPEN,
    PL,
    PL_THRESHOLD,
    PRODUCT_SPECS_BY_SOURCE_TYPE,
    PROMOTION_REASON,
    PROMOTION_SCORE,
    RISK,
    RISK_GREEK,
    RISK_THRESHOLD,
    RISK_TYPE,
    SOURCE_TYPE,
    SWAP_AXIS,
    UNDERLYING,
    VOL_SCORE,
)


MATRIX_NAME = "MatrixName"
REDUCED_TENOR_CATALOG_COLUMNS = (
    RISK_TYPE,
    RISK_GREEK,
    UNDERLYING,
    MATRIX_NAME,
)
REDUCED_TENOR_CATALOG_KEY = (RISK_TYPE, RISK_GREEK, UNDERLYING)

# The first six names are the canonical dashboard breakdowns.  The P&L aliases
# make the pure reducer usable by callers which choose the display spelling
# before invoking it.  Only columns actually present in the input are used.
ADDITIVE_REDUCTION_COLUMNS = (
    RISK,
    DRISK,
    PL,
    "Risk Expo",
    "Risk Hedges",
    "dRisk Expo",
    "dRisk Hedges",
    "PL Expo",
    "PL Hedges",
    "P&L Expo",
    "P&L Hedges",
    *CREDIT_MEASURE_COLUMNS,
)
MARKET_QUOTE_COLUMNS = (
    OPEN,
    CURRENT,
    MARKET_MOVE,
    MARKET_AVAILABLE,
    MARKET_DATA_STATUS,
)

# These fields are metadata derived from a full-tenor row, rather than part of
# a position's identity or an additive vector.  A reduced position carries the
# first value in source order.  Promotion can then be recomputed by its owner.
_CARRIED_COLUMNS = (
    VOL_SCORE,
    PROMOTION_REASON,
    PROMOTION_SCORE,
    RISK_THRESHOLD,
    DRISK_THRESHOLD,
    PL_THRESHOLD,
)
_REQUIRED_FRAME_COLUMNS = (
    SOURCE_TYPE,
    RISK_TYPE,
    RISK_GREEK,
    UNDERLYING,
    TENOR_SWAP,
    TENOR_SWAP_ORDER,
    RISK,
    DRISK,
    PL,
)
_ELIGIBLE_SOURCE_TYPES = frozenset(
    source_type
    for source_type, spec in PRODUCT_SPECS_BY_SOURCE_TYPE.items()
    if spec.axes == (SWAP_AXIS,)
)
_ELIGIBLE_RISK_PAIRS = frozenset(
    (spec.risk_type, spec.risk_greek)
    for spec in PRODUCT_SPECS_BY_SOURCE_TYPE.values()
    if spec.axes == (SWAP_AXIS,)
)
_REDUCTION_WORKING_SET_BYTES = 32 * 1024 * 1024
_LOGGER = logging.getLogger(__name__)


class MatrixProvider(Protocol):
    """Return one raw reduction matrix by its catalogue name."""

    def __call__(self, matrix_name: str) -> pd.DataFrame: ...


CatalogSource = pd.DataFrame | str | Path
MatrixProviderLike = MatrixProvider | Callable[[str], pd.DataFrame]


def _duplicates(columns: pd.Index) -> list[object]:
    return columns[columns.duplicated()].unique().tolist()


def _clean_text_column(values: pd.Series, *, column: str) -> pd.Series:
    invalid_type = ~values.map(lambda value: isinstance(value, str))
    cleaned = values.astype("string").str.strip()
    invalid = invalid_type | cleaned.isna() | cleaned.eq("")
    if invalid.any():
        rows = values.index[invalid].tolist()[:5]
        raise ValueError(f"Reduced-tenor catalogue {column!r} is blank at rows {rows}")
    return cleaned.astype(str)


def load_reduced_tenor_catalog(source: CatalogSource) -> pd.DataFrame:
    """Load and validate the four-column matrix-selection catalogue.

    A catalogue identity is unique.  Matrix names may deliberately repeat so
    several underlyings can share one matrix.  Risk identities which do not
    describe a one-axis Tenor Swap product are rejected at this external-data
    boundary and can therefore never make a scalar or two-axis product
    reducible by accident.
    """

    if isinstance(source, pd.DataFrame):
        frame = source.copy()
    elif isinstance(source, (str, Path)):
        frame = pd.read_csv(source, dtype=str, keep_default_na=False)
    else:
        raise TypeError("reduced-tenor catalogue must be a DataFrame or path")

    if _duplicates(frame.columns):
        raise ValueError(
            f"Reduced-tenor catalogue has duplicate columns: {_duplicates(frame.columns)}"
        )
    actual_columns = tuple(frame.columns)
    if actual_columns != REDUCED_TENOR_CATALOG_COLUMNS:
        raise ValueError(
            "Reduced-tenor catalogue columns must be exactly "
            f"{list(REDUCED_TENOR_CATALOG_COLUMNS)} in that order"
        )

    for column in REDUCED_TENOR_CATALOG_COLUMNS:
        frame[column] = _clean_text_column(frame[column], column=column)

    duplicated = frame.duplicated(list(REDUCED_TENOR_CATALOG_KEY), keep=False)
    if duplicated.any():
        identities = (
            frame.loc[duplicated, list(REDUCED_TENOR_CATALOG_KEY)]
            .drop_duplicates()
            .head(5)
            .to_dict("records")
        )
        raise ValueError(
            f"Reduced-tenor catalogue identities must be unique: {identities}"
        )

    invalid_pair = ~pd.Series(
        list(zip(frame[RISK_TYPE], frame[RISK_GREEK], strict=True)),
        index=frame.index,
    ).isin(_ELIGIBLE_RISK_PAIRS)
    if invalid_pair.any():
        identities = (
            frame.loc[invalid_pair, [RISK_TYPE, RISK_GREEK]]
            .drop_duplicates()
            .head(5)
            .to_dict("records")
        )
        raise ValueError(
            "Reduced-tenor catalogue may contain only one-axis Tenor Swap "
            f"products: {identities}"
        )

    return frame.reset_index(drop=True)


def _clean_matrix_labels(labels: pd.Index, *, axis: str) -> pd.Index:
    cleaned: list[str] = []
    for position, value in enumerate(labels):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Reduction matrix {axis} labels must be nonblank text; "
                f"invalid position {position}"
            )
        cleaned.append(value.strip())
    result = pd.Index(cleaned)
    duplicates = result[result.duplicated()].unique().tolist()
    if duplicates:
        raise ValueError(f"Reduction matrix {axis} labels must be unique: {duplicates}")
    return result


def validate_reduction_matrix(
    raw: pd.DataFrame,
    *,
    matrix_name: str = "matrix",
) -> pd.DataFrame:
    """Validate rows=new tenors and columns=full tenors, preserving row order."""

    if not isinstance(raw, pd.DataFrame):
        raise TypeError(f"Reduction matrix {matrix_name!r} must be a DataFrame")
    if raw.empty or len(raw.columns) == 0:
        raise ValueError(f"Reduction matrix {matrix_name!r} must not be empty")

    frame = raw.copy()
    frame.index = _clean_matrix_labels(frame.index, axis="row")
    frame.columns = _clean_matrix_labels(frame.columns, axis="column")
    for column in frame.columns:
        values = frame[column]
        boolean = values.map(lambda value: isinstance(value, (bool, np.bool_)))
        numeric = pd.to_numeric(values, errors="coerce")
        invalid = boolean | numeric.isna() | ~np.isfinite(numeric)
        if invalid.any():
            rows = frame.index[invalid].tolist()[:5]
            raise ValueError(
                f"Reduction matrix {matrix_name!r} column {column!r} must "
                f"contain finite numbers; invalid rows {rows}"
            )
        frame[column] = numeric.astype(float)
    return frame


def _temporary_column(columns: pd.Index, stem: str) -> str:
    candidate = stem
    suffix = 1
    while candidate in columns:
        candidate = f"{stem}_{suffix}"
        suffix += 1
    return candidate


def _validated_additive_values(
    frame: pd.DataFrame,
    columns: list[str],
) -> np.ndarray:
    converted: list[np.ndarray] = []
    for column in columns:
        values = frame[column]
        boolean = values.map(lambda value: isinstance(value, (bool, np.bool_)))
        numeric = pd.to_numeric(values, errors="coerce")
        blank = values.isna() | values.astype("string").str.strip().eq("")
        invalid = boolean | (~blank & numeric.isna())
        invalid |= numeric.notna() & ~np.isfinite(numeric)
        if invalid.any():
            rows = frame.index[invalid].tolist()[:5]
            raise ValueError(
                f"Reduced-tenor additive column {column!r} contains a "
                f"non-numeric or non-finite value at rows {rows}"
            )
        converted.append(numeric.to_numpy(dtype=float, na_value=np.nan))
    return np.column_stack(converted)


def _position_codes(
    frame: pd.DataFrame, columns: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    identity = pd.MultiIndex.from_frame(frame[columns])
    codes, _ = pd.factorize(identity, sort=False)
    if (codes < 0).any():  # pragma: no cover - MultiIndex tuple keys retain nulls
        raise ValueError("Reduced-tenor position identity could not be resolved")
    _, first_rows = np.unique(codes, return_index=True)
    return codes.astype(np.intp, copy=False), first_rows.astype(np.intp, copy=False)


def _normalized_tenor_labels(values: pd.Series) -> pd.Index:
    labels: list[str] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            return pd.Index([])
        labels.append(value.strip())
    return pd.Index(labels)


class ReducedTenorReducer:
    """Apply cached, provider-owned matrices to mapped post-P&L vectors.

    One provider call is made per distinct ``MatrixName`` for the lifetime of
    this reducer.  The cache is bounded by the matrix names in the catalogue.
    No provider is called while the full-tenor view is merely constructed.
    """

    def __init__(
        self,
        catalog: CatalogSource,
        matrix_provider: MatrixProviderLike,
    ) -> None:
        if not callable(matrix_provider):
            raise TypeError("matrix_provider must be callable")
        self._catalog = load_reduced_tenor_catalog(catalog)
        self._matrix_provider = matrix_provider
        self._matrix_cache: dict[str, pd.DataFrame] = {}
        self._unavailable_matrices: set[str] = set()
        self._matrix_names = frozenset(self._catalog[MATRIX_NAME])
        self._cache_lock = RLock()

    @property
    def catalog(self) -> pd.DataFrame:
        """Return a caller-owned copy of the validated catalogue."""

        return self._catalog.copy()

    def _matrix(self, matrix_name: str) -> pd.DataFrame | None:
        if matrix_name not in self._matrix_names:  # pragma: no cover - internal guard
            raise KeyError(f"Unknown reduction matrix {matrix_name!r}")
        with self._cache_lock:
            if matrix_name in self._unavailable_matrices:
                return None
            cached = self._matrix_cache.get(matrix_name)
            if cached is None:
                try:
                    raw = self._matrix_provider(matrix_name)
                    cached = validate_reduction_matrix(raw, matrix_name=matrix_name)
                except Exception as exc:
                    # Reduced tenor is an optional presentation. A missing or
                    # malformed provider response must leave the authoritative
                    # full-tenor rows intact instead of failing Risk Explorer.
                    self._unavailable_matrices.add(matrix_name)
                    _LOGGER.warning(
                        "Reduced-tenor matrix %r is unavailable; keeping full tenors: %s",
                        matrix_name,
                        exc,
                    )
                    return None
                self._matrix_cache[matrix_name] = cached
            return cached

    def _batches(
        self, frame: pd.DataFrame
    ) -> list[tuple[str, str, object, np.ndarray]]:
        """Return matrix/source/underlying batches in first-seen source order."""

        eligible_positions = np.flatnonzero(
            frame[SOURCE_TYPE].isin(_ELIGIBLE_SOURCE_TYPES).to_numpy(dtype=bool)
        )
        if len(eligible_positions) == 0:
            return []

        selected = frame.iloc[eligible_positions][
            [SOURCE_TYPE, *REDUCED_TENOR_CATALOG_KEY]
        ].copy()
        identities = pd.MultiIndex.from_frame(
            selected.loc[:, list(REDUCED_TENOR_CATALOG_KEY)]
        )
        catalog_identities = pd.MultiIndex.from_frame(
            self._catalog.loc[:, list(REDUCED_TENOR_CATALOG_KEY)]
        )
        matrix_by_identity = pd.Series(
            self._catalog[MATRIX_NAME].to_numpy(),
            index=catalog_identities,
        )
        selected[MATRIX_NAME] = matrix_by_identity.reindex(identities).to_numpy()
        selected["__position__"] = eligible_positions
        selected = selected.loc[selected[MATRIX_NAME].notna()]
        if selected.empty:
            return []

        return [
            (
                str(matrix_name),
                str(source_type),
                underlying,
                group["__position__"].to_numpy(dtype=np.intp, copy=True),
            )
            for (
                matrix_name,
                source_type,
                _risk_type,
                _risk_greek,
                underlying,
            ), group in selected.groupby(
                [MATRIX_NAME, SOURCE_TYPE, *REDUCED_TENOR_CATALOG_KEY],
                sort=False,
                dropna=False,
                observed=True,
            )
        ]

    @staticmethod
    def _quote_values(
        market_frame: pd.DataFrame,
        *,
        source_type: str,
        underlying: object,
        reduced_tenors: pd.Index,
        column: str,
    ) -> np.ndarray:
        if market_frame.empty or column not in market_frame:
            if column == MARKET_AVAILABLE:
                return np.full(len(reduced_tenors), False, dtype=object)
            if column == MARKET_DATA_STATUS:
                return np.full(len(reduced_tenors), "", dtype=object)
            return np.full(len(reduced_tenors), np.nan, dtype=object)

        matches = market_frame.loc[
            market_frame[SOURCE_TYPE].eq(source_type)
            & market_frame[UNDERLYING].eq(underlying)
        ]
        if matches.empty:
            if column == MARKET_AVAILABLE:
                return np.full(len(reduced_tenors), False, dtype=object)
            if column == MARKET_DATA_STATUS:
                return np.full(len(reduced_tenors), "", dtype=object)
            return np.full(len(reduced_tenors), np.nan, dtype=object)

        labels = matches[TENOR_SWAP].map(
            lambda value: value.strip() if isinstance(value, str) else value
        )
        lookup = pd.Series(matches[column].to_numpy(), index=labels).loc[
            lambda values: ~values.index.duplicated(keep="first")
        ]
        selected = lookup.reindex(reduced_tenors)
        matched = reduced_tenors.isin(lookup.index)
        if column == MARKET_AVAILABLE:
            return selected.where(matched, False).to_numpy(dtype=object)
        if column == MARKET_DATA_STATUS:
            return selected.where(matched, "").fillna("").to_numpy(dtype=object)
        return selected.where(matched, np.nan).to_numpy(dtype=object)

    def _reduce_batch(
        self,
        frame: pd.DataFrame,
        positions: np.ndarray,
        matrix: pd.DataFrame,
        market_frame: pd.DataFrame,
        *,
        source_type: str,
        underlying: object,
    ) -> tuple[pd.DataFrame, np.ndarray] | None:
        batch = frame.iloc[positions].copy()
        old_labels = _normalized_tenor_labels(batch[TENOR_SWAP])
        if len(old_labels) != len(batch):
            return None
        old_codes = matrix.columns.get_indexer(old_labels)
        # A matrix must cover the full source vector.  Silently dropping a real
        # full-tenor exposure would be worse than leaving this mapped identity
        # in its authoritative full-tenor form.
        if (old_codes < 0).any():
            return None

        additive_columns = [
            column for column in ADDITIVE_REDUCTION_COLUMNS if column in batch
        ]
        excluded = {
            TENOR_SWAP,
            TENOR_SWAP_ORDER,
            *additive_columns,
            *MARKET_QUOTE_COLUMNS,
            *[column for column in _CARRIED_COLUMNS if column in batch],
        }
        position_columns = [
            column for column in batch.columns if column not in excluded
        ]
        codes, first_rows = _position_codes(batch, position_columns)
        position_count = len(first_rows)
        old_tenor_count = len(matrix.columns)
        measure_count = len(additive_columns)

        weights = matrix.to_numpy(dtype=float, copy=False)
        new_tenors = matrix.index
        new_tenor_count = len(new_tenors)
        # Bound the transient tensor size. The estimate covers input values,
        # accumulated values/observations, output/support, and a safety factor
        # for einsum temporaries. Large books are therefore processed in
        # position chunks instead of allocating one whole-book 3-D array.
        bytes_per_position = max(
            1,
            measure_count * (old_tenor_count * 17 + new_tenor_count * 9) * 2,
        )
        chunk_positions = max(1, _REDUCTION_WORKING_SET_BYTES // bytes_per_position)
        # Quote lookup is independent of portfolio/position, so resolve it
        # once per matrix batch and tile only inside each bounded chunk.
        quote_values_by_column = {
            column: self._quote_values(
                market_frame,
                source_type=source_type,
                underlying=underlying,
                reduced_tenors=new_tenors,
                column=column,
            )
            for column in MARKET_QUOTE_COLUMNS
            if column in batch
        }

        reduced_parts: list[pd.DataFrame] = []
        origin_parts: list[np.ndarray] = []
        nonzero_weights = (weights != 0.0).astype(np.uint8)
        for position_start in range(0, position_count, chunk_positions):
            position_end = min(position_count, position_start + chunk_positions)
            row_mask = (codes >= position_start) & (codes < position_end)
            row_positions = np.flatnonzero(row_mask)
            chunk = batch.iloc[row_positions]
            chunk_codes = codes[row_positions] - position_start
            chunk_old_codes = old_codes[row_positions]
            values = _validated_additive_values(chunk, additive_columns)
            chunk_count = position_end - position_start
            summed = np.zeros(
                (chunk_count, old_tenor_count, measure_count), dtype=float
            )
            valid = ~np.isnan(values)
            np.add.at(
                summed,
                (chunk_codes, chunk_old_codes),
                np.where(valid, values, 0.0),
            )
            observed = np.zeros_like(summed, dtype=bool)
            np.logical_or.at(observed, (chunk_codes, chunk_old_codes), valid)
            reduced_values = np.einsum("no,pom->pnm", weights, summed, optimize=True)
            support = np.einsum(
                "no,pom->pnm",
                nonzero_weights,
                observed.astype(np.uint8),
                optimize=True,
            )
            reduced_values[support == 0] = np.nan

            template_rows = first_rows[position_start:position_end]
            templates = batch.iloc[template_rows].reset_index(drop=True)
            reduced = templates.loc[
                templates.index.repeat(new_tenor_count)
            ].reset_index(drop=True)
            reduced[TENOR_SWAP] = np.tile(new_tenors.to_numpy(), chunk_count)
            reduced[TENOR_SWAP_ORDER] = np.tile(
                np.arange(new_tenor_count, dtype=np.int64), chunk_count
            )
            for measure_index, column in enumerate(additive_columns):
                reduced[column] = reduced_values[:, :, measure_index].reshape(-1)
            for column, quote_values in quote_values_by_column.items():
                reduced[column] = np.tile(quote_values, chunk_count)
            reduced_parts.append(reduced)
            origin_parts.append(np.repeat(positions[template_rows], new_tenor_count))

        return (
            pd.concat(reduced_parts, ignore_index=True, sort=False),
            np.concatenate(origin_parts),
        )

    def reduce(
        self,
        frame: pd.DataFrame,
        *,
        market_frame: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Return a reduced copy while preserving all ineligible/unmapped rows.

        Reduction is batched by catalogue mapping and source type.  Each batch
        performs one matrix multiplication across every independent position
        and every present additive measure.  A mapped batch whose real full
        tenors are not all represented by the matrix is retained unchanged.
        """

        if not isinstance(frame, pd.DataFrame):
            raise TypeError("frame must be a pandas DataFrame")
        duplicates = _duplicates(frame.columns)
        if duplicates:
            raise ValueError(f"frame has duplicate columns: {duplicates}")
        missing = [column for column in _REQUIRED_FRAME_COLUMNS if column not in frame]
        if missing:
            raise ValueError(
                f"frame is missing required reduced-tenor columns: {missing}"
            )
        if frame.empty or self._catalog.empty:
            return frame.copy()

        quotes = frame if market_frame is None else market_frame
        if not isinstance(quotes, pd.DataFrame):
            raise TypeError("market_frame must be a pandas DataFrame")
        if not quotes.empty:
            quote_missing = [
                column
                for column in (SOURCE_TYPE, UNDERLYING, TENOR_SWAP)
                if column not in quotes
            ]
            if quote_missing:
                raise ValueError(
                    f"market_frame is missing quote identity columns: {quote_missing}"
                )

        working = frame.reset_index(drop=True)
        removed = np.zeros(len(working), dtype=bool)
        reduced_parts: list[pd.DataFrame] = []
        origin_parts: list[np.ndarray] = []
        for matrix_name, source_type, underlying, positions in self._batches(working):
            matrix = self._matrix(matrix_name)
            if matrix is None:
                continue
            reduced = self._reduce_batch(
                working,
                positions,
                matrix,
                quotes,
                source_type=source_type,
                underlying=underlying,
            )
            if reduced is None:
                continue
            part, origins = reduced
            removed[positions] = True
            reduced_parts.append(part)
            origin_parts.append(origins)

        if not reduced_parts:
            return frame.copy()

        origin_column = _temporary_column(working.columns, "__tenor_reduction_origin__")
        secondary_column = _temporary_column(
            working.columns.append(pd.Index([origin_column])),
            "__tenor_reduction_order__",
        )
        passthrough = working.loc[~removed].copy()
        passthrough[origin_column] = np.flatnonzero(~removed)
        passthrough[secondary_column] = 0
        ordered_parts = [passthrough]
        for part, origins in zip(reduced_parts, origin_parts, strict=True):
            part[origin_column] = origins
            part[secondary_column] = part[TENOR_SWAP_ORDER].to_numpy()
            ordered_parts.append(part)

        result = pd.concat(ordered_parts, ignore_index=True, sort=False)
        result = result.sort_values(
            [origin_column, secondary_column], kind="stable"
        ).drop(columns=[origin_column, secondary_column])
        return result.loc[:, frame.columns].reset_index(drop=True)


def reduce_tenor_swap(
    frame: pd.DataFrame,
    *,
    catalog: CatalogSource,
    matrix_provider: MatrixProviderLike,
    market_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Convenience wrapper for a one-off reduced-tenor calculation."""

    return ReducedTenorReducer(catalog, matrix_provider).reduce(
        frame,
        market_frame=market_frame,
    )


__all__ = [
    "ADDITIVE_REDUCTION_COLUMNS",
    "CatalogSource",
    "MATRIX_NAME",
    "MARKET_QUOTE_COLUMNS",
    "MatrixProvider",
    "MatrixProviderLike",
    "REDUCED_TENOR_CATALOG_COLUMNS",
    "REDUCED_TENOR_CATALOG_KEY",
    "ReducedTenorReducer",
    "load_reduced_tenor_catalog",
    "reduce_tenor_swap",
    "validate_reduction_matrix",
]
