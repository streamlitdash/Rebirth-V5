"""Pure components and source boundary for the dated Stock comparison page."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pandas as pd
from dash import dash_table, dcc, html
import plotly.graph_objects as go

from adapters.s05_stock import (
    STOCK_DATE_COLUMN,
    STOCK_HISTORY_COLUMNS,
    StockConnectorAdapter,
    StockSource,
    build_stock_adapter,
    normalize_stock_date,
)
from core.s01_schema import PORTFOLIO_MAPPED_COLUMN
from core.s07_stock import (
    CURRENT_MARKET_VALUE_COLUMN,
    CURRENT_QUANTITY_COLUMN,
    MAPPED_STOCK_COMPARISON_COLUMNS,
    MARKET_VALUE_CHANGE_COLUMN,
    PRIOR_MARKET_VALUE_COLUMN,
    PRIOR_QUANTITY_COLUMN,
    QUANTITY_CHANGE_COLUMN,
    STOCK_CHANGE_COLUMN,
    STOCK_COLUMNS,
    STOCK_COMPARISON_NUMERIC_COLUMNS,
    STOCK_FILTER_COLUMN_BY_KEY,
    STOCK_HIERARCHY_COLUMNS,
    STOCK_HIERARCHY_DEPTH_COLUMN,
    STOCK_HIERARCHY_LABEL_COLUMN,
    STOCK_HIERARCHY_LEAF_COLUMN,
    STOCK_HIERARCHY_LEVEL_COLUMN,
    STOCK_HIERARCHY_PATH_COLUMN,
    STOCK_HIERARCHY_POSITION_COUNT_COLUMN,
    STOCK_IDENTITY_COLUMNS,
    STOCK_PROMOTION_BUCKET_COLUMN,
    STOCK_PROMOTION_THRESHOLD_DEFAULT,
    filter_stock_comparison,
    map_stock_comparison_portfolios,
    normalize_stock_promotion_threshold,
    summarize_visible_stock_hierarchy,
    validate_stock_frame,
)
from shared.constants import (
    FILTER_DIMENSION_FIELDS,
    ROW_TOGGLE_CLOSED_GLYPH,
    ROW_TOGGLE_OPEN_GLYPH,
)
from shared.saved_views import (
    SavedFilterViewControls,
    build_saved_filter_view_bar,
)


STOCK_FILTER_FIELDS = FILTER_DIMENSION_FIELDS
STOCK_FILTER_IDS = {
    field.key: f"stock-{field.dash_filter_id}" for field in STOCK_FILTER_FIELDS
}
STOCK_SAVED_VIEW_CONTROLS = SavedFilterViewControls(
    scope="stock",
    prefix="stock",
    fields=STOCK_FILTER_FIELDS,
    filter_ids=STOCK_FILTER_IDS,
    exclude_id="stock-filter-exclude-selected",
)
STOCK_FILTER_NOTE = (
    "Include mode uses OR within one filter (B or D) and AND across filters "
    "(Credit and Portfolio B or D). Exclude mode removes a row if it matches any "
    "selected value in any populated filter. Leave a filter blank for all values; "
    "Stock selections remain independent from Risk and P&L."
)
STOCK_HIERARCHY_METRICS = (
    PRIOR_QUANTITY_COLUMN,
    CURRENT_QUANTITY_COLUMN,
    QUANTITY_CHANGE_COLUMN,
    PRIOR_MARKET_VALUE_COLUMN,
    CURRENT_MARKET_VALUE_COLUMN,
    MARKET_VALUE_CHANGE_COLUMN,
)
STOCK_HIERARCHY_TOGGLE_TYPE = "stock-hierarchy-toggle"
STOCK_HISTORY_METRICS = ("Quantity", "Market Value")


@dataclass(frozen=True)
class StockPageData:
    """One server-owned, mapped comparison and the dates that produced it."""

    mapped_stock: pd.DataFrame
    current_date: pd.Timestamp
    prior_date: pd.Timestamp
    portfolio_date: pd.Timestamp


def default_stock_dates(reference_date: object) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the prior two business dates relative to a market/reference date."""

    reference = normalize_stock_date(reference_date)
    current_date = reference - pd.offsets.BDay(1)
    prior_date = current_date - pd.offsets.BDay(1)
    return current_date, prior_date


def normalize_stock_date_pair(
    current_date: object,
    prior_date: object,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Validate two distinct, ordered Stock comparison dates."""

    current = normalize_stock_date(current_date)
    prior = normalize_stock_date(prior_date)
    if prior >= current:
        raise ValueError("Prior Stock date must be earlier than current Stock date")
    return current, prior


def stock_history_date_range(end_date: object) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the bounded trailing-one-year window ending on ``end_date``."""

    end = normalize_stock_date(end_date)
    start = end - pd.DateOffset(years=1) + pd.offsets.BDay(1)
    return normalize_stock_date(start), end


def normalize_stock_history_frame(
    value: object,
    *,
    identity: Mapping[str, object],
    start_date: object,
    end_date: object,
) -> pd.DataFrame:
    """Validate one exact-identity history result at the page boundary."""

    start = normalize_stock_date(start_date)
    end = normalize_stock_date(end_date)
    expected_identity = stock_history_identity_from_token(
        stock_history_identity_token(identity)
    )
    if not isinstance(value, pd.DataFrame):
        raise TypeError("Stock history source must return a pandas DataFrame")
    if tuple(value.columns) != STOCK_HISTORY_COLUMNS:
        raise ValueError(
            "Stock history source columns must be exactly "
            f"{list(STOCK_HISTORY_COLUMNS)}"
        )
    source = value.copy(deep=True)
    if source.empty:
        source[STOCK_DATE_COLUMN] = pd.Series(
            index=source.index,
            dtype="datetime64[ns]",
        )
    else:
        source[STOCK_DATE_COLUMN] = source[STOCK_DATE_COLUMN].map(normalize_stock_date)
    expected_dates = pd.bdate_range(start=start, end=end)
    actual_dates = pd.DatetimeIndex(
        sorted(source[STOCK_DATE_COLUMN].drop_duplicates().tolist())
    )
    if not actual_dates.isin(expected_dates).all():
        raise ValueError("Stock history source returned dates outside the request")
    if source.duplicated([STOCK_DATE_COLUMN, *STOCK_IDENTITY_COLUMNS]).any():
        raise ValueError("Stock history source returned duplicate dated identities")
    for column, expected in expected_identity.items():
        if not source[column].eq(expected).all():
            raise ValueError(
                "Stock history source returned rows outside the selected identity"
            )

    if source.empty:
        return source.reset_index(drop=True)

    validated: list[pd.DataFrame] = []
    for stock_date, dated_rows in source.groupby(STOCK_DATE_COLUMN, sort=True):
        rows = validate_stock_frame(
            dated_rows.loc[:, list(STOCK_COLUMNS)],
            label=f"Stock history for {stock_date.date().isoformat()}",
        )
        rows.insert(0, STOCK_DATE_COLUMN, stock_date)
        validated.append(rows)
    return (
        pd.concat(validated, ignore_index=True)
        .sort_values(
            [STOCK_DATE_COLUMN, *STOCK_IDENTITY_COLUMNS],
            kind="stable",
        )
        .reset_index(drop=True)
    )


def stock_history_identity_token(identity: Mapping[str, object]) -> str:
    """Serialize one exact Stock identity independently from its display label."""

    if set(identity) != set(STOCK_IDENTITY_COLUMNS):
        raise ValueError(
            "Stock history identity must contain exactly "
            f"{list(STOCK_IDENTITY_COLUMNS)}"
        )
    payload: dict[str, str] = {}
    for column in STOCK_IDENTITY_COLUMNS:
        value = identity[column]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Stock history identity {column} must be non-blank text")
        payload[column] = value
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def stock_history_identity_from_token(token: object) -> dict[str, str]:
    """Decode and strictly validate one structured Stock identity token."""

    if not isinstance(token, str) or not token.strip():
        raise ValueError("Select one Stock history identity")
    try:
        payload = json.loads(token)
    except json.JSONDecodeError as exc:
        raise ValueError("Stock history identity token is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("Stock history identity token must contain an object")
    stock_history_identity_token(payload)
    return {column: payload[column] for column in STOCK_IDENTITY_COLUMNS}


def stock_history_identity_options(
    history: pd.DataFrame,
) -> list[dict[str, str]]:
    """Return labels and independent structured values for exact identities."""

    identities = history.loc[:, list(STOCK_IDENTITY_COLUMNS)].drop_duplicates()
    options = []
    for identity in identities.to_dict("records"):
        label = " | ".join(
            f"{column}={identity[column]}" for column in STOCK_IDENTITY_COLUMNS
        )
        options.append(
            {
                "label": label,
                "value": stock_history_identity_token(identity),
            }
        )
    return sorted(options, key=lambda option: option["label"].casefold())


def _selected_stock_history_rows(
    history: pd.DataFrame,
    identity_token: object,
) -> tuple[pd.DataFrame, dict[str, str]]:
    identity = stock_history_identity_from_token(identity_token)
    selected = history
    for column, value in identity.items():
        selected = selected.loc[selected[column].eq(value)]
    return selected.sort_values(STOCK_DATE_COLUMN, kind="stable"), identity


def build_stock_history_empty_figure(message: str) -> go.Figure:
    """Return a stable empty figure without loading historical data."""

    figure = go.Figure()
    figure.update_layout(
        template="plotly_white",
        height=360,
        margin={"l": 55, "r": 20, "t": 30, "b": 45},
        annotations=[
            {
                "text": str(message),
                "xref": "paper",
                "yref": "paper",
                "x": 0.5,
                "y": 0.5,
                "showarrow": False,
            }
        ],
    )
    return figure


def build_stock_history_figure(
    history: pd.DataFrame,
    *,
    identity_token: object,
    metric: object,
    start_date: object,
    end_date: object,
) -> go.Figure:
    """Plot one exact Stock identity while retaining missing daily observations."""

    if metric not in STOCK_HISTORY_METRICS:
        raise ValueError(f"Unknown Stock history metric: {metric!r}")
    selected, identity = _selected_stock_history_rows(history, identity_token)
    all_dates = pd.bdate_range(
        start=normalize_stock_date(start_date),
        end=normalize_stock_date(end_date),
    )
    values = selected.set_index(STOCK_DATE_COLUMN)[str(metric)].reindex(all_dates)
    figure = go.Figure(
        go.Scatter(
            x=all_dates,
            y=values,
            mode="lines+markers",
            connectgaps=False,
            name=str(metric),
            hovertemplate=(
                "%{x|%Y-%m-%d}<br>" + f"{metric}: " + "%{y:,.2f}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        template="plotly_white",
        height=360,
        margin={"l": 65, "r": 20, "t": 55, "b": 45},
        title=" | ".join(identity[column] for column in STOCK_IDENTITY_COLUMNS),
        xaxis_title=STOCK_DATE_COLUMN,
        yaxis_title=str(metric),
        hovermode="x unified",
    )
    return figure


def build_stock_history_table(
    history: pd.DataFrame,
    *,
    identity_token: object,
) -> dash_table.DataTable:
    """Build raw historical rows for one exact Stock identity."""

    selected, _identity = _selected_stock_history_rows(history, identity_token)
    display = selected.copy(deep=True)
    display[STOCK_DATE_COLUMN] = display[STOCK_DATE_COLUMN].dt.strftime("%Y-%m-%d")
    return dash_table.DataTable(
        id="stock-history-table",
        columns=[{"name": column, "id": column} for column in STOCK_HISTORY_COLUMNS],
        data=_json_records(display.loc[:, list(STOCK_HISTORY_COLUMNS)]),
        page_action="native",
        page_size=15,
        sort_action="native",
        filter_action="native",
        style_table={"overflowX": "auto"},
        style_cell={
            "padding": "8px 10px",
            "textAlign": "left",
            "minWidth": "110px",
            "whiteSpace": "nowrap",
        },
        style_cell_conditional=[
            {
                "if": {"column_id": list(STOCK_HISTORY_METRICS)},
                "fontVariantNumeric": "tabular-nums",
                "textAlign": "right",
            }
        ],
    )


def _json_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    display = frame.astype(object).where(pd.notna(frame), None)
    return display.to_dict("records")


def stock_filter_map(
    values: Sequence[Sequence[str] | None],
) -> dict[str, list[str]]:
    """Bind Stock-only dropdown values to governed reporting keys."""

    return {
        field.key: list(selected or [])
        for field, selected in zip(STOCK_FILTER_FIELDS, values, strict=True)
    }


def stock_exclude_selected(value: Sequence[str] | None) -> bool:
    """Normalize the Stock-local exclusion checklist value."""

    return "exclude" in (value or [])


def stock_filter_options(
    mapped_stock: pd.DataFrame,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
) -> tuple[dict[str, list[dict[str, str]]], dict[str, list[str]]]:
    """Return full-snapshot options and selected values that remain valid."""

    selected = dict(selected_filters or {})
    unknown = sorted(set(selected) - set(STOCK_FILTER_COLUMN_BY_KEY))
    if unknown:
        raise ValueError(f"Unknown Stock reporting-dimension filters: {unknown}")
    options: dict[str, list[dict[str, str]]] = {}
    valid: dict[str, list[str]] = {}
    for field in STOCK_FILTER_FIELDS:
        column = field.external_name
        available = sorted(
            mapped_stock[column].dropna().astype(str).unique().tolist(),
            key=str.casefold,
        )
        options[field.key] = [{"label": value, "value": value} for value in available]
        valid[field.key] = [
            str(value)
            for value in (selected.get(field.key) or [])
            if str(value) in available
        ]
    return options, valid


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


def build_stock_history_section(*, available: bool) -> html.Details:
    """Build a stable, explicitly loaded trailing-one-year history section."""

    status = (
        "History is not loaded. Load the trailing 1Y only when needed."
        if available
        else "Stock history is not configured for this application."
    )
    return html.Details(
        [
            html.Summary("Historical Stock"),
            dcc.Store(id="stock-history-loaded-range", data=None),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label(
                                "Stock identity", htmlFor="stock-history-identity"
                            ),
                            dcc.Dropdown(
                                id="stock-history-identity",
                                options=[],
                                value=None,
                                clearable=False,
                                disabled=not available,
                                placeholder="Load history to select an identity",
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Metric", htmlFor="stock-history-metric"),
                            dcc.Dropdown(
                                id="stock-history-metric",
                                options=[
                                    {"label": metric, "value": metric}
                                    for metric in STOCK_HISTORY_METRICS
                                ],
                                value="Market Value",
                                clearable=False,
                                disabled=not available,
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Period", htmlFor="stock-history-load-button"),
                            html.Button(
                                "Load trailing 1Y history",
                                id="stock-history-load-button",
                                n_clicks=0,
                                type="button",
                                disabled=True,
                                className="refresh-button",
                            ),
                        ],
                        className="control-field stock-compare-action",
                    ),
                ],
                className="controls top-controls",
            ),
            html.P(
                status,
                id="stock-history-status",
                className="static-data-page-note",
                role="status",
            ),
            dcc.Loading(
                html.Div(
                    [
                        dcc.Graph(
                            id="stock-history-chart",
                            figure=build_stock_history_empty_figure(status),
                            config={"displaylogo": False, "responsive": True},
                        ),
                        html.Div(
                            html.P(status, className="static-data-page-note"),
                            id="stock-history-table-panel",
                            className="static-data-panel",
                        ),
                    ]
                ),
                delay_show=120,
            ),
        ],
        id="stock-history-details",
        open=False,
        className="aux-details",
    )


def stock_summary_text(
    filtered: pd.DataFrame,
    *,
    total_rows: int,
    current_date: pd.Timestamp,
    prior_date: pd.Timestamp,
) -> tuple[str, str, str]:
    """Return the three page counters for one filtered Stock view."""

    mapped_count = int(filtered[PORTFOLIO_MAPPED_COLUMN].eq(True).sum())
    unmapped_count = len(filtered) - mapped_count
    rows = (
        f"Rows: {len(filtered):,} of {total_rows:,} · Current "
        f"{current_date.date().isoformat()} · Prior {prior_date.date().isoformat()}"
    )
    return rows, f"Mapped: {mapped_count:,}", f"Unmapped: {unmapped_count:,}"


def build_stock_page_from_data(
    page_data: StockPageData,
    *,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
) -> html.Main:
    """Build Stock comparison content from one server-owned page snapshot."""

    filtered = filter_stock_comparison(
        page_data.mapped_stock,
        dict(selected_filters or {}),
        exclude_selected=exclude_selected,
    )
    rows, mapped, unmapped = stock_summary_text(
        filtered,
        total_rows=len(page_data.mapped_stock),
        current_date=page_data.current_date,
        prior_date=page_data.prior_date,
    )
    return html.Main(
        [
            html.Div(
                [
                    html.Span(
                        rows,
                        id="stock-row-count",
                        className="static-data-row-count",
                    ),
                    html.Span(
                        mapped,
                        id="stock-mapped-count",
                        className="static-data-col-count",
                    ),
                    html.Span(
                        unmapped,
                        id="stock-unmapped-count",
                        className="static-data-col-count",
                    ),
                ],
                className="static-data-meta",
            ),
            html.Div(
                [
                    html.H3("Stacked Stock", className="static-data-page-title"),
                    html.P(
                        "Activity → Promotion Bucket → Group (Temporary Fixture) → CPTY → CRDS. "
                        "The temporary Group is currency-based; promotion uses absolute net current market value at the displayed Stock-name identity after filters. Every level is ordered by absolute current Stock descending.",
                        id="stock-hierarchy-rule-note",
                        className="static-data-page-note",
                    ),
                    html.Div(
                        build_stock_hierarchy_panel(
                            filtered,
                            has_unfiltered_rows=not page_data.mapped_stock.empty,
                            promotion_threshold=promotion_threshold,
                        ),
                        id="stock-hierarchy-view",
                    ),
                ],
                id="stock-hierarchy-panel",
                className="static-data-panel",
            ),
            build_stock_source_rows_section(),
        ],
        id="stock-comparison-view",
        **{
            "data-stock-columns": ",".join(STOCK_COLUMNS),
            "data-current-date": page_data.current_date.date().isoformat(),
            "data-prior-date": page_data.prior_date.date().isoformat(),
        },
    )


def build_stock_page_placeholder(
    message: str,
    *,
    error: bool = False,
) -> list[object]:
    """Keep every Stock callback target mounted before data is available.

    Native Dash Pages can remount Stock while a dated load from an earlier
    mount is completing. The filter callback therefore targets only nodes
    that exist in loading, error, and loaded states.
    """

    status = str(message).strip() or "Stock data is not available yet."
    return [
        (
            html.P(
                status,
                id="stock-load-error",
                className="static-data-empty",
                role="alert",
            )
            if error
            else None
        ),
        html.Div(
            [
                html.Span(
                    "Rows: loading…",
                    id="stock-row-count",
                    className="static-data-row-count",
                ),
                html.Span(
                    "Mapped: loading…",
                    id="stock-mapped-count",
                    className="static-data-col-count",
                ),
                html.Span(
                    "Unmapped: loading…",
                    id="stock-unmapped-count",
                    className="static-data-col-count",
                ),
            ],
            className="static-data-meta",
        ),
        html.Div(
            [
                html.H3("Stacked Stock", className="static-data-page-title"),
                html.P(
                    "Activity → Promotion Bucket → Group (Temporary Fixture) → CPTY → CRDS. "
                    "The temporary Group is currency-based; promotion uses absolute net current market value at the displayed Stock-name identity after filters. Every level is ordered by absolute current Stock descending.",
                    id="stock-hierarchy-rule-note",
                    className="static-data-page-note",
                ),
                html.Div(
                    html.P(status, className="static-data-page-note"),
                    id="stock-hierarchy-view",
                ),
            ],
            id="stock-hierarchy-panel",
            className="static-data-panel",
        ),
        build_stock_source_rows_section(status),
    ]


def build_stock_page_shell(
    *,
    current_date: object,
    prior_date: object,
    history_available: bool = False,
) -> html.Main:
    """Paint the complete Stock control shell before any connector work."""

    current, prior = normalize_stock_date_pair(current_date, prior_date)
    filter_controls = [
        html.Div(
            [
                html.Label(field.label, htmlFor=STOCK_FILTER_IDS[field.key]),
                dcc.Dropdown(
                    id=STOCK_FILTER_IDS[field.key],
                    options=[],
                    multi=True,
                    placeholder=f"All {field.label.casefold()} values",
                    value=[],
                ),
            ],
            className="control-field",
        )
        for field in STOCK_FILTER_FIELDS
    ]
    return html.Main(
        [
            dcc.Store(id="stock-loaded-revision", data=-1),
            dcc.Store(id="stock-loaded-dates", data=None),
            dcc.Store(id="stock-hierarchy-open-paths", data=[]),
            dcc.Store(
                id="stock-source-rows-state",
                data={"requested": False, "loaded_dates": None},
            ),
            dcc.Store(
                id="stock-dimension-filter-store",
                data={
                    "filters": {field.key: [] for field in STOCK_FILTER_FIELDS},
                    "exclude_selected": False,
                    "promotion_threshold": STOCK_PROMOTION_THRESHOLD_DEFAULT,
                },
            ),
            dcc.Interval(
                id="stock-load-trigger",
                interval=1_000,
                n_intervals=0,
                disabled=False,
            ),
            html.Div(
                [
                    html.H2("Stock", className="static-data-page-title"),
                    html.P(
                        "Compare two dated Stock snapshots, enriched through the authoritative Portfolio mapping.",
                        className="static-data-page-note",
                    ),
                ],
                className="static-data-header",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label(
                                "Current stock date", htmlFor="stock-current-date"
                            ),
                            dcc.DatePickerSingle(
                                id="stock-current-date",
                                date=current.date().isoformat(),
                                display_format="YYYY-MM-DD",
                                clearable=False,
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Prior stock date", htmlFor="stock-prior-date"),
                            dcc.DatePickerSingle(
                                id="stock-prior-date",
                                date=prior.date().isoformat(),
                                display_format="YYYY-MM-DD",
                                clearable=False,
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Compare", htmlFor="stock-compare-button"),
                            html.Button(
                                "Compare dates",
                                id="stock-compare-button",
                                n_clicks=0,
                                type="button",
                                className="refresh-button stock-compare-button",
                            ),
                        ],
                        className="control-field stock-compare-action",
                    ),
                    html.Div(
                        [
                            html.Label(
                                "Promotion threshold",
                                htmlFor="stock-promotion-threshold",
                            ),
                            dcc.Input(
                                id="stock-promotion-threshold",
                                type="number",
                                min=0,
                                step=1_000,
                                value=STOCK_PROMOTION_THRESHOLD_DEFAULT,
                                debounce=True,
                            ),
                            html.Small(
                                "Promote when |Current Market Value| is greater than or equal to this amount.",
                                id="stock-promotion-threshold-note",
                                className="static-data-page-note",
                            ),
                        ],
                        className="control-field",
                    ),
                ],
                className="controls top-controls",
            ),
            build_saved_filter_view_bar(
                STOCK_SAVED_VIEW_CONTROLS,
                filter_note=STOCK_FILTER_NOTE,
                filter_bar=html.Div(
                    [
                        html.Div(
                            [
                                *filter_controls,
                                dcc.Checklist(
                                    id="stock-filter-exclude-selected",
                                    options=[
                                        {
                                            "label": (
                                                "Exclude rows matching any selected value"
                                            ),
                                            "value": "exclude",
                                        }
                                    ],
                                    value=[],
                                    className=("stock-filter-mode filter-mode-control"),
                                ),
                            ],
                            className="controls filter-controls",
                        ),
                    ],
                    className="dimension-filter-bar top-controls",
                ),
            ),
            dcc.Loading(
                html.Div(
                    build_stock_page_placeholder(
                        "Loading both GetStock dates and the Portfolio mapping…"
                    ),
                    id="stock-page-content",
                ),
                delay_show=120,
            ),
            build_stock_history_section(available=history_available),
        ],
        id="stock-page",
        className="static-data-page",
    )


def load_stock_page_data(
    *,
    stock_source: StockSource | StockConnectorAdapter,
    portfolio_config_source: (
        pd.DataFrame | str | Path | Callable[[pd.Timestamp], pd.DataFrame | str | Path]
    ),
    current_date: object,
    prior_date: object,
    portfolio_date: object | None = None,
) -> StockPageData:
    """Resolve both dated Stock legs and one current Portfolio authority."""

    current, prior = normalize_stock_date_pair(current_date, prior_date)
    selected_portfolio_date = normalize_stock_date(
        current if portfolio_date is None else portfolio_date
    )
    adapter = (
        stock_source
        if isinstance(stock_source, StockConnectorAdapter)
        else build_stock_adapter(stock=stock_source)
    )
    current_stock = adapter.get_stock(current)
    prior_stock = adapter.get_stock(prior)
    portfolio_config = (
        portfolio_config_source(selected_portfolio_date)
        if callable(portfolio_config_source)
        else portfolio_config_source
    )
    mapped = map_stock_comparison_portfolios(
        current_stock,
        prior_stock,
        portfolio_config,
    )
    return StockPageData(
        mapped_stock=mapped,
        current_date=current,
        prior_date=prior,
        portfolio_date=selected_portfolio_date,
    )


def build_stock_page(
    current_stock: pd.DataFrame,
    prior_stock: pd.DataFrame,
    portfolio_config: pd.DataFrame | str | Path,
    *,
    current_date: object,
    prior_date: object,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
) -> html.Main:
    """Build the pure mapped comparison page from in-memory inputs."""

    current, prior = normalize_stock_date_pair(current_date, prior_date)
    data = StockPageData(
        mapped_stock=map_stock_comparison_portfolios(
            current_stock,
            prior_stock,
            portfolio_config,
        ),
        current_date=current,
        prior_date=prior,
        portfolio_date=current,
    )
    return build_stock_page_from_data(
        data,
        selected_filters=selected_filters,
        exclude_selected=exclude_selected,
        promotion_threshold=promotion_threshold,
    )


def build_stock_page_from_sources(
    *,
    stock_source: StockSource | StockConnectorAdapter,
    portfolio_config_source: (
        pd.DataFrame | str | Path | Callable[[pd.Timestamp], pd.DataFrame | str | Path]
    ),
    current_date: object,
    prior_date: object,
    portfolio_date: object | None = None,
    selected_filters: Mapping[str, Sequence[str] | None] | None = None,
    exclude_selected: bool = False,
    promotion_threshold: object = STOCK_PROMOTION_THRESHOLD_DEFAULT,
) -> html.Main:
    """Load both snapshots, then delegate to the pure Stock page builder."""

    page_data = load_stock_page_data(
        stock_source=stock_source,
        portfolio_config_source=portfolio_config_source,
        current_date=current_date,
        prior_date=prior_date,
        portfolio_date=portfolio_date,
    )
    return build_stock_page_from_data(
        page_data,
        selected_filters=selected_filters,
        exclude_selected=exclude_selected,
        promotion_threshold=promotion_threshold,
    )


__all__ = [
    "STOCK_FILTER_FIELDS",
    "STOCK_FILTER_IDS",
    "STOCK_SAVED_VIEW_CONTROLS",
    "STOCK_HIERARCHY_TOGGLE_TYPE",
    "StockPageData",
    "build_stock_hierarchy",
    "build_stock_hierarchy_panel",
    "build_stock_hierarchy_panel_with_state",
    "build_stock_hierarchy_with_state",
    "build_stock_page",
    "build_stock_page_from_data",
    "build_stock_page_from_sources",
    "build_stock_page_placeholder",
    "build_stock_page_shell",
    "build_stock_history_empty_figure",
    "build_stock_history_figure",
    "build_stock_history_section",
    "build_stock_history_table",
    "build_stock_source_rows_section",
    "build_stock_table",
    "build_stock_table_panel",
    "default_stock_dates",
    "load_stock_page_data",
    "normalize_stock_date_pair",
    "normalize_stock_history_frame",
    "normalize_stock_hierarchy_open_tokens",
    "stock_exclude_selected",
    "stock_filter_map",
    "stock_filter_options",
    "stock_history_date_range",
    "stock_history_identity_from_token",
    "stock_history_identity_options",
    "stock_history_identity_token",
    "stock_summary_text",
    "stock_hierarchy_path_from_token",
    "stock_hierarchy_path_token",
    "toggle_stock_hierarchy_open_tokens",
]
