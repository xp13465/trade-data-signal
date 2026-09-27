import { chromium } from 'playwright';
const url = process.env.URL || 'https://ss.fx8.store';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
  viewport: { width: 1440, height: 2400 },
});
await ctx.clearCookies();
const page = await ctx.newPage();
page.on('pageerror', e => console.log('[pageerror]', String(e).slice(0,120)));
try {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(4000);
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').includes('策略实验')); if (b) b.click(); });
  await page.waitForTimeout(1200);
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').includes('自定义分析')); if (b) b.click(); });
  await page.waitForTimeout(1200);
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').includes('信号凯利')); if (b) b.click(); });
  // 等 y1 就绪
  for (let i = 0; i < 90; i++) {
    const rows = await page.$$eval('.lab-sigkelly-all-card .lab-sigkelly-trade-row', els => els.length);
    if (rows > 0) break;
    await page.waitForTimeout(2000);
  }
  console.log('y1 ready');
  // 切到 all, 并观察
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('.lab-sigkelly-period-btn')).find(x => x.dataset.period === 'all'); if (b) b.click(); });
  // 等 5s, 10s, 30s 各读一次
  for (const wait of [3000, 7000, 20000]) {
    await page.waitForTimeout(wait);
    const info = await page.evaluate(() => {
      const g = document.querySelector('.lab-sigkelly-all-group');
      const loading = (g && g.querySelector('.lab-sigkelly-all-loading, .lab-custom-loading')) || null;
      const rows = Array.from(g ? g.querySelectorAll('.lab-sigkelly-all-card .lab-sigkelly-trade-row') : []);
      const ak = [];
      for (const r of rows) {
        const tds = Array.from(r.querySelectorAll('td')).map(td => td.textContent.trim());
        if (tds[0] && (tds[0].startsWith('A') || tds[0].startsWith('K'))) ak.push({ m: tds[0].slice(0,3), n: tds[5], tp: tds[6], rmh: tds[7] });
      }
      return { loading: loading ? loading.textContent.trim().slice(0,80) : null, ak };
    });
    console.log(`after ${wait}ms: loading="${info.loading}" A/K:`, JSON.stringify(info.ak));
  }
  // 最后切回 y10 对比
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('.lab-sigkelly-period-btn')).find(x => x.dataset.period === 'y10'); if (b) b.click(); });
  await page.waitForTimeout(1500);
  const y10 = await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('.lab-sigkelly-all-card .lab-sigkelly-trade-row'));
    const ak = [];
    for (const r of rows) { const tds = Array.from(r.querySelectorAll('td')).map(td=>td.textContent.trim()); if (tds[0] && (tds[0].startsWith('A')||tds[0].startsWith('K'))) ak.push({m:tds[0].slice(0,3),n:tds[5],tp:tds[6],rmh:tds[7]}); }
    return ak;
  });
  console.log('y10:', JSON.stringify(y10));
} catch(e) { console.log('ERR', String(e).slice(0,400)); }
await browser.close();
