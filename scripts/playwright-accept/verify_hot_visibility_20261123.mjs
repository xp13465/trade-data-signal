#!/usr/bin/env node
/**
 * verify_hot_visibility_20261123.mjs — 降亏下拉 HOT/NEW 可见性 + 对比卡叫法/角标 + 旧 NEW 撤除验收(2026-11-23)
 *
 * 任务书 /tmp/task-hot-visibility-20261123.md 六项:
 *   ① 触发按钮选中 a9/b9 显示 HOT(复用 .hot-tier-badge), 选 s06/new14 不显示
 *   ② 触发按钮 NEW 角标可见, hover 文案=刚升级:更多模式已折叠收纳
 *   ③ 390px 触发按钮/角标不裁切、面板不横向溢出
 *   ④ 「AI 降亏组成对比」卡 A/B 卡头 HOT + 新叫法「A进攻王(on9)」「B均衡卡(on9)」
 *   ⑤ 旧 NEW 徽章零残留: lab.min.js/lab.min.css 与源 lab.js/lab.css 均无 lab-sigkelly-toggle-new 与 🆕
 *   ⑥ 老验收脚本 verify_hot_badge_dropdown_20261122.mjs 不红(由本任务单独跑, 结构断言不变)
 *
 * 用法:
 *   须先 build_min(或 merge 后)再跑: min 由 main-merge 统一构建。
 *   ln -sfn /Users/linhuichen/code/trade/static-site/data static-site/data   # worktree 只读数据软链
 *   python3 -m http.server 8000 -d static-site &
 *   cd scripts/playwright-accept && node verify_hot_visibility_20261123.mjs http://localhost:8000
 */
import { chromium } from 'playwright';
import { pickFadeMode } from './fade_mode_dd_helper.mjs';
import fs from 'node:fs';

const BASE = process.argv[2] || 'http://localhost:8000';
let pass = 0, fail = 0;
function ok(tag, cond, detail) {
  if (cond) pass++; else fail++;
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${tag}${detail ? '  (' + detail + ')' : ''}`);
}
function triggerInfo(page, selId) {
  return page.evaluate((id) => {
    const sel = document.getElementById(id);
    if (!sel) return null;
    const w = sel.closest('.tds-fade-mode-dd');
    const btn = w && w.querySelector('.tds-fade-mode-ddb');
    if (!btn) return null;
    const hot = btn.querySelector('.hot-tier-badge');
    const nw = btn.querySelector('.tds-fade-mode-new');
    const br = btn.getBoundingClientRect();
    const inBtn = (el) => {
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { w: Math.round(r.width), h: Math.round(r.height), left: Math.round(r.left), right: Math.round(r.right), shrink: getComputedStyle(el).flexShrink, inside: r.left >= br.left - 0.5 && r.right <= br.right + 0.5 };
    };
    return {
      value: sel.value,
      cur: (w.querySelector('.tds-fade-mode-cur') || {}).textContent || '',
      hot: hot ? { text: hot.textContent.trim(), title: hot.getAttribute('title') || '', ...inBtn(hot) } : null,
      newBadge: nw ? { text: nw.textContent.trim(), title: nw.getAttribute('title') || '', ...inBtn(nw) } : null,
      btn: { w: Math.round(br.width), h: Math.round(br.height), left: Math.round(br.left), right: Math.round(br.right), overflow: btn.scrollWidth - btn.clientWidth },
      vw: window.innerWidth,
    };
  }, selId);
}
async function dismissRuleModal(page) {
  await page.evaluate(() => {
    const kill = () => {
      const intro = document.querySelector('.onboarding-modal:not(.hidden)');
      if (intro) {
        const skip = intro.querySelector('.onboarding-skip');
        if (skip) skip.click();
        else intro.classList.add('hidden');
      }
      document.querySelectorAll('.rule-modal-overlay').forEach((o) => {
        if (o.getBoundingClientRect().width > 0) {
          const m = o.closest('.rule-modal');
          if (m) m.classList.add('hidden');
        }
      });
    };
    if (!window.__hvIntroObserver) {
      window.__hvIntroObserver = new MutationObserver(() => { if (document.querySelector('.onboarding-modal:not(.hidden)')) kill(); });
      window.__hvIntroObserver.observe(document.body, { childList: true, subtree: true });
    }
    document.querySelectorAll('.rule-modal .rule-modal-close').forEach((b) => b.click());
    kill();
  });
  await page.waitForTimeout(500);
}
async function openPanel(page, selId) {
  const wrap = page.locator('.tds-fade-mode-dd').filter({ has: page.locator('#' + selId) }).first();
  const hidden = await page.evaluate((id) => {
    const s = document.getElementById(id);
    const w = s && s.closest('.tds-fade-mode-dd');
    const p = w && w.querySelector('.tds-fade-mode-panel');
    return !!(p && p.hidden);
  }, selId);
  if (hidden) await wrap.locator('.tds-fade-mode-ddb').click();
  return wrap;
}

(async () => {
  // ── ⑤ 静态零残留(源 + 构建产物) ──
  try {
    const files = ['static-site/lab.js', 'static-site/lab.css', 'static-site/lab.min.js', 'static-site/lab.min.css'];
    for (const f of files) {
      const p = new URL('../../' + f, import.meta.url);
      const s = fs.readFileSync(p, 'utf8');
      ok(`⑤ ${f} 无旧 NEW 徽章类(lab-sigkelly-toggle-new)`, s.indexOf('lab-sigkelly-toggle-new') < 0, 'count=' + s.split('lab-sigkelly-toggle-new').length);
      ok(`⑤ ${f} 无 🆕 字符`, s.indexOf('🆕') < 0);
    }
  } catch (e) {
    fail++;
    console.log('FAIL  ⑤ 静态零残留读取异常  (' + String(e.message).slice(0, 160) + ')');
  }

  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 2400 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|net::ERR|Failed to fetch/i.test(m.text())) errors.push('console: ' + m.text()); });

  try {
    await page.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#lab-kelly-fade-mode-sel', { timeout: 90000 });
    await page.waitForTimeout(1500);
    await dismissRuleModal(page);

    // ① 默认 s06: 无 HOT, 有 NEW
    const s06 = await triggerInfo(page, 'lab-kelly-fade-mode-sel');
    ok('①默认 s06 触发按钮无 HOT 角标', s06 && s06.hot === null, s06 ? `value=${s06.value}` : '');
    ok('②s06 触发按钮有 NEW 角标', s06 && s06.newBadge && s06.newBadge.text === 'NEW', s06 && s06.newBadge ? s06.newBadge.text : '');
    ok('②NEW hover 文案=刚升级:更多模式已折叠收纳', s06 && s06.newBadge && /刚升级/.test(s06.newBadge.title) && /更多模式/.test(s06.newBadge.title) && /折叠/.test(s06.newBadge.title), s06 && s06.newBadge ? s06.newBadge.title : '');
    ok('②NEW 角标不收缩且完整落在触发按钮内', s06 && s06.newBadge && s06.newBadge.shrink === '0' && s06.newBadge.w > 0 && s06.newBadge.inside,
      s06 && s06.newBadge ? `w=${s06.newBadge.w} shrink=${s06.newBadge.shrink} inside=${s06.newBadge.inside}` : '');
    ok('②触发按钮无内容溢出(档名走省略号, 角标不被挤掉)', s06 && s06.btn.overflow <= 1, s06 ? `overflow=${s06.btn.overflow}` : '');

    // ① 选 a9 → HOT 出现
    await pickFadeMode(page, 'lab-kelly-fade-mode-sel', 'a9');
    await page.waitForTimeout(400);
    const a9 = await triggerInfo(page, 'lab-kelly-fade-mode-sel');
    ok('①选 a9 触发按钮显示 HOT', a9 && a9.value === 'a9' && a9.hot && a9.hot.text === 'HOT', a9 ? `value=${a9.value} hot=${a9.hot && a9.hot.text}` : '');
    ok('①a9 HOT hover 含数据依据(≥8字)', a9 && a9.hot && a9.hot.title.length >= 8, a9 && a9.hot ? a9.hot.title : '');
    ok('①a9 HOT+NEW 并排不挤(NEW 仍在且都在按钮内)', a9 && a9.hot && a9.newBadge && a9.hot.inside && a9.newBadge.inside && a9.newBadge.right <= a9.btn.right,
      a9 ? `hotRight=${a9.hot && a9.hot.right} newRight=${a9.newBadge && a9.newBadge.right} btnRight=${a9.btn.right}` : '');
    ok('①a9 触发按钮无内容溢出', a9 && a9.btn.overflow <= 1, a9 ? `overflow=${a9.btn.overflow}` : '');

    // ① 选 b9 → HOT 出现
    await pickFadeMode(page, 'lab-kelly-fade-mode-sel', 'b9');
    await page.waitForTimeout(400);
    const b9 = await triggerInfo(page, 'lab-kelly-fade-mode-sel');
    ok('①选 b9 触发按钮显示 HOT', b9 && b9.value === 'b9' && b9.hot && b9.hot.text === 'HOT', b9 ? `value=${b9.value} hot=${b9.hot && b9.hot.text}` : '');

    // ① 选 new14 → HOT 消失
    await pickFadeMode(page, 'lab-kelly-fade-mode-sel', 'new14');
    await page.waitForTimeout(400);
    const n14 = await triggerInfo(page, 'lab-kelly-fade-mode-sel');
    ok('①选 new14 触发按钮不显示 HOT', n14 && n14.value === 'new14' && n14.hot === null, n14 ? `value=${n14.value}` : '');

    // 回到默认 s06
    await pickFadeMode(page, 'lab-kelly-fade-mode-sel', 's06');
    await page.waitForTimeout(300);

    // ④ 对比卡: 叫法 + HOT
    const cmp = await page.evaluate(() => {
      const cards = Array.prototype.map.call(document.querySelectorAll('.lab-sigkelly-mode-card'), (c) => {
        const name = (c.querySelector('.lab-sigkelly-mode-card-name') || {}).textContent || '';
        const hot = c.querySelector('.lab-sigkelly-mode-card-head .hot-tier-badge');
        return { name: name.trim(), hot: hot ? { text: hot.textContent.trim(), title: hot.getAttribute('title') || '' } : null, headText: (c.querySelector('.lab-sigkelly-mode-card-head') || {}).textContent || '' };
      });
      return cards;
    });
    const cardA = cmp.find((c) => /A进攻王/.test(c.name));
    const cardB = cmp.find((c) => /B均衡卡/.test(c.name));
    ok('④对比卡 A 卡头叫法=A进攻王(on9)', !!cardA && cardA.name === 'A进攻王(on9)', cardA ? cardA.name : '');
    ok('④对比卡 B 卡头叫法=B均衡卡(on9)', !!cardB && cardB.name === 'B均衡卡(on9)', cardB ? cardB.name : '');
    ok('④对比卡 A 卡头 HOT 角标', !!cardA && cardA.hot && cardA.hot.text === 'HOT', cardA && cardA.hot ? cardA.hot.text : '');
    ok('④对比卡 B 卡头 HOT 角标', !!cardB && cardB.hot && cardB.hot.text === 'HOT', cardB && cardB.hot ? cardB.hot.text : '');
    ok('④对比卡 A HOT hover 含数据依据', !!cardA && cardA.hot && cardA.hot.title.length >= 8, cardA && cardA.hot ? cardA.hot.title : '');
    ok('④旧叫法「A on9 / B on9」在对比卡区零残留', !cmp.some((c) => /A on9|B on9/.test(c.headText)), cmp.map((c) => c.name).join(' | '));
    ok('④C 卡保持原叫法 C on9(本次只统一 A/B)', cmp.some((c) => c.name === 'C on9'), cmp.map((c) => c.name).join(' | '));
  } catch (e) {
    fail++;
    console.log('FAIL  lab 用例异常  (' + String(e.message).slice(0, 200) + ')');
  }
  await ctx.close();

  // ── ③ 390px 不裁切(首页同源组件) ──
  try {
    const mctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const mp = await mctx.newPage();
    mp.on('pageerror', (e) => errors.push('mobile pageerror: ' + e.message));
    await mp.goto(BASE + '/index.html', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await mp.waitForSelector('#sig-home-fade-mode-sel', { timeout: 90000 });
    await mp.waitForTimeout(1500);
    await dismissRuleModal(mp);
    const m06 = await triggerInfo(mp, 'sig-home-fade-mode-sel');
    ok('③390px s06 触发按钮 NEW 角标不裁切', m06 && m06.newBadge && m06.newBadge.w > 0 && m06.newBadge.inside && m06.newBadge.right <= m06.vw,
      m06 && m06.newBadge ? `w=${m06.newBadge.w} right=${m06.newBadge.right} vw=${m06.vw}` : '');
    await pickFadeMode(mp, 'sig-home-fade-mode-sel', 'a9');
    await mp.waitForTimeout(400);
    const mHot = await triggerInfo(mp, 'sig-home-fade-mode-sel');
    ok('③390px a9 触发按钮 HOT+NEW 均可见且不裁切', mHot && mHot.hot && mHot.newBadge && mHot.hot.inside && mHot.newBadge.inside && mHot.hot.right <= mHot.vw && mHot.newBadge.right <= mHot.vw,
      mHot ? `hotRight=${mHot.hot && mHot.hot.right} newRight=${mHot.newBadge && mHot.newBadge.right} vw=${mHot.vw}` : '');
    ok('③390px 触发按钮无内容溢出', mHot && mHot.btn.overflow <= 1, mHot ? `overflow=${mHot.btn.overflow}` : '');
    await openPanel(mp, 'sig-home-fade-mode-sel');
    await mp.waitForTimeout(250);
    const mob = await mp.evaluate(() => {
      const s = document.getElementById('sig-home-fade-mode-sel');
      const w = s.closest('.tds-fade-mode-dd');
      const panel = w.querySelector('.tds-fade-mode-panel');
      const pr = panel.getBoundingClientRect();
      return { docOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth, left: Math.round(pr.left), right: Math.round(pr.right), vw: window.innerWidth };
    });
    ok('③390px 页面无横向溢出', mob.docOverflow <= 1, `overflow=${mob.docOverflow}px`);
    ok('③390px 面板不超出视口(左右各留 ≥7px)', mob.left >= 7 && mob.right <= mob.vw - 7, `panel=[${mob.left},${mob.right}] vw=${mob.vw}`);
    await mp.keyboard.press('Escape');
    await mctx.close();
  } catch (e) {
    fail++;
    console.log('FAIL  390px 用例异常  (' + String(e.message).slice(0, 200) + ')');
  }

  ok('全程无 pageerror/console.error', errors.length === 0, errors.slice(0, 3).join(' | ').slice(0, 400));

  await browser.close();
  console.log(`\nSUMMARY: PASS=${pass} FAIL=${fail}`);
  process.exit(fail === 0 ? 0 : 1);
})();
