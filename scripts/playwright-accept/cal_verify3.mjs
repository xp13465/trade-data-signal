import { chromium } from "playwright";
// 验证 07-17 冰点明细: 6 个维度中文名+值齐全; 同时对比桌面弹出明细渲染
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8133/#overview", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(11000);
await page.evaluate(() => { document.querySelectorAll(".onboarding-modal, .rule-modal").forEach((m) => m && m.remove()); });
// 点击 07-17 行日期标签
const clicked = await page.evaluate(() => {
  const btns = [...document.querySelectorAll(".sig-day-date-btn")];
  const target = btns.find((b) => b.dataset.calDate === "20260717");
  if (!target) return false;
  target.click();
  return true;
});
await page.waitForTimeout(600);
const det = await page.evaluate(() => {
  const m = document.getElementById("sentimentDayDetailModal");
  if (!m || m.classList.contains("hidden")) return null;
  const rows = [...m.querySelectorAll(".dd-row")].map((r) => r.textContent.trim());
  return { title: m.querySelector(".day-detail-title")?.textContent?.trim(), rows };
});
console.log("clicked:", clicked);
console.log("title:", det?.title);
console.log((det?.rows || []).join(" | "));
// 值与 overview.json 源数据一致(toFixed(1) 格式)
const need = ["中证1000情绪分8.7", "中证500情绪分13.0", "创业板情绪分13.4", "沪深300情绪分12.0", "科创50情绪分15.8", "上证50情绪分18.3"];
const allRows = (det?.rows || []).join(" ");
let pass = 1;
for (const n of need) {
  const has = allRows.includes(n);
  if (!has) pass = 0;
  console.log(`${has ? "PASS" : "FAIL"}  冰点维度 ${n}`);
}
await browser.close();
process.exit(pass ? 0 : 1);