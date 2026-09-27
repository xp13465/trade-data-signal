import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1500, height: 3000 } });
const page = await ctx.newPage();
const logs = [];
page.on('pageerror', e => logs.push('PAGEERROR=' + String(e).slice(0,600)));
page.on('console', m => { if (m.type() === 'error') logs.push('CONSOLEERR=' + m.text().slice(0,300)); });

await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.waitForTimeout(6000);

// 点一个 .lab-sigkelly-trade-row 打开交易记录弹窗
const rows = await page.evaluate(() => document.querySelectorAll('.lab-sigkelly-trade-row').length);
console.log('trade-rows:', rows);
if (rows > 0) {
  await page.evaluate(() => { document.querySelector('.lab-sigkelly-trade-row').click(); });
  await page.waitForTimeout(4000);
  const st = await page.evaluate(() => {
    const out = {};
    out.modal = !!document.querySelector('.lab-sigkelly-modal');
    out.anchor = document.querySelectorAll('.lab-sigkelly-intraday-anchor').length;
    out.anchorParent = (() => { const a = document.querySelector('.lab-sigkelly-intraday-anchor'); return a ? (a.parentNode ? a.parentNode.className : 'no-parent') : 'no-anchor'; })();
    out.viewExists = document.querySelectorAll('#kelly-intraday-view').length;
    out.anchorNextEl = (() => { const a = document.querySelector('.lab-sigkelly-intraday-anchor'); return a && a.nextElementSibling ? a.nextElementSibling.id || a.nextElementSibling.className : null; })();
    // 弹窗里 html 片段
    const m = document.querySelector('.lab-sigkelly-modal');
    out.modalHtmlSnip = m ? m.outerHTML.slice(0, 1500) : 'none';
    return out;
  });
  console.log(JSON.stringify(st, null, 1));
}
console.log('errors:', JSON.stringify(logs));
await b.close();
