import { chromium } from 'playwright';
const url = process.env.URL || 'https://ss.fx8.store';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
  viewport: { width: 1440, height: 2400 },
});
await ctx.clearCookies();
const page = await ctx.newPage();
page.on('pageerror', e => console.log('[pageerror]', String(e).slice(0,150)));
try {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(4000);
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').includes('策略实验')); if (b) b.click(); });
  await page.waitForTimeout(1200);
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').includes('自定义分析')); if (b) b.click(); });
  await page.waitForTimeout(1200);
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').includes('信号凯利')); if (b) b.click(); });
  console.log('entered sigkelly');
  // 等全信号表出现
  for (let i = 0; i < 90; i++) {
    const has = await page.$$eval('.lab-sigkelly-all-group', els => els.length);
    if (has) break;
    await page.waitForTimeout(2000);
  }
  // 等全量加载就绪: all 周期行出现(非占位/无数据), 且不再有 loading
  let allReady = false;
  for (let i = 0; i < 150; i++) {
    const loading = await page.$$eval('.lab-sigkelly-all-group .lab-sigkelly-all-loading', els => els.length);
    const rows = await page.$$eval('.lab-sigkelly-all-card .lab-sigkelly-trade-row', els => els.length);
    if (loading === 0 && rows > 0) { allReady = true; break; }
    await page.waitForTimeout(2000);
  }
  console.log('y1 default ready=', allReady);
  // 逐周期读完整
  const readAllRows = async () => {
    return await page.evaluate(() => {
      const rows = Array.from(document.querySelectorAll('.lab-sigkelly-all-card .lab-sigkelly-trade-row'));
      const out = [];
      for (const r of rows) {
        const tds = Array.from(r.querySelectorAll('td')).map(td => td.textContent.trim());
        if (!tds[0]) continue;
        out.push({
          mode: tds[0].slice(0, 8),
          n: tds[5] || '', tp: tds[6] || '', rmh: tds[7] || '',
          mc: tds[9] || '', ann: tds[11] || ''
        });
      }
      return out;
    });
  };
  const headNote = async () => await page.$eval('.lab-sigkelly-all-group', g => (g.querySelector('.lab-custom-loading, .lab-sigkelly-all-loading, .lab-sigkelly-all-empty') || {}).textContent || '')
    .catch(() => '');
  const periods = ['all','y10','y5','y3','y1'];
  for (const p of periods) {
    await page.evaluate((pp) => {
      const b = Array.from(document.querySelectorAll('.lab-sigkelly-period-btn')).find(x => x.dataset.period === pp);
      if (b) b.click();
    }, p);
    // all 周期可能需长等待
    await page.waitForTimeout(2500);
    const note = await headNote();
    const rows = await readAllRows();
    console.log(`===== period=${p}  note="${note}" rows=${rows.length} =====`);
    for (const r of rows) {
      console.log(`  ${r.mode.padEnd(8)} n=${r.n.padEnd(5)} tp=${r.tp.padEnd(11)} rmh=${r.rmh.padEnd(9)} mc=${r.mc.padEnd(12)} ann=${r.ann}`);
    }
  }
} catch(e) { console.log('ERR', String(e).slice(0,600)); }
await browser.close();
