"""Lazy, typed and paged Jump-to-Default reference data."""

from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import Sequence

import pandas as pd

from cube.app.s01_settings import resolve_data_path
from cube.ui.s10_table_data import filter_table_rows

JTD_REFERENCE_PATH = Path(__file__).resolve().parents[2] / "data" / "s13_jtd.csv"
JTD_NUMERIC_COLUMNS = ("Risk JTD", "EAD")  # Add every other measure here.
JTD_PAGE_SIZE = 25


class JTDReferenceError(RuntimeError):
    """The optional reference file cannot be used."""


@lru_cache(maxsize=1)
def _read_jtd_reference(path_text: str, modified_ns: int, size: int) -> pd.DataFrame:
    del modified_ns, size  # These values invalidate the one-file cache.
    path = Path(path_text)
    try:
        frame = pd.read_csv(
            path, dtype="string", encoding="utf-8-sig", keep_default_na=False
        )
    except (OSError, UnicodeError, pd.errors.EmptyDataError, pd.errors.ParserError) as error:
        raise JTDReferenceError(f"Could not read {path.name}: {error}") from error
    if "Underlying" not in frame.columns:
        raise JTDReferenceError(f"{path.name} must contain a column named 'Underlying'.")
    if frame.columns.duplicated().any():
        raise JTDReferenceError(f"{path.name} contains duplicate column names.")

    numeric_names = {name.casefold() for name in JTD_NUMERIC_COLUMNS}
    for column in frame.columns:
        if column.casefold() not in numeric_names:
            continue
        text = frame[column].str.strip().str.replace(",", "", regex=False)
        values = pd.to_numeric(text.mask(text.eq("")), errors="coerce")
        invalid = (text.ne("") & values.isna()) | values.isin([float("inf"), -float("inf")])
        if invalid.any():
            raise JTDReferenceError(f"{column} contains invalid numbers; fix the CSV.")
        frame[column] = values

    risk_column = next((c for c in frame if c.casefold() == "risk jtd"), None)
    if risk_column is None and not frame.empty:
        raise JTDReferenceError("JTD reference requires a 'Risk JTD' column for ordering.")
    if risk_column is not None:
        frame = frame.sort_values(
            risk_column, key=lambda values: values.abs(), ascending=False,
            kind="stable", na_position="last",
        )
    return frame.reset_index(drop=True)


def jtd_reference_rows(
    underlying: str | Sequence[str], *, path: str | Path | None = None
) -> pd.DataFrame:
    """Match raw identities exactly, retaining each CSV row once and all columns."""
    selected = [underlying] if isinstance(underlying, str) else list(underlying)
    source = resolve_data_path(
        str(path) if path is not None else os.getenv("CUBE_JTD_REFERENCE_PATH"),
        JTD_REFERENCE_PATH, root=JTD_REFERENCE_PATH.parent.parent,
    )
    try:
        stat = source.stat()
    except OSError as error:
        raise JTDReferenceError(f"JTD reference file is missing: {source}") from error
    frame = _read_jtd_reference(str(source.resolve()), stat.st_mtime_ns, stat.st_size)
    result = frame.loc[frame["Underlying"].isin(selected)].reset_index(drop=True).copy()
    if frame.empty:
        # Keep the ordinary table/filter row visible for an unpopulated template.
        # This adds column headings only, never exposure or identifier values.
        existing = {column.casefold() for column in result}
        for column in ("CRDS", *JTD_NUMERIC_COLUMNS):
            if column.casefold() not in existing:
                dtype = "float64" if column in JTD_NUMERIC_COLUMNS else "string"
                result[column] = pd.Series(dtype=dtype)
        result.attrs["jtd_empty_source"] = (
            f"No JTD records loaded: {source.name} contains only column headers. "
            "Supply the populated JTD reference file to show this selection."
        )
    return result


def jtd_page(frame, page_current=0, filter_tree=None, sort_by=None, *, filter_query=""):
    """Filter/sort the full branch; return one total row and 25 detail rows."""
    try:
        selected = filter_table_rows(frame, filter_tree, filter_query=filter_query)
    except ValueError as error:
        raise JTDReferenceError(str(error)) from error
    numeric = [column for column in frame if pd.api.types.is_numeric_dtype(frame[column])]
    totals = {column: None for column in frame}
    label_column = next((column for column in frame if column not in numeric), None)
    if label_column is not None:
        totals[label_column] = "Total (filtered rows)"
    for column in numeric:
        # All-missing measures stay missing, rather than inventing zero exposure.
        total = selected[column].sum(min_count=1)
        totals[column] = None if pd.isna(total) else float(total)
    if sort_by:
        if any(item.get("column_id") not in frame or item.get("direction") not in {"asc", "desc"}
               for item in sort_by):
            raise JTDReferenceError("That sort column changed; select the JTD row again.")
        selected = selected.sort_values(
            [item["column_id"] for item in sort_by],
            ascending=[item["direction"] == "asc" for item in sort_by],
            kind="stable", na_position="last",
        )
    else:
        risk_column = next((c for c in frame if c.casefold() == "risk jtd"), None)
        if risk_column is not None:
            selected = selected.sort_values(risk_column, key=lambda values: values.abs(),
                                            ascending=False, kind="stable", na_position="last")
    count = len(selected)
    page_count = (count + JTD_PAGE_SIZE - 1) // JTD_PAGE_SIZE
    page_current = min(max(int(page_current or 0), 0), max(page_count - 1, 0))
    start = page_current * JTD_PAGE_SIZE
    page = selected.iloc[start:start + JTD_PAGE_SIZE]
    records = [totals] + page.astype(object).where(page.notna(), None).to_dict("records")
    ordering = " · |Risk JTD| largest first" if not sort_by else ""
    note = (
        f"{start + 1:,}–{start + len(page):,} of {count:,} matching rows{ordering}. "
        "Total includes every matching row, across all pages."
        if count else frame.attrs.get("jtd_empty_source", "No matching JTD reference rows.")
    )
    return records, page_count, page_current, note


__all__ = [
    "JTD_REFERENCE_PATH", "JTD_NUMERIC_COLUMNS", "JTD_PAGE_SIZE",
    "JTDReferenceError", "jtd_reference_rows", "jtd_page",
]
