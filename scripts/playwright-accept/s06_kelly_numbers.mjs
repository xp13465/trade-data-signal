import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:4000} });
const page = await ctx.newPage();
const errs=[];
page.on('pageerror', e => errs.push(String(e)));
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(25000);
// 读取全信号表区域文本
const txt = await page.evaluate(() => {
  const all = document.querySelector('.lab-sigkelly-all-group');
  const adv = document.querySelector('.lab-sigkelly-advice-note');
  let favMode = '';
  const sel = document.getElementById('lab-kelly-fade-mode-caliber');
  if (sel) favMode = sel.innerText;
  return { allTxt: all ? all.innerText.slice(0, 5000) : '(none)', advice: adv ? adv.innerText.slice(0,1500) : '', mode: favMode };
});
console.log('== 模式展示:', txt.mode);
console.log('== 全信号表区域(前3500字):');
console.log(txt.allTxt.slice(0,3500));
await page.screenshot({ path:'/Users/linhuichen/code/trade/scripts/playwright-accept/s06-kelly-current.png', fullPage:false });
console.log('JS errors:', errs.length ? errs.slice(0,5) : '(无)');
await b.close();
