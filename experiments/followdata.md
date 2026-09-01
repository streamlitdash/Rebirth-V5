# Follow the data — add a tenor matrix, Stock/history, and P&L/history

This is the step-by-step implementation guide for the current Rebirth V5 code on branch **v4**. It is deliberately detailed enough to follow as a change checklist.

This Markdown file is documentation only. Adding this file does not itself connect a source, create a matrix, write history, or send P&L.

The three requested parts are:

1. add a new reduced-tenor matrix;
2. add live Stock and Stock history to the Stock page; and
3. add Predict P&L, Colossus actual P&L history, and, if required, the two outbound P&L senders to the P&L page.

The current code already owns the pages, callbacks, tables, charts, revision checks, filtering, and most validation. The safest implementation is to replace the narrow data boundaries and leave page code alone.

## The most important distinction

These are separate data paths:

~~~text
Reduced tenor
  ProductSpec
    -> dated Risk connector returns Risk + named matrices
    -> refresh validates and commits both in one revision
    -> Risk page applies a matrix only when Reduced is selected

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

Code blocks containing names such as **YOUR_SYNC_STOCK_CLIENT**, **AUTHORIZED_COLOSSUS_CLIENT**, **SANITIZED_MANAGER_FACTORY**, or **HISTORY_ROOT** are templates. Replace every all-capital placeholder with the approved site object or path before running the block. Do not add a fake implementation merely to make an import succeed.

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

Then return to Step 1.3 and add the matrix.

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

# Part 2 — add Stock and Stock history

## 2.1 Treat current Stock and history as two deliveries

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

## 2.2 Current Stock contract

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

## 2.3 Step 1 — replace the temporary Stock source

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

## 2.4 Step 2 — leave current Stock page logic unchanged

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

## 2.5 Step 3 — verify Portfolio authority

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

## 2.6 Current Stock failure behavior

One failure in either the current or prior date read fails that current Stock load. The callback:

- logs **Could not load current Stock**;
- retains the previous loaded UI token;
- displays the failure in **stock-load-status**.

Do not catch source errors and return an empty DataFrame. An empty frame would disguise an unavailable source as a genuine zero-position day.

## 2.7 History contract

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

## 2.8 The current scheduled-archive gap

The current archive writer can store **stock_frame** when a test/fixture snapshot happens to expose one. The normal **RefreshSnapshot** does not have **stock_frame** or **stock_date**.

The current scheduled path:

~~~text
tools/s02_archive.py
  -> RiskRefreshManager refresh
  -> archive_from_manager(manager, colossus_loader, root)
~~~

therefore does not load real Stock.

The easiest contained fix is to add an optional **stock_loader** to the archive boundary. Do not put Stock into every Risk refresh and do not mutate the frozen snapshot.

## 2.9 Step 4 — add the StockLoader type

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

## 2.10 Step 5 — add stock_loader to archive_official_snapshot

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

raw_stock = (
    stock_loader(pd.Timestamp(market_date))
    if stock_loader is not None
    else getattr(snapshot, "stock_frame", None)
)
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

## 2.11 Step 6 — pass stock_loader through archive_from_manager

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

## 2.12 Step 7 — resolve Stock in the scheduled job

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

## 2.13 Step 8 — leave SQLStockHistoryRepository and the page unchanged

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

## 2.14 Never patch a completed leaf by hand

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

## 2.15 Alternative: query an existing historical Stock database

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

## 2.16 Tests to add for Stock

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
8. **archive_from_manager()** passes the loader after exactly one coherent refresh;
9. scheduled wrapper resolves and passes **STOCK_LOADER**;
10. an explicit loader uses Market Date even when a legacy snapshot has stale **stock_date**;
11. legacy snapshot Stock still validates its supplied **stock_date**;
12. a completed date without Stock remains an intentional no-op;
13. any implemented Stock-readiness gate prevents publication before Stock is final.

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

## 2.17 Validate Part 2

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

## 2.18 Common Part 2 failures

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

## 2.19 Part 2 done checklist

- [ ] Live synchronous source returns exact seven-column Stock schema.
- [ ] Current and prior dates are supported.
- [ ] Real governed Stock key is documented and tested; the temporary five-field identity is retained only if it is truly unique.
- [ ] Portfolio metadata remains outside Stock source.
- [ ] Current-date versus checker-date Portfolio authority is explicitly chosen and tested.
- [ ] App still uses the existing Stock page/callback.
- [ ] StockLoader type and optional writer parameter added.
- [ ] Scheduler resolves and passes the same real Stock callable.
- [ ] Stock EOD is final before the first immutable official write.
- [ ] Stock is written only as part of a complete schema-v4 leaf.
- [ ] A scheduled/publish gate calls **list_completed_v4_archive_days()** so digest integrity is checked outside the interactive page.
- [ ] App and scheduler use the same durable PL_HISTORICAL_PATH.
- [ ] Current, history, archive, and startup tests pass.
- [ ] One sandbox archive is queryable through SQLStockHistoryRepository.

---

# Part 3 — add P&L and P&L history

## 3.1 First decide which “P&L” is being added

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

## 3.2 Current Predict chain

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
- leaves unavailable market P&L as NaN in **combined_pl** rather than zero; the separate archive/display zero-fill caveat is covered in Step 3.8A.

**_release_pl_views()**:

- concatenates product P&L and governed overlays;
- maps Portfolio metadata;
- attaches reported identities/promotions;
- commits **combined_pl** for sending;
- creates mapped **dashboard_frame** for display/history;
- creates **unmapped_frame**.

Do not fetch a competing current P&L frame inside **cube/pages/pnl**. If Predict is missing or wrong, fix the owning Risk/Open/Current adapter, ProductSpec formula/multiplier, or Portfolio authority.

## 3.3 Step 1 — connect current Predict through product sources

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

## 3.4 Step 2 — keep the Concerto mapping complete

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

## 3.5 Step 3 — verify Portfolio governance

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

## 3.6 Understand adjustment behavior

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

## 3.7 Step 4 — replace outbound sender stubs only if sending is required

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

## 3.8 Current P&L overview is archive-backed

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

### 3.8A — decide the archived missing-P&L policy

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

## 3.9 Colossus actual history contract

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
- Underlying uses the same raw identity as archived Risk;
- Risk Type/Greek use canonical ProductSpec labels;
- Product is deliberately absent.

Do not add Product by duplicating or arbitrarily deduplicating Colossus rows. If the business requires Product-level actuals for one multi-product Portfolio, that needs a deliberate archive schema revision across contract, writer, manifest, SQL projection, migrations, and tests.

## 3.10 Step 5 — replace get_colossus_pl

In **cube/services/s05_sources.py**, replace the temporary body of **get_colossus_pl()**.

Recommended shape:

~~~python
def get_colossus_pl(
    market_date: pd.Timestamp,
) -> pd.DataFrame:
    selected = _normalized_date(
        market_date,
        parameter="market_date",
    )

    raw = AUTHORIZED_COLOSSUS_CLIENT.get_pl(
        as_of=selected.date().isoformat(),
        connect_timeout=5,
        read_timeout=30,
    )
    if not isinstance(raw, pd.DataFrame):
        raw = pd.DataFrame.from_records(raw)

    frame = raw.rename(
        columns={
            # "real_portfolio": "Portfolio",
            # "real_underlying": "Underlying",
            # "real_risk_type": "Risk Type",
            # "real_risk_greek": "Risk Greek",
            # "real_pl": "PL",
        }
    )

    missing = [
        column
        for column in COLOSSUS_COLUMNS
        if column not in frame.columns
    ]
    if missing:
        raise ValueError(
            f"Colossus P&L is missing columns: {missing}"
        )

    return validate_colossus_frame(
        frame.loc[:, list(COLOSSUS_COLUMNS)].copy(deep=True)
    )
~~~

Use the current imported **COLOSSUS_COLUMNS** and **validate_colossus_frame**. If the validator is not imported directly in this module after your edit, import it from **cube.history**.

Do not catch source/validation failure and publish zeros. The whole daily archive must fail before publication.

## 3.11 Step 6 — configure the scheduled archive

The scheduler resolves:

~~~text
COLOSSUS_LOADER=module:function
~~~

The default is:

~~~text
cube.services.s05_sources:get_colossus_pl
~~~

Set it explicitly in production if the real function lives elsewhere:

~~~powershell
$env:COLOSSUS_LOADER = 'cube.services.s05_sources:get_colossus_pl'
$env:PL_HISTORICAL_PATH = 'D:\rebirth-private\histo'
~~~

If Part 2 is implemented:

~~~powershell
$env:STOCK_LOADER = 'cube.adapters.s08_stock:get_stock'
~~~

Run the entry point only after the Market source is OFFICIAL:

~~~powershell
& '.\.venv\Scripts\python.exe' -m tools.s02_archive
~~~

The scheduler:

1. builds the production refresh manager;
2. refreshes with force Risk and force P&L;
3. requires the naturally resolved Market Date;
4. requires Market Status exactly OFFICIAL;
5. requires no committed refresh errors;
6. loads Colossus;
7. optionally loads Stock;
8. validates all frames;
9. writes a pending directory;
10. writes **_SUCCESS** last;
11. atomically renames the leaf.

If run early, it returns **skipped**. Schedule a later retry; do not fake OFFICIAL.

If a completed date already exists, it returns **already_archived** and does not overwrite it.

## 3.12 Step 7 — verify the daily leaf

Expected schema-v4 files:

~~~text
risk.parquet
colossus.parquet
market.parquet
stock.parquet       optional
_SUCCESS
~~~

Under the default display-zero policy, **risk.parquet** contains the committed mapped **snapshot.dashboard_frame** and therefore the archived Predict PL. If Step 3.8A hardening is applied, it instead contains the newly generated same-revision mapped projection from **snapshot.combined_pl**, with authoritative PL restored after mapping. In either mode, validate the exact policy you chose; do not assume the file is always a byte-for-byte projection of **dashboard_frame**.

**colossus.parquet** contains actual P&L at its separate four-key grain.

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

## 3.13 How SQL P&L history is built

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

SQL excludes a group only when archived **risk.parquet** still contains missing PL. With the current writer’s display-normalized **dashboard_frame**, unavailable PL has already become 0.0, so the SQL guard cannot detect it. The optional archive-frame hardening in Step 3.8A is required before this exclusion becomes effective for real unavailable Predict rows.

### Colossus projection

Colossus keeps each official four-key row once. It attaches Activity, SignoffGroup, Category, Sub Category, and Product from that same date’s Risk-derived Portfolio authority.

If a Portfolio:

- is absent from Risk; or
- maps to more than one distinct SignoffGroup/Product authority,

the Colossus row is labelled **Unmapped**. It is not duplicated or guessed.

## 3.14 Step 8 — leave app P&L history wiring unchanged

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

## 3.15 Step 9 — run a safe end-to-end archive test

Do not first test against the production history root.

Use a temporary/sandbox root and injected sanitized sources:

The following call assumes Part 2’s optional **stock_loader** scheduler patch has already been applied:

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

If Part 2 has not been applied, omit the unsupported Stock argument:

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

## 3.16 Tests to add for P&L

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

Use **tests/s29_archive.py** for:

- exact ordered Colossus schema;
- blank text rejection;
- nonfinite PL rejection;
- duplicate key rejection;
- empty actuals rejection;
- OFFICIAL eligibility;
- naturally resolved date;
- snapshot errors;
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
- current display-zero archive behavior, or missing Predict PL remains absent after Step 3.8A hardening;
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

## 3.17 Validate Part 3

~~~powershell
& '.\.venv\Scripts\python.exe' -m pytest tests\s05_pl.py tests\s09_plui.py tests\s24_plhistory.py tests\s28_validation.py tests\s29_archive.py -q -p no:cacheprovider
& '.\.venv\Scripts\python.exe' -m pytest tests\s04_market.py tests\s07_integration.py tests\s12_startup.py tests\s13_publish.py -q -p no:cacheprovider
~~~

## 3.18 Common Part 3 failures

| Symptom | Most likely cause |
|---|---|
| Predict is missing | Risk/Open/Current adapter or ProductSpec calculation is incomplete |
| Upper overview lags send editors | Overview is latest archive; editors are live manager snapshot |
| Send build fails for one pair | data/s08_concerto.csv lacks that exact Risk Type/Greek |
| Sender endpoint has wrong date | Current delivery payload has no Market Date; contract was not deliberately extended |
| Adjustment appears added twice | Implementation added instead of replacing the same key |
| History has Predict but no Colossus | Colossus loader/archive failed or leaf is incomplete |
| History has Colossus Unmapped | Portfolio absent/ambiguous in that date’s archived Risk authority |
| Product attribution looks wrong | Five-column Colossus contract cannot disambiguate a multi-product Portfolio |
| Today’s leaf is absent | Scheduler ran before OFFICIAL, used wrong root, or refresh carried errors |
| SQL rejects history | Leaves are legacy/non-v4, corrupt, differently shaped, or missing _SUCCESS |
| Unavailable archived Predict displays as zero | Current writer archives display-normalized dashboard_frame; apply Step 3.8A if historical missingness must be retained |
| All history fails after about 262 dual-type dates | The 524-row series bound was exceeded |
| Worker RSS grows with filter combinations | Python stats/risk-summary result caches were left unbounded |

## 3.19 Part 3 done checklist

- [ ] Predict comes from real Risk/Open/Current adapters, not a page P&L fetch.
- [ ] Product formula/multiplier hand checks pass.
- [ ] Portfolio authority is unique and complete.
- [ ] Concerto mapping covers every send pair uniquely.
- [ ] Adjustment replacement semantics preserved.
- [ ] Senders either remain fail-closed or use exact seven-column acknowledged delivery.
- [ ] Sender date/revision requirement explicitly handled, not inferred.
- [ ] Real Colossus loader returns exact five-column unique finite data.
- [ ] Scheduler writes complete OFFICIAL schema-v4 leaves to durable storage.
- [ ] App and scheduler share PL_HISTORICAL_PATH.
- [ ] Archived missing-P&L policy is explicitly accepted or Step 3.8A is implemented and tested.
- [ ] Long-history row limit and Python result-cache bound are tested.
- [ ] SQL summary/series and Validate P&L work on a sandbox archive.
- [ ] Current, send, archive, history, startup, and publish tests pass.

---

# Final integration order

Follow this order to minimize ambiguity.

## Phase 1 — pure contracts

1. Add/validate the new tenor matrix and selector.
2. Add the real Stock source and its unit tests.
3. Add the real Colossus loader and its unit tests.
4. Keep outbound senders fail-closed until their payload contract is approved.

## Phase 2 — archive support

1. Add optional **StockLoader**.
2. Pass it through the writer and scheduled job.
3. Test writer eligibility and atomicity.
4. Point all components at a sandbox history root.
5. Produce one complete test leaf.

## Phase 3 — page integration

1. Start the app.
2. Force one full Risk/P&L refresh.
3. Verify Full and Reduced Risk.
4. Verify current/prior Stock.
5. Query Stock history.
6. Verify archive-backed P&L overview and chart.
7. Verify Predict-versus-Colossus validation.
8. Verify adjustment editor without sending.

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
3. per-source Risk Date;
4. matrix committed key;
5. Full and Reduced hand totals;
6. Stock current and prior source dates;
7. completed archive path;
8. Stock row count;
9. Colossus row count;
10. P&L overview as-of date;
11. one Predict and one Colossus series value;
12. sender acknowledgement in a non-production destination.

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

## Stock rollback

1. Restore the previous current Stock callable.
2. unset **STOCK_LOADER** or omit it from the scheduler.
3. keep valid completed leaves untouched;
4. if necessary, pass no Stock history source to disable history controls.

Schema-v4 permits valid dates with and without Stock. Do not delete archive history as rollback.

## P&L rollback

1. Restore sender functions to fail-closed stubs.
2. restore the previous **COLOSSUS_LOADER**.
3. restore the previous **PL_HISTORICAL_PATH**.
4. disable the scheduler rather than deleting completed leaves.
5. preserve user adjustment files.

Never recursively delete adjustment or history roots during rollback.

# Final acceptance criteria

The change is complete only when all of these are true:

- a new non-Credit matrix is selected by exact raw identity, is same-date with Risk, and is committed/reused/replaced by revision;
- Credit still uses only its separate shared map;
- live Stock returns exact current/prior frames and the current page needs no new callback;
- scheduled official archives contain validated optional Stock and required Predict/Colossus/Market data;
- Stock and P&L history query only completed schema-v4 leaves;
- missing Stock dates and missing P&L dates are not manufactured as zero, and the per-row Predict archive zero-fill policy is explicitly accepted or hardened;
- Portfolio and Product ambiguity is explicit rather than deduplicated;
- P&L overview archive timing is understood;
- outbound sender payload/context is explicit;
- focused and full tests pass;
- real secrets and financial data remain outside Git.
