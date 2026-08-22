"""Risk-page hierarchy, exposure, trade-detail, and compact table builders."""

from __future__ import annotations

import json
from typing import Callable, Mapping

import numpy as np
import pandas as pd
from dash import html

from core.s01_schema import PORTFOLIO_FIELDS
from core.s10_new_trades import NEW_TRADES_SPLIT
from shared.aggregation import (
    HierarchyAggregationIndex,
    aggregate_values,
    credit_measure_available,
    credit_measure_values,
    dimension_title,
    display_metric,
    format_number,
    number_sign_class,
    ordered_unique,
    row_key,
    selected_dimension,
    should_show_sum,
    tree_scope,
    visible_tree_level,
)
from shared.constants import (
    BASE_GROUPS,
    CREDIT_MEASURES,
    GRID_METRIC_COLUMNS,
    METRIC_BREAKDOWNS,
    METRIC_COLUMNS,
    RISK_TYPE_ORDER,
    ROW_TOGGLE_CLOSED_GLYPH,
    ROW_TOGGLE_OPEN_GLYPH,
    TOP_EXPOSURE_GROUPS,
    TOP_EXPOSURE_LABELS,
    get_active_groups,
)

from .common import _meaningful_tenor_mask, metric_title


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


def _active_groups_for_frame(
    frame: pd.DataFrame,
    promotion_enabled: bool,
    region_enabled: bool,
) -> list[str]:
    """Resolve the hierarchy without inventing Region for products that lack it."""
    region_available = bool(
        "region" in frame
        and frame["region"].fillna("").astype(str).str.strip().ne("").any()
    )
    return get_active_groups(
        promotion_enabled,
        region_enabled,
        region_available=region_available,
    )


def metric_class(column: str, expanded_metrics: list[str] | None = None) -> str:
    classes = ["metric-cell"]
    expanded = set(expanded_metrics or [])
    if column == "pl" or column.startswith("pl "):
        classes.append("pl-cell")
    if column == "pl":
        classes.append("pl-block-left")
        if "pl" not in expanded:
            classes.append("pl-block-right")
    if column == "pl hedges":
        classes.append("pl-block-right")
    if column.endswith("expo"):
        classes.extend(["metric-child", "metric-exposure"])
    if column.endswith("hedges"):
        classes.extend(["metric-child", "metric-hedges"])
    if column == "move":
        classes.append("market-block-left")
        if "move" not in expanded:
            classes.append("market-block-right")
    if column in {"open", "current"}:
        classes.extend(["metric-child", "market-child"])
    if column == "current":
        classes.append("market-block-right")
    return " ".join(classes)


def metric_header(column: str, expanded_metrics: list[str]) -> html.Th:
    if column in METRIC_BREAKDOWNS:
        expanded = column in set(expanded_metrics or [])
        breakdown_names = " and ".join(
            metric_title(value) for value in METRIC_BREAKDOWNS[column]
        )
        return html.Th(
            html.Button(
                f"{ROW_TOGGLE_OPEN_GLYPH if expanded else ROW_TOGGLE_CLOSED_GLYPH} "
                f"{metric_title(column)}",
                type="button",
                className="metric-header-button",
                title=f"{'Collapse' if expanded else 'Expand'} {breakdown_names}",
                **{
                    "data-risk-metric": column,
                    "aria-label": (
                        f"{'Collapse' if expanded else 'Expand'} {breakdown_names}"
                    ),
                    "aria-expanded": str(expanded).lower(),
                },
            ),
            className=f"metric-header {'pl-header' if column == 'pl' else ''} {metric_class(column, expanded_metrics)}",
            scope="col",
            **{"data-metric": column},
        )
    display = metric_title(column)
    return html.Th(
        display,
        className=f"metric-header {metric_class(column, expanded_metrics)}",
        scope="col",
        **{"data-metric": column},
    )


def build_columns(expanded_metrics: list[str] | None) -> list[str]:
    expanded = set(expanded_metrics or [])
    columns: list[str] = []
    for metric in GRID_METRIC_COLUMNS:
        columns.append(metric)
        if metric in expanded and metric in METRIC_BREAKDOWNS:
            columns.extend(METRIC_BREAKDOWNS[metric])
    return columns


def build_tree_rows(
    frame: pd.DataFrame,
    columns: list[str],
    open_rows: list[str] | None,
    expanded_metrics: list[str] | None,
    level: int = 0,
    depth: int = 0,
    context: dict[str, str] | None = None,
    groups: list[str] | None = None,
    cell_builder: Callable[[pd.DataFrame, dict[str, str]], list[html.Td]] | None = None,
    toggle_type: str = "row-toggle",
    cell_type: str = "risk-cell",
    aggregation_index: HierarchyAggregationIndex | None = None,
    delegated_actions: bool = False,
    underlying_sort_metric: str | None = None,
) -> list[html.Tr]:
    context = context or {}
    groups = BASE_GROUPS if groups is None else groups
    open_set = set(open_rows or [])
    level = visible_tree_level(frame, level, context, groups)
    group_column = groups[level] if level < len(groups) else None
    rows: list[html.Tr] = []

    if group_column is None:
        return rows

    for value in ordered_unique(
        frame,
        group_column,
        underlying_sort_metric=underlying_sort_metric,
    ):
        next_context = {**context, group_column: value}
        scoped = tree_scope(frame, group_column, value)
        if scoped.empty:
            continue
        key = row_key(next_context)
        next_level = visible_tree_level(scoped, level + 1, next_context, groups)
        can_expand = next_level < len(groups)
        is_open = key in open_set
        metrics = (
            (
                aggregation_index.aggregate(
                    scoped,
                    include_market=should_show_sum("move", next_context),
                )
                if aggregation_index is not None
                else aggregate_values(
                    scoped,
                    include_market=should_show_sum("move", next_context),
                )
            )
            if cell_builder is None
            else None
        )
        indent = 14 + depth * 18
        toggle_props: dict[str, object] = {
            "type": "button",
            "className": "row-toggle",
        }
        if can_expand:
            toggle_props.update(
                {
                    "title": ("Collapse" if is_open else "Expand") + f" {value}",
                    "aria-label": ("Collapse" if is_open else "Expand") + f" {value}",
                    "aria-expanded": str(is_open).lower(),
                }
            )
        else:
            toggle_props.update(
                {
                    "disabled": True,
                    "tabIndex": -1,
                    "aria-hidden": "true",
                }
            )
        if can_expand and not delegated_actions:
            toggle_props.update(
                {
                    "id": {"type": toggle_type, "key": key},
                    "n_clicks": 0,
                }
            )
        label = html.Button(
            (ROW_TOGGLE_OPEN_GLYPH if is_open else ROW_TOGGLE_CLOSED_GLYPH)
            if can_expand
            else "",
            **toggle_props,
        )
        index_children = [
            label,
            html.Span(str(value), className="row-label-text"),
        ]
        if group_column == "display bucket" and value != "Other":
            reasons = scoped["promotion reason"].dropna().astype(str)
            reason = next((item for item in reasons if item), "Top risk")
            index_children.append(html.Span(reason, className="promotion-badge"))
        cells = [
            html.Th(
                index_children,
                className=f"index-cell level-{level}",
                style={"paddingLeft": f"{indent}px"},
                scope="row",
                **{"data-metric": "index", "data-copy-value": str(value)},
            )
        ]
        if cell_builder is not None:
            cells.extend(cell_builder(scoped, next_context))
        else:
            for column in columns:
                metric_value = metrics[column]
                display_value = display_metric(
                    metrics,
                    column,
                    next_context,
                )
                cell_class = f"{metric_class(column, expanded_metrics)} {number_sign_class(metric_value)}"
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
                            className="metric-cell-button",
                            title=f"Open tenor detail for {metric_title(column)}",
                            **(
                                {
                                    "data-risk-metric": column,
                                    "aria-label": f"Open {metric_title(column)} detail for {value}: {display_value}",
                                }
                                if delegated_actions
                                else {
                                    "id": {
                                        "type": cell_type,
                                        "key": key,
                                        "metric": column,
                                    },
                                    "n_clicks": 0,
                                    "aria-label": f"Open {metric_title(column)} detail for {value}: {display_value}",
                                }
                            ),
                        ),
                        className=cell_class,
                        **{"data-metric": column},
                    )
                )
        row_kind = group_column.replace(" ", "-").replace("(", "").replace(")", "")
        row_classes = [
            "group-row",
            f"group-level-{depth}",
            f"group-kind-{row_kind}",
        ]
        if group_column in {"label", "risk type", "risk greek"}:
            row_classes.append("hierarchy-total-row")
        if group_column == "display bucket" and value != "Other":
            row_classes.append("promoted-underlying-row")
        row_props: dict[str, object] = {"aria-level": str(depth + 1)}
        if delegated_actions:
            row_props["data-risk-key"] = key
        if can_expand:
            row_props["aria-expanded"] = str(is_open).lower()
        rows.append(
            html.Tr(
                cells,
                className=" ".join(row_classes),
                **row_props,
            )
        )
        if can_expand and is_open:
            rows.extend(
                build_tree_rows(
                    scoped,
                    columns,
                    open_rows,
                    expanded_metrics,
                    next_level,
                    depth + 1,
                    next_context,
                    groups,
                    cell_builder,
                    toggle_type,
                    cell_type,
                    aggregation_index,
                    delegated_actions,
                    underlying_sort_metric=underlying_sort_metric,
                )
            )
    return rows


def build_risk_table(
    frame: pd.DataFrame,
    expanded_metrics: list[str] | None,
    open_rows: list[str] | None,
    *,
    dimension: str = "activity",
    toggle_type: str = "row-toggle",
    cell_type: str = "risk-cell",
    index_label: str = "Index",
    view_token: str | None = None,
    promotion_enabled: bool = True,
    region_enabled: bool = True,
    underlying_sort_metric: str | None = None,
) -> html.Div:
    if frame.empty:
        return html.Div(
            [
                html.Strong("No matching risk rows"),
                html.Span("Try clearing one or more filters."),
            ],
            className="empty-state",
            role="status",
        )
    columns = build_columns(expanded_metrics)
    aggregation_index = HierarchyAggregationIndex(frame)
    frame = aggregation_index.frame
    total_metrics = aggregation_index.aggregate(frame, include_market=False)
    total_cells = [
        html.Th(
            html.Span("TOTAL", className="row-label-text"),
            className="index-cell total-index",
            scope="row",
            **{"data-metric": "index", "data-copy-value": "TOTAL"},
        )
    ]
    for column in columns:
        metric_value = total_metrics[column]
        display_value = display_metric(total_metrics, column, {})
        cell_class = f"{metric_class(column, expanded_metrics)} {number_sign_class(metric_value)}"
        if not display_value:
            total_cells.append(
                html.Td(
                    "",
                    className=f"{cell_class} metric-cell-inert",
                    **{"data-metric": column},
                )
            )
            continue
        total_cells.append(
            html.Td(
                html.Button(
                    display_value,
                    type="button",
                    className="metric-cell-button",
                    title=f"Open tenor detail for {metric_title(column)}",
                    **{
                        "data-risk-metric": column,
                        "aria-label": f"Open total {metric_title(column)} detail: {display_value}",
                    },
                ),
                className=cell_class,
                **{"data-metric": column},
            )
        )
    body_rows = [
        html.Tr(
            total_cells,
            className="total-row",
            **{"data-risk-key": ""},
        )
    ]
    if not frame.empty:
        body_rows.extend(
            build_tree_rows(
                frame,
                columns,
                open_rows,
                expanded_metrics,
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                ),
                toggle_type=toggle_type,
                cell_type=cell_type,
                aggregation_index=aggregation_index,
                delegated_actions=True,
                underlying_sort_metric=underlying_sort_metric,
            )
        )
    header = html.Thead(
        html.Tr(
            [
                html.Th(
                    index_label,
                    className="index-header",
                    scope="col",
                    **{"data-metric": "index"},
                )
            ]
            + [metric_header(column, expanded_metrics or []) for column in columns]
        )
    )
    return html.Div(
        [
            html.Div("", className="selection-summary", **{"aria-live": "polite"}),
            html.Table(
                [
                    html.Caption(
                        f"{index_label} hierarchy and risk metrics",
                        className="sr-only",
                    ),
                    header,
                    html.Tbody(body_rows),
                ],
                className="risk-table",
                role="treegrid",
                **{"aria-label": f"{index_label} risk hierarchy"},
            ),
        ],
        className="risk-table-wrap",
        **(
            {
                "data-risk-view-token": view_token,
                "data-risk-open-rows": json.dumps(
                    sorted(open_rows or []), separators=(",", ":")
                ),
            }
            if view_token
            else {}
        ),
    )


def build_alt_risk_table(
    frame: pd.DataFrame,
    metric: str,
    open_rows: list[str] | None,
    dimension: str = "activity",
    index_label: str = "Index",
    view_token: str | None = None,
    promotion_enabled: bool = True,
    region_enabled: bool = True,
    underlying_sort_metric: str | None = None,
) -> html.Div:
    """Build the indexed hierarchy with the selected dimension pivoted into columns."""
    if frame.empty:
        return html.Div(
            [
                html.Strong("No matching risk rows"),
                html.Span("Try clearing one or more filters."),
            ],
            className="empty-state",
            role="status",
        )
    selected_metric = metric if metric in METRIC_COLUMNS else "risk"
    dimension_column = selected_dimension(dimension)
    dimension_values = (
        ordered_unique(frame, dimension_column) if not frame.empty else []
    )

    def dimension_cells(scoped: pd.DataFrame, context: dict[str, str]) -> list[html.Td]:
        by_dimension = (
            scoped.groupby(dimension_column)[selected_metric]
            .sum(min_count=1)
            .reindex(dimension_values)
        )
        values = [
            (dimension_value, float(by_dimension[dimension_value]))
            for dimension_value in dimension_values
        ]
        values.append(("Total", float(scoped[selected_metric].sum(min_count=1))))
        show_value = should_show_sum(selected_metric, context)
        cells: list[html.Td] = []
        for dimension_value, value in values:
            cell_context = (
                context
                if dimension_value == "Total"
                else {**context, dimension_column: dimension_value}
            )
            total_class = " total-column" if dimension_value == "Total" else ""
            display_value = format_number(value) if show_value else ""
            if not display_value:
                cells.append(
                    html.Td(
                        "",
                        className=f"metric-cell alt-dimension-cell metric-cell-inert{total_class} {number_sign_class(value)}",
                        **{"data-metric": f"{selected_metric}:{dimension_value}"},
                    )
                )
                continue
            cells.append(
                html.Td(
                    html.Button(
                        display_value,
                        type="button",
                        className="metric-cell-button",
                        title=f"Open {dimension_value} detail for {metric_title(selected_metric)}",
                        **{
                            "data-risk-key": (
                                row_key(cell_context) if cell_context else ""
                            ),
                            "data-risk-metric": selected_metric,
                            "aria-label": f"Open {dimension_value} {metric_title(selected_metric)} detail: {display_value}",
                        },
                    ),
                    className=f"metric-cell alt-dimension-cell{total_class} {number_sign_class(value)}",
                    **{"data-metric": f"{selected_metric}:{dimension_value}"},
                )
            )
        return cells

    total_cells = [
        html.Th(
            html.Span("TOTAL", className="row-label-text"),
            className="index-cell total-index",
            scope="row",
            **{"data-metric": "index", "data-copy-value": "TOTAL"},
        ),
        *dimension_cells(frame, {}),
    ]
    body_rows = [html.Tr(total_cells, className="total-row")]
    if not frame.empty:
        body_rows.extend(
            build_tree_rows(
                frame,
                [],
                open_rows,
                [],
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                ),
                cell_builder=dimension_cells,
                toggle_type="alt-row-toggle",
                cell_type="alt-risk-cell",
                delegated_actions=True,
                underlying_sort_metric=underlying_sort_metric,
            )
        )
    header = html.Thead(
        html.Tr(
            [
                html.Th(
                    index_label,
                    className="index-header",
                    scope="col",
                    **{"data-metric": "index"},
                )
            ]
            + [
                html.Th(
                    value,
                    className=(
                        "metric-header alt-dimension-header total-column"
                        if value == "Total"
                        else "metric-header alt-dimension-header"
                    ),
                    scope="col",
                    **{"data-metric": f"{selected_metric}:{value}"},
                )
                for value in [*dimension_values, "Total"]
            ]
        )
    )
    return html.Div(
        [
            html.Div(
                f"{metric_title(selected_metric)} by {dimension_title(dimension)}; Risk and dRisk show scoped sums from Risk Greek through every descendant level.",
                className="alt-table-note",
            ),
            html.Div("", className="selection-summary", **{"aria-live": "polite"}),
            html.Table(
                [
                    html.Caption(
                        f"{index_label} hierarchy by {dimension_title(dimension)}",
                        className="sr-only",
                    ),
                    header,
                    html.Tbody(body_rows),
                ],
                className="risk-table alt-risk-table",
                role="treegrid",
                **{"aria-label": f"{index_label} risk hierarchy"},
            ),
        ],
        className="risk-table-wrap",
        **(
            {
                "data-risk-view-token": view_token,
                "data-risk-open-rows": json.dumps(
                    sorted(open_rows or []), separators=(",", ":")
                ),
            }
            if view_token
            else {}
        ),
    )


def build_credit_multi_table(
    frame: pd.DataFrame,
    metric: str,
    open_rows: list[str] | None,
    dimension: str = "activity",
    view_token: str | None = None,
    promotion_enabled: bool | None = None,
    region_enabled: bool = True,
    underlying_sort_metric: str | None = None,
) -> html.Div:
    """Build Credit Multi: one selected metric across all credit measures."""
    if frame.empty:
        return html.Div(
            [
                html.Strong("No matching credit rows"),
                html.Span("Try clearing one or more filters."),
            ],
            className="empty-state",
            role="status",
        )
    selected_metric = metric if metric in METRIC_COLUMNS else "risk"
    measure_completeness = {
        measure: credit_measure_available(frame, measure) for measure in CREDIT_MEASURES
    }

    def measure_cells(
        scoped: pd.DataFrame,
        context: dict[str, str],
    ) -> list[html.Td]:
        show_value = should_show_sum(selected_metric, context)
        cells: list[html.Td] = []
        for measure in CREDIT_MEASURES:
            series = credit_measure_values(
                scoped,
                selected_metric,
                measure,
                connector_complete=measure_completeness[measure],
            )
            value = float(series.sum(min_count=1))
            display_value = (
                format_number(value, column=selected_metric) if show_value else ""
            )
            classes = f"metric-cell credit-measure-cell {number_sign_class(value)}"
            content = ""
            if display_value:
                content = html.Button(
                    display_value,
                    type="button",
                    className="metric-cell-button credit-measure-cell-button",
                    title=(
                        "Use Shift, Control or Command with Enter or Space "
                        f"to select this {metric_title(selected_metric)} value"
                    ),
                    **{
                        "data-risk-metric": selected_metric,
                        "data-risk-measure": measure,
                        "aria-label": (
                            f"{metric_title(selected_metric)} {measure} value "
                            f"{display_value}. Use a modifier key with Enter or "
                            "Space to select it."
                        ),
                    },
                )
            cells.append(
                html.Td(
                    content,
                    className=classes
                    if display_value
                    else f"{classes} metric-cell-inert",
                    **{"data-metric": f"{selected_metric}:{measure}"},
                )
            )
        return cells

    body_rows = [
        html.Tr(
            [
                html.Th(
                    html.Span("TOTAL", className="row-label-text"),
                    className="index-cell total-index",
                    scope="row",
                    **{"data-metric": "index", "data-copy-value": "TOTAL"},
                ),
                *measure_cells(frame, {}),
            ],
            className="total-row",
            **{"data-risk-key": ""},
        )
    ]
    body_rows.extend(
        build_tree_rows(
            frame,
            [],
            open_rows,
            [],
            groups=_active_groups_for_frame(
                frame,
                promotion_enabled,
                region_enabled,
            ),
            cell_builder=measure_cells,
            toggle_type="main-row-toggle",
            cell_type="main-risk-cell",
            delegated_actions=True,
            underlying_sort_metric=underlying_sort_metric,
        )
    )
    missing_measures = [
        measure
        for measure in CREDIT_MEASURES
        if not credit_measure_available(frame, measure)
    ]
    if selected_metric == "pl":
        availability_note = "P&L is measure-invariant, so the same portfolio P&L appears under every credit measure."
    elif missing_measures and selected_metric != "pl":
        availability_note = (
            "Unavailable connector measures are blank: "
            + ", ".join(missing_measures)
            + ". Any XGamma source sensitivities retain generic Risk."
        )
    else:
        availability_note = (
            "Connector measure columns drive ordinary Credit rows. Any XGamma "
            "source sensitivities retain generic Risk."
        )
    return html.Div(
        [
            html.Div(
                availability_note,
                className="alt-table-note credit-measure-note",
                role="status",
            ),
            html.Div("", className="selection-summary", **{"aria-live": "polite"}),
            html.Table(
                [
                    html.Caption(
                        f"Credit hierarchy with {metric_title(selected_metric)} by measure",
                        className="sr-only",
                    ),
                    html.Thead(
                        html.Tr(
                            [
                                html.Th(
                                    "Credit",
                                    className="index-header",
                                    scope="col",
                                    **{"data-metric": "index"},
                                )
                            ]
                            + [
                                html.Th(
                                    measure,
                                    className="metric-header credit-measure-header",
                                    scope="col",
                                    **{"data-metric": f"{selected_metric}:{measure}"},
                                )
                                for measure in CREDIT_MEASURES
                            ]
                        )
                    ),
                    html.Tbody(body_rows),
                ],
                className="risk-table credit-multi-table",
                role="treegrid",
                **{"aria-label": "Credit risk hierarchy"},
            ),
        ],
        className="risk-table-wrap credit-multi-wrap",
        **(
            {
                "data-risk-view-token": view_token,
                "data-risk-open-rows": json.dumps(
                    sorted(open_rows or []), separators=(",", ":")
                ),
            }
            if view_token
            else {}
        ),
    )


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


def build_small_table(frame: pd.DataFrame, metric: str) -> html.Table:
    show_source = "source type" in frame and frame["source type"].nunique() > 1
    show_underlying = "underlying" in frame and frame["underlying"].nunique() > 1
    tenor_columns = [
        (column, label)
        for column, label in (
            ("tenor swap", "Tenor Swap"),
            ("tenor option", "Tenor Option"),
        )
        if column in frame and _meaningful_tenor_mask(frame[column]).any()
    ]
    displayed_metrics = (
        ["move", "open", "current"]
        if metric == "move"
        else [
            metric,
            *METRIC_BREAKDOWNS.get(metric, []),
        ]
    )
    if frame.empty:
        return html.Table(
            [
                html.Tbody(
                    html.Tr(
                        html.Td(
                            "No rows",
                            colSpan=(
                                1
                                + len(tenor_columns)
                                + len(displayed_metrics)
                                + int(show_source)
                                + int(show_underlying)
                            ),
                            className="detail-table-empty",
                        )
                    )
                )
            ],
            className="detail-table",
        )
    header_cells = [
        *([html.Th("Source Type", scope="col")] if show_source else []),
        *([html.Th("Underlying", scope="col")] if show_underlying else []),
        *[html.Th(label, scope="col") for column, label in tenor_columns],
        *[
            html.Th(metric_title(column), className="detail-number", scope="col")
            for column in displayed_metrics
        ],
    ]
    header_cells.append(html.Th("Rows", className="detail-number", scope="col"))
    body_rows = []
    # Total row at the top
    total_cells = (
        [
            html.Th(
                "Total",
                scope="row",
                className="detail-source",
                style={"fontWeight": "bold"},
            ),
        ]
        if show_source
        else []
    )
    if show_underlying:
        total_cells.append(html.Th("", scope="row", className="detail-underlying"))
    for _column, label in tenor_columns:
        total_cells.append(html.Th("", scope="row", className="detail-tenor"))
    for column in displayed_metrics:
        col_sum = frame[column].sum()
        total_cells.append(
            html.Td(
                format_number(col_sum, column=column),
                className=f"detail-number {number_sign_class(col_sum)}",
                style={"fontWeight": "bold"},
            )
        )
    total_rows = frame["rows"].sum() if "rows" in frame else len(frame)
    total_cells.append(
        html.Td(
            format_number(total_rows, 0),
            className="detail-number number-positive",
            style={"fontWeight": "bold"},
        )
    )
    body_rows.append(html.Tr(total_cells))
    # Data rows
    for record in frame.to_dict("records"):
        cells = [
            *(
                [html.Td(record["source type"], className="detail-source")]
                if show_source
                else []
            ),
            *(
                [html.Td(record["underlying"], className="detail-underlying")]
                if show_underlying
                else []
            ),
            *[
                html.Td(record[column], className="detail-tenor")
                for column, _label in tenor_columns
            ],
        ]
        for column in displayed_metrics:
            cells.append(
                html.Td(
                    format_number(record[column], column=column),
                    className=f"detail-number {number_sign_class(record[column])}",
                )
            )
        cells.append(
            html.Td(
                format_number(record["rows"], 0),
                className="detail-number number-positive",
            )
        )
        body_rows.append(html.Tr(cells))
    return html.Table(
        [
            html.Caption("Selected tenor detail", className="sr-only"),
            html.Thead(html.Tr(header_cells)),
            html.Tbody(body_rows),
        ],
        className="detail-table",
    )


__all__ = [
    "NEW_TRADE_DETAIL_COLUMNS",
    "NEW_TRADE_DETAIL_LABELS",
    "NEW_TRADE_SPLIT",
    "build_alt_risk_table",
    "build_columns",
    "build_credit_multi_table",
    "build_new_trade_detail_table",
    "build_risk_table",
    "build_small_table",
    "build_top_book_exposures",
    "build_tree_rows",
    "default_top_book_open_rows",
    "metric_class",
    "metric_header",
    "new_trade_detail_frame",
    "top_book_exposure_frame",
    "top_book_hierarchy_frame",
]
