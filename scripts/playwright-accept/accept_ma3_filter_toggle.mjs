#!/usr/bin/env node
// 2026-11-21 「MA3连3日」降亏筛选开关 · 首页验收(默认关不影响既有视图 + 开=灰显/标注 + 与仅显示可用联动)。
//
// 运行(在 scripts/playwright-accept 下):
//   SOURCE_ROOT=<worktree根> DATA_ROOT=<源数据根(可选, 默认自动推断)> BASE_URL=<站点> node accept_ma3_filter_toggle.mjs
//
// 机制: 用 mobile_source_harness 把 .min.js/.min.css 回源到 SOURCE_ROOT 下的未压缩源文件
// (worktree 未做 build_min, 直接跑 .min 会验到旧产物); data 目录以「符号链接全集 + 注入副本」
// 临时重建, 只在 signals_today/overview 的副本里给 4 条入样买入信号注入 _ma3(2 命中/1 未命中/1 数据不足),
// 不改任何真实数据文件。页面逻辑与后端打标的接口契约由此用例覆盖(后端判定另有 pytest 单测)。
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { createRequire } from 'node:module';
import { installSources, dismissIntro, saveEvidence } from './mobile_source_harness.mjs';

const { chromium } = createRequire(import.meta.url)('playwright');
const HERE = path.dirname(new URL(import.meta.url).pathname);
const SOURCE_ROOT = process.env.SOURCE_ROOT || path.resolve(HERE, '../..');
process.env.SOURCE_ROOT = SOURCE_ROOT;
const DATA_SRC = path.resolve(process.env.DATA_ROOT || path.resolve(SOURCE_ROOT, 'static-site/data'));
const BUY = new Set(['buy', 'buy_aux', 'buy_special', 'buy_backup']);

// --- 数据副本: 符号链接全集 + 两个 JSON 先写「未注入」副本 ---
// 未注入副本先让探针跑一遍真实基线(DOM 里可见的行集随窗口/ETF档/仓位建议联动),
// 再只对「基线上确实渲染出来的买入信号」定向注入 _ma3。若随便挑文件里的前几条,
// 它们在「仅显示可用」视图里可能早已被仓位建议 top-K(当日已满)隐藏, 断言会变成假空转。
// ⚠️ mobile_source_harness 的 read() 有模块级 cache(按文件路径缓存字节), 探针读过的路径
// 后续一律返回旧字节。所以探针与正式场景必须用两个不同目录, 注入只写正式目录。
const TMP = await fsp.mkdtemp(path.join(os.tmpdir(), 'ma3-accept-'));
const TMP_PROBE = await fsp.mkdtemp(path.join(os.tmpdir(), 'ma3-probe-'));
for (const name of await fsp.readdir(DATA_SRC)) {
  await fsp.symlink(path.join(DATA_SRC, name), path.join(TMP, name));
  await fsp.symlink(path.join(DATA_SRC, name), path.join(TMP_PROBE, name));
}
const DATA_FILES = ['signals_today.json', 'overview.json'];
for (const fn of DATA_FILES) {
  const src = path.join(DATA_SRC, fn);
  if (!fs.existsSync(src)) continue;
  const body = await fsp.readFile(src, 'utf8');
  for (const dir of [TMP, TMP_PROBE]) {
    await fsp.rm(path.join(dir, fn), { force: true });
    await fsp.writeFile(path.join(dir, fn), body);
  }
}
process.env.DATA_ROOT = TMP_PROBE;  // 探针先跑未注入副本

const injections = [];  // 记录注入结果供断言预期
let expectHits = 0;
const SIG_KEY = (s) => `${s.date}|${s.index_id}|${s.signal}`;
// planByKey: key -> {hit,status,reason}; 只改命中的 key, 其余信号保持原样(不臆造字段)
async function applyPlanToData(planByKey) {
  for (const fn of DATA_FILES) {
    const src = path.join(TMP_PROBE, fn);
    if (!fs.existsSync(src)) continue;
    const obj = JSON.parse(await fsp.readFile(src, 'utf8'));
    const sigs = Array.isArray(obj) ? obj : (obj && Array.isArray(obj.signals_today) ? obj.signals_today : null);
    if (!sigs) { console.error(`[warn] ${fn} 未找到 signals_today 数组`); continue; }
    for (const s of sigs) {
      if (!s || !BUY.has(s.signal)) continue;
      const plan = planByKey[SIG_KEY(s)];
      if (!plan) continue;
      const code = (s.etfs || []).find((e) => e && e.code);
      const etf = code ? code.code : null;
      s._ma3 = { ...plan, etf, ma3: plan.status === 'ok' ? 1.2345 : null, close: plan.status === 'ok' ? 1.1111 : null };
      if (fn === 'signals_today.json') injections.push({ date: s.date, signal: s.signal, index_id: s.index_id, etf, hit: plan.hit, status: plan.status });
    }
    await fsp.writeFile(path.join(TMP, fn), JSON.stringify(obj));
  }
  expectHits = injections.filter((x) => x.hit === true).length;
}

const BASE = process.env.BASE_URL || 'https://ss.fx8.store';
const browser = await chromium.launch({ headless: true });
const results = []; let failures = 0;
const check = (name, pass, detail) => { results.push({ name, pass: !!pass, detail }); if (!pass) failures++; };
try {
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
  const page = await context.newPage();
  const pageErrors = []; page.on('pageerror', (e) => pageErrors.push(String(e)));
  const cellCount = () => page.locator('.sig-card .signal-grid .sig-item').count();

  // 探针(只用未注入副本): 取「仅显示可用 + AI降亏关」视图里基线真实可见的买入信号作为注入目标。
  // 单靠文件顺序挑候选不可靠——很多信号在该视图里被仓位建议 top-K(当日已满)隐藏, 开 MA3 前后都不可见,
  // 断言 116==116 会假空转(上一版即踩此坑)。命中 2 条必须落不同日期(K=1 每日只 1 个 kept 行)。
  const probeCtx = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
  const probePage = await probeCtx.newPage();
  await installSources(probePage);
  await probePage.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await probePage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached', timeout: 60000 });
  await dismissIntro(probePage);
  await probePage.evaluate(() => { localStorage.setItem('tds_home_fade', '0'); localStorage.setItem('tds_home_show_available_only', '1'); localStorage.setItem('tds_home_ma3', '0'); });
  await probePage.reload({ waitUntil: 'domcontentloaded' });
  await probePage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const visible = await probePage.evaluate(() => [...document.querySelectorAll('.sig-card .signal-grid .sig-item')]
    .map((e) => ({ date: e.getAttribute('data-date'), idx: e.getAttribute('data-idx'), sig: e.getAttribute('data-sig') }))
    .filter((x) => x.date && x.idx && ['buy', 'buy_aux', 'buy_special', 'buy_backup'].includes(x.sig)));
  await probeCtx.close();
  const keyOf = (v) => `${v.date}|${v.idx}|${v.sig}`;
  const hitTargets = []; const seenDates = new Set();
  for (const v of visible) {
    if (seenDates.has(v.date)) continue;
    seenDates.add(v.date); hitTargets.push(v);
    if (hitTargets.length === 2) break;
  }
  const others = visible.filter((v) => !hitTargets.some((h) => keyOf(h) === keyOf(v)));
  if (hitTargets.length !== 2 || others.length < 2) {
    console.error('探针失败: 基线可见买入信号不足 visible=' + JSON.stringify(visible.slice(0, 12)));
    process.exit(2);
  }
  const planByKey = {
    [keyOf(hitTargets[0])]: { hit: true, status: 'ok', reason: null },
    [keyOf(hitTargets[1])]: { hit: true, status: 'ok', reason: null },
    [keyOf(others[0])]: { hit: false, status: 'ok', reason: null },
    [keyOf(others[1])]: { hit: null, status: 'na', reason: 'short_history' },
  };
  await applyPlanToData(planByKey);
  if (expectHits !== 2) {
    console.error('注入失败: 期望 2 条命中, 实际 ' + expectHits + ' ' + JSON.stringify(injections));
    process.exit(2);
  }
  process.env.DATA_ROOT = TMP;  // 正式场景切到注入后的独立目录(避开 harness 进程级缓存)
  console.log('[prep] 注入 = ' + JSON.stringify(injections));

  // A. 默认态(零 localStorage): 开关在位且未勾, 无任何 MA3 标记
  await installSources(page); await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached', timeout: 60000 });
  await dismissIntro(page);
  check('A1 开关默认未勾', !(await page.locator('.sig-switch-ma3-cb').isChecked()));
  check('A2 默认态无灰显行', (await page.locator('.sig-card .sig-ma3-hit').count()) === 0);
  check('A3 默认态无 MA3 角标', (await page.locator('.sig-card .sig-ma3-badge').count()) === 0);
  check('A4 默认态未写本机记忆', (await page.evaluate(() => localStorage.getItem('tds_home_ma3'))) === null);

  // B. 关掉 AI降亏 / 仅显示可用(排除两层干扰) → 记录整列表, 勾选后逐项断言
  await page.evaluate(() => { localStorage.setItem('tds_home_fade', '0'); localStorage.setItem('tds_home_show_available_only', '0'); });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const nAll = await cellCount();
  check('B1 全量列表已渲染', nAll > 4, { nAll });
  await page.locator('.sig-switch-ma3-cb').check();
  check('B2 勾选后 checkbox=checked', await page.locator('.sig-switch-ma3-cb').isChecked());
  check('B3 本机记忆写入 1', (await page.evaluate(() => localStorage.getItem('tds_home_ma3'))) === '1');
  const nHit = await page.locator('.sig-card .sig-item.sig-ma3-hit').count();
  const nBadge = await page.locator('.sig-card .sig-ma3-badge').count();
  check('B4 灰显行数 == 注入命中数', nHit === expectHits, { nHit, expectHits });
  check('B5 角标数 == 注入命中数', nBadge === expectHits, { nBadge, expectHits });
  check('B6 未命中/数据不足行不灰显', nHit === 2 && (await page.locator('.sig-card .sig-item').count()) === nAll, { nHit, nAll });
  const hitKeys = injections.filter((x) => x.hit === true).map((x) => `${x.date}|${x.index_id}|${x.signal}`);
  const keptOnHit = await page.evaluate((keys) => [...document.querySelectorAll('.sig-card .signal-grid .sig-item')]
    .filter((e) => keys.includes([e.getAttribute('data-date'), e.getAttribute('data-idx'), e.getAttribute('data-sig')].join('|')))
    .filter((e) => e.querySelector('.sig-poscap-ok')).length, hitKeys);
  check('B13 命中行不占 AI建议位(与AI降亏同口径补位)', keptOnHit === 0, { keptOnHit });
  const tips = await page.locator('.sig-card .sig-ma3-badge').evaluateAll((els) => els.map((e) => e.getAttribute('data-tip') || ''));
  check('B7 角标说明含规则名', tips.length > 0 && tips.every((t) => t.includes('MA3连3日') && t.includes('3日均线')));
  check('B8 角标说明含回测逐位数字', tips.length > 0 && tips.every((t) => t.includes('93.9%') && t.includes('49.9%') && t.includes('88.4%') && t.includes('28.7%') && t.includes('47.27') && t.includes('38.12') && t.includes('97.7')));
  check('B9 角标说明含防前视/口径', tips.length > 0 && tips.every((t) => t.includes('防前视') && t.includes('K=1 每日池 1 万基准') && t.includes('不构成投资建议')));
  // 再点一次关掉 → 灰显/角标消失, 列表行数恢复
  await page.locator('.sig-switch-ma3-cb').uncheck();
  check('B10 关后灰显清除', (await page.locator('.sig-card .sig-ma3-hit').count()) === 0);
  check('B11 关后记忆写 0', (await page.evaluate(() => localStorage.getItem('tds_home_ma3'))) === '0');
  check('B12 关后行数恢复原样', (await cellCount()) === nAll, { now: await cellCount(), nAll });

  // C. 仅显示可用=开 + MA3=关 → 基线行数(此时已过滤掉非入样/AI降亏等行)
  await page.evaluate(() => { localStorage.setItem('tds_home_show_available_only', '1'); localStorage.setItem('tds_home_ma3', '0'); });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const nAvail0 = await cellCount();
  check('C1 仅显示可用开+MA3关: 基线已渲染', nAvail0 > 0 && nAvail0 < nAll, { nAvail0, nAll });
  // D. 同视图下开 MA3 → 注入的 2 条命中行被移除(与 AI 降亏同款联动)
  await page.evaluate(() => localStorage.setItem('tds_home_ma3', '1'));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const nAvail1 = await cellCount();
  const dbg = await page.evaluate((keys) => ({
    ls: { ma3: localStorage.getItem('tds_home_ma3'), avail: localStorage.getItem('tds_home_show_available_only') },
    cbChecked: (document.querySelector('.sig-switch-ma3-cb') || {}).checked,
    hitRowsPresent: [...document.querySelectorAll('.sig-card .signal-grid .sig-item')]
      .filter((e) => keys.includes([e.getAttribute('data-date'), e.getAttribute('data-idx'), e.getAttribute('data-sig')].join('|'))).length,
  }), hitKeys);
  console.log('[dbg D] ' + JSON.stringify(dbg));
  // 命中行被移除; 因同口径补位(不占 AI建议位), 行数可能持平(有替补)或减少(当日无替补), 但绝不增加
  check('D1 仅显示可用开+MA3开: 命中行被移除且不增加', dbg.hitRowsPresent === 0 && nAvail1 <= nAvail0, { nAvail1, nAvail0, hitRowsPresent: dbg.hitRowsPresent });
  check('D2 过滤视图无灰显行', (await page.locator('.sig-card .sig-ma3-hit').count()) === 0);
  check('D3 过滤视图无 MA3 角标', (await page.locator('.sig-card .sig-ma3-badge').count()) === 0);
  // E. 再关 MA3 → 行数恢复到基线
  await page.evaluate(() => localStorage.setItem('tds_home_ma3', '0'));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  check('E1 MA3关后仅显示可用视图行数恢复', (await cellCount()) === nAvail0, { now: await cellCount(), nAvail0 });

  // F. 公示文案可达: purpose-notes.home.ma3filter 已加载且含数字
  const note = await page.evaluate(() => (window.PURPOSE_NOTES || {})['home.ma3filter'] || '');
  check('F1 公示键 home.ma3filter 在位', note.includes('MA3连3日'));
  check('F2 公示含防前视/保守语义/主观声明', note.includes('防前视') && note.includes('保守') && note.includes('不构成投资建议'));
  check('F3 公示含回测逐位数字', ['93.9%', '49.9%', '88.4%', '28.7%', '47.27', '38.12', '97.7', 'K=1 每日池 1 万基准'].every((x) => note.includes(x)));
  check('F4 无页面 JS 报错', pageErrors.length === 0, pageErrors);
  await context.close();
} catch (e) {
  check('scenario completed', false, String(e));
} finally {
  await browser.close();
  await fsp.rm(TMP, { recursive: true, force: true });
  await fsp.rm(TMP_PROBE, { recursive: true, force: true });
  await saveEvidence(process.env.EVIDENCE_FILE, { results, failures, injections, scope: 'local source + injected _ma3 copy; NOT live deployment' });
}
console.log(results.map((r) => `${r.pass ? 'PASS' : 'FAIL'} ${r.name}${r.pass ? '' : ' ' + JSON.stringify(r.detail)}`).join('\n'));
console.log(`ma3 filter accept: ${results.filter((r) => r.pass).length} passed / ${failures} failed; injections=${injections.length}`);
process.exitCode = failures ? 1 : 0;
