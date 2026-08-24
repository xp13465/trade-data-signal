#!/usr/bin/env node
/**
 * sim_modal_baseline_probe.js — 「模拟回测」弹窗默认态探针(§23.7 一致性 A/B 对比用, 2026-08-24)
 *
 * 目的: 分别对本 feat 分支构建与现版 main 构建各跑一次, 输出默认打开状态 JSON(摘要/行数/首行内容/
 *       控件默认值), 两份输出逐项 diff 一致 = 只动布局不动行为(§22 用户视角一致性)。
 *
 * 用法: node sim_modal_baseline_probe.js <URL>   # 需先 python3 -m http.server -d <static-site>
 */
'use strict';
const { chromium } = require('playwright');
const URL = process.argv[2] || 'http://localhost:8137';

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 2400 } });
  await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(6000);
  await page.evaluate(() => {
    document.querySelectorAll('.rule-modal .rule-modal-close').forEach((b) => b.click());
    document.querySelectorAll('.rule-modal').forEach((m) => m.classList.add('hidden'));
    document.querySelectorAll('.rule-modal-overlay').forEach((o) => o.remove());
    try { localStorage.clear(); } catch (e) {}   // 清记忆体, 保证两边都走纯默认路径
  });
  await page.click('.sig-kbtn-sim');
  // 等数据加载完成(loading 收起 + summary 有值), 上限 90s(64MB)
  await page.waitForFunction(() => {
    const m = document.getElementById('simBacktestModal');
    if (!m) return false;
    const loading = m.querySelector('.sim-table-loading');
    const summary = m.querySelector('.sim-summary');
    return loading && loading.style.display === 'none' && summary && (summary.textContent || '').trim().length > 0;
  }, { timeout: 90000 });
  await page.waitForTimeout(500);
  const out = await page.evaluate(() => {
    const m = document.getElementById('simBacktestModal');
    const firstRow = m.querySelector('.sim-table-body tbody tr');
    return {
      summaryText: (m.querySelector('.sim-summary').textContent || '').replace(/\s+/g, ' ').trim(),
      rowCount: m.querySelectorAll('.sim-table-body tbody tr').length,
      colCount: m.querySelectorAll('.sim-table-body thead th').length,
      firstRowText: firstRow ? [...firstRow.cells].map((c) => c.textContent.trim()).join(' | ') : '',
      pagerText: (m.querySelector('.sim-pager').textContent || '').replace(/\s+/g, ' ').trim(),
      defaults: {
        start: m.querySelector('.sim-date-start').value,
        end: m.querySelector('.sim-date-end').value,
        fadeMode: (document.querySelector('#sim-fade-mode-sel') || {}).value || null,
        kActive: (m.querySelector('.sim-kbtn.active') || {}).dataset ? m.querySelector('.sim-kbtn.active').dataset.k : null,
        sellMode: m.querySelector('.sim-mode-sel').value,
        feeActive: ((m.querySelector('.simbt-fee-btn.active') || {}).dataset || {}).fee || null,
      },
    };
  });
  console.log(JSON.stringify(out, null, 2));
  await browser.close();
})();
