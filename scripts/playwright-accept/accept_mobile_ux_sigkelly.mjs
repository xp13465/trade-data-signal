#!/usr/bin/env node
// BASE_URL=... [SOURCE_ROOT=/checkout DATA_ROOT=/actual/static-site/data]
// EVIDENCE_FILE=/tmp/mobile.json node scripts/playwright-accept/accept_mobile_ux_sigkelly.mjs
import { createRequire } from 'node:module';
import { installSources, dismissIntro, saveEvidence } from './mobile_source_harness.mjs';
const {chromium} = createRequire(import.meta.url)('playwright');
const base = process.env.BASE_URL || 'https://ss.fx8.store';
const results=[]; let failures=0;
const browser=await chromium.launch({headless:true});
const matrix=[[320,568],[375,667],[390,844],[430,932],[760,800],[761,800],[1280,900],[760,360],[760,320],[320,568,1.5]];
try {
 for (const [width,height,fontScale=1] of matrix) {
  const context=await browser.newContext({viewport:{width,height},isMobile:width<=760,hasTouch:width<=760,serviceWorkers:'block'});
  const page=await context.newPage(); const errors=[];page.on('pageerror',e=>errors.push(String(e)));
  const row={width,height,fontScale,checks:[],errors};results.push(row);
  function check(name,pass,detail){row.checks.push({name,pass,detail});if(!pass)failures++;}
  try {
   await installSources(page);
   await page.goto(base+'/#lab?sub=sigkelly',{waitUntil:'domcontentloaded',timeout:60000});
   const toggle=page.locator('#lab-kelly-params-toggle');
   await toggle.waitFor({state:'visible',timeout:60000}); await dismissIntro(page);
   await page.locator('.lab-sigkelly-grid').first().waitFor({state:'visible',timeout:30000});
   const panel=page.locator('.lab-sigkelly-params-body');
   const initialOpen=await panel.isVisible();
   check('default state matches 760px boundary',initialOpen===(width>760),initialOpen);
   check('expanded aria matches actual visibility',(await toggle.getAttribute('aria-expanded'))===String(initialOpen));
   // Synthetic font enlargement; genuine iOS/Android system-font checks remain manual.
   if(fontScale!==1) await page.evaluate(scale=>{
    const elements=[...document.querySelectorAll('.lab-sigkelly-bar *')];
    const sizes=elements.map(el=>parseFloat(getComputedStyle(el).fontSize));
    elements.forEach((el,i)=>el.style.fontSize=(sizes[i]*scale)+'px');
   },fontScale);
   if(!initialOpen)await toggle.click();
   await panel.waitFor({state:'visible'});
   await page.waitForFunction(()=>{const b=document.querySelector('#lab-kelly-params-toggle');return b.getAttribute('aria-expanded')==='true';});
   await toggle.scrollIntoViewIfNeeded();
   await page.evaluate(()=>window.scrollBy(0,400));
   const metrics=await page.evaluate(()=>{
    const rect=s=>{const e=document.querySelector(s),r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,width:r.width,scrollHeight:e.scrollHeight,clientHeight:e.clientHeight};};
    return {panel:rect('.lab-sigkelly-params-body'),button:rect('#lab-kelly-params-toggle'),bar:rect('.lab-sigkelly-bar'),bottom:rect('.h5-bottomnav'),viewport:innerHeight,position:getComputedStyle(document.querySelector('.lab-sigkelly-bar')).position,overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth};
   });row.metrics=metrics;
   check('no page overflow',metrics.overflow<=1,metrics.overflow);
   check('panel really opened',metrics.panel.height>0,metrics.panel.height);
   if(width<=760){
    check('compact button retained',metrics.button.height>0&&metrics.button.height<=28*fontScale,metrics.button.height);
    check('panel bounded',metrics.panel.height<=height*.55+1,metrics.panel.height);
    check('sticky strip leaves result space',metrics.position!=='sticky'||metrics.bar.bottom<=metrics.bottom.top-40,metrics.bar.bottom);
    if(metrics.panel.scrollHeight>metrics.panel.clientHeight){
     await panel.hover();await page.mouse.wheel(0,1000);
     await page.waitForFunction(()=>document.querySelector('.lab-sigkelly-params-body').scrollTop>0);
     check('internal scroll responds to wheel',true);
    }
    await toggle.focus();await page.keyboard.press('Escape');
    check('Escape closes and restores focus',!(await panel.isVisible())&&await toggle.evaluate(e=>document.activeElement===e));
    await page.keyboard.press('Enter');await panel.waitFor({state:'visible'});
    check('keyboard reopens actual controls',await panel.isVisible());
    await toggle.click();check('close button works',!(await panel.isVisible()));
    const notification=page.locator('.h5-notify-btn');
    await notification.scrollIntoViewIfNeeded();await notification.click({trial:true});
    check('notification remains reachable',await notification.isVisible());
   }
   for(const selector of ['.auto-trade-steps','.lab-top-disclaimer','.lab-sigkelly-advice']) {
    check('essential content present: '+selector,await page.locator(selector).first().isVisible());
   }
   const details=page.locator('.auto-trade-steps details').first();
   if(width<=760){
    check('plan has an expansion control',await details.count()===1);
    if(await details.count()) {const summary=details.locator('summary').first();await summary.click();check('plan expands',await details.evaluate(e=>e.open));}
   }
   check('no script errors',errors.length===0,errors);
   if(process.env.SCREENSHOT_DIR){const fs=await import('node:fs/promises');await fs.mkdir(process.env.SCREENSHOT_DIR,{recursive:true});await page.screenshot({path:`${process.env.SCREENSHOT_DIR}/${width}x${height}-${fontScale}.png`});}
  }catch(error){check('scenario completed',false,String(error));}
  finally{await context.close();}
  console.log(JSON.stringify(row));
 }
}finally{await browser.close();await saveEvidence(process.env.EVIDENCE_FILE,{results,failures});}
console.log(`mobile matrix: ${results.reduce((n,r)=>n+r.checks.filter(c=>c.pass).length,0)} passed / ${failures} failed`);
process.exitCode=failures?1:0;
