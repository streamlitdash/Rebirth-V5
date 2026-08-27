# Fix 16 — Cache reduced tenor once for fast switching

**Status:** Implemented on the `v3` branch.

This is the smallest functional fix for repeatedly switching between Full and
Reduced tenor. It changes only the Risk server cache. It adds no background
worker, callback, JavaScript, CSS, or cold-start work.

## What was slow

Previously the cache key contained every filter as well as the Reduced-tenor
flag:

```text
revision + Risk Type + IR family + Split + reporting filters
+ include/exclude + Full/Reduced + promotion generation
```

The first exact key was cached, but a new Category, Activity, Signoff Group,
Subcategory, Split, or include/exclude selection could run the complete tenor
reduction again. A filtered result larger than 96 MiB was not cached at all.

## New flow

```text
Committed prepared book
  -> select the active Risk Type
  -> lazily build its reduced book once
  -> choose Full or Reduced book
  -> apply IR family, Split, and reporting filters
  -> apply the selected promotion generation
  -> render the table
```

The reduced books are owned by `_RiskDataCache` and keyed only by:

```python
(revision, active_risk_type)
```

Keeping the Risk Type in this key avoids reducing irrelevant products and
preserves the Credit rule: a Credit-only request does not open the non-Credit
`s11_matrix.csv` catalogue.

The first Reduced click after a refresh or Clear Cache still performs one real
calculation. Later Full/Reduced switches and later filters reuse it. A new data
revision correctly builds a new book.

## Files changed

```text
cube/pages/risk/s02_state.py
tests/s19_riskfilters.py
README.md
experiments/fix16.md
```

No connector, financial P&L, matrix, callback, layout, asset, or deployment
file changes are required.

## Manual implementation

### 1. Increase the small exact-filter cache

In `cube/pages/risk/s02_state.py`, change:

```python
_FILTER_CACHE_MAX_BYTES = 96 * 1024 * 1024
```

to:

```python
_FILTER_CACHE_MAX_BYTES = 512 * 1024 * 1024
```

The canonical full and reduced books are separate from this bounded cache.
The larger limit simply makes the most recent exact Full/Reduced filtered
views more likely to remain available on the 20 GB host. It is a maximum, not
a preallocation; the existing 32-entry limit remains.

### 2. Add the revision-owned reduced books

In `_RiskDataCache.__init__`, immediately after `_tenor_reducer`, add:

```python
self._reduced_frames: dict[tuple[int, str | None], pd.DataFrame] = {}
```

In both `replace_frame()` and `clear_reconstructable()`, add this beside the
other cache resets:

```python
self._reduced_frames.clear()
```

### 3. Add `_reduced_for_scope()`

Place this method immediately after `_reduce_filtered()`:

```python
def _reduced_for_scope(
    self,
    frame: pd.DataFrame,
    manager: RefreshManagerProtocol | None,
    *,
    revision: int,
    active_risk_type: str | None,
) -> pd.DataFrame | None:
    key = (revision, active_risk_type)
    with self._lock:
        cached = self._reduced_frames.get(key)
        if cached is not None:
            return cached

    scoped = (
        frame
        if active_risk_type is None
        else frame.loc[frame["risk type"].eq(active_risk_type)]
    )
    reduced = self._reduce_filtered(
        scoped,
        manager,
        revision=revision,
        fallback=frame,
    )
    if reduced is None:
        return None

    with self._lock:
        if self._revision != revision:
            return None
        existing = self._reduced_frames.get(key)
        if existing is not None:
            return existing
        self._reduced_frames[key] = reduced
        return reduced
```

The existing `_filter_compute_lock` already makes this single-flight, so no
new lock or executor is necessary. Reduction and manager reads happen without
holding `_lock`; the final revision check prevents stale publication.

### 4. Choose the book before filtering

In `_RiskDataCache.filtered()`, replace the old filter-then-reduce section with:

```python
selected_book = frame
if reduced_tenor:
    selected_book = self._reduced_for_scope(
        frame,
        manager,
        revision=revision,
        active_risk_type=active_risk_type,
    )
    if selected_book is None:
        continue

filtered = apply_filters(
    filter_ir_family(selected_book, active_risk_type, ir_family),
    [active_risk_type] if active_risk_type else [],
    list(splits or ()),
    dimension_filters,
    exclude_selected=exclude_selected,
)
filtered = apply_promotion_generation(
    filtered,
    parsed_generation,
    revision=revision,
)
```

Delete the old `if reduced_tenor:` block that called `_reduce_filtered()`
after those filters.

Promotion remains after filtering because a current-view promotion belongs to
one session and filter basis; it must not be baked into the shared reduced
book. Baseline promotion fields remain ordinary committed row metadata.

## Why filtering afterward is valid

Current visible filters operate on position fields retained by the reducer:
Risk Type, Risk Greek/IR family, Split, Activity, Signoff Group, Category, and
Subcategory. Portfolio remains an internal grouping boundary even though Risk
does not expose it as a filter. Raw and Reported Underlying are also retained.
Reduction therefore cannot combine rows across those boundaries.

Tenor definitions are expected to cover every real tenor in their configured
source. If a definition is incomplete, the existing safe behavior retains the
whole affected source/Underlying batch at full tenor. With the shared reduced
book, that decision remains consistent when filters change instead of a filter
temporarily hiding the uncovered tenor.

Do not reuse this optimization for a future filter based on tenor, a market
value/availability field, promotion bucket, or a numeric metric without first
rechecking the aggregation semantics.

## Tests

`tests/s19_riskfilters.py` verifies that:

- Full mode performs no matrix/catalogue work;
- two different reporting filters cause only one reducer execution;
- reducing once before filtering matches the former filter-first result for
  both mapped and unmapped rows;
- Full and Reduced output remains reversible and financially correct;
- market quotes are read once per cache/revision lifetime, reused across Risk
  Types and filters, and reread after Clear Cache or a new revision;
- Clear Cache forces exactly one new reduced build;
- a new revision forces exactly one new reduced build;
- current-view promotion is applied after filtering and is not baked into the
  shared reduced book;
- Credit remains reducible without opening the non-Credit catalogue even when
  the committed frame also contains IR rows.

Run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests\s19_riskfilters.py tests\s43_reducedtenor.py tests\s44_tenorreductionsource.py -q
& '.\.venv\Scripts\python.exe' -m pytest -q
& '.\.venv\Scripts\python.exe' -m ruff check .
& '.\.venv\Scripts\python.exe' -m ruff format --check .
git diff --check
```

## Expected behavior and troubleshooting

- Full mode and cold start do no reduced-tenor work.
- The first Reduced click for a Risk Type can still take one calculation.
- Repeated Full/Reduced switching with the same committed revision reuses the
  reduced DataFrame and the existing exact rendered-table cache.
- Changing a reporting filter no longer runs tenor reduction again.
- A refresh or Clear Cache deliberately invalidates the reduced book.
- If the server cache hits but the browser still pauses, the remaining cost is
  Dash serializing and replacing the visible HTML hierarchy. That is a separate
  virtualization/client-rendering change and is not hidden inside this patch.

## Rollback

Revert the four runtime edits in `cube/pages/risk/s02_state.py`: restore the
96 MiB limit, remove `_reduced_frames`, remove its two resets and helper, and
restore filter-then-reduce inside `filtered()`. No data or CSV rollback is
required.
