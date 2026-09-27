import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1500, height: 3000 } });
const page = await ctx.newPage();
const logs = [];
let routeHits = 0;
page.on('pageerror', e => logs.push('PAGEERROR=' + String(e).slice(0,500)));
page.on('console', m => { if (m.type() === 'error') logs.push('CONSOLEERR=' + m.text().slice(0,300)); });
page.on('response', r => { if (r.url().includes('signal_kelly_trades_intraday')) { logs.push('RESP=' + r.status() + ' ' + r.url().split('/').pop().split('?')[0]); } });

await page.route('**/signal_kelly_trades_intraday.json*', async route => {
  routeHits++;
  const r = await route.fetch();
  const j = await r.json();
  if (j && j.intraday) {
    const today = new Date();
    const ymd = '' + today.getFullYear() + String(today.getMonth()+1).padStart(2,'0') + String(today.getDate()).padStart(2,'0');
    j.intraday.next_open_date = ymd;
    logs.push('ROUTE MOCK next_open=' + ymd);
  }
  await route.fulfill({ response: r, json: j });
});

await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.waitForTimeout(6000);

// 直接调 window._kellyIntradayFetch 看拿到的数据
const fetched = await page.evaluate(async () => {
  if (typeof window._kellyIntradayFetch === 'function') {
    const d = await window._kellyIntradayFetch();
    return d ? { next_open: d.intraday && d.intraday.next_open_date, mode: d.intraday && d.intraday.mode, rows0: d.quadrants.rating_high.A.length } : 'NULL';
  }
  return 'NO_FN';
});
console.log('fetched:', JSON.stringify(fetched));
console.log('routeHits:', routeHits);

const nRows = await page.evaluate(() => document.querySelectorAll('.lab-sigkelly-trade-row').length);
if (nRows > 0) {
  await page.evaluate(() => { document.querySelector('.lab-sigkelly-trade-row').click(); });
  await page.waitForTimeout(4000);
  const st = await page.evaluate(() => {
    const out = {};
    out.viewExists = document.querySelectorAll('#kelly-intraday-view').length;
    out.anchor = document.querySelectorAll('.lab-sigkelly-intraday-anchor').length;
    return out;
  });
  console.log('after click:', JSON.stringify(st));
}
console.log('errors:', JSON.stringify(logs.filter(l => l.startsWith('PAGEERROR') || l.startsWith('CONSOLEERR'))));
await b.close();
