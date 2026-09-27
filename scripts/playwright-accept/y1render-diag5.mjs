import { chromium } from 'playwright';
const BASE = 'http://127.0.0.1:18871';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1500, height: 3000 } });
await ctx.route(/^(?!.*127\.0\.0\.1|.*ss\.fx8\.store|.*sugas\.site|.*r2\.)/, (r) => r.abort());
await ctx.route(/signal_kelly_trades_parts/, (route) => {
  const url = route.request().url();
  const m = /t(\d{4})\.json/.exec(url);
  const year = m ? m[1] : '';
  if (year === '2026' || year === '2025') route.continue();
  else setTimeout(() => route.continue(), 30000);
});
const page = await ctx.newPage();
const T0 = Date.now();
page.on('pageerror', (e) => console.log('[pageerror@' + (Date.now()-T0) + 'ms]', String(e).slice(0, 400)));
page.on('console', (m) => { const t = m.text() || ''; if (/RenderY1Now|sigkelly.*(error|load)|Cannot read|undefined is/i.test(t)) console.log('[console@' + (Date.now()-T0) + 'ms]', m.type(), t.slice(0, 220)); });
await page.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
// 等 lab 注入完成后检查
await page.waitForTimeout(1500);
console.log('lab 注入后:', await page.evaluate(() => ({ r1: typeof window._labKellyRenderY1Now, sst: typeof window.state, s06: typeof window._tdsS06StateEnsure })));
// state 的实际暴露
console.log('state 键:', await page.evaluate(() => window.state ? Object.keys(window.state).slice(0, 20).join(',') : 'no state'));
// 手动调用新函数测试(无痕链路已在加载中)
console.log('手动调用 _labKellyRenderY1Now =>', await page.evaluate(() => window._labKellyRenderY1Now ? window._labKellyRenderY1Now().then(()=>'resolved').catch(e=>'reject:'+String(e)) : 'no fn'));
await page.waitForTimeout(2000);
const st = await page.evaluate(() => {
  const fs = window.state && window.state.labSigKellyFeeStats;
  return { parts: fs ? (fs.__partsState || 'no-flag') : 'NO-FS', y1r: !!window._labKellyY1Ready, allr: !!window._labKellyAllReady, done: window._labKellyLoadedYears ? window._labKellyLoadedYears.length : 0 };
});
console.log('手动调用后:', JSON.stringify(st));
await browser.close();
