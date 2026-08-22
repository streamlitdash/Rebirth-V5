"""Risk-page tenor state, line, heatmap, matrix, and detail-panel builders."""

from __future__ import annotations

import logging
from html import escape as html_escape
from textwrap import wrap

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from shared.aggregation import (
    detail_frame,
    format_number,
    frame_for_context,
    number_sign_class,
    parse_row_key,
    tenor_axis_order,
)
from shared.constants import METRIC_BREAKDOWNS, PLOT_METRICS, ROW_KEY_COLUMNS

from .common import (
    DETAIL_TENOR_VIEW_LABELS,
    _meaningful_tenor_mask,
    metric_title,
)
from .tables import build_new_trade_detail_table, build_small_table


_DETAIL_LOGGER = logging.getLogger(__name__)


def _compact_tenor_label(
    value: object,
    *,
    max_chars: int = 18,
) -> str:
    """Return bounded visible text without changing the canonical value."""
    text = " ".join(str(value).split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 1].rstrip()}…"


def _wrapped_plotly_label(
    value: object,
    *,
    line_width: int = 24,
    max_lines: int = 3,
) -> str:
    """Return safe Plotly hover HTML with a strict line and length bound."""
    text = " ".join(str(value).split()) or "—"
    lines = wrap(
        text,
        width=line_width,
        break_long_words=True,
        break_on_hyphens=False,
        max_lines=max_lines,
        placeholder="…",
    )
    return "<br>".join(html_escape(line) for line in lines)


def _surface_hover_data(
    pivot: pd.DataFrame,
    metric: str,
) -> list[list[list[str]]]:
    """Build wrapped axis labels and the matrix-formatted value per cell."""
    return [
        [
            [
                _wrapped_plotly_label(swap_tenor),
                _wrapped_plotly_label(option_tenor),
                (
                    ""
                    if pd.isna(pivot.iat[row_number, column_number])
                    else format_number(
                        pivot.iat[row_number, column_number],
                        column=metric,
                    )
                ),
            ]
            for column_number, swap_tenor in enumerate(pivot.columns)
        ]
        for row_number, option_tenor in enumerate(pivot.index)
    ]


def _tenor_surface_pivot(
    detail: pd.DataFrame,
    metric: str,
) -> tuple[pd.DataFrame, bool, bool]:
    """Build an ordered surface pivot from long-form detail rows."""
    surface_columns = ["tenor option", "tenor swap", metric]
    surface_columns.extend(
        column
        for column in ("tenor option order", "tenor swap order")
        if column in detail
    )
    surface = detail[surface_columns].copy()

    for column in ("tenor option", "tenor swap"):
        surface[column] = surface[column].astype("string").str.strip()
        surface = surface.loc[_meaningful_tenor_mask(surface[column])]

    option_tenors, ambiguous_option_order = tenor_axis_order(
        surface,
        "tenor option",
        "tenor option order",
    )
    swap_tenors, ambiguous_swap_order = tenor_axis_order(
        surface,
        "tenor swap",
        "tenor swap order",
    )

    grouped = surface.groupby(
        ["tenor option", "tenor swap"],
        dropna=False,
    )[metric]
    values = (
        grouped.mean()
        if metric in {"move", "open", "current"}
        else grouped.sum(min_count=1)
    )
    pivot = values.unstack("tenor swap").reindex(
        index=reversed(option_tenors),
        columns=swap_tenors,
    )
    return pivot, ambiguous_option_order, ambiguous_swap_order


def build_surface_matrix_table(
    pivot: pd.DataFrame,
    metric: str,
    *,
    metric_label: str | None = None,
    row_axis: str = "Tenor Option",
    column_axis: str = "Tenor Swap",
    wrapper_class: str = "detail-table-wrap tenor-matrix-wrap",
) -> html.Div:
    """Render one heatmap pivot as an accessible HTML matrix.

    The row axis (Tenor Option) is presented in reverse order to match the
    heatmap orientation where the shortest option tenor appears at the top.
    """
    display_metric = metric_label or metric_title(metric)
    # The pivot index is in reversed order (shortest tenor first), but Plotly
    # places the first category at the bottom of the y-axis. The HTML table
    # places the first <tr> at the top, so we reverse again to match the
    # visual heatmap orientation (longest tenor at top).
    option_order = list(reversed(pivot.index))
    ordered_pivot = pivot.loc[option_order]

    headers = [
        html.Th(
            f"{row_axis} / {column_axis}",
            scope="col",
            className="tenor-matrix-corner",
        ),
        *[
            html.Th(
                _compact_tenor_label(label),
                scope="col",
                className="detail-tenor tenor-matrix-column-header",
                title=str(label),
                **{"data-copy-value": str(label)},
            )
            for label in pivot.columns
        ],
    ]

    rows = []
    for row_label, row_values in ordered_pivot.iterrows():
        cells = [
            html.Th(
                _compact_tenor_label(row_label),
                scope="row",
                className="detail-tenor tenor-matrix-row-header",
                title=str(row_label),
                **{"data-copy-value": str(row_label)},
            )
        ]
        for value in row_values:
            if pd.isna(value):
                cells.append(
                    html.Td(
                        "",
                        className=("detail-number tenor-matrix-empty"),
                        **{"data-copy-value": ""},
                    )
                )
                continue

            cells.append(
                html.Td(
                    format_number(value, column=metric),
                    className=(f"detail-number {number_sign_class(value)}"),
                    **{"data-copy-value": str(value)},
                )
            )
        rows.append(html.Tr(cells))

    table = html.Table(
        [
            html.Caption(
                f"{display_metric} tenor matrix",
                className="sr-only",
            ),
            html.Thead(html.Tr(headers)),
            html.Tbody(rows),
        ],
        className="detail-table tenor-matrix-table",
    )
    return html.Div(
        table,
        className=wrapper_class,
        tabIndex=0,
        role="region",
        **{
            "aria-label": (
                f"{display_metric} matrix. Rows are {row_axis}; "
                f"columns are {column_axis}."
            )
        },
    )


def detail_tenor_partitions(detail: pd.DataFrame) -> dict[str, pd.Series]:
    """Return mutually exclusive tenor-shape masks for one detail frame."""
    index = detail.index
    swap_values = detail.get(
        "tenor swap", pd.Series(pd.NA, index=index, dtype="string")
    )
    option_values = detail.get(
        "tenor option", pd.Series(pd.NA, index=index, dtype="string")
    )
    swap = _meaningful_tenor_mask(swap_values).reindex(index, fill_value=False)
    option = _meaningful_tenor_mask(option_values).reindex(index, fill_value=False)
    return {
        "paired": swap & option,
        "swap_only": swap & ~option,
        "option_only": ~swap & option,
        "no_tenor": ~swap & ~option,
    }


def detail_tenor_view_state(
    detail: pd.DataFrame,
    requested_view: str | None,
) -> tuple[list[dict[str, object]], str]:
    """Return fixed dropdown options and a valid requested tenor view."""
    partitions = detail_tenor_partitions(detail)
    available = {
        "auto": True,
        "swap": bool(partitions["paired"].any() or partitions["swap_only"].any()),
        "option": bool(partitions["paired"].any() or partitions["option_only"].any()),
        "surface": bool(partitions["paired"].any()),
    }
    options = [
        {
            "label": label,
            "value": value,
            "disabled": not available[value],
        }
        for value, label in DETAIL_TENOR_VIEW_LABELS.items()
    ]
    requested = str(requested_view or "auto")
    resolved = requested if available.get(requested, False) else "auto"
    return options, resolved


def selected_context_title(context: dict[str, str]) -> str:
    return (
        " · ".join(context[column] for column in ROW_KEY_COLUMNS if column in context)
        or "Total"
    )


def build_line_chart(
    detail: pd.DataFrame,
    group_column: str,
    order_column: str,
    metric: str,
    title: str,
    x_title: str,
) -> dcc.Graph:
    axis_values, ambiguous_order = tenor_axis_order(
        detail,
        group_column,
        order_column,
    )
    if metric in {"move", "open", "current"}:
        market_series = ["move", "open", "current"] if metric == "move" else [metric]
        quote_identity = [
            column for column in ("source type", "underlying") if column in detail
        ]
        if quote_identity:
            by_underlying = detail.groupby(
                [*quote_identity, group_column],
                as_index=False,
                dropna=False,
            )[market_series].mean()
            curve = by_underlying.groupby(
                group_column,
                as_index=False,
                dropna=False,
            )[market_series].mean()
        else:
            curve = detail.groupby(
                group_column,
                as_index=False,
                dropna=False,
            )[market_series].mean()
        curve["_axis_order"] = (
            curve[group_column]
            .astype(str)
            .map({label: rank for rank, label in enumerate(axis_values)})
        )
        curve = curve.sort_values("_axis_order", kind="stable")
        figure = go.Figure()
        market_colors = {"move": "#D88989", "open": "#A8BAC8", "current": "#91C6A1"}
        for column in market_series:
            is_secondary = metric == "move" and column in {"open", "current"}
            if is_secondary:
                # Open and Current are lines on secondary axis
                figure.add_trace(
                    go.Scatter(
                        name=metric_title(column),
                        x=curve[group_column],
                        y=curve[column],
                        mode="lines+markers",
                        line={
                            "color": market_colors[column],
                            "width": 2,
                        },
                        yaxis="y2",
                        hoverlabel={"font": {"size": 10}},
                    )
                )
            else:
                # Move is bar on primary axis
                figure.add_trace(
                    go.Bar(
                        name=metric_title(column),
                        x=curve[group_column],
                        y=curve[column],
                        marker={
                            "color": market_colors[column],
                            "line": {"color": "rgba(0,0,0,0.3)", "width": 1},
                        },
                        opacity=0.7,
                        width=0.8,
                        hoverlabel={"font": {"size": 10}},
                    )
                )
        figure.update_layout(
            title=title,
            xaxis={
                "title": x_title,
                "type": "category",
                "categoryorder": "array",
                "categoryarray": axis_values,
                "tickangle": -30,
                "tickfont": {"size": 10},
            },
            yaxis={"title": metric_title(metric)},
            yaxis2=(
                {
                    "title": "Open / Market Status",
                    "overlaying": "y",
                    "side": "right",
                    "showgrid": False,
                }
                if metric == "move"
                else None
            ),
            legend={"orientation": "h", "y": 1.12},
            template="plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin={"l": 52, "r": 58, "t": 58, "b": 70},
            height=300,
        )
    else:
        series = [metric, *METRIC_BREAKDOWNS.get(metric, [])]
        curve = detail.groupby(group_column, as_index=False)[series].sum(min_count=1)
        curve["_axis_order"] = (
            curve[group_column]
            .astype(str)
            .map({label: rank for rank, label in enumerate(axis_values)})
        )
        curve = curve.sort_values("_axis_order", kind="stable")
        figure = go.Figure()
        colors = {
            metric: (
                "#73A9D8"
                if metric.endswith(" expo")
                else "#D99191"
                if metric.endswith(" hedges")
                else "#4C8A4A"
            )
        }
        colors.update(
            {
                component: color
                for component, color in zip(series[1:], ("#73A9D8", "#D99191"))
            }
        )
        # Total goes on primary axis (y) as bar, breakdowns on secondary (y2) as scatter
        figure.add_trace(
            go.Bar(
                name="Total" if metric in METRIC_BREAKDOWNS else metric_title(metric),
                x=curve[group_column],
                y=curve[metric],
                marker={
                    "color": colors[metric],
                    "line": {"color": "rgba(0,0,0,0.3)", "width": 1},
                },
                opacity=0.7,
                width=0.8,
                hoverlabel={"font": {"size": 10}},
            )
        )
        for component in series[1:]:
            figure.add_trace(
                go.Scatter(
                    name=metric_title(component),
                    x=curve[group_column],
                    y=curve[component],
                    mode="lines+markers",
                    line={"color": colors[component], "width": 2},
                    yaxis="y2",
                    hoverlabel={"font": {"size": 10}},
                )
            )
        figure.update_layout(
            title=title,
            xaxis={
                "title": x_title,
                "type": "category",
                "categoryorder": "array",
                "categoryarray": axis_values,
                "tickangle": -30,
                "tickfont": {"size": 10},
            },
            yaxis={"title": f"{metric_title(metric)} amount"},
            yaxis2={
                "title": "XVA / Hedges amount",
                "overlaying": "y",
                "side": "right",
                "showgrid": False,
            },
            legend={"orientation": "h", "y": 1.12},
            template="plotly_white",
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin={"l": 52, "r": 58, "t": 58, "b": 70},
            height=300,
        )
        if ambiguous_order:
            figure.add_annotation(
                text=(
                    "Selected underlyings use different tenor ranks; "
                    "labels use modal connector order."
                ),
                x=0,
                xref="paper",
                y=-0.24,
                yref="paper",
                showarrow=False,
                align="left",
                font={"size": 10, "color": "#626B75"},
            )
            figure.update_layout(margin={"l": 52, "r": 58, "t": 58, "b": 68})
        return dcc.Graph(
            figure=figure,
            config={"displayModeBar": False},
        )


def build_tenor_heatmap(
    detail: pd.DataFrame, metric: str, title: str = "Swap x option surface"
) -> dcc.Graph:
    """Build a sparse surface from all observed swap and option tenors.

    Neither axis has a fixed size. Missing combinations stay blank instead of
    being manufactured as zero-valued cells.
    """
    pivot, ambiguous_option_order, ambiguous_swap_order = _tenor_surface_pivot(
        detail,
        metric,
    )
    display_metric = metric_title(metric)
    hover_data = _surface_hover_data(pivot, metric)

    # use same colour scheme as market heatmap
    colorscale = [
        [0.0, "#D98282"],
        [0.25, "#F2BA8A"],
        [0.5, "#FFFDF6"],
        [0.75, "#BFE4C7"],
        [1.0, "#79BE89"],
    ]

    # Mirror market heatmap color-bounds logic for "risk"-style metrics
    finite_values = np.asarray(pivot.values, dtype=float)
    finite_values = finite_values[np.isfinite(finite_values)]
    max_abs = float(np.max(np.abs(finite_values))) if finite_values.size else 0.0
    color_bounds: dict[str, float] = {"zmid": 0.0}
    if max_abs > 0:
        color_bounds.update(zmin=-max_abs, zmax=max_abs)

    option_order = list(pivot.index)
    trace = go.Heatmap(
        z=pivot.values,
        x=list(pivot.columns),
        y=option_order,
        customdata=hover_data,
        hoverongaps=False,
        xgap=1,
        ygap=1,
        colorscale=colorscale,
        colorbar={
            "title": {"text": display_metric},
            "thickness": 12,
            "len": 0.78,
            "xpad": 6,
        },
        hovertemplate=(
            "<b>Tenor Swap</b>: %{customdata[0]}<br>"
            "<b>Tenor Option</b>: %{customdata[1]}<br>"
            f"<b>{display_metric}</b>: %{{customdata[2]}}"
            "<extra></extra>"
        ),
        hoverlabel={"font": {"size": 11}},
        **color_bounds,
    )

    figure = go.Figure(data=[trace])
    figure.update_xaxes(
        title={"text": "Tenor Swap", "standoff": 10},
        type="category",
        categoryorder="array",
        categoryarray=list(pivot.columns),
        tickmode="array",
        tickvals=list(pivot.columns),
        ticktext=[_compact_tenor_label(value) for value in pivot.columns],
        side="top",
        ticklabelposition="outside top",
        ticks="outside",
        ticklen=5,
        automargin=True,
        constrain="domain",
    )

    figure.update_yaxes(
        title_text="Tenor Option",
        type="category",
        categoryorder="array",
        categoryarray=list(pivot.index),
        tickmode="array",
        tickvals=list(pivot.index),
        ticktext=[_compact_tenor_label(value) for value in pivot.index],
        automargin=True,
        constrain="domain",
    )

    figure.update_layout(
        autosize=False,
        hovermode="closest",
        hoverlabel={
            "align": "left",
            "font": {"size": 11},
        },
        margin={"l": 58, "r": 46, "t": 90, "b": 44},
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=500,
    )
    if ambiguous_option_order or ambiguous_swap_order:
        figure.add_annotation(
            text=(
                "Selected underlyings use different tenor ranks; "
                "axes use modal connector order."
            ),
            x=0,
            xref="paper",
            y=-0.24,
            yref="paper",
            showarrow=False,
            align="left",
            font={"size": 10, "color": "#626B75"},
        )
        figure.update_layout(margin={"l": 58, "r": 46, "t": 90, "b": 68})
    return dcc.Graph(
        figure=figure,
        responsive=True,
        className="tenor-surface-graph",
        config={"displayModeBar": False, "responsive": True},
    )


def _detail_source_rows(frame: pd.DataFrame) -> int:
    if "rows" not in frame:
        return len(frame)
    values = pd.to_numeric(frame["rows"], errors="coerce").fillna(0)
    return int(values.sum())


def _detail_chart_card(title: str, chart) -> html.Div:
    return html.Div(
        [html.H3(title, className="detail-chart-title"), chart],
        className="detail-chart-card",
    )


def _build_detail_panel_from_frame(
    *,
    scoped: pd.DataFrame,
    detail: pd.DataFrame,
    context: dict[str, str],
    selected_metric: str,
    metric: str,
    tenor_view: str,
    new_trade_details: pd.DataFrame | None = None,
) -> html.Div:
    # Diagnostics: trace tenor view data for debugging
    partitions = detail_tenor_partitions(detail)
    paired = partitions["paired"]
    swap_only = partitions["swap_only"]
    option_only = partitions["option_only"]
    no_tenor = partitions["no_tenor"]
    _DETAIL_LOGGER.debug(
        "_sample tenor_swap=%s paired=%d swap_only=%d option_only=%d no_tenor=%d context=%s metric=%s scoped_rows=%d",
        tenor_view,
        len(detail),
        int(paired.sum()),
        int(swap_only.sum()),
        int(option_only.sum()),
        int(no_tenor.sum()),
        context,
        metric,
        len(scoped),
    )
    if not detail.empty:
        _DETAIL_LOGGER.debug(
            "_sample tenor_swap=%s sample_tenor_option=%s sample_underlying=%s",
            detail["tenor swap"].head(3).tolist()
            if "tenor swap" in detail
            else "MISSING",
            detail["tenor option"].head(3).tolist()
            if "tenor option" in detail
            else "MISSING",
            detail["underlying"].head(3).tolist()
            if "underlying" in detail
            else "MISSING",
        )

    chart_cards: list[html.Div] = []
    displayed_detail = detail
    matrix_detail: pd.DataFrame | None = None

    if tenor_view == "swap":
        included = paired | swap_only
        displayed_detail = detail.loc[included]
        if included.any():
            chart_cards.append(
                _detail_chart_card(
                    "",
                    build_line_chart(
                        displayed_detail,
                        "tenor swap",
                        "tenor swap order",
                        metric,
                        "Tenor Swap line",
                        "Tenor Swap",
                    ),
                )
            )
    elif tenor_view == "option":
        included = paired | option_only
        displayed_detail = detail.loc[included]
        if included.any():
            chart_cards.append(
                _detail_chart_card(
                    "",
                    build_line_chart(
                        displayed_detail,
                        "tenor option",
                        "tenor option order",
                        metric,
                        "Tenor Option line",
                        "Tenor Option",
                    ),
                )
            )
    elif tenor_view == "surface":
        displayed_detail = detail.loc[paired]
        matrix_detail = displayed_detail
        if paired.any():
            chart_cards.append(
                build_tenor_heatmap(
                    displayed_detail, metric, title="Swap x option surface"
                )
            )
    else:
        # Auto uses the mutually exclusive populations. Every detail row therefore
        # appears exactly once across its charts or the no-tenor note.
        _DETAIL_LOGGER.debug(
            "auto path: paired.any()=%s swap_only.any()=%s option_only.any()=%s no_tenor.any()=%s",
            bool(paired.any()),
            bool(swap_only.any()),
            bool(option_only.any()),
            bool(no_tenor.any()),
        )
        if paired.any():
            matrix_detail = detail.loc[paired]
            _DETAIL_LOGGER.debug(
                "building heatmap for paired rows=%d", int(paired.sum())
            )
            chart_cards.append(
                build_tenor_heatmap(
                    detail.loc[paired], metric, title="Swap x option surface"
                )
            )
            _DETAIL_LOGGER.debug("chart_cards length now=%d", len(chart_cards))
        if swap_only.any():
            chart_cards.append(
                _detail_chart_card(
                    "",
                    build_line_chart(
                        detail.loc[swap_only],
                        "tenor swap",
                        "tenor swap order",
                        metric,
                        "",
                        "Tenor Swap",
                    ),
                )
            )
        if option_only.any():
            chart_cards.append(
                _detail_chart_card(
                    "",
                    build_line_chart(
                        detail.loc[option_only],
                        "tenor option",
                        "tenor option order",
                        metric,
                        "",
                        "Tenor Option",
                    ),
                )
            )
        if no_tenor.any():
            chart_cards.append(
                html.Div(
                    f"{_detail_source_rows(detail.loc[no_tenor]):,} source rows "
                    "have no tenor dimension and remain in the table.",
                    className="detail-note detail-chart-card",
                )
            )

    if not chart_cards and not detail.empty:
        chart_cards.append(
            html.Div(
                "This selection has no rows for the chosen tenor view.",
                className="detail-note detail-chart-card",
            )
        )

    total_detail_rows = _detail_source_rows(detail)
    included_detail_rows = _detail_source_rows(displayed_detail)
    coverage = (
        f"{DETAIL_TENOR_VIEW_LABELS[tenor_view]} · "
        f"{included_detail_rows:,} of {total_detail_rows:,} source rows shown"
    )
    if tenor_view != "auto" and included_detail_rows != total_detail_rows:
        coverage += f" · {total_detail_rows - included_detail_rows:,} outside this view"

    title = f"{selected_context_title(context)} — {metric_title(metric)}"
    new_trade_table = (
        build_new_trade_detail_table(new_trade_details, context)
        if new_trade_details is not None
        else None
    )

    # Build matrix table for surface view, otherwise use flat table
    if matrix_detail is not None and not matrix_detail.empty:
        pivot, _ambiguous_option, _ambiguous_swap = _tenor_surface_pivot(
            matrix_detail,
            metric,
        )
        detail_table = build_surface_matrix_table(pivot, metric)
    else:
        detail_table = build_small_table(displayed_detail, metric)

    return html.Div(
        [
            html.Div(
                [
                    html.H2(title),
                    html.Div(
                        f"{len(scoped):,} source rows, opened from {selected_metric}",
                        className="detail-subtitle",
                    ),
                    html.Div(
                        coverage,
                        className="detail-tenor-coverage",
                        **{"aria-live": "polite"},
                    ),
                ],
                className="detail-header",
            ),
            *([new_trade_table] if new_trade_table is not None else []),
            html.Div(
                [
                    html.Div(chart_cards, className="detail-chart detail-chart-stack"),
                    html.Div(
                        detail_table,
                        className="detail-table-wrap",
                    ),
                ],
                className="detail-grid",
            ),
        ],
        className="detail-panel-body",
    )


def build_detail_panel_with_state(
    frame: pd.DataFrame,
    selection: dict[str, str] | None,
    plot_metric: str,
    tenor_view: str | None = "auto",
    *,
    new_trade_details: pd.DataFrame | None = None,
) -> tuple[html.Div, list[dict[str, object]], str]:
    """Build one detail panel and its synchronized tenor-view picker state."""
    if not selection:
        options, resolved_view = detail_tenor_view_state(pd.DataFrame(), "auto")
        return (
            html.Div(
                [
                    html.H2("Tenor detail"),
                    html.P("Select any metric cell to open the tenor table and chart."),
                ],
                className="detail-panel body empty-detail",
            ),
            options,
            resolved_view,
        )

    metric = plot_metric if plot_metric in PLOT_METRICS else "risk"
    selected_metric = selection.get("metric", "risk")
    context = parse_row_key(selection.get("key"))
    scoped = frame_for_context(frame, context)
    detail = detail_frame(frame, context, metric)
    options, resolved_view = detail_tenor_view_state(detail, tenor_view)
    panel = _build_detail_panel_from_frame(
        scoped=scoped,
        detail=detail,
        context=context,
        selected_metric=selected_metric,
        metric=metric,
        tenor_view=resolved_view,
        new_trade_details=new_trade_details,
    )
    return panel, options, resolved_view


__all__ = [
    "build_detail_panel_with_state",
    "build_line_chart",
    "build_surface_matrix_table",
    "build_tenor_heatmap",
    "detail_tenor_partitions",
    "detail_tenor_view_state",
    "selected_context_title",
]
