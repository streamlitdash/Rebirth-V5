# Data page: fast choices and reliable Quick prefill

Apply this to your existing unified Data page with **Risk / Market / Both** and **Choose a series**, after the performance changes you have already completed. Keep those changes. This is a further repair to Data selection; replacing a document does not mean undoing working application code.

The remaining design problem is that the selection callback runs in Python and receives the full catalogue whenever you edit a control. Quick navigation can also wait for catalogue preparation, then lose its incoming selection when empty page controls initialize. The earlier implementation instructions did not supply a complete replacement for that callback.

The fix is to run that one selection callback in the browser. It filters the catalogue already on the page and immediately selects the exact identity supplied by Quick Risk or Quick Market. Python still validates each submitted request and reads the actual history. Changing a mode or a dropdown edits a selection; pressing **Load**, or arriving with a new Quick selection, loads it.

There are five edits: add one JavaScript file, replace one selection callback registration, correct the catalogue callback inputs, correct metadata polling, and add one initial-load guard. No new cache, service, data limit or selection control is needed.

These instructions match the unified component IDs and history request format below. The modified application running in your JupyterHub has not been inspected directly. Local checks cover the replacement callback and its request format; they do not measure your archive or provider speed.

In an isolated Dash browser check with invented identities, Quick Risk populated while the catalogue response was deliberately held open. Releasing that response preserved the selection. Market mode, manual selection and Both caused no additional financial-loader call; pressing Load then submitted the selected pair once.

## 1. Keep the working changes and locate the files

1. Stop the app using your usual notebook or process control.
2. In the JupyterHub file browser, open the application folder containing both `cube/` and `assets/`.
3. Keep the completed Portfolio filtering, Risk rendering/grouping, promotion calculations and bulk Data identity listing. Keep the current-plus-archive catalogue and the current snapshot appended to history.
4. Open `cube/pages/data/s03_callbacks.py`. Find `def register_callbacks(`, then the nested `def edit_workspace(`. This is the unified selector with thirteen outputs. Its outputs include `data-series-picker.options`, `data-series-picker.value` and `data-history-request-store.data`.
5. Also locate `def refresh_archive_catalog(`, `def refresh_archive_generation(` and `def load_workspace(` in that file. Keep `query_workspace_bundle` and the server request parser.
6. If the app still has only `choose_history_request` and no unified `edit_workspace`, this replacement does not match that older layout. Do not paste a second selector alongside it. Match the running application's unified callback first.
7. Save copies of `cube/pages/data/s03_callbacks.py` and `cube/pages/data/s02_view.py` outside the app folder. If `assets/data_workspace_editor.js` already exists, save a copy of it too. Keep JavaScript backups outside `assets/`, because Dash loads JavaScript files from that folder.

## 2. Add the complete browser selection callback

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

## 3. Replace the Python selector with one browser registration

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

## 4. Make catalogue preparation independent of selection

1. Stay inside `register_callbacks` in `cube/pages/data/s03_callbacks.py`.
2. Find the decorated `refresh_archive_catalog` function. Keep its existing function body, helper call, error handling, Outputs and State arguments. There are two existing naming variants: one calls `load_data_catalog(manager, repository, cache_state)`; the other calls `load_archive_catalog(repository, cache_state, refresh_manager)`. Keep the version already working in your file, including its argument order. Do not rename one into the other.
3. In this callback's decorator, keep `Input("data-history-cache-state-store", "data")` and its existing committed-data revision Input. The revision is either `Input("data-revision-store", "data")` or `Input("refresh-commit-revision", "children")`. Keep the one your app already has; do not add a component or retain both alternatives merely for this repair.
4. Remove any Input line in this callback whose component ID is `data-display-mode`, `data-series-picker`, `data-companion-picker`, `data-history-request-store`, `data-period` or `data-custom-range`. Remove any Input connected to the Play/Pause frame interval too. Remove the corresponding positional function parameter for each removed Input. These controls do not determine which identities exist. Keep all other parameter names and the body unchanged.
5. If the only Inputs are already the cache-state and committed-data revision from item 3, no Input removal is needed. Keep that callback as it is. Ensure its `prevent_initial_call` is `False`; if it is explicitly `True`, replace that value with `False`. Omitting the setting already uses the default initial call.
6. Keep the bulk `SearchCatalog.history_identities()` implementation, its `data_history_identities()` manager delegate, and the existing catalogue helper using that bulk method. Keep its current-data plus archive merge and generation/revision checks.

The catalogue is prepared when committed data or archive metadata changes, including the initial page load. Ordinary selector edits reuse it in the browser. Risk and Market share one catalogue, but their available exact identities can differ; Both includes both kinds.

## 5. Stop selection from restarting metadata preparation

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

## 6. Avoid reading the same history twice during initial navigation

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

## 7. Check syntax and callback ownership, then restart

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
5. Confirm `refresh_archive_catalog` has only the two Inputs shown in step 4 and `refresh_archive_generation` has only the two Inputs shown in step 5.
6. Restart the app using the same startup command or notebook cell you normally use.
7. Hard-refresh the browser so it downloads the new JavaScript asset. Keep your normal JupyterHub application URL and prefix.
8. If Dash reports that `cube.workspaceEditor` is missing, check that the new `.js` file is inside the actual top-level assets folder used by the app. Open the browser console for a JavaScript syntax error, correct the reported line from the complete block, restart and hard-refresh again. Do not create a second Python selector to work around a missing asset.

## 8. Check the behaviour in this order

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

## 9. If something is still slow, identify which wait remains

1. If **Choose a series stays empty after Quick**, check that the JavaScript asset loaded, the old selector was removed, and the new callback uses catalogue `modified_timestamp` as Input with catalogue `data` as State. Check for duplicate-output or dependency-cycle errors in Dash.
2. If **Risk / Market / Both still causes a server callback**, check that the old Python selector is gone and the catalogue/loader Inputs match steps 4–6. In the browser Network panel, ordinary selector edits should not send a history request to `_dash-update-component`. The existing periodic metadata check may still appear independently.
3. If **the selection appears quickly but the chart takes time**, the remaining wait is history reading, processing or rendering. This guide preserves the requested date range. Choose MTD and press Load to compare with All; do not silently truncate history or remove size checks to hide the delay.
4. If **Data itself does not appear until much later**, record whether the delay occurs before navigation, during application cold start, or after the selected identity is visible. A browser selector repair cannot remove a slow provider call or a queued server navigation callback.
5. If **Preparing history metadata… never clears**, inspect the Data Diagnostics status and server message from the metadata callback. Confirm the enabled interval and initial callback in step 5. Fix a reported archive-path or metadata error; do not bypass server validation.

To undo only this repair, stop the app, restore the saved `cube/pages/data/s03_callbacks.py` and `cube/pages/data/s02_view.py`, and restore or remove `assets/data_workspace_editor.js` according to whether it existed before. Restart and hard-refresh. Leave the earlier completed performance and Portfolio changes in place.
