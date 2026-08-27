#!/usr/bin/env node
/**
 * xcount-consensus-smoke.js — AI信号认可度计数口径(X/Y/W)渲染层冒烟(2026-08-27)
 *
 * 手法: 线上页(真实最新数据) + route 注入本地新构建 min(worktree 无 data 目录取线上数据的
 *   news-epoch-facts.mjs 同款), 验证计数口径渲染三态在真实 DOM 的输出:
 *   S1 页面无 error 级 console/pageerror;
 *   S2 信号 cell data-consensus 全部为 y|x|w 三段式(x∈0..8|"na");
 *   S3 存在当日 winner(|w 结尾)且 hover 弹层显示「{x}票·当日主推」且票数==属性 x 一致;
 *   S4 任一 x=0 cell hover 显示「0·非主推」;
 *   S5 新 tooltip 文案(「模式认可广度」)出现在 title/data-tip;
 *   S6 冒烟↔机检逐条比对(2026-08-27 F2): 读 check_consensus_parity.mjs 产出的 expected
 *     (key=date|index_id|signal, value={y,x,w,label}; env CONS_EXPECTED 可改, 默认
 *     /tmp/consensus-expected.json), 与页面 cell(data-date/data-idx/data-sig 同构 key)比对:
 *     a) expected 覆盖的 cell 逐条比 label(attr 重建 vs 机检);
 *     b) 日期交集内逐日比 winner 集合(页面 |w 集合 == 机检 w=true 集合)——验证「页面 winner
 *        就是机检判定的那支」, 不只是格式存在性;
 *     c) expected 缺失或日期无交集 → SKIP(环境问题不算 FAIL, 提示先跑 parity)。
 *
 * 用法:
 *   node xcount-consensus-smoke.js [--local-only]
 *     默认注入 https://ss.fx8.store; --local-only 则直开 http://localhost:8000(worktree 全量自足场景)
 *
 * 复现:
 *   cd <worktree> && python3 scripts/build_min.py(需先 commit 使 HEAD=新源)
 *   # 先跑机检产出 expected(worktree 无数据产物时 CONS_DATA_DIR 指主树只读):
 *   CONS_DATA_DIR=/Users/linhuichen/code/trade/static-site/data node scripts/check_consensus_parity.mjs
 *   node scripts/playwright-accept/xcount-consensus-smoke.js
 */
'use strict';
const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(process.env.PW_NM ||
  '/Users/linhuichen/code/trade/scripts/playwright-accept', 'node_modules', 'playwright'));

const ROOT = path.resolve(__dirname, '..', '..');
const SITE = path.join(ROOT, 'static-site');
const LOCAL_ONLY = process.argv.includes('--local-only');
const BASE = LOCAL_ONLY ? 'http://localhost:8000' : 'https://ss.fx8.store';

const INJECT = ['app.min.js', 'purpose-notes.min.js', 'lab.min.js', 'common.min.js', 'style.min.css', 'lab.min.css'];
const results = [];
function rec(step, ok, detail) { results.push({ step, ok, detail }); console.log(`${ok ? 'PASS' : 'FAIL'} ${step} ${detail || ''}`); }

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
    viewport: { width: 1440, height: 900 },
  });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console.error: ' + m.text()); });

  // 本地新产物 route 注入(路径子串匹配带 ?v= 版本串)
  if (!LOCAL_ONLY) {
    for (const f of INJECT) {
      const buf = fs.readFileSync(path.join(SITE, f));
      await ctx.route('**/' + f + '*', (route) => route.fulfill({ body: buf,
        contentType: f.endsWith('.css') ? 'text/css' : 'application/javascript' }));
    }
  }
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(4000);
  // 首次访问 onboarding 引导弹窗会拦截 hover: 点「跳过」关闭(标记 localStorage 后不再弹)
  await page.evaluate(() => {
    try { localStorage.setItem('onboarding_done', '1'); } catch (e) {}
    const skip = document.querySelector('.onboarding-skip');
    if (skip) skip.click();
    document.querySelectorAll('.rule-modal-overlay, .rule-modal').forEach((m) => m.classList.add('hidden'));
  });
  await page.waitForTimeout(2000); // 等信号卡+异步依赖(S06快照/tier map)渲染

  // S1 无报错
  rec('S1-no-page-error', errors.length === 0, errors.slice(0, 3).join(' | '));

  // S2 属性三段式格式
  const attrInfo = await page.evaluate(() => {
    const els = [...document.querySelectorAll('[data-consensus]')];
    const bad = [], win = [], zero = [];
    for (const el of els) {
      const v = el.getAttribute('data-consensus');
      if (v === 'na') continue;
      if (!/^\d+\|(?:\d+|na)\|w?$/.test(v)) bad.push(v);
      if (/\|w$/.test(v)) win.push({ v });
      if (/^\d+\|0\|w?$/.test(v)) zero.push(el);
    }
    return { total: els.length, nonNa: els.length - els.filter((e) => e.getAttribute('data-consensus') === 'na').length,
      badCount: bad.length, badSample: bad.slice(0, 3), winners: win.slice(0, 5), zeroCount: zero.length };
  });
  rec('S2-attr-format', attrInfo.total > 0 && attrInfo.badCount === 0,
    `total=${attrInfo.total} nonNa=${attrInfo.nonNa} bad=${attrInfo.badCount}${attrInfo.badSample.join(',')}`);

  // hover 工具函数: 信号 cell 内部子元素(.etf-tag 等)带 data-no-pop, 物理 hover 落点可能命中
  //   子元素致 findTipEl 拒触发 → 改为对 cell span 本身 dispatch mouseover(委托在 document, 同链触发 show())
  async function hoverLabel(sel) {
    await page.evaluate((s) => {
      const el = document.querySelector(s);
      if (!el) return;
      try { el.removeAttribute('data-no-pop'); } catch (e) {}
      el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, cancelable: true }));
    }, sel);
    await page.waitForTimeout(300);
    return page.evaluate(() => {
      const rows = [...document.querySelectorAll('.term-pop-consensus')];
      const el = rows[rows.length - 1];
      return { text: el ? el.textContent.trim() : null,
        tip: el ? (el.getAttribute('title') || '') : '' };
    });
  }

  // S3 winner 弹层 = {x}票·当日主推 且票数与属性一致; 顺带取 S5 的 tooltip 文案
  let s3ok = false, s3detail = 'no winner cell found', s3tip = '';
  if (attrInfo.winners.length) {
    const v = await page.evaluate(() => {
      const el = document.querySelector('[data-consensus$="|w"]');
      return el ? el.getAttribute('data-consensus') : null;
    });
    if (v) {
      const r = await hoverLabel('[data-consensus$="|w"]');
      const expect = parseInt(v.split('|')[1], 10) + '票·当日主推';
      s3ok = !!r.text && r.text.includes(expect);
      s3tip = r.tip || '';
      s3detail = `attr=${v} expect含「${expect}」 got=「${r.text}」`;
    }
  }
  rec('S3-winner-hover-label', s3ok, s3detail);

  // S4 x=0 cell → 0·非主推(属性以 "|0|" 结尾=y|0|空w)
  let s4ok = false, s4detail = 'no x=0 cell in current window';
  {
    const hasZero = await page.evaluate(() => !!document.querySelector('[data-consensus$="|0|"]'));
    if (hasZero) {
      const r = await hoverLabel('[data-consensus$="|0|"]');
      s4ok = !!r.text && r.text.includes('0·非主推');
      s4detail = `got=「${r.text}」`;
    }
  }
  rec('S4-zero-hover-label', s4ok, s4detail);

  // S5 新 tooltip 文案: winner 行 title=CONS_TIP 全文(escaped), 含「模式认可广度」+「票·当日主推」
  rec('S5-tooltip-new-copy', s3tip.includes('模式认可广度') && s3tip.includes('票·当日主推'),
    `tipLen=${s3tip.length}`);

  // S6 冒烟↔机检逐条比对: 读 parity 机检 expected(key=date|index_id|signal → {y,x,w,label}),
  //   与页面 cell(自带 data-date/data-idx/data-sig, key 同构)逐条对齐:
  //   a) expected 覆盖的 cell: attr(y|x|w)重建 label 逐条 == 机检 label;
  //   b) 日期交集内逐日: 页面 |w winner 集合 == 机检 w=true 集合(验证 winner 是机检判定的那支);
  //   c) expected 缺失/日期无交集(线上数据比机检新) → SKIP 不算 FAIL, 提示先跑 parity。
  {
    const expFile = process.env.CONS_EXPECTED || '/tmp/consensus-expected.json';
    let exp = null;
    try { exp = JSON.parse(fs.readFileSync(expFile, 'utf8')); } catch (e) { /* 缺失走 SKIP */ }
    if (!exp) {
      results.push({ step: 'S6-parity-alignment', ok: true, skip: true });
      console.log(`SKIP S6-parity-alignment expected 缺失(${expFile}), 先跑: node scripts/check_consensus_parity.mjs(必要时 CONS_DATA_DIR 指主树)`);
    } else {
      const cells = await page.evaluate(() => [...document.querySelectorAll('[data-consensus]')].map((el) => ({
        key: (el.getAttribute('data-date') || '') + '|' + (el.getAttribute('data-idx') || '') + '|' + (el.getAttribute('data-sig') || ''),
        attr: el.getAttribute('data-consensus') || '',
      })));
      // attr → 渲染 label(与 app.js hoverpop show()/parity renderLabel 同款映射)
      const labelOfAttr = (attr) => {
        if (attr === 'na') return '—';
        const p = attr.split('|');
        const x = parseInt(p[1], 10);
        if (!Number.isFinite(x)) return '—';
        return (x >= 1 && p[2] === 'w') ? x + '票·当日主推' : x + '·非主推';
      };
      const mismatch = [];
      let cmp = 0;
      const pageWinByDate = {}, expWinByDate = {};
      const pageDates = new Set();
      for (const c of cells) {
        pageDates.add(c.key.split('|')[0]);
        const e = exp[c.key];
        if (!e) continue; // 非买入类(attr=na)或机检数据窗口外的 cell 不比对
        cmp++;
        const lbl = labelOfAttr(c.attr);
        if (lbl !== e.label) mismatch.push(`${c.key} label 页「${lbl}」vs 机检「${e.label}」`);
        if (c.attr.endsWith('|w')) (pageWinByDate[c.key.split('|')[0]] = pageWinByDate[c.key.split('|')[0]] || new Set()).add(c.key);
      }
      for (const [k, e] of Object.entries(exp)) {
        if (e.w) { const dx = k.split('|')[0]; (expWinByDate[dx] = expWinByDate[dx] || new Set()).add(k); }
      }
      const sharedDates = [...new Set(Object.keys(exp).map((k) => k.split('|')[0]))].filter((d) => pageDates.has(d));
      let winCmp = 0, winMis = 0;
      for (const d of sharedDates) {
        const pg = pageWinByDate[d] || new Set();
        const ex = expWinByDate[d] || new Set();
        winCmp++;
        if (pg.size !== ex.size || [...ex].some((k) => !pg.has(k))) {
          winMis++;
          mismatch.push(`${d} winner 页=[${[...pg].join(',')}] vs 机检=[${[...ex].join(',')}]`);
        }
      }
      if (!sharedDates.length) {
        results.push({ step: 'S6-parity-alignment', ok: true, skip: true });
        console.log(`SKIP S6-parity-alignment expected 与页面日期无交集(机检窗口过期), 重跑 parity 刷新 ${expFile}`);
      } else {
        rec('S6-parity-alignment', mismatch.length === 0,
          `label逐条=${cmp} winner逐日=${winCmp} 不一致=${mismatch.length}${mismatch.length ? ' | ' + mismatch.slice(0, 3).join(' ; ') : ''}`);
      }
    }
  }

  await browser.close();
  const fails = results.filter((r) => !r.ok).length;
  console.log(`\n== 冒烟结果: ${results.length - fails}/${results.length} PASS${fails ? `, exit 1` : ''}`);
  process.exit(fails ? 1 : 0);
})().catch((e) => { console.error('FATAL', e); process.exit(1); });
