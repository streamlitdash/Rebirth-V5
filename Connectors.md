# Real connectors: Cross Gamma, new trades, Stock and P&L

This is an implementation guide, not an already connected production feed. It was checked against commit `2220a3f4839318863a9131e3fef8118d0f82fb7d`. Publishing this guide does not change the application.

The simplest approach is to replace the existing temporary source functions and keep the existing validators, refresh manager and page callbacks. You do not need a new connector framework, another database or a background worker just to connect these feeds.

## 1. Where everything goes

| What you supply | Existing entry point | What happens next |
|---|---|---|
| Cross Gamma matrix | `cube/adapters/s06_crossgamma.py::get_cross_gamma` | Validates cells, requests their market identities, develops output risk, joins the main snapshot. |
| Today's new market positions and cashflows | `cube/adapters/s07_newpositions.py::get_new_positions` | Validates the blotter, joins market quotes for MARKET rows, uses the supplied amount for CASHFLOW rows, joins the main snapshot. |
| Stock for a particular date | `cube/adapters/s08_stock.py::get_stock` | Stock page calls it for current and prior dates, compares them, and attaches Portfolio metadata. |
| Existing positions, opening quotes and current quotes | `cube/services/s05_sources.py::{get_risk,get_market_open,get_market_status}` | Product validators and existing product formulas calculate live P&L. |
| Official realised/actual Colossus P&L | `cube/services/s05_sources.py::get_colossus_pl` | The separate archive job saves it; P&L History reads the completed archive. |

**Implementation order:** make the shared Portfolio and market sources real in section 2; connect Cross Gamma in section 3; new trades in section 4; Stock in section 5; then P&L and history in section 6. You can connect Stock independently if its Portfolio source is ready.

The code below uses imports such as `from your_company_connectors import GetStock`. **That is a placeholder for your own existing connector module and function, not a package in this repository.** Replace that import with your actual import. If your connector already returns the listed columns, the wrapper is almost finished. Otherwise rename/select its columns before returning them. Do not copy the illustrative financial rows into a production feed.

For example, this is how a source-specific rename belongs inside a wrapper:

```python
frame = YourActualFunction(stock_date)
frame = frame.rename(columns={"your_crds_field": "CRDS"})
return frame.loc[:, list(STOCK_COLUMNS)].copy()
```

Replace the example source name and field name with yours. Do not use `.reindex(columns=...)` to silently create missing required data. Selecting with `.loc` makes a missing field visible immediately.

## 2. Shared prerequisites: use real identities, dates and market data

### 2.1 Replace the Portfolio mapping source

In `cube/services/s05_sources.py`, replace the **whole body** of `get_portfolio_config`; keep its signature. This function already feeds both the Risk pipeline and Stock.

```python
def get_portfolio_config(portfolio_date: pd.Timestamp) -> pd.DataFrame:
    from your_company_connectors import GetPortfolioConfig

    selected_date = _business_date(portfolio_date, parameter="portfolio_date")
    frame = GetPortfolioConfig(selected_date)
    columns = list(PORTFOLIO_CONFIG_REQUIRED_COLUMNS)
    if "Sub Category" in frame:
        columns.append("Sub Category")
    return frame.loc[:, columns].copy()
```

Return one row per `Portfolio`:

| Column | Meaning |
|---|---|
| `Portfolio` | Exact book identifier used by every other feed. |
| `Product` | Exactly `XVA` or `Hedges`; this is the XVA/hedge classification, not the instrument name. |
| `Activity` | Your authoritative Activity label. |
| `SignoffGroup` | Your authoritative signoff group. |
| `Category` | Your authoritative category. |
| `Sub Category` | Optional; omit if genuinely absent. |

The Risk manager passes the preceding business day as `portfolio_date`. The Stock page passes its selected current Stock date. **Honour the date supplied; do not subtract another day inside your connector.** Unmapped books remain in the app as `Unmapped`, but the intended filters and P&L sending require correct mappings.

Remove the old `_read_temp_csv` and `_require_temp_notice` calls **from this replaced body**. Keep those helper functions while other source functions still use them. Do not merely delete `TEMP_REPLACE_ME` from fixture rows.

### 2.2 Replace existing-position Risk

In the same file, replace `get_risk` with:

```python
def get_risk(risk_date: pd.Timestamp, source_type: str) -> pd.DataFrame:
    from your_company_connectors import GetRisk

    selected_date = _business_date(risk_date, parameter="risk_date")
    spec = _source_spec(source_type)
    frame = GetRisk(selected_date, source_type)
    columns = [
        "Underlying", *spec.tenor_columns,
        "Portfolio", "Group", "Risk", "dRisk", VOL_SCORE,
    ]
    if spec.risk_type == "Credit":
        if REGION in frame:
            columns.insert(columns.index("Group") + 1, REGION)
        columns.extend(column for column in CREDIT_MEASURE_COLUMNS if column in frame)
    return frame.loc[:, columns].copy()
```

`GetRisk` above must use **both** its arguments. An API returning all products must be filtered to the requested `source_type` before the return.

Required shapes, in the order returned by this wrapper:

```text
Scalar:  Underlying, Portfolio, Group, Risk, dRisk, Vol Score
Curve:   Underlying, Tenor Swap, Portfolio, Group, Risk, dRisk, Vol Score
Surface: Underlying, Tenor Swap, Tenor Option,
         Portfolio, Group, Risk, dRisk, Vol Score
```

Use raw market Underlying identifiers and exact connector tenor labels. `Group` belongs to the source. The common validator adds/enforces `Risk Type` and `Risk Greek`; do not add `Reported Underlying`, Portfolio metadata, calculated PL, or a derived Gamma row here.

`Risk`, `dRisk` and `Vol Score` are numeric. `Risk` is the authoritative sensitivity in the agreed product units; it is not automatically Notional. `dRisk` is your source's actual change measure, not `Risk` copied into another column. `Vol Score` is required and must be between 0 and 100; if you do not have one, first agree what the score means and supply it deliberately. The current validator discards rows with blank Risk and retains blank dRisk as unavailable. It rejects ordinary malformed values, but explicitly converts tokens such as `"inf"`/`"N/A"` and numeric infinity to zero in Risk measures. Do not rely on that conversion to validate a live source: return finite Risk and explicit missing dRisk, and reconcile this existing policy with the source meaning.

Positions are unique by `Underlying` + required tenors + `Portfolio` within a product. If Credit supplies `Region`, that field also participates in the position key. `Group` alone does not distinguish duplicates. Aggregate genuine trade-level sensitivities to this key only when that is the approved source meaning; otherwise add the missing identity to the contract deliberately. Do not use an arbitrary `drop_duplicates()`.

Credit may supply `Region` and paired measures such as `Risk JTD` + `dRisk JTD`, `Risk SP01` + `dRisk SP01`, `Risk PSP01` + `dRisk PSP01`, `Risk PM01` + `dRisk PM01`, `Risk PM01P` + `dRisk PM01P`, and `Risk Theta` + `dRisk Theta`. Supply both columns of a pair or omit both. The separate JTD detail source is covered in `JTD.md`.

### 2.3 Replace Open and Current market sources

In `cube/services/s05_sources.py`, replace these two complete functions. Keep their signatures:

```python
def get_market_open(
    source_type: str,
    open_date: pd.Timestamp,
    underlying: str,
    *,
    market_status: str,
) -> pd.DataFrame:
    from your_company_connectors import GetMarketOpen

    selected_date = _business_date(open_date, parameter="open_date")
    selected_status = _market_status(market_status)
    spec = _source_spec(source_type)
    frame = GetMarketOpen(
        source_type, selected_date, underlying, market_status=selected_status
    )
    columns = [
        UNDERLYING, *spec.tenor_columns, *spec.tenor_order_columns, OPEN,
    ]
    return frame.loc[:, columns].copy()


def get_market_status(
    source_type: str,
    market_date: pd.Timestamp,
    underlying: str,
    *,
    market_status: str,
) -> pd.DataFrame:
    from your_company_connectors import GetMarketCurrent

    selected_date = _business_date(market_date, parameter="market_date")
    selected_status = _market_status(market_status)
    spec = _source_spec(source_type)
    frame = GetMarketCurrent(
        source_type, selected_date, underlying, market_status=selected_status
    )
    columns = [
        UNDERLYING, *spec.tenor_columns, *spec.tenor_order_columns, CURRENT,
    ]
    result = frame.loc[:, columns].copy()
    result[MARKET_STATUS] = selected_status
    return result
```

The actual source must select the requested `underlying` and the exact supplied status, `Live` or `OFFICIAL`. Current is a value column named `Current`; `Market Status` is routing metadata. Setting that metadata does not turn a live quote into an official quote.

For a surface the returns are:

```text
Open:    Underlying, Tenor Swap, Tenor Option,
         Tenor Swap Order, Tenor Option Order, Open
Current: Underlying, Tenor Swap, Tenor Option,
         Tenor Swap Order, Tenor Option Order, Current, Market Status
```

For a curve omit both Option fields. For a scalar omit all tenor/order fields. Return numeric quotes, not strings formatted with commas or percent signs. The order fields are finite integer ranks supplied by your market authority; use the same label/rank convention across Open and Current. Do not sort tenor strings alphabetically to invent financial order.

There must be one quote per raw Underlying + required tenors, within the requested product. **No Portfolio column in market data.** Three hundred Portfolios sharing a quote should join to one market row. Return all genuine tenor quotes for the requested Underlying, including tenors without an existing position; this also supports Cross Gamma, new trades and Quick Market.

Open is requested for the preceding business day; Current is requested for the selected market day. Risk has its separately selected effective date. The manager supplies these dates already. Current weekday handling is Monday–Friday; no desk holiday calendar is inferred.

### 2.4 Do not leave the FX Delta bulk hook connected to fixtures

**This step is easy to miss.** `_get_csv_product_connector_adapters()` currently registers special bulk functions for `fx/delta`. The manager prefers those over the individual market functions above.

For the simplest working integration, inside the `ProductConnectorAdapter(...)` construction in `_get_csv_product_connector_adapters`, replace:

```python
            market_open_bulk=(
                get_fx_delta_market_open_bulk if source_type == "fx/delta" else None
            ),
            market_status_bulk=(
                get_fx_delta_market_status_bulk if source_type == "fx/delta" else None
            ),
```

with:

```python
            market_open_bulk=None,
            market_status_bulk=None,
```

Now FX Delta also calls your real functions in section 2.3. Keep the other three adapter arguments and the registration loop. This is one quote call per requested Underlying, **not one call per Portfolio**.

If your existing market connector supports a real batch, retain the two hooks instead and replace the bodies of `get_fx_delta_market_open_bulk(open_date, underlyings, *, market_status)` and `get_fx_delta_market_status_bulk(market_date, underlyings, *, market_status)`. Pass the supplied ordered tuple of Underlyings to your batch service. Return the same scalar columns as above, containing only requested Underlyings, once per quote. Preserve one batched request per leg. Do not keep the fixture-backed `_get_fx_delta_market_bulk` as their implementation. These are two alternative wirings; choose one, not both.

### 2.5 Replace the remaining source authorities used by the refresh

In `cube/services/s05_sources.py`, replace only the bodies listed below with calls to your actual sources. These functions are already wired in `build_production_refresh_manager`; keep that wiring.

| Function | Required return and use |
|---|---|
| `get_risk_checker(checker_date)` | Tuple `(readiness, inventory)`. Readiness columns: `Risk Type, Risk Greek, Age`. Inventory columns: `Risk Type, Risk Greek, MRX File, Product`. Age is a nonnegative integer; it controls the effective Risk date from the supplied checker day. Return genuine availability/age, not always zero. |
| `get_market_state(market_date, *, trading_timezone=..., now=None)` | Exactly `Live` or `OFFICIAL`. Replace the local cutoff calculation if your real source has an official completion service. Keep the parameters; the manager calls the function once and passes the result to all quote calls. |
| `get_risk_thresholds()` | `Risk Type, Risk Greek, PL, Risk, dRisk`, one unique row per required product pair, positive finite thresholds. These are your promotion settings, not data copied from a Risk observation. |
| `get_reported_underlyings()` | `Risk Type, Risk Greek, Underlying, Reported Underlying`, unique on the first three columns. Return real mappings; missing mappings fall back to raw identity. An intentionally empty mapping must retain these headers. |
| `get_pinned_promotions()` | `Risk Type, Risk Greek, Reported Underlying, Underlying`, unique on all four. Keep your governed CSV if it already contains the desired real pins; an empty, correctly headed frame means no pins. |

Template for replacing one body, with the actual import filled in:

```python
def get_risk_checker(checker_date: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame]:
    from your_company_connectors import GetRiskChecker

    selected_date = _business_date(checker_date, parameter="checker_date")
    readiness, inventory = GetRiskChecker(selected_date)
    return (
        readiness.loc[:, ["Risk Type", "Risk Greek", "Age"]].copy(),
        inventory.loc[:, ["Risk Type", "Risk Greek", MRX_FILE, "Product"]].copy(),
    )
```

The three undated governance functions follow the same pattern: call your function, select the exact columns in the table, return a DataFrame. For `get_market_state`, call your status service and validate its return with `_market_status`; do not infer official completion by renaming a live dataset.

The factory registers all 16 product contracts. Connecting only one product while leaving the others on fixtures produces a mixed dataset, not a finished production cutover. Base Risk currently rejects a completely empty source frame; do not fabricate a zero row for an unsupported or legitimately empty product. Decide which products the production deployment supports and handle that source-contract case explicitly before enabling a partial universe. Empty Cross Gamma/new-trade/Stock returns have their separate rules below.

### 2.6 Check the financial unit convention before reconciling totals

`cube/domain/s02_products.py::PRODUCT_SPECS` is the authority. The existing source pairs are:

| Source Type | Risk Type / Greek | Axes | Current formula |
|---|---|---|---|
| `fx/delta` | FX / Delta | none | percentage |
| `fx/gamma` | FX / Gamma | none | Taylor Gamma |
| `fx/vega` | FX / Vega | Swap | absolute |
| `ir/delta`, `ir/xccy`, `ir/inflation`, `ir/basis`, `ir/bond` | IR / Delta, XCCY, Inflation, Basis, Bond | Swap | absolute |
| `ir/gamma` | IR / Gamma | Swap | Taylor Gamma |
| `ir/deltavega`, `ir/xccyvega`, `ir/inflationvega` | IR / DeltaVega, XCCYVega, InflationVega | Swap + Option | percentage |
| `credit/delta`, `credit/vega` | Credit / Delta, Vega | Swap | absolute |
| `commo/delta` | Commo / Delta | Swap | percentage |
| `commo/vega` | Commo / Vega | Swap | absolute |

For ordinary products, absolute means `Risk * (Current - Open) * multiplier`; percentage means `Risk * ((Current - Open) / Open) * multiplier`. Multipliers default to 1. The market-unit label alone does **not** insert a basis-point conversion. For example, a Risk quoted per bp needs market values whose difference is compatible with that risk, or a deliberately configured multiplier. Reconcile one known position for each product instead of assuming a label such as `bp` performs the conversion.

IR Gamma currently explicitly scales the raw quote difference by 10,000 and uses risk step 10; FX Gamma uses the default scales. Keep existing formulas until the desk's actual sensitivity convention is confirmed. Cross Gamma has its own convention in section 3.3.

Two existing behaviours matter with real feeds: `_merge_validated_market_legs` currently copies the available quote into a missing opposite leg, labels it `Available; ... copied ...`, and produces a zero move. `_normalize_computed_pl` also turns nonfinite calculations into zero when market is marked available. These are current application policies, **not evidence that the missing source data was retrieved**. This connector guide does not silently change them. Include missing-quote and zero-Open examples in reconciliation; resolve those policies before treating the displayed numbers as production results. Never add additional fallback zeros in your connectors.

## 3. A — Connect Cross Gamma

### 3.1 Replace the temporary matrix function

Open `cube/adapters/s06_crossgamma.py`.

1. Remove the whole `_temp_cross_gamma` function, including its illustrative rows.
2. In the same location add:

```python
def _live_cross_gamma(market_date: pd.Timestamp) -> pd.DataFrame:
    from your_company_connectors import GetCrossGamma

    frame = GetCrossGamma(market_date)
    # Rename your source columns here, if needed.
    return frame.loc[:, list(CROSS_GAMMA_COLUMNS)].copy()
```

3. Replace `_DEFAULT_ADAPTER = build_cross_gamma_adapter(sensitivities=_temp_cross_gamma)` with:

```python
_DEFAULT_ADAPTER = build_cross_gamma_adapter(sensitivities=_live_cross_gamma)
```

4. Keep `build_cross_gamma_adapter`, `get_cross_gamma`, the `GetCrossGamma` compatibility alias and `validate_cross_gamma_rows`. Change the `get_cross_gamma` docstring to say it returns the validated live matrix.
5. Keep `cube/services/s05_sources.py::get_cross_gamma_sensitivities` and `cross_gamma_matrix_loader=get_cross_gamma_sensitivities` in the manager factory. They already route to this adapter. No page callback change is needed.

### 3.2 Return one row per complete matrix cell

Return exactly these 14 columns, in this order:

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
```

All identities are text. Required tenors come from each side's ProductSpec; use an empty string `""` for an axis that product does not have. `Cross Gamma Sensitivity` must be a finite number. The full first 13 columns identify a cell; duplicate cells are rejected.

`Input Risk Greek` is the actual product Greek that chooses the market quote, such as `Delta` or `Vega`. The separate `Risk Greek` column is the sensitivity's display classification: `XGamma Vega` when the input Greek is `Vega`, `DeltaVega`, `InflationVega` or `XCCYVega`; otherwise `XGamma`. Output Risk Type/Greek is the actual target product pair. Both sides must exist in `PRODUCT_SPECS`; Cash Flow/New is not allowed.

An illustrative row shape is:

```python
{
    "Portfolio": "BOOK_A",
    "Group": "Index",
    "Input Risk Type": "Credit",
    "Input Risk Greek": "Delta",
    "Risk Greek": "XGamma",
    "Input Underlying": "CDX IG",
    "Input Tenor Swap": "5Y",
    "Input Tenor Option": "",
    "Output Risk Type": "Credit",
    "Output Risk Greek": "Delta",
    "Output Underlying": "Example CDS",
    "Output Tenor Swap": "5Y",
    "Output Tenor Option": "",
    "Cross Gamma Sensitivity": 125.0,
}
```

If there are genuinely no cells on that date, return `pd.DataFrame(columns=list(CROSS_GAMMA_COLUMNS))`. A source outage is not “no cells”: let the source error propagate; do not catch it and return an empty success.

### 3.3 Understand the flow

```text
Your matrix for the selected market date
  -> adapter normalises the date and validates cells
  -> manager includes both input and output Underlyings in quote scope
  -> normal Open/Current connectors build MarketBooks
  -> sensitivity * input MarketBook Move = output-risk contribution
  -> contributions with the same Portfolio/Group/output identity are summed
  -> Portfolio mapping, reporting and dashboard release
```

The `Move` consumed here is the stored **raw `Current - Open`**, even for a product whose ordinary P&L uses a percentage formula. Your sensitivity must be per unit of that stored move. Cross Gamma does not apply an extra bp conversion or 0.5 factor. For example, sensitivity 125 and stored move 2 produces output risk 250.

The code keeps the source sensitivity under `XGamma`/`XGamma Vega`, `Split="Risk"`, and releases the developed target exposure under its real Greek with `Split="XGAMMA"`. **Both legs currently have PL 0 and unavailable dRisk.** This integration adds the existing Cross Gamma exposure behaviour; it is not a new Cross Gamma P&L engine.

An unavailable input quote fails the development step. An absent output quote can retain calculated risk with market marked unavailable. Inspect the actual quote status too, because the existing one-sided-quote copying described above can produce an apparent zero move.

## 4. B — Connect new MARKET trades and CASHFLOW rows

### 4.1 Replace the temporary blotter function

Open `cube/adapters/s07_newpositions.py`.

1. Remove the whole `_temp_new_positions` function and its sample rows.
2. Add this in its place:

```python
def _live_new_positions(market_date: pd.Timestamp) -> pd.DataFrame:
    from your_company_connectors import GetNewPositions

    frame = GetNewPositions(market_date)
    # Rename/normalise your source fields here before selecting them.
    return frame.loc[:, list(NEW_POSITION_BLOTTER_COLUMNS)].copy()
```

3. Replace `_DEFAULT_ADAPTER = build_new_positions_adapter(blotter=_temp_new_positions)` with:

```python
_DEFAULT_ADAPTER = build_new_positions_adapter(blotter=_live_new_positions)
```

4. Keep `validate_new_positions`, `build_new_positions_adapter`, `get_new_positions` and the `GetNewPositions` alias. Update the public function's temp docstring.
5. Keep `get_new_trades` and `new_trades_loader=get_new_trades` in `cube/services/s05_sources.py`. They already use this adapter.

### 4.2 Return this exact raw blotter

Your personal connector returns **17 columns**; the adapter adds the 18th `PL` column. Do not add PL to your raw return.

| Column, in order | MARKET row | CASHFLOW row |
|---|---|---|
| `Row Type` | `MARKET` | `CASHFLOW` |
| `Trade ID` | Nonblank text | Nonblank text |
| `Position ID` | Nonblank text | Nonblank text |
| `Risk Type` | Existing product type | `Cash Flow` |
| `Risk Greek` | Existing product Greek | `New` |
| `Underlying` | Raw quote identifier | `""` |
| `Tenor Swap` | Required tenor, or `""` for scalar | `""` |
| `Tenor Option` | Required tenor for a surface, otherwise `""` | `""` |
| `Portfolio` | Exact book identifier | Exact book identifier |
| `Risk` | Finite, signed sensitivity | `np.nan` |
| `Notional` | Optional finite number, otherwise `np.nan` | `np.nan` |
| `Traded Level` | Finite value if known; otherwise `np.nan` | `np.nan` |
| `Traded True` | Python `True` or `False` | `False` |
| `Trade Time` | Valid trade timestamp | `pd.NaT` |
| `Trader Code` | Nonblank text | `""` |
| `Trader Name` | Nonblank text | `""` |
| `Cash Flow` | `np.nan` | Finite signed P&L amount |

The combination `(Trade ID, Position ID)` must be unique across the entire returned blotter. If a trade contains multiple risk buckets, return a stable position/bucket identifier for each distinct row. Do not repeat one Position ID across tenors and expect the validator to aggregate it.

`Traded True` must be a real boolean, not `"True"`, `"False"`, 0 or 1. When it is false, leave `Traded Level` missing so the engine deliberately falls back to Open. Do not write `.astype(bool)` on source strings: the nonempty string `"False"` becomes true. Map your source flags explicitly.

Convert timestamps to the agreed desk timezone before returning them; the current adapter removes timezone information while preserving the stated clock time. It does not perform a timezone conversion for you. Filter the requested trading day's blotter in your source. Keep meaningful signed numbers; do not send formatted strings.

A genuinely empty day returns `pd.DataFrame(columns=list(NEW_POSITION_BLOTTER_COLUMNS))`. Source failures must raise. The manager has its own existing operational-error handling; an empty successful return conceals that distinction.

### 4.3 Do not double count existing positions

Return the current complete set of **supplemental positions for the requested day**, not just the newest rows since the previous button press. Each refresh replaces this overlay. Handle cancellations/amendments in your source so only the effective records remain.

Once a trade is included in the aged base Risk snapshot, it must stop being included in the New Trades overlay according to your source's cutoff/booking rule. The app does not deduplicate trades against base Risk: base Risk does not contain Trade ID. This cutoff is source logic, not a missing UI checkbox. The overlay does not write trades into your source system or automatically promote them into base Risk. Your upstream risk process incorporates the position; a later `get_risk` call reads that result, and your blotter stops returning the already incorporated supplemental position.

### 4.4 Understand MARKET versus cashflows

```text
Your 17-column blotter
  -> adapter validates and adds PL
  -> MARKET Underlyings are added to normal quote requests
  -> known Traded Level, otherwise Open, becomes the P&L reference
  -> existing product formula uses Current minus that reference
  -> New Trades exposure and PL join combined_pl
  -> Portfolio/reporting rules -> Risk and P&L pages

CASHFLOW row
  -> validated Cash Flow amount becomes PL directly
  -> no Open/Current quote request
  -> same Portfolio/reporting release path
```

For a Credit Delta example, Risk 100, known Traded Level 101 and Current 103 gives PL 200 with multiplier 1. `Notional` is descriptive metadata and does not replace Risk in the formula. Gamma trades use the existing Taylor formula and derived Delta behaviour, not the linear example.

For a cashflow, `Cash Flow=-500` gives PL -500. The current cashflow schema has no Currency column or conversion stage: supply an amount already in the app's agreed P&L reporting unit. These are daily P&L cashflow entries, not a future payment schedule with due dates. Do not feed a full future cashflow ladder into this contract.

The current `cube/app/s06_routing.py` registers Risk, Data, Stock, P&L and Statics; there is no separate Cashflows page or second cashflow-page connector in this version. The cashflow instructions here cover the existing `CASHFLOW` rows in New Trades. A standalone payment-schedule page would be a separate feature.

## 5. C — Connect the Stock page

### 5.1 Replace its source, keep the comparison logic

Open `cube/adapters/s08_stock.py`.

1. Remove `_temp_stock_source`, which currently reads the packaged fixture archive.
2. Add:

```python
def _live_stock_source(stock_date: pd.Timestamp) -> pd.DataFrame:
    from your_company_connectors import GetStock

    frame = GetStock(stock_date)
    return frame.loc[:, list(STOCK_COLUMNS)].copy()
```

3. Replace `_TEMP_STOCK_ADAPTER = build_stock_adapter(stock=_temp_stock_source)` with:

```python
_STOCK_ADAPTER = build_stock_adapter(stock=_live_stock_source)
```

4. Replace the public `get_stock` function with:

```python
def get_stock(stock_date: object) -> pd.DataFrame:
    """Return validated production Stock for the requested date."""
    return _STOCK_ADAPTER.get_stock(stock_date)
```

5. Keep `build_stock_adapter`, `StockConnectorAdapter`, `validate_stock_frame`, and `GetStock = get_stock`.
6. Keep these existing lines in `app.py`; no further wiring is required:

```python
from cube.adapters.s08_stock import get_stock
```

```python
            stock_source=get_stock,
            stock_portfolio_source=get_portfolio_config,
            stock_history_source=SQLStockHistoryRepository(history_path),
```

Do not route real Stock through `load_stock_archive_leaf`: that function deliberately checks the packaged fixture marker. Keeping it unused is harmless and avoids removing code still used by fixture tests. The production archive reader is the separate history repository.

### 5.2 Return seven columns for each requested date

```text
CRDS, CPTY, Portfolio, Instrument, Currency, Quantity, Market Value
```

The first five are nonblank text. Preserve identifiers such as CRDS as strings so leading zeroes survive. Quantity and Market Value must be finite numbers. Use the agreed units consistently between dates; the current app does not fetch FX conversions for Stock.

Return one row per complete identity `(CRDS, CPTY, Portfolio, Instrument, Currency)`. Although the basic frame validator checks columns and values, the two-date comparison additionally rejects duplicate identities. If your feed is trade-level, aggregate only additive measures at that identity when appropriate; otherwise extend the identity deliberately instead of dropping rows.

The page calls your connector twice: once for **current** and once for **prior**. It computes `Stock` from current `Market Value`, and `dStock` from the two dated snapshots. Do not return today's numbers for both dates or precompute dStock in your seven-column return. Missing current/prior identities are handled by the existing comparison logic.

```text
GetStock(current date) + GetStock(prior date)
  -> validate both
  -> compare exact identities
  -> attach Portfolio metadata using selected current date
  -> Stock filters, hierarchy, detail and current-vs-prior differences
```

An empty result with the seven headers can represent a genuinely empty book universe for a date. A failed query should raise rather than pretending every position disappeared. Supplying a live Stock connector does not create past archive days; section 6.4 explains that separate step.

### 5.3 First check after restarting

Select two dates for which your source has real snapshots. Compare one CRDS/Portfolio with the source and verify Quantity, Stock and dStock. Confirm `Product` is XVA or Hedges and that Activity filters include your real labels. The Stock page's Base Review defaults to Activity 1–3 (including its existing aliases); use the intended filters when reconciling totals.

## 6. D — Connect P&L without replacing its calculations accidentally

### 6.1 Live P&L is already calculated from Risk and market data

There is no separate `GetPL` call feeding the live main P&L table. After sections 2–4 are connected:

```text
real Risk + real Open/Current + real New Trades/cashflows
  -> get_product_pl / build_new_trade_rows
  -> Cross Gamma exposure overlay
  -> Portfolio mapping + Reported Underlying + promotion
  -> manager commits combined_pl and dashboard_frame
  -> P&L page reads the committed PL snapshot
  -> Concerto mapping + saved adjustments -> display/send rows
```

Keep `RiskRefreshManager`, `get_product_pl`, the existing P&L callbacks, and the snapshot revision handling. Do not replace `combined_pl` with your Colossus return: those tables have different schemas and purposes.

After connecting the sources, restart the process and use Refresh Risk once to load the real base snapshot. Refresh PL then refreshes the requested market path and supplementary feeds according to the manager's existing rules; it is not a continuous subscription. Reconcile one position and one cashflow before comparing an entire Portfolio. Resolve the unit/missing-quote policies in section 2.6 if the totals disagree.

### 6.2 Supply the real Concerto mapping and keep adjustments separate

Replace the **contents** of `data/s08_concerto.csv` with your real mapping, or set `CONCERTO_MAPPING_PATH` to your mapping file before app startup. Keep columns:

```text
Risk Type,Risk Greek,ConcertoField
```

The mapping needs one unambiguous field per represented Risk Type/Greek pair, and ConcertoField names must be unique under the current validator. Include the pairs you intend to send, including `Cash Flow,New` where applicable. Do not invent source-system field names from the examples.

`PL_ADJUSTMENT_PATH` points to the existing saved-adjustment repository. Its key is market date + Portfolio + ConcertoField. Use a persistent writable location if adjustments must survive deployment replacement. Do not add a saved adjustment again inside a feed that already includes it; agree whether your source amount is before or after adjustments.

### 6.3 Connect official actual P&L through Colossus

In `cube/services/s05_sources.py`, replace the entire body of `get_colossus_pl` with:

```python
def get_colossus_pl(market_date: pd.Timestamp) -> pd.DataFrame:
    from your_company_connectors import GetColossusPL
    from cube.history import validate_colossus_frame

    selected_date = _normalized_date(market_date, parameter="market_date")
    frame = GetColossusPL(selected_date)
    return validate_colossus_frame(frame.loc[:, list(COLOSSUS_COLUMNS)].copy())
```

Return exactly:

```text
Portfolio, Underlying, Risk Type, Risk Greek, PL
```

Use nonblank text keys and a finite numeric PL in the agreed reporting currency/unit. There must be at least one row, unique on the first four columns. If the upstream feed is more granular, aggregate **additive actual PL** to those four keys using the source's correct date/status scope first. Do not sum multiple snapshots of the same official result together. Do not attach `Product`, tenors, ConcertoField or Market Date to this five-column return; the archive supplies its date and joins the appropriate authority separately.

`tools/s02_archive.py` already resolves this function by default. Alternatively its existing `COLOSSUS_LOADER=module:function` setting can name your compatible function directly; do not change both unless you intend to. **This source is consumed by the official archive workflow; merely replacing it does not populate the live P&L table or create historical files.**

### 6.4 Populate real history using the existing job

Set `PL_HISTORICAL_PATH` to the same persistent archive directory in the app and the archive job. Use a clean production directory; the packaged `data/histo` contains illustrative history and completed days are intentionally not overwritten.

The existing job is the right entry point for real Risk, market and Colossus. Apply the small job change below before using it with new cashflows and Stock:

```bash
python -m tools.s02_archive
```

Run it using the existing Jupyter Scheduler entry point after the source becomes OFFICIAL. No automatic schedule is created by editing a connector. A job can correctly return `skipped` while the source is Live or the snapshot has errors. Its eligible date is the natural current market day; forcing an old date is not a historical backfill mechanism.

**Two current gaps:** the manager's `RefreshSnapshot` has no `stock_frame`, so the unchanged job does not write Stock history. Also, a `CASHFLOW` overlay adds Source Type `new-position/cash-flow` to the dashboard, but the manager's `risk_dates` map contains only the base products. The archive validator requires exactly the Source Types present in its Risk frame, so it rejects that otherwise valid cashflow snapshot. This was reproduced with the checked-in sources.

The simplest repair is a small archive snapshot view: keep the existing Risk/market frames, supply the market date for cashflow's date (as the current domain calculation already does), and add Stock for that same day. This does not put Stock into every Risk refresh or weaken the archive validator.

To repair the metadata and include Stock in that same daily job:

1. In `tools/s02_archive.py`, add these imports alongside the existing imports:

```python
from types import SimpleNamespace

from cube.adapters.s08_stock import get_stock
from cube.domain.s03_calculations import market_date_for
from cube.history import archive_official_snapshot
```

2. Inside `run_scheduled_archive`, keep the existing lines that resolve `values`, `root`, `loader` and `manager`. Replace only:

```python
    return archive_from_manager(manager, loader, root, refresh=True)
```

with:

```python
    snapshot = manager.refresh(
        force_risk=True,
        force_pl=True,
        reason="scheduled_official_archive",
    )
    eligible = (
        snapshot.market_date == market_date_for(snapshot.system_date)
        and snapshot.market_status == "OFFICIAL"
        and not snapshot.errors
    )
    leaf = root / snapshot.market_date.date().isoformat()
    if not eligible or leaf.exists():
        # Let the existing writer return its precise skipped/already-done result.
        return archive_official_snapshot(snapshot, loader, root)

    archive_risk_dates = {
        source_type: (
            snapshot.market_date
            if source_type == "new-position/cash-flow"
            else snapshot.risk_dates[source_type]
        )
        for source_type in snapshot.dashboard_frame["Source Type"].unique()
    }
    archive_view = SimpleNamespace(
        revision=snapshot.revision,
        refreshed_at=snapshot.refreshed_at,
        system_date=snapshot.system_date,
        market_date=snapshot.market_date,
        market_status=snapshot.market_status,
        dashboard_frame=snapshot.dashboard_frame,
        market_frame=snapshot.market_frame,
        risk_dates=archive_risk_dates,
        errors=snapshot.errors,
        stock_date=snapshot.market_date,
        stock_frame=get_stock(snapshot.market_date),
    )
    return archive_official_snapshot(archive_view, loader, root)
```

3. Remove the now-unused `archive_from_manager` import from this module; keep `ArchiveResult` and `ColossusLoader`.
4. Test one eligible day in a separate empty archive directory. Verify the completed leaf contains Risk, market, Colossus, Stock and its `_SUCCESS` manifest. The writer validates everything and publishes the day atomically; do not hand-write the success marker.
5. Point the app at the same directory. Its existing `SQLPLHistoryRepository`, `SQLStockHistoryRepository` and Data archive repository read the completed leaves. Populate additional genuine days with a separately reviewed backfill process if needed; do not manufacture earlier history by reusing today's values.

This adds one Stock fetch to the scheduled daily job, not to every Refresh PL click. If a complete eligible day has already been saved without Stock, rerunning is intentionally a no-op; do not delete production archive leaves casually to force replacement. Test the combined writer before the first production day.

### 6.5 Only connect outbound Send buttons if you need delivery

The existing `send_sog_pl(frame)` and `send_portfolio_pl(frame)` in `cube/services/s05_sources.py` deliberately raise while the fixture boundary is active. Reading live P&L does not require enabling them. When delivery is required, replace each whole body with a call to your own sender; keep `app.py`'s existing `PLSendConfig` wiring.

The current UI passes these seven columns to both senders:

```text
Risk Type, Risk Greek, Portfolio, SignoffGroup, ConcertoField, PL, Adjustment
```

Your sender should return normally only when accepted, and raise if delivery fails. Return type is `None`; returning `False` is currently treated as successful completion. Test against your destination's test mode first.

For a sender that accepts the existing payload, the body is simply:

```python
def send_sog_pl(frame: pd.DataFrame) -> None:
    from your_company_connectors import SendSogPL

    SendSogPL(frame.copy())
```

Apply the same pattern to `send_portfolio_pl` with your Portfolio sender. Your own wrapper must raise on a negative acknowledgement if your SDK does not already do so.

The current seven-column payload **does not contain Market Date**, although the internal governed rows do. If the real destination requires a date, do not substitute the server's current clock, because the user may be viewing a different date. That is a small, separate send-contract change: pass the selected snapshot's date explicitly to both send paths and update their tests before enabling delivery. It is not needed for live display or history ingestion.

## 7. Verify the integration in this order

1. In a Python session, call each personal connector for a date you can reconcile. Print columns, row counts and a small sample; do not dump the whole dataset or credentials.
2. Call the corresponding public wrapper: `get_cross_gamma(date)`, `get_new_positions(date)`, `get_stock(date)`, and `get_colossus_pl(date)`. These must return validated canonical frames. Try an empty-but-successful day where allowed and a deliberate malformed row to confirm you see an error.
3. For each product use `get_product_risk`, `get_product_market_open` and `get_product_market_status` from `cube/domain/s03_calculations.py` against your returned frames. Check both Live and OFFICIAL routing, date selection, duplicate keys and tenor order.
4. Build a manager with `build_production_refresh_manager(stage_delays={})`, call `manager.refresh(force_risk=True, force_pl=True, reason="connector_check")`, and inspect the returned `errors`, revision, dates and selected rows. A successful connector call alone does not prove the complete application accepted the data. The manager can record operational source failures; check logs and snapshot status as well as whether a table exists.
5. Reconcile one ordinary position, a known-level new trade, an Open-fallback trade, a cashflow and a Cross Gamma contribution. Then compare whole-Portfolio totals. Check scalar, curve and surface products and quote units separately.
6. Restart the application so its existing function references are rebuilt. Check Risk, Quick Risk, Quick Market, Stock current/prior, live P&L and then archive-backed history. A dropdown or chart should read the committed result; it should not need another connector call on every selection.
7. Run the relevant existing regression tests from the repository root using your environment:

```bash
python -m pytest tests/s17_stock.py tests/s18_newpositions.py tests/s25_crossgamma.py tests/s26_newtrades.py tests/s29_archive.py -q
```

Some tests intentionally exercise fixture defaults. Once those defaults are replaced, adapt those specific fixture tests to inject their test frames rather than calling production services. Keep the pure schema/calculation tests and failure cases. Tests that assert FX Delta has a bulk hook also need to reflect your choice in section 2.4; do not delete the whole suite because its original registration was fixture-specific.

The guide's wrapper snippets and core flows were checked with isolated synthetic inputs, including ordinary PL, Cross Gamma, new trades, cashflow PL, the Stock date comparison, strict schemas, and a Stock-inclusive archive with cashflow metadata and a repeated-day no-op. That verifies compatibility with this code version, not your private APIs, authentication, upstream financial conventions or deployed data.

## 8. What to keep and what to remove

| Keep | Replace/remove in the relevant edited function |
|---|---|
| ProductSpec catalogue and financial formulas, pending separate agreed changes | Temporary source rows and CSV/fixture reads on the live path. |
| Existing adapters and validators | `_temp_cross_gamma`, `_temp_new_positions`, `_temp_stock_source`, and their default bindings as instructed. |
| Refresh manager, atomic snapshots and revision signals | FX Delta fixture bulk wiring if you have not replaced those bulk functions. |
| Stock two-date comparison and Portfolio mapping | Placeholder Portfolio mappings and real-source calls that ignore the supplied date. |
| Existing archive format and completed-day writer | The default job's final call only if adding Stock as in section 6.4. |
| Existing P&L calculation, history readers and adjustment repository | Fixture Colossus read; disabled sender bodies only when you deliberately connect delivery. |

Keep calls lazy: no fetch at module import and no permanent global DataFrame cache. Use your organisation's existing configured credentials/client; never put secrets into these files. Start with these function replacements, reconcile them, and add batching only where the real connector already supports it.

To roll back a failed integration, restore only the source functions/bindings you changed and restart. Keep already written real archive data and saved adjustments separate from fixture directories. Do not roll back by deleting production history.
