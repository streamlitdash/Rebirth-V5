# Fix 22 — Rebuild and verify the current reduced-tenor matrix chain

**Status:** Audit and implementation guide for `v4` at
`3d702eb6d29ee40a745eda61015ebb7f6e5473f6`. Adding this document does not
change runtime behavior.

This guide consolidates the latest reduced-tenor design. The current behavior
is not the design from any one older experiment. It is the combination of:

```text
1c3fbfc  automatic shared Credit mapping
8f65a11  one reduced book per revision and Risk Type
ea3341f  dated non-Credit matrices committed with Risk
```

If an implementation stopped after one of the earlier versions, it can look
mostly correct while still using the wrong matrix authority, recomputing on
every filter, or requiring obsolete Credit catalogue rows.

## Short answer

The current intended chain is:

```text
REFRESH
resolved source Risk Date
  -> adapter.risk(risk_date)
  -> full-tenor Risk plus same-date non-Credit matrix bundle
  -> validate Risk
  -> select required MatrixNames from s11_matrix.csv
  -> validate only those matrices
  -> calculate full-tenor market/P&L
  -> atomically commit Risk, Risk Date, MarketBook, P&L and matrices

RISK EXPLORER
Reduced tenor selected
  -> read the committed dashboard revision
  -> read exact full-tenor market quotes for that revision
  -> read the committed non-Credit matrix book for that revision
  -> build one reduced book for (revision, active Risk Type)
  -> apply IR family, Split and reporting filters
  -> apply an explicit manual promotion generation, if any
  -> apply the selected Credit display measure
  -> render table and detail
```

Credit is deliberately different:

```text
every one-axis Credit source
  -> ignore s11_matrix.csv
  -> use one provider-owned CREDIT_STANDARD mapping
  -> map Full Tenor to Reduced Tenor
  -> sum every additive measure within the existing position
```

The numeric matrix is a post-P&L presentation transform. It is not a market
quote transform and it is not part of the full-tenor P&L calculation.

## The two authorities must not be mixed

| Contract | Non-Credit | Credit |
|---|---|---|
| Eligibility | Exact one-axis `Tenor Swap` product plus catalogue match | Every registered one-axis Credit product |
| Selector | `s11_matrix.csv` exact Risk Type + Risk Greek + raw Underlying | No catalogue row |
| Definition | Numeric matrix | Ordered two-column mapping |
| Shape | Rows = reduced tenors; columns = full tenors | `Full Tenor`, `Reduced Tenor` |
| Data authority | Same source Risk Date as `ProductRiskBundle.risk` | Provider/code-owned `CREDIT_STANDARD` |
| Committed key | `(source_type, MatrixName)` | Not stored in the dated matrix book |
| Calculation | `new = matrix @ old` for every additive vector | Map and sum by reduced label |
| Missing definition | Keep the whole affected batch at full tenor | Keep the whole affected batch at full tenor |
| Market values | Exact output-label lookup only | Exact output-label lookup only |

The application-level `matrix_provider` remains necessary for Credit and for a
legacy adapter which returns only a DataFrame. It must not override a missing
matrix from a source which returned a `ProductRiskBundle`.

## How the design reached its current state

### Initial V5 — `e7c1685`

The initial design had catalogue-selected non-Credit matrices. They were
loaded through the provider on the first Reduced click and reduction happened
after the current filters. Different filter combinations could therefore run
the expensive calculation again. The provider cache was process-owned rather
than Risk-Date-owned.

### First Credit version — `61e980f` — now obsolete

The first Credit implementation added a direct mapping, but required a
`CREDIT_STANDARD` row in `s11_matrix.csv` for every Credit Underlying. Do not
copy that version.

### Current Credit semantics — `1c3fbfc`

Every one-axis Credit source and raw Underlying now selects
`CREDIT_STANDARD` automatically. Credit rows were removed from
`s11_matrix.csv`, the non-Credit catalogue became lazy for a Credit-only UI
request, and quote compaction was expanded to all reducible source types.

### Current cache semantics — `8f65a11`

Reduction moved before session filters and manual promotion. The canonical
reduced book is now cached by:

```python
(revision, active_risk_type)
```

This is why changing Activity, Signoff Group, Category, Sub Category, Split or
include/exclude should not rerun tenor reduction for the same revision and
Risk Type.

### Current non-Credit authority — `ea3341f`

The product Risk adapter can now return `ProductRiskBundle(risk, matrices)`.
The matrices use the exact same source Risk Date, are validated during the
refresh, and are committed atomically with Risk. A Reduced click reads the
small committed matrix book from memory; it makes no matrix connector call.

Fix 17 is the final authority for dated non-Credit matrices. The later T-1
supplemental-data change does not alter ordinary product Risk Dates or matrix
dates.

## Step-by-step implementation

### 1. Decide whether the product is actually reducible

The engine only accepts products whose registered axes are exactly:

```python
(Tenor Swap,)
```

Scalar products and two-axis surfaces pass through. Current one-axis source
types include IR Delta/Gamma/XCCY/Inflation/Basis/Bond, FX Vega, Commodity
Delta/Vega, and Credit Delta/Vega. A non-Credit source still needs an exact
catalogue row; eligibility alone does not reduce it.

Do not try to force a scalar or surface product into `s11_matrix.csv`. The
catalogue validator rejects an ineligible Risk Type/Greek pair.

### 2. Treat `s11_matrix.csv` as a selector, not as matrix data

File:

```text
data/s11_matrix.csv
```

It must contain exactly these columns in this order:

```csv
Risk Type,Risk Greek,Underlying,MatrixName
```

Example production rows:

```csv
Risk Type,Risk Greek,Underlying,MatrixName
IR,Delta,USD SOFR,IR_DELTA_STANDARD
IR,Delta,EUR ESTR,IR_DELTA_STANDARD
FX,Vega,EUR/USD Vol,FX_VEGA_STANDARD
```

Rules:

- `Underlying` is the exact raw connector `Underlying`, not Reported
  Underlying or Display Bucket;
- matching is case-sensitive after surrounding whitespace is stripped;
- `(Risk Type, Risk Greek, Underlying)` must be unique;
- several Underlyings may share one `MatrixName`;
- there are no Credit rows in the current design; and
- the file contains no matrix weights.

The Statics page exposes this file read-only. Replace it through the deployment
or governed source, then restart the process. Clear Cache does not reload the
reducer's already-cached catalogue.

### 3. Build the non-Credit matrix in the correct orientation

The required orientation is:

```text
index   = new/reduced Tenor Swap labels
columns = old/full Tenor Swap labels
cells   = finite numeric weights
```

For example:

```python
pd.DataFrame(
    [
        [1.0, 1.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 1.0],
    ],
    index=["1Y", "5Y", "10Y"],
    columns=["6M", "1Y", "2Y", "5Y", "10Y"],
)
```

For one position and one measure, the calculation is:

```text
new[n] = sum(matrix[n, old] * full[old])
```

The reducer implements this as `matrix @ full_vector`; do not transpose it.
The matrix row order becomes `Tenor Swap Order = 0, 1, ...`.

The validator enforces nonblank unique axes and finite numeric cells. It does
not enforce the business meaning of the weights. For a pure rebucketing which
must preserve the total, each full-tenor column should normally sum to `1.0`.
Rows do not need to sum to one. If rows are normalized instead of columns, the
book can shrink or grow even though validation passes.

Every actual full-tenor label in a mapped source/Underlying batch must appear
among the matrix columns. One missing label leaves that entire batch at full
tenor. A CSV parser will usually need to set the label column as the DataFrame
index explicitly:

```python
raw = pd.read_csv(matrix_file)
matrix = raw.set_index("Reduced Tenor")
matrix.index.name = None
```

### 4. Return Risk and dated matrices from the same product adapter

Core contract:

```text
cube/domain/s02_products.py::ProductRiskBundle
cube/domain/s02_products.py::ProductConnectorAdapter
```

The production pattern is:

```python
from cube.domain.s02_products import ProductRiskBundle


def get_ir_delta_risk(risk_date: pd.Timestamp) -> ProductRiskBundle:
    response = client.get_risk_package(risk_date=risk_date)
    risk = parse_risk_file(response.risk_file)

    try:
        matrices = parse_matrix_secondary_file(response.matrix_file)
    except Exception:
        logger.exception("IR Delta reduced-tenor matrix file failed")
        matrices = {}

    return ProductRiskBundle(risk=risk, matrices=matrices)
```

The adapter's `matrices` mapping is keyed by the bare catalogue name:

```python
{
    "IR_DELTA_STANDARD": ir_delta_matrix,
    "ANOTHER_MATRIX": another_matrix,
}
```

Do not return `(source_type, MatrixName)` keys from the adapter. The refresh
manager adds `source_type` when it commits the book.

Use the exact `risk_date` supplied to `adapter.risk()`. Do not use Market Date,
checker date, today's date, or a second independently resolved date. Prefer one
Risk package response. One Risk call plus one same-date bulk matrix call is an
acceptable fallback. Do not call once per Portfolio, Underlying, row, or
MatrixName.

Keep optional matrix parsing inside its own `try` block. A malformed optional
matrix must not discard otherwise valid Risk or cause the Risk connector to be
retried.

Only adapters which actually own dated non-Credit matrices need to return a
bundle. Other production adapters can continue to return a DataFrame. The
fixture currently wraps every product in a bundle for convenience; copying
that blanket wrapper into a real connector layer creates unnecessary matrix
work during refresh.

### 5. Keep the refresh manager's exact selection and authority rules

Relevant symbols:

```text
cube/domain/s11_tenorreduction.py::required_reduction_matrix_names
cube/services/s06_refresh.py::_validated_bundle_matrices
cube/services/s06_refresh.py::RiskRefreshManager.refresh
```

After Risk validation, the manager must:

```text
load the catalogue lazily
  -> select exact Risk Type + Risk Greek
  -> intersect exact raw Underlyings present in validated Risk
  -> deduplicate MatrixName
  -> ignore extra returned matrix names
  -> validate each required matrix independently
  -> store valid matrices under (source_type, MatrixName)
```

Mark the source type authoritative whenever it returned a
`ProductRiskBundle`, even if one required matrix was missing or invalid. That
prevents a failed live dated matrix from silently falling back to a static or
stale provider matrix.

Refresh lifecycle must remain:

```text
source unchanged            reuse its committed matrices
P&L-only refresh            reuse all committed matrices
Portfolio-only refresh      reuse all committed matrices
source Risk Date changed    remove and replace only that source's matrices
force_risk=True             reload every changed source's matrices
later refresh stage fails   preserve the previous atomic snapshot
```

The matrix book and authoritative-source set are committed under the same
state lock as Risk frames and the new snapshot revision.

### 6. Keep the revision-bound read model

Required boundaries:

```text
cube/services/s01_snapshots.py::ReductionMatrixRead
cube/services/s02_state.py::read_reduction_matrices
cube/app/s02_contracts.py::ReductionMatrixReadProtocol
cube/app/s02_contracts.py::RefreshManagerProtocol.read_reduction_matrices
```

The read returns:

```python
ReductionMatrixRead(
    revision=revision,
    matrices={(source_type, matrix_name): caller_owned_frame},
    authoritative_source_types=frozenset(...),
)
```

It is separate from the large refresh snapshot so ordinary UI reads do not
copy matrix frames. The Risk cache checks that the matrix revision equals the
dashboard revision. A revision race causes the filter loop to restart against
the newer revision rather than combining new Risk with old matrices.

### 7. Wire the same catalogue into both owners

The catalogue is intentionally used at two boundaries:

```text
Refresh manager
  -> decides which returned dated matrices are required and committed

Risk-page reducer
  -> maps each prepared raw Risk identity to its MatrixName
```

Current composition is:

```python
# cube/services/s05_sources.py
RiskRefreshManager(
    ...,
    reduced_tenor_catalog=get_reduced_tenor_catalog_source(),
)
```

and:

```python
# app.py
build_app(
    ...,
    reduced_tenor_catalog=get_reduced_tenor_catalog_source(),
    reduced_tenor_matrix_provider=get_reduced_tenor_matrix,
)
```

Supplying only the manager side is not enough for row mapping. Supplying only
the app side loses dated matrix selection and atomic authority. `build_app()`
also requires its catalogue and provider together.

In the latest design, the app provider has two jobs:

1. return `CREDIT_STANDARD`; and
2. support legacy plain-DataFrame adapters.

For a bundled non-Credit source, the committed matrix book wins and the
provider must not be called on the Reduced click.

### 8. Implement Credit as the shared mapping, not catalogue matrices

Current symbols:

```text
cube/domain/s11_tenorreduction.py::CREDIT_STANDARD_MAPPING_NAME
cube/domain/s11_tenorreduction.py::validate_credit_tenor_mapping
cube/domain/s11_tenorreduction.py::ReducedTenorReducer._reduce_credit_batch
cube/services/s07_tenorreduction.py::get_credit_tenor_mapping
```

The provider must return exactly:

```text
Full Tenor, Reduced Tenor
```

Example:

```python
pd.DataFrame(
    [
        ("3Y", "3Y"),
        ("4Y", "5Y"),
        ("5Y", "5Y"),
    ],
    columns=["Full Tenor", "Reduced Tenor"],
)
```

Full-tenor labels must be unique. Repeated reduced labels are intentional and
cause summation. The first used occurrence in the mapping controls output
order.

The one shared mapping must cover the union of actual Tenor Swap labels from
every registered one-axis Credit source, currently Credit Delta and Credit
Vega. If the business requires different source-specific mappings, the current
shared contract must be extended; adding Credit rows to `s11_matrix.csv` does
nothing because the reducer deliberately ignores them.

Credit mapping applies after P&L and sums, per existing position:

```text
Risk, dRisk, P&L
Risk/dRisk Expo and Hedges
P&L Expo and Hedges
Risk/dRisk SP01
Risk/dRisk PSP01
Risk/dRisk PM01
Risk/dRisk PM01P
Risk/dRisk Theta
Risk/dRisk JTD
```

Changing the Credit measure in the UI happens later. The reducer transforms
all measure columns once, then `apply_credit_measure()` copies the selected
pair into the display Risk/dRisk columns. A Credit measure change should
rerender the table but should not rebuild the reduced book.

### 9. Preserve position grain and transform only additive values

The numeric reducer batches by:

```text
MatrixName + Source Type + Risk Type + Risk Greek + raw Underlying
```

Inside a batch, a position is every remaining column except:

```text
Tenor Swap and Tenor Swap Order
additive measure columns
market quote columns
carried promotion/threshold metadata
```

Portfolio, Split, Group, Product, reporting dimensions, raw Underlying and
Reported Underlying therefore remain boundaries. There is no cross-Portfolio
matrix aggregation.

Risk, dRisk, P&L, breakdowns and Credit measure pairs are transformed. Vol
Score, thresholds and baseline promotion metadata carry their first source
value. Promotion may then be recomputed by its owner.

### 10. Never multiply or sum market quotes

Before reduction, the UI reads the complete committed MarketBook for the same
revision and compacts exact keys:

```text
Source Type + raw Underlying + Tenor Swap
```

For each reduced label:

- an exact matching full-tenor label supplies Open, Current, Move, availability
  and status;
- a synthetic label such as `Long` has blank Open/Current/Move, availability
  `False`, and blank status; and
- quotes are never matrix products, weighted averages, or sums.

The Risk source date and Market Date can legitimately differ. That is why the
matrix follows Risk Date while quotes come from the committed MarketBook.

### 11. Build the reduced book before filters and promotion

Current UI cache path:

```text
cube/pages/risk/s02_state.py::_RiskDataCache.filtered
cube/pages/risk/s02_state.py::_reduced_for_scope
cube/pages/risk/s02_state.py::_reduce_filtered
```

The exact order is:

```text
committed prepared full book
  -> scope to active Risk Type, or all Risk Types for promotion recalc
  -> reduce and cache that canonical book
  -> IR family filter
  -> Risk Type, Split and reporting filters
  -> explicit manual promotion generation
```

Do not move reduction back after filters. Doing so recreates the original
performance defect and can make an incomplete definition appear to work only
because a filter hid the missing tenor.

Do not bake a session promotion generation into `_reduced_frames`. Promotion
is session/filter-basis-owned and must remain after the shared reduced book.

### 12. Understand the cache layers

| Cache | Key/lifetime | Invalidated by |
|---|---|---|
| Dated non-Credit matrix book | Source Risk Date, published with revision | Changed source Risk refresh |
| UI matrix read | Revision | New committed dashboard revision |
| Compact MarketBook quotes | Revision | Clear Cache or new revision |
| Canonical reduced book | `(revision, active_risk_type)` | Clear Cache or new revision |
| Exact filtered result | Revision + filters + Reduced flag + generation | LRU/reset/revision |
| Static provider/Credit mapping | Reducer process lifetime | Process restart |
| UI-loaded catalogue | Reducer process lifetime | Process restart |

Clear Cache deliberately rebuilds the reduced book and quote cache, but it
does not reconstruct the reducer or retry a provider name previously cached as
unavailable. Editing `s11_matrix.csv` or `CREDIT_STANDARD` therefore requires
an application restart, not only Clear Cache.

### 13. Promotion recalculation is a separate all-Risk scope

`risk-explorer-options` includes the Reduced flag in `PromotionBasis`. Clicking
**Recalculate all Risk views** calls:

```python
cache.filtered(
    refresh_manager,
    None,
    None,
    ...,
    reduced_tenor=basis.reduced_tenor,
)
```

That builds or reads the `(revision, None)` all-Risk reduced book. A table may
already have built `(revision, "Credit")`, but those are different cache keys;
the first reduced promotion recalculation can therefore reduce the same Credit
rows again as part of the all-Risk book.

Only after filtering and reduction does promotion aggregate generic Risk,
dRisk and P&L and create the generation identifier. The UUID is not the
expensive part. The selected Credit measure is not a promotion-basis input and
is applied only while rendering the Credit table.

Changing Full/Reduced makes an existing manual generation stale and shows the
warning to recalculate or reset. It does not automatically recalculate.

## What an older or partial implementation is likely missing

Use this as the porting checklist:

- [ ] Remove every Credit row from `s11_matrix.csv`.
- [ ] Automatically select `CREDIT_STANDARD` for all one-axis Credit sources.
- [ ] Make the Credit-only UI path avoid opening the non-Credit catalogue or
  matrix book.
- [ ] Reduce all Credit Risk/dRisk measure pairs, not only generic Risk/dRisk or
  SP01.
- [ ] Cache the canonical reduced book by `(revision, active_risk_type)`.
- [ ] Reduce before IR/Split/reporting filters and before manual promotion.
- [ ] Clear reduced and market caches on Clear Cache and new revision.
- [ ] Add `ProductRiskBundle`, while retaining DataFrame adapter compatibility.
- [ ] Fetch a non-Credit matrix bundle with the exact source Risk Date.
- [ ] Select only catalogue-required names after Risk validation.
- [ ] Commit matrices under `(source_type, MatrixName)` to avoid name collisions.
- [ ] Commit Risk and matrices atomically.
- [ ] Carry an `authoritative_source_types` set even when a bundled matrix is
  missing.
- [ ] Never fall back to the static provider for a bundled authoritative source.
- [ ] Remove only a changed source's old matrices during selective refresh.
- [ ] Reuse matrices during P&L-only and Portfolio-only refreshes.
- [ ] Add the separate revision-bound defensive matrix read.
- [ ] Retry the UI read on a revision race.
- [ ] Wire the same catalogue into both refresh manager and Risk-page cache.
- [ ] Keep the provider for Credit and legacy adapters.
- [ ] Use raw Underlying, not Reported Underlying, for catalogue matching.
- [ ] Treat matrix rows as outputs and columns as inputs.
- [ ] Require complete actual-tenor coverage or pass the entire batch through.
- [ ] Transform additive values only; use exact-label market quote lookup.
- [ ] Make a Credit measure switch reuse the already-reduced all-measure frame.

## Confirmed current-repository findings

The core chain above is present and its focused tests pass, but the checked-in
fixture is not a production-complete example.

### 1. All checked-in definitions are placeholders

`data/s11_matrix.csv` and `cube/services/s07_tenorreduction.py` deliberately
prefix labels with:

```text
TEMP_REPLACE_ME -
```

The IR and FX matrices are constants, not real dated service responses. A
production deployment must replace the catalogue values, matrix parser/bundle,
and Credit mapping together. Replacing only the visible CSV is insufficient.

### 2. The fixture Credit mapping does not cover Credit Vega

The current placeholder mapping covers:

```text
1Y, 3Y, 4Y, 5Y, 7Y, 10Y
```

The fixture Credit Vega source contains:

```text
1M, 3M, 6M
```

Reduced mode logs incomplete-mapping warnings and keeps Credit Vega at full
tenor. Fixture Credit Delta uses 1Y/3Y/5Y/7Y, which all map to themselves, so
the current fixture does not demonstrate a real Credit tenor collapse.

Before production sign-off, `CREDIT_STANDARD` must cover the actual union of
Credit Delta and Credit Vega labels and create the approved reduced buckets.

### 3. Sparse non-Credit positions currently create unsupported output rows

The numeric reducer emits every matrix row for each preserved position. When a
position has no observed input under any nonzero weight for one output, its
additive values become blank, but the output row remains.

On the current fixture, one all-Risk probe produced:

```text
full rows                         10,572
reduced rows                      12,378
all-core-additive blank outputs    1,806

FX Vega       423 ->   846 rows, 423 blank outputs
IR Delta      705 -> 2,088 rows, 1,383 blank outputs
```

This can make a feature named Reduced tenor increase the server/table workload.
Current focused tests do not define whether unsupported rows should remain for
a regular grid or be dropped. Decide that business/UI contract explicitly. If
the rows are not required, drop output rows with no support across all additive
measures and add a sparse-position regression test before changing runtime.

### 4. The fixture bundles matrices from every product adapter

`cube/services/s05_sources.py::_get_csv_product_connector_adapters` returns the
same small non-Credit matrix bundle from every fixture Risk function. This is a
local simplification, not the recommended production pattern. It means refresh
can inspect matrix metadata even when the user remains in Full mode.

Real adapters should return a bundle only where they own a same-date matrix
secondary file. Other products should return their normal DataFrame.

### 5. Mixed full and reduced batches are not labelled in the UI

Missing catalogue rows, incomplete matrices and unavailable definitions all
preserve full tenor safely. The table can therefore contain reduced and
full-tenor batches together without a visible status column. App Logs capture
missing/malformed bundled matrices and Credit coverage warnings, but an
incomplete non-Credit matrix's runtime coverage fallback is currently silent.

For operational clarity, add a diagnostic/status count before treating the
feature as production-complete.

### 6. Catalogue/provider recovery requires a restart

The manager logs catalogue failures while processing a bundle, but the UI
reducer independently loads the same catalogue on its first non-Credit Reduced
request. That read is not wrapped by the reducer's provider fail-soft handler.
An invalid catalogue can therefore still fail the callback.

Provider failures and the loaded catalogue are also cached for the reducer's
lifetime. A corrected static service or edited CSV is not retried by Clear
Cache or a new data revision. A restart is the current recovery path. A future
hardening patch should catch catalogue-load failure and provide an explicit
reloader/invalidation policy.

## Scope boundaries which can look like missing reduction

Reduced tenor currently belongs to Risk Explorer table/detail requests.
Aggregate P&L, Quick Risk, Quick Market and search do not accept the Reduced
flag. Top Promotions reads the committed full-tenor rows, although it can show
a classification from a manual generation calculated on a reduced basis.

New Trades position detail also rereads full `combined_pl`. A synthetic reduced
label may therefore find only an exact same-label trade or no trade rather than
all full tenors which contributed through the matrix. Extending those views
requires a separate contribution-lineage contract; it is not accomplished by
passing the current boolean farther downstream.

## Verification

### Contract tests already passing

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest `
    tests\s43_reducedtenor.py `
    tests\s44_tenorreductionsource.py `
    tests\s19_riskfilters.py `
    tests\s07_integration.py `
    tests\s20_connectors.py `
    -q -p no:cacheprovider
```

Current result:

```text
102 passed
```

These tests cover matrix/mapping validation, math, exact quotes, fail-safe
passthrough, revision ownership, dated source replacement, cache reuse and
Credit's automatic route.

### Tests still needed before production sign-off

Add tests for:

1. numeric reduction of PSP01, PM01, PM01P, Theta and JTD as well as SP01;
2. every production catalogue identity matching a real raw Underlying;
3. each numeric matrix covering every actual full tenor for its source;
4. `CREDIT_STANDARD` covering the union of every Credit source tenor;
5. the approved sparse-position output-row policy;
6. an invalid catalogue failing soft in the UI path;
7. a realistic full-book `(revision, None)` reduction time and memory bound;
8. Reduced Credit measure switching followed by promotion recalc; and
9. repeated reduced promotion recalc reusing the all-Risk cache.

### Hand calculation

For one known position, calculate by hand:

```text
matrix @ Risk
matrix @ dRisk
matrix @ P&L
matrix @ every populated Credit measure pair
```

Compare those values at the same Portfolio, raw Underlying and output tenor.
Check total preservation only when the business matrix columns sum to one.

### Live acceptance sequence

1. Restart the application after installing the catalogue/provider changes.
2. Force a Risk refresh for one matrix-owning source.
3. Confirm `read_reduction_matrices().revision` equals the committed revision.
4. Confirm the expected `(source_type, MatrixName)` keys and source Risk Date.
5. Select Full tenor and record rows/values for one known position.
6. Select Reduced tenor and compare every additive vector with the hand result.
7. Confirm an exact output tenor reuses its market quote.
8. Confirm a synthetic output tenor has blank market values.
9. Switch SP01, PSP01, PM01, PM01P, Theta and JTD; confirm no second reduction.
10. Change reporting filters; confirm the same reduced book is reused.
11. Click promotion recalculation; confirm the first all-Risk build is bounded
    and the next identical request is a cache hit.
12. Run a P&L-only refresh; confirm matrices are reused.
13. Change one source Risk Date; confirm only its matrices are replaced.
14. Remove one required matrix in a test environment; confirm Risk remains and
    only that batch stays full tenor without static fallback.
15. Deselect Reduced tenor; confirm the authoritative full book returns intact.

## Expected behavior after a correct implementation

- Full mode performs no UI matrix, mapping or reduction work.
- A non-Credit Reduced click performs no network matrix request.
- The first Reduced request per revision and active Risk Type builds once.
- Later filters and Credit measure changes reuse that reduced book.
- The first reduced promotion recalc may build the separate all-Risk book once.
- Risk and dated non-Credit matrices can never cross revisions.
- Missing optional matrices never discard valid Risk.
- A bundled missing matrix never falls back to fixture/static data.
- Credit needs no catalogue row and reduces every measure pair together.
- Market quotes remain full-tenor observations attached only by exact label.
- Full mode is always reversible because the committed source book is never
  mutated.

## Rollout and rollback

Deploy catalogue, connector parser/bundle and Credit mapping changes together.
Restart the application so process-owned catalogue/provider caches are fresh,
then force the affected Risk sources to publish a new revision.

The immediate user rollback is to deselect Reduced tenor; Full mode retains the
authoritative committed book. For a code rollback, revert the production
adapter/catalogue/provider deployment as one unit and restart. Do not leave a
live catalogue name pointing at a stale temporary provider definition.
