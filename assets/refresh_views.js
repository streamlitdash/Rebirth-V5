/* The publisher never waits for renderers before publishing their revision. */
(() => {
    "use strict";
    const queued = new Map();
    let mountedPage = null;
    const node = (id) => document.getElementById(id);
    const open = (id) => Boolean(node(id)?.open);
    const riskVisible = () => Boolean(node("risk-type-tabs"))
        && node("risk-page-host")?.style.display !== "none";
    const editorOpen = (section) => Boolean(node(`pl-${section}-summary`)?.closest("details")?.open);
    const pageTail = () => window.location.pathname.replace(/\/+$/, "").split("/").pop();
    const visibleOwners = (workspace) => {
        const tail = pageTail();
        if (!["pnl", "data", "stock", "static-data"].includes(tail) && riskVisible()) {
            const owners = ["risk-explorer"];
            if (open("ag-pl-details")) {
                if (workspace === "aggregate-pl") owners.push("aggregate-pl");
                if (workspace === "top-promotions") owners.push("top-promotions");
                if (workspace === "quick-risk") owners.push("quick-risk-options", "quick-risk-table", "quick-risk-chart");
                if (workspace === "quick-market") owners.push("quick-market-options", "quick-market");
            }
            if (open("unmapped-books-details")) owners.push("unmapped-books");
            return owners;
        }
        if (tail === "pnl" && node("pnl-page-container")) {
            const owners = ["pnl-summary"];
            for (const section of ["sog", "portfolio"]) if (editorOpen(section)) owners.push(`pnl-editor-${section}`);
            return owners;
        }
        if (tail === "data" && node("data-page")) return ["data-history"];
        if (tail === "stock" && node("stock-current-table")) return ["stock-current"];
        return [];
    };
    const pageMounted = () => {
        // During routing, the old page can still exist after pathname changes.
        // Wait for the requested root; a temporary DOM gap retires nothing.
        const tail = pageTail();
        const expected = {pnl: "pnl-page-container", data: "data-page", stock: "stock-page", "static-data": "static-data-page"}[tail];
        return expected ? Boolean(node(expected)) : riskVisible();
    };
    const graphReady = (root) => {
        if (root.matches?.(".dash-graph--pending") || root.querySelector(".dash-graph--pending")) return false;
        const graphs = [...root.querySelectorAll(".dash-graph")];
        if (root.matches?.(".dash-graph")) graphs.push(root);
        return graphs.every(graph => Boolean(graph.querySelector(".js-plotly-plot")?._fullLayout));
    };
    const queueAck = (ack, pageKey) => {
        if (!ack?.owner) return;
        const signature = JSON.stringify(ack);
        const previous = queued.get(ack.owner);
        if (previous?.signature === signature && previous.pageKey === pageKey) return;
        const pending = {signature, pageKey, cancelled: false};
        if (previous) previous.cancelled = true;
        queued.set(ack.owner, pending);
        // Two frames let React mount the callback outputs and start Plotly.react.
        const check = () => {
            if (pending.cancelled || mountedPage !== pageKey) return;
            const roots = [
                ...(ack.mounts || []).map(id => document.querySelector(`[data-refresh-render="${id}"]`)),
                ...(ack.ready_ids || []).map(node),
            ];
            if (roots.some(root => !root || !graphReady(root))) {
                setTimeout(check, 100);
                return;
            }
            window.__cubeV5Assets?.receiveRefreshViewAck({...ack, pageKey});
        };
        requestAnimationFrame(() => requestAnimationFrame(check));
    };
    window.dash_clientside = window.dash_clientside || {};
    window.dash_clientside.cubeRefresh = {
        publish(_tick, committed, published, workspace, ...acks) {
            const assets = window.__cubeV5Assets;
            const noUpdate = window.dash_clientside.no_update;
            if (!assets || !pageMounted()) return noUpdate;
            const owners = visibleOwners(workspace);
            // A real workspace/open-panel change explicitly supersedes the
            // former presentation targets; it never cancels backend work.
            const pageKey = JSON.stringify([window.location.pathname, owners]);
            if (mountedPage !== pageKey) {
                mountedPage = pageKey;
                for (const pending of queued.values()) pending.cancelled = true;
                queued.clear();
                assets.refreshPageChanged(pageKey, owners);
            }
            const current = Number(published || 0);
            assets.observedPublishedDataRevision = current;
            const revision = Math.max(Number(committed || 0), Number(assets.pendingCommittedDataRevision || 0), current);
            if (!Number.isSafeInteger(revision) || revision <= 0) return noUpdate;
            assets.prepareRefreshViews(revision, owners);
            const requestId = assets.refreshDiagnostics?.()?.request_id || null;
            for (const ack of acks) {
                if (ack && owners.includes(ack.owner)
                    && Number(ack.revision) === revision
                    && (ack.request_id || null) === requestId) queueAck(ack, pageKey);
            }
            assets.noteStartupLayoutReady();
            return revision > current ? revision : noUpdate;
        },
    };
})();
