# Refresh interaction and the stuck waiting panel

This is the current correction for the cumulative guide implementation. Later replacements take precedence over earlier versions. Keep the existing Data browser editor, connectors, history, JTD and Portfolio changes.

Implement the current `quick risk fix.md` Part D first, then the current `Hero.md`, then check the one dependency below. These are one coordinated update; restart after all the changes are in place. Do not put the earlier Hero lifecycle or this file's former section 5D back alongside the replacement.

## 1. Remove the callback dependency that delays Risk interactions

Open `cube/pages/risk/s07_explorer.py`. Find the `@app.callback` immediately above `def update_dimension_filters(...)`.

Replace only this Input:

```python
Input(CLEAR_CACHE_COMPLETE_STORE_ID, "data", allow_optional=True),
```

with:

```python
Input(CLEAR_CACHE_COMPLETE_STORE_ID, "modified_timestamp", allow_optional=True),
```

Keep the argument in the same position. This callback only needs to know that a clear completed; it does not consume the generation value. Leave other callbacks that actually read the generation on `data`.

Why: the long refresh callback owns the Store's `data` Output. Using that same property as an Input can put downstream filter work behind the refresh, even when you only changed a filter. The timestamp gives this callback its completion notification without that direct Output-to-Input dependency. This does not clear data or loosen the single-writer guard.

## 2. Replace the complete lifecycle using Hero.md

Follow `Hero.md` in order, including its Stores, backend receipt, renderer decorators and both JavaScript assets. Installing only the progress painter is incomplete.

The new flow is:

1. A click creates one request ID and starts the hero before dispatching that request.
2. The existing server callback performs the financial operation. A lightweight poll keeps the displayed step current.
3. The server callback returns a result bearing that request ID. A running flag becoming false is insufficient on its own.
4. A separate one-second clientside publisher exposes the committed revision immediately. It does not wait for the hero to finish.
5. The visible Risk/P&L callbacks return small completion receipts with their outputs. The browser waits for those outputs to mount and for their charts to finish drawing.
6. The hero displays completion or failure and remains visible. It does not disappear on a timer.

The publisher is driven only by `committed-revision-poll.n_intervals`. The committed revision and renderer receipts are **States**, not Inputs from the long callback. Making them Inputs recreates the dependency this repair removes.

On navigation or a workspace change, the displayed-result wait follows the new visible workspace. It never cancels the backend refresh. Closed, unrequested history queries are not launched merely to make the hero finish.

## 3. Keep browsing enabled

Keep the `running=[...]` entries supplied in Hero.md for actions that could launch another financial operation. Keep the manager's existing single-writer guard.

The replacement hero never adds a page-wide loading overlay or sets the app root to `inert`. Its painter clears the old global refresh loader. Tabs, row expansion, search and navigation continue to use the last committed snapshot during the refresh.

Do not disable all dropdowns, put `pointer-events: none` on the app root, or make every ordinary callback depend on `refresh-busy-store.data`. If you added such a lock while implementing an older guide, remove that added lock; keep individual editor save/send protections.

An individual large query can still take time. Keeping browsing enabled does not make pandas work free, and this change does not create more server workers.

## 4. Why the panel previously said “Waiting for Server”

There were several separate gaps in the earlier instructions:

- Reattaching the hero element did not repaint all of its text and stages. A replacement element could retain its initial waiting placeholder.
- The guide described parts of start/completion matching without supplying the complete implementation. Different interpretations could reject progress updates or finish an unrelated request.
- Holding the bootstrap hero open while also blocking revision publication created a circular wait: the views needed a revision that the hero was preventing them from receiving.
- Watching only the main Risk table omitted Aggregate P&L and other visible results.
- A Retry could receive the previous startup attempt's failure before the new attempt started. The new lifecycle excludes that old result until the new attempt is identified.

The replacement supplies the whole lifecycle and its bridges. Cold startup additionally waits for the startup worker to finish and for the dashboard to mount. Normal refreshes use their own callback result. Both paint live progress as it arrives.

A connection failure is shown as an interrupted connection; it is not labelled success. A rejected, busy or no-work request has its own outcome. The app never silently retries a financial operation.

## 5. Check the finished implementation

1. Start the server from a clean process and open Risk. The hero must show changing real steps, then a completed state after the visible table and Aggregate P&L have updated.
2. Repeat with a direct visit to `/pnl` from a clean process.
3. Click Refresh PL once. While it runs, expand/collapse a section, use another tab and navigate. The last committed data should remain usable.
4. Press Shift+F9 once. It must dispatch one request and eventually report that request's outcome. Do not test this by pressing three times.
5. Leave a Quick Risk or Quick Market chart visible and refresh. The hero must wait for the new chart to finish drawing.
6. Cause a controlled connector failure in a test environment. Expect a failure result and usable last-good data, not a flash of success.

For a stuck result, open the browser console and run:

```javascript
window.__cubeV5Assets.refreshDiagnostics()
```

Read `callback_pending`, `phase`, `target_revision` and `pending_views`. If `callback_pending` stays true, check the refresh callback's network response and server error. If a view remains pending, check that owner's extra Output, final State and decorator from Hero.md. Do not remove its completion check to hide the symptom.

## 6. Verification scope

The replacement is tested against reconstructed affected guide paths and local CSV/synthetic adapters, including actual Dash callbacks and Chrome rendering. It is an implementation guide, not a deployment to your production app. Existing history limits, stock pagination, connector setup and other earlier features remain your cumulative implementation; this correction does not replace them with the GitHub baseline.
