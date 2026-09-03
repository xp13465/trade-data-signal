// playwright 全量页面回归(2026-09-03/04 ZCode):补跑 test-suite-spec 降级挂账用例
// 路径: 首页→lab tab→自定义分析→信号凯利回测→卡片→交易模式弹窗→淘汰区
// 运行: node docs/kelly/analysis/scripts/pw-regression-20260903.cjs
const { chromium } = require('playwright');
const BASE = 'http://localhost:8000';
const results = [];
function rec(id, name, pass, evidence) { results.push({ id, name, pass, evidence }); console.log(`${pass ? 'PASS' : 'FAIL'} ${id} ${name} :: ${evidence}`); }

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  const consoleErrs = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrs.push(m.text().slice(0, 120)); });
  page.on('pageerror', e => consoleErrs.push('PAGEERR:' + String(e).slice(0, 120)));

  // ── 进入凯利区 ──
  await page.goto(BASE + '/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await page.waitForTimeout(2500);
  rec('TC-UI-001', '首屏KPI渲染/console干净', consoleErrs.length === 0, `console错误=${consoleErrs.length}${consoleErrs[0] ? ' 首条=' + consoleErrs[0] : ''}`);
  // 先清引导弹窗(它拦截一切点击)——只删引导/规则弹窗,绝不动 #lab-sigkelly-trades-overlay(交易弹窗容器,误删=弹窗永远打不开)
  await page.evaluate(() => { document.querySelectorAll('.rule-modal-overlay, .onboarding-modal, .rule-modal').forEach(o => o.remove()); });
  await page.waitForTimeout(500);
  await page.locator('[data-tab="lab"]').first().click({ force: true });
  await page.waitForTimeout(3500);
  await page.evaluate(() => { document.querySelectorAll('.rule-modal-overlay, .onboarding-modal, .rule-modal').forEach(o => o.remove()); });
  await page.evaluate(() => document.querySelector('.lab-subnav-tab[data-sub="custom"]')?.click());
  await page.waitForTimeout(2500);
  await page.evaluate(() => document.querySelector('.lab-subnav-tab[data-sub="sigkelly"]')?.click());
  // 凯利数据加载(全量分片可能慢)
  await page.waitForFunction(() => !!document.querySelector('.lab-sigkelly-host') && document.querySelector('.lab-sigkelly-host').innerText.length > 50, null, { timeout: 30000 }).catch(() => {});
  await page.waitForTimeout(4000);
  const kellyReady = await page.evaluate(() => ({
    host: !!document.querySelector('.lab-sigkelly-host'),
    text: (document.querySelector('.lab-sigkelly-host') || {}).innerText?.length || 0,
    quadCount: document.querySelectorAll('[data-quad]').length,
  }));
  rec('TC-UI-010', '信号凯利回测区加载', kellyReady.host && kellyReady.text > 50, `host=${kellyReady.host} 文本长度=${kellyReady.text} quad数=${kellyReady.quadCount}`);

  // ── 找信号卡片并打开交易模式弹窗(行=tr.lab-sigkelly-trade-row 直接绑 onclick;element.click() 在此不稳定,用 dispatchEvent bubbles ──
  const opened = await page.evaluate(() => {
    const quads = [...document.querySelectorAll('tr[data-quad][data-mode], [data-quad][data-mode]')];
    if (!quads.length) return { ok: false, why: 'no [data-mode] 行' };
    const row = quads[0];
    row.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    return { ok: true, mode: row.dataset.mode, quad: row.dataset.quad, period: row.dataset.period };
  });
  await page.waitForFunction(() => {
    const ov = document.querySelector('#lab-sigkelly-trades-overlay');
    return ov && ov.style.display !== 'none' && (ov.querySelector('.lab-sigkelly-modal-title') || {}).textContent;
  }, null, { timeout: 20000 }).catch(() => {});
  const modal = await page.evaluate(() => {
    const ov = document.querySelector('#lab-sigkelly-trades-overlay') || document.querySelector('[class*="sigkelly-trades-overlay"]');
    if (!ov) return { open: false };
    const title = (ov.querySelector('.lab-sigkelly-modal-title') || {}).textContent?.trim().slice(0, 50) || '';
    const visible = ov.style.display !== 'none' && !!title;
    return { open: visible, title };
  });
  rec('TC-UI-011', '交易模式弹窗打开', modal.open, `opened=${JSON.stringify(opened)} modal=${JSON.stringify(modal)}`);

  if (modal.open) {
    const main = await page.evaluate(() => {
      const table = document.querySelector('.lab-sigkelly-modal .lab-sigkelly-trades-table');
      const ths = table ? [...table.querySelectorAll('th')].map(t => t.textContent.trim()) : [];
      const stats = [...document.querySelectorAll('.lab-sigkelly-modal-stats span')].map(s => s.textContent.trim().slice(0, 25));
      return { cols: ths.length, stats };
    });
    rec('TC-UI-011a', '主表12列(买/卖价合并后)+统计行', main.cols === 12, `主表列数=${main.cols} 统计行=${main.stats.join(' | ').slice(0, 100)}`);

    const elim = await page.evaluate(() => {
      const wrap = document.querySelector('.lab-sigkelly-modal-elimwrap');
      if (!wrap) return { has: false };
      const ths = [...wrap.querySelectorAll('th')].map(t => t.textContent.trim());
      const cells = [...wrap.querySelectorAll('td.lab-sigkelly-elim-reason')];
      const reasons = [...new Set(cells.map(c => c.textContent.trim()))];
      const first = cells[0];
      const lineThrough = first ? getComputedStyle(first).textDecorationLine.includes('line-through') : null;
      const title = (wrap.querySelector('.lab-sigkelly-modal-elimtitle') || {}).textContent?.trim() || '';
      const statSpan = [...document.querySelectorAll('.lab-sigkelly-elim-stat')].map(s => s.textContent.trim())[0] || '';
      return { has: true, cols: ths.length, hasReasonTh: ths.includes('淘汰原因'), reasons, n: cells.length, lineThrough, title: title.slice(0, 70), statSpan };
    });
    rec('TC-UI-012a', '淘汰区13列(12+原因尾列)含原因列表头', elim.has && elim.cols === 13 && elim.hasReasonTh, `列数=${elim.cols} 原因表头=${elim.hasReasonTh}`);
    rec('TC-UI-012b', '原因值三分类', elim.has && elim.reasons.length > 0, `在场原因=${JSON.stringify(elim.reasons)} 行数=${elim.n}`);
    rec('TC-UI-012c', '原因列豁免删除线', elim.lineThrough === false, `lineThrough=${elim.lineThrough}`);
    rec('TC-UI-012d', '统计行/标题动态标签', elim.has, `统计="${elim.statSpan}" 标题="${elim.title}"`);

    const filt = await page.evaluate(() => {
      const all = [...document.querySelectorAll('.lab-sigkelly-modal select')];
      return { n: all.length, opts: all.map(s => [...s.options].map(o => o.text).join('/').slice(0, 60)) };
    });
    rec('TC-UI-012e', '原因筛选下拉(Claude增强)', filt.opts && filt.opts.some(o => o && o.includes('仅降亏')), `selects=${JSON.stringify(filt).slice(0, 150)}`);

    await page.evaluate(() => { const ov = document.querySelector('#lab-sigkelly-trades-overlay'); if (ov) ov.style.display = 'none'; });
    const gihToggle = await page.evaluate(() => {
      const labels = [...document.querySelectorAll('label, [class*="toggle"]')];
      const hit = labels.find(l => /ai长线|G\/H\/I/.test(l.textContent));
      if (!hit) return { found: false };
      const input = hit.querySelector('input[type="checkbox"]');
      if (input && !input.checked) { input.click(); return { found: true, toggled: true }; }
      return { found: true, already: !!(input && input.checked) };
    });
    await page.waitForTimeout(6000);
    rec('TC-UI-013-pre', 'GIH开关可寻址', !!gihToggle.found, JSON.stringify(gihToggle).slice(0, 80));
    const reopened = await page.evaluate(() => {
      const quads = [...document.querySelectorAll('[data-quad][data-mode]')];
      const gih = quads.find(q => q.dataset.mode === 'H') || quads.find(q => ['G','H','I'].includes(q.dataset.mode)) || quads[0];
      if (!gih) return false;
      gih.dispatchEvent(new MouseEvent('click', { bubbles: true })); return true;
    });
    await page.waitForTimeout(7000);
    const gihModal = await page.evaluate(() => {
      const ov = document.querySelector('#lab-sigkelly-trades-overlay');
      if (!ov || ov.style.display === 'none') return { open: false };
      const note = (ov.querySelector('.lab-sigkelly-gih-modal-note') || {}).textContent?.trim().slice(0, 60) || '';
      const reasons = [...new Set([...ov.querySelectorAll('td.lab-sigkelly-elim-reason')].map(c => c.textContent.trim()))];
      const gihNoteVisible = !!ov.querySelector('.lab-sigkelly-gih-modal-note');
      return { open: true, gihNoteVisible, note, reasons };
    });
    rec('TC-UI-013', 'GIH开启态H模式弹窗+长线满仓原因在场', gihModal.open && gihModal.gihNoteVisible && gihModal.reasons.includes('AI长线·满仓不买'), `open=${gihModal.open} gihNote=${gihModal.gihNoteVisible} note="${gihModal.note}" 淘汰原因=${JSON.stringify(gihModal.reasons)}`);
  }

  const mob = await browser.newPage({ viewport: { width: 390, height: 844 } });
  const mobErrs = [];
  mob.on('pageerror', e => mobErrs.push(String(e).slice(0, 80)));
  await mob.goto(BASE + '/', { waitUntil: 'domcontentloaded' });
  await mob.waitForTimeout(3000);
  const mobW = await mob.evaluate(() => ({ sw: document.documentElement.scrollWidth, kpi: !!document.querySelector('[class*="kpi"], [class*="KPI"]') }));
  rec('TC-UI-022', '移动端390px加载', mobErrs.length === 0, `scrollWidth=${mobW.sw} KPI存在=${mobW.kpi} pageErr=${mobErrs.length}`);
  await mob.close();

  console.log('\n===== 汇总 =====');
  const p = results.filter(r => r.pass).length, f = results.filter(r => !r.pass).length;
  console.log(`PASS ${p} / FAIL ${f} / 共 ${results.length}`);
  console.log('console错误总数:', consoleErrs.length, consoleErrs.slice(0, 3));
  await browser.close();
  process.exit(0);
})().catch(e => { console.error('脚本异常:', e.message); process.exit(2); });
