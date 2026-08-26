#!/usr/bin/env node
/** kelly-overflow-probe.js — 定位凯利参数区横向溢出元素(375px), 输出前 12 个超宽元素路径 */
'use strict';
const path = require('path');
const { chromium } = require(path.join('/Users/linhuichen', 'node_modules', 'playwright'));
const BASE = process.argv[2] || 'http://localhost:8803';
(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 375, height: 812 } });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/index.html#lab?sub=sigkelly`, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForSelector('#lab-kelly-params-toggle', { state: 'visible', timeout: 120000 });
  // 稳健展开: 轮询点击直到 topgrid 可见(防初始重算重渲染折叠)
  for (let i = 0; i < 20; i++) {
    const st = await page.evaluate(() => {
      const b = document.querySelector('.lab-sigkelly-params-body');
      return b ? getComputedStyle(b).display !== 'none' : false;
    });
    if (!st) { try { await page.click('#lab-kelly-params-toggle', { timeout: 3000 }); } catch (e) {} }
    else break;
    await page.waitForTimeout(600);
  }
  await page.waitForTimeout(1000);
  const offenders = await page.evaluate(() => {
    const iw = window.innerWidth;
    const out = [];
    document.querySelectorAll('body *').forEach((el) => {
      const r = el.getBoundingClientRect();
      if (r.width > 1 && r.right > iw + 1) {
        const p = [];
        let n = el;
        while (n && n !== document.body && p.length < 5) {
          let s = n.tagName.toLowerCase();
          if (n.id) s += '#' + n.id;
          else if (n.className && typeof n.className === 'string') s += '.' + n.className.trim().split(/\s+/).slice(0, 2).join('.');
          p.unshift(s);
          n = n.parentElement;
        }
        out.push({ path: p.join(' > '), w: Math.round(r.width), right: Math.round(r.right), sw: el.scrollWidth, cw: el.clientWidth, text: (el.textContent || '').trim().slice(0, 40) });
      }
    });
    out.sort((a, b) => b.right - a.right);
    return { iw, sw: document.scrollingElement.scrollWidth, top: out.slice(0, 14) };
  });
  console.log(`innerWidth=${offenders.iw} docScrollWidth=${offenders.sw}`);
  offenders.top.forEach((o, i) => console.log(`${i + 1}. w=${o.w} right=${o.right} sw=${o.sw} cw=${o.cw} ${o.path}\n   text=${o.text}`));
  await browser.close();
})();
