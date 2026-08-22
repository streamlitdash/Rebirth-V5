# Rebirth V4 codebase guide

This is the single practical guide to the current application: what owns each
behavior, how data crosses the financial boundary, why cold start is quick, how
history works, and how to test and release it. Start with the short
[README](README.md) when you only need to run the app.

## 1. Authority and safety

Current source and tests are authoritative for V4 behavior. The
[Rebirth V3 archive](docs/rebirth-v3/README.md) is deliberately retained as the
historical design record, not as the current file map. When inherited V3
documents disagree, the
[V3.2 correction](docs/rebirth-v3/v3.2/REVISION_V3_2.md) wins for plots,
playback, Risk Explorer navigation, and preservation decisions.

All checked-in financial data is deterministic fake data. Reporting identities
contain `FAKE_REPLACE_ME`; this warning is part of the fixture contract. V4 is a
real application architecture around fake sources, not a production data feed.

Two rules explain most implementation choices:

1. Financial inputs fail closed: malformed schemas, ambiguous joins, duplicate
   identities, invalid dates, missing governance, and incomplete archives are
   rejected before publication or sending.
2. The running UI fails soft: a failed refresh never replaces the last good
   immutable snapshot, warnings are visible, and an unaffected page remains
   usable.

## 2. Semantic tree and ownership

```text
Rebirth-V4/
├── app.py                    composition root and local/WSGI entry
├── publish.py                validated minimal Plotly Cloud publisher
├── gunicorn.conf.py          one-worker, threaded runtime settings
├── plotly-cloud.toml         Plotly application identity
├── rebirth/
│   ├── adapters/             source-specific connector normalization
│   ├── app/                  factory, routing, settings, startup, logging
│   ├── domain/               pure financial and governance rules
│   ├── history/              archive contracts, Parquet I/O, DuckDB queries
│   ├── pages/
│   │   ├── risk/             Risk-only layout, callbacks, tables, pivot, promo
│   │   ├── data/             Risk/Market history selection and playback
│   │   ├── stock/            Stock Current and History workspaces
│   │   ├── pnl/              P&L Current, validation, send, and History
│   │   └── static_data/      approved fixture-file viewer
│   ├── services/             refresh, snapshots, adjustments, saved views
│   └── ui/                   genuinely reusable controls and presentation
├── assets/                   shared shell and page-scoped CSS/JavaScript
├── data/
│   ├── histo/YYYY-MM-DD/     immutable daily Parquet archive leaves
│   └── *.csv                 fake spot sources and governance fixtures
├── jobs/                     Jupyter exploration and scheduler notebooks
├── tools/                    fixtures, manual, archive job, benchmark
├── tests/                    contract, page, performance, and release tests
└── docs/rebirth-v3/          preserved design/version history
```

The dependency direction is intentionally simple:

- `domain` contains calculations and validation and does not depend on Dash.
- `adapters` translate one external source into a domain-owned exact schema.
- `services` orchestrate validated sources and publish immutable snapshots.
- `history` owns persistent archive and query behavior, not page layout.
- each package under `rebirth/pages` owns its controls, callbacks, tables, and
  page-only state; a Stock change should not alter P&L or Risk callbacks.
- `ui` is reserved for controls or formatting genuinely shared by pages.
- `app` composes these boundaries, registers native routes, and owns process
  lifecycle behavior. Business calculations do not belong there.

`app.py` is the only normal composition root. It injects the refresh manager,
Stock source, Portfolio source, history repositories, adjustment repository,
saved-view storage, P&L senders, and runtime settings. A page module should not
import the composition root or silently construct a production connector.

## 3. Composition, first paint, and fail-soft state

Importing or creating the app builds the Dash shell and lazy service objects.
It does not call a connector or read an annual history frame. Native Dash Pages
mount only the active route, which prevents hidden page callback trees from
doing work.

On a cold process:

1. Flask/Dash becomes reachable and returns the navigation and loading shell.
2. A cold financial shell requests the idempotent `/startz` boundary after
   first paint; Risk and P&L also schedule the same process-owned start after a
   0.5-second delay.
3. one `StartupCoordinator` owns revision 1 for that process. Multiple browsers
   follow the same worker and cannot create duplicate writers.
4. `/progressz` reports the live server-side stage. `/healthz` reports
   `starting`, `ok`, or `degraded` with revision and last-attempt metadata.
5. only a completely validated refresh is atomically committed. Readers then
   switch to the new immutable revision.

The startup watchdog defaults to 2,400 seconds and is configured with
`CUBE_STARTUP_TIMEOUT_SECONDS`. It reports a stalled connector but does not try
to kill Python code or launch a second writer. Connector I/O timeouts belong in
the connector itself. A genuine startup failure publishes no partial snapshot
and exposes Retry.

After revision 1, refresh calculation runs outside the short-held committed
state lock. Users continue reading the previous snapshot until the replacement
transaction succeeds. If it fails, the previous snapshot remains active and
the failure is reported once in the page status/log. Up to ten committed source
warnings appear in the collapsible global warning summary; further warnings
remain in the server log.

Gunicorn deliberately uses one worker with several threads. The snapshot,
startup coordinator, saved query state, and progress state are process-local;
multiple independent workers would otherwise disagree about the active
revision. Increase `GUNICORN_THREADS` for concurrent requests, not the worker
count, unless state is first moved to an external coordinator.

## 4. Strict financial boundaries

The strict boundary is narrow on purpose.

### Product and market contracts

`ProductSpec` defines every supported source type, Risk Type/Greek, required
tenor axes, and their order columns. Adapters must return exactly the columns
required by that source. Risk and dRisk are connector-owned values; the common
domain code owns date policy, Market merge, P&L calculation, reporting mapping,
thresholds, and release validation.

Open and Current Market legs are validated independently, then joined on their
canonical quote key with explicit cardinality. Missing quotes stay missing and
receive an explicit availability/status result; they are not silently changed
to zero. Tenor order must agree with the ProductSpec catalogue. Product is a
table/reporting dimension, never an invented plot axis.

### Governance and mapping

The Portfolio registry is one row per Portfolio. Its governed fields are
Product, Activity, SignoffGroup, Category, and Sub Category. Merge cardinality
is checked so Portfolio enrichment cannot multiply financial rows. Unmapped
positions are retained as explicit `Unmapped` records where the consuming
contract allows them; they never borrow a random mapping.

Reported Underlying is attached through its own exact governed mapping.
Thresholds are unique by Risk Type and Risk Greek, numeric, finite, and
positive. Baseline promotion is calculated only after P&L, Portfolio mapping,
Reported Underlying, and thresholds are all valid.

### Snapshot, browser, and send boundaries

The refresh manager stages readiness, Risk, Market, P&L, mapping, promotion,
search indexes, and release views before one commit. A failed stage cannot
partially mutate the active revision.

Authoritative Risk and P&L frames remain server-side. Browser stores carry
revision tokens, open paths, filter selections, and small presentation state.
The explicit exception is the bounded Data-page history bundle needed for
client-side playback; it has hard row/cell limits and is created only for an
exact requested identity.

P&L send actions reapply the Concerto mapping, Portfolio authority, adjustment
schema, selected scope, and exact output columns at click time. Derived fields
cannot be trusted from an edited browser record. No real sender should be
enabled until its authentication, authorization, audit, idempotency, and error
handling have been reviewed.

## 5. The five native pages

### Risk — `/`

Risk uses one reporting-filter bar and two distinct tab layers.

The top workspace has exactly four tabs, in this order:

1. **Aggregate P&L** — mapped P&L context for the active page scope.
2. **Quick Risk** — bounded exact position/reporting-identity inspection.
3. **Quick Market** — bounded exact raw quote inspection.
4. **Top Promotions** — a flat ranked table, never a hierarchy. It consumes the
   active promotion generation and does not recalculate it.

The Risk Explorer below it has exactly three workspaces:

- **Cross** is an immutable built-in hierarchy for the established risk view.
- **SplitVA** is an immutable built-in pivot with Activity across columns.
- **Custom** edits presentation rules—rows, columns, measures, sort, totals,
  density, zero handling, and bounded paging. Users can create, clone, save,
  rename, select, and delete named views. Saving creates a dropdown option, not
  another browser tab, and never stores financial rows.

Risk Type and IR-family tabs remain product-family controls inside these
workspaces. Cross and SplitVA cannot be overwritten by Custom.

The immutable default Filter View is **Default - Activities 1-3**. It selects
the exact canonical Activity 1, Activity 2, and Activity 3 values and leaves
the other governed dimensions unrestricted. If a required activity is absent,
the page warns rather than widening the default silently.

The committed baseline promotion calculation also uses Activities 1-3, but
that scope controls contribution, not row retention. It aggregates mapped rows
at Risk Type + Risk Greek + Reported Underlying, classifies Risk/dRisk/P&L
threshold breaches, and joins the result back to all rows at that identity.
An identity found only outside the baseline activities remains present with a
neutral classification.

Ordinary filter, tab, split, pivot, and chart changes do **not** recompute
promotion. **Recalculate current view** explicitly creates one revision-bound,
session-owned generation from the current Risk Type, IR family, splits,
filters, and include/exclude mode. Later filter changes mark that generation as
stale. **Reset to baseline** returns to the pipeline-owned classification.
Top Promotions always reads whichever generation is active.

### Data — `/data`

Data owns Risk and Market history. It can receive an exact Quick Risk/Quick
Market handoff, but it does not require one. Users can directly select the Risk
or Market tab, Risk Type, Risk Greek, and Underlying from the archive catalogue.
Risk supports Reported Underlying or raw Underlying identity; Market is always
raw quote identity. A handoff locks the identity until **Unlock selection** is
chosen.

Metrics are Risk/dRisk/P&L for Risk and Open/Current/Move for Market. Periods are
WTD, MTD, YTD, 1Y, 5Y, All, and Custom. The resolver chooses observed archive
dates inside the requested calendar window; it never fabricates missing days.

ProductSpec dimensionality determines the projections:

- zero tenor axes: one timeline;
- one tenor axis: Tenor × Date, one selected-tenor history, or Date A/B/Delta;
- two tenor axes: one selected-date surface, a fixed-axis history for either
  tenor, or Date A/B/Delta surfaces.

After one bounded query, the play/pause button, date slider, date pill, chart,
and selected-date table update client-side. Playback is isolated from Risk
filters, promotion, Stock, P&L, and other charts. Missing cells remain null;
canonical tenor order and plot bounds remain stable for the bundle. A separate
raw-period table preserves the exact selected rows.

### Stock — `/stock`

Stock has page-owned **Current** and **History** workspaces.

Current loads two explicitly selected GetStock dates and performs a full outer
comparison at the exact Stock identity:
CRDS + CPTY + Portfolio + Instrument + Currency. It retains Added, Removed,
Changed, and Unchanged rows, maps Portfolio once, exposes exact source rows, and
builds the Activity → Promotion Bucket → temporary Group → CPTY → CRDS view.
Stock promotion is a view-local absolute current Market Value threshold; it is
not persisted into history.

Mounting Current performs no history read. History opens an archive-backed
search over the same exact identity, returns at most 50 selector choices, and
queries rows only after **Load history**. Its periods are WTD, MTD, YTD, 1Y,
All, and Custom, clamped to actual available dates. Quantity and Market Value
are chartable and the exact dated rows remain visible.

### P&L — `/pnl`

P&L also has page-owned **Current** and **History** workspaces governed by one
page filter/saved-view bar.

Current retains mapped Aggregate P&L; editable SOG and Portfolio disclosures;
new-row, adjustment-save, scoped-send, and Send All actions; and Validate P&L.
The editor patches changed cells while derived SignoffGroup and Concerto values
remain governed. Validate P&L compares an official archived Predict projection
with Colossus at the supported hierarchy and reports mapped, Predict-only, and
Colossus-only results rather than forcing a match.

Mounting Current performs no P&L-history query. Opening History lazily creates a
DuckDB view from Risk and Colossus only; Market and Stock Parquet are not scanned
for this workspace. The expandable hierarchy is SignoffGroup → Risk Type → Risk
Greek → Underlying → Product → Portfolio, with Daily Predict and expandable
MTD/YTD Colossus/Predict values. A selected cell drives a WTD, MTD, YTD, All, or
custom daily series and a Both/Colossus/Predict selector.

The separately labelled **Raw historical rows** disclosure stays closed and
performs no query until opened. It then returns at most 500 rows with the full
identity columns:
Market Date, P&L Type, Activity, SignoffGroup, Category, Sub Category, Risk Type,
Risk Greek, Underlying, Product, Portfolio, Mapping Status, and P&L. The query
also calculates count and P&L total over the complete selected scope so the UI
can state whether the bounded table reconciles to the chart.

### Statics — `/static-data`

Statics is a read-only, approved-file catalogue for the fake spot CSVs and
governance mappings. It loads only the selected file and provides native sort,
filter, paging, and row/column counts. It is an inspection aid, not a bypass
around connector or governance validation.

## 6. Archive layout, schema, and row counts

The checked-in demonstration archive contains exactly 262 weekday leaves from
2025-08-21 through 2026-08-21. Each leaf is self-contained:

```text
data/histo/YYYY-MM-DD/
├── risk.parquet
├── colossus.parquet
├── market.parquet
├── stock.parquet
└── _SUCCESS
```

Per-day contracts are:

| File | Rows/day | Grain and exact columns |
|---|---:|---|
| `risk.parquet` | 10,000 | One released dashboard position/tenor row. Exact 44-column schema is listed below. |
| `colossus.parquet` | 5,000 | Portfolio + Underlying + Risk Type + Risk Greek; metric PL. |
| `market.parquet` | 5,000 | Source Type + Risk Type + Risk Greek + Underlying + Tenor Swap + Tenor Option; order/date/Open/Current/Move/status fields. |
| `stock.parquet` | 5,000 | CRDS + CPTY + Portfolio + Instrument + Currency; Quantity and Market Value. |

That is 25,000 source rows per leaf and 6,550,000 source rows across the year.
Parquet uses Zstandard compression, dictionary encoding, statistics, and
bounded row groups.

The exact Risk schema is:

```text
Source Type, Risk Type, Risk Greek, Split, Product, Activity,
Display Bucket, Group, Reported Underlying, Underlying,
Tenor Swap, Tenor Option, Tenor Swap Order, Tenor Option Order,
Portfolio, SignoffGroup, Category, Sub Category, Portfolio Mapped,
Promotion Reason, Promotion Score,
Risk Threshold, dRisk Threshold, PL Threshold,
Risk, dRisk, Open, Current, PL, Move,
Market Available, Market Data Status,
Risk SP01, dRisk SP01, Risk PSP01, dRisk PSP01,
Risk PM01, dRisk PM01, Risk PM01P, dRisk PM01P,
Risk Theta, dRisk Theta, Risk JTD, dRisk JTD
```

The exact Market schema is:

```text
Source Type, Risk Type, Risk Greek, Underlying,
Tenor Swap, Tenor Option, Tenor Swap Order, Tenor Option Order,
Market Date, Open, Current, Move, Market Status, Market Data Status
```

`_SUCCESS` is the commit marker. It records schema version 4, official market
date/status, revision, refresh time, source Risk dates, every exact column list,
row counts, Stock date, fixture identity, and SHA-256 for all four Parquet
files. A completed leaf must contain exactly the five expected artifacts. The
publisher performs full digest validation; lazy query paths validate completion
metadata, schema, row counts, and Parquet metadata before opening virtual views.

Daily publication uses a pending directory, fsync, validation, and atomic
rename. A completed official date is immutable and an idempotent scheduler run
does not overwrite it. CSV archive versions remain readable for migration, but
the checked-in V4 fixture and publish gate require schema-v4 Parquet.

## 7. DuckDB and Jupyter

DuckDB is an embedded query engine here, not a server. No service, port, login,
or persistent database file is required. `open_history_database()` returns a
disposable in-memory connection whose virtual views read the authoritative
Parquet files:

- `archive_days`
- `risk_history`
- `market_history`
- `colossus_history`
- `stock_history`

The views add manifest-owned Snapshot Date, Revision, and Risk Date metadata
without copying the annual dataset into a new governed store. Always filter and
project only the columns needed for ad-hoc work.

Open [jobs/explore_history.ipynb](jobs/explore_history.ipynb) and run it top to
bottom for a working summary and Risk query. It imports
`rebirth.history.open_history_database` and closes with the notebook process.

The scheduled [official archive notebook](jobs/archive_official_risk.ipynb)
calls `tools.archive_snapshot.run_from_env`. Configure:

| Setting | Purpose |
|---|---|
| `RISK_CUBE_PROJECT_ROOT` | Repository root when the scheduler runs elsewhere. |
| `PL_HISTORICAL_PATH` | Durable archive root; relative values resolve against the repository. |
| `COLOSSUS_LOADER` | Callable reference in `module:function` form. |

Run it only after the relevant market is official. The job refreshes through
the same manager, requires a fully valid official snapshot, and then invokes
the atomic archive writer. Use durable storage if the Jupyter environment is
ephemeral.

## 8. Lazy reads, cache ownership, and Clear Cache

V4 caches only reconstructable or explicitly user-authored state:

- the prepared Risk display frame is cached once per committed revision;
- fake connector CSV parsing is keyed by file revision;
- the Data identity catalogue and DuckDB connection are keyed by the immutable
  archive generation;
- Stock reuses one Stock-only DuckDB connection while the completed-day tuple
  is unchanged;
- P&L reuses one Risk+Colossus connection and small filtered statistics while
  the completed-day tuple is unchanged;
- saved filter views, Custom pivot definitions, and P&L adjustments are
  user-authored files with validated paths and atomic replacement.

Lazy sequence by page:

- app construction: zero connector calls and zero archive reads;
- Data mount: archive-free layout first, then a small direct-selector catalogue;
  exact rows only after a request;
- Stock Current mount: zero archive reads; Stock catalogue on History only;
- P&L Current mount: zero annual-history reads; hierarchy on History only;
- playback: no server query for each slider tick after the bounded bundle loads.

Risk/Market Data payloads are capped at 10,000 exact raw rows and 16,000
canonical chart cells. P&L caps visible hierarchy nodes at 5,000, open parents
at 128, daily series rows at 524, and raw display rows at 500. Stock catalogue
results default to 50. These are truthfulness and browser-payload limits, not
silent truncation: the UI asks for a narrower scope or reports shown versus
complete counts.

**Clear Cache** is a reset generation, not a filesystem delete. It invalidates
in-process connector/query caches, prevents an older in-flight generation from
committing, and refreshes the financial snapshot. History repositories close
their disposable DuckDB state and rebuild it on demand. Immutable Parquet,
saved views, Custom definitions, and governed adjustment files are not erased.

## 9. Timing logs and budgets

Runtime timings use structured logging, not ad-hoc prints, so local Dash,
Gunicorn, and Plotly capture the same records. Set `CUBE_LOG_LEVEL` to a normal
Python logging level; `INFO` is the default. Timing records include event,
duration, status, and safe counts such as rows/dates/revision. Financial
identities and values are deliberately excluded. An over-budget event warns
once per event/revision to avoid log storms.

Built-in runtime budgets are 1,000 ms for app construction, 2,000 ms for lazy
Risk/Market archive operations, 750 ms for Stock catalogue/row SQL, and 3,000 ms
for P&L open/hierarchy/series/raw SQL.

`tools/benchmark.py --enforce` applies the acceptance budgets below. The final
V4 evidence shown here was captured against the complete checked-in fixture;
timings remain hardware-sensitive, so retain the raw JSON when comparing later
changes.

| Operation | Budget | Final V4 evidence |
|---|---:|---:|
| Fresh-process import/app build, with zero data/network I/O | 2,000 ms | 1,292 ms |
| Spot refresh | 2,000 ms | 1,058 ms |
| Prepare 100,000 Risk rows / 500 Portfolios | 2,500 ms | 1,346 ms |
| Default Activities 1-3 filter at that scale | 500 ms | 29 ms |
| Cross render at that scale | 1,500 ms | 59 ms |
| Custom pivot at that scale | 1,000 ms | 535 ms |
| First Risk history query | 2,500 ms | 2,207 ms |
| First Market history query | 2,000 ms | 425 ms |
| First Stock history query | 2,500 ms | 812 ms |
| First P&L hierarchy query | 3,500 ms | 2,068 ms |

The benchmark is deliberately read-only and uses exact checked-in identities.
Its fresh child process audits data-file and socket access during import. It
does not publish, rewrite fixtures, or warm the app before measuring the first
history paths.

## 10. Testing and fixture maintenance

Install `requirements-dev.txt`, then run the complete gate:

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python tools/fixtures.py --check
python tools/benchmark.py --enforce
```

The tests cover pure calculations, exact connector schemas, source call counts,
merge cardinality, refresh transactions, last-good reads, startup races,
prefix-aware endpoints, page ownership, saved views, promotion generations,
pivot limits, Stock comparison/history, P&L validation/send/history, archive
atomicity and corruption, playback payloads, observability, and minimal publish
staging.

`tools/fixtures.py --check` deterministically materializes expected leaves in
temporary storage and compares them to all checked-in files. It is slow by
design because it verifies the entire year. `tools/fixtures.py --probe-size`
materializes one representative temporary day. Running `tools/fixtures.py`
without either option rewrites the fake spot data and all 262 archive leaves;
do that only for an intentional fixture-contract change and review row counts,
schemas, hashes, and Git diff afterward.

For a fast development loop, select behavior rather than coupling the guide to
test filenames:

```powershell
python -m pytest -q -k "startup or history or stock or pnl or publish"
```

Finish with the complete gate before release.

## 11. Replacing fake connectors

Production replacement belongs at the connector boundary, not in page
callbacks or by editing fake CSV values.

1. Inventory the public loaders in `rebirth.services.sources` and the
   source-specific builders under `rebirth.adapters`.
2. Implement one dated real adapter at a time while preserving its documented
   function signature, exact output columns, ProductSpec axes, and one-call
   semantics. Source-specific renaming belongs inside that adapter.
3. Supply real Portfolio, threshold, Reported Underlying, Risk readiness,
   Risk/Market, Cross Gamma/new-position, Stock, and Colossus boundaries as
   applicable. Keep the refresh manager and domain calculations unchanged.
4. Replace the P&L send functions with reviewed destinations. Do not enable
   sending merely because a real read connector is available.
5. Put credentials in the deployment secret store or environment. Never place
   them in source, fixture files, notebooks, logs, saved views, or browser
   stores.
6. Add contract fixtures for empty results, missing quotes, duplicate keys,
   stale dates, partial service failures, and retry/idempotency. Run the full
   test and benchmark gate with production-sized sanitized samples.
7. Remove the `FAKE_REPLACE_ME` checks only from a boundary that has actually
   become real. Never relabel synthetic values as production.

The recovered private connector examples remain comments beside several fake
fallbacks for migration context. Treat them as unreviewed reference material:
dependencies, credentials, timeouts, permissions, and schemas must be audited
before any block is enabled.

## 12. Runtime settings

| Setting | Default | Purpose |
|---|---|---|
| `HOST` | `127.0.0.1` | Local bind address. |
| `PORT` | `8050` | Dash port. |
| `DASH_DEBUG` | false | Dash debug mode; reloader stays disabled. |
| `DASH_REQUESTS_PATHNAME_PREFIX` | `/` | Public asset/callback prefix. |
| `DASH_ROUTES_PATHNAME_PREFIX` | `/` | Server route prefix. |
| `JUPYTERHUB_SERVICE_PREFIX` | unset | Derives the JupyterHub proxy/service path. |
| `DASH_JUPYTERHUB_MODE` | `proxy` | `proxy` or `service` prefix behavior. |
| `CUBE_LOG_LEVEL` | `INFO` | Runtime and performance log level. |
| `CUBE_STARTUP_TIMEOUT_SECONDS` | `2400` | Non-destructive startup watchdog. |
| `PL_HISTORICAL_PATH` | `data/histo` | Parquet archive root. |
| `PL_ADJUSTMENT_PATH` | `adjustments` | Governed local adjustment storage. |
| `SAVED_FILTER_VIEWS_PATH` | `data/saved_views` | Shared filter-view catalogue. |
| `CONCERTO_MAPPING_PATH` | checked-in fake mapping | P&L Risk/Greek mapping. |
| `GUNICORN_THREADS` | `4` | Request concurrency in the single worker. |
| `GUNICORN_TIMEOUT_SECONDS` | `300` | Gunicorn request timeout. |

Relative data paths resolve against the repository/application root rather than
the caller's working directory.

## 13. Release process

The intended private GitHub home is
[https://github.com/streamlitdash/Rebirth-V4](https://github.com/streamlitdash/Rebirth-V4).
Do not describe it as published until the remote exists and the target branch
has been pushed.

For each release:

1. confirm the branch contains only intended V4 changes and no credentials,
   private data, local adjustments, scratch databases, or temporary leaves;
2. run the full test, lint, fixture, and enforced benchmark gate;
3. run `python app.py`, exercise all five routes, test a genuinely cold
   process, Clear Cache, one direct Data query/playback, Stock History, P&L
   History/raw reconciliation, and a failed-refresh last-good scenario;
4. review `CUBE_LOG_LEVEL=INFO` timing output and investigate every new budget
   warning rather than raising the budget reflexively;
5. push the reviewed branch/tag to the intended private repository;
6. authenticate the official Plotly CLI and run `python publish.py`;
7. verify Plotly build/runtime logs and the prefix-correct `/healthz`,
   `/progressz`, and idempotent `/startz` endpoints in the deployed environment;
8. record commit, fixture version/date range, benchmark evidence, and deployment
   result in the release note. Roll back by publishing the last reviewed commit,
   not by editing files inside a running container.

The publisher refuses a partial or corrupt annual fixture. It stages only the
conventional runtime files plus `rebirth`, `assets`, and `data`, validates the
copy, and re-encodes only staged Parquet to fit cloud transport. Tests, tools,
notebooks, design history, local output, and compatibility material are not in
the runtime bundle. Plotly's configured application name is `rebirth-v4`. Its
private deployment is
[https://6e5bc823-783b-44cb-b4e4-c4e5be489df7.plotly.app](https://6e5bc823-783b-44cb-b4e4-c4e5be489df7.plotly.app).

## 14. Rules for future changes

- Put page-only behavior in that page package. Promote code to `ui`, `domain`,
  `services`, or `history` only when two real consumers share the same contract.
- Add a reporting field once in the authoritative schema registry and let
  filters, mapping, exports, and fixtures derive from it.
- Add a product through ProductSpec and an adapter; do not branch on product
  labels throughout callbacks.
- Keep Cross and SplitVA immutable. Extend Custom through its versioned
  presentation schema without storing financial data.
- Do not add automatic promotion recomputation to ordinary UI callbacks.
- Do not preload archive frames at import, app construction, or Current-page
  mount. Add a bounded query and measure its first interaction.
- Keep archive leaves flat, dated, immutable, manifest-validated, and
  independently queryable. Do not add a second persisted history truth merely
  to speed one screen.
- Preserve exact raw rows beside aggregations and provide reconciliation totals
  wherever a bounded table cannot show the entire selected scope.
- Add focused contract tests first, then run the full gate and benchmark before
  release.
