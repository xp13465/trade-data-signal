'use strict';
const { chromium } = require('playwright');
const fs = require('fs');
const APP_SRC = '/Users/linhuichen/code/trade/.claude/worktrees/sim-price-toggle/static-site/app.js';
let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; console.log('PASS', msg); } else { fail++; console.log('FAIL', msg); } };

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push('CONSOLE: ' + m.text()); });
  await page.route('**/app.min.js**', route => {
    route.fulfill({ status: 200, contentType: 'text/javascript', body: fs.readFileSync(APP_SRC, 'utf8') });
  });
  await page.goto('http://localhost:8517/index.html', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForSelector('.sig-kbtn-sim', { timeout: 30000 });
  await page.waitForTimeout(2500);
  // 移除 onboarding 引导弹窗(否则其 overlay 拦截弹窗内按钮点击)
  await page.evaluate(() => { const m = document.querySelector('.onboarding-modal'); if (m) m.remove(); });
  await page.waitForTimeout(3000);
  await page.evaluate(() => { const m = document.querySelector('.onboarding-modal'); if (m) m.remove(); });

  await page.evaluate(() => { const b = document.querySelector('.sig-kbtn-sim'); if (b) b.click(); });
  await page.waitForSelector('#simBacktestModal:not(.hidden) .sim-table-body table', { timeout: 30000 });

  // ① 双档开关存在、默认次日开盘 active
  const basisN = await page.$$eval('#simBacktestModal .sim-buybasis-btn', els => els.length);
  ok(basisN === 2, '双档开关有 2 个按钮 (' + basisN + ')');
  const nextActive = await page.$eval('#simBacktestModal .sim-buybasis-btn[data-basis="next_day_open"]', el => el.classList.contains('active'));
  ok(nextActive, '默认「次日开盘」按钮 active');

  // ⑤ 表头
  const c1 = await page.$eval('#simBacktestModal .sim-tbl th:nth-child(1)', el => el.textContent.trim());
  ok(c1 === '信号日期', '第1列表头为「信号日期」(实际=' + c1 + ')');
  const c5 = await page.$eval('#simBacktestModal .sim-tbl th:nth-child(5)', el => el.textContent.trim());
  ok(c5 === '计划买入时间', '第5列表头为「计划买入时间」(实际=' + c5 + ')');
  const c1title = await page.$eval('#simBacktestModal .sim-tbl th:nth-child(1)', el => (el.getAttribute('title') || '').includes('信号触发日'));
  ok(c1title, '第1列表头 tooltip 标注信号触发日');

  // ⑥ 表头15 = 行15
  const hc = await page.$eval('#simBacktestModal .sim-tbl thead tr', el => el.querySelectorAll('th').length);
  const rc = await page.$eval('#simBacktestModal .sim-tbl tbody tr', el => el.querySelectorAll('td').length);
  ok(hc === 15 && rc === 15, '表头15列=' + hc + ' 行15列=' + rc);

  // 取消「AI降亏过滤」+ K 切「关」(对账样例 560210 被默认过滤/K=1 选样淘汰, 需 raw 全量人口)
  await page.evaluate(() => {
    const cb = document.querySelector('#simBacktestModal .sim-fade-on-cb');
    if (cb && cb.checked) cb.click();
    const k0 = document.querySelector('#simBacktestModal .sim-kbtn[data-k="0"]');
    if (k0) k0.click();
  });
  await page.waitForFunction(() => {
    const t = document.querySelector('#simBacktestModal .sim-summary');
    return t && t.textContent.indexOf('降亏关') >= 0 && t.textContent.indexOf('K=关') >= 0;
  }, { timeout: 15000 });
  ok(true, '已取消 AI降亏过滤 + K=关(按 raw 全量人口对账)');

  const rowSel = '#simBacktestModal .sim-tbl tbody tr:has(td[data-code="560210"])';
  const rowExists = await page.$(rowSel);
  ok(!!rowExists, '找到对账样例行(560210, 20260903)');
  let readNext = null;
  if (rowExists) {
    readNext = await page.$eval(rowSel, tr => {
      const tds = tr.querySelectorAll('td');
      return {
        col5_sd: tds[4].querySelector('.sim-buytime-sd') ? tds[4].querySelector('.sim-buytime-sd').textContent.trim() : '',
        col5_bd: tds[4].querySelector('.sim-buytime-bd') ? tds[4].querySelector('.sim-buytime-bd').textContent.trim() : '',
        col6_buyprice: tds[5].textContent.trim()
      };
    });
    ok(readNext.col5_sd === '20260903', '次日档计划买入时间上行=信号日期 20260903 (实际=' + readNext.col5_sd + ')');
    ok(readNext.col5_bd !== '20260903' && /^\d{8}$/.test(readNext.col5_bd), '次日档下行=下一交易日(' + readNext.col5_bd + ', 非当天)');
    ok(readNext.col6_buyprice === '0.8341', '次日档买入价=0.8341(对账 0.83413, 实际=' + readNext.col6_buyprice + ')');
  }

  const sumNext = await page.$eval('#simBacktestModal .sim-summary', el => el.textContent.trim());
  const peakNext = await page.$eval('#simBacktestModal .sim-peak-note', el => el.textContent.trim());

  // ② 切「当日收盘」
  await page.evaluate(() => { const b = document.querySelector('#simBacktestModal .sim-buybasis-btn[data-basis="signal_day_close"]'); if (b) b.click(); });
  await page.waitForFunction(() => {
    const btn = document.querySelector('#simBacktestModal .sim-buybasis-btn[data-basis="signal_day_close"]');
    const t = document.querySelector('#simBacktestModal .sim-summary');
    const peak = document.querySelector('#simBacktestModal .sim-peak-note');
    const tbl = document.querySelector('#simBacktestModal .sim-table-body table tbody');
    return btn && btn.classList.contains('active') && !btn.disabled && t && t.textContent.indexOf('筛选结果') >= 0 && peak && tbl && tbl.querySelectorAll('tr').length > 0;
  }, { timeout: 60000 });

  // ③ 汇总/峰值联动
  const sumSdc = await page.$eval('#simBacktestModal .sim-summary', el => el.textContent.trim());
  ok(sumSdc !== sumNext, '切档后汇总文本随口径联动(次日≠当日)');
  const peakSdc = await page.$eval('#simBacktestModal .sim-peak-note', el => el.textContent.trim());
  const smSdc = await page.$eval('#simBacktestModal .sim-summary', el => el.textContent.trim());
  const m1 = peakSdc.match(/持仓\s*(\d+)\s*笔/);
  const m2 = smSdc.replace(/\s+/g, ' ').match(/持仓\s*(\d+)\s*笔/);
  ok(m1 && m2 && m1[1] === m2[1], '切档后峰值说明条随口径重建且与汇总同值(峰值=' + (m1 ? m1[1] : '?') + '笔)');
  const rowExists2 = await page.$(rowSel);
  ok(!!rowExists2, '切档后仍找到对账样例行(560210)');
  if (rowExists2) {
    const r2 = await page.$eval(rowSel, tr => {
      const tds = tr.querySelectorAll('td');
      return {
        col5_bd: tds[4].querySelector('.sim-buytime-bd') ? tds[4].querySelector('.sim-buytime-bd').textContent.trim() : '',
        col6_buyprice: tds[5].textContent.trim()
      };
    });
    ok(r2.col5_bd === '20260903', '当日档下行=信号日当天 20260903 (实际=' + r2.col5_bd + ')');
    ok(r2.col6_buyprice === '0.8371', '当日档买入价=0.8371(对账 0.83714, 实际=' + r2.col6_buyprice + ')');
  }

  // 切回次日开盘(可逆)
  await page.evaluate(() => { const b = document.querySelector('#simBacktestModal .sim-buybasis-btn[data-basis="next_day_open"]'); if (b) b.click(); });
  await page.waitForFunction(() => {
    const btn = document.querySelector('#simBacktestModal .sim-buybasis-btn[data-basis="next_day_open"]');
    const t = document.querySelector('#simBacktestModal .sim-summary');
    const peak = document.querySelector('#simBacktestModal .sim-peak-note');
    const tbl = document.querySelector('#simBacktestModal .sim-table-body table tbody');
    return btn && btn.classList.contains('active') && !btn.disabled && t && t.textContent.indexOf('筛选结果') >= 0 && peak && tbl && tbl.querySelectorAll('tr').length > 0;
  }, { timeout: 60000 });
  ok(true, '切回「次日开盘」按钮恢复 active');

  // ⑦ 独立开关
  const simKey = await page.evaluate(() => localStorage.getItem('tds_sim_buy_basis'));
  const labKey = await page.evaluate(() => localStorage.getItem('lab_sigkelly_buy_basis'));
  ok(simKey === 'next_day_open', 'sim 开关写入独立键 tds_sim_buy_basis=' + simKey);
  ok(labKey === null, 'lab 键 lab_sigkelly_buy_basis 未被 sim 开关触碰(当前=' + labKey + ')');
  await page.evaluate(() => localStorage.setItem('lab_sigkelly_buy_basis', 'signal_day_close'));
  await page.evaluate(() => { const m = document.getElementById('simBacktestModal'); if (m) m.classList.add('hidden'); });
  await page.click('.sig-kbtn-sim');
  await page.waitForSelector('#simBacktestModal:not(.hidden) .sim-table-body table', { timeout: 30000 });
  const nextActiveAfter = await page.$eval('#simBacktestModal .sim-buybasis-btn[data-basis="next_day_open"]', el => el.classList.contains('active'));
  ok(nextActiveAfter, 'lab 键切当日收盘不影响本弹窗(重开后仍默认次日开盘)');

  ok(errors.length === 0, '无 console/page error(' + errors.length + ' 条)' + (errors.length ? ' 首条: ' + errors[0] : ''));

  console.log('\n==== 结果: PASS=' + pass + ' FAIL=' + fail + ' ====');
  await browser.close();
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.log('SCRIPT_ERROR', e.message); process.exit(2); });
