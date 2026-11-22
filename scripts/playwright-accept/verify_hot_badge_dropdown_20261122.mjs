#!/usr/bin/env node
/**
 * verify_hot_badge_dropdown_20261122.js — 降亏模式下拉「双 HOT 角标 + 压缩折叠」验收(2026-11-22)
 *
 * 验收口径(任务书 /tmp/task-hot-badge-dropdown-20261122.md):
 *   ① A进攻王(a9)/B均衡卡(b9) 两档 HOT 角标可见/文案 HOT/hover 提示一句白话
 *   ② 折叠区默认收起、展开后 5 档全在、档总数 9 不变
 *   ③ 默认档 s06 选中行为不变(select.value/触发按钮文案)
 *   ④ 选中折叠区档(p8)刷新后选中态正确(触发按钮显示当前选中名, 重开面板折叠区自动展开并高亮)
 *   ⑤ 390px 不裁切(HOT 角标不被裁 + 面板不横向溢出)
 *   ⑥ 首页/监控卡同款结构(举一反三): 三处消费点同源 common.js 组件
 *
 * 用法:
 *   ln -sfn /Users/linhuichen/code/trade/static-site/data static-site/data   # worktree 只读数据软链
 *   python3 -m http.server 8000 -d static-site &
 *   cd scripts/playwright-accept && node verify_hot_badge_dropdown_20261122.js http://localhost:8000
 */
import { chromium } from 'playwright';
import { pickFadeMode } from './fade_mode_dd_helper.mjs';

const BASE = process.argv[2] || 'http://localhost:8000';
const MAIN_IDS = ['s06', 'a9', 'new14', 'b9'];
let pass = 0, fail = 0;
function ok(tag, cond, detail) {
  if (cond) pass++; else fail++;
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${tag}${detail ? '  (' + detail + ')' : ''}`);
}
function ddInfo(page, selId) {
  return page.evaluate((id) => {
    const sel = document.getElementById(id);
    if (!sel) return null;
    const w = sel.closest('.tds-fade-mode-dd');
    if (!w) return null;
    const panel = w.querySelector('.tds-fade-mode-panel');
    const more = w.querySelector('.tds-fade-mode-more');
    const opts = Array.prototype.map.call(w.querySelectorAll('[data-fade-mode-opt]'), (b) => ({
      id: b.getAttribute('data-fade-mode-opt'),
      main: !b.closest('.tds-fade-mode-extra'),
      active: b.classList.contains('is-active'),
      hot: !!b.querySelector('.hot-tier-badge'),
    }));
    const badges = Array.prototype.map.call(panel.querySelectorAll('.hot-tier-badge'), (b) => {
      const r = b.getBoundingClientRect();
      const row = b.closest('[data-fade-mode-opt]');
      return {
        row: row ? row.getAttribute('data-fade-mode-opt') : null,
        text: b.textContent.trim(),
        title: b.getAttribute('title') || '',
        w: Math.round(r.width), h: Math.round(r.height),
        flexShrink: getComputedStyle(b).flexShrink,
        inRow: row ? row.getBoundingClientRect().width >= r.right - row.getBoundingClientRect().left : false,
      };
    });
    return {
      value: sel.value,
      nativeOptions: sel.options.length,
      panelHidden: panel.hidden,
      moreOpen: more ? more.open : null,
      moreLabel: more ? (more.querySelector('summary').textContent || '').trim() : '',
      opts: opts,
      badges: badges,
      cur: (w.querySelector('.tds-fade-mode-cur') || {}).textContent || '',
      selW: Math.round(sel.getBoundingClientRect().width),
      btnW: Math.round(w.querySelector('.tds-fade-mode-ddb').getBoundingClientRect().width),
      ddTag: sel.tagName,
    };
  }, selId);
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
  const browser = await chromium.launch();

  // ───────────────── 桌面 1440px: lab 凯利区 ─────────────────
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 2400 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/Failed to load resource|net::ERR|Failed to fetch/i.test(m.text())) errors.push('console: ' + m.text()); });

  try {
    await page.goto(BASE + '/index.html#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#lab-kelly-fade-mode-sel', { timeout: 90000 });
    await page.waitForTimeout(1500);
    const before = await ddInfo(page, 'lab-kelly-fade-mode-sel');
    ok('①lab 下拉存在且原生 select 保留为值源(tag=SELECT)', before && before.ddTag === 'SELECT');
    ok('③lab 默认档 s06 选中不变', before && before.value === 's06', before ? `value=${before.value}` : '');
    ok('③lab 触发按钮显示当前选中档名(含 S06)', before && /S06/.test(before.cur), before ? before.cur.slice(0, 40) : '');
    ok('②lab 面板默认收起', before && before.panelHidden === true);
    ok('②lab 折叠区默认收起', before && before.moreOpen === false);
    ok('②lab 折叠头文案=更多模式(5 档·已收纳)', before && /更多模式\(5 档·已收纳\)/.test(before.moreLabel), before ? before.moreLabel : '');
    ok('②lab 档总数 9 不变(原生 select)', before && before.nativeOptions === 9, before ? `options=${before.nativeOptions}` : '');
    ok('②lab 主列表=4 档(s06/A进攻王/NEW14/B均衡卡)',
      before && before.opts.filter((o) => o.main).map((o) => o.id).join(',') === MAIN_IDS.join(','),
      before ? before.opts.filter((o) => o.main).map((o) => o.id).join(',') : '');
    ok('②lab 折叠区=5 档', before && before.opts.filter((o) => !o.main).length === 5, before ? String(before.opts.filter((o) => !o.main).length) : '');
    ok('②lab 可见层+隐藏层档总数 9', before && before.opts.length === 9, before ? String(before.opts.length) : '');
    ok('几何: 触发按钮宽==原生 select 宽(同行/宽度断言不受影响)', before && before.selW === before.btnW && before.selW === 200, before ? `sel=${before.selW} btn=${before.btnW}` : '');

    // 展开面板 → HOT 角标
    await openPanel(page, 'lab-kelly-fade-mode-sel');
    await page.waitForTimeout(200);
    const opened = await ddInfo(page, 'lab-kelly-fade-mode-sel');
    ok('面板点击后展开', opened && opened.panelHidden === false);
    ok('①HOT 角标恰好 2 个(A进攻王/B均衡卡)',
      opened && opened.badges.length === 2 && opened.badges.map((b) => b.row).sort().join(',') === 'a9,b9',
      opened ? opened.badges.map((b) => b.row + ':' + b.text).join(' | ') : '');
    ok('①HOT 文案=HOT', opened && opened.badges.every((b) => b.text === 'HOT'));
    ok('①HOT hover 提示含数据依据(一句白话)', opened && opened.badges.every((b) => b.title.length >= 8), opened ? opened.badges.map((b) => b.title.slice(0, 24)).join(' | ') : '');
    ok('①HOT 角标不收缩(flex:0 0 auto, 防 390px 裁切)', opened && opened.badges.every((b) => b.flexShrink === '0' && b.w > 0));
    ok('①HOT 角标完整落在选项行内(不裁切)', opened && opened.badges.every((b) => b.inRow));
    ok('②展开面板后折叠区仍默认收起(s06 不在折叠区)', opened && opened.moreOpen === false);

    // 展开折叠区 → 5 档可见
    await page.locator('.tds-fade-mode-dd').filter({ has: page.locator('#lab-kelly-fade-mode-sel') }).first().locator('.tds-fade-mode-more-sum').click();
    await page.waitForTimeout(150);
    const moreInfo = await page.evaluate(() => {
      const s = document.getElementById('lab-kelly-fade-mode-sel');
      const w = s.closest('.tds-fade-mode-dd');
      const vis = Array.prototype.filter.call(w.querySelectorAll('.tds-fade-mode-extra [data-fade-mode-opt]'), (b) => {
        const r = b.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      }).map((b) => b.getAttribute('data-fade-mode-opt'));
      return { open: w.querySelector('.tds-fade-mode-more').open, visible: vis };
    });
    ok('②折叠区展开后 5 档全可见', moreInfo.open && moreInfo.visible.length === 5, moreInfo.visible.join(','));
    ok('②折叠区 5 档=p8/p9/c9/new15/s06p1(不删档)', ['p8', 'p9', 'c9', 'new15', 's06p1'].every((id) => moreInfo.visible.indexOf(id) >= 0), moreInfo.visible.join(','));

    // Esc 只关面板
    await page.keyboard.press('Escape');
    await page.waitForTimeout(150);
    const afterEsc = await ddInfo(page, 'lab-kelly-fade-mode-sel');
    ok('Esc 关闭面板(不误触发切档)', afterEsc && afterEsc.panelHidden === true && afterEsc.value === 's06');

    // ④ 选折叠区档 p8 → 刷新后选中态正确
    await pickFadeMode(page, 'lab-kelly-fade-mode-sel', 'p8');
    await page.waitForTimeout(600);
    const p8State = await ddInfo(page, 'lab-kelly-fade-mode-sel');
    ok('④选 p8 成功(值源+记忆)', p8State && p8State.value === 'p8');
    ok('④触发按钮显示 p8 当前选中名(折叠不等于失效)', p8State && /8键/.test(p8State.cur), p8State ? p8State.cur : '');
    const mem = await page.evaluate(() => { try { return JSON.parse(localStorage.getItem('tds_kelly_fade_mode') || 'null'); } catch (e) { return null; } });
    ok('④p8 写入 lab 独立记忆 tds_kelly_fade_mode(TTL 格式)', !!(mem && mem.v && mem.v.mode === 'p8' && typeof mem.ts === 'number'), JSON.stringify(mem));

    // 重开面板: 折叠区自动展开 + p8 高亮
    await openPanel(page, 'lab-kelly-fade-mode-sel');
    await page.waitForTimeout(200);
    const reopened = await ddInfo(page, 'lab-kelly-fade-mode-sel');
    ok('④重开面板: 已选档在折叠区→折叠区自动展开', reopened && reopened.moreOpen === true);
    ok('④重开面板: p8 行高亮 is-active', reopened && reopened.opts.filter((o) => o.active).map((o) => o.id).join(',') === 'p8',
      reopened ? reopened.opts.filter((o) => o.active).map((o) => o.id).join(',') : '');
    await page.keyboard.press('Escape');

    // 刷新 → 选中态保持(TTL 内)
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForSelector('#lab-kelly-fade-mode-sel', { timeout: 90000 });
    await page.waitForTimeout(1500);
    const afterReload = await ddInfo(page, 'lab-kelly-fade-mode-sel');
    ok('④刷新后选中态正确(p8 仍在, 触发按钮文案=p8)', afterReload && afterReload.value === 'p8' && /8键/.test(afterReload.cur),
      afterReload ? `${afterReload.value}/${afterReload.cur}` : '');
    ok('④刷新后档总数/折叠结构不变', afterReload && afterReload.nativeOptions === 9 && afterReload.opts.length === 9 && afterReload.moreOpen === false);
  } catch (e) {
    fail++;
    console.log('FAIL  lab 用例异常  (' + String(e.message).slice(0, 200) + ')');
  }

  // ───────────────── 首页 + 监控卡同款结构(举一反三) ─────────────────
  try {
    const p2 = await ctx.newPage();
    p2.on('pageerror', (e) => errors.push('home pageerror: ' + e.message));
    await p2.goto(BASE + '/index.html', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await p2.waitForSelector('#sig-home-fade-mode-sel', { timeout: 90000 });
    await p2.waitForTimeout(1500);
    const home = await ddInfo(p2, 'sig-home-fade-mode-sel');
    ok('⑥首页下拉同款结构(默认 s06/9 档/主 4+折叠 5)',
      home && home.value === 's06' && home.nativeOptions === 9 && home.opts.filter((o) => o.main).length === 4 && home.opts.filter((o) => !o.main).length === 5,
      home ? `value=${home.value} options=${home.nativeOptions} main=${home.opts.filter((o) => o.main).length}` : '');
    await openPanel(p2, 'sig-home-fade-mode-sel');
    await p2.waitForTimeout(200);
    const homeOpen = await ddInfo(p2, 'sig-home-fade-mode-sel');
    ok('⑥首页 HOT 角标 2 个', homeOpen && homeOpen.badges.length === 2 && homeOpen.badges.map((b) => b.row).sort().join(',') === 'a9,b9',
      homeOpen ? homeOpen.badges.map((b) => b.row).join(',') : '');
    await pickFadeMode(p2, 'sig-home-fade-mode-sel', 'p8');
    await p2.waitForTimeout(600);
    const homeAfter = await ddInfo(p2, 'sig-home-fade-mode-sel');
    const homeMem = await p2.evaluate(() => { try { return JSON.parse(localStorage.getItem('tds_home_fade_mode') || 'null'); } catch (e) { return null; } });
    ok('⑥首页可正常选折叠区 p8(真实点击路径)', homeAfter && homeAfter.value === 'p8' && !!(homeMem && homeMem.v === 'p8'), homeAfter ? homeAfter.value : '');

    const ovPresent = await p2.$('#overfit-fade-mode-sel').then((x) => !!x);
    if (ovPresent) {
      const ov = await ddInfo(p2, 'overfit-fade-mode-sel');
      ok('⑥监控卡下拉同款结构(9 档/主 4+折叠 5)',
        ov && ov.nativeOptions === 9 && ov.opts.filter((o) => o.main).length === 4 && ov.opts.filter((o) => !o.main).length === 5,
        ov ? `options=${ov.nativeOptions}` : '');
      await openPanel(p2, 'overfit-fade-mode-sel');
      await p2.waitForTimeout(200);
      const ovOpen = await ddInfo(p2, 'overfit-fade-mode-sel');
      ok('⑥监控卡 HOT 角标 2 个', ovOpen && ovOpen.badges.length === 2, ovOpen ? String(ovOpen.badges.length) : '');
      await p2.keyboard.press('Escape');
    } else {
      fail++;
      console.log('FAIL  ⑥监控卡下拉未出现(#overfit-fade-mode-sel)');
    }
    await p2.close();
  } catch (e) {
    fail++;
    console.log('FAIL  首页/监控卡用例异常  (' + String(e.message).slice(0, 200) + ')');
  }

  // ───────────────── 390px 不裁切 ─────────────────
  try {
    const mctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const mp = await mctx.newPage();
    mp.on('pageerror', (e) => errors.push('mobile pageerror: ' + e.message));
    await mp.goto(BASE + '/index.html', { waitUntil: 'domcontentloaded', timeout: 60000 });
    await mp.waitForSelector('#sig-home-fade-mode-sel', { timeout: 90000 });
    await mp.waitForTimeout(1500);
    await openPanel(mp, 'sig-home-fade-mode-sel');
    await mp.waitForTimeout(250);
    const mob = await mp.evaluate(() => {
      const s = document.getElementById('sig-home-fade-mode-sel');
      const w = s.closest('.tds-fade-mode-dd');
      const panel = w.querySelector('.tds-fade-mode-panel');
      const pr = panel.getBoundingClientRect();
      const badges = Array.prototype.map.call(panel.querySelectorAll('.hot-tier-badge'), (b) => {
        const r = b.getBoundingClientRect();
        return { w: Math.round(r.width), h: Math.round(r.height), right: Math.round(r.right), left: Math.round(r.left), shrink: getComputedStyle(b).flexShrink };
      });
      return {
        docOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        panel: { left: Math.round(pr.left), right: Math.round(pr.right), w: Math.round(pr.width) },
        badges: badges,
        vw: window.innerWidth,
      };
    });
    ok('⑤390px 页面无横向溢出', mob.docOverflow <= 1, `overflow=${mob.docOverflow}px`);
    ok('⑤390px 面板不超出视口(左右各留 ≥7px)', mob.panel.left >= 7 && mob.panel.right <= mob.vw - 7,
      `panel=[${mob.panel.left},${mob.panel.right}] vw=${mob.vw}`);
    ok('⑤390px HOT 角标可见且不收缩', mob.badges.length === 2 && mob.badges.every((b) => b.w > 0 && b.h > 0 && b.shrink === '0' && b.right <= mob.vw),
      mob.badges.map((b) => `${b.w}x${b.h}`).join(','));
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
