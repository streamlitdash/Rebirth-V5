# Quick Risk charts and clientside Data search

Updated 11 September 2026 for `streamlitdash/Rebirth-V5`, branch `v7`. This document contains implementation instructions; publishing it does not deploy application code.

## Read first: this corrects the earlier Data instructions

**Part A keeps the dedicated Quick Risk chart. Part B now extends your existing clientside Data workspace.** It does not bring back the old Risk Type / Greek / Underlying callbacks.

The old Part B was written for the original three-selector Python implementation in GitHub. Your earlier guides replaced that layout with Risk / Market / Both and Choose a series, then replaced the Python selection editor with `cube.workspaceEditor` in `assets/data_workspace_editor.js`. Those are different versions. Complete copies of the old callbacks did not make them suitable for your current interface.

Use this order:

1. Keep or implement Part A, then check its charts.
2. Implement this revised Part B on the existing browser-editor workspace. Complete its JavaScript and registration changes together, then restart and hard-refresh.
3. Apply `JTD.md` independently if needed.
4. Apply `Hero.md`; include `render_quick_risk_tenor` when Quick Risk participates. Keep any already-implemented completion acknowledgement outputs/returns when adapting the Part A callback.
5. Use `Connectors.md` for live feeds. These display changes do not require a connector migration.

Part A was checked against application source at `2220a3f4839318863a9131e3fef8118d0f82fb7d`. Part B extends the complete clientside editor previously published in `DATA_INTERACTION_FIX.md` at `335bdce6453b7544d4eac436b7094f35c14864c6`, matching the interface you described. GitHub's untouched application source still contains the older Data page: **this document is not a migration from that old page to the unified workspace.** Further local changes to your deployed files have not been inspected. The component and argument contract is listed below so you can compare it directly.

Full affected definitions, imports, callback registration and dropdown copies are supplied. Replace each named definition/registration once; keep unrelated local code. Do not overwrite the application folder with older GitHub files, add duplicate Output owners, or recreate old selectors just because their Python names are absent.

Before editing, save the affected files using your normal source-control/backup process. Keep JavaScript backups outside `assets/`, where Dash would otherwise load them too. Run `git status --short` if using a checkout and preserve your existing changes.

## Part A — a dedicated, spacious Quick Risk chart

### A1. What changes and why

The earlier guide reused `build_detail_panel_with_state`. That brings a heading, context information, detail tables/matrix and a two-column layout. Worse, the old example placed the chart in `quick-search-dimension-control`, a two-column control grid capped at 960px; the chart could land in its narrow first column. Remove that approach.

The replacement has its own chart builder and CSS. It does not call or import the tenor selector's component or figure builders. It reuses only the existing prepared data, financial aggregation and tenor-order/absence rules.

| View | Dedicated Quick Risk presentation |
|---|---|
| Tenor Swap | Total Risk bars; Risk XVA and Risk Hedges lines, all on one y-axis; option tenors are summed |
| Tenor Option | The same three measures; swap tenors are summed |
| Surface | 2D Total Risk heatmap, red through white to green around zero; missing cells remain blank |
| Auto | Full-width charts for each distinct tenor shape, stacked vertically; no rows counted twice |
| No tenor | Three compact Total/XVA/Hedges values, with no invented tenor axis |

Curves have a 500px chart area, surfaces 560px, and the full available width. The only control added is Chart view. There is no duplicate detail table, matrix, context subtitle, snapshot counter, P&L or market series inside this chart. The existing Quick Risk hierarchy and Open in Data remain separately available below/above it.

The chart reads the complete selected reported identity from `_RiskDataCache.current()`, applies shared filters, and aggregates `risk`, `risk expo` and `risk hedges`. The existing validator owns `risk = risk expo + risk hedges`; `risk expo` is displayed as XVA. Do not rename dRisk to XVA or derive components in the chart. Product/reporting classification still determines the underlying components.

The hierarchy's 250-leaf display cap does not limit the chart. Selecting Swap/Option includes all rows with that axis and adds a short note if other shapes are excluded. Auto includes those other shapes. The surface allocation is checked before creating a rectangular grid: more than 250,000 cells prompts the user to use a curve. This limits only that dense picture, not source rows, history or either aggregate curve.

### A2. Add the complete dedicated chart module

Create `cube/pages/risk/s16_quickriskcharts.py` with this entire content. This module and all its functions are **new**. If you already created this module from this revised guide, replace it with this copy; otherwise keep unrelated existing files.

```python
"""Quick Risk charts: full-width figures, with no tenor-detail panel or tables."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from cube.ui.s02_aggregation import detail_frame, tenor_axis_order
from .s01_common import _meaningful_tenor_mask

RISK_SERIES = ("risk", "risk expo", "risk hedges")
RISK_LABELS = ("Total Risk", "Risk XVA", "Risk Hedges")
RISK_COLORS = ("#4C8A4A", "#4C87B9", "#C26464")
MAX_SURFACE_CELLS = 250_000


def quick_risk_view_state(detail, requested_view):
    """Partition every row once; keep the selector valid after identity changes."""
    index = detail.index
    swap = _meaningful_tenor_mask(
        detail.get("tenor swap", pd.Series(pd.NA, index=index, dtype="string"))
    )
    option = _meaningful_tenor_mask(
        detail.get("tenor option", pd.Series(pd.NA, index=index, dtype="string"))
    )
    masks = {
        "surface": swap & option,
        "swap": swap & ~option,
        "option": option & ~swap,
        "scalar": ~swap & ~option,
    }
    available = {
        "auto": True, "swap": bool(swap.any()),
        "option": bool(option.any()), "surface": bool((swap & option).any()),
    }
    options = [
        {"label": label, "value": value, "disabled": not available[value]}
        for value, label in (
            ("auto", "Auto"), ("swap", "Tenor Swap"),
            ("option", "Tenor Option"), ("surface", "Surface"),
        )
    ]
    requested = str(requested_view or "auto")
    return masks, options, requested if available.get(requested, False) else "auto"


def _chart_style(figure, *, surface=False):
    figure.update_layout(
        template="plotly_white", autosize=True,
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font={"family": "Arial, sans-serif", "size": 12, "color": "#48515C"},
        margin={"l": 75, "r": 80 if surface else 25, "t": 45, "b": 85},
        hoverlabel={"font": {"size": 12}},
        legend={"orientation": "h", "y": 1.12, "x": 0},
        hovermode="closest" if surface else "x unified",
        bargap=0.3,
    )
    figure.update_xaxes(automargin=True, showgrid=False, tickfont={"size": 11})
    figure.update_yaxes(automargin=True, tickfont={"size": 11})
    return dcc.Graph(
        figure=figure, responsive=True, className="quick-risk-plot",
        style={"height": "560px" if surface else "500px", "width": "100%"},
        config={"displayModeBar": False, "responsive": True},
    )


def _order_note(ambiguous):
    return html.P(
        "Some underlying tenor ranks differ; the shared connector-order rule is used.",
        className="quick-risk-chart-note",
    ) if ambiguous else None


def _curve_chart(detail, axis):
    labels, ambiguous = tenor_axis_order(detail, axis, f"{axis} order")
    curve = detail.groupby(axis, sort=False)[list(RISK_SERIES)].sum(min_count=1)
    curve.index = curve.index.astype(str)
    curve = curve.reindex(labels)
    figure = go.Figure()
    figure.add_bar(
        name=RISK_LABELS[0], x=labels, y=curve["risk"],
        marker_color=RISK_COLORS[0], opacity=0.65,
        hovertemplate="Total Risk: %{y:,.2f}<extra></extra>",
    )
    for column, name, color in zip(RISK_SERIES[1:], RISK_LABELS[1:], RISK_COLORS[1:]):
        figure.add_scatter(
            name=name, x=labels, y=curve[column], mode="lines+markers",
            line={"color": color, "width": 2.5}, marker={"size": 5},
            connectgaps=False,
            hovertemplate=name + ": %{y:,.2f}<extra></extra>",
        )
    # All three measures share one scale; never add yaxis2 here.
    figure.update_xaxes(
        title_text=axis.title(), type="category", categoryorder="array",
        categoryarray=labels, tickangle=-30,
    )
    figure.update_yaxes(
        title_text="Risk", tickformat=",.0f", rangemode="tozero",
        zeroline=True, zerolinecolor="#89939E", gridcolor="#E6EBF0",
    )
    return html.Div([
        html.H3(axis.title(), className="quick-risk-chart-title"),
        _chart_style(figure), _order_note(ambiguous),
    ])


def _surface_chart(detail):
    swaps, swap_ambiguous = tenor_axis_order(detail, "tenor swap", "tenor swap order")
    options, option_ambiguous = tenor_axis_order(detail, "tenor option", "tenor option order")
    # Check before unstack allocates the rectangular plotting grid.
    if len(swaps) * len(options) > MAX_SURFACE_CELLS:
        return html.P(
            "This surface is too dense to draw clearly. Choose Tenor Swap or Tenor Option; "
            "both curves still include all matching positions.",
            className="quick-risk-chart-note",
        )
    values = detail.groupby(["tenor option", "tenor swap"])["risk"].sum(min_count=1)
    matrix = values.unstack("tenor swap").reindex(index=options, columns=swaps)
    numeric = matrix.to_numpy(dtype=float, na_value=np.nan)
    finite = numeric[np.isfinite(numeric)]
    bound = max(float(np.abs(finite).max()), 1e-12) if finite.size else 1.0
    figure = go.Figure(go.Heatmap(
        x=swaps, y=options, z=numeric, zmin=-bound, zmax=bound, zmid=0,
        colorscale=[[0, "#C26464"], [0.5, "#FCFCFA"], [1, "#4C8A4A"]],
        xgap=1, ygap=1, hoverongaps=False,
        colorbar={"title": {"text": "Total Risk"}, "thickness": 12, "tickformat": ",.0f"},
        hovertemplate=("Swap: %{x}<br>Option: %{y}<br>Total Risk: %{z:,.2f}<extra></extra>"),
    ))
    figure.update_xaxes(
        title_text="Tenor Swap", type="category", categoryorder="array",
        categoryarray=swaps, tickangle=-30,
    )
    figure.update_yaxes(
        title_text="Tenor Option", type="category", categoryorder="array",
        categoryarray=options, autorange="reversed", showgrid=False,
    )
    return html.Div([
        html.H3("Total Risk surface", className="quick-risk-chart-title"),
        _chart_style(figure, surface=True), _order_note(swap_ambiguous or option_ambiguous),
    ])


def _scalar_summary(detail):
    totals = detail[list(RISK_SERIES)].sum(min_count=1)
    return html.Div([
        html.H3("Risk without tenor", className="quick-risk-chart-title"),
        html.Div([
            html.Div([
                html.Span(name),
                html.Strong("—" if pd.isna(totals[column]) else f"{totals[column]:,.2f}"),
            ]) for column, name in zip(RISK_SERIES, RISK_LABELS)
        ], className="quick-risk-scalar-values"),
    ])


def build_quick_risk_chart(scope: pd.DataFrame, requested_view="auto"):
    """Receive the complete filtered, prepared identity; return chart, choices, view."""
    # Reuse validated aggregation, not the tenor selector's component/figure builders.
    detail = detail_frame(scope, {}, "risk") if not scope.empty else pd.DataFrame()
    for axis in ("tenor swap", "tenor option"):
        if axis in detail:
            detail[axis] = detail[axis].astype("string").str.strip()
    masks, options, resolved = quick_risk_view_state(detail, requested_view)
    if detail.empty:
        return html.P("No positions match this selection."), options, resolved
    charts = []
    if resolved == "auto":
        for shape, mask in masks.items():
            if not mask.any():
                continue
            part = detail.loc[mask]
            charts.append(
                _surface_chart(part) if shape == "surface"
                else _scalar_summary(part) if shape == "scalar"
                else _curve_chart(part, f"tenor {shape}")
            )
    else:
        included = masks["surface"] if resolved == "surface" else masks[resolved] | masks["surface"]
        part = detail.loc[included]
        charts.append(_surface_chart(part) if resolved == "surface" else _curve_chart(part, f"tenor {resolved}"))
        excluded_rows = int(detail.loc[~included, "rows"].sum())
        if excluded_rows:
            charts.append(html.P(
                f"{excluded_rows:,} positions fall outside this tenor view. Choose Auto to include their results.",
                className="quick-risk-chart-note",
            ))
    return html.Div(charts, className="quick-risk-chart-stack"), options, resolved
```

`detail_frame`, `tenor_axis_order` and `_meaningful_tenor_mask` are existing shared helpers at the imported paths. Keep them as the single authority; do not copy the whole tenor-selector panel or create another snapshot cache. `detail_frame` receives an already scoped, prepared frame and an empty context deliberately; there is no second identity lookup or parsing of a display label.

### A3. Replace the Quick Risk layout function

Open `cube/pages/risk/s08_quickrisk.py`. Replace only the complete `build_quick_search` definition with this copy. Keep its signature and the other definitions/constants. This also replaces the old Part A picker/layout if you already applied it, so there is only one instance of each `quick-risk-tenor-*` ID. The chart's loader is a sibling below its controls, not a child of the hierarchy's dropdown grid.

```python
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
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Chart view", htmlFor="quick-risk-tenor-view"),
                                    dcc.Dropdown(
                                        id="quick-risk-tenor-view",
                                        options=[
                                            {"label": "Auto", "value": "auto"},
                                            {"label": "Tenor Swap", "value": "swap"},
                                            {"label": "Tenor Option", "value": "option"},
                                            {"label": "Surface", "value": "surface"},
                                        ],
                                        value="auto", clearable=False, searchable=False,
                                        className="quick-risk-chart-picker",
                                    ),
                                ],
                                className="quick-risk-chart-controls",
                            ),
                            dcc.Loading(
                                html.Div(id="quick-risk-tenor-result"),
                                type="dot", delay_show=160, className="quick-risk-chart-loading",
                            ),
                        ],
                        className="quick-risk-chart-panel",
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
```

### A4. Remove the obsolete chart from the hierarchy

Still in `s08_quickrisk.py`:

1. Remove the complete old `build_quick_risk_figure` definition if present.
2. Remove `"build_quick_risk_figure",` from `__all__` if present.
3. Remove `import plotly.graph_objects as go` if it has no other local use. Keep pandas, numpy and the other existing imports.
4. Replace the complete `build_quick_search_pivot` function with the copy below. Its hierarchy, totals and coverage notice are preserved; the old `leaf_frame` and `dcc.Graph` are removed. If you have already removed those two items in a locally customised table, keep that table rather than overwriting unrelated custom columns.

This is the complete function, so you do not need to infer where the old graph ends:

```python
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

    # Compute table totals from displayed leaf rows only.
    leaf_rows = [
        r
        for r in frame.to_dict("records")
        if r[QUICK_SEARCH_HIERARCHY_DEPTH] == len(selected_indexes)
    ]
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
```

Keep the existing `_quick_search_text`, `_quick_search_path_token`, `_quick_search_number` helpers and `QUICK_SEARCH_*` constants in this module. The original v7 table already depends on them; they are not new chart dependencies. If your table is a different implementation, apply only the graph removal to its owner instead of adding a second hierarchy.

### A5. Add or replace the chart callback once

Open `cube/pages/risk/s14_workspacecallbacks.py`. Add this import alongside the existing imports:

```python
from .s16_quickriskcharts import build_quick_risk_chart
```

Keep `apply_filters`, `reporting_filter_map`, `risk_exclude_selected`, `html`, `no_update`, `Input` and `Output`; they already exist in this file. If you applied the previous Quick Risk guide, remove its `build_detail_panel_with_state` import when unused here, and remove its `row_key` import when unused. Keep other local uses/imports.

Inside `register_workspace_callbacks`, inside the existing `if refresh_manager is not None:` block, place the following complete decorator and function after `render_current_pivot` and before the callback for `quick-market-combine-udl.options`. The block below is indented eight spaces on purpose. If `render_quick_risk_tenor` already exists, replace its decorator and body; do not add a second owner. Preserve any Hero completion acknowledgement as explained at the start.

```python
        @app.callback(
            Output("quick-risk-tenor-result", "children"),
            Output("quick-risk-tenor-view", "options"),
            Output("quick-risk-tenor-view", "value"),
            Input("quick-search-combine-udl", "value"),
            Input("quick-risk-tenor-view", "value"),
            Input("risk-workspace-tabs", "value"),
            Input("data-revision-store", "data"),
            Input("split-filter", "value"),
            Input("dimension-filter-values-store", "data"),
            Input("risk-filter-exclude-applied-store", "data"),
        )
        def render_quick_risk_tenor(
            combine_udl, tenor_view, active_workspace, revision,
            selected_splits, dimension_values, exclude_value,
        ):
            if active_workspace != "quick-risk":
                return None, no_update, no_update
            if not combine_udl:
                return "Choose a Search Risk identity.", no_update, no_update
            try:
                identity = refresh_manager.resolve_history_identity(
                    "risk", str(combine_udl), identity_mode="reported",
                )
                committed = cache.current(refresh_manager)
                if not (
                    int(revision or 0) == identity.source_revision == cache.revision
                ):
                    return "Snapshot changed; waiting for the current revision…", no_update, no_update
                # Scope before filtering/copying. Never mutate the shared cache.
                scope = committed.loc[
                    committed["source type"].isin(identity.source_types)
                    & committed["risk type"].eq(identity.risk_type)
                    & committed["risk greek"].eq(identity.risk_greek)
                    & committed["reported underlying"].eq(identity.underlying)
                ]
                scope = apply_filters(
                    scope, [], list(selected_splits or []),
                    reporting_filter_map(dimension_values),
                    exclude_selected=risk_exclude_selected(exclude_value),
                )
                panel, options, resolved = build_quick_risk_chart(scope, tenor_view)
                return panel, options, (resolved if resolved != tenor_view else no_update)
            except (AttributeError, KeyError, LookupError, TypeError, ValueError, RuntimeError) as error:
                app.logger.exception("Quick Risk chart failed")
                return html.Div(
                    f"Quick Risk chart unavailable: {error}", role="alert",
                ), no_update, no_update
```

The display identity is resolved by the existing manager; it is never split on a `|` character. The revision comparison prevents mixing rows and an identity from different snapshots. Errors remain visible; a missing/error result must not be acknowledged as successful by the Hero implementation. No connector is called by the chart callback.

### A6. Add the layout rules once

Append this block to `assets/s03_risk.css`. If this exact block is already present, replace it rather than appending another copy. Keep `.quick-search-dimension-control` for the hierarchy dropdown and keep all tenor-selector/detail styles. The new chart never uses `.detail-grid`, `.detail-panel-body` or `.quick-search-dimension-control`. The obsolete `.quick-risk-current-chart` rule can be removed when nothing uses that class.

```css
/* Quick Risk chart only: keep it outside the dropdown and detail grids. */
.quick-risk-chart-panel {
  display: block;
  width: 100%;
  min-width: 0;
  max-width: none;
  margin: 18px 0;
  border: 1px solid var(--outline);
  border-radius: 12px;
  background: var(--surface);
}
.quick-risk-chart-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--outline);
}
.quick-risk-chart-controls > label { margin: 0; font-weight: 700; }
.quick-risk-chart-picker { width: 210px; min-width: 0; }
.quick-risk-chart-loading,
#quick-risk-tenor-result,
.quick-risk-chart-stack,
.quick-risk-chart-stack > div { width: 100%; min-width: 0; }
.quick-risk-chart-stack { display: grid; grid-template-columns: minmax(0, 1fr); gap: 18px; padding: 14px; }
.quick-risk-chart-title { margin: 0 0 4px; font-size: 14px; color: var(--text); }
.quick-risk-chart-note { margin: 4px 8px 8px; font-size: 12px; color: var(--text-muted); }
.quick-risk-plot { width: 100%; min-width: 0; }
.quick-risk-scalar-values { display: flex; flex-wrap: wrap; gap: 24px; padding: 18px 0; }
.quick-risk-scalar-values > div { display: grid; gap: 6px; }
.quick-risk-scalar-values span { color: var(--text-muted); font-size: 12px; }
.quick-risk-scalar-values strong { font-size: 20px; font-variant-numeric: tabular-nums; }
@media (max-width: 640px) {
  .quick-risk-chart-stack { padding: 8px; }
  .quick-risk-chart-controls { padding: 10px; }
}
```

### A7. Verify the chart before changing Data

1. Restart. Check that one Chart view picker and one chart result exist. Search for duplicate `quick-risk-tenor-result` Outputs if Dash complains.
2. Compare a swap identity with the tenor selector using identical filters: Total, XVA and Hedges must match at every tenor. All three traces use one y-axis; legend clicks can hide a measure temporarily.
3. Check a two-axis identity: Surface displays only a heatmap, Swap and Option sum the opposite axis correctly. Connector ranks, not alphabetic tenor labels, own order. The option axis displays its first ordered tenor at the top.
4. Check mixed shapes and a scalar identity. Auto must account for every row once; an explicit axis explains omitted shapes. Nulls remain gaps/dashes and genuine zeros remain zero.
5. Check a selected identity above 250 hierarchy leaves: all its chart points remain. Test shared include/exclude filters and refresh during selection.
6. At wide and narrow window widths, the graph occupies its own full-width row and does not sit beside a detail table. Long tenor labels remain readable via hover. The existing hierarchy can scroll independently.
7. Check Open in Data, Quick Market and the clicked tenor selector still work. These changes introduce no changes to their presentation or source contracts.
8. If Hero is already implemented, a refresh must wait for this callback and its visible graph render when Quick Risk participates; do not finalize on the data-revision Store alone.

After code changes, update tests which still import the deliberately removed `build_quick_risk_figure` or expect its old 3D figure. The replacement tests should target `build_quick_risk_chart` and its registered callback.

## Part B — keep the browser editor and make its choices lighter

### B1. Confirm the correct version and keep its responsibilities

Find these existing items:

| Location | What must be there |
|---|---|
| `assets/data_workspace_editor.js` | The exported `window.dash_clientside.cube.workspaceEditor` selection function |
| `cube/pages/data/s03_callbacks.py`, inside `register_callbacks` | One `app.clientside_callback` registration for `ClientsideFunction(namespace="cube", function_name="workspaceEditor")` |
| `cube/pages/data/s02_view.py` | `data-display-mode`, `data-series-picker`, `data-companion-picker` and the existing Data workspace stores |
| Existing Python loader | `load_workspace` and its request parser / `query_workspace_bundle`, including the current-observation reader |

The editor runs in the browser. It edits selections, preserves imported Risk scope, chooses an exact opposite-kind companion when allowed, and emits a request on Load or a fresh Quick handoff. Python still independently validates that request and reads the requested financial data. The existing browser projection/player callbacks continue rendering the loaded bundle.

Do not add `choose_risk_type`, `choose_risk_greek`, `choose_underlying` or `choose_history_request`. Do not recreate `data-underlying`. Do not register a Python `edit_workspace` alongside the browser editor.

If you have extra deliberate Outputs or a different workspace request schema, compare them before replacing the registration and preserve the corresponding JavaScript return values. The complete copy here has the established thirteen Outputs, with the exact matching argument order in B4.

### B2. Undo only incompatible changes from the previous Part B, if applied

If you did not implement that section, proceed to B3.

1. Preserve your current files, then use your **pre-change working unified-workspace copy** to restore only sections changed by the previous Part B. Keep the chart changes from Part A.
2. Remove any obsolete Python selector/request registrations you added. Keep one owner of `data-history-request-store.data`: the existing browser editor. Identify the decorator belonging to each removed definition; do not delete neighbouring callbacks.
3. Restore your working unified catalogue producer and its helper, including the current-data plus archive merge. `data-history-catalog-store.data` must again include its complete `entries` array, alongside its generation/revision metadata. A generation-only dictionary is incompatible with this editor.
4. If you replaced a current-plus-history helper with the old archive-only `load_archive_catalog(repository, cache_state)`, restore your prior helper body and signature. Returning archive entries alone would still lose current-only choices. Do not take that helper from untouched GitHub v7 as a substitute for your unified implementation.
5. Restore the unified series/companion controls and any overwritten workspace loader or parser from that same working copy. Keep current observations, historical-only identities, exact source identity and Risk-filter handling.
6. The previous `cached_property` change to `HistoryCatalogEntry.key` is not required here. A working hash-identical property may remain; restore it from your backup only if deliberately undoing that unrelated change. This repair does not depend on it or on the old Python `underlying_options` function.

Do not erase unrelated customizations or roll back the whole repository. If a required unified helper was overwritten and you have no working copy, its actual source needs recovering/comparing before this patch can be completed; inventing a replacement from the older three-selector files would be unsafe for data correctness.

### B3. Replace the complete browser-editor asset

Open `assets/data_workspace_editor.js` in the actual app's top-level assets directory. Replace its complete existing editor implementation with the code below. Keep other asset files and exports; the namespace assignment preserves unrelated functions. If your local editor contains extra deliberate behavior, retain that behavior when merging this complete reference rather than silently dropping it.

The changes are small in scope:

- Build the key/identity/search index once for the current catalogue object and timestamp; reuse it on later selection/search edits. This is browser-local identity metadata, not a server-global selection or a financial-frame cache.
- Pass both dropdowns' `search_value` into the existing editor.
- Return at most 100 options per dropdown, including its retained normal or Quick selection. Searching never changes the selected value or loads history by itself.
- Keep the complete catalogue available for exact lookup and companion pairing. The cap is on rendered options, not on data, dates, portfolios or available identities.


```javascript
/* Data selection only. The existing Python loader validates and reads history.
 * workspaceEditor: 13 Inputs followed by 4 States; exactly 13 Outputs.
 * New search Inputs follow end_date and precede previous/consumed/loaded/catalog.
 */
(function () {
    "use strict";
    const MODES = ["risk", "market", "both"];
    const PERIODS = ["wtd", "mtd", "ytd", "1y", "5y", "all", "custom"];
    const QUICK = "__quick_handoff__";
    const copy = value => value == null ? null : JSON.parse(JSON.stringify(value));
    const opposite = kind => kind === "risk" ? "market" : "risk";
    const selectedKey = kind => "__data_selected_" + kind + "__";
    const identityKey = identity => JSON.stringify([
        identity.source_types, identity.risk_type, identity.risk_greek,
        identity.underlying, identity.identity_mode
    ]);
    const sameIdentity = (a, b) => Boolean(a && b && a.kind === b.kind &&
        identityKey(a.identity) === identityKey(b.identity));
    const integer = value => Number.isInteger(value) && value >= 0;
    const validDate = value => typeof value === "string" &&
        /^\d{4}-\d{2}-\d{2}$/.test(value) &&
        !Number.isNaN(Date.parse(value)) &&
        new Date(value).toISOString().slice(0, 10) === value;

    function checkedHandoff(value) {
        const h = copy(value), i = h && h.identity;
        if (!h || h.schema_version !== 1 || !["risk", "market"].includes(h.kind) ||
            !integer(h.source_revision) || !integer(h.reset_generation) ||
            !validDate(h.snapshot_date) || !i ||
            !Array.isArray(i.source_types) || !i.source_types.length ||
            !i.source_types.every(v => typeof v === "string" && v.trim()) ||
            ![i.risk_type, i.risk_greek, i.underlying].every(v => typeof v === "string" && v.trim()) ||
            !["reported", "underlying"].includes(i.identity_mode)) {
            throw Error("The selected series has an invalid identity; reopen it or choose another.");
        }
        if (h.kind === "market" && (h.filter_view != null ||
            i.identity_mode !== "underlying" || i.source_types.length !== 1)) {
            throw Error("Market requires one raw series without Risk filters.");
        }
        if (h.filter_view != null && (typeof h.filter_view.filters !== "object" ||
            h.filter_view.filters === null || typeof h.filter_view.exclude_selected !== "boolean" ||
            !Object.values(h.filter_view.filters).every(values => Array.isArray(values) &&
                values.every(v => typeof v === "string")))) {
            throw Error("The imported Risk scope is invalid; reopen Quick Risk.");
        }
        h.metric = h.kind === "risk" ? "risk" : "current";
        return h;
    }

    function label(h) {
        const i = h.identity;
        return [h.kind === "risk" ? "Risk" : "Market", i.risk_type, i.risk_greek,
            i.underlying, i.identity_mode === "reported" ? "Reported" : "Raw",
            i.source_types.join(", ")].join(" · ");
    }

    function requestFor(draft, period, start, end, requestId) {
        if (!PERIODS.includes(period)) throw Error("Choose a valid period.");
        if (period === "custom" && (!validDate(start) || !validDate(end) || start > end)) {
            throw Error("Choose both custom dates, with the start on or before the end.");
        }
        const handoffs = {};
        const required = draft.display_mode === "both" ? ["risk", "market"] : [draft.display_mode];
        for (const kind of required) {
            const handoff = checkedHandoff(draft[kind]);
            if (handoff.kind !== kind || handoff.reset_generation !== draft.reset_generation) {
                throw Error("Choose a current " + kind + " series.");
            }
            handoffs[kind] = handoff;
        }
        return {schema_version: 1, display_mode: draft.display_mode, handoffs,
            period, start_date: period === "custom" ? start : null,
            end_date: period === "custom" ? end : null, request_id: requestId};
    }

    function sameSelection(a, b) {
        if (!a || !b || a.display_mode !== b.display_mode || a.period !== b.period ||
            a.start_date !== b.start_date || a.end_date !== b.end_date) return false;
        return ["risk", "market"].every(kind => {
            const x = a.handoffs[kind], y = b.handoffs && b.handoffs[kind];
            return !x && !y || sameIdentity(x, y) &&
                x.source_revision === y.source_revision && x.snapshot_date === y.snapshot_date &&
                x.reset_generation === y.reset_generation &&
                JSON.stringify(x.filter_view) === JSON.stringify(y.filter_view);
        });
    }

    const OPTION_LIMIT = 100;
    const EMPTY_INDEX = {
        byKey: new Map(), byIdentity: new Map(),
        lists: {risk: [], market: [], both: []}
    };
    // One replaceable index of immutable identity metadata, never user selection
    // or financial rows. A new Store object/timestamp invalidates it.
    let cachedCatalog = null;
    let cachedTimestamp = null;
    let cachedGeneration = null;
    let cachedIndex = EMPTY_INDEX;
    const searchParts = value => String(value == null ? "" : value)
        .normalize("NFKC").toLowerCase().match(/[a-z0-9]+/g) || [];

    function catalogIndexFor(catalog, timestamp) {
        if (!catalog || !Array.isArray(catalog.entries)) {
            cachedCatalog = null; cachedTimestamp = null;
            cachedGeneration = null; cachedIndex = EMPTY_INDEX;
            return EMPTY_INDEX;
        }
        if (cachedCatalog === catalog && cachedTimestamp === timestamp &&
            cachedGeneration === catalog.generation) return cachedIndex;
        const byKey = new Map(), byIdentity = new Map(), listed = [];
        for (const entry of catalog.entries) {
            const displayLabel = label(entry), parts = searchParts(displayLabel);
            const record = Object.assign({}, entry, {
                displayLabel, sortLabel: displayLabel.toLowerCase(),
                searchText: parts.join(""),
                searchAliases: parts.join(" ") + " " + parts.join("")
            });
            byKey.set(record.key, record);
            const key = record.kind + ":" + identityKey(record.identity);
            const matches = byIdentity.get(key) || [];
            matches.push(record); byIdentity.set(key, matches);
            listed.push(record);
        }
        listed.sort((a, b) => a.sortLabel.localeCompare(b.sortLabel) ||
            a.key.localeCompare(b.key));
        const index = {byKey, byIdentity, lists: {
            both: listed,
            risk: listed.filter(record => record.kind === "risk"),
            market: listed.filter(record => record.kind === "market")
        }};
        cachedCatalog = catalog; cachedTimestamp = timestamp;
        cachedGeneration = catalog.generation; cachedIndex = index;
        return index;
    }

    function boundedOptions(index, kind, searchValue, retained) {
        const query = String(searchValue == null ? "" : searchValue);
        const terms = searchParts(query), result = [];
        for (const record of index.lists[kind] || []) {
            if (!terms.every(term => record.searchText.includes(term))) continue;
            result.push({label: record.displayLabel, value: record.key,
                // Keep Dash's local substring filter consistent with this
                // already-matched, punctuation-tolerant token search.
                search: record.searchAliases + " " + query});
            if (result.length === OPTION_LIMIT) break;
        }
        if (retained && !result.some(option => option.value === retained.value)) {
            if (result.length === OPTION_LIMIT) result.pop();
            result.push({label: retained.label, value: retained.value,
                search: retained.label + " " + query});
        }
        return result;
    }

    function workspaceEditor(rawQuick, catalogTimestamp, mode, primaryKey, companionKey,
        clearClicks, loadClicks, reset, period, start, end, primarySearch, companionSearch,
        previous, consumed, loaded, rawCatalog) {
        const nu = window.dash_clientside.no_update;
        const unchanged = () => Array(13).fill(nu);
        // Wait for the Data controls to mount. The session handoff remains pending.
        if (!MODES.includes(mode)) return unchanged();
        const context = window.dash_clientside.callback_context || {};
        const triggered = new Set((context.triggered || []).map(item => item.prop_id));
        const changed = id => triggered.has(id);
        const old = previous && previous.schema_version === 1 ? previous : {};
        let d = Object.assign({schema_version: 1, initialized: false, display_mode: "risk",
            primary_key: null, primary_kind: null, companion_key: null,
            risk: null, market: null, risk_scope: null, quick_nonce: null,
            rejected_quick_nonce: null, catalog_generation: null, reset_generation: reset}, copy(old));
        let status = "", request = nu, consume = nu, event = "initial", valid = false;
        let options = [], companions = [], companionKind = "market";
        const catalogReady = Boolean(rawCatalog && Array.isArray(rawCatalog.entries));
        let index = EMPTY_INDEX;
        let byKey = index.byKey, byIdentity = index.byIdentity;
        const rawNonce = String(rawQuick && rawQuick.nonce || "");
        const fresh = Boolean(rawNonce && rawNonce !== String(consumed || "") &&
            rawNonce !== String(d.quick_nonce || "") && rawNonce !== String(d.rejected_quick_nonce || ""));
        let quick = null;
        const keyFor = handoff => {
            const matches = byIdentity.get(handoff.kind + ":" + identityKey(handoff.identity)) || [];
            return matches.length === 1 ? matches[0].key : null;
        };
        const isImported = handoff => sameIdentity(handoff, quick) && d.quick_nonce === rawNonce;
        const displayKey = handoff => keyFor(handoff) ||
            (isImported(handoff) ? QUICK : selectedKey(handoff.kind));
        const resolve = key => {
            const entry = byKey.get(key);
            let handoff;
            if (entry) {
                handoff = checkedHandoff({schema_version: 1, kind: entry.kind,
                    identity: entry.identity, metric: entry.kind === "risk" ? "risk" : "current",
                    source_revision: entry.source_revision, snapshot_date: entry.snapshot_date,
                    filter_view: null, reset_generation: reset});
            } else {
                const existing = [d.risk, d.market].find(h => h &&
                    (key === selectedKey(h.kind) || key === QUICK && isImported(h)));
                if (!existing) throw Error("Choose an available exact series.");
                handoff = checkedHandoff(existing);
            }
            if (handoff.kind === "risk") handoff.filter_view = copy(d.risk_scope);
            return handoff;
        };
        const setPrimary = key => {
            status = "";
            if (key == null) {
                d.primary_key = d.primary_kind = d.companion_key = null;
                d.risk = d.market = null;
                return;
            }
            const h = resolve(key);
            if (d.display_mode !== "both" && h.kind !== d.display_mode) {
                throw Error("Series does not match the selected display mode.");
            }
            d.primary_key = key; d.primary_kind = h.kind; d.companion_key = null;
            d.risk = d.market = null; d[h.kind] = h;
        };
        const setMode = value => {
            d.display_mode = value;
            if (value !== "both") {
                d.primary_kind = d[value] ? value : null;
                d.primary_key = d[value] ? displayKey(d[value]) : null;
                d.companion_key = null;
            }
        };
        const setCompanion = key => {
            if (d.display_mode !== "both" || !d.primary_kind) throw Error("Choose the primary series first.");
            const other = opposite(d.primary_kind), h = key == null ? null : resolve(key);
            if (h && h.kind !== other) throw Error("The companion must be the opposite kind.");
            d[other] = h; d.companion_key = key;
        };
        try {
            index = catalogIndexFor(rawCatalog, catalogTimestamp);
            byKey = index.byKey; byIdentity = index.byIdentity;
            if (!integer(reset)) throw Error("Invalid cache reset; reload the page.");
            if (rawQuick && rawQuick.handoff) {
                try { quick = checkedHandoff(rawQuick.handoff); }
                catch (error) { if (fresh) throw error; }
            }
            if (!fresh) for (const kind of ["risk", "market"]) {
                if (d[kind]) {
                    try {
                        d[kind] = checkedHandoff(d[kind]);
                        if (d[kind].kind !== kind) throw Error("Mismatched saved kind");
                    } catch (error) {
                        d[kind] = null;
                        if (d.primary_kind === kind) d.primary_key = d.primary_kind = null;
                        else d.companion_key = null;
                        if (kind === "risk") d.risk_scope = null;
                        status = "The saved selection is invalid; choose another series.";
                    }
                }
            }
            if (fresh) {
                if (!quick || quick.reset_generation !== reset) {
                    throw Error("Quick selection predates Clear Cache; reopen it from Risk.");
                }
                event = "handoff";
                d.display_mode = quick.kind; d.primary_kind = quick.kind;
                d.risk = d.market = null; d[quick.kind] = quick;
                d.risk_scope = quick.kind === "risk" ? copy(quick.filter_view) : null;
                d.quick_nonce = rawNonce; d.primary_key = displayKey(quick); d.companion_key = null;
            } else if (!d.initialized) {
                // Restore before interpreting the layout's initial empty picker values.
                if (!d.risk && !d.market && loaded && MODES.includes(loaded.display_mode)) {
                    d.display_mode = loaded.display_mode;
                    for (const kind of ["risk", "market"]) {
                        if (loaded.handoffs && loaded.handoffs[kind]) {
                            d[kind] = checkedHandoff(loaded.handoffs[kind]);
                        }
                    }
                    d.primary_kind = d.risk ? "risk" : d.market ? "market" : null;
                    d.risk_scope = d.risk ? copy(d.risk.filter_view) : null;
                    if (rawNonce === String(consumed || "")) d.quick_nonce = rawNonce;
                }
                if (d.primary_kind && d[d.primary_kind]) {
                    d.primary_key = displayKey(d[d.primary_kind]);
                    const other = opposite(d.primary_kind);
                    d.companion_key = d.display_mode === "both" && d[other] ? displayKey(d[other]) : null;
                }
            } else if (changed("reset-generation-store.data") && d.reset_generation !== reset) {
                event = "reset";
            } else if (changed("data-load-history-button.n_clicks") && loadClicks > 0) {
                event = "load";
                // A click and edited values can arrive in the same browser update.
                if (changed("data-clear-risk-scope.n_clicks") && clearClicks > 0) {
                    d.risk_scope = null; if (d.risk) d.risk.filter_view = null;
                }
                if (changed("data-display-mode.value") && mode !== d.display_mode) setMode(mode);
                if (changed("data-series-picker.value") && primaryKey !== old.primary_key) setPrimary(primaryKey);
                if (changed("data-companion-picker.value") && companionKey !== old.companion_key) setCompanion(companionKey);
            } else if (changed("data-clear-risk-scope.n_clicks") && clearClicks > 0) {
                event = "clear_scope"; d.risk_scope = null;
                if (d.risk) d.risk.filter_view = null;
            } else if (changed("data-display-mode.value") && mode !== d.display_mode) {
                event = "mode"; setMode(mode);
            } else if (changed("data-series-picker.value") && primaryKey !== d.primary_key) {
                event = "primary"; setPrimary(primaryKey);
            } else if (changed("data-companion-picker.value") && companionKey !== d.companion_key) {
                event = "companion"; setCompanion(companionKey);
            } else if (changed("data-history-catalog-store.modified_timestamp")) {
                event = "catalog";
            } else if (changed("data-series-picker.search_value") ||
                changed("data-companion-picker.search_value")) {
                event = "search";
            } else { event = "dates"; }

            // Reset also covers a saved request restored after a cache clear.
            if ([d.risk, d.market].some(h => h && h.reset_generation !== reset)) event = "reset";
            if (event === "reset") {
                for (const kind of ["risk", "market"]) if (d[kind]) d[kind].reset_generation = reset;
                request = null; status = "Cache cleared — press Load to reload this selection";
            }
            d.reset_generation = reset;
            if (catalogReady && ["initial", "catalog"].includes(event)) {
                for (const kind of ["risk", "market"]) {
                    if (d[kind] && !keyFor(d[kind]) && !isImported(d[kind])) {
                        d[kind] = null; status = "This series is no longer available; choose another";
                    }
                }
                d.primary_key = d.primary_kind && d[d.primary_kind] ? displayKey(d[d.primary_kind]) : null;
                if (!d.primary_key) d.primary_kind = null;
            }
            const primary = d.primary_kind && d[d.primary_kind];
            companionKind = opposite(d.primary_kind);
            if (d.display_mode === "both" && primary) {
                const mayPair = ["initial", "mode", "primary"].includes(event) ||
                    event === "load" && (changed("data-display-mode.value") || changed("data-series-picker.value"));
                const clearedCompanion = changed("data-companion-picker.value") && companionKey == null &&
                    companionKey !== old.companion_key;
                if (!d[companionKind] && mayPair && !clearedCompanion &&
                    primary.identity.identity_mode === "underlying" && primary.identity.source_types.length === 1) {
                    const matches = byIdentity.get(companionKind + ":" + identityKey(primary.identity)) || [];
                    if (matches.length === 1) d[companionKind] = resolve(matches[0].key);
                }
                d.companion_key = d[companionKind] ? displayKey(d[companionKind]) : null;
            } else { d.companion_key = null; }

            valid = Boolean(primary && d.primary_key &&
                (d.display_mode === "both" ? d.risk && d.market && d.companion_key : d[d.display_mode]));
            if ((event === "handoff" || event === "load") && valid) {
                const token = window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() :
                    Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
                request = requestFor(d, period || "all", start, end, token);
                if (d.quick_nonce && d.quick_nonce === rawNonce && String(consumed || "") !== rawNonce) consume = rawNonce;
            }
            if (!status && !valid) status = d.display_mode === "both" && primary ?
                "Choose the " + companionKind + " series to compare" : "Choose an exact series";
            if (!status && valid) {
                try {
                    const candidate = requestFor(d, period || "all", start, end, "draft");
                    status = request !== nu && request !== null || sameSelection(candidate, loaded) ?
                        "" : "Selection changed — press Load";
                } catch (error) { status = error.message; }
            }
            d.catalog_generation = catalogReady ? rawCatalog.generation : null;
            d.initialized = true;
        } catch (error) {
            status = error.message || "The selection is invalid; choose another series.";
            request = event === "reset" ? null : nu;
            if (fresh && event !== "handoff") d.rejected_quick_nonce = rawNonce;
            d.initialized = true;
        }
        // Search changes only these bounded option lists. The selected keys,
        // handoffs, scope and loaded request are never kept in the index.
        const retainedOption = (key, handoff, kind) => {
            if (!key || !handoff || (kind !== "both" && handoff.kind !== kind)) return null;
            const record = byKey.get(key);
            if (record) return {value: key, label: record.displayLabel};
            try {
                return {value: key, label: label(handoff) +
                    (isImported(handoff) ? " · from Quick " +
                        (handoff.kind === "risk" ? "Risk" : "Market") :
                        " · selected (catalogue loading)")};
            } catch (_error) { return null; }
        };
        const selectedPrimary = d.primary_kind && d[d.primary_kind];
        options = boundedOptions(index, d.display_mode, primarySearch,
            retainedOption(d.primary_key, selectedPrimary, d.display_mode));
        companions = d.display_mode === "both" && selectedPrimary ?
            boundedOptions(index, companionKind, companionSearch,
                retainedOption(d.companion_key, d[companionKind], companionKind)) : [];
        const scope = d.risk_scope;
        const scopeText = scope ? "Risk scope: " + (scope.exclude_selected ? "Exclude selected" : "Include selected") +
            "; " + (Object.entries(scope.filters || {}).map(([key, values]) => key + "=" +
                (Array.isArray(values) ? values.join(", ") : "invalid scope")).join("; ") || "no restrictions") :
            "Risk scope: all archived positions for the selected identity";
        return [d, d.display_mode, options, d.primary_key, companions, d.companion_key,
            (companionKind === "risk" ? "Risk" : "Market") + " series to compare",
            d.display_mode !== "both", !valid, scopeText, status, request, consume];
    }
    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.cube = window.dash_clientside.cube || {};
    window.dash_clientside.cube.workspaceEditor = workspaceEditor;
}());
```

Keep only one copy of this asset in the active assets directory. The index is rebuilt when its catalogue/timestamp changes, including clear/reload; it must not retain an old lookup after a new catalogue arrives. Per-user selection remains in the existing browser draft store. The current catalogue object is treated as immutable, as with the existing Dash Store contract.

### B4. Replace the one clientside registration

Open `cube/pages/data/s03_callbacks.py`. Keep its current imports. Ensure the following names are imported from `dash`:

```python
from dash import ClientsideFunction, Input, Output, State
```

Inside `register_callbacks`, replace only the existing `app.clientside_callback(...)` call that registers `cube.workspaceEditor` with this full block. Its four-space indentation is intentional. Do not add a second registration or restore the removed Python editor.

```python
    app.clientside_callback(
        ClientsideFunction(namespace="cube", function_name="workspaceEditor"),
        Output("data-workspace-draft-store", "data"),
        Output("data-display-mode", "value"),
        Output("data-series-picker", "options"),
        Output("data-series-picker", "value"),
        Output("data-companion-picker", "options"),
        Output("data-companion-picker", "value"),
        Output("data-companion-label", "children"),
        Output("data-companion-control", "hidden"),
        Output("data-load-history-button", "disabled"),
        Output("data-risk-scope-caption", "children"),
        Output("data-draft-status", "children"),
        Output("data-history-request-store", "data"),
        Output("data-history-handoff-consumed-store", "data"),
        Input("data-history-handoff-store", "data"),
        Input("data-history-catalog-store", "modified_timestamp", allow_optional=True),
        Input("data-display-mode", "value", allow_optional=True),
        Input("data-series-picker", "value", allow_optional=True),
        Input("data-companion-picker", "value", allow_optional=True),
        Input("data-clear-risk-scope", "n_clicks", allow_optional=True),
        Input("data-load-history-button", "n_clicks", allow_optional=True),
        Input("reset-generation-store", "data"),
        Input("data-period", "value", allow_optional=True),
        Input("data-custom-range", "start_date", allow_optional=True),
        Input("data-custom-range", "end_date", allow_optional=True),
        Input("data-series-picker", "search_value", allow_optional=True),
        Input("data-companion-picker", "search_value", allow_optional=True),
        State("data-workspace-draft-store", "data", allow_optional=True),
        State("data-history-handoff-consumed-store", "data"),
        State("data-history-request-store", "data"),
        State("data-history-catalog-store", "data", allow_optional=True),
        prevent_initial_call=False,
    )
```

There are **13 Inputs, then 4 States**, matching the seventeen JavaScript arguments exactly:

| Positions | Arguments |
|---|---|
| 1–5 | `rawQuick`, `catalogTimestamp`, `mode`, `primaryKey`, `companionKey` |
| 6–11 | `clearClicks`, `loadClicks`, `reset`, `period`, `start`, `end` |
| 12–13 — new Inputs | `primarySearch`, `companionSearch` |
| 14–17 — existing States | `previous`, `consumed`, `loaded`, `rawCatalog` |

The thirteen Outputs and their return order remain unchanged. In particular, the browser editor owns the Load button's disabled property and the submitted request. The Python loader may keep its existing running-state button text.

Keep catalogue **modified_timestamp as Input** and complete catalogue **data as State**. Do not change it back to catalogue data as Input: the earlier Quick-prefill repair uses this arrangement so an incoming Quick selection can appear while the catalogue callback is pending. The new search Inputs must not be added to catalogue preparation or history loading.

### B5. Keep the two existing dropdowns searchable

In `cube/pages/data/s02_view.py`, find the existing `dcc.Dropdown` with `id="data-series-picker"`, and the one with `id="data-companion-picker"`. Do not add a second pair.

The minimal complete copies are below. Keep each in its existing wrapper, keep the existing mode control, companion label/visibility wrapper, and preserve additional local `className`, `style`, `persistence` or accessibility settings when applying these properties. The picker values are still owned by the browser editor.

```python
dcc.Dropdown(
    id="data-series-picker",
    options=[],
    value=None,
    searchable=True,
    clearable=True,
    placeholder="Type a series — up to 100 matches",
),
```

```python
dcc.Dropdown(
    id="data-companion-picker",
    options=[],
    value=None,
    searchable=True,
    clearable=True,
    placeholder="Type a companion — up to 100 matches",
),
```

Typing changes only the bounded option list. A currently selected item is kept in that list even if it is outside the search result, so its value/label does not disappear. Both mode still uses an exact Risk plus Market pair. Display names are never parsed to reconstruct financial identities.

### B6. Keep catalogue preparation independent and keep all identities

This is a wiring check; do not replace the working catalogue helper with one from the old Part B.

1. Keep your current helper and argument order. Existing versions use either `load_data_catalog(manager, repository, cache_state)` or `load_archive_catalog(repository, cache_state, refresh_manager)`. Both refer here to your already-implemented **current-plus-archive** logic. A matching name alone is not proof the body is correct.
2. Keep the complete identity catalogue in `data-history-catalog-store`. It includes `generation`, `entries`, and your existing revision metadata. Each entry needs its existing `key`, `kind`, `identity`, `source_revision` and `snapshot_date`. Keep the exact identity's `source_types`, `risk_type`, `risk_greek`, `underlying` and `identity_mode` fields. Do not add positions or history values to this catalogue.
3. Keep the existing bulk `SearchCatalog.history_identities()` and manager `data_history_identities()` path, plus the archive/current merge and cache invalidation. Current-only and archived-only series must both remain discoverable.
4. In `refresh_archive_catalog`, retain the cache-state Input and its existing committed revision Input: either `data-revision-store.data` or `refresh-commit-revision.children`, whichever your app already uses. Keep its Outputs, State, helper call and error handling.
5. Remove only selector, search, draft-date, request or player-tick Inputs that were accidentally attached to that catalogue callback, plus their matching positional parameters. It should not rebuild because you type, change mode, move a slider or press Load. Keep initial invocation enabled.

**This clientside approach still sends the full identity catalogue when it changes.** It avoids repeated server selection work and sending thousands of options into each dropdown. It does not eliminate the first archive scan, initial JSON transfer or first index build. Do not promise that a slow initial provider/archive read has been fixed by this UI change.

### B7. Preserve the metadata and financial-load boundary

If the earlier clientside repair is already working, keep these parts. The complete metadata callback is included so you do not have to reconstruct its old request dependency.

Inside the same `register_callbacks`, `refresh_archive_generation` should be registered once as follows, using the existing `repository` and `poll_archive_generation` helper:

```python
    @app.callback(
        Output("data-history-cache-state-store", "data"),
        Output("data-clear-status", "children"),
        Input("data-history-generation-interval", "n_intervals"),
        Input("clear-cache-complete-store", "data"),
        State("data-history-cache-state-store", "data"),
        prevent_initial_call=False,
    )
    def refresh_archive_generation(
        _intervals,
        reset_generation,
        previous_state,
    ):
        return poll_archive_generation(
            repository,
            None,
            previous_state,
            reset_generation,
        )
```

Keep the existing metadata interval enabled at `interval=60_000`, starting with `n_intervals=0`. This metadata interval does not belong to Play/Pause. There must be no selected-request Input on the metadata callback; ignoring that argument in the body would still leave a dependency loop.

Keep `load_workspace`'s submitted-request, cache-state, reset and existing committed-revision Inputs. Preserve its parser, `query_workspace_bundle`, current-observation reader, captions, errors and output order. Do not add search, picker, mode, draft-date or player-tick Inputs to it.

For the existing three-output loader, keep its initial guard and the metadata guard below before the `try`/query call. If they already exist, leave them once. Keep `Mapping` imported from `collections.abc` or your existing compatible import.

```python
        if raw_request is None:
            return None, "Choose a series and press Load", "No loaded selection"
        if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
            return (
                None,
                "Preparing history metadata…",
                "Selection ready; waiting for history metadata",
            )
```

The rest of the loader stays as implemented. An empty archive may still have valid metadata and a real current observation; do not require nonempty history or a selected catalogue entry before accepting a fresh Quick request. If your loader has additional intentional Outputs, its guard must preserve their existing return arity too.

### B8. Check ownership and restart

1. Save the JavaScript and the one registration change together. Save dropdown or dependency corrections only where needed.
2. Search your app for `workspaceEditor`: there should be one function export and one active clientside registration. No legacy Python selector should also own its Outputs.
3. Check that there are exactly thirteen matching return values on every editor path and that the thirteen Inputs/four States match B4. A missing/unmounted Data control must not erase the shared request.
4. Confirm that the catalogue still contains `entries`. Confirm that `load_workspace` receives immutable submitted requests, not search strings or the editor's draft.
5. Restart using your normal launcher, then hard-refresh the browser to load the new asset. Keep backups out of `assets/`.

Optional syntax checks from the application directory:

```powershell
node --check assets/data_workspace_editor.js
```

If Node is unavailable in your deployment, use the browser console and the checks below; no new Node installation is required to run the app.

```python
from pathlib import Path

for name in ("cube/pages/data/s03_callbacks.py", "cube/pages/data/s02_view.py"):
    path = Path(name)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
    print("Python syntax OK:", name)
```

### B9. Check the actual user flows

1. Open Data directly. After catalogue readiness, search a series beyond the first 100 and load it. No previous Quick search is required.
2. Try case differences, spaces and punctuation, such as `eurusd` versus `EUR/USD`. Search both the primary and companion dropdowns. Each options result must contain at most 100 items including its current selection.
3. Keep a selected value while typing unrelated text, clearing the search text, changing modes and receiving a catalogue update. A previously loaded request must not overwrite a newer manual choice.
4. Open from Quick Risk while catalogue preparation is pending. The imported identity and Risk scope must appear; catalogue arrival must preserve them and not issue a second request. Repeat from Quick Market; Market must not acquire Portfolio filters.
5. In Both mode, verify raw exact identities pair only when unambiguous. Reported Risk baskets require the appropriate explicit Market companion. Clear a companion and confirm it stays cleared until you choose again.
6. Type, change mode, change period and move the player. Those actions must not invoke the financial loader. Load submits the current valid draft once; a fresh Quick handoff also submits once. Independent periodic metadata traffic is expected.
7. Check a current-only series with no history and an archived-only series absent today. Both must still be selectable, with their existing reader behavior intact.
8. Leave Data and return. An already consumed Quick nonce must not reset a manual selection; a new nonce should work. Clear Cache invalidates the old request and retains the existing reload instruction.
9. Check invalid dates, stale Quick reset, missing companion, bad identity and a removed catalogue identity. The editor shows an error/unavailable state; Python still rejects invalid submitted requests independently. Failed loads must not relabel old figures as new results.
10. Compare first visit with repeat typing/mode changes. If the remaining delay happens before catalogue readiness, inspect catalogue preparation/storage/network. If it happens only on Load, inspect the existing reader/rendering spans. Do not change history limits or omit data to disguise that delay.

### B10. Roll back only this repair if required

Restore the prior working browser-editor JavaScript and its matching registration together, then restart and hard-refresh. Revert only dropdown/dependency edits made for this repair. Keep the unified Data page, current-plus-archive catalogue, validated loader and playback. Do not roll back to the obsolete five-selector Part B. No financial data or saved archives are rewritten by these changes.

## Verification and source references

Part A's dedicated chart code is unchanged in this correction. Its previous isolated checks covered 300 complete curve points, Total/XVA/Hedges reconciliation, one y-axis, missing/zero surface cells, connector order, mixed/scalar shapes, filters and revision mismatch. Synthetic curve/surface previews were inspected in a browser at 1440px, 800px and 390px with no page overflow or JavaScript errors. These were preview checks, not tests of your deployed app.

The corrected Part B is validated separately against the supplied browser-editor code and its complete callback registration. The validation results below are recorded after running those checks; a fixture or local benchmark is not a production latency guarantee.

Node syntax and regression checks passed for 72 editor transitions, including the 100-option caps, normal/virtual selected-value retention, punctuation/case search, primary/companion behavior, resets, stale handoffs, bad metadata and reuse/invalidation of the metadata index. All seven emitted sample requests passed the existing unified-workspace Python parser against the v7 history-model contracts.

The complete replacement registration was exercised in a local Dash 4.4.0 browser fixture using 2,406 invented catalogue identities. Quick prefill worked while catalogue delivery was deliberately held open; release preserved the selection without another load. Searches reached an identity beyond the first 100, retained selections through unrelated search text, and supported both primary and companion selection. The fixture recorded exactly two financial-load calls: the initial fresh Quick request and one explicit Both Load. Typing, mode changes and draft-period changes added none. No JavaScript page errors occurred. This tests the supplied editor/registration with a fixture loader, not your production providers or archive timings.

Source references:

- [Earlier complete browser editor and thirteen-output registration](https://github.com/streamlitdash/Rebirth-V5/blob/335bdce6453b7544d4eac436b7094f35c14864c6/DATA_INTERACTION_FIX.md)
- [Original Quick Risk layout and hierarchy](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/risk/s08_quickrisk.py)
- [Shared risk aggregation and tenor order](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/ui/s02_aggregation.py)

The old Data source in untouched v7 does not contain `workspaceEditor`; the earlier guide above supplied it for the unified implementation. This corrected guide follows that clientside contract instead of pretending the old selector callbacks belong in your current page.

Run `git diff --check` and inspect your own diff before committing application changes. Publishing this Markdown changes the guide only.
