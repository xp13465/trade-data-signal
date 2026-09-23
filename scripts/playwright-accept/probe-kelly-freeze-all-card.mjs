// 页面实测锚点: 首页 lab「全信号表 · 最后结果」卡 A 档真实渲染值(2026-09-23 固化口径调研)
// 独立实测: 无痕浏览器零 localStorage
// 卡面列序(name/半凯利/胜率/盈亏比/?/样本n/净盈亏/峰值资金收益率/最大持仓/最小本金)
// 本脚本: 默认档(etf_main) 与 切 etf_def 档 各实测一次
import { chromium } from 'playwright';
const url = process.env.URL || 'https://ss.fx8.store/#lab?sub=sigkelly';
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({
  userAgent: 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36',
  viewport: { width: 1440, height: 2400 },
});
await ctx.clearCookies();
const page = await ctx.newPage();
page.on('pageerror', e => console.log('[pageerror]', String(e).slice(0, 150)));
const t0 = Date.now();

async function readAK() {
  return await page.evaluate(() => {
    const rows = Array.from(document.querySelectorAll('.lab-sigkelly-all-card .lab-sigkelly-trade-row'));
    const seen = new Set();
    const ak = [];
    for (const r of rows) {
      const tds = Array.from(r.querySelectorAll('td')).map(td => td.textContent.trim());
      if (tds[0] && (tds[0].startsWith('A') || tds[0].startsWith('K'))) {
        const key = tds[0] + '|' + tds[1] + '|' + tds[2] + '|' + tds[3] + '|' + tds[4] + '|' + tds[5] + '|' + tds[6] + '|' + tds[7];
        if (seen.has(key)) continue;
        seen.add(key);
        ak.push({ name: tds[0], halfKelly: tds[1], win: tds[2], pl: tds[3], col4: tds[4], n: tds[5], prof: tds[6], rmh: tds[7], maxConc: tds[8], minCap: tds[9] });
      }
    }
    return ak;
  });
}

async function waitStable(maxPoll, stepMs) {
  let last = null, stable = 0;
  for (let i = 0; i < maxPoll; i++) {
    await page.waitForTimeout(stepMs);
    const ak = await readAK();
    const sig = JSON.stringify(ak);
    if (sig === last) stable++; else { stable = 0; last = sig; }
    if (i % 5 === 0 || stable >= 2) {
      console.log(`[poll ${i}] stable=${stable} rows=${JSON.stringify(ak)} elapsed=${Date.now()-t0}ms`);
    }
    if (stable >= 2 && ak.length > 0) return ak;
  }
  return await readAK();
}

try {
  await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 90000 });
  await page.waitForTimeout(8000);
  await page.evaluate(() => {
    document.querySelectorAll('.onboarding-modal, .rule-modal-overlay, [class*=onboarding]').forEach(el => el.remove());
  });
  // 等 y1 就绪
  for (let i = 0; i < 40; i++) {
    const rows = await page.$$eval('.lab-sigkelly-all-card .lab-sigkelly-trade-row', els => els.length);
    if (rows > 0) break;
    await page.waitForTimeout(2000);
  }
  // 切 all 周期
  await page.evaluate(() => {
    const b = Array.from(document.querySelectorAll('.lab-sigkelly-period-btn')).find(x => x.dataset && x.dataset.period === 'all');
    if (b) b.click();
  });
  console.log('[default-fee] waiting stable...');
  const defRows = await waitStable(40, 3000);
  console.log('[DEFAULT_FEE_FINAL]', JSON.stringify(defRows));

  // 切 etf_def 费率
  await page.evaluate(() => {
    const b = Array.from(document.querySelectorAll('.lab-sigkelly-fee-btn')).find(x => x.dataset && x.dataset.fee === 'etf_def');
    if (b) { b.click(); return 'clicked'; }
    return 'no-btn';
  });
  console.log('[switch etf_def] waiting stable...');
  await page.waitForTimeout(1000);
  const defFeeRows = await waitStable(60, 4000);
  console.log('[ETFDEF_FEE_FINAL]', JSON.stringify(defFeeRows));
} catch (e) {
  console.log('[ERR]', String(e).slice(0, 800));
}
await browser.close();