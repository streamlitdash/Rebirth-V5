"""V4 page-owned, lazy Stock archive queries and presentation helpers."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Protocol, runtime_checkable

import duckdb
import pandas as pd
import plotly.graph_objects as go

from rebirth.adapters.s08_stock import (
    STOCK_DATE_COLUMN,
    STOCK_HISTORY_COLUMNS,
    normalize_stock_date,
)
from rebirth.app.s03_logging import perf_span
from rebirth.domain.s09_stock import (
    STOCK_COLUMNS,
    STOCK_IDENTITY_COLUMNS,
    validate_stock_frame,
)
from rebirth.history import (
    REVISION,
    CompletedArchiveDay,
    list_queryable_v4_archive_days,
)


LOGGER = logging.getLogger(__name__)
STOCK_HISTORY_METRICS = ("Quantity", "Market Value")
STOCK_HISTORY_SELECTOR_LIMIT = 50
STOCK_HISTORY_SEARCH_LIMIT = 200
_STOCK_HISTORY_QUERY_BUDGET_MS = 750


@dataclass(frozen=True)
class StockHistoryCatalogResult:
    """Small selector page and truthful archive date bounds."""

    options: tuple[dict[str, str], ...]
    minimum_date: str | None
    maximum_date: str | None
    date_count: int


@runtime_checkable
class StockHistoryQueryProtocol(Protocol):
    """Bounded page-owned Stock history source."""

    def clear(self) -> None: ...

    def catalog(
        self,
        search: object = None,
        *,
        limit: int = STOCK_HISTORY_SELECTOR_LIMIT,
    ) -> StockHistoryCatalogResult: ...

    def rows(
        self,
        identity: Mapping[str, object],
        start_date: object,
        end_date: object,
    ) -> pd.DataFrame: ...


def stock_history_identity_token(identity: Mapping[str, object]) -> str:
    """Serialize one exact Stock identity independently from its label."""

    if set(identity) != set(STOCK_IDENTITY_COLUMNS):
        raise ValueError(
            "Stock history identity must contain exactly "
            f"{list(STOCK_IDENTITY_COLUMNS)}"
        )
    payload: dict[str, str] = {}
    for column in STOCK_IDENTITY_COLUMNS:
        value = identity[column]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Stock history identity {column} must be non-blank text")
        payload[column] = value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def stock_history_identity_from_token(token: object) -> dict[str, str]:
    """Decode and strictly validate one structured Stock identity token."""

    if not isinstance(token, str) or not token.strip():
        raise ValueError("Select one Stock history identity")
    try:
        payload = json.loads(token)
    except json.JSONDecodeError as exc:
        raise ValueError("Stock history identity token is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("Stock history identity token must contain an object")
    stock_history_identity_token(payload)
    return {column: payload[column] for column in STOCK_IDENTITY_COLUMNS}


def stock_history_identity_options(
    history: pd.DataFrame,
) -> list[dict[str, str]]:
    """Return labels and structured values for exact identities."""

    identities = history.loc[:, list(STOCK_IDENTITY_COLUMNS)].drop_duplicates()
    options = []
    for identity in identities.to_dict("records"):
        options.append(
            {
                "label": " | ".join(
                    f"{column}={identity[column]}" for column in STOCK_IDENTITY_COLUMNS
                ),
                "value": stock_history_identity_token(identity),
            }
        )
    return sorted(options, key=lambda option: option["label"].casefold())


def stock_history_date_range(
    end_date: object,
    *,
    preset: object = "1y",
    minimum_date: object | None = None,
    start_date: object | None = None,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Resolve one named period and clamp it to actual archive bounds."""

    end = normalize_stock_date(end_date)
    selected = str(preset or "1y").strip().casefold()
    if selected == "wtd":
        start = end - pd.Timedelta(days=end.weekday())
    elif selected == "mtd":
        start = end.replace(day=1)
    elif selected == "ytd":
        start = end.replace(month=1, day=1)
    elif selected == "all":
        start = normalize_stock_date(minimum_date or end)
    elif selected == "custom":
        start = normalize_stock_date(start_date or minimum_date or end)
    elif selected == "1y":
        start = end - pd.DateOffset(years=1) + pd.offsets.BDay(1)
    else:
        raise ValueError(f"Unknown Stock history period: {preset!r}")
    if minimum_date is not None:
        start = max(start, normalize_stock_date(minimum_date))
    return normalize_stock_date(min(start, end)), end


def normalize_stock_history_frame(
    value: object,
    *,
    identity: Mapping[str, object],
    start_date: object,
    end_date: object,
) -> pd.DataFrame:
    """Validate one exact-identity history result at the page boundary."""

    start = normalize_stock_date(start_date)
    end = normalize_stock_date(end_date)
    expected_identity = stock_history_identity_from_token(
        stock_history_identity_token(identity)
    )
    if not isinstance(value, pd.DataFrame):
        raise TypeError("Stock history source must return a pandas DataFrame")
    if tuple(value.columns) != STOCK_HISTORY_COLUMNS:
        raise ValueError(
            "Stock history source columns must be exactly "
            f"{list(STOCK_HISTORY_COLUMNS)}"
        )
    source = value.copy(deep=True)
    if source.empty:
        source[STOCK_DATE_COLUMN] = pd.Series(
            index=source.index,
            dtype="datetime64[ns]",
        )
    else:
        source[STOCK_DATE_COLUMN] = source[STOCK_DATE_COLUMN].map(normalize_stock_date)
    if not source.empty and not source[STOCK_DATE_COLUMN].between(start, end).all():
        raise ValueError("Stock history source returned dates outside the request")
    if source.duplicated([STOCK_DATE_COLUMN, *STOCK_IDENTITY_COLUMNS]).any():
        raise ValueError("Stock history source returned duplicate dated identities")
    for column, expected in expected_identity.items():
        if not source[column].eq(expected).all():
            raise ValueError(
                "Stock history source returned rows outside the selected identity"
            )
    if source.empty:
        return source.reset_index(drop=True)

    validated: list[pd.DataFrame] = []
    for stock_date, dated_rows in source.groupby(STOCK_DATE_COLUMN, sort=True):
        rows = validate_stock_frame(
            dated_rows.loc[:, list(STOCK_COLUMNS)],
            label=f"Stock history for {stock_date.date().isoformat()}",
        )
        rows.insert(0, STOCK_DATE_COLUMN, stock_date)
        validated.append(rows)
    return (
        pd.concat(validated, ignore_index=True)
        .sort_values([STOCK_DATE_COLUMN, *STOCK_IDENTITY_COLUMNS], kind="stable")
        .reset_index(drop=True)
    )


class SQLStockHistoryRepository:
    """Generation-aware Stock-only queries over completed Parquet leaves."""

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser()
        self._lock = RLock()
        self._days: tuple[CompletedArchiveDay, ...] | None = None
        self._connection: duckdb.DuckDBPyConnection | None = None

    def clear(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
            self._connection = None
            self._days = None

    def _current_connection(self) -> duckdb.DuckDBPyConnection:
        days = list_queryable_v4_archive_days(self._root)
        if self._connection is not None and days == self._days:
            return self._connection
        self.clear()
        connection = duckdb.connect(":memory:")
        try:
            connection.execute("SET enable_progress_bar = false")
            stock_days = tuple(day for day in days if day.stock_path is not None)
            if not stock_days:
                projection = ", ".join(
                    [
                        f'CAST(NULL AS DATE) AS "{STOCK_DATE_COLUMN}"',
                        f'CAST(NULL AS BIGINT) AS "{REVISION}"',
                        *(
                            f'CAST(NULL AS {"DOUBLE" if column in STOCK_HISTORY_METRICS else "VARCHAR"}) AS "{column}"'
                            for column in STOCK_COLUMNS
                        ),
                    ]
                )
                connection.execute(
                    f"CREATE VIEW stock_history AS SELECT {projection} WHERE FALSE"
                )
            else:
                paths = [str(day.stock_path.resolve()) for day in stock_days]
                connection.from_parquet(
                    paths,
                    filename=True,
                    union_by_name=False,
                ).create_view("_stock_files")
                connection.execute(
                    "CREATE TABLE _stock_days ("
                    "stock_date DATE, revision BIGINT, stock_path VARCHAR)"
                )
                connection.executemany(
                    "INSERT INTO _stock_days VALUES (?, ?, ?)",
                    [
                        (
                            day.stock_date,
                            day.revision,
                            str(day.stock_path.resolve()),
                        )
                        for day in stock_days
                    ],
                )
                connection.execute(
                    f'''CREATE VIEW stock_history AS
                        SELECT d.stock_date AS "{STOCK_DATE_COLUMN}",
                               d.revision AS "{REVISION}",
                               s.* EXCLUDE(filename)
                        FROM _stock_files s
                        JOIN _stock_days d ON s.filename = d.stock_path'''
                )
        except BaseException:
            connection.close()
            raise
        self._connection = connection
        self._days = days
        return connection

    def catalog(
        self,
        search: object = None,
        *,
        limit: int = STOCK_HISTORY_SELECTOR_LIMIT,
    ) -> StockHistoryCatalogResult:
        text = str(search or "").strip()
        if len(text) > STOCK_HISTORY_SEARCH_LIMIT:
            raise ValueError(
                f"Stock history search is limited to {STOCK_HISTORY_SEARCH_LIMIT} characters"
            )
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= 100
        ):
            raise ValueError("Stock history selector limit must be between 1 and 100")
        identity_sql = ", ".join(f'"{column}"' for column in STOCK_IDENTITY_COLUMNS)
        search_sql = " || ' | ' || ".join(
            f'CAST("{column}" AS VARCHAR)' for column in STOCK_IDENTITY_COLUMNS
        )
        with (
            self._lock,
            perf_span(
                LOGGER,
                "stock.history.catalog",
                budget_ms=_STOCK_HISTORY_QUERY_BUDGET_MS,
            ) as timing,
        ):
            connection = self._current_connection()
            minimum, maximum, date_count = connection.execute(
                f'''SELECT min("{STOCK_DATE_COLUMN}")::VARCHAR,
                           max("{STOCK_DATE_COLUMN}")::VARCHAR,
                           count(DISTINCT "{STOCK_DATE_COLUMN}")::BIGINT
                    FROM stock_history'''
            ).fetchone()
            rows = connection.execute(
                f"""SELECT DISTINCT {identity_sql}
                    FROM stock_history
                    WHERE ? = '' OR lower({search_sql}) LIKE ?
                    ORDER BY {identity_sql}
                    LIMIT ?""",
                [text.casefold(), f"%{text.casefold()}%", limit],
            ).df()
            rows.columns = list(STOCK_IDENTITY_COLUMNS)
            options = tuple(stock_history_identity_options(rows))
            timing.update(rows=len(options), dates=int(date_count or 0))
        return StockHistoryCatalogResult(
            options,
            minimum,
            maximum,
            int(date_count or 0),
        )

    def rows(
        self,
        identity: Mapping[str, object],
        start_date: object,
        end_date: object,
    ) -> pd.DataFrame:
        selected_identity = stock_history_identity_from_token(
            stock_history_identity_token(identity)
        )
        start = normalize_stock_date(start_date)
        end = normalize_stock_date(end_date)
        if start > end:
            raise ValueError("Stock history start date must not exceed end date")
        clauses = " AND ".join(f'"{column}" = ?' for column in STOCK_IDENTITY_COLUMNS)
        projection = ", ".join(
            [f'"{STOCK_DATE_COLUMN}"', *(f'"{column}"' for column in STOCK_COLUMNS)]
        )
        with (
            self._lock,
            perf_span(
                LOGGER,
                "stock.history.rows",
                budget_ms=_STOCK_HISTORY_QUERY_BUDGET_MS,
            ) as timing,
        ):
            frame = (
                self._current_connection()
                .execute(
                    f'''SELECT {projection}
                    FROM stock_history
                    WHERE {clauses}
                      AND "{STOCK_DATE_COLUMN}" BETWEEN ? AND ?
                    ORDER BY "{STOCK_DATE_COLUMN}"''',
                    [
                        *(
                            selected_identity[column]
                            for column in STOCK_IDENTITY_COLUMNS
                        ),
                        start.date().isoformat(),
                        end.date().isoformat(),
                    ],
                )
                .df()
            )
            frame.columns = list(STOCK_HISTORY_COLUMNS)
            timing.update(rows=len(frame))
        return normalize_stock_history_frame(
            frame,
            identity=selected_identity,
            start_date=start,
            end_date=end,
        )


def build_stock_history_empty_figure(message: str) -> go.Figure:
    figure = go.Figure()
    figure.update_layout(
        template="plotly_white",
        height=360,
        margin={"l": 55, "r": 20, "t": 30, "b": 45},
        annotations=[
            {
                "text": str(message),
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
            }
        ],
    )
    return figure


def stock_value_history_frame(
    history: pd.DataFrame,
    *,
    start_date: object,
    end_date: object,
) -> pd.DataFrame:
    """Return Stock and dStock on a truthful business-date axis.

    The input may contain several exact source identities selected through one
    CRDS + Activity pair. Only the numeric historical value is combined; no
    static or mapped metadata is ever aggregated.
    """

    if not isinstance(history, pd.DataFrame):
        raise TypeError("Stock history must be a pandas DataFrame")
    required = {STOCK_DATE_COLUMN, "Market Value"}
    missing = sorted(required - set(history.columns))
    if missing:
        raise ValueError(f"Stock history is missing required columns: {missing}")
    start = normalize_stock_date(start_date)
    end = normalize_stock_date(end_date)
    if start > end:
        raise ValueError("Stock history start date must not exceed end date")

    display_dates = pd.bdate_range(start, end)
    calculation_dates = pd.bdate_range(start - pd.offsets.BDay(1), end)
    source = history.loc[:, [STOCK_DATE_COLUMN, "Market Value"]].copy()
    if not source.empty:
        source[STOCK_DATE_COLUMN] = source[STOCK_DATE_COLUMN].map(normalize_stock_date)
        source["Market Value"] = pd.to_numeric(source["Market Value"], errors="coerce")
        stock = source.groupby(STOCK_DATE_COLUMN, sort=True)["Market Value"].sum(
            min_count=1
        )
    else:
        stock = pd.Series(dtype="float64")
    stock = stock.reindex(calculation_dates)
    result = pd.DataFrame(
        {
            STOCK_DATE_COLUMN: display_dates,
            "Stock": stock.reindex(display_dates).to_numpy(),
            "dStock": stock.diff().reindex(display_dates).to_numpy(),
        }
    )
    return result


def build_stock_value_history_figure(
    history: pd.DataFrame,
    *,
    crds: object,
    activity: object,
    start_date: object,
    end_date: object,
) -> go.Figure:
    """Plot inline Stock and dStock with visible archive gaps."""

    crds_value = str(crds or "").strip()
    activity_value = str(activity or "").strip()
    if not crds_value or not activity_value:
        raise ValueError("Select both CRDS and Activity")
    values = stock_value_history_frame(
        history,
        start_date=start_date,
        end_date=end_date,
    )
    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=values[STOCK_DATE_COLUMN],
            y=values["Stock"],
            mode="lines+markers",
            connectgaps=False,
            name="Stock",
            hovertemplate="%{x|%Y-%m-%d}<br>Stock: %{y:,.2f}<extra></extra>",
        )
    )
    figure.add_trace(
        go.Bar(
            x=values[STOCK_DATE_COLUMN],
            y=values["dStock"],
            name="dStock",
            opacity=0.42,
            yaxis="y2",
            hovertemplate="%{x|%Y-%m-%d}<br>dStock: %{y:,.2f}<extra></extra>",
        )
    )
    figure.update_layout(
        template="plotly_white",
        height=380,
        margin={"l": 65, "r": 65, "t": 55, "b": 45},
        title=f"{crds_value} · {activity_value}",
        hovermode="x unified",
        barmode="overlay",
        xaxis_title=STOCK_DATE_COLUMN,
        yaxis={"title": "Stock"},
        yaxis2={"title": "dStock", "overlaying": "y", "side": "right"},
        legend={"orientation": "h", "y": 1.08, "x": 1, "xanchor": "right"},
    )
    return figure


__all__ = [
    "SQLStockHistoryRepository",
    "STOCK_HISTORY_METRICS",
    "STOCK_HISTORY_SELECTOR_LIMIT",
    "StockHistoryCatalogResult",
    "StockHistoryQueryProtocol",
    "build_stock_history_empty_figure",
    "build_stock_value_history_figure",
    "normalize_stock_history_frame",
    "stock_history_date_range",
    "stock_history_identity_from_token",
    "stock_history_identity_options",
    "stock_history_identity_token",
    "stock_value_history_frame",
]
