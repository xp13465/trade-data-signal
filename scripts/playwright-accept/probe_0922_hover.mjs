// 探针: hover 9-22 AI建议 cell 抓 term-pop 实际内容
import { chromium } from 'playwright';

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1680, height: 4000 } });
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/', { waitUntil: 'domcontentloaded', timeout: 120000 });

await page.evaluate(() => { const s = document.querySelector('.onboarding-skip'); if (s) s.click(); }).catch(() => {});

// 等渲染+快照
for (let i = 0; i < 40; i++) {
  const n = await page.locator('.sig-item[data-date="20260922"]').count().catch(() => 0);
  const s = await page.evaluate(() => window._sigSnapByDate ? 1 : 0).catch(() => 0);
  if (n > 0 && s) break;
  await page.waitForTimeout(2000);
}

const cell = page.locator('.sig-item[data-date="20260922"].sig-poscap-kept').first();
console.log('cell count:', await cell.count());

// 先读 cell 的 title 属性(可能已迁走) 与 keep badge
const info = await cell.evaluate((el) => ({
  title: el.getAttribute('title'),
  dataTip: el.getAttribute('data-tip'),
  html: el.outerHTML.slice(0, 800),
})).catch((e) => ({ err: String(e) }));
console.log('=== cell info ===');
console.log(JSON.stringify(info, null, 1));

// 真实 hover 并停留, 长等待
await cell.hover({ timeout: 8000 }).catch(() => {});
await page.waitForTimeout(2000);

const pop = await page.evaluate(() => {
  const p = document.querySelector('.term-pop');
  if (!p) return { found: false };
  return { found: true, display: p.style.display, text: (p.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 500), html: p.outerHTML.slice(0, 600) };
}).catch((e) => ({ err: String(e) }));
console.log('=== term-pop ===');
console.log(JSON.stringify(pop, null, 1));

// 也尝试 evaluate 直接 dispatch mouseover(与 hover 并列对比), 再抓一遍
await cell.evaluate((el) => el.dispatchEvent(new MouseEvent('mouseover', { bubbles: true, view: window }))).catch(() => {});
await page.waitForTimeout(800);
const pop2 = await page.evaluate(() => {
  const p = document.querySelector('.term-pop');
  if (!p) return { found: false };
  return { found: true, display: p.style.display, text: (p.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 500) };
}).catch((e) => ({ err: String(e) }));
console.log('=== term-pop after manual mouseover ===');
console.log(JSON.stringify(pop2, null, 1));

await b.close();
