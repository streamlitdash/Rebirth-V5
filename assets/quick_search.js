/* One label index per snapshot/filter scope; typing never calls the server. */
(function () {
    "use strict";
    const api = window.dash_clientside = window.dash_clientside || {};
    api.quickSearch = {
        options: function (index, query, current) {
            const unchanged = window.dash_clientside.no_update;
            if (!index || !Array.isArray(index.rows)) return [[], unchanged];
            const typed = String(query || "").slice(0, 256);
            const terms = typed.normalize("NFKC")
                .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
                .toLowerCase().replace(/ß/g, "ss").split(/[^a-z0-9]+/).filter(Boolean);
            const options = [];
            let selectedExists = !current;
            let selectedIncluded = false;
            for (const row of index.rows) {
                const value = row[0], label = row[1];
                if (value === current) selectedExists = true;
                if (options.length < 100 && terms.every(term => label.includes(term))) {
                    // Dash also filters these options locally. Preserve the typed
                    // phrase for matches already proven by the compact index.
                    options.push({label: value, value: value, search: typed + " " + label});
                    if (value === current) selectedIncluded = true;
                }
                if (options.length === 100 && selectedExists) break;
            }
            if (current && selectedExists && !selectedIncluded) {
                if (options.length === 100) options.pop();
                options.unshift({label: current, value: current, search: current});
            }
            // Typing changes only choices. Only a changed scope can invalidate
            // a selection; there is never an automatically chosen first result.
            return [options, selectedExists ? unchanged : null];
        }
    };
})();
