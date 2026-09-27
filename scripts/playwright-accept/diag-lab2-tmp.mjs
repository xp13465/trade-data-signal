import { chromium } from "playwright";
const BASE = "http://127.0.0.1:8124";
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const pageErrors = [];
const consoleMsgs = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 200)));
page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") consoleMsgs.push(m.type() + ": " + m.text().slice(0, 200)); });
await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded" });
await page.waitForTimeout(2000);
await page.locator('button[data-tab="lab"]').first().click();
// 等 20 秒看加载
for (let i = 0; i < 4; i++) {
  await page.waitForTimeout(5000);
  const rows = await page.locator(".lab-sigkelly-trade-row").count();
  const sK = await page.locator("[class*='sigkelly' i]").count();
  const done = await page.evaluate(() => ({ ok: !!window._labKellyAllReady, y1: !!window._labKellyY1Ready, keys: Object.keys(window).filter(k=>k.includes('Kelly')||k.includes('sigkelly')).slice(0,10) }));
  console.log(`t=${(i+1)*5}s rows=${rows} sigkelly=${sK} ready=${JSON.stringify(done)}`);
  if (rows > 0) break;
}
console.log("consoleMsgs:", consoleMsgs.slice(0, 8));
console.log("pageerrors:", pageErrors.slice(0, 6));
// dump lab 主体
const labTxt = await page.locator("main").textContent().catch(() => "");
console.log("lab main 文本 key 段:", (labTxt||"").replace(/\s+/g," ").includes("信号凯利") ? "含信号凯利" : "不含信号凯利");
const subTabs = await page.locator(".lab-subnav button, .lab-subnav-child button, [class*='subnav'] button").allTextContents().catch(()=>[]);
console.log("lab 子 tab:", subTabs);
const ks = await page.evaluate(() => Object.keys(window).filter(k => /kelly/i.test(k) && typeof window[k] === "function").slice(0, 15));
console.log("window kelly 函数挂载:", ks);
await browser.close();
