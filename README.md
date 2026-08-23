# Rebirth V4.1

Rebirth V4.1 is the page-owned rebuild of the Cube risk application. It keeps
the financial content carried forward from V1 while making cold start,
historical reads, promotions, saved filters, and refresh ownership explicit.
It is a Dash 4.4 application backed by pandas/NumPy for current snapshots and
PyArrow/DuckDB for lazy Parquet history.

> **Demonstration data only.** The checked-in connectors and 262-day archive
> are deterministic synthetic fixtures marked `FAKE_REPLACE_ME`. The example
> send functions are not production integrations. Replace those boundaries
> and complete the relevant control review before using this application for
> financial decisions.

`app.py` is the only runtime entrypoint. Importing it builds the shell and
service boundaries without loading source data or scanning annual history.
The first page can therefore paint before the initial refresh begins.

## Quick start

From PowerShell in the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:8050/`. The equivalent launch forms are:

```powershell
.\.venv\Scripts\python.exe app.py --host 0.0.0.0 --port 8050
$env:HOST = "0.0.0.0"
$env:PORT = "8050"
.\.venv\Scripts\python.exe app.py
```

`--debug` or `DASH_DEBUG=1` enables Dash debug mode. Production WSGI servers
import `app:server`. `gunicorn.conf.py` deliberately uses one `gthread` worker
because the committed snapshot and refresh progress are process-owned; its
thread and timeout overrides are `GUNICORN_THREADS` and
`GUNICORN_TIMEOUT_SECONDS`.

Runtime dependencies are pinned in `requirements.txt`: Dash 4.4.0, DuckDB
1.5.5, NumPy 2.5.1, pandas 3.0.3, PyArrow 25.0.1, Plotly 6.9.0, tzdata
2026.3, and Gunicorn 23.0.0 on non-Windows hosts. The Dash pin is intentional
because the native P&L editor is lifecycle-tested against its DataTable and
Patch behavior. `requirements-dev.txt` adds Plotly Cloud, pytest, and Ruff.

## Pages and user flow

| Route | Owner | User workflow |
|---|---|---|
| `/` | Risk | Current risk, P&L, search, promotions, and pivot exploration. |
| `/data` | Data | Editable Risk or Market historical selection and playback. |
| `/stock` | Stock | Current mapped stock rows and inline Stock/dStock history. |
| `/pnl` | P&L | Aggregate review, inline history, governed editors, send, and validation. |
| `/static-data` | Statics | Read approved connector files or edit the governed subset. |

### Risk

The top workspace is one open-by-default **Aggregate P&L** disclosure with exactly
four compact tabs in this order:

1. **Aggregate P&L** renders the mapped snapshot by the selected governed
   dimension.
2. **Quick Risk** resolves one committed risk identity, renders its exact
   hierarchy, and can hand it to Data.
3. **Quick Market** resolves one committed quote identity, renders its current
   matrix, and can hand the editable identity to Data for history.
4. **Top Promotions** is a flat Vol Score rank with ten rows per page. Its
   connector-signal selector defaults to Vol Score; the internal promotion
   threshold score is not shown as a table column.

The Data handoff is only a prefill. It never locks Data controls. A strict
Quick handoff performs one initial history request; after that, Risk Type,
Risk Greek, underlying, identity mode, dates, projection, and slice are
normal Data controls again.

The Risk Explorer has only **Cross** and **SplitVA** tabs. Both expose their
Risk Type/Greek families as expandable, chevron-driven financial hierarchies;
Credit also retains its Single/Multi presentation.
The default governed view is Activity, with Activities 1, 2, and 3 as the
baseline scope. The shared filter row is Activity, Signoff Group, Portfolio,
Category, and Sub Category, with explicit include/exclude semantics. Saved
Views is a form: selecting a named view or changing a selector edits a draft;
only **Apply filters** changes Risk outputs, and **Cancel changes** restores the
last committed selection. Stock and P&L use the same small contract while
keeping independent page state. On the first visit to each page, Base is
resolved from that page's authoritative data and committed once automatically;
later draft changes still require Apply. Clear Cache invalidates data caches but
preserves the page's committed view.

Promotions are computed against thresholds at exact Risk Type + Risk Greek
grain. The baseline generation uses Activities 1-3 and is committed with the
refresh revision. **Recalculate promotions** is the explicit action that
creates a new revision-bound promotion generation from the visible scope;
filter and display changes do not continually recompute it. Eligibility still
uses the governed threshold rules, while ranking uses the deterministic
connector-owned **Vol Score**. Reset returns to the baseline generation.

### Data

Data has **Risk History** and **Market History** tabs. Risk uses a reported/raw
underlying dropdown and always plots `Risk`; Market uses its exact raw identity
and always plots the archived `Official` value. There is no redundant metric
selector. The user then chooses Risk Type, Risk Greek, underlying, and a
segmented WTD/MTD/YTD/1Y/5Y/All/Custom period. Custom start/end dates appear
only for Custom.
`Load history` snapshots those controls into one immutable request; changing a
control alone does not scan the archive. Quick handoffs are consumed once, so
the controls remain editable after navigation.

The returned bundle drives ProductSpec-shaped projection and slice controls,
Date A/Date B comparison, a canonical scalar/line/surface plot, and bounded
selected-date details. Two-axis swap/option-over-time projections default the
fixed axis to **Sum**, using a null-preserving sum across its tenors, while each
individual tenor remains selectable. The compact browser-side player supports
static mode, play/pause, live slider dragging, and wheel scrubbing without
another server query. There is no default raw-history table or second raw
payload. Loading status appears immediately while the single history read is
running.

### Stock

Stock first paints an empty shell, then loads the latest connector comparison
asynchronously. Its Saved Views disclosure owns the five governed filters—
Activity, Signoff Group, Portfolio, Category, and Sub Category—which default to
the same Activities 1-3 scope as Risk and affect the pivot only after Apply.
A configurable chevron pivot defaults to Activity → Category (Bucket) → CRDS
→ CPTY, with optional Currency/Product columns and `Stock`/`dStock` values.
The underlying detail stays position-level and preserves portfolio and static
metadata rather than aggregating it.

Clicking a CRDS/CPTY leaf loads its history chart on the same page. The same
selection can be made manually with always-visible WTD/MTD/YTD/1Y/All/Custom
controls; start/end dates appear only for Custom. Period and custom-date
changes update the selected history directly.
History is chart-only: it does not open another route or send a raw history
table to the browser.

### P&L

One authoritative saved-filter row—Activity, Signoff Group, Portfolio,
Category, and Sub Category—governs every P&L section. The page-owned review is
Risk Type → Risk Greek → Underlying and carries **Today**, **MTD**, and **YTD**.
It reads its historical summary when the P&L page is entered, independently of
the Risk-page Aggregate P&L callback. Underlying children are bounded so a
large Greek cannot send thousands of rows to the browser at once. Clicking a
Today/MTD/YTD value at Total, Risk Type, Greek, or Underlying level reveals the
summed inline history for that exact hierarchy scope. The chart uses segmented
WTD/MTD/YTD/1Y/All/Custom controls, shows start/end only for Custom, and has one
Both/Colossus/Predict source dropdown; no raw history table remains.

The lower workflow contains the current Send All, SOG editor, Portfolio editor,
adjustment-save, and Validate P&L sections. Derived fields stay locked. Validate
P&L compares official Predict/Risk results with Colossus. It stays fully lazy
while its disclosure is closed, reuses an unchanged rendered result, and builds
the hierarchy once for a new date/filter state. Chevrons then expand only their
local subtree in the browser without rerunning the comparison. Missing
historical dates remain missing rather than being silently filled with zero.

### Statics

Statics has **Read** and **Write** tabs. Read can inspect all approved
`data/s01_*.csv` through `data/s09_*.csv` files in a bounded filterable table.
Write is intentionally limited to:

- `s06_portfolios.csv`
- `s07_thresholds.csv`
- `s08_concerto.csv`
- `s09_reported.csv`

The editable table provides Add row, editable existing cells, row deletion,
column hiding, Save, and Cancel. Governed connector columns cannot be
permanently deleted because doing so would make the source unreadable. Save
validates the complete schema and domain invariants, writes a temporary file,
publishes it with an atomic replace, and refreshes the Read table immediately.
Cancel reloads the governed file.

## Runtime, status, and failure behavior

All five pages use the persistent shared shell. Clear Cache sits beside the
theme switch. The operational controls are:

- **Refresh Portfolios**, **Refresh Risk** (`Shift+F8`), and **Refresh PL**
  (`Shift+F9`), each with visible running/completion status.
- **Commodity quotes: Loaded/Disabled**. Disabling quotes does not hide
  Commodity Risk.
- **Risk dates: Checker/Today**. The date editor is a draft until Apply;
  Cancel discards it. Checker readiness and inventory are disclosed lazily.
- **Auto P&L: On/Off · 15 min**. This timer is browser-local; it does not create
  a second backend scheduler.
- **Clear Cache**, which advances the reset generation, clears reconstructable
  process caches, and performs one guarded full refresh. It does not delete
  Parquet or governed files.

Applied Commodity, Risk Checker, and date settings mirror the one committed
process snapshot. Auto P&L alone is browser-local scheduling state.

A cold visit to any of the five routes starts or follows one process-owned
background writer after the shell paints. Risk and P&L also schedule that same
idempotent attempt from their page builders; direct Data, Stock, and Statics
visits use the shared shell. Concurrent browsers follow the same attempt. Slow
source work happens outside the reader lock, so every reader sees the previous
immutable revision until the whole replacement is ready. A failed refresh is
rejected transactionally: the UI keeps the last successful snapshot, reports
one bounded warning, and offers retry. A watchdog can report a stalled attempt
but never starts a duplicate writer. This is fail-closed at the financial
boundary without closing or blanking the working application.
`CUBE_STARTUP_TIMEOUT_SECONDS` changes that reporting threshold from its
2,400-second default; it does not kill the connector call or start a replacement.

On Plotly Starter, an inactive container can sleep. The platform wake-up is
outside the Dash process and can make the first request look like a crash even
though the application has no traceback. Once the container is awake, the
fresh app import is kept free of data/archive I/O and is covered by the local
startup budget. Moving to an always-on plan is the only way to eliminate the
hosting sleep itself.

`CUBE_LOG_LEVEL` selects the process log level (default `INFO`). Runtime timing
covers app build, refresh stages, Stock current load, promotion recalculation,
Validate P&L stages, and Data/Stock/P&L history queries. The release benchmark
separately times preparation, filtering, and Cross rendering. Performance logs
use bounded structural fields; they do not log underlying identities or
financial values. Warning deduplication prevents a single incident from
flooding the page.

## Historical data and cache

The authoritative layout is:

```text
data/histo/YYYY-MM-DD/
├── risk.parquet
├── colossus.parquet
├── market.parquet
├── stock.parquet
└── _SUCCESS
```

This checkout contains 262 weekday leaves from 2025-08-21 through 2026-08-21.
Each deterministic day has 10,000 risk rows and 5,000 rows each for Colossus,
Market, and Stock. `_SUCCESS` records schema version 4, date, revision, source
dates, columns, row counts, SHA-256 hashes, and the immutable fixture identifier
`deterministic-rebirth-v4`. V4.1 is the application release; schema version 4
and that fixture identifier intentionally do not change.

Parquet is authoritative. DuckDB is an embedded query engine here, not a
server: no service, credentials, or persistent database file are required.
Data and Stock open their in-memory history connections only after history is
requested. P&L deliberately opens its own summary query when that page is
entered so Today/MTD/YTD are immediately available; its leaf series remains
click-driven. Every owner pushes exact identity, date, and column predicates
into Parquet scans. Connections and distinct catalogues are reused while the
archive-generation fingerprint is unchanged, then discarded after Clear Cache
or an archive change. Query and browser-payload budgets keep results bounded.

The owners are `ArchiveHistoryRepository`/`ArchiveSQLStore` for Data,
`SQLStockHistoryRepository` for Stock, and `SQLPLHistoryRepository` for P&L.
The scheduled archive boundary is idempotent: a completed `_SUCCESS` leaf is
never overwritten, and a partial pending leaf is never published.

## Live source and merge contracts

The checked-in files document the live connector boundaries:

| File | Exact boundary |
|---|---|
| `s01_readiness.csv` | Risk Type, Risk Greek, Age |
| `s02_checker.csv` | Risk Type, Risk Greek, MMMFile, Product |
| `s03_risk.csv` | Source Type, identity/tenors, Portfolio, Group, connector-owned Vol Score, and governed Risk/dRisk measure pairs |
| `s04_open.csv` | Source Type, identity/tenors and tenor order, Open |
| `s05_current.csv` | Source Type, identity/tenors and tenor order, Current |
| `s06_portfolios.csv` | unique Portfolio plus Product, Activity, SignoffGroup, Category, and optional Sub Category |
| `s07_thresholds.csv` | unique Risk Type + Risk Greek with positive P&L, Risk, and dRisk thresholds |
| `s08_concerto.csv` | unique Risk Type + Risk Greek to ConcertoField |
| `s09_reported.csv` | unique Risk Type + Risk Greek + Underlying to Reported Underlying |

The Stock connector returns exactly `CRDS, CPTY, Portfolio, Instrument,
Currency, Quantity, Market Value`. Colossus history returns exactly `Portfolio,
Underlying, Risk Type, Risk Greek, PL`. Connector adapters require exact column
names and order, nonblank text identities, and finite numeric measures; shared
alias guessing is deliberately absent.

The financial invariants are:

- `ProductSpec` is the authority for Source Type, Risk Type/Greek, axes, tenor
  order, market keys, metric formulas, and plot dimensionality.
- Current/Open joins occur at exact quote grain with declared pandas
  cardinality, normally `many_to_one`; duplicates fail rather than multiply
  rows.
- Portfolio config is unique by Portfolio and joins `many_to_one`. Unmapped
  positions are retained as `Portfolio Mapped=False` with `Unmapped` labels.
- Reported Underlying is a unique, non-recursive Risk Type + Risk Greek + raw
  Underlying map. It is applied exactly once after P&L; unmatched rows retain
  the raw underlying.
- Thresholds are unique and positive at Risk Type + Risk Greek grain and must
  cover every release pair used by promotions.
- Concerto mapping is unique at Risk Type + Risk Greek grain. Adjustments are
  keyed by Market Date + Portfolio + ConcertoField.
- Current/prior Stock identities are unique and compare `one_to_one`; portfolio
  metadata then joins `many_to_one`. Static metadata is not aggregated.
- A committed refresh revision is immutable and returned defensively. Row-count
  and merge-cardinality violations reject the candidate before any partial
  state can leak to readers.

## Ordered ownership tree

Within each owned folder, `sNN_` gives a stable reading and ownership sequence;
it is not a strict import dependency order. Files are deliberately small enough
to have one important responsibility, while a page keeps its layout, callbacks,
and page-only helpers together.

```text
rebirth/
├── adapters/
│   ├── s01_common.py          strict frame validation
│   ├── s02_ir.py              IR products
│   ├── s03_fx.py              FX products
│   ├── s04_credit.py          Credit products and measures
│   ├── s05_commodities.py     Commodity products
│   ├── s06_crossgamma.py      Cross-Gamma connector
│   ├── s07_newpositions.py    New-position blotter
│   └── s08_stock.py           Stock connector
├── app/
│   ├── s01_settings.py        paths, host, port, and JupyterHub prefixes
│   ├── s02_contracts.py       structural boundary protocols
│   ├── s03_logging.py         safe logging and timed spans
│   ├── s04_startup.py         one-writer cold-start coordinator
│   ├── s05_progress.py        progress serialization
│   ├── s06_routing.py         native page routing
│   └── s07_factory.py         application composition
├── domain/
│   ├── s01_schema.py          portfolio/reporting registry
│   ├── s02_products.py        ProductSpec catalogue
│   ├── s03_calculations.py    risk and P&L calculations
│   ├── s04_crossgamma.py      Cross-Gamma rules
│   ├── s05_newtrades.py       new-trade rules
│   ├── s06_reporting.py       reported-underlying mapping
│   ├── s07_governance.py      mapping and threshold validation
│   ├── s08_pnl.py             P&L mapping/send/adjustment rules
│   ├── s09_stock.py           Stock comparison and mapping
│   └── s10_search.py          exact Quick identity catalogue
├── history/
│   ├── s01_models.py          Data requests and canonical bundles
│   ├── s02_contracts.py       archive schemas and manifests
│   ├── s03_io.py              atomic archive I/O
│   ├── s04_queries.py         bounded projections and plots
│   ├── s05_store.py           generation-aware DuckDB store
│   ├── s06_repository.py      Data history repository
│   └── s07_sql.py             SQL P&L history repository
├── pages/
│   ├── s01_notfound.py        fallback page
│   ├── data/
│   │   ├── s01_selection.py   editable request/handoff state
│   │   ├── s02_view.py        Data layout and figures
│   │   └── s03_callbacks.py   catalogue, query, chart, and playback callbacks
│   ├── stock/
│   │   ├── s01_data.py        current comparison and filters
│   │   ├── s02_history.py     lazy Stock SQL contract
│   │   ├── s03_view.py        current table and inline history layout
│   │   ├── s04_callbacks.py   asynchronous current/history callbacks
│   │   └── s05_pivot.py       Stock chevron-pivot model
│   ├── pnl/
│   │   ├── s01_common.py      P&L page contracts
│   │   ├── s02_editor.py      editor transformations
│   │   ├── s03_history.py     lazy Colossus/Predict history
│   │   ├── s04_sender.py      current send/editor/validation sections
│   │   ├── s05_sendcallbacks.py send and adjustment callbacks
│   │   ├── s06_validation.py  official comparison rules
│   │   ├── s07_view.py        page and inline-history layout
│   │   ├── s08_aggregate.py   mapped Aggregate P&L callbacks
│   │   ├── s09_drilldown.py   cell selection and inline chart callbacks
│   │   └── s10_summary.py     bounded Today/MTD/YTD hierarchy
│   ├── static_data/
│   │   ├── s01_store.py       approved files, validation, atomic save
│   │   ├── s02_view.py        Read/Write layout
│   │   └── s03_callbacks.py   lazy read and governed write callbacks
│   └── risk/
│       ├── s01_common.py      IDs and shared Risk contracts
│       ├── s02_state.py       committed/browser state envelopes
│       ├── s03_defaults.py    default scopes
│       ├── s04_handoff.py     Quick-to-Data payloads
│       ├── s05_charts.py      Risk figures
│       ├── s06_explorertables.py explorer table builders
│       ├── s07_explorer.py    explorer callbacks
│       ├── s08_quickrisk.py   Quick Risk view
│       ├── s09_quickmarket.py Quick Market view
│       ├── s10_search.py      exact search callbacks
│       ├── s11_promotion.py   immutable promotion model
│       ├── s12_promotecallbacks.py promotion actions
│       ├── s13_workspacetables.py four-tab table builders
│       ├── s14_workspacecallbacks.py four-tab callbacks
│       ├── s15_refresh.py     runtime controls and progress
│       ├── s16_view.py        Risk page composition
│       └── s17_callbacks.py   Risk callback facade
├── services/
│   ├── s01_snapshots.py       immutable snapshot models
│   ├── s02_state.py           atomic state and refresh manager
│   ├── s03_adjustments.py     validated local P&L adjustment CSVs
│   ├── s04_savedviews.py      atomic shared saved-view JSON
│   ├── s05_sources.py         source wiring and fixture connectors
│   └── s06_refresh.py         refresh orchestration
└── ui/
    ├── s01_constants.py       shared field/hierarchy registry
    ├── s02_aggregation.py     shared financial aggregation
    ├── s03_filters.py         saved filter controls
    └── s04_components.py      shell, tables, loaders, and controls
```

The other ordered owners are:

- `assets/s01_shell.css` through `s08_promotions.css`: shell, controls/tables,
  Risk, P&L, responsive rules, visuals, history, and promotion styling.
- `assets/s09_playback.js` through `s14_pnl.js`: Data playback, theme/Plotly,
  table interaction, refresh lifecycle, Risk interaction, and P&L cell
  selection.
- `data/s01_readiness.csv` through `s09_reported.csv`: the connector and
  governance sequence documented above.
- `jobs/s01_archive.ipynb`, `s02_explore.ipynb`: scheduled archive and ad-hoc
  DuckDB exploration.
- `tools/s01_fixtures.py`, `s02_archive.py`, `s03_benchmark.py`: deterministic
  data, official archiving, and regression budgets.
- `tests/s01_schema.py` through `s42_statics.py`: domain, integration, startup,
  publishing, UI, history, observability, architecture, assets, and Statics
  contracts. Tests do not count against the production ownership budget.

The handful of unnumbered names are tool conventions, not stray ownership:
`app.py` is the Dash/WSGI discovery entrypoint; `publish.py` is the human release
command; `gunicorn.conf.py` is Gunicorn's conventional config name;
`requirements*.txt`, `pytest.ini`, `plotly-cloud.toml`, `.gitignore`, and
`.gitattributes` are read by external tools; and `__init__.py` files define
Python packages and their public exports. Dated archive leaves and `_SUCCESS`
also keep their immutable data-contract names. This `README.md` is the
repository's only Markdown document.

## Jupyter and archive jobs

Run `app.py` from a Jupyter terminal exactly as in Quick start.
`RuntimeSettings` detects `JUPYTERHUB_SERVICE_PREFIX`; its default `proxy` mode
derives the request prefix as `<hub-prefix>/proxy/<PORT>/`. Set
`DASH_JUPYTERHUB_MODE=service` for a JupyterHub service, or set
`DASH_REQUESTS_PATHNAME_PREFIX` and `DASH_ROUTES_PATHNAME_PREFIX` explicitly.
All relative data paths resolve from the repository root, not the notebook's
working directory.

- `jobs/s01_archive.ipynb` runs the idempotent official archive job. It finds
  the repository through `RISK_CUBE_PROJECT_ROOT` or parent discovery and uses
  `PL_HISTORICAL_PATH` plus `COLOSSUS_LOADER=module:function` when overridden.
- `jobs/s02_explore.ipynb` calls `open_history_database(...)` and exposes
  `archive_days`, `risk_history`, `market_history`, `colossus_history`, and
  `stock_history` as in-memory DuckDB views.

The application path overrides are `CONCERTO_MAPPING_PATH`,
`PL_ADJUSTMENT_PATH`, `PL_HISTORICAL_PATH`, and
`SAVED_FILTER_VIEWS_PATH`. Defaults are respectively `data/s08_concerto.csv`,
`adjustments/`, `data/histo/`, and `data/saved_views/`.

## Persistence boundary

Local Statics writes are durable filesystem changes. Saved filter views are
small validated JSON files in `data/saved_views/`; P&L adjustments are complete
per-portfolio CSV files under `adjustments/YYYY-MM-DD/`. All three write
boundaries use atomic replacement and reject malformed or stale writes.

Plotly and similar deployments may provide ephemeral or release-local writable
filesystems. A Statics edit, saved view, or adjustment made inside a deployed
container can disappear on restart/redeploy and is not automatically pushed to
Git. Commit approved CSV changes for the next release, and use an explicitly
durable shared store for saved views/adjustments if cross-release persistence
is required. Do not increase Gunicorn workers without first moving refresh
state and these write boundaries to shared infrastructure.

## Test and benchmark gate

Run the complete gate before a release:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe tools/s01_fixtures.py --check
.\.venv\Scripts\python.exe tools/s03_benchmark.py --enforce
```

The benchmark is read-only. It audits a fresh-process import/app build for
unexpected I/O, a spot refresh, prepare/filter/Cross operations on a
100,000-row and 500-portfolio fixture, and the first Risk, Market, Stock, and
P&L queries across all 262 leaves. The enforced local regression budgets are
2.0 s for app build, 2.0 s for spot refresh, 2.5 s for preparation, 0.5 s for
filtering, 1.5 s for Cross, and 2.5/2.0/2.5/3.5 s for the first
Risk/Market/Stock/P&L history queries. Absolute times remain hardware-dependent;
a budget failure exits nonzero so the regression is visible.

`tools/s01_fixtures.py --check` validates the checked-in fixture without
rewriting it. `tools/s02_archive.py` is the CLI form of the official archive
boundary.

## GitHub and Plotly release

This checkout publishes to the private `streamlitdash/Rebirth-V4.1` repository
through the `rebirth-v4-1` remote and updates the existing Rebirth V4.1 Plotly
application. Run the full gate, push the reviewed commit, then publish:

- [GitHub repository](https://github.com/streamlitdash/Rebirth-V4.1)
- [Live Plotly application](https://8d1e8451-d8ed-4e0b-ba89-bdaef442d5a1.plotly.app)

```powershell
.\.venv\Scripts\python.exe publish.py
.\.venv\Scripts\plotly.exe app status --verbose
.\.venv\Scripts\plotly.exe app logs --type build
.\.venv\Scripts\plotly.exe app logs --type runtime
```

`publish.py` validates the exact 262-day archive, stages only `app.py`,
`gunicorn.conf.py`, `requirements.txt`, `rebirth/`, `assets/`, and `data/`, then
recompresses only the staged Parquet copy before publishing. The governed
source archive is never modified. Use `--keep-bundle <directory>` only when you
also intend to publish and retain the staged runtime for inspection; it is not
a dry run. After publish, smoke-test a cold wake, all five routes, both Data
modes, Stock and P&L inline history, promotion recalculation, Statics
validation, dark/light mode, and Clear Cache.
