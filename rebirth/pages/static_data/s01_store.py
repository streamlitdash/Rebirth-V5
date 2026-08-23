"""Small validated, atomic CSV store for the Statics page."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import RLock

import pandas as pd

from rebirth.domain.s07_governance import load_config, load_thresholds
from rebirth.domain.s08_pnl import load_plsend_mapping
from rebirth.domain.s06_reporting import load_reported_underlying_mapping
from rebirth.domain.s01_schema import PORTFOLIO_CONFIG_REQUIRED_COLUMNS


DATA_DIR = Path(__file__).resolve().parents[3] / "data"

STATIC_FILE_LABELS: Mapping[str, str] = {
    "s01_readiness.csv": "Readiness Risks Today",
    "s02_checker.csv": "Not Ready Risk File Inventory",
    "s03_risk.csv": "All Risks",
    "s04_open.csv": "Market Open",
    "s05_current.csv": "Market Status",
    "s06_portfolios.csv": "Portfolio Mapping",
    "s07_thresholds.csv": "Top Thresholds",
    "s08_concerto.csv": "Concerto Mapping",
    "s09_reported.csv": "Reported Underlying Mapping",
}
WRITABLE_STATIC_FILES = (
    "s06_portfolios.csv",
    "s07_thresholds.csv",
    "s08_concerto.csv",
    "s09_reported.csv",
)
_EXPECTED_COLUMNS: Mapping[str, tuple[str, ...]] = {
    "s06_portfolios.csv": tuple(PORTFOLIO_CONFIG_REQUIRED_COLUMNS),
    "s07_thresholds.csv": ("Risk Type", "Risk Greek", "PL", "Risk", "dRisk"),
    "s08_concerto.csv": ("Risk Type", "Risk Greek", "ConcertoField"),
    "s09_reported.csv": (
        "Risk Type",
        "Risk Greek",
        "Underlying",
        "Reported Underlying",
    ),
}


class StaticDataStore:
    """Read approved fixtures and atomically replace governed editable files."""

    def __init__(self, root: str | Path = DATA_DIR) -> None:
        self._root = Path(root).expanduser().resolve()
        self._lock = RLock()

    @property
    def root(self) -> Path:
        return self._root

    def options(self, *, writable: bool = False) -> list[dict[str, str]]:
        allowed = WRITABLE_STATIC_FILES if writable else tuple(STATIC_FILE_LABELS)
        return [
            {"label": STATIC_FILE_LABELS[key], "value": key}
            for key in allowed
            if (self._root / key).is_file()
        ]

    def _path(self, file_key: object, *, writable: bool = False) -> Path:
        key = str(file_key)
        allowed = set(WRITABLE_STATIC_FILES) if writable else set(STATIC_FILE_LABELS)
        if key not in allowed or Path(key).name != key:
            raise ValueError("The selected static data file is not approved")
        path = (self._root / key).resolve()
        if path.parent != self._root:
            raise ValueError("The selected static data path is outside the data root")
        return path

    def read(self, file_key: object) -> pd.DataFrame:
        path = self._path(file_key)
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False)
        except (OSError, UnicodeError, pd.errors.ParserError) as exc:
            raise ValueError(f"Could not read {path.name}: {exc}") from exc

    @staticmethod
    def _records_frame(
        rows: object,
        columns: Sequence[object],
    ) -> pd.DataFrame:
        names = [str(column).strip() for column in columns]
        if (
            not names
            or any(not name for name in names)
            or len(names) != len(set(names))
        ):
            raise ValueError("Static data columns must be unique nonblank names")
        if not isinstance(rows, list) or any(
            not isinstance(row, Mapping) for row in rows
        ):
            raise ValueError("Static data rows must be table records")
        return pd.DataFrame.from_records(rows, columns=names).fillna("")

    def validate(
        self,
        file_key: object,
        rows: object,
        columns: Sequence[object],
    ) -> pd.DataFrame:
        key = str(file_key)
        self._path(key, writable=True)
        frame = self._records_frame(rows, columns)
        expected = list(_EXPECTED_COLUMNS[key])
        if list(frame.columns) != expected:
            raise ValueError(
                f"{STATIC_FILE_LABELS[key]} columns must be exactly {expected}"
            )
        if key == "s06_portfolios.csv":
            load_config(frame)
        elif key == "s07_thresholds.csv":
            load_thresholds(frame)
        elif key == "s08_concerto.csv":
            load_plsend_mapping(frame)
        else:
            load_reported_underlying_mapping(frame)
        return frame

    def write(
        self,
        file_key: object,
        rows: object,
        columns: Sequence[object],
    ) -> pd.DataFrame:
        key = str(file_key)
        validated = self.validate(key, rows, columns)
        destination = self._path(key, writable=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_name: str | None = None
        with self._lock:
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    newline="",
                    suffix=".csv.tmp",
                    prefix=f".{destination.stem}-",
                    dir=destination.parent,
                    delete=False,
                ) as handle:
                    temporary_name = handle.name
                    validated.to_csv(handle, index=False, lineterminator="\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_name, destination)
            except OSError as exc:
                raise ValueError(f"Could not save {destination.name}: {exc}") from exc
            finally:
                if temporary_name:
                    Path(temporary_name).unlink(missing_ok=True)
        return self.read(key)


__all__ = [
    "DATA_DIR",
    "STATIC_FILE_LABELS",
    "WRITABLE_STATIC_FILES",
    "StaticDataStore",
]
