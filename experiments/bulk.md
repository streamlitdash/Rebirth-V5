# Commodity bulk Market update — simple exact-pair guide

This guide is for the current Rebirth V5 code on branch **v4**.

It explains the smallest change needed to add bulk Market updates for:

- `commo/delta`
- `commo/vega`

The important correction is that a Commodity request cannot be scoped by
`Underlying` alone. Each Commodity bulk connector must receive the exact ordered,
unique Risk pairs:

```text
(Underlying, Tenor Swap)
```

FX Delta must keep its existing Underlying-only bulk interface.

This file is an implementation guide only. Publishing it does not change the
running application.

## Short answer

Do not create another refresh manager, cache, UUID, async layer, page callback, or
general-purpose market-scope framework.

Make four narrow changes:

1. keep FX Delta exactly as it is;
2. derive unique `(Underlying, Tenor Swap)` pairs from the already validated
   Commodity Risk frame;
3. pass those pairs once to each Commodity Open or Current bulk connector; and
4. reject any returned Commodity pair that was not requested.

The two Commodity Greeks remain separate because they are separate products and
may use different sources.

```text
Commo Delta Open     -> one call containing all Delta Risk pairs
Commo Delta Current  -> one call containing all Delta Risk pairs
Commo Vega Open      -> one call containing all Vega Risk pairs
Commo Vega Current   -> one call containing all Vega Risk pairs
```

That means:

| Refresh | Commodity bulk calls |
|---|---:|
| Warm Recalculate, Current only | `2` |
| Cold/full Risk refresh, Open and Current | `4` |
| Commodity quotes disabled | `0` |

There must not be one request per tenor and there must not be one combined
Delta-and-Vega request.

## Corrected result for the current fixtures

The current temporary fixtures make the effect of the corrected scope measurable:

| Product | Risk rows | Risk Underlyings | Unique Risk pairs | Current Market pairs | Pairs after this change |
|---|---:|---:|---:|---:|---:|
| Commo Delta | `414` | `3` | `9` | `12` | `9` |
| Commo Vega | `414` | `3` | `9` | `12` | `9` |

Risk contains `1M`, `3M`, and `6M`. The current Market fixture also contains a
market-only `1Y` row for each Underlying. Because the new request is deliberately
driven by exact Risk pairs, those three `1Y` rows are not requested. Each Commodity
MarketBook therefore changes from 12 rows to 9 rows.

This is expected, not a bulk-connector bug:

- quotes and P&L for the 9 Risk pairs must match the old path;
- market-only `1Y` rows will no longer appear in Quick Market or history; and
- if the business later requires market-only tenors, provide a separate
  authoritative tenor catalogue. Do not discover or guess them from a previous
  Market response or from UI state.

## The exact contract

For Commodity, the bulk input is an ordered tuple of two-value tuples:

```python
CommodityMarketKey = tuple[str, str]
CommodityMarketScope = tuple[CommodityMarketKey, ...]

scope = (
    ("BRENT", "DEC26"),
    ("GOLD", "MAR27"),
)
```

The rules are simple:

- `Underlying` comes from validated Risk;
- `Tenor Swap` comes from the same validated Risk row;
- duplicate Risk positions collapse to one pair;
- first-seen Risk order is retained;
- `Tenor Swap Order` does **not** come from Risk; it remains Market-owned output;
- a connector may return fewer requested pairs when quotes are unavailable;
- a connector may never return an unrequested pair; and
- never split the pairs into independent Underlying and tenor lists.

For example, if the request is:

```text
(BRENT, DEC26)
(GOLD, MAR27)
```

then `(BRENT, MAR27)` is outside scope even though both individual values occur in
the request. Filtering with two independent `.isin(...)` calls would wrongly allow
that crossed pair. Use an exact two-column join.

## How the current bulk flow works

The current FX Delta path is already the model for call timing and failure handling:

```text
Recalculate / refresh request
  -> RiskRefreshManager resolves which Market legs need refreshing
  -> it builds the requested scope
  -> it prefers adapter.market_open_bulk or adapter.market_status_bulk
  -> the source reads one partition / makes one upstream request
  -> the normal product validators validate the returned DataFrame
  -> Open and Current merge into MarketBook
  -> the existing P&L calculation runs
```

Keep that chain. Only the Commodity scope changes from an Underlying tuple to an
exact pair tuple.

The active registration is in `cube/services/s05_sources.py`, inside
`_get_csv_product_connector_adapters()`. Do not add these hooks only to
`cube/adapters/s05_commodities.py`; that is not the active composition point for
this path.

## Files to change

Only these runtime files need changing:

1. `cube/domain/s02_products.py`
2. `cube/services/s05_sources.py`
3. `cube/services/s06_refresh.py`

Update these tests:

4. `tests/s20_connectors.py`
5. `tests/s07_integration.py`

No page, table, history, P&L, ProductSpec, or calculation file needs a new bulk
implementation.

## Step 1 — add the narrow Commodity callable type

In `cube/domain/s02_products.py`, leave `ProductBulkMarketConnector` unchanged.
FX Delta already uses it and must continue receiving `tuple[str, ...]`.

Immediately after it, add a Commodity-specific scope and protocol:

```python
CommodityMarketKey = tuple[str, str]
CommodityMarketScope = tuple[CommodityMarketKey, ...]


class ProductTenoredBulkMarketConnector(Protocol):
    """One Commodity connector for exact Risk Underlying/tenor pairs."""

    def __call__(
        self,
        source_date: pd.Timestamp,
        market_keys: CommodityMarketScope,
        *,
        market_status: str,
    ) -> pd.DataFrame: ...


ProductBulkMarketHook = (
    ProductBulkMarketConnector | ProductTenoredBulkMarketConnector
)
```

Then change only the two optional field annotations in
`ProductConnectorAdapter`:

```python
market_open_bulk: ProductBulkMarketHook | None = None
market_status_bulk: ProductBulkMarketHook | None = None
```

Update that class's bulk docstring to say:

- FX Delta receives an ordered, unique Underlying tuple.
- Commo Delta and Commo Vega receive ordered, unique
  `(Underlying, Tenor Swap)` pairs from validated Risk.

Do not add new adapter fields. The existing `market_open_bulk` and
`market_status_bulk` fields are sufficient.

## Step 2 — add the Commodity source functions

Work in `cube/services/s05_sources.py`.

### 2.1 Leave FX unchanged

Do not rewrite these functions:

```text
_bulk_underlying_scope
_get_fx_delta_market_bulk
get_fx_delta_market_open_bulk
get_fx_delta_market_status_bulk
```

FX does not have a tenor axis, so its current Underlying-only contract is correct.

### 2.2 Validate the Commodity pair input

Import `CommodityMarketScope` from `cube.domain.s02_products`, then add a small
validator beside `_bulk_underlying_scope`:

```python
def _bulk_commodity_scope(
    market_keys: CommodityMarketScope,
) -> CommodityMarketScope:
    if not isinstance(market_keys, tuple):
        raise TypeError("market_keys must be an ordered tuple")

    normalized: list[tuple[str, str]] = []
    for item in market_keys:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ValueError(
                "Commodity market_keys must contain "
                "(Underlying, Tenor Swap) tuples"
            )
        underlying, tenor_swap = item
        if not isinstance(underlying, str) or not underlying.strip():
            raise ValueError("Commodity Underlying must be nonblank text")
        if not isinstance(tenor_swap, str) or not tenor_swap.strip():
            raise ValueError("Commodity Tenor Swap must be nonblank text")
        normalized.append((underlying.strip(), tenor_swap.strip()))

    if len(set(normalized)) != len(normalized):
        raise ValueError("Commodity market_keys must be unique")
    return tuple(normalized)
```

### 2.3 Read one partition and filter by exact pair

Add one shared private Commodity helper:

```python
def _get_commo_market_bulk(
    source_type: str,
    dataset: str,
    source_date: pd.Timestamp,
    market_keys: CommodityMarketScope,
    *,
    market_status: str,
) -> pd.DataFrame:
    if dataset not in {"market_open", "market_status"}:
        raise ValueError("dataset must be 'market_open' or 'market_status'")
    date_parameter = "open_date" if dataset == "market_open" else "market_date"
    _business_date(source_date, parameter=date_parameter)
    selected_status = _market_status(market_status)
    requested = _bulk_commodity_scope(market_keys)
    spec = _source_spec(source_type)
    if source_type not in {"commo/delta", "commo/vega"}:
        raise ValueError("Commodity bulk source_type is not supported")
    if spec.tenor_columns != ["Tenor Swap"]:
        raise ValueError("Commodity bulk expects exactly the Tenor Swap axis")

    value_column = OPEN if dataset == "market_open" else CURRENT
    output_columns = [
        UNDERLYING,
        *spec.tenor_columns,
        *spec.tenor_order_columns,
        value_column,
    ]
    frame = _source_rows(
        dataset,
        source_type,
        output_columns,
        allow_empty=True,
    )

    requested_frame = pd.DataFrame(
        requested,
        columns=[UNDERLYING, "Tenor Swap"],
    )
    requested_frame["__bulk_pair_order"] = range(len(requested_frame))
    frame = requested_frame.merge(
        frame,
        how="inner",
        on=[UNDERLYING, "Tenor Swap"],
        validate="one_to_one",
    )
    frame = (
        frame.sort_values("__bulk_pair_order", kind="stable")
        .drop(columns="__bulk_pair_order")
        .reset_index(drop=True)
    )
    frame = frame.loc[:, output_columns]

    _require_temp_notice(
        frame,
        [UNDERLYING, *spec.tenor_columns],
        dataset=dataset,
    )
    if dataset == "market_status":
        frame[MARKET_STATUS] = selected_status
    return frame
```

The important line is the merge on both columns. Do not use:

```python
frame[UNDERLYING].isin(underlyings) & frame["Tenor Swap"].isin(tenors)
```

That loses the pairing and can return crossed rows.

### 2.4 Add four thin public wrappers

Add:

```text
get_commo_delta_market_open_bulk
get_commo_delta_market_status_bulk
get_commo_vega_market_open_bulk
get_commo_vega_market_status_bulk
```

Each wrapper should only bind its `source_type` and `dataset`, then call
`_get_commo_market_bulk(...)`. Keep the same date and `market_status` keyword
contract as FX.

For example:

```python
def get_commo_delta_market_open_bulk(
    open_date: pd.Timestamp,
    market_keys: CommodityMarketScope,
    *,
    market_status: str,
) -> pd.DataFrame:
    return _get_commo_market_bulk(
        "commo/delta",
        "market_open",
        open_date,
        market_keys,
        market_status=market_status,
    )
```

The other three wrappers are the same shape with the bound product and leg
changed.

### 2.5 Register the hooks

Inside `_get_csv_product_connector_adapters()`, use two explicit maps:

```python
bulk_open = {
    "fx/delta": get_fx_delta_market_open_bulk,
    "commo/delta": get_commo_delta_market_open_bulk,
    "commo/vega": get_commo_vega_market_open_bulk,
}
bulk_status = {
    "fx/delta": get_fx_delta_market_status_bulk,
    "commo/delta": get_commo_delta_market_status_bulk,
    "commo/vega": get_commo_vega_market_status_bulk,
}
```

Then register:

```python
market_open_bulk=bulk_open.get(source_type),
market_status_bulk=bulk_status.get(source_type),
```

Add the four public Commodity functions to `__all__` if this module continues to
export the FX functions there.

For a real upstream connector, send one request containing the exact pairs, for
example:

```json
{
  "marketDate": "2026-08-14",
  "riskType": "Commo",
  "riskGreek": "Delta",
  "marketStatus": "OFFICIAL",
  "keys": [
    {"underlying": "BRENT", "tenorSwap": "DEC26"},
    {"underlying": "GOLD", "tenorSwap": "MAR27"}
  ]
}
```

Do not loop over the old one-Underlying connector inside the new bulk wrapper.
That would preserve the old call count while only changing the function name.

## Step 3 — build the Commodity pairs from validated Risk

Work in `cube/services/s06_refresh.py`.

### 3.1 Widen the existing FX-only gate

Near the existing refresh constants, add:

```python
_BULK_MARKET_SOURCE_TYPES = frozenset(
    {"fx/delta", "commo/delta", "commo/vega"}
)
_COMMODITY_BULK_SOURCE_TYPES = (
    _BULK_MARKET_SOURCE_TYPES - {"fx/delta"}
)
```

`RiskRefreshManager.__init__()` currently rejects a bulk hook on every source except
`fx/delta`. Replace its FX-only condition:

```python
if source_type != "fx/delta" and any(bulk_hooks.values()):
    ...
```

with:

```python
if source_type not in _BULK_MARKET_SOURCE_TYPES and any(bulk_hooks.values()):
    ...
```

Update the error text to list the three supported source types. Do not remove the
guard entirely: a bulk hook on a product such as `credit/delta` must still fail at
construction.

### 3.2 Derive a stable pair scope

Near `_risk_underlyings`, add:

```python
@staticmethod
def _commodity_market_scope(
    spec: ProductSpec,
    risk_frame: pd.DataFrame,
) -> tuple[tuple[str, str], ...]:
    if spec.source_type not in _COMMODITY_BULK_SOURCE_TYPES:
        raise ValueError("Commodity pair scope requested for an unsupported source")
    columns = [UNDERLYING, *spec.tenor_columns]
    scope = risk_frame.loc[:, columns].drop_duplicates(keep="first")
    return tuple(scope.itertuples(index=False, name=None))
```

Call this with `next_risk[source_type]`. That frame has already passed
`get_product_risk(...)`, so it is the correct contract boundary.

Do not reload Risk inside the Market connector. The selected Risk date can differ
from the Open and Current dates because of readiness Age or Force Risk.

### 3.3 Pass the pair scope only for Commodity bulk

Add an optional internal keyword to `_load_product_market_open(...)` and
`_load_product_market_status(...)`:

```python
commodity_scope: tuple[tuple[str, str], ...] | None = None
```

When selecting the bulk argument, branch only on the two Commodity source types:

```python
if (
    bulk_connector is not None
    and spec.source_type in _COMMODITY_BULK_SOURCE_TYPES
    and commodity_scope is None
):
    raise ValueError("Commodity bulk connector requires exact Risk pairs")

bulk_scope = (
    commodity_scope
    if spec.source_type in _COMMODITY_BULK_SOURCE_TYPES
    else underlyings
)
```

For a Commodity bulk hook, require `commodity_scope` to be present. For FX Delta,
continue passing the unchanged `underlyings` tuple. The ordinary, non-bulk fallback
still needs `underlyings` and should remain unchanged.

Keep `_load_bulk_market_frame(...)`'s second positional argument as
`underlyings`. Its current quick contract check compares returned Underlying text
against that tuple. Pass the exact pairs only to the connector lambda:

```python
return self._load_bulk_market_frame(
    spec,
    underlyings,
    connector=bulk_connector,
    stage="market_open",
    label="Open",
    load_bulk=lambda: bulk_connector(
        open_date,
        bulk_scope,
        market_status=selected_status,
    ),
    circuit=circuit,
    budget=budget,
)
```

Make the same narrow change in `_load_product_market_status(...)`, using
`market_date`, its existing stage/label, and the same `bulk_scope`. If pair tuples
are passed as `_load_bulk_market_frame(...)`'s second argument, every returned
string Underlying will be rejected, so keep the two scopes in their stated places.

At each Open and Current call site, build and pass the scope:

```python
commodity_scope = (
    self._commodity_market_scope(spec, next_risk[source_type])
    if source_type in _COMMODITY_BULK_SOURCE_TYPES
    else None
)
```

Then pass `commodity_scope=commodity_scope` to the matching loader.

Base Risk tenor changes already put that product into the existing Open and
Current refresh sets. No new cache key, scope fingerprint, or invalidation system
is needed.

### 3.4 Reject an out-of-scope returned pair

The existing `_reject_unrequested_market_underlyings(...)` check is not enough for
Commodity because it cannot see an extra tenor under a valid Underlying.

Add:

```python
@staticmethod
def _reject_unrequested_commodity_market_pairs(
    spec: ProductSpec,
    frame: pd.DataFrame,
    requested: tuple[tuple[str, str], ...],
    *,
    label: str,
) -> None:
    columns = [UNDERLYING, *spec.tenor_columns]
    returned = set(frame.loc[:, columns].itertuples(index=False, name=None))
    extras = sorted(returned - set(requested))
    if extras:
        raise ValueError(
            f"{label} returned Commodity pairs outside validated Risk scope: "
            f"{extras[:5]}"
        )
```

Run this check after `get_product_market_open(...)` or
`get_product_market_status(...)`, because those normal validators have already
normalized and validated the returned identity columns.

At both call sites, run the exact-pair check only when that leg actually used its
Commodity bulk hook. This keeps removing the optional hook as a clean rollback to
the existing ordinary connector:

```python
if uses_bulk and commodity_scope is not None:
    self._reject_unrequested_commodity_market_pairs(
        spec,
        validated_open,
        commodity_scope,
        label=f"{spec.key} market open",
    )
```

Initialize `uses_bulk = False` before the Commodity-disabled branch so the value is
always defined. Use `validated_status` and the status label in the Current branch.

Keep the existing Underlying-only rejection for FX and the ordinary products.
Returning fewer pairs in either leg is valid. The existing merge copies Current to
Open when only Current exists, and Open to Current when only Open exists. A pair is
unavailable only when it is absent from both legs. None of these cases should be
changed to zero.

### 3.5 Keep supplemental Commodity scope fail-closed for now

The current Cross Gamma and New Trades scope helpers provide Underlyings but no
Commodity tenor. Today their fixture products are Credit-only, so this does not
affect the current result.

Add a guard after `supplemental_market_scope` is built:

```python
unsupported = {
    source_type
    for source_type in _COMMODITY_BULK_SOURCE_TYPES
    if supplemental_market_scope.get(source_type)
}
if unsupported:
    raise ValueError(
        "Supplemental Commodity market scope requires exact "
        "(Underlying, Tenor Swap) pairs"
    )
```

Do not guess a tenor and do not combine each supplemental Underlying with every
base-Risk tenor. If Commodity supplemental rows are required later, change those
source contracts to supply their own validated exact pairs.

## Step 4 — update the tests

Keep the test change focused on the contract and call count.

### `tests/s20_connectors.py`

Replace the FX-only registration assertion with assertions that:

- FX Delta still receives `tuple[str, ...]`;
- Commo Delta and Commo Vega register both bulk hooks;
- all other products still have no bulk hooks; and
- the fixture Commodity scope is derived as:

```python
pairs = tuple(
    risk[["Underlying", "Tenor Swap"]]
    .drop_duplicates(keep="first")
    .itertuples(index=False, name=None)
)
```

For each Commodity product, assert:

```text
414 Risk rows
9 unique Risk pairs
9 returned Open pairs
9 returned Current pairs
no 1Y returned
```

### `tests/s07_integration.py`

Add or update tests for these behaviours:

1. duplicate Risk rows across Portfolios collapse to one first-seen pair;
2. Commo Delta and Commo Vega each make one Open call and one Current call;
3. their ordinary per-Underlying hooks are not called when bulk is configured;
4. an empty validated Commodity Risk frame makes zero Commodity calls;
5. disabled Commodity quotes make zero Commodity calls;
6. enabling Commodity quotes makes one call per product per required leg;
7. either connector leg may return a subset of the requested pairs;
8. an extra tenor under a requested Underlying is rejected;
9. a crossed pair is rejected;
10. FX Delta still receives its old Underlying-only tuple;
11. nonempty Underlying-only supplemental Commodity scope fails closed;
12. a pair missing from one leg uses the existing other-leg continuity rule;
13. a pair missing from both legs remains unavailable; and
14. the manager accepts bulk hooks for the exact three allowed source types but
    still rejects one on `credit/delta`.

Compare old and new Commodity quotes and P&L only on the 9 requested Risk pairs.
Separately assert that the three market-only `1Y` rows are absent. Do not assert
12-row parity because that would contradict the new Risk-driven contract.

## What must remain unchanged

- FX Delta's public bulk signatures
- Risk date, Open date, and Current date ownership
- Live versus OFFICIAL resolution
- Commodity enabled/disabled behaviour
- the ordinary per-Underlying connector as a configuration rollback
- connector timeout, retry, circuit-breaker, and last-good handling
- Market validation and P&L formulas
- Quick Market and history formatting

A bulk operational failure must follow the existing failure path. Do not silently
retry every pair through the ordinary connector; that can turn one failed call into
many calls and recreate the original stall.

## Validation commands

Run the focused tests first:

```powershell
python -m pytest tests/s20_connectors.py tests/s07_integration.py -q
```

Then run the complete checks used by the repository:

```powershell
python -m ruff check .
python -m ruff format --check cube/domain/s02_products.py cube/services/s05_sources.py cube/services/s06_refresh.py tests/s20_connectors.py tests/s07_integration.py
python -m pytest -q
```

Useful final search:

```powershell
rg -n "commo/(delta|vega)|market_(open|status)_bulk|CommodityMarketScope" cube tests
```

## Definition of done

The implementation is complete when all of the following are true:

- FX Delta still receives one ordered Underlying tuple;
- Commo Delta and Commo Vega receive exact ordered Risk
  `(Underlying, Tenor Swap)` pairs;
- duplicate Portfolio positions do not duplicate request pairs;
- each Commodity product makes at most one call per refreshed Market leg;
- an unrequested or crossed Commodity pair fails validation;
- a one-leg-only pair uses the existing continuity rule;
- a pair absent from both legs remains unavailable rather than becoming zero;
- Commodity disabled mode makes no Commodity connector calls;
- current fixture MarketBooks contain 9 Risk-driven pairs per Commodity Greek and
  exclude the three market-only `1Y` rows;
- the focused and full test suites pass; and
- no new async, cache, UUID, or page logic has been introduced.

That is the complete change. The key is not merely adding Commodity names to the
existing FX allowlist: Commodity bulk must carry the exact Underlying-and-tenor
identity from validated Risk all the way to the source and back.
