import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1600,height:3000} });
const page = await ctx.newPage();
const fetched = {};
page.on('response', r => { if (r.status()===200){ const u=r.url(); if(u.includes('kelly_mode_s06_state')) fetched['s06state']=true; if(u.includes('signal_kelly_trades')) fetched['trades']=true; } });
const errs=[];
page.on('pageerror', e => errs.push(String(e)));
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(16000);
console.log('s06state fetched:', !!fetched['s06state'], '| trades fetched:', !!fetched['trades']);
// 警示 span
const warn = await page.evaluate(() => {
  const el = document.getElementById('lab-kelly-s06-state');
  if (!el) return '(no element)';
  return { text: el.innerText, visible: el.style.display !== 'none' };
});
console.log('s06-state span:', JSON.stringify(warn));
// 全页面包含 "S06 判定没能读到" 字样?
const allTxt = await page.evaluate(() => document.body.innerText);
console.log('页面含3972:', allTxt.includes('3972'));
console.log('页面含"S06 判定没能读到":', allTxt.includes('S06 判定没能读到'));
console.log('页面含"超出 S06 快照覆盖期":', allTxt.includes('超出 S06 快照覆盖期'));
// 截取警示相关上下文
const idx = allTxt.indexOf('S06 判定没能读到');
if (idx>=0) console.log('上下文:', allTxt.slice(idx-80, idx+180).replace(/\n/g,' | '));
const idx2 = allTxt.indexOf('超出 S06 快照覆盖期');
if (idx2>=0) console.log('超期上下文:', allTxt.slice(idx2-80, idx2+160).replace(/\n/g,' | '));
// 快照状态(从 window)
const st = await page.evaluate(() => (typeof window._tdsS06Status === 'function') ? window._tdsS06Status() : null);
console.log('_tdsS06Status:', JSON.stringify(st));
console.log('JS errors:', errs.length ? errs.slice(0,5) : '(无)');
await b.close();
