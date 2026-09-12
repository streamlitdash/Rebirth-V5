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
const started=play(player,1,0,1,{},initial[20]);
assert.equal(started[20].playing,true);
const tick=play(player,1,1,1,{},started[20]);
assert.equal(tick[16],'2026-09-10');
assert.equal(tick[0].data[0].y[1],null);
const hidden=play(player,1,2,0,{hidden:true},tick[20]);
assert.equal(hidden[20].playing,false);
console.log('Data: 50-option cap, local search, unchanged tick, archive arrival, 250,000-cell heatmap, nulls, palette, receipts and playback passed.');
