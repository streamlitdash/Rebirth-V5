# Fix 19 — Preserve Cross Gamma dRisk and shared promotion

## What this fixes

This change does two things:

1. It adds connector-owned `dRisk` to the raw Cross Gamma source exposure.
2. It prevents a genuinely missing neutral `Promotion Score` from stopping the
   Risk dashboard during startup.

The shared promotion calculation itself already existed. Do not add a second
promotion calculation and do not group promotion by `Split`.

The current release order is:

```text
ordinary Risk and developed Gamma
    + developed Cross Gamma
    + New Trades
    -> Portfolio configuration
    -> Reported Underlying
    -> promotion calculation
```

Promotion is calculated at:

```text
Risk Type + Risk Greek + Reported Underlying
```

`Split` and `Portfolio` are not promotion keys. Therefore matching rows from
all four sources contribute to the same signed totals.

Example:

```text
Ordinary FX Delta Risk       40
Developed Cross Gamma Risk   20
Developed Gamma Risk         15
New Trades FX Delta Risk     25
                              --
Total FX Delta Risk         100
```

The total is calculated first. `abs()` is applied only when the total is
divided by its promotion threshold.

## Important scope rule

The committed baseline promotion calculation uses only rows that:

- have a mapped Portfolio; and
- belong to the configured Activities 1–3 promotion universe.

Rows outside that universe remain in the data, but do not contribute to the
baseline total. They can inherit a result from an eligible row with the same
Risk Type, Risk Greek and Reported Underlying.

## Exact Cross Gamma calculation

The real Cross Gamma connector must now provide both:

```text
Cross Gamma Sensitivity
dRisk
```

Only `Cross Gamma Sensitivity` is developed through the input MarketBook
`Move`:

```python
developed_risk = cross_gamma_sensitivity * input_market_move
```

When several input matrix cells develop into the same output identity, their
developed Risk values are summed:

```text
Portfolio
+ Group
+ Output Risk Type
+ Output Risk Greek
+ Output Underlying
+ Output Tenor Swap
+ Output Tenor Option
```

Cross Gamma P&L remains exactly zero.

Connector `dRisk` remains authoritative on the raw `XGamma` or `XGamma Vega`
source row and contributes to that source Greek's promotion. Developed output
dRisk stays unavailable, just like the Delta developed from ordinary Gamma.
The code does not invent a dRisk transformation that the connector contract
has not defined.

## Files involved

Functional runtime files:

```text
cube/domain/s04_crossgamma.py
cube/adapters/s06_crossgamma.py
cube/domain/s07_governance.py
cube/ui/s02_aggregation.py
```

Documentation-only correction:

```text
cube/domain/s03_calculations.py
cube/pages/risk/s06_explorertables.py
```

Regression tests:

```text
tests/s25_crossgamma.py
tests/s14_reporting.py
tests/s19_riskfilters.py
```

No functional change is needed in:

```text
cube/services/s05_sources.py
```

Its existing `get_cross_gamma_sensitivities(risk_date)` function already
forwards the adapter result into the refresh manager.

## Easiest manual installation

### 1. Stop the server completely

Do not rely on a browser refresh or Shift+F9. Stop the Python server/kernel so
the old imported modules and committed snapshot are removed.

### 2. Copy the three framework files

Copy these complete files from the updated branch:

```text
cube/domain/s04_crossgamma.py
cube/domain/s07_governance.py
cube/ui/s02_aggregation.py
```

You may also copy `cube/domain/s03_calculations.py` and
`cube/pages/risk/s06_explorertables.py`; they only correct explanations of the
Cross Gamma dRisk and Credit-measure behavior.

### 3. Do not overwrite your real Cross Gamma connector

If `cube/adapters/s06_crossgamma.py` contains your real connector code, keep
that code. Only update its returned DataFrame contract as shown below.

Import `DRISK` if it is not already imported:

```python
from cube.domain.s02_products import DRISK
```

Every returned row must include a finite `dRisk` value:

```python
{
    "Portfolio": portfolio,
    "Group": group,
    "Input Risk Type": input_risk_type,
    "Input Risk Greek": input_risk_greek,
    "Risk Greek": source_xgamma_greek,
    "Input Underlying": input_underlying,
    "Input Tenor Swap": input_tenor_swap,
    "Input Tenor Option": input_tenor_option,
    "Output Risk Type": output_risk_type,
    "Output Risk Greek": output_risk_greek,
    "Output Underlying": output_underlying,
    "Output Tenor Swap": output_tenor_swap,
    "Output Tenor Option": output_tenor_option,
    "Cross Gamma Sensitivity": cross_gamma_sensitivity,
    "dRisk": cross_gamma_drisk,
}
```

Return the exact ordered schema:

```python
from cube.domain.s04_crossgamma import CROSS_GAMMA_COLUMNS

frame = pd.DataFrame(rows)
return frame.loc[:, list(CROSS_GAMMA_COLUMNS)]
```

The exact order is:

```text
Portfolio
Group
Input Risk Type
Input Risk Greek
Risk Greek
Input Underlying
Input Tenor Swap
Input Tenor Option
Output Risk Type
Output Risk Greek
Output Underlying
Output Tenor Swap
Output Tenor Option
Cross Gamma Sensitivity
dRisk
```

Missing, blank, boolean, infinite or non-numeric Cross Gamma Risk/dRisk values
are rejected at the adapter boundary. Do not replace a missing real connector
value with a made-up number.

### 4. Leave the service forwarding code alone

This remains sufficient in `cube/services/s05_sources.py`:

```python
def get_cross_gamma_sensitivities(risk_date: pd.Timestamp) -> pd.DataFrame:
    selected_date = pd.Timestamp(risk_date).normalize()
    return get_cross_gamma_matrix(selected_date)
```

Do not call the Cross Gamma adapter a second time elsewhere.

### 5. Start a completely new server process

Start the app normally after the files are in place. A full restart is required
because the raw schema constants and callback modules are imported at process
startup.

## What changed inside `s04_crossgamma.py`

### Raw schema

`dRisk` is placed immediately after `Cross Gamma Sensitivity`:

```python
CROSS_GAMMA_COLUMNS = (
    # identity columns remain unchanged
    CROSS_GAMMA_SENSITIVITY,
    DRISK,
)
```

Both numeric values are excluded from the duplicate-cell identity:

```python
CROSS_GAMMA_CELL_COLUMNS = tuple(
    column
    for column in CROSS_GAMMA_COLUMNS
    if column not in (CROSS_GAMMA_SENSITIVITY, DRISK)
)
```

This means two rows with the same complete matrix-cell identity are still a
duplicate even when their Risk or dRisk values disagree.

### Validation

Both values use the same required finite-number check:

```python
for column in (CROSS_GAMMA_SENSITIVITY, DRISK):
    raw_values = result[column]
    boolean_values = raw_values.map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    converted = pd.to_numeric(raw_values, errors="coerce")
    invalid = boolean_values | converted.isna() | ~converted.map(np.isfinite)
    if invalid.any():
        rows = result.index[invalid].tolist()[:5]
        raise ValueError(
            f"{column!r} must contain finite numbers at rows {rows}"
        )
    result[column] = converted.astype(float)
```

### Source dRisk and developed Risk

Each raw input cell keeps its connector dRisk on the source row and creates one
developed Risk contribution:

```python
joined[_CONTRIBUTION] = (
    joined[CROSS_GAMMA_SENSITIVITY].astype(float)
    * invalid_move.astype(float)
)
```

The existing output grouping sums that Risk over the complete output identity:

```python
developed = (
    contributions.groupby(
        output_keys,
        sort=False,
        as_index=False,
        dropna=False,
    )[_CONTRIBUTION]
    .sum(min_count=1)
    .rename(columns={_CONTRIBUTION: RISK})
)
```

The old line overwriting source Cross Gamma `dRisk` was removed. Developed
output dRisk deliberately remains unavailable:

```python
result[DRISK] = np.nan
```

Cross Gamma P&L remains:

```python
result[PL] = 0.0
```

## Why all four sources already contribute to promotion

`cube/services/s02_state.py::_release_pl_views` builds one release before
calling promotion:

```python
release_frames = ordinary_product_pl_frames
release_frames.extend(cross_gamma_and_new_trade_overlays)
enriched = pd.concat(release_frames, ignore_index=True, sort=False)
enriched = attach_reported_underlying(enriched, reported_underlyings)
enriched = apply_baseline_promotions(enriched, thresholds)
```

Developed ordinary Gamma already becomes:

```text
Risk Greek = Delta
Split = Gamma
Risk = developed Gamma Risk
dRisk = unavailable
PL = 0
```

Developed Cross Gamma becomes its declared output identity, for example:

```text
Input:  Credit / Delta / CDX IG
Output: FX / Delta / EUR/USD

Released promotion identity:
FX / Delta / Reported EUR/USD
Split = XGAMMA
```

A matching ordinary FX Delta row, developed Gamma Delta row and New Trades FX
Delta row therefore share one promotion total.

The raw Cross Gamma source row remains separately visible under `XGamma` or
`XGamma Vega`. Its connector Risk and dRisk participate in that separate source
Greek's promotion result.

## Promotion Score startup protection

The governance calculation already assigns an unclassified identity the
neutral result:

```python
result[DISPLAY_BUCKET] = result[DISPLAY_BUCKET].fillna("Other")
result[PROMOTION_REASON] = result[PROMOTION_REASON].fillna("")
result[PROMOTION_SCORE] = result[PROMOTION_SCORE].fillna(0.0)
```

This fix adds two small protections without hiding a new pipeline defect:

1. A new dashboard release requires `Promotion Score` to be finite and
   nonmissing. The governed calculation above is the only place that supplies
   a neutral zero.
2. UI preparation can still render an older already-committed snapshot whose
   neutral score is genuinely missing.

Bad text, booleans and infinity still raise an error. Only a true missing value
is treated as neutral zero.

## Credit SP01 display

Credit Cross Gamma source rows contain generic connector Risk/dRisk rather than
separate SP01/PSP01 columns. When the Credit measure selector is used, the UI
keeps both generic values on those source rows:

```python
selected.loc[source_mask] = frame.loc[source_mask, metric].astype(float)
```

Developed Credit Delta Cross Gamma rows populate `Risk SP01`. Their developed
`dRisk SP01` remains unavailable at the calculation boundary and is displayed
as zero on the dashboard.

## Verification

From the repository root, run:

```powershell
python -m pytest tests/s25_crossgamma.py tests/s14_reporting.py tests/s19_riskfilters.py tests/s15_overlays.py tests/s05_pl.py tests/s26_newtrades.py -q
```

Expected focused result for this change:

```text
121 passed
```

Then run the complete suite:

```powershell
python -m pytest -q
```

The completed v4 verification for this change was:

```text
676 passed
```

## Quick manual check

Choose one destination identity that has all relevant sources, such as
`FX / Delta / EUR/USD`, and print:

```python
check = dashboard.loc[
    dashboard["Risk Type"].eq("FX")
    & dashboard["Risk Greek"].eq("Delta")
    & dashboard["Reported Underlying"].eq("EUR/USD"),
    [
        "Split",
        "Underlying",
        "Risk",
        "dRisk",
        "PL",
        "Promotion Score",
        "Promotion Reason",
    ],
]
print(check.to_string(index=False))
```

You should see the same Promotion Score and Promotion Reason on matching
`Risk`, `Gamma`, `XGAMMA`, and `New Trades` rows.

## Common failures

### `Cross Gamma columns must be exactly ...`

Your real connector has not added `dRisk`, has added it in the wrong place, or
returns an extra column. Select `CROSS_GAMMA_COLUMNS` immediately before return.

### `'dRisk' must contain finite numbers`

At least one raw matrix cell has missing, text, boolean or infinite dRisk. Fix
the connector data. Do not weaken the validator or invent zero.

### A developed output is not joining ordinary risk

Compare these exact fields after Reported Underlying is attached:

```text
Risk Type
Risk Greek
Reported Underlying
```

`Split`, Portfolio and raw input Underlying are not promotion keys.

### A row does not contribute to baseline promotion

Check:

```text
Portfolio Mapped == True
Activity is inside the Activities 1–3 promotion universe
```

### The old Promotion Score error still appears

Confirm that both `cube/domain/s07_governance.py` and
`cube/ui/s02_aggregation.py` were copied, then fully stop and restart the
Python server. A browser refresh alone does not replace imported modules or the
old committed snapshot.

## Final checklist

```text
[ ] Cross Gamma connector returns exact ordered columns
[ ] dRisk is finite on every Cross Gamma matrix cell
[ ] s04_crossgamma.py copied
[ ] s07_governance.py copied
[ ] s02_aggregation.py copied
[ ] personal adapter logic preserved
[ ] s05_sources.py not duplicated or recalled elsewhere
[ ] server process fully restarted
[ ] focused tests pass
[ ] ordinary/Gamma/XGAMMA/New Trades share destination promotion
[ ] Cross Gamma P&L remains zero
[ ] application opens without a missing Promotion Score error
```
