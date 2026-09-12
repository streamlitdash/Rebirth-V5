// Run against app.py with the bundled demo connectors and Playwright installed.
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const fs = require('node:fs');
const assert=require('node:assert/strict');
const path = require('node:path');
const root = process.env.BROWSER_ARTIFACT_DIR || require('node:os').tmpdir();
const result = {console: [], errors: [], callbacks: [], snapshots: []};
(async () => {
 const browser = await chromium.launch({headless: true, ...(process.env.CHROME_PATH ? {executablePath:process.env.CHROME_PATH} : {})});
 const page = await browser.newPage({viewport:{width:1440,height:1000}});
 page.on('pageerror', e => result.errors.push(String(e)));
 page.on('console', m => {if(m.type()==='error')result.console.push(m.text());});
 page.on('response', async r => {
   if (!r.url().includes('_dash-update-component')) return;
   const body = r.request().postDataJSON();
   if (/data-|quick-search|quick-market/.test(body?.output || '')) {
     let text = await r.text().catch(() => '');
     if(text.length>12000) text=text.slice(0,12000);
     result.callbacks.push({output:body.output,inputs:body.inputs,changed:body.changedPropIds,status:r.status(),body:text});
   }
 });
 async function snapshot(step) {
   result.snapshots.push(await page.evaluate(step => ({step,url:location.href,
     statuses:Object.fromEntries(['quick-search-data-status','quick-market-data-status','data-search-status','data-selection-status','data-history-status','data-identity-breadcrumb','data-player-date-pill'].map(id=>[id,document.getElementById(id)?.textContent])),
     graphs:[...document.querySelectorAll('#data-history-results .js-plotly-plot')].map(el=>({traces:el.data?.length,annotation:el.layout?.annotations?.[0]?.text})),
     quickRiskText:document.getElementById('quick-search-combine-udl')?.textContent,quickMarketText:document.getElementById('quick-market-combine-udl')?.textContent,dataPresent:!!document.getElementById('data-page')}),step));
 }
 try {
   await page.goto((process.env.BASE_URL || 'http://127.0.0.1:8192/'));
   await page.locator('#risk-grid table').waitFor({timeout:90000});
   await page.getByText('· Quick Risk',{exact:true}).first().click();
   await page.locator('#quick-search-combine-udl').click();
   await page.getByRole('searchbox').fill('IR Delta');
   await page.getByRole('option').first().waitFor();
   result.riskOptions=await page.getByRole('option').allTextContents();
   await page.getByRole('option').first().click();
   await page.waitForTimeout(1500);
   await snapshot('quick risk selected');
   if(await page.locator('#quick-search-open-data').isEnabled()) await page.locator('#quick-search-open-data').click({timeout:5000}); else result.riskButtonDisabled=true;
   await page.waitForTimeout(7000);
   await snapshot('quick risk open in data');
   await page.locator('#cube-nav-link').click();
   await page.getByText('· Quick Market',{exact:true}).first().click();
   await page.locator('#quick-market-combine-udl').click();
   await page.getByRole('searchbox').fill('IR Delta');
   await page.getByRole('option').first().waitFor();
   result.marketOptions=await page.getByRole('option').allTextContents();
   await page.getByRole('option').first().click();
   await page.waitForTimeout(1500);
   if(await page.locator('#quick-market-open-data').isEnabled()) await page.locator('#quick-market-open-data').click({timeout:5000}); else result.marketButtonDisabled=true;
   await page.waitForTimeout(7000);
   await snapshot('quick market open in data');
   await page.locator('#data-nav-link').click();
   await page.locator('#data-underlying').click();
   await page.getByRole('searchbox').fill('IR Delta');
   await page.getByRole('option').first().waitFor();
   result.dataOptions=await page.getByRole('option').allTextContents();
   await page.getByRole('option',{name:'Risk · IR | Delta | TEMP_REPLACE_ME - G10 Rates',exact:true}).click();
   await page.waitForTimeout(7000);
   await snapshot('direct data selection');
   await page.locator('#data-history-kind-tabs').getByText('Risk',{exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('#data-risk-chart .js-plotly-plot')?.data?.[0]?.type==='bar');
   assert.ok(await page.locator('#data-risk-chart .js-plotly-plot').evaluate(e=>Array.from(e.data[0].y).some(v=>Number.isFinite(v))));
   await snapshot('manual risk mode plots bars');
   await page.locator('#data-history-kind-tabs').getByText('Both',{exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('#data-history-status')?.textContent.includes('Risk: Loaded')&&document.querySelector('#data-history-status')?.textContent.includes('Market: Loaded'));
   await page.locator('#data-player-button').click();
   await page.waitForFunction(()=>document.querySelector('#data-player-button')?.textContent==='Pause');
   await page.waitForTimeout(1200);
   await page.locator('#data-player-button').click();
   await page.waitForFunction(()=>document.querySelector('#data-player-button')?.textContent==='Play');
   await snapshot('both modes and play pause');
   await page.locator('#cube-nav-link').click();
   await page.locator('#data-nav-link').click();
   await page.waitForFunction(()=>document.querySelector('#data-history-status')?.textContent.includes('Risk: Loaded')&&document.querySelector('#data-history-status')?.textContent.includes('Market: Loaded'));
   assert.ok(await page.locator('#data-history-kind-tabs input').nth(2).isChecked());
   await snapshot('return to data restores both');
   await page.locator('#data-underlying').click();await page.getByRole('searchbox').fill('market IR Vega');
   await page.getByRole('option').filter({hasText:'Market · IR |'}).first().click();
   await page.locator('#data-history-kind-tabs').getByText('Market',{exact:true}).click();
   await page.waitForTimeout(7000);await snapshot('surface selection');
   assert.equal(await page.locator('#data-market-chart .js-plotly-plot').evaluate(e=>e.data?.[0]?.type),'heatmap');
   assert.deepEqual(result.errors,[]);assert.deepEqual(result.console,[]);

 } catch(e) {result.failure=String(e);process.exitCode=1;await snapshot('failure');}
 finally {
   await page.screenshot({path:path.join(root,'data-navigation-repro.png'),fullPage:true});
   fs.writeFileSync(path.join(root,'data-navigation-repro.json'),JSON.stringify(result,null,2));
   console.log(JSON.stringify({snapshots:result.snapshots,errors:result.errors,console:[...new Set(result.console.map(x=>x.split('The string ids')[0]))],failure:result.failure},null,2));
   await browser.close();
 }
})();
