const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const frames = [], timers = [], received = [];
let plotting = true;
const plain = {matches: () => false, querySelector: () => null, querySelectorAll: () => []};
const graph = {
  matches: () => false,
  querySelector(selector) {return selector === '.dash-graph--pending' && plotting ? {} : null;},
  querySelectorAll: () => [{querySelector: () => ({_fullLayout: {}})}],
};
const nodes = new Map([['stock-page', plain], ['stock-current-table', plain]]);
const scope = {
  requestAnimationFrame: callback => frames.push(callback),
  setTimeout: callback => timers.push(callback),
  document: {getElementById: id => nodes.get(id) || null, querySelector: () => plain},
  window: {
    location: {pathname: '/stock'}, dash_clientside: {no_update: null},
    __cubeV5Assets: {
      refreshPageChanged() {}, prepareRefreshViews() {}, noteStartupLayoutReady() {},
      receiveRefreshViewAck: receipt => received.push(receipt),
    },
  },
};
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../assets/refresh_views.js'), 'utf8'), scope);
scope.window.dash_clientside.cubeRefresh.publish(1, 9, 9, null, {
  owner: 'stock-current', revision: 9, request_id: null,
  mounts: ['receipt-stamp'], ready_ids: ['stock-current-table', 'stock-history-chart'],
});
while (frames.length) frames.shift()();
assert.equal(received.length, 0, 'Wait for the new graph DOM to mount');
nodes.set('stock-history-chart', graph);
timers.shift()();
assert.equal(received.length, 0, 'An old fullLayout is insufficient while Plotly.react is pending');
plotting = false;
timers.shift()();
assert.equal(received.length, 1, 'Acknowledge once the updated graph finishes');
console.log('Refresh completion waits for updated table/graph targets and the Plotly promise.');
