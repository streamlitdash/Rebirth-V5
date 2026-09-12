const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const asset = fs.readFileSync(require('node:path').join(__dirname, '../assets/s12_refresh.js'), 'utf8');
function element(id) {
  const classes = new Set();
  const children = new Map();
  return {
    id, hidden: true, textContent: '', dataset: {}, isConnected: true,
    style: {width:'', removeProperty(){}},
    classList: {toggle(name,on){if(on)classes.add(name);else classes.delete(name);},contains(name){return classes.has(name);}},
    querySelector(selector){if(!children.has(selector))children.set(selector,{textContent:''});return children.get(selector);},
  };
}
function fixture({cold=false}={}) {
  let now = 100000;
  const elements = new Map();
  for (const id of ['backend-endpoints','refresh-progress','refresh-progress-title','refresh-progress-elapsed',
    'refresh-progress-function','refresh-progress-source','refresh-progress-product','refresh-progress-count',
    'refresh-progress-hold','refresh-progress-bar-track','refresh-progress-bar','refresh-commit-revision',
    'shared-refresh-shell','cube-page-container','risk-type-tabs','refresh-status',
    ...['readiness','risk','market','pl','final'].map(stage=>'refresh-stage-'+stage)]) elements.set(id,element(id));
  elements.get('backend-endpoints').dataset={startUrl:'/prefix/startz',progressUrl:'/prefix/progressz'};
  elements.get('refresh-progress').dataset.initialLoad=String(cold);
  elements.get('refresh-commit-revision').textContent=cold?'0':'7';
  const animation=[]; const intervals=[]; const timeouts=[]; const requests=[]; const pending=[];
  let last={running:false,attempt_id:'old',revision:cold?0:7,server_boot_id:'boot',startup_phase:cold?'idle':'succeeded',startup_attempt_id:cold?'':'startup-old',startup_worker_alive:false};
  const scope={URL,AbortController,Map,Set,Math,Number,String,Boolean,JSON,console,
    Date:class extends Date {static now(){return now;}},
    setInterval(fn){intervals.push(fn);return intervals.length;},clearInterval(){},
    setTimeout(fn){timeouts.push(fn);return timeouts.length;},clearTimeout(){},
    MutationObserver:class {constructor(fn){this.fn=fn;}observe(){}disconnect(){}},
    document:{body:{},baseURI:'https://cube.test/prefix/',getElementById(id){return elements.get(id)||null;},
      querySelectorAll(){return [];},addEventListener(){}},
    fetch:async(url,options)=>{requests.push({url,options});
      if(options.method==='POST')return{ok:true,status:202,headers:{get:()=> 'application/json'},json:async()=>({accepted:true})};
      let value=pending.length?pending.shift():last;
      if(value instanceof Error)throw value;
      last=value;
      return{ok:true,status:200,headers:{get:()=> 'application/json'},json:async()=>({...value})};},
  };
  scope.window={location:{pathname:'/prefix/',origin:'https://cube.test'},requestAnimationFrame(fn){animation.push(fn);},
    __cubeV5Assets:{setGlobalLoaderVisible(value){scope.loader=value;}}};
  vm.createContext(scope);vm.runInContext(asset,scope);
  const app=scope.window.__cubeV5Assets;
  async function flush(){for(let i=0;i<15;i++)await Promise.resolve();let count=0;while(animation.length){animation.shift()();assert.ok(++count<100,'paint queue bounded');}}
  async function sample(value){pending.push(value);now+=40000;intervals[0]();await flush();}
  async function begin(id,mode='pl',value=last){pending.push(value);const accepted=app.beginRefreshRequest({id,trigger:'refresh-pl-button',count:1,mode,requested_at:now});if(!accepted)pending.pop();await flush();return accepted;}
  return{app,scope,elements,pending,requests,flush,sample,begin,advance(ms){now+=ms;},
    result(id,outcome='complete',rev=8,extra={}){return app.receiveRefreshResult({request_id:id,outcome,revision:rev,server_boot_id:'boot',message:'',error:'',...extra});},
    ack(owner,rev,status='rendered'){return app.receiveRefreshViewAck({owner,revision:rev,status,request_id:app.refreshDiagnostics()?.request_id||null});},
    progress(attempt,stage='risk',rev=7){return{running:true,attempt_id:attempt,server_boot_id:'boot',revision:rev,stage,function_name:'get_'+stage,product_index:1,product_total:4,startup_phase:'succeeded',startup_attempt_id:'startup-old',startup_worker_alive:false};},
    snapshot(){return JSON.parse(JSON.stringify(app.refreshDiagnostics()));}};
}
(async()=>{
  let cases=0;
  const f=fixture();
  assert.equal(await f.begin('one'),true);assert.equal(f.snapshot().phase,'requested');cases++;
  await f.sample(f.progress('A','risk'));assert.equal(f.snapshot().phase,'data');assert.equal(f.elements.get('refresh-progress-function').textContent,'get_risk');
  await f.sample({...f.progress('A','market'),product_index:3});assert.equal(f.elements.get('refresh-progress-function').textContent,'get_market');assert.equal(f.elements.get('refresh-progress-count').textContent,'3 of 4');cases++;
  assert.equal(await f.begin('blocked'),false);assert.equal(f.snapshot().request_id,'one');cases++;
  await f.sample({...f.progress('A','complete',8),running:false,finished_at:'now'});assert.equal(f.snapshot().phase,'finishing');assert.equal(f.snapshot().active,true);cases++;
  f.result('one');await f.flush();assert.equal(f.snapshot().phase,'views');assert.equal(f.app.pendingCommittedDataRevision,8);assert.equal(f.snapshot().participants_established,false);cases++;
  f.app.prepareRefreshViews(8,['risk','aggregate']);f.ack('risk',8);f.ack('aggregate',7);await f.flush();assert.deepEqual(f.snapshot().pending_views,['aggregate']);assert.equal(f.snapshot().active,true);
  f.ack('aggregate',8);await f.flush();assert.equal(f.snapshot().phase,'complete');assert.equal(f.snapshot().active,false);assert.equal(f.elements.get('refresh-progress').hidden,false);cases++;
  const panel=element('refresh-progress');f.elements.set('refresh-progress',panel);f.app.syncRefreshLifecycleNodes();await f.flush();assert.equal(panel.hidden,false);assert.equal(panel.classList.contains('is-complete'),true);cases++;
  await f.begin('two','pl',f.progress('B'));assert.equal(f.snapshot().request_id,'two');assert.equal(f.snapshot().phase,'data');
  f.result('one','failed',7,{error:'late wrong result'});assert.equal(f.snapshot().callback_pending,true);
  f.result('two','failed',8,{error:'same error'});await f.flush();assert.equal(f.snapshot().phase,'failed');assert.equal(f.elements.get('refresh-progress-product').textContent,'same error');
  await f.begin('three','pl',f.progress('C', 'risk',8));f.result('three','failed',8,{error:'same error'});await f.flush();assert.equal(f.snapshot().phase,'failed');assert.equal(f.elements.get('refresh-progress-product').textContent,'same error');cases++;
  await f.begin('four','pl',f.progress('D','risk',8));await f.sample(new Error('offline'));assert.equal(f.snapshot().active,true);assert.match(f.elements.get('refresh-progress-title').textContent,/interrupted/);
  await f.sample(f.progress('D','pl',8));assert.equal(f.elements.get('refresh-progress-function').textContent,'get_pl');cases++;
  f.result('four','complete',9);f.app.prepareRefreshViews(9,['risk']);f.ack('risk',9,'failed');await f.flush();assert.equal(f.snapshot().phase,'failed');assert.match(f.elements.get('refresh-progress-product').textContent,/risk/);cases++;
  await f.begin('five','pl',f.progress('E','market',9));f.result('five','complete',10);f.app.prepareRefreshViews(10,['risk','aggregate']);f.ack('risk',10);await f.flush();assert.equal(f.snapshot().active,true);
  assert.equal(await f.begin('six','pl',f.progress('F','market',10)),true);f.result('six','complete',11);f.app.prepareRefreshViews(11,['risk']);f.ack('aggregate',10);f.ack('risk',11);await f.flush();assert.equal(f.snapshot().phase,'complete');assert.equal(f.snapshot().target_revision,11);cases++;
  await f.begin('seven','pl',f.progress('G','risk',11));f.result('seven','busy',11,{message:'Another writer is running'});await f.flush();assert.equal(f.snapshot().phase,'busy');assert.equal(f.snapshot().active,false);cases++;
  await f.begin('eight','pl',f.progress('H','risk',11));await f.sample({...f.progress('other'),server_boot_id:'new-boot'});assert.equal(f.snapshot().phase,'interrupted');cases++;
  const c=fixture({cold:true});
  c.pending.push({...c.progress('cold-A'),revision:0,startup_phase:'running',startup_attempt_id:'S',startup_worker_alive:true});
  c.app.startRefreshProgress('bootstrap');await c.flush();assert.equal(c.snapshot().phase,'data');assert.equal(c.elements.get('refresh-progress-function').textContent,'get_risk');
  c.app.receiveStartupLayout({server_boot_id:'boot',startup_attempt_id:'S',revision:1,status:'rendered'});
  c.app.prepareRefreshViews(1,['risk','aggregate']);c.ack('risk',1);c.ack('aggregate',1);
  await c.sample({...c.progress('cold-A','complete',1),running:false,startup_phase:'succeeded',startup_attempt_id:'S',startup_worker_alive:true});assert.equal(c.snapshot().active,true);assert.equal(c.snapshot().target_revision,null);cases++;
  await c.sample({...c.progress('cold-A','complete',1),running:false,startup_phase:'succeeded',startup_attempt_id:'S',startup_worker_alive:false});assert.equal(c.snapshot().phase,'complete');assert.equal(c.app.pendingCommittedDataRevision,1);cases++;
  const r=fixture();await r.begin('route','pl',r.progress('R'));r.result('route','complete',8);r.app.prepareRefreshViews(8,['risk']);
  r.app.refreshPageChanged('/pnl',['pnl-summary']);r.ack('risk',8);await r.flush();assert.deepEqual(r.snapshot().pending_views,['pnl-summary']);r.ack('pnl-summary',8);await r.flush();assert.equal(r.snapshot().phase,'complete');cases++;
  const x=fixture();await x.begin('fast');x.app.prepareRefreshViews(8,[]);x.result('fast','complete',8);await x.flush();assert.equal(x.snapshot().phase,'complete');assert.equal(x.snapshot().active,false);cases++;
  const e=fixture();await e.begin('both');e.result('both','complete',8);e.app.prepareRefreshViews(8,['risk','aggregate']);e.ack('risk',8,'failed');await e.flush();
  assert.equal(e.snapshot().active,true);assert.deepEqual(e.snapshot().pending_views,['aggregate']);assert.match(e.elements.get('refresh-progress-product').textContent,/risk/);
  assert.equal(e.app.receiveRefreshViewAck({owner:'aggregate',revision:8,status:'rendered',request_id:'wrong'}),false);
  e.ack('aggregate',8);await e.flush();assert.equal(e.snapshot().phase,'failed');assert.equal(e.snapshot().active,false);cases++;
  const retry=fixture({cold:true});retry.pending.push({...retry.progress('failed-A'),running:false,startup_phase:'failed',startup_attempt_id:'fail-S',startup_worker_alive:false,error:'same startup error'});retry.app.startRefreshProgress('bootstrap');await retry.flush();assert.equal(retry.snapshot().phase,'failed');
  retry.pending.push({...retry.progress('failed-A'),running:false,startup_phase:'failed',startup_attempt_id:'fail-S',startup_worker_alive:false,error:'same startup error'});retry.app.startRefreshProgress('bootstrap');await retry.flush();assert.equal(retry.snapshot().phase,'requested');assert.equal(retry.snapshot().active,true);
  await retry.sample({...retry.progress('retry-A'),revision:0,startup_phase:'running',startup_attempt_id:'retry-S',startup_worker_alive:true});assert.equal(retry.snapshot().phase,'data');assert.equal(retry.snapshot().startup_attempt_id,'retry-S');cases++;
  const ready=fixture();await ready.sample({...ready.progress('already-done','complete',7),running:false,startup_phase:'succeeded',startup_attempt_id:'already-S',startup_worker_alive:false});
  assert.equal(ready.snapshot().active,true);assert.equal(ready.snapshot().layout_ready,false);
  ready.app.prepareRefreshViews(7,['risk']);ready.ack('risk',7);ready.app.noteStartupLayoutReady();await ready.flush();assert.equal(ready.snapshot().phase,'complete');cases++;
  const lost=fixture();await lost.begin('lost','pl',lost.progress('lost-A'));
  await lost.sample({...lost.progress('lost-A','complete',8),running:false});
  assert.equal(lost.app.beginRefreshRequest({id:'auto-denied',trigger:'auto-refresh-interval',mode:'automatic'}),false);
  lost.elements.get('refresh-status').classList.toggle('is-refreshing',true);
  assert.equal(lost.app.beginRefreshRequest({id:'still-busy',trigger:'refresh-pl-button',mode:'pl'}),false);
  lost.elements.get('refresh-status').classList.toggle('is-refreshing',false);
  assert.equal(lost.app.beginRefreshRequest({id:'deliberate-retry',trigger:'refresh-pl-button',mode:'pl'}),true);await lost.flush();
  assert.equal(lost.snapshot().request_id,'deliberate-retry');assert.equal(lost.snapshot().phase,'requested');cases++;
  const newer=fixture();await newer.begin('old-eight');newer.result('old-eight','complete',8);newer.app.prepareRefreshViews(8,['risk','aggregate']);newer.ack('risk',8);
  newer.app.prepareRefreshViews(9,['risk','aggregate']);newer.ack('aggregate',8);await newer.flush();assert.equal(newer.snapshot().target_revision,9);assert.deepEqual(newer.snapshot().pending_views,['risk','aggregate']);
  newer.ack('risk',9);newer.ack('aggregate',9);await newer.flush();assert.equal(newer.snapshot().phase,'complete');assert.equal(newer.elements.get('refresh-progress-product').textContent,'Validated snapshot is live');cases++;
  const disconnected=fixture({cold:true});const failedStartup={...disconnected.progress('fail'),running:false,startup_phase:'failed',startup_attempt_id:'failed-startup',startup_worker_alive:false,error:'startup failed'};
  disconnected.pending.push(failedStartup);disconnected.app.startRefreshProgress('bootstrap');await disconnected.flush();assert.equal(disconnected.snapshot().phase,'failed');
  const fetchNormally=disconnected.scope.fetch;disconnected.scope.fetch=async(url,options)=>{if(options.method==='POST')throw new Error('Start request offline');return fetchNormally(url,options);};
  disconnected.pending.push(failedStartup);disconnected.app.startRefreshProgress('bootstrap');await disconnected.flush();await disconnected.sample(failedStartup);
  assert.match(disconnected.elements.get('refresh-progress-title').textContent,/Startup request unconfirmed/);assert.match(disconnected.elements.get('refresh-progress-function').textContent,/offline/);cases++;
  const hide=fixture();await hide.begin('hide');hide.app.prepareRefreshViews(8,[]);hide.result('hide','complete',8);await hide.flush();
  assert.equal(hide.elements.get('refresh-progress').hidden,false);hide.advance(301);hide.app.syncRefreshLifecycleNodes();await hide.flush();assert.equal(hide.elements.get('refresh-progress').hidden,true);cases++;
  const remountHidden=element('refresh-progress');hide.elements.set('refresh-progress',remountHidden);hide.app.syncRefreshLifecycleNodes();await hide.flush();assert.equal(remountHidden.hidden,true);cases++;
  await hide.begin('new-visible','pl',hide.progress('new-visible-A','market',8));hide.advance(6000);hide.app.syncRefreshLifecycleNodes();await hide.flush();assert.equal(remountHidden.hidden,false);assert.equal(hide.elements.get('refresh-progress-title').textContent,'Refreshing P&L');cases++;
  hide.result('new-visible','failed',8,{error:'Warm failure'});await hide.flush();assert.equal(remountHidden.hidden,false);hide.advance(5001);hide.app.syncRefreshLifecycleNodes();await hide.flush();assert.equal(remountHidden.hidden,true);cases++;
  const retained=fixture({cold:true});retained.pending.push({...retained.progress('fail-cold'),running:false,startup_phase:'failed',startup_attempt_id:'fail-cold',startup_worker_alive:false,error:'Startup failed'});retained.app.startRefreshProgress('bootstrap');await retained.flush();retained.advance(60000);retained.app.syncRefreshLifecycleNodes();await retained.flush();assert.equal(retained.elements.get('refresh-progress').hidden,false);cases++;
  const rendering=fixture();await rendering.begin('rendering','pl',rendering.progress('rendering-A','market',7));rendering.result('rendering','complete',8);rendering.app.prepareRefreshViews(8,['risk']);await rendering.flush();
  assert.equal(rendering.snapshot().phase,'views');assert.equal(rendering.elements.get('refresh-stage-market').classList.contains('is-active'),false);assert.equal(rendering.elements.get('refresh-stage-final').classList.contains('is-active'),true);
  assert.equal(rendering.elements.get('refresh-progress-function').textContent,'Updating tables and charts');assert.equal(rendering.elements.get('refresh-progress-source').textContent,'');assert.equal(rendering.elements.get('refresh-progress-count').textContent,'');cases++;
  const anotherTab=fixture();await anotherTab.sample({...anotherTab.progress('other-tab','market',7),startup_phase:'succeeded'});assert.equal(anotherTab.snapshot(),null);await anotherTab.sample({...anotherTab.progress('other-tab','complete',8),running:false,startup_phase:'succeeded'});assert.equal(anotherTab.snapshot(),null);assert.equal(anotherTab.app.pendingCommittedDataRevision,8);cases++;
  rendering.ack('risk',8,'failed');await rendering.flush();assert.equal(rendering.snapshot().phase,'failed');assert.equal(rendering.elements.get('refresh-progress-function').textContent,'');assert.equal(rendering.elements.get('refresh-progress-source').textContent,'');assert.equal(rendering.elements.get('refresh-progress-count').textContent,'');cases++;
  process.stdout.write(JSON.stringify({cases_passed:cases,asset:'full replacement s12_refresh.js',scope:'Deterministic full-asset mocked browser, not a production session'},null,2)+'\n');
})().catch(error=>{console.error(error);process.exitCode=1;});
