"""Stock hierarchy and flat-table presentation."""

from __future__ import annotations

import json
from typing import Sequence

import pandas as pd
from dash import dash_table, html

from rebirth.domain.schema import PORTFOLIO_MAPPED_COLUMN
from rebirth.domain.stock import (
    CURRENT_MARKET_VALUE_COLUMN,
    CURRENT_QUANTITY_COLUMN,
    MAPPED_STOCK_COMPARISON_COLUMNS,
    MARKET_VALUE_CHANGE_COLUMN,
    PRIOR_MARKET_VALUE_COLUMN,
    PRIOR_QUANTITY_COLUMN,
    QUANTITY_CHANGE_COLUMN,
    STOCK_CHANGE_COLUMN,
    STOCK_COMPARISON_NUMERIC_COLUMNS,
    STOCK_HIERARCHY_COLUMNS,
    STOCK_HIERARCHY_DEPTH_COLUMN,
    STOCK_HIERARCHY_LABEL_COLUMN,
    STOCK_HIERARCHY_LEAF_COLUMN,
    STOCK_HIERARCHY_LEVEL_COLUMN,
    STOCK_HIERARCHY_PATH_COLUMN,
    STOCK_HIERARCHY_POSITION_COUNT_COLUMN,
    STOCK_PROMOTION_BUCKET_COLUMN,
    STOCK_PROMOTION_THRESHOLD_DEFAULT,
    normalize_stock_promotion_threshold,
    summarize_visible_stock_hierarchy,
)
from rebirth.ui.constants import ROW_TOGGLE_CLOSED_GLYPH, ROW_TOGGLE_OPEN_GLYPH


STOCK_HIERARCHY_METRICS = (
    PRIOR_QUANTITY_COLUMN,
    CURRENT_QUANTITY_COLUMN,
    QUANTITY_CHANGE_COLUMN,
    PRIOR_MARKET_VALUE_COLUMN,
    CURRENT_MARKET_VALUE_COLUMN,
    MARKET_VALUE_CHANGE_COLUMN,
)
STOCK_HIERARCHY_TOGGLE_TYPE = "stock-hierarchy-toggle"


def _json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    display = frame.astype(object).where(pd.notna(frame), None)
    return display.to_dict("records")


def _hierarchy_metric_cell(value: object, *, label: str) -> html.Span:
    numeric = float(value)
    return html.Span(
        f"{numeric:,.2f}",
        className="copy-value stock-hierarchy-metric",
        title=f"{label}: {numeric:,.2f}",
        **{"data-stock-metric": label, "data-stock-value": str(numeric)},
    )


def stock_hierarchy_path_token(path: Sequence[str]) -> str:
    """Serialize one hierarchy path for Dash pattern IDs and browser state."""

    return json.dumps([str(value) for value in path], separators=(",", ":"))


def stock_hierarchy_path_from_token(value: object) -> tuple[str, ...] | None:
    """Parse one bounded path token without accepting arbitrary JSON shapes."""

    if not isinstance(value, str):
        return None
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(decoded, list) or not 1 <= len(decoded) <= len(
        STOCK_HIERARCHY_COLUMNS
    ):
        return None
    if any(not isinstance(item, str) or not item.strip() for item in decoded):
        return None
    return tuple(decoded)


def normalize_stock_hierarchy_open_tokens(values: object) -> list[str]:
    """Return unique valid path tokens in deterministic tree order."""

    if not isinstance(values, (list, tuple)):
        return []
    paths = {
        path
        for value in values
        if (path := stock_hierarchy_path_from_token(value)) is not None
    }
    return [
        stock_hierarchy_path_token(path)
        for path in sorted(
            paths, key=lambda item: (len(item), tuple(map(str.casefold, item)))
        )
    ]


def toggle_stock_hierarchy_open_tokens(
    current: object,
    requested_path_token: object,
) -> list[str]:
    """Open one visible branch or close it together with its descendants."""

    path = stock_hierarchy_path_from_token(requested_path_token)
    normalized = normalize_stock_hierarchy_open_tokens(current)
    paths = {
        parsed
        for token in normalized
        if (parsed := stock_hierarchy_path_from_token(token)) is not None
    }
    if path is None:
        return normalized
    if path in paths:
        paths = {candidate for candidate in paths if candidate[: len(path)] != path}
    else:
        paths.update(path[:depth] for depth in range(1, len(path) + 1))
    return [
        stock_hierarchy_path_token(candidate)
        for candidate in sorted(
            paths,
            key=lambda item: (len(item), tuple(map(str.casefold, item))),
        )
    ]


def _stock_number_sign_class(value: object) -> str:
    return "number-negative" if float(value) < 0 else "number-positive"


def _stock_hierarchy_row_cells(
    row: pd.Series,
    *,
    expandable: bool,
    is_open: bool,
    total: bool = False,
) -> list[object]:
    """Build semantic cells using the Risk Explorer table vocabulary."""

    level = str(row[STOCK_HIERARCHY_LEVEL_COLUMN])
    label = str(row[STOCK_HIERARCHY_LABEL_COLUMN])
    path = tuple(row[STOCK_HIERARCHY_PATH_COLUMN])
    depth = int(row[STOCK_HIERARCHY_DEPTH_COLUMN])
    index_children: list[object] = []
    if total:
        index_children.append(html.Span(label, className="row-label-text"))
    elif expandable:
        action = "Collapse" if is_open else "Expand"
        index_children.append(
            html.Button(
                ROW_TOGGLE_OPEN_GLYPH if is_open else ROW_TOGGLE_CLOSED_GLYPH,
                id={
                    "type": STOCK_HIERARCHY_TOGGLE_TYPE,
                    "path": stock_hierarchy_path_token(path),
                },
                n_clicks=0,
                className="row-toggle stock-hierarchy-toggle",
                type="button",
                title=f"{action} {level}: {label}",
                **{
                    "aria-label": f"{action} {level}: {label}",
                    "aria-expanded": str(is_open).lower(),
                },
            )
        )
    else:
        index_children.append(
            html.Button(
                "",
                type="button",
                className="row-toggle stock-hierarchy-toggle",
                disabled=True,
                tabIndex=-1,
                **{"aria-hidden": "true"},
            )
        )
    if not total:
        index_children.append(html.Span(label, className="row-label-text"))

    cells: list[object] = [
        html.Th(
            index_children,
            className=(
                "index-cell total-index stock-hierarchy-index"
                if total
                else f"index-cell level-{max(depth - 1, 0)} stock-hierarchy-index"
            ),
            scope="row",
            style={} if total else {"paddingLeft": f"{14 + max(depth - 1, 0) * 18}px"},
            title=f"{level}: {label}",
            **{"data-metric": "index", "data-copy-value": label},
        ),
        html.Td(
            html.Span(
                f"{int(row[STOCK_HIERARCHY_POSITION_COUNT_COLUMN]):,}",
                className="copy-value",
                title="Preserved Stock comparison rows",
            ),
            className="metric-cell stock-hierarchy-position-count number-positive",
            **{
                "data-metric": STOCK_HIERARCHY_POSITION_COUNT_COLUMN,
                "data-copy-value": str(int(row[STOCK_HIERARCHY_POSITION_COUNT_COLUMN])),
            },
        ),
    ]
    cells.extend(
        html.Td(
            _hierarchy_metric_cell(row[column], label=column),
            className=(
                "metric-cell stock-hierarchy-metric-cell "
                f"{_stock_number_sign_class(row[column])}"
            ),
            **{
                "data-metric": column,
                "data-copy-value": f"{float(row[column]):.12g}",
            },
        )
        for column in STOCK_HIERARCHY_METRICS
    )
    return cells


def build_stock_hierarchy(
    mapped_stock: pd.DataFrame,
    *,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
    open_path_tokens: object = None,
) -> html.Div:
    """Render only the currently visible portion of the Stock hierarchy."""

    component, _effective_open_tokens = build_stock_hierarchy_with_state(
        mapped_stock,
        promotion_threshold=promotion_threshold,
        open_path_tokens=open_path_tokens,
    )
    return component


def build_stock_hierarchy_with_state(
    mapped_stock: pd.DataFrame,
    *,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
    open_path_tokens: object = None,
) -> tuple[html.Div, list[str]]:
    """Render visible rows and return only open paths valid in that view."""

    threshold = normalize_stock_promotion_threshold(promotion_threshold)
    requested_tokens = normalize_stock_hierarchy_open_tokens(open_path_tokens)
    requested_paths = [
        path
        for token in requested_tokens
        if (path := stock_hierarchy_path_from_token(token)) is not None
    ]
    summary = summarize_visible_stock_hierarchy(
        mapped_stock,
        threshold,
        open_paths=requested_paths,
    )
    if summary.empty:
        return (
            html.Div(
                "No Stock rows are available for the stacked hierarchy.",
                id="stock-hierarchy-empty",
                className="static-data-empty",
            ),
            [],
        )

    root = summary.iloc[0]
    if tuple(root[STOCK_HIERARCHY_PATH_COLUMN]):  # pragma: no cover
        raise RuntimeError("Stock hierarchy summary is missing its total row")

    visible_expandable_paths = {
        tuple(row[STOCK_HIERARCHY_PATH_COLUMN])
        for _, row in summary.iterrows()
        if tuple(row[STOCK_HIERARCHY_PATH_COLUMN])
        and not bool(row[STOCK_HIERARCHY_LEAF_COLUMN])
    }
    effective_open_paths = set(requested_paths) & visible_expandable_paths
    effective_open_tokens = [
        stock_hierarchy_path_token(path)
        for path in sorted(
            effective_open_paths,
            key=lambda item: (len(item), tuple(map(str.casefold, item))),
        )
    ]

    def hierarchy_row(row: pd.Series) -> html.Tr:
        path = tuple(row[STOCK_HIERARCHY_PATH_COLUMN])
        depth = int(row[STOCK_HIERARCHY_DEPTH_COLUMN])
        expandable = not bool(row[STOCK_HIERARCHY_LEAF_COLUMN])
        is_open = path in effective_open_paths
        path_label = " / ".join(path)
        level = str(row[STOCK_HIERARCHY_LEVEL_COLUMN])
        row_kind = "-".join(level.casefold().replace("(", "").replace(")", "").split())
        classes = [
            "group-row",
            f"group-level-{max(depth - 1, 0)}",
            f"group-kind-{row_kind}",
            "stock-hierarchy-row",
            f"stock-hierarchy-depth-{depth}",
        ]
        if depth == 1:
            classes.append("hierarchy-total-row")
        if (
            level == STOCK_PROMOTION_BUCKET_COLUMN
            and str(row[STOCK_HIERARCHY_LABEL_COLUMN]) == "Promoted"
        ):
            classes.append("promoted-underlying-row")
        if not expandable:
            classes.append("stock-hierarchy-leaf")
        accessibility = {
            "aria-level": str(depth),
            **({"aria-expanded": str(is_open).lower()} if expandable else {}),
        }
        return html.Tr(
            _stock_hierarchy_row_cells(
                row,
                expandable=expandable,
                is_open=is_open,
            ),
            className=" ".join(classes),
            **{
                "data-stock-hierarchy-path": path_label,
                "data-stock-hierarchy-level": level,
                "data-stock-position-count": str(
                    int(row[STOCK_HIERARCHY_POSITION_COUNT_COLUMN])
                ),
                **accessibility,
            },
        )

    header = html.Thead(
        html.Tr(
            [
                html.Th(
                    "Stock hierarchy",
                    className="index-header stock-hierarchy-index-header",
                    scope="col",
                    **{"data-metric": "index"},
                ),
                html.Th(
                    "Rows",
                    className="metric-header stock-hierarchy-position-count-header",
                    scope="col",
                    title="Preserved Stock comparison rows",
                    **{"data-metric": STOCK_HIERARCHY_POSITION_COUNT_COLUMN},
                ),
                *[
                    html.Th(
                        column,
                        className="metric-header stock-hierarchy-metric-header",
                        scope="col",
                        title=column,
                        **{"data-metric": column},
                    )
                    for column in STOCK_HIERARCHY_METRICS
                ],
            ]
        )
    )
    total_row = html.Tr(
        _stock_hierarchy_row_cells(
            root,
            expandable=False,
            is_open=True,
            total=True,
        ),
        className="total-row stock-hierarchy-total-row",
        **{
            "data-stock-hierarchy-path": "",
            "data-stock-hierarchy-level": "Total",
            "data-stock-position-count": str(
                int(root[STOCK_HIERARCHY_POSITION_COUNT_COLUMN])
            ),
        },
    )
    visible_rows = [hierarchy_row(row) for _, row in summary.iloc[1:].iterrows()]
    component = html.Div(
        [
            html.Div("", className="selection-summary", **{"aria-live": "polite"}),
            html.Table(
                [
                    html.Caption(
                        "Stock hierarchy and dated comparison metrics",
                        className="sr-only",
                    ),
                    header,
                    html.Tbody([total_row, *visible_rows]),
                ],
                className="risk-table stock-hierarchy-table",
                role="treegrid",
                **{"aria-label": "Stock hierarchy and dated comparison metrics"},
            ),
        ],
        id="stock-hierarchy-stack",
        className="risk-table-wrap stock-hierarchy-table-wrap",
        **{
            "data-stock-promotion-threshold": str(threshold),
            "data-stock-open-paths": json.dumps(
                effective_open_tokens,
                separators=(",", ":"),
            ),
        },
    )
    return component, effective_open_tokens


def build_stock_hierarchy_panel(
    filtered: pd.DataFrame,
    *,
    has_unfiltered_rows: bool,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
    open_path_tokens: object = None,
) -> object:
    """Return the primary Stock hierarchy or the appropriate empty state."""

    return build_stock_hierarchy_panel_with_state(
        filtered,
        has_unfiltered_rows=has_unfiltered_rows,
        promotion_threshold=promotion_threshold,
        open_path_tokens=open_path_tokens,
    )[0]


def build_stock_hierarchy_panel_with_state(
    filtered: pd.DataFrame,
    *,
    has_unfiltered_rows: bool,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
    open_path_tokens: object = None,
) -> tuple[object, list[str]]:
    """Return the visible Stock tree and its pruned server-validated state."""

    if not filtered.empty:
        return build_stock_hierarchy_with_state(
            filtered,
            promotion_threshold=promotion_threshold,
            open_path_tokens=open_path_tokens,
        )
    message = (
        "No Stock rows match the selected filters."
        if has_unfiltered_rows
        else "GetStock returned no rows for either selected date."
    )
    return (
        html.Div(message, id="stock-hierarchy-empty", className="static-data-empty"),
        [],
    )


def build_stock_table(mapped_stock: pd.DataFrame) -> dash_table.DataTable:
    """Render one already-mapped and optionally filtered Stock comparison."""

    if not isinstance(mapped_stock, pd.DataFrame):
        raise TypeError("mapped_stock must be a pandas DataFrame")
    missing = [
        column
        for column in MAPPED_STOCK_COMPARISON_COLUMNS
        if column not in mapped_stock
    ]
    if missing:
        raise ValueError(f"mapped_stock is missing required columns: {missing}")
    frame = mapped_stock[list(MAPPED_STOCK_COMPARISON_COLUMNS)].copy()
    columns = [
        {
            "name": column,
            "id": column,
            **(
                {"type": "numeric", "format": {"specifier": ",.2f"}}
                if column in STOCK_COMPARISON_NUMERIC_COLUMNS
                else {}
            ),
        }
        for column in frame.columns
    ]
    return dash_table.DataTable(
        id="stock-table",
        columns=columns,
        data=_json_records(frame),
        editable=False,
        filter_action="native",
        filter_options={"case": "insensitive"},
        sort_action="native",
        sort_mode="multi",
        page_action="native",
        page_size=50,
        fixed_rows={"headers": True},
        style_table={"overflowX": "auto", "maxHeight": "72vh"},
        style_header={
            "backgroundColor": "#E3E5E7",
            "color": "#111111",
            "fontWeight": "700",
            "border": "1px solid #D9E0E7",
        },
        style_cell={
            "backgroundColor": "#FFFFFF",
            "color": "#111111",
            "border": "1px solid #E5E9ED",
            "fontFamily": "Inter, Segoe UI, Arial, sans-serif",
            "fontSize": "12px",
            "padding": "8px 10px",
            "textAlign": "left",
            "minWidth": "110px",
            "whiteSpace": "nowrap",
        },
        style_cell_conditional=[
            {
                "if": {"column_id": list(STOCK_COMPARISON_NUMERIC_COLUMNS)},
                "fontVariantNumeric": "tabular-nums",
                "textAlign": "right",
            }
        ],
        style_data_conditional=[
            {
                "if": {"filter_query": f"{{{PORTFOLIO_MAPPED_COLUMN}}} = false"},
                "backgroundColor": "#FFF3E0",
            },
            {
                "if": {
                    "filter_query": f"{{{MARKET_VALUE_CHANGE_COLUMN}}} < 0",
                    "column_id": MARKET_VALUE_CHANGE_COLUMN,
                },
                "color": "#B42318",
            },
            {
                "if": {"filter_query": f'{{{STOCK_CHANGE_COLUMN}}} = "Added"'},
                "backgroundColor": "#ECFDF3",
            },
            {
                "if": {"filter_query": f'{{{STOCK_CHANGE_COLUMN}}} = "Removed"'},
                "backgroundColor": "#FFF7ED",
            },
        ],
        tooltip_header={
            "Portfolio": "Stock Portfolio used for the governed mapping",
            PORTFOLIO_MAPPED_COLUMN: (
                "True when Portfolio exists in the authoritative mapping"
            ),
            CURRENT_MARKET_VALUE_COLUMN: "Market value on the selected current date",
            MARKET_VALUE_CHANGE_COLUMN: "Current market value minus prior market value",
        },
    )


def build_stock_table_panel(
    filtered: pd.DataFrame,
    *,
    has_unfiltered_rows: bool,
) -> object:
    if not filtered.empty:
        return build_stock_table(filtered)
    message = (
        "No Stock rows match the selected filters."
        if has_unfiltered_rows
        else "GetStock returned no rows for either selected date."
    )
    return html.Div(message, id="stock-empty-state", className="static-data-empty")


def build_stock_source_rows_section(message: str | None = None) -> html.Details:
    """Build the stable, explicitly on-demand source-row disclosure."""

    status = (
        str(message).strip()
        if message is not None
        else "Source comparison rows are not loaded. Load them only when needed."
    )
    return html.Details(
        [
            html.Summary("Source comparison rows"),
            html.Div(
                [
                    html.Button(
                        "Load filtered source rows",
                        id="stock-source-rows-button",
                        n_clicks=0,
                        className="refresh-button",
                        type="button",
                    ),
                    html.Div(
                        html.P(status, className="static-data-page-note"),
                        id="stock-table-panel",
                        className="static-data-panel",
                    ),
                ],
                className="stock-source-rows-controls",
            ),
        ],
        id="stock-source-comparison-details",
        open=False,
        className="aux-details",
    )


__all__ = [
    "STOCK_HIERARCHY_TOGGLE_TYPE",
    "build_stock_hierarchy",
    "build_stock_hierarchy_panel",
    "build_stock_hierarchy_panel_with_state",
    "build_stock_hierarchy_with_state",
    "build_stock_source_rows_section",
    "build_stock_table",
    "build_stock_table_panel",
    "normalize_stock_hierarchy_open_tokens",
    "stock_hierarchy_path_from_token",
    "stock_hierarchy_path_token",
    "toggle_stock_hierarchy_open_tokens",
]
