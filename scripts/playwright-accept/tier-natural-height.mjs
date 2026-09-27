// 探测 tier-tooltip 浮层的自然高度(去除 inset:0 约束后内容真实高度)
// 用法: node scripts/playwright-accept/tier-natural-height.mjs <width>
import { chromium } from 'playwright';
const SITE = 'https://ss.fx8.store/';
const W = parseInt(process.argv[2], 10) || 375;
const UA_IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({
  viewport: { width: W, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
  userAgent: UA_IPHONE, serviceWorkers: 'block',
});
// 拦截本地 CSS(与 measure-tier-card-static 同口径)
await ctx.route(/\.css(\?.*)?$/, (route) =>
  route.fulfill({ path: '/Users/linhuichen/code/trade/static-site/style.css', contentType: 'text/css' }));
await ctx.addInitScript(() => {
  const t = new Date();
  const stamp = `${t.getFullYear()}${String(t.getMonth() + 1).padStart(2, '0')}${String(t.getDate()).padStart(2, '0')}`;
  ['last_visit_date', 'welcome_shown_date'].forEach((k) => localStorage.setItem(k, stamp));
  ['onboarding_done', 'nt_intro_done'].forEach((k) => localStorage.setItem(k, '1'));
});
const page = await ctx.newPage();
await page.goto(SITE, { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.waitForTimeout(1200);
for (let i = 0; i < 60; i++) { if (await page.locator('.card.kpi.tier-card').count() > 0) break; await page.waitForTimeout(500); }
await page.waitForTimeout(800);
const r = await page.evaluate(() => {
  const tt = document.querySelector('.card.kpi.tier-card .tier-tooltip');
  tt.style.overflow = 'visible';
  tt.style.visibility = 'visible';
  tt.style.opacity = '1';
  // 去除 inset 约束,测自然高度
  const saved = { top: tt.style.top, bottom: tt.style.bottom, height: tt.style.height };
  tt.style.bottom = 'auto';
  tt.style.height = 'auto';
  const natural = tt.getBoundingClientRect().height;
  // 恢复
  tt.style.bottom = saved.bottom; tt.style.height = saved.height;
  // 同时量 4 行明细时(模拟极端:每行取线高)
  const rows = [...tt.querySelectorAll('.tier-detail-row')].map((r) => Math.ceil(r.getBoundingClientRect().height));
  const pad = getComputedStyle(tt).paddingTop + ' ' + getComputedStyle(tt).paddingBottom;
  const titleH = tt.querySelector('.tier-tooltip-title').getBoundingClientRect().height;
  return {
    width: innerWidth,
    naturalH: natural,
    rows, pad,
    titleH,
    rowCount: rows.length,
    gap: getComputedStyle(tt).gap,
  };
});
console.log(JSON.stringify(r, null, 2));
await b.close();