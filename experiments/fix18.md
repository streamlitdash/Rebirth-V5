# Fix 18 — Hierarchy trade details and T-1 supplemental Risk Date

**Status:** Implemented on the `v4` branch of `Rebirth-V5`.

This guide explains the two commits immediately after the dated-matrix change:

```text
c4834f3  Show trade details from hierarchy rows
0950f47  Use T-1 risk date for supplemental data
```

It is written for someone applying the changes manually on top of commit
`ea3341f` (`Fix 17 — Load dated reduced-tenor matrices with Risk`).

## What this fixes

1. New Trades detail is shown when the user clicks either:
   - the `New Trades` split itself; or
   - any parent hierarchy row which contains New Trades below it.
2. The normal tenor table and plots still describe the row actually clicked.
3. New Trades and Cash Flow use one flat ten-column table:

   ```text
   TradeID
   TypeTrade
   Underlying
   Risk
   NotionalTraded
   TradedSpread
   Portfolio
   TraderCode
   TraderName
   TradeTime
   ```

4. JTD reference data can be opened from a promoted issuer row as well as a raw
   or Reported Underlying row.
5. Cross Gamma and New Trades receive the checker/T-1 Risk Date. Their Market
   Date remains the selected Market Date.

## What this does not change

- It does not change ordinary product Risk dates.
- It does not change Open or Current market connector dates.
- It does not change the Cross Gamma or New Trades calculations.
- It does not add another connector call.
- It does not change cold-start, retry, timeout, reduced-tenor, CSS or JavaScript
  behavior.
- It does not make the checker calendar holiday-aware. The existing checker
  calculation uses weekdays, so Monday maps to the preceding Friday.

## Files changed

Required runtime files:

```text
cube/domain/s05_newtrades.py
cube/pages/risk/s02_state.py
cube/pages/risk/s07_explorer.py
cube/pages/risk/s13_workspacetables.py
cube/adapters/s06_crossgamma.py
cube/adapters/s07_newpositions.py
cube/services/s05_sources.py
cube/services/s06_refresh.py
```

Regression-test files:

```text
tests/s06_ui.py
tests/s15_overlays.py
tests/s26_newtrades.py
tests/s48_jtd.py
```

The application needs the eight runtime files. The four test files do not
change runtime behavior, but they prove that the manual implementation is
complete.

## Safest way to apply it

If your checkout is an unchanged copy of commit `ea3341f`, copying all twelve
files above from the current `v4` branch is the easiest exact installation.

If you have put real connector functions into `cube/services/s05_sources.py`,
do **not** replace that entire file. Apply only Step 8 below so that your real
connector code is preserved. The same warning applies to any other file you
have customized.

Before editing, check the branch and working tree:

```powershell
git branch --show-current
git status --short
git log -1 --oneline
```

Keep a copy of every locally customized file before applying the manual edits.

## Resulting data flow

### New Trades hierarchy click

```text
clicked Risk hierarchy context
  -> scope the already-filtered dashboard rows
  -> check whether that scope contains Split == "New Trades"
  -> only then read position-grain combined_pl
  -> apply the same filters and promotion generation
  -> select the matching Trade IDs
  -> render the ten-column flat table
  -> render the normal tenor detail for the original clicked row
```

The aggregated Risk Explorer frame is used only to decide whether New Trades
exist below the selected row. The descriptive trade table is then read from
`combined_pl`, because Trade ID, Portfolio, trader and traded-level information
must remain at position grain.

### Supplemental date

```text
selected Market Date
  -> existing checker_date calculation
  -> supplemental_risk_date = checker_date
  -> Cross Gamma loader(supplemental_risk_date)
  -> New Trades loader(supplemental_risk_date)
  -> released rows: Risk Date = checker date
  -> released rows: Market Date = selected Market Date
```

For example:

```text
Market Date:  Monday 2026-07-20
Risk Date:    Friday 2026-07-17
```

## Step-by-step manual implementation

## Part A — Hierarchy New Trades and promoted JTD

### 1. Expand the canonical trade-detail fields

Open `cube/domain/s05_newtrades.py` and find
`NEW_TRADE_DETAIL_COLUMNS`.

Replace:

```python
NEW_TRADE_DETAIL_COLUMNS = (
    TRADE_ID,
    RISK,
    NOTIONAL,
    TRADED_LEVEL,
    TRADE_TIME,
    TRADER_CODE,
    TRADER_NAME,
)
```

with:

```python
NEW_TRADE_DETAIL_COLUMNS = (
    TRADE_ID,
    ROW_TYPE,
    UNDERLYING,
    RISK,
    NOTIONAL,
    TRADED_LEVEL,
    PORTFOLIO,
    TRADER_CODE,
    TRADER_NAME,
    TRADE_TIME,
)
```

This is the position-detail contract. It does not alter the connector's larger
New Trades blotter schema.

### 2. Detect New Trades below the selected hierarchy row

Open `cube/pages/risk/s02_state.py` and find
`_new_trade_detail_requested`.

Replace the complete old function:

```python
def _new_trade_detail_requested(
    selected_context: Mapping[str, str],
    splits: Sequence[str] | None,
) -> bool:
    """Recognize New Trades from either the row path or its exact page filter."""

    selected_split = selected_context.get("split")
    return selected_split == NEW_TRADE_SPLIT or (
        selected_split is None and tuple(splits or ()) == (NEW_TRADE_SPLIT,)
    )
```

with:

```python
def _new_trade_detail_requested(
    filtered: pd.DataFrame,
    selected_context: Mapping[str, str],
) -> bool:
    """Whether the selected hierarchy scope contains any New Trades rows."""

    scoped = frame_for_context(filtered, dict(selected_context))
    return bool("split" in scoped and scoped["split"].eq(NEW_TRADE_SPLIT).any())
```

Why this is needed:

- the old function only recognized an explicit `New Trades` split or a page
  filtered exclusively to New Trades;
- the new function scopes the visible data by the clicked hierarchy path; and
- a Risk Greek, promoted issuer or other parent row now qualifies when at least
  one descendant has `split == "New Trades"`.

Do not replace this with a check of every split in the whole page. That would
show unrelated trades under a sibling branch.

### 3. Add the JTD identity helper

In the same `cube/pages/risk/s02_state.py` file, add this function immediately
after `_new_trade_detail_requested`:

```python
def _jtd_underlying_for_context(
    selected_context: Mapping[str, str],
) -> str | None:
    """Resolve the clicked raw, reported, or promoted issuer identity."""

    underlying = selected_context.get("underlying") or selected_context.get(
        "reported underlying"
    )
    if underlying:
        return str(underlying)
    promoted = selected_context.get("display bucket")
    if promoted and promoted != "Other":
        return str(promoted)
    return None
```

The priority is deliberately:

```text
raw Underlying
-> Reported Underlying
-> promoted display bucket
```

`Other` is not a real issuer and must not be sent to the JTD CSV lookup.

No new import is required on the `ea3341f` base: `Mapping`, `pd`,
`frame_for_context` and `NEW_TRADE_SPLIT` are already imported.

### 4. Update the Risk Explorer detail callback

Open `cube/pages/risk/s07_explorer.py`.

#### 4a. Clean up the imports

In the import from `cube.ui.s02_aggregation`, remove `row_key`.

In the import from `.s02_state`, add:

```python
_jtd_underlying_for_context,
```

Remove this import because it is no longer needed in this file:

```python
from .s13_workspacetables import NEW_TRADE_SPLIT
```

#### 4b. Replace the New Trades selection block

Inside the detail callback, immediately after the Credit-measure handling, find
the block starting with `filtered_splits = (` and ending after the construction
of `detail_selection`.

Replace that whole block with:

```python
new_trades_selected = _new_trade_detail_requested(
    filtered,
    selected_context,
)
```

Then use the following position-detail block:

```python
new_trade_details = None
if new_trades_selected:
    combined = refresh_manager.read_frame("combined_pl").frame
    new_trade_details = _new_trade_details_for_selection(
        combined,
        selected_context,
        detail_risk_type,
        ir_family,
        splits,
        reporting_filter_map(dimension_values),
        exclude_selected=exclude_selected,
        promotion_generation=promotion_generation,
        revision=int(cache.revision),
    )
```

Important details:

- `combined_pl` is read only when the selected scope actually contains New
  Trades;
- pass the original `selected_context` into the position-grain selector; and
- do not manufacture a replacement row key with `split="New Trades"`.

Manufacturing a new key was the reason a parent click could lose or distort its
ordinary tenor detail.

#### 4c. Use the promoted-JTD helper

In the JTD block, replace:

```python
jtd_underlying = selected_context.get("underlying") or selected_context.get(
    "reported underlying"
)
```

with:

```python
jtd_underlying = _jtd_underlying_for_context(selected_context)
```

Finally, in the call to `build_detail_panel_with_state`, make sure the second
argument is the original `selection`:

```python
return build_detail_panel_with_state(
    filtered,
    selection,
    compose_detail_metric(plot_measure, plot_component),
    tenor_view,
    new_trade_details=new_trade_details,
    jtd_reference=jtd_reference,
    jtd_underlying=jtd_underlying,
    jtd_error=jtd_error,
)
```

There should be no remaining `detail_selection`, `detail_context`,
`filtered_splits` or `row_key` use in this callback.

### 5. Expand and relax the flat detail table

Open `cube/pages/risk/s13_workspacetables.py`.

#### 5a. Replace the table columns and labels

Replace both constants near the top of the file with:

```python
NEW_TRADE_DETAIL_COLUMNS = (
    "trade id",
    "row type",
    "underlying",
    "risk",
    "notional",
    "traded level",
    "portfolio",
    "trader code",
    "trader name",
    "trade time",
)
NEW_TRADE_DETAIL_LABELS = {
    "trade id": "TradeID",
    "row type": "TypeTrade",
    "underlying": "Underlying",
    "risk": "Risk",
    "notional": "NotionalTraded",
    "traded level": "TradedSpread",
    "portfolio": "Portfolio",
    "trader code": "TraderCode",
    "trader name": "TraderName",
    "trade time": "TradeTime",
}
```

The lowercase names are the internal normalized names. The values in
`NEW_TRADE_DETAIL_LABELS` are the exact headers shown to the user.

#### 5b. Accept compact UI aliases

In `_normalize_new_trade_detail_columns`, keep the existing Portfolio-field
aliases and make the explicit alias section read:

```python
aliases = {
    **{
        field.external_name.strip().casefold(): field.key
        for field in PORTFOLIO_FIELDS
    },
    "portfolio": "portfolio",
    "tradeid": "trade id",
    "typetrade": "row type",
    "type trade": "row type",
    "notionaltraded": "notional",
    "notional traded": "notional",
    "tradedspread": "traded level",
    "traded spread": "traded level",
    "tradercode": "trader code",
    "tradername": "trader name",
    "tradetime": "trade time",
}
```

`Notional` remains optional. The other nine detail columns are required. Do not
make `Row Type`, `Underlying` or `Portfolio` optional because those fields are
part of the requested trade identity.

#### 5c. Allow a parent context without an explicit split

In `new_trade_detail_frame`, replace:

```python
if str(context.get("split", "")) != split:
    return normalized.iloc[0:0].loc[:, list(NEW_TRADE_DETAIL_COLUMNS)]
```

with:

```python
selected_split = str(context.get("split", ""))
if selected_split and selected_split != split:
    return normalized.iloc[0:0].loc[:, list(NEW_TRADE_DETAIL_COLUMNS)]
```

Make the identical condition change at the start of
`build_new_trade_detail_table`:

```python
selected_split = str(context.get("split", ""))
if selected_split and selected_split != split:
    return None
```

This means:

```text
no Split in the clicked parent path  -> table is allowed
Split == New Trades                  -> table is allowed
Split == Risk or another sibling     -> table is suppressed
```

#### 5d. Render all ten cells in the exact order

Inside `build_new_trade_detail_table`, replace the complete existing
`rows.append(...)` block with:

```python
rows.append(
    html.Tr(
        [
            html.Td(_format_new_trade_text(record["trade id"])),
            html.Td(_format_new_trade_text(record["row type"])),
            html.Td(_format_new_trade_text(record["underlying"])),
            html.Td(
                _format_new_trade_number(record["risk"], decimals=1),
                className="detail-number",
            ),
            html.Td(
                _format_optional_new_trade_number(
                    record["notional"], decimals=0
                ),
                className="detail-number",
            ),
            html.Td(
                _format_new_trade_number(
                    record["traded level"], decimals=6
                ),
                className="detail-number",
            ),
            html.Td(_format_new_trade_text(record["portfolio"])),
            html.Td(_format_new_trade_text(record["trader code"])),
            html.Td(_format_new_trade_text(record["trader name"])),
            html.Td(_format_new_trade_text(record["trade time"])),
        ]
    )
)
```

Keep the empty-row `colSpan` derived from
`len(NEW_TRADE_DETAIL_COLUMNS)`. It will automatically become ten.

Cash Flow uses this same table. Its normalized detail row supplies:

```text
TypeTrade = CASHFLOW
Underlying = Cash Flow
Risk = released cash-flow amount
Portfolio = source Portfolio
unavailable trade fields = blank/em dash
```

Do not merge the descriptive table back into the aggregated dashboard frame.
The existing position-grain trace is the correct authority.

## Part B — T-1 Risk Date for Cross Gamma and New Trades

### 6. Rename the Cross Gamma adapter date parameter

Open `cube/adapters/s06_crossgamma.py`.

This step is a semantic rename: the supplied date was previously named
`market_date`, but it now represents a Risk Date.

Change the protocol to:

```python
class CrossGammaSource(Protocol):
    """Site-owned portfolio sensitivity matrix source."""

    def __call__(self, risk_date: pd.Timestamp) -> pd.DataFrame: ...
```

Change `_normalized_date` messages from `market_date` to `risk_date`:

```python
def _normalized_date(value: object) -> pd.Timestamp:
    if value is None or isinstance(value, (bool, np.bool_)):
        raise TypeError("risk_date must be a date-like value")
    try:
        selected = pd.Timestamp(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("risk_date must be a valid scalar date") from exc
    if pd.isna(selected):
        raise ValueError("risk_date must be a valid scalar date")
    if selected.tzinfo is not None:
        selected = selected.tz_localize(None)
    return selected.normalize()
```

Change the adapter wrapper to:

```python
def build_cross_gamma_adapter(*, sensitivities: CrossGammaSource) -> CrossGammaLoader:
    """Bind a personal portfolio sensitivity source to the strict raw contract."""

    if not callable(sensitivities):
        raise TypeError("sensitivities must be callable")

    def get_cross_gamma(risk_date: pd.Timestamp) -> pd.DataFrame:
        selected_date = _normalized_date(risk_date)
        return validate_cross_gamma_rows(sensitivities(selected_date))

    return get_cross_gamma
```

Rename the temp and public function parameters as well:

```python
def _temp_cross_gamma(_risk_date: pd.Timestamp) -> pd.DataFrame:
    ...


def get_cross_gamma(risk_date: pd.Timestamp) -> pd.DataFrame:
    """Return deterministic temp Credit Cross Gamma sensitivity rows."""

    return _DEFAULT_ADAPTER(risk_date)
```

No Cross Gamma columns, matrix identities or calculations change here.

### 7. Rename the New Positions/New Trades adapter date parameter

Open `cube/adapters/s07_newpositions.py`.

Change the protocol to:

```python
class NewPositionsSource(Protocol):
    """Personal blotter callable bound by :func:`build_new_positions_adapter`."""

    def __call__(self, risk_date: pd.Timestamp) -> pd.DataFrame: ...
```

Change the three validation messages inside `_normalized_date` from
`market_date` to `risk_date`.

Change the adapter wrapper to:

```python
def build_new_positions_adapter(
    *,
    blotter: NewPositionsSource,
) -> NewPositionsLoader:
    """Bind a personal raw-blotter function to the strict public contract."""

    if not callable(blotter):
        raise TypeError("blotter must be callable")

    def get_new_positions(risk_date: pd.Timestamp) -> pd.DataFrame:
        selected_date = _normalized_date(risk_date)
        return validate_new_positions(blotter(selected_date))

    return get_new_positions
```

For the temp source, change:

```python
def _temp_new_positions(risk_date: pd.Timestamp) -> pd.DataFrame:
    """Return deterministic illustrative rows; replace this source in production."""

    trade_day = risk_date.normalize()
```

Change the public wrapper to:

```python
def get_new_positions(risk_date: pd.Timestamp) -> pd.DataFrame:
    """Return the validated deterministic temp new-position blotter."""

    return _DEFAULT_ADAPTER(risk_date)
```

Do not change the New Trades schema or row validation in this step.

### 8. Update the two service connector boundaries

Open `cube/services/s05_sources.py`.

Replace only these two functions. This is especially important if this file
contains your real connector code.

```python
def get_cross_gamma_sensitivities(risk_date: pd.Timestamp) -> pd.DataFrame:
    """Return validated portfolio-level XGAMMA sensitivity matrix rows."""

    selected_date = _normalized_date(risk_date, parameter="risk_date")
    return get_cross_gamma_matrix(selected_date)


def get_new_trades(risk_date: pd.Timestamp) -> pd.DataFrame:
    """Return the validated mixed MARKET/CASHFLOW New Trades blotter."""

    selected_date = _normalized_date(risk_date, parameter="risk_date")
    return get_new_position_blotter(selected_date)
```

If your real functions are in another adapter file, their equivalent signature
should also be:

```python
def my_cross_gamma_connector(risk_date: pd.Timestamp) -> pd.DataFrame:
    ...


def my_new_trades_connector(risk_date: pd.Timestamp) -> pd.DataFrame:
    ...
```

The refresh manager already holds function references. Do not call either
function yourself during app construction.

### 9. Pass the checker date from the refresh manager

Open `cube/services/s06_refresh.py`.

#### 9a. Define one shared supplemental Risk Date

Find this comment in the Risk-loading section:

```python
# Raw supplemental sources are loaded exactly once before
# MarketBook calls. Their input/target identities expand the
# connector scope without becoming ordinary aged Risk rows.
```

Immediately below it, add:

```python
supplemental_risk_date = checker_date
```

Keep the existing `raw_cross_gamma`, `raw_new_trades` and market-scope
initialization immediately after it.

#### 9b. Change the two loader calls

Change:

```python
lambda: loader(market_date)
```

to:

```python
lambda: loader(supplemental_risk_date)
```

Do this in exactly two places:

```text
("supplemental", "cross_gamma")
("supplemental", "new_trades")
```

Do not change ordinary product Risk loaders or market loaders.

#### 9c. Stamp both released overlay frames correctly

In the Cross Gamma overlay block, use:

```python
if not cross_gamma.empty:
    cross_gamma[RISK_DATE] = supplemental_risk_date
    cross_gamma[MARKET_DATE] = market_date
```

In the New Trades overlay block, use:

```python
if not new_trades.empty:
    new_trades[RISK_DATE] = supplemental_risk_date
    new_trades[MARKET_DATE] = market_date
```

Do not change the `MARKET_DATE` assignments. Cross Gamma and New Trades still
use the current MarketBook to calculate their released output. Only their
source Risk Date is T-1.

## Real connector example

The connector receives the resolved checker date directly:

```python
def get_real_new_trades(risk_date: pd.Timestamp) -> pd.DataFrame:
    print(f"New Trades Risk Date: {risk_date:%Y-%m-%d}")
    return real_client.get_new_trades(risk_date=risk_date)


def get_real_cross_gamma(risk_date: pd.Timestamp) -> pd.DataFrame:
    print(f"Cross Gamma Risk Date: {risk_date:%Y-%m-%d}")
    return real_client.get_cross_gamma(risk_date=risk_date)
```

Register those functions in
`cube/services/s05_sources.py::build_production_refresh_manager`. Pass the
functions by reference; do not invoke them there:

```python
RiskRefreshManager(
    ...,
    cross_gamma_matrix_loader=get_real_cross_gamma,
    new_trades_loader=get_real_new_trades,
    ...,
)
```

If you kept the existing public wrapper names
`get_cross_gamma_sensitivities` and `get_new_trades` and edited only their
bodies, the existing registrations in `build_production_refresh_manager` are
already correct and need no further change.

Positional callers continue to work because the callable still accepts one
date. A caller using a keyword must change:

```python
get_new_trades(market_date=selected_date)
```

to:

```python
get_new_trades(risk_date=selected_date)
```

The same applies to Cross Gamma.

## Regression tests

The implementation changed these tests:

### `tests/s06_ui.py`

Verify:

- the exact ten headers and their order;
- selected-context filtering;
- a parent context without `split` can render the table;
- an explicit non-New-Trades split suppresses it;
- the empty state spans ten columns;
- missing Notional remains allowed;
- Cash Flow uses the same table; and
- a parent click keeps ordinary tenor detail while adding the trade table.

### `tests/s26_newtrades.py`

Verify:

- Cash Flow position details survive the complete manager release;
- the normalized detail projection has exactly ten columns; and
- `_new_trade_detail_requested(filtered, context)` is true only when that
  selected scope contains at least one New Trades row.

### `tests/s48_jtd.py`

Verify the JTD priority:

```text
raw Underlying > Reported Underlying > promoted display bucket
```

Also verify that `display bucket == "Other"` returns no issuer.

### `tests/s15_overlays.py`

Wrap both supplemental loaders so the test records the date supplied by the
manager. For a clock on Monday `2026-07-20`, assert:

```python
expected_risk_date = pd.Timestamp("2026-07-17")

assert snapshot.market_date == pd.Timestamp("2026-07-20")
assert snapshot.checker_date == expected_risk_date
assert cross_gamma_dates == [expected_risk_date]
assert new_trade_dates == [expected_risk_date]
```

For both `XGAMMA` and `New Trades` rows in `combined_pl`, assert:

```text
Risk Date   == 2026-07-17
Market Date == 2026-07-20
```

## Validation commands

Run the four focused test files first:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest `
    tests\s06_ui.py `
    tests\s15_overlays.py `
    tests\s26_newtrades.py `
    tests\s48_jtd.py -q
```

Then run the full test suite:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest -q
```

Run the quality checks:

```powershell
& '.\.venv\Scripts\python.exe' -m ruff check cube tests
& '.\.venv\Scripts\python.exe' -m ruff format --check cube tests
git diff --check
```

The published `v4` implementation passed 673 tests plus Ruff, formatting and
`git diff --check`.

## Manual smoke test

After changing Python files, completely restart the Python/Dash server. A
browser refresh alone does not reload imported Python modules.

1. Start the app and allow revision 1 to finish.
2. Open the Risk Explorer.
3. Select a Risk hierarchy which contains a `New Trades` descendant.
4. Click the Risk Greek or issuer parent row.
5. Confirm the New Trades table appears above the ordinary tenor detail.
6. Confirm all ten headers appear in the exact requested order.
7. Click an explicit `Risk` split and confirm the New Trades table disappears.
8. Select Credit JTD and click a promoted issuer row.
9. Confirm the flat JTD reference table appears for that issuer.
10. Print or log the date received by both real supplemental connectors.
11. On a Monday Market Date, confirm both receive the preceding Friday.
12. Inspect `combined_pl` and confirm supplemental Risk Date is T-1 while Market
    Date remains the selected date.

## Common problems

### The table still appears only when `New Trades` is clicked

You likely changed the table component but missed either:

```text
cube/pages/risk/s02_state.py::_new_trade_detail_requested
cube/pages/risk/s07_explorer.py detail callback
```

Both changes are required.

### Clicking a parent shows the table but loses the ordinary tenor detail

Remove the old synthetic `detail_selection`/`row_key` logic. Pass the original
`selection` to `build_detail_panel_with_state`.

### `Missing new-trade detail columns` appears

The selected position trace must contain:

```text
Trade ID
Row Type
Underlying
Risk
Traded Level
Portfolio
Trader Code
Trader Name
Trade Time
```

`Notional` is the only optional display field.

### The table shows trades from an unrelated branch

Make sure `_new_trade_detail_requested` calls:

```python
frame_for_context(filtered, dict(selected_context))
```

before checking the `split` column. Do not check the entire page frame without
the selected hierarchy context.

### A promoted JTD issuer shows no reference rows

Check that:

- the selected display bucket is not `Other`;
- the promoted issuer text exactly matches `Underlying` in `s13_jtd.csv`; and
- `s13_jtd.csv` was copied into the active `data` directory.

### The connector still receives Market Date

Check all three parts of Step 9:

1. `supplemental_risk_date = checker_date` exists;
2. both loaders receive `supplemental_risk_date`; and
3. both overlay `RISK_DATE` columns receive it.

Then fully restart the server.

### A keyword call raises `unexpected keyword argument 'market_date'`

Change the caller to `risk_date=...`. Positional calls require no change.

### Monday does not map to Friday around a holiday

This change deliberately reuses the existing weekday checker calculation. It
does not add a holiday calendar. If a site holiday calendar is required, that
is a separate change to the date authority and should not be hidden in these
supplemental adapters.

### Old buttons or old table columns are still visible

Stop the running server, start it again from the updated checkout, then hard
refresh the browser. Confirm the terminal's working directory points to the
same repository where these files were edited.

## Rollback

If these exact commits have been committed and pushed, use normal revert
commits in newest-first order:

```powershell
git revert 0950f47
git revert c4834f3
```

Do not use `git reset --hard` on a working copy containing personal connector
edits.

For a manual uncommitted installation, restore the eight runtime files from
your saved copies. If you also copied or edited the regression tests, restore
those four test files as well. The clean base immediately before these changes
is commit `ea3341f`.

## Final checklist

```text
[ ] 8 runtime files updated
[ ] 4 regression-test files updated or equivalent tests added
[ ] No real connector code overwritten
[ ] New Trades parent-click detection uses the scoped filtered frame
[ ] Original clicked selection still owns ordinary tenor detail
[ ] Ten requested table columns appear in exact order
[ ] JTD accepts promoted issuer and rejects Other
[ ] Cross Gamma receives checker/T-1 date
[ ] New Trades receives checker/T-1 date
[ ] Supplemental Risk Date is T-1
[ ] Supplemental Market Date remains selected Market Date
[ ] Server fully restarted
[ ] Focused tests pass
[ ] Full suite and quality checks pass
```
