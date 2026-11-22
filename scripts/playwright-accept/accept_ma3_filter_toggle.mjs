#!/usr/bin/env node
// 2026-11-21 「MA3连3日」降亏筛选开关 · 首页验收(默认关不影响既有视图 + 开=灰显/标注 + post 口径 + 双开叠加 + 390px 移动端)。
//
// 运行(在 scripts/playwright-accept 下):
//   SOURCE_ROOT=<worktree根> DATA_ROOT=<源数据根(可选, 默认自动推断)> BASE_URL=<站点> node accept_ma3_filter_toggle.mjs
//
// 机制: 用 mobile_source_harness 把 .min.js/.min.css 回源到 SOURCE_ROOT 下的未压缩源文件
// (worktree 未做 build_min, 直接跑 .min 会验到旧产物); data 目录以「符号链接全集 + 注入副本」
// 临时重建, 只在 signals_today/overview 的副本里定向注入 _ma3 / ai_macro, 不改任何真实数据文件。
// 页面逻辑与后端打标的接口契约由此用例覆盖(后端判定另有 pytest 单测)。
//
// 返工要点(2026-11-21 P2-5/P2-6):
// - MA3 口径 = post(用户拍板②): 先按原规则选 AI建议 top-K, 再剔除命中, 命中**仍占原位置、不补位**。
//   B13 因此改为判别力断言: 命中行不显示任何仓位 badge(既非 AI建议也非当日已满), 同日被挤在
//   「当日已满」的兄弟行必须**仍是当日已满**(若被回填成 AI建议 = 实现退化成 pre, 直接红)。
// - 新增场景 G: 老数据(信号无 _ma3 字段)+ 开关开 → 不误灰、不误占位(行数/仓位 badge 与关时一致)。
// - 新增场景 H: AI降亏 + MA3 双开 → 仅AI命中/仅MA3命中/双命中 三行的 class 与原因角标各自正确。
// - 新增场景 I: 390px 视口 → 开关标签可见、命中角标在视口内且不溢出、长 tooltip 不横向溢出。
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
const DATA_FILES = ['signals_today.json', 'overview.json'];
const SIG_KEY = (s) => `${s.date}|${s.index_id}|${s.signal}`;
const KEY = (o) => `${o.date}|${o.idx}|${o.sig}`;

// --- 数据副本工厂: 符号链接全集 + 两个 JSON 真实副本(可独立注入, 互不污染) ---
// mobile_source_harness 的 read() 有模块级 cache(按文件路径缓存字节), 故每个用途一个独立目录:
// PROBE=探针基线(不注入) / MAIN=主用例注入 / OLD=老数据无 _ma3 / DUAL=双开注入。
async function mkDataDir(prefix) {
  const dir = await fsp.mkdtemp(path.join(os.tmpdir(), prefix));
  for (const name of await fsp.readdir(DATA_SRC)) {
    await fsp.symlink(path.join(DATA_SRC, name), path.join(dir, name));
  }
  for (const fn of DATA_FILES) {
    const src = path.join(DATA_SRC, fn);
    if (!fs.existsSync(src)) continue;
    await fsp.rm(path.join(dir, fn), { force: true });
    await fsp.copyFile(src, path.join(dir, fn));
  }
  return dir;
}
const TMP_PROBE = await mkDataDir('ma3-probe-');
const TMP = await mkDataDir('ma3-accept-');
const TMP_OLD = await mkDataDir('ma3-old-');
const TMP_DUAL = await mkDataDir('ma3-dual-');

// 对某目录下的 signals_today/overview 逐条买入信号执行 mutate(sig, fileName)。
async function mutateData(dir, mutate) {
  let touched = 0;
  for (const fn of DATA_FILES) {
    const p = path.join(dir, fn);
    if (!fs.existsSync(p)) continue;
    const obj = JSON.parse(await fsp.readFile(p, 'utf8'));
    const sigs = Array.isArray(obj) ? obj : (obj && Array.isArray(obj.signals_today) ? obj.signals_today : null);
    if (!sigs) { console.error(`[warn] ${fn} 未找到 signals_today 数组`); continue; }
    for (const s of sigs) {
      if (!s || !BUY.has(s.signal)) continue;
      if (mutate(s, fn)) touched++;
    }
    await fsp.writeFile(p, JSON.stringify(obj));
  }
  return touched;
}

const BASE = process.env.BASE_URL || 'https://ss.fx8.store';
const browser = await chromium.launch({ headless: true });
const results = []; let failures = 0;
const check = (name, pass, detail) => { results.push({ name, pass: !!pass, detail }); if (!pass) failures++; };

// DOM 行信息: 找 data-date/data-idx/data-sig 匹配的 .sig-item, 返回仓位/降亏/MA3 事实
async function rowsInfo(page, keys) {
  return page.evaluate((ks) => ks.map((k) => {
    const [d, i, s] = k.split('|');
    const el = [...document.querySelectorAll('.sig-card .signal-grid .sig-item')]
      .find((e) => e.getAttribute('data-date') === d && e.getAttribute('data-idx') === i && e.getAttribute('data-sig') === s);
    if (!el) return { k, found: false };
    return {
      k, found: true,
      date: d,
      ok: !!el.querySelector('.sig-poscap-ok'),
      full: !!el.querySelector('.sig-poscap-full'),
      poscapBadges: el.querySelectorAll('.sig-poscap-badge').length,
      ma3: el.classList.contains('sig-ma3-hit'),
      ai: el.classList.contains('sig-ai-hit'),
      ma3Badges: el.querySelectorAll('.sig-ma3-badge').length,
      aiBadges: el.querySelectorAll('.sig-ai-hit-badge').length,
      ma3Tip: el.querySelector('.sig-ma3-badge')?.getAttribute('data-tip') || '',
      aiTip: el.querySelector('.sig-ai-hit-badge')?.getAttribute('data-tip') || '',
    };
  }), keys);
}

try {
  // ===== 探针: 用未注入副本拿基线(DOM 里真实可见的买入行 + 每行的仓位 badge 事实) =====
  const probeCtx = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
  const probePage = await probeCtx.newPage();
  process.env.DATA_ROOT = TMP_PROBE;
  await installSources(probePage);
  await probePage.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await probePage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached', timeout: 60000 });
  await dismissIntro(probePage);
  await probePage.evaluate(() => {
    localStorage.setItem('tds_home_fade', '0');
    localStorage.setItem('tds_home_show_available_only', '0');
    localStorage.setItem('tds_home_ma3', '0');
    localStorage.setItem('tds_home_poscap', JSON.stringify({ on: true, k: 1 }));
  });
  await probePage.reload({ waitUntil: 'domcontentloaded' });
  await probePage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const visible = await probePage.evaluate(() => [...document.querySelectorAll('.sig-card .signal-grid .sig-item')]
    .map((e) => ({
      date: e.getAttribute('data-date'),
      idx: e.getAttribute('data-idx'),
      sig: e.getAttribute('data-sig'),
      ok: !!e.querySelector('.sig-poscap-ok'),
      full: !!e.querySelector('.sig-poscap-full'),
    }))
    .filter((x) => x.date && x.idx && ['buy', 'buy_aux', 'buy_special', 'buy_backup'].includes(x.sig)));
  await probeCtx.close();

  const byDate = {};
  for (const v of visible) (byDate[v.date] = byDate[v.date] || []).push(v);
  const okDates = Object.keys(byDate).filter((d) => byDate[d].some((x) => x.ok));
  const mixedDates = okDates.filter((d) => byDate[d].some((x) => x.full) && byDate[d].some((x) => x.ok));
  // 命中目标取两个不同日期的「AI建议(kept)」行: post 口径下它们仍占位, 便于 D1 用行数精确断言。
  // 第 1 条固定取「同日含 ok+full 的混合日」→ 保证 B13b 断言 sibling 与命中行同日(2026-11-22 P2-b 返工;
  // 原实现 sibling 取 mixedDates[0] 而命中行取 okDates[0], 两者可能不同日, 断言名不副实)。
  const mixedDate = mixedDates[0] || null;
  const hitTargets = [];
  if (mixedDate) hitTargets.push(byDate[mixedDate].find((x) => x.ok));
  for (const d of okDates) {
    if (d === mixedDate) continue;
    hitTargets.push(byDate[d].find((x) => x.ok));
    if (hitTargets.length === 2) break;
  }
  const sibling = mixedDate ? byDate[mixedDate].find((x) => x.full) : null;
  const others = visible.filter((v) => !hitTargets.some((h) => KEY(h) === KEY(v)) && (!sibling || KEY(sibling) !== KEY(v)));
  if (hitTargets.length !== 2 || !mixedDate || !sibling || others.length < 2) {
    console.error('探针失败: 基线可见买入行不足/无同日 kept+full 组合 visible=' + JSON.stringify(visible.slice(0, 20)));
    process.exit(2);
  }
  const hitKeys = hitTargets.map(KEY);
  const siblingKey = KEY(sibling);
  const planByKey = {
    [hitKeys[0]]: { hit: true, status: 'ok', reason: null },
    [hitKeys[1]]: { hit: true, status: 'ok', reason: null },
    [KEY(others[0])]: { hit: false, status: 'ok', reason: null },
    [KEY(others[1])]: { hit: null, status: 'na', reason: 'short_history' },
  };
  let hitInjectedKeys = new Set();
  const touched = await mutateData(TMP, (s) => {
    const plan = planByKey[SIG_KEY(s)];
    if (!plan) return false;
    const code = (s.etfs || []).find((e) => e && e.code);
    const etf = code ? code.code : null;
    s._ma3 = { ...plan, etf, ma3: plan.status === 'ok' ? 1.2345 : null, close: plan.status === 'ok' ? 1.1111 : null };
    if (plan.hit === true) hitInjectedKeys.add(SIG_KEY(s));
    return true;
  });
  if (hitInjectedKeys.size !== 2) {
    console.error('注入失败: 期望 2 条命中, 实际 ' + hitInjectedKeys.size + ' touched=' + touched + ' keys=' + JSON.stringify(planByKey));
    process.exit(2);
  }
  console.log('[prep] 命中注入 = ' + JSON.stringify(hitKeys) + ' 同日兄弟=' + siblingKey + ' 注入副本数=' + touched);

  // ===== A. 默认态(零本机记忆): 开关在位且未勾, 无任何 MA3 标记 =====
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
  const page = await context.newPage();
  const pageErrors = []; page.on('pageerror', (e) => pageErrors.push(String(e)));
  process.env.DATA_ROOT = TMP;
  const cellCount = () => page.locator('.sig-card .signal-grid .sig-item').count();
  await installSources(page);
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached', timeout: 60000 });
  await dismissIntro(page);
  check('A1 开关默认未勾', !(await page.locator('.sig-switch-ma3-cb').isChecked()));
  check('A2 默认态无灰显行', (await page.locator('.sig-card .sig-ma3-hit').count()) === 0);
  check('A3 默认态无 MA3 角标', (await page.locator('.sig-card .sig-ma3-badge').count()) === 0);
  check('A4 默认态未写本机记忆', (await page.evaluate(() => localStorage.getItem('tds_home_ma3'))) === null);
  // A5(2026-11-22 新增): MA3 开关旁的 NEW 角标可见、文案=NEW、带 hover 说明, 且不改变开关默认态。
  const newBadge = await page.evaluate(() => {
    const b = document.querySelector('.sig-switch-lab.sig-switch-ma3 .hot-new-badge');
    if (!b) return null;
    const r = b.getBoundingClientRect();
    return { text: (b.textContent || '').trim(), title: b.getAttribute('title') || '', w: r.width, h: r.height };
  });
  check('A5 NEW角标在MA3开关旁可见且文案=NEW',
    !!newBadge && newBadge.text === 'NEW' && newBadge.w > 0 && newBadge.h > 0 && newBadge.title.includes('最新上线'), newBadge);

  // ===== B. 全量列表(AI降亏关 / 仅显示可用关 / 仓位建议默认 K=1): 勾选后逐项断言 =====
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
  check('B4 灰显行数 == 注入命中数', nHit === 2, { nHit });
  check('B5 角标数 == 注入命中数', nBadge === 2, { nBadge });
  check('B6 未命中/数据不足行不灰显且总行数不变', (await page.locator('.sig-card .sig-item').count()) === nAll, { nAll });

  // B13(判别力, post 口径): 命中行仍占原 AI建议位 → 它本身不显示任何仓位 badge(既非 AI建议也非当日已满);
  // 同日被挤在「当日已满」的兄弟行必须仍是当日已满 —— 若实现回填, 兄弟会变 AI建议, 本条即红。
  const b13 = await rowsInfo(page, [hitKeys[0], siblingKey]);
  const hitRow = b13[0] || {};
  const sibRow = b13[1] || {};
  check('B13 命中行不显示仓位badge且不占AI建议标注(命中=被过滤)',
    hitRow.found && hitRow.ma3 && !hitRow.ok && !hitRow.full && hitRow.poscapBadges === 0,
    hitRow);
  check('B13b 同日兄弟行仍是「当日已满」(命中占位不补位, post 口径)',
    sibRow.found && sibRow.full === true && sibRow.ok === false && sibRow.date === hitRow.date,
    sibRow);
  const tips = await page.locator('.sig-card .sig-ma3-badge').evaluateAll((els) => els.map((e) => e.getAttribute('data-tip') || ''));
  check('B7 角标说明含规则名', tips.length === 2 && tips.every((t) => t.includes('MA3连3日') && t.includes('3日均线')));
  check('B8 角标说明含回测逐位数字', tips.length === 2 && tips.every((t) => t.includes('93.9%') && t.includes('49.9%') && t.includes('88.4%') && t.includes('28.7%') && t.includes('47.27') && t.includes('38.12') && t.includes('97.7')));
  check('B9 角标说明含防前视/口径且无字面HTML', tips.length === 2 && tips.every((t) => t.includes('防前视') && t.includes('K=1 每日池 1 万基准') && t.includes('不构成投资建议') && !t.includes('<b>') && !t.includes('&lt;b')));
  check('B14 角标说明含 post 占位语义', tips.length === 2 && tips.every((t) => t.includes('post') && t.includes('不补位')));
  // 再点一次关掉 → 灰显/角标消失, 列表行数恢复
  await page.locator('.sig-switch-ma3-cb').uncheck();
  check('B10 关后灰显清除', (await page.locator('.sig-card .sig-ma3-hit').count()) === 0);
  check('B11 关后记忆写 0', (await page.evaluate(() => localStorage.getItem('tds_home_ma3'))) === '0');
  check('B12 关后行数恢复原样', (await cellCount()) === nAll, { now: await cellCount(), nAll });

  // ===== C/D/E. 仅显示可用=开: post 口径下命中行被隐藏且不补位(可见行数精确 -命中数) =====
  await page.evaluate(() => { localStorage.setItem('tds_home_show_available_only', '1'); localStorage.setItem('tds_home_ma3', '0'); });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const nAvail0 = await cellCount();
  check('C1 仅显示可用开+MA3关: 基线已渲染', nAvail0 > 0 && nAvail0 < nAll, { nAvail0, nAll });
  await page.evaluate(() => localStorage.setItem('tds_home_ma3', '1'));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const nAvail1 = await cellCount();
  const dRows = await rowsInfo(page, hitKeys);
  const hitRowsPresent = dRows.filter((r) => r.found).length;
  const dbgD = await page.evaluate(() => ({
    ls: { ma3: localStorage.getItem('tds_home_ma3'), avail: localStorage.getItem('tds_home_show_available_only') },
    cbChecked: (document.querySelector('.sig-switch-ma3-cb') || {}).checked,
  }));
  console.log('[dbg D] ' + JSON.stringify({ ...dbgD, nAvail1, nAvail0, hitRowsPresent }));
  check('D1 仅显示可用开+MA3开: 命中行被移除', hitRowsPresent === 0, { hitRowsPresent });
  check('D1b 可见行数 == 基线 - 命中数(命中不补位, post 口径)', nAvail1 === nAvail0 - 2, { nAvail1, nAvail0 });
  check('D2 过滤视图无灰显行', (await page.locator('.sig-card .sig-ma3-hit').count()) === 0);
  check('D3 过滤视图无 MA3 角标', (await page.locator('.sig-card .sig-ma3-badge').count()) === 0);
  await page.evaluate(() => localStorage.setItem('tds_home_ma3', '0'));
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  check('E1 MA3关后仅显示可用视图行数恢复', (await cellCount()) === nAvail0, { now: await cellCount(), nAvail0 });

  // ===== F. 公示文案可达 + 口径完整 =====
  const note = await page.evaluate(() => (window.PURPOSE_NOTES || {})['home.ma3filter'] || '');
  check('F1 公示键 home.ma3filter 在位', note.includes('MA3连3日'));
  check('F2 公示含防前视/保守语义/主观声明', note.includes('防前视') && note.includes('保守') && note.includes('不构成投资建议'));
  check('F3 公示含回测逐位数字', ['93.9%', '49.9%', '88.4%', '28.7%', '47.27', '38.12', '97.7', 'K=1 每日池 1 万基准'].every((x) => note.includes(x)));
  check('F4 公示含 post 占位语义(命中=该日建议位置空缺不给替补)', note.includes('post 口径') && note.includes('不给替补') && note.includes('不会顺延补位'));
  check('F5 公示含年份依赖(49.9%主要来自2026/99笔/7笔未平仓/28.7%靠2018)', note.includes('主要来自 2026 年') && note.includes('99 笔') && note.includes('7 笔未平仓') && note.includes('2018 年那段真金白银的改善'));
  check('F6 无页面 JS 报错', pageErrors.length === 0, pageErrors);
  // F7-F9(2026-11-22 P3 并入): 真点 ⓘ → 完整公示弹窗可见且含完整公示文本 → 不误切开关 → 可关闭。
  await page.locator('.sig-switch-ma3 .sig-switch-tip[data-ma3-note]').click();
  const modalVisible = (await page.locator('#ma3FilterNoteModal:not(.hidden)').count()) === 1;
  const modalText = modalVisible ? await page.locator('#ma3FilterNoteModal .rule-modal-content').innerText() : '';
  check('F7 ⓘ点击弹出完整公示弹窗且含完整公示文本',
    modalVisible && modalText.includes('MA3连3日') && modalText.includes('不给替补')
      && modalText.includes('不构成投资建议') && modalText.includes('49.9%')
      && !modalText.includes('**'),
    { modalVisible, len: modalText.length, hasLiteralMarkdown: modalText.includes('**') });
  check('F7b 公示加粗走 <b> 标签渲染(无字面 Markdown)',
    modalVisible && (await page.locator('#ma3FilterNoteModal .rule-modal-content').innerHTML()).includes('<b>仍然占着'));
  check('F8 点击ⓘ不误切MA3开关', !(await page.locator('.sig-switch-ma3-cb').isChecked()));
  await page.locator('#ma3FilterNoteModal .rule-modal-close').click();
  check('F9 弹窗可关闭', (await page.locator('#ma3FilterNoteModal.hidden').count()) === 1);
  check('F6b 点击/关闭弹窗后仍无页面 JS 报错', pageErrors.length === 0, pageErrors);
  await context.close();

  // ===== G. 老数据无 _ma3 字段 + 开关开 → 不误灰、不误占位 =====
  // G0 前置: 断言待测副本确实是「老数据」(买入信号无语义 _ma3 字段), 否则场景不成立/结论不可信。
  let oldMa3Count = 0;
  for (const fn of DATA_FILES) {
    const p = path.join(TMP_OLD, fn);
    if (!fs.existsSync(p)) continue;
    const obj = JSON.parse(await fsp.readFile(p, 'utf8'));
    const sigs = Array.isArray(obj) ? obj : (obj.signals_today || []);
    for (const s of sigs) if (s && BUY.has(s.signal) && s._ma3) oldMa3Count++;
  }
  check('G0 老数据副本确无 _ma3 字段(场景前置)', oldMa3Count === 0, { oldMa3Count });
  const gctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
  const gpage = await gctx.newPage();
  const gErrors = []; gpage.on('pageerror', (e) => gErrors.push(String(e)));
  process.env.DATA_ROOT = TMP_OLD;
  await installSources(gpage);
  await gpage.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await gpage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached', timeout: 60000 });
  await dismissIntro(gpage);
  await gpage.evaluate(() => {
    localStorage.setItem('tds_home_fade', '0');
    localStorage.setItem('tds_home_show_available_only', '0');
    localStorage.setItem('tds_home_ma3', '0');
    localStorage.setItem('tds_home_poscap', JSON.stringify({ on: true, k: 1 }));
  });
  await gpage.reload({ waitUntil: 'domcontentloaded' });
  await gpage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const gBase = await gpage.evaluate(() => ({
    rows: document.querySelectorAll('.sig-card .signal-grid .sig-item').length,
    ok: document.querySelectorAll('.sig-poscap-ok').length,
    full: document.querySelectorAll('.sig-poscap-full').length,
  }));
  await gpage.evaluate(() => localStorage.setItem('tds_home_ma3', '1'));
  await gpage.reload({ waitUntil: 'domcontentloaded' });
  await gpage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const gOn = await gpage.evaluate(() => ({
    rows: document.querySelectorAll('.sig-card .signal-grid .sig-item').length,
    ok: document.querySelectorAll('.sig-poscap-ok').length,
    full: document.querySelectorAll('.sig-poscap-full').length,
    hit: document.querySelectorAll('.sig-ma3-hit').length,
    badge: document.querySelectorAll('.sig-ma3-badge').length,
  }));
  check('G1 老数据无_ma3 开关开不误灰不误标', gOn.hit === 0 && gOn.badge === 0, { gOn });
  check('G2 老数据无_ma3 行数/仓位badge不误占位', gOn.rows === gBase.rows && gOn.ok === gBase.ok && gOn.full === gBase.full, { gBase, gOn });
  check('G3 老数据场景无 JS 报错', gErrors.length === 0, gErrors);
  await gctx.close();

  // ===== H. AI降亏 + MA3 双开: 仅AI命中 / 仅MA3命中 / 双命中 三行各自正确 =====
  const dualRows = visible.filter((v) => !hitTargets.some((h) => KEY(h) === KEY(v))).slice(0, 3);
  if (dualRows.length < 3) {
    check('H0 双开场景数据准备', false, { visible: visible.length });
  } else {
    const dualKeys = dualRows.map(KEY);
    const dualTouched = new Set();
    await mutateData(TMP_DUAL, (s) => {
      const k = SIG_KEY(s);
      const idx = dualKeys.indexOf(k);
      if (idx < 0) return false;
      const code = (s.etfs || []).find((e) => e && e.code);
      const etf = code ? code.code : null;
      const aiHit = idx === 0 || idx === 2;
      const ma3Hit = idx === 1 || idx === 2;
      s.ai_macro = { ...(s.ai_macro || {}), hit: aiHit, filters: aiHit ? ['greedy15'] : [] };
      s._ma3 = ma3Hit
        ? { hit: true, status: 'ok', reason: null, etf, ma3: 1.2345, close: 1.1111 }
        : { hit: false, status: 'ok', reason: null, etf, ma3: 1.2345, close: 1.1111 };
      dualTouched.add(k);
      return true;
    });
    if (dualTouched.size < 3) {
      check('H0 双开场景注入', false, { dualTouched: dualTouched.size, dualKeys });
    } else {
      const hctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
      const hpage = await hctx.newPage();
      const hErrors = []; hpage.on('pageerror', (e) => hErrors.push(String(e)));
      process.env.DATA_ROOT = TMP_DUAL;
      await installSources(hpage);
      await hpage.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
      await hpage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached', timeout: 60000 });
      await dismissIntro(hpage);
      await hpage.evaluate(() => {
        localStorage.setItem('tds_home_fade', '1');
        localStorage.setItem('tds_home_fade_mode', 'p8');
        localStorage.setItem('tds_home_show_available_only', '0');
        localStorage.setItem('tds_home_ma3', '1');
      });
      await hpage.reload({ waitUntil: 'domcontentloaded' });
      await hpage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
      const h = await rowsInfo(hpage, dualKeys);
      const [hAi, hMa3, hBoth] = h;
      check('H1 仅AI命中行: 有AI降亏角标/无MA3标记',
        hAi.found && hAi.ai === true && hAi.ma3 === false && hAi.aiBadges === 1 && hAi.ma3Badges === 0 && hAi.aiTip.includes('删除线原因'),
        hAi);
      check('H2 仅MA3命中行: 有MA3角标/无AI降亏标记',
        hMa3.found && hMa3.ma3 === true && hMa3.ai === false && hMa3.ma3Badges === 1 && hMa3.aiBadges === 0 && hMa3.ma3Tip.includes('MA3连3日') && hMa3.ma3Tip.includes('post'),
        hMa3);
      check('H3 双命中行: 两种class与两种角标同时出现',
        hBoth.found && hBoth.ai === true && hBoth.ma3 === true && hBoth.aiBadges === 1 && hBoth.ma3Badges === 1,
        hBoth);
      check('H4 双开场景无 JS 报错', hErrors.length === 0, hErrors);
      await hctx.close();
    }
  }

  // ===== I. 390px 移动端: 标签可见 / 角标不遮挡不溢出 / 长 tooltip 不横向溢出 =====
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, serviceWorkers: 'block' });
  const mpage = await mctx.newPage();
  const mErrors = []; mpage.on('pageerror', (e) => mErrors.push(String(e)));
  process.env.DATA_ROOT = TMP;
  await installSources(mpage);
  await mpage.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await mpage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached', timeout: 60000 });
  await dismissIntro(mpage);
  await mpage.evaluate(() => {
    localStorage.setItem('tds_home_fade', '0');
    localStorage.setItem('tds_home_show_available_only', '0');
    localStorage.setItem('tds_home_ma3', '1');
    localStorage.setItem('tds_home_poscap', JSON.stringify({ on: true, k: 1 }));
  });
  await mpage.reload({ waitUntil: 'domcontentloaded' });
  await mpage.locator('.sig-switch-ma3-cb').waitFor({ state: 'attached' });
  const mInfo = await mpage.evaluate(() => {
    const lab = document.querySelector('.sig-switch-lab.sig-switch-ma3');
    const lb = lab ? lab.getBoundingClientRect() : null;
    const badge = document.querySelector('.sig-card .sig-ma3-badge');
    const bb = badge ? badge.getBoundingClientRect() : null;
    const item = badge ? badge.closest('.sig-item') : null;
    const ib = item ? item.getBoundingClientRect() : null;
    const nb = lab ? lab.querySelector('.hot-new-badge') : null;
    const nbb = nb ? nb.getBoundingClientRect() : null;
    return {
      lab: lb ? { l: lb.left, r: lb.right, w: lb.width, h: lb.height } : null,
      newBadge: nbb ? { l: nbb.left, r: nbb.right, w: nbb.width, h: nbb.height } : null,
      badge: bb ? { l: bb.left, r: bb.right, t: bb.top, b: bb.bottom, w: bb.width, h: bb.height } : null,
      item: ib ? { l: ib.left, r: ib.right, t: ib.top, b: ib.bottom } : null,
      docScrollW: document.documentElement.scrollWidth,
      viewportW: window.innerWidth,
    };
  });
  check('I1 390px 开关标签可见', !!mInfo.lab && mInfo.lab.w > 0 && mInfo.lab.h > 0 && mInfo.lab.l >= 0 && mInfo.lab.r <= 390, mInfo.lab);
  check('I2 390px 命中角标可见且在视口内',
    !!mInfo.badge && mInfo.badge.w > 0 && mInfo.badge.h > 0 && mInfo.badge.l >= 0 && mInfo.badge.r <= 390, mInfo.badge);
  // sup 角标按 vertical-align:super 上浮, 顶部略高于行盒属正常排版; 事实层判据=水平不出格 + 底部不出行盒。
  check('I3 390px 角标在信号行内不遮挡出界',
    !!mInfo.badge && !!mInfo.item
      && mInfo.badge.l >= mInfo.item.l - 1 && mInfo.badge.r <= mInfo.item.r + 1
      && mInfo.badge.b <= mInfo.item.b + 1, { badge: mInfo.badge, item: mInfo.item });
  if (mInfo.badge) {
    const badge = mpage.locator('.sig-card .sig-ma3-badge').first();
    await badge.scrollIntoViewIfNeeded();
    await badge.hover();
    await mpage.locator('.term-pop').waitFor({ state: 'visible', timeout: 5000 }).catch(() => {});
    const tip = await mpage.evaluate(() => {
      const pop = document.querySelector('.term-pop');
      if (!pop || pop.style.display === 'none') return { shown: false };
      const r = pop.getBoundingClientRect();
      const cs = getComputedStyle(pop);
      return {
        shown: true, l: r.left, r: r.right, w: r.width, h: r.height,
        scrollW: pop.scrollWidth, clientW: pop.clientWidth,
        overflowX: cs.overflowX, overflowY: cs.overflowY,
        textLen: (pop.textContent || '').length,
      };
    });
    check('I4 390px 长tooltip 可弹出且不横向溢出',
      tip.shown && tip.w > 0 && tip.l >= -1 && tip.r <= 391 && tip.scrollW <= tip.clientW + 1 && tip.textLen > 100,
      tip);
  } else {
    check('I4 390px 长tooltip 可弹出且不横向溢出', false, { reason: '无角标可 hover' });
  }
  // I6(2026-11-22 新增): NEW 角标 390px 可见、在视口内、不被裁切/不撑出横向滚动。
  check('I6 390px NEW角标可见且在视口内不裁切',
    !!mInfo.newBadge && mInfo.newBadge.w > 0 && mInfo.newBadge.h > 0
      && mInfo.newBadge.l >= 0 && mInfo.newBadge.r <= 390
      && mInfo.docScrollW <= mInfo.viewportW + 1,
    { newBadge: mInfo.newBadge, scrollW: mInfo.docScrollW, vw: mInfo.viewportW });
  check('I5 390px 场景无 JS 报错', mErrors.length === 0, mErrors);
  await mctx.close();

  // ===== J. 凯利区 lab.sigkelly 公示: 无字面 ** + 加粗走 <b> 渲染(2026-11-22) =====
  const jctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: 'block' });
  const jpage = await jctx.newPage();
  const jErrors = []; jpage.on('pageerror', (e) => jErrors.push(String(e)));
  process.env.DATA_ROOT = TMP;
  await installSources(jpage);
  await jpage.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await jpage.locator('.lab-sigkelly-wrap .purpose-note').waitFor({ state: 'attached', timeout: 60000 });
  const labNote = await jpage.evaluate(() => {
    const el = document.querySelector('.lab-sigkelly-wrap .purpose-note');
    if (!el) return null;
    return {
      text: el.textContent || '',
      html: el.innerHTML,
      boldCount: el.querySelectorAll('b').length,
    };
  });
  check('J1 凯利区公示无字面 Markdown 星号',
    !!labNote && labNote.text.length > 500 && !labNote.text.includes('**') && !labNote.html.includes('**'),
    labNote && { len: labNote.text.length });
  check('J2 凯利区公示原星号内容改走 <b> 渲染',
    !!labNote && labNote.boldCount >= 6
      && labNote.html.includes('<b>未定价标的') && labNote.html.includes('<b>不计入本轮买价基准</b>')
      && labNote.html.includes('<b>甲档</b>') && labNote.html.includes('<b>乙档</b>'),
    labNote && { boldCount: labNote.boldCount });
  check('J3 凯利区场景无 JS 报错', jErrors.length === 0, jErrors);
  await jctx.close();
} catch (e) {
  check('scenario completed', false, String(e));
} finally {
  await browser.close();
  for (const d of [TMP, TMP_PROBE, TMP_OLD, TMP_DUAL]) {
    await fsp.rm(d, { recursive: true, force: true });
  }
  await saveEvidence(process.env.EVIDENCE_FILE, { results, failures });
}
console.log(results.map((r) => `${r.pass ? 'PASS' : 'FAIL'} ${r.name}${r.pass ? '' : ' ' + JSON.stringify(r.detail)}`).join('\n'));
console.log(`ma3 filter accept: ${results.filter((r) => r.pass).length} passed / ${failures} failed`);
process.exitCode = failures ? 1 : 0;
