import { chromium } from "playwright";
// 补验: 移动端所有日期标签点击目标高度(含格子少的矮行) + 明细弹层无横向溢出
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
const page = await ctx.newPage();
await page.goto("http://127.0.0.1:8133/#overview", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(11000);
await page.evaluate(() => { document.querySelectorAll(".onboarding-modal, .rule-modal").forEach((m) => m && m.remove()); });
const heights = await page.evaluate(() => {
  const btns = [...document.querySelectorAll(".sig-day-date-btn")];
  const hs = btns.map((b) => Math.round(b.getBoundingClientRect().height));
  const countByH = {};
  hs.forEach((h) => (countByH[h] = (countByH[h] || 0) + 1));
  return { min: Math.min(...hs), max: Math.max(...hs), all44up: hs.every((h) => h >= 44), count: hs.length, countByH };
});
console.log("date-btn heights:", JSON.stringify(heights));
let pass = heights.all44up === true ? 0 : 1;
console.log(`${heights.all44up ? "PASS" : "FAIL"}  移动端全部日期点击目标≥44px(min=${heights.min} max=${heights.max})`);
// 弹层无横向溢出
await page.click(".sig-day-date-btn:first-of-type");
await page.waitForTimeout(600);
const ovf = await page.evaluate(() => {
  const m = document.getElementById("sentimentDayDetailModal");
  if (!m || m.classList.contains("hidden")) return null;
  const body = m.querySelector(".day-detail-content");
  return {
    bodyScrollW: body.scrollWidth,
    bodyClientW: body.clientWidth,
    docOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    closeVisible: m.querySelector(".rule-modal-close").offsetHeight > 0,
    closeHit: (() => { const r = m.querySelector(".rule-modal-close").getBoundingClientRect(); return Math.min(r.width, r.height) >= 40; })(),
  };
});
console.log("modal:", JSON.stringify(ovf));
if (ovf && ovf.bodyScrollW <= ovf.bodyClientW && ovf.docOverflowX <= 0 && ovf.closeVisible && ovf.closeHit) {
  console.log("PASS  明细弹层无横向溢出+关闭按钮可点(≥40)");
} else {
  console.log("FAIL  弹层溢出或关闭按钮问题");
  pass = 1;
}
await browser.close();
process.exit(pass);