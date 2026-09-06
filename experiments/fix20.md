# Daily history setup and Promotion Score investigation

This guide explains the current `v4` behavior. It does not change the Risk,
promotion, history, or connector code.

## Part 1 — Where promotion is calculated

The cold-start promotion path is:

```text
per-product Risk/P&L frames
    + Gamma rows
    + XGamma rows
    + New Trades rows
        |
        v
cube/services/s02_state.py::_release_pl_views
        |
        +-- merge Portfolio configuration
        +-- attach Reported Underlying
        +-- apply_baseline_promotions
        +-- apply_pinned_promotions
        +-- build dashboard_frame
        +-- _validate_dashboard_release
        |
        v
cube/ui/s02_aggregation.py::prepare_risk_data
```

### 1. The release coordinator

File:

```text
cube/services/s02_state.py
```

Function:

```python
_release_pl_views(...)
```

This function concatenates all ordinary product P&L frames and the non-empty
XGamma/New Trades overlay frames. It then calls:

```python
enriched = apply_baseline_promotions(enriched, thresholds)
enriched = apply_pinned_promotions(enriched, pinned_promotions)
```

This is the best place to inspect the complete frame immediately before and
after baseline promotion.

### 2. The authoritative baseline calculation

File:

```text
cube/domain/s07_governance.py
```

Functions:

```python
_apply_validated_thresholds(...)
apply_baseline_promotions(...)
```

The aggregation keys are exactly:

```text
Risk Type + Risk Greek + Reported Underlying
```

`Portfolio` and `Split` are not promotion keys. That is what allows ordinary
Risk, developed Gamma, developed XGamma and New Trades to contribute the
metrics they actually own to the same promoted identity. Raw Cross Gamma source
rows contribute connector Risk and dRisk under their XGamma source pair.
Developed `Split = XGAMMA` rows contribute developed Risk under the destination
pair; developed dRisk remains unavailable.

Only Portfolio-mapped rows in Activities 1–3 contribute to the cold-start
baseline calculation. The temporary fixtures also recognize their explicit
legacy aliases (`Macro`, `Credit`, `Hedge`) and temp-prefixed equivalents. The
calculation is:

```python
risk_ratio = abs(total_risk) / risk_threshold
drisk_ratio = abs(total_drisk) / drisk_threshold
pl_ratio = abs(total_pl) / pl_threshold

promotion_score = max(risk_ratio, drisk_ratio, pl_ratio)
```

A ratio greater than or equal to `1.0` adds the corresponding reason:

```text
Big Risk
Big dRisk
Big PL
```

The classification is then joined back onto every matching position row.

### 3. Pinned promotions

File:

```text
cube/domain/s07_governance.py
```

Function:

```python
apply_pinned_promotions(...)
```

This function only prefixes `*` and moves a matched Reported Underlying into
the promoted bucket. It does not calculate or replace `Promotion Score`.

### 4. The two validation boundaries

The new committed dashboard is checked by:

```text
cube/domain/s07_governance.py::_validate_dashboard_release
```

The Risk Explorer then normalizes and checks it again in:

```text
cube/ui/s02_aggregation.py::prepare_risk_data
```

The error:

```text
Column 'promotion score' contains missing, non-numeric, or non-finite values
```

comes from `prepare_risk_data`. That is the final reporter, not necessarily the
place that created the bad value.

## Part 2 — Investigate the two invalid rows

Current `v4` has both of these protections:

```python
# cube/domain/s07_governance.py
result[PROMOTION_SCORE] = result[PROMOTION_SCORE].fillna(0.0)
```

```python
# cube/ui/s02_aggregation.py
frame["promotion score"] = frame["promotion score"].fillna(0.0)
```

Therefore, a genuine pandas null should not reach the failing numeric check.
If the two rows still fail, check these possibilities first:

1. The running server has an older `cube/domain/s07_governance.py`.
2. The running server has an older `cube/ui/s02_aggregation.py`.
3. The server was not fully restarted after copying the files.
4. The value is text such as `"NA"`, `"nan"`, `"None"` or `"inf"`, not a
   genuine null.
5. A local edit replaces `Promotion Score` after baseline promotion.

### Smallest useful temporary print

Put the diagnostic at the input of the function that raised the pictured error.
This preserves the exact value before the UI applies its neutral-null fallback.

In:

```text
cube/ui/s02_aggregation.py
```

Inside `prepare_risk_data`, place the block immediately after the duplicate
column check and before:

```python
if "display bucket" not in frame:
```

Temporarily add:

```python
if "promotion score" in frame:
    raw_score = frame["promotion score"]
    boolean_score = raw_score.map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    numeric_score = pd.to_numeric(raw_score, errors="coerce")
    bad_score = boolean_score | numeric_score.isna()
    bad_score |= numeric_score.notna() & ~np.isfinite(numeric_score)

    if bad_score.any():
        columns = [
            "source type",
            "risk type",
            "risk greek",
            "split",
            "portfolio",
            "underlying",
            "reported underlying",
            "activity",
            "risk",
            "drisk",
            "pl",
            "promotion score",
        ]
        available = [column for column in columns if column in frame]
        debug = frame.loc[bad_score, available].copy()
        debug["raw promotion score"] = raw_score.loc[bad_score].map(repr)
        print("INVALID PROMOTION ROWS")
        print(debug.to_string(index=True))
```

Both `pandas as pd` and `numpy as np` are already imported in this file.

Restart the Python server completely and reproduce the error. This print shows:

- whether the rows are XGamma, New Trades, Gamma or ordinary Risk;
- their raw and reported identities;
- Activity and Portfolio;
- the exact Python representation of `Promotion Score`.

Remove the temporary block after finding the source.

### Quick version and import-path check

First confirm the source files in the launch directory contain both fallbacks:

```bash
grep -n "PROMOTION_SCORE.*fillna(0.0)" cube/domain/s07_governance.py
grep -n 'promotion score.*fillna(0.0)' cube/ui/s02_aggregation.py
```

Then confirm the Python environment imports those exact files rather than a
second checkout or installed copy:

```bash
.venv/bin/python -c "import cube.domain.s07_governance as g; import cube.ui.s02_aggregation as a; print(g.__file__); print(a.__file__)"
```

Both paths must point inside the directory from which this app is launched.
Then stop the current Python process and start it again. A browser refresh alone
does not reload Python modules.

## Part 3 — What is saved every day

The application uses one immutable directory per official Market Date:

```text
<PL_HISTORICAL_PATH>/YYYY-MM-DD/
├── risk.parquet
├── market.parquet
├── colossus.parquet
└── _SUCCESS
```

`stock.parquet` is supported by the archive format but is not written by the
standard production job because the ordinary refresh snapshot does not contain
a Stock frame.

### `risk.parquet`

The source is:

```python
snapshot.dashboard_frame
```

It is the final Portfolio-mapped Risk Explorer snapshot after:

- product Risk/dRisk loading;
- market attachment and P&L;
- Gamma development;
- XGamma and New Trades overlays;
- Portfolio mapping;
- Reported Underlying mapping;
- baseline and pinned promotion.

It retains position-grain fields including Portfolio, raw and reported
Underlying, Risk, dRisk, P&L, tenors and attached market values.

It does not separately save:

- unmapped Portfolio rows;
- raw per-product connector frames;
- `combined_pl`;
- reduced-tenor caches;
- matrices;
- browser filters, expanded rows or other UI state.

### `market.parquet`

This is the complete official MarketBook at raw Underlying and quote-tenor
grain. It includes market-only tenors that have no matching Risk row.

### `colossus.parquet`

This is the separate official P&L source with exactly:

```text
Portfolio
Underlying
Risk Type
Risk Greek
PL
```

The first four columns must be unique, nonblank keys. `PL` must be finite.

### `_SUCCESS`

This is the completion manifest. It records:

- archive schema version;
- Market Date and `OFFICIAL` status;
- committed revision;
- per-product Risk dates;
- columns and row counts;
- SHA-256 digest for every payload.

Do not create or edit `_SUCCESS` manually.

## Part 4 — When the daily job writes

The daily job forces one coherent Risk and P&L refresh. It writes only when:

1. The selected Market Date is the current natural business Market Date.
2. Market Status is exactly `OFFICIAL`.
3. The committed refresh contains no errors.
4. A completed archive does not already exist for that date.

Possible results are:

```text
archived          A new completed date was written.
already_archived  That date already exists and was not overwritten.
skipped           The date/status/error eligibility checks failed.
```

Running `app.py` does not automatically create history. The job must be run or
scheduled separately.

## Part 5 — Minimum live setup

The daily archive needs:

1. Working real Risk connectors.
2. Working Open and Current market connectors.
3. A real market-state function that eventually returns `OFFICIAL`.
4. Working Portfolio, threshold and Reported Underlying sources.
5. XGamma and New Trades loaders if those overlays are enabled.
6. A real Colossus P&L loader.
7. A persistent writable history directory.
8. The same connector credentials and network access in the scheduler process.
9. The repository Python environment with pandas, PyArrow and DuckDB installed.

The checked-in default Colossus loader reads an existing temporary archive. It
does not obtain a genuinely new live day. Real history therefore needs a real
replacement loader.

### Colossus loader contract

Create a function in your connector module:

```python
import pandas as pd


def get_colossus_pl(market_date: pd.Timestamp) -> pd.DataFrame:
    frame = obtain_real_colossus_data(market_date)
    return frame[
        [
            "Portfolio",
            "Underlying",
            "Risk Type",
            "Risk Greek",
            "PL",
        ]
    ]
```

The archive validates the returned DataFrame. Do not add extra columns or
change their order.

## Part 6 — Run one archive manually on JupyterHub

Use a persistent path. Do not use `/tmp`, and do not put confidential live
history under the versioned temporary `data/histo` directory.

From a Jupyter terminal:

```bash
export RISK_CUBE_PROJECT_ROOT="/path/to/Rebirth-V5"
export PL_HISTORICAL_PATH="/persistent/path/rebirth-history"
export COLOSSUS_LOADER="my_connectors:get_colossus_pl"

cd "$RISK_CUBE_PROJECT_ROOT"
.venv/bin/python -m tools.s02_archive
```

The configured module must be importable from that Python environment.

The entry point is:

```text
tools/s02_archive.py
```

After one successful manual run, schedule:

```text
jobs/s01_archive.ipynb
```

once each business day after the real market-state source becomes `OFFICIAL`.

## Part 7 — Point the application at the same history

The archive job and application must use the same absolute
`PL_HISTORICAL_PATH`:

```bash
export PL_HISTORICAL_PATH="/persistent/path/rebirth-history"
cd "/path/to/Rebirth-V5"
.venv/bin/python app.py
```

Despite its old name, `PL_HISTORICAL_PATH` is the root for Risk, Market, P&L
and Stock history.

If a new date is downloaded or created while the application is running,
restart the app or use Clear Cache so each history repository sees the new
archive generation.

DuckDB is an embedded local query engine. It does not require a DuckDB server,
database credentials or a persistent `.duckdb` file.

## Part 8 — Download already-created history from S3

The application does not download from S3 itself. Copy complete archive leaves
locally before launching the app.

Required S3 layout:

```text
s3://YOUR-BUCKET/cube/histo/
└── YYYY-MM-DD/
    ├── risk.parquet
    ├── market.parquet
    ├── colossus.parquet
    ├── stock.parquet       # optional
    └── _SUCCESS
```

AWS access needs permission to list the prefix and read its objects. Do not put
AWS access keys in the repository.

First preview the download:

```bash
aws s3 sync s3://YOUR-BUCKET/cube/histo "$PL_HISTORICAL_PATH" \
  --exclude "*" \
  --include "*/risk.parquet" \
  --include "*/market.parquet" \
  --include "*/colossus.parquet" \
  --include "*/stock.parquet" \
  --include "*/_SUCCESS" \
  --dryrun
```

Then run the same command without `--dryrun`.

Do not use `--delete`. Do not download only `risk.parquet`; a complete archive
day requires `colossus.parquet`, `market.parquet` and a matching `_SUCCESS`.

## Part 9 — Validate the downloaded or generated history

Run this from the same repository environment:

```python
from pathlib import Path
import os

from cube.history import list_completed_v4_archive_days


history_root = Path(os.environ["PL_HISTORICAL_PATH"])
days = list_completed_v4_archive_days(history_root)

if not days:
    raise RuntimeError(f"No valid schema-v4 history found under {history_root}")

print(f"Validated {len(days)} days")
print(f"First date: {days[0].snapshot_date}")
print(f"Last date:  {days[-1].snapshot_date}")
print(f"Latest Risk rows:   {days[-1].risk_rows:,}")
print(f"Latest Market rows: {days[-1].market_rows:,}")
```

## Part 10 — Important limitations

- There is no in-app remote history downloader.
- There is no browser CSV/Parquet history export button.
- `Load history` queries the locally available Parquet archive and displays it.
- The standard daily job writes locally; it does not upload completed leaves to
  S3. A central S3 archive needs a separate approved upload/synchronization job.
- The standard daily production job does not currently archive Stock.
- The daily job does not backfill arbitrary historical dates.

## Final checklist

```text
[ ] Both Promotion Score fillna lines exist in the running source tree
[ ] Python server was fully restarted
[ ] Invalid rows were printed with their exact raw Promotion Score values
[ ] Real Risk/Open/Current/market-state connectors work in the scheduler process
[ ] Real Colossus loader returns the exact five-column contract
[ ] PL_HISTORICAL_PATH is absolute, persistent and writable
[ ] Manual archive run returns archived or already_archived
[ ] Completed date contains all required files and _SUCCESS
[ ] list_completed_v4_archive_days validates at least one day
[ ] app.py uses the same PL_HISTORICAL_PATH
[ ] daily notebook/job runs only after OFFICIAL
```
