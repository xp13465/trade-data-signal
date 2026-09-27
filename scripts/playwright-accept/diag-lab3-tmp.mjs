import { chromium } from "playwright";
const BASE = "http://127.0.0.1:8124";
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const pageErrors = [];
const reqFailed = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 200)));
page.on("requestfailed", (r) => reqFailed.push(r.url().slice(0, 120) + " :: " + (r.failure()?.errorText || "")));
const resp = await page.goto(BASE + "/index.html", { waitUntil: "load", timeout: 60000 }).catch((e) => console.log("goto err", e.message));
await page.waitForTimeout(2000);
await page.locator('button[data-tab="lab"]').first().click();
// 探测数据加载
await page.waitForTimeout(10000);
const st = await page.evaluate(() => ({
  loading: window._simKellyLoading,
  loadErr: window._simKellyLoadErr,
  dataKeys: window._simKellyData ? Object.keys(window._simKellyData).slice(0, 8) : null,
  prog: window._labKellyLoadProgress,
  allReady: window._labKellyAllReady,
  y1Ready: window._labKellyY1Ready,
}));
console.log("状态:", JSON.stringify(st, null, 1));
console.log("pageerrors:", pageErrors.slice(0, 6));
console.log("reqFailed:", reqFailed.slice(0, 8));
// fetch 测 parts 可访问
const pt = await page.evaluate(async () => {
  try { const r = await fetch("data/signal_kelly_trades_parts/t2026.json"); return { status: r.status, len: (await r.text()).length }; } catch (e) { return { err: String(e).slice(0, 100) }; }
});
console.log("parts fetch:", pt);
await browser.close();
