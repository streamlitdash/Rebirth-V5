"""Inline, lazy history for the current Aggregate P&L table."""

from __future__ import annotations

from collections.abc import Mapping
from threading import RLock

import pandas as pd
from dash import Dash, Input, Output, ctx

from rebirth.domain.s08_pnl import (
    COLOSSUS_TYPE,
    HISTORY_TYPE,
    MARKET_DATE,
    PL,
    PLSendValidationError,
    PREDICT_TYPE,
    load_pl_history,
    select_pl_history_series,
    validate_pl_history_frame,
)
from rebirth.history import PLHistorySeriesResult
from .s01_common import (
    PL_FILTER_EXCLUDE_ID,
    PL_FILTER_FIELDS,
    PL_FILTER_IDS,
    PLHistoryQueryProtocol,
    PLSendConfig,
    apply_pl_filters,
    pl_external_filter_map,
)
from .s03_history import build_pl_history_figure


def _empty_figure():
    return build_pl_history_figure(pd.DataFrame(), path=())


def _selection_criteria(selection: Mapping[str, object]) -> dict[str, list[str]]:
    """Translate one visible current-table cell into positive history filters."""

    criteria: dict[str, list[str]] = {}
    risk_type = str(selection.get("risk_type", "")).strip()
    risk_greek = str(selection.get("risk_greek", "")).strip()
    underlying = str(selection.get("underlying", "")).strip()
    if risk_type:
        criteria["Risk Type"] = [risk_type]
    if risk_greek:
        criteria["Risk Greek"] = [risk_greek]
    if underlying:
        criteria["Underlying"] = [underlying]
    return criteria


def _selection_label(selection: Mapping[str, object]) -> str:
    parts = [str(selection.get("risk_type", "")).strip() or "All risk types"]
    greek = str(selection.get("risk_greek", "")).strip()
    if greek:
        parts.append(greek)
    underlying = str(selection.get("underlying", "")).strip()
    if underlying:
        parts.append(underlying)
    return " · ".join(parts)


def _frame_series(
    frame: pd.DataFrame,
    *,
    history_types: tuple[str, ...],
    preset: str,
    start_date: object,
    end_date: object,
) -> tuple[pd.DataFrame, str | None, str | None]:
    if frame.empty:
        return pd.DataFrame(columns=[MARKET_DATE, HISTORY_TYPE, PL]), None, None
    dates = pd.to_datetime(frame[MARKET_DATE], errors="raise").dt.normalize()
    minimum = dates.min()
    maximum = dates.max()
    selected = str(preset or "1y").casefold()
    if selected == "wtd":
        start = maximum - pd.Timedelta(days=maximum.weekday())
    elif selected == "mtd":
        start = maximum.replace(day=1)
    elif selected == "ytd":
        start = maximum.replace(month=1, day=1)
    elif selected == "1y":
        start = maximum - pd.DateOffset(years=1)
    elif selected == "custom":
        start = pd.Timestamp(start_date).normalize() if start_date else minimum
        maximum = pd.Timestamp(end_date).normalize() if end_date else maximum
    else:
        start = minimum
    start = min(max(pd.Timestamp(start), minimum), maximum)
    maximum = min(max(pd.Timestamp(maximum), minimum), dates.max())
    if start > maximum:
        start, maximum = maximum, start
    selected_frame = select_pl_history_series(frame, ()).loc[
        lambda current: (
            current[HISTORY_TYPE].isin(history_types)
            & pd.to_datetime(current[MARKET_DATE], errors="raise").between(
                start, maximum
            )
        )
    ]
    return (
        selected_frame.reset_index(drop=True),
        start.date().isoformat(),
        maximum.date().isoformat(),
    )


def register_pl_history_callbacks(app: Dash, config: PLSendConfig) -> None:
    """Register one current-cell-to-history callback with bounded SQL access."""

    cache_lock = RLock()
    cached_history: pd.DataFrame | None = None
    query_source = (
        config.history_source
        if isinstance(config.history_source, PLHistoryQueryProtocol)
        else None
    )

    def current_history(*, reload: bool = False) -> pd.DataFrame:
        nonlocal cached_history
        if not reload:
            with cache_lock:
                if cached_history is not None:
                    return cached_history
        source = config.history_source
        loaded = (
            validate_pl_history_frame(source())
            if callable(source)
            else load_pl_history(source)
        )
        with cache_lock:
            cached_history = loaded
        return loaded

    @app.callback(
        Output("pl-history-chart", "figure"),
        Output("pl-history-plot-status", "children"),
        Output("pl-history-selection-label", "children"),
        Output("pnl-history-workspace", "style"),
        Input("pl-history-selection-store", "data"),
        Input("pl-history-series-selector", "value"),
        Input("pl-history-period", "value"),
        Input("pl-history-date-range", "start_date"),
        Input("pl-history-date-range", "end_date"),
        *[Input(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        Input(PL_FILTER_EXCLUDE_ID, "value"),
        Input("clear-cache-complete-store", "data"),
        prevent_initial_call=True,
    )
    def render_inline_pl_history(
        selection,
        series_choice,
        period,
        start_date,
        end_date,
        activity_filter,
        signoff_filter,
        portfolio_filter,
        category_filter,
        subcategory_filter,
        exclude_filter,
        _cache_generation,
    ):
        nonlocal cached_history
        if ctx.triggered_id == "clear-cache-complete-store":
            if query_source is not None:
                query_source.clear()
            with cache_lock:
                cached_history = None
        if not isinstance(selection, Mapping) or not selection:
            return (
                _empty_figure(),
                "History loads only after a P&L value is selected.",
                "No P&L value selected.",
                {"display": "none"},
            )

        selected_types = {
            "colossus": (COLOSSUS_TYPE,),
            "predict": (PREDICT_TYPE,),
            "both": (COLOSSUS_TYPE, PREDICT_TYPE),
        }.get(str(series_choice), (COLOSSUS_TYPE, PREDICT_TYPE))
        page_filters = pl_external_filter_map(
            [
                activity_filter,
                signoff_filter,
                portfolio_filter,
                category_filter,
                subcategory_filter,
            ]
        )
        criteria = _selection_criteria(selection)
        exclude_selected = "exclude" in (exclude_filter or [])
        try:
            if query_source is not None:
                result = query_source.series(
                    path=(),
                    history_types=selected_types,
                    preset=str(period or "1y"),
                    start_date=start_date,
                    end_date=end_date,
                    filters=page_filters,
                    criteria=criteria,
                    exclude_selected=exclude_selected,
                )
                if not isinstance(result, PLHistorySeriesResult):
                    raise TypeError("P&L history source returned an invalid series")
                visible = result.series
                resolved_start = result.resolved_start
                resolved_end = result.resolved_end
            else:
                history = apply_pl_filters(
                    current_history(),
                    page_filters,
                    exclude_selected=exclude_selected,
                )
                history = apply_pl_filters(history, criteria)
                visible, resolved_start, resolved_end = _frame_series(
                    history,
                    history_types=selected_types,
                    preset=str(period or "1y"),
                    start_date=start_date,
                    end_date=end_date,
                )
        except (PLSendValidationError, TypeError, ValueError, OSError) as exc:
            return (
                _empty_figure(),
                f"Historical P&L could not be loaded: {exc}",
                _selection_label(selection),
                {},
            )

        label = _selection_label(selection)
        if resolved_start is None or resolved_end is None or visible.empty:
            return (
                _empty_figure(),
                "No Colossus/Predict P&L history matches this selection.",
                label,
                {},
            )
        status = (
            f"{resolved_start} to {resolved_end} · {len(visible):,} observed points. "
            "Missing dates remain missing rather than being filled with zero."
        )
        return build_pl_history_figure(visible, path=(label,)), status, label, {}


__all__ = ["register_pl_history_callbacks"]
