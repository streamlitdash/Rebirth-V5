# Rebirth V4

Rebirth V4 is the clean, page-owned rebuild of the Cube risk application. It
keeps the financial behavior and content inherited from V1, applies the V3.2
plot and playback decisions, and makes cold start, history, promotion, and page
state explicit. The maintained runtime starts at `app.py`; application code
lives under `rebirth/`.

> **Demonstration data only.** Every checked-in connector row and every dated
> Parquet leaf is synthetic and visibly marked `FAKE_REPLACE_ME`. Do not use
> the fixtures, thresholds, mappings, P&L send functions, or deployment as a
> production financial source. Replace the connector boundaries and complete
> your own controls review first.

The intended private repository is
[streamlitdash/Rebirth-V4](https://github.com/streamlitdash/Rebirth-V4). See the
[codebase guide](CODEBASE_GUIDE.md) for ownership, data contracts, history,
operations, and release instructions. The preserved
[V3 design record](docs/rebirth-v3/README.md) explains inherited decisions;
V3.2 takes precedence where earlier V3 documents conflict.

## Quick start

Python 3.12 is recommended. From PowerShell in the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe app.py
```

Open `http://127.0.0.1:8050/`. Optional launch overrides are `--host`,
`--port`, and `--debug`; equivalent environment variables are `HOST`, `PORT`,
and `DASH_DEBUG`.

The shell is intentionally available before the first financial refresh. Risk
or P&L schedules one process-owned background load after first paint. The Data,
Stock Current, and P&L Current workspaces do not load annual history merely by
being mounted.

## Five pages

| Route | Owner | Purpose |
|---|---|---|
| `/` | Risk | Aggregate P&L, Quick Risk, Quick Market, flat Top Promotions, and the Cross/SplitVA/Custom Risk Explorer. |
| `/data` | Data | Direct Risk or Market archive selection, ProductSpec projections, A/B comparison, exact rows, and isolated playback. |
| `/stock` | Stock | Two-date Stock comparison plus archive-backed exact-identity history. |
| `/pnl` | P&L | Aggregate review, governed editors/send actions, Validate P&L, and Colossus/Predict history. |
| `/static-data` | Statics | Read-only inspection of the approved fake connector CSVs. |

## Validate and benchmark

Run the normal gate before publishing:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe tools/fixtures.py --check
.\.venv\Scripts\python.exe tools/benchmark.py --enforce
```

The benchmark is read-only. It covers a fresh-process import/app build with an
I/O audit, spot refresh, Cross and Custom interactions on a
100,000-row/500-portfolio fixture, and the first Risk, Market, Stock, and P&L
history queries against all 262 checked-in archive dates.

## Jupyter

Install `requirements-dev.txt`, start Jupyter Lab, and open one of:

- [Explore history](jobs/explore_history.ipynb) — opens an in-memory DuckDB
  connection over the Parquet leaves. There is no SQL server or database file.
- [Archive official Risk](jobs/archive_official_risk.ipynb) — the idempotent
  scheduler job for one completed official date.

`RuntimeSettings` also understands JupyterHub proxy and service prefixes. Run
`app.py` from a Jupyter terminal with `JUPYTERHUB_SERVICE_PREFIX` available, or
set the Dash pathname-prefix variables explicitly.

## Publish

Plotly Cloud publishing is an operator action; this repository does not claim a
public Plotly URL. Authenticate the configured Plotly CLI, run the validation
gate, then:

```powershell
.\.venv\Scripts\python.exe publish.py
```

`publish.py` validates the complete archive and stages only `app.py`,
`gunicorn.conf.py`, `requirements.txt`, `rebirth/`, `assets/`, and `data/`.
Cloud-only Parquet recompression occurs in that temporary copy and never
changes the governed source archive. The configured Plotly application name is
`rebirth-v4`.

For production replacement, operational settings, failure behavior, schemas,
and the release checklist, continue with [CODEBASE_GUIDE.md](CODEBASE_GUIDE.md).
