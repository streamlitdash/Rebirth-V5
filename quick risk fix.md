# Quick Risk charts and faster Data choices

Updated 11 September 2026 for `streamlitdash/Rebirth-V5`, branch `v7`. The application baseline is commit `2220a3f4839318863a9131e3fef8118d0f82fb7d`; later v7 commits have changed documentation only. This is a guide to implement, not an application deployment.

## Read this first: order, existing functions and your version

1. Implement Part A, then run its checks.
2. Check the Data layout described below, then implement all of Part B before restarting/testing it. Its browser payload and its consumers must change together.
3. Implement `JTD.md` if required. It is independent of these chart changes.
4. Implement `Hero.md`; its section 1.10 must include the new `render_quick_risk_tenor` callback when Quick Risk is active. If already implemented, preserve/add its acknowledgement Output and corresponding return values when adapting this callback; do not lose the completion mechanism by pasting the baseline return tuple over it.
5. Connect real feeds using `Connectors.md`: shared sources, Cross Gamma, new trades/cashflows, Stock, then P&L/history. No connector migration is required to build these charts.

**You do not need an older guide to create the Data selectors in the inspected v7 baseline.** `choose_risk_type`, `choose_risk_greek`, `choose_underlying` and `choose_history_request` already exist inside `cube/pages/data/s03_callbacks.py::register_callbacks`. They are nested definitions; search inside that function. `choose_history_request` is singular. The Data Underlying dropdown is an inline `dcc.Dropdown(id="data-underlying")` in `s02_view.py`, not a function named `data_underlying_dropdown`.

This revision includes complete affected function bodies, callback decorators, imports and the dropdown block. "Replace" means remove the old definition and its decorator if the supplied block includes one. "Add" means add it once at the stated indentation. Do not register two callbacks for the same Output, even under different Python names.

**Version check:** this baseline's Data page has Risk History / Market History tabs and `data-risk-type`, `data-risk-greek`, `data-underlying`. A local version using Risk / Market / Both and a Choose series editor has a different callback contract. The complete baseline copies below make the implementation explicit; they are not a license to overwrite that newer page. For that version, retain its controls and map the server-catalog/search logic to its actual callback Inputs, Outputs and request format. That mapping requires the actual source; unseen code cannot be guaranteed compatible. A missing function alone is not a reason to recreate the old Data page.

Run from your repository root before editing:

```powershell
git status --short
rg -n 'def (choose_risk_type|choose_risk_greek|choose_underlying|choose_history_request)|data-underlying' cube/pages/data
rg -n 'def (detail_frame|tenor_axis_order|_meaningful_tenor_mask)|class _RiskDataCache|def register_workspace_callbacks' cube
```

Keep your local changes. Use the existing v7 aggregation/cache/filter implementations. If those core contracts are absent too, compare the actual source with v7 before transplanting this guide; do not fill a missing financial calculation with guessed values.

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

## Part B — make Data choices searchable without sending the whole catalog

This part is now a complete set of replacement definitions, including the callback decorators and helper bodies. It is independent of the Quick Risk chart changes in Part A. Apply all of Part B as one group, then restart and test: a generation-only catalog store and the old catalog consumers cannot run together.

### B1. Check the Data version and where the functions belong

The audited GitHub source has Risk History / Market History tabs and these three component IDs: `data-risk-type`, `data-risk-greek`, and `data-underlying`. It uses `ArchiveHistoryRepository` and `HistoryHandoff`.

| What to look for | Exact existing location in the audited source |
|---|---|
| `choose_risk_type` | Nested inside `cube/pages/data/s03_callbacks.py::register_callbacks` |
| `choose_risk_greek` | In that same registration function |
| `choose_underlying` | In that same registration function |
| `choose_history_request` | In that same registration function; singular **request** |
| Underlying dropdown | Inline `dcc.Dropdown(id="data-underlying")` inside `cube/pages/data/s02_view.py::build_data_page` |

There is no function called `data_underlying_dropdown` or `chooser_history_requests`. The full definitions below remove the need to infer any of their bodies.

For the five callback replacements in B6:

1. If the named callback exists, replace its complete `@app.callback(...)` decorator **and** function body with the corresponding block below.
2. If your callback has another name but owns the same Outputs, replace that existing owner; do not add a second owner of those Outputs.
3. Add a missing block once inside `register_callbacks` only if this same three-selector layout, typed history contracts, and repository wiring are present and no callback owns those Outputs.
4. Keep all other callbacks in `register_callbacks`. In particular, retain the identity-mode/breadcrumb callbacks, archive-generation polling, history loading, custom-date controls, and clientside playback callbacks. Do not replace the whole `s03_callbacks.py` file or the whole registration function.

**Different deployed layout:** if your Data page has the newer Risk / Market / Both workspace with “Choose series”, these replacements are not a migration for it. Its callbacks and state contract need to be mapped from its actual source. Do not recreate the old selectors, add duplicate callback owners, or overwrite the newer page just to make the names match. This guide supplies complete code for the audited GitHub version; it cannot safely replace callbacks in an unseen local variant.

### B2. Keep one server catalog and understand the 100-option limit

The existing archive repository already caches its immutable identity catalog by archive generation. Keep that catalog there. The browser will receive only `{"generation": "..."}` as a readiness marker and at most 100 dropdown options per search.

This is a limit on **visible choices**, not on the positions, dates, portfolios, or history you can read. Type a name to find any other identity, including an archived instrument absent from today's Quick Risk catalog. The selected identity is retained within the 100-option total. History requests, exact identity validation, history budgets, and playback remain unchanged.

The cold archive scan may still take seconds. This change removes the unnecessary whole-catalog transfer, repeated reconstruction, and unbounded option rendering; it does not claim to make cold storage access instant. The page shell and navigation must remain usable while the existing status says “Preparing archive choices…”.

### B3. Calculate each immutable identity key once

Open `cube/history/s01_models.py`. Add this import alongside its standard-library imports if it is not already present:

```python
from functools import cached_property
```

Inside `class HistoryCatalogEntry`, replace the complete `key` property, including its current `@property` decorator, with this block. Do not replace the class, its fields, or its validation methods.

```python
    @cached_property
    def key(self) -> str:
        payload = {
            "kind": self.kind,
            "identity": self.identity.to_mapping(),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()
```

The key's value is unchanged. `HistoryCatalogEntry` is frozen, so caching its key avoids repeating the same JSON serialization and SHA calculation on every search. It is one string per existing catalog entry, not another cache of financial frames.

### B4. Install the complete selection helpers

Open `cube/pages/data/s01_selection.py`. The block below is the complete final content of the small selection module in the audited baseline. To preserve local additions, update its import block and replace each existing function with the complete same-named definition below; add a function only if missing. Keep unrelated local helpers or imports, and include their existing names if you maintain additional `__all__` exports. Do not leave two definitions of the same function.

On the unmodified audited module, these are all of its imports, functions, and exports. The behavior change is in `underlying_options`; the other complete bodies are included so there are no missing local helper definitions to guess.

```python
"""Pure direct-selection helpers owned by the V5 Data page."""

from __future__ import annotations

from collections import Counter
from cube.domain.s10_search import _dropdown_search_terms, _dropdown_search_label
from cube.pages.risk.s10_search import _combine_udl_browser_search
from collections.abc import Sequence

from cube.history import (
    HistoryCatalogEntry,
    HistoryHandoff,
    HistoryIdentityCatalog,
    HistoryValidationError,
)


def _catalog(value: object) -> HistoryIdentityCatalog:
    return (
        value
        if isinstance(value, HistoryIdentityCatalog)
        else HistoryIdentityCatalog.from_mapping(value)
    )


def effective_identity_mode(kind: object, mode: object) -> str:
    """Market always uses raw Underlying; Risk defaults to reported identity."""

    if str(kind or "risk").strip().casefold() == "market":
        return "underlying"
    selected = str(mode or "reported").strip().casefold()
    return selected if selected in {"reported", "underlying"} else "reported"


def matching_entries(
    raw_catalog: object,
    *,
    kind: object,
    identity_mode: object,
    risk_type: object = None,
    risk_greek: object = None,
) -> tuple[HistoryCatalogEntry, ...]:
    catalog = _catalog(raw_catalog)
    selected_kind = str(kind or "risk").strip().casefold()
    selected_mode = effective_identity_mode(selected_kind, identity_mode)
    selected_type = str(risk_type or "").strip()
    selected_greek = str(risk_greek or "").strip()
    return tuple(
        entry
        for entry in catalog.entries
        if entry.kind == selected_kind
        and entry.identity.identity_mode == selected_mode
        and (not selected_type or entry.identity.risk_type == selected_type)
        and (not selected_greek or entry.identity.risk_greek == selected_greek)
    )


def risk_type_options(
    raw_catalog: object, kind: object, identity_mode: object
) -> list[dict[str, str]]:
    values = sorted(
        {
            entry.identity.risk_type
            for entry in matching_entries(
                raw_catalog,
                kind=kind,
                identity_mode=identity_mode,
            )
        },
        key=str.casefold,
    )
    return [{"label": value, "value": value} for value in values]


def risk_greek_options(
    raw_catalog: object,
    kind: object,
    identity_mode: object,
    risk_type: object,
) -> list[dict[str, str]]:
    values = sorted(
        {
            entry.identity.risk_greek
            for entry in matching_entries(
                raw_catalog,
                kind=kind,
                identity_mode=identity_mode,
                risk_type=risk_type,
            )
        },
        key=str.casefold,
    )
    return [{"label": value, "value": value} for value in values]


def underlying_options(
    raw_catalog: object,
    kind: object,
    identity_mode: object,
    risk_type: object,
    risk_greek: object,
    *,
    search_value: str | None = None,
    limit: int = 100,
    include: object = None,
) -> list[dict[str, str]]:
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
        raise ValueError("option limit must be a positive integer")
    entries = matching_entries(
        raw_catalog, kind=kind, identity_mode=identity_mode,
        risk_type=risk_type, risk_greek=risk_greek,
    )
    terms = _dropdown_search_terms(search_value)
    counts = Counter(entry.identity.underlying for entry in entries)
    options = []
    selected_option = None
    for entry in entries:
        if len(options) >= limit and (include is None or selected_option is not None):
            break
        label = entry.identity.underlying
        if counts[label] > 1:
            label = f"{label} · {', '.join(entry.identity.source_types)}"
        search = _dropdown_search_label(label)
        matches = all(term in search for term in terms)
        selected = entry.key == include
        if not selected and (len(options) >= limit or not matches):
            continue
        option = {
            "label": label, "value": entry.key,
            "search": _combine_udl_browser_search(label),
        }
        if selected:
            selected_option = option
        if len(options) < limit and matches:
            options.append(option)
    if selected_option is not None and not any(
        option["value"] == selected_option["value"] for option in options
    ):
        options = options[:limit - 1] + [selected_option]
    return options


def selected_value(
    options: Sequence[dict[str, str]],
    current: object = None,
    preferred: object = None,
) -> str | None:
    """Keep a valid current/preferred choice, otherwise choose the first option."""

    values = [option["value"] for option in options]
    for candidate in (preferred, current):
        if candidate in values:
            return str(candidate)
    return values[0] if values else None


def catalog_key_for_handoff(raw_catalog: object, raw_handoff: object) -> str | None:
    try:
        catalog = _catalog(raw_catalog)
        handoff = HistoryHandoff.from_mapping(raw_handoff)
    except (HistoryValidationError, TypeError, ValueError):
        return None
    for entry in catalog.entries:
        if entry.kind == handoff.kind and entry.identity == handoff.identity:
            return entry.key
    return None


def direct_history_handoff(
    raw_catalog: object,
    entry_key: object,
    *,
    kind: object,
    reset_generation: object,
) -> HistoryHandoff:
    catalog = _catalog(raw_catalog)
    entry = catalog.resolve(entry_key)
    selected_kind = str(kind or "risk").strip().casefold()
    if entry.kind != selected_kind:
        raise HistoryValidationError("selected identity belongs to another history tab")
    if isinstance(reset_generation, bool):
        raise HistoryValidationError("reset generation must be an integer")
    try:
        reset = int(reset_generation or 0)
    except (TypeError, ValueError) as exc:
        raise HistoryValidationError("reset generation must be an integer") from exc
    return entry.to_handoff(reset_generation=reset)


__all__ = [
    "catalog_key_for_handoff",
    "direct_history_handoff",
    "effective_identity_mode",
    "matching_entries",
    "risk_greek_options",
    "risk_type_options",
    "selected_value",
    "underlying_options",
]
```

The three imported Quick-search normalization helpers already exist in the audited code: `_dropdown_search_terms` and `_dropdown_search_label` in `cube/domain/s10_search.py`, and `_combine_udl_browser_search` in `cube/pages/risk/s10_search.py`. Keep those implementations. They preserve case/punctuation handling and Dash's browser-search aliases. If those modules are also different or absent, the baseline check in B1 has failed; do not substitute an unrelated normalizer without comparing the source.

### B5. Supply complete callback imports and top-level helpers

Open `cube/pages/data/s03_callbacks.py`. Keep its other functions. Ensure its top import block contains the following complete baseline imports. Keep any additional imports used by local code; do not paste a second `from __future__` below executable code.

```python
"""Page-owned lazy query and playback callbacks for V5 Data history."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import date, datetime
from typing import Mapping

import numpy as np
import pandas as pd
from dash import ClientsideFunction, Dash, Input, Output, State, ctx, no_update

from cube.history import (
    HISTORY_CANONICAL_CELL_BUDGET,
    HISTORY_RAW_ROW_BUDGET,
    ArchiveHistoryRepository,
    HistoryBundle,
    HistoryHandoff,
    HistoryQuery,
    HistoryValidationError,
)
from .s01_selection import (
    catalog_key_for_handoff,
    direct_history_handoff,
    risk_greek_options,
    risk_type_options,
    selected_value,
    underlying_options,
)
```

Keep this constant once at module level, after the imports:

```python
QUICK_HANDOFF_ENTRY_KEY = "__quick_handoff__"
```

The following helpers are called by the replacement callbacks. They belong at **module level**, outside `register_callbacks`, before it is defined. They are unchanged baseline helpers, provided in full. Keep an identical existing definition; if it is absent in an otherwise compatible three-selector implementation, add it once. If a local definition has changed intentionally, compare that change before replacing it.

```python
def _stored_history_handoff(raw_handoff: object) -> HistoryHandoff:
    payload = (
        raw_handoff.get("handoff")
        if isinstance(raw_handoff, Mapping) and "handoff" in raw_handoff
        else raw_handoff
    )
    return HistoryHandoff.from_mapping(payload)


def _stored_handoff_nonce(raw_handoff: object) -> str:
    if isinstance(raw_handoff, Mapping):
        nonce = str(raw_handoff.get("nonce") or "").strip()
        if nonce:
            return nonce
    handoff = _stored_history_handoff(raw_handoff)
    return f"legacy-{handoff.kind}-{handoff.source_revision}"


def _pending_history_handoff(
    raw_handoff: object,
    consumed_nonce: object,
) -> HistoryHandoff:
    nonce = _stored_handoff_nonce(raw_handoff)
    if nonce == str(consumed_nonce or ""):
        raise HistoryValidationError("history handoff was already consumed")
    return _stored_history_handoff(raw_handoff)


def _requested_history_handoff(raw_request: object) -> HistoryHandoff:
    if not isinstance(raw_request, Mapping) or "handoff" not in raw_request:
        raise HistoryValidationError("history request has no identity")
    return HistoryHandoff.from_mapping(raw_request["handoff"])


def _request_query(raw_request: object) -> HistoryQuery:
    if not isinstance(raw_request, Mapping):
        raise HistoryValidationError("history request must be a mapping")
    request_error = str(raw_request.get("error") or "").strip()
    if request_error:
        raise HistoryValidationError(request_error)
    handoff = HistoryHandoff.from_mapping(raw_request.get("handoff"))
    period = str(raw_request.get("period") or "all").strip().casefold()
    return HistoryQuery(
        handoff=handoff,
        period=period,
        start_date=(raw_request.get("start_date") if period == "custom" else None),
        end_date=(raw_request.get("end_date") if period == "custom" else None),
    )


def history_request_payload(
    handoff: HistoryHandoff,
    *,
    period: object = "all",
    start_date: object = None,
    end_date: object = None,
    request_id: object = None,
) -> dict[str, object]:
    """Build the one immutable request consumed by the archive callback."""

    selected_metric = "risk" if handoff.kind == "risk" else "current"
    selected_handoff = replace(handoff, metric=selected_metric)
    selected_period = str(period or "all").strip().casefold()
    query = HistoryQuery(
        handoff=selected_handoff,
        period=selected_period,
        start_date=(start_date if selected_period == "custom" else None),
        end_date=(end_date if selected_period == "custom" else None),
    )
    return {
        "handoff": selected_handoff.to_mapping(),
        "period": query.period,
        "start_date": (
            query.start_date.isoformat() if query.start_date is not None else None
        ),
        "end_date": query.end_date.isoformat() if query.end_date is not None else None,
        "request_id": None if request_id is None else str(request_id),
    }
```

Now replace the complete top-level `load_archive_catalog` function with this one. It returns the readiness marker, never `catalog.to_mapping()`:

```python
def load_archive_catalog(
    repository: ArchiveHistoryRepository,
    cache_state: object,
) -> tuple[dict[str, object] | None, str]:
    """Load the tiny direct-selector catalog after the Data route is mounted."""

    if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
        return None, "Preparing archive choices…"
    catalog = repository.catalog()
    risk_count = sum(entry.kind == "risk" for entry in catalog.entries)
    market_count = sum(entry.kind == "market" for entry in catalog.entries)
    if not catalog.entries:
        status = (
            "No completed schema-v4 Risk or Market archive identities are available."
        )
    else:
        status = (
            f"Archive ready: {risk_count:,} Risk and {market_count:,} Market choices."
        )
    return {"generation": catalog.generation}, status
```

### B6. Replace the five nested callback blocks

All five blocks below belong inside the existing function with this header:

```python
def register_callbacks(
    app: Dash,
    repository: ArchiveHistoryRepository,
) -> None:
```

That header is a location marker, not an additional function to paste. Each block below already has its required four-space indentation. Use the replacement rules in B1, keep exactly one owner per Output, and retain every other callback in that registration function.

#### B6.1. Catalog readiness

Replace `refresh_archive_catalog` and its decorator. The current store is now checked by generation only; it no longer contains an `entries` list.

```python
    @app.callback(
        Output("data-history-catalog-store", "data"),
        Output("data-catalog-status", "children"),
        Input("data-history-cache-state-store", "data"),
        State("data-history-catalog-store", "data"),
    )
    def refresh_archive_catalog(cache_state, current):
        if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
            return None, "Preparing archive choices…"
        if (
            isinstance(current, Mapping)
            and current.get("generation") == cache_state.get("generation")
        ):
            return no_update, no_update
        try:
            return load_archive_catalog(repository, cache_state)
        except (OSError, HistoryValidationError, TypeError, ValueError) as error:
            return None, f"Archive choices failed: {error}"
```

#### B6.2. Risk Type

Replace `choose_risk_type` and its decorator. It reads the typed server catalog and retains the Quick handoff fallback while the catalog is preparing.

```python
    @app.callback(
        Output("data-risk-type", "options"),
        Output("data-risk-type", "value"),
        Input("data-history-catalog-store", "data"),
        Input("data-history-kind-tabs", "value"),
        Input("data-identity-mode", "value"),
        Input("data-history-request-store", "data"),
        State("data-risk-type", "value"),
        State("data-history-handoff-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
    )
    def choose_risk_type(
        raw_catalog,
        kind,
        identity_mode,
        raw_request,
        current,
        raw_handoff,
        consumed_nonce,
    ):
        if raw_catalog is None:
            try:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                if (
                    handoff.kind == str(kind or "risk").casefold()
                    and handoff.identity.identity_mode
                    == str(identity_mode or "reported").casefold()
                ):
                    value = handoff.identity.risk_type
                    return [{"label": value, "value": value}], value
            except (HistoryValidationError, TypeError, ValueError):
                pass
            return [], None
        try:
            options = risk_type_options(repository.catalog(), kind, identity_mode)
            preferred = None
            try:
                handoff = _requested_history_handoff(raw_request)
            except (HistoryValidationError, TypeError, ValueError):
                try:
                    handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                except (HistoryValidationError, TypeError, ValueError):
                    handoff = None
            if (
                handoff is not None
                and handoff.kind == str(kind or "risk").casefold()
                and handoff.identity.identity_mode
                == str(identity_mode or "reported").casefold()
            ):
                preferred = handoff.identity.risk_type
            return options, selected_value(options, current, preferred)
        except (OSError, HistoryValidationError, TypeError, ValueError):
            return [], None
```

#### B6.3. Risk Greek

Replace `choose_risk_greek` and its decorator.

```python
    @app.callback(
        Output("data-risk-greek", "options"),
        Output("data-risk-greek", "value"),
        Input("data-history-catalog-store", "data"),
        Input("data-history-kind-tabs", "value"),
        Input("data-identity-mode", "value"),
        Input("data-risk-type", "value"),
        Input("data-history-request-store", "data"),
        State("data-risk-greek", "value"),
        State("data-history-handoff-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
    )
    def choose_risk_greek(
        raw_catalog,
        kind,
        identity_mode,
        risk_type,
        raw_request,
        current,
        raw_handoff,
        consumed_nonce,
    ):
        if risk_type is None:
            return [], None
        if raw_catalog is None:
            try:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                if handoff.kind == str(
                    kind or "risk"
                ).casefold() and handoff.identity.risk_type == str(risk_type):
                    value = handoff.identity.risk_greek
                    return [{"label": value, "value": value}], value
            except (HistoryValidationError, TypeError, ValueError):
                pass
            return [], None
        try:
            options = risk_greek_options(
                repository.catalog(),
                kind,
                identity_mode,
                risk_type,
            )
            preferred = None
            try:
                handoff = _requested_history_handoff(raw_request)
            except (HistoryValidationError, TypeError, ValueError):
                try:
                    handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                except (HistoryValidationError, TypeError, ValueError):
                    handoff = None
            if (
                handoff is not None
                and handoff.kind == str(kind or "risk").casefold()
                and handoff.identity.identity_mode
                == str(identity_mode or "reported").casefold()
                and handoff.identity.risk_type == str(risk_type)
            ):
                preferred = handoff.identity.risk_greek
            return options, selected_value(options, current, preferred)
        except (OSError, HistoryValidationError, TypeError, ValueError):
            return [], None
```

#### B6.4. Underlying search

Replace `choose_underlying` and its decorator together. The decorator includes the new `search_value` Input; the function includes the matching argument in the same position. Do not add a second textbox or another callback just for typing.

```python
    @app.callback(
        Output("data-underlying", "options"),
        Output("data-underlying", "value"),
        Output("data-load-history-button", "disabled"),
        Input("data-history-catalog-store", "data"),
        Input("data-history-kind-tabs", "value"),
        Input("data-identity-mode", "value"),
        Input("data-risk-type", "value"),
        Input("data-risk-greek", "value"),
        Input("data-history-request-store", "data"),
        Input("data-underlying", "search_value"),
        State("data-underlying", "value"),
        State("data-history-handoff-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
    )
    def choose_underlying(
        raw_catalog, kind, identity_mode, risk_type, risk_greek,
        raw_request, search_value, current, raw_handoff, consumed_nonce,
    ):
        if risk_type is None or risk_greek is None:
            return [], None, True
        if raw_catalog is None:
            try:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                if (
                    handoff.kind == str(kind or "risk").casefold()
                    and handoff.identity.identity_mode == str(identity_mode or "reported").casefold()
                    and handoff.identity.risk_type == str(risk_type)
                    and handoff.identity.risk_greek == str(risk_greek)
                ):
                    return [
                        {"label": handoff.identity.underlying, "value": QUICK_HANDOFF_ENTRY_KEY}
                    ], QUICK_HANDOFF_ENTRY_KEY, False
            except (HistoryValidationError, TypeError, ValueError):
                pass
            return [], None, True
        try:
            catalog = repository.catalog()
            preferred = None
            try:
                handoff = _requested_history_handoff(raw_request)
            except (HistoryValidationError, TypeError, ValueError):
                try:
                    handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
                except (HistoryValidationError, TypeError, ValueError):
                    handoff = None
            if (
                handoff is not None
                and handoff.kind == str(kind or "risk").casefold()
                and handoff.identity.identity_mode == str(identity_mode or "reported").casefold()
                and handoff.identity.risk_type == str(risk_type)
                and handoff.identity.risk_greek == str(risk_greek)
            ):
                preferred = catalog_key_for_handoff(catalog, handoff.to_mapping())
            use_preferred = (
                ctx.triggered_id == "data-history-request-store"
                or (
                    ctx.triggered_id == "data-history-catalog-store"
                    and current in (None, QUICK_HANDOFF_ENTRY_KEY)
                )
            )
            if not use_preferred:
                preferred = None
            options = underlying_options(
                catalog, kind, identity_mode, risk_type, risk_greek,
                search_value=search_value, limit=100,
                include=preferred or current,
            )
            selected = selected_value(options, current, preferred)
            return options, selected, selected is None
        except (OSError, HistoryValidationError, TypeError, ValueError):
            return [], None, True
```

This callback sends at most 100 choices, keeps a selected choice outside the first 100, and does not restore the previous loaded request merely because you typed again or a catalog refresh completed. The current browser selection remains browser/session state, not a mutable module global.

#### B6.5. Create a history request

Replace `choose_history_request` and its decorator. The selected opaque key is resolved against `repository.catalog()`; the generation marker is never parsed as a full catalog. Keep the function name singular as shown.

```python
    @app.callback(
        Output("data-history-request-store", "data"),
        Output("data-history-handoff-consumed-store", "data"),
        Input("data-history-handoff-store", "data"),
        Input("data-load-history-button", "n_clicks", allow_optional=True),
        Input("reset-generation-store", "data"),
        State("data-history-kind-tabs", "value", allow_optional=True),
        State("data-history-catalog-store", "data", allow_optional=True),
        State("data-underlying", "value", allow_optional=True),
        State("data-period", "value", allow_optional=True),
        State("data-custom-range", "start_date", allow_optional=True),
        State("data-custom-range", "end_date", allow_optional=True),
        State("data-history-request-store", "data", allow_optional=True),
        State("data-history-handoff-consumed-store", "data"),
    )
    def choose_history_request(
        raw_handoff,
        load_clicks,
        reset_generation,
        kind,
        raw_catalog,
        entry_key,
        period,
        start_date,
        end_date,
        current_request,
        consumed_nonce,
    ):
        triggered = ctx.triggered_id
        if triggered is None and raw_handoff is None:
            return no_update, no_update
        if (
            triggered == "data-load-history-button"
            and int(load_clicks or 0) <= 0
            and raw_handoff is None
        ):
            return no_update, no_update
        if triggered == "data-history-handoff-store":
            if raw_handoff is None:
                return no_update, no_update
            try:
                handoff_nonce = _stored_handoff_nonce(raw_handoff)
            except (HistoryValidationError, TypeError, ValueError):
                handoff_nonce = ""
            if handoff_nonce and handoff_nonce == str(consumed_nonce or ""):
                return no_update, no_update
        try:
            reset = int(reset_generation or 0)
        except (TypeError, ValueError):
            reset = 0
        try:
            if triggered == "data-load-history-button" and int(load_clicks or 0) > 0:
                if entry_key == QUICK_HANDOFF_ENTRY_KEY:
                    handoff = _stored_history_handoff(raw_handoff)
                    if handoff.kind != str(kind or "risk").strip().casefold():
                        raise HistoryValidationError(
                            "Quick history identity belongs to another tab"
                        )
                    handoff = replace(handoff, reset_generation=reset)
                else:
                    handoff = direct_history_handoff(
                        repository.catalog(),
                        entry_key,
                        kind=kind,
                        reset_generation=reset,
                    )
                return history_request_payload(
                    handoff,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    request_id=f"load-{int(load_clicks or 0)}-{reset}",
                ), no_update
            if triggered == "reset-generation-store":
                if current_request is None:
                    return no_update, no_update
                query = _request_query(current_request)
                return history_request_payload(
                    replace(query.handoff, reset_generation=reset),
                    period=query.period,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    request_id=f"reset-{reset}",
                ), no_update
            handoff = _stored_history_handoff(raw_handoff)
            nonce = _stored_handoff_nonce(raw_handoff)
            return history_request_payload(
                replace(handoff, reset_generation=reset),
                period=period,
                start_date=start_date,
                end_date=end_date,
                request_id=f"quick-{nonce}-{reset}",
            ), nonce
        except (OSError, HistoryValidationError, TypeError, ValueError) as error:
            detail = " ".join(str(error).splitlines()).strip() or type(error).__name__
            return {
                "error": detail,
                "request_id": f"invalid-{triggered}-{int(load_clicks or 0)}-{reset}",
            }, no_update
```

The `raw_catalog` argument is retained to match the existing callback State signature; it is only a readiness marker now. The Quick handoff branch, nonce consumption, reset behavior, exact identity validation, and standard `HistoryQuery` construction remain intact.

### B7. Use the complete Underlying dropdown block

Open `cube/pages/data/s02_view.py`, inside `build_data_page`.

Find the `html.Div` whose label is “Underlying” and whose dropdown has `id="data-underlying"`. Replace that one complete control block with the following. Keep it beside the existing Risk Type and Risk Greek controls; do not add a second dropdown with the same ID. Indent it to match its sibling control blocks.

```python
html.Div(
    [
        html.Label("Underlying", htmlFor="data-underlying"),
        dcc.Dropdown(
            id="data-underlying",
            options=[],
            value=None,
            clearable=False,
            searchable=True,
            placeholder="Type an underlying — up to 100 matches",
        ),
    ],
    className="data-control data-underlying-control",
),
```

Keep the existing `html`, `dcc`, and other imports. Keep the catalog store as this single component; there must be no default `entries` payload:

```python
dcc.Store(id="data-history-catalog-store", storage_type="memory"),
```

Keep the existing catalog-status component beside the Load history button. Its complete replacement is:

```python
html.Span(
    "Preparing archive choices…",
    id="data-catalog-status",
    className="data-history-status",
),
```

Keep the rest of `build_data_page`: tabs, identity-mode control, other selectors, load button, periods/dates, result stores, player controls, and graph. No whole-page loading overlay is needed. If you add a spinner, place it only around the identity controls; never cover the shared navigation.

### B8. Check the dependency boundary before restarting

These are existing parts of the application, not new functions to create for this optimization:

| Keep | Why it remains |
|---|---|
| `ArchiveHistoryRepository.catalog()` | Owns/caches all archive identities and generation invalidation |
| `HistoryIdentityCatalog.resolve()` | Resolves an exact opaque identity key |
| `configure_identity_mode`, `sync_quick_handoff`, `configure_request` | Keep tabs, raw/reported mode, and breadcrumb consistent |
| `refresh_archive_generation` / `poll_archive_generation` | Update the archive-generation marker and clear caches correctly |
| `load_history` / `query_history_bundle` | Execute the requested history query |
| `serialize_history_bundle` and clientside playback callbacks | Keep current chart/play-pause behavior and history budgets |
| Shared `data-history-handoff-store`, `data-history-request-store`, and consumed-nonce store | Carry Quick handoffs and the active history request across pages |

Run from the repository root:

```powershell
rg -n 'data-history-catalog-store|raw_catalog|catalog.to_mapping' cube/pages/data
```

Confirm that `load_archive_catalog` returns only generation/status and that all three selectors plus direct history loading resolve against the typed server catalog. Do not pass the generation-only dictionary into `HistoryIdentityCatalog.from_mapping` or `direct_history_handoff`, and do not weaken their validators to accept it.

### B9. Restart once, then verify

1. Open Data and immediately navigate away while the first catalog prepares. Navigation must remain usable. Test a cold start and a second visit separately.
2. Inspect browser Network responses: the catalog response must have generation/status only; Underlying options must contain at most 100 choices including the retained selection.
3. Search with case differences, punctuation, multiple words, an identity beyond the first 100, and duplicate labels with different Source Types. Select an instrument, load it, then select/type another: the earlier loaded instrument must not keep coming back.
4. Test an archived-only identity absent from today's Quick search. It must still be available. The 100-choice cap must not truncate its historical rows or dates.
5. Test direct Data entry; Quick Risk and Quick Market handoffs before and after the archive catalog is ready; Risk Reported/Raw modes; Market mode; Clear Cache; and a newly completed archive generation.
6. Verify that typing in Underlying does not query/load a history bundle. Explicit Load history and a Quick handoff remain the request triggers.
7. If latency remains, compare existing `history.archive.open` and `history.catalog.query` log spans with response size and browser rendering time. Cold archive validation can still take seconds. If navigation requests queue, check storage/CPU contention and that deployment matches `gunicorn.conf.py`: one `gthread` worker, four threads by default through `GUNICORN_THREADS`. Keep one worker because snapshot/progress state is process-local; adding workers is not a safe shortcut here.

Do not promise an unmeasured production speedup. This patch removes the whole-catalog browser transfer/reconstruction and unbounded choice rendering; it preserves the existing archive query and financial-data contracts.

### B10. Roll back as one group if needed

Revert Part B's edits in `cube/history/s01_models.py`, `cube/pages/data/s01_selection.py`, `cube/pages/data/s02_view.py`, and `cube/pages/data/s03_callbacks.py` together, then restart. Do not revert only the store or only one consumer. No archives, positions, or connector outputs are rewritten by this change.

## Final checks and rollback

These snippets were checked against the stated source in an isolated local candidate. The chart callback registered and ran; a 300-point curve retained all points and correct Total/XVA/Hedges sums. Checks covered shared include/exclude filters, revision mismatch, invalid view reset, surface tenor order, missing cells versus zero, padded tenor labels, mixed/scalar coverage and the surface allocation check. The dedicated chart layout contains unique component IDs and no detail tables.

Synthetic curve and surface previews were rendered and visually inspected in a local Chromium browser. At 1440px, 800px and 390px viewport widths they had no page overflow or JavaScript errors. This validates the chart design in a standalone preview; it is not a full end-to-end test of your deployed app, its themes, browser extensions or long production labels. At phone width a heatmap naturally has less space; check your real tenor vocabulary after implementation.

The Data section's complete imported helpers and five replacement callback blocks were executed and registered. A 503-identity fixture covered the 100-choice total, a retained identity outside the first page, archived-only selection, Risk raw/reported and Market modes, punctuation search, prior-request retention rules, Quick handoff before catalog readiness, nonce consumption, and reset handling. These are correctness checks, not a measured production speedup.

Run the Quick Risk and Data tests in your own checkout, adapting any tests that assert the old full browser catalog or import the removed figure function. Add the edge cases listed in A7/B9 to your existing test files. Check Python imports and Dash callback registration, then perform the browser checks. Finally run:

```powershell
git diff --check
git diff --stat
```

To undo Part A, restore your pre-change `s08_quickrisk.py`, `s14_workspacecallbacks.py` and the appended CSS block together; remove `s16_quickriskcharts.py` only after its import/callback has been restored. Keep unrelated CSS or local table customizations. To undo Part B, restore its four files together as described in B10. Restart after either rollback. No archive, JTD CSV, live connector, saved position or financial result is rewritten by implementing this guide.

## Source references

These links are pinned to the application baseline so the instructions remain checkable after the branch moves:

- [Quick Risk layout and original hierarchy/figure](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/risk/s08_quickrisk.py)
- [Workspace callback registration and shared filters](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/risk/s14_workspacecallbacks.py)
- [Existing risk aggregation and tenor-order authority](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/ui/s02_aggregation.py)
- [Existing tenor selector, kept separate from the new chart presentation](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/risk/s05_charts.py)
- [Data callbacks and current request wiring](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/data/s03_callbacks.py)
- [Data layout and dropdown IDs](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/data/s02_view.py)

Publishing this Markdown updates the implementation instructions only. Apply the code changes and run the deployment checks to change the running application.
