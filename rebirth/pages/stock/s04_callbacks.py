"""Page-owned callbacks for the single-flow V4.1 Stock page."""

from __future__ import annotations

import json
from collections.abc import Mapping
from threading import Lock
from time import perf_counter
from typing import Any

import pandas as pd
from dash import Input, Output, State, ctx, no_update
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from rebirth.app.s02_contracts import RefreshManagerProtocol
from rebirth.services.s04_savedviews import SavedFilterViewRepository
from rebirth.ui.s03_filters import (
    BASE_SAVED_VIEW_ID,
    committed_filter_state_values,
    register_saved_filter_view_callbacks,
    saved_view_request_id,
    saved_view_request_matches_base,
    saved_view_request_values,
)

from .s01_data import (
    STOCK_DISPLAY_COLUMNS,
    STOCK_FILTER_FIELDS,
    STOCK_FILTER_IDS,
    STOCK_SAVED_VIEW_CONTROLS,
    StockPageData,
    default_stock_filter_values,
    load_stock_page_data,
    stock_display_rows,
    stock_exclude_selected,
    stock_filter_map,
    stock_filter_options,
    stock_history_identities,
)
from .s02_history import (
    StockHistoryCatalogResult,
    StockHistoryQueryProtocol,
    build_stock_history_empty_figure,
    build_stock_value_history_figure,
    normalize_stock_history_frame,
    stock_history_date_range,
)
from .s03_view import STOCK_PERIODS, stock_pivot_columns, stock_table_records
from .s05_pivot import (
    build_stock_pivot,
    stock_pivot_row_payload,
    toggle_stock_pivot_path,
)


def _stock_snapshot_key(token: object) -> tuple[int, str, str] | None:
    if not isinstance(token, Mapping):
        return None
    try:
        return (
            int(token["revision"]),
            str(token["current_date"]),
            str(token["prior_date"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _selected_stock_row(active_cell: object) -> tuple[str, str]:
    if not isinstance(active_cell, Mapping):
        raise ValueError("Click a Stock row")
    row_id = active_cell.get("row_id")
    if not isinstance(row_id, str):
        raise ValueError("The selected Stock row is invalid")
    try:
        values = json.loads(row_id)
    except json.JSONDecodeError as error:
        raise ValueError("The selected Stock row is invalid") from error
    if isinstance(values, Mapping):
        if values.get("kind") != "history":
            raise ValueError("Expand the branch and click a history-ready leaf")
        crds = str(values.get("crds") or "").strip()
        activity = str(values.get("activity") or "").strip()
    elif isinstance(values, list) and len(values) == 2:
        crds, activity = (str(value).strip() for value in values)
    else:
        raise ValueError("The selected Stock row is invalid")
    if not crds or not activity:
        raise ValueError("The selected Stock row is invalid")
    return crds, activity


def _period_from_trigger(triggered_id: object) -> str:
    prefix = "stock-period-"
    value = str(triggered_id or "")
    if not value.startswith(prefix):
        raise ValueError("Unknown Stock history period control")
    period = value[len(prefix) :]
    if period not in {value for _label, value in STOCK_PERIODS}:
        raise ValueError("Unknown Stock history period control")
    return period


def register_callbacks(
    app: Any,
    *,
    refresh_manager: RefreshManagerProtocol | None,
    stock_source: Any | None,
    stock_portfolio_source: Any | None,
    saved_view_repository: SavedFilterViewRepository,
    stock_history_source: Any | None = None,
) -> None:
    """Register Stock-local filters, pivot state, and inline lazy history."""

    if stock_source is None or stock_portfolio_source is None:
        return

    register_saved_filter_view_callbacks(
        app,
        saved_view_repository,
        STOCK_SAVED_VIEW_CONTROLS,
    )

    cache_lock = Lock()
    cached_pages: dict[tuple[int, str, str], StockPageData] = {}

    def committed_revision() -> int:
        try:
            return int(refresh_manager.health.revision) if refresh_manager else 0
        except Exception:
            return 0

    def cached_page(token: object) -> StockPageData | None:
        key = _stock_snapshot_key(token)
        return cached_pages.get(key) if key is not None else None

    @app.callback(
        Output("stock-loaded-snapshot", "data"),
        Output("stock-load-status", "children"),
        Input("stock-load-trigger", "n_intervals"),
        Input("refresh-commit-revision", "children"),
        Input("clear-cache-complete-store", "data"),
        State("stock-date-store", "data"),
        prevent_initial_call=True,
    )
    def load_current_stock(
        _ticks,
        _refresh_revision,
        _cache_generation,
        date_state,
    ):
        """Load only the latest two Stock leaves and one mapping authority."""

        try:
            trigger = ctx.triggered_id
        except MissingCallbackContextException:
            trigger = None
        if trigger == "clear-cache-complete-store":
            with cache_lock:
                cached_pages.clear()
            if isinstance(stock_history_source, StockHistoryQueryProtocol):
                stock_history_source.clear()

        if not isinstance(date_state, Mapping):
            return no_update, "Stock dates are unavailable."
        current_date = date_state.get("current_date")
        prior_date = date_state.get("prior_date")
        revision = committed_revision()
        token = {
            "revision": revision,
            "current_date": str(current_date),
            "prior_date": str(prior_date),
        }
        key = _stock_snapshot_key(token)
        if key is None:
            return no_update, "Stock dates are invalid."

        started = perf_counter()
        try:
            with cache_lock:
                page_data = cached_pages.get(key)
                if page_data is None:
                    page_data = load_stock_page_data(
                        stock_source=stock_source,
                        portfolio_config_source=stock_portfolio_source,
                        current_date=current_date,
                        prior_date=prior_date,
                        portfolio_date=current_date,
                    )
                    cached_pages[key] = page_data
                    while len(cached_pages) > 4:
                        cached_pages.pop(next(iter(cached_pages)))
        except Exception as error:
            app.logger.exception("Could not load current Stock")
            return no_update, f"Stock could not be loaded: {error}"

        elapsed_ms = (perf_counter() - started) * 1_000
        current_rows = len(stock_display_rows(page_data.mapped_stock))
        app.logger.info(
            "stock.current.loaded rows=%s elapsed_ms=%.1f revision=%s",
            current_rows,
            elapsed_ms,
            revision,
        )
        return token, (
            f"As of {page_data.current_date.date().isoformat()} · "
            f"{current_rows:,} positions · {elapsed_ms:.0f} ms"
        )

    filter_outputs = [
        output
        for field in STOCK_FILTER_FIELDS
        for output in (
            Output(STOCK_FILTER_IDS[field.key], "options"),
            Output(STOCK_FILTER_IDS[field.key], "value"),
        )
    ]

    @app.callback(
        *filter_outputs,
        Output(STOCK_SAVED_VIEW_CONTROLS.exclude_id, "value"),
        Output("stock-filter-ready", "data"),
        Input("stock-loaded-snapshot", "data"),
        Input(STOCK_SAVED_VIEW_CONTROLS.apply_request_id, "data"),
        Input("clear-cache-complete-store", "data"),
        *[State(STOCK_FILTER_IDS[field.key], "value") for field in STOCK_FILTER_FIELDS],
        State(STOCK_SAVED_VIEW_CONTROLS.exclude_id, "value"),
        State(STOCK_SAVED_VIEW_CONTROLS.applied_request_id, "data"),
        State("stock-filter-ready", "data"),
        prevent_initial_call=True,
    )
    def update_stock_filters(
        loaded_snapshot,
        saved_view_request,
        _cache_generation,
        *state,
    ):
        """Own all five filter values and apply Base Review exactly once."""

        page_data = cached_page(loaded_snapshot)
        selected_values = list(state[: len(STOCK_FILTER_FIELDS)])
        exclude_value = list(state[len(STOCK_FILTER_FIELDS)] or [])
        applied_request = state[len(STOCK_FILTER_FIELDS) + 1]
        ready = bool(state[len(STOCK_FILTER_FIELDS) + 2])
        if page_data is None:
            result: list[object] = []
            for selected in selected_values:
                result.extend(([], list(selected or [])))
            return (*result, exclude_value, ready)

        try:
            trigger = ctx.triggered_id
        except MissingCallbackContextException:
            trigger = None
        request_id = saved_view_request_id(saved_view_request)
        pending = bool(request_id and request_id != applied_request)
        matches_base = False
        if pending:
            try:
                matches_base = saved_view_request_matches_base(
                    saved_view_request,
                    STOCK_SAVED_VIEW_CONTROLS,
                    selected_values,
                    exclude_value,
                )
            except ValueError:
                matches_base = False
        apply_pending = pending and (
            trigger == STOCK_SAVED_VIEW_CONTROLS.apply_request_id or matches_base
        )
        if apply_pending:
            try:
                requested = saved_view_request_values(
                    saved_view_request,
                    STOCK_SAVED_VIEW_CONTROLS,
                )
            except ValueError:
                requested = None
            if requested is not None:
                requested_values, exclude_value = requested
                selected_values = [list(values) for values in requested_values]

        use_base = (
            not ready
            or trigger == "clear-cache-complete-store"
            or (
                apply_pending
                and isinstance(saved_view_request, Mapping)
                and saved_view_request.get("view_id") == BASE_SAVED_VIEW_ID
            )
        )
        if use_base:
            defaults = default_stock_filter_values(page_data.mapped_stock)
            selected_values = [defaults[field.key] for field in STOCK_FILTER_FIELDS]
            exclude_value = []

        selected_map = stock_filter_map(selected_values)
        options, valid = stock_filter_options(page_data.mapped_stock, selected_map)
        result = []
        for field in STOCK_FILTER_FIELDS:
            result.extend((options[field.key], valid[field.key]))
        return (*result, exclude_value, True)

    @app.callback(
        Output("stock-current-table", "data"),
        Output("stock-current-table", "columns"),
        Output("stock-position-detail-table", "data"),
        Output("stock-row-count", "children"),
        Output("stock-mapped-count", "children"),
        Output("stock-unmapped-count", "children"),
        Output("stock-history-crds", "options"),
        Output("stock-history-activity", "options"),
        Input("stock-loaded-snapshot", "data"),
        Input(STOCK_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
        Input("stock-pivot-rows", "value"),
        Input("stock-pivot-column", "value"),
        Input("stock-pivot-values", "value"),
        Input("stock-pivot-open-paths", "data"),
        prevent_initial_call=True,
    )
    def render_current_stock(
        loaded_snapshot,
        committed_filter_state,
        pivot_rows,
        pivot_column,
        pivot_values,
        open_paths,
    ):
        """Rebuild the pivot from applied filters, never draft controls."""

        page_data = cached_page(loaded_snapshot)
        if page_data is None:
            empty = pd.DataFrame(columns=list(STOCK_DISPLAY_COLUMNS))
            pivot = build_stock_pivot(
                empty,
                row_fields=pivot_rows,
                column_field=pivot_column,
                value_fields=pivot_values,
                open_paths=open_paths,
            )
            return (
                [],
                stock_pivot_columns(pivot.columns),
                [],
                "Rows: 0",
                "Mapped: 0",
                "Unmapped: 0",
                [],
                [],
            )
        try:
            committed_values = committed_filter_state_values(
                committed_filter_state,
                STOCK_SAVED_VIEW_CONTROLS,
            )
        except ValueError as error:
            app.logger.warning("Ignoring invalid committed Stock filters: %s", error)
            committed_values = None
        if committed_values is None:
            defaults = default_stock_filter_values(page_data.mapped_stock)
            filter_values = [defaults[field.key] for field in STOCK_FILTER_FIELDS]
            exclude_value: list[str] = []
        else:
            filter_values, exclude_value = committed_values
        display = stock_display_rows(
            page_data.mapped_stock,
            dimension_filters=stock_filter_map(filter_values),
            exclude_selected=stock_exclude_selected(exclude_value),
        )
        pivot = build_stock_pivot(
            display,
            row_fields=pivot_rows,
            column_field=pivot_column,
            value_fields=pivot_values,
            open_paths=open_paths,
        )
        try:
            trigger = ctx.triggered_id
        except MissingCallbackContextException:
            trigger = None
        if trigger in {
            "stock-pivot-open-paths",
            "stock-pivot-rows",
            "stock-pivot-column",
            "stock-pivot-values",
        }:
            return (
                pivot.records,
                stock_pivot_columns(pivot.columns),
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
                no_update,
            )
        all_rows = stock_display_rows(page_data.mapped_stock)
        crds_values = sorted(
            all_rows["CRDS"].astype(str).unique().tolist(), key=str.casefold
        )
        activity_values = sorted(
            all_rows["Activity"].astype(str).unique().tolist(), key=str.casefold
        )
        mapped = int(display["Portfolio Mapped"].eq(True).sum())
        return (
            pivot.records,
            stock_pivot_columns(pivot.columns),
            stock_table_records(display),
            f"Rows: {len(display):,} of {len(all_rows):,}",
            f"Mapped: {mapped:,}",
            f"Unmapped: {len(display) - mapped:,}",
            [{"label": value, "value": value} for value in crds_values],
            [{"label": value, "value": value} for value in activity_values],
        )

    @app.callback(
        Output("stock-pivot-open-paths", "data"),
        Output("stock-current-table", "active_cell"),
        Input("stock-current-table", "active_cell"),
        State("stock-pivot-open-paths", "data"),
        prevent_initial_call=True,
    )
    def toggle_stock_branch(active_cell, open_paths):
        if not isinstance(active_cell, Mapping):
            raise PreventUpdate
        if active_cell.get("column_id") != "Hierarchy":
            raise PreventUpdate
        try:
            payload = stock_pivot_row_payload(active_cell.get("row_id"))
        except ValueError as error:
            raise PreventUpdate from error
        if payload.get("kind") != "branch":
            raise PreventUpdate
        return toggle_stock_pivot_path(open_paths, payload["path"]), None

    @app.callback(
        Output("stock-history-crds", "value"),
        Output("stock-history-activity", "value"),
        Output("stock-history-autoload", "data"),
        Input("stock-current-table", "active_cell"),
        State("stock-loaded-snapshot", "data"),
        prevent_initial_call=True,
    )
    def select_stock_row(active_cell, loaded_snapshot):
        """Prefill the inline controls and request history for one clicked row."""

        try:
            crds, activity = _selected_stock_row(active_cell)
        except ValueError as error:
            raise PreventUpdate from error
        page_data = cached_page(loaded_snapshot)
        if page_data is None or not stock_history_identities(
            page_data.mapped_stock,
            crds=crds,
            activity=activity,
        ):
            raise PreventUpdate
        return crds, activity, {"crds": crds, "activity": activity}

    period_outputs = [
        Output(f"stock-period-{value}", "className") for _label, value in STOCK_PERIODS
    ]

    @app.callback(
        Output("stock-history-period", "data"),
        *period_outputs,
        *[
            Input(f"stock-period-{value}", "n_clicks")
            for _label, value in STOCK_PERIODS
        ],
        prevent_initial_call=True,
    )
    def select_stock_period(*_clicks):
        """Keep period buttons as one ordinary, editable segmented control."""

        try:
            period = _period_from_trigger(ctx.triggered_id)
        except (MissingCallbackContextException, ValueError):
            raise PreventUpdate
        classes = [
            (
                "refresh-button stock-period-button stock-period-selected"
                if value == period
                else "refresh-button stock-period-button"
            )
            for _label, value in STOCK_PERIODS
        ]
        return period, *classes

    app.clientside_callback(
        """
        function (period) {
            return String(period || "").toLowerCase() === "custom"
                ? {}
                : {display: "none"};
        }
        """,
        Output("stock-history-custom-range-control", "style"),
        Input("stock-history-period", "data"),
    )

    if stock_history_source is None:
        return

    query_source = (
        stock_history_source
        if isinstance(stock_history_source, StockHistoryQueryProtocol)
        else None
    )

    @app.callback(
        Output("stock-history-chart", "figure"),
        Output("stock-history-status", "children"),
        Input("stock-history-autoload", "data"),
        Input("stock-history-load-button", "n_clicks"),
        Input("clear-cache-complete-store", "data"),
        Input("stock-history-period", "data"),
        Input("stock-history-date-range", "start_date"),
        Input("stock-history-date-range", "end_date"),
        State("stock-history-crds", "value"),
        State("stock-history-activity", "value"),
        State("stock-loaded-snapshot", "data"),
        prevent_initial_call=True,
        running=[(Output("stock-history-load-button", "disabled"), True, False)],
    )
    def load_stock_history(
        autoload,
        load_clicks,
        _cache_generation,
        period,
        custom_start,
        custom_end,
        crds,
        activity,
        loaded_snapshot,
    ):
        """Read archive rows only after a row click or explicit Load."""

        try:
            trigger = ctx.triggered_id
        except MissingCallbackContextException:
            trigger = None
        if trigger == "clear-cache-complete-store":
            message = "Stock history cache cleared. Select or load a position."
            return build_stock_history_empty_figure(message), message
        if trigger == "stock-history-autoload":
            if not isinstance(autoload, Mapping):
                raise PreventUpdate
            crds = autoload.get("crds")
            activity = autoload.get("activity")
        elif trigger == "stock-history-load-button" and int(load_clicks or 0) <= 0:
            raise PreventUpdate
        elif trigger in {
            "stock-history-period",
            "stock-history-date-range",
        }:
            if not crds or not activity:
                raise PreventUpdate
            if trigger == "stock-history-date-range" and str(period) != "custom":
                raise PreventUpdate

        page_data = cached_page(loaded_snapshot)
        if page_data is None:
            message = "Load current Stock before requesting history."
            return build_stock_history_empty_figure(message), message
        try:
            identities = stock_history_identities(
                page_data.mapped_stock,
                crds=crds,
                activity=activity,
            )
            if not identities:
                raise ValueError("No current Stock row matches that CRDS and Activity")

            minimum = None
            maximum = page_data.current_date.date().isoformat()
            if query_source is not None:
                catalog = query_source.catalog(crds, limit=1)
                if not isinstance(catalog, StockHistoryCatalogResult):
                    raise TypeError("Stock history source returned an invalid catalog")
                minimum = catalog.minimum_date
                maximum = catalog.maximum_date or maximum
            selected_period = str(period or "1y")
            requested_end = custom_end if selected_period == "custom" else maximum
            start_date, end_date = stock_history_date_range(
                requested_end,
                preset=selected_period,
                minimum_date=minimum,
                start_date=custom_start,
            )
            query_start = start_date - pd.offsets.BDay(1)
            if minimum is not None:
                query_start = max(query_start, pd.Timestamp(minimum))

            frames: list[pd.DataFrame] = []
            for identity in identities:
                raw = (
                    query_source.rows(identity, query_start, end_date)
                    if query_source is not None
                    else stock_history_source(identity, query_start, end_date)
                )
                frames.append(
                    normalize_stock_history_frame(
                        raw,
                        identity=identity,
                        start_date=query_start,
                        end_date=end_date,
                    )
                )
            history = pd.concat(frames, ignore_index=True)
            if history.empty:
                message = f"No Stock history is available for {crds} · {activity} in this period."
                return build_stock_history_empty_figure(message), message
            figure = build_stock_value_history_figure(
                history,
                crds=crds,
                activity=activity,
                start_date=start_date,
                end_date=end_date,
            )
            observations = history.loc[
                history["Stock Date"].between(start_date, end_date), "Stock Date"
            ].nunique()
            return (
                figure,
                (
                    f"Loaded {observations:,} available dates from "
                    f"{start_date.date().isoformat()} through {end_date.date().isoformat()}."
                ),
            )
        except Exception as error:
            app.logger.exception("Could not load Stock history")
            message = f"Stock history could not be loaded: {error}"
            return build_stock_history_empty_figure(message), message


__all__ = [
    "_period_from_trigger",
    "_selected_stock_row",
    "_stock_snapshot_key",
    "register_callbacks",
]
