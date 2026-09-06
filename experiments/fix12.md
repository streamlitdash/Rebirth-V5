# Fix 12 — Isolate market failures by product

**Status:** Proposed experiment. This document does not change the application source code.

## Problem

The refresh currently shares one market circuit breaker across every product in
`cube/services/s06_refresh.py`:

```python
market_circuit = _OperationalCircuitBreaker()
```

That same object is passed into the Open and Current calls for Credit Delta,
FX Delta, FX Vega, and the remaining products:

```python
circuit=market_circuit
```

This means that if Credit Delta Open has a network failure, the shared circuit
opens. FX Delta and FX Vega can then be skipped even though their own connectors
may be working.

The required behaviour is:

```text
Credit Delta Open fails
    -> record Credit Delta Open as missing
    -> still call Credit Delta Current
    -> still call FX Delta
    -> still call FX Vega
    -> show a warning for the failed Credit Delta call
```

## Smallest manual change

Make the circuit breaker local to each product call instead of sharing it across
all products.

### 1. Disable the cumulative refresh budget for this experiment

Find:

```python
connector_budget = _ConnectorRefreshBudget(
    self._connector_refresh_budget_seconds
)
```

Replace it with:

```python
connector_budget = None
```

Then delete the two blocks that begin with:

```python
if connector_budget.is_exhausted and not risk_circuit.is_open:
```

and:

```python
if connector_budget.is_exhausted and not market_circuit.is_open:
```

This is necessary for two reasons:

1. `None.is_exhausted` would raise an error.
2. The shared cumulative budget can independently skip every remaining product
   after an earlier product consumes the budget.

This does **not** remove the individual connector deadline. Each connector call
still has its existing per-call timeout.

### 2. Give every Open call its own circuit

Inside:

```python
for spec in open_specs:
```

add this immediately before the Open connector call:

```python
product_open_circuit = _OperationalCircuitBreaker()
```

Then make the call look like this:

```python
raw_open = self._load_product_market_open(
    spec,
    checker_date,
    requested_underlyings,
    market_status=expected_market_status,
    circuit=product_open_circuit,
    budget=None,
)
```

### 3. Give every Current call its own circuit

Inside:

```python
for spec in status_specs:
```

add this immediately before the Current connector call:

```python
product_status_circuit = _OperationalCircuitBreaker()
```

Then make the call look like this:

```python
raw_status = self._load_product_market_status(
    spec,
    market_date,
    requested_underlyings,
    market_status=expected_market_status,
    circuit=product_status_circuit,
    budget=None,
)
```

### 4. Leave the existing global circuit declarations for the first experiment

Do not remove `market_circuit` or `risk_circuit` yet. Other error-handling paths
may still refer to them. The important change is that the product Open and
Current connector calls no longer use one shared market circuit.

Existing Risk calls can continue to use:

```python
budget=connector_budget
```

because `connector_budget` is now `None`. An operational Risk connector failure
already returns `_empty_product_risk(spec)` and continues to the next product.

## Result when a product fails

### Only Open fails

If Current succeeds, the existing market-leg merge copies Current into Open.
The product remains usable and its market move is zero.

### Only Current fails

If Open succeeds, the existing market-leg merge copies Open into Current. The
product remains usable and its market move is zero.

### Open and Current both fail

For that product only:

- Open and Current remain `NA`.
- `Market Available` is `False`.
- Market status reports `No matching market row`.
- Dashboard-visible Market Move and P&L are zero.
- Risk and dRisk remain available if the Risk connector succeeded.
- The UI shows a warning and the exact incident is written to the terminal log.

FX Delta, FX Vega, and every later product are still called normally.

### Risk fails

A failed Risk connector cannot safely invent Portfolio, Underlying, or tenor
identities. That product therefore contributes zero Risk rows, a warning is
shown, and later product connectors are still called.

## Errors that should continue versus stop

Network and service-availability failures should be handled product by product:

```text
log exact error -> add UI warning -> use shaped missing data -> continue
```

Data contract errors must remain fatal:

- missing required columns;
- duplicate connector keys;
- invalid values;
- merge-cardinality errors;
- connector signature errors such as `TypeError`.

These indicate bad code or bad data, so the refresh should fail and retain the
last known-good dashboard instead of silently replacing it.

## Checks to run

1. Register products in this order: Credit Delta, FX Delta, FX Vega.
2. Make Credit Delta Open raise a network/availability error.
3. Confirm FX Delta Open and FX Vega Open are each called once.
4. Confirm Credit Delta Current is still called.
5. If Credit Delta Current succeeds, confirm it is copied into Open.
6. If both Credit Delta market legs fail, confirm its dashboard Open/Current are
   missing, `Market Available` is false, and Market Move/P&L are zero.
7. Confirm later products still contain their normal data.
8. Make Credit Delta Risk fail and confirm later Risk connectors are still
   called.
9. Make Credit Delta return an invalid schema and confirm the refresh fails and
   retains the previous good dashboard.
10. Confirm connector retries remain disabled and the refresh still uses one
    worker.

## Rollback

Revert only the edits described above in `cube/services/s06_refresh.py`. This
Markdown file itself is documentation and does not affect runtime behaviour.
