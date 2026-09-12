const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.join(__dirname, '..');
const factory = fs.readFileSync(path.join(root, 'cube/app/s07_factory.py'), 'utf8');
const callback = factory.match(/function\(committed, style, current\) \{[\s\S]*?\n        \}/)[0];
const noUpdate = Symbol('no_update');
const mirror = vm.runInNewContext(`(${callback})`, {window: {dash_clientside: {no_update: noUpdate}}});
assert.equal(mirror(7, {display: 'none'}, null), noUpdate, 'No hidden initial render');
assert.equal(mirror(7, {}, null), 7, 'First visible render');
assert.equal(mirror(7, {}, 7), noUpdate, 'An unchanged return does not trigger tables');
assert.equal(mirror(8, {display: 'none'}, 7), noUpdate, 'Hidden refresh does not rebuild Risk');
assert.equal(mirror(8, {}, 7), 8, 'Return catches up with the latest committed revision');
assert.equal(mirror(8, {}, 8), noUpdate, 'Only one catch-up publication');

const elements = new Map([
  ['risk-page-host', {style: {display: 'none'}}],
  ['risk-type-tabs', {}], ['data-page', {}],
  ['ag-pl-details', {open: true}],
]);
let participants;
const scope = {
  document: {getElementById: id => elements.get(id) || null},
  window: {
    location: {pathname: '/cube/data'},
    dash_clientside: {no_update: noUpdate},
    __cubeV5Assets: {
      refreshPageChanged(_page, owners) {participants = owners;},
      prepareRefreshViews(_revision, owners) {participants = owners;},
      noteStartupLayoutReady() {},
    },
  },
};
vm.runInNewContext(fs.readFileSync(path.join(root, 'assets/refresh_views.js'), 'utf8'), scope);
const publish = scope.window.dash_clientside.cubeRefresh.publish;
assert.equal(publish(1, 8, 7, 'aggregate-pl'), 8);
assert.deepEqual(Array.from(participants), ['data-history'], 'Hidden Risk does not own the Data hero');
// Native routing can finish before the Risk visibility response arrives.
elements.get('risk-page-host').style = {};
publish(2, 8, 8, 'aggregate-pl');
assert.deepEqual(Array.from(participants), ['data-history'], 'URL wins during the routing transition');
elements.delete('data-page');
scope.window.location.pathname = '/cube/';
publish(3, 8, 8, 'aggregate-pl');
assert.deepEqual(Array.from(participants), ['risk-explorer', 'aggregate-pl']);
console.log('Risk retention: unchanged navigation, hidden refresh, revision catch-up and hero ownership passed.');
