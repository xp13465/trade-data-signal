import { chromium } from "playwright";
const BASE = "http://127.0.0.1:8124";
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
// 线上资源重定向本地: ss.fx8.store → 127.0.0.1:8124(同 path, sim 数据可测)
await ctx.route(/^https:\/\/ss\.fx8\.store\//, async (route) => {
  const u = route.request().url();
  const rel = u.replace(/^https:\/\/ss\.fx8\.store\//, "");
  const resp = await route.fetch({ url: BASE + "/" + rel });
  await route.fulfill({ response: resp });
});
const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 200)));
await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(1500);
const ob = page.locator(".onboarding-modal:not(.hidden)");
if (await ob.count()) await page.locator(".onboarding-skip").first().click().catch(() => {});
await page.waitForTimeout(300);
await page.locator('button[data-tab="lab"]').first().click({ force: true });
let rows = 0;
for (let i = 0; i < 8; i++) {
  await page.waitForTimeout(5000);
  rows = await page.locator(".lab-sigkelly-trade-row").count();
  const st = await page.evaluate(() => ({ all: !!window._labKellyAllReady, y1: !!window._labKellyY1Ready, prog: window._labKellyLoadProgress && window._labKellyLoadProgress.done }));
  console.log(`t=${(i+1)*5}s rows=${rows} ready=${JSON.stringify(st)}`);
  if (rows > 0) break;
}
console.log("pageerrors:", pageErrors.slice(0, 8));
await browser.close();
