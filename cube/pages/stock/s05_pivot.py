"""Small, page-owned Stock pivot projection.

Only the two numeric Stock measures are aggregated.  Static connector and
Portfolio-mapping columns remain available through the row-level detail table
owned by :mod:`s03_view`.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import pandas as pd


STOCK_PIVOT_ROW_FIELDS = (
    ("Activity", "Activity"),
    ("Category", "Bucket"),
    ("CRDS", "CRDS"),
    ("CPTY", "CPTY"),
    ("Portfolio", "Portfolio"),
    ("SignoffGroup", "Sign-off group"),
    ("SubCategory", "Sub-category"),
    ("Product", "Product"),
    ("Currency", "Currency"),
    ("Instrument", "Instrument"),
)
STOCK_PIVOT_DEFAULT_ROWS = ("Activity", "Category", "CRDS", "CPTY")
STOCK_PIVOT_COLUMN_FIELDS = (
    ("", "No column split"),
    ("Currency", "Currency"),
    ("Product", "Product"),
)
STOCK_PIVOT_VALUES = (("Stock", "Stock"), ("dStock", "dStock"))
STOCK_PIVOT_DEFAULT_VALUES = ("Stock", "dStock")
STOCK_PIVOT_SPLIT_LIMIT = 8

_ROW_FIELDS = {value for value, _label in STOCK_PIVOT_ROW_FIELDS}
_COLUMN_FIELDS = {value for value, _label in STOCK_PIVOT_COLUMN_FIELDS}
_VALUE_FIELDS = {value for value, _label in STOCK_PIVOT_VALUES}


@dataclass(frozen=True)
class StockPivotResult:
    """Visible Stock tree records and its Dash DataTable columns."""

    records: list[dict[str, object]]
    columns: list[dict[str, object]]
    visible_positions: int


def normalize_stock_pivot_controls(
    rows: object,
    column: object,
    values: object,
) -> tuple[tuple[str, ...], str, tuple[str, ...]]:
    """Validate compact pivot controls and provide useful empty defaults."""

    row_values = (
        [str(item) for item in rows]
        if isinstance(rows, Sequence) and not isinstance(rows, (str, bytes))
        else []
    )
    normalized_rows = tuple(
        dict.fromkeys(item for item in row_values if item in _ROW_FIELDS)
    )
    if not normalized_rows:
        normalized_rows = STOCK_PIVOT_DEFAULT_ROWS

    normalized_column = str(column or "")
    if normalized_column not in _COLUMN_FIELDS:
        normalized_column = ""

    value_values = (
        [str(item) for item in values]
        if isinstance(values, Sequence) and not isinstance(values, (str, bytes))
        else []
    )
    normalized_values = tuple(
        dict.fromkeys(item for item in value_values if item in _VALUE_FIELDS)
    )
    if not normalized_values:
        normalized_values = STOCK_PIVOT_DEFAULT_VALUES
    return normalized_rows, normalized_column, normalized_values


def stock_pivot_path_token(path: Sequence[str]) -> str:
    """Serialize a hierarchy path without parsing visible labels."""

    return json.dumps([str(value) for value in path], separators=(",", ":"))


def stock_pivot_path_from_token(value: object) -> tuple[str, ...]:
    """Decode a bounded hierarchy path token."""

    if not isinstance(value, str):
        raise ValueError("Stock pivot path is invalid")
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("Stock pivot path is invalid") from error
    if (
        not isinstance(decoded, list)
        or not decoded
        or len(decoded) > len(STOCK_PIVOT_ROW_FIELDS)
        or any(not isinstance(item, str) or not item.strip() for item in decoded)
    ):
        raise ValueError("Stock pivot path is invalid")
    return tuple(decoded)


def normalize_stock_pivot_open_paths(value: object) -> set[tuple[str, ...]]:
    """Return valid open paths and ignore stale paths after a layout change."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return set()
    result: set[tuple[str, ...]] = set()
    for token in value:
        try:
            result.add(stock_pivot_path_from_token(token))
        except ValueError:
            continue
    return result


def toggle_stock_pivot_path(open_paths: object, token: object) -> list[str]:
    """Toggle one exact branch and close any now-hidden descendants."""

    requested = stock_pivot_path_from_token(token)
    current = normalize_stock_pivot_open_paths(open_paths)
    if requested in current:
        current = {
            path
            for path in current
            if path != requested and path[: len(requested)] != requested
        }
    else:
        current.add(requested)
    return [stock_pivot_path_token(path) for path in sorted(current)]


def _metric_value(frame: pd.DataFrame, metric: str) -> float | None:
    value = pd.to_numeric(frame[metric], errors="coerce").sum(min_count=1)
    return None if pd.isna(value) else float(value)


def _ordered_children(
    frame: pd.DataFrame, field: str
) -> Iterable[tuple[str, pd.DataFrame]]:
    labels = frame[field].fillna("Unmapped").astype(str)
    children: list[tuple[str, pd.DataFrame, float]] = []
    for label in labels.drop_duplicates().tolist():
        child = frame.loc[labels.eq(label)]
        stock = _metric_value(child, "Stock") or 0.0
        children.append((label, child, abs(stock)))
    children.sort(key=lambda item: (-item[2], item[0].casefold()))
    return ((label, child) for label, child, _magnitude in children)


def _history_key(frame: pd.DataFrame) -> tuple[str, str] | None:
    pairs = frame.loc[:, ["CRDS", "Activity"]].drop_duplicates()
    if len(pairs) != 1:
        return None
    row = pairs.iloc[0]
    return str(row["CRDS"]), str(row["Activity"])


def build_stock_pivot(
    display: pd.DataFrame,
    *,
    row_fields: object = STOCK_PIVOT_DEFAULT_ROWS,
    column_field: object = "",
    value_fields: object = STOCK_PIVOT_DEFAULT_VALUES,
    open_paths: object = (),
) -> StockPivotResult:
    """Build only visible hierarchy rows for the current Stock selection."""

    if not isinstance(display, pd.DataFrame):
        raise TypeError("Stock pivot input must be a pandas DataFrame")
    rows, column, values = normalize_stock_pivot_controls(
        row_fields, column_field, value_fields
    )
    required = {"CRDS", "Activity", "Stock", "dStock", *rows}
    if column:
        required.add(column)
    missing = sorted(required - set(display.columns))
    if missing:
        raise ValueError(f"Stock pivot input is missing columns: {missing}")

    split_values: list[str] = []
    if column:
        split_values = sorted(
            display[column].dropna().astype(str).unique().tolist(),
            key=str.casefold,
        )[:STOCK_PIVOT_SPLIT_LIMIT]

    columns: list[dict[str, object]] = [
        {
            "name": " / ".join(dict(STOCK_PIVOT_ROW_FIELDS)[field] for field in rows),
            "id": "Hierarchy",
        },
        {"name": "Positions", "id": "Positions", "type": "numeric"},
    ]
    metric_columns: list[tuple[str, str, str | None]] = []
    if column and split_values:
        for split in split_values:
            for metric in values:
                identifier = f"{column}:{split}:{metric}"
                columns.append(
                    {"name": [split, metric], "id": identifier, "type": "numeric"}
                )
                metric_columns.append((identifier, metric, split))
    else:
        for metric in values:
            columns.append({"name": metric, "id": metric, "type": "numeric"})
            metric_columns.append((metric, metric, None))

    if display.empty:
        return StockPivotResult([], columns, 0)

    opened = normalize_stock_pivot_open_paths(open_paths)
    records: list[dict[str, object]] = []

    def append_children(scope: pd.DataFrame, depth: int, path: tuple[str, ...]) -> None:
        if depth >= len(rows):
            return
        field = rows[depth]
        for label, child in _ordered_children(scope, field):
            child_path = (*path, label)
            leaf = depth == len(rows) - 1
            token = stock_pivot_path_token(child_path)
            history_key = _history_key(child) if leaf else None
            glyph = "" if leaf else ("−" if child_path in opened else "▸")
            indent = "\u00a0\u00a0" * depth
            record: dict[str, object] = {
                "id": json.dumps(
                    {
                        "kind": "history"
                        if history_key
                        else "leaf"
                        if leaf
                        else "branch",
                        "path": token,
                        **(
                            {"crds": history_key[0], "activity": history_key[1]}
                            if history_key
                            else {}
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                "Hierarchy": f"{indent}{glyph} {label}".rstrip(),
                "Positions": int(len(child)),
            }
            for identifier, metric, split in metric_columns:
                metric_scope = child
                if split is not None:
                    metric_scope = child.loc[child[column].astype(str).eq(split)]
                record[identifier] = _metric_value(metric_scope, metric)
            records.append(record)
            if not leaf and child_path in opened:
                append_children(child, depth + 1, child_path)

    append_children(display, 0, ())
    return StockPivotResult(records, columns, len(display))


def stock_pivot_row_payload(row_id: object) -> Mapping[str, object]:
    """Decode one server-generated DataTable row identifier."""

    if not isinstance(row_id, str):
        raise ValueError("The selected Stock row is invalid")
    try:
        payload = json.loads(row_id)
    except json.JSONDecodeError as error:
        raise ValueError("The selected Stock row is invalid") from error
    if not isinstance(payload, Mapping) or payload.get("kind") not in {
        "branch",
        "leaf",
        "history",
    }:
        raise ValueError("The selected Stock row is invalid")
    stock_pivot_path_from_token(payload.get("path"))
    return payload


__all__ = [
    "STOCK_PIVOT_COLUMN_FIELDS",
    "STOCK_PIVOT_DEFAULT_ROWS",
    "STOCK_PIVOT_DEFAULT_VALUES",
    "STOCK_PIVOT_ROW_FIELDS",
    "STOCK_PIVOT_VALUES",
    "StockPivotResult",
    "build_stock_pivot",
    "normalize_stock_pivot_controls",
    "normalize_stock_pivot_open_paths",
    "stock_pivot_path_from_token",
    "stock_pivot_path_token",
    "stock_pivot_row_payload",
    "toggle_stock_pivot_path",
]
