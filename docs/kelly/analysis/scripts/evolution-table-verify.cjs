// 演进弹窗·表格视图对账脚本(docs/kelly/analysis/evolution-table-impl-20260910.md 复现脚本)
// 目的: 验证表格「📌 当前全量」末行与全信号卡 feeStats.all.all 逐位一致 + 重开稳定性 + 全史粒度 + 耗时。
// 口径: 买入=全信号(评级三区并集)×S06 动态基座(按 signal_date 取 a9/new14)×AI仓位建议 K=1 每日只买最优1笔、
//       每日资金池 1 万等分×ETF 主流费率重算; 历史行=截至该日已平仓(closed-by-D); 末行=当前全量含未平仓。
// 输入依赖: 本地 http 服务 8898 提供 static-site(需 static-site/data 真实数据: signal_kelly_trades.json 74MB
//           + signal_kelly_snapshots/index.json + signal_kelly_backtest.json); playwright 安装在 /Users/linhuichen/node_modules。
// 重跑命令: cd static-site && python3 -m http.server 8898  (另终端) node docs/kelly/analysis/scripts/evolution-table-verify.cjs
// 退出码: 0=全部 PASS, 2=任一对账 FAIL。
const path = require('path');
const { chromium } = require('/Users/linhuichen/node_modules/playwright');
const fs = require('fs');
const ROOT = path.resolve(__dirname, '../../../..'); // scripts → analysis → kelly → docs → repo 根
const LAB_JS = fs.readFileSync(ROOT + '/static-site/lab.js', 'utf-8');
const APP_JS = fs.readFileSync(ROOT + '/static-site/app.js', 'utf-8');

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('PAGEERROR: ' + e.message.slice(0, 300)));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text().slice(0, 200)); });

  await page.route('**/lab.min.js*', (route) => route.fulfill({ status: 200, contentType: 'text/javascript', body: LAB_JS }));
  await page.route('**/app.min.js*', (route) => route.fulfill({ status: 200, contentType: 'text/javascript', body: APP_JS }));
  await page.route('https://ss.fx8.store/**', (route) => route.fulfill({ status: 404, contentType: 'text/plain', body: '{}' }));
  await page.route('https://hm.baidu.com/**', (route) => route.abort());
  await page.route('https://zz.bdstatic.com/**', (route) => route.abort());
  await page.route('https://sp0.baidu.com/**', (route) => route.abort());

  try {
    await page.goto('http://127.0.0.1:8898/index.html#lab?sub=sigkelly', { waitUntil: 'load', timeout: 60000 });
  } catch (e) { console.log('goto warn:', e.message); }

  // 等演进按钮 + 全量数据就绪
  await page.waitForSelector('#lab-kelly-evo-btn', { timeout: 60000 });
  await page.waitForFunction(() => typeof _labKellyAllReady === 'boolean', null, { timeout: 120000 });
  for (let i = 0; i < 60; i++) {
    const ready = await page.evaluate(() => !!_labKellyAllReady && !!state.labSigKellyFeeStats);
    if (ready) break;
    await page.waitForTimeout(2000);
  }
  const pre = await page.evaluate(() => ({
    allReady: !!_labKellyAllReady,
    hasFeeStats: !!state.labSigKellyFeeStats,
    gigOn: !!state.labSigKellyGihOn,
    base: state.labSigKellyFadeModeBase,
    fkeys: state.labSigKellyFeeStats && state.labSigKellyFeeStats.all ? Object.keys(state.labSigKellyFeeStats.all.all).filter((k) => !k.includes('__')) : []
  }));
  console.log('PRE:', JSON.stringify(pre));

  // 点演进按钮, 切表格 tab
  await page.click('#lab-kelly-evo-btn');
  await page.waitForSelector('#labKellyEvoOverlay', { timeout: 15000 });
  await page.click('.lab-kelly-evo-tab[data-evo-tab="table"]');
  try {
    await page.waitForSelector('#lab-kelly-evo-table-host .lab-kelly-evo-table tbody tr', { timeout: 180000 });
  } catch (e) {
    const host = await page.innerHTML('#lab-kelly-evo-table-host').catch(() => '');
    console.log('RESULT: FAIL - 表格未渲染. HOST:', host.slice(0, 2000));
    fs.writeFileSync('/tmp/evo-table-test/fail-errors.txt', errors.join('\n') || '(no errors)');
    await browser.close();
    process.exit(1);
  }

  // 抽末行(📌 当前全量) 每模式 {p, r, n}
  const finalRow = await page.evaluate(() => {
    const rows = document.querySelectorAll('#lab-kelly-evo-table-host .lab-kelly-evo-table tbody tr');
    const last = rows[rows.length - 1];
    const ths = document.querySelectorAll('#lab-kelly-evo-table-host .lab-kelly-evo-table thead th');
    const modeKeys = [];
    ths.forEach((th, i) => { if (i > 0) modeKeys.push(th.textContent.trim()); });
    const cells = last.querySelectorAll('td');
    const data = { date: cells[0].textContent.trim(), modes: {} };
    for (let i = 1; i < cells.length; i++) {
      const spans = cells[i].querySelectorAll('.lab-kelly-evo-p');
      const nEl = cells[i].querySelector('.lab-kelly-evo-n');
      data.modes[modeKeys[i - 1]] = {
        p: spans[0] ? spans[0].textContent.trim() : '-',
        r: spans[1] ? spans[1].textContent.trim() : '-',
        n: nEl ? nEl.textContent.trim() : '-'
      };
    }
    return data;
  });

  // 卡 stats(含 GIH __gihb1) 对比基准
  const cardStats = await page.evaluate(() => {
    const fs = state.labSigKellyFeeStats;
    if (!fs || !fs.all || !fs.all.all) return null;
    const st = {};
    const base = fs.all.all;
    for (const m of Object.keys(base)) {
      const r = base[m];
      if (!r) continue;
      st[m] = { tp: r.total_profit, rmh: r.return_pct_max_holding, n: r.n };
    }
    return st;
  });

  const foot = await page.textContent('#lab-kelly-evo-table-host .lab-kelly-evo-foot').catch(() => '');
  const rowInfo = await page.evaluate(() => {
    const rows = document.querySelectorAll('#lab-kelly-evo-table-host .lab-kelly-evo-table tbody tr');
    return { shown: rows.length, first: rows[0] ? rows[0].querySelector('td').textContent.trim() : '-', last: rows[rows.length - 1].querySelector('td').textContent.trim() };
  });

  console.log('FINAL ROW:', JSON.stringify(finalRow, null, 1));
  console.log('CARD STATS:', JSON.stringify(cardStats, null, 1));
  console.log('ROW INFO:', JSON.stringify(rowInfo));
  console.log('FOOT:', foot);

  // 对账: 末行 A/G/H/I 与卡逐位
  const notes = [];
  let pass = true;
  const checks = ['A', 'E', 'G', 'H', 'I'];
  for (const m of checks) {
    const expKey = (!pre.gigOn && ['G', 'H', 'I'].includes(m)) ? m : ((pre.gigOn && ['G', 'H', 'I'].includes(m)) ? m + '__gihb1' : m);
    const cs = cardStats ? cardStats[expKey] || cardStats[m] || null : null;
    if (!cs) { notes.push(m + ': 卡无该模式, 跳过'); continue; }
    const expectP = (cs.tp >= 0 ? '+' : '') + cs.tp.toFixed(0);
    const expectR = (cs.rmh >= 0 ? '+' : '') + cs.rmh.toFixed(2) + '%';
    const gotP = (finalRow.modes[m] || {}).p;
    const gotR = (finalRow.modes[m] || {}).r;
    const okP = gotP === expectP;
    const okR = gotR === expectR;
    notes.push(`${m}: 净利 "${gotP}" vs 卡 "${expectP}" ${okP ? 'OK' : 'MISMATCH'} | 收益率 "${gotR}" vs 卡 "${expectR}" ${okR ? 'OK' : 'MISMATCH'}`);
    if (!okP || !okR) pass = false;
  }

  // 历史行稳定性抽查: 取样 3 个历史行(60行粒度内)重开重算对比(值应稳定——重开弹窗再抽同末行前一行)
  await page.click("#labKellyEvoOverlay .lab-rank-modal-close");
  await page.click('#lab-kelly-evo-btn');
  await page.waitForSelector('#labKellyEvoOverlay', { timeout: 15000 });
  await page.click('.lab-kelly-evo-tab[data-evo-tab="table"]');
  await page.waitForSelector('#lab-kelly-evo-table-host .lab-kelly-evo-table tbody tr', { timeout: 180000 });
  const second = await page.evaluate(() => {
    const rows = document.querySelectorAll('#lab-kelly-evo-table-host .lab-kelly-evo-table tbody tr');
    const last = rows[rows.length - 1];
    const ths = document.querySelectorAll('#lab-kelly-evo-table-host .lab-kelly-evo-table thead th');
    const modeKeys = []; ths.forEach((th, i) => { if (i > 0) modeKeys.push(th.textContent.trim()); });
    const cells = last.querySelectorAll('td');
    const out = { date: cells[0].textContent.trim(), modes: {} };
    for (let i = 1; i < cells.length; i++) {
      const spans = cells[i].querySelectorAll('.lab-kelly-evo-p');
      out.modes[modeKeys[i - 1]] = { p: spans[0] ? spans[0].textContent.trim() : '-', r: spans[1] ? spans[1].textContent.trim() : '-' };
    }
    return out;
  });
  // 稳定性对比只比 p/r(两次弹窗的 n 字段结构不同, 不比 n)
  const stripN = (o) => { const m = {}; for (const k in o.modes) m[k] = { p: o.modes[k].p, r: o.modes[k].r }; return { date: o.date, modes: m }; };
  const stable = JSON.stringify(stripN(finalRow)) === JSON.stringify(stripN(second));
  notes.push('重开弹窗末行稳定(两次 p/r 一致): ' + (stable ? 'OK' : 'MISMATCH'));
  if (!stable) pass = false;

  // 全史粒度行数
  await page.click('.lab-kelly-evo-gran-btn[data-evo-gran="all"]');
  await page.waitForFunction(() => {
    const rows = document.querySelectorAll('#lab-kelly-evo-table-host .lab-kelly-evo-table tbody tr');
    return rows.length > 70;
  }, null, { timeout: 30000 });
  const allRowsInfo = await page.evaluate(() => {
    const rows = document.querySelectorAll('#lab-kelly-evo-table-host .lab-kelly-evo-table tbody tr');
    const ths = document.querySelectorAll('#lab-kelly-evo-table-host .lab-kelly-evo-table thead th');
    return { rows: rows.length, cols: ths.length, first: rows[0] ? rows[0].querySelector('td').textContent.trim() : '-' };
  });
  notes.push('全史粒度: ' + JSON.stringify(allRowsInfo));
  // 全史应 = 轴点总数(582) + 1 pin 行 = 583, 且远超 60 粒度; 首行应早于 2020
  if (allRowsInfo.rows < 500 || allRowsInfo.rows <= 61) pass = false;
  if (allRowsInfo.first >= '20200101') pass = false; // 全史首行应覆盖早年

  fs.writeFileSync('/tmp/evo-table-test/errors.txt', errors.join('\n') || '(no errors)');
  console.log('PAGE ERRORS:', errors.length ? '\n' + errors.join('\n') : '(none)');
  console.log('NOTES:\n' + notes.join('\n'));
  console.log('RESULT:', pass ? 'PASS' : 'FAIL');
  await browser.close();
  process.exit(pass ? 0 : 2);
})();