"""Measure Rebirth V4.1 startup and lazy-history paths on checked-in scale data."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from time import perf_counter
from typing import Callable, TypeVar

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rebirth.domain.s01_schema import (  # noqa: E402
    PORTFOLIO_COLUMN,
    PORTFOLIO_METADATA_COLUMNS,
)
from rebirth.domain.s09_stock import STOCK_IDENTITY_COLUMNS  # noqa: E402
from rebirth.history import (  # noqa: E402
    HISTORY_HANDOFF_SCHEMA_VERSION,
    SQLPLHistoryRepository,
    ArchiveHistoryRepository,
    HistoryHandoff,
    HistoryIdentity,
    HistoryQuery,
)
from rebirth.services.s05_sources import build_production_refresh_manager  # noqa: E402
from rebirth.pages.stock.s02_history import SQLStockHistoryRepository  # noqa: E402
from rebirth.pages.risk.s06_explorertables import build_risk_table  # noqa: E402
from rebirth.pages.risk.s03_defaults import (  # noqa: E402
    default_risk_filter_payload,
)
from rebirth.ui.s02_aggregation import (  # noqa: E402
    apply_filters,
    default_open_rows,
    prepare_risk_data,
)


T = TypeVar("T")
ARCHIVE_ROOT = ROOT / "data" / "histo"


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    duration_ms: float
    budget_ms: float
    passed: bool
    rows: int | None = None
    dates: int | None = None
    portfolios: int | None = None


def _fresh_process_app_import(budget_ms: float = 2_000) -> BenchmarkResult:
    """Import and build ``app`` in a fresh interpreter with data-I/O auditing."""

    child_script = r"""
import json
import sys
from pathlib import Path
from time import perf_counter

root = Path.cwd().resolve()
data_root = (root / "data").resolve()
data_events = []
network_events = []

def under_data(value):
    try:
        return Path(value).resolve().is_relative_to(data_root)
    except (OSError, TypeError, ValueError):
        return False

def audit(event, args):
    if event in {"open", "os.listdir", "os.scandir"} and args and under_data(args[0]):
        data_events.append(event)
    elif event in {"socket.connect", "socket.connect_ex"}:
        network_events.append(event)

sys.addaudithook(audit)
started = perf_counter()
import app as application
duration_ms = (perf_counter() - started) * 1_000
payload = {
    "duration_ms": duration_ms,
    "data_events": data_events,
    "network_events": network_events,
    "app_built": application.app is not None and application.server is not None,
}
print("REBIRTH_BENCHMARK=" + json.dumps(payload, sort_keys=True))
"""
    environment = os.environ.copy()
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started = perf_counter()
    completed = subprocess.run(
        [sys.executable, "-c", child_script],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    duration_ms = round((perf_counter() - started) * 1_000, 3)
    marker = "REBIRTH_BENCHMARK="
    payload_line = next(
        (line for line in completed.stdout.splitlines() if line.startswith(marker)),
        None,
    )
    if completed.returncode or payload_line is None:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"fresh app import failed: {detail}")
    payload = json.loads(payload_line.removeprefix(marker))
    io_clean = not payload["data_events"] and not payload["network_events"]
    return BenchmarkResult(
        name="startup.import_app.fresh_process",
        duration_ms=duration_ms,
        budget_ms=budget_ms,
        passed=bool(payload["app_built"]) and io_clean and duration_ms <= budget_ms,
        rows=0,
        dates=0,
        portfolios=0,
    )


def _measure(
    name: str,
    budget_ms: float,
    operation: Callable[[], T],
    describe: Callable[[T], tuple[int | None, int | None, int | None]],
) -> BenchmarkResult:
    started = perf_counter()
    value = operation()
    duration_ms = round((perf_counter() - started) * 1_000, 3)
    rows, dates, portfolios = describe(value)
    return BenchmarkResult(
        name=name,
        duration_ms=duration_ms,
        budget_ms=budget_ms,
        passed=duration_ms <= budget_ms,
        rows=rows,
        dates=dates,
        portfolios=portfolios,
    )


def _first_row(file_name: str, columns: list[str]) -> dict[str, object]:
    latest = max(path for path in ARCHIVE_ROOT.iterdir() if path.is_dir())
    return pq.read_table(latest / file_name, columns=columns).slice(0, 1).to_pylist()[0]


def _scaled_dashboard_fixture(
    source: pd.DataFrame,
    *,
    rows: int = 100_000,
    portfolios: int = 500,
) -> pd.DataFrame:
    """Expand validated current rows for an interaction-only stress check."""

    if source.empty:
        raise ValueError("current dashboard fixture must not be empty")
    positions = np.arange(rows, dtype=np.int64)
    scaled = source.iloc[positions % len(source)].reset_index(drop=True).copy()
    portfolio_ids = positions % portfolios
    scaled[PORTFOLIO_COLUMN] = [
        f"FAKE_REPLACE_ME - BOOK_{value:04d}" for value in portfolio_ids
    ]
    reporting_values = {
        "Activity": [
            f"FAKE_REPLACE_ME - Activity {value % 3 + 1}" for value in positions
        ],
        "SignoffGroup": [
            f"FAKE_REPLACE_ME - SOG_{value % 20 + 1:02d}" for value in positions
        ],
        "Category": [
            f"FAKE_REPLACE_ME - Category {value % 12 + 1}" for value in positions
        ],
        "Sub Category": [
            f"FAKE_REPLACE_ME - Sub Category {value % 30 + 1}" for value in positions
        ],
    }
    for column in PORTFOLIO_METADATA_COLUMNS:
        if column in reporting_values:
            scaled[column] = reporting_values[column]
    return scaled


def run_benchmarks() -> list[BenchmarkResult]:
    """Run safe read-only benchmarks against the full 262-date fixture."""

    manager = build_production_refresh_manager(stage_delays={"risk_product": 0.0})
    results = [
        _fresh_process_app_import(),
        _measure(
            "spot.refresh",
            2_000,
            lambda: manager.refresh(
                force_risk=True,
                reason="v4-benchmark",
                copy_result=False,
            ),
            lambda _value: (
                len(manager.read_frame("dashboard_frame").frame),
                None,
                manager.read_frame("dashboard_frame").frame[PORTFOLIO_COLUMN].nunique(),
            ),
        ),
    ]

    current = manager.read_frame("dashboard_frame").frame
    scaled = _scaled_dashboard_fixture(current)
    prepared_holder: dict[str, pd.DataFrame] = {}

    def prepare_scaled() -> pd.DataFrame:
        prepared_holder["frame"] = prepare_risk_data(scaled)
        return prepared_holder["frame"]

    prepared = prepare_scaled()
    default_filters = default_risk_filter_payload(prepared)

    def filter_scaled() -> pd.DataFrame:
        return apply_filters(
            prepared,
            risk_types=None,
            splits=None,
            dimension_filters=default_filters,
        )

    filtered = filter_scaled()
    first_risk_type = str(filtered["risk type"].iloc[0])
    table_frame = filtered.loc[filtered["risk type"].eq(first_risk_type)]
    results.extend(
        [
            _measure(
                "interaction.prepare_100k",
                2_500,
                prepare_scaled,
                lambda value: (
                    len(value),
                    None,
                    value["portfolio"].nunique(),
                ),
            ),
            _measure(
                "interaction.default_filter_100k",
                500,
                filter_scaled,
                lambda value: (
                    len(value),
                    None,
                    value["portfolio"].nunique(),
                ),
            ),
            _measure(
                "interaction.cross_render_100k",
                1_500,
                lambda: build_risk_table(
                    table_frame,
                    expanded_metrics=[],
                    open_rows=default_open_rows(table_frame, first_risk_type),
                ),
                lambda _value: (
                    len(table_frame),
                    None,
                    table_frame["portfolio"].nunique(),
                ),
            ),
        ]
    )

    risk_row = _first_row(
        "risk.parquet",
        ["Source Type", "Risk Type", "Risk Greek", "Underlying"],
    )
    market_row = _first_row(
        "market.parquet",
        ["Source Type", "Risk Type", "Risk Greek", "Underlying"],
    )
    stock_row = _first_row("stock.parquet", list(STOCK_IDENTITY_COLUMNS))
    history = ArchiveHistoryRepository(ARCHIVE_ROOT)
    stock_history = SQLStockHistoryRepository(ARCHIVE_ROOT)

    def history_query(kind: str, row: dict[str, object], metric: str):
        handoff = HistoryHandoff(
            schema_version=HISTORY_HANDOFF_SCHEMA_VERSION,
            kind=kind,
            identity=HistoryIdentity(
                source_types=(str(row["Source Type"]),),
                risk_type=str(row["Risk Type"]),
                risk_greek=str(row["Risk Greek"]),
                underlying=str(row["Underlying"]),
            ),
            metric=metric,
            source_revision=262,
            snapshot_date=date(2026, 8, 21),
        )
        return history.read(HistoryQuery(handoff=handoff, period="1y"))

    results.extend(
        [
            _measure(
                "history.risk.first",
                2_500,
                lambda: history_query("risk", risk_row, "risk"),
                lambda value: (len(value.raw_rows), len(value.dates), None),
            ),
            _measure(
                "history.market.first",
                2_000,
                lambda: history_query("market", market_row, "current"),
                lambda value: (len(value.raw_rows), len(value.dates), None),
            ),
            _measure(
                "history.stock.first",
                2_500,
                lambda: stock_history.rows(
                    {key: str(stock_row[key]) for key in STOCK_IDENTITY_COLUMNS},
                    "2025-08-21",
                    "2026-08-21",
                ),
                lambda value: (len(value), value["Stock Date"].nunique(), None),
            ),
        ]
    )

    pnl = SQLPLHistoryRepository(ARCHIVE_ROOT)
    results.append(
        _measure(
            "history.pnl.overview.first",
            3_500,
            pnl.risk_summary,
            lambda value: (len(value.summary), None, None),
        )
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--enforce",
        action="store_true",
        help="Return a failing exit code when any measured budget is exceeded.",
    )
    args = parser.parse_args()
    results = run_benchmarks()
    print(json.dumps([asdict(result) for result in results], indent=2))
    return int(args.enforce and not all(result.passed for result in results))


if __name__ == "__main__":
    raise SystemExit(main())
