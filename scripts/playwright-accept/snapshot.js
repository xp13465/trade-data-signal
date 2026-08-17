#!/usr/bin/env node
/**
 * snapshot.js — Playwright accessibility snapshot 输出(辅助)
 *
 * 目的:输出页面「语义结构树」文本版(role + 名称/文本层级),主控/ reviewer 无法
 *       看图时,用这个拿到页面层级结构直接读。
 *       注:Playwright 1.6x 已移除 page.accessibility API,这里用 DOM 遍历生成语义树
 *       (heading/link/button/nav/main/table 等语义角色 + 文本),等价于 accessibility 快照。
 *
 * 用法:
 *   node snapshot.js <URL> [--wait <ms>]
 *
 * 输出:页面 accessibility 树文本(role/name 层级)。可选 --wait 给前端渲染留时间。
 *
 * 复现:
 *   node snapshot.js http://localhost:8000 --wait 2000
 */
'use strict';

const { chromium } = require('playwright');

const args = process.argv.slice(2);
if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
  console.log('用法: node snapshot.js <URL> [--wait <ms>]');
  process.exit(args.length === 0 ? 1 : 0);
}
const url = args[0];
let wait = 0;
const wi = args.indexOf('--wait');
if (wi >= 0) wait = parseInt(args[wi + 1], 10) || 0;

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  } catch (e) {
    console.error(`页面加载失败: ${e.message}`);
    await browser.close();
    process.exit(1);
  }
  if (wait) await page.waitForTimeout(wait);
  // 注:Playwright 1.6x 已移除 page.accessibility API,改用 DOM 语义树输出文本结构。
  const snap = await page.evaluate(() => {
    const lines = [];
    const roleOf = (el) => {
      const tag = el.tagName.toLowerCase();
      const aria = el.getAttribute('role');
      if (aria) return aria;
      const map = { h1: 'heading', h2: 'heading', h3: 'heading', h4: 'heading',
        a: 'link', button: 'button', nav: 'navigation', main: 'main',
        header: 'banner', footer: 'contentinfo', img: 'img', input: 'textbox',
        select: 'combobox', table: 'table' };
      return map[tag] || tag;
    };
    const walk = (el, depth) => {
      if (el.nodeType !== 1) return;
      const role = roleOf(el);
      const semRoles = ['heading', 'link', 'button', 'navigation', 'main', 'banner',
        'contentinfo', 'img', 'textbox', 'combobox', 'table', 'section', 'article',
        'list', 'listitem', 'tab', 'tablist', 'alert', 'dialog', 'form'];
      const text = (el.innerText || '').trim().replace(/\s+/g, ' ');
      const name = (el.getAttribute('aria-label') || (role === 'img' ? el.getAttribute('alt') : '') || '')
        .trim().replace(/\s+/g, ' ');
      if (semRoles.includes(role)) {
        let line = '  '.repeat(depth) + role;
        if (name) line += ` "${name}"`;
        if (text && role === 'heading') line += ` ${text.slice(0, 60)}`;
        if (text && (role === 'button' || role === 'link' || role === 'tab')) line += ` "${text.slice(0, 60)}"`;
        lines.push(line);
      }
      for (const c of el.children) walk(c, depth + (semRoles.includes(role) ? 1 : 0));
    };
    walk(document.body, 0);
    return lines.join('\n');
  });
  console.log(snap || '(无语义结构输出)');
  await browser.close();
})();
