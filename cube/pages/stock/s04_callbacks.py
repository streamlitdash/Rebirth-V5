"""Stock callback ownership: one load, one render, one click selection."""

from collections.abc import Mapping
from math import ceil
from threading import Lock

import pandas as pd
from dash import Input, Output, State, ctx, html, no_update
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from cube.ui.s08_refresh_views import refresh_view
from cube.ui.s10_table_data import filter_table_rows
from .s01_data import load_stock_page_data
from .s02_history import (
    build_stock_history_empty_figure,
    build_stock_value_history_figure,
    stock_history_date_range,
)
from .s03_view import stock_table_columns, stock_number_styles, stock_table_records
from .s05_pivot import build_stock_tree


def _trigger():
    try:
        return ctx.triggered_id
    except MissingCallbackContextException:
        return None


def _changed_ids():
    """A row click changes expansion and selection in the same Dash response."""
    try:
        return set(getattr(ctx, "triggered_prop_ids", {}).values()) or {_trigger()}
    except MissingCallbackContextException:
        return {None}


def _stock_snapshot_key(token):
    if not isinstance(token, Mapping) or "current_date" not in token:
        return None
    return int(token.get("revision", 0)), str(token["current_date"])


def stock_raw_page(frame, page, page_size, sort_by, filter_tree, filter_query):
    """Filter/sort server-side; serialize only the requested 25 source rows."""
    filtered = filter_table_rows(frame, filter_tree, filter_query=filter_query)
    ordering = [item for item in (sort_by or []) if item["column_id"] in frame.columns]
    if ordering:
        filtered = filtered.sort_values(
            [item["column_id"] for item in ordering],
            ascending=[item["direction"] == "asc" for item in ordering],
            kind="stable",
            na_position="last",
        )
    size = min(100, max(1, int(page_size or 25)))
    count = ceil(len(filtered) / size)
    page = min(max(0, int(page or 0)), max(0, count - 1))
    return (
        stock_table_records(filtered.iloc[page * size : (page + 1) * size]),
        count,
        len(filtered),
        page,
    )


def stock_history_result(source, selection, page, period, custom_start, custom_end):
    if not selection:
        return no_update, "", {"display": "none"}, "Stock history"
    column, value = selection["column"], selection["value"]
    title = f"{column}: {value}"
    if source is None:
        message = "Stock history connector is not configured."
        return build_stock_history_empty_figure(message), message, {}, title
    # None start means all retained history; the connector returns dated Stock/dStock.
    start = custom_start if period == "custom" else None
    end = (custom_end or page.current_date) if period == "custom" else page.current_date
    identity = {column: value}
    rows = (
        source.stock_series(identity, start, end)
        if hasattr(source, "stock_series")
        else source(identity, start, end)
    )
    history = rows.copy()
    history["Stock Date"] = pd.to_datetime(history["Stock Date"])
    # Current connector observation wins over history for the same date.
    current = page.raw.loc[page.raw[column].eq(value), ["Stock", "dStock"]].sum(
        min_count=1
    )
    if pd.Timestamp(end).normalize() >= page.current_date.normalize():
        history = history.loc[
            history["Stock Date"].dt.normalize().ne(page.current_date.normalize())
        ]
        history = pd.concat(
            [
                history,
                pd.DataFrame(
                    [
                        {
                            "Stock Date": page.current_date,
                            "Stock": current["Stock"],
                            "dStock": current["dStock"],
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
    if history.empty:
        message = f"No Stock history is available for {value}."
        return build_stock_history_empty_figure(message), message, {}, title
    minimum = history["Stock Date"].min()
    start, end = stock_history_date_range(
        end, preset=period, minimum_date=minimum, start_date=custom_start
    )
    figure = build_stock_value_history_figure(
        history, crds=value, activity="", start_date=start, end_date=end
    )
    figure.update_layout(title=None, margin={"l": 65, "r": 65, "t": 35, "b": 45})
    dates = history.loc[
        history["Stock Date"].between(start, end), "Stock Date"
    ].nunique()
    return (
        figure,
        f"{dates:,} available dates · {start.date()} to {end.date()}",
        {},
        title,
    )


def register_callbacks(
    app,
    *,
    refresh_manager,
    stock_source,
    stock_portfolio_source=None,
    saved_view_repository=None,
    stock_history_source=None,
):
    # The two obsolete optional arguments remain accepted for existing callers.
    # No mapping or saved-filter workflow is registered for Stock.
    if stock_source is None:
        return
    cache = {}
    lock = Lock()

    def revision():
        return int(refresh_manager.health.revision) if refresh_manager else 0

    # Native <details> toggling alone does not update Dash's open prop.
    app.clientside_callback(
        "function (clicks) { return Boolean((clicks || 0) % 2); }",
        Output("stock-raw-panel", "open"),
        Input("stock-raw-summary", "n_clicks"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("stock-loaded-snapshot", "data"),
        Output("stock-load-status", "children"),
        Input("stock-load-trigger", "n_intervals"),
        Input("refresh-commit-revision", "children"),
        Input("clear-cache-complete-store", "modified_timestamp"),
        State("stock-date-store", "data"),
        prevent_initial_call=True,
    )
    def load_current_stock(_ticks, refresh_revision, _generation, dates):
        captured = revision()
        try:
            if _trigger() == "clear-cache-complete-store":
                with lock:
                    cache.clear()
                if hasattr(stock_history_source, "clear"):
                    stock_history_source.clear()
            current_date = dates["current_date"]
            if (
                refresh_manager
                and captured > 0
                and hasattr(refresh_manager, "control_snapshot")
            ):
                current_date = refresh_manager.control_snapshot.market_date
            token = {"revision": captured, "current_date": str(current_date)}
            key = _stock_snapshot_key(token)
            with lock:
                if key not in cache:
                    loaded = load_stock_page_data(
                        stock_source=stock_source, current_date=current_date
                    )
                    cache[key] = loaded
                    # Financial snapshots only, never expanded component trees.
                    while len(cache) > 2:
                        cache.pop(next(iter(cache)))
                page = cache[key]
            status = f"As of {page.current_date.date()} · {len(page.raw):,} rows"
            if page.raw.attrs.get("notice"):
                status += " · " + str(page.raw.attrs["notice"])
        except Exception as error:
            app.logger.exception("Could not load Stock")
            if revision() != captured:
                return no_update, no_update
            message = f"Stock could not be loaded: {error}"
            return {
                "revision": max(captured, int(refresh_revision or 0)),
                "error": message,
            }, message
        if revision() != captured:
            return no_update, no_update
        return token, status

    # Decode clicks in the browser: the complete hierarchy never travels back
    # to Python merely to identify one clicked row.
    app.clientside_callback(
        """function (active, records, paths) {
            const no = window.dash_clientside.no_update;
            if (!active || active.column_id !== 'Hierarchy') return [no, no, no];
            const rows = records || [];
            const row = rows.find(item => item.id === active.row_id);
            if (!row) return [no, no, null];
            const selected = JSON.parse(row.id);
            const opened = new Set(paths || []);
            if (paths === null || paths === undefined) {
                for (const item of rows) {
                    if (!item.id.includes('"open":true')) continue;
                    const value = JSON.parse(item.id);
                    if (value.open) opened.add(value.path);
                }
            }
            if (selected.branch) {
                if (selected.open) opened.delete(selected.path);
                else opened.add(selected.path);
            }
            return [Array.from(opened).sort(), selected.selection || no, null];
        }""",
        Output("stock-pivot-open-paths", "data"),
        Output("stock-history-selection", "data"),
        Output("stock-current-table", "active_cell"),
        Input("stock-current-table", "active_cell"),
        State("stock-current-table", "data"),
        State("stock-pivot-open-paths", "data"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("stock-history-custom-range-control", "style"),
        Input("stock-history-period", "value"),
    )
    def show_custom_dates(period):
        return {} if period == "custom" else {"display": "none"}

    @app.callback(
        Output("stock-current-table", "data"),
        Output("stock-row-count", "children"),
        Output("stock-raw-table", "data"),
        Output("stock-raw-table", "columns"),
        Output("stock-raw-table", "style_data_conditional"),
        Output("stock-raw-table", "page_count"),
        Output("stock-raw-status", "children"),
        Output("stock-history-chart", "figure"),
        Output("stock-history-status", "children"),
        Output("stock-history-panel", "style"),
        Output("stock-history-title", "children"),
        Output("stock-raw-table", "page_current"),
        Output("refresh-view-stock-current", "data"),
        Input("stock-loaded-snapshot", "data"),
        Input("stock-pivot-open-paths", "data"),
        Input("stock-raw-panel", "open"),
        Input("stock-raw-table", "page_current"),
        Input("stock-raw-table", "sort_by"),
        Input("stock-raw-table", "derived_filter_query_structure"),
        Input("stock-raw-table", "filter_query"),
        Input("stock-history-selection", "data"),
        Input("stock-history-period", "value"),
        Input("stock-history-date-range", "start_date"),
        Input("stock-history-date-range", "end_date"),
        State("stock-raw-table", "page_size"),
        State("refresh-action-request", "data"),
        prevent_initial_call=True,
    )
    @refresh_view(
        "stock-current",
        revision_arg="loaded_snapshot",
        outputs=12,
        content=[0, 2, 7, 8],
        stamp=[1],
        ready={0: "stock-current-table", 2: "stock-raw-table", 7: "stock-history-chart"},
    )
    def render_current_stock(
        loaded_snapshot,
        opened,
        raw_open,
        raw_page,
        sort_by,
        filter_tree,
        filter_query,
        selection,
        period,
        custom_start,
        custom_end,
        page_size,
    ):
        if not loaded_snapshot:
            raise PreventUpdate
        if int(loaded_snapshot.get("revision", 0)) != revision():
            raise PreventUpdate
        if loaded_snapshot.get("error"):
            raise RuntimeError(loaded_snapshot["error"])
        page = cache.get(_stock_snapshot_key(loaded_snapshot))
        if page is None:
            raise RuntimeError("Stock snapshot expired. Refresh Stock to reload it.")
        changed = _changed_ids()
        new_snapshot = bool(changed & {None, "stock-loaded-snapshot"})
        tree = (
            build_stock_tree(page.raw, opened)
            if new_snapshot or "stock-pivot-open-paths" in changed
            else no_update
        )
        count = f"{len(page.raw):,} connector rows"
        raw = (no_update,) * 5
        corrected_page = no_update
        if raw_open and (
            new_snapshot or changed & {"stock-raw-panel", "stock-raw-table"}
        ):
            try:
                # Changing a filter or sort starts its result at page 1.
                changed_props = (
                    getattr(ctx, "triggered_prop_ids", {})
                    if None not in changed
                    else {}
                )
                reset = any(
                    key.endswith(
                        (".sort_by", ".filter_query", ".derived_filter_query_structure")
                    )
                    for key in changed_props
                )
                records, pages, rows, selected_page = stock_raw_page(
                    page.raw,
                    0 if reset else raw_page,
                    page_size,
                    sort_by,
                    filter_tree,
                    filter_query,
                )
                columns = stock_table_columns(page.raw)
                raw = (
                    records,
                    columns,
                    stock_number_styles(columns),
                    pages,
                    f"{rows:,} of {len(page.raw):,} rows",
                )
                if selected_page != int(raw_page or 0):
                    corrected_page = selected_page
            except ValueError as error:
                raw = no_update, no_update, no_update, no_update, str(error)
        history = (no_update,) * 4
        if new_snapshot or changed & {
            "stock-history-selection",
            "stock-history-period",
            "stock-history-date-range",
        }:
            try:
                history = stock_history_result(
                    stock_history_source,
                    selection,
                    page,
                    period or "all",
                    custom_start,
                    custom_end,
                )
            except Exception as error:
                app.logger.exception("Could not load Stock history")
                message = f"Stock history could not be loaded: {error}"
                history = (
                    no_update,
                    html.Span(message, role="alert"),
                    {},
                    "Stock history",
                )
        if int(loaded_snapshot.get("revision", 0)) != revision():
            raise PreventUpdate
        return tree, count, *raw, *history, corrected_page
