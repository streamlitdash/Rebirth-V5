"""Lazy in-memory DuckDB views and bounded P&L history queries.

Parquet leaves remain the sole persisted archive.  Merely constructing a
repository performs no filesystem or DuckDB work; explicit SQL access or a P&L
query validates the completed schema-v4 leaves and opens ``:memory:`` only.
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from threading import RLock

import duckdb
import pandas as pd

from rebirth.domain.pnl import (
    ACTIVITY,
    CATEGORY,
    COLOSSUS_TYPE,
    HISTORY_IDENTITY_COLUMNS,
    HISTORY_MAPPING_STATUS,
    HISTORY_TYPE,
    MARKET_DATE,
    PL,
    PL_HISTORY_COLUMNS,
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
from .archive_contracts import (
    COLOSSUS_COLUMNS,
    MARKET_ARCHIVE_COLUMNS,
    REVISION,
    RISK_DATE,
    RISK_PROJECTION_COLUMNS,
    SNAPSHOT_DATE,
    CompletedArchiveDay,
    RiskArchiveValidationError,
)
from .archive_io import (
    list_completed_v4_archive_days,
    list_queryable_v4_archive_days,
)
from rebirth.domain.stock import STOCK_COLUMNS
from rebirth.app.observability import perf_span


LOGGER = logging.getLogger(__name__)
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
PL_HISTORY_MAX_RAW_ROWS = 500
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


@dataclass(frozen=True)
class PLHistoryRowsResult:
    """Bounded raw rows plus totals for the complete selected scope."""

    rows: pd.DataFrame
    row_count: int
    pl_total: float | None
    resolved_start: str | None
    resolved_end: str | None


def _empty_series() -> pd.DataFrame:
    return pd.DataFrame(columns=[MARKET_DATE, HISTORY_TYPE, PL])


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=list(PL_HISTORY_SUMMARY_COLUMNS))


def _empty_raw_rows() -> pd.DataFrame:
    return pd.DataFrame(columns=list(PL_HISTORY_COLUMNS))


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


def _resolved_date_range(
    minimum: object,
    maximum: object,
    *,
    preset: object,
    start_date: object = None,
    end_date: object = None,
) -> tuple[str, str, str]:
    """Resolve one bounded range against the filtered archive dates."""

    minimum_value = pd.Timestamp(minimum).normalize()
    maximum_value = pd.Timestamp(maximum).normalize()
    selected = str(preset).strip().casefold()
    if selected == "wtd":
        start = maximum_value - timedelta(days=maximum_value.weekday())
        end = maximum_value
    elif selected == "mtd":
        start, end = maximum_value.replace(day=1), maximum_value
    elif selected == "ytd":
        start, end = maximum_value.replace(month=1, day=1), maximum_value
    elif selected == "custom":
        start = pd.Timestamp(start_date).normalize() if start_date else minimum_value
        end = pd.Timestamp(end_date).normalize() if end_date else maximum_value
        start = min(max(start, minimum_value), maximum_value)
        end = min(max(end, minimum_value), maximum_value)
        if start > end:
            start, end = end, start
    else:
        selected = "all"
        start, end = minimum_value, maximum_value
    return selected, start.date().isoformat(), end.date().isoformat()


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


def _initial_hierarchy(
    connection: duckdb.DuckDBPyConnection,
    clause: str,
    parameters: Sequence[object],
) -> PLHistoryHierarchyResult:
    """Build Total and first-level rows with one projected archive scan."""

    first_level = HISTORY_IDENTITY_COLUMNS[0]
    if clause == "TRUE" and not parameters:
        daily_ctes = f'''
        portfolio_authority AS (
            SELECT "{SNAPSHOT_DATE}", "{PORTFOLIO}",
                   CASE WHEN count(DISTINCT struct_pack(
                       signoff := "{SIGNOFF_GROUP}", product := "{PRODUCT}"
                   )) = 1 THEN min("{SIGNOFF_GROUP}") ELSE 'Unmapped' END
                       AS label,
                   CASE WHEN count(DISTINCT struct_pack(
                       signoff := "{SIGNOFF_GROUP}", product := "{PRODUCT}"
                   )) = 1 THEN 'Mapped' ELSE 'Unmapped' END AS mapping_status
            FROM risk_history
            GROUP BY "{SNAPSHOT_DATE}", "{PORTFOLIO}"
        ), predict_identity AS (
            SELECT "{SNAPSHOT_DATE}" AS market_date,
                   "{SIGNOFF_GROUP}" AS label,
                   sum("{PL}") AS pl
            FROM risk_history
            GROUP BY "{SNAPSHOT_DATE}", "{SIGNOFF_GROUP}", "{RISK_TYPE}",
                     "{RISK_GREEK}", "{UNDERLYING}", "{PRODUCT}", "{PORTFOLIO}"
            HAVING count("{PL}") = count(*)
        ), daily AS (
            SELECT label, market_date, '{PREDICT_TYPE}' AS history_type,
                   'Mapped' AS mapping_status, count(*)::BIGINT AS source_rows,
                   sum(pl) AS pl
            FROM predict_identity
            GROUP BY ALL
            UNION ALL
            SELECT coalesce(a.label, 'Unmapped') AS label,
                   c."{SNAPSHOT_DATE}" AS market_date,
                   '{COLOSSUS_TYPE}' AS history_type,
                   coalesce(a.mapping_status, 'Unmapped') AS mapping_status,
                   count(*)::BIGINT AS source_rows, sum(c."{PL}") AS pl
            FROM colossus_history c
            LEFT JOIN portfolio_authority a
              ON a."{SNAPSHOT_DATE}" = c."{SNAPSHOT_DATE}"
             AND a."{PORTFOLIO}" = c."{PORTFOLIO}"
            GROUP BY ALL
        )'''
    else:
        daily_ctes = f'''
        daily AS (
            SELECT h."{first_level}" AS label,
                   h."{MARKET_DATE}" AS market_date,
                   h."{HISTORY_TYPE}" AS history_type,
                   h."{HISTORY_MAPPING_STATUS}" AS mapping_status,
                   count(*)::BIGINT AS source_rows,
                   sum(h."{PL}") AS pl
            FROM _pl_history h
            WHERE {clause}
            GROUP BY ALL
        )'''
    rows = connection.execute(
        f"""
        WITH {daily_ctes}, dated AS (
            SELECT *, max(market_date) OVER () AS maximum_date
            FROM daily
        )
        SELECT grouping(label)::INTEGER AS total_row,
               coalesce(label, 'TOTAL') AS label,
               sum(source_rows)::BIGINT AS row_count,
               count(DISTINCT market_date)::BIGINT AS date_count,
               min(market_date)::VARCHAR AS minimum_date,
               max(market_date)::VARCHAR AS maximum_date,
               coalesce(sum(source_rows) FILTER (
                   WHERE mapping_status = 'Unmapped'
               ), 0)::BIGINT AS unmapped_rows,
               sum(pl) FILTER (
                   WHERE market_date = maximum_date
                     AND history_type = '{PREDICT_TYPE}'
               ) AS daily_predict,
               sum(pl) FILTER (
                   WHERE market_date >= date_trunc('month', maximum_date)
                     AND history_type = '{COLOSSUS_TYPE}'
               ) AS mtd_colossus,
               sum(pl) FILTER (
                   WHERE market_date >= date_trunc('month', maximum_date)
                     AND history_type = '{PREDICT_TYPE}'
               ) AS mtd_predict,
               sum(pl) FILTER (
                   WHERE market_date >= date_trunc('year', maximum_date)
                     AND history_type = '{COLOSSUS_TYPE}'
               ) AS ytd_colossus,
               sum(pl) FILTER (
                   WHERE market_date >= date_trunc('year', maximum_date)
                     AND history_type = '{PREDICT_TYPE}'
               ) AS ytd_predict
        FROM dated
        GROUP BY GROUPING SETS ((), (label)), maximum_date
        ORDER BY total_row DESC, label
        """,
        list(parameters),
    ).fetchall()
    if not rows:
        return PLHistoryHierarchyResult(_empty_summary(), 0, 0, None, None, 0)
    root = rows[0]
    if int(root[0]) != 1 or root[5] is None:
        return PLHistoryHierarchyResult(_empty_summary(), 0, 0, None, None, 0)

    def metrics(row: Sequence[object]) -> dict[str, float | None]:
        return dict(
            zip(
                PL_HISTORY_SUMMARY_COLUMNS[5:],
                (None if value is None else float(value) for value in row[7:]),
                strict=True,
            )
        )

    records: list[dict[str, object]] = [
        {
            PL_HISTORY_DEPTH: 0,
            PL_HISTORY_LEVEL: "Total",
            PL_HISTORY_LABEL: "TOTAL",
            PL_HISTORY_PATH: (),
            PL_HISTORY_LEAF: False,
            **metrics(root),
        }
    ]
    for child in rows[1:]:
        label = str(child[1])
        records.append(
            {
                PL_HISTORY_DEPTH: 1,
                PL_HISTORY_LEVEL: first_level,
                PL_HISTORY_LABEL: label,
                PL_HISTORY_PATH: (label,),
                PL_HISTORY_LEAF: len(HISTORY_IDENTITY_COLUMNS) == 1,
                **metrics(child),
            }
        )
    return PLHistoryHierarchyResult(
        pd.DataFrame.from_records(records, columns=list(PL_HISTORY_SUMMARY_COLUMNS)),
        int(root[2]),
        int(root[3]),
        str(root[4]),
        str(root[5]),
        int(root[6]),
    )


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
    *,
    validate_relation_values: bool = True,
    domains: frozenset[str] | None = None,
) -> None:
    selected_domains = domains or frozenset({"risk", "market", "colossus", "stock"})
    unknown_domains = selected_domains - {"risk", "market", "colossus", "stock"}
    if unknown_domains:
        raise ValueError(f"Unknown archive domains: {sorted(unknown_domains)}")
    if "risk" not in selected_domains:
        raise ValueError("Archive SQL access requires the Risk domain")
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
    if "colossus" in selected_domains:
        connection.from_parquet(
            colossus_paths, filename=True, union_by_name=False
        ).create_view("_colossus_files")
    if "market" in selected_domains:
        connection.from_parquet(
            market_paths, filename=True, union_by_name=False
        ).create_view("_market_files")
    if "stock" in selected_domains and stock_paths:
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
    if "market" in selected_domains:
        connection.execute(
            f'''CREATE VIEW market_history AS
                SELECT f.snapshot_date AS "{SNAPSHOT_DATE}",
                       f.revision AS "{REVISION}",
                       m.* EXCLUDE(filename)
                FROM _market_files m
                JOIN _archive_files f ON m.filename = f.market_path'''
        )
    else:
        _empty_view(
            connection,
            "market_history",
            (
                (SNAPSHOT_DATE, "DATE"),
                (REVISION, "BIGINT"),
                *((column, "VARCHAR") for column in MARKET_ARCHIVE_COLUMNS),
            ),
        )
    if "colossus" in selected_domains:
        connection.execute(
            f'''CREATE VIEW colossus_history AS
                SELECT f.snapshot_date AS "{SNAPSHOT_DATE}",
                       f.revision AS "{REVISION}",
                       c.* EXCLUDE(filename)
                FROM _colossus_files c
                JOIN _archive_files f ON c.filename = f.colossus_path'''
        )
    else:
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
    if "stock" in selected_domains and stock_paths:
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

    if not validate_relation_values:
        return
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
    if "market" in selected_domains:
        wrong_market_date = connection.execute(
            f'''SELECT 1 FROM market_history
                WHERE CAST("{MARKET_DATE}" AS DATE) <> "{SNAPSHOT_DATE}"
                LIMIT 1'''
        ).fetchone()
        if wrong_market_date is not None:
            raise RiskArchiveValidationError(
                "schema-v4 Market Date values do not match their manifest dates"
            )


def _create_pl_archive_views(
    connection: duckdb.DuckDBPyConnection,
    days: tuple[CompletedArchiveDay, ...],
) -> None:
    """Register only the dated Risk and Colossus columns P&L consumes."""

    if not days:
        _create_empty_archive_views(connection)
        return
    risk_paths = [str(day.risk_path.resolve()) for day in days]
    colossus_paths = [str(day.colossus_path.resolve()) for day in days]
    connection.from_parquet(
        risk_paths,
        filename=True,
        union_by_name=True,
    ).create_view("_risk_files")
    connection.from_parquet(
        colossus_paths,
        filename=True,
        union_by_name=False,
    ).create_view("_colossus_files")
    connection.execute(
        "CREATE TABLE _pl_archive_files ("
        "snapshot_date DATE, risk_path VARCHAR, colossus_path VARCHAR)"
    )
    connection.executemany(
        "INSERT INTO _pl_archive_files VALUES (?, ?, ?)",
        [
            (
                day.snapshot_date,
                str(day.risk_path.resolve()),
                str(day.colossus_path.resolve()),
            )
            for day in days
        ],
    )
    connection.execute(
        f'''CREATE VIEW risk_history AS
            SELECT f.snapshot_date AS "{SNAPSHOT_DATE}",
                   r.* EXCLUDE(filename)
            FROM _risk_files r
            JOIN _pl_archive_files f ON r.filename = f.risk_path'''
    )
    connection.execute(
        f'''CREATE VIEW colossus_history AS
            SELECT f.snapshot_date AS "{SNAPSHOT_DATE}",
                   c.* EXCLUDE(filename)
            FROM _colossus_files c
            JOIN _pl_archive_files f ON c.filename = f.colossus_path'''
    )


def _create_pl_history_view(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        f'''
        CREATE VIEW _pl_history AS
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


def _open_days_database(
    days: tuple[CompletedArchiveDay, ...],
    *,
    include_pl: bool = False,
    temp_directory: Path | None = None,
    validate_relation_values: bool = True,
    domains: frozenset[str] | None = None,
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
        if include_pl:
            _create_pl_archive_views(connection, days)
            _create_pl_history_view(connection)
        else:
            _create_archive_views(
                connection,
                days,
                validate_relation_values=validate_relation_values,
                domains=domains,
            )
    except BaseException:
        connection.close()
        raise
    return connection


def open_history_database(root: str | Path) -> duckdb.DuckDBPyConnection:
    """Open validated archive views in a disposable in-memory DuckDB database."""

    return _open_days_database(list_completed_v4_archive_days(root))


def open_history_query_database(root: str | Path) -> duckdb.DuckDBPyConnection:
    """Open predicate-ready views after generation-level file validation.

    Completion manifests, schemas, row counts, and Parquet metadata are still
    validated once per generation. Whole-file digest checks remain in publish
    and full inspection gates; the two whole-archive relation scans used by the
    broad inspection API are also deferred because this path reads only exact
    projected rows.
    """

    days = list_queryable_v4_archive_days(root)
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("SET enable_progress_bar = false")
        if not days:
            _create_empty_archive_views(connection)
            return connection
        risk_paths = [str(day.risk_path.resolve()) for day in days]
        market_paths = [str(day.market_path.resolve()) for day in days]
        connection.from_parquet(
            risk_paths,
            filename=True,
            union_by_name=True,
        ).create_view("_risk_files")
        connection.from_parquet(
            market_paths,
            filename=True,
            union_by_name=False,
        ).create_view("_market_files")
        connection.execute(
            "CREATE TABLE _history_files ("
            "snapshot_date DATE, revision BIGINT, risk_path VARCHAR, "
            "market_path VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO _history_files VALUES (?, ?, ?, ?)",
            [
                (
                    day.snapshot_date,
                    day.revision,
                    str(day.risk_path.resolve()),
                    str(day.market_path.resolve()),
                )
                for day in days
            ],
        )
        connection.execute(
            "CREATE TABLE _history_risk_dates ("
            "snapshot_date DATE, source_type VARCHAR, risk_date DATE)"
        )
        connection.executemany(
            "INSERT INTO _history_risk_dates VALUES (?, ?, ?)",
            [
                (day.snapshot_date, source_type, risk_date)
                for day in days
                for source_type, risk_date in day.risk_dates.items()
            ],
        )
        connection.execute(
            f'''CREATE VIEW archive_days AS
                SELECT snapshot_date AS "{SNAPSHOT_DATE}",
                       revision AS "{REVISION}"
                FROM _history_files'''
        )
        connection.execute(
            f'''CREATE VIEW risk_history AS
                SELECT f.snapshot_date AS "{SNAPSHOT_DATE}",
                       f.revision AS "{REVISION}",
                       d.risk_date AS "{RISK_DATE}",
                       r.* EXCLUDE(filename)
                FROM _risk_files r
                JOIN _history_files f ON r.filename = f.risk_path
                LEFT JOIN _history_risk_dates d
                  ON d.snapshot_date = f.snapshot_date
                 AND d.source_type = r."Source Type"'''
        )
        connection.execute(
            f'''CREATE VIEW market_history AS
                SELECT f.snapshot_date AS "{SNAPSHOT_DATE}",
                       f.revision AS "{REVISION}",
                       m.* EXCLUDE(filename)
                FROM _market_files m
                JOIN _history_files f ON m.filename = f.market_path'''
        )
    except BaseException:
        connection.close()
        raise
    return connection


class SQLPLHistoryRepository:
    """Thread-safe, generation-aware bounded queries over the virtual P&L view."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser()
        self._lock = RLock()
        self._days: tuple[CompletedArchiveDay, ...] | None = None
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._temporary_directory: tempfile.TemporaryDirectory[str] | None = None
        self._stats_cache: dict[
            tuple[str, tuple[object, ...]],
            tuple[int, int, str | None, str | None, int, tuple[float | None, ...]],
        ] = {}

    @property
    def root(self) -> Path:
        return self._root

    def clear(self) -> None:
        """Close only this process-local reconstructable query state."""

        with self._lock:
            self._close_connection()
            self._days = None

    def _close_connection(self) -> None:
        self._stats_cache.clear()
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
        days = list_queryable_v4_archive_days(self._root)
        if self._connection is None or days is not self._days:
            self._close_connection()
            temporary = self._new_temporary_directory()
            try:
                with perf_span(
                    LOGGER,
                    "pnl.history.open",
                    budget_ms=3_000,
                    dates=len(days),
                ):
                    self._connection = _open_days_database(
                        days,
                        include_pl=True,
                        temp_directory=Path(temporary.name),
                        validate_relation_values=False,
                        domains=frozenset({"risk", "colossus"}),
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

    def _cached_stats(
        self,
        connection: duckdb.DuckDBPyConnection,
        clause: str,
        parameters: Sequence[object],
    ) -> tuple[int, int, str | None, str | None, int, tuple[float | None, ...]]:
        key = (clause, tuple(parameters))
        cached = self._stats_cache.get(key)
        if cached is None:
            cached = self._stats(connection, clause, parameters)
            self._stats_cache[key] = cached
        return cached

    def _remember_hierarchy_stats(
        self,
        clause: str,
        parameters: Sequence[object],
        result: PLHistoryHierarchyResult,
    ) -> None:
        if result.summary.empty:
            metrics = (None,) * 5
        else:
            root = result.summary.iloc[0]
            metrics = tuple(
                None if pd.isna(root[column]) else float(root[column])
                for column in PL_HISTORY_SUMMARY_COLUMNS[5:]
            )
        self._stats_cache[(clause, tuple(parameters))] = (
            result.row_count,
            result.date_count,
            result.minimum_date,
            result.maximum_date,
            result.unmapped_rows,
            metrics,
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
        if parents == ((),):
            try:
                with (
                    self._lock,
                    perf_span(
                        LOGGER,
                        "pnl.history.hierarchy",
                        budget_ms=3_000,
                        kind="initial",
                    ) as timing,
                ):
                    result = _initial_hierarchy(
                        self._current_connection(),
                        clause,
                        filter_parameters,
                    )
                    self._remember_hierarchy_stats(
                        clause,
                        filter_parameters,
                        result,
                    )
                    timing.update(
                        rows=result.row_count,
                        cells=len(result.summary),
                    )
                    return result
            except (duckdb.Error, RiskArchiveValidationError, OSError) as exc:
                raise PLSendValidationError(
                    f"Could not query P&L history: {exc}"
                ) from exc
        try:
            with (
                self._lock,
                perf_span(
                    LOGGER,
                    "pnl.history.hierarchy",
                    budget_ms=3_000,
                    kind="expanded",
                ) as timing,
            ):
                connection = self._current_connection()
                row_count, date_count, minimum, maximum, unmapped, root_metrics = (
                    self._cached_stats(connection, clause, filter_parameters)
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
                timing.update(rows=row_count, cells=len(children) + 1)
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
            with (
                self._lock,
                perf_span(
                    LOGGER,
                    "pnl.history.series",
                    budget_ms=3_000,
                    kind=selected_preset,
                ) as timing,
            ):
                connection = self._current_connection()
                row_count, _date_count, minimum, maximum, _unmapped, _metrics = (
                    self._cached_stats(connection, clause, parameters)
                )
                if row_count == 0 or minimum is None or maximum is None:
                    return PLHistorySeriesResult(
                        _empty_series(), None, None, None, None
                    )
                selected_preset, resolved_start, resolved_end = _resolved_date_range(
                    minimum,
                    maximum,
                    preset=selected_preset,
                    start_date=start_date,
                    end_date=end_date,
                )
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
                timing.update(rows=len(frame))
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

    def raw_rows(
        self,
        *,
        path: Sequence[object] = (),
        history_types: Sequence[str] = _PL_TYPES,
        preset: str = "all",
        start_date: object = None,
        end_date: object = None,
        filters: Mapping[str, Sequence[object] | None] | None = None,
        exclude_selected: bool = False,
        limit: int = PL_HISTORY_MAX_RAW_ROWS,
    ) -> PLHistoryRowsResult:
        """Return bounded source rows and totals for the selected chart scope."""

        if isinstance(limit, bool) or not isinstance(limit, int):
            raise PLSendValidationError("P&L raw-row limit must be an integer")
        if not 1 <= limit <= PL_HISTORY_MAX_RAW_ROWS:
            raise PLSendValidationError(
                f"P&L raw-row limit must be between 1 and {PL_HISTORY_MAX_RAW_ROWS}"
            )
        selected_path = _resolved_path(path)
        selected_types = tuple(
            history_type for history_type in _PL_TYPES if history_type in history_types
        )
        clause, parameters = _filter_clause(
            filters,
            exclude_selected=exclude_selected,
        )
        try:
            with (
                self._lock,
                perf_span(
                    LOGGER,
                    "pnl.history.raw_rows",
                    budget_ms=3_000,
                    kind=str(preset).strip().casefold(),
                ) as timing,
            ):
                connection = self._current_connection()
                row_count, _date_count, minimum, maximum, _unmapped, _metrics = (
                    self._cached_stats(connection, clause, parameters)
                )
                if row_count == 0 or minimum is None or maximum is None:
                    return PLHistoryRowsResult(_empty_raw_rows(), 0, None, None, None)
                _selected_preset, resolved_start, resolved_end = _resolved_date_range(
                    minimum,
                    maximum,
                    preset=preset,
                    start_date=start_date,
                    end_date=end_date,
                )
                if not selected_types:
                    return PLHistoryRowsResult(
                        _empty_raw_rows(),
                        0,
                        None,
                        resolved_start,
                        resolved_end,
                    )
                path_clauses = [
                    f'h."{column}" = ?'
                    for column in HISTORY_IDENTITY_COLUMNS[: len(selected_path)]
                ]
                path_sql = " AND ".join(path_clauses) or "TRUE"
                type_placeholders = ", ".join("?" for _value in selected_types)
                scope_parameters = [
                    *parameters,
                    *selected_path,
                    *selected_types,
                    resolved_start,
                    resolved_end,
                ]
                scope_sql = f'''{clause}
                      AND {path_sql}
                      AND h."{HISTORY_TYPE}" IN ({type_placeholders})
                      AND h."{MARKET_DATE}" BETWEEN ? AND ?'''
                projection = ", ".join(f'h."{column}"' for column in PL_HISTORY_COLUMNS)
                frame = connection.execute(
                    f'''SELECT {projection},
                               count(*) OVER ()::BIGINT AS _scope_row_count,
                               sum(h."{PL}") OVER () AS _scope_pl_total
                        FROM _pl_history h
                        WHERE {scope_sql}
                        ORDER BY h."{MARKET_DATE}" DESC,
                                 CASE h."{HISTORY_TYPE}"
                                   WHEN '{COLOSSUS_TYPE}' THEN 0 ELSE 1 END,
                                 h."{SIGNOFF_GROUP}", h."{RISK_TYPE}",
                                 h."{RISK_GREEK}", h."{UNDERLYING}",
                                 h."{PRODUCT}", h."{PORTFOLIO}"
                        LIMIT ?''',
                    [*scope_parameters, limit],
                ).df()
                timing.update(rows=len(frame))
        except (duckdb.Error, RiskArchiveValidationError, OSError, ValueError) as exc:
            raise PLSendValidationError(
                f"Could not query P&L raw history: {exc}"
            ) from exc
        if frame.empty:
            count, total = 0, None
        else:
            count = int(frame["_scope_row_count"].iloc[0])
            total = frame["_scope_pl_total"].iloc[0]
            frame = frame.drop(columns=["_scope_row_count", "_scope_pl_total"])
        frame.columns = list(PL_HISTORY_COLUMNS)
        if not frame.empty:
            frame[MARKET_DATE] = frame[MARKET_DATE].astype(str)
            for column in PL_HISTORY_COLUMNS[1:-1]:
                frame[column] = frame[column].astype(str)
            frame[PL] = pd.to_numeric(frame[PL], errors="raise").astype(float)
        return PLHistoryRowsResult(
            frame.reset_index(drop=True),
            int(count),
            None if total is None else float(total),
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
    "PL_HISTORY_MAX_RAW_ROWS",
    "PL_HISTORY_MTD_COLOSSUS",
    "PL_HISTORY_MTD_PREDICT",
    "PL_HISTORY_PATH",
    "PL_HISTORY_SUMMARY_COLUMNS",
    "PL_HISTORY_YTD_COLOSSUS",
    "PL_HISTORY_YTD_PREDICT",
    "PLHistoryHierarchyResult",
    "PLHistoryRowsResult",
    "PLHistorySeriesResult",
    "SQLPLHistoryRepository",
    "open_history_database",
    "open_history_query_database",
]
