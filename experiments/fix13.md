# Fix 13 — Sum market splits before averaging tenors, and diagnose Risk lag

**Status:** Proposed experiment. This document does not change the application
source code.

## Required result

The Risk Explorer market columns must use this order of calculation:

```text
remove duplicate Portfolio / XVA / Hedges copies
    -> sum Risk, Gamma, and other Split contributions at one exact market cell
    -> average Tenor Option cells inside each Tenor Swap
    -> average Tenor Swap levels inside each raw Underlying
    -> average raw Underlyings at the displayed parent
```

This document assumes the existing custom logic already sets the Gamma market
contribution to zero. Do **not** add another Gamma-zeroing function here.

Example:

```text
1Y: Risk Move 2 + Gamma Move 0 = tenor Move 2
2Y: Risk Move 6 + Gamma Move 0 = tenor Move 6

Underlying Move = average(2, 6) = 4
```

For a scalar product such as FX Delta, `Spot` and `N/A` are not real tenors.
They represent one scalar market cell:

```text
FX Delta Move = Risk Move + Gamma Move
              = Risk Move + 0
```

Never sum the raw position rows. The same market quote is repeated for multiple
Portfolios and sometimes for XVA/Hedges, so summing raw rows would weight the
quote by the number of books.

## Where the calculation belongs

Put the calculation in:

```text
cube/ui/s02_aggregation.py
```

There is also one scalar-label correction in:

```text
cube/domain/s03_calculations.py::_with_dashboard_tenors
```

The two implementations that must agree are:

```text
hierarchical_market_value()  # slower reference/fallback path
_MarketQuoteIndex.value()    # fast path used by the normal Risk Explorer
```

Do not put the arithmetic in `should_show_sum()`. That function only decides
whether a market cell is visible.

No edit is needed in `cube/pages/risk/s06_explorertables.py` for this formula.
It already passes each scoped hierarchy frame to the aggregation layer.

## Part 1 — Give both scalar FX sources the same non-tenor label

### 1. Make FX Gamma use `Spot`, just like FX Delta

In `cube/domain/s03_calculations.py`, inside `_with_dashboard_tenors()`, find:

```python
result[TENOR_SWAP] = "Spot" if spec.key == "fxdelta" else "N/A"
```

Replace it with:

```python
result[TENOR_SWAP] = "Spot" if spec.key in {"fxdelta", "fxgamma"} else "N/A"
```

Both products are scalar. This makes the FX Delta Risk row and the FX Gamma
derived `Split="Gamma"` row share one scalar cell. Without this one-line change,
the reducer treats `Spot` and `N/A` as two cells and can halve the displayed FX
Delta value even when Gamma is zero.

Tenor Option is already `N/A` for both, so do not change it.

## Part 2 — Change the reference market reducer

### 2. Replace `hierarchical_market_value()`

Replace the current function with:

```python
def hierarchical_market_value(frame: pd.DataFrame, column: str) -> float:
    """Sum split contributions at a quote cell, then average tenor levels."""
    if column not in {"open", "current", "move"}:
        raise ValueError(f"Unsupported market column: {column}")
    if frame.empty:
        return float("nan")

    identity = [
        "risk type",
        "risk greek",
        "source type",
        "underlying",
        "tenor swap",
        "tenor option",
        "split",
    ]
    quotes = (
        frame[[*identity, column]]
        .dropna(subset=[column])
        .drop_duplicates()
    )
    if quotes.empty:
        return float("nan")

    option_totals = quotes.groupby(
        ["underlying", "tenor swap", "tenor option"],
        dropna=False,
    )[column].sum(min_count=1)
    swap_averages = option_totals.groupby(
        level=["underlying", "tenor swap"],
        dropna=False,
    ).mean()
    underlying_averages = swap_averages.groupby(
        level="underlying",
        dropna=False,
    ).mean()
    return float(underlying_averages.mean())
```

Why each step exists:

```text
source type + split in the identity
    -> Risk and Gamma remain separate contributions

drop_duplicates()
    -> repeated Portfolio/XVA/Hedges copies count once

first sum()
    -> combine Split contributions at the exact market cell

later mean() calls
    -> average option tenors, swap tenors, and raw Underlyings
```

## Part 3 — Change the fast Risk Explorer reducer

Changing only `hierarchical_market_value()` is not enough. The normal Explorer
uses `_MarketQuoteIndex`, so both paths must be edited.

### 3. Expand the quote identity

Find `_MARKET_QUOTE_IDENTITY` and replace it with:

```python
_MARKET_QUOTE_IDENTITY = (
    "risk type",
    "risk greek",
    "source type",
    "underlying",
    "tenor swap",
    "tenor option",
    "split",
)
```

### 4. Add a grouped-sum helper

Keep `_means_by_group()` unchanged. Immediately below it, add:

```python
@staticmethod
def _sums_by_group(
    values: np.ndarray,
    group_codes: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    groups, inverse = np.unique(group_codes, return_inverse=True)
    totals = np.bincount(inverse, weights=values)
    return groups, totals
```

### 5. Sum only the first level

In `_MarketQuoteIndex.value()`, replace:

```python
option_codes, option_means = self._means_by_group(
    self._quote_values[quote_codes],
    self._quote_to_option[quote_codes],
)
swap_codes, swap_means = self._means_by_group(
    option_means,
    self._option_to_swap[option_codes],
)
```

with:

```python
option_codes, option_totals = self._sums_by_group(
    self._quote_values[quote_codes],
    self._quote_to_option[quote_codes],
)
swap_codes, swap_means = self._means_by_group(
    option_totals,
    self._option_to_swap[option_codes],
)
```

Leave the remaining swap-to-underlying mean and final underlying mean exactly as
they are.

The result is:

```text
exact option cell: sum Splits
swap row:          average its option cells
underlying row:    average its swap levels
reported parent:   average its raw Underlyings
```

The same rule is automatically applied to Open, Current, and Move because
`HierarchyAggregationIndex` already loops over `_MARKET_COLUMNS`. This keeps the
displayed relationship `Move = Current - Open` coherent, assuming the Gamma
Open, Current, and Move contributions are all zero as stated.

### 6. Show the reported parent value, if required

The default Explorer is Reported Underlying mode. The current visibility rule
can leave a Reported Underlying market cell blank even though the reducer can
calculate its equal-weight raw-underlying average.

If the phrase “top level of Underlying” includes the Reported Underlying row,
replace `_is_semantic_underlying()` with:

```python
def _is_semantic_underlying(context: dict[str, str]) -> bool:
    """Show market values at a displayed identity or its descendants."""
    promoted_underlying = context.get("display bucket") not in {None, "Other"}
    return (
        promoted_underlying
        or "reported underlying" in context
        or "underlying" in context
        or any(
            column in context
            for column in (
                "tenor swap",
                "tenor option",
                "split",
                *VIEW_DIMENSIONS,
            )
        )
    )
```

This makes a reported parent display the equal-weight average of its raw
Underlyings. The Display Bucket condition lets a promoted Underlying row show
the same value when duplicate hierarchy labels are skipped.

If the top market value is only required in Raw Underlying mode, skip this one
visibility edit.

## Part 4 — Add one regression test

In `tests/s19_riskfilters.py`, add these imports from
`cube.ui.s02_aggregation`:

```python
HierarchyAggregationIndex,
aggregate_values,
```

Then add a test with this shape:

```python
def test_market_sums_splits_before_averaging_tenors() -> None:
    def row(
        *,
        source_type: str,
        underlying: str,
        tenor: str,
        split: str,
        portfolio: str,
        open_value: float,
        current_value: float,
    ) -> dict[str, object]:
        return {
            "risk type": "IR",
            "risk greek": "Delta",
            "source type": source_type,
            "underlying": underlying,
            "tenor swap": tenor,
            "tenor option": "N/A",
            "split": split,
            "portfolio": portfolio,
            "risk": 0.0,
            "risk expo": 0.0,
            "risk hedges": 0.0,
            "drisk": 0.0,
            "drisk expo": 0.0,
            "drisk hedges": 0.0,
            "pl": 0.0,
            "pl expo": 0.0,
            "pl hedges": 0.0,
            "open": open_value,
            "current": current_value,
            "move": current_value - open_value,
        }

    rows = []
    cells = {
        ("U1", "1Y"): (100.0, 102.0),
        ("U1", "2Y"): (200.0, 206.0),
        ("U2", "1Y"): (50.0, 51.0),
        ("U2", "2Y"): (70.0, 73.0),
    }
    for (underlying, tenor), (open_value, current_value) in cells.items():
        for portfolio in ("BOOK-A", "BOOK-B"):
            rows.append(
                row(
                    source_type="ir/delta",
                    underlying=underlying,
                    tenor=tenor,
                    split="Risk",
                    portfolio=portfolio,
                    open_value=open_value,
                    current_value=current_value,
                )
            )
            rows.append(
                row(
                    source_type="ir/gamma",
                    underlying=underlying,
                    tenor=tenor,
                    split="Gamma",
                    portfolio=portfolio,
                    open_value=0.0,
                    current_value=0.0,
                )
            )

    frame = pd.DataFrame(rows)
    fallback = aggregate_values(frame)
    index = HierarchyAggregationIndex(frame)
    fast = index.aggregate(index.frame)

    # U1 mean Move = (2 + 6) / 2 = 4.
    # U2 mean Move = (1 + 3) / 2 = 2.
    # Top mean Move = (4 + 2) / 2 = 3.
    assert fallback["move"] == pytest.approx(3.0)
    assert fast["move"] == pytest.approx(3.0)
    assert fast["open"] == pytest.approx(105.0)
    assert fast["current"] == pytest.approx(108.0)
```

Add a second small assertion using FX rows after `_with_dashboard_tenors()` has
assigned `Spot` to both FX Delta and FX Gamma. Its expected Move must be
`Risk + 0`, not half of Risk. This protects the one-line scalar correction in
step 1.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\s19_riskfilters.py -q
```

## Part 5 — Optional: make clicked market detail use the same rule

The steps above fix the main Risk Explorer hierarchy table. Clicked tenor
detail uses separate reductions in:

```text
cube/ui/s02_aggregation.py::detail_frame
cube/pages/risk/s05_charts.py::build_line_chart
cube/pages/risk/s05_charts.py::_tenor_surface_pivot
```

Those paths currently average market rows. Therefore, after the main table is
fixed, a clicked pre-Split market chart can still show the old value.

The smallest safe detail change is in `detail_frame()`:

1. Set `market_metric = metric in {"move", "open", "current"}`.
2. For a market metric, omit `source type` from `identity_keys`, leaving raw
   `underlying` as the market-series identity.
3. Keep `source type` and add `split` in `quote_identity` so distinct source and
   Split contributions survive deduplication.
4. For a market metric, group the deduplicated quote rows by `group_keys` and
   use `.sum(min_count=1)` for Open, Current, and Move.
5. For Risk, dRisk, and P&L detail, retain the existing source-aware behavior.

The essential shape is:

```python
market_metric = metric in {"move", "open", "current"}
identity_keys = [
    *(
        []
        if market_metric or "source type" not in scoped
        else ["source type"]
    ),
    "underlying",
]
group_keys = [
    *identity_keys,
    "tenor swap",
    "tenor swap order",
    "tenor option",
    "tenor option order",
]
quote_identity = ["risk type", "risk greek", "split", *group_keys]
if "source type" in scoped and "source type" not in quote_identity:
    quote_identity.insert(2, "source type")

deduplicated_quotes = scoped.drop_duplicates(
    quote_identity + ["open", "current", "move"]
)
if market_metric:
    quotes = (
        deduplicated_quotes.groupby(group_keys, as_index=False)[
            ["open", "current", "move"]
        ]
        .sum(min_count=1)
    )
else:
    quotes = deduplicated_quotes.groupby(group_keys, as_index=False).agg(
        open=("open", "mean"),
        current=("current", "mean"),
        move=("move", "mean"),
    )
```

After this, the existing chart functions can continue averaging exact cells
over option tenors, swap tenors, and raw Underlyings. Do not blindly replace
every chart mean with a sum.

If only the hierarchy table is required now, leave this optional part for a
second commit. It is deliberately separated to keep the first manual edit
small.

## Part 6 — Chevron and filter lag: what is actually known

Compression is **not proven** to be the cause of the lag.

Current behavior:

```text
Chevron click
    -> filtered DataFrame is normally reused from cache
    -> every new open-row combination misses the exact component cache
    -> Python rebuilds the full visible hierarchy
    -> Dash returns the full table
    -> the browser replaces and lays out the full table
```

Applying a filter is different:

```text
edit draft dropdown       -> no heavy Risk Explorer rebuild
click Apply               -> publish committed filters
                          -> rebuild Risk Explorer
                          -> also rebuild Aggregate P&L
```

The filter operation itself was fast on the checked fixture. The delay comes
from the downstream component builds. Risk Explorer and Aggregate P&L also use
the same serialized render lock to respect the one-core/memory constraint, so
one build can wait for the other.

The checked fixture measured approximately:

| View | Python build | Uncompressed component JSON | Gzip size |
|---|---:|---:|---:|
| Cross | 0.12 s | 143 KB | 5.3 KB |
| SplitVA | 0.14 s | 767 KB | 26.7 KB |

Real data can be much larger. These figures show that compression may help the
transfer, especially for SplitVA, but it cannot reduce Python aggregation,
render-lock waiting, JSON parsing, React reconciliation, or browser layout.

### 7. Identify the slow phase before changing compression

In the browser:

1. Open Developer Tools.
2. Open **Network**.
3. Click one chevron.
4. Select the `_dash-update-component` request.
5. Inspect **Timing** and **Response Headers**.

Interpret it as follows:

| Observation | Likely cost |
|---|---|
| High Waiting / TTFB | Server hierarchy build or waiting for the render lock |
| High Content Download and no `gzip`/`br` | Compression can help |
| Request finishes quickly but UI remains frozen | Full-table browser replacement/layout |

### 8. Make the chevron react immediately

This improves perceived responsiveness without changing financial data or
server authority.

In `assets/s13_risk.js`, replace the existing block:

```javascript
if (riskAction && !(selectionHeader && hasAggregationModifier(event))) {
  event.preventDefault();
  if (publishRiskAction(riskAction)) return;
}
```

with:

```javascript
if (riskAction && !(selectionHeader && hasAggregationModifier(event))) {
  event.preventDefault();

  const isRow = riskAction.classList.contains("row-toggle");
  const willExpand =
    isRow && riskAction.getAttribute("aria-expanded") !== "true";

  if (publishRiskAction(riskAction)) {
    if (isRow) {
      riskAction.textContent = willExpand ? "\u2212" : "\u25b8";
      riskAction.setAttribute("aria-expanded", String(willExpand));
      riskAction.closest("tr")?.setAttribute(
        "aria-expanded",
        String(willExpand),
      );
    }
    return;
  }
}
```

The children still arrive from the server. This only stops the button from
looking frozen while the request runs.

### 9. Stop hidden Aggregate P&L from competing after Apply

This is the smallest meaningful filter-path experiment when the user mainly
works in Risk Explorer.

First, in `cube/pages/risk/s16_view.py`, find the `html.Details` whose id is
`ag-pl-details` and change:

```python
open=True,
```

to:

```python
open=False,
```

Second, in `cube/pages/risk/s14_workspacecallbacks.py`, add this callback Input:

```python
Input("ag-pl-details", "open"),
```

Add the matching `aggregate_panel_open` argument to
`reduce_and_render_aggregate_pl()`, in the same position as that Input. Near the
top of the function, add:

```python
if not aggregate_panel_open:
    raise PreventUpdate
```

When Aggregate P&L is closed, applying filters no longer builds its all-risk
table and the Risk Explorer build does not queue behind or in front of it. When
the user opens Aggregate P&L, the `open` Input triggers a fresh render using the
latest committed filters.

This is a plausible scaling/concurrency fix for large real data, not proof that
Aggregate P&L is the only cause.

### 10. Enable compression only when the header check says it is missing

If the Dash response does not already contain `Content-Encoding: gzip` or
`Content-Encoding: br`, change `requirements.txt` from:

```text
dash==4.4.0
```

to:

```text
dash[compress]==4.4.0
```

Then, in `cube/app/s07_factory.py`, immediately before `app = Dash(...)`, add:

```python
dash_options.setdefault("compress", True)
```

Do not expect this to fix high server Waiting/TTFB or a browser freeze after the
response has arrived. It only reduces response-transfer bytes.

## Do not make these changes

Do not:

- remove `_render_compute_lock`; it is the protection that keeps concurrent
  hierarchy builds from consuming multiple cores and duplicate memory;
- disable the filtered-frame cache;
- pre-render every closed descendant row in the browser, because that increases
  cold-start payload and memory;
- replace every market mean with a sum;
- sum raw Portfolio rows;
- add another Gamma-zeroing function in this experiment.

## Final checks

1. A Risk Move of 2 plus a Gamma Move of 0 displays 2 at the exact tenor.
2. Two tenor totals 2 and 6 display 4 at their Underlying parent.
3. Duplicate Portfolio rows do not change Open, Current, or Move.
4. FX Delta and FX Gamma both use scalar label `Spot`; Risk plus Gamma zero
   displays Risk, not half Risk.
5. Fast and fallback reducers return the same results.
6. Changing only a draft filter does not rebuild Risk Explorer.
7. Applying a filter rebuilds Risk Explorer once.
8. Closed Aggregate P&L does not rebuild on Apply; opening it uses the latest
   filters.
9. A chevron glyph changes immediately, then the correct child rows arrive.
10. Compression is enabled only if the deployment was not already compressing.

## Rollback

Revert only the edits described above. This Markdown file is documentation and
does not alter runtime behavior.
