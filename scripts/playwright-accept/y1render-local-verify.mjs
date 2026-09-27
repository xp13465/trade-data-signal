// #100 y1先渲染修复 本地实测 v2 —— 捕捉「y1渲染完成」中间态(非就绪帧), 对账与全量数字一致
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
  else setTimeout(() => route.continue(), 20000);
});
const page = await ctx.newPage();
const T0 = Date.now();
const logs = [];
page.on('console', (m) => { const t = m.text() || ''; if (/sigkelly|error|Error/i.test(t)) logs.push({ t: Date.now() - T0, type: m.type(), text: t.slice(0, 220) }); });
page.on('pageerror', (e) => logs.push({ t: Date.now() - T0, type: 'pageerror', text: String(e).slice(0, 400) }));

console.log('goto...');
await page.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });

// 阶段1前基线(静态 backtest 数据)
await page.waitForTimeout(3000);
const baseSnap = await page.evaluate(() => {
  const selRows = (sel) => document.querySelectorAll(sel).length;
  const allCard = document.querySelector('.lab-sigkelly-all-group .lab-sigkelly-card');
  return {
    cards: selRows('.lab-sigkelly-card'), rows: selRows('.lab-sigkelly-card .lab-sigkelly-table tbody tr'),
    yearlyRows: selRows('.lab-sigkelly-yearly-table tbody tr'), loading: selRows('.lab-sigkelly-all-loading'),
    allCardHead: allCard ? allCard.textContent.replace(/\s+/g, ' ').slice(0, 200) : null,
    y1r: !!window._labKellyY1Ready, allr: !!window._labKellyAllReady,
  };
});
console.log(`[基线@${Date.now()-T0}ms] y1r=${baseSnap.y1r} allr=${baseSnap.allr} cards=${baseSnap.cards} rows=${baseSnap.rows} yearlyRows=${baseSnap.yearlyRows} loading=${baseSnap.loading}`);

// 等待 y1 渲染完成(阶段1就绪后, y1渲染异步执行): 用 yearlyRows>0(阶段1应有2025/2026两行)作为「y1渲染完成」信号
// 兜底: 等到 rows 从基线变化 / all 就绪前 的最早时刻
let y1RenderSnap = null, y1RenderAt = 0, allSnap = null, allAt = 0;
let lastRows = baseSnap.rows, lastYearly = baseSnap.yearlyRows;
const MAX = 120000;
while (Date.now() - T0 < MAX) {
  const st = await page.evaluate(() => {
    const selRows = (sel) => document.querySelectorAll(sel).length;
    const firstTR = document.querySelector('.lab-sigkelly-all-group .lab-sigkelly-table tbody tr');
    const allCard = document.querySelector('.lab-sigkelly-all-group .lab-sigkelly-card');
    return {
      y1r: !!window._labKellyY1Ready, allr: !!window._labKellyAllReady,
      done: window._labKellyLoadedYears ? window._labKellyLoadedYears.length : 0,
      cards: selRows('.lab-sigkelly-card'), rows: selRows('.lab-sigkelly-card .lab-sigkelly-table tbody tr'),
      yearlyRows: selRows('.lab-sigkelly-yearly-table tbody tr'), loading: selRows('.lab-sigkelly-all-loading'),
      allCardHead: allCard ? allCard.textContent.replace(/\s+/g, ' ').slice(0, 200) : null,
      firstRow: firstTR ? Array.from(firstTR.querySelectorAll('td')).map(td => td.textContent.trim()).join(' | ').slice(0, 200) : null,
      allCardNull: allCard ? (allCard.textContent.indexOf('null') >= 0) : false,
    };
  });
  const now = Date.now() - T0;
  // 捕捉 y1 渲染完成: y1r=true 且 (yearlyRows>0 或 rows 比基线增加) 且 allr=false 且 loading 降下来
  if (st.y1r && !st.allr && !y1RenderSnap && (st.yearlyRows > 0 || st.rows > lastRows || (st.rows !== baseSnap.rows))) {
    y1RenderAt = now; y1RenderSnap = st;
    console.log(`[y1渲染完成@${now}ms] y1r=${st.y1r} allr=${st.allr} done=${st.done} cards=${st.cards} rows=${st.rows} yearlyRows=${st.yearlyRows} loading=${st.loading} allCardNull=${st.allCardNull}`);
    if (st.firstRow) console.log('   all卡首行:', st.firstRow);
    if (st.allCardHead) console.log('   all卡头:', st.allCardHead.slice(0, 150));
  }
  if (st.y1r && !st.allr && (st.yearlyRows > 0 || st.rows > lastRows)) lastYearly = st.yearlyRows;
  if (st.rows > lastRows) lastRows = st.rows;
  if (st.allr) { allAt = now; allSnap = st; break; }
  await new Promise((r) => setTimeout(r, 300));
}
if (!allSnap) { await page.waitForTimeout(1000); allSnap = await page.evaluate(() => {
  const firstTR = document.querySelector('.lab-sigkelly-all-group .lab-sigkelly-table tbody tr');
  return { allr: !!window._labKellyAllReady, rows: document.querySelectorAll('.lab-sigkelly-card .lab-sigkelly-table tbody tr').length, yearlyRows: document.querySelectorAll('.lab-sigkelly-yearly-table tbody tr').length, firstRow: firstTR ? Array.from(firstTR.querySelectorAll('td')).map(td => td.textContent.trim()).join(' | ').slice(0, 200) : null };
}); }
console.log(`[全量就绪@${allAt || '?'}ms] allr=${allSnap.allr} rows=${allSnap.rows} yearlyRows=${allSnap.yearlyRows}`);
if (allSnap.firstRow) console.log('   all卡首行:', allSnap.firstRow);

// 对账: 阶段1 y1 渲染后的 all 卡首行数字 vs 全量后 首行数字(默认周期 y1, 应逐位一致)
console.log('--- 对账 ---');
console.log('基线 rows=' + baseSnap.rows + ' → y1渲染 rows=' + (y1RenderSnap ? y1RenderSnap.rows : '无') + ' → 全量 rows=' + allSnap.rows);
if (y1RenderSnap && y1RenderSnap.firstRow && allSnap.firstRow) {
  const a = y1RenderSnap.firstRow, b = allSnap.firstRow;
  console.log('y1渲染 首行:', a);
  console.log('全量   首行:', b);
  console.log('逐位一致: ' + (a === b));
}
console.log('--- console 日志 ---');
logs.slice(0, 30).forEach(l => console.log('  t=' + l.t + 'ms [' + l.type + '] ' + l.text.slice(0, 200)));
console.log('DONE');
await page.screenshot({ path: '/tmp/y1render-local-final.png', fullPage: false });
await browser.close();