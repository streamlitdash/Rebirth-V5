// Run against app.py with the bundled demo connectors and Playwright installed.
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
 const page=await browser.newPage({viewport:{width:1440,height:1000}});
 const result={errors:[],console:[],checks:[]};
 page.on('pageerror',e=>result.errors.push(String(e)));
 page.on('console',m=>{if(m.type()==='error')result.console.push(m.text().split('The string ids')[0]);});
 try{
   await page.goto((process.env.BASE_URL || 'http://127.0.0.1:8192/'));
   await page.locator('#risk-grid table').waitFor({timeout:90000});
   result.riskLabelStyle=await page.locator('#risk-grid .row-detail-button').first().evaluate(e=>({background:getComputedStyle(e).backgroundColor,border:getComputedStyle(e).borderWidth}));
   assert.equal(result.riskLabelStyle.border,'0px');
   await page.locator('#stock-nav-link').click();
   await page.locator('#stock-current-table tbody tr[data-stock-index]').first().waitFor({timeout:60000});
   const rows=page.locator('#stock-current-table tbody tr[data-stock-index]');
   const total=async()=>Number(await page.locator('#stock-current-table table').getAttribute('aria-rowcount'))-1;
   const first=page.locator('#stock-current-table .row-toggle').first();
   const initial=await total();
   await first.click();await page.waitForFunction(n=>Number(document.querySelector('#stock-current-table table')?.getAttribute('aria-rowcount'))-1<n,initial);
   await first.click();await page.waitForFunction(n=>Number(document.querySelector('#stock-current-table table')?.getAttribute('aria-rowcount'))-1===n,initial);
   result.checks.push('Sign-off collapse and reopen');
   const promoted=rows.filter({has:page.locator('.promotion-badge')}).first();
   const toggle=promoted.locator('.row-toggle');
   await toggle.click();await page.waitForFunction(n=>Number(document.querySelector('#stock-current-table table')?.getAttribute('aria-rowcount'))-1>n,initial);
   await toggle.click();await page.waitForFunction(n=>Number(document.querySelector('#stock-current-table table')?.getAttribute('aria-rowcount'))-1===n,initial);
   await promoted.locator('.row-label-text').click();
   await page.waitForFunction(()=>document.querySelector('#stock-history-status')?.textContent.includes('available dates'));
   assert.ok((await page.locator('#stock-history-chart .js-plotly-plot').evaluate(e=>e.data.length))>0);
   result.checks.push('Promoted chevrons and identifier history');
   await page.locator('#stock-current-table').evaluate(e=>{e.scrollTop=e.scrollHeight});await page.waitForTimeout(150);
   const other=rows.filter({has:page.getByRole('button',{name:'Other',exact:true})}).last().locator('.row-toggle');
   for(let i=0;i<3;i++){
     await other.click();await page.waitForFunction(n=>Number(document.querySelector('#stock-current-table table')?.getAttribute('aria-rowcount'))-1>n,initial);
     await other.click();await page.waitForFunction(n=>Number(document.querySelector('#stock-current-table table')?.getAttribute('aria-rowcount'))-1===n,initial);
   }
   result.checks.push('Other expands and collapses repeatedly after scrolling to bottom');
   for(let i=0;i<3;i++){
     await page.locator('#stock-raw-summary').click();
     await page.waitForFunction(open=>document.getElementById('stock-raw-panel').open===open,i%2===0);
     if(i%2===0)await page.waitForFunction(()=>document.querySelectorAll('#stock-raw-table td.dash-cell').length>0);
   }
   result.checks.push('Raw area opens, closes and reopens');
   const dateInput=page.locator('input#stock-input-date');await dateInput.fill('2026-08-04');await dateInput.press('Enter');await dateInput.press('Tab');await page.waitForFunction(()=>document.querySelector('#stock-load-status')?.textContent.includes('2026-08-04'));result.checks.push('Date picker loads connector for 2026-08-04');
   await page.locator('#stock-input-date').press('Escape');await page.locator('#stock-load-status').click();
   await page.waitForFunction(()=>document.querySelector('#stock-history-status')?.textContent.endsWith('2026-08-04'));
   const filters=page.locator('#stock-raw-table th[data-dash-column="CRDS"] input[type="text"]');
   await filters.fill('= "TEMP_REPLACE_ME - CRDS-000000"');await filters.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#stock-raw-status')?.textContent==='1 of 5,001 rows');
   await filters.fill('');await filters.press('Enter');
   await page.waitForFunction(()=>document.querySelector('#stock-raw-status')?.textContent==='5,001 of 5,001 rows');
   result.checks.push('Raw per-column filter searches the complete connector');
   const before=await page.locator('#refresh-commit-revision').textContent();
   await page.keyboard.press('Shift+F9');
   await page.waitForFunction(()=>window.__cubeV5Assets?.refreshDiagnostics()?.active===true);
   await page.locator('#stock-raw-summary').click();
   await page.waitForFunction(()=>!document.getElementById('stock-raw-panel').open);
   await page.waitForFunction(old=>Number(document.getElementById('refresh-commit-revision').textContent)>Number(old),before);
   await page.waitForFunction(()=>window.__cubeV5Assets?.refreshDiagnostics()?.phase==='complete',{},{timeout:60000});
   result.refresh=await page.evaluate(()=>window.__cubeV5Assets.refreshDiagnostics());
   assert.equal(result.refresh.pending_views.length,0);
   result.checks.push('One Shift+F9 refresh completes; raw panel remains clickable during work');
   await page.locator('#stock-current-table').evaluate(e=>{e.scrollTop=0});await page.waitForTimeout(150);
   assert.ok(await rows.count()<70);result.paintedRows=await rows.count();
   result.dateControl=await page.locator('#stock-input-date').evaluate(e=>e.outerHTML);
   result.inputs=await page.locator('#stock-page input').evaluateAll(es=>es.map(e=>({id:e.id,placeholder:e.placeholder,value:e.value})));
   result.totalRows=initial;
   assert.equal(await page.locator('#stock-current-table button.next-page').count(),0);
   assert.deepEqual(result.errors,[]);assert.deepEqual(result.console,[]);
   await page.screenshot({path:path.join(process.env.BROWSER_ARTIFACT_DIR || require('node:os').tmpdir(),'stock-interactions-repro.png'),fullPage:true});
 }catch(e){result.failure=String(e);process.exitCode=1;await page.screenshot({path:path.join(process.env.BROWSER_ARTIFACT_DIR || require('node:os').tmpdir(),'stock-interactions-repro.png'),fullPage:true}).catch(()=>{});}
 finally{fs.writeFileSync(path.join(process.env.BROWSER_ARTIFACT_DIR || require('node:os').tmpdir(),'stock-interactions-repro.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result,null,2));await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});

