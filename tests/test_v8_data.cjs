/* Run with node tests/test_v8_data.cjs; no dependencies besides Node. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const noUpdate = {};
const context = {window:{dash_clientside:{no_update:noUpdate}}, document:{hidden:false}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname,'../assets/s09_playback.js'),'utf8'),context);
const {search, searchCurrent, play} = context.window.dash_clientside.cubeData;
const choices = {risk:Array.from({length:20000},(_,i)=>`IR | Delta | Name${i}`),market:[]};
const selected = {label:'Chosen archived name',value:'chosen'};
assert.equal(search(choices,{},'Name',selected,'chosen')[0].length,50);
assert.equal(search(choices,{},'Name',selected,'chosen')[0][0].value,'chosen');
const first = searchCurrent('Name19999',null,1,choices,null,null);
assert.equal(first[0].length,1);
const unchanged = searchCurrent('Name19999',null,2,choices,null,null);
assert.equal(unchanged[0],noUpdate);
const ready = searchCurrent('ArchiveOnly',null,3,choices,{choices:[['ArchiveOnly','archive-key']]},null);
assert.equal(ready[0][0].value,'archive-key');

// Large allowed bundles must not spread 250,000 cells into function arguments.
const swaps=Array.from({length:500},(_,i)=>String(i));
const options=Array.from({length:500},(_,i)=>String(i));
const values=[];
for(const swap of swaps)for(const option of options)values.push({'Risk Date':'2026-09-11','Tenor Swap':swap,'Tenor Option':option,Risk: swap==='0' && option==='0' ? -1234 : 2});
const bundle={key:'large',kind:'risk',date_column:'Risk Date',dates:['2026-09-11'],metric_column:'Risk',
 axes:[{column:'Tenor Swap',labels:swaps},{column:'Tenor Option',labels:options}],values,
 handoff:{identity:{underlying:'Test'}}};
const payload={key:'render-a',mode:'risk',bundles:{risk:bundle},refresh:{owner:'data-history',revision:4,request_id:'request-a',status:'rendered'}};
const result=play(payload,0,0,0,{},null);
assert.equal(result.length,23);
assert.equal(result[0].data[0].type,'heatmap');
assert.equal(result[0].data[0].zmin,-1234);
assert.equal(result[0].data[0].zmax,1234);
assert.equal(result[0].layout.yaxis.autorange,'reversed');
assert.equal(result[0].data[0].colorscale[2][1],'#4C8A4A');
assert.equal(result[21],'render-a');
assert.equal(result[22].request_id,'request-a');
assert.equal(result[22].mounts[0],'render-a');
assert.equal(result[6][0].if.filter_query,'{Risk} < 0');

const curve={...bundle,key:'curve',axes:[{column:'Tenor Swap',labels:['1Y','5Y']}],values:[
 {'Risk Date':'2026-09-10','Tenor Swap':'1Y',Risk:-7},
 {'Risk Date':'2026-09-10','Tenor Swap':'5Y',Risk:null},
 {'Risk Date':'2026-09-11','Tenor Swap':'1Y',Risk:9}],dates:['2026-09-10','2026-09-11']};
const player={key:'play',mode:'risk',bundles:{risk:curve}};
const initial=play(player,0,0,0,{},null);
assert.equal(initial[0].data[0].type,'bar');
assert.equal(initial[0].layout.yaxis.rangemode,'tozero');
assert.equal(initial[0].layout.yaxis2,undefined);
assert.deepEqual(Array.from(initial[0].data[0].x),['1Y','5Y']);
assert.deepEqual(Array.from(initial[0].data[0].y),[9,null]);
const started=play(player,1,0,1,{},initial[20]);
assert.equal(started[20].playing,true);
const tick=play(player,1,1,1,{},started[20]);
assert.equal(tick[16],'2026-09-10');
assert.equal(tick[0].data[0].y[0],-7);
assert.equal(tick[0].data[0].y[1],null);
const hidden=play(player,1,2,0,{hidden:true},tick[20]);
assert.equal(hidden[20].playing,false);

// The change is limited to Risk by tenor; Market curves and spot histories remain lines.
const market={...curve,key:'market',kind:'market',date_column:'Market Date',metric_column:'Current',values:[
 {'Market Date':'2026-09-11','Tenor Swap':'1Y',Current:3.75},
 {'Market Date':'2026-09-11','Tenor Swap':'5Y',Current:3.9}]};
const both=play({key:'both',mode:'both',bundles:{risk:curve,market}},0,0,0,{},null);
assert.equal(both[0].data[0].type,'bar');
assert.equal(both[1].data[0].type,'scatter');
assert.equal(both[1].data[0].mode,'lines+markers');
assert.deepEqual(Array.from(both[1].data[0].y),[3.75,3.9]);
for (const kind of ['risk','market']) {
 const dateColumn=kind==='risk'?'Risk Date':'Market Date';
 const metric=kind==='risk'?'Risk':'Current';
 const spot={...curve,key:`spot-${kind}`,kind,date_column:dateColumn,metric_column:metric,axes:[],values:[
  {[dateColumn]:'2026-09-10',[metric]:-7},
  {[dateColumn]:'2026-09-11',[metric]:9}]};
 const spotResult=play({key:`spot-${kind}`,mode:kind,bundles:{[kind]:spot}},0,0,0,{},null);
 const figure=spotResult[kind==='risk'?0:1];
 assert.equal(figure.data[0].type,'scatter');
 assert.equal(figure.data[0].mode,'lines+markers');
 assert.equal(figure.layout.xaxis.title.text,'Date');
 assert.deepEqual(Array.from(figure.data[0].x),['2026-09-10','2026-09-11']);
}
console.log('Data: local search, 250,000-cell heatmap, Risk tenor bars, Market curves, spot history lines, nulls, palette, receipts and playback passed.');
