"""V4 promotions, exposure, and new-trade table presentation."""

from __future__ import annotations

import json
from typing import Mapping

import numpy as np
import pandas as pd
from dash import html

from rebirth.domain.schema import PORTFOLIO_FIELDS
from rebirth.domain.new_trades import NEW_TRADES_SPLIT
from rebirth.ui.aggregation import (
    format_number,
    number_sign_class,
    ordered_unique,
    row_key,
    should_show_sum,
)
from rebirth.ui.constants import (
    METRIC_COLUMNS,
    RISK_TYPE_ORDER,
    TOP_EXPOSURE_GROUPS,
    TOP_EXPOSURE_LABELS,
)

from .common import metric_title
from .explorer_tables import build_tree_rows, metric_class

NEW_TRADE_SPLIT = NEW_TRADES_SPLIT
NEW_TRADE_DETAIL_COLUMNS = (
    "trade id",
    "risk",
    "notional",
    "traded level",
    "trade time",
    "trader code",
    "trader name",
)
NEW_TRADE_DETAIL_LABELS = {
    "trade id": "Trade ID",
    "risk": "Risk",
    "notional": "Notional Traded",
    "traded level": "Traded Spread / Level",
    "trade time": "Trade Time",
    "trader code": "Trader Code",
    "trader name": "Trader Name",
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
    ]
    if frame.empty:
        return pd.DataFrame(columns=output_columns)
    required = [
        "risk type",
        "risk greek",
        "reported underlying",
        "promotion reason",
        "promotion score",
        "risk",
        "drisk",
        "pl",
    ]
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(f"Top book exposures require columns: {missing}")

    promoted = frame.loc[
        frame["promotion reason"].fillna("").astype(str).str.strip().ne("")
    ].copy()
    if promoted.empty:
        return pd.DataFrame(columns=output_columns)

    label_order = {"Big Risk": 0, "Big dRisk": 1, "Big PL": 2}

    def combined_label(values: pd.Series) -> str:
        unique = {str(value).strip() for value in values if str(value).strip()}
        return " / ".join(
            sorted(unique, key=lambda value: (label_order.get(value, 99), value))
        )

    aggregated = (
        promoted.groupby(
            ["risk type", "risk greek", "reported underlying"], dropna=False, sort=False
        )
        .agg(
            {
                "promotion reason": combined_label,
                "promotion score": "max",
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
        }
    )[output_columns].reset_index(drop=True)


_TOP_PROMOTION_SORT_COLUMNS = {
    "score": "Score",
    "pl": "P&L",
    "risk": "Risk",
    "drisk": "dRisk",
}


def top_promotions_frame(
    frame: pd.DataFrame,
    *,
    rank_by: str = "score",
    limit: int = 500,
) -> pd.DataFrame:
    """Return a deterministic flat rank from committed promotion columns.

    This function never classifies or recalculates promotion. It only groups
    position rows carrying the committed ``promotion reason`` and
    ``promotion score`` fields, then changes their presentation order.
    """

    selected_rank = rank_by if rank_by in _TOP_PROMOTION_SORT_COLUMNS else "score"
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
        "Promotion Score",
    ]
    if promoted.empty:
        return pd.DataFrame(columns=output_columns)

    metric_column = _TOP_PROMOTION_SORT_COLUMNS[selected_rank].replace(
        "Score", "Promotion Score"
    )
    promoted["_primary_rank"] = pd.to_numeric(
        promoted[metric_column], errors="coerce"
    ).abs()
    promoted["_score_rank"] = pd.to_numeric(
        promoted["Promotion Score"], errors="coerce"
    )
    promoted["_pl_rank"] = pd.to_numeric(promoted["P&L"], errors="coerce").abs()
    promoted = promoted.sort_values(
        [
            "_primary_rank",
            "_score_rank",
            "_pl_rank",
            "Risk Type",
            "Risk Greek",
            "Reported Underlying",
        ],
        ascending=[False, False, False, True, True, True],
        kind="mergesort",
        na_position="last",
    ).reset_index(drop=True)
    promoted.insert(0, "Rank", promoted.index + 1)
    return promoted.head(max(1, int(limit)))[output_columns].copy()


def build_top_promotions_table(
    frame: pd.DataFrame,
    *,
    rank_by: str = "score",
    limit: int = 500,
) -> html.Div:
    """Render committed promotions as a bounded semantic flat table."""

    ranked = top_promotions_frame(frame, rank_by=rank_by, limit=limit)
    if ranked.empty:
        return html.Div(
            "No committed promotions are available for this view.",
            className="empty-state",
            role="status",
        )

    headers = list(ranked.columns)
    numeric_columns = {"Risk", "dRisk", "P&L", "Promotion Score"}
    rows: list[html.Tr] = []
    for record in ranked.to_dict("records"):
        cells: list[html.Td] = []
        for column in headers:
            value = record[column]
            if column == "Rank":
                cells.append(html.Td(str(int(value)), className="promotion-rank"))
            elif column in numeric_columns:
                numeric = pd.to_numeric(value, errors="coerce")
                rendered = (
                    ""
                    if pd.isna(numeric)
                    else (
                        f"{float(numeric):,.3f}"
                        if column == "Promotion Score"
                        else format_number(float(numeric), column=column.casefold())
                    )
                )
                sign = "" if pd.isna(numeric) else number_sign_class(float(numeric))
                cells.append(
                    html.Td(
                        rendered,
                        className=f"promotion-number {sign}".strip(),
                    )
                )
            else:
                cells.append(html.Td(str(value), title=str(value)))
        rows.append(html.Tr(cells))

    return html.Div(
        [
            html.Div(
                f"{len(ranked):,} committed promotion identities",
                className="top-promotions-count",
            ),
            html.Table(
                [
                    html.Caption(
                        "Flat ranked Top Promotions",
                        className="sr-only",
                    ),
                    html.Thead(html.Tr([html.Th(column) for column in headers])),
                    html.Tbody(rows),
                ],
                className="top-promotions-table",
                **{"aria-label": "Top Promotions flat ranked table"},
            ),
        ],
        className="top-promotions-table-wrap",
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
        "notional traded": "notional",
        "traded spread": "traded level",
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
    """Return display columns for the selected New Trades hierarchy cell.

    Every selected-context column carried by the detail frame is applied as an
    exact identity filter.  The manager should therefore enrich this frame
    with the output Risk identity and portfolio metadata before supplying it;
    the component never attempts a financial or reporting merge of its own.
    """

    if not isinstance(context, Mapping):
        raise TypeError("context must be a mapping")
    normalized = _normalize_new_trade_detail_columns(frame)
    if str(context.get("split", "")) != split:
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


def build_new_trade_detail_table(
    frame: pd.DataFrame,
    context: Mapping[str, str],
    *,
    split: str = NEW_TRADE_SPLIT,
) -> html.Div | None:
    """Build the descriptive trade table for an explicit New Trades cell."""

    if str(context.get("split", "")) != split:
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
                        html.Td(_format_new_trade_text(record["trade time"])),
                        html.Td(_format_new_trade_text(record["trader code"])),
                        html.Td(_format_new_trade_text(record["trader name"])),
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
    "build_new_trade_detail_table",
    "build_top_book_exposures",
    "build_top_promotions_table",
    "default_top_book_open_rows",
    "new_trade_detail_frame",
    "top_book_exposure_frame",
    "top_book_hierarchy_frame",
    "top_promotions_frame",
]
