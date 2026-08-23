"""Strict source validation and product-level market/P&L calculations."""

from __future__ import annotations

from datetime import date, datetime
from numbers import Real
from typing import Mapping

import numpy as np
import pandas as pd

from rebirth.domain.s01_schema import TENOR_OPTION, TENOR_ORDER_COLUMNS, TENOR_SWAP
from rebirth.domain.s02_products import (
    CREDIT_MEASURES,
    CREDIT_MEASURE_COLUMNS,
    CURRENT,
    DRISK,
    FrameSource,
    GROUP,
    LIVE,
    MARKET_AVAILABLE,
    MARKET_DATA_STATUS,
    MARKET_MOVE,
    MARKET_STATUS,
    OFFICIAL,
    OPEN,
    PL,
    PORTFOLIO,
    PRODUCT_SPECS,
    PRODUCT_SPECS_BY_SOURCE_TYPE,
    REGION,
    RISK,
    RISK_DATE,
    RISK_GREEK,
    RISK_TYPE,
    SOURCE_TYPE,
    SPLIT,
    UNDERLYING,
    ProductSources,
    ProductSpec,
    ProductionIntegrationError,
    _validate_multiplier,
    _validate_multipliers,
)


def _load_frame(
    source: FrameSource,
    *,
    label: str,
    allow_empty: bool = False,
) -> pd.DataFrame:
    if source is None:
        raise ProductionIntegrationError(
            f"{label} requires an explicit real connector DataFrame or callable"
        )
    if isinstance(source, pd.DataFrame):
        frame = source
    elif callable(source):
        frame = source()
    else:
        raise TypeError(
            "A source must be a pandas DataFrame or a zero-argument callable"
        )
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Data source functions must return a pandas DataFrame")
    if frame.empty and not allow_empty:
        raise ValueError("Data source returned an empty DataFrame")
    # Product adapters own any source-specific renaming. The shared boundary is
    # intentionally strict so one column name has one meaning everywhere.
    return frame.copy()


def _require_columns(frame: pd.DataFrame, columns: list[str], label: str) -> None:
    missing = [column for column in columns if column not in frame]
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def _coerce_numeric(
    frame: pd.DataFrame, columns: list[str], label: str
) -> pd.DataFrame:
    result = frame.copy()
    for column in columns:
        if result[column].map(lambda value: isinstance(value, (bool, np.bool_))).any():
            raise ValueError(f"{label} column {column!r} must not contain booleans")
        converted = pd.to_numeric(result[column], errors="coerce")
        invalid = converted.isna() | ~np.isfinite(converted)
        if invalid.any():
            rows = result.index[invalid].tolist()[:5]
            raise ValueError(
                f"{label} column {column!r} has missing, non-numeric, or non-finite values at rows {rows}"
            )
        result[column] = converted.astype(float)
    return result


def _validate_market_tenor_orders(
    frame: pd.DataFrame,
    spec: ProductSpec,
    label: str,
) -> pd.DataFrame:
    """Validate market-owned axis order without making it part of quote identity."""
    result = frame.copy()
    for axis in spec.axes:
        tenor_column = axis.column
        order_column = axis.order_column
        _require_columns(result, [order_column], label)
        boolean = result[order_column].map(
            lambda value: isinstance(value, (bool, np.bool_))
        )
        numeric = pd.to_numeric(result[order_column], errors="coerce")
        invalid = boolean | numeric.isna() | ~np.isfinite(numeric)
        invalid |= numeric.lt(0) | numeric.mod(1).ne(0)
        if invalid.any():
            rows = result.index[invalid].tolist()[:5]
            raise ValueError(
                f"{label} column {order_column!r} must contain non-negative "
                f"integer market orders at rows {rows}"
            )
        result[order_column] = numeric.astype("Int64")
        # Within one Source Type (fixed by ProductSpec), each Underlying has one
        # authority for a tenor label and one tenor label at each order position.
        tenor_to_order = result.groupby([UNDERLYING, tenor_column], dropna=False)[
            order_column
        ].nunique(dropna=False)
        if tenor_to_order.gt(1).any():
            raise ValueError(
                f"{label} has conflicting {order_column!r} values per "
                f"Source Type + Underlying + {tenor_column}"
            )
        order_to_tenor = result.groupby([UNDERLYING, order_column], dropna=False)[
            tenor_column
        ].nunique(dropna=False)
        if order_to_tenor.gt(1).any():
            raise ValueError(
                f"{label} maps more than one {tenor_column!r} to the same "
                f"{order_column!r} per Source Type + Underlying"
            )
    return result


def _require_nonblank(
    frame: pd.DataFrame, columns: list[str], label: str
) -> pd.DataFrame:
    """Reject null/blank join keys and normalize their surrounding whitespace."""
    result = frame.copy()
    for column in columns:
        missing = result[column].isna()
        normalized = result[column].astype("string").str.strip()
        invalid = missing | normalized.eq("")
        if invalid.any():
            rows = result.index[invalid].tolist()[:5]
            raise ValueError(
                f"{label} column {column!r} has null or blank keys at rows {rows}"
            )
        result[column] = normalized.astype(str)
    return result


def _enforce_product(
    frame: pd.DataFrame, spec: ProductSpec, label: str
) -> pd.DataFrame:
    result = frame.copy()
    if (
        RISK_TYPE in result
        and not result[RISK_TYPE].dropna().astype(str).eq(spec.risk_type).all()
    ):
        raise ValueError(f"{label} contains a Risk Type other than {spec.risk_type!r}")
    if (
        RISK_GREEK in result
        and not result[RISK_GREEK].dropna().astype(str).eq(spec.risk_greek).all()
    ):
        raise ValueError(
            f"{label} contains a Risk Greek other than {spec.risk_greek!r}"
        )
    result[RISK_TYPE] = spec.risk_type
    result[RISK_GREEK] = spec.risk_greek
    return result


def _as_timestamp(value: date | datetime | str | pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError("date values must not be NaT or blank")
    if timestamp.tzinfo is not None:
        # Preserve the caller's stated calendar day. Production connectors should
        # normalize to their agreed trading timezone before calling this function.
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


def market_date_for(
    calendar_date: date | datetime | str | pd.Timestamp,
) -> pd.Timestamp:
    """Return the latest weekday on or before the supplied calendar date.

    Cube deliberately uses pandas' Monday-to-Friday business-day convention
    only; no site-specific holiday calendar is inferred. Weekdays are returned
    unchanged, while Saturday and Sunday both resolve to the preceding Friday.
    Explicit user-selected dates are validated separately and are never rolled
    silently by this helper in the force-date path.
    """

    selected_date = _as_timestamp(calendar_date)
    if selected_date.weekday() >= 5:
        return selected_date - pd.offsets.BDay(1)
    return selected_date


def checker_date_for(
    market_date: date | datetime | str | pd.Timestamp,
) -> pd.Timestamp:
    """Return T-1 from the centralized weekday Market Date."""

    return market_date_for(market_date) - pd.offsets.BDay(1)


def risk_date_for(
    checker_date: date | datetime | str | pd.Timestamp,
    age: int,
) -> pd.Timestamp:
    """Apply checker Age to the already-derived checker date."""

    if isinstance(age, (bool, np.bool_)) or not isinstance(age, Real):
        raise TypeError("Age must be a non-negative integer")
    selected_age = float(age)
    if (
        not np.isfinite(selected_age)
        or selected_age < 0
        or not selected_age.is_integer()
    ):
        raise ValueError("Age must be a non-negative integer")

    return _as_timestamp(checker_date) - pd.offsets.BDay(int(selected_age))


def get_risk(
    risk_date: date | datetime | str | pd.Timestamp,
    source_type: str,
) -> pd.DataFrame:
    """Fail-closed generic risk connector boundary.

    ``risk_date`` is the effective T-1/T-2 (or forced) business date and
    ``source_type`` is one of the 16 source contracts, for example ``fx/delta``.
    Return a ``pandas.DataFrame`` containing ``Underlying``, ``Portfolio``,
    opaque connector-owned ``Group``, numeric authoritative ``Risk`` and
    ``dRisk``, plus every tenor column required by that source's
    ``ProductSpec``. ``Risk Type`` and ``Risk Greek`` are optional inputs
    because the common validator adds and enforces them. Credit connectors may
    additionally return columns named by ``CREDIT_MEASURE_COLUMNS``. Rows must
    be unique by underlying, applicable tenors, and portfolio.
    """
    try:
        spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    except KeyError as exc:
        raise ValueError(f"Unknown Source Type {source_type!r}") from exc
    normalized_date = _as_timestamp(risk_date)
    required = [UNDERLYING, *spec.tenor_columns, PORTFOLIO, GROUP, RISK, DRISK]
    # APP DATA ACCESS IS CENTRALIZED IN rebirth.services.s05_sources.get_risk.
    # Direct-library integration shape (comments only, never fallback data):
    # records = risk_client.fetch(source_type=source_type, risk_date=normalized_date)
    # return pd.DataFrame(records)
    raise ProductionIntegrationError(
        f"No real risk connector is configured for {source_type!r} on "
        f"{normalized_date.date()}. Implement get_risk() or inject risk_loader=...; "
        f"required columns are {required}."
    )


def get_market_open(
    source_type: str,
    open_date: date | datetime | str | pd.Timestamp,
    underlying: str,
    *,
    market_status: str,
) -> pd.DataFrame:
    """Fail-closed generic opening-market connector boundary.

    Return one row per source-specific market key for the authoritative T-1
    ``open_date`` with a finite numeric ``Open``. Required keys are
    ``Underlying`` plus the tenor columns declared by the source's
    ``ProductSpec``. ``Risk Type`` and ``Risk Greek`` may be supplied and will
    be checked. A genuinely unavailable market leg may be represented by an
    empty DataFrame with the correct schema; it must never be replaced with
    zero-valued quotes. ``market_status`` is the manager-selected ``Live`` or
    ``OFFICIAL`` source and must be used rather than independently inferred by
    the connector.
    """
    try:
        spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    except KeyError as exc:
        raise ValueError(f"Unknown Source Type {source_type!r}") from exc
    selected_date = _as_timestamp(open_date)
    if not isinstance(underlying, str) or not underlying.strip():
        raise ValueError("underlying must be nonblank text")
    selected_status = _require_market_status(market_status)
    required = [UNDERLYING, *spec.tenor_columns, *spec.tenor_order_columns, OPEN]
    # APP DATA ACCESS IS CENTRALIZED IN rebirth.services.s05_sources.get_market_open.
    # Direct-library integration shape (comments only, never fallback data):
    # records = market_client.fetch_open(source_type=source_type, date=selected_date)
    # return pd.DataFrame(records)
    raise ProductionIntegrationError(
        f"No real opening-market connector is configured for {source_type!r} on "
        f"{selected_date.date()}. Implement get_market_open() or inject "
        "market_open_loader=...; the loader also receives the ordered Risk "
        f"Underlying {underlying!r} and Market Status "
        f"{selected_status!r}; required columns are {required}."
    )


def _require_market_status(value: object) -> str:
    """Validate the exact connector routing value before any source I/O."""
    if value not in {LIVE, OFFICIAL}:
        raise ValueError("market_status must be exactly 'Live' or 'OFFICIAL'")
    return str(value)


def get_market_status(
    source_type: str,
    market_date: date | datetime | str | pd.Timestamp,
    underlying: str,
    *,
    market_status: str,
) -> pd.DataFrame:
    """Fail-closed generic current/official market connector boundary.

    ``source_type`` is a source contract and ``market_date`` is the selected view
    date. Return unique market keys plus finite numeric ``Current``. The caller also
    supplies the authoritative ``market_status`` (exactly ``Live`` or
    ``OFFICIAL``), which selects the real upstream source. A returned ``Market
    Status`` column is optional and, when present, must match that input.
    """
    try:
        spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    except KeyError as exc:
        raise ValueError(f"Unknown Source Type {source_type!r}") from exc
    selected_date = _as_timestamp(market_date)
    if not isinstance(underlying, str) or not underlying.strip():
        raise ValueError("underlying must be nonblank text")
    selected_status = _require_market_status(market_status)
    required = [UNDERLYING, *spec.tenor_columns, *spec.tenor_order_columns, CURRENT]
    # APP DATA ACCESS IS CENTRALIZED IN rebirth.services.s05_sources.get_market_status.
    # Direct-library integration shape (comments only, never fallback data):
    # if selected_status == LIVE:
    #     records = market_client.fetch_live(source_type=source_type, date=selected_date)
    # else:
    #     records = market_client.fetch_official(source_type=source_type, date=selected_date)
    # frame = pd.DataFrame(records)
    # frame[MARKET_STATUS] = selected_status
    # return frame
    raise ProductionIntegrationError(
        f"No real {selected_status} market connector is configured for "
        f"{source_type!r} on {selected_date.date()}. Implement get_market_status() "
        f"or inject market_status_loader=...; required columns are {required} "
        f"and optional {MARKET_STATUS!r} must equal {selected_status!r}; the "
        f"loader also receives Risk Underlying {underlying!r}."
    )


def get_product_risk(
    spec: ProductSpec,
    risk_date: date | datetime | str | pd.Timestamp,
    source: FrameSource = None,
) -> pd.DataFrame:
    """Validate one connector snapshot with connector-owned Group, Risk, and dRisk.

    PRODUCTION INTEGRATION POINT: ``source`` may be the connector DataFrame or a
    zero-argument callable already bound to this product and risk date. Prefer a
    ``ProductConnectorAdapter.risk`` when constructing the refresh manager.
    """
    if source is None:
        raise ProductionIntegrationError(
            f"{spec.key} risk requires a real connector source; provide source=... "
            "or configure ProductConnectorAdapter.risk"
        )
    _as_timestamp(risk_date)
    frame = _enforce_product(
        _load_frame(source, label=f"{spec.key} risk"),
        spec,
        f"{spec.key} risk",
    )
    key_columns = [RISK_TYPE, RISK_GREEK, UNDERLYING, *spec.tenor_columns, PORTFOLIO]
    required = [*key_columns, GROUP, RISK, DRISK]
    _require_columns(frame, required, f"{spec.key} risk")
    frame = _require_nonblank(frame, key_columns, f"{spec.key} risk")
    frame = _coerce_numeric(frame, [RISK, DRISK], f"{spec.key} risk")
    credit_measure_columns = [
        column for column in CREDIT_MEASURE_COLUMNS if column in frame
    ]
    if credit_measure_columns and spec.risk_type != "Credit":
        raise ValueError(
            f"{spec.key} risk contains Credit measure columns outside the Credit family"
        )
    if spec.risk_type == "Credit":
        for measure in CREDIT_MEASURES:
            risk_measure = f"{RISK} {measure}"
            drisk_measure = f"{DRISK} {measure}"
            supplied = (risk_measure in frame, drisk_measure in frame)
            if supplied[0] != supplied[1]:
                raise ValueError(
                    f"{spec.key} optional Credit measure {measure!r} must supply "
                    f"both {risk_measure!r} and {drisk_measure!r}, or omit both"
                )
    if credit_measure_columns:
        frame = _coerce_numeric(
            frame,
            credit_measure_columns,
            f"{spec.key} optional Credit measures",
        )
    if REGION in frame and spec.risk_type != "Credit":
        raise ValueError(
            f"{spec.key} risk contains {REGION!r} outside the Credit family"
        )
    position_keys = [*key_columns, *([REGION] if REGION in frame else [])]
    if frame.duplicated(position_keys).any():
        raise ValueError(f"{spec.key} risk has duplicate position keys")
    frame[SPLIT] = "Risk"
    columns = [
        RISK_TYPE,
        RISK_GREEK,
        SPLIT,
        UNDERLYING,
        *spec.tenor_columns,
        PORTFOLIO,
        GROUP,
        *([REGION] if REGION in frame else []),
        RISK,
        DRISK,
        *credit_measure_columns,
    ]
    return frame[columns].copy()


def get_product_market_open(
    spec: ProductSpec,
    open_date: date | datetime | str | pd.Timestamp,
    source: FrameSource,
) -> pd.DataFrame:
    """Validate one product's opening-market connector result.

    PRODUCTION INTEGRATION POINT: pass a date-bound ``source`` here for direct
    use, or inject ``ProductConnectorAdapter.market_open`` into the manager.
    """
    if source is None:
        raise ProductionIntegrationError(
            f"{spec.key} market open requires a real connector source; provide "
            "source=... or configure ProductConnectorAdapter.market_open"
        )
    _as_timestamp(open_date)
    columns = [*spec.market_keys, *spec.tenor_order_columns, OPEN]
    raw_frame = _load_frame(
        source,
        label=f"{spec.key} market open",
        allow_empty=True,
    )
    frame = _enforce_product(raw_frame, spec, f"{spec.key} market open")
    _require_columns(frame, columns, f"{spec.key} market open")
    if frame.empty:
        return frame[columns].copy()
    frame = _require_nonblank(frame, spec.market_keys, f"{spec.key} market open")
    frame = _coerce_numeric(frame, [OPEN], f"{spec.key} market open")
    frame = _validate_market_tenor_orders(frame, spec, f"{spec.key} market open")
    if frame.duplicated(spec.market_keys).any():
        raise ValueError(f"{spec.key} market open has duplicate join keys")
    return frame[columns].copy()


def get_product_market_status(
    spec: ProductSpec,
    market_date: date | datetime | str | pd.Timestamp,
    source: FrameSource,
    *,
    market_status: str,
) -> pd.DataFrame:
    """Validate the Live or OFFICIAL market leg.

    PRODUCTION INTEGRATION POINT: pass a date-bound ``source`` here for direct
    use, or inject ``ProductConnectorAdapter.market_status`` into the manager.
    """
    if source is None:
        raise ProductionIntegrationError(
            f"{spec.key} market status requires a real connector source; provide "
            "source=... or configure ProductConnectorAdapter.market_status"
        )
    _as_timestamp(market_date)
    selected_status = _require_market_status(market_status)
    columns = [
        *spec.market_keys,
        *spec.tenor_order_columns,
        CURRENT,
        MARKET_STATUS,
    ]
    raw_frame = _load_frame(
        source,
        label=f"{spec.key} market status",
        allow_empty=True,
    )
    frame = _enforce_product(raw_frame, spec, f"{spec.key} market status")
    status_was_supplied = MARKET_STATUS in frame
    if not status_was_supplied:
        frame[MARKET_STATUS] = selected_status
    _require_columns(frame, columns, f"{spec.key} current market")
    if frame.empty:
        return frame[columns].copy()
    frame = _require_nonblank(frame, spec.market_keys, f"{spec.key} market status")
    frame = _coerce_numeric(frame, [CURRENT], f"{spec.key} current market")
    frame = _validate_market_tenor_orders(frame, spec, f"{spec.key} market status")
    if status_was_supplied:
        supplied_status = frame[MARKET_STATUS]
        blank_status = supplied_status.isna() | supplied_status.astype(
            "string"
        ).str.strip().eq("")
        if blank_status.any():
            rows = frame.index[blank_status].tolist()[:5]
            raise ValueError(
                f"{spec.key} market status column {MARKET_STATUS!r} "
                f"has null or blank values at rows {rows}"
            )
        exact_status = supplied_status.map(
            lambda value: isinstance(value, str) and value == selected_status
        )
        if not exact_status.all():
            raise ValueError(
                f"{spec.key} market status must be exactly {selected_status!r} "
                "on every supplied row"
            )
    elif (
        not frame[MARKET_STATUS].eq(selected_status).all()
    ):  # pragma: no cover - defensive
        raise ValueError(
            f"{spec.key} generated market status must be exactly {selected_status!r}"
        )
    if frame.duplicated(spec.market_keys).any():
        raise ValueError(f"{spec.key} current market has duplicate join keys")
    return frame[columns].copy()


def _merge_validated_market_legs(
    spec: ProductSpec,
    market_open: pd.DataFrame,
    market_status: pd.DataFrame,
    *,
    selected_status: str,
) -> pd.DataFrame:
    """Merge quote legs and reconcile their shared market-owned axis authority."""
    selected_status = _require_market_status(selected_status)
    for axis in spec.axes:
        tenor_column = axis.column
        order_column = axis.order_column
        open_authority = market_open[
            [UNDERLYING, tenor_column, order_column]
        ].drop_duplicates()
        status_authority = market_status[
            [UNDERLYING, tenor_column, order_column]
        ].drop_duplicates()
        authority = open_authority.merge(
            status_authority,
            on=[UNDERLYING, tenor_column],
            how="inner",
            suffixes=("_open", "_status"),
            validate="one_to_one",
        )
        open_order = f"{order_column}_open"
        status_order = f"{order_column}_status"
        if not authority[open_order].eq(authority[status_order]).all():
            raise ValueError(
                f"{spec.key} market Open and Status disagree on {order_column!r} "
                f"per Source Type + Underlying + {tenor_column}"
            )

    market = market_open.merge(
        market_status,
        on=spec.market_keys,
        how="outer",
        validate="one_to_one",
        indicator=True,
        suffixes=("_open", "_status"),
    )
    # Order fields describe display authority, not quote identity.  Compare the
    # two legs above, then coalesce them after joining only on canonical keys.
    for order_column in spec.tenor_order_columns:
        open_order = f"{order_column}_open"
        status_order = f"{order_column}_status"
        market[order_column] = (
            market[open_order].combine_first(market[status_order]).astype("Int64")
        )
        market = market.drop(columns=[open_order, status_order])
    # Validate the coalesced union as well. Two disjoint legs must not be able
    # to assign the same order to different labels for one Underlying.
    market = _validate_market_tenor_orders(market, spec, f"{spec.key} merged market")
    # Status is routing metadata for the complete MarketBook, not merely a
    # property of rows returned by the Current leg. Open-only rows therefore
    # still state which source was selected for the missing Current quote.
    market[MARKET_STATUS] = selected_status
    market[MARKET_AVAILABLE] = (
        market["_merge"].eq("both") & market[OPEN].notna() & market[CURRENT].notna()
    )
    market[MARKET_DATA_STATUS] = np.select(
        [
            market[MARKET_AVAILABLE],
            market[OPEN].isna() & market[CURRENT].isna(),
            market[OPEN].isna(),
            market[CURRENT].isna(),
        ],
        [
            "Available",
            "Missing Open and Current (Live/OFFICIAL)",
            "Missing Open",
            "Missing Current (Live/OFFICIAL)",
        ],
        default="Incomplete market data",
    )
    market = market.drop(columns="_merge")
    market[MARKET_MOVE] = market[CURRENT] - market[OPEN]
    return market


def get_product_market(
    spec: ProductSpec,
    market_date: date | datetime | str | pd.Timestamp,
    open_source: FrameSource,
    status_source: FrameSource,
    *,
    market_status: str,
) -> pd.DataFrame:
    """Outer-join validated opening and Live/OFFICIAL connector legs.

    PRODUCTION INTEGRATION POINT: ``open_source`` and ``status_source`` accept
    connector DataFrames or zero-argument, date-bound callables. In the managed
    path they are populated from the configured adapter/generic loaders.
    """
    selected_date = _as_timestamp(market_date)
    selected_status = _require_market_status(market_status)
    market_open = get_product_market_open(spec, selected_date, open_source)
    market_current = get_product_market_status(
        spec,
        selected_date,
        status_source,
        market_status=selected_status,
    )
    return _merge_validated_market_legs(
        spec,
        market_open,
        market_current,
        selected_status=selected_status,
    )


def _raw_market_move(frame: pd.DataFrame) -> pd.Series:
    """Return the unscaled market move used by all P&L strategies."""
    return frame[CURRENT] - frame[OPEN]


def _pnl_move(spec: ProductSpec, frame: pd.DataFrame) -> pd.Series:
    """Apply the product's configured absolute or percentage move convention."""
    if spec.pl_formula == "identity":
        return pd.Series(1.0, index=frame.index, dtype=float)
    raw_move = _raw_market_move(frame)
    if spec.pl_formula == "percentage":
        nonzero_open = frame[OPEN].where(frame[OPEN].ne(0.0))
        return raw_move / nonzero_open
    return raw_move


def get_product_pl(
    spec: ProductSpec,
    risk_date: date | datetime | str | pd.Timestamp,
    risk_source: FrameSource = None,
    open_source: FrameSource = None,
    status_source: FrameSource = None,
    multiplier: float = 1.0,
    validated_risk: pd.DataFrame | None = None,
    validated_market: pd.DataFrame | None = None,
    *,
    market_date: date | datetime | str | pd.Timestamp,
    market_status: str,
) -> pd.DataFrame:
    """Join authoritative risk to market and apply the product P&L contract.

    PRODUCTION INTEGRATION POINT: direct callers inject ``risk_source``,
    ``open_source``, and ``status_source``; managed callers should configure the
    corresponding ``RiskRefreshManager`` loaders/adapters once. ``validated_risk``
    is for the manager's already-validated cache and is not a second connector.
    """
    selected_market_status = _require_market_status(market_status)
    validated_multiplier = _validate_multiplier(
        multiplier, label=f"multiplier for {spec.key!r}"
    )
    if validated_risk is not None:
        if risk_source is not None:
            raise ValueError("validated_risk cannot be combined with a raw risk source")
        risk = validated_risk.copy()
    else:
        risk = get_product_risk(spec, risk_date, risk_source)
    if validated_market is not None:
        if open_source is not None or status_source is not None:
            raise ValueError(
                "validated_market cannot be combined with raw market sources"
            )
        market = validated_market.copy()
    else:
        market = get_product_market(
            spec,
            market_date,
            open_source,
            status_source,
            market_status=selected_market_status,
        )
    result = risk.merge(
        market,
        on=spec.market_keys,
        how="left",
        validate="many_to_one",
        indicator="_market_merge",
    )
    no_market_row = result["_market_merge"].ne("both")
    result[MARKET_AVAILABLE] = result[MARKET_AVAILABLE].fillna(False).astype(bool)
    result.loc[no_market_row, MARKET_DATA_STATUS] = "No matching market row"
    result[MARKET_DATA_STATUS] = result[MARKET_DATA_STATUS].fillna(
        "No matching market row"
    )
    result = result.drop(columns="_market_merge")
    sort_columns = [UNDERLYING, *spec.tenor_order_columns, PORTFOLIO]
    result = result.sort_values(
        sort_columns,
        kind="stable",
        na_position="last",
    ).reset_index(drop=True)
    pnl_move = _pnl_move(spec, result)
    invalid_percentage_open = (
        spec.pl_formula == "percentage" and result[OPEN].eq(0.0).any()
    )
    if invalid_percentage_open:
        zero_open = result[OPEN].eq(0.0)
        result.loc[zero_open, MARKET_DATA_STATUS] = (
            "Open is zero; percentage P&L unavailable"
        )
    if spec.pl_formula != "taylor_gamma":
        result[PL] = result[RISK] * pnl_move * validated_multiplier
        result.loc[~result[MARKET_AVAILABLE], PL] = np.nan
        result[SPLIT] = "Risk"
        return result

    # Keep the Taylor P&L on the sourced Gamma/Risk position. The generated
    # Delta/Gamma row represents delta exposure only and therefore has no P&L.
    sourced = result.copy()
    sourced[SPLIT] = "Risk"
    raw_move = _raw_market_move(result)
    # Product metadata owns quote scaling and the development step. This keeps
    # the calculation generic and avoids product-name branches in the engine.
    taylor_move = raw_move * spec.gamma_move_scale
    developed_risk = result[RISK] * taylor_move / spec.gamma_risk_step
    sourced[PL] = 0.5 * developed_risk * taylor_move * validated_multiplier
    sourced.loc[~sourced[MARKET_AVAILABLE], PL] = np.nan

    # A developed Delta exists only when both market legs exist. Retain the
    # authoritative sourced Gamma row when market is missing, but do not emit a
    # placeholder derived row whose exposure cannot actually be calculated.
    derived = result.loc[result[MARKET_AVAILABLE]].copy()
    derived_developed_risk = developed_risk.loc[derived.index]
    derived[RISK_GREEK] = "Delta"
    derived[SPLIT] = "Gamma"
    derived[RISK] = derived_developed_risk
    # The derived Delta is a point-in-time development of Gamma.  There is no
    # connector-sourced prior-day Delta here, so manufacturing dRisk would be
    # misleading.  The sourced Gamma/Risk row above retains authoritative dRisk.
    derived[DRISK] = np.nan
    derived[PL] = 0.0
    combined = pd.concat([sourced, derived], ignore_index=True, sort=False)
    combined["__split_order__"] = combined[SPLIT].map({"Risk": 0, "Gamma": 1})
    combined = combined.sort_values(
        [UNDERLYING, *spec.tenor_order_columns, PORTFOLIO, "__split_order__"],
        kind="stable",
        na_position="last",
    )
    return combined.drop(columns="__split_order__").reset_index(drop=True)


def _with_dashboard_tenors(frame: pd.DataFrame, spec: ProductSpec) -> pd.DataFrame:
    result = frame.copy()
    if TENOR_SWAP not in result:
        result[TENOR_SWAP] = "Spot" if spec.key == "fxdelta" else "N/A"
    if TENOR_OPTION not in result:
        result[TENOR_OPTION] = "N/A"
    # Authority is supplied by market connectors. Risk-only unmatched rows keep
    # nullable orders so the presentation layer can apply a documented fallback
    # without pretending that Risk owned the ordering.
    for order_column in TENOR_ORDER_COLUMNS:
        if order_column not in result:
            result[order_column] = pd.Series(pd.NA, index=result.index, dtype="Int64")
        else:
            result[order_column] = pd.to_numeric(
                result[order_column], errors="raise"
            ).astype("Int64")
    return result


def _with_supplemental_credit_sp01(frame: pd.DataFrame) -> pd.DataFrame:
    """Attach the default Credit measure without inventing alternate measures.

    New Trades and XGAMMA carry the same generic Credit Delta sensitivity as
    the normal Risk adapter.  In the Credit UI that sensitivity is SP01.  dRisk
    remains unavailable for these supplemental rows and is not replaced with a
    fabricated zero.
    """

    if frame.empty:
        return frame
    result = frame.copy()
    credit_delta = result[RISK_TYPE].eq("Credit") & result[RISK_GREEK].eq("Delta")
    if not credit_delta.any():
        return result
    risk_sp01 = f"{RISK} SP01"
    drisk_sp01 = f"{DRISK} SP01"
    if risk_sp01 not in result:
        result[risk_sp01] = np.nan
    if drisk_sp01 not in result:
        result[drisk_sp01] = np.nan
    result.loc[credit_delta, risk_sp01] = result.loc[credit_delta, RISK]
    result.loc[credit_delta, drisk_sp01] = result.loc[credit_delta, DRISK]
    return result


def build_all_pl(
    product_sources: ProductSources | None = None,
    multipliers: Mapping[str, float] | None = None,
    risk_dates: Mapping[str, date | datetime | str | pd.Timestamp] | None = None,
    *,
    market_date: date | datetime | str | pd.Timestamp,
    market_status: str,
) -> pd.DataFrame:
    """Build validated P&L rows for every supported source contract.

    REAL CONNECTOR INTEGRATION POINT: for a one-shot build, populate
    ``product_sources[product_key]`` with ``risk``, ``open``, and ``status``
    DataFrames or date-bound callables, and supply explicit ``risk_dates``.
    Long-running applications should prefer ``RiskRefreshManager`` adapters.
    """
    if product_sources is None:
        raise ProductionIntegrationError(
            "build_all_pl requires real product_sources for all supported products"
        )
    if risk_dates is None:
        raise ProductionIntegrationError(
            "build_all_pl requires explicit risk_dates keyed by source type"
        )
    unknown_products = sorted(set(product_sources) - set(PRODUCT_SPECS))
    if unknown_products:
        raise ValueError(f"Unknown product source keys: {unknown_products}")
    missing_products = sorted(set(PRODUCT_SPECS) - set(product_sources))
    if missing_products:
        raise ProductionIntegrationError(
            f"Real connector sources are missing for products: {missing_products}"
        )
    selected_market_status = _require_market_status(market_status)
    validated_multipliers = _validate_multipliers(multipliers)
    selected_dates = dict(risk_dates)
    frames: list[pd.DataFrame] = []
    for key, spec in PRODUCT_SPECS.items():
        sources = product_sources[key]
        if not isinstance(sources, Mapping):
            raise TypeError(f"product_sources[{key!r}] must be a mapping")
        missing_legs = [
            leg
            for leg, available in (
                ("risk", sources.get("risk") is not None),
                ("open", sources.get("open") is not None),
                ("status", sources.get("status") is not None),
            )
            if not available
        ]
        if missing_legs:
            raise ProductionIntegrationError(
                f"product_sources[{key!r}] is missing real connector legs: "
                f"{missing_legs}"
            )
        if spec.source_type not in selected_dates:
            raise ValueError(f"No risk date supplied for {spec.source_type!r}")
        frame = get_product_pl(
            spec,
            selected_dates[spec.source_type],
            risk_source=sources.get("risk"),
            open_source=sources.get("open"),
            status_source=sources.get("status"),
            multiplier=validated_multipliers.get(key, 1.0),
            market_date=market_date,
            market_status=selected_market_status,
        )
        frame[SOURCE_TYPE] = spec.source_type
        frame[RISK_DATE] = _as_timestamp(selected_dates[spec.source_type])
        frames.append(_with_dashboard_tenors(frame, spec))
    return pd.concat(frames, ignore_index=True, sort=False)
