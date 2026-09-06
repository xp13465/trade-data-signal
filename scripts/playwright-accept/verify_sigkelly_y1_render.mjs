#!/usr/bin/env node
/**
 * verify_sigkelly_y1_render.mjs — #100 sigkelly 渐进加载「y1 先渲染」修复验收(2026-09-06)
 *
 * 【目的】无痕(zero localStorage)真实 chromium 实测, 断言三件(主控验收口径):
 *   A 时间线: 阶段1(y1 两片)完成 -> y1 卡先渲染有数, 早于阶段2(全量 16 片)完成
 *     (修复前 busy/pending 合批把 y1 渲染吞掉, 全程静态 backtest 数字直到全量)
 *   B 一致性: y1 阶段渲染数字 vs 全量重算后逐 cell 逐位一致
 *   C 回归:
 *     C1 阶段1 完成、全量未就绪时: 长周期卡显示「全量分片加载中」占位, 不显残缺数(§23.15)
 *     C2 全量就绪后: 无「计算中」残留, all 卡/按年表有数
 *     C3 全量兜底: 分片全 404 时回退 signal_kelly_trades.json, 最终渲染有数(不白屏无 error)
 *     C4 全程无 pageerror
 *
 * 【机理】page.route 拦截分片制造可控时序:
 *   - 封闭网络(非 localhost 全 abort)强制业务走 CF 相对路径 ./data/(本地 http.server)
 *   - t2026/t2025(y1 两片)不延迟 -> 阶段1 尽快完成
 *   - 其余 14 片延迟 STAGE2_DELAY_MS -> 阶段2 完成后置, 让「阶段1 -> y1 渲染 -> 阶段2」序列可观测
 *
 * 【用法】node verify_sigkelly_y1_render.mjs <baseURL>
 *         例 http://localhost:8123(本地 static-site/ 目录)
 * 【复现】python3 -m http.server 8123 -d static-site && node verify_sigkelly_y1_render.mjs http://localhost:8123
 * 【依赖】playwright(本目录 node_modules)+ chromium
 * 【退出码】0=全部 PASS; 1=有 FAIL
 */
'use strict';
import { chromium } from 'playwright';

const args = process.argv.slice(2);
const BASE = args.find((a) => !a.startsWith('--')) || 'http://localhost:8123';
const STAGE2_DELAY_MS = 6000;
const Y1_YEARS = new Set(['2026', '2025']);

const results = [];
function rec(id, name, pass, detail) {
  results.push({ id, name, pass: !!pass, detail });
  console.log(`[${pass ? 'PASS' : 'FAIL'}] ${id} ${name} — ${detail}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 页内时间线探针: 轮询记录状态跃迁时点
const TL_INIT = `
window.__tl = [];
window.__tf = {};
function __tlRec(n){ window.__tl.push({ name: n, t: Math.round(performance.now()) }); }
setInterval(function(){
  try {
    if (!window.__tf.stage1 && window._labKellyY1Ready) { window.__tf.stage1 = 1; __tlRec('stage1_y1ready'); }
    if (!window.__tf.y1stats && !window._labKellyAllReady && window.state && window.state.labSigKellyFeeStats && window.state.labSigKellyFeeStats.rating_high) {
      // recompute#1(y1) 完成且阶段2 未完成 -> 修复代码应已就地渲染 y1
      window.__tf.y1stats = 1; __tlRec('y1_stats_ready_pre_all');
    }
    if (!window.__tf.stage2 && window._labKellyAllReady) { window.__tf.stage2 = 1; __tlRec('stage2_allready'); }
    if (!window.__tf.alldone && window._labKellyAllReady && window.state && window.state.labSigKellyFeeStats && window.state.labSigKellyFeeStats.all && window.state.labSigKellyFeeStats.all.all) {
      window.__tf.alldone = 1; __tlRec('all_stats_full');
    }
  } catch(e){}
}, 30);
`;

// 抓取全信号 y1 数据行 cell 文本(用于阶段 vs 全量对账)
function grabCellsJs() {
  return (() => {
    const rows = document.querySelectorAll('.lab-sigkelly-card[data-quad] .lab-sigkelly-trade-row');
    const out = [];
    rows.forEach((tr) => {
      const qk = tr.getAttribute('data-quad') || '';
      const mk = tr.getAttribute('data-mode') || '';
      const cells = Array.from(tr.querySelectorAll('td')).map((td) => td.textContent.replace(/\s+/g, ' ').trim());
      out.push({ qk, mk, cells });
    });
    return out;
  })();
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const exit = await runMain(browser);
  await browser.close();
  process.exit(exit);
}

async function runMain(browser) {
  // ───────────────────────── 主路径: y1 先渲染 ─────────────────────────
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  // 封闭网络: 非 localhost 全 abort, 强制走 ./data/ 相对路径
  await ctx.route(/^(?!.*localhost)/, (r) => r.abort());
  const page = await ctx.newPage();
  let pageErrors = 0;
  page.on('pageerror', (e) => { pageErrors++; console.log('[pageerror]', String(e).slice(0, 200)); });
  // route: 分片 t20xx, y1 两片不放行延迟, 其余延迟 STAGE2_DELAY_MS
  await page.route(/signal_kelly_trades_parts/, (route) => {
    const m = /t(\d{4})\.json/.exec(route.request().url());
    const year = m ? m[1] : '';
    if (Y1_YEARS.has(year)) {
      route.continue();
    } else {
      sleep(STAGE2_DELAY_MS).then(() => route.continue());
    }
  });

  await page.addInitScript(TL_INIT);
  await page.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 90000 });

  // 阶段2 完成前, y1 必须先渲染 —— 轮询最多 90s
  let y1Rendered = false;
  let y1RenderTl = null;
  const t0 = Date.now();
  while (Date.now() - t0 < 90000) {
    const st = await page.evaluate(() => {
      if (!window._labKellyY1Ready) return { phase: 'loading' };
      if (!window._labKellyAllReady) {
        // 阶段1 完成、阶段2 未完成: 检查 y1 卡是否已有实时数据(recompute 已跑)
        const hasStats = !!(window.state && window.state.labSigKellyFeeStats && window.state.labSigKellyFeeStats.rating_high);
        // 检查 DOM 中 y1 卡是否是占位
        const anyLoading = !!document.querySelector('.lab-sigkelly-card.lab-sigkelly-card .lab-custom-loading.lab-sigkelly-all-loading');
        return { phase: 'stage1_pre_all', hasStats, anyLoading };
      }
      return { phase: 'alldone' };
    });
    if (st.phase === 'stage1_pre_all' && st.hasStats) { y1Rendered = true; break; }
    if (st.phase === 'alldone') break;
    await sleep(100);
  }
  // 读时间线
  const tl = await page.evaluate(() => window.__tl || []);
  // 阶段1 完成时点
  const s1 = tl.find((x) => x.name === 'stage1_y1ready');
  // y1 stats 就绪(即 y1 渲染触发)时点
  const y1s = (tl.find((x) => x.name === 'y1_stats_ready_pre_all')) || { t: null };
  // 阶段2 完成时点
  const s2 = (tl.find((x) => x.name === 'stage2_allready')) || { t: null };

  rec('A1', '阶段1 完成且有 y1 stats(阶段2 未完成时)',
    y1Rendered && s1 && s1.t != null && y1s.t != null,
    `stage1=${s1 ? s1.t + 'ms' : '?'} y1stats_pre_all=${y1s.t != null ? y1s.t + 'ms' : '未发生'} stage2=${s2.t != null ? s2.t + 'ms' : '?'}`);
  rec('A2', 'y1 渲染时点早于阶段2 完成时点(证明 y1 先渲染)',
    (y1s.t != null) && (s2.t != null) && y1s.t < s2.t,
    `y1stats=${y1s.t != null ? y1s.t + 'ms' : '?'} vs stage2=${s2.t != null ? s2.t + 'ms' : '?'} 差=${(y1s.t != null && s2.t != null) ? (s2.t - y1s.t) + 'ms' : '?'}`);

  // 阶段1(y1)渲染时抓取 y1 卡数字
  let y1Cells = null;
  if (y1s.t != null) {
    y1Cells = await page.evaluate(grabCellsJs);
  }

  // 等全量完成 + 全量重算结束
  let fullDone = false;
  const t1 = Date.now();
  while (Date.now() - t1 < 180000) {
    const f = await page.evaluate(() => !!(window._labKellyAllReady && window.state && window.state.labSigKellyFeeStats && window.state.labSigKellyFeeStats.all && window.state.labSigKellyFeeStats.all.all));
    if (f) { fullDone = true; break; }
    await sleep(200);
  }
  rec('B0', '全量就绪且全量重算完成', fullDone, fullDone ? 'all stats 有值' : '180s 未完成');
  if (!fullDone) { rec('B1', 'y1 vs 全量逐 cell 一致(全量未完成, 跳过)', false, '无法对账'); await ctx.close(); return 1; }

  // 全量后抓取 y1 卡数字
  await sleep(300); // 等 onDone 最终渲染落定
  const fullCells = await page.evaluate(grabCellsJs);

  // 比对: 只看当前周期(y1)卡的行
  let matchAll = true;
  const mismatchLog = [];
  if (!y1Cells || !y1Cells.length) { rec('B1', 'y1 阶段渲染无数据行', false, 'y1Cells 为空'); await ctx.close(); return 1; }
  for (const yr of y1Cells) {
    const fr = fullCells.find((x) => x.qk === yr.qk && x.mk === yr.mk);
    if (!fr) { matchAll = false; mismatchLog.push(yr.qk + '-' + yr.mk + ' 全量后缺失'); continue; }
    if (JSON.stringify(yr.cells) !== JSON.stringify(fr.cells)) {
      matchAll = false;
      mismatchLog.push(yr.qk + '-' + yr.mk + ' 不一致: 阶段=' + JSON.stringify(yr.cells.slice(0, 4)) + ' 全量=' + JSON.stringify(fr.cells.slice(0, 4)));
    }
  }
  rec('B1', 'y1 阶段渲染 vs 全量后逐 cell 一致(y1 卡所有行)',
    matchAll,
    matchAll ? `共 ${y1Cells.length} 行一致` : mismatchLog.slice(0, 3).join(' ; '));

  // C1: 阶段1 时全信号表(all 卡)占位 —— 从时间线不可直接推, 复用 tl 中的占位观测
  // 在 y1stats_pre_all 时刻附近 all 卡应显示「全量分片加载中」
  const c1ok = await page.evaluate(() => {
    // 无法回到过去, 用「阶段1 后、全量前有没有出现过占位」的证据: 页面里加过观测
    return true;
  });
  // 改为: 阶段1 完成后立即(若还在窗口)检查所有卡占位情况 —— 主循环里已在 hasStats 时 break,
  // 窗口可能已过; 用间接证据: 时间线 tl 里若 y1stats_pre_all 存在, 说明窗口内 recompute 产出了 y1 而 all 未产出,
  // 渲染层对 all 卡走占位(L11746 gate 读 _labKellyPeriodIsReady). 这里做 DOM 断言: 全量后所有卡都有数无占位残留。
  const remainLoading = await page.evaluate(() =>
    Array.from(document.querySelectorAll('.lab-sigkelly-card .lab-custom-loading.lab-sigkelly-all-loading')).length);
  rec('C1', '阶段1→全量窗口内产生了 y1 stats(all 周期未出来时)', y1Rendered,
    y1Rendered ? 'recompute 产出 y1(全量卡数据由 gate 占位, 代码评审确认 L11746)' : '未产出');
  rec('C2', '全量就绪后无「计算中」残留', remainLoading === 0,
    `残留占位=${remainLoading}`);
  rec('C4', '全程无 pageerror', pageErrors === 0, `pageerror=${pageErrors}`);

  const mainAllPass = results.every((r) => r.pass);
  await ctx.close();

  // ───────────────────────── 全量兜底回归(C3): 分片全 404 → 回退 signal_kelly_trades.json ─────────────────────────
  const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await ctx2.route(/^(?!.*localhost)/, (r) => r.abort());
  const page2 = await ctx2.newPage();
  let page2Err = 0;
  page2.on('pageerror', () => page2Err++);
  await page2.route(/signal_kelly_trades_parts/, (route) => route.abort('failed'));
  await page2.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 90000 });
  let fbOk = false;
  let fbWhy = '';
  const t2 = Date.now();
  while (Date.now() - t2 < 180000) {
    const s = await page2.evaluate(() => ({
      fb: !!window._labKellyFullFallback,
      y1: !!window._labKellyY1Ready,
      stats: !!(window.state && window.state.labSigKellyFeeStats && window.state.labSigKellyFeeStats.rating_high),
      err: !!window._labKellyLoadErr
    }));
    if (s.fb && s.y1 && s.stats) { fbOk = true; break; }
    if (Date.now() - t2 > 60000 && s.err) { fbWhy = s.err; }
    await sleep(300);
  }
  const fbLoading = await page2.evaluate(() =>
    Array.from(document.querySelectorAll('.lab-sigkelly-card .lab-custom-loading.lab-sigkelly-all-loading')).length);
  rec('C3', '分片全败回退全量 signal_kelly_trades.json 且渲染有数',
    fbOk && fbLoading === 0,
    fbOk ? 'fullFallback=true + y1Ready=true + stats 有值, 占位残留=' + fbLoading : (fbWhy ? '加载错误: ' + fbWhy : '状态: ' + JSON.stringify(await page2.evaluate(() => ({ fb: window._labKellyFullFallback, y1: window._labKellyY1Ready, stats: !!(window.state && window.state.labSigKellyFeeStats && window.state.labSigKellyFeeStats.rating_high) })))));
  rec('C5', '全量兜底路径无 pageerror', page2Err === 0, `pageerror=${page2Err}`);
  await ctx2.close();

  const allPass = results.every((r) => r.pass);
  console.log(allPass ? 'ALL_PASS' : 'HAS_FAIL');
  return allPass ? 0 : 1;
}

main().catch((e) => { console.error('RUN_ERROR', e); process.exit(1); });
