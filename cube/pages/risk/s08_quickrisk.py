"""V5 Quick Risk controls and position-grain result presentation."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from cube.domain.s01_schema import PORTFOLIO_FIELDS
from cube.domain.s10_search import HIERARCHY_DEPTH
from cube.ui.s02_aggregation import format_number, number_sign_class
from cube.ui.s01_constants import ROW_TOGGLE_CLOSED_GLYPH, ROW_TOGGLE_OPEN_GLYPH

QUICK_RISK_PIVOT_LIMIT = 250
QUICK_SEARCH_DEFAULT_INDEX = ("Underlying", "Tenor Swap", "Tenor Option")
QUICK_SEARCH_HIERARCHY_DEPTH = HIERARCHY_DEPTH
_QUICK_SEARCH_IDENTITY_OPTIONS = (
    ("Source type", "Source Type"),
    ("Risk type", "Risk Type"),
    ("Risk Greek", "Risk Greek"),
    ("Underlying", "Underlying"),
    ("Tenor Swap", "Tenor Swap"),
    ("Tenor Option", "Tenor Option"),
    ("Portfolio", "Portfolio"),
)
QUICK_SEARCH_INDEX_OPTIONS = (
    *_QUICK_SEARCH_IDENTITY_OPTIONS,
    *((field.label, field.external_name) for field in PORTFOLIO_FIELDS),
)


def build_quick_search(*, embedded: bool = False) -> html.Details | html.Div:
    """Build the Quick Risk inspector as a disclosure or workspace-tab body."""

    dimension_options = [
        {"label": label, "value": value} for label, value in QUICK_SEARCH_INDEX_OPTIONS
    ]

    disclosure = html.Details(
        [
            html.Summary(
                [
                    html.Span(
                        "Quick Risk Search",
                        className="quick-search-pivot-title",
                    ),
                    html.Span(
                        "Risk · dRisk · PL · Open · Current · Move",
                        className="quick-search-pivot-values",
                    ),
                ],
                id="quick-search-summary",
                n_clicks=0,
                className="quick-search-pivot-summary",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2("Risk, PL and Market"),
                                    html.P(
                                        "Choose one exact Risk Type, Risk Greek and Underlying identity. "
                                        "The bounded dropdown never refreshes connector data."
                                    ),
                                ],
                                className="quick-search-heading-copy",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Search Risk",
                                        htmlFor="quick-search-combine-udl",
                                    ),
                                    dcc.Dropdown(
                                        id="quick-search-combine-udl",
                                        options=[],
                                        value=None,
                                        multi=False,
                                        clearable=False,
                                        searchable=True,
                                        placeholder="Type e.g. IR Delta EUR",
                                        className="quick-search-combine-dropdown",
                                    ),
                                    html.Span(
                                        "Search one full Risk Type | Risk Greek | Underlying identity.",
                                        className="quick-search-selector-help",
                                    ),
                                ],
                                className="quick-search-selector-control",
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Open in Data",
                                        id="quick-search-open-data",
                                        n_clicks=0,
                                        disabled=True,
                                        type="button",
                                        className="data-open-button",
                                    ),
                                    html.Span(
                                        "",
                                        id="quick-search-data-status",
                                        className="quick-search-selector-help",
                                        role="status",
                                    ),
                                ],
                                className="quick-search-selector-control data-open-control",
                            ),
                        ],
                        className="quick-search-heading",
                    ),
                    html.P(
                        "One current-snapshot hierarchy combines Risk, PL and quote-aware Market values.",
                        className="quick-search-pivot-description",
                    ),
                    html.Div(
                        [
                            html.Label(
                                "View hierarchy",
                                htmlFor="quick-search-dimensions",
                            ),
                            dcc.Dropdown(
                                id="quick-search-dimensions",
                                options=dimension_options,
                                value=list(QUICK_SEARCH_DEFAULT_INDEX),
                                multi=True,
                                clearable=False,
                                searchable=True,
                                closeOnSelect=False,
                                className="quick-search-dimensions",
                            ),
                            html.Span(
                                "Underlying and the product's tenor axes fill automatically. "
                                "Add reporting fields only when you need another split.",
                                className="quick-search-dimension-help",
                            ),
                        ],
                        className="quick-search-dimension-control",
                    ),
                    dcc.Loading(
                        html.Div(
                            "Open this section to build its current-snapshot hierarchy.",
                            id="quick-search-results",
                            className="quick-search-results quick-search-hint",
                        ),
                        type="dot",
                        delay_show=160,
                        className="quick-search-loading",
                    ),
                ],
                className="quick-search-pivot-body",
            ),
        ],
        id="quick-search-details",
        open=False,
        className="quick-search-shell quick-search-pivot-details",
        **{"aria-label": "Quick Risk Search hierarchy"},
    )
    if not embedded:
        return disclosure
    return html.Div(
        disclosure.children[1:],
        id=disclosure.id,
        className="quick-search-shell quick-search-tab-body",
        **{"aria-label": "Quick Risk Search hierarchy"},
    )


def _quick_search_text(value: object, *, fallback: str = "—") -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    return text or fallback


def _quick_search_path_token(value: object) -> str | None:
    """Preserve missing and literal display-fallback labels as distinct paths."""
    if value is None or pd.isna(value):
        return None
    return str(value).strip()


def _quick_search_number(value: object, *, column: str) -> tuple[str, str]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return _quick_search_text(value), ""
    if not np.isfinite(numeric):
        return "—", ""
    return format_number(numeric, column=column.casefold()), number_sign_class(numeric)


def build_quick_risk_figure(
    leaves: pd.DataFrame,
    index_columns: list[str] | tuple[str, ...],
) -> go.Figure:
    """Plot the current exact Risk identity using its ProductSpec-shaped axes."""

    axes = [
        column
        for column in ("Tenor Swap", "Tenor Option")
        if column in index_columns and column in leaves
    ]
    figure = go.Figure()
    if not axes:
        values = [
            pd.to_numeric(leaves.get(metric), errors="coerce").sum(min_count=1)
            for metric in ("Risk", "dRisk")
        ]
        figure.add_trace(
            go.Bar(
                x=["Risk", "dRisk"],
                y=values,
                marker_color=["#79BE89", "#78A9D1"],
                hovertemplate="<b>%{x}</b><br>%{y:,.6g}<extra></extra>",
            )
        )
    elif len(axes) == 1:
        axis = axes[0]
        curve = leaves.groupby(axis, as_index=False, sort=False)[["Risk", "dRisk"]].sum(
            min_count=1
        )
        for metric, color in (("Risk", "#79BE89"), ("dRisk", "#78A9D1")):
            figure.add_trace(
                go.Scatter(
                    x=curve[axis],
                    y=curve[metric],
                    name=metric,
                    mode="lines+markers",
                    line={"color": color, "width": 3},
                    connectgaps=False,
                )
            )
        figure.update_xaxes(title=axis, type="category")
    else:
        first, second = axes
        surface = leaves.pivot_table(
            index=second,
            columns=first,
            values="Risk",
            aggfunc="sum",
            sort=False,
            dropna=False,
        )
        figure.add_trace(
            go.Surface(
                x=list(surface.columns.astype(str)),
                y=list(surface.index.astype(str)),
                z=surface.to_numpy(dtype=float),
                colorbar={"title": "Risk"},
                connectgaps=False,
            )
        )
        figure.update_layout(
            scene={
                "xaxis": {"title": first, "type": "category"},
                "yaxis": {"title": second, "type": "category"},
                "zaxis": {"title": "Risk"},
            }
        )
    figure.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=340,
        margin={"l": 48, "r": 24, "t": 42, "b": 48},
        title={"text": "Current risk shape", "x": 0.01},
        legend={"orientation": "h", "y": 1.08},
        uirevision="quick-risk-current",
    )
    return figure


def build_quick_search_pivot(
    frame: pd.DataFrame,
    *,
    combine_udl: str,
    index_columns: list[str] | tuple[str, ...],
    total: int | None = None,
    revision: int | None = None,
) -> html.Div:
    """Render one bounded, selectable hierarchy returned by the backend catalog."""
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("search result frame must be a pandas DataFrame")
    selected_indexes = [str(value) for value in index_columns]
    if not selected_indexes:
        raise ValueError("at least one pivot index column is required")
    if len(selected_indexes) != len(set(selected_indexes)):
        raise ValueError("pivot index columns must be unique")

    metric_columns = (
        ("Risk", "Risk"),
        ("dRisk", "dRisk"),
        ("PL", "PL"),
        ("Open", "Open"),
        ("Current", "Current"),
        ("Move", "Move"),
    )
    required = [
        QUICK_SEARCH_HIERARCHY_DEPTH,
        *selected_indexes,
        *(column for column, _ in metric_columns),
    ]
    missing = [column for column in required if column not in frame.columns]
    if missing and not frame.empty:
        raise ValueError(f"pivot result is missing columns: {', '.join(missing)}")

    depths = pd.to_numeric(
        frame.get(
            QUICK_SEARCH_HIERARCHY_DEPTH,
            pd.Series(dtype="float64"),
        ),
        errors="coerce",
    )
    if not frame.empty:
        valid_depths = (
            depths.notna()
            & depths.ge(1)
            & depths.le(len(selected_indexes))
            & depths.mod(1).eq(0)
        )
        if not valid_depths.all():
            raise ValueError("pivot hierarchy contains an invalid depth")

    shown_leaves = int(depths.eq(len(selected_indexes)).sum())
    if (
        shown_leaves > QUICK_RISK_PIVOT_LIMIT
        or len(frame) > len(selected_indexes) * QUICK_RISK_PIVOT_LIMIT
    ):
        raise ValueError("pivot hierarchy exceeds the bounded UI contract")
    result_total = max(shown_leaves, int(total)) if total is not None else shown_leaves
    suffix = f" · snapshot {int(revision)}" if revision is not None else ""
    if frame.empty:
        return html.Div(
            [
                html.Div(
                    f"No current groups match '{str(combine_udl).strip()}'{suffix}.",
                    className="quick-search-empty",
                    role="status",
                    **{"aria-live": "polite"},
                )
            ],
            className="quick-search-result-set",
        )

    rows: list[html.Tr] = []
    emitted_paths: set[str] = set()
    for record in frame.to_dict("records"):
        depth = int(record[QUICK_SEARCH_HIERARCHY_DEPTH])
        index_dimension = selected_indexes[depth - 1]
        path_tokens = [
            _quick_search_path_token(record.get(index_column))
            for index_column in selected_indexes[:depth]
        ]
        path = json.dumps(path_tokens, ensure_ascii=False, separators=(",", ":"))
        parent_path = json.dumps(
            path_tokens[:-1],
            ensure_ascii=False,
            separators=(",", ":"),
        )

        if path in emitted_paths:
            raise ValueError("pivot hierarchy contains a duplicate path")
        if depth > 1 and parent_path not in emitted_paths:
            raise ValueError("pivot hierarchy child precedes its parent")
        emitted_paths.add(path)

        display_value = _quick_search_text(record.get(index_dimension))
        has_children = depth < len(selected_indexes)
        is_open = has_children and depth == 1
        if has_children:
            state = "Collapse" if is_open else "Expand"
            index_toggle: html.Button | html.Span = html.Button(
                ROW_TOGGLE_OPEN_GLYPH if is_open else ROW_TOGGLE_CLOSED_GLYPH,
                type="button",
                className="row-toggle quick-search-hierarchy-toggle",
                title=f"{state} {index_dimension}: {display_value}",
                **{
                    "aria-label": f"{state} {index_dimension}: {display_value}",
                    "aria-expanded": str(is_open).lower(),
                },
            )
        else:
            index_toggle = html.Button(
                "",
                type="button",
                className="row-toggle quick-search-hierarchy-toggle-spacer",
                disabled=True,
                tabIndex=-1,
                **{"aria-hidden": "true"},
            )

        cells: list[html.Th | html.Td] = [
            html.Th(
                [
                    index_toggle,
                    html.Span(
                        display_value,
                        className="row-label-text quick-search-hierarchy-label",
                    ),
                ],
                scope="row",
                className=(
                    "index-cell quick-search-pivot-index "
                    "quick-search-first-index quick-search-last-index "
                    "quick-search-hierarchy-index"
                ),
                style={"paddingLeft": f"{12 + (depth - 1) * 20}px"},
                title=f"{index_dimension}: {display_value}",
                **{
                    "data-metric": "index",
                    "data-copy-value": display_value,
                    "data-index-dimension": index_dimension,
                },
            )
        ]
        for metric_column, label in metric_columns:
            raw_value = record.get(metric_column)
            text_value, sign_class = _quick_search_number(
                raw_value, column=metric_column
            )
            try:
                numeric_value = float(raw_value)
                copy_value = str(numeric_value) if np.isfinite(numeric_value) else ""
            except (TypeError, ValueError):
                copy_value = ""
            cells.append(
                html.Td(
                    text_value,
                    className=(
                        "metric-cell quick-search-number "
                        f"{'quick-search-pl-column ' if metric_column == 'PL' else ''}"
                        f"{sign_class}"
                    ).strip(),
                    **{
                        "data-metric": metric_column,
                        "data-copy-value": copy_value,
                    },
                )
            )

        row_classes = [
            "quick-search-hierarchy-row",
            f"quick-search-hierarchy-depth-{depth}",
        ]
        if depth == 1:
            row_classes.append("quick-search-hierarchy-root")
        if not has_children:
            row_classes.append("quick-search-hierarchy-leaf")
        row_props = {
            "aria-level": str(depth),
            "data-quick-search-depth": str(depth),
            "data-quick-search-path": path,
            "data-quick-search-parent-path": parent_path,
            "data-quick-search-open": str(is_open).lower(),
            "data-quick-search-label": display_value,
            "data-quick-search-dimension": index_dimension,
        }
        if has_children:
            row_props["aria-expanded"] = str(is_open).lower()
        rows.append(
            html.Tr(
                cells,
                className=" ".join(row_classes),
                hidden=depth > 2,
                **row_props,
            )
        )

    # Compute totals and the current chart from leaf rows only.
    leaf_rows = [
        r
        for r in frame.to_dict("records")
        if r[QUICK_SEARCH_HIERARCHY_DEPTH] == len(selected_indexes)
    ]
    leaf_frame = pd.DataFrame(leaf_rows)
    metric_summaries = {}
    for metric_column, label in metric_columns:
        values = []
        for record in leaf_rows:
            raw = record.get(metric_column)
            try:
                numeric = float(raw)
                if np.isfinite(numeric):
                    values.append(numeric)
            except (TypeError, ValueError):
                pass
        metric_summaries[metric_column] = sum(values) if values else 0.0

    if leaf_rows:
        total_cells: list[html.Th | html.Td] = [
            html.Th(
                html.Span(
                    "Total",
                    className="total-label quick-search-total-label",
                ),
                scope="col",
                className="index-cell quick-search-pivot-index quick-search-total-index",
                style={"fontWeight": "bold"},
            )
        ]
        for metric_column, label in metric_columns:
            total_value, sign_class = _quick_search_number(
                metric_summaries[metric_column], column=metric_column
            )
            total_cells.append(
                html.Td(
                    total_value,
                    className=(
                        "metric-cell quick-search-number quick-search-total-cell "
                        f"{'quick-search-pl-column ' if metric_column == 'PL' else ''}"
                        f"{sign_class}"
                    ).strip(),
                    style={"fontWeight": "bold"},
                    **{
                        "data-metric": metric_column,
                        "data-copy-value": str(metric_summaries[metric_column]),
                    },
                )
            )
        rows.append(
            html.Tr(
                total_cells,
                className="quick-search-total-row",
                **{
                    "data-quick-search-total": "true",
                },
            )
        )

    status = (
        f"Showing {shown_leaves:,} of {result_total:,} leaf groups "
        f"across {len(rows):,} hierarchy rows{suffix}"
    )
    index_header = html.Th(
        "Index",
        scope="col",
        className=(
            "index-header quick-search-pivot-index-header "
            "quick-search-first-index quick-search-last-index"
        ),
        title="Hierarchy: " + " · ".join(selected_indexes),
        **{"data-metric": "index"},
    )
    metric_headers = [
        html.Th(
            label,
            scope="col",
            className=(
                "metric-header quick-search-pivot-metric-header "
                f"{'quick-search-pl-column' if column == 'PL' else ''}"
            ),
            **{"data-metric": column},
        )
        for column, label in metric_columns
    ]
    return html.Div(
        [
            html.Div(
                status,
                className="quick-search-result-count",
                role="status",
                **{"aria-live": "polite", "aria-atomic": "true"},
            ),
            dcc.Graph(
                figure=build_quick_risk_figure(leaf_frame, selected_indexes),
                config={"displaylogo": False, "responsive": True},
                className="quick-risk-current-chart",
            ),
            html.Div(
                [
                    html.Div(
                        "",
                        className="selection-summary",
                        **{"aria-live": "polite"},
                    ),
                    html.Table(
                        [
                            html.Caption(
                                "Current Risk, PL and Market hierarchy ordered by "
                                f"{' · '.join(selected_indexes)}",
                                className="sr-only",
                            ),
                            html.Thead(html.Tr([index_header, *metric_headers])),
                            html.Tbody(rows),
                        ],
                        className="cell-selection-table quick-search-pivot-table",
                        role="treegrid",
                        **{
                            "aria-label": "Current combined Quick Search hierarchy",
                            "data-quick-search-level-count": str(len(selected_indexes)),
                        },
                    ),
                ],
                className="risk-table-wrap quick-search-pivot-table-wrap",
                tabIndex=0,
                **{"aria-label": "Scrollable current combined hierarchy"},
            ),
        ],
        className="quick-search-result-set",
        **({"data-snapshot-revision": str(revision)} if revision is not None else {}),
    )


__all__ = [
    "QUICK_RISK_PIVOT_LIMIT",
    "QUICK_SEARCH_DEFAULT_INDEX",
    "QUICK_SEARCH_HIERARCHY_DEPTH",
    "QUICK_SEARCH_INDEX_OPTIONS",
    "build_quick_search",
    "build_quick_risk_figure",
    "build_quick_search_pivot",
]
