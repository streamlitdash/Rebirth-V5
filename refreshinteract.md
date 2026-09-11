# Keep the app interactive while a refresh and its hero are running

Apply this after your implemented `Hero.md`. The hero should remain visible until its work finishes **and you should still be able to navigate, change filters, select an underlying and use Quick Risk/Quick Market while it runs**. Those views use the last committed snapshot until a new one is available.

**11 September correction:** section 4 now removes the bootstrap publication gate. The previous instruction to retain that gate conflicts with waiting for views before completing startup. Section 5D repairs replacement markup only; it is not a repair for stopped polling or a classifier rejecting live updates. The broader reported live-progress failure still requires inspection of the implemented application code.

This guide repairs the interaction path. It does not remove the full-completion checks from `Hero.md`. It also supersedes that guide's instruction to preserve the old revision publisher if you already installed the earlier interaction fix.

## 1. What went wrong, and what is confirmed

The earlier guides were incomplete as an implementation package. Hero sections 1.8–1.10 describe new classification, completion and view-acknowledgement logic without supplying all of that code. Installing a display helper cannot fill those gaps. Do not repeatedly add restoration calls or another poller to address a static hero; inspect the installed lifecycle first.

One specific instruction error is corrected here: the independent publisher must also work while the startup hero remains active. Cold Risk shell hydration can leave `data-revision-store` at 0 even after `refresh-commit-revision` becomes 1. If the hero waits for revision-driven views but the publisher refuses to run in bootstrap mode, those waits can become circular. The initial page can already contain revision-1 content, so this is not proof that every cold-start render is blocked, nor an explanation for all missing live updates. Section 4 removes the conflicting gate while retaining the page-mount check.

For a hero that appears but gives no fresh details, check the actual installed `assets/s12_refresh.js` together with `assets/s13_risk.js` and `cube/pages/risk/s15_refresh.py`. Compare the first browser Console error, successive progress responses and the painter's accepted samples. A response containing changing function/count values establishes backend progress; it does not establish that the painter received them. The unchanged server placeholder alone establishes neither backend failure nor completion.

Keep these boundaries explicit during that inspection:

- `finished_at` and fresh post-callback confirmation govern terminal confirmation. They must not be prerequisites for displaying ordinary running progress.
- `startup_attempt_id` and the manager's `attempt_id` are different identifiers. Never require equality between them.
- A new financial action and its hero must have a coordinated start. An old unconfirmed hero cannot silently reject a new UI start while the native button still launches another backend refresh. The earlier unconditional active-state guard did not specify this recovery path.

These are diagnosed guide gaps, not a claim to have inspected or repaired your separately edited app. A complete live-progress replacement must be built and tested against those actual files before being supplied as executable instructions.

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
- `app.canPublishDataRevision()` allows publication as soon as the financial layout can consume it, including while the hero remains in bootstrap mode. Remove the old bootstrap exclusion using 4A.1 below.
- The publisher does not wait for `refresh-busy-store`, `!refreshProgressState`, `dashIsLoading() === false` or “all view acknowledgements received”.

If these checks pass and revision propagation works, keep your publisher. Remove only a locally added wait condition that makes publication depend on the hero finishing. If your Hero baseline capture also needs the removed `renderedDataRevisionFloor()` function, use the coordinated replacement below. Do not restore the old direct Store writer to get that function back.

#### 4A.1 Correct the already-installed bootstrap gate

In `assets/s12_refresh.js`, find this existing assignment from the previous version of this guide:

```javascript
    app.canPublishDataRevision = () => (
      refreshProgressState?.mode !== "bootstrap"
      && Boolean(financialPageCanConsumeRevision())
    );
```

Replace that whole assignment with:

```javascript
    app.canPublishDataRevision = () => (
      Boolean(financialPageCanConsumeRevision())
    );
```

Keep `financialPageCanConsumeRevision()`, the actual Store comparison, the single publisher callback and the existing intervals. This permits notification of a committed revision; it does not start a second refresh or treat publication as completion. If a duplicate bootstrap exclusion remains inside the old `syncCommittedDataRevision`, use the coordinated block in 4B instead of retaining two publisher implementations. Do not add another timer.

Verify a cold Risk start with a deliberately slow visible renderer: revision 1 must reach `data-revision-store` while the hero is still waiting for that renderer. It must not publish to a missing financial layout or invent a revision before the server commits. Repeat with P&L and an ordinary warm refresh. Keep the hero's completion checks intact.

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

    // Publishing must not wait for the hero: the hero can be waiting
    // for views that need this revision, including after cold startup.
    app.canPublishDataRevision = () => (
      Boolean(financialPageCanConsumeRevision())
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

### 5D. Restore a replaced hero panel; first distinguish a stopped progress lifecycle

This section corrects the missing display-restoration step in `Hero.md` sections 1.6 and 1.9. The pasted 1.6 code made a replacement panel visible, but restoring its contents was left to later prose. A fresh panel could therefore retain its waiting placeholder while the real refresh state survived.

This is a confirmed gap in the earlier instructions, and a possible explanation for your panel. Your locally implemented application has not been inspected. The repair below handles a replaced hero panel and checks whether the full markup is present. It does not turn a failed status request into a successful refresh.

Keep the rest of this document. If steps 3–5C are already installed, start here. All JavaScript edits below belong in the existing `assets/s12_refresh.js`; keep the JTD click changes in `assets/s13_risk.js`.

#### 5D.1 Check whether the real hero is present

While the waiting panel is showing, open Browser Developer Tools → Console and run this read-only check:

```javascript
(() => {
  const panels = document.querySelectorAll('[id="refresh-progress"]');
  const panel = panels[0];
  const required = [
    "refresh-progress-title", "refresh-progress-elapsed",
    "refresh-progress-product", "refresh-progress-function",
    "refresh-progress-source", "refresh-progress-count", "refresh-progress-hold",
    "refresh-progress-bar-track", "refresh-progress-bar",
    "refresh-stage-readiness", "refresh-stage-risk", "refresh-stage-market",
    "refresh-stage-pl", "refresh-stage-final",
  ];
  const selectors = required.map(id => `[id="${id}"]`);
  for (const stage of ["readiness", "risk", "market", "pl", "final"]) {
    for (const part of ["icon", "function", "duration"]) {
      selectors.push(`#refresh-stage-${stage} .refresh-stage-${part}`);
    }
  }
  return {
    panelCount: panels.length,
    missing: selectors.filter(selector => !panel?.querySelector(selector)),
    title: panel?.querySelector("#refresh-progress-title")?.textContent,
    detail: panel?.querySelector("#refresh-progress-function")?.textContent,
    hidden: panel?.hidden,
  };
})()
```

- `panelCount` should be **1**, with `missing: []` once the page has mounted.
- If IDs are missing, the panel may be a small placeholder instead of the real hero. Use 5D.2 to recover its existing layout.
- If the full structure is present, skip the optional Python replacement and use 5D.3–5D.5 to restore its current display after replacement.
- If `panelCount` is greater than one, remove the accidentally duplicated hero from the page layout. Keep the one in `shared-refresh-shell`; two elements with the same IDs can send updates to the wrong panel.

Do not replace the whole page with a loading tab or a `html.Div("Waiting for Server", id="refresh-progress")`. The IDs above are where the existing JavaScript writes the real progress.

#### 5D.2 Only if the hero layout was replaced: restore its existing builder

**File: `cube/ui/s04_components.py`.** Find `def _build_refresh_progress(`. Replace only that function, stopping immediately before `def build_shared_refresh_shell(`, with this complete copy of the inspected existing builder. If this full builder is already present and the check above passes, leave it alone.

Keep the existing `Mapping` and Dash `html` imports and the existing `build_cube_loader()` in this module. This copy uses those existing names; it adds no package or callback.

```python
def _build_refresh_progress(
    stage_delays: Mapping[str, float] | None,
    *,
    initial_loading: bool = False,
    initial_error: bool = False,
) -> html.Div:
    """Build the shared progress hero without performing any source work."""
    stage_delay_values = dict(stage_delays or {})
    visible = initial_loading or initial_error
    if initial_error:
        title = "Initial data load failed"
        product = "No financial snapshot was published"
        function_name = "Use Retry after checking the connector error"
        class_name = "refresh-progress is-error"
    elif initial_loading:
        title = "Loading Cube data"
        product = "Preparing the first validated snapshot"
        function_name = "Waiting for the server-started refresh"
        class_name = "refresh-progress is-running"
    else:
        title = "Refresh pipeline"
        product = "Preparing product queue"
        function_name = "Waiting for refresh request"
        class_name = "refresh-progress"

    return html.Div(
        [
            html.Div(
                [
                    html.Div(
                        [
                            build_cube_loader("Refreshing Cube data", announce=False),
                            html.Span(
                                title,
                                id="refresh-progress-title",
                                className="refresh-progress-title",
                            ),
                        ],
                        className="refresh-progress-title-wrap",
                    ),
                    html.Span(
                        "",
                        id="refresh-progress-elapsed",
                        className="refresh-progress-elapsed",
                        **{"aria-hidden": "true"},
                    ),
                ],
                className="refresh-progress-header",
            ),
            html.Div(
                [
                    html.Strong(
                        product,
                        id="refresh-progress-product",
                        className="refresh-product-name",
                    ),
                    html.Span("Active call", className="refresh-function-label"),
                    html.Code(
                        function_name,
                        id="refresh-progress-function",
                        className="refresh-function-name",
                    ),
                    html.Span(
                        "",
                        id="refresh-progress-source",
                        className="refresh-function-source",
                    ),
                    html.Span(
                        "",
                        id="refresh-progress-count",
                        className="refresh-function-count",
                    ),
                    html.Span(
                        "",
                        id="refresh-progress-hold",
                        className="refresh-function-hold",
                    ),
                    html.Span(
                        html.Span(
                            id="refresh-progress-bar",
                            className="refresh-progress-bar-fill",
                        ),
                        id="refresh-progress-bar-track",
                        className="refresh-progress-bar-track",
                    ),
                ],
                className="refresh-function-live refresh-product-card",
                role="status",
                **{"aria-live": "polite", "aria-atomic": "true"},
            ),
            (
                None
                if initial_loading or initial_error
                else html.P(
                    "The current committed snapshot stays usable while a staged refresh runs; refresh controls are locked until it finishes.",
                    className="refresh-progress-note",
                )
            ),
            html.Ol(
                [
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Load RiskChecker readiness",
                                className="refresh-stage-function",
                            ),
                            html.Span(className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-readiness",
                        className="refresh-stage",
                    ),
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Risk & @risk product calls (if dates changed)",
                                className="refresh-stage-function",
                            ),
                            html.Span(className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-risk",
                        className="refresh-stage",
                    ),
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Open + Current market",
                                className="refresh-stage-function",
                            ),
                            html.Span(className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-market",
                        className="refresh-stage",
                    ),
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Calculate product P&L",
                                className="refresh-stage-function",
                            ),
                            html.Span(className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-pl",
                        className="refresh-stage",
                    ),
                    html.Li(
                        [
                            html.Span("", className="refresh-stage-icon"),
                            html.Span(
                                "Validate + publish snapshot",
                                className="refresh-stage-function",
                            ),
                            html.Span("Finalising", className="refresh-stage-duration"),
                        ],
                        id="refresh-stage-final",
                        className="refresh-stage",
                    ),
                ],
                className="refresh-stage-list",
            ),
        ],
        id="refresh-progress",
        className=class_name,
        hidden=not visible,
        **{
            "data-risk-product-delay": str(
                0.0
                if initial_loading or initial_error
                else stage_delay_values.get("risk_product", 0.0)
            ),
            "data-initial-load": "true" if visible else "false",
        },
    )
```

Inside `build_shared_refresh_shell()`, keep the existing call below. If you replaced that call with a waiting label, restore the call in its original place after `refresh-control-strip`. Do not add a second copy.

```python
            (
                _build_refresh_progress(
                    stage_delays,
                    initial_loading=initial_loading,
                    initial_error=bool(error),
                )
                if refresh_enabled
                else None
            ),
```

Keep its actual flags. Do not hardcode `initial_loading=True` to keep the hero visible: that would mislabel a warm page as initial startup. An idle hero before the first action is hidden; the existing lifecycle shows it when work starts and keeps a completed result visible according to your Hero implementation. Do not add a callback that replaces `refresh-progress.children` or the shared shell on every poll.

#### 5D.3 Add the complete display-restoration helper

**File: `assets/s12_refresh.js`.** Immediately after the existing line below, add the full helper. Keep that line and the following `normalizeProgressStage` function.

```javascript
    const REFRESH_STAGES = ["readiness", "risk", "market", "pl", "final"];
```

The existing `refreshProgressState.panel` still points to the old hero when Dash replaces it. The helper transfers only its known text, stage styling and progress attributes into the new layout, then updates that one pointer. It preserves the current title, error and “Updating displayed tables” wording without guessing your locally implemented classifier's phase-field names.

```javascript
    const restoreRefreshPanel = () => {
      const state = refreshProgressState;
      if (!state) return;
      const replacement = document.getElementById("refresh-progress");
      // A temporary DOM gap does not end the request or its clocks.
      if (!replacement) return;
      if (state.panel === replacement && replacement.isConnected) {
        if (replacement.hidden) replacement.hidden = false;
        return;
      }

      const previous = state.panel;
      const textSelectors = [
        "#refresh-progress-title", "#refresh-progress-elapsed",
        "#refresh-progress-product", "#refresh-progress-function",
        "#refresh-progress-source", "#refresh-progress-count",
        "#refresh-progress-hold",
        ...REFRESH_STAGES.flatMap((stage) => [
          `#refresh-stage-${stage} .refresh-stage-icon`,
          `#refresh-stage-${stage} .refresh-stage-function`,
          `#refresh-stage-${stage} .refresh-stage-duration`,
        ]),
      ];
      const statusSelectors = [
        ...REFRESH_STAGES.map((stage) => `#refresh-stage-${stage}`),
        "#refresh-progress-bar-track", "#refresh-progress-bar",
      ];
      const selectors = [...textSelectors, ...statusSelectors];
      const hasCompletePanel = (panel) => Boolean(
        panel && selectors.every((selector) => panel.querySelector(selector)),
      );
      if (!hasCompletePanel(replacement)) {
        // Retain the old panel until Dash has mounted all of the new children.
        if (replacement.hidden) replacement.hidden = false;
        const title = replacement.querySelector("#refresh-progress-title");
        if (title && title.textContent !== "Refresh panel is still mounting") {
          title.textContent = "Refresh panel is still mounting";
        }
        return;
      }

      const states = ["is-running", "is-active", "is-complete", "is-skipped", "is-error"];
      const aria = ["role", "aria-valuemin", "aria-valuenow", "aria-valuemax", "aria-label", "aria-valuetext"];
      const copyStatus = (from, to) => {
        states.forEach((name) => to.classList.toggle(name, from.classList.contains(name)));
        aria.forEach((name) => {
          if (from.hasAttribute(name)) to.setAttribute(name, from.getAttribute(name));
          else to.removeAttribute(name);
        });
      };
      if (hasCompletePanel(previous)) {
        textSelectors.forEach((selector) => {
          replacement.querySelector(selector).textContent = previous.querySelector(selector).textContent;
        });
        copyStatus(previous, replacement);
        statusSelectors.forEach((selector) => {
          const from = previous.querySelector(selector);
          const to = replacement.querySelector(selector);
          copyStatus(from, to);
          to.hidden = from.hidden;
          ["width", "--stage-progress"].forEach((property) => {
            const value = from.style.getPropertyValue(property);
            if (value) to.style.setProperty(property, value);
            else to.style.removeProperty(property);
          });
        });
        if (previous.hasAttribute("data-progress-source")) {
          replacement.setAttribute("data-progress-source", previous.getAttribute("data-progress-source"));
        } else replacement.removeAttribute("data-progress-source");
      } else {
        // Lost markup is not proof of backend success or failure.
        states.forEach((name) => replacement.classList.remove(name));
        replacement.classList.add(state.backendError ? "is-error" : "is-running");
        replacement.querySelector("#refresh-progress-title").textContent = state.backendError
          ? "Refresh error — checking status"
          : "Refresh status not confirmed";
        replacement.querySelector("#refresh-progress-product").textContent = state.backendError
          || "The previous progress display could not be restored";
        replacement.querySelector("#refresh-progress-function").textContent =
          "Waiting for the next confirmed progress update";
        ["source", "count", "hold"].forEach((suffix) => {
          replacement.querySelector(`#refresh-progress-${suffix}`).textContent = "";
        });
        replacement.querySelector("#refresh-progress-bar-track").hidden = true;
        REFRESH_STAGES.forEach((stage) => {
          const row = replacement.querySelector(`#refresh-stage-${stage}`);
          states.forEach((name) => row.classList.remove(name));
          aria.forEach((name) => row.removeAttribute(name));
          row.style.removeProperty("--stage-progress");
          row.querySelector(".refresh-stage-duration").textContent = "Status not confirmed";
        });
        replacement.dataset.progressSource = "pending";
      }
      state.panel = replacement;
      replacement.hidden = false;
      const elapsed = replacement.querySelector("#refresh-progress-elapsed");
      if (Number.isFinite(state.startedAt)) {
        elapsed.textContent = `${Math.max(0, Math.floor((Date.now() - state.startedAt) / 1000))}s elapsed`;
      }
    };
```

This adds one function, not a callback or a second refresh state. It does not clone HTML, retain table data, fetch progress, mark a task complete, or create a timer. It restores the **last displayed** progress; normal accepted updates continue advancing it. A temporary missing/incomplete panel keeps the old pointer so that restoration can happen when the complete new layout appears. If even the old layout has been lost, it shows an honest unconfirmed status until the existing lifecycle can paint a confirmed update.

For whole-panel replacement this supersedes Hero 1.6's reattachment-only block and Hero 1.9 item 7's proposed repaint helper. It repairs an active attempt. It cannot recover a previous display that was already overwritten before you installed it, or reconstruct a completed result after its state has been cleared; keep your existing terminal-display handling. Validate it on the next normal refresh after restarting the edited asset.

The status classes listed in the helper are the existing classes in the inspected app. If your custom hero uses an additional phase class, include that actual class in `states`; preserve its existing CSS and phase owner.

#### 5D.4 Replace the reattachment-only function

Find the later assignment starting `syncRefreshLifecycleNodes = () => {`. Replace its entire body through the matching `};` with the following. Keep its earlier declaration/export near the top of the asset and keep its callers.

```javascript
  syncRefreshLifecycleNodes = () => {
    restoreRefreshPanel();
    syncRefreshStatusObserver();
    if (financialPageCanConsumeRevision()) {
      syncCommittedDataRevision(lastBackendProgress);
    }
  };
```

This replaces the earlier block that only set `state.panel`, `hidden = false` and `is-running`. Do not leave that old block below this one; it would erase error/completed styling again.

If your implemented `syncRefreshLifecycleNodes` also contains deliberate participant/view-acknowledgement tracking from Hero 1.10, keep that extra logic after restoration. Replace the old reattachment block and move restoration first; do not delete unrelated completion tracking just to make your function identical to the small baseline-shaped copy above.

**The order matters:** restore first, then run the existing status observer. The observer can synchronously advance the phase or finish a fully confirmed task. Restoring afterwards could overwrite that newer display with the old one. Neither restoration nor publication is conditional on the hero being finished.

Keep the existing warm-shell guard from Hero 1.5 (`if shell_revision > 0: raise PreventUpdate` inside the successful-startup branch). The shared hero stays above the routed page content. Keep the existing observer in `assets/s11_tables.js`; it already notices whole hero/status node replacements. No new global observer is needed.

#### 5D.5 Attach before existing code paints a new result

Add `restoreRefreshPanel();` at these entry points so a poll response cannot paint the new panel and then have that newer result overwritten by an old display. Keep every existing validation, classification and completion guard.

1. In `renderBackendProgress(progress)`, immediately after `if (!progress || !refreshProgressState) return;` and before looking up `panel` or writing any DOM values:

```javascript
      restoreRefreshPanel();
```

2. In your implemented `finishRefreshProgress(...)`, add the same line **after** its full-completion/rejection guards pass and **before** it reads `panel`/`title` or paints the terminal result. Keep your current signature and all backend/callback/required-view checks. Do not paste the older baseline finalizer; it contained premature completion and auto-hide behavior.

3. In `recoverReadyBootstrap(progress)`, add the same line after its existing early-return guards, immediately before `const state = refreshProgressState;`. Keep the stronger startup identity/success checks from Hero 1.8–1.10.

4. In the existing `refreshProgressPoll` interval, immediately after its awaited progress fetch and the following active-state guard, add the line:

```javascript
      const progress = await requestBackendProgress();
      if (!refreshProgressState) return;
      restoreRefreshPanel();
```

Keep the subsequent classification, restart and transport handling. If your implemented guard also checks the attempt identity after the `await`, keep that check and place the new line after it.

5. If you implemented a separate phase/result painter for Hero 1.9–1.10, put `restoreRefreshPanel();` at the start of that **existing** painter, after its state/identity guard and before its first DOM write. This is one insertion, not an instruction to invent a new phase function. Its normal work then paints the newest accepted phase. Any direct post-`await` hero writes in your custom code need the same ordering.

Do not call `startRefreshProgress()` to restore a panel; keep the existing active-attempt guard at its start. Do not call `renderBackendProgress(lastBackendProgress)` from the restoration helper: the global sample may belong to different work, and backend rendering can overwrite a later view-completion phase.

Keep the dynamic elapsed-node lookup from Hero 1.6. If your `updateElapsed` still closes over the old element, replace that inner function in `startRefreshProgress` with:

```javascript
      const updateElapsed = () => {
        const elapsedNode = document.getElementById("refresh-progress-elapsed");
        if (elapsedNode && refreshProgressState?.startedAt === startedAt) {
          elapsedNode.textContent = `${Math.floor((Date.now() - startedAt) / 1000)}s elapsed`;
        }
      };
```

Keep its existing interval and cleanup, and remove the old now-unused captured `const elapsed = ...` from that function. Do not add another clock. Keep attempt IDs, baselines, `lastAcceptedProgress`, pending view acknowledgements and terminal display retention unchanged.

#### 5D.6 Check the repaired display before changing server behavior

1. Save and restart; hard-refresh so the browser loads the edited asset. Compile `cube/ui/s04_components.py` if you changed it, and run `node --check assets/s12_refresh.js` if Node is available.
2. Repeat 5D.1. Confirm one full hero with all expected IDs.
3. Start one refresh. Confirm the real operation title, stage list and elapsed time appear. In a development run, recreate the **whole** hero from its normal builder while the request is active. Its title/stages must survive and elapsed time must continue; no second refresh request or timer should be created.
4. Repeat while the backend has committed but a required visible table is still rendering. The restored panel must retain “Updating displayed tables” (or your equivalent), remain visible and leave browsing usable. It must not revert to “Waiting for Server” or claim completion early.
5. Repeat while an error/unconfirmed state is visible. Preserve that message and styling. A temporary gap with no mounted panel must preserve the active attempt. Restore the panel and check again.
6. Let the real completion path finish. Keep its completed display visible, with no auto-hide timeout. Do not reset the task just to clear the waiting label.

If it still shows a waiting panel, distinguish these cases:

| Observation | Next check |
|---|---|
| Missing expected IDs | Restore the full builder/call in 5D.2; a small placeholder cannot display the full hero. |
| Full panel recreated, but old text never comes back | Confirm `restoreRefreshPanel()` is called before observer/paint operations and the old `state.panel` was not overwritten first. |
| The same panel's children keep being reset | Find and remove the conflicting callback/layout rewrite of `refresh-progress.children` or its title. This helper repairs a whole-panel replacement; it does not repeatedly fight another owner overwriting the same node. |
| The full hero is present, but no progress has ever been confirmed | Check the progress request and classifier; there is no prior accepted display for a DOM repair to recover. |
| JavaScript error or no poll request | Fix that asset/endpoint error before interpreting the displayed status. |

For the last two cases, retain Hero 1.7's normalized fields inside `requestBackendProgress()`:

```javascript
            finished_at: progressStartedAt(payload.finished_at),
            requested_at: now,
```

`now` is the existing timestamp captured before the request; keep it unchanged on reused responses. The backend's terminal stage names are `complete` and `error`. A classifier waiting for `done` or a field that normalization discarded will never accept completion. Keep the callback-settled and view-acknowledgement checks; an idle server response alone is not full-refresh completion.

To undo only this display repair, restore `assets/s12_refresh.js` from the backup made before 5D and restart/hard-refresh. Restore the Python builder only if you changed it. Keep the earlier interaction/publisher fix, JTD changes and current data. This section adds no new persistent file to the app.

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
- Earlier focused JavaScript checks covered normal-refresh publication, old/invalid revisions, unchanged Store values and the baseline helper. Their expectation that bootstrap publication stay blocked was wrong for the full-wait lifecycle; it is superseded by the 11 September checks below.
- A local Chrome/Dash browser reproduction held the backend open. With the original `data` dependency, Risk stayed queued; with `modified_timestamp`, the selected Risk view rendered on the last-good revision before refresh ended. Quick Market remained responsive in both cases.
- The same browser fixture used the exact replacement publisher and held a required Risk renderer after revision 8 committed. Revision 8 still published while refresh state remained active; a separate Market view remained usable; a simple illustrative hero observer stayed pending until the held renderer returned, then retained its terminal display. There were no browser JavaScript errors.

The browser fixture verifies the dependency and publication behaviour; its illustrative hero observer is not a test of your complete local `Hero.md` implementation. It does not establish why every page in your running app freezes or prove all of your financial adapters and completion acknowledgements are correct. Use step 7 against that application after applying the relevant edits.

Additional validation for section 5D passed. The optional Python builder is identical to the verified v7 source; its idle, startup and error layouts were checked for the expected stage structure and unique IDs. The complete JavaScript asset with the documented attachment hooks passes Node syntax checking.

Eleven Chrome checks using the actual Python hero layout and existing progress painter covered running and post-commit remounts, title/stage/meter/ARIA restoration, skipped stages, error text, an existing retained terminal display, a partial mount, a temporary DOM gap, missing old markup, unchanged active-state metadata, a no-mutation same-node path and normal page-button interaction. Restoration before the observer/painter allowed the subsequent newer paint to remain visible. There were no browser JavaScript errors. These are local display/integration checks; they do not implement or verify your complete custom completion classifier, financial adapters, or deployed progress endpoint. The earlier dependency checks remain relevant; the bootstrap publication expectation is corrected below.

To roll back only this repair, restore the files you changed from the same backup and restart/hard-refresh. If you used step 4B, restore its three files together so that the direct writer and browser callback do not both own the revision Store. Keep your other JTD, Quick Risk, Data and connector work.

Source references: [Risk filter callback](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/risk/s07_explorer.py), [refresh callback](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/risk/s15_refresh.py), [refresh asset](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/assets/s12_refresh.js), [shell CSS](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/assets/s01_shell.css), and [the Hero guide this supplements](https://github.com/streamlitdash/Rebirth-V5/blob/caaa96fe325d520b3fbcc8f2eae36c709ffc4f2a/Hero.md).


### 11 September validation of the publication correction

- Eight browser checks using the exact publisher registration reproduced the old bootstrap gate holding Store revision 0 after commit 1, and verified the corrected gate publishing 1 while bootstrap remained active. They also covered an unmounted financial layout, later mounting, P&L, no committed revision, and unchanged warm publication. No browser JavaScript errors were reported.
- A disposable copy of the actual Dash app with its CSV fixture adapters completed cold startup and painted different live progress values. With a test-only hold keeping the hero in bootstrap mode, the corrected publisher advanced the actual revision Store to 1 while the real Risk layout showed revision 1 and bootstrap remained active. The initial layout could already contain revision-1 content before the Store advanced. No browser JavaScript errors were reported. Artificial step delays allowed multiple progress samples; this was not a production performance measurement.
- Full-asset browser checks with controlled progress responses covered bootstrap, P&L, reload, portfolios and automatic modes. The existing restoration helper allowed fresh function/count details to advance through a whole-panel replacement. These checks isolate restoration and polling; they do not implement the unwritten classifier or establish the cause of the separately modified application's frozen hero.

The app code on GitHub v7 is still the original baseline beneath these guides. This update corrects documentation; it does not deploy an app repair or certify that all reported refresh/search issues are resolved.
