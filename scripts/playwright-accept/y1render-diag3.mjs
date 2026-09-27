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
const logs = [];
page.on('console', (m) => { const t = m.text() || ''; if (/sigkelly|s06|S06|error|Error|降级/i.test(t)) logs.push({ t: Date.now() - T0, type: m.type(), text: t.slice(0, 180) }); });
page.on('pageerror', (e) => logs.push({ t: Date.now() - T0, type: 'pageerror', text: String(e).slice(0, 500) }));
await page.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
let lastKey = '';
const MAX = 100000;
while (Date.now() - T0 < MAX) {
  const st = await page.evaluate(() => {
    const fs = window.state && window.state.labSigKellyFeeStats;
    const sel = (s) => document.querySelectorAll(s).length;
    return {
      y1r: !!window._labKellyY1Ready, allr: !!window._labKellyAllReady,
      done: window._labKellyLoadedYears ? window._labKellyLoadedYears.length : 0,
      parts: fs ? fs.__partsState : null,
      fsAll: fs ? Object.keys(fs).slice(0, 8).join(',') : 'no-fs',
      yearlyVals: fs && fs.allYearlyByMode ? Object.keys(fs.allYearlyByMode).join(',') : 'none',
      year2rows: fs && fs.allYearlyByMode ? Object.keys(fs.allYearlyByMode).map(k=>k+':'+Object.keys(fs.allYearlyByMode[k]).sort().join('/')).join(' ') : 'none',
      yearlyRows: sel('.lab-sigkelly-yearly-table tbody tr'),
      rows: sel('.lab-sigkelly-card .lab-sigkelly-table tbody tr'),
      loading: sel('.lab-sigkelly-all-loading'),
      busy: !!window._kellyRecomputeBusy,
      s6: (typeof window._tdsS06Status === 'function') ? window._tdsS06Status() : null,
    };
  });
  const now = Date.now() - T0;
  const key = st.y1r + '/' + st.allr + '/' + st.parts + '/' + st.year2rows + '/' + st.yearlyRows + '/' + st.busy;
  if (key !== lastKey) {
    lastKey = key;
    console.log(`[t=${now}ms] y1r=${st.y1r} allr=${st.allr} done=${st.done} parts=${st.parts} fs=[${st.fsAll}] yearlyVals=${st.yearlyVals} year2rows=${st.year2rows} yearlyRows=${st.yearlyRows} rows=${st.rows} loading=${st.loading} busy=${st.busy} s6loaded=${st.s6 ? st.s6.loaded : '?'}`);
  }
  if (st.allr) { console.log('== 全量就绪, 收尾 =='); break; }
  await new Promise((r) => setTimeout(r, 500));
}
console.log('--- 日志(前25) ---');
logs.slice(0, 25).forEach(l => console.log('  t=' + l.t + 'ms [' + l.type + '] ' + l.text.slice(0, 200)));
await browser.close();
