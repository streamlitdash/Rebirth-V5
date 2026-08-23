"""V4 Quick Market controls, quote-grain results, and lazy history presentation."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from dash import dcc, html

from rebirth.ui.s02_aggregation import tenor_axis_order

from .s05_charts import (
    _compact_tenor_label,
    _surface_hover_data,
    build_surface_matrix_table,
)
from .s01_common import _ABSENT_TENOR_LABELS, _meaningful_tenor_mask
from .s08_quickrisk import _quick_search_number, _quick_search_text

_QUICK_MARKET_HISTORY_PERIOD_LABELS = {
    "wtd": "WTD",
    "mtd": "MTD",
    "ytd": "YTD",
    "all": "All",
    "custom": "Custom",
}
_MARKET_AXIS_ORDER_COLUMNS = {
    "Tenor Swap": "Tenor Swap Order",
    "Tenor Option": "Tenor Option Order",
}
QUICK_MARKET_DEFAULT_INDEX = (
    "Risk Type",
    "Risk Greek",
    "Underlying",
    "Tenor Swap",
    "Tenor Option",
)
_QUICK_MARKET_IDENTITY_COLUMNS = ("Risk Type", "Risk Greek", "Underlying")
_QUICK_MARKET_HISTORY_CELL_COLUMNS = ("Tenor Swap", "Tenor Option")


def build_quick_market_search(*, embedded: bool = False) -> html.Details | html.Div:
    """Build Quick Market as a disclosure or workspace-tab body."""

    disclosure = html.Details(
        [
            html.Summary(
                [
                    html.Span(
                        "Quick Market Search",
                        className="quick-search-pivot-title",
                    ),
                    html.Span(
                        "Full market tenor structure",
                        className="quick-search-pivot-values",
                    ),
                ],
                id="quick-market-summary",
                n_clicks=0,
                className="quick-search-pivot-summary",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.H2("Market curves and surfaces"),
                                    html.P(
                                        "Select Risk Type, Risk Greek and Underlying. "
                                        "This reads the complete saved MarketBook, including tenors with no Risk row."
                                    ),
                                ],
                                className="quick-search-heading-copy",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Market identity",
                                        htmlFor="quick-market-combine-udl",
                                    ),
                                    dcc.Dropdown(
                                        id="quick-market-combine-udl",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        searchable=True,
                                        placeholder="Select Risk Type · Risk Greek · Underlying",
                                        className="quick-search-combine-dropdown",
                                    ),
                                ],
                                className="quick-search-selector-control",
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Open in Data",
                                        id="quick-market-open-data",
                                        n_clicks=0,
                                        disabled=True,
                                        type="button",
                                        className="data-open-button",
                                    ),
                                    html.Span(
                                        "",
                                        id="quick-market-data-status",
                                        className="quick-search-selector-help",
                                        role="status",
                                    ),
                                ],
                                className="quick-search-selector-control data-open-control",
                            ),
                        ],
                        className="quick-search-heading",
                    ),
                    html.Div(
                        [
                            html.Label("Chart", htmlFor="quick-market-view"),
                            dcc.RadioItems(
                                id="quick-market-view",
                                options=[
                                    {"label": "Auto", "value": "auto"},
                                    {"label": "Tenor Swap line", "value": "swap"},
                                    {"label": "Tenor Option line", "value": "option"},
                                    {"label": "Surface", "value": "surface"},
                                ],
                                value="auto",
                                inline=True,
                                className="detail-tenor-view-radio",
                            ),
                        ],
                        className="quick-search-dimension-control",
                    ),
                    html.Div(
                        [
                            html.Label(
                                "Heatmap",
                                htmlFor="quick-market-surface-metric",
                            ),
                            dcc.RadioItems(
                                id="quick-market-surface-metric",
                                options=[
                                    {"label": "Open", "value": "open"},
                                    {
                                        "label": "Market Status",
                                        "value": "current",
                                    },
                                    {"label": "Move", "value": "move"},
                                ],
                                value="current",
                                inline=True,
                                className="detail-tenor-view-radio",
                            ),
                        ],
                        id="quick-market-surface-metric-control",
                        className="quick-search-dimension-control",
                        hidden=True,
                    ),
                    dcc.Loading(
                        html.Div(
                            "Open this section to read the current MarketBook.",
                            id="quick-market-results",
                            className="quick-search-results quick-search-hint",
                        ),
                        type="dot",
                        delay_show=160,
                    ),
                ],
                className="quick-search-pivot-body",
            ),
        ],
        id="quick-market-details",
        open=False,
        className="quick-search-shell quick-search-pivot-details",
        **{"aria-label": "Quick Market Search"},
    )
    if not embedded:
        return disclosure
    return html.Div(
        disclosure.children[1:],
        id=disclosure.id,
        className="quick-search-shell quick-search-tab-body",
        **{"aria-label": "Quick Market Search"},
    )


def _market_axis(frame: pd.DataFrame, column: str) -> bool:
    return column in frame and _meaningful_tenor_mask(frame[column]).any()


def _market_surface_metric_options(
    market_status: str,
) -> list[dict[str, str]]:
    """Label the current quote with the resolver's exact live/OFFICIAL status."""
    return [
        {"label": "Open", "value": "open"},
        {"label": market_status, "value": "current"},
        {"label": "Move", "value": "move"},
    ]


def _ordered_market_axis(frame: pd.DataFrame, column: str) -> list[str]:
    """Return one market axis in its connector-supplied rank order."""

    if column not in _MARKET_AXIS_ORDER_COLUMNS:
        raise ValueError(f"Unsupported market tenor axis: {column}")
    ordered, _ambiguous = tenor_axis_order(
        frame,
        column,
        _MARKET_AXIS_ORDER_COLUMNS[column],
    )
    return ordered


def _sort_market_rows(frame: pd.DataFrame, axes: list[str]) -> pd.DataFrame:
    """Sort a MarketBook view by authoritative ranks without mutating it."""

    if frame.empty or not axes:
        return frame.copy()
    ordered = frame.copy()
    rank_columns: list[str] = []
    for position, axis in enumerate(axes):
        rank_column = f"__cube_market_axis_{position}__"
        axis_order = _ordered_market_axis(ordered, axis)
        ranks = {label: rank for rank, label in enumerate(axis_order)}
        ordered[rank_column] = ordered[axis].astype("string").str.strip().map(ranks)
        # Missing/absent coordinates remain visible after all ranked labels.
        ordered[rank_column] = ordered[rank_column].fillna(len(ranks))
        rank_columns.append(rank_column)
    return ordered.sort_values(rank_columns, kind="stable").drop(columns=rank_columns)


def _quick_market_history_cell_value(
    tenor_swap: object,
    tenor_option: object,
) -> str:
    """Serialize one exact tenor cell without relying on a display delimiter."""

    def coordinate(value: object) -> str | None:
        if pd.isna(value):
            return None
        label = str(value).strip()
        return None if label.casefold() in _ABSENT_TENOR_LABELS else label

    return json.dumps(
        {
            "tenor option": coordinate(tenor_option),
            "tenor swap": coordinate(tenor_swap),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _quick_market_history_cell_label(value: str) -> str:
    cell = json.loads(value)
    swap = cell["tenor swap"]
    option = cell["tenor option"]
    if swap is not None and option is not None:
        return f"Swap {swap} · Option {option}"
    if swap is not None:
        return f"Tenor Swap {swap}"
    if option is not None:
        return f"Tenor Option {option}"
    return "Spot / no tenor"


def quick_market_history_cell_state(
    frame: pd.DataFrame,
    requested_cell: str | None,
) -> tuple[list[dict[str, str]], str | None, bool]:
    """Return exact quote-cell options in connector-owned tenor order.

    A curve or surface must resolve to one quote cell before it can be compared
    through time. The first connector-ranked cell is the deterministic default;
    no values from incompatible tenors are combined.
    """

    if frame.empty:
        return [], None, True
    axes = [
        column
        for column in _QUICK_MARKET_HISTORY_CELL_COLUMNS
        if _market_axis(frame, column)
    ]
    ordered = _sort_market_rows(frame, axes)
    values: list[str] = []
    for record in ordered.to_dict("records"):
        value = _quick_market_history_cell_value(
            record.get("Tenor Swap"),
            record.get("Tenor Option"),
        )
        if value not in values:
            values.append(value)
    options = [
        {"label": _quick_market_history_cell_label(value), "value": value}
        for value in values
    ]
    selected = str(requested_cell or "").strip()
    resolved = selected if selected in values else (values[0] if values else None)
    return options, resolved, len(options) <= 1


def quick_market_history_identity(frame: pd.DataFrame) -> tuple[str, str, str]:
    """Extract one unambiguous raw MarketBook identity from an exact pivot."""

    missing = [
        column for column in _QUICK_MARKET_IDENTITY_COLUMNS if column not in frame
    ]
    if missing:
        raise ValueError(f"Quick Market result is missing identity columns: {missing}")
    identities = frame.loc[:, list(_QUICK_MARKET_IDENTITY_COLUMNS)].drop_duplicates()
    if len(identities) != 1:
        raise ValueError("Quick Market result must contain one exact raw identity")
    row = identities.iloc[0]
    values = tuple(
        str(row[column]).strip() for column in _QUICK_MARKET_IDENTITY_COLUMNS
    )
    if any(not value for value in values):
        raise ValueError("Quick Market raw identity cannot contain blank values")
    return values


def _quick_market_history_cell(frame: pd.DataFrame, selected_cell: str) -> pd.DataFrame:
    """Select one exact tenor cell while treating all absent labels alike."""

    try:
        cell = json.loads(selected_cell)
        requested = {
            "Tenor Swap": cell["tenor swap"],
            "Tenor Option": cell["tenor option"],
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Historical quote selection is invalid") from exc

    keep = pd.Series(True, index=frame.index)
    for column, value in requested.items():
        values = frame.get(column, pd.Series(pd.NA, index=frame.index))
        if value is None:
            keep &= ~_meaningful_tenor_mask(values)
        else:
            keep &= values.astype("string").str.strip().eq(str(value)).fillna(False)
    return frame.loc[keep].copy()


def _quick_market_history_date(value: object, *, label: str) -> pd.Timestamp:
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a valid date") from exc
    if pd.isna(timestamp):
        raise ValueError(f"{label} must be a valid date")
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return timestamp.normalize()


def quick_market_history_date_window(
    period: str | None,
    market_date: object,
    *,
    start_date: object | None = None,
    end_date: object | None = None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None, str]:
    """Resolve one inclusive historical range against the current Market Date."""

    current_date = _quick_market_history_date(market_date, label="Market Date")
    selected_period = str(period or "all").strip().casefold()
    try:
        label = _QUICK_MARKET_HISTORY_PERIOD_LABELS[selected_period]
    except KeyError as exc:
        raise ValueError(
            "Historical period must be WTD, MTD, YTD, All or Custom"
        ) from exc
    if selected_period == "all":
        return None, current_date, label
    if selected_period == "wtd":
        return (
            current_date - pd.Timedelta(days=current_date.weekday()),
            current_date,
            label,
        )
    if selected_period == "mtd":
        return current_date.replace(day=1), current_date, label
    if selected_period == "ytd":
        return current_date.replace(month=1, day=1), current_date, label
    if start_date in (None, "") or end_date in (None, ""):
        return None, None, label
    selected_start = _quick_market_history_date(
        start_date,
        label="Historical start date",
    )
    selected_end = _quick_market_history_date(
        end_date,
        label="Historical end date",
    )
    if selected_start > selected_end:
        raise ValueError("Historical start date must be on or before end date")
    if selected_start > current_date:
        raise ValueError(
            "Historical start date must be on or before the current Market Date"
        )
    return selected_start, min(selected_end, current_date), label


def build_quick_market_history_result(
    history_frame: pd.DataFrame,
    current_frame: pd.DataFrame,
    *,
    selected_cell: str,
    market_date: object,
    market_status: str,
    period: str = "all",
    start_date: object | None = None,
    end_date: object | None = None,
) -> tuple[html.Div | dcc.Graph, str]:
    """Plot daily Current values for one quote cell plus the live current point."""

    window_start, window_end, period_label = quick_market_history_date_window(
        period,
        market_date,
        start_date=start_date,
        end_date=end_date,
    )
    if str(period or "all").strip().casefold() == "custom" and (
        window_start is None or window_end is None
    ):
        message = "Choose both custom dates to plot this exact quote cell."
        return html.Div(message, className="quick-search-hint"), message

    required = {"Market Date", "Current"}
    missing = sorted(required - set(history_frame.columns))
    if missing and not history_frame.empty:
        raise ValueError(f"Market history is missing required columns: {missing}")

    if history_frame.empty:
        historical = pd.DataFrame(columns=["Market Date", "Current"])
    else:
        historical = _quick_market_history_cell(history_frame, selected_cell)
    current = _quick_market_history_cell(current_frame, selected_cell)
    if len(current) != 1:
        raise ValueError("Historical chart requires one current quote per tenor cell")

    points = historical.loc[:, ["Market Date", "Current"]].copy()
    points["Market Date"] = pd.to_datetime(points["Market Date"], errors="coerce")
    points["Current"] = pd.to_numeric(points["Current"], errors="coerce")
    points = points.dropna(subset=["Market Date", "Current"])

    current_date = _quick_market_history_date(market_date, label="Market Date")
    current_value = pd.to_numeric(
        pd.Series([current.iloc[0]["Current"]]), errors="coerce"
    ).iloc[0]
    current_available = bool(pd.notna(current_value))
    # The committed in-memory MarketBook owns its date even when that quote is
    # unavailable. Never fall back to an archived value for the current date.
    points = points.loc[points["Market Date"].dt.normalize().ne(current_date)]
    duplicate_dates = points["Market Date"].dt.normalize().duplicated(keep=False)
    if duplicate_dates.any():
        dates = sorted(
            points.loc[duplicate_dates, "Market Date"]
            .dt.date.astype(str)
            .unique()
            .tolist()
        )
        raise ValueError(
            "Market history contains duplicate quote cells for dates "
            + ", ".join(dates[:5])
        )
    if window_start is not None:
        points = points.loc[points["Market Date"].dt.normalize().ge(window_start)]
    if window_end is not None:
        points = points.loc[points["Market Date"].dt.normalize().le(window_end)]
    current_in_window = bool(
        (window_start is None or current_date >= window_start)
        and (window_end is None or current_date <= window_end)
    )
    current_included = current_available and current_in_window
    if current_included:
        points = pd.concat(
            [
                points,
                pd.DataFrame(
                    {"Market Date": [current_date], "Current": [current_value]}
                ),
            ],
            ignore_index=True,
        )

    points = points.sort_values("Market Date", kind="stable")
    if points.empty:
        return (
            html.Div(
                "No historical observations or current quote are available for this cell.",
                className="quick-search-empty",
            ),
            "No daily observations are available for the selected quote cell.",
        )

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            name="Current market",
            x=points["Market Date"],
            y=points["Current"],
            mode="lines+markers",
            line={"color": "#79BE89", "width": 3},
            marker={"size": 7},
            hovertemplate=("<b>%{x|%Y-%m-%d}</b><br>Current: %{y:,.6g}<extra></extra>"),
        )
    )
    if current_included:
        figure.add_trace(
            go.Scatter(
                name=f"Today · {market_status}",
                x=[current_date],
                y=[current_value],
                mode="markers",
                marker={
                    "color": "#111111",
                    "size": 10,
                    "line": {"color": "#79BE89", "width": 2},
                },
                hovertemplate=(
                    f"<b>{current_date.date().isoformat()} · {market_status}</b>"
                    "<br>Current: %{y:,.6g}<extra></extra>"
                ),
            )
        )
    figure.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=300,
        margin={"l": 54, "r": 24, "t": 30, "b": 52},
        legend={"orientation": "h", "y": 1.12},
        xaxis={"title": "Market Date", "type": "date"},
        yaxis={"title": "Current"},
        hovermode="x unified",
    )
    observation_count = len(points) - int(current_included)
    if current_included:
        current_status = f" · today's {market_status} point included"
    elif not current_in_window:
        current_status = f" · today's {market_status} point is outside the date range"
    else:
        current_status = f" · today's {market_status} quote is unavailable"
    status = (
        f"{period_label} · {_quick_market_history_cell_label(selected_cell)} · "
        f"{observation_count:,} archived daily observation"
        f"{'s' if observation_count != 1 else ''}{current_status}"
    )
    return (
        dcc.Graph(
            figure=figure,
            responsive=True,
            config={"displayModeBar": False, "responsive": True},
        ),
        status,
    )


def _market_line_chart(
    frame: pd.DataFrame,
    *,
    axis: str,
    market_status: str,
) -> dcc.Graph:
    curve = frame.loc[_meaningful_tenor_mask(frame[axis])].copy()
    axis_order = _ordered_market_axis(curve, axis)
    curve = curve.groupby(axis, as_index=False, sort=False)[["Open", "Current"]].mean()
    # Keep the chart aligned with the paired-quote aggregation contract used by
    # Quick Market: Move is always the displayed Current quote minus Open.
    curve["Move"] = curve["Current"] - curve["Open"]
    curve[axis] = curve[axis].astype(str)
    curve["__cube_market_axis_order__"] = curve[axis].map(
        {label: rank for rank, label in enumerate(axis_order)}
    )
    curve = curve.sort_values("__cube_market_axis_order__", kind="stable").drop(
        columns="__cube_market_axis_order__"
    )
    figure = make_subplots(specs=[[{"secondary_y": True}]])
    # Add bar chart first so it renders behind the line traces
    figure.add_trace(
        go.Bar(
            name="Market Move",
            x=curve[axis],
            y=curve["Move"],
            marker_color="#D88989",
            marker_line_color="rgba(0,0,0,0.3)",
            marker_line_width=1,
            opacity=0.4,
            hoverlabel={"font": {"size": 10}},
        ),
        secondary_y=True,
    )
    # Add line traces on top
    figure.add_trace(
        go.Scatter(
            name="Open",
            x=curve[axis],
            y=curve["Open"],
            mode="lines+markers",
            line={"color": "#7FAD7F", "width": 3},
            hoverlabel={"font": {"size": 10}},
        ),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            name=market_status,
            x=curve[axis],
            y=curve["Current"],
            mode="lines+markers",
            line={"color": "#79BE89", "width": 3},
            hoverlabel={"font": {"size": 10}},
        ),
        secondary_y=False,
    )
    figure.update_layout(
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=300,
        margin={"l": 54, "r": 60, "t": 30, "b": 52},
        legend={"orientation": "h", "y": 1.12},
        xaxis={
            "title": axis,
            "type": "category",
            "categoryorder": "array",
            "categoryarray": axis_order,
        },
        yaxis={"title": f"Open / {market_status}"},
        yaxis2={
            "title": "Market Move",
            "overlaying": "y",
            "side": "right",
            "showgrid": False,
        },
        uniformtext={"mode": "hide", "minsize": 10},
    )
    return dcc.Graph(figure=figure, config={"displayModeBar": False})


def _market_surface_chart(
    frame: pd.DataFrame,
    *,
    market_status: str,
    metric: str,
) -> tuple[dcc.Graph, pd.DataFrame, str, str]:
    """Build the Quick Market surface heatmap and return its pivot matrix."""
    surface = frame.loc[
        _meaningful_tenor_mask(frame["Tenor Swap"])
        & _meaningful_tenor_mask(frame["Tenor Option"])
    ].copy()
    surface["Move"] = surface["Current"] - surface["Open"]
    swap = _ordered_market_axis(surface, "Tenor Swap")
    option_ordered = _ordered_market_axis(surface, "Tenor Option")
    option_reversed = list(reversed(option_ordered))
    metric_settings = {
        "open": (
            "Open",
            "Open",
            [[0.0, "#F7FBFF"], [1.0, "#9CC7EB"]],
        ),
        "current": (
            "Current",
            market_status,
            [[0.0, "#F4FBF5"], [1.0, "#9ED5AA"]],
        ),
        "move": (
            "Move",
            "Move",
            [
                [0.0, "#D98282"],
                [0.25, "#F2BABA"],
                [0.5, "#FFFDF6"],
                [0.75, "#BFE4C7"],
                [1.0, "#79BE89"],
            ],
        ),
    }
    selected_metric = str(metric or "current").casefold()
    if selected_metric not in metric_settings:
        selected_metric = "current"
    column, label, colors = metric_settings[selected_metric]
    values = surface.pivot_table(
        index="Tenor Option",
        columns="Tenor Swap",
        values=column,
        aggfunc="mean",
        sort=False,
    ).reindex(index=option_reversed, columns=swap)
    color_bounds: dict[str, float] = {}
    if selected_metric == "move":
        finite_values = np.asarray(values.values, dtype=float)
        finite_values = finite_values[np.isfinite(finite_values)]
        max_abs = float(np.max(np.abs(finite_values))) if finite_values.size else 0.0
        color_bounds["zmid"] = 0.0
        if max_abs > 0:
            color_bounds.update(zmin=-max_abs, zmax=max_abs)

    hover_data = _surface_hover_data(values, column.casefold())
    trace = go.Heatmap(
        z=values.values,
        x=swap,
        y=option_reversed,
        customdata=hover_data,
        colorscale=colors,
        hoverongaps=False,
        xgap=1,
        ygap=1,
        colorbar={
            "title": {"text": label},
            "thickness": 12,
            "len": 0.78,
            "xpad": 6,
        },
        hovertemplate=(
            "<b>Tenor Swap</b>: %{customdata[0]}<br>"
            "<b>Tenor Option</b>: %{customdata[1]}<br>"
            f"<b>{label}</b>: %{{customdata[2]}}"
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
        categoryarray=list(values.columns),
        tickmode="array",
        tickvals=list(values.columns),
        ticktext=[_compact_tenor_label(value) for value in values.columns],
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
        categoryarray=option_reversed,
        tickmode="array",
        tickvals=option_reversed,
        ticktext=[_compact_tenor_label(value) for value in option_reversed],
        automargin=True,
        constrain="domain",
    )
    figure.update_layout(
        autosize=True,
        hovermode="closest",
        hoverlabel={
            "align": "left",
            "font": {"size": 11},
        },
        margin={"l": 58, "r": 46, "t": 90, "b": 44},
        template="plotly_white",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )

    graph = dcc.Graph(
        figure=figure,
        responsive=True,
        className="tenor-surface-graph",
        config={
            "displayModeBar": False,
            "responsive": True,
        },
        style={"height": "800px"},
    )
    return (
        graph,
        values,
        column.casefold(),
        label,
    )


def build_quick_market_result(
    frame: pd.DataFrame,
    *,
    combine_udl: str,
    requested_view: str,
    surface_metric: str,
    market_status: str,
    revision: int,
) -> tuple[
    html.Div,
    str,
    list[dict[str, object]],
    list[dict[str, str]],
]:
    """Render a full-market table and status-aware curve/surface."""

    if frame.empty:
        return (
            html.Div(
                f"No MarketBook rows match '{combine_udl}'.",
                className="quick-search-empty",
            ),
            "auto",
            [{"label": "Auto", "value": "auto"}],
            _market_surface_metric_options(market_status),
        )

    available = {
        "swap": _market_axis(frame, "Tenor Swap"),
        "option": _market_axis(frame, "Tenor Option"),
    }
    available["surface"] = available["swap"] and available["option"]
    automatic = (
        "surface"
        if available["surface"]
        else "swap"
        if available["swap"]
        else "option"
        if available["option"]
        else "auto"
    )
    selected = requested_view if available.get(requested_view, False) else automatic
    labels = {
        "auto": "Auto",
        "swap": "Tenor Swap line",
        "option": "Tenor Option line",
        "surface": "Surface",
    }
    options = [
        {
            "label": label,
            "value": value,
            "disabled": value != "auto" and not available.get(value, False),
        }
        for value, label in labels.items()
    ]

    chart = None
    matrix = None
    matrix_metric = None
    matrix_label = None
    if selected == "surface":
        chart, matrix, matrix_metric, matrix_label = _market_surface_chart(
            frame,
            market_status=market_status,
            metric=surface_metric,
        )
        table = html.Div(
            build_surface_matrix_table(
                matrix,
                matrix_metric,
                metric_label=matrix_label,
                wrapper_class=(
                    "risk-table-wrap quick-search-pivot-table-wrap tenor-matrix-wrap"
                ),
            ),
            className="tenor-surface-pair",
        )
    elif selected in {"swap", "option"}:
        axis = {
            "swap": "Tenor Swap",
            "option": "Tenor Option",
        }[selected]
        chart = _market_line_chart(frame, axis=axis, market_status=market_status)
        axes = [
            column
            for column in ("Tenor Swap", "Tenor Option")
            if _market_axis(frame, column)
        ]
        display_frame = _sort_market_rows(frame, axes)
        columns = [*axes, "Open", "Current", "Move"]
        header = [
            html.Th(
                market_status if column == "Current" else column,
                className="index-header" if column in axes else "metric-header",
            )
            for column in columns
        ]
        body = []
        for record in display_frame.to_dict("records"):
            cells = []
            for column in columns:
                value = record.get(column)
                if column in {"Open", "Current", "Move"}:
                    text, sign = _quick_search_number(value, column=column)
                    cells.append(
                        html.Td(
                            text,
                            className=f"metric-cell {sign}",
                            **{"data-copy-value": "" if pd.isna(value) else str(value)},
                        )
                    )
                else:
                    cells.append(
                        html.Th(
                            _quick_search_text(value),
                            scope="row",
                            className="index-cell",
                            **{
                                "data-copy-value": _quick_search_text(
                                    value, fallback=""
                                )
                            },
                        )
                    )
            body.append(html.Tr(cells))
        table = html.Div(
            html.Table(
                [html.Thead(html.Tr(header)), html.Tbody(body)],
                className="cell-selection-table quick-search-pivot-table",
            ),
            className="risk-table-wrap quick-search-pivot-table-wrap",
            tabIndex=0,
        )
    else:
        axes = [
            column
            for column in ("Tenor Swap", "Tenor Option")
            if _market_axis(frame, column)
        ]
        display_frame = _sort_market_rows(frame, axes)
        columns = [*axes, "Open", "Current", "Move"]
        header = [
            html.Th(
                market_status if column == "Current" else column,
                className="index-header" if column in axes else "metric-header",
            )
            for column in columns
        ]
        body = []
        for record in display_frame.to_dict("records"):
            cells = []
            for column in columns:
                value = record.get(column)
                if column in {"Open", "Current", "Move"}:
                    text, sign = _quick_search_number(value, column=column)
                    cells.append(
                        html.Td(
                            text,
                            className=f"metric-cell {sign}",
                            **{"data-copy-value": "" if pd.isna(value) else str(value)},
                        )
                    )
                else:
                    cells.append(
                        html.Th(
                            _quick_search_text(value),
                            scope="row",
                            className="index-cell",
                            **{
                                "data-copy-value": _quick_search_text(
                                    value, fallback=""
                                )
                            },
                        )
                    )
            body.append(html.Tr(cells))
        table = html.Div(
            html.Table(
                [html.Thead(html.Tr(header)), html.Tbody(body)],
                className="cell-selection-table quick-search-pivot-table",
            ),
            className="risk-table-wrap quick-search-pivot-table-wrap",
            tabIndex=0,
        )

    result = html.Div(
        [
            html.Div(
                f"{len(frame):,} full-market rows · {market_status} · snapshot {revision}",
                className="quick-search-result-count",
            ),
            *([chart] if chart is not None else []),
            table,
        ],
        className="quick-search-result-set",
    )
    return (
        result,
        selected,
        options,
        _market_surface_metric_options(market_status),
    )


__all__ = [
    "QUICK_MARKET_DEFAULT_INDEX",
    "build_quick_market_history_result",
    "build_quick_market_result",
    "build_quick_market_search",
    "quick_market_history_cell_state",
    "quick_market_history_date_window",
    "quick_market_history_identity",
]
