// 诊断: y1渲染中间态时 state.labSigKellyFeeStats 的真实结构
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
  else setTimeout(() => route.continue(), 25000);
});
const page = await ctx.newPage();
const T0 = Date.now();
page.on('pageerror', (e) => console.log('[pageerror]', String(e).slice(0, 400)));
await page.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
let printed = false;
const MAX = 90000;
while (Date.now() - T0 < MAX) {
  const st = await page.evaluate(() => {
    const fs = window.state && window.state.labSigKellyFeeStats;
    const sel = (s) => document.querySelectorAll(s).length;
    return {
      y1r: !!window._labKellyY1Ready, allr: !!window._labKellyAllReady,
      done: window._labKellyLoadedYears ? window._labKellyLoadedYears.length : 0,
      parts: fs ? fs.__partsState : null,
      fsAllType: fs ? (fs.all ? (typeof fs.all === 'object' ? 'obj:' + Object.keys(fs.all).join(',') : typeof fs.all) : 'null') : 'no-fs',
      yearlyKeys: fs && fs.allYearlyByMode ? Object.keys(fs.allYearlyByMode).join(',') : 'none',
      yearlyRows: sel('.lab-sigkelly-yearly-table tbody tr'),
      loading: sel('.lab-sigkelly-all-loading'),
      rows: sel('.lab-sigkelly-card .lab-sigkelly-table tbody tr'),
      recomputeBusy: !!window._kellyRecomputeBusy,
    };
  });
  if (st.y1r && !st.allr && !printed) {
    printed = true;
    console.log(`[y1就绪@${Date.now()-T0}ms] done=${st.done} parts=${st.parts} fsAll=${st.fsAllType} yearlyKeys=${st.yearlyKeys} yearlyRows=${st.yearlyRows} loading=${st.loading} rows=${st.rows} busy=${st.recomputeBusy}`);
  }
  if (st.allr) { console.log(`[all就绪@${Date.now()-T0}ms] rows=${st.rows} yearlyRows=${st.yearlyRows}`); break; }
  await new Promise((r) => setTimeout(r, 300));
}
await browser.close();
