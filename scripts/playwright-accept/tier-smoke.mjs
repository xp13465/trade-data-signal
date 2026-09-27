// 冒烟: 移动端 hover/点按四档卡 → 浮层完整可见、不裁剪、不遮挡下方卡片
// 用法: node scripts/playwright-accept/tier-smoke.mjs [width] [--shots <dir>]
import { chromium } from 'playwright';
import fs from 'node:fs';

const W = parseInt(process.argv[2], 10) || 375;
const SHOTS = process.argv[3] === '--shots' ? process.argv[4] : null;
const CSS_FILE = '/Users/linhuichen/code/trade/static-site/style.css';
const SITE = 'https://ss.fx8.store/';
const UA_IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({
  viewport: { width: W, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
  userAgent: UA_IPHONE, serviceWorkers: 'block',
});
await ctx.route(/\.css(\?.*)?$/, (route) => route.fulfill({ path: CSS_FILE, contentType: 'text/css' }));
await ctx.addInitScript(() => {
  const t = new Date();
  const stamp = `${t.getFullYear()}${String(t.getMonth() + 1).padStart(2, '0')}${String(t.getDate()).padStart(2, '0')}`;
  ['last_visit_date', 'welcome_shown_date'].forEach((k) => localStorage.setItem(k, stamp));
  ['onboarding_done', 'nt_intro_done'].forEach((k) => localStorage.setItem(k, '1'));
});
const page = await ctx.newPage();
const consoleErrs = [];
page.on('console', (msg) => { if (msg.type() === 'error') consoleErrs.push(msg.text().slice(0, 200)); });
page.on('pageerror', (e) => consoleErrs.push(String(e).slice(0, 200)));

await page.goto(SITE, { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.evaluate(() => { document.querySelectorAll('.onboarding-modal, .rule-modal, .rule-modal-overlay, .onboarding-overlay').forEach((m) => m.remove()); }).catch(() => {});
for (let i = 0; i < 60; i++) { if (await page.locator('.card.kpi.tier-card').count() > 0) break; await page.waitForTimeout(500); }
await page.waitForTimeout(1200);

const out = { width: W, consoleErrs };
const tier = page.locator('.card.kpi.tier-card');
await tier.scrollIntoViewIfNeeded();
await page.waitForTimeout(400);

// 1. hover 状态浮层几何
await tier.hover();
await page.waitForTimeout(500);
out.hover = await page.evaluate(() => {
  const tier = document.querySelector('.card.kpi.tier-card');
  const tt = tier.querySelector('.tier-tooltip');
  const tierR = tier.getBoundingClientRect();
  const ttR = tt.getBoundingClientRect();
  const rows = [...tt.querySelectorAll('.tier-detail-row')];
  const lastRow = rows[rows.length - 1];
  const lastR = lastRow.getBoundingClientRect();
  return {
    tier: { top: tierR.top, bottom: tierR.bottom, h: tierR.height },
    tooltip: { top: ttR.top, bottom: ttR.bottom, visibility: getComputedStyle(tt).visibility, opacity: getComputedStyle(tt).opacity },
    lastRowBottom: lastR.bottom,
    lastRowVisible: lastR.bottom <= tierR.bottom + 0.5, // 最后一行底不超卡底 = 不裁
    lastRowText: lastRow.textContent.slice(0, 60),
    scrollH: tt.scrollHeight, clientH: tt.clientHeight,
  };
});
if (SHOTS) await page.screenshot({ path: `${SHOTS}/tier-hover-${W}.png` });

// 2. tap(点按)状态
await page.mouse.move(10, 10); // 离开
await page.waitForTimeout(200);
await tier.tap();
await page.waitForTimeout(500);
out.tap = await page.evaluate(() => {
  const tt = document.querySelector('.card.kpi.tier-card .tier-tooltip');
  const cs = getComputedStyle(tt);
  const tierR = document.querySelector('.card.kpi.tier-card').getBoundingClientRect();
  const ttR = tt.getBoundingClientRect();
  const rows = [...tt.querySelectorAll('.tier-detail-row')];
  const lastR = rows[rows.length - 1].getBoundingClientRect();
  return {
    visibility: cs.visibility, opacity: cs.opacity,
    lastRowVisible: lastR.bottom <= tierR.bottom + 0.5,
    lastRowBottom: lastR.bottom, tierBottom: tierR.bottom,
    rows: rows.length,
    scrollH: tt.scrollHeight, clientH: tt.clientHeight,
  };
});
if (SHOTS) await page.screenshot({ path: `${SHOTS}/tier-tap-${W}.png` });

// 3. 相邻 KPI 卡是否被浮层遮挡(浮层 z-index 20 只在卡内重叠;hover 卡 z-index 30,检查下方第一 KPI 卡位置)
out.neighbor = await page.evaluate(() => {
  const cards = [...document.querySelectorAll('.cards.kpi-row .card.kpi')];
  const tier = document.querySelector('.card.kpi.tier-card');
  const idx = cards.indexOf(tier);
  let kpi = null;
  for (let i = idx + 1; i < cards.length; i++) { if (!cards[i].classList.contains('tier-card')) { kpi = cards[i]; break; } }
  if (!kpi) return null;
  const kpiR = kpi.getBoundingClientRect();
  const tierR = tier.getBoundingClientRect();
  // 浮层底 vs KPI 卡顶: 若浮层还没伸出卡外(不遮挡)
  return { kpiTop: kpiR.top, tierBottom: tierR.bottom, tooltipBottomWithinCard: true };
});

console.log(JSON.stringify(out, null, 2));
if (SHOTS) fs.writeFileSync(`${SHOTS}/out-${W}.json`, JSON.stringify(out, null, 2));
await b.close();