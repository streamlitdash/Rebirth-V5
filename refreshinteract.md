# Keep the app interactive while a refresh and its hero are running

Apply this after your implemented `Hero.md`. The hero should remain visible until its work finishes **and you should still be able to navigate, change filters, select an underlying and use Quick Risk/Quick Market while it runs**. Those views use the last committed snapshot until a new one is available.

This guide repairs the interaction path. It does not remove the full-completion checks from `Hero.md`. It also supersedes that guide's instruction to preserve the old revision publisher if you already installed the earlier interaction fix.

## 1. What went wrong, and what is confirmed

The inspected code already supports reading the last good data while a refresh calculates. `RiskRefreshManager` has a writer lock and a separate short-held state lock. The intended design was not to freeze the app.

There is a concrete callback dependency that can freeze the Risk view: `update_dimension_filters` listens to `clear-cache-complete-store.data`, and the long `refresh_pipeline` callback declares that exact property as an Output. Dash can therefore hold the filter callback and its dependent Risk/Quick Risk views until refresh returns, **even when an ordinary refresh eventually returns `no_update` for Clear Cache**. The earlier interaction guide corrected this, so check that this one-line fix survived your later edits.

The published Hero guide also says to keep `renderedDataRevisionFloor()`, while the earlier interaction guide replaced the old revision publisher. That was an instruction mismatch. Reinstating the entire old publisher to recover that one function is unnecessary. The optional replacement in step 4 supplies the small compatibility function and keeps the independent publisher.

The inspected hero is an inline panel. Its global loader already has `pointer-events: none`; I did not find a baseline full-screen interaction lock. The published Hero guide does not instruct you to add one. Your running, locally edited application has not been inspected, so an added overlay, disabled controls or an overbroad busy guard must be checked rather than assumed. Waiting for completion should control the hero's message, not whether normal browsing is permitted.

## 2. Save a small backup, and keep these parts

Stop the app with your normal process/notebook control. Save the files you change outside the `assets` folder; a backup JavaScript file left inside `assets` can run alongside the real file.

| Keep | Reason |
|---|---|
| Atomic commit and last-good snapshot in `cube/services/s06_refresh.py` | Readers see a complete dataset, including after a failed refresh. |
| The server's single-writer guard and existing refresh-action controls | A second financial refresh must not overlap the first. |
| Hero attempt identity, remount preservation, backend/callback checks and required-view acknowledgements | Keeping the app interactive must not reintroduce premature completion or disappearance. |
| The warm-shell guard in `hydrate_shared_refresh_shell` | A refresh must not remount the whole page and lose selection. |
| Existing data/financial validation, stale-request checks and reset generations | This fix changes notifications, not data authority. |

Do not add another manager, financial cache, job queue, server process or copy of the dataset. `jtd.md` also changes `cube/pages/risk/s07_explorer.py`, in its selection/render section. Keep those changes; step 3 below changes only the separate dimension-filter Input. Keep the JTD row-click changes in `assets/s13_risk.js` too.

## 3. Make the smallest confirmed fix first

1. Open `cube/pages/risk/s07_explorer.py`.
2. Find `def update_dimension_filters(` and its decorator immediately above it.
3. Replace only this Input:

```python
        Input(CLEAR_CACHE_COMPLETE_STORE_ID, "data", allow_optional=True),
```

with:

```python
        Input(CLEAR_CACHE_COMPLETE_STORE_ID, "modified_timestamp", allow_optional=True),
```

4. Keep all other Inputs, States, Outputs, function arguments and the whole body unchanged. `_clear_cache_complete` is unused in the inspected function; it is a wake-up signal.
5. If you already have the timestamp version, keep it. Do not paste another decorator or callback.

This still wakes the callback after a real Clear Cache update, without directly depending on the long callback's `data` Output. Do not replace `data` with `modified_timestamp` throughout the app: other callbacks need the real generation value for validation.

## 4. Check the revision notification and repair it only if needed

The required flow is:

```text
User changes a tab/filter during refresh
  -> normal view callback reads the last committed snapshot

Server commits revision N
  -> independent browser publisher updates data-revision-store
  -> existing visible-view callbacks render revision N
  -> their acknowledgements let the hero finish
```

The publisher must run while the hero is still active. Waiting for the hero to finish before publishing revision N creates a circle: the hero waits for the views, but the views never receive N.

### 4A. If the earlier independent publisher is already installed

Check that all of these are true:

- `committed-revision-poll` exists once in the shared shell and drives one clientside callback.
- That callback alone writes `data-revision-store.data`; it uses the actual Store as State to compare revisions.
- `refresh-commit-revision.children` is **State**, not Input, in that browser callback.
- `syncCommittedDataRevision` records the newest committed revision; it no longer directly calls `set_props` on `data-revision-store`.
- `app.canPublishDataRevision()` allows normal refreshes and post-commit view updates. Its cold-start `mode !== "bootstrap"` guard can stay.
- The publisher does not wait for `refresh-busy-store`, `!refreshProgressState`, `dashIsLoading() === false` or “all view acknowledgements received”.

If these checks pass and revision propagation works, keep your publisher. Remove only a locally added wait condition that makes publication depend on the hero finishing. If your Hero baseline capture also needs the removed `renderedDataRevisionFloor()` function, use the coordinated replacement below. Do not restore the old direct Store writer to get that function back.

### 4B. Known complete replacement when your publisher is missing or mixed

Use this section as one coordinated edit only if 4A fails. Skip it if your current equivalent works. The existing page-mount guard below covers warm Risk and P&L, matching the inspected source. Keep any working additional page guards from your implemented Data/Stock guides; do not accidentally narrow their supported routes.

**File 1: `assets/s12_refresh.js`**

1. Remove `let lastPublishedDataRevision = 0;` if present.
2. Find the neighbouring revision publisher functions near `normalizedRevision` and before `claimSessionReload`.
3. Replace the existing `renderedDataRevisionFloor`, `financialPageCanConsumeRevision`, `syncCommittedDataRevision` definitions and any existing `app.pendingCommittedDataRevision`/`app.canPublishDataRevision` assignments in this region with this one block. If the floor function was already removed, start at the existing `financialPageCanConsumeRevision` definition. Keep `normalizedRevision` before it and `claimSessionReload` after it.

```javascript
    const financialPageCanConsumeRevision = () => (
      (document.getElementById("cube-page-container")
        && document.getElementById("risk-type-tabs"))
      || document.getElementById("pnl-page-container")
    );

    app.pendingCommittedDataRevision = 0;
    app.observedPublishedDataRevision = 0;

    // A warm refresh remains interactive, including while the hero waits
    // for its required views. Cold startup still uses its existing owner.
    app.canPublishDataRevision = () => (
      refreshProgressState?.mode !== "bootstrap"
      && Boolean(financialPageCanConsumeRevision())
    );

    // Compatibility with the click-baseline capture in Hero.md. This is
    // known revision metadata, NEVER proof that all views have rendered.
    const renderedDataRevisionFloor = () => Math.max(
      0,
      normalizedRevision(app.observedPublishedDataRevision) ?? 0,
      normalizedRevision(app.pendingCommittedDataRevision) ?? 0,
      normalizedRevision(
        document.getElementById("refresh-commit-revision")?.textContent,
      ) ?? 0,
    );

    const syncCommittedDataRevision = (progress) => {
      const progressRevision = progress?.running === false
        ? normalizedRevision(progress.revision) : null;
      const commitRevision = normalizedRevision(
        document.getElementById("refresh-commit-revision")?.textContent,
      );
      const candidates = [progressRevision, commitRevision]
        .filter((value) => value !== null);
      if (!candidates.length) return false;
      const revision = Math.max(...candidates);
      if (revision <= app.pendingCommittedDataRevision) return false;
      app.pendingCommittedDataRevision = revision;
      return true;
    };
```

4. Keep every existing `syncCommittedDataRevision(...)` call. Keep all your Hero lifecycle functions and completion acknowledgements.
5. Search this asset for `set_props`/`setProps` targeting `data-revision-store`: remove that old publisher write if a copy remains. Keep unrelated writes such as refresh button state.
6. `renderedDataRevisionFloor()` now exists for the Hero click baseline only. It reports known revision metadata and does not inspect a nonexistent Store DOM node. Keep your baseline fixed after the click. Never use this helper as evidence that all required views finished.

**File 2: `cube/ui/s04_components.py`**

1. In `build_shared_refresh_shell`, keep:

```python
            dcc.Store(id="data-revision-store", data=rendered_revision),
```

2. Immediately after it, add this only if it does not already exist:

```python
            dcc.Interval(
                id="committed-revision-poll",
                interval=1_000,
                n_intervals=0,
            ),
```

3. Keep one instance in the persistent shell. Keep the startup/automatic-refresh intervals and the existing `refresh-commit-revision` hidden Span. This new clock runs a browser callback, not a provider query every second.

**File 3: `cube/pages/risk/s15_refresh.py`**

1. Inside `register_refresh_callbacks`, find `if refresh_manager is not None:`.
2. Immediately inside that branch, before `coordinator = ...`, add the following registration. If you already have the `committed-revision-poll` publisher, replace that registration with this one instead of adding another.

```python
        app.clientside_callback(
            """
            function (_tick, committed, published) {
                const noUpdate = window.dash_clientside.no_update;
                const assets = window.__cubeV5Assets;
                const normalize = (value) => {
                    if ((typeof value !== "number" && typeof value !== "string")
                        || (typeof value === "string" && !value.trim())) return null;
                    const number = Number(value);
                    return Number.isSafeInteger(number) && number >= 0 ? number : null;
                };
                const current = normalize(published) ?? 0;
                if (!assets) return noUpdate;
                assets.observedPublishedDataRevision = current;
                if (typeof assets.canPublishDataRevision !== "function"
                    || !assets.canPublishDataRevision()) return noUpdate;
                const candidates = [committed, assets.pendingCommittedDataRevision]
                    .map(normalize).filter((value) => value !== null);
                if (!candidates.length) return noUpdate;
                const revision = Math.max(...candidates);
                return revision > current ? revision : noUpdate;
            }
            """,
            Output("data-revision-store", "data"),
            Input("committed-revision-poll", "n_intervals"),
            State("refresh-commit-revision", "children"),
            State("data-revision-store", "data"),
            prevent_initial_call=False,
        )
```

3. `Input`, `Output` and `State` already exist in the inspected imports. Preserve the eight-space indentation shown.
4. The long `refresh_pipeline` callback must keep `Output("refresh-commit-revision", "children")`, not write `data-revision-store.data`. Its returned revision still belongs in the same first return position; do not delete or reorder its Outputs/returns.
5. Keep one normal callback owner for `data-revision-store.data`. Do not add `allow_duplicate=True` to conceal a second owner.
6. Keep the rest of `refresh_pipeline`, including its `running` entries for refresh-action controls. Unchanged revisions return `no_update` from the new publisher, so the timer does not rerender the app every second.

## 5. Make the hero a status panel, not a page lock

These are checks for locally added code. Skip a removal if the code is absent. Do not paste a global “enable every control” workaround.

### 5A. Check the refresh callback's `running` list

In `cube/pages/risk/s15_refresh.py`, the inspected `refresh_pipeline` disables these existing financial-action controls while it runs:

```text
refresh-portfolios-button
refresh-pl-button
reload-risk-button
auto-refresh-toggle
commo-market-toggle
risk-checker-toggle
```

It also sets `refresh-busy-store.data` and `refresh-status.className`. Clear Cache and force-date Apply have their existing separate availability logic. Keep these controls and the server writer guard.

Remove only entries you added for ordinary browsing controls, for example disabling Risk Type tabs, VA/display modes, underlying pickers, filters, normal table interaction or navigation. Keep any intentional restriction for actual editing/submission of financial adjustments. Being able to browse does not require submitting competing writes.

### 5B. Check ordinary render callbacks for a new blanket busy guard

Search these files for `refresh_busy`, `refresh-busy-store`, `is-refreshing` and any new “wait for hero” condition:

```text
cube/pages/risk/s07_explorer.py
cube/pages/risk/s14_workspacecallbacks.py
cube/pages/pnl/s08_aggregate.py
```

For a normal read/render callback, remove a locally added guard whose sole purpose is “the hero is active, therefore return `no_update`/`PreventUpdate`.” Keep its real page/selection/revision validation and error handling. Remove the newly added busy Input/State and its matching argument if that argument is now unused. Do not change return order.

If a read callback was given a direct Input from `refresh-commit-revision.children` or the long callback's `refresh-result-store.data` only to wake it after a refresh, route that wake-up through the existing independent `data-revision-store.data` instead. Do not add a second identical Input; keep the function's argument count matched to its decorator. Do not do this to genuine settings reconciliation or transaction callbacks that consume the actual result.

The inspected `load_market_udl_options` and `render_market_search` already use view/selection and the independent revision. Quick Market did not freeze in the earlier dependency reproduction; a remaining Quick Market freeze needs the checks in step 7, not a claim that the Risk timestamp change explains everything.

### 5C. Check for a locally added page-sized overlay or loading wrapper

The expected baseline CSS in `assets/s01_shell.css` is:

```css
.refresh-progress {
  margin: 12px 0 14px;
  padding: 12px 13px;
  border: 1px solid var(--outline);
  border-radius: var(--radius);
  background: var(--surface-soft);
}
```

Keep this inline panel and your existing inner card/stage styles. If your Hero implementation replaced its positioning with `position: fixed; inset: 0` or added a modal backdrop over the app, remove those added overlay declarations/backdrop. Keep the hero content in the shared shell above the page content.

The small `.cube-global-loader` in the same stylesheet should retain:

```css
  position: fixed;
  right: 24px;
  bottom: 24px;
  pointer-events: none;
```

Keep its existing small dimensions and other styling. Do not expand it across the page. Search later CSS files too: a later `pointer-events: auto` override or `.cube-is-loading ... { pointer-events: none; }` applied to the app can override the correct earlier rules.

In any newly added Hero JavaScript, remove only page-lock operations such as setting the page root `inert`, adding a full-screen click catcher, or preventing every click/keydown while a refresh is active. In `cube/app/s07_factory.py`, remove a newly added full-page `dcc.Loading` wrapper that owns/hides the entire existing page during this action, keeping its child page/shell layout and existing legitimate local loading indicators. Do not remove initial-load handling; there is no prior snapshot on the very first load.

Do not delete `refreshProgressState` to unlock the page. Do not bring back the 300 ms auto-hide timer. Do not make the hero transparent to conceal a still-running task.

## 6. Keep completion tracking observational

`Hero.md` still applies to whether a refresh is complete. Its acknowledgements observe what rendered; they must not prevent the ordinary rendering that produces those acknowledgements.

1. Keep using the existing last-good snapshot reader while backend refresh runs.
2. Publish a confirmed committed revision while the hero remains active, then let visible renderers consume it.
3. Keep pending view acknowledgements and the active hero until those required results settle.
4. If the user changes the active view, use your existing Hero view-request identity/retirement rules to track the replacement view. Do not lock navigation to avoid this case or wait forever for an unmounted page.
5. Do not make every new search, mouse click or permanent interval part of the refresh. Track the finite refresh-dependent work described in `Hero.md`.
6. A failure still leaves the last good data available and the error visible. A lost progress response still means unconfirmed status, not permission to mark completion or retry the financial action automatically.

This guide changes none of the full-wait success conditions. It separates “work is still happening” from “the user cannot browse.”

## 7. Restart and prove the intended behaviour

1. Save the edited files. Compile each Python file you actually edited. From a notebook in your app folder:

```python
from pathlib import Path

for name in (
    "cube/pages/risk/s07_explorer.py",
    "cube/pages/risk/s15_refresh.py",
    "cube/ui/s04_components.py",
):
    path = Path(name)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
    print("Syntax OK:", name)
```

2. Restart with your normal startup command/cell, then Ctrl+F5. Resolve any duplicate Output, missing component or JavaScript `ReferenceError` before judging interaction. A guide-only GitHub update does not modify your running app.
3. Start from a loaded snapshot. Press Refresh P&L once, and while it is still running change IR/FX, Cross/Split VA, a filter and an underlying; use Quick Risk and Quick Market. Normal views should respond with the last committed revision. They can still take their normal calculation/rendering time.
4. Navigate between the existing pages. The shared hero should stay visible for this document's pending action. Do not repeatedly press refresh to test navigation.
5. In a development run, hold the backend briefly and then hold one required visible renderer after backend commit. Browse in both phases. The hero must remain active until its final required acknowledgement; the page must remain usable in both phases.
6. Leave the chosen view alone as refresh completes. Its new revision should render without another click. Check that the completed hero remains visible and its revision is truthful.
7. Verify the existing refresh buttons prevent duplicate writes. Test a refresh failure: last-good values remain usable and the hero shows the failure. Test Clear Cache separately: actual reset generations must still invalidate old requests and wake filters.

If one view still freezes, inspect Browser Developer Tools → Network, filtered to `_dash-update-component`:

| Observation while you click/type | Check next |
|---|---|
| Control cannot focus/open, or navigation does not respond | A disabled control, `inert` ancestor or overlay in step 5. Use the Elements panel to identify the actual element over it. |
| Control changes, but no expected render request appears until refresh ends | A direct callback dependency or an added busy gate. Inspect that renderer's actual Inputs and their producers. |
| Render request is sent but remains pending until refresh ends | Server request capacity, an added broad lock, or expensive work in the deployed process. The Risk timestamp edit cannot fix this case. |
| Request returns a traceback/error | Use that callback's exception, not more refresh clicks. |
| Request succeeds but the displayed revision never changes | Publisher ownership, target revision and the actual callback Outputs. Check step 4 and browser errors. |

The checked server configuration uses one `gthread` worker with four threads by default (`gunicorn.conf.py`), preserving one in-memory manager. If your startup command changed this to a single synchronous request worker, restore the existing threaded configuration. Do not blindly add worker processes: each would have its own manager/snapshot. If requests remain slow with the existing configuration, record the particular callback and timing before changing concurrency or locks.

## 8. What was checked for this guide

The checked sources are the v7 application baseline and the published `Hero.md`, plus the earlier interaction fix. Your implemented local application may differ. The baseline proves the unwanted Clear Cache dependency, separate snapshot read/write locks, inline hero, nonblocking small loader, and the existing refresh-action-only disabled list.

Validation for the proposed snippets passed:

- The modified baseline Python files parse, the full modified refresh JavaScript passes syntax checking, and Dash registers the publisher with exactly one timer Input and the two intended States.
- Focused JavaScript checks confirm publication during an active normal refresh, preservation of the bootstrap guard, no rollback for old/invalid revision signals, `no_update` for an unchanged Store, and a callable Hero baseline compatibility function.
- A local Chrome/Dash browser reproduction held the backend open. With the original `data` dependency, Risk stayed queued; with `modified_timestamp`, the selected Risk view rendered on the last-good revision before refresh ended. Quick Market remained responsive in both cases.
- The same browser fixture used the exact replacement publisher and held a required Risk renderer after revision 8 committed. Revision 8 still published while refresh state remained active; a separate Market view remained usable; a simple illustrative hero observer stayed pending until the held renderer returned, then retained its terminal display. There were no browser JavaScript errors.

The browser fixture verifies the dependency and publication behaviour; its illustrative hero observer is not a test of your complete local `Hero.md` implementation. It does not establish why every page in your running app freezes or prove all of your financial adapters and completion acknowledgements are correct. Use step 7 against that application after applying the relevant edits.

To roll back only this repair, restore the files you changed from the same backup and restart/hard-refresh. If you used step 4B, restore its three files together so that the direct writer and browser callback do not both own the revision Store. Keep your other JTD, Quick Risk, Data and connector work.

Source references: [Risk filter callback](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/risk/s07_explorer.py), [refresh callback](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/risk/s15_refresh.py), [refresh asset](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/assets/s12_refresh.js), [shell CSS](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/assets/s01_shell.css), and [the Hero guide this supplements](https://github.com/streamlitdash/Rebirth-V5/blob/caaa96fe325d520b3fbcc8f2eae36c709ffc4f2a/Hero.md).
