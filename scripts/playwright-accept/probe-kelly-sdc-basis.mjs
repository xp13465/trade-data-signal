// 买入口径=当日收盘(signal_day_close)的实测, 对比默认次日开盘(2026-09-23 固化口径调研)
import { chromium } from 'playwright';
const url = process.env.URL || 'https://ss.fx8.store/#lab?sub=sigkelly';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36',
  viewport: { width: 1440, height: 2400 },
});
await ctx.clearCookies();
const page = await ctx.newPage();
async function readAK() {
  return await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('.lab-sigkelly-all-card .lab-sigkelly-trade-row'));
    const seen = new Set();
    const ak = [];
    for (const r of rows) {
      const tds = Array.from(r.querySelectorAll('td')).map(td => td.textContent.trim());
      if (tds[0] && (tds[0].startsWith('A') || tds[0].startsWith('K'))) {
        const key = tds.join('|');
        if (seen.has(key)) continue;
        seen.add(key);
        ak.push({ name: tds[0], c1: tds[1], c2: tds[2], c3: tds[3], c4: tds[4], n: tds[5], prof: tds[6], rmh: tds[7], maxConc: tds[8], minCap: tds[9] });
      }
    }
    return ak;
  });
}
await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
await page.waitForTimeout(8000);
await page.evaluate(() => {
  document.querySelectorAll('.onboarding-modal, .rule-modal-overlay, [class*=onboarding]').forEach(el => el.remove());
});
// 切当日收盘
const clicked = await page.evaluate(() => {
  const b = Array.from(document.querySelectorAll('.lab-sigkelly-buybasis-btn')).find(x => x.dataset && x.dataset.basis === 'signal_day_close');
  if (b) { b.click(); return true; }
  return false;
});
console.log('[sdc-btn-clicked]', clicked);
// 切换会清空数据整区重建, 等重新加载
let ready = false;
for (let i = 0; i < 60; i++) {
  const rows = await page.$$eval('.lab-sigkelly-all-card .lab-sigkelly-trade-row', els => els.length);
  if (rows > 0) { ready = true; break; }
  await page.waitForTimeout(2500);
}
console.log('[sdc-reloaded]', ready);
// 切 all 周期
await page.evaluate(() => {
  const b = Array.from(document.querySelectorAll('.lab-sigkelly-period-btn')).find(x => x.dataset && x.dataset.period === 'all');
  if (b) b.click();
});
let last = null, stable = 0, fin = null;
for (let i = 0; i < 60; i++) {
  await page.waitForTimeout(4000);
  const ak = await readAK();
  const sig = JSON.stringify(ak);
  if (sig === last) stable++; else { stable = 0; last = sig; }
  if (!fin && stable >= 2 && ak.length > 0) { fin = ak; console.log('[SDC_FINAL]', JSON.stringify(ak)); break; }
}
if (!fin) console.log('[SDC_NO_STABLE]', JSON.stringify(await readAK()));
await browser.close();