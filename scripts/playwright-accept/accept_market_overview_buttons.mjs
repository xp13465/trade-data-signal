#!/usr/bin/env node
// Actual overview/market DOM. Same SOURCE_ROOT/DATA_ROOT interface as sigkelly.
import {createRequire} from 'node:module';
import {installSources,dismissIntro,saveEvidence} from './mobile_source_harness.mjs';
const {chromium}=createRequire(import.meta.url)('playwright');
const browser=await chromium.launch({headless:true}); const results=[];let failures=0;
try {for(const width of [320,375,390,430,760,761,1280]) {
 const context=await browser.newContext({viewport:{width,height:844},isMobile:width<=760,hasTouch:width<=760,serviceWorkers:'block'});
 const page=await context.newPage();const row={width,checks:[],errors:[]};results.push(row);page.on('pageerror',e=>row.errors.push(String(e)));
 const check=(name,pass,detail)=>{row.checks.push({name,pass,detail});if(!pass)failures++;};
 try {
  await installSources(page);await page.goto((process.env.BASE_URL||'https://ss.fx8.store')+'/#overview',{waitUntil:'domcontentloaded',timeout:60000});
  await page.locator('.summary-ai-btn').waitFor({state:'visible',timeout:60000});await dismissIntro(page);
  for(const selector of ['.summary-ai-btn','.summary-history-btn']){
   const el=page.locator(selector);await el.scrollIntoViewIfNeeded();await el.click({trial:true});const box=await el.boundingBox();
   check('visible compact '+selector,box.height>0&&box.height<=32,box);}
  check('overview has no page overflow',await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth<=1));
  if(width<=760){
   await page.locator('nav.h5-bottomnav button[data-tab="market"]').click();
   await page.locator('.h5-periods button').first().waitFor({state:'visible'});
   const buttons=page.locator('.h5-periods button');const heights=await buttons.evaluateAll(els=>els.map(e=>e.getBoundingClientRect().height));
   check('all market period buttons compact and visible',heights.length>0&&heights.every(h=>h>0&&h<=32),heights);
   await buttons.first().click();check('market period control clickable',true);
   check('market has no page overflow',await page.evaluate(()=>document.documentElement.scrollWidth-document.documentElement.clientWidth<=1));
  }else{check('desktop mobile toolbar stays hidden',!(await page.locator('.h5-period-bar').isVisible()));}
  check('no script errors',row.errors.length===0,row.errors);
 }catch(e){check('scenario completed',false,String(e));}finally{await context.close();}
 console.log(JSON.stringify(row));
}}finally{await browser.close();await saveEvidence(process.env.EVIDENCE_FILE,{results,failures});}
console.log(`overview matrix: ${results.reduce((n,r)=>n+r.checks.filter(c=>c.pass).length,0)} passed / ${failures} failed`);process.exitCode=failures?1:0;
