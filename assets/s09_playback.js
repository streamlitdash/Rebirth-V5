/* Data has one local label search and one player for the selected small bundles. */
(() => {
  "use strict";
  const normal = value => String(value ?? "").normalize("NFKC").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  let previousCurrent, previousArchive, index = [];
  function search(current, archive, query, selected, value) {
    if (current !== previousCurrent || archive !== previousArchive) {
      const rows = [];
      for (const kind of ["risk", "market"]) {
        for (const label of current?.[kind] || []) {
          rows.push([`${kind === "risk" ? "Risk" : "Market"} · ${label}`, JSON.stringify([kind, label])]);
        }
      }
      rows.push(...(archive?.choices || []));
      index = rows.map(([label, token]) => ({label, value: token, search: normal(label) + " " + normal(label).replaceAll(" ", "")}));
      previousCurrent = current;
      previousArchive = archive;
    }
    const terms = normal(query).split(" ").filter(Boolean);
    const options = [];
    for (const option of index) {
      if (terms.every(term => option.search.includes(term))) options.push(option);
      if (options.length === 50) break;
    }
    if (selected?.value === value && !options.some(option => option.value === value)) options.unshift(selected);
    if (options.length > 50) options.length = 50;
    return [options, index.length ? `Search ${index.length.toLocaleString()} current and archived series. Up to 50 matches shown.` : "Current choices will appear after the first refresh."];
  }

  const finite = value => value === null || value === undefined || value === "" || !Number.isFinite(Number(value)) ? null : Number(value);
  const empty = message => ({data: [], layout: {template: "plotly_white", height: 420,
    margin: {l: 60, r: 25, t: 40, b: 60}, annotations: [{text: message, x: .5, y: .5, xref: "paper", yref: "paper", showarrow: false}]}});
  function selectedRows(bundle, day) {
    return (bundle?.values || []).filter(row => String(row[bundle.date_column]) === day);
  }
  function figure(bundle, day, error) {
    if (!bundle || !bundle.values?.length) return empty(error || "No observations for this selection and period.");
    const axes = bundle.axes || [], metric = bundle.metric_column;
    const rows = selectedRows(bundle, day);
    const layout = {template: "plotly_white", height: 420, autosize: true,
      margin: {l: 65, r: 30, t: 35, b: 65}, paper_bgcolor: "#fff", plot_bgcolor: "#fff",
      font: {family: "Arial, sans-serif", size: 12, color: "#1e293b"},
      hovermode: axes.length < 2 ? "x unified" : "closest", uirevision: bundle.key,
      xaxis: {showgrid: false, zeroline: false}, yaxis: {gridcolor: "#e8edf3", tickformat: ",.2f", zerolinecolor: "#cbd5e1"}};
    if (!axes.length) {
      layout.xaxis.title = {text: "Date"};
      layout.yaxis.title = {text: metric};
      return {data: [{type: "scatter", mode: "lines+markers", x: bundle.values.map(row => row[bundle.date_column]),
        y: bundle.values.map(row => finite(row[metric])), line: {color: bundle.kind === "risk" ? "#4C8A4A" : "#2563eb", width: 2}, marker: {size: 5},
        connectgaps: false, name: metric, hovertemplate: "%{x}<br>%{y:,.2f}<extra></extra>"}], layout};
    }
    if (!rows.length) return empty(`No observation on ${day}. Choose a date with data for this series.`);
    if (axes.length === 1) {
      const axis = axes[0], byLabel = new Map(rows.map(row => [String(row[axis.column]), finite(row[metric])]));
      layout.xaxis = {...layout.xaxis, title: {text: axis.column}, type: "category", categoryorder: "array", categoryarray: axis.labels};
      layout.yaxis.title = {text: metric};
      return {data: [{type: "scatter", mode: "lines+markers", x: axis.labels, y: axis.labels.map(label => byLabel.get(label) ?? null),
        line: {color: bundle.kind === "risk" ? "#4C8A4A" : "#2563eb", width: 2}, marker: {size: 6}, connectgaps: false, name: metric,
        hovertemplate: "%{x}<br>%{y:,.2f}<extra></extra>"}], layout};
    }
    const swap = axes.find(axis => axis.column === "Tenor Swap") || axes[0];
    const option = axes.find(axis => axis.column === "Tenor Option") || axes[1];
    const cells = new Map(rows.map(row => [JSON.stringify([String(row[swap.column]), String(row[option.column])]), finite(row[metric])]));
    const z = option.labels.map(o => swap.labels.map(s => cells.get(JSON.stringify([s, o])) ?? null));
    layout.xaxis = {title: {text: swap.column}, type: "category", categoryorder: "array", categoryarray: swap.labels};
    layout.yaxis = {title: {text: option.column}, type: "category", categoryorder: "array", categoryarray: option.labels, autorange: "reversed"};
    const heat = {type: "heatmap", x: swap.labels, y: option.labels, z, xgap: 1, ygap: 1,
      colorscale: bundle.kind === "risk" ? [[0,"#C26464"],[.5,"#FCFCFA"],[1,"#4C8A4A"]] : "Viridis",
      colorbar: {title: {text: metric}, tickformat: ",.2f", thickness: 12}, hoverongaps: false,
      hovertemplate: `${swap.column}: %{x}<br>${option.column}: %{y}<br>${metric}: %{z:,.2f}<extra></extra>`};
    if (bundle.kind === "risk") {
      let extent = 1;
      for (const row of z) for (const value of row) if (value !== null) extent = Math.max(extent, Math.abs(value));
      heat.zmin = -extent; heat.zmax = extent;
    }
    return {data: [heat], layout};
  }

  function table(bundle, day) {
    const rows = selectedRows(bundle, day);
    if (!bundle) return [[], [], []];
    const names = [bundle.date_column, ...(bundle.axes || []).map(axis => axis.column), bundle.metric_column];
    const columns = names.map(id => id === bundle.metric_column ? {name: id, id, type: "numeric", format: {specifier: ",.2f"}} : {name: id, id, type: "text"});
    const style = [{if: {column_id: bundle.metric_column, filter_query: `{${bundle.metric_column}} < 0`}, color: "#b91c1c"}];
    return [rows.map(row => Object.fromEntries(names.map(name => [name, row[name]]))), columns, style];
  }

  function play(payload, clicks, ticks, slider, visibility, prior) {
    const bundles = payload?.bundles || {}, mode = payload?.mode || "risk";
    const dates = [...new Set(Object.values(bundles).flatMap(bundle => bundle?.dates || []))].sort();
    const old = prior || {}, changed = old.key !== payload?.key;
    const count = dates.length;
    let at = changed ? Math.max(0, count - 1) : Math.max(0, Math.min(Number(old.index) || 0, count - 1));
    let playing = !changed && Boolean(old.playing) && count > 1;
    if (document.hidden || visibility?.hidden) playing = false;
    else if (!changed && Number(clicks || 0) !== Number(old.clicks || 0)) playing = !playing && count > 1;
    else if (!changed && Number(ticks || 0) !== Number(old.ticks || 0) && playing) at = (at + 1) % count;
    else if (!changed && Number(slider) !== at && Number.isInteger(Number(slider))) { at = Math.max(0, Math.min(Number(slider), count - 1)); playing = false; }
    const day = dates[at] || "No date", marks = {};
    if (count) { marks[0] = dates[0]; marks[count - 1] = dates[count - 1]; }
    const [riskRows, riskColumns, riskStyle] = table(bundles.risk, day);
    const [marketRows, marketColumns, marketStyle] = table(bundles.market, day);
    const title = kind => `${kind === "risk" ? "Risk" : "Market"}${bundles[kind] ? " · " + bundles[kind].handoff.identity.underlying : ""}`;
    return [figure(bundles.risk, day, payload?.errors?.risk), figure(bundles.market, day, payload?.errors?.market),
      riskRows, riskColumns, marketRows, marketColumns, riskStyle, marketStyle,
      mode === "market" ? {display: "none"} : {}, mode === "risk" ? {display: "none"} : {}, title("risk"), title("market"),
      Math.max(0, count - 1), marks, at, count < 2, day, playing ? "Pause" : "Play", count < 2, !playing,
      {key: payload?.key || null, index: at, playing, clicks: Number(clicks || 0), ticks: Number(ticks || 0)},
      payload?.key || "", payload?.refresh ? {...payload.refresh, mounts: [payload.key]} : window.dash_clientside.no_update];
  }
  let lastSearch;
  function searchCurrent(query, selected, _tick, current, archive, value) {
    const args = [query, selected, current, archive, value];
    if (lastSearch && args.every((arg, i) => arg === lastSearch[i])) {
      return [window.dash_clientside.no_update, window.dash_clientside.no_update];
    }
    lastSearch = args;
    return search(current, archive, query, selected, value);
  }
  window.dash_clientside = Object.assign({}, window.dash_clientside, {cubeData: {
    search, play,
    searchCurrent,
  }});
})();
