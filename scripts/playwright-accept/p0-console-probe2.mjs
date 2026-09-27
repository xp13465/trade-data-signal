// P0 补测探索2: ①全局搜索 142.68/182.25/163.25 文本元素位置 ②切换周期/费率 触发更多 __gih_missing_px_ 缺价报错
import { chromium } from 'playwright';
import fs from 'fs';

const out = { steps: [], gih: [] };
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1680, height: 4000 } });
const page = await ctx.newPage();

page.on('console', (msg) => {
  const t = msg.type();
  if (t === 'error' || t === 'warning') {
    const m = msg.text();
    if (m.includes('__gih_missing_px_')) {
      const mm = m.match(/etf_code=(\S+)\s+buy_date=(\S+)\s+force_date=(\S+)/);
      const key = mm ? `${mm[1]}|${mm[2]}|${mm[3]}` : m;
      if (!out.gih.find(g => g.key === key)) {
        out.gih.push({ key, etf_code: mm?.[1], buy_date: mm?.[2], force_date: mm?.[3], step: out.steps.length });
      }
    }
    out.steps.forEach((s, i) => { if (s) { /* noop */ } });
  }
});
const captured = [];
page.on('console', (msg) => { if (msg.type() === 'error' || msg.type() === 'warning') captured.push({t: msg.type(), text: msg.text()}); });
page.on('pageerror', (e) => captured.push({t: 'pageerror', text: String(e)}));

await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
// 等全信号表渲染
for (let i = 0; i < 60; i++) {
  if (await page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').count() > 0) break;
  await page.waitForTimeout(2000);
}
out.steps.push({ name: 'initial', wait_ms: 0, gih_after: [...out.gih], captured_after: captured.filter(c => c.text.includes('__gih_missing_px_')).length });

// 全局搜索目标数字文本元素
const targets = ['142.68', '182.25', '163.25', '163', '224.92'];
out.text_hits = {};
for (const tgt of targets) {
  out.text_hits[tgt] = [];
  // 用 XPath 搜含该子串的文本节点
  const hits = await page.evaluate((t) => {
    const res = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while (n = walker.nextNode()) {
      if (n.textContent && n.textContent.includes(t)) {
        const el = n.parentElement;
        const cls = el.className ? (typeof el.className === 'string' ? el.className : '') : '';
        const tag = el.tagName;
        // 往上找 3 层 class
        let ctx = [];
        let cur = el;
        for (let i = 0; i < 4 && cur; i++) {
          ctx.push(cur.tagName + (cur.className ? '.' + String(cur.className).split(' ').slice(0,2).join('.') : ''));
          cur = cur.parentElement;
        }
        res.push({ text: n.textContent.trim().slice(0, 120), ctx: ctx.join(' < ') });
      }
    }
    return res.slice(0, 20);
  }, tgt);
  out.text_hits[tgt] = hits;
}

// 切换周期 tabs: 找周期切换按钮(all/y1/y3)
async function clickPeriodAndCapture(label) {
  const before = out.gih.length;
  const btn = page.locator(`.lab-sigkelly-bar button:has-text("${label}")`).first();
  if (await btn.count()) {
    await btn.click().catch(() => {});
    await page.waitForTimeout(3000);
  }
  out.steps.push({ name: 'period_' + label, gih_after: [...out.gih], captured_gih_total: out.gih.length });
}

await clickPeriodAndCapture('全部');
await clickPeriodAndCapture('近1年');
await clickPeriodAndCapture('近3年');
await clickPeriodAndCapture('全部'); // 还原

// 切费率档(如果有)
const feeSel = page.locator('.lab-sigkelly-fee-select, select.lab-sigkelly-fee').first();
if (await feeSel.count()) {
  const opts = await feeSel.locator('option').allTextContents();
  out.fee_options = opts;
  if (opts.length > 1) {
    await feeSel.selectOption({ index: 1 }).catch(() => {});
    await page.waitForTimeout(3000);
    out.steps.push({ name: 'fee_switch', gih_after: [...out.gih], captured_gih_total: out.gih.length });
    await feeSel.selectOption({ index: 0 }).catch(() => {});
    await page.waitForTimeout(3000);
  }
}

out.captured_all = captured;
out.gih_unique = [...out.gih];
out.captured_gih_total = captured.filter(c => c.text.includes('__gih_missing_px_')).length;
out.captured_error_total = captured.filter(c => c.t === 'error').length;
out.captured_warn_total = captured.filter(c => c.t === 'warning').length;
out.captured_pageerror_total = captured.filter(c => c.t === 'pageerror').length;

fs.writeFileSync('/tmp/p0-console/p0-probe2.json', JSON.stringify(out, null, 2));
console.log('== 文本命中 142.68 ==');
console.log(JSON.stringify(out.text_hits['142.68'], null, 1));
console.log('== 文本命中 182.25 ==');
console.log(JSON.stringify(out.text_hits['182.25'], null, 1));
console.log('== 文本命中 163.25 ==');
console.log(JSON.stringify(out.text_hits['163.25'], null, 1));
console.log('== 文本命中 163(前5) ==');
console.log(JSON.stringify(out.text_hits['163'].slice(0,5), null, 1));
console.log('== 文本命中 224.92 ==');
console.log(JSON.stringify(out.text_hits['224.92'], null, 1));
console.log('== 缺价笔数总览 ==');
console.log('gih_unique:', out.gih_unique.length);
console.log('captured_gih_total:', out.captured_gih_total);
console.log('captured_error_total:', out.captured_error_total, 'warn:', out.captured_warn_total, 'pageerror:', out.captured_pageerror_total);
console.log('== steps ==');
console.log(JSON.stringify(out.steps.map(s => ({ name: s.name, gih_after: s.gih_after.length })), null, 1));
await b.close();
