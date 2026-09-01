# Fix 21 — Make promoted-underlying sorting follow Risk, dRisk, or P&L

This is an implementation guide for the confirmed Risk Explorer ordering
defect. Adding this document does not change runtime behavior.

## What this fixes

The **Sort selected identity by** control offers:

```text
Risk
dRisk
P&L
```

P&L is the configured default. The intended identity order is descending by
the absolute value of the selected aggregated metric:

```text
abs(sum(Risk))
abs(sum(dRisk))
abs(sum(P&L))
```

The aggregation is signed first and made absolute afterward. It is not
`sum(abs(position value))`.

The metric sorter itself already implements this correctly. The problem is
that promoted identities do not reach it.

## Confirmed current behavior

The selector is correctly passed through the Risk callback, generation state,
render key, and table builder. The defect is inside:

```text
cube/ui/s02_aggregation.py::ordered_unique
```

Promotion is enabled by default. A promoted Reported Underlying is displayed
as a `display bucket` row immediately below its Risk Greek. The existing
`display bucket` branch ignores `underlying_sort_metric` and always uses:

```text
maximum Promotion Score descending
Other last
```

The hierarchy subsequently skips the duplicate Reported Underlying level on a
promoted branch. In the default Reported identity mode, the raw Underlying
level is also removed. The visible row therefore looks like an underlying but
is actually a Display Bucket, so changing Risk/dRisk/P&L cannot affect it.

The resulting default hierarchy is effectively:

```text
Risk Greek
    promoted Display Buckets by Promotion Score
    Other
        Region
            Group
                Reported Underlying by the selected absolute metric
```

Inside `Other`, identity ordering is local to each Region/Group. It is not a
global order across the whole Greek.

## Reproduction evidence

One checked-in fixture scope produced:

```text
Rendered promoted order:  G10 Rates, GBP SONIA
Promotion Score:           27.44, 12.24
Absolute P&L:              5,368, 19,743
Correct P&L order:         GBP SONIA, G10 Rates
```

Selecting Risk, dRisk, or P&L did not change those Display Bucket rows. With
Promotion disabled, the selected metric order worked across the tested Risk
Types and identity modes.

Credit SP01, PSP01, PM01, PM01P, Theta, and JTD use the same hierarchy and can
all exhibit the same promoted-bucket issue. In Credit Single view, Risk/dRisk
sorting uses the currently selected Credit measure because that measure is
applied before the table is built.

## Smallest implementation

Change one branch in:

```text
cube/ui/s02_aggregation.py
```

Function:

```python
ordered_unique(...)
```

Replace the current `display bucket` branch:

```python
if column == "display bucket":
    promoted = (
        frame.loc[frame[column].ne("Other")]
        .groupby(column)["promotion score"]
        .max()
        .sort_values(ascending=False, kind="stable")
    )
    values = promoted.index.astype(str).tolist()
    if frame[column].eq("Other").any():
        values.append("Other")
    return values
```

with:

```python
if column == "display bucket":
    promoted_frame = frame.loc[frame[column].ne("Other")]

    if underlying_sort_metric is not None:
        metric = selected_underlying_sort_metric(underlying_sort_metric)
        values = _ordered_by_metric(
            promoted_frame,
            column,
            metric,
        )
    else:
        # Retain Promotion Score ordering for callers that do not supply the
        # Risk Explorer's identity-sort selection.
        promoted = (
            promoted_frame.groupby(column)["promotion score"]
            .max()
            .sort_values(ascending=False, kind="stable")
        )
        values = promoted.index.astype(str).tolist()

    if frame[column].eq("Other").any():
        values.append("Other")

    return values
```

## Expected behavior after the change

When the Risk Explorer supplies a selected metric:

```text
Risk selected   -> promoted buckets by abs(sum(Risk))
dRisk selected  -> promoted buckets by abs(sum(dRisk))
P&L selected    -> promoted buckets by abs(sum(P&L))
Other           -> always last
```

When another caller invokes `ordered_unique` without an
`underlying_sort_metric`, the existing Promotion Score order remains
available as the fallback.

The existing `_ordered_by_metric` helper supplies a deterministic
case-insensitive label tie-break after metric magnitude.

## Why this is the safest change

This is presentation-only. Do not change any of the following:

```text
promotion thresholds
Promotion Score
Promotion Reason
Display Bucket classification
Risk/dRisk/P&L values
Credit-measure conversion
promotion generation UUIDs
callback inputs or outputs
render-cache keys
Reported Underlying mapping
```

The patch changes only sibling ordering inside an already-built hierarchy.
It neither promotes nor demotes an identity.

## Regression test

Add the focused pure-function test to:

```text
tests/s06_ui.py
```

Use promotion scores deliberately opposed to the financial metrics so the
test cannot pass accidentally:

```python
@pytest.mark.parametrize(
    ("metric", "expected"),
    [
        ("risk", ["B", "A", "Other"]),
        ("drisk", ["A", "B", "Other"]),
        ("pl", ["B", "A", "Other"]),
    ],
)
def test_promoted_display_buckets_follow_selected_metric(
    metric: str,
    expected: list[str],
) -> None:
    frame = pd.DataFrame(
        {
            "display bucket": ["A", "B", "Other"],
            "promotion score": [9.0, 1.0, 0.0],
            "risk": [10.0, 50.0, 1_000.0],
            "drisk": [80.0, 20.0, 1_000.0],
            "pl": [5.0, -100.0, 1_000.0],
        }
    )

    assert ordered_unique(
        frame,
        "display bucket",
        underlying_sort_metric=metric,
    ) == expected
```

Also retain or add a fallback assertion:

```python
assert ordered_unique(frame, "display bucket") == ["A", "B", "Other"]
```

That proves callers without a selected metric still receive Promotion Score
ordering.

## Verification

From the repository root, run:

```powershell
& '.\.venv\Scripts\python.exe' -m pytest tests/s06_ui.py tests/s19_riskfilters.py -q
& '.\.venv\Scripts\python.exe' -m pytest -q
git diff --check
```

Then perform this browser check:

1. Open Risk Explorer with Promotion enabled.
2. Expand a Greek containing at least two promoted identities.
3. Record the promoted order under P&L.
4. Select Risk and confirm the order follows descending absolute Risk.
5. Select dRisk and confirm the order follows descending absolute dRisk.
6. Return to P&L and confirm descending absolute P&L.
7. Confirm `Other` remains last.
8. Repeat on Credit after selecting one non-default Credit measure.

## Important limitations

This fix does not globally sort identities inside `Other`. Region and Group
remain higher hierarchy levels, and underlyings are sorted only among siblings
inside the same parent. Global ordering would require a separate product
decision and hierarchy reordering.

Credit Multi shows several measures simultaneously. Its Risk/dRisk hierarchy
sort still uses the generic Risk/dRisk columns rather than one visible measure
column. P&L is common across those columns. Choosing a specific Credit Multi
measure as the hierarchy-sort authority is a separate decision.

Pinned identities are not guaranteed to be first by this change. If pinned
rows require an absolute priority over the selected financial metric, add an
explicit pinned rank rather than changing or fabricating their financial
values.

## Rollback

Rollback is confined to `ordered_unique`: restore the original Promotion
Score-only `display bucket` branch. No data migration, cache migration, or
connector rollback is required. Restart the server after replacing the Python
file so the running process imports the restored function.

## Final checklist

```text
[ ] Only cube/ui/s02_aggregation.py runtime behavior changed
[ ] Promoted buckets honor Risk
[ ] Promoted buckets honor dRisk
[ ] Promoted buckets honor P&L
[ ] Default P&L uses abs(sum(P&L)) descending
[ ] Other remains last
[ ] Promotion Score fallback remains for callers without a selector
[ ] Promotion classification and thresholds are unchanged
[ ] Focused tests pass
[ ] Full test suite passes
[ ] Browser check covers Promotion and a Credit measure
```
