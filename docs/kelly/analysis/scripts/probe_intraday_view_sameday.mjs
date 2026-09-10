// 覆写 Date → 让页面认为今天是 2026-09-09（与产物 next_open_date=20260909 同日），验证渲染链路
import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1500, height: 3000 } });
const page = await ctx.newPage();
const logs = [];
page.on('pageerror', e => logs.push('PAGEERROR=' + String(e).slice(0,500)));
page.on('console', m => { if (m.type() === 'error') logs.push('CONSOLEERR=' + m.text().slice(0,300)); });

await page.addInitScript(() => {
  const RealDate = Date;
  const FIXED = new RealDate('2026-09-09T10:00:00+08:00');
  class MockDate extends RealDate {
    constructor(...args) { if (args.length === 0) super(FIXED.getTime()); else super(...args); }
    static now() { return FIXED.getTime(); }
    static parse(s) { return RealDate.parse(s); }
    static UTC(...a) { return RealDate.UTC(...a); }
  }
  window.Date = MockDate;
});

await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.waitForTimeout(6000);

const nRows = await page.evaluate(() => document.querySelectorAll('.lab-sigkelly-trade-row').length);
console.log('trade-rows:', nRows);
if (nRows > 0) {
  await page.evaluate(() => { document.querySelector('.lab-sigkelly-trade-row').click(); });
  await page.waitForTimeout(4000);
  const st = await page.evaluate(() => {
    const out = {};
    out.viewExists = document.querySelectorAll('#kelly-intraday-view').length;
    const v = document.querySelector('#kelly-intraday-view');
    out.viewNote = v ? (v.querySelector('.kelly-intraday-note')?.textContent || '').trim().slice(0,150) : null;
    out.tblRows = v ? v.querySelectorAll('.sim-intraday-tbl tbody tr').length : null;
    out.rect = v ? (() => { const r = v.getBoundingClientRect(); return { h: Math.round(r.height), sh: v.scrollHeight, sw: v.scrollWidth, cw: r.width }; })() : null;
    out.scrollbarY = v ? v.scrollHeight > v.clientHeight : null;
    return out;
  });
  console.log(JSON.stringify(st, null, 1));
}
console.log('errors:', JSON.stringify(logs.filter(l => l.startsWith('PAGEERROR') || l.startsWith('CONSOLEERR'))));
await b.close();
