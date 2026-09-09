// F1 实测(2026-09-09 review 修复): lab 凯利交易记录弹窗
// 断言: 1) 无 ReferenceError(_fIdx→fIdx) 2) 排序表头可点 3) 翻页/淘汰区存在 4) 资产走势块渲染
import { chromium } from "playwright";
const BASE = "http://127.0.0.1:8124";
let nPass = 0, nFail = 0;
const check = (name, cond, detail="") => { if (cond) nPass++; else nFail++; console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`); };

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
// 线上资源重定向本地(same path): ss.fx8.store → 127.0.0.1:8124, 数据全走本地 symlink
await ctx.route(/^https:\/\/ss\.fx8\.store\//, async (route) => {
  const u = route.request().url();
  const rel = u.replace(/^https:\/\/ss\.fx8\.store\//, "");
  try { const resp = await route.fetch({ url: BASE + "/" + rel }); await route.fulfill({ response: resp }); }
  catch (e) { await route.fulfill({ status: 404, body: "redirect fail" }); }
});
const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 300)));

// 直入 lab 凯利子 tab(hash 带 sub=sigkelly)
await page.goto(BASE + "/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(1500);
const ob = page.locator(".onboarding-modal:not(.hidden)");
if (await ob.count()) await page.locator(".onboarding-skip").first().click().catch(() => {});
await page.waitForTimeout(300);

let rowCount = 0;
for (let i = 0; i < 9; i++) {
  await page.waitForTimeout(5000);
  rowCount = await page.locator(".lab-sigkelly-trade-row").count();
  if (rowCount > 0) break;
}
const ready = await page.evaluate(() => ({ all: !!window._labKellyAllReady, y1: !!window._labKellyY1Ready, err: window._labKellyLoadErr }));
console.log(`  [lab 数据 ready=${JSON.stringify(ready)}]`);
check("lab 凯利交易记录行可见", rowCount > 0, `rows=${rowCount}`);
if (rowCount === 0) { console.log("  [诊断 pageerror]", pageErrors.slice(0, 4)); await browser.close(); process.exit(nFail ? 1 : 0); }

await page.locator(".lab-sigkelly-trade-row").first().click({ force: true });
await page.waitForTimeout(3000);

const overlay = page.locator("#lab-sigkelly-trades-overlay");
let ovVisible = false;
try { ovVisible = await overlay.isVisible(); } catch (e) {}
check("凯利交易记录弹窗可见", ovVisible);

const naBlock = await page.locator(".sim-netasset-chart.lab-sigkelly-netasset").count();
const naBody = await page.locator(".sim-netasset-chart.lab-sigkelly-netasset .sim-netasset-body").textContent().catch(() => "");
check("资产走势块容器存在", naBlock > 0);
check("资产走势块有渲染内容", (naBody || "").trim().length > 0, `len=${(naBody || "").trim().length}`);

const thCount = await page.locator(".lab-sigkelly-trades-th").count();
check("排序表头存在", thCount > 0, `th=${thCount}`);
if (thCount > 0) {
  await page.locator(".lab-sigkelly-trades-th").first().click({ force: true });
  await page.waitForTimeout(400);
  check("点击排序表头不新增页面错误", pageErrors.length === 0, `errs=${pageErrors.length}`);
}

const pagEnd = await page.locator(".lab-sigkelly-page-next").count();
check("翻页区域存在", pagEnd > 0);
if (pagEnd > 0) {
  const nxt = page.locator(".lab-sigkelly-page-next");
  if (!(await nxt.isDisabled())) { await nxt.click({ force: true }); await page.waitForTimeout(300); }
  check("点击下一页不新增页面错误", pageErrors.length === 0, `errs=${pageErrors.length}`);
}
const elimToggle = await page.locator(".sigkelly-elim-toggle, [class*='elim-toggle' i], .lab-sigkelly-elim-toggle").count();
check("淘汰区折叠 toggle 存在", elimToggle > 0, `n=${elimToggle}`);

const hasRef = pageErrors.some((e) => e.includes("ReferenceError"));
check("弹窗内无 ReferenceError", !hasRef, pageErrors.slice(0, 3).join(" | "));
check("全程无任何 pageerror", pageErrors.length === 0, pageErrors.slice(0, 3).join(" | "));

await page.screenshot({ path: "/tmp/f1-lab-modal-fix.png", fullPage: false }).catch(() => {});
console.log(`\nF1 lab 弹窗实测: PASS=${nPass} FAIL=${nFail}`);
await browser.close();
process.exit(nFail ? 1 : 0);
