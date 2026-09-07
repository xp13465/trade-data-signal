#!/usr/bin/env node
// 验收 #sigkelly-silent-fill 方案 A(补齐后静默重算不再锁屏)+ 方案 B(占位去数字轻提示)
// 用法: cd scripts/playwright-accept && node accept_sigkelly_silent.mjs
// 前置: 本地已起 http.server 于 8123(静态站根目录 = 新版产物 + 全量数据, 见 /tmp/sim-site-static)
// §5.4⑦ 页面实测锚点: 无痕 context(零 localStorage), 本地 8123 新版 app.min.js/lab.min.js(版本串 a556)
import { createRequire } from "module";
const require = createRequire("/Users/linhuichen/code/trade/scripts/playwright-accept/");
const { chromium } = require("playwright");

const BASE = "http://localhost:8123";
let nPass = 0, nFail = 0;
const check = (name, cond, detail = "") => { if (cond) nPass++; else nFail++; console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`); };

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.clearCookies();
// 封闭网络: 只放行 localhost
await ctx.route(/^(?!.*localhost)/, (r) => r.abort());

// 分片拦截: 阶段1 放行 t2025/t2026, 其余 14 片 hold 至 release(release 后 ALL_READY → 静默全量重算)
let released = false;
const waiters = [];
await ctx.route(/signal_kelly_trades_parts/, async (route) => {
  const m = /t(\d{4})\.json/.exec(route.request().url());
  const year = m ? m[1] : "";
  if (year === "2026" || year === "2025") { route.continue(); return; }
  if (released) { route.continue(); return; }
  await new Promise((r) => waiters.push(r));
  route.continue();
});

const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 240)));

// 时间线观测: 记录 host loading ON/OFF + PROG 占位文本 + Y1/ALL ready
const t0 = Date.now();
await page.addInitScript((t0ms) => {
  window.__tl = [];
  const log = (tag, detail) => window.__tl.push({ t: +((Date.now() - 1000 * t0ms) / 1000).toFixed(1), tag, detail });
  setInterval(() => {
    try {
      const host = document.querySelector(".lab-sigkelly-host");
      if (!host) return;
      const loading = host.classList.contains("lab-custom-host--loading");
      if (loading !== window.__lastLoading) { window.__lastLoading = loading; log(loading ? "HOST_LOADING_ON" : "HOST_LOADING_OFF", ""); }
      const prog = document.querySelector(".lab-sigkelly-all-loading");
      const txt = prog ? prog.textContent.replace(/\s+/g, " ").trim() : "";
      if (txt && txt !== window.__lastProg) { window.__lastProg = txt; log("PROG", txt); }
      if (window._labKellyY1Ready && !window.__y1) { window.__y1 = true; log("Y1_READY", ""); }
      if (window._labKellyAllReady && !window.__all) { window.__all = true; log("ALL_READY", ""); }
    } catch (e) {}
  }, 200);
}, (Date.now() - t0) / 1000);

await page.goto(BASE + "/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 120000 });

// 等 Y1_READY + 阶段2 占位文案出现(窗口期)
let y1Seen = false, progLight = "";
for (let i = 0; i < 80; i++) {
  await new Promise((r) => setTimeout(r, 800));
  const s = await page.evaluate(() => {
    const prog = document.querySelector(".lab-sigkelly-all-loading");
    return { y1: !!window._labKellyY1Ready, prog: prog ? prog.textContent.replace(/\s+/g, " ").trim() : "", hostLoading: !!document.querySelector(".lab-sigkelly-host")?.classList.contains("lab-custom-host--loading") };
  });
  if (s.y1) y1Seen = true;
  if (s.prog && s.prog.includes("后台补齐其余周期")) { progLight = s.prog; break; }
  if (i >= 60) break;
}
console.log(`[窗口期] y1=${y1Seen} progLight=[${progLight}]`);

// B1: 阶段2 占位为无数字轻提示
check("B1 阶段2 占位轻提示含「后台补齐其余周期, 完成后自动展示…」", progLight.includes("后台补齐其余周期") && progLight.includes("完成后自动展示"), progLight);
check("B2 阶段2 占位不含进度数字 N/16", !/补全 \d+\/\d+/.test(progLight), progLight);

// release 剩余 14 片 → ALL_READY → 静默全量重算
waiters.forEach((w) => w());
released = true;
waiters.length = 0;

// 等 ALL_READY 且最终解锁
let allSeen = false, unlocked = false;
for (let i = 0; i < 120; i++) {
  await new Promise((r) => setTimeout(r, 1000));
  const s = await page.evaluate(() => ({ all: !!window._labKellyAllReady, loading: !!document.querySelector(".lab-sigkelly-host")?.classList.contains("lab-custom-host--loading") }));
  if (s.all) allSeen = true;
  if (s.all && !s.loading) { unlocked = true; break; }
  if (i >= 90) break;
}
console.log(`[补齐后] allSeen=${allSeen} unlocked=${unlocked}`);

// 提取时间线里 ALL_READY 之后的 HOST_LOADING_ON 序列 → 断言无「补齐后又加遮罩」
const tl = await page.evaluate(() => window.__tl || []);
const allIdx = tl.findIndex((e) => e.tag === "ALL_READY");
const afterAll = allIdx >= 0 ? tl.slice(allIdx) : [];
const onCountAfterAll = afterAll.filter((e) => e.tag === "HOST_LOADING_ON").length;
const onSeq = tl.filter((e) => e.tag.startsWith("HOST_LOADING")).map((e) => `@${e.t} ${e.tag}`).join(" | ");
console.log("时间线序列(HOST_LOADING):", onSeq);
check("A1 补齐完成(ALL_READY)后不再出现 HOST_LOADING_ON(静默重算无遮罩)", onCountAfterAll === 0, `ALL_READY后ON次数=${onCountAfterAll}`);
check("A2 最终状态解锁(lab-custom-host--loading 已移除)", unlocked, "");
check("A3 全量完成后主卡有交易行", await page.evaluate(() => !!document.querySelector('.lab-sigkelly-card[data-quad="sig_main"]')?.querySelector(".lab-sigkelly-trade-row")), "");
check("A4 无 pageerror", pageErrors.length === 0, pageErrors.slice(0, 2).join(" | "));

console.log(`\n===== 结果: ${nPass} pass / ${nFail} fail =====`);
if (nFail) console.log("时间线: " + tl.map((e) => `${e.t}s:${e.tag}[${e.detail.slice(0, 40)}]`).join(" → "));
await browser.close();
process.exit(nFail ? 1 : 0);
