"""Callbacks for governed V4 P&L adjustment, editing, and sending."""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from dash import Dash, Input, Output, Patch, State, ctx, no_update
from dash.exceptions import PreventUpdate

from rebirth.domain.s08_pnl import (
    ADJUSTMENT,
    MARKET_DATE,
    PL_SEND_COLUMNS,
    PORTFOLIO,
    SIGNOFF_GROUP,
    collapse_pl_send_rows,
    load_plsend_mapping,
)
from rebirth.app.s02_contracts import RefreshManagerProtocol

from .s01_common import (
    DISPLAY_COLUMNS,
    GRID_ROW_ID,
    PL_FILTER_EXCLUDE_ID,
    PL_FILTER_FIELDS,
    PL_FILTER_IDS,
    PLSendConfig,
    SendFunction,
)
from .s02_editor import (
    _allowed_portfolios,
    _baseline_editor_records,
    _domain_frame,
    _draft_key,
    _drafts_with_scope,
    _editor_dropdowns,
    _effective_rows,
    _effective_store,
    _filtered_store_governance,
    _govern_current_editor_records,
    _governance,
    _matching_draft_rows,
    _merge_and_persist_adjustments,
    _new_editor_row,
    _pl_filter_scope,
    _require_current_filter_scope,
)


_SELECTION_SUMMARY_SCRIPT = r"""
function (selectedCells, rows) {
    if (!Array.isArray(selectedCells) || selectedCells.length < 2) {
        return ["", true];
    }
    var records = Array.isArray(rows) ? rows : [];
    var numbers = selectedCells.filter(function (cell) {
        return cell.column_id === "PL";
    }).map(function (cell) {
        var record = records[cell.row] || {};
        var value = record[cell.column_id];
        if (value === null || value === undefined || value === ""
            || typeof value === "boolean") {
            return null;
        }
        if (typeof value === "number") {
            return Number.isFinite(value) ? value : null;
        }
        var normalized = String(value).replace(/[£€¥,\s]/g, "");
        if (!normalized) return null;
        var parsed = Number(normalized);
        return Number.isFinite(parsed) ? parsed : null;
    }).filter(function (value) { return value !== null; });
    if (!numbers.length) {
        return [selectedCells.length + " cells selected · no PL values", false];
    }
    var sum = numbers.reduce(function (total, value) { return total + value; }, 0);
    var format = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
    return [selectedCells.length + " cells selected · "
        + numbers.length + " PL · Sum " + format.format(sum)
        + " · Average " + format.format(sum / numbers.length)
        + " · Min " + format.format(Math.min.apply(null, numbers))
        + " · Max " + format.format(Math.max.apply(null, numbers)), false];
}
"""

_CLEAR_SELECTION_SCRIPT = r"""
function (_nClicks, _scope, _effectiveStore) {
    return [[], null];
}
"""


def register_pl_send_callbacks(
    app: Dash,
    refresh_manager: RefreshManagerProtocol,
    config: PLSendConfig,
) -> None:
    """Register effective-row editors and governed send actions."""

    def current_pl_snapshot():
        """Return None only while this worker has no committed revision yet."""
        try:
            return refresh_manager.pl_snapshot
        except RuntimeError:
            if int(refresh_manager.health.revision) <= 0:
                return None
            raise

    def register_effective_store(
        *,
        store_id: str,
        toggle_id: str,
        section_revision_id: str,
        summary_id: str,
        filter_id: str,
        scope_column: str,
    ) -> None:
        @app.callback(
            Output(store_id, "data"),
            Output(filter_id, "options"),
            Output(filter_id, "value"),
            Input(summary_id, "n_clicks"),
            Input("data-revision-store", "data"),
            Input(toggle_id, "value"),
            Input(section_revision_id, "data"),
            *[Input(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
            Input(PL_FILTER_EXCLUDE_ID, "value"),
            State(filter_id, "value"),
            prevent_initial_call=True,
        )
        def refresh_effective_store(
            summary_clicks,
            _revision,
            include_values,
            section_revision,
            *filter_values_mode_and_scope,
        ):
            filter_values = filter_values_mode_and_scope[: len(PL_FILTER_FIELDS)]
            exclude_value = filter_values_mode_and_scope[len(PL_FILTER_FIELDS)]
            selected_scope = filter_values_mode_and_scope[-1]
            if not int(summary_clicks or 0) % 2:
                return {}, no_update, no_update
            snapshot = current_pl_snapshot()
            if snapshot is None:
                return {}, [], None
            effective, _mapping, filtered_governance = _effective_rows(
                snapshot,
                config,
                include_adjustments="include" in (include_values or []),
                filter_values=filter_values,
                exclude_value=exclude_value,
            )
            values = sorted(effective[scope_column].astype(str).unique().tolist())
            selected = (
                selected_scope
                if selected_scope in values
                else (values[0] if values else None)
            )
            return (
                _effective_store(
                    snapshot,
                    effective,
                    filtered_governance=filtered_governance,
                    filter_scope=_pl_filter_scope(filter_values, exclude_value),
                    include_adjustments="include" in (include_values or []),
                    editor_epoch=int(section_revision or 0),
                ),
                [{"label": value, "value": value} for value in values],
                selected,
            )

    register_effective_store(
        store_id="pl-send-sog-effective-store",
        toggle_id="pl-sog-include-adjustments",
        section_revision_id="pl-sog-adjustment-revision-store",
        summary_id="pl-sog-summary",
        filter_id="pl-send-sog-filter",
        scope_column=SIGNOFF_GROUP,
    )
    register_effective_store(
        store_id="pl-send-portfolio-effective-store",
        toggle_id="pl-portfolio-include-adjustments",
        section_revision_id="pl-portfolio-adjustment-revision-store",
        summary_id="pl-portfolio-summary",
        filter_id="pl-send-portfolio-filter",
        scope_column=PORTFOLIO,
    )

    def register_editor(
        *,
        store_id: str,
        table_id: str,
        filter_id: str,
        add_id: str,
        draft_store_id: str,
        active_scope_store_id: str,
        scope_column: str,
        portfolio_editable: bool,
        save_id: str,
        send_id: str,
    ) -> None:
        @app.callback(
            Output(table_id, "data"),
            Output(table_id, "dropdown"),
            Output(table_id, "dropdown_conditional"),
            Output(draft_store_id, "data"),
            Output(active_scope_store_id, "data"),
            Output(f"{table_id}-data-status", "children"),
            Input(store_id, "data"),
            Input(filter_id, "value"),
            Input(add_id, "n_clicks"),
            Input(table_id, "data_timestamp"),
            State(table_id, "data"),
            State(table_id, "data_previous"),
            State(draft_store_id, "data"),
            State(active_scope_store_id, "data"),
            running=[
                (Output(add_id, "disabled"), True, False),
                (Output(save_id, "disabled"), True, False),
                (Output(send_id, "disabled"), True, False),
            ],
        )
        def control_editor(
            store,
            selected_scope,
            _add_clicks,
            _data_timestamp,
            current_rows,
            _previous_rows,
            drafts,
            active_scope,
        ):
            if not store or not selected_scope:
                return (
                    [],
                    {},
                    [],
                    no_update,
                    selected_scope,
                    f"Choose a {scope_column} to load rows.",
                )

            trigger = ctx.triggered_id
            try:
                snapshot = refresh_manager.pl_snapshot
                mapping = load_plsend_mapping(config.mapping_source)
                governance = _filtered_store_governance(
                    _governance(snapshot),
                    store,
                )
                allowed = _allowed_portfolios(
                    governance,
                    scope_column=scope_column,
                    selected_scope=selected_scope,
                )
                dropdown, dropdown_conditional = _editor_dropdowns(
                    mapping,
                    allowed,
                    portfolio_editable=portfolio_editable,
                )
                scope_key = _draft_key(scope_column, selected_scope)

                def baseline_or_draft() -> list[dict[str, object]]:
                    draft_rows = _matching_draft_rows(
                        drafts,
                        store,
                        scope_key=scope_key,
                        scope_column=scope_column,
                        selected_scope=selected_scope,
                    )
                    if draft_rows is not None:
                        return _govern_current_editor_records(
                            draft_rows,
                            store,
                            mapping,
                            governance,
                            scope_column=scope_column,
                            selected_scope=selected_scope,
                        )
                    return _baseline_editor_records(
                        store,
                        mapping,
                        governance,
                        scope_column=scope_column,
                        selected_scope=selected_scope,
                    )

                if not allowed:
                    return (
                        [],
                        dropdown,
                        dropdown_conditional,
                        no_update,
                        str(selected_scope),
                        f"No governed Portfolio belongs to {selected_scope}.",
                    )

                if trigger == add_id:
                    use_current_rows = bool(current_rows) and str(
                        active_scope or ""
                    ) == str(selected_scope)
                    rows = (
                        [dict(row) for row in current_rows]
                        if use_current_rows
                        else baseline_or_draft()
                    )
                    added = _new_editor_row(
                        market_date=store["market_date"],
                        mapping=mapping,
                        governance=governance,
                        allowed_portfolios=allowed,
                    )
                    final_rows = [added, *rows]
                    updated_drafts = _drafts_with_scope(
                        drafts,
                        store,
                        final_rows,
                        scope_column=scope_column,
                        selected_scope=selected_scope,
                    )
                    if use_current_rows:
                        patch = Patch()
                        patch.prepend(added)
                        data_out = patch
                    else:
                        data_out = final_rows
                    return (
                        data_out,
                        no_update,
                        no_update,
                        updated_drafts,
                        no_update,
                        f"Draft updated · {len(final_rows):,} rows for {selected_scope}.",
                    )

                if trigger == table_id:
                    rows = [dict(row) for row in (current_rows or [])]
                    for row in rows:
                        if row.get(scope_column) in (None, ""):
                            row[scope_column] = selected_scope
                    wrong_scope = str(active_scope or "") != str(selected_scope)
                    wrong_scope = wrong_scope or any(
                        str(row.get(scope_column, "")) != str(selected_scope)
                        for row in rows
                    )
                    if wrong_scope:
                        recovered = baseline_or_draft()
                        return (
                            recovered,
                            dropdown,
                            dropdown_conditional,
                            no_update,
                            str(selected_scope),
                            f"Recovered {len(recovered):,} rows for {selected_scope} after a late edit.",
                        )

                    governed = _govern_current_editor_records(
                        rows,
                        store,
                        mapping,
                        governance,
                        scope_column=scope_column,
                        selected_scope=selected_scope,
                    )
                    patch = Patch()
                    has_patch = False
                    governed_columns = (*DISPLAY_COLUMNS, GRID_ROW_ID, MARKET_DATE)
                    for row_index, (current, final) in enumerate(zip(rows, governed)):
                        for column in governed_columns:
                            if current.get(column) != final.get(column):
                                patch[row_index][column] = final.get(column)
                                has_patch = True
                    updated_drafts = _drafts_with_scope(
                        drafts,
                        store,
                        governed,
                        scope_column=scope_column,
                        selected_scope=selected_scope,
                    )
                    return (
                        patch if has_patch else no_update,
                        no_update,
                        no_update,
                        updated_drafts,
                        no_update,
                        f"Draft updated · {len(governed):,} rows for {selected_scope}.",
                    )

                loaded = baseline_or_draft()
                message = (
                    f"Ready · {len(loaded):,} rows for {selected_scope}."
                    if loaded
                    else f"No PL rows are available for {selected_scope}."
                )
                return (
                    loaded,
                    dropdown,
                    dropdown_conditional,
                    no_update,
                    str(selected_scope),
                    message,
                )
            except Exception as exc:
                data_out = no_update if trigger in (table_id, add_id) else []
                return (
                    data_out,
                    no_update,
                    no_update,
                    no_update,
                    no_update,
                    f"Could not prepare {scope_column} rows: {exc}",
                )

        app.clientside_callback(
            _SELECTION_SUMMARY_SCRIPT,
            Output(f"{table_id}-selection-summary-text", "children"),
            Output(f"{table_id}-selection-summary", "hidden"),
            Input(table_id, "selected_cells"),
            Input(table_id, "data"),
        )
        app.clientside_callback(
            _CLEAR_SELECTION_SCRIPT,
            Output(table_id, "selected_cells"),
            Output(table_id, "active_cell"),
            Input(f"{table_id}-selection-clear", "n_clicks"),
            Input(filter_id, "value"),
            Input(store_id, "data"),
            prevent_initial_call=True,
        )

    register_editor(
        store_id="pl-send-sog-effective-store",
        table_id="pl-send-sog-grid",
        filter_id="pl-send-sog-filter",
        add_id="add-sog-pl-row",
        draft_store_id="pl-send-sog-drafts-store",
        active_scope_store_id="pl-send-sog-active-scope-store",
        scope_column=SIGNOFF_GROUP,
        portfolio_editable=True,
        save_id="save-sog-adjustments-button",
        send_id="send-sog-pl-button",
    )
    register_editor(
        store_id="pl-send-portfolio-effective-store",
        table_id="pl-send-portfolio-grid",
        filter_id="pl-send-portfolio-filter",
        add_id="add-portfolio-pl-row",
        draft_store_id="pl-send-portfolio-drafts-store",
        active_scope_store_id="pl-send-portfolio-active-scope-store",
        scope_column=PORTFOLIO,
        portfolio_editable=False,
        save_id="save-portfolio-adjustments-button",
        send_id="send-portfolio-pl-button",
    )

    @app.callback(
        Output("pl-save-sog-adjustments-status", "children"),
        Output("pl-save-portfolio-adjustments-status", "children"),
        Output("pl-adjustment-revision-store", "data"),
        Output("pl-sog-adjustment-revision-store", "data"),
        Output("pl-portfolio-adjustment-revision-store", "data"),
        Input("save-sog-adjustments-button", "n_clicks"),
        Input("save-portfolio-adjustments-button", "n_clicks"),
        State("pl-send-sog-grid", "data"),
        State("pl-send-portfolio-grid", "data"),
        State("pl-send-sog-effective-store", "data"),
        State("pl-send-portfolio-effective-store", "data"),
        State("pl-sog-adjustment-revision-store", "data"),
        State("pl-adjustment-revision-store", "data"),
        State("pl-portfolio-adjustment-revision-store", "data"),
        State("pl-send-sog-filter", "value"),
        State("pl-send-portfolio-filter", "value"),
        *[State(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        State(PL_FILTER_EXCLUDE_ID, "value"),
        prevent_initial_call=True,
    )
    def save_adjustments(
        _sog_clicks,
        _portfolio_clicks,
        sog_records,
        portfolio_records,
        sog_store,
        portfolio_store,
        adjustment_revision,
        sog_adjustment_revision,
        portfolio_adjustment_revision,
        selected_sog,
        selected_portfolio,
        *filter_values_mode,
    ):
        trigger = ctx.triggered_id
        is_sog = trigger == "save-sog-adjustments-button"
        records = sog_records if is_sog else portfolio_records
        store = sog_store if is_sog else portfolio_store
        unchanged = no_update
        try:
            snapshot = refresh_manager.pl_snapshot
            if not store:
                raise ValueError("the PL editor has not loaded")
            filter_values = filter_values_mode[: len(PL_FILTER_FIELDS)]
            exclude_value = filter_values_mode[len(PL_FILTER_FIELDS)]
            _require_current_filter_scope(store, filter_values, exclude_value)
            expected_date = pd.Timestamp(snapshot.market_date).date().isoformat()
            if int(store.get("revision", -1)) != int(snapshot.revision):
                raise ValueError("the risk snapshot changed; reload the PL editor")
            if str(store.get("market_date", "")) != expected_date:
                raise ValueError("the market date changed; reload the PL editor")
            mapping = load_plsend_mapping(config.mapping_source)
            governance = _filtered_store_governance(
                _governance(snapshot),
                store,
            )
            scope_column = SIGNOFF_GROUP if is_sog else PORTFOLIO
            selected_scope = selected_sog if is_sog else selected_portfolio
            if not selected_scope:
                raise ValueError("select a Scope before saving")
            raw_rows = _domain_frame(records)
            outside_scope = raw_rows[scope_column].astype(str).ne(str(selected_scope))
            if outside_scope.any():
                raise ValueError(
                    f"the editor contains rows outside the selected {scope_column}"
                )
            governed_records = _govern_current_editor_records(
                records,
                store,
                mapping,
                governance,
                scope_column=scope_column,
                selected_scope=selected_scope,
            )
            rows = _domain_frame(governed_records)
            adjustments = rows.loc[rows[ADJUSTMENT].eq(True)].copy()
            include_existing = bool(store.get("include_adjustments"))
            if adjustments.empty and not include_existing:
                message = "No adjustments to save."
                return (
                    message if is_sog else unchanged,
                    unchanged if is_sog else message,
                    no_update,
                    no_update,
                    no_update,
                )
            collapsed = (
                collapse_pl_send_rows(
                    adjustments,
                    mapping,
                    governance,
                    require_adjustment=True,
                )
                if not adjustments.empty
                else adjustments.reindex(columns=list(PL_SEND_COLUMNS))
            )
            if include_existing:
                if is_sog:
                    replace_portfolios = set(
                        governance.loc[
                            governance[SIGNOFF_GROUP]
                            .astype(str)
                            .eq(str(selected_scope)),
                            PORTFOLIO,
                        ]
                        .astype(str)
                        .tolist()
                    )
                else:
                    replace_portfolios = {str(selected_scope)}
            else:
                replace_portfolios = set(collapsed[PORTFOLIO].astype(str).tolist())
            _merge_and_persist_adjustments(
                config,
                collapsed,
                market_date=expected_date,
                revision=int(snapshot.revision),
                replace_portfolios=replace_portfolios,
            )
            message = (
                f"Saved {len(collapsed):,} adjustments for {expected_date}."
                if not collapsed.empty
                else f"Cleared saved adjustments for {selected_scope}."
            )
            next_revision = int(adjustment_revision or 0) + 1
            next_section_revision = (
                int(
                    sog_adjustment_revision if is_sog else portfolio_adjustment_revision
                )
                or 0
            ) + 1
            return (
                message if is_sog else unchanged,
                unchanged if is_sog else message,
                next_revision,
                (next_section_revision if is_sog else no_update),
                (next_section_revision if not is_sog else no_update),
            )
        except Exception as exc:
            message = f"Not saved: {exc}"
            return (
                message if is_sog else unchanged,
                unchanged if is_sog else message,
                no_update,
                no_update,
                no_update,
            )

    def send_rows(
        records,
        sender: SendFunction,
        store: dict[str, object],
        *,
        scope_column: str,
        selected_scope: object,
        filter_values: Sequence[Sequence[object] | None],
        exclude_value: Sequence[object] | None,
    ) -> str:
        snapshot = refresh_manager.pl_snapshot
        if not store or not selected_scope:
            raise ValueError("select a loaded scope before sending")
        expected_date = pd.Timestamp(snapshot.market_date).date().isoformat()
        if int(store.get("revision", -1)) != int(snapshot.revision):
            raise ValueError("the risk snapshot changed; reload the PL editor")
        if str(store.get("market_date", "")) != expected_date:
            raise ValueError("the market date changed; reload the PL editor")
        _require_current_filter_scope(store, filter_values, exclude_value)
        mapping = load_plsend_mapping(config.mapping_source)
        governance = _filtered_store_governance(_governance(snapshot), store)
        raw_rows = _domain_frame(records)
        outside_scope = raw_rows[scope_column].astype(str).ne(str(selected_scope))
        if outside_scope.any():
            raise ValueError(
                f"the editor contains rows outside the selected {scope_column}"
            )
        governed_records = _govern_current_editor_records(
            records,
            store,
            mapping,
            governance,
            scope_column=scope_column,
            selected_scope=selected_scope,
        )
        rows = _domain_frame(governed_records)
        if rows.empty:
            raise ValueError("there are no rows to send")
        rows = collapse_pl_send_rows(rows, mapping, governance)
        sender(rows[list(DISPLAY_COLUMNS)].copy())
        return f"success · sent {len(rows):,} governed rows"

    @app.callback(
        Output("pl-send-all-status", "children"),
        Input("send-all-pl-button", "n_clicks"),
        *[State(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        State(PL_FILTER_EXCLUDE_ID, "value"),
        prevent_initial_call=True,
        running=[(Output("send-all-pl-button", "disabled"), True, False)],
    )
    def send_all(n_clicks, *filter_values_mode):
        if not n_clicks:
            raise PreventUpdate

        try:
            snapshot = current_pl_snapshot()
            if snapshot is None:
                return "Not sent: P&L data is still loading."
            filter_values = filter_values_mode[: len(PL_FILTER_FIELDS)]
            exclude_value = filter_values_mode[len(PL_FILTER_FIELDS)]
            effective, mapping, governance = _effective_rows(
                snapshot,
                config,
                include_adjustments=True,
                filter_values=filter_values,
                exclude_value=exclude_value,
            )
            rows = collapse_pl_send_rows(effective, mapping, governance)
            if rows.empty:
                raise ValueError("there are no governed rows to send")
            payload = rows[list(DISPLAY_COLUMNS)].copy(deep=True)
        except Exception as exc:
            return f"Not sent: could not build governed P&L: {exc}"

        succeeded: list[str] = []
        failed: list[str] = []
        for label, sender in (
            ("SOG", config.send_sog_pl),
            ("Portfolio", config.send_portfolio_pl),
        ):
            try:
                sender(payload.copy(deep=True))
                succeeded.append(label)
            except Exception as exc:
                failed.append(f"{label} failed ({exc})")

        row_count = len(payload)
        if not failed:
            return f"success · sent {row_count:,} governed rows to SOG and Portfolio"
        if succeeded:
            return (
                f"Partially sent · {', '.join(succeeded)} succeeded; "
                f"{'; '.join(failed)}"
            )
        return f"Not sent · {'; '.join(failed)}"

    @app.callback(
        Output("pl-send-sog-status", "children"),
        Input("send-sog-pl-button", "n_clicks"),
        State("pl-send-sog-grid", "data"),
        State("pl-send-sog-effective-store", "data"),
        State("pl-send-sog-filter", "value"),
        *[State(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        State(PL_FILTER_EXCLUDE_ID, "value"),
        prevent_initial_call=True,
    )
    def send_sog(n_clicks, records, store, selected_scope, *filter_values_mode):
        if not n_clicks:
            raise PreventUpdate

        try:
            return send_rows(
                records,
                config.send_sog_pl,
                store,
                scope_column=SIGNOFF_GROUP,
                selected_scope=selected_scope,
                filter_values=filter_values_mode[: len(PL_FILTER_FIELDS)],
                exclude_value=filter_values_mode[len(PL_FILTER_FIELDS)],
            )
        except Exception as exc:
            return f"Not sent: {exc}"

    @app.callback(
        Output("pl-send-portfolio-status", "children"),
        Input("send-portfolio-pl-button", "n_clicks"),
        State("pl-send-portfolio-grid", "data"),
        State("pl-send-portfolio-effective-store", "data"),
        State("pl-send-portfolio-filter", "value"),
        *[State(PL_FILTER_IDS[field.key], "value") for field in PL_FILTER_FIELDS],
        State(PL_FILTER_EXCLUDE_ID, "value"),
        prevent_initial_call=True,
    )
    def send_portfolio(
        n_clicks,
        records,
        store,
        selected_scope,
        *filter_values_mode,
    ):
        if not n_clicks:
            raise PreventUpdate

        try:
            return send_rows(
                records,
                config.send_portfolio_pl,
                store,
                scope_column=PORTFOLIO,
                selected_scope=selected_scope,
                filter_values=filter_values_mode[: len(PL_FILTER_FIELDS)],
                exclude_value=filter_values_mode[len(PL_FILTER_FIELDS)],
            )
        except Exception as exc:
            return f"Not sent: {exc}"


__all__ = ["register_pl_send_callbacks"]
