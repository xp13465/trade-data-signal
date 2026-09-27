import { chromium } from 'playwright';
const url = process.env.URL || 'https://ss.fx8.store';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36',
  viewport: { width: 1440, height: 2400 },
});
// 零 localStorage 无痕
await ctx.clearCookies();
const page = await ctx.newPage();
page.on('pageerror', e => console.log('[pageerror]', String(e).slice(0,200)));
try {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(4000);
  // 策略实验
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').includes('策略实验')); if (b) b.click(); });
  await page.waitForTimeout(1500);
  // 自定义分析
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').includes('自定义分析')); if (b) b.click(); });
  await page.waitForTimeout(1500);
  // 信号凯利回测
  await page.evaluate(() => { const b = Array.from(document.querySelectorAll('button')).find(x => (x.textContent||'').includes('信号凯利')); if (b) b.click(); });
  console.log('clicked 信号凯利回测');
  await page.waitForTimeout(4000);
  // 等待全信号表出现
  let ok = false;
  for (let i = 0; i < 60; i++) {
    const has = await page.$$eval('.lab-sigkelly-all-group', els => els.length);
    if (has) { ok = true; break; }
    await page.waitForTimeout(2000);
  }
  console.log('all-group appeared =', ok);
  const barInfo = await page.$$eval('.lab-sigkelly-period-btn', els => els.map(e => (e.dataset.period||'')+':'+(e.textContent||'').trim()+(e.classList.contains('active')?'[active]':'')));
  console.log('period buttons:', JSON.stringify(barInfo));
  // 等计算完成: 占位消失
  for (let i = 0; i < 90; i++) {
    const loading = await page.$$eval('.lab-sigkelly-all-group .lab-custom-loading, .lab-sigkelly-all-group .lab-sigkelly-all-loading', els => els.length);
    const rows = await page.$$eval('.lab-sigkelly-all-card .lab-sigkelly-trade-row', els => els.length);
    if (loading === 0 && rows > 0) break;
    await page.waitForTimeout(2000);
  }
  // 读取当前周期全信号表 A/K 行
  const readRows = async (period) => {
    const res = await page.evaluate((p) => {
      const rows = Array.from(document.querySelectorAll('.lab-sigkelly-all-card .lab-sigkelly-trade-row'));
      const out = [];
      for (const r of rows) {
        const tds = Array.from(r.querySelectorAll('td')).map(td => td.textContent.trim());
        const mode = tds[0] || '';
        if (mode.startsWith('A') || mode.startsWith('K')) {
          out.push({ mode: mode.slice(0,3), row: tds.join(' | ') });
        }
      }
      return { period: p, rows: out };
    }, period);
    return res;
  };
  const periods = ['all','y10','y5','y3','y1'];
  for (const p of periods) {
    await page.evaluate((pp) => {
      const b = Array.from(document.querySelectorAll('.lab-sigkelly-period-btn')).find(x => x.dataset.period === pp);
      if (b) b.click();
    }, p);
    // 等 300ms 渲染 + 若占位等待
    await page.waitForTimeout(1200);
    const r = await readRows(p);
    console.log(`--- period=${r.period} ---`);
    for (const row of r.rows) console.log('  ' + row.mode + ': ' + row.row);
    // 也读卡内 n / 峰值资金
  }
  // 额外: 读回测口径说明
  const desc = await page.$eval('.lab-sigkelly-all-desc', e => e.textContent.trim().slice(0,300)).catch(() => 'N/A');
  console.log('desc:', desc);
} catch(e) { console.log('ERR', String(e).slice(0,800)); }
await browser.close();
