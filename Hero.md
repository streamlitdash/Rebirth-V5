# Hero — reliable refresh status and Shift+F9

Implementation guide for `streamlitdash/Rebirth-V5`, branch `v7`. Based on application code at `2220a3f4839318863a9131e3fef8118d0f82fb7d`. Updated 10 September 2026.

This independent guide covers the disappearing refresh hero, misleading completion ticks and how to verify a single Shift+F9 P&L refresh. It replaces the earlier Commo-only hero advice. Read the steps in order; keep changes that are already installed and match your deployed code before replacing a block.

Publishing this document does not change the application. The small DOM corrections include exact replacement snippets; the shared completion classifier is specified step by step and still needs implementation and browser testing. No Portfolio, Data or unrelated historical guides are included here.

## Required behaviour: keep the hero until the whole refresh finishes

**The hero must stay visible for the entire requested refresh, including work after the backend publishes its snapshot and the resulting updates to the visible tables/charts. A backend “complete” sample alone must not close it or end the active refresh display.**

Finish successfully only after all three conditions are confirmed for the same refresh:

1. The backend attempt has finished its work and published the validated result.
2. The initiating refresh callback has finished its remaining work and returned.
3. The visible views updated by that refresh have finished their dependent callbacks and rendered the target revision.

While any condition is pending, keep the hero visible, preserve the attempt and elapsed time, and show the real phase: “Refreshing data”, “Finishing refresh” or “Updating displayed tables”. A redraw, navigation within the app, polling failure, timeout, changed status text or old response must never hide it or mark it complete.

If completion cannot be confirmed, keep a visible “Waiting for confirmation” or connection-error message. A confirmed failure must leave a visible failure message. After confirmed success, keep the completed result visible until the next refresh; **do not auto-hide it after a delay**.

“Whole refresh” means the finite work started by this action, including dependent visible results. It does not mean waiting for permanent progress timers, future automatic refreshes or unrelated user activity to stop. Closing/reloading the browser destroys its DOM; reconnect to server status afterwards rather than claiming an old page can remain visible.

The implementation detail is in section 1.10 below. This update changes the guide; it does not deploy the application fix.

## 1. Refresh hero disappears; Shift+F9 appears to need several attempts

### 1.1 What is happening, in plain English

There are three separate events:

1. Your button or Shift+F9 asks the server to refresh.
2. The server fetches the required data, calculates P&L and publishes a validated snapshot.
3. The browser redraws the tables from that snapshot.

The current hero sometimes treats the end of the browser callback as proof that all three happened. It is not proof. A callback can finish because the request was rejected, another refresh already owns the writer, or the UI changed. Separately, replacing the hero's HTML can make the browser forget the active display while Python continues working.

That explains how “running on the server” and “no hero visible” can coexist. It also explains a false-looking flash of green ticks. It does **not** establish that every first or second keypress in your deployment is lost; that requires the single-press check in section 1.3.

The intended behaviour is: **one press, one request; a continuously visible and truthful status; success only after the backend, refresh callback and required visible updates have all finished.** Publication is an intermediate milestone. A successful refresh can legitimately produce the same P&L if the input prices did not change.

### 1.2 What the checked code proves, and what remains a hypothesis

| Finding | Exact location | What it means |
|---|---|---|
| Shift+F9 calls the existing enabled button's `.click()` and rejects held-key repeats. | `assets/s13_risk.js`, `keydown` listener | There is no intentional three-press rule. Keep one keyboard/button path. |
| The manual branch already passes `force_pl=True`, `reason="manual P&L"`, `copy_result=False`. | `cube/pages/risk/s15_refresh.py`, `refresh_pipeline`, `refresh-pl-button` branch | Do not fix this by adding another forced call or by reloading all Risk. |
| Normal callback completion calls `finishRefreshProgress()` without a matching terminal backend result. The busy/follower branch accepts any idle progress object. | `assets/s12_refresh.js`, `handleRefreshStatusTransition` | An ended callback or an old response can close the hero too early. |
| Other poll branches finish on `sawRunning` or changed status text, including a transport-failure path. | `assets/s12_refresh.js`, `refreshProgressPoll` | Fixing only the observer leaves other premature-success exits. |
| The finalizer marks every non-skipped stage complete and hides successful progress after 300 ms. | `assets/s12_refresh.js`, `finishRefreshProgress` | The “ticks everything and disappears” effect is explicitly implemented. It is not reliable proof of fresh data. |
| A detached normal-refresh panel causes `abandonRefreshProgress(state)` even if a replacement exists. | `assets/s12_refresh.js`, `syncRefreshLifecycleNodes`; invoked by the DOM observer in `assets/s11_tables.js` | A DOM replacement can erase the hero's local state without cancelling the backend. |
| The startup shell callback may rebuild an already populated shell when `is-refreshing` is present. | `cube/pages/risk/s15_refresh.py`, `hydrate_shared_refresh_shell` | This is a reachable remount hazard. The ordinary warm refresh does not itself enable the startup interval, so this is not proven to be the trigger for every disappearance. |
| A forced progress poll can join a request sent before the click; the timestamp matcher accepts starts up to one second before the click. | `assets/s12_refresh.js`, `requestBackendProgress`, `progressStartedDuringAttempt` | “Response arrived after I clicked” does not mean “response describes my click.” |
| Error text is treated as new only if it differs from the previous text. | `assets/s12_refresh.js`, `finishRefreshProgress` | Two identical failures must not turn the second failure into a success. |

Four deterministic probes of the checked JavaScript reproduced the permissive decisions: finishing while the last backend sample says running, accepting an unrelated finished sample, abandoning an available replacement panel, and accepting a start 500 ms before the click. These used extracted functions and a mocked DOM. Three additional Python source probes confirmed the warm-shell rebuild path, that manual refresh is not automatically coalesced, and that forced P&L cannot take the ordinary metadata-only no-change path. These seven checks are **not** a production-browser reproduction or tests of an implemented fix.

### 1.3 First establish whether one Shift+F9 request actually ran

Do this once before changing the code, then repeat after the implementation. Use a development session if you need to change an adapter's input.

1. Open the browser Network panel. Turn on Preserve log. Find the app's Dash update requests and its progress requests. Use the configured progress URL under your actual app/JupyterHub prefix; do not assume `/progressz` is at the host root. `backend-endpoints` and `backendEndpointUrl()` already resolve it.
2. Record the current progress `server_boot_id`, `attempt_id`, `revision` and the displayed `refresh-commit-revision`. Record which P&L view/date you are looking at.
3. Wait until the refresh button is enabled. Press Shift+F9 **once**, briefly. Inspect the relevant Dash request: `changedPropIds` should include `refresh-pl-button.n_clicks`. Other Dash requests may redraw tables; they are not extra refresh requests.
4. Record the callback response and the next fresh progress samples: `attempt_id`, `running`, `started_at`, `finished_at`, `error`, `revision` and `server_boot_id`. Do not share full request payloads or financial rows just to debug this.
5. Check the existing refresh metrics/log entry for `reason="manual P&L"`. It already records Risk, market Open, market status and P&L call counts, durations and row counts. A new manual attempt plus the expected Current/selected market-status calls is stronger evidence than the hero's animation.
6. Confirm the committed revision reached `data-revision-store`, then that the relevant live P&L callback read it. A server commit and a table render are different milestones.
7. Repeat using one button click. If both fail the same way, investigate the shared refresh path. If only the shortcut fails, inspect focus, disabled state, browser interception and whether its `n_clicks` request was emitted.

| Observation | Interpret it this way | Next action |
|---|---|---|
| No manual refresh request appears. | The event did not reach the Dash callback. | Check shortcut/button state and the capture handler; do not clear financial caches. |
| Callback reports another refresh is running. | This request did not acquire the writer. | Show “Another refresh is running; this action was not started.” Following its progress does not mean the manual action is queued. |
| Callback reports a stale revision/reset generation. | The request was rejected before work could proceed safely. | Show that rejection clearly; use the existing reload/retry instructions. Do not silently remove the guard. |
| A new attempt runs but revision is retained and an error is returned. | Refresh failed and last-good data was kept. | Investigate that attempt's error; do not show green completion. |
| Revision advances and source values are identical. | A refresh can be real with unchanged inputs/results. | Inspect selected Current/Official source and adapter timestamps. |
| Server revision advances but live P&L stays at the old revision. | Publication-to-render propagation needs attention. | Trace `syncCommittedDataRevision` and the P&L callback, not the key binding. |
| Only archived Summary/history numbers stay unchanged. | Refreshing live data does not rewrite the archive. | Check section 1.11 before treating this as a failed live refresh. |

### 1.4 Keep and remove: the small implementation boundary

Keep the current refresh manager, single-writer lock, atomic snapshot commit, last-good-data fallback, reset/revision validation, startup recovery and one-second progress polling. Keep `force_pl=True` for the manual action and `copy_result=False`; changing that flag would restore unnecessary full-frame return copies.

Remove the assumptions that “callback ended,” “loading spinner ended,” “status text changed,” or “some idle progress arrived” each means financial success. Remove normal-remount abandonment and the automatic 300 ms disappearance. Keep automatic-refresh coalescing: it is explicitly guarded for automatic requests, and the normal no-change shortcut excludes `force_pl=True`.

The lifecycle changes belong in `cube/pages/risk/s15_refresh.py` and `assets/s12_refresh.js`. `assets/s13_risk.js` needs only a small trigger guard. Sections 1.8–1.9 consolidate backend progress decisions. Section 1.10 adds small completion acknowledgements to the existing visible-view callbacks: those are required to wait for the full refresh instead of stopping at the backend commit. Keep the existing financial data path and revision stores; add no frame copies or job framework.

Before editing, make one backup/commit of the application files you will touch. If earlier Commo patches are already installed, use the new behaviour below for **all normal refresh modes**, and remove Commo-only early returns that would compete with it. Do not paste a second copy of the same JavaScript function.

### 1.5 Stop a late startup callback rebuilding a warm refresh shell

Open `cube/pages/risk/s15_refresh.py`. In `hydrate_shared_refresh_shell`, find the successful-startup branch and its existing `try/except` that computes `shell_revision`.

Immediately after that `try/except`, replace this block:

```python
                if (
                    shell_revision >= refresh_manager.health.revision
                    and "is-refreshing" not in str(status_class or "").split()
                ):
                    raise PreventUpdate
```

with:

```python
                # Startup hydration owns the cold shell only. Normal refresh
                # callbacks and the revision signal own an already loaded UI.
                if shell_revision > 0:
                    raise PreventUpdate
```

Keep the surrounding `startup.phase == "succeeded"` check and `build_shared_refresh_shell(...)` return for an uninitialised shell. Keep the failed/stalled/retry branches. Do not remove startup polling or the server-restart recovery logic.

Why: an existing positive commit revision means the shell is already populated. A late startup callback should not recreate its buttons, stores and hero just because a normal refresh is in flight or a newer revision exists. Normal publication already has a separate route.

Check both cold Risk and cold P&L navigation after this edit. A freshly started/replaced server must still reach its validated initial layout; this guard is not a substitute for the existing server-boot recovery.

### 1.6 Preserve the active hero when its panel changes

Open `assets/s12_refresh.js`. In `syncRefreshLifecycleNodes`, keep the calls to `syncRefreshStatusObserver()` and `syncCommittedDataRevision(...)` at the top. Replace everything from its `const state = refreshProgressState;` through the old `abandonRefreshProgress(state);` with:

```javascript
    const state = refreshProgressState;
    if (!state) return;
    const replacement = document.getElementById("refresh-progress");
    // A temporary page/DOM gap is not evidence that Python stopped.
    if (!replacement) return;
    if (state.panel === replacement && replacement.isConnected) {
      replacement.hidden = false;
      return;
    }
    state.panel = replacement;
    replacement.hidden = false;
    replacement.classList.remove("is-complete", "is-error");
    replacement.classList.add("is-running");
```

Keep the function's closing `};`. This snippet fixes retention/reattachment only. When adding the accepted-progress state in section 1.9, repaint the replacement from that state after attaching it; do not repaint it from an unrelated global progress response. Do not reset its start time, accepted attempt ID, baseline revision or error.

Next, inside `startRefreshProgress`, replace the `updateElapsed` function with:

```javascript
      const updateElapsed = () => {
        const elapsedNode = document.getElementById("refresh-progress-elapsed");
        if (elapsedNode && refreshProgressState?.startedAt === startedAt) {
          elapsedNode.textContent = `${Math.floor((Date.now() - startedAt) / 1000)}s elapsed`;
        }
      };
```

Remove the now-unused captured `const elapsed = document.getElementById("refresh-progress-elapsed");` in `startRefreshProgress`. Keep its interval and timer cleanup. Otherwise the clock can keep writing into the detached old node.

At the beginning of `startRefreshProgress`, before clearing timers or creating a new state, add:

```javascript
      if (refreshProgressState) {
        syncRefreshLifecycleNodes();
        return;
      }
```

This keeps a repeated click from resetting the visible attempt. It is a UI guard, not a replacement for the server writer lock. Preserve this same state during the post-commit “Updating displayed tables” phase too. Keep the shared hero above `page_container` in `cube/app/s07_factory.py`; a page-local loading wrapper must not own or hide it. Check its ancestors as well as its own `hidden` property: a hidden parent still hides the hero. Keep actual page teardown in `stopRefreshLifecycle()`/the `pagehide` handler.

### 1.7 Record fresh progress without confusing it with a result

In `requestBackendProgress`, the existing `now` is captured before the fetch. Inside its normalized `const progress = { ... }`, add these two fields beside `started_at`/`received_at`:

```javascript
            finished_at: progressStartedAt(payload.finished_at),
            requested_at: now,
```

The Python `progress_payload` already supplies `finished_at`; no extra financial data query is needed. `requested_at` is browser metadata describing when this HTTP request started. Preserve it on cached responses; never overwrite it when reusing one.

In the refresh state, record `dashCallbackCompletedAt` when the running class ends. A response used to confirm the post-callback server state must have been **requested after** that boundary. A forced poll can still join an older in-flight request, so `force=true` alone is insufficient. Keep request deduplication; if the joined response is too old, schedule the next ordinary poll rather than treating it as confirmation or launching many parallel requests.

Keep the server boot ID check. If the process changes, the old attempt cannot be confirmed by the replacement process's status. Preserve the existing recovery/error message.

Do not use the one-second timestamp tolerance to establish ownership of a manual action. Timestamps and a changed global attempt ID can help diagnose progress, but they cannot prove which browser initiated it. The next step handles ambiguous results explicitly.

### 1.8 Use the existing attempt identity to classify progress

Keep the current button/callback wiring and existing progress endpoint. There is no need to add a job queue, new request-store protocol or another copy of the financial data for this initial fix. Add one small pure helper, `classifyRefreshProgress(state, progress)`, beside `progressFingerprint()` in `assets/s12_refresh.js`.

Its job is to return `running`, `committed`, `failed`, `unconfirmed` or `ignored`, together with the accepted progress. Here `committed` means the backend milestone only; it must enter the full-refresh wait in section 1.10, not call the finalizer. This section specifies the implementation logic; it is not a fully written drop-in JavaScript function.

Implement its state and rules in this order:

1. At click time, capture `baselineRevision` as the maximum valid revision from `refresh-commit-revision`, `renderedDataRevisionFloor()` and the last progress sample for the current server. Capture the last known attempt ID and boot ID. Do this before creating the new state. Do not raise that revision baseline when the first response arrives: a fast commit must not become its own baseline.
2. Add `acceptedAttemptId`, `lastAcceptedProgress` and `dashCallbackCompletedAt` to `refreshProgressState`. Keep one active state. An ID different from the baseline is a candidate observed backend run, not proof this browser owns it. If the pre-click identity was unavailable or another browser could explain the change, label it as observed server work; do not assert this manual action ran.
3. Accept fresh progress only from the captured server boot. If no boot ID was known at click time, bind the first fresh successful sample as observed server context; do not retroactively claim ownership of that run. On a later boot change, discard old revision baselines/floors and use the existing reconnect/reload path. Do not compare old-process DOM revisions with a new process. Once an attempt ID is accepted, use that same ID for its stage details, error and terminal result. An idle response from another ID cannot finish it. Never rebind an already accepted attempt to a newer one merely to obtain a completion.
4. If the callback explicitly reports an existing writer, show `Following existing refresh`. Adopt the writer's confirmed running ID as a followed attempt; do not say that the requested manual refresh is queued or has run. If it finished before its identity could be established, show the callback's busy/not-started result instead of adopting an arbitrary idle sample.
5. A matching `running: true` means keep the hero active regardless of the Dash CSS class. Record `lastAcceptedProgress`. A different/unbound writer can be shown with a qualified message without overwriting this attempt's stage/error history.
6. A matching fresh terminal sample must have `running: false`, a terminal stage and `finished_at`. If its error is present, classify failure even when the text equals the previous failure. Do not use `initialErrorText` inequality as the deciding test.
7. To report a new server commit, also require a successful terminal sample and a revision greater than the fixed baseline. If no new revision is confirmed, say `No new revision confirmed`; do not automatically turn that into failure or success. An explicit no-work/coalesced callback may legitimately retain a revision. Keep operational warnings visible even if a snapshot committed.
8. A known rejection/busy result from this callback takes precedence over claiming that its requested work succeeded. Use the existing returned status/error content for that result, associated with the observed callback completion. An ambiguous class/text ordering is unconfirmed, not success; the class transition alone is never an acknowledgement.
9. Cached responses, transport failures, missing identities, old results and process changes cannot establish success. Preserve the pending attempt and last confirmed details, show the uncertainty and keep the hero visible. Do not finalize, clear state or enable an automatic retry because a poll failed or an idle response arrived. If the callback returned but its result cannot be matched, show “Refresh outcome unconfirmed”; require an explicit reconnect/check before a deliberate retry. Never discard still-pending view updates or automatically resubmit an outcome-unknown action.
10. Keep startup separate: require its explicit successful phase, positive committed revision, and accepted startup attempt/process identity. Preserve failure/stall/retry and server-restart recovery. Do not use a positive old revision to treat an ordinary warm refresh as completed startup.

The endpoint reads progress and committed health separately. Its `revision` is the server's current revision, not an immutable result attached to a particular browser action. Therefore the honest completion wording is `Server committed revision N` for the accepted observed work. It cannot prove that every requested setting from an unrelated/rejected action was applied. Do not attribute revision N to a specific attempt without matching callback evidence. Keep the callback's rejection and the committed controls visible.

This deliberately conservative approach can report `Unconfirmed` when very fast overlapping work overwrites the global progress before it is sampled. That is a known limitation, not a reason to display a false success. Only if the controlled tests show that ambiguity is frequent should a later change return a tiny per-action outcome captured inside the existing writer lock. Do not build that additional protocol as part of this first repair.

### 1.9 Route every progress and completion path through that rule

Keep one completion helper that receives the classification and advances the full-refresh phases in section 1.10. Backend completion advances to callback/view completion; it does not clear the active state. Apply these changes in `assets/s12_refresh.js` in order:

1. **`startRefreshProgress`:** replace its first forced-poll `.then(...)` branch's independent `belongsToAttempt`/revision/timestamp success inference with the classifier. Keep the initial revision baseline fixed. Do not accept an earlier global error as this request's error.
2. **`handleRefreshStatusTransition`:** keep its running-class tracking, and record `dashCallbackCompletedAt = Date.now()` when the callback ends. Remove the unconditional `finishRefreshProgress()` and the follower branch's `else if (progress)` completion. The end of the class should request fresh confirmation, not declare success.
3. **Fresh-fetch handling:** when confirmation is needed, let an existing `backendProgressRequest` settle before requesting again; require a successful fetch started after the confirmation boundary. Keep backoff and request deduplication. A response returned from the catch/cache path is not fresh confirmation. Do not stamp it with a new `requested_at`.
4. **`refreshProgressPoll`, progress-present branch:** classify before calling `renderBackendProgress` or finishing. Remove the fallback completion based on `sawRunning` or `statusChanged`, as well as revision-only and arbitrary-idle completion. Gating just the finalizer is insufficient if old progress can still paint green stages.
5. **`refreshProgressPoll`, progress-unavailable branch:** preserve reconnect/backoff and show `Progress unavailable; last confirmed ...`. Delete the success fallback based on a cleared spinner/CSS class. Do not cancel an active server job or retry the financial action because its status endpoint is unavailable.
6. **`recoverReadyBootstrap`:** tighten its ready decision to explicit startup success and the accepted startup/process identity. Preserve its existing one-reload/session guard and cold-layout handoff. A committed revision alone does not identify a completed new startup attempt.
7. **`syncRefreshLifecycleNodes`:** after reattachment, repaint from `lastAcceptedProgress` and the current classification. Extract only the DOM-paint portion of `startRefreshProgress` into a small `paintRefreshPanel(state)` helper shared by start and reattachment. Keep timer creation, requests and baseline capture outside that helper. This restores titles and mode-specific skipped stages without creating another attempt or trusting arbitrary global progress.
8. **Every remaining `finishRefreshProgress(` call:** successful finalization requires all three completion conditions in section 1.10. A backend `committed` classification alone must not call it. Keep rejection/failure results visible; an unconfirmed state remains visible and pending. A boolean named `backendConfirmed` is not sufficient.

| Evidence | Allowed display |
|---|---|
| Click sent; no confirmed work yet | Requested; waiting for server. |
| Accepted active writer progress | Running, with actual details; qualify foreign/unbound work. |
| Same observed attempt commits; refresh callback or view updates are pending | Server committed revision N — finishing refresh/updating displayed tables; hero stays active and visible. |
| Backend, refresh callback and required views all confirm completion | Refresh complete — revision N; completed hero stays visible. |
| Callback says busy | This action did not start; optionally follow the identified existing writer. |
| Callback rejects stale/invalid controls | Show the rejection and existing corrective action. |
| Accepted attempt fails | Show the current failure, even if its text repeats. |
| Same revision/no matching new work | No new revision confirmed; retain existing data. |
| Missing/old/mismatched progress | Unconfirmed; never green success. |
| Progress network failure | Status unavailable; never infer completion. |
| Server boot ID changed | Previous attempt interrupted/unconfirmed; use existing recovery. |

### 1.10 Wait for all refresh work before finalizing the hero

This step is required. Simply removing the 300 ms hide timer fixes the flash but does not prove that the work has finished.

#### A. Keep backend completion separate from callback completion

In `cube/services/s06_refresh.py`, the successful refresh currently calls `_finish_progress()` before writing its metrics and returning. In `cube/pages/risk/s15_refresh.py`, `refresh_pipeline` then still runs `synchronize_committed_dashboard`, builds status/settings outputs, and returns them to Dash. Therefore even a correct `running: false` progress sample can arrive before the complete action has returned.

In `assets/s12_refresh.js`, keep the same `refreshProgressState` when an accepted backend result is committed. Record its target revision and move to “Finishing refresh”. Wait for the initiating callback to settle as well. The observed start/end transition in `handleRefreshStatusTransition` is evidence about that callback only; combine it with the matching backend outcome, never use it alone. A fresh progress response requested after that callback ends helps exclude old in-flight samples. A remounted status node is not a callback-end acknowledgement.

Keep all work that belongs to a refresh inside the manager/callback's awaited execution. If a connector internally starts a thread/future and returns immediately, change that connector boundary to await/join its result before returning: the hero cannot infer unfinished private work from a returned DataFrame. If following another writer, confirm that writer's end rather than treating this browser's early busy response as its completion. Where current status cannot prove that, remain visibly unconfirmed.

#### B. Require completion of the visible results triggered by the refresh

Setting `data-revision-store` starts more work. For example, `reduce_and_render_risk_view` updates Risk tables/detail, and `risk-initial-render-ready` then triggers Aggregate P&L. The hero must stay active through that second callback too.

1. Before publishing the target revision to the UI, establish the small set of visible results this action will update. Do not let an initially empty set count as “all rendered” before that set is ready. Include active/open widgets; exclude closed lazy widgets and views that the action does not refresh.
2. Give each required renderer a separate small acknowledgement output, returned alongside its actual table/chart content. Use a distinct memory Store or wrapper attribute per owner; do not make several Python callbacks write one shared mutable map. The acknowledgement should identify the refresh/view request, the actual revision used, and `rendered` or `failed`. No financial rows belong in it.
3. Return success only with the actual result for the target revision, including a legitimate empty-state result. An exception returns a failed acknowledgement and visible error. `no_update`, an inactive branch, a query-store update, or a newly set revision value does not prove the table was rendered. Preserve every return tuple's Output order/arity.
4. Deliver the acknowledgement to one lifecycle handler in `assets/s12_refresh.js` through a clientside callback, or observe a revision attribute on the newly rendered wrapper. A `dcc.Store` is not a readable DOM element: do not use `document.getElementById(store_id).data`. When using a Store bridge, let Dash apply the associated content before acknowledging the mounted result; include Plotly's completed-render event for a graph whose drawing is still in flight. Do not acknowledge a figure merely because its Python dictionary was produced.
5. Accept acknowledgements only for the current action/view identity and its target revision. Ignore late responses from older requests. If newer work supersedes a pending view, explicitly replace that pending target and wait for the replacement; never use an unrelated newer revision as proof the old view completed.
6. Keep the finite participant list aligned with in-app navigation. Do not wait for a removed page to render nonexistent DOM. Explicitly retire its presentation target and track the refresh-dependent results on the newly mounted page; still wait for any action-owned backend/callback work already started. A short DOM-remount gap is not retirement, success or cancellation. While it is unresolved, preserve the hero and its pending state.

These are the existing owners to update when their results participate:

| Visible result | Existing callback and file |
|---|---|
| Risk main/alternate tables and selected detail | `reduce_and_render_risk_view`, `cube/pages/risk/s07_explorer.py` |
| Aggregate P&L on Risk | `reduce_and_render_aggregate_pl`, `cube/pages/risk/s14_workspacecallbacks.py` |
| Active Quick Risk result | `render_current_pivot`, `cube/pages/risk/s14_workspacecallbacks.py`; also `render_quick_risk_tenor` if the separate Quick Risk guide has been implemented |
| Active Quick Market result | `render_market_search`, `cube/pages/risk/s14_workspacecallbacks.py` |
| Active Top Promotions | `render_top_promotions`, `cube/pages/risk/s14_workspacecallbacks.py` |
| Open unmapped-books table | `render_unmapped_books`, `cube/pages/risk/s07_explorer.py` |
| Visible P&L summary updated by this action | `reduce_and_render_pl_summary`, `cube/pages/pnl/s08_aggregate.py` |
| Open P&L editors updated by this action | `control_editor` registered by `register_editor`, `cube/pages/pnl/s05_sendcallbacks.py` |

For a history-backed summary, acknowledge that its query/render for this refresh has finished; do not claim new historical observations were written. `render_inline_pl_history` in `cube/pages/pnl/s09_drilldown.py` does not ordinarily take a data-revision Input. Include it only if the actual action triggers it; do not create a permanent wait for a callback that will not run.

Keep `renderedDataRevisionFloor()` for its current publication/deduplication purpose. It takes the maximum of several revision signals. **One table reaching revision N cannot prove that every required table reached N.** Neither that maximum nor global `dashIsLoading()` is an all-results completion check.

#### C. Make the finalizer use the whole-refresh result

In `assets/s12_refresh.js`, guard successful `finishRefreshProgress(...)` with all of the following, evaluated together:

```text
matching backend result confirmed
AND initiating refresh callback settled
AND required-view set established
AND every required view acknowledged its target result
AND no required result failed or remains unconfirmed
```

While any condition is pending, do not set `refreshProgressState = null`, clear the elapsed timer, release the active refresh display, or mark 100%. Keep repainting the existing hero with “Finishing refresh” or “Updating displayed tables”. Keep the status check lightweight; do not poll full data frames or build another scheduler.

A confirmed failure/rejection is an error result, not successful completion. Leave the error visible, retain last-good financial data, and account for any still-running work before allowing a new action. A transport timeout only means status is unavailable; it does not mean the refresh finished or failed. Keep the same pending attempt and continue the existing bounded polling/backoff without automatically rerunning it.

Once the complete action has settled, clear its timer and active-work state, but retain its terminal display until the next refresh. Remove the success/failure auto-hide block entirely. If an earlier local patch added a tracked hide timer, cancel it on start/remount and remove the code that schedules it. Do not leave an old timeout capable of hiding a newer hero.

Preserve truthful stage information: remove both the finalizer's sweep that turns all stages green and `renderBackendProgress`'s automatic completion of every preceding stage (`index < activeIndex`). Unsampled stages are “Not observed”; use “Reused” only when that is known. After backend publication, say “Server committed revision N — updating displayed tables”. Use “Refresh complete — revision N” only after the full condition above passes. The completed hero still remains visible.

Keep the keyboard's `event.repeat` and disabled-button checks. In the delegated click handler in `assets/s13_risk.js`, replace only `if (refreshTrigger) {` with `if (refreshTrigger && !refreshTrigger.disabled) {`; keep its body unchanged. Keep one button/keyboard dispatch and do not disable the click target synchronously in the capture handler before Dash receives the event.

### 1.11 Make sure the P&L view is the one the action can refresh

There are different consumers in this app:

- `cube/pages/pnl/s05_sendcallbacks.py` includes a live sender/effective-query path driven by `data-revision-store`. That path should consume the newly committed live snapshot.
- `cube/pages/pnl/s08_aggregate.py`, `reduce_and_render_pl_summary`, reads `query_source.risk_summary` for the archive-based summary. A revision trigger can rerun that query without adding new archive observations.
- The history readers use their own stored observations. A live refresh does not automatically manufacture or rewrite a historical record.

Consequently, do not “fix” an unchanged historical Summary by forcing repeated live refreshes. Check the selected date, source and view. If you want intraday/live numbers on an archive summary, make that an explicit product change with a clearly labelled live overlay or a defined snapshot-writing process. Decide its date/key and duplicate policy; do not silently mix current observations into all historical dates.

For live P&L that remains stale after a proven commit, follow this path: manager committed revision → `refresh-commit-revision` and revision publication → `data-revision-store` → relevant P&L callback → query result/cache identity → visible table. Only change a cache if the trace shows it retained the old revision.

Use one known position/market input in a test adapter to verify that changing its Current value changes live P&L after one press. Keep a second case with unchanged Current values: the request should still be correctly acknowledged without promising a numerical change. Leave production risk and archive rows alone during this test.

### 1.12 Verification and restart, in order

These are acceptance checks for the implementation. They have **not** been run against your deployment or a completed implementation of the proposed completion classifier.

1. Check Python syntax for every edited `.py` file and JavaScript syntax for every edited asset. Check callback input/output counts, unique IDs and one writer per output. Syntax alone does not establish correct refresh behaviour.
2. Add focused tests of the classifier and warm-shell guard: current terminal success, repeated identical failure, stale response, busy/follower, missing identity and unchanged revision. Keep manager tests verifying manual forced work is not automatically coalesced and ordinary failure retains last-good data. No new DataFrame-return path is needed.
3. Start the app normally and hard-refresh the browser to load the changed assets. Verify cold startup on Risk and P&L, startup failure/retry, and server restart recovery.
4. Hold a fake connector until explicitly released. Press Shift+F9 once. Through at least three progress polls, the hero must remain visible without completion. Other refresh actions must not silently start duplicate work.
5. During that hold, replace/remount the hero or use in-app navigation away and back within the same document. Its attempt identity, elapsed time and last confirmed stage must survive; temporary absence of a DOM node must not cancel the backend or clear its state. Full browser navigation intentionally runs `pagehide` cleanup; on return, reconnect rather than promising the old local timer survives.
6. Deliver an old completed progress response that was requested before the click. It must not acknowledge the new request, colour all stages green or hide the hero.
7. Complete a run in less than one poll interval. Its fresh terminal attempt identity and advanced revision should confirm the observed server result without needing a second keypress. If another run overwrote the only global result, show unconfirmed instead of success; record that limitation for a targeted follow-up. A delayed old response must not overwrite the current attempt.
8. Use two sessions: while one owns the writer, send an action from the other. The second must explicitly report busy/not started. If following the first, it must not claim that its own requested settings/action ran.
9. Fail twice with exactly the same exception text. Both attempts must show failure and retain last-good data. Also test validation rejection before the manager starts.
10. Drop progress responses while work is held. Show “Progress unavailable”; never infer success from callback CSS, a timeout, or a cleared spinner. Restore the connection and accept only the right outcome.
11. Delay the final callback work after `_finish_progress`, then separately hold Aggregate P&L after Risk Explorer is ready, then hold an open P&L editor or graph render. In every case the hero must remain visible and active until the last required result finishes. Completing only the backend or first table must not call the finalizer. Never roll `data-revision-store` back because an older response arrived.
12. Test one shortcut press and one separate button click with changed and unchanged Current inputs. Test archived Summary separately. Record the request count, result and revision for each case.
13. Check Commo, Reload Risk, Portfolio refresh, Apply dates, Clear Cache and automatic refresh once each. Keep automatic coalescing and existing committed settings/reset protections.
14. After success, wait longer than the former hide delay: the completed hero must remain visible. Start another refresh before an old hide timer would have fired; that timer must not hide the new attempt. Test that a missing render acknowledgement remains visibly pending and a render failure remains visibly failed. Ongoing progress/automatic-refresh intervals must not keep an otherwise finished action active.
15. After these checks pass, deploy the coordinated application changes together and repeat the single-press production observation without altering financial inputs. If rolling back, restore the edited files from the same backup. This Markdown-only commit does not require an app restart by itself.

### 1.13 What to avoid, and why

Do not solve a misleading progress display by fetching all 100,000 Risk rows again, clearing all caches, extending a spinner delay, disabling single-writer protection or sending repeated shortcut clicks. Those changes increase work or hide symptoms without proving success.

The existing attempt ID answers “Which server run is this progress describing?” The revision answers “Has the server published newer data?” Use those small fields instead of keeping another copy of the Risk table. Where they cannot establish the requested action's result, show that uncertainty. Keep one progress endpoint and the existing revision signal for table updates.

### 1.14 Source references and limits of this review

All references below are pinned to the inspected commit so the findings remain checkable after `v7` moves:

- [Hero lifecycle and progress polling](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/assets/s12_refresh.js).
- [Keyboard/button handlers](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/assets/s13_risk.js).
- [Refresh and startup-shell callbacks](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/risk/s15_refresh.py).
- [Manager refresh, commit and existing metrics](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/services/s06_refresh.py).
- [Progress identity and completion state](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/services/s02_state.py) and [progress endpoint payload](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/app/s05_progress.py).
- [Live P&L callback path](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/pnl/s05_sendcallbacks.py) and [archive summary path](https://github.com/streamlitdash/Rebirth-V5/blob/2220a3f4839318863a9131e3fef8118d0f82fb7d/cube/pages/pnl/s08_aggregate.py).

Verified here: source inspection, four current-source mocked-DOM probes and three Python source probes, and publication of this independent guide. This follow-up also traced backend completion through refresh callback return and downstream Risk/P&L rendering. Not verified here: the production root cause of every missed refresh, live adapter freshness, the proposed render-acknowledgement implementation, or successful deployment of the application changes.
