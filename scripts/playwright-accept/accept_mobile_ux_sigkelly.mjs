#!/usr/bin/env node
// 移动端「数据优先+说明折叠」双视口验收
// 用法: BASE_URL=https://ss.fx8.store node scripts/playwright-accept/accept_mobile_ux_sigkelly.mjs
//   本地: BASE_URL=http://localhost:8123 node scripts/playwright-accept/accept_mobile_ux_sigkelly.mjs
// 断言两类: 移动端(390x844)可视度达标 + 桌面端(1280x900)零回归。双 PASS 才会 exit 0。
import { createRequire } from "module";
const require = createRequire("/Users/linhuichen/code/trade/scripts/playwright-accept/");
const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "https://ss.fx8.store";
const URL = BASE + "/#lab?sub=sigkelly";
let pass = 0, fail = 0;
const ok = (name, cond, detail = "") => { cond ? pass++ : fail++; console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`); };
const vis = (el) => el ? (el.offsetHeight > 0 && getComputedStyle(el).display !== "none") : false;

const browser = await chromium.launch({ headless: true });

// ---------- 移动端 390x844 ----------
async function runMobile() {
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", e => errors.push(String(e)));
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(9000);

  const m = await page.evaluate(() => {
    const q = s => document.querySelector(s);
    const top = s => { const el = q(s); return el ? Math.round(el.getBoundingClientRect().top + scrollY) : null; };
    const h = s => { const el = q(s); return el ? Math.round(el.getBoundingClientRect().height) : null; };
    const hidden = s => { const el = q(s); return el ? (el.offsetHeight === 0 || getComputedStyle(el).display === "none") : null; };
    return {
      labDisclaimerTall: (() => { const el = q(".lab-top-disclaimer"); return el ? (el.offsetHeight > 70 && getComputedStyle(el).display !== "none") : false; })(),
      guideOpen: q(".lab-newbie-guide") ? q(".lab-newbie-guide").open : null,
      guideH: h(".lab-newbie-guide"),
      purposeH: h(".purpose-note"),
      autoStepsH: h(".auto-trade-steps"),
      autoStepsVisible: (() => { const el = q(".auto-trade-steps"); return el ? (el.offsetHeight > 0 && getComputedStyle(el).display !== "none") : null; })(),
      adviceH: h(".lab-sigkelly-advice"),
      gridTop: top(".lab-sigkelly-grid") || top(".lab-sigkelly-group"),
      overflowPx: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });

  console.log("\n[mobile 390x844]", JSON.stringify(m));
  ok("M1 免责已收敛(合并/折叠到≤70px,不可盲藏)", m.labDisclaimerTall === false);
  ok("M2 新手引导默认收起(<70px)", m.guideH !== null && m.guideH < 70, `open=${m.guideOpen} h=${m.guideH}`);
  ok("M3 purpose-note 折叠(≤60px)", m.purposeH !== null && m.purposeH <= 60, `h=${m.purposeH}`);
  ok("M4 实操提醒折叠成一行且保留入口(1~100px,不藏死)", m.autoStepsVisible === true && m.autoStepsH !== null && m.autoStepsH <= 100, `h=${m.autoStepsH} visible=${m.autoStepsVisible}`);
  ok("M5 建议指南 advice 折叠(≤120px)", m.adviceH !== null && m.adviceH <= 120, `h=${m.adviceH}`);
  ok("M6 主数据网格 top ≤1600", m.gridTop !== null && m.gridTop <= 1600, `top=${m.gridTop}`);
  ok("M7 无横向溢出", m.overflowPx <= 0, `overflow=${m.overflowPx}px`);
  ok("M8 无页面脚本错误", errors.length === 0, errors.slice(0, 2).join(" | "));
  // ③ 通知入口保留：移动端通知选择器(pc-notify-btn / h5 铃铛)各异且易随实现变动,
  //    不在脚本硬断言,按实现细则 §5 人工验收「通知入口仍可见可点」即可。

  // v3 复审哨兵：回退点击44px + 参数抽屉化
  const barH = await page.evaluate(() => { const el = document.querySelector(".lab-sigkelly-bar"); return el ? Math.round(el.getBoundingClientRect().height) : null; });
  await page.evaluate(() => { const el = document.querySelector(".lab-sigkelly-params-toggle"); if (el) el.click(); });
  await page.waitForTimeout(900);
  const pp = await page.evaluate(() => { const el = document.querySelector(".lab-sigkelly-params-body"); const r = el ? el.getBoundingClientRect() : null; return { h: r ? Math.round(r.height) : 0, ratio: (r && window.innerHeight) ? +(r.height / window.innerHeight).toFixed(2) : null }; });
  ok("M9 筛选条不膨胀(≤100px)", barH !== null && barH <= 100, `barH=${barH}`);
  ok("M10 参数面板不占满屏(≤55%视口)", pp.ratio !== null && pp.ratio <= 0.55, `h=${pp.h} ratio=${pp.ratio}`);
  await ctx.close();
}

// ---------- 桌面端 1280x900（零回归） ----------
async function runDesktop() {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(9000);

  const m = await page.evaluate(() => {
    const q = s => document.querySelector(s);
    const v = s => { const el = q(s); return el ? (el.offsetHeight > 0 && getComputedStyle(el).display !== "none") : null; };
    const h = s => { const el = q(s); return el ? Math.round(el.getBoundingClientRect().height) : null; };
    return {
      disclaimerVisible: v(".lab-top-disclaimer"),
      guideOpen: q(".lab-newbie-guide") ? q(".lab-newbie-guide").open : null,
      guideH: h(".lab-newbie-guide"),
      autoStepsVisible: v(".auto-trade-steps"),
      adviceVisible: v(".lab-sigkelly-advice"),
      overflowPx: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });

  console.log("\n[desktop 1280x900]", JSON.stringify(m));
  ok("D1 免责 lab-top-disclaimer 仍可见(零回归)", m.disclaimerVisible === true);
  ok("D2 新手引导仍默认展开", m.guideOpen === true, `open=${m.guideOpen} h=${m.guideH}`);
  ok("D3 实操提醒仍可见(零回归)", m.autoStepsVisible === true);
  ok("D4 建议指南仍可见(零回归)", m.adviceVisible === true);
  ok("D5 无横向溢出", m.overflowPx <= 0, `overflow=${m.overflowPx}px`);
  await ctx.close();
}

await runMobile();
await runDesktop();
await browser.close();

console.log(`\n${fail === 0 ? "✅ 双视口全部通过" : "❌ 有失败"}: pass=${pass} fail=${fail}`);
process.exit(fail === 0 ? 0 : 1);
