"""Lazy Stock-history callbacks, isolated from current comparison behavior."""

from __future__ import annotations

from threading import Lock
from typing import Any, Callable, Mapping

import pandas as pd
from dash import Input, Output, State, ctx, html, no_update
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from .data import StockPageData
from .history import (
    STOCK_HISTORY_SELECTOR_LIMIT,
    StockHistoryCatalogResult,
    StockHistoryQueryProtocol,
    build_stock_history_empty_figure,
    build_stock_history_figure,
    build_stock_history_table,
    normalize_stock_history_frame,
    stock_history_date_range,
    stock_history_identity_from_token,
    stock_history_identity_options,
)


def register_stock_history_callbacks(
    app: Any,
    *,
    stock_history_source: Any | None,
    stock_cached_pages: Mapping[tuple[int, str, str, str], StockPageData],
    stock_cache_key: Callable[[object], tuple[int, str, str, str] | None],
) -> None:
    """Register archive work only for the lazily opened History workspace."""

    stock_history_lock = Lock()
    stock_history_cache: dict[tuple[str, str, str, str], pd.DataFrame] = {}

    def stock_history_cache_key(
        token: object,
    ) -> tuple[str, str, str, str] | None:
        if not isinstance(token, Mapping):
            return None
        try:
            return (
                str(token["request_scope"]),
                str(token["identity"]),
                str(token["start_date"]),
                str(token["end_date"]),
            )
        except (KeyError, TypeError, ValueError):
            return None

    if stock_history_source is None:
        return

    query_source = (
        stock_history_source
        if isinstance(stock_history_source, StockHistoryQueryProtocol)
        else None
    )

    @app.callback(
        Output("stock-history-identity", "options"),
        Output("stock-history-identity", "value"),
        Output("stock-history-load-button", "disabled"),
        Output("stock-history-date-range", "min_date_allowed"),
        Output("stock-history-date-range", "max_date_allowed"),
        Output("stock-history-date-range", "start_date"),
        Output("stock-history-date-range", "end_date"),
        Output("stock-history-catalog", "data"),
        Input("stock-workspace-tabs", "value"),
        Input("stock-loaded-dates", "data"),
        Input("stock-history-identity", "search_value"),
        Input("clear-cache-complete-store", "data"),
        State("stock-history-identity", "value"),
        prevent_initial_call=True,
    )
    def sync_stock_history_identities(
        workspace,
        loaded_dates,
        search_value,
        _clear_cache_generation,
        selected_identity,
    ):
        """Search the archive only while the History workspace is active."""

        try:
            trigger = ctx.triggered_id
        except MissingCallbackContextException:
            trigger = None
        if trigger == "clear-cache-complete-store":
            if query_source is not None:
                query_source.clear()
            with stock_history_lock:
                stock_history_cache.clear()
            return [], None, True, None, None, None, None, None
        if workspace != "history":
            return (no_update,) * 8
        try:
            if query_source is not None:
                result = query_source.catalog(
                    search_value,
                    limit=STOCK_HISTORY_SELECTOR_LIMIT,
                )
                if not isinstance(result, StockHistoryCatalogResult):
                    raise TypeError("Stock history source returned an invalid catalog")
                options = list(result.options)
                minimum = result.minimum_date
                maximum = result.maximum_date
                date_count = result.date_count
            else:
                page_data = stock_cached_pages.get(stock_cache_key(loaded_dates))
                if page_data is None:
                    return [], None, True, None, None, None, None, None
                all_options = stock_history_identity_options(page_data.mapped_stock)
                search = str(search_value or "").strip().casefold()
                options = [
                    option
                    for option in all_options
                    if not search or search in option["label"].casefold()
                ][:STOCK_HISTORY_SELECTOR_LIMIT]
                minimum, maximum = stock_history_date_range(page_data.current_date)
                minimum = minimum.date().isoformat()
                maximum = maximum.date().isoformat()
                date_count = 0
        except Exception as error:
            app.logger.exception("Could not search Stock history")
            return (
                [],
                None,
                True,
                None,
                None,
                None,
                None,
                {"error": str(error)},
            )
        option_by_value = {option["value"]: option for option in options}
        selected_option = option_by_value.get(selected_identity)
        if selected_option is None and selected_identity:
            try:
                selected_values = stock_history_identity_from_token(selected_identity)
                selected_option = {
                    "label": " | ".join(
                        f"{column}={value}" for column, value in selected_values.items()
                    ),
                    "value": selected_identity,
                }
                options = [
                    selected_option,
                    *options[: STOCK_HISTORY_SELECTOR_LIMIT - 1],
                ]
            except ValueError:
                selected_option = None
        selected = (
            selected_identity
            if selected_option is not None
            else (options[0]["value"] if options else None)
        )
        if minimum is None or maximum is None:
            return options, selected, True, None, None, None, None, {"date_count": 0}
        start, end = stock_history_date_range(
            maximum,
            preset="1y",
            minimum_date=minimum,
        )
        return (
            options,
            selected,
            not bool(options),
            minimum,
            maximum,
            start.date().isoformat(),
            end.date().isoformat(),
            {
                "minimum_date": minimum,
                "maximum_date": maximum,
                "date_count": date_count,
            },
        )

    @app.callback(
        Output("stock-history-loaded-range", "data"),
        Output("stock-history-status", "children"),
        Input("stock-history-load-button", "n_clicks"),
        State("stock-current-date", "date"),
        State("stock-request-scope", "data"),
        State("stock-history-identity", "value"),
        State("stock-history-period", "value"),
        State("stock-history-date-range", "start_date"),
        State("stock-history-date-range", "end_date"),
        State("stock-history-catalog", "data"),
        prevent_initial_call=True,
    )
    def load_stock_history_rows(
        n_clicks,
        current_date,
        request_scope,
        identity_token,
        period,
        custom_start,
        custom_end,
        catalog_state,
    ):
        """Load the bounded history only after the explicit page-local request."""

        if int(n_clicks or 0) <= 0:
            raise PreventUpdate
        try:
            catalog = dict(catalog_state or {})
            maximum = catalog.get("maximum_date") or current_date
            minimum = catalog.get("minimum_date")
            requested_end = custom_end if period == "custom" else maximum
            start_date, end_date = stock_history_date_range(
                requested_end,
                preset=period,
                minimum_date=minimum,
                start_date=custom_start,
            )
            identity = stock_history_identity_from_token(identity_token)
            with stock_history_lock:
                history = normalize_stock_history_frame(
                    (
                        query_source.rows(identity, start_date, end_date)
                        if query_source is not None
                        else stock_history_source(identity, start_date, end_date)
                    ),
                    identity=identity,
                    start_date=start_date,
                    end_date=end_date,
                )
                token = {
                    "request_scope": str(request_scope or "stock-unscoped"),
                    "identity": identity_token,
                    "start_date": start_date.date().isoformat(),
                    "end_date": end_date.date().isoformat(),
                    "period": str(period),
                }
                key = stock_history_cache_key(token)
                if key is None:
                    raise RuntimeError(
                        "Stock history cache key could not be constructed"
                    )
                stock_history_cache[key] = history
                if len(stock_history_cache) > 4:
                    stock_history_cache.pop(next(iter(stock_history_cache)))
            return (
                token,
                (
                    f"Loaded {len(history):,} historical observations "
                    f"across {history['Stock Date'].nunique():,} available dates "
                    f"from {token['start_date']} through {token['end_date']}."
                ),
            )
        except Exception as error:
            app.logger.exception("Could not load Stock history")
            return (
                None,
                f"Stock history could not be loaded: {error}",
            )

    @app.callback(
        Output("stock-history-chart", "figure"),
        Output("stock-history-table-panel", "children"),
        Input("stock-history-identity", "value"),
        Input("stock-history-metric", "value"),
        Input("stock-history-loaded-range", "data"),
        prevent_initial_call=True,
    )
    def render_stock_history(identity_token, metric, loaded_range):
        """Render one cached exact identity without another archive read."""

        key = stock_history_cache_key(loaded_range)
        history = stock_history_cache.get(key)
        selection_matches = (
            isinstance(loaded_range, Mapping)
            and loaded_range.get("identity") == identity_token
        )
        if history is None or not selection_matches:
            message = "Load history for the selected Stock identity."
            return (
                build_stock_history_empty_figure(message),
                html.P(message, className="static-data-page-note"),
            )
        try:
            return (
                build_stock_history_figure(
                    history,
                    identity_token=identity_token,
                    metric=metric,
                    start_date=loaded_range["start_date"],
                    end_date=loaded_range["end_date"],
                ),
                build_stock_history_table(
                    history,
                    identity_token=identity_token,
                ),
            )
        except Exception as error:
            message = f"Stock history selection could not be rendered: {error}"
            return (
                build_stock_history_empty_figure(message),
                html.P(message, className="static-data-empty", role="alert"),
            )


__all__ = ["register_stock_history_callbacks"]
