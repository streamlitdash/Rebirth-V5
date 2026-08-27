# Manual Cross Gamma dRisk and Shared Promotion Changes

You only need to manually edit four functional files. Do not change
`cube/services/s05_sources.py`, and do not copy over your real connector.

## 1. Edit `cube/domain/s04_crossgamma.py`

### 1A. Add `dRisk` to the raw connector columns

Find:

```python
CROSS_GAMMA_COLUMNS = (
```

At the end, change:

```python
    CROSS_GAMMA_SENSITIVITY,
)
```

to:

```python
    CROSS_GAMMA_SENSITIVITY,
    DRISK,
)
```

`DRISK = "dRisk"` should already be defined near the top of the file.

### 1B. Change the matrix-cell identity

Replace:

```python
CROSS_GAMMA_CELL_COLUMNS = tuple(
    column for column in CROSS_GAMMA_COLUMNS if column != CROSS_GAMMA_SENSITIVITY
)
```

with:

```python
CROSS_GAMMA_CELL_COLUMNS = tuple(
    column
    for column in CROSS_GAMMA_COLUMNS
    if column not in (CROSS_GAMMA_SENSITIVITY, DRISK)
)
```

This ensures Risk and dRisk values are not incorrectly treated as identity
columns.

### 1C. Validate both Risk and dRisk

Inside:

```python
def validate_cross_gamma_rows(...)
```

find the block beginning:

```python
raw_sensitivity = result[CROSS_GAMMA_SENSITIVITY]
```

and ending:

```python
result[CROSS_GAMMA_SENSITIVITY] = converted_sensitivity.astype(float)
```

Replace that entire block with:

```python
for column in (CROSS_GAMMA_SENSITIVITY, DRISK):
    raw_values = result[column]

    boolean_values = raw_values.map(
        lambda value: isinstance(value, (bool, np.bool_))
    )

    converted = pd.to_numeric(raw_values, errors="coerce")

    invalid = (
        boolean_values
        | converted.isna()
        | ~converted.map(np.isfinite)
    )

    if invalid.any():
        rows = result.index[invalid].tolist()[:5]
        raise ValueError(
            f"{column!r} must contain finite numbers at rows {rows}"
        )

    result[column] = converted.astype(float)
```

### 1D. Preserve source XGamma dRisk

Inside:

```python
def _build_input_legs(...)
```

find:

```python
source[SPLIT] = CROSS_GAMMA_SOURCE_SPLIT
source[DRISK] = np.nan
source[PL] = 0.0
```

Delete only:

```python
source[DRISK] = np.nan
```

The result should be:

```python
source[SPLIT] = CROSS_GAMMA_SOURCE_SPLIT
source[PL] = 0.0
```

### 1E. Keep developed output dRisk unavailable

Inside:

```python
def _attach_output_market(...)
```

keep this exactly as it is:

```python
result[SOURCE_TYPE] = spec.source_type
result[SPLIT] = XGAMMA_SPLIT
result[DRISK] = np.nan
result[PL] = 0.0
```

Do not remove this `result[DRISK] = np.nan` line.

The resulting contract is:

```text
Raw XGamma row dRisk = connector dRisk
Developed output dRisk = unavailable
Developed output Risk = Cross Gamma Sensitivity × input Move
```

## 2. Edit your real Cross Gamma adapter

File:

```text
cube/adapters/s06_crossgamma.py
```

### 2A. Import `DRISK`

Change:

```python
from cube.domain.s02_products import GROUP, PORTFOLIO, RISK_GREEK
```

to:

```python
from cube.domain.s02_products import DRISK, GROUP, PORTFOLIO, RISK_GREEK
```

If your import uses several lines, simply add:

```python
DRISK,
```

### 2B. Add dRisk to every returned row

Where you build each connector row, add:

```python
DRISK: real_connector_drisk_value,
```

For example:

```python
{
    PORTFOLIO: portfolio,
    GROUP: group,
    INPUT_RISK_TYPE: input_risk_type,
    INPUT_RISK_GREEK: input_risk_greek,
    RISK_GREEK: source_xgamma_greek,
    INPUT_UNDERLYING: input_underlying,
    INPUT_TENOR_SWAP: input_tenor_swap,
    INPUT_TENOR_OPTION: input_tenor_option,
    OUTPUT_RISK_TYPE: output_risk_type,
    OUTPUT_RISK_GREEK: output_risk_greek,
    OUTPUT_UNDERLYING: output_underlying,
    OUTPUT_TENOR_SWAP: output_tenor_swap,
    OUTPUT_TENOR_OPTION: output_tenor_option,
    CROSS_GAMMA_SENSITIVITY: cross_gamma_sensitivity,
    DRISK: cross_gamma_drisk,
}
```

If your connector already returns a DataFrame, rename its dRisk column if
necessary:

```python
frame = frame.rename(
    columns={
        "your real dRisk column": DRISK,
    }
)
```

Then return the exact order:

```python
return frame.loc[:, list(CROSS_GAMMA_COLUMNS)]
```

The final columns must be exactly:

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

Do not set real missing dRisk to a made-up zero.

### 2C. Update temporary rows if you still use them

In `_temp_cross_gamma`, add a finite dRisk to every dictionary, for example:

```python
CROSS_GAMMA_SENSITIVITY: 12_500.0,
DRISK: 1_250.0,
```

Repeat this for every temporary row.

## 3. Edit `cube/domain/s07_governance.py`

### 3A. Ensure neutral promotion values are filled

At the end of:

```python
def _apply_validated_thresholds(...)
```

immediately before `return result`, make sure all three lines exist:

```python
result[DISPLAY_BUCKET] = result[DISPLAY_BUCKET].fillna("Other")
result[PROMOTION_REASON] = result[PROMOTION_REASON].fillna("")
result[PROMOTION_SCORE] = result[PROMOTION_SCORE].fillna(0.0)

return result
```

The earlier `Promotion Score` error can happen when the third line is missing
from the deployed version.

### 3B. Reject missing Promotion Scores before publishing

Inside:

```python
def _validate_dashboard_release(...)
```

find:

```python
if column == RISK or column in threshold_columns:
    invalid |= numeric.isna()
```

Replace it with:

```python
if column in (RISK, PROMOTION_SCORE) or column in threshold_columns:
    invalid |= numeric.isna()
```

## 4. Edit `cube/ui/s02_aggregation.py`

### 4A. Allow an older snapshot with a missing Promotion Score to open

Inside:

```python
def prepare_risk_data(...)
```

find:

```python
if "promotion score" not in frame:
    frame["promotion score"] = 0.0
```

Replace it with:

```python
if "promotion score" not in frame:
    frame["promotion score"] = 0.0
else:
    frame["promotion score"] = frame["promotion score"].fillna(0.0)
```

This only fills genuinely missing values. Bad text and infinity continue to
produce an error.

### 4B. Display source XGamma dRisk

Inside:

```python
def credit_measure_values(...)
```

find:

```python
if metric == "risk":
    selected.loc[source_mask] = frame.loc[source_mask, "risk"].astype(float)
```

Replace it with:

```python
selected.loc[source_mask] = frame.loc[source_mask, metric].astype(float)
```

This means source XGamma rows retain both their generic Risk and generic dRisk
when changing the Credit measure selector.

## 5. Do not change the promotion grouping

In `cube/domain/s07_governance.py`, the promotion keys must remain:

```python
keys = [
    RISK_TYPE,
    RISK_GREEK,
    REPORTED_UNDERLYING,
]
```

Do not add `Split` or `Portfolio`.

That is why these rows combine:

```text
Split=Risk
Split=Gamma
Split=XGAMMA
Split=New Trades
```

when they share the same destination:

```text
Risk Type + Risk Greek + Reported Underlying
```

## 6. Do not change `cube/services/s05_sources.py`

This remains correct:

```python
def get_cross_gamma_sensitivities(
    risk_date: pd.Timestamp,
) -> pd.DataFrame:
    selected_date = pd.Timestamp(risk_date).normalize()
    return get_cross_gamma_matrix(selected_date)
```

Do not call the Cross Gamma adapter again anywhere else.

## 7. Fully restart the server

After saving all four functional files:

1. Stop the running Python/Dash server.
2. Stop the Jupyter kernel if necessary.
3. Start a completely new process.
4. Open the app again.

A browser refresh or Shift+F9 may leave old imported modules or the old
committed snapshot in memory.

## Final confirmation

When these rows share the same destination identity:

```text
Risk Type + Risk Greek + Reported Underlying
```

promotion includes:

```text
ordinary Risk
+ developed Cross Gamma Risk
+ developed Gamma Risk
+ New Trades Risk/P&L
```

`Split` and `Portfolio` are deliberately not promotion grouping keys. The
committed baseline calculation still uses only Portfolio-mapped rows in the
configured Activities 1–3 promotion universe.
