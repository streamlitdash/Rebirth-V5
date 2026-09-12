"""Legacy archive/domain contracts retained after the simple Stock page rewrite.

Current page interaction and refresh contracts are tested in s81_stock_simple.py.
"""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
import pytest
from flask import Flask

from cube.adapters import s08_stock as stock_adapter
from cube.adapters.s08_stock import (
    GetStock,
    STOCK_ARCHIVE_ROOT,
    STOCK_COLUMNS,
    STOCK_DATE_COLUMN,
    STOCK_HISTORY_COLUMNS,
    STOCK_HISTORY_MAX_DATES,
    build_stock_adapter,
    get_stock,
    load_stock_history,
    validate_stock_frame,
)
from cube.domain.s01_schema import PORTFOLIO_MAPPED_COLUMN, UNMAPPED_VALUE
from cube.domain.s09_stock import (
    CURRENT_MARKET_VALUE_COLUMN,
    MAPPED_STOCK_COMPARISON_COLUMNS,
    MARKET_VALUE_CHANGE_COLUMN,
    PRIOR_QUANTITY_COLUMN,
    QUANTITY_CHANGE_COLUMN,
    STOCK_CHANGE_COLUMN,
    STOCK_HIERARCHY_DEPTH_COLUMN,
    STOCK_HIERARCHY_LABEL_COLUMN,
    STOCK_HIERARCHY_LEVEL_COLUMN,
    STOCK_HIERARCHY_PATH_COLUMN,
    STOCK_HIERARCHY_POSITION_COUNT_COLUMN,
    STOCK_IDENTITY_COLUMNS,
    STOCK_PROMOTION_BUCKET_COLUMN,
    STOCK_TEMPORARY_GROUP_COLUMN,
    compare_stock_snapshots,
    filter_stock_comparison,
    map_stock_comparison_portfolios,
    map_stock_portfolios,
    prepare_stock_hierarchy,
    summarize_stock_hierarchy,
)
from cube.pages import PAGE_SERVICES_CONFIG_KEY
from cube.pages.stock.s01_data import default_stock_dates
from cube.pages.stock import layout as stock_page_layout
from cube.pages.stock.s02_history import (
    SQLStockHistoryRepository,
    build_stock_value_history_figure,
    stock_history_date_range,
    stock_history_identity_from_token,
    stock_value_history_frame,
)
from tools.s01_fixtures import (
    HISTORICAL_MARKET_DATES,
    _materialize_history_leaf,
    build_official_history_fixture,
)


def _stock(rows: list[list[object]] | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        rows
        if rows is not None
        else [
            ["CRDS-1", "CPTY-A", "BOOK_A", "EURUSD", "USD", 100.0, 25.5],
            ["CRDS-2", "CPTY-B", "BOOK_UNKNOWN", "CDX", "USD", -50.0, -12.0],
        ],
        columns=list(STOCK_COLUMNS),
    )


def _config(rows: list[list[object]] | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        rows
        if rows is not None
        else [
            ["BOOK_A", "XVA", "Macro", "SOG-A", "Core", "Rates"],
            ["BOOK_B", "Hedges", "Hedge", "SOG-B", "Hedge", "Credit"],
            ["BOOK_C", "XVA", "Macro", "SOG-C", "Other", "FX"],
        ],
        columns=[
            "Portfolio",
            "Product",
            "Activity",
            "SignoffGroup",
            "Category",
            "Sub Category",
        ],
    )


def _comparison_legs() -> tuple[pd.DataFrame, pd.DataFrame]:
    current = _stock(
        [
            ["CRDS-1", "CPTY-A", "BOOK_A", "EURUSD", "USD", 110.0, 30.0],
            ["CRDS-2", "CPTY-B", "BOOK_B", "CDX", "USD", 50.0, 12.0],
            ["CRDS-3", "CPTY-C", "BOOK_C", "GILT", "GBP", 20.0, 8.0],
        ]
    )
    prior = _stock(
        [
            ["CRDS-1", "CPTY-A", "BOOK_A", "EURUSD", "USD", 100.0, 25.0],
            ["CRDS-2", "CPTY-B", "BOOK_B", "CDX", "USD", 50.0, 12.0],
            ["CRDS-4", "CPTY-D", "BOOK_UNKNOWN", "UST", "USD", 7.0, 4.0],
        ]
    )
    return current, prior


def _history_frame(start_date: object, end_date: object) -> pd.DataFrame:
    rows: list[list[object]] = []
    for offset, stock_date in enumerate(pd.bdate_range(start_date, end_date)):
        rows.append(
            [
                stock_date,
                "CRDS-STABLE",
                "CPTY-A",
                "BOOK_A",
                "EURUSD",
                "USD",
                100.0 + offset,
                1_000.0 + (10.0 * offset),
            ]
        )
        if offset in {0, 2}:
            rows.append(
                [
                    stock_date,
                    "CRDS-GAPPED",
                    "CPTY-B",
                    "BOOK_B",
                    "CDX",
                    "USD",
                    10.0 + offset,
                    200.0 + offset,
                ]
            )
    return pd.DataFrame(rows, columns=list(STOCK_HISTORY_COLUMNS))


def _walk(component: object) -> Iterable[object]:
    yield component
    children = getattr(component, "children", None)
    if isinstance(children, (list, tuple)):
        for child in children:
            yield from _walk(child)
    elif children is not None:
        yield from _walk(children)


def _callback_for_input(app, component_id: str):
    return next(
        metadata["callback"].__wrapped__
        for metadata in app.callback_map.values()
        if any(item["id"] == component_id for item in metadata["inputs"])
    )


def _callback_for_output(app, component_id: str, component_property: str):
    return next(
        metadata["callback"].__wrapped__
        for metadata in app.callback_map.values()
        if any(
            output.component_id == component_id
            and output.component_property == component_property
            for output in _callback_outputs(metadata)
        )
    )


def _callback_outputs(metadata: dict) -> list[object]:
    output = metadata["output"]
    return list(output) if isinstance(output, (list, tuple)) else [output]


def test_stock_adapter_normalizes_dates_and_returns_a_defensive_copy() -> None:
    calls: list[pd.Timestamp] = []
    source_frame = _stock()

    def source(stock_date: pd.Timestamp) -> pd.DataFrame:
        calls.append(stock_date)
        return source_frame

    result = build_stock_adapter(stock=source).get_stock("2026-08-15 13:45")
    result.loc[0, "CPTY"] = "changed"

    assert calls == [pd.Timestamp("2026-08-15")]
    assert tuple(result.columns) == STOCK_COLUMNS
    assert source_frame.loc[0, "CPTY"] == "CPTY-A"


@pytest.mark.parametrize(
    ("frame", "message"),
    [
        (_stock()[list(reversed(STOCK_COLUMNS))], "columns must be exactly"),
        (
            _stock([["CRDS-1", "", "BOOK_A", "EURUSD", "USD", 1.0, 2.0]]),
            "CPTY.*nonblank text",
        ),
        (
            _stock([["CRDS-1", "CPTY-A", "BOOK_A", "EURUSD", "USD", True, 2.0]]),
            "Quantity.*finite numbers",
        ),
    ],
)
def test_stock_adapter_rejects_schema_and_value_contract_failures(
    frame: pd.DataFrame,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_stock_frame(frame)


def test_checked_in_legacy_v4_stock_is_validated_and_varies_by_date() -> None:
    prior = get_stock("2026-08-20")
    current = GetStock("2026-08-21")
    prior_identities = set(
        prior[list(STOCK_IDENTITY_COLUMNS)].itertuples(index=False, name=None)
    )
    current_identities = set(
        current[list(STOCK_IDENTITY_COLUMNS)].itertuples(index=False, name=None)
    )

    assert tuple(current.columns) == STOCK_COLUMNS
    assert len(current) == 5_000
    assert current["CRDS"].str.startswith("TEMP_REPLACE_ME").all()
    assert len(current_identities - prior_identities) == 1
    assert len(prior_identities - current_identities) == 1
    stable = current_identities & prior_identities
    prior_stable = prior.set_index(list(STOCK_IDENTITY_COLUMNS)).loc[list(stable)]
    current_stable = current.set_index(list(STOCK_IDENTITY_COLUMNS)).loc[list(stable)]
    assert not current_stable[["Quantity", "Market Value"]].equals(
        prior_stable[["Quantity", "Market Value"]]
    )

    current.loc[:, "CPTY"] = "changed"
    assert GetStock("2026-08-21")["CPTY"].str.startswith("TEMP_REPLACE_ME").all()


def test_stock_history_loader_is_bounded_and_explicitly_lazy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def unexpected_read(_root, _stock_date):
        nonlocal calls
        calls += 1
        raise AssertionError("bounded validation must happen before leaf I/O")

    monkeypatch.setattr(stock_adapter, "load_stock_archive_leaf", unexpected_read)
    with pytest.raises(ValueError, match=str(STOCK_HISTORY_MAX_DATES)):
        load_stock_history(STOCK_ARCHIVE_ROOT, "2020-01-01", "2030-01-01")
    assert calls == 0


def test_stock_history_skips_only_genuinely_absent_business_dates(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for stock_date in ("2026-08-17", "2026-08-19"):
        (tmp_path / stock_date).mkdir()
    calls: list[str] = []

    def completed_leaf(_root, stock_date, *, identity=None):
        del identity
        calls.append(pd.Timestamp(stock_date).date().isoformat())
        return _stock()

    monkeypatch.setattr(stock_adapter, "load_stock_archive_leaf", completed_leaf)
    history = load_stock_history(tmp_path, "2026-08-17", "2026-08-19")

    assert calls == ["2026-08-17", "2026-08-19"]
    assert history[STOCK_DATE_COLUMN].dt.strftime("%Y-%m-%d").unique().tolist() == [
        "2026-08-17",
        "2026-08-19",
    ]

    (tmp_path / "2026-08-18").mkdir()

    def invalid_leaf(_root, stock_date, *, identity=None):
        del identity
        if pd.Timestamp(stock_date) == pd.Timestamp("2026-08-18"):
            raise ValueError("invalid completed leaf")
        return _stock()

    monkeypatch.setattr(stock_adapter, "load_stock_archive_leaf", invalid_leaf)
    with pytest.raises(ValueError, match="invalid completed leaf"):
        load_stock_history(tmp_path, "2026-08-17", "2026-08-19")


def test_stock_history_loader_adds_dates_only_when_invoked() -> None:
    history = load_stock_history(
        STOCK_ARCHIVE_ROOT,
        "2026-08-20",
        "2026-08-21",
    )

    assert tuple(history.columns) == (STOCK_DATE_COLUMN, *STOCK_COLUMNS)
    assert history[STOCK_DATE_COLUMN].dt.strftime("%Y-%m-%d").unique().tolist() == [
        "2026-08-20",
        "2026-08-21",
    ]


def test_sql_stock_history_repository_is_lazy_exact_and_payload_bounded(
    tmp_path,
) -> None:
    fixture = build_official_history_fixture(HISTORICAL_MARKET_DATES[-1])
    _materialize_history_leaf(fixture, tmp_path)
    repository = SQLStockHistoryRepository(tmp_path)

    assert repository._connection is None
    catalog = repository.catalog("BOOK-0001", limit=7)

    assert 0 < len(catalog.options) <= 7
    assert catalog.minimum_date == fixture.market_date
    assert catalog.maximum_date == fixture.market_date
    assert catalog.date_count == 1
    identity = stock_history_identity_from_token(catalog.options[0]["value"])
    rows = repository.rows(identity, fixture.market_date, fixture.market_date)
    assert len(rows) == 1
    assert rows[STOCK_DATE_COLUMN].dt.strftime("%Y-%m-%d").tolist() == [
        fixture.market_date
    ]
    for column, value in identity.items():
        assert rows[column].eq(value).all()
    repository.clear()
    assert repository._connection is None


def test_stock_history_loader_projects_one_exact_identity() -> None:
    first = get_stock("2026-08-20")
    identity = first.loc[0, list(STOCK_IDENTITY_COLUMNS)].to_dict()

    history = load_stock_history(
        STOCK_ARCHIVE_ROOT,
        "2026-08-20",
        "2026-08-21",
        identity=identity,
    )

    assert 0 < len(history) <= 2
    assert tuple(history.columns) == STOCK_HISTORY_COLUMNS
    for column, value in identity.items():
        assert history[column].eq(value).all()


def test_stock_mapping_remains_left_many_to_one_and_preserves_unmapped() -> None:
    mapped = map_stock_portfolios(_stock(), _config())

    assert mapped["CRDS"].tolist() == ["CRDS-1", "CRDS-2"]
    assert mapped[PORTFOLIO_MAPPED_COLUMN].tolist() == [True, False]
    assert mapped.loc[0, "SignoffGroup"] == "SOG-A"
    assert mapped.loc[1, "SignoffGroup"] == UNMAPPED_VALUE


def test_stock_comparison_is_full_outer_with_visible_deltas_and_status() -> None:
    current, prior = _comparison_legs()
    compared = compare_stock_snapshots(current, prior).set_index("CRDS")

    assert compared.index.tolist() == ["CRDS-1", "CRDS-2", "CRDS-3", "CRDS-4"]
    assert compared[STOCK_CHANGE_COLUMN].to_dict() == {
        "CRDS-1": "Changed",
        "CRDS-2": "Unchanged",
        "CRDS-3": "Added",
        "CRDS-4": "Removed",
    }
    assert compared.loc["CRDS-1", QUANTITY_CHANGE_COLUMN] == 10.0
    assert compared.loc["CRDS-1", MARKET_VALUE_CHANGE_COLUMN] == 5.0
    assert pd.isna(compared.loc["CRDS-3", PRIOR_QUANTITY_COLUMN])
    assert compared.loc["CRDS-3", QUANTITY_CHANGE_COLUMN] == 20.0
    assert pd.isna(compared.loc["CRDS-4", CURRENT_MARKET_VALUE_COLUMN])
    assert compared.loc["CRDS-4", MARKET_VALUE_CHANGE_COLUMN] == -4.0


def test_stock_comparison_rejects_ambiguous_duplicate_identity() -> None:
    current, prior = _comparison_legs()
    duplicate = pd.concat([current, current.iloc[[0]]], ignore_index=True)

    with pytest.raises(ValueError, match="duplicate Stock identities"):
        compare_stock_snapshots(duplicate, prior)


def test_stock_comparison_mapping_and_filters_are_or_within_and_across() -> None:
    current, prior = _comparison_legs()
    mapped = map_stock_comparison_portfolios(current, prior, _config())

    assert tuple(mapped.columns) == MAPPED_STOCK_COMPARISON_COLUMNS
    assert mapped.set_index("CRDS").loc["CRDS-4", "Activity"] == UNMAPPED_VALUE
    filtered = filter_stock_comparison(
        mapped,
        {
            "portfolio": ["BOOK_A", "BOOK_B"],
            "activity": ["Macro", "Hedge"],
            "category": ["Core"],
            "signoffgroup": [],
            "subcategory": None,
        },
    )
    assert filtered["CRDS"].tolist() == ["CRDS-1"]
    excluded = filter_stock_comparison(
        mapped,
        {"portfolio": ["BOOK_A", "BOOK_UNKNOWN"]},
        exclude_selected=True,
    )
    assert excluded["CRDS"].tolist() == ["CRDS-2", "CRDS-3"]
    with pytest.raises(ValueError, match="Unknown Stock"):
        filter_stock_comparison(mapped, {"risk-only-filter": ["x"]})


def test_stock_promotion_runs_on_the_filtered_comparison_shape() -> None:
    """A promoted source row cannot leak into a lower-value filtered view."""

    current = _stock(
        [
            ["CRDS-HIGH", "CPTY-A", "BOOK_A", "EQ-A", "USD", 1.0, 60_000.0],
            ["CRDS-LOW", "CPTY-B", "BOOK_B", "EQ-B", "USD", 1.0, 20_000.0],
        ]
    )
    prior = current.copy()
    prior["Market Value"] = 0.0
    mapped = map_stock_comparison_portfolios(current, prior, _config())

    global_hierarchy = summarize_stock_hierarchy(mapped, 50_000.0)
    filtered = filter_stock_comparison(mapped, {"activity": ["Hedge"]})
    filtered_hierarchy = summarize_stock_hierarchy(filtered, 50_000.0)

    global_paths = set(global_hierarchy[STOCK_HIERARCHY_PATH_COLUMN])
    filtered_paths = set(filtered_hierarchy[STOCK_HIERARCHY_PATH_COLUMN])
    assert ("Macro", "Promoted") in global_paths
    assert filtered[CURRENT_MARKET_VALUE_COLUMN].sum() == 20_000.0
    assert ("Hedge", "Promoted") not in filtered_paths
    assert ("Hedge", "Other") in filtered_paths
    assert all("CRDS-HIGH" not in path for path in filtered_paths)


def test_stock_promotion_aggregates_filtered_rows_at_displayed_name_identity() -> None:
    """Several Portfolio rows for one visible name share one promotion bucket."""

    current = _stock(
        [
            ["CRDS-1", "CPTY-A", "BOOK_A", "EQ-A", "USD", 1.0, 30_000.0],
            ["CRDS-1", "CPTY-A", "BOOK_B", "EQ-B", "USD", 1.0, 30_000.0],
        ]
    )
    prior = current.copy()
    prior["Market Value"] = 0.0
    config = _config(
        [
            ["BOOK_A", "XVA", "Macro", "SOG-A", "Core", "Rates"],
            ["BOOK_B", "XVA", "Macro", "SOG-A", "Core", "Rates"],
        ]
    )
    mapped = map_stock_comparison_portfolios(current, prior, config)

    prepared = prepare_stock_hierarchy(mapped, 50_000.0)
    assert prepared[CURRENT_MARKET_VALUE_COLUMN].tolist() == [30_000.0, 30_000.0]
    assert prepared[STOCK_PROMOTION_BUCKET_COLUMN].tolist() == [
        "Promoted",
        "Promoted",
    ]

    hierarchy = summarize_stock_hierarchy(mapped, 50_000.0)
    visible_leaf = hierarchy.loc[
        hierarchy[STOCK_HIERARCHY_PATH_COLUMN].map(
            lambda path: (
                path
                == (
                    "Macro",
                    "Promoted",
                    "Temporary currency group · USD",
                    "CPTY-A",
                    "CRDS-1",
                )
            )
        )
    ].iloc[0]
    assert visible_leaf[CURRENT_MARKET_VALUE_COLUMN] == 60_000.0
    assert not any(
        path[:2] == ("Macro", "Other")
        for path in hierarchy[STOCK_HIERARCHY_PATH_COLUMN]
    )


def test_stock_hierarchy_orders_absolute_current_stock_after_filtering() -> None:
    current = _stock(
        [
            ["CRDS-A", "CPTY-A", "BOOK_A", "EQ-A", "USD", 1.0, 70_000.0],
            ["CRDS-B", "CPTY-B", "BOOK_B", "EQ-B", "USD", 1.0, -65_000.0],
            ["CRDS-C", "CPTY-C", "BOOK_C", "EQ-C", "USD", 1.0, -60_000.0],
        ]
    )
    prior = current.copy()
    prior["Market Value"] = 0.0
    config = _config(
        [
            ["BOOK_A", "XVA", "Macro", "SOG-A", "Core", "Rates"],
            ["BOOK_B", "XVA", "Macro", "SOG-A", "Core", "Rates"],
            ["BOOK_C", "XVA", "Hedge", "SOG-A", "Core", "Rates"],
        ]
    )
    mapped = map_stock_comparison_portfolios(current, prior, config)

    def activity_order(frame: pd.DataFrame) -> list[str]:
        hierarchy = summarize_stock_hierarchy(frame, 50_000.0)
        return hierarchy.loc[
            hierarchy[STOCK_HIERARCHY_DEPTH_COLUMN].eq(1),
            STOCK_HIERARCHY_LABEL_COLUMN,
        ].tolist()

    # Macro nets to +5k globally, so Hedge's 60k absolute Stock ranks first.
    assert activity_order(mapped) == ["Hedge", "Macro"]

    # Removing BOOK_B changes Macro to +70k and therefore recomputes its rank.
    filtered = filter_stock_comparison(
        mapped,
        {"portfolio": ["BOOK_A", "BOOK_C"]},
    )
    assert activity_order(filtered) == ["Macro", "Hedge"]


def test_stock_promotion_and_hierarchy_preserve_identity_and_totals() -> None:
    current = _stock(
        [
            ["CRDS-1", "CPTY-A", "BOOK_A", "EQ-A", "USD", 10.0, 50_000.0],
            ["CRDS-2", "CPTY-B", "BOOK_B", "EQ-B", "GBP", 20.0, -60_000.0],
            ["CRDS-3", "CPTY-C", "BOOK_C", "EQ-C", "USD", 30.0, 49_999.0],
            [
                "CRDS-4",
                "CPTY-D",
                "BOOK_UNKNOWN",
                "EQ-D",
                "EUR",
                40.0,
                100_000.0,
            ],
        ]
    )
    prior = current.copy()
    prior["Market Value"] = 0.0
    mapped = map_stock_comparison_portfolios(current, prior, _config())

    prepared = prepare_stock_hierarchy(mapped, 50_000)
    assert prepared[STOCK_PROMOTION_BUCKET_COLUMN].tolist() == [
        "Promoted",  # equality is intentionally inclusive
        "Promoted",  # negative current MV uses its absolute value
        "Other",
        "Promoted",
    ]
    assert prepared[STOCK_TEMPORARY_GROUP_COLUMN].tolist() == [
        "Temporary currency group · USD",
        "Temporary currency group · GBP",
        "Temporary currency group · USD",
        "Temporary currency group · EUR",
    ]
    assert prepared[PORTFOLIO_MAPPED_COLUMN].tolist() == [True, True, True, False]

    hierarchy = summarize_stock_hierarchy(mapped, 50_000)
    total = hierarchy.loc[
        hierarchy[STOCK_HIERARCHY_PATH_COLUMN].map(lambda path: path == ())
    ].iloc[0]
    assert total[CURRENT_MARKET_VALUE_COLUMN] == 139_999.0
    assert total[MARKET_VALUE_CHANGE_COLUMN] == 139_999.0
    paths = set(hierarchy[STOCK_HIERARCHY_PATH_COLUMN])
    macro = hierarchy.loc[
        hierarchy[STOCK_HIERARCHY_PATH_COLUMN].map(lambda path: path == ("Macro",))
    ].iloc[0]
    assert macro[STOCK_HIERARCHY_POSITION_COUNT_COLUMN] == 2
    assert macro[CURRENT_MARKET_VALUE_COLUMN] == 99_999.0
    assert macro[MARKET_VALUE_CHANGE_COLUMN] == 99_999.0
    assert (
        "Macro",
        "Promoted",
        "Temporary currency group · USD",
        "CPTY-A",
        "CRDS-1",
    ) in paths
    assert (
        "Macro",
        "Other",
        "Temporary currency group · USD",
        "CPTY-C",
        "CRDS-3",
    ) in paths
    assert (
        UNMAPPED_VALUE,
        "Promoted",
        "Temporary currency group · EUR",
        "CPTY-D",
        "CRDS-4",
    ) in paths
    assert set(hierarchy[STOCK_HIERARCHY_LEVEL_COLUMN]) == {
        "Total",
        "Activity",
        STOCK_PROMOTION_BUCKET_COLUMN,
        STOCK_TEMPORARY_GROUP_COLUMN,
        "CPTY",
        "CRDS",
    }


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("2026-08-14", ("2026-08-14", "2026-08-13")),  # Friday
        ("2026-08-17", ("2026-08-17", "2026-08-14")),  # Monday
        ("2026-08-15", ("2026-08-14", "2026-08-13")),  # Saturday
        ("2026-08-16", ("2026-08-14", "2026-08-13")),  # Sunday
    ],
)
def test_stock_default_dates_use_reference_market_date_and_prior_business_day(
    reference: str,
    expected: tuple[str, str],
) -> None:
    current, prior = default_stock_dates(reference)
    assert (current.date().isoformat(), prior.date().isoformat()) == expected


@pytest.mark.parametrize(
    ("preset", "expected_start"),
    [
        ("wtd", "2026-08-17"),
        ("mtd", "2026-08-01"),
        ("ytd", "2026-01-01"),
        ("1y", "2025-10-15"),
        ("all", "2025-10-15"),
    ],
)
def test_stock_history_periods_are_clamped_to_archive_bounds(
    preset: str,
    expected_start: str,
) -> None:
    start, end = stock_history_date_range(
        "2026-08-21",
        preset=preset,
        minimum_date="2025-10-15",
    )

    assert start.date().isoformat() == expected_start
    assert end.date().isoformat() == "2026-08-21"


def test_stock_history_custom_period_uses_the_selected_start() -> None:
    start, end = stock_history_date_range(
        "2026-08-21",
        preset="custom",
        minimum_date="2025-10-15",
        start_date="2026-07-04",
    )

    assert start.date().isoformat() == "2026-07-04"
    assert end.date().isoformat() == "2026-08-21"




def test_native_stock_page_resolves_the_active_flask_service() -> None:
    first = Flask("first-stock-app")
    second = Flask("second-stock-app")
    first.server_name = "first.test"
    second.server_name = "second.test"
    first.config[PAGE_SERVICES_CONFIG_KEY] = {"stock_page_builder": lambda: "first"}
    second.config[PAGE_SERVICES_CONFIG_KEY] = {"stock_page_builder": lambda: "second"}

    with first.app_context():
        assert stock_page_layout() == "first"
    with second.app_context():
        assert stock_page_layout() == "second"


def _v5_config() -> pd.DataFrame:
    return _config(
        [
            ["BOOK_A", "XVA", "Activity 1", "SOG-A", "Core", "Rates"],
            ["BOOK_B", "XVA", "Activity 2", "SOG-B", "Core", "Credit"],
            ["BOOK_C", "Hedges", "Activity 3", "SOG-C", "Hedge", "FX"],
        ]
    )








def test_v5_stock_and_dstock_history_retain_business_day_gaps() -> None:
    history = _history_frame("2026-08-14", "2026-08-19").loc[
        lambda rows: rows["CRDS"].eq("CRDS-GAPPED")
    ]

    values = stock_value_history_frame(
        history,
        start_date="2026-08-17",
        end_date="2026-08-19",
    )
    figure = build_stock_value_history_figure(
        history,
        crds="CRDS-GAPPED",
        activity="Activity 2",
        start_date="2026-08-17",
        end_date="2026-08-19",
    )

    assert values[STOCK_DATE_COLUMN].dt.strftime("%Y-%m-%d").tolist() == [
        "2026-08-17",
        "2026-08-18",
        "2026-08-19",
    ]
    assert pd.isna(values.loc[0, "Stock"])
    assert values.loc[1, "Stock"] == 202.0
    assert pd.isna(values.loc[2, "Stock"])
    assert pd.isna(values.loc[1, "dStock"])
    assert pd.isna(values.loc[2, "dStock"])
    assert [trace.name for trace in figure.data] == ["Stock", "dStock"]
    assert figure.data[0].connectgaps is False
































