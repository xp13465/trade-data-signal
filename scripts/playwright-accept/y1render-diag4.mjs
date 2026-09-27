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
page.on('pageerror', (e) => console.log('[pageerror@' + (Date.now()-T0) + 'ms]', String(e).slice(0, 500)));
page.on('console', (m) => { const t = m.text() || ''; if (/y1render|sigkelly|error|Error/i.test(t)) console.log('[console@' + (Date.now()-T0) + 'ms]', m.type(), t.slice(0, 220)); });
await page.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
// 检查新函数是否存在(新min加载验证)
const hasFn = await page.evaluate(() => ({ r1: typeof window._labKellyRenderY1Now, parts: typeof window._labKellyY1Ready }));
console.log('window._labKellyRenderY1Now 类型:', hasFn.r1, '| _labKellyY1Ready:', hasFn.parts);
// 注入 hook 追踪 _labKellyRenderY1Now 执行
await page.evaluate(() => {
  try {
    const orig = window._labKellyRenderY1Now;
    window._labKellyRenderY1Now = async function () {
      console.log('[_y1render hook] 调用开始 t=' + Date.now() + ' y1=' + window._labKellyY1Ready + ' all=' + window._labKellyAllReady);
      const r = await orig.apply(this, arguments);
      console.log('[_y1render hook] 调用结束 r=' + r + ' y1=' + window._labKellyY1Ready + ' all=' + window._labKellyAllReady);
      return r;
    };
  } catch (e) { console.log('[hook注入失败]', String(e)); }
});
const MAX = 90000;
while (Date.now() - T0 < MAX) {
  const st = await page.evaluate(() => {
    const fs = window.state && window.state.labSigKellyFeeStats;
    return { y1r: !!window._labKellyY1Ready, allr: !!window._labKellyAllReady, done: window._labKellyLoadedYears ? window._labKellyLoadedYears.length : 0, parts: fs ? fs.__partsState : 'no-fs', busy: !!window._kellyRecomputeBusy, rows: document.querySelectorAll('.lab-sigkelly-card .lab-sigkelly-table tbody tr').length, yearlyRows: document.querySelectorAll('.lab-sigkelly-yearly-table tbody tr').length };
  });
  if (st.y1r && !st.allr && st.done === 2) {
    // 阶段1完成后观察 3 秒, 期间打印 fs 状态
    for (let i = 0; i < 6; i++) {
      await new Promise((r) => setTimeout(r, 600));
      const s2 = await page.evaluate(() => {
        const fs = window.state && window.state.labSigKellyFeeStats;
        return { parts: fs ? fs.__partsState : 'no-fs', all: fs && fs.all ? 'obj' : (fs ? 'null' : 'no-fs'), yearly: fs && fs.allYearlyByMode ? Object.keys(fs.allYearlyByMode).join(',') : 'none', busy: !!window._kellyRecomputeBusy };
      });
      console.log('  [观察] parts=' + s2.parts + ' fs.all=' + s2.all + ' yearlyKeys=' + s2.yearly + ' busy=' + s2.busy);
    }
    break;
  }
  await new Promise((r) => setTimeout(r, 400));
}
await browser.close();
