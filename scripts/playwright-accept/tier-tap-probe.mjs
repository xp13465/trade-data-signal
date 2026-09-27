// 移动端点按能否触发 tier 卡浮层(可访问性检查)
// 用法: node scripts/playwright-accept/tier-tap-probe.mjs
import { chromium } from 'playwright';

const SITE = 'https://ss.fx8.store/';
const UA_IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({
  viewport: { width: 375, height: 844 },
  deviceScaleFactor: 2,
  isMobile: true,
  hasTouch: true,
  userAgent: UA_IPHONE,
  serviceWorkers: 'block',
});
const page = await ctx.newPage();
await ctx.addInitScript(() => {
  const t = new Date();
  const stamp = `${t.getFullYear()}${String(t.getMonth() + 1).padStart(2, '0')}${String(t.getDate()).padStart(2, '0')}`;
  localStorage.setItem('last_visit_date', stamp);
  localStorage.setItem('welcome_shown_date', stamp);
  localStorage.setItem('onboarding_done', '1');
  localStorage.setItem('nt_intro_done', '1');
});
await page.goto(SITE, { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.waitForTimeout(1500);
// 兜底:强制移除任何 onboarding 遮罩 DOM
await page.evaluate(() => {
  document.querySelectorAll('.onboarding-modal, .rule-modal, .rule-modal-overlay, .onboarding-overlay, .onboarding-skip')
    .forEach((m) => m.remove());
}).catch(() => {});
await page.waitForTimeout(300);
for (let i = 0; i < 60; i++) {
  if (await page.locator('.card.kpi.tier-card').count() > 0) break;
  await page.waitForTimeout(500);
}
await page.waitForTimeout(1000);
const tier = page.locator('.card.kpi.tier-card');
await tier.scrollIntoViewIfNeeded();
await page.waitForTimeout(500);

// 状态记录
const readState = () => page.evaluate(() => {
  const tt = document.querySelector('.card.kpi.tier-card .tier-tooltip');
  if (!tt) return null;
  const cs = getComputedStyle(tt);
  return { opacity: cs.opacity, visibility: cs.visibility, pointerEvents: cs.pointerEvents };
});
const out = { tap: null, hover: null, afterTapElsewhere: null };

// 1. Playwright hover(鼠标模拟,桌面语义)
await tier.hover();
await page.waitForTimeout(400);
out.hover = await readState();

// 2. tap(触屏模拟)
await page.evaluate(() => { const tt = document.querySelector('.card.kpi.tier-card .tier-tooltip'); if (tt) tt.style.transition = 'none'; });
await tier.tap();
await page.waitForTimeout(400);
out.tap = await readState();

// 3. 点按卡片外部后是否保持
await page.mouse.click(10, 10);
await page.waitForTimeout(400);
out.afterTapElsewhere = await readState();

console.log(JSON.stringify(out, null, 2));
await b.close();