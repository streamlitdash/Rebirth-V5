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

from .s01_data import (
    StockPageData,
    default_stock_activities,
    load_stock_page_data,
    stock_activity_options,
    stock_display_rows,
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
from .s03_view import STOCK_PERIODS, stock_table_records


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
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError("The selected Stock row is invalid")
    crds, activity = (str(value).strip() for value in values)
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
    """Register a small current-table flow and an isolated lazy history flow."""

    del saved_view_repository
    if stock_source is None or stock_portfolio_source is None:
        return

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
        Output("stock-current-activity", "options"),
        Output("stock-current-activity", "value"),
        Output("stock-history-activity", "options"),
        Output("stock-load-status", "children"),
        Input("stock-load-trigger", "n_intervals"),
        Input("refresh-commit-revision", "children"),
        Input("clear-cache-complete-store", "data"),
        State("stock-date-store", "data"),
        State("stock-current-activity", "value"),
        State("stock-loaded-snapshot", "data"),
        State("stock-request-scope", "data"),
        prevent_initial_call=True,
    )
    def load_current_stock(
        _ticks,
        _refresh_revision,
        _cache_generation,
        date_state,
        selected_activities,
        loaded_snapshot,
        request_scope,
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
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                "Stock dates are unavailable.",
            )
        current_date = date_state.get("current_date")
        prior_date = date_state.get("prior_date")
        revision = committed_revision()
        token = {
            "revision": revision,
            "current_date": str(current_date),
            "prior_date": str(prior_date),
            "request_scope": str(request_scope or "stock-unscoped"),
        }
        key = _stock_snapshot_key(token)
        if key is None:
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                "Stock dates are invalid.",
            )

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
            return (
                no_update,
                no_update,
                no_update,
                no_update,
                f"Stock could not be loaded: {error}",
            )

        options = stock_activity_options(page_data.mapped_stock)
        available = {str(option["value"]) for option in options}
        if _stock_snapshot_key(loaded_snapshot) is None:
            selected = default_stock_activities(page_data.mapped_stock)
        else:
            selected = [
                str(value)
                for value in (selected_activities or ())
                if str(value) in available
            ]
        elapsed_ms = (perf_counter() - started) * 1_000
        current_rows = len(stock_display_rows(page_data.mapped_stock))
        app.logger.info(
            "stock.current.loaded rows=%s elapsed_ms=%.1f revision=%s",
            current_rows,
            elapsed_ms,
            revision,
        )
        return (
            token,
            options,
            selected,
            options,
            (
                f"As of {page_data.current_date.date().isoformat()} · "
                f"{current_rows:,} positions · {elapsed_ms:.0f} ms"
            ),
        )

    @app.callback(
        Output("stock-current-table", "data"),
        Output("stock-row-count", "children"),
        Output("stock-mapped-count", "children"),
        Output("stock-unmapped-count", "children"),
        Output("stock-history-crds", "options"),
        Input("stock-loaded-snapshot", "data"),
        Input("stock-current-activity", "value"),
        prevent_initial_call=True,
    )
    def render_current_stock(loaded_snapshot, selected_activities):
        """Filter the cached row-level projection without another source read."""

        page_data = cached_page(loaded_snapshot)
        if page_data is None:
            return [], "Rows: 0", "Mapped: 0", "Unmapped: 0", []
        display = stock_display_rows(page_data.mapped_stock, selected_activities)
        all_rows = stock_display_rows(page_data.mapped_stock)
        crds_values = sorted(
            all_rows["CRDS"].astype(str).unique().tolist(), key=str.casefold
        )
        mapped = int(display["Portfolio Mapped"].eq(True).sum())
        return (
            stock_table_records(display),
            f"Rows: {len(display):,} of {len(all_rows):,}",
            f"Mapped: {mapped:,}",
            f"Unmapped: {len(display) - mapped:,}",
            [{"label": value, "value": value} for value in crds_values],
        )

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

        crds, activity = _selected_stock_row(active_cell)
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
        State("stock-history-crds", "value"),
        State("stock-history-activity", "value"),
        State("stock-history-period", "data"),
        State("stock-history-date-range", "start_date"),
        State("stock-history-date-range", "end_date"),
        State("stock-loaded-snapshot", "data"),
        prevent_initial_call=True,
        running=[(Output("stock-history-load-button", "disabled"), True, False)],
    )
    def load_stock_history(
        autoload,
        load_clicks,
        _cache_generation,
        crds,
        activity,
        period,
        custom_start,
        custom_end,
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
