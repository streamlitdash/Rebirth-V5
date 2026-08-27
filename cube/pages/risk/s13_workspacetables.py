"""V5 promotions, exposure, and new-trade table presentation."""

from __future__ import annotations

import json
from typing import Mapping

import numpy as np
import pandas as pd
from dash import dash_table, html
from dash.dash_table.Format import Format, Scheme

from cube.domain.s01_schema import PORTFOLIO_FIELDS
from cube.domain.s05_newtrades import NEW_TRADES_SPLIT
from cube.ui.s02_aggregation import (
    format_number,
    number_sign_class,
    ordered_unique,
    row_key,
    should_show_sum,
)
from cube.ui.s01_constants import (
    METRIC_COLUMNS,
    RISK_TYPE_ORDER,
    TOP_EXPOSURE_GROUPS,
    TOP_EXPOSURE_LABELS,
)

from .s01_common import metric_title
from .s06_explorertables import build_tree_rows, metric_class

NEW_TRADE_SPLIT = NEW_TRADES_SPLIT
NEW_TRADE_DETAIL_COLUMNS = (
    "trade id",
    "row type",
    "underlying",
    "risk",
    "notional",
    "traded level",
    "portfolio",
    "trader code",
    "trader name",
    "trade time",
)
NEW_TRADE_DETAIL_LABELS = {
    "trade id": "TradeID",
    "row type": "TypeTrade",
    "underlying": "Underlying",
    "risk": "Risk",
    "notional": "NotionalTraded",
    "traded level": "TradedSpread",
    "portfolio": "Portfolio",
    "trader code": "TraderCode",
    "trader name": "TraderName",
    "trade time": "TradeTime",
}
TOP_PROMOTION_SIGNALS = {
    "vol-score": "Vol Score",
    "risk": "Risk",
    "drisk": "dRisk",
    "pl": "P&L",
}


def top_book_exposure_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate only exposures already promoted by the risk-threshold rules."""
    output_columns = [
        "Risk Type",
        "Risk Greek",
        "Label",
        "Underlying",
        "Risk",
        "dRisk",
        "P&L",
        "Score",
        "Vol Score",
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)
    source = frame.copy()
    if "vol score" not in source:
        source["vol score"] = 0.0
    required = [
        "risk type",
        "risk greek",
        "reported underlying",
        "promotion reason",
        "promotion score",
        "vol score",
        "risk",
        "drisk",
        "pl",
    ]
    missing = [column for column in required if column not in source]
    if missing:
        raise ValueError(f"Top book exposures require columns: {missing}")

    promoted = source.loc[
        source["promotion reason"].fillna("").astype(str).str.strip().ne("")
    ].copy()
    if promoted.empty:
        return pd.DataFrame(columns=output_columns)

    label_order = {"*": 0, "Big Risk": 1, "Big dRisk": 2, "Big PL": 3}

    def combined_label(values: pd.Series) -> str:
        unique = {
            token.strip()
            for value in values
            for token in str(value).replace("/", ",").split(",")
            if token.strip()
        }
        return ", ".join(
            sorted(unique, key=lambda value: (label_order.get(value, 99), value))
        )

    def signed_max_abs(values: pd.Series) -> float:
        numeric = pd.to_numeric(values, errors="coerce").dropna().to_numpy(dtype=float)
        if numeric.size == 0:
            return np.nan
        return float(numeric[np.argmax(np.abs(numeric))])

    aggregated = (
        promoted.groupby(
            ["risk type", "risk greek", "reported underlying"], dropna=False, sort=False
        )
        .agg(
            {
                "promotion reason": combined_label,
                "promotion score": "max",
                "vol score": signed_max_abs,
                "risk": lambda values: values.sum(min_count=1),
                "drisk": lambda values: values.sum(min_count=1),
                "pl": lambda values: values.sum(min_count=1),
            }
        )
        .reset_index()
    )
    aggregated["_risk_order"] = aggregated["risk type"].map(RISK_TYPE_ORDER).fillna(99)
    aggregated = aggregated.sort_values(
        [
            "_risk_order",
            "risk type",
            "risk greek",
            "promotion score",
            "reported underlying",
        ],
        ascending=[True, True, True, False, True],
        kind="mergesort",
    )
    return aggregated.rename(
        columns={
            "risk type": "Risk Type",
            "risk greek": "Risk Greek",
            "promotion reason": "Label",
            "reported underlying": "Underlying",
            "risk": "Risk",
            "drisk": "dRisk",
            "pl": "P&L",
            "promotion score": "Score",
            "vol score": "Vol Score",
        }
    )[output_columns].reset_index(drop=True)


def top_promotions_frame(
    frame: pd.DataFrame,
    *,
    limit: int = 500,
    signal: str = "vol-score",
) -> pd.DataFrame:
    """Rank committed promotions by the absolute selected signal.

    This function never classifies or recalculates promotion. It only groups
    position rows carrying the committed ``promotion reason`` and
    ``promotion score`` fields. Promotion Score is not used for ranking or
    displayed.
    """

    signal_column = TOP_PROMOTION_SIGNALS.get(str(signal))
    if signal_column is None:
        raise ValueError(f"Unknown Top Promotions signal: {signal}")

    promoted = top_book_exposure_frame(frame).rename(
        columns={
            "Label": "Promotion Reason",
            "Underlying": "Reported Underlying",
            "Score": "Promotion Score",
        }
    )
    output_columns = [
        "Rank",
        "Promotion Reason",
        "Risk Type",
        "Risk Greek",
        "Reported Underlying",
        "Risk",
        "dRisk",
        "P&L",
        "Vol Score",
    ]
    if promoted.empty:
        return pd.DataFrame(columns=output_columns)

    promoted["_signal_rank"] = pd.to_numeric(
        promoted[signal_column], errors="coerce"
    ).abs()
    promoted["_pl_rank"] = pd.to_numeric(promoted["P&L"], errors="coerce").abs()
    promoted = promoted.sort_values(
        [
            "_signal_rank",
            "_pl_rank",
            "Risk Type",
            "Risk Greek",
            "Reported Underlying",
        ],
        ascending=[False, False, True, True, True],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)
    promoted.insert(0, "Rank", promoted.index + 1)
    return promoted.head(max(1, int(limit)))[output_columns].copy()


def build_top_promotions_table(
    frame: pd.DataFrame,
    *,
    limit: int = 500,
    signal: str = "vol-score",
) -> html.Div:
    """Render a bounded flat rank with ten visible rows per native page."""

    ranked = top_promotions_frame(frame, limit=limit, signal=signal)
    if ranked.empty:
        return html.Div(
            "No committed promotions are available for this view.",
            className="empty-state",
            role="status",
        )

    headers = list(ranked.columns)
    number_format = Format(precision=2, scheme=Scheme.fixed, group=",")
    score_format = Format(precision=3, scheme=Scheme.fixed, group=",")
    numeric_columns = {"Rank", "Risk", "dRisk", "P&L", "Vol Score"}
    columns = []
    for column in headers:
        definition: dict[str, object] = {"name": column, "id": column}
        if column in numeric_columns:
            definition["type"] = "numeric"
            if column != "Rank":
                definition["format"] = (
                    score_format if column == "Vol Score" else number_format
                )
        columns.append(definition)

    return html.Div(
        [
            html.Div(
                f"{len(ranked):,} committed promotion identities",
                className="top-promotions-count",
            ),
            html.Div(
                dash_table.DataTable(
                    id="top-promotions-table",
                    columns=columns,
                    data=ranked.to_dict("records"),
                    page_action="native",
                    page_current=0,
                    page_size=10,
                    cell_selectable=False,
                    style_table={"overflowX": "auto"},
                    style_cell={
                        "padding": "8px 10px",
                        "borderBottom": "1px solid var(--outline-soft)",
                        "backgroundColor": "var(--surface)",
                        "color": "var(--text)",
                        "fontFamily": "inherit",
                        "fontSize": "13px",
                        "lineHeight": "1.3",
                        "textAlign": "left",
                        "whiteSpace": "nowrap",
                    },
                    style_header={
                        "backgroundColor": "var(--surface-muted)",
                        "color": "var(--text)",
                        "fontWeight": 850,
                    },
                    style_data_conditional=[
                        {
                            "if": {"column_id": column},
                            "textAlign": "right",
                        }
                        for column in numeric_columns
                    ],
                ),
                className="detail-table top-promotions-table",
            ),
        ],
        className="detail-table-wrap top-promotions-table-wrap",
    )


def top_book_hierarchy_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Explode existing underlying labels into Cross hierarchy memberships.

    Threshold classification remains authoritative.  An underlying carrying
    more than one existing label appears once beneath each applicable label,
    with the same already-aggregated exposure in each branch.
    """
    columns = [
        "label",
        "risk type",
        "risk greek",
        "reported underlying",
        "risk",
        "drisk",
        "pl",
    ]
    promoted = top_book_exposure_frame(frame)
    if promoted.empty:
        return pd.DataFrame(columns=columns)

    def labels(value: object) -> tuple[str, ...]:
        supplied = {
            token.strip()
            for token in str(value).replace("/", ",").split(",")
            if token.strip()
        }
        return tuple(label for label in TOP_EXPOSURE_LABELS if label in supplied)

    hierarchy = promoted.copy()
    hierarchy["label"] = hierarchy["Label"].map(labels)
    hierarchy = hierarchy.explode("label").dropna(subset=["label"])
    hierarchy = hierarchy.rename(
        columns={
            "Risk Type": "risk type",
            "Risk Greek": "risk greek",
            "Underlying": "reported underlying",
            "Risk": "risk",
            "dRisk": "drisk",
            "P&L": "pl",
        }
    )
    return hierarchy[columns].reset_index(drop=True)


def default_top_book_open_rows(frame: pd.DataFrame) -> list[str]:
    """Open Label, Risk Type, and Risk Greek when lazy Top Book is mounted.

    The disclosure itself remains closed and has no children on initial page
    load.  Once requested, the useful hierarchy is immediately visible through
    Underlying without requiring a long sequence of chevron clicks.
    """
    hierarchy = top_book_hierarchy_frame(frame)
    open_rows: list[str] = []
    for label in ordered_unique(hierarchy, "label"):
        label_context = {"label": label}
        open_rows.append(row_key(label_context))
        label_frame = hierarchy.loc[hierarchy["label"].eq(label)]
        for risk_type in ordered_unique(label_frame, "risk type"):
            risk_type_context = {**label_context, "risk type": risk_type}
            open_rows.append(row_key(risk_type_context))
            risk_type_frame = label_frame.loc[label_frame["risk type"].eq(risk_type)]
            for risk_greek in ordered_unique(risk_type_frame, "risk greek"):
                open_rows.append(
                    row_key({**risk_type_context, "risk greek": risk_greek})
                )
    return sorted(set(open_rows))


def build_top_book_exposures(
    frame: pd.DataFrame,
    open_rows: list[str] | None = None,
    *,
    view_token: str = "top-book",
) -> html.Div:
    """Render existing Big Risk/dRisk/PL labels as one Cross-only hierarchy."""
    hierarchy = top_book_hierarchy_frame(frame)
    if hierarchy.empty:
        return html.Div(
            "No labelled book exposures are available.",
            className="empty-state",
            role="status",
        )

    resolved_open_rows = (
        default_top_book_open_rows(frame) if open_rows is None else open_rows
    )
    columns = list(METRIC_COLUMNS)

    def exposure_cells(
        scoped: pd.DataFrame,
        context: dict[str, str],
    ) -> list[html.Td]:
        cells: list[html.Td] = []
        for column in columns:
            value = scoped[column].sum(min_count=1)
            cell_class = f"{metric_class(column, [])} {number_sign_class(value)}"
            display_value = (
                format_number(value, column=column)
                if should_show_sum(column, context)
                else ""
            )
            if not display_value:
                cells.append(
                    html.Td(
                        "",
                        className=f"{cell_class} metric-cell-inert",
                        **{"data-metric": column},
                    )
                )
                continue
            cells.append(
                html.Td(
                    html.Button(
                        display_value,
                        type="button",
                        className="metric-cell-button top-book-metric-cell-button",
                        title=(
                            "Use Shift, Control or Command with Enter or Space "
                            f"to select this {metric_title(column)} value"
                        ),
                        **{
                            "data-risk-key": row_key(
                                {
                                    key: item
                                    for key, item in context.items()
                                    if key != "label"
                                }
                            ),
                            "data-risk-metric": column,
                            "aria-label": (
                                f"{metric_title(column)} value {display_value}. "
                                "Use a modifier key with Enter or Space to select it."
                            ),
                        },
                    ),
                    className=cell_class,
                    **{"data-metric": column},
                )
            )
        return cells

    rows = build_tree_rows(
        hierarchy,
        columns,
        resolved_open_rows,
        [],
        groups=list(TOP_EXPOSURE_GROUPS),
        cell_builder=exposure_cells,
        toggle_type="top-book-row-toggle",
        cell_type="top-book-risk-cell",
        delegated_actions=True,
    )
    header = html.Thead(
        html.Tr(
            [
                html.Th(
                    "Label",
                    className="index-header",
                    scope="col",
                    **{"data-metric": "index"},
                )
            ]
            + [
                html.Th(
                    metric_title(column),
                    className=f"metric-header {metric_class(column, [])}",
                    scope="col",
                    **{"data-metric": column},
                )
                for column in columns
            ]
        )
    )
    return html.Div(
        [
            html.Div("", className="selection-summary", **{"aria-live": "polite"}),
            html.Table(
                [
                    html.Caption(
                        "Label, Risk Type, Risk Greek and Underlying Cross hierarchy",
                        className="sr-only",
                    ),
                    header,
                    html.Tbody(rows),
                ],
                className="risk-table top-book-table top-book-cross-table",
                role="treegrid",
                **{"aria-label": "Top Book exposure hierarchy"},
            ),
        ],
        className="risk-table-wrap top-book-table-wrap top-book-cross-wrap",
        **{
            "data-risk-view-token": view_token,
            "data-risk-open-rows": json.dumps(
                sorted(resolved_open_rows), separators=(",", ":")
            ),
        },
    )


def _normalize_new_trade_detail_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize a manager-owned trade-detail frame without mutating it.

    Trade metadata remains at position grain and is intentionally separate
    from the aggregated Risk Explorer frame.  Canonical connector names are
    accepted here so the UI does not force adapters to emit lowercase labels.
    """

    if not isinstance(frame, pd.DataFrame):
        raise TypeError("new_trade_details must be a pandas DataFrame")
    aliases = {
        **{
            field.external_name.strip().casefold(): field.key
            for field in PORTFOLIO_FIELDS
        },
        "portfolio": "portfolio",
        "tradeid": "trade id",
        "typetrade": "row type",
        "type trade": "row type",
        "notionaltraded": "notional",
        "notional traded": "notional",
        "tradedspread": "traded level",
        "traded spread": "traded level",
        "tradercode": "trader code",
        "tradername": "trader name",
        "tradetime": "trade time",
    }
    normalized = frame.copy()
    normalized.columns = [
        aliases.get(str(column).strip().casefold(), str(column).strip().casefold())
        for column in normalized.columns
    ]
    duplicates = normalized.columns[normalized.columns.duplicated()].unique().tolist()
    if duplicates:
        raise ValueError(
            f"Duplicate new-trade detail columns after normalization: {duplicates}"
        )
    if "notional" not in normalized:
        normalized["notional"] = np.nan
    missing = [
        column
        for column in NEW_TRADE_DETAIL_COLUMNS
        if column != "notional" and column not in normalized
    ]
    if missing:
        raise ValueError(f"Missing new-trade detail columns: {missing}")
    return normalized


def new_trade_detail_frame(
    frame: pd.DataFrame,
    context: Mapping[str, str],
    *,
    split: str = NEW_TRADE_SPLIT,
) -> pd.DataFrame:
    """Return New Trades display rows for the selected hierarchy scope.

    Every selected-context column carried by the detail frame is applied as an
    exact identity filter.  The manager should therefore enrich this frame
    with the output Risk identity and portfolio metadata before supplying it;
    the component never attempts a financial or reporting merge of its own.
    """

    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping")
    normalized = _normalize_new_trade_detail_columns(frame)
    selected_split = str(context.get("split", ""))
    if selected_split and selected_split != split:
        return normalized.iloc[0:0].loc[:, list(NEW_TRADE_DETAIL_COLUMNS)]

    scoped = normalized
    for column, value in context.items():
        if column == "split" or column not in scoped:
            continue
        scoped = scoped.loc[scoped[column].astype(str).eq(str(value))]
    return scoped.loc[:, list(NEW_TRADE_DETAIL_COLUMNS)].reset_index(drop=True)


def _format_new_trade_number(value: object, *, decimals: int) -> str:
    if pd.isna(value):
        return "—"
    if isinstance(value, (bool, np.bool_)):
        raise ValueError("new-trade numeric display values cannot be boolean")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("new-trade numeric display values must be numeric") from exc
    if not np.isfinite(numeric):
        raise ValueError("new-trade numeric display values must be finite")
    rendered = f"{numeric:,.{decimals}f}"
    if decimals:
        rendered = rendered.rstrip("0").rstrip(".")
    return "0" if rendered == "-0" else rendered


def _format_optional_new_trade_number(value: object, *, decimals: int) -> str:
    if pd.isna(value):
        return ""
    return _format_new_trade_number(value, decimals=decimals)


def _format_new_trade_text(value: object) -> str:
    if pd.isna(value) or not str(value).strip():
        return "—"
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ")
    return str(value)


def build_jtd_reference_table(
    frame: pd.DataFrame | None,
    underlying: str | None,
    *,
    error: str | None = None,
) -> html.Div:
    """Render every matching s13_jtd column and row as a flat detail table."""

    title = f"JTD reference — {underlying}" if underlying else "JTD reference"
    if error:
        content = html.Div(error, className="empty-state", role="status")
    elif frame is None or frame.empty:
        message = (
            f"No JTD reference rows for {underlying}."
            if underlying
            else "Select an Underlying row to show its JTD reference."
        )
        content = html.Div(message, className="empty-state", role="status")
    else:
        headers = [html.Th(str(column), scope="col") for column in frame.columns]
        rows = [
            html.Tr(
                [
                    html.Td("" if pd.isna(value) else str(value))
                    for value in record.values()
                ]
            )
            for record in frame.to_dict("records")
        ]
        content = html.Div(
            html.Table(
                [
                    html.Caption(title, className="sr-only"),
                    html.Thead(html.Tr(headers)),
                    html.Tbody(rows),
                ],
                className="detail-table jtd-reference-table",
            ),
            className="detail-table-wrap jtd-reference-table-wrap",
            tabIndex=0,
        )
    return html.Div(
        [html.H3(title, className="jtd-reference-title"), content],
        className="jtd-reference-card",
        **{"aria-label": title},
    )


def build_new_trade_detail_table(
    frame: pd.DataFrame,
    context: Mapping[str, str],
    *,
    split: str = NEW_TRADE_SPLIT,
) -> html.Div | None:
    """Build the descriptive trade table for a scope containing New Trades."""

    selected_split = str(context.get("split", ""))
    if selected_split and selected_split != split:
        return None
    scoped = new_trade_detail_frame(frame, context, split=split)
    header = html.Thead(
        html.Tr(
            [
                html.Th(NEW_TRADE_DETAIL_LABELS[column], scope="col")
                for column in NEW_TRADE_DETAIL_COLUMNS
            ]
        )
    )
    if scoped.empty:
        body = html.Tbody(
            html.Tr(
                html.Td(
                    "No matching new trades",
                    colSpan=len(NEW_TRADE_DETAIL_COLUMNS),
                    className="detail-table-empty",
                )
            )
        )
    else:
        rows = []
        for record in scoped.to_dict("records"):
            rows.append(
                html.Tr(
                    [
                        html.Td(_format_new_trade_text(record["trade id"])),
                        html.Td(_format_new_trade_text(record["row type"])),
                        html.Td(_format_new_trade_text(record["underlying"])),
                        html.Td(
                            _format_new_trade_number(record["risk"], decimals=1),
                            className="detail-number",
                        ),
                        html.Td(
                            _format_optional_new_trade_number(
                                record["notional"], decimals=0
                            ),
                            className="detail-number",
                        ),
                        html.Td(
                            _format_new_trade_number(
                                record["traded level"], decimals=6
                            ),
                            className="detail-number",
                        ),
                        html.Td(_format_new_trade_text(record["portfolio"])),
                        html.Td(_format_new_trade_text(record["trader code"])),
                        html.Td(_format_new_trade_text(record["trader name"])),
                        html.Td(_format_new_trade_text(record["trade time"])),
                    ]
                )
            )
        body = html.Tbody(rows)

    table = html.Table(
        [
            html.Caption("Selected new trades", className="sr-only"),
            header,
            body,
        ],
        className="detail-table",
    )
    return html.Div(
        [
            html.H3("New trades", className="detail-chart-title"),
            html.Div(table, className="detail-table-wrap"),
        ],
        className="detail-chart-card",
    )


__all__ = [
    "NEW_TRADE_DETAIL_COLUMNS",
    "NEW_TRADE_DETAIL_LABELS",
    "NEW_TRADE_SPLIT",
    "TOP_PROMOTION_SIGNALS",
    "build_jtd_reference_table",
    "build_new_trade_detail_table",
    "build_top_book_exposures",
    "build_top_promotions_table",
    "default_top_book_open_rows",
    "new_trade_detail_frame",
    "top_book_exposure_frame",
    "top_book_hierarchy_frame",
    "top_promotions_frame",
]
