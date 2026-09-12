/* Risk Explorer styling; Python owns all totals and promotion decisions. */
(() => {
  'use strict';
  const rowHeight = 36, overscan = 10;
  const number = new Intl.NumberFormat('en-GB', {minimumFractionDigits: 2, maximumFractionDigits: 2});
  let rows = [], root, body, sequence = 0, pending = false, anchor;
  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  function paint() {
    if (!root?.isConnected || !body) return;
    const start = Math.max(0, Math.floor(root.scrollTop / rowHeight) - overscan);
    const end = Math.min(rows.length, start + Math.ceil(root.clientHeight / rowHeight) + 2 * overscan);
    const fragment = document.createDocumentFragment();
    const spacer = height => {
      const tr = element('tr'), td = element('td');
      td.colSpan = 3;
      td.style.cssText = `height:${height}px;padding:0;border:0;`;
      tr.setAttribute('aria-hidden', 'true'); tr.append(td); fragment.append(tr);
    };
    spacer(start * rowHeight);
    for (let index = start; index < end; index++) {
      const row = rows[index], item = JSON.parse(row.id), depth = JSON.parse(item.path).length - 1;
      const label = row.Hierarchy.replace(/^\s*[▾▸]?\s*/, '').replace(/ · Promoted$/, '');
      const tr = element('tr', undefined, 'group-row' + (depth === 0 ? ' hierarchy-total-row' : ''));
      tr.dataset.stockIndex = index; tr.setAttribute('aria-rowindex', index + 2);
      const th = element('th', undefined, 'index-cell'); th.scope = 'row'; th.style.paddingLeft = `${14 + depth * 18}px`;
      const toggle = element('button', item.branch ? (item.open ? '▾' : '▸') : '', 'row-toggle');
      toggle.type = 'button'; toggle.disabled = !item.branch; toggle.dataset.stockAction = 'toggle';
      toggle.setAttribute('aria-expanded', String(item.open));
      toggle.setAttribute('aria-label', (item.open ? 'Collapse ' : 'Expand ') + label);
      const name = element(item.selection || item.branch ? 'button' : 'span', label, 'row-label-text row-detail-button');
      if (name.tagName === 'BUTTON') { name.type = 'button'; name.dataset.stockAction = item.selection ? 'history' : 'toggle'; }
      th.append(toggle, name);
      if (row.Promoted) th.append(element('span', 'Promoted', 'promotion-badge'));
      tr.append(th);
      for (const metric of ['Stock', 'dStock']) {
        const value = row[metric];
        tr.append(element('td', value === null ? '' : number.format(value), 'metric-cell ' + (value < 0 ? 'number-negative' : 'number-positive')));
      }
      fragment.append(tr);
    }
    spacer((rows.length - end) * rowHeight);
    body.replaceChildren(fragment);
    root.querySelector('table').setAttribute('aria-rowcount', rows.length + 1);
  }
  function mount(next) {
    root = next;
    const table = element('table', undefined, 'risk-table stock-hierarchy-table');
    const head = element('thead'), header = element('tr');
    ['Hierarchy', 'Stock', 'dStock'].forEach((label, i) => header.append(element('th', label, i ? 'metric-header' : 'index-header')));
    head.append(header); body = element('tbody'); body.id = 'stock-tree-body';
    table.append(head, body); root.replaceChildren(table);
    root.addEventListener('scroll', () => {
      if (pending) return;
      pending = true; requestAnimationFrame(() => { pending = false; paint(); });
    }, {passive: true});
    root.addEventListener('click', event => {
      const button = event.target.closest('button[data-stock-action]');
      if (!button || button.disabled) return;
      const tr = button.closest('tr'), selected = JSON.parse(rows[Number(tr.dataset.stockIndex)].id);
      anchor = {path: selected.path, offset: Number(tr.dataset.stockIndex) * rowHeight - root.scrollTop};
      window.dash_clientside.set_props('stock-row-action', {data: {
        row: selected, kind: button.dataset.stockAction,
        open_paths: rows.map(row => JSON.parse(row.id)).filter(row => row.open).map(row => row.path),
        sequence: ++sequence,
      }});
    });
  }
  window.addEventListener('resize', paint);
  const api = window.dash_clientside = window.dash_clientside || {};
  api.stockTree = {render(records) {
    const next = document.getElementById('stock-current-table');
    if (!next || !records) return window.dash_clientside.no_update;
    if (root !== next) { anchor = null; mount(next); }
    rows = records;
    if (anchor) {
      const index = rows.findIndex(row => JSON.parse(row.id).path === anchor.path);
      if (index >= 0) root.scrollTop = Math.max(0, index * rowHeight - anchor.offset);
      anchor = null;
    }
    root.scrollTop = Math.min(root.scrollTop, Math.max(0, (rows.length + 1) * rowHeight - root.clientHeight));
    paint();
    return String(++sequence);
  }};
})();
