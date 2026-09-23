#!/usr/bin/env node
// 市场全景「按钮尺寸」验收（回退 a11y 点击≥44px 误伤）
// 用法: BASE_URL=https://ss.fx8.store node scripts/playwright-accept/accept_market_overview_buttons.mjs
// 断言: 移动端(概览页)顶部「每日速递/更多」两按钮恢复紧凑(≤32px) + 桌面端零回归。
// 注: 概览页 .h5-period-bar 本就 display:none(app.js:11130), 不在本脚本断言。
import { createRequire } from "module";
const require = createRequire("/Users/linhuichen/code/trade/scripts/playwright-accept/");
const { chromium } = require("playwright");
const BASE = process.env.BASE_URL || "https://ss.fx8.store";
const URL = BASE + "/#overview";
let pass = 0, fail = 0;
const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log(`${c ? "PASS" : "FAIL"}  ${n}${d ? `  [${d}]` : ""}`); };

const browser = await chromium.launch({ headless: true });

async function run(width, isMobile, tag) {
  const ctx = await browser.newContext({ viewport: { width, height: 844 }, isMobile, hasTouch: isMobile });
  const page = await ctx.newPage();
  const errs = []; page.on("pageerror", e => errs.push(String(e)));
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 90000 });
  await page.waitForTimeout(9000);
  const m = await page.evaluate(() => {
    const h = s => { const el = document.querySelector(s); return el ? Math.round(el.getBoundingClientRect().height) : null; };
    const w = s => { const el = document.querySelector(s); return el ? Math.round(el.getBoundingClientRect().width) : null; };
    return {
      periodH: h(".h5-periods button"),
      aiBtn: { w: w(".summary-ai-btn"), h: h(".summary-ai-btn") },
      histBtn: { w: w(".summary-history-btn"), h: h(".summary-history-btn") },
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
  console.log(`\n[${tag} ${width}x844]`, JSON.stringify(m));
  if (isMobile) {
    ok(`${tag} M1 每日速递按钮恢复紧凑(≤32px, 桌面24 为基准)`, m.aiBtn.h !== null && m.aiBtn.h <= 32, `h=${m.aiBtn.h}`);
    ok(`${tag} M2 更多按钮恢复紧凑(≤32px)`, m.histBtn.h !== null && m.histBtn.h <= 32, `h=${m.histBtn.h}`);
    ok(`${tag} M3 无横向溢出`, m.overflow <= 0, `overflow=${m.overflow}px`);
    ok(`${tag} M4 无页面脚本错误`, errs.length === 0, errs.slice(0,2).join(" | "));
  } else {
    ok(`${tag} D1 周期按钮存在(零回归)`, m.periodH !== null, `h=${m.periodH}`);
    ok(`${tag} D2 速递/更多按钮存在(零回归)`, m.aiBtn.h !== null && m.histBtn.h !== null);
    ok(`${tag} D3 无横向溢出`, m.overflow <= 0, `overflow=${m.overflow}px`);
  }
  await ctx.close();
}

await run(390, true, "mobile");
await run(1280, false, "desktop");
await browser.close();
console.log(`\n${fail === 0 ? "✅ 全部通过" : "❌ 有失败"}: pass=${pass} fail=${fail}`);
process.exit(fail === 0 ? 0 : 1);
