"""Reusable Dash controls and callbacks for shared saved filter views."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final
from uuid import uuid4

from dash import Dash, Input, Output, State, ctx, dcc, html, no_update
from dash.exceptions import MissingCallbackContextException, PreventUpdate

from cube.domain.s01_schema import PortfolioField
from cube.services.s04_savedviews import SavedFilterView, SavedFilterViewRepository


BASE_SAVED_VIEW_ID: Final = "__base__"
BASE_SAVED_VIEW_LABEL: Final = "Base / No view"
_COMMITTED_DRAFT_VIEW_ID: Final = "__committed__"


@dataclass(frozen=True)
class SavedFilterViewControls:
    """Declare one page's IDs without sharing its browser selection state."""

    scope: str
    prefix: str
    fields: tuple[PortfolioField, ...]
    filter_ids: Mapping[str, str]
    exclude_id: str
    base_label: str = BASE_SAVED_VIEW_LABEL

    def __post_init__(self) -> None:
        field_keys = tuple(field.key for field in self.fields)
        if (
            not self.scope
            or not self.prefix
            or not self.exclude_id
            or not self.base_label
        ):
            raise ValueError("Saved filter-view control identifiers must be nonblank")
        if not field_keys or len(field_keys) != len(set(field_keys)):
            raise ValueError("Saved filter-view fields must be non-empty and unique")
        if set(self.filter_ids) != set(field_keys):
            raise ValueError("Saved filter-view filter IDs must match its field keys")
        if len(set(self.filter_ids.values())) != len(self.filter_ids):
            raise ValueError("Saved filter-view Dash IDs must be unique")

    @property
    def selector_id(self) -> str:
        return f"{self.prefix}-saved-view-selector"

    @property
    def name_id(self) -> str:
        return f"{self.prefix}-saved-view-name"

    @property
    def save_id(self) -> str:
        return f"{self.prefix}-saved-view-save"

    @property
    def delete_id(self) -> str:
        return f"{self.prefix}-saved-view-delete"

    @property
    def status_id(self) -> str:
        return f"{self.prefix}-saved-view-status"

    @property
    def current_label_id(self) -> str:
        return f"{self.prefix}-saved-view-current-label"

    @property
    def refresh_id(self) -> str:
        return f"{self.prefix}-saved-view-refresh"

    @property
    def apply_request_id(self) -> str:
        return f"{self.prefix}-saved-view-apply-request"

    @property
    def applied_request_id(self) -> str:
        return f"{self.prefix}-saved-view-applied-request"

    @property
    def committed_state_id(self) -> str:
        return f"{self.prefix}-saved-view-committed"

    @property
    def apply_id(self) -> str:
        return f"{self.prefix}-saved-view-apply"

    @property
    def cancel_id(self) -> str:
        return f"{self.prefix}-saved-view-cancel"

    @property
    def initialized_id(self) -> str:
        return f"{self.prefix}-saved-view-initialized"


def saved_view_options(
    views: Sequence[SavedFilterView],
    *,
    base_label: str = BASE_SAVED_VIEW_LABEL,
) -> list[dict[str, str]]:
    """Return Base plus deterministic named options from the shared catalogue."""

    return [
        {"label": base_label, "value": BASE_SAVED_VIEW_ID},
        *(view.option() for view in views),
    ]


def build_saved_filter_view_bar(
    controls: SavedFilterViewControls,
    *,
    initial_views: Sequence[SavedFilterView] = (),
    filter_note: str | None = None,
    filter_bar: object | None = None,
) -> html.Details:
    """Build one collapsed editor containing a page's filter authority.

    ``filter_note`` keeps page-specific include/exclude guidance inside this
    disclosure so the copy disappears whenever Saved views is closed.  A
    supplied ``filter_bar`` is mounted in the same disclosure; this keeps the
    five authoritative page selectors and their include/exclude mode out of
    sight until the user opens Saved views.
    """

    return html.Details(
        [
            dcc.Store(id=controls.apply_request_id, data=None),
            dcc.Store(id=controls.applied_request_id, data=None),
            dcc.Store(id=controls.committed_state_id, data=None),
            dcc.Store(id=controls.initialized_id, data=False),
            dcc.Interval(
                id=controls.refresh_id,
                interval=100,
                n_intervals=0,
                max_intervals=1,
            ),
            html.Summary(
                [
                    html.Span("Saved views", className="saved-view-summary-title"),
                    html.Span(
                        controls.base_label,
                        id=controls.current_label_id,
                        className="saved-view-summary-note",
                    ),
                ],
                className="saved-view-summary",
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.Label("View", htmlFor=controls.selector_id),
                            dcc.Dropdown(
                                id=controls.selector_id,
                                options=saved_view_options(
                                    initial_views,
                                    base_label=controls.base_label,
                                ),
                                value=BASE_SAVED_VIEW_ID,
                                clearable=False,
                                placeholder=controls.base_label,
                            ),
                        ],
                        className="control-field saved-view-selector-field",
                    ),
                    html.Div(
                        [
                            html.Label("New view name", htmlFor=controls.name_id),
                            dcc.Input(
                                id=controls.name_id,
                                type="text",
                                value="",
                                maxLength=80,
                                # Save samples this component as State, so every
                                # keystroke must reach Dash before an immediate click.
                                debounce=False,
                                disabled=False,
                                placeholder="Name these filters",
                            ),
                        ],
                        className="control-field saved-view-name-field",
                    ),
                    html.Div(
                        [
                            html.Label("Actions", className="saved-view-actions-label"),
                            html.Div(
                                [
                                    html.Button(
                                        "Save New",
                                        id=controls.save_id,
                                        n_clicks=0,
                                        type="button",
                                        className=(
                                            "refresh-button saved-view-save-button"
                                        ),
                                    ),
                                    html.Button(
                                        "Delete",
                                        id=controls.delete_id,
                                        n_clicks=0,
                                        type="button",
                                        disabled=True,
                                        className=(
                                            "refresh-button saved-view-delete-button"
                                        ),
                                    ),
                                ],
                                className="saved-view-actions",
                            ),
                        ],
                        className="control-field saved-view-action-field",
                    ),
                    html.Div(
                        [
                            html.Div(
                                f"{controls.base_label} is active.",
                                id=controls.status_id,
                                className="saved-view-status",
                                role="status",
                                **{"aria-live": "polite"},
                            ),
                            html.Div(
                                "Named views are shared across Risk, Stock, and P&L. "
                                "Each page keeps its own current selection. On Plotly, "
                                "filesystem changes may be lost after a restart or "
                                "redeploy.",
                                className="saved-view-persistence-note",
                            ),
                        ],
                        className="saved-view-copy",
                    ),
                    *(
                        [
                            html.Div(
                                filter_note,
                                className="filter-note saved-view-filter-note",
                            )
                        ]
                        if filter_note
                        else []
                    ),
                    *(
                        [
                            html.Div(
                                filter_bar,
                                className="saved-view-filter-bar",
                                style={"gridColumn": "1 / -1"},
                            )
                        ]
                        if filter_bar is not None
                        else []
                    ),
                    html.Div(
                        [
                            html.Span(
                                "Draft changes affect the page only after Apply.",
                                className="saved-view-draft-note",
                            ),
                            html.Div(
                                [
                                    html.Button(
                                        "Cancel changes",
                                        id=controls.cancel_id,
                                        n_clicks=0,
                                        type="button",
                                        className="action-button action-secondary",
                                    ),
                                    html.Button(
                                        "Apply filters",
                                        id=controls.apply_id,
                                        n_clicks=0,
                                        type="button",
                                        className="action-button action-primary",
                                    ),
                                ],
                                className="saved-view-form-buttons",
                            ),
                        ],
                        className="saved-view-form-actions",
                    ),
                ],
                className="saved-filter-view-panel",
            ),
        ],
        id=f"{controls.prefix}-saved-view-bar",
        open=False,
        className="saved-filter-view-disclosure top-controls",
        **{"data-saved-view-scope": controls.scope},
    )


def selected_filter_payload(
    controls: SavedFilterViewControls,
    filter_values: Sequence[Sequence[str] | None],
) -> dict[str, list[str]]:
    """Normalize page controls into the repository's exact ordered contract."""

    if len(filter_values) != len(controls.fields):
        raise ValueError("Saved filter-view values do not match its fields")
    result: dict[str, list[str]] = {}
    for field, selected in zip(controls.fields, filter_values, strict=True):
        if selected is None:
            result[field.key] = []
        elif isinstance(selected, (str, bytes)):
            raise TypeError(f"Saved filter {field.key!r} must be a sequence")
        else:
            result[field.key] = [str(value) for value in selected]
    return result


def committed_filter_state(
    controls: SavedFilterViewControls,
    selected_identifier: object,
    filter_values: Sequence[Sequence[str] | None],
    exclude_value: Sequence[str] | None,
) -> dict[str, object]:
    """Serialize the one filter state that visible page consumers may use."""

    view_id = (
        BASE_SAVED_VIEW_ID
        if is_base_saved_view(selected_identifier)
        else str(selected_identifier).strip()
    )
    if not view_id:
        raise ValueError("Committed filter view identifier must be nonblank")
    return {
        "scope": controls.scope,
        "view_id": view_id,
        "filters": selected_filter_payload(controls, filter_values),
        "exclude_selected": "exclude" in (exclude_value or []),
    }


def committed_filter_state_values(
    value: object,
    controls: SavedFilterViewControls,
) -> tuple[tuple[list[str], ...], list[str]] | None:
    """Validate the small committed Store before a page filters its data."""

    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {
        "scope",
        "view_id",
        "filters",
        "exclude_selected",
    }:
        raise ValueError("Committed filter state has unexpected fields")
    if value["scope"] != controls.scope:
        raise ValueError("Committed filter state belongs to another page")
    if not isinstance(value["view_id"], str) or not value["view_id"].strip():
        raise ValueError("Committed filter view identifier is invalid")
    raw_filters = value["filters"]
    expected_keys = {field.key for field in controls.fields}
    if not isinstance(raw_filters, Mapping) or set(raw_filters) != expected_keys:
        raise ValueError("Committed filters do not match this page")
    normalized: list[list[str]] = []
    for field in controls.fields:
        selected = raw_filters[field.key]
        if isinstance(selected, (str, bytes)) or not isinstance(selected, Sequence):
            raise ValueError(f"Committed filter {field.key!r} must be a sequence")
        if any(not isinstance(item, str) for item in selected):
            raise ValueError(f"Committed filter {field.key!r} values must be text")
        normalized.append(list(selected))
    if not isinstance(value["exclude_selected"], bool):
        raise ValueError("Committed filter mode is invalid")
    exclude_value = ["exclude"] if value["exclude_selected"] else []
    return tuple(normalized), exclude_value


def base_saved_filter_view(controls: SavedFilterViewControls) -> SavedFilterView:
    """Return the non-persisted selection that clears this page's filters."""

    return SavedFilterView(
        identifier=BASE_SAVED_VIEW_ID,
        scope=controls.scope,
        name=controls.base_label,
        filters={field.key: () for field in controls.fields},
        exclude_selected=False,
    )


def is_base_saved_view(value: object) -> bool:
    """Treat legacy empty selections as the always-present Base option."""

    return value in (None, "", BASE_SAVED_VIEW_ID)


def selected_saved_view_label(
    selected_identifier: object,
    options: object,
    *,
    base_label: str = BASE_SAVED_VIEW_LABEL,
) -> str:
    """Resolve the current view's human label from trusted Dropdown options."""

    if is_base_saved_view(selected_identifier):
        return base_label
    if isinstance(options, Sequence) and not isinstance(options, (str, bytes)):
        for option in options:
            if not isinstance(option, Mapping):
                continue
            if option.get("value") != selected_identifier:
                continue
            label = option.get("label")
            if isinstance(label, str) and label.strip():
                return label.strip()
    # A missing catalogue entry is treated exactly like the selector's own
    # invalid-value recovery: Base is the only durable selection left.
    return base_label


def saved_view_control_values(
    view: SavedFilterView,
    controls: SavedFilterViewControls,
) -> tuple[object, ...]:
    """Map one trusted repository value back to page-local Dash controls."""

    if view.scope != controls.scope:
        raise ValueError("Saved filter view belongs to another page")
    values: list[object] = [list(view.filters[field.key]) for field in controls.fields]
    values.append(["exclude"] if view.exclude_selected else [])
    return tuple(values)


def saved_view_apply_request(
    view: SavedFilterView,
    *,
    base_filters: Mapping[str, Sequence[str] | None],
    base_exclude_selected: bool,
) -> dict[str, object]:
    """Serialize one trusted view as a small, page-local component request."""

    return {
        "request_id": uuid4().hex,
        "view_id": view.identifier,
        "scope": view.scope,
        "filters": {key: list(values) for key, values in view.filters.items()},
        "exclude_selected": view.exclude_selected,
        "base_filters": {
            key: list(values or ()) for key, values in base_filters.items()
        },
        "base_exclude_selected": bool(base_exclude_selected),
    }


def saved_view_request_values(
    value: object,
    controls: SavedFilterViewControls,
) -> tuple[tuple[list[str], ...], list[str]] | None:
    """Validate a browser Store request before a page's sole owner applies it."""

    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("Saved filter-view request must be a mapping")
    if set(value) != {
        "request_id",
        "view_id",
        "scope",
        "filters",
        "exclude_selected",
        "base_filters",
        "base_exclude_selected",
    }:
        raise ValueError("Saved filter-view request has unexpected fields")
    if not isinstance(value["request_id"], str) or len(value["request_id"]) != 32:
        raise ValueError("Saved filter-view request ID is invalid")
    if value["scope"] != controls.scope or not isinstance(value["view_id"], str):
        raise ValueError("Saved filter-view request belongs to another page")
    expected_keys = {field.key for field in controls.fields}

    def normalize_filters(raw_filters: object, *, label: str) -> list[list[str]]:
        if not isinstance(raw_filters, Mapping) or set(raw_filters) != expected_keys:
            raise ValueError(
                f"Saved filter-view request {label} do not match this page"
            )
        normalized_filters: list[list[str]] = []
        for field in controls.fields:
            selected = raw_filters[field.key]
            if isinstance(selected, (str, bytes)) or not isinstance(selected, Sequence):
                raise ValueError(
                    f"Saved filter-view request {field.key!r} must be a sequence"
                )
            if any(not isinstance(item, str) for item in selected):
                raise ValueError(
                    f"Saved filter-view request {field.key!r} values must be text"
                )
            normalized_filters.append(list(selected))
        return normalized_filters

    normalized = normalize_filters(value["filters"], label="filters")
    normalize_filters(value["base_filters"], label="base filters")
    if not isinstance(value["exclude_selected"], bool) or not isinstance(
        value["base_exclude_selected"], bool
    ):
        raise ValueError("Saved filter-view request mode is invalid")
    exclude_value = ["exclude"] if value["exclude_selected"] else []
    return tuple(normalized), exclude_value


def saved_view_request_id(value: object) -> str | None:
    """Return a bounded request ID, or ``None`` for absent/invalid state."""

    if not isinstance(value, Mapping):
        return None
    request_id = value.get("request_id")
    if not isinstance(request_id, str) or len(request_id) != 32:
        return None
    return request_id


def saved_view_request_matches_base(
    value: object,
    controls: SavedFilterViewControls,
    filter_values: Sequence[Sequence[str] | None],
    exclude_value: Sequence[str] | None,
) -> bool:
    """Check that later manual edits have not superseded a pending request."""

    saved_view_request_values(value, controls)
    assert isinstance(value, Mapping)
    current = selected_filter_payload(controls, filter_values)
    base = value["base_filters"]
    return (
        current == {field.key: list(base[field.key]) for field in controls.fields}
        and ("exclude" in (exclude_value or [])) == value["base_exclude_selected"]
    )


def register_saved_filter_view_callbacks(
    app: Dash,
    repository: SavedFilterViewRepository,
    controls: SavedFilterViewControls,
) -> None:
    """Register one independent saved-view workflow for a Dash page."""

    field_keys = tuple(field.key for field in controls.fields)
    if not set(field_keys).issubset(repository.filter_keys):
        raise ValueError("Saved view repository must cover the configured UI fields")

    def page_view(view: SavedFilterView) -> SavedFilterView:
        """Project the shared catalogue onto this page's visible fields."""

        return SavedFilterView(
            identifier=view.identifier,
            scope=view.scope,
            name=view.name,
            filters={key: view.filters[key] for key in field_keys},
            exclude_selected=view.exclude_selected,
        )

    def repository_filters(
        filters: Mapping[str, Sequence[str] | None],
        *,
        current: SavedFilterView | None = None,
    ) -> dict[str, Sequence[str] | None]:
        """Expand page fields without erasing another page's extra fields."""

        expanded: dict[str, Sequence[str] | None] = {
            key: () for key in repository.filter_keys
        }
        if current is not None:
            expanded.update(current.filters)
        expanded.update(filters)
        return expanded

    @app.callback(
        Output(controls.current_label_id, "children"),
        Input(controls.committed_state_id, "data"),
        Input(controls.selector_id, "options"),
    )
    def sync_current_saved_view_label(committed_state, options):
        selected_identifier = (
            committed_state.get("view_id")
            if isinstance(committed_state, Mapping)
            else BASE_SAVED_VIEW_ID
        )
        return selected_saved_view_label(
            selected_identifier,
            options,
            base_label=controls.base_label,
        )

    @app.callback(
        Output(controls.selector_id, "options"),
        Output(controls.selector_id, "value"),
        Output(controls.name_id, "value"),
        Output(controls.status_id, "children"),
        Input(controls.refresh_id, "n_intervals"),
        Input(controls.save_id, "n_clicks"),
        Input(controls.delete_id, "n_clicks"),
        Input(controls.cancel_id, "n_clicks"),
        State(controls.selector_id, "value"),
        State(controls.name_id, "value"),
        State(controls.committed_state_id, "data"),
        *[State(controls.filter_ids[field.key], "value") for field in controls.fields],
        State(controls.exclude_id, "value"),
        prevent_initial_call=True,
    )
    def mutate_saved_views(
        _refresh_intervals,
        _save_clicks,
        _delete_clicks,
        _cancel_clicks,
        selected_identifier,
        requested_name,
        committed_state,
        *filter_values_and_exclude,
    ):
        filter_values = filter_values_and_exclude[: len(controls.fields)]
        exclude_value = filter_values_and_exclude[-1]
        try:
            triggered = ctx.triggered_id
        except MissingCallbackContextException:
            triggered = controls.refresh_id

        try:
            selected = selected_identifier
            name_update: object = no_update
            if triggered == controls.save_id:
                filters = selected_filter_payload(controls, filter_values)
                exclude_selected = "exclude" in (exclude_value or [])
                if is_base_saved_view(selected_identifier):
                    view = repository.save_new(
                        controls.scope,
                        requested_name,
                        repository_filters(filters),
                        exclude_selected=exclude_selected,
                    )
                    status = f"Saved new view: {view.name}."
                    name_update = ""
                else:
                    current = repository.get(controls.scope, selected_identifier)
                    view = repository.update(
                        controls.scope,
                        selected_identifier,
                        repository_filters(filters, current=current),
                        exclude_selected=exclude_selected,
                    )
                    status = f"Updated view: {view.name}."
                selected = view.identifier
            elif triggered == controls.delete_id:
                if is_base_saved_view(selected_identifier):
                    raise ValueError("Choose a named view before deleting it")
                if (
                    isinstance(committed_state, Mapping)
                    and committed_state.get("view_id") == selected_identifier
                ):
                    raise ValueError(
                        "Apply Base or another view before deleting the active view"
                    )
                view = repository.delete(controls.scope, selected_identifier)
                selected = BASE_SAVED_VIEW_ID
                status = f"Deleted view: {view.name}."
            elif triggered == controls.cancel_id:
                committed_filter_state_values(committed_state, controls)
                selected = (
                    committed_state["view_id"]
                    if isinstance(committed_state, Mapping)
                    else BASE_SAVED_VIEW_ID
                )
                status = "Draft changes cancelled; committed filters restored."
            else:
                status = "Shared saved views are ready."

            views = repository.list(controls.scope)
            identifiers = {view.identifier for view in views}
            if selected not in identifiers:
                selected = BASE_SAVED_VIEW_ID
            return (
                saved_view_options(views, base_label=controls.base_label),
                selected,
                name_update,
                status,
            )
        except (OSError, TimeoutError, ValueError) as error:
            try:
                options = saved_view_options(
                    repository.list(controls.scope),
                    base_label=controls.base_label,
                )
            except (OSError, ValueError):
                options = no_update
            return (
                options,
                no_update,
                no_update,
                f"Could not update saved views: {error}",
            )

    @app.callback(
        Output(controls.apply_request_id, "data"),
        Input(controls.selector_id, "value"),
        Input(controls.cancel_id, "n_clicks"),
        State(controls.committed_state_id, "data"),
        *[State(controls.filter_ids[field.key], "value") for field in controls.fields],
        State(controls.exclude_id, "value"),
        prevent_initial_call=True,
    )
    def stage_saved_view(
        selected_identifier,
        _cancel_clicks,
        committed_state,
        *filter_values_and_exclude,
    ):
        filter_values = filter_values_and_exclude[: len(controls.fields)]
        exclude_value = filter_values_and_exclude[-1]
        try:
            triggered = ctx.triggered_id
        except MissingCallbackContextException:
            triggered = controls.selector_id

        def committed_view() -> SavedFilterView | None:
            parsed = committed_filter_state_values(committed_state, controls)
            if parsed is None:
                return None
            committed_values, committed_exclude = parsed
            return SavedFilterView(
                identifier=_COMMITTED_DRAFT_VIEW_ID,
                scope=controls.scope,
                name="Committed filters",
                filters={
                    field.key: tuple(values)
                    for field, values in zip(
                        controls.fields,
                        committed_values,
                        strict=True,
                    )
                },
                exclude_selected="exclude" in committed_exclude,
            )

        if triggered == controls.cancel_id:
            view = committed_view() or base_saved_filter_view(controls)
        elif is_base_saved_view(selected_identifier):
            view = base_saved_filter_view(controls)
        else:
            try:
                view = page_view(repository.get(controls.scope, selected_identifier))
            except (OSError, ValueError) as error:
                raise PreventUpdate from error
        return saved_view_apply_request(
            view,
            base_filters=selected_filter_payload(controls, filter_values),
            base_exclude_selected="exclude" in (exclude_value or []),
        )

    @app.callback(
        Output(controls.committed_state_id, "data"),
        Input(controls.apply_id, "n_clicks"),
        Input(controls.initialized_id, "data"),
        State(controls.selector_id, "value"),
        *[State(controls.filter_ids[field.key], "value") for field in controls.fields],
        State(controls.exclude_id, "value"),
        State(controls.committed_state_id, "data"),
        prevent_initial_call=True,
    )
    def commit_filter_draft(
        apply_clicks,
        initialized,
        selected_identifier,
        *filter_values_and_exclude,
    ):
        filter_values = filter_values_and_exclude[: len(controls.fields)]
        exclude_value = filter_values_and_exclude[len(controls.fields)]
        committed_state = filter_values_and_exclude[len(controls.fields) + 1]
        try:
            triggered = ctx.triggered_id
        except MissingCallbackContextException:
            triggered = controls.apply_id if int(apply_clicks or 0) > 0 else None
        if triggered == controls.initialized_id:
            if not initialized or committed_state is not None:
                raise PreventUpdate
            selected_identifier = BASE_SAVED_VIEW_ID
        elif triggered != controls.apply_id or int(apply_clicks or 0) <= 0:
            raise PreventUpdate
        return committed_filter_state(
            controls,
            selected_identifier,
            filter_values,
            exclude_value,
        )

    @app.callback(
        Output(controls.applied_request_id, "data"),
        Input(controls.apply_request_id, "data"),
        *[Input(controls.filter_ids[field.key], "value") for field in controls.fields],
        Input(controls.exclude_id, "value"),
        State(controls.applied_request_id, "data"),
        prevent_initial_call=True,
    )
    def acknowledge_saved_view_request(request, *values):
        request_id = saved_view_request_id(request)
        if request_id is None or request_id == values[-1]:
            raise PreventUpdate
        filter_values = values[: len(controls.fields)]
        exclude_value = values[len(controls.fields)]
        target_values = saved_view_request_values(request, controls)
        if target_values is None:
            raise PreventUpdate
        target_filters, target_exclude = target_values
        current_filters = selected_filter_payload(controls, filter_values)
        target_filter_map = selected_filter_payload(controls, target_filters)
        reached_target = (
            current_filters == target_filter_map
            and list(exclude_value or []) == target_exclude
        )
        superseded_manually = not saved_view_request_matches_base(
            request,
            controls,
            filter_values,
            exclude_value,
        )
        if not reached_target and not superseded_manually:
            raise PreventUpdate
        return request_id

    @app.callback(
        Output(controls.save_id, "children"),
        Output(controls.delete_id, "disabled"),
        Output(controls.name_id, "disabled"),
        Input(controls.selector_id, "value"),
    )
    def sync_saved_view_actions(selected_identifier):
        named_view = not is_base_saved_view(selected_identifier)
        return (
            "Update View" if named_view else "Save New",
            not named_view,
            named_view,
        )


__all__ = [
    "BASE_SAVED_VIEW_ID",
    "BASE_SAVED_VIEW_LABEL",
    "SavedFilterViewControls",
    "base_saved_filter_view",
    "build_saved_filter_view_bar",
    "committed_filter_state",
    "committed_filter_state_values",
    "is_base_saved_view",
    "register_saved_filter_view_callbacks",
    "saved_view_apply_request",
    "saved_view_control_values",
    "saved_view_options",
    "saved_view_request_id",
    "saved_view_request_matches_base",
    "saved_view_request_values",
    "selected_saved_view_label",
    "selected_filter_payload",
]
