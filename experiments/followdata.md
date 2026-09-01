# Follow the data — add a tenor matrix, Market/history, Stock/history, and P&L/history

This is the step-by-step implementation guide for the current Rebirth V5 code on branch **v4**. It is deliberately detailed enough to follow as a change checklist.

This Markdown file is documentation only. Adding this file does not itself connect a source, create a matrix, write history, or send P&L.

The four requested parts are:

1. add a new reduced-tenor matrix;
2. add live Market data to Quick Market and Market history to the Data page;
3. add live Stock and Stock history to the Stock page; and
4. add Predict P&L, Colossus actual P&L history, and, if required, the two outbound P&L senders to the P&L page.

The current code already owns the pages, callbacks, tables, charts, revision checks, filtering, and most validation. The safest implementation is to replace the narrow data boundaries and leave page code alone.

## The most important distinction

These are separate data paths:

~~~text
Reduced tenor
  ProductSpec
    -> dated Risk connector returns Risk + named matrices
    -> refresh validates and commits both in one revision
    -> Risk page applies a matrix only when Reduced is selected

Live Market
  one committed Market Status (Live or OFFICIAL)
    -> ProductSpec Open connector at T-1 + Current connector at Market Date
    -> one validated raw-quote MarketBook in the refresh revision
    -> Quick Market and Predict P&L

Market history
  committed natural-date OFFICIAL MarketBook
    -> market.parquet in a complete immutable daily archive
    -> ArchiveHistoryRepository
    -> /data Market History tab

Live Stock
  GetStock(current date) + GetStock(prior business date)
    -> Stock validator
    -> Portfolio mapping
    -> /stock current table and pivot

Stock history
  scheduled GetStock(market date)
    -> stock.parquet in a completed daily archive
    -> SQLStockHistoryRepository
    -> /stock history chart

Current Predict P&L
  validated Risk + validated Open/Current MarketBook
    -> product P&L calculation
    -> committed combined_pl
    -> /pnl send editors

Actual P&L history
  scheduled Colossus loader
    -> colossus.parquet beside archived Predict risk.parquet
    -> SQLPLHistoryRepository
    -> /pnl overview and Colossus/Predict chart

Outbound P&L
  committed combined_pl
    -> mapping + Portfolio governance + adjustment overlay
    -> SOG sender and Portfolio sender
~~~

Do not collapse these paths into one connector. In particular:

- changing a tenor matrix must not fetch data from a page callback;
- making live Market work does not create history until a complete OFFICIAL archive is published;
- there is no separate Market-history loader: the archive writer uses the committed **snapshot.market_frame**;
- Quick Market only creates a typed handoff to **/data**; the Data page is the only active Market-history workspace;
- making live Stock work does not populate Stock history;
- there is no separate live Predict-P&L connector;
- Colossus is actual P&L for history and validation, not the source of current Predict;
- the upper P&L overview currently reads the latest archive, while the send editors use the live committed refresh snapshot.

## Files involved

| Purpose | Current owner |
|---|---|
| Product registry and matrix bundle type | **cube/domain/s02_products.py** |
| Matrix selector and reduction rules | **cube/domain/s11_tenorreduction.py** |
| Temporary matrix provider | **cube/services/s07_tenorreduction.py** |
| Matrix selector CSV | **data/s11_matrix.csv** |
| Active product source composition | **cube/services/s05_sources.py** |
| Refresh and same-revision matrix commit | **cube/services/s06_refresh.py** |
| Revision-bound matrix read | **cube/services/s02_state.py** |
| Risk-page reduced cache | **cube/pages/risk/s02_state.py** |
| Market Open/Current validation and merge | **cube/domain/s03_calculations.py** |
| Committed Quick Market/search MarketBook | **cube/domain/s10_search.py** |
| Market archive/history contracts | **cube/history/s01_models.py**, **s02_contracts.py** |
| Market archive queries and lazy SQL | **cube/history/s04_queries.py**, **s05_store.py**, **s06_repository.py** |
| Data-page Market history UI | **cube/pages/data/s01_selection.py**, **s02_view.py**, **s03_callbacks.py** |
| Quick Market → Data handoff | **cube/pages/risk/s04_handoff.py** |
| Stock schema and comparisons | **cube/domain/s09_stock.py** |
| Stock adapter boundary | **cube/adapters/s08_stock.py** |
| Stock current-page loader | **cube/pages/stock/s01_data.py** |
| Stock SQL history repository | **cube/pages/stock/s02_history.py** |
| Stock callbacks | **cube/pages/stock/s04_callbacks.py** |
| Predict P&L calculation | **cube/domain/s03_calculations.py** |
| P&L send governance | **cube/domain/s08_pnl.py** |
| P&L page dependency config | **cube/pages/pnl/s01_common.py** |
| P&L editor and send callbacks | **cube/pages/pnl/s02_editor.py**, **s05_sendcallbacks.py** |
| P&L history callbacks | **cube/pages/pnl/s09_drilldown.py** |
| Colossus and sender replacement points | **cube/services/s05_sources.py** |
| Unified archive contracts and writer | **cube/history/s02_contracts.py**, **s03_io.py** |
| P&L SQL history repository | **cube/history/s07_sql.py** |
| Scheduled archive entry point | **tools/s02_archive.py** |
| App composition | **app.py**, **cube/app/s07_factory.py** |

## Before changing code

### Step 0.1 — start from a clean branch

From the repository root:

~~~powershell
git status --short --branch
git branch --show-current
~~~

Do not discard unrelated changes. Commit or preserve them separately before following this guide.

### Step 0.2 — decide where real data lives

The checked-in sources and archive contain deterministic temporary data. Real credentials and private financial data must not be committed.

Use:

- environment variables or the approved secret service for credentials;
- an approved durable path for history;
- a synchronous, bounded site client behind the existing callable boundary;
- the same archive root for the scheduler and the web app.

The shared history variable is currently named **PL_HISTORICAL_PATH**, even though it now contains Risk, Market, P&L, and optional Stock history.

For example:

~~~powershell
$env:PL_HISTORICAL_PATH = 'D:\rebirth-private\histo'
~~~

Code blocks containing names such as **AUTHORIZED_MARKET_CLIENT**, **AUTHORIZED_MARKET_OPERATIONAL_ERRORS**, **YOUR_SYNC_STOCK_CLIENT**, **AUTHORIZED_COLOSSUS_CLIENT**, **AUTHORIZED_COLOSSUS_OPERATIONAL_ERRORS**, **SANITIZED_MANAGER_FACTORY**, or **HISTORY_ROOT** are templates. Replace every all-capital placeholder with the approved site object, exception tuple, or path before running the block. Do not add a fake implementation merely to make an import succeed.

The resolved leaf layout is flat by date:

~~~text
<PL_HISTORICAL_PATH>/
  2026-09-01/
    risk.parquet
    colossus.parquet
    market.parquet
    stock.parquet
    _SUCCESS
~~~

Do not create nested year/month folders.

### Step 0.3 — keep all new source functions synchronous

The current adapters and Dash callbacks call these functions synchronously. An async function would return a coroutine instead of a DataFrame unless the entire boundary were redesigned.

Use a normal function with explicit connection and read timeouts:

~~~python
def get_something(selected_date: pd.Timestamp) -> pd.DataFrame:
    raw = SYNC_CLIENT.load(
        as_of=selected_date.date().isoformat(),
        connect_timeout=5,
        read_timeout=30,
    )
    ...
~~~

Do not wrap blocking I/O in async merely to change the keyword. If the client itself is asynchronous, create one deliberately owned synchronous adapter at the composition boundary and test its timeout/cancellation behavior.

---

# Part 1 — add a new matrix to tenor reduction

## 1.1 Choose exactly one lane

Most mistakes start by changing more files than the requested matrix needs.

### Lane A — a new raw Underlying uses an existing identical matrix

Add:

- one selector row in **data/s11_matrix.csv**; and
- coverage/regression tests.

Do not add a new ProductSpec or copy the same numeric matrix under another name.

This lane works only when the reused MatrixName is available to the owning source:

- if that source returns **ProductRiskBundle**, its own **matrices** mapping must include the bare reused name; or
- if that source returns a plain Risk DataFrame, the app-level fallback provider must supply that name.

A matrix committed by another source is keyed by that other source type and is not automatically reusable. A bundled source that omits the name is authoritative and will stay Full rather than fall back.

### Lane B — an existing eligible product needs a new numeric definition

Add:

- one selector row;
- one named matrix in the owning dated Risk response;
- a fallback provider entry only if the deployment still uses the static provider; and
- tests.

This is the normal “add a new matrix” lane.

### Lane C — Credit tenor reduction

Credit does not use a numeric selector matrix. Update the shared **CREDIT_STANDARD** two-column Full Tenor to Reduced Tenor mapping.

Do not add a Credit row to **data/s11_matrix.csv**.

### Lane D — a brand-new Risk Type/Risk Greek product

First add the whole product to the product registry, adapters, readiness, thresholds, market connectors, P&L calculation, source composition, and tests. Once the product works in Full tenor, follow Lane B.

Do not add a fake ProductSpec only to make a matrix selector row pass validation.

## 1.2 Understand the exact current chain

The current non-Credit path is:

~~~text
cube/domain/s02_products.py::PRODUCT_SPECS
  -> only axes == (SWAP_AXIS,) are eligible

data/s11_matrix.csv
  -> Risk Type + Risk Greek + raw Underlying selects MatrixName

owning adapter risk(risk_date)
  -> ProductRiskBundle(risk=..., matrices={MatrixName: DataFrame})

RiskRefreshManager._validated_bundle_matrices()
  -> validates Risk first
  -> selects only matrix names actually required by that Risk response
  -> validates each matrix independently
  -> stores key (source_type, MatrixName)

atomic refresh commit
  -> Risk rows, MarketBook, P&L, and matrices share one revision

Risk page
  -> reads committed matrix book once per revision
  -> applies matrix only when Reduced is selected
  -> caches the result by revision and active Risk Type
~~~

A Full-tenor page render does not call the app-level fallback provider and does not perform matrix multiplication. An owning-source Risk refresh can still fetch and validate its dated bundled matrices even if every user remains in Full mode.

## 1.3 Step 1 — prove that the product is eligible

Open **cube/domain/s02_products.py** and find the exact source in **PRODUCT_SPECS_BY_SOURCE_TYPE**.

Run this from the repository root, replacing the source value:

~~~powershell
& '.\.venv\Scripts\python.exe' -c "from cube.domain.s02_products import PRODUCT_SPECS_BY_SOURCE_TYPE, SWAP_AXIS; s=PRODUCT_SPECS_BY_SOURCE_TYPE['ir/basis']; print(s); assert s.axes == (SWAP_AXIS,); assert s.risk_type != 'Credit'"
~~~

The product must have exactly one axis and that axis must be **SWAP_AXIS**.

These do not qualify:

- scalar products with no tenor axis;
- two-axis surfaces with Swap and Option tenor;
- Credit, because Credit has its own mapping path.

Adding a selector CSV row cannot make an ineligible ProductSpec reducible. **load_reduced_tenor_catalog()** rejects it.

## 1.4 Step 2 — capture the exact raw identity and full tenors

Use the validated Risk source, not a displayed label.

Record:

1. Source Type;
2. Risk Type;
3. Risk Greek;
4. raw Underlying; and
5. every actual Tenor Swap label returned for that Underlying.

The selector uses raw **Underlying**, not **Reported Underlying**.

Use a small diagnostic against the owning adapter:

~~~python
import pandas as pd

from cube.domain.s02_products import (
    PRODUCT_SPECS_BY_SOURCE_TYPE,
    ProductRiskBundle,
)
from cube.domain.s03_calculations import get_product_risk
from cube.services.s05_sources import get_product_connector_adapters

SOURCE_TYPE = "ir/basis"
RISK_DATE = pd.Timestamp("2026-09-01")

spec = PRODUCT_SPECS_BY_SOURCE_TYPE[SOURCE_TYPE]
raw_result = get_product_connector_adapters()[SOURCE_TYPE].risk(RISK_DATE)
raw_risk = (
    raw_result.risk
    if isinstance(raw_result, ProductRiskBundle)
    else raw_result
)
risk = get_product_risk(spec, RISK_DATE, raw_risk)

print(
    risk[["Underlying", "Tenor Swap"]]
    .drop_duplicates()
    .sort_values(["Underlying", "Tenor Swap"], kind="stable")
    .to_string(index=False)
)
~~~

Do not guess case, prefixes, spaces, or tenor aliases. Matrix coverage is label-based.

## 1.5 Step 3 — choose the MatrixName

Choose a stable, nonblank, source-specific name, for example:

~~~text
IR_BASIS_GBP_STANDARD
~~~

Rules:

- use the exact same spelling in the selector and bundle mapping;
- bundle keys are bare strings, not tuples;
- several Underlyings may share one MatrixName only when their numeric definition is identical;
- do not reuse one name for two different definitions.

Committed matrices are internally keyed by **(source_type, MatrixName)**, but the fallback provider receives only **MatrixName** and caches by that name. Globally unique descriptive names avoid ambiguity.

## 1.6 Step 4 — build the matrix in the correct orientation

The mandatory orientation is:

- rows/index = new reduced Tenor Swap labels;
- columns = old full Tenor Swap labels;
- calculation = new vector equals matrix multiplied by old vector.

Never transpose it.

Example:

~~~python
import pandas as pd

matrix = pd.DataFrame(
    [
        [1.0, 1.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 0.0, 1.0],
    ],
    index=["1Y", "5Y", "10Y"],
    columns=["6M", "1Y", "2Y", "5Y", "10Y"],
    dtype=float,
)
~~~

For an old Risk vector:

~~~text
6M=10, 1Y=20, 2Y=30, 5Y=40, 10Y=50
~~~

the result is:

~~~text
1Y=60, 5Y=40, 10Y=50
~~~

The matrix validator requires:

- a pandas DataFrame;
- at least one row and one column;
- nonblank unique string row labels;
- nonblank unique string column labels;
- finite numeric values;
- no booleans, NaN, or infinity.

Validate it immediately:

~~~python
from cube.domain.s11_tenorreduction import validate_reduction_matrix

matrix = validate_reduction_matrix(
    matrix,
    matrix_name="IR_BASIS_GBP_STANDARD",
)
~~~

The validator intentionally does not enforce column sums or reject an all-zero output row. If the business rule is “preserve total additive exposure,” add this explicit assertion in the source test:

~~~python
import numpy as np

assert np.allclose(matrix.sum(axis=0).to_numpy(), 1.0)
~~~

Avoid all-zero rows. They can create blank reduced rows and increase table/memory size without representing exposure.

## 1.7 Step 5 — prove full-tenor coverage

Every actual full tenor in the selected Source Type + Underlying batch must appear in the matrix columns.

Use:

~~~python
UNDERLYING = "GBP SONIA BASIS"

actual = set(
    risk.loc[risk["Underlying"].eq(UNDERLYING), "Tenor Swap"]
    .astype(str)
    .str.strip()
)
missing = actual - set(matrix.columns)
assert not missing, f"Matrix misses full tenors: {sorted(missing)}"
~~~

Coverage is fail-safe and all-or-nothing per batch:

- if one actual tenor is missing, the whole batch stays Full;
- the reducer does not silently drop that tenor;
- extra unused matrix columns are allowed;
- case and aliases still have to match exactly after surrounding whitespace is stripped.

## 1.8 Step 6 — add the selector row

Edit **data/s11_matrix.csv**.

The header and order must remain exactly:

~~~csv
Risk Type,Risk Greek,Underlying,MatrixName
~~~

Add one row, for example:

~~~csv
IR,Basis,GBP SONIA BASIS,IR_BASIS_GBP_STANDARD
~~~

The tuple:

~~~text
Risk Type + Risk Greek + raw Underlying
~~~

must be unique.

The selector contains no matrix weights. It only selects a name.

For Lane A, point the new Underlying row at the already existing MatrixName. Before stopping, verify that the owning source’s ProductRiskBundle contains that bare name, or that the source is unbundled and the app-level fallback provider supplies it. Then continue with tests and refresh/restart.

## 1.9 Step 7 — return the matrix with the owning dated Risk response

The preferred production source returns a **ProductRiskBundle**.

In the actual adapter registered for the source, change the Risk callable from returning only a DataFrame:

~~~python
def get_basis_risk(risk_date: pd.Timestamp) -> pd.DataFrame:
    return load_and_shape_basis_risk(risk_date)
~~~

to:

~~~python
import logging

import pandas as pd

from cube.domain.s02_products import ProductRiskBundle


LOGGER = logging.getLogger(__name__)


def get_basis_risk(risk_date: pd.Timestamp) -> ProductRiskBundle:
    selected_date = pd.Timestamp(risk_date).normalize()
    risk = load_and_shape_basis_risk(selected_date)

    try:
        raw_matrix = load_basis_matrix(selected_date)
        matrix = (
            raw_matrix
            .set_index("Reduced Tenor")
        )
        matrices = {
            "IR_BASIS_GBP_STANDARD": matrix.copy(deep=True),
        }
    except Exception:
        LOGGER.exception(
            "Could not load the dated reduced-tenor matrix",
            extra={
                "source_type": "ir/basis",
                "risk_date": selected_date.date().isoformat(),
            },
        )
        matrices = {}

    return ProductRiskBundle(
        risk=risk.copy(deep=True),
        matrices=matrices,
    )
~~~

Replace only:

- **load_and_shape_basis_risk** with the existing Risk connector;
- **load_basis_matrix** with the real matrix call;
- **Reduced Tenor** with the actual row-label field, if different;
- the source type and MatrixName with the real values.

The matrix and Risk must be for the same **risk_date**. Fetching the matrix later when the user clicks Reduced would mix revisions and add page latency.

The matrix response must have its reduced labels in the DataFrame index. If the external source puts them in a normal column, call **set_index()** before returning.

Return caller-owned copies. Do not expose a mutable client cache directly.

### The critical authority rule

As soon as a source returns any **ProductRiskBundle**, that source becomes authoritative for its matrices in that committed revision.

If a required bundled matrix is missing or invalid:

- valid Risk still commits for the interactive app;
- the affected batch remains Full;
- the page does not fall back to a stale static provider matrix;
- matrix validation records an operational warning in **RefreshSnapshot.errors**;
- **archive_official_snapshot()** therefore returns **status="skipped"** with reason **"The committed snapshot reports refresh errors."**, without loading Colossus or writing that date's Risk, Market, Colossus, or Stock leaf.

This is intentional under the current all-or-nothing official archive policy. A dated source failure must not silently substitute a different-date fixture, and a completed history leaf must not imply that every committed input was healthy. Operationally, this means a matrix outage affects more than the Reduced display: fix the dated matrix source and rerun a fresh successful OFFICIAL refresh before the archive retry window closes. If the business instead wants matrix warnings to be non-blocking for history, that is a separate policy/code change; do not achieve it by deleting errors in the scheduler.

## 1.10 Step 8 — update the temporary provider only when it is still active

The checked-in fixture uses **cube/services/s07_tenorreduction.py**:

- **_TEMP_REDUCTION_MATRICES** stores numeric definitions;
- **get_reduced_tenor_matrix_bundle()** copies the complete fixture bundle;
- **get_reduced_tenor_matrix(name)** is the UI fallback provider.

For a fixture-only change, edit the existing dictionary in **cube/services/s07_tenorreduction.py**. Insert the new entry and keep every existing entry; do not replace the whole dictionary:

~~~python
_TEMP_REDUCTION_MATRICES = {
    # Keep every existing matrix entry above and below this one.
    "IR_BASIS_GBP_STANDARD": _matrix(
        [
            [1.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 1.0],
        ],
        index=["6M", "2Y"],
        columns=["3M", "6M", "1Y", "2Y"],
    ),
}
~~~

Then add the matching fixture selector row to **data/s11_matrix.csv**:

~~~csv
IR,Basis,TEMP_REPLACE_ME - GBP 3M/6M,IR_BASIS_GBP_STANDARD
~~~

The fixture helper **_matrix()** automatically prefixes both its row and column labels with **TEMP_REPLACE_ME -**. That makes the actual matrix columns **TEMP_REPLACE_ME - 3M**, **TEMP_REPLACE_ME - 6M**, **TEMP_REPLACE_ME - 1Y**, and **TEMP_REPLACE_ME - 2Y**, matching the checked-in **ir/basis** fixture. The first reduced row adds 3M + 6M into 6M; the second adds 1Y + 2Y into 2Y. Do not use that helper for real, unprefixed tenor labels.

This fixture row deliberately differs from the production-style selector example in Step 6. Use the Step 6 row for a real **GBP SONIA BASIS** source; use the prefixed row above only with the checked-in temporary fixture.

In a real deployment, prefer the same-date ProductRiskBundle. Do not load every matrix for every product as the fixture currently does. The owning source should return only the small set it owns and that can be dated consistently with its Risk.

## 1.11 Step 9 — do not edit the Risk page

For an existing eligible product, no page or callback change is required.

Existing code already:

- exposes the Reduced option;
- lazily creates the reducer;
- reads the committed matrix book once per revision;
- caches reduced books by revision and active Risk Type;
- preserves Full data when a definition is unavailable;
- rebuilds promotion against the selected Full/Reduced basis.

Do not add:

- another Reduced checkbox;
- a page callback that fetches a matrix;
- matrix data in browser stores;
- a new UUID;
- a special case for the Underlying in the UI.

## 1.12 What is transformed and what is not

The reducer multiplies/sums additive values that are present, including:

- Risk;
- dRisk;
- PL;
- Risk/dRisk/PL Expo and Hedges aliases;
- populated Credit measure columns.

It does not multiply or average:

- Open;
- Current;
- Market Move;
- Market Available;
- Market Data Status.

Those values are looked up from the complete committed MarketBook using:

~~~text
Source Type + raw Underlying + reduced Tenor Swap
~~~

Therefore a valid reduced Risk row can have a blank market quote if the new reduced tenor label has no exact quote in the MarketBook.

The matrix row order becomes:

~~~text
Tenor Swap Order = 0, 1, 2, ...
~~~

## 1.13 Credit is a separate map-and-sum path

Every one-axis Credit source automatically selects **CREDIT_STANDARD**.

The provider returns exactly:

~~~csv
Full Tenor,Reduced Tenor
1Y,1Y
3Y,3Y
4Y,5Y
5Y,5Y
7Y,7Y
10Y,10Y
~~~

Those six rows are the checked-in fixture example, not the production tenor contract. Production may use a different complete mapping, such as the site’s common 15-full-tenor to 5-reduced-tenor definition. Only the two exact column names/order, nonblank labels, and unique Full Tenor values are structural requirements.

Rules:

- Full Tenor must be unique;
- several full tenors may map to the same Reduced Tenor;
- mapped additive rows are summed;
- ordered first appearance controls reduced order;
- one missing source tenor keeps the whole Credit batch Full.

To change Credit:

1. update the real provider response for **CREDIT_STANDARD**, or the fixture **_TEMP_CREDIT_TENOR_MAPPINGS**;
2. preserve the exact two-column order;
3. add Credit mapping tests;
4. restart the process because provider success/failure is cached.

The current refresh manager deliberately ignores Credit mappings in ProductRiskBundle: **required_reduction_matrix_names()** returns no numeric names for Credit. **CREDIT_STANDARD** is loaded only through the app-level matrix provider. Carrying a dated Credit mapping in the Risk bundle would require a new contract and tests; a new Risk revision alone does not reload the current Credit mapping.

Do not add Credit rows to **data/s11_matrix.csv**.

## 1.14 If this is a brand-new product

Complete these first:

1. add a unique **ProductSpec** in **cube/domain/s02_products.py**;
2. use exactly **(SWAP_AXIS,)** if it should reduce;
3. add its Risk connector;
4. add Open and Current market connector hooks;
5. register the adapter in active source composition;
6. add readiness/checker inventory;
7. add threshold coverage;
8. add Portfolio/reporting mappings where required;
9. prove Full-tenor P&L and MarketBook behavior;
10. add product, schema, connector, integration, and publish tests.

Then return to Section 1.3 and add the matrix.

## 1.15 Tests to add or update

### Domain matrix tests

Update **tests/s43_reducedtenor.py** with:

- selector identity accepted;
- exact hand calculation;
- row order;
- Risk, dRisk, and PL transformed;
- quote values looked up rather than weighted;
- missing full tenor leaves the whole batch Full;
- the business column-sum rule, if required.

Minimal arithmetic shape:

~~~python
import pandas as pd

from cube.domain.s11_tenorreduction import validate_reduction_matrix


def test_new_basis_matrix_has_expected_orientation_and_math():
    matrix = pd.DataFrame(
        [
            [1.0, 1.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0],
        ],
        index=["1Y", "5Y", "10Y"],
        columns=["6M", "1Y", "2Y", "5Y", "10Y"],
        dtype=float,
    )
    validated = validate_reduction_matrix(
        matrix,
        matrix_name="IR_BASIS_GBP_STANDARD",
    )

    old = pd.Series(
        [10.0, 20.0, 30.0, 40.0, 50.0],
        index=["6M", "1Y", "2Y", "5Y", "10Y"],
    )
    actual = validated @ old

    assert actual.to_dict() == {
        "1Y": 60.0,
        "5Y": 40.0,
        "10Y": 50.0,
    }
~~~

### Provider tests

Update **tests/s44_tenorreductionsource.py**:

- every selector name is available from the fixture provider;
- the new provider call returns a defensive copy;
- malformed names fail clearly.

### Connector and revision tests

Update:

- **tests/s20_connectors.py** for the exact bundle name and supplied date;
- **tests/s07_integration.py** for the committed **(source_type, MatrixName)** key, defensive copies, P&L-only reuse, and forced Risk-date replacement;
- **tests/s19_riskfilters.py** for no fallback call when a source is authoritative, one matrix read per revision, cache reuse, and lazy Full behavior.

In particular, update the complete hard-coded key set in **tests/s07_integration.py::test_dated_risk_matrices_are_reused_then_replaced_with_their_source**. It currently expects only:

~~~python
{
    ("ir/delta", "IR_DELTA_STANDARD"),
    ("fx/vega", "FX_VEGA_STANDARD"),
}
~~~

If the change creates a new **(source_type, MatrixName)** key, add it to that exact set and assert that its matrix is reused by a P&L-only refresh and replaced by the next owning-source Risk-date refresh. Lane A may leave the set unchanged when it only adds another Underlying under an already expected source/name.

Retain explicit failure tests:

- missing bundle matrix;
- invalid bundle matrix;
- transposed/missing labels;
- same name on another source remains isolated by committed key;
- valid Risk remains available;
- no stale static fallback;
- the matrix warning is present in **snapshot.errors**;
- passing that warned snapshot to **archive_official_snapshot()** returns **skipped** before the Colossus loader is called and before any history leaf is created.

## 1.16 Validate Part 1

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests\s43_reducedtenor.py tests\s44_tenorreductionsource.py tests\s07_integration.py tests\s19_riskfilters.py tests\s20_connectors.py -q -p no:cacheprovider
~~~

Then:

1. restart the app;
2. force Risk refresh for the owning source;
3. inspect **manager.read_reduction_matrices()** and confirm the current revision plus exact key;
4. select Full and record totals;
5. select Reduced and hand-check every additive measure;
6. confirm reduced tenor order;
7. confirm quote blanks only where no exact reduced-tenor quote exists;
8. run a P&L-only refresh and confirm the matrix is retained;
9. force a new Risk date and confirm the old matrix is replaced.

Static provider catalogue/data and provider failures are process-cached. Navigation or changing a filter does not reload them.

The checked-in composition already supplies the boundaries in both places:

- **cube/services/s05_sources.py::build_production_refresh_manager()** passes the reduced-tenor catalogue to the refresh manager;
- **app.py::create_app()** passes the matching catalogue and provider to **build_app()**.

If you rename or replace those provider/catalogue functions rather than changing their bodies, update both composition points. **build_app()** requires catalogue and provider together; passing only one fails.

## 1.17 Common Part 1 failures

| Symptom | Most likely cause |
|---|---|
| New Underlying stays Full | Selector uses Reported Underlying, or actual full tenor is missing from matrix columns |
| Catalogue fails at startup/use | Wrong four-column order, duplicate identity, Credit/scalar/surface row |
| Values look transposed | Rows and columns were reversed |
| Bundle matrix is ignored | Bundle key spelling differs from MatrixName |
| Static provider is never called | Source returned ProductRiskBundle and is authoritative |
| Risk works but reduced matrix does not | Matrix validation failed independently; inspect refresh logs |
| Reduced Risk exists but Open/Current is blank | No exact market quote for the new reduced tenor label |
| Edit appears to do nothing | Old process/revision cache is still active |
| Reduced output is larger than expected | Too many matrix rows or all-zero output rows |

## 1.18 Part 1 done checklist

- [ ] Correct lane chosen.
- [ ] Existing ProductSpec is exactly one Swap axis, or full new-product integration completed.
- [ ] Raw Underlying captured from validated Risk.
- [ ] Matrix rows are reduced tenors and columns are full tenors.
- [ ] Every actual full tenor is covered.
- [ ] Selector has exact four-column schema and unique identity.
- [ ] Dated owning source returns ProductRiskBundle with a bare MatrixName key.
- [ ] Risk and matrix use the same risk_date.
- [ ] No Risk page callback was added.
- [ ] Domain, provider, connector, revision, and UI cache tests pass.
- [ ] App restarted and a new owning-source Risk revision committed.

---

# Part 2 — add live Market data and Market history

## 2.1 Understand what is already implemented

Market history already exists in Rebirth V5. Do not add another Market-history loader, another page, or another SQL repository.

The complete current chain is:

~~~text
get_market_state()
  + get_market_open(T-1 business date, one raw Underlying, selected status)
  + get_market_status(Market Date, one raw Underlying, selected status)
    -> ProductConnectorAdapter
    -> RiskRefreshManager
    -> validated and merged MarketBook
    -> RefreshSnapshot.market_frame
    -> archive_from_manager()
    -> archive_official_snapshot()
    -> <PL_HISTORICAL_PATH>/<YYYY-MM-DD>/market.parquet
    -> ArchiveSQLStore / ArchiveHistoryRepository
    -> /data Market History
~~~

The easiest production change is therefore:

1. replace the three temporary Market functions in **cube/services/s05_sources.py**;
2. disable both temporary FX Delta bulk hooks, or replace both with bounded real bulk calls;
3. keep the existing manager, archive writer, repository, Data page, and callbacks;
4. point both the scheduled job and web app at the same durable **PL_HISTORICAL_PATH**;
5. run the scheduled archive only when the authoritative status is **OFFICIAL**; and
6. configure the real Colossus loader described in Part 4, because a complete schema-v4 daily leaf cannot contain Market alone.

Do not add a **MARKET_HISTORY_LOADER** environment variable. None is needed.

## 2.2 Keep the four Market authorities separate

There are four different pieces of authority:

| Authority | Owner |
|---|---|
| Market Date | **RiskRefreshManager** and **market_date_for()** |
| Live versus OFFICIAL | one call to **get_market_state()** per refresh |
| Open source date | the T-1 business date supplied to **get_market_open()** |
| Quote identity and tenor rank | each product's **ProductSpec** plus connector-owned order columns |

The refresh manager resolves status once and passes the exact same value to every Open and Current connector. The only accepted values are the case-sensitive strings:

~~~python
"Live"
"OFFICIAL"
~~~

Do not let each product connector compare against its own clock. That could combine Live IR with OFFICIAL Credit in one revision.

Open's request date is the prior business day. The Current/OFFICIAL request date is the selected Market Date. The persisted **Market Date** remains the selected official date; do not archive Open under its T-1 source date.

The current centralized calendar is pandas Monday-to-Friday rollback, not a site holiday calendar. If the desk requires holiday-aware Market/Open dates, change **market_date_for()** and **checker_date_for()** as one governed calendar authority and update their tests. Do not special-case a holiday inside only one product connector.

## 2.3 Know the exact live connector contracts

The normal adapter path calls a product connector with one Risk-derived raw **Underlying** at a time. A deliberately registered bulk hook instead receives the exact ordered requested Underlying tuple. Return only the requested scope, or a correctly shaped empty DataFrame when the upstream source explicitly says that no quote exists.

For a scalar product, Open returns:

~~~text
Underlying, Open
~~~

and Current returns:

~~~text
Underlying, Current, Market Status
~~~

For a one-axis product, Open returns:

~~~text
Underlying, Tenor Swap, Tenor Swap Order, Open
~~~

and Current returns:

~~~text
Underlying, Tenor Swap, Tenor Swap Order, Current, Market Status
~~~

For a two-axis product, Open returns:

~~~text
Underlying, Tenor Swap, Tenor Option,
Tenor Swap Order, Tenor Option Order, Open
~~~

and Current returns the same identity/order fields followed by:

~~~text
Current, Market Status
~~~

The exact columns are derived from the existing ProductSpec:

~~~python
spec = PRODUCT_SPECS_BY_SOURCE_TYPE[source_type]

open_columns = [
    UNDERLYING,
    *spec.tenor_columns,
    *spec.tenor_order_columns,
    OPEN,
]

current_columns = [
    UNDERLYING,
    *spec.tenor_columns,
    *spec.tenor_order_columns,
    CURRENT,
    MARKET_STATUS,
]
~~~

The downstream validator adds/checks the ProductSpec **Risk Type** and **Risk Greek** when those optional fields reach it. The templates below also validate optional upstream Source Type/Risk Type/Risk Greek before projecting the narrow result, so a contradictory partition label is never silently dropped.

Contract rules:

- **Open** and **Current** are finite numeric values or null; booleans and arbitrary strings fail;
- a genuine missing quote stays null, never zero;
- each exact Market key is unique;
- declared tenor ranks are non-negative integers;
- ranks should express the source's intended stable display order; the domain resolves leg disagreements and collisions before the final one-to-one archived mapping;
- undeclared axes are not invented by the connector;
- raw Underlying is the identity—do not return **Reported Underlying**, Portfolio, Activity, or other Risk reporting fields; and
- a timeout, authentication failure, malformed response, or server error must raise a sanitized exception. It is not an empty quote response.

## 2.4 Step 1 — replace the Market-state resolver

Open **cube/services/s05_sources.py** and replace only the body of **get_market_state()**. Keep its public signature so the existing manager composition remains valid.

Use this shape, adapting only the approved client's method and response-field names:

~~~python
def get_market_state(
    market_date: pd.Timestamp,
    *,
    trading_timezone: str = "Europe/London",
    now: datetime | pd.Timestamp | None = None,
) -> str:
    """Return the one authoritative source state for this refresh."""
    del trading_timezone, now  # production authority is the service, not this process
    selected_date = market_date_for(
        _normalized_date(market_date, parameter="market_date")
    )
    try:
        raw = AUTHORIZED_MARKET_CLIENT.get_market_state(
            as_of=selected_date.date().isoformat(),
            connect_timeout=3,
            read_timeout=8,
        )
    except AUTHORIZED_MARKET_OPERATIONAL_ERRORS:
        raise RuntimeError("Market-state source failed") from None
    status = raw.get(MARKET_STATUS) if isinstance(raw, Mapping) else raw
    return _market_status(status)
~~~

Also import or construct **AUTHORIZED_MARKET_CLIENT** through the approved secret/client composition. Client construction must not perform network I/O at module import or app construction; the first remote call belongs inside the connector function after refresh begins. Do not put a token, password, URL containing credentials, or private response sample in this repository.

The final **_market_status()** call is important. It rejects variants such as **Official**, **official**, **EOD**, **LIVE**, blank, or an unknown status instead of silently routing them.

If the authority service is unavailable, raise a short sanitized exception. Do not fall back from OFFICIAL to Live, do not use the old 22:00 fixture rule in production, and do not reuse an earlier status without an explicit governed policy.

Define **AUTHORIZED_MARKET_OPERATIONAL_ERRORS** as the exact tuple of approved client timeout, connection, authentication, and availability exceptions. Do not include **Exception**, **TypeError**, **ValueError**, or schema/programming errors. Only known operational failures should be translated to the fixed safe **RuntimeError** used by the manager's fail-soft path; contract/programming failures must propagate so the refresh retains last-good. Never include a raw client message, URL, request/response body, credential, or financial value in the replacement exception.

The manager's current hard deadline for one connector call is 15 seconds, and timed-out thread work cannot be forcibly cancelled. Keep the client's total connection/read deadline comfortably below that bound, as in the 3-second/8-second examples. A client timeout longer than the manager deadline can leave abandoned work occupying the eight-call connector gate. If the site genuinely requires more time, change and test the manager deadline and gate policy deliberately rather than only increasing the client timeout.

## 2.5 Step 2 — replace the Open connector

In the same file, replace only the body of **get_market_open()**. Keep the parameters exactly as they are.

~~~python
def get_market_open(
    source_type: str,
    open_date: pd.Timestamp,
    underlying: str,
    *,
    market_status: str,
) -> pd.DataFrame:
    selected_date = _business_date(open_date, parameter="open_date")
    selected_status = _market_status(market_status)
    if not isinstance(underlying, str) or not underlying.strip():
        raise ValueError("underlying must be nonblank text")

    selected_underlying = underlying.strip()
    spec = _source_spec(source_type)
    columns = [
        UNDERLYING,
        *spec.tenor_columns,
        *spec.tenor_order_columns,
        OPEN,
    ]

    try:
        response = AUTHORIZED_MARKET_CLIENT.get_open(
            source_type=source_type,
            as_of=selected_date.date().isoformat(),
            underlying=selected_underlying,
            source=selected_status,
            connect_timeout=3,
            read_timeout=8,
        )
    except AUTHORIZED_MARKET_OPERATIONAL_ERRORS:
        raise RuntimeError("Market Open source failed") from None

    if not isinstance(response, Mapping) or not {
        "availability",
        "rows",
    }.issubset(response):
        raise TypeError("Market Open client must return availability plus rows")
    rows = response["rows"]
    try:
        frame = (
            rows.copy(deep=True)
            if isinstance(rows, pd.DataFrame)
            else pd.DataFrame.from_records(rows)
        )
    except (TypeError, ValueError):
        raise ValueError("Market Open rows could not be normalized") from None
    if response["availability"] == "NO_DATA":
        if not frame.empty:
            raise ValueError("Market Open NO_DATA response contains rows")
        return pd.DataFrame(columns=columns)
    if response["availability"] != "OK" or frame.empty:
        raise ValueError("Market Open availability/rows contract is invalid")

    frame = frame.rename(
        columns={
            # "your_open_field": OPEN,
            # "your_underlying_field": UNDERLYING,
            # "your_swap_tenor_field": "Tenor Swap",
            # "your_swap_rank_field": "Tenor Swap Order",
        }
    )
    if frame.columns.duplicated().any():
        raise ValueError("Market Open response has duplicate canonical columns")
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"Market Open response is missing columns: {missing}")

    for field, expected in (
        ("Source Type", source_type),
        ("Risk Type", spec.risk_type),
        ("Risk Greek", spec.risk_greek),
    ):
        if field in frame:
            exact = frame[field].map(
                lambda value: isinstance(value, str) and value == expected
            )
            if not exact.all():
                raise ValueError(f"Market Open response contradicts {field}")

    answer = frame.loc[:, columns].copy().reset_index(drop=True)
    wrong_scope = ~answer[UNDERLYING].eq(selected_underlying)
    if wrong_scope.any():
        raise ValueError("Market Open returned a different Underlying")
    return answer
~~~

Delete the commented rename examples after inserting the actual source mapping. Do not use **reindex(columns=...)** to manufacture a missing required column: check **missing** first.

Map the real client's result to the explicit **availability = OK/NO_DATA** envelope. Only the documented **NO_DATA** result with no rows becomes a correctly shaped empty DataFrame. An unexpected empty OK result, absent envelope field, unknown status, transport failure, or parsing failure raises. If the client supplies a DataFrame in **rows**, the template takes a defensive copy.

## 2.6 Step 3 — replace the Current/OFFICIAL connector

Replace only the body of **get_market_status()**. Despite the historical function name, this is the quote leg that returns **Current** plus the already selected Market Status.

~~~python
def get_market_status(
    source_type: str,
    market_date: pd.Timestamp,
    underlying: str,
    *,
    market_status: str,
) -> pd.DataFrame:
    selected_date = _business_date(market_date, parameter="market_date")
    selected_status = _market_status(market_status)
    if not isinstance(underlying, str) or not underlying.strip():
        raise ValueError("underlying must be nonblank text")

    selected_underlying = underlying.strip()
    spec = _source_spec(source_type)
    quote_columns = [
        UNDERLYING,
        *spec.tenor_columns,
        *spec.tenor_order_columns,
        CURRENT,
    ]
    output_columns = [*quote_columns, MARKET_STATUS]

    try:
        response = AUTHORIZED_MARKET_CLIENT.get_current(
            source_type=source_type,
            as_of=selected_date.date().isoformat(),
            underlying=selected_underlying,
            source=selected_status,
            connect_timeout=3,
            read_timeout=8,
        )
    except AUTHORIZED_MARKET_OPERATIONAL_ERRORS:
        raise RuntimeError("Current Market source failed") from None

    if not isinstance(response, Mapping) or not {
        "availability",
        "rows",
    }.issubset(response):
        raise TypeError("Current Market client must return availability plus rows")
    rows = response["rows"]
    try:
        frame = (
            rows.copy(deep=True)
            if isinstance(rows, pd.DataFrame)
            else pd.DataFrame.from_records(rows)
        )
    except (TypeError, ValueError):
        raise ValueError("Current Market rows could not be normalized") from None
    if response["availability"] == "NO_DATA":
        if not frame.empty:
            raise ValueError("Current Market NO_DATA response contains rows")
        return pd.DataFrame(columns=output_columns)
    if response["availability"] != "OK" or frame.empty:
        raise ValueError("Current Market availability/rows contract is invalid")

    frame = frame.rename(
        columns={
            # "your_current_field": CURRENT,
            # map the same identity and rank fields as Open
        }
    )
    if frame.columns.duplicated().any():
        raise ValueError("Current Market response has duplicate canonical columns")
    missing = [column for column in quote_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"Current Market response is missing columns: {missing}")

    for field, expected in (
        ("Source Type", source_type),
        ("Risk Type", spec.risk_type),
        ("Risk Greek", spec.risk_greek),
    ):
        if field in frame:
            exact = frame[field].map(
                lambda value: isinstance(value, str) and value == expected
            )
            if not exact.all():
                raise ValueError(f"Current Market response contradicts {field}")

    if MARKET_STATUS in frame.columns:
        exact = frame[MARKET_STATUS].map(
            lambda value: isinstance(value, str) and value == selected_status
        )
        if not exact.all():
            raise ValueError("Current Market response contradicts selected status")

    frame[MARKET_STATUS] = selected_status
    answer = frame.loc[:, output_columns].copy().reset_index(drop=True)
    wrong_scope = ~answer[UNDERLYING].eq(selected_underlying)
    if wrong_scope.any():
        raise ValueError("Current Market returned a different Underlying")
    return answer
~~~

Use the same upstream field-to-canonical-field mapping for Open and Current. The current domain reconciliation is deterministic: Open is preferred for a tenor label, Current supplies a rank only when Open does not, and any rank collision between different labels causes that Underlying/axis vocabulary to be densely renumbered by preferred rank and stable source order. Do not add a second reconciliation rule inside the connector.

## 2.7 Step 4 — keep or replace the adapter map

The easiest setup is one approved client that supports every Source Type. Keep **get_product_connector_adapters()** and **build_production_refresh_manager()**, and keep the per-Underlying wrappers inside **_get_csv_product_connector_adapters()**.

However, one mandatory FX Delta choice remains. The current FX Delta adapter registers these two separate bulk fixture functions:

- **get_fx_delta_market_open_bulk()**; and
- **get_fx_delta_market_status_bulk()**.

The manager prefers those hooks over the generic functions. Therefore, replacing only **get_market_open()** and **get_market_status()** would leave FX Delta reading the temporary CSV.

The smallest production change is to remove the two bulk assignments so every product, including FX Delta, uses the newly replaced per-Underlying functions:

~~~python
adapters[source_type] = ProductConnectorAdapter(
    risk=risk,
    market_open=market_open,
    market_status=market_status_connector,
    market_open_bulk=None,
    market_status_bulk=None,
)
~~~

Replace the existing **ProductConnectorAdapter(...)** construction in that helper with this form. Test that FX Delta now reaches the approved client and that no temporary Market CSV partition is read.

This fallback makes FX Delta use sequential per-Underlying calls under the current default **market_max_workers=1**. Measure the largest production FX scope against the 15-second per-call and 120-second total connector budgets. If it cannot fit, implement both real bounded bulk legs; do not raise worker counts or introduce async blindly.

If the real API truly supports a bounded bulk request, the alternative is to replace both public FX bulk function bodies with approved calls for the exact manager-supplied ordered Underlying tuple. Do not leave either fixture body active, mix one real bulk leg with one temporary leg, or issue an unbounded “all markets” query merely to preserve batching.

The private wrapper's name still says **csv**; renaming it is optional cleanup, not required behavior.

If different product families use different services or payloads, create a **ProductConnectorAdapter** per exact Source Type through the existing builders:

- **cube/adapters/s02_ir.py::build_ir_adapters()**;
- **cube/adapters/s03_fx.py::build_fx_adapters()**;
- **cube/adapters/s04_credit.py::build_credit_adapter()**; and
- **cube/adapters/s05_commodities.py::build_commo_adapter()**.

Return the complete mapping from **get_product_connector_adapters()**. Do not provide only the new product: the manager requires complete Source Type coverage.

## 2.8 Step 5 — let the domain merge the two legs

Do not merge Open and Current in the connector. The existing functions in **cube/domain/s03_calculations.py** already:

1. add/check the ProductSpec Risk Type and Risk Greek;
2. validate numeric quotes and exact Market keys;
3. validate non-negative integer rank values;
4. outer one-to-one merge Open and Current;
5. reconcile label/rank authority with Open preference and deterministic collision renumbering;
6. attach the selected Market Status;
7. calculate **Move = Current - Open**; and
8. create a visible **Market Data Status**.

The current continuity policy copies a single available leg to the missing leg:

- missing Open with Current present → **Available; Open copied from Current**;
- missing Current with Open present → **Available; Current copied from Open**.

This makes Move zero for that row and records why. Do not pre-copy or pre-zero quotes in the connector, because doing so would hide which leg was absent and defeat the status message.

## 2.9 Step 6 — verify the committed live MarketBook

Run a refresh through the manager rather than calling a page callback:

~~~python
from cube.services.s05_sources import build_production_refresh_manager

manager = build_production_refresh_manager()
snapshot = manager.refresh(
    force_risk=True,
    force_pl=True,
    reason="market_connector_smoke",
)

assert not snapshot.errors, snapshot.errors
assert snapshot.market_status in {"Live", "OFFICIAL"}
assert not snapshot.market_frame.empty
print(snapshot.market_frame.head())
~~~

The committed frame is the full raw-quote MarketBook, including Market-only tenors. Do not substitute a Risk-joined or page-filtered frame when archiving.

A sanitized **RuntimeError** from a Market connector is treated as an operational source failure: the manager can convert that failed leg to empty, commit one coherent degraded revision with **snapshot.errors**, and the archive writer then skips that revision. Contract/programming failures such as **TypeError** or **ValueError** fail the refresh and retain the previous coherent snapshot. In neither case may a partial new MarketBook be mixed with the old revision.

Then start the app and verify:

1. Quick Market uses the same committed revision;
2. scalar, one-axis, and two-axis products render;
3. the displayed status matches the one resolver call;
4. Open, Current, and Move are numerically correct; and
5. a missing quote shows the framework-owned Market Data Status rather than silently becoming an invented upstream zero.

Changing the Credit measure—SP01, PSP01, JTD, Theta, and the other committed measure overlays—or clicking Promotion **Recalculate** uses the existing committed/revision-bound Risk data. Neither action changes ProductSpec, calls Market/history, nor creates a connector UUID. Only the separate source Refresh controls invoke **RiskRefreshManager** loading under the normal revision rules.

## 2.10 Exact persisted market.parquet contract

For a schema-v4 day, the writer validates and projects **snapshot.market_frame** to exactly this ordered schema:

~~~text
Source Type
Risk Type
Risk Greek
Underlying
Tenor Swap
Tenor Option
Tenor Swap Order
Tenor Option Order
Market Date
Open
Current
Move
Market Status
Market Data Status
~~~

The unique identity is:

~~~text
Source Type + Risk Type + Risk Greek + Underlying
+ Tenor Swap + Tenor Option
~~~

This is raw quote grain. It deliberately has no Portfolio, Group, Activity, mapping, or Reported Underlying.

The archive validator requires:

- a non-empty Market frame;
- exactly one Market Date, equal to the date-folder name;
- every Market Status exactly **OFFICIAL**;
- a known Source Type and its exact registered Risk Type/Risk Greek pair;
- nullable finite Open, Current, and Move;
- Move present exactly when both legs are present and equal to **Current - Open**;
- a unique exact Market identity;
- required declared-axis order fields with consistent label/rank mappings; and
- a nonblank Market Data Status.

For undeclared axes the canonical archive uses **N/A** with a null order. FX Delta's undeclared Swap axis uses **Spot** with a null order. The committed Market catalogue in **cube/domain/s10_search.py::_dashboard_tenors()** creates this normalization; the archive writer only validates/projects it. Do not invent a second convention in the source or expect archive ingestion to repair raw rows.

## 2.11 Step 7 — understand the unified writer

There is intentionally no Market-history loader. **archive_official_snapshot()** reads the committed **snapshot.market_frame** and writes it in the same transaction as the rest of the daily leaf.

For the canonical current schema, one completed leaf is:

~~~text
<PL_HISTORICAL_PATH>/<YYYY-MM-DD>/
  risk.parquet
  colossus.parquet
  market.parquet
  stock.parquet       # only when Stock archival from Part 3 is enabled
  _SUCCESS
~~~

Risk, Colossus, and Market are mandatory for a complete schema-v4 leaf. Stock is optional unless the manifest declares it.

The writer:

1. requires the snapshot's Market Date to be the natural business date for its System Date;
2. skips a Live snapshot;
3. skips a snapshot containing refresh errors;
4. validates Risk, Colossus, Market, and optional Stock before publication;
5. writes compressed Parquet into a hidden pending directory;
6. records row counts, ordered columns, dates, revision, and SHA-256 payload hashes in **_SUCCESS**;
7. publishes by atomically renaming the completed directory; and
8. returns **already_archived** on a valid repeat for the same date.

Never write **market.parquet** directly into a completed date folder. Never hand-create or patch **_SUCCESS**. A partial or mismatched leaf is intentionally invisible/invalid.

### The Part 4 dependency

The scheduled writer always requires a callable, non-empty, valid Colossus loader. Therefore, after implementing only Part 2, live Market works, but production daily history publication is not ready until the real Colossus boundary in Part 4 is configured—or complete externally produced schema-v4 leaves already exist.

Do not insert dummy Colossus rows to unblock Market history. Complete Part 4's loader first, then run the unified writer.

## 2.12 Step 8 — configure and run the official daily archive

The scheduler and web process must use the exact same durable root:

~~~powershell
$env:PL_HISTORICAL_PATH = 'D:\rebirth-private\histo'
$env:COLOSSUS_LOADER = 'your_connector_module:get_colossus_pl'
~~~

The default is **data/histo**, but real private history should normally use an ignored, mounted, durable directory such as the example above. Do not commit private leaves to GitHub.

The checked-in **publish.py** is intentionally specific to the deterministic demo archive: it requires the exact 262 fixture dates, fixture tag, row counts, Stock file, revisions, and hashes under **data/histo**. It does not publish an arbitrary private **PL_HISTORICAL_PATH**. For a hosted production deployment, deliberately choose one approved mechanism:

- mount the durable history root into the runtime;
- download complete validated leaves from approved storage before serving financial pages; or
- generalize the staging/publish contract and its tests for the governed production archive.

Do not copy private history into Git merely to satisfy the fixture-specific publish gate. The app must not begin serving history until the staged/mounted root has passed strict validation.

After the authoritative resolver returns **OFFICIAL**, run:

~~~powershell
& '.\.venv\Scripts\python.exe' -m tools.s02_archive
~~~

The entry point resolves **PL_HISTORICAL_PATH** and **COLOSSUS_LOADER**, builds the production manager, forces one coherent Risk/P&L refresh, and calls **archive_from_manager()**.

Expected behavior:

- before OFFICIAL → **skipped**;
- committed/retained snapshot with **snapshot.errors** → **skipped** and no Colossus call/write;
- cold-start or contract refresh exception before a usable snapshot → command failure, with no ArchiveResult and no published leaf;
- first valid official run → **archived**;
- second valid run for the same completed date → **already_archived**; and
- invalid Risk, Colossus, Market, Stock, or manifest data → failure with no published partial leaf.

The existing **jobs/s01_archive.ipynb** is a notebook wrapper around the same workflow. Schedule one entry point, not both.

## 2.13 Step 9 — put existing Market history in the correct place

If another governed process already produces Rebirth schema-v4 leaves, copy or mount each complete date directory under the configured root:

~~~text
D:\rebirth-private\histo\
  2026-08-28\
    risk.parquet
    colossus.parquet
    market.parquet
    _SUCCESS
  2026-08-31\
    risk.parquet
    colossus.parquet
    market.parquet
    stock.parquet
    _SUCCESS
~~~

Install without exposing a half-copied leaf to the Data page:

1. copy/download the complete date folders into a separate staging root on the same target volume;
2. run the strict structural, digest, and full value validation from Section 2.16 against that staging root;
3. verify the final **<PL_HISTORICAL_PATH>/<YYYY-MM-DD>** target does not already exist;
4. atomically rename the validated date directory into the final root; and
5. rerun strict validation on the final root before clearing the app cache.

The complete directory must appear at once. Never copy payloads directly into a visible final date folder, never expose **_SUCCESS** before its payloads, and never overwrite an existing completed date. The Data page polls archive generation and could otherwise observe a half-installed leaf.

Copy the whole immutable leaf. Do not copy only **market.parquet**, only **colossus.parquet**, or a loose collection of source files. A leaf with Stock must include Stock metadata and hash in its manifest; a leaf without Stock must not contain an undeclared Stock file.

Before switching the app to that root, run strict validation as shown in Section 2.16.

### If you only have raw historical Market rows

The current daily tool deliberately has no backfill-date argument. Do not force today's manager to an old display date, copy today's Risk into old folders, use test fixture snapshot types, or manufacture a manifest.

The easiest correct choices, in order, are:

1. obtain complete writer-produced schema-v4 leaves from the authoritative archive;
2. reconstruct a full coherent official snapshot for every date in a separate reviewed backfill job; or
3. design a new Market-only archive schema and repository as an explicit larger project.

For option 2, the backfill must supply, for each business date:

- **system_date** and **market_date** corresponding to that historical run;
- Market Status **OFFICIAL**;
- no snapshot errors;
- full mapped Risk/dashboard authority and exact Risk dates;
- full canonical MarketBook;
- the real Colossus data for that same date; and
- Stock for that date if the leaf declares Stock.

Write first to a new staging root using **archive_official_snapshot()**, validate every completed leaf, compare row counts/totals to source control totals, and only then switch **PL_HISTORICAL_PATH**. Do not mutate an existing completed root in place.

If only Market exists and there is no corresponding Risk and Colossus authority, the current schema deliberately cannot represent it as a completed Rebirth day.

## 2.14 Step 10 — leave the Data page wiring unchanged

The web app already performs all required wiring:

1. **app.py** resolves **PL_HISTORICAL_PATH**;
2. **cube/app/s07_factory.py** creates **ArchiveHistoryRepository** with that same root;
3. the **/data** route mounts a lazy shell;
4. Data callbacks load the Market catalogue only after interaction; and
5. **ArchiveSQLStore** opens an in-memory DuckDB view over selected **market.parquet** leaves with identity/date/column pushdown.

Do not add a startup scan or load all history into a Dash Store. That would make app startup and every browser session pay for the whole archive.

The Market-history identity is exactly one:

~~~text
Source Type + Risk Type + Risk Greek + raw Underlying
~~~

ProductSpec axes then determine whether the Data page renders a scalar, curve, or surface. Portfolio/reporting filters do not apply to Market history.

The archive column is still named **Current**. The Data page intentionally labels it **Official** in the browser. Do not rename the Parquet field to Official.

Observed dates drive WTD, MTD, YTD, 1Y, 5Y, All, and Custom periods. Missing dates/cells remain gaps/nulls, never zero. Current guardrails are 100,000 repository rows, 2,000 dates, 10,000 raw browser rows, and 16,000 canonical cells.

## 2.15 Step 11 — keep the Quick Market handoff small

Quick Market does not fetch history. **cube/pages/risk/s04_handoff.py** creates a typed handoff that tells **/data** which exact raw identity to open and uses the **current** metric.

The UUID is not inside **HistoryHandoff**. **_handoff_payload()** places **handoff.to_mapping()** beside a separate UUID-backed **nonce** used only as a small navigation/event trigger. It allows selecting the same row twice to retrigger navigation. It is not a quote identifier, not a Market data version, and not the cause of a connector refresh by itself.

Do not replace the handoff with the Market DataFrame or place Market history in a client-side Store. Keep **/data** as the only active Market-history workspace.

## 2.16 Step 12 — validate installed archive history strictly

Use the strict completed-day path outside interactive requests:

~~~python
from pathlib import Path

from cube.history import (
    list_completed_v4_archive_days,
    load_risk_archive,
    load_stock_archive_frame,
    open_history_database,
)

root = Path(r"D:\rebirth-private\histo")
days = list_completed_v4_archive_days(root)
assert days, f"No completed schema-v4 leaves under {root}"
assert all(day.market_rows > 0 for day in days)

# Full offline value/domain validation for externally installed leaves.
for day in days:
    archive = load_risk_archive(root, day.snapshot_date)
    assert archive.market is not None and not archive.market.empty
    if day.stock_path is not None:
        assert not load_stock_archive_frame(root, day.snapshot_date).empty

with open_history_database(root) as database:
    summary = database.execute(
        '''
        SELECT
            "Snapshot Date",
            count(*) AS rows,
            count(DISTINCT "Market Date") AS market_dates
        FROM market_history
        GROUP BY "Snapshot Date"
        ORDER BY "Snapshot Date"
        '''
    ).df()
    assert summary["market_dates"].eq(1).all()
    print(summary.tail())
~~~

**list_completed_v4_archive_days()** checks the manifest, exact file set, Parquet schemas, row counts, and SHA-256 hashes. The explicit **load_risk_archive()** and conditional **load_stock_archive_frame()** calls additionally run the full Risk, Colossus, Market, and optional Stock value/domain validators for every installed day. **open_history_database()** starts from strict completed-day validation and scans relation values such as Market Date versus Snapshot Date.

The interactive Data page deliberately uses **list_queryable_v4_archive_days()** and the lazy query database, which validate manifest/file/schema/row metadata but do not hash every whole file on every click. Run the strict check in deployment, after copying/downloading leaves, and on a schedule. Do not claim an interactive query rehashes the entire archive.

The catalogue is generation-cached and polled periodically. After externally installing valid leaves, use Data's **Clear Cache** action or restart the process. Never “refresh the cache” by weakening manifest validation.

## 2.17 Step 13 — smoke-test the exact Data-page query

Replace the identity values below with one real archived raw Underlying:

~~~python
from pathlib import Path

from cube.history import ArchiveHistoryRepository, HistoryQuery

root = Path(r"D:\rebirth-private\histo")
repository = ArchiveHistoryRepository(root)
entry = next(
    item
    for item in repository.catalog().entries
    if item.kind == "market"
    and item.identity.source_type == "ir/delta"
    and item.identity.risk_type == "IR"
    and item.identity.risk_greek == "Delta"
    and item.identity.underlying == "YOUR_RAW_UNDERLYING"
)
bundle = repository.read(
    HistoryQuery(handoff=entry.to_handoff(), period="mtd")
)

assert not bundle.empty
assert bundle.metric_column == "Current"
assert "Portfolio" not in bundle.raw_rows.columns
print(bundle.resolved_start, bundle.resolved_end, len(bundle.raw_rows))
~~~

Use the bounded MTD request for the first smoke test. Test 1Y/5Y/All separately only when the selected identity remains within the repository and browser row/cell budgets.

Check at least one exact row against its source:

~~~text
date + Source Type + Risk Type + Risk Greek + raw Underlying
+ Tenor Swap + Tenor Option -> Current
~~~

For one-axis history, missing date/tenor combinations must remain null in the canonical grid. For a two-axis product, verify both rank orders and one surface cell manually.

## 2.18 Tests to add or update for Market

### Live source and merge tests

Update **tests/s04_market.py**, **tests/s20_connectors.py**, and **tests/s07_integration.py** for:

- exact Market-state date and exact **Live/OFFICIAL** value;
- importing/building the manager and app performs no Market I/O; first I/O occurs inside refresh;
- one resolver call shared by all product connectors;
- Open receives T-1 business date;
- Current receives Market Date;
- both legs receive the same selected status;
- exact Risk-derived Underlying scope;
- scalar, one-axis, and two-axis ordered schemas;
- valid nullable quotes;
- empty genuine quote response;
- the direct boundary raises a sanitized transport failure rather than returning an invented empty response;
- duplicate Market keys fail;
- invalid, negative, fractional, or missing declared-axis ranks fail;
- Open wins a same-label Open/Current rank disagreement;
- disjoint labels or colliding ranks are densely renumbered deterministically;
- a one-leg quote gets the documented copy/status behavior;
- Market-only tenors remain in the committed MarketBook; and
- an operational **RuntimeError** becomes a coherent degraded snapshot with errors and is not archived;
- a contract/programming failure retains the previous coherent snapshot; and
- neither failure path partially mixes old and new Market data.

Also update **tests/s08_feeds.py**. Its current partition-cache and London 22:00 tests call the public temporary Market functions directly. After production replacement, move those fixture-only assertions to fixture/private helpers and test the public boundaries with a mocked approved client; never make unit tests call the real service.

### Archive and Data tests

Keep or extend **tests/s29_archive.py**, **tests/s30_history.py**, **tests/s31_data.py**, and **tests/s12_startup.py** for:

- Market schema, date, status, Move, identity, and rank validation;
- null quotes remain null;
- atomic publication and idempotent rerun;
- manifest Market row count/columns/hash;
- no partial leaf after a validation/write failure;
- cross-date rank conflicts fail history ordering;
- missing date/cell reindexing stays null;
- lazy and bounded catalogue/query behavior;
- the browser's fixed **Official** label over archived Current;
- direct selector and Quick Market handoff select the same identity;
- Clear Cache changes repository generation without bypassing validation; and
- Data remains the only active Market-history path.

Do not make tests depend on private production values. Use sanitized deterministic adapter responses and temporary archive roots.

## 2.19 Validate Part 2

Run the focused regression suites:

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests\s04_market.py tests\s07_integration.py tests\s08_feeds.py tests\s20_connectors.py tests\s29_archive.py tests\s30_history.py tests\s31_data.py tests\s12_startup.py -q -p no:cacheprovider
~~~

Then validate a non-production root:

1. run a Live refresh and confirm no daily leaf is published;
2. inject a sanitized OFFICIAL resolver, Market client, and real-contract Colossus fixture;
3. run the archive once and expect **archived**;
4. run it again and expect **already_archived**;
5. run **list_completed_v4_archive_days()**;
6. inspect one manifest's Market row count and hash;
7. query one exact identity through **ArchiveHistoryRepository**;
8. open **/data**, choose Market, and confirm the same Current/Official value; and
9. use Quick Market and confirm it opens the same Data identity without starting a connector call.

Only after this passes should the production scheduler use the durable root.

## 2.20 Common Part 2 failures

| Symptom | Most likely cause |
|---|---|
| Live Quick Market is empty | Connector returned wrong raw Underlying/keys or refresh retained last-good after an error |
| Every Move is zero | Source pre-copied one leg, or Open and Current point to the same upstream snapshot |
| Open is dated incorrectly | Connector ignored the manager-supplied T-1 date |
| Refresh rejects/retains last-good for Market status | A Current connector contradicted the one supplied Live/OFFICIAL value |
| Refresh/archive rejects tenor order | A declared order is missing, noninteger, negative, or otherwise invalid |
| Tenor order differs from the source expectation | Open/Current disagreed or ranks collided and the documented reconciliation changed the final order |
| Archive says skipped | Status is Live, date is not natural, or snapshot has refresh errors |
| Market works but no date folder appears | Part 4 Colossus is unconfigured/not FINAL/control-invalid, another enabled source failed, or scheduler/web roots differ |
| Data page shows no Market history | Leaf is incomplete/invalid, wrong root, stale catalogue generation, or identity differs |
| Historical Current appears under Official | Expected UI label; the stored column remains Current |
| One Underlying has two histories | Raw identity spelling changed across dates |
| Copied leaf is ignored | Only market.parquet was copied, file set/manifest/hash/schema is invalid |
| Interactive query opens but strict audit fails | Queryable validation intentionally skips whole-file digest checks |
| Startup becomes slow | History was loaded eagerly instead of leaving the existing lazy repository intact |

## 2.21 Part 2 done checklist

- [ ] Market-state service returns exactly **Live** or **OFFICIAL** once per refresh.
- [ ] Open uses supplied T-1 business date, raw Underlying, and selected status.
- [ ] Current uses supplied Market Date, raw Underlying, and the same status.
- [ ] Scalar, one-axis, and two-axis exact schemas pass.
- [ ] Quotes are finite numeric-or-null; true missing stays null.
- [ ] Exact Market keys are unique and tenor ranks are stable.
- [ ] Direct connector failures raise sanitized errors; manager operational degradation and contract-failure last-good behavior are both tested.
- [ ] Existing adapter coverage remains complete.
- [ ] Both FX Delta bulk fixture hooks are disabled or replaced together.
- [ ] Domain—not connector—owns leg merge, copy policy, status text, and Move.
- [ ] Committed full MarketBook includes Market-only tenors.
- [ ] Scheduler and web app use the same durable **PL_HISTORICAL_PATH**.
- [ ] Real Part 4 Colossus loader exists before publishing production history.
- [ ] Writer creates the entire immutable daily leaf; no file/manifest is hand-patched.
- [ ] Existing history is installed only as complete validated schema-v4 leaves.
- [ ] Strict completed-day/hash validation passes.
- [ ] ArchiveHistoryRepository returns an exact Current row for a known identity.
- [ ] Data page shows that value as Official with null-preserving gaps.
- [ ] Quick Market handoff opens the same identity without carrying data.
- [ ] Focused live, archive, history, Data, and startup tests pass.

---

# Part 3 — add Stock and Stock history

## 3.1 Treat current Stock and history as two deliveries

Current Stock is a two-date live read:

~~~text
GetStock(current Market Date)
+ GetStock(prior pandas business day)
  -> exact identity comparison
  -> Portfolio mapping
  -> /stock
~~~

Stock history is scheduled persistence:

~~~text
GetStock(official Market Date)
  -> unified archive writer
  -> stock.parquet + _SUCCESS
  -> SQLStockHistoryRepository
  -> /stock history chart
~~~

If current Stock works but history is empty, that is expected until completed daily archive leaves contain Stock.

## 3.2 Current Stock contract

The source must return exactly these columns in exactly this order:

~~~python
(
    "CRDS",
    "CPTY",
    "Portfolio",
    "Instrument",
    "Currency",
    "Quantity",
    "Market Value",
)
~~~

The current repository's **temporary** Stock identity is all five text columns:

~~~python
(
    "CRDS",
    "CPTY",
    "Portfolio",
    "Instrument",
    "Currency",
)
~~~

This is an implementation placeholder, not a proven production position key. Before copying the adapter code, prove the real governed key with the Stock source owner and with a representative date range:

1. obtain the documented source position key and its effective-date/version rules;
2. test uniqueness on several ordinary dates, month-end, new positions, closed positions, amendments, and corrections;
3. confirm whether multiple source lots may legitimately share CRDS + CPTY + Portfolio + Instrument + Currency;
4. keep **STOCK_IDENTITY_COLUMNS = STOCK_TEXT_COLUMNS** only if the source contract guarantees those five fields are unique per date;
5. if the real key is narrower, wider, or needs a stable Position ID, stop and change the Stock contract end to end before enabling the live feed.

Do not make a nonconforming real feed fit by aggregating rows or retaining an arbitrary first row in **_site_stock_source()**. That would destroy position identity before current comparison and history. A governed identity change must update, together:

- **cube/domain/s09_stock.py**: **STOCK_COLUMNS**, **STOCK_IDENTITY_COLUMNS**, comparison joins, and validation;
- **cube/adapters/s08_stock.py**: exact-history identity validation;
- **cube/history/s02_contracts.py** and **cube/history/s03_io.py**: archive/history contracts and manifest checks;
- **cube/pages/stock/s01_data.py** and **cube/pages/stock/s02_history.py**: current identity payloads, SQL predicates, and selected-history behavior;
- schema version/backfill policy if persisted columns or key semantics change;
- **tests/s17_stock.py**, **tests/s29_archive.py**, and startup tests.

The remaining steps use the current five-field temporary identity. Follow them unchanged only after that key passes the proof above.

Rules under that current contract:

- all five identity values are real, nonblank Python strings;
- Quantity and Market Value are finite numbers and are not booleans;
- negative numeric values are valid;
- one date cannot contain duplicate five-field identities;
- do not aggregate duplicates or keep an arbitrary first row;
- do not use **astype(str)** on nullable source fields, because null becomes the misleading string **nan**;
- Activity, SignoffGroup, Category, and Sub Category come from Portfolio configuration, not GetStock.

The current page calls the source twice:

1. current date;
2. current date minus one pandas business day.

The current code uses weekdays, not a holiday calendar. If the real source cannot serve the prior weekday on a holiday, deliberately replace date authority and add holiday tests; do not silently substitute another date inside the connector.

## 3.3 Step 1 — replace the temporary Stock source

The narrow boundary is **cube/adapters/s08_stock.py**.

Keep **StockConnectorAdapter**, **build_stock_adapter()**, **validate_stock_frame()**, and public **get_stock()**. Replace the temporary source at the bottom with a real synchronous source.

Recommended shape:

~~~python
def _site_stock_source(stock_date: pd.Timestamp) -> pd.DataFrame:
    selected = normalize_stock_date(stock_date)

    raw = YOUR_SYNC_STOCK_CLIENT.get_stock(
        as_of=selected.date().isoformat(),
        connect_timeout=5,
        read_timeout=30,
    )
    if not isinstance(raw, pd.DataFrame):
        raw = pd.DataFrame.from_records(raw)

    frame = raw.rename(
        columns={
            # "real_crds_field": "CRDS",
            # "real_counterparty_field": "CPTY",
            # "real_portfolio_field": "Portfolio",
            # "real_instrument_field": "Instrument",
            # "real_currency_field": "Currency",
            # "real_quantity_field": "Quantity",
            # "real_market_value_field": "Market Value",
        }
    )

    missing = [
        column
        for column in STOCK_COLUMNS
        if column not in frame.columns
    ]
    if missing:
        raise ValueError(f"Real Stock is missing columns: {missing}")

    frame = frame.loc[:, list(STOCK_COLUMNS)].copy(deep=True)
    frame = validate_stock_frame(
        frame,
        label=f"Stock for {selected.date().isoformat()}",
    )

    duplicate = frame.duplicated(
        list(STOCK_IDENTITY_COLUMNS),
        keep=False,
    )
    if duplicate.any():
        examples = (
            frame.loc[duplicate, list(STOCK_IDENTITY_COLUMNS)]
            .head(5)
            .to_dict("records")
        )
        raise ValueError(
            f"Real Stock contains duplicate identities: {examples}"
        )

    if frame.empty:
        raise ValueError(
            f"Real Stock is empty for {selected.date().isoformat()}"
        )
    return frame


_STOCK_ADAPTER = build_stock_adapter(stock=_site_stock_source)


def get_stock(stock_date: object) -> pd.DataFrame:
    return _STOCK_ADAPTER.get_stock(stock_date)


GetStock = get_stock
~~~

Also import **STOCK_IDENTITY_COLUMNS** if it is not already imported in the edited section; the current module already imports it.

Replace only the client call and rename mapping with site-specific details.

The client object imported or created at module scope must be configuration-only and lazy. Importing **cube.adapters.s08_stock** occurs during app construction; client construction must not authenticate, discover a remote schema, open a socket, or perform any other network I/O. The first remote operation belongs inside **_site_stock_source()**, when the Stock page or archive job actually invokes it.

Remove or stop using:

- **_temp_stock_source**;
- **_TEMP_STOCK_ADAPTER**;
- the fixture-only archive read as the current source.

The old fixture history helpers may remain for their tests, but the active public **get_stock()** must call the real source.

If live Stock has already been implemented somewhere else, do not create a second connector. Pass that existing validated callable into **build_app(stock_source=...)** and use the same callable in the archive scheduler below.

## 3.4 Step 2 — leave current Stock page logic unchanged

**app.py** already passes:

~~~python
stock_source=get_stock
stock_portfolio_source=get_portfolio_config
~~~

The existing chain:

~~~text
cube/pages/stock/s04_callbacks.py::load_current_stock
  -> cube/pages/stock/s01_data.py::load_stock_page_data
  -> source(current)
  -> source(prior)
  -> get_portfolio_config(current)
  -> map_stock_comparison_portfolios
  -> current pivot/table/detail
~~~

already owns lazy loading, four-entry process caching, filtering, table creation, and error display.

Do not add another Dash page or another current Stock callback. **/stock** is already registered as a native page.

## 3.5 Step 3 — verify Portfolio authority

The checked-in page currently maps Stock with **get_portfolio_config(current_date)**. That is not the same date authority used by Risk/P&L:

- the Stock callback explicitly passes **portfolio_date=current_date**;
- RiskRefreshManager passes its **checker_date**, normally Market Date minus one business day;
- P&L consumes the already mapped committed Risk snapshot rather than making a separate current-date config call.

The fixture hides this difference because it returns the same rows for every date. Before connecting a truly dated Portfolio source, choose and test one authority.

The smallest no-code choice is to keep current-date Stock mapping and document why Stock intentionally differs from Risk/P&L. If Stock must use the same Portfolio authority as Risk/P&L, change **cube/pages/stock/s04_callbacks.py::load_current_stock** from:

~~~python
portfolio_date=current_date,
~~~

to:

~~~python
portfolio_date=prior_date,
~~~

or pass the exact committed checker date if a later page-state change exposes it. Update **StockPageData.portfolio_date** and callback tests. Do not let the connector silently substitute one date for another.

Confirm:

- one row per Portfolio;
- required metadata columns are present;
- the merge is many Stock rows to one Portfolio row;
- unmapped Portfolios remain visible and explicitly unmapped;
- duplicates in Portfolio configuration fail rather than multiplying Stock.

Do not put Activity or Category into the GetStock contract.

## 3.6 Current Stock failure behavior

One failure in either the current or prior date read fails that current Stock load. The callback:

- logs **Could not load current Stock**;
- retains the previous loaded UI token;
- displays the failure in **stock-load-status**.

Do not catch source errors and return an empty DataFrame. An empty frame would disguise an unavailable source as a genuine zero-position day.

## 3.7 History contract

The Stock SQL repository returns exactly:

~~~python
(
    "Stock Date",
    "CRDS",
    "CPTY",
    "Portfolio",
    "Instrument",
    "Currency",
    "Quantity",
    "Market Value",
)
~~~

Rules:

- at most one row per Stock Date plus five-field identity;
- all rows match the exact requested identity;
- all dates are inside the requested range;
- an empty result still has the exact columns in the exact order;
- missing business dates stay missing and appear as chart gaps, never manufactured zeroes.

The page selection is initially CRDS + current Activity. The callback resolves that to one or more exact current five-field identities, queries each identity, and sums visible Market Value across them per date.

Historical Activity is not stored in Stock. If CPTY, Portfolio, Instrument, or Currency changes, that creates a separate exact query identity. The rendered page does **not** draw a separate trace for each identity: it loads every current identity matching the selected CRDS + Activity, concatenates their observations, and **stock_value_history_frame()** sums Market Value by date into one selected CRDS/Activity Stock trace (plus its dStock trace).

The current UI resolves selectable history identities from the current mapped Stock snapshot. An old identity that no longer exists cannot be selected through the normal CRDS + Activity workflow, so its earlier observations disappear from that chart. If continuity across identity changes is required, add a governed stable Stock ID/mapping contract; do not loosen the exact query or join identities by guesswork.

## 3.8 The current scheduled-archive gap

The current archive writer can store **stock_frame** when a test/fixture snapshot happens to expose one. The normal **RefreshSnapshot** does not have **stock_frame** or **stock_date**.

The current scheduled path:

~~~text
tools/s02_archive.py
  -> RiskRefreshManager refresh
  -> archive_from_manager(manager, colossus_loader, root)
~~~

therefore does not load real Stock.

The easiest contained fix is to add an optional **stock_loader** to the archive boundary. Do not put Stock into every Risk refresh and do not mutate the frozen snapshot.

## 3.9 Step 4 — add the StockLoader type

In **cube/history/s02_contracts.py**, immediately after:

~~~python
ColossusLoader = Callable[[pd.Timestamp], pd.DataFrame]
~~~

add:

~~~python
StockLoader = Callable[[pd.Timestamp], pd.DataFrame]
~~~

Add **StockLoader** to that module’s **__all__**.

In **cube/history/__init__.py**:

1. import **StockLoader** from **s02_contracts**;
2. add **StockLoader** to **__all__**.

## 3.10 Step 5 — add stock_loader to archive_official_snapshot

In **cube/history/s03_io.py**, import **StockLoader** with the other archive contracts.

Change the signature from:

~~~python
def archive_official_snapshot(
    snapshot: OfficialSnapshot,
    colossus_loader: ColossusLoader,
    root: str | Path,
) -> ArchiveResult:
~~~

to:

~~~python
def archive_official_snapshot(
    snapshot: OfficialSnapshot,
    colossus_loader: ColossusLoader,
    root: str | Path,
    *,
    stock_loader: StockLoader | None = None,
) -> ArchiveResult:
~~~

Keep the existing eligibility checks and existing completed-leaf no-op before any Stock call.

Find:

~~~python
raw_stock = getattr(snapshot, "stock_frame", None)
stock = None if raw_stock is None else validate_stock_archive_frame(raw_stock)
~~~

Replace it with:

~~~python
if stock_loader is not None and not callable(stock_loader):
    raise TypeError("stock_loader must be callable")

if stock_loader is not None:
    # A configured loader is authority. None/empty/malformed must fail rather
    # than silently publishing the day without Stock.
    raw_stock = stock_loader(pd.Timestamp(market_date))
    stock = validate_stock_archive_frame(raw_stock)
else:
    raw_stock = getattr(snapshot, "stock_frame", None)
    stock = (
        None
        if raw_stock is None
        else validate_stock_archive_frame(raw_stock)
    )
~~~

Then replace the later Stock Date block with explicit precedence:

~~~python
stock_date = market_date
if stock is not None and stock_loader is None:
    stock_date = _normalize_date(
        getattr(snapshot, "stock_date", snapshot.market_date),
        label="Stock Date",
    )
if stock is not None and stock_date != market_date:
    raise RiskArchiveValidationError(
        "Stock Date must match the archive Market Date"
    )
~~~

With an explicit loader, the Market Date passed to that loader is authoritative. Without it, legacy fixture snapshots may still supply **stock_frame** and **stock_date**.

A configured loader returning **None** is not the same as Stock being disabled. It must fail validation and block the complete leaf. Stock is optional only when **stock_loader is None** and the snapshot has no Stock frame.

Leave all other subsequent existing logic intact:

- Stock requires the canonical MarketBook/schema v4;
- Stock Date must equal Market Date;
- exact identity validation;
- write to a pending directory;
- create **stock.parquet**;
- include Stock columns, row count, date, and SHA-256 in **_SUCCESS**;
- write **_SUCCESS** last;
- atomically rename the pending directory.

Because the loader runs inside the writer before publication, a source failure or invalid frame leaves no completed daily leaf.

Update the writer docstring and archived-result reason/log message so operators can see that Stock is included when **stock_rows > 0**. Do not change the result status contract.

## 3.11 Step 6 — pass stock_loader through archive_from_manager

Change:

~~~python
def archive_from_manager(
    manager: object,
    colossus_loader: ColossusLoader,
    root: str | Path,
    *,
    refresh: bool = True,
) -> ArchiveResult:
~~~

to:

~~~python
def archive_from_manager(
    manager: object,
    colossus_loader: ColossusLoader,
    root: str | Path,
    *,
    refresh: bool = True,
    stock_loader: StockLoader | None = None,
) -> ArchiveResult:
~~~

Replace the final return with:

~~~python
return archive_official_snapshot(
    snapshot,
    colossus_loader,
    root,
    stock_loader=stock_loader,
)
~~~

This is backward compatible: callers that omit **stock_loader** keep the current optional-Stock behavior.

## 3.12 Step 7 — resolve Stock in the scheduled job

In **tools/s02_archive.py**:

1. import **StockLoader** from **cube.history**;
2. add a resolver parallel to the Colossus resolver;
3. add **stock_loader** to **run_scheduled_archive()**;
4. pass it through;
5. print **stock_rows**.

Add:

~~~python
def resolve_stock_loader(
    value: str | None,
) -> StockLoader | None:
    reference = str(value or "").strip()
    if not reference:
        return None

    module_name, separator, attribute_name = reference.partition(":")
    if (
        not separator
        or not module_name.strip()
        or not attribute_name.strip()
    ):
        raise ValueError(
            "STOCK_LOADER must use the form 'module:function'"
        )

    module = importlib.import_module(module_name.strip())
    loader = getattr(module, attribute_name.strip(), None)
    if not callable(loader):
        raise TypeError(
            f"Configured Stock loader is not callable: {reference}"
        )
    return loader
~~~

Change the scheduled signature to:

~~~python
def run_scheduled_archive(
    *,
    environ: Mapping[str, str] | None = None,
    manager_factory: Callable[[], object] | None = None,
    colossus_loader: ColossusLoader | None = None,
    stock_loader: StockLoader | None = None,
) -> ArchiveResult:
~~~

Inside it, resolve and pass Stock:

~~~python
values = os.environ if environ is None else environ
root = resolve_archive_root(values)
loader = (
    colossus_loader
    or resolve_colossus_loader(values.get("COLOSSUS_LOADER"))
)
resolved_stock_loader = (
    stock_loader
    if stock_loader is not None
    else resolve_stock_loader(values.get("STOCK_LOADER"))
)
manager = (manager_factory or _default_manager_factory)()

return archive_from_manager(
    manager,
    loader,
    root,
    refresh=True,
    stock_loader=resolved_stock_loader,
)
~~~

Update the main print:

~~~python
print(
    f"{result.status}: {result.reason} date={result.market_date} "
    f"risk_rows={result.risk_rows} "
    f"colossus_rows={result.colossus_rows} "
    f"stock_rows={result.stock_rows} "
    f"path={result.path}"
)
~~~

Add **resolve_stock_loader** to **__all__**.

Do not default the scheduler to the checked-in temporary Stock history loader. That loader supports fixture dates and reads archives; pointing a writer at its own output root can create a circular dependency.

**STOCK_LOADER** must resolve to a top-level callable function. A **StockConnectorAdapter** instance is not itself callable. Export a wrapper such as **cube.adapters.s08_stock:get_stock**, which then calls its adapter’s **get_stock()** method.

Once the real source is active, configure:

~~~powershell
$env:STOCK_LOADER = 'cube.adapters.s08_stock:get_stock'
~~~

If the real callable lives elsewhere, use that exact **module:function**.

Enable this variable before the first official archive job for a new date. If the date was already completed without Stock, rerunning returns **already_archived** and intentionally does not add Stock.

### Stock must also be official

The existing archive eligibility gate knows only the Risk/Market snapshot’s **market_status**. It has no separate Stock readiness flag. A current-date Stock source may still be provisional when Market becomes OFFICIAL.

Before enabling the job, require both:

1. Market is OFFICIAL; and
2. the site’s Stock EOD is final and immutable for that date.

The scheduler’s **get_stock(date)** must return the same official result on every retry. Schedule the job after both authorities are final. If timing cannot guarantee that, add a site-owned Stock-readiness resolver/status gate to **run_scheduled_archive()** and test that the writer is not called until it is final.

Once **STOCK_LOADER** is configured, a Stock timeout, source error, empty response, duplicate identity, or schema failure blocks publication of the entire Risk/Market/Colossus/Stock leaf. That all-or-nothing behavior is intentional.

## 3.13 Step 8 — leave SQLStockHistoryRepository and the page unchanged

**app.py** already resolves the root and passes the repository inline:

~~~python
history_path = resolve_data_path(
    os.getenv("PL_HISTORICAL_PATH"),
    Path("data/histo"),
    root=project_root,
)

return build_app(
    ...,
    stock_history_source=SQLStockHistoryRepository(history_path),
    ...,
)
~~~

and passes it into **build_app()**.

The repository is lazy:

- construction does no filesystem or DuckDB work;
- first query discovers completed schema-v4 leaves;
- only leaves containing **stock.parquet** enter the Stock view;
- queries are exact identity/date predicate pushdowns;
- the process connection is reused until the archive generation changes;
- Clear Cache closes it.

No Stock page change is required.

## 3.14 Never patch a completed leaf by hand

A completed daily leaf is immutable.

Never:

- copy **stock.parquet** into an existing completed folder;
- edit **_SUCCESS**;
- overwrite one file in place;
- leave extra files inside the leaf.

There are two validation levels; do not describe them as equivalent:

- **list_completed_v4_archive_days()** is the strict path. It checks the exact file set, manifest, schema/order, row counts, and SHA-256 digests.
- the interactive Stock SQL path uses **list_queryable_v4_archive_days()**. It checks completion metadata, exact file presence, Parquet schema/order, and row counts, but deliberately calls the cached validator with **verify_digests=False** to avoid hashing entire files during page use.

A partial folder without **_SUCCESS** stays hidden. Wrong file sets, schema, or row counts fail both paths. However, same-shape value corruption can pass the interactive query path until a separate strict digest check runs.

If hash integrity is an operational promise, add a strict publish gate after every scheduled write and before exposing/promoting the archive root:

~~~python
from cube.history import list_completed_v4_archive_days

strict_days = list_completed_v4_archive_days(archive_root)
if not any(
    day.snapshot_date == result.market_date
    for day in strict_days
):
    raise RuntimeError("Strict archive validation did not find the new date")
~~~

Run the same strict validation on a schedule to detect later disk/object-store corruption. Do not rely on opening the Stock page to verify hashes.

The normal scheduled manager cannot backfill Stock into past completed leaves:

- a completed date is a no-op; and
- **archive_official_snapshot()** rejects a historical Market Date unless it is the natural Market Date for the supplied snapshot System Date.

For a governed offline backfill:

1. choose a new empty archive root;
2. for every historical date, reconstruct one complete coherent OfficialSnapshot containing that date’s Risk, Market, revision, and per-source Risk Dates;
3. set that reconstructed snapshot’s System Date so **market_date_for(system_date)** resolves to the historical Market Date;
4. load that date’s complete Colossus and Stock;
5. call the same archive writer to produce the whole leaf;
6. validate every leaf and the full new root;
7. compare counts/totals to the existing archive;
8. stop scheduler and app;
9. switch **PL_HISTORICAL_PATH** to the validated root;
10. keep the old root as rollback.

This is a full-leaf migration, not a Stock-only backfill. It needs an approved migration script and tests; never patch existing leaves.

## 3.15 Alternative: query an existing historical Stock database

If company history already exists and must not be copied to Parquet, implement **StockHistoryQueryProtocol**:

~~~python
class StockHistoryQueryProtocol(Protocol):
    def clear(self) -> None: ...

    def catalog(
        self,
        search: object = None,
        *,
        limit: int = 50,
    ) -> StockHistoryCatalogResult: ...

    def rows(
        self,
        identity: Mapping[str, object],
        start_date: object,
        end_date: object,
    ) -> pd.DataFrame: ...
~~~

Then pass the repository to:

~~~python
build_app(
    ...,
    stock_history_source=YOUR_STOCK_HISTORY_REPOSITORY,
)
~~~

Choose this or the archive route, not both.

The protocol repository must:

- return **StockHistoryCatalogResult** from **catalog()**;
- return the exact eight-column history frame from **rows()**;
- bound selector/search queries;
- filter by exact five-field identity and date in the database;
- implement **clear()**;
- perform no history preload during app import.

## 3.16 Tests to add for Stock

### Current source tests

In **tests/s17_stock.py**, add or retain:

- raw source names rename to exact canonical order;
- blank identity rejected;
- nonfinite/boolean numeric rejected;
- duplicate identity rejected;
- current and prior dates both passed to source;
- one unmapped Portfolio retained;
- no source DataFrame mutation.

Replacing public **get_stock()/GetStock** changes two existing fixture tests. Retarget them so unit tests do not call the live client:

- **test_checked_in_legacy_v4_stock_is_validated_and_varies_by_date** should call **load_stock_archive_leaf(STOCK_ARCHIVE_ROOT, date)** directly;
- **test_stock_history_loader_projects_one_exact_identity** should derive its identity from that fixture leaf/helper frame rather than public **get_stock()**.

Add separate mocked tests for **_site_stock_source()** and the public validated wrapper. Never let the test suite depend on a real network or credentials.

### History boundary tests

In **tests/s17_stock.py**, cover:

- exact empty-result schema;
- exact identity/date bounds;
- duplicate dated identity rejection;
- row from another identity rejection;
- missing business date remains a chart gap;
- identity drift creates a different exact query identity, and the page combines all currently selected CRDS/Activity identities into one date-summed trace.

### Archive writer tests

In **tests/s29_archive.py**, add:

1. snapshot without **stock_frame** plus injected **stock_loader** produces Stock;
2. loader receives exactly the archive Market Date;
3. manifest has exact Stock date, rows, columns, and hash;
4. loader is not called when date/status/errors make the archive ineligible;
5. loader is not called for an already completed date;
6. loader exception publishes no completed leaf;
7. empty, duplicate, or invalid Stock publishes no completed leaf;
8. a configured loader returning **None** fails instead of silently omitting Stock;
9. **archive_from_manager()** passes the loader after exactly one coherent refresh;
10. scheduled wrapper resolves and passes **STOCK_LOADER**;
11. an explicit loader uses Market Date even when a legacy snapshot has stale **stock_date**;
12. legacy snapshot Stock still validates its supplied **stock_date**;
13. a completed date without Stock remains an intentional no-op;
14. any implemented Stock-readiness gate prevents publication before Stock is final.

Example assertion shape:

~~~python
called = []


def stock_loader(stock_date):
    called.append(pd.Timestamp(stock_date))
    return valid_stock_frame()


result = archive_official_snapshot(
    snapshot_without_stock,
    valid_colossus_loader,
    archive_root,
    stock_loader=stock_loader,
)

assert result.status == "archived"
assert called == [pd.Timestamp(snapshot_without_stock.market_date)]
assert result.stock_rows == len(valid_stock_frame())
assert (result.path / "stock.parquet").is_file()
~~~

### App wiring tests

In **tests/s12_startup.py**, prove:

- the same real Stock current source is bound;
- SQL/protocol history source is bound;
- cold app construction does not call either source;
- **/stock** remains available;
- history controls reflect whether history is configured;
- prefixed deployment routes still work.

## 3.17 Validate Part 3

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests\s17_stock.py -q -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m pytest tests\s29_archive.py -q -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m pytest tests\s12_startup.py -q -p no:cacheprovider
~~~

Before using the production root:

1. point **PL_HISTORICAL_PATH** to a temporary sandbox root;
2. inject a sanitized manager, Colossus loader, and Stock loader;
3. run one scheduled archive;
4. inspect the five expected files;
5. call **list_completed_v4_archive_days(root)**;
6. construct **SQLStockHistoryRepository(root)**;
7. call **catalog()** and one exact **rows()** query;
8. open the Stock page and load that identity.

## 3.18 Common Part 3 failures

| Symptom | Most likely cause |
|---|---|
| Entire current Stock load fails | Current or prior date source failed |
| Stock current works, history is empty | Scheduler never wrote stock.parquet, wrong root, or selected identity changed |
| Columns error | Wrong names/order or extra source columns were not projected out |
| Duplicate comparison/archive error | The temporary five-field identity is not unique; prove the governed source key and update the full contract rather than aggregating in the adapter |
| Portfolio metadata multiplies rows | Portfolio config is not one row per Portfolio |
| History controls say not configured | No stock_history_source passed to build_app |
| History query returns no match | Current CRDS/Activity resolves a different exact identity than historical rows |
| DuckDB union fails | One completed day has a different Stock schema/order |
| New leaf does not appear | Root is wrong, leaf is incomplete/invalid, or the date was already completed without Stock |
| Interactive Stock query rejects a completed leaf | Row count, schema, date, manifest, or exact file set is invalid |
| Strict archive validation rejects a leaf that the page queried | SHA-256 differs even though the interactive path deliberately skipped digest verification |

## 3.19 Part 3 done checklist

- [ ] Live synchronous source returns exact seven-column Stock schema.
- [ ] Current and prior dates are supported.
- [ ] Real governed Stock key is documented and tested; the temporary five-field identity is retained only if it is truly unique.
- [ ] Portfolio metadata remains outside Stock source.
- [ ] Current-date versus checker-date Portfolio authority is explicitly chosen and tested.
- [ ] App still uses the existing Stock page/callback.
- [ ] StockLoader type and optional writer parameter added.
- [ ] Scheduler resolves and passes the same real Stock callable.
- [ ] A configured Stock loader returning None/empty/malformed blocks publication rather than disabling Stock.
- [ ] Stock EOD is final before the first immutable official write.
- [ ] Stock is written only as part of a complete schema-v4 leaf.
- [ ] A scheduled/publish gate calls **list_completed_v4_archive_days()** so digest integrity is checked outside the interactive page.
- [ ] App and scheduler use the same durable PL_HISTORICAL_PATH.
- [ ] Current, history, archive, and startup tests pass.
- [ ] One sandbox archive is queryable through SQLStockHistoryRepository.

---

# Part 4 — add P&L, Colossus history, and optional outbound sends

## 4.1 First decide which “P&L” is being added

There are three separate meanings:

### Predict/current P&L

Calculated inside Rebirth from:

~~~text
Risk + Open + Current + ProductSpec formula/multiplier
~~~

There is no independent current Predict-P&L connector.

### Colossus actual P&L

Loaded once per official day at archive time. It supplies:

- historical actual values;
- Predict-versus-Colossus validation;
- MTD/YTD actuals in the P&L overview.

### Outbound P&L

Governed Predict rows sent to:

- SOG; and
- Portfolio.

The two checked-in send functions deliberately fail closed until replaced.

## 4.2 Current Predict chain

~~~text
get_product_connector_adapters()
  -> RiskRefreshManager.refresh()
  -> get_product_pl()
  -> _release_pl_views()
  -> RefreshSnapshot.combined_pl
  -> RiskRefreshManager.pl_snapshot
  -> P&L mapping/governance/adjustments
  -> send editors and send callbacks
~~~

**get_product_pl()**:

- validates Risk;
- validates Open/Current MarketBook;
- joins many Risk rows to one quote;
- applies the ProductSpec move convention and multiplier;
- uses separate Taylor-Gamma behavior;
- leaves unavailable market P&L as NaN in **combined_pl** rather than zero; the separate archive/display zero-fill caveat is covered in Step 4.8A.

**_release_pl_views()**:

- concatenates product P&L and governed overlays;
- maps Portfolio metadata;
- attaches reported identities/promotions;
- commits **combined_pl** for sending;
- creates mapped **dashboard_frame** for display/history;
- creates **unmapped_frame**.

Do not fetch a competing current P&L frame inside **cube/pages/pnl**. If Predict is missing or wrong, fix the owning Risk/Open/Current adapter, ProductSpec formula/multiplier, or Portfolio authority.

## 4.3 Step 1 — connect current Predict through product sources

For every product that should contribute:

1. confirm a ProductSpec exists;
2. return exact validated Risk at its resolved Risk Date;
3. return Open for the required Open Date;
4. return Current for the Market Date/status;
5. preserve one quote per product market identity;
6. register the adapter in **get_product_connector_adapters()**;
7. provide Portfolio configuration;
8. refresh with **force_risk=True, force_pl=True**;
9. inspect **manager.pl_snapshot.combined_pl**.

Use:

~~~python
snapshot = manager.refresh(
    force_risk=True,
    force_pl=True,
    reason="verify_real_predict_pl",
)

pl_snapshot = manager.pl_snapshot
print(pl_snapshot.revision)
print(pl_snapshot.market_date)
print(
    pl_snapshot.combined_pl[
        [
            "Market Date",
            "Risk Type",
            "Risk Greek",
            "Underlying",
            "Portfolio",
            "PL",
        ]
    ].head()
)
~~~

Verify:

- Market Date is the selected committed date;
- missing market remains missing;
- mapped and unmapped Portfolios are truthful;
- no duplicate market quote multiplied Risk rows;
- P&L agrees with a hand calculation for each ProductSpec formula.

## 4.4 Step 2 — keep the Concerto mapping complete

The default mapping is **data/s08_concerto.csv**, or the path in **CONCERTO_MAPPING_PATH**.

Exact schema/order:

~~~csv
Risk Type,Risk Greek,ConcertoField
~~~

Rules:

- nonempty;
- Risk Type + Risk Greek unique;
- ConcertoField unique;
- every mapped pair in current P&L must exist;
- labels must match canonical ProductSpec labels.

For a new product pair, add one row, for example:

~~~csv
IR,Basis,irbasiseffect
~~~

Do not reuse a ConcertoField for two pairs.

## 4.5 Step 3 — verify Portfolio governance

Real **get_portfolio_config(portfolio_date)** must provide the ordered required fields:

~~~text
Portfolio
Product
Activity
SignoffGroup
Category
~~~

**Sub Category** is optional where the existing contract permits it.

There must be one row per Portfolio. The P&L send path:

- keeps only explicitly mapped Portfolio rows in the governed base;
- rejects conflicting SignoffGroup/metadata;
- filters governed Portfolios before aggregation;
- sums one row per Market Date + Portfolio + ConcertoField.

The archive writes the mapped **dashboard_frame**, not all of **combined_pl**. A Predict Portfolio missing from the dated Portfolio configuration is therefore absent from Predict history, while an unknown Colossus Portfolio can still appear as **Unmapped**.

Before production, fail a coverage check for every Portfolio whose Predict history is required:

~~~python
required = set(REQUIRED_PREDICT_PORTFOLIOS)
mapped = set(
    pl_snapshot.combined_pl.loc[
        pl_snapshot.combined_pl["Portfolio Mapped"].eq(True),
        "Portfolio",
    ]
)
missing = required - mapped
assert not missing, (
    f"Required Predict Portfolios are unmapped: {sorted(missing)}"
)
~~~

Replace **REQUIRED_PREDICT_PORTFOLIOS** with the approved inventory. Do not interpret an omitted unmapped Predict Portfolio as zero activity.

## 4.6 Understand adjustment behavior

Internal domain rows use exactly:

~~~python
(
    "Market Date",
    "Risk Type",
    "Risk Greek",
    "Portfolio",
    "SignoffGroup",
    "ConcertoField",
    "PL",
    "Adjustment",
)
~~~

The key is:

~~~text
Market Date + Portfolio + ConcertoField
~~~

An adjustment replaces the base row at that key. It is not added on top of it.

The current local repository writes atomically under:

~~~text
adjustments/YYYY-MM-DD/
  <safe-portfolio>--<hash-prefix>.csv
~~~

It also records Base Revision, Saved At UTC, and Adjustment ID and rejects stale revisions.

If adjustments must survive a deploy/restart, **PL_ADJUSTMENT_PATH** must be on a durable mounted path or the repository must be replaced by an approved durable implementation of the same protocol. This applies even to one worker when its container filesystem is ephemeral. Multi-host deployments additionally require shared storage and concurrency-safe writes; a local host directory is not shared state.

## 4.7 Step 4 — replace outbound sender stubs only if sending is required

The stubs are:

- **cube/services/s05_sources.py::send_sog_pl**;
- **cube/services/s05_sources.py::send_portfolio_pl**.

Keep the signature:

~~~python
def send_sog_pl(frame: pd.DataFrame) -> None:
    ...


def send_portfolio_pl(frame: pd.DataFrame) -> None:
    ...
~~~

Despite the eight-column internal schema, current callbacks pass senders exactly these seven columns:

~~~python
(
    "Risk Type",
    "Risk Greek",
    "Portfolio",
    "SignoffGroup",
    "ConcertoField",
    "PL",
    "Adjustment",
)
~~~

The sender implementation should:

1. require a DataFrame;
2. require the exact seven-column order;
3. validate finite numeric PL;
4. send a defensive copy;
5. apply explicit connect/read timeouts;
6. return only after acknowledged success;
7. raise on timeout, rejection, or partial destination failure;
8. use destination idempotency where available;
9. never log the payload, credentials, URLs with query values, response bodies, or financial values;
10. never let a raw client/HTTP exception reach the Dash callback, because the current callback includes **str(exc)** in the user-visible status.

Example shape:

~~~python
import logging

import numpy as np


LOGGER = logging.getLogger(__name__)


_DELIVERY_COLUMNS = (
    "Risk Type",
    "Risk Greek",
    "Portfolio",
    "SignoffGroup",
    "ConcertoField",
    "PL",
    "Adjustment",
)


def _validated_delivery(frame: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("P&L sender expects a pandas DataFrame")
    if tuple(frame.columns) != _DELIVERY_COLUMNS:
        raise ValueError(
            "P&L sender received the wrong columns or column order"
        )

    payload = frame.copy(deep=True)
    boolean = payload["PL"].map(
        lambda value: isinstance(value, (bool, np.bool_))
    )
    numeric = pd.to_numeric(payload["PL"], errors="coerce")
    if (
        boolean.any()
        or numeric.isna().any()
        or not np.isfinite(numeric).all()
    ):
        raise ValueError("P&L sender received nonfinite PL")
    payload["PL"] = numeric.astype(float)
    return payload


def _send_with_client(
    payload: pd.DataFrame,
    *,
    client: object,
    destination: str,
) -> None:
    try:
        receipt = client.send(
            payload.to_dict("records"),
            connect_timeout=5,
            read_timeout=30,
        )
        acknowledged = bool(getattr(receipt, "acknowledged", False))
    except Exception as exc:
        # Deliberately log only approved metadata. Do not use LOGGER.exception(),
        # exc_info=True, repr(exc), or str(exc): client exceptions can contain
        # URLs, headers, request bodies, or response bodies.
        LOGGER.error(
            "P&L delivery transport failed",
            extra={
                "destination": destination,
                "failure_type": type(exc).__name__,
            },
        )
        # The Dash callbacks currently render str(exc), so this message must be
        # safe for every user who can see the page. `from None` suppresses the
        # sensitive client exception as chained context.
        raise RuntimeError(
            f"{destination} P&L delivery failed; see approved server logs"
        ) from None

    if not acknowledged:
        LOGGER.error(
            "P&L delivery was not acknowledged",
            extra={"destination": destination},
        )
        raise RuntimeError(
            f"{destination} did not acknowledge P&L"
        )


def send_sog_pl(frame: pd.DataFrame) -> None:
    payload = _validated_delivery(frame)
    _send_with_client(
        payload,
        client=AUTHORIZED_SOG_CLIENT,
        destination="SOG",
    )


def send_portfolio_pl(frame: pd.DataFrame) -> None:
    payload = _validated_delivery(frame)
    _send_with_client(
        payload,
        client=AUTHORIZED_PORTFOLIO_CLIENT,
        destination="Portfolio",
    )
~~~

Replace only client-specific calls and response checks. Preserve the sanitized boundary: catch transport/response exceptions inside the sender and raise a fixed safe message **from None**. Unit-test this with a client exception containing a fake secret, URL query, and response body; assert none appears in the raised message, Dash status, or captured approved log fields.

**Send All is not transactional.** SOG may succeed while Portfolio fails. The UI reports partial success.

### Important missing context in the current sender payload

The seven-column callback payload does not include Market Date or snapshot revision.

If the endpoint requires either:

- do not infer it from wall-clock time;
- do not read a module global;
- deliberately extend the sender contract and callbacks to carry trusted server-side context;
- update both destinations and tests together.

That is a separate contract change. Do not silently hide it inside the sender.

## 4.8 Current P&L overview is archive-backed

The upper P&L overview uses **SQLPLHistoryRepository.risk_summary()**.

Its “Current” value means:

~~~text
latest archived Predict value
~~~

It is not the warm **manager.pl_snapshot**.

The send editors below it use the live committed snapshot. Therefore:

- before today’s archive runs, the upper overview can show the prior date;
- send data can simultaneously be current.

The easiest correct solution is to run the official archive after OFFICIAL is available. Making the upper overview merge live and archived data is a separate feature with new authority and matching rules.

### 4.8A — decide the archived missing-P&L policy

The live calculation and the current archive do not have the same missingness behavior:

1. **combined_pl** preserves unavailable market P&L as NaN;
2. **to_dashboard_frame()** calls **_zero_fill_dashboard_metrics()** and converts null PL to 0.0 for display;
3. **archive_official_snapshot()** currently archives **snapshot.dashboard_frame**;
4. therefore current **risk.parquet** cannot distinguish an unavailable Predict PL from a genuine zero.

The SQL view contains a completeness guard, but it cannot recover information that was already zero-filled before persistence.

The easiest hookup is to accept and explicitly document the existing display-zero policy. If the business requires historical missingness to remain truthful, build the archive projection from the same-revision **snapshot.combined_pl** inside the scheduled writer. This avoids retaining a third large DataFrame in every live worker.

In **cube/history/s03_io.py**, import:

~~~python
from cube.domain.s02_products import PL, PORTFOLIO_MAPPED
from cube.domain.s07_governance import to_dashboard_frame
~~~

Replace:

~~~python
risk = validate_risk_archive_frame(snapshot.dashboard_frame)
~~~

with:

~~~python
raw_combined_pl = getattr(snapshot, "combined_pl", None)
if isinstance(raw_combined_pl, pd.DataFrame):
    mapped = raw_combined_pl.loc[
        raw_combined_pl[PORTFOLIO_MAPPED].eq(True)
    ]
    archive_projection = to_dashboard_frame(mapped)
    archive_projection[PL] = mapped[PL].to_numpy(copy=True)
    raw_risk_archive = archive_projection
else:
    # Backward compatibility for minimal legacy/test OfficialSnapshot objects.
    raw_risk_archive = snapshot.dashboard_frame

risk = validate_risk_archive_frame(raw_risk_archive)
~~~

This keeps the archive mapped and in exact dashboard column order while restoring authoritative PL after the display projection zero-fills it. The real RefreshSnapshot’s **combined_pl**, MarketBook, dashboard, and metadata are already part of the same atomic revision.

Add tests proving:

- live **combined_pl** has NaN when market is unavailable;
- display **dashboard_frame** has the current deliberate 0.0;
- **risk.parquet** retains it;
- SQL excludes that incomplete Predict group rather than displaying zero.

If this hardening is not implemented, document historical Predict zero-fill as current behavior and do not claim that an archived zero proves market availability.

## 4.9 Colossus actual history contract

The site loader signature is:

~~~python
def get_colossus_pl(
    market_date: pd.Timestamp,
) -> pd.DataFrame:
    ...
~~~

It must return exactly:

~~~python
(
    "Portfolio",
    "Underlying",
    "Risk Type",
    "Risk Greek",
    "PL",
)
~~~

Rules:

- exact column order;
- at least one row;
- first four columns nonblank text;
- first four columns form a unique key;
- PL is finite and nonboolean;
- Product is deliberately absent.

The semantic contract is equally important:

- **PL is one-day/DTD official actual P&L for exactly the requested Market Date**;
- it is not MTD, YTD, inception-to-date, or another cumulative value—the SQL repository sums daily values to build MTD/YTD, so a cumulative input would be double-counted;
- values are already converted to the approved reporting currency and unit;
- the sign convention is the approved Rebirth/Colossus convention;
- Underlying should use the same raw identity as archived Risk; and
- Risk Type/Risk Greek should use canonical ProductSpec labels.

The current structural **validate_colossus_frame()** enforces the five-column shape, text/key rules, and finite PL. It cannot prove source date, finality, DTD semantics, currency, unit, sign, or completeness because none of those fields remain in the canonical frame. It also does not reject an unknown Underlying or Risk pair; unmatched actuals remain valid Colossus-only/**Unmapped** rows. The loader must validate the upstream metadata and control totals before projecting them away. Add explicit governed identity/allowlist reconciliation in the loader if production policy requires unknown identities to fail instead.

Do not add Product by duplicating or arbitrarily deduplicating Colossus rows. If the business requires Product-level actuals for one multi-product Portfolio, that needs a deliberate archive schema revision across contract, writer, manifest, SQL projection, migrations, and tests.

## 4.10 Step 5 — replace get_colossus_pl

In **cube/services/s05_sources.py**, replace the temporary body of **get_colossus_pl()**.

Recommended shape:

~~~python
import math
from collections.abc import Mapping


def _colossus_market_date(value: object) -> pd.Timestamp:
    selected = pd.Timestamp(value)
    if pd.isna(selected):
        raise ValueError("market_date must not be blank or NaT")
    if selected.tzinfo is not None:
        selected = selected.tz_localize(None)
    return selected.normalize()


def _validated_colossus_payload(
    payload: object,
    *,
    metadata: Mapping[str, object],
    selected: pd.Timestamp,
) -> pd.DataFrame:
    required_metadata = {
        "market_date",
        "status",
        "row_count",
        "pl_total",
        "pnl_basis",
        "currency",
        "unit",
        "sign_convention",
    }
    missing_metadata = sorted(required_metadata - set(metadata))
    if missing_metadata:
        raise ValueError(
            f"Colossus controls are missing fields: {missing_metadata}"
        )

    source_date = _colossus_market_date(metadata["market_date"])
    if source_date != selected:
        raise ValueError("Colossus source date does not match requested Market Date")
    if metadata["status"] != "FINAL":
        raise RuntimeError("Colossus is not final for the requested Market Date")

    expected_metadata = {
        "pnl_basis": "DTD",
        "currency": APPROVED_COLOSSUS_REPORTING_CURRENCY,
        "unit": APPROVED_COLOSSUS_UNIT,
        "sign_convention": APPROVED_COLOSSUS_SIGN_CONVENTION,
    }
    for field, expected in expected_metadata.items():
        if metadata[field] != expected:
            raise ValueError(f"Colossus {field} does not match approved policy")

    expected_rows = metadata["row_count"]
    if type(expected_rows) is not int or expected_rows < 1:
        raise ValueError("Colossus row_count control must be a positive integer")
    if isinstance(metadata["pl_total"], bool):
        raise ValueError("Colossus PL control total must be numeric")
    try:
        expected_total = float(metadata["pl_total"])
    except (TypeError, ValueError):
        raise ValueError("Colossus PL control total must be numeric") from None
    if not math.isfinite(expected_total):
        raise ValueError("Colossus PL control total must be finite")

    try:
        raw = (
            payload.copy(deep=True)
            if isinstance(payload, pd.DataFrame)
            else pd.DataFrame.from_records(payload)
        )
    except (TypeError, ValueError):
        raise ValueError("Colossus rows could not be normalized") from None
    frame = raw.rename(
        columns={
            # "real_portfolio": "Portfolio",
            # "real_underlying": "Underlying",
            # "real_risk_type": "Risk Type",
            # "real_risk_greek": "Risk Greek",
            # "real_pl": "PL",
        }
    )
    if frame.columns.duplicated().any():
        raise ValueError("Colossus response has duplicate canonical columns")
    missing = [
        column
        for column in COLOSSUS_COLUMNS
        if column not in frame.columns
    ]
    if missing:
        raise ValueError(f"Colossus P&L is missing columns: {missing}")

    answer = validate_colossus_frame(
        frame.loc[:, list(COLOSSUS_COLUMNS)].copy(deep=True)
    )
    if len(answer) != expected_rows:
        raise ValueError("Colossus row count does not match its source control")
    if not math.isclose(
        float(answer["PL"].sum()),
        expected_total,
        rel_tol=0.0,
        abs_tol=APPROVED_COLOSSUS_TOTAL_TOLERANCE,
    ):
        raise ValueError("Colossus PL does not match its source control total")
    return answer


def get_colossus_pl(
    market_date: pd.Timestamp,
) -> pd.DataFrame:
    selected = _colossus_market_date(market_date)

    try:
        response = AUTHORIZED_COLOSSUS_CLIENT.get_pl(
            as_of=selected.date().isoformat(),
            connect_timeout=5,
            read_timeout=30,
        )
    except AUTHORIZED_COLOSSUS_OPERATIONAL_ERRORS:
        raise RuntimeError(
            "Colossus source failed for the requested Market Date"
        ) from None
    if not isinstance(response, Mapping) or "rows" not in response:
        raise TypeError("Colossus client must return rows plus source controls")
    return _validated_colossus_payload(
        response["rows"],
        metadata=response,
        selected=selected,
    )
~~~

Use the current imported **COLOSSUS_COLUMNS** and **validate_colossus_frame**. Define the four **APPROVED_COLOSSUS_...** values from governed configuration: reporting currency, unit, sign convention, and an explicit control-total tolerance appropriate to that unit. Do not guess them in this guide. If the validator is not imported directly in this module after your edit, import it from **cube.history**.

The response-envelope field names are the adapter contract in this example. Map the authorized service's readiness/date/currency/unit/sign/row-count/total fields into this envelope before calling the helper. If the source has an independent signed checksum or another stronger control, validate that as well. Do not manufacture controls from the same already-truncated five-column result and call that reconciliation.

Define **AUTHORIZED_COLOSSUS_OPERATIONAL_ERRORS** as the exact approved client transport/availability exception tuple; do not catch programming/schema errors as operational. Client/module construction must be configuration-only and perform no authentication, schema fetch, or network call at import time. The scheduled tool imports the configured loader module before refresh; first Colossus I/O belongs inside **get_colossus_pl()** after archive eligibility is known.

Do not catch source/validation failure and publish zeros. The whole daily archive must fail before publication.

### Where the Colossus data goes

Do not manually put a file inside **PL_HISTORICAL_PATH/<date>**. That directory is the archive writer's destination and becomes immutable when **_SUCCESS** is published.

The intended direction is:

~~~text
authorized Colossus API or governed dated source file
  -> get_colossus_pl(exact Market Date)
  -> canonical five-column DataFrame
  -> validate_colossus_frame()
  -> archive_official_snapshot()
  -> <PL_HISTORICAL_PATH>/<YYYY-MM-DD>/colossus.parquet
     beside risk.parquet, market.parquet, optional stock.parquet, and _SUCCESS
~~~

The writer—not the loader—chooses the archive destination, Parquet compression, manifest row count, and SHA-256 hash.

If the authorized source is already a dated Parquet drop rather than an API, keep the inbound source in a different governed directory. For example:

~~~text
<COLOSSUS_SOURCE_ROOT>/
  2026-08-31.parquet
  2026-08-31.ready.json
  2026-09-01.parquet
  2026-09-01.ready.json
~~~

The upstream publisher must write/close the Parquet payload to a temporary name, atomically rename it to the final dated name, then atomically publish the ready JSON last. The marker must contain the exact **market_date**, **status=FINAL**, **pnl_basis=DTD**, **row_count**, independently reconciled **pl_total**, approved **currency**, **unit**, **sign_convention**, and the payload **sha256**. The scheduler must ignore a payload that has no final marker.

Add a site-owned environment variable for that inbound directory:

~~~powershell
$env:COLOSSUS_SOURCE_ROOT = 'D:\governed-input\colossus'
~~~

Put **_colossus_market_date()**, **_validated_colossus_payload()**, and the approved constants from the API example in the same connector module, then use this file-backed loader:

~~~python
import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path

import pandas as pd

from cube.history import COLOSSUS_COLUMNS, validate_colossus_frame


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def get_colossus_pl(
    market_date: pd.Timestamp,
) -> pd.DataFrame:
    selected = _colossus_market_date(market_date)
    root_text = os.environ.get("COLOSSUS_SOURCE_ROOT", "").strip()
    if not root_text:
        raise RuntimeError("COLOSSUS_SOURCE_ROOT is not configured")
    source_root = Path(root_text).expanduser()
    if not source_root.is_absolute():
        raise ValueError("COLOSSUS_SOURCE_ROOT must be an absolute path")
    source_root = source_root.resolve(strict=True)

    source = source_root / f"{selected.date().isoformat()}.parquet"
    ready = source_root / f"{selected.date().isoformat()}.ready.json"

    try:
        metadata = json.loads(ready.read_text(encoding="utf-8"))
        if not isinstance(metadata, Mapping):
            raise ValueError("ready marker must be an object")
        expected_hash = metadata.get("sha256")
        if not isinstance(expected_hash, str) or _sha256(source) != expected_hash:
            raise ValueError("payload hash does not match ready marker")
        raw = pd.read_parquet(source)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise RuntimeError(
            "Final Colossus source is unavailable for the requested Market Date"
        ) from None

    return _validated_colossus_payload(
        raw,
        metadata=metadata,
        selected=selected,
    )
~~~

The imports plus the two helpers make this example self-contained in a separate approved connector module. If you keep the replacement in **cube/services/s05_sources.py**, several imports already exist; reuse them rather than duplicating imports. Replace the source-to-canonical rename mapping inside **_validated_colossus_payload()** and remove its comments before use.

The dated filename is only an example of a governed source convention. If the real system uses date folders, CSV, a database, or an API, change only the source read. Preserve the callable signature and canonical returned DataFrame.

For old actual P&L:

- a loose historical Colossus source file belongs in the inbound source root and must be processed together with same-date Risk and Market through a reviewed full-leaf backfill;
- an already complete schema-v4 date folder belongs under **PL_HISTORICAL_PATH** as a whole immutable leaf; and
- a lone **colossus.parquet** must never be copied into or added to a completed archive folder.

## 4.11 Step 6 — configure the scheduled archive

The scheduler resolves:

~~~text
COLOSSUS_LOADER=module:function
~~~

The default is:

~~~text
cube.services.s05_sources:get_colossus_pl
~~~

Blank or unset **COLOSSUS_LOADER** selects that default; it does not disable Colossus. A non-default value must be an importable **module:function** pointing to a top-level callable. A lambda, nested function, notebook-local function, or misspelled attribute will fail resolution.

Set it explicitly in production if the real function lives elsewhere:

~~~powershell
$env:COLOSSUS_LOADER = 'cube.services.s05_sources:get_colossus_pl'
$env:COLOSSUS_SOURCE_ROOT = 'D:\governed-input\colossus'
$env:PL_HISTORICAL_PATH = 'D:\rebirth-private\histo'
~~~

If Part 3 is implemented:

~~~powershell
$env:STOCK_LOADER = 'cube.adapters.s08_stock:get_stock'
~~~

Run the entry point only after all enabled sources are immutable for the date:

- Market source is **OFFICIAL**;
- Colossus source is **FINAL** and its date/control totals reconcile; and
- Stock source is final when Part 3 Stock archival is enabled.

~~~powershell
& '.\.venv\Scripts\python.exe' -m tools.s02_archive
~~~

The scheduler:

1. builds the production refresh manager;
2. refreshes with force Risk and force P&L;
3. requires the naturally resolved Market Date;
4. requires Market Status exactly OFFICIAL;
5. requires no committed refresh errors;
6. loads Colossus and verifies its final/date/semantic controls before five-column projection;
7. optionally loads final Stock;
8. validates all canonical frames;
9. writes a pending directory;
10. writes **_SUCCESS** last;
11. atomically renames the leaf.

If Market is still Live, the writer returns **skipped**. If Market is OFFICIAL but Colossus/Stock is not final or a source/control check fails, the command fails without publishing a leaf. Schedule a later retry; do not fake OFFICIAL/FINAL or return partial/zero data.

If a valid completed date already exists, it returns **already_archived** without calling the source loaders or overwriting it. A corrupt, partial, or invalid final date directory raises; it is not reported as already archived.

## 4.12 Step 7 — verify the daily leaf

Expected schema-v4 files:

~~~text
risk.parquet
colossus.parquet
market.parquet
stock.parquet       optional
_SUCCESS
~~~

Under the default display-zero policy, **risk.parquet** contains the committed mapped **snapshot.dashboard_frame** and therefore the archived Predict PL. If Step 4.8A hardening is applied, it instead contains the newly generated same-revision mapped projection from **snapshot.combined_pl**, with authoritative PL restored after mapping. In either mode, validate the exact policy you chose; do not assume the file is always a byte-for-byte projection of **dashboard_frame**.

**colossus.parquet** contains actual P&L at its separate four-key grain.

The canonical file and **_SUCCESS** do not retain Colossus source date/finality/DTD/currency/unit/sign controls. Retain the approved source receipt or ready marker in the governed upstream audit system and log only a metadata-level reconciliation result/incident ID—never the financial control total or payload.

**market.parquet** is required by schema v4 even though P&L history SQL projects Risk and Colossus.

**_SUCCESS** records:

- schema version 4;
- exact official date/status;
- revision;
- per-source Risk Dates;
- row counts;
- exact columns;
- hashes;
- optional Stock metadata.

Strictly validate:

~~~python
from cube.history import list_completed_v4_archive_days

days = list_completed_v4_archive_days(HISTORY_ROOT)
assert days
print(days[-1])
~~~

Do not hand-author **_SUCCESS**.

## 4.13 How SQL P&L history is built

**SQLPLHistoryRepository** creates one virtual history with:

~~~python
(
    "Market Date",
    "P&L Type",
    "Activity",
    "SignoffGroup",
    "Category",
    "Sub Category",
    "Risk Type",
    "Risk Greek",
    "Underlying",
    "Product",
    "Portfolio",
    "Mapping Status",
    "PL",
)
~~~

### Predict projection

Predict comes from archived **risk.parquet** and is aggregated at:

~~~text
date
+ SignoffGroup
+ Risk Type
+ Risk Greek
+ raw Underlying
+ Product
+ Portfolio
~~~

SQL excludes a group only when archived **risk.parquet** still contains missing PL. With the current writer’s display-normalized **dashboard_frame**, unavailable PL has already become 0.0, so the SQL guard cannot detect it. The optional archive-frame hardening in Step 4.8A is required before this exclusion becomes effective for real unavailable Predict rows.

### Colossus projection

Colossus keeps each official four-key row once. It attaches Activity, SignoffGroup, Category, Sub Category, and Product from that same date’s Risk-derived Portfolio authority.

If a Portfolio:

- is absent from Risk; or
- maps to more than one distinct SignoffGroup/Product authority,

the Colossus row is labelled **Unmapped**. It is not duplicated or guessed.

## 4.14 Step 8 — leave app P&L history wiring unchanged

**app.py** already constructs:

~~~python
pl_send_config = PLSendConfig(
    mapping_source=mapping_path,
    adjustment_repository=LocalCsvAdjustmentRepository(
        adjustment_path
    ),
    send_sog_pl=send_sog_pl,
    send_portfolio_pl=send_portfolio_pl,
    history_source=SQLPLHistoryRepository(history_path),
)
~~~

and passes:

~~~python
pl_send_config=pl_send_config
pl_history_root=history_path
~~~

No P&L page callback change is required.

The existing P&L page registers:

- archive-backed overview and filters;
- inline Colossus/Predict history;
- lazy SOG and Portfolio editors;
- adjustment save/send;
- Predict-versus-Colossus validation.

The SQL repository:

- performs no I/O at construction;
- accepts only completed schema-v4 Parquet leaves;
- uses an in-memory DuckDB connection;
- caps DuckDB memory at 384 MB and threads at 2;
- uses a temporary spill directory;
- reopens on archive generation change;
- clears connection/caches/spill state on Clear Cache.

Missing dates remain missing. **series()** does not fill gaps with zero.

### Real-history row limit

**PL_HISTORY_MAX_SERIES_ROWS** is currently 524. One row is returned per observed date and requested P&L type. When both Colossus and Predict exist every day, 262 dates fit and the 263rd fully observed date exceeds the limit. An “All” multi-year request then raises instead of silently truncating.

Before loading long real history, choose one:

- keep the existing limit and default users to a bounded period such as 1Y;
- add reviewed date-windowing or deterministic downsampling;
- raise the limit only after measuring browser payload, query time, and memory and adding boundary tests.

Never silently discard rows without telling the user which period was returned.

### Bound the Python result caches

DuckDB’s 384 MB limit does not bound Python pandas objects. **SQLPLHistoryRepository._stats_cache** and **_risk_summary_cache** are ordinary dictionaries and can grow for every unique high-cardinality filter combination until Clear Cache or archive-generation rollover.

For production, either disable these result caches or cap them. One contained FIFO/LRU-style insertion helper is:

~~~python
from collections import OrderedDict


PL_HISTORY_RESULT_CACHE_MAX_ENTRIES = 64


def _remember_bounded(cache, key, value) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > PL_HISTORY_RESULT_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)
~~~

Change both cache declarations and type annotations so **_stats_cache** and **_risk_summary_cache** are initialized as **OrderedDict** instances. Then replace every direct cache assignment with **_remember_bounded(...)** in all three write sites: **_remember_hierarchy_stats()**, **_cached_stats()**, and **risk_summary()**. Missing **_cached_stats()** leaves an unbounded path even if the other two methods are patched. Move a key to the end on a cache hit if true LRU behavior is wanted. Add a test that issues more than the limit in unique filter keys and proves old entries are evicted and totals remain correct. Log cache entry counts and process RSS; do not log filter values or financial results.

## 4.15 Step 9 — run a safe end-to-end archive test

Do not first test against the production history root.

Use a temporary/sandbox root and injected sanitized sources:

The following call assumes Part 3’s optional **stock_loader** scheduler patch has already been applied:

~~~python
from tools.s02_archive import run_scheduled_archive

result = run_scheduled_archive(
    environ={
        "PL_HISTORICAL_PATH": str(SANDBOX_ROOT),
    },
    manager_factory=SANITIZED_MANAGER_FACTORY,
    colossus_loader=SANITIZED_COLOSSUS_LOADER,
    stock_loader=SANITIZED_STOCK_LOADER,
)
assert result.status == "archived"
~~~

If Part 3 has not been applied, omit the unsupported Stock argument:

~~~python
result = run_scheduled_archive(
    environ={
        "PL_HISTORICAL_PATH": str(SANDBOX_ROOT),
    },
    manager_factory=SANITIZED_MANAGER_FACTORY,
    colossus_loader=SANITIZED_COLOSSUS_LOADER,
)
assert result.status == "archived"
~~~

Then:

~~~python
from cube.history import SQLPLHistoryRepository

repository = SQLPLHistoryRepository(SANDBOX_ROOT)

summary = repository.risk_summary()
series = repository.series(
    path=(),
    history_types=("Colossus", "Predict"),
    preset="all",
)

print(summary.as_of_date)
print(summary.summary.head())
print(series.series.head())
~~~

Finally:

1. open the P&L page;
2. confirm overview as-of date;
3. click a Risk Type/Greek/Underlying value;
4. choose Both;
5. confirm observed Colossus and Predict points;
6. confirm a missing date is a gap;
7. open Validate P&L for that date;
8. verify mapped and Unmapped actuals.

## 4.16 Tests to add for P&L

### Current Predict tests

Use **tests/s04_market.py** and **tests/s07_integration.py** for:

- matched Risk/Open/Current hand calculation;
- missing market remains unavailable;
- percentage and absolute move behavior;
- Taylor-Gamma behavior;
- exact many-to-one quote grain;
- mapped and unmapped Portfolio handling;
- committed revision/date.

### Mapping, adjustments, and sender tests

Use **tests/s05_pl.py** and **tests/s09_plui.py** for:

- missing mapping pair;
- duplicate pair;
- duplicate ConcertoField;
- adjustment replace semantics;
- stale revision rejection;
- exact seven-column delivery payload;
- sender does not mutate input;
- acknowledged success;
- timeout/rejection;
- a transport/response exception containing fake sensitive text is reduced to a fixed safe raised message and approved metadata-only logs;
- partial Send All;
- idempotency behavior.

### Colossus and archive tests

Update **tests/s08_feeds.py** for the real source boundary. The existing **test_legacy_v4_colossus_loader_reads_unified_parquet_archive_grain** expects 5,000 temporary rows containing **TEMP_REPLACE_ME** and must no longer call the replaced public production loader. Retarget that fixture assertion to a fixture-only helper, then add mocked real-loader tests for:

- exact requested Market Date reaches the source;
- source date mismatch fails;
- non-FINAL/absent ready marker fails;
- DTD rather than cumulative semantic metadata;
- approved currency, unit, and sign convention;
- reconciled row count, PL control total, and file hash;
- safe transport failure;
- exact canonical five-column result; and
- importing the module performs no client/network call.

Use **tests/s29_archive.py** for:

- exact ordered Colossus schema;
- blank text rejection;
- nonfinite PL rejection;
- duplicate key rejection;
- empty actuals rejection;
- OFFICIAL eligibility;
- naturally resolved date;
- snapshot errors;
- exact eligible date passed to Colossus;
- no Colossus call for Live, non-natural, errored, or already-valid completed dates;
- no leaf when Colossus finality/date/control validation fails;
- atomic pending write;
- existing-date idempotency;
- partial/corrupt leaf behavior.

### SQL/page history tests

Use:

- **tests/s24_plhistory.py**;
- **tests/s28_validation.py**;
- **tests/s29_archive.py**;
- **tests/s09_plui.py**.

Cover:

- summary and series totals;
- latest archive Current behavior;
- current display-zero archive behavior, or missing Predict PL remains absent after Step 4.8A hardening;
- ambiguous Product becomes Unmapped;
- new archive generation becomes visible;
- Clear Cache closes/reopens state;
- spill cleanup;
- the 524-row series boundary and selected long-history behavior;
- bounded Python result-cache eviction across many unique filter keys;
- observed missing dates remain missing.

### Startup/publish tests

Use:

- **tests/s12_startup.py** for paths, env, and lazy wiring;
- **tests/s13_publish.py** for deployable imports and required artifacts.

## 4.17 Validate Part 4

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests\s05_pl.py tests\s08_feeds.py tests\s09_plui.py tests\s24_plhistory.py tests\s28_validation.py tests\s29_archive.py -q -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m pytest tests\s04_market.py tests\s07_integration.py tests\s12_startup.py tests\s13_publish.py -q -p no:cacheprovider
~~~

## 4.18 Common Part 4 failures

| Symptom | Most likely cause |
|---|---|
| Predict is missing | Risk/Open/Current adapter or ProductSpec calculation is incomplete |
| Upper overview lags send editors | Overview is latest archive; editors are live manager snapshot |
| Send build fails for one pair | data/s08_concerto.csv lacks that exact Risk Type/Greek |
| Sender endpoint has wrong date | Current delivery payload has no Market Date; contract was not deliberately extended |
| Adjustment appears added twice | Implementation added instead of replacing the same key |
| A valid selected history shows Predict but no matching Colossus points | Actual identity/filter/date does not match, or the governed actual source was semantically incomplete |
| History has Colossus Unmapped | Portfolio absent/ambiguous in that date’s archived Risk authority |
| Product attribution looks wrong | Five-column Colossus contract cannot disambiguate a multi-product Portfolio |
| MTD/YTD actual grows far too quickly | Loader supplied cumulative rather than one-day/DTD Colossus PL |
| Colossus sign/unit/currency is wrong | Loader projected rows before validating/converting approved semantic controls |
| Today’s leaf is absent | Market is not OFFICIAL, Colossus/Stock is not final, a loader/control failed, root is wrong, or refresh carried errors |
| SQL rejects history | Leaves are legacy/non-v4, corrupt, differently shaped, or missing _SUCCESS |
| Unavailable archived Predict displays as zero | Current writer archives display-normalized dashboard_frame; apply Step 4.8A if historical missingness must be retained |
| All history fails after about 262 dual-type dates | The 524-row series bound was exceeded |
| Worker RSS grows with filter combinations | Python stats/risk-summary result caches were left unbounded |

## 4.19 Part 4 done checklist

- [ ] Predict comes from real Risk/Open/Current adapters, not a page P&L fetch.
- [ ] Product formula/multiplier hand checks pass.
- [ ] Portfolio authority is unique and complete.
- [ ] Concerto mapping covers every send pair uniquely.
- [ ] Adjustment replacement semantics preserved.
- [ ] Senders either remain fail-closed or use exact seven-column acknowledged delivery.
- [ ] Sender date/revision requirement explicitly handled, not inferred.
- [ ] Real Colossus loader verifies requested date, FINAL state, DTD semantics, currency/unit/sign, row count, and control total before returning exact five-column unique finite data.
- [ ] File-backed Colossus uses an absolute governed source root, atomic payload publication, a marker published last, and a verified payload hash.
- [ ] Importing/building the app or scheduled job performs no Colossus network/source read.
- [ ] Scheduler writes complete OFFICIAL schema-v4 leaves to durable storage.
- [ ] App and scheduler share PL_HISTORICAL_PATH.
- [ ] Archived missing-P&L policy is explicitly accepted or Step 4.8A is implemented and tested.
- [ ] Long-history row limit and Python result-cache bound are tested.
- [ ] SQL summary/series and Validate P&L work on a sandbox archive.
- [ ] Current, send, archive, history, startup, and publish tests pass.

---

# Final integration order

Follow this order to minimize ambiguity.

## Phase 1 — pure contracts

1. Add/validate the new tenor matrix and selector.
2. Replace the Market-state, Open, and Current boundaries, including the FX Delta bulk decision, and add their unit tests.
3. Verify the full committed live MarketBook and Quick Market.
4. Add the real Stock source and its unit tests.
5. Add the real Colossus loader and its unit tests.
6. Keep outbound senders fail-closed until their payload contract is approved.

## Phase 2 — archive support

1. Point the app and scheduled job at the same sandbox **PL_HISTORICAL_PATH**.
2. Configure the mandatory real Colossus loader.
3. Prove Colossus source date, FINAL readiness, DTD/currency/unit/sign metadata, row count, and control total before the first immutable write.
4. Add optional **StockLoader** and pass it through the writer/job if Stock history is required.
5. Test OFFICIAL/finality eligibility, full-leaf validation, and atomicity.
6. Produce one complete Risk/Colossus/Market leaf, with Stock only when configured.
7. Run strict completed-day/hash/value validation and query one exact Market identity through **ArchiveHistoryRepository**.

## Phase 3 — page integration

1. Start the app.
2. Force one full Risk/P&L refresh.
3. Verify Full and Reduced Risk.
4. Verify Quick Market Open/Current/Move and status.
5. Open the same identity in **/data** and verify archived Current appears as Official.
6. Verify current/prior Stock.
7. Query Stock history.
8. Verify archive-backed P&L overview and chart.
9. Verify Predict-versus-Colossus validation.
10. Verify adjustment editor without sending.

## Phase 4 — sending

1. Confirm the endpoint accepts the exact seven-column payload, or formally extend the contract.
2. Test against a non-production destination.
3. Test timeout, rejection, and partial Send All.
4. Enable one destination at a time.
5. Never use a successful UI message as the only delivery audit; retain the destination’s approved acknowledgement/idempotency record.

# Full repository validation

After all code changes:

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest -q -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m ruff check .
& '.\.venv\Scripts\python.exe' -m ruff format --check .
git diff --check
git status --short
~~~

If the repository does not expose Ruff as a Python module, use the project’s checked-in lint command instead. Do not install or upgrade dependencies only to change the guide.

# Operational smoke test

Use one known source/date/identity and record:

1. current refresh revision;
2. Market Date;
3. exact Market Status returned by the one resolver call;
4. one Open request date and one Current request date;
5. one live Open, Current, and Move value;
6. per-source Risk Date;
7. matrix committed key;
8. Full and Reduced hand totals;
9. completed archive path;
10. exact Colossus source date and FINAL status;
11. approved DTD/currency/unit/sign identifiers and a control-total-reconciled pass/fail flag, without logging the financial total;
12. Market and Colossus row counts;
13. the same archived Current/Official value on **/data**;
14. Stock current/prior source dates and archived row count, when enabled;
15. P&L overview as-of date;
16. one Predict and one Colossus series value; and
17. sender acknowledgement in a non-production destination, when sending is enabled.

Do not use production financial values in Git, screenshots, test fixtures, or logs.

# Rollback

## Tenor matrix rollback

1. Deselect Reduced for immediate user recovery.
2. Remove the exact selector row.
3. Stop returning/remove the named matrix.
4. Revert exact-key test expectations.
5. restart the app;
6. force the owning source’s Risk refresh.

No history migration is required.

## Market rollback

1. Pause the scheduled archive.
2. Restore the previous **get_market_state()**, **get_market_open()**, and **get_market_status()** bodies as one coherent set.
3. Restore the matching FX Delta bulk-hook choice and any bulk function bodies changed with it.
4. restore the previous **PL_HISTORICAL_PATH** only if the root itself changed;
5. strictly validate that target root;
6. restart the app/job and force one full Risk/P&L refresh;
7. keep valid completed leaves untouched; and
8. re-enable scheduling only after the restored source passes its smoke test.

Do not delete or patch completed archive history as a connector rollback.

## Stock rollback

1. Pause the scheduled archive.
2. Restore the previous current Stock callable.
3. unset **STOCK_LOADER** or omit it from the scheduler.
4. strictly validate the unchanged history root;
5. restart the app/job and smoke the restored current Stock path;
6. keep valid completed leaves untouched;
7. if necessary, pass no Stock history source to disable history controls; and
8. re-enable scheduling only after every enabled source is final and valid.

Schema-v4 permits valid dates with and without Stock. Do not delete archive history as rollback.

## P&L rollback

1. Pause the scheduled archive.
2. Restore sender functions to fail-closed stubs.
3. restore the previous **COLOSSUS_LOADER** plus its client/**COLOSSUS_SOURCE_ROOT** configuration;
4. restore the previous **PL_HISTORICAL_PATH** only if it changed;
5. strictly validate the target history root;
6. restart the app/job and smoke the restored loader without sending;
7. preserve user adjustment files; and
8. re-enable scheduling only after Market OFFICIAL and every enabled source is final.

If a semantically wrong but hash-valid Colossus day was already published, ordinary rollback cannot overwrite that immutable date. Build a corrected complete archive in a new root, validate every leaf and source control, switch both app and job to that root, and retain the old root for audit.

Never recursively delete adjustment or history roots during rollback.

# Final acceptance criteria

The change is complete only when all of these are true:

- a new non-Credit matrix is selected by exact raw identity, is same-date with Risk, and is committed/reused/replaced by revision;
- Credit still uses only its separate shared map;
- live Market uses one authoritative status, supplied Open/Current dates, exact raw identity, and stable tenor order;
- the committed MarketBook includes Market-only tenors and Quick Market reads that same revision;
- **/data** queries complete schema-v4 leaves and shows archived Current as Official with missing cells preserved;
- live Stock returns exact current/prior frames and the current page needs no new callback;
- scheduled official archives contain validated optional Stock and required Predict/Colossus/Market data;
- Colossus source date, FINAL readiness, DTD currency/unit/sign semantics, row count, and control total are verified before five-column projection;
- archive-backed Stock and all P&L history query only completed schema-v4 leaves; any approved external Stock-history alternative implements the bounded **StockHistoryQueryProtocol** without patching those leaves;
- missing Stock dates and missing P&L dates are not manufactured as zero, and the per-row Predict archive zero-fill policy is explicitly accepted or hardened;
- Portfolio and Product ambiguity is explicit rather than deduplicated;
- P&L overview archive timing is understood;
- outbound sender payload/context is explicit;
- focused and full tests pass;
- real secrets and financial data remain outside Git.
