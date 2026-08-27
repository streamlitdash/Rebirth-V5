# Fix 17 — Load dated reduced-tenor matrices with Risk

**Status:** Implemented on the `v4` branch.

This change lets one product Risk adapter return both:

1. the normal full-tenor Risk DataFrame; and
2. a secondary collection of reduced-tenor matrices loaded for the exact same
   Risk Date.

It does not add a matrix request when the user clicks Reduced Tenor. The click
uses the matrix book already committed in server memory. Existing adapters
which return only a DataFrame continue to work.

## Resulting flow

```text
adapter.risk(risk_date)
  -> one Risk response plus its same-date matrix secondary file
  -> validate the Risk frame
  -> match s11_matrix.csv by Risk Type + Risk Greek + raw Underlying
  -> deduplicate MatrixName
  -> validate only the required matrices
  -> commit Risk, Risk Date and matrices in one revision

Reduced Tenor click
  -> read the small committed matrix book from memory once per revision
  -> reduce and cache once per revision + active Risk Type
  -> later Full/Reduced switches reuse the cached result
```

There is no Portfolio-row matrix loop. Catalogue matching uses distinct raw
Underlyings, and several Underlyings may share one MatrixName.

## Files changed

Runtime files:

```text
cube/domain/s02_products.py
cube/domain/s11_tenorreduction.py
cube/services/s01_snapshots.py
cube/services/s02_state.py
cube/services/s05_sources.py
cube/services/s06_refresh.py
cube/services/s07_tenorreduction.py
cube/app/s02_contracts.py
cube/pages/risk/s02_state.py
```

Regression tests:

```text
tests/s07_integration.py
tests/s19_riskfilters.py
tests/s20_connectors.py
tests/s43_reducedtenor.py
```

No callback, layout, JavaScript, CSS, P&L formula, market connector, or Credit
reduction rule was changed.

## Step-by-step manual implementation

### 1. Add the adapter result type

In `cube/domain/s02_products.py`, immediately before
`ProductConnectorAdapter`, add:

```python
@dataclass(frozen=True)
class ProductRiskBundle:
    """One dated adapter response containing Risk and optional tenor matrices."""

    risk: pd.DataFrame
    matrices: Mapping[str, pd.DataFrame]


ProductRiskResult = pd.DataFrame | ProductRiskBundle
```

Change the `risk` field in `ProductConnectorAdapter` from:

```python
risk: Callable[[pd.Timestamp], pd.DataFrame]
```

to:

```python
risk: Callable[[pd.Timestamp], ProductRiskResult]
```

This is backward compatible:

```python
# Still valid
def risk(risk_date: pd.Timestamp) -> pd.DataFrame:
    ...
```

```python
# New dated-matrix form
def risk(risk_date: pd.Timestamp) -> ProductRiskBundle:
    ...
```

Do not return an unnamed tuple. The named bundle prevents Risk and matrices
from being accidentally swapped.

### 2. Add the exact catalogue selector

In `cube/domain/s11_tenorreduction.py`:

1. import `Collection`, `Mapping`, and `ProductSpec`;
2. add `required_reduction_matrix_names()` after
   `load_reduced_tenor_catalog()`; and
3. export it in `__all__`.

The helper is:

```python
def required_reduction_matrix_names(
    catalog: pd.DataFrame,
    spec: ProductSpec,
    risk: pd.DataFrame,
) -> tuple[str, ...]:
    if spec.source_type in CREDIT_REDUCTION_SOURCE_TYPES:
        return ()

    active_underlyings = risk[UNDERLYING].drop_duplicates()
    selected = catalog.loc[
        catalog[RISK_TYPE].eq(spec.risk_type)
        & catalog[RISK_GREEK].eq(spec.risk_greek)
        & catalog[UNDERLYING].isin(active_underlyings)
    ]
    return tuple(selected[MATRIX_NAME].drop_duplicates().tolist())
```

It does not validate the same inputs again. The manager calls it only after the
catalogue and product Risk frame have passed their existing validators.

Example:

```text
s11 rows:
IR,Delta,USD SOFR,IR_STANDARD
IR,Delta,EUR ESTR,IR_STANDARD
IR,Delta,GBP SONIA,IR_STANDARD

active Risk Underlyings:
USD SOFR, EUR ESTR

required result:
("IR_STANDARD",)
```

The shared name is processed once even if many Portfolios contain those
Underlyings.

### 3. Allow the reducer to use committed matrices

In `ReducedTenorReducer.reduce()` add these keyword arguments:

```python
committed_matrices: Mapping[tuple[str, str], pd.DataFrame] | None = None,
authoritative_source_types: Collection[str] = (),
```

In the non-Credit branch, replace the unconditional provider lookup with:

```python
if source_type in authoritative_sources:
    matrix = (committed_matrices or {}).get((source_type, matrix_name))
else:
    matrix = self._matrix(matrix_name)
```

Keep the Credit branch unchanged. Credit still uses:

```python
self._credit_mapping("CREDIT_STANDARD")
```

The `authoritative_source_types` set matters. If a live bundle omitted or
failed to parse a required matrix, that Underlying must remain at full tenor.
It must not silently use a temporary hard-coded matrix. A source which still
returns only a DataFrame retains the old provider behavior.

The committed key is:

```python
(source_type, matrix_name)
```

Using Source Type avoids collisions if two products use the same MatrixName.
A date is not required in this key because the complete source matrix set is
replaced whenever that source's Risk Date changes.

### 4. Add the revision-bound matrix read model

In `cube/services/s01_snapshots.py`, after `FrameRead`, add:

```python
@dataclass(frozen=True)
class ReductionMatrixRead:
    revision: int
    matrices: dict[tuple[str, str], pd.DataFrame]
    authoritative_source_types: frozenset[str]
```

This is separate from `RefreshSnapshot`, so normal snapshot reads do not copy
all matrices.

### 5. Add the matching app protocol

In `cube/app/s02_contracts.py` add `ReductionMatrixReadProtocol` with:

```python
revision: int
matrices: Mapping[tuple[str, str], pd.DataFrame]
authoritative_source_types: frozenset[str]
```

Add this method to `RefreshManagerProtocol`:

```python
def read_reduction_matrices(self) -> ReductionMatrixReadProtocol: ...
```

Also add `ReductionMatrixReadProtocol` to `__all__`.

### 6. Publish and read matrices atomically

In `cube/services/s02_state.py`:

1. import `ReductionMatrixRead`;
2. add `read_reduction_matrices()` beside `read_frame()`; and
3. add the matrix dictionary and source set to `_commit_full_snapshot()`.

The read method captures the revision and matrices under the existing short
state lock, and gives every caller its own DataFrame copies:

```python
def read_reduction_matrices(self) -> ReductionMatrixRead:
    with self._state_lock:
        revision = self._snapshot.revision
        matrices = {
            key: frame.copy(deep=True)
            for key, frame in self._reduction_matrices.items()
        }
        source_types = frozenset(self._reduction_matrix_source_types)
    return ReductionMatrixRead(
        revision=revision,
        matrices=matrices,
        authoritative_source_types=source_types,
    )
```

Inside `_commit_full_snapshot()`, assign:

```python
self._reduction_matrices = reduction_matrices
self._reduction_matrix_source_types = reduction_matrix_source_types
```

These assignments stay in the same lock block as Risk frames, Risk Dates and
the new snapshot revision. A reader can therefore never see new Risk with old
matrices.

### 7. Teach the refresh manager about bundles

In `cube/services/s06_refresh.py`:

1. import `ProductRiskBundle`, `ProductRiskResult`, the catalogue types and the
   matrix validators;
2. add optional `reduced_tenor_catalog` to `RiskRefreshManager.__init__`;
3. keep the catalogue source lazy;
4. initialize the two matrix state fields;
5. change `_load_product_risk()` to return `ProductRiskResult`;
6. unpack a bundle only after the connector call returns;
7. validate Risk with the existing `get_product_risk()` first;
8. select and validate only required matrices; and
9. pass the matrix state through both full commit call sites.

The new manager state is:

```python
self._reduction_matrices: dict[tuple[str, str], pd.DataFrame] = {}
self._reduction_matrix_source_types: set[str] = set()
```

At the beginning of a refresh, copy the committed values beside the existing
Risk-frame state. Before loading changed sources, remove only their old matrix
entries:

```python
next_reduction_matrices = {
    key: matrix
    for key, matrix in base_reduction_matrices.items()
    if key[0] not in changed_source_types
}
next_reduction_matrix_source_types = (
    base_reduction_matrix_source_types - changed_source_types
)
```

After the existing Risk connector call:

```python
if isinstance(risk_result, ProductRiskBundle):
    raw_risk = risk_result.risk
    raw_matrices = risk_result.matrices
else:
    raw_risk = risk_result
    raw_matrices = None

validated_risk = get_product_risk(spec, risk_date, raw_risk)
next_risk[source_type] = validated_risk

if isinstance(risk_result, ProductRiskBundle):
    next_reduction_matrix_source_types.add(source_type)
    next_reduction_matrices.update(
        self._validated_bundle_matrices(
            spec,
            validated_risk,
            raw_matrices,
            product_label=product_label,
        )
    )
```

`_validated_bundle_matrices()` does four small operations:

```text
load s11 lazily
-> find distinct required names
-> ignore extra returned names
-> validate and store each required matrix
```

If one matrix is missing or malformed, it logs an App Logs/terminal incident,
skips only that matrix, and continues. The valid Risk frame and every other
matrix remain available.

Lifecycle behavior:

```text
Risk source unchanged      -> reuse its matrix set
P&L-only refresh           -> reuse all matrix sets
Portfolio-only refresh     -> reuse all matrix sets
Risk source/date changed   -> replace only that source's matrix set
force_risk=True            -> reload all source matrix sets
Risk connector fails       -> existing fail-soft empty Risk behavior continues
later transaction fails    -> last committed Risk and matrices remain together
```

### 8. Return a bundle from the active fixture adapter

In `cube/services/s07_tenorreduction.py`, add:

```python
def get_reduced_tenor_matrix_bundle() -> dict[str, pd.DataFrame]:
    return {
        matrix_name: matrix.copy()
        for matrix_name, matrix in _TEMP_REDUCTION_MATRICES.items()
    }
```

This is only the local fixture's equivalent of one secondary matrix file. It
does not perform network calls.

In `cube/services/s05_sources.py`, change the bound Risk adapter to:

```python
def risk(risk_date: pd.Timestamp, *, _source: str = source_type) -> ProductRiskBundle:
    return ProductRiskBundle(
        risk=get_risk(risk_date, _source),
        matrices=get_reduced_tenor_matrix_bundle(),
    )
```

Pass the same catalogue source into the manager:

```python
RiskRefreshManager(
    ...,
    connector_adapters=get_product_connector_adapters(),
    reduced_tenor_catalog=get_reduced_tenor_catalog_source(),
)
```

The manager retains only catalogue names matching that validated product and
its active raw Underlyings. The fixture secondary file is tiny and local.

### 9. Read the matrix book once per UI revision

In `cube/pages/risk/s02_state.py`, add three small fields to `_RiskDataCache`:

```python
self._reduction_matrix_revision: int | None = None
self._reduction_matrices: Mapping[tuple[str, str], pd.DataFrame] | None = None
self._reduction_matrix_source_types: frozenset[str] = frozenset()
```

Clear these fields in `replace_frame()` when a new dashboard revision is
published.

Add `_reduction_matrices_for_revision()`. It:

1. returns the already-read in-memory matrix book for the current revision;
2. otherwise calls `manager.read_reduction_matrices()` once;
3. checks that its revision equals the dashboard revision; and
4. returns `None` on a race so the existing filter loop restarts on the newer
   revision.

In `_reduce_filtered()`, convert the prepared frame to canonical columns once,
read the matrix book only if a non-Credit reducible source is present, and call:

```python
reducer.reduce(
    canonical_reducible,
    market_frame=market_quotes,
    committed_matrices=committed_matrices,
    authoritative_source_types=authoritative_source_types,
)
```

Full Tenor performs no matrix read. Credit-only Reduced Tenor keeps the shared
Credit map-and-sum route and does not read the non-Credit matrix book.

The existing V3 reduced-book cache remains:

```python
(revision, active_risk_type)
```

Therefore the first Reduced click per revision/Risk Type calculates once;
later switches and filters reuse it.

## How to connect the real Risk service

Do not create 30 `if underlying == ...` branches. Do not call the network once
per Portfolio, Risk row, or matrix name.

### Preferred: Risk and matrices in one upstream response

Replace one product's existing Risk function in the adapter file:

```python
import logging

from cube.domain.s02_products import ProductRiskBundle

_LOG = logging.getLogger(__name__)


def get_ir_delta_risk(risk_date: pd.Timestamp) -> ProductRiskBundle:
    response = real_client.get_risk_package(risk_date=risk_date)

    risk_frame = parse_risk_file(response.risk_file)
    try:
        matrix_frames = parse_matrix_secondary_file(response.matrix_file)
    except Exception:
        _LOG.exception("IR Delta reduced-tenor matrix file failed")
        matrix_frames = {}

    return ProductRiskBundle(
        risk=risk_frame,
        matrices=matrix_frames,
    )
```

`parse_matrix_secondary_file()` must return:

```python
{
    "IR_DELTA_STANDARD": ir_matrix_dataframe,
    "ANOTHER_MATRIX": another_matrix_dataframe,
}
```

Each matrix DataFrame must have:

```text
index   = new reduced tenor labels
columns = old full tenor labels
values  = finite numeric weights
```

Example:

```python
pd.DataFrame(
    [[1.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    index=["2Y", "5Y"],
    columns=["1Y", "2Y", "5Y"],
)
```

Register this function exactly where the old Risk function was registered:

```python
adapters["ir/delta"] = ProductConnectorAdapter(
    risk=get_ir_delta_risk,
    market_open=get_ir_delta_market_open,
    market_status=get_ir_delta_market_status,
)
```

You do not call `get_ir_delta_risk()` a second time. The adapter registry holds
the function and the refresh manager calls it with the resolved Risk Date.

Keep the `try` block around only the optional matrix extraction/parsing. This is
important: if matrix parsing raises before the adapter returns its bundle, the
refresh manager cannot preserve the already-valid Risk frame. Returning an
empty matrix mapping keeps Risk available. The manager then records a
missing-matrix incident for each required `s11_matrix.csv` name and leaves only
those batches at full tenor. Do not retry the Risk call merely because its
optional matrix file is malformed.

### Acceptable alternative: one Risk call plus one bulk matrix call

If the upstream API cannot return a secondary file with Risk, use:

```text
one Risk call for the product/date
plus
one bulk matrix call for distinct required MatrixNames and the same date
```

Apply the same small `try`/`except` around that one optional bulk matrix call.
On failure, log the exception and return the valid Risk with `matrices={}`.

Do not make 30 separate matrix network calls. If the upstream service can only
serve one matrix per request, that client limitation should be fixed or given a
bulk wrapper before enabling it during cold start.

## `s11_matrix.csv`

Keep exactly these columns and order:

```csv
Risk Type,Risk Greek,Underlying,MatrixName
```

`Underlying` means raw connector `Underlying`, not `Reported Underlying`.

Example:

```csv
Risk Type,Risk Greek,Underlying,MatrixName
IR,Delta,USD SOFR,IR_DELTA_STANDARD
IR,Delta,EUR ESTR,IR_DELTA_STANDARD
FX,Vega,EUR/USD Vol,FX_VEGA_STANDARD
```

Underlyings absent from the validated product Risk response are ignored for
that refresh. Underlyings with no catalogue row remain full tenor without a UI
marker.

Credit remains separate. All one-axis Credit sources continue to use the
single 15-to-5 `CREDIT_STANDARD` full-tenor-to-reduced-tenor mapping and sum
Risk, dRisk and P&L. Credit does not need rows in `s11_matrix.csv`.

## Failure behavior

```text
one missing matrix
  -> incident appears in App Logs/terminal
  -> affected batch remains full tenor
  -> other matrices still reduce
  -> Risk remains available
  -> next products continue

one malformed matrix
  -> same behavior

whole Risk connector failure
  -> existing shaped-empty Risk handling remains
  -> later products continue according to the existing Risk failure policy
```

There is no fallback from a failed live bundled matrix to temporary matrix
data. That would conceal the failure and could apply the wrong date.

## Validation performed

Focused tests cover:

- the same resolved Risk Date producing Risk and its dated matrix bundle;
- only catalogue-relevant matrices being committed;
- shared MatrixName values stored once per source;
- P&L-only and Portfolio-only matrix reuse;
- source-date changes replacing only that source's matrices;
- defensive reads;
- one missing authoritative matrix leaving only its batch full tenor;
- legacy DataFrame adapters retaining the old provider behavior;
- Credit retaining automatic map-and-sum; and
- repeated Reduced clicks performing no provider or connector calls.

Run the focused checks:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest `
    tests\s07_integration.py `
    tests\s19_riskfilters.py `
    tests\s20_connectors.py `
    tests\s43_reducedtenor.py `
    tests\s44_tenorreductionsource.py -q
```

Run code quality checks:

```powershell
& '.\.venv\Scripts\python.exe' -m ruff check cube tests
& '.\.venv\Scripts\python.exe' -m ruff format --check cube tests
git diff --check
```
