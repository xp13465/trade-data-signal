#!/usr/bin/env node
// 市场全景「按钮尺寸」验收（回退 a11y 点击≥44px 误伤）
// 用法: BASE_URL=https://ss.fx8.store node scripts/playwright-accept/accept_market_overview_buttons.mjs
// 断言:
//   - 移动端概览页 顶部「每日速递/更多」两按钮恢复紧凑(≤32px)
//   - 移动端切「大盘/情绪」tab(market=指数表现)后 .h5-periods 周期钮恢复紧凑(≤32px,
//     第 2 处回退点: .h5-periods button 删 min-height:44px 的量化断言; 概览 tab 下 .h5-period-bar
//     display:none(app.js:11132), 必须切到显示周期栏的 tab 才测得到真实高度)
//   - 桌面端零回归(概览 tab 周期栏按设计保持隐藏 = 高度 0)
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
  const readStats = () => page.evaluate(() => {
    const h = s => { const el = document.querySelector(s); return el ? Math.round(el.getBoundingClientRect().height) : null; };
    const w = s => { const el = document.querySelector(s); return el ? Math.round(el.getBoundingClientRect().width) : null; };
    return {
      periodH: h(".h5-periods button"),
      barH: h(".h5-period-bar"),
      aiBtn: { w: w(".summary-ai-btn"), h: h(".summary-ai-btn") },
      histBtn: { w: w(".summary-history-btn"), h: h(".summary-history-btn") },
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
  const m = await readStats();
  console.log(`\n[${tag} ${width}x844]`, JSON.stringify(m));
  if (isMobile) {
    ok(`${tag} M1 每日速递按钮恢复紧凑(≤32px, 桌面24 为基准)`, m.aiBtn.h !== null && m.aiBtn.h <= 32, `h=${m.aiBtn.h}`);
    ok(`${tag} M2 更多按钮恢复紧凑(≤32px)`, m.histBtn.h !== null && m.histBtn.h <= 32, `h=${m.histBtn.h}`);
    ok(`${tag} M3 概览页无横向溢出`, m.overflow <= 0, `overflow=${m.overflow}px`);
    ok(`${tag} M4 无页面脚本错误`, errs.length === 0, errs.slice(0,2).join(" | "));
    // 盲区1: D1 原为 DOM 存在性断言(概览 tab .h5-period-bar 隐藏, periodH=0 恒假阳性)。
    // 改为: 切到显示周期栏的 market tab(指数表现=大盘), 测 .h5-periods button 真实移动端高度。
    // 同时覆盖盲区2: 第 2 处回退点(.h5-periods button 删 min-height)的量化断言。
    if (m.barH !== null && m.barH === 0) {
      // 首次访问会弹 onboarding 引导(rule-modal), 遮罩拦截底部导航点击; 先 dismiss 所有可见弹窗
      await page.evaluate(() => {
        document.querySelectorAll(".rule-modal:not(.hidden)").forEach(ml => ml.classList.add("hidden"));
      });
      await page.click('nav.h5-bottomnav button[data-tab="market"]');
      await page.waitForFunction(() => {
        const bar = document.querySelector(".h5-period-bar");
        const btn = document.querySelector(".h5-periods button");
        return bar && btn && bar.getBoundingClientRect().height > 0 && btn.getBoundingClientRect().height > 0;
      }, { timeout: 30000 });
      await page.waitForTimeout(1500);
      const m2 = await readStats();
      ok(`${tag} M5 周期按钮恢复紧凑(≤32px, 切 market tab 真实高度`, m2.periodH !== null && m2.periodH <= 32, `h=${m2.periodH}`);
      ok(`${tag} M6 market tab 无横向溢出`, m2.overflow <= 0, `overflow=${m2.overflow}px`);
    } else {
      ok(`${tag} M5/M6 周期按钮(前置: 概览周期栏应为隐藏, barH=0)`, m.barH !== null && m.barH === 0, `barH=${m.barH}`);
    }
  } else {
    // 盲区1 修订: 桌面端概览 tab 周期栏设计上保持隐藏(base CSS .h5-period-bar{display:none}),
    // 原 D1「周期按钮存在」是假断言(恒 null→PASS)。改为名符其实的零回归断言: 概览页周期栏按设计隐藏。
    ok(`${tag} D1 概览页周期栏保持隐藏(零回归, 高度0)`, m.barH !== null && m.barH === 0, `barH=${m.barH} periodH=${m.periodH}`);
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