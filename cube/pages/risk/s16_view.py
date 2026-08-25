"""Committed V5 Risk-page layout, date editor, checker, and mapping disclosures."""

from __future__ import annotations

from typing import Mapping

import pandas as pd
from dash import dash_table, dcc, html

from cube.domain.s01_schema import PORTFOLIO_METADATA_COLUMNS
from cube.ui.s02_aggregation import (
    apply_credit_measure,
    apply_filters,
    default_open_rows,
    filter_ir_family,
    ordered_unique,
)
from cube.ui.s04_components import (
    build_cube_loader,
    build_shared_refresh_shell,
)
from cube.ui.s01_constants import (
    CREDIT_MEASURES,
    DEFAULT_UNDERLYING_SORT_METRIC,
    DEFAULT_VIEW_DIMENSION,
    DETAIL_COMPONENT_LABELS,
    DETAIL_COMPONENTS,
    DETAIL_MEASURES,
    DIMENSION_FILTER_IDS,
    EXPANDABLE_METRICS,
    RISK_FILTER_DIMENSION_FIELDS,
    IR_GREEK_FAMILY_LABELS,
    METRIC_COLUMNS,
    UNDERLYING_SORT_METRICS,
    VIEW_DIMENSION_FIELDS,
)
from cube.app.s02_contracts import ControlSnapshotProtocol, RefreshSnapshotProtocol
from cube.ui.s03_filters import build_saved_filter_view_bar

from .s05_charts import detail_tenor_view_state
from .s01_common import RISK_FILTER_NOTE, RISK_SAVED_VIEW_CONTROLS, metric_title
from .s03_defaults import default_risk_filter_payload, default_risk_filter_values
from .s11_promotion import build_promotion_generation_controls
from .s09_quickmarket import build_quick_market_search
from .s08_quickrisk import build_quick_search
from .s13_workspacetables import TOP_PROMOTION_SIGNALS


_UNSET = object()


def build_risk_date_editor(
    snapshot: RefreshSnapshotProtocol,
    applied_overrides: dict[str, str] | None,
    draft_overrides: dict[str, str] | None = None,
    applied_view_date: str | None = None,
    draft_view_date: object = _UNSET,
) -> html.Div:
    applied = dict(applied_overrides or {})
    draft = dict(applied if draft_overrides is None else draft_overrides)
    snapshot_view = getattr(snapshot, "forced_view_date", None)
    applied_view = applied_view_date or (
        pd.Timestamp(snapshot_view).date().isoformat()
        if snapshot_view is not None
        else None
    )
    if draft_view_date is _UNSET:
        draft_view = applied_view
    else:
        draft_view = (
            pd.Timestamp(draft_view_date).date().isoformat()
            if draft_view_date not in (None, "")
            else None
        )
    system_today = pd.Timestamp(snapshot.system_date).date()
    market_date = pd.Timestamp(snapshot.market_date).date()
    view_dirty = draft_view != applied_view
    rows = []
    status = snapshot.risk_status.sort_values("Source Type")
    source_types = status["Source Type"].astype(str).tolist()
    common_forced_dates = {draft.get(source) for source in source_types}
    force_all_risk = (
        bool(source_types)
        and None not in common_forced_dates
        and len(common_forced_dates) == 1
    )
    suggested_market_date = pd.Timestamp(draft_view or market_date).normalize()
    loaded_market_date = pd.Timestamp(snapshot.market_date).normalize()
    status_is_loaded = suggested_market_date == loaded_market_date
    market_status = (
        str(snapshot.market_status) if status_is_loaded else "Resolved on apply"
    )
    market_status_class = (
        f"is-{str(snapshot.market_status).casefold()}"
        if status_is_loaded
        else "is-pending"
    )
    suggested_risk_date = (
        (suggested_market_date - pd.offsets.BDay(1)).date().isoformat()
    )
    loaded_checker_date = pd.Timestamp(snapshot.checker_date).date().isoformat()
    forced_all_risk_date = (
        next(iter(common_forced_dates)) if force_all_risk else suggested_risk_date
    )
    for record in status.to_dict("records"):
        source_type = str(record["Source Type"])
        forced_date = draft.get(source_type)
        applied_date = applied.get(source_type)
        effective = pd.Timestamp(record["Effective Risk Date"]).date().isoformat()
        suggested_source_date = (
            pd.Timestamp(record["Suggested Risk Date"]).date().isoformat()
        )
        age = int(record["Age"])
        age_defaulted = bool(record.get("Age Defaulted", False))
        age_label = f"{age} (T-1 fallback)" if age_defaulted else str(age)
        age_title = (
            "RiskChecker did not report this Risk Type / Risk Greek pair; "
            "Cube uses Age 0, the business day before the market date."
            if age_defaulted
            else f"RiskChecker explicitly reported Age {age}."
        )
        rows.append(
            html.Tr(
                [
                    html.Td(source_type, className="status-source"),
                    html.Td(age_label, title=age_title),
                    html.Td(suggested_source_date),
                    html.Td(effective, className="applied-risk-date"),
                    html.Td(
                        dcc.Checklist(
                            id={"type": "force-risk-checkbox", "source": source_type},
                            options=[{"label": "Force", "value": "force"}],
                            value=["force"] if forced_date else [],
                            className="force-risk-check",
                        )
                    ),
                    html.Td(
                        dcc.DatePickerSingle(
                            id={"type": "forced-risk-date", "source": source_type},
                            date=forced_date or effective,
                            max_date_allowed=system_today,
                            display_format="YYYY-MM-DD",
                            clearable=False,
                            disabled=not bool(forced_date),
                        )
                    ),
                ],
                className="force-risk-row is-dirty"
                if forced_date != applied_date
                else "force-risk-row",
            )
        )
    checker_enabled = bool(getattr(snapshot, "risk_checker_enabled", False))
    checker_content = html.Div(
        (
            f"Open this section to render the dated MRX File inventory for {loaded_checker_date}."
            + (
                f" Apply reloads the inventory for {suggested_risk_date}."
                if suggested_risk_date != loaded_checker_date
                else ""
            )
            if checker_enabled
            else "Risk checker is Off; its combined readiness and MRX File inventory function is not called."
        ),
        className="status-panel-note",
    )
    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            html.H3("Market date", className="date-card-title"),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Span(
                                                "System today",
                                                className="market-view-label",
                                            ),
                                            html.Strong(
                                                system_today.isoformat(),
                                                className="market-view-value",
                                            ),
                                        ],
                                        className="market-view-stat",
                                    ),
                                    html.Div(
                                        [
                                            html.Span(
                                                "Suggested market date",
                                                className="market-view-label",
                                            ),
                                            html.Strong(
                                                suggested_market_date.date().isoformat(),
                                                className="market-view-value",
                                            ),
                                        ],
                                        className="market-view-stat",
                                    ),
                                    html.Div(
                                        [
                                            html.Span(
                                                "Market status",
                                                className="market-view-label",
                                            ),
                                            html.Strong(
                                                market_status,
                                                className=f"market-view-status {market_status_class}",
                                            ),
                                        ],
                                        className="market-view-stat",
                                    ),
                                ],
                                className="date-card-stats",
                            ),
                            html.Div(
                                [
                                    dcc.Checklist(
                                        id="force-view-date-checkbox",
                                        options=[
                                            {
                                                "label": "Force market date",
                                                "value": "force",
                                            }
                                        ],
                                        value=["force"] if draft_view else [],
                                        className="force-view-date-check",
                                    ),
                                    dcc.DatePickerSingle(
                                        id="forced-view-date",
                                        date=draft_view or market_date,
                                        max_date_allowed=system_today,
                                        display_format="YYYY-MM-DD",
                                        clearable=False,
                                        disabled=not bool(draft_view),
                                    ),
                                    html.Span(
                                        "Draft" if view_dirty else "Applied",
                                        className="market-view-draft-state is-dirty"
                                        if view_dirty
                                        else "market-view-draft-state",
                                    ),
                                ],
                                className="market-view-force",
                            ),
                        ],
                        className="market-view-card is-dirty"
                        if view_dirty
                        else "market-view-card",
                    ),
                    html.Div(
                        [
                            html.H3("Risk date", className="date-card-title"),
                            html.Div(
                                [
                                    html.Div(
                                        [
                                            html.Span(
                                                "Suggested risk date",
                                                className="market-view-label",
                                            ),
                                            html.Strong(
                                                suggested_risk_date,
                                                className="market-view-value",
                                            ),
                                        ],
                                        className="market-view-stat",
                                    ),
                                    html.Div(
                                        [
                                            html.Span(
                                                "Date rule",
                                                className="market-view-label",
                                            ),
                                            html.Strong(
                                                "Market date - 1 business day",
                                                className="market-view-rule",
                                            ),
                                        ],
                                        className="market-view-stat",
                                    ),
                                    html.Div(
                                        [
                                            html.Span(
                                                "Forced sources",
                                                className="market-view-label",
                                            ),
                                            html.Strong(
                                                str(
                                                    sum(
                                                        bool(draft.get(source))
                                                        for source in source_types
                                                    )
                                                ),
                                                className="market-view-value",
                                            ),
                                        ],
                                        className="market-view-stat",
                                    ),
                                ],
                                className="date-card-stats",
                            ),
                            html.Div(
                                [
                                    dcc.Checklist(
                                        id="force-all-risk-checkbox",
                                        options=[
                                            {
                                                "label": "Force all risk",
                                                "value": "force",
                                            }
                                        ],
                                        value=["force"] if force_all_risk else [],
                                        className="force-view-date-check",
                                    ),
                                    dcc.DatePickerSingle(
                                        id="forced-all-risk-date",
                                        date=forced_all_risk_date,
                                        max_date_allowed=system_today,
                                        display_format="YYYY-MM-DD",
                                        clearable=False,
                                        disabled=not force_all_risk,
                                    ),
                                ],
                                className="market-view-force",
                            ),
                        ],
                        className="market-view-card risk-view-card",
                    ),
                ],
                className="date-control-grid",
            ),
            html.Details(
                [
                    html.Summary("Risk readiness", className="nested-status-summary"),
                    html.Div(
                        "Age 0 uses the business day before the market date; Age 1 uses two business days before it. "
                        "T-1 fallback appears only when RiskChecker omits a configured pair; Cube keeps that product "
                        "at Age 0 instead of silently dropping it. Force all risk or a per-source override is absolute. "
                        "Edit the draft, then choose Apply.",
                        className="status-panel-note",
                    ),
                    html.Div(
                        html.Table(
                            [
                                html.Thead(
                                    html.Tr(
                                        [
                                            html.Th(value)
                                            for value in [
                                                "Source type",
                                                "Age",
                                                "System risk date",
                                                "Applied risk date",
                                                "Force risk",
                                                "Draft override date",
                                            ]
                                        ]
                                    )
                                ),
                                html.Tbody(rows),
                            ],
                            className="status-table",
                        ),
                        className="status-table-wrap",
                    ),
                ],
                open=False,
                className="nested-status-details risk-readiness-inventory-details",
            ),
            html.Details(
                [
                    html.Summary(
                        "Risk checker inventory",
                        id="risk-checker-inventory-summary",
                        n_clicks=0,
                        className="nested-status-summary",
                    ),
                    html.Div(checker_content, id="risk-checker-inventory"),
                ],
                id="risk-checker-inventory-details",
                open=False,
                className="nested-status-details risk-checker-inventory-details",
            ),
        ],
        className="status-panel",
    )


def build_risk_checker_inventory(
    checker_frame: pd.DataFrame,
    checker_date: object,
    *,
    enabled: bool,
    row_limit: int = 2_000,
) -> html.Div:
    """Render the potentially large checker inventory only when requested."""
    if not enabled:
        return html.Div(
            "Risk checker is Off; its combined readiness and MRX File inventory function is not called.",
            className="status-panel-note",
        )

    checker_columns = ["Risk Type", "Risk Greek", "MRX File", "Product"]
    checker = checker_frame.reindex(columns=checker_columns)
    limit = max(1, int(row_limit))
    visible = checker.head(limit)
    rows = [
        html.Tr([html.Td(str(record[column])) for column in checker_columns])
        for record in visible.to_dict("records")
    ]
    loaded_checker_date = pd.Timestamp(checker_date).date().isoformat()
    note = f"{len(checker):,} dated MRX File inventory rows loaded for {loaded_checker_date}."
    if len(checker) > len(visible):
        note += f" Showing the first {len(visible):,} rows."
    return html.Div(
        [
            html.Div(note, className="status-panel-note"),
            html.Div(
                html.Table(
                    [
                        html.Thead(
                            html.Tr([html.Th(column) for column in checker_columns])
                        ),
                        html.Tbody(rows),
                    ],
                    className="status-table",
                ),
                className="status-table-wrap",
            ),
        ]
    )


def build_unmapped_books_table(frame: pd.DataFrame) -> html.Div:
    if frame.empty:
        return html.Div(
            "All portfolios are mapped in config.", className="unmapped-empty"
        )

    total_rows = len(frame)
    portfolio_count = (
        frame["Portfolio"].dropna().astype(str).str.strip().replace("", pd.NA).nunique()
        if "Portfolio" in frame
        else 0
    )
    portfolio_label = "portfolio" if portfolio_count == 1 else "portfolios"
    display_frame = frame.head(2_000).copy()
    requested_columns = [
        "Portfolio",
        "Risk Type",
        "Risk Greek",
        "Split",
        *PORTFOLIO_METADATA_COLUMNS,
        "Group",
        "Underlying",
        "Tenor Swap",
        "Tenor Swap Order",
        "Tenor Option",
        "Tenor Option Order",
        "Risk",
        "dRisk",
        "PL",
    ]
    columns = list(
        dict.fromkeys(value for value in requested_columns if value in display_frame)
    )
    table_frame = display_frame[columns].copy()
    table_frame = table_frame.astype(object).where(pd.notna(table_frame), None)
    numeric_columns = {"Tenor Swap Order", "Tenor Option Order", "Risk", "dRisk", "PL"}
    return html.Div(
        [
            html.Div(
                f"{total_rows:,} normalized P&L rows across {portfolio_count:,} "
                f"{portfolio_label} are excluded from mapped dashboard totals because "
                "their Portfolio value has no matching config entry. "
                "They remain visible here for remediation. "
                + ("The first 2,000 are shown." if total_rows > 2_000 else ""),
                className="unmapped-note",
            ),
            html.Div(
                dash_table.DataTable(
                    id="unmapped-books-table",
                    columns=[
                        {
                            "name": column,
                            "id": column,
                            **(
                                {"type": "numeric", "format": {"specifier": ",.0f"}}
                                if column in numeric_columns
                                else {}
                            ),
                        }
                        for column in columns
                    ],
                    data=table_frame.to_dict("records"),
                    editable=False,
                    filter_action="native",
                    filter_options={"case": "insensitive"},
                    sort_action="native",
                    sort_mode="multi",
                    page_action="native",
                    page_size=25,
                    fixed_rows={"headers": True},
                    style_table={"overflowX": "auto", "maxHeight": "520px"},
                    style_header={
                        "backgroundColor": "#F7F8FA",
                        "color": "#111111",
                        "fontWeight": "850",
                    },
                    style_cell={
                        "backgroundColor": "#FFFFFF",
                        "color": "#111111",
                        "border": "1px solid #E2E6EA",
                        "fontFamily": (
                            '"Segoe UI Variable Text", "Segoe UI", Arial, sans-serif'
                        ),
                        "fontSize": "12px",
                        "padding": "7px 9px",
                        "textAlign": "left",
                        "minWidth": "110px",
                        "whiteSpace": "nowrap",
                    },
                    style_cell_conditional=[
                        {
                            "if": {"column_id": list(numeric_columns)},
                            "fontVariantNumeric": "tabular-nums",
                            "textAlign": "right",
                        }
                    ],
                    style_data_conditional=[
                        {
                            "if": {
                                "filter_query": f"{{{column}}} < 0",
                                "column_id": column,
                            },
                            "color": "#B42318",
                        }
                        for column in ("Risk", "dRisk", "PL")
                    ],
                ),
                className="unmapped-table-wrap",
            ),
        ]
    )


def build_layout(
    risk_data: pd.DataFrame,
    initial_snapshot: ControlSnapshotProtocol | RefreshSnapshotProtocol | None = None,
    *,
    refresh_enabled: bool = False,
    stage_delays: Mapping[str, float] | None = None,
    include_shared_refresh_shell: bool = True,
) -> html.Div:
    """Build the application layout without registering routes or callbacks."""
    risk_values = ordered_unique(risk_data, "risk type")
    risk_options = [{"label": value, "value": value} for value in risk_values]
    split_options = [
        {"label": value, "value": value} for value in ordered_unique(risk_data, "split")
    ]
    expanded_metric_options = [
        {"label": metric_title(value), "value": value} for value in EXPANDABLE_METRICS
    ]
    detail_measure_options = [
        {"label": metric_title(value), "value": value} for value in DETAIL_MEASURES
    ]
    detail_component_options = [
        {"label": DETAIL_COMPONENT_LABELS[value], "value": value}
        for value in DETAIL_COMPONENTS["risk"]
    ]
    detail_tenor_options, _ = detail_tenor_view_state(pd.DataFrame(), "auto")
    view_dimension_options = [
        {"label": field.label, "value": field.key} for field in VIEW_DIMENSION_FIELDS
    ]

    initial_filter_values = default_risk_filter_values(risk_data)
    initial_filter_payload = default_risk_filter_payload(risk_data)
    dimension_filter_controls = [
        html.Div(
            [
                html.Label(field.label, htmlFor=DIMENSION_FILTER_IDS[field.key]),
                dcc.Dropdown(
                    id=DIMENSION_FILTER_IDS[field.key],
                    options=[
                        {"label": value, "value": value}
                        for value in ordered_unique(risk_data, field.key)
                    ],
                    multi=True,
                    placeholder=f"All {field.label.casefold()} values",
                    value=list(initial_filter_values[index]),
                ),
            ],
            className="control-field",
        )
        for index, field in enumerate(RISK_FILTER_DIMENSION_FIELDS)
    ]
    initial_risk_type = risk_options[0]["value"]
    initial_ir_family = "delta" if initial_risk_type == "IR" else None
    default_filtered = apply_filters(
        risk_data,
        [],
        [],
        initial_filter_payload,
    )
    initial_risk_frame = default_filtered.loc[
        default_filtered["risk type"].eq(initial_risk_type)
    ]
    initial_risk_frame = filter_ir_family(
        initial_risk_frame,
        initial_risk_type,
        initial_ir_family,
    )
    if initial_risk_type == "Credit":
        initial_risk_frame = apply_credit_measure(
            initial_risk_frame,
            CREDIT_MEASURES[0],
        )
    initial_open_rows = default_open_rows(initial_risk_frame, initial_risk_type)
    # The mounted callbacks own both tables and fire from the committed
    # revision Store. Building them here as well doubles the largest initial
    # component work and response payload for no durable result.
    initial_risk_table = html.Div(
        "Loading Risk Explorer…",
        className="risk-grid-placeholder",
        role="status",
    )
    initial_aggregate_table = html.Div(
        "Loading Aggregate P&L…",
        className="aggregate-pl-placeholder",
        role="status",
    )
    return html.Div(
        [
            (
                build_shared_refresh_shell(
                    initial_snapshot,
                    refresh_enabled=refresh_enabled,
                    stage_delays=stage_delays,
                )
                if include_shared_refresh_shell
                else None
            ),
            dcc.Store(
                id="open-rows-store",
                data=initial_open_rows,
            ),
            # Renderers listen to this synchronized context rather than the raw
            # risk tabs. A tab change can therefore update the Greek choices,
            # default open rows and selection state before expensive tables run.
            dcc.Store(id="risk-view-context-store", data=None),
            # Aggregate P&L waits for this one-shot handoff so its first large
            # groupby cannot compete with the initial Risk table render.
            dcc.Store(id="risk-initial-render-ready", data=None),
            # Dynamic hierarchy controls publish small delegated DOM actions to
            # these stable stores. Keeping per-row/per-cell Dash IDs out of the
            # rendered tables prevents the callback graph from being remounted
            # whenever a large risk hierarchy is replaced.
            dcc.Store(id="risk-row-action-store", data=None),
            dcc.Store(id="risk-cell-action-store", data=None),
            dcc.Store(id="risk-metric-action-store", data=None),
            dcc.Store(id="aggregate-open-risk-types", data=[]),
            dcc.Store(
                id="dimension-filter-values-store",
                # This Store is positional because the Risk reducer binds it to
                # RISK_FILTER_DIMENSION_FIELDS with ``zip(..., strict=True)``. Its
                # initial value must match the dropdowns exactly; the old
                # mapping briefly turned field names into character filters and
                # could replace a warm table with an empty render during mount.
                data=[list(value) for value in initial_filter_values],
            ),
            dcc.Store(id="risk-filter-exclude-applied-store", data=[]),
            dcc.Store(id="selected-cell-store", data=None),
            html.Div(
                [
                    dcc.Checklist(
                        id="expanded-metrics",
                        options=expanded_metric_options,
                        value=[],
                    ),
                ],
                style={"display": "none"},
            ),
            html.H1("Cube Risk & PL", className="sr-only"),
            # New top-level controls: dates/readiness, dimension filters, quick search
            html.Details(
                [
                    html.Summary(
                        "Dates and readiness",
                        className="aux-summary risk-readiness-summary",
                    ),
                    html.Div(
                        [
                            html.Div(
                                build_risk_date_editor(
                                    initial_snapshot,
                                    {
                                        str(source): pd.Timestamp(value)
                                        .date()
                                        .isoformat()
                                        for source, value in initial_snapshot.forced_dates.items()
                                    }
                                    if initial_snapshot is not None
                                    else None,
                                ),
                                id="risk-date-editor",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        "All date settings are applied.",
                                        id="force-risk-edit-status",
                                        className="force-risk-edit-status",
                                        **{"aria-live": "polite"},
                                    ),
                                    html.Div(
                                        [
                                            html.Button(
                                                "Cancel",
                                                id="force-risk-cancel-button",
                                                n_clicks=0,
                                                disabled=True,
                                                className="force-risk-cancel-button",
                                            ),
                                            html.Button(
                                                "Apply date settings",
                                                id="force-risk-apply-button",
                                                n_clicks=0,
                                                disabled=True,
                                                className="force-risk-apply-button",
                                            ),
                                        ],
                                        className="force-risk-action-buttons",
                                    ),
                                ],
                                className="force-risk-actions",
                            ),
                        ],
                    ),
                ],
                open=False,
                className="aux-details risk-readiness-details top-controls",
            )
            if refresh_enabled
            else None,
            build_saved_filter_view_bar(
                RISK_SAVED_VIEW_CONTROLS,
                filter_note=RISK_FILTER_NOTE,
                filter_bar=html.Div(
                    [
                        html.Div(
                            [
                                *dimension_filter_controls,
                                dcc.Checklist(
                                    id="risk-filter-exclude-selected",
                                    options=[
                                        {
                                            "label": (
                                                "Exclude rows matching any selected value"
                                            ),
                                            "value": "exclude",
                                        }
                                    ],
                                    value=[],
                                    className=("risk-filter-mode filter-mode-control"),
                                ),
                            ],
                            className="controls filter-controls",
                        ),
                    ],
                    className="dimension-filter-bar top-controls",
                ),
            )
            if refresh_enabled
            else None,
            html.Details(
                [
                    html.Summary(
                        [
                            html.Span(
                                "Aggregate P&L", className="risk-workspace-title"
                            ),
                            html.Span(
                                "Aggregate · Quick Risk · Quick Market · Promotions",
                                className="risk-workspace-summary-note",
                            ),
                        ],
                        className="risk-workspace-summary",
                    ),
                    dcc.Tabs(
                        id="risk-workspace-tabs",
                        value="aggregate-pl",
                        children=[
                            dcc.Tab(
                                label="Aggregate P&L",
                                value="aggregate-pl",
                                children=html.Div(
                                    [
                                        html.Div(
                                            [
                                                html.Div(
                                                    "View by",
                                                    className="aggregate-pl-title",
                                                ),
                                                dcc.RadioItems(
                                                    id="aggregate-pl-dimension",
                                                    options=view_dimension_options,
                                                    value=DEFAULT_VIEW_DIMENSION,
                                                    inline=True,
                                                    className="aggregate-pl-selector",
                                                ),
                                            ],
                                            className="aggregate-pl-header",
                                        ),
                                        html.Div(
                                            dcc.Loading(
                                                html.Div(
                                                    initial_aggregate_table,
                                                    id="aggregate-pl-grid",
                                                ),
                                                custom_spinner=build_cube_loader(
                                                    "Loading aggregate P&L"
                                                ),
                                                delay_show=120,
                                                className="cube-loading-boundary",
                                            ),
                                            className="aggregate-pl-panel",
                                        ),
                                    ],
                                    className="risk-workspace-tab-panel",
                                ),
                            ),
                            dcc.Tab(
                                label="· Quick Risk",
                                value="quick-risk",
                                children=build_quick_search(embedded=True)
                                if refresh_enabled
                                else html.Div(
                                    "Quick Risk is available after the first committed refresh.",
                                    className="empty-state",
                                ),
                            ),
                            dcc.Tab(
                                label="· Quick Market",
                                value="quick-market",
                                children=build_quick_market_search(embedded=True)
                                if refresh_enabled
                                else html.Div(
                                    "Quick Market is available after the first committed refresh.",
                                    className="empty-state",
                                ),
                            ),
                            dcc.Tab(
                                label="· Top Promotions",
                                value="top-promotions",
                                children=html.Div(
                                    [
                                        html.Div(
                                            [
                                                html.Div(
                                                    [
                                                        html.H2("Top Promotions"),
                                                        html.P(
                                                            "A flat rank of eligible committed promotions. "
                                                            "Vol Score comes directly from the Risk connector."
                                                        ),
                                                    ],
                                                    className="top-promotions-heading-copy",
                                                ),
                                                html.Div(
                                                    [
                                                        html.Label(
                                                            "Connector signal",
                                                            htmlFor="top-promotions-signal",
                                                            className="eyebrow",
                                                        ),
                                                        dcc.Dropdown(
                                                            id="top-promotions-signal",
                                                            options=[
                                                                {
                                                                    "label": label,
                                                                    "value": value,
                                                                }
                                                                for value, label in TOP_PROMOTION_SIGNALS.items()
                                                            ],
                                                            value="vol-score",
                                                            clearable=False,
                                                            searchable=False,
                                                        ),
                                                    ],
                                                    className="top-promotions-rank-control",
                                                ),
                                            ],
                                            className="top-promotions-header",
                                        ),
                                        html.Div(
                                            "Select Top Promotions to read the committed rank.",
                                            id="top-promotions-status",
                                            className="top-promotions-status",
                                            role="status",
                                        ),
                                        dcc.Loading(
                                            html.Div(id="top-promotions-grid"),
                                            custom_spinner=build_cube_loader(
                                                "Loading top promotions"
                                            ),
                                            delay_show=120,
                                            className="cube-loading-boundary",
                                        ),
                                    ],
                                    className=(
                                        "risk-workspace-tab-panel top-promotions-panel"
                                    ),
                                ),
                            ),
                        ],
                        className="workspace-tabs risk-workspace-tabs",
                    ),
                ],
                id="ag-pl-details",
                open=True,
                className="aux-details ag-pl-details",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div("Risk explorer", className="section-title"),
                            html.Div(
                                "Switch layout and reporting dimension without losing your filters.",
                                className="section-note",
                            ),
                        ],
                        className="section-heading",
                    ),
                    dcc.Tabs(
                        id="table-view-tabs",
                        value="main",
                        children=[
                            dcc.Tab(label="Cross", value="main"),
                            dcc.Tab(label="SplitVA", value="alt"),
                        ],
                        className="workspace-tabs view-mode-tabs",
                    ),
                    html.Div(
                        [
                            html.Span("Dimension", className="table-dimension-label"),
                            dcc.RadioItems(
                                id="table-dimension",
                                options=view_dimension_options,
                                value=DEFAULT_VIEW_DIMENSION,
                                inline=True,
                                className="table-dimension-selector",
                            ),
                        ],
                        className="table-dimension-control",
                    ),
                ],
                className="workspace-toolbar",
            ),
            dcc.Tabs(
                id="risk-type-tabs",
                value=risk_options[0]["value"],
                children=[
                    dcc.Tab(label=option["label"], value=option["value"])
                    for option in risk_options
                ],
                className="workspace-tabs risk-type-tabs",
            ),
            html.Div(
                [
                    dcc.Tabs(
                        id="credit-view-tabs",
                        value="single",
                        children=[
                            dcc.Tab(label="Single", value="single"),
                            dcc.Tab(label="Multi", value="multi"),
                        ],
                        className="workspace-tabs credit-view-tabs",
                    ),
                    html.Div(
                        [
                            html.Label("Credit measure", htmlFor="credit-measure"),
                            dcc.Dropdown(
                                id="credit-measure",
                                options=[
                                    {"label": measure, "value": measure}
                                    for measure in CREDIT_MEASURES
                                ],
                                value=CREDIT_MEASURES[0],
                                clearable=False,
                            ),
                        ],
                        id="credit-single-control",
                        className="credit-measure-control",
                    ),
                    html.Div(
                        [
                            html.Span("Show", className="credit-multi-label"),
                            dcc.RadioItems(
                                id="credit-multi-metric",
                                options=[
                                    {"label": metric_title(metric), "value": metric}
                                    for metric in METRIC_COLUMNS
                                ],
                                value="risk",
                                inline=True,
                                className="credit-multi-metric",
                            ),
                        ],
                        id="credit-multi-control",
                        className="credit-measure-control",
                        style={"display": "none"},
                    ),
                ],
                id="credit-view-controls",
                className="credit-view-controls",
                style={"display": "none"},
            ),
            dcc.Tabs(
                id="ir-family-tabs",
                value="delta",
                children=[
                    dcc.Tab(label=label, value=family)
                    for family, label in IR_GREEK_FAMILY_LABELS.items()
                ],
                className="workspace-tabs ir-family-tabs",
                style={"display": "none"},
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("Split", htmlFor="split-filter"),
                            dcc.Dropdown(
                                id="split-filter",
                                options=split_options,
                                multi=True,
                                placeholder="All splits",
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label(
                                "Sort underlying by", htmlFor="underlying-sort-metric"
                            ),
                            dcc.Dropdown(
                                id="underlying-sort-metric",
                                options=[
                                    {
                                        "label": metric_title(metric),
                                        "value": metric,
                                    }
                                    for metric in UNDERLYING_SORT_METRICS
                                ],
                                value=DEFAULT_UNDERLYING_SORT_METRIC,
                                clearable=False,
                            ),
                        ],
                        className="control-field",
                    ),
                    html.Div(
                        [
                            html.Label("Options", htmlFor="risk-explorer-options"),
                            dcc.Checklist(
                                id="risk-explorer-options",
                                options=[
                                    {"label": "Region", "value": "region"},
                                    {
                                        "label": "Promotion",
                                        "value": "promotion",
                                    },
                                    {
                                        "label": "Reduced tenor",
                                        "value": "reduced-tenor",
                                    },
                                ],
                                value=["promotion"],
                                className="risk-explorer-options",
                            ),
                        ],
                        className="control-field risk-explorer-option-field",
                    ),
                    html.Div(
                        [
                            html.Span("Promotion level", className="control-label"),
                            build_promotion_generation_controls(
                                int(initial_snapshot.revision)
                                if initial_snapshot is not None
                                else 0
                            ),
                        ],
                        className="control-field risk-explorer-promotion-field",
                    ),
                ],
                className="controls",
            ),
            html.Div(
                [
                    html.Span("Show", className="alt-metric-label"),
                    dcc.RadioItems(
                        id="alt-metric",
                        options=[
                            {"label": metric_title(metric), "value": metric}
                            for metric in METRIC_COLUMNS
                        ],
                        value="risk",
                        inline=True,
                        className="alt-metric-selector",
                    ),
                ],
                id="alt-metric-control",
                className="alt-metric-control",
                style={"display": "none"},
            ),
            html.Div(
                # Keep the current hierarchy mounted while a tab switch is
                # resolved. Replacing a readable table with a spinner forces
                # a full browser layout and makes ordinary navigation feel
                # like a data refresh. Explicit Refresh Risk / Refresh PL
                # operations retain the dedicated refresh progress loader.
                html.Div(
                    initial_risk_table,
                    id="risk-grid",
                    className="risk-grid",
                ),
                id="main-risk-panel",
                className="risk-panel",
            ),
            html.Div(
                html.Div(id="alt-risk-grid", className="risk-grid"),
                id="alt-risk-panel",
                className="risk-panel",
                style={"display": "none"},
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Div(
                                [
                                    html.Label("Detail metric", htmlFor="plot-measure"),
                                    dcc.Dropdown(
                                        id="plot-measure",
                                        options=detail_measure_options,
                                        value="risk",
                                        clearable=False,
                                    ),
                                ],
                                className="detail-plot-control",
                            ),
                            html.Div(
                                [
                                    html.Label("Series", htmlFor="plot-component"),
                                    dcc.Dropdown(
                                        id="plot-component",
                                        options=detail_component_options,
                                        value="total",
                                        clearable=False,
                                    ),
                                ],
                                className="detail-plot-control",
                            ),
                            html.Div(
                                [
                                    html.Label(
                                        "Tenor view", htmlFor="detail-tenor-view"
                                    ),
                                    dcc.Dropdown(
                                        id="detail-tenor-view",
                                        options=detail_tenor_options,
                                        value="auto",
                                        clearable=False,
                                    ),
                                ],
                                className="detail-plot-control",
                            ),
                        ],
                        className="detail-plot-controls",
                    ),
                    # Preserve the current detail while a new cell/tab context
                    # is resolved. A quiet non-animated loading label is
                    # provided by CSS on this stable output node; animated cube
                    # loaders are reserved for Risk/P&L refresh operations.
                    html.Div(id="detail-panel", className="detail-panel"),
                ],
                className="detail-shell",
            ),
            html.Details(
                [
                    html.Summary(
                        "Unmapped Books",
                        id="unmapped-books-summary",
                        n_clicks=0,
                        className="aux-summary",
                    ),
                    html.Div(id="unmapped-books-grid", className="unmapped-panel"),
                ],
                id="unmapped-books-details",
                open=False,
                className="aux-details",
                # Keep the callback graph identical in manager-backed and
                # static-data apps. Dash validates callback dependencies in
                # the browser, so conditionally removing these IDs would make
                # the unified Risk Explorer callback impossible to initialise
                # in static mode. Static apps hide the inert disclosure while
                # retaining the stable layout contract.
                hidden=not refresh_enabled,
            ),
        ],
        className="app-shell cube-app-shell",
    )


__all__ = [
    "build_layout",
    "build_risk_checker_inventory",
    "build_risk_date_editor",
    "build_unmapped_books_table",
]
