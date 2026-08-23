"""Live inline P&L history figure and observed-series contracts."""

from __future__ import annotations

import pandas as pd
import pytest

from rebirth.domain.s08_pnl import (
    ACTIVITY,
    CATEGORY,
    COLOSSUS_TYPE,
    HISTORY_FILE_COLUMNS,
    HISTORY_MAPPING_STATUS,
    HISTORY_TYPE,
    PL_HISTORY_COLUMNS,
    PORTFOLIO,
    PREDICT_TYPE,
    SIGNOFF_GROUP,
    SUB_CATEGORY,
    select_pl_history_series,
)
from rebirth.pages.pnl.s03_history import build_pl_history_figure


def _history() -> pd.DataFrame:
    rows = [
        ["2026-01-05", COLOSSUS_TYPE, "IR", "Delta", "EUR", "XVA", "BOOK-A", 1.0],
        ["2026-01-05", PREDICT_TYPE, "IR", "Delta", "EUR", "XVA", "BOOK-A", 1.5],
        ["2026-08-03", COLOSSUS_TYPE, "IR", "Delta", "EUR", "XVA", "BOOK-A", 2.0],
        ["2026-08-03", PREDICT_TYPE, "IR", "Delta", "EUR", "XVA", "BOOK-A", 2.5],
        ["2026-08-10", COLOSSUS_TYPE, "IR", "Delta", "EUR", "XVA", "BOOK-A", 10.0],
        ["2026-08-10", PREDICT_TYPE, "IR", "Delta", "EUR", "XVA", "BOOK-A", 11.0],
        ["2026-08-12", COLOSSUS_TYPE, "IR", "Delta", "EUR", "XVA", "BOOK-A", 4.0],
        ["2026-08-13", COLOSSUS_TYPE, "IR", "Delta", "EUR", "XVA", "BOOK-A", 5.0],
        ["2026-08-13", PREDICT_TYPE, "IR", "Delta", "EUR", "XVA", "BOOK-A", 6.0],
        [
            "2026-08-14",
            COLOSSUS_TYPE,
            "FX",
            "Delta",
            "EUR/USD",
            "Spot",
            "BOOK-B",
            7.0,
        ],
        [
            "2026-08-14",
            PREDICT_TYPE,
            "FX",
            "Delta",
            "EUR/USD",
            "Spot",
            "BOOK-B",
            8.0,
        ],
    ]
    history = pd.DataFrame(
        rows,
        columns=["Market Date", HISTORY_TYPE, *HISTORY_FILE_COLUMNS],
    ).rename(columns={"Book": PORTFOLIO})
    history[ACTIVITY] = history[PORTFOLIO].map({"BOOK-A": "Rates", "BOOK-B": "FX"})
    history[SIGNOFF_GROUP] = history[PORTFOLIO].map(
        {"BOOK-A": "SOG-A", "BOOK-B": "SOG-B"}
    )
    history[CATEGORY] = "Core"
    history[SUB_CATEGORY] = "Synthetic"
    history[HISTORY_MAPPING_STATUS] = "Mapped"
    return history.loc[:, list(PL_HISTORY_COLUMNS)]


def test_inline_history_figure_plots_only_observed_rows() -> None:
    series = select_pl_history_series(_history(), ("SOG-A", "IR"))
    figure = build_pl_history_figure(series, path=("SOG-A", "IR"))

    assert [trace.name for trace in figure.data] == [COLOSSUS_TYPE, PREDICT_TYPE]
    assert list(figure.data[0].x) == [
        "2026-01-05",
        "2026-08-03",
        "2026-08-10",
        "2026-08-12",
        "2026-08-13",
    ]
    assert list(figure.data[1].x) == [
        "2026-01-05",
        "2026-08-03",
        "2026-08-10",
        "2026-08-13",
    ]
    assert "2026-08-11" not in {
        str(value) for trace in figure.data for value in trace.x
    }
    assert all(value != 0 for trace in figure.data for value in trace.y)
    assert figure.layout.title.text.endswith("SOG-A → IR")


def test_inline_history_figure_handles_one_source_empty_and_invalid_input() -> None:
    predict = select_pl_history_series(
        _history(),
        ("SOG-A", "IR"),
        PREDICT_TYPE,
    )
    predict_figure = build_pl_history_figure(predict, path=("SOG-A", "IR"))
    assert [trace.name for trace in predict_figure.data] == [PREDICT_TYPE]
    assert list(predict_figure.data[0].y) == [1.5, 2.5, 11.0, 6.0]

    empty = build_pl_history_figure(pd.DataFrame(), path=("SOG-A", "IR"))
    assert not empty.data
    assert empty.layout.annotations[0].text.startswith("Select a P&L cell")
    with pytest.raises(TypeError, match="DataFrame"):
        build_pl_history_figure([])  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="missing columns"):
        build_pl_history_figure(pd.DataFrame({"Market Date": ["2026-08-14"]}))
