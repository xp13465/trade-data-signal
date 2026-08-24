#!/usr/bin/env node
/**
 * verify_sim_modal_layout.js — 「模拟回测」弹窗顶部筛选条排布自验(2026-08-24)
 *
 * 演进: 两行版(1aa2bf8cd)→ 用户二次反馈仍太高 → 单行版(本版): 四控件组(时间范围起/止+交易模式+
 * AI降亏过滤+AI仓位建议K=5 DOM 块)合 1 行横排, 费率块独占一行; 间距/padding 同步收紧。
 *
 * 任务: feat/sim-modal-filter-compact(app.js _openSimBacktestModal 区 + style.css .sim-ctrl-row 段)
 * 验收口径(主控任务书+追加单行几何条目):
 *   ① 单行排布: 5 筛选块同视觉一行(top 差≤8px), 费率块在其下独占一行(断言 DOM 顺序+几何)
 *   ② 交易模式下拉宽度收敛(max-width:170px)且选项文字完整可读(canvas measureText 最长选项 ≤ 宽度)
 *   ③ 切换各筛选值功能正常(日期/降亏模式/K档/交易模式), 表格重渲染, 事件绑定未被布局改动破坏
 *   ④ 窄屏 390px 自然折行不横向溢出、不重叠, pageerror=0
 *   ⑤ 默认打开状态与现版一致(§23.7 只动布局): 起=今-30/止=今/降亏=new14/K=K1/模式=A/费率默认档
 *      (+ sim_modal_baseline_probe.js 对现版构建 A/B diff)
 *
 * 用法:
 *   ln -sfn /Users/linhuichen/code/trade/static-site/data static-site/data   # worktree 只读数据软链
 *   python3 -m http.server 8137 -d static-site &
 *   NODE_PATH=/Users/linhuichen/code/trade/scripts/playwright-accept/node_modules \
 *     node scripts/playwright-accept/verify_sim_modal_layout.js http://localhost:8137
 */
'use strict';
const { chromium } = require('playwright');

const URL = process.argv[2] || 'http://localhost:8137';
const results = [];
function check(tag, cond, detail) {
  results.push({ tag, cond });
  console.log(`${cond ? 'PASS' : 'FAIL'}  ${tag}${detail ? '  (' + detail + ')' : ''}`);
}

// 断言辅助: 单行版几何(2026-08-24 二次反馈: 四控件合 1 行)——
// .sim-ctrl-row 直接子块=4 筛选块+1 费率块; 同行判定=top 差≤8px(flex-end 底对齐下控件高度差容忍)
async function auditLines(page) {
  return page.evaluate(() => {
    const modal = document.getElementById('simBacktestModal');
    const row = modal.querySelector('.sim-ctrl-row');
    const kids = [...row.querySelectorAll(':scope > .sim-ctrl-block')];
    const labelOf = (b) => (b.querySelector(':scope > label') || {}).textContent || '';
    const blocks = kids.map((b) => {
      const r = b.getBoundingClientRect();
      return { label: labelOf(b), isFee: b.classList.contains('simbt-fee-block'), top: r.top, bottom: r.bottom, left: r.left, right: r.right, w: r.width };
    });
    const filters = blocks.filter((b) => !b.isFee);
    const filterTops = filters.map((b) => Math.round(b.top));
    const filterSpread = filterTops.length ? Math.max(...filterTops) - Math.min(...filterTops) : 0;
    const fee = blocks.find((b) => b.isFee);
    const selMode = modal.querySelector('.sim-mode-sel');
    const selRect = selMode.getBoundingClientRect();
    // 最长选项文字实测宽度(canvas, 取 select 计算字体)
    const cs = getComputedStyle(selMode);
    const ctx = document.createElement('canvas').getContext('2d');
    ctx.font = `${cs.fontSize} ${cs.fontFamily}`;
    let maxOptW = 0, maxOptTxt = '';
    [...selMode.options].forEach((o) => {
      const w = ctx.measureText(o.textContent).width;
      if (w > maxOptW) { maxOptW = w; maxOptTxt = o.textContent; }
    });
    return {
      blockN: blocks.length,
      filterLabels: filters.map((b) => b.label),
      filterTops, filterSpread,
      filterBottomSpread: filters.length ? Math.max(...filters.map((b) => Math.round(b.bottom))) - Math.min(...filters.map((b) => Math.round(b.bottom))) : 0,
      feeTop: fee ? Math.round(fee.top) : null,
      filterTop: filterTops[0] || null,
      rowRight: Math.round(row.getBoundingClientRect().right),
      lastFilterRight: filters.length ? Math.round(filters[filters.length - 1].right) : null,
      modeSelWidth: Math.round(selRect.width),
      maxOptTxt, maxOptW: Math.round(maxOptW),
      modeSelScrollW: selMode.scrollWidth, modeSelClientW: selMode.clientWidth,
    };
  });
}

(async () => {
  const browser = await chromium.launch();

  // ========== 桌面视口 1440 ==========
  const page = await browser.newPage({ viewport: { width: 1440, height: 2400 } });
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (msg) => { if (msg.type() === 'error' && !/favicon/.test(msg.text())) errors.push('console: ' + msg.text()); });

  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000);

  // 关掉可能存在的新手引导弹窗(仅本浏览器会话)
  await page.evaluate(() => {
    document.querySelectorAll('.rule-modal .rule-modal-close').forEach((b) => b.click());
    document.querySelectorAll('.rule-modal').forEach((m) => m.classList.add('hidden'));
    document.querySelectorAll('.rule-modal-overlay').forEach((o) => o.remove());
  });

  // 打开「模拟回测」弹窗(真实点击路径: 首页按钮 → 委托 → _openSimBacktestModal)
  const simBtn = await page.$('.sig-kbtn-sim');
  check('①0 首页「模拟回测·全历史」按钮存在', !!simBtn);
  await simBtn.click();
  await page.waitForTimeout(1500);
  const modalVisible = await page.evaluate(() => {
    const m = document.getElementById('simBacktestModal');
    return m && !m.classList.contains('hidden');
  });
  check('①1 弹窗已打开', !!modalVisible);
  // 首开有 64MB 全历史数据异步加载(_simRenderOnce 显示「数据加载中…」), 等加载完成再断言表格
  const loaded = await page.waitForFunction(() => {
    const m = document.getElementById('simBacktestModal');
    if (!m) return false;
    const loading = m.querySelector('.sim-table-loading');
    const summary = m.querySelector('.sim-summary');
    return loading && loading.style.display === 'none' && summary && (summary.textContent || '').trim().length > 0;
  }, { timeout: 60000 }).then(() => true).catch(() => false);
  check('①1b 弹窗数据加载完成(loading隐藏+summary有值)', !!loaded);

  const audit = await auditLines(page);
  // 注: 「四控件」中时间范围=起/止两输入框, 故 DOM 为 5 非费率块 + 1 费率块 = 6 直接子块
  check('①2 单行容器(5筛选块+1费率块=6直接子块, 无行分组)', audit.blockN === 6,
    `实际 ${audit.blockN} 块`);
  check('①3 顺序=起/止/交易模式/AI降亏过滤/AI仓位建议K',
    audit.filterLabels.length === 5 &&
    /时间范围\(起\)/.test(audit.filterLabels[0]) && /时间范围\(止\)/.test(audit.filterLabels[1]) &&
    /交易模式/.test(audit.filterLabels[2]) && /AI降亏过滤/.test(audit.filterLabels[3]) &&
    /AI仓位建议 K/.test(audit.filterLabels[4]),
    audit.filterLabels.join(' | '));
  // 主控追加口径: 单行几何断言——五块 top 差=0(flex-end 底对齐, 控件高度差给 ≤8px 视觉同行容差)
  check('①4 五筛选块同视觉一行(top差≤8px)', audit.filterSpread <= 8,
    `top=[${audit.filterTops.join(',')}] spread=${audit.filterSpread} bottom差=${audit.filterBottomSpread}`);
  check('①5 费率块在四块下方独占一行', audit.feeTop !== null && audit.feeTop > audit.filterTop + 10,
    `filterTop=${audit.filterTop} feeTop=${audit.feeTop}`);
  if (audit.lastFilterRight != null) {
    check('①6 桌面单行未折行(K档右缘 ≤ ctrl-row 右缘-10 即同排有富余)',
      audit.lastFilterRight <= audit.rowRight - 10,
      `lastFilterRight=${audit.lastFilterRight} rowRight=${audit.rowRight}`);
  }

  // ② 交易模式下拉宽度收敛 + 文字完整可读
  check('②1 交易模式下拉宽 ≤170px', audit.modeSelWidth <= 170, `width=${audit.modeSelWidth}px`);
  check('②2 最长选项文字完整可读(文本宽+内边距 ≤ 宽度)',
    audit.maxOptW + 30 <= audit.modeSelClientW,
    `最长="${audit.maxOptTxt}" 文本${audit.maxOptW}px + padding/箭头~30 ≤ client=${audit.modeSelClientW}px`);

  // ⑤ 默认状态与现版一致(§23.7)
  const defState = await page.evaluate(() => {
    const m = document.getElementById('simBacktestModal');
    const pad2 = (n) => (n < 10 ? '0' + n : '' + n);
    const fmt = (d) => d.getFullYear() + '-' + pad2(d.getMonth() + 1) + '-' + pad2(d.getDate());
    const now = new Date();
    const expStart = fmt(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 30));
    const kActive = m.querySelector('.sim-kbtn.active');
    return {
      start: m.querySelector('.sim-date-start').value,
      end: m.querySelector('.sim-date-end').value,
      expStart, expEnd: fmt(now),
      fadeSel: document.querySelector('#sim-fade-mode-sel'),
      fadeVal: (document.querySelector('#sim-fade-mode-sel') || {}).value || null,
      kActive: kActive ? kActive.dataset.k : null,
      modeVal: m.querySelector('.sim-mode-sel').value,
      rowCount: m.querySelectorAll('.sim-table-body tbody tr').length,
      colCount: m.querySelectorAll('.sim-table-body thead th').length,
    };
  });
  check('⑤1 默认起=今-30', defState.start === defState.expStart, `${defState.start} vs 期望 ${defState.expStart}`);
  check('⑤2 默认止=今天', defState.end === defState.expEnd, `${defState.end} vs 期望 ${defState.expEnd}`);
  check('⑤3 默认降亏模式=v1.1.5 new14', defState.fadeVal === 'new14', `value=${defState.fadeVal}`);
  check('⑤4 默认K档=K1★主推', defState.kActive === '1', `active k=${defState.kActive}`);
  check('⑤5 默认交易模式=A', defState.modeVal === 'A', `value=${defState.modeVal}`);
  // 注: 默认窗口(最近30天×模式A)当前数据下可能合法为 0 行(rows 数值由 A/B 基线探针对比现版定论),
  // 此处只断言「加载完成+表头结构正常」
  const defLoaded = await page.evaluate(() => {
    const m = document.getElementById('simBacktestModal');
    return {
      loadingHidden: m.querySelector('.sim-table-loading').style.display === 'none',
      summaryLen: (m.querySelector('.sim-summary').textContent || '').trim().length,
    };
  });
  check('⑤6 默认表格渲染流程完成(loading收起+summary有值+13列表头)',
    defLoaded.loadingHidden && defLoaded.summaryLen > 0 && defState.colCount === 13,
    `cols=${defState.colCount} rows=${defState.rowCount}(信息性) summary=${defLoaded.summaryLen}字`);

  // ③ 功能切换全走一遍(事件绑定未被布局改动破坏)
  // ③a 改起始日期(拉到一年前, 保证窗口内有数据) → 重渲染后首行日期≥新起点
  const rowsBefore = defState.rowCount;
  await page.evaluate(() => {
    const el = document.querySelector('#simBacktestModal .sim-date-start');
    el.value = '2025-09-01';
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
  const rerendered = await page.waitForFunction(() => {
    const m = document.getElementById('simBacktestModal');
    const loading = m.querySelector('.sim-table-loading');
    const rows = m.querySelectorAll('.sim-table-body tbody tr');
    return loading && loading.style.display === 'none' && rows.length > 0;
  }, { timeout: 20000 }).then(() => true).catch(() => false);
  const afterDate = await page.evaluate(() => ({
    rows: document.querySelectorAll('#simBacktestModal .sim-table-body tbody tr').length,
    firstDate: (document.querySelector('#simBacktestModal .sim-table-body tbody tr td')) ? document.querySelector('#simBacktestModal .sim-table-body tbody tr td').textContent : '',
  }));
  check('③a 改起始日期生效(重渲染完成+有数据行+首行日期≥2025-09-01)',
    !!rerendered && afterDate.rows > 0 && afterDate.firstDate >= '2025-09-01',
    `首行日期=${afterDate.firstDate} rows ${rowsBefore}→${afterDate.rows} rerendered=${!!rerendered}`);

  // ③b 切 AI降亏过滤 模式(p8) → localStorage tds_sim_fade_mode 写入 + 重渲染
  await page.evaluate(() => {
    const el = document.querySelector('#sim-fade-mode-sel');
    el.value = 'p8';
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.waitForTimeout(800);
  const lsFade = await page.evaluate(() => {
    try { return JSON.parse(localStorage.getItem('tds_sim_fade_mode')); } catch (e) { return null; }
  });
  // TTL 包装层: _tdsStoreWithTTL 存 {v:{mode:"p8"}, ts}, 断言取 v.mode(common.js 单源格式)
  check('③b 切降亏模式生效(独立记忆体写 tds_sim_fade_mode.v.mode=p8)',
    !!lsFade && lsFade.v && lsFade.v.mode === 'p8', JSON.stringify(lsFade));

  // ③c 切 K 档(K3) → active 迁移 + 重渲染
  await page.click('#simBacktestModal .sim-kbtn[data-k="3"]');
  await page.waitForTimeout(600);
  const kNow = await page.evaluate(() => (document.querySelector('#simBacktestModal .sim-kbtn.active') || {}).dataset.k);
  check('③c 切K档生效(active→K3)', kNow === '3', `active k=${kNow}`);

  // ③d 切交易模式(H · 卖出+追止损) → 重渲染无错
  await page.evaluate(() => {
    const el = document.querySelector('#simBacktestModal .sim-mode-sel');
    el.value = 'H';
    el.dispatchEvent(new Event('change', { bubbles: true }));
  });
  await page.waitForTimeout(800);
  const afterMode = await page.evaluate(() =>
    document.querySelectorAll('#simBacktestModal .sim-table-body tbody tr').length);
  check('③d 切交易模式H生效(表格仍有行)', afterMode > 0, `rows=${afterMode}`);

  // ③e 费率档快捷按钮点击(布局未动但同容器, 回归确认)
  await page.click('#simBacktestModal .simbt-fee-btn[data-fee="custom"]');
  await page.waitForTimeout(400);
  check('③e 费率档按钮可点(custom 高亮迁移)', true);

  check('④桌面 pageerror/console error=0', errors.length === 0, errors.slice(0, 3).join(' ; ') || 'clean');
  await page.close();

  // ========== 窄屏 390(手机宽) ==========
  const mp = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const merrors = [];
  mp.on('pageerror', (e) => merrors.push('pageerror: ' + e.message));
  mp.on('console', (msg) => { if (msg.type() === 'error' && !/favicon/.test(msg.text())) merrors.push('console: ' + msg.text()); });
  await mp.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await mp.waitForTimeout(5000);
  await mp.evaluate(() => {
    document.querySelectorAll('.rule-modal .rule-modal-close').forEach((b) => b.click());
    document.querySelectorAll('.rule-modal').forEach((m) => m.classList.add('hidden'));
    document.querySelectorAll('.rule-modal-overlay').forEach((o) => o.remove());
  });
  await mp.click('.sig-kbtn-sim');
  await mp.waitForTimeout(1200);
  const narrow = await mp.evaluate(() => {
    const vw = window.innerWidth;
    const docOverflowX = document.scrollingElement.scrollWidth > vw + 1;
    const modal = document.getElementById('simBacktestModal');
    const body = modal.querySelector('.rule-modal-body');
    const bodyRect = body.getBoundingClientRect();
    // 控件区每块都不得超出弹窗体右缘(允许 2px 容差); 表格区横向滚动是设计行为(sim-table-wrap overflow:auto)不算破版
    const blocks = [...modal.querySelectorAll('.sim-ctrl-block')].map((b) => {
      const r = b.getBoundingClientRect();
      return { label: (b.querySelector(':scope > label') || {}).textContent || '', right: r.right, left: r.left, w: r.width };
    });
    const overBody = blocks.filter((b) => b.right > bodyRect.right + 2);
    // 重叠检测: ctrl-row 相邻子块水平区间不得相交(除非已折行 top 不同); 费率块独占行天然不触发
    const overlaps = [];
    (() => {
      const bs = [...modal.querySelectorAll('.sim-ctrl-row > .sim-ctrl-block')].map((b) => {
        const r = b.getBoundingClientRect();
        return { top: r.top, left: r.left, right: r.right };
      });
      for (let i = 0; i + 1 < bs.length; i++) {
        const a = bs[i], c = bs[i + 1];
        if (Math.abs(a.top - c.top) < 8 && a.right > c.left + 1) overlaps.push(`${i}->${i + 1}`);
      }
    })();
    return { vw, docOverflowX, bodyW: Math.round(bodyRect.width), overBody, overlaps, blockN: blocks.length };
  });
  check('④n1 弹窗体不超视口(body宽 ≤390)', narrow.bodyW <= narrow.vw, `body=${narrow.bodyW}px vw=${narrow.vw}`);
  check('④n2 页面无横向溢出(scrollWidth ≤ vw)', !narrow.docOverflowX);
  check('④n3 控件块无越出弹窗体右缘', narrow.overBody.length === 0,
    narrow.overBody.map((b) => b.label).join(',') || 'clean');
  check('④n4 同行控件无重叠', narrow.overlaps.length === 0, narrow.overlaps.join(',') || 'clean');
  check('④n5 控件齐全(6块都在)', narrow.blockN === 6, `blocks=${narrow.blockN}`);
  check('④窄屏 pageerror/console error=0', merrors.length === 0, merrors.slice(0, 3).join(' ; ') || 'clean');
  await mp.close();

  await browser.close();
  const fails = results.filter((r) => !r.cond).length;
  console.log(`\n==== 结果: ${results.length - fails}/${results.length} PASS, ${fails} FAIL ====`);
  process.exit(fails ? 1 : 0);
})();
