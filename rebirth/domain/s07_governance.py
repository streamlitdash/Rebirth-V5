"""Portfolio governance, reporting identity, promotion, and release views."""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Final, Mapping

import numpy as np
import pandas as pd

from rebirth.domain.s01_schema import (
    PORTFOLIO_CONFIG_COLUMNS,
    PORTFOLIO_CONFIG_REQUIRED_COLUMNS,
    PORTFOLIO_FIELDS,
    PORTFOLIO_METADATA_COLUMNS,
    PORTFOLIO_OPTIONAL_METADATA_COLUMNS,
    PORTFOLIO_POSITION_COLUMNS,
    PORTFOLIO_REPORTING_COLUMNS,
    TENOR_COLUMNS,
    TENOR_ORDER_COLUMNS,
    UNMAPPED_VALUE,
)
from rebirth.domain.s06_reporting import (
    REPORTED_UNDERLYING,
    attach_reported_underlying,
    load_reported_underlying_mapping,
)
from rebirth.domain.s03_calculations import (
    _coerce_numeric,
    _require_columns,
    _require_nonblank,
    build_all_pl,
)
from rebirth.domain.s02_products import (
    ACTIVITY,
    CANONICAL_PRODUCTS,
    CREDIT_MEASURE_COLUMNS,
    CURRENT,
    DISPLAY_BUCKET,
    DRISK,
    DRISK_THRESHOLD,
    GROUP,
    MARKET_AVAILABLE,
    MARKET_DATA_STATUS,
    MARKET_MOVE,
    OPEN,
    PL,
    PL_THRESHOLD,
    PORTFOLIO,
    PORTFOLIO_MAPPED,
    PRODUCT,
    PRODUCT_LABELS,
    PROMOTION_REASON,
    PROMOTION_SCORE,
    REGION,
    RELEASE_RISK_PAIRS,
    RISK,
    RISK_GREEK,
    RISK_THRESHOLD,
    RISK_TYPE,
    SOURCE_TYPE,
    SPLIT,
    UNDERLYING,
    DataFrameSource,
    GovernanceSource,
    PortfolioConfigSource,
    ProductSources,
    ProductionIntegrationError,
)


BASELINE_PROMOTION_ACTIVITIES: Final = (
    "Activity 1",
    "Activity 2",
    "Activity 3",
)
# Explicit aliases retained by the V4 demo fixtures.
_BASELINE_PROMOTION_LEGACY_ALIASES: Final = ("Macro", "Credit", "Hedge")
_FAKE_ACTIVITY_PREFIX: Final = "fake_replace_me - "


def _activity_key(value: object) -> str:
    """Return the exact comparison key used by the baseline activity policy."""

    key = " ".join(unicodedata.normalize("NFKC", str(value)).split()).casefold()
    if key.startswith(_FAKE_ACTIVITY_PREFIX):
        key = key[len(_FAKE_ACTIVITY_PREFIX) :]
    return key


_BASELINE_PROMOTION_ACTIVITY_KEYS: Final = frozenset(
    _activity_key(value)
    for value in (
        *BASELINE_PROMOTION_ACTIVITIES,
        *_BASELINE_PROMOTION_LEGACY_ALIASES,
    )
)


def _load_governance_source(
    source: GovernanceSource,
    *,
    label: str,
) -> pd.DataFrame | str | Path:
    """Resolve a zero-argument loader only when a refresh actually needs it."""
    resolved = source() if callable(source) else source
    if not isinstance(resolved, (pd.DataFrame, str, Path)):
        raise TypeError(f"{label} loader must return a DataFrame or CSV path")
    return resolved


def load_config(source: DataFrameSource) -> pd.DataFrame:
    frame = (
        pd.read_csv(source, dtype={PORTFOLIO: "string"}, keep_default_na=False)
        if isinstance(source, (str, Path))
        else source
    )
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("config must be a DataFrame or CSV path")
    # Connector boundaries use one canonical vocabulary. Source-specific
    # renaming belongs inside the connector, never in the shared pipeline.
    result = frame.copy()
    required_columns = list(PORTFOLIO_CONFIG_REQUIRED_COLUMNS)
    _require_columns(result, required_columns, "config")
    for column in PORTFOLIO_OPTIONAL_METADATA_COLUMNS:
        if column not in result:
            result[column] = next(
                field.default_value
                for field in PORTFOLIO_FIELDS
                if field.external_name == column
            )
    columns = list(PORTFOLIO_CONFIG_COLUMNS)
    result = _require_nonblank(result, columns, "config")
    product_labels = result[PRODUCT].str.casefold()
    invalid_product = ~product_labels.isin(PRODUCT_LABELS)
    if invalid_product.any():
        rows = result.index[invalid_product].tolist()[:5]
        raise ValueError(
            f"config Product must contain only 'XVA' or 'Hedges'; invalid rows {rows}"
        )
    result[PRODUCT] = product_labels.map(PRODUCT_LABELS)
    reserved_columns = [
        column for column in PORTFOLIO_METADATA_COLUMNS if column != PRODUCT
    ]
    reserved = result[reserved_columns].apply(
        lambda column: column.str.casefold().eq(UNMAPPED_VALUE.casefold())
    )
    if reserved.any().any():
        raise ValueError("config metadata must not use the reserved value 'Unmapped'")
    if result.duplicated(PORTFOLIO).any():
        duplicates = (
            result.loc[result.duplicated(PORTFOLIO, keep=False), PORTFOLIO]
            .unique()
            .tolist()
        )
        raise ValueError(f"config contains duplicate portfolios: {duplicates}")
    return result[columns].copy()


def _load_portfolio_config(
    source: PortfolioConfigSource,
    portfolio_date: pd.Timestamp,
) -> pd.DataFrame:
    """Call the dated Portfolio connector, then validate its canonical frame."""
    resolved = source(portfolio_date) if callable(source) else source
    if not isinstance(resolved, (pd.DataFrame, str, Path)):
        raise TypeError("portfolio config loader must return a DataFrame or CSV path")
    return load_config(resolved)


def load_thresholds(source: GovernanceSource) -> pd.DataFrame:
    source = _load_governance_source(source, label="thresholds")
    frame = pd.read_csv(source) if isinstance(source, (str, Path)) else source
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("thresholds must be a DataFrame or CSV path")
    result = frame.copy()
    columns = [RISK_TYPE, RISK_GREEK, RISK_THRESHOLD, DRISK_THRESHOLD, PL_THRESHOLD]
    metric_columns = [RISK_TYPE, RISK_GREEK, PL, RISK, DRISK]
    if list(result.columns) != metric_columns:
        raise ValueError(
            f"risk thresholds columns must be exactly {metric_columns} in that "
            f"order; found {list(result.columns)}"
        )
    # The external file mirrors metric names. Explicit internal suffixes keep
    # those governance values distinct when they are joined to position data.
    result = result.rename(
        columns={RISK: RISK_THRESHOLD, DRISK: DRISK_THRESHOLD, PL: PL_THRESHOLD}
    )
    result = _require_nonblank(result, [RISK_TYPE, RISK_GREEK], "risk thresholds")
    if result.duplicated([RISK_TYPE, RISK_GREEK]).any():
        raise ValueError(
            "risk thresholds must contain unique Risk Type + Risk Greek rows"
        )
    result = _coerce_numeric(
        result, [RISK_THRESHOLD, DRISK_THRESHOLD, PL_THRESHOLD], "risk thresholds"
    )
    if (result[[RISK_THRESHOLD, DRISK_THRESHOLD, PL_THRESHOLD]] <= 0).any().any():
        raise ValueError("risk thresholds must be greater than zero")
    return result[columns].copy()


def load_reported_underlyings(
    source: GovernanceSource | None,
) -> pd.DataFrame:
    """Resolve and validate the optional cross-product reporting map lazily."""

    if source is None:
        return load_reported_underlying_mapping(
            None,
            allowed_pairs=RELEASE_RISK_PAIRS,
        )
    resolved = _load_governance_source(source, label="Reported Underlying mapping")
    return load_reported_underlying_mapping(
        resolved,
        allowed_pairs=RELEASE_RISK_PAIRS,
    )


def _apply_validated_thresholds(
    frame: pd.DataFrame,
    threshold_frame: pd.DataFrame,
    *,
    promotion_activity_keys: frozenset[str] | None = None,
) -> pd.DataFrame:
    """Apply thresholds at the governed reporting-underlying grain."""
    result = frame.copy()
    _require_columns(result, [GROUP], "configured P&L")
    if REPORTED_UNDERLYING not in result:
        result[REPORTED_UNDERLYING] = result[UNDERLYING]
    required_pairs = result[[RISK_TYPE, RISK_GREEK]].drop_duplicates()
    missing = required_pairs.merge(
        threshold_frame[[RISK_TYPE, RISK_GREEK]],
        on=[RISK_TYPE, RISK_GREEK],
        how="left",
        indicator=True,
    )
    if missing["_merge"].ne("both").any():
        records = missing.loc[
            missing["_merge"].ne("both"), [RISK_TYPE, RISK_GREEK]
        ].to_dict("records")
        raise ValueError(
            f"risk thresholds are missing Risk Type + Risk Greek rows: {records}"
        )

    keys = [RISK_TYPE, RISK_GREEK, REPORTED_UNDERLYING]
    _require_columns(result, [PORTFOLIO_MAPPED], "configured P&L")
    calculation_rows = result
    if promotion_activity_keys is not None:
        _require_columns(result, [ACTIVITY], "configured P&L")
        activity_keys = result[ACTIVITY].map(_activity_key)
        calculation_rows = result.loc[activity_keys.isin(promotion_activity_keys)]
    mapped = calculation_rows.loc[calculation_rows[PORTFOLIO_MAPPED].eq(True)]
    aggregate = mapped.groupby(keys, as_index=False)[[RISK, DRISK, PL]].sum(min_count=1)
    aggregate = aggregate.merge(
        threshold_frame, on=[RISK_TYPE, RISK_GREEK], how="left", validate="many_to_one"
    )
    risk_ratio = aggregate[RISK].abs() / aggregate[RISK_THRESHOLD]
    drisk_ratio = aggregate[DRISK].abs() / aggregate[DRISK_THRESHOLD]
    pl_ratio = aggregate[PL].abs() / aggregate[PL_THRESHOLD]
    aggregate[PROMOTION_SCORE] = pd.concat(
        [risk_ratio, drisk_ratio, pl_ratio], axis=1
    ).max(axis=1)
    aggregate[PROMOTION_REASON] = [
        ", ".join(
            reason
            for reason, breached in (
                ("Big Risk", risk_value >= 1.0),
                ("Big dRisk", drisk_value >= 1.0),
                ("Big PL", pl_value >= 1.0),
            )
            if breached
        )
        for risk_value, drisk_value, pl_value in zip(risk_ratio, drisk_ratio, pl_ratio)
    ]
    aggregate[DISPLAY_BUCKET] = np.where(
        aggregate[PROMOTION_REASON].ne(""),
        aggregate[REPORTED_UNDERLYING],
        "Other",
    )
    classification = aggregate[
        keys + [DISPLAY_BUCKET, PROMOTION_REASON, PROMOTION_SCORE]
    ]
    result = result.merge(
        classification,
        on=keys,
        how="left",
        sort=False,
        validate="many_to_one",
    )
    # Thresholds remain available on every position so an explicit session
    # recalculation can use any current filtered view. An identity with no row
    # in the configured calculation universe is deliberately neutral below.
    result = result.merge(
        threshold_frame,
        on=[RISK_TYPE, RISK_GREEK],
        how="left",
        sort=False,
        validate="many_to_one",
    )
    result[DISPLAY_BUCKET] = result[DISPLAY_BUCKET].fillna("Other")
    result[PROMOTION_REASON] = result[PROMOTION_REASON].fillna("")
    result[PROMOTION_SCORE] = result[PROMOTION_SCORE].fillna(0.0)
    return result


def apply_baseline_promotions(
    frame: pd.DataFrame,
    threshold_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate the committed promotion baseline from Activities 1-3 only.

    The activity scope controls calculation, not row retention. Classification
    is joined back at the governed identity grain, so an out-of-scope row can
    inherit a baseline identity's result without contributing to it. An
    identity found only outside Activities 1-3 is retained with its thresholds
    and an explicit neutral result (``Other``, blank reason, zero score).
    """

    return _apply_validated_thresholds(
        frame,
        threshold_frame,
        promotion_activity_keys=_BASELINE_PROMOTION_ACTIVITY_KEYS,
    )


def evaluate_promotions(
    frame: pd.DataFrame,
    threshold_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Re-evaluate promotion on a position subset using validated thresholds.

    This is the supplied pure boundary used when the UI wants promotion to
    follow an already-filtered position set.  External threshold files still go
    through :func:`apply_thresholds`; this function deliberately requires the
    internal ``... Threshold`` columns so the two contracts cannot be confused.
    """

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("promotion input must be a pandas DataFrame")
    if not isinstance(threshold_frame, pd.DataFrame):
        raise TypeError("validated thresholds must be a pandas DataFrame")
    required_threshold_columns = [
        RISK_TYPE,
        RISK_GREEK,
        RISK_THRESHOLD,
        DRISK_THRESHOLD,
        PL_THRESHOLD,
    ]
    _require_columns(
        threshold_frame,
        required_threshold_columns,
        "validated thresholds",
    )
    return _apply_validated_thresholds(frame, threshold_frame)


def apply_thresholds(
    frame: pd.DataFrame,
    thresholds: pd.DataFrame | str | Path,
) -> pd.DataFrame:
    """Validate external thresholds once, then apply exposure promotion rules."""

    return _apply_validated_thresholds(frame, load_thresholds(thresholds))


def _merge_validated_config(
    pl_frame: pd.DataFrame,
    validated_config: pd.DataFrame,
) -> pd.DataFrame:
    """Join one already-validated internal Portfolio mapping."""

    result = pl_frame.copy()
    result = _require_nonblank(result, [PORTFOLIO], "P&L")
    overlap = sorted(
        set(result.columns) & set((*PORTFOLIO_METADATA_COLUMNS, PORTFOLIO_MAPPED))
    )
    if overlap:
        raise ValueError(
            f"P&L already contains portfolio-config-owned columns: {overlap}"
        )
    result = result.merge(
        validated_config,
        on=PORTFOLIO,
        how="left",
        validate="many_to_one",
        indicator="_config_merge",
    )
    unmapped = result["_config_merge"].ne("both")
    result[PORTFOLIO_MAPPED] = ~unmapped
    result.loc[unmapped, list(PORTFOLIO_METADATA_COLUMNS)] = UNMAPPED_VALUE
    return result.drop(columns="_config_merge")


def merge_config(
    pl_frame: pd.DataFrame, config: pd.DataFrame | str | Path
) -> pd.DataFrame:
    """Validate an external Portfolio mapping once, then join it to P&L."""

    return _merge_validated_config(pl_frame, load_config(config))


def to_dashboard_frame(frame: pd.DataFrame) -> pd.DataFrame:
    _require_columns(
        frame,
        [
            SOURCE_TYPE,
            RISK_TYPE,
            RISK_GREEK,
            SPLIT,
            *PORTFOLIO_METADATA_COLUMNS,
            PORTFOLIO_MAPPED,
            DISPLAY_BUCKET,
            GROUP,
            UNDERLYING,
            REPORTED_UNDERLYING,
            *TENOR_COLUMNS,
            *TENOR_ORDER_COLUMNS,
            PORTFOLIO,
            RISK,
            DRISK,
            OPEN,
            CURRENT,
            PL,
            MARKET_MOVE,
            MARKET_AVAILABLE,
            MARKET_DATA_STATUS,
            PROMOTION_REASON,
            PROMOTION_SCORE,
            RISK_THRESHOLD,
            DRISK_THRESHOLD,
            PL_THRESHOLD,
        ],
        "combined P&L",
    )
    columns = [
        SOURCE_TYPE,
        RISK_TYPE,
        RISK_GREEK,
        SPLIT,
        *PORTFOLIO_POSITION_COLUMNS,
        DISPLAY_BUCKET,
        GROUP,
        *([REGION] if REGION in frame else []),
        REPORTED_UNDERLYING,
        UNDERLYING,
        *TENOR_COLUMNS,
        *TENOR_ORDER_COLUMNS,
        PORTFOLIO,
        *PORTFOLIO_REPORTING_COLUMNS,
        PORTFOLIO_MAPPED,
        PROMOTION_REASON,
        PROMOTION_SCORE,
        RISK_THRESHOLD,
        DRISK_THRESHOLD,
        PL_THRESHOLD,
        RISK,
        DRISK,
        OPEN,
        CURRENT,
        PL,
        MARKET_MOVE,
        MARKET_AVAILABLE,
        MARKET_DATA_STATUS,
        *[column for column in CREDIT_MEASURE_COLUMNS if column in frame],
    ]
    return frame[columns].copy()


def _validate_dashboard_release(frame: pd.DataFrame) -> None:
    """Reject pipeline-owned invariant failures before an atomic cache commit.

    This is deliberately narrower than ``rebirth.ui.s02_aggregation.prepare_risk_data``: the UI
    remains responsible for display normalization and derived breakdown columns.
    The pipeline owns the authoritative numeric values, canonical Product
    partition, market identity, and nonblank aggregation keys checked here.
    Keeping this guard in this module avoids a pipeline-to-UI import cycle.
    """
    if not isinstance(frame, pd.DataFrame):  # pragma: no cover - internal contract
        raise TypeError("dashboard release must be a pandas DataFrame")
    if frame.empty:
        raise ValueError("dashboard release must contain at least one mapped row")

    grouping_columns = [
        SOURCE_TYPE,
        RISK_TYPE,
        RISK_GREEK,
        SPLIT,
        *PORTFOLIO_POSITION_COLUMNS,
        DISPLAY_BUCKET,
        GROUP,
        REPORTED_UNDERLYING,
        UNDERLYING,
        *TENOR_COLUMNS,
        *PORTFOLIO_REPORTING_COLUMNS,
    ]
    threshold_columns = [RISK_THRESHOLD, DRISK_THRESHOLD, PL_THRESHOLD]
    numeric_columns = [
        RISK,
        DRISK,
        OPEN,
        CURRENT,
        PL,
        MARKET_MOVE,
        PROMOTION_SCORE,
        *threshold_columns,
    ]
    required_columns = [
        *grouping_columns,
        *TENOR_ORDER_COLUMNS,
        *numeric_columns,
        PORTFOLIO_MAPPED,
        MARKET_AVAILABLE,
        MARKET_DATA_STATUS,
    ]
    missing = [column for column in required_columns if column not in frame]
    if missing:
        raise ValueError(f"dashboard release is missing required columns: {missing}")
    duplicates = frame.columns[frame.columns.duplicated()].unique().tolist()
    if duplicates:
        raise ValueError(f"dashboard release contains duplicate columns: {duplicates}")

    for order_column in TENOR_ORDER_COLUMNS:
        values = frame[order_column]
        boolean = values.map(lambda value: isinstance(value, (bool, np.bool_)))
        numeric = pd.to_numeric(values, errors="coerce")
        nonblank = values.notna() & values.astype("string").str.strip().ne("")
        invalid = boolean | (nonblank & numeric.isna())
        invalid |= numeric.notna() & (
            ~np.isfinite(numeric) | numeric.lt(0) | numeric.mod(1).ne(0)
        )
        if invalid.any():
            rows = frame.index[invalid].tolist()[:5]
            raise ValueError(
                f"dashboard release {order_column!r} must be nullable or a "
                f"non-negative integer at rows {rows}"
            )

    # Group is opaque connector-owned metadata. Its column is structurally
    # required above, but the framework deliberately applies no value,
    # taxonomy, type, blank, or allow-list validation to it.
    validated_text_keys = [column for column in grouping_columns if column != GROUP]
    for column in validated_text_keys:
        values = frame[column]
        invalid = values.isna() | ~values.map(lambda value: isinstance(value, str))
        invalid |= values.astype("string").str.strip().eq("")
        if invalid.any():
            rows = frame.index[invalid].tolist()[:5]
            raise ValueError(
                f"dashboard release column {column!r} has blank or non-text keys "
                f"at rows {rows}"
            )

    mapped_values = frame[PORTFOLIO_MAPPED]
    invalid_mapped = ~mapped_values.map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if invalid_mapped.any():
        rows = frame.index[invalid_mapped].tolist()[:5]
        raise ValueError(
            f"dashboard release {PORTFOLIO_MAPPED!r} must be boolean at rows {rows}"
        )
    if not mapped_values.astype(bool).all():
        rows = frame.index[~mapped_values.astype(bool)].tolist()[:5]
        raise ValueError(
            f"dashboard release contains unmapped portfolio rows at {rows}"
        )

    invalid_product = ~frame[PRODUCT].isin(CANONICAL_PRODUCTS)
    if invalid_product.any():
        rows = frame.index[invalid_product].tolist()[:5]
        raise ValueError(
            "dashboard release Product must be exactly 'XVA' or 'Hedges'; "
            f"invalid rows {rows}"
        )
    # Product is the disjoint partition from which the UI derives each
    # Risk/dRisk/P&L XVA + Hedges breakdown. Canonical labels here are therefore
    # the aggregate identity that can be proven before UI-side derivation.

    optional_credit_columns = [
        column for column in CREDIT_MEASURE_COLUMNS if column in frame
    ]
    converted: dict[str, pd.Series] = {}
    for column in [*numeric_columns, *optional_credit_columns]:
        values = frame[column]
        boolean = values.map(lambda value: isinstance(value, (bool, np.bool_)))
        numeric = pd.to_numeric(values, errors="coerce")
        blank = values.isna() | values.astype("string").str.strip().eq("")
        invalid = boolean | (~blank & numeric.isna())
        invalid |= numeric.notna() & ~np.isfinite(numeric)
        if column == RISK or column in threshold_columns:
            invalid |= numeric.isna()
        if invalid.any():
            rows = frame.index[invalid].tolist()[:5]
            raise ValueError(
                f"dashboard release column {column!r} contains missing, non-numeric, "
                f"boolean, or non-finite values at rows {rows}"
            )
        converted[column] = numeric

    for column in threshold_columns:
        invalid_threshold = converted[column].le(0)
        if invalid_threshold.any():
            rows = frame.index[invalid_threshold].tolist()[:5]
            raise ValueError(
                f"dashboard release column {column!r} must be greater than zero "
                f"at rows {rows}"
            )

    availability = frame[MARKET_AVAILABLE]
    invalid_availability = ~availability.map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    if invalid_availability.any():
        rows = frame.index[invalid_availability].tolist()[:5]
        raise ValueError(
            f"dashboard release {MARKET_AVAILABLE!r} must be boolean at rows {rows}"
        )
    complete_quotes = converted[OPEN].notna() & converted[CURRENT].notna()
    availability_mismatch = availability.astype(bool).ne(complete_quotes)
    if availability_mismatch.any():
        rows = frame.index[availability_mismatch].tolist()[:5]
        raise ValueError(
            "dashboard release 'market available' contradicts Open/Current at rows "
            f"{rows}"
        )

    move_matches_quotes = pd.Series(
        np.isclose(
            converted[MARKET_MOVE].to_numpy(dtype=float, na_value=np.nan),
            (
                converted[CURRENT].to_numpy(dtype=float, na_value=np.nan)
                - converted[OPEN].to_numpy(dtype=float, na_value=np.nan)
            ),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=False,
        ),
        index=frame.index,
    )
    invalid_move = complete_quotes & ~move_matches_quotes
    if invalid_move.any():
        rows = frame.index[invalid_move].tolist()[:5]
        raise ValueError(
            "dashboard release Move must equal Current - Open where quotes exist; "
            f"invalid rows {rows}"
        )

    market_status = frame[MARKET_DATA_STATUS]
    invalid_market_status = (
        market_status.isna()
        | ~market_status.map(lambda value: isinstance(value, str))
        | market_status.astype("string").str.strip().eq("")
    )
    if invalid_market_status.any():
        rows = frame.index[invalid_market_status].tolist()[:5]
        raise ValueError(
            f"dashboard release market status is blank or non-text at rows {rows}"
        )


def build_dashboard_dataframe(
    config: pd.DataFrame | str | Path,
    thresholds: pd.DataFrame | str | Path | None = None,
    product_sources: ProductSources | None = None,
    multipliers: Mapping[str, float] | None = None,
    risk_dates: Mapping[str, date | datetime | str | pd.Timestamp] | None = None,
    *,
    market_date: date | datetime | str | pd.Timestamp,
    market_status: str,
    reported_underlyings: pd.DataFrame | str | Path | None = None,
) -> pd.DataFrame:
    """Build a display-ready frame from connector, config, and threshold inputs.

    REAL CONNECTOR INTEGRATION POINT: supply ``product_sources``, ``risk_dates``,
    governed portfolio ``config``, and approved ``thresholds``.
    ``product_sources`` is keyed by ProductSpec key (for example ``fxdelta``),
    while ``risk_dates`` is keyed by source type (for example ``fx/delta``).
    For transactional refreshes and readiness transitions, construct a
    ``RiskRefreshManager`` instead of repeatedly calling this one-shot helper.
    """
    if thresholds is None:
        raise ProductionIntegrationError(
            "build_dashboard_dataframe requires an explicit real threshold source"
        )
    configured = merge_config(
        build_all_pl(
            product_sources,
            multipliers,
            risk_dates,
            market_date=market_date,
            market_status=market_status,
        ),
        config,
    )
    reported = attach_reported_underlying(
        configured,
        reported_underlyings,
        allowed_pairs=RELEASE_RISK_PAIRS,
    )
    enriched = apply_baseline_promotions(reported, load_thresholds(thresholds))
    return to_dashboard_frame(enriched.loc[enriched[PORTFOLIO_MAPPED].eq(True)])
