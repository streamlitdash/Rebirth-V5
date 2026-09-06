# all — JupyterHub implementation manual

This manual is for editing an existing Rebirth application folder from JupyterHub. Follow the jobs in the order shown. Each job identifies the files and functions to change, the behaviour to preserve, the edits to make, and the checks required before continuing. Reading this manual does not modify the running application.

The completed Data workspace must accept both Quick Risk and Quick Market navigation. It must offer **Risk / Market / Both** in one place. Both means two linked views with separate units and independently validated selections; it does not mean adding Risk to a Market price or multiplying a quote by the number of positions. An ambiguous companion selection must be chosen explicitly.

## Implementation order

Work down this list. Jobs within a group are sequential. Optional tools are complete file listings near the end; create them before running a feature job that explicitly calls one.

1. [Job A00 — Prepare the project and notebook](#job-a00)
2. [Job A01 — Repair the Statics table picker](#job-a01)
3. [Job A02 — Reuse prepared Risk data and stop retaining Explorer table copies](#job-a02)
4. [Job B01 — Check history size before allocating the grid](#job-b01)
5. [Job B02 — Apply the selected Risk scope before the SQL row limit](#job-b02)
6. [Job B03 — Put a visible construction budget on the Risk hierarchy](#job-b03)
7. [Job B04 — Send Stock position detail one requested page at a time](#job-b04)
8. [Job B05 — Bound the current P&L Validate tree before changing its navigation](#job-b05)
9. [Job B06 — Bound the P&L history caches without rejecting valid results](#job-b06)
10. [Job B07 — Stop Statics Read work while Write is displayed](#job-b07)
11. [Job C01 — Use replacement P&L values consistently](#job-c01)
12. [Job C02 — Prevent lost or concurrent adjustment saves](#job-c02)
13. [Job C03 — Keep Stock history on the exact clicked population](#job-c03)
14. [Job C04 — Make Stock column coverage and source dates explicit](#job-c04)
15. [Job C05 — Match demo identities across current and historical reads](#job-c05)
16. [Job C06 — Show complete and partial P&L reconciliation honestly](#job-c06)
17. [Job C07 — Let every P&L reconciliation child remain reachable](#job-c07)
18. [Job C08 — Keep P&L summary dates, periods and historical filters aligned](#job-c08)
19. [Job C09 — Make empty market legs and reduction retries safe](#job-c09)
20. [Job C10 — Remove obsolete layers after their replacements pass](#job-c10)
21. [Job D00 — Correct Quick Risk totals before using them as a comparison](#job-d00)
22. [Job D01 — Define the one Data workspace and make its backup](#job-d01)
23. [Job D02 — Add exact selection and pairing helpers](#job-d02)
24. [Job D03 — Give paired queries one calendar window and one budget](#job-d03)
25. [Job D04 — Replace the Data layout without orphaned component IDs](#job-d04)
26. [Job D05 — Implement the draft-to-loaded state transition](#job-d05)
27. [Job D06 — Replace callback registrations and keep one owner per output](#job-d06)
28. [Job D07 — Give both panels one browser-local player and matching views](#job-d07)
29. [Job D08 — Reuse one segmented-control style](#job-d08)
30. [Job D09 — Check syntax and exact selection behavior in the notebook](#job-d09)
31. [Job D10 — Restart in JupyterHub and inspect the complete interaction](#job-d10)
32. [Job P01 — Group Risk siblings once per parent](#job-p01)
33. [Job P02 — Skip calculations for intentionally blank Credit cells](#job-p02)
34. [Job P03 — Use one Risk surface pivot for chart and matrix](#job-p03)
35. [Job P04 — Select a Risk detail scope once](#job-p04)
36. [Job P05 — Filter Search using only the required position columns](#job-p05)
37. [Job P06 — Batch table resizing and rectangular selection in the browser](#job-p06)
38. [Job P07 — Group Stock children once per parent](#job-p07)
39. [Job P08 — Batch Stock history identities and read date bounds directly](#job-p08)
40. [Job P09 — Reuse archive discovery metadata within one history action](#job-p09)
41. [Job P10 — Index P&L summary children once](#job-p10)
42. [Job P11 — Avoid an unused full snapshot copy after Portfolio refresh](#job-p11)
43. [Job P12 — Validate supplemental inputs once within one refresh](#job-p12)
44. [Job P13 — Replace repeated row checks with grouped product and tenor checks](#job-p13)
45. [Job P14 — Use vectorised finite-number validation](#job-p14)
46. [Job P15 — Select the MarketBook once per tenor-reduction batch](#job-p15)
47. [Job P16 — Bound warning deduplication and unfinished log lines](#job-p16)
48. [Job P17 — Remove only proven duplicate temporary-source copies](#job-p17)
49. [Job F01 — Add Quantity and dQuantity to Stock without changing position identity](#job-f01)
50. [Job F02 — Add an optional ISIN column through a dated metadata lookup](#job-f02)
51. [Job F03 — Show Quantity history and discover positions that exist only in the archive](#job-f03)
52. [Job F04 — Create isolated demonstration history and verify all three history readers](#job-f04)
53. [Job F05 — Capture coherent daily Risk, Market, actual P&L and Stock](#job-f05)
54. [Job F06 — Keep adjustment versions and active values in one transaction](#job-f06)
55. [Job F07 — Record exactly what P&L was sent and whether delivery was confirmed](#job-f07)
56. [Job F08 — Keep durable diagnostic logs and optional intraday snapshots](#job-f08)
57. [Job F09 — Fix market-move rendering and make tenor charts easier to read](#job-f09)
58. [Job F10 — Browse Portfolio detail from main Risk without expanding the whole book population](#job-f10)
59. [Job T01 — Create the optional demonstration tools](#job-t01)
60. [Job Z01 — Finish cleanup and check the saved source](#job-z01)
61. [Job Z02 — Start one preview process through JupyterHub](#job-z02)
62. [Job Z03 — Check the final interaction and record what works](#job-z03)

<a id="job-a00"></a>
## Job A00 — Prepare the project and notebook

### 1. Locate the application folder

Open JupyterLab's file browser. Locate the folder containing `app.py`, `cube`, `assets` and `requirements.txt`. Create an implementation notebook beside that folder. Do not create it inside `data`, an archive date folder or an adjustment folder.

Run this cell. Replace the example folder name with the folder visible in your own file browser. If the notebook is already inside the application folder, use `Path.cwd()` instead.

```python
from pathlib import Path
import ast
import datetime as dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

APP_ROOT = (Path.cwd() / "Rebirth").resolve()  # Set this to your application folder.
assert (APP_ROOT / "app.py").is_file(), APP_ROOT
assert (APP_ROOT / "cube").is_dir(), APP_ROOT
PYTHON = sys.executable
BACKUP_ROOT = APP_ROOT.parent / "rebirth_implementation_backups"
BACKUP_ROOT.mkdir(exist_ok=True)
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))
print("Application:", APP_ROOT)
print("Notebook Python:", PYTHON)
print("Backups:", BACKUP_ROOT)
```

Do not continue if these assertions fail. Correct `APP_ROOT` from the file browser. Do not create an empty `app.py` to satisfy the check.

### 2. Add the editing and verification helpers

Run this complete cell once. Keep it near the top of the notebook. These helpers operate only on explicitly named files under the application folder. The implementation jobs name application source files; saved financial records remain separate.

```python
JOB_BACKUPS = {}

def project_path(relative_path):
    candidate = (APP_ROOT / relative_path).resolve()
    if candidate != APP_ROOT and APP_ROOT not in candidate.parents:
        raise ValueError("Path leaves the application folder")
    return candidate

def backup_job(job_id, relative_paths):
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    destination = BACKUP_ROOT / f"{job_id}-{stamp}"
    destination.mkdir()
    manifest = []
    for relative in dict.fromkeys(str(p) for p in relative_paths):
        source = project_path(relative)
        relative = str(source.relative_to(APP_ROOT))
        if source.exists() and not source.is_file():
            raise ValueError(f"Expected a file: {relative}")
        row = {"path": relative, "existed": source.is_file()}
        if source.is_file():
            payload = source.read_bytes()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            row["sha256"] = hashlib.sha256(payload).hexdigest()
        manifest.append(row)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    JOB_BACKUPS[job_id] = destination
    print("Backup:", destination)
    return destination

def show_symbol(relative_path, name):
    source = project_path(relative_path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    candidates = [node for node in ast.walk(tree)
                  if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                  and node.name == name]
    if not candidates:
        raise LookupError(f"No symbol {name!r} in {relative_path}")
    lines = source.splitlines()
    for node in candidates:
        decorators = getattr(node, "decorator_list", [])
        start = min([node.lineno] + [item.lineno for item in decorators])
        print(f"\n{relative_path}: {name}, lines {start}-{node.end_lineno}")
        print("\n".join(f"{i+1}: {lines[i]}" for i in range(start-1, node.end_lineno)))

def search_project(text, folders=("cube", "assets", "tools")):
    matches = []
    for folder in folders:
        for path in sorted(project_path(folder).rglob("*")):
            if path.suffix not in {".py", ".js", ".css"} or not path.is_file():
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if text in line:
                    matches.append((str(path.relative_to(APP_ROOT)), number, line.strip()))
    for match in matches[:100]:
        print(*match, sep=": ")
    print("Matches:", len(matches))
    return matches

def write_source(relative_path, content):
    target = project_path(relative_path)
    if target.suffix == ".py":
        ast.parse(content, filename=str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=target.name + ".", dir=target.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()

def replace_exact(relative_path, old, new):
    if not old:
        raise ValueError("Use write_source for an explicitly new file")
    target = project_path(relative_path)
    source = target.read_text(encoding="utf-8")
    count = source.count(old)
    if count == 0 and new and source.count(new) == 1:
        print("Already present:", relative_path)
        return
    if count != 1:
        raise ValueError(f"Expected one exact old block in {relative_path}; found {count}")
    write_source(relative_path, source.replace(old, new, 1))
    print("Updated:", relative_path)

def run_module(module, *arguments):
    command = [PYTHON, "-m", module, *map(str, arguments)]
    result = subprocess.run(command, cwd=APP_ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout)
    if result.returncode:
        raise RuntimeError(f"Command failed with status {result.returncode}: {module}")
    return result

def check_syntax(relative_paths):
    checked = 0
    for relative in dict.fromkeys(relative_paths):
        target = project_path(relative)
        if target.suffix != ".py":
            continue
        source = target.read_text(encoding="utf-8")
        ast.parse(source, filename=str(target))
        print("Syntax OK:", relative)
        checked += 1
    print("Python files checked:", checked)

def check_javascript(relative_paths):
    node = shutil.which("node")
    if node is None:
        print("JavaScript command checker unavailable; use the browser checks below.")
        return
    for relative in relative_paths:
        result = subprocess.run([node, "--check", str(project_path(relative))],
                                text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        if result.returncode:
            print(result.stdout)
            raise RuntimeError(f"JavaScript syntax error: {relative}")
        print("JavaScript syntax OK:", relative)

def restore_job(job_id):
    destination = JOB_BACKUPS[job_id]
    rows = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    for row in rows:
        target = project_path(row["path"])
        if row["existed"]:
            payload = (destination / row["path"]).read_bytes()
            if hashlib.sha256(payload).hexdigest() != row["sha256"]:
                raise ValueError("Backup checksum mismatch")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        elif target.is_file():
            target.unlink()
    print("Restored source files for", job_id)
```

If a replacement reports zero or multiple matches, stop that edit and use `show_symbol` or `search_project`. Read the whole existing function and reconcile its extra changes. Do not weaken the helper to replace every occurrence. A matching new block means that particular edit already exists; verify the rest of the job before marking it complete.

### 3. Check the Python environment

Run the following cell. It reports package versions without starting the app or contacting financial connectors.

```python
from importlib.metadata import version, PackageNotFoundError
for package in ["pandas", "numpy", "dash", "plotly", "duckdb"]:
    try:
        print(package, version(package))
    except PackageNotFoundError:
        print(package, "MISSING")
```

If required packages are missing, select the project’s designated Jupyter kernel. If that kernel is intended to be managed by you, install the versions in `requirements.txt` with this cell, then restart the kernel and rerun the setup cells. Do not substitute unpinned latest versions or install into a different interpreter.

```python
subprocess.run(
    [PYTHON, "-m", "pip", "install", "-r", str(APP_ROOT / "requirements.txt")],
    cwd=APP_ROOT, check=True,
)
```

### 4. Check the starting Python syntax

Run this cell. It reads Python source and checks whether Python can parse it. It does not start the app, call financial connectors or require extra project folders.

```python
SOURCE_FILES = ["app.py"] + [
    str(path.relative_to(APP_ROOT))
    for folder in ("cube", "tools")
    for path in sorted((APP_ROOT / folder).rglob("*.py"))
    if path.is_file()
]
check_syntax(SOURCE_FILES)
```

Success prints `Syntax OK` and a file count. A `SyntaxError` identifies the file and line to correct. Save this output before editing so an existing error is distinguishable from a new one. **Syntax success proves only that the file can be parsed.** It does not prove that imports, callbacks, calculations or browser controls work; the small checks and visible actions under each job cover those separately.

### 5. Use the same method for every job

1. Read that job’s prerequisites and file list.
2. Run its `backup_job` cell before editing. Include each newly created file in the list so rollback knows it was absent.
3. Open the files in JupyterLab’s text editor, or use the supplied exact-replacement cells. Locate functions by name, not an old line number.
   When a step says **run this cell**, execute it in the notebook. When it says **add/replace in a file**, paste the code into that named source file at the stated location. A function signature or a few lines from inside a function is a source fragment, not a complete notebook program. Preserve its surrounding function and indentation as instructed.
4. Make the numbered edits in order. **KEEP** means preserve that behaviour in the final function; **REPLACE** means remove only the named old block and insert the supplied new block; **ADD** means insert once at the named location; **REMOVE** means delete only the named obsolete statement, output, callback or control.
5. Check every return branch when callback outputs change. There must be one intended owner for each output. Remove decorators together with obsolete callback functions.
6. Save all edited files. Run `check_syntax` on the named Python files. Run the small self-contained Python cells provided by the job and follow its browser actions when it changes the interface.
7. Record PASS with the cell output and visible result in the notebook. An `assert` is an ordinary Python check: silence means that assertion passed; `AssertionError` means its expected result was not obtained. Do not label a helper or a design sketch as complete before its checks pass.
8. If the job fails and you need to undo it, stop the preview app and call `restore_job` for that job only. Rerun its earlier checks. Once later jobs depend on it, restore dependent jobs in reverse order. This source rollback does not undo stored financial records or schema migrations.

### 6. Keep these data rules throughout

1. Keep the full selected position population when calculating Risk and P&L totals. Paging changes displayed rows, not the financial scope.
2. Keep Market quote keys independent of Portfolio count. Validate their uniqueness; never choose an arbitrary duplicate to make a join pass.
3. Keep raw and reported underlying identities distinct. Ask for a precise companion selection when their mapping is ambiguous.
4. Keep missing observations unavailable. Do not fill them with zero or carry prices across absent dates to make linked charts appear complete.
5. Keep connector-owned tenor order. Do not infer tenor order from label strings.
6. Keep committed snapshots immutable and retain the last good snapshot after a failed refresh.
7. Keep daily archive files and completion hashes unchanged after publication. Real source configuration and dated observations are required for real history.
8. A retained-cache budget only changes reuse. An oversized valid scope can still calculate without being retained. Display and history-request budgets are separate limits and must have visible explanations and navigation to remaining detail.

<a id="job-a01"></a>
## Job A01 — Repair the Statics table picker

### 1. Back up the exact files

```python
backup_job('A01', ['cube/pages/static_data/s03_callbacks.py'])
```

### 2. Apply the replacement cells in order

Each cell contains the complete old block and its complete replacement. Run the cells top to bottom. An already-present block is kept. If a cell reports a mismatch, inspect that function and retain unrelated edits; do not force a broad replacement. Keep imports and callback decorators exactly as shown.

#### cube/pages/static_data/s03_callbacks.py — replacement 1

```python
old = (
    '            return html.Div("No file selected.", className="static-data-empty")\n'
    '        return build_static_data_table(selected_file, store=static_store)\n'
    '\n'
    '    @app.callback(\n'
    '        Output("static-data-write-table", "columns"),\n'
    '        Output("static-data-write-table", "data"),\n'
)
new = (
    '            return html.Div("No file selected.", className="static-data-empty")\n'
    '        return build_static_data_table(selected_file, store=static_store)\n'
    '\n'
    '    @app.callback(\n'
    '        Output("static-data-write-table", "filter_query"),\n'
    '        Output("static-data-write-table", "sort_by"),\n'
    '        Output("static-data-write-table", "page_current"),\n'
    '        Output("static-data-write-table", "hidden_columns"),\n'
    '        Output("static-data-write-table", "active_cell"),\n'
    '        Output("static-data-write-table", "selected_cells"),\n'
    '        Input("static-data-write-selector", "value"),\n'
    '    )\n'
    '    def reset_static_table_view(_selected_file):\n'
    '        # DataTable retains view state when its data and schema are replaced.\n'
    '        # A filter on a column from the previous file can hide every new row.\n'
    '        return "", [], 0, [], None, []\n'
    '\n'
    '    @app.callback(\n'
    '        Output("static-data-write-table", "columns"),\n'
    '        Output("static-data-write-table", "data"),\n'
)
replace_exact('cube/pages/static_data/s03_callbacks.py', old, new)
```

### 3. Verify the change

```python
check_syntax(['cube/pages/static_data/s03_callbacks.py'])
```

Expected: `Syntax OK` for every listed Python file. This checks whether Python can read the edited source; complete the browser steps below to check behaviour.

1. Start the preview app using Job Z02. Open Statics → Write.
2. Apply a filter and sort, move to a later page, and hide one column. Change the selected table.
3. Confirm the new table starts on page zero with cleared filter/sort/hidden-column settings and displays its actual columns.
4. Using an isolated demonstration mapping file, edit a value, add a row, validate and save. Confirm the existing save validation still applies.
5. Keep the Read/Write separation and all existing source/save functions. This job resets view state; it does not replace stored values.

### 4. Roll back if verification fails

Stop the preview process using Job Z02. Run `restore_job('A01')` and repeat the focused checks. Restore later dependent jobs first if any have already been applied.

<a id="job-a02"></a>
## Job A02 — Reuse prepared Risk data and stop retaining Explorer table copies

### 1. Back up the exact files

```python
backup_job('A02', ['cube/pages/risk/s02_state.py', 'cube/pages/risk/s06_explorertables.py', 'cube/pages/risk/s07_explorer.py', 'cube/ui/s02_aggregation.py'])
```

### 2. Apply the replacement cells in order

Each cell contains the complete old block and its complete replacement. Run the cells top to bottom. An already-present block is kept. If a cell reports a mismatch, inspect that function and retain unrelated edits; do not force a broad replacement. Keep imports and callback decorators exactly as shown.

#### cube/pages/risk/s02_state.py — replacement 1

```python
old = (
    '    ReducedTenorReducer,\n'
    ')\n'
    'from cube.ui.s02_aggregation import (\n'
    '    apply_filters,\n'
    '    filter_ir_family,\n'
    '    frame_for_context,\n'
    '    parse_row_key,\n'
    '    prepare_risk_data,\n'
    ')\n'
    'from cube.app.s02_contracts import (\n'
    '    ControlSnapshotProtocol,\n'
    '    RefreshManagerProtocol,\n'
)
new = (
    '    ReducedTenorReducer,\n'
    ')\n'
    'from cube.ui.s02_aggregation import (\n'
    '    HierarchyAggregationIndex,\n'
    '    apply_credit_measure,\n'
    '    apply_filters,\n'
    '    filter_ir_family,\n'
    '    frame_for_context,\n'
    '    parse_row_key,\n'
    '    prepare_risk_data,\n'
    ')\n'
    'from cube.ui.s01_constants import CREDIT_MEASURES\n'
    'from cube.app.s02_contracts import (\n'
    '    ControlSnapshotProtocol,\n'
    '    RefreshManagerProtocol,\n'
)
replace_exact('cube/pages/risk/s02_state.py', old, new)
```

#### cube/pages/risk/s02_state.py — replacement 2

```python
old = (
    '_UNSET = object()\n'
    '_FILTER_CACHE_MAX_ENTRIES = 32\n'
    '_FILTER_CACHE_MAX_BYTES = 512 * 1024 * 1024\n'
    '\n'
    '_REDUCER_CANONICAL_COLUMNS = (\n'
    '    SOURCE_TYPE,\n'
)
new = (
    '_UNSET = object()\n'
    '_FILTER_CACHE_MAX_ENTRIES = 32\n'
    '_FILTER_CACHE_MAX_BYTES = 512 * 1024 * 1024\n'
    '_HIERARCHY_CACHE_MAX_ENTRIES = 4\n'
    '_HIERARCHY_CACHE_MAX_BYTES = 256 * 1024 * 1024\n'
    '\n'
    '_REDUCER_CANONICAL_COLUMNS = (\n'
    '    SOURCE_TYPE,\n'
)
replace_exact('cube/pages/risk/s02_state.py', old, new)
```

#### cube/pages/risk/s02_state.py — replacement 3

```python
old = (
    '            OrderedDict()\n'
    '        )\n'
    '        self._filtered_bytes = 0\n'
    '        self._rendered: OrderedDict[str, Any] = OrderedDict()\n'
    '        self._promotion_generations: OrderedDict[str, PromotionGeneration] = (\n'
    '            OrderedDict()\n'
)
new = (
    '            OrderedDict()\n'
    '        )\n'
    '        self._filtered_bytes = 0\n'
    '        self._cache_epoch = 0\n'
    '        self._hierarchies: OrderedDict[\n'
    '            tuple[int, str | None], tuple[pd.DataFrame, HierarchyAggregationIndex, int]\n'
    '        ] = OrderedDict()\n'
    '        self._hierarchy_bytes = 0\n'
    '        self._rendered: OrderedDict[str, Any] = OrderedDict()\n'
    '        self._promotion_generations: OrderedDict[str, PromotionGeneration] = (\n'
    '            OrderedDict()\n'
)
replace_exact('cube/pages/risk/s02_state.py', old, new)
```

#### cube/pages/risk/s02_state.py — replacement 4

```python
old = (
    '                self._revision = int(revision)\n'
    '                self._filtered.clear()\n'
    '                self._filtered_bytes = 0\n'
    '                self._rendered.clear()\n'
    '                self._promotion_generations.clear()\n'
    '                self._reduced_frames.clear()\n'
)
new = (
    '                self._revision = int(revision)\n'
    '                self._filtered.clear()\n'
    '                self._filtered_bytes = 0\n'
    '                self._cache_epoch += 1\n'
    '                self._hierarchies.clear()\n'
    '                self._hierarchy_bytes = 0\n'
    '                self._rendered.clear()\n'
    '                self._promotion_generations.clear()\n'
    '                self._reduced_frames.clear()\n'
)
replace_exact('cube/pages/risk/s02_state.py', old, new)
```

#### cube/pages/risk/s02_state.py — replacement 5

```python
old = (
    '            with self._lock:\n'
    '                self._filtered.clear()\n'
    '                self._filtered_bytes = 0\n'
    '                self._rendered.clear()\n'
    '                self._promotion_generations.clear()\n'
    '                self._reduced_frames.clear()\n'
)
new = (
    '            with self._lock:\n'
    '                self._filtered.clear()\n'
    '                self._filtered_bytes = 0\n'
    '                self._cache_epoch += 1\n'
    '                self._hierarchies.clear()\n'
    '                self._hierarchy_bytes = 0\n'
    '                self._rendered.clear()\n'
    '                self._promotion_generations.clear()\n'
    '                self._reduced_frames.clear()\n'
)
replace_exact('cube/pages/risk/s02_state.py', old, new)
```

#### cube/pages/risk/s02_state.py — replacement 6

```python
old = (
    '        while True:\n'
    '            frame = self.current(manager)\n'
    '            with self._lock:\n'
    '                revision = self._revision\n'
    '            key = (\n'
    '                revision,\n'
    '                active_risk_type,\n'
)
new = (
    '        while True:\n'
    '            frame = self.current(manager)\n'
    '            with self._lock:\n'
    '                if frame is not self._frame:\n'
    '                    continue\n'
    '                revision = self._revision\n'
    '                epoch = self._cache_epoch\n'
    '            key = (\n'
    '                revision,\n'
    '                active_risk_type,\n'
)
replace_exact('cube/pages/risk/s02_state.py', old, new)
```

#### cube/pages/risk/s02_state.py — replacement 7

```python
old = (
    '                with self._lock:\n'
    '                    if self._revision != revision:\n'
    '                        continue\n'
    '                    cached = self._filtered.get(key)\n'
    '                    if cached is not None:\n'
    '                        self._filtered.move_to_end(key)\n'
)
new = (
    '                with self._lock:\n'
    '                    if self._revision != revision:\n'
    '                        continue\n'
    '                    if self._cache_epoch != epoch:\n'
    '                        return filtered\n'
    '                    cached = self._filtered.get(key)\n'
    '                    if cached is not None:\n'
    '                        self._filtered.move_to_end(key)\n'
)
replace_exact('cube/pages/risk/s02_state.py', old, new)
```

#### cube/pages/risk/s02_state.py — replacement 8

```python
old = (
    '                        self._filtered_bytes -= old_size\n'
    '                    return filtered\n'
    '\n'
    '    def rendered(self, key: str, build: Callable[[], Any]) -> Any:\n'
    '        """Return one exact immutable table tree from a bounded thread-safe LRU."""\n'
    '        with self._lock:\n'
    '            cached = self._rendered.get(key, _UNSET)\n'
    '            if cached is not _UNSET:\n'
    '                self._rendered.move_to_end(key)\n'
)
new = (
    '                        self._filtered_bytes -= old_size\n'
    '                    return filtered\n'
    '\n'
    '    def hierarchy_index(\n'
    '        self, frame: pd.DataFrame, *, credit_measure: str | None = None\n'
    '    ) -> HierarchyAggregationIndex:\n'
    '        """Reuse one read-only index across display states of an owned frame.\n'
    '\n'
    '        Filter/reduction/promotion scope is represented by the exact cached\n'
    "        frame. Credit's measure transform is the only additional numeric key.\n"
    '        Strong source references prevent object-id reuse while entries live.\n'
    '        """\n'
    '        measure = (\n'
    '            (\n'
    '                credit_measure\n'
    '                if credit_measure in CREDIT_MEASURES\n'
    '                else CREDIT_MEASURES[0]\n'
    '            )\n'
    '            if credit_measure is not None\n'
    '            else None\n'
    '        )\n'
    '        key = (id(frame), measure)\n'
    '        with self._lock:\n'
    '            epoch = self._cache_epoch\n'
    '            cached = self._hierarchies.get(key)\n'
    '            if cached is not None:\n'
    '                self._hierarchies.move_to_end(key)\n'
    '                return cached[1]\n'
    '        with self._render_compute_lock:\n'
    '            with self._lock:\n'
    '                cached = self._hierarchies.get(key)\n'
    '                if cached is not None:\n'
    '                    self._hierarchies.move_to_end(key)\n'
    '                    return cached[1]\n'
    '            selected = apply_credit_measure(frame, measure) if measure else frame\n'
    '            index = HierarchyAggregationIndex(selected)\n'
    '            size = index.memory_bytes\n'
    '            if selected is not frame:\n'
    '                size += int(frame.memory_usage(index=True, deep=True).sum())\n'
    '            with self._lock:\n'
    '                owned = frame is self._frame or any(\n'
    '                    frame is entry[0] for entry in self._filtered.values()\n'
    '                )\n'
    '                if (\n'
    '                    self._cache_epoch != epoch\n'
    '                    or not owned\n'
    '                    or size > _HIERARCHY_CACHE_MAX_BYTES\n'
    '                ):\n'
    '                    return index\n'
    '                self._hierarchies[key] = (frame, index, size)\n'
    '                self._hierarchy_bytes += size\n'
    '                while (\n'
    '                    len(self._hierarchies) > _HIERARCHY_CACHE_MAX_ENTRIES\n'
    '                    or self._hierarchy_bytes > _HIERARCHY_CACHE_MAX_BYTES\n'
    '                ):\n'
    '                    _old_key, (_source, _index, old_size) = self._hierarchies.popitem(\n'
    '                        last=False\n'
    '                    )\n'
    '                    self._hierarchy_bytes -= old_size\n'
    '                return index\n'
    '\n'
    '    def render_explorer(self, build: Callable[[], Any]) -> Any:\n'
    '        """Serialize visible-table builds without retaining component trees."""\n'
    '        with self._render_compute_lock:\n'
    '            return build()\n'
    '\n'
    '    def rendered(self, key: str, build: Callable[[], Any]) -> Any:\n'
    '        """Return one exact immutable table tree from a bounded thread-safe LRU."""\n'
    '        with self._lock:\n'
    '            epoch = self._cache_epoch\n'
    '            cached = self._rendered.get(key, _UNSET)\n'
    '            if cached is not _UNSET:\n'
    '                self._rendered.move_to_end(key)\n'
)
replace_exact('cube/pages/risk/s02_state.py', old, new)
```

#### cube/pages/risk/s02_state.py — replacement 9

```python
old = (
    '                    return existing\n'
    '            component = build()\n'
    '            with self._lock:\n'
    '                self._rendered[key] = component\n'
    '                while len(self._rendered) > 24:\n'
    '                    self._rendered.popitem(last=False)\n'
)
new = (
    '                    return existing\n'
    '            component = build()\n'
    '            with self._lock:\n'
    '                if self._cache_epoch != epoch:\n'
    '                    return component\n'
    '                self._rendered[key] = component\n'
    '                while len(self._rendered) > 24:\n'
    '                    self._rendered.popitem(last=False)\n'
)
replace_exact('cube/pages/risk/s02_state.py', old, new)
```

#### cube/pages/risk/s06_explorertables.py — replacement 1

```python
old = (
    '    region_enabled: bool = True,\n'
    '    underlying_identity_mode: str = "reported",\n'
    '    underlying_sort_metric: str | None = None,\n'
    ') -> html.Div:\n'
    '    if frame.empty:\n'
    '        return html.Div(\n'
    '            [\n'
)
new = (
    '    region_enabled: bool = True,\n'
    '    underlying_identity_mode: str = "reported",\n'
    '    underlying_sort_metric: str | None = None,\n'
    '    aggregation_index: HierarchyAggregationIndex | None = None,\n'
    ') -> html.Div:\n'
    '    # A supplied index owns both row membership and numeric/quote values.\n'
    '    # Never mix its row positions with a separately transformed frame.\n'
    '    if aggregation_index is not None:\n'
    '        frame = aggregation_index.frame\n'
    '    if frame.empty:\n'
    '        return html.Div(\n'
    '            [\n'
)
replace_exact('cube/pages/risk/s06_explorertables.py', old, new)
```

#### cube/pages/risk/s06_explorertables.py — replacement 2

```python
old = (
    '            role="status",\n'
    '        )\n'
    '    columns = build_columns(expanded_metrics)\n'
    '    aggregation_index = HierarchyAggregationIndex(frame)\n'
    '    frame = aggregation_index.frame\n'
    '    total_metrics = aggregation_index.aggregate(frame, include_market=False)\n'
    '    total_cells = [\n'
)
new = (
    '            role="status",\n'
    '        )\n'
    '    columns = build_columns(expanded_metrics)\n'
    '    if aggregation_index is None:\n'
    '        aggregation_index = HierarchyAggregationIndex(frame)\n'
    '    frame = aggregation_index.frame\n'
    '    total_metrics = aggregation_index.aggregate(frame, include_market=False)\n'
    '    total_cells = [\n'
)
replace_exact('cube/pages/risk/s06_explorertables.py', old, new)
```

#### cube/pages/risk/s07_explorer.py — replacement 1

```python
old = (
    '\n'
    'from __future__ import annotations\n'
    '\n'
    'import json\n'
    'import logging\n'
    'from typing import Any, Mapping, Sequence\n'
    '\n'
)
new = (
    '\n'
    'from __future__ import annotations\n'
    '\n'
    'import logging\n'
    'from typing import Any, Mapping, Sequence\n'
    '\n'
)
replace_exact('cube/pages/risk/s07_explorer.py', old, new)
```

#### cube/pages/risk/s07_explorer.py — replacement 2

```python
old = (
    '                None,\n'
    '                generation_state=generation_state,\n'
    '            )\n'
    '            render_key = json.dumps(\n'
    '                [view_token, sorted(open_rows or [])],\n'
    '                separators=(",", ":"),\n'
    '            )\n'
    '\n'
    '            def build_alt_component():\n'
    '                filtered = filtered_frame()\n'
)
new = (
    '                None,\n'
    '                generation_state=generation_state,\n'
    '            )\n'
    '\n'
    '            def build_alt_component():\n'
    '                filtered = filtered_frame()\n'
)
replace_exact('cube/pages/risk/s07_explorer.py', old, new)
```

#### cube/pages/risk/s07_explorer.py — replacement 3

```python
old = (
    '                    underlying_sort_metric=selected_sort_metric,\n'
    '                )\n'
    '\n'
    '            return no_update, cache.rendered(render_key, build_alt_component)\n'
    '\n'
    '        view_token = risk_action_view_token(\n'
    '            risk_context,\n'
)
new = (
    '                    underlying_sort_metric=selected_sort_metric,\n'
    '                )\n'
    '\n'
    '            return no_update, cache.render_explorer(build_alt_component)\n'
    '\n'
    '        view_token = risk_action_view_token(\n'
    '            risk_context,\n'
)
replace_exact('cube/pages/risk/s07_explorer.py', old, new)
```

#### cube/pages/risk/s07_explorer.py — replacement 4

```python
old = (
    '            credit_view,\n'
    '            generation_state=generation_state,\n'
    '        )\n'
    '        render_key = json.dumps(\n'
    '            [view_token, sorted(open_rows or []), promotion_enabled, region_enabled],\n'
    '            separators=(",", ":"),\n'
    '        )\n'
    '\n'
    '        def build_main_component():\n'
    '            filtered = filtered_frame()\n'
)
new = (
    '            credit_view,\n'
    '            generation_state=generation_state,\n'
    '        )\n'
    '\n'
    '        def build_main_component():\n'
    '            filtered = filtered_frame()\n'
)
replace_exact('cube/pages/risk/s07_explorer.py', old, new)
```

#### cube/pages/risk/s07_explorer.py — replacement 5

```python
old = (
    '                    underlying_identity_mode=selected_identity_mode,\n'
    '                    underlying_sort_metric=selected_sort_metric,\n'
    '                )\n'
    '            if active_risk_type == "Credit":\n'
    '                filtered = apply_credit_measure(filtered, credit_measure)\n'
    '            return build_risk_table(\n'
    '                filtered,\n'
    '                expanded_metrics,\n'
)
new = (
    '                    underlying_identity_mode=selected_identity_mode,\n'
    '                    underlying_sort_metric=selected_sort_metric,\n'
    '                )\n'
    '            aggregation_index = cache.hierarchy_index(\n'
    '                filtered,\n'
    '                credit_measure=(\n'
    '                    credit_measure or CREDIT_MEASURES[0]\n'
    '                    if active_risk_type == "Credit"\n'
    '                    else None\n'
    '                ),\n'
    '            )\n'
    '            return build_risk_table(\n'
    '                filtered,\n'
    '                expanded_metrics,\n'
)
replace_exact('cube/pages/risk/s07_explorer.py', old, new)
```

#### cube/pages/risk/s07_explorer.py — replacement 6

```python
old = (
    '                region_enabled=region_enabled,\n'
    '                underlying_identity_mode=selected_identity_mode,\n'
    '                underlying_sort_metric=selected_sort_metric,\n'
    '            )\n'
    '\n'
    '        return cache.rendered(render_key, build_main_component), no_update\n'
    '\n'
    '    def render_active_detail(\n'
    '        *,\n'
)
new = (
    '                region_enabled=region_enabled,\n'
    '                underlying_identity_mode=selected_identity_mode,\n'
    '                underlying_sort_metric=selected_sort_metric,\n'
    '                aggregation_index=aggregation_index,\n'
    '            )\n'
    '\n'
    '        return cache.render_explorer(build_main_component), no_update\n'
    '\n'
    '    def render_active_detail(\n'
    '        *,\n'
)
replace_exact('cube/pages/risk/s07_explorer.py', old, new)
```

#### cube/ui/s02_aggregation.py — replacement 1

```python
old = (
    '        totals = np.bincount(inverse, weights=values)\n'
    '        return groups, totals / counts\n'
    '\n'
    '    def value(self, row_positions: np.ndarray) -> float:\n'
    '        """Evaluate the existing option -> swap -> underlying mean hierarchy."""\n'
    '        if not len(row_positions) or not len(self._quote_values):\n'
)
new = (
    '        totals = np.bincount(inverse, weights=values)\n'
    '        return groups, totals / counts\n'
    '\n'
    '    @property\n'
    '    def memory_bytes(self) -> int:\n'
    '        """Array storage retained by this quote index."""\n'
    '        return sum(\n'
    '            values.nbytes\n'
    '            for values in (\n'
    '                self._row_quote_codes,\n'
    '                self._quote_values,\n'
    '                self._quote_to_option,\n'
    '                self._option_to_swap,\n'
    '                self._swap_to_underlying,\n'
    '            )\n'
    '        )\n'
    '\n'
    '    def value(self, row_positions: np.ndarray) -> float:\n'
    '        """Evaluate the existing option -> swap -> underlying mean hierarchy."""\n'
    '        if not len(row_positions) or not len(self._quote_values):\n'
)
replace_exact('cube/ui/s02_aggregation.py', old, new)
```

#### cube/ui/s02_aggregation.py — replacement 2

```python
old = (
    '\n'
    '\n'
    'class HierarchyAggregationIndex:\n'
    '    """Precomputed numeric and quote state for one hierarchy render.\n'
    '\n'
    '    The previous renderer rebuilt three pandas grouping pipelines and three\n'
    '    validation DataFrames for every visible node. This index factorizes quote\n'
    '    identities once, stores numeric measures in contiguous arrays, and then\n'
    '    evaluates each scoped node with small NumPy reductions. It is deliberately\n'
    '    request-local: no caller-owned DataFrame or cross-user state is mutated.\n'
    '    """\n'
    '\n'
    '    _ROW_POSITION_BASE = "__cube_aggregation_row_position__"\n'
)
new = (
    '\n'
    '\n'
    'class HierarchyAggregationIndex:\n'
    '    """Reusable numeric and quote state for one immutable data scope.\n'
    '\n'
    '    The previous renderer rebuilt three pandas grouping pipelines and three\n'
    '    validation DataFrames for every visible node. This index factorizes quote\n'
    '    identities once, stores numeric measures in contiguous arrays, and then\n'
    '    evaluates each scoped node with small NumPy reductions. Callers may share\n'
    '    the index across renders of the same scope, but must not mutate its frame\n'
    '    or the source frame. Aggregation itself only reads the retained state.\n'
    '    """\n'
    '\n'
    '    _ROW_POSITION_BASE = "__cube_aggregation_row_position__"\n'
)
replace_exact('cube/ui/s02_aggregation.py', old, new)
```

#### cube/ui/s02_aggregation.py — replacement 3

```python
old = (
    '            column: _MarketQuoteIndex(frame, column) for column in _MARKET_COLUMNS\n'
    '        }\n'
    '\n'
    '    def aggregate(\n'
    '        self,\n'
    '        scoped: pd.DataFrame,\n'
)
new = (
    '            column: _MarketQuoteIndex(frame, column) for column in _MARKET_COLUMNS\n'
    '        }\n'
    '\n'
    '    @property\n'
    '    def memory_bytes(self) -> int:\n'
    '        """Conservative retained-data accounting, not total process memory.\n'
    '\n'
    '        Count the whole frame even when its blocks are shared with the source;\n'
    '        retaining an index can outlive the filtered-frame cache entry.\n'
    '        """\n'
    '        return (\n'
    '            int(self.frame.memory_usage(index=True, deep=True).sum())\n'
    '            + self._sum_values.nbytes\n'
    '            + sum(index.memory_bytes for index in self._market_indexes.values())\n'
    '        )\n'
    '\n'
    '    def aggregate(\n'
    '        self,\n'
    '        scoped: pd.DataFrame,\n'
)
replace_exact('cube/ui/s02_aggregation.py', old, new)
```

### 3. Verify the change

```python
check_syntax(['cube/pages/risk/s02_state.py', 'cube/pages/risk/s06_explorertables.py', 'cube/pages/risk/s07_explorer.py', 'cube/ui/s02_aggregation.py'])
```

Expected: `Syntax OK` for every listed Python file. This checks whether Python can read the edited source; complete the browser steps below to check behaviour.

1. Open a standard Risk table and expand/collapse the same selection. Confirm the prepared aggregation index is reused while displayed rows are rebuilt.
2. Change filters, Credit measure, refresh and Clear Cache. Confirm old indexes are invalidated and financial totals remain identical.
3. Keep the complete dataset. Four entries / 256 MiB is a starting retained-index budget, not a row limit or process-memory guarantee. Oversized valid results calculate without retention.
4. Keep the separate Aggregate P&L and Top Promotions component cache and special Credit/Split calculations. Remove only Explorer finished-table retention.
5. Run the capacity jobs before enabling broad Portfolio detail. This cache job alone does not bound visible rows.

### 4. Roll back if verification fails

Stop the preview process using Job Z02. Run `restore_job('A02')` and repeat the focused checks. Restore later dependent jobs first if any have already been applied.

<a id="job-b01"></a>
## Job B01 — Check history size before allocating the grid

### 1. Back up and locate the files

```python
backup_job('B01', ['cube/history/s06_repository.py', 'cube/history/s01_models.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

The unified Data job later adds a request-local `max_cells` argument. When that job is applied, both checks below must use its `effective_max_cells`, so Risk + Market together obey one budget. Do not change the repository instance limit between requests.

### 2. Make the edits in this order

This is a capacity fix. It should preserve the same error/limit semantics for already rejected requests and avoid changing valid charts.

1. In `cube/history/s06_repository.py`, add `from math import prod` with the standard-library imports.
2. In `ArchiveHistoryRepository.read`, immediately after the `ordering = HistoryOrdering(...)` block and **before** `values = _canonical_values(...)`, add:

```python
        expected_cells = len(dates) * prod(
            len(axis.labels) for axis in ordering.axes
        )
        if expected_cells > self._max_cells:
            raise HistoryValidationError(
                f"Canonical history has {expected_cells:,} cells and exceeds the "
                f"{self._max_cells:,}-cell browser budget. Choose a narrower period "
                "or exact identity."
            )
```

3. Keep the existing post-build `len(values)` guard as a cheap defensive check. It also catches future changes to canonicalization whose size formula might differ.
4. Do not reduce a requested grid by silently dropping tenor/date cells. Missing cells must still become null for requests within budget.
5. Before running a broad selection, calculate its cell count in a notebook as shown in the verification steps below. Use a small display cap for the preview. A sparse input below the row cap must still be refused when its date × axis grid exceeds the cell cap, before `_canonical_values` is called. Keep scalar data, empty dates, empty axes and exactly-at-limit selections valid under their existing rules.
6. In Data, load a small one-axis history and a small two-axis history. Verify date and tenor order and then narrow the selection after a capacity notice. Do not allocate an enormous grid merely to demonstrate the hazard.

No cache or new subsystem is required. Rollback consists only of removing the import and preflight block.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/history/s06_repository.py', 'cube/history/s01_models.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Open Data with a small history selection. It must still load and play.
2. Set a small request-local display cap in an isolated preview and select more cells than that cap. It must show the capacity message before building the canonical grid. Narrowing the selection must load successfully.
3. Keep reading source rows unrestricted by the display-cell check except for the separate existing query bound. Restore the normal preview setting.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('B01')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-b02"></a>
## Job B02 — Apply the selected Risk scope before the SQL row limit

### 1. Back up and locate the files

```python
backup_job('B02', ['cube/history/s05_store.py', 'cube/history/s06_repository.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

The exact existing semantics matter: `RiskFilterView` validates an allowlisted tuple of filters; values are OR within one field and AND across fields. Exclusion negates each populated reporting field, while **Split always remains inclusive**. The current Data store converts legacy `FAKE_REPLACE_ME` text to `TEMP_REPLACE_ME` before pandas filtering; preserve that existing behaviour until Job C09 replaces the alias handling.

1. In `cube/history/s05_store.py`, import `RiskFilterView` from `.s01_models`.
2. Add this helper after `_quoted`. It interpolates only identifiers previously validated by `RiskFilterView` and quoted by `_quoted`; all selected values and legacy-label text remain SQL parameters:

```python
def _risk_filter_clause(view: RiskFilterView | None) -> tuple[str, list[object]]:
    if view is None:
        return "TRUE", []
    if not isinstance(view, RiskFilterView):
        raise TypeError("filter_view must be a RiskFilterView or None")
    clauses: list[str] = []
    parameters: list[object] = []
    for column, selected in view.filters:
        placeholders = ", ".join("?" for _value in selected)
        expression = f"replace(CAST({_quoted(column)} AS VARCHAR), ?, ?)"
        matches = f"coalesce({expression} IN ({placeholders}), FALSE)"
        negate = view.exclude_selected and column != "Split"
        clauses.append(f"NOT ({matches})" if negate else matches)
        parameters.extend((_LEGACY_ARCHIVE_NOTICE, _TEMP_NOTICE, *selected))
    return " AND ".join(clauses) or "TRUE", parameters
```

3. Add the keyword parameter `filter_view: RiskFilterView | None = None` to `ArchiveSQLStore.rows`. Before building `parameters`, calculate:

```python
        if kind != "risk" and filter_view is not None:
            raise ValueError("Market history does not accept Risk contributor filters")
        filter_clause, filter_parameters = _risk_filter_clause(filter_view)
```

4. In its SQL, add `AND ({filter_clause})` **after** the exact-underlying predicate and **before** the date predicate. Insert `*filter_parameters` into the bound parameter list after `*identities` and before `start_date`. Keep the `LIMIT max_rows + 1` parameter last.
5. In `ArchiveHistoryRepository.read`, add `filter_view=handoff.filter_view` to the `_store.rows(...)` call, immediately after its existing `max_rows=self._max_rows` argument. `HistoryHandoff.filter_view` is a real field in `s01_models.py`; its `__post_init__` explicitly rejects non-None filters for `kind == "market"` (around lines 357–365). Consequently valid Market requests pass `None`, and the store's new guard still rejects an invalid direct caller. No conditional is required or desirable to conceal invalid Market filters. Keep `_apply_risk_filters(...)` in place initially: it remains necessary for the legacy CSV fallback and provides a parity check while this change is introduced. Do not add contributor filters to Market queries.
6. Leave `available_dates` unchanged in this patch. That preserves current period resolution and visible gaps across the identity's observed dates. Filtering available dates too would alter which dates presets resolve to, and deserves a separate product decision.
7. Use an isolated six-row demonstration archive and temporarily set `max_rows=3` in its repository instance. Choose a Portfolio containing two of those rows: the selected read must return both rows. The unfiltered six-row read must give the existing capacity notice. A selected four-row read must also give that notice. Restore the normal cap afterwards.
8. Compare the new SQL selection against `_apply_risk_filters` on the full small reference frame. Check that invalid column names are rejected by `RiskFilterView` and quoted values remain parameters.

This change does not deduplicate positions, change quote grain, fill nulls, or bypass archive validation. Rollback removes the new argument/clause while retaining the established pandas filter.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/history/s05_store.py', 'cube/history/s06_repository.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the six-row archive example in edit step 7. Expected: the selected two-row scope loads under a three-row cap.
2. Compare include/exclude and Split selections with the old pandas filter on the same small frame. Quoted labels must match literally; invalid column names must be rejected.
3. Confirm unfiltered requests and selected requests above their own bounds still show the capacity notice.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('B02')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-b03"></a>
## Job B03 — Put a visible construction budget on the Risk hierarchy

### 1. Back up and locate the files

```python
backup_job('B03', ['cube/pages/risk/s06_explorertables.py', 'cube/pages/risk/s13_workspacetables.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

**This is an intermediate display safeguard.** It caps rows constructed at once, not source positions or financial totals. Keep the notice visible. Complete the paged Portfolio job to make all 300–400 books reachable without expanding everything. Do not describe this cutoff alone as unlimited browsing.

### 2. Make the edits in this order

Current source: `cube/pages/risk/s06_explorertables.py::build_tree_rows` at line 138; recursive call around line 316. `build_risk_table` starts at 335, `build_alt_risk_table` at 477, and `build_credit_multi_table` at 646. Closed branches already skip their descendants. There is no shared limit across the branches that are open. Each visible row constructs a label, buttons, cells, attributes and styles. The new index cache does not remove that output cost.

The smallest useful intermediate safeguard is a shared **render budget**, with a visible warning. It must be applied while constructing rows. Calling `body_rows[:2000]` after building everything is not a capacity fix. Do not truncate the source frame: financial totals must use the full filtered scope.

Exact implementation steps:

1. In `s06_explorertables.py`, immediately above `build_tree_rows`, add:

```python
_EXPLORER_TREE_ROW_LIMIT = 1999  # Plus the existing TOTAL row.


def _tree_limit_notice(budget: dict[str, int | bool]) -> list[html.Div]:
    if not budget["truncated"]:
        return []
    return [
        html.Div(
            f"Showing at most {_EXPLORER_TREE_ROW_LIMIT + 1:,} hierarchy rows. "
            "Some hierarchy rows are "
            "omitted. Totals include the full filtered scope. Collapse a "
            "branch or narrow the filters to see the remaining rows.",
            className="detail-note",
            role="status",
        )
    ]
```

2. Append this parameter to `build_tree_rows` after `underlying_sort_metric`:

```python
    render_budget: dict[str, int | bool] | None = None,
```

3. Inside its `for value in ordered_unique(...)` loop, before `next_context = ...`, add:

```python
        if render_budget is not None and int(render_budget["remaining"]) <= 0:
            render_budget["truncated"] = True
            break
```

4. Immediately after the existing `rows.append(html.Tr(...))` statement completes, before `if can_expand and is_open:`, add:

```python
        if render_budget is not None:
            render_budget["remaining"] = int(render_budget["remaining"]) - 1
```

5. In the recursive call to `build_tree_rows`, add `render_budget=render_budget`. The **same object** must be passed to all descendants; resetting 1,999 for each child would not bound the tree. Do not initialise a new budget inside `build_tree_rows`; initialise it only in each top-level builder as in step 6.

6. In each of `build_risk_table`, `build_alt_risk_table` and `build_credit_multi_table`, after the empty-frame return and before building the TOTAL row, add:

```python
    render_budget: dict[str, int | bool] = {
        "remaining": _EXPLORER_TREE_ROW_LIMIT,
        "truncated": False,
    }
```

7. Pass `render_budget=render_budget` into that builder's top-level `build_tree_rows(...)` call.

8. In each builder's final `html.Div([...], className="risk-table-wrap...", ...)`, add `*_tree_limit_notice(render_budget),` as the first item in the child list. Evaluate this after the tree has been built, as those functions already do.

9. Leave the default `render_budget=None` for direct callers until their separate presentation requirements are reviewed. One such caller exists in `cube/pages/risk/s13_workspacetables.py::build_top_book_exposures` at line 438; it is a separate Top Book helper, not the current ranked Top Promotions table. This change explicitly covers the three Explorer views and does not claim to bound every table in the application.

10. Keep Portfolio out of the main expanded hierarchy. After checking this row budget, implement the selected-scope, server-paged Portfolio breakdown in Job F10. It provides 50 portfolios per page with search and preserves full totals. The budget above is immediate display protection; it does not itself implement Portfolio navigation.

Correctness rules: TOTAL and every displayed parent still aggregate all matching positions; omitted rows must be disclosed; no summary should be labelled as a total of only the visible rows; stale action-token validation must remain; the row-budget mechanism cannot alter quote aggregation or source data. The warning deliberately does not claim an exact omitted-row count because calculating that would require walking the unrendered tree.

Verification: use the preview app with a temporary row budget of 8. Open two sibling branches and their grandchildren. The final table must have at most 8 hierarchy rows plus TOTAL. The notice must appear when another row was suppressed. TOTAL must still include the complete filtered scope. Collapse a branch: later branches can now use the freed display budget. Repeat for Cross, Split VA and Credit Multi. Restore the configured budget after this check. At 100k positions and 300–400 portfolios, start with a small visible selection and increase the display budget only while the browser remains responsive; 2,000 is an initial setting, not a universal safe limit.

Rollback: remove the helper, budget argument and the three caller additions together. Do not disable the warning while keeping truncation.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/risk/s06_explorertables.py', 'cube/pages/risk/s13_workspacetables.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the temporary eight-row budget check above, including collapsed branches.
2. Compare TOTAL with the original full-scope number; it must not change when opening or closing rows.
3. Restore the configured display budget. Continue to F10 for pageable Portfolio detail.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('B03')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-b04"></a>
## Job B04 — Send Stock position detail one requested page at a time

### 1. Back up and locate the files

```python
backup_job('B04', ['cube/pages/stock/s03_view.py', 'cube/pages/stock/s04_callbacks.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

Later Stock selection/Changes/column jobs must extend the new `selected_display` helper and seven-output callback created here. They must not paste the old eight-output callback back into this file.

### 2. Make the edits in this order

The related Statics Read table has the same native-pagination payload issue. Keep its solution separate from the small editable mapping tables, which need whole-frame validation.

The practical minimal Stock change is one page callback over the already server-owned `StockPageData`. It does not need a database or a cache of HTML tables. There is a UX choice: the snippet below replaces the native column-query language with an explicit plain-text search box. If the native filter syntax must remain, implement and check a small allowlisted parser instead; do not use `eval`, and do not claim native filtering works across rows the browser never receives.

#### Exact Stock edits, in order

1. In `cube/pages/stock/s03_view.py`, add `from math import ceil` with the standard-library imports. Add `stock_detail_page` to the module's existing `__all__` list.
2. Replace the complete `build_stock_position_detail` function, from its `def` through its return and before `build_stock_filter_bar`, with this function. It retains the existing argument for current builder call sites, and creates no position records during layout construction. Use an explicit button and callback-owned `Div.hidden`, as below: the installed Dash HTML component only reports Details clicks and does not synchronize a native Summary toggle back to `Details.open`. An `Input(..., "open")` alone would therefore not reliably load the detail:

```python
def build_stock_position_detail(display: pd.DataFrame) -> html.Div:
    """Create a lazy, server-paged view of unaggregated connector rows."""
    del display
    table = dash_table.DataTable(
        id="stock-position-detail-table",
        columns=_stock_table_columns(),
        data=[],
        filter_action="none",
        sort_action="custom",
        sort_mode="multi",
        sort_by=[],
        page_action="custom",
        page_current=0,
        page_size=50,
        page_count=0,
        active_cell=None,
        fixed_rows={"headers": True},
        style_table={"overflowX": "auto", "maxHeight": "52vh"},
        style_cell={
            "padding": "7px 9px",
            "textAlign": "left",
            "minWidth": "100px",
            "whiteSpace": "nowrap",
        },
        style_cell_conditional=[
            {
                "if": {"column_id": ["Quantity", "Stock", "dStock"]},
                "textAlign": "right",
                "fontVariantNumeric": "tabular-nums",
            }
        ],
    )
    content = html.Div(
        [
            html.P(
                "Static identifiers and Portfolio mappings are shown exactly as received.",
                className="page-note",
            ),
            html.Label("Search position detail", htmlFor="stock-detail-search"),
            dcc.Input(
                id="stock-detail-search",
                type="text",
                debounce=True,
                value="",
                maxLength=200,
            ),
            html.P(id="stock-detail-status", className="page-note", role="status"),
            table,
        ],
        id="stock-position-detail",
        hidden=True,
    )
    return html.Div(
        [
            html.Button(
                "Show position detail",
                id="stock-detail-toggle",
                type="button",
                n_clicks=0,
                **{"aria-expanded": "false", "aria-controls": "stock-position-detail"},
            ),
            content,
        ],
        className="stock-position-detail",
    )
```

3. In the same module, add this complete helper **after** `stock_table_records` and **before** `stock_pivot_columns`. It searches/sorts the full filtered frame, then serializes only the selected slice. Invalid browser page/sort values fail explicitly; no filter expression is evaluated:

```python
def stock_detail_page(display, *, search="", page_current=0, page_size=50, sort_by=()):
    text = str(search or "").strip()
    if len(text) > 200:
        raise ValueError("Stock detail search is limited to 200 characters")
    if isinstance(page_size, bool) or page_size not in {15, 25, 50, 100}:
        raise ValueError("Unsupported Stock detail page size")
    size = int(page_size)
    if isinstance(page_current, bool) or not isinstance(page_current, int) or page_current < 0:
        raise ValueError("Invalid Stock detail page number")
    if not isinstance(sort_by, (list, tuple)):
        raise ValueError("Invalid Stock detail sort")
    work = display
    if text:
        matches = pd.Series(False, index=work.index)
        for column in STOCK_DISPLAY_COLUMNS:
            matches |= work[column].astype("string").str.contains(
                text, case=False, regex=False, na=False
            )
        work = work.loc[matches]
    columns, ascending = [], []
    for item in sort_by or ():
        if not isinstance(item, Mapping):
            raise ValueError("Invalid Stock detail sort")
        column, direction = item.get("column_id"), item.get("direction")
        if column not in STOCK_DISPLAY_COLUMNS or direction not in {"asc", "desc"}:
            raise ValueError("Invalid Stock detail sort")
        if column not in columns:
            columns.append(column)
            ascending.append(direction == "asc")
    if columns:
        work = work.sort_values(columns, ascending=ascending, kind="stable")
    pages = ceil(len(work) / size)
    page = min(page_current, max(pages - 1, 0))
    return stock_table_records(work.iloc[page * size : (page + 1) * size]), pages
```

4. In `cube/pages/stock/s04_callbacks.py`, replace the current import `from .s03_view import STOCK_PERIODS, stock_pivot_columns, stock_table_records` with:

```python
from .s03_view import STOCK_PERIODS, stock_detail_page, stock_pivot_columns
```

5. Inside `register_callbacks`, immediately after the existing local `cached_page` helper and before the callback decorated with `Output("stock-loaded-snapshot", "data")`, insert this helper. This is the **exact existing filter-resolution block**, moved to one location; it uses the already imported functions and retains the prior fallback and logging:

```python
    def selected_display(page_data: StockPageData, committed_filter_state) -> pd.DataFrame:
        try:
            committed_values = committed_filter_state_values(
                committed_filter_state,
                STOCK_SAVED_VIEW_CONTROLS,
            )
        except ValueError as error:
            app.logger.warning("Ignoring invalid committed Stock filters: %s", error)
            committed_values = None
        if committed_values is None:
            defaults = default_stock_filter_values(page_data.mapped_stock)
            filter_values = [defaults[field.key] for field in STOCK_FILTER_FIELDS]
            exclude_value: list[str] = []
        else:
            filter_values, exclude_value = committed_values
        return stock_display_rows(
            page_data.mapped_stock,
            dimension_filters=stock_filter_map(filter_values),
            exclude_selected=stock_exclude_selected(exclude_value),
        )
```

6. Replace the complete `render_current_stock` callback, **including its decorator**, from `@app.callback(Output("stock-current-table", "data"), ...)` through the end of the function and before `toggle_stock_branch`, with the following. Its inputs stay the same. Its output tuple changes from eight to **seven** everywhere because position detail now has its own callback. This includes the empty, pivot-only and full-update return branches:

```python
    @app.callback(
        Output("stock-current-table", "data"),
        Output("stock-current-table", "columns"),
        Output("stock-row-count", "children"),
        Output("stock-mapped-count", "children"),
        Output("stock-unmapped-count", "children"),
        Output("stock-history-crds", "options"),
        Output("stock-history-activity", "options"),
        Input("stock-loaded-snapshot", "data"),
        Input(STOCK_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
        Input("stock-pivot-rows", "value"),
        Input("stock-pivot-column", "value"),
        Input("stock-pivot-values", "value"),
        Input("stock-pivot-open-paths", "data"),
        prevent_initial_call=True,
    )
    def render_current_stock(
        loaded_snapshot,
        committed_filter_state,
        pivot_rows,
        pivot_column,
        pivot_values,
        open_paths,
    ):
        page_data = cached_page(loaded_snapshot)
        if page_data is None:
            empty = pd.DataFrame(columns=list(STOCK_DISPLAY_COLUMNS))
            pivot = build_stock_pivot(
                empty,
                row_fields=pivot_rows,
                column_field=pivot_column,
                value_fields=pivot_values,
                open_paths=open_paths,
            )
            return (
                [], stock_pivot_columns(pivot.columns),
                "Rows: 0", "Mapped: 0", "Unmapped: 0", [], [],
            )
        display = selected_display(page_data, committed_filter_state)
        pivot = build_stock_pivot(
            display,
            row_fields=pivot_rows,
            column_field=pivot_column,
            value_fields=pivot_values,
            open_paths=open_paths,
        )
        try:
            trigger = ctx.triggered_id
        except MissingCallbackContextException:
            trigger = None
        if trigger in {
            "stock-pivot-open-paths", "stock-pivot-rows",
            "stock-pivot-column", "stock-pivot-values",
        }:
            return (
                pivot.records, stock_pivot_columns(pivot.columns),
                no_update, no_update, no_update, no_update, no_update,
            )
        all_rows = stock_display_rows(page_data.mapped_stock)
        crds_values = sorted(
            all_rows["CRDS"].astype(str).unique().tolist(), key=str.casefold
        )
        activity_values = sorted(
            all_rows["Activity"].astype(str).unique().tolist(), key=str.casefold
        )
        mapped = int(display["Portfolio Mapped"].eq(True).sum())
        return (
            pivot.records,
            stock_pivot_columns(pivot.columns),
            f"Rows: {len(display):,} of {len(all_rows):,}",
            f"Mapped: {mapped:,}",
            f"Unmapped: {len(display) - mapped:,}",
            [{"label": value, "value": value} for value in crds_values],
            [{"label": value, "value": value} for value in activity_values],
        )
```

7. Immediately after that replacement callback, still **inside** `register_callbacks` and before `toggle_stock_branch`, add these three complete callbacks. The explicit button owns visibility; the detail renderer owns data/page count/status; the reset callback owns page reset/active cell. There are no duplicate outputs and no connector reads. Button clicks produce a real Dash property update, so visibility and loading remain synchronized. Do not add the entire frame to a `dcc.Store`:

```python
    @app.callback(
        Output("stock-position-detail", "hidden"),
        Output("stock-detail-toggle", "children"),
        Output("stock-detail-toggle", "aria-expanded"),
        Input("stock-detail-toggle", "n_clicks"),
        prevent_initial_call=True,
    )
    def toggle_stock_detail(clicks):
        opened = bool(int(clicks or 0) % 2)
        return (
            not opened,
            "Hide position detail" if opened else "Show position detail",
            str(opened).lower(),
        )

    @app.callback(
        Output("stock-position-detail-table", "data"),
        Output("stock-position-detail-table", "page_count"),
        Output("stock-detail-status", "children"),
        Input("stock-position-detail", "hidden"),
        Input("stock-loaded-snapshot", "data"),
        Input(STOCK_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
        Input("stock-detail-search", "value"),
        Input("stock-position-detail-table", "page_current"),
        Input("stock-position-detail-table", "page_size"),
        Input("stock-position-detail-table", "sort_by"),
        prevent_initial_call=True,
    )
    def render_stock_detail(
        detail_hidden,
        loaded_snapshot,
        committed_filter_state,
        search,
        page_current,
        page_size,
        sort_by,
    ):
        if detail_hidden is not False:
            return [], 0, ""
        page_data = cached_page(loaded_snapshot)
        if page_data is None:
            return [], 0, "Load current Stock to inspect position detail."
        try:
            display = selected_display(page_data, committed_filter_state)
            records, pages = stock_detail_page(
                display,
                search=search,
                page_current=page_current,
                page_size=page_size,
                sort_by=sort_by,
            )
        except (TypeError, ValueError) as error:
            app.logger.warning("Could not render Stock detail: %s", error)
            return [], 0, f"Position detail could not be shown: {error}"
        if not pages:
            return [], 0, "No positions match this search and the applied filters."
        return records, pages, f"{len(records):,} positions on this page · {pages:,} pages."

    @app.callback(
        Output("stock-position-detail-table", "page_current"),
        Output("stock-position-detail-table", "active_cell"),
        Input("stock-loaded-snapshot", "data"),
        Input(STOCK_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
        Input("stock-detail-search", "value"),
        Input("stock-position-detail-table", "sort_by"),
        Input("stock-position-detail-table", "page_size"),
        prevent_initial_call=True,
    )
    def reset_stock_detail_page(
        _loaded_snapshot, _committed_filter_state, _search, _sort_by, _page_size
    ):
        return 0, None
```

The reset callback may cause an additional small page projection when filters/search change; it avoids leaving the browser on a stale page number. The full source remains server-owned. This change intentionally does not introduce a cache to eliminate that second projection before measuring it.

8. Keep `toggle_stock_branch` and `select_stock_row` unchanged. The existing history row-click callback listens to `stock-current-table.active_cell` (the pivot). The position-detail table does **not** currently have its own history-click callback, and this pagination change does not silently add one. Its compact row IDs are preserved.
9. Open the detail panel, sort, search and page through it. Confirm a hidden panel sends no position rows, each displayed page contains at most its requested size, and a search can find an identity outside the first page. Opening and closing the panel must update its button label. Confirm there is one callback owner for each new output; use the callback-owner check in Job Z03.
10. Keep summary counts calculated from the **full filtered current Stock frame**. Do not replace full-scope counts or pivot totals with page totals. If export is added later, perform it from the same server query and clearly distinguish “this page” from “all matching rows”.
11. Run the syntax cell below, restart the preview, then check opening/closing detail, multi-column sorting, search debounce, next/previous pages, saved-filter application and refresh. A filter or search change must return to page zero. Nulls and connector metadata must remain unchanged. Keep row-click history on the pivot table.

This eliminates the major payload without introducing a second full-data cache. Sorting/filtering 100k rows still has a server cost; measure it before adding any filtered-view cache. Rollback restores the native table and its original output ownership.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/stock/s03_view.py', 'cube/pages/stock/s04_callbacks.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Restart the notebook kernel before importing the edited module, then rerun A00 setup/helper cells. Run the self-contained page check below.
2. In the preview, opening detail shows one page; closing it clears its returned rows. A search finds an identity beyond the original first page.
3. Change saved filters and refresh: page zero and full-scope pivot totals must update consistently.

```python
import pandas as pd
from cube.pages.stock.s01_data import STOCK_DISPLAY_COLUMNS
from cube.pages.stock.s03_view import stock_detail_page

example = pd.DataFrame({column: ["example"] * 123 for column in STOCK_DISPLAY_COLUMNS})
for column in ("Quantity", "Stock", "dStock"):
    if column in example:
        example[column] = 1.0
example["CRDS"] = [f"ROW-{i:03d}" for i in range(123)]
first, count = stock_detail_page(example, page_size=50)
last, last_count = stock_detail_page(example, page_current=2, page_size=50)
found, found_count = stock_detail_page(example, search="ROW-122", page_size=50)
assert len(first) == 50 and count == 3
assert len(last) == 23 and last_count == 3
assert len(found) == 1 and found_count == 1
assert found[0]["CRDS"] == "ROW-122"
print("Page size, final page and full-frame search are correct")
```

This creates 123 temporary rows in notebook memory. It does not read or change your financial data. Expected: the final success message without an exception.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('B04')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-b05"></a>
## Job B05 — Bound the current P&L Validate tree before changing its navigation

### 1. Back up and locate the files

```python
backup_job('B05', ['cube/pages/pnl/s06_validation.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

**Apply this before the later P&L navigation job.** Keep the existing local hidden-row toggle until server-owned expansion/paging and all callback owners have been replaced together. After the later job, retain a construction bound on its requested visible page; do not restore hidden descendants.

### 2. Make the edits in this order

This is the exact situation discussed in the Portfolio conversation: caching numeric leaf data is useful; building every descendant's HTML and hiding it is still expensive. The current local JavaScript toggles depend on descendants being present, so simply changing `if can_expand:` to `if can_expand and is_open:` would break expansion. Do not make that isolated edit.

Recommended staged change:

1. First add a global build budget, for example `_VALIDATE_PL_MAX_RENDERED_ROWS = 1_000`, next to `VALIDATE_PL_CHILD_LIMIT`. Keep the ten-child limit too. Treat the number as an initial measured UI budget, not a financial limit.
2. Add an optional shared mutable counter argument to `_tree_rows`, initialized once at the root, passed to recursive calls, decremented before creating each `html.Tr`. Return immediately if it reaches zero. Use the same counter across all branches rather than resetting it per recursion. Do not change `_hierarchy_nodes` or its full-scope aggregates.

```python
# Add to _tree_rows' keyword parameters:
remaining: list[int] | None = None,

# Add at the beginning of _tree_rows:
if remaining is None:
    remaining = [_VALIDATE_PL_MAX_RENDERED_ROWS]

# Add at the start of the for-path loop, before creating components:
if remaining[0] <= 0:
    break
remaining[0] -= 1

# Pass through to its existing recursive _tree_rows(...) call:
remaining=remaining,
```

3. Update the visible limit note in `_validate_tree_table`: “Totals include every filtered row. The tree shows up to 10 children per branch and up to 1,000 hierarchy rows in this view. Narrow the page filters to inspect other rows.” This is honest truncation disclosure; do not imply a hidden child was absent from source data.
4. A bounded tree can still hide some children due to depth-first allocation. Treat the hard bound as immediate crash protection, not the final browse experience. The subsequent functional change should reuse the current comparison/numeric hierarchy and render requested branches on the server, with the 25-row child page specified in Job C07. Add a browser store for open paths and parent pages, replace only the Validate toggle's local DOM handler with a Dash callback, and build descendants only when opened. This is a coupled Python/JavaScript change and requires the browser checks in Job C07; it is not supplied as a one-line patch.
5. As immediate protection before C07, in `_validate_unmapped_table` replace only `for record in unmapped.to_dict("records"):` with `for record in unmapped.head(50).to_dict("records"):`. Keep the Summary count based on `len(unmapped)`. Append this sentence to its existing explanatory paragraph: “This preview shows the first 50 unmapped entries; the count and financial totals still include every filtered entry. Narrow the page filters to inspect another scope.” Do not slice the comparison frame passed to financial aggregation. C07 replaces this temporary first-page loop with searchable server paging so every entry is reachable.
6. In the preview app, temporarily lower the hierarchy budget to 20 and open a scope with several branches. Count the displayed hierarchy rows; closed descendants also consume this temporary budget because they are still constructed in this intermediate job. The whole constructed hierarchy must stay within 20 rows, with headers/root additional. Root totals must equal the full filtered input and the limit note must be visible. Restore the configured budget. Complete Job C07 before describing this as fully pageable navigation.

Rollback of stage one is only the budget/counter/note. Do not remove the existing date comparison cache, hierarchy prefix grouping, stale-generation checks, or authoritative archive hash validation.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/pnl/s06_validation.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the small temporary row-budget check above. Confirm the note and unchanged root totals.
2. Open and close a branch; the existing local toggle must still work at this intermediate stage.
3. Complete C07 before allowing deep browsing. Keep the capacity guard even after paging is added.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('B05')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-b06"></a>
## Job B06 — Bound the P&L history caches without rejecting valid results

### 1. Back up and locate the files

```python
backup_job('B06', ['cube/history/s07_sql.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

Do not replace this with a general distributed cache. A process-local LRU is sufficient for this reconstructable state. Each worker owns its own budget; deployment memory budgeting must multiply by worker count and include live query memory.

1. Add `from collections import OrderedDict` and `import sys` to `s07_sql.py`.
2. Keep the existing key/value type annotations, but initialize `_stats_cache` and `_risk_summary_cache` as `OrderedDict()` instead of `{}`. Optionally annotate them as OrderedDict explicitly for clarity.
3. Add `_PL_STATS_CACHE_ENTRIES = 128`, `_PL_RISK_CACHE_ENTRIES = 16`, and `_PL_RISK_CACHE_BYTES = 16 * 1024 * 1024` beside other private query limits. These are initial tunable retention budgets, not hard process-RSS guarantees.
4. Add this size helper near `_empty_summary`. `deep=True` covers DataFrame text but tuple paths may own nested strings, so count those conservatively as well:

```python
def _risk_summary_cache_bytes(result: PLRiskSummaryResult) -> int:
    frame = result.summary
    paths = frame.get(PL_RISK_SUMMARY_PATH, ())
    nested = sum(
        sys.getsizeof(part)
        for path in paths
        if isinstance(path, tuple)
        for part in path
    )
    return int(frame.memory_usage(index=True, deep=True).sum()) + nested
```

5. Add these two methods to `SQLPLHistoryRepository`, and call them only while its existing `RLock` is held:

```python
    def _remember_stats(self, key, value) -> None:
        self._stats_cache[key] = value
        self._stats_cache.move_to_end(key)
        while len(self._stats_cache) > _PL_STATS_CACHE_ENTRIES:
            self._stats_cache.popitem(last=False)

    def _remember_risk_summary(self, key, result) -> None:
        if _risk_summary_cache_bytes(result) > _PL_RISK_CACHE_BYTES:
            return
        self._risk_summary_cache[key] = result
        self._risk_summary_cache.move_to_end(key)
        while (
            len(self._risk_summary_cache) > _PL_RISK_CACHE_ENTRIES
            or sum(_risk_summary_cache_bytes(item)
                   for item in self._risk_summary_cache.values()) > _PL_RISK_CACHE_BYTES
        ):
            self._risk_summary_cache.popitem(last=False)
```

6. Replace `self._stats_cache[key] = cached` in `_cached_stats` with `self._remember_stats(key, cached)`. On a hit call `move_to_end(key)`.
7. In `_remember_hierarchy_stats`, replace the final direct dictionary assignment, from `self._stats_cache[(clause, tuple(parameters))] = (` through that tuple's closing parenthesis, with this complete call. Keep the preceding `metrics` calculation unchanged:

```python
        self._remember_stats(
            (clause, tuple(parameters)),
            (
                result.row_count,
                result.date_count,
                result.minimum_date,
                result.maximum_date,
                result.unmapped_rows,
                metrics,
            ),
        )
```
8. In `risk_summary`, on an existing cache hit call `self._risk_summary_cache.move_to_end(cache_key)` before returning its defensive copy. Replace `self._risk_summary_cache[cache_key] = result` with `self._remember_risk_summary(cache_key, result)`.
9. Keep both clear operations in `_close_connection`. Keep returned defensive DataFrame copies: callers must not mutate retained results. An oversized result can still be returned to the current caller; it simply must not remain cached.
10. Cap total selected filter values separately if profiling or abuse hardening needs it. The current `_normalized_filters` caps each text length but not count; a 128-entry stats cache alone is not a strict byte bound for arbitrarily large key tuples. A simple key-byte check can skip caching a key whose UTF-8 text estimate exceeds 16 KiB, without rejecting the underlying valid query. If applied, use it in both remember methods.
11. In a preview repository instance with a small cache setting, read several distinct scopes, revisit one and add another scope. Confirm the entry count/estimated bytes stay within their limits and recently used entries are retained. Repeat an evicted selection: its full result must match the first read. A result larger than the retention budget must still return correctly without being retained. Clear Cache and a newly published archive generation must invalidate old entries. Mutating a returned summary must not change a subsequent read.

The DataFrame byte estimate is accounting, not exact RSS; Python and DuckDB overhead, temporary copies and active queries remain separate. Use an RSS measurement during representative repeated-filter use to select final values.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/history/s07_sql.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Open several P&L history scopes, revisit the first, and use Clear Cache. Full totals must remain identical.
2. Inspect the small-cap preview cache as described above; eviction must bound retention without rejecting a valid result.
3. Publish a new isolated demonstration day and reload. The new generation must be visible without reusing an old summary.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('B06')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-b07"></a>
## Job B07 — Stop Statics Read work while Write is displayed

### 1. Back up and locate the files

```python
backup_job('B07', ['cube/pages/static_data/s03_callbacks.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

The smallest change is to stop rebuilding the Read panel while Write is selected:

1. In `s03_callbacks.py`, locate the callback with `Output("static-data-table-container", "children")`.
2. Add `Input("static-data-mode", "value")` after the revision input. `Input` and `no_update` are already imported.
3. Replace only that callback function with the following complete definition. Keep the existing Statics Write picker reset and editor/save callback unchanged.

```python
    def render_static_data_table(selected_file, _revision, mode):
        if mode != "read":
            return no_update
        if not selected_file:
            return html.Div("No file selected.", className="static-data-empty")
        return build_static_data_table(selected_file, store=static_store)
```

4. In Statics, keep Write displayed and save an isolated demonstration mapping. The hidden Read table must not reload on the revision update. Switch to Read: it must load once and display the saved revision. Inspect the callback with `show_symbol` and confirm its Write-mode return occurs before any store read; the signature now accepts the third `mode` argument.
5. Validate entering Write, saving, switching back to Read, changing files, and keeping an unsaved Write draft when switching modes. This change does not add a mode-triggered editor reload, which could discard such a draft.

This avoids unnecessary hidden work but still sends the full file when Read is used. If real `s03_risk.csv` is much larger, implement **read-only server pagination** as a separate UI change using the same principles as Stock position detail: filter and sort the full permitted source before selecting the page; show total count and page scope; whitelist fields; reset page state on file/scope change. Changing `page_size` alone does not solve network/memory use. Do not page the writable mapping buffer and then save only that page through the current whole-file replacement API. Small governed Write files should retain whole-table validation and atomic saving.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/static_data/s03_callbacks.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Keep Statics Write visible and change its selected frame. It must display the correct table and remain responsive.
2. Save an isolated demonstration mapping and then switch to Read. It must show the saved revision.
3. Inspect the callback: Write mode returns before the Read store is queried.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('B07')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-c01"></a>
## Job C01 — Use replacement P&L values consistently

**Result:** entering 10 against a calculated P&L of 100 means an effective P&L of 10. It does not mean 110. The editor, saved overlay, preview and send payload must agree. This job chooses replacement semantics; do not introduce a second delta mode.

**KEEP:** `build_pl_send_base`, mapping validation, Portfolio governance, `ADJUSTMENT_KEY`, the current date/revision/filter guards, and `apply_adjustment_overlay` as the financial overlay. `ADJUSTMENT_KEY` is exactly Market Date + Portfolio + ConcertoField. Risk Type, Risk Greek and SignoffGroup remain governed metadata, not extra ways to create duplicate replacement keys.

**REMOVE:** summing an added replacement row together with the displayed base row; treating absence from a filtered editor as a request to delete an adjustment; sending unsaved draft rows directly.

Jobs C01 and C02 form one change: perform C01's edits, then C02's storage/wiring edits, then run both sets of checks before restarting the app with Save enabled.

1. Back up the files before editing:

   ```python
   backup_job("C01", [
       "cube/domain/s08_pnl.py",
       "cube/pages/pnl/s02_editor.py",
       "cube/pages/pnl/s04_sender.py",
       "cube/pages/pnl/s05_sendcallbacks.py",
   ])
   ```

2. Open `cube/domain/s08_pnl.py` and locate `apply_adjustment_overlay`. Keep its base-row aggregation. Immediately before it collapses `adjustment_rows`, call `validate_pl_send_rows(adjustment_rows, mapping, portfolio_governance, require_adjustment=True, allow_duplicates=False)`. Pass that validated frame to the existing adjustment collapse. This rejects two replacements for the same key instead of adding them. Do not change `collapse_pl_send_rows` globally: adding source positions into a base total is still valid.

3. In `cube/pages/pnl/s02_editor.py`, add this pure helper after `_domain_frame`. The frame passed as `base` must come from `build_pl_send_base`; it must not already contain saved adjustments. Add `ADJUSTMENT_KEY`, `PL_SEND_COLUMNS`, `validate_pl_send_rows` and `apply_adjustment_overlay` to the existing imports if absent.

   ```python
   def replacement_preview(base, saved, edited, mapping, governance, *, delete_keys=()):
       """Build one effective result without mutating the saved adjustment set."""
       saved = saved.reindex(columns=list(PL_SEND_COLUMNS)).copy()
       edited = edited.reindex(columns=list(PL_SEND_COLUMNS)).copy()
       saved = validate_pl_send_rows(
           saved, mapping, governance,
           require_adjustment=True, allow_duplicates=False,
       )
       edited = validate_pl_send_rows(
           edited, mapping, governance,
           require_adjustment=True, allow_duplicates=False,
       )
       deletes = {tuple(str(value) for value in key) for key in delete_keys}
       edited_keys = set(edited[list(ADJUSTMENT_KEY)].itertuples(index=False, name=None))
       if edited_keys & deletes:
           raise ValueError("A replacement cannot be saved and cleared together")
       saved_keys = saved[list(ADJUSTMENT_KEY)].apply(tuple, axis=1)
       retained = saved.loc[~saved_keys.isin(edited_keys | deletes)]
       replacements = pd.concat([retained, edited], ignore_index=True)
       return apply_adjustment_overlay(base, replacements, mapping, governance)
   ```

4. In `s02_editor.py`, keep `_govern_current_editor_records` responsible for validating the selected SOG/Portfolio and mapping edited fields. In the add-row path, look up the governed adjustment key after Risk Type/Greek and Portfolio have been selected. If that key already appears in the editor, select its existing row and display “Edit the existing replacement for this Portfolio and field.” Do not append another row for the same key. Reject duplicate keys again at Save; browser prevention alone is insufficient.

5. In `_drafts_with_scope`, keep the existing revision/date/filter/allowed-Portfolio/scope fields and `rows` for rendering. Add three explicit fields: `edited_rows`, `delete_keys`, and `adjustment_version`. `edited_rows` contains only new/changed replacement rows, not every currently visible row. For a row already carrying a saved adjustment, do not consider `Adjustment=True` alone proof that the user edited it. Compare the governed editable signature with the baseline captured when the editor loaded. Keep grid row IDs stable until the editor is reloaded. Add `adjustment_version` to `_matching_draft_rows`' identity guards. Remove `include_adjustments` from those identity guards: showing/hiding saved rows is a presentation change, not permission to lose a pending edit. Permit an empty `rows` list when valid `delete_keys` exist; the current `not rows` check must not discard a clear-only draft. Read delete keys directly from the same validated draft entry when calling the preview and Save helpers.

6. In `cube/pages/pnl/s04_sender.py`, change the numeric editor label to “Replacement P&L”. Add a short caption: “This value replaces calculated P&L for the selected Portfolio and field.” Add per-section “Clear selected saved replacement” buttons with IDs `clear-sog-replacement-button` and `clear-portfolio-replacement-button`. In `s05_sendcallbacks.py::register_editor`, add a `clear_id` argument and pass the matching ID at its two call sites. Add `Input(clear_id, "n_clicks")` and `State(table_id, "active_cell")` to its existing callback; update the function parameters in the same order and keep all six outputs unchanged. Resolve `active_cell["row_id"]` against the server-governed baseline, not merely its visible row number. Add the complete key to `delete_keys`; remove any pending edit for the same key. A cleared saved replacement reveals its base P&L. Removing an unsaved newly added row only removes the draft row; it does not create a delete request. Never infer clearing from a row that disappears when Show adjustments is off.

7. In `s05_sendcallbacks.py`, change both SOG and Portfolio preview paths to call `replacement_preview`. Build the unadjusted base once for the exact allowed Portfolios, pass the complete saved adjustment set restricted to those Portfolios, and then pass the section's changed rows and explicit delete keys. Display the effective total separately from the editable grid. Show “Unsaved changes” when either draft collection is nonempty. Show adjustments controls which saved rows are visible for editing; it must not disable saved adjustments in the effective-to-send total.

8. Complete Job C02 before enabling Save. Replace the `include_existing`/`replace_portfolios` branches in `save_adjustments` with the per-key `apply_changes` call described there. Keep all current snapshot, date, mapping and scope validation before the call. Only clear the draft and reload the section after persistence succeeds. On error preserve the draft and show “Not saved: …”.

9. In `s05_sendcallbacks.py::send_rows`, remove `rows = collapse_pl_send_rows(rows, mapping, governance)` over the editable grid and the subsequent direct send of those rows. Keep the existing date/revision/filter/scope guards. Reject sending while the selected section contains unsaved edits or delete keys, with “Save or discard these changes before sending.” Reload the saved effective result using `_effective_rows(..., include_adjustments=True, ...)`, filter it to the exact selected scope, then collapse that already-effective result only to validate its send grain. Use that frame for both the displayed send preview and the payload. `send_all` must also reject any dirty SOG/Portfolio drafts relevant to its filtered book, rather than silently sending a different result. Add `State("pl-send-sog-drafts-store", "data")` and `State("pl-send-portfolio-drafts-store", "data")` to `send_all`; add the corresponding single section store to `send_sog`/`send_portfolio` and forward its validated draft entry into `send_rows`. Update function parameters in decorator order. Check dirty state only on drafts matching the current date, revision, filter and allowed-Portfolio scope; mark stale drafts visibly rather than applying them to another book.

10. After completing C02, run this notebook cell. It uses in-memory amounts and no sender or real adjustment directory:

    ```python
    import pandas as pd
    from cube.domain.s08_pnl import PL_SEND_COLUMNS, empty_pl_send_frame
    from cube.pages.pnl.s02_editor import replacement_preview

    mapping_check = pd.DataFrame(
        [["IR", "Delta", "IRPL"]],
        columns=["Risk Type", "Risk Greek", "ConcertoField"],
    )
    governance_check = pd.DataFrame(
        [["CHECK_BOOK", "CHECK_SOG"]], columns=["Portfolio", "SignoffGroup"],
    )
    base_check = pd.DataFrame(
        [["2026-09-04", "IR", "Delta", "CHECK_BOOK", "CHECK_SOG", "IRPL", 100.0, False]],
        columns=PL_SEND_COLUMNS,
    )
    replacement_check = base_check.copy()
    replacement_check["PL"] = 10.0
    replacement_check["Adjustment"] = True
    result_check = replacement_preview(
        base_check, empty_pl_send_frame(), replacement_check,
        mapping_check, governance_check,
    )
    assert result_check["PL"].tolist() == [10.0]
    try:
        replacement_preview(
            base_check, empty_pl_send_frame(),
            pd.concat([replacement_check, replacement_check], ignore_index=True),
            mapping_check, governance_check,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Duplicate replacement keys were accepted")
    print("Replacement arithmetic and duplicate-key checks passed")
    ```

    In the app, use a demonstration sender that only displays its payload and repeat these actions. Do not send real messages merely to check the editor:

    | Input/action | Required result |
    |---|---|
    | Base 100, saved set empty, entered replacement 10 | Preview 10; Save then scoped Send payload 10; Send filtered book 10 |
    | Two draft replacement rows for the same key | Validation error; nothing saved or sent |
    | Existing FX replacement 105; edit IR to 210 with Show adjustments off | Saved FX remains 105 and IR becomes 210 |
    | Clear the IR replacement explicitly | IR returns to its calculated base; FX remains saved |
    | Hide adjustments or narrow filters without editing | No saved row is deleted |
    | Draft 10 has not been saved | Both send routes report that the draft must be saved/discarded |

11. Run `check_syntax(['cube/domain/s08_pnl.py', 'cube/pages/pnl/s02_editor.py', 'cube/pages/pnl/s04_sender.py', 'cube/pages/pnl/s05_sendcallbacks.py'])`. Open both editors in the running app and repeat the 100-to-10 example using a preview-only receiver configuration. Do not remove the date, filter, revision or Portfolio guards to make a check pass.

<a id="job-c02"></a>
## Job C02 — Prevent lost or concurrent adjustment saves

**Result:** changing one field preserves the other fields, and a stale editor cannot overwrite another user's save against the same Risk revision.

**KEEP:** the validated CSV column contract, collision-resistant Portfolio filenames and existing temporary-file/rollback writer. **ADD:** a content version and one lock covering read → check version → merge → write. The existing Risk `Base Revision` is still checked; it is not an adjustment-store version.

The locking code below is for a Linux JupyterHub host and cooperating processes on a filesystem supporting advisory locks. Run the two-process acceptance check before using the CSV writer concurrently. If the shared storage does not honor the lock, use one writer until the transactional-store job is complete. Atomic replacement of individual CSV files does not make a multi-file save crash-atomic; the later transactional-store job addresses that additional requirement.

1. Back up the files:

   ```python
   backup_job("C02", [
       "cube/services/s03_adjustments.py", "cube/pages/pnl/s02_editor.py",
       "cube/pages/pnl/s05_sendcallbacks.py",
   ])
   ```

2. In `cube/services/s03_adjustments.py`, add `from contextlib import contextmanager` and `from threading import local`. Keep `RLock`, `hashlib`, `os` and the current validation imports. Add this module-level locking helper before `LocalCsvAdjustmentRepository`:

   ```python
   _DIRECTORY_LOCKS = {}
   _DIRECTORY_LOCKS_GUARD = RLock()
   _HELD_DIRECTORY_LOCKS = local()

   @contextmanager
   def _locked_adjustment_date(directory, normalized_date):
       import fcntl
       root = Path(directory).expanduser().resolve()
       date_directory = root / normalized_date
       date_directory.mkdir(parents=True, exist_ok=True)
       lock_path = date_directory / ".adjustments.lock"
       lock_key = str(lock_path)
       with _DIRECTORY_LOCKS_GUARD:
           thread_lock = _DIRECTORY_LOCKS.setdefault(lock_key, RLock())
       with thread_lock:
           held = getattr(_HELD_DIRECTORY_LOCKS, "keys", None)
           if held is None:
               held = _HELD_DIRECTORY_LOCKS.keys = set()
           if lock_key in held:
               yield
               return
           with lock_path.open("a+b") as handle:
               fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
               held.add(lock_key)
               try:
                   yield
               finally:
                   held.remove(lock_key)
                   fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

   def adjustment_version(frame):
       canonical = frame.reindex(columns=list(PERSISTED_ADJUSTMENT_COLUMNS))
       canonical = canonical.sort_values(list(ADJUSTMENT_KEY), kind="stable")
       payload = canonical.to_csv(
           index=False, lineterminator="\n", float_format="%.17g",
       ).encode("utf-8")
       return hashlib.sha256(payload).hexdigest()
   ```

3. Rename the existing `LocalCsvAdjustmentRepository.save` method to `_replace_portfolios_unlocked`. Do not change its parameters or writer body. The method's name means callers must already hold the date lock. Keep its existing `self._lock` as an internal guard. Add these public methods immediately after that writer and replace the old public `load` method with the one below:

   ```python
   def load_versioned(self, market_date):
       day = normalize_market_date(market_date)
       with _locked_adjustment_date(self.directory, day), self._lock:
           frame = self._load_unlocked(day)
           return frame, adjustment_version(frame)

   def load(self, market_date):
       return self.load_versioned(market_date)[0]

   def save(self, market_date, rows, *, base_revision, saved_at=None,
            replace_portfolios=None):
       """Compatibility writer for controlled imports, not editor saves."""
       day = normalize_market_date(market_date)
       with _locked_adjustment_date(self.directory, day):
           return self._replace_portfolios_unlocked(
               day, rows, base_revision=base_revision, saved_at=saved_at,
               replace_portfolios=replace_portfolios,
           )

   def apply_changes(self, market_date, rows, *, base_revision,
                     expected_version, delete_keys=()):
       day = normalize_market_date(market_date)
       incoming = normalize_pl_send_rows(rows, label="edited replacements")
       if incoming.duplicated(list(ADJUSTMENT_KEY)).any():
           raise AdjustmentPersistenceError("Replacement keys must be unique")
       if not incoming.empty and (
           incoming[ADJUSTMENT_KEY[0]].ne(day).any()
           or not incoming[ADJUSTMENT].eq(True).all()
       ):
           raise AdjustmentPersistenceError("Replacement date/flag is invalid")
       deletes = set()
       for key in delete_keys:
           if (not isinstance(key, (tuple, list)) or len(key) != 3
                   or any(not isinstance(value, str) or not value.strip() for value in key)):
               raise AdjustmentPersistenceError("Clear requires a complete adjustment key")
           candidate = tuple(value.strip() for value in key)
           if normalize_market_date(candidate[0]) != day:
               raise AdjustmentPersistenceError("Clear key has another Market Date")
           deletes.add((day, candidate[1], candidate[2]))
       keys = set(incoming[list(ADJUSTMENT_KEY)].itertuples(index=False, name=None))
       if keys & deletes:
           raise AdjustmentPersistenceError("The same key is edited and cleared")
       with _locked_adjustment_date(self.directory, day), self._lock:
           existing = self._load_unlocked(day)
           if adjustment_version(existing) != str(expected_version):
               raise AdjustmentPersistenceError(
                   "Adjustments changed since this editor loaded; reload before saving"
               )
           if not keys and not deletes:
               return adjustment_version(existing)
           existing_keys = existing[list(ADJUSTMENT_KEY)].apply(tuple, axis=1)
           if deletes - set(existing_keys):
               raise AdjustmentPersistenceError("A cleared saved replacement no longer exists")
           touched = {key[1] for key in keys | deletes}
           keep = existing.loc[
               existing[PORTFOLIO].isin(touched)
               & ~existing_keys.isin(keys | deletes), list(PL_SEND_COLUMNS)
           ]
           complete_touched = pd.concat([keep, incoming], ignore_index=True)
           self._replace_portfolios_unlocked(
               day, complete_touched, base_revision=base_revision,
               replace_portfolios=touched,
           )
           return adjustment_version(self._load_unlocked(day))
   ```

4. Keep the writer's validation of prior `Base Revision`. The new version check occurs before any temporary or destination file is modified. When complete touched-Portfolio files are replaced, unchanged keys retain their financial values but the current writer regenerates their save metadata; do not claim this is a per-edit audit trail. The later audit job records actual changed keys.

5. In `s02_editor.py::_merge_and_persist_adjustments`, replace the call to `repository.save` with `repository.apply_changes`. Replace the `replace_portfolios` keyword argument with required `expected_version` and optional `delete_keys=()`. Return the new version string. Do not perform a separate unlocked `load` followed by `save` in this helper.

6. Add required `adjustment_version: str` to `_effective_store` and put it in the returned dictionary under `"adjustment_version"`. In `s02_editor.py::_effective_rows`, add keyword `saved_adjustments: pd.DataFrame | None = None`. When `include_adjustments=True`, use the supplied frame if it is not `None`; otherwise retain the existing repository-load path for callers not yet migrated. Never check the truth value of a DataFrame. In `s05_sendcallbacks.py::refresh_effective_query`, load the current date's version once with `load_versioned` when a section opens, reloads, or Save succeeds. Store that token in that section's query dictionary under `"adjustment_version"`. Do not update the baseline token on every cell edit; doing so would allow a stale draft to pass the conflict check.

7. In `effective_query_rows`, add `section_state["adjustment_version"]` to `cache_key` in addition to the Risk revision. Resolve the saved rows and token in the same `load_versioned` call, compare that token to the section baseline before using a cached result, and pass the rows as `saved_adjustments=loaded_rows` into `_effective_rows`. Do not load the version and rows separately. If that version differs from the baseline token during an edit, keep the draft, mark it stale and require Reload. Keep the function's existing four-value return. In `materialized_editor_store`, pass `adjustment_version=str(section_state["adjustment_version"])` to `_effective_store`; this is the token just checked against the rows, not a newly fetched later version.

8. In `save_adjustments`, after governing the edited rows and explicit delete keys, call `_merge_and_persist_adjustments(..., expected_version=store["adjustment_version"], delete_keys=...)`. Check every delete key's Portfolio is in `allowed_portfolios` and in the selected SOG/Portfolio before persistence. Keep the existing five callback outputs and return shapes. Increment the existing browser adjustment-revision stores only after a successful write; they remain UI refresh signals, not conflict tokens.

9. In `send_rows`, compare the current saved version to the preview's token and refuse stale previews. Pass that same call's loaded rows to `_effective_rows(saved_adjustments=loaded_rows, include_adjustments=True, ...)`. `send_all` must likewise build one immutable effective payload from one `load_versioned` result, record the version used, and pass copies of that same payload to its two existing sender functions. It must not rebuild the second destination's payload after the first destination returns. Release the storage lock before calling an external sender; the immutable payload/version identifies what was sent even if another adjustment is saved meanwhile.

10. Run this complete notebook check against a disposable directory. It preserves existing financial files by never opening the configured adjustment path:

    ```python
    import tempfile
    import pandas as pd
    from cube.domain.s08_pnl import PL_SEND_COLUMNS, empty_pl_send_frame
    from cube.services.s03_adjustments import (
        LocalCsvAdjustmentRepository, AdjustmentPersistenceError,
    )

    def check_adjustment_row(kind, field, value):
        return pd.DataFrame(
            [["2026-09-04", kind, "Delta", "CHECK_BOOK", "CHECK_SOG", field, value, True]],
            columns=PL_SEND_COLUMNS,
        )

    with tempfile.TemporaryDirectory(prefix="adjustment-check-") as check_directory:
        check_repository = LocalCsvAdjustmentRepository(check_directory)
        check_repository.save(
            "2026-09-04", check_adjustment_row("FX", "FXPL", 105.0), base_revision=7,
        )
        _, version_a = check_repository.load_versioned("2026-09-04")
        _, version_b = check_repository.load_versioned("2026-09-04")
        assert version_a == version_b
        newer_version = check_repository.apply_changes(
            "2026-09-04", check_adjustment_row("IR", "IRPL", 210.0),
            base_revision=7, expected_version=version_a,
        )
        values = check_repository.load("2026-09-04").set_index("ConcertoField")["PL"].to_dict()
        assert values == {"FXPL": 105.0, "IRPL": 210.0}
        try:
            check_repository.apply_changes(
                "2026-09-04", check_adjustment_row("FX", "FXPL", 999.0),
                base_revision=7, expected_version=version_b,
            )
        except AdjustmentPersistenceError:
            pass
        else:
            raise AssertionError("Stale adjustment save was accepted")
        check_repository.apply_changes(
            "2026-09-04", empty_pl_send_frame(), base_revision=7,
            expected_version=newer_version,
            delete_keys=[("2026-09-04", "CHECK_BOOK", "IRPL")],
        )
        values = check_repository.load("2026-09-04").set_index("ConcertoField")["PL"].to_dict()
        assert values == {"FXPL": 105.0}
    print("Merge, stale-version and explicit-clear checks passed")
    ```

    In the app, attempt to clear a key outside the selected Portfolio/SOG. The callback must reject it and preserve the draft.

11. Run this separate two-process notebook check on the JupyterHub host. It proves the file lock covers separate Python processes. Each child waits at most ten seconds, and both use the same disposable directory:

    ```python
    import subprocess
    import tempfile
    import time
    from pathlib import Path

    child_code = r'''
    import sys, time
    from pathlib import Path
    import pandas as pd
    sys.path.insert(0, sys.argv[1])
    from cube.domain.s08_pnl import PL_SEND_COLUMNS
    from cube.services.s03_adjustments import LocalCsvAdjustmentRepository, AdjustmentPersistenceError
    work = Path(sys.argv[2])
    identifier = sys.argv[3]
    repository = LocalCsvAdjustmentRepository(work / "values")
    _, version = repository.load_versioned("2026-09-04")
    (work / (identifier + ".ready")).write_text(version, encoding="utf-8")
    deadline = time.monotonic() + 10
    while not (work / "start").exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Concurrent check did not start")
        time.sleep(0.02)
    rows = pd.DataFrame(
        [["2026-09-04", "IR", "Delta", "CHECK_BOOK", "CHECK_SOG", "IRPL", float(identifier), True]],
        columns=PL_SEND_COLUMNS,
    )
    try:
        repository.apply_changes("2026-09-04", rows, base_revision=7, expected_version=version)
        print("SAVED")
    except AdjustmentPersistenceError as error:
        if "changed since" not in str(error):
            raise
        print("STALE")
    '''
    import textwrap
    child_code = textwrap.dedent(child_code)
    with tempfile.TemporaryDirectory(prefix="adjustment-lock-check-") as directory:
        processes = [
            subprocess.Popen(
                [str(PYTHON), "-c", child_code, str(APP_ROOT), directory, identifier],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            for identifier in ("1", "2")
        ]
        try:
            work = Path(directory)
            deadline = time.monotonic() + 10
            while not all((work / (identifier + ".ready")).exists() for identifier in ("1", "2")):
                if time.monotonic() > deadline or any(p.poll() is not None for p in processes):
                    raise RuntimeError("A concurrency-check child did not initialize")
                time.sleep(0.02)
            assert (work / "1.ready").read_text() == (work / "2.ready").read_text()
            (work / "start").touch()
            outcomes = []
            for process in processes:
                output, error = process.communicate(timeout=15)
                assert process.returncode == 0, error
                outcomes.append(output.strip())
            assert sorted(outcomes) == ["SAVED", "STALE"], outcomes
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
    print("Two-process adjustment-lock check passed")
    ```

12. Run `check_syntax(['cube/services/s03_adjustments.py', 'cube/pages/pnl/s02_editor.py', 'cube/pages/pnl/s05_sendcallbacks.py'])`. The transactional audit job may later replace the storage internals, but it must preserve `load_versioned` and `apply_changes` semantics. Do not maintain a CSV writer and a database writer as simultaneous authorities.

<a id="job-c03"></a>
## Job C03 — Keep Stock history on the exact clicked population

**Result:** clicking a Stock value of 100 loads the identities contributing to that 100. It cannot silently broaden to a CRDS/Activity population worth 1,000.

**KEEP:** the page-owned pivot, applied saved-view filters, original position identity (`CRDS`, `CPTY`, `Portfolio`, `Instrument`, `Currency`) and exact dated-history validation. **REMOVE:** resolving a click from only CRDS + Activity against unfiltered current Stock. Those two fields are display/search aids, not sufficient position identity.

1. Back up the files:

   ```python
   backup_job("C03", [
       "cube/pages/stock/s01_data.py", "cube/pages/stock/s03_view.py",
       "cube/pages/stock/s04_callbacks.py", "cube/pages/stock/s05_pivot.py",
       "cube/pages/stock/s02_history.py",
   ])
   ```

2. In `s01_data.py::stock_display_rows`, add keyword `projection="current"`. Validate it is `"current"` or `"changes"`. Replace the unconditional `CURRENT_MARKET_VALUE_COLUMN.notna()` selection with the following:

   ```python
   if projection not in {"current", "changes"}:
       raise ValueError("Unknown Stock projection")
   selected = (
       filtered.loc[filtered[CURRENT_MARKET_VALUE_COLUMN].notna()].copy()
       if projection == "current" else filtered.copy()
   )
   ```

   Use `selected` where the function currently uses `current`. Keep `Stock` unavailable for prior-only exits; show their negative `dStock`. Do not fill every missing numeric value with zero. Import `STOCK_CHANGE_COLUMN` from `cube.domain.s09_stock`, include it in the selected projection, rename it to `Change`, and add `"Change"` to `STOCK_DISPLAY_COLUMNS`. The `changes` projection contains the complete outer comparison, including unchanged positions; an “Only changed positions” option, if added later, must leave the complete change total calculated before that presentation filter.

3. Complete Job B04 before this step. In `s03_view.py`, add a Current positions / Changes segmented control immediately before the pivot controls, with `id="stock-projection"`, values `current` and `changes`, default `current`. Reuse the page's existing button appearance. In `s04_callbacks.py`, extend the new shared `selected_display(page_data, committed_filter_state)` helper to `selected_display(page_data, committed_filter_state, projection="current")`, forwarding `projection` to `stock_display_rows`. Add `stock-projection.value` as an input to the new seven-output `render_current_stock` and server-paged detail callback, with parameters in the same decorator order. Both call this shared helper. Add projection changes to the detail-page reset inputs. Keep all seven pivot callback return values in their current order; do not restore its removed full-detail output. Counts and captions must identify which projection is shown.

4. In `s05_pivot.py::build_stock_pivot`, keep the existing `path` token in each row ID. Remove the requirement that a row have exactly one CRDS/Activity pair to be history-selectable. Set a leaf's `kind` to `"history"`; retain `"branch"` for expandable rows. A click on a branch metric cell is also a valid population selection; a click on its Hierarchy cell still expands/collapses. Do not serialize whole position frames into every row ID.

5. Add these helpers in `s01_data.py` immediately before `stock_history_identities`. They resolve a server-validated path against an already filtered projection and produce a compact verification token. Add `import hashlib`, `import json`, and `STOCK_IDENTITY_COLUMNS` to imports if absent.

   ```python
   def selected_stock_identities(display, row_fields, path, *,
                                 column_field="", split_value=None):
       if not path or len(path) > len(row_fields):
           raise ValueError("Stock selection path does not match its row layout")
       selected = display
       for field, value in zip(row_fields, path, strict=False):
           if field not in selected:
               raise ValueError("Stock selection field is unavailable")
           labels = selected[field].fillna("Unmapped").astype(str)
           selected = selected.loc[labels.eq(str(value))]
       if column_field and split_value is not None:
           if column_field not in selected:
               raise ValueError("Stock column split is unavailable")
           selected = selected.loc[selected[column_field].astype(str).eq(str(split_value))]
       identities = selected.loc[:, list(STOCK_IDENTITY_COLUMNS)].drop_duplicates()
       if identities.empty:
           raise ValueError("This Stock population is no longer available; reload the table")
       return identities.astype(str).to_dict("records")

   def stock_identity_fingerprint(identities):
       keys = sorted(
           tuple(str(identity[column]) for column in STOCK_IDENTITY_COLUMNS)
           for identity in identities
       )
       payload = json.dumps(keys, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
       return hashlib.sha256(payload).hexdigest()
   ```

6. In `s04_callbacks.py::select_stock_row`, keep its three existing outputs and make this callback the sole writer for both clicked and manual history requests. Replace its decorator with the exact dependencies below, then change the function parameter order to match. Its name may remain `select_stock_row`:

   ```text
   @app.callback(
       Output("stock-history-crds", "value"),
       Output("stock-history-activity", "value"),
       Output("stock-history-autoload", "data"),
       Input("stock-current-table", "active_cell"),
       Input("stock-history-load-button", "n_clicks"),
       State("stock-loaded-snapshot", "data"),
       State(STOCK_SAVED_VIEW_CONTROLS.committed_state_id, "data"),
       State("stock-pivot-rows", "value"),
       State("stock-pivot-column", "value"),
       State("stock-pivot-values", "value"),
       State("stock-projection", "value"),
       State("stock-history-crds", "value"),
       State("stock-history-activity", "value"),
       prevent_initial_call=True,
   )
   ```

   The function arguments, in order, are `active_cell, load_clicks, loaded_snapshot, committed_filter_state, pivot_rows, pivot_column, pivot_values, projection, manual_crds, manual_activity`. Wait for committed filters to initialize; do not create a history payload from missing/invalid state. When the pivot cell triggered, read its row ID using `stock_pivot_row_payload`, decode with `stock_pivot_path_from_token`, normalize pivot controls with `normalize_stock_pivot_controls`, and resolve the exact filtered display through `selected_display(page_data, committed_filter_state, projection)`. Call `selected_stock_identities` on that frame. A branch's Hierarchy cell remains an expand action and returns `PreventUpdate` here; its metric cells select history. When the manual Load button triggered, follow step 10 instead. Do not copy filter resolution into another helper.

7. Resolve a clicked metric column using the generated pivot column metadata, not by splitting a string on `":"`: Portfolio/Instrument labels can contain punctuation. Add an explicit dictionary of column ID → `{metric, column_field, split_value}` to `StockPivotResult`, populated where `metric_columns` is constructed. Rebuild that small metadata on the server for the committed scope. A Hierarchy click selects the whole leaf; a Currency/metric cell selects only that currency. Reject a column ID absent from the generated dictionary, except for the explicitly supported Hierarchy column.

8. Replace the `stock-history-autoload` payload with this contract:

   ```python
   {
       "mode": "clicked",
       "snapshot": dict(loaded_snapshot),
       "row_fields": list(normalized_rows),
       "path": list(path),
       "column_field": normalized_column,
       "split_value": selected_split,
       "projection": projection,
       "filter_state": dict(committed_filter_state),
       "identity_count": len(exact_identities),
       "identity_fingerprint": stock_identity_fingerprint(exact_identities),
       "label": " › ".join(path),
       "metric": selected_metric,
   }
   ```

   Keep `exact_identities` on the server for that callback only; do not put its entire list or any position frame into this browser store. The browser payload is a request, not trusted authority. Before each history read, compare its snapshot token to the loaded snapshot, reapply its validated committed filters/path/split on the server, recompute the exact identities, and verify their count/fingerprint. This token checks consistency; it is not an authorization mechanism. The server must still validate the request scope. A future archive-picker mode may contain one explicitly selected archived identity because it cannot be resolved from the current snapshot; that single-identity case is separate from a current-population click.

9. In `load_stock_history`, keep `stock-history-autoload.data` as the selection owner. Remove its direct `stock-history-load-button` input and all reads of the draft CRDS/Activity controls. The commit callback above owns those. Otherwise a button click can read old store data before its new manual scope is committed. Use the following ordered Inputs: `stock-history-autoload.data`, `clear-cache-complete-store.data`, `stock-history-period.data`, `stock-history-date-range.start_date`, `stock-history-date-range.end_date`, `stock-loaded-snapshot.data`, committed Stock filter state, `stock-pivot-rows.value`, `stock-pivot-column.value`, `stock-pivot-values.value`, and `stock-projection.value`. The function arguments become `selection, cache_generation, period, custom_start, custom_end, loaded_snapshot, committed_filter_state, pivot_rows, pivot_column, pivot_values, projection`. Keep its two figure/status outputs and remove the old `load_clicks`, `crds` and `activity` arguments/trigger branches. The metric input added in the later history job is appended to this contract.

   On a committed selection, period or custom-date event, resolve the stored scope and load it. On a changed loaded snapshot/filter/pivot/projection, clear or mark an incompatible result stale and request reselection; do not read under a broadened scope. On Clear Cache, clear source caches and show the existing explicit empty message. Do not call the old unfiltered `stock_history_identities(page_data.mapped_stock, crds=..., activity=...)` for clicked mode. Use the server-resolved and fingerprint-checked identities from step 8. Keep `normalize_stock_history_frame` for each returned identity, or the later batched exact-identity validator. For multiple currencies, draw separate labelled panels or require one Currency before a monetary total; do not pass a mixed-currency frame into the single-total history chart.

10. Keep manual CRDS/Activity search as an explicit mode. Label its Load action “Load matching CRDS / Activity”. In the commit callback's manual-button branch, require positive clicks and nonblank manual CRDS/Activity. Resolve `selected_display` using the same committed filters/projection, filter that result by exact CRDS and Activity, and select its distinct `STOCK_IDENTITY_COLUMNS`. Reject an empty match. Build `mode="manual"` with `crds`, `activity`, the same snapshot/filter/projection fields, identity count/fingerprint, metric and a caption naming the selection. A manual request does not use the pivot path/column split, so omit those fields. Return the two selected control values and this new store payload. The loader recomputes this exact filtered manual population and verifies count/fingerprint just as for clicked mode. Show its position count and applied filters. Do not switch a clicked selection to manual mode merely because its CRDS/Activity controls were prefilled; only pressing the manual button commits that change.

11. Check these small cases in the notebook or through the browser using disposable demonstration inputs:

    - Same CRDS/Activity, Portfolio A=100 and Portfolio B=900; apply Portfolio A filter, click its value, change MTD to YTD, press Load again. Every reader request must still contain only A's full five-field identities.
    - Same row path with USD=100 and EUR=200; clicking USD requests only USD; clicking the leaf label requests both identities but does not combine unlike-currency market values into one total.
    - Current-only change +110 and a prior-only exit −500: Changes sums `dStock` to −390; Current positions retains its current-position meaning and labels its subtotal accordingly.
    - Change the Risk/Stock revision after a click: the history callback requests reselection rather than silently reusing an old scope.

12. Run `check_syntax(['cube/pages/stock/s01_data.py', 'cube/pages/stock/s03_view.py', 'cube/pages/stock/s04_callbacks.py', 'cube/pages/stock/s05_pivot.py', 'cube/pages/stock/s02_history.py'])`. Keep this scope-resolution helper when adding Stock columns or changing detail pagination; those later jobs must not restore the old CRDS/Activity-only click path.

<a id="job-c04"></a>
## Job C04 — Make Stock column coverage and source dates explicit

1. Back up the files:

   ```python
   backup_job("C04", [
       "cube/pages/stock/s05_pivot.py", "cube/pages/stock/s03_view.py",
       "cube/pages/stock/s04_callbacks.py", "cube/adapters/s08_stock.py",
   ])
   ```

2. In `build_stock_pivot`, replace `sorted(... )[:STOCK_PIVOT_SPLIT_LIMIT]` with two variables: `all_split_values = sorted(...)` and a page slice. Keep 8 as a page size, rename the constant to `STOCK_PIVOT_SPLIT_PAGE_SIZE`, and add keyword `column_page=0`. Validate nonboolean integer page input, clamp it to the available pages, then compute `start = page * 8` and `split_values = all_split_values[start:start + 8]`.

3. Extend `StockPivotResult` with `column_page`, `column_pages` and `total_split_values`. Update all constructors including the empty-frame return. Add Previous columns / Next columns buttons and a caption “Columns 1–8 of 9” in `s03_view.py`; store the selected page in `stock-pivot-column-page`. One callback owns that store. Reset it to zero on committed filter, projection or column-field changes. Feed it into `render_current_stock`, and update the controls from the returned metadata. Page 2 must expose the ninth column. Do not implement an “Other” currency total.

4. Keep complete selected-position counts independent of the page slice. Where Stock units are local currency, suppress an unsplit monetary total covering more than one currency and display “Choose Currency split to compare these values.” Each currency total still includes its complete filtered population. If a connector supplies an explicitly converted reporting-currency amount later, give it a separate named measure and unit; do not assume the existing Market Value is converted.

5. Locate creation of `stock-date-store` in `s03_view.py`. Add `"mode": "default"` to the default date state. When the user enters dates, switch it to `"mode": "custom"`. In `s04_callbacks.py::load_current_stock`, on `refresh-commit-revision`, resolve the current snapshot's market date and call `default_stock_dates` only when mode is default. Preserve explicit custom dates. Use the resolved dates to load and construct `stock-loaded-snapshot`; never report a new revision alongside old default dates without making that distinction visible.

6. Add a typed `StockDateUnavailable` exception in `cube/adapters/s08_stock.py`, carrying `requested_date` and optional `latest_available_date`. Raise it only for a genuinely absent dated leaf. A malformed manifest, corrupt file, incompatible schema or permission failure must keep its error type; it must not masquerade as an absent day.

7. At the source boundary, determine latest available Stock date from completed archive metadata or a connector-supplied `available_dates()` method. Do not search arbitrary directory names and choose a partial date. In the callback catch only `StockDateUnavailable` to show “Stock requested for YYYY-MM-DD is unavailable. Latest available: YYYY-MM-DD.” Log detailed paths server-side, not in the user caption.

8. Add an initially hidden “Load latest available” button and store containing the offered date. Give it one callback that validates the offered date still exists, resolves an available earlier comparison date, writes explicit date state, and invokes the normal load trigger. It must not load older data automatically after an error. If no earlier date exists, explain that a comparison cannot yet be formed instead of inventing prior zero positions.

9. Keep the last successful result on failure, with its own loaded date and “New request failed; showing previous result” caption. Its existing snapshot token must remain unchanged. Changing date controls alone must not relabel an old table.

10. Check nine currencies across two pages, an all-empty selection, filter changes while on page 2, default-date rollover, retained custom dates, an absent day, and a corrupt existing day. Verify only the absent-day case offers Load latest. Run `check_syntax(['cube/pages/stock/s05_pivot.py', 'cube/pages/stock/s03_view.py', 'cube/pages/stock/s04_callbacks.py', 'cube/adapters/s08_stock.py'])`.

<a id="job-c05"></a>
## Job C05 — Match demo identities across current and historical reads

**Result:** a current `TEMP_REPLACE_ME_…` demo identity matches its exact archived `FAKE_REPLACE_ME_…` equivalent. Genuine identifiers, exact keys, dates and archive files stay intact.

1. Back up the files. Include the new helper path as absent in the manifest so rollback can remove it if this job creates it:

   ```python
   backup_job("C05", [
       "cube/adapters/s08_stock.py", "cube/pages/stock/s02_history.py",
       "cube/history/s07_sql.py", "cube/services/s05_sources.py",
       "cube/pages/pnl/s06_validation.py", "cube/domain/s14_identityaliases.py",
   ])
   ```

2. Add `cube/domain/s14_identityaliases.py` with the following complete implementation. It changes only the exact demo prefix followed by a known fixture separator (`_` or ` - `), or the entire prefix by itself. A real identifier containing that text in the middle is not rewritten.

   ```python
   """Explicit demo-name compatibility at read/query boundaries."""

   LEGACY_DEMO_PREFIX = "FAKE_REPLACE_ME"
   CURRENT_DEMO_PREFIX = "TEMP_REPLACE_ME"

   def canonical_demo_identity(value):
       if not isinstance(value, str):
           return value
       if value == LEGACY_DEMO_PREFIX or value.startswith((LEGACY_DEMO_PREFIX + "_", LEGACY_DEMO_PREFIX + " - ")):
           return CURRENT_DEMO_PREFIX + value[len(LEGACY_DEMO_PREFIX):]
       return value

   def legacy_demo_identity(value):
       if not isinstance(value, str):
           return value
       if value == CURRENT_DEMO_PREFIX or value.startswith((CURRENT_DEMO_PREFIX + "_", CURRENT_DEMO_PREFIX + " - ")):
           return LEGACY_DEMO_PREFIX + value[len(CURRENT_DEMO_PREFIX):]
       return value

   def canonical_demo_sql(expression):
       # expression is built from source-owned column names, never user input.
       prefix_length = len(LEGACY_DEMO_PREFIX)
       return (
           f"CASE WHEN {expression} = '{LEGACY_DEMO_PREFIX}' "
           f"OR starts_with({expression}, '{LEGACY_DEMO_PREFIX}_') "
           f"OR starts_with({expression}, '{LEGACY_DEMO_PREFIX} - ') "
           f"THEN '{CURRENT_DEMO_PREFIX}' || substr({expression}, {prefix_length + 1}) "
           f"ELSE {expression} END"
       )
   ```

3. In `s08_stock.py`, replace the `.replace(_LEGACY_FIXTURE_NOTICE, TEMP_NOTICE)` lambda inside `_normalize_legacy_identities` with `canonical_demo_identity`. In `_legacy_archive_identity`, replace the reverse `.replace` call with `legacy_demo_identity`. Keep raw files untouched. Preserve raw identity in source provenance/log context when comparing a canonical request with the raw row.

4. In `cube/services/s05_sources.py`, locate the existing current CSV legacy-notice normalization and use the same helper on its explicitly named textual identity columns. In `s06_validation.py`, replace the inline `.str.replace(_LEGACY_ARCHIVE_NOTICE, _TEMP_NOTICE, regex=False)` for identity dimensions with `.map(canonical_demo_identity)`. Do not apply this to dates, Risk Type/Greek, tenor order, numeric values or entire CSV text.

5. In `cube/pages/stock/s02_history.py::SQLStockHistoryRepository._current_connection`, keep `_stock_files` as the immutable raw relation. Replace `s.* EXCLUDE(filename)` in the `stock_history` view with an explicit projection over `STOCK_COLUMNS`: for each text identity column use `canonical_demo_sql('s."' + column + '"') + ' AS "' + column + '"'`; for numeric columns use the direct quoted column. Keep the date/revision projection and filename-to-manifest join. Use only the source-owned `STOCK_COLUMNS` list to construct identifiers.

6. In `cube/history/s07_sql.py`, apply the same canonical projection to demo identity fields in every constructor of the `risk_history`, `colossus_history` and `stock_history` views: `_create_archive_views`, `_create_pl_archive_views`, and the query-only Risk view construction. Use the existing schema column lists to generate explicit projections; retain every numeric/status/tenor field unchanged. Do not canonicalize only the filter while querying raw archived text: both sides of matching must use the same identity representation. Canonicalize selected filter values in `_normalized_filters` as well.

   `SQLPLHistoryRepository.risk_summary` also queries `_risk_files` and `_colossus_files` directly. In its `projected` CTE, canonicalize the identity/dimension columns emitted by both the Predict and Colossus arms before the `filtered` CTE applies user selections. Keep the raw Portfolio joins inside that query consistent on both sides, and keep filename/date constraints untouched. Changing only the shared views would leave this summary path broken.

7. Preserve archive validators on raw data. After canonical projection, check the canonical business keys for collisions before grouping: if both a legacy and canonical row for the same date/key exist, fail with an explicit alias-collision message rather than summing them. For Stock use Stock Date + `STOCK_IDENTITY_COLUMNS`; for P&L retain its exact dated history/comparison keys. Do not put extra raw-provenance columns into the strict Stock history result schema; retain them only in a diagnostic projection or source context.

8. In `normalize_stock_history_frame`, canonicalize expected identity and the returned identity columns consistently before the existing exact-identity check. Keep date-window, duplicate-key, schema and numeric validation in place.

9. Run the identity assertions below, then use a disposable archive to check current demo Portfolio A finds only archived demo A; Portfolio B does not match A; a wrong requested date still fails; legacy/canonical duplicates raise a collision. Completed archive bytes and manifests must not be modified.

   ```python
   from cube.domain.s14_identityaliases import canonical_demo_identity, legacy_demo_identity
   assert canonical_demo_identity("FAKE_REPLACE_ME_BOOK_A") == "TEMP_REPLACE_ME_BOOK_A"
   assert canonical_demo_identity("FAKE_REPLACE_ME - Activity 1") == "TEMP_REPLACE_ME - Activity 1"
   assert canonical_demo_identity("REAL_FAKE_REPLACE_ME_A") == "REAL_FAKE_REPLACE_ME_A"
   assert canonical_demo_identity("FAKE_REPLACE_ME_BOOK_B") != "TEMP_REPLACE_ME_BOOK_A"
   assert legacy_demo_identity("TEMP_REPLACE_ME_BOOK_A") == "FAKE_REPLACE_ME_BOOK_A"
   print("Explicit demo alias checks passed")
   check_syntax([
       "cube/adapters/s08_stock.py", "cube/pages/stock/s02_history.py",
       "cube/history/s07_sql.py", "cube/services/s05_sources.py",
       "cube/pages/pnl/s06_validation.py", "cube/domain/s14_identityaliases.py",
   ])
   ```

<a id="job-c06"></a>
## Job C06 — Show complete and partial P&L reconciliation honestly

**KEEP:** the one-to-one comparison grain and the existing rule marking a leaf Predict unavailable when one of its required archived tenors is unavailable. **REMOVE:** treating the sum of the remaining available Predict leaves as a complete parent Predict result.

1. Back up the files:

   ```python
   backup_job("C06", ["cube/pages/pnl/s06_validation.py", "cube/history/s07_sql.py"])
   ```

2. Add this helper immediately before `_hierarchy_nodes`. `tolerance=0.01` is an absolute display/reconciliation tolerance in the P&L amount's unit; name it in the UI caption. It does not alter stored values.

   ```python
   def reconciliation_metrics(frame, *, tolerance=0.01):
       p = pd.to_numeric(frame["pl"], errors="coerce")
       c = pd.to_numeric(frame["colossus"], errors="coerce")
       paired = p.notna() & c.notna()
       complete = bool(len(frame)) and bool(paired.all())
       def total(values):
           return float(values.sum(min_count=1))
       matched_p = total(p.loc[paired])
       matched_c = total(c.loc[paired])
       missing_p = int(p.isna().sum())
       missing_c = int(c.isna().sum())
       if not len(frame):
           status = "No data"
       elif missing_p == len(frame) and missing_c == len(frame):
           status = "Missing both"
       elif complete:
           status = "Matched" if abs(matched_p - matched_c) <= tolerance else "Mismatch"
       elif missing_p and not missing_c:
           status = "Missing Predict" if missing_p == len(frame) else "Partial: missing Predict"
       elif missing_c and not missing_p:
           status = "Missing Colossus" if missing_c == len(frame) else "Partial: missing Colossus"
       else:
           status = "Partial: missing comparison values"
       return {
           "pl": total(p) if bool(len(frame)) and bool(p.notna().all()) else float("nan"),
           "colossus": total(c) if bool(len(frame)) and bool(c.notna().all()) else float("nan"),
           "difference": matched_p - matched_c if complete else float("nan"),
           "matched_predict": matched_p,
           "matched_colossus": matched_c,
           "matched_difference": matched_p - matched_c,
           "unmatched_predict": total(p.loc[p.notna() & c.isna()]),
           "unmatched_colossus": total(c.loc[c.notna() & p.isna()]),
           "matched_count": int(paired.sum()),
           "leaf_count": int(len(frame)),
           "missing_predict": missing_p,
           "missing_colossus": missing_c,
           "status": status,
       }
   ```

3. In `build_validate_pl_comparison`, keep `comparison status` for join provenance (`Matched`, Predict only, Colossus only, Colossus unmapped). Do not reuse it as a statement that numeric values match. Add a distinct `reconciliation status` after concatenating mapped/unmapped rows, using the helper on each leaf's Predict/Colossus pair. The helper's status follows availability and difference, not merge membership.

4. In `_hierarchy_nodes`, keep grouping by each `VALIDATE_PL_GROUPS` prefix, but replace blind `sum` of the two comparison measures with `reconciliation_metrics(group)`. Retain the existing Risk/dRisk `sum(min_count=1)` separately. Store the helper's numeric values, counts and string status in each node. Update type annotations from `dict[str, float]` to `dict[str, object]` where necessary. In `_validate_tree_table`, use the same helper on the full filtered comparison for the total row. Never build a total by summing only rendered child rows.

5. Extend displayed columns in this order: Risk, dRisk, Predict, Colossus, Difference, Status, Coverage. Difference means complete Predict minus complete Colossus and is blank when the selected comparison is incomplete. Coverage renders `matched_count / leaf_count`. Keep numeric cell copy values empty for unavailable amounts. Add a disclosure below the total with matched Predict, matched Colossus, matched difference, unmatched Predict and unmatched Colossus. These matched figures are useful but must be labelled “Matched population”; they are not full-book reconciliation.

6. In `_metric_cell`, add a title and formatting rule for `difference`. Render Status/Coverage as text cells, not through `float()` or numeric sign formatting. In `_node_sort_key`, for Underlying sort missing-coverage rows first, then complete mismatches by descending absolute Difference, then stable label. Preserve governed Risk Type ordering and deterministic tie-breaking.

7. Keep unmapped actual amounts in their separate section, and give that section equivalent availability/status columns. Do not distribute an unmapped Colossus amount across multiple Products or drop it to make the total reconcile.

8. Run this self-contained notebook check:

   ```python
   import pandas as pd
   from cube.pages.pnl.s06_validation import reconciliation_metrics
   frame = pd.DataFrame({"pl": [10.0, float("nan")], "colossus": [12.0, 12.0]})
   result = reconciliation_metrics(frame)
   assert pd.isna(result["pl"])
   assert result["colossus"] == 24.0
   assert pd.isna(result["difference"])
   assert result["matched_predict"] == 10.0
   assert result["matched_colossus"] == 12.0
   assert result["matched_difference"] == -2.0
   assert result["unmatched_colossus"] == 12.0
   assert result["matched_count"] == 1 and result["leaf_count"] == 2
   assert "missing Predict" in result["status"]
   ```

   Also check complete 10/12 → Difference −2 and Mismatch; 10/10 → Matched; all missing → Missing both with blank amounts; complete zero/zero → Matched with visible zeros. In the browser verify a parent with one incomplete leaf, not only complete hand-prepared inputs.

9. Run `check_syntax(['cube/pages/pnl/s06_validation.py'])`. Preserve this helper when installing pagination and numeric cache limits. Paging must not change these totals or their coverage.

10. Apply the same missing-value rule to the history query boundary in `cube/history/s07_sql.py`. In `_create_pl_history_view`'s `predict` CTE, replace `sum("{PL}") AS "{PL}"` with `CASE WHEN count("{PL}") = count(*) THEN sum("{PL}") ELSE NULL END AS "{PL}"` and remove its `HAVING count("{PL}") = count(*)`. In `SQLPLHistoryRepository.risk_summary`'s separate `predict` CTE, make the same replacement using `r."{PL}"` and remove that CTE's corresponding `HAVING`. Keep the incomplete leaf with a null value; the old HAVING removed it entirely before parent coverage could be checked. Do not remove other unrelated HAVING constraints.

11. In `SQLPLHistoryRepository.series`, replace its daily `sum(h."{PL}") AS "{PL}"` projection with `CASE WHEN count(h."{PL}") = count(*) THEN sum(h."{PL}") ELSE NULL END AS "{PL}"`. Retain its exact date/type/identity grouping, filters, parameters and row bound. This prevents one unavailable leaf being skipped within a daily sum.

12. In `risk_summary`'s final three amount expressions, replace each `sum("{PL}") FILTER (WHERE predicate)` with `CASE WHEN count(*) FILTER (WHERE predicate) = count("{PL}") FILTER (WHERE predicate) THEN sum("{PL}") FILTER (WHERE predicate) ELSE NULL END`. Repeat each existing predicate exactly, including its P&L Type restriction. Because the predicate's `?` placeholders now occur three times, replace only the final five date parameters after `*parameters` with this exact tail:

    ```python
    # These are the final parameters inside the existing query argument list.
    # Keep *risk_paths, latest_risk_path, *colossus_paths and *parameters before them.
    summary_date_parameters = [
        as_of_date, as_of_date, as_of_date,
        month_start, as_of_date, month_start, as_of_date, month_start, as_of_date,
        year_start, as_of_date, year_start, as_of_date, year_start, as_of_date,
    ]
    ```

    Define `summary_date_parameters` immediately before that query and expand `*summary_date_parameters` at the end of the existing argument list. Keep its output column order and seven-value row unpacking unchanged. Do not duplicate the non-date filters or file-path parameters.

13. Verify the SQL availability rule in an isolated in-memory connection, then check the app's summary with one incomplete Predict leaf. Neither the archived summary nor its daily history may show a partial amount as complete:

    ```python
    import duckdb
    with duckdb.connect(":memory:") as check_connection:
        check_connection.execute("CREATE TABLE amounts (portfolio VARCHAR, amount DOUBLE)")
        check_connection.executemany(
            "INSERT INTO amounts VALUES (?, ?)", [("A", 10.0), ("B", None)],
        )
        incomplete = check_connection.execute(
            "SELECT CASE WHEN count(amount) = count(*) THEN sum(amount) ELSE NULL END FROM amounts"
        ).fetchone()[0]
        assert incomplete is None
        check_connection.execute("UPDATE amounts SET amount = 12.0 WHERE portfolio = 'B'")
        complete = check_connection.execute(
            "SELECT CASE WHEN count(amount) = count(*) THEN sum(amount) ELSE NULL END FROM amounts"
        ).fetchone()[0]
        assert complete == 22.0
    print("SQL missing-value aggregation check passed")
    check_syntax(["cube/pages/pnl/s06_validation.py", "cube/history/s07_sql.py"])
    ```

<a id="job-c07"></a>
## Job C07 — Let every P&L reconciliation child remain reachable

Apply this after the temporary P&L construction-budget safeguard. This job replaces the hidden-HTML interaction with server-owned expansion and paging. Keep the safeguard until this complete interaction passes; do not merely remove the ten-child slice and construct the entire tree.

1. Back up the files:

   ```python
   backup_job("C07", [
       "cube/pages/pnl/s06_validation.py", "assets/s14_pnl.js",
   ])
   ```

2. In `build_validate_pl_section`, add `dcc.Store(id="pl-validate-navigation", data={"scope_key": None, "open": [], "pages": {}, "unmapped_page": 0})`, a labelled `dcc.Input(id="pl-validate-underlying-search", type="search", placeholder="Find Underlying", debounce=True)`, and a separately labelled `dcc.Input(id="pl-validate-unmapped-search", type="search", placeholder="Find unmapped Portfolio / Underlying", debounce=True)`. Use the existing `pl-validate-status` element for navigation notices. Put both inputs in the fixed section layout, outside the dynamically replaced table, so they always exist for callback registration. This store contains paths and page numbers, not DataFrames or prebuilt HTML.

3. Keep `_path_token` and `_path_from_token` as validators. Insert these helpers after them. A malformed path/page raises a controlled validation message and does not broaden the selection:

   ```python
   VALIDATE_PL_ROOT_TOKEN = "__root__"
   VALIDATE_PL_PAGE_SIZE = 25

   def validate_parent_path(token):
       if token == VALIDATE_PL_ROOT_TOKEN:
           return ()
       context = _path_from_token(token)
       if context is None:
           raise ValueError("Invalid reconciliation path")
       return tuple(context[column] for column in VALIDATE_PL_GROUPS if column in context)

   def validate_child_page(value, child_count, *, page_size=VALIDATE_PL_PAGE_SIZE):
       if isinstance(value, bool) or not isinstance(value, int):
           raise ValueError("Invalid reconciliation page")
       if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size < 1:
           raise ValueError("Invalid reconciliation page size")
       last = max((child_count - 1) // page_size, 0)
       return min(max(value, 0), last)
   ```

4. In `_tree_rows`, add `page_by_parent`, and the existing shared row-budget object as parameters. Obtain all numeric child nodes for this parent, determine the requested page and slice `children[start:end]`. Charge the global row budget before constructing each component. Build children only when `is_open` is true; remove recursion into closed branches and remove `hidden=not visible`. Parent totals still use all numeric children from Job C06.

5. Replace each expand button's browser-only `data-validate-path` action with a Dash ID dictionary `{"type": "pl-validate-toggle", "path": token}` and `n_clicks=0`. After a parent's visible child page, add Previous/Next buttons with IDs `{"type": "pl-validate-page", "path": parent_token, "page": target_page}` and caption “Children 26–50 of 81”. Omit both controls when there are zero or one pages to avoid duplicate page-zero IDs. Use `VALIDATE_PL_ROOT_TOKEN` for the empty parent and `_path_token(dict(zip(VALIDATE_PL_GROUPS, parent)))` otherwise. Do not allow arbitrary JSON to select fields outside `VALIDATE_PL_GROUPS`.

6. Replace `render_validate_pl` with one callback that owns exactly these four outputs, in order: `pl-validate-table.children`, `pl-validate-status.children`, `pl-validate-render-key.data`, `pl-validate-navigation.data`. Add `ALL` and `ctx` imports. Its ordered Inputs are: `pl-validate-date.value`, `Input(PL_SAVED_VIEW_CONTROLS.committed_state_id, "data")`, `pl-validate-summary.n_clicks`, `clear-cache-complete-store.data`, `{"type": "pl-validate-toggle", "path": ALL}.n_clicks`, `{"type": "pl-validate-page", "path": ALL, "page": ALL}.n_clicks`, `pl-validate-underlying-search.value`, `{"type": "pl-validate-unmapped-page", "page": ALL}.n_clicks`, and `pl-validate-unmapped-search.value`. Then add State for current render key and navigation store. Its function arguments, in that same order, are `market_date, committed_filter_state, summary_clicks, cache_generation, toggle_clicks, page_clicks, underlying_search, unmapped_page_clicks, unmapped_search, current_render_key, navigation_state`. Update every success/empty/error return to four outputs. Do not register a separate unmapped callback or another owner of these outputs.

7. At the start of this callback, calculate `scope_key` from date, committed filters, exclude flag, cache generation and normalized global Underlying search. If it differs from the store's scope, clear open paths/pages and set `unmapped_page=0`. Otherwise reduce only the triggered action: toggle one validated path, removing descendants when closed; or set one validated parent's page, clearing open descendants under that parent so old pages do not leave orphaned open state. Ignore initial zero-valued pattern clicks. Filter the complete comparison by literal case-insensitive global Underlying search before building nodes; label totals “Search matches” while that search is active. Clearing it restores the full filtered comparison. Unmapped-only search is separate: it resets `unmapped_page` to zero and filters only that detail list, leaving mapped data and the complete unmapped total intact.

8. Extend `build_validate_pl_table` with `page_by_parent`, `row_budget`, `unmapped_page=0`, and `unmapped_search=""`. Call it with the reduced navigation state. Extend `_validate_tree_table` to forward the same mapped hierarchy counter to `_tree_rows` as its existing `remaining` argument; `row_budget` and `remaining` refer to the same list object, not new counters per branch. Include navigation and both search strings in the render key. Remove the early return that skips rendering solely because date/filters are unchanged; expansion and paging now require rendering. Keep cached numeric comparison data reusable across these actions.

9. If the shared row budget would be exhausted by open branches, retain the most recently requested branch and close the oldest other open branches until the visible tree fits. Report which branches were collapsed to keep browsing responsive. Every branch and every page remains reachable; no financial row is permanently discarded. Do not exceed the budget just to append an arbitrarily large set of paging controls. Reserve their count as part of the budget calculation.

10. Add this helper immediately before `_validate_unmapped_table`. It pages only the unmapped detail records, while preserving the complete filtered unmapped amount. Its normal page size is 50:

    ```python
    VALIDATE_PL_UNMAPPED_PAGE_SIZE = 50

    def unmapped_detail_page(unmapped, page=0, search="", *, page_size=50):
        if not isinstance(unmapped, pd.DataFrame):
            raise TypeError("Unmapped comparison must be a DataFrame")
        text = str(search or "").strip().casefold()
        if len(text) > 200:
            raise ValueError("Unmapped search must contain at most 200 characters")
        selected = unmapped
        if text:
            matches = pd.Series(False, index=unmapped.index)
            for column in VALIDATE_PL_DIMENSION_COLUMNS:
                if column in unmapped:
                    matches |= unmapped[column].fillna("").astype(str).str.casefold().str.contains(text, regex=False)
            selected = unmapped.loc[matches]
        sort_columns = [column for column in (PORTFOLIO, RISK_TYPE, RISK_GREEK, UNDERLYING) if column in selected]
        if sort_columns:
            selected = selected.sort_values(sort_columns, kind="stable")
        page = validate_child_page(page, len(selected), page_size=page_size)
        start = page * page_size
        end = min(start + page_size, len(selected))
        return selected.iloc[start:end], {
            "page": page,
            "page_count": (len(selected) + page_size - 1) // page_size,
            "matching_count": len(selected),
            "total_count": len(unmapped),
            "start": start,
            "end": end,
            "total_colossus": reconciliation_metrics(unmapped)["colossus"],
        }
    ```

11. Extend `_validate_unmapped_table` to `_validate_unmapped_table(unmapped, *, page=0, search="", page_size=VALIDATE_PL_UNMAPPED_PAGE_SIZE)`. Start by calling `visible_unmapped, paging = unmapped_detail_page(unmapped, page, search, page_size=page_size)`. Replace the temporary B05 loop `for record in unmapped.head(50).to_dict("records"):` with `for record in visible_unmapped.to_dict("records"):`. If the temporary preview used a named first-50 frame instead, remove that frame and replace its loop at the same location. Remove the temporary first-50-only notice; the page caption below replaces it. Keep the row's exact Portfolio/Risk Type/Greek/Underlying, unavailable Predict, actual Colossus and mapping reason. Keep the extra status/coverage cells introduced in C06.

    Keep the summary count based on `paging["total_count"]` and add a caption displaying `paging["total_colossus"]` labelled “All filtered unmapped Colossus”. This complete amount must not change when paging or using the unmapped-only search. Render a separate detail caption `Rows {start + 1}–{end} of {matching_count} matching` when matches exist, otherwise “No unmapped entries match this search”. A match count is not a substitute for the complete unmapped count. Set the returned `html.Details` to `open=True` so clicking Next does not replace it with a closed section.

    When `paging["page_count"] > 1`, append Previous and Next buttons immediately below the table, with IDs `{"type": "pl-validate-unmapped-page", "page": max(page - 1, 0)}` and `{"type": "pl-validate-unmapped-page", "page": min(page + 1, page_count - 1)}` using the normalized values from `paging`. Set `n_clicks=0`, disable the first/last controls appropriately, and use `className="refresh-button"`. For zero/one page, omit both buttons; this avoids duplicate IDs pointing to page zero. Do not serialize all unmapped rows into a browser store or hidden second table.

12. In `render_validate_pl`, when `ctx.triggered_id` is an unmapped-page ID with a positive corresponding click, validate the requested integer page and write it to `navigation_state["unmapped_page"]`; do not alter mapped open paths/pages. After applying page-wide filters and the global Underlying search, select the unmapped subset with `comparison[HISTORY_MAPPING_STATUS].eq(UNMAPPED_VALUE)`. Calculate `unmapped_page_size = min(VALIDATE_PL_UNMAPPED_PAGE_SIZE, max(1, _VALIDATE_PL_MAX_RENDERED_ROWS // 4))`. Call `unmapped_detail_page` on this subset with the requested page, `unmapped_search`, and `page_size=unmapped_page_size` to clamp the page against actual matches. Put that normalized page back in the navigation store and pass it plus `unmapped_search` into `build_validate_pl_table`. Include the normalized unmapped page and search in the render key. When unmapped search changes, start at page zero. Date/filter/cache changes reset it to zero through step 7. On empty results return the bounded empty message and a zero page; never reuse an old page against new data.

    In `build_validate_pl_table`, reserve unmapped rows before allocating the mapped-tree budget. Use `unmapped_page_size = min(VALIDATE_PL_UNMAPPED_PAGE_SIZE, max(1, _VALIDATE_PL_MAX_RENDERED_ROWS // 4))`. When an unmapped subset exists, reserve `unmapped_page_size + 3` slots for its data, summary and pager before constructing mapped rows. The shared mapped counter starts at the remaining budget; require the configured overall budget to be at least 16 so navigation itself can fit. Pass that page size to `_validate_unmapped_table`. This keeps the complete rendered comparison bounded across both sections. Financial totals still come from the complete filtered frames, never the reserved page slice.

13. Run this notebook check, then page through a real preview scope with more than 50 unmapped entries. All entries must remain reachable:

    ```python
    import pandas as pd
    from cube.pages.pnl.s06_validation import unmapped_detail_page
    comparison_check = pd.DataFrame({
        "Portfolio": [f"CHECK_{number:03d}" for number in range(121)],
        "Risk Type": ["IR"] * 121, "Risk Greek": ["Delta"] * 121,
        "Underlying": ["CHECK_U"] * 121,
        "pl": [float("nan")] * 121, "colossus": [1.0] * 121,
    })
    observed = []
    for page in range(3):
        records, paging = unmapped_detail_page(comparison_check, page)
        assert len(records) <= 50
        assert paging["total_count"] == 121 and paging["total_colossus"] == 121.0
        observed.extend(records["Portfolio"].tolist())
    assert len(observed) == 121 and len(set(observed)) == 121
    records, paging = unmapped_detail_page(comparison_check, 99, "CHECK_120")
    assert records["Portfolio"].tolist() == ["CHECK_120"]
    assert paging["page"] == 0 and paging["total_colossus"] == 121.0
    print("Unmapped paging, search and full-total checks passed")
    ```

14. Open `assets/s14_pnl.js`. Remove `setValidateRowOpen`, `toggleValidateHierarchy`, and the document click-handler block dispatching `.validate-pl-row-toggle` only after the Dash callback path exists. Keep unrelated P&L disclosure, editor and send behavior in that file.

15. In the browser and notebook, verify: closed branches generate no descendant components; opening a branch generates only its first page; 81 children are all reachable through four pages; a child with missing Predict sorts ahead of complete reconciled children; moving pages preserves full total and coverage; search finds a child originally on page 4; clearing search restores full totals; refresh resets stale navigation. Check the 121-row unmapped scope across three pages, including a last-page search and then clearing it.

    Add this notebook-only helper to count the components actually constructed. The configured budget counts hierarchy/data rows plus reserved navigation slots; it is not a limit on every `Td`, button and wrapper. Keep fixed header/root rows separate when interpreting the `Tr` count. Use the helper on the table returned by `build_validate_pl_table` when checking mapped expansion, and on `_validate_unmapped_table` as in this complete small check:

    ```python
    from collections import Counter
    from dash.development.base_component import Component
    from cube.pages.pnl.s06_validation import _validate_unmapped_table

    def generated_component_counts(value):
        counts = Counter()
        def visit(item):
            if isinstance(item, Component):
                counts[type(item).__name__] += 1
                visit(item.to_plotly_json()["props"])
            elif isinstance(item, dict):
                for child in item.values():
                    visit(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    visit(child)
        visit(value)
        return counts

    counts = generated_component_counts(_validate_unmapped_table(comparison_check, page=0))
    # Fifty data rows and a small fixed header/footer allowance, never all 121 rows.
    assert 50 <= counts["Tr"] <= 55, counts
    print(dict(counts))
    ```

16. Run `check_syntax(['cube/pages/pnl/s06_validation.py'])`. In the browser expand, page, collapse, use both searches, change date, then return. There must be one response to each click and no duplicate browser/server toggle handling.

<a id="job-c08"></a>
## Job C08 — Keep P&L summary dates, periods and historical filters aligned

1. Back up the files:

   ```python
   backup_job("C08", [
       "cube/pages/pnl/s10_summary.py", "cube/pages/pnl/s08_aggregate.py",
       "cube/pages/pnl/s09_drilldown.py", "cube/pages/pnl/s07_view.py",
       "cube/history/s07_sql.py",
   ])
   ```

2. In `s10_summary.py`, replace the displayed Today label with a label constructed inside `build_pl_summary_table` from its existing `as_of_date`: `f"Archived Predict {as_of_date}"` when a date exists, otherwise “Archived latest Predict”. Label MTD/YTD as Colossus amounts, matching the existing query. Keep the underlying `PL_RISK_SUMMARY_CURRENT` field name to avoid an unnecessary schema change. Display current calculated base/effective-to-send separately in the editor; do not relabel an archive amount as live current P&L.

3. In each summary history-cell ID, retain `metric` and add `as_of_date`. Update the `ALL` pattern in `s08_aggregate.py` to match the new key. In `select_pl_history_cell`, return both fields in `pl-history-selection-store` alongside Risk Type/Greek/Underlying. Add the exact committed filter state to the selection so a subsequent filter edit cannot relabel the existing chart without a new load.

4. In `s09_drilldown.py`, when the selection store triggers, map `PL_RISK_SUMMARY_CURRENT` to that one archived date and the Predict source, MTD to the first day of that date's month through that date and Colossus, and YTD to January 1 through that date and Colossus. Compute dates using `pd.Timestamp`, `replace(day=1)` and `replace(month=1, day=1)`. Keep the clicked `as_of_date` as the end; do not use the computer's current date. Add one hydration callback owning `pl-history-period.value`, `pl-history-date-range.start_date`, `pl-history-date-range.end_date` and `pl-history-series-selector.value`, triggered by `pl-history-selection-store.data`. Use Custom for the one-date Current request, MTD/YTD for the other two, while setting the exact start/end dates. Ensure the figure callback uses the selection's committed dates/source when that store itself triggers, so callback scheduling cannot briefly query old controls. Subsequent explicit period/source edits may change the range, while retaining the same exact selected identity/filter scope.

5. Add a Daily / Cumulative control beside the existing history series choice in `s07_view.py`, default Daily, with one input to `render_inline_pl_history`. Apply presentation after receiving the same daily series: sort by Market Date and, within each P&L Type, calculate cumulative sums starting from the selected period's start. Keep unavailable points unavailable. After a missing required day's amount, cumulative totals must stay unavailable until a new complete period starts; do not let `cumsum(skipna=True)` hide a gap. Do not calculate cumulative values across different P&L Types or a mixture of scopes.

6. Add `history_filter_options(*, selected=None, limit=2000)` to `SQLPLHistoryRepository`. Return a dictionary keyed by the source-owned `HISTORY_DIMENSION_COLUMNS`, with sorted canonical string values as each value. Query distinct nonblank values from validated `_pl_history`; use fixed schema identifiers and bound parameters for values. Fetch `limit + 1` per dimension so a bound is detectable. If exceeded, return a clear request for a narrower archive range instead of silently dropping selected values. Include any exact selected historical values after verifying their existence with a parameterized query. Reuse the bounded connection/generation cache; do not load complete position frames just to form options.

7. In `s08_aggregate.py::update_pl_filter_controls`, merge those historical values with the current options by exact canonical value. Label values found only in history as “historical”, and preserve a selected historical Portfolio even when absent from the current snapshot. This is one shared filter set; do not add another page-mode store merely to choose options. Current sending still uses current Portfolio governance. If a selected historical-only Portfolio has no current send rows, show that fact and disable its send action; do not silently broaden the selection to All. Keep Base Review initialization based on the existing current authority so the historical union does not unexpectedly change the page's default filters.

8. Check an archive dated December 31 while the machine is in January; Today must say Archived December 31, MTD must cover that December, and YTD that prior year. Click each metric and assert the reader receives those dates. Check a Portfolio present only in history, a missing daily value, Daily/Cumulative switching, and filter changes after a click. Run `check_syntax(['cube/pages/pnl/s10_summary.py', 'cube/pages/pnl/s08_aggregate.py', 'cube/pages/pnl/s09_drilldown.py', 'cube/pages/pnl/s07_view.py', 'cube/history/s07_sql.py'])`.

<a id="job-c09"></a>
## Job C09 — Make empty market legs and reduction retries safe

1. Back up the files:

   ```python
   backup_job("C09", [
       "cube/domain/s03_calculations.py", "cube/domain/s11_tenorreduction.py",
       "cube/pages/risk/s02_state.py",
   ])
   ```

2. In `get_product_market_open`, locate the early `if frame.empty: return frame[columns].copy()`. Replace its body with a copy that explicitly sets `Open` to a float Series and each `spec.tenor_order_columns` field to an `Int64` Series on the same empty index. In `get_product_market_status`, do the same for `Current`; retain the already selected Market Status. Set market identity columns to a consistent text/object dtype in both empty and nonempty results. Do not fabricate identity rows to make an empty merge succeed.

   ```python
   # Open branch; use CURRENT for the analogous Current branch.
   if frame.empty:
       result = frame.loc[:, columns].copy()
       result[OPEN] = pd.Series(index=result.index, dtype="float64")
       for column in spec.tenor_order_columns:
           result[column] = pd.Series(index=result.index, dtype="Int64")
       for column in spec.market_keys:
           result[column] = result[column].astype(object)
       return result
   ```

3. In `_merge_validated_market_legs`, keep `validate="one_to_one"` on the quote-leg join. Before any same-row Open/Current fallback assignment, ensure both quote columns are numeric floats. Use `pd.to_numeric(..., errors="raise").astype(float)` on the already validated values. Keep the separate Risk-to-Market `many_to_one` join unchanged.

4. Preserve the application's explicit one-leg copying policy and its status labels: an Open-only row may show Current copied from Open, and vice versa. These are fallback quotes, not two independent observed prices. Keep “Available; Open copied from Current” / “Available; Current copied from Open” visible in details and coverage. Both missing remains unavailable and PL/Move remain missing. Never replace truly missing market data with zero. If the business later removes quote copying, treat that as a separate financial-policy change with separate acceptance checks.

5. For a connector exception, preserve the last complete committed revision and its caption. Do not catch an exception and substitute an empty market frame as though the connector successfully reported no observations. Check connector exception and successful empty result separately.

6. Add `clear()` immediately after `ReducedTenorReducer.__init__`:

   ```python
   def clear(self):
       """Permit an explicit retry after a provider/catalog repair."""
       with self._cache_lock:
           self._catalog = None
           self._matrix_cache.clear()
           self._unavailable_matrices.clear()
           self._credit_mapping_cache.clear()
           self._unavailable_credit_mappings.clear()
           self._matrix_names = frozenset()
   ```

7. In `_RiskDataCache.clear_reconstructable`, after releasing the existing nested market/state locks, acquire `_reducer_load_lock` and, if `_tenor_reducer` exists, call `_tenor_reducer.clear()`. It will reload its matrix/catalog lazily on next use. Keep the existing cache epoch increment and last-good committed frame. Do not call a provider while holding the general view-cache lock.

8. In `_reduced_for_scope`, capture `_cache_epoch` alongside the initial cache lookup, before reducing. Before publishing a reduced result, check both the revision and that captured epoch still match. Return `None`/retry through the existing caller path if they changed. Otherwise an in-flight request begun before Clear Cache could repopulate the cache with the repaired provider's old failure result.

9. In `ReducedTenorReducer._reduce_batch`, replace both `np.uint8` conversions in support counting with `np.int64`: `nonzero_weights = (weights != 0.0).astype(np.int64)` and `observed.astype(np.int64)` inside `einsum`. Update `bytes_per_position` so its estimate includes the larger support tensors. A conservative formula is `measure_count * (old_tenor_count * 25 + new_tenor_count * 24) * 2`; keep the existing bounded chunk calculation. Do not fix overflow by capping the count at 255.

10. Keep monetary P&L unchanged by optional tenor presentation. In `_reduce_batch`, immediately after creating `weights`, if `PL` is among the additive columns require the sum of each matrix column to equal 1 within `np.allclose(..., rtol=0.0, atol=1e-12)`. Otherwise log a specific warning and return `None` for that batch so the caller retains its authoritative full-tenor rows. This is the smallest safe contract: do not normalize an arbitrary Risk transformation into a guessed P&L allocation. The fallback caption must state that full tenors are retained because the supplied matrix does not conserve P&L.

11. Preserve missing P&L coverage during a valid reduction. After the existing support calculation, for the PL measure only, build a boolean `(chunk_count, old_tenor_count)` array marking supplied source rows whose PL is missing. Populate it with `np.logical_or.at(missing_pl, (chunk_codes, chunk_old_codes), np.isnan(values[:, pl_index]))`. Multiply its integer form by nonzero matrix support. Set an output PL to `NaN` when any missing contributing source PL feeds that output. An absent position at a tenor is distinct from a supplied position whose PL is unavailable. Keep this rule limited to PL; do not silently alter all Risk/dRisk missing-value policies.

12. In `_reduce_credit_batch`, keep the existing exact full-tenor-to-reduced-tenor mapping and summation, but apply the same strict missing-PL coverage rule per position/reduced tenor: compare nonmissing PL count to contributing supplied-row count; if unequal, retain `NaN`. A mapping that drops a full tenor must keep the existing full-tenor fallback.

13. Run the following complete notebook reduction check. It creates only small synthetic frames:

    ```python
    import numpy as np
    import pandas as pd
    from cube.domain.s11_tenorreduction import ReducedTenorReducer, REDUCED_TENOR_CATALOG_COLUMNS
    for count in (255, 256, 257):
        frame_check = pd.DataFrame({
            "Source Type": ["ir/delta"] * count,
            "Risk Type": ["IR"] * count, "Risk Greek": ["Delta"] * count,
            "Underlying": ["CHECK_U"] * count,
            "Tenor Swap": [f"T{i}" for i in range(count)],
            "Tenor Swap Order": range(count), "Portfolio": ["CHECK_BOOK"] * count,
            "Risk": [1.0] * count, "dRisk": [1.0] * count, "PL": [1.0] * count,
        })
        matrix_check = pd.DataFrame(
            np.ones((1, count)), index=["All"], columns=frame_check["Tenor Swap"],
        )
        catalog_check = pd.DataFrame(
            [["IR", "Delta", "CHECK_U", "CHECK_MATRIX"]],
            columns=REDUCED_TENOR_CATALOG_COLUMNS,
        )
        reduced_check = ReducedTenorReducer(catalog_check, lambda name: matrix_check).reduce(frame_check)
        for metric in ("Risk", "dRisk", "PL"):
            assert reduced_check[metric].tolist() == [float(count)], (count, metric)
    print("255 / 256 / 257 support checks passed")
    ```

    Repeat with a conserving two-output matrix and positive/negative position PL; compare per-Portfolio full and reduced PL sums. A nonconserving matrix must retain full rows. A missing contributing PL must stay unavailable in its affected output, while unrelated complete outputs remain valid.

14. Check provider failure → cached full-tenor fallback → provider repaired → explicit Clear Cache → provider called again → reduced display. Add an in-flight old-epoch check and assert it cannot publish after Clear Cache. Check empty Open, empty Current, both empty, nonfinite quote rejection, and connector exception retaining the last-good revision. Run `check_syntax(['cube/domain/s03_calculations.py', 'cube/domain/s11_tenorreduction.py', 'cube/pages/risk/s02_state.py'])`.

<a id="job-c10"></a>
## Job C10 — Remove obsolete layers after their replacements pass

At this position in the sequence, perform only the inventory below. Do not delete definitions yet: the Data and later performance/feature replacements are still to come. Execute the identified removals in Job Z01, after those replacements exist and their notebook/browser checks pass. Cleanup must remove duplicate responsibility, not the validation that protects values and scope.

1. Save an inventory-stage backup of the files below and record the preceding focused checks in the notebook. Make no deletions here. Job Z01 must make a fresh backup immediately before its edits; restoring this earlier inventory backup later would also discard the intervening jobs. The inventory scope uses:

   ```python
   backup_job("C10", [
       "cube/pages/pnl/s02_editor.py", "cube/pages/pnl/s05_sendcallbacks.py",
       "cube/domain/s09_stock.py", "cube/domain/__init__.py",
       "cube/pages/stock/s04_callbacks.py",
   ])
   ```

   The Data job separately lists and backs up its exact controls/callbacks/assets before removing them. Do not edit additional files under this backup identifier; create a separate named backup with their complete paths if an import inventory identifies another required cleanup.

2. Record the Data controls/callbacks that its upcoming job explicitly replaces. After that job is complete, Job Z01 keeps its unified query/draft/loaded-result owner and removes only the named obsolete separate Risk/Market controls, stores and callbacks. Search each component ID across Python and assets before deletion. Update decorators and layouts together; do not leave hidden old inputs just to satisfy stale callbacks. At C10, record this work only.

3. Record any duplicated P&L collapse/overlay/save logic remaining after C01/C02. At Z01, keep the two useful scope selectors, the existing `register_editor` factory, and shared pure replacement/draft helpers. Remove duplicate arithmetic only after both scopes call the shared helpers. Keep destinations explicit; do not introduce a generic plugin/editor framework.

4. Inventory Stock legacy route symbols with this notebook cell:

   ```python
   import re
   symbols = re.compile(r"STOCK_HIERARCHY_|STOCK_PROMOTION_|build_stock_hierarchy|promote_stock")
   for path in sorted(APP_ROOT.rglob("*.py")):
       if any(part in {".venv", "venv", "__pycache__", "data"} for part in path.parts):
           continue
       for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
           if symbols.search(line):
               print(path.relative_to(APP_ROOT), number, line.strip())
   ```

5. Record obsolete Stock promotion/hierarchy candidates in `cube/domain/s09_stock.py` only when no live caller remains. At Z01, before each removal, search the exact symbol through all Python files, including package `__init__.py` exports, adapters and tools. If a live caller remains, keep the symbol until that caller is explicitly migrated. Do not remove Stock comparison, mapping, filtering, metadata or archive identity helpers.

6. Record the checks required after each proposed removal: position identity, outer-comparison exits, left many-to-one Portfolio mapping, unmapped retention, tenor authority, full totals and callback ownership. Execute them at Z01 after making that removal. Do not delete validation merely because a retired route also used it.

7. Record any remaining old full-detail Stock output. At Z01, keep lazy server-paged detail and the exact selected-identity history contract; remove the old full-detail `to_dict("records")` output only after the paged callback owns it. Do not add a second hidden table containing all positions.

8. Record any retained HTML variants superseded by bounded numeric caches. At Z01, remove only those proven-unused variants. Keep the numeric history, prepared Risk index and current Stock snapshot responsibilities. Do not add workers, queues, another query database or a generic chart registry during cleanup.

9. Save the inventory in the working notebook and continue to the Data job. After implementing the listed removals at Z01, run `check_syntax(['cube/pages/pnl/s02_editor.py', 'cube/pages/pnl/s05_sendcallbacks.py', 'cube/domain/s09_stock.py', 'cube/domain/__init__.py', 'cube/pages/stock/s04_callbacks.py'])`, restart the preview and visit Risk, Data, Stock, P&L and Statics. Verify no missing component IDs, duplicate output owners or stale captions appear.

<a id="job-d00"></a>
## Job D00 — Correct Quick Risk totals before using them as a comparison

**Result:** Quick Risk's footer does not sum quote levels across positions, and its financial totals do not stop at the 250 displayed leaf groups.

1. Run this complete backup cell before editing:

   ```python
   backup_job("D-quick-totals", [
       "cube/domain/s10_search.py",
       "cube/app/s02_contracts.py",
       "cube/pages/risk/s08_quickrisk.py",
       "cube/pages/risk/s10_search.py",
   ])
   ```

   Keep the existing exact-identity lookup, Risk filtering, raw Risk-to-quote bridge and quote uniqueness guards.
2. In `cube/domain/s10_search.py::SearchResult`, add two optional fields after the existing required `total` field:

   ```python
   full_totals: Mapping[str, float | None] | None = None
   chart_frame: pd.DataFrame | None = None
   ```

   Defaults preserve other search result constructors. `full_totals` contains the Risk, dRisk and PL totals plus explicit PL coverage counts; it contains no aggregate Open/Current/Move.
3. In `SearchCatalog.pivot_combined_hierarchy`, locate the assignment `selected_risk, selected_quotes = self._combined_source_rows(...)`. Immediately after this complete call, before any `visible_leaves` slicing, add:

   ```python
   full_totals = {}
   for metric in RISK_PIVOT_VALUE_COLUMNS:
       values = pd.to_numeric(selected_risk[metric], errors="coerce")
       finite = values.notna() & np.isfinite(values).fillna(False)
       value = values.where(finite).sum(min_count=1)
       full_totals[metric] = None if pd.isna(value) else float(value)
       if metric == "PL":
           missing = int((~finite).sum())
           full_totals["PL missing rows"] = missing
           full_totals["PL total rows"] = len(values)
           if missing:
               full_totals["PL"] = None
   chart_columns = [column for column in TENOR_COLUMNS if column in selected_risk]
   if selected_risk.empty:
       chart_frame = selected_risk.loc[:, [*chart_columns, *RISK_PIVOT_VALUE_COLUMNS]].copy()
   elif chart_columns:
       chart_frame = selected_risk.groupby(
           chart_columns, sort=False, dropna=False, observed=True
       )[list(RISK_PIVOT_VALUE_COLUMNS)].sum(min_count=1).reset_index()
       # The PL sum is unavailable if any contributing position lacks PL.
       pl_complete = selected_risk.assign(
           __pl_complete__=np.isfinite(pd.to_numeric(selected_risk["PL"], errors="coerce")).fillna(False)
       ).groupby(chart_columns, sort=False, dropna=False, observed=True)["__pl_complete__"].all()
       chart_frame.loc[~pl_complete.to_numpy(), "PL"] = np.nan
   else:
       chart_frame = pd.DataFrame([{metric: full_totals[metric]
                                    for metric in RISK_PIVOT_VALUE_COLUMNS}])
   chart_cells = 1
   for column in chart_columns:
       chart_cells *= max(1, int(chart_frame[column].nunique(dropna=False)))
   if chart_cells > 10_000:
       chart_frame = None
   ```

   Before grouping, preserve existing tenor-order authority: when an order column exists, prove each tenor label has one unique rank; append the one-per-label rank mapping back to the grouped chart using `validate="many_to_one"`. If ambiguous, display a chart-order warning rather than selecting an arbitrary rank. Do not group sums by `Portfolio`, and do not use quote rows to calculate Risk totals.
4. Add `full_totals=MappingProxyType(full_totals)` and `chart_frame=chart_frame` to the `SearchResult(...)` returned by this hierarchy method. Keep the hierarchy's bounded `frame`, total leaf count and revision unchanged. The chart contains only aggregated tenor cells, not all position rows. The 10,000-cell chart guard suppresses the chart with a clear message; it never truncates financial totals or underlying data.
5. In `cube/app/s02_contracts.py::SearchResultProtocol`, add read-only properties `def full_totals(self) -> Mapping[str, float | None] | None: ...` and `def chart_frame(self) -> pd.DataFrame | None: ...`, each decorated with `@property`, matching its existing result properties. Keep `RiskRefreshManager.pivot_combined_hierarchy` in `cube/services/s02_state.py` as the existing pass-through; it already returns the domain result without reconstructing it.
6. In `cube/pages/risk/s10_search.py::_render_quick_search_pivot`, after the final `result` is obtained (including the optional second query after tenor-index pruning), read `full_totals` and `chart_frame` from the object attributes or mapping keys. Pass them as new keyword arguments to `build_quick_search_pivot`. Leave `_quick_search_result_parts`' three-value tuple unchanged so its other callers/checks do not break.
7. In `cube/pages/risk/s08_quickrisk.py::build_quick_search_pivot`, add keyword arguments `full_totals=None, chart_frame=None`. Locate the loop below the comment **Compute totals and the current chart from leaf rows only**. Replace its indiscriminate sum of all six metric columns with:

   ```python
   metric_summaries = {"Open": None, "Current": None, "Move": None}
   for metric in ("Risk", "dRisk", "PL"):
       if full_totals is not None:
           metric_summaries[metric] = full_totals.get(metric)
       else:
           values = pd.to_numeric(leaf_frame.get(metric), errors="coerce")
           value = values.sum(min_count=1)
           metric_summaries[metric] = None if pd.isna(value) else float(value)
   ```

8. Add a coverage caption using `PL total rows` and `PL missing rows`: **PL available for N of M positions**. If any selected position lacks finite PL, the full PL total is `—`; a known-position subtotal must not be labeled the full total. Risk/dRisk remain additive totals of their available finite source values under the existing risk convention. Set the footer label to **Total — full selected scope** when `full_totals` is supplied. For older callers without it, use **Displayed groups subtotal**; do not label a capped subtotal as a full total. Quote cells display `—`. For missing totals, set `data-copy-value` to an empty string, not `None`, `nan` or zero; keep the existing number formatter for real finite values.
9. Replace `build_quick_risk_figure(leaf_frame, selected_indexes)` at the graph construction point. With `full_totals` and a non-None `chart_frame`, render that complete tenor aggregate. With full totals but `chart_frame is None`, return an empty figure captioned **Chart exceeds the detail budget; narrow the selection. Full totals remain available.** For legacy callers without full totals, the old leaf chart may remain only with an explicit **Displayed groups only** caption. Do not silently use capped leaf rows for the modern full-scope chart.
10. Keep every normal hierarchy row's existing independently resolved quote values. Do not blank all Market information just because a quote total is not additive. In particular retain `SearchCatalog._combined_source_rows`' unique raw quote positions and existing `_combined_pivot`/parent aggregation contracts.
11. Run `check_syntax(["cube/domain/s10_search.py", "cube/app/s02_contracts.py", "cube/pages/risk/s08_quickrisk.py", "cube/pages/risk/s10_search.py"])`. In the running app, inspect an identity with two Portfolios sharing a quote and one with more than 250 leaves. Confirm the Risk/dRisk total covers the full selection while Open/Current/Move footer cells remain blank. For one known PL value of 10 and one missing value, expect full PL `—` and coverage 1 of 2; do not report total PL 10. For all missing PL, expect `—`, never 0. Confirm copied missing cells are empty and the chart is independent of the displayed leaf cap.
12. Restart and inspect Quick Risk before proceeding. The values used when comparing with Data must come from full-scope financial totals, while quote charts remain independently scoped Market observations.

<a id="job-d01"></a>
## Job D01 — Define the one Data workspace and make its backup

**Result:** Quick Risk and Quick Market both open the existing Data route. Data has one main series picker and one **Risk / Market / Both** segmented control. Both displays two coordinated panels in the same workspace. Risk and Market keep their own identity, values, units and filters; they are never concatenated into one financial measure.

Perform this chapter after the history allocation and query limits have been installed. Complete D01–D10 as one change before restarting the app. During intermediate edits, the old layout and new callbacks will not match.

1. Run this notebook cell before editing:

   ```python
   backup_job("D-unified-data", [
       "cube/pages/data/s01_selection.py",
       "cube/pages/data/s02_view.py",
       "cube/pages/data/s03_callbacks.py",
       "cube/pages/data/s04_workspace.py",
       "cube/pages/risk/s04_handoff.py",
       "cube/history/s06_repository.py",
       "cube/app/s07_factory.py",
       "assets/s02_controls.css",
       "assets/s04_pnl.css",
       "assets/s06_visuals.css",
       "assets/s07_history.css",
       "assets/s09_playback.js",
   ])
   ```

2. Open `cube/pages/data/s02_view.py::build_data_page`, `cube/pages/data/s03_callbacks.py::register_callbacks`, and `cube/pages/risk/s04_handoff.py::build_history_handoff` using `show_symbol`. These are the current layout, callback owner and Quick handoff constructor.
3. **KEEP** the existing Data route, lazy layout, archive repository, `HistoryIdentity`, `HistoryHandoff`, `HistoryQuery`, `RiskFilterView`, archive validation, ProductSpec axes, and native page registration. Do not create a second Data page or a new archive format.
4. **KEEP** Quick Risk and Quick Market on Risk. Their **Open in Data** buttons are entry points to the unified Data workspace. This job does not delete the Quick tools or move their current Risk-page functionality.
5. **REMOVE** the separate Risk History / Market History tabs from Data, the visible four-dropdown Identity / Risk Type / Risk Greek / Underlying cascade, and the old dropdown-cascade callbacks. Exact callback names are listed in D06.
6. **ADD** one searchable series picker. Its labels must contain kind, Risk Type, Greek, underlying, reported/raw mode and Source Types. Its value must be the existing catalog key, not display text.
7. **ADD** the Both mode as a page-owned request containing one Risk handoff and one Market handoff. Do not add `"both"` to `HistoryHandoff.kind`, `HistoryCatalogEntry.kind`, database query kinds or archive file names. Those contracts remain strictly `"risk"` or `"market"`.
8. **KEEP** WTD, MTD, YTD, 1Y, 5Y, All and Custom. Use matching Stock/P&L styling without reducing Data's available periods.
9. Use **Snapshot / Over time / Compare** as the main view control. Keep the existing additional projections inside **Advanced chart options**. Put diagnostics in a separate collapsed **Diagnostics** area. Put values in a collapsed **Show values** area.
10. Treat Risk and Market dates as observation dates, not interchangeable archive folder names. Both uses a common selected calendar date. A missing observation remains missing; do not substitute the nearest date or zero.

The finished control order is: **Risk / Market / Both → searchable series → companion when needed → period → custom dates when needed → Load**. Below that: a loaded-selection caption, **Snapshot / Over time / Compare**, contextual chart controls, one shared player, the chart panels and the collapsed values/diagnostics sections.

### Outcome check for D01

Check the planned layout against the listed KEEP/REMOVE controls before editing. Both Quick entry buttons must still target the single existing Data route. D01–D08 are coupled; finish the notebook checks in D09 and the fresh-process browser checks in D10 before accepting or restarting this combined layout/callback change.

<a id="job-d02"></a>
## Job D02 — Add exact selection and pairing helpers

**Result:** a reported Risk series cannot silently become a raw Market quote, and changing the period cannot drop the Risk filter scope.

1. **KEEP** `cube/pages/data/s01_selection.py` for its existing public pure helpers; existing callers can continue using them. The new UI must not call `selected_value()` to choose an arbitrary financial series or companion.
2. **ADD** `cube/pages/data/s04_workspace.py` with the complete code below. This module performs no archive I/O and creates no Dash app.

   ```python
   """Pure selection and immutable requests for the unified Data workspace."""
   from __future__ import annotations

   from dataclasses import replace
   from datetime import date, timedelta
   from typing import Mapping
   import hashlib
   import json
   import pandas as pd

   from cube.history import (
       HistoryHandoff, HistoryIdentityCatalog, HistoryQuery,
       HistoryValidationError, RiskFilterView,
   )

   DISPLAY_MODES = ("risk", "market", "both")
   QUICK_KEY = "__quick_handoff__"

   def catalog_entries(raw):
       catalog = (raw if isinstance(raw, HistoryIdentityCatalog)
                  else HistoryIdentityCatalog.from_mapping(raw))
       return catalog.entries

   def entry_label(entry):
       identity = entry.identity
       mode = "Reported" if identity.identity_mode == "reported" else "Raw"
       return (
           f"{entry.kind.title()} · {identity.risk_type} · "
           f"{identity.risk_greek} · {identity.underlying} · {mode} · "
           f"{', '.join(identity.source_types)}"
       )

   def series_options(raw_catalog, display_mode):
       if display_mode not in DISPLAY_MODES:
           raise HistoryValidationError("Choose Risk, Market or Both")
       entries = catalog_entries(raw_catalog)
       selected = [entry for entry in entries
                   if display_mode == "both" or entry.kind == display_mode]
       return [{"label": entry_label(entry), "value": entry.key}
               for entry in sorted(selected,
                                   key=lambda item: (entry_label(item).casefold(),
                                                     item.key))]

   def retain_exact(options, current):
       values = {option["value"] for option in options}
       return current if current in values else None

   def handoff_from_entry(raw_catalog, key, reset, risk_scope=None):
       if isinstance(reset, bool) or not isinstance(reset, int) or reset < 0:
           raise HistoryValidationError("Reset generation must be a nonnegative integer")
       catalog = (raw_catalog if isinstance(raw_catalog, HistoryIdentityCatalog)
                  else HistoryIdentityCatalog.from_mapping(raw_catalog))
       handoff = catalog.resolve(key).to_handoff(reset_generation=reset)
       if handoff.kind == "risk" and risk_scope is not None:
           scope = (risk_scope if isinstance(risk_scope, RiskFilterView)
                    else RiskFilterView.from_mapping(risk_scope))
           handoff = replace(handoff, filter_view=scope)
       return handoff

   def opposite_options(raw_catalog, primary):
       """Explicit comparison choices, not an inferred economic mapping."""
       opposite = "market" if primary.kind == "risk" else "risk"
       entries = [entry for entry in catalog_entries(raw_catalog)
                  if entry.kind == opposite]
       return [{"label": entry_label(entry), "value": entry.key}
               for entry in sorted(entries,
                                   key=lambda item: (entry_label(item).casefold(),
                                                     item.key))]

   def unambiguous_raw_companion(raw_catalog, primary):
       """Only identical single-source raw identities can pair automatically."""
       identity = primary.identity
       if identity.identity_mode != "underlying" or len(identity.source_types) != 1:
           return None
       opposite = "market" if primary.kind == "risk" else "risk"
       candidates = [entry for entry in catalog_entries(raw_catalog)
                     if entry.kind == opposite and entry.identity == identity]
       return candidates[0].key if len(candidates) == 1 else None

   def scope_caption(raw_scope):
       if raw_scope is None:
           return "Risk scope: all archived positions for the selected identity"
       scope = (raw_scope if isinstance(raw_scope, RiskFilterView)
                else RiskFilterView.from_mapping(raw_scope))
       items = [f"{column}={', '.join(values)}"
                for column, values in scope.filters]
       mode = "Exclude selected" if scope.exclude_selected else "Include selected"
       return f"Risk scope: {mode}; " + ("; ".join(items) or "no restrictions")

   def workspace_request(display_mode, risk, market, *, period,
                         start_date=None, end_date=None, request_id):
       if display_mode not in DISPLAY_MODES:
           raise HistoryValidationError("Choose Risk, Market or Both")
       selected = {"risk": risk, "market": market}
       required = (("risk", "market") if display_mode == "both"
                   else (display_mode,))
       handoffs = {}
       for kind in required:
           handoff = selected[kind]
           if not isinstance(handoff, HistoryHandoff) or handoff.kind != kind:
               raise HistoryValidationError(f"Choose an exact {kind.title()} series")
           handoff = replace(handoff, metric="risk" if kind == "risk" else "current")
           query = HistoryQuery(handoff, str(period).casefold(),
                                start_date if period == "custom" else None,
                                end_date if period == "custom" else None)
           handoffs[kind] = handoff.to_mapping()
       resets = {item["reset_generation"] for item in handoffs.values()}
       if len(resets) != 1:
           raise HistoryValidationError("Selections belong to different cache resets")
       return {
           "schema_version": 1,
           "display_mode": display_mode,
           "handoffs": handoffs,
           "period": query.period,
           "start_date": query.start_date.isoformat() if query.start_date else None,
           "end_date": query.end_date.isoformat() if query.end_date else None,
           "request_id": str(request_id),
       }

   def parse_workspace_request(raw):
       fields = {"schema_version", "display_mode", "handoffs", "period",
                 "start_date", "end_date", "request_id"}
       if not isinstance(raw, Mapping) or set(raw) != fields:
           raise HistoryValidationError("Invalid Data workspace request fields")
       if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
           raise HistoryValidationError("Unsupported Data workspace request version")
       mode = raw["display_mode"]
       if mode not in DISPLAY_MODES:
           raise HistoryValidationError("Invalid Data display mode")
       required = {"risk", "market"} if mode == "both" else {mode}
       if not isinstance(raw["handoffs"], Mapping) or set(raw["handoffs"]) != required:
           raise HistoryValidationError("Selected mode and handoffs do not match")
       parsed = {kind: HistoryHandoff.from_mapping(value)
                 for kind, value in raw["handoffs"].items()}
       normalized = workspace_request(
           mode, parsed.get("risk"), parsed.get("market"),
           period=raw["period"], start_date=raw["start_date"],
           end_date=raw["end_date"], request_id=raw["request_id"],
       )
       if normalized != dict(raw):
           raise HistoryValidationError("Data request is not in canonical form")
       return parsed

   def common_bounds(raw_request, available_by_kind):
       """Resolve one period against the union of actual observation dates."""
       parsed = parse_workspace_request(raw_request)
       available = sorted({date.fromisoformat(str(value))
                           for kind in parsed
                           for value in available_by_kind.get(kind, ())})
       period = raw_request["period"]
       if period == "custom":
           return (date.fromisoformat(raw_request["start_date"]),
                   date.fromisoformat(raw_request["end_date"]))
       if not available:
           return None, None
       end = available[-1]
       if period == "all":
           start = available[0]
       elif period == "wtd":
           start = end - timedelta(days=end.weekday())
       elif period == "mtd":
           start = end.replace(day=1)
       elif period == "ytd":
           start = end.replace(month=1, day=1)
       else:
           years = {"1y": 1, "5y": 5}[period]
           start = (pd.Timestamp(end) - pd.DateOffset(years=years)).date()
       return start, end

   def content_key(value):
       return hashlib.sha256(json.dumps(
           value, sort_keys=True, separators=(",", ":"), allow_nan=False
       ).encode("utf-8")).hexdigest()
   ```

3. **KEEP** all Source Types in an imported Quick Risk identity. A Risk Delta identity can contain contributions from several source products. Do not change `source_types` to its first item to make Market validation pass.
4. **KEEP** the exact imported Risk `filter_view` in a separate small draft field. Preserve it when selecting another Risk series, changing dates, switching Risk/Market/Both, or changing a companion. Show its caption throughout. Only the explicit **Clear Risk scope** button may replace it with `None`.
5. **ADD** the companion picker only in Both. If `unambiguous_raw_companion()` returns one exact key, preselect it; keep the picker editable. For reported Risk, multiple raw underlyings, multiple Source Types, no match or multiple matches, leave it blank and show **Choose the Market series to compare**. Do not silently pick the first quote.
6. The explicit companion list contains the opposite kind, with full labels. It is a deliberate comparison, not proof that this quote generated all selected Risk. Show **Selected Market companion; quote values are not portfolio weighted**. If identities differ in product, Greek or axes, show **Different series: dates are linked; axes and units are independent**. This allows useful comparisons without inventing a mapping service.
7. A Market-origin Both selection works symmetrically: retain the exact Market identity, require/select its Risk companion, and show that directly selected Risk initially uses all archived positions. A Market handoff must never inherit Risk filters.
8. If the primary key changes to a different identity, clear the previous companion before trying the exact raw match. Do not attach an old companion to a newly chosen primary without an explicit new selection.

### Outcome check for D02

Run `check_syntax(["cube/pages/data/s04_workspace.py"])` and confirm Syntax OK. This checks only the helper source syntax. After adding the reducer in D05, run the complete selection examples in D09 to check reported/raw pairing and preserved Risk scope.

<a id="job-d03"></a>
## Job D03 — Give paired queries one calendar window and one budget

**Result:** Both reads bounded Risk and Market results independently and displays them for the same requested period.

1. Open `cube/history/s06_repository.py::ArchiveHistoryRepository.read`. Locate the block starting with `try:` followed by `available_dates = tuple(` and ending immediately before `dates = resolve_actual_period_dates(available_dates, query)`.
2. **EXTRACT**, without changing its SQL arguments or legacy exception condition, that block into a new method `_available_dates_and_legacy(self, handoff)`. At its start assign `identity = handoff.identity`, `generation = self.generation()` and `date_column = RISK_DATE if handoff.kind == "risk" else MARKET_DATE`. At its end return `(available_dates, legacy_raw)`.
3. In `read`, **REPLACE** the extracted block with:

   ```python
   available_dates, legacy_raw = self._available_dates_and_legacy(handoff)
   ```

   Keep `handoff`, `identity`, `generation` and `date_column` assignments already used by the rest of `read`.
4. **ADD** this method directly after `_available_dates_and_legacy`:

   ```python
   def available_dates(self, handoff: HistoryHandoff) -> tuple[date, ...]:
       if not isinstance(handoff, HistoryHandoff):
           raise HistoryValidationError("A typed history handoff is required")
       available, _legacy_rows = self._available_dates_and_legacy(handoff)
       return available
   ```

   Add `from datetime import date` if not already present. This method uses the existing narrow date query for current archives. The existing bounded legacy fallback remains available; do not add an unbounded whole-archive scan.
5. Change `read(self, query: HistoryQuery)` to `read(self, query: HistoryQuery, *, max_cells: int | None = None)`. Immediately after validating `query`, add:

   ```python
   if max_cells is not None and (
       isinstance(max_cells, bool) or not isinstance(max_cells, int) or max_cells < 1
   ):
       raise HistoryValidationError("Remaining history cell budget must be positive")
   effective_max_cells = self._max_cells if max_cells is None else min(
       self._max_cells, max_cells
   )
   ```

6. Inside this method only, **REPLACE** the previously added canonical preallocation threshold `self._max_cells` with `effective_max_cells`. Also replace `self._max_cells` in the final `len(values)` guard and its error text. Do not replace the constructor field, defaults or other methods. Both checks must use the same request-local cap. Do not temporarily assign a smaller value to `self._max_cells`; concurrent users share the repository.
7. In `cube/pages/data/s03_callbacks.py`, **KEEP** `serialize_history_bundle`, `_frame_payload`, `_json_value`, `load_archive_catalog` and `poll_archive_generation`. Add `HistoryIdentityCatalog` to the existing `from cube.history import (...)` list if absent. Add `from uuid import uuid4` if absent. Add this import block exactly once:

   ```python
   from .s04_workspace import (
       QUICK_KEY, catalog_entries, common_bounds, content_key,
       entry_label, opposite_options, parse_workspace_request,
       reduce_workspace_draft, retain_exact, scope_caption,
       series_options, unambiguous_raw_companion, workspace_request,
   )
   ```

   The existing callback module already imports `hashlib`, `json`, `replace`, `HistoryHandoff`, `HistoryQuery`, `HistoryValidationError`, the two history budgets, `Mapping`, `no_update` and `ctx`; keep one import for each. After replacing the old registrations, remove only imported names with no remaining references; do not remove names still used by the retained public helpers.
8. **ADD** `query_workspace_bundle(repository, raw_request, cache_state, reset_generation)` before `register_callbacks`. Implement it in exactly this order:
   1. Validate `raw_request` with `parse_workspace_request`.
   2. Require an integer, nonnegative reset generation, rejecting booleans. Require every selected handoff's `reset_generation` to equal it. Reject before any date/row read if stale.
   3. Require `cache_state` to be a mapping containing a nonempty generation. If unavailable, return `(None, "Preparing archive choices…")`.
   4. Save `start_generation = repository.generation()`. Require it to equal `cache_state["generation"]` before reading.
   5. Call `repository.available_dates(handoff)` once for each selected kind. Pass the resulting dictionary to `common_bounds`. This gives one shared start/end based on actual dates, including leap years. Do not independently resolve WTD/MTD for two different latest observation dates.
   6. If both bounds are `None`, return an empty workspace envelope with the validated request, no panel values, empty dates, current generation/reset and a **No archived observations** status. Do not invent a date window.
   7. Initialize `remaining = HISTORY_CANONICAL_CELL_BUDGET`, `panels = {}`, `raw_count = 0`. Process `risk` first when selected, then `market`. If only Market is selected, process it once.
   8. Before each `read`, require `remaining > 0`. Construct `HistoryQuery(handoff, period="custom", start_date=start, end_date=end)`. Read with `repository.read(query, max_cells=remaining)`. Both preallocation and postallocation checks now use the remaining budget.
   9. Require `bundle.generation == start_generation`. Add `len(bundle.raw_rows)` to `raw_count`; reject if the combined count exceeds `HISTORY_RAW_ROW_BUDGET`. Serialize this bounded bundle, subtract `len(bundle.values)` from `remaining`, and save the payload under its actual kind. Do not save `raw_rows`, a second DataFrame copy, or the complete `HistoryBundle` in a page/global cache. Release the local bundle before reading the next panel.
   10. Add a `unit_label` to each serialized panel. Read the Market convention from `handoff.identity.product_spec.market_unit` for its validated single-source Market identity. Set the Risk label to **Risk (source units)**; do not guess currency, bp or percent. The ProductSpec field is a string with values `pips`, `outright`, `vol_points` or `bp`. Preserve it as `market_convention` metadata. For an archived `Current` quote use **Official (stored quote units)** unless the connector explicitly establishes the stored quote unit; a move convention such as pips does not justify relabeling an outright rate. Never multiply quote levels merely to match a label, and never relabel raw quote values as Risk units.
   11. Require `repository.generation() == start_generation` after all reads. If generation changed between the two reads, reject the whole result with **Archive changed during load; press Load again**. Do not publish one old and one new panel.
   12. Set the envelope's dates to the sorted union of the panels' actual observation dates. Keep each panel's original dates and canonical values unchanged. Do not create a union-date × union-tenor Cartesian product on the server.
   13. Build an envelope with exactly these fields: `schema_version: 1`, `request: raw_request`, `display_mode`, `panels`, `dates`, `resolved_start`, `resolved_end`, `generation`, `reset_generation`, `key`. Compute `key` from request identity/scope/period plus generation and panel keys using `content_key`; include both panel keys. Missing panels are `null` or omitted consistently; the renderer uses `panels.get(kind)` semantics.
   14. Serialize the envelope with `json.dumps(..., allow_nan=False, separators=(",", ":"))`. Reject if UTF-8 size exceeds a named `DATA_WORKSPACE_BYTE_BUDGET = 16 * 1024 * 1024`; do not return a truncated payload. Use the same constant in the notebook check below. Explain the narrower-period/selection recovery in the visible error.
   15. Return the complete envelope and a caption giving requested period, resolved dates and per-panel date/cell counts. This is the only envelope passed to the browser.
9. **KEEP** the original single-query functions as public helpers if existing non-UI callers import them. **REMOVE** their use from the Data page's registered `load_history` callback in D06. The UI must have exactly one workspace loader.
10. The combined raw-row and byte checks occur before publication but after each individual bounded read. They do not replace the earlier per-read SQL/raw/allocation guards. The canonical allocation cap is additionally enforced before the second panel is built. Document measured peak memory for Both in D10; do not describe a postserialization byte check as a complete preallocation memory limit.

### Outcome check for D03

Run `check_syntax(["cube/history/s06_repository.py", "cube/pages/data/s03_callbacks.py"])`. Check that the preallocation and postallocation conditions both use the request-local effective cell cap. Complete the common-date, reset and missing-observation checks in D09–D10 before accepting paired loading.

<a id="job-d04"></a>
## Job D04 — Replace the Data layout without orphaned component IDs

**Result:** one compact selection area, two coordinated result panels only when Both is selected, and the same button family as Stock/P&L.

1. In `cube/pages/data/s02_view.py`, **KEEP** `PERIOD_OPTIONS`, `empty_history_figure`, the `build_data_page` signature, root `data-page` ID and `data-page` class. Keep construction lazy: no repository or connector call in this file.
2. **REPLACE** the children of `build_data_page` with the following ordered component groups. Create every listed ID once, even when hidden; callback targets must exist throughout this page's lifetime.

| Order | Component and exact IDs | Initial configuration |
|---|---|---|
| 1 | `dcc.Store` IDs `data-history-catalog-store`, `data-history-bundle-store`, `data-workspace-draft-store` | Memory stores; first two `None`; draft schema described in D05 |
| 2 | Existing `data-history-cache-state-store`, `data-player-state-store`, `data-player-visibility-store` | Keep current initial data and memory storage |
| 3 | Existing `data-history-generation-interval`, `data-player-interval` | Keep 60,000 ms generation polling and 900 ms player interval, player disabled |
| 4 | Header | H1 **Data**; one sentence: **Explore Risk and Market for one selected period.** |
| 5 | `dcc.RadioItems(id="data-display-mode")` | Risk/risk, Market/market, Both/both; value risk; `inline=True`, class `cube-segments` |
| 6 | Searchable `dcc.Dropdown(id="data-series-picker")` | Empty options, value None, `clearable=True`, placeholder **Choose a series**; full labels from D02 |
| 7 | `html.Div(id="data-companion-control")` containing label `data-companion-label` and searchable `data-companion-picker` | Hidden initially; empty options and value None; label updates to required opposite kind |
| 8 | `data-period`, `data-custom-range-control`, `data-custom-range` | Keep existing periods, DatePickerRange settings and IDs; change period class to `cube-segments`; custom control hidden |
| 9 | `data-load-history-button` | Text **Load**, initially disabled; place after period/custom dates |
| 10 | `data-draft-status`, `data-identity-breadcrumb`, `data-history-status` | Small status text; aria-live polite; draft message separate from loaded caption |
| 11 | `html.Details` **Risk scope and advanced identity** | `data-risk-scope-caption`; button `data-clear-risk-scope` with n_clicks=0; text **Market quotes do not use Portfolio filters** |
| 12 | `dcc.RadioItems(id="data-view-mode")` | Snapshot/snapshot, Over time/over_time, Compare/compare; value snapshot; `inline=True`, class `cube-segments` |
| 13 | `data-history-comparison-dates` containing existing `data-history-date-a` and `data-history-date-b` dropdowns | Hidden outside Compare; keep searchable=False; no arbitrary-date nearest-match fallback |
| 14 | Existing shared player `data-player-controls` | Keep button, slider, date pill and mode pill IDs/classes from the current layout |
| 15 | Container `data-chart-grid` with `data-risk-panel` and `data-market-panel` | Each contains a heading, independent Graph and contextual controls defined below |
| 16 | `html.Details` with summary **Show values** | Wrap each DataTable in `html.Div(id="data-risk-values-panel")` / `html.Div(id="data-market-values-panel")`; table IDs are `data-risk-values-table` / `data-market-values-table`, page_size=12, native page/sort on bounded selected-view rows |
| 17 | `html.Details` with summary **Diagnostics** | Move `data-catalog-status`, `data-clear-status` and technical generation/order text here; retain both existing status IDs |

3. Build each panel with a small local helper `history_panel(kind)`; call it for `"risk"` and `"market"`. The helper returns these components in order:
   1. `html.H2("Risk" if kind == "risk" else "Market")`.
   2. `html.Div(id=f"data-{kind}-caption")` for exact identity, units and missing-date status.
   3. A two-control container `id=f"data-{kind}-tenor-controls"` containing wrapper IDs `data-{kind}-tenor-0-control` and `data-{kind}-tenor-1-control`, with dropdowns `data-{kind}-tenor-0` and `data-{kind}-tenor-1`, each initially empty. Create label IDs `data-{kind}-tenor-label-0` and `data-{kind}-tenor-label-1`; their children come from the corresponding serialized axis column. Show only needed controls in Over time; two axes require both choices for an exact-cell timeline.
   4. `html.Details` with summary **Advanced chart options**, containing `dcc.Dropdown(id=f"data-{kind}-projection", options=[{"label": "Use main view", "value": "auto"}], value="auto", clearable=False)` and `dcc.Dropdown(id=f"data-{kind}-advanced-slice", options=[], value=None)`. These preserve the existing advanced projections; show the slice control only when its projection needs it.
   5. `dcc.Loading(dcc.Graph(id=f"data-{kind}-chart", figure=empty_history_figure("Choose a series and press Load"), config={"displaylogo": False, "responsive": True}))`.
4. Remove the old sole `data-history-chart` and sole `data-selected-table`; they are replaced by the two kind-specific IDs. Remove old `data-history-kind-tabs`, `data-identity-mode`, `data-risk-type`, `data-risk-greek`, `data-underlying`, `data-history-projection`, `data-history-slice`, `data-history-slice-label`, `data-history-slice-control` and `data-history-projection-controls`. D06 removes their callback registrations at the same time.
5. Do not add shell stores inside this layout. In `cube/app/s07_factory.py`, keep the existing single `data-history-handoff-store` (session), `data-history-handoff-consumed-store` (session), `data-history-request-store` (memory), and `data-route-location`. Their IDs and route-prefix behavior stay unchanged. Only the small request store's data schema changes to the workspace envelope.
6. Keep `assets/s13_risk.js`'s existing visibility handler for `data-player-visibility-store`. Keep the wheel handler in `assets/s09_playback.js`; its existing slider/control IDs still exist. Do not register a second global wheel/visibility handler.

### Outcome check for D04

Run `check_syntax(["cube/pages/data/s02_view.py"])`. Check each listed ID appears exactly once in the new layout or shared shell. Do not launch this intermediate layout with its old registrations; finish D06–D08 and then use D09–D10.

<a id="job-d05"></a>
## Job D05 — Implement the draft-to-loaded state transition

**Result:** editing controls does not relabel an old chart, Quick navigation preserves exact scope, and Both requires valid selections before Load.

1. Use this initial JSON-safe draft, created in `data-workspace-draft-store`:

   ```python
   {
       "schema_version": 1,
       "display_mode": "risk",
       "primary_key": None,
       "primary_kind": None,
       "companion_key": None,
       "risk": None,
       "market": None,
       "risk_scope": None,
       "quick_nonce": None,
       "catalog_generation": None,
   }
   ```

   `risk` and `market` contain `HistoryHandoff.to_mapping()` values or None. They never contain DataFrames or chart arrays. Treat store content as untrusted input: parse the handoffs and scope before using them.
2. **ADD** a pure `reduce_workspace_draft(...)` helper in `s04_workspace.py`. Inputs are an explicit event name, the previous draft, catalog, raw Quick envelope, display mode, primary key, companion key and reset generation. Return a new draft, picker options/values, companion label/visibility, valid-selection flag and status. Implement the transitions in this exact priority order:

| Event | Exact transition |
|---|---|
| Fresh Quick nonce | Parse `raw_quick["handoff"]`; copy its entire identity and Risk scope; set mode to its kind; set primary key to matching catalog key or `QUICK_KEY`; clear companion; retain the Quick mapping even if the archive catalog has no matching key; set `quick_nonce`; do not select a substitute identity |
| Initial page mount | If a valid loaded workspace request exists, reconstruct the draft from its handoffs/mode and current catalog, preserving its Risk scope and exact missing-catalog Quick identity; otherwise retain a valid draft or use the initial draft |
| Cache reset | Update the draft handoffs' reset generations using `dataclasses.replace`; preserve identity, scope and dates; invalidate the loaded request in D06 until Load is pressed |
| Primary picker change | Resolve the exact selected catalog key; apply the stored Risk scope only for Risk; set it as primary, clear companion and the opposite selected identity; in Both try only the unambiguous raw match; blank selection leaves Load disabled |
| Mode change | Retain the existing primary if allowed by the mode; for Risk/Market switch to that kind's previously chosen handoff when available, otherwise clear the picker; entering Both preserves the current primary and resolves/requires a companion; do not pick the first series |
| Companion change | Require Both and an opposite-kind entry. Resolve it exactly. Apply Risk scope only when companion kind is Risk. A blank companion leaves the primary selected and disables Load |
| Clear Risk scope | Set scope to None and replace any Risk handoff filter_view with None; retain all identities and period controls; mark the draft changed |
| Catalog generation change | Refresh choices. Keep valid exact keys. Preserve an imported Quick identity with a labeled virtual option. For a directly selected entry no longer present, clear that selection and show **This series is no longer available; choose another**; do not silently replace it |

3. Append this complete reducer to `cube/pages/data/s04_workspace.py`. It implements the transitions above. The callback passes event names `initial`, `handoff`, `catalog`, `mode`, `primary`, `companion`, `clear_scope`, `reset`, `load`, or `dates`; arbitrary names are rejected.

   ```python
   def reduce_workspace_draft(
       event, previous, raw_catalog, raw_quick, display_mode,
       primary_key, companion_key, reset_generation,
       loaded_request=None, consumed_nonce=None,
   ):
       allowed_events = {"initial", "handoff", "catalog", "mode", "primary",
                         "companion", "clear_scope", "reset", "load", "dates"}
       if event not in allowed_events:
           raise HistoryValidationError("Unknown Data selection event")
       if type(reset_generation) is not int or reset_generation < 0:
           raise HistoryValidationError("Invalid reset generation")
       initial = {
           "schema_version": 1, "display_mode": "risk",
           "primary_key": None, "primary_kind": None, "companion_key": None,
           "risk": None, "market": None, "risk_scope": None,
           "quick_nonce": None, "catalog_generation": None,
       }
       draft = dict(initial)
       if isinstance(previous, Mapping) and previous.get("schema_version") == 1:
           draft.update({key: previous[key] for key in initial if key in previous})
       entries = catalog_entries(raw_catalog) if raw_catalog is not None else ()
       by_key = {entry.key: entry for entry in entries}
       parsed = {}
       for kind in ("risk", "market"):
           raw = draft[kind]
           if raw is not None:
               handoff = HistoryHandoff.from_mapping(raw)
               if handoff.kind != kind:
                   raise HistoryValidationError("Draft kind does not match its identity")
               parsed[kind] = handoff
       if draft["risk_scope"] is not None:
           RiskFilterView.from_mapping(draft["risk_scope"])
       status = ""

       def catalog_key(handoff):
           matches = [entry.key for entry in entries
                      if entry.kind == handoff.kind and entry.identity == handoff.identity]
           return matches[0] if len(matches) == 1 else None

       def resolve(key):
           if key == QUICK_KEY:
               if not isinstance(raw_quick, Mapping):
                   raise HistoryValidationError("The Quick selection is unavailable")
               selected = HistoryHandoff.from_mapping(raw_quick.get("handoff"))
               selected = replace(selected, reset_generation=reset_generation)
               if selected.kind == "risk":
                   selected = replace(selected, filter_view=(
                       RiskFilterView.from_mapping(draft["risk_scope"])
                       if draft["risk_scope"] is not None else None))
               return selected
           if key not in by_key:
               raise HistoryValidationError("Choose an available exact series")
           return handoff_from_entry(raw_catalog, key, reset_generation,
                                     draft["risk_scope"])

       def set_primary(key):
           if key is None:
               draft["primary_key"] = draft["primary_kind"] = None
               draft["companion_key"] = None
               parsed.clear()
               return
           selected = resolve(key)
           if draft["display_mode"] != "both" and selected.kind != draft["display_mode"]:
               raise HistoryValidationError("Series does not match the selected display mode")
           draft["primary_key"], draft["primary_kind"] = key, selected.kind
           draft["companion_key"] = None
           parsed.clear()
           parsed[selected.kind] = selected

       raw_nonce = (str(raw_quick.get("nonce") or "")
                    if isinstance(raw_quick, Mapping) else "")
       fresh_quick = bool(raw_nonce and raw_nonce != str(consumed_nonce or "")
                          and raw_nonce != str(draft["quick_nonce"] or ""))
       if fresh_quick:
           handoff = HistoryHandoff.from_mapping(raw_quick.get("handoff"))
           # A stale Quick handoff is not made current by changing its number.
           if handoff.reset_generation != reset_generation:
               raise HistoryValidationError("Quick selection predates Clear Cache; reopen it")
           draft["display_mode"] = handoff.kind
           draft["risk_scope"] = (handoff.filter_view.to_mapping()
                                   if handoff.kind == "risk" and handoff.filter_view else None)
           draft["quick_nonce"] = raw_nonce
           set_primary(catalog_key(handoff) or QUICK_KEY)
           # Keep the original exact source revision/snapshot and scoped identity.
           parsed[handoff.kind] = handoff
       elif event == "initial" and not parsed and loaded_request is not None:
           parsed = parse_workspace_request(loaded_request)
           draft["display_mode"] = loaded_request["display_mode"]
           primary_kind = "risk" if "risk" in parsed else "market"
           draft["primary_kind"] = primary_kind
           risk = parsed.get("risk")
           draft["risk_scope"] = (risk.filter_view.to_mapping()
                                   if risk is not None and risk.filter_view else None)
           primary = parsed[primary_kind]
           draft["primary_key"] = catalog_key(primary)
           if draft["primary_key"] is None and isinstance(raw_quick, Mapping):
               quick = HistoryHandoff.from_mapping(raw_quick.get("handoff"))
               if quick.kind == primary_kind and quick.identity == primary.identity:
                   draft["primary_key"] = QUICK_KEY
           opposite = "market" if primary_kind == "risk" else "risk"
           draft["companion_key"] = catalog_key(parsed[opposite]) if opposite in parsed else None
       elif event == "reset":
           parsed = {kind: replace(value, reset_generation=reset_generation)
                     for kind, value in parsed.items()}
           status = "Cache cleared — press Load to reload this selection"
       elif event == "primary":
           set_primary(primary_key)
       elif event == "mode":
           if display_mode not in DISPLAY_MODES:
               raise HistoryValidationError("Choose Risk, Market or Both")
           draft["display_mode"] = display_mode
           if display_mode != "both":
               selected = parsed.get(display_mode)
               draft["primary_kind"] = display_mode if selected is not None else None
               draft["primary_key"] = catalog_key(selected) if selected is not None else None
               if selected is not None and draft["primary_key"] is None:
                   if isinstance(raw_quick, Mapping):
                       quick = HistoryHandoff.from_mapping(raw_quick.get("handoff"))
                       if quick.kind == selected.kind and quick.identity == selected.identity:
                           draft["primary_key"] = QUICK_KEY
               draft["companion_key"] = None
       elif event == "companion":
           if draft["display_mode"] != "both" or draft["primary_kind"] not in parsed:
               raise HistoryValidationError("Choose the primary series before its companion")
           opposite = "market" if draft["primary_kind"] == "risk" else "risk"
           if companion_key is None:
               parsed.pop(opposite, None)
               draft["companion_key"] = None
           else:
               selected = resolve(companion_key)
               if selected.kind != opposite:
                   raise HistoryValidationError("The companion must be the opposite kind")
               parsed[opposite] = selected
               draft["companion_key"] = companion_key
       elif event == "clear_scope":
           draft["risk_scope"] = None
           if "risk" in parsed:
               parsed["risk"] = replace(parsed["risk"], filter_view=None)
       if raw_catalog is not None and event in {"initial", "catalog"}:
           for key_name, kind in (("primary_key", draft["primary_kind"]),
                                 ("companion_key", "market" if draft["primary_kind"] == "risk" else "risk")):
               key = draft[key_name]
               if key is None and kind in parsed:
                   draft[key_name] = catalog_key(parsed[kind])
               elif key is not None and key != QUICK_KEY and key not in by_key:
                   draft[key_name] = None
                   parsed.pop(kind, None)
                   status = "This series is no longer available; choose another"
       primary = parsed.get(draft["primary_kind"])
       if draft["display_mode"] == "both" and primary is not None:
           opposite = "market" if primary.kind == "risk" else "risk"
           # Never reselect a companion immediately after the user clears it.
           if (opposite not in parsed and raw_catalog is not None
                   and (fresh_quick or event in {"primary", "mode", "initial"})):
               automatic = unambiguous_raw_companion(raw_catalog, primary)
               if automatic is not None:
                   parsed[opposite] = resolve(automatic)
                   draft["companion_key"] = automatic
       else:
           opposite = "market" if draft["primary_kind"] == "risk" else "risk"
       options = series_options(raw_catalog, draft["display_mode"]) if raw_catalog is not None else []
       if draft["primary_key"] == QUICK_KEY and primary is not None:
           label = (f"{primary.kind.title()} · {primary.identity.risk_type} · "
                    f"{primary.identity.risk_greek} · {primary.identity.underlying} · "
                    f"{primary.identity.identity_mode} · {', '.join(primary.identity.source_types)} · from Quick")
           options.append({"label": label, "value": QUICK_KEY})
       companions = (opposite_options(raw_catalog, primary)
                     if raw_catalog is not None and primary is not None
                     and draft["display_mode"] == "both" else [])
       required = {"risk", "market"} if draft["display_mode"] == "both" else {draft["display_mode"]}
       valid = (draft["primary_key"] is not None and required.issubset(parsed)
                and all(parsed[kind].reset_generation == reset_generation for kind in required)
                and (draft["display_mode"] != "both" or draft["companion_key"] is not None))
       if not valid and not status:
           status = (f"Choose the {opposite.title()} series to compare"
                     if draft["display_mode"] == "both" and primary is not None
                     else "Choose an exact series")
       for kind in ("risk", "market"):
           draft[kind] = parsed[kind].to_mapping() if kind in parsed else None
       draft["catalog_generation"] = raw_catalog.get("generation") if isinstance(raw_catalog, Mapping) else None
       return {"draft": draft, "options": options, "companion_options": companions,
               "companion_label": f"{opposite.title()} series to compare",
               "companion_hidden": draft["display_mode"] != "both",
               "valid": valid, "status": status, "fresh_quick": fresh_quick}
   ```

   Multiple Inputs can change during page hydration. Use `ctx.triggered_prop_ids` to detect the set, not only whichever property happens to be first. Select events in this precedence: an unconsumed fresh Quick nonce; reset; initial hydration when no valid previous draft exists (reconstruct the loaded request before interpreting empty layout defaults); a real Load click; Clear scope; explicit mode change; explicit primary change; explicit companion change; catalog change; period/date change; initial mount. Call the reducer once for that effective event. On catalog hydration, pass the draft's current values rather than empty layout defaults. A zero Load click count is not a Load event. For values emitted by the callback itself, compare against the previous effective draft; equal values are not new selection events and must return `no_update` for the request. This prevents an imported identity from being cleared by initial empty picker values or its own callback response.

4. For a virtual Quick entry, append a single option labeled with the imported full identity and **from Quick Risk** or **from Quick Market**, value `QUICK_KEY`. Resolve it from the stored Quick mapping only. Do not call `catalog.resolve(QUICK_KEY)`.
5. The same identity can be either primary or companion. Keep `risk` and `market` in fixed named fields independent of their UI position. Rendering always uses those named fields.
6. The valid-selection flag is true only when the current mode's required handoffs are present, typed, correctly kinded, reset-current, and a direct primary/companion selection still resolves. For Both, one Risk plus one Market is required. Validate the dates independently when Load is pressed.
7. Keep the loaded caption derived solely from `data-history-bundle-store.request` plus resolved dates. Never derive a chart caption from an edited picker. While controls differ from the loaded request, show **Selection changed — press Load** in `data-draft-status`; do not relabel the old values.
8. Preserve draft-only editing: primary, companion, period and custom-date changes do not query archives. Quick **Open in Data** loads its single exact incoming kind automatically, as before; selecting Both afterwards waits for a valid pair and Load.

### Outcome check for D05

Run `check_syntax(["cube/pages/data/s04_workspace.py"])` and the inline selection example in D09. Expected: a reported Risk identity requires an explicit Market companion and preserves its full Risk scope after pairing. Complete D06 before using the new state in the app.

<a id="job-d06"></a>
## Job D06 — Replace callback registrations and keep one owner per output

1. In `cube/pages/data/s03_callbacks.py::register_callbacks`, **REMOVE the whole decorated definitions** of `sync_quick_handoff`, `configure_identity_mode`, `configure_request`, `choose_risk_type`, `choose_risk_greek`, `choose_underlying`, `choose_history_request` and `load_history`. Locate actual `def` names with `show_symbol`/search before removing; do not remove a neighboring callback's decorator.
2. **REMOVE** the three existing clientside callback registrations bound to `dataProjectionBase`, `dataProjectionSlice` and `dataPlayback`. Keep their JavaScript implementations where D07 reuses them as pure rendering helpers; they no longer own the Data UI outputs.
3. **KEEP** `refresh_archive_catalog` (same catalog/status outputs), `show_custom_range` (same hidden property) and `refresh_archive_generation` (same cache-state/clear-status outputs). For generation refresh, its request input is now the workspace request; `poll_archive_generation` ignores that payload and continues polling normally.
4. **ADD one server callback** named `edit_workspace` with these Inputs: `data-history-handoff-store.data`, `data-history-catalog-store.data`, `data-display-mode.value`, `data-series-picker.value`, `data-companion-picker.value`, `data-clear-risk-scope.n_clicks`, `data-load-history-button.n_clicks`, `reset-generation-store.data`, `data-period.value`, `data-custom-range.start_date`, `data-custom-range.end_date`. Use State for `data-workspace-draft-store.data`, `data-history-handoff-consumed-store.data`, `data-history-request-store.data`. Period/date Inputs update the dirty-selection caption only; they must not create a new archive request until Load. Use `allow_optional=True` for page-only components when the callback can fire while another route is mounted, following the existing callback convention.
5. Give `edit_workspace` the following Outputs, in exactly this return order:

   ```python
   Output("data-workspace-draft-store", "data"),
   Output("data-display-mode", "value"),
   Output("data-series-picker", "options"),
   Output("data-series-picker", "value"),
   Output("data-companion-picker", "options"),
   Output("data-companion-picker", "value"),
   Output("data-companion-label", "children"),
   Output("data-companion-control", "hidden"),
   Output("data-load-history-button", "disabled"),
   Output("data-risk-scope-caption", "children"),
   Output("data-draft-status", "children"),
   Output("data-history-request-store", "data"),
   Output("data-history-handoff-consumed-store", "data"),
   ```

6. Implement `edit_workspace` as follows:
   1. Read `ctx.triggered_id`; map it to the D05 event table. When there is an unconsumed valid Quick nonce on first mount, handle it before catalog/selection initialization.
   2. If page controls are absent and there is no new Quick event, return 13 `no_update` values. Do not clear shell state merely because another page is mounted.
   3. For an already consumed nonce, do not reload or reset selection. A freshly mounted page reconstructs its controls from the loaded request/draft, not by replaying consumed Quick navigation.
   4. Call the pure reducer and construct the first eleven outputs from its result.
   5. On an ordinary draft edit, return `no_update` for the request and consumed nonce.
   6. On Load with valid required handoffs, call `workspace_request(...)` using all current period/date Input values. Use a fresh `uuid4().hex` request ID. Return the immutable request in output 12 and `no_update` in output 13.
   7. On fresh Quick navigation, call `workspace_request` for the incoming kind, using the current period/date values when mounted and `period="all"` otherwise. Put its nonce into consumed output only after the request has validated. If custom dates are incomplete, show the validation message, do not consume the nonce, and leave the imported draft available for correction/Load.
   8. On reset, return `None` for the request so playback stops and old data cannot appear current. Keep the draft's exact selection with the new reset generation; show **Cache cleared — press Load to reload this selection**.
   9. Catch `HistoryValidationError`, `TypeError`, `ValueError`, `LookupError` at the UI boundary. Show a concise error in draft status, disable Load only for invalid identities, and return `no_update` for the last valid request unless reset intentionally invalidates it. Do not hide an error by selecting a default identity.
7. Because this one callback reads and writes the picker values, it is a single callback with circular component values, not a cycle across several callbacks. Return the same effective values when nothing changed. Do not split its picker writes between callbacks or add `allow_duplicate=True` to work around ownership mistakes.
8. **ADD one server callback** `load_workspace`, with Inputs `data-history-request-store.data`, `data-history-cache-state-store.data`, `reset-generation-store.data`; Outputs `data-history-bundle-store.data`, `data-history-status.children`, `data-identity-breadcrumb.children`. With no request, return `None`, **Choose a series and press Load**, and **No loaded selection**. Otherwise call `query_workspace_bundle`, format its loaded caption from that envelope, and return all three outputs together. On validation/read failure, return `None`, the explicit error and **No current loaded result**; do not keep a stale chart under the new selection's heading. Use the `running` callback argument only for button text (**Loading…** then **Load**), not its disabled property owned by `edit_workspace`.
9. **ADD the two clientside callbacks** specified in D07: `workspaceProjectionControls` owns advanced/tenor choices and their visibility; `workspacePlayback` owns figures, values, player and Compare dates. Do not retain any old callback that also writes those outputs.
10. Keep `cube/pages/risk/s04_handoff.py::build_history_handoff`, `_handoff_payload` and `open_in_data` contracts. Their session payload remains `{handoff, nonce}` and destination remains `data_href`. Update only visible text **Opening exact history…** to **Opening Data…** if desired. Do not construct Both in the Risk-page handoff writer; the Data mode control owns that choice.
11. At the end of this job, search Python files for every removed ID from D04. There must be no remaining callback Input/State/Output targeting one. Search for `Output("data-history-request-store"` and confirm only `edit_workspace` writes it. Search for each player output and confirm only `workspacePlayback` writes it. Confirm that no duplicate registrations remain; do not retain old callbacks merely to keep removed component IDs present.

### Outcome check for D06

Run `check_syntax(["cube/pages/data/s03_callbacks.py", "cube/pages/risk/s04_handoff.py"])`. Check removed IDs have no registered targets and each output listed above has one owner. After D07, use the running-preview dependency check and browser flows in the final verification job.

<a id="job-d07"></a>
## Job D07 — Give both panels one browser-local player and matching views

**Result:** Play/Pause and dragging the shared slider never reread archives. Risk and Market advance to the same calendar date, with honest gaps.

1. Edit `assets/s09_playback.js` inside its existing outer `(() => { ... })()` function. **KEEP** `dataAxes`, `dataDates`, `dataLabels`, `finiteNumber`, `dataHistoryPointMap`, `dataHistoryPoint`, `dataDifference`, `categoricalAxis`, `dataSliderMarks`, the existing advanced figure helpers and wheel handler.
2. **ADD** these four pure helpers immediately before the current `const dataPlayback = (` declaration:

   ```javascript
   const workspaceKinds = (bundle) => bundle?.display_mode === "both"
     ? ["risk", "market"] : [bundle?.display_mode].filter(Boolean);

   const workspaceAdvancedSelection = (panel, projection, slice) => {
     const allowed = dataProjectionOptions(dataAxes(panel).length).map((item) => item.value);
     if (!allowed.includes(projection)) {
       throw new Error("This advanced projection is unavailable for the selected series");
     }
     if (panel?.kind === "market" && slice === SUM_SLICE) {
       throw new Error("Market quote levels cannot use Sum; choose an exact tenor slice");
     }
     const definition = dataSliceDefinition(panel, projection);
     const values = definition.values.filter((value) =>
       panel?.kind !== "market" || value !== SUM_SLICE);
     if (values.length && !values.includes(slice)) {
       throw new Error("Choose an exact available slice for this advanced projection");
     }
     return {projection, slice: values.length ? slice : null};
   };

   const workspaceDateRows = (panel, dates, view, selectedDate, dateA, dateB, tenors) => {
     if (!panel) return [];
     const axes = dataAxes(panel);
     const metric = String(panel.metric_column);
     const dateColumn = String(panel.date_column);
     const records = Array.isArray(panel.values) ? panel.values : [];
     const pointMap = dataHistoryPointMap(
       records, [dateColumn, ...axes.map((axis) => axis.column)], metric,
     );
     const tuples = axes.length === 0 ? [[]] : axes.length === 1
       ? dataLabels(axes[0]).map((first) => [first])
       : dataLabels(axes[0]).flatMap((first) =>
           dataLabels(axes[1]).map((second) => [first, second]));
     const base = (tuple) => Object.fromEntries(
       axes.map((axis, index) => [axis.column, tuple[index]]),
     );
     if (view === "over_time") {
       const tuple = axes.map((_axis, index) => tenors[index]);
       if (tuple.some((value) => value == null)) return [];
       return dates.map((day) => ({
         Date: day, ...base(tuple),
         [metric]: dataHistoryPoint(pointMap, [day, ...tuple]),
       }));
     }
     if (view === "compare") {
       return tuples.map((tuple) => {
         const a = dataHistoryPoint(pointMap, [dateA, ...tuple]);
         const b = dataHistoryPoint(pointMap, [dateB, ...tuple]);
         return {...base(tuple), "Date A": dateA, "Value A": a,
           "Date B": dateB, "Value B": b, "Change B−A": dataDifference(a, b)};
       });
     }
     return tuples.map((tuple) => ({
       Date: selectedDate, ...base(tuple),
       [metric]: dataHistoryPoint(pointMap, [selectedDate, ...tuple]),
     }));
   };

   const workspaceMainFigure = (panel, dates, view, day, dateA, dateB, tenors, key) => {
     if (!panel) return dataHistoryEmptyFigure("No series selected for this panel.");
     const axes = dataAxes(panel);
     const metric = String(panel.metric_column);
     const unit = String(panel.unit_label || metric);
     const rows = workspaceDateRows(panel, dates, view, day, dateA, dateB, tenors);
     const common = {autosize: true, paper_bgcolor: "#ffffff", plot_bgcolor: "#ffffff",
       margin: {l: 64, r: 28, t: 60, b: 72}, uirevision: key,
       hoverlabel: {namelength: -1}, legend: {orientation: "h"}};
     let traces = [], layout = {};
     if (view === "over_time") {
       traces = [{type: "scatter", mode: "lines+markers", x: dates,
         y: rows.map((row) => row[metric]), connectgaps: false, name: metric}];
       layout = {xaxis: categoricalAxis("Observation date", dates),
         yaxis: {title: {text: unit}}};
     } else if (axes.length < 2) {
       const labels = axes.length ? dataLabels(axes[0]) : [metric];
       if (view === "compare") {
         traces = [
           {type: axes.length ? "scatter" : "bar", mode: "lines+markers",
             name: String(dateA), x: labels, y: rows.map((row) => row["Value A"]), connectgaps: false},
           {type: axes.length ? "scatter" : "bar", mode: "lines+markers",
             name: String(dateB), x: labels, y: rows.map((row) => row["Value B"]), connectgaps: false},
         ];
       } else {
         traces = [{type: axes.length ? "scatter" : "bar", mode: "lines+markers",
           name: metric, x: labels, y: rows.map((row) => row[metric]), connectgaps: false}];
       }
       layout = {xaxis: categoricalAxis(axes[0]?.column || "Measure", labels),
         yaxis: {title: {text: unit}}, barmode: "group"};
     } else {
       const x = dataLabels(axes[0]), y = dataLabels(axes[1]);
       const field = view === "compare" ? "Change B−A" : metric;
       const byKey = new Map(rows.map((row) => [
         JSON.stringify([row[axes[0].column], row[axes[1].column]]), row[field],
       ]));
       const z = y.map((second) => x.map((first) =>
         byKey.get(JSON.stringify([first, second])) ?? null));
       const signed = panel.kind === "risk" || view === "compare";
       traces = [{type: "heatmap", x, y, z, hoverongaps: false,
         colorscale: signed ? "RdBu" : "Viridis", reversescale: signed,
         ...(signed ? {zmid: 0} : {}), colorbar: {title: {text: unit}},
         hovertemplate: "%{x}<br>%{y}<br>%{z:,.6g}<extra></extra>"}];
       layout = {xaxis: categoricalAxis(axes[0].column, x),
         yaxis: categoricalAxis(axes[1].column, y)};
     }
     const title = view === "compare" ? `${metric}: ${dateA} → ${dateB}`
       : view === "over_time" ? `${metric} over time` : `${metric}: ${day}`;
     return {data: traces, layout: {...common, ...layout, title: {text: title, x: 0.01}}};
   };
   ```

3. All cells come from an already bounded canonical panel. Preserve connector-provided label order. Do not sort tenor text alphabetically or merge Risk/Market axes. Add a guard rejecting more than two meaningful axes before `workspaceDateRows`; do not silently use only the first two.
4. **ADD** `workspaceProjectionControls(envelope, view, riskProjection, marketProjection, riskTenor0, riskTenor1, marketTenor0, marketTenor1, riskAdvancedSlice, marketAdvancedSlice)`. For each `risk`, then `market`, perform these exact operations:
   1. Read that panel from `envelope.panels`. For each of its axes, create label/value options from serialized `axis.labels`; retain a valid current tenor, otherwise choose the first tenor **within the already explicitly chosen series**. There are at most two axes. This is a display slice, not an inferred financial identity.
   2. Show the tenor-0 control only for Over time with at least one axis, tenor-1 only for Over time with two axes. If an advanced projection is active, show only that advanced projection's slice control instead.
   3. Build advanced options as **Use main view/auto** plus the original `dataProjectionOptions(axisCount)` for that panel. The original scalar timeline, one-axis 3D history, one-tenor timeline, two-axis surface, swap/option sweeps and comparisons remain reachable. Retain a valid advanced value; otherwise reset to auto. Main mode changes must reset both advanced values to auto so the visible main mode remains truthful.
   4. Use `dataSliceDefinition` for an advanced projection. For Market, remove `SUM_SLICE` from its values; summing quote values across tenors is not a meaningful replacement for an exact slice. Risk may retain its existing explicit Sum slice.
   5. Return dropdown options/values, axis labels and control styles only; perform no chart rendering and no network request. For absent/empty panels return empty options, null values and hidden control containers. Do not add an unlisted disabled Output; keep the ownership/return list below exact.
5. Register that callback in Python with all ten arguments as Inputs in the same order as its signature: bundle store, main view, Risk/Market projection values, Risk tenor-0/1, Market tenor-0/1, Risk/Market advanced-slice values. It owns the resulting values within this single clientside callback. It may use its own circular Inputs/Outputs, but no other callback writes those properties. Its Outputs, repeated for Risk then Market, are: projection options/value; tenor-label-0 children; tenor-0 options/value and tenor-0-control style; tenor-label-1 children; tenor-1 options/value and tenor-1-control style; advanced-slice options/value/style; tenor-controls style. Emit the two axis-label children as the axis column name or an empty string for an absent axis; hide each label with its corresponding control wrapper. These are its only output owners. Main-view change detection may use Dash clientside callback context to reset advanced values; do not use a global last-user value.
6. **ADD** `workspacePlayback(envelope, view, riskProjection, marketProjection, riskTenor0, riskTenor1, marketTenor0, marketTenor1, riskAdvancedSlice, marketAdvancedSlice, dateA, dateB, buttonClicks, intervalTicks, sliderValue, resetGeneration, cacheState, visibilityState, previousState)`. Implement its body by this exact sequence:
   1. Reject absent/invalid envelope, schema version other than 1, mismatched cache generation or reset. Return two empty figures, two empty tables and a stopped player. Do not fall back to a previous envelope.
   2. Read the envelope's sorted union dates. Date A defaults to the first date and Date B to the last; retain valid existing choices. Both panels use these exact dates even when one has no observation there.
   3. Set a state key from envelope key, main view, both projections, both tenor pairs, both advanced slices and A/B. A changed key stops playback and selects the last date. Otherwise adapt the existing `dataPlayback` click/tick/slider/visibility logic to this one shared key and union-date index. Store clicks/ticks/index/playing/key in `data-player-state-store`. Never store per-user player state in a module/global variable.
   4. Pause when the document is hidden, visibility store is hidden, identity/generation/reset changes, or the slider is dragged. Enable Play only with more than one union date and an active Snapshot/Over time view. Compare disables Play; show only date A/B controls there.
   5. For each selected panel with projection `auto`, call `workspaceMainFigure` and `workspaceDateRows` with the shared calendar date and that panel's independent tenor choices. For nonselected panel return an empty figure/table and hide its panel/table.
   6. Build table column definitions from the generated view rows, not `panel.values[0]`. Snapshot values cover the selected date and that chart's full axes; Over time values cover the exact selected tenor tuple and all shared dates; Compare values include A, B and B−A. A missing A or B gives null change. Do not display the old single selected-date table beneath a timeline or comparison.
   7. For an explicitly selected advanced projection, first call `workspaceAdvancedSelection(panel, projection, advancedSlice)` inside a per-panel try/catch. This independently validates the value at the rendering boundary; never trust dropdown options alone. A Market `__sum__`, unknown projection or unavailable slice must produce that panel's explicit unavailable figure/caption and empty values. Do not call `dataHistoryFigure` in that error branch, and do not silently replace the rejected value with another slice. For a valid result, pass its returned projection and slice to existing `dataHistoryFigure` with a shallow panel wrapper whose `dates` are the shared union dates. Keep its `values`, `axes`, `metric_column` and original date column unchanged. Pass the shared index and exact A/B; never translate an absent calendar date into the nearest panel index. Filter the table to the same advanced slice: one_tenor uses one axis label across dates; two_swap fixes option tenor (or explicit Risk Sum), two_option fixes swap tenor (or explicit Risk Sum); one_surface uses all displayed dates and tenors; two_surface uses the selected date; comparisons use exact A/B plus null-aware differences. Use the original helpers' financial Sum operation only for explicit Risk Sum, never Market. Keep advanced projection names visible in the panel caption so the main mode cannot misdescribe the chart.
   8. Set each caption to exact identity and unit plus **No observation on YYYY-MM-DD** when the selected date is absent from that panel's original dates. A missing panel/date still occupies its place in Both; do not silently hide it and make the remaining graph look complete.
   9. Return shared slider min=0, max=max(0, dates.length−1), marks=`dataSliderMarks(dates)`, current value, disabled flag, date pill, Play/Pause text, Play disabled, Static/Playing mode pill, interval disabled, player state, player-controls style and Compare-date controls style. Return Date A/B options/values from the union dates. Return panel grid class `data-chart-grid data-chart-grid-both` for Both, `data-chart-grid` otherwise.
7. Register `workspacePlayback` as a **clientside** callback. Use Inputs for envelope, view, projections, tenor choices, advanced slices, A/B, play clicks, interval ticks, slider value, reset, cache state and visibility; use State for previous player state. Return Outputs in this order: Risk chart figure, Risk values-table data/columns, Risk caption children, Risk panel style, Risk values-panel style; Market same six outputs; all shared-player outputs in the existing order; Compare-controls style; Date A options/value; Date B options/value; chart-grid className. Use the same order in the JavaScript return list and Python registration. List and count them beside the callback registration; do not leave return ordering implicit.
8. Add `workspaceProjectionControls` and `workspacePlayback` to the existing `window.dash_clientside.cube` export object. Export the new pure selection/row/figure helpers there too so they can be called directly from the browser console for checking. Do not create another outer global namespace.
9. **KEEP** the old pure `dataPlayback`, `dataProjectionBase` and `dataProjectionSlice` functions temporarily for their reusable behavior. Their three old callback registrations were removed in D06, so they do not render duplicate UI. Remove these pure functions only in a later cleanup after confirming no callers remain; they do not hold cached tables.
10. Do not put an interval Input on `load_workspace`, `repository.read` or catalog loading. The only repeated player work is bounded browser rendering of the already loaded envelope. Existing per-frame indexing performance improvements must remain in the advanced renderer; do not restore an older renderer over them.

### Outcome check for D07

Run `check_javascript(["assets/s09_playback.js"])` when Node is already available. If unavailable, complete the browser checks in D10. Check the new JavaScript return array has the same number and ordering as the Python callback Outputs; syntax success alone does not establish that agreement.

<a id="job-d08"></a>
## Job D08 — Reuse one segmented-control style

1. Open `assets/s04_pnl.css` and locate the six adjacent rules beginning `.pl-history-period-segments` through its focus-visible rule. They define the established P&L control appearance.
2. **MOVE** those base rules, preserving declarations, into `assets/s02_controls.css`. Change their selector prefix to `:is(.cube-segments, .pl-history-period-segments)`. Remove the original six base rules from `s04_pnl.css` so there is one owner. Keep its page-specific responsive rules; extend those selectors to `.cube-segments` only where their intended responsive behavior is shared.
3. **REMOVE** `.data-period-segmented` base/label/input/checked rules from `assets/s07_history.css`; `data-period` now uses `cube-segments`. Keep unrelated Data layout/player/graph rules.
4. **KEEP** Stock's existing period button IDs and callback behavior in `cube/pages/stock/s03_view.py` and `s04_callbacks.py`. In `assets/s06_visuals.css`, adjust `.stock-period-button` to the shared height, padding, font weight and border radius; keep `.stock-period-selected` as the selected class used by its callback. Add a focus-visible outline matching the P&L rule. Styling parity does not require converting working Stock buttons to new radio components.
5. **ADD** these layout rules at the end of `assets/s07_history.css`:

   ```css
   .data-chart-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
   .data-chart-grid-both { grid-template-columns: repeat(2, minmax(0, 1fr)); }
   .data-chart-grid > section { min-width: 0; }
   .data-page .cube-segments { max-width: 100%; flex-wrap: wrap; }
   .data-page details { min-width: 0; }
   .data-page summary { cursor: pointer; padding: 10px 0; font-weight: 700; }
   .data-page summary:focus-visible { outline: 2px solid var(--selection-line); }
   .data-page .data-history-chart { min-height: 360px; }
   @media (max-width: 1000px) {
     .data-chart-grid-both { grid-template-columns: minmax(0, 1fr); }
   }
   ```

6. Confirm the selected state uses the same foreground/background pair on Data, P&L and Stock. Use native radio/button keyboard interaction and visible focus; do not implement custom keyboard handling for the segmented controls.
7. Keep controls readable at narrow widths. The page itself must not gain a horizontal scrollbar from a wide surface or values table; scrolling belongs inside the graph/table container.

### Outcome check for D08

Check the stylesheet contains one owner for the shared base segmented-control rules and preserves Stock button IDs. Complete D09 and then D10 to inspect focus, narrow layouts, missing data and both Quick entry paths after a fresh process restart.

<a id="job-d09"></a>
## Job D09 — Check syntax and exact selection behavior in the notebook

1. Run this cell. It checks Python syntax without importing the application or needing any extra checking package:

   ```python
   check_syntax([
       "cube/pages/data/s01_selection.py",
       "cube/pages/data/s02_view.py",
       "cube/pages/data/s03_callbacks.py",
       "cube/pages/data/s04_workspace.py",
       "cube/pages/risk/s04_handoff.py",
       "cube/history/s06_repository.py",
   ])
   ```

2. Start a fresh kernel so it imports the saved code, then run this self-contained pure selection check. All financial values here are temporary in-memory examples; this writes no archive:

   ```python
   import sys
   from dataclasses import replace
   from datetime import date
   if str(APP_ROOT) not in sys.path:
       sys.path.insert(0, str(APP_ROOT))
   from cube.history import (
       HISTORY_HANDOFF_SCHEMA_VERSION, HistoryCatalogEntry,
       HistoryHandoff, HistoryIdentity, HistoryIdentityCatalog, RiskFilterView,
   )
   from cube.pages.data.s04_workspace import (
       common_bounds, parse_workspace_request, reduce_workspace_draft,
       unambiguous_raw_companion, workspace_request,
   )
   risk_identity = HistoryIdentity(
       source_types=("ir/delta",), risk_type="IR", risk_greek="Delta",
       underlying="EUR", identity_mode="reported",
   )
   market_identity = replace(risk_identity, identity_mode="underlying")
   risk_entry = HistoryCatalogEntry("risk", risk_identity, 1, date(2026, 8, 19))
   market_entry = HistoryCatalogEntry("market", market_identity, 1, date(2026, 8, 19))
   catalog = HistoryIdentityCatalog("example-generation", (risk_entry, market_entry))
   scope = RiskFilterView(filters=(("Portfolio", ("ExamplePortfolio",)),), exclude_selected=True)
   risk = replace(risk_entry.to_handoff(reset_generation=0), filter_view=scope)
   market = market_entry.to_handoff(reset_generation=0)
   assert unambiguous_raw_companion(catalog, risk) is None
   request = workspace_request("both", risk, market, period="wtd", request_id="example")
   parsed = parse_workspace_request(request)
   assert parsed["risk"].filter_view == scope
   assert parsed["market"].filter_view is None
   start, end = common_bounds(request, {
       "risk": [date(2026, 8, 17), date(2026, 8, 19)],
       "market": [date(2026, 8, 18), date(2026, 8, 19)],
   })
   assert (start, end) == (date(2026, 8, 17), date(2026, 8, 19))
   quick = {"handoff": risk.to_mapping(), "nonce": "example-quick"}
   imported = reduce_workspace_draft(
       "handoff", None, catalog.to_mapping(), quick, "risk", None, None, 0,
   )
   assert imported["draft"]["risk"]["filter_view"] == scope.to_mapping()
   paired = reduce_workspace_draft(
       "mode", imported["draft"], catalog.to_mapping(), quick,
       "both", risk_entry.key, None, 0, consumed_nonce="example-quick",
   )
   assert paired["valid"] is False  # reported identity needs explicit companion
   chosen = reduce_workspace_draft(
       "companion", paired["draft"], catalog.to_mapping(), quick,
       "both", risk_entry.key, market_entry.key, 0, consumed_nonce="example-quick",
   )
   assert chosen["valid"] is True
   assert chosen["draft"]["risk"]["filter_view"] == scope.to_mapping()
   assert chosen["draft"]["market"]["filter_view"] is None
   print("Selection scope, explicit pairing and common calendar checks passed")
   ```

3. If the cell stops with an assertion or import error, read the error and fix the named step. Do not remove the assertion or replace missing values with zero. If you changed saved Python code after importing it, restart the kernel before repeating the cell.
4. Check the callback source from the notebook with `search_project` for every removed ID listed in D04. No registered Input/State/Output may reference those IDs. Search for `Output("data-history-request-store"` and confirm only `edit_workspace` writes it. Search all shared-player outputs and confirm only `workspacePlayback` writes them. Inspect each clientside registration's output count beside its JavaScript return array.
5. In the browser console, call the exported `workspaceDateRows` helper on tiny panel objects containing zero, null, different observation dates and one/two axes. Confirm null remains null, zero remains zero, absent A/B gives null difference, Over time follows the exact tenor tuple, and selected-date rows use that exact calendar date. Do not substitute an unavailable neighboring date.
6. Use syntax checks to catch malformed Python only. The notebook assertions check a few exact state rules. Neither proves the callback graph, visuals, real data compatibility or memory behavior; those need the browser steps in D10.

<a id="job-d10"></a>
## Job D10 — Restart in JupyterHub and inspect the complete interaction

1. Save every edited Python, CSS and JavaScript file in the uploaded project. Stop the currently running app cell/server with its normal stop/interrupt control. Do not start a second process on the same port.
2. Restart the notebook kernel or start the app in a fresh Python process through the same known working JupyterHub launch method. A running process retains imported callback definitions; a browser reload alone is insufficient after changing callback registrations.
3. Open the Data page through the existing application navigation. Hard-refresh the browser once to load the modified assets.
4. On direct entry, confirm there is one Risk/Market/Both control and one searchable primary series picker. Confirm no archive row data is read while building the page layout. Only the archive catalog/date metadata may initialize when this page mounts.
5. Open one Quick Risk identity with a restrictive scope. Confirm exact identity, Source Types, include/exclude scope and Risk default arrive in Data. Load a different period and confirm the scope remains. Navigate away/back and confirm a consumed Quick nonce does not reset a subsequent direct selection.
6. Choose Both. For a reported identity with several possible raw quotes, confirm the companion selector is blank with a clear instruction. Select one Market quote and Load. Confirm two panels in one workspace, exact independent captions and units, one period and one date slider. Confirm changing the Risk Portfolio scope does not weight the Market quote.
7. Exercise Snapshot, Over time, Compare and every retained Advanced projection. In Over time, set the exact tenor(s) and confirm the values table follows the same choice. In Compare, select A/B, verify null-aware differences and confirm Play is disabled. Check that advanced options do not leave the main mode label misleading.
8. Exercise Play, Pause, drag, wheel scrubbing, hidden-browser-tab pause and Clear Cache. The player must stop on reset and must not restart with an old envelope. A fresh Load reloads the preserved draft selection. Watch the app's request log: slider/play ticks must not trigger archive reads.
9. Inspect a Market-only tenor/date and a Risk-only tenor/date. Confirm a visible missing-observation caption, no automatic nearest-date replacement, no fabricated zeros and no lost Market-only grid entries.
10. With a realistic selection, inspect server memory during one Risk load and one Both load, and inspect browser response size. Record row counts, selected date count, canonical cell counts and serialized bytes. If Both exceeds the declared budget, keep the clear recovery message and narrow the selection; do not raise caps without measuring the resulting peak.
11. Inspect the layout at a wide and narrow browser width. Both panels stack below 1000 px; captions/period controls remain readable; the values and diagnostics sections stay collapsed until opened; selected/focus styling matches Stock/P&L.
12. If a blocking regression remains, stop the app and restore **the complete D-unified-data backup group**, including callbacks, layout, helper module, CSS and JavaScript. For a newly created file absent from that backup, remove only that exact newly created project file. Keep archive data and user adjustments untouched. Restart the process and hard-refresh. Do not restore only the layout while leaving the new callbacks installed.
13. Mark this job complete only when Quick Risk, Quick Market, direct Risk, direct Market and Both have all been exercised successfully. The acceptance result is one unified Data destination with complete browsing controls; publishing instructions alone does not change the running application.

<a id="job-p01"></a>
## Job P01 — Group Risk siblings once per parent

### 1. Back up and locate the files

```python
backup_job('P01', ['cube/pages/risk/s06_explorertables.py', 'cube/ui/s02_aggregation.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

Current source: `build_tree_rows`, especially `scoped = tree_scope(frame, group_column, value)` at line 170. `cube/ui/s02_aggregation.py::tree_scope` calls `frame_for_context`, which converts the group column to strings and builds a full-length comparison mask for each child. With 400 children of a 100k-row parent this repeatedly inspects the same parent. The reusable numeric index accelerates the sums **after** this scoping step; it does not currently index branch membership.

The minimal change does not need a new persistent hierarchy cache. Build child-position groups once per visited parent and retain the existing special handling for the promoted `Other` branch.

Exact implementation steps:

1. In `build_tree_rows`, after `if group_column is None: return rows` and before the `for value in ordered_unique(...)` loop, add:

```python
    positions_by_value = frame.groupby(
        frame[group_column].astype(str),
        sort=False,
        dropna=False,
    ).indices
```

2. Replace only `scoped = tree_scope(frame, group_column, value)` with:

```python
        scoped = (
            tree_scope(frame, group_column, value)
            if group_column == "display bucket" and value == "Other"
            else frame.iloc[positions_by_value[value]]
        )
```

3. Keep `ordered_unique(...)`, `visible_tree_level(...)`, `next_context`, `row_key(...)` and the existing recursion unchanged. Authoritative tenor sorting and promotion rules remain their responsibility. The row budget in item 1 should be checked before creating each child scope.

4. Do not replace the promoted `Other` fallback with a plain group lookup: `tree_scope` excludes reported identities that are already promoted elsewhere in the same parent. That is financial membership logic, not incidental overhead.

Before implementation, add a component-level old/new comparison covering reported/raw identity, sparse tenor levels, promotion enabled/disabled and `Other`. Include duplicate DataFrame indices and mixed `1`/`"1"` labels; positions must be positional (`iloc`), never assumed to be the DataFrame's index labels. With your representative input, compare cold and repeated expanded views with the same numeric cache. No new cache invalidation is needed for this local-per-parent grouping.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/risk/s06_explorertables.py', 'cube/ui/s02_aggregation.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Expand Risk siblings with the same filters used before editing. Names, order, row actions and totals must match.
2. Include a missing label, cancellation to zero and a nondefault hierarchy. Empty selection must still show its existing empty state.
3. Confirm full aggregation remains in the prepared index and only visible rows are constructed.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P01')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p02"></a>
## Job P02 — Skip calculations for intentionally blank Credit cells

### 1. Back up and locate the files

```python
backup_job('P02', ['cube/pages/risk/s06_explorertables.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

Current source: `build_alt_risk_table::dimension_cells` at line 505 calculates a pandas groupby and total before `should_show_sum` decides whether anything may be displayed. `build_credit_multi_table::measure_cells` at line 672 calls `credit_measure_values` six times even when `should_show_sum` is false. The helper allocates masks and series and checks connector completeness; the unused TOTAL Risk row alone can touch the entire selected frame six times. `build_credit_multi_table` also recomputes measure availability at line 755 despite having `measure_completeness` already.

Exact implementation steps for Credit Multi:

1. Immediately after `show_value = should_show_sum(selected_metric, context)` in `measure_cells`, add:

```python
        if not show_value:
            return [
                html.Td(
                    "",
                    className=(
                        "metric-cell credit-measure-cell metric-cell-inert "
                        "number-positive"
                    ),
                    **{"data-metric": f"{selected_metric}:{measure}"},
                )
                for measure in CREDIT_MEASURES
            ]
```

2. Replace the `missing_measures = [...]` expression with:

```python
    missing_measures = [
        measure for measure in CREDIT_MEASURES if not measure_completeness[measure]
    ]
```

3. Keep the existing helper for displayed cells. Do not replace all calls with precomputed full-frame numbers without checking partial connector availability and Cross Gamma sources. `credit_measure_values` makes a local completeness decision as well as accepting the outer completeness flag. A naive precompute can blank a locally complete subgroup or leak partial values. P&L is intentionally repeated across measures; summing the six measure columns would double-count it.

Exact implementation steps for Split VA:

1. Add the following at the start of `dimension_cells`, before its groupby:

```python
        show_value = should_show_sum(selected_metric, context)
        if not show_value:
            return [
                html.Td(
                    "",
                    className=(
                        "metric-cell alt-dimension-cell metric-cell-inert"
                        + (" total-column" if value == "Total" else "")
                        + " number-positive"
                    ),
                    **{"data-metric": f"{selected_metric}:{value}"},
                )
                for value in [*dimension_values, "Total"]
            ]
```

2. Remove the later duplicate `show_value = should_show_sum(selected_metric, context)` assignment. Retain all existing groupby/sum code for displayed cells.

These snippets deliberately change only the meaningless sign class of an empty inert cell to neutral-positive. They do not remove a displayed value. If CSS later uses signed backgrounds on inert cells, change the inert styling explicitly rather than computing invisible financial totals for colour.

Check in the browser: open Credit Multi and Split VA. Intentionally blank total cells remain blank and retain their notes/action attributes. Compare displayed numbers and P&L before/after for every available measure and a partially available connector pair. P&L must not be summed across the six measure columns. Use the preview with existing missing-source examples to confirm a locally complete subgroup still displays its values. This saving is separate from the standard Cross/Credit Single index cache.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/risk/s06_explorertables.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the Credit Multi and Split VA checks above.
2. Inspect the blank-cell branches: they must return before Credit grouping/measure calculations.
3. Check partial connector availability and keep the existing missing-data notes.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P02')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p03"></a>
## Job P03 — Use one Risk surface pivot for chart and matrix

### 1. Back up and locate the files

```python
backup_job('P03', ['cube/pages/risk/s05_charts.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

Current source: `cube/pages/risk/s05_charts.py::_tenor_surface_pivot` line 95; `build_tenor_heatmap` line 488; `_build_detail_panel_from_frame` line 625, especially the second pivot at lines 809–813. In surface/auto mode the heatmap builds the pivot, and the adjacent matrix builds it again from the same detail and metric. Quick Market already returns its pivot with the chart (`s09_quickmarket.py::_market_surface_chart`, line 647), demonstrating the same sharing pattern without a global cache.

Exact implementation steps:

1. Rename the existing heatmap implementation to `_build_tenor_heatmap_from_pivot` and replace its signature with:

Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

```text
def _build_tenor_heatmap_from_pivot(
    pivot: pd.DataFrame,
    metric: str,
    title: str = "Swap x option surface",
    *,
    ambiguous_option_order: bool = False,
    ambiguous_swap_order: bool = False,
) -> dcc.Graph:
```

2. Remove only its initial `_tenor_surface_pivot(detail, metric)` assignment. Keep the rest of the existing trace, axis, colour, annotation and Graph code unchanged.

3. Immediately before that private function, add a public compatibility wrapper with the original signature:

```python
def build_tenor_heatmap(
    detail: pd.DataFrame,
    metric: str,
    title: str = "Swap x option surface",
) -> dcc.Graph:
    pivot, option_ambiguous, swap_ambiguous = _tenor_surface_pivot(detail, metric)
    return _build_tenor_heatmap_from_pivot(
        pivot,
        metric,
        title,
        ambiguous_option_order=option_ambiguous,
        ambiguous_swap_order=swap_ambiguous,
    )
```

4. In `_build_detail_panel_from_frame`, immediately after `matrix_detail: pd.DataFrame | None = None`, add:

```python
    matrix_pivot: pd.DataFrame | None = None

    def surface_chart(surface_detail: pd.DataFrame) -> dcc.Graph:
        nonlocal matrix_pivot
        matrix_pivot, option_ambiguous, swap_ambiguous = _tenor_surface_pivot(
            surface_detail, metric
        )
        return _build_tenor_heatmap_from_pivot(
            matrix_pivot,
            metric,
            title="Swap x option surface",
            ambiguous_option_order=option_ambiguous,
            ambiguous_swap_order=swap_ambiguous,
        )
```

5. Replace the surface branch's `build_tenor_heatmap(displayed_detail, metric, title=...)` call with `surface_chart(displayed_detail)`.

6. Replace the auto branch's `build_tenor_heatmap(detail.loc[paired], metric, title=...)` call with `surface_chart(matrix_detail)`; this branch already sets `matrix_detail = detail.loc[paired]`.

7. At the bottom, replace the block beginning `if matrix_detail is not None and not matrix_detail.empty:` with:

```python
    if matrix_pivot is not None:
        detail_table = build_surface_matrix_table(matrix_pivot, metric)
    else:
        detail_table = build_small_table(displayed_detail, metric)
```

8. Keep `build_tenor_heatmap` in `__all__`; the private helper need not be exported.

Check in the browser: select a small non-square two-axis surface, including a missing cell. The chart and matrix must show identical values in identical tenor order. A missing value stays missing. Confirm surface mode and the automatic paired-row panel each call `_tenor_surface_pivot` only once by inspecting the edited call sites with `search_project("_tenor_surface_pivot")`. Keep existing mean aggregation for market values and `sum(min_count=1)` for Risk/P&L.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/risk/s05_charts.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Compare chart and matrix for one sparse non-square surface. Each tenor pair must show the same value in both.
2. Change metric and tenor ordering; both views must move together. Missing pairs must stay blank.
3. Inspect call sites to confirm one pivot per combined panel build.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P03')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p04"></a>
## Job P04 — Select a Risk detail scope once

### 1. Back up and locate the files

```python
backup_job('P04', ['cube/pages/risk/s05_charts.py', 'cube/pages/risk/s07_explorer.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

Current source: `s05_charts.py::build_detail_panel_with_state` line 881 selects `scoped = frame_for_context(frame, context)`, then line 882 calls `detail_frame(frame, context, metric)`, which repeats the same selection internally.

Exact change: replace

```python
    detail = detail_frame(frame, context, metric)
```

with

```python
    detail = detail_frame(scoped, {}, metric)
```

Leave the preceding `scoped = ...`, context/title handling and all aggregation rules in `detail_frame` unchanged. The latter still copies its selected frame before adding the `rows` column, so this does not mutate shared cached data.

Check the same detail selection before and after this edit for `risk`, `drisk`, `pl`, `move`, `open` and `current`. Include an empty selection and a selection with more than one context field. Values, title and selected identities must match. Keep the copy inside `detail_frame` before adding its `rows` column so cached input is not mutated.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/risk/s05_charts.py', 'cube/pages/risk/s07_explorer.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Compare every supported detail metric for the same selected row.
2. Clear the selection and then choose a deeper multi-field row. Empty behavior, titles and totals must match.
3. Confirm detail processing does not add columns to a shared cached source frame.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P04')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p05"></a>
## Job P05 — Filter Search using only the required position columns

### 1. Back up and locate the files

```python
backup_job('P05', ['cube/domain/s10_search.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

Current source: `cube/domain/s10_search.py::_filter_risk_positions` line 154. It constructs `candidates = frame.iloc[positions]` before checking whether any filter selections are nonempty. That copies/slices all available columns, although filtering needs only a small subset. `search_combine_udl_options` at line 1054 calls this once per candidate exact identity; a dictionary containing empty selections still incurs the broad slice.

Replace the complete `_filter_risk_positions` function with:

```python
def _filter_risk_positions(
    frame: pd.DataFrame,
    positions: np.ndarray,
    risk_filters: Mapping[str, Sequence[str] | None] | None,
    *,
    exclude_selected: bool = False,
) -> np.ndarray:
    """Filter exact position numbers using only active filter columns."""
    selected_filters = dict(risk_filters or {})
    unknown = sorted(set(selected_filters) - set(QUICK_RISK_FILTER_COLUMNS))
    if unknown:
        raise ValueError(f"Unknown Quick Risk filters: {unknown}")
    if len(positions) == 0 or not selected_filters:
        return positions

    active_filters: list[tuple[str, list[str]]] = []
    for column in QUICK_RISK_FILTER_COLUMNS:
        raw_selected = selected_filters.get(column)
        if isinstance(raw_selected, (str, bytes)):
            raise TypeError(
                f"Quick Risk filter {column!r} must be a sequence of values"
            )
        selected = list(raw_selected or [])
        if selected:
            active_filters.append((column, selected))
    if not active_filters:
        return positions

    keep = np.ones(len(positions), dtype=bool)
    for column, selected in active_filters:
        matches = frame[column].iloc[positions].isin(selected).to_numpy()
        keep &= ~matches if exclude_selected and column != SPLIT else matches
    return positions[keep]
```

No import changes are required: `Mapping`, `Sequence`, `pd` and `np` already exist. This keeps OR within a filter, AND between filters, and the special always-include Split rule. Exact row positions and their order remain unchanged; quote resolution still occurs after Risk filtering. Unknown-filter and text-instead-of-list rejection remain. A malformed frame/filter combination could raise a different first error because validation now precedes slicing; ordinary validated callers should not depend on that ordering.

Check Search before and after the edit with inclusion, exclusion, empty selections, combined Portfolio/Split filters, and each supported filter field. The identity options must match. A still-valid selected identity must remain selected; a no-longer-valid identity must be cleared. Duplicate/out-of-order position indices must retain their original order. Unknown fields and malformed text selections must still give the same validation error.

Do not automatically replace this with a full-frame filter on every keystroke. A narrow text query can touch only one small identity, so a mandatory scan of all 100k positions could be slower. A cache of filter masks is a later measured option; it needs canonical filter/revision keys and a memory bound.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/domain/s10_search.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the inclusion/exclusion and combined-filter comparisons above.
2. Apply each registered filter in Search. The options and retained selected identity must match the original behavior.
3. Clear all selections and verify the default list is restored.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P05')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p06"></a>
## Job P06 — Batch table resizing and rectangular selection in the browser

### 1. Back up and locate the files

```python
backup_job('P06', ['assets/s11_tables.js'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

Current source: `assets/s11_tables.js::attachResizeHandles` line 269. Every mousemove calls `resizeColumn`, which queries all cells in the column and writes three style properties per cell. `cellsInRectangle` at line 188 queries all selectable cells and filters them even when the requested rectangle is tiny. These are local browser costs, independent of the Python numeric cache.

#### Resize: retain the current table implementation and batch the gesture

Replace only the entire `handle.addEventListener("mousedown", ...)` block at lines 287–305 with:

```javascript
        handle.addEventListener("mousedown", (event) => {
          event.preventDefault();
          event.stopPropagation();
          const startX = event.clientX;
          const startWidth = header.getBoundingClientRect().width;
          const columnCells = Array.from(
            table.querySelectorAll(`tr > *:nth-child(${index + 1})`),
          );
          let pendingWidth = startWidth;
          let frameId = null;

          const applyPendingWidth = () => {
            frameId = null;
            if (!table.isConnected) return;
            columnCells.forEach((cell) => {
              cell.style.width = `${pendingWidth}px`;
              cell.style.minWidth = `${pendingWidth}px`;
              cell.style.maxWidth = `${pendingWidth}px`;
            });
          };
          const onMove = (moveEvent) => {
            pendingWidth = Math.max(82, startWidth + moveEvent.clientX - startX);
            if (frameId === null) {
              frameId = requestAnimationFrame(applyPendingWidth);
            }
          };
          const onUp = () => {
            document.removeEventListener("mousemove", onMove, true);
            document.removeEventListener("mouseup", onUp, true);
            window.removeEventListener("blur", onUp);
            if (frameId !== null) cancelAnimationFrame(frameId);
            applyPendingWidth();
          };

          document.addEventListener("mousemove", onMove, true);
          document.addEventListener("mouseup", onUp, true);
          window.addEventListener("blur", onUp);
        });
```

The existing `resizeColumn` remains for keyboard resizing and the double-click reset remains. This is an incremental improvement: it still writes all cells in the column once per animation frame. A CSS `<colgroup>` redesign could reduce writes further but is a larger table-layout change and is not required for the initial fix.

#### Rectangle: visit only the requested table rows/columns

Inside `cellsInRectangle`, keep all existing start/end/table checks and row/column range calculations. Replace the final `return Array.from(table.querySelectorAll(...)).filter(...)` expression with:

```javascript
    const cells = [];
    for (let rowIndex = rowMin; rowIndex <= rowMax; rowIndex += 1) {
      const row = table.rows[rowIndex];
      if (!row || row.hidden || row.parentElement?.tagName !== "TBODY") continue;
      for (let columnIndex = columnMin; columnIndex <= columnMax; columnIndex += 1) {
        const cell = row.cells[columnIndex];
        if (
          cell?.matches("td.metric-cell, th.index-cell, th.aggregate-index")
          && clipboardValueFromCell(cell) !== ""
        ) cells.push(cell);
      }
    }
    return cells;
```

This uses `rowIndex` and `cellIndex`, matching the original function's coordinate system. It does not reinterpret hidden rows or invent spreadsheet coordinates for colspans. Check selection/copy across hidden Quick Risk descendants, totals, keyboard modifiers, blank cells and multiple tables; resize via mouse and keyboard, double-click reset, blur during drag and table replacement during drag. Use DevTools Performance on a representative bounded table; compare long tasks and style/layout work. Syntax alone is not sufficient browser validation. Apply the edit to the asset file and reload the preview before checking these interactions.

### 3. Check syntax and the changed behaviour

```python
check_syntax([])
check_javascript(['assets/s11_tables.js'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Drag a column boundary, release outside the table, double-click to reset, and change tables during a drag. The final width must be correct and dragging must stop.
2. Select/copy across blank cells, totals and collapsed Quick Risk rows. Check modifier keys and multiple tables.
3. Use the keyboard resize control and confirm focus/width remain correct after the table is replaced.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P06')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p07"></a>
## Job P07 — Group Stock children once per parent

### 1. Back up and locate the files

```python
backup_job('P07', ['cube/pages/stock/s05_pivot.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

Replace only the function named below. Keep the existing tree renderer, full-scope totals and expansion state. After editing, compare the displayed pivot with the original preview for the same saved filters.

1. Replace `_ordered_children` in `s05_pivot.py` with:

```python
def _ordered_children(
    frame: pd.DataFrame, field: str
) -> Iterable[tuple[str, pd.DataFrame]]:
    labels = frame[field].fillna("Unmapped").astype(str)
    children = [
        (str(label), child, abs(_metric_value(child, "Stock") or 0.0))
        for label, child in frame.groupby(
            labels, sort=False, observed=True, dropna=False
        )
    ]
    children.sort(key=lambda item: (-item[2], item[0].casefold()))
    return ((label, child) for label, child, _magnitude in children)
```

2. Keep `_metric_value(...).sum(min_count=1)`, ordering by absolute **net Stock**, tie-breaking, and the full child frames. Do not change the ordering to sum of absolute position values; that would change behaviour.
3. In Stock, inspect the default pivot, change row dimensions and column split, expand several levels and compare totals. Use examples with null labels, all-missing metrics, cancellation to zero, duplicate indices and empty selection. A zero caused by cancellation must remain visible under the existing rules; a missing value must not become zero.
4. Measure the 100k/400-book case and a representative deeper hierarchy. Expect less sibling scanning, not a fix for unbounded rendered rows.
5. Only after that simple change, consider reusing the Stock display projection across expand/collapse. `render_current_stock` calls `stock_display_rows` on every pivot change even though `loaded_snapshot` and committed filters are unchanged. A prepared projection may be keyed by the snapshot token, canonical committed filters and exclusion mode; do not include open paths in that key. Retain it only with a small entry/byte budget and clear it with the owning `cached_pages` store. Do not implement this additional cache unless measured projection time justifies it.

This is the same principle as the Risk fix but at a smaller scope. The first change removes an avoidable algorithmic cost without adding retention at all.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/stock/s05_pivot.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the Stock grouping checks above, including empty and missing values.
2. Change row hierarchy and column split, then expand/collapse. Full totals and business order must match.
3. Verify Stock history selection still identifies the clicked scope.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P07')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p08"></a>
## Job P08 — Batch Stock history identities and read date bounds directly

### 1. Back up and locate the files

```python
backup_job('P08', ['cube/pages/stock/s02_history.py', 'cube/pages/stock/s04_callbacks.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

1. Open `cube/pages/stock/s02_history.py`. Keep the existing `StockHistoryQueryProtocol` and callable fallback. Add `from cube.domain.s14_identityaliases import canonical_demo_identity` from C05 if absent. Immediately after `StockHistoryQueryProtocol`, add this separate optional protocol. `Protocol`, `runtime_checkable`, `Mapping`, `pd` and `StockHistoryCatalogResult` already exist:

```python
@runtime_checkable
class StockHistoryBatchQueryProtocol(Protocol):
    def bounds(self) -> StockHistoryCatalogResult: ...

    def rows_many(
        self,
        identities: list[Mapping[str, object]],
        start_date: object,
        end_date: object,
    ) -> pd.DataFrame: ...
```

2. In `SQLStockHistoryRepository.__init__`, change only the signature to accept `*, max_rows: int = 100_000` after `root`. Keep all existing assignments. At the end add:

```python
        if isinstance(max_rows, bool) or not isinstance(max_rows, int) or max_rows < 1:
            raise ValueError("Stock history max_rows must be a positive integer")
        self._max_rows = max_rows
        self._bounds = StockHistoryCatalogResult((), None, None, 0)
```

   In `clear`, inside its existing lock, after `self._days = None`, add `self._bounds = StockHistoryCatalogResult((), None, None, 0)`. Keep connection closing and all revision checks.

3. In `_current_connection`, inside its existing `try` block and after both the empty-view and populated-view branches, add this block at the same indentation as `connection.execute("SET enable_progress_bar = false")`. It runs once when that connection opens. Keep the existing exception handler and final assignments to `self._connection`/`self._days`:

```python
            minimum, maximum, date_count = connection.execute(
                f'''SELECT min("{STOCK_DATE_COLUMN}")::VARCHAR,
                           max("{STOCK_DATE_COLUMN}")::VARCHAR,
                           count(DISTINCT "{STOCK_DATE_COLUMN}")::BIGINT
                    FROM stock_history'''
            ).fetchone()
            self._bounds = StockHistoryCatalogResult(
                (), minimum, maximum, int(date_count or 0)
            )
```

   In `catalog`, keep the text search, maximum search length, selector limit and bounded identity query. Replace only its repeated `minimum, maximum, date_count = connection.execute(...).fetchone()` block with:

```python
            minimum = self._bounds.minimum_date
            maximum = self._bounds.maximum_date
            date_count = self._bounds.date_count
```

   After the existing `text = str(search or "").strip()`, add `text = canonical_demo_identity(text)`. The C05 view already emits canonical identity values. Keep free-text matching as plain text; do not interpret search text as SQL or a serialized identity.

4. Add this complete `bounds` method after `clear`:

```python
    def bounds(self) -> StockHistoryCatalogResult:
        with self._lock:
            self._current_connection()
            return self._bounds
```

   The result is frozen and contains no position rows. Keep generation discovery in `_current_connection`; do not permanently freeze the completed-day list.

5. Add this complete `rows_many` method immediately before the existing `rows` method. It canonicalizes every validated identity **before** deduplicating requests, matching C05's SQL view. It rejects duplicate archived observations; it does not collapse them to hide a collision:

```python
    def rows_many(self, identities, start_date, end_date) -> pd.DataFrame:
        start = normalize_stock_date(start_date)
        end = normalize_stock_date(end_date)
        if start > end:
            raise ValueError("Stock history start date must not exceed end date")
        if not isinstance(identities, (list, tuple)):
            raise ValueError("Stock history identities must be a list or tuple")
        validated = []
        seen = set()
        for identity in identities:
            decoded = stock_history_identity_from_token(
                stock_history_identity_token(identity)
            )
            canonical = {
                column: canonical_demo_identity(decoded[column])
                for column in STOCK_IDENTITY_COLUMNS
            }
            key = tuple(canonical[column] for column in STOCK_IDENTITY_COLUMNS)
            if key not in seen:
                seen.add(key)
                validated.append(canonical)
        if not validated:
            return pd.DataFrame(columns=STOCK_HISTORY_COLUMNS)
        selected = pd.DataFrame(validated, columns=STOCK_IDENTITY_COLUMNS)
        predicates = " AND ".join(
            f'h."{column}" = s."{column}"' for column in STOCK_IDENTITY_COLUMNS
        )
        projection = ", ".join(f'h."{column}"' for column in STOCK_HISTORY_COLUMNS)
        with self._lock:
            connection = self._current_connection()
            connection.register("_stock_selected_keys", selected)
            try:
                frame = connection.execute(
                    f'''SELECT {projection} FROM stock_history h
                        SEMI JOIN _stock_selected_keys s ON {predicates}
                        WHERE h."{STOCK_DATE_COLUMN}" BETWEEN ? AND ?
                        ORDER BY h."{STOCK_DATE_COLUMN}"
                        LIMIT ?''',
                    [start.date().isoformat(), end.date().isoformat(), self._max_rows + 1],
                ).df()
            finally:
                connection.unregister("_stock_selected_keys")
        if len(frame) > self._max_rows:
            raise ValueError("Stock history selection is too large; narrow its dates or scope")
        frame.columns = list(STOCK_HISTORY_COLUMNS)
        if frame.empty:
            return normalize_stock_history_frame(
                frame, identity=validated[0], start_date=start, end_date=end
            )
        dated_key = [STOCK_DATE_COLUMN, *STOCK_IDENTITY_COLUMNS]
        if frame.duplicated(dated_key).any():
            raise ValueError("Duplicate or alias-colliding Stock history observations")
        parts = []
        for key, group in frame.groupby(list(STOCK_IDENTITY_COLUMNS), sort=False, dropna=False):
            key = tuple(key) if isinstance(key, tuple) else (key,)
            if key not in seen:
                raise ValueError("Stock history returned an unrequested identity")
            parts.append(normalize_stock_history_frame(
                group,
                identity=dict(zip(STOCK_IDENTITY_COLUMNS, key)),
                start_date=start,
                end_date=end,
            ))
        return pd.concat(parts, ignore_index=True).loc[:, list(STOCK_HISTORY_COLUMNS)].sort_values(
            [STOCK_DATE_COLUMN, *STOCK_IDENTITY_COLUMNS], kind="stable"
        ).reset_index(drop=True)
```

6. Replace the complete existing `rows` method with this adapter. Keep its public signature so existing providers/callers are unaffected:

```python
    def rows(self, identity, start_date, end_date) -> pd.DataFrame:
        return self.rows_many([identity], start_date, end_date)
```

   Add `StockHistoryBatchQueryProtocol` to this module's existing `__all__` list. Do not change `StockHistoryQueryProtocol` or require external providers to implement batching.

7. Open `cube/pages/stock/s04_callbacks.py`. Add `StockHistoryBatchQueryProtocol` to its existing `.s02_history` import. In `load_stock_history`, keep C03's committed clicked/manual scope resolution and fingerprint checks. Immediately before resolving date bounds, assign `batch_source = query_source if isinstance(query_source, StockHistoryBatchQueryProtocol) else None`. Replace only the `catalog = query_source.catalog(crds, limit=1)` statement with `catalog = batch_source.bounds() if batch_source is not None else query_source.catalog(crds, limit=1)`. Keep the following access to `catalog.minimum_date` and `catalog.maximum_date` and the existing no-history message.

8. In that same callback, after the exact `identities` list and the look-back `query_start` are resolved, replace the per-identity read loop with two branches. For `batch_source is not None`, make one call `combined_history = batch_source.rows_many(identities, query_start, end_date)`. For `batch_source is None`, retain the existing per-identity `query_source.rows(...)` or callable `stock_history_source(...)` path, including each `normalize_stock_history_frame` check and the `pd.concat` of its parts. Both branches must assign the same `combined_history` variable. Pass it to the existing figure builder in place of the old concatenation expression. Keep its existing error/status outputs. Do not re-read today's Stock, broaden clicked scope or invoke the batch method once per identity.

9. Keep the one prior business day needed for `dStock`, actual archive gaps and full-scope Market Value summation. Do not zero-fill or forward-fill history. Keep C03's currency guard. F03 later adds Quantity with its own compatible-unit rule and an archive-only selector. That later path must use the same canonical exact identities and optional `bounds` method.

10. Use two exact identities with the same CRDS/Activity but different remaining fields. Compare the combined read with the two separate single-identity reads. Every dated observation must match, requesting an identity twice must not double its values, and an unexpected or duplicate dated identity must raise an error. Include one legacy demo spelling and its canonical spelling: both requests must resolve to the same canonical key without rewriting archive bytes. A provider with only `StockHistoryQueryProtocol` must still work through the fallback. Start with 1 and 10 identities before using a 400-identity scope.


### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/stock/s02_history.py', 'cube/pages/stock/s04_callbacks.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the two-exact-identity archive comparison above.
2. Choose Stock history for one identity and then a multi-position scope. Missing dates and the preceding business day must keep their original meaning.
3. Use an existing provider implementing only the single-read method and confirm fallback remains usable.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P08')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p09"></a>
## Job P09 — Reuse archive discovery metadata within one history action

### 1. Back up and locate the files

```python
backup_job('P09', ['cube/history/s03_io.py', 'cube/history/s06_repository.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

Do **not** claim that interactive history rehashes every financial file on every click. It does not. The code deliberately keeps digest-verified `list_completed_v4_archive_days` and publication validation separate from the interactive schema/manifest/row-count path. Preserve both paths and all immutable-leaf contracts.

1. First make each fingerprint scan cheaper without changing its observable cadence. In `ArchiveHistoryRepository.generation`, replace the file comprehension with a loop that obtains each file's `stat()` once, uses `stat.S_ISREG(stat_result.st_mode)` for the existing regular-file check, and stores size/mtime from the same result. Add `from stat import S_ISREG`.
2. Apply the same single-stat approach to `_completed_archive_root_signature`: it already stores `stat = entry.stat()` but then calls `entry.is_file()` separately. Use `S_ISREG(stat.st_mode)` for that boolean. Keep all entries in the signature, including unexpected files/directories, so the completion contract still detects them.
3. Preserve existing treatment of absent files, concurrent creation and error handling. Catch only `FileNotFoundError` if a formerly absent expected file vanishes between enumeration and stat; do not swallow permission errors or completed-marker corruption. The full validation routine must still fail a completed leaf whose required file is missing.
4. Remove **intra-action** repeated discovery first: the Stock batch operation above must reuse one `_current_connection()` result for all its SQL statements. Bounds must be generation-scoped. Likewise any P&L action running multiple SQL statements should acquire the current connection once and pass that local handle.
5. Do not memoize archive discovery forever or key it solely on the root directory mtime. Existing date files and `_SUCCESS` metadata participate in validation, and new or invalid completed leaves must be detected.
6. A short worker-local discovery TTL is an optional later optimization for slow network shares only after these changes are measured. If adopted, make the freshness delay explicit (for example, five seconds), force refresh on Clear Cache and official publication, and clear the memo on error. Do not use that memo for strict digest verification/publish gates. Keep the existing discovery boundary; do not add a background filesystem watcher or catalog service.
7. In an isolated demonstration archive, check a missing date, an in-progress leaf and a newly completed date. Only completed valid leaves are readable. A new completed day must become available on the next action. Keep failures for changed manifests, unexpected files, non-directory roots and permission errors. Inspect the action-local generation flow: catalog and exact read must share one validated generation without becoming a permanent discovery cache.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/history/s03_io.py', 'cube/history/s06_repository.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the isolated archive-day checks above.
2. Refresh the Data catalog after adding a completed day. It must appear on the next action.
3. Keep publication digest validation and interactive validation separate; neither may be removed.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P09')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p10"></a>
## Job P10 — Index P&L summary children once

### 1. Back up and locate the files

```python
backup_job('P10', ['cube/pages/pnl/s10_summary.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

1. In `build_pl_summary_table`, immediately after its existing loop that fills `rows`, build a parent lookup once:

```python
    children_by_parent: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for path in rows:
        if path:
            children_by_parent.setdefault(path[:-1], []).append(path)
    for children in children_by_parent.values():
        children.sort(key=_sort_key)
```

2. In the nested `append_row`, replace `children = _children(rows, path)` with `children = children_by_parent.get(path, [])`.
3. Run `search_project("_children(")`. Remove only the old `_children` function in `cube/pages/pnl/s10_summary.py` if no remaining caller needs it. Keep similarly named functions in other modules. In P&L Summary, verify rendered child order and totals rather than depending on a private helper name.
4. Preserve `_sort_key`, open-path reduction, the existing 75-leaf paging size (`PL_SUMMARY_LEAF_PAGE_SIZE = 75`), history cell IDs, and whole-scope totals. Do not introduce a cross-request table cache for this small lookup.
5. Compare rendered output for collapsed, expanded and paged summaries, including ties. Only keep the change if representative summary timings warrant it; this is P3 compared with the capacity items above.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/pages/pnl/s10_summary.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Open P&L Summary with the same scope before/after editing. Child order, totals and missing values must match.
2. Expand and collapse branches. Opening one must not cause unrelated hidden children to be rendered.
3. Inspect the new child lookup: it is built once per render and is not retained as an HTML cache.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P10')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p11"></a>
## Job P11 — Avoid an unused full snapshot copy after Portfolio refresh

### 1. Back up and locate the files

```python
backup_job('P11', ['cube/services/s06_refresh.py', 'cube/app/s02_contracts.py', 'cube/pages/risk/s15_refresh.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

**Location:** `cube/services/s06_refresh.py::RiskRefreshManager.refresh_portfolios` at line 1577, success return at line 1748 and retained-snapshot return at line 1817; `cube/pages/risk/s15_refresh.py::register_refresh_callbacks.refresh_pipeline` branch around line 646; `cube/app/s02_contracts.py::RefreshManagerProtocol.refresh_portfolios` around line 420. Use the symbols as anchors if preceding changes shift line numbers.

#### Exact changes

1. In the service method signature add `copy_result: bool = True` after `expected_reset_generation`. Replace its return annotation with `RefreshSnapshot | None`:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   def refresh_portfolios(
       self,
       *,
       reason: str = "portfolio mapping",
       expected_revision: int | None = None,
       expected_reset_generation: int | None = None,
       copy_result: bool = True,
   ) -> RefreshSnapshot | None:
   ```

2. Immediately after the method's existing docstring and before acquiring `_refresh_lock`, add:

   ```python
   if not isinstance(copy_result, bool):
       raise TypeError("copy_result must be boolean")
   ```

3. In **this method only**, replace its success return:

   ```python
   return self._copy_snapshot(snapshot) if copy_result else None
   ```

4. In the same method, replace the failure/last-good return:

   ```python
   return self._copy_snapshot(retained) if copy_result else None
   ```

   Do not remove `_commit_snapshot`, `_commit_full_snapshot`, stale-revision checks, `finally` lock release, or any failure handling.

5. Update the protocol declaration in `cube/app/s02_contracts.py` to match:

   ```python
   def refresh_portfolios(
       self,
       *,
       reason: str = "portfolio mapping",
       expected_revision: int | None = None,
       expected_reset_generation: int | None = None,
       copy_result: bool = True,
   ) -> RefreshSnapshotProtocol | None: ...
   ```

6. In `cube/pages/risk/s15_refresh.py`, replace the complete `elif "refresh-portfolios-button" in triggered_ids:` branch with:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   elif "refresh-portfolios-button" in triggered_ids:
       refresh_manager.refresh_portfolios(
           reason="portfolio mapping",
           expected_revision=current_revision,
           expected_reset_generation=browser_reset_generation,
           copy_result=False,
       )
       snapshot = refresh_manager.control_snapshot
   ```

7. Run `search_project("refresh_portfolios(")`. Update the Risk refresh callback to pass `copy_result=False`; keep other existing callers on the default copy-returning behavior unless their return is also explicitly unused. Check the protocol signature agrees with the manager signature.

8. In the preview, refresh Portfolios after a valid mapping change. Confirm the displayed revision advances and the control snapshot reports success. Inspect the `copy_result=False` return branch: it must return `None` without calling `_copy_snapshot`. Using an isolated invalid mapping source, refresh again and confirm the existing snapshot is retained and the error is shown. Restore the valid source.

9. Compare refresh duration for the same bounded input. Keep mapping, release and Search rebuild work; this job removes only the unused returned snapshot copy. Verify a caller using the default `copy_result=True` still receives an isolated snapshot.

**Invariants:** default public behaviour remains backward compatible; callers cannot mutate committed frames; same error and atomicity semantics; no connector is skipped merely to save time. Rollback is limited to those three production files and the recorded notebook comparison.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/services/s06_refresh.py', 'cube/app/s02_contracts.py', 'cube/pages/risk/s15_refresh.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete successful and failed isolated Portfolio refresh checks above.
2. The visible revision and error state must match the committed snapshot.
3. Keep default full-snapshot callers working; only the callback with an unused return opts out of copying.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P11')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p12"></a>
## Job P12 — Validate supplemental inputs once within one refresh

### 1. Back up and locate the files

```python
backup_job('P12', ['cube/domain/s05_newtrades.py', 'cube/domain/s04_crossgamma.py', 'cube/services/s06_refresh.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

**Location:** `cube/domain/s05_newtrades.py::new_trade_market_scope` (line 323) and `build_new_trade_rows` (line 519); `cube/domain/s04_crossgamma.py::cross_gamma_market_scope` (line 302) and `build_cross_gamma_rows` (line 493); calls in `cube/services/s06_refresh.py` around lines 2376, 2403, 2701 and 2721.

#### Exact changes for New Trades

1. In `cube/domain/s05_newtrades.py`, rename the current scope function to:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   def _new_trade_market_scope_validated(
       rows: pd.DataFrame,
   ) -> dict[str, tuple[str, ...]]:
   ```

   Delete only `rows = validate_new_trade_rows(raw_or_validated)` from its body. Keep the remaining scope computation. Adjust its docstring to state that its input is already validated and it does not mutate it.

2. Rename the current builder to:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   def _build_new_trade_rows_validated(
       rows: pd.DataFrame,
       market_frames: Mapping[str, pd.DataFrame],
       *,
       multipliers: Mapping[str, float] | None = None,
   ) -> pd.DataFrame:
   ```

   Delete only `rows = validate_new_trade_rows(raw_or_validated)` from its body. Keep the MarketBook mapping guard, multiplier validation, market join, unavailable-data handling, Gamma calculation, cashflows and audit columns.

3. Before `__all__`, add the two original public names as validating wrappers:

   ```python
   def new_trade_market_scope(
       raw_or_validated: object,
   ) -> dict[str, tuple[str, ...]]:
       """Validate an external frame and return its required quote scope."""
       return _new_trade_market_scope_validated(
           validate_new_trade_rows(raw_or_validated)
       )


   def build_new_trade_rows(
       raw_or_validated: object,
       market_frames: Mapping[str, pd.DataFrame],
       *,
       multipliers: Mapping[str, float] | None = None,
   ) -> pd.DataFrame:
       """Validate an external frame and release New Trades."""
       if not isinstance(market_frames, Mapping):
           raise TypeError(
               "market_frames must map Source Type to validated MarketBooks"
           )
       return _build_new_trade_rows_validated(
           validate_new_trade_rows(raw_or_validated),
           market_frames,
           multipliers=multipliers,
       )
   ```

4. Keep the existing public names in `__all__`; do not export the private helpers.

#### Exact changes for Cross Gamma

5. In `cube/domain/s04_crossgamma.py`, rename the current scope function to:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   def _cross_gamma_market_scope_validated(
       rows: pd.DataFrame,
   ) -> dict[str, tuple[str, ...]]:
   ```

   Delete its single `rows = validate_cross_gamma_rows(raw_or_validated)` line. Preserve scope ordering and input/output quote identities.

6. Rename the current builder to:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   def _build_cross_gamma_rows_validated(
       rows: pd.DataFrame,
       market_frames: Mapping[str, pd.DataFrame],
   ) -> pd.DataFrame:
   ```

   Delete its single validator call. Keep the mapping guard, empty-frame schema, source sensitivity rows, portfolio/input/output grain, contribution sums and output-quote handling.

7. Add the original public names before `__all__`:

   ```python
   def cross_gamma_market_scope(
       raw_or_validated: object,
   ) -> dict[str, tuple[str, ...]]:
       """Validate an external frame and return its required quote scope."""
       return _cross_gamma_market_scope_validated(
           validate_cross_gamma_rows(raw_or_validated)
       )


   def build_cross_gamma_rows(
       raw_or_validated: object,
       market_frames: Mapping[str, pd.DataFrame],
   ) -> pd.DataFrame:
       """Validate an external frame and release Cross Gamma positions."""
       if not isinstance(market_frames, Mapping):
           raise TypeError(
               "market_frames must map Source Type to validated MarketBooks"
           )
       return _build_cross_gamma_rows_validated(
           validate_cross_gamma_rows(raw_or_validated), market_frames
       )
   ```

#### Exact manager wiring

8. In `cube/services/s06_refresh.py`, replace the imported supplemental scope/build names with the corresponding private helpers and add the two validator imports. Preserve the column constants:

   ```python
   from cube.domain.s04_crossgamma import (
       CROSS_GAMMA_COLUMNS,
       _build_cross_gamma_rows_validated,
       _cross_gamma_market_scope_validated,
       validate_cross_gamma_rows,
   )
   from cube.domain.s05_newtrades import (
       NEW_TRADE_COLUMNS,
       _build_new_trade_rows_validated,
       _new_trade_market_scope_validated,
       validate_new_trade_rows,
   )
   ```

9. Replace the existing `add_supplemental_scope(cross_gamma_market_scope(raw_cross_gamma))` statement with:

   ```python
   raw_cross_gamma = validate_cross_gamma_rows(raw_cross_gamma)
   add_supplemental_scope(
       _cross_gamma_market_scope_validated(raw_cross_gamma)
   )
   ```

   Place this after the existing loader `try/except`, so the operational-error empty-frame fallback is also validated. Keep it inside the existing loader-enabled branch.

10. Replace the New Trades scope statement with:

    ```python
    raw_new_trades = validate_new_trade_rows(raw_new_trades)
    add_supplemental_scope(_new_trade_market_scope_validated(raw_new_trades))
    ```

11. In the later P&L stage, replace only the function names of `build_cross_gamma_rows(...)` and `build_new_trade_rows(...)` calls with `_build_cross_gamma_rows_validated(...)` and `_build_new_trade_rows_validated(...)`. Keep their arguments, multiplier handling and `_with_supplemental_credit_sp01` wrapper. Change the matching progress `function_name` string to the new helper name so diagnostic locations remain accurate.

12. With small isolated connector frames, check that public builders still reject duplicate identities, invalid axes, nonfinite sensitivities and malformed schemas. Compare the public builder output with the private builder for the same already-validated frame by comparing values, column names, dtypes and row order in the notebook. Keep validation in every external entry point. In the manager, inspect that each successful refresh validates each supplemental frame once, then calls the private builder. Input frames, missing quotes, cashflows, Gamma-developed Delta and totals per Portfolio/output identity must remain unchanged.

**Do not do:** remove adapter validation, use a mutable global cache of supplemental frames, cache them across dates without a source revision, or trust that an arbitrary DataFrame is validated because its columns look right. This change reuses only the result within one already isolated refresh attempt.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/domain/s05_newtrades.py', 'cube/domain/s04_crossgamma.py', 'cube/services/s06_refresh.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the small valid/invalid connector-frame comparisons above.
2. Inspect public entry points: they must still validate external data. Private builders must only receive frames validated in that refresh.
3. Refresh valid supplemental data in the preview and compare Portfolio totals, Gamma-developed Delta and missing-quote behavior.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P12')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p13"></a>
## Job P13 — Replace repeated row checks with grouped product and tenor checks

### 1. Back up and locate the files

```python
backup_job('P13', ['cube/domain/s05_newtrades.py', 'cube/domain/s04_crossgamma.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

**Location:** `cube/domain/s05_newtrades.py::validate_new_trade_rows`, loop at line 311; `cube/domain/s04_crossgamma.py::validate_cross_gamma_rows`, loop at line 252.

#### New Trades replacement

1. Inside `validate_new_trade_rows`, keep everything before `pairs, _ = _product_catalogue()` exactly as it is.
2. Replace the block from that assignment through `_validate_axes(rows, row_index=row_index, spec=spec)` with:

   ```python
   pairs, _ = _product_catalogue()
   market_rows = rows.loc[market]
   for pair, group in market_rows.groupby(
       [RISK_TYPE, RISK_GREEK], sort=False, dropna=False
   ):
       try:
           spec = pairs[pair]
       except KeyError as exc:
           row_index = group.index[0]
           raise ValueError(
               f"New Trades pair {pair!r} is not in PRODUCT_SPECS at row {row_index}"
           ) from exc
       for column in (TENOR_SWAP, TENOR_OPTION):
           blank = group[column].eq("")
           invalid = blank if column in spec.tenor_columns else ~blank
           if invalid.any():
               _validate_axes(
                   rows, row_index=group.index[invalid][0], spec=spec
               )
   ```

3. Keep the final `return rows.reset_index(drop=True)`. Keep `_validate_axes` because the grouped block uses it to produce the authoritative error for an invalid row.

#### Cross Gamma replacement

4. Inside `validate_cross_gamma_rows`, replace the block beginning `pair_catalogue = _product_by_pair()` and ending with `_validate_axes(result, row_index=row_index, spec=spec, side=side)` with:

   ```python
   pair_catalogue = _product_by_pair()
   for side, type_column, greek_column in (
       ("Input", INPUT_RISK_TYPE, INPUT_RISK_GREEK),
       ("Output", OUTPUT_RISK_TYPE, OUTPUT_RISK_GREEK),
   ):
       for pair, group in result.groupby(
           [type_column, greek_column], sort=False, dropna=False
       ):
           row_index = group.index[0]
           if pair == ("Cash Flow", "New"):
               raise ValueError(
                   f"Cross Gamma {side} cannot use Cash Flow/New at row {row_index}"
               )
           try:
               spec = pair_catalogue[pair]
           except KeyError as exc:
               raise ValueError(
                   f"Cross Gamma {side} pair {pair!r} is not in PRODUCT_SPECS "
                   f"at row {row_index}"
               ) from exc
           columns = (
               _INPUT_COLUMNS_BY_AXIS
               if side == "Input"
               else _OUTPUT_COLUMNS_BY_AXIS
           )
           for axis, column in columns.items():
               blank = group[column].eq("")
               invalid = blank if axis in spec.tenor_columns else ~blank
               if invalid.any():
                   _validate_axes(
                       result,
                       row_index=group.index[invalid][0],
                       spec=spec,
                       side=side,
                   )
   ```

5. Keep all checks after this block, particularly expected XGamma/XGamma Vega classification and duplicate full matrix cells. Validate the Cross Gamma replacement with the cases below before accepting it.

6. Check isolated examples for mixed scalar/curve/surface products on both Input and Output sides, blank/forbidden tenor cells, cashflow rejection, unknown pairs, empty frames and duplicate cells. Error ordering can change when several different invalid rows exist: grouping may report a different valid diagnostic first. Do not assert identical first-error ordering unless that is an intentional API requirement; assert the same malformed rows are rejected and valid results remain identical.

**Why this is not overengineering:** it replaces a per-row loop with a per-product loop inside the existing validators. It does not add another data model, framework, cache or validation engine.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/domain/s05_newtrades.py', 'cube/domain/s04_crossgamma.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Use valid scalar, curve and two-axis supplemental examples. The accepted identities and totals must match.
2. Use one invalid product/tenor pair in each isolated example. It must give the existing validation error.
3. Include empty data and missing optional fields; preserve their current outcomes.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P13')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p14"></a>
## Job P14 — Use vectorised finite-number validation

### 1. Back up and locate the files

```python
backup_job('P14', ['cube/domain/s05_newtrades.py', 'cube/domain/s04_crossgamma.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

**Locations:** `cube/domain/s05_newtrades.py` lines 150, 176 and 304; `cube/domain/s04_crossgamma.py` lines 242 and 414.

**Cause:** `.map(np.isfinite)` invokes a scalar function for each value. The operands here have already gone through `pd.to_numeric`; `np.isfinite(series)` performs the same finite-number operation as an array operation and preserves a Series index.

#### Exact replacements

1. In `_finite_numeric` and `_optional_finite_numeric`, replace:

   ```python
   invalid = booleans | numeric.isna() | ~numeric.fillna(0.0).map(np.isfinite)
   ```

   with:

   ```python
   invalid = booleans | numeric.isna() | ~np.isfinite(numeric.fillna(0.0))
   ```

2. In `validate_new_trade_rows`, replace:

   ```python
   nonfinite_traded = known & ~traded_numeric.fillna(0.0).map(np.isfinite)
   ```

   with:

   ```python
   nonfinite_traded = known & ~np.isfinite(traded_numeric.fillna(0.0))
   ```

3. In `validate_cross_gamma_rows`, replace only the finite-check operand:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   | ~converted_sensitivity.map(np.isfinite)
   ```

   with:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   | ~np.isfinite(converted_sensitivity)
   ```

4. In `_build_input_legs` in the same file, replace:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   | ~invalid_move.fillna(0.0).map(np.isfinite)
   ```

   with:

   Source fragment: replace only the named part in the application file; keep its surrounding body. Do not run this fragment in a notebook cell.

   ```text
   | ~np.isfinite(invalid_move.fillna(0.0))
   ```

5. NumPy is already imported in both files. Add no dependency. Do not remove the separate boolean, `isna`, known-trade or market-availability guards. The intermediate `fillna(0.0)` is only part of a validation mask; this change does **not** turn missing financial data into zero.

6. In a notebook, check finite floats, missing values, infinity, booleans, numeric strings, blank optional fields and nonnumeric text. Keep the existing numeric conversion and schema rules: vectorisation must not silently allow a previously invalid input. Use the small conversion check below, then verify the full builder on an isolated valid connector frame.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/domain/s05_newtrades.py', 'cube/domain/s04_crossgamma.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Run the notebook cell below. It shows how the finite-value check treats a numeric string, missing values, infinity and nonnumeric text.
2. Keep the original earlier schema/conversion checks for booleans and optional fields; this cell does not replace those checks.
3. Compare the full builder on a valid isolated connector frame after the edit.

```python
import numpy as np
import pandas as pd
values = pd.to_numeric(pd.Series([1.5, "2.5", None, np.inf, "bad"]), errors="coerce")
finite = np.isfinite(values.to_numpy(dtype=float, na_value=np.nan))
assert finite.tolist() == [True, True, False, False, False]
print("Finite-number conversion check is correct")
```

Expected: the success message. These five example values exist only in notebook memory.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P14')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p15"></a>
## Job P15 — Select the MarketBook once per tenor-reduction batch

### 1. Back up and locate the files

```python
backup_job('P15', ['cube/domain/s11_tenorreduction.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

**Location:** `cube/domain/s11_tenorreduction.py::ReducedTenorReducer._quote_values` (line 510), `_reduce_batch` quote comprehension (line 603), `_reduce_credit_batch` quote loop (line 757).

**Cause:** `_quote_values` selects the same Source Type + Underlying from the full MarketBook each time it is called. Each batch calls it for up to five quote columns. Quote scope does not change between those calls.

#### Minimal exact change

1. In `_reduce_batch`, immediately before the `quote_values_by_column = {` comprehension, insert:

   ```python
   batch_market = market_frame
   if not market_frame.empty:
       batch_market = market_frame.loc[
           market_frame[SOURCE_TYPE].eq(source_type)
           & market_frame[UNDERLYING].eq(underlying)
       ]
   ```

2. Inside that comprehension, replace only the first argument to `self._quote_values` from `market_frame` to `batch_market`. Keep all remaining arguments and the `if column in batch` clause.

3. In `_reduce_credit_batch`, immediately before `for column in MARKET_QUOTE_COLUMNS:`, insert the same `batch_market` block. In that loop replace only the first `_quote_values` argument with `batch_market`.

4. Keep `_quote_values` unchanged. It still verifies scope on a much smaller frame, retains the existing missing-value defaults and resolves connector labels in the same way. Keeping its private signature avoids unnecessary interface changes.

5. With a small isolated MarketBook containing the selected and an unrelated product/underlying, include all five quote columns. Compare complete reduced frames before and after. Missing quotes, market-only tenors, Credit reduction, multiple portfolios and chunked versus unchunked output must retain the same values, dtypes and order.

**Limits:** this does not address the existing first-occurrence quote choice if someone passes conflicting duplicate quotes to this private lookup. Do not treat selecting an arbitrary duplicate as a new optimisation; preserve the authoritative upstream quote uniqueness checks. Matrix/provider caching and the 32 MiB transient tensor budget already exist and should remain.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/domain/s11_tenorreduction.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the isolated MarketBook comparison above.
2. Refresh the same tenor-reduction selection in the preview and compare full output totals and missing quotes.
3. Inspect the new selected MarketBook variable: every column reader in the batch must reuse it while retaining each column's existing aggregation rule.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P15')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p16"></a>
## Job P16 — Bound warning deduplication and unfinished log lines

### 1. Back up and locate the files

```python
backup_job('P16', ['cube/app/s03_logging.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

**Location:** `cube/app/s03_logging.py::_warned` at line 38, `perf_span` around line 385, and `_TerminalTee.write` around line 251.

The published App Logs buffer is already bounded to 200 records with per-record and response character limits. Two adjacent details are different:

- `_warned` stores one `(event, revision)` key for every revision that exceeded a timing budget, without eviction. Usually small, but it grows across a long-lived process.
- `_TerminalTee._pending` accumulates text until a newline arrives. Repeated `print(..., end="")` or a source writing a very long unterminated line can grow this string without a bound. The later per-record truncation does not apply until a completed line is emitted.

Neither is confirmed as a cause of the user's Portfolio crash. They are worthwhile bounded-memory hygiene, not a reason to replace the logging system.

#### Bound warning de-duplication

1. Extend the existing collections import:

   ```python
   from collections import OrderedDict, deque
   ```

2. Replace `_warned: set[tuple[str, object]] = set()` with:

   ```python
   _PERFORMANCE_WARNING_KEY_LIMIT = 512
   _warned: OrderedDict[tuple[str, object], None] = OrderedDict()
   _warned_lock = RLock()
   ```

3. Immediately before the `@contextmanager` decorator above `perf_span`, add the following helper. Keep that decorator attached to `perf_span`, not to the new helper:

   ```python
   def _first_performance_warning(key: tuple[str, object]) -> bool:
       with _warned_lock:
           if key in _warned:
               _warned.move_to_end(key)
               return False
           _warned[key] = None
           while len(_warned) > _PERFORMANCE_WARNING_KEY_LIMIT:
               _warned.popitem(last=False)
           return True
   ```

4. Replace `if over_budget and warning_key not in _warned:` with `if over_budget and _first_performance_warning(warning_key):` and delete the immediately following `_warned.add(warning_key)` line. Keep the actual warning/info emissions unchanged.

5. Replace the body of `reset_performance_warnings` with:

   ```python
   with _warned_lock:
       _warned.clear()
   ```

   An evicted ancient revision may warn again if revisited. That is acceptable for bounded operational diagnostics; if the business needs immutable event history, this logger is not that store.

#### Bound incomplete stdout text

6. Add `_TERMINAL_PENDING_CHAR_LIMIT = 16_384` next to the other logging size constants.

7. In `_TerminalTee.write`, after the existing loop that handles all completed lines, still inside `with self._lock`, add:

   ```python
   if len(self._pending) > _TERMINAL_PENDING_CHAR_LIMIT:
       _APPLICATION_LOG_HANDLER.append_terminal_text(
           self._source,
           self._pending[:_TERMINAL_PENDING_CHAR_LIMIT]
           + " ... [unterminated output truncated]",
       )
       self._pending = ""
   ```

   The original stdout stream has already received the complete text. Only the bounded browser mirror discards the excess. Keep redaction in `append_terminal_text` and the existing output-record cap. One exceptionally large `write()` argument can still exist transiently; this stops accumulation across repeated writes.

8. Use the preview logger with synthetic messages: create more than 512 distinct revision-warning keys and inspect that retention stays bounded. Repeating a retained key must not log twice. The claim-and-insert must remain inside the same lock. Feed repeated newline-free text to the bounded stream helper: `_pending` and browser output must stay bounded while the underlying stream receives the full text. Complete-line behavior and redaction must remain unchanged. Remove the temporary messages after checking.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/app/s03_logging.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the synthetic warning and unfinished-line checks above.
2. Verify normal log lines still appear and redaction remains applied.
3. Inspect both retention guards and the warning lock. Remove the temporary synthetic messages before normal use.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P16')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-p17"></a>
## Job P17 — Remove only proven duplicate temporary-source copies

### 1. Back up and locate the files

```python
backup_job('P17', ['cube/services/s05_sources.py'])
```

Open each listed file in JupyterLab. Locate the symbols named below with `show_symbol`; preserve other functions and imports.

### 2. Make the edits in this order

**Location:** `cube/services/s05_sources.py::_read_temp_csv` (line 183), `get_risk_checker` (line 317), `get_portfolio_config` (line 564), `get_risk_thresholds` (line 587), `get_reported_underlyings` (line 596), `get_pinned_promotions` (line 613).

`_read_temp_csv()` already returns `frame.copy(deep=True)`. Several public temporary loaders immediately copy that caller-owned result again. These files are typically small, so this is housekeeping after higher-impact work.

1. Keep the defensive copy in `_read_temp_csv`. It protects the `lru_cache`'s stored source frame.
2. In `get_risk_checker`, replace `return readiness.copy(), checker.copy()` with `return readiness, checker`.
3. In `get_portfolio_config` and `get_reported_underlyings`, replace only their final `return frame.copy()` with `return frame`. Keep their date/notice/schema checks.
4. Replace `return _read_temp_csv("risk_thresholds").copy()` with `return _read_temp_csv("risk_thresholds")`.
5. Replace `return _read_temp_csv("pinned_promotions").copy()` with `return _read_temp_csv("pinned_promotions")`.
6. Using an isolated synthetic source file, load its frame, change one value in the returned frame, and call the source again. The second result must still contain the original value. Change the source file revision, reload, and confirm the new content is read. Do not use a live financial source for this mutation check.

Do not copy this advice into real site-owned connectors blindly: a real connector may return a shared frame. The proof here depends specifically on the existing `_read_temp_csv` boundary.

### 3. Check syntax and the changed behaviour

```python
check_syntax(['cube/services/s05_sources.py'])
```

Expected: `Syntax OK` for each Python file. The JavaScript helper explains whether its optional syntax checker is available. Restart the preview with Job Z02 before browser checks so it uses the edited files. Syntax alone does not verify values or interactions.

1. Complete the isolated source-mutation check above.
2. Verify source revision changes invalidate the cached value.
3. If isolation cannot be demonstrated, restore this optional change; retaining one copy is preferable to sharing mutable input accidentally.

### 4. Roll back this job only

Stop the preview app using Job Z02. Run `restore_job('P17')`, restart and repeat the checks. Reverse dependent jobs first if they have already changed the same functions.

<a id="job-f01"></a>
## Job F01 — Add Quantity and dQuantity to Stock without changing position identity

**Result:** users can choose Stock, dStock, Quantity and dQuantity as numeric values. Quantity means the current holding; dQuantity means current holding minus the selected prior holding. Complete the Stock scope and server pagination jobs first. Keep their callback bodies and extend their columns; do not restore an older callback to obtain these fields.

1. Run `backup_job("F01", ["cube/pages/stock/s01_data.py", "cube/pages/stock/s03_view.py", "cube/pages/stock/s05_pivot.py"])`. Open those files in the JupyterLab editor.
2. **KEEP** `STOCK_TEXT_COLUMNS`, `STOCK_IDENTITY_COLUMNS`, `STOCK_COLUMNS`, the connector validator, and the archive schema in `cube/domain/s09_stock.py`. Quantity already exists in the source and daily archive. Do not add dQuantity to the source contract; it is a comparison result.
3. In `cube/pages/stock/s01_data.py`, find the import from `cube.domain.s09_stock`. **ADD** `QUANTITY_CHANGE_COLUMN` once, beside `CURRENT_QUANTITY_COLUMN`.
4. Find `STOCK_DISPLAY_COLUMNS`. **ADD** `"dQuantity"` immediately after `"Quantity"`. Keep every existing field and its order otherwise.
5. Find `stock_display_rows`. In its `current.loc[:, [...]]` projection, **ADD** `QUANTITY_CHANGE_COLUMN` immediately after `CURRENT_QUANTITY_COLUMN`. In the `display.rename(columns={...})` mapping, **ADD** `QUANTITY_CHANGE_COLUMN: "dQuantity"`. Keep the prior-only/removed-row decision made in the Stock correctness job; this addition must not silently change that decision.
6. In `cube/pages/stock/s05_pivot.py`, **REPLACE** `STOCK_PIVOT_VALUES` with:

   ```python
   STOCK_PIVOT_VALUES = (
       ("Stock", "Stock"),
       ("dStock", "dStock"),
       ("Quantity", "Quantity"),
       ("dQuantity", "dQuantity"),
   )
   ```

7. **KEEP** `STOCK_PIVOT_DEFAULT_VALUES = ("Stock", "dStock")`. Existing users still start with the same two measures. The extra measures become explicit choices.
8. In the same file, **REPLACE the complete `_metric_value` function only** with:

   ```python
   def _metric_value(frame: pd.DataFrame, metric: str) -> float | None:
       if metric in {"Stock", "dStock"}:
           if frame.empty or frame["Currency"].nunique(dropna=False) != 1:
               return None
       if metric in {"Quantity", "dQuantity"}:
           if frame.empty or len(frame[["Instrument", "Currency"]].drop_duplicates()) != 1:
               return None
       value = pd.to_numeric(frame[metric], errors="coerce").sum(min_count=1)
       return None if pd.isna(value) else float(value)
   ```

   This keeps C04's single-currency rule for existing monetary measures and adds a conservative quantity-unit rule. If the real instrument source says that one Instrument/Currency pair can contain incompatible quantity units, replace the compatibility key with its explicit unit key before enabling Quantity totals. Never display a sum of shares, bond nominal and option contracts as one meaningful quantity.
9. In `cube/pages/stock/s03_view.py`, find `_stock_table_columns` and `build_stock_position_detail`. In each numeric-field collection containing `"Quantity", "Stock", "dStock"`, **ADD** `"dQuantity"`. Keep horizontal scrolling, custom server pagination, and stable row IDs.
10. **KEEP** `s03_view.py::stock_detail_page` from B04: it already allows fields through `STOCK_DISPLAY_COLUMNS` and sorts using the DataFrame's real dtypes; it has no separate numeric allowlist to edit. Adding the fields to `STOCK_DISPLAY_COLUMNS` in step 4 therefore enables its search/sort. Confirm Quantity/dQuantity remain numeric in the server frame. Do not stringify them before sorting or add them only to the first 50 browser records.
11. Run this notebook cell after importing the changed module in a fresh kernel:

   ```python
   import pandas as pd
   from cube.pages.stock.s05_pivot import _metric_value, STOCK_PIVOT_VALUES
   measures = dict(STOCK_PIVOT_VALUES)
   assert {"Stock", "dStock", "Quantity", "dQuantity"} <= set(measures)
   sample = pd.DataFrame({"Instrument": ["DEMO-A", "DEMO-A"],
                          "Currency": ["USD", "USD"],
                          "Quantity": [125.0, 50.0], "dQuantity": [25.0, -10.0]})
   assert _metric_value(sample, "Quantity") == 175
   assert _metric_value(sample, "dQuantity") == 15
   mixed = sample.copy()
   mixed.loc[1, "Instrument"] = "DEMO-B"
   assert _metric_value(mixed, "Quantity") is None
   assert _metric_value(mixed, "dQuantity") is None
   check_syntax(["cube/pages/stock/s01_data.py", "cube/pages/stock/s03_view.py",
                 "cube/pages/stock/s05_pivot.py"])
   ```

12. In an isolated application instance, choose an actual same-identity comparison with known prior/current Quantity. Confirm current minus prior equals dQuantity; for example, 100 then 125 must give 25. Record Stock/dStock before changing the displayed metric and confirm they remain identical afterward. Confirm two Portfolios holding one Instrument remain two positions.
13. Restart the application process and reload Stock. Select the two new metrics, change page, sort Quantity descending, and confirm the largest value appears on the first page even when its original source row was beyond page one.
14. If validation fails, stop the app and restore only the files recorded for F01, then restart. Do not restore archive data; this job changes no persisted financial data.

<a id="job-f02"></a>
## Job F02 — Add an optional ISIN column through a dated metadata lookup

**Result:** ISIN is displayed beside Instrument, with no change to Stock comparison keys or existing historical files. ISIN is metadata. A missing ISIN remains blank.

1. Run `backup_job("F02", ["cube/pages/stock/s01_data.py", "cube/pages/stock/s03_view.py", "cube/pages/stock/s04_callbacks.py", "cube/pages/stock/s06_metadata.py", "cube/app/s07_factory.py", "app.py"])`.
2. **KEEP** the seven-column Stock source/archive contract. **DO NOT ADD** ISIN to `STOCK_TEXT_COLUMNS`, because that tuple also defines position identity. Changing it would break old histories and make a metadata correction look like a removed position plus an added position.
3. **ADD** `cube/pages/stock/s06_metadata.py` with this complete content:

   ```python
   """Optional dated Stock metadata; no financial aggregation."""
   from __future__ import annotations

   import pandas as pd


   def enrich_stock_isin(display: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
       required = ["Instrument", "ISIN"]
       if list(metadata.columns) != required:
           raise ValueError("Instrument metadata must be exactly Instrument, ISIN")
       lookup = metadata.copy()
       for column in required:
           valid = lookup[column].map(
               lambda value: isinstance(value, str) and bool(value.strip())
           )
           if not valid.all():
               raise ValueError(f"{column} must contain nonblank text")
           lookup[column] = lookup[column].astype("string").str.strip()
       if lookup["Instrument"].duplicated().any():
           raise ValueError("Instrument metadata must have one row per Instrument")
       result = display.merge(
           lookup, on="Instrument", how="left", sort=False, validate="many_to_one"
       )
       if len(result) != len(display):
           raise AssertionError("Metadata join changed Stock row count")
       return result
   ```

4. Obtain the real dated Instrument-to-ISIN source. Its application-facing function must have the signature `get_instrument_metadata(as_of_date: pd.Timestamp) -> pd.DataFrame` and return exactly `Instrument, ISIN`. The source location and credentials are site configuration, not values to guess. If no source exists yet, leave this feature unconfigured and display blanks. Do not insert fabricated security identifiers.
5. In `cube/pages/stock/s01_data.py`, change `from dataclasses import dataclass` to `from dataclasses import dataclass, field`. Import `enrich_stock_isin` from `.s06_metadata`.
6. In `StockPageData`, **ADD this last field**, after `portfolio_date`, so old callers still work:

   ```python
   instrument_metadata: pd.DataFrame = field(
       default_factory=lambda: pd.DataFrame(columns=["Instrument", "ISIN"])
   )
   ```

7. In `load_stock_page_data`, **ADD** the keyword argument `instrument_metadata_source=None`. After normalizing `current`, resolve metadata once:

   ```python
   metadata = (
       instrument_metadata_source(current)
       if callable(instrument_metadata_source)
       else instrument_metadata_source
   )
   if metadata is None:
       metadata = pd.DataFrame(columns=["Instrument", "ISIN"])
   if not isinstance(metadata, pd.DataFrame):
       raise TypeError("Instrument metadata source must return a DataFrame")
   # Validate even when the selected Stock scope is empty.
   enrich_stock_isin(pd.DataFrame(columns=["Instrument"]), metadata)
   ```

8. In its `StockPageData(...)` return, **ADD** `instrument_metadata=metadata.copy(deep=True)`. Keep the existing dated Stock reads and Portfolio mapping intact. The callback cache now retains the lookup alongside that loaded Stock date.
9. In `stock_display_rows`, **ADD** keyword argument `instrument_metadata=None`. After the existing `display.rename(...)`, before the final column selection, **ADD**:

   ```python
   if instrument_metadata is None:
       instrument_metadata = pd.DataFrame(columns=["Instrument", "ISIN"])
   display = enrich_stock_isin(display, instrument_metadata)
   ```

10. **ADD** `"ISIN"` immediately after `"Instrument"` in `STOCK_DISPLAY_COLUMNS`. Leave ISIN out of all numeric-field lists and value aggregations.
11. In `cube/pages/stock/s04_callbacks.py::register_callbacks`, **ADD** optional keyword `instrument_metadata_source=None`. Pass it to `load_stock_page_data(...)` in the load callback. In the shared `selected_display(page_data, committed_filter_state, projection="current")` helper from B04/C03, **ADD** `instrument_metadata=page_data.instrument_metadata` to its `stock_display_rows(...)` call and keep `projection=projection`. Add the same metadata argument to other direct `stock_display_rows(...)` calls using a cached `page_data`, including the full-population count/options path. Do not create a second projection helper or restore the removed eighth output in `render_current_stock`.
12. In `cube/pages/stock/s03_view.py::build_stock_page_from_data`, pass `page_data.instrument_metadata` into its display call. In `build_stock_page_from_sources`, add `instrument_metadata_source=None` and forward it to `load_stock_page_data`. Preserve the shell path with empty data.
13. In `cube/app/s07_factory.py::build_app`, **ADD** optional keyword `stock_instrument_metadata_source=None`, and forward it as `instrument_metadata_source=stock_instrument_metadata_source` in `register_stock_callbacks(...)`. In `app.py::create_app`, pass the configured dated metadata callable under `stock_instrument_metadata_source`. If none is configured, omit this argument; the defaults deliberately preserve startup.
14. Search all Python files for `stock_display_rows(` and `load_stock_page_data(`. Check each call individually. The live callback path and the direct component-building path must receive the same metadata; callers intentionally using no metadata may keep the default.
15. Run this plain notebook check. Its identifiers are demonstration strings, not real security claims:

   ```python
   import pandas as pd
   from cube.pages.stock.s06_metadata import enrich_stock_isin
   display = pd.DataFrame({"Instrument": ["DEMO-A", "DEMO-B", "DEMO-A"],
                           "Stock": [10.0, 20.0, 30.0], "Quantity": [1, 2, 3]})
   lookup = pd.DataFrame({"Instrument": ["DEMO-A"], "ISIN": ["DEMO-METADATA"]})
   result = enrich_stock_isin(display, lookup)
   assert len(result) == len(display)
   assert result[["Stock", "Quantity"]].equals(display[["Stock", "Quantity"]])
   assert pd.isna(result.loc[1, "ISIN"])
   try:
       enrich_stock_isin(display, pd.concat([lookup, lookup], ignore_index=True))
   except ValueError:
       pass
   else:
       raise AssertionError("Duplicate Instrument metadata was accepted")
   check_syntax(["cube/pages/stock/s06_metadata.py", "cube/pages/stock/s01_data.py",
                 "cube/pages/stock/s03_view.py", "cube/pages/stock/s04_callbacks.py",
                 "cube/app/s07_factory.py", "app.py"])
   ```

16. Restart and check current/prior dates, server detail paging and blank metadata. Read one existing old archive with no ISIN and confirm it still loads. Change only the demonstration metadata and confirm it does not alter added/removed classification. A lookup must be read once per Stock load, not once per expand, sort or page action. Roll back this job's code only if it fails; retain the authoritative metadata source unchanged.

<a id="job-f03"></a>
## Job F03 — Show Quantity history and discover positions that exist only in the archive

**Result:** the Stock history chart has a Market Value / Quantity control and can load an exact archived position even if it is absent from today's Stock. Complete the exact Stock-history scope fix first.

1. Run `backup_job("F03", ["cube/pages/stock/s02_history.py", "cube/pages/stock/s03_view.py", "cube/pages/stock/s04_callbacks.py"])`.
2. **KEEP** `STOCK_HISTORY_METRICS = ("Quantity", "Market Value")`, the archive identity token functions, the SQL repository, and the preceding-business-day read. Do not derive historical Quantity from current positions.
3. In `cube/pages/stock/s03_view.py::build_stock_history_section`, **ADD** `dcc.RadioItems(id="stock-history-metric", options=[{"label": value, "value": value, "disabled": not available} for value in ("Market Value", "Quantity")], value="Market Value", inline=True, className="cube-segments")` before the Period control. The disabled flag belongs to each option; do not pass an unsupported top-level `disabled` property to `RadioItems`.
4. In `stock_value_history_frame`, **ADD** keyword `metric="Market Value"`. First reject values outside `STOCK_HISTORY_METRICS`. Set `(value_label, delta_label)` to `("Stock", "dStock")` for Market Value or `("Quantity", "dQuantity")` for Quantity. Replace the hardcoded required field, projected numeric field, conversion and groupby measure `"Market Value"` with `metric`. Replace the two result column names with `value_label` and `delta_label`. Keep the business-date reindex and `.diff()` after reindexing.
5. Before the Quantity aggregation, require columns `Instrument` and `Currency` and exactly one distinct Instrument/Currency pair among the selected identities. Return a user-readable validation error for a mixed-unit selection. An empty frame may render an empty chart; a nonempty frame with incompatible units must not produce a fabricated total.
6. In `build_stock_value_history_figure`, **ADD** keyword `metric="Market Value"`; forward it to `stock_value_history_frame`. Use the same two labels for traces, hover text and axes. Keep `connectgaps=False`. Do not fill missing observations with zero.
7. In `cube/pages/stock/s04_callbacks.py::load_stock_history`, **ADD** `Input("stock-history-metric", "value")` immediately after the Period Input and add `metric` in the corresponding function argument position. Pass `metric=metric` to the figure builder. On this trigger, use C03's compact `stock-history-autoload.data` scope: for clicked/manual mode recompute identities on the server from its validated snapshot/filter/path/split/projection and compare its `identity_count`/`identity_fingerprint`. For archive mode read its single explicit identity. Preserve the same scope and dates; do not replace a clicked scope with broad CRDS/Activity. Keep the single-Currency rule for Market Value; a single currency is not sufficient to aggregate different Quantity units.
8. In `build_stock_history_section`, **ADD** a searchable dropdown `stock-history-archive-identity` with empty options, `value=None`, `clearable=True`, and placeholder `Find an archived position`. Label it `Archived position`. Beside it add `html.Button("Reload archived selection", id="stock-history-archive-reload", n_clicks=0, type="button", disabled=True)`. Keep C03's separate manual CRDS/Activity Load action; it intentionally selects a different population. The archive controls are an alternative history identity selection, not a filter on today's Stock.
9. In Stock callback registration, after `query_source` is initialized, add one callback with Outputs `stock-history-archive-identity.options`, `.disabled`, and `stock-history-archive-reload.disabled`, and Inputs `stock-history-archive-identity.search_value`, `clear-cache-complete-store.data`, `stock-history-archive-identity.value`, in that order. When `query_source` is absent or `getattr(query_source, "generation", None)` is not callable, return `([], True, True)`. Otherwise call `query_source.catalog(search_text or "", limit=50)` and return `(list(result.options), False, not bool(selected_archive_token))`. On invalid search/read error return `([], False, True)` and log the error. Keep search terms as values passed to the existing repository; do not interpolate them into SQL. This sends at most 50 choices, not the complete archive catalog.
10. Extend C03's `select_stock_row` callback, the sole owner of `stock-history-autoload.data`, by appending Inputs `stock-history-archive-identity.value` and `stock-history-archive-reload.n_clicks`, State `stock-history-metric.value`, and a fourth Output `stock-history-metric.value`; add matching parameters in decorator order. Keep its first three outputs in C03's CRDS/Activity/autoload order. For clicked metric Quantity/dQuantity, output `"Quantity"`; for Stock/dStock, output `"Market Value"`; preserve the current metric for a Hierarchy/manual/archive action. Update every return to contain four values, appending `no_update` on branches that do not change the metric. This synchronizes the visible selector and chart when a Quantity cell is clicked. When `ctx.triggered_id` is either archive control and its token is nonempty, decode with `stock_history_identity_from_token`, call `query_source.generation()` and write `{"mode": "archive", "identities": [decoded_identity], "label": " · ".join(decoded_identity.values()), "metric": metric, "archive_generation": generation}` to that same Store. Return `(decoded_identity["CRDS"], None, payload, no_update)`; the archive path does not need a fabricated Activity. Preserve clicked/manual branches and their compact scope/count/fingerprint fields. `load_stock_history` already listens to the Store, so do not add a competing callback owner or duplicate archive Input there. In archive mode require exactly one decoded identity, compare its stored generation to `query_source.generation()`, and require the new Reload archived selection action if changed. Do not require `cached_page(loaded_snapshot)` in that branch. Add the following read-only method immediately after `SQLStockHistoryRepository.clear`, and add `import hashlib` to `s02_history.py`:

   ```python
   def generation(self) -> str:
       with self._lock:
           days = list_queryable_v4_archive_days(self._root)
           signature = []
           for day in days:
               if day.stock_path is None:
                   continue
               stock_stat = day.stock_path.stat()
               marker_stat = (day.path / "_SUCCESS").stat()
               signature.append((
                   day.snapshot_date, day.revision, str(day.stock_path.resolve()),
                   stock_stat.st_size, stock_stat.st_mtime_ns,
                   marker_stat.st_size, marker_stat.st_mtime_ns,
               ))
           payload = json.dumps(signature, separators=(",", ":"))
           return hashlib.sha256(payload.encode("utf-8")).hexdigest()
   ```

   **KEEP** `StockHistoryQueryProtocol` unchanged so existing query-source injections remain usable. Check the extra `generation` capability with `callable(getattr(query_source, "generation", None))` only for the new archive-picker path. Legacy callable/query history still serves current/manual selections. Use filesystem metadata only as a generation signal; retain strict manifest/schema/payload validation when actually reading values. A generation mismatch must not silently relabel old values as new. Pressing Reload archived selection rematerializes that same exact identity with a new generation. The extended selection callback's argument order must be four Inputs first (active cell, manual Load clicks, archive token, archive reload clicks), then its nine States (loaded snapshot, committed filters, pivot rows, pivot column, pivot values, projection, manual CRDS, manual Activity, history metric). Add archive Inputs before the existing State block, not after it.
11. In `load_stock_history`, after its Clear Cache early return, **ADD the archive-mode branch before calling C03's current/manual selection resolver**. Check `selection["mode"] == "archive"`, validate one identity using the existing token encode/decode functions, require the query source's generation capability and a current generation, then use that one identity directly. Do not ask C03's compact current-scope resolver to parse archive mode. For all other modes keep its existing snapshot/filter/path/count/fingerprint checks. Preserve P08's metadata-only date lookup: when `isinstance(query_source, StockHistoryBatchQueryProtocol)`, use `bounds = query_source.bounds()`; otherwise use `bounds = query_source.catalog(limit=1)` for the existing compatible query source. Both return `StockHistoryCatalogResult`; use `.minimum_date`/`.maximum_date` without requesting identity options from the batch source. No current Stock date is needed for an archive-only selection. Use its Instrument/Portfolio in the caption; do not invent an Activity that is not in the archive identity. Keep the shared bounded read/normalize/figure path after these branches so both produce the same history-frame contract.
12. Preserve the existing figure function's required CRDS/Activity parameters. For the archive path, pass the identity's CRDS and a truthful display label `"Archived position"` as `activity`; that value is a caption only and is never used to filter financial rows. Do not rename that argument during this job.
13. Run this notebook check of the calculation:

   ```python
   import pandas as pd
   from cube.pages.stock.s02_history import stock_value_history_frame
   rows = pd.DataFrame({"Stock Date": ["2026-08-19", "2026-08-20"],
                        "Instrument": ["DEMO-A", "DEMO-A"],
                        "Currency": ["USD", "USD"],
                        "Quantity": [100.0, 125.0], "Market Value": [1000.0, 1300.0]})
   result = stock_value_history_frame(rows, start_date="2026-08-20",
                                      end_date="2026-08-20", metric="Quantity")
   assert result["Quantity"].iloc[0] == 125
   assert result["dQuantity"].iloc[0] == 25
   gap = stock_value_history_frame(rows.iloc[1:], start_date="2026-08-20",
                                   end_date="2026-08-20", metric="Quantity")
   assert pd.isna(gap["dQuantity"].iloc[0])
   check_syntax(["cube/pages/stock/s02_history.py", "cube/pages/stock/s03_view.py",
                 "cube/pages/stock/s04_callbacks.py"])
   ```

14. Restart; type an archived-only Instrument, select it, choose Custom, and change the metric. Its scope must stay selected. Compare its observation count to the archive reader; three existing dated observations must remain three. Try a mixed-instrument Quantity selection and confirm the clear unit-selection error. Restore F03 code if validation fails; archive contents require no rollback.

<a id="job-f04"></a>
## Job F04 — Create isolated demonstration history and verify all three history readers

**Result:** Data, Stock and P&L history can be checked with clearly labelled synthetic observations. This creates demonstration data only. It does not recover past real positions.

1. Install the complete `tools/s05_demo_history.py` and `tools/s06_read_demo_history.py` bodies from code packs [CODE-DEMO-HISTORY](#code-demo-history) and [CODE-READ-HISTORY](#code-read-history) in this document. If a file already exists with the same content, **KEEP** it and do not install it twice. Run `check_syntax(["tools/s05_demo_history.py", "tools/s06_read_demo_history.py"])`.
2. In a Jupyter notebook, choose an empty sibling directory outside the application folder and run:

   ```python
   import subprocess
   DEMO_ROOT = APP_ROOT.parent / "rebirth-demo-history"
   subprocess.run(
       [PYTHON, "-m", "tools.s05_demo_history", "--start", "2026-08-19",
        "--end", "2026-08-21", "--output", str(DEMO_ROOT)],
       cwd=APP_ROOT, check=True,
   )
   subprocess.run(
       [PYTHON, "-m", "tools.s06_read_demo_history", "--archive", str(DEMO_ROOT)],
       cwd=APP_ROOT, check=True,
   )
   ```

3. **KEEP** the helper's governed synthetic date restriction and its refusal to write inside the application folder or mix real and synthetic archives. For the shipped fixture builder the supported range is 2025-08-21 through 2026-08-21. Do not remove that restriction to label current data as a different date.
4. Expect three completed date folders, each containing `risk.parquet`, `market.parquet`, `colossus.parquet`, `stock.parquet`, and `_SUCCESS`. `_SUCCESS` is a JSON manifest containing schema, date, row counts, ordered columns and payload hashes. **DO NOT** create it manually or alter completed parquet files under it.
5. Run the same generation command again. Expect `already_archived` for each completed date and identical existing file hashes. The reader must identify the data as synthetic and load Risk, Market, P&L and Stock through the real archive APIs.
6. To view it in an isolated app process, make a copy of the process environment and set `PL_HISTORICAL_PATH` to `str(DEMO_ROOT)` there. Keep the normal launch procedure and its JupyterHub proxy configuration from the setup job. Choose All or Custom dates 2026-08-19 through 2026-08-21 in the pages. The setting controls history readers; it does not replace today's connectors.
7. Verify P&L has Predict and Colossus observations; Data can select scalar Risk and Market; Stock can select an exact archived position using F03. If a chart is empty, check identity and requested dates before generating more data.
8. Stop the isolated process and remove only its environment override when done. Keep production history, demonstration history and adjustment storage separate. No production files need replacing or deleting.

<a id="job-f05"></a>
## Job F05 — Capture coherent daily Risk, Market, actual P&L and Stock

**Result:** the existing scheduled archive entry point also captures Stock, using a same-date validated Stock source. The official archive remains one immutable completed cut per Market Date.

1. Run `backup_job("F05", ["tools/s02_archive.py"])`. **KEEP** the notebook `jobs/s01_archive.ipynb` and its import of `tools.s02_archive.run_from_env`. The implementation stays in that same module.
2. Before enabling real capture, configure authoritative Risk/Open/Current connectors, historical Portfolio/reporting authority, a dated actual-P&L loader, and the dated Stock callable. The application-facing actual-P&L columns must be exactly `Portfolio, Underlying, Risk Type, Risk Greek, PL`, unique on its first four columns. Stock must be exactly `CRDS, CPTY, Portfolio, Instrument, Currency, Quantity, Market Value`. Missing real source details require site configuration; never guess credentials, dates or rows.
3. In `tools/s02_archive.py`, **ADD** `from types import SimpleNamespace`, `import pandas as pd`, `from cube.adapters.s08_stock import build_stock_adapter`, and `from cube.domain.s03_calculations import market_date_for`. In the `cube.history` import block, **REPLACE** `archive_from_manager` with `archive_official_snapshot`. Keep `ArchiveResult`, `ColossusLoader` and the existing `Path` import.
4. **ADD this whole function** immediately after `_default_manager_factory` and before `run_scheduled_archive`:

   ```python
   def archive_with_stock(manager, colossus_loader, get_stock, root):
       snapshot = manager.refresh(
           force_risk=True, force_pl=True, reason="scheduled_official_archive"
       )
       stock_date = pd.Timestamp(snapshot.market_date).normalize()
       natural_date = market_date_for(snapshot.system_date).normalize()
       if (str(snapshot.market_status).strip() != "OFFICIAL"
               or snapshot.errors or stock_date != natural_date):
           return archive_official_snapshot(snapshot, colossus_loader, root)
       leaf = Path(root).expanduser().resolve() / stock_date.date().isoformat()
       if leaf.exists():
           result = archive_official_snapshot(snapshot, colossus_loader, root)
           if not (leaf / "stock.parquet").is_file():
               raise ValueError("Completed daily leaf lacks Stock; repair is required")
           return result
       stock = build_stock_adapter(stock=get_stock).get_stock(stock_date)
       capture = SimpleNamespace(
           revision=snapshot.revision,
           refreshed_at=snapshot.refreshed_at,
           system_date=snapshot.system_date,
           market_date=snapshot.market_date,
           market_status=snapshot.market_status,
           risk_dates=snapshot.risk_dates,
           dashboard_frame=snapshot.dashboard_frame,
           market_frame=snapshot.market_frame,
           errors=snapshot.errors,
           stock_date=stock_date,
           stock_frame=stock,
       )
       return archive_official_snapshot(capture, colossus_loader, root)
   ```

5. In `run_scheduled_archive`, **ADD** keyword `stock_loader: Callable | None = None` after `colossus_loader`. Keep root resolution, `COLOSSUS_LOADER` resolution and manager construction. **REPLACE only its final return** with:

   ```python
   if stock_loader is None:
       from cube.adapters.s08_stock import get_stock
       stock_loader = get_stock
   return archive_with_stock(manager, loader, stock_loader, root)
   ```

6. **KEEP** `run_from_env()` unchanged. In `main()` add `stock_rows={result.stock_rows}` to the printed row counts. Add `archive_with_stock` to the existing `__all__` export list. Do not add an undocumented environment setting; the default Stock boundary is the same `get_stock` used by `app.py`. A site runner may pass `stock_loader=site_get_stock` explicitly.
7. Keep the writer's eligibility checks and temporary-leaf publication. A failing Stock read must occur before a date is marked complete. A skipped snapshot is not a successful daily capture. A completed older leaf without Stock is not repaired by rerunning this function; preserve it and perform a separately validated migration with backups if historical Stock must be added.
8. Run `check_syntax(["tools/s02_archive.py"])`. In an isolated notebook directory, call `run_scheduled_archive` with a controlled manager/dated sources before enabling a schedule. Wrap the manager's refresh callable with a counter; one archive attempt must call refresh once. Repeat with non-OFFICIAL status and with snapshot errors: Stock must not be read and no completed date may appear. Make the injected Stock callable raise `RuntimeError("Demonstration Stock failure")`; no completed date may appear. Restore the valid callable, run once successfully, then repeat and compare every existing file hash; they must be unchanged. Keep these checks separate from the real history root.
9. Query the successful isolated leaf with `SQLStockHistoryRepository.rows` for one exact identity and compare its Quantity/Market Value to the injected source rows with plain `assert` statements. Inspect `_SUCCESS` and confirm Stock rows, columns and hash are present. F04 supplies the independent demonstration reader command for the complete archive; use it only on its tagged demonstration output, not on untagged real captures.
10. Configure a persistent mounted `PL_HISTORICAL_PATH` outside the application folder. Resolve the real Colossus function as `COLOSSUS_LOADER="site_module:get_colossus_pl"` only after that module exists and its dated function has been validated. Do not treat an object-storage URI as a local filesystem `Path`.
11. In Jupyter Scheduler, use the existing archive notebook, the project's Python environment, and the configured environment variables. Schedule one attempt at a time after the site's real official cut. The time must come from the source owner. Do not assume that every source becomes official at a universal clock time.
12. Define three monitored outcomes: completed/already-completed; skipped/not-yet-official; failed. Retry transient failed or not-yet-official captures under the runner's existing policy. Alert when the expected completed date is absent by the agreed deadline. A zero process exit with `status="skipped"` is not evidence of captured history.
13. Validate the first real completed leaf with `list_completed_v4_archive_days` and the three page readers before relying on the schedule. Restart or clear application history caches so the newly completed dates can be discovered. Keep Predict derived from archived `PL`; do not add an independently calculated competing prediction file.
14. For a genuine backfill, first implement a site function `build_dated_capture(day)` that reads all real dated sources plus their historical configuration and returns the same validated snapshot/Stock fields. Reconcile one historical day against the authoritative report. Only then loop over explicitly requested historical dates and call the existing writer. **KEEP** the current live manager clock and current feeds untouched; changing a live snapshot's label is not a backfill.
15. Rollback: stop the schedule first; restore the F05 code; restart the app if needed. Keep already completed validated archive leaves. Do not delete financial history as part of a code rollback.

<a id="job-f06"></a>
## Job F06 — Keep adjustment versions and active values in one transaction

**Result:** every saved adjustment change can be reconstructed. Implement after the replacement-adjustment arithmetic and version-aware Save job. The active value remains a replacement value: base 100 and entered adjustment 10 gives effective 10.

1. Run `backup_job("F06", ["cube/services/s03_adjustments.py", "cube/services/s09_adjustment_audit.py", "cube/app/s02_contracts.py", "cube/pages/pnl/s01_common.py", "cube/pages/pnl/s02_editor.py", "cube/pages/pnl/s05_sendcallbacks.py", "app.py"])`. Stop all application writers during the later migration step; source editing and isolated notebook checks may be done beforehand.
2. **KEEP** the already defined contracts `load_versioned(market_date) -> (frame, version)`, `load(market_date) -> frame`, and `apply_changes(market_date, rows, *, base_revision, expected_version, delete_keys=()) -> version`. Keep explicit deletion of only named three-part keys, preservation of untouched keys, and the stale-editor check. **REMOVE** direct UI calls to the CSV `save()` method if any remain.
3. **ADD** `cube/services/s09_adjustment_audit.py`. Use Python `sqlite3`; do not introduce an ORM or another service. Put `SQLiteAdjustmentRepository` in this module, with `__init__(self, database_path)` resolving the explicitly supplied database file path. The database path must be on persistent storage with working local file locks. For a shared deployment whose filesystem does not support SQLite locking, use the site's existing transactional database instead; do not claim a network share makes SQLite safely distributed.
4. Create these tables at repository initialization, in one connection. Keep `PRAGMA foreign_keys=ON` and `PRAGMA busy_timeout=10000` on every connection. Do not hold one SQLite connection in a module-global object across request threads.

   ```sql
   CREATE TABLE IF NOT EXISTS adjustment_state (
       market_date TEXT PRIMARY KEY,
       payload_json TEXT NOT NULL,
       version TEXT NOT NULL
   );
   CREATE TABLE IF NOT EXISTS adjustment_events (
       event_id TEXT PRIMARY KEY,
       request_id TEXT NOT NULL UNIQUE,
       occurred_at_utc TEXT NOT NULL,
       actor TEXT NOT NULL,
       reason TEXT NOT NULL,
       action TEXT NOT NULL CHECK (action IN ('change', 'import')),
       market_date TEXT NOT NULL,
       base_revision INTEGER NOT NULL,
       before_version TEXT NOT NULL,
       after_version TEXT NOT NULL,
       before_json TEXT NOT NULL,
       after_json TEXT NOT NULL,
       delete_keys_json TEXT NOT NULL,
       request_json TEXT NOT NULL
   );
   ```

5. Keep one active JSON payload per Market Date. This stores a small adjustment set, not all Risk positions. Serialize exactly `PERSISTED_ADJUSTMENT_COLUMNS` in their existing order, with rows sorted by `ADJUSTMENT_KEY`, `allow_nan=False`, UTF-8, and canonical JSON separators. Normalize numeric and boolean values with the current domain validator before serialization. Compute `version = sha256(payload_json.encode("utf-8")).hexdigest()`. Preserve Adjustment ID/time in the payload so a saved version changes even if the numeric values happen to match.
6. Implement `load_versioned`: normalize the date, open one connection, SELECT the active record, deserialize to the exact persisted DataFrame schema, validate its keys/revisions/timestamps/Adjustment flags, recompute and compare its hash, return the frame and version. If no row exists, return the correctly typed empty persisted frame and the canonical empty-payload hash. Implement `load` by returning element zero. A malformed record is an error, never an empty replacement.
7. Extend `apply_changes` with required keyword arguments `actor`, `reason`, and `request_id`. These are server-side audit context. Begin its connection with `BEGIN IMMEDIATE`, then execute these operations in this exact order:
   1. Normalize and validate the Market Date, nonnegative base revision, nonblank actor, nonblank reason and request ID. Normalize the incoming rows with `normalize_pl_send_rows`. Require Adjustment=True, matching Market Date, and unique `ADJUSTMENT_KEY`.
   2. Query `adjustment_events` for `request_id`. If found, compare date, actor, reason and canonical intended changes with the recorded request. Return its `after_version` for the exact same request; reject a reused ID with different contents. Store the canonical request fields as additional event columns if needed for this comparison; do not infer equivalence from before/after values alone.
   3. Read the current active payload and version inside this same transaction. Require `expected_version` to equal that version. Reject a stale version without changing active state or appending a successful event.
   4. Validate every explicit deletion key is a length-three tuple for this Market Date. Reject a key present in both incoming replacements and deletions. Keep all old keys not mentioned by the request. Reject replacement/deletion of rows with a Base Revision newer than the incoming base revision.
   5. Create new persisted rows for incoming keys using the normalized PL send fields plus this revision, UTC saved time and a new Adjustment ID per row. Preserve untouched rows byte-for-byte at the record level. Remove only explicit delete keys. Sort and validate the complete candidate.
   6. Compute the new canonical payload/hash. INSERT the event with full before and after payloads and versions. UPSERT `adjustment_state` for the date. COMMIT once. On any exception ROLLBACK both operations.
   7. Return the committed version. There must be no active CSV write after this transaction.
8. Populate the schema's `request_json` field with canonical normalized incoming rows, deletion keys, date, actor, reason and base revision. Use this exact field for step 7.2's replay check. Keep the schema definition above as the initial schema; do not add a repeated startup `ALTER TABLE` statement.
9. In `PLSendConfig` in `cube/pages/pnl/s01_common.py`, **ADD** `actor_provider: Callable[[], str] | None = None`. Resolve it in `app.py` from the deployment's authenticated request identity boundary. Do not trust a name typed into the browser or infer the actor from a process user shared by everyone. If no trusted identity provider is configured, keep audit Save disabled with a clear configuration message; do not silently write `unknown` as if it identified a user.
10. In the P&L editor layout, add a labelled reason input and include its value as State in `save_adjustments`. Generate a UUID request ID in the server when the loaded draft is materialized, retain it in that browser's draft store, and regenerate it after successful Save or any draft change. Repeated delivery of the same Save uses the same request ID.
11. In `_merge_and_persist_adjustments` and `save_adjustments`, forward expected version, explicit deletion keys and the three audit fields. Obtain `actor` by calling `config.actor_provider()` during the request. Keep the returned version in the loaded editor store. Clear the saved draft only after success. A concurrency conflict leaves the draft visible and asks the user to reload/review, not to overwrite automatically.
12. In `cube/app/s02_contracts.py::AdjustmentRepositoryProtocol`, replace the obsolete `save`-based requirement with the three live signatures `load`, `load_versioned`, and `apply_changes` including the audit keyword arguments from step 7. Keep the old CSV compatibility writer for explicit import/recovery only. Run this notebook cell against a temporary database before changing `app.py`:

   ```python
   import tempfile
   import sqlite3
   import pandas as pd
   from pathlib import Path
   from cube.services.s09_adjustment_audit import SQLiteAdjustmentRepository
   from cube.services.s03_adjustments import AdjustmentPersistenceError
   from cube.domain.s08_pnl import PL_SEND_COLUMNS
   with tempfile.TemporaryDirectory() as temporary:
       database = Path(temporary) / "adjustments.sqlite"
       repository = SQLiteAdjustmentRepository(database)
       day = "2026-08-21"
       rows = pd.DataFrame([{
           "Market Date": day, "Risk Type": "IR", "Risk Greek": "Delta",
           "Portfolio": "DEMO-BOOK", "SignoffGroup": "DEMO-SOG",
           "ConcertoField": "DEMO-FIELD", "PL": 125.0, "Adjustment": True,
       }], columns=list(PL_SEND_COLUMNS))
       _, version0 = repository.load_versioned(day)
       version1 = repository.apply_changes(day, rows, base_revision=1,
           expected_version=version0, actor="isolated-notebook", reason="Demonstration",
           request_id="demo-create")
       changed = rows.copy()
       changed["PL"] = 150.0
       version2 = repository.apply_changes(day, changed, base_revision=1,
           expected_version=version1, actor="isolated-notebook", reason="Demonstration",
           request_id="demo-change")
       assert repository.load(day)["PL"].tolist() == [150.0]
       assert version0 != version1 != version2
       try:
           repository.apply_changes(day, rows, base_revision=1,
               expected_version=version1, actor="isolated-notebook", reason="Stale edit",
               request_id="demo-stale")
       except AdjustmentPersistenceError:
           pass
       else:
           raise AssertionError("A stale adjustment version was accepted")
       with sqlite3.connect(database) as connection:
           assert connection.execute("SELECT count(*) FROM adjustment_events").fetchone()[0] == 2
       assert repository.load(day)["PL"].tolist() == [150.0]
   check_syntax(["cube/services/s09_adjustment_audit.py", "cube/app/s02_contracts.py",
                 "cube/pages/pnl/s01_common.py", "cube/pages/pnl/s02_editor.py",
                 "cube/pages/pnl/s05_sendcallbacks.py", "app.py"])
   ```

   Also clear that saved key with an explicit delete, verify a separate untouched key remains, and inspect before/after JSON. Replaying `demo-change` with its identical request must return the same version without another event. A different request body with that ID must raise. Before real use, run two notebook processes against the same temporary database/version: exactly one competing change may commit; the other must report a stale version.
13. Migrate existing data once, with the app and schedules stopped. Read each existing date through `LocalCsvAdjustmentRepository.load`; do not read arbitrary CSVs with relaxed validation. For each date, write one `action='import'` event and its active state in one SQLite transaction, retaining original Adjustment IDs, Saved At UTC and Base Revision. Use an explicit migration actor and reason; the import is not evidence of who made historic edits. Reject a nonempty destination unless the exact import request has already completed.
14. Compare sorted imported frames with source frames for every date, including all persisted fields, row counts and totals. Back up the database with SQLite's backup API. Only after these checks change `app.py` to inject `SQLiteAdjustmentRepository` instead of `LocalCsvAdjustmentRepository`. Make old CSV storage read-only and retain it for recovery; do not keep two live writers.
15. Restart the isolated application and use both SOG Save and Portfolio Save with demonstration rows. Verify they create the same repository event format. Inspect an event with a read-only SQL query to confirm before/after values and actor. Code rollback after new SQLite edits must retain/export those edits first; switching blindly to the old CSV directory would lose subsequent saves.

<a id="job-f07"></a>
## Job F07 — Record exactly what P&L was sent and whether delivery was confirmed

**Result:** each destination has its own persisted send attempt and outcome. Sending remains an explicit user action; no automatic delivery or retry is added.

1. Run `backup_job("F07", ["cube/services/s10_send_ledger.py", "cube/pages/pnl/s01_common.py", "cube/pages/pnl/s05_sendcallbacks.py", "app.py"])`. Complete effective-value and saved-draft consistency checks first.
2. Add `cube/services/s10_send_ledger.py` with a small SQLite `SendLedger` class whose constructor is `__init__(self, database_path)`, using the same per-operation connection pattern as F06. Create `send_attempts` with columns `request_id TEXT PRIMARY KEY`, `destination TEXT NOT NULL`, `created_at_utc TEXT NOT NULL`, `actor TEXT NOT NULL`, `market_date TEXT NOT NULL`, `snapshot_revision INTEGER NOT NULL`, `adjustment_version TEXT NOT NULL`, `scope_json TEXT NOT NULL`, `payload_json TEXT NOT NULL`, `payload_sha256 TEXT NOT NULL`, `status TEXT NOT NULL`, `completed_at_utc TEXT`, `receipt_json TEXT`, `error_text TEXT`. Constrain status to `prepared`, `accepted`, `rejected`, or `unknown`.
3. Implement `prepare(self, *, request_id, destination, actor, market_date, snapshot_revision, adjustment_version, scope, payload)`: serialize the exact governed DataFrame payload after the final `collapse_pl_send_rows`, including ordered columns and exact records; reject nonfinite values; hash the bytes; insert `prepared` before calling any sender. Enforce unique request ID in the database transaction and return `(record, created)` where `created` is true only for this invocation's successful new insert. On repeat, return the existing record with `created=False` only when destination, payload hash, scope, revision and adjustment version match; otherwise reject. The caller must invoke the sender only when `created=True`; matching a pre-existing prepared record is not permission to send it again.
4. Implement `finish(request_id, status, receipt=None, error=None)` as one transaction updating only an existing `prepared` or `unknown` row. Require status accepted/rejected/unknown, preserve the original payload permanently, and record completion time. Record provider receipt if present. A database failure after network delivery must be reported as an unresolved outcome rather than a clean failure.
5. Add a `send_ledger` field to `PLSendConfig` and inject it from `app.py`. Reuse its authenticated `actor_provider`. Keep sender adapters' financial payload schema unchanged.
6. In `cube/pages/pnl/s05_sendcallbacks.py::send_rows`, locate the direct `sender(rows[list(DISPLAY_COLUMNS)].copy())` call. **REPLACE that call only** with this sequence: capture the current saved adjustment version and committed scope; prepare the ledger record; if `created=False`, return its recorded outcome without sending; otherwise call the selected sender exactly once; classify a documented confirmed acceptance as accepted, a documented definite rejection as rejected, and a timeout/connection loss/unclassified exception as unknown; persist that outcome; show request ID and outcome in the existing status component. Keep all current date/revision/governance/scope checks before preparation. Store the send request ID in the loaded action state before submission and reuse it for duplicate delivery of that action; generating a new ID on every callback retry would defeat this rule.
7. The current `SendFunction` contract returns `None`. Do not label `None` as a provider receipt. If the actual site's callable guarantees that returning normally means acceptance, record acceptance with `receipt_json=null` and identify the adapter contract in its docstring. Otherwise extend that adapter to return a documented result with accepted/rejected and receipt, update `SendFunction` accordingly, and verify that boundary with stubs before claiming delivery confirmation.
8. In `send_all`, replace each destination's direct sender call with the same ledger helper. Generate a separate request ID for SOG and Portfolio. If SOG succeeds and Portfolio is unknown, show the distinct outcomes. Do not resend SOG while resolving Portfolio.
9. Change generic exception wording from `failed` to `outcome unknown` when delivery cannot be ruled out. Disable automatic retry of prepared/unknown requests. On process startup, treat old `prepared` attempts as unresolved; a crash may have happened after delivery and before receipt persistence. Reconcile them against the provider's lookup/idempotency mechanism before any operator-authorized retry.
10. Run this notebook cell with a temporary ledger; it invokes no sender:

   ```python
   import tempfile
   import sqlite3
   import pandas as pd
   from pathlib import Path
   from cube.services.s10_send_ledger import SendLedger
   with tempfile.TemporaryDirectory() as temporary:
       database = Path(temporary) / "send.sqlite"
       ledger = SendLedger(database)
       arguments = dict(request_id="demo-send", destination="DEMO",
           actor="isolated-notebook", market_date="2026-08-21", snapshot_revision=1,
           adjustment_version="demo-version", scope={"Portfolio": ["DEMO-BOOK"]},
           payload=pd.DataFrame({"Portfolio": ["DEMO-BOOK"], "PL": [10.0]}))
       first, created = ledger.prepare(**arguments)
       assert created is True
       second, created_again = ledger.prepare(**arguments)
       assert created_again is False
       assert first["payload_sha256"] == second["payload_sha256"]
       ledger.finish("demo-send", "unknown", error="Demonstration timeout")
       with sqlite3.connect(database) as connection:
           assert connection.execute("SELECT status FROM send_attempts").fetchall() == [("unknown",)]
   check_syntax(["cube/services/s10_send_ledger.py", "cube/pages/pnl/s01_common.py",
                 "cube/pages/pnl/s05_sendcallbacks.py", "app.py"])
   ```

11. Restart an isolated application with sender stubs that increment a notebook-visible counter instead of contacting a destination. Repeat the same action twice; the counter must remain one. Make a stub raise a timeout; status must be unknown and replay must not call it again. Make SOG accept and Portfolio return a definite rejection; retain two distinct records. Stop before the sender if preparation fails. Keep real Send buttons governed by the normal application workflow. A code rollback must preserve the ledger database; delivery records must not be deleted because UI code is restored.

<a id="job-f08"></a>
## Job F08 — Keep durable diagnostic logs and optional intraday snapshots

**Result:** application errors survive a process restart. Optional intraday capture is separate from daily official history and separate from adjustment/send records.

1. Run `backup_job("F08", ["cube/app/s03_logging.py", "cube/services/s02_state.py", "cube/services/s05_sources.py", "cube/services/s06_refresh.py", "cube/services/s11_intraday_capture.py", "app.py"])`. Do the diagnostic-log steps first. Leave intraday capture disabled until the remainder passes.
2. In `cube/app/s03_logging.py`, keep the existing `os` import and add `from pathlib import Path` and `from logging.handlers import RotatingFileHandler`. **ADD this complete helper** immediately before `configure_runtime_logging`:

   ```python
   def configure_file_logging(directory):
       root = Path(directory).expanduser().resolve()
       root.mkdir(parents=True, exist_ok=True)
       path = root / f"application-{os.getpid()}.log"
       logger = logging.getLogger()
       for handler in logger.handlers:
           filename = getattr(handler, "baseFilename", None)
           if filename is not None and Path(filename).resolve() == path:
               return path
       handler = RotatingFileHandler(
           path, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
       )
       handler.setFormatter(logging.Formatter(
           "%(asctime)s %(levelname)s %(name)s %(message)s"
       ))
       logger.addHandler(handler)
       return path
   ```
3. In `configure_runtime_logging`, after root level is set, call that helper only when a new documented `CUBE_LOG_DIRECTORY` setting is nonblank. Keep the existing bounded browser log handler and safe metric filtering. Do not add positions, credentials, full payloads or financial values to timing messages. A shared production log collector may replace the file handler using the deployment's existing facilities.
4. In a notebook, call `configure_file_logging` twice with the same temporary directory. Inspect `logging.getLogger().handlers`: exactly one handler may have that resolved `baseFilename`. Emit `logging.warning("Demonstration log line")`, flush the handler, read that file and assert the phrase occurs once. Restart the process and verify old logs remain. Add disk-retention/backup policy to the deployment configuration; five files per process is a starting limit, not an unlimited archive.
5. For intraday financial capture, define a separate persistent root `RISK_INTRADAY_PATH`. Keep it outside daily completed date leaves. Use directories `YYYY-MM-DD/<process-run-id>/<revision>/` containing `risk.parquet`, `market.parquet`, `unmapped.parquet`, and `metadata.json`. A process-run UUID is created once at manager construction; revision alone is not globally unique after restarts.
6. In `cube/services/s11_intraday_capture.py`, add `capture_committed_snapshot(snapshot, root, run_id)`. Validate that the snapshot has its committed revision and full frames. Write to a new temporary sibling directory. Write the three parquet files, compute SHA256 and row counts for each, then write metadata last, flush/close files, and rename the temporary directory to the final revision path. Do not overwrite an existing final path; verify matching hashes and return an idempotent result or raise on a mismatch.
7. Metadata must include schema version for this separate format, run ID, revision, UTC captured-at, `snapshot.refreshed_at`, refresh reason, system date, market date/status, actual source risk dates, forced dates/view, snapshot errors, and payload hashes/columns/row counts. Include governed connector/config version identifiers only where the site can supply them; do not invent versions. Preserve degraded snapshot status explicitly.
8. In `cube/services/s06_refresh.py`, add `import uuid`. In `RiskRefreshManager.__init__`, add optional constructor keyword `committed_snapshot_sink=None`. Assign it to `self._committed_snapshot_sink`, set `self._capture_error=None`, and create `self._capture_run_id=uuid.uuid4().hex` once. Find `_commit_full_snapshot` in `cube/services/s02_state.py`. At its end, after leaving its `with self._state_lock:` block, **ADD this block at method-body indentation**:

   ```python
   sink = self._committed_snapshot_sink
   if sink is not None:
       try:
           sink(snapshot, self._capture_run_id)
       except Exception as error:
           with self._state_lock:
               self._capture_error = f"Intraday capture failed: {error}"
           self._logger.exception(
               "Intraday capture failed for committed revision %s", snapshot.revision
           )
       else:
           with self._state_lock:
               self._capture_error = None
   ```

   This shared boundary covers normal refresh and release/promotion commits once. Do not also call it at every call site. Do not add the hook to `_commit_snapshot`, which handles retained/status-only paths. Add a read-only `capture_error` property beside the mixin's existing `health` property: under `self._state_lock`, return `self._capture_error`.
9. Keep capture errors in the durable process log and available through `manager.capture_error`. Do not make sink failure roll back an already committed financial snapshot. If the business requires every revision to be durable before any user sees it, this optional after-commit hook is insufficient; that requirement needs a deliberately transactional publication design. Do not claim complete audit coverage from a best-effort hook.
10. Record failed refresh attempts as small event metadata with attempt time/reason/error in a separate attempts stream. Do not write retained last-good values as if they were fresh successful data. Do not retain every raw connector response unless that separate retention requirement is explicitly implemented at the source boundary.
11. In `cube/services/s05_sources.py::build_production_refresh_manager`, add `committed_snapshot_sink=None` and forward it into `RiskRefreshManager(...)`. In `app.py`, resolve `RISK_INTRADAY_PATH` only when configured and build a callable `sink(snapshot, run_id)` which calls `capture_committed_snapshot(snapshot, root, run_id)`; pass that callable into manager construction. When the setting is blank, pass `None`; constructing the app must not create capture files or read financial connectors. Keep the existing refresh callback outputs unchanged; inspect capture errors in the durable log or manager property. Do not put snapshots into a browser `dcc.Store` or an unbounded queue. This first implementation is synchronous and measurable; if disk writing adds unacceptable latency, measure before introducing a bounded asynchronous worker.
12. Add a read-only `list_intraday_captures(root)` to `s11_intraday_capture.py`: enumerate only the described date/run/revision layout, reject temporary directories, require all four payload/metadata files, validate metadata and hashes, and return only complete captures. In an isolated app, record directory count; one full committed refresh must add one, a read must add zero, and repeating the same run/revision capture must add zero. Restart the process and confirm a new run ID. Place an incomplete temporary sibling directory under the isolated root; the reader must ignore it.
13. Run `check_syntax(["cube/app/s03_logging.py", "cube/services/s02_state.py", "cube/services/s05_sources.py", "cube/services/s06_refresh.py", "cube/services/s11_intraday_capture.py", "app.py"])`. Restart with an isolated capture root, trigger one refresh, and inspect metadata plus row counts. Make the isolated sink raise once: the financial revision must remain committed and capture-health must report failure. Leave the official daily archive unchanged. Rollback disables the sink and restores code while retaining capture/log directories for review.

<a id="job-f09"></a>
## Job F09 — Fix market-move rendering and make tenor charts easier to read

**Result:** Risk detail renders market metrics, exposure and hedges use a comparable scale, and sparse surfaces are responsive. Complete the unique-quote aggregation and shared-pivot jobs first; keep those calculations while changing presentation.

1. Run `backup_job("F09", ["cube/pages/risk/s05_charts.py", "assets/s06_visuals.css"])`. The `.tenor-surface-graph` selector is in that existing stylesheet; edit it there without creating a competing stylesheet.
2. Open `build_line_chart` in `cube/pages/risk/s05_charts.py`. Find its market branch `if metric in {"move", "open", "current"}:` and its nonmarket `else:`. At the end, the current `return dcc.Graph(...)` is indented inside that `else`. **REMOVE that return from inside `else` and ADD this return at function-body indentation**, after both branches finish:

   ```python
   return dcc.Graph(
       figure=figure,
       responsive=True,
       config={"displaylogo": False, "responsive": True},
   )
   ```

3. Verify every market and nonmarket path defines `figure`. Keep quote aggregation independent of Portfolio count. In a notebook, call `build_line_chart` with `move`, `open`, and `current` and assert each returns a Graph with nonempty traces. For the missing-move bug this return placement is the functional fix; cosmetic changes alone cannot fix it.
4. In the nonmarket branch, **REMOVE** `yaxis="y2"` from exposure/hedge Scatter traces and **REMOVE** that branch's `yaxis2={...}` layout entry. Keep total, exposure and hedges on the same y-axis because they share units. Keep the existing total Bar and component Scatter types. In that branch's colour dictionary and component-colour tuple, replace exposure `#73A9D8` with `#2563EB`, hedges `#D99191` with `#B45309`, and total `#4C8A4A` with `#334155`; preserve the actual signed values. Update the y-axis label to the selected metric's governed unit, or `Risk (source units)` if the source has not defined a more specific unit.
5. For the market branch, show Move separately from quote levels. The smallest consistent layout is two vertically stacked Plotly subplots with shared x: Open/Current lines in the top row, Move bars in the lower row. Add `from plotly.subplots import make_subplots`. When metric is `move`, construct `make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.10, row_heights=[0.65, 0.35])`; add Open/Current to row 1 and Move to row 2. Remove overlay/right-axis layout for this case. For metric Open or Current alone, keep one plot. Do not place Risk and market values on one unlabelled common axis.
6. Keep connector tenor order: use existing `tenor_axis_order` and its `axis_values` category array. Keep its ambiguity annotation. Show full labels in hover and shortened labels only on ticks. Do not sort labels alphabetically or parse tenor strings to invent ranks.
7. In `_build_tenor_heatmap_from_pivot` introduced by P03, keep its supplied shared pivot, sparse `NaN` cells, and `_surface_hover_data`. **KEEP** the public `build_tenor_heatmap` compatibility wrapper unchanged. **REPLACE** the private renderer's red/green colour scale with `[[0.0, "#B45309"], [0.5, "#F8FAFC"], [1.0, "#2563EB"]]` for signed Risk/dRisk/P&L/Move. Keep symmetric bounds around zero for those signed metrics. For Open/Current quote levels, use a sequential palette and bounds of their finite quote values; do not imply zero is the economic midpoint of a rate/price level.
8. Replace `autosize=False` with `autosize=True`. Keep the responsive Graph configuration. Use height `max(320, min(620, 100 + 24 * len(pivot.index)))`; give the container `min-width: 0`. Keep full information available in the scrollable matrix/table; do not hide tenors merely to fit a chart. If there are many columns, show fewer tick labels with full hover, not fewer data columns.
9. Make heatmap and matrix orientation identical. The current matrix reverses option rows for display. Retain that matrix order and configure the heatmap option category axis to produce the same visual order. Check the same named swap/option cell appears in the same visual corner and reports the same value. Keep the underlying pivot order authoritative.
10. Add small-matrix values only when there are at most 100 cells. Use Plotly text/hover formatting with missing cells blank; omit cell labels on larger matrices. Never format an unavailable quote as `0.00`.
11. **KEEP** the existing chart/table selection owner. This job changes the line and surface presentation and preserves the shared matrix; it does not add an additional independently selected profile chart or new selection Store.
12. Install the complete [CODE-CHART-PREVIEW](#code-chart-preview) helper at `tools/s04_chart_previews.py` to inspect the alternative visuals offline. Run `subprocess.run([PYTHON, "-m", "tools.s04_chart_previews", "--archive", str(DEMO_ROOT), "--date", "2026-08-21", "--output", str(APP_ROOT.parent / "chart-previews")], cwd=APP_ROOT, check=True)` after the demonstration history job. Open its generated HTML outputs from JupyterLab. These previews are demonstration artifacts; app changes are the explicit edits above. Do not replace financial inputs with the preview generator's synthetic values.
13. In the isolated app, open one scalar, swap-only, option-only and two-axis selection. For each select market move/open/current, then Risk/dRisk/P&L. All supported branches must return a visible chart; missing values must remain blank. Compare the chart numbers with the adjacent values table. In a two-Portfolio demonstration where Open is 3 and Current is 4 for the same quote, quote levels must remain 3 and 4. Record the existing metric totals before editing and confirm they are unchanged afterward.
14. Run `check_syntax(["cube/pages/risk/s05_charts.py"])`, restart, and inspect normal/narrow browser widths. Check long labels, mixed connector rank warnings and keyboard access to the Data table. If the checks fail, restore only F09 edits while keeping the earlier shared-pivot/correctness improvements; do not paste an older complete renderer over them.

<a id="job-f10"></a>
## Job F10 — Browse Portfolio detail from main Risk without expanding the whole book population

**Result:** clicking a Risk value makes its contributing portfolios available in a searchable, server-paged detail section. Every matching portfolio is reachable; totals include the full selected scope. The default main hierarchy stays compact. This is the selected implementation for the approximately 100,000-row / 300–400-Portfolio workload.

1. Complete the Risk index reuse and server/output memory jobs first. Run `backup_job("F10", ["cube/pages/risk/s07_explorer.py", "cube/pages/risk/s16_view.py", "cube/pages/risk/s18_portfolios.py"])`.
2. **KEEP** `Portfolio` in position data. **KEEP** the existing main hierarchy and shared view dimensions. **DO NOT ADD** Portfolio to `VIEW_DIMENSIONS`, market quote keys, `ALT_GROUPS`, or every expanded main-table leaf. This job adds a separate selected-scope detail section with 50 portfolios per page; it does not create nonexistent position/Portfolio combinations.
3. **ADD** `cube/pages/risk/s18_portfolios.py` containing the pure table builder below. Its input is the already prepared, selected position scope, before the page slice; quotes are deliberately absent from this table because they require independent quote identity.

   ```python
   """Server-page an exact selected Risk scope by Portfolio."""
   from __future__ import annotations

   from collections.abc import Mapping
   import math
   import pandas as pd
   from cube.ui.s02_aggregation import should_show_sum


   def portfolio_page(frame, *, context=None, search="", page=0, sort_by=None):
       if isinstance(page, bool) or not isinstance(page, int) or page < 0:
           raise ValueError("Invalid Portfolio page number")
       columns = ["portfolio", "risk", "drisk", "pl"]
       missing = [column for column in columns if column not in frame]
       if missing:
           raise ValueError(f"Portfolio detail is missing columns: {missing}")
       metrics = ["risk", "drisk", "pl"]
       context = dict(context or {})
       work = frame.loc[:, columns].copy()
       for metric in metrics:
           work[metric] = pd.to_numeric(work[metric], errors="raise").replace(
               [float("inf"), float("-inf")], float("nan")
           )
       missing_counts = work[metrics].isna().sum().to_dict()
       totals = work[metrics].sum(min_count=1).where(
           work[metrics].notna().all()
       ).to_dict()
       groups = work.groupby("portfolio", dropna=False, observed=True, sort=False)
       grouped_values = groups[metrics].sum(min_count=1)
       complete = groups[metrics].count().eq(groups.size(), axis="index")
       grouped_values = grouped_values.where(complete)
       for metric in metrics:
           if not should_show_sum(metric, context):
               totals[metric] = float("nan")
               grouped_values[metric] = float("nan")
       grouped = grouped_values.reset_index()
       total_portfolios = len(grouped)
       term = str(search or "").strip()
       if len(term) > 200:
           raise ValueError("Portfolio search is limited to 200 characters")
       if term:
           grouped = grouped.loc[
               grouped["portfolio"].astype("string").str.contains(
                   term, case=False, regex=False, na=False
               )
           ]
       matched = len(grouped)
       clauses = sort_by or [{"column_id": "portfolio", "direction": "asc"}]
       if not isinstance(clauses, (list, tuple)) or len(clauses) > len(columns):
           raise ValueError("Invalid Portfolio detail sort")
       if any(not isinstance(item, Mapping)
              or item.get("column_id") not in columns
              or item.get("direction") not in {"asc", "desc"} for item in clauses):
           raise ValueError("Invalid Portfolio detail sort")
       keys = [item["column_id"] for item in clauses]
       if len(keys) != len(set(keys)):
           raise ValueError("Duplicate Portfolio sort field")
       directions = [item["direction"] == "asc" for item in clauses]
       if "portfolio" not in keys:
           keys.append("portfolio")
           directions.append(True)
       grouped = grouped.sort_values(keys, ascending=directions, kind="stable")
       page_count = max(1, math.ceil(matched / 50))
       selected_page = min(max(0, int(page or 0)), page_count - 1)
       start = selected_page * 50
       visible = grouped.iloc[start:start + 50].copy().astype(object)
       visible = visible.where(pd.notna(visible), None)
       records = visible.to_dict("records")
       safe_totals = {key: None if pd.isna(value) else float(value)
                      for key, value in totals.items()}
       return {
           "records": records, "page_count": page_count,
           "page_current": selected_page, "matched": matched,
           "total_portfolios": total_portfolios, "totals": safe_totals,
           "missing_counts": {key: int(value) for key, value in missing_counts.items()},
           "start": 0 if not matched else start + 1,
           "end": min(start + 50, matched),
       }
   ```

4. In `cube/pages/risk/s16_view.py::build_layout`, immediately after the stable `html.Div(id="detail-panel", ...)`, **ADD** `html.Button("Show portfolios in this selection", id="risk-portfolio-toggle", n_clicks=0, type="button", **{"aria-expanded": "false", "aria-controls": "risk-portfolio-details"})` and `html.Div(id="risk-portfolio-details", hidden=True, children=[...])`. Inside the Div add: `dcc.Input(id="risk-portfolio-search", type="search", debounce=True, maxLength=200, placeholder="Find Portfolio")`; `html.P(id="risk-portfolio-status", role="status")`; and a `dash_table.DataTable` with ID `risk-portfolio-table`, columns Portfolio/risk/drisk/pl, `data=[]`, `page_action="custom"`, `page_current=0`, `page_size=50`, `page_count=1`, `sort_action="custom"`, `sort_mode="multi"`, `sort_by=[]`, `filter_action="none"`. Import `dash_table` if absent. Use this explicit button/hidden pattern from B04: native Summary clicks do not reliably update a Dash `Details.open` Input in the installed component. Do not place source rows in a Store.
5. In `cube/pages/risk/s07_explorer.py::register_explorer_callbacks`, **ADD this nested helper immediately before `render_active_detail`**. It shares the exact source/measure selection with Portfolio detail; it does not yet apply the selected row key:

   ```python
   def resolve_detail_source(
       *, active_risk_type, ir_family, splits, table_view, credit_view,
       credit_measure, selection, dimension_values, exclude_selected=False,
       promotion_generation=None, reduced_tenor=False,
   ):
       context = parse_row_key(selection.get("key"))
       risk_type = context.get("risk type", active_risk_type)
       filtered = cache.filtered(
           refresh_manager, risk_type, ir_family, splits,
           reporting_filter_map(dimension_values),
           exclude_selected=exclude_selected,
           promotion_generation=promotion_generation,
           reduced_tenor=reduced_tenor,
       )
       selected_measure = selection.get("credit_measure")
       if risk_type == "Credit" and selected_measure:
           filtered = apply_credit_measure(filtered, selected_measure)
       elif risk_type == "Credit" and (
           table_view == "alt" or credit_view == "single"
       ):
           filtered = apply_credit_measure(filtered, credit_measure)
       return filtered, context
   ```

6. In `render_active_detail`, keep its empty-selection return. **REPLACE** the block beginning `selected_context = parse_row_key(...)` and ending at the second Credit-measure adjustment with a call to `resolve_detail_source`, passing its identically named arguments explicitly. Unpack to `filtered, selected_context`. Immediately after the call restore `detail_risk_type = selected_context.get("risk type", active_risk_type)` and `selected_credit_measure = selection.get("credit_measure")`, since later JTD code uses them. **KEEP** all subsequent New Trades and JTD logic. Verify the original detail figures are unchanged before wiring Portfolio pagination.
7. In the new Portfolio callback, obtain `filtered, selected_context` through that same helper. Import `frame_for_context` from `cube.ui.s02_aggregation`. Determine `filtered_splits = set(filtered["split"].dropna().astype(str))` when the column exists. If `_new_trade_detail_requested(selected_context, splits)` is true or `filtered_splits == {NEW_TRADE_SPLIT}`, add `split=NEW_TRADE_SPLIT` to a copy of the context. Then compute `scope = frame_for_context(filtered, selected_context)` and pass `scope` to `portfolio_page`. Keep raw/reported identity as encoded in the selected row key; do not group a fresh unfiltered `cache.current()` frame.
8. In `s07_explorer.py`, add imports `portfolio_page` from `.s18_portfolios` and `frame_for_context, format_number` from `cube.ui.s02_aggregation`. `Mapping`, Dash dependencies, `_valid_delegated_row_key`, `PROMOTION_GENERATION_STORE_ID`, `_explorer_option_state`, `risk_exclude_selected` and the New Trades helpers are already imported or defined in this module; do not duplicate them. **ADD these two complete callbacks inside `register_explorer_callbacks`, after `resolve_detail_source` and before `render_active_detail`**:

   ```python
   @app.callback(
       Output("risk-portfolio-details", "hidden"),
       Output("risk-portfolio-toggle", "children"),
       Output("risk-portfolio-toggle", "aria-expanded"),
       Input("risk-portfolio-toggle", "n_clicks"),
       prevent_initial_call=True,
   )
   def toggle_portfolio_detail(clicks):
       opened = bool(int(clicks or 0) % 2)
       return (
           not opened,
           "Hide portfolios in this selection" if opened
           else "Show portfolios in this selection",
           str(opened).lower(),
       )

   @app.callback(
       Output("risk-portfolio-table", "data"),
       Output("risk-portfolio-table", "page_count"),
       Output("risk-portfolio-table", "page_current"),
       Output("risk-portfolio-status", "children"),
       Input("risk-portfolio-details", "hidden"),
       Input("selected-cell-store", "data"),
       Input("risk-portfolio-search", "value"),
       Input("risk-portfolio-table", "page_current"),
       Input("risk-portfolio-table", "sort_by"),
       Input("data-revision-store", "data"),
       Input("risk-type-tabs", "value"),
       Input("ir-family-tabs", "value"),
       Input("split-filter", "value"),
       Input("table-view-tabs", "value"),
       Input("credit-view-tabs", "value"),
       Input("credit-measure", "value"),
       Input("dimension-filter-values-store", "data"),
       Input("risk-filter-exclude-applied-store", "data"),
       Input("risk-explorer-options", "value"),
       Input(PROMOTION_GENERATION_STORE_ID, "data", allow_optional=True),
       Input("underlying-identity-mode", "value"),
       prevent_initial_call=True,
   )
   def render_portfolio_detail(
       detail_hidden, selection, search, page_current, sort_by, data_revision,
       active_risk_type, ir_family, splits, table_view, credit_view,
       credit_measure, dimension_values, exclude_value, explorer_options,
       promotion_generation, underlying_identity_mode,
   ):
       if detail_hidden is not False:
           return [], 1, 0, "Open to load the selected portfolios"
       if not isinstance(selection, Mapping) or not _valid_delegated_row_key(
           selection.get("key"), allow_total=True
       ):
           return [], 1, 0, "Select a Risk value first"
       try:
           try:
               triggered = set(ctx.triggered_prop_ids)
           except MissingCallbackContextException:
               triggered = set()
           only_paging = not triggered or triggered <= {
               "risk-portfolio-table.page_current"
           }
           requested_page = page_current if only_paging else 0
           _promotion, _region, reduced = _explorer_option_state(explorer_options)
           filtered, context = resolve_detail_source(
               active_risk_type=active_risk_type,
               ir_family=ir_family,
               splits=splits,
               table_view=table_view,
               credit_view=credit_view,
               credit_measure=credit_measure,
               selection=selection,
               dimension_values=dimension_values or [],
               exclude_selected=risk_exclude_selected(exclude_value),
               promotion_generation=promotion_generation,
               reduced_tenor=reduced,
           )
           identity_mode = _selected_underlying_identity_mode(underlying_identity_mode)
           stale_identity = (
               identity_mode == "underlying" and "reported underlying" in context
           ) or (identity_mode == "reported" and "underlying" in context)
           if stale_identity:
               return [], 1, 0, "Identity view changed; select a Risk value again"
           filtered_splits = (
               set(filtered["split"].dropna().astype(str))
               if "split" in filtered else set()
           )
           if (_new_trade_detail_requested(context, splits)
                   or filtered_splits == {NEW_TRADE_SPLIT}):
               context = {**context, "split": NEW_TRADE_SPLIT}
           scope = frame_for_context(filtered, context)
           result = portfolio_page(
               scope, context=context, search=search,
               page=requested_page or 0, sort_by=sort_by,
           )
           totals = result["totals"]
           formatted = {
               key: "unavailable" if value is None
               else format_number(value, column=key)
               for key, value in totals.items()
           }
           status = (
               f"Showing {result['start']}–{result['end']} of "
               f"{result['matched']} matching portfolios; "
               f"{result['total_portfolios']} in the complete selected scope. "
               f"Complete-scope Risk {formatted['risk']}, "
               f"dRisk {formatted['drisk']}, P&L {formatted['pl']}. "
               f"Data revision {data_revision}."
           )
           if "risk greek" not in context:
               status += " Select a Risk Greek to show compatible Risk/dRisk amounts."
           incomplete = [f"{key}: {count}" for key, count
                         in result["missing_counts"].items() if count]
           if incomplete:
               status += " Unavailable input rows (no partial total): " + ", ".join(incomplete)
           return (result["records"], result["page_count"],
                   result["page_current"], status)
       except (TypeError, ValueError, KeyError) as error:
           LOGGER.warning("Portfolio detail could not be loaded: %s", error)
           return [], 1, 0, f"Portfolio detail could not be loaded: {error}"
   ```

9. Match the 17 data-callback parameters to its 17 Inputs exactly. Closed content is not grouped. The button callback owns visibility/label/ARIA; the data callback owns only the four data/status outputs. Add shell-ID/callback-ownership assertions for all five new IDs plus the detail container before continuing.
10. When search, sort, selected cell or any scope/revision Input changes, reset requested page to zero before calling `portfolio_page`. When only the page Input changes, use the requested page. Include the Data revision in every retained result key; the simplest first version does not cache these at-most-400 grouped portfolio records at all.
11. Return only `result["records"]`. Search changes which portfolio names are displayed, not the complete-scope totals. Use `should_show_sum` from the existing app: TOTAL/Risk Type selections keep Risk/dRisk unavailable until Risk Greek is selected, so different sensitivity units are not added. A metric with any unavailable input in a Portfolio is unavailable for that Portfolio; any unavailable input in the full selected scope makes its full-scope total unavailable. Keep complete books' values visible and state missing input counts. Never show a partial sum or page-only subtotal as a complete total.
12. This callback owns its own four outputs. Do not add a second callback writing the same table data or page state. A same-callback page-current clamp can be used to normalize an out-of-range request; guard unchanged outputs with `no_update` if needed to avoid a redundant round trip.
13. **KEEP** the main `selected-cell-store` owner unchanged. This job supplies complete Portfolio table browsing; it does not add a second per-Portfolio chart callback or an extra chart-selection Store. Existing Risk tenor detail remains available for the selected parent scope. Do not improvise another callback writing the main Risk selection as part of this job.
14. Run this plain notebook cell. It constructs its own demonstration frame and uses only application code and pandas:

   ```python
   import pandas as pd
   from cube.pages.risk.s18_portfolios import portfolio_page
   sample = pd.DataFrame({"portfolio": [f"DEMO-{i:03}" for i in range(400)],
                          "risk": [1.0] * 400, "drisk": [2.0] * 400,
                          "pl": [3.0] * 400})
   visited = []
   for page in range(8):
       result = portfolio_page(sample, context={"risk greek": "Delta"}, page=page)
       assert result["page_count"] == 8 and len(result["records"]) == 50
       assert result["totals"] == {"risk": 400.0, "drisk": 800.0, "pl": 1200.0}
       visited.extend(row["portfolio"] for row in result["records"])
   assert len(visited) == len(set(visited)) == 400
   found = portfolio_page(sample, context={"risk greek": "Delta"}, search="DEMO-399", page=7)
   assert found["page_current"] == 0
   assert [row["portfolio"] for row in found["records"]] == ["DEMO-399"]
   assert portfolio_page(sample)["matched"] == 400
   assert portfolio_page(sample, page=999)["page_current"] == 7
   broad = portfolio_page(sample)
   assert broad["totals"]["risk"] is None and broad["totals"]["drisk"] is None
   assert broad["totals"]["pl"] == 1200.0
   incomplete = sample.copy()
   incomplete.loc[0, "pl"] = float("nan")
   checked = portfolio_page(incomplete, context={"risk greek": "Delta"})
   assert checked["totals"]["pl"] is None
   assert checked["missing_counts"]["pl"] == 1
   assert checked["records"][0]["pl"] is None
   assert checked["records"][1]["pl"] == 3.0
   check_syntax(["cube/pages/risk/s07_explorer.py", "cube/pages/risk/s16_view.py",
                 "cube/pages/risk/s18_portfolios.py"])
   ```

15. In the browser, select a known narrow activity/underlying/split/tenor/Credit scope and compare its Portfolio table total to the parent. Change a scope control while on a later page; the table must reset to page one. Repeat raw/reported identity, promotion on/off, reduced/full tenor and New Trades. A two-book scope with Risk 10/20 and PL 4/6 must show totals 30/10; the quote detail still shows Open 3/Current 4, not 6/8. In a notebook inspect the prepared frame's columns: `assert prepared.columns.is_unique` and `assert list(prepared.columns).count("portfolio") == 1`, using the same prepared frame obtained in the Risk index job.
16. Restart and start with one Risk type/underlying. Open the Portfolio detail, search, change pages, and clear selection. Then measure a representative 100,000-row/400-book demonstration population: raw/prepared/filtered rows, grouped books, returned records, response bytes, elapsed callback time and worker memory. Returned records must never exceed 50; every matching book must remain reachable. A broad scope must not create all tree leaves or retain full rendered table variants.
17. Rollback restores F10 code and removes its optional controls. It does not alter source data, financial totals, daily archives or the shared Risk index. Keep the index fix even if this new UI is temporarily disabled.

<a id="job-t01"></a>
## Job T01 — Create the optional demonstration tools

### 1. Back up the three tool paths

```python
backup_job("T01", ['tools/s04_chart_previews.py', 'tools/s05_demo_history.py', 'tools/s06_read_demo_history.py'])
```

### 2. Create all three complete files below

<a id="code-chart-preview"></a>
### CODE-CHART-PREVIEW — Chart preview generator

Create `tools/s04_chart_previews.py` in the JupyterLab text editor and paste the complete file below. If it exists, compare it before replacing it. Keep the entire file, including its command-line arguments and validation.

```python
"""Build standalone tenor-design previews from the shipped synthetic archive.

Run from the repository root:
    python -m tools.s04_chart_previews --output docs/chart-previews

This optional tool reads archive files and writes only the selected output
directory. It is not imported by the Dash app and changes no financial data.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from cube.history import load_risk_archive
from cube.ui.s02_aggregation import detail_frame, prepare_risk_data, tenor_axis_order


ROOT = Path(__file__).resolve().parents[1]
BLUE = "#2976B8"
ORANGE = "#C37726"
INK = "#263948"
GRID = "#DDE3E8"
WHITE = "#FFFFFF"
DIVERGING = [[0, BLUE], [0.5, "#F4F5F6"], [1, ORANGE]]


def _json_number(value: float, digits: int = 5) -> float | None:
    return round(float(value), digits) if np.isfinite(value) else None


def _style(figure: go.Figure, *, title: str, height: int) -> go.Figure:
    figure.update_layout(
        title={"text": title, "font": {"size": 18}, "x": 0.025},
        template="plotly_white",
        font={"family": "Arial, sans-serif", "size": 13, "color": INK},
        paper_bgcolor=WHITE,
        plot_bgcolor=WHITE,
        height=height,
        margin={"l": 76, "r": 38, "t": 94, "b": 62},
        legend={"orientation": "h", "y": 1.1, "x": 0},
        hoverlabel={"font": {"size": 13}, "namelength": -1},
        hovermode="x unified",
        bargap=0.24,
    )
    figure.update_xaxes(
        showgrid=False, linecolor=GRID, ticks="outside", automargin=True
    )
    figure.update_yaxes(gridcolor=GRID, zerolinecolor=INK, automargin=True)
    return figure


def _ordered_curve(detail: pd.DataFrame, metrics: list[str]) -> pd.DataFrame:
    order, ambiguous = tenor_axis_order(detail, "tenor swap", "tenor swap order")
    if ambiguous:
        raise ValueError("Preview requires one authoritative tenor order")
    return (
        detail.groupby("tenor swap")[metrics]
        .sum(min_count=1)
        .reindex(order)
        .reset_index()
    )


def risk_curve(curve: pd.DataFrame) -> go.Figure:
    """Use one numeric scale for exposures, hedges and the net position."""
    figure = go.Figure()
    for metric, label, color in (
        ("risk expo", "Exposure", BLUE),
        ("risk hedges", "Hedges", ORANGE),
    ):
        figure.add_bar(
            x=curve["tenor swap"],
            y=curve[metric] / 1_000_000,
            name=label,
            marker_color=color,
            hovertemplate="%{x}: %{y:+.3f}m<extra>" + label + "</extra>",
        )
    figure.add_scatter(
        x=curve["tenor swap"],
        y=curve["risk"] / 1_000_000,
        name="Net",
        mode="markers",
        marker={"color": INK, "size": 10, "symbol": "diamond"},
        hovertemplate="%{x}: %{y:+.3f}m<extra>Net</extra>",
    )
    figure.update_layout(barmode="group")
    figure.update_xaxes(
        type="category",
        categoryorder="array",
        categoryarray=curve["tenor swap"],
        title="Swap tenor",
    )
    figure.update_yaxes(
        title="Risk · millions of source units", tickformat="+.1f", rangemode="tozero"
    )
    return _style(figure, title="Exposure, hedges & net", height=430)


def market_curve(detail: pd.DataFrame) -> go.Figure:
    """Keep rate levels and their move in aligned, separate panels.

    The selected demo IR source stores decimal rates. The transformations below
    are display-only: decimal * 100 = percent; decimal change * 10,000 = bp.
    They must not be applied to every ProductSpec without checking its units.
    """
    order, ambiguous = tenor_axis_order(detail, "tenor swap", "tenor swap order")
    if ambiguous or detail["underlying"].nunique() != 1:
        raise ValueError("Select one exact underlying with authoritative tenor order")
    quotes = detail.set_index("tenor swap")[["open", "current", "move"]].reindex(order)
    if not quotes.index.is_unique:
        raise ValueError("Market preview expects one quote per tenor")
    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.1,
        row_heights=[0.65, 0.35],
    )
    for metric, label, color, dash in (
        ("open", "Open", ORANGE, "dash"),
        ("current", "Current", BLUE, "solid"),
    ):
        figure.add_scatter(
            x=order,
            y=quotes[metric] * 100,
            name=label,
            mode="lines+markers",
            line={"color": color, "width": 2.5, "dash": dash},
            marker={"size": 6},
            hovertemplate="%{x}: %{y:.3f}%<extra>" + label + "</extra>",
            row=1,
            col=1,
        )
    figure.add_bar(
        x=order,
        y=quotes["move"] * 10_000,
        name="Move",
        showlegend=False,
        marker_color=[BLUE if value >= 0 else ORANGE for value in quotes["move"]],
        hovertemplate="%{x}: %{y:+.2f} bp<extra>Move</extra>",
        row=2,
        col=1,
    )
    figure.update_xaxes(type="category", categoryorder="array", categoryarray=order)
    figure.update_xaxes(title="Swap tenor", row=2, col=1)
    figure.update_yaxes(title="Rate (%)", row=1, col=1)
    figure.update_yaxes(title="Move (bp)", rangemode="tozero", row=2, col=1)
    return _style(figure, title="Rates and daily move", height=510)


def risk_surface(detail: pd.DataFrame) -> tuple[go.Figure, pd.DataFrame]:
    """Show signed tenor risk on a symmetric scale; preserve missing cells."""
    swaps, swap_ambiguous = tenor_axis_order(detail, "tenor swap", "tenor swap order")
    options, option_ambiguous = tenor_axis_order(
        detail, "tenor option", "tenor option order"
    )
    if swap_ambiguous or option_ambiguous:
        raise ValueError("Preview requires authoritative axis orders")
    matrix = (
        detail.groupby(["tenor option", "tenor swap"])["risk"]
        .sum(min_count=1)
        .unstack("tenor swap")
        .reindex(index=options, columns=swaps)
        / 1_000_000
    )
    finite = matrix.to_numpy()[np.isfinite(matrix.to_numpy())]
    limit = float(np.abs(finite).max()) if finite.size else 1.0
    limit = limit or 1.0
    figure = go.Figure(
        go.Heatmap(
            x=swaps,
            y=options,
            z=matrix.to_numpy(),
            zmin=-limit,
            zmax=limit,
            zmid=0,
            colorscale=DIVERGING,
            xgap=2,
            ygap=2,
            hoverongaps=False,
            texttemplate="%{z:.2f}",
            textfont={"size": 12},
            colorbar={"title": "Risk (m)", "thickness": 12, "len": 0.85},
            hovertemplate="Expiry %{y} · Swap %{x}<br>Risk %{z:+.3f}m<extra></extra>",
        )
    )
    figure.update_xaxes(
        title="Swap tenor", type="category", categoryorder="array", categoryarray=swaps
    )
    figure.update_yaxes(
        title="Option tenor",
        type="category",
        categoryorder="array",
        categoryarray=options,
        autorange="reversed",
    )
    _style(figure, title="Risk by option and swap tenor", height=430)
    figure.update_layout(
        hovermode="closest", margin={"l": 76, "r": 75, "t": 68, "b": 62}
    )
    return figure, matrix


def surface_slice(matrix: pd.DataFrame, option: str) -> go.Figure:
    values = matrix.loc[option]
    figure = go.Figure(
        go.Bar(
            x=matrix.columns,
            y=values,
            marker_color=[BLUE if value >= 0 else ORANGE for value in values],
            hovertemplate="%{x}: %{y:+.3f}m<extra>Selected expiry</extra>",
        )
    )
    figure.update_xaxes(
        title="Swap tenor",
        type="category",
        categoryorder="array",
        categoryarray=list(matrix.columns),
    )
    figure.update_yaxes(title="Risk · millions of source units", rangemode="tozero")
    return _style(figure, title=f"Selected expiry · {option}", height=310)


def build_previews(archive: Path, selected_date: str, output: Path) -> dict:
    archive, output = archive.resolve(), output.resolve()
    if output == archive or output.is_relative_to(archive):
        raise ValueError("Preview output must be outside the input archive")
    loaded = load_risk_archive(archive, selected_date)
    marker = json.loads((loaded.path / "_SUCCESS").read_text(encoding="utf-8"))
    if (
        loaded.schema_version != 4
        or marker.get("fixture") != "deterministic-rebirth-v4"
    ):
        raise ValueError(
            "Preview tool accepts only completed synthetic schema-v4 fixtures"
        )
    selected_date = loaded.market_date
    source_path = loaded.path / "risk.parquet"
    raw = loaded.risk
    prepared = prepare_risk_data(raw)
    curve_scope = {
        "source type": "ir/delta",
        "underlying": "FAKE_REPLACE_ME - USD SOFR",
    }
    surface_scope = {
        "source type": "ir/deltavega",
        "underlying": "FAKE_REPLACE_ME - USD SOFR Vol",
    }

    def exact_scope(identity: dict[str, str]) -> pd.DataFrame:
        mask = pd.Series(True, index=prepared.index)
        for column, value in identity.items():
            mask &= prepared[column].eq(value)
        return prepared.loc[mask]

    curve_detail = detail_frame(exact_scope(curve_scope), {}, "risk")
    market_detail = detail_frame(exact_scope(curve_scope), {}, "move")
    surface_detail = detail_frame(exact_scope(surface_scope), {}, "risk")
    if curve_detail.empty or market_detail.empty or surface_detail.empty:
        raise ValueError(
            "Selected archive lacks the exact synthetic preview identities"
        )
    curve = _ordered_curve(curve_detail, ["risk", "risk expo", "risk hedges"])
    assert np.allclose(curve["risk"], curve["risk expo"] + curve["risk hedges"], rtol=1e-7, atol=0)
    figures = [risk_curve(curve), market_curve(market_detail)]
    heatmap, matrix = risk_surface(surface_detail)
    figures += [heatmap, surface_slice(matrix, str(matrix.index[0]))]
    assert np.allclose(
        matrix.sum().sum() * 1_000_000, surface_detail["risk"].sum(), rtol=1e-7, atol=0
    )
    output.mkdir(parents=True, exist_ok=True)
    fragments = [
        figure.to_html(
            full_html=False,
            include_plotlyjs=True if index == 0 else False,
            div_id=f"design-{index}",
            config={"responsive": True, "displaylogo": False},
        )
        for index, figure in enumerate(figures)
    ]
    select_options = "".join(
        f'<option value="{option}">{option}</option>' for option in matrix.index
    )
    slice_values = {
        str(option): [_json_number(value) for value in matrix.loc[option]]
        for option in matrix.index
    }
    surface_json = json.dumps(slice_values, allow_nan=False)
    document = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Rebirth tenor chart proposals</title><style>
body{{margin:0;background:#f3f5f7;color:#263948;font:15px/1.5 Arial,sans-serif}}
main{{max-width:1000px;margin:0 auto;padding:24px 16px}}h1{{font-size:25px;margin:0 0 6px}}
.caption{{margin:0 0 20px;color:#4b5d6b}}section{{background:#fff;margin:0 0 22px;padding:8px 6px}}
label{{display:block;padding:12px 18px}}select{{font:inherit;padding:7px 16px}}
.note{{padding:0 20px 14px;margin:0}}.plotly-graph-div{{width:100%}}
</style></head><body><main>
<h1>Rebirth · tenor chart proposals</h1><p class="caption">Synthetic market cut · {selected_date} · USD SOFR / USD SOFR Vol · Full tenors · Proposals, not the live app<br>Risk dates: Delta {loaded.risk_dates["ir/delta"]} · DeltaVega {loaded.risk_dates["ir/deltavega"]}</p>
<section>{fragments[0]}<p class="note">All three series use the same scale. Diamonds show net risk without covering the exposure and hedge bars.</p></section>
<section>{fragments[1]}<p class="note">Levels and changes have their own units and aligned tenor axes. Rate conversion is specific to this decimal-rate demo source.</p></section>
<section>{fragments[2]}<label>Inspect expiry <select id="expiry">{select_options}</select></label>{fragments[3]}<p class="note">Click a heatmap cell or choose an expiry. Missing cells remain unavailable; zero stays neutral.</p></section>
</main><script>
const rows={surface_json};
function chooseExpiry(value){{
document.getElementById('expiry').value=value;
Plotly.restyle('design-3',{{y:[rows[value]],'marker.color':[rows[value].map(v=>v>=0?'{BLUE}':'{ORANGE}')]}});
Plotly.relayout('design-3',{{'title.text':'Selected expiry · '+value}});
}}
document.getElementById('expiry').addEventListener('change',event=>chooseExpiry(event.target.value));
document.getElementById('design-2').on('plotly_click',event=>chooseExpiry(String(event.points[0].y)));
</script></body></html>"""
    (output / "index.html").write_text(document, encoding="utf-8")
    curve_rows = [
        {
            "tenor": row["tenor swap"],
            "net": _json_number(row["risk"] / 1_000_000),
            "exposure": _json_number(row["risk expo"] / 1_000_000),
            "hedges": _json_number(row["risk hedges"] / 1_000_000),
        }
        for row in curve.to_dict("records")
    ]
    payload = {
        "source": str(source_path.relative_to(ROOT))
        if source_path.is_relative_to(ROOT)
        else str(source_path),
        "synthetic": True,
        "date": selected_date,
        "risk_dates": {
            source: loaded.risk_dates[source] for source in ("ir/delta", "ir/deltavega")
        },
        "curve": curve_rows,
        "surface": {
            "swaps": list(matrix.columns),
            "options": list(matrix.index),
            "values": [
                [_json_number(value) for value in row] for row in matrix.to_numpy()
            ],
        },
    }
    (output / "data.json").write_text(
        json.dumps(payload, indent=2, allow_nan=False), encoding="utf-8"
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "data/histo")
    parser.add_argument("--date", default="2026-08-21")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/chart-previews")
    args = parser.parse_args()
    result = build_previews(args.archive.resolve(), args.date, args.output.resolve())
    print(
        json.dumps(
            {
                "output": str(args.output.resolve() / "index.html"),
                "curve_tenors": len(result["curve"]),
                "surface_shape": [
                    len(result["surface"]["options"]),
                    len(result["surface"]["swaps"]),
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
```

<a id="code-demo-history"></a>
### CODE-DEMO-HISTORY — Isolated demonstration history

Create `tools/s05_demo_history.py` in the JupyterLab text editor and paste the complete file below. If it exists, compare it before replacing it. Keep the entire file, including its command-line arguments and validation.

```python
"""Generate SYNTHETIC schema-v4 history in a required directory outside this repo.

Run from the repository root:
    python -m tools.s05_demo_history --start 2026-08-19 --end 2026-08-21 \
        --output ../demo-history

This optional tool uses deterministic fixtures and the existing immutable archive
writer. It never calls live connectors or sends P&L. Existing completed synthetic
days are validated and retained. Real, incomplete, or unrelated output contents
are rejected before any archive is written.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from cube.history import (
    CompletedArchiveDay,
    archive_official_snapshot,
    list_completed_v4_archive_days,
    open_history_database,
)
from tools.s01_fixtures import (
    FIXTURE_TAG,
    HISTORICAL_MARKET_DATES,
    build_official_history_fixture,
)


ROOT = Path(__file__).resolve().parents[1]


def fixture_dates(start: str, end: str) -> tuple[str, ...]:
    """Validate the entire requested range before generating its first day."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.isoformat() != start or last.isoformat() != end:
        raise ValueError("Use ISO dates in YYYY-MM-DD format.")
    if first > last:
        raise ValueError("--start must be on or before --end.")
    if start < HISTORICAL_MARKET_DATES[0] or end > HISTORICAL_MARKET_DATES[-1]:
        raise ValueError(
            "The entire range must stay within the SYNTHETIC fixture range "
            f"{HISTORICAL_MARKET_DATES[0]} to {HISTORICAL_MARKET_DATES[-1]}."
        )
    days = tuple(day for day in HISTORICAL_MARKET_DATES if start <= day <= end)
    if not days:
        raise ValueError("The range must contain at least one fixture business day.")
    return days


def validate_synthetic_root(root: Path) -> tuple[CompletedArchiveDay, ...]:
    """Read-only preflight: accept an empty root or only complete tagged fixtures.

    The shared archive validator checks _SUCCESS, all payload hashes, ordered
    schemas and row counts. Checking every entry first also rejects incomplete
    leaves that the general history reader intentionally hides.
    """
    if not root.exists():
        return ()
    if not root.is_dir():
        raise ValueError(f"Archive root must be a directory: {root}")
    entries = tuple(root.iterdir())
    for leaf in entries:
        if (
            not leaf.is_dir()
            or leaf.resolve() != leaf
            or leaf.name not in HISTORICAL_MARKET_DATES
            or not (leaf / "_SUCCESS").is_file()
        ):
            raise ValueError(f"Refusing unrelated or incomplete archive entry: {leaf}")
        marker = json.loads((leaf / "_SUCCESS").read_text(encoding="utf-8"))
        if not isinstance(marker, dict) or marker.get("fixture") != FIXTURE_TAG:
            raise ValueError(
                f"Refusing to mix SYNTHETIC data with untagged data: {leaf}"
            )
    days = list_completed_v4_archive_days(root)
    if len(days) != len(entries):
        raise ValueError("Every existing output entry must be a completed v4 fixture.")
    return days


def generate_history(start: str, end: str, output: Path) -> None:
    days = fixture_dates(start, end)
    root = output.expanduser().resolve()
    if root == ROOT or ROOT in root.parents:
        raise ValueError("Use an isolated --output directory outside the repository.")
    validate_synthetic_root(root)
    print(f"SYNTHETIC fixture history only; output: {root}", flush=True)
    for day in days:
        selected = pd.Timestamp(day)
        fixture = build_official_history_fixture(day)
        snapshot = SimpleNamespace(
            revision=fixture.revision,
            refreshed_at=datetime(
                selected.year, selected.month, selected.day, 17, 30, tzinfo=timezone.utc
            ),
            system_date=selected,
            market_date=selected,
            market_status="OFFICIAL",
            risk_dates=fixture.risk_dates,
            dashboard_frame=fixture.risk,
            market_frame=fixture.market,
            stock_frame=fixture.stock,
            stock_date=selected,
            errors=(),
            fixture=FIXTURE_TAG,
        )
        result = archive_official_snapshot(
            snapshot, lambda _date: fixture.colossus, root
        )
        if result.status not in {"archived", "already_archived"}:
            raise RuntimeError(f"Unexpected archive result: {result}")
        print(
            day,
            result.status,
            "risk",
            result.risk_rows,
            "market",
            result.market_rows,
            "colossus",
            result.colossus_rows,
            "stock",
            result.stock_rows,
            flush=True,
        )

    completed = validate_synthetic_root(root)
    print(
        "Validated SYNTHETIC schema-v4 days, payload hashes and schemas:",
        len(completed),
    )
    connection = open_history_database(root)
    try:
        for view in (
            "risk_history",
            "market_history",
            "colossus_history",
            "stock_history",
        ):
            print(
                view, connection.execute(f'SELECT count(*) FROM "{view}"').fetchone()[0]
            )
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start", required=True, help="First date, YYYY-MM-DD (inclusive)."
    )
    parser.add_argument(
        "--end", required=True, help="Last date, YYYY-MM-DD (inclusive)."
    )
    parser.add_argument(
        "--output", required=True, type=Path, help="Isolated path outside repo."
    )
    args = parser.parse_args()
    try:
        generate_history(args.start, args.end, args.output)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
```

<a id="code-read-history"></a>
### CODE-READ-HISTORY — Demonstration history reader

Create `tools/s06_read_demo_history.py` in the JupyterLab text editor and paste the complete file below. If it exists, compare it before replacing it. Keep the entire file, including its command-line arguments and validation.

```python
"""Read SYNTHETIC history through the real Data, P&L and Stock repositories.

Run from the repository root:
    python -m tools.s06_read_demo_history --archive ../demo-history

Dates come from the available completed archive days. This read-only example
rejects untagged/real archives so its output cannot be mistaken for live results.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from cube.history import (
    ArchiveHistoryRepository,
    HistoryQuery,
    SQLPLHistoryRepository,
)
from cube.pages.stock.s02_history import (
    SQLStockHistoryRepository,
    stock_history_identity_from_token,
)
from tools.s05_demo_history import validate_synthetic_root


def read_history(archive: Path) -> None:
    root = archive.expanduser().resolve()
    days = validate_synthetic_root(root)
    if not days:
        raise ValueError(f"No completed SYNTHETIC archive days in {root}")
    dates = sorted(day.snapshot_date for day in days)
    start, end = dates[0], dates[-1]
    print(f"SYNTHETIC results only; {start} to {end}; {len(days)} completed days")
    print(f"Archive: {root}")
    pl = SQLPLHistoryRepository(root)
    stock = SQLStockHistoryRepository(root)
    try:
        print("P&L history:")
        print(pl.series(preset="all").series.to_string(index=False))

        data = ArchiveHistoryRepository(root)
        catalog = data.catalog()
        for kind in ("risk", "market"):
            entry = next(
                (
                    item
                    for item in catalog.entries
                    if item.kind == kind and not item.identity.axes
                ),
                None,
            )
            if entry is None:
                print(kind, "has no scalar identity in this archive")
                continue
            result = data.read(HistoryQuery(handoff=entry.to_handoff(), period="all"))
            print(
                kind,
                "dates",
                len(result.dates),
                "canonical values",
                len(result.values),
                "source rows",
                len(result.raw_rows),
            )

        catalog = stock.catalog(limit=1)
        if not catalog.options:
            print("No Stock identity is available.")
        else:
            identity = stock_history_identity_from_token(catalog.options[0]["value"])
            rows = stock.rows(identity, start, end)
            print("Stock history (one exact identity):")
            print(
                rows[["Stock Date", "Quantity", "Market Value"]].to_string(index=False)
            )
    finally:
        pl.clear()
        stock.clear()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    args = parser.parse_args()
    try:
        read_history(args.archive)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
```

### 3. Check the complete tools

```python
check_syntax(["tools/s04_chart_previews.py", "tools/s05_demo_history.py", "tools/s06_read_demo_history.py"])
run_module("tools.s04_chart_previews", "--help")
run_module("tools.s05_demo_history", "--help")
run_module("tools.s06_read_demo_history", "--help")
```

Expected: three `Syntax OK` messages followed by each tool's usage and argument list. These `--help` calls do not publish history. Use the isolated output directories and Python cells in the history and chart jobs to create previews. Demonstration rows are synthetic and do not backfill real history. Keep the existing archive writer and application entry point.

### 4. Restore these three source files if needed

Run `restore_job("T01")` and repeat the syntax check for any restored files that existed before this job. This restores source files only; it does not erase generated output folders.

<a id="job-z01"></a>
## Job Z01 — Finish cleanup and check the saved source

### 1. Keep the existing responsibilities

1. **KEEP** ProductSpec as the owner of Risk Type, Greek, tenor axes, quote conventions and P&L formulas. A cleaner page must read those definitions rather than inventing another product registry.
2. **KEEP** many-to-one Risk-to-Market validation, missing-market indicators and market-only tenors. Do not reduce the MarketBook to positions that happen to exist today.
3. **KEEP** prepared frames and revision-aware caches on the server. Browser stores contain small selection state or explicitly bounded history bundles, not copies of every position frame.
4. **KEEP** single-flight cache preparation, refresh invalidation and source revision references. Do not remove their locks merely to improve one timing result.
5. **KEEP** defensive public snapshot reads. Only an explicitly documented internal no-copy path may share data without a copy.
6. **KEEP** delegated Risk actions and revision tokens. Do not replace these with one callback Input for every table cell.
7. **KEEP** source retry/deadline controls, atomic refresh publication and the last good snapshot after failure.
8. **KEEP** completed daily archive leaves, exact schemas, date authority and integrity metadata. A faster read must not make an incomplete day visible.
9. **KEEP** the special Credit and Split financial rules. Reduce their unnecessary rendering work without changing their calculations.
10. **KEEP** the existing process-owned refresh model. A second worker creates separate managers, datasets and caches; this manual does not introduce shared state between workers.

### 2. Remove only a definition that the preceding jobs replaced

1. Start from the exact **REMOVE** instruction in the job you implemented. Do not pick unrelated helpers for cleanup merely because their names look old.
2. Run `search_project("exact_symbol_name")`, replacing the text with that definition's exact name. Inspect every match, including imports, exports, callback registration and JavaScript references. Open `app.py` in the editor and search there separately because the helper's default folders do not include root files.
3. Identify the new definition and the component IDs or caller that now use it. If any current caller still needs the old helper, **KEEP** it. In particular, pure chart helpers deliberately retained by D07 are not old callback registrations and can remain.
4. Back up every file you are about to edit. Fill this list with the exact paths from the relevant job before running the cell; the empty list deliberately stops the operation:

   ```python
   CLEANUP_FILES = []  # Copy the exact source and caller paths from that job.
   if not CLEANUP_FILES:
       raise ValueError("Set CLEANUP_FILES to the exact files for this cleanup")
   backup_job("Z-final-cleanup", CLEANUP_FILES)
   ```

5. Remove the unused definition and only its now-unused imports/exports. Remove a replaced callback's decorator and function together. Remove obsolete component IDs only after their replacement output owner and layout exist.
6. Search each removed symbol and component ID again. Remaining references must be explained by an intentional retained caller or removed. Do not add duplicate output ownership or relax callback validation to hide a missing ID.
7. If you cannot prove a definition is unused, leave it in place. This is a small cleanup, not a new framework, a general callback abstraction or a rewrite of the archive layer.

### 3. Check Python syntax and available JavaScript syntax

1. Run this notebook cell after saving the selected implementation jobs and cleanup. It discovers application Python source; it does not depend on any additional checking framework:

   ```python
   python_files = ["app.py"]
   for folder in ("cube", "tools", "jobs"):
       directory = APP_ROOT / folder
       if directory.is_dir():
           python_files.extend(
               str(path.relative_to(APP_ROOT))
               for path in sorted(directory.rglob("*.py"))
               if "__pycache__" not in path.parts
           )
   check_syntax(python_files)
   javascript_files = [
       str(path.relative_to(APP_ROOT))
       for path in sorted((APP_ROOT / "assets").glob("*.js"))
   ]
   check_javascript(javascript_files)
   ```

2. Expected Python result: one **Syntax OK** line for each parsed file and a final count, with no exception. If parsing fails, open the reported file and line, fix its indentation/brackets/quotes and rerun the cell.
3. `check_javascript` uses Node only if it is already available. If unavailable, it prints that the checker is unavailable; continue to the browser checks in Z03. Do not install a new package solely for this check.
4. These checks only parse syntax. They do not prove imports resolve, callbacks agree with layout IDs, financial calculations are correct, the charts look right, or the application fits in memory. Complete Z02 and Z03 before calling the change working.
5. **REMOVE nothing** because a syntax check succeeds. Do not downcast financial values, broadly convert columns to categories, precompute every portfolio/tenor combination or introduce a queue/distributed cache during this final step.
6. If cleanup broke a previously working source path, call `restore_job("Z-final-cleanup")`, rerun syntax checks and continue with the old helper retained. Keep financial data and adjustment stores untouched.

<a id="job-z02"></a>
## Job Z02 — Start one preview process through JupyterHub

### 1. Select a free port and a private preview output folder

1. Keep the working source integration settings supplied for your JupyterHub environment. The archive path supplies history; it does not replace today's Risk or Stock connector.
2. For the ordinary notebook-server proxy use `DASH_JUPYTERHUB_MODE=proxy`. The application derives its public request prefix from `JUPYTERHUB_SERVICE_PREFIX`; the proxy removes that prefix before forwarding to Dash. Do not hardcode another user's URL or rewrite application routing to work around a wrong proxy setting.
3. Run this cell. It checks a port without terminating anything that already uses it:

   ```python
   import socket
   import datetime as dt
   PORT = 8052
   with socket.socket() as probe:
       probe.bind(("127.0.0.1", PORT))
   preview_stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
   RUN_ROOT = APP_ROOT.parent / f"rebirth_preview_{preview_stamp}"
   RUN_ROOT.mkdir()
   APP_LOG = RUN_ROOT / "app.log"
   print("Preview output:", RUN_ROOT)
   print("Preview port:", PORT)
   ```

4. If binding fails, select another permitted port and rerun this cell. Do not terminate another process merely because it uses the first port.
5. If your administrator uses a separately registered service rather than the notebook-server proxy, keep the supplied service configuration and set the existing `service` mode in the next cell. Use the service's provided preview URL instead of constructing a proxy URL.

### 2. Start with the notebook's current Python interpreter

1. Use a separate adjustment folder and saved-view folder for this preview. The cell below creates those locations under `RUN_ROOT`; it does not copy or overwrite live adjustment history.
2. If you completed the synthetic history job, use its actual completed output folder in `PREVIEW_HISTORY_ROOT`. Otherwise leave it as `None` to keep the existing archive setting. A missing demo variable must not silently point to a made-up path.
3. Run this cell once:

   ```python
   import os
   import subprocess
   PREVIEW_HISTORY_ROOT = None  # Or set to the actual completed example-history Path.
   app_env = os.environ.copy()
   app_env.update({
       "DASH_JUPYTERHUB_MODE": "proxy",
       "DASH_DEBUG": "0",
       "HOST": "127.0.0.1",
       "PORT": str(PORT),
       "PL_ADJUSTMENT_PATH": str(RUN_ROOT / "adjustments"),
       "SAVED_FILTER_VIEWS_PATH": str(RUN_ROOT / "saved_views"),
   })
   if PREVIEW_HISTORY_ROOT is not None:
       selected_history = Path(PREVIEW_HISTORY_ROOT).expanduser().resolve()
       if not selected_history.is_dir():
           raise ValueError(f"History folder does not exist: {selected_history}")
       app_env["PL_HISTORICAL_PATH"] = str(selected_history)
   if "server_process" in globals() and server_process.poll() is None:
       raise RuntimeError("This notebook already owns a running preview; stop it first")
   app_log_handle = APP_LOG.open("a", encoding="utf-8")
   try:
       server_process = subprocess.Popen(
           [PYTHON, str(APP_ROOT / "app.py"), "--host", "127.0.0.1", "--port", str(PORT)],
           cwd=APP_ROOT,
           env=app_env,
           stdout=app_log_handle,
           stderr=subprocess.STDOUT,
       )
   except Exception:
       app_log_handle.close()
       raise
   print("Preview PID:", server_process.pid)
   print("Log:", APP_LOG)
   hub_base = app_env.get("JUPYTERHUB_SERVICE_PREFIX", "").rstrip("/")
   if hub_base and app_env["DASH_JUPYTERHUB_MODE"] == "proxy":
       print("Open on this JupyterHub host:", f"{hub_base}/proxy/{PORT}/")
   else:
       print("Use the preview URL configured by your JupyterHub administrator.")
   ```

4. This starts a new process using `PYTHON = sys.executable` from setup. It avoids stale notebook module imports and starts with debug/reloader disabled. It does not prove every source is available.
5. Open the printed path on the same JupyterHub host. If the Hub's application proxy is unavailable, use the site's existing app preview launcher with these same interpreter/settings. Do not expose a separate unauthenticated public port as a replacement.
6. The preview adjustment folder does not redirect an external P&L sender. Exercise **Send** only when the configured receiver is the explicit preview sink established in the audit job; otherwise inspect validation/preview and record the real-send check as not performed.

### 3. Read startup output before using the controls

1. Allow startup to progress, then run:

   ```python
   from collections import deque
   print("Exit status:", server_process.poll())
   with APP_LOG.open(encoding="utf-8", errors="replace") as stream:
       print("".join(deque(stream, maxlen=80)))
   ```

2. An exit status of `None` means that this process is still running. A number means it exited; inspect the first exception in the log before restarting.
3. A loaded shell is not proof that all sources/callbacks work. Distinguish a missing dependency, unavailable source, schema/merge error, missing callback ID and proxy-prefix problem. Fix the actual failing boundary; do not disable validators or raise all timeouts.
4. If the log contains sensitive financial rows, replace that broad diagnostic output with the narrow status/count information specified in the relevant job before continuing. Keep full position frames out of routine preview logs.

### 4. Stop and restart only the process this notebook owns

1. Run this cell before restarting after any Python callback change. Use it again when finished with the preview:

   ```python
   if "server_process" in globals() and server_process.poll() is None:
       server_process.terminate()
       try:
           server_process.wait(timeout=15)
       except subprocess.TimeoutExpired:
           server_process.kill()
           server_process.wait(timeout=10)
   if "app_log_handle" in globals() and not app_log_handle.closed:
       app_log_handle.close()
   print("Owned preview process stopped")
   ```

2. Rerun the start cell with the existing preview variables, then hard-refresh the browser to load the saved JavaScript/CSS. Do not create another process on the same port or rely on reexecuting an import in a kernel that already loaded the old callback module.
3. After restarting the notebook kernel, do not guess an old process ID and terminate it. Use the site's process controls for the preview you own, or verify the recorded PID and command before acting. Recreate setup/preview variables before starting a replacement process.
4. To restore source after a kernel restart, reconnect `JOB_BACKUPS["job-id"]` to the exact backup directory printed for that job, then call `restore_job("job-id")`. Stop the preview first and restart after restoring all files in that job.

<a id="job-z03"></a>
## Job Z03 — Check the final interaction and record what works

### 1. Check output ownership on the running preview

1. Keep the preview from Z02 running. This notebook cell reads only its Dash callback dependency metadata from loopback; it does not import another app, create a second manager or read a position frame.
2. Set `CHECKED_UI_JOBS` to the UI jobs you actually completed. The default below covers Stock detail and unified Data; add `"F10"` only if Portfolio detail is installed.
3. Run this complete cell. The existing runtime settings resolve the local route prefix for both proxy mode and service mode, including explicit route overrides. Do not put the browser's public proxy prefix in front of a proxy-mode loopback URL:

   ```python
   import json
   from collections import Counter
   from urllib.request import urlopen
   from cube.app.s01_settings import RuntimeSettings

   CHECKED_UI_JOBS = {"B04", "D06", "D07"}  # Add "F10" if implemented.
   preview_settings = RuntimeSettings.from_env(app_env)
   dependencies_url = (
       f"http://127.0.0.1:{preview_settings.port}"
       f"{preview_settings.routes_pathname_prefix}_dash-dependencies"
   )
   with urlopen(dependencies_url, timeout=10) as response:
       dependencies = json.load(response)
   if not isinstance(dependencies, list):
       raise ValueError("The preview did not return a callback dependency list")

   def output_tokens(raw):
       text = str(raw or "")
       parts = text[2:-2].split("...") if text.startswith("..") and text.endswith("..") else [text]
       return [part.split("@", 1)[0] for part in parts if part]

   owners = Counter(
       output for callback in dependencies
       for output in output_tokens(callback.get("output"))
   )
   groups = {
       "B04": {
           "stock-position-detail.hidden", "stock-detail-toggle.children",
           "stock-detail-toggle.aria-expanded", "stock-position-detail-table.data",
           "stock-position-detail-table.page_count", "stock-detail-status.children",
           "stock-position-detail-table.page_current", "stock-position-detail-table.active_cell",
       },
       "D06": {
           "data-history-request-store.data", "data-history-handoff-consumed-store.data",
           "data-workspace-draft-store.data", "data-display-mode.value",
           "data-series-picker.options", "data-series-picker.value",
           "data-companion-picker.options", "data-companion-picker.value",
           "data-history-bundle-store.data", "data-history-status.children",
           "data-identity-breadcrumb.children",
       },
       "D07": {
           "data-risk-chart.figure", "data-market-chart.figure",
           "data-risk-values-table.data", "data-risk-values-table.columns",
           "data-market-values-table.data", "data-market-values-table.columns",
           "data-player-slider.value", "data-player-state-store.data",
           "data-player-interval.disabled", "data-history-date-a.value",
           "data-history-date-b.value",
       },
       "F10": {
           "risk-portfolio-details.hidden", "risk-portfolio-toggle.children",
           "risk-portfolio-toggle.aria-expanded", "risk-portfolio-table.data",
           "risk-portfolio-table.page_count", "risk-portfolio-table.page_current",
           "risk-portfolio-status.children",
       },
   }
   unknown = CHECKED_UI_JOBS - groups.keys()
   if unknown:
       raise ValueError(f"Unknown callback check groups: {sorted(unknown)}")
   expected = set().union(*(groups[job] for job in CHECKED_UI_JOBS))
   incorrect = {output: owners[output] for output in sorted(expected) if owners[output] != 1}
   if incorrect:
       raise AssertionError(f"Expected one output owner; found these counts: {incorrect}")
   if {"D06", "D07"} & CHECKED_UI_JOBS:
       removed_ids = {
           "data-history-kind-tabs", "data-identity-mode", "data-risk-type",
           "data-risk-greek", "data-underlying", "data-history-chart",
           "data-selected-table", "data-history-projection", "data-history-slice",
           "data-history-slice-label", "data-history-slice-control",
           "data-history-projection-controls",
       }
       references = []
       for callback in dependencies:
           references.extend(item.get("id") for field in ("inputs", "state")
                             for item in callback.get(field, []))
           references.extend(output.rsplit(".", 1)[0]
                             for output in output_tokens(callback.get("output")))
       stale = sorted({value for value in references
                       if isinstance(value, str) and value in removed_ids})
       if stale:
           raise AssertionError(f"Removed Data IDs still have callbacks: {stale}")
   print("Exactly one owner for", len(expected), "selected outputs; no stale Data targets")
   ```

4. Expected result: one owner for every selected output, no stale Data targets and no exception. A zero count means a callback is missing or its ID differs from the layout. A count above one means several registrations claim that output; remove the replaced registration rather than adding duplicate-output flags.
5. A connection error means the preview is unavailable or the port/prefix is wrong. Recheck Z02's process/log and the actual `app_env`. If your site's service adds authorization to the local endpoint, use the signed-in browser's Network panel to inspect the same dependency response; do not disable authorization or expose an endpoint publicly to complete this check.
6. This verifies registration metadata only. It cannot prove the component exists on every route, callback argument/return order is correct or a real request succeeds. Continue with the browser interactions below.

### 2. Exercise the selected features in the running browser

Perform these steps on the saved, cleaned source from Z01, using the fresh process from Z02. For an optional feature you did not implement, record **Not selected** instead of claiming it works.

1. **Statics:** in Write, sort/filter/page a table and hide a column, then choose another DataFrame. Expect the selected frame's correct columns and rows with stale table settings reset. Confirm valid edit/save behavior still works and the hidden Read panel does not fetch data.
2. **Risk:** expand/collapse, change filters/measures, refresh, Clear Cache and open detail. Expect full-scope financial totals, honest display-limit notices, stale-action rejection and reuse of prepared data. A changed expansion must not retain another full Explorer component tree.
3. **Portfolio:** use an exact scope containing 300–400 books. Navigate every page and find a portfolio beyond the first page. Expect all books to remain reachable with unchanged full-scope totals. Change scope while a detail request is pending; an older response must not overwrite the new selection.
4. **Quick Risk to Data:** import an exact reported selection with include/exclude filters. Change period and reload. Expect the exact scope to remain. Switch to Both; a reported identity with several possible quotes must require explicit companion selection.
5. **Quick Market to Data:** import an exact raw quote. Enter Both with a precise Risk companion. Expect independent Risk and Market values, no Portfolio-weighted price, no sum of quote levels and no unexplained identity substitution.
6. **Data views:** use Snapshot, Over time, Compare and retained advanced projections. Expect the values table to follow the same date/tenor slice as its chart. Both shares dates but retains separate axes/units; an absent observation is null/unavailable, never zero or the nearest available date.
7. **Data pending selection:** edit controls without Load, leave and return, then load the new period. The old displayed result must keep its own loaded caption until the new request completes. Play/Pause and slider ticks must not trigger archive reads.
8. **Stock detail:** filter, sort and page detail; find an item beyond page one; click an exact filtered pivot cell to open history. Expect only its intended constituents, prior-only exits in Changes and access to every supported currency/column.
9. **Stock metadata:** check Quantity/dQuantity units, unchanged position identity and blank missing ISIN. Conflicting metadata must be rejected instead of duplicated across positions. Expanding the same scope must not refetch its metadata unnecessarily.
10. **P&L:** check replacement adjustments, explicit deletes and stale-save rejection in the isolated adjustment folder. Expect full selected scope, visible missing Predict/Actual coverage and actual observation dates. Navigate beyond the first ten children if that job was implemented. One available PL value plus one missing value must not appear as a complete total.
11. **History:** use one isolated completed date and read it through Risk, Market, P&L and Stock views. Repeating the same capture must follow the specified idempotency rule. A mismatched Stock date or incomplete archive leaf must remain an explicit failure, not visible successful history.
12. **Audit, when selected:** change and delete one preview adjustment and inspect the old/new versions and actor. A failed save must not leave an event claiming success. An unknown send result must remain unknown and must not be automatically resent. If an isolated sender/failure scenario is not configured, record that part as not performed; do not simulate it against a live receiver.

### 3. Measure the actual data shape

1. Use an isolated representative dataset with around 100,000 position rows and 300–400 portfolios, preserving real column/grain rules. Use approved example data or synthetic values. Do not print entire financial frames into the notebook or logs.
2. Record the selected filters, Risk Type, tenor mode, hierarchy state and visible measures. Use the same scope when comparing behavior before and after a change.
3. Record first-load time, repeated expansion time, response size, displayed rows, server memory and browser responsiveness. Use the application's existing timing/memory output and browser Network panel where available; mark unavailable measurements as unavailable rather than estimating them.
4. Exercise one standard Risk case, Credit Single, Credit Multi, Split VA, broad Stock detail, a sparse two-axis history request and Both. Record each separately; they do not all use the same aggregation path.
5. Confirm that a display budget leaves complete financial totals and a working route to remaining rows. A page that becomes fast by silently omitting positions is not complete.
6. If several users normally share one worker, repeat representative simultaneous browsing at that ordinary concurrency. Watch peak memory and responsiveness. Do not remove locks or multiply workers as an unmeasured shortcut.
7. Change a cache budget only after measuring available memory. A retained-index budget of 256 MiB is not a limit on the dataset or a guarantee that the whole process stays within that size; temporary arrays, response objects and other caches also use memory.

### 4. Record results and handle a failure

1. Add one notebook record per implemented job: job ID, exact files changed, syntax result, observed browser result, measured workload information and **Working / Needs fixing / Not selected**.
2. Record unconfigured sources, optional jobs not selected, unavailable JavaScript parsing and browser scenarios not performed explicitly. Do not call an unimplemented instruction or unconfigured integration operational.
3. If a problem appears, use the app log and the exact failing interaction to return to the relevant job. Back up any additional corrective edit under that job before changing it. Do not silently introduce another feature during final checking.
4. If a correction changes Python, rerun `check_syntax` for those files. If it changes JavaScript, rerun `check_javascript` when available. Stop/restart the preview using Z02 and repeat the affected browser steps above. After cleanup or callback/layout edits, repeat all five entry paths: direct Risk, direct Market, Quick Risk, Quick Market and Both.
5. If the change cannot be corrected now, stop the preview and call `restore_job` for its exact backup group. Restore matching layout, callbacks and assets together; do not leave one half of an interface changed. Restart and confirm the previous working interaction. Keep archive data and saved financial records out of source rollback.
6. Keep the notebook record, source backups and preview output until the application has been accepted in its intended JupyterHub environment. Stop the owned preview process with Z02's shutdown cell when finished. Do not delete the backups as part of cleanup.
7. Mark the work complete only for the behavior actually observed. Syntax success is useful but cannot establish financial correctness, interactive behavior or memory safety by itself.
