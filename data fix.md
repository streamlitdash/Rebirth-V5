# Data fix — standalone Data, Full-tenor troubleshooting and bulk market calls

This is a step-by-step implementation and troubleshooting manual for the existing application in JupyterHub. Keep the completed Risk cache, Stock/P&L correctness and unified Data work. Apply small edits to the files actually launched by your notebook; do not overwrite whole modules with older copies.

The saved source explains the intended wiring, but the modified files and running browser in your JupyterHub have not been inspected here. The Full-tenor symptom narrows the investigation; it does not by itself prove one cause. The bulk integration below is a proposed source change, not an already connected market service.

## Read this first: order and boundaries

1. **[Chapter 1](#data-dependency):** verify the one-callback Data dependency repair if you have already applied it. It allows catalogue initialization without a selection arriving from Risk.
2. **[Chapter 2](#data-troubleshooting):** identify the first remaining Data failure: mounting, catalogue, editing, Load, archive read or rendering. Apply only the correction supported by that observation.
3. **[Chapter 3](#full-tenor):** trace a fresh Full-tenor click from the browser to the server and tree builder. Compare it with the working Reduced-to-Full sequence, correct the identified boundary, then remove the temporary diagnostics.
4. **[Chapter 4](#bulk-market):** add bulk Commodity Delta/Vega and connect FX Delta through the existing adapters. Do this after the interaction diagnosis so connector and display changes are not confused.

For every source-edit job: stop the process before restarting it, make the described source backup, find the named function, change only the specified block, save, run the supplied ordinary Python syntax/read-only checks, and restart using the same launcher. Existing completed work must remain in place. A Python fence is a notebook cell only when the step says to run it; a source replacement belongs in the named editor location. Do not paste every fence into one notebook cell.

Data must work both by direct selection and by optional Quick Risk/Quick Market prefill. Direct history choices require completed compatible archives. A live quote or position does not create past observations.

Commodity market identity is **Underlying plus the original Tenor Swap**. For example, requesting `(BRENT, DEC26)` and `(GOLD, MAR27)` does not request `(BRENT, MAR27)` or `(GOLD, DEC26)`. Commodity Vega has the same single tenor axis in this application. FX Delta has no tenor axis in its connector request and keeps its Underlying-only bulk call. Reduced display labels must never replace source quote identities.

<a id="data-dependency"></a>

## Chapter 1 — Verify the standalone Data dependency repair

This chapter applies after the unified Risk / Market / Both Data workspace has been implemented. If this callback correction is already applied, verify it with steps 4–5 and then continue to Chapter 2; do not replace it again merely because another fault remains. It repairs one callback dependency and preserves the existing picker, charts, playback, history reader and Quick navigation.

The intended result is:

1. Open Data directly.
2. Choose Risk, Market or Both.
3. Search the series dropdown and select an available archived series.
4. For Both, select the opposite-kind companion when required.
5. Choose the period and press Load.

Quick Risk and Quick Market remain optional shortcuts that prefill an exact selection. They must not be prerequisites for populating Data's dropdown.

This document gives source edits to apply in JupyterHub. The callback dependency described below is present in the earlier wiring instructions. It has not been confirmed as the particular failure in your running application.

### 1. Understand the fault and the scope of this correction

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

### 2. Stop the running application and locate its source

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

### 3. Make a source backup and display the existing callback

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

### 4. Replace this one decorated callback

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

### 5. Check syntax and the exact dependency declarations

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

### 6. Confirm the existing catalogue path was retained

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

### 7. Restart the application with the saved source

1. Confirm the source file is saved.
2. Confirm the old application process has stopped.
3. If the application runs inside the notebook kernel, restart that kernel and rerun the existing setup and launch cells in their usual order. If it uses a separately launched process, stop and relaunch that same process using the usual working launch method.
4. Start exactly one application instance. Keep the existing JupyterHub port, proxy and source configuration.
5. Reload the browser. A browser reload by itself does not replace callback registrations retained in an old Python process.

No new installation or archive migration is part of this correction.

### 8. Walk through direct Data entry first

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

### 9. Confirm Quick navigation and Clear Cache still work

1. From Risk, use Quick Risk's existing Open in Data action on a known identity. Expect its exact selection and Risk scope to arrive in Data and use the existing automatic load.
2. Change the history period and press Load. The imported scope must remain visible and preserved.
3. Select a different series directly in Data. The previously consumed Quick navigation must not keep replacing that new choice.
4. Repeat from Quick Market. Its Market identity must remain exact and independent of Portfolio filters.
5. Use Clear Cache while Data is open. Expect the existing reset message, preserved draft selection under the new reset generation, and stopped old playback. The next Load must use fresh metadata. Do not use the old Quick selection merely to wake catalogue loading.
6. Leave Data and return. The restored draft or loaded selection must coexist with the full searchable catalogue. Visiting Risk first must remain optional.

### 10. Interpret an empty dropdown before changing more code

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

### 11. Restore the source backup if necessary

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

<a id="data-troubleshooting"></a>

## Chapter 2 — Diagnose the remaining standalone Data problem

### A. Find the first failing stage before changing more source

The previous callback correction removes a real dependency loop. It does not establish that every part of the implemented Data page is connected correctly. The running JupyterHub files and browser have not been inspected here, so use the following steps to locate the remaining failure. Do not replace the complete Data callback module with a speculative rewrite.

1. Save your current source. Keep the source backup already made. Do not restore it merely because another problem remains: that would also restore the removed callback dependency.
2. Restart the actual application process once using your normal launch method, then reload its existing browser page. Use one running instance. Do not import `app.py` or call `create_app()` in a second notebook to investigate the first instance.
3. Open Data directly without using Quick Risk or Quick Market. Use a fresh browser session if the current one contains an imported selection; keep the current session available for the later Quick check.
4. Open Diagnostics and record its exact catalogue message, the draft status beside Load, and the loaded-result status. These are three different stages.
5. Classify the first failure with this table. Start with the earliest failing row, because later stages depend on it.

| Stage | Expected result | If this is the first failure |
|---|---|---|
| Page mount | Risk / Market / Both, primary picker, period and Load exist | Inspect layout/source mismatch and browser missing-component errors. |
| Metadata initialization | Diagnostics leaves “Preparing archive choices…” | Inspect generation callback, interval and its error output. |
| Catalogue read | Diagnostics reports choice counts or an explicit empty/archive error | Inspect the configured archive and catalogue response. |
| Selection editing | Choosing an available series enables Load in single-kind mode | Inspect `edit_workspace` options, values, draft validity and page-presence guard. |
| Request creation | One Load click produces the selected immutable request | Inspect Load handling and current-input reconciliation. |
| Archive read | A loaded result or an explicit read/validation message appears | Inspect `load_workspace`, not the catalogue picker. |
| Browser rendering | The appropriate panel displays its figure and values | Inspect the clientside exports, output count, console error and bundle contract. |

**Keep:** the single Data workspace, typed Risk/Market handoffs, explicit Both companion rules, budgets and existing archive validation. **Remove:** no additional source until a failing stage has been identified. A zero-choice catalogue and a JavaScript exception require different repairs.

### B. Check the saved file and inspect individual callback definitions

Use the existing `APP_ROOT` from the folder-location step. If the notebook kernel was restarted, rerun that step first. `APP_ROOT` must name the folder actually launched, not another uploaded copy with a similar name.

1. Run this source-only cell. It parses the current files and defines a small display helper. It does not import the application or read financial data.

```python
import ast
import hashlib
from pathlib import Path

if "APP_ROOT" not in globals():
    raise RuntimeError("Rerun the application-folder location cell first")
APP_ROOT = Path(APP_ROOT).resolve()
DATA_SOURCE = APP_ROOT / "cube/pages/data/s03_callbacks.py"
DATA_LAYOUT = APP_ROOT / "cube/pages/data/s02_view.py"
DATA_HELPERS = APP_ROOT / "cube/pages/data/s04_workspace.py"

for source_path in (DATA_SOURCE, DATA_LAYOUT, DATA_HELPERS):
    if not source_path.is_file():
        raise FileNotFoundError(f"Required implemented file is missing: {source_path}")
    raw = source_path.read_bytes()
    ast.parse(raw.decode("utf-8"), filename=str(source_path))
    print("Syntax OK:", source_path)
    print("  saved-source SHA256:", hashlib.sha256(raw).hexdigest())

def show_data_symbol(name, source_path=DATA_SOURCE):
    source_path = Path(source_path)
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(source_path))
    nodes = [node for node in ast.walk(tree)
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name == name]
    if len(nodes) != 1:
        raise ValueError(f"Expected one {name}; found {len(nodes)} in {source_path}")
    node = nodes[0]
    start = min([node.lineno] + [item.lineno for item in node.decorator_list])
    lines = text.splitlines()
    print("Source:", source_path)
    for number in range(start, node.end_lineno + 1):
        print(f"{number:4}: {lines[number - 1]}")

show_data_symbol("refresh_archive_generation")
```

2. Expect the generation decorator to have only the metadata-interval and Clear Cache Inputs. Its helper call must pass `None` as the unused second argument. If the old request Input appears, the saved source is still wrong; repeat the exact one-callback replacement, save and restart.
3. If the source is corrected but the browser still reports the old edge, suspect the running process/source path before making another change. A printed saved-source hash identifies the file on disk; it does **not** prove an already running process reloaded that file.
4. For a selection failure, run `show_data_symbol("edit_workspace")`. For a loaded-result failure, run `show_data_symbol("load_workspace")`. For an initialization failure, run `show_data_symbol("refresh_archive_catalog")` and `show_data_symbol("load_archive_catalog")`. Inspect the relevant complete decorated function instead of replacing it from memory.
5. Expected syntax result: all three files parse. A missing `s04_workspace.py` means the unified helper implementation is absent from this particular folder. A syntax success does not prove callback return counts, component presence or selection correctness.

### C. Read the callback declarations belonging to the running page

There are two ways to obtain the same kind of metadata. Use the first method only when the real running Dash object is already available in this notebook. Otherwise use the browser method. Do not create an application instance just to obtain a callback map.

#### Method 1: an existing running object in this notebook

1. Find the variable in your existing launch cell that holds the running Dash object. Its name might be `app`, but use that only if the launch cell actually defines it. A notebook supervising a separate Python process normally does not have that process's Dash object.
2. Set `DATA_APP_VARIABLE` below to that existing variable name, then run the cell. It reads only registered metadata.

```python
DATA_APP_VARIABLE = "app"  # Replace with the actual existing launch-variable name.
if DATA_APP_VARIABLE not in globals():
    raise RuntimeError("No such existing object; use the browser method instead")
running_data_app = globals()[DATA_APP_VARIABLE]
if not hasattr(running_data_app, "callback_map"):
    raise TypeError("This variable is not the running Dash object")

DATA_DEPENDENCIES = [
    {"output": output,
     "inputs": entry.get("inputs", []),
     "state": entry.get("state", [])}
    for output, entry in running_data_app.callback_map.items()
]
print("Registered callback records:", len(DATA_DEPENDENCIES))
print("Read the object already present in this notebook; no app was created")
```

3. If the browser is served by a different process, discard this object's result and use Method 2. Metadata from an unused notebook object cannot diagnose that browser. An empty callback map from an unserved object is not evidence that the running server has no callbacks.

#### Method 2: the existing browser request

1. Open the browser's developer tools and its Network panel. Keep the existing application URL and authenticated session.
2. Enable Preserve log, filter for `_dash-dependencies`, then reload the application and enter Data. Select the successful `_dash-dependencies` request for this application.
3. Read its Response. It should be a JSON array of callback declarations. A login page, 404, redirected response or HTML page is not callback metadata. Inspect that navigation/proxy problem first; do not change the app's prefix settings based on a guessed URL.
4. For notebook inspection, copy **only the JSON Response body** into a new text file named `data_dependencies.json` in `APP_ROOT`, using JupyterLab's editor. Do not export a full network archive, copy request headers/cookies, or copy financial `_dash-update-component` responses into this file.
5. Run this cell only if you used Method 2. It replaces any metadata from an unrelated notebook object with the actual browser response.

```python
import json

dependency_file = APP_ROOT / "data_dependencies.json"
if not dependency_file.is_file():
    raise FileNotFoundError("Save only the dependencies JSON response at " + str(dependency_file))
DATA_DEPENDENCIES = json.loads(dependency_file.read_text(encoding="utf-8"))
if not isinstance(DATA_DEPENDENCIES, list):
    raise ValueError("Expected the dependencies response to be a JSON array")
print("Browser callback records:", len(DATA_DEPENDENCIES))
```

6. Neither method sends a new history request, clears a cache, constructs a new app, or requires direct access to an unprotected local HTTP port.

#### Check exact ownership and the three bootstrap callbacks

Run this cell after obtaining `DATA_DEPENDENCIES` by one method. It checks selected fixed Data IDs and prints only dependency names, not store contents.

```python
from collections import defaultdict

def data_output_targets(encoded):
    if not isinstance(encoded, str):
        return []
    parts = encoded[2:-2].split("...") if encoded.startswith("..") and encoded.endswith("..") else [encoded]
    return [part.split("@", 1)[0] for part in parts if "." in part]

data_owners = defaultdict(list)
for callback_number, dependency in enumerate(DATA_DEPENDENCIES):
    for target in data_output_targets(dependency.get("output")):
        data_owners[target].append(callback_number)

required_targets = [
    "data-history-cache-state-store.data", "data-history-catalog-store.data",
    "data-series-picker.options", "data-series-picker.value",
    "data-display-mode.value", "data-companion-picker.value",
    "data-workspace-draft-store.data", "data-history-request-store.data",
    "data-history-handoff-consumed-store.data", "data-load-history-button.disabled",
    "data-history-bundle-store.data", "data-identity-breadcrumb.children",
    "data-risk-chart.figure", "data-market-chart.figure",
]
for target in required_targets:
    owner_numbers = data_owners.get(target, [])
    print("OK" if len(owner_numbers) == 1 else "CHECK", target, "owners:", owner_numbers)

for target in ("data-history-cache-state-store.data",
               "data-history-catalog-store.data", "data-history-request-store.data"):
    for owner in data_owners.get(target, []):
        declaration = DATA_DEPENDENCIES[owner]
        print("\nOwner", owner, "of", target)
        print("Inputs:", declaration.get("inputs", []))
        print("State:", declaration.get("state", []))
```

Expected result:

1. Each listed target has one owner. Zero means its registration is absent from the inspected app, or the response is from the wrong process/version. More than one means a duplicate owner exists. This check includes duplicate registrations that use `allow_duplicate`; adding that flag does not repair conflicting ownership.
2. The owner of `data-history-cache-state-store.data` has only `data-history-generation-interval.n_intervals` and `clear-cache-complete-store.data` as Inputs.
3. The owner of `data-history-catalog-store.data` receives `data-history-cache-state-store.data` as its Input. Its existing previous-catalogue State is allowed.
4. The owner of `data-history-request-store.data` receives catalogue and selection controls as Inputs. Its own previous request and consumed nonce are **State**, so reading them does not create another triggering edge.
5. The single picker/request owner is the existing `edit_workspace` registration; the bundle owner is `load_workspace`; figures belong to the clientside workspace player. Preserve those owners.

This is a focused declaration check. It does not prove the whole app has no dependency cycles, that every target is mounted, or that every callback returns the right number of values. If the browser names a different cycle, record its exact component-property sequence. Trace only its Input-to-Output edges; State is not a trigger. A callback reading and writing its own picker values is intentional, while a loop crossing several callbacks requires correction.

If duplicate or retired registrations are found, back up `cube/pages/data/s03_callbacks.py` before editing. Locate the whole decorated functions `sync_quick_handoff`, `configure_identity_mode`, `configure_request`, `choose_risk_type`, `choose_risk_greek`, `choose_underlying`, `choose_history_request`, and `load_history`. Remove only a remaining old registration among these; keep `edit_workspace`, `load_workspace`, `refresh_archive_generation`, `refresh_archive_catalog`, and `show_custom_range`. Remove only old clientside registrations targeting `dataProjectionBase`, `dataProjectionSlice`, and `dataPlayback`; keep reusable JavaScript helper functions. Do not remove another callback merely because it appears in the metadata table. If an unexpected owner is a different function, inspect that exact decorated definition before deciding which registration is obsolete. Rerun syntax, restart, obtain fresh browser metadata and repeat the ownership check.

### D. Separate an empty archive from a broken picker

1. Enter Data directly and open Diagnostics. Do not use a Quick button to make the options appear.
2. If the message is **Archive ready**, note the Risk and Market counts separately. Choose a kind whose count is greater than zero before judging its dropdown. A readable Risk archive does not imply a readable Market archive.
3. If the message says there are no completed compatible archive identities, inspect the archive root used by the running application and completed history availability. The dropdown is built from archived exact identities. Live Risk rows and live Market quotes do not, by themselves, create dated archive history. Do not remove the completed/schema checks or fabricate historical dates to fill the picker.
4. If the message stays **Preparing archive choices…**, inspect the generation/clear status beside it. A generation error may be the actual cause. In `cube/pages/data/s02_view.py::build_data_page`, the metadata interval must be mounted with `n_intervals=0` and polling enabled. Keep `data-history-cache-state-store` and `data-history-catalog-store` mounted once. In `refresh_archive_generation`, keep initial execution enabled. Do not gate initialization on a selected series or Quick payload.
5. If counts are positive but options are blank, inspect the Network response for the callback whose output includes `data-series-picker.options`. Expect an `options` array for the current kind. A missing callback invocation means a registration/mount/trigger problem; a successful response returning an empty array despite a nonempty eligible catalogue points to `edit_workspace`'s event/option logic.
6. In `cube/pages/data/s03_callbacks.py::edit_workspace`, inspect only the page-absence guard first. With the Data page mounted, an empty `data-series-picker.value`, absent Quick payload and absent loaded request are normal. They must not make this callback return before constructing options. If the guard incorrectly requires one of those values, remove that requirement from this guard; keep the absent-page check based on the optional Data mode control being `None`. Do not change the no-request guard in `load_workspace`.
7. Next confirm `data-history-catalog-store.data` is an Input of `edit_workspace`, and that the callback calls `reduce_workspace_draft` with the actual catalogue. Its first eleven results must include the returned `options` in the third output slot and the effective primary key in the fourth. Preserve the thirteen-output registration order.
8. If the response contains correct options but the visible dropdown remains blank, inspect Console for a missing-component or invalid-property error and confirm there is only one `data-series-picker` in `build_data_page`. A second picker or an old callback is not a repair.

For any conditional source edit in this section: back up the affected file, change only the identified guard/component/Input, parse that file with `ast.parse`, restart the running process and repeat direct entry. Keep the resulting diagnostic message visible. Do not catch every exception and turn it into an empty successful catalogue.

### E. Diagnose selection dispatch and a rapid Load click

Two implementation details can explain a page that behaves inconsistently even after catalogue initialization works. They are possibilities to inspect in the running implementation, not a claim that either is its current fault.

1. First choose a Risk series slowly. Wait until its visible selected label and draft status settle, then press Load. Record the exact loaded identity caption.
2. Choose a different Risk series and immediately press Load when the button is enabled. Record the loaded caption again. It must describe the newly selected series, never the previous one. Repeat once with an explicit Both companion change.
3. If the slower sequence succeeds and the immediate sequence loads the previous identity, inspect `edit_workspace`'s Load branch. `reduce_workspace_draft(event="load", ...)` preserves the previous parsed draft; it does not automatically resolve a new primary or companion value supplied separately as a current Input. Passing current period/date values to `workspace_request` fixes dates only, not a stale identity.
4. Record the relevant `_dash-update-component` request locally in Network. Compare only its current picker/companion keys, period, `changedPropIds`, and the output request's identity keys. Do not export the full financial bundle or request headers. This distinguishes a stale selection from an archive read of the correct selection that returned no rows.
5. Inspect the event-dispatch block in `edit_workspace`. It must consider `set(ctx.triggered_prop_ids)`, because several Inputs can change during hydration or one response. Using only `ctx.triggered_id` can select whichever trigger is presented first and ignore another relevant change.
6. The existing callback should give a new unconsumed Quick navigation priority, then a reset, then first-mount draft/request restoration. Empty layout defaults must not clear an already restored selection. A Load count of zero is not a user Load action. Values emitted by the callback itself must be compared with the effective draft before being interpreted as fresh user edits.
7. If the Load race is demonstrated, correct **only the existing Load branch in `cube/pages/data/s03_callbacks.py::edit_workspace`**. Before calling `workspace_request`, reconcile the current mode, primary key and, in Both, companion key against the draft in that order. Use the existing `reduce_workspace_draft` transitions `mode`, `primary`, and `companion` when their values differ. Carry forward the updated draft returned by each transition. Then validate the required handoffs and construct the request from that final draft plus the current period/custom dates. Do not silently take the first available companion. If a control combination is incomplete or inconsistent during a mode change, show the validation message and require a valid selection rather than loading the previous identity.
8. Preserve the imported Risk scope while reconciling a directly selected Risk identity; use the existing reducer to do so. Never put that scope on Market. A newly arriving Quick navigation must still follow its own validated import/consumption path; it must not be treated as an ordinary Load click.
9. On an ordinary picker/period edit with no Load, keep `no_update` for the request. Do not solve the race by making every dropdown change query history, introducing a second request writer, adding a sleep, or disabling validation.
10. Because the implemented callback body may differ, use the displayed complete `edit_workspace` definition to locate its existing Load branch. Keep its current argument-to-Input mapping and thirteen-output contract. The following conditional patch uses the registered property names to read current values, so it does not require guessing or renaming callback parameters. If the failing branch cannot be identified from this definition and the recorded action, preserve the source and record the evidence before editing it.

### Conditional Load correction: apply only when the stale-selection behavior is demonstrated

1. Back up `cube/pages/data/s03_callbacks.py` using the same byte-copy procedure used for the generation correction, with a new timestamp. Do not overwrite the earlier backup.
2. At the top of `s03_callbacks.py`, keep its existing imports of `Mapping`, `HistoryHandoff`, `HistoryValidationError`, `ctx` and `no_update`. Keep the existing imports of `reduce_workspace_draft`, `scope_caption` and `workspace_request` from `.s04_workspace`. Add `from uuid import uuid4` only if `uuid4` is not already imported. Do not import the application factory.
3. Immediately **before** `def register_callbacks`, add this complete top-level helper with no outer indentation. It reads the mapping passed by the existing callback and returns its existing thirteen outputs. It creates no callback registration and performs no archive read.

```python
def _load_current_workspace_controls(current_inputs, current_states):
    """Build one explicit Load from current control values, not a stale draft."""
    required_inputs = {
        "data-history-catalog-store.data", "data-history-handoff-store.data",
        "data-display-mode.value", "data-series-picker.value",
        "data-companion-picker.value", "reset-generation-store.data",
        "data-period.value", "data-custom-range.start_date",
        "data-custom-range.end_date",
    }
    required_states = {
        "data-workspace-draft-store.data",
        "data-history-handoff-consumed-store.data",
        "data-history-request-store.data",
    }
    if not required_inputs.issubset(current_inputs):
        raise HistoryValidationError("Data Load is missing a registered control Input")
    if not required_states.issubset(current_states):
        raise HistoryValidationError("Data Load is missing a registered selection State")

    mode = current_inputs["data-display-mode.value"]
    primary_key = current_inputs["data-series-picker.value"]
    companion_key = current_inputs["data-companion-picker.value"]
    reset = current_inputs["reset-generation-store.data"]
    catalog = current_inputs["data-history-catalog-store.data"]
    quick = current_inputs["data-history-handoff-store.data"]
    previous = current_states["data-workspace-draft-store.data"]
    consumed = current_states["data-history-handoff-consumed-store.data"]
    loaded = current_states["data-history-request-store.data"]
    if mode not in {"risk", "market", "both"}:
        raise HistoryValidationError("Choose Risk, Market or Both before loading")

    def transition(event, draft):
        return reduce_workspace_draft(
            event, draft, catalog, quick, mode, primary_key, companion_key, reset,
            loaded_request=loaded, consumed_nonce=consumed,
        )

    result = transition("initial", previous)
    if result["fresh_quick"]:
        raise HistoryValidationError("A new Quick selection is arriving; let it finish before Load")
    if result["draft"]["display_mode"] != mode:
        result = transition("mode", result["draft"])
    if result["draft"]["primary_key"] != primary_key:
        previous_companion = result["draft"]["companion_key"]
        result = transition("primary", result["draft"])
        if (mode == "both" and companion_key is not None
                and companion_key == previous_companion
                and companion_key != result["draft"]["companion_key"]):
            raise HistoryValidationError(
                "Primary series changed; choose its companion before Load"
            )
    if mode == "both" and result["draft"]["companion_key"] != companion_key:
        result = transition("companion", result["draft"])
    if not result["valid"]:
        raise HistoryValidationError(result["status"] or "Choose a valid exact series")

    draft = result["draft"]
    risk = HistoryHandoff.from_mapping(draft["risk"]) if draft["risk"] is not None else None
    market = HistoryHandoff.from_mapping(draft["market"]) if draft["market"] is not None else None
    request = workspace_request(
        draft["display_mode"], risk, market,
        period=current_inputs["data-period.value"],
        start_date=current_inputs["data-custom-range.start_date"],
        end_date=current_inputs["data-custom-range.end_date"],
        request_id=uuid4().hex,
    )
    return (
        draft,
        draft["display_mode"],
        result["options"],
        draft["primary_key"],
        result["companion_options"],
        draft["companion_key"],
        result["companion_label"],
        result["companion_hidden"],
        False,
        scope_caption(draft["risk_scope"]),
        "",
        request,
        no_update,
    )
```

4. Inside `edit_workspace`, find the existing event-dispatch block that reads `ctx.triggered_id`. At the beginning of that block, add the following local values. These property keys correspond to the existing simple Inputs and State, regardless of their Python parameter names. Keep the callback signature unchanged.

```python
        triggered_properties = set(ctx.triggered_prop_ids)
        current_control_values = ctx.inputs
        current_selection_states = ctx.states
        load_clicks = current_control_values.get("data-load-history-button.n_clicks")
        load_clicked = (
            "data-load-history-button.n_clicks" in triggered_properties
            and isinstance(load_clicks, (int, float))
            and not isinstance(load_clicks, bool)
            and load_clicks > 0
        )
```

The snippet is indented for a nested callback body. If that code is inside the callback's `try` block, indent it one additional level. Do not paste it outside `edit_workspace`.

5. Keep the existing fresh-Quick and reset branches ahead of Load. Identify a reset from membership of `"reset-generation-store.data"` in `triggered_properties`, rather than assuming it was the sole first trigger. Keep first-mount restoration before ordinary mode/picker interpretation. Do not run Load when the Data mode control is absent.
6. Find the existing branch which handles a user Load and calls `workspace_request`. Replace that branch's **condition** with `load_clicked` and replace only that branch's **body** with this line:

```python
            return _load_current_workspace_controls(current_control_values, current_selection_states)
```

Keep the surrounding `if`/`elif` form appropriate to the existing dispatch chain. Keep this branch inside the existing `try` block that catches `HistoryValidationError`, `TypeError`, `ValueError` and `LookupError`. Do not leave its old `workspace_request` call after the new return. Do not replace the fresh-Quick branch's request creation or nonce consumption.

7. Keep one request writer. The helper is invoked only by `edit_workspace`; do not decorate the helper or add a separate Load callback. On validation failure, keep the existing UI boundary's explicit status, preserve `no_update` for the last valid request, and disable Load only when the selected identities are invalid.
8. For the other event choices, replace checks that assume a single trigger with membership checks using these exact keys: mode `data-display-mode.value`; primary `data-series-picker.value`; companion `data-companion-picker.value`; catalogue `data-history-catalog-store.data`; scope clear `data-clear-risk-scope.n_clicks`; dates/period `data-period.value`, `data-custom-range.start_date`, `data-custom-range.end_date`. Also compare a selection value against the effective draft before treating it as changed. Keep the documented fresh-Quick, reset and initial-hydration priority; do not turn self-emitted equal values into new archive requests.
9. Save the file and run `ast.parse(DATA_SOURCE.read_text(encoding="utf-8"), filename=str(DATA_SOURCE))` in the notebook. This parses source only. Restart the application and repeat both Load sequences. The new helper deliberately refuses a temporarily inconsistent mode/series/pair rather than reading a previous identity. Once the controls settle into a valid selection, Load must succeed normally.

The explicit companion guard also prevents a rapid primary change from resurrecting the old companion value while the ordinary selection callback is still clearing it. A companion supplied by the existing exact automatic-pairing rule remains valid. Otherwise, wait for the new primary's controls to settle and choose the companion explicitly.

After a correction, parse the callback source, restart, repeat the slow and immediate sequences, then repeat a normal draft-only edit. Expected: the selected identity is exact; draft-only edits preserve the old loaded caption and request until Load; an invalid pair produces a visible message and no substituted result.

### F. Check Quick navigation replay, reset and lazy page mounting

1. After direct browsing works, open one exact identity using Quick Risk. Expect that incoming identity and its Risk scope, followed by its existing automatic load.
2. Choose a different series directly in Data. Wait, change the period, then leave Data and return. The consumed Quick nonce must not reapply the old selection.
3. If the selection repeatedly jumps back, inspect `edit_workspace` and `reduce_workspace_draft` in `cube/pages/data/s04_workspace.py`. A Quick payload's mere presence is not a fresh event. Its nonce must differ from both the consumed nonce and the draft's remembered Quick nonce. Keep `data-history-handoff-consumed-store.data` as State of the editor and write it only from that same editor after the incoming request validates.
4. Keep the existing session handoff/consumed stores in `cube/app/s07_factory.py`. Do not duplicate them inside `build_data_page`, clear all browser storage, or consume a nonce before validation to hide the replay. If duplicate shell stores are present in the page layout, remove only those duplicate page declarations after backing up the layout; retain the shell declarations and their storage types.
5. Use Clear Cache. Expect the player to stop and the request to be invalidated, while the draft preserves the identity/scope under the new reset generation. Press Load to read it again. A stale incoming Quick selection must show its reset mismatch, not be silently made current.
6. Leave Data, then use Quick Market to navigate back. If Console reports a missing Data component during this transition, record the exact ID and whether it is an Input, State or Output. Check that all listed Data controls and panel targets are created once when `build_data_page` mounts, including hidden controls. A collapsed Details section should keep its children mounted; it should not control Python loading through an `open` Input.
7. Optional page-only Inputs can be `None` while another route is mounted. Keep the existing optional-input convention supported by this application. Do not treat hidden controls as absent, and do not create a second Data layout in the shell merely to silence a missing target. If the error concerns an Output while the route has not mounted, inspect the actual timing and registration before changing the navigation contract; `allow_optional` on an Input cannot make an absent Output exist.

Expected: direct entry, Quick import, a later direct edit, return navigation and reset each work without overwriting another flow. If only return navigation fails, record that narrower symptom instead of describing the entire catalogue as broken.

### G. If data loads but the charts still fail

1. Confirm the loaded-result status describes a successful request and an exact identity. If it instead describes missing observations, a budget rejection or a read error, handle that message first. A rendering change cannot repair a failed archive read.
2. Open Console and reproduce the problem once. Record the first error and its named clientside function. The relevant implemented functions are `workspaceProjectionControls` and `workspacePlayback`, exported from `assets/s09_playback.js` under `window.dash_clientside.cube`.
3. Check their presence with this read-only Console expression. It neither plays a frame nor changes a selection:

```javascript
({
  controls: typeof window.dash_clientside?.cube?.workspaceProjectionControls,
  player: typeof window.dash_clientside?.cube?.workspacePlayback,
  figure: typeof window.dash_clientside?.cube?.workspaceMainFigure
})
```

4. Expect `"function"` for all three. If a function is missing, inspect the existing export object at the end of `assets/s09_playback.js`; retain its other exports and add only the missing implemented function's export. Do not register an old player callback again. If source exports are correct but Console sees an older file, reload assets after confirming the running application serves the edited folder.
5. If Dash reports the wrong number of returned values, compare the existing clientside registration's Output order in `s03_callbacks.py` with the corresponding JavaScript return array. Correct the mismatched branch, including empty/error returns, to return one value for every declared Output in the exact same order. Keep one callback owner for each figure, table and player property.
6. In Both, check each panel separately. One exact date can have Risk without Market or Market without Risk. Show a missing-observation caption and null values for the absent observation; do not hide the panel, choose a nearby date, or fill it with zero. Market quote values must not use the Risk Sum slice.
7. Move the slider and use Play/Pause. The successful archive request must remain the same. These are browser rendering actions on the loaded bundle. If they start server reads, inspect the Inputs of `load_workspace`: keep only the request, cache-state and reset stores, and remove an accidentally added player/slider Input from that loader together with its matching Python argument. Keep player Inputs in the clientside player registration.

Back up the exact Python or JavaScript file before a conditional edit. Parse changed Python; use the existing JavaScript syntax check only if its runtime is already available. Then restart/reload as appropriate and repeat the failing chart action. A syntax result alone does not prove the visual or financial result is correct.

### H. Record a small, useful outcome

1. Record the application folder, saved source hash and the ordinary launch method/process that serves the browser.
2. Record the first failing stage, exact visible status/error, and whether the failure occurs on direct entry, only after Quick navigation, only with Both, or only with an immediate Load click.
3. Keep the relevant callback source and dependency-owner output. Keep any browser metadata file locally; it is optional diagnostic material, not an application dependency.
4. Record one expected-versus-observed example using non-sensitive identity labels if the notes will be shared. Do not include full positions, financial bundles, cookies, access tokens or complete network archives.
5. After a source correction, rerun the direct Risk, direct Market, valid Both, Quick Risk, Quick Market and Clear Cache actions that were affected. State which actually worked and which still failed.
6. If a conditional change worsens the application, stop it and restore only that change's source backup, preserving unrelated later edits. Restart the same process. Do not restore historical archives or remove the already confirmed generation-callback correction as a side effect.

These steps narrow the problem without creating another cache, another picker, another running app or another output owner. They deliberately leave an unobserved callback body intact until its specific failure has been identified.

<a id="full-tenor"></a>

## Chapter 3 — Troubleshoot Full-tenor hierarchy expansion

### 1. Understand what this symptom does and does not establish

The reported sequence is: an Underlying opens in Reduced mode; the same Underlying does not open when first clicked in Full mode; opening it in Reduced mode and then changing to Full shows the full-tenor children.

That is useful evidence. Full mode can render children when it receives an already-open hierarchy key. It does **not** establish that a click made in Full mode reaches the same state. Trace the click, its validation, the updated open-row list, and the resulting table separately. Do not change reduction matrices, merge keys, financial values, or tenor labels to repair an interaction problem. Opening Reduced first is a reproduction clue, not the completed repair.

The source design uses this path:

```text
Underlying arrow in the browser
  -> assets/s13_risk.js::publishRiskAction
  -> risk-row-action-store
  -> s07_explorer.py::reduce_and_render_risk_view
  -> validate the table generation, action source and hierarchy keys
  -> effective_open_rows / open-rows-store
  -> render_active_risk_table with reduced_tenor=False
  -> build_tree_rows with the clicked key in open_rows
  -> children, subject to the shared visible-row budget
```

The instructions below inspect the running copy. A cause is confirmed only when the observed trace supports it. Some source copies also include committed reduction matrices and a `ProductRiskBundle` supplied by the Risk adapter. Keep that transport, its authoritative source-type declarations, and the complete unreduced risk frame. Do not replace whole modules with an older copy while correcting the interaction.

### 2. Back up the files before adding temporary diagnostics

1. Open a Python notebook beside the application folder.
2. Set `FT_ROOT` to the folder containing `app.py`, `cube` and `assets`. Change only the example folder name in this cell.
3. Run the cell. It copies the current files into a new sibling backup folder. It does not modify application data.

```python
from pathlib import Path
from datetime import datetime
import ast
import shutil

FT_ROOT = (Path.cwd() / "Rebirth").resolve()  # Edit this folder if necessary.
assert (FT_ROOT / "app.py").is_file(), FT_ROOT
FT_FILES = [
    "assets/s13_risk.js",
    "cube/pages/risk/s02_state.py",
    "cube/pages/risk/s07_explorer.py",
    "cube/pages/risk/s06_explorertables.py",
    "cube/ui/s02_aggregation.py",
]
FT_BACKUP = FT_ROOT.parent / (
    FT_ROOT.name + "_tenor_backup_" + datetime.now().strftime("%Y%m%d_%H%M%S_%f")
)
FT_BACKUP.mkdir()
for relative in FT_FILES:
    source = FT_ROOT / relative
    assert source.is_file(), source
    target = FT_BACKUP / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
print("Backup:", FT_BACKUP)
```

Expected: one backup folder is printed. Keep this notebook open so that the path remains available.

### 3. Reproduce the failure with one small, unchanged selection

1. Restart the application process using the same launcher and data configuration you normally use. Refresh the browser page afterwards; saving Python files alone does not replace a running process.
2. Choose one Risk Type and one familiar Underlying. Apply narrow filters so that this one branch fits comfortably within the visible-row budget. Keep the data revision, filters, reporting identity, hierarchy layout and promotion settings unchanged during the comparison.
3. Choose **Full** before opening the Underlying. Wait for the table to finish updating. Click the small expansion arrow once, without holding Ctrl, Shift or Alt. Record whether the arrow changes, whether children appear, and whether a row-limit notice appears.
4. Open a fresh browser tab, choose the same selection, choose **Reduced**, and open the same Underlying. Record the same observations. Then switch to Full and observe the inherited open branch.
5. In that Full view, collapse and reopen the Underlying. This distinguishes “Full can retain an open branch” from “Full can process a new open action.”
6. Repeat only once with a broader selection if the narrow selection works. A failure that appears only with a broader view points towards the construction budget or response size; a failure on a single small branch points elsewhere.

Expected: a compact comparison of a cold Full click, a Reduced click, a Reduced-to-Full switch, and a new Full click after collapsing. Do not change several controls between those observations.

### 4. Trace the browser action

1. Open `assets/s13_risk.js` in the editor.
2. Find `const publishRiskAction = (node) => {`.
3. Inside that function, find the final line `setProps(storeId, { data: action });`.
4. Insert the following block immediately **before** that line. Do not replace `setProps`, the view-token lookup, or the `pendingRiskRowState` logic.

```javascript
    // BEGIN TEMPORARY TENOR TRACE
    if (kind === "row") {
      let renderedMode = "unavailable";
      try {
        renderedMode = JSON.parse(viewToken).generation?.reduced_tenor;
      } catch (_error) {
        renderedMode = "unavailable";
      }
      console.info("RISK_TENOR_TRACE browser publish", {
        source: action.source,
        key: action.key,
        sequence: action.sequence,
        reduced_tenor: renderedMode,
        open_count: action.open_rows?.length,
        clicked_key_is_open: action.open_rows?.includes(action.key),
      });
    }
    // END TEMPORARY TENOR TRACE
```

5. Save the file and hard-refresh the browser so that the changed asset is loaded.
6. Open the browser's developer tools and choose **Console**. No console commands are required. Clear old messages, make the cold Full click from step 3, and look for `RISK_TENOR_TRACE browser publish`.

Expected when opening a closed row: `reduced_tenor: false`, the appropriate source (`main-row-toggle` or `alt-row-toggle`), and `clicked_key_is_open: true`. When collapsing it, the final flag should be false. The key is a hierarchy identity, not a row number.

If there is **no browser publish message**, first check the arrow itself using the developer tools' element inspector:

1. The arrow must have class `row-toggle`.
2. Its containing row must have a nonempty `data-risk-key`.
3. A containing table wrapper must have `data-risk-view-token` and `data-risk-open-rows`.
4. The arrow must not be disabled when there are meaningful child levels.
5. The console must not show a JavaScript error before `publishRiskAction` reaches its final line.

An Underlying with only a scalar Spot quote might correctly have no meaningful tenor children. Use the exact same Underlying for which the Reduced-to-Full sequence displays children.

### 5. Trace why the server accepts or rejects the click

1. Open `cube/pages/risk/s07_explorer.py`.
2. Add `import json` and `import os` beside the standard-library imports if each is absent. Keep the existing `import logging` and `LOGGER`.
3. Find the nested callback `reduce_and_render_risk_view`.
4. Inside it, find the branch beginning `if ctx.triggered_id == "risk-row-action-store":` and ending immediately before `elif ctx.triggered_id == "risk-metric-action-store":`.
5. Replace **only that row-action branch** with the block below. Keep the following `elif` and all other callback branches. Its normal validation and state update are unchanged; the extra part explains each decision in the application log.

```python
            if ctx.triggered_id == "risk-row-action-store":
                expected_source = (
                    "alt-row-toggle" if table_view == "alt" else "main-row-toggle"
                )
                action = row_action if isinstance(row_action, Mapping) else {}
                key = action.get("key")
                opened = action.get("open_rows")
                current_action = _is_current_risk_action(
                    row_action,
                    kind="row",
                    expected_view_token=expected_token,
                )
                valid_key = _valid_delegated_row_key(key, allow_total=False)
                valid_opened = isinstance(opened, list) and all(
                    _valid_delegated_row_key(item, allow_total=False)
                    for item in opened
                )
                valid_source = action.get("source") == expected_source

                # BEGIN TEMPORARY TENOR TRACE
                if os.environ.get("CUBE_RISK_TRACE") == "1":
                    def token_parts(value):
                        try:
                            parsed = json.loads(value)
                        except (TypeError, ValueError):
                            return {}
                        return parsed if isinstance(parsed, dict) else {}

                    received = token_parts(action.get("view_token"))
                    expected = token_parts(expected_token)
                    received_generation = received.get("generation") or {}
                    expected_generation = expected.get("generation") or {}
                    changed_fields = [
                        name for name in sorted(set(received) | set(expected))
                        if name != "generation" and received.get(name) != expected.get(name)
                    ]
                    if isinstance(received_generation, dict) and isinstance(expected_generation, dict):
                        changed_fields += [
                            "generation." + name
                            for name in sorted(set(received_generation) | set(expected_generation))
                            if received_generation.get(name) != expected_generation.get(name)
                        ]
                    LOGGER.warning(
                        "RISK_TENOR_TRACE server row %s",
                        {
                            "reduced_tenor": bool(reduced_tenor),
                            "sequence": action.get("sequence"),
                            "current_action": current_action,
                            "token_changed_fields": changed_fields,
                            "source_ok": valid_source,
                            "key_ok": valid_key,
                            "opened_ok": valid_opened,
                            "open_count_before": len(current_open_rows or []),
                            "open_count_requested": len(opened) if isinstance(opened, list) else None,
                            "clicked_key_is_open": key in opened if isinstance(opened, list) else None,
                            "key": key,
                        },
                    )
                # END TEMPORARY TENOR TRACE

                if not current_action or not valid_source or not valid_key or not valid_opened:
                    raise PreventUpdate
                effective_open_rows = sorted(set(opened))
                updates[2] = effective_open_rows
                should_render_table = True
```

6. Still inside that callback, find `triggered = set(ctx.triggered_prop_ids)` near its beginning. Add this block immediately afterwards. It shows whether the request reached the callback but took a context-refresh branch before row-action validation:

```python
        # BEGIN TEMPORARY TENOR TRACE
        if os.environ.get("CUBE_RISK_TRACE") == "1":
            LOGGER.warning(
                "RISK_TENOR_TRACE callback entry %s",
                {
                    "triggered": sorted(triggered),
                    "reduced_tenor": bool(reduced_tenor),
                    "has_previous_context": isinstance(previous_context, Mapping),
                },
            )
        # END TEMPORARY TENOR TRACE
```

Then find `if should_render_table:` near the callback's end. Immediately after that line and before `main_grid, alt_grid = render_active_risk_table(...)`, add:

```python
            # BEGIN TEMPORARY TENOR TRACE
            if os.environ.get("CUBE_RISK_TRACE") == "1":
                LOGGER.warning(
                    "RISK_TENOR_TRACE render request %s",
                    {
                        "reduced_tenor": bool(reduced_tenor),
                        "open_count": len(effective_open_rows),
                        "trigger": str(ctx.triggered_id),
                        "table_view": table_view,
                    },
                )
            # END TEMPORARY TENOR TRACE
```

7. Add these lines to the notebook launcher **before** it starts the application subprocess:

```python
import os
os.environ["CUBE_RISK_TRACE"] = "1"
os.environ["CUBE_RISK_TRACE_LABEL"] = "PUT THE EXACT UNDERLYING LABEL HERE"
```

If the launcher passes an explicit `env=` dictionary to the subprocess, add those same two entries to that dictionary instead. They must be present in the environment of the application process; setting notebook variables after the process has started does not affect it.

8. Save the file. Run this syntax check, then stop and restart the application process with that launcher:

```python
for relative in ("cube/pages/risk/s07_explorer.py",):
    ast.parse((FT_ROOT / relative).read_text(encoding="utf-8"), filename=relative)
    print("Syntax OK:", relative)
```

9. Repeat one cold Full click and read the application log where the launcher normally sends output.

Expected: `current_action`, `source_ok`, `key_ok` and `opened_ok` are all true; `token_changed_fields` is empty; `clicked_key_is_open` is true for an opening action. The next `render request` has `reduced_tenor: False`.

If the browser publishes but there is no callback-entry message, inspect the browser Network panel for the failed callback request and the application log for a startup/registration error. If callback-entry appears but server-row does not, inspect its `triggered` fields and `has_previous_context`: a concurrent context refresh or missing context may have selected the earlier initialization branch. Wait for initialization to finish and repeat. If `has_previous_context` remains false after initialization, check that this callback still returns its `updates[5] = context` value to `risk-view-context-store`; do not bypass that initialization guard.

Do not remove `_is_current_risk_action` to force the click through. It prevents an old table's action from being applied to a new filter, data revision or tenor mode.

### 6. Trace the actual child decision and row budget

1. Open `cube/pages/risk/s06_explorertables.py`.
2. Add `import logging` and `import os` beside the standard-library imports if absent.
3. Find `build_tree_rows`.
4. Find its consecutive assignments `can_expand = next_level < len(groups)` and `is_open = key in open_set`.
5. Immediately after `is_open = key in open_set`, add this block. It prints only the target's Underlying/promoted-parent decision, not every position or descendant.

```python
        # BEGIN TEMPORARY TENOR TRACE
        trace_label = os.environ.get("CUBE_RISK_TRACE_LABEL", "")
        if (
            os.environ.get("CUBE_RISK_TRACE") == "1"
            and trace_label
            and str(value) == trace_label
            and group_column in {"underlying", "reported underlying", "display bucket"}
        ):
            logging.getLogger(__name__).warning(
                "RISK_TENOR_TRACE tree decision %s",
                {
                    "group_column": group_column,
                    "key": key,
                    "is_open": is_open,
                    "can_expand": can_expand,
                    "next_group": groups[next_level] if next_level < len(groups) else None,
                    "scoped_rows": len(scoped),
                    "swap_labels": scoped["tenor swap"].nunique(dropna=False) if "tenor swap" in scoped else None,
                    "option_labels": scoped["tenor option"].nunique(dropna=False) if "tenor option" in scoped else None,
                    "remaining_before_parent": int(render_budget["remaining"]) if render_budget is not None else None,
                },
            )
        # END TEMPORARY TENOR TRACE
```

This block assumes the visible-row safeguard has added the `render_budget` argument to `build_tree_rows`. If that argument is absent in the running copy, leave out only the `remaining_before_parent` entry until the safeguard is present. Do not invent a module-global budget.

6. In the existing budget guard inside `build_tree_rows`, find:

```python
        if render_budget is not None and int(render_budget["remaining"]) <= 0:
            render_budget["truncated"] = True
            break
```

Insert the following immediately before `render_budget["truncated"] = True`, preserving the surrounding guard:

```python
            # BEGIN TEMPORARY TENOR TRACE
            if os.environ.get("CUBE_RISK_TRACE") == "1" and not render_budget["truncated"]:
                logging.getLogger(__name__).warning(
                    "RISK_TENOR_TRACE budget exhausted before group=%s depth=%s",
                    group_column,
                    depth,
                )
            # END TEMPORARY TENOR TRACE
```

7. Run `ast.parse` for `cube/pages/risk/s06_explorertables.py`, as in the previous syntax cell, then restart the application. Repeat the same four observations from step 3.

Expected after an accepted opening click: `is_open: True`, `can_expand: True`, and a meaningful `next_group`. Full mode normally has more distinct source tenor labels than Reduced mode. Their exact labels and ranks come from the source; this diagnostic must not change them.

### 7. Apply only the correction identified by the trace

Use the first matching case below. These are separate branches, not a list of speculative edits to apply together.

#### Case A: no browser action is published

1. In `s06_explorertables.py::build_tree_rows`, keep `className: "row-toggle"` in `toggle_props` for both modes.
2. In the same function, keep `row_props["data-risk-key"] = key` when `delegated_actions` is true.
3. In the top-level call to `build_tree_rows` inside `build_risk_table`, `build_alt_risk_table` and `build_credit_multi_table`, restore `delegated_actions=True` if an edited caller omitted it. Preserve all other keyword arguments, including `render_budget`.
4. In each builder's final outer `html.Div`, restore these attributes if missing. Use its existing `view_token` and `open_rows` arguments:

```python
        **(
            {
                "data-risk-view-token": view_token,
                "data-risk-open-rows": json.dumps(
                    sorted(open_rows or []), separators=(",", ":")
                ),
            }
            if view_token
            else {}
        ),
```

These are keyword arguments of the outer `html.Div`, alongside `className`; they are not children of the table. Keep exactly one copy of each attribute. If `json` is absent from that module's imports, add `import json`.

5. In `assets/s13_risk.js`, keep the delegated click selector covering `#risk-grid .row-toggle` and `#alt-risk-grid .row-toggle`. Do not add a second `n_clicks` callback for these same arrows.
6. If all attributes are already present, inspect the JavaScript error reported in step 4. A browser asset-loading or script error requires its own correction; do not claim the hierarchy code is repaired merely by adding duplicate attributes.

Expected after the relevant correction: one browser publish message per arrow click. If the arrow is disabled, go to Case D instead of forcing `disabled=False`.

#### Case B: the server rejects the action because the token differs

1. Read `token_changed_fields`. A brief mismatch while the table is still changing is expected stale-action protection. A mismatch that remains after the table finishes changing is the fault to repair.
2. In `s07_explorer.py::render_active_risk_table`, find the call `generation_state = risk_generation_state(...)`. Ensure it contains exactly:

```python
            reduced_tenor=reduced_tenor,
```

3. In `reduce_and_render_risk_view`, find `expected_token = risk_action_view_token(...)` and its nested `risk_generation_state(...)` call. Ensure it contains:

```python
                    reduced_tenor=bool(reduced_tenor),
```

4. In the same callback's final `render_active_risk_table(...)` call, ensure it contains:

```python
                reduced_tenor=bool(reduced_tenor),
```

5. In `render_active_risk_table`'s `filtered_frame()` function, ensure `cache.filtered(...)` receives:

```python
                reduced_tenor=reduced_tenor,
```

6. Keep the single option parser `_explorer_option_state(explorer_options)` as the source of this flag. Full means the literal `"reduced-tenor"` value is absent from the selected options. Do not compare a displayed label such as `"Full"` to a Boolean.
7. If `token_changed_fields` identifies filters, promotion generation, sorting or a different field, compare that field's arguments in the **same two** `risk_generation_state` calls. Restore any missing argument using the callback's existing effective value. Do not remove the field from the token to make the strings match.

Expected after an evidenced wiring correction: the browser and server both report Full, with no persistent token differences. All token checks remain enabled.

#### Case C: source or hierarchy-key validation fails

1. If `source_ok` is false, compare the active container and the browser trace. A main/Credit table publishes `main-row-toggle`; the alternative table publishes `alt-row-toggle`.
2. In `assets/s13_risk.js::publishRiskAction`, retain the row-source selection from `node.dataset.riskSource`, falling back to the enclosing `#alt-risk-grid` or main grid. Do not hardcode every row to the same source.
3. If `key_ok` or `opened_ok` is false, compare the browser's key with the `tree decision` key. The server validator uses `cube/ui/s02_aggregation.py::parse_row_key` and the allowed columns in `ROW_KEY_COLUMNS`.
4. In `build_tree_rows`, retain the canonical creation `key = row_key(next_context)` and use that exact `key` in the row's `data-risk-key`. Do not substitute the visible label, an ordinal row number, a concatenated string or a key containing the tenor-mode flag.
5. In `publishRiskAction`, retain both reset conditions on `pendingRiskRowState`: a changed `viewToken` **or** changed `renderedRows` reloads the server-rendered open-row list. The predicate must remain:

```javascript
      if (
        !pendingRiskRowState
        || pendingRiskRowState.viewToken !== viewToken
        || pendingRiskRowState.renderedRows !== renderedRows
      ) {
```

6. If the key originates from a real blank or unsupported source field, preserve the failing compact key and its validation reason for a targeted schema decision. Do not make every string valid or clear the entire open-row state on every click. A page reload can establish whether the invalid value was retained browser state, but a reload alone is not a persistent repair.

Expected: browser and tree use the same canonical key, all retained open keys pass the existing validation, and a mode change does not keep an obsolete pending browser action.

#### Case D: the action is accepted but the parent cannot expand

1. Read `tree decision`: `can_expand=False` means the builder found no remaining meaningful hierarchy level. `is_open=False` after an accepted opening action means the renderer did not receive the same key/open list.
2. For `is_open=False`, in `reduce_and_render_risk_view` preserve `effective_open_rows = sorted(set(opened))`, `updates[2] = effective_open_rows`, and `open_rows=effective_open_rows` in the final renderer call. In the recursive `build_tree_rows` call, pass the existing `open_rows` unchanged.
3. For `can_expand=False`, open `cube/ui/s02_aggregation.py::visible_tree_level`. Keep its tenor check limited to absent/placeholder axes (`""`, `"N/A"`, `"Spot"`, `"Unspecified"`). Do not skip a tenor level because the table is Full, because the number of labels exceeds a display preference, or because a Risk amount happens to be zero.
4. Compare `scoped_rows`, `swap_labels` and `option_labels` between the cold Full case and the working inherited Full case. If these differ despite unchanged filters/revision, inspect `_RiskDataCache.filtered` and its `reduced_tenor` cache-key member in `cube/pages/risk/s02_state.py`. The filter-cache key must include `bool(reduced_tenor)`.
5. For the main table, inspect the existing `cache.hierarchy_index(filtered, ...)` call in `render_active_risk_table`. It must receive this request's `filtered` frame. Inside `build_risk_table`, a supplied aggregation index and its `aggregation_index.frame` must stay together. Do not apply its row positions to a separately transformed Full/Reduced frame.
6. If an edited hierarchy cache uses only the Underlying or only the open-row state as its key, restore its source-frame identity plus the selected Credit measure key:

```python
        key = (id(frame), measure)
```

Do this only in `_RiskDataCache.hierarchy_index`, preserving the strong reference to `frame` in the retained cache entry, locking and byte limits. A bare object ID without the retained source reference is insufficient. Do not add Full/Reduced to financial quote identity; the filtered source frame already represents that display choice.
7. If the frame has the correct axes and `can_expand=True`, move to Case E. If the cold Full frame actually lacks the source tenor columns, this is an upstream preparation problem; preserve the compact counts and investigate where those columns disappear. Do not manufacture their labels from the Reduced output.

Expected: the same source scope produces the same Full tree whether it is opened directly or inherited from Reduced.

#### Case E: the shared visible-row budget is exhausted

1. Confirm `RISK_TENOR_TRACE budget exhausted` and inspect the parent's `remaining_before_parent`. A remaining value of 1 can display the parent but leave no room for a child.
2. In `s06_explorertables.py`, check that each top-level builder creates a **new local** budget once per render, before building TOTAL/children:

```python
    render_budget: dict[str, int | bool] = {
        "remaining": _EXPLORER_TREE_ROW_LIMIT,
        "truncated": False,
    }
```

3. Keep the **same** budget object in that tree's recursive calls. Do not reuse yesterday's or a previous click's budget from a cache or module variable, and do not create a fresh budget for each child.
4. Keep `*_tree_limit_notice(render_budget),` in the final child list of each top-level wrapper so that omissions are disclosed. If the note is missing, add this call after the rows have been built; do not hide it with CSS.
5. Narrow the selection or collapse unrelated branches and repeat the cold Full opening. The branch should now open if the budget was the only cause.
6. Keep the guard enabled. Raising the limit until a large hierarchy happens to render is not a safe repair for 100k positions. If normal browsing repeatedly reaches the limit, the next enhancement is paging within a selected hierarchy branch. That is separate from correcting a lost click.

Financial TOTAL and parent totals must always use the complete filtered frame. Do not apply `.head(...)`, row slicing, tenor reduction or portfolio removal to the source frame to satisfy a display budget.

#### Case F: children were built but are not visible

1. Use the browser's element inspector to look beneath the affected row for tenor child rows. Compare their existence with the application's `tree decision` and callback error log.
2. If the rows exist, inspect inherited `display`, `visibility`, `hidden` and overflow rules on the rows/wrapper. Risk Explorer descendants are constructed by the server only when open; an unrelated client-side Quick Risk/P&L hiding rule must not hide these rows.
3. If the rows do not exist but the log says the parent is open and expandable with budget remaining, inspect the callback response/error log for a serialization exception. Keep the error visible; do not catch it and silently return the previous table.
4. In `s07_explorer.py`, the Risk Explorer paths after the cache simplification should call `cache.render_explorer(build_main_component)` or `cache.render_explorer(build_alt_component)`. A source copy from before that simplification still calls `cache.rendered(render_key, ...)`; this is not by itself evidence of the lost-click cause. Its key must include both `open_rows` and the full `view_token`, which includes tenor mode. First confirm whether a stale component is actually being returned.
5. If the simplification was partially applied, check for `_RiskDataCache.render_explorer` in `cube/pages/risk/s02_state.py` before changing the callers. If absent, add this method immediately before the existing `rendered` method, preserving the class indentation and its existing `_render_compute_lock`:

```python
    def render_explorer(self, build: Callable[[], Any]) -> Any:
        """Build the visible table without retaining its component tree."""
        with self._render_compute_lock:
            return build()
```

6. In `render_active_risk_table`, replace only these two returns if they still use `cache.rendered`:

```python
            return no_update, cache.render_explorer(build_alt_component)
```

```python
        return cache.render_explorer(build_main_component), no_update
```

7. Remove only the now-unused `render_key = json.dumps(...)` blocks belonging to those two return paths. Preserve other panels' caches, retained-index byte limits, committed matrix retrieval and all reduction logic. This correction avoids retaining obsolete table presentations; it does not prove a click was accepted, so repeat the event trace afterwards.

Expected: the table returned for the accepted action contains its requested children and the browser displays those same rows.

### 8. Check the repair from a cold start and remove diagnostics

1. Restart the application and open a fresh browser tab.
2. Select Full first, then open and close the known Underlying repeatedly. Tenors must open immediately without a prior Reduced selection.
3. Repeat in Reduced, switch in both directions, and open a different Underlying. Parent keys may remain open across modes; the leaf labels must correspond to the selected mode.
4. Repeat in the main table, alternative table and Credit Multi where applicable. Apply one filter change and repeat. An old in-flight click must still be rejected after a genuine generation change.
5. Confirm totals are unchanged by expansion/collapse. Confirm no missing quote was changed to zero. Keep authoritative source tenor order and preserve the complete MarketBook, including tenors that have quotes but no current Risk positions. Risk hierarchy presentation must not trim the independent MarketBook.
6. Retain the shared visible-row budget and its notice. Confirm a narrowed Full branch is reachable when a broad view reaches that budget.
7. Remove every block between `BEGIN TEMPORARY TENOR TRACE` and `END TEMPORARY TENOR TRACE` in the three files. The refactored row branch may remain if its acceptance rules are unchanged; remove its logging-only `token_parts` helper together with the marked block.
8. Remove `CUBE_RISK_TRACE` and `CUBE_RISK_TRACE_LABEL` from the launch environment. Remove only imports newly added for diagnostics if no remaining code uses them. Do not remove existing logging used elsewhere.
9. Run the following cell and restart once more:

```python
for relative in FT_FILES:
    source = (FT_ROOT / relative).read_text(encoding="utf-8")
    assert "RISK_TENOR_TRACE" not in source, relative
    assert "CUBE_RISK_TRACE" not in source, relative
    if relative.endswith(".py"):
        ast.parse(source, filename=relative)
        print("Syntax OK:", relative)
print("Temporary trace code removed.")
```

10. Repeat the cold Full opening after removing diagnostics. Syntax checks confirm that Python can parse the edited files; the browser sequence establishes whether this specific interaction works.

If the sequence still fails, retain the compact browser/server/tree observations before removing the temporary blocks: mode, action sequence, validation flags, changed token field names, exact hierarchy key, `is_open`, `can_expand`, next group, counts and budget status. Those observations identify the failing boundary without requiring the complete position dataset.

### 9. Roll back only if a diagnostic edit prevents startup

Stop the application process. Run this cell to restore the backed-up source files, then restart with the usual launcher. This removes all edits made to those files since the backup; use it before unrelated work is added to them.

```python
for relative in FT_FILES:
    source = (FT_BACKUP / relative).resolve()
    target = (FT_ROOT / relative).resolve()
    assert source.is_relative_to(FT_BACKUP.resolve())
    assert target.is_relative_to(FT_ROOT)
    assert source.is_file()
    shutil.copy2(source, target)
print("Restored the source files from:", FT_BACKUP)
```

Keep data archives, source tenor definitions and risk/market adapters unchanged during this interaction diagnosis.

<a id="bulk-market"></a>

## Chapter 4 — Add the bulk market adapter calls

This change reduces external market calls. It does not change Risk aggregation, financial formulae, tenor reduction, or the amount of market history stored. A bulk call means sending a list of requested quote identities together and receiving one DataFrame for the leg. There is one Open call and one Current call for each refreshed product, subject to the existing retry settings. Open and Current can require different dates and sources, so they remain separate calls.

FX Delta already has bulk hooks in the starting application. Its request is `("EURUSD", "USDJPY")`. Commodity Delta and Commodity Vega are curves: their request must instead be `(("Oil", "Jun-27"), ("Gas", "Sep-27"))`. These are two exact pairs, not four combinations. Do not send `(Oil, Sep-27)` or `(Gas, Jun-27)` unless those pairs are actually needed or exist in the source catalogue.

The request is the union of full raw Risk quote pairs, exact supplemental Cross Gamma/New Trades pairs, and the source-owned quote catalogue for the selected raw Underlyings on both market dates. The catalogue preserves quoted tenors with no Risk position. It is metadata, not a quote table copied from the UI. Never build a market request from Reduced tenors, Reported Underlying, a currently expanded table, Portfolio, or a displayed page. Switching Full/Reduced must not change the market request.

The full quote universe here means all source-owned tenors of the requested raw Underlyings. It does not silently request every Underlying in the entire provider. If the business requires additional market-only Underlyings, supply them explicitly in the authoritative requested scope as a separate requirement.

### Before editing

1. Stop only your own preview app process. Leave source data and archive files alone.
2. Set APP_ROOT below to the folder containing `app.py`, `cube` and `assets`. If APP_ROOT is already correct in your notebook, keep that value. Run the complete helper and backup cell once. It is self-contained and uses ordinary Python; no terminal commands are required. Each replacement cell below identifies an exact old block, an exact replacement and its source file. If an old block is absent because your implementation differs, inspect that named symbol and make the same local change. Do not replace an entire service module with a baseline copy.
3. Keep the printed backup folder until the feature works.

```python
from pathlib import Path
import ast
import datetime as dt
import os
import shutil
import sys
import tempfile

APP_ROOT = (Path.cwd() / "Rebirth").resolve()  # Set this to your real application folder.
assert (APP_ROOT / "app.py").is_file(), APP_ROOT
assert (APP_ROOT / "cube").is_dir(), APP_ROOT
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

BULK_FILES = [
    "cube/domain/s02_products.py",
    "cube/adapters/s01_common.py",
    "cube/domain/s04_crossgamma.py",
    "cube/domain/s05_newtrades.py",
    "cube/services/s06_refresh.py",
    "cube/services/s05_sources.py",
]
BULK_BACKUP = APP_ROOT.parent / (
    "rebirth_bulk_backup_" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
)
BULK_BACKUP.mkdir()
for relative in BULK_FILES:
    source_path = APP_ROOT / relative
    assert source_path.is_file(), source_path
    backup_path = BULK_BACKUP / relative
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, backup_path)
print("Backup:", BULK_BACKUP)

def bulk_replace(relative, old, new):
    path = (APP_ROOT / relative).resolve()
    if not path.is_relative_to(APP_ROOT) or relative not in BULK_FILES:
        raise ValueError("Unexpected source path")
    text = path.read_text(encoding="utf-8")
    if new in text:
        print("Already present:", relative)
        return
    if text.count(old) != 1:
        raise ValueError(f"Expected one old block in {relative}; found {text.count(old)}")
    updated = text.replace(old, new, 1)
    ast.parse(updated, filename=str(path))
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     suffix=".tmp", delete=False) as handle:
        handle.write(updated)
        temporary_path = Path(handle.name)
    os.replace(temporary_path, path)
    print("Updated:", relative)

def bulk_check_syntax():
    for relative in BULK_FILES:
        path = APP_ROOT / relative
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        print("Syntax OK:", relative)
```

4. Keep all existing ProductSpec declarations. Commodity Delta remains `commo/delta`, a Tenor Swap curve using its existing percentage-move formula. Commodity Vega remains `commo/vega`, a Tenor Swap curve using its existing absolute-move formula. FX Delta remains scalar. Adding bulk I/O is not permission to change quote units, multipliers or formulae.
5. Keep `cube/adapters/s05_commodities.py::build_commo_adapter`, `cube/adapters/s03_fx.py::build_fx_adapters` and the single-Underlying functions. The active source factory binds ProductConnectorAdapter directly. The optional bulk fields override only the quote leg they provide; existing Risk and fallback functions stay available. A site factory using those builder functions can attach the same optional fields with `dataclasses.replace`.

6. If your current application has `ProductRiskBundle`, `ProductRiskResult`, dated tenor matrices or a `reduced_tenor_catalog` manager argument, keep them. Keep the existing Risk callable and its matrix bundle unchanged. Keep supplemental loaders receiving `supplemental_risk_date` when that is already implemented. None of the following quote edits requires changing Risk dates, matrix dates or the reduction catalogue.

### Apply these source edits in order

Run each cell once, in the order shown. A successful replacement prints its named file. No source data is loaded by these editing cells.

#### Bulk edit 01 — Extend the existing bulk contract

File: `cube/domain/s02_products.py`. Keep the existing bulk field names. FX Delta still receives an ordered tuple of raw Underlyings. Commodity Delta and Vega instead receive an ordered tuple of exact (raw Underlying, Tenor Swap) pairs. The metadata hook discovers market-only tenors for the requested Underlyings on either market date.

```python
bulk_replace(
    'cube/domain/s02_products.py',
    '''class ProductBulkMarketConnector(Protocol):
    """One source-bound connector for an ordered set of Underlyings."""

    def __call__(
        self,
        source_date: pd.Timestamp,
        underlyings: tuple[str, ...],
        *,
        market_status: str,
    ) -> pd.DataFrame: ...''',
    '''class ProductBulkMarketConnector(Protocol):
    """FX Delta takes Underlyings; Commodity Delta/Vega take exact quote pairs."""

    def __call__(
        self,
        source_date: pd.Timestamp,
        request: tuple[str, ...] | tuple[tuple[str, str], ...],
        *,
        market_status: str,
    ) -> pd.DataFrame: ...


class ProductMarketTenorScope(Protocol):
    """Return the union of source-owned quote identities for both market dates."""

    def __call__(
        self,
        open_date: pd.Timestamp,
        market_date: pd.Timestamp,
        underlyings: tuple[str, ...],
        *,
        market_status: str,
    ) -> tuple[tuple[str, str], ...]: ...''',
)
```

#### Bulk edit 02 — Add the optional tenor catalogue hook

File: `cube/domain/s02_products.py`. Add the optional field after the existing two bulk fields. Existing adapters remain valid. Commodity adapters using either bulk quote hook must supply the tenor catalogue hook.

```python
bulk_replace(
    'cube/domain/s02_products.py',
    '''    market_status_bulk: ProductBulkMarketConnector | None = None''',
    '''    market_status_bulk: ProductBulkMarketConnector | None = None
    market_tenor_scope: ProductMarketTenorScope | None = None''',
)
```

#### Bulk edit 03 — Correct the adapter documentation

File: `cube/domain/s02_products.py`. Replace the obsolete FX-only paragraph. Keep the Risk, single-Underlying market, date, status, schema and uniqueness contracts around it unchanged.

```python
bulk_replace(
    'cube/domain/s02_products.py',
    '''        Optional FX-Delta-only equivalents which receive the complete ordered,
        unique Underlying tuple and return the concatenated leg in one upstream
        call. When configured, the manager prefers the bulk hook to the matching
        per-Underlying hook. Other products deliberately retain their normal
        connector path.''',
    '''        Optional equivalents preferred to the matching per-Underlying hook.
        FX Delta receives the ordered unique Underlying tuple. Commodity Delta
        and Vega receive exact (Underlying, Tenor Swap) pairs. They also require
        market_tenor_scope(open_date, market_date, underlyings, *, market_status)
        to preserve the complete source-owned quote universe for the selected
        Underlyings, including quote tenors with no Risk position. Other
        products retain their existing connector path.''',
)
```

#### Bulk edit 04 — Add one small pair validator

File: `cube/adapters/s01_common.py`. Insert this helper immediately before market_frame. Do not change market_frame, exact_frame, exact_status, or the single-Underlying adapter functions. This validates request identity only; quote values and authoritative tenor ranks still go through the existing product validators.

```python
bulk_replace(
    'cube/adapters/s01_common.py',
    '''def market_frame(
''',
    '''def exact_market_pairs(value: object) -> tuple[tuple[str, str], ...]:
    """Validate exact raw Underlying/tenor identity; preserve source order."""
    if not isinstance(value, tuple):
        raise TypeError("market pairs must be an ordered tuple")
    result = []
    seen = set()
    for pair in value:
        if not isinstance(pair, tuple) or len(pair) != 2:
            raise TypeError("each market pair must be (Underlying, Tenor Swap)")
        if any(not isinstance(v, str) or not v.strip() for v in pair):
            raise ValueError("Underlying and Tenor Swap must be nonblank text")
        clean = tuple(v.strip() for v in pair)
        if clean in seen:
            raise ValueError(f"duplicate requested market pair: {clean!r}")
        seen.add(clean)
        result.append(clean)
    return tuple(result)


def market_frame(
''',
)
```

#### Bulk edit 05 — Export the pair helper

File: `cube/adapters/s01_common.py`. Add exactly one name to the existing __all__ list.

```python
bulk_replace(
    'cube/adapters/s01_common.py',
    '''    "exact_frame",''',
    '''    "exact_frame",
    "exact_market_pairs",''',
)
```

#### Bulk edit 06 — Preserve supplemental Cross Gamma tenor pairs

File: `cube/domain/s04_crossgamma.py`. Keep cross_gamma_market_scope for existing products. Add its companion immediately after it. Read both the input and output market identities; do not use the release Risk Greek, reported Underlying, or a reduced tenor label.

```python
bulk_replace(
    'cube/domain/s04_crossgamma.py',
    '''def cross_gamma_market_scope(raw_or_validated: object) -> dict[str, tuple[str, ...]]:
    """Return ordered input/output Underlyings required from each MarketBook."""

    rows = validate_cross_gamma_rows(raw_or_validated)
    pair_catalogue = _product_by_pair()
    scope: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows.itertuples(index=False, name=None):
        values = dict(zip(CROSS_GAMMA_COLUMNS, row, strict=True))
        for type_column, greek_column, underlying_column in (
            (INPUT_RISK_TYPE, INPUT_RISK_GREEK, INPUT_UNDERLYING),
            (OUTPUT_RISK_TYPE, OUTPUT_RISK_GREEK, OUTPUT_UNDERLYING),
        ):
            spec = pair_catalogue[(values[type_column], values[greek_column])]
            underlying = values[underlying_column]
            if underlying not in scope[spec.source_type]:
                scope[spec.source_type].append(underlying)
    return {source_type: tuple(values) for source_type, values in scope.items()}''',
    '''def cross_gamma_market_scope(raw_or_validated: object) -> dict[str, tuple[str, ...]]:
    """Return ordered input/output Underlyings required from each MarketBook."""

    rows = validate_cross_gamma_rows(raw_or_validated)
    pair_catalogue = _product_by_pair()
    scope: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows.itertuples(index=False, name=None):
        values = dict(zip(CROSS_GAMMA_COLUMNS, row, strict=True))
        for type_column, greek_column, underlying_column in (
            (INPUT_RISK_TYPE, INPUT_RISK_GREEK, INPUT_UNDERLYING),
            (OUTPUT_RISK_TYPE, OUTPUT_RISK_GREEK, OUTPUT_UNDERLYING),
        ):
            spec = pair_catalogue[(values[type_column], values[greek_column])]
            underlying = values[underlying_column]
            if underlying not in scope[spec.source_type]:
                scope[spec.source_type].append(underlying)
    return {source_type: tuple(values) for source_type, values in scope.items()}


def cross_gamma_market_pair_scope(
    raw_or_validated: object,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Keep Commodity input AND output tenor identity from the raw matrix."""
    rows = validate_cross_gamma_rows(raw_or_validated)
    catalogue = _product_by_pair()
    scope = {}
    for row in rows.to_dict("records"):
        for type_col, greek_col, underlying_col, tenor_col in (
            (INPUT_RISK_TYPE, INPUT_RISK_GREEK, INPUT_UNDERLYING, INPUT_TENOR_SWAP),
            (OUTPUT_RISK_TYPE, OUTPUT_RISK_GREEK, OUTPUT_UNDERLYING, OUTPUT_TENOR_SWAP),
        ):
            spec = catalogue[(row[type_col], row[greek_col])]
            if spec.source_type not in {"commo/delta", "commo/vega"}:
                continue
            values = scope.setdefault(spec.source_type, [])
            pair = (row[underlying_col], row[tenor_col])
            if pair not in values:
                values.append(pair)
    return {source: tuple(values) for source, values in scope.items()}''',
)
```

#### Bulk edit 07 — Preserve supplemental New Trades tenor pairs

File: `cube/domain/s05_newtrades.py`. Keep new_trade_market_scope. Add its companion after it. CASHFLOW rows do not request market quotes. An existing position is not required for a MARKET trade to request its quote.

```python
bulk_replace(
    'cube/domain/s05_newtrades.py',
    '''def new_trade_market_scope(raw_or_validated: object) -> dict[str, tuple[str, ...]]:
    """Return ordered ProductSpec/Underlying scope required by MARKET trades."""

    rows = validate_new_trade_rows(raw_or_validated)
    pairs, _ = _product_catalogue()
    scope: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows.loc[rows[ROW_TYPE].eq(MARKET)].to_dict("records"):
        spec = pairs[(row[RISK_TYPE], row[RISK_GREEK])]
        underlying = row[UNDERLYING]
        if underlying not in scope[spec.source_type]:
            scope[spec.source_type].append(underlying)
    return {source_type: tuple(values) for source_type, values in scope.items()}''',
    '''def new_trade_market_scope(raw_or_validated: object) -> dict[str, tuple[str, ...]]:
    """Return ordered ProductSpec/Underlying scope required by MARKET trades."""

    rows = validate_new_trade_rows(raw_or_validated)
    pairs, _ = _product_catalogue()
    scope: defaultdict[str, list[str]] = defaultdict(list)
    for row in rows.loc[rows[ROW_TYPE].eq(MARKET)].to_dict("records"):
        spec = pairs[(row[RISK_TYPE], row[RISK_GREEK])]
        underlying = row[UNDERLYING]
        if underlying not in scope[spec.source_type]:
            scope[spec.source_type].append(underlying)
    return {source_type: tuple(values) for source_type, values in scope.items()}


def new_trade_market_pair_scope(
    raw_or_validated: object,
) -> dict[str, tuple[tuple[str, str], ...]]:
    """Keep exact Commodity tenor pairs from MARKET rows only."""
    rows = validate_new_trade_rows(raw_or_validated)
    catalogue, _ = _product_catalogue()
    scope = {}
    for row in rows.loc[rows[ROW_TYPE].eq(MARKET)].to_dict("records"):
        spec = catalogue[(row[RISK_TYPE], row[RISK_GREEK])]
        if spec.source_type not in {"commo/delta", "commo/vega"}:
            continue
        values = scope.setdefault(spec.source_type, [])
        pair = (row[UNDERLYING], row[TENOR_SWAP])
        if pair not in values:
            values.append(pair)
    return {source: tuple(values) for source, values in scope.items()}''',
)
```

#### Bulk edit 08 — Import the pair helper and canonical tenor name

File: `cube/services/s06_refresh.py`. Add these two imports after pandas. Do not import any UI reduction function into the refresh service.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''import pandas as pd
''',
    '''import pandas as pd

from cube.adapters.s01_common import exact_market_pairs
from cube.domain.s01_schema import TENOR_SWAP
''',
)
```

#### Bulk edit 09 — Import supplemental Cross Gamma scope

File: `cube/services/s06_refresh.py`. Add the new function to the existing domain import block.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''    cross_gamma_market_scope,''',
    '''    cross_gamma_market_scope,
    cross_gamma_market_pair_scope,''',
)
```

#### Bulk edit 10 — Import supplemental New Trades scope

File: `cube/services/s06_refresh.py`. Add the new function to the existing domain import block.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''    new_trade_market_scope,''',
    '''    new_trade_market_scope,
    new_trade_market_pair_scope,''',
)
```

#### Bulk edit 11 — Allow exactly the three requested products

File: `cube/services/s06_refresh.py`. Replace the FX-only rejection. Keep all existing required-hook checks, optional-hook callable checks and unknown-product checks. Requiring a Commodity catalogue avoids silently dropping quoted tenors that have no position.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''            if source_type != "fx/delta" and any(bulk_hooks.values()):
                raise ValueError(
                    "bulk market connector hooks are supported only for 'fx/delta'; "
                    f"found bulk hook on {source_type!r}"
                )''',
    '''            has_bulk = any(connector is not None for connector in bulk_hooks.values())
            if source_type not in {"fx/delta", "commo/delta", "commo/vega"} and has_bulk:
                raise ValueError(f"bulk market hooks are unsupported for {source_type!r}")
            scope_hook = adapter.market_tenor_scope
            if scope_hook is not None and not callable(scope_hook):
                raise TypeError(f"market_tenor_scope is not callable for {source_type!r}")
            if source_type in {"commo/delta", "commo/vega"} and has_bulk and scope_hook is None:
                raise ValueError(
                    f"{source_type!r} bulk quotes require market_tenor_scope "
                    "to preserve market-only tenor identities"
                )''',
)
```

#### Bulk edit 12 — Keep the bulk executor shared

File: `cube/services/s06_refresh.py`. Only correct its old FX-only description. Keep the implementation of _load_bulk_market_frame, including retries, timeout, budget, progress, error handling and returned Underlying checks.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''        """Call one optional FX-Delta bulk connector for a complete market leg."""''',
    '''        """Call one optional product bulk connector for a complete market leg."""''',
)
```

#### Bulk edit 13 — Pass exact pairs through _load_product_market_open

File: `cube/services/s06_refresh.py`. Replace this complete method. The same retry, timeout, elapsed budget, circuit and progress machinery remains in use. FX receives exactly its previous Underlying tuple. Commodity receives quote_pairs. The fallback single-Underlying calls remain unchanged; never add one call per Portfolio or a nested Underlying-by-tenor loop.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''    def _load_product_market_open(
        self,
        spec: ProductSpec,
        open_date: pd.Timestamp,
        underlyings: tuple[str, ...],
        *,
        market_status: str,
        circuit: _OperationalCircuitBreaker | None = None,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        # PRODUCTION INTEGRATION POINT: every Open adapter receives the one
        # authoritative T-1 business date. It is independent of any older
        # per-product Risk date produced by readiness Age or a force override.
        adapter = self._connector_adapters.get(spec.source_type)
        bulk_connector = adapter.market_open_bulk if adapter is not None else None
        selected_status = _require_market_status(market_status)
        if bulk_connector is not None:
            return self._load_bulk_market_frame(
                spec,
                underlyings,
                connector=bulk_connector,
                stage="market_open",
                label="Open",
                load_bulk=lambda: bulk_connector(
                    open_date,
                    underlyings,
                    market_status=selected_status,
                ),
                circuit=circuit,
                budget=budget,
            )
        connector = (
            adapter.market_open if adapter is not None else self._market_open_loader
        )

        def load_one(underlying: str) -> object:
            if adapter is not None:
                return adapter.market_open(
                    open_date, underlying, market_status=selected_status
                )
            return self._market_open_loader(
                spec.source_type,
                open_date,
                underlying,
                market_status=selected_status,
            )

        return self._load_market_frames(
            spec,
            underlyings,
            connector=connector,
            stage="market_open",
            label="Open",
            load_one=load_one,
            circuit=circuit,
            budget=budget,
        )''',
    '''    def _load_product_market_open(
        self,
        spec: ProductSpec,
        open_date: pd.Timestamp,
        underlyings: tuple[str, ...],
        *,
        market_status: str,
        quote_pairs: tuple[tuple[str, str], ...] = (),
        circuit: _OperationalCircuitBreaker | None = None,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        # PRODUCTION INTEGRATION POINT: every Open adapter receives the one
        # authoritative T-1 business date. It is independent of any older
        # per-product Risk date produced by readiness Age or a force override.
        adapter = self._connector_adapters.get(spec.source_type)
        bulk_connector = adapter.market_open_bulk if adapter is not None else None
        selected_status = _require_market_status(market_status)
        if bulk_connector is not None and spec.source_type in {"commo/delta", "commo/vega"}:
            quote_pairs = exact_market_pairs(quote_pairs)
            if underlyings and not quote_pairs:
                raise ValueError("Commodity bulk request is missing exact tenor pairs")
        if bulk_connector is not None:
            return self._load_bulk_market_frame(
                spec,
                underlyings,
                connector=bulk_connector,
                stage="market_open",
                label="Open",
                load_bulk=lambda: bulk_connector(
                    open_date,
                    (quote_pairs if spec.source_type in {"commo/delta", "commo/vega"} else underlyings),
                    market_status=selected_status,
                ),
                circuit=circuit,
                budget=budget,
            )
        connector = (
            adapter.market_open if adapter is not None else self._market_open_loader
        )

        def load_one(underlying: str) -> object:
            if adapter is not None:
                return adapter.market_open(
                    open_date, underlying, market_status=selected_status
                )
            return self._market_open_loader(
                spec.source_type,
                open_date,
                underlying,
                market_status=selected_status,
            )

        return self._load_market_frames(
            spec,
            underlyings,
            connector=connector,
            stage="market_open",
            label="Open",
            load_one=load_one,
            circuit=circuit,
            budget=budget,
        )''',
)
```

#### Bulk edit 14 — Pass exact pairs through _load_product_market_status

File: `cube/services/s06_refresh.py`. Replace this complete method. The same retry, timeout, elapsed budget, circuit and progress machinery remains in use. FX receives exactly its previous Underlying tuple. Commodity receives quote_pairs. The fallback single-Underlying calls remain unchanged; never add one call per Portfolio or a nested Underlying-by-tenor loop.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''    def _load_product_market_status(
        self,
        spec: ProductSpec,
        market_date: pd.Timestamp,
        underlyings: tuple[str, ...],
        *,
        market_status: str,
        circuit: _OperationalCircuitBreaker | None = None,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        # PRODUCTION INTEGRATION POINT: the injected callable selects Live for
        # today and OFFICIAL for prior views, then returns the normalized leg.
        adapter = self._connector_adapters.get(spec.source_type)
        bulk_connector = adapter.market_status_bulk if adapter is not None else None
        selected_status = _require_market_status(market_status)
        if bulk_connector is not None:
            return self._load_bulk_market_frame(
                spec,
                underlyings,
                connector=bulk_connector,
                stage="market_status",
                label=selected_status,
                load_bulk=lambda: bulk_connector(
                    market_date,
                    underlyings,
                    market_status=selected_status,
                ),
                circuit=circuit,
                budget=budget,
            )
        connector = (
            adapter.market_status if adapter is not None else self._market_status_loader
        )

        def load_one(underlying: str) -> object:
            if adapter is not None:
                return adapter.market_status(
                    market_date, underlying, market_status=selected_status
                )
            return self._market_status_loader(
                spec.source_type,
                market_date,
                underlying,
                market_status=selected_status,
            )

        return self._load_market_frames(
            spec,
            underlyings,
            connector=connector,
            stage="market_status",
            label=selected_status,
            load_one=load_one,
            circuit=circuit,
            budget=budget,
        )''',
    '''    def _load_product_market_status(
        self,
        spec: ProductSpec,
        market_date: pd.Timestamp,
        underlyings: tuple[str, ...],
        *,
        market_status: str,
        quote_pairs: tuple[tuple[str, str], ...] = (),
        circuit: _OperationalCircuitBreaker | None = None,
        budget: _ConnectorRefreshBudget | None = None,
    ) -> pd.DataFrame:
        # PRODUCTION INTEGRATION POINT: the injected callable selects Live for
        # today and OFFICIAL for prior views, then returns the normalized leg.
        adapter = self._connector_adapters.get(spec.source_type)
        bulk_connector = adapter.market_status_bulk if adapter is not None else None
        selected_status = _require_market_status(market_status)
        if bulk_connector is not None and spec.source_type in {"commo/delta", "commo/vega"}:
            quote_pairs = exact_market_pairs(quote_pairs)
            if underlyings and not quote_pairs:
                raise ValueError("Commodity bulk request is missing exact tenor pairs")
        if bulk_connector is not None:
            return self._load_bulk_market_frame(
                spec,
                underlyings,
                connector=bulk_connector,
                stage="market_status",
                label=selected_status,
                load_bulk=lambda: bulk_connector(
                    market_date,
                    (quote_pairs if spec.source_type in {"commo/delta", "commo/vega"} else underlyings),
                    market_status=selected_status,
                ),
                circuit=circuit,
                budget=budget,
            )
        connector = (
            adapter.market_status if adapter is not None else self._market_status_loader
        )

        def load_one(underlying: str) -> object:
            if adapter is not None:
                return adapter.market_status(
                    market_date, underlying, market_status=selected_status
                )
            return self._market_status_loader(
                spec.source_type,
                market_date,
                underlying,
                market_status=selected_status,
            )

        return self._load_market_frames(
            spec,
            underlyings,
            connector=connector,
            stage="market_status",
            label=selected_status,
            load_one=load_one,
            circuit=circuit,
            budget=budget,
        )''',
)
```

#### Bulk edit 15 — Add pair request construction and returned-scope checks

File: `cube/services/s06_refresh.py`. Insert these two methods before the existing Underlying scope rejection. Deduplicating request identities is correct: many positions share a quote. Do not deduplicate returned quotes to hide a provider error. Missing requested pairs are permitted and remain missing.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''    @staticmethod
    def _reject_unrequested_market_underlyings(''',
    '''    @staticmethod
    def _requested_market_pairs(
        risk_frame: pd.DataFrame,
        supplemental: tuple[tuple[str, str], ...],
        universe: tuple[tuple[str, str], ...],
        underlyings: tuple[str, ...],
    ) -> tuple[tuple[str, str], ...]:
        """Union exact full Risk, supplemental and source-catalogue identities."""
        raw_pairs = tuple(
            risk_frame[[UNDERLYING, TENOR_SWAP]]
            .drop_duplicates()
            .itertuples(index=False, name=None)
        )
        parts = (exact_market_pairs(raw_pairs), exact_market_pairs(supplemental),
                 exact_market_pairs(universe))
        result = tuple(dict.fromkeys(pair for part in parts for pair in part))
        extra = sorted({pair[0] for pair in result} - set(underlyings))
        if extra:
            raise ValueError(f"market tenor scope returned unrequested Underlyings: {extra[:5]}")
        return result

    @staticmethod
    def _reject_unrequested_market_pairs(
        frame: pd.DataFrame,
        requested: tuple[tuple[str, str], ...],
        *,
        label: str,
    ) -> None:
        actual = set(frame[[UNDERLYING, TENOR_SWAP]].itertuples(index=False, name=None))
        extra = sorted(actual - set(requested))
        if extra:
            raise ValueError(f"{label} returned unrequested market pairs: {extra[:5]}")

    @staticmethod
    def _reject_unrequested_market_underlyings(''',
)
```

#### Bulk edit 16 — Keep supplemental pairs for this refresh only

File: `cube/services/s06_refresh.py`. Add a request-local mapping beside supplemental_market_scope. It exists only for the current refresh. No global cache or browser state is involved.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                supplemental_market_scope: dict[str, list[str]] = {}''',
    '''                supplemental_market_scope: dict[str, list[str]] = {}
                supplemental_market_pairs: dict[str, tuple[tuple[str, str], ...]] = {}

                def add_supplemental_pairs(scope):
                    for source_type, pairs in scope.items():
                        old_pairs = supplemental_market_pairs.get(source_type, ())
                        supplemental_market_pairs[source_type] = tuple(
                            dict.fromkeys((*old_pairs, *exact_market_pairs(pairs)))
                        )''',
)
```

#### Bulk edit 17 — Collect the supplemental exact pairs

File: `cube/services/s06_refresh.py`. Keep the original Underlying scope call and add this call immediately after it. Do not call the raw external loader again.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                    add_supplemental_scope(cross_gamma_market_scope(raw_cross_gamma))''',
    '''                    add_supplemental_scope(cross_gamma_market_scope(raw_cross_gamma))
                    add_supplemental_pairs(cross_gamma_market_pair_scope(raw_cross_gamma))''',
)
```

#### Bulk edit 18 — Collect the supplemental exact pairs

File: `cube/services/s06_refresh.py`. Keep the original Underlying scope call and add this call immediately after it. Do not call the raw external loader again.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                    add_supplemental_scope(new_trade_market_scope(raw_new_trades))''',
    '''                    add_supplemental_scope(new_trade_market_scope(raw_new_trades))
                    add_supplemental_pairs(new_trade_market_pair_scope(raw_new_trades))''',
)
```

#### Bulk edit 19 — Build one authoritative Commodity scope before market calls

File: `cube/services/s06_refresh.py`. Insert this block after the supplemental loaders and before the existing scope-reuse comment. next_risk holds validated unreduced source Risk. The catalogue contributes the union of Open-date and Current-date quote identities for the requested raw Underlyings. Keep market-only tenors. Compare against the previous immutable REQUEST identity stored on each leg, not the rows returned: legitimately missing quotes must not force unnecessary refreshes. A changed tenor within the same Underlying still invalidates the affected cache. Catalogue I/O uses the existing timeout and elapsed budget. An ordinary catalogue outage marks only that Commodity product unavailable; the next edit uses its existing product circuit to prevent a misleading Risk-only quote fetch. Contract errors still abort atomically.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                # Supplemental identities may expand or shrink between
''',
    '''                # Resolve one full quote identity catalogue per enabled bulk Commodity.
                commodity_bulk_pairs = {}
                commodity_scope_errors = {}
                if commodity_market_enabled:
                    for source_type in ("commo/delta", "commo/vega"):
                        adapter = self._connector_adapters.get(source_type)
                        if adapter is None or (
                            adapter.market_open_bulk is None
                            and adapter.market_status_bulk is None
                        ):
                            continue
                        underlyings = self._requested_market_underlyings(
                            next_risk[source_type],
                            supplemental_market_scope.get(source_type, ()),
                        )
                        if underlyings:
                            try:
                                universe = self._call_connector(
                                    ("market", "tenor_scope", source_type),
                                    lambda adapter=adapter, underlyings=underlyings: adapter.market_tenor_scope(
                                        checker_date,
                                        market_date,
                                        underlyings,
                                        market_status=expected_market_status,
                                    ),
                                    budget=connector_budget,
                                )
                            except Exception as error:
                                if not self._is_operational_connector_error(error):
                                    raise
                                commodity_scope_errors[source_type] = error
                                universe = ()
                                self._log_operational_failure(
                                    boundary="Commodity tenor catalogue",
                                    error=error,
                                    source_type=source_type,
                                    stage="market",
                                )
                                if isinstance(error, ConnectorRefreshBudgetError):
                                    risk_circuit.trip(error)
                                    market_circuit.trip(error)
                        else:
                            universe = ()
                        pairs = self._requested_market_pairs(
                            next_risk[source_type],
                            supplemental_market_pairs.get(source_type, ()),
                            universe,
                            underlyings,
                        )
                        commodity_bulk_pairs[source_type] = pairs
                        # A changed tenor within the same Underlying also needs new quotes.
                        expected_pairs = set(pairs)
                        for frames, refresh_types in (
                            (next_open, open_source_types),
                            (next_status, market_status_source_types),
                        ):
                            existing = frames.get(source_type)
                            previous_request = None if existing is None else existing.attrs.get(
                                "cube_requested_market_pairs"
                            )
                            if (
                                source_type in commodity_scope_errors
                                or previous_request is None
                                or set(previous_request) != expected_pairs
                            ):
                                refresh_types.add(source_type)

                # Supplemental identities may expand or shrink between
''',
)
```

#### Bulk edit 20 — Avoid rechecking Commodity scope against returned Underlying rows

File: `cube/services/s06_refresh.py`. Add this short guard in the existing supplemental cache-reuse loop. Commodity bulk reuse is already decided from the saved requested pairs above. Otherwise a legitimately unavailable whole Underlying could still make the old row-based comparison refresh both legs repeatedly. All other products retain their previous reuse behavior.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                    for source_type in PRODUCT_SPECS_BY_SOURCE_TYPE:
                        requested_underlyings = self._requested_market_underlyings(''',
    '''                    for source_type in PRODUCT_SPECS_BY_SOURCE_TYPE:
                        if source_type in commodity_bulk_pairs:
                            continue  # The exact requested-pair comparison above owns reuse.
                        requested_underlyings = self._requested_market_underlyings(''',
)
```

#### Bulk edit 21 — Isolate a catalogue outage using the existing product circuit

File: `cube/services/s06_refresh.py`. Add these lines immediately after the existing per-product circuit mapping. The corresponding Commodity Open and Current loaders return unavailable legs without making quote calls. Other products continue unless the common elapsed budget is exhausted. Do not fetch an incomplete Risk-only universe after a failed catalogue read.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                product_market_circuits: dict[str, _OperationalCircuitBreaker] = {}''',
    '''                product_market_circuits: dict[str, _OperationalCircuitBreaker] = {}
                for source_type, scope_error in commodity_scope_errors.items():
                    failed_circuit = _OperationalCircuitBreaker()
                    failed_circuit.trip(scope_error)
                    product_market_circuits[source_type] = failed_circuit''',
)
```

#### Bulk edit 22 — Wire the open refresh call site

File: `cube/services/s06_refresh.py`. Add quote_pairs to this call without changing its date, status, circuit or budget arguments. Keep the existing market_open_calls / market_status_calls calculations: each configured bulk quote leg counts as one call, independent of positions and tenors. The catalogue is a separate bounded metadata call.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                        raw_open = self._load_product_market_open(
                            spec,
                            checker_date,
                            requested_underlyings,
                            market_status=expected_market_status,
                            circuit=market_batch_circuit(source_type),
                            budget=connector_budget,
                        )''',
    '''                        raw_open = self._load_product_market_open(
                            spec,
                            checker_date,
                            requested_underlyings,
                            market_status=expected_market_status,
                            quote_pairs=commodity_bulk_pairs.get(source_type, ()),
                            circuit=market_batch_circuit(source_type),
                            budget=connector_budget,
                        )''',
)
```

#### Bulk edit 23 — Wire the status refresh call site

File: `cube/services/s06_refresh.py`. Add quote_pairs to this call without changing its date, status, circuit or budget arguments. Keep the existing market_open_calls / market_status_calls calculations: each configured bulk quote leg counts as one call, independent of positions and tenors. The catalogue is a separate bounded metadata call.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                        raw_status = self._load_product_market_status(
                            spec,
                            market_date,
                            requested_underlyings,
                            market_status=expected_market_status,
                            circuit=market_batch_circuit(source_type),
                            budget=connector_budget,
                        )''',
    '''                        raw_status = self._load_product_market_status(
                            spec,
                            market_date,
                            requested_underlyings,
                            market_status=expected_market_status,
                            quote_pairs=commodity_bulk_pairs.get(source_type, ()),
                            circuit=market_batch_circuit(source_type),
                            budget=connector_budget,
                        )''',
)
```

#### Bulk edit 24 — Validate the returned open pair scope

File: `cube/services/s06_refresh.py`. Insert the pair-scope check after the existing product validator and Underlying check. Keep every existing uniqueness, numeric value, finite-value, status, tenor-rank and Open/Current merge guard. Store the immutable requested-pair tuple on this newly validated frame, never on a previous cached frame. A successful response may legitimately omit some quote pairs and still receives its request stamp. An operationally failed/skipped quote call or unavailable catalogue receives no successful stamp, so a later source-loading refresh can retry it. A response containing an unrequested pair is a connector error. Missing quotes remain unavailable, never zero.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                        next_open[source_type] = validated_open''',
    '''                        if source_type in commodity_bulk_pairs:
                            self._reject_unrequested_market_pairs(
                                validated_open,
                                commodity_bulk_pairs[source_type],
                                label=f"{spec.key} market open",
                            )
                            if (
                                source_type not in commodity_scope_errors
                                and not market_batch_circuit(source_type).is_open
                            ):
                                validated_open.attrs["cube_requested_market_pairs"] = (
                                    commodity_bulk_pairs[source_type]
                                )
                        next_open[source_type] = validated_open''',
)
```

#### Bulk edit 25 — Validate the returned status pair scope

File: `cube/services/s06_refresh.py`. Insert the pair-scope check after the existing product validator and Underlying check. Keep every existing uniqueness, numeric value, finite-value, status, tenor-rank and Open/Current merge guard. Store the immutable requested-pair tuple on this newly validated frame, never on a previous cached frame. A successful response may legitimately omit some quote pairs and still receives its request stamp. An operationally failed/skipped quote call or unavailable catalogue receives no successful stamp, so a later source-loading refresh can retry it. A response containing an unrequested pair is a connector error. Missing quotes remain unavailable, never zero.

```python
bulk_replace(
    'cube/services/s06_refresh.py',
    '''                        next_status[source_type] = validated_status''',
    '''                        if source_type in commodity_bulk_pairs:
                            self._reject_unrequested_market_pairs(
                                validated_status,
                                commodity_bulk_pairs[source_type],
                                label=f"{spec.key} market status",
                            )
                            if (
                                source_type not in commodity_scope_errors
                                and not market_batch_circuit(source_type).is_open
                            ):
                                validated_status.attrs["cube_requested_market_pairs"] = (
                                    commodity_bulk_pairs[source_type]
                                )
                        next_status[source_type] = validated_status''',
)
```

#### Bulk edit 26 — Import adapter replacement

File: `cube/services/s05_sources.py`. This lets the active factory retain its existing Risk and single-Underlying connector functions while attaching the optional bulk functions.

```python
bulk_replace(
    'cube/services/s05_sources.py',
    '''from datetime import datetime
''',
    '''from datetime import datetime
from dataclasses import replace
''',
)
```

#### Bulk edit 27 — Import request validation in the source boundary

File: `cube/services/s05_sources.py`. Reuse the same exact-pair validation at the external source boundary.

```python
bulk_replace(
    'cube/services/s05_sources.py',
    '''import pandas as pd
''',
    '''import pandas as pd

from cube.adapters.s01_common import exact_market_pairs
''',
)
```

#### Bulk edit 28 — Add Commodity bulk source boundaries

File: `cube/services/s05_sources.py`. Insert these functions before get_portfolio_config. The included bodies are runnable against the existing placeholder CSV data. They demonstrate exact schemas and request shaping; they are not a real desk provider. The next instructions explain precisely which small read blocks to replace for the real service. No cartesian product is constructed; Tenor Swap Order is returned by the source unchanged.

```python
bulk_replace(
    'cube/services/s05_sources.py',
    '''def get_portfolio_config(''',
    '''def get_commo_market_tenor_scope(
    source_type: str,
    open_date: pd.Timestamp,
    market_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> tuple[tuple[str, str], ...]:
    """Return full source-owned quote identity, including market-only tenors."""
    if source_type not in {"commo/delta", "commo/vega"}:
        raise ValueError("Commodity tenor scope requires a Commodity source")
    _business_date(open_date, parameter="open_date")
    _business_date(market_date, parameter="market_date")
    _market_status(market_status)
    requested = _bulk_underlying_scope(underlyings)
    # CSV example boundary: replace the two reads with your dated tenor catalogue.
    parts = [
        _source_rows(dataset, source_type, ["Underlying", "Tenor Swap"], allow_empty=True)
        for dataset in ("market_open", "market_status")
    ]
    universe = pd.concat(parts, ignore_index=True)
    universe = universe.loc[universe["Underlying"].isin(requested)]
    return exact_market_pairs(tuple(
        universe.drop_duplicates(["Underlying", "Tenor Swap"])
        .itertuples(index=False, name=None)
    ))


def _get_commo_market_bulk(
    dataset: str,
    source_type: str,
    source_date: pd.Timestamp,
    quote_pairs: tuple[tuple[str, str], ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    """Read a whole Commodity leg once and retain the requested exact pairs."""
    if dataset not in {"market_open", "market_status"}:
        raise ValueError("dataset must be market_open or market_status")
    if source_type not in {"commo/delta", "commo/vega"}:
        raise ValueError("Commodity bulk quotes require a Commodity source")
    parameter = "open_date" if dataset == "market_open" else "market_date"
    _business_date(source_date, parameter=parameter)
    selected_status = _market_status(market_status)
    pairs = exact_market_pairs(quote_pairs)
    spec = _source_spec(source_type)
    value_column = OPEN if dataset == "market_open" else CURRENT
    columns = [UNDERLYING, *spec.tenor_columns, *spec.tenor_order_columns, value_column]
    # CSV example boundary: replace this read/filter block with ONE provider request.
    frame = _source_rows(dataset, source_type, columns, allow_empty=True)
    rank = {pair: index for index, pair in enumerate(pairs)}
    pair_index = pd.MultiIndex.from_frame(frame[[UNDERLYING, "Tenor Swap"]])
    requested_index = pd.MultiIndex.from_tuples(pairs, names=[UNDERLYING, "Tenor Swap"])
    frame = frame.loc[pair_index.isin(requested_index)].copy()
    if not frame.empty:
        frame["__request_order"] = [rank[pair] for pair in frame[[UNDERLYING, "Tenor Swap"]].itertuples(index=False, name=None)]
        frame = frame.sort_values("__request_order", kind="stable").drop(columns="__request_order")
    _require_temp_notice(frame, [UNDERLYING, *spec.tenor_columns], dataset=dataset)
    if dataset == "market_status":
        frame[MARKET_STATUS] = selected_status
    return frame.reset_index(drop=True)


def get_commo_market_open_bulk(
    source_type: str,
    open_date: pd.Timestamp,
    quote_pairs: tuple[tuple[str, str], ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    return _get_commo_market_bulk(
        "market_open", source_type, open_date, quote_pairs, market_status=market_status
    )


def get_commo_market_status_bulk(
    source_type: str,
    market_date: pd.Timestamp,
    quote_pairs: tuple[tuple[str, str], ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    return _get_commo_market_bulk(
        "market_status", source_type, market_date, quote_pairs, market_status=market_status
    )


def get_portfolio_config(''',
)
```

#### Bulk edit 29 — Attach both Commodity adapters to the actual factory

File: `cube/services/s05_sources.py`. Replace the complete get_product_connector_adapters function. The default arguments _source=source_type are essential: without them both loop-created wrappers would use the final source, Commodity Vega. Keep _get_csv_product_connector_adapters and build_production_refresh_manager. The latter already passes connector_adapters=get_product_connector_adapters(). FX Delta remains attached to its existing two bulk functions. If your factory already builds real site adapters, keep its existing mapping construction instead of _get_csv_product_connector_adapters(), then apply this same for-loop to that mapping. Do not switch your real Risk sources back to CSV.

```python
bulk_replace(
    'cube/services/s05_sources.py',
    '''def get_product_connector_adapters() -> Mapping[str, ProductConnectorAdapter]:
    """Return the active per-product connector adapters."""

    return _get_csv_product_connector_adapters()''',
    '''def get_product_connector_adapters() -> Mapping[str, ProductConnectorAdapter]:
    """Attach bulk market hooks while retaining each existing Risk boundary."""
    adapters = dict(_get_csv_product_connector_adapters())
    for source_type in ("commo/delta", "commo/vega"):
        def opened(open_date, quote_pairs, *, market_status, _source=source_type):
            return get_commo_market_open_bulk(
                _source, open_date, quote_pairs, market_status=market_status
            )

        def current(market_date, quote_pairs, *, market_status, _source=source_type):
            return get_commo_market_status_bulk(
                _source, market_date, quote_pairs, market_status=market_status
            )

        def tenor_scope(open_date, market_date, underlyings, *, market_status, _source=source_type):
            return get_commo_market_tenor_scope(
                _source, open_date, market_date, underlyings, market_status=market_status
            )

        opened.__name__ = f"get_{source_type.replace('/', '_')}_market_open_bulk"
        current.__name__ = f"get_{source_type.replace('/', '_')}_market_status_bulk"
        tenor_scope.__name__ = f"get_{source_type.replace('/', '_')}_market_tenor_scope"
        adapters[source_type] = replace(
            adapters[source_type],
            market_open_bulk=opened,
            market_status_bulk=current,
            market_tenor_scope=tenor_scope,
        )
    return adapters''',
)
```

#### Bulk edit 30 — Export get_commo_market_tenor_scope

File: `cube/services/s05_sources.py`. Add the new public name to the existing __all__ list. Keep every existing exported name.

```python
bulk_replace(
    'cube/services/s05_sources.py',
    '''    "get_cross_gamma_sensitivities",''',
    '''    "get_commo_market_tenor_scope",
    "get_cross_gamma_sensitivities",''',
)
```

#### Bulk edit 31 — Export get_commo_market_open_bulk

File: `cube/services/s05_sources.py`. Add the new public name to the existing __all__ list. Keep every existing exported name.

```python
bulk_replace(
    'cube/services/s05_sources.py',
    '''    "get_cross_gamma_sensitivities",''',
    '''    "get_commo_market_open_bulk",
    "get_cross_gamma_sensitivities",''',
)
```

#### Bulk edit 32 — Export get_commo_market_status_bulk

File: `cube/services/s05_sources.py`. Add the new public name to the existing __all__ list. Keep every existing exported name.

```python
bulk_replace(
    'cube/services/s05_sources.py',
    '''    "get_cross_gamma_sensitivities",''',
    '''    "get_commo_market_status_bulk",
    "get_cross_gamma_sensitivities",''',
)
```

### Connect the real Commodity service without changing the framework

The quote-provider implementation is site-owned and is not present in the available application. The existing Commodity adapter even records that its original real connector body was unavailable. Consequently the only site-specific work below is translating the desk's actual callable and its response columns to this small boundary. Do not invent an endpoint, credentials, tenor order or quote unit.

1. Open `cube/services/s05_sources.py`. Locate `_get_commo_market_bulk`. Keep its signature and the validation of `source_type`, source date, `market_status`, `quote_pairs`, `spec`, `value_column` and `columns`.
2. Locate the comment `CSV example boundary: replace this read/filter block with ONE provider request`. Remove the following block from the `_source_rows(...)` call through the `_require_temp_notice(...)` call. Those statements read placeholder CSV data. Do not remove the date/status checks above them, the Current status attachment below them, or the final `return`.
3. Build a request table using the exact supplied pairs. This code is complete and does not make a network call:

```python
request_rows = pd.DataFrame(
    pairs,
    columns=["Underlying", "Tenor Swap"],
)
```

4. Call your existing desk bulk callable once, using `request_rows` or `pairs` in the representation that callable accepts. The required inputs are `source_type`, `source_date`, the exact pairs, the leg selected by `dataset`, and the manager's `selected_status`. Use `dataset == "market_open"` to select opening quotes and `dataset == "market_status"` for Current quotes. There must not be a loop that calls the provider for each row. If the upstream service accepts a dictionary, convert the exact pairs to `Underlying -> list of its own tenors`; never send independent lists of all Underlyings and all tenors unless the service explicitly supports paired arrays.
5. Assign the provider response to `frame`, a pandas DataFrame. Translate its actual column names to the following canonical output. Keep values in the established quote units. If it returns a single generic price column, rename that column to `value_column`. If it returns both Open and Current, select only the requested leg. If it includes dates, statuses, vendor sources or products, filter them to this exact request before returning the frame. Verify any supplied source status/date agrees with the request before discarding metadata columns; attaching the manager's status later must not disguise an incorrectly routed response.

| Product | Open columns, in order | Current columns, in order |
|---|---|---|
| Commodity Delta | `Underlying`, `Tenor Swap`, `Tenor Swap Order`, `Open` | `Underlying`, `Tenor Swap`, `Tenor Swap Order`, `Current` |
| Commodity Vega | `Underlying`, `Tenor Swap`, `Tenor Swap Order`, `Open` | `Underlying`, `Tenor Swap`, `Tenor Swap Order`, `Current` |

6. Finish the replacement provider-read block with `frame = frame.loc[:, columns].copy()`. Let the existing lines below attach `Market Status` for the Current leg. Do not return Portfolio, Group, Reported Underlying or a reduced tenor label. Those are not quote identities.
7. Return at most one row per `(Underlying, Tenor Swap)` in each product and leg. Do not silently `drop_duplicates` returned quotes. If the service returns several vendors or observations for one identity, use the desk's actual authority rule to select the right observation before producing the canonical frame. An unknown rule is an integration question, not permission to choose the first row.
8. Preserve the provider's authoritative `Tenor Swap Order`. It is display metadata and must be consistent across both legs: one label maps to one order, and one order maps to one label, within each raw Underlying. Do not calculate orders from request position, lexical sorting or parsing tenor text. Request order and display tenor order are different things.
9. For unavailable quotes, return a correctly shaped empty frame or omit the unavailable exact pairs. Do not create zero prices and do not forward-fill from another date. Existing MarketBook logic will expose absent legs and unavailable P&L honestly.
10. Now locate `get_commo_market_tenor_scope`. Keep its signature and all date/status/Underlying validations. Replace only the CSV `parts = [...]` and concatenation/filter block with a read of the real source's dated tenor catalogue. Return the union of actual `(Underlying, Tenor Swap)` identities available for the selected Underlyings on `open_date` and `market_date`. The final `exact_market_pairs(...)` return can stay. This catalogue must include market-only tenors; it must not simply repeat Risk's tenor list.
11. If no separate catalogue API exists, use the desk's existing source-owned contract/expiry metadata, or derive the identity union from the existing complete dated market-source snapshots. Use a source snapshot already fetched for this refresh where your real adapter has one. Do not fetch the complete quote data twice just to emulate an additional metadata service. If the real provider can only accept exact pairs and there is no authoritative source of its available pairs, full market-only coverage cannot be inferred: keep the existing single-Underlying Commodity hooks active until that source is provided. A Risk-only guess would remove data that the old whole-curve call could return.
12. Keep catalogue failure visible. Do not catch a failed catalogue read in the provider wrapper and return only Risk pairs. The manager uses the existing timeout, elapsed budget and per-product circuit: an ordinary catalogue outage marks that Commodity product unavailable while other products continue. A schema/contract error aborts atomically and retains the previous committed snapshot. An exhausted common elapsed budget still stops further network calls across products.

### Connect the real FX Delta bulk service

FX Delta bulk dispatch already exists. Do not add a tenor axis or change its market grain.

1. In `cube/services/s05_sources.py`, keep `get_fx_delta_market_open_bulk(open_date, underlyings, *, market_status)` and `get_fx_delta_market_status_bulk(market_date, underlyings, *, market_status)`.
2. Locate `_get_fx_delta_market_bulk`. Keep its validation of dates, exact `Live`/`OFFICIAL` status and `_bulk_underlying_scope(underlyings)`.
3. Replace its `_source_rows(...)` CSV read and placeholder-notice handling with one call to the desk's FX Delta bulk service for the complete ordered `requested` tuple. Preserve all requested identity, date and status inputs. The Open call receives the T−1 business date; Current receives the resolved Market Date. These dates are independent of an older Risk readiness date.
4. Adapt the response to exactly `Underlying, Open` for Open and `Underlying, Current` for Current. Keep the existing `Market Status` attachment on Current. If retaining the existing request-order filtering/sort code, ensure the provider's canonical `Underlying` column exists before that code runs.
5. A currency pair without a quote should be absent. It must not become a zero rate. Reject ambiguous duplicate currency-pair quotes using the existing product validator.
6. Keep the FX bindings already present in `_get_csv_product_connector_adapters`: `market_open_bulk=get_fx_delta_market_open_bulk` and `market_status_bulk=get_fx_delta_market_status_bulk` only for `source_type == "fx/delta"`.
7. Keep `get_product_connector_adapters()` returning that mapping with the Commodity additions. Keep `build_production_refresh_manager(... connector_adapters=get_product_connector_adapters(), ...)`. Attaching functions to an unused builder will not activate them.
8. If your active source factory is site-specific, attach the same two FX function objects to its existing FX Delta adapter with `replace(existing_fx_adapter, market_open_bulk=get_fx_delta_market_open_bulk, market_status_bulk=get_fx_delta_market_status_bulk)`. Keep the Risk function already held by `existing_fx_adapter`; it may return a Risk/matrix bundle.

### Check syntax and request shaping from the notebook

These checks use small invented identities in memory. They do not read or send live quotes, change source files, write history, or call the real provider. They establish that requests preserve exact pair identity and that the manager chooses the intended callable. They do not establish whether an unavailable external provider is correctly connected.

1. Run the syntax cell. Success is one `Syntax OK` message for each changed file. A syntax failure identifies a path and line to correct before restarting the app.

```python
bulk_check_syntax()
```

2. Note your APP_ROOT path and the printed backup folder, then restart the notebook kernel before the following imports. Rerun only the imports and APP_ROOT/path setup at the top of the helper cell; do not create a replacement backup of already edited files. Python caches imported modules, so a restarted kernel prevents stale class definitions from hiding a missed edit. Run this cell to check exact pairs and preserve an extra market-only tenor:

```python
import pandas as pd
from cube.adapters.s01_common import exact_market_pairs
from cube.services.s06_refresh import RiskRefreshManager

# Two portfolios can share a quote, so two identical Risk identities need one request.
raw_risk = pd.DataFrame({
    "Underlying": ["Oil", "Oil", "Gas"],
    "Tenor Swap": ["Jun-27", "Jun-27", "Sep-27"],
})
supplemental = (("Oil", "Aug-27"),)
universe = (("Oil", "Jun-27"), ("Oil", "Jul-27"), ("Gas", "Sep-27"))
pairs = RiskRefreshManager._requested_market_pairs(
    raw_risk, supplemental, universe, ("Oil", "Gas")
)
assert pairs == (
    ("Oil", "Jun-27"), ("Gas", "Sep-27"),
    ("Oil", "Aug-27"), ("Oil", "Jul-27"),
)
assert ("Gas", "Jun-27") not in pairs
assert ("Oil", "Sep-27") not in pairs
assert ("Oil", "Jul-27") in pairs  # Market-only tenor survives.
try:
    exact_market_pairs((("Oil", "Jun-27"), ("Oil", "Jun-27")))
except ValueError:
    pass
else:
    raise AssertionError("Duplicate request identities were accepted")
print("Exact pairs, supplemental tenor and market-only tenor preserved")
```

3. Run this cell. It replaces only the in-memory call executor with a recorder; it does not construct a real refresh manager or contact a service. It checks that one Open call and one Current call are selected for each of the three products, that both Commodity products receive exact pairs, that FX receives Underlyings, and that dates/statuses are unchanged.

```python
from types import SimpleNamespace
from cube.domain.s02_products import ProductConnectorAdapter, PRODUCT_SPECS_BY_SOURCE_TYPE

recorded = []
def no_network(*args, **kwargs):
    raise AssertionError("A legacy per-Underlying hook was selected")

def quote_hook(source, leg):
    def read(source_date, request, *, market_status):
        recorded.append((source, leg, source_date, request, market_status))
        return pd.DataFrame()
    return read

def record_bulk(spec, underlyings, *, load_bulk, **kwargs):
    return load_bulk()

adapters = {}
for source in ("commo/delta", "commo/vega", "fx/delta"):
    adapters[source] = ProductConnectorAdapter(
        risk=no_network,
        market_open=no_network,
        market_status=no_network,
        market_open_bulk=quote_hook(source, "Open"),
        market_status_bulk=quote_hook(source, "Current"),
        market_tenor_scope=None,
    )
recorder = SimpleNamespace(
    _connector_adapters=adapters,
    _load_bulk_market_frame=record_bulk,
    _market_open_loader=no_network,
    _market_status_loader=no_network,
)
open_date = pd.Timestamp("2026-09-04")
market_date = pd.Timestamp("2026-09-07")
for source in adapters:
    spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source]
    underlying_scope = ("EURUSD", "USDJPY") if source == "fx/delta" else ("Oil", "Gas")
    pair_scope = () if source == "fx/delta" else pairs
    RiskRefreshManager._load_product_market_open(
        recorder, spec, open_date, underlying_scope,
        market_status="OFFICIAL", quote_pairs=pair_scope,
    )
    RiskRefreshManager._load_product_market_status(
        recorder, spec, market_date, underlying_scope,
        market_status="OFFICIAL", quote_pairs=pair_scope,
    )
assert len(recorded) == 6
for source, leg, date, request, status in recorded:
    assert date == (open_date if leg == "Open" else market_date)
    assert status == "OFFICIAL"
    assert request == (("EURUSD", "USDJPY") if source == "fx/delta" else pairs)
print("All six bulk dispatches preserve product, date, status and exact scope")
```

The recorder deliberately does not call the manager constructor or perform market validation. Real Commodity adapters still require a callable catalogue; do not copy the recorder's `market_tenor_scope=None` into the real factory.

4. Run this cell to check the already validated quote-scope guard. Missing quote pairs are accepted, but an extra unrequested quote identity is rejected. This does not bypass the product-level uniqueness checks used by the real refresh.

```python
available = pd.DataFrame({
    "Underlying": ["Oil"], "Tenor Swap": ["Jun-27"],
})
RiskRefreshManager._reject_unrequested_market_pairs(available, pairs, label="example")
extra = pd.DataFrame({
    "Underlying": ["Gas"], "Tenor Swap": ["Jun-27"],
})
try:
    RiskRefreshManager._reject_unrequested_market_pairs(extra, pairs, label="example")
except ValueError:
    pass
else:
    raise AssertionError("An unrequested quote pair was accepted")
print("Unavailable pairs remain absent; unrequested pairs are rejected")
```

### Restart and inspect the running application

1. Restart your app process from the notebook using the normal launch cell. Construction should still avoid source I/O; the existing refresh flow owns source calls.
2. Enable the existing Commodity market option. With Commodity market disabled, the code deliberately bypasses the real Commodity connectors and labels the result `Commodity market disabled`. That disabled mode cannot demonstrate bulk routing. Do not remove its switch or claim its placeholder output is a real quote.
3. Click the existing **Refresh Risk** button. Its `reload-risk-button` callback calls `manager.refresh(force_risk=True, ...)`, so it refreshes Risk and both market legs. Do not use **Recalculate all Risk views** for this check: that action recalculates the promotion views and does not replace source refresh. A metadata-only refresh can legitimately return before consulting the market catalogue. After a provider's tenor catalogue changes without a Risk date change, click **Refresh Risk** again; this change does not introduce continuous catalogue polling.
4. Inspect the refresh progress/log names. For enabled Commodity Delta, Commodity Vega and FX Delta, each refreshed Open and Current leg should select its bulk callable. Commodity has one additional bounded catalogue call per product on refreshes reaching the data-loading stage. Do not expect one quote call per portfolio or tenor.
5. Check one Underlying with two tenors and another Underlying with a different tenor. Compare the returned quote identities with the exact request. Reject a provider response formed from a cartesian product of independent Underlying and tenor lists.
6. Open Quick Market for a Commodity Underlying that has a quoted tenor with no position. That tenor must still appear in the full MarketBook and its chart. The absence of a Risk position must not remove the quote.
7. Check a Commodity New Trades MARKET row whose tenor is absent from aged Risk. Check a Cross Gamma matrix row whose input or output Commodity tenor is absent from aged Risk. Both required quote pairs must be present in the request, using their own raw labels.
8. In a controlled preview input, change only a Commodity tenor while retaining the same Underlying. Click **Refresh Risk**. The affected quote leg must be fetched again; the old pair must not survive merely because the Underlying name is unchanged. The saved requested-pair comparison also detects this change on ordinary refreshes that reach the source-loading stage.
9. Toggle Reduced and Full after the refresh. The underlying market request and raw MarketBook must remain the same; only the Risk presentation changes. This bulk change does not fix a separate hierarchy click-wiring error.
10. Compare a handful of complete quotes and P&L values with the prior single-Underlying connector for the same exact dates/status. Bulk transport must preserve those values. For a missing quote, the app must still show unavailable data. Check the provider's actual quote units before interpreting any difference.
11. If startup says Commodity bulk hooks are unsupported, the old manager constructor is still loaded or its whitelist edit was missed. If a call says it received unexpected `market_status`, fix the provider wrapper to accept that exact keyword; do not silently discard it. If the hook says it is missing exact tenor pairs, inspect both manager call-site edits and the scope block. If neither Commodity bulk hook is reached, check the active factory and Commodity option before modifying the callbacks.
12. If quote-rank validation fails, print only `Underlying`, `Tenor Swap`, `Tenor Swap Order` for the problematic product/leg. Correct the provider's rank authority. Do not remove a rank or duplicate-key validator to make the refresh proceed.

### Roll back only this feature if necessary

1. Stop your own app process.
2. Restore the six named source files from the backup created immediately before this chapter. Keep all earlier Data and hierarchy fixes and all financial records.
3. Run this complete rollback cell, replacing both path values with the folders you recorded. Do not point BULK_BACKUP at a new backup created after the edits. The cell first checks that all six saved files exist and contain valid Python, then restores only those six paths and checks their syntax again.

```python
from pathlib import Path
import ast
import shutil

APP_ROOT = Path("/replace/with/your/application/folder").resolve()
BULK_BACKUP = Path("/replace/with/the/original/rebirth_bulk_backup_folder").resolve()
assert (APP_ROOT / "app.py").is_file(), APP_ROOT
assert BULK_BACKUP.is_dir(), BULK_BACKUP
assert BULK_BACKUP != APP_ROOT
BULK_FILES = [
    "cube/domain/s02_products.py",
    "cube/adapters/s01_common.py",
    "cube/domain/s04_crossgamma.py",
    "cube/domain/s05_newtrades.py",
    "cube/services/s06_refresh.py",
    "cube/services/s05_sources.py",
]
for relative in BULK_FILES:
    saved = (BULK_BACKUP / relative).resolve()
    target = (APP_ROOT / relative).resolve()
    assert saved.is_relative_to(BULK_BACKUP) and saved.is_file(), saved
    assert target.is_relative_to(APP_ROOT) and target.is_file(), target
    ast.parse(saved.read_text(encoding="utf-8"), filename=str(saved))
for relative in BULK_FILES:
    target = APP_ROOT / relative
    shutil.copy2(BULK_BACKUP / relative, target)
    ast.parse(target.read_text(encoding="utf-8"), filename=str(target))
    print("Restored; syntax OK:", relative)
```

4. Restart the app. Its previous single-Underlying Commodity routing and existing FX bulk routing should return. A rollback restores the connector implementation; it does not reverse any source data or archived observations.

The final implementation retains the existing product adapters, validator/merge pipeline, atomic snapshot commits, dates, status authority, formulae, Risk/matrix bundle and Full/Reduced UI state. It adds one optional callable to ProductConnectorAdapter and one immutable requested-pair tuple in each relevant market leg's metadata for cache reuse. Catalogue frames and other request-building work remain local to one refresh; there is no new global table cache.
