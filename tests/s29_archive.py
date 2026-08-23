"""Official flat Risk archive, projection, and scheduler contracts."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import duckdb
import pandas as pd
import pytest

from rebirth.history import s03_io as archive_io_module
from rebirth.history import s04_queries as archive_query_module
from rebirth.history import (
    PL_HISTORY_DAILY_PREDICT,
    PL_HISTORY_DEPTH,
    PL_HISTORY_LABEL,
    PL_HISTORY_MAX_RAW_ROWS,
    PL_HISTORY_MAX_SERIES_ROWS,
    PL_HISTORY_MTD_COLOSSUS,
    PL_HISTORY_MTD_PREDICT,
    PL_HISTORY_PATH,
    PL_HISTORY_SUMMARY_COLUMNS,
    PL_HISTORY_YTD_COLOSSUS,
    PL_HISTORY_YTD_PREDICT,
    PL_RISK_SUMMARY_COLUMNS,
    PL_RISK_SUMMARY_CURRENT,
    PL_RISK_SUMMARY_MTD,
    PL_RISK_SUMMARY_PATH,
    PL_RISK_SUMMARY_YTD,
    SQLPLHistoryRepository,
    open_history_database,
)
from rebirth.domain.s08_pnl import (
    ACTIVITY,
    CATEGORY,
    COLOSSUS_TYPE,
    HISTORY_FILE_COLUMNS,
    HISTORY_MAPPING_STATUS,
    HISTORY_IDENTITY_COLUMNS,
    HISTORY_TYPE,
    PL_HISTORY_COLUMNS,
    PL_HISTORY_DAILY_PERIOD,
    PL_HISTORY_MTD_PERIOD,
    PL_HISTORY_PERIOD,
    PL_HISTORY_YTD_PERIOD,
    PORTFOLIO,
    PREDICT_TYPE,
    RISK_TYPE,
    SIGNOFF_GROUP,
    SUB_CATEGORY,
    pl_history_period_values,
    select_pl_history_series,
)
from rebirth.domain.s01_schema import UNMAPPED_VALUE
from rebirth.history import (
    ARCHIVE_FILE_NAMES,
    ARCHIVE_SCHEMA_VERSION,
    COLOSSUS_FILE_NAME,
    COLOSSUS_COLUMNS,
    MARKET_ARCHIVE_COLUMNS,
    MARKET_FILE_NAME,
    MARKET_HISTORY_COLUMNS,
    RISK_FILE_NAME,
    STOCK_ARCHIVE_FILE_NAMES,
    STOCK_FILE_NAME,
    ArchiveResult,
    RiskArchive,
    RiskArchiveValidationError,
    archive_from_manager,
    archive_official_snapshot,
    list_completed_market_dates,
    load_market_history_for_identity,
    load_risk_archive,
    load_risk_history_for_identity,
    load_stock_archive_frame,
    load_shared_pl_history,
    list_completed_v4_archive_days,
    project_archive_to_pl_history,
    validate_market_archive_frame,
)
from rebirth.domain.s09_stock import STOCK_COLUMNS, STOCK_IDENTITY_COLUMNS
from tools.s02_archive import (
    DEFAULT_ARCHIVE_ROOT,
    resolve_archive_root,
    run_scheduled_archive,
)


def _risk() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Source Type": "ir/delta",
                "Portfolio": "BOOK-A",
                "Underlying": "EUR",
                "Risk Type": "IR",
                "Risk Greek": "Delta",
                "Product": "XVA",
                "Activity": "Rates",
                "SignoffGroup": "SOG-A",
                "Category": "Core",
                "Sub Category": "IR",
                "Tenor Swap": "1Y",
                "PL": 10.0,
                "Risk": 100.0,
                "dRisk": 1.0,
            },
            {
                "Source Type": "ir/delta",
                "Portfolio": "BOOK-A",
                "Underlying": "EUR",
                "Risk Type": "IR",
                "Risk Greek": "Delta",
                "Product": "XVA",
                "Activity": "Rates",
                "SignoffGroup": "SOG-A",
                "Category": "Core",
                "Sub Category": "IR",
                "Tenor Swap": "5Y",
                "PL": 15.0,
                "Risk": 200.0,
                "dRisk": 2.0,
            },
            {
                "Source Type": "fx/delta",
                "Portfolio": "BOOK-B",
                "Underlying": "EUR/USD",
                "Risk Type": "FX",
                "Risk Greek": "Delta",
                "Product": "Hedges",
                "Activity": "FX",
                "SignoffGroup": "SOG-B",
                "Category": "Core",
                "Sub Category": "FX",
                "Tenor Swap": "Spot",
                "PL": -4.0,
                "Risk": -40.0,
                "dRisk": -0.4,
            },
        ]
    )


def _colossus() -> pd.DataFrame:
    return pd.DataFrame(
        [
            ["BOOK-A", "EUR", "IR", "Delta", 24.0],
            ["BOOK-B", "EUR/USD", "FX", "Delta", -3.5],
        ],
        columns=list(COLOSSUS_COLUMNS),
    )


def _market(market_date: str = "2026-08-14", *, shift: float = 0.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            [
                "ir/delta",
                "IR",
                "Delta",
                "EUR",
                "1Y",
                "N/A",
                0,
                pd.NA,
                market_date,
                4.0,
                4.1 + shift,
                0.1 + shift,
                "OFFICIAL",
                "Available",
            ],
            [
                "ir/delta",
                "IR",
                "Delta",
                "EUR",
                "5Y",
                "N/A",
                1,
                pd.NA,
                market_date,
                4.2,
                4.3 + shift,
                0.1 + shift,
                "OFFICIAL",
                "Available",
            ],
            [
                "fx/delta",
                "FX",
                "Delta",
                "EUR/USD",
                "Spot",
                "N/A",
                pd.NA,
                pd.NA,
                market_date,
                1.1,
                1.11 + shift,
                0.01 + shift,
                "OFFICIAL",
                "Available",
            ],
        ],
        columns=list(MARKET_ARCHIVE_COLUMNS),
    )


def _stock() -> pd.DataFrame:
    return pd.DataFrame(
        [["CRDS-1", "CPTY-1", "BOOK-A", "BOND-1", "EUR", 10.0, 125.0]],
        columns=list(STOCK_COLUMNS),
    )


def _snapshot(
    *,
    market_status: str = "OFFICIAL",
    market_date: str = "2026-08-14",
    system_date: str = "2026-08-14",
    errors: tuple[str, ...] = (),
    risk: pd.DataFrame | None = None,
    market: pd.DataFrame | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        revision=7,
        refreshed_at=datetime(2026, 8, 14, 22, 5, tzinfo=timezone.utc),
        market_date=pd.Timestamp(market_date),
        system_date=pd.Timestamp(system_date),
        market_status=market_status,
        errors=errors,
        dashboard_frame=_risk() if risk is None else risk,
        market_frame=_market(market_date) if market is None else market,
        risk_dates={
            "fx/delta": pd.Timestamp(market_date),
            "ir/delta": pd.Timestamp(market_date) - pd.Timedelta(days=1),
        },
    )


def _write_legacy_archive(
    root: Path,
    schema_version: int,
    *,
    include_stock: bool = False,
) -> Path:
    if schema_version not in {1, 2, 3}:
        raise AssertionError("legacy test archive version must be 1, 2, or 3")
    leaf = root / "2026-08-14"
    leaf.mkdir(parents=True)
    frames = {
        "risk.csv": _risk(),
        "colossus.csv": _colossus(),
    }
    if schema_version >= 2:
        frames["market.csv"] = _market()
    if include_stock:
        if schema_version != 3:
            raise AssertionError("only schema v3 CSV fixtures may include Stock")
        frames["stock.csv"] = _stock()
    for file_name, frame in frames.items():
        frame.to_csv(leaf / file_name, index=False, lineterminator="\n")
    manifest: dict[str, object] = {
        "schema_version": schema_version,
        "market_date": "2026-08-14",
        "market_status": "OFFICIAL",
        "revision": 7,
        "refreshed_at": "2026-08-14T22:05:00+00:00",
        "risk_rows": len(frames["risk.csv"]),
        "colossus_rows": len(frames["colossus.csv"]),
        "risk_columns": frames["risk.csv"].columns.tolist(),
        "colossus_columns": list(COLOSSUS_COLUMNS),
        "sha256": {
            file_name: hashlib.sha256((leaf / file_name).read_bytes()).hexdigest()
            for file_name in frames
        },
    }
    if schema_version >= 2:
        manifest["market_rows"] = len(frames["market.csv"])
        manifest["market_columns"] = list(MARKET_ARCHIVE_COLUMNS)
    if schema_version == 3:
        manifest["risk_dates"] = {
            "fx/delta": "2026-08-14",
            "ir/delta": "2026-08-13",
        }
    if include_stock:
        manifest["fixture"] = "deterministic-rebirth-v3"
        manifest["stock_date"] = "2026-08-14"
        manifest["stock_rows"] = len(frames["stock.csv"])
        manifest["stock_columns"] = list(STOCK_COLUMNS)
    (leaf / "_SUCCESS").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return leaf


def test_official_archive_is_atomic_complete_and_idempotent(tmp_path: Path) -> None:
    calls: list[pd.Timestamp] = []

    def load_colossus(market_date: pd.Timestamp) -> pd.DataFrame:
        calls.append(market_date)
        return _colossus()

    first = archive_official_snapshot(_snapshot(), load_colossus, tmp_path)

    assert first == ArchiveResult(
        status="archived",
        reason="Official Risk Explorer and Colossus P&L archived.",
        market_date="2026-08-14",
        path=tmp_path.resolve() / "2026-08-14",
        risk_rows=3,
        colossus_rows=2,
        market_rows=3,
    )
    assert calls == [pd.Timestamp("2026-08-14")]
    assert {path.name for path in first.path.iterdir()} == set(ARCHIVE_FILE_NAMES)
    assert list_completed_market_dates(tmp_path) == ("2026-08-14",)

    loaded = load_risk_archive(tmp_path, "2026-08-14")
    assert loaded.market_date == "2026-08-14"
    assert loaded.risk.columns.tolist() == _risk().columns.tolist()
    assert loaded.risk["Portfolio"].tolist() == _risk()["Portfolio"].tolist()
    pd.testing.assert_frame_equal(loaded.colossus, _colossus())
    pd.testing.assert_frame_equal(
        loaded.market, validate_market_archive_frame(_market())
    )

    second = archive_official_snapshot(
        _snapshot(),
        lambda _date: (_ for _ in ()).throw(AssertionError("must not reload")),
        tmp_path,
    )
    assert second.status == "already_archived"
    assert second.risk_rows == 3
    assert second.colossus_rows == 2
    assert second.market_rows == 3
    assert calls == [pd.Timestamp("2026-08-14")]


def test_sunday_system_date_accepts_its_resolved_friday_market_date(
    tmp_path: Path,
) -> None:
    result = archive_official_snapshot(
        _snapshot(market_date="2026-08-14", system_date="2026-08-16"),
        lambda _date: _colossus(),
        tmp_path,
    )

    assert result.status == "archived"
    assert result.market_date == "2026-08-14"


def test_new_official_archive_manifest_covers_market_parquet(tmp_path: Path) -> None:
    result = archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    manifest = json.loads((result.path / "_SUCCESS").read_text(encoding="utf-8"))

    assert manifest["schema_version"] == ARCHIVE_SCHEMA_VERSION
    assert manifest["market_rows"] == 3
    assert manifest["market_columns"] == list(MARKET_ARCHIVE_COLUMNS)
    assert manifest["revision"] == 7
    assert manifest["risk_dates"] == {
        "fx/delta": "2026-08-14",
        "ir/delta": "2026-08-13",
    }
    assert MARKET_FILE_NAME in manifest["sha256"]
    assert result.market_rows == 3
    loaded = load_risk_archive(tmp_path, result.market_date)
    assert loaded.schema_version == ARCHIVE_SCHEMA_VERSION
    assert loaded.revision == 7
    assert dict(loaded.risk_dates) == manifest["risk_dates"]


def test_duckdb_history_uses_only_explicit_completed_v4_leaves(
    tmp_path: Path,
) -> None:
    result = archive_official_snapshot(
        _snapshot(),
        lambda _date: _colossus(),
        tmp_path,
    )
    partial = tmp_path / "2026-08-15"
    partial.mkdir()
    (partial / RISK_FILE_NAME).write_bytes((result.path / RISK_FILE_NAME).read_bytes())

    days = list_completed_v4_archive_days(tmp_path)

    assert [day.snapshot_date for day in days] == ["2026-08-14"]
    assert days[0].revision == 7
    assert dict(days[0].risk_dates) == {
        "fx/delta": "2026-08-14",
        "ir/delta": "2026-08-13",
    }
    with open_history_database(tmp_path) as database:
        views = {
            row[0]
            for row in database.execute(
                "SELECT table_name FROM information_schema.views "
                "WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert {
            "archive_days",
            "risk_history",
            "market_history",
            "colossus_history",
            "stock_history",
        } <= views
        assert database.execute("SELECT count(*) FROM archive_days").fetchone() == (1,)
        assert database.execute("SELECT count(*) FROM risk_history").fetchone() == (
            len(_risk()),
        )
        assert database.execute("SELECT count(*) FROM market_history").fetchone() == (
            len(_market()),
        )
        assert database.execute("SELECT count(*) FROM colossus_history").fetchone() == (
            len(_colossus()),
        )
        assert database.execute("SELECT count(*) FROM stock_history").fetchone() == (0,)
        assert database.execute(
            'SELECT DISTINCT "Source Type", CAST("Risk Date" AS VARCHAR) '
            'FROM risk_history ORDER BY "Source Type"'
        ).fetchall() == [
            ("fx/delta", "2026-08-14"),
            ("ir/delta", "2026-08-13"),
        ]
    assert not list(tmp_path.glob("*.duckdb"))


def test_duckdb_history_rejects_completed_legacy_leaves(tmp_path: Path) -> None:
    _write_legacy_archive(tmp_path, 3, include_stock=True)

    with pytest.raises(RiskArchiveValidationError, match="schema-v4 Parquet"):
        open_history_database(tmp_path)


def test_sql_pl_repository_matches_projected_history_and_stays_bounded(
    tmp_path: Path,
) -> None:
    archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    second_risk = _risk().copy(deep=True)
    second_risk.loc[0, "PL"] = pd.NA
    second_colossus = pd.concat(
        [
            _colossus(),
            pd.DataFrame(
                [["BOOK-C", "GBP", "IR", "Delta", 5.0]],
                columns=list(COLOSSUS_COLUMNS),
            ),
        ],
        ignore_index=True,
    )
    archive_official_snapshot(
        _snapshot(
            market_date="2026-08-17",
            system_date="2026-08-17",
            risk=second_risk,
            market=_market("2026-08-17"),
        ),
        lambda _date: second_colossus,
        tmp_path,
    )
    expected = pd.concat(
        [
            project_archive_to_pl_history(load_risk_archive(tmp_path, market_date))
            for market_date in ("2026-08-14", "2026-08-17")
        ],
        ignore_index=True,
    )
    repository = SQLPLHistoryRepository(tmp_path)

    hierarchy = repository.hierarchy()
    assert hierarchy.row_count == len(expected)
    assert hierarchy.date_count == 2
    assert (hierarchy.minimum_date, hierarchy.maximum_date) == (
        "2026-08-14",
        "2026-08-17",
    )
    assert hierarchy.unmapped_rows == int(
        expected[HISTORY_MAPPING_STATUS].eq("Unmapped").sum()
    )
    assert set(
        hierarchy.summary.loc[
            hierarchy.summary[PL_HISTORY_DEPTH].eq(1), PL_HISTORY_LABEL
        ]
    ) == set(expected[SIGNOFF_GROUP])
    first_signoff = str(expected[SIGNOFF_GROUP].iloc[0])
    sql_summary = repository.hierarchy(open_paths=[(first_signoff,)]).summary

    def assert_summary_contract(
        summary: pd.DataFrame,
        source: pd.DataFrame,
        expected_paths: set[tuple[str, ...]],
    ) -> None:
        assert list(summary.columns) == list(PL_HISTORY_SUMMARY_COLUMNS)
        assert {tuple(path) for path in summary[PL_HISTORY_PATH]} == expected_paths
        latest = pd.to_datetime(source["Market Date"], errors="raise").max()
        metric_keys = {
            PL_HISTORY_DAILY_PREDICT: (PL_HISTORY_DAILY_PERIOD, PREDICT_TYPE),
            PL_HISTORY_MTD_COLOSSUS: (PL_HISTORY_MTD_PERIOD, COLOSSUS_TYPE),
            PL_HISTORY_MTD_PREDICT: (PL_HISTORY_MTD_PERIOD, PREDICT_TYPE),
            PL_HISTORY_YTD_COLOSSUS: (PL_HISTORY_YTD_PERIOD, COLOSSUS_TYPE),
            PL_HISTORY_YTD_PREDICT: (PL_HISTORY_YTD_PERIOD, PREDICT_TYPE),
        }
        for _, row in summary.iterrows():
            path = tuple(row[PL_HISTORY_PATH])
            scope = source
            for column, value in zip(
                HISTORY_IDENTITY_COLUMNS[: len(path)], path, strict=True
            ):
                scope = scope.loc[scope[column].astype(str).eq(value)]
            periods = pl_history_period_values(scope, (), as_of=latest)
            lookup = {
                (record[PL_HISTORY_PERIOD], record[HISTORY_TYPE]): record["PL"]
                for record in periods.to_dict("records")
            }
            for column, key in metric_keys.items():
                expected_value = lookup.get(key)
                if expected_value is None:
                    assert pd.isna(row[column])
                else:
                    assert row[column] == pytest.approx(expected_value)

    first_level_paths = {
        (),
        *((str(value),) for value in expected[SIGNOFF_GROUP].drop_duplicates()),
    }
    opened_paths = {
        *first_level_paths,
        *(
            (first_signoff, str(value))
            for value in expected.loc[
                expected[SIGNOFF_GROUP].eq(first_signoff), RISK_TYPE
            ].drop_duplicates()
        ),
    }
    assert_summary_contract(hierarchy.summary, expected, first_level_paths)
    assert_summary_contract(sql_summary, expected, opened_paths)

    risk_summary = repository.risk_summary()
    assert risk_summary.as_of_date == "2026-08-17"
    assert list(risk_summary.summary.columns) == list(PL_RISK_SUMMARY_COLUMNS)
    assert {tuple(path) for path in risk_summary.summary[PL_RISK_SUMMARY_PATH]} >= {
        (),
        ("IR",),
        ("IR", "Delta"),
        ("IR", "Delta", "EUR"),
    }
    fx_delta = risk_summary.summary.loc[
        risk_summary.summary[PL_RISK_SUMMARY_PATH].map(
            lambda path: tuple(path) == ("FX", "Delta", "EUR/USD")
        )
    ].iloc[0]
    latest = expected.loc[
        pd.to_datetime(expected["Market Date"]).eq(pd.Timestamp("2026-08-17"))
        & expected[HISTORY_TYPE].eq(PREDICT_TYPE)
        & expected["Risk Type"].eq("FX")
        & expected["Risk Greek"].eq("Delta")
        & expected["Underlying"].eq("EUR/USD"),
        "PL",
    ].sum(min_count=1)
    official = expected.loc[
        expected[HISTORY_TYPE].eq(COLOSSUS_TYPE)
        & expected["Risk Type"].eq("FX")
        & expected["Risk Greek"].eq("Delta")
        & expected["Underlying"].eq("EUR/USD"),
        "PL",
    ].sum(min_count=1)
    assert fx_delta[PL_RISK_SUMMARY_CURRENT] == pytest.approx(latest)
    assert fx_delta[PL_RISK_SUMMARY_MTD] == pytest.approx(official)
    assert fx_delta[PL_RISK_SUMMARY_YTD] == pytest.approx(official)
    cached = repository.risk_summary()
    pd.testing.assert_frame_equal(cached.summary, risk_summary.summary)
    selected_activity = str(expected[ACTIVITY].iloc[0])
    filtered_expected = expected.loc[expected[ACTIVITY].eq(selected_activity)]
    filtered_hierarchy = repository.hierarchy(filters={ACTIVITY: [selected_activity]})
    assert_summary_contract(
        filtered_hierarchy.summary,
        filtered_expected,
        {
            (),
            *(
                (str(value),)
                for value in filtered_expected[SIGNOFF_GROUP].drop_duplicates()
            ),
        },
    )
    assert filtered_hierarchy.row_count == len(filtered_expected)

    paths = expected.loc[:, list(HISTORY_IDENTITY_COLUMNS)].drop_duplicates()
    for raw_path in paths.itertuples(index=False, name=None):
        path = tuple(str(value) for value in raw_path)
        actual_series = repository.series(path=path).series
        expected_series = select_pl_history_series(expected, path)
        pd.testing.assert_frame_equal(
            actual_series,
            expected_series,
            check_dtype=False,
        )

    total = repository.series().series
    pd.testing.assert_frame_equal(
        total,
        select_pl_history_series(expected),
        check_dtype=False,
    )
    assert len(total) <= PL_HISTORY_MAX_SERIES_ROWS
    assert set(total["Market Date"]) == {"2026-08-14", "2026-08-17"}
    assert "2026-08-15" not in set(total["Market Date"])

    raw = repository.raw_rows()
    assert list(raw.rows.columns) == list(PL_HISTORY_COLUMNS)
    assert raw.row_count == len(expected)
    assert len(raw.rows) <= PL_HISTORY_MAX_RAW_ROWS
    assert raw.pl_total == pytest.approx(expected["PL"].sum())
    raw_daily = (
        raw.rows.groupby(["Market Date", HISTORY_TYPE], as_index=False)["PL"]
        .sum()
        .sort_values(["Market Date", HISTORY_TYPE], kind="stable")
        .reset_index(drop=True)
    )
    total_daily = total.sort_values(
        ["Market Date", HISTORY_TYPE], kind="stable"
    ).reset_index(drop=True)
    pd.testing.assert_frame_equal(raw_daily, total_daily, check_dtype=False)

    registered = {
        row[0]
        for row in repository._connection.execute(
            "SELECT table_name FROM information_schema.tables"
        ).fetchall()
    }
    assert {"_risk_files", "_colossus_files"} <= registered
    assert {
        "_market_files",
        "_stock_files",
        "_pl_fact",
        "_pl_identity",
        "_pl_projection",
    }.isdisjoint(registered)

    first_connection = repository._connection
    assert first_connection is not None
    repository.clear()
    assert repository._connection is None
    with pytest.raises(duckdb.ConnectionException, match="closed"):
        first_connection.execute("SELECT 1")


def test_sql_pl_repository_caps_memory_and_cleans_os_spill_directory(
    tmp_path: Path,
) -> None:
    archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    repository = SQLPLHistoryRepository(tmp_path)

    repository.hierarchy()

    connection = repository._connection
    temporary = repository._temporary_directory
    assert connection is not None
    assert temporary is not None
    memory_limit, threads, preserve_order, configured_temp = connection.execute(
        """SELECT current_setting('memory_limit'), current_setting('threads'),
                  current_setting('preserve_insertion_order'),
                  current_setting('temp_directory')"""
    ).fetchone()
    amount, unit = str(memory_limit).split()
    memory_bytes = float(amount) * {"MiB": 1024**2, "MB": 1000**2}[unit]
    spill_directory = Path(temporary.name).resolve()
    repository_root = Path(__file__).resolve().parents[1]
    assert memory_bytes == pytest.approx(384_000_000, abs=1024**2)
    assert threads == 2
    assert preserve_order is False
    assert configured_temp.replace("\\\\", "\\") == str(spill_directory)
    assert repository_root not in spill_directory.parents
    sentinel = spill_directory / "cleanup-proof"
    sentinel.write_text("temporary", encoding="utf-8")

    repository.clear()

    assert not spill_directory.exists()
    assert repository._connection is None
    assert repository._temporary_directory is None


def test_v4_parquet_bytes_and_zstd_encoding_are_deterministic(tmp_path: Path) -> None:
    first = archive_official_snapshot(
        _snapshot(),
        lambda _date: _colossus(),
        tmp_path / "first",
    )
    second = archive_official_snapshot(
        _snapshot(),
        lambda _date: _colossus(),
        tmp_path / "second",
    )

    for file_name in (RISK_FILE_NAME, COLOSSUS_FILE_NAME, MARKET_FILE_NAME):
        first_path = first.path / file_name
        second_path = second.path / file_name
        assert first_path.read_bytes() == second_path.read_bytes()
        parquet = archive_io_module.pq.ParquetFile(first_path)
        compressions = {
            parquet.metadata.row_group(group).column(column).compression
            for group in range(parquet.metadata.num_row_groups)
            for column in range(parquet.metadata.row_group(group).num_columns)
        }
        assert compressions == {"ZSTD"}


def test_v4_writer_rejects_noncanonical_risk_date_keys(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.risk_dates = {
        "fx/delta": pd.Timestamp("2026-08-14"),
        " ir/delta ": pd.Timestamp("2026-08-13"),
    }

    with pytest.raises(RiskArchiveValidationError, match="keys must be nonblank"):
        archive_official_snapshot(snapshot, lambda _date: _colossus(), tmp_path)


def test_v4_marker_rejects_boolean_schema_and_invalid_financial_metadata(
    tmp_path: Path,
) -> None:
    result = archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    marker = result.path / "_SUCCESS"
    manifest = json.loads(marker.read_text(encoding="utf-8"))

    manifest["schema_version"] = True
    marker.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RiskArchiveValidationError, match="unsupported schema"):
        load_risk_archive(tmp_path, result.market_date)

    manifest["schema_version"] = ARCHIVE_SCHEMA_VERSION
    manifest["revision"] = True
    marker.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RiskArchiveValidationError, match="non-negative integer"):
        load_risk_archive(tmp_path, result.market_date)

    manifest["revision"] = 7
    manifest["risk_dates"]["ir/delta"] = "2026-02-30"
    marker.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RiskArchiveValidationError, match="ISO YYYY-MM-DD"):
        load_risk_archive(tmp_path, result.market_date)


def test_v4_reader_checks_parquet_metadata_against_manifest(tmp_path: Path) -> None:
    result = archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    marker = result.path / "_SUCCESS"
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    manifest["risk_rows"] += 1
    marker.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RiskArchiveValidationError, match="Parquet archive row count"):
        load_risk_archive(tmp_path, result.market_date)


def test_writer_propagates_only_present_bounded_fixture_tag(tmp_path: Path) -> None:
    snapshot = _snapshot()
    snapshot.fixture = "deterministic-rebirth-v4"
    snapshot.stock_frame = _stock()

    result = archive_official_snapshot(snapshot, lambda _date: _colossus(), tmp_path)
    manifest = json.loads((result.path / "_SUCCESS").read_text(encoding="utf-8"))

    assert manifest["fixture"] == "deterministic-rebirth-v4"
    assert manifest["stock_date"] == "2026-08-14"
    assert manifest["stock_rows"] == 1
    assert manifest["stock_columns"] == list(STOCK_COLUMNS)
    assert STOCK_FILE_NAME in manifest["sha256"]
    assert {path.name for path in result.path.iterdir()} == set(
        STOCK_ARCHIVE_FILE_NAMES
    )
    assert load_risk_archive(tmp_path, result.market_date).stock_rows == 1
    pd.testing.assert_frame_equal(
        load_stock_archive_frame(tmp_path, result.market_date),
        _stock(),
        check_dtype=False,
    )


def test_stock_extension_is_all_or_nothing_and_rejects_duplicate_identity(
    tmp_path: Path,
) -> None:
    snapshot = _snapshot()
    snapshot.stock_frame = pd.concat([_stock(), _stock()], ignore_index=True)
    with pytest.raises(RiskArchiveValidationError, match="duplicate Stock identities"):
        archive_official_snapshot(snapshot, lambda _date: _colossus(), tmp_path)

    snapshot.stock_frame = _stock()
    snapshot.stock_date = pd.Timestamp("2026-08-13")
    with pytest.raises(RiskArchiveValidationError, match="must match"):
        archive_official_snapshot(snapshot, lambda _date: _colossus(), tmp_path)


def test_specialized_stock_reader_avoids_generic_frame_materialization(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot = _snapshot()
    snapshot.stock_frame = _stock()
    archive_official_snapshot(snapshot, lambda _date: _colossus(), tmp_path)
    archive_io_module._load_stock_leaf_cached.cache_clear()
    original_read_table = archive_io_module.pq.read_table
    stock_reads = 0

    def counted_read_table(source, *args, **kwargs):
        nonlocal stock_reads
        if Path(source).name == STOCK_FILE_NAME:
            stock_reads += 1
        return original_read_table(source, *args, **kwargs)

    monkeypatch.setattr(archive_io_module.pq, "read_table", counted_read_table)

    assert load_risk_archive(tmp_path, "2026-08-14").stock_rows == 1
    assert stock_reads == 0
    assert len(load_stock_archive_frame(tmp_path, "2026-08-14")) == 1
    assert stock_reads == 1


def test_stock_identity_query_pushes_exact_parquet_predicate(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot = _snapshot()
    snapshot.stock_frame = pd.concat(
        [
            _stock(),
            _stock().assign(CRDS="CRDS-2", Instrument="BOND-2"),
        ],
        ignore_index=True,
    )
    archive_official_snapshot(snapshot, lambda _date: _colossus(), tmp_path)
    archive_io_module._load_stock_leaf_cached.cache_clear()
    original_read_table = archive_io_module.pq.read_table
    stock_filters: list[object] = []

    def counted_read_table(source, *args, **kwargs):
        if Path(source).name == STOCK_FILE_NAME:
            stock_filters.append(kwargs.get("filters"))
        return original_read_table(source, *args, **kwargs)

    monkeypatch.setattr(archive_io_module.pq, "read_table", counted_read_table)
    identity = {
        column: str(snapshot.stock_frame.iloc[0][column])
        for column in STOCK_IDENTITY_COLUMNS
    }

    selected = load_stock_archive_frame(
        tmp_path,
        "2026-08-14",
        identity=identity,
    )
    missing = load_stock_archive_frame(
        tmp_path,
        "2026-08-14",
        identity={**identity, "CRDS": "missing"},
    )

    assert selected["CRDS"].tolist() == ["CRDS-1"]
    assert list(missing.columns) == list(STOCK_COLUMNS)
    assert missing.empty
    assert stock_filters == [
        [(column, "==", identity[column]) for column in STOCK_IDENTITY_COLUMNS],
        [
            (column, "==", "missing" if column == "CRDS" else identity[column])
            for column in STOCK_IDENTITY_COLUMNS
        ],
    ]


def test_schema_one_official_archive_without_optional_market_remains_readable(
    tmp_path: Path,
) -> None:
    leaf = _write_legacy_archive(tmp_path, 1)

    archive = load_risk_archive(tmp_path, leaf.name)
    market_history = load_market_history_for_identity(tmp_path, "IR", "Delta", "EUR")

    assert archive.market is None
    assert market_history.empty
    assert list(market_history.columns) == list(MARKET_HISTORY_COLUMNS)
    assert list_completed_market_dates(tmp_path) == ("2026-08-14",)


def test_schema_one_cannot_be_mislabeled_with_market_metadata(tmp_path: Path) -> None:
    leaf = _write_legacy_archive(tmp_path, 1)
    marker = leaf / "_SUCCESS"
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    manifest["market_rows"] = 1
    manifest["market_columns"] = list(MARKET_ARCHIVE_COLUMNS)
    manifest["sha256"]["market.csv"] = "0" * 64
    marker.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RiskArchiveValidationError, match="must not declare Market"):
        load_risk_archive(tmp_path, leaf.name)


@pytest.mark.parametrize(
    ("schema_version", "include_stock"),
    ((2, False), (3, False), (3, True)),
)
def test_schema_two_and_three_csv_contracts_remain_fully_readable(
    tmp_path: Path,
    schema_version: int,
    include_stock: bool,
) -> None:
    leaf = _write_legacy_archive(
        tmp_path,
        schema_version,
        include_stock=include_stock,
    )

    archive = load_risk_archive(tmp_path, leaf.name)

    assert archive.schema_version == schema_version
    pd.testing.assert_frame_equal(archive.risk, _risk(), check_dtype=False)
    pd.testing.assert_frame_equal(archive.colossus, _colossus(), check_dtype=False)
    pd.testing.assert_frame_equal(
        archive.market,
        validate_market_archive_frame(_market()),
        check_dtype=False,
    )
    assert archive.revision == (7 if schema_version == 3 else None)
    assert archive.stock_rows == (1 if include_stock else 0)
    if schema_version == 3:
        risk_history = load_risk_history_for_identity(
            tmp_path,
            "ir/delta",
            "IR",
            "Delta",
            "EUR",
        )
        assert risk_history["Tenor Swap"].tolist() == ["1Y", "5Y"]
        assert risk_history["Revision"].tolist() == [7, 7]
        assert risk_history["Risk Date"].tolist() == ["2026-08-13"] * 2
    if include_stock:
        pd.testing.assert_frame_equal(
            load_stock_archive_frame(tmp_path, leaf.name),
            _stock(),
            check_dtype=False,
        )


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda frame: frame.assign(**{"Risk Greek": "Vega"}),
            "must use Risk Type",
        ),
        (
            lambda frame: frame.assign(**{"Source Type": "unknown/source"}),
            "unknown Source Type",
        ),
        (
            lambda frame: frame.assign(**{"Market Date": "2026-08-13"}),
            "does not match",
        ),
        (
            lambda frame: pd.concat([frame, frame.iloc[[0]]], ignore_index=True),
            "duplicate quote identities",
        ),
        (
            lambda frame: frame.assign(**{"Tenor Swap Order": 1.5}),
            "non-negative integer market orders",
        ),
    ],
)
def test_market_archive_rejects_corrupt_or_mixed_quote_identities(
    mutate,
    message: str,
) -> None:
    with pytest.raises(RiskArchiveValidationError, match=message):
        validate_market_archive_frame(
            mutate(_market()),
            market_date="2026-08-14",
        )


def test_market_archive_retains_unavailable_quote_as_missing_not_zero() -> None:
    market = _market().iloc[[0]].copy()
    market.loc[:, ["Open", "Current", "Move"]] = float("nan")
    market["Market Data Status"] = "Missing Open and Current (OFFICIAL)"

    validated = validate_market_archive_frame(market, market_date="2026-08-14")

    assert validated[["Open", "Current", "Move"]].isna().all().all()


def test_legacy_market_csv_is_optional_and_query_keeps_daily_quote_order(
    tmp_path: Path,
) -> None:
    legacy_pl = pd.DataFrame(
        [["IR", "Delta", "EUR", "XVA", "BOOK-A", 7.0]],
        columns=list(HISTORY_FILE_COLUMNS),
    )
    for market_date, shift in (
        ("2026-08-12", -0.02),
        ("2026-08-13", -0.01),
        ("2026-08-14", 0.0),
    ):
        leaf = tmp_path / market_date
        leaf.mkdir(parents=True)
        legacy_pl.to_csv(leaf / "histo.csv", index=False)
        legacy_pl.to_csv(leaf / "predicted.csv", index=False)
        if market_date != "2026-08-13":
            _market(market_date, shift=shift).to_csv(
                leaf / "market.csv",
                index=False,
            )

    pl_history = load_shared_pl_history(tmp_path)
    market_history = load_market_history_for_identity(
        tmp_path,
        "IR",
        "Delta",
        "EUR",
    )

    assert pl_history["Market Date"].drop_duplicates().tolist() == [
        "2026-08-12",
        "2026-08-13",
        "2026-08-14",
    ]
    assert market_history[["Market Date", "Tenor Swap"]].values.tolist() == [
        ["2026-08-12", "1Y"],
        ["2026-08-12", "5Y"],
        ["2026-08-14", "1Y"],
        ["2026-08-14", "5Y"],
    ]
    assert market_history["Current"].tolist() == pytest.approx([4.08, 4.28, 4.1, 4.3])
    assert "Portfolio" not in market_history


def test_market_identity_query_avoids_pnl_files_and_caches_only_selected_leaf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    archive_query_module._load_market_identity_leaf_cached.cache_clear()
    original_read_table = archive_io_module.pq.read_table
    market_reads: list[dict[str, object]] = []

    def counted_read_table(source, *args, **kwargs):
        if Path(source).name == MARKET_FILE_NAME:
            market_reads.append(
                {
                    "columns": kwargs.get("columns"),
                    "filters": kwargs.get("filters"),
                }
            )
        return original_read_table(source, *args, **kwargs)

    monkeypatch.setattr(archive_io_module.pq, "read_table", counted_read_table)
    monkeypatch.setattr(
        archive_query_module,
        "_load_completed_leaf",
        lambda _path: (_ for _ in ()).throw(
            AssertionError("market query must not load Risk or Colossus")
        ),
    )

    first = load_market_history_for_identity(tmp_path, "IR", "Delta", "EUR")
    second = load_market_history_for_identity(tmp_path, "IR", "Delta", "EUR")

    pd.testing.assert_frame_equal(first, second)
    assert market_reads == [
        {"columns": ["Market Date"], "filters": None},
        {
            "columns": list(MARKET_ARCHIVE_COLUMNS),
            "filters": [
                ("Risk Type", "==", "IR"),
                ("Risk Greek", "==", "Delta"),
                ("Underlying", "==", "EUR"),
            ],
        },
    ]
    assert len(first) == 2


def test_risk_identity_query_pushes_parquet_predicate_and_projection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    archive_query_module._load_risk_identity_leaf_cached.cache_clear()
    original_read_table = archive_io_module.pq.read_table
    risk_reads: list[dict[str, object]] = []

    def counted_read_table(source, *args, **kwargs):
        if Path(source).name == RISK_FILE_NAME:
            risk_reads.append(
                {
                    "columns": kwargs.get("columns"),
                    "filters": kwargs.get("filters"),
                }
            )
        return original_read_table(source, *args, **kwargs)

    monkeypatch.setattr(archive_io_module.pq, "read_table", counted_read_table)

    first = load_risk_history_for_identity(
        tmp_path,
        "ir/delta",
        "IR",
        "Delta",
        "EUR",
    )
    second = load_risk_history_for_identity(
        tmp_path,
        "ir/delta",
        "IR",
        "Delta",
        "EUR",
    )

    pd.testing.assert_frame_equal(first, second)
    assert risk_reads == [
        {"columns": ["Source Type"], "filters": None},
        {
            "columns": _risk().columns.tolist(),
            "filters": [
                ("Source Type", "==", "ir/delta"),
                ("Risk Type", "==", "IR"),
                ("Risk Greek", "==", "Delta"),
                ("Underlying", "==", "EUR"),
            ],
        },
    ]
    assert first["Tenor Swap"].tolist() == ["1Y", "5Y"]


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (_snapshot(market_status="Live"), "not OFFICIAL"),
        (
            _snapshot(market_date="2026-08-13", system_date="2026-08-14"),
            "not the current natural",
        ),
        (_snapshot(errors=("retained last good",)), "refresh errors"),
    ],
)
def test_ineligible_snapshots_skip_without_loading_colossus(
    tmp_path: Path,
    snapshot: SimpleNamespace,
    reason: str,
) -> None:
    result = archive_official_snapshot(
        snapshot,
        lambda _date: (_ for _ in ()).throw(AssertionError("must not load")),
        tmp_path,
    )

    assert result.status == "skipped"
    assert reason in result.reason
    assert not (tmp_path / "2026-08-14").exists()


def test_loader_failure_or_invalid_grain_never_publishes_partial_leaf(
    tmp_path: Path,
) -> None:
    with pytest.raises(RuntimeError, match="source unavailable"):
        archive_official_snapshot(
            _snapshot(),
            lambda _date: (_ for _ in ()).throw(RuntimeError("source unavailable")),
            tmp_path,
        )
    assert list_completed_market_dates(tmp_path) == ()
    assert not (tmp_path / "2026-08-14").exists()

    empty = pd.DataFrame(columns=list(COLOSSUS_COLUMNS))
    with pytest.raises(RiskArchiveValidationError, match="at least one"):
        archive_official_snapshot(_snapshot(), lambda _date: empty, tmp_path)
    assert list_completed_market_dates(tmp_path) == ()
    assert not (tmp_path / "2026-08-14").exists()

    duplicate = pd.concat([_colossus(), _colossus().iloc[[0]]], ignore_index=True)
    with pytest.raises(RiskArchiveValidationError, match="duplicate four-key"):
        archive_official_snapshot(_snapshot(), lambda _date: duplicate, tmp_path)
    assert list_completed_market_dates(tmp_path) == ()
    assert not (tmp_path / "2026-08-14").exists()


def test_incomplete_leaf_is_hidden_but_a_completed_corrupt_leaf_fails_closed(
    tmp_path: Path,
) -> None:
    incomplete = tmp_path / "2026-08-13"
    incomplete.mkdir(parents=True)
    (incomplete / "risk.csv").write_text("PL\n1\n", encoding="utf-8")
    assert list_completed_market_dates(tmp_path) == ()

    invalid_marker = tmp_path / "2026-08-12"
    invalid_marker.mkdir(parents=True)
    (invalid_marker / "risk.csv").write_text("PL\n1\n", encoding="utf-8")
    (invalid_marker / "colossus.csv").write_text("PL\n1\n", encoding="utf-8")
    (invalid_marker / "_SUCCESS").write_text("{}\n", encoding="utf-8")
    with pytest.raises(RiskArchiveValidationError, match="marker is invalid"):
        list_completed_market_dates(tmp_path)
    for path in invalid_marker.iterdir():
        path.unlink()
    invalid_marker.rmdir()

    result = archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    (result.path / RISK_FILE_NAME).write_bytes(b"corrupt parquet")
    with pytest.raises(RiskArchiveValidationError, match="completion marker"):
        load_risk_archive(tmp_path, "2026-08-14")


def test_parquet_round_trip_preserves_numeric_looking_identity_text(
    tmp_path: Path,
) -> None:
    risk = _risk()
    risk["Activity"] = ["001", "002", "003"]
    risk.loc[0, "Portfolio"] = "001"
    risk.loc[0, "Underlying"] = "007"
    colossus = _colossus()
    colossus.loc[0, "Portfolio"] = "001"
    colossus.loc[0, "Underlying"] = "007"

    result = archive_official_snapshot(
        _snapshot(risk=risk),
        lambda _date: colossus,
        tmp_path,
    )
    loaded = load_risk_archive(tmp_path, result.market_date)

    assert loaded.risk.loc[0, "Portfolio"] == "001"
    assert loaded.risk.loc[0, "Underlying"] == "007"
    assert loaded.risk.loc[0, "Activity"] == "001"
    assert loaded.colossus.loc[0, "Portfolio"] == "001"
    assert loaded.colossus.loc[0, "Underlying"] == "007"


def test_completed_marker_must_retain_official_status_and_colossus_schema(
    tmp_path: Path,
) -> None:
    result = archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    marker = result.path / "_SUCCESS"
    manifest = json.loads(marker.read_text(encoding="utf-8"))
    manifest["market_status"] = "Live"
    marker.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(RiskArchiveValidationError, match="marker is invalid"):
        list_completed_market_dates(tmp_path)
    with pytest.raises(RiskArchiveValidationError, match="not OFFICIAL"):
        load_risk_archive(tmp_path, result.market_date)

    manifest["market_status"] = "OFFICIAL"
    manifest["colossus_columns"] = ["wrong"]
    marker.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RiskArchiveValidationError, match="marker is invalid"):
        list_completed_market_dates(tmp_path)
    with pytest.raises(RiskArchiveValidationError, match="Colossus archive columns"):
        load_risk_archive(tmp_path, result.market_date)


def test_projection_sums_predict_once_and_attaches_product_to_colossus() -> None:
    archive = RiskArchive(
        market_date="2026-08-14",
        path=Path("unused"),
        risk=_risk(),
        colossus=_colossus(),
    )

    history = project_archive_to_pl_history(archive)

    assert list(history.columns) == list(PL_HISTORY_COLUMNS)
    assert len(history) == 4
    ir = history.loc[
        history["Risk Type"].eq("IR") & history[PORTFOLIO].eq("BOOK-A")
    ].set_index(HISTORY_TYPE)["PL"]
    assert ir.to_dict() == {COLOSSUS_TYPE: 24.0, PREDICT_TYPE: 25.0}
    fx = history.loc[history["Risk Type"].eq("FX") & history[PORTFOLIO].eq("BOOK-B")]
    assert fx["Product"].unique().tolist() == ["Hedges"]
    assert set(history[HISTORY_MAPPING_STATUS]) == {"Mapped"}
    assert set(history["SignoffGroup"]) == {"SOG-A", "SOG-B"}


def test_projection_omits_incomplete_predict_group_without_zero_or_partial_sum() -> (
    None
):
    risk = _risk()
    risk.loc[1, "PL"] = pd.NA
    archive = RiskArchive("2026-08-14", Path("unused"), risk, _colossus())

    history = project_archive_to_pl_history(archive)

    ir_predict = history.loc[
        history["Risk Type"].eq("IR") & history[HISTORY_TYPE].eq(PREDICT_TYPE)
    ]
    assert ir_predict.empty
    assert history.loc[
        history["Risk Type"].eq("IR") & history[HISTORY_TYPE].eq(COLOSSUS_TYPE),
        "PL",
    ].tolist() == [24.0]


def test_projection_reports_missing_explorer_authority_columns_clearly() -> None:
    with pytest.raises(
        RiskArchiveValidationError,
        match="missing historical P&L authority columns.*Activity",
    ):
        project_archive_to_pl_history(
            RiskArchive(
                "2026-08-14",
                Path("unused"),
                _risk().drop(columns="Activity"),
                _colossus(),
            )
        )


def test_projection_retains_ambiguous_or_missing_authority_once_as_unmapped() -> None:
    ambiguous = pd.concat(
        [
            _risk(),
            _risk().iloc[[0]].assign(Product="Hedges", PL=1.0),
        ],
        ignore_index=True,
    )
    ambiguous_history = project_archive_to_pl_history(
        RiskArchive("2026-08-14", Path("unused"), ambiguous, _colossus())
    )
    ambiguous_colossus = ambiguous_history.loc[
        ambiguous_history[HISTORY_TYPE].eq(COLOSSUS_TYPE)
        & ambiguous_history[PORTFOLIO].eq("BOOK-A")
    ]
    assert len(ambiguous_colossus) == 1
    assert ambiguous_colossus.iloc[0][HISTORY_MAPPING_STATUS] == UNMAPPED_VALUE
    assert ambiguous_colossus.iloc[0]["SignoffGroup"] == UNMAPPED_VALUE
    assert ambiguous_colossus.iloc[0]["Product"] == UNMAPPED_VALUE

    unknown = pd.concat(
        [
            _colossus(),
            pd.DataFrame(
                [["BOOK-Z", "GBP", "IR", "Delta", 1.0]],
                columns=list(COLOSSUS_COLUMNS),
            ),
        ],
        ignore_index=True,
    )
    unknown_history = project_archive_to_pl_history(
        RiskArchive("2026-08-14", Path("unused"), _risk(), unknown)
    )
    unknown_row = unknown_history.loc[
        unknown_history[HISTORY_TYPE].eq(COLOSSUS_TYPE)
        & unknown_history[PORTFOLIO].eq("BOOK-Z")
    ]
    assert len(unknown_row) == 1
    assert unknown_row.iloc[0][HISTORY_MAPPING_STATUS] == UNMAPPED_VALUE
    assert unknown_row.iloc[0]["PL"] == 1.0


def test_all_completed_dates_project_to_one_canonical_history(tmp_path: Path) -> None:
    archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    archive_official_snapshot(
        _snapshot(market_date="2026-08-17", system_date="2026-08-17"),
        lambda _date: _colossus(),
        tmp_path,
    )

    history = load_shared_pl_history(tmp_path)

    assert list(history.columns) == list(PL_HISTORY_COLUMNS)
    assert history["Market Date"].drop_duplicates().tolist() == [
        "2026-08-14",
        "2026-08-17",
    ]
    assert len(history) == 8


def test_one_history_root_combines_legacy_demo_and_official_archive_dates(
    tmp_path: Path,
) -> None:
    legacy_leaf = tmp_path / "2026-08-13"
    legacy_leaf.mkdir(parents=True)
    legacy = pd.DataFrame(
        [["IR", "Delta", "EUR", "XVA", "BOOK-A", 7.0]],
        columns=list(HISTORY_FILE_COLUMNS),
    )
    legacy.to_csv(legacy_leaf / "histo.csv", index=False)
    legacy.assign(PL=8.0).to_csv(legacy_leaf / "predicted.csv", index=False)
    archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)

    history = load_shared_pl_history(tmp_path)

    assert list(history.columns) == list(PL_HISTORY_COLUMNS)
    assert history["Market Date"].drop_duplicates().tolist() == [
        "2026-08-13",
        "2026-08-14",
    ]
    assert history.loc[history["Market Date"].eq("2026-08-13"), "PL"].tolist() == [
        7.0,
        8.0,
    ]
    assert set(
        history.loc[history["Market Date"].eq("2026-08-13"), HISTORY_MAPPING_STATUS]
    ) == {UNMAPPED_VALUE}
    legacy_rows = history.loc[history["Market Date"].eq("2026-08-13")]
    for column in (ACTIVITY, SIGNOFF_GROUP, CATEGORY, SUB_CATEGORY):
        assert set(legacy_rows[column]) == {UNMAPPED_VALUE}
    assert len(history.loc[history["Market Date"].eq("2026-08-14")]) == 4


def test_shared_history_rejects_the_retired_nested_year_layout(
    tmp_path: Path,
) -> None:
    nested_leaf = tmp_path / "2026" / "08-13"
    nested_leaf.mkdir(parents=True)

    with pytest.raises(RiskArchiveValidationError, match="YYYY-MM-DD leaves"):
        load_shared_pl_history(tmp_path)


def test_shared_history_catalog_detects_a_new_atomic_official_leaf(
    tmp_path: Path,
) -> None:
    legacy_leaf = tmp_path / "2026-08-13"
    legacy_leaf.mkdir(parents=True)
    legacy = pd.DataFrame(
        [["IR", "Delta", "EUR", "XVA", "BOOK-A", 7.0]],
        columns=list(HISTORY_FILE_COLUMNS),
    )
    legacy.to_csv(legacy_leaf / "histo.csv", index=False)
    legacy.to_csv(legacy_leaf / "predicted.csv", index=False)

    before = load_shared_pl_history(tmp_path)
    archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    after = load_shared_pl_history(tmp_path)

    assert before["Market Date"].drop_duplicates().tolist() == ["2026-08-13"]
    assert after["Market Date"].drop_duplicates().tolist() == [
        "2026-08-13",
        "2026-08-14",
    ]


def test_shared_history_hides_partial_official_leaf_without_success_marker(
    tmp_path: Path,
) -> None:
    partial = tmp_path / "2026-08-14"
    partial.mkdir(parents=True)
    _risk().to_csv(partial / "risk.csv", index=False)

    history = load_shared_pl_history(tmp_path)

    assert history.empty
    assert list(history.columns) == list(PL_HISTORY_COLUMNS)


def test_shared_history_rejects_one_date_mixing_legacy_and_official_files(
    tmp_path: Path,
) -> None:
    leaf = tmp_path / "2026-08-14"
    leaf.mkdir(parents=True)
    legacy = pd.DataFrame(
        [["IR", "Delta", "EUR", "XVA", "BOOK-A", 7.0]],
        columns=list(HISTORY_FILE_COLUMNS),
    )
    legacy.to_csv(leaf / "histo.csv", index=False)
    legacy.to_csv(leaf / "predicted.csv", index=False)
    _risk().to_csv(leaf / "risk.csv", index=False)

    with pytest.raises(RiskArchiveValidationError, match="mixes legacy and official"):
        load_shared_pl_history(tmp_path)


def test_shared_history_delegates_corrupt_completed_leaf_to_archive_validation(
    tmp_path: Path,
) -> None:
    leaf = tmp_path / "2026-08-14"
    leaf.mkdir(parents=True)
    (leaf / "_SUCCESS").write_text("{}\n", encoding="utf-8")

    with pytest.raises(RiskArchiveValidationError, match="unsupported schema"):
        load_shared_pl_history(tmp_path)


def test_shared_history_ignores_pending_leaf_that_disappears_during_catalog(
    tmp_path: Path,
    monkeypatch,
) -> None:
    pending = tmp_path / ".2026-08-14.pending-race"
    pending.mkdir(parents=True)
    original_iterdir = Path.iterdir

    def racing_iterdir(path: Path):
        entries = list(original_iterdir(path))
        if path == tmp_path and pending.exists():
            pending.rmdir()
        return iter(entries)

    monkeypatch.setattr(Path, "iterdir", racing_iterdir)

    history = load_shared_pl_history(tmp_path)

    assert history.empty


def test_scheduler_refuses_existing_legacy_date_before_loading_colossus(
    tmp_path: Path,
) -> None:
    leaf = tmp_path / "2026-08-14"
    leaf.mkdir(parents=True)
    legacy = pd.DataFrame(
        [["IR", "Delta", "EUR", "XVA", "BOOK-A", 7.0]],
        columns=list(HISTORY_FILE_COLUMNS),
    )
    legacy.to_csv(leaf / "histo.csv", index=False)
    legacy.to_csv(leaf / "predicted.csv", index=False)

    with pytest.raises(RiskArchiveValidationError, match="incomplete or invalid"):
        archive_official_snapshot(
            _snapshot(),
            lambda _date: (_ for _ in ()).throw(
                AssertionError("Colossus must not be called")
            ),
            tmp_path,
        )


def test_pl_history_projection_caches_each_immutable_leaf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    archive_official_snapshot(_snapshot(), lambda _date: _colossus(), tmp_path)
    archive_query_module._project_completed_leaf_cached.cache_clear()
    original = archive_query_module._load_completed_leaf
    calls = 0

    def counted(path: Path):
        nonlocal calls
        calls += 1
        return original(path)

    monkeypatch.setattr(archive_query_module, "_load_completed_leaf", counted)

    first = load_shared_pl_history(tmp_path)
    second = load_shared_pl_history(tmp_path)

    pd.testing.assert_frame_equal(first, second)
    assert calls == 1


def test_manager_and_scheduler_wrapper_force_one_coherent_refresh(
    tmp_path: Path,
) -> None:
    class Manager:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def refresh(self, **kwargs: object) -> SimpleNamespace:
            self.calls.append(kwargs)
            return _snapshot()

    manager = Manager()
    direct = archive_from_manager(
        manager,
        lambda _date: _colossus(),
        tmp_path / "direct",
    )
    assert direct.status == "archived"
    assert manager.calls == [
        {
            "force_risk": True,
            "force_pl": True,
            "reason": "scheduled_official_archive",
        }
    ]

    scheduled_manager = Manager()
    result = run_scheduled_archive(
        environ={"PL_HISTORICAL_PATH": str(tmp_path / "scheduled")},
        manager_factory=lambda: scheduled_manager,
        colossus_loader=lambda _date: _colossus(),
    )
    assert result.status == "archived"
    assert result.path == (tmp_path / "scheduled" / "2026-08-14").resolve()
    assert resolve_archive_root({}) == DEFAULT_ARCHIVE_ROOT.resolve()
    assert DEFAULT_ARCHIVE_ROOT.parts[-2:] == ("data", "histo")
    assert (
        resolve_archive_root({"PL_HISTORICAL_PATH": "relative-history"}).name
        == "relative-history"
    )
