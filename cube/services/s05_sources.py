"""Lazy site-owned connector boundary over explicit temp CSV fixtures.

Replace individual public functions with authorized production connectors while
preserving their exact parameters and ordered DataFrame schemas.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from cube.adapters.s06_crossgamma import get_cross_gamma as get_cross_gamma_matrix
from cube.adapters.s07_newpositions import (
    get_new_positions as get_new_position_blotter,
)
from cube.domain.s03_calculations import market_date_for
from cube.domain.s02_products import (
    CREDIT_MEASURE_COLUMNS,
    CURRENT,
    LIVE,
    MARKET_STATUS,
    MRX_FILE,
    OFFICIAL,
    OPEN,
    PORTFOLIO,
    PRODUCT_SPECS_BY_SOURCE_TYPE,
    REGION,
    UNDERLYING,
    VOL_SCORE,
    ProductConnectorAdapter,
    ProductRiskBundle,
)
from cube.domain.s01_schema import (
    PORTFOLIO_CONFIG_REQUIRED_COLUMNS,
    PORTFOLIO_FIELD_BY_KEY,
    TENOR_COLUMNS,
    TENOR_ORDER_COLUMNS,
)
from cube.history import COLOSSUS_COLUMNS
from cube.services.s06_refresh import RiskRefreshManager
from cube.services.s07_tenorreduction import (
    get_reduced_tenor_catalog_source,
    get_reduced_tenor_matrix_bundle,
)


TEMP_DATA_DIRECTORY = Path(__file__).resolve().parents[2] / "data"
TEMP_CSV_FILES = {
    "risk_readiness": TEMP_DATA_DIRECTORY / "s01_readiness.csv",
    "risk_checker": TEMP_DATA_DIRECTORY / "s02_checker.csv",
    "risk": TEMP_DATA_DIRECTORY / "s03_risk.csv",
    "market_open": TEMP_DATA_DIRECTORY / "s04_open.csv",
    "market_status": TEMP_DATA_DIRECTORY / "s05_current.csv",
    "portfolio_config": TEMP_DATA_DIRECTORY / "s06_portfolios.csv",
    "risk_thresholds": TEMP_DATA_DIRECTORY / "s07_thresholds.csv",
    "reported_underlyings": TEMP_DATA_DIRECTORY / "s09_reported.csv",
    "pinned_promotions": TEMP_DATA_DIRECTORY / "s12_pinned.csv",
}

_SOURCE_TYPE = "Source Type"
_TEMP_NOTICE = "TEMP_REPLACE_ME"
_LEGACY_ARCHIVE_NOTICE = "FAKE_REPLACE_ME"
_TEMP_CSV_SCHEMAS = {
    "risk_readiness": ("Risk Type", "Risk Greek", "Age"),
    "risk_checker": ("Risk Type", "Risk Greek", MRX_FILE, "Product"),
    "risk": (
        _SOURCE_TYPE,
        "Underlying",
        *TENOR_COLUMNS,
        "Portfolio",
        "Group",
        "Risk",
        "dRisk",
        VOL_SCORE,
        *CREDIT_MEASURE_COLUMNS,
    ),
    "market_open": (
        _SOURCE_TYPE,
        "Underlying",
        *TENOR_COLUMNS,
        *TENOR_ORDER_COLUMNS,
        "Open",
    ),
    "market_status": (
        _SOURCE_TYPE,
        "Underlying",
        *TENOR_COLUMNS,
        *TENOR_ORDER_COLUMNS,
        "Current",
    ),
    "portfolio_config": PORTFOLIO_CONFIG_REQUIRED_COLUMNS,
    "risk_thresholds": ("Risk Type", "Risk Greek", "PL", "Risk", "dRisk"),
    "reported_underlyings": (
        "Risk Type",
        "Risk Greek",
        "Underlying",
        "Reported Underlying",
    ),
    "pinned_promotions": (
        "Risk Type",
        "Risk Greek",
        "Reported Underlying",
        "Underlying",
    ),
}


class TempCsvConnectorError(RuntimeError):
    """Raised when an explicit temp connector CSV is missing or malformed."""


@lru_cache(maxsize=32)
def _load_temp_csv(
    dataset: str,
    path_text: str,
    modified_ns: int,
    size: int,
) -> pd.DataFrame:
    """Parse one immutable file revision; callers always receive a copy."""

    del modified_ns, size  # Their values intentionally form the cache key.
    path = Path(path_text)
    expected_columns = _TEMP_CSV_SCHEMAS[dataset]
    try:
        frame = pd.read_csv(
            path,
            dtype="string",
            encoding="utf-8-sig",
            keep_default_na=False,
        )
    except (OSError, UnicodeError, pd.errors.ParserError) as exc:
        raise TempCsvConnectorError(
            f"Could not read temp connector file {path}: {exc}"
        ) from exc
    actual_columns = tuple(str(column).strip() for column in frame.columns)
    if actual_columns != expected_columns:
        raise TempCsvConnectorError(
            f"Temp connector file {path.name} must have columns "
            f"{list(expected_columns)} in that order; found {list(actual_columns)}."
        )
    if frame.empty and dataset != "pinned_promotions":
        raise TempCsvConnectorError(f"Temp connector file {path.name} has no rows.")
    frame.columns = list(expected_columns)
    if _SOURCE_TYPE in expected_columns:
        _validate_source_coverage(frame, _SOURCE_TYPE, dataset)
    return frame


def _temp_csv_revision(dataset: str) -> tuple[Path, str, int, int]:
    """Return one file revision key without copying or parsing its contents."""

    path = TEMP_CSV_FILES[dataset]
    try:
        stat = path.stat()
    except OSError as exc:
        raise TempCsvConnectorError(
            f"Temp connector file is missing: {path}. Restore it or replace the "
            f"{dataset!r} loader in cube.services.s05_sources with a real function."
        ) from exc
    return path, str(path.resolve()), stat.st_mtime_ns, stat.st_size


@lru_cache(maxsize=1024)
def _load_temp_source_partition(
    dataset: str,
    path_text: str,
    modified_ns: int,
    size: int,
    source_type: str,
    underlying: str | None,
) -> pd.DataFrame:
    """Cache one immutable-by-convention source/Underlying file partition."""

    frame = _load_temp_csv(dataset, path_text, modified_ns, size)
    scoped = frame.loc[frame[_SOURCE_TYPE].eq(source_type)]
    if underlying is not None:
        scoped = scoped.loc[scoped["Underlying"].eq(underlying)]
    return scoped.reset_index(drop=True)


def _read_temp_csv(dataset: str) -> pd.DataFrame:
    """Read one fixed placeholder file, reusing only the same file revision."""

    _path, path_text, modified_ns, size = _temp_csv_revision(dataset)
    frame = _load_temp_csv(dataset, path_text, modified_ns, size)
    return frame.copy(deep=True)


def _normalized_date(value: pd.Timestamp, *, parameter: str) -> pd.Timestamp:
    """Validate a connector date even though static placeholder rows are reused."""
    timestamp = pd.Timestamp(value)
    if pd.isna(timestamp):
        raise ValueError(f"{parameter} must not be blank or NaT")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_localize(None)
    return timestamp.normalize()


def _business_date(value: pd.Timestamp, *, parameter: str) -> pd.Timestamp:
    """Require a weekday using the pipeline's centralized date authority."""

    selected_date = _normalized_date(value, parameter=parameter)
    if market_date_for(selected_date) != selected_date:
        raise ValueError(f"{parameter} must be a business day")
    return selected_date


def _market_status(value: object) -> str:
    """Reject ambiguous status routing before a connector reads any source."""
    if value not in {LIVE, OFFICIAL}:
        raise ValueError("market_status must be exactly 'Live' or 'OFFICIAL'")
    return str(value)


def get_market_state(
    market_date: pd.Timestamp,
    *,
    trading_timezone: str = "Europe/London",
    now: datetime | pd.Timestamp | None = None,
) -> str:
    """Resolve the one authoritative Live/OFFICIAL source for a market date.

    Replace this function body with the real market-status service. The refresh
    manager calls it once per refresh, validates the exact returned value, and
    passes that same value to every per-Underlying Open and Current connector.
    The checked-in temp implementation follows the desk's 22:00 trading-time
    cutoff: an earlier date is OFFICIAL, while today's date becomes OFFICIAL at
    22:00 in the configured timezone. Weekend inputs use the same centralized
    rollback as the manager and therefore resolve to the preceding Friday.
    ``now`` exists only for deterministic fixture tests; production callers
    leave it unset.
    """

    selected_date = market_date_for(
        _normalized_date(market_date, parameter="market_date")
    )
    zone = ZoneInfo(trading_timezone)
    trading_now = pd.Timestamp(datetime.now(zone) if now is None else now)
    if trading_now.tzinfo is None:
        trading_now = trading_now.tz_localize(zone)
    else:
        trading_now = trading_now.tz_convert(zone)
    trading_today = pd.Timestamp(trading_now.date())
    if selected_date < trading_today:
        return OFFICIAL
    if selected_date == trading_today and trading_now.hour >= 22:
        return OFFICIAL
    return LIVE


def _source_spec(source_type: str):
    try:
        return PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    except KeyError as exc:
        raise ValueError(f"Unknown source_type {source_type!r}") from exc


def _validate_source_coverage(frame: pd.DataFrame, column: str, dataset: str) -> None:
    expected = set(PRODUCT_SPECS_BY_SOURCE_TYPE)
    actual = set(frame[column].astype(str))
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        raise TempCsvConnectorError(
            f"{TEMP_CSV_FILES[dataset].name} source coverage is invalid; "
            f"missing={missing}, extra={extra}."
        )


def _require_temp_notice(
    frame: pd.DataFrame,
    columns: list[str],
    *,
    dataset: str,
) -> None:
    """Keep placeholder warnings visible in every reporting dimension."""
    for column in columns:
        values = frame[column].astype(str)
        invalid = ~values.str.contains(_TEMP_NOTICE, regex=False)
        if invalid.any():
            rows = frame.index[invalid].tolist()[:5]
            raise TempCsvConnectorError(
                f"{TEMP_CSV_FILES[dataset].name} column {column!r} must contain "
                f"{_TEMP_NOTICE!r}; invalid rows {rows}. Replace the loader code, "
                "not the warning, when connecting real data."
            )


def _source_rows(
    dataset: str,
    source_type: str,
    output_columns: list[str],
    *,
    underlying: str | None = None,
    allow_empty: bool = False,
) -> pd.DataFrame:
    _path, path_text, modified_ns, size = _temp_csv_revision(dataset)
    partition = _load_temp_source_partition(
        dataset,
        path_text,
        modified_ns,
        size,
        source_type,
        underlying,
    )
    if partition.empty and not allow_empty:
        raise TempCsvConnectorError(
            f"{TEMP_CSV_FILES[dataset].name} has no rows for {source_type!r}."
        )
    # The cached partition is never exposed: connector callers receive only a
    # narrow defensive copy, so one call cannot mutate a later call's result.
    return partition.loc[:, output_columns].copy().reset_index(drop=True)


def get_risk_checker(
    checker_date: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return ``(risk_readiness_df, risk_checker_df)`` from one dated call.

    The readiness frame contains ``Risk Type``, ``Risk Greek``, and ``Age``.
    Missing known pairs are completed by the pipeline with Age 0. The inventory
    frame contains ``Risk Type``, ``Risk Greek``, ``MRX File``, and ``Product``.
    A real implementation should fetch both atomically for ``checker_date``.
    """

    _business_date(checker_date, parameter="checker_date")
    readiness = _read_temp_csv("risk_readiness")
    checker = _read_temp_csv("risk_checker")
    return readiness.copy(), checker.copy()


def get_risk(risk_date: pd.Timestamp, source_type: str) -> pd.DataFrame:
    """Return temp Risk/dRisk rows for one source and requested risk date.

    Real replacement contract: use both parameters and return ``Underlying``,
    ``Portfolio``, ``Group``, ``Risk``, ``dRisk``, ``Vol Score``, plus the source's required
    tenor fields. Credit may additionally return connector-owned ``Region``.
    Connector Group, Region, Risk, and dRisk remain authoritative.
    """
    _business_date(risk_date, parameter="risk_date")
    spec = _source_spec(source_type)
    output_columns = [
        "Underlying",
        *spec.tenor_columns,
        "Portfolio",
        "Group",
        "Risk",
        "dRisk",
        VOL_SCORE,
    ]
    if spec.risk_type == "Credit":
        output_columns.extend(CREDIT_MEASURE_COLUMNS)
    frame = _source_rows("risk", source_type, output_columns)
    if spec.risk_type == "Credit":
        # The supplied Credit connector owns a Region dimension.  The public
        # fixture intentionally has no site taxonomy, so its deterministic and
        # truthful fallback is the connector-owned Group rather than an invented
        # geography.  A real Credit loader should return its authoritative
        # Region directly and remove this fixture-only derivation.
        frame.insert(frame.columns.get_loc("Group") + 1, REGION, frame["Group"])
    _require_temp_notice(
        frame,
        ["Underlying", *spec.tenor_columns, "Portfolio"],
        dataset="risk",
    )
    return frame


def get_cross_gamma_sensitivities(market_date: pd.Timestamp) -> pd.DataFrame:
    """Return validated portfolio-level XGAMMA sensitivity matrix rows."""

    selected_date = _normalized_date(market_date, parameter="market_date")
    return get_cross_gamma_matrix(selected_date)


def get_new_trades(market_date: pd.Timestamp) -> pd.DataFrame:
    """Return the validated mixed MARKET/CASHFLOW New Trades blotter."""

    selected_date = _normalized_date(market_date, parameter="market_date")
    return get_new_position_blotter(selected_date)


def get_market_open(
    source_type: str,
    open_date: pd.Timestamp,
    underlying: str,
    *,
    market_status: str,
) -> pd.DataFrame:
    """Return temp opening quotes for one source and requested T-1 date.

    Real replacement contract: use the T-1 business date and requested
    Underlying, returning numeric ``Open``, the source's tenor fields, and its
    applicable tenor-order authority. The manager supplies one Risk-derived
    ``underlying`` per call. Use the explicit ``market_status`` to select the
    Live or OFFICIAL dataset.
    """
    _business_date(open_date, parameter="open_date")
    _market_status(market_status)
    if not isinstance(underlying, str) or not underlying.strip():
        raise ValueError("underlying must be nonblank text")
    spec = _source_spec(source_type)
    output_columns = [
        "Underlying",
        *spec.tenor_columns,
        *spec.tenor_order_columns,
        "Open",
    ]
    frame = _source_rows(
        "market_open",
        source_type,
        output_columns,
        underlying=underlying.strip(),
        allow_empty=True,
    )
    _require_temp_notice(
        frame,
        ["Underlying", *spec.tenor_columns],
        dataset="market_open",
    )
    return frame


def get_market_status(
    source_type: str,
    market_date: pd.Timestamp,
    underlying: str,
    *,
    market_status: str,
) -> pd.DataFrame:
    """Return a temp numeric Live/OFFICIAL leg for the requested market date.

    Real replacement contract: use the date and requested Underlying, returning
    numeric ``Current``, the source's tenor fields, and the same applicable
    ``Tenor ... Order`` authority as Open. Product adapters call once per member
    of the ordered Risk-derived Underlying tuple.

    ``market_status`` is supplied by the manager as exactly ``Live`` or
    ``OFFICIAL``. A real connector uses it to choose the upstream source rather
    than comparing the date to its own clock.
    """
    _business_date(market_date, parameter="market_date")
    selected_status = _market_status(market_status)
    if not isinstance(underlying, str) or not underlying.strip():
        raise ValueError("underlying must be nonblank text")
    spec = _source_spec(source_type)
    output_columns = [
        "Underlying",
        *spec.tenor_columns,
        *spec.tenor_order_columns,
        CURRENT,
    ]
    frame = _source_rows(
        "market_status",
        source_type,
        output_columns,
        underlying=underlying.strip(),
        allow_empty=True,
    )
    _require_temp_notice(
        frame,
        ["Underlying", *spec.tenor_columns],
        dataset="market_status",
    )
    frame[MARKET_STATUS] = selected_status
    return frame


def _bulk_underlying_scope(underlyings: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize the manager-owned ordered scope for a bulk market connector."""

    if not isinstance(underlyings, tuple):
        raise TypeError("underlyings must be an ordered tuple of text values")
    normalized: list[str] = []
    for underlying in underlyings:
        if not isinstance(underlying, str) or not underlying.strip():
            raise ValueError("underlyings must contain only nonblank text")
        normalized.append(underlying.strip())
    if len(set(normalized)) != len(normalized):
        raise ValueError("underlyings must be unique")
    return tuple(normalized)


def _get_fx_delta_market_bulk(
    dataset: str,
    source_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    """Read one FX-Delta source partition and preserve requested scope order."""

    date_parameter = "open_date" if dataset == "market_open" else "market_date"
    _business_date(source_date, parameter=date_parameter)
    selected_status = _market_status(market_status)
    requested = _bulk_underlying_scope(underlyings)
    spec = _source_spec("fx/delta")
    value_column = OPEN if dataset == "market_open" else CURRENT
    output_columns = [
        UNDERLYING,
        *spec.tenor_columns,
        *spec.tenor_order_columns,
        value_column,
    ]
    frame = _source_rows(
        dataset,
        spec.source_type,
        output_columns,
        allow_empty=True,
    )
    requested_order = {underlying: index for index, underlying in enumerate(requested)}
    frame = frame.loc[frame[UNDERLYING].isin(requested)].copy()
    if not frame.empty:
        frame["__bulk_underlying_order"] = frame[UNDERLYING].map(requested_order)
        frame = (
            frame.sort_values("__bulk_underlying_order", kind="stable")
            .drop(columns="__bulk_underlying_order")
            .reset_index(drop=True)
        )
    _require_temp_notice(
        frame,
        [UNDERLYING, *spec.tenor_columns],
        dataset=dataset,
    )
    if dataset == "market_status":
        frame[MARKET_STATUS] = selected_status
    return frame


def get_fx_delta_market_open_bulk(
    open_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    """Return all requested temp FX-Delta opening quotes in one source read."""

    return _get_fx_delta_market_bulk(
        "market_open",
        open_date,
        underlyings,
        market_status=market_status,
    )


def get_fx_delta_market_status_bulk(
    market_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    """Return all requested temp FX-Delta current quotes in one source read."""

    return _get_fx_delta_market_bulk(
        "market_status",
        market_date,
        underlyings,
        market_status=market_status,
    )


def get_portfolio_config(portfolio_date: pd.Timestamp) -> pd.DataFrame:
    """Return Portfolio mappings effective one business day before market date.

    Real replacement contract: return every required column from
    ``cube.domain.s01_schema.PORTFOLIO_CONFIG_REQUIRED_COLUMNS``. Optional registered
    fields such as ``Sub Category`` are preserved when supplied. The manager
    supplies ``market_date - BDay(1)`` as ``portfolio_date``.
    """

    _business_date(portfolio_date, parameter="portfolio_date")
    frame = _read_temp_csv("portfolio_config")
    _require_temp_notice(
        frame,
        [
            column
            for column in PORTFOLIO_CONFIG_REQUIRED_COLUMNS
            if column != PORTFOLIO_FIELD_BY_KEY["product"].external_name
        ],
        dataset="portfolio_config",
    )
    return frame.copy()


def get_risk_thresholds() -> pd.DataFrame:
    """Return temp positive absolute PL/Risk/dRisk promotion limits.

    Real replacement contract: return one unique ``Risk Type`` + ``Risk Greek``
    row with positive absolute ``PL``, ``Risk``, and ``dRisk`` limits.
    """
    return _read_temp_csv("risk_thresholds").copy()


def get_reported_underlyings() -> pd.DataFrame:
    """Return the cross-product raw-to-reporting Underlying map.

    Real replacement contract: return exactly ``Risk Type``, ``Risk Greek``,
    ``Underlying``, and ``Reported Underlying``. The first three columns form a
    unique source key; multiple source keys may share one reported target.
    """

    frame = _read_temp_csv("reported_underlyings")
    _require_temp_notice(
        frame,
        ["Underlying", "Reported Underlying"],
        dataset="reported_underlyings",
    )
    return frame.copy()


def get_pinned_promotions() -> pd.DataFrame:
    """Return exact raw-to-reported identities that receive the ``*`` marker.

    Real replacement contract: return exactly ``Risk Type``, ``Risk Greek``,
    ``Reported Underlying``, and ``Underlying``. The four columns form a unique
    key. Unlike temp connector data, these governed labels need no placeholder
    notice because they are intended to be maintained directly.
    """

    return _read_temp_csv("pinned_promotions").copy()


def get_colossus_pl(market_date: pd.Timestamp) -> pd.DataFrame:
    """Return official Colossus P&L at the archive's four-key grain.

    REAL CONNECTOR INTEGRATION POINT: replace this body with the site-owned
    Colossus function. It must return exactly ``Portfolio``, ``Underlying``,
    ``Risk Type``, ``Risk Greek``, and ``PL`` with one row per first four
    columns. The active fixture reads the selected completed
    ``colossus.parquet`` leaf from the unified history archive; Product remains
    governed separately by the official Risk Explorer snapshot.
    """

    selected_date = _normalized_date(market_date, parameter="market_date")
    source = (
        TEMP_DATA_DIRECTORY
        / "histo"
        / selected_date.date().isoformat()
        / "colossus.parquet"
    )
    expected = tuple(COLOSSUS_COLUMNS)
    try:
        frame = pd.read_parquet(source)
    except (OSError, ValueError) as exc:
        raise TempCsvConnectorError(
            f"Could not read temp Colossus P&L file {source}: {exc}"
        ) from exc
    actual = tuple(str(column).strip() for column in frame.columns)
    if actual != expected:
        raise TempCsvConnectorError(
            f"Temp Colossus P&L file {source} must have columns "
            f"{list(expected)} in that order; found {list(actual)}"
        )
    # Keep v4 Parquet leaves as immutable provenance while presenting their
    # identities through the current temp-fixture contract.
    for column in (PORTFOLIO, UNDERLYING):
        frame[column] = (
            frame[column]
            .astype(str)
            .str.replace(
                _LEGACY_ARCHIVE_NOTICE,
                _TEMP_NOTICE,
                regex=False,
            )
        )
    _require_temp_notice(
        frame,
        [PORTFOLIO, "Underlying"],
        dataset="colossus_pl",
    )
    return frame[list(COLOSSUS_COLUMNS)].copy()


def send_sog_pl(frame: pd.DataFrame) -> None:
    """Reject external SOG delivery while the fixture boundary is active."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("send_sog_pl expects a pandas DataFrame")
    raise RuntimeError(
        "External SOG delivery is disabled in fixture mode; "
        "replace cube.services.s05_sources.send_sog_pl for an authorized deployment"
    )


def send_portfolio_pl(frame: pd.DataFrame) -> None:
    """Reject external Portfolio delivery while the fixture boundary is active."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("send_portfolio_pl expects a pandas DataFrame")
    raise RuntimeError(
        "External Portfolio delivery is disabled in fixture mode; "
        "replace cube.services.s05_sources.send_portfolio_pl for an authorized deployment"
    )


def _get_csv_product_connector_adapters() -> Mapping[str, ProductConnectorAdapter]:
    """Build the per-source views over the active temp CSV loaders.

    Every source gets its own bound callable. FX Delta additionally exposes one
    bulk Open hook and one bulk Current hook; the manager prefers those hooks so
    replacing them with a real batched API does not change any other product.
    """
    adapters: dict[str, ProductConnectorAdapter] = {}
    for source_type in PRODUCT_SPECS_BY_SOURCE_TYPE:

        def risk(
            risk_date: pd.Timestamp, *, _source: str = source_type
        ) -> ProductRiskBundle:
            return ProductRiskBundle(
                risk=get_risk(risk_date, _source),
                matrices=get_reduced_tenor_matrix_bundle(),
            )

        def market_open(
            open_date: pd.Timestamp,
            underlying: str,
            *,
            market_status: str,
            _source: str = source_type,
        ) -> pd.DataFrame:
            return get_market_open(
                _source, open_date, underlying, market_status=market_status
            )

        def market_status_connector(
            market_date: pd.Timestamp,
            underlying: str,
            *,
            market_status: str,
            _source: str = source_type,
        ) -> pd.DataFrame:
            return get_market_status(
                _source, market_date, underlying, market_status=market_status
            )

        risk.__name__ = f"get_{source_type.replace('/', '_')}_risk"
        market_open.__name__ = f"get_{source_type.replace('/', '_')}_market_open"
        market_status_connector.__name__ = (
            f"get_{source_type.replace('/', '_')}_market_status"
        )
        adapters[source_type] = ProductConnectorAdapter(
            risk=risk,
            market_open=market_open,
            market_status=market_status_connector,
            market_open_bulk=(
                get_fx_delta_market_open_bulk if source_type == "fx/delta" else None
            ),
            market_status_bulk=(
                get_fx_delta_market_status_bulk if source_type == "fx/delta" else None
            ),
        )
    return adapters


def get_product_connector_adapters() -> Mapping[str, ProductConnectorAdapter]:
    """Return the active per-product connector adapters."""

    return _get_csv_product_connector_adapters()


def build_production_refresh_manager(
    *,
    stage_delays: Mapping[str, float] | None = None,
    logger: logging.Logger | None = None,
) -> RiskRefreshManager:
    """Compose Cube from the explicit connector functions over temp datasets.

    Every loader is passed by reference.  Constructing the WSGI app performs no
    source I/O; the browser-triggered initial refresh calls and validates every
    boundary after the refresh shell is visible.
    """
    trading_timezone = (
        os.getenv("CUBE_MARKET_TIMEZONE", "Europe/London").strip() or "Europe/London"
    )

    def resolve_market_state(market_date: pd.Timestamp) -> str:
        return get_market_state(
            market_date,
            trading_timezone=trading_timezone,
        )

    resolve_market_state.__name__ = "get_market_state"
    return RiskRefreshManager(
        get_portfolio_config,
        thresholds=get_risk_thresholds,
        reported_underlyings=get_reported_underlyings,
        pinned_promotions=get_pinned_promotions,
        risk_checker_loader=get_risk_checker,
        market_status_resolver=resolve_market_state,
        risk_loader=get_risk,
        cross_gamma_matrix_loader=get_cross_gamma_sensitivities,
        new_trades_loader=get_new_trades,
        market_open_loader=get_market_open,
        market_status_loader=get_market_status,
        connector_adapters=get_product_connector_adapters(),
        reduced_tenor_catalog=get_reduced_tenor_catalog_source(),
        stage_delays=stage_delays,
        trading_timezone=trading_timezone,
        logger=logger,
    )


__all__ = [
    "TEMP_CSV_FILES",
    "TEMP_DATA_DIRECTORY",
    "TempCsvConnectorError",
    "build_production_refresh_manager",
    "get_cross_gamma_sensitivities",
    "get_colossus_pl",
    "get_fx_delta_market_open_bulk",
    "get_fx_delta_market_status_bulk",
    "get_market_open",
    "get_market_state",
    "get_market_status",
    "get_new_trades",
    "get_pinned_promotions",
    "get_portfolio_config",
    "get_product_connector_adapters",
    "get_reported_underlyings",
    "get_risk",
    "get_risk_checker",
    "get_risk_thresholds",
    "send_portfolio_pl",
    "send_sog_pl",
]
