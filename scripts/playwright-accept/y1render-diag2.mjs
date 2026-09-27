// 诊断v2: 轮询捕捉 parts='Y1' 中间态(即 _labKellyRenderY1Now 真正写 state.labSigKellyFeeStats 并刷新 DOM 的时刻)
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
let y1Seen = 0, y1RenderSnap = null;
const MAX = 100000;
while (Date.now() - T0 < MAX) {
  const st = await page.evaluate(() => {
    const fs = window.state && window.state.labSigKellyFeeStats;
    const sel = (s) => document.querySelectorAll(s).length;
    const allCard = document.querySelector('.lab-sigkelly-all-group .lab-sigkelly-card');
    const firstTR = document.querySelector('.lab-sigkelly-all-group .lab-sigkelly-table tbody tr');
    return {
      y1r: !!window._labKellyY1Ready, allr: !!window._labKellyAllReady,
      done: window._labKellyLoadedYears ? window._labKellyLoadedYears.length : 0,
      parts: fs ? fs.__partsState : null,
      yearlyKeys: fs && fs.allYearlyByMode ? Object.keys(fs.allYearlyByMode).join(',') : 'none',
      yearlyRows: sel('.lab-sigkelly-yearly-table tbody tr'),
      loading: sel('.lab-sigkelly-all-loading'),
      rows: sel('.lab-sigkelly-card .lab-sigkelly-table tbody tr'),
      busy: !!window._kellyRecomputeBusy,
      allCardHead: allCard ? allCard.textContent.replace(/\s+/g, ' ').slice(0, 150) : null,
      firstRow: firstTR ? Array.from(firstTR.querySelectorAll('td')).map(td => td.textContent.trim()).join(' | ').slice(0, 220) : null,
    };
  });
  const now = Date.now() - T0;
  // 捕捉 Y1 中间态(第一次 parts=Y1 且 !allr)
  if (st.parts === 'Y1' && !st.allr && !y1RenderSnap) {
    y1RenderSnap = st; y1Seen = now;
    console.log(`[Y1中间态@${now}ms] done=${st.done} yearlyKeys=${st.yearlyKeys} yearlyRows=${st.yearlyRows} loading=${st.loading} rows=${st.rows} busy=${st.busy}`);
    if (st.firstRow) console.log('   all卡首行:', st.firstRow);
  }
  if (st.allr) {
    console.log(`[all就绪@${now}ms] rows=${st.rows} yearlyRows=${st.yearlyRows} yearlyKeys=${st.yearlyKeys}`);
    if (y1RenderSnap && st.firstRow) {
      console.log('   all卡首行(全量):', st.firstRow);
    }
    break;
  }
  await new Promise((r) => setTimeout(r, 200));
}
if (!y1RenderSnap) console.log('!! 未捕捉到 parts=Y1 中间态');
await browser.close();
