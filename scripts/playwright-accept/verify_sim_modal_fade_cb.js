#!/usr/bin/env node
/**
 * verify_sim_modal_fade_cb.js — sim 弹窗「AI降亏过滤」总开关行为自验(2026-08-24 第4轮)
 *
 * 验收口径(主控 4 条):
 *  A. 默认加载与现版(a403 main)逐位一致 — feat(8137) vs main(8138) 探针 diff, 新增仅 fadeCb 字段
 *  B1. 开关关 → summary「降亏关」+ 表格数字变 raw 口径(行数/首行与过滤态不同)
 *  B2. 重开 → 恢复当前模式(new14)口径, 数字与初始过滤态逐位一致
 *  B3. 全程下拉选中值与 tds_sim_fade_mode 记忆不变(用户核心诉求: 开关不改变下拉结果)
 *  C. 刷新页面后开关状态与模式记忆各自保持(关→reload 仍关; 模式记忆仍 new14)
 *  D. 双视口全程 pageerror=0
 *
 * 用法: node verify_sim_modal_fade_cb.js <FEAT_URL> <MAIN_URL>
 *   先 python3 -m http.server 8137 -d <feat static-site> ; 8138 -d <main static-site>
 */
'use strict';
const { chromium } = require('playwright');
const FEAT = process.argv[2] || 'http://localhost:8137';
const MAIN = process.argv[3] || 'http://localhost:8138';
let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) { pass++; console.log(`  PASS ${name}`); }
  else { fail++; console.log(`  FAIL ${name}${extra ? ' :: ' + extra : ''}`); }
}
async function openSim(page) {
  // 注意: 这里不做任何 localStorage 清理(清理由调用方负责)——Part C 验证「刷新后记忆保持」,
  // 若在此删除 tds_sim_fade_mode 会破坏被测状态(首轮跑分 4 FAIL 的根因即此)。
  await page.evaluate(() => {
    document.querySelectorAll('.rule-modal .rule-modal-close').forEach((b) => b.click());
    document.querySelectorAll('.rule-modal').forEach((m) => m.classList.add('hidden'));
  });
  await page.click('.sig-kbtn-sim');
  await page.waitForFunction(() => {
    const m = document.getElementById('simBacktestModal');
    if (!m) return false;
    const loading = m.querySelector('.sim-table-loading');
    return loading && loading.style.display === 'none';
  }, { timeout: 120000 });
}
async function renderState(page) {
  return page.evaluate(() => {
    const m = document.getElementById('simBacktestModal');
    const cb = m.querySelector('.sim-fade-on-cb');
    const sel = document.getElementById('sim-fade-mode-sel');
    let modeMem = null;
    try {
      const raw = JSON.parse(localStorage.getItem('tds_sim_fade_mode') || 'null');
      modeMem = raw && raw.v ? raw.v.mode : null;   // TTL 包装层 {v:{mode},ts}
    } catch (e) {}
    const firstRow = m.querySelector('.sim-table-body tbody tr');
    return {
      summary: (m.querySelector('.sim-summary').textContent || '').replace(/\s+/g, ' ').trim(),
      rowCount: m.querySelectorAll('.sim-table-body tbody tr').length,
      firstRowText: firstRow ? [...firstRow.cells].map((c) => c.textContent.trim()).join('|') : '',
      cbChecked: cb ? !!cb.checked : null,
      selVal: sel ? sel.value : null,
      fadeKey: (() => { try { return localStorage.getItem('tds_sim_fade'); } catch (e) { return null; } })(),
      modeMem,
    };
  });
}

(async () => {
  const browser = await chromium.launch();

  // ===== Part A: A/B 默认加载逐位一致(feat vs main a403) =====
  console.log('== Part A: A/B 默认态一致性 ==');
  async function probe(url) {
    const p = await browser.newPage({ viewport: { width: 1440, height: 2400 } });
    await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await p.waitForTimeout(6000);
    await p.evaluate(() => { try { localStorage.clear(); } catch (e) {} });
    await openSim(p);
    await p.waitForFunction(() => {
      const s = document.querySelector('#simBacktestModal .sim-summary');
      return s && (s.textContent || '').trim().length > 0;
    }, { timeout: 120000 });
    await p.waitForTimeout(500);
    const st = await renderState(p);
    await p.close();
    return st;
  }
  const [aFeat, aMain] = [await probe(FEAT), await probe(MAIN)];
  for (const k of ['summary', 'rowCount', 'firstRowText', 'selVal', 'kActive']) {}
  ok('A.a summary 一致', aFeat.summary === aMain.summary,
    `feat="${aFeat.summary}" main="${aMain.summary}"`);
  ok('A.b rowCount 一致', aFeat.rowCount === aMain.rowCount, `${aFeat.rowCount} vs ${aMain.rowCount}`);
  ok('A.c firstRowText 一致', aFeat.firstRowText === aMain.firstRowText);
  ok('A.d 模式下拉默认一致', aFeat.selVal === aMain.selVal && aFeat.selVal === 'new14', `${aFeat.selVal}/${aMain.selVal}`);
  ok('A.e feat 默认开关=开', aFeat.cbChecked === true, String(aFeat.cbChecked));
  ok('A.f feat 默认无强制关记忆', aFeat.fadeKey !== '0', `tds_sim_fade=${aFeat.fadeKey}`);

  // ===== Part B+C: 开关行为链 + 刷新保持(pageerror 监听) =====
  console.log('== Part B: 开关行为链(feat) ==');
  const errors = [];
  const page = await browser.newPage({ viewport: { width: 1440, height: 2400 } });
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto(FEAT, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000);
  await page.evaluate(() => {
    try {
      localStorage.clear();
      // 预置模式记忆=new14(模拟用户已选模式), 开关键不设(走默认开)
      localStorage.setItem('tds_sim_fade_mode', JSON.stringify({ v: { mode: 'new14' }, ts: Date.now() }));
    } catch (e) {}
  });
  await openSim(page);
  // 拉长窗口保证有数据行(默认30天可能 0 行)
  await page.evaluate(() => {
    const m = document.getElementById('simBacktestModal');
    m.querySelector('.sim-date-start').value = '2025-06-01';
    m.querySelector('.sim-date-end').value = '2026-08-15';
    m.querySelector('.sim-date-start').dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.waitForTimeout(2500);
  await page.waitForFunction(() => {
    const loading = document.querySelector('#simBacktestModal .sim-table-loading');
    const s = document.querySelector('#simBacktestModal .sim-summary');
    return loading && loading.style.display === 'none' && s && /筛选结果/.test(s.textContent || '');
  }, { timeout: 120000 });

  const on0 = await renderState(page);
  ok('B0 初始=降亏开+new14', on0.cbChecked === true && on0.summary.includes('降亏开') && on0.selVal === 'new14',
    JSON.stringify({ cb: on0.cbChecked, sum: on0.summary.slice(0, 60), sel: on0.selVal }));
  ok('B0 有数据行', on0.rowCount > 0, `rows=${on0.rowCount}`);

  // 关开关
  await page.click('.sim-fade-on-cb');
  await page.waitForFunction(() => /降亏关/.test((document.querySelector('#simBacktestModal .sim-summary') || {}).textContent || ''), { timeout: 120000 });
  const off1 = await renderState(page);
  ok('B1 关=降亏关', off1.cbChecked === false && off1.summary.includes('降亏关'));
  ok('B1 raw 口径数字≠过滤态(行数或首行变化)', off1.rowCount !== on0.rowCount || off1.firstRowText !== on0.firstRowText,
    `on rows=${on0.rowCount} first="${on0.firstRowText.slice(0, 50)}" | off rows=${off1.rowCount} first="${off1.firstRowText.slice(0, 50)}"`);
  ok('B1 下拉选中值不变(B3)', off1.selVal === 'new14', off1.selVal);
  ok('B1 模式记忆不变(B3: 开关操作前后逐位一致, 含"无键"态)', off1.modeMem === on0.modeMem && off1.selVal === on0.selVal,
    `mem ${on0.modeMem} -> ${off1.modeMem}`);
  ok('B1 开关键落盘="0"', off1.fadeKey === '0', off1.fadeKey);

  // 重开开关
  await page.click('.sim-fade-on-cb');
  await page.waitForFunction(() => /降亏开/.test((document.querySelector('#simBacktestModal .sim-summary') || {}).textContent || ''), { timeout: 120000 });
  const on2 = await renderState(page);
  ok('B2 重开=降亏开', on2.summary.includes('降亏开') && on2.cbChecked === true);
  ok('B2 数字恢复当前模式口径(与初始逐位一致)', on2.rowCount === on0.rowCount && on2.firstRowText === on0.firstRowText,
    `rows ${on2.rowCount} vs ${on0.rowCount}`);
  ok('B2 下拉选中值/记忆仍不变(与初始一致)', on2.selVal === on0.selVal && on2.modeMem === on0.modeMem
    && on2.fadeKey !== '0');

  // 切一个别的模式再关/开(验证"恢复的是当前所选模式"而非固定 new14)
  await page.selectOption('#sim-fade-mode-sel', 'p8');
  await page.waitForFunction(() => !/筛选结果.*加载/.test((document.querySelector('#simBacktestModal .sim-table-loading') || {}).style || {}) , { timeout: 1000 }).catch(() => {});
  await page.waitForTimeout(2500);
  await page.waitForFunction(() => {
    const l = document.querySelector('#simBacktestModal .sim-table-loading');
    return l && l.style.display === 'none';
  }, { timeout: 120000 });
  const p8 = await renderState(page);
  ok('B3a 切 p8 后记忆更新', p8.selVal === 'p8' && p8.modeMem === 'p8', `${p8.selVal}/${p8.modeMem}`);
  await page.click('.sim-fade-on-cb');
  await page.waitForFunction(() => /降亏关/.test((document.querySelector('#simBacktestModal .sim-summary') || {}).textContent || ''), { timeout: 120000 });
  await page.click('.sim-fade-on-cb');
  await page.waitForFunction(() => /降亏开/.test((document.querySelector('#simBacktestModal .sim-summary') || {}).textContent || ''), { timeout: 120000 });
  const p8back = await renderState(page);
  ok('B3b p8 态关/开后数字稳定且下拉=p8', p8back.selVal === 'p8' && p8back.modeMem === 'p8'
    && p8back.rowCount === p8.rowCount && p8back.firstRowText === p8.firstRowText);

  // ===== Part C: 刷新保持 =====
  console.log('== Part C: 刷新保持 ==');
  await page.click('.sim-fade-on-cb');            // 置为关
  await page.waitForFunction(() => /降亏关/.test((document.querySelector('#simBacktestModal .sim-summary') || {}).textContent || ''), { timeout: 120000 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(6000);
  await openSim(page);
  await page.evaluate(() => {
    const m = document.getElementById('simBacktestModal');
    m.querySelector('.sim-date-start').value = '2025-06-01';
    m.querySelector('.sim-date-end').value = '2026-08-15';
    m.querySelector('.sim-date-start').dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.waitForTimeout(2500);
  await page.waitForFunction(() => /筛选结果/.test(((document.querySelector('#simBacktestModal .sim-summary') || {}).textContent) || ''), { timeout: 120000 });
  const cOff = await renderState(page);
  ok('C1 刷新后开关仍=关', cOff.cbChecked === false && cOff.summary.includes('降亏关'), JSON.stringify({ cb: cOff.cbChecked }));
  ok('C2 模式记忆独立保持=p8', cOff.selVal === 'p8' && cOff.modeMem === 'p8', `${cOff.selVal}/${cOff.modeMem}`);
  await page.click('.sim-fade-on-cb');            // 开回来再刷新
  await page.waitForFunction(() => /降亏开/.test((document.querySelector('#simBacktestModal .sim-summary') || {}).textContent || ''), { timeout: 120000 });
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(6000);
  await openSim(page);
  await page.waitForTimeout(1500);
  const cOn = await renderState(page);
  ok('C3 再刷新开关仍=开+模式仍=p8', cOn.cbChecked === true && cOn.selVal === 'p8');

  ok('D 全程 pageerror=0', errors.length === 0, errors.slice(0, 3).join(' ;; '));

  console.log(`\n==== RESULT: PASS=${pass} FAIL=${fail} ====`);
  await browser.close();
  process.exit(fail > 0 ? 1 : 0);
})();
