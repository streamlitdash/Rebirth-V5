# Data fix — make standalone browsing independent of Risk navigation

Apply this correction after the unified Risk / Market / Both Data workspace has been implemented. It repairs one callback dependency and preserves the existing picker, charts, playback, history reader and Quick navigation.

The intended result is:

1. Open Data directly.
2. Choose Risk, Market or Both.
3. Search the series dropdown and select an available archived series.
4. For Both, select the opposite-kind companion when required.
5. Choose the period and press Load.

Quick Risk and Quick Market remain optional shortcuts that prefill an exact selection. They must not be prerequisites for populating Data's dropdown.

This document gives source edits to apply in JupyterHub. The callback dependency described below is present in the earlier wiring instructions. It has not been confirmed as the particular failure in your running application.

## 1. Understand the fault and the scope of this correction

The unified selection callback, `edit_workspace`, reads the archive catalogue and writes the selected history request. The retained `refresh_archive_generation` callback also listens to that request, even though its helper ignores the request's contents.

That produces this dependency loop:

```text
Selected history request
    -> archive generation refresh
    -> archive catalogue refresh
    -> selection editor
    -> selected history request
```

Dash builds its dependency graph from registered Inputs and Outputs. Returning `no_update`, ignoring an argument in Python, or relying on a button not being pressed does not remove an edge from that graph. This loop crosses several callbacks; it is separate from the selection editor intentionally reading and writing its own picker values within one callback.

The corrected sequence is:

```text
Data page opens / metadata timer / Clear Cache
    -> archive generation state
    -> archive catalogue
    -> searchable series options

User chooses a series and presses Load
    -> selected history request
    -> history read
    -> charts and values

Quick Risk or Quick Market
    -> optional prefilled selection and its existing automatic load
```

Only one existing application file needs changing for this confirmed dependency fault:

`cube/pages/data/s03_callbacks.py`

Keep these responsibilities:

| Keep | Why |
|---|---|
| `refresh_archive_catalog` and `load_archive_catalog` | They obtain the choices for standalone browsing. |
| `poll_archive_generation` | It checks archive metadata and handles cache reset. |
| The generation interval and Clear Cache input | They initialize and refresh the catalogue independently of a selected series. |
| `edit_workspace` and the searchable series picker | They already support selecting a catalogue entry without a Quick selection. |
| `load_workspace` and its request input | Loading an explicitly selected series still needs the selected request. |
| Exact Risk scope, Market identity and Both pairing rules | Standalone browsing must not weaken financial selection rules. |
| Existing shared browser player | Play/Pause and slider actions continue using the loaded bundle. |

Remove the request input **only from `refresh_archive_generation`**. Do not remove it from the history loader. Do not replace the entire callback module with an older version, create another picker, introduce another cache, or change archive schemas.

## 2. Stop the running application and locate its source

1. Save any unrelated source edits already in progress.
2. Stop the running application using the same notebook Stop/Interrupt control or process control used to launch it. Do not start another copy while the old process is still running.
3. Open JupyterLab's file browser and locate the application folder containing `app.py` and `cube`.
4. Open a Python notebook. Run the following cell. Change only the example folder name to match your application folder. If the notebook is already inside that folder, use `APP_ROOT = Path.cwd().resolve()` instead.

```python
from pathlib import Path
import ast
import datetime as dt

APP_ROOT = (Path.cwd() / "Rebirth").resolve()  # Set your actual application folder.
if not (APP_ROOT / "app.py").is_file():
    raise FileNotFoundError(f"No app.py in {APP_ROOT}; correct APP_ROOT")

TARGET = APP_ROOT / "cube/pages/data/s03_callbacks.py"
if not TARGET.is_file():
    raise FileNotFoundError(f"Missing callback file: {TARGET}")

print("Application folder:", APP_ROOT)
print("File to edit:", TARGET)
```

Expected result: the correct application folder and callback file are printed. If they are wrong, correct `APP_ROOT` before continuing. Do not create an empty file to satisfy the check.

## 3. Make a source backup and display the existing callback

Run this cell once before editing. It copies only the callback source into a timestamped backup folder beside the application. It does not read or change positions, market observations, daily archives or adjustments.

```python
source_before = TARGET.read_bytes()
stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
BACKUP_DIR = APP_ROOT.parent / "rebirth_data_fix_backups" / stamp
BACKUP_DIR.mkdir(parents=True, exist_ok=False)
BACKUP_FILE = BACKUP_DIR / "s03_callbacks.py"
BACKUP_FILE.write_bytes(source_before)
print("Source backup:", BACKUP_FILE)

source_text = source_before.decode("utf-8")
parsed = ast.parse(source_text, filename=str(TARGET))
matches = [
    node for node in ast.walk(parsed)
    if isinstance(node, ast.FunctionDef)
    and node.name == "refresh_archive_generation"
]
if len(matches) != 1:
    raise ValueError(
        f"Expected one refresh_archive_generation definition; found {len(matches)}. "
        "Locate its actual definition before editing."
    )

existing = matches[0]
first_line = min([existing.lineno] + [item.lineno for item in existing.decorator_list])
source_lines = source_text.splitlines()
for number in range(first_line, existing.end_lineno + 1):
    print(f"{number:4}: {source_lines[number - 1]}")
```

Expected result: the backup path, followed by the complete decorated `refresh_archive_generation` callback. Keep the printed backup path in the notebook. If this cell finds multiple definitions, do not add another callback; resolve the duplicate registration first.

## 4. Replace this one decorated callback

1. Open `cube/pages/data/s03_callbacks.py` in JupyterLab's text editor.
2. Find `def refresh_archive_generation` inside `register_callbacks`.
3. Select from its immediately preceding `@app.callback(` line through the end of that function's `return poll_archive_generation(...)` call. Include the entire decorator and function. Stop before the next callback's decorator.
4. Replace that selected block with the complete code below. This is code to paste into the source file, **not a notebook cell to execute**. Its four-space outer indentation places it inside `register_callbacks`.

```python
    @app.callback(
        Output("data-history-cache-state-store", "data"),
        Output("data-clear-status", "children"),
        Input("data-history-generation-interval", "n_intervals"),
        Input("clear-cache-complete-store", "data"),
        State("data-history-cache-state-store", "data"),
        prevent_initial_call=False,
    )
    def refresh_archive_generation(
        _intervals,
        reset_generation,
        previous_state,
    ):
        return poll_archive_generation(
            repository,
            None,
            previous_state,
            reset_generation,
        )
```

5. Save the file.

What changed, exactly:

- **REMOVE** `Input("data-history-request-store", "data")` from this decorator.
- **REMOVE** the corresponding request argument from the function signature. It was named `raw_handoff` in the original function; an implementation may have renamed it `raw_request`.
- **REPLACE** the second argument of `poll_archive_generation` with `None`.
- **KEEP** the helper's existing four-argument signature. Its unused second parameter can remain for compatibility; no other caller needs changing.
- **KEEP** both existing Outputs, both remaining Inputs and the previous-state State in the order shown.
- **SET** `prevent_initial_call=False` so the initial mounted interval can initialize archive metadata without waiting for a user action.

The new function receives two Input values followed by one State value. Every invocation returns the helper's same two output values. It neither reads a selected history request nor writes a history request.

Do not reintroduce the removed Input when reconciling this function with earlier implementation instructions. The replacement above is the final version of this callback.

## 5. Check syntax and the exact dependency declarations

Run this notebook cell after saving. It reads source text only. It does not start another application, connect to financial sources or require an additional checking package.

```python
source_after = TARGET.read_text(encoding="utf-8")
parsed_after = ast.parse(source_after, filename=str(TARGET))
print("Syntax OK:", TARGET.name)

matches = [
    node for node in ast.walk(parsed_after)
    if isinstance(node, ast.FunctionDef)
    and node.name == "refresh_archive_generation"
]
if len(matches) != 1:
    raise ValueError("There must be exactly one refresh_archive_generation")
callback = matches[0]

registrations = [
    item for item in callback.decorator_list
    if isinstance(item, ast.Call)
    and isinstance(item.func, ast.Attribute)
    and item.func.attr == "callback"
]
if len(registrations) != 1:
    raise ValueError("Expected one callback decorator on refresh_archive_generation")
registration = registrations[0]

def declared_targets(kind):
    result = []
    for argument in registration.args:
        if (isinstance(argument, ast.Call)
                and isinstance(argument.func, ast.Name)
                and argument.func.id == kind):
            result.append(tuple(ast.literal_eval(value) for value in argument.args[:2]))
    return result

expected = {
    "Output": [
        ("data-history-cache-state-store", "data"),
        ("data-clear-status", "children"),
    ],
    "Input": [
        ("data-history-generation-interval", "n_intervals"),
        ("clear-cache-complete-store", "data"),
    ],
    "State": [("data-history-cache-state-store", "data")],
}
for kind, required in expected.items():
    found = declared_targets(kind)
    if found != required:
        raise ValueError(f"Unexpected {kind} declarations: {found}")
    print(kind, "declarations OK:", found)

parameters = [argument.arg for argument in callback.args.args]
if parameters != ["_intervals", "reset_generation", "previous_state"]:
    raise ValueError(f"Callback parameters do not match the replacement: {parameters}")

initial_flags = [
    ast.literal_eval(item.value)
    for item in registration.keywords if item.arg == "prevent_initial_call"
]
if initial_flags != [False]:
    raise ValueError("The generation callback must permit its initial call")

calls = [
    node for node in ast.walk(callback)
    if isinstance(node, ast.Call)
    and isinstance(node.func, ast.Name)
    and node.func.id == "poll_archive_generation"
]
if (len(calls) != 1 or len(calls[0].args) != 4
        or not isinstance(calls[0].args[1], ast.Constant)
        or calls[0].args[1].value is not None):
    raise ValueError("Expected poll_archive_generation(repository, None, previous_state, reset_generation)")

print("Generation callback reads no selection request and allows initial loading")
```

Expected result: `Syntax OK`, three dependency-declaration confirmations, and the final success message. If a check raises an error, compare the saved source with the replacement in step 4 and correct that block. Do not remove a check to hide a mismatch.

These checks confirm the saved Python can be parsed and this callback's declarations match the repair. They do not prove the running browser has loaded the new code or that archives are configured. Continue with the following steps.

## 6. Confirm the existing catalogue path was retained

This is an inspection of the surrounding implementation. The dependency removed in step 4 is the confirmed fault; the items below identify possible implementation omissions if standalone browsing still fails. Do not rewrite these functions merely because they appear in this list.

1. Open `cube/pages/data/s02_view.py` and find `build_data_page`. Confirm the page includes these components once:
   - `data-history-generation-interval`, with its existing 60,000 ms interval, initial `n_intervals=0`, and polling enabled.
   - `data-history-cache-state-store` and `data-history-catalog-store`.
   - `data-display-mode`, initially `risk`.
   - `data-series-picker`, with searchable choices and an initially empty selection.
   - `data-catalog-status`, retained inside Diagnostics.
2. An initially empty `data-series-picker.value` is correct. Options should arrive from the catalogue before the user chooses a value. Do not require a selected value before generating its options.
3. In `s03_callbacks.py`, confirm `refresh_archive_catalog` still listens to `data-history-cache-state-store.data` and writes `data-history-catalog-store.data` plus `data-catalog-status.children`. Its existing previous-catalogue State can remain. It must not need a Quick selection or a selected history request to call `load_archive_catalog`.
4. Keep `load_archive_catalog(repository, cache_state)` reading `repository.catalog()` after generation metadata is ready. Do not filter that catalogue down to the incoming Quick selection. Loading these choices reads catalogue metadata; it does not load every position history into the browser.
5. Confirm `edit_workspace` still receives `data-history-catalog-store.data` as an Input and still owns `data-series-picker.options`. Its reducer must accept `raw_quick=None` and an empty primary selection, then return `series_options(catalog, display_mode)`.
6. Keep the valid page-absence guard when the Data route is not mounted. On a mounted Data page, a missing Quick selection, a missing loaded request or an empty picker value must not be treated as page absence. Those are all normal on direct entry.
7. Keep the history loader's no-request guard: before a user chooses a series and presses Load, `load_workspace` should show its empty selection message. Removing that guard would create unnecessary reads. Catalogue readiness and a loaded chart are different states.
8. Keep imported Quick Risk filters and the visible Clear scope action. Standalone direct selection starts without an imported Risk scope; if the user previously imported a scope in the same session, show it clearly and allow it to be cleared. Market quotes never inherit Portfolio filters.

If an item is missing from your implementation, record the exact missing component or callback condition. Resolve that specific omission using the existing component IDs and output owner; do not add a second catalogue callback or another owner of picker options. If changing another source file, back it up separately before editing it.

## 7. Restart the application with the saved source

1. Confirm the source file is saved.
2. Confirm the old application process has stopped.
3. If the application runs inside the notebook kernel, restart that kernel and rerun the existing setup and launch cells in their usual order. If it uses a separately launched process, stop and relaunch that same process using the usual working launch method.
4. Start exactly one application instance. Keep the existing JupyterHub port, proxy and source configuration.
5. Reload the browser. A browser reload by itself does not replace callback registrations retained in an old Python process.

No new installation or archive migration is part of this correction.

## 8. Walk through direct Data entry first

Perform these actions before using either Quick button. A fresh browser session is useful if a prior session has an old imported selection.

1. Open the application and navigate directly to Data.
2. Open Diagnostics. Once metadata loading completes, expect an archive-ready message showing the available Risk and Market choice counts, or a specific empty/error message.
3. Choose Risk. Open the series picker and type part of a known archived underlying or other identity label. Expect matching Risk choices without first visiting a Quick tool.
4. Select a Risk series. Choose a period, then press Load. Expect its loaded caption and Risk result, or an honest no-rows message if that exact period has no observations.
5. Choose Market. Search and select a known archived Market series, choose its period and press Load. Expect Market results with their own identity and units.
6. Choose Both. Select a primary series and its companion. If more than one companion is possible, choose it explicitly. Expect Load to remain disabled until both required selections are valid. After Load, expect two coordinated panels with separate Risk and Market values.
7. Change the selected series or period without pressing Load. The old result must retain its original loaded caption and show that the selection has changed. Press Load to request the new result.
8. If using a time view, move the slider and use Play/Pause. These actions must continue using the loaded browser bundle; they must not be added as archive-read triggers.

Standalone browsing is working when these flows succeed without an incoming Risk-page selection. An empty initial chart before the first Load is expected.

## 9. Confirm Quick navigation and Clear Cache still work

1. From Risk, use Quick Risk's existing Open in Data action on a known identity. Expect its exact selection and Risk scope to arrive in Data and use the existing automatic load.
2. Change the history period and press Load. The imported scope must remain visible and preserved.
3. Select a different series directly in Data. The previously consumed Quick navigation must not keep replacing that new choice.
4. Repeat from Quick Market. Its Market identity must remain exact and independent of Portfolio filters.
5. Use Clear Cache while Data is open. Expect the existing reset message, preserved draft selection under the new reset generation, and stopped old playback. The next Load must use fresh metadata. Do not use the old Quick selection merely to wake catalogue loading.
6. Leave Data and return. The restored draft or loaded selection must coexist with the full searchable catalogue. Visiting Risk first must remain optional.

## 10. Interpret an empty dropdown before changing more code

| What you observe | What it means and what to inspect |
|---|---|
| Diagnostics reports zero available Risk/Market identities | There are no readable completed archive identities for those kinds. This correction cannot invent past observations. Check the existing archive root and completed history availability. |
| Diagnostics remains on “Preparing archive choices…” | Generation state has not become ready. Check the enabled mounted generation interval, initial callback and any generation error shown under Diagnostics. |
| Diagnostics reports available identities, but the dropdown has no options | Inspect the catalogue Input and picker-option output in `edit_workspace`. Check that no early return requires a Quick selection, a loaded request or an already-selected series. |
| Options appear, but Load stays disabled after a single Risk or Market selection | Inspect the selected catalogue key and the reducer's valid-selection result. Both additionally needs a valid companion. Read the draft status before changing validation. |
| A choice loads but the chart says no observations | The identity exists in the catalogue but may have no rows for that period or retained Risk scope. Check the period and the displayed scope. |
| Only an option marked “from Quick” appears | The imported exact selection can be retained as a virtual option even without a matching catalogue entry. That does not establish that standalone catalogue loading is working. Inspect Diagnostics. |
| The browser still reports a dependency loop after the edit | Confirm the old Python process stopped, the edited source is the one being launched, and there is only one `refresh_archive_generation`. Inspect any additional callback edges introduced during implementation. |
| An archive access/schema/integrity error appears | Preserve the actual error. Repair the configured source or archive problem; do not convert the error to an empty success, disable validation or substitute a nearby date. |

These are diagnostic possibilities, not claims about which condition exists in your application. The confirmed source correction remains the one callback replacement in step 4.

## 11. Restore the source backup if necessary

1. Stop the application before restoring source.
2. Use the exact backup path printed in step 3. If the notebook kernel restarted, rerun the folder-location cell and set `BACKUP_FILE = Path("the exact printed backup path")` before the following cell.
3. Do not restore this backup over later unrelated edits. If more source work has happened since the backup, compare the files and restore only the affected callback block.
4. When no later edits need preserving, run:

```python
if not BACKUP_FILE.is_file():
    raise FileNotFoundError(f"Backup not found: {BACKUP_FILE}")
restored_source = BACKUP_FILE.read_bytes()
ast.parse(restored_source.decode("utf-8"), filename=str(TARGET))
TARGET.write_bytes(restored_source)
print("Restored callback source from:", BACKUP_FILE)
```

5. Restart the application using the normal launch method. Restoring this source file leaves archives, adjustments and saved financial records unchanged. It also restores the previous callback wiring, including the known dependency fault if it was present in that backup; restoration is recovery, not a successful repair.

Record the result in the notebook: the edited source path, backup path, syntax/dependency output, direct Risk/Market/Both outcomes, Quick navigation outcome and Clear Cache outcome. A saved guide or a syntax success alone is not proof that the running page has been repaired.
