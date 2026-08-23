"""Bounded archive projections and exact Risk, Market, and P&L queries."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from rebirth.domain.s08_pnl import (
    ACTIVITY,
    CATEGORY,
    COLOSSUS_TYPE,
    HISTORY_MAPPING_STATUS,
    HISTORY_TYPE,
    MARKET_DATE,
    PL,
    PL_HISTORY_COLUMNS,
    PL_HISTORY_KEY,
    PREDICT_TYPE,
    PRODUCT,
    PLSendValidationError,
    RISK_GREEK,
    RISK_TYPE,
    SIGNOFF_GROUP,
    SUB_CATEGORY,
    UNDERLYING,
    load_legacy_pl_history_leaf,
    validate_pl_history_frame,
)
from rebirth.domain.s01_schema import (
    TENOR_OPTION,
    TENOR_OPTION_ORDER,
    TENOR_SWAP,
    TENOR_SWAP_ORDER,
    UNMAPPED_VALUE,
)
from rebirth.domain.s10_search import REPORTED_UNDERLYING, SOURCE_TYPE

from .s02_contracts import (
    ALL_ARCHIVE_FILE_NAMES,
    MAPPED_HISTORY_VALUE,
    MAPPING_STATUS,
    MARKET_ARCHIVE_COLUMNS,
    MARKET_FILE_NAME,
    MARKET_HISTORY_COLUMNS,
    PORTFOLIO,
    PORTFOLIO_AUTHORITY_COLUMNS,
    REVISION,
    RISK_DATE,
    RISK_FILE_NAME,
    RISK_HISTORY_METADATA_COLUMNS,
    RiskArchive,
    RiskArchiveValidationError,
    SNAPSHOT_DATE,
    SUCCESS_FILE_NAME,
    _CSV_MARKET_FILE_NAME,
    _CSV_RISK_FILE_NAME,
    _DATE_PATTERN,
    _LEGACY_HISTORY_FILE_NAMES,
    _OFFICIAL_HISTORY_FILE_NAMES,
    _PENDING_LEAF_PATTERN,
    _VERSIONED_METADATA_SCHEMA_VERSIONS,
    _archive_file_name,
    _manifest_versioned_metadata,
    _normalize_date,
    _nullable_numeric,
    _source_types_in_risk,
    _uses_parquet,
    _validate_text_columns,
    validate_colossus_frame,
    validate_market_archive_frame,
    validate_risk_archive_frame,
)
from .s03_io import (
    _completed_leaf_contract,
    _completed_leaf_date,
    _completed_v4_archive_days_cached,
    _file_sha256,
    _load_completed_leaf,
    _load_stock_leaf_cached,
    _read_archive_frame,
    _read_manifest,
    _validate_parquet_contract,
)


def build_history_portfolio_authority(risk: pd.DataFrame) -> pd.DataFrame:
    """Return one nonduplicating Portfolio authority for historical P&L.

    Colossus owns no Product or SignoffGroup.  Those two fields are authoritative
    only when the archived Predict snapshot has exactly one distinct
    ``(SignoffGroup, Product)`` pair for the Portfolio.  Ambiguous Portfolios are
    retained once and labelled ``Unmapped`` so callers can expose them without
    guessing or duplicating Colossus rows.  The remaining filter metadata is
    independently retained only when unique for that Portfolio.
    """

    validated = validate_risk_archive_frame(risk)
    required = (
        PORTFOLIO,
        SIGNOFF_GROUP,
        PRODUCT,
        ACTIVITY,
        CATEGORY,
        SUB_CATEGORY,
    )
    missing = [column for column in required if column not in validated]
    if missing:
        raise RiskArchiveValidationError(
            "official Risk Explorer snapshot is missing historical P&L authority "
            f"columns: {missing}"
        )
    normalized = _validate_text_columns(
        validated,
        required,
        label="official Risk Explorer snapshot",
    )
    portfolios = (
        normalized[[PORTFOLIO]]
        .drop_duplicates()
        .sort_values(PORTFOLIO, kind="stable")
        .reset_index(drop=True)
    )
    pairs = normalized[[PORTFOLIO, SIGNOFF_GROUP, PRODUCT]].drop_duplicates()
    pair_counts = pairs.groupby(PORTFOLIO, sort=False).size()
    valid_portfolios = set(pair_counts.loc[pair_counts.eq(1)].index.astype(str))
    unique_pairs = pairs.loc[pairs[PORTFOLIO].isin(valid_portfolios)]
    authority = portfolios.merge(
        unique_pairs,
        on=PORTFOLIO,
        how="left",
        validate="one_to_one",
    )
    mapped = authority[PORTFOLIO].isin(valid_portfolios)
    authority[HISTORY_MAPPING_STATUS] = np.where(
        mapped,
        MAPPED_HISTORY_VALUE,
        UNMAPPED_VALUE,
    )
    authority.loc[~mapped, [SIGNOFF_GROUP, PRODUCT]] = UNMAPPED_VALUE

    for column in (ACTIVITY, CATEGORY, SUB_CATEGORY):
        values = normalized[[PORTFOLIO, column]].drop_duplicates()
        counts = values.groupby(PORTFOLIO, sort=False).size()
        unique_portfolios = set(counts.loc[counts.eq(1)].index.astype(str))
        unique_values = values.loc[values[PORTFOLIO].isin(unique_portfolios)]
        authority = authority.merge(
            unique_values,
            on=PORTFOLIO,
            how="left",
            validate="one_to_one",
        )
        authority[column] = authority[column].fillna(UNMAPPED_VALUE)

    return authority.loc[:, list(PORTFOLIO_AUTHORITY_COLUMNS)].reset_index(drop=True)


def project_archive_to_pl_history(archive: RiskArchive) -> pd.DataFrame:
    """Project one archive into the existing canonical Colossus/Predict grain.

    Predict is summed from position rows only after grouping to SignoffGroup +
    Risk Type + Risk Greek + Underlying + Product + Portfolio. A partially
    missing PL group is omitted rather than treated as a partial or zero total.
    Colossus receives SignoffGroup and Product only from the strict archived
    Portfolio authority. Unknown or ambiguous Portfolios are retained once in
    the explicit Unmapped hierarchy instead of failing or being duplicated.
    """

    market_date = _normalize_date(archive.market_date, label="Market Date")
    risk = validate_risk_archive_frame(archive.risk)
    colossus = validate_colossus_frame(archive.colossus)
    authority_dimensions = (
        SIGNOFF_GROUP,
        ACTIVITY,
        CATEGORY,
        SUB_CATEGORY,
    )
    missing = [column for column in authority_dimensions if column not in risk]
    if missing:
        raise RiskArchiveValidationError(
            "official Risk Explorer snapshot is missing historical P&L authority "
            f"columns: {missing}"
        )
    normalized_risk = _validate_text_columns(
        risk,
        (
            PORTFOLIO,
            UNDERLYING,
            RISK_TYPE,
            RISK_GREEK,
            PRODUCT,
            SIGNOFF_GROUP,
            ACTIVITY,
            CATEGORY,
            SUB_CATEGORY,
        ),
        label="official Risk Explorer snapshot",
    )
    normalized_risk[PL] = _nullable_numeric(
        normalized_risk[PL],
        label="official Risk Explorer snapshot column 'PL'",
        allow_missing=True,
    )

    portfolio_authority = build_history_portfolio_authority(normalized_risk)
    predict_keys = [
        SIGNOFF_GROUP,
        RISK_TYPE,
        RISK_GREEK,
        UNDERLYING,
        PRODUCT,
        PORTFOLIO,
    ]
    predicted = (
        normalized_risk[predict_keys + [PL]]
        .groupby(
            predict_keys,
            as_index=False,
            sort=False,
            observed=True,
            dropna=False,
        )[PL]
        .agg(lambda values: values.sum(min_count=len(values)))
        .dropna(subset=[PL])
    )
    predicted = predicted.merge(
        portfolio_authority[[PORTFOLIO, ACTIVITY, CATEGORY, SUB_CATEGORY]],
        on=PORTFOLIO,
        how="left",
        validate="many_to_one",
    )
    predicted[HISTORY_MAPPING_STATUS] = MAPPED_HISTORY_VALUE
    predicted.insert(0, HISTORY_TYPE, PREDICT_TYPE)
    predicted.insert(0, MARKET_DATE, market_date)

    actual = colossus.merge(
        portfolio_authority,
        on=PORTFOLIO,
        how="left",
        validate="many_to_one",
    )
    authority_columns = (
        SIGNOFF_GROUP,
        PRODUCT,
        ACTIVITY,
        CATEGORY,
        SUB_CATEGORY,
        HISTORY_MAPPING_STATUS,
    )
    for column in authority_columns:
        actual[column] = actual[column].fillna(UNMAPPED_VALUE)
    actual.insert(0, HISTORY_TYPE, COLOSSUS_TYPE)
    actual.insert(0, MARKET_DATE, market_date)

    history = pd.concat(
        [
            actual[list(PL_HISTORY_COLUMNS)],
            predicted[list(PL_HISTORY_COLUMNS)],
        ],
        ignore_index=True,
    )
    duplicates = history.duplicated(list(PL_HISTORY_KEY), keep=False)
    if duplicates.any():
        keys = (
            history.loc[duplicates, list(PL_HISTORY_KEY)]
            .drop_duplicates()
            .to_dict("records")
        )
        raise RiskArchiveValidationError(
            f"Projected P&L history contains duplicate hierarchy keys: {keys}"
        )
    return history.sort_values(list(PL_HISTORY_KEY), kind="stable").reset_index(
        drop=True
    )


def _leaf_fingerprint(leaf: Path) -> tuple[tuple[str, int, int], ...]:
    """Return a cheap immutable-leaf cache key without rereading data frames."""

    return tuple(
        (file_name, path.stat().st_size, path.stat().st_mtime_ns)
        for file_name in ALL_ARCHIVE_FILE_NAMES
        if (path := leaf / file_name).is_file()
    )


@lru_cache(maxsize=512)
def _project_completed_leaf_cached(
    leaf_text: str,
    fingerprint: tuple[tuple[str, int, int], ...],
) -> pd.DataFrame:
    """Validate/hash one immutable leaf once per worker and cache its projection."""

    del fingerprint
    return project_archive_to_pl_history(_load_completed_leaf(Path(leaf_text)))


def _legacy_leaf_fingerprint(leaf: Path) -> tuple[tuple[str, int, int], ...]:
    """Fingerprint one immutable checked-in legacy date leaf."""

    try:
        fingerprint = []
        for file_name in sorted(_LEGACY_HISTORY_FILE_NAMES):
            stat = (leaf / file_name).stat()
            fingerprint.append((file_name, stat.st_size, stat.st_mtime_ns))
        return tuple(fingerprint)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect legacy P&L history leaf {leaf}: {exc}"
        ) from exc


@lru_cache(maxsize=512)
def _load_legacy_leaf_cached(
    leaf_text: str,
    fingerprint: tuple[tuple[str, int, int], ...],
) -> pd.DataFrame:
    """Parse one unchanged legacy date leaf at most once per worker."""

    del fingerprint
    try:
        return load_legacy_pl_history_leaf(Path(leaf_text))
    except PLSendValidationError as exc:
        raise RiskArchiveValidationError(str(exc)) from exc


def load_shared_pl_history(root: str | Path) -> pd.DataFrame:
    """Load one ``data/histo`` root containing legacy and official dates.

    Legacy demo leaves contain the old ``histo.csv``/``predicted.csv`` pair.
    Completed official leaves contain sole Predict Risk plus Colossus authority.
    A date leaf may use exactly one versioned contract. Partial
    official leaves without ``_SUCCESS`` are hidden; completed leaves are
    validated against their manifest before any rows are returned.
    """

    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return pd.DataFrame(columns=list(PL_HISTORY_COLUMNS))
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Shared P&L history root must be a directory: {directory}"
        )

    frames: list[pd.DataFrame] = []
    try:
        leaf_entries = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect shared P&L history root {directory}: {exc}"
        ) from exc
    for leaf in leaf_entries:
        if _PENDING_LEAF_PATTERN.fullmatch(leaf.name):
            continue
        if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
            raise RiskArchiveValidationError(
                "Shared P&L history root may contain only YYYY-MM-DD leaves; "
                f"found {leaf}"
            )
        market_date = _completed_leaf_date(leaf)
        try:
            entries = tuple(leaf.iterdir())
        except OSError as exc:
            raise RiskArchiveValidationError(
                f"Could not inspect shared P&L history leaf {leaf}: {exc}"
            ) from exc
        names = {path.name for path in entries}
        legacy_artifacts = names & _LEGACY_HISTORY_FILE_NAMES
        official_artifacts = names & _OFFICIAL_HISTORY_FILE_NAMES
        if legacy_artifacts and official_artifacts:
            raise RiskArchiveValidationError(
                f"P&L history date {market_date} mixes legacy and official files"
            )
        if official_artifacts:
            if SUCCESS_FILE_NAME not in names:
                continue
            projected = _project_completed_leaf_cached(
                str(leaf),
                _leaf_fingerprint(leaf),
            )
            frames.append(projected.copy(deep=True))
            continue
        legacy = _load_legacy_leaf_cached(
            str(leaf),
            _legacy_leaf_fingerprint(leaf),
        )
        frames.append(legacy.copy(deep=True))

    if not frames:
        return pd.DataFrame(columns=list(PL_HISTORY_COLUMNS))
    try:
        history = validate_pl_history_frame(pd.concat(frames, ignore_index=True))
    except PLSendValidationError as exc:
        raise RiskArchiveValidationError(str(exc)) from exc
    duplicates = history.duplicated(list(PL_HISTORY_KEY), keep=False)
    if duplicates.any():
        raise RiskArchiveValidationError(
            "Shared P&L history contains duplicate date/type/hierarchy keys"
        )
    return history


def _risk_leaf_fingerprint(leaf: Path) -> tuple[tuple[str, int, int], ...]:
    """Fingerprint only immutable files needed by an exact Risk-history read."""

    try:
        return tuple(
            (file_name, path.stat().st_size, path.stat().st_mtime_ns)
            for file_name in (_CSV_RISK_FILE_NAME, RISK_FILE_NAME, SUCCESS_FILE_NAME)
            if (path := leaf / file_name).is_file()
        )
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical Risk leaf {leaf}: {exc}"
        ) from exc


@lru_cache(maxsize=4096)
def _load_risk_identity_leaf_cached(
    leaf_text: str,
    fingerprint: tuple[tuple[str, int, int], ...],
    source_type: str,
    risk_type: str,
    risk_greek: str,
    identity_value: str,
    identity_mode: str,
) -> pd.DataFrame:
    """Validate versioned Risk authority and cache one exact history identity."""

    del fingerprint
    leaf = Path(leaf_text)
    market_date = _completed_leaf_date(leaf)
    names = {path.name for path in leaf.iterdir()}
    if SUCCESS_FILE_NAME not in names:
        return pd.DataFrame(columns=list(RISK_HISTORY_METADATA_COLUMNS))
    manifest = _read_manifest(leaf)
    _completed_leaf_contract(leaf, manifest, market_date)
    schema_version = int(manifest["schema_version"])
    if schema_version not in _VERSIONED_METADATA_SCHEMA_VERSIONS:
        return pd.DataFrame(columns=list(RISK_HISTORY_METADATA_COLUMNS))
    risk_file_name = _archive_file_name(schema_version, "risk")
    risk_path = leaf / risk_file_name
    digests = manifest.get("sha256")
    expected_digest = digests.get(risk_file_name) if isinstance(digests, dict) else None
    if expected_digest != _file_sha256(risk_path):
        raise RiskArchiveValidationError(
            f"Historical Risk does not match its completion marker: {risk_path}"
        )
    risk_columns = list(manifest["risk_columns"])
    risk_rows = int(manifest["risk_rows"])
    identity_column = REPORTED_UNDERLYING if identity_mode == "reported" else UNDERLYING
    if identity_column not in risk_columns:
        raise RiskArchiveValidationError(
            f"Historical Risk is missing identity column {identity_column!r}: {leaf}"
        )
    filters = [
        (SOURCE_TYPE, "==", source_type),
        (RISK_TYPE, "==", risk_type),
        (RISK_GREEK, "==", risk_greek),
        (identity_column, "==", identity_value),
    ]
    if _uses_parquet(schema_version):
        _validate_parquet_contract(
            risk_path,
            expected_columns=risk_columns,
            expected_rows=risk_rows,
        )
        source_frame = _read_archive_frame(
            risk_path,
            schema_version=schema_version,
            columns=[SOURCE_TYPE],
        )
        source_types = _source_types_in_risk(source_frame)
        selected = _read_archive_frame(
            risk_path,
            schema_version=schema_version,
            columns=risk_columns,
            filters=filters,
        )
        if not selected.empty:
            selected = validate_risk_archive_frame(selected)
    else:
        risk = validate_risk_archive_frame(
            _read_archive_frame(risk_path, schema_version=schema_version)
        )
        if risk_columns != list(risk.columns):
            raise RiskArchiveValidationError(
                f"Risk archive columns do not match its completion marker: {leaf}"
            )
        if risk_rows != len(risk):
            raise RiskArchiveValidationError(
                f"Risk archive row count does not match its completion marker: {leaf}"
            )
        source_types = _source_types_in_risk(risk)
        selected = risk
        for column, _operator, value in filters:
            selected = selected.loc[selected[column].eq(value)]
        selected = selected.copy()
    revision, risk_dates = _manifest_versioned_metadata(manifest, leaf=leaf)
    if set(risk_dates) != set(source_types):
        raise RiskArchiveValidationError(
            "versioned Risk archive risk_dates must be keyed exactly by "
            f"the Risk Source Type values in {leaf}; expected={list(source_types)}, "
            f"found={sorted(risk_dates)}"
        )
    if selected.empty:
        return pd.DataFrame(columns=[*RISK_HISTORY_METADATA_COLUMNS, *risk_columns])
    metadata_overlap = set(RISK_HISTORY_METADATA_COLUMNS) & set(selected.columns)
    if metadata_overlap:
        raise RiskArchiveValidationError(
            f"Historical Risk contains archive-owned metadata columns: "
            f"{sorted(metadata_overlap)}"
        )
    selected.insert(0, MAPPING_STATUS, MAPPED_HISTORY_VALUE)
    selected.insert(0, RISK_DATE, risk_dates[source_type])
    selected.insert(0, REVISION, revision)
    selected.insert(0, SNAPSHOT_DATE, market_date)
    return selected.reset_index(drop=True)


def _bounded_row_limit(value: object, *, label: str = "history row limit") -> int:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)):
        raise RiskArchiveValidationError(f"{label} must be a positive integer")
    selected = int(value)
    if selected < 1:
        raise RiskArchiveValidationError(f"{label} must be a positive integer")
    return selected


def load_risk_history_for_identity(
    root: str | Path,
    source_type: str,
    risk_type: str,
    risk_greek: str,
    underlying: str,
    *,
    identity_mode: str = "underlying",
    max_rows: int = 100_000,
) -> pd.DataFrame:
    """Return exact v3/v4 Risk rows with truthful daily metadata."""

    selected_source = _identity_argument(source_type, label=SOURCE_TYPE)
    selected_risk_type = _identity_argument(risk_type, label=RISK_TYPE)
    selected_risk_greek = _identity_argument(risk_greek, label=RISK_GREEK)
    selected_underlying = _identity_argument(underlying, label=UNDERLYING)
    if not isinstance(identity_mode, str):
        raise RiskArchiveValidationError("Risk identity mode must be text")
    selected_mode = identity_mode.strip().casefold()
    if selected_mode not in {"reported", "underlying"}:
        raise RiskArchiveValidationError(
            "Risk identity mode must be 'reported' or 'underlying'"
        )
    row_limit = _bounded_row_limit(max_rows)
    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return pd.DataFrame(columns=list(RISK_HISTORY_METADATA_COLUMNS))
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Historical Risk root must be a directory: {directory}"
        )

    frames: list[pd.DataFrame] = []
    row_count = 0
    try:
        leaves = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical Risk root {directory}: {exc}"
        ) from exc
    for leaf in leaves:
        if _PENDING_LEAF_PATTERN.fullmatch(leaf.name):
            continue
        if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
            raise RiskArchiveValidationError(
                f"Historical Risk root may contain only YYYY-MM-DD leaves; found {leaf}"
            )
        selected = _load_risk_identity_leaf_cached(
            str(leaf),
            _risk_leaf_fingerprint(leaf),
            selected_source,
            selected_risk_type,
            selected_risk_greek,
            selected_underlying,
            selected_mode,
        ).copy(deep=True)
        if selected.empty:
            continue
        row_count += len(selected)
        if row_count > row_limit:
            raise RiskArchiveValidationError(
                f"Historical Risk query exceeds its {row_limit}-row bound"
            )
        frames.append(selected)
    if not frames:
        return pd.DataFrame(columns=list(RISK_HISTORY_METADATA_COLUMNS))
    return pd.concat(frames, ignore_index=True, sort=False).reset_index(drop=True)


def _market_leaf_fingerprint(leaf: Path) -> tuple[tuple[str, int, int], ...]:
    """Fingerprint only files needed to establish historical market authority."""

    names = sorted(
        {_CSV_MARKET_FILE_NAME, MARKET_FILE_NAME, SUCCESS_FILE_NAME}
        | set(_LEGACY_HISTORY_FILE_NAMES)
    )
    try:
        return tuple(
            (file_name, path.stat().st_size, path.stat().st_mtime_ns)
            for file_name in names
            if (path := leaf / file_name).is_file()
        )
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical MarketBook leaf {leaf}: {exc}"
        ) from exc


@lru_cache(maxsize=4096)
def _load_market_identity_leaf_cached(
    leaf_text: str,
    fingerprint: tuple[tuple[str, int, int], ...],
    risk_type: str,
    risk_greek: str,
    underlying: str,
) -> pd.DataFrame:
    """Validate one unchanged market file and cache only one raw identity."""

    del fingerprint
    leaf = Path(leaf_text)
    market_date = _completed_leaf_date(leaf)
    names = {path.name for path in leaf.iterdir()}
    if SUCCESS_FILE_NAME in names:
        manifest = _read_manifest(leaf)
        expected_files = _completed_leaf_contract(leaf, manifest, market_date)
        schema_version = int(manifest["schema_version"])
        market_file_name = _archive_file_name(schema_version, "market")
        if market_file_name not in expected_files:
            return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
        digests = manifest.get("sha256")
        expected_digest = (
            digests.get(market_file_name) if isinstance(digests, dict) else None
        )
        market_path = leaf / market_file_name
        if expected_digest != _file_sha256(market_path):
            raise RiskArchiveValidationError(
                "Historical MarketBook does not match its completion marker: "
                f"{market_path}"
            )
        if _uses_parquet(schema_version):
            _validate_parquet_contract(
                market_path,
                expected_columns=list(MARKET_ARCHIVE_COLUMNS),
                expected_rows=int(manifest["market_rows"]),
            )
            archived_dates = _read_archive_frame(
                market_path,
                schema_version=schema_version,
                columns=[MARKET_DATE],
            )[MARKET_DATE].map(
                lambda value: _normalize_date(value, label="Market Date")
            )
            if archived_dates.drop_duplicates().tolist() != [market_date]:
                raise RiskArchiveValidationError(
                    "Historical MarketBook dates do not match its archive leaf: "
                    f"{market_path}"
                )
            market = _read_archive_frame(
                market_path,
                schema_version=schema_version,
                columns=list(MARKET_ARCHIVE_COLUMNS),
                filters=[
                    (RISK_TYPE, "==", risk_type),
                    (RISK_GREEK, "==", risk_greek),
                    (UNDERLYING, "==", underlying),
                ],
            )
            if market.empty:
                return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
            return validate_market_archive_frame(market, market_date=market_date)
    else:
        schema_version = 1
        market_file_name = _CSV_MARKET_FILE_NAME
        market_path = leaf / market_file_name
        missing_legacy = sorted(_LEGACY_HISTORY_FILE_NAMES - names)
        official_artifacts = names & _OFFICIAL_HISTORY_FILE_NAMES
        if official_artifacts:
            # A partial official write is never historical authority, even if a
            # market file happened to reach the target directory independently.
            return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
        if missing_legacy:
            raise RiskArchiveValidationError(
                f"Historical MarketBook date {market_date} is not a completed "
                f"legacy P&L leaf; missing={missing_legacy}"
            )
        if market_file_name not in names:
            return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
    market = _read_archive_frame(market_path, schema_version=schema_version)
    market = validate_market_archive_frame(market, market_date=market_date)
    return market.loc[
        market[RISK_TYPE].eq(risk_type)
        & market[RISK_GREEK].eq(risk_greek)
        & market[UNDERLYING].eq(underlying)
    ].reset_index(drop=True)


def _identity_argument(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RiskArchiveValidationError(f"{label} must be nonblank text")
    return value.strip()


def load_market_history_for_identity(
    root: str | Path,
    risk_type: str,
    risk_greek: str,
    underlying: str,
) -> pd.DataFrame:
    """Return one raw Quick Market identity across completed archive dates.

    Selection is the structured Risk Type/Risk Greek/raw Underlying triple,
    never a parsed display label.  Every stored quote cell is retained at its
    connector-owned tenor grain; no Portfolio join, aggregation, or weighting
    occurs.  Callers can therefore select one explicit tenor cell for a daily
    series, or render the complete historical curve/surface for each date.
    """

    selected_risk_type = _identity_argument(risk_type, label=RISK_TYPE)
    selected_risk_greek = _identity_argument(risk_greek, label=RISK_GREEK)
    selected_underlying = _identity_argument(underlying, label=UNDERLYING)
    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return pd.DataFrame(columns=list(MARKET_HISTORY_COLUMNS))
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Historical MarketBook root must be a directory: {directory}"
        )

    frames: list[pd.DataFrame] = []
    try:
        leaves = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical MarketBook root {directory}: {exc}"
        ) from exc
    for leaf in leaves:
        if _PENDING_LEAF_PATTERN.fullmatch(leaf.name):
            continue
        if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
            raise RiskArchiveValidationError(
                "Historical MarketBook root may contain only YYYY-MM-DD leaves; "
                f"found {leaf}"
            )
        selected = _load_market_identity_leaf_cached(
            str(leaf),
            _market_leaf_fingerprint(leaf),
            selected_risk_type,
            selected_risk_greek,
            selected_underlying,
        ).copy(deep=True)
        if not selected.empty:
            frames.append(selected)

    if not frames:
        return pd.DataFrame(columns=list(MARKET_HISTORY_COLUMNS))
    selected_history = pd.concat(frames, ignore_index=True, sort=False)
    source_types = selected_history[SOURCE_TYPE].drop_duplicates().tolist()
    if len(source_types) != 1:
        raise RiskArchiveValidationError(
            "Historical MarketBook identity resolves to multiple Source Types: "
            f"{source_types}"
        )
    duplicates = selected_history.duplicated(
        [MARKET_DATE, TENOR_SWAP, TENOR_OPTION], keep=False
    )
    if duplicates.any():
        keys = (
            selected_history.loc[duplicates, [MARKET_DATE, TENOR_SWAP, TENOR_OPTION]]
            .drop_duplicates()
            .to_dict("records")
        )
        raise RiskArchiveValidationError(
            f"Historical MarketBook identity contains duplicate daily quote cells: "
            f"{keys}"
        )
    return (
        selected_history.loc[:, list(MARKET_HISTORY_COLUMNS)]
        .sort_values(
            [
                MARKET_DATE,
                TENOR_SWAP_ORDER,
                TENOR_OPTION_ORDER,
                TENOR_SWAP,
                TENOR_OPTION,
            ],
            kind="stable",
            na_position="last",
        )
        .reset_index(drop=True)
    )


def load_full_market_history_for_identity(
    root: str | Path,
    source_type: str,
    risk_type: str,
    risk_greek: str,
    underlying: str,
    *,
    max_rows: int = 100_000,
) -> pd.DataFrame:
    """Return exact full-schema MarketBook rows across completed dates.

    Unlike the compact Quick Market loader, this Data-page boundary retains
    Source Type, Open, Current, Move, Market Status, and Market Data Status.
    V1/V2/V3/V4 completed market leaves and complete legacy market files remain
    readable; no Portfolio/reporting fields are joined onto quote grain.
    """

    selected_source = _identity_argument(source_type, label=SOURCE_TYPE)
    selected_risk_type = _identity_argument(risk_type, label=RISK_TYPE)
    selected_risk_greek = _identity_argument(risk_greek, label=RISK_GREEK)
    selected_underlying = _identity_argument(underlying, label=UNDERLYING)
    row_limit = _bounded_row_limit(max_rows)
    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
    if not directory.is_dir():
        raise RiskArchiveValidationError(
            f"Historical MarketBook root must be a directory: {directory}"
        )

    frames: list[pd.DataFrame] = []
    row_count = 0
    try:
        leaves = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError as exc:
        raise RiskArchiveValidationError(
            f"Could not inspect historical MarketBook root {directory}: {exc}"
        ) from exc
    for leaf in leaves:
        if _PENDING_LEAF_PATTERN.fullmatch(leaf.name):
            continue
        if not leaf.is_dir() or not _DATE_PATTERN.fullmatch(leaf.name):
            raise RiskArchiveValidationError(
                "Historical MarketBook root may contain only YYYY-MM-DD leaves; "
                f"found {leaf}"
            )
        selected = _load_market_identity_leaf_cached(
            str(leaf),
            _market_leaf_fingerprint(leaf),
            selected_risk_type,
            selected_risk_greek,
            selected_underlying,
        ).copy(deep=True)
        selected = selected.loc[selected[SOURCE_TYPE].eq(selected_source)]
        if selected.empty:
            continue
        row_count += len(selected)
        if row_count > row_limit:
            raise RiskArchiveValidationError(
                f"Historical MarketBook query exceeds its {row_limit}-row bound"
            )
        frames.append(selected)
    if not frames:
        return pd.DataFrame(columns=list(MARKET_ARCHIVE_COLUMNS))
    history = pd.concat(frames, ignore_index=True, sort=False)
    duplicates = history.duplicated([MARKET_DATE, TENOR_SWAP, TENOR_OPTION], keep=False)
    if duplicates.any():
        keys = (
            history.loc[duplicates, [MARKET_DATE, TENOR_SWAP, TENOR_OPTION]]
            .drop_duplicates()
            .to_dict("records")
        )
        raise RiskArchiveValidationError(
            "Historical MarketBook identity contains duplicate daily quote cells: "
            f"{keys}"
        )
    return (
        history.loc[:, list(MARKET_ARCHIVE_COLUMNS)]
        .sort_values(
            [
                MARKET_DATE,
                TENOR_SWAP_ORDER,
                TENOR_OPTION_ORDER,
                TENOR_SWAP,
                TENOR_OPTION,
            ],
            kind="stable",
            na_position="last",
        )
        .reset_index(drop=True)
    )


def clear_archive_caches() -> None:
    """Clear only in-process, reconstructable archive reader caches."""

    _completed_v4_archive_days_cached.cache_clear()
    _project_completed_leaf_cached.cache_clear()
    _load_legacy_leaf_cached.cache_clear()
    _load_market_identity_leaf_cached.cache_clear()
    _load_risk_identity_leaf_cached.cache_clear()
    _load_stock_leaf_cached.cache_clear()


__all__ = [
    "build_history_portfolio_authority",
    "clear_archive_caches",
    "load_full_market_history_for_identity",
    "load_market_history_for_identity",
    "load_risk_history_for_identity",
    "load_shared_pl_history",
    "project_archive_to_pl_history",
]
