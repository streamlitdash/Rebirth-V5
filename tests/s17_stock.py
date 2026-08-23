"""Contracts for dated Stock comparison, local filters, and lazy callbacks."""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace

import pandas as pd
import pytest
from dash import no_update
from flask import Flask

from rebirth.adapters import s08_stock as stock_adapter
from rebirth.adapters.s08_stock import (
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
from rebirth.domain.s01_schema import PORTFOLIO_MAPPED_COLUMN, UNMAPPED_VALUE
from rebirth.domain.s09_stock import (
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
from rebirth.services.s05_sources import build_production_refresh_manager
from rebirth.pages import PAGE_SERVICES_CONFIG_KEY
from rebirth.pages.stock import s04_callbacks as stock_callbacks
from rebirth.pages.stock import layout as stock_page_layout
from rebirth.pages.stock.s01_data import (
    STOCK_DISPLAY_COLUMNS,
    STOCK_FILTER_FIELDS,
    STOCK_FILTER_IDS,
    STOCK_SAVED_VIEW_CONTROLS,
    default_stock_activities,
    default_stock_dates,
    normalize_stock_date_pair,
    stock_display_rows,
    stock_history_identities,
)
from rebirth.pages.stock.s02_history import (
    SQLStockHistoryRepository,
    build_stock_value_history_figure,
    stock_history_date_range,
    stock_history_identity_from_token,
    stock_value_history_frame,
)
from rebirth.pages.stock.s03_view import (
    build_stock_page_shell,
)
from rebirth.pages.stock.s05_pivot import (
    STOCK_PIVOT_DEFAULT_ROWS,
    build_stock_pivot,
    stock_pivot_row_payload,
    toggle_stock_pivot_path,
)
from rebirth.app.s07_factory import build_app
from rebirth.ui.s03_filters import committed_filter_state
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


def test_checked_in_getstock_is_fake_validated_and_varies_by_date() -> None:
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
    assert current["CRDS"].str.startswith("FAKE_REPLACE_ME").all()
    assert len(current_identities - prior_identities) == 1
    assert len(prior_identities - current_identities) == 1
    stable = current_identities & prior_identities
    prior_stable = prior.set_index(list(STOCK_IDENTITY_COLUMNS)).loc[list(stable)]
    current_stable = current.set_index(list(STOCK_IDENTITY_COLUMNS)).loc[list(stable)]
    assert not current_stable[["Quantity", "Market Value"]].equals(
        prior_stable[["Quantity", "Market Value"]]
    )

    current.loc[:, "CPTY"] = "changed"
    assert GetStock("2026-08-21")["CPTY"].str.startswith("FAKE_REPLACE_ME").all()


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


@pytest.mark.parametrize(
    ("current", "prior"),
    [("2026-08-14", "2026-08-14"), ("2026-08-14", "2026-08-15")],
)
def test_stock_date_pair_requires_prior_before_current(
    current: str, prior: str
) -> None:
    with pytest.raises(ValueError, match="must be earlier"):
        normalize_stock_date_pair(current, prior)


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


def _v41_config() -> pd.DataFrame:
    return _config(
        [
            ["BOOK_A", "XVA", "Activity 1", "SOG-A", "Core", "Rates"],
            ["BOOK_B", "XVA", "Activity 2", "SOG-B", "Core", "Credit"],
            ["BOOK_C", "Hedges", "Activity 3", "SOG-C", "Hedge", "FX"],
        ]
    )


def test_v41_latest_projection_is_row_level_and_preserves_unmapped() -> None:
    current = _stock(
        [
            ["CRDS-1", "CPTY-A", "BOOK_A", "EURUSD", "USD", 110.0, 30.0],
            ["CRDS-2", "CPTY-B", "BOOK_A", "CDX", "USD", 50.0, 12.0],
            ["CRDS-3", "CPTY-C", "BOOK_UNKNOWN", "GILT", "GBP", 20.0, 8.0],
        ]
    )
    prior = current.copy()
    prior["Market Value"] = [25.0, 11.0, 10.0]
    mapped = map_stock_comparison_portfolios(current, prior, _v41_config())

    display = stock_display_rows(mapped)

    assert tuple(display.columns) == STOCK_DISPLAY_COLUMNS
    assert display["CRDS"].tolist() == ["CRDS-1", "CRDS-2", "CRDS-3"]
    assert display["Stock"].tolist() == [30.0, 12.0, 8.0]
    assert display["dStock"].tolist() == [5.0, 1.0, -2.0]
    assert display["Portfolio Mapped"].tolist() == [True, True, False]
    assert display.loc[2, "Activity"] == UNMAPPED_VALUE
    assert display.loc[0, "SubCategory"] == "Rates"


def test_v41_default_activities_resolve_exact_fixture_aliases() -> None:
    frame = pd.DataFrame(
        {
            "Activity": [
                "FAKE_REPLACE_ME - Activity 3",
                "Something Else",
                "FAKE_REPLACE_ME - Activity 1",
                "FAKE_REPLACE_ME - Activity 2",
            ]
        }
    )

    assert default_stock_activities(frame) == [
        "FAKE_REPLACE_ME - Activity 1",
        "FAKE_REPLACE_ME - Activity 2",
        "FAKE_REPLACE_ME - Activity 3",
    ]


def test_v41_history_selection_resolves_exact_source_identities() -> None:
    current, prior = _comparison_legs()
    mapped = map_stock_comparison_portfolios(current, prior, _v41_config())

    identities = stock_history_identities(
        mapped,
        crds="CRDS-1",
        activity="Activity 1",
    )

    assert identities == [
        {
            "CRDS": "CRDS-1",
            "CPTY": "CPTY-A",
            "Portfolio": "BOOK_A",
            "Instrument": "EURUSD",
            "Currency": "USD",
        }
    ]
    assert (
        stock_history_identities(
            mapped,
            crds="CRDS-4",
            activity=UNMAPPED_VALUE,
        )
        == []
    )  # prior-only rows are not part of latest Stock


def test_v41_stock_and_dstock_history_retain_business_day_gaps() -> None:
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


def test_v41_shell_is_one_page_with_editable_inline_history() -> None:
    shell = build_stock_page_shell(
        current_date="2026-08-14",
        prior_date="2026-08-13",
        history_available=True,
    )
    components = list(_walk(shell))
    ids = {getattr(component, "id", None) for component in components}

    assert {
        "stock-current-table",
        "stock-position-detail-table",
        "stock-pivot-rows",
        "stock-pivot-column",
        "stock-pivot-values",
        "stock-history-crds",
        "stock-history-activity",
        "stock-history-date-range",
        "stock-history-custom-range-control",
        "stock-history-load-button",
        "stock-history-chart",
        *(
            f"stock-period-{period}"
            for _label, period in (
                ("WTD", "wtd"),
                ("MTD", "mtd"),
                ("YTD", "ytd"),
                ("1Y", "1y"),
                ("All", "all"),
                ("Custom", "custom"),
            )
        ),
        *(STOCK_FILTER_IDS[field.key] for field in STOCK_FILTER_FIELDS),
    } <= ids
    assert {
        "stock-workspace-tabs",
        "stock-current-date",
        "stock-prior-date",
        "stock-compare-button",
        "stock-history-table",
        "stock-source-rows-button",
        "stock-promotion-threshold",
    }.isdisjoint(ids)
    load = next(
        component
        for component in components
        if getattr(component, "id", None) == "stock-history-load-button"
    )
    assert load.disabled is False
    custom_range = next(
        component
        for component in components
        if getattr(component, "id", None) == "stock-history-custom-range-control"
    )
    assert custom_range.style == {"display": "none"}


def test_v41_current_load_is_lazy_cached_and_defaults_activities_one_to_three() -> None:
    calls: list[tuple[str, pd.Timestamp]] = []
    current, prior = _comparison_legs()

    def stock_source(stock_date: pd.Timestamp) -> pd.DataFrame:
        calls.append(("stock", stock_date))
        return current if stock_date == pd.Timestamp("2026-08-14") else prior

    def config_source(stock_date: pd.Timestamp) -> pd.DataFrame:
        calls.append(("config", stock_date))
        return _v41_config()

    app = build_app(
        refresh_manager=build_production_refresh_manager(),
        stock_source=stock_source,
        stock_portfolio_source=config_source,
    )
    assert calls == []
    load = _callback_for_input(app, "stock-load-trigger")

    loaded = load(
        1,
        "0",
        0,
        {"current_date": "2026-08-14", "prior_date": "2026-08-13"},
    )
    cached = load(
        1,
        "0",
        0,
        {"current_date": "2026-08-14", "prior_date": "2026-08-13"},
    )
    filters = _callback_for_output(app, "stock-filter-ready", "data")
    filter_state = filters(
        loaded[0],
        None,
        0,
        *([] for _field in STOCK_FILTER_FIELDS),
        [],
        None,
        False,
    )

    assert calls == [
        ("stock", pd.Timestamp("2026-08-14")),
        ("stock", pd.Timestamp("2026-08-13")),
        ("config", pd.Timestamp("2026-08-14")),
    ]
    assert filter_state[1] == ["Activity 1", "Activity 2", "Activity 3"]
    assert cached[0] == loaded[0]


def test_v41_filter_and_row_click_use_cache_then_prefill_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, prior = _comparison_legs()
    calls = 0

    def source(stock_date: pd.Timestamp) -> pd.DataFrame:
        nonlocal calls
        calls += 1
        return current if stock_date == pd.Timestamp("2026-08-14") else prior

    app = build_app(
        refresh_manager=build_production_refresh_manager(),
        stock_source=source,
        stock_portfolio_source=lambda _date: _v41_config(),
    )
    load = _callback_for_input(app, "stock-load-trigger")
    token, *_rest = load(
        1,
        "0",
        0,
        {"current_date": "2026-08-14", "prior_date": "2026-08-13"},
    )
    render = _callback_for_output(app, "stock-current-table", "data")
    open_paths: list[str] = []
    for path in (
        '["Activity 1"]',
        '["Activity 1","Core"]',
        '["Activity 1","Core","CRDS-1"]',
    ):
        open_paths = toggle_stock_pivot_path(open_paths, path)
    committed = committed_filter_state(
        STOCK_SAVED_VIEW_CONTROLS,
        "__base__",
        [["Activity 1"], [], [], [], []],
        [],
    )
    (
        rows,
        _columns,
        detail,
        row_count,
        mapped,
        unmapped,
        crds_options,
        _activity_options,
    ) = render(
        token,
        committed,
        list(STOCK_PIVOT_DEFAULT_ROWS),
        "",
        ["Stock", "dStock"],
        open_paths,
    )
    selected_row = next(
        row for row in rows if stock_pivot_row_payload(row["id"])["kind"] == "history"
    )
    select = _callback_for_output(app, "stock-history-crds", "value")
    crds, activity, autoload = select(
        {
            "row_id": selected_row["id"],
            "row": rows.index(selected_row),
            "column": 0,
            "column_id": "Hierarchy",
        },
        token,
    )

    assert calls == 2
    assert row_count == "Rows: 1 of 3"
    assert mapped == "Mapped: 1"
    assert unmapped == "Unmapped: 0"
    assert len(detail) == 1
    assert len(crds_options) == 3  # manual history remains independent of table filter
    assert (crds, activity) == ("CRDS-1", "Activity 1")
    assert autoload == {"crds": "CRDS-1", "activity": "Activity 1"}

    monkeypatch.setattr(
        stock_callbacks,
        "ctx",
        SimpleNamespace(triggered_id="stock-pivot-open-paths"),
    )
    pivot_only = render(
        token,
        committed,
        list(STOCK_PIVOT_DEFAULT_ROWS),
        "",
        ["Stock", "dStock"],
        open_paths[:-1],
    )
    assert pivot_only[0]
    assert pivot_only[1]
    assert all(value is no_update for value in pivot_only[2:])


def test_stock_pivot_defaults_to_activity_bucket_crds_cpty_and_toggles() -> None:
    current, prior = _comparison_legs()
    mapped = map_stock_comparison_portfolios(current, prior, _v41_config())
    display = stock_display_rows(mapped)

    closed = build_stock_pivot(display)
    assert closed.columns[0]["name"] == "Activity / Bucket / CRDS / CPTY"
    assert [row["Hierarchy"] for row in closed.records] == [
        "▸ Activity 1",
        "▸ Activity 2",
        "▸ Activity 3",
    ]

    opened = toggle_stock_pivot_path([], '["Activity 1"]')
    activity_open = build_stock_pivot(display, open_paths=opened)
    assert any(
        row["Hierarchy"] == "\u00a0\u00a0▸ Core" for row in activity_open.records
    )
    assert sum(row["Stock"] for row in closed.records) == pytest.approx(
        display["Stock"].sum()
    )


def test_stock_pivot_column_split_and_values_are_bounded() -> None:
    current, prior = _comparison_legs()
    mapped = map_stock_comparison_portfolios(current, prior, _v41_config())
    display = stock_display_rows(mapped)

    pivot = build_stock_pivot(
        display,
        row_fields=["Activity", "CRDS"],
        column_field="Currency",
        value_fields=["Stock"],
    )

    assert [column["name"] for column in pivot.columns[2:]] == [
        ["GBP", "Stock"],
        ["USD", "Stock"],
    ]
    assert all("dStock" not in column["id"] for column in pivot.columns)


def test_stock_saved_view_contract_is_base_review_with_five_filters() -> None:
    assert STOCK_SAVED_VIEW_CONTROLS.base_label == "Base Review"
    assert tuple(STOCK_FILTER_IDS) == (
        "activity",
        "signoffgroup",
        "portfolio",
        "category",
        "subcategory",
    )
    page = build_stock_page_shell(
        current_date="2026-08-14",
        prior_date="2026-08-13",
    )
    saved_views = next(
        item
        for item in _walk(page)
        if getattr(item, "id", None) == "stock-saved-view-bar"
    )
    saved_ids = {getattr(item, "id", None) for item in _walk(saved_views)}
    assert set(STOCK_FILTER_IDS.values()) <= saved_ids
    assert STOCK_SAVED_VIEW_CONTROLS.exclude_id in saved_ids
    assert {
        STOCK_SAVED_VIEW_CONTROLS.apply_id,
        STOCK_SAVED_VIEW_CONTROLS.cancel_id,
        STOCK_SAVED_VIEW_CONTROLS.committed_state_id,
    } <= saved_ids


def test_v41_history_is_read_only_after_click_or_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, prior = _comparison_legs()
    history_calls: list[tuple[dict[str, str], pd.Timestamp, pd.Timestamp]] = []

    def history_source(identity, start_date, end_date):
        history_calls.append((dict(identity), start_date, end_date))
        rows = []
        for offset, stock_date in enumerate(pd.bdate_range(start_date, end_date)):
            rows.append(
                [
                    stock_date,
                    *(identity[column] for column in STOCK_IDENTITY_COLUMNS),
                    100.0 + offset,
                    1_000.0 + (10.0 * offset),
                ]
            )
        return pd.DataFrame(rows, columns=list(STOCK_HISTORY_COLUMNS))

    app = build_app(
        refresh_manager=build_production_refresh_manager(),
        stock_source=lambda stock_date: (
            current if stock_date == pd.Timestamp("2026-08-14") else prior
        ),
        stock_portfolio_source=lambda _date: _v41_config(),
        stock_history_source=history_source,
    )
    load = _callback_for_input(app, "stock-load-trigger")
    token, *_rest = load(
        1,
        "0",
        0,
        {"current_date": "2026-08-14", "prior_date": "2026-08-13"},
    )
    assert history_calls == []

    history_callback = _callback_for_output(app, "stock-history-chart", "figure")
    monkeypatch.setattr(
        stock_callbacks,
        "ctx",
        SimpleNamespace(triggered_id="stock-history-autoload"),
    )
    figure, status = history_callback(
        {"crds": "CRDS-1", "activity": "Activity 1"},
        0,
        0,
        "1y",
        "2025-08-15",
        "2026-08-14",
        "CRDS-1",
        "Activity 1",
        token,
    )

    assert len(history_calls) == 1
    assert [trace.name for trace in figure.data] == ["Stock", "dStock"]
    assert "Loaded" in status

    monkeypatch.setattr(
        stock_callbacks,
        "ctx",
        SimpleNamespace(triggered_id="stock-history-period"),
    )
    refreshed, refreshed_status = history_callback(
        {"crds": "CRDS-1", "activity": "Activity 1"},
        0,
        0,
        "mtd",
        "2025-08-15",
        "2026-08-14",
        "CRDS-1",
        "Activity 1",
        token,
    )

    assert len(history_calls) == 2
    assert [trace.name for trace in refreshed.data] == ["Stock", "dStock"]
    assert "2026-08-01" in refreshed_status


def test_v41_enabled_callback_outputs_have_one_owner_and_exist_in_shell() -> None:
    app = build_app(
        refresh_manager=build_production_refresh_manager(),
        stock_source=lambda _date: _stock(),
        stock_portfolio_source=lambda _date: _v41_config(),
        stock_history_source=lambda _identity, _start, _end: pd.DataFrame(
            columns=list(STOCK_HISTORY_COLUMNS)
        ),
    )
    with app.server.test_request_context("/stock"):
        shell = stock_page_layout()
    shell_ids = {
        str(component_id)
        for component in _walk(shell)
        if isinstance((component_id := getattr(component, "id", None)), str)
    }
    owners: dict[tuple[str, str], int] = {}
    for metadata in app.callback_map.values():
        for output in _callback_outputs(metadata):
            component_id = str(output.component_id)
            if component_id.startswith("stock-") and component_id != "stock-nav-link":
                key = (component_id, output.component_property)
                owners[key] = owners.get(key, 0) + 1
                assert component_id in shell_ids

    assert owners
    assert set(owners.values()) == {1}
    assert ("stock-current-table", "data") in owners
    assert ("stock-history-chart", "figure") in owners
    pivot_metadata = next(
        metadata
        for metadata in app.callback_map.values()
        if any(
            output.component_id == "stock-current-table"
            and output.component_property == "data"
            for output in _callback_outputs(metadata)
        )
    )
    pivot_inputs = {(item["id"], item["property"]) for item in pivot_metadata["inputs"]}
    assert (STOCK_SAVED_VIEW_CONTROLS.committed_state_id, "data") in pivot_inputs
    assert not any(
        (component_id, "value") in pivot_inputs
        for component_id in STOCK_FILTER_IDS.values()
    )
