"""Lazy generation-scoped SQL access for Risk and Market history.

The Parquet archive remains authoritative.  This module owns only a disposable
in-process DuckDB connection: it is opened after a Data-page interaction,
reused while the archive generation is unchanged, and discarded on reset.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path
from threading import RLock

import duckdb
import pandas as pd

from .s07_sql import open_history_query_database
from rebirth.domain.s10_search import (
    REPORTED_UNDERLYING,
    RISK_GREEK,
    RISK_TYPE,
    SOURCE_TYPE,
    UNDERLYING,
)
from .s02_contracts import REVISION, RISK_DATE, SNAPSHOT_DATE
from rebirth.domain.s08_pnl import MARKET_DATE
from rebirth.app.s03_logging import perf_span


LOGGER = logging.getLogger(__name__)
_QUERY_BUDGET_MS = 2_000.0


def _quoted(column: str) -> str:
    """Quote one internally allowlisted identifier."""

    return f'"{column.replace(chr(34), chr(34) * 2)}"'


class ArchiveSQLStore:
    """Thread-safe virtual views over one validated immutable generation."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser()
        self._lock = RLock()
        self._generation: str | None = None
        self._connection: duckdb.DuckDBPyConnection | None = None
        self._catalog_generation: str | None = None
        self._risk_catalog: pd.DataFrame | None = None
        self._market_catalog: pd.DataFrame | None = None

    def clear(self) -> None:
        """Drop only reconstructable process-local state."""

        with self._lock:
            if self._connection is not None:
                self._connection.close()
            self._connection = None
            self._generation = None
            self._catalog_generation = None
            self._risk_catalog = None
            self._market_catalog = None

    def _current(self, generation: str) -> duckdb.DuckDBPyConnection:
        if self._connection is not None and self._generation == generation:
            return self._connection
        self.clear()
        with perf_span(
            LOGGER,
            "history.archive.open",
            budget_ms=_QUERY_BUDGET_MS,
            operation="validate_generation",
        ):
            connection = open_history_query_database(self._root)
        self._connection = connection
        self._generation = generation
        return connection

    @staticmethod
    def _has_days(connection: duckdb.DuckDBPyConnection) -> bool:
        return (
            connection.execute("SELECT 1 FROM archive_days LIMIT 1").fetchone()
            is not None
        )

    def catalog_frames(self, generation: str) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Return tiny distinct identity frames, cached once per generation."""

        with self._lock:
            if (
                self._catalog_generation == generation
                and self._risk_catalog is not None
                and self._market_catalog is not None
            ):
                return (
                    self._risk_catalog.copy(deep=True),
                    self._market_catalog.copy(deep=True),
                )
            connection = self._current(generation)
            if not self._has_days(connection):
                risk = pd.DataFrame(
                    columns=[
                        SOURCE_TYPE,
                        RISK_TYPE,
                        RISK_GREEK,
                        REPORTED_UNDERLYING,
                        UNDERLYING,
                        SNAPSHOT_DATE,
                        REVISION,
                    ]
                )
                market = pd.DataFrame(
                    columns=[
                        SOURCE_TYPE,
                        RISK_TYPE,
                        RISK_GREEK,
                        UNDERLYING,
                        SNAPSHOT_DATE,
                        REVISION,
                    ]
                )
            else:
                with perf_span(
                    LOGGER,
                    "history.catalog.query",
                    budget_ms=_QUERY_BUDGET_MS,
                    operation="distinct_identities",
                ) as metrics:
                    risk = connection.execute(
                        f"""
                        SELECT {_quoted(SOURCE_TYPE)}, {_quoted(RISK_TYPE)},
                               {_quoted(RISK_GREEK)}, {_quoted(REPORTED_UNDERLYING)},
                               {_quoted(UNDERLYING)},
                               max({_quoted(SNAPSHOT_DATE)}) AS {_quoted(SNAPSHOT_DATE)},
                               arg_max({_quoted(REVISION)}, {_quoted(SNAPSHOT_DATE)})
                                   AS {_quoted(REVISION)}
                        FROM risk_history
                        GROUP BY {_quoted(SOURCE_TYPE)}, {_quoted(RISK_TYPE)},
                                 {_quoted(RISK_GREEK)}, {_quoted(REPORTED_UNDERLYING)},
                                 {_quoted(UNDERLYING)}
                        ORDER BY {_quoted(RISK_TYPE)}, {_quoted(RISK_GREEK)},
                                 {_quoted(REPORTED_UNDERLYING)}, {_quoted(SOURCE_TYPE)}
                        """
                    ).df()
                    market = connection.execute(
                        f"""
                        SELECT {_quoted(SOURCE_TYPE)}, {_quoted(RISK_TYPE)},
                               {_quoted(RISK_GREEK)}, {_quoted(UNDERLYING)},
                               max({_quoted(SNAPSHOT_DATE)}) AS {_quoted(SNAPSHOT_DATE)},
                               arg_max({_quoted(REVISION)}, {_quoted(SNAPSHOT_DATE)})
                                   AS {_quoted(REVISION)}
                        FROM market_history
                        GROUP BY {_quoted(SOURCE_TYPE)}, {_quoted(RISK_TYPE)},
                                 {_quoted(RISK_GREEK)}, {_quoted(UNDERLYING)}
                        ORDER BY {_quoted(RISK_TYPE)}, {_quoted(RISK_GREEK)},
                                 {_quoted(UNDERLYING)}, {_quoted(SOURCE_TYPE)}
                        """
                    ).df()
                    metrics["rows"] = len(risk) + len(market)
            self._catalog_generation = generation
            self._risk_catalog = risk.copy(deep=True)
            self._market_catalog = market.copy(deep=True)
            return risk, market

    def available_dates(
        self,
        generation: str,
        *,
        kind: str,
        source_types: Sequence[str],
        risk_type: str,
        risk_greek: str,
        underlying: str,
        identity_mode: str,
    ) -> tuple[str, ...]:
        """Return observed dates for one exact identity without materializing rows."""

        table = "risk_history" if kind == "risk" else "market_history"
        date_column = RISK_DATE if kind == "risk" else MARKET_DATE
        identity_column = (
            REPORTED_UNDERLYING
            if kind == "risk" and identity_mode == "reported"
            else UNDERLYING
        )
        placeholders = ", ".join("?" for _source in source_types)
        parameters: list[object] = [*source_types, risk_type, risk_greek, underlying]
        with self._lock:
            connection = self._current(generation)
            if not self._has_days(connection):
                return ()
            with perf_span(
                LOGGER,
                "history.dates.query",
                budget_ms=_QUERY_BUDGET_MS,
                kind=kind,
                operation="date_projection",
            ) as metrics:
                rows = connection.execute(
                    f"""
                    SELECT DISTINCT CAST({_quoted(date_column)} AS DATE) AS selected_date
                    FROM {table}
                    WHERE {_quoted(SOURCE_TYPE)} IN ({placeholders})
                      AND {_quoted(RISK_TYPE)} = ?
                      AND {_quoted(RISK_GREEK)} = ?
                      AND {_quoted(identity_column)} = ?
                    ORDER BY selected_date
                    """,
                    parameters,
                ).fetchall()
                metrics["dates"] = len(rows)
        return tuple(str(row[0]) for row in rows)

    def rows(
        self,
        generation: str,
        *,
        kind: str,
        source_types: Sequence[str],
        risk_type: str,
        risk_greek: str,
        underlying: str,
        identity_mode: str,
        columns: Sequence[str],
        start_date: str,
        end_date: str,
        max_rows: int,
    ) -> pd.DataFrame:
        """Read one bounded exact identity with row and column pushdown."""

        table = "risk_history" if kind == "risk" else "market_history"
        date_column = RISK_DATE if kind == "risk" else MARKET_DATE
        identity_column = (
            REPORTED_UNDERLYING
            if kind == "risk" and identity_mode == "reported"
            else UNDERLYING
        )
        projection = ", ".join(_quoted(column) for column in dict.fromkeys(columns))
        order_columns = [
            column
            for column in (
                date_column,
                "Tenor Swap Order",
                "Tenor Option Order",
                "Tenor Swap",
                "Tenor Option",
                "Portfolio",
                SOURCE_TYPE,
            )
            if column in columns
        ]
        order_clause = ", ".join(_quoted(column) for column in order_columns)
        placeholders = ", ".join("?" for _source in source_types)
        parameters: list[object] = [
            *source_types,
            risk_type,
            risk_greek,
            underlying,
            start_date,
            end_date,
            max_rows + 1,
        ]
        with self._lock:
            connection = self._current(generation)
            if not self._has_days(connection):
                return pd.DataFrame(columns=list(dict.fromkeys(columns)))
            with perf_span(
                LOGGER,
                "history.rows.query",
                budget_ms=_QUERY_BUDGET_MS,
                kind=kind,
                operation="exact_projection",
            ) as metrics:
                frame = connection.execute(
                    f"""
                    SELECT {projection}
                    FROM {table}
                    WHERE {_quoted(SOURCE_TYPE)} IN ({placeholders})
                      AND {_quoted(RISK_TYPE)} = ?
                      AND {_quoted(RISK_GREEK)} = ?
                      AND {_quoted(identity_column)} = ?
                      AND CAST({_quoted(date_column)} AS DATE) BETWEEN ? AND ?
                    ORDER BY {order_clause}
                    LIMIT ?
                    """,
                    parameters,
                ).df()
                metrics["rows"] = len(frame)
        return frame


__all__ = ["ArchiveSQLStore"]
