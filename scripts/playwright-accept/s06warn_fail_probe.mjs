import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1600,height:3000} });
const page = await ctx.newPage();
// 拦截所有 kelly_mode_s06_state 请求 → 失败
let blocked = 0;
await page.route('**/*kelly_mode_s06_state*', r => { blocked++; return r.abort('failed'); });
const errs=[];
page.on('pageerror', e => errs.push(String(e)));
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(18000);
console.log('blocked s06 requests:', blocked);
const warn = await page.evaluate(() => {
  const el = document.getElementById('lab-kelly-s06-state');
  if (!el) return '(no element)';
  return { text: el.innerText, visible: el.style.display !== 'none' };
});
console.log('s06-state span(快照全失败场景):', JSON.stringify(warn));
const st = await page.evaluate(() => (typeof window._tdsS06Status === 'function') ? window._tdsS06Status() : null);
console.log('_tdsS06Status:', JSON.stringify(st));
console.log('JS errors:', errs.length ? errs.slice(0,5) : '(无)');
await b.close();
