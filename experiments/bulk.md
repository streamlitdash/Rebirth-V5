# Commodity bulk Market update — extend the existing FX Delta path

This is the implementation guide for the current Rebirth V5 code on branch **v4**. It explains how the existing FX Delta bulk Market path works and the smallest safe way to add the same capability to **Commo Delta** and **Commo Vega**.

This Markdown file is documentation only. Adding this file does not itself connect a production Commodity source or change runtime behaviour.

## Short answer

Most of the bulk system is already product-generic. Do not build a new refresh system, page callback, cache, UUID, thread pool, or `async` layer.

Make these five focused changes:

1. allow bulk hooks for exactly `fx/delta`, `commo/delta`, and `commo/vega` in `cube/services/s06_refresh.py`;
2. generalise the private FX CSV bulk helper in `cube/services/s05_sources.py` so it accepts a bound `source_type`;
3. add paired Open and Current bulk functions for both Commodity products and register them beside FX Delta;
4. keep the existing per-Underlying connectors as a configuration rollback, not automatic error failover; and
5. update the FX-only tests, then add Commodity toggle, contract, failure-isolation, and call-count tests.

The target is **one call per product per required market leg**:

```text
Commo Delta Open     -> one call for all requested Commo Delta Underlyings
Commo Delta Current  -> one call for all requested Commo Delta Underlyings
Commo Vega Open      -> one call for all requested Commo Vega Underlyings
Commo Vega Current   -> one call for all requested Commo Vega Underlyings
```

That is four Commodity calls when both legs need refreshing and both product scopes are nonempty. It is not one combined Delta-and-Vega call, and it is not four calls per Underlying.

Let `D` be the number of distinct Commo Delta Underlyings and `V` the number of distinct Commo Vega Underlyings:

The first two rows assume Commodity quotes are enabled and both product scopes are nonempty. Startup currently defaults Commodity quotes to disabled, which is the zero-call row.

| Refresh situation | Commodity calls now | Commodity calls after this change |
|---|---:|---:|
| Warm Recalculate, same date and status | `D + V` Current calls | `2` Current calls |
| Cold start, Reload All Risk, date change, or enabling Commodity quotes | `2D + 2V` Open/Current calls | `4` Open/Current calls |
| Commodity quotes disabled | `0` | `0` |

FX Delta keeps its existing one-call-per-leg behaviour. Other products keep their existing per-Underlying path.

## What “bulk” means in this application

Bulk changes only how one raw market leg is transported into the refresh manager. It does not change the data grain, calculations, page layout, MarketBook, history, or P&L formula.

The bulk result is logically the concatenation of the old per-Underlying results:

```text
old
  get_current(date, BRENT)  -> every BRENT tenor row
  get_current(date, GOLD)   -> every GOLD tenor row
  get_current(date, TTF)    -> every TTF tenor row
  concatenate

new
  get_current_bulk(date, (BRENT, GOLD, TTF))
    -> the same BRENT, GOLD, and TTF tenor rows in one DataFrame
```

Do not aggregate the rows. Do not remove `Tenor Swap`. Do not combine Delta and Vega. Do not calculate P&L in the connector.

## How the current FX Delta bulk chain works

### 1. The shared adapter contract already exists

`cube/domain/s02_products.py` defines this protocol:

```python
class ProductBulkMarketConnector(Protocol):
    def __call__(
        self,
        source_date: pd.Timestamp,
        underlyings: tuple[str, ...],
        *,
        market_status: str,
    ) -> pd.DataFrame: ...
```

`ProductConnectorAdapter` has five relevant fields:

```python
risk
market_open
market_status
market_open_bulk = None
market_status_bulk = None
```

The ordinary Open and Current hooks remain required even when the optional bulk hooks are installed. The manager prefers a matching bulk hook when it is non-`None`; otherwise it automatically uses the ordinary hook once per Underlying.

This is a **configuration fallback**, not an error fallback. Once a bulk hook is selected, a timeout or other failure does not retry the same leg through the per-Underlying hook. The manager applies the bulk failure policy described below.

### 2. Risk determines the requested scope

The manager first validates Risk for a `ProductSpec`. It then calls `_requested_market_underlyings(...)`, which produces an ordered, unique tuple of raw `Underlying` values from that validated Risk frame, followed by any valid supplemental Cross Gamma or New Trades identities.

For example:

```python
("BRENT", "GOLD", "TTF GAS")
```

This scope is not a set of tenor rows, Portfolio values, Groups, or Reported Underlyings. It is the exact raw Underlying scope owned by the refresh transaction.

### 3. The manager owns date and status

The connector must use the arguments it receives:

- Open receives the manager's T-1 business/checker date;
- Current receives the resolved Market Date;
- `market_status` is exactly `Live` or `OFFICIAL` and is resolved once by the manager; and
- an older Risk date caused by readiness Age or Force Risk must not replace either market date.

The connector must not call “today” again or independently decide Live versus OFFICIAL.

### 4. The manager chooses bulk before per-Underlying

`RiskRefreshManager._load_product_market_open(...)` checks `adapter.market_open_bulk`. `_load_product_market_status(...)` does the same for `market_status_bulk`.

When a hook exists, `_load_bulk_market_frame(...)` calls it once with the complete tuple. When it does not, `_load_market_frames(...)` calls the normal hook once for each Underlying.

There is no need for a new page callback or an `async def`. The current manager already owns the call deadline, total refresh budget, progress state, circuit breaker, and atomic commit.

### 5. Current FX fixture behaviour

`cube/services/s05_sources.py::_get_fx_delta_market_bulk(...)` currently:

1. validates the business date;
2. validates exact `Live`/`OFFICIAL` status;
3. requires an actual tuple containing unique, nonblank Underlyings;
4. reads the whole `fx/delta` CSV source partition once;
5. keeps only the requested Underlyings;
6. stable-sorts Underlyings into request order;
7. returns only the FX Delta market-leg columns; and
8. attaches `Market Status` to the Current leg.

Only two details make it FX-specific: `_source_spec("fx/delta")` is hardcoded, and only the two FX functions are registered in `_get_csv_product_connector_adapters()`.

### 6. The manager validates the result

The bulk loader and the normal loader meet at the same validators. The candidate must be a pandas `DataFrame`; the product validators then enforce:

- exact product identity;
- required tenor and value columns;
- nonblank canonical keys;
- finite numeric or genuinely blank quotes;
- non-negative integer tenor ranks;
- one row per canonical market key in each leg;
- exact Current `Market Status`; and
- no returned Underlying outside the transaction's requested scope.

Missing requested Underlyings are allowed and become unavailable market data. Extra Underlyings are a contract error.

### 7. Open and Current are merged as before

Validated Open and Current legs are outer-joined one-to-one on the ProductSpec market keys. The existing merge code:

- prefers Open's tenor rank when Open and Current disagree;
- deterministically resolves rank collisions;
- copies Current to Open when only Current exists;
- copies Open to Current when only Open exists;
- leaves both absent when neither exists; and
- derives Market availability, move, and then the product-specific P&L.

Bulk must not reproduce any of this logic.

### 8. The snapshot is still atomic

The manager builds the candidate MarketBook and P&L off to the side. It commits the new revision only after validation and release finish. A warm contract failure retains the last good revision.

Quick Market, Predict P&L, search, and the OFFICIAL Market history archive all consume the same committed MarketBook. They need no Commodity-bulk-specific code.

### 9. Recalculate usually needs only Current

On an already loaded, unchanged Market Date, Recalculate uses `force_pl=True`. That marks all Current market sources for refresh, but reuses committed Open legs. After this patch that means one Commo Delta Current call and one Commo Vega Current call, provided Commodity quotes are enabled.

Open is also refreshed on cold start, Reload All Risk, Market Date change, a changed Commodity-enabled state, or a changed product Risk date/scope.

### 10. Commodity quotes are deliberately opt-in

`commodity_market_enabled` defaults to `False`. While it is false, the manager bypasses both Commodity connectors and creates the existing zero quote legs with `Market Data Status = Commodity market disabled`.

When the user enables Commodity quotes, the setting change schedules both Open and Current for `commo/delta` and `commo/vega`. This toggle is also the fastest operational rollback if the new source misbehaves.

## The two blockers in current v4

Adding four functions alone will not work because there are two explicit FX-only restrictions:

1. `cube/services/s05_sources.py::_get_csv_product_connector_adapters()` registers bulk hooks only when `source_type == "fx/delta"`.
2. `cube/services/s06_refresh.py::RiskRefreshManager.__init__()` rejects any bulk hook outside `fx/delta`, so the application will fail during construction if a Commodity hook is registered first.

Both must change in the same commit.

## Exact Commodity contracts

Both Commodity products are one-axis curves, but their quote meanings and P&L formulas differ:

| Source Type | Product identity | Axis | Quote unit | Existing P&L move |
|---|---|---|---|---|
| `commo/delta` | Commo / Delta | `Tenor Swap` | outright | percentage |
| `commo/vega` | Commo / Vega | `Tenor Swap` | vol points | absolute |

The transport shape is the same, but never mix their rows.

### Open result

Return these exact normalized columns, in this order:

```text
Underlying
Tenor Swap
Tenor Swap Order
Open
```

### Current result

Return these exact normalized columns, in this order:

```text
Underlying
Tenor Swap
Tenor Swap Order
Current
Market Status
```

`Market Status` may technically be omitted because the validator can attach the manager's explicit status. Returning it with the exact passed value is easier to audit.

### Row rules

- Return every available tenor row for every requested raw Underlying.
- `(Underlying, Tenor Swap)` must be unique within each product leg.
- `Tenor Swap Order` must be a non-negative integer.
- Rank tenor labels within each raw Underlying. The same ranks may be reused for another Underlying.
- Preserve the source's real strip/contract order. Do not lexically sort labels such as `DEC26`, use one global DataFrame row number, or rank all Underlyings together.
- `Open` and `Current` must be finite numeric values or genuinely blank for an absent quote. A network error is not a blank quote.
- If `Risk Type` or `Risk Greek` is supplied, every row must exactly match `Commo` and the correct `Delta` or `Vega`. The simplest normalized result omits them and lets the ProductSpec attach them.
- Omit `Portfolio`, `Group`, `Reported Underlying`, `Source Type`, and connector-specific payload columns.
- Never turn missing data or an exception into zero inside the connector. The manager owns unavailable-data and disabled-Commodity behaviour.
- An empty DataFrame is valid only when it has the required columns and the source genuinely has no quotes for the requested scope.

## Files to change when implementing

| File | Required change |
|---|---|
| `cube/services/s06_refresh.py` | Permit exactly three bulk source types; make the bulk docstring product-neutral |
| `cube/services/s05_sources.py` | Generalise the private helper; add four public Commodity functions; register and export them |
| `cube/domain/s02_products.py` | Replace the stale “FX-Delta-only” adapter documentation |
| `tests/s20_connectors.py` | Assert the exact three registered bulk products and raw schemas |
| `tests/s07_integration.py` | Prove call preference, allowed sources, scope, gating, failures, and rollback |
| `tests/s10_reads.py` | Add a focused aggregate call-count assertion if refresh metrics are changed/tested |
| `README.md` | Replace the stale sentence saying only FX Delta can be bulk |

`cube/adapters/s05_commodities.py` is not the active site composition in this v4 code. It is a per-Underlying Commodity Delta example, and its retained source explicitly says the Vega implementation was not recovered. Editing only that file will not enable runtime Commodity bulk. Leave it as the fallback example for the smallest patch.

## Step-by-step implementation

### Step 0 — record the baseline

Before editing runtime code:

```powershell
git status --short --branch
python -m pytest tests/s20_connectors.py tests/s03_adapters.py -q
```

The current v4 baseline for those two files is 17 passing tests. At the time this guide was written, the full suite was 676 passing tests and `ruff check .` passed. `ruff format --check .` separately reported the pre-existing, unrelated `cube/domain/s04_crossgamma.py`; do not reformat that file as part of this focused patch unless it is separately in scope. If your checkout differs, resolve or record the baseline before attributing failures to the bulk change.

### Step 1 — extend the fail-closed manager permission

In `cube/services/s06_refresh.py`, add this beside the other module constants:

```python
_BULK_MARKET_SOURCE_TYPES = frozenset(
    {
        "fx/delta",
        "commo/delta",
        "commo/vega",
    }
)
```

In `RiskRefreshManager.__init__()`, replace:

```python
if source_type != "fx/delta" and any(bulk_hooks.values()):
    raise ValueError(
        "bulk market connector hooks are supported only for 'fx/delta'; "
        f"found bulk hook on {source_type!r}"
    )
```

with:

```python
if source_type not in _BULK_MARKET_SOURCE_TYPES and any(
    connector is not None for connector in bulk_hooks.values()
):
    raise ValueError(
        "bulk market connector hooks are supported only for "
        f"{sorted(_BULK_MARKET_SOURCE_TYPES)!r}; "
        f"found bulk hook on {source_type!r}"
    )
```

Also change `_load_bulk_market_frame()`'s docstring from “FX-Delta” to “one bulk connector for a complete product market leg.”

Why keep an allowlist instead of deleting the check entirely? The bulk machinery is generic, but the allowlist keeps construction fail-closed and catches an accidental bulk hook on Credit, IR, or a future product. Adding the two approved Commodity source types is only a tiny change and does not silently broaden policy.

### Step 2 — make the private fixture helper source-generic

In `cube/services/s05_sources.py`, replace `_get_fx_delta_market_bulk(...)` with the following helper:

```python
def _get_market_bulk(
    source_type: str,
    dataset: str,
    source_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    """Read one product source partition and preserve requested scope order."""

    if dataset not in {"market_open", "market_status"}:
        raise ValueError("dataset must be 'market_open' or 'market_status'")
    date_parameter = "open_date" if dataset == "market_open" else "market_date"
    _business_date(source_date, parameter=date_parameter)
    selected_status = _market_status(market_status)
    requested = _bulk_underlying_scope(underlyings)
    spec = _source_spec(source_type)
    value_column = OPEN if dataset == "market_open" else CURRENT
    output_columns = [
        UNDERLYING,
        *spec.tenor_columns,
        *spec.tenor_order_columns,
        value_column,
    ]
    frame = _source_rows(
        dataset,
        spec.source_type,
        output_columns,
        allow_empty=True,
    )
    requested_order = {
        underlying: index for index, underlying in enumerate(requested)
    }
    frame = frame.loc[frame[UNDERLYING].isin(requested)].copy()
    if not frame.empty:
        frame["__bulk_underlying_order"] = frame[UNDERLYING].map(requested_order)
        frame = (
            frame.sort_values("__bulk_underlying_order", kind="stable")
            .drop(columns="__bulk_underlying_order")
            .reset_index(drop=True)
        )
    _require_temp_notice(
        frame,
        [UNDERLYING, *spec.tenor_columns],
        dataset=dataset,
    )
    if dataset == "market_status":
        frame[MARKET_STATUS] = selected_status
    return frame
```

This is a fixture/source-partition helper, not a new manager. It preserves the existing FX behaviour while allowing the bound `ProductSpec` to supply the Commodity tenor columns.

### Step 3 — update FX wrappers and add four Commodity wrappers

Keep the public functions explicit. That makes progress logs, tests, and production replacement easier to understand than a closure or `partial` chain.

Change the two existing FX wrappers so they pass `"fx/delta"` into `_get_market_bulk(...)`, then add these four functions beside them:

```python
def get_commo_delta_market_open_bulk(
    open_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    """Return all requested Commodity Delta opening quotes in one source read."""

    return _get_market_bulk(
        "commo/delta",
        "market_open",
        open_date,
        underlyings,
        market_status=market_status,
    )


def get_commo_delta_market_status_bulk(
    market_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    """Return all requested Commodity Delta current quotes in one source read."""

    return _get_market_bulk(
        "commo/delta",
        "market_status",
        market_date,
        underlyings,
        market_status=market_status,
    )


def get_commo_vega_market_open_bulk(
    open_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    """Return all requested Commodity Vega opening quotes in one source read."""

    return _get_market_bulk(
        "commo/vega",
        "market_open",
        open_date,
        underlyings,
        market_status=market_status,
    )


def get_commo_vega_market_status_bulk(
    market_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    """Return all requested Commodity Vega current quotes in one source read."""

    return _get_market_bulk(
        "commo/vega",
        "market_status",
        market_date,
        underlyings,
        market_status=market_status,
    )
```

Update both FX wrappers explicitly so their existing public signatures remain unchanged:

```python
def get_fx_delta_market_open_bulk(
    open_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    return _get_market_bulk(
        "fx/delta",
        "market_open",
        open_date,
        underlyings,
        market_status=market_status,
    )


def get_fx_delta_market_status_bulk(
    market_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    return _get_market_bulk(
        "fx/delta",
        "market_status",
        market_date,
        underlyings,
        market_status=market_status,
    )
```

Finally, add all four Commodity names to `s05_sources.py::__all__`.

### Step 4 — register the paired hooks in one explicit map

Before `_get_csv_product_connector_adapters()`, add:

```python
_BULK_MARKET_HOOKS = {
    "fx/delta": (
        get_fx_delta_market_open_bulk,
        get_fx_delta_market_status_bulk,
    ),
    "commo/delta": (
        get_commo_delta_market_open_bulk,
        get_commo_delta_market_status_bulk,
    ),
    "commo/vega": (
        get_commo_vega_market_open_bulk,
        get_commo_vega_market_status_bulk,
    ),
}
```

Inside the adapter loop, immediately before constructing `ProductConnectorAdapter`, bind the pair:

```python
bulk_open, bulk_status = _BULK_MARKET_HOOKS.get(source_type, (None, None))
```

Then replace the FX-only conditional fields with:

```python
adapters[source_type] = ProductConnectorAdapter(
    risk=risk,
    market_open=market_open,
    market_status=market_status_connector,
    market_open_bulk=bulk_open,
    market_status_bulk=bulk_status,
)
```

Register both legs together. A one-leg hybrid is technically possible, but it is harder to reason about and test. Removing both fields later restores the per-Underlying fallback automatically.

### Step 5 — update the stale domain and README wording

In `cube/domain/s02_products.py`, replace the text saying bulk hooks are “FX-Delta-only” with text saying they are optional equivalents for explicitly permitted source types.

In `README.md`, update the paragraph that currently starts “FX Delta can instead supply...” so it names FX Delta, Commo Delta, and Commo Vega. The preceding circuit-breaker sentence is also stale in current v4: an ordinary Market connector outage now opens a source-local product circuit, while a refresh-budget or Market-status-resolver failure can stop the remaining Market batch. Correct that wording in the same documentation edit.

`FIX1.md` describes the historical FX-only rollout. Either leave it as a dated record and add a pointer to `experiments/bulk.md`, or label its FX-only statement as superseded. Do not silently rewrite historical rationale as though Commodity was present in the original patch.

## Replace the CSV body with a real production bulk query

The code shown above makes the checked-in CSV boundary bulk-capable. The repository does not contain the recovered production Commodity client or its real method name, so that one authorised source call cannot be named here.

The app-facing function signatures and DataFrame contracts above are exact. Replace only the source-specific read/normalisation inside the four public Commodity functions or their private provider. If the upstream response includes an as-of date, status, product, or Greek in its envelope, validate each against the exact arguments before projecting the DataFrame; never accept a stale or cross-product response merely because its columns fit.

The important rule is that a bulk hook must perform a real bulk source operation. The following parameterised shape covers both Commodity products and both legs. Only the authorised client call, response-envelope check, and vendor field names are source-specific:

```python
def _get_real_commo_market_bulk(
    source_type: str,
    dataset: str,
    source_date: pd.Timestamp,
    underlyings: tuple[str, ...],
    *,
    market_status: str,
) -> pd.DataFrame:
    greek_by_source = {
        "commo/delta": "Delta",
        "commo/vega": "Vega",
    }
    try:
        greek = greek_by_source[source_type]
    except KeyError as exc:
        raise ValueError(f"unsupported Commodity source {source_type!r}") from exc
    if dataset not in {"market_open", "market_status"}:
        raise ValueError("dataset must be 'market_open' or 'market_status'")

    date_parameter = "open_date" if dataset == "market_open" else "market_date"
    _business_date(source_date, parameter=date_parameter)
    selected_status = _market_status(market_status)
    requested = _bulk_underlying_scope(underlyings)
    value_column = OPEN if dataset == "market_open" else CURRENT
    quote_kind = "Open" if dataset == "market_open" else "Current"

    # Replace this one call and its field names with the authorised source API.
    # The native client must use finite timeouts shorter than the manager's wait.
    records = commodity_market_client.fetch_quotes(
        greek=greek,
        quote_kind=quote_kind,
        source_date=source_date,
        underlyings=requested,
        market_status=selected_status,
    )
    # If the response has envelope metadata, verify its date, status, and Greek
    # here before reading its records.
    frame = pd.DataFrame.from_records(records).rename(
        columns={
            "vendor_underlying": UNDERLYING,
            "vendor_tenor": "Tenor Swap",
            "vendor_tenor_rank": "Tenor Swap Order",
            "vendor_quote": value_column,
        }
    )
    output_columns = [
        UNDERLYING,
        "Tenor Swap",
        "Tenor Swap Order",
        value_column,
    ]
    missing = [column for column in output_columns if column not in frame]
    if missing:
        raise ValueError(f"{source_type} {dataset} is missing columns: {missing}")
    frame = frame.loc[:, output_columns].copy()
    normalized_underlying = frame[UNDERLYING].astype("string").str.strip()
    invalid_underlying = normalized_underlying.isna() | normalized_underlying.eq("")
    if invalid_underlying.any():
        raise ValueError(f"{source_type} {dataset} has blank Underlying values")
    frame[UNDERLYING] = normalized_underlying.astype(str)
    extras = sorted(set(frame[UNDERLYING]) - set(requested))
    if extras:
        raise ValueError(
            f"{source_type} {dataset} returned unrequested Underlyings: {extras[:5]}"
        )
    requested_order = {name: index for index, name in enumerate(requested)}
    if not frame.empty:
        frame["__bulk_underlying_order"] = frame[UNDERLYING].map(requested_order)
        frame = (
            frame.sort_values("__bulk_underlying_order", kind="stable")
            .drop(columns="__bulk_underlying_order")
            .reset_index(drop=True)
        )
    if dataset == "market_status":
        frame[MARKET_STATUS] = selected_status
    return frame
```

When replacing the fixture provider, each of the four public Commodity wrappers calls this provider with its fixed source and leg: `commo/delta` plus `market_open`, `commo/delta` plus `market_status`, `commo/vega` plus `market_open`, or `commo/vega` plus `market_status`. Therefore the Open wrapper passes `open_date`, the Current wrapper passes `market_date`, and Current always appends the exact `Market Status`.

The example assumes an endpoint scoped by the requested tuple and therefore rejects extra Underlyings. If the authorised endpoint is explicitly a whole-product snapshot, filter it to `requested` inside the connector before returning and log both fetched and returned row counts. In either case, no extra identity may cross the connector boundary into the manager.

For a database, use one parameterised query with the requested Underlyings, not string-built SQL. For a service that can return a complete dated product snapshot, make one snapshot request and project it to the requested scope.

Do **not** implement this:

```python
frames = [old_connector(date, name) for name in underlyings]
return pd.concat(frames)
```

That merely hides the same `N` network calls inside a function named “bulk”; it does not remove fan-out, timeouts, or source load.

If the upstream API has a hard page or request-size limit, the hook may have to page or chunk internally. Keep that work bounded and sequential first. It still has to finish inside the manager's deadline, and its logs must reveal the real upstream request/page count. Do not introduce concurrency until measurements prove it is needed.

If one upstream response contains both Delta and Vega, the simplest safe version is still to project a separate result in each product hook. Reusing one network response across both products requires a refresh-transaction-scoped snapshot or cache key containing date, status, product scope, and source revision. A permanent module-global DataFrame cache can leak stale or cross-date quotes and is not part of this patch.

## Timeouts and operational behaviour

The current manager defaults are:

```text
per connector wait       15 seconds
whole refresh call budget 120 seconds
market retries            0
per-Underlying workers    1
maximum outstanding calls 8
```

The manager's 15-second wait cannot kill Python I/O that ignores cancellation. Set finite connect/read/query timeouts in the native Commodity client so it returns before the manager's deadline. Bulk reduces the number of calls but makes each call carry a larger result, so project to the required rows and columns before returning.

Failure classes remain deliberately different:

- `TypeError` and `ValueError` mean a connector/contract bug. They reject the candidate refresh; on a warm refresh the last good revision remains active.
- timeout, connection, and other operational errors fail soft for that product. The manager opens that refresh's product circuit, returns a correctly shaped missing leg, records a bounded warning, and continues other products.
- an Open bulk operational failure prevents a second Current call for that same product in that refresh because its product circuit is already open. It must not stop the other Commodity product.

Do not catch all exceptions and return an empty frame inside the connector. That erases the distinction between “no quotes” and “the source broke.”

## Tests to change and add

### 1. Exact registration test

In `tests/s20_connectors.py`, replace `test_only_fx_delta_registers_bulk_market_hooks` with a test based on this exact map:

```python
expected = {
    "fx/delta": (
        sources.get_fx_delta_market_open_bulk,
        sources.get_fx_delta_market_status_bulk,
    ),
    "commo/delta": (
        sources.get_commo_delta_market_open_bulk,
        sources.get_commo_delta_market_status_bulk,
    ),
    "commo/vega": (
        sources.get_commo_vega_market_open_bulk,
        sources.get_commo_vega_market_status_bulk,
    ),
}
```

For every entry, assert that the adapter fields are those exact functions. Then assert every other registered source has both bulk fields set to `None`.

Invoke both hooks for all three products using the ordered unique Underlyings from that product's Risk frame. For each result assert:

```python
open_columns = [
    "Underlying",
    *spec.tenor_columns,
    *spec.tenor_order_columns,
    "Open",
]
current_columns = [
    "Underlying",
    *spec.tenor_columns,
    *spec.tenor_order_columns,
    "Current",
    "Market Status",
]
```

Also assert that `Underlying.drop_duplicates().tolist()` equals the requested tuple order and every Current row has the exact requested status.

### 2. Manager permission test

In `tests/s07_integration.py`, replace the FX-only rejection test with:

- positive construction cases for `fx/delta`, `commo/delta`, and `commo/vega`; and
- the retained negative case for `credit/delta`, matching “bulk market connector hooks are supported only for”.

This proves the new allowlist is exact rather than accidentally disabled or globally open.

### 3. One-call preference test

Parameterise the existing `test_fx_delta_bulk_connectors_are_called_once_per_leg` over:

```python
(
    ("fxdelta", "fx/delta"),
    ("commodelta", "commo/delta"),
    ("commovega", "commo/vega"),
)
```

For each case:

1. make the ordinary per-Underlying functions raise `AssertionError` if called;
2. make the bulk functions record the date, exact tuple, status, and leg;
3. return two tenor rows per Commodity Underlying, with valid per-Underlying ranks;
4. call `_load_product_market_open()` and `_load_product_market_status()`; and
5. assert exactly one Open and one Current bulk call and zero ordinary calls.

Do not test Commodity with only `Underlying` and a value. Both Commodity products require `Tenor Swap` and `Tenor Swap Order`.

### 4. Scope and schema tests

Run the normal product validators over Commodity bulk results and cover all of these failures:

- an unrequested Underlying;
- duplicate `(Underlying, Tenor Swap)` rows;
- missing `Tenor Swap`;
- missing, negative, fractional, or nonnumeric `Tenor Swap Order`;
- a nonnumeric or infinite quote;
- a Delta row returned by the Vega hook, or vice versa; and
- Current rows whose supplied `Market Status` differs from the argument.

Also test a correctly shaped empty result and a result missing one requested Underlying. Both are allowed and must become unavailable rather than zero.

### 5. Commodity toggle test

This test is essential because Commodity connectors are opt-in:

1. construct a manager with recording bulk hooks installed for both Commodity products;
2. refresh with `commodity_market_enabled=False`;
3. assert neither Commodity bulk function was called and the committed rows say `Commodity market disabled`;
4. refresh again with `commodity_market_enabled=True` and the expected revision;
5. assert exactly one Open and one Current call for each Commodity product; and
6. assert validated Commodity quotes and P&L are now used.

If this test forgets `commodity_market_enabled=True`, it can pass without ever exercising Commodity bulk.

### 6. Failure-isolation and last-good tests

Add these two cases:

- Commo Delta Open raises `TimeoutError`: it is called once, Commo Delta Current is skipped by that product circuit, its quote state is unavailable, and Commo Vega still gets one Open and one Current call.
- after a valid Commodity-enabled baseline, Commo Vega Current raises `ValueError`: the new candidate fails and the complete prior MarketBook/dashboard revision is retained.

These distinguish an operational outage from a broken financial contract.

### 7. Call-count and parity tests

For a warm unchanged Recalculate with Commodity enabled, use recording hooks to prove one Current call for each registered bulk product with nonempty scope. For a cold/full refresh, use those hooks to prove one call per required leg. The manager's completion metrics are aggregate across all products, so their expected total is the bulk calls plus the remaining products' per-Underlying calls; they cannot by themselves prove which product made each call. If operators require that breakdown, add the bounded per-source telemetry below.

Before switching a real feed, run the same dated snapshot through the old and new connectors and compare canonical rows after stable sorting by:

```text
Risk Type
Risk Greek
Underlying
Tenor Swap Order
Tenor Swap
```

Open, Current, Market Move, Market availability, and P&L must match. Only source call count and elapsed time should change.

## Logging to retain

The refresh manager already emits:

- product progress such as `Loading bulk Open` and `Loading bulk Live/OFFICIAL`;
- an internal call-gate key containing `market`, leg, source type, and `__bulk__` (it is not emitted as telemetry by default);
- bounded operational warnings; and
- completion metrics containing aggregate Market call counts, row counts, and stage durations.

At the real Commodity client boundary, add one bounded completion/failure event per bulk call with:

```text
source_type
stage (market_open or market_status)
market_status
requested_count
returned_rows
upstream_request_count
duration_ms
outcome
```

Do not log the entire Underlying tuple, DataFrame, quote values, raw payload, query text with parameters, credentials, or tokens.

## Validation commands

Run the narrow tests first:

```powershell
python -m pytest tests/s20_connectors.py -q
python -m pytest tests/s07_integration.py -q
python -m pytest tests/s04_market.py tests/s10_reads.py -q
python -m pytest tests/s03_adapters.py tests/s08_feeds.py -q
```

Then run repository checks. First check the files touched by this change:

```powershell
python -m ruff check .
python -m ruff format --check cube/domain/s02_products.py cube/services/s05_sources.py cube/services/s06_refresh.py tests/s07_integration.py tests/s20_connectors.py tests/s10_reads.py
python -m pytest -q
git diff --check
```

You may also run `python -m ruff format --check .`, but compare it with the recorded baseline: current v4 has unrelated formatting drift in `cube/domain/s04_crossgamma.py`.

## Manual smoke test

Use a controlled dated source snapshot and watch the terminal logs:

1. start with **Commodity quotes: Disabled** and load the app;
2. verify there are no Commo Delta/Vega source calls;
3. enable Commodity quotes;
4. verify one Delta Open, one Delta Current, one Vega Open, and one Vega Current call;
5. verify every requested Underlying and tenor appears once in its correct product;
6. verify Delta and Vega values have not been scaled, aggregated, or swapped;
7. click Recalculate without changing the date or status;
8. verify only one Current call per Commodity product, with no per-Underlying fan-out;
9. compare Quick Market and P&L with the pre-bulk dated baseline;
10. force one Commodity timeout and verify the other Commodity product still completes;
11. force one schema error and verify the prior revision stays visible; and
12. disable Commodity quotes and verify connector calls stop immediately on the next refresh transaction.

## Common wrong implementations

### Registering the functions before changing the manager gate

The app fails during `RiskRefreshManager` construction because current v4 permits only FX Delta.

### Editing only `cube/adapters/s05_commodities.py`

Nothing changes in the running site because current production composition comes from `cube/services/s05_sources.py::get_product_connector_adapters()`.

### Looping over the old connector inside the bulk hook

The manager reports one bulk call, but the source still receives `N` calls. Latency and timeout risk remain.

### Combining Delta and Vega rows

The products have different identities, quote meanings, and P&L formulas. Mixed rows either fail validation or, if mislabeled, produce incorrect P&L.

### Returning only one row per Underlying

Commodity Market is a tenor curve. Collapsing the curve destroys the join grain and loses Risk rows.

### Deriving tenor order from global row position

The second Underlying starts at the wrong rank and later Open/Current merges can conflict. Rank within each raw Underlying using source authority.

### Enabling bulk but leaving Commodity disabled in tests

The manager deliberately bypasses every Commodity connector, so the test does not exercise the new code.

### Swallowing a network error as an empty DataFrame

Operators see “no data” instead of an outage, failure isolation is not exercised, and the last-good policy cannot classify the event correctly.

### Adding `async` or increasing workers first

The existing manager already owns deadlines and a bounded call gate. True bulk removes the fan-out directly. Extra concurrency adds ordering, cancellation, and lingering-I/O failure modes without fixing a connector that still makes one request per Underlying.

## Rollback

There are two safe rollback levels:

1. **Immediate operations:** set **Commodity quotes** to Disabled. The manager bypasses both Commodity sources while Risk remains available.
2. **Code fallback:** remove both bulk hook registrations for the affected Commodity source, leaving its required `market_open` and `market_status` hooks unchanged. The manager automatically returns to the existing per-Underlying path.

Remove Open and Current bulk hooks as a pair unless a one-leg rollout has its own explicit tests.

## Definition of done

- Exactly `fx/delta`, `commo/delta`, and `commo/vega` have paired bulk hooks.
- The app constructs successfully; a bulk hook on `credit/delta` is still rejected.
- Commodity-disabled refreshes make zero Commodity connector calls.
- Enabling Commodity calls each product exactly once per leg.
- Warm Recalculate calls each Commodity Current hook once and reuses Open.
- Bulk results preserve the complete `(Underlying, Tenor Swap)` grain and source tenor order.
- Delta and Vega remain separate and produce identical MarketBook/P&L rows to the old dated baseline.
- Extra scope, duplicate keys, bad ranks, bad quotes, and wrong status fail validation.
- Operational failure in one Commodity product does not stop the other.
- A warm contract failure retains the complete last-good revision.
- Per-source client logs show bounded call count, row count, duration, and outcome.
- Focused tests, the full suite, Ruff, changed-file formatting, and `git diff --check` pass; any unrelated full-tree formatting baseline is recorded separately.
