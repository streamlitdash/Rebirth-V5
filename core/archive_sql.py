"""Lazy in-memory DuckDB views and bounded P&L history queries.

Parquet leaves remain the sole persisted archive.  Merely constructing a
repository performs no filesystem or DuckDB work; explicit SQL access or a P&L
query validates the completed schema-v4 leaves and opens ``:memory:`` only.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import RLock

import duckdb
import pandas as pd

from core.s04_pl import (
    ACTIVITY,
    CATEGORY,
    COLOSSUS_TYPE,
    HISTORY_IDENTITY_COLUMNS,
    HISTORY_MAPPING_STATUS,
    HISTORY_TYPE,
    MARKET_DATE,
    PL,
    PREDICT_TYPE,
    PRODUCT,
    PLSendValidationError,
    PORTFOLIO,
    RISK_GREEK,
    RISK_TYPE,
    SIGNOFF_GROUP,
    SUB_CATEGORY,
    UNDERLYING,
)
from core.s11_risk_archive import (
    COLOSSUS_COLUMNS,
    MARKET_ARCHIVE_COLUMNS,
    REVISION,
    RISK_DATE,
    RISK_PROJECTION_COLUMNS,
    SNAPSHOT_DATE,
    CompletedArchiveDay,
    RiskArchiveValidationError,
    list_completed_v4_archive_days,
)
from core.s07_stock import STOCK_COLUMNS


PL_HISTORY_DEPTH = "Hierarchy Depth"
PL_HISTORY_LEVEL = "Hierarchy Level"
PL_HISTORY_LABEL = "Hierarchy Label"
PL_HISTORY_PATH = "Hierarchy Path"
PL_HISTORY_LEAF = "Hierarchy Leaf"
PL_HISTORY_DAILY_PREDICT = "Daily Predict"
PL_HISTORY_MTD_COLOSSUS = "MTD Colossus"
PL_HISTORY_MTD_PREDICT = "MTD Predict"
PL_HISTORY_YTD_COLOSSUS = "YTD Colossus"
PL_HISTORY_YTD_PREDICT = "YTD Predict"
PL_HISTORY_SUMMARY_COLUMNS = (
    PL_HISTORY_DEPTH,
    PL_HISTORY_LEVEL,
    PL_HISTORY_LABEL,
    PL_HISTORY_PATH,
    PL_HISTORY_LEAF,
    PL_HISTORY_DAILY_PREDICT,
    PL_HISTORY_MTD_COLOSSUS,
    PL_HISTORY_MTD_PREDICT,
    PL_HISTORY_YTD_COLOSSUS,
    PL_HISTORY_YTD_PREDICT,
)
PL_HISTORY_MAX_VISIBLE_NODES = 5_000
PL_HISTORY_MAX_OPEN_PARENTS = 128
PL_HISTORY_MAX_SERIES_ROWS = 524
_PL_FILTER_COLUMNS = (ACTIVITY, SIGNOFF_GROUP, PORTFOLIO, CATEGORY, SUB_CATEGORY)
_PL_TYPES = (COLOSSUS_TYPE, PREDICT_TYPE)
_SERIES_PRESETS = frozenset(("wtd", "mtd", "ytd", "all", "custom"))
_MAX_TEXT = 5_000
_PL_HISTORY_MEMORY_LIMIT = "384MB"
_PL_HISTORY_THREADS = 2


@dataclass(frozen=True)
class PLHistoryHierarchyResult:
    """Small visible hierarchy result plus filtered archive statistics."""

    summary: pd.DataFrame
    row_count: int
    date_count: int
    minimum_date: str | None
    maximum_date: str | None
    unmapped_rows: int


@dataclass(frozen=True)
class PLHistorySeriesResult:
    """Bounded daily series and its resolved filtered-history range."""

    series: pd.DataFrame
    minimum_date: str | None
    maximum_date: str | None
    resolved_start: str | None
    resolved_end: str | None


def _empty_series() -> pd.DataFrame:
    return pd.DataFrame(columns=[MARKET_DATE, HISTORY_TYPE, PL])


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=list(PL_HISTORY_SUMMARY_COLUMNS))


def _resolved_path(path: Sequence[object]) -> tuple[str, ...]:
    if isinstance(path, (str, bytes)) or not isinstance(path, Sequence):
        raise PLSendValidationError("P&L history path must be a sequence")
    if len(path) > len(HISTORY_IDENTITY_COLUMNS):
        raise PLSendValidationError("P&L history path is deeper than its hierarchy")
    values = tuple(str(value).strip() for value in path)
    if any(not value or len(value) > _MAX_TEXT for value in values):
        raise PLSendValidationError(
            "P&L history path values must be bounded nonblank text"
        )
    return values


def _normalized_open_paths(value: object) -> tuple[tuple[str, ...], ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PLSendValidationError("P&L history open paths must be a sequence")
    paths = {_resolved_path(path) for path in value}
    paths.discard(())
    if len(paths) > PL_HISTORY_MAX_OPEN_PARENTS:
        raise PLSendValidationError(
            f"P&L history may open at most {PL_HISTORY_MAX_OPEN_PARENTS} branches"
        )
    return tuple(sorted(paths, key=lambda path: (len(path), path)))


def _normalized_filters(
    selections: Mapping[str, Sequence[object] | None] | None,
) -> dict[str, tuple[str, ...]]:
    if selections is None:
        return {}
    if not isinstance(selections, Mapping):
        raise TypeError("P&L history filters must be a mapping")
    unknown = sorted(set(selections) - set(_PL_FILTER_COLUMNS))
    if unknown:
        raise PLSendValidationError(f"Unknown P&L history filters: {unknown}")
    normalized: dict[str, tuple[str, ...]] = {}
    for column in _PL_FILTER_COLUMNS:
        raw = selections.get(column)
        if raw is None:
            continue
        if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence):
            raise PLSendValidationError(
                f"P&L history filter {column!r} must be a sequence"
            )
        values = {
            text.casefold()
            for value in raw
            if (text := str(value).strip()) and len(text) <= _MAX_TEXT
        }
        if values:
            normalized[column] = tuple(sorted(values))
    return normalized


def _filter_clause(
    selections: Mapping[str, Sequence[object] | None] | None,
    *,
    exclude_selected: bool,
    alias: str = "h",
) -> tuple[str, list[object]]:
    filters = _normalized_filters(selections)
    if not filters:
        return "TRUE", []
    clauses: list[str] = []
    parameters: list[object] = []
    for column, values in filters.items():
        placeholders = ", ".join("?" for _value in values)
        clauses.append(
            f'lower(trim(CAST({alias}."{column}" AS VARCHAR))) IN ({placeholders})'
        )
        parameters.extend(values)
    joined = (" OR " if exclude_selected else " AND ").join(clauses)
    return (f"NOT ({joined})" if exclude_selected else f"({joined})"), parameters


def _empty_view(
    connection: duckdb.DuckDBPyConnection,
    name: str,
    columns: Sequence[tuple[str, str]],
) -> None:
    projection = ", ".join(
        f'CAST(NULL AS {data_type}) AS "{column}"' for column, data_type in columns
    )
    connection.execute(f"CREATE VIEW {name} AS SELECT {projection} WHERE FALSE")


def _create_empty_archive_views(connection: duckdb.DuckDBPyConnection) -> None:
    _empty_view(
        connection,
        "archive_days",
        (
            (SNAPSHOT_DATE, "DATE"),
            (REVISION, "BIGINT"),
            ("Stock Date", "DATE"),
            ("Risk Dates", "JSON"),
        ),
    )
    risk_columns = tuple(
        dict.fromkeys(
            (
                "Source Type",
                *RISK_PROJECTION_COLUMNS,
                ACTIVITY,
                SIGNOFF_GROUP,
                CATEGORY,
                SUB_CATEGORY,
            )
        )
    )
    _empty_view(
        connection,
        "risk_history",
        (
            (SNAPSHOT_DATE, "DATE"),
            (REVISION, "BIGINT"),
            (RISK_DATE, "DATE"),
            *(
                (column, "DOUBLE" if column in {"Risk", "dRisk", PL} else "VARCHAR")
                for column in risk_columns
            ),
        ),
    )
    _empty_view(
        connection,
        "market_history",
        (
            (SNAPSHOT_DATE, "DATE"),
            (REVISION, "BIGINT"),
            *((column, "VARCHAR") for column in MARKET_ARCHIVE_COLUMNS),
        ),
    )
    _empty_view(
        connection,
        "colossus_history",
        (
            (SNAPSHOT_DATE, "DATE"),
            (REVISION, "BIGINT"),
            *(
                (column, "DOUBLE" if column == PL else "VARCHAR")
                for column in COLOSSUS_COLUMNS
            ),
        ),
    )
    _empty_view(
        connection,
        "stock_history",
        (
            ("Stock Date", "DATE"),
            (REVISION, "BIGINT"),
            *((column, "VARCHAR") for column in STOCK_COLUMNS),
        ),
    )


def _create_archive_views(
    connection: duckdb.DuckDBPyConnection,
    days: tuple[CompletedArchiveDay, ...],
) -> None:
    if not days:
        _create_empty_archive_views(connection)
        return

    risk_paths = [str(day.risk_path.resolve()) for day in days]
    colossus_paths = [str(day.colossus_path.resolve()) for day in days]
    market_paths = [str(day.market_path.resolve()) for day in days]
    stock_paths = [str(day.stock_path.resolve()) for day in days if day.stock_path]
    connection.from_parquet(risk_paths, filename=True, union_by_name=True).create_view(
        "_risk_files"
    )
    connection.from_parquet(
        colossus_paths, filename=True, union_by_name=False
    ).create_view("_colossus_files")
    connection.from_parquet(
        market_paths, filename=True, union_by_name=False
    ).create_view("_market_files")
    if stock_paths:
        connection.from_parquet(
            stock_paths, filename=True, union_by_name=False
        ).create_view("_stock_files")

    connection.execute(
        """
        CREATE TABLE _archive_files (
            snapshot_date DATE,
            revision BIGINT,
            stock_date DATE,
            risk_dates JSON,
            risk_path VARCHAR,
            colossus_path VARCHAR,
            market_path VARCHAR,
            stock_path VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO _archive_files VALUES (?, ?, ?, ?::JSON, ?, ?, ?, ?)",
        [
            (
                day.snapshot_date,
                day.revision,
                day.stock_date,
                json.dumps(dict(day.risk_dates), sort_keys=True),
                str(day.risk_path.resolve()),
                str(day.colossus_path.resolve()),
                str(day.market_path.resolve()),
                str(day.stock_path.resolve()) if day.stock_path else None,
            )
            for day in days
        ],
    )
    connection.execute(
        "CREATE TABLE _archive_risk_dates ("
        "snapshot_date DATE, source_type VARCHAR, risk_date DATE)"
    )
    connection.executemany(
        "INSERT INTO _archive_risk_dates VALUES (?, ?, ?)",
        [
            (day.snapshot_date, source_type, risk_date)
            for day in days
            for source_type, risk_date in day.risk_dates.items()
        ],
    )
    connection.execute(
        f'''CREATE VIEW archive_days AS
            SELECT snapshot_date AS "{SNAPSHOT_DATE}",
                   revision AS "{REVISION}",
                   stock_date AS "Stock Date",
                   risk_dates AS "Risk Dates"
            FROM _archive_files'''
    )
    connection.execute(
        f'''CREATE VIEW risk_history AS
            SELECT f.snapshot_date AS "{SNAPSHOT_DATE}",
                   f.revision AS "{REVISION}",
                   d.risk_date AS "{RISK_DATE}",
                   r.* EXCLUDE(filename)
            FROM _risk_files r
            JOIN _archive_files f ON r.filename = f.risk_path
            LEFT JOIN _archive_risk_dates d
              ON d.snapshot_date = f.snapshot_date
             AND d.source_type = r."Source Type"'''
    )
    connection.execute(
        f'''CREATE VIEW market_history AS
            SELECT f.snapshot_date AS "{SNAPSHOT_DATE}",
                   f.revision AS "{REVISION}",
                   m.* EXCLUDE(filename)
            FROM _market_files m
            JOIN _archive_files f ON m.filename = f.market_path'''
    )
    connection.execute(
        f'''CREATE VIEW colossus_history AS
            SELECT f.snapshot_date AS "{SNAPSHOT_DATE}",
                   f.revision AS "{REVISION}",
                   c.* EXCLUDE(filename)
            FROM _colossus_files c
            JOIN _archive_files f ON c.filename = f.colossus_path'''
    )
    if stock_paths:
        connection.execute(
            f'''CREATE VIEW stock_history AS
                SELECT f.stock_date AS "Stock Date",
                       f.revision AS "{REVISION}",
                       s.* EXCLUDE(filename)
                FROM _stock_files s
                JOIN _archive_files f ON s.filename = f.stock_path'''
        )
    else:
        _empty_view(
            connection,
            "stock_history",
            (
                ("Stock Date", "DATE"),
                (REVISION, "BIGINT"),
                *((column, "VARCHAR") for column in STOCK_COLUMNS),
            ),
        )

    missing_risk_date = connection.execute(
        f'''SELECT 1 FROM (
                SELECT "{SNAPSHOT_DATE}", "Source Type" FROM risk_history
                GROUP BY ALL
                EXCEPT
                SELECT snapshot_date, source_type FROM _archive_risk_dates
            ) UNION ALL SELECT 1 FROM (
                SELECT snapshot_date, source_type FROM _archive_risk_dates
                EXCEPT
                SELECT "{SNAPSHOT_DATE}", "Source Type" FROM risk_history
                GROUP BY ALL
            ) LIMIT 1'''
    ).fetchone()
    if missing_risk_date is not None:
        raise RiskArchiveValidationError(
            "schema-v4 risk_dates do not exactly match archived Source Type values"
        )
    wrong_market_date = connection.execute(
        f'''SELECT 1 FROM market_history
            WHERE CAST("{MARKET_DATE}" AS DATE) <> "{SNAPSHOT_DATE}"
            LIMIT 1'''
    ).fetchone()
    if wrong_market_date is not None:
        raise RiskArchiveValidationError(
            "schema-v4 Market Date values do not match their manifest dates"
        )


def _materialize_pl_history(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f'''
        CREATE VIEW _pl_projection AS
        WITH portfolio_authority AS (
            SELECT
                "{SNAPSHOT_DATE}",
                "{PORTFOLIO}",
                CASE WHEN count(DISTINCT struct_pack(
                    signoff := "{SIGNOFF_GROUP}", product := "{PRODUCT}"
                )) = 1 THEN min("{SIGNOFF_GROUP}") ELSE 'Unmapped' END
                    AS "{SIGNOFF_GROUP}",
                CASE WHEN count(DISTINCT struct_pack(
                    signoff := "{SIGNOFF_GROUP}", product := "{PRODUCT}"
                )) = 1 THEN min("{PRODUCT}") ELSE 'Unmapped' END
                    AS "{PRODUCT}",
                CASE WHEN count(DISTINCT "{ACTIVITY}") = 1
                    THEN min("{ACTIVITY}") ELSE 'Unmapped' END AS "{ACTIVITY}",
                CASE WHEN count(DISTINCT "{CATEGORY}") = 1
                    THEN min("{CATEGORY}") ELSE 'Unmapped' END AS "{CATEGORY}",
                CASE WHEN count(DISTINCT "{SUB_CATEGORY}") = 1
                    THEN min("{SUB_CATEGORY}") ELSE 'Unmapped' END
                    AS "{SUB_CATEGORY}",
                CASE WHEN count(DISTINCT struct_pack(
                    signoff := "{SIGNOFF_GROUP}", product := "{PRODUCT}"
                )) = 1 THEN 'Mapped' ELSE 'Unmapped' END
                    AS "{HISTORY_MAPPING_STATUS}"
            FROM risk_history
            GROUP BY "{SNAPSHOT_DATE}", "{PORTFOLIO}"
        ),
        predict AS (
            SELECT
                "{SNAPSHOT_DATE}",
                "{SIGNOFF_GROUP}", "{RISK_TYPE}", "{RISK_GREEK}",
                "{UNDERLYING}", "{PRODUCT}", "{PORTFOLIO}",
                sum("{PL}") AS "{PL}"
            FROM risk_history
            GROUP BY "{SNAPSHOT_DATE}", "{SIGNOFF_GROUP}", "{RISK_TYPE}",
                     "{RISK_GREEK}", "{UNDERLYING}", "{PRODUCT}", "{PORTFOLIO}"
            HAVING count("{PL}") = count(*)
        ),
        projected_predict AS (
            SELECT
                p."{SNAPSHOT_DATE}" AS "{MARKET_DATE}",
                '{PREDICT_TYPE}' AS "{HISTORY_TYPE}",
                a."{ACTIVITY}", p."{SIGNOFF_GROUP}", a."{CATEGORY}",
                a."{SUB_CATEGORY}", p."{RISK_TYPE}", p."{RISK_GREEK}",
                p."{UNDERLYING}", p."{PRODUCT}", p."{PORTFOLIO}",
                'Mapped' AS "{HISTORY_MAPPING_STATUS}", p."{PL}"
            FROM predict p
            JOIN portfolio_authority a
              ON a."{SNAPSHOT_DATE}" = p."{SNAPSHOT_DATE}"
             AND a."{PORTFOLIO}" = p."{PORTFOLIO}"
        ),
        projected_colossus AS (
            SELECT
                c."{SNAPSHOT_DATE}" AS "{MARKET_DATE}",
                '{COLOSSUS_TYPE}' AS "{HISTORY_TYPE}",
                coalesce(a."{ACTIVITY}", 'Unmapped') AS "{ACTIVITY}",
                coalesce(a."{SIGNOFF_GROUP}", 'Unmapped') AS "{SIGNOFF_GROUP}",
                coalesce(a."{CATEGORY}", 'Unmapped') AS "{CATEGORY}",
                coalesce(a."{SUB_CATEGORY}", 'Unmapped') AS "{SUB_CATEGORY}",
                c."{RISK_TYPE}", c."{RISK_GREEK}", c."{UNDERLYING}",
                coalesce(a."{PRODUCT}", 'Unmapped') AS "{PRODUCT}",
                c."{PORTFOLIO}",
                coalesce(a."{HISTORY_MAPPING_STATUS}", 'Unmapped')
                    AS "{HISTORY_MAPPING_STATUS}",
                c."{PL}"
            FROM colossus_history c
            LEFT JOIN portfolio_authority a
              ON a."{SNAPSHOT_DATE}" = c."{SNAPSHOT_DATE}"
             AND a."{PORTFOLIO}" = c."{PORTFOLIO}"
        )
        SELECT * FROM projected_colossus
        UNION ALL BY NAME
        SELECT * FROM projected_predict
        '''
    )
    identity_columns = (
        HISTORY_TYPE,
        ACTIVITY,
        SIGNOFF_GROUP,
        CATEGORY,
        SUB_CATEGORY,
        RISK_TYPE,
        RISK_GREEK,
        UNDERLYING,
        PRODUCT,
        PORTFOLIO,
        HISTORY_MAPPING_STATUS,
    )
    identity_projection = ", ".join(f'"{column}"' for column in identity_columns)
    connection.execute(
        f"""
        CREATE TEMP TABLE _pl_identity AS
        SELECT row_number() OVER (ORDER BY {identity_projection})::INTEGER
                   AS identity_id,
               identity.*
        FROM (
            SELECT DISTINCT {identity_projection} FROM _pl_projection
        ) identity
        """
    )
    connection.execute(
        f'''
        CREATE TEMP TABLE _pl_fact AS
        SELECT p."{MARKET_DATE}", i.identity_id, p."{PL}"
        FROM _pl_projection p
        JOIN _pl_identity i USING ({identity_projection})
        ORDER BY i.identity_id, p."{MARKET_DATE}"
        '''
    )
    duplicate = connection.execute(
        f'''SELECT 1 FROM _pl_fact
            GROUP BY identity_id, "{MARKET_DATE}"
            HAVING count(*) > 1 LIMIT 1'''
    ).fetchone()
    if duplicate is not None:
        raise RiskArchiveValidationError(
            "projected P&L history contains duplicate daily hierarchy keys"
        )
    connection.execute(
        f'''
        CREATE VIEW _pl_history AS
        SELECT f."{MARKET_DATE}", {identity_projection}, f."{PL}"
        FROM _pl_fact f
        JOIN _pl_identity i USING (identity_id)
        '''
    )
    connection.execute("DROP VIEW _pl_projection")


def _open_days_database(
    days: tuple[CompletedArchiveDay, ...],
    *,
    include_pl: bool = False,
    temp_directory: Path | None = None,
) -> duckdb.DuckDBPyConnection:
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET enable_progress_bar = false")
        if include_pl:
            if temp_directory is None:  # pragma: no cover - internal invariant
                raise AssertionError("P&L history requires an explicit spill directory")
            connection.execute("SET memory_limit = ?", [_PL_HISTORY_MEMORY_LIMIT])
            connection.execute("SET threads = ?", [_PL_HISTORY_THREADS])
            connection.execute("SET preserve_insertion_order = false")
            connection.execute("SET temp_directory = ?", [str(temp_directory)])
        _create_archive_views(connection, days)
        if include_pl:
            _materialize_pl_history(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def open_history_database(root: str | Path) -> duckdb.DuckDBPyConnection:
    """Open validated archive views in a disposable in-memory DuckDB database."""

    return _open_days_database(list_completed_v4_archive_days(root))


class SQLPLHistoryRepository:
    """Thread-safe, generation-aware bounded queries over the virtual P&L view."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser()
        self._lock = RLock()
        self._days: tuple[CompletedArchiveDay, ...] | None = None
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None

    @property
    def root(self) -> Path:
        return self._root

    def clear(self) -> None:
        """Close only this process-local reconstructable query state."""

        with self._lock:
            self._close_connection()
            self._days = None

    def _close_connection(self) -> None:
        try:
            if self._connection is not None:
                self._connection.close()
        finally:
            self._connection = None
            if self._temporary_directory is not None:
                self._temporary_directory.cleanup()
                self._temporary_directory = None

    @staticmethod
    def _new_temporary_directory() -> tempfile.TemporaryDirectory[str]:
        temporary = tempfile.TemporaryDirectory(prefix="rebirth-pnl-duckdb-")
        path = Path(temporary.name).resolve()
        repository_root = Path(__file__).resolve().parents[1]
        if path == repository_root or repository_root in path.parents:
            temporary.cleanup()
            raise PLSendValidationError(
                "DuckDB spill storage must be outside the repository"
            )
        return temporary

    def _current_connection(self) -> duckdb.DuckDBPyConnection:
        days = list_completed_v4_archive_days(self._root)
        if self._connection is None or days is not self._days:
            self._close_connection()
            temporary = self._new_temporary_directory()
            try:
                self._connection = _open_days_database(
                    days,
                    include_pl=True,
                    temp_directory=Path(temporary.name),
                )
            except BaseException:
                temporary.cleanup()
                raise
            self._temporary_directory = temporary
            self._days = days
        return self._connection

    @staticmethod
    def _stats(
        connection: duckdb.DuckDBPyConnection,
        clause: str,
        parameters: Sequence[object],
    ) -> tuple[int, int, str | None, str | None, int, tuple[float | None, ...]]:
        row = connection.execute(
            f'''
            WITH filtered AS MATERIALIZED (
                SELECT h."{MARKET_DATE}", h."{HISTORY_TYPE}",
                       h."{HISTORY_MAPPING_STATUS}", h."{PL}"
                FROM _pl_history h WHERE {clause}
            ), bounds AS (
                SELECT max("{MARKET_DATE}") AS maximum_date FROM filtered
            )
            SELECT count(h."{MARKET_DATE}")::BIGINT,
                   count(DISTINCT h."{MARKET_DATE}")::BIGINT,
                   min(h."{MARKET_DATE}")::VARCHAR,
                   max(h."{MARKET_DATE}")::VARCHAR,
                   count(*) FILTER (
                       WHERE h."{HISTORY_MAPPING_STATUS}" = 'Unmapped'
                   )::BIGINT,
                   sum(h."{PL}") FILTER (
                       WHERE h."{MARKET_DATE}" = b.maximum_date
                         AND h."{HISTORY_TYPE}" = '{PREDICT_TYPE}'
                   ),
                   sum(h."{PL}") FILTER (
                       WHERE h."{MARKET_DATE}" >= date_trunc('month', b.maximum_date)
                         AND h."{HISTORY_TYPE}" = '{COLOSSUS_TYPE}'
                   ),
                   sum(h."{PL}") FILTER (
                       WHERE h."{MARKET_DATE}" >= date_trunc('month', b.maximum_date)
                         AND h."{HISTORY_TYPE}" = '{PREDICT_TYPE}'
                   ),
                   sum(h."{PL}") FILTER (
                       WHERE h."{MARKET_DATE}" >= date_trunc('year', b.maximum_date)
                         AND h."{HISTORY_TYPE}" = '{COLOSSUS_TYPE}'
                   ),
                   sum(h."{PL}") FILTER (
                       WHERE h."{MARKET_DATE}" >= date_trunc('year', b.maximum_date)
                         AND h."{HISTORY_TYPE}" = '{PREDICT_TYPE}'
                   )
            FROM bounds b LEFT JOIN filtered h ON TRUE
            GROUP BY b.maximum_date
            ''',
            list(parameters),
        ).fetchone()
        if row is None:  # pragma: no cover - aggregate always returns one row
            raise AssertionError("P&L history statistics query returned no row")
        return (
            int(row[0]),
            int(row[1]),
            row[2],
            row[3],
            int(row[4]),
            tuple(None if value is None else float(value) for value in row[5:]),
        )

    def hierarchy(
        self,
        *,
        open_paths: object = None,
        filters: Mapping[str, Sequence[object] | None] | None = None,
        exclude_selected: bool = False,
    ) -> PLHistoryHierarchyResult:
        """Return Total plus children of only the requested visible parents."""

        if not isinstance(exclude_selected, bool):
            raise TypeError("exclude_selected must be boolean")
        requested = ((), *_normalized_open_paths(open_paths))
        parents = tuple(
            path for path in requested if len(path) < len(HISTORY_IDENTITY_COLUMNS)
        )
        clause, filter_parameters = _filter_clause(
            filters,
            exclude_selected=exclude_selected,
        )
        try:
            with self._lock:
                connection = self._current_connection()
                row_count, date_count, minimum, maximum, unmapped, root_metrics = (
                    self._stats(connection, clause, filter_parameters)
                )
                if row_count == 0 or maximum is None:
                    return PLHistoryHierarchyResult(
                        _empty_summary(), 0, 0, None, None, 0
                    )
                parent_rows = [
                    (index, len(path), *path, *([None] * (6 - len(path))))
                    for index, path in enumerate(parents)
                ]
                placeholders = ", ".join(
                    "(?, ?, ?, ?, ?, ?, ?, ?)" for _row in parent_rows
                )
                parent_parameters = [value for row in parent_rows for value in row]
                label_case = (
                    "CASE p.depth "
                    + " ".join(
                        f'WHEN {depth} THEN h."{column}"'
                        for depth, column in enumerate(HISTORY_IDENTITY_COLUMNS)
                    )
                    + " END"
                )
                prefix = " AND ".join(
                    f'(p.depth <= {depth} OR h."{column}" = p.v{depth})'
                    for depth, column in enumerate(HISTORY_IDENTITY_COLUMNS)
                )
                as_of = pd.Timestamp(maximum)
                mtd_start = as_of.replace(day=1).date().isoformat()
                ytd_start = as_of.replace(month=1, day=1).date().isoformat()
                children = connection.execute(
                    f'''
                    WITH parents(id, depth, v0, v1, v2, v3, v4, v5) AS (
                        VALUES {placeholders}
                    )
                    SELECT p.id, p.depth, {label_case} AS label,
                           sum(h."{PL}") FILTER (
                               WHERE h."{MARKET_DATE}" = ?
                                 AND h."{HISTORY_TYPE}" = '{PREDICT_TYPE}'
                           ) AS daily_predict,
                           sum(h."{PL}") FILTER (
                               WHERE h."{MARKET_DATE}" BETWEEN ? AND ?
                                 AND h."{HISTORY_TYPE}" = '{COLOSSUS_TYPE}'
                           ) AS mtd_colossus,
                           sum(h."{PL}") FILTER (
                               WHERE h."{MARKET_DATE}" BETWEEN ? AND ?
                                 AND h."{HISTORY_TYPE}" = '{PREDICT_TYPE}'
                           ) AS mtd_predict,
                           sum(h."{PL}") FILTER (
                               WHERE h."{MARKET_DATE}" BETWEEN ? AND ?
                                 AND h."{HISTORY_TYPE}" = '{COLOSSUS_TYPE}'
                           ) AS ytd_colossus,
                           sum(h."{PL}") FILTER (
                               WHERE h."{MARKET_DATE}" BETWEEN ? AND ?
                                 AND h."{HISTORY_TYPE}" = '{PREDICT_TYPE}'
                           ) AS ytd_predict
                    FROM _pl_history h
                    JOIN parents p ON {prefix}
                    WHERE {clause}
                    GROUP BY p.id, p.depth, label
                    ''',
                    [
                        *parent_parameters,
                        maximum,
                        mtd_start,
                        maximum,
                        mtd_start,
                        maximum,
                        ytd_start,
                        maximum,
                        ytd_start,
                        maximum,
                        *filter_parameters,
                    ],
                ).fetchall()
        except (duckdb.Error, RiskArchiveValidationError, OSError) as exc:
            raise PLSendValidationError(f"Could not query P&L history: {exc}") from exc

        records: list[dict[str, object]] = [
            {
                PL_HISTORY_DEPTH: 0,
                PL_HISTORY_LEVEL: "Total",
                PL_HISTORY_LABEL: "TOTAL",
                PL_HISTORY_PATH: (),
                PL_HISTORY_LEAF: False,
                PL_HISTORY_DAILY_PREDICT: root_metrics[0],
                PL_HISTORY_MTD_COLOSSUS: root_metrics[1],
                PL_HISTORY_MTD_PREDICT: root_metrics[2],
                PL_HISTORY_YTD_COLOSSUS: root_metrics[3],
                PL_HISTORY_YTD_PREDICT: root_metrics[4],
            }
        ]
        for parent_id, parent_depth, label, *metrics in children:
            parent = parents[int(parent_id)]
            path = (*parent, str(label))
            depth = int(parent_depth) + 1
            records.append(
                {
                    PL_HISTORY_DEPTH: depth,
                    PL_HISTORY_LEVEL: HISTORY_IDENTITY_COLUMNS[depth - 1],
                    PL_HISTORY_LABEL: str(label),
                    PL_HISTORY_PATH: path,
                    PL_HISTORY_LEAF: depth == len(HISTORY_IDENTITY_COLUMNS),
                    **dict(
                        zip(
                            PL_HISTORY_SUMMARY_COLUMNS[5:],
                            (
                                None if value is None else float(value)
                                for value in metrics
                            ),
                            strict=True,
                        )
                    ),
                }
            )
        if len(records) > PL_HISTORY_MAX_VISIBLE_NODES:
            raise PLSendValidationError(
                f"Visible P&L history exceeds {PL_HISTORY_MAX_VISIBLE_NODES:,} nodes"
            )
        return PLHistoryHierarchyResult(
            pd.DataFrame.from_records(
                records, columns=list(PL_HISTORY_SUMMARY_COLUMNS)
            ),
            row_count,
            date_count,
            minimum,
            maximum,
            unmapped,
        )

    def series(
        self,
        *,
        path: Sequence[object] = (),
        history_types: Sequence[str] = _PL_TYPES,
        preset: str = "all",
        start_date: object = None,
        end_date: object = None,
        filters: Mapping[str, Sequence[object] | None] | None = None,
        exclude_selected: bool = False,
    ) -> PLHistorySeriesResult:
        """Return at most one observed point per date and requested P&L type."""

        selected_path = _resolved_path(path)
        selected_types = tuple(
            history_type for history_type in _PL_TYPES if history_type in history_types
        )
        selected_preset = str(preset).strip().casefold()
        if selected_preset not in _SERIES_PRESETS:
            selected_preset = "all"
        clause, parameters = _filter_clause(
            filters,
            exclude_selected=exclude_selected,
        )
        try:
            with self._lock:
                connection = self._current_connection()
                row_count, _date_count, minimum, maximum, _unmapped, _metrics = (
                    self._stats(connection, clause, parameters)
                )
                if row_count == 0 or minimum is None or maximum is None:
                    return PLHistorySeriesResult(
                        _empty_series(), None, None, None, None
                    )
                minimum_value = pd.Timestamp(minimum)
                maximum_value = pd.Timestamp(maximum)
                if selected_preset == "wtd":
                    start = maximum_value - timedelta(days=maximum_value.weekday())
                    end = maximum_value
                elif selected_preset == "mtd":
                    start, end = maximum_value.replace(day=1), maximum_value
                elif selected_preset == "ytd":
                    start, end = maximum_value.replace(month=1, day=1), maximum_value
                elif selected_preset == "custom":
                    start = pd.Timestamp(start_date) if start_date else minimum_value
                    end = pd.Timestamp(end_date) if end_date else maximum_value
                    start = min(max(start.normalize(), minimum_value), maximum_value)
                    end = min(max(end.normalize(), minimum_value), maximum_value)
                    if start > end:
                        start, end = end, start
                else:
                    selected_preset = "all"
                    start, end = minimum_value, maximum_value
                resolved_start = start.date().isoformat()
                resolved_end = end.date().isoformat()
                path_clauses = [
                    f'h."{column}" = ?'
                    for column in HISTORY_IDENTITY_COLUMNS[: len(selected_path)]
                ]
                type_placeholders = ", ".join("?" for _value in selected_types)
                if not selected_types:
                    return PLHistorySeriesResult(
                        _empty_series(),
                        minimum,
                        maximum,
                        resolved_start,
                        resolved_end,
                    )
                path_sql = " AND ".join(path_clauses) or "TRUE"
                frame = connection.execute(
                    f'''
                    SELECT h."{MARKET_DATE}", h."{HISTORY_TYPE}", sum(h."{PL}") AS "{PL}"
                    FROM _pl_history h
                    WHERE {clause}
                      AND {path_sql}
                      AND h."{HISTORY_TYPE}" IN ({type_placeholders})
                      AND h."{MARKET_DATE}" BETWEEN ? AND ?
                    GROUP BY h."{MARKET_DATE}", h."{HISTORY_TYPE}"
                    ORDER BY h."{MARKET_DATE}",
                             CASE h."{HISTORY_TYPE}"
                               WHEN '{COLOSSUS_TYPE}' THEN 0 ELSE 1 END
                    ''',
                    [
                        *parameters,
                        *selected_path,
                        *selected_types,
                        resolved_start,
                        resolved_end,
                    ],
                ).df()
        except (duckdb.Error, RiskArchiveValidationError, OSError, ValueError) as exc:
            raise PLSendValidationError(f"Could not query P&L history: {exc}") from exc
        if len(frame) > PL_HISTORY_MAX_SERIES_ROWS:
            raise PLSendValidationError(
                f"P&L history series exceeds {PL_HISTORY_MAX_SERIES_ROWS:,} rows"
            )
        frame.columns = [MARKET_DATE, HISTORY_TYPE, PL]
        if not frame.empty:
            frame[MARKET_DATE] = frame[MARKET_DATE].astype(str)
            frame[HISTORY_TYPE] = frame[HISTORY_TYPE].astype(str)
            frame[PL] = pd.to_numeric(frame[PL], errors="raise").astype(float)
        return PLHistorySeriesResult(
            frame.reset_index(drop=True),
            minimum,
            maximum,
            resolved_start,
            resolved_end,
        )


__all__ = [
    "PL_HISTORY_DAILY_PREDICT",
    "PL_HISTORY_DEPTH",
    "PL_HISTORY_LABEL",
    "PL_HISTORY_LEAF",
    "PL_HISTORY_LEVEL",
    "PL_HISTORY_MAX_SERIES_ROWS",
    "PL_HISTORY_MTD_COLOSSUS",
    "PL_HISTORY_MTD_PREDICT",
    "PL_HISTORY_PATH",
    "PL_HISTORY_SUMMARY_COLUMNS",
    "PL_HISTORY_YTD_COLOSSUS",
    "PL_HISTORY_YTD_PREDICT",
    "PLHistoryHierarchyResult",
    "PLHistorySeriesResult",
    "SQLPLHistoryRepository",
    "open_history_database",
]
