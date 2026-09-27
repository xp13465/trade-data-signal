// 极端情形: 注入 4 档各有指数的 index_tiers 假数据, 测 375 下浮层是否被裁
// 用法: node scripts/playwright-accept/tier-4tier-probe.mjs
import { chromium } from 'playwright';
import fs from 'node:fs';

const SITE = 'https://ss.fx8.store/';
const CSS_FILE = '/Users/linhuichen/code/trade/static-site/style.css';
const UA_IPHONE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1';

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({
  viewport: { width: 375, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
  userAgent: UA_IPHONE, serviceWorkers: 'block',
});
await ctx.addInitScript(() => {
  const t = new Date();
  const stamp = `${t.getFullYear()}${String(t.getMonth() + 1).padStart(2, '0')}${String(t.getDate()).padStart(2, '0')}`;
  localStorage.setItem('last_visit_date', stamp); localStorage.setItem('welcome_shown_date', stamp);
  localStorage.setItem('onboarding_done', '1'); localStorage.setItem('nt_intro_done', '1');
});
// 注入本地 CSS
await ctx.route(/\.css(\?.*)?$/, (route) => route.fulfill({ path: CSS_FILE, contentType: 'text/css' }));
// 拦截 overview.json: 4 档各 2 个指数(静态路径 ./data/overview.json)
await ctx.route('**/data/overview.json**', async (route) => {
  const resp = await route.fetch();
  let j;
  try { j = await resp.json(); } catch { j = {}; }
  if (j && typeof j === 'object') {
    // 最坏组合: 4 档都存在, 且其中一档含 4 个指数(名称长, 310 屏下换行), 其余 3 档各 1 个
    j.index_tiers = {
      hs300: { tier: '牛市·主升', date: '2026-09-25' },
      sh: { tier: '牛市·主升', date: '2026-09-25' },
      sz: { tier: '牛市·主升', date: '2026-09-25' },
      sz50: { tier: '牛市·主升', date: '2026-09-25' },
      csi500: { tier: '上升期', date: '2026-09-25' },
      csi1000: { tier: '下降期', date: '2026-09-25' },
      cyb: { tier: '熊市·主跌', date: '2026-09-25' },
      kc50: { tier: '熊市·主跌', date: '2026-09-25' },
    };
  }
  await route.fulfill({ response: resp, json: j, contentType: 'application/json' });
});
const page = await ctx.newPage();
page.on('console', (msg) => { if (msg.type() === 'error') console.log('CONSOLE-ERR:', msg.text().slice(0, 200)); });
page.on('pageerror', (e) => console.log('PAGEERR:', String(e).slice(0, 200)));
await page.goto(SITE, { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.waitForTimeout(1500);
for (let i = 0; i < 60; i++) { if (await page.locator('.card.kpi.tier-card').count() > 0) break; await page.waitForTimeout(500); }
await page.waitForTimeout(1000);
const r = await page.evaluate(() => {
  const tier = document.querySelector('.card.kpi.tier-card');
  const tt = tier.querySelector('.tier-tooltip');
  return {
    tierH: tier.getBoundingClientRect().height,
    tierClientH: tier.clientHeight,
    scrollH: tt.scrollHeight,
    clientH: tt.clientHeight,
    cutBy: tt.scrollHeight - tt.clientHeight,
    rows: [...tt.querySelectorAll('.tier-detail-row')].length,
    rowHeights: [...tt.querySelectorAll('.tier-detail-row')].map((x) => Math.ceil(x.getBoundingClientRect().height)),
    text: tt.textContent.slice(0, 200),
  };
});
console.log(JSON.stringify(r, null, 2));
await b.close();