#!/usr/bin/env node
// 验收 #sigkelly-silent-fill 方案 C(首页模拟回测弹窗渐进加载)
// 用法: cd scripts/playwright-accept && node accept_sim_progressive.mjs
// 前置: 本地已起 http.server 于 8123(静态站根目录 = 新版产物 + 全量数据, 见 /tmp/sim-site-static)
// §5.4⑦ 页面实测锚点: 无痕 context(零 localStorage), 本地 8123 新版 app.min.js(版本串 a556)
import { createRequire } from "module";
const require = createRequire("/Users/linhuichen/code/trade/scripts/playwright-accept/");
const { chromium } = require("playwright");

const BASE = "http://localhost:8123";
let nPass = 0, nFail = 0;
const check = (name, cond, detail = "") => { if (cond) nPass++; else nFail++; console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`); };

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.clearCookies();
await ctx.route(/^(?!.*localhost)/, (r) => r.abort());

// 确定性测试(verify_sigkelly_y1_render 同款模式): recent 热区放行, 年片 t*.json 全部 hold 至 release
// → 窗口渲染用 recent 秒完成(全史未就绪, 标注「全史校准中」稳定出现), release 后后台补齐完成标注消失。
let releasedParts = false;
const partWaiters = [];
await ctx.route(/signal_kelly_trades_parts/, async (route) => {
  const url = route.request().url();
  if (url.includes("recent.json")) { route.continue(); return; }
  if (releasedParts) { route.continue(); return; }
  await new Promise((r) => partWaiters.push(r));
  route.continue();
});

const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 240)));

// 打开首页(主站)
await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded", timeout: 120000 });

// 等首页信号卡渲染出「模拟回测」按钮
let btn = null;
for (let i = 0; i < 60; i++) {
  await new Promise((r) => setTimeout(r, 1000));
  btn = await page.$('.sig-kbtn[data-k="sim"], .sig-kbtn-sim');
  if (btn) break;
}
check("S0 首页「模拟回测」按钮已渲染", !!btn, "");
if (!btn) { console.log("按钮未渲染, 退出"); process.exit(1); }

// 点按钮打开弹窗
await btn.click();
let modal = null;
for (let i = 0; i < 40; i++) {
  await new Promise((r) => setTimeout(r, 500));
  modal = await page.$(".rule-modal:not(.hidden)");
  if (modal) break;
}
check("S1 模拟回测弹窗已打开", !!modal, "");

// 把日期范围设为热区内(20260715~20260903), 触发 change → 渲染只用 recent, 秒完成且全史未就绪
await page.evaluate(() => {
  const s = document.querySelector(".rule-modal:not(.hidden) .sim-date-start");
  const e = document.querySelector(".rule-modal:not(.hidden) .sim-date-end");
  if (s) { s.value = "2026-07-15"; s.dispatchEvent(new Event("change", { bubbles: true })); }
  if (e) { e.value = "2026-09-03"; e.dispatchEvent(new Event("change", { bubbles: true })); }
});
console.log("[调试] 已设热区内窗口 20260715~20260903(仅 recent 渲染, 年片被 hold)");

// 等待表格先渲染(有交易行)—— 不等待全史补齐
let rowsSeen = false, calibSeen = false;
for (let i = 0; i < 60; i++) {
  await new Promise((r) => setTimeout(r, 800));
  const s = await page.evaluate(() => {
    const body = document.querySelector(".rule-modal:not(.hidden) .sim-table-body");
    const rows = body ? body.querySelectorAll(".sim-tbl tbody tr").length : 0;
    const txt = body ? body.textContent : "";
    return { rows, hasCalib: txt.includes("全史校准中"), hasCurveNote: txt.includes("后台补全全史数据") };
  });
  if (s.rows > 0) rowsSeen = true;
  if (s.hasCalib) { calibSeen = true; console.log(`[渐进] 表格已先渲染 rows=${s.rows}, 「全史校准中」标注出现`); }
  if (s.rows > 0 && (s.hasCalib || i > 30)) break;
  if (i >= 50) break;
}

// C1: 表格先渲染(未等全史补齐)
const stateEarly = await page.evaluate(() => {
  const body = document.querySelector(".rule-modal:not(.hidden) .sim-table-body");
  const dbg = {
    hotMin: window._simHotMinDate, hotMax: window._simHotMaxDate,
    allHistReady: window._simAllHistReady, allHistLoading: window._simAllHistLoading,
    startD: (document.querySelector(".rule-modal:not(.hidden) .sim-date-start") || {}).value || "",
    endD: (document.querySelector(".rule-modal:not(.hidden) .sim-date-end") || {}).value || "",
    fallback: window._simFullFallback,
  };
  window.__dbg = dbg;
  return {
    rows: body ? body.querySelectorAll(".sim-tbl tbody tr").length : 0,
    hasCalib: body ? body.textContent.includes("全史校准中") : false,
    curveNote: (document.querySelector(".rule-modal:not(.hidden) .sim-netasset-note") || {}).textContent || "",
  };
});
console.log("[debug] " + JSON.stringify(await page.evaluate(() => window.__dbg || {})));
check("C1 表格已先渲染(渐进: 不等全史补齐)", stateEarly.rows > 0, `rows=${stateEarly.rows}`);
check("C2 全史未就绪时「全史校准中」标注出现", stateEarly.hasCalib, "");
check("C3 净资产曲线 note 含补全提示", stateEarly.curveNote.includes("后台补全全史数据"), stateEarly.curveNote);

// release 年片 → 后台补齐全史 → 原地重渲染, 标注消失
partWaiters.forEach((w) => w());
releasedParts = true;
partWaiters.length = 0;
console.log("[调试] 已 release 年片, 后台补齐全史…");

// 等待后台补齐完成 → 标注消失
let calibGone = false;
for (let i = 0; i < 120; i++) {
  await new Promise((r) => setTimeout(r, 1000));
  const s = await page.evaluate(() => {
    const body = document.querySelector(".rule-modal:not(.hidden) .sim-table-body");
    const note = document.querySelector(".rule-modal:not(.hidden) .sim-netasset-note");
    return { hasCalib: body ? body.textContent.includes("全史校准中") : true, curveNote: note ? note.textContent : "", rows: body ? body.querySelectorAll(".sim-tbl tbody tr").length : 0 };
  });
  if (!s.hasCalib && s.rows > 0) { calibGone = true; console.log(`[补齐后] 「全史校准中」标注已消失, rows=${s.rows}, curveNote=[${s.curveNote}]`); break; }
  if (i >= 100) break;
}
check("C4 后台补齐完成后「全史校准中」标注消失(峰值口径已刷全史)", calibGone, "");
check("C5 补齐后净资产曲线补全提示消失", !(await page.evaluate(() => (document.querySelector(".rule-modal:not(.hidden) .sim-netasset-note") || {}).textContent || "")).includes("后台补全全史数据"), "");
check("C6 无 pageerror", pageErrors.length === 0, pageErrors.slice(0, 2).join(" | "));

console.log(`\n===== 结果: ${nPass} pass / ${nFail} fail =====`);
await browser.close();
process.exit(nFail ? 1 : 0);
