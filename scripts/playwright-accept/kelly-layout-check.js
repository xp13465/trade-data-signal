#!/usr/bin/env node
/**
 * kelly-layout-check.js — 2026-08-26 凯利参数区排版调整验收脚本(feat/kelly-longmode-layout)
 *
 * 任务:「ai长线模式(G/H/I)仓位管理」块从降亏过滤区后移到费率模块后。
 * 断言(纯事实层, 观感由用户拍板):
 *   A1 DOM 顺序: fee-row → gih 块 → 降亏过滤区(.lab-sigkelly-toggle-row)
 *   A2 结构: .lab-sigkelly-topgrid 下 feecol+gihcol 两列
 *   A3 PC 1280: 费率与长线模式同行, 降亏过滤区在两者之下独占一行
 *   A4 窄屏(768/375): feecol 与 gihcol 垂直堆叠(费率一行/长线模式一行)
 *   A5 手机 375: 过滤区内 poscap 组 column 堆叠(AI仓位建议 与 AI降亏 两行)
 *   A6 参数区内部无横向溢出(全页 scrollWidth 溢出为 AI 报告折叠区表格存量问题,
 *      基线对照 kelly-overflow-probe.js 双侧一致=765px, 非本次引入, §23.7⑤ 上报)
 *   B1-B5 交互回归: G档切换+持久化 / gih开关 / 对比表开合 / 费率预设 / AI降亏总开关
 *
 * 用法: node kelly-layout-check.js <baseURL>   (默认 http://localhost:8803)
 * 复现:
 *   python3 -m http.server 8803 -d <worktree>/static-site
 *   node scripts/playwright-accept/kelly-layout-check.js http://localhost:8803
 */
'use strict';
const path = require('path');
const { chromium } = require(path.join('/Users/linhuichen', 'node_modules', 'playwright'));

const BASE = process.argv[2] || 'http://localhost:8803';
const OUT = __dirname;
const results = [];
const consoleErrors = [];
function ok(name, pass, detail) {
  results.push({ name, pass, detail });
  console.log(`${pass ? 'PASS' : 'FAIL'}  ${name}${detail ? '  | ' + detail : ''}`);
}
/** 稳健展开参数区: 初始重算完成后会整条重渲染 bar 把折叠态打回去, 轮询点开直到 topgrid 可见 */
async function ensureExpanded(page) {
  await page.waitForSelector('#lab-kelly-params-toggle', { state: 'visible', timeout: 120000 });
  for (let i = 0; i < 40; i++) {
    const open = await page.evaluate(() => {
      const b = document.querySelector('.lab-sigkelly-params-body');
      return !!(b && getComputedStyle(b).display !== 'none' && b.querySelector('.lab-sigkelly-topgrid'));
    });
    if (open) return true;
    try { await page.click('#lab-kelly-params-toggle', { timeout: 2000 }); } catch (e) {}
    await page.waitForTimeout(600);
  }
  return false;
}

(async () => {
  const browser = await chromium.launch();
  const viewports = [
    { tag: 'pc1280', width: 1280, height: 900 },
    { tag: 'tablet768', width: 768, height: 1024 },
    { tag: 'mobile375', width: 375, height: 812 },
  ];
  for (const vp of viewports) {
    const ctx = await browser.newContext({ viewport: { width: vp.width, height: vp.height } });
    const page = await ctx.newPage();
    page.on('pageerror', (e) => consoleErrors.push(`[${vp.tag}] pageerror: ${e.message}`));
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(`[${vp.tag}] console.error: ${m.text().slice(0, 200)}`); });
    try {
      await page.goto(`${BASE}/index.html#lab?sub=sigkelly`, { waitUntil: 'domcontentloaded', timeout: 60000 });
      const expanded = await ensureExpanded(page);
      ok(`A0 [${vp.tag}] 参数区展开成功`, expanded);
      if (!expanded) throw new Error('params never expanded');
      await page.waitForTimeout(500);

      // A1 DOM 顺序
      const order = await page.evaluate(() => {
        const fee = document.querySelector('.lab-sigkelly-fee-row');
        const gih = document.querySelector('.lab-sigkelly-topgrid .lab-sigkelly-toggle-group-gih');
        const filterRow = document.querySelector('.lab-sigkelly-toggle-row');
        const cmp = (a, b) => a && b ? (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? 1 : -1) : 0;
        return { feeBeforeGih: cmp(fee, gih) === 1, gihBeforeFilter: cmp(gih, filterRow) === 1 };
      });
      ok(`A1 [${vp.tag}] DOM顺序 fee→gih→过滤区`, order.feeBeforeGih && order.gihBeforeFilter, JSON.stringify(order));

      // A2 结构
      const struct = await page.evaluate(() => {
        const grid = document.querySelector('.lab-sigkelly-topgrid');
        return { gridExists: !!grid, hasFeecol: !!(grid && grid.querySelector(':scope > .lab-sigkelly-feecol > .lab-sigkelly-fee-row')),
          hasGihcol: !!(grid && grid.querySelector(':scope > .lab-sigkelly-gihcol > .lab-sigkelly-toggle-group-gih')) };
      });
      ok(`A2 [${vp.tag}] topgrid(feecol+gihcol)结构`, struct.gridExists && struct.hasFeecol && struct.hasGihcol, JSON.stringify(struct));

      // A6 参数区内部无横向溢出(只验本任务改动域, 全页存量溢出见文件头注释)
      const pOverflow = await page.evaluate(() => {
        const iw = window.innerWidth;
        const zone = document.querySelector('.lab-sigkelly-params-body');
        if (!zone) return { bad: 1 };
        let bad = [];
        zone.querySelectorAll('*').forEach((el) => {
          const r = el.getBoundingClientRect();
          if (r.width > 1 && r.right > iw + 1) bad.push(el.className ? String(el.className).slice(0, 50) : el.tagName);
        });
        return { badCount: bad.length, sample: bad.slice(0, 3) };
      });
      ok(`A6 [${vp.tag}] 参数区无横向溢出`, pOverflow.badCount === 0, JSON.stringify(pOverflow).slice(0, 120));

      if (vp.tag === 'pc1280') {
        // A3 PC 同行 + 过滤区独占下一行
        const geo = await page.evaluate(() => {
          const r = (sel) => { const el = document.querySelector(sel); if (!el) return null; const b = el.getBoundingClientRect(); return { top: b.top, bottom: b.bottom }; };
          return { fee: r('.lab-sigkelly-feecol'), gih: r('.lab-sigkelly-gihcol'), filter: r('.lab-sigkelly-toggle-row') };
        });
        const sameRow = geo.fee && geo.gih && Math.abs(geo.fee.top - geo.gih.top) < 4;
        const filterBelow = geo.filter && geo.fee && geo.gih && geo.filter.top >= Math.max(geo.fee.bottom, geo.gih.bottom) - 1;
        ok('A3a [pc1280] 费率+长线同行(top对齐)', !!sameRow, `feeTop=${geo.fee && geo.fee.top.toFixed(1)} gihTop=${geo.gih && geo.gih.top.toFixed(1)}`);
        ok('A3b [pc1280] 过滤区独占下一整行', !!filterBelow, `filterTop=${geo.filter && geo.filter.top.toFixed(1)} colsBottom=${geo.fee && Math.max(geo.fee.bottom, geo.gih.bottom).toFixed(1)}`);

        // B3 PC 对比表展开(全宽) → 截图 → 收起
        await page.click('#lab-kelly-gih-compare-btn');
        await page.waitForTimeout(300);
        const cmpOpen = await page.evaluate(() => {
          const b = document.getElementById('lab-kelly-gih-compare-body');
          return b && b.style.display !== 'none' ? { w: Math.round(b.getBoundingClientRect().width), vw: window.innerWidth } : null;
        });
        ok('B3a [pc1280] 对比表展开可见', !!cmpOpen, cmpOpen ? `width=${cmpOpen.w}px viewport=${cmpOpen.vw}px` : '');
        await page.screenshot({ path: path.join(OUT, 'kelly-layout-pc1280-compare-open.png'), fullPage: false });
        await page.click('#lab-kelly-gih-compare-btn');
        await page.waitForTimeout(200);
        const cmpClosed = await page.evaluate(() => {
          const b = document.getElementById('lab-kelly-gih-compare-body');
          return b && b.style.display === 'none';
        });
        ok('B3b [pc1280] 对比表收起隐藏', !!cmpClosed);
      }

      if (vp.tag === 'tablet768' || vp.tag === 'mobile375') {
        // A4 窄屏: feecol 与 gihcol 垂直堆叠(不同行起始 + gih 在 fee 之下)
        const stacked = await page.evaluate(() => {
          const f = document.querySelector('.lab-sigkelly-feecol').getBoundingClientRect();
          const g = document.querySelector('.lab-sigkelly-gihcol').getBoundingClientRect();
          return { feeBottom: f.bottom, gihTop: g.top, sameTop: Math.abs(f.top - g.top) };
        });
        ok(`A4 [${vp.tag}] 费率/长线两行堆叠`, stacked.sameTop > 8 && stacked.gihTop >= stacked.feeBottom - 1,
          `feeBottom=${stacked.feeBottom.toFixed(0)} gihTop=${stacked.gihTop.toFixed(0)}`);
      }

      if (vp.tag === 'mobile375') {
        // A5 手机: 过滤区内 poscap 组(toggle-row 直接子组, 非对比表内同名装饰组) column 两行堆叠
        const poscap = await page.evaluate(() => {
          const grp = document.querySelector('.lab-sigkelly-toggle-row > .lab-sigkelly-toggle-group-poscap');
          if (!grp) return null;
          const fd = getComputedStyle(grp).flexDirection;
          const kids = [...grp.children].filter((el) => el.offsetHeight > 0).map((el) => Math.round(el.getBoundingClientRect().top));
          return { fd, rows: [...new Set(kids)].length };
        });
        ok('A5 [mobile375] 过滤区内仓位/AI降亏分两行(poscap column)', !!poscap && poscap.fd === 'column' && poscap.rows >= 2,
          poscap ? `flexDirection=${poscap.fd} distinctRows=${poscap.rows}` : 'poscap组未找到');
      }

      await page.screenshot({ path: path.join(OUT, `kelly-layout-${vp.tag}.png`), fullPage: false });

      // ---- 交互回归 ----
      // B1 G档切换 13万→15万: 轮询等重算完成(active 变化), 断言 ✓ 文案+localStorage 持久化
      await page.evaluate(() => { try { localStorage.removeItem('tds_gih_g_tier'); } catch (e) {} });
      const beforeTier = await page.evaluate(() => {
        const el = document.querySelector('.lab-sigkelly-gih-tier-btn.lab-sigkelly-gih-tier-active');
        return el ? el.dataset.tier : null;
      });
      await page.click('.lab-sigkelly-gih-tier-btn[data-tier="15万"]');
      let afterTier = null;
      for (let i = 0; i < 60; i++) {
        afterTier = await page.evaluate(() => ({
          active: (document.querySelector('.lab-sigkelly-gih-tier-btn.lab-sigkelly-gih-tier-active') || {}).dataset ? document.querySelector('.lab-sigkelly-gih-tier-btn.lab-sigkelly-gih-tier-active').dataset.tier : null,
          stored: localStorage.getItem('tds_gih_g_tier'),
          textHasCheck: /✓/.test((document.querySelector('.lab-sigkelly-gih-tier-btn[data-tier="15万"]') || {}).textContent || '') }));
        if (afterTier.active === '15万') break;
        await page.waitForTimeout(1000);
      }
      ok(`B1 [${vp.tag}] G档切15万(active+✓+持久化)`, beforeTier === '13万' && afterTier.active === '15万' && afterTier.stored === '15万' && afterTier.textHasCheck,
        `before=${beforeTier} after=${JSON.stringify(afterTier)}`);
      await page.click('.lab-sigkelly-gih-tier-btn[data-tier="13万"]'); // 还原默认档
      await page.waitForTimeout(1500);

      // B2 gih 开关翻转 + 写共享键 tds_gihpos({on:true} 对象)
      const gihBefore = await page.evaluate(() => document.querySelector('.lab-sigkelly-toggle-gih').checked);
      await page.click('.lab-sigkelly-toggle-gih');
      await page.waitForTimeout(400);
      const gihMid = await page.evaluate(() => document.querySelector('.lab-sigkelly-toggle-gih').checked);
      const gihStored = await page.evaluate(() => JSON.parse(localStorage.getItem('tds_gihpos') || 'null'));
      await page.click('.lab-sigkelly-toggle-gih'); // 切回默认关
      await page.waitForTimeout(400);
      ok(`B2 [${vp.tag}] 长线开关翻转+写共享键`, gihBefore === false && gihMid === true && gihStored && gihStored.on === true,
        `before=${gihBefore} mid=${gihMid} tds_gihpos=${JSON.stringify(gihStored)}`);

      // B4 费率预设切换 etf_main→etf_def(轮询等重算重渲染)
      const feeBefore = await page.evaluate(() => {
        const el = document.querySelector('.lab-sigkelly-fee-btn.active');
        return el ? el.dataset.fee : null;
      });
      await page.click('.lab-sigkelly-fee-btn[data-fee="etf_def"]');
      let feeAfter = null;
      for (let i = 0; i < 45; i++) {
        feeAfter = await page.evaluate(() => {
          const el = document.querySelector('.lab-sigkelly-fee-btn.active');
          return el ? el.dataset.fee : null;
        });
        if (feeAfter === 'etf_def') break;
        await page.waitForTimeout(1000);
      }
      ok(`B4 [${vp.tag}] 费率预设切换(${feeBefore}→etf_def)`, feeBefore === 'etf_main' && feeAfter === 'etf_def', `after=${feeAfter}`);
      await page.click('.lab-sigkelly-fee-btn[data-fee="etf_main"]'); // 还原默认档
      await page.waitForTimeout(1200);

      // B3 对比表开合(窄屏也验一次功能)
      await page.click('#lab-kelly-gih-compare-btn');
      await page.waitForTimeout(250);
      const cmpOpen2 = await page.evaluate(() => { const b = document.getElementById('lab-kelly-gih-compare-body'); return b && b.style.display !== 'none'; });
      await page.click('#lab-kelly-gih-compare-btn');
      await page.waitForTimeout(250);
      const cmpClosed2 = await page.evaluate(() => { const b = document.getElementById('lab-kelly-gih-compare-body'); return b && b.style.display === 'none'; });
      ok(`B3 [${vp.tag}] 对比表展开/收起`, !!cmpOpen2 && !!cmpClosed2);

      // B5 AI降亏过滤总开关翻转(重算较重放最后, 只断 checked 翻转不等重算完成)
      const aiBefore = await page.evaluate(() => document.querySelector('.lab-sigkelly-toggle-aimacro').checked);
      await page.click('.lab-sigkelly-toggle-aimacro');
      await page.waitForTimeout(600);
      const aiMid = await page.evaluate(() => document.querySelector('.lab-sigkelly-toggle-aimacro').checked);
      ok(`B5 [${vp.tag}] AI降亏总开关翻转`, aiBefore === true && aiMid === false, `before=${aiBefore} mid=${aiMid}`);
    } catch (e) {
      ok(`[${vp.tag}] 流程异常`, false, e.message.slice(0, 200));
    }
    await ctx.close();
  }
  await browser.close();
  const fails = results.filter((r) => !r.pass);
  console.log(`\n===== 结果: ${results.length - fails.length}/${results.length} PASS =====`);
  if (consoleErrors.length) {
    console.log(`console/pageerror ${consoleErrors.length} 条:`);
    consoleErrors.slice(0, 10).forEach((e) => console.log('  ' + e));
  } else {
    console.log('console/pageerror: 0 条');
  }
  process.exit(fails.length ? 1 : 0);
})();
