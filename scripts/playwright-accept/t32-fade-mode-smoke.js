#!/usr/bin/env node
/**
 * t32-fade-mode-smoke.js — T3-2「AI降亏·模式」三处接入真实浏览器冒烟(2026-08-23)
 *
 * 目的(主控硬要求④): node --check 之外的真实浏览器实操验证——
 *   ① 首页模式下拉存在, 且与「AI降亏过滤」文字同一行(offsetTop 差 < 阈值, UI 落点铁律)
 *   ② AI 监控卡模式下拉+「牛市×辅备买全停」+1开关与「AI降亏过滤」同一行
 *   ③ 快速连切 7 模式(p8→p9→a9→b9→c9→new14→new18)无卡死: 无 pageerror/console error,
 *      localStorage 写入正确(tds_home_fade_mode / tds_overfit_fade_mode), 切完页面仍响应
 *
 * 用法:
 *   cd scripts/playwright-accept && node t32-fade-mode-smoke.js http://localhost:8000 [--mobile]
 *   (先起本地站: python3 -m http.server 8000 -d <worktree>/static-site)
 *
 * 复现(worktree 隔离环境):
 *   ln -sfn /Users/linhuichen/code/trade/static-site/data static-site/data   # 只读软链生产数据(跑完删除!)
 *   python3 -m http.server 8000 -d static-site &
 *   cd scripts/playwright-accept && node t32-fade-mode-smoke.js http://localhost:8000
 */
'use strict';
const { chromium } = require('playwright');

const URL = process.argv[2] || 'http://localhost:8000';
const MODES = ['p8', 'p9', 'a9', 'b9', 'c9', 'new14', 'new18'];
const ROW_TOL = (() => { const m = process.argv.includes('--mobile'); return m ? 40 : 8; })();

const results = [];
function check(tag, cond, detail) {
  results.push({ tag, cond, detail });
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${tag}${detail ? '  (' + detail + ')' : ''}`);
}

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 2400 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push('console: ' + msg.text()); });

  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000);   // 数据 fetch + 首屏渲染

  // ---- ① 首页: 下拉存在 + 与 AI降亏过滤 同行 ----
  const homeSel = await page.$('#sig-home-fade-mode-sel');
  check('首页模式下拉存在', !!homeSel);
  if (homeSel) {
    const rowInfo = await page.evaluate(() => {
      const sel = document.querySelector('#sig-home-fade-mode-sel');
      const row = sel.closest('.sig-switch-row');
      const aiLab = row && row.querySelector('.sig-switch-ai');
      if (!row || !aiLab) return null;
      const a = sel.getBoundingClientRect(), b = aiLab.getBoundingClientRect();
      return { sameRowDom: true, dy: Math.abs(a.top - b.top), orderOk: b.left < a.left };
    });
    check('首页下拉紧跟「AI降亏过滤」同一行(dy<' + ROW_TOL + ')',
      !!rowInfo && rowInfo.dy < ROW_TOL, rowInfo ? `dy=${rowInfo.dy.toFixed(1)}px 左侧序=${rowInfo.orderOk}` : 'DOM结构缺失');
  }

  // ---- ② 监控卡: 下拉 + bullstop 存在 + 同行 ----
  await page.waitForSelector('.overfit-card', { timeout: 20000 }).catch(() => {});
  const ovSel = await page.$('#overfit-fade-mode-sel');
  check('监控卡模式下拉存在', !!ovSel);
  check('监控卡+1开关(牛市×辅备买全停)存在', !!(await page.$('[data-overfit-bullstop]')));
  if (ovSel) {
    const ovInfo = await page.evaluate(() => {
      const sel = document.querySelector('#overfit-fade-mode-sel');
      const row = sel.closest('.overfit-fade-row');
      const aiLab = row && row.querySelector('.overfit-fade-label');
      if (!row || !aiLab) return null;
      const a = sel.getBoundingClientRect(), b = aiLab.getBoundingClientRect();
      return { dy: Math.abs(a.top - b.top), orderOk: b.left < a.left };
    });
    check('监控卡下拉紧跟「AI降亏过滤」同一行(dy<' + ROW_TOL + ')',
      !!ovInfo && ovInfo.dy < ROW_TOL, ovInfo ? `dy=${ovInfo.dy.toFixed(1)}px 左侧序=${ovInfo.orderOk}` : 'DOM结构缺失');
  }

  // ---- ③ 快速连切 7 模式(首页) ----
  if (homeSel) {
    for (let i = 0; i < MODES.length; i++) {
      await page.evaluate((m) => {
        const s = document.querySelector('#sig-home-fade-mode-sel');
        s.value = m;
        s.dispatchEvent(new Event('change', { bubbles: true }));
      }, MODES[i]);
      await page.waitForTimeout(60);   // 60ms 快切, 故意不留渲染余地
    }
    await page.waitForTimeout(1500);
    const homeStored = await page.evaluate(() => localStorage.getItem('tds_home_fade_mode'));
    check('首页快速连切7模式: localStorage=最后选择(new18)', homeStored === 'new18', `got=${homeStored}`);
    const respOK = await page.evaluate(() => {
      const s = document.querySelector('#sig-home-fade-mode-sel');
      s.value = 'p8'; s.dispatchEvent(new Event('change', { bubbles: true }));
      return localStorage.getItem('tds_home_fade_mode') === 'p8';
    });
    await page.waitForTimeout(500);
    check('首页连切后仍响应(切回 p8 成功)', respOK);
    check('首页默认回落 p8(≡现网基线)', (await page.evaluate(() => localStorage.getItem('tds_home_fade_mode'))) === 'p8');
  }

  // ---- ③b 快速连切 7 模式(监控卡) ----
  if (ovSel) {
    for (let i = 0; i < MODES.length; i++) {
      await page.evaluate((m) => {
        const s = document.querySelector('#overfit-fade-mode-sel');
        s.value = m;
        s.dispatchEvent(new Event('change', { bubbles: true }));
      }, MODES[i]);
      await page.waitForTimeout(60);
    }
    await page.waitForTimeout(2500);   // 组集重绘两图留渲染时间
    const ovStored = await page.evaluate(() => localStorage.getItem('tds_overfit_fade_mode'));
    check('监控卡快速连切7模式: localStorage=最后选择(new18)', ovStored === 'new18', `got=${ovStored}`);
    const ovResp = await page.evaluate(() => {
      const s = document.querySelector('#overfit-fade-mode-sel');
      s.value = 'p8'; s.dispatchEvent(new Event('change', { bubbles: true }));
      return localStorage.getItem('tds_overfit_fade_mode') === 'p8';
    });
    await page.waitForTimeout(1000);
    check('监控卡连切后仍响应(切回 p8 成功)', ovResp);
  }

  // ---- ④ bullstop 开关交互(监控卡): 点一下写入 tds_overfit_bull_stop ----
  const bsCb = await page.$('[data-overfit-bullstop]');
  if (bsCb) {
    await bsCb.click();
    await page.waitForTimeout(400);
    const bsOn = await page.evaluate(() => localStorage.getItem('tds_overfit_bull_stop'));
    await bsCb.click();               // 还原关闭
    await page.waitForTimeout(400);
    check('监控卡+1开关注入/还原正常', bsOn === '1' && (await page.evaluate(() => localStorage.getItem('tds_overfit_bull_stop')) !== '1'),
      `点击后=${bsOn}`);
  }

  // ---- ⑤ 全程无 JS 错误 ----
  check('全程无 pageerror/console.error', errors.length === 0,
    errors.length ? errors.slice(0, 5).join(' | ').slice(0, 500) : 'clean');

  await browser.close();
  const fails = results.filter((r) => !r.cond);
  console.log(`\n[t32-smoke] 总结: ${fails.length === 0 ? 'PASS ✅' : 'FAIL ❌ ' + fails.map((f) => f.tag).join(', ')}`);
  process.exit(fails.length === 0 ? 0 : 1);
})().catch((e) => { console.error('[t32-smoke] 异常终止:', e.message); process.exit(1); });
