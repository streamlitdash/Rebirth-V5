"""Lazy V4 historical P&L disclosure and chart callbacks."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from threading import RLock

import pandas as pd
from dash import ALL, Dash, Input, Output, State, ctx, html, no_update

from rebirth.history import (
    PL_HISTORY_MAX_RAW_ROWS,
    PLHistoryHierarchyResult,
    PLHistoryRowsResult,
    PLHistorySeriesResult,
)
from rebirth.domain.pnl import (
    COLOSSUS_TYPE,
    HISTORY_IDENTITY_COLUMNS,
    HISTORY_MAPPING_STATUS,
    HISTORY_TYPE,
    MARKET_DATE,
    PL,
    PL_HISTORY_COLUMNS,
    PLSendValidationError,
    PREDICT_TYPE,
    load_pl_history,
    pl_history_period_bounds,
    select_pl_history_series as select_history_series,
    validate_pl_history_frame,
)
from rebirth.domain.schema import UNMAPPED_VALUE

from .common import (
    PL_FILTER_EXCLUDE_ID,
    PL_FILTER_FIELDS,
    PL_FILTER_IDS,
    PLHistoryQueryProtocol,
    PLSendConfig,
    apply_pl_filters,
    pl_external_filter_map,
)
from .history import (
    PL_HISTORY_METRIC_CELL_TYPE,
    PL_HISTORY_PERIOD_HEADER_TYPE,
    PL_HISTORY_ROW_TOGGLE_TYPE,
    build_pl_history_figure,
    build_pl_history_table_from_summary,
    build_pl_history_table_with_state,
    pl_history_path_from_token,
    toggle_pl_history_expanded_periods,
    toggle_pl_history_open_tokens,
)


def register_pl_history_callbacks(app: Dash, config: PLSendConfig) -> None:
    """Register the independently lazy historical disclosure and chart."""
    history_cache_lock = RLock()
    history_cache: pd.DataFrame | None = None
    query_source = (
        config.history_source
        if isinstance(config.history_source, PLHistoryQueryProtocol)
        else None
    )

    @app.callback(
        Output("pnl-current-workspace", "style"),
        Output("pnl-history-workspace", "style"),
        Input("pnl-workspace-tabs", "value"),
    )
    def switch_pl_workspace(value):
        """Switch mounted workspaces without starting historical I/O."""

        history_selected = value == "history"
        return (
            {"display": "none"} if history_selected else {},
            {} if history_selected else {"display": "none"},
        )

    def current_pl_history(*, reload: bool = False) -> pd.DataFrame:
        """Load history once per disclosure, then reuse it for cell/range clicks."""
        nonlocal history_cache
        if not reload:
            with history_cache_lock:
                if history_cache is not None:
                    return history_cache
        try:
            source = config.history_source
            loaded = (
                validate_pl_history_frame(source())
                if callable(source)
                else load_pl_history(source)
            )
        except (PLSendValidationError, TypeError):
            if reload:
                with history_cache_lock:
                    history_cache = None
            raise
        with history_cache_lock:
            history_cache = loaded
            return history_cache

    @app.callback(
        Output("pl-history-grid", "children"),
        Output("pl-history-status", "children"),
        Output("pl-history-date-range", "min_date_allowed"),
        Output("pl-history-date-range", "max_date_allowed"),
        Output("pl-history-open-paths", "data"),
        Output("pl-history-open-comparisons", "data"),
        Output("pl-history-selection-store", "data"),
        Input("pnl-workspace-tabs", "value"),
        Input("clear-cache-complete-store", "data"),
        Input({"type": PL_HISTORY_ROW_TOGGLE_TYPE, "path": ALL}, "n_clicks"),
        Input(
            {"type": PL_HISTORY_PERIOD_HEADER_TYPE, "period": ALL},
            "n_clicks",
        ),
        Input(
            {
                "type": PL_HISTORY_METRIC_CELL_TYPE,
                "path": ALL,
                "period": ALL,
                "series": ALL,
            },
            "n_clicks",
        ),
        *[Input(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        Input(PL_FILTER_EXCLUDE_ID, "value"),
        State("pl-history-open-paths", "data"),
        State("pl-history-open-comparisons", "data"),
        State("pl-history-selection-store", "data"),
        prevent_initial_call=True,
    )
    def render_historical_pl_hierarchy(
        workspace,
        _clear_cache_generation,
        _row_clicks,
        _period_header_clicks,
        _metric_clicks,
        activity_filter,
        signoff_filter,
        portfolio_filter,
        category_filter,
        subcategory_filter,
        exclude_filter,
        open_path_tokens,
        open_comparison_tokens,
        selection_state,
    ):
        """Load and lazily render one expandable Colossus/Predict hierarchy."""
        nonlocal history_cache
        try:
            trigger = ctx.triggered_id
        except Exception:
            trigger = None

        def has_click(values: object) -> bool:
            return isinstance(values, Sequence) and any(
                isinstance(value, int) and not isinstance(value, bool) and value > 0
                for value in values
            )

        if trigger == "clear-cache-complete-store":
            if query_source is not None:
                query_source.clear()
            with history_cache_lock:
                history_cache = None
            return (no_update,) * 7
        if workspace != "history":
            return (no_update,) * 7
        if config.history_source is None:
            return (
                html.Div(
                    "No historical P&L source is configured.",
                    className="static-data-empty",
                ),
                "No historical P&L source is configured.",
                None,
                None,
                [],
                [],
                {},
            )
        page_filters = pl_external_filter_map(
            [
                activity_filter,
                signoff_filter,
                portfolio_filter,
                category_filter,
                subcategory_filter,
            ]
        )
        next_open = open_path_tokens
        next_comparisons = open_comparison_tokens
        next_selection = dict(selection_state or {})
        if isinstance(trigger, str) and trigger in {
            *PL_FILTER_IDS.values(),
            PL_FILTER_EXCLUDE_ID,
        }:
            next_open = []
            next_comparisons = []
            next_selection = {"path": []}
        elif (
            has_click(_row_clicks)
            and isinstance(trigger, dict)
            and trigger.get("type") == PL_HISTORY_ROW_TOGGLE_TYPE
        ):
            next_open = toggle_pl_history_open_tokens(
                open_path_tokens,
                trigger.get("path"),
            )
        elif (
            has_click(_period_header_clicks)
            and isinstance(trigger, dict)
            and trigger.get("type") == PL_HISTORY_PERIOD_HEADER_TYPE
        ):
            next_comparisons = toggle_pl_history_expanded_periods(
                open_comparison_tokens,
                trigger.get("period"),
            )
        elif (
            has_click(_metric_clicks)
            and isinstance(trigger, dict)
            and trigger.get("type") == PL_HISTORY_METRIC_CELL_TYPE
        ):
            path = pl_history_path_from_token(trigger.get("path"))
            if path is not None:
                next_selection = {
                    "path": list(path),
                    "period": str(trigger.get("period", "")),
                }
        elif not next_selection:
            next_selection = {"path": []}

        exclude_selected = "exclude" in (exclude_filter or [])
        try:
            if query_source is not None:
                decoded_paths = [
                    path
                    for token in (next_open or [])
                    if (path := pl_history_path_from_token(token)) is not None
                ]
                result = query_source.hierarchy(
                    open_paths=decoded_paths,
                    filters=page_filters,
                    exclude_selected=exclude_selected,
                )
                if not isinstance(result, PLHistoryHierarchyResult):
                    raise TypeError(
                        "bounded P&L history source returned an invalid hierarchy"
                    )
                table, effective_open, effective_comparisons, effective_selection = (
                    build_pl_history_table_from_summary(
                        result.summary,
                        open_path_tokens=next_open,
                        open_comparison_tokens=next_comparisons,
                        selection=next_selection,
                    )
                )
                row_count = result.row_count
                date_count = result.date_count
                minimum_date = result.minimum_date
                maximum_date = result.maximum_date
                unmapped = result.unmapped_rows
            else:
                history = current_pl_history(reload=trigger == "pnl-workspace-tabs")
                history = apply_pl_filters(
                    history,
                    page_filters,
                    exclude_selected=exclude_selected,
                )
                table, effective_open, effective_comparisons, effective_selection = (
                    build_pl_history_table_with_state(
                        history,
                        open_path_tokens=next_open,
                        open_comparison_tokens=next_comparisons,
                        selection=next_selection,
                    )
                )
                dates = sorted(history[MARKET_DATE].astype(str).unique())
                row_count = len(history)
                date_count = len(dates)
                minimum_date = dates[0] if dates else None
                maximum_date = dates[-1] if dates else None
                unmapped = int(history[HISTORY_MAPPING_STATUS].eq(UNMAPPED_VALUE).sum())
        except (PLSendValidationError, TypeError, ValueError) as exc:
            message = f"Historical P&L could not be loaded: {exc}"
            return (
                html.Div(message, className="static-data-empty"),
                message,
                None,
                None,
                [],
                [],
                {},
            )
        if not row_count or minimum_date is None or maximum_date is None:
            return (
                table,
                "No Colossus/Predict P&L history matches the page filters.",
                None,
                None,
                effective_open,
                effective_comparisons,
                effective_selection,
            )
        status = (
            f"Colossus / Predict · {row_count:,} filtered rows across "
            f"{date_count:,} daily partitions · {minimum_date} to {maximum_date}. "
            "Expand only the branches you need"
        )
        if unmapped:
            status += f" · {unmapped:,} explicit Unmapped rows"
        status += "."
        return (
            table,
            status,
            minimum_date,
            maximum_date,
            effective_open,
            effective_comparisons,
            effective_selection,
        )

    @app.callback(
        Output("pl-history-chart", "figure"),
        Output("pl-history-range-store", "data"),
        Output("pl-history-plot-status", "children"),
        Output("pl-history-range-wtd", "className"),
        Output("pl-history-range-mtd", "className"),
        Output("pl-history-range-ytd", "className"),
        Output("pl-history-range-all", "className"),
        Output("pl-history-date-range", "start_date"),
        Output("pl-history-date-range", "end_date"),
        Output("pl-history-observations-table", "data"),
        Output("pl-history-raw-table", "data"),
        Output("pl-history-raw-status", "children"),
        Input("pnl-workspace-tabs", "value"),
        Input("pl-history-selection-store", "data"),
        Input("pl-history-series-selector", "value"),
        *[Input(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        Input(PL_FILTER_EXCLUDE_ID, "value"),
        Input("pl-history-range-wtd", "n_clicks"),
        Input("pl-history-range-mtd", "n_clicks"),
        Input("pl-history-range-ytd", "n_clicks"),
        Input("pl-history-range-all", "n_clicks"),
        Input("pl-history-date-range", "start_date"),
        Input("pl-history-date-range", "end_date"),
        Input("pl-history-raw-details", "open"),
        State("pl-history-range-store", "data"),
        prevent_initial_call=True,
    )
    def render_historical_pl_chart(
        workspace,
        selection_state,
        series_choice,
        activity_filter,
        signoff_filter,
        portfolio_filter,
        category_filter,
        subcategory_filter,
        exclude_filter,
        _wtd_clicks,
        _mtd_clicks,
        _ytd_clicks,
        _all_clicks,
        explicit_start,
        explicit_end,
        raw_open,
        range_state,
    ):
        """Plot observed Colossus/Predict rows for the selected hierarchy scope."""
        if workspace != "history":
            return (no_update,) * 12
        empty_figure = build_pl_history_figure(pd.DataFrame(), path=())
        if config.history_source is None or not isinstance(selection_state, Mapping):
            classes = ["pl-history-range-button"] * 4
            classes[-1] += " is-active"
            return (
                empty_figure,
                {"preset": "all"},
                "Select a P&L hierarchy cell to plot its observed daily series.",
                *classes,
                None,
                None,
                [],
                [],
                "Raw rows load with the selected historical chart scope.",
            )
        raw_path = selection_state.get("path")
        if not isinstance(raw_path, list):
            raw_path = []
        path = tuple(str(value) for value in raw_path)
        choice_types = {
            "colossus": (COLOSSUS_TYPE,),
            "predict": (PREDICT_TYPE,),
            "both": (COLOSSUS_TYPE, PREDICT_TYPE),
        }
        selected_types = choice_types.get(str(series_choice), choice_types["both"])
        try:
            trigger = ctx.triggered_id
        except Exception:
            trigger = None
        preset_by_button = {
            "pl-history-range-wtd": "wtd",
            "pl-history-range-mtd": "mtd",
            "pl-history-range-ytd": "ytd",
            "pl-history-range-all": "all",
        }
        prior_range = dict(range_state or {})
        preset = str(prior_range.get("preset", "all"))
        start_date = prior_range.get("start_date")
        end_date = prior_range.get("end_date")
        if trigger in preset_by_button:
            preset = preset_by_button[str(trigger)]
            start_date = None
            end_date = None
        elif trigger == "pl-history-date-range" and (
            explicit_start != prior_range.get("start_date")
            or explicit_end != prior_range.get("end_date")
        ):
            preset = "custom" if explicit_start or explicit_end else "all"
            start_date = explicit_start
            end_date = explicit_end
        if preset not in {"wtd", "mtd", "ytd", "all", "custom"}:
            preset = "all"

        page_filters = pl_external_filter_map(
            [
                activity_filter,
                signoff_filter,
                portfolio_filter,
                category_filter,
                subcategory_filter,
            ]
        )
        exclude_selected = "exclude" in (exclude_filter or [])
        raw_result: PLHistoryRowsResult | None = None
        try:
            if query_source is not None:
                result = query_source.series(
                    path=path,
                    history_types=selected_types,
                    preset=preset,
                    start_date=start_date,
                    end_date=end_date,
                    filters=page_filters,
                    exclude_selected=exclude_selected,
                )
                if not isinstance(result, PLHistorySeriesResult):
                    raise TypeError(
                        "bounded P&L history source returned an invalid series"
                    )
                visible = result.series
                resolved_start = result.resolved_start
                resolved_end = result.resolved_end
                raw_result = (
                    query_source.raw_rows(
                        path=path,
                        history_types=selected_types,
                        preset=preset,
                        start_date=start_date,
                        end_date=end_date,
                        filters=page_filters,
                        exclude_selected=exclude_selected,
                        limit=PL_HISTORY_MAX_RAW_ROWS,
                    )
                    if raw_open and callable(getattr(query_source, "raw_rows", None))
                    else None
                )
                if raw_result is not None and not isinstance(
                    raw_result, PLHistoryRowsResult
                ):
                    raise TypeError(
                        "bounded P&L history source returned invalid raw rows"
                    )
            else:
                history = apply_pl_filters(
                    current_pl_history(),
                    page_filters,
                    exclude_selected=exclude_selected,
                )
                if history.empty:
                    resolved_start = None
                    resolved_end = None
                    visible = pd.DataFrame(columns=[MARKET_DATE, HISTORY_TYPE, "PL"])
                else:
                    series = select_history_series(history, path).loc[
                        lambda frame: frame[HISTORY_TYPE].isin(selected_types)
                    ]
                    global_dates = pd.to_datetime(history[MARKET_DATE], errors="raise")
                    global_minimum = global_dates.min().normalize()
                    global_maximum = global_dates.max().normalize()
                    period_bounds = pl_history_period_bounds(global_maximum)
                    if preset in {"wtd", "mtd", "ytd"}:
                        start, end = period_bounds[preset.upper()]
                    elif preset == "custom":
                        start = (
                            pd.Timestamp(start_date).normalize()
                            if start_date
                            else global_minimum
                        )
                        end = (
                            pd.Timestamp(end_date).normalize()
                            if end_date
                            else global_maximum
                        )
                        start = min(max(start, global_minimum), global_maximum)
                        end = min(max(end, global_minimum), global_maximum)
                        if start > end:
                            start, end = end, start
                    else:
                        start, end = global_minimum, global_maximum
                        preset = "all"
                    resolved_start = pd.Timestamp(start).date().isoformat()
                    resolved_end = pd.Timestamp(end).date().isoformat()
                    visible = series.loc[
                        series[MARKET_DATE]
                        .astype(str)
                        .between(resolved_start, resolved_end, inclusive="both")
                    ]
                    if raw_open:
                        raw_scope = history
                        for column, value in zip(
                            HISTORY_IDENTITY_COLUMNS[: len(path)], path, strict=True
                        ):
                            raw_scope = raw_scope.loc[raw_scope[column].eq(value)]
                        raw_scope = raw_scope.loc[
                            raw_scope[HISTORY_TYPE].isin(selected_types)
                            & raw_scope[MARKET_DATE]
                            .astype(str)
                            .between(resolved_start, resolved_end, inclusive="both")
                        ].sort_values(
                            [MARKET_DATE, HISTORY_TYPE, *HISTORY_IDENTITY_COLUMNS],
                            ascending=[
                                False,
                                True,
                                *([True] * len(HISTORY_IDENTITY_COLUMNS)),
                            ],
                            kind="stable",
                        )
                        raw_result = PLHistoryRowsResult(
                            raw_scope.loc[:, list(PL_HISTORY_COLUMNS)].head(
                                PL_HISTORY_MAX_RAW_ROWS
                            ),
                            len(raw_scope),
                            (
                                None
                                if raw_scope.empty
                                else float(raw_scope[PL].sum(min_count=1))
                            ),
                            resolved_start,
                            resolved_end,
                        )
        except (PLSendValidationError, TypeError, ValueError) as exc:
            classes = ["pl-history-range-button"] * 4
            return (
                empty_figure,
                dict(range_state or {}),
                f"Historical P&L could not be loaded: {exc}",
                *classes,
                explicit_start,
                explicit_end,
                [],
                [],
                f"Raw historical rows could not be loaded: {exc}",
            )
        if resolved_start is None or resolved_end is None:
            classes = ["pl-history-range-button"] * 4
            classes[-1] += " is-active"
            return (
                empty_figure,
                {"preset": "all"},
                "No Colossus/Predict P&L history matches the page filters.",
                *classes,
                None,
                None,
                [],
                [],
                "No raw historical rows match the page filters.",
            )

        resolved_range = {
            "preset": preset,
            "start_date": resolved_start,
            "end_date": resolved_end,
        }
        label = " → ".join(path) or "TOTAL"
        type_label = " / ".join(selected_types)
        status = (
            f"{type_label} · {label} · {resolved_start} to {resolved_end} · "
            f"{len(visible):,} observed daily points (missing dates are not zero-filled)."
        )
        active_preset = preset if preset in {"wtd", "mtd", "ytd", "all"} else None
        classes = [
            "pl-history-range-button" + (" is-active" if active_preset == value else "")
            for value in ("wtd", "mtd", "ytd", "all")
        ]
        raw_records: list[dict[str, object]] = []
        raw_status = (
            "Open Raw historical rows to query the selected scope."
            if not raw_open
            else "This historical source does not expose bounded raw rows."
        )
        if raw_result is not None:
            raw_display = raw_result.rows.loc[:, list(PL_HISTORY_COLUMNS)].copy()
            raw_records = (
                raw_display.astype(object)
                .where(pd.notna(raw_display), None)
                .to_dict("records")
            )
            chart_total = None if visible.empty else float(visible[PL].sum(min_count=1))
            reconciled = (
                chart_total is None
                and raw_result.pl_total is None
                or chart_total is not None
                and raw_result.pl_total is not None
                and math.isclose(
                    chart_total,
                    raw_result.pl_total,
                    rel_tol=1e-9,
                    abs_tol=1e-6,
                )
            )
            shown = len(raw_records)
            raw_status = (
                f"Showing {shown:,} of {raw_result.row_count:,} source rows for "
                f"{resolved_start} to {resolved_end}. "
                + (
                    "Their complete-scope total reconciles to the chart."
                    if reconciled
                    else "Warning: the complete raw scope does not reconcile to the chart."
                )
            )
        return (
            build_pl_history_figure(visible, path=path),
            resolved_range,
            status,
            *classes,
            resolved_start,
            resolved_end,
            visible.loc[:, [MARKET_DATE, HISTORY_TYPE, "PL"]].to_dict("records"),
            raw_records,
            raw_status,
        )


__all__ = ["register_pl_history_callbacks"]
