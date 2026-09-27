#!/usr/bin/env node
// 实测时间线(2026-09-07): sigkelly 渐进加载全流程——2/2 片加载完成 / y1 渲染 / 全量补齐 / 补齐后是否再次灰蒙层锁屏(lab-custom-host--loading)
// 用法: cd scripts/playwright-accept && node timeline_sigkelly_silent_fill.mjs
// §5.4⑦ 页面实测锚点: 无痕 context(零 localStorage), 真实线上 ss.fx8.store, 全量放行分片
import { chromium } from "playwright";

const BASE = "https://ss.fx8.store";
const t0 = Date.now();
const tl = [];  // 时间线记录
const log = (tag, detail = "") => { tl.push({ t: +((Date.now() - t0) / 1000).toFixed(2), tag, detail }); };

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.clearCookies();
const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 240)));
page.on("console", (m) => {
  const txt = m.text();
  if (txt.includes("[sigkelly]") || txt.includes("全量") || txt.includes("分片")) log("console", txt.slice(0, 160));
});

// 注入时间线观测器: 轮询 300ms 记录里程碑
await page.addInitScript((t0) => {
  window.__tl = [];
  const log = (tag, detail) => window.__tl.push({ t: +((Date.now() - t0) / 1000).toFixed(2), tag, detail });
  setInterval(() => {
    try {
      const host = document.querySelector(".lab-sigkelly-host");
      if (!host) return;
      const loading = host.classList.contains("lab-custom-host--loading");
      if (loading !== window.__lastLoading) {
        window.__lastLoading = loading;
        log(loading ? "HOST_LOADING_ON" : "HOST_LOADING_OFF", "");
      }
      const prog = document.querySelector(".lab-sigkelly-all-loading");
      const progTxt = prog ? prog.textContent.replace(/\s+/g, " ").trim() : "";
      if (progTxt && progTxt !== window.__lastProg) { window.__lastProg = progTxt; log("PROG", progTxt); }
      const y1 = window._labKellyY1Ready, all = window._labKellyAllReady;
      if (y1 && !window.__y1) { window.__y1 = true; log("Y1_READY", ""); }
      if (all && !window.__all) { window.__all = true; log("ALL_READY", ""); }
      const rows = document.querySelectorAll('.lab-sigkelly-card[data-quad="sig_main"] .lab-sigkelly-trade-row').length;
      if (rows > 0 && rows !== window.__lastRows) { window.__lastRows = rows; log("MAIN_ROWS", String(rows)); }
    } catch (e) {}
  }, 300);
}, [Date.now() - t0 + 300000]);

log("NAVIGATE", BASE + "/index.html#lab?sub=sigkelly");
await page.goto(BASE + "/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 120000 });
log("DOM_READY", "");

// 等全量就绪(最长 6 分钟: 16 片 ~69MB 下载 + 全量重算)
let allReady = false;
for (let i = 0; i < 120; i++) {
  await new Promise((r) => setTimeout(r, 3000));
  const s = await page.evaluate(() => ({ all: !!window._labKellyAllReady, y1: !!window._labKellyY1Ready, loading: !!document.querySelector(".lab-sigkelly-host")?.classList.contains("lab-custom-host--loading") }));
  if (i % 5 === 0) log("POLL", `y1=${s.y1} all=${s.all} loading=${s.loading}`);
  if (s.all && !s.loading) { allReady = true; log("ALL_READY_AND_UNLOCKED", ""); }
  if (allReady) { await new Promise((r) => setTimeout(r, 4000)); break; }
}

const finalState = await page.evaluate(() => {
  const host = document.querySelector(".lab-sigkelly-host");
  const mainCard = document.querySelector('.lab-sigkelly-card[data-quad="sig_main"]');
  const allCard = document.querySelector('.lab-sigkelly-card[data-quad="all"]');
  const afg = document.querySelector(".lab-sigkelly-afg-realtime");
  return {
    loading: host ? host.classList.contains("lab-custom-host--loading") : null,
    y1Ready: window._labKellyY1Ready, allReady: window._labKellyAllReady,
    mainRows: mainCard ? mainCard.querySelectorAll(".lab-sigkelly-trade-row").length : -1,
    allRows: allCard ? allCard.querySelectorAll(".lab-sigkelly-trade-row").length : -1,
    afgPlaceholder: afg ? afg.textContent.includes("加载中") : null,
    leftoverCalc: host ? host.textContent.includes("计算中") : null,
  };
});
log("FINAL", JSON.stringify(finalState));

const pageTimeline = await page.evaluate(() => window.__tl || []);
const merged = [...tl, ...pageTimeline].sort((a, b) => a.t - b.t);
console.log("===== 时间线(秒)=====");
for (const e of merged) console.log(`${String(e.t).padStart(6)} ${e.tag}  ${e.detail}`);
console.log("\n===== 最终状态 =====");
console.log(JSON.stringify(finalState, null, 2));
console.log("pageerrors:", pageErrors.length ? pageErrors.slice(0, 3).join(" | ") : "无");
await browser.close();
