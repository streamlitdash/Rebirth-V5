# Fix 14 — Keep saved views selected and classify cleared Risk filters correctly

**Status:** Implemented on the `v2-fix` branch.

## What this fixes

This is only a saved-view state fix. It does not change the risk data, market
data, filters themselves, or any financial calculation.

After this change:

- selecting a named view and clicking **Apply** keeps that named view;
- changing any filter and clicking **Apply** changes the label to **Custom Mode**;
- clearing every Risk filter is also **Custom Mode**, because the Risk default
  is Activity 1–3 rather than “no filters”;
- the real Activity 1–3 default still displays as **Default**;
- the one-time saved-view catalogue refresh cannot overwrite a newer browser
  selection with Default;
- Apply wins if it arrives together with the startup refresh or initialization.

Risk Default specifically means the available Activity 1–3 values with every
other Risk filter empty. Clearing every Risk filter is therefore Custom Mode.
Pages without this special Risk matcher still treat all-empty filters as Base.

All runtime edits are in:

```text
cube/ui/s03_filters.py
```

There are five required replacements.

## 1. Replace `matches_activity_1_to_3_base()`

Find the whole function beginning with:

```python
def matches_activity_1_to_3_base(
```

Replace that whole function, up to the `@dataclass` immediately below it, with:

```python
def matches_activity_1_to_3_base(
    filters: Mapping[str, Sequence[str] | None],
    exclude_selected: bool,
    activity_options: Sequence[object] | None = None,
) -> bool:
    """Recognize the shared Activity 1-3 Base after page-specific expansion."""

    if exclude_selected or any(
        values for key, values in filters.items() if key != "activity"
    ):
        return False
    selected = {
        str(value).strip()
        for value in (filters.get("activity") or ())
        if str(value).strip()
    }
    if not selected:
        return False

    def owner_for(raw_value: object) -> int | None:
        value = " ".join(
            unicodedata.normalize("NFKC", str(raw_value)).split()
        ).casefold()
        if value.startswith(_TEMP_ACTIVITY_PREFIX):
            value = value[len(_TEMP_ACTIVITY_PREFIX) :]
        return next(
            (
                index
                for index, aliases in enumerate(_BASE_ACTIVITY_ALIASES)
                if value in aliases
            ),
            None,
        )

    if activity_options is not None:
        available_defaults = {
            str(option.get("value") if isinstance(option, Mapping) else option).strip()
            for option in activity_options
            if owner_for(option.get("value") if isinstance(option, Mapping) else option)
            is not None
        }
        return selected == available_defaults

    selected_owners = {owner_for(value) for value in selected}
    return None not in selected_owners and selected_owners == set(
        range(len(_BASE_ACTIVITY_ALIASES))
    )
```

The important line is:

```python
if not selected:
    return False
```

Previously, an empty selection could be compared with an empty set of
recognized default options and incorrectly be treated as Default.

## 2. Replace `committed_view_identifier()`

Inside `register_saved_filter_view_callbacks()`, find the nested function
beginning with:

```python
    def committed_view_identifier(
```

Replace that whole nested function, up to the next `@app.callback`, with:

```python
    def committed_view_identifier(
        selected_identifier: object,
        filter_values: Sequence[Sequence[str] | None],
        exclude_value: Sequence[str] | None,
        activity_options: Sequence[object] | None = None,
    ) -> str:
        """Name an applied exact view, otherwise mark it as unsaved Custom."""

        if is_custom_saved_view(selected_identifier):
            return CUSTOM_SAVED_VIEW_ID

        current_filters = selected_filter_payload(controls, filter_values)
        current_exclude = "exclude" in (exclude_value or [])
        if is_base_saved_view(selected_identifier):
            if controls.base_filter_matcher is not None:
                return (
                    BASE_SAVED_VIEW_ID
                    if controls.base_filter_matcher(
                        current_filters,
                        current_exclude,
                        activity_options,
                    )
                    else CUSTOM_SAVED_VIEW_ID
                )
            base_filters = {field.key: [] for field in controls.fields}
            return (
                BASE_SAVED_VIEW_ID
                if current_filters == base_filters and not current_exclude
                else CUSTOM_SAVED_VIEW_ID
            )

        try:
            selected_view = page_view(
                repository.get(controls.scope, str(selected_identifier))
            )
        except (OSError, ValueError):
            return CUSTOM_SAVED_VIEW_ID
        expected_filters = {
            field.key: list(selected_view.filters[field.key])
            for field in controls.fields
        }
        if (
            current_filters == expected_filters
            and current_exclude == selected_view.exclude_selected
        ):
            return selected_view.identifier
        return CUSTOM_SAVED_VIEW_ID
```

This removes the old `committed_state` fallback. The selected view is now named
only from the filter values actually being applied:

```text
exact Default values    -> Default
exact named-view values -> that named view
anything else           -> Custom Mode
```

There are two calls to `committed_view_identifier()` in the same file. At both
calls, remove this argument:

```python
committed_state,
```

Each remaining call must look like:

```python
selected = committed_view_identifier(
    selected_identifier,
    filter_values,
    exclude_value,
    activity_options,
)
```

## 3. Stop catalogue refresh from resetting the selector

In the saved-view catalogue callback, find:

```python
            else:
                status = "Shared saved views are ready."
```

Replace it with:

```python
            else:
                # The one-shot catalogue refresh owns only the option list.
                # Returning a selector value from its stale State can overwrite
                # a selection made while the server response was in flight.
                selected = no_update
                status = "Shared saved views are ready."
```

Then find:

```python
            if selected not in identifiers:
                selected = BASE_SAVED_VIEW_ID
```

Replace it with:

```python
            if selected is not no_update and selected not in identifiers:
                selected = BASE_SAVED_VIEW_ID
```

Immediately below that block, add:

```python
            option_identifier = (
                selected_identifier if selected is no_update else selected
            )
```

Finally, in the `saved_view_options()` call immediately below it, replace:

```python
include_custom=is_custom_saved_view(selected),
```

with:

```python
include_custom=is_custom_saved_view(option_identifier),
```

`no_update` is already imported from Dash at the top of the file, so no new
import is required.

This is the part that prevents a delayed one-time server response from writing
an old Default value over a view that the user just selected. Using
`option_identifier` also keeps the disabled Custom Mode option in the catalogue
when Custom Mode is already active.

## 4. Let user actions win over the catalogue refresh

Inside `mutate_saved_views()`, find:

```python
        try:
            triggered = ctx.triggered_id
        except MissingCallbackContextException:
            triggered = controls.refresh_id
```

Replace it with:

```python
        try:
            triggered_ids = set(ctx.triggered_prop_ids.values())
        except (AttributeError, LookupError, MissingCallbackContextException):
            try:
                triggered = ctx.triggered_id
            except (AttributeError, LookupError, MissingCallbackContextException):
                triggered = controls.refresh_id
            triggered_ids = {triggered}
        triggered = next(
            (
                candidate
                for candidate in (
                    controls.save_id,
                    controls.delete_id,
                    controls.cancel_id,
                    controls.apply_id,
                    controls.refresh_id,
                )
                if candidate in triggered_ids
            ),
            controls.refresh_id,
        )
```

Dash can report the startup refresh and a button click in the same callback.
This small priority list makes Save, Delete, Cancel, or Apply own that response
instead of letting the timer hide the user action.

## 5. Let Apply win if it arrives with initialization

Inside `commit_filter_draft()`, find this block:

```python
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
        else:
            selected_identifier = committed_view_identifier(
                selected_identifier,
                filter_values,
                exclude_value,
                activity_options,
            )
```

Replace it with:

```python
        try:
            triggered_ids = set(ctx.triggered_prop_ids.values())
        except (AttributeError, LookupError, MissingCallbackContextException):
            try:
                triggered = ctx.triggered_id
            except (AttributeError, LookupError, MissingCallbackContextException):
                triggered = controls.apply_id if int(apply_clicks or 0) > 0 else None
            triggered_ids = {triggered} if triggered is not None else set()

        apply_triggered = (
            controls.apply_id in triggered_ids and int(apply_clicks or 0) > 0
        )
        initialized_triggered = controls.initialized_id in triggered_ids
        if apply_triggered:
            selected_identifier = committed_view_identifier(
                selected_identifier,
                filter_values,
                exclude_value,
                activity_options,
            )
        elif initialized_triggered:
            if not initialized or committed_state is not None:
                raise PreventUpdate
            selected_identifier = BASE_SAVED_VIEW_ID
        else:
            raise PreventUpdate
```

This handles the first Apply cleanly when Dash combines it with the one-time
initialization update. It checks which input actually triggered, rather than
treating an old non-zero click count as a new Apply.

## Nothing else needs changing

Do not change:

- the saved-view repository;
- the filter dropdown callbacks;
- the risk-data cache;
- Portfolio or any other filter field;
- the financial calculations.

The branch also contains regression tests in:

```text
tests/s23_savedviews.py
```

You do not need to copy the test edits for the runtime fix to work, but they
protect these five cases from returning later.

## Test it

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\s23_savedviews.py tests\s19_riskfilters.py -q
```

Then check these five actions in the app:

1. Select a named view, click **Apply**, and confirm its name remains visible.
2. Change one filter, click **Apply**, and confirm **Custom Mode** appears.
3. On the Risk page, clear every filter, click **Apply**, and confirm Custom Mode
   appears rather than Default.
4. Reapply the real Activity 1–3 default and confirm Default appears.
5. Apply a view as soon as the page becomes ready and confirm it does not jump
   back to Default.

## Rollback

Revert the five blocks above in `cube/ui/s03_filters.py`. The Markdown guide
itself does not affect runtime behavior.
