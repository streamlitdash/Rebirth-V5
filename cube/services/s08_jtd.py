"""Lazy lookup for the optional Jump-to-Default reference table."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd


JTD_REFERENCE_PATH = Path(__file__).resolve().parents[2] / "data" / "s13_jtd.csv"


class JTDReferenceError(RuntimeError):
    """Raised when the optional JTD reference file cannot be used."""


@lru_cache(maxsize=1)
def _read_jtd_reference(path_text: str, modified_ns: int, size: int) -> pd.DataFrame:
    """Read one file revision; revision fields form the small cache key."""

    del modified_ns, size
    path = Path(path_text)
    try:
        frame = pd.read_csv(
            path,
            dtype="string",
            encoding="utf-8-sig",
            keep_default_na=False,
        )
    except (
        OSError,
        UnicodeError,
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
    ) as error:
        raise JTDReferenceError(f"Could not read {path.name}: {error}") from error
    if "Underlying" not in frame.columns:
        raise JTDReferenceError(
            f"{path.name} must contain a column named 'Underlying'."
        )
    if frame.columns.duplicated().any():
        raise JTDReferenceError(f"{path.name} contains duplicate column names.")
    return frame


def jtd_reference_rows(
    underlying: str,
    *,
    path: str | Path = JTD_REFERENCE_PATH,
) -> pd.DataFrame:
    """Return caller-owned rows exactly matching one clicked Underlying."""

    selected = str(underlying)
    source = Path(path)
    try:
        stat = source.stat()
    except OSError as error:
        raise JTDReferenceError(f"JTD reference file is missing: {source}") from error
    frame = _read_jtd_reference(
        str(source.resolve()),
        stat.st_mtime_ns,
        stat.st_size,
    )
    return frame.loc[frame["Underlying"].eq(selected)].reset_index(drop=True).copy()


__all__ = ["JTD_REFERENCE_PATH", "JTDReferenceError", "jtd_reference_rows"]
