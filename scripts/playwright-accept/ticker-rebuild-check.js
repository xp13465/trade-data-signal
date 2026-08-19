#!/usr/bin/env node
/**
 * ticker-rebuild-check.js — 跑马灯「切 tab 重建后是否消失」实测
 *
 * 目的:坐实根因。用户报首页跑马灯"开隐私窗口看不到"(新建 session 首载 → 可能首载就看不到,
 * 或首载看到切 tab/刷新后消失)。本脚本用 Playwright 走真实流程:
 *   1. 首载 overview → 查 .global-ticker 是否渲染
 *   2. 切到 market → 切回 overview(触发 renderOverview content.innerHTML 重建)→ 再查
 *   3. 切到 sentiment → 切回 overview → 再查
 *   4. 滚动页面 → 再查
 *   记录每一步 DOM 事实(.global-ticker 容器数 / .gt-track 品种项数),输出可 grep 证据文本。
 *
 * 用法:
 *   node ticker-rebuild-check.js <URL> [--wait <ms>]
 *     <URL>    本地静态站 http://localhost:8000 或线上三站
 *     --wait   每次渲染后额外等待 ms(默认 2500,给 news_digest .then 链渲染时间)
 *
 * 复现:
 *   python3 -m http.server 8000 -d /Users/linhuichen/code/trade/static-site
 *   node ticker-rebuild-check.js http://localhost:8000
 */
'use strict';

const { chromium } = require('playwright');

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
  console.log(`用法: node ticker-rebuild-check.js <URL> [--wait <ms>]`);
  process.exit(args.length === 0 ? 1 : 0);
}
const url = args[0];
let wait = 2500;
for (let i = 1; i < args.length; i++) {
  if (args[i] === '--wait') wait = parseInt(args[++i], 10) || 2500;
}

const fails = [];
function check(label, ok, detail) {
  const tag = ok ? 'PASS' : 'FAIL';
  if (!ok) fails.push(label);
  console.log(`[${tag}] ${label} ${detail || ''}`);
}

(async () => {
  const b = await chromium.launch({ headless: true });
  try {
    const p = await b.newPage();
    const errors = [];
    p.on('pageerror', e => errors.push('pageerror: ' + e.message));
    p.on('console', m => { if (m.type() === 'error') errors.push('console-error: ' + m.text()); });

    // ---- 首载:先关闭 onboarding 引导弹窗(不关会挡住后续 tab 点击)----
    await p.goto(url, { waitUntil: 'domcontentloaded' });
    await p.waitForTimeout(wait);
    const closeModal = async () => {
      const n = await p.locator('.onboarding-modal .rule-modal-close, .rule-modal.rule-modal-close, .rule-modal .rule-modal-close').count();
      if (n) { await p.evaluate(() => { document.querySelectorAll('.rule-modal-close').forEach(x => x.click()); }); await p.waitForTimeout(400); }
    };
    await closeModal();
    const probe = () => p.evaluate(() => {
      const els = document.querySelectorAll('.global-ticker');
      const names = [];
      document.querySelectorAll('.global-ticker .gt-track .gt-name').forEach(n => names.push(n.textContent.trim()));
      const banner = document.querySelector('.summary-top, #banner, .overview-banner');
      return {
        containerCount: els.length,
        containerConnected: els.length ? els[0].isConnected : false,
        nameCount: names.length,
        names: names.slice(0, 12),
        trackChildren: document.querySelectorAll('.global-ticker .gt-track > *').length,
        bannerInDom: !!banner,
        newsEntry: document.querySelectorAll('.summary-news-entry').length,
        newsFallback: document.querySelectorAll('.summary-news-fallback').length,
        tickerParentChain: els.length ? (els[0].parentElement ? els[0].parentElement.className : 'none') : 'no-el',
      };
    });
    let s = await probe();
    console.log('\n===== 场景1: 首载 overview(已关引导弹窗)=====');
    check('首载容器存在', s.containerCount > 0, JSON.stringify(s));

    // ---- 2. 切 market → 切回 overview ----
    console.log('\n===== 场景2: market → overview =====');
    await p.evaluate(() => { const b = document.querySelector('button[data-tab="market"]'); if (b) b.click(); });
    await p.waitForTimeout(1500);
    await p.evaluate(() => { const b = document.querySelector('button[data-tab="overview"]'); if (b) b.click(); });
    await p.waitForTimeout(wait);
    await closeModal();
    s = await probe();
    check('切1次后容器仍在', s.containerCount > 0 && s.containerConnected, JSON.stringify(s));

    // ---- 3. 切 sentiment → 切回 overview ----
    console.log('\n===== 场景3: sentiment → overview =====');
    await p.evaluate(() => { const b = document.querySelector('button[data-tab="sentiment"]'); if (b) b.click(); });
    await p.waitForTimeout(1500);
    await p.evaluate(() => { const b = document.querySelector('button[data-tab="overview"]'); if (b) b.click(); });
    await p.waitForTimeout(wait);
    await closeModal();
    s = await probe();
    check('切2次后容器仍在', s.containerCount > 0 && s.containerConnected, JSON.stringify(s));

    // ---- 4. 滚动页面 ----
    console.log('\n===== 场景4: 滚动后 =====');
    await p.mouse.wheel(0, 800);
    await p.waitForTimeout(800);
    s = await probe();
    check('滚动后容器仍在', s.containerCount > 0 && s.containerConnected, JSON.stringify(s));

    // ---- 浏览器报错汇总 ----
    console.log('\n===== 浏览器报错 =====');
    if (errors.length === 0) console.log('[PASS] 无 pageerror / console-error');
    else { errors.forEach(e => console.log('[ERR] ' + e)); check('无浏览器报错', false, 'errors=' + errors.length); }

    console.log('\n===== 汇总 =====');
    if (fails.length === 0) console.log('[ALL PASS] 跑马灯首载 + 切tab + 滚动全程可见,未消失');
    else { console.log('[FAIL] 跑马灯在这些场景下消失: ' + fails.join(' / ')); process.exit(1); }
  } finally {
    await b.close();
  }
})().catch(e => { console.error('[FATAL] ' + (e && e.stack || e)); process.exit(1); });
