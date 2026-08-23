"""Callbacks owned exclusively by the V4 Risk Explorer Custom pivot."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping, Sequence
from uuid import uuid4

from dash import Dash, Input, Output, State, ctx, html, no_update
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from rebirth.domain.s11_riskviews import (
    BUILTIN_PIVOT_SPECS,
    CROSS_PIVOT_SPEC,
    PivotSpec,
    RiskViewRepository,
)
from rebirth.ui.s02_aggregation import apply_credit_measure, ordered_unique
from rebirth.ui.s01_constants import FILTER_DIMENSION_FIELDS
from rebirth.app.s02_contracts import RefreshManagerProtocol

from .s13_pivot import (
    build_hierarchical_pivot_table,
    compute_native_pivot,
    pivot_control_values,
    pivot_spec_from_controls,
)
from .s11_promotion import PROMOTION_GENERATION_STORE_ID
from .s02_state import risk_exclude_selected


@dataclass(frozen=True)
class RiskViewMutation:
    """Pure repository action result consumed by the Dash adapter."""

    options: tuple[dict[str, str], ...]
    selected: str | None
    command: dict[str, object] | None
    clear_name: bool
    status: str


def risk_view_options(repository: RiskViewRepository) -> tuple[dict[str, str], ...]:
    return tuple(view.option() for view in repository.list())


def pivot_command(spec: PivotSpec) -> dict[str, object]:
    """Create a small one-use command; financial rows never enter the browser."""

    return {"nonce": uuid4().hex, "pivot": spec.to_dict()}


def pivot_spec_from_command(value: object) -> PivotSpec:
    if not isinstance(value, Mapping) or set(value) != {"nonce", "pivot"}:
        raise ValueError("Custom pivot command has unexpected fields")
    nonce = value["nonce"]
    if not isinstance(nonce, str) or len(nonce) != 32:
        raise ValueError("Custom pivot command ID is invalid")
    return PivotSpec.from_dict(value["pivot"])


def mutate_risk_view(
    repository: RiskViewRepository,
    action: str,
    *,
    selected: object = None,
    name: object = "",
    pivot: PivotSpec | Mapping[str, object] = CROSS_PIVOT_SPEC,
    preset: object = "cross",
) -> RiskViewMutation:
    """Apply one bounded Custom-view action outside callback context."""

    selected_id = str(selected or "").strip().casefold() or None
    current_spec = pivot if isinstance(pivot, PivotSpec) else PivotSpec.from_dict(pivot)
    command: dict[str, object] | None = None
    clear_name = False
    normalized_action = str(action).strip().casefold()

    if normalized_action == "refresh":
        identifiers = {view.identifier for view in repository.list()}
        if selected_id not in identifiers:
            selected_id = None
        status = "Custom Risk Views are ready."
    elif normalized_action == "new":
        selected_id = None
        command = pivot_command(CROSS_PIVOT_SPEC)
        clear_name = True
        status = "New Custom view started from Cross."
    elif normalized_action in {"clone-cross", "clone-splitva"}:
        builtin = "cross" if normalized_action == "clone-cross" else "splitva"
        view = repository.clone_builtin(builtin, name)
        selected_id = view.identifier
        command = pivot_command(view.pivot)
        clear_name = True
        status = f"Saved {view.name} from {pivot_label(builtin)}."
    elif normalized_action == "edit":
        if selected_id is None:
            raise ValueError("Choose a saved Custom view before editing it")
        view = repository.update(selected_id, current_spec)
        command = pivot_command(view.pivot)
        status = f"Updated Custom view: {view.name}."
    elif normalized_action == "save-copy":
        view = repository.save_new(name, current_spec)
        selected_id = view.identifier
        command = pivot_command(view.pivot)
        clear_name = True
        status = f"Saved Custom view copy: {view.name}."
    elif normalized_action == "rename":
        if selected_id is None:
            raise ValueError("Choose a saved Custom view before renaming it")
        view = repository.rename(selected_id, name)
        selected_id = view.identifier
        command = pivot_command(view.pivot)
        clear_name = True
        status = f"Renamed Custom view: {view.name}."
    elif normalized_action == "delete":
        if selected_id is None:
            raise ValueError("Choose a saved Custom view before deleting it")
        view = repository.delete(selected_id)
        selected_id = None
        command = pivot_command(CROSS_PIVOT_SPEC)
        clear_name = True
        status = f"Deleted Custom view: {view.name}."
    elif normalized_action == "preset":
        key = str(preset or "cross").strip().casefold()
        if key not in BUILTIN_PIVOT_SPECS:
            raise ValueError("Custom pivot preset must be Cross or SplitVA")
        command = pivot_command(BUILTIN_PIVOT_SPECS[key])
        status = f"{pivot_label(key)} preset loaded."
    else:
        raise ValueError(f"Unsupported Custom Risk View action: {action!r}")

    return RiskViewMutation(
        options=risk_view_options(repository),
        selected=selected_id,
        command=command,
        clear_name=clear_name,
        status=status,
    )


def pivot_label(value: object) -> str:
    return "SplitVA" if str(value).strip().casefold() == "splitva" else "Cross"


def _filter_map(
    values: Sequence[Sequence[str] | None] | None,
) -> dict[str, list[str]]:
    selected_values = list(values or ())
    if len(selected_values) != len(FILTER_DIMENSION_FIELDS):
        selected_values = [[] for _field in FILTER_DIMENSION_FIELDS]
    return {
        field.key: list(selected or ())
        for field, selected in zip(
            FILTER_DIMENSION_FIELDS,
            selected_values,
            strict=True,
        )
    }


def pivot_filter_status(
    field: object,
    options: Sequence[Mapping[str, object]] | None,
    selected_values: Sequence[object] | None,
) -> str:
    """Describe the current local pivot limit from settled control values."""

    if not str(field or "").strip():
        return "Choose a field, then select values."
    available = {
        str(option.get("value"))
        for option in options or ()
        if isinstance(option, Mapping) and option.get("value") is not None
    }
    selected = {
        str(value) for value in selected_values or () if str(value) in available
    }
    if selected:
        return f"{len(selected):,} selected; this limit applies immediately."
    return f"{len(available):,} available; no local limit applied."


def register_pivot_callbacks(
    app: Dash,
    cache: Any,
    refresh_manager: RefreshManagerProtocol | None,
    repository: RiskViewRepository,
) -> None:
    """Register Custom-pivot callbacks without owning any other page outputs."""

    @app.callback(
        Output("risk-custom-view-selector", "options"),
        Output("risk-custom-view-selector", "value"),
        Output("risk-custom-view-name", "value"),
        Output("risk-custom-view-status", "children"),
        Output("risk-custom-pivot-command", "data"),
        Input("risk-custom-view-refresh", "n_intervals"),
        Input("risk-custom-view-selector", "value"),
        Input("risk-custom-view-new", "n_clicks"),
        Input("risk-custom-view-clone-cross", "n_clicks"),
        Input("risk-custom-view-clone-splitva", "n_clicks"),
        Input("risk-custom-view-edit", "n_clicks"),
        Input("risk-custom-view-save-copy", "n_clicks"),
        Input("risk-custom-view-rename", "n_clicks"),
        Input("risk-custom-view-delete", "n_clicks"),
        Input("risk-pivot-use-preset", "n_clicks"),
        State("risk-custom-view-name", "value"),
        State("risk-custom-pivot-applied", "data"),
        State("risk-pivot-preset", "value"),
        prevent_initial_call=True,
    )
    def mutate_saved_custom_views(
        _refresh,
        selected,
        _new,
        _clone_cross,
        _clone_splitva,
        _edit,
        _save_copy,
        _rename,
        _delete,
        _preset_clicks,
        name,
        applied,
        preset,
    ):
        try:
            triggered = ctx.triggered_id
        except MissingCallbackContextException:
            triggered = "risk-custom-view-refresh"
        actions = {
            "risk-custom-view-refresh": "refresh",
            "risk-custom-view-new": "new",
            "risk-custom-view-clone-cross": "clone-cross",
            "risk-custom-view-clone-splitva": "clone-splitva",
            "risk-custom-view-edit": "edit",
            "risk-custom-view-save-copy": "save-copy",
            "risk-custom-view-rename": "rename",
            "risk-custom-view-delete": "delete",
            "risk-pivot-use-preset": "preset",
        }
        try:
            if triggered == "risk-custom-view-selector":
                if not selected:
                    return (
                        no_update,
                        no_update,
                        no_update,
                        "New unsaved Custom view is active.",
                        no_update,
                    )
                view = repository.get(selected)
                return (
                    no_update,
                    no_update,
                    no_update,
                    f"Loaded Custom view: {view.name}.",
                    pivot_command(view.pivot),
                )
            result = mutate_risk_view(
                repository,
                actions.get(str(triggered), "refresh"),
                selected=selected,
                name=name,
                pivot=applied,
                preset=preset,
            )
            return (
                list(result.options),
                result.selected,
                "" if result.clear_name else no_update,
                result.status,
                result.command if result.command is not None else no_update,
            )
        except (OSError, TimeoutError, TypeError, ValueError) as error:
            try:
                options: object = list(risk_view_options(repository))
            except (OSError, ValueError):
                options = no_update
            return (
                options,
                no_update,
                no_update,
                f"Could not update Custom Risk Views: {error}",
                no_update,
            )

    @app.callback(
        Output("risk-custom-pivot-applied", "data"),
        Output("risk-pivot-rows", "value"),
        Output("risk-pivot-columns", "value"),
        Output("risk-pivot-measures", "value"),
        Output("risk-pivot-filter-field", "value"),
        Output("risk-pivot-filter-command-values", "data"),
        Output("risk-pivot-sort-field", "value"),
        Output("risk-pivot-sort-direction", "value"),
        Output("risk-pivot-totals", "value"),
        Output("risk-pivot-row-limit", "value"),
        Output("risk-pivot-column-limit", "value"),
        Output("risk-pivot-density", "value"),
        Output("risk-pivot-display-flags", "value"),
        Output("risk-pivot-editor-status", "children"),
        Input("risk-custom-pivot-command", "data"),
        Input("risk-pivot-apply", "n_clicks"),
        Input("risk-pivot-filter-values", "value"),
        State("risk-pivot-rows", "value"),
        State("risk-pivot-columns", "value"),
        State("risk-pivot-measures", "value"),
        State("risk-pivot-filter-field", "value"),
        State("risk-pivot-sort-field", "value"),
        State("risk-pivot-sort-direction", "value"),
        State("risk-pivot-totals", "value"),
        State("risk-pivot-row-limit", "value"),
        State("risk-pivot-column-limit", "value"),
        State("risk-pivot-density", "value"),
        State("risk-pivot-display-flags", "value"),
        prevent_initial_call=True,
    )
    def manage_pivot_editor(
        command,
        _apply_clicks,
        filter_values,
        rows,
        columns,
        measures,
        filter_field,
        sort_field,
        sort_direction,
        totals,
        row_limit,
        column_limit,
        density,
        display_flags,
    ):
        try:
            triggered = ctx.triggered_id
        except MissingCallbackContextException:
            triggered = "risk-custom-pivot-command"
        if triggered in {"risk-pivot-apply", "risk-pivot-filter-values"}:
            try:
                spec = pivot_spec_from_controls(
                    rows=rows,
                    columns=columns,
                    measures=measures,
                    filter_field=filter_field,
                    filter_values=filter_values,
                    sort_field=sort_field,
                    sort_direction=sort_direction,
                    totals=totals,
                    row_limit=row_limit,
                    column_limit=column_limit,
                    density=density,
                    display_flags=display_flags,
                )
            except (OverflowError, TypeError, ValueError) as error:
                return (
                    no_update,
                    *([no_update] * 12),
                    f"Pivot not applied: {error}",
                )
            return (
                spec.to_dict(),
                *([no_update] * 12),
                (
                    "Filter applied immediately."
                    if triggered == "risk-pivot-filter-values"
                    else "Custom view updated."
                ),
            )
        try:
            spec = pivot_spec_from_command(command)
        except (TypeError, ValueError) as error:
            raise PreventUpdate from error
        return (
            spec.to_dict(),
            *pivot_control_values(spec),
            "Loaded. Edit fields and select Update table when ready.",
        )

    @app.callback(
        Output("risk-pivot-filter-values", "options"),
        Output("risk-pivot-filter-values", "value"),
        Input("risk-pivot-filter-field", "value"),
        Input("risk-pivot-filter-command-values", "data"),
        Input("risk-type-tabs", "value"),
        Input("ir-family-tabs", "value"),
        Input("data-revision-store", "data"),
        Input("split-filter", "value"),
        Input("dimension-filter-values-store", "data"),
        Input("risk-filter-exclude-selected", "value"),
        Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
        State("risk-pivot-filter-values", "value"),
        prevent_initial_call=True,
    )
    def load_pivot_filter_values(
        field,
        command_values,
        risk_type,
        ir_family,
        _revision,
        splits,
        dimension_values,
        exclude_value,
        promotion_generation,
        current_values,
    ):
        selected_field = str(field or "").strip().casefold()
        if not selected_field:
            return [], []
        try:
            frame = cache.filtered(
                refresh_manager,
                risk_type,
                ir_family,
                splits,
                _filter_map(dimension_values),
                exclude_selected=risk_exclude_selected(exclude_value),
                promotion_generation=promotion_generation,
            )
            values = ordered_unique(frame, selected_field)
        except (KeyError, TypeError, ValueError):
            return [], []
        options = [{"label": value, "value": value} for value in values]
        try:
            triggered = ctx.triggered_id
        except MissingCallbackContextException:
            triggered = None
        if triggered == "risk-pivot-filter-command-values":
            requested = command_values or ()
        elif triggered == "risk-pivot-filter-field":
            requested = ()
        else:
            requested = current_values or ()
        available = set(values)
        selected = [value for value in requested if value in available]
        return options, selected

    @app.callback(
        Output("risk-pivot-filter-status", "children"),
        Input("risk-pivot-filter-field", "value"),
        Input("risk-pivot-filter-values", "options"),
        Input("risk-pivot-filter-values", "value"),
    )
    def render_pivot_filter_status(field, options, selected_values):
        return pivot_filter_status(field, options, selected_values)

    @app.callback(
        Output("risk-pivot-dirty-status", "children"),
        Output("risk-pivot-apply", "className"),
        Input("risk-pivot-rows", "value"),
        Input("risk-pivot-columns", "value"),
        Input("risk-pivot-measures", "value"),
        Input("risk-pivot-filter-field", "value"),
        Input("risk-pivot-filter-values", "value"),
        Input("risk-pivot-sort-field", "value"),
        Input("risk-pivot-sort-direction", "value"),
        Input("risk-pivot-totals", "value"),
        Input("risk-pivot-row-limit", "value"),
        Input("risk-pivot-column-limit", "value"),
        Input("risk-pivot-density", "value"),
        Input("risk-pivot-display-flags", "value"),
        Input("risk-custom-pivot-applied", "data"),
    )
    def mark_pivot_editor_state(
        rows,
        columns,
        measures,
        filter_field,
        filter_values,
        sort_field,
        sort_direction,
        totals,
        row_limit,
        column_limit,
        density,
        display_flags,
        applied,
    ):
        try:
            draft = pivot_spec_from_controls(
                rows=rows,
                columns=columns,
                measures=measures,
                filter_field=filter_field,
                filter_values=filter_values,
                sort_field=sort_field,
                sort_direction=sort_direction,
                totals=totals,
                row_limit=row_limit,
                column_limit=column_limit,
                density=density,
                display_flags=display_flags,
            )
            current = PivotSpec.from_dict(applied)
        except (OverflowError, TypeError, ValueError) as error:
            return f"Cannot update yet: {error}", "refresh-button has-errors"
        if draft == current:
            return "Table is up to date.", "refresh-button"
        return (
            "Changes waiting — select Update table.",
            "refresh-button is-dirty",
        )

    @app.callback(
        Output("risk-custom-grid", "children"),
        Output("risk-pivot-viewport-status", "children"),
        Output("risk-pivot-row-page", "max"),
        Output("risk-pivot-column-page", "max"),
        Output("risk-custom-view-token", "data"),
        Input("table-view-tabs", "value"),
        Input("risk-custom-pivot-applied", "data"),
        Input("risk-pivot-row-page", "value"),
        Input("risk-pivot-column-page", "value"),
        Input("risk-type-tabs", "value"),
        Input("ir-family-tabs", "value"),
        Input("data-revision-store", "data"),
        Input("split-filter", "value"),
        Input("dimension-filter-values-store", "data"),
        Input("risk-filter-exclude-selected", "value"),
        Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
        Input("credit-measure", "value"),
        Input("risk-custom-open-rows", "data"),
        prevent_initial_call=True,
    )
    def render_custom_pivot(
        table_view,
        applied,
        row_page,
        column_page,
        risk_type,
        ir_family,
        _revision,
        splits,
        dimension_values,
        exclude_value,
        promotion_generation,
        credit_measure,
        open_rows,
    ):
        if table_view != "custom":
            raise PreventUpdate
        started = perf_counter()
        try:
            spec = PivotSpec.from_dict(applied)
            frame = cache.filtered(
                refresh_manager,
                risk_type,
                ir_family,
                splits,
                _filter_map(dimension_values),
                exclude_selected=risk_exclude_selected(exclude_value),
                promotion_generation=promotion_generation,
            )
            if risk_type == "Credit":
                frame = apply_credit_measure(frame, credit_measure)
            render_basis = {
                "kind": "custom-pivot",
                "revision": cache.revision,
                "risk_type": risk_type,
                "ir_family": ir_family if risk_type == "IR" else None,
                "splits": sorted(splits or ()),
                "filters": _filter_map(dimension_values),
                "exclude": risk_exclude_selected(exclude_value),
                "promotion": (
                    promotion_generation.get("id")
                    if isinstance(promotion_generation, Mapping)
                    else None
                ),
                "credit_measure": credit_measure if risk_type == "Credit" else None,
                "pivot": spec.to_dict(),
                "row_page": row_page,
                "column_page": column_page,
            }
            serialized_basis = json.dumps(
                render_basis,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )
            view_token = hashlib.sha256(serialized_basis.encode("utf-8")).hexdigest()[
                :24
            ]
            render_key = json.dumps(
                {
                    **render_basis,
                    "open_rows": sorted(set(open_rows or ())),
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            )

            def build_render():
                result = compute_native_pivot(
                    frame,
                    spec,
                    row_page=max(1, int(row_page or 1)),
                    column_page=max(1, int(column_page or 1)),
                )
                row_start = result.row_offset + 1 if result.row_count else 0
                row_end = result.row_offset + len(result.row_keys)
                column_start = result.column_offset + 1 if result.column_count else 0
                column_end = result.column_offset + len(result.column_keys)
                status = (
                    f"Leaf rows {row_start:,}–{row_end:,} of {result.row_count:,} · "
                    f"Columns {column_start:,}–{column_end:,} of "
                    f"{result.column_count:,} · Use chevrons to expand groups"
                )
                return (
                    build_hierarchical_pivot_table(
                        frame,
                        result,
                        open_rows=open_rows,
                        view_token=view_token,
                    ),
                    status,
                    result.row_page_count,
                    result.column_page_count,
                    view_token,
                )

            rendered = cache.rendered(render_key, build_render)
            elapsed_ms = (perf_counter() - started) * 1_000.0
            app.logger.info(
                "risk.custom_pivot rendered revision=%s rows=%s elapsed_ms=%.1f",
                cache.revision,
                len(frame),
                elapsed_ms,
            )
            return rendered
        except (KeyError, OverflowError, TypeError, ValueError) as error:
            app.logger.exception("risk.custom_pivot failed")
            return (
                html.Div(str(error), className="empty-state", role="alert"),
                "Custom pivot could not be rendered.",
                1,
                1,
                no_update,
            )

    @app.callback(
        Output("risk-custom-open-rows", "data"),
        Input("risk-row-action-store", "data"),
        State("risk-custom-view-token", "data"),
        prevent_initial_call=True,
    )
    def apply_custom_row_action(action, view_token):
        if not isinstance(action, Mapping):
            raise PreventUpdate
        opened = action.get("open_rows")
        if (
            action.get("kind") != "row"
            or action.get("source") != "custom-row-toggle"
            or action.get("view_token") != view_token
            or not isinstance(opened, list)
            or len(opened) > 1_000
            or any(not isinstance(value, str) or len(value) > 4_096 for value in opened)
        ):
            raise PreventUpdate
        return sorted(set(opened))


__all__ = [
    "RiskViewMutation",
    "mutate_risk_view",
    "pivot_command",
    "pivot_filter_status",
    "pivot_spec_from_command",
    "register_pivot_callbacks",
    "risk_view_options",
]
