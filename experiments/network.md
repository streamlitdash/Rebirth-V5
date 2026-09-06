# Network and worker diagnosis — make every disconnect explainable

This is a repository-wide diagnosis and implementation guide for Rebirth V5. It assumes the changes described by `experiments/fix12.md` through `experiments/fix23.md` have been applied. It deliberately does **not** change financial calculations, connector authority, reduced-tenor rules, promotion semantics, or table contents.

The immediate goal is narrower: the next time the browser says it cannot connect to the server, the logs and tests must prove which of these happened:

1. one Dash callback failed with an ordinary Python exception;
2. the process stayed alive, but all Gunicorn request threads were occupied;
3. the worker timed out or was restarted;
4. the operating system or platform killed the process for memory;
5. a connector or reduced-tenor provider never returned;
6. the server returned successfully, but a large or malformed response froze the browser; or
7. the request never reached this application because the browser, proxy, or route failed.

Do the observability patch first. Do not increase timeouts, add workers, or rewrite promotion until one reproduced incident has a request ID, boot ID, process ID, memory reading, active-request count, and phase timings.

## Short answer

The strongest code-level explanation is **request-thread starvation with a possible memory spike**, not the credit-measure UUID and not necessarily a network socket failure.

The repository's production configuration defaults to one process and four request threads:

```python
# gunicorn.conf.py
workers = 1
threads = 4                  # default through GUNICORN_THREADS
worker_class = "gthread"
timeout = 300
```

Risk cache misses are serialized behind two process-global locks:

- `_RiskDataCache._filter_compute_lock` serializes every cold filter or reduction;
- `_RiskDataCache._render_compute_lock` serializes every cold component-tree render.

One concrete four-thread queue is possible without a circular deadlock:

```text
T1  Recalculate holds the filter lock
T2  Risk render holds the render lock, then waits for the filter lock
T3  another render waits for the render lock
T4  a detail/filter request waits for the filter lock
```

There is then no request thread available for `/healthz`, even though the worker and its background heartbeat can still be alive.

A thread waiting for either lock still occupies one of the four Gunicorn slots. Rapidly changing `SP01 -> PSP01 -> JTD -> Theta` can issue several full Risk callbacks. The pinned Dash 4.4 renderer can stop watching an older callback, but it does not cancel the HTTP request already executing in Python. Four current or superseded requests can therefore occupy all four server threads. At that point even `/healthz` and `/progressz` wait in the same queue, so the UI reports a server connection problem while the process may still be alive.

Recalculate adds a heavier chain:

```text
Credit measure click
  -> full Risk reducer/render callback
  -> cold filter/render cache variant may be built

Recalculate click
  -> all-Risk filtered/reduced book, risk_type=None
  -> promotion calculation and Python row materialisation
  -> new promotion-generation identifier is published
  -> Risk reducer/render runs again for that generation
```

The identifier is only the version of the newly calculated promotion result. It is not the expensive part. The expensive part is the all-Risk reduction/filter, the promotion copies/grouping, and the generation-specific rerender around it.

The 32-character UUID allocation is trivial, but a successful recalculation does put the new ID into filtered and rendered cache keys. Recalculating an identical basis repeatedly can therefore retain several generation-specific frames and component variants until count/byte eviction. The test plan below deliberately clicks an unchanged basis more than the 16-generation limit and verifies associated objects are evicted too.

Navigation appears to repair the page because it remounts a clean button and output tree. It does **not** prove the old server request stopped. In fact, returning to Risk can issue a fresh initial render while the abandoned request is still holding or waiting for a Risk lock.

## What implementing every earlier fix still leaves behind

The earlier guides solve real functional problems, but they do not eliminate this failure class:

- Fix 13 deliberately keeps serialized Risk component rendering and explains that cold hierarchy/open-row combinations wait for it.
- Fix 15 adds useful in-app logs, but those logs are process-local and bounded. They disappear when the worker restarts and cannot capture platform, proxy, or pre-logging failures.
- Fix 16 adds revision-owned reduced books and raises the exact filtered-frame allowance to 512 MiB. It reuses the same global filter lock and does not add one aggregate cache budget.
- Fix 22 confirms that Reduced Credit and Recalculate use two different reduced scopes: `(revision, "Credit")` and `(revision, None)`. It also confirms that Reduced can contain more rows than Full when unsupported sparse outputs are retained.
- Fix 23 native JTD pagination limits visible rows, but `page_action="native"` still sends every matching issuer record to the browser. It is display pagination, not server pagination.

So “all fixes applied” remains compatible with a process that is alive but thread-starved, or a process that is killed at a high-memory point.

## Repository-wide findings, ranked

| Priority | Failure mode | Exact code evidence | Why it matches |
|---|---|---|---|
| P0 | Four-thread starvation | `gunicorn.conf.py`; `_RiskDataCache.filtered()` and `.rendered()` in `cube/pages/risk/s02_state.py` | Several current/stale callbacks can fill all four slots while waiting on the two global locks; health polling then also stalls. |
| P0 | Recalculate callback 500 leaves the button stuck | `manage_promotion_generation()` in `cube/pages/risk/s12_promotecallbacks.py` catches only `TypeError` and `ValueError`; `assets/s13_risk.js` disables the button optimistically | Any other exception produces a Dash 500. No client `finally` resets the optimistic busy state. Navigation remounts it. |
| P0 | Memory kill/restart | 512 MiB filtered cache; unbounded reduced-frame bytes; 24 render trees by count; 16 promotion generations; full-book promotion copies; history result caches | An OS `SIGKILL`/exit 137 produces no Python traceback. App Logs vanish with the process. |
| P1 | Reduced-tenor peak allocation | `ReducedTenorReducer` accumulates chunk and batch DataFrames before two concatenations; Recalculate can separately build the all-Risk reduced book | The advertised tensor chunk bound is not a bound on final output or concatenation copies. |
| P1 | Connector gate exhaustion | `_DaemonConnectorCallGate` in `cube/services/s06_refresh.py` times out the waiter but cannot kill the connector thread; capacity is eight | Eight distinct permanently blocked calls make later connector work Busy until the original calls return or the process restarts. |
| P1 | Startup thread has no terminal transition for some `BaseException`s | the connector gate can retain/re-raise `BaseException`; `StartupCoordinator._run()` handles `Exception` | A dead startup worker can remain reported as running/non-retryable unless status explicitly detects `worker_alive=false`. |
| P1 | Clear Cache peak | `reset_refresh()` can build/copy the replacement snapshot before reconstructable UI caches are cleared | Old snapshot + old UI caches + staged frames + committed replacement + defensive return copy can coexist. |
| P1 | Browser unresolved request | pinned Dash 4.4 renderer plus optimistic state in `assets/s13_risk.js` | A request may continue after its output unmounts. A truncated HTTP-200 JSON body can surface as an unhandled rejection and leave the loading lifecycle unresolved. |
| P1 | Detached Risk observers | `riskGridObservers` in `assets/s11_tables.js` retains grid elements until a real `pagehide` | Native Dash Pages navigation does not unload the document; route cycles can retain detached grids and fail to attach to the replacement grids. |
| P2 | Large client payload | the main Risk callback returns 14 outputs; Fix 23 native JTD pagination sends all matches | A 200 can complete on the server yet spend a long time transferring, parsing JSON, or mounting React/DataTable nodes. |
| P2 | Proxy/platform event | there is no current request correlation or durable worker-lifecycle record | A 502/503/504 or container replacement cannot currently be separated from an application exception. |

### The main callback is unusually broad

`cube/pages/risk/s07_explorer.py::reduce_and_render_risk_view` is one synchronous callback with 14 outputs and roughly 22 inputs. It owns filter-control convergence, hierarchy rendering, alternate views, and detail output in one request. It currently has no outer start/error/finish envelope and no separate timings for:

- filter/reduced-book acquisition;
- hierarchy aggregation;
- component-tree construction;
- detail/JTD construction;
- JSON response size.

Changing a credit measure is display semantics, but it changes the render/cache key and can make this broad callback cold. Publishing a new promotion generation also invalidates generation-specific filter/render variants and invokes the callback again.

Record `browser_revision`, `cache_revision`, manager revision, refresh reason/stage, and whether an automatic refresh is active at callback start. The global 15-minute auto refresh can overlap a user's measure churn/Recalculate and commit a new revision through the same callback graph. Without these fields, a refresh race can look measure-specific.

Also record the number of expanded hierarchy rows. `risk-row-action-store.open_rows` validates key shape but has no cardinality ceiling; a large valid expansion can produce an enormous component response.

### Recalculate has several simultaneous allocations

`calculate_current_view_promotion()` does more than generate a UUID. In the current chain it can retain:

1. the cached all-Risk filtered or reduced book;
2. a full classified position copy;
3. grouped parent summaries;
4. a merge back to the full book;
5. another copy while preserving pins;
6. a second summary grouping; and
7. up to 20,000 Python `PromotionRow` objects.

These objects can overlap a previous credit-measure render and the generation-triggered next render.

### Cache memory is only partly bounded

`_RiskDataCache` currently has several independent retention policies rather than one process budget:

- filtered frames: at most 32 entries and 512 MiB;
- reduced frames: keyed by `(revision, active_risk_type)`, with no byte/entry bound;
- rendered Dash component trees: 24 entries, count-bound only;
- promotion generations: 16 entries, each with up to 20,000 Python rows;
- prepared frame, market quote maps, and reducer matrices: separate lifetimes.

There are other Python-side caches outside Risk:

- `SQLPLHistoryRepository._stats_cache` and `_risk_summary_cache` are ordinary dictionaries without entry or byte eviction until the repository connection/cache is cleared;
- history query LRUs retain DataFrames by identity/filter combination;
- source and P&L LRUs are count-bound rather than byte-bound.

DuckDB's configured memory limit does not limit these Python DataFrames, component trees, dictionaries, or dataclass rows.

### A stale render can be republished after a revision change

The filter/reduced publication paths recheck the revision. `cache.rendered()` does not. A render begun on revision N can finish after `replace_frame()` clears the caches for revision N+1, then insert the stale component tree back into `_rendered`. It may be unreachable but still consumes memory until eviction. Add an epoch/revision check before rendered publication and a deterministic regression for this race.

### Current scale evidence

A read-only repeated-fixture probe was used to expose retention shape; it is not a production forecast:

| Shape | Prepared | Reduced Credit | Reduced all-Risk | Filtered cache | Retained DataFrame subtotal |
|---|---:|---:|---:|---:|---:|
| checked-in 10,572-row fixture | 7.6 MiB | 0.8 MiB | 10.2 MiB | 11.2 MiB | 29.8 MiB |
| 100,000 repeated production-shape rows | 72.5 MiB | 7.5 MiB | 92.9 MiB | 100.4 MiB | about 273 MiB including both reduced scopes |

The 100,000-row probe excludes rendered component trees, promotion dataclasses and transient copies, SearchCatalog, manager snapshots, refresh staging, response serialization, and history caches. It also confirmed that Reduced is not guaranteed to be smaller: the checked-in fixture goes from 10,572 Full rows to 12,378 Reduced rows, including 1,806 unsupported blank-output rows documented in Fix 22.

## What the current checks do and do not prove

The focused existing suite is healthy:

```text
86 passed
tests/s12_startup.py
tests/s19_riskfilters.py
tests/s32_observability.py
tests/s45_failurevisibility.py
tests/s46_applogs.py
```

That proves the existing startup, cache, operator-log, and Python failure contracts. It does not run a real one-worker/four-thread Gunicorn process, issue concurrent Dash HTTP POSTs, measure response bytes/RSS, kill a worker, or execute the browser lifecycle.

The current benchmark also does not clear this incident. On this audit run:

- app import, 10,572-row refresh, 100k prepare/filter/render, market history, stock history, and P&L overview were inside their budgets;
- Risk history first-open took 7,095 ms against a 2,500 ms budget, so `tools/s03_benchmark.py --enforce` exited 1;
- the benchmark is sequential and has no Reduced Credit -> measure churn -> all-Risk Recalculate path.

The live Plotly runtime could not be inspected during this audit because the saved CLI session returned HTTP 401 for both app status and runtime logs. That means this document ranks plausible causes from code evidence; it does not pretend to name the latest production exit reason without platform logs.

## The minimum event contract

Every heavy request and operation needs a start record and exactly one terminal record. Completion-only timing is not enough: an OOM kill or timeout happens before the completion log.

Use these identifiers consistently:

| Field | Meaning |
|---|---|
| `server_boot_id` | one random ID for the lifetime of the application process; reuse `StartupCoordinator.server_boot_id` |
| `pid` | operating-system process ID |
| `request_id` | one random ID per HTTP request, returned as `X-Cube-Request-ID` |
| `operation_id` | one random ID per expensive logical operation such as promotion calculation or reduced build |
| `revision` | committed financial snapshot revision, never a financial value |

Safe event fields are:

```text
event, status, stage, request_id, operation_id, server_boot_id,
pid, thread, method, path, http_status, request_bytes, response_bytes,
duration_ms, active_requests, oldest_request_ms, rss_mb, peak_rss_mb,
revision, cache_hit, lock_wait_ms, compute_ms, rows, cache_entries,
cache_bytes, connector_active, connector_oldest_seconds
```

Never log:

- a Dash request body;
- filter values, Underlyings, books, portfolios, trade IDs, or financial values;
- query strings;
- cookies, authorization headers, tokens, or connector credentials;
- a whole DataFrame, records list, or response body.

Log only the URL path without its query. Do not parse the Dash JSON body in generic middleware merely to obtain inputs. Explicit phase logs inside the known callbacks provide safer operation names without retaining or accidentally printing user data.

## Step-by-step diagnostic patch

Apply the changes in this order. The first rollout should add evidence, not alter financial results.

### 1. Configure logging before the rest of the application imports

In `app.py`, import and call the logging bootstrap before importing adapters, pages, history repositories, or connector factories:

```python
from cube.app.s03_logging import configure_runtime_logging, perf_span

configure_runtime_logging()

# Import the remaining cube modules only after logging is live.
from cube.adapters.s08_stock import get_stock  # noqa: E402
from cube.app.s07_factory import build_app  # noqa: E402
# ...the remaining current imports...
```

At present, most Cube modules are imported before `configure_runtime_logging()`. An import-time exception can therefore precede the configured terminal/application handlers.

Do not make App Logs the crash authority. `cube/app/s03_logging.py` keeps only 200 process-local entries, limits each record to 4,000 characters, and returns at most 100/64 KiB. It is useful while the worker lives; stdout/stderr runtime logs must be the durable incident source.

Extend `_OPERATOR_EVENT_FIELDS` in `cube/app/s03_logging.py` with the safe network fields above so the in-app drawer can show the latest incident IDs. Keep the existing redaction and response bounds.

### 2. Add one request/process diagnostics module

Create `cube/app/s09_network.py`. Keep it independent of pandas and financial modules so health and logging never acquire a snapshot/cache lock.

The module should own:

- the shared boot ID supplied by the startup coordinator;
- a lock-protected map of `request_id -> monotonic start`;
- request start/finish/error hooks;
- a cheap process snapshot;
- a periodic stdout heartbeat;
- a helper that returns the current request ID to callback phase logs.

Use this shape:

```python
from __future__ import annotations

from pathlib import Path
from threading import Event, Lock, Thread, active_count
from time import monotonic, perf_counter
from uuid import uuid4
import logging
import os

from flask import Flask, g, got_request_exception, has_request_context, request


LOGGER = logging.getLogger("cube.network")
_SLOW_REQUEST_MS = float(os.getenv("CUBE_SLOW_REQUEST_MS", "2000"))


def _linux_memory() -> tuple[int | None, int | None]:
    """Return current and high-water RSS bytes without adding a dependency."""
    try:
        values: dict[str, int] = {}
        for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
            name, separator, rest = line.partition(":")
            if separator and name in {"VmRSS", "VmHWM"}:
                values[name] = int(rest.split()[0]) * 1024
        return values.get("VmRSS"), values.get("VmHWM")
    except (OSError, ValueError, IndexError):
        return None, None


class NetworkDiagnostics:
    def __init__(self, server_boot_id: str) -> None:
        self.server_boot_id = str(server_boot_id)
        self.started_at = monotonic()
        self._lock = Lock()
        self._inflight: dict[str, float] = {}
        self._heartbeat_stop = Event()

    def _begin(self, request_id: str) -> int:
        with self._lock:
            self._inflight[request_id] = monotonic()
            return len(self._inflight)

    def _finish(self, request_id: str) -> None:
        with self._lock:
            self._inflight.pop(request_id, None)

    def snapshot(self, *, include_memory: bool = True) -> dict[str, object]:
        now = monotonic()
        with self._lock:
            starts = tuple(self._inflight.values())
        rss, peak = _linux_memory() if include_memory else (None, None)
        return {
            "server_boot_id": self.server_boot_id,
            "pid": os.getpid(),
            "uptime_seconds": round(now - self.started_at, 3),
            "thread_count": active_count(),
            "active_requests": len(starts),
            "oldest_request_ms": (
                round((now - min(starts)) * 1000.0, 3) if starts else 0.0
            ),
            "rss_bytes": rss,
            "peak_rss_bytes": peak,
        }

    @staticmethod
    def current_request_id() -> str | None:
        if not has_request_context():
            return None
        return getattr(g, "cube_request_id", None)

    def install(self, server: Flask) -> None:
        @server.before_request
        def cube_request_start() -> None:
            request_id = uuid4().hex
            g.cube_request_id = request_id
            g.cube_request_started = perf_counter()
            g.cube_request_finished = False
            active = self._begin(request_id)
            if request.path.endswith("_dash-update-component") or request.method != "GET":
                LOGGER.info(
                    "cube.http.start request_id=%s boot=%s pid=%s method=%s path=%s "
                    "request_bytes=%s active=%s",
                    request_id,
                    self.server_boot_id,
                    os.getpid(),
                    request.method,
                    request.path,
                    request.content_length,
                    active,
                )

        @server.after_request
        def cube_request_finish(response):
            request_id = getattr(g, "cube_request_id", "missing")
            started = getattr(g, "cube_request_started", perf_counter())
            duration_ms = (perf_counter() - started) * 1000.0
            response.headers["X-Cube-Request-ID"] = request_id
            response.headers["X-Cube-Boot-ID"] = self.server_boot_id
            response.headers["Server-Timing"] = f"cube;dur={duration_ms:.3f}"
            self._finish(request_id)
            g.cube_request_finished = True
            traced = request.path.endswith("_dash-update-component") or request.method != "GET"
            unusual = response.status_code >= 400 or duration_ms >= _SLOW_REQUEST_MS
            if traced or unusual:
                snapshot = self.snapshot(include_memory=True)
                level = logging.WARNING if unusual else logging.INFO
                LOGGER.log(
                    level,
                    "cube.http.finish request_id=%s boot=%s pid=%s method=%s path=%s "
                    "status=%s duration_ms=%.3f request_bytes=%s response_bytes=%s "
                    "active=%s oldest_request_ms=%s rss_bytes=%s",
                    request_id,
                    self.server_boot_id,
                    os.getpid(),
                    request.method,
                    request.path,
                    response.status_code,
                    duration_ms,
                    request.content_length,
                    response.content_length,
                    snapshot["active_requests"],
                    snapshot["oldest_request_ms"],
                    snapshot["rss_bytes"],
                )
            return response

        def cube_request_exception(sender, exception, **_extra) -> None:
            request_id = getattr(g, "cube_request_id", "missing")
            LOGGER.error(
                "cube.http.error request_id=%s boot=%s pid=%s error_type=%s",
                request_id,
                self.server_boot_id,
                os.getpid(),
                type(exception).__name__,
                exc_info=(type(exception), exception, exception.__traceback__),
            )

        # Keep a strong receiver: this function is local to install().
        got_request_exception.connect(
            cube_request_exception,
            sender=server,
            weak=False,
        )

        @server.teardown_request
        def cube_request_teardown(_error: BaseException | None) -> None:
            if getattr(g, "cube_request_finished", False):
                return
            request_id = getattr(g, "cube_request_id", "missing")
            self._finish(request_id)
```

The production version should emit these as `cube_operator_event` dictionaries too, using only the safe field allowlist. The example intentionally does not parse request JSON and does not call `response.get_data()`, because either can increase memory or expose values. `response.content_length` may legitimately be `None`; Gunicorn access logging supplies the final response length as an independent measurement.

`/proc/self/status` provides current/high-water RSS on the Linux deployment. It returns `None` on local Windows. For a Windows-only soak, collect the child process working set from the test harness or add a pinned cross-platform process-metrics dependency; do not make the health endpoint fail when RSS is unavailable.

Add a heartbeat method which logs `process.heartbeat` every 15 seconds while diagnostics are enabled. It should call `snapshot()` and cheap, precomputed cache/gate snapshots. It must never calculate `DataFrame.memory_usage(deep=True)` on the heartbeat thread. Compute byte counts when a cache entry is published, then read counters here.

Recommended environment controls:

```text
CUBE_NETWORK_DIAGNOSTICS=1
CUBE_DIAGNOSTICS_HEARTBEAT_SECONDS=15
CUBE_SLOW_REQUEST_MS=2000
```

After the incident is fixed, keep the request IDs and worker lifecycle permanently; move the heartbeat to 30–60 seconds or disable it by environment.

### 3. Install diagnostics with the existing boot ID

In `cube/app/s07_factory.py`, create diagnostics after `StartupCoordinator` is created and before routes/callbacks can serve requests:

```python
from uuid import uuid4

from cube.app.s09_network import NetworkDiagnostics


startup = startup_coordinator.status() if startup_coordinator is not None else None
server_boot_id = startup.server_boot_id if startup is not None else uuid4().hex
network_diagnostics = NetworkDiagnostics(server_boot_id)
network_diagnostics.install(app.server)
app.server.config["CUBE_NETWORK_DIAGNOSTICS"] = network_diagnostics
```

Use this same `server_boot_id` everywhere. Do not create a second unrelated boot UUID in each page or callback.

Add the following safe fields to `/healthz` and `/progressz`:

```text
server_boot_id, pid, uptime_seconds, thread_count,
active_requests, oldest_request_ms, rss_bytes, peak_rss_bytes
```

Keep `/progressz` frame-free and cache-lock-free. Preserve the current `/healthz` status-code contract until the deployment health-probe behavior is known.

Optionally add:

- `/livez`: returns 200 if this WSGI process can answer;
- `/readyz`: returns 200 only when a usable snapshot exists, otherwise 503.

These endpoints must only read cheap counters. A lock-free handler still cannot respond if all four Gunicorn request slots are already occupied, so a timeout with a continuing process heartbeat is itself the starvation signature. Do not claim that adding `/livez` reserves capacity.

### 4. Turn on Gunicorn access, error, and worker-lifecycle logs

Extend `gunicorn.conf.py`:

```python
import faulthandler
import os
import sys


network_diagnostics = os.getenv("CUBE_NETWORK_DIAGNOSTICS", "0") == "1"
accesslog = "-" if network_diagnostics else None
errorlog = "-"
capture_output = True
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")
access_log_format = (
    "%(t)s pid=%(p)s method=%(m)s path=%(U)s status=%(s)s "
    "response_bytes=%(B)s duration_us=%(D)s "
    "request_id=%({x-cube-request-id}o)s"
)


def post_worker_init(worker):
    faulthandler.enable(file=sys.stderr, all_threads=True)
    worker.log.info("cube.worker.ready pid=%s", worker.pid)


def worker_abort(worker):
    worker.log.critical("cube.worker.abort pid=%s", worker.pid)
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)


def worker_exit(server, worker):
    server.log.warning("cube.worker.exit pid=%s", worker.pid)


def child_exit(server, worker):
    server.log.warning("cube.worker.child_exit pid=%s", worker.pid)
```

Gunicorn documents `worker_abort` as the hook generally reached on a worker timeout. It also documents `%(D)s` as request microseconds and `{header}o` as a response header in the access format. The response request ID therefore joins the application start/finish event to the Gunicorn access event.

Keep the access log gated by incident mode: otherwise every browser's one-second `/progressz` request creates a durable line. If access logging must remain permanently enabled, add a tested custom logger/filter which samples successful health/progress GETs while always retaining slow, failed, Dash POST, and lifecycle records.

`timeout=300` means worker silence, not a guaranteed 300-second deadline for each request, especially with a `gthread` worker. A hosting proxy may abandon one long response earlier while Python continues working, and an otherwise responsive threaded worker may not be killed merely because one callback is long. Treat an actual `worker_abort`/platform termination record as evidence; do not infer one from elapsed time alone.

A `SIGKILL` or whole-container kill cannot run a Python exit hook. That absence is useful evidence: an abrupt heartbeat end followed by a new boot ID, especially with exit 137/OOM in platform logs, is a process kill rather than a caught callback exception.

Log `BrokenPipeError`/client-disconnect cases distinctly. They usually mean the browser or hosting proxy gave up on a long response while Python was still computing or writing; they are not proof that the worker originated the failure.

Do not enable `max_requests` as the first response. Automatic recycling can hide a leak and deliberately destroys the process-local snapshot. Diagnose and bound the retained objects first.

### 5. Add start/finish/error phase logs around Risk

Add a small context manager beside the network diagnostics which emits:

```text
<operation>.start  operation_id=... request_id=...
<operation>.finish operation_id=... request_id=... duration_ms=...
<operation>.error  operation_id=... request_id=... error_type=... traceback
```

It must log `.start` before entering a cache/provider/aggregation call and use `finally` for the terminal event.

Instrument these exact places:

#### `cube/pages/risk/s07_explorer.py`

Wrap `reduce_and_render_risk_view` and separately time:

```text
risk.view.total
risk.view.filter_or_reduce
risk.view.hierarchy
risk.view.render
risk.view.detail
risk.view.jtd
```

Include revision, risk-type category, cache hit, row count, response-safe component count, and bytes where available. Do not log the selected Risk Type, measure, book, or underlying as free text; use a fixed enumerated category or a hash only if correlation truly needs it.

Record filter-lock wait separately from compute. A 45-second call with `lock_wait_ms=44,000` is a queue problem; a 45-second call with `compute_ms=44,000` is an algorithm/provider problem.

#### `cube/pages/risk/s12_promotecallbacks.py`

Emit a start breadcrumb before `cache.filtered()` and split the operation into:

```text
risk.promotion.filter_reduce
risk.promotion.parent_aggregation
risk.promotion.row_materialisation
risk.promotion.publish
risk.promotion.total
```

Change the callback boundary from:

```python
except (TypeError, ValueError) as error:
```

to:

```python
except Exception as error:
    app.logger.exception(
        "risk.promotion.calculate failed incident=%s revision=%s",
        operation_id,
        revision,
    )
    # Return the existing baseline-restored failure tuple, including:
    # button text normal, disabled=False, aria-busy="false".
```

Do not catch `BaseException`; `KeyboardInterrupt`, `SystemExit`, and process signals are not ordinary callback failures. Keep the existing visible baseline-restored behavior for all ordinary exceptions.

#### `cube/pages/risk/s02_state.py`

For `filtered()`, `_reduced_for_scope()`, and `rendered()` record:

- cache hit/miss;
- time waiting for the compute lock;
- build time after lock acquisition;
- revision/epoch at start and publication;
- rows and precomputed retained bytes;
- total entries/bytes by cache class.

Add a revision/epoch guard to `rendered()` before publishing the completed component tree. If the cache epoch changed, return the result to the already-running caller if needed but do not retain it in the new revision cache.

#### `cube/domain/s11_tenorreduction.py`

Record provider/catalog acquisition, batch count, input/output rows, current RSS before/after, and both concatenation phases. The tensor's 32 MiB chunk target is not a full-operation memory ceiling because chunk DataFrames and batch DataFrames are accumulated before concatenation.

The production request path should use revision-committed matrices. If a real reduced-tenor provider performs network I/O lazily under `_cache_lock`, move that I/O to refresh/staging and give the native client explicit connect/read deadlines. A request callback must not hold the global Risk filter lock around unbounded provider I/O.

Aggregate incomplete-mapping coverage into one bounded warning per build/source/Greek/missing-tenor set. The current Credit batch path can warn once per raw Underlying; thousands of incomplete issuers can generate thousands of synchronous stdout records, repeat for Credit and all-Risk scopes, slow the build, and evict the useful first diagnostics. Test that 10,000 equivalent misses produce O(1) warnings plus counts, never 10,000 lines.

#### `cube/pages/risk/s14_workspacecallbacks.py`

Assert and log that Aggregate P&L is gated when its view is closed, as Fix 13 requires. Documentation is not proof that the deployed callback map contains the gate.

#### `cube/services/s08_jtd.py`

Record source byte size, matching row count, result JSON bytes, and duration. Never log issuer names or rows. If Fix 23 can return a large issuer, move from native to custom/server pagination or enforce an explicit validated maximum.

Test JTD both with no selected cell and with an existing selected cell: the measure change enters the main table callback, and a retained selection can make the same request rebuild JTD detail and scan/copy all exact issuer matches.

### 6. Add cheap cache and connector snapshots

Add `_RiskDataCache.diagnostics()` with counters updated when objects are inserted/evicted:

```python
{
    "revision": ...,
    "prepared_bytes": ...,
    "filtered_entries": ...,
    "filtered_bytes": ...,
    "reduced_entries": ...,
    "reduced_bytes": ...,
    "render_entries": ...,
    "promotion_generations": ...,
    "promotion_rows": ...,
}
```

For reduced frames, deduplicate by object identity when accounting if two keys share an object. Calculate deep DataFrame size once at publication, not during health polling. For component trees, HTTP response bytes are the most useful transfer measurement; if retained-object sizing is not reliable, expose count and the last/max serialized response size rather than pretending to have an exact Python-object size.

Add `_DaemonConnectorCallGate.diagnostics()`:

```python
{
    "active": ...,
    "capacity": 8,
    "oldest_seconds": ...,
    "timed_out_total": ...,
    "busy_total": ...,
    "late_completed_total": ...,
}
```

Do not expose raw connector keys. At most log a stable bounded hash. A manager timeout only stops waiting; it does not cancel the native thread. The native connector itself must use connect/read/query timeouts so the gate eventually drains.

This checkout's production-manager composition still uses local fixture CSV/Parquet/in-memory providers; it does not contain the site's real HTTP/database client bodies. The repository can test the outer 15-second gate, but it cannot prove a replacement client closes its socket, cursor, or query after that deadline. Audit and instrument those replacement bodies at their actual deployment boundary. If this checkout is deployed unchanged, starvation/memory is more plausible than an upstream network socket.

Make the connector/startup exception policies consistent. `_DaemonConnectorCallGate` can capture and re-raise a `BaseException`, while `StartupCoordinator._run()` handles ordinary `Exception`. Add an explicit status transition when the startup thread is no longer alive but the phase is still `running`, log the terminal incident, and make it retryable where safe. Test `asyncio.CancelledError` and `SystemExit` in a subprocess so the test runner itself is not terminated.

Add configurable per-source row/byte ceilings immediately after each real connector result, before adapters, joins, SearchCatalog, and defensive copies amplify it. Check row count, upstream/file size, and shallow bytes first. Computing `memory_usage(deep=True)` across a pathological object-string frame can itself become the expensive failure, so calculate deep bytes only below the early ceiling or sample safely. Failure-inject a 10x/100x oversized but valid-shaped result and apply the existing source's fail-soft/fail-hard contract instead of letting the operating system choose the outcome.

Also expose cheap counts for the unbounded SQL history dictionaries and the bounded DataFrame LRUs. The soak test should prove they plateau or should replace them with entry-and-byte-bounded caches.

### 7. Add a process heartbeat to durable stdout

Every 15 seconds during diagnosis, emit one line with:

```text
process.heartbeat server_boot_id pid uptime rss peak_rss thread_count
active_requests oldest_request_ms revision refresh_stage progress_age
filtered_bytes reduced_bytes render_entries promotion_rows
connector_active connector_oldest_seconds
```

This heartbeat is more important than the in-app log drawer:

- heartbeat continues, same boot, active requests reaches four, health times out: request-thread starvation;
- heartbeat continues but connector oldest age grows: connector/provider stall;
- heartbeat stops abruptly after increasing RSS, then a new boot starts: likely memory/process kill;
- an actual `worker_abort` and all-thread dump appear: Gunicorn timeout/stall (the configured 300 seconds is not a per-request stopwatch);
- heartbeat and health remain quick while one request returns 500: callback exception.

Rate-limit automatic all-thread stack dumps. A useful diagnostic rule is one dump after an operation/lock/progress value is unchanged for 30–60 seconds, then no more than one every five minutes. Stack dumps go to stderr/runtime logs, never the browser.

### 8. Add browser transport diagnostics and reliable recovery

Extend `assets/s12_refresh.js` so diagnostics exist for ordinary Dash callbacks, not only an active refresh panel.

Capture a bounded `sessionStorage` ring buffer containing only:

```text
UTC time, client event type, endpoint path, HTTP status,
elapsed time, response content type, transfer size,
the diagnostic probe's request/boot IDs, online/offline state
```

Developer Tools, Playwright, and the server/proxy logs can read `X-Cube-Request-ID` from Dash's internal fetch response. Ordinary application JavaScript does not automatically receive that raw `Response`. Do not monkey-patch Dash's private fetch just to expose the header. For an in-page incident ID, use the app's own `/healthz` probe, a tested `Server-Timing` path, or a normal callback error/status output. Browser support for any Resource Timing correlation must be tested before relying on it.

Listen for:

- `window.error`;
- `window.unhandledrejection` using only bounded error name/message;
- `online` and `offline`;
- resource timing for `/_dash-update-component`, `/healthz`, and `/progressz`;
- a Dash loading marker remaining active beyond two seconds.

When loading persists, probe `/healthz` with a 3–5 second browser timeout. The existing progress fetch waits 30 seconds and only covers the refresh lifecycle; that is too slow and does not cancel Python callback work.

Show one of these truthful statuses:

```text
Server alive; callback still running
Server alive; callback returned an error (incident ... when available)
Server process restarted (old boot ... -> new boot ...)
Server did not answer; checking platform/runtime logs
Browser received an invalid or interrupted response
Browser is offline
```

Do not build an automatic reload loop. Offer one explicit retry/remount after recording the diagnostic buffer.

In `assets/s13_risk.js`, keep the immediate visual feedback, but add bounded recovery after a confirmed callback failure or boot-ID change. The Python outputs remain authoritative. A server 500, request failure, invalid JSON, or replaced process must restore:

```text
children="Recalculate all Risk views"
disabled=false
aria-busy="false"
```

Do not patch the vendored Dash renderer in `.venv`. Validate whether a later Dash release fixes the unresolved/truncated-response behavior, but treat a Dash upgrade as a separate change because this repository intentionally pins 4.4.0 and has lifecycle-sensitive DataTable/Patch behavior.

### 9. Clean up detached Risk grid observers

Before attaching observers in `assets/s11_tables.js::connectRiskGridObservers`, prune detached elements:

```javascript
riskGridObservers.forEach((observer, grid) => {
  if (!grid.isConnected) {
    observer.disconnect();
    riskGridObservers.delete(grid);
  }
});
```

Reset the retry counter when native page content changes and reconnect against the current `risk-grid` and `alt-risk-grid`. A real `pagehide` only occurs when the document unloads; moving between native Dash pages does not guarantee it.

On route unmount also clear `selectedCells`, `rangeGesture`, and `suppressedMetricClick` references which point at detached table cells. Instrument the document-wide UI observer's batch/node count and duration; if large Risk mounts create browser long tasks, skip known Risk-table subtrees or observe only the stable hook containers.

This is probably secondary to server starvation, but route-cycle memory/stale observer behavior should not contaminate the browser reproduction.

### 10. Add an external probe

Create `tools/s04_network_probe.py` with this interface:

```text
python tools/s04_network_probe.py \
  --base-url http://127.0.0.1:8050 \
  --seconds 600 \
  --interval 0.5 \
  --timeout 4 \
  --output network-probe.jsonl
```

For `/healthz` and `/progressz`, record only:

```text
timestamp_utc, endpoint, status, elapsed_ms, content_type,
server_boot_id, pid, request_id, active_requests,
oldest_request_ms, rss_bytes, error_type
```

Do not store response bodies or authentication values. If the deployed app requires browser authentication, run the probe locally against the same Gunicorn command or use the browser's signed-in Network panel; do not copy session cookies into a report.

## Tests which can actually classify the failure

Create `tests/s49_network.py` for fast contracts, then add a real-server and browser tier. Tests which call callback functions through `.__wrapped__` do not exercise Dash JSON serialization, HTTP concurrency, routing, or JavaScript lifecycle.

### A. Fast middleware and safety tests

Test that:

1. every response has unique, bounded `X-Cube-Request-ID` and stable `X-Cube-Boot-ID`;
2. start and finish events share the request ID;
3. a route exception produces one error/500 record and decrements active requests;
4. successful one-second `/progressz` polling does not flood INFO logs;
5. a slow or failing poll is logged;
6. query strings, request JSON, cookies, authorization, filter values, and response bodies never appear;
7. `/healthz`/`/progressz` expose only the safe process fields;
8. the request tracker returns to zero after exceptions;
9. heartbeat fields are cheap precomputed values;
10. Gunicorn config enables stdout access/error logs and the lifecycle hooks.

### B. Actual Dash HTTP tests

Use the Flask/Dash client to POST the real `/_dash-update-component` payload for:

- each Credit measure;
- Recalculate;
- the generation-triggered Risk rerender;
- a selected JTD detail.

Assert:

- no 500;
- `application/json` response;
- request/boot correlation headers;
- start plus one finish/error event;
- response byte budget;
- no financial input values in logs;
- every failure tuple re-enables Recalculate.

Keep direct domain/callback unit tests too; the HTTP layer supplements them.

### C. Real Gunicorn contention test

Flask `test_client` cannot reproduce the configured worker pool. On Linux CI or the deployment image:

1. start real Gunicorn with one worker and four threads;
2. inject a controlled slow reduced/render builder;
3. issue four or more concurrent Risk POSTs with different cold keys;
4. request `/healthz` every 250–500 ms with a one-second deadline;
5. capture request IDs, heartbeat, active count, oldest age, lock wait, and boot ID.

The test should initially reproduce the classifier even if the health call times out. The permanent fix must either keep health responsive or explicitly reject/coalesce excess heavy work instead of leaving every thread waiting indefinitely.

Do not “fix” the test by adding worker processes. The snapshot, startup coordinator, caches, and promotion generations are process-local; more workers would give users inconsistent state unless those owners are redesigned.

### D. Exact browser reproduction

Add Playwright or Dash browser coverage for:

```text
Open Risk / Credit / Reduced
SP01 -> PSP01 -> JTD -> Theta rapidly
click Recalculate
navigate away while one request is active
return to Risk
select a large JTD issuer
repeat 20–50 cycles
```

Capture:

- `request`, `response`, and `requestfailed` for `/_dash-update-component`;
- response request/boot IDs and byte sizes;
- console errors and `pageerror`;
- `unhandledrejection`;
- time to response start/end;
- time from response end until Dash loading clears and two animation frames pass;
- browser long tasks;
- connected Risk observer count;
- server RSS/cache counters.

Assert that:

- normal runs keep the same boot ID;
- Recalculate ends enabled with `aria-busy=false`;
- only the two currently connected Risk grids are observed;
- old/unmounted callback requests are coalesced or finish within a bound;
- server and browser memory plateau;
- response size and post-response mount time stay within explicit budgets.

Add one browser fault which intercepts a Dash response and returns status 200 with truncated JSON. The app must record “invalid/interrupted response” and offer recovery instead of remaining permanently busy.

### E. Memory/soak tests

Run the sequence at 100k and 250k production-shape rows in a subprocess so RSS and worker survival are observable. Measure after each phase:

```text
committed/prepared snapshot
Reduced Credit
all credit measure variants
all-Risk Reduced Recalculate
promotion row materialisation
generation-triggered rerender
JTD detail
clear cache / refresh
```

Require:

- aggregate cache bytes plateau after eviction;
- generation eviction also removes generation-specific filter/render entries;
- stale revision renders are not retained;
- thread count returns to baseline;
- connector gate returns to zero;
- second warm calculation is a cache hit;
- no monotonic RSS growth across 20–50 cycles.

The reduced-tenor stress must measure peak RSS, not only final frame bytes, because both chunk and batch concatenations temporarily coexist.

### F. Connector and refresh fault tests

Add deterministic cases for:

1. eight distinct blocked connector keys, then a ninth Busy response;
2. releasing all eight and proving active returns to zero;
3. a timed-out call which later completes and increments `late_completed_total`;
4. a native connector deadline which really terminates its I/O/thread;
5. a slow matrix provider which must not run under a request lock;
6. refresh failure at release/SearchCatalog while retaining the last-good snapshot;
7. peak RSS during atomic refresh;
8. Clear Cache ordering and no-copy return behavior;
9. a dead startup thread after `CancelledError`/`SystemExit` reaches a visible terminal/retryable state;
10. eight timed-out connectors cannot all allocate/return huge late results together;
11. forced worker exit mid-refresh and a changed boot ID after recovery.

### G. Cache-boundary tests outside Risk

Generate many unique history/filter/source keys and prove:

- SQL result dictionaries are bounded or explicitly cleared;
- DataFrame LRUs have a byte ceiling, not only a count;
- Clear Cache reaches every reconstructable process cache intended by its label;
- financial last-good state remains available;
- no cache-clearing test changes source authority or financial values.

## Live incident runbook

### 1. Restore Plotly CLI access

From the repository:

```powershell
$env:PYTHONUTF8='1'
.\.venv\Scripts\plotly.exe user login
.\.venv\Scripts\plotly.exe user whoami
.\.venv\Scripts\plotly.exe app status --verbose
.\.venv\Scripts\plotly.exe app logs --type runtime
```

The UTF-8 environment avoids the local CLI's Windows Unicode rendering issue. If login is not allowed from that machine, obtain the runtime logs from the Plotly Cloud UI instead.

### 2. Deploy only the diagnostic patch first

Enable request IDs, Gunicorn logs, heartbeat, phase timings, and browser diagnostics. Do not combine this deploy with a cache/algorithm/worker-count change; otherwise the first reproduction cannot isolate cause.

Record the deployed Git SHA/build time in a generated `build.json` or one `process.boot` log. Never guess which code the worker is running.

### 3. Capture the browser

Open browser developer tools before reproducing:

- Network: Preserve log;
- Console: preserve messages;
- filter Network to `_dash-update-component`, `healthz`, and `progressz`;
- record UTC start time and the exact selector sequence;
- save the HAR only if permitted, then remove cookies/query data before sharing it.

### 4. Run the probe and exact sequence

Start `tools/s04_network_probe.py`, then:

```text
Risk -> Credit -> Reduced
SP01 -> PSP01 -> JTD -> Theta
Recalculate all Risk views
wait without navigating for the first failure capture
then navigate away/back once and record whether boot_id changed
```

The first untouched failure is more useful than repeated reload attempts.

### 5. Collect one incident bundle

Keep:

- exact UTC window;
- deployed Git SHA;
- external runtime logs;
- probe JSONL;
- browser console diagnostics;
- sanitized HAR or request-ID list;
- benchmark/test output;
- old and new boot IDs;
- last five process heartbeats.

Do not include financial records or credentials.

## How to read the evidence

| Observed evidence | Classification | Next action |
|---|---|---|
| Dash POST returns 500; same boot ID; matching traceback/request ID | ordinary callback error | Fix that exact exception and keep reliable busy-state reset. |
| Dash POST remains pending; heartbeat continues; active requests approaches four; lock wait grows; health/progress time out; boot unchanged after recovery | Gunicorn thread starvation | Coalesce/debounce stale work; replace coarse global waiting with keyed single-flight/bounded admission; preserve health capacity. |
| Health and heartbeat both pause during Python component/JSON work, then the same boot ID returns | GIL/CPU starvation | Bound component/response size and move/reduce Python-heavy construction; a spare request thread alone may not help. |
| One POST is slow but health remains fast; same boot | isolated slow callback | Use phase timings to optimize the phase, provider, or payload. |
| Request start exists but no finish; an actual `worker_abort`/thread dump is logged | Gunicorn worker timeout/stall | Fix the blocked phase/native deadline; do not merely raise the timeout. |
| Heartbeat RSS rises, then all logs stop; new boot ID; exit 137/OOM/SIGKILL | memory kill | Add aggregate byte bounds and remove peak copies/duplicate reduced scopes. |
| New boot ID with no Python traceback and no prior request start | platform/container replacement | Inspect platform lifecycle/build/resource logs. |
| Browser has 502/503/504 but application has no matching request start | proxy/routing/platform | Inspect Plotly ingress and deployment status, not financial code. |
| Health fast; response is 200 and large; server timing short; browser loading clears much later with long tasks | transfer/JSON/React/DataTable cost | Bound response, server-page/virtualize, and reduce component tree size. |
| Status 200 but truncated/invalid JSON; `unhandledrejection`; busy state never clears | interrupted response/client lifecycle | Prevent kill/oversize transfer and add app-level failure recovery; separately assess Dash upgrade. |
| No Network request after click | stale DOM/client event problem | Fix observer/listener/remount lifecycle. |
| Connector active/oldest grows, progress does not advance | missing native connector timeout | Add connect/read/query deadline and gate telemetry. |
| Navigating back recovers UI, boot unchanged | UI remount or stale request, not a process restart | Correlate the old and new request IDs; do not count remount as cancellation. |
| Navigating back returns a new boot ID | worker/container restarted | Use the last heartbeat, Gunicorn, and platform exit reason. |

## Smallest permanent fix after classification

Do not implement every possible fix at once. Apply the row proven by the evidence.

### If it is thread starvation

1. debounce/coalesce rapid credit-measure changes;
2. add per-key single-flight so duplicate keys share one build;
3. stop waiting indefinitely inside all four request threads—use bounded admission and return/retry for superseded work;
4. attach a cache epoch/revision and discard stale publication;
5. keep one process unless shared snapshot/state is redesigned;
6. prove `/healthz` latency under the real Gunicorn contention test.

Increasing threads alone only admits more memory-heavy work and can make OOM more likely.

### If it is memory

1. introduce one environment-configured aggregate Risk cache budget;
2. byte-bound reduced frames, rendered responses/component variants, and promotion generations;
3. evict generation-associated filtered/rendered entries with the generation;
4. eliminate the duplicate `(revision, "Credit")` / `(revision, None)` reduced retention if equivalence tests prove a safe shared representation;
5. optimize promotion Recalculate to aggregate/classify/preserve pins once at parent grain instead of merge-back/copy/re-group;
6. eliminate unsupported blank reduced output rows only after the Fix 22 contract tests approve the policy;
7. clear reconstructable UI caches before the forced Clear Cache refresh and return metadata/no-copy rather than a defensive full snapshot copy;
8. bound SQL history/source caches;
9. use staged incremental/preallocated reduction output if peak concatenation remains the high-water point.

Do not hard-code a memory threshold based on an assumed 20 GB host. Read the actual deployment resource ceiling, make budgets configurable, and leave headroom for atomic refresh plus response serialization.

### If it is a callback exception

Use the exact request/operation ID and traceback. Catch ordinary exceptions at the promotion callback boundary, log with `logger.exception`, restore baseline status, and always return a non-busy button. Add the exact HTTP regression which failed.

### If it is payload/browser rendering

1. record encoded and decoded response sizes;
2. server-page large JTD issuers rather than native-page all records;
3. cap or virtualize very large detail/table outputs;
4. avoid returning unchanged large outputs from the 14-output callback;
5. test time from response end to loading-clear, not only server time;
6. prune detached observers on every native page remount.

Compression helps transfer bytes; it does not reduce server compute, Python object retention, JSON creation, or React/DataTable mount cost.

A cached Dash component tree still has to be JSON-serialized and sent on a warm callback response. A near-zero `cache.rendered()` build time is therefore not proof of a healthy request; keep the response-byte and browser post-response measurements.

### If it is connector exhaustion

Reinstate an explicit whole-refresh deadline as well as per-call limits, and configure real native I/O timeouts. Fix 12's product isolation should remain, but an unlimited cumulative refresh plus uncancellable calls can make total refresh time unbounded. Prove late calls drain the eight-slot gate.

## Files to change

| File | Change |
|---|---|
| `app.py` | configure logging before remaining Cube imports |
| `gunicorn.conf.py` | access/error output, request correlation, lifecycle hooks, `faulthandler` |
| `cube/app/s03_logging.py` | allowlisted network/operator fields |
| `cube/app/s05_progress.py` | safe process fields in progress payload |
| `cube/app/s07_factory.py` | install diagnostics; health/live/readiness fields |
| `cube/app/s09_network.py` | new request/process tracker, spans, heartbeat |
| `cube/pages/risk/s02_state.py` | lock-wait/cache-byte/epoch diagnostics |
| `cube/pages/risk/s07_explorer.py` | Risk callback phase spans |
| `cube/pages/risk/s12_promotecallbacks.py` | full exception visibility, phase spans, reliable reset |
| `cube/pages/risk/s14_workspacecallbacks.py` | assert Aggregate P&L active-view gate |
| `cube/domain/s11_tenorreduction.py` | provider/batch/concat timings and peak-memory evidence |
| `cube/services/s06_refresh.py` | connector-gate and refresh-stage diagnostics |
| `cube/services/s08_jtd.py` | safe size/count/timing diagnostics |
| `assets/s11_tables.js` | remove detached grid observers |
| `assets/s12_refresh.js` | ordinary-callback health/client diagnostic ring |
| `assets/s13_risk.js` | failed/restarted request recovery for Recalculate |
| `tests/s49_network.py` | fast instrumentation/privacy/error contracts |
| `tools/s03_benchmark.py` | promotion/reduced/RSS/response/concurrency phases |
| `tools/s04_network_probe.py` | external health/progress JSONL probe |

## Verification commands

Run fast checks first:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest `
  tests\s12_startup.py `
  tests\s19_riskfilters.py `
  tests\s32_observability.py `
  tests\s45_failurevisibility.py `
  tests\s46_applogs.py `
  tests\s49_network.py `
  -q -p no:cacheprovider

& '.\.venv\Scripts\python.exe' tools\s03_benchmark.py --enforce

& '.\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider

git diff --check
```

Then run the Linux Gunicorn contention test, subprocess memory soak, browser test, and one live diagnostic reproduction. A unit suite alone is not sign-off for this incident.

## Acceptance criteria

The diagnostic patch is complete only when:

- every Dash POST has a request ID visible in browser Developer Tools/automation, the application log, and the Gunicorn access log;
- every heavy Risk operation has start plus finish/error events;
- boot ID and PID prove whether a process restarted;
- current/peak RSS, active requests, oldest request, and cache/gate counters appear in durable heartbeats;
- successful `/progressz` polling does not flood logs;
- logs contain no request bodies, credentials, filters, identities, or financial values;
- one test distinguishes a 500 from a stalled thread pool from a worker restart;
- the exact rapid measure/Recalculate/navigation browser sequence is automated;
- response bytes and post-response browser time are measured;
- Recalculate cannot remain permanently disabled after a confirmed failure;
- relevant existing tests and the full suite still pass.

The incident itself is fixed only when the reproduction either no longer fails under the agreed production-scale load or fails in a bounded, visible, recoverable way, with RSS/cache/thread counts plateauing.

## Rollout and rollback

### Rollout

1. publish the diagnostics-only commit;
2. authenticate runtime-log access and record the deployed Git SHA;
3. reproduce once and classify from the matrix;
4. implement the smallest proven permanent fix in a separate commit;
5. run HTTP, real-Gunicorn, browser, soak, fault, and existing regressions;
6. leave request IDs, lifecycle logs, and error reset in place permanently;
7. reduce heartbeat frequency after stability is established.

### Rollback

The diagnostic layer is state-free. To roll it back:

1. remove `cube/app/s09_network.py` registration and its health fields;
2. remove Gunicorn access/lifecycle hooks if log volume is unacceptable;
3. remove browser diagnostic storage/listeners;
4. retain any confirmed exception fix and reliable Recalculate reset;
5. do not roll back or migrate financial snapshots, history, mappings, promotion rows, or reduced-tenor data.

## References

- [Gunicorn settings: access/error logs, format fields, threads, timeouts, and hooks](https://docs.gunicorn.org/en/stable/settings.html)
- [Flask application request lifecycle](https://flask.palletsprojects.com/en/stable/lifecycle/)
- [Flask request context and teardown behavior](https://flask.palletsprojects.com/en/stable/reqcontext/)
- [Dash advanced callback running/error behavior](https://dash.plotly.com/advanced-callbacks)
