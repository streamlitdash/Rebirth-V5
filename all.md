# all — refresh reliability, Portfolio and Data

Updated 10 September 2026. Repository: `streamlitdash/Rebirth-V5`, branch `v6`.

This is an implementation guide, not an application patch. Publishing this file does **not** change the running app. The new investigation below was made against commit `335bdce6453b7544d4eac436b7094f35c14864c6`. Check your deployed files before applying it: a manually edited JupyterHub deployment may differ from GitHub.

## Reading order and which instructions apply

1. **Chapter 1: refresh hero and Shift+F9.** This is the new work. It replaces the earlier Commo-only hero advice and covers ordinary P&L, Commo, Risk reload and other refresh actions. The small DOM fixes include exact replacement snippets; the completion changes are an ordered implementation specification, not a tested, complete drop-in patch.
2. **Chapter 2: Portfolio.** Preserved from the previous `all.md`. Keep changes already installed; do not apply them twice.
3. **Chapter 3: independent Data page.** Preserved from the previous `all.md` for its earlier dropdown layout. Use it only where the shown old code still matches. Do not revert an already unified Data page to this layout.
4. **Chapter 4: Data interaction repair.** Previously `DATA_INTERACTION_FIX.md`. This requires the already unified Risk / Market / Both page with `edit_workspace` and thirteen outputs. Chapter 3 alone does not create that interface. If you have the unified page, keep it and apply Chapter 4; do not also paste Chapter 3's old selector.
5. **Appendix: earlier Commo-only hero guide.** Retained for comparison, not for implementation. Do not apply it on top of Chapter 1.

The previous two Markdown files have been consolidated here. Their Portfolio, Data and Data-interaction implementation instructions remain available. The new publication changes documentation only; it does not add a framework, queue, database or financial data restriction.

## 1. Refresh hero disappears; Shift+F9 appears to need several attempts

### 1.1 What is happening, in plain English

There are three separate events:

1. Your button or Shift+F9 asks the server to refresh.
2. The server fetches the required data, calculates P&L and publishes a validated snapshot.
3. The browser redraws the tables from that snapshot.

The current hero sometimes treats the end of the browser callback as proof that all three happened. It is not proof. A callback can finish because the request was rejected, another refresh already owns the writer, or the UI changed. Separately, replacing the hero's HTML can make the browser forget the active display while Python continues working.

That explains how “running on the server” and “no hero visible” can coexist. It also explains a false-looking flash of green ticks. It does **not** establish that every first or second keypress in your deployment is lost; that requires the single-press check in section 1.3.

The intended behaviour is: **one press, one request; a visible and truthful status; success only when publication is confirmed.** A successful refresh can legitimately produce the same P&L if the input prices did not change.

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

The core changes belong in `cube/pages/risk/s15_refresh.py` and `assets/s12_refresh.js`. `assets/s13_risk.js` needs only a small trigger guard. Keep the existing server callback signatures and stores for this initial repair. Sections 1.8–1.9 consolidate the browser's completion decisions using metadata already available.

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

This keeps a repeated click from resetting the visible attempt. It is a UI guard, not a replacement for the server writer lock. Keep actual page teardown in `stopRefreshLifecycle()`/the `pagehide` handler.

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

Its job is to return `running`, `committed`, `failed`, `unconfirmed` or `ignored`, together with the accepted progress. This section specifies the implementation logic; it is not a fully written drop-in JavaScript function.

Implement its state and rules in this order:

1. At click time, capture `baselineRevision` as the maximum valid revision from `refresh-commit-revision`, `renderedDataRevisionFloor()` and the last progress sample for the current server. Capture the last known attempt ID and boot ID. Do this before creating the new state. Do not raise that revision baseline when the first response arrives: a fast commit must not become its own baseline.
2. Add `acceptedAttemptId`, `lastAcceptedProgress` and `dashCallbackCompletedAt` to `refreshProgressState`. Keep one active state. An ID different from the baseline is a candidate observed backend run, not proof this browser owns it. If the pre-click identity was unavailable or another browser could explain the change, label it as observed server work; do not assert this manual action ran.
3. Accept fresh progress only from the captured server boot. If no boot ID was known at click time, bind the first fresh successful sample as observed server context; do not retroactively claim ownership of that run. On a later boot change, discard old revision baselines/floors and use the existing reconnect/reload path. Do not compare old-process DOM revisions with a new process. Once an attempt ID is accepted, use that same ID for its stage details, error and terminal result. An idle response from another ID cannot finish it. Never rebind an already accepted attempt to a newer one merely to obtain a completion.
4. If the callback explicitly reports an existing writer, show `Following existing refresh`. Adopt the writer's confirmed running ID as a followed attempt; do not say that the requested manual refresh is queued or has run. If it finished before its identity could be established, show the callback's busy/not-started result instead of adopting an arbitrary idle sample.
5. A matching `running: true` means keep the hero active regardless of the Dash CSS class. Record `lastAcceptedProgress`. A different/unbound writer can be shown with a qualified message without overwriting this attempt's stage/error history.
6. A matching fresh terminal sample must have `running: false`, a terminal stage and `finished_at`. If its error is present, classify failure even when the text equals the previous failure. Do not use `initialErrorText` inequality as the deciding test.
7. To report a new server commit, also require a successful terminal sample and a revision greater than the fixed baseline. If no new revision is confirmed, say `No new revision confirmed`; do not automatically turn that into failure or success. An explicit no-work/coalesced callback may legitimately retain a revision. Keep operational warnings visible even if a snapshot committed.
8. A known rejection/busy result from this callback takes precedence over claiming that its requested work succeeded. Use the existing returned status/error content for that result, associated with the observed callback completion. An ambiguous class/text ordering is unconfirmed, not success; the class transition alone is never an acknowledgement.
9. Cached responses, transport failures, missing identities, old results and process changes cannot establish success. Preserve last confirmed details, show the uncertainty and keep polling while an identified writer is active. After the callback has returned and a fresh sample confirms no active writer but no matching new work, show an unconfirmed terminal result and allow a deliberate retry. Do not automatically resubmit an outcome-unknown action.
10. Keep startup separate: require its explicit successful phase, positive committed revision, and accepted startup attempt/process identity. Preserve failure/stall/retry and server-restart recovery. Do not use a positive old revision to treat an ordinary warm refresh as completed startup.

The endpoint reads progress and committed health separately. Its `revision` is the server's current revision, not an immutable result attached to a particular browser action. Therefore the honest completion wording is `Server committed revision N` for the accepted observed work. It cannot prove that every requested setting from an unrelated/rejected action was applied. Do not attribute revision N to a specific attempt without matching callback evidence. Keep the callback's rejection and the committed controls visible.

This deliberately conservative approach can report `Unconfirmed` when very fast overlapping work overwrites the global progress before it is sampled. That is a known limitation, not a reason to display a false success. Only if the controlled tests show that ambiguity is frequent should a later change return a tiny per-action outcome captured inside the existing writer lock. Do not build that additional protocol as part of this first repair.

### 1.9 Route every progress and completion path through that rule

Keep one completion helper that receives the classification and renders its result. Apply these changes in `assets/s12_refresh.js` in order:

1. **`startRefreshProgress`:** replace its first forced-poll `.then(...)` branch's independent `belongsToAttempt`/revision/timestamp success inference with the classifier. Keep the initial revision baseline fixed. Do not accept an earlier global error as this request's error.
2. **`handleRefreshStatusTransition`:** keep its running-class tracking, and record `dashCallbackCompletedAt = Date.now()` when the callback ends. Remove the unconditional `finishRefreshProgress()` and the follower branch's `else if (progress)` completion. The end of the class should request fresh confirmation, not declare success.
3. **Fresh-fetch handling:** when confirmation is needed, let an existing `backendProgressRequest` settle before requesting again; require a successful fetch started after the confirmation boundary. Keep backoff and request deduplication. A response returned from the catch/cache path is not fresh confirmation. Do not stamp it with a new `requested_at`.
4. **`refreshProgressPoll`, progress-present branch:** classify before calling `renderBackendProgress` or finishing. Remove the fallback completion based on `sawRunning` or `statusChanged`, as well as revision-only and arbitrary-idle completion. Gating just the finalizer is insufficient if old progress can still paint green stages.
5. **`refreshProgressPoll`, progress-unavailable branch:** preserve reconnect/backoff and show `Progress unavailable; last confirmed ...`. Delete the success fallback based on a cleared spinner/CSS class. Do not cancel an active server job or retry the financial action because its status endpoint is unavailable.
6. **`recoverReadyBootstrap`:** tighten its ready decision to explicit startup success and the accepted startup/process identity. Preserve its existing one-reload/session guard and cold-layout handoff. A committed revision alone does not identify a completed new startup attempt.
7. **`syncRefreshLifecycleNodes`:** after reattachment, repaint from `lastAcceptedProgress` and the current classification. Extract only the DOM-paint portion of `startRefreshProgress` into a small `paintRefreshPanel(state)` helper shared by start and reattachment. Keep timer creation, requests and baseline capture outside that helper. This restores titles and mode-specific skipped stages without creating another attempt or trusting arbitrary global progress.
8. **Every remaining `finishRefreshProgress(` call:** require an explicit classified terminal result. Keep unconfirmed/rejected/busy outcomes visually distinct from committed success. A boolean named `backendConfirmed` is not enough if a caller can set it for any idle object.

| Evidence | Allowed display |
|---|---|
| Click sent; no confirmed work yet | Requested; waiting for server. |
| Accepted active writer progress | Running, with actual details; qualify foreign/unbound work. |
| Same observed attempt completes successfully and server revision advances | Server committed revision N. |
| Callback says busy | This action did not start; optionally follow the identified existing writer. |
| Callback rejects stale/invalid controls | Show the rejection and existing corrective action. |
| Accepted attempt fails | Show the current failure, even if its text repeats. |
| Same revision/no matching new work | No new revision confirmed; retain existing data. |
| Missing/old/mismatched progress | Unconfirmed; never green success. |
| Progress network failure | Status unavailable; never infer completion. |
| Server boot ID changed | Previous attempt interrupted/unconfirmed; use existing recovery. |

### 1.10 Make the final display useful rather than a flash

In `finishRefreshProgress`, take the classified terminal result as an argument. Replace `hasNewError` based on `errorText !== initialErrorText` with that result's classification/error. Treat an unconfirmed result, callback rejection/busy result, failure and confirmed server commit separately; absence of a new error string does not equal success.

Remove the loop that turns every unskipped stage green. Also amend `renderBackendProgress`: its `if (index < activeIndex)` branch currently marks all preceding stages complete. Preserve actual accepted stage observations instead of automatically completing unsampled earlier stages. Preserve stages actually confirmed by accepted progress. When a fast run is not sampled at every stage, leave those stage details as “Not observed” rather than inventing per-stage ticks; the accepted terminal result still confirms the overall server result. Use “Reused” only when reuse is known from the backend; do not infer it merely because a stage was not sampled. Do not show 100% for an unknown or rejected request.

Replace “Validated snapshot is live” with “Server committed revision N” for a committed outcome. Keep the revision publication through `syncCommittedDataRevision`, including its page-consumer and stale-revision protections. If the tables are still rendering, say “Updating displayed tables.” Do not claim the visible figures are on revision N until the relevant table render has confirmed it; a generic Dash loading flag is not a revision-specific acknowledgement.

Remove the success/failure auto-hide timeout at the end of `finishRefreshProgress`. Keep the terminal result visible until the next refresh. This needs no new close button. Keep clearing the elapsed interval and releasing the active loading indicator on a real terminal result. Next refresh replaces the displayed outcome through the existing start function.

Keep the keyboard's `event.repeat` and disabled-button checks. In the delegated refresh-click handler, ignore a disabled trigger before opening the hero. Keep the existing button dispatch: do not add a second keyboard-specific refresh, `.click()` three times, or a timer that retries financial actions automatically. In `assets/s13_risk.js`, replace only `if (refreshTrigger) {` with `if (refreshTrigger && !refreshTrigger.disabled) {`; keep its body unchanged.

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
11. Delay table rendering after a valid commit. Distinguish “server committed” from “tables updated”; never roll `data-revision-store` back because an older response arrived.
12. Test one shortcut press and one separate button click with changed and unchanged Current inputs. Test archived Summary separately. Record the request count, result and revision for each case.
13. Check Commo, Reload Risk, Portfolio refresh, Apply dates, Clear Cache and automatic refresh once each. Keep automatic coalescing and existing committed settings/reset protections.
14. After these checks pass, deploy the coordinated application changes together and repeat the single-press production observation without altering financial inputs. If rolling back, restore the edited files from the same backup. This Markdown-only commit does not require an app restart by itself.

### 1.13 What to avoid, and why

Do not solve a misleading progress display by fetching all 100,000 Risk rows again, clearing all caches, extending a spinner delay, disabling single-writer protection or sending repeated shortcut clicks. Those changes increase work or hide symptoms without proving success.

The existing attempt ID answers “Which server run is this progress describing?” The revision answers “Has the server published newer data?” Use those small fields instead of keeping another copy of the Risk table. Where they cannot establish the requested action's result, show that uncertainty. Keep one progress endpoint and the existing revision signal for table updates.

### 1.14 Source references and limits of this review

All references below are pinned to the inspected commit so the findings remain checkable after `v6` moves:

- [Hero lifecycle and progress polling](https://github.com/streamlitdash/Rebirth-V5/blob/335bdce6453b7544d4eac436b7094f35c14864c6/assets/s12_refresh.js).
- [Keyboard/button handlers](https://github.com/streamlitdash/Rebirth-V5/blob/335bdce6453b7544d4eac436b7094f35c14864c6/assets/s13_risk.js).
- [Refresh and startup-shell callbacks](https://github.com/streamlitdash/Rebirth-V5/blob/335bdce6453b7544d4eac436b7094f35c14864c6/cube/pages/risk/s15_refresh.py).
- [Manager refresh, commit and existing metrics](https://github.com/streamlitdash/Rebirth-V5/blob/335bdce6453b7544d4eac436b7094f35c14864c6/cube/services/s06_refresh.py).
- [Progress identity and completion state](https://github.com/streamlitdash/Rebirth-V5/blob/335bdce6453b7544d4eac436b7094f35c14864c6/cube/services/s02_state.py) and [progress endpoint payload](https://github.com/streamlitdash/Rebirth-V5/blob/335bdce6453b7544d4eac436b7094f35c14864c6/cube/app/s05_progress.py).
- [Live P&L callback path](https://github.com/streamlitdash/Rebirth-V5/blob/335bdce6453b7544d4eac436b7094f35c14864c6/cube/pages/pnl/s05_sendcallbacks.py) and [archive summary path](https://github.com/streamlitdash/Rebirth-V5/blob/335bdce6453b7544d4eac436b7094f35c14864c6/cube/pages/pnl/s08_aggregate.py).

Verified here: source inspection, four current-source mocked-DOM probes and three Python source probes, and consolidation/publication of this guide. Not verified here: the production root cause of every missed refresh, live adapter freshness, or successful deployment of the proposed application changes.

---


The following application instructions are preserved from the two documents that were on `v6` before this update. Their code blocks are unchanged. Their preconditions still matter: an older selector and the unified `edit_workspace` selector are different interfaces, so choose the matching Data instructions rather than applying both blindly.

## Preparation for the retained Portfolio and Data instructions

1. Stop the running application.
2. In the JupyterHub file browser, open the application folder containing `app.py`, `assets` and `cube`.
3. Create a folder called `manual-backup` alongside `assets` and `cube`. If that name already exists, use a new name. Keep it outside `assets` so the app does not load backup JavaScript.
4. Copy each existing file below into that backup, keeping its folder structure. Files marked **Add new file** have no original to copy.
5. Make every replacement in its numbered order. Search for the shown text or function name. Keep everything outside the specified block. If an old block is missing or occurs more than once, stop that edit and check the file; do not guess or duplicate a callback.

| Application file | Action |
|---|---|
| `assets/s12_refresh.js` | Edit existing file |
| `cube/ui/s01_constants.py` | Edit existing file |
| `cube/ui/s02_aggregation.py` | Edit existing file |
| `cube/pages/risk/s06_explorertables.py` | Edit existing file |
| `cube/pages/risk/s02_state.py` | Edit existing file |
| `cube/pages/risk/s01_common.py` | Edit existing file |
| `cube/pages/risk/s16_view.py` | Edit existing file |
| `cube/services/s02_state.py` | Edit existing file |
| `cube/app/s02_contracts.py` | Edit existing file |
| `cube/history/s06_repository.py` | Edit existing file |
| `cube/pages/data/s03_callbacks.py` | Edit existing file |
| `cube/pages/data/s02_view.py` | Edit existing file |
| `cube/app/s07_factory.py` | Edit existing file |

Leave the connectors, source data, archives and financial calculation rules in place.

## 2. Add Portfolio to Risk Explorer

This uses the Portfolio column already present in the current risk data. It adds a searchable, multiple-selection Portfolio filter and a Portfolio choice beside Product, Activity and the other Explorer dimensions. No connector or market-data change is needed.

All three pages should offer these five filters: **Activity, Signoff Group, Portfolio, Category and Sub Category**.

| Page | Starting code | Action in this chapter |
|---|---|---|
| Risk | Four visible filters; Portfolio is excluded | Add Portfolio as the fifth filter |
| Stock | All five filters are already built | Keep its existing Portfolio filter |
| P&L | All five filters are already built | Keep its existing Portfolio filter |

The filters are inside each page's **Saved views** section. Each page keeps its own applied selection. The extra Portfolio grouping choice described below is a separate Risk Explorer feature.

With **Cross → Dimension: Portfolio**, Portfolio replaces Activity as the final hierarchy level, after the existing tenor and Split levels. It is not inserted above every underlying. Expand a branch to see its books; parent values still sum all positions within the applied filters. Activity remains the default dimension.

With **SplitVA → Dimension: Portfolio**, selected portfolios become columns. More than 20 matching portfolios produces a message asking you to use Cross or narrow the Portfolio filter. This is a display-width limit, not a data-loading limit.

Apply every step below before restarting the app. Keep the existing lazy expansion condition `if can_expand and is_open:` in `build_tree_rows`; do not generate closed branches or expand all branches on startup. Keep all raw risk rows, quote keys, market joins, reduced-tenor logic and connector code.

### 2.1. Register Portfolio as a selectable dimension

File: `cube/ui/s01_constants.py`.

Replace this entire block. Keep the existing Portfolio field; do not add another field to the connector schema.

Find:

```python
    # Stock and P&L still use Portfolio as a filter. Risk deliberately keeps
    # this shared saved-view field internal and aggregates across it.
    roles=frozenset({"filter_dimension"}),
```

Replace with:

```python
    roles=frozenset({"filter_dimension", "view_dimension"}),
```

### 2.2. Include that field in the dimension list

File: `cube/ui/s01_constants.py`.

Replace this assignment. Product and the existing dimensions remain available, and Activity remains the default.

Find:

```python
VIEW_DIMENSION_FIELDS = tuple(
    field for field in PORTFOLIO_FIELDS if "view_dimension" in field.roles
)
```

Replace with:

```python
VIEW_DIMENSION_FIELDS = tuple(
    field
    for field in (*PORTFOLIO_FIELDS, PORTFOLIO_UI_FIELD)
    if "view_dimension" in field.roles
)
```

### 2.3. Enable the existing Portfolio filter on Risk

File: `cube/ui/s01_constants.py`.

Replace this assignment. The existing layout and callbacks already build their controls from this list, so do not add a separate dropdown or callback.

Find:

```python
RISK_FILTER_DIMENSION_FIELDS = tuple(
    field for field in FILTER_DIMENSION_FIELDS if field.key != "portfolio"
)
```

Replace with:

```python
RISK_FILTER_DIMENSION_FIELDS = FILTER_DIMENSION_FIELDS
```

### 2.4. Remove the duplicate Portfolio preparation

File: `cube/ui/s02_aggregation.py`.

Portfolio is now handled by the existing `for column in FILTER_COLUMNS` loop immediately above. Delete only the following block; keep that loop.

Find:

```python
    # Portfolio remains part of the prepared position data for P&L, Stock,
    # history, and diagnostics even though Risk has no Portfolio filter or
    # grouping. Keep its historical string contract (including named books).
    if "portfolio" not in frame:
        frame["portfolio"] = "Unspecified"
    else:
        frame["portfolio"] = frame["portfolio"].fillna("Unspecified").astype(str)
```

Remove that block entirely. Add nothing in its place.

### 2.5. Keep exactly one Portfolio column in the prepared frame

File: `cube/ui/s02_aggregation.py`.

Near the end of `prepare_risk_data`, replace this part of the returned column list. `VIEW_DIMENSIONS` now contains `portfolio`; leaving the explicit line creates duplicate column names and can break pandas operations. This removes a repeated column selection, not Portfolio data.

Find:

```python
            # P&L and history reuse this prepared frame and still require the
            # position identity. Risk has no Portfolio control or grouping,
            # so its table group-bys aggregate across this retained column.
            "portfolio",
            *VIEW_DIMENSIONS,
```

Replace with:

```python
            *VIEW_DIMENSIONS,
```

### 2.6. Let the row hierarchy use the selected dimension

File: `cube/pages/risk/s06_explorertables.py`.

Replace the whole `_active_groups_for_frame` function, stopping before `def metric_class`. All required names are already imported in this file.

Find the function starting with:

```python
def _active_groups_for_frame(
```

Replace with:

```python
def _active_groups_for_frame(
    frame: pd.DataFrame,
    promotion_enabled: bool,
    region_enabled: bool,
    underlying_identity_mode: str = "reported",
    dimension: str | None = None,
) -> list[str]:
    """Resolve the existing hierarchy and its final reporting dimension."""
    region_available = bool(
        "region" in frame
        and frame["region"].fillna("").astype(str).str.strip().ne("").any()
    )
    identity_group = (
        "underlying"
        if str(underlying_identity_mode).strip().casefold() == "underlying"
        else "reported underlying"
    )
    groups = [
        group
        for group in get_active_groups(
            promotion_enabled,
            region_enabled,
            region_available=region_available,
        )
        if group not in {"reported underlying", "underlying"} or group == identity_group
    ]
    if dimension is not None:
        groups[-1] = selected_dimension(dimension)
    return groups
```

### 2.7. Pass the dimension into the Cross hierarchy

File: `cube/pages/risk/s06_explorertables.py`.

Inside `build_risk_table` only, replace this block. Keep `HierarchyAggregationIndex`, which already sums positions separately from distinct market quotes.

Find:

```python
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                    underlying_identity_mode,
                ),
                toggle_type=toggle_type,
```

Replace with:

```python
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                    underlying_identity_mode,
                    dimension=dimension,
                ),
                toggle_type=toggle_type,
```

### 2.8. Avoid a 400-column Portfolio pivot

File: `cube/pages/risk/s06_explorertables.py`.

Inside `build_alt_risk_table`, replace the following block with the version below. The check runs before building any cells. It limits only the width of the Portfolio SplitVA display; Cross and the Portfolio filter can still use every portfolio and all source rows.

Find:

```python
    dimension_values = (
        ordered_unique(frame, dimension_column) if not frame.empty else []
    )

    def dimension_cells
```

Replace with:

```python
    dimension_values = (
        ordered_unique(frame, dimension_column) if not frame.empty else []
    )
    if dimension_column == "portfolio" and len(dimension_values) > 20:
        return html.Div(
            [
                html.Strong("Too many portfolio columns for SplitVA"),
                html.Span(
                    "Use Cross to explore all portfolios, or choose at most "
                    "20 portfolios in Filter View and click Apply filters."
                ),
            ],
            className="empty-state",
            role="status",
        )

    def dimension_cells
```

### 2.9. Keep the pivot dimension out of the SplitVA row hierarchy

File: `cube/pages/risk/s06_explorertables.py`.

Still inside `build_alt_risk_table`, replace this block. `[:-1]` removes the final Activity row level, since this view already shows the selected dimension as columns.

Find:

```python
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                    underlying_identity_mode,
                ),
                cell_builder=dimension_cells,
```

Replace with:

```python
                groups=_active_groups_for_frame(
                    frame,
                    promotion_enabled,
                    region_enabled,
                    underlying_identity_mode,
                )[:-1],
                cell_builder=dimension_cells,
```

### 2.10. Pass the dimension into Credit Multi too

File: `cube/pages/risk/s06_explorertables.py`.

Inside `build_credit_multi_table`, replace this block. The Credit measure columns stay unchanged; Portfolio becomes the final row level when selected.

Find:

```python
            groups=_active_groups_for_frame(
                frame,
                promotion_enabled,
                region_enabled,
                underlying_identity_mode,
            ),
            cell_builder=measure_cells,
```

Replace with:

```python
            groups=_active_groups_for_frame(
                frame,
                promotion_enabled,
                region_enabled,
                underlying_identity_mode,
                dimension=dimension,
            ),
            cell_builder=measure_cells,
```

### 2.11. Stop retaining 24 full HTML table versions

File: `cube/pages/risk/s02_state.py`.

Inside `_RiskDataCache`, replace the whole `rendered` method, stopping before `def _next_counter`. Keep the method name and arguments so its callers do not change. The existing prepared and filtered data caches remain. This rebuilds the requested visible table when needed, with one build at a time; it does not retain previous expanded HTML trees.

Find the method starting with:

```python
    def rendered(self, key: str, build: Callable[[], Any]) -> Any:
```

Replace with:

```python
    def rendered(self, key: str, build: Callable[[], Any]) -> Any:
        """Build the visible table without retaining prior component trees."""
        with self._render_compute_lock:
            return build()
```

### 2.12. Remove the unused HTML-cache field

File: `cube/pages/risk/s02_state.py`.

Inside `_RiskDataCache.__init__`, delete only this line. Keep `_filtered`, `_filtered_bytes` and `_render_compute_lock`.

Find:

```python
        self._rendered: OrderedDict[str, Any] = OrderedDict()
```

Remove that block entirely. Add nothing in its place.

### 2.13. Remove HTML-cache clearing from revision replacement

File: `cube/pages/risk/s02_state.py`.

Inside `replace_frame`, replace this short block. Keep the surrounding code and the other cache invalidation.

Find:

```python
                self._rendered.clear()
                self._promotion_generations.clear()
                self._reduced_frames.clear()
                self._market_quote_revision = None
                self._market_quotes = None
                return prepared
```

Replace with:

```python
                self._promotion_generations.clear()
                self._reduced_frames.clear()
                self._market_quote_revision = None
                self._market_quotes = None
                return prepared
```

### 2.14. Remove the other HTML-cache clearing line

File: `cube/pages/risk/s02_state.py`.

Inside `clear_reconstructable`, delete only this line. It is now the only remaining occurrence. Do not delete `_UNSET`; unrelated date controls still use it.

Find:

```python
                self._rendered.clear()
```

Remove that block entirely. Add nothing in its place.

### 2.15. Update the filter explanation shown on the page

File: `cube/pages/risk/s01_common.py`.

Inside `RISK_FILTER_NOTE`, replace these strings so the page describes the new controls correctly.

Find:

```python
    "values. Risk is aggregated across Portfolio; Stock and P&L keep their "
    "own Portfolio filters."
```

Replace with:

```python
    "values. Portfolio filters Risk Explorer, Aggregate P&L and Quick Risk. "
    "Click Apply filters to use your selection. Stock and P&L keep their "
    "own Portfolio filters."
```

### 2.16. Keep the new grouping choice in Risk Explorer

File: `cube/pages/risk/s16_view.py`.

Inside the `dcc.RadioItems` whose ID is `aggregate-pl-dimension`, replace this block. This preserves the existing Aggregate P&L dimension choices; the Explorer control with ID `table-dimension` keeps the complete list, including Portfolio. The shared Portfolio filter still applies to Aggregate P&L and Quick Risk.

Find:

```python
                                                    id="aggregate-pl-dimension",
                                                    options=view_dimension_options,
```

Replace with:

```python
                                                    id="aggregate-pl-dimension",
                                                    options=[
                                                        option
                                                        for option in view_dimension_options
                                                        if option["value"] != "portfolio"
                                                    ],
```

### 2.17. Use the Portfolio controls after the final restart

1. Open Risk's **Saved views**, type a known book into **Portfolio**, select it, and press **Apply filters**. Choosing a value only edits the draft until you apply it.
2. Open **Risk explorer → Cross** and choose **Portfolio** under **Dimension**. Open one underlying through its tenor and Split levels. The final rows should be portfolios rather than Activity values. A Spot or unused tenor axis may be skipped, as before.
3. Apply two books that share an underlying and tenor. Their Risk, dRisk and P&L must add to the corresponding parent within the same Greek. Open, Current and Move remain quote values, not sums multiplied by two books. A missing quote stays unavailable.
4. Clear only the Portfolio selection and press **Apply filters**. Broader totals should return, subject to your other active filters. Clearing Portfolio does not clear Activity or category filters.
5. Choose **SplitVA → Portfolio**. With at most 20 matching books, each book should have a column and a Total column should remain. With more than 20, the explanatory message should appear. Use Cross to explore all 300–400 books.
6. Check **Credit → Multi** with Portfolio selected; its final row level should also be Portfolio. Switch back to Activity to recover the original final grouping.
7. Close and reopen a few branches. Closed children should disappear and return with the same figures. The existing prepared/filtered data cache remains, so this does not reread connectors on every click.

There is no source-row cap in this change. It removes the repeated HTML retention and avoids a 400-column pivot, but opening a very large number of branches at once still creates a large page. It cannot guarantee that an unknown server memory allowance will accommodate every expansion of 100,000 rows.

### 2.18. Keep and check the fifth filter on Stock and P&L

1. Open `cube/pages/stock/s01_data.py`. Keep this existing assignment unchanged:

   ```python
   STOCK_FILTER_FIELDS = FILTER_DIMENSION_FIELDS
   ```

2. Open `cube/pages/pnl/s01_common.py`. Keep this existing assignment unchanged:

   ```python
   PL_FILTER_FIELDS = FILTER_DIMENSION_FIELDS
   ```

3. Keep the existing `for field in STOCK_FILTER_FIELDS` loop in `build_stock_filter_bar` in `cube/pages/stock/s03_view.py`, and the `for field in PL_FILTER_FIELDS` loop in `build_pl_filter_bar` in `cube/pages/pnl/s07_view.py`. These already build all five dropdowns from the shared list. Keep their existing callbacks and component IDs: `stock-portfolio-filter` and `pnl-portfolio-filter`. Add no duplicate dropdown or callback.
4. After the final restart, open **Saved views** on Stock. Confirm all five filter labels appear, select a known Portfolio, and press **Apply filters**. Its displayed positions should follow that Portfolio selection. Clear Portfolio and apply again to restore the broader view within the other active filters.
5. Repeat on the P&L page. Its P&L view should follow its own applied Portfolio selection. This is the page's main Portfolio filter, separate from any Portfolio selector inside the sending controls.
6. Return to Risk and confirm its fifth filter is also present. Changing the Stock or P&L selection should not silently change Risk's selection.

## 3. Make Data work on its own with a searchable, scrollable dropdown

Keep the existing Risk History and Market History tabs, period controls, charts, playback and Load history button. The same page will work when opened directly. Quick Risk and Quick Market still prefill the selection, and you can then select something else.

The current code builds dropdown choices only from completed archives. This change also uses the already committed current identities and loads current data even when no archive exists. Current Market uses its real committed Market Date, as the final observation in this current view; it is not relabelled with the computer date. Risk uses each source’s actual Risk Date. Custom periods still exclude observations outside the selected range.

Apply the steps below in order. Paths are relative to the folder containing `app.py`.

### 3.1. Add two read methods to the refresh manager

Open `cube/services/s02_state.py`.

Insert these methods immediately above `def combine_udl_options`. Keep that existing method and all methods below it. These reads use committed data; they do not call connectors or copy every table.



Add this code, indented at the same level as the other methods:

```python
    def data_history_identities(self) -> tuple[ResolvedHistoryIdentity, ...]:
        """Read compact Data choices from one committed search catalog."""
        with self._state_lock:
            catalog = self._search_catalog
        if catalog is None:
            return ()
        identities = []
        for kind, mode in (
            ("risk", "reported"), ("risk", "underlying"), ("market", "underlying")
        ):
            labels = (
                catalog.market_udl_options()
                if kind == "market"
                else catalog.combine_udl_options(identity_mode=mode)
            )
            for label in labels:
                identities.append(catalog.resolve_history_identity(
                    kind, label, identity_mode=mode
                ))
        return tuple(identities)

    def read_data_history(self, handoff) -> tuple[int, pd.DataFrame]:
        """Copy only the selected current identity from one committed snapshot."""
        with self._state_lock:
            committed = self._snapshot
        if committed is None:
            return 0, pd.DataFrame()
        identity = handoff.identity
        frame = (
            committed.dashboard_frame if handoff.kind == "risk"
            else committed.market_frame
        )
        column = (
            "Reported Underlying" if identity.identity_mode == "reported"
            else "Underlying"
        )
        mask = (
            frame["Source Type"].isin(identity.source_types)
            & frame["Risk Type"].eq(identity.risk_type)
            & frame["Risk Greek"].eq(identity.risk_greek)
            & frame[column].eq(identity.underlying)
        )
        rows = frame.loc[mask].copy()
        rows["Revision"] = committed.revision
        rows["Snapshot Date"] = committed.market_date
        if handoff.kind == "risk":
            rows["Risk Date"] = rows["Source Type"].map(committed.risk_dates)
            if rows["Risk Date"].isna().any():
                raise ValueError("Current Risk has no committed source Risk Date")
            rows["Mapping Status"] = "Mapped"
        else:
            rows["Market Date"] = committed.market_date
        return committed.revision, rows
```

### 3.2. Declare the two manager reads at the app boundary

Open `cube/app/s02_contracts.py`.



Find:

```python
    def read_frame(self, name: FrameName) -> FrameReadProtocol: ...
```

Replace with:

```python
    def read_frame(self, name: FrameName) -> FrameReadProtocol: ...

    def data_history_identities(self) -> tuple[object, ...]: ...

    def read_data_history(self, handoff) -> tuple[int, pd.DataFrame]: ...
```

### 3.3. Allow the existing history reader to receive current rows

Open `cube/history/s06_repository.py`.



Find:

```python
    def read(self, query: HistoryQuery) -> HistoryBundle:
```

Replace with:

```python
    def read(
        self,
        query: HistoryQuery,
        *,
        current_rows: pd.DataFrame | None = None,
        current_revision: int = 0,
    ) -> HistoryBundle:
```

### 3.4. Include actual current dates before resolving the requested period

Open `cube/history/s06_repository.py`.



Find:

```python
        dates = resolve_actual_period_dates(available_dates, query)
```

Replace with:

```python
        live = current_rows.copy() if current_rows is not None else pd.DataFrame()
        if handoff.kind == "risk" and not live.empty:
            live = _apply_risk_filters(live, handoff.filter_view)
        if not live.empty:
            live[date_column] = live[date_column].map(
                lambda value: _date(value, label=date_column)
            )
            live_dates = tuple(sorted(set(live[date_column])))
            # The committed Market date is the end of this current view.
            if handoff.kind == "market":
                available_dates = tuple(
                    value for value in available_dates if value <= live_dates[-1]
                )
            available_dates = tuple(sorted(set(available_dates).union(live_dates)))
        dates = resolve_actual_period_dates(available_dates, query)
```

### 3.5. Add current values and replace same-day archive observations

Open `cube/history/s06_repository.py`.



Find:

```python
        if handoff.kind == "risk":
            period_rows = _apply_risk_filters(period_rows, handoff.filter_view)
```

Replace with:

```python
        if not live.empty:
            live = live.loc[live[date_column].isin(dates)].copy()
        if not live.empty:
            if not period_rows.empty:
                archived_dates = period_rows[date_column].map(
                    lambda value: _date(value, label=date_column)
                )
                # Replace the whole selected source/day, not individual tenor cells.
                # This also removes tenors that no longer exist in the current view.
                live_keys = set(zip(live[SOURCE_TYPE], live[date_column]))
                keep = [
                    (source, day) not in live_keys
                    for source, day in zip(period_rows[SOURCE_TYPE], archived_dates)
                ]
                period_rows = period_rows.loc[keep]
            if len(period_rows) + len(live) > self._max_raw_rows:
                raise HistoryValidationError(
                    "Current plus archived data is too large; narrow the period or Risk filters."
                )
            period_rows = pd.concat([period_rows, live], ignore_index=True, sort=False)
        if handoff.kind == "risk":
            period_rows = _apply_risk_filters(period_rows, handoff.filter_view)
```

### 3.6. Include the current revision in the returned playback identity

Open `cube/history/s06_repository.py`.



Find:

```python
            raw_rows=period_rows.reset_index(drop=True),
            generation=generation,
```

Replace with:

```python
            raw_rows=period_rows.reset_index(drop=True),
            generation=f"{generation}:current:{current_revision}",
```

### 3.7. Import the existing catalog types

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    HistoryBundle,
```

Replace with:

```python
    HistoryBundle,
    HistoryCatalogEntry,
    HistoryIdentityCatalog,
```

### 3.8. Remove the unused old selection import

Open `cube/pages/data/s03_callbacks.py`.



Remove:

```python
    catalog_key_for_handoff,
```

### 3.9. Keep the truthful Current label

Open `cube/pages/data/s03_callbacks.py`.

Delete this entire block. Keep `metric_column = bundle.metric_column` and `browser_values = bundle.values` directly above it.



Remove:

```python
    if bundle.query.handoff.kind == "market" and metric_column == "Current":
        metric_column = "Official"
        browser_values = browser_values.rename(columns={"Current": metric_column})
```

### 3.10. Use the same label in the breadcrumb

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    series = "Risk" if handoff.kind == "risk" else "Official"
```

Replace with:

```python
    series = "Risk" if handoff.kind == "risk" else "Current"
```

### 3.11. Pass the manager into the existing query helper

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    reset_generation: object,
) -> tuple[dict[str, object] | None, str]:
```

Replace with:

```python
    reset_generation: object,
    refresh_manager=None,
) -> tuple[dict[str, object] | None, str]:
```

### 3.12. Read the selected current rows when Load history is clicked

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    bundle = repository.read(query)
```

Replace with:

```python
    revision, rows = (
        refresh_manager.read_data_history(handoff)
        if refresh_manager is not None else (0, pd.DataFrame())
    )
    bundle = repository.read(query, current_rows=rows, current_revision=revision)
```

### 3.13. Update the empty-result explanation

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
        status = "No archived rows match this exact identity and period."
```

Replace with:

```python
        status = "No current or archived rows match this identity and period."
```

### 3.14. Replace the archive-only catalog helper

Open `cube/pages/data/s03_callbacks.py`.

Replace the entire top-level `load_archive_catalog` function. Stop before `def register_callbacks`; keep that next function.



Find:

```python
def load_archive_catalog(
    repository: ArchiveHistoryRepository,
    cache_state: object,
) -> tuple[dict[str, object] | None, str]:
    """Load the tiny direct-selector catalog after the Data route is mounted."""

    if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
        return None, "Preparing archive choices…"
    catalog = repository.catalog()
    risk_count = sum(entry.kind == "risk" for entry in catalog.entries)
    market_count = sum(entry.kind == "market" for entry in catalog.entries)
    if not catalog.entries:
        status = (
            "No completed schema-v4 Risk or Market archive identities are available."
        )
    else:
        status = (
            f"Archive ready: {risk_count:,} Risk and {market_count:,} Market choices."
        )
    return catalog.to_mapping(), status
```

Replace with:

```python
def load_archive_catalog(
    repository: ArchiveHistoryRepository,
    cache_state: object,
    refresh_manager=None,
) -> tuple[dict[str, object] | None, str]:
    """Combine archive identities with compact committed current choices."""
    if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
        return None, "Preparing Data choices…"
    archive = repository.catalog()
    entries = {entry.key: entry for entry in archive.entries}
    revision = 0
    if refresh_manager is not None:
        for resolved in refresh_manager.data_history_identities():
            handoff = HistoryHandoff.from_resolved_identity(
                resolved, metric="risk" if resolved.kind == "risk" else "current"
            )
            entry = HistoryCatalogEntry(
                kind=handoff.kind, identity=handoff.identity,
                source_revision=handoff.source_revision,
                snapshot_date=handoff.snapshot_date,
            )
            entries[entry.key] = entry
            revision = max(revision, entry.source_revision)
    ordered = tuple(sorted(entries.values(), key=lambda entry: (
        entry.kind, entry.identity.risk_type, entry.identity.risk_greek,
        entry.identity.underlying.casefold(), entry.identity.identity_mode,
        entry.identity.source_types,
    )))
    catalog = HistoryIdentityCatalog(
        generation=f"{archive.generation}:current:{revision}", entries=ordered
    )
    status = (
        f"Ready: {len(ordered):,} current/archive identity choices."
        if ordered else "No choices yet. Wait for the initial data refresh to finish."
    )
    return catalog.to_mapping(), status
```

### 3.15. Let Data callbacks use the existing refresh manager

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
def register_callbacks(
    app: Dash,
    repository: ArchiveHistoryRepository,
) -> None:
```

Replace with:

```python
def register_callbacks(
    app: Dash,
    repository: ArchiveHistoryRepository,
    refresh_manager=None,
) -> None:
```

### 3.16. Give the dropdowns one owner

Open `cube/pages/data/s03_callbacks.py`.

Delete both complete callbacks `sync_quick_handoff` and `configure_identity_mode`, including their `@app.callback(...)` decorators. Insert the callback below in their place. Stop before the decorator for `configure_request`, whose first Output is `data-identity-breadcrumb`; keep that breadcrumb callback. The dropdown values are intentionally Inputs and Outputs of this one callback; do not split it back into mutually dependent callbacks.



Paste this complete replacement block:

```python
    @app.callback(
        Output("data-history-kind-tabs", "value"),
        Output("data-identity-mode", "value"),
        Output("data-identity-mode", "disabled"),
        Output("data-risk-type", "options"),
        Output("data-risk-type", "value"),
        Output("data-risk-greek", "options"),
        Output("data-risk-greek", "value"),
        Output("data-underlying", "options"),
        Output("data-underlying", "value"),
        Output("data-load-history-button", "disabled"),
        Input("data-history-catalog-store", "data"),
        Input("data-history-kind-tabs", "value"),
        Input("data-identity-mode", "value"),
        Input("data-risk-type", "value"),
        Input("data-risk-greek", "value"),
        Input("data-underlying", "value"),
        Input("data-history-handoff-store", "data"),
        State("data-history-handoff-consumed-store", "data"),
        State("data-history-request-store", "data"),
    )
    def choose_data_identity(
        raw_catalog, kind, mode, risk_type, greek, underlying,
        raw_handoff, consumed_nonce, raw_request,
    ):
        # One callback owns the dependent selectors. User changes remain selected.
        # A new Quick navigation prefills them once, without locking them later.
        handoff = None
        try:
            if ctx.triggered_id == "data-history-handoff-store":
                handoff = _stored_history_handoff(raw_handoff)
            elif ctx.triggered_id is None:
                handoff = _pending_history_handoff(raw_handoff, consumed_nonce)
        except (HistoryValidationError, TypeError, ValueError):
            if ctx.triggered_id is None:
                try:
                    handoff = _requested_history_handoff(raw_request)
                except (HistoryValidationError, TypeError, ValueError):
                    pass
        kind = handoff.kind if handoff else str(kind or "risk").casefold()
        mode = handoff.identity.identity_mode if handoff else str(mode or "reported")
        if kind == "market":
            mode = "underlying"
        try:
            catalog = HistoryIdentityCatalog.from_mapping(raw_catalog)
        except (HistoryValidationError, TypeError, ValueError):
            catalog = HistoryIdentityCatalog(generation="pending", entries=())
        if handoff:
            risk_type = handoff.identity.risk_type
            greek = handoff.identity.risk_greek
        try:
            fallback = handoff or _stored_history_handoff(raw_handoff)
            entry = HistoryCatalogEntry(
                kind=fallback.kind, identity=fallback.identity,
                source_revision=fallback.source_revision,
                snapshot_date=fallback.snapshot_date,
            )
            if handoff:
                underlying = entry.key
            if (
                underlying == entry.key and kind == fallback.kind
                and mode == fallback.identity.identity_mode
                and risk_type == fallback.identity.risk_type
                and greek == fallback.identity.risk_greek
            ):
                entries = {item.key: item for item in catalog.entries}
                entries.setdefault(entry.key, entry)
                catalog = HistoryIdentityCatalog(
                    generation=catalog.generation, entries=tuple(entries.values())
                )
        except (HistoryValidationError, TypeError, ValueError):
            pass
        type_options = risk_type_options(catalog, kind, mode)
        risk_type = selected_value(type_options, risk_type)
        greek_options = (
            risk_greek_options(catalog, kind, mode, risk_type) if risk_type else []
        )
        greek = selected_value(greek_options, greek)
        options = (
            underlying_options(catalog, kind, mode, risk_type, greek)
            if risk_type and greek else []
        )
        underlying = selected_value(options, underlying)
        return (
            kind, mode, kind == "market", type_options, risk_type,
            greek_options, greek, options, underlying, underlying is None,
        )
```

### 3.17. Replace catalog refresh and remove the three old dropdown callbacks

Open `cube/pages/data/s03_callbacks.py`.

Delete the complete `refresh_archive_catalog`, `choose_risk_type`, `choose_risk_greek`, and `choose_underlying` callbacks, including their decorators. This contiguous block starts with the decorator whose first Output is `data-history-catalog-store` and ends immediately before the decorator whose first Output is `data-history-request-store`. Insert the callback below. Keep `choose_history_request` and its decorator unchanged for now; the next steps adjust only specified lines.



Paste this complete replacement block:

```python
    @app.callback(
        Output("data-history-catalog-store", "data"),
        Output("data-catalog-status", "children"),
        Input("data-history-cache-state-store", "data"),
        Input("refresh-commit-revision", "children"),
        State("data-history-catalog-store", "data"),
    )
    def refresh_archive_catalog(cache_state, _committed_revision, current):
        if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
            return None, "Preparing Data choices…"
        revision = int(refresh_manager.health.revision) if refresh_manager else 0
        generation = f"{cache_state['generation']}:current:{revision}"
        if isinstance(current, Mapping) and current.get("generation") == generation:
            return no_update, no_update
        try:
            return load_archive_catalog(repository, cache_state, refresh_manager)
        except (OSError, HistoryValidationError, TypeError, ValueError) as error:
            return None, f"Data choices failed: {error}"
```

### 3.18. Keep a Quick selection loadable while its catalog is preparing

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
                    handoff = direct_history_handoff(
                        raw_catalog,
                        entry_key,
                        kind=kind,
                        reset_generation=reset,
                    )
```

Replace with:

```python
                    try:
                        handoff = direct_history_handoff(
                            raw_catalog, entry_key, kind=kind, reset_generation=reset
                        )
                    except HistoryValidationError:
                        # Preserve an exact Quick identity while the catalog loads.
                        fallback = _stored_history_handoff(raw_handoff)
                        entry = HistoryCatalogEntry(
                            kind=fallback.kind, identity=fallback.identity,
                            source_revision=fallback.source_revision,
                            snapshot_date=fallback.snapshot_date,
                        )
                        if entry.key != entry_key or fallback.kind != kind:
                            raise
                        handoff = replace(fallback, reset_generation=reset)
```

### 3.19. Preserve Quick Risk filters when reloading the same identity

Open `cube/pages/data/s03_callbacks.py`.

Inside `choose_history_request`, replace this exact Load-button return block. Choosing a different identity creates a fresh direct selection. Reloading the same identity, including after changing period, keeps its existing Quick Risk filters.



Find:

```python
                return history_request_payload(
                    handoff,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    request_id=f"load-{int(load_clicks or 0)}-{reset}",
                ), no_update
```

Replace with:

```python
                try:
                    previous_handoff = _requested_history_handoff(current_request)
                except (HistoryValidationError, TypeError, ValueError):
                    previous_handoff = None
                if (
                    previous_handoff is not None
                    and previous_handoff.kind == handoff.kind
                    and previous_handoff.identity == handoff.identity
                ):
                    handoff = replace(
                        handoff, filter_view=previous_handoff.filter_view,
                        metric=previous_handoff.metric,
                    )
                return history_request_payload(
                    handoff,
                    period=period,
                    start_date=start_date,
                    end_date=end_date,
                    request_id=f"load-{int(load_clicks or 0)}-{reset}",
                ), no_update
```

### 3.20. Stop a request from re-triggering catalog preparation

Open `cube/pages/data/s03_callbacks.py`.

This occurrence is in the decorator immediately above `refresh_archive_generation`. Keep the same function parameters.



Find:

```python
        Input("data-history-request-store", "data"),
        State("data-history-cache-state-store", "data"),
```

Replace with:

```python
        State("data-history-request-store", "data"),
        State("data-history-cache-state-store", "data"),
```

### 3.21. Refresh the selected view after a committed data refresh

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
        Input("reset-generation-store", "data"),
        running=[
```

Replace with:

```python
        Input("reset-generation-store", "data"),
        Input("refresh-commit-revision", "children"),
        running=[
```

### 3.22. Accept the committed revision signal in the loading callback

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
    def load_history(
        raw_request,
        cache_state,
        reset_generation,
    ):
```

Replace with:

```python
    def load_history(
        raw_request,
        cache_state,
        reset_generation,
        _committed_revision,
    ):
```

### 3.23. Supply the manager when the loading callback queries history

Open `cube/pages/data/s03_callbacks.py`.



Find:

```python
                cache_state,
                reset_generation,
            )
```

Replace with:

```python
                cache_state,
                reset_generation,
                refresh_manager,
            )
```

### 3.24. Make the Underlying dropdown explicitly searchable and scrollable

Open `cube/pages/data/s02_view.py`.



Find:

```python
                                        id="data-underlying",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        searchable=True,
```

Replace with:

```python
                                        id="data-underlying",
                                        options=[],
                                        value=None,
                                        clearable=False,
                                        searchable=True,
                                        maxHeight=300,
                                        optionHeight=36,
                                        placeholder="Type or scroll to choose an underlying",
```

### 3.25. Update the initial dropdown description

Open `cube/pages/data/s02_view.py`.



Find:

```python
                                "Archive choices load only on this page.",
```

Replace with:

```python
                                "Current and archived choices load on this page.",
```

### 3.26. Start normal data loading on a direct Data visit

Open `cube/app/s07_factory.py`.



Find:

```python
    def data_page_body():
        """Build the archive-free Data shell with prefix-correct links."""

        return build_data_page(
```

Replace with:

```python
    def data_page_body():
        """Build Data immediately and start the shared refresh if it is cold."""
        schedule_cold_start()
        return build_data_page(
```

### 3.27. Connect the Data callbacks to the existing manager

Open `cube/app/s07_factory.py`.



Find:

```python
    register_data_callbacks(app, history_repository)
```

Replace with:

```python
    register_data_callbacks(app, history_repository, refresh_manager)
```

### 3.28. Use the standalone page

After saving and restarting the app, open `/data` directly in a fresh browser tab. Wait for the ordinary initial data refresh. Choose Risk History or Market History, choose Identity, Risk Type and Risk Greek, then type in or scroll the Underlying dropdown. Choose the period and click **Load history**.

With no archive, the current observation still appears. With archives, earlier observations appear before the current Market observation. Same-day current data replaces that day’s archived selection, so it is not counted twice. Missing quotes remain missing. With only one date, there is nothing for Play to advance through.

Open Data from Quick Risk and Quick Market once each, then change the dropdown to a different identity and click Load history. The new choice must remain selected. A Quick Risk selection keeps its existing filters when the same identity is reloaded or its period is changed. Selecting a different identity starts a fresh Data-page selection.

## Checks for the retained Portfolio and earlier Data changes

1. Save every edited file.
2. In a notebook opened in the application folder, run this Python cell. It checks syntax without starting the app or calling any connector:

```python
from pathlib import Path

files = [
    "cube/ui/s01_constants.py",
    "cube/ui/s02_aggregation.py",
    "cube/pages/risk/s06_explorertables.py",
    "cube/pages/risk/s02_state.py",
    "cube/pages/risk/s01_common.py",
    "cube/pages/risk/s16_view.py",
    "cube/services/s02_state.py",
    "cube/app/s02_contracts.py",
    "cube/history/s06_repository.py",
    "cube/pages/data/s03_callbacks.py",
    "cube/pages/data/s02_view.py",
    "cube/app/s07_factory.py",
]
for name in files:
    compile(Path(name).read_text(encoding="utf-8-sig"), name, "exec")
print("Python syntax is valid.")
```

3. Start the app using your normal command. Hard-refresh its browser tab with **Ctrl+Shift+R** to load the edited JavaScript.
4. Perform the short browser checks at the end of each chapter. A syntax check cannot establish that a dropdown or refresh behaves correctly in the running app.
5. If an edit needs to be undone, stop the app, restore all the copied application files from the same backup, and remove only the new application files listed above. Start the app and hard-refresh again. Keep all source data and archive files.


---

The next chapter preserves the later unified-Data repair. Its original test report is part of that earlier guide; it was not rerun during this refresh investigation. If your code has `choose_data_identity`/`choose_history_request` and lacks the unified `edit_workspace`, this chapter is not a drop-in upgrade to that interface.

### 4.4. Data page: fast choices and reliable Quick prefill

Apply this to your existing unified Data page with **Risk / Market / Both** and **Choose a series**, after the performance changes you have already completed. Keep those changes. This is a further repair to Data selection; replacing a document does not mean undoing working application code.

The remaining design problem is that the selection callback runs in Python and receives the full catalogue whenever you edit a control. Quick navigation can also wait for catalogue preparation, then lose its incoming selection when empty page controls initialize. The earlier implementation instructions did not supply a complete replacement for that callback.

The fix is to run that one selection callback in the browser. It filters the catalogue already on the page and immediately selects the exact identity supplied by Quick Risk or Quick Market. Python still validates each submitted request and reads the actual history. Changing a mode or a dropdown edits a selection; pressing **Load**, or arriving with a new Quick selection, loads it.

There are five edits: add one JavaScript file, replace one selection callback registration, correct the catalogue callback inputs, correct metadata polling, and add one initial-load guard. No new cache, service, data limit or selection control is needed.

These instructions match the unified component IDs and history request format below. The modified application running in your JupyterHub has not been inspected directly. Local checks cover the replacement callback and its request format; they do not measure your archive or provider speed.

In an isolated Dash browser check with invented identities, Quick Risk populated while the catalogue response was deliberately held open. Releasing that response preserved the selection. Market mode, manual selection and Both caused no additional financial-loader call; pressing Load then submitted the selected pair once.

### 4.1. Keep the working changes and locate the files

1. Stop the app using your usual notebook or process control.
2. In the JupyterHub file browser, open the application folder containing both `cube/` and `assets/`.
3. Keep the completed Portfolio filtering, Risk rendering/grouping, promotion calculations and bulk Data identity listing. Keep the current-plus-archive catalogue and the current snapshot appended to history.
4. Open `cube/pages/data/s03_callbacks.py`. Find `def register_callbacks(`, then the nested `def edit_workspace(`. This is the unified selector with thirteen outputs. Its outputs include `data-series-picker.options`, `data-series-picker.value` and `data-history-request-store.data`.
5. Also locate `def refresh_archive_catalog(`, `def refresh_archive_generation(` and `def load_workspace(` in that file. Keep `query_workspace_bundle` and the server request parser.
6. If the app still has only `choose_history_request` and no unified `edit_workspace`, this replacement does not match that older layout. Do not paste a second selector alongside it. Match the running application's unified callback first.
7. Save copies of `cube/pages/data/s03_callbacks.py` and `cube/pages/data/s02_view.py` outside the app folder. If `assets/data_workspace_editor.js` already exists, save a copy of it too. Keep JavaScript backups outside `assets/`, because Dash loads JavaScript files from that folder.

### 4.2. Add the complete browser selection callback

1. In the application's top-level `assets/` folder, create `data_workspace_editor.js`. Its path must be `assets/data_workspace_editor.js`, alongside the other application assets. Do not create it inside `cube/pages/data/`.
2. Paste the entire following block into the new file. If this exact file already exists, replace its contents with this block.
3. Keep all other assets, including playback and chart helpers. The namespace assignment at the end preserves those existing functions.

```javascript
/* Data selection only. The existing Python loader validates and reads history. */
(function () {
    "use strict";
    const MODES = ["risk", "market", "both"];
    const PERIODS = ["wtd", "mtd", "ytd", "1y", "5y", "all", "custom"];
    const QUICK = "__quick_handoff__";
    const copy = value => value == null ? null : JSON.parse(JSON.stringify(value));
    const opposite = kind => kind === "risk" ? "market" : "risk";
    const selectedKey = kind => "__data_selected_" + kind + "__";
    const identityKey = identity => JSON.stringify([
        identity.source_types, identity.risk_type, identity.risk_greek,
        identity.underlying, identity.identity_mode
    ]);
    const sameIdentity = (a, b) => Boolean(a && b && a.kind === b.kind &&
        identityKey(a.identity) === identityKey(b.identity));
    const integer = value => Number.isInteger(value) && value >= 0;
    const validDate = value => typeof value === "string" &&
        /^\d{4}-\d{2}-\d{2}$/.test(value) &&
        !Number.isNaN(Date.parse(value)) &&
        new Date(value).toISOString().slice(0, 10) === value;

    function checkedHandoff(value) {
        const h = copy(value), i = h && h.identity;
        if (!h || h.schema_version !== 1 || !["risk", "market"].includes(h.kind) ||
            !integer(h.source_revision) || !integer(h.reset_generation) ||
            !validDate(h.snapshot_date) || !i ||
            !Array.isArray(i.source_types) || !i.source_types.length ||
            !i.source_types.every(v => typeof v === "string" && v.trim()) ||
            ![i.risk_type, i.risk_greek, i.underlying].every(v => typeof v === "string" && v.trim()) ||
            !["reported", "underlying"].includes(i.identity_mode)) {
            throw Error("The selected series has an invalid identity; reopen it or choose another.");
        }
        if (h.kind === "market" && (h.filter_view != null ||
            i.identity_mode !== "underlying" || i.source_types.length !== 1)) {
            throw Error("Market requires one raw series without Risk filters.");
        }
        if (h.filter_view != null && (typeof h.filter_view.filters !== "object" ||
            h.filter_view.filters === null || typeof h.filter_view.exclude_selected !== "boolean" ||
            !Object.values(h.filter_view.filters).every(values => Array.isArray(values) &&
                values.every(v => typeof v === "string")))) {
            throw Error("The imported Risk scope is invalid; reopen Quick Risk.");
        }
        h.metric = h.kind === "risk" ? "risk" : "current";
        return h;
    }

    function label(h) {
        const i = h.identity;
        return [h.kind === "risk" ? "Risk" : "Market", i.risk_type, i.risk_greek,
            i.underlying, i.identity_mode === "reported" ? "Reported" : "Raw",
            i.source_types.join(", ")].join(" · ");
    }

    function requestFor(draft, period, start, end, requestId) {
        if (!PERIODS.includes(period)) throw Error("Choose a valid period.");
        if (period === "custom" && (!validDate(start) || !validDate(end) || start > end)) {
            throw Error("Choose both custom dates, with the start on or before the end.");
        }
        const handoffs = {};
        const required = draft.display_mode === "both" ? ["risk", "market"] : [draft.display_mode];
        for (const kind of required) {
            const handoff = checkedHandoff(draft[kind]);
            if (handoff.kind !== kind || handoff.reset_generation !== draft.reset_generation) {
                throw Error("Choose a current " + kind + " series.");
            }
            handoffs[kind] = handoff;
        }
        return {schema_version: 1, display_mode: draft.display_mode, handoffs,
            period, start_date: period === "custom" ? start : null,
            end_date: period === "custom" ? end : null, request_id: requestId};
    }

    function sameSelection(a, b) {
        if (!a || !b || a.display_mode !== b.display_mode || a.period !== b.period ||
            a.start_date !== b.start_date || a.end_date !== b.end_date) return false;
        return ["risk", "market"].every(kind => {
            const x = a.handoffs[kind], y = b.handoffs && b.handoffs[kind];
            return !x && !y || sameIdentity(x, y) &&
                x.source_revision === y.source_revision && x.snapshot_date === y.snapshot_date &&
                x.reset_generation === y.reset_generation &&
                JSON.stringify(x.filter_view) === JSON.stringify(y.filter_view);
        });
    }

    function workspaceEditor(rawQuick, catalogTimestamp, mode, primaryKey, companionKey,
        clearClicks, loadClicks, reset, period, start, end, previous, consumed, loaded, rawCatalog) {
        const nu = window.dash_clientside.no_update;
        const unchanged = () => Array(13).fill(nu);
        // Wait for the Data controls to mount. The session handoff remains pending.
        if (!MODES.includes(mode)) return unchanged();
        const context = window.dash_clientside.callback_context || {};
        const triggered = new Set((context.triggered || []).map(item => item.prop_id));
        const changed = id => triggered.has(id);
        const old = previous && previous.schema_version === 1 ? previous : {};
        let d = Object.assign({schema_version: 1, initialized: false, display_mode: "risk",
            primary_key: null, primary_kind: null, companion_key: null,
            risk: null, market: null, risk_scope: null, quick_nonce: null,
            rejected_quick_nonce: null, catalog_generation: null, reset_generation: reset}, copy(old));
        let status = "", request = nu, consume = nu, event = "initial", valid = false;
        let options = [], companions = [], companionKind = "market";
        const catalogReady = Boolean(rawCatalog && Array.isArray(rawCatalog.entries));
        const entries = catalogReady ? rawCatalog.entries : [];
        const byKey = new Map(entries.map(entry => [entry.key, entry]));
        const byIdentity = new Map();
        for (const entry of entries) {
            const key = entry.kind + ":" + identityKey(entry.identity);
            const matches = byIdentity.get(key) || [];
            matches.push(entry); byIdentity.set(key, matches);
        }
        const listed = entries.map(entry => ({label: label(entry), value: entry.key, kind: entry.kind}));
        listed.sort((a, b) => a.label.toLowerCase().localeCompare(b.label.toLowerCase()) || a.value.localeCompare(b.value));
        const optionList = kind => listed.filter(item => kind === "both" || item.kind === kind)
            .map(item => ({label: item.label, value: item.value}));
        options = optionList(d.display_mode);
        const rawNonce = String(rawQuick && rawQuick.nonce || "");
        const fresh = Boolean(rawNonce && rawNonce !== String(consumed || "") &&
            rawNonce !== String(d.quick_nonce || "") && rawNonce !== String(d.rejected_quick_nonce || ""));
        let quick = null;
        const keyFor = handoff => {
            const matches = byIdentity.get(handoff.kind + ":" + identityKey(handoff.identity)) || [];
            return matches.length === 1 ? matches[0].key : null;
        };
        const isImported = handoff => sameIdentity(handoff, quick) && d.quick_nonce === rawNonce;
        const displayKey = handoff => keyFor(handoff) ||
            (isImported(handoff) ? QUICK : selectedKey(handoff.kind));
        const resolve = key => {
            const entry = byKey.get(key);
            let handoff;
            if (entry) {
                handoff = checkedHandoff({schema_version: 1, kind: entry.kind,
                    identity: entry.identity, metric: entry.kind === "risk" ? "risk" : "current",
                    source_revision: entry.source_revision, snapshot_date: entry.snapshot_date,
                    filter_view: null, reset_generation: reset});
            } else {
                const existing = [d.risk, d.market].find(h => h &&
                    (key === selectedKey(h.kind) || key === QUICK && isImported(h)));
                if (!existing) throw Error("Choose an available exact series.");
                handoff = checkedHandoff(existing);
            }
            if (handoff.kind === "risk") handoff.filter_view = copy(d.risk_scope);
            return handoff;
        };
        const setPrimary = key => {
            status = "";
            if (key == null) {
                d.primary_key = d.primary_kind = d.companion_key = null;
                d.risk = d.market = null;
                return;
            }
            const h = resolve(key);
            if (d.display_mode !== "both" && h.kind !== d.display_mode) {
                throw Error("Series does not match the selected display mode.");
            }
            d.primary_key = key; d.primary_kind = h.kind; d.companion_key = null;
            d.risk = d.market = null; d[h.kind] = h;
        };
        const setMode = value => {
            d.display_mode = value;
            if (value !== "both") {
                d.primary_kind = d[value] ? value : null;
                d.primary_key = d[value] ? displayKey(d[value]) : null;
                d.companion_key = null;
            }
        };
        const setCompanion = key => {
            if (d.display_mode !== "both" || !d.primary_kind) throw Error("Choose the primary series first.");
            const other = opposite(d.primary_kind), h = key == null ? null : resolve(key);
            if (h && h.kind !== other) throw Error("The companion must be the opposite kind.");
            d[other] = h; d.companion_key = key;
        };
        try {
            if (!integer(reset)) throw Error("Invalid cache reset; reload the page.");
            if (rawQuick && rawQuick.handoff) {
                try { quick = checkedHandoff(rawQuick.handoff); }
                catch (error) { if (fresh) throw error; }
            }
            if (!fresh) for (const kind of ["risk", "market"]) {
                if (d[kind]) {
                    try {
                        d[kind] = checkedHandoff(d[kind]);
                        if (d[kind].kind !== kind) throw Error("Mismatched saved kind");
                    } catch (error) {
                        d[kind] = null;
                        if (d.primary_kind === kind) d.primary_key = d.primary_kind = null;
                        else d.companion_key = null;
                        if (kind === "risk") d.risk_scope = null;
                        status = "The saved selection is invalid; choose another series.";
                    }
                }
            }
            if (fresh) {
                if (!quick || quick.reset_generation !== reset) {
                    throw Error("Quick selection predates Clear Cache; reopen it from Risk.");
                }
                event = "handoff";
                d.display_mode = quick.kind; d.primary_kind = quick.kind;
                d.risk = d.market = null; d[quick.kind] = quick;
                d.risk_scope = quick.kind === "risk" ? copy(quick.filter_view) : null;
                d.quick_nonce = rawNonce; d.primary_key = displayKey(quick); d.companion_key = null;
            } else if (!d.initialized) {
                // Restore before interpreting the layout's initial empty picker values.
                if (!d.risk && !d.market && loaded && MODES.includes(loaded.display_mode)) {
                    d.display_mode = loaded.display_mode;
                    for (const kind of ["risk", "market"]) {
                        if (loaded.handoffs && loaded.handoffs[kind]) {
                            d[kind] = checkedHandoff(loaded.handoffs[kind]);
                        }
                    }
                    d.primary_kind = d.risk ? "risk" : d.market ? "market" : null;
                    d.risk_scope = d.risk ? copy(d.risk.filter_view) : null;
                    if (rawNonce === String(consumed || "")) d.quick_nonce = rawNonce;
                }
                if (d.primary_kind && d[d.primary_kind]) {
                    d.primary_key = displayKey(d[d.primary_kind]);
                    const other = opposite(d.primary_kind);
                    d.companion_key = d.display_mode === "both" && d[other] ? displayKey(d[other]) : null;
                }
            } else if (changed("reset-generation-store.data") && d.reset_generation !== reset) {
                event = "reset";
            } else if (changed("data-load-history-button.n_clicks") && loadClicks > 0) {
                event = "load";
                // A click and edited values can arrive in the same browser update.
                if (changed("data-clear-risk-scope.n_clicks") && clearClicks > 0) {
                    d.risk_scope = null; if (d.risk) d.risk.filter_view = null;
                }
                if (changed("data-display-mode.value") && mode !== d.display_mode) setMode(mode);
                if (changed("data-series-picker.value") && primaryKey !== old.primary_key) setPrimary(primaryKey);
                if (changed("data-companion-picker.value") && companionKey !== old.companion_key) setCompanion(companionKey);
            } else if (changed("data-clear-risk-scope.n_clicks") && clearClicks > 0) {
                event = "clear_scope"; d.risk_scope = null;
                if (d.risk) d.risk.filter_view = null;
            } else if (changed("data-display-mode.value") && mode !== d.display_mode) {
                event = "mode"; setMode(mode);
            } else if (changed("data-series-picker.value") && primaryKey !== d.primary_key) {
                event = "primary"; setPrimary(primaryKey);
            } else if (changed("data-companion-picker.value") && companionKey !== d.companion_key) {
                event = "companion"; setCompanion(companionKey);
            } else if (changed("data-history-catalog-store.modified_timestamp")) {
                event = "catalog";
            } else { event = "dates"; }

            // Reset also covers a saved request restored after a cache clear.
            if ([d.risk, d.market].some(h => h && h.reset_generation !== reset)) event = "reset";
            if (event === "reset") {
                for (const kind of ["risk", "market"]) if (d[kind]) d[kind].reset_generation = reset;
                request = null; status = "Cache cleared — press Load to reload this selection";
            }
            d.reset_generation = reset;
            if (catalogReady && ["initial", "catalog"].includes(event)) {
                for (const kind of ["risk", "market"]) {
                    if (d[kind] && !keyFor(d[kind]) && !isImported(d[kind])) {
                        d[kind] = null; status = "This series is no longer available; choose another";
                    }
                }
                d.primary_key = d.primary_kind && d[d.primary_kind] ? displayKey(d[d.primary_kind]) : null;
                if (!d.primary_key) d.primary_kind = null;
            }
            const primary = d.primary_kind && d[d.primary_kind];
            companionKind = opposite(d.primary_kind);
            if (d.display_mode === "both" && primary) {
                const mayPair = ["initial", "mode", "primary"].includes(event) ||
                    event === "load" && (changed("data-display-mode.value") || changed("data-series-picker.value"));
                const clearedCompanion = changed("data-companion-picker.value") && companionKey == null &&
                    companionKey !== old.companion_key;
                if (!d[companionKind] && mayPair && !clearedCompanion &&
                    primary.identity.identity_mode === "underlying" && primary.identity.source_types.length === 1) {
                    const matches = byIdentity.get(companionKind + ":" + identityKey(primary.identity)) || [];
                    if (matches.length === 1) d[companionKind] = resolve(matches[0].key);
                }
                d.companion_key = d[companionKind] ? displayKey(d[companionKind]) : null;
            } else { d.companion_key = null; }

            options = optionList(d.display_mode);
            companions = d.display_mode === "both" && primary ? optionList(companionKind) : [];
            const addSelected = (list, key, h) => {
                if (h && key && !byKey.has(key)) list.push({value: key, label: label(h) +
                    (isImported(h) ? " · from Quick " + (h.kind === "risk" ? "Risk" : "Market") : " · selected (catalogue loading)")});
            };
            addSelected(options, d.primary_key, primary);
            addSelected(companions, d.companion_key, d[companionKind]);
            valid = Boolean(primary && d.primary_key &&
                (d.display_mode === "both" ? d.risk && d.market && d.companion_key : d[d.display_mode]));
            if ((event === "handoff" || event === "load") && valid) {
                const token = window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() :
                    Date.now().toString(36) + "-" + Math.random().toString(36).slice(2);
                request = requestFor(d, period || "all", start, end, token);
                if (d.quick_nonce && d.quick_nonce === rawNonce && String(consumed || "") !== rawNonce) consume = rawNonce;
            }
            if (!status && !valid) status = d.display_mode === "both" && primary ?
                "Choose the " + companionKind + " series to compare" : "Choose an exact series";
            if (!status && valid) {
                try {
                    const candidate = requestFor(d, period || "all", start, end, "draft");
                    status = request !== nu && request !== null || sameSelection(candidate, loaded) ?
                        "" : "Selection changed — press Load";
                } catch (error) { status = error.message; }
            }
            d.catalog_generation = catalogReady ? rawCatalog.generation : null;
            d.initialized = true;
        } catch (error) {
            status = error.message || "The selection is invalid; choose another series.";
            request = event === "reset" ? null : nu;
            if (fresh && event !== "handoff") d.rejected_quick_nonce = rawNonce;
            d.initialized = true;
        }
        const scope = d.risk_scope;
        const scopeText = scope ? "Risk scope: " + (scope.exclude_selected ? "Exclude selected" : "Include selected") +
            "; " + (Object.entries(scope.filters || {}).map(([key, values]) => key + "=" +
                (Array.isArray(values) ? values.join(", ") : "invalid scope")).join("; ") || "no restrictions") :
            "Risk scope: all archived positions for the selected identity";
        return [d, d.display_mode, options, d.primary_key, companions, d.companion_key,
            (companionKind === "risk" ? "Risk" : "Market") + " series to compare",
            d.display_mode !== "both", !valid, scopeText, status, request, consume];
    }
    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.cube = window.dash_clientside.cube || {};
    window.dash_clientside.cube.workspaceEditor = workspaceEditor;
}());
```

This is selection code only. Its small saved draft remembers the chosen Risk and Market identities, imported Risk filters and Quick navigation token. It does not copy positions, calculate values or read history. Both can automatically pair matching raw identities from one source. A reported Risk basket still needs an explicit Market companion; matching visible names alone would be ambiguous.

### 4.3. Replace the Python selector with one browser registration

1. In `cube/pages/data/s03_callbacks.py`, inspect the existing imports from `dash`.
2. Keep `Input`, `Output`, `State`, `no_update` and other names still used by the module. If `ClientsideFunction` is missing, add this import near the other Dash imports:

```python
from dash import ClientsideFunction
```

3. Inside `register_callbacks`, locate the `@app.callback(...)` decorator immediately belonging to `def edit_workspace(`.
4. Remove that decorator and the complete `edit_workspace` function body, stopping before the next sibling callback decorator or registration. Do not remove `register_callbacks` itself, the loader, or neighbouring callbacks.
5. In that same place, paste this complete registration. The four-space indentation is intentional: it belongs inside `register_callbacks`.

```python
    app.clientside_callback(
        ClientsideFunction(namespace="cube", function_name="workspaceEditor"),
        Output("data-workspace-draft-store", "data"),
        Output("data-display-mode", "value"),
        Output("data-series-picker", "options"),
        Output("data-series-picker", "value"),
        Output("data-companion-picker", "options"),
        Output("data-companion-picker", "value"),
        Output("data-companion-label", "children"),
        Output("data-companion-control", "hidden"),
        Output("data-load-history-button", "disabled"),
        Output("data-risk-scope-caption", "children"),
        Output("data-draft-status", "children"),
        Output("data-history-request-store", "data"),
        Output("data-history-handoff-consumed-store", "data"),
        Input("data-history-handoff-store", "data"),
        Input("data-history-catalog-store", "modified_timestamp", allow_optional=True),
        Input("data-display-mode", "value", allow_optional=True),
        Input("data-series-picker", "value", allow_optional=True),
        Input("data-companion-picker", "value", allow_optional=True),
        Input("data-clear-risk-scope", "n_clicks", allow_optional=True),
        Input("data-load-history-button", "n_clicks", allow_optional=True),
        Input("reset-generation-store", "data"),
        Input("data-period", "value", allow_optional=True),
        Input("data-custom-range", "start_date", allow_optional=True),
        Input("data-custom-range", "end_date", allow_optional=True),
        State("data-workspace-draft-store", "data", allow_optional=True),
        State("data-history-handoff-consumed-store", "data"),
        State("data-history-request-store", "data"),
        State("data-history-catalog-store", "data", allow_optional=True),
        prevent_initial_call=False,
    )
```

6. Keep exactly one owner for each of these thirteen outputs. Remove any leftover selector callback that also writes these same properties. Do not add `allow_duplicate=True` to retain both versions.
7. Keep `cube/pages/data/s04_workspace.py`, including `parse_workspace_request`, `workspace_request` and any pure helpers. The server loader still uses their request validation. There is no need to delete unused helpers as part of this repair.
8. Keep the layout, shared stores, Quick handoff writer, chart callbacks and playback callbacks. The existing Quick payload is still `{handoff, nonce}`. No new store is required.

The catalogue uses **modified_timestamp as Input** and **data as State** deliberately. Using catalogue data as an Input can make Dash hold the selector behind a pending catalogue response. The timestamp arrangement lets a Quick identity appear before the full catalogue arrives. Later catalogue arrival updates the choices without clearing that identity or submitting another history request.

### 4.4. Make catalogue preparation independent of selection

1. Stay inside `register_callbacks` in `cube/pages/data/s03_callbacks.py`.
2. Find the decorated `refresh_archive_catalog` function. Keep its existing function body, helper call, error handling, Outputs and State arguments. There are two existing naming variants: one calls `load_data_catalog(manager, repository, cache_state)`; the other calls `load_archive_catalog(repository, cache_state, refresh_manager)`. Keep the version already working in your file, including its argument order. Do not rename one into the other.
3. In this callback's decorator, keep `Input("data-history-cache-state-store", "data")` and its existing committed-data revision Input. The revision is either `Input("data-revision-store", "data")` or `Input("refresh-commit-revision", "children")`. Keep the one your app already has; do not add a component or retain both alternatives merely for this repair.
4. Remove any Input line in this callback whose component ID is `data-display-mode`, `data-series-picker`, `data-companion-picker`, `data-history-request-store`, `data-period` or `data-custom-range`. Remove any Input connected to the Play/Pause frame interval too. Remove the corresponding positional function parameter for each removed Input. These controls do not determine which identities exist. Keep all other parameter names and the body unchanged.
5. If the only Inputs are already the cache-state and committed-data revision from item 3, no Input removal is needed. Keep that callback as it is. Ensure its `prevent_initial_call` is `False`; if it is explicitly `True`, replace that value with `False`. Omitting the setting already uses the default initial call.
6. Keep the bulk `SearchCatalog.history_identities()` implementation, its `data_history_identities()` manager delegate, and the existing catalogue helper using that bulk method. Keep its current-data plus archive merge and generation/revision checks.

The catalogue is prepared when committed data or archive metadata changes, including the initial page load. Ordinary selector edits reuse it in the browser. Risk and Market share one catalogue, but their available exact identities can differ; Both includes both kinds.

### 4.5. Stop selection from restarting metadata preparation

1. In the same `register_callbacks`, find the whole decorated `refresh_archive_generation` function.
2. Replace its decorator and body with this block. Keep the existing `poll_archive_generation` helper.

```python
    @app.callback(
        Output("data-history-cache-state-store", "data"),
        Output("data-clear-status", "children"),
        Input("data-history-generation-interval", "n_intervals"),
        Input("clear-cache-complete-store", "data"),
        State("data-history-cache-state-store", "data"),
        prevent_initial_call=False,
    )
    def refresh_archive_generation(
        _intervals,
        reset_generation,
        previous_state,
    ):
        return poll_archive_generation(
            repository,
            None,
            previous_state,
            reset_generation,
        )
```

3. Remove the old `Input("data-history-request-store", "data")` from this callback, along with its corresponding function parameter. The replacement passes `None` because this polling helper does not need a selected request.
4. Do not retain a second decorated `refresh_archive_generation`. Returning `no_update` from an old callback does not remove its dependency links.
5. Open `cube/pages/data/s02_view.py`. Find the existing `dcc.Interval` with `id="data-history-generation-interval"`. Keep it enabled with `interval=60_000` and `n_intervals=0`. If `disabled=True` is present, replace it with `disabled=False`. If it is absent, the default is enabled. Keep the other existing interval properties.
6. Do not replace this with the faster Play/Pause interval. Metadata polling and player frames have different purposes.

Removing the request input breaks the chain in which selecting a request can restart metadata preparation, then catalogue preparation, then selection. The initial callback still runs immediately; it does not wait one minute.

### 4.6. Avoid reading the same history twice during initial navigation

1. Return to `cube/pages/data/s03_callbacks.py`.
2. Keep the existing `Mapping` import. If the name is missing from the module's imports, add this near the other standard-library imports:

```python
from collections.abc import Mapping
```

3. Inside the existing `load_workspace` function, find its initial empty-request guard. Keep it:

```python
        if raw_request is None:
            return None, "Choose a series and press Load", "No loaded selection"
```

4. Immediately after that guard, before the `try:` that calls `query_workspace_bundle`, add:

```python
        if not isinstance(cache_state, Mapping) or not cache_state.get("generation"):
            return (
                None,
                "Preparing history metadata…",
                "Selection ready; waiting for history metadata",
            )
```

5. Keep the rest of `load_workspace` unchanged: the `query_workspace_bundle` call, request parsing, caption, error handling and three return values. Keep the current observation reader and all server validation.
6. Keep its Inputs for `data-history-request-store.data`, `data-history-cache-state-store.data`, `reset-generation-store.data` and its existing committed-data revision trigger for current snapshots. Keep whichever revision name already works in your app: `data-revision-store.data` or `refresh-commit-revision.children`. Do not replace that component or add the alternative.
7. Remove any mode, picker, draft-period, draft-date or player-interval Inputs added to this loader. Remove their corresponding parameters as well. Those controls now feed the browser editor; the submitted request contains the values the server needs.
8. Keep the loader's `running` setting for the Load button's text. Its `disabled` property belongs to the browser editor. Do not add the financial bundle as State to this loader.

The picker can populate immediately from Quick while metadata is preparing. The first financial read waits for that metadata instead of running once without it and then running again when it arrives. An archive with no observations still has a valid metadata generation; this guard does not require historical rows or remove the current observation.

### 4.7. Check syntax and callback ownership, then restart

1. Save the callback and JavaScript files, plus `s02_view.py` if its interval needed correction.
2. In a notebook opened in the application folder, run this ordinary Python cell. It checks syntax without importing or starting the app:

```python
from pathlib import Path

for name in ("cube/pages/data/s03_callbacks.py", "cube/pages/data/s02_view.py"):
    path = Path(name)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
    print("Python syntax OK:", name)
```

3. Use the editor's project search for `workspaceEditor`. Expect one JavaScript function/assignment and one `ClientsideFunction` registration. There must be no remaining decorated Python `edit_workspace`.
4. Search Python files for `Output("data-series-picker"` and `Output("data-history-request-store"`. These properties should be written only by the new browser registration. Check single-quoted spellings too if your editor uses them. Request-store reads are expected and must remain.
5. Confirm `refresh_archive_catalog` has only the two Inputs shown in section 4.4 and `refresh_archive_generation` has only the two Inputs shown in section 4.5.
6. Restart the app using the same startup command or notebook cell you normally use.
7. Hard-refresh the browser so it downloads the new JavaScript asset. Keep your normal JupyterHub application URL and prefix.
8. If Dash reports that `cube.workspaceEditor` is missing, check that the new `.js` file is inside the actual top-level assets folder used by the app. Open the browser console for a JavaScript syntax error, correct the reported line from the complete block, restart and hard-refresh again. Do not create a second Python selector to work around a missing asset.

### 4.8. Check the behaviour in this order

1. **Quick Risk:** choose a known series on Risk, then open it in Data. Risk mode and the full exact identity should be selected. The imported filter scope should be visible. While the catalogue is pending, the option may end with **from Quick Risk**; it must remain selected when normal options arrive.
2. **Quick Market:** repeat with Quick Market. Market mode and the raw identity should be selected automatically. Market must not acquire the Risk Portfolio filter.
3. **Standalone Data:** open Data directly. Once its current/archive metadata arrives, open Choose a series, scroll or type to find an identity, choose it and press Load. A previous Quick navigation is not required.
4. **Mode changes:** after choices have loaded, switch Risk, Market and Both several times. Choices should change locally. A mode with no selected identity can correctly show a blank value while still offering options. The editor must not quietly choose the first option for you.
5. **Both:** a selected raw identity with exactly one matching opposite-kind identity may pair automatically. A reported Risk basket requires you to choose the Market companion. Press Load once both identities are selected.
6. **Draft edits:** change the chosen series or period without pressing Load. Expect **Selection changed — press Load** or a missing-selection message. Existing charts and their loaded caption retain the previously submitted result until you load the new selection.
7. **Imported Risk scope:** press Clear Risk scope if you want an unfiltered Risk selection, then press Load. Changing to Market must not send that Risk scope to a Market request.
8. **Navigation again:** leave Data and return. A consumed old Quick token must not overwrite a newer manual selection. A genuinely new Quick navigation must replace the current selection and load normally.
9. **Clear Cache:** clear it using the app's existing control. The old request should be invalidated; the identity can remain selected with a message to press Load again.
10. **Current-only data:** use a valid current series with no archive observations. Its current observation should still be available through the existing current-data reader. This repair must not change its dates, values or tenor coverage.

### 4.9. If something is still slow, identify which wait remains

1. If **Choose a series stays empty after Quick**, check that the JavaScript asset loaded, the old selector was removed, and the new callback uses catalogue `modified_timestamp` as Input with catalogue `data` as State. Check for duplicate-output or dependency-cycle errors in Dash.
2. If **Risk / Market / Both still causes a server callback**, check that the old Python selector is gone and the catalogue/loader Inputs match steps 4–6. In the browser Network panel, ordinary selector edits should not send a history request to `_dash-update-component`. The existing periodic metadata check may still appear independently.
3. If **the selection appears quickly but the chart takes time**, the remaining wait is history reading, processing or rendering. This guide preserves the requested date range. Choose MTD and press Load to compare with All; do not silently truncate history or remove size checks to hide the delay.
4. If **Data itself does not appear until much later**, record whether the delay occurs before navigation, during application cold start, or after the selected identity is visible. A browser selector repair cannot remove a slow provider call or a queued server navigation callback.
5. If **Preparing history metadata… never clears**, inspect the Data Diagnostics status and server message from the metadata callback. Confirm the enabled interval and initial callback in section 4.5. Fix a reported archive-path or metadata error; do not bypass server validation.

To undo only this repair, stop the app, restore the saved `cube/pages/data/s03_callbacks.py` and `cube/pages/data/s02_view.py`, and restore or remove `assets/data_workspace_editor.js` according to whether it existed before. Restart and hard-refresh. Leave the earlier completed performance and Portfolio changes in place.


---

## Appendix: superseded Commo-only hero instructions

**Reference only — do not implement this appendix. Chapter 1 above replaces this older advice.** It remains here so the previous guide is not silently lost. Its old subsection numbering and code are preserved for comparison; they do not change the reading order above.

<details>
<summary>Earlier Commo-only implementation, superseded by Chapter 1</summary>

## 1. Keep the Commodity loading hero visible until the refresh finishes

The hero must stay visible while Commodity quotes load and while the app calculates, validates, and commits the result. It may finish with a reported error if the refresh fails. The existing Python manager already reports completion after committing its snapshot; this change makes the browser follow that report.

Edit only `assets/s12_refresh.js` for this chapter. Keep your Commodity providers, tenors, calculations, backend progress endpoint, and refresh intervals unchanged. No Python imports are needed.

### 1.1 Prevent a page update from declaring Commo complete

Find this exact function opening. Replace only these two lines; keep the rest of the function underneath it.

Remove:

```javascript
  const finishRefreshProgress = () => {
    if (!refreshProgressState) return;
```

Add in the same place:

```javascript
  const finishRefreshProgress = (backendConfirmed = false) => {
    if (!refreshProgressState) return;
    if (refreshProgressState.mode === "commo" && !backendConfirmed) return;
```

### 1.2 Let confirmed backend completion close the hero

Inside the `refreshProgressPoll` interval, find this exact line. It occurs once. Replace only this occurrence. Keep the surrounding checks that recognise the backend attempt and wait for the refresh callback to end. The new condition rejects an old progress request that was already in flight when the callback ended. Steps 1.3 and 1.4 add its timestamps; finish all edits before restarting.

Remove:

```javascript
          if (!running) finishRefreshProgress();
```

Add in the same place:

```javascript
          const completionResponseIsCurrent = (
            refreshProgressState.mode !== "commo"
            || progress.requested_at > (
              refreshProgressState.dashCallbackCompletedAt || refreshProgressState.startedAt
            )
          );
          if (!running && completionResponseIsCurrent) finishRefreshProgress(true);
```

### 1.3 Record when the refresh callback ends

Inside `handleRefreshStatusTransition`, replace these two lines with the following three. This timestamp lets the browser distinguish a new progress response from an old cached response.

Remove:

```javascript
    state.dashCallbackComplete = true;
    const statusText = (node.textContent || "").trim();
```

Add in the same place:

```javascript
    state.dashCallbackComplete = true;
    state.dashCallbackCompletedAt = Date.now();
    const statusText = (node.textContent || "").trim();
```

### 1.4 Record when each progress request starts

Inside `requestBackendProgress`, replace these two lines with the following three. Keep its existing `const now = Date.now();` line near the start of that function. The new field records when the browser requested progress, so a late response from an earlier request cannot pretend to confirm that a later callback finished.

Remove:

```javascript
            server_time: progressStartedAt(payload.server_time),
            received_at: Date.now(),
```

Add in the same place:

```javascript
            server_time: progressStartedAt(payload.server_time),
            requested_at: now,
            received_at: Date.now(),
```

### 1.5 Do not mistake a recent previous refresh for this Commo refresh

Inside `startRefreshProgress`, find these two lines at the end of `belongsToAttempt`. Replace them with the following block. Keep the preceding checks for a changed refresh attempt and an increased committed revision. This excludes a known previous attempt even if it finished just before you clicked Commo.

Remove:

```javascript
          || progressStartedDuringAttempt(progress, startedAt)
        );
```

Add in the same place:

```javascript
          || (
            progressStartedDuringAttempt(progress, startedAt)
            && (
              mode !== "commo"
              || !refreshProgressState.baselineRefreshAttemptId
              || progress.attempt_id !== refreshProgressState.baselineRefreshAttemptId
            )
          )
        );
```

### 1.6 Handle a request rejected before its data call starts

Back inside `refreshProgressPoll`, find the following complete `else if` block. Replace the whole block. This prevents an invalid or stale request from leaving the hero open forever: a progress request started after the callback ends must confirm the backend is idle, and the callback must report an error. It also preserves the existing behaviour of following a refresh already started elsewhere. A missing progress response still means the result is unconfirmed, so the existing reconnecting display remains active.

Remove:

```javascript
        } else if (!running && !dashLoading && (refreshProgressState.sawRunning || statusChanged)) {
          if (!isBaselineSnapshot) renderBackendProgress(progress);
          finishRefreshProgress();
        }
```

Add in the same place:

```javascript
        } else if (!running && !dashLoading && (refreshProgressState.sawRunning || statusChanged)) {
          if (refreshProgressState.mode === "commo") {
            const errorNode = refreshErrorNode();
            const callbackError = (errorNode?.textContent || "").trim();
            // A rejected callback may create no new backend attempt. Require
            // an idle progress request started after that callback ended.
            const callbackEndConfirmed = (
              refreshProgressState.dashCallbackComplete
              && progress.requested_at > refreshProgressState.dashCallbackCompletedAt
            );
            if (callbackEndConfirmed && refreshProgressState.followingExistingWriter) {
              renderBackendProgress(progress);
              finishRefreshProgress(true);
            } else if (
              callbackEndConfirmed
              && errorNode?.classList.contains("has-errors")
              && callbackError
            ) {
              refreshProgressState.backendError = callbackError;
              finishRefreshProgress(true);
            }
          } else {
            if (!isBaselineSnapshot) renderBackendProgress(progress);
            finishRefreshProgress();
          }
        }
```

### 1.7 Keep the active hero when Dash redraws its panel

Inside `syncRefreshLifecycleNodes`, replace the exact four-line block below. Keep all the existing bootstrap handling and `abandonRefreshProgress` code underneath it. This also covers Dash hiding the existing panel without replacing the DOM node.

Remove:

```javascript
    const state = refreshProgressState;
    if (!state || state.panel?.isConnected) return;
    const replacement = document.getElementById("refresh-progress");
    if (state.mode === "bootstrap") {
```

Add in the same place:

```javascript
    const state = refreshProgressState;
    if (!state) return;
    const replacement = document.getElementById("refresh-progress");
    if (state.mode === "commo" && refreshLifecycleVisible()) {
      // Dash can replace the panel or restore its hidden property in place.
      // Keep following the same refresh, including a gap before remounting.
      if (replacement) {
        state.panel = replacement;
        replacement.hidden = false;
        replacement.classList.remove("is-complete");
        replacement.classList.add("is-running");
      }
      return;
    }
    if (state.panel?.isConnected) return;
    if (state.mode === "bootstrap") {
```

### 1.8 Save and check the behaviour

1. Save `assets/s12_refresh.js`.
2. Restart the app using your usual JupyterHub launch cell.
3. Hard-refresh the app browser with Ctrl+Shift+R so it loads the updated JavaScript.
4. Enable Commo Market and remain on the Risk page. The hero should remain visible through the last Commodity quote call, calculations, validation, and snapshot commit. It should then show completion and close.
5. Disable and re-enable Commo Market. A fast cached refresh may close quickly, but a slow refresh must keep its hero visible.
6. If a refresh fails, read the error log: it should show a failure and retain the last successful data. A disconnected progress endpoint should show reconnection status, not claim success. Do not deliberately damage your data or providers to create an error.
7. Leave every other `finishRefreshProgress()` call unchanged. Keep the existing percentage-bar behaviour; the Commo hero does not need an invented percentage to remain visible.


</details>
