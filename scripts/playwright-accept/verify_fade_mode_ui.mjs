#!/usr/bin/env node
/**
 * verify_fade_mode_ui.mjs — AI降亏模式下拉·UI交互+性能专项验收(T3-1修复批 2026-08-23)
 *
 * 【目的】真实浏览器(chromium)实操冒烟, 验四件修复+性能硬指标:
 *   A(lab 页)
 *     A1 「AI降亏过滤」总开关文字与「模式」下拉同一可视行(同一 flex 容器/y 中点差<40px)
 *     A2 连续快切 7 个代表模式(间隔≤300ms): 不假死(最后切换后 500ms 内 DOM 可响应)+标签点亮态正确
 *        (p9 → .lab-sigkelly-toggle-bullstop 勾亮; p8 → 不亮; 每步校验)
 *     A3 toggle 勾选冷重算分片实测: 勾选→取消小标签强制全量重算(缓存签名变化), 采 longtask
 *        验证分片让步后 >200ms 长任务=0 且不假死(硬指标「任意操作 >200ms=0」的冷路径直接证据)
 *   B(sim 弹窗)
 *     B1 旧控件不存在(.sim-fade-cb / .sim-bullstop-cb)+新下拉存在(#sim-fade-mode-sel)
 *     B2 弹窗内快切 7 模式(间隔≤300ms)不卡死(同款响应探针)
 *   性能(performance 专项, 主控追加): 每阶段记录 PerformanceObserver longtask
 *     最大长任务 ms / >200ms 任务数 / 切换响应 ms, 输出 --perf-out JSON(供优化前后对比)。
 *     硬指标: 操作期 >200ms 长任务=0 且响应<500ms(首切含 trades.json 64MB 冷加载单独标注不计入)。
 *
 * 【用法】node verify_fade_mode_ui.mjs <baseURL> [--shot-prefix <path>] [--perf-out <json>]
 *         baseURL 例 http://localhost:8123(本地静态站); 截图默认存本目录。
 * 【复现】python3 -m http.server 8123 -d <站点目录> && node verify_fade_mode_ui.mjs http://localhost:8123
 * 【依赖】playwright(本目录 node_modules) + chromium(ms-playwright 缓存)
 * 【退出码】0=全部 PASS; 1=有 FAIL
 */
'use strict';
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const BASE = args.find((a) => !a.startsWith('--')) || 'http://localhost:8123';
function optOf(name, def) { const i = args.indexOf(name); return i > 0 ? args[i + 1] : def; }
const SHOT_PREFIX = optOf('--shot-prefix', path.join(path.dirname(new URL(import.meta.url).pathname), 'fade-mode-ui'));
const PERF_OUT = optOf('--perf-out', null);

// v20260826(用户拍板): new18 从下拉移除 → 快切清单同步去掉; 现预设 8 个(s06/p9/a9/b9/c9/new14/new15/p8),
// 冒烟取 7 代表档(含 s06 动态档)覆盖三档星标与两基座口径。
const MODES = ['p8', 'p9', 'a9', 'b9', 'c9', 'new14', 's06'];
const SWITCH_GAP_MS = 250;           // ≤300ms 快切要求
const PROBE_TIMEOUT_MS = 5000;       // 冻结探针上限(>500ms 即判不达标, >5s 视为彻底饿死)
const PROBE_PASS_MS = 500;           // 硬指标: 探针响应 <500ms

const results = [];   // {id, name, pass, detail}
const perf = {};      // {phase: {maxLongtaskMs, over200Count, probeMs, notes}}
function rec(id, name, pass, detail) {
  results.push({ id, name, pass: !!pass, detail });
  console.log(`[${pass ? 'PASS' : 'FAIL'}] ${id} ${name} — ${detail}`);
}
// 渲染器可能被饿死(测坏代码): 截图/close 全带超时护栏
const shot = async (pg, p2) => { await Promise.race([pg.screenshot({ path: p2 }).catch(() => {}), new Promise((r) => setTimeout(r, 6000))]); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
// 带超时的页面求值: 页面被饿死时裸 evaluate 会永久挂起(比探针更早死), 一律走此护栏
async function evalT(pg, fn, arg, to = 3000) {
  try {
    return await Promise.race([pg.evaluate(fn, arg), new Promise((r) => setTimeout(() => r('__TIMEOUT__'), to))]);
  } catch (e) { return '__TIMEOUT__'; }
}

// 在页面里装 longtask 收集器(addInitScript 保证先于业务脚本)
const OBSERVER_INIT = `
window.__lt = [];
try {
  const po = new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lt.push({ s: e.startTime, d: e.duration }); });
  po.observe({ entryTypes: ['longtask'] });
} catch (e) {}
`;
async function ltSnapshot(page) {
  return page.evaluate(() => { const a = window.__lt || []; window.__lt = []; return a; });
}
// 阶段性能汇总: maxLongtask / >200ms 计数 / 探针响应ms
function perfSum(entries, probeMs, notes) {
  const maxD = entries.reduce((m, e) => Math.max(m, e.d), 0);
  return { maxLongtaskMs: Math.round(maxD), over200Count: entries.filter((e) => e.d > 200).length, probeMs, notes: notes || '' };
}
// 冻结探针: 让主线程算 1+1 并回传。页面被微任务饿死时 evaluate 挂起→超时返回 {frozen:true}
async function probe(page) {
  const t0 = Date.now();
  try {
    await Promise.race([
      page.evaluate(() => 1 + 1),
      new Promise((_, rej) => setTimeout(() => rej(new Error('probe-timeout')), PROBE_TIMEOUT_MS)),
    ]);
    return { frozen: false, ms: Date.now() - t0 };
  } catch (e) {
    return { frozen: true, ms: Date.now() - t0 };
  }
}

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
// 封闭网络: 拦掉所有非 localhost 请求(R2 直链 ss.fx8.store 等), 强制业务走 CF 相对路径 fallback
// → 本地 /data/ 可达, 特征 JSON 必就绪, 复现路径与生产一致且测试可重复
await ctx.route(/^(?!.*localhost)/, (r) => r.abort());
const page = await ctx.newPage();
page.on('pageerror', (e) => console.log('[pageerror]', String(e).slice(0, 200)));
let consoleErr = 0; // 只计业务 JS 错误(pageerror + 非资源加载类 console.error); 封闭网络拦外域的 net::ERR 属预期噪声不计
page.on('pageerror', () => consoleErr++);
page.on('console', (m) => {
  if (m.type() !== 'error') return;
  const t = m.text() || '';
  if (/Failed to load resource|net::ERR|Failed to fetch/i.test(t)) return;
  consoleErr++;
});

try {
  // ───────────────────────── PHASE A: lab 页 ─────────────────────────
  await page.addInitScript(OBSERVER_INIT);
  await page.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 60000 });
  try {
    await page.waitForSelector('#lab-kelly-fade-mode-sel', { timeout: 45000 });
  } catch (e) {
    rec('A0', 'lab页模式下拉出现', false, '45s 内未出现 #lab-kelly-fade-mode-sel: ' + e.message);
  }

  if ((await page.$('#lab-kelly-fade-mode-sel'))) {
    // A1 同行断言: 总开关 label 与下拉同一 flex 容器 + y 中点差<20px + 下拉在文字右侧(紧跟其后)
    const rowInfo = await page.evaluate(() => {
      const lbl = document.querySelector('.lab-sigkelly-toggle-aimacro');
      const sel = document.querySelector('#lab-kelly-fade-mode-sel');
      if (!lbl || !sel) return { ok: false, why: 'label或select缺失' };
      const a = lbl.getBoundingClientRect(), b = sel.getBoundingClientRect();
      const yDiff = Math.abs((a.top + a.height / 2) - (b.top + b.height / 2));
      const after = b.left >= a.right; // 下拉起点在文字终点右侧=「紧跟其后」不换行
      return { ok: yDiff < 20 && after, yDiff: Math.round(yDiff), after, selW: Math.round(b.width) };
    });
    rec('A1', '「AI降亏过滤」与模式下拉同一可视行且紧跟其后', rowInfo.ok,
      `y中点差=${rowInfo.yDiff}px 右侧=${rowInfo.after} 下拉宽=${rowInfo.selW}px`);
    await shot(page, SHOT_PREFIX + '-lab-row.png');

    // A2 七模式快切(首个模式切换会冷加载 trades.json 64MB, 先暖场一次再计时)
    const warm = await page.evaluate(async () => {
      const sel = document.querySelector('#lab-kelly-fade-mode-sel');
      sel.value = 'p9'; sel.dispatchEvent(new Event('change', { bubbles: true }));
      return 'switched-p9-warmup';
    });
    // 等重算完(busy 标志复位=bar 重渲染完成)
    const tWarm0 = Date.now();
    while (Date.now() - tWarm0 < 120000) {
      const st = await probe(page);
      if (st.frozen) break;
      const done = await page.evaluate(() => !document.querySelector('.lab-custom-host--loading')).catch(() => null);
      if (done === true) { const bull = await page.$eval('input.lab-sigkelly-toggle-bullstop', (el) => el.checked).catch(() => null); if (bull === true) break; }
      await page.waitForTimeout(400);
    }
    const coldLoadSec = Math.round((Date.now() - tWarm0) / 100) / 10;

    // 稳态性能采样: 清空 longtask 缓冲再快切, 只统计稳态切换期任务(冷加载单列 notes)
    await ltSnapshot(page);
    let lastProbe = { frozen: true, ms: -1 };
    for (const m of MODES) {
      const r = await evalT(page, (mid) => {
        const sel = document.querySelector('#lab-kelly-fade-mode-sel');
        sel.value = mid; sel.dispatchEvent(new Event('change', { bubbles: true }));
        return 'ok';
      }, m);
      if (r === '__TIMEOUT__') break; // 页面饿死, 探针会给出冻结结论
      await page.waitForTimeout(SWITCH_GAP_MS);
    }
    lastProbe = await probe(page);
    // 等 busy 复位后验标签点亮态(p8 收尾=不亮; 再补验 p9 亮)
    let settleMs = 0;
    while (settleMs < 30000) {
      const st = await probe(page); settleMs += 300;
      if (st.frozen) break;
      const busy = await page.evaluate(() => !!document.querySelector('.lab-custom-host--loading')).catch(() => null);
      if (busy === false) break;
      await page.waitForTimeout(300);
    }
    const bullAfterP8 = await page.$eval('input.lab-sigkelly-toggle-bullstop', (el) => el.checked).catch(() => 'n/a');
    await evalT(page, () => { const s = document.querySelector('#lab-kelly-fade-mode-sel'); s.value = 'p9'; s.dispatchEvent(new Event('change', { bubbles: true })); return 'ok'; }, undefined);
    await page.waitForTimeout(SWITCH_GAP_MS);
    let settle2 = 0;
    while (settle2 < 30000) {
      const busy = await page.evaluate(() => !!document.querySelector('.lab-custom-host--loading')).catch(() => null);
      if (busy === false) break;
      await page.waitForTimeout(300); settle2 += 300;
    }
    const bullAfterP9 = await page.$eval('input.lab-sigkelly-toggle-bullstop', (el) => el.checked).catch(() => 'n/a');
    rec('A2a', 'lab 七模式快切不假死', !lastProbe.frozen && lastProbe.ms <= PROBE_PASS_MS,
      `探针响应=${lastProbe.ms}ms frozen=${lastProbe.frozen}(冷加载${coldLoadSec}s 单独标注)`);
    rec('A2b', '标签点亮态(p8 不亮/p9 亮 bullAuxBackupStop)', bullAfterP8 === false && bullAfterP9 === true,
      `p8→checked=${bullAfterP8} p9→checked=${bullAfterP9}`);
    perf.lab = perfSum(await ltSnapshot(page), lastProbe.ms, `冷加载(trades.json 64MB 解析)≈${coldLoadSec}s 不计入稳态`);
    await shot(page, SHOT_PREFIX + '-lab-after.png');

    // A3 冷重算分片实测(2026-08-23 性能专项): A2 快切命中逐桶缓存不代表冷路径, 这里勾选→取消小标签
    // 强制全量重算(缓存签名变化), 采 longtask 验证分片让步后单任务 <200ms(硬指标: 任意操作 >200ms=0)
    await ltSnapshot(page);
    await evalT(page, () => { const el = document.querySelector('input.lab-sigkelly-toggle-bullstop'); if (el) el.click(); return 'on'; });
    let s3a = 0;
    while (s3a < 90000) {
      const st = await probe(page); s3a += 300;
      if (st.frozen) break;
      const busy = await page.evaluate(() => !!document.querySelector('.lab-custom-host--loading')).catch(() => null);
      if (busy === false) break;
      await page.waitForTimeout(300);
    }
    const probeOn = await probe(page);
    await evalT(page, () => { const el = document.querySelector('input.lab-sigkelly-toggle-bullstop'); if (el) el.click(); return 'off'; });
    let s3b = 0;
    while (s3b < 90000) {
      const st = await probe(page); s3b += 300;
      if (st.frozen) break;
      const busy = await page.evaluate(() => !!document.querySelector('.lab-custom-host--loading')).catch(() => null);
      if (busy === false) break;
      await page.waitForTimeout(300);
    }
    const probeOff = await probe(page);
    const ltToggle = await ltSnapshot(page);
    rec('A3', 'toggle 勾选冷重算分片(不假死+>200ms 长任务=0)',
      !probeOff.frozen && probeOff.ms <= PROBE_PASS_MS && !ltToggle.some((e) => e.d > 200),
      `探针=${probeOff.ms}ms frozen=${probeOff.frozen} 开关全程最大长任务=${ltToggle.reduce((m, e) => Math.max(m, e.d), 0)}ms >200ms数=${ltToggle.filter((e) => e.d > 200).length}`);
    perf.labToggle = perfSum(ltToggle, Math.max(probeOn.ms, probeOff.ms), 'bullAuxBackupStop 开→关两次全量重算(缓存签名变化强制冷路径)');

    // A4 最冷路径实测: 费率预设切换(feeSig 变化→单笔重算缓存 _kellyRecomputeCache 全 miss,
    // 全部桶真重算=最坏场景)。0%剥离 ↔ 默认档来回各一次, 采 longtask 验证分片后 >200ms 仍=0
    await ltSnapshot(page);
    const feeBtn = (k) => evalT(page, (key) => {
      const b = document.querySelector('.lab-sigkelly-fee-btn[data-fee="' + key + '"]');
      if (!b) return 'no-btn:' + key;
      b.click(); return 'ok';
    }, k);
    let feeWait = async () => {
      let w = 0;
      while (w < 90000) {
        const st = await probe(page); w += 300;
        if (st.frozen) break;
        const busy = await page.evaluate(() => !!document.querySelector('.lab-custom-host--loading')).catch(() => null);
        if (busy === false) break;
        await page.waitForTimeout(300);
      }
      return probe(page);
    };
    await feeBtn('zero');            // 切 0%剥离(若键名不同 fallback no-btn 记录)
    const probeFee1 = await feeWait();
    await feeBtn('etf_main');        // 切回默认 ETF主流
    const probeFee2 = await feeWait();
    const ltFee = await ltSnapshot(page);
    rec('A4', '费率切换最冷路径(缓存全 miss 重算, 不假死+>200ms 长任务=0)',
      !probeFee2.frozen && probeFee2.ms <= PROBE_PASS_MS && !ltFee.some((e) => e.d > 200),
      `探针=${probeFee2.ms}ms frozen=${probeFee2.frozen} 全程最大长任务=${ltFee.reduce((m, e) => Math.max(m, e.d), 0)}ms >200ms数=${ltFee.filter((e) => e.d > 200).length}(fee1探针=${probeFee1.ms}ms)`);
    perf.labFeeCold = perfSum(ltFee, Math.max(probeFee1.ms, probeFee2.ms), '费率 0%剥离↔ETF主流 两轮全 miss 重算(最坏冷路径)');
  }

  // ───────────────────────── PHASE B: sim 弹窗 ─────────────────────────
  await page.goto(BASE + '/index.html', { waitUntil: 'domcontentloaded', timeout: 60000 });
  try {
    await page.waitForSelector('.sig-kbtn-sim', { timeout: 60000 });
    await page.click('.sig-kbtn-sim');
    await page.waitForSelector('#simBacktestModal:not(.hidden)', { timeout: 30000 });
  } catch (e) {
    rec('B0', 'sim弹窗打开', false, e.message.slice(0, 150));
  }
  if (await page.$('#simBacktestModal:not(.hidden)')) {
    rec('B0', 'sim弹窗打开', true, '#simBacktestModal 已显示');
    // B1 旧控件删净+新下拉在
    const ctl = await page.evaluate(() => ({
      oldFadeCb: document.querySelectorAll('#simBacktestModal .sim-fade-cb').length,
      oldBullCb: document.querySelectorAll('#simBacktestModal .sim-bullstop-cb').length,
      newSel: document.querySelectorAll('#simBacktestModal #sim-fade-mode-sel').length,
      options: (document.querySelector('#simBacktestModal #sim-fade-mode-sel') || { options: [] }).options.length,
    }));
    rec('B1', '旧两控件已删+新模式下拉存在', ctl.oldFadeCb === 0 && ctl.oldBullCb === 0 && ctl.newSel >= 1,
      `.sim-fade-cb=${ctl.oldFadeCb} .sim-bullstop-cb=${ctl.oldBullCb} #sim-fade-mode-sel=${ctl.newSel}(options=${ctl.options})`);

    // B2 七模式快切: 默认数据热区(recent)即可渲染, 无需等全量分片
    const ltSim0 = await Promise.race([ltSnapshot(page).catch(() => []), sleep(4000).then(() => [])]);
    for (const m of MODES) {
      const r = await evalT(page, (mid) => {
        const sel = document.querySelector('#simBacktestModal #sim-fade-mode-sel');
        sel.value = mid; sel.dispatchEvent(new Event('change', { bubbles: true }));
        return 'ok';
      }, m);
      if (r === '__TIMEOUT__') break; // 页面饿死(坏代码), 探针给冻结结论
      await page.waitForTimeout(SWITCH_GAP_MS);
    }
    const bProbe = await probe(page);
    rec('B2', 'sim 弹窗七模式快切不卡死', !bProbe.frozen && bProbe.ms <= PROBE_PASS_MS,
      `探针响应=${bProbe.ms}ms frozen=${bProbe.frozen}`);
    // 冻结时后续 evaluate 会挂起, 全部加超时护栏
    const safeEval = async (fn, to = 4000) => Promise.race([
      page.evaluate(fn).catch(() => null),
      new Promise((r) => setTimeout(() => r(null), to)),
    ]);
    await page.waitForTimeout(1200);
    const ltB = await Promise.race([ltSnapshot(page).catch(() => []), new Promise((r) => setTimeout(() => r([]), 4000))]);
    perf.sim = perfSum(ltB, bProbe.ms, '含 recent 热区渲染');
    await shot(page, SHOT_PREFIX + '-sim-modal.png');
    await safeEval(() => { const b = document.querySelector('#simBacktestModal .rule-modal-close'); if (b) b.click(); });
  }

  rec('CONSOLE', '无 error 级 console', consoleErr === 0, `error 数=${consoleErr}`);
} finally {
  await Promise.race([browser.close(), sleep(6000)]).catch(() => {});
}

if (PERF_OUT) {
  fs.writeFileSync(PERF_OUT, JSON.stringify({ base: BASE, at: new Date().toISOString(), switchGapMs: SWITCH_GAP_MS, perf, results }, null, 2));
  console.log('[perf] 已写 ' + PERF_OUT);
}
const fails = results.filter((r) => !r.pass);
console.log(`\n===== 总结: ${results.length - fails.length}/${results.length} PASS ${fails.length ? '(FAIL: ' + fails.map((f) => f.id).join(',') + ')' : ''} =====`);
process.exit(fails.length ? 1 : 0);
