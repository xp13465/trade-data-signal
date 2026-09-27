// 移动端四档卡高度测量(线上数据 + 本地 CSS 拦截)
// 用法: node /tmp/measure-tier-card-static.mjs <CssFileAbs> [width...] [--out <json>]
// 用线上 ss.fx8.store 数据,route.fulfill 拦截所有 .css 请求替换为本地文件(改动前后同口径对比)
import { chromium } from 'playwright';
import fs from 'node:fs';

const CSS_FILE = process.argv[2];
const CONSOLE_OUT = [];
const args = process.argv.slice(3);
let outPath = null;
const widths = [];
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--out') { outPath = args[i + 1]; i++; continue; }
  const n = parseInt(args[i], 10);
  if (!isNaN(n)) widths.push(n);
}
if (!widths.length) widths.push(375, 390, 414, 1280);

const SITE = 'https://ss.fx8.store/';
const UA_IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';
const UA_DESKTOP = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15';
const UA = (w) => (w <= 768 ? UA_IPHONE : UA_DESKTOP);

const b = await chromium.launch({ headless: true });

async function waitRender(page, sel, tries = 60) {
  for (let i = 0; i < tries; i++) {
    if (await page.locator(sel).count().catch(() => 0) > 0) return true;
    await page.waitForTimeout(500);
  }
  return false;
}

async function measure(width) {
  const ctx = await b.newContext({
    viewport: { width, height: 844 },
    deviceScaleFactor: 2,
    isMobile: width <= 768,
    hasTouch: width <= 768,
    userAgent: UA(width),
    serviceWorkers: 'block',
  });
  const page = await ctx.newPage();
  page.on('console', (msg) => {
    const t = msg.type();
    if (t === 'error') CONSOLE_OUT.push({ w: width, type: t, text: msg.text().slice(0, 300) });
  });
  page.on('pageerror', (e) => CONSOLE_OUT.push({ w: width, type: 'pageerror', text: String(e).slice(0, 300) }));

  // 拦截所有 .css → local
  await ctx.route(/\.css(\?.*)?$/, (route) =>
    route.fulfill({ path: CSS_FILE, contentType: 'text/css' }));

  let r = { width, found: false, errors: [] };
  try {
    await page.goto(SITE, { waitUntil: 'domcontentloaded', timeout: 120000 });
    // 关 onboarding
    await page.evaluate(() => {
      const skip = document.querySelector('.onboarding-skip');
      if (skip) skip.click();
    }).catch(() => {});
    const ok = await waitRender(page, '.card.kpi.tier-card');
    r.found = ok;
    if (ok) {
      await page.waitForTimeout(1500);
      r = await page.evaluate(() => {
        const tier = document.querySelector('.card.kpi.tier-card');
        const cards = [...document.querySelectorAll('.cards.kpi-row .card.kpi')];
        const tierIdx = cards.indexOf(tier);
        // 相邻 KPI = tier 之后的第一个非 tier-card
        let kpi = null;
        for (let i = tierIdx + 1; i < cards.length; i++) { if (!cards[i].classList.contains('tier-card')) { kpi = cards[i]; break; } }
        const tt = tier.querySelector('.tier-tooltip');
        const tierR = tier.getBoundingClientRect();
        const kpiR = kpi ? kpi.getBoundingClientRect() : null;
        const sameRow = kpi ? (Math.abs(tierR.top - kpiR.top) < 2) : null;
        const rowStyle = getComputedStyle(document.querySelector('.cards.kpi-row'));
        return {
          width: window.innerWidth,
          tierH: tierR.height, tierW: tierR.width, tierTop: tierR.top,
          tierClientH: tier.clientHeight,
          tierRows: getComputedStyle(tier, null).display === 'flex' ? tier.querySelectorAll('.tier-detail-row').length : 0,
          kpiH: kpiR ? kpiR.height : null, kpiW: kpiR ? kpiR.width : null, kpiTop: kpiR ? kpiR.top : null,
          sameRow,
          kpiRowDisplay: rowStyle.display,
          kpiRowWrap: rowStyle.flexWrap,
          kpiRowAlign: rowStyle.alignItems,
          tooltipScrollH: tt.scrollHeight,
          tooltipClientH: tt.clientHeight,
          tooltipOverflow: getComputedStyle(tt).overflow,
          tooltipHidden: getComputedStyle(tt).visibility,
          cutBy: tt.scrollHeight - tt.clientHeight, // >0 = 被裁
          detailRows: [...tt.querySelectorAll('.tier-detail-row')].map((r) => r.getBoundingClientRect().height),
        };
      });
    }
  } catch (e) {
    r.errors.push(String(e).slice(0, 300));
  } finally {
    await ctx.close();
  }
  return r;
}

const out = { css: CSS_FILE, ts: new Date().toISOString(), results: [], console: CONSOLE_OUT };
for (const w of widths) out.results.push(await measure(w));
const final = JSON.stringify(out, null, 2);
if (outPath) fs.writeFileSync(outPath, final);
console.log(final);
await b.close();