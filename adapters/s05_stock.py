"""Validated Stock connector boundary with a replaceable fake implementation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from core.s07_stock import (
    STOCK_COLUMNS,
    STOCK_IDENTITY_COLUMNS,
    STOCK_NUMERIC_COLUMNS,
    STOCK_TEXT_COLUMNS,
    validate_stock_frame,
)
from core.s11_risk_archive import (
    ARCHIVE_SCHEMA_VERSION,
    STOCK_ARCHIVE_FILE_NAMES,
    STOCK_FILE_NAME,
    SUCCESS_FILE_NAME,
    load_stock_archive_frame,
)


FAKE_NOTICE = "FAKE_REPLACE_ME"
FIXTURE_TAG = "deterministic-rebirth-v4"
_LEGACY_FIXTURE_TAG = "deterministic-rebirth-v3"
STOCK_DATE_COLUMN = "Stock Date"
STOCK_HISTORY_COLUMNS = (STOCK_DATE_COLUMN, *STOCK_COLUMNS)
STOCK_ARCHIVE_SCHEMA_VERSION = ARCHIVE_SCHEMA_VERSION
STOCK_HISTORY_MAX_DATES = 1_000
STOCK_SUCCESS_FILE_NAME = SUCCESS_FILE_NAME
STOCK_ARCHIVE_ROOT = Path(__file__).resolve().parents[1] / "data" / "histo"


class StockSource(Protocol):
    """Shape of the site's replaceable ``GetStock`` function."""

    def __call__(self, stock_date: pd.Timestamp) -> pd.DataFrame: ...


def normalize_stock_date(value: object) -> pd.Timestamp:
    """Return one normalized stock date without silently accepting null input."""

    if value is None or isinstance(value, (bool, np.bool_)):
        raise TypeError("stock_date must be a date-like value")
    try:
        selected = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("stock_date must be a valid date-like value") from exc
    if pd.isna(selected):
        raise ValueError("stock_date must be a valid date-like value")
    if selected.tzinfo is not None:
        selected = selected.tz_localize(None)
    return selected.normalize()


@dataclass(frozen=True)
class StockConnectorAdapter:
    """Bind one personal ``GetStock`` function to the validated Stock contract."""

    stock: StockSource

    def get_stock(self, stock_date: object) -> pd.DataFrame:
        selected_date = normalize_stock_date(stock_date)
        return validate_stock_frame(
            self.stock(selected_date),
            label=f"Stock for {selected_date.date().isoformat()}",
        )


def build_stock_adapter(*, stock: StockSource) -> StockConnectorAdapter:
    """Return a validated adapter around the site's personal Stock function."""

    if not callable(stock):
        raise TypeError("stock must be callable")
    return StockConnectorAdapter(stock=stock)


def _validate_fake_identities(frame: pd.DataFrame) -> None:
    fake_identity_columns = tuple(
        column for column in STOCK_TEXT_COLUMNS if column != "Currency"
    )
    if (
        not frame.loc[:, list(fake_identity_columns)]
        .map(lambda value: isinstance(value, str) and FAKE_NOTICE in value)
        .all(axis=None)
    ):
        raise ValueError(
            f"Every governed Stock identity must retain the {FAKE_NOTICE} marker"
        )


def load_stock_archive_leaf(
    root: str | Path,
    stock_date: object,
    *,
    identity: Mapping[str, str] | None = None,
) -> pd.DataFrame:
    """Lazily validate and return one completed Stock archive leaf."""

    selected = normalize_stock_date(stock_date)
    selected_text = selected.date().isoformat()
    resolved_root = Path(root).expanduser().resolve()
    leaf = resolved_root / selected_text
    if not leaf.is_dir():
        raise ValueError(f"Completed Stock leaf has invalid entries: {leaf}")
    frame = load_stock_archive_frame(
        resolved_root,
        selected,
        identity=identity,
    )
    marker_path = leaf / STOCK_SUCCESS_FILE_NAME
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    if marker.get("fixture") not in {FIXTURE_TAG, _LEGACY_FIXTURE_TAG}:
        raise ValueError(
            f"Completed Stock marker is not a governed fixture: {marker_path}"
        )
    if frame.empty and identity is None:
        raise ValueError(f"No {FAKE_NOTICE} Stock history exists for {selected_text}")
    if not frame.empty:
        _validate_fake_identities(frame)
    return frame.copy(deep=True)


def load_stock_history(
    root: str | Path,
    start_date: object,
    end_date: object,
    *,
    identity: Mapping[str, object] | None = None,
) -> pd.DataFrame:
    """Load bounded history, optionally projecting one exact Stock identity."""

    start = normalize_stock_date(start_date)
    end = normalize_stock_date(end_date)
    if start > end:
        raise ValueError("Stock history start_date must not be after end_date")
    dates = pd.bdate_range(start=start, end=end)
    if len(dates) > STOCK_HISTORY_MAX_DATES:
        raise ValueError(
            f"Stock history is limited to {STOCK_HISTORY_MAX_DATES} business dates"
        )
    resolved_root = Path(root).expanduser().resolve()
    if not resolved_root.is_dir():
        raise ValueError(f"Stock history root must be a directory: {resolved_root}")
    selected_identity: dict[str, str] | None = None
    if identity is not None:
        if set(identity) != set(STOCK_IDENTITY_COLUMNS):
            raise ValueError(
                "Stock history identity must contain exactly "
                f"{list(STOCK_IDENTITY_COLUMNS)}"
            )
        selected_identity = {}
        for column in STOCK_IDENTITY_COLUMNS:
            value = identity[column]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Stock history identity {column} must be non-blank text"
                )
            selected_identity[column] = value
    frames: list[pd.DataFrame] = []
    for stock_date in dates:
        # A genuinely absent completed date is a truthful missing observation.
        # Existing leaves still pass through strict marker/schema validation.
        if not (resolved_root / stock_date.date().isoformat()).exists():
            continue
        frame = load_stock_archive_leaf(
            resolved_root,
            stock_date,
            identity=selected_identity,
        )
        frame.insert(0, STOCK_DATE_COLUMN, stock_date)
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=list(STOCK_HISTORY_COLUMNS))
    return pd.concat(frames, ignore_index=True)


def _fake_stock_source(stock_date: pd.Timestamp) -> pd.DataFrame:
    """Return one defensive dated slice from governed fake Stock history."""

    return load_stock_archive_leaf(STOCK_ARCHIVE_ROOT, stock_date)


_FAKE_STOCK_ADAPTER = build_stock_adapter(stock=_fake_stock_source)


def get_stock(stock_date: object) -> pd.DataFrame:
    """Return validated fake Stock data for the selected date.

    Replace ``_fake_stock_source`` with the site's real implementation at the
    composition boundary; callers keep the same exact schema.
    """

    return _FAKE_STOCK_ADAPTER.get_stock(stock_date)


# Retain the business-facing name from the requested external connector.
GetStock = get_stock


__all__ = [
    "GetStock",
    "STOCK_ARCHIVE_FILE_NAMES",
    "STOCK_ARCHIVE_ROOT",
    "STOCK_ARCHIVE_SCHEMA_VERSION",
    "STOCK_DATE_COLUMN",
    "STOCK_FILE_NAME",
    "STOCK_HISTORY_COLUMNS",
    "STOCK_HISTORY_MAX_DATES",
    "STOCK_SUCCESS_FILE_NAME",
    "STOCK_COLUMNS",
    "STOCK_NUMERIC_COLUMNS",
    "STOCK_TEXT_COLUMNS",
    "StockConnectorAdapter",
    "StockSource",
    "build_stock_adapter",
    "get_stock",
    "load_stock_archive_leaf",
    "load_stock_history",
    "normalize_stock_date",
    "validate_stock_frame",
]
