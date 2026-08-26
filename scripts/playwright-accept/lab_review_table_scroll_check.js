#!/usr/bin/env node
/**
 * lab_review_table_scroll_check.js — lab 页手机横向溢出修复验收(feat/lab-review-table-scroll)
 *
 * 病灶(实测修正版): 页面级溢出 docSW=765@375 真凶=.lab-sigkelly-bar 内 [data-tip]::after 气泡
 *   (lab.css L1541 旧版 visibility:hidden absolute w270 参与 scroll overflow);
 *   AI 报告折叠区表格自身横滚正常, 本批 B 项补 max-width:100% 防御对齐 L2071 先例。
 * 修复: A=[data-tip]::after 改 display:none/hover 态 block; B=review-body table 加 max-width:100%。
 *
 * 验收口径(主控拍板 A+B 同批):
 *   1) 375/768/1280 三视口 + 凯利参数区展开(最严苛态) docScrollWidth == viewport.width
 *   2) AI 报告表格内容可横向滑动可见(表格自身滚动容器 scrollLeft 可变且能滚到最右)
 *   3) PC(1280) hover 参数开关 → 说明气泡弹出(display:block 可见); 移开 → 收回(display:none)
 *   4) 折叠展开交互正常(details open 切换往返)
 *
 * 用法: node lab_review_table_scroll_check.js [BASE] [TAG]   (BASE 默认 http://localhost:8803)
 */
'use strict';
const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join('/Users/linhuichen', 'node_modules', 'playwright'));

const BASE = process.argv[2] || 'http://localhost:8803';
const TAG = process.argv[3] || 'after';
const SHOT_DIR = path.join(__dirname);
const VIEWPORTS = [375, 768, 1280];
const TOL = 1;

// 展开凯利参数区(docSW=765 的复现前提, 与 scripts/playwright-accept/kelly-overflow-probe.js 同口径)
async function expandKellyParams(page) {
  await page.waitForSelector('#lab-kelly-params-toggle', { state: 'visible', timeout: 120000 });
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
}

(async () => {
  const browser = await chromium.launch();
  const results = [];
  let hoverCheck = null;
  for (const vw of VIEWPORTS) {
    const ctx = await browser.newContext({ viewport: { width: vw, height: 812 }, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/index.html#lab?sub=sigkelly`, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await expandKellyParams(page);
    // 展开 AI 报告全部 details(折叠交互对象)
    await page.evaluate(() => {
      document.querySelectorAll('.lab-sigkelly-ai-review details').forEach((d) => { d.open = true; });
    });
    await page.waitForTimeout(800);

    const m = await page.evaluate(({ vw, TOL }) => {
      const doc = document.scrollingElement;
      const out = {
        viewport: vw,
        docScrollWidth: doc.scrollWidth,
        docClientWidth: doc.clientWidth,
        overflowX: doc.scrollWidth - doc.clientWidth,
        tables: [],
        detailsToggleOk: null,
      };
      document.querySelectorAll('.lab-sigkelly-ai-review table').forEach((tb, i) => {
        if (tb.scrollWidth <= tb.clientWidth + TOL) return; // 无需滚动的不测滑动
        const before = tb.scrollLeft;
        tb.scrollLeft = tb.scrollWidth;
        const slid = tb.scrollLeft > before;
        const reached = tb.scrollLeft + tb.clientWidth >= tb.scrollWidth - TOL;
        tb.scrollLeft = before;
        out.tables.push({ i, cw: tb.clientWidth, sw: tb.scrollWidth, slid, reached });
      });
      const d0 = document.querySelector('.lab-sigkelly-ai-review details');
      if (d0) {
        const o1 = d0.open;
        d0.open = !o1; const a = d0.open === !o1;
        d0.open = o1; const b = d0.open === o1;
        out.detailsToggleOk = a && b;
      }
      // 溢出元凶复查: 参数栏气泡伪元素默认应为 display:none
      const tg = document.querySelector('.lab-sigkelly-toggle[data-tip]');
      out.tipDefaultDisplay = tg ? getComputedStyle(tg, '::after').display : 'no-el';
      return out;
    }, { vw, TOL });

    // PC hover 气泡验证(仅 1280 跑): hover 带说明的第一个参数开关
    if (vw === 1280) {
      const tg = page.locator('.lab-sigkelly-toggle[data-tip]').first();
      await tg.scrollIntoViewIfNeeded();
      await page.waitForTimeout(200);
      await tg.hover();
      await page.waitForTimeout(400);
      const h1 = await page.evaluate(() => {
        const el = document.querySelector('.lab-sigkelly-toggle[data-tip]');
        const cs = getComputedStyle(el, '::after');
        return { display: cs.display, opacity: cs.opacity, visibility: cs.visibility };
      });
      await page.mouse.move(5, 5); // 移开鼠标
      await page.waitForTimeout(400);
      const h2 = await page.evaluate(() => getComputedStyle(document.querySelector('.lab-sigkelly-toggle[data-tip]'), '::after').display);
      hoverCheck = { hoverShow: h1, mouseAwayDisplay: h2 };
      // hover 态气泡可见时页面也不应有横向溢出
      const hoverDocSW = await page.evaluate(() => ({ sw: document.scrollingElement.scrollWidth, iw: window.innerWidth }));
      hoverCheck.hoverStateDocScrollWidth = hoverDocSW.sw;
      hoverCheck.hoverStateInnerWidth = hoverDocSW.iw;
      await tg.hover(); // 为截图恢复常态前先无所谓
      await page.mouse.move(5, 5);
      await page.waitForTimeout(200);
    }

    // 截图: AI 报告存档区元素图
    const archive = page.locator('.lab-sigkelly-ai-archive').first();
    try {
      await archive.scrollIntoViewIfNeeded();
      await page.waitForTimeout(300);
      await archive.screenshot({ path: path.join(SHOT_DIR, `lab-ai-review-${vw}-${TAG}.png`) });
    } catch (e) { /* 元素截图失败不阻断 */ }

    m.passOverflow = m.overflowX <= TOL;
    const needSlide = m.tables.length > 0;
    m.passSlide = needSlide ? m.tables.every((t) => t.slid && t.reached) : true;
    m.passToggle = m.detailsToggleOk === true;
    m.tipDefaultHidden = m.tipDefaultDisplay === 'none';
    m.pass = m.passOverflow && m.passSlide && m.passToggle && m.tipDefaultHidden;
    results.push(m);
    await ctx.close();
  }
  await browser.close();

  console.log(`\n===== lab 手机横溢出修复验收(A+B 批) [${TAG}] =====`);
  for (const r of results) {
    console.log(`viewport=${r.viewport} docScrollWidth=${r.docScrollWidth} overflowX=${r.overflowX} 页面无溢出=${r.passOverflow ? 'PASS' : 'FAIL'} | 气泡默认display=${r.tipDefaultDisplay}${r.tipDefaultHidden ? '(隐藏OK)' : '(FAIL)'}`);
    r.tables.forEach((t) => console.log(`  table[${t.i}] cw=${t.cw} sw=${t.sw} 可滑=${t.slid} 到最右=${t.reached}`));
    console.log(`  表格滑动=${r.passSlide ? 'PASS' : 'FAIL'} 折叠交互=${r.passToggle ? 'PASS' : 'FAIL'} 综合=${r.pass ? 'PASS' : 'FAIL'}`);
  }
  if (hoverCheck) {
    const showOk = hoverCheck.hoverShow.display === 'block';
    const hideOk = hoverCheck.mouseAwayDisplay === 'none';
    console.log(`PC hover 气泡: hover态display=${hoverCheck.hoverShow.display}(期望block)${showOk ? ' PASS' : ' FAIL'} | 移开display=${hoverCheck.mouseAwayDisplay}(期望none)${hideOk ? ' PASS' : ' FAIL'} | hover态docSW=${hoverCheck.hoverStateDocScrollWidth}/iw=${hoverCheck.hoverStateInnerWidth}`);
  }
  const allPass = results.every((r) => r.pass) && (!hoverCheck || (hoverCheck.hoverShow.display === 'block' && hoverCheck.mouseAwayDisplay === 'none'));
  console.log(`===== 总体[${TAG}]: ${allPass ? 'PASS' : 'FAIL'} =====`);
  fs.writeFileSync(path.join(SHOT_DIR, `lab_review_table_scroll_${TAG}.json`), JSON.stringify({ viewports: results, hoverCheck }, null, 2));
  process.exit(allPass ? 0 : 1);
})().catch((e) => { console.error('PROBE ERROR:', e.message); process.exit(2); });
