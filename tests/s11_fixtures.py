"""Canonical temp-fixture generator contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest

from cube.domain.s01_schema import TENOR_OPTION, TENOR_SWAP, TENOR_SWAP_ORDER
from cube.domain.s02_products import (
    CURRENT,
    PL,
    VOL_SCORE,
    PRODUCT_SPECS_BY_SOURCE_TYPE,
)
from cube.domain.s10_search import SearchCatalog
from cube.history import (
    ArchiveHistoryRepository,
    HistoryHandoff,
    HistoryQuery,
    HistoryValidationError,
)
from cube.history import (
    ARCHIVE_SCHEMA_VERSION,
    COLOSSUS_FILE_NAME,
    MARKET_FILE_NAME,
    RISK_FILE_NAME,
    STOCK_ARCHIVE_FILE_NAMES,
    STOCK_FILE_NAME,
    load_risk_archive,
    load_stock_archive_frame,
)
from cube.services.s05_sources import _TEMP_CSV_SCHEMAS
from cube.services.s05_sources import build_production_refresh_manager
from cube.pages.pnl.s06_validation import build_validate_pl_comparison
from tools import s01_fixtures as fixtures
from tools.s01_fixtures import (
    TEMP_NOTICE,
    CURRENT_PORTFOLIO_COUNT,
    CURRENT_RISK_ROWS,
    FIXTURE_TAG,
    HISTORICAL_MARKET_DATES,
    HISTORY_COLOSSUS_ROWS,
    HISTORY_MARKET_ROWS,
    HISTORY_RISK_ROWS,
    HISTORY_SOURCE_TYPES,
    HISTORY_STOCK_ROWS,
    SCHEMAS,
    FixtureValidationError,
    build_datasets,
    build_official_history_fixture,
    validate_datasets,
)


FILE_TO_FEED_DATASET = {
    "s01_readiness.csv": "risk_readiness",
    "s02_checker.csv": "risk_checker",
    "s03_risk.csv": "risk",
    "s04_open.csv": "market_open",
    "s05_current.csv": "market_status",
    "s06_portfolios.csv": "portfolio_config",
    "s07_thresholds.csv": "risk_thresholds",
}
PARQUET_ROWS = {
    RISK_FILE_NAME: HISTORY_RISK_ROWS,
    COLOSSUS_FILE_NAME: HISTORY_COLOSSUS_ROWS,
    MARKET_FILE_NAME: HISTORY_MARKET_ROWS,
    STOCK_FILE_NAME: HISTORY_STOCK_ROWS,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _manifest(leaf: Path) -> dict[str, object]:
    return json.loads((leaf / "_SUCCESS").read_text(encoding="utf-8"))


def test_generated_schemas_are_the_exact_feed_contracts() -> None:
    assert {
        filename: _TEMP_CSV_SCHEMAS[dataset]
        for filename, dataset in FILE_TO_FEED_DATASET.items()
    } == SCHEMAS


def test_generator_uses_canonical_axes_and_current_field() -> None:
    datasets = build_datasets()
    validate_datasets(datasets)

    assert PRODUCT_SPECS_BY_SOURCE_TYPE["ir/gamma"].tenor_columns == [TENOR_SWAP]
    assert PRODUCT_SPECS_BY_SOURCE_TYPE["credit/vega"].tenor_columns == [TENOR_SWAP]
    assert CURRENT in SCHEMAS["s05_current.csv"]
    assert "Live" not in SCHEMAS["s05_current.csv"]
    assert "Group" in SCHEMAS["s03_risk.csv"]

    for source_type in ("ir/gamma", "credit/vega"):
        source_rows = [
            row for row in datasets["s03_risk.csv"] if row["Source Type"] == source_type
        ]
        assert len({row[TENOR_SWAP] for row in source_rows}) >= 3
        assert all(not row[TENOR_OPTION] for row in source_rows)
    assert {
        row["Underlying"]
        for row in datasets["s03_risk.csv"]
        if row["Source Type"] == "ir/gamma"
    } == {
        row["Underlying"]
        for row in datasets["s03_risk.csv"]
        if row["Source Type"] == "ir/delta"
    }


def test_risk_fixture_supplies_connector_owned_groups() -> None:
    risk = build_datasets()["s03_risk.csv"]

    assert {
        row["Group"]
        for row in risk
        if row["Source Type"] == "credit/delta"
        and row["Underlying"].endswith("Ford CDS")
    } == {"Single Name"}
    assert {row["Group"] for row in risk if row["Source Type"] == "commo/delta"} == {
        "Oil",
        "Precious",
        "Gas",
    }


def test_live_risk_fixture_has_realistic_scale_and_stable_vol_scores() -> None:
    risk = build_datasets()["s03_risk.csv"]
    repeated = build_datasets()["s03_risk.csv"]

    assert len(risk) == CURRENT_RISK_ROWS == 10_000
    assert len({row["Portfolio"] for row in risk}) == CURRENT_PORTFOLIO_COUNT == 500
    assert [row[VOL_SCORE] for row in repeated] == [row[VOL_SCORE] for row in risk]
    scores = [float(row[VOL_SCORE]) for row in risk]
    assert min(scores) >= 0.0
    assert max(scores) <= 100.0
    assert len(set(scores)) > 1_000


def test_full_market_keeps_ordered_tenors_not_present_in_risk() -> None:
    datasets = build_datasets()
    source_type = "ir/delta"
    risk = {
        (row["Underlying"], row[TENOR_SWAP])
        for row in datasets["s03_risk.csv"]
        if row["Source Type"] == source_type
    }
    market = [
        row for row in datasets["s04_open.csv"] if row["Source Type"] == source_type
    ]
    market_keys = {(row["Underlying"], row[TENOR_SWAP]) for row in market}

    assert risk < market_keys
    for underlying in {row["Underlying"] for row in market}:
        ranks = [
            int(row[TENOR_SWAP_ORDER])
            for row in market
            if row["Underlying"] == underlying
        ]
        assert ranks == list(range(len(ranks)))


def test_history_range_is_exactly_262_business_dates() -> None:
    dates = HISTORICAL_MARKET_DATES

    assert len(dates) == 262
    assert dates[0] == "2025-08-21"
    assert dates[-1] == "2026-08-21"
    assert (pd.Timestamp(dates[-1]) - pd.Timestamp(dates[0])).days == 365
    assert pd.DatetimeIndex(dates).dayofweek.max() < 5


@pytest.mark.parametrize(
    "market_date",
    (
        HISTORICAL_MARKET_DATES[0],
        HISTORICAL_MARKET_DATES[len(HISTORICAL_MARKET_DATES) // 2],
        HISTORICAL_MARKET_DATES[-1],
    ),
)
def test_one_day_history_has_exact_grains_and_all_product_axes(
    market_date: str,
) -> None:
    fixture = build_official_history_fixture(market_date)

    assert len(fixture.risk) == HISTORY_RISK_ROWS
    assert len(fixture.market) == HISTORY_MARKET_ROWS
    assert len(fixture.colossus) == HISTORY_COLOSSUS_ROWS
    assert len(fixture.stock) == HISTORY_STOCK_ROWS
    assert set(fixture.risk["Source Type"]) == set(HISTORY_SOURCE_TYPES)
    assert set(fixture.market["Source Type"]) == set(HISTORY_SOURCE_TYPES)
    assert set(fixture.risk_dates) == set(HISTORY_SOURCE_TYPES)
    assert {len(spec.axes) for spec in PRODUCT_SPECS_BY_SOURCE_TYPE.values()} == {
        0,
        1,
        2,
    }
    quote_key = [
        "Source Type",
        "Risk Type",
        "Underlying",
        "Tenor Swap",
        "Tenor Option",
    ]
    assert fixture.risk.groupby(quote_key, dropna=False).size().eq(2).all()
    assert fixture.risk["Portfolio"].nunique() == 640
    assert fixture.risk["Portfolio"].str.contains(TEMP_NOTICE, regex=False).all()
    assert fixture.stock["CRDS"].str.contains(TEMP_NOTICE, regex=False).all()
    assert fixture.risk[PL].sum() != pytest.approx(fixture.colossus[PL].sum())
    cells_by_axes = {0: 1, 1: 6, 2: 12}
    for source_type, spec in PRODUCT_SPECS_BY_SOURCE_TYPE.items():
        raw_counts = (
            fixture.risk.loc[fixture.risk["Source Type"].eq(source_type)]
            .groupby("Underlying")
            .size()
        )
        max_positions = cells_by_axes[len(spec.axes)] * 2
        assert raw_counts.max() == max_positions
        assert raw_counts.le(max_positions).all()
        reported_counts = (
            fixture.risk.loc[fixture.risk["Source Type"].eq(source_type)]
            .groupby("Reported Underlying")
            .size()
        )
        assert reported_counts.sum() == raw_counts.sum()
    assert (
        fixture.risk.groupby(["Source Type", "Underlying"])["Portfolio"]
        .nunique()
        .eq(2)
        .all()
    )
    comparison = build_validate_pl_comparison(fixture.risk, fixture.colossus)
    assert comparison["comparison status"].value_counts().to_dict() == {
        "Colossus only": 3_000,
        "Matched": 2_000,
        "Predict only": 564,
    }


def test_every_handoff_constructible_quick_identity_exists_in_history() -> None:
    fixture = build_official_history_fixture(HISTORICAL_MARKET_DATES[-1])
    archive = SearchCatalog(
        revision=fixture.revision,
        risk_dates=fixture.risk_dates,
        market_date=pd.Timestamp(fixture.market_date),
        market_frame=fixture.market,
        risk_pivot_frame=fixture.risk,
    )
    manager = build_production_refresh_manager(stage_delays={"risk_product": 0.0})
    manager.refresh(force_risk=True, reason="quick-history-coverage", copy_result=False)

    archived_risk_identities = {
        HistoryHandoff.from_resolved_identity(
            archive.resolve_history_identity(
                "risk",
                option,
                identity_mode=identity_mode,
            ),
            metric="risk",
        ).identity
        for identity_mode in ("reported", "underlying")
        for option in archive.combine_udl_options(identity_mode=identity_mode)
    }
    expected_current_only = {
        (("credit/delta",), "Credit", "XGamma"),
        (("credit/vega",), "Credit", "XGamma Vega"),
        (("new-position/cash-flow",), "Cash Flow", "New"),
    }
    for identity_mode in ("reported", "underlying"):
        current_only: set[tuple[tuple[str, ...], str, str]] = set()
        accepted_signatures: set[tuple[tuple[str, ...], str, str]] = set()
        covered_sources: set[str] = set()
        for option in manager.combine_udl_options(identity_mode=identity_mode):
            resolved = manager.resolve_history_identity(
                "risk",
                option,
                identity_mode=identity_mode,
            )
            signature = (
                resolved.source_types,
                resolved.risk_type,
                resolved.risk_greek,
            )
            if signature in expected_current_only:
                current_only.add(signature)
                with pytest.raises(HistoryValidationError):
                    HistoryHandoff.from_resolved_identity(
                        resolved,
                        metric="risk",
                    )
                continue

            assert set(resolved.source_types) <= set(HISTORY_SOURCE_TYPES)
            handoff = HistoryHandoff.from_resolved_identity(
                resolved,
                metric="risk",
            )
            accepted_signatures.add(signature)
            covered_sources.update(resolved.source_types)
            assert handoff.identity in archived_risk_identities

        assert covered_sources == set(HISTORY_SOURCE_TYPES)
        assert {
            (("fx/delta", "fx/gamma"), "FX", "Delta"),
            (("ir/delta", "ir/gamma"), "IR", "Delta"),
        } <= accepted_signatures
        assert current_only == expected_current_only

    archived_market_identities = {
        HistoryHandoff.from_resolved_identity(
            archive.resolve_history_identity(
                "market",
                option,
                identity_mode="underlying",
            ),
            metric="current",
        ).identity
        for option in archive.market_udl_options()
    }
    current_market_identities = {
        HistoryHandoff.from_resolved_identity(
            manager.resolve_history_identity(
                "market",
                option,
                identity_mode="underlying",
            ),
            metric="current",
        ).identity
        for option in manager.market_udl_options()
    }
    assert {identity.source_type for identity in current_market_identities} == set(
        HISTORY_SOURCE_TYPES
    )
    assert current_market_identities <= archived_market_identities


def test_history_has_temporal_dynamics_and_stock_lifecycle() -> None:
    first = build_official_history_fixture(HISTORICAL_MARKET_DATES[0])
    first_market_total = first.market[CURRENT].sum()
    first_risk_total = first.risk["Risk"].sum()
    first_stock = set(first.stock["CRDS"])
    first_quantity = first.stock.loc[
        first.stock["CRDS"].str.endswith("000000"), "Quantity"
    ].iloc[0]
    del first

    middle = build_official_history_fixture(
        HISTORICAL_MARKET_DATES[len(HISTORICAL_MARKET_DATES) // 2]
    )
    middle_stock = set(middle.stock["CRDS"])
    del middle

    last = build_official_history_fixture(HISTORICAL_MARKET_DATES[-1])
    last_stock = set(last.stock["CRDS"])
    last_quantity = last.stock.loc[
        last.stock["CRDS"].str.endswith("000000"), "Quantity"
    ].iloc[0]

    assert first_market_total != pytest.approx(last.market[CURRENT].sum())
    assert first_risk_total != pytest.approx(last.risk["Risk"].sum())
    assert first_quantity != pytest.approx(last_quantity)
    assert len(first_stock & middle_stock & last_stock) == 4_800
    assert first_stock != middle_stock != last_stock
    assert first_stock - last_stock
    assert last_stock - first_stock


def test_one_leaf_uses_live_v4_parquet_writer_and_specialized_stock_reader(
    tmp_path: Path,
) -> None:
    market_date = HISTORICAL_MARKET_DATES[len(HISTORICAL_MARKET_DATES) // 2]
    fixture = build_official_history_fixture(market_date)
    root = tmp_path / "histo"
    leaf = fixtures._materialize_history_leaf(fixture, root)
    marker = _manifest(leaf)

    assert ARCHIVE_SCHEMA_VERSION == 4
    assert {path.name for path in leaf.iterdir()} == set(STOCK_ARCHIVE_FILE_NAMES)
    assert marker["schema_version"] == 4
    assert marker["fixture"] == FIXTURE_TAG
    assert marker["stock_date"] == marker["market_date"] == market_date
    assert marker["risk_rows"] == HISTORY_RISK_ROWS
    assert marker["market_rows"] == HISTORY_MARKET_ROWS
    assert marker["colossus_rows"] == HISTORY_COLOSSUS_ROWS
    assert marker["stock_rows"] == HISTORY_STOCK_ROWS
    assert set(marker["sha256"]) == set(PARQUET_ROWS)
    for file_name, expected_rows in PARQUET_ROWS.items():
        parquet = pq.ParquetFile(leaf / file_name)
        assert parquet.metadata.num_rows == expected_rows
        assert parquet.metadata.row_group(0).column(0).compression == "ZSTD"
        assert marker["sha256"][file_name] == _sha256(leaf / file_name)

    archive = load_risk_archive(root, market_date)
    assert len(archive.risk) == HISTORY_RISK_ROWS
    assert archive.market is not None and len(archive.market) == HISTORY_MARKET_ROWS
    pd.testing.assert_frame_equal(
        load_stock_archive_frame(root, market_date),
        fixture.stock.sort_values(
            ["CRDS", "CPTY", "Portfolio", "Instrument", "Currency"],
            kind="stable",
        ).reset_index(drop=True),
        check_dtype=False,
    )

    catalog = SearchCatalog(
        revision=fixture.revision,
        risk_dates=fixture.risk_dates,
        market_date=pd.Timestamp(market_date),
        market_frame=fixture.market,
        risk_pivot_frame=fixture.risk,
    )
    resolved = next(
        identity
        for option in catalog.combine_udl_options(identity_mode="reported")
        if (
            identity := catalog.resolve_history_identity(
                "risk",
                option,
                identity_mode="reported",
            )
        ).source_types
        == ("ir/delta", "ir/gamma")
    )
    bundle = ArchiveHistoryRepository(root).read(
        HistoryQuery(HistoryHandoff.from_resolved_identity(resolved, metric="risk"))
    )

    assert set(bundle.raw_rows["Source Type"]) == {"ir/delta", "ir/gamma"}
    assert set(bundle.raw_rows["Split"]) == {"Risk", "Gamma"}
    assert bundle.values["Risk"].sum() == pytest.approx(bundle.raw_rows["Risk"].sum())


def test_history_install_restores_parent_acl_before_atomic_visibility(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "histo"
    root.mkdir()
    market_date = HISTORICAL_MARKET_DATES[-1]
    staged = tmp_path / "stage" / market_date
    staged.mkdir(parents=True)
    (staged / "payload").write_text("fixture", encoding="utf-8")
    destination = root / market_date
    observed: list[Path] = []

    def restore_permissions(pending: Path) -> None:
        assert pending.is_dir()
        assert not destination.exists()
        observed.append(pending)

    monkeypatch.setattr(fixtures, "RISK_ARCHIVE_DIRECTORY", root)
    monkeypatch.setattr(
        fixtures,
        "_restore_windows_parent_acl",
        restore_permissions,
    )

    fixtures._install_history_leaf(staged)

    assert observed == [root / f".{market_date}.fixture-v4-pending"]
    assert (destination / "payload").read_text(encoding="utf-8") == "fixture"


def test_replacement_preflight_accepts_only_recognized_fixture_leaves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "histo"
    market_date = HISTORICAL_MARKET_DATES[0]
    leaf = root / market_date
    leaf.mkdir(parents=True)
    for file_name in ("risk.csv", "colossus.csv", "market.csv", "stock.csv"):
        (leaf / file_name).write_text("old fixture\n", encoding="utf-8")
    (leaf / "_SUCCESS").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "market_date": market_date,
                "stock_date": market_date,
                "fixture": fixtures.LEGACY_FIXTURE_TAG,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(fixtures, "RISK_ARCHIVE_DIRECTORY", root)

    fixtures._recognize_replaceable_fixture_leaf(leaf, market_date)
    marker = _manifest(leaf)
    marker["fixture"] = "runtime-user-data"
    (leaf / "_SUCCESS").write_text(json.dumps(marker), encoding="utf-8")

    with pytest.raises(FixtureValidationError, match="Refusing to replace"):
        fixtures._recognize_replaceable_fixture_leaf(leaf, market_date)


def test_checked_in_archive_has_262_exact_v4_leaves_and_sampled_content() -> None:
    root = fixtures.RISK_ARCHIVE_DIRECTORY
    leaves = tuple(
        sorted(
            path
            for path in root.iterdir()
            if path.is_dir() and path.name in HISTORICAL_MARKET_DATES
        )
    )
    assert tuple(path.name for path in leaves) == HISTORICAL_MARKET_DATES

    sampled_totals: list[tuple[float, float]] = []
    sampled_stock_ids: list[set[str]] = []
    sample_dates = {
        HISTORICAL_MARKET_DATES[0],
        HISTORICAL_MARKET_DATES[len(HISTORICAL_MARKET_DATES) // 2],
        HISTORICAL_MARKET_DATES[-1],
    }
    for leaf in leaves:
        assert {path.name for path in leaf.iterdir()} == set(STOCK_ARCHIVE_FILE_NAMES)
        marker = _manifest(leaf)
        assert marker["schema_version"] == 4
        assert marker["fixture"] == FIXTURE_TAG
        assert marker["market_date"] == marker["stock_date"] == leaf.name
        assert marker["risk_rows"] == HISTORY_RISK_ROWS
        assert marker["market_rows"] == HISTORY_MARKET_ROWS
        assert marker["colossus_rows"] == HISTORY_COLOSSUS_ROWS
        assert marker["stock_rows"] == HISTORY_STOCK_ROWS
        assert set(marker["sha256"]) == set(PARQUET_ROWS)
        for file_name, expected_rows in PARQUET_ROWS.items():
            path = leaf / file_name
            assert pq.ParquetFile(path).metadata.num_rows == expected_rows
            assert marker["sha256"][file_name] == _sha256(path)

        if leaf.name not in sample_dates:
            continue
        risk = pd.read_parquet(leaf / RISK_FILE_NAME)
        market = pd.read_parquet(leaf / MARKET_FILE_NAME)
        colossus = pd.read_parquet(leaf / COLOSSUS_FILE_NAME)
        stock = pd.read_parquet(leaf / STOCK_FILE_NAME)
        assert set(risk["Source Type"]) == set(HISTORY_SOURCE_TYPES)
        assert risk["Portfolio"].nunique() == 640
        assert market["Underlying"].str.contains("FAKE_REPLACE_ME", regex=False).all()
        assert colossus["Portfolio"].str.contains("FAKE_REPLACE_ME", regex=False).all()
        assert stock["CRDS"].str.contains("FAKE_REPLACE_ME", regex=False).all()
        sampled_totals.append((market[CURRENT].sum(), risk["Risk"].sum()))
        sampled_stock_ids.append(set(stock["CRDS"]))

    assert len(set(sampled_totals)) == 3
    assert len(set.intersection(*sampled_stock_ids)) == 4_800
    assert len({frozenset(values) for values in sampled_stock_ids}) == 3
