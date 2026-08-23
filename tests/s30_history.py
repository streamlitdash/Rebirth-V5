"""V3.2 typed history, exact archive query, and frozen-order contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from rebirth.history import s05_store as history_store_module
from rebirth.history import (
    HISTORY_HANDOFF_SCHEMA_VERSION,
    ORDER_AMBIGUOUS,
    ORDERED,
    ArchiveHistoryRepository,
    HistoryHandoff,
    HistoryIdentity,
    HistoryQuery,
    HistoryValidationError,
    RiskFilterView,
    resolve_actual_period_dates,
)
from rebirth.domain.s02_products import PRODUCT_SPECS_BY_SOURCE_TYPE
from rebirth.domain.s10_search import SearchCatalog
from rebirth.history import (
    ARCHIVE_SCHEMA_VERSION,
    COLOSSUS_COLUMNS,
    MARKET_ARCHIVE_COLUMNS,
    MAPPING_STATUS,
    RISK_DATE,
    SNAPSHOT_DATE,
    RiskArchiveValidationError,
    archive_official_snapshot,
)


def _cells(source_type: str, *values: tuple) -> list[dict[str, object]]:
    spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    rows = []
    for item in values:
        swap, option, swap_order, option_order, value = item
        rows.append(
            {
                "Tenor Swap": swap,
                "Tenor Option": option,
                "Tenor Swap Order": swap_order,
                "Tenor Option Order": option_order,
                "value": float(value),
                "Risk Type": spec.risk_type,
                "Risk Greek": spec.risk_greek,
            }
        )
    return rows


def _risk_frame(
    source_type: str,
    cells: list[dict[str, object]],
    *,
    portfolios: tuple[tuple[str, str, float], ...] = (("BOOK-A", "A", 0.0),),
    underlying: str = "EUR",
    reported_underlying: str | None = None,
) -> pd.DataFrame:
    records = []
    for cell in cells:
        for portfolio, activity, adjustment in portfolios:
            value = float(cell["value"]) + adjustment
            records.append(
                {
                    "Source Type": source_type,
                    "Risk Type": cell["Risk Type"],
                    "Risk Greek": cell["Risk Greek"],
                    "Underlying": underlying,
                    "Reported Underlying": reported_underlying or underlying,
                    "Tenor Swap": cell["Tenor Swap"],
                    "Tenor Option": cell["Tenor Option"],
                    "Tenor Swap Order": cell["Tenor Swap Order"],
                    "Tenor Option Order": cell["Tenor Option Order"],
                    "Portfolio": portfolio,
                    "Product": "XVA",
                    "Activity": activity,
                    "SignoffGroup": "SOG-A",
                    "Category": "Core",
                    "Sub Category": "Rates",
                    "Split": "Risk",
                    "Region": "EMEA",
                    "Group": "Rates",
                    "Risk": value,
                    "dRisk": value / 10,
                    "PL": value / 5,
                }
            )
    return pd.DataFrame(records)


def _market_frame(
    source_type: str,
    cells: list[dict[str, object]],
    market_date: str,
    *,
    underlying: str = "EUR",
) -> pd.DataFrame:
    spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    records = []
    for cell in cells:
        current = float(cell["value"])
        records.append(
            {
                "Source Type": source_type,
                "Risk Type": spec.risk_type,
                "Risk Greek": spec.risk_greek,
                "Underlying": underlying,
                "Tenor Swap": cell["Tenor Swap"],
                "Tenor Option": cell["Tenor Option"],
                "Tenor Swap Order": cell["Tenor Swap Order"],
                "Tenor Option Order": cell["Tenor Option Order"],
                "Market Date": market_date,
                "Open": current - 0.25,
                "Current": current,
                "Move": 0.25,
                "Market Status": "OFFICIAL",
                "Market Data Status": "Available",
            }
        )
    return pd.DataFrame(records, columns=list(MARKET_ARCHIVE_COLUMNS))


def _archive_day(
    root: Path,
    market_date: str,
    source_type: str,
    risk: pd.DataFrame,
    market: pd.DataFrame,
    *,
    risk_date: str | None = None,
    revision: int = 1,
) -> None:
    colossus = risk[
        ["Portfolio", "Underlying", "Risk Type", "Risk Greek"]
    ].drop_duplicates()
    colossus["PL"] = 1.0
    colossus = colossus.loc[:, list(COLOSSUS_COLUMNS)]
    snapshot = SimpleNamespace(
        revision=revision,
        refreshed_at=datetime(2026, 8, 1, 22, tzinfo=timezone.utc),
        system_date=pd.Timestamp(market_date),
        market_date=pd.Timestamp(market_date),
        market_status="OFFICIAL",
        errors=(),
        dashboard_frame=risk,
        market_frame=market,
        risk_dates={
            selected_source: pd.Timestamp(risk_date or market_date)
            for selected_source in sorted(risk["Source Type"].unique())
        },
    )
    archive_official_snapshot(snapshot, lambda _date: colossus, root)


def _rewrite_as_schema_v2_csv(root: Path, market_date: str) -> None:
    leaf = root / market_date
    manifest_path = leaf / "_SUCCESS"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = {
        "risk.parquet": "risk.csv",
        "colossus.parquet": "colossus.csv",
        "market.parquet": "market.csv",
    }
    digests: dict[str, str] = {}
    for parquet_name, csv_name in names.items():
        parquet_path = leaf / parquet_name
        csv_path = leaf / csv_name
        pd.read_parquet(parquet_path).to_csv(
            csv_path,
            index=False,
            lineterminator="\n",
        )
        parquet_path.unlink()
        digests[csv_name] = hashlib.sha256(csv_path.read_bytes()).hexdigest()
    manifest["schema_version"] = 2
    manifest.pop("risk_dates")
    manifest["sha256"] = digests
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _handoff(
    source_type: str,
    *,
    kind: str = "risk",
    metric: str = "risk",
    filter_view: RiskFilterView | None = None,
    identity_mode: str = "underlying",
    underlying: str = "EUR",
) -> HistoryHandoff:
    spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]
    return HistoryHandoff(
        schema_version=HISTORY_HANDOFF_SCHEMA_VERSION,
        kind=kind,
        identity=HistoryIdentity(
            (source_type,),
            spec.risk_type,
            spec.risk_greek,
            underlying,
            identity_mode,
        ),
        metric=metric,
        source_revision=9,
        snapshot_date=date(2026, 8, 14),
        filter_view=filter_view,
        reset_generation=2,
    )


def test_handoff_round_trip_is_strict_and_market_rejects_filters() -> None:
    filters = RiskFilterView.from_mapping(
        {
            "filters": {"Activity": ["A"], "Split": ["Risk"]},
            "exclude_selected": False,
        }
    )
    handoff = _handoff(
        "ir/delta",
        filter_view=filters,
        identity_mode="reported",
    )

    assert HistoryHandoff.from_mapping(handoff.to_mapping()) == handoff
    payload = handoff.to_mapping()
    payload["unknown"] = True
    with pytest.raises(HistoryValidationError, match="unknown"):
        HistoryHandoff.from_mapping(payload)
    with pytest.raises(HistoryValidationError, match="does not accept"):
        _handoff("ir/delta", kind="market", metric="current", filter_view=filters)
    with pytest.raises(HistoryValidationError, match="does not publish"):
        HistoryIdentity(("ir/delta",), "FX", "Delta", "EUR")


def test_search_catalog_resolves_structured_identity_without_label_parsing() -> None:
    cells = _cells("ir/delta", ("1Y", "N/A", 0, pd.NA, 3.0))
    gamma_cells = _cells("ir/gamma", ("1Y", "N/A", 0, pd.NA, 0.5))
    gamma_risk = _risk_frame("ir/gamma", gamma_cells, reported_underlying="EUR-RATES")
    gamma_risk["Risk Greek"] = "Delta"
    gamma_risk["Split"] = "Gamma"
    risk = pd.concat(
        [
            _risk_frame("ir/delta", cells, reported_underlying="EUR-RATES"),
            gamma_risk,
        ],
        ignore_index=True,
    )
    market = pd.concat(
        [
            _market_frame("ir/delta", cells, "2026-08-14"),
            _market_frame("ir/gamma", gamma_cells, "2026-08-14"),
        ],
        ignore_index=True,
    )
    catalog = SearchCatalog(
        revision=14,
        risk_dates={
            "ir/delta": pd.Timestamp("2026-08-13"),
            "ir/gamma": pd.Timestamp("2026-08-13"),
        },
        market_date=pd.Timestamp("2026-08-14"),
        market_frame=market,
        risk_pivot_frame=risk,
    )

    risk_identity = catalog.resolve_history_identity(
        "risk",
        catalog.combine_udl_options(identity_mode="reported")[0],
        identity_mode="reported",
    )
    market_identity = catalog.resolve_history_identity(
        "market",
        catalog.market_udl_options()[0],
        identity_mode="underlying",
    )
    handoff = HistoryHandoff.from_resolved_identity(risk_identity, metric="risk")

    assert risk_identity.underlying == "EUR-RATES"
    assert risk_identity.source_types == ("ir/delta", "ir/gamma")
    assert market_identity.underlying == "EUR"
    assert handoff.source_revision == 14
    assert handoff.snapshot_date == date(2026, 8, 14)
    with pytest.raises(ValueError, match="not an exact identity"):
        catalog.resolve_history_identity(
            "risk",
            "IR | Delta | value containing separators",
        )


@pytest.mark.parametrize(
    ("source_types", "risk_type", "expected_axes"),
    [
        (("ir/delta", "ir/gamma"), "IR", 1),
        (("fx/delta", "fx/gamma"), "FX", 0),
    ],
)
def test_derived_gamma_delta_sources_share_one_productspec_axis_policy(
    source_types: tuple[str, ...],
    risk_type: str,
    expected_axes: int,
) -> None:
    identity = HistoryIdentity(source_types, risk_type, "Delta", "EUR")

    assert len(identity.axes) == expected_axes
    with pytest.raises(HistoryValidationError, match="multiple Source Types"):
        _ = identity.source_type


def test_multi_source_risk_history_queries_and_sums_derived_gamma(
    tmp_path: Path,
) -> None:
    delta_cells = _cells("ir/delta", ("1Y", "N/A", 0, pd.NA, 10.0))
    gamma_cells = _cells("ir/gamma", ("1Y", "N/A", 0, pd.NA, 2.0))
    gamma_risk = _risk_frame("ir/gamma", gamma_cells)
    gamma_risk["Risk Greek"] = "Delta"
    gamma_risk["Split"] = "Gamma"
    risk = pd.concat(
        [_risk_frame("ir/delta", delta_cells), gamma_risk],
        ignore_index=True,
    )
    market = pd.concat(
        [
            _market_frame("ir/delta", delta_cells, "2026-08-03"),
            _market_frame("ir/gamma", gamma_cells, "2026-08-03"),
        ],
        ignore_index=True,
    )
    _archive_day(tmp_path, "2026-08-03", "ir/delta", risk, market)
    handoff = HistoryHandoff(
        schema_version=HISTORY_HANDOFF_SCHEMA_VERSION,
        kind="risk",
        identity=HistoryIdentity(
            ("ir/delta", "ir/gamma"),
            "IR",
            "Delta",
            "EUR",
        ),
        metric="risk",
        source_revision=1,
        snapshot_date=date(2026, 8, 3),
    )

    bundle = ArchiveHistoryRepository(tmp_path).read(HistoryQuery(handoff))

    assert bundle.values["Risk"].tolist() == [12.0]
    assert set(bundle.raw_rows["Source Type"]) == {"ir/delta", "ir/gamma"}


def test_multi_source_risk_rejects_conflicting_productspec_axes(monkeypatch) -> None:
    gamma = PRODUCT_SPECS_BY_SOURCE_TYPE["ir/gamma"]
    monkeypatch.setitem(
        PRODUCT_SPECS_BY_SOURCE_TYPE,
        "ir/gamma",
        replace(gamma, axes=()),
    )

    with pytest.raises(HistoryValidationError, match="conflicting ProductSpec axes"):
        HistoryIdentity(("ir/delta", "ir/gamma"), "IR", "Delta", "EUR")


def test_periods_resolve_only_actual_available_dates() -> None:
    available = (
        date(2025, 8, 8),
        date(2026, 8, 3),
        date(2026, 8, 5),
        date(2026, 8, 10),
    )
    handoff = _handoff("fx/delta")

    assert resolve_actual_period_dates(available, HistoryQuery(handoff, "wtd")) == (
        date(2026, 8, 10),
    )
    assert resolve_actual_period_dates(available, HistoryQuery(handoff, "1y")) == (
        date(2026, 8, 3),
        date(2026, 8, 5),
        date(2026, 8, 10),
    )
    custom = HistoryQuery(
        handoff,
        "custom",
        start_date=date(2026, 8, 4),
        end_date=date(2026, 8, 9),
    )
    assert resolve_actual_period_dates(available, custom) == (date(2026, 8, 5),)


def test_zero_axis_risk_filters_before_sum_and_preserves_exact_rows(
    tmp_path: Path,
) -> None:
    cells_1 = _cells("fx/delta", ("Spot", "N/A", pd.NA, pd.NA, 10.0))
    cells_2 = _cells("fx/delta", ("Spot", "N/A", pd.NA, pd.NA, 20.0))
    portfolios = (("BOOK-A", "A", 0.0), ("BOOK-B", "B", 90.0))
    for market_date, cells in (("2026-08-03", cells_1), ("2026-08-04", cells_2)):
        risk = _risk_frame(
            "fx/delta",
            cells,
            portfolios=portfolios,
            underlying="EUR/USD",
        )
        _archive_day(
            tmp_path,
            market_date,
            "fx/delta",
            risk,
            _market_frame("fx/delta", cells, market_date, underlying="EUR/USD"),
        )
    view = RiskFilterView((("Activity", ("A",)),), False)
    bundle = ArchiveHistoryRepository(tmp_path).read(
        HistoryQuery(
            _handoff(
                "fx/delta",
                filter_view=view,
                underlying="EUR/USD",
            )
        )
    )

    assert bundle.ordering.axes == ()
    assert bundle.values["Risk"].tolist() == [10.0, 20.0]
    assert bundle.raw_rows["Portfolio"].tolist() == ["BOOK-A", "BOOK-A"]
    assert bundle.selected_rows["Portfolio"].tolist() == ["BOOK-A"]
    assert bundle.raw_rows[RISK_DATE].tolist() == ["2026-08-03", "2026-08-04"]
    assert bundle.raw_rows[SNAPSHOT_DATE].tolist() == ["2026-08-03", "2026-08-04"]
    assert set(bundle.raw_rows[MAPPING_STATUS]) == {"Mapped"}


def test_one_axis_market_freezes_union_and_reindexes_missing_cells_to_null(
    tmp_path: Path,
) -> None:
    first = _cells(
        "ir/delta",
        ("1Y", "N/A", 0, pd.NA, 1.0),
        ("5Y", "N/A", 1, pd.NA, 5.0),
    )
    second = _cells("ir/delta", ("1Y", "N/A", 0, pd.NA, 2.0))
    for market_date, cells in (("2026-08-03", first), ("2026-08-04", second)):
        _archive_day(
            tmp_path,
            market_date,
            "ir/delta",
            _risk_frame("ir/delta", cells),
            _market_frame("ir/delta", cells, market_date),
        )

    bundle = ArchiveHistoryRepository(tmp_path).read(
        HistoryQuery(_handoff("ir/delta", kind="market", metric="current"))
    )

    assert bundle.ordering.status == ORDERED
    assert bundle.ordering.axes[0].labels == ("1Y", "5Y")
    assert len(bundle.values) == 4
    missing = bundle.values.loc[
        bundle.values["Market Date"].eq("2026-08-04")
        & bundle.values["Tenor Swap"].eq("5Y"),
        "Current",
    ]
    assert missing.isna().all()
    assert {
        "Source Type",
        "Open",
        "Current",
        "Move",
        "Market Status",
        "Market Data Status",
    }.issubset(bundle.raw_rows)
    assert bundle.selected_rows["Tenor Swap"].tolist() == ["1Y"]


def test_two_axis_risk_bundle_uses_productspec_axes_and_full_cartesian_grid(
    tmp_path: Path,
) -> None:
    first = _cells(
        "ir/deltavega",
        ("1Y", "1M", 0, 0, 1.0),
        ("1Y", "3M", 0, 1, 2.0),
        ("5Y", "1M", 1, 0, 3.0),
        ("5Y", "3M", 1, 1, 4.0),
    )
    second = _cells("ir/deltavega", ("1Y", "1M", 0, 0, 5.0))
    for market_date, cells in (("2026-08-03", first), ("2026-08-04", second)):
        _archive_day(
            tmp_path,
            market_date,
            "ir/deltavega",
            _risk_frame("ir/deltavega", cells),
            _market_frame("ir/deltavega", cells, market_date),
        )

    bundle = ArchiveHistoryRepository(tmp_path).read(
        HistoryQuery(_handoff("ir/deltavega"))
    )

    assert tuple(axis.column for axis in bundle.ordering.axes) == (
        "Tenor Swap",
        "Tenor Option",
    )
    assert len(bundle.values) == 8
    assert bundle.values["Risk"].isna().sum() == 3
    assert len(bundle.raw_rows) == 5


@pytest.mark.parametrize(
    ("second_cell", "message"),
    [
        (("1Y", "N/A", 1, pd.NA, 2.0), "conflicting ranks"),
        (("2Y", "N/A", 0, pd.NA, 2.0), "multiple labels to one rank"),
    ],
)
def test_history_rejects_cross_date_rank_conflicts_and_collisions(
    tmp_path: Path,
    second_cell: tuple,
    message: str,
) -> None:
    first = _cells("ir/delta", ("1Y", "N/A", 0, pd.NA, 1.0))
    second = _cells("ir/delta", second_cell)
    for market_date, cells in (("2026-08-03", first), ("2026-08-04", second)):
        _archive_day(
            tmp_path,
            market_date,
            "ir/delta",
            _risk_frame("ir/delta", cells),
            _market_frame("ir/delta", cells, market_date),
        )

    with pytest.raises(HistoryValidationError, match=message):
        ArchiveHistoryRepository(tmp_path).read(
            HistoryQuery(_handoff("ir/delta", kind="market", metric="current"))
        )


def test_wholly_unranked_risk_axis_uses_deterministic_flagged_fallback(
    tmp_path: Path,
) -> None:
    risk_cells = _cells(
        "ir/delta",
        ("10Y", "N/A", pd.NA, pd.NA, 10.0),
        ("2Y", "N/A", pd.NA, pd.NA, 2.0),
    )
    market_cells = _cells(
        "ir/delta",
        ("10Y", "N/A", 1, pd.NA, 10.0),
        ("2Y", "N/A", 0, pd.NA, 2.0),
    )
    _archive_day(
        tmp_path,
        "2026-08-03",
        "ir/delta",
        _risk_frame("ir/delta", risk_cells),
        _market_frame("ir/delta", market_cells, "2026-08-03"),
    )

    bundle = ArchiveHistoryRepository(tmp_path).read(HistoryQuery(_handoff("ir/delta")))

    assert bundle.ordering.status == ORDER_AMBIGUOUS
    assert bundle.ordering.axes[0].labels == ("2Y", "10Y")
    assert bundle.ordering.axes[0].ranks == (None, None)


def test_market_v2_csv_remains_readable_while_exact_risk_requires_metadata(
    tmp_path: Path,
) -> None:
    cells = _cells("ir/delta", ("1Y", "N/A", 0, pd.NA, 3.0))
    _archive_day(
        tmp_path,
        "2026-08-03",
        "ir/delta",
        _risk_frame("ir/delta", cells),
        _market_frame("ir/delta", cells, "2026-08-03"),
    )
    _rewrite_as_schema_v2_csv(tmp_path, "2026-08-03")

    repository = ArchiveHistoryRepository(tmp_path)
    market = repository.read(
        HistoryQuery(_handoff("ir/delta", kind="market", metric="current"))
    )
    risk = repository.read(HistoryQuery(_handoff("ir/delta")))

    assert ARCHIVE_SCHEMA_VERSION == 4
    assert market.raw_rows["Current"].tolist() == [3.0]
    assert risk.empty


def test_repository_is_lazy_bounded_and_generation_includes_new_leaves(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository = ArchiveHistoryRepository(tmp_path, max_rows=1)
    before = repository.generation()
    monkeypatch.setattr(
        repository._store,
        "available_dates",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("read invoked")),
    )
    with pytest.raises(RuntimeError, match="read invoked"):
        repository.read(HistoryQuery(_handoff("fx/delta")))

    monkeypatch.undo()
    cells = _cells(
        "ir/delta",
        ("1Y", "N/A", 0, pd.NA, 1.0),
        ("5Y", "N/A", 1, pd.NA, 2.0),
    )
    _archive_day(
        tmp_path,
        "2026-08-03",
        "ir/delta",
        _risk_frame("ir/delta", cells),
        _market_frame("ir/delta", cells, "2026-08-03"),
    )
    after = repository.generation()

    assert before != after
    with pytest.raises(RiskArchiveValidationError, match="row bound"):
        repository.read(HistoryQuery(_handoff("ir/delta")))
    repository.clear_reconstructable_cache()
    assert (tmp_path / "2026-08-03" / "_SUCCESS").is_file()


def test_catalog_and_exact_reads_share_one_validated_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cells = _cells("ir/delta", ("1Y", "N/A", 0, pd.NA, 3.0))
    _archive_day(
        tmp_path,
        "2026-08-03",
        "ir/delta",
        _risk_frame("ir/delta", cells),
        _market_frame("ir/delta", cells, "2026-08-03"),
    )
    calls = 0
    real_open = history_store_module.open_history_query_database

    def counted_open(root):
        nonlocal calls
        calls += 1
        return real_open(root)

    monkeypatch.setattr(
        history_store_module,
        "open_history_query_database",
        counted_open,
    )
    repository = ArchiveHistoryRepository(tmp_path)
    catalog = repository.catalog()
    risk = next(
        entry
        for entry in catalog.entries
        if entry.kind == "risk" and entry.identity.identity_mode == "reported"
    )
    market = next(entry for entry in catalog.entries if entry.kind == "market")

    risk_bundle = repository.read(HistoryQuery(risk.to_handoff()))
    market_bundle = repository.read(HistoryQuery(market.to_handoff()))

    assert calls == 1
    assert risk_bundle.raw_rows["Risk"].tolist() == [3.0]
    assert market_bundle.raw_rows["Current"].tolist() == [3.0]
