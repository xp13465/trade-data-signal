#!/usr/bin/env node
// Phase C(2026-09-21)改造后页面实测: lab 凯利页「最后结果」G 行/全信号表关键数字, 与基线文档
// docs/kelly/analysis/kelly-unique-frontend-baseline-20260920.md diff 空。
// 固定口径: 模式=G、周期=y1/all、K=1、S06 默认、费率默认(etf_main)、buyBasis 默认(next_day_open)。
// 最终态判定(基线文档 §1): G 行名称含「P≤3d」且 .lab-sigkelly-trade-row 数量 >100。
// 本机改造后 lab.js 走 unique 全量(signal_kelly_trades_unique.json, localhost 兜底);
// 渐进分片 unique_t*.json 本地未部署 → 阶段1 失败回退全量, 属面上测试的「全量兜底」路径(数值与旧全量一致)。
import { createRequire } from "module";
import fs from "node:fs";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = "http://localhost:8231";
const OUT = "/tmp/kelly-unique-phasea-out/capture-phaseC-lab.json";

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 3000 } });
await ctx.clearCookies();
await ctx.route(/^(?!http:\/\/localhost:8231)/, (r) => r.abort());

const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 200)));
page.on("console", (m) => { if (m.type() === "error") pageErrors.push("[console] " + m.text().slice(0, 200)); });

const snap = {};
await page.goto(BASE + "/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 90000 });

const waitFinal = async (periodWanted) => {
  for (let i = 0; i < 120; i++) {
    await page.waitForTimeout(1000);
    const st = await page.evaluate((pw) => {
      const active = (() => { const b = document.querySelector(".lab-sigkelly-period-btn.active"); return b ? b.dataset.period : null; })();
      if (pw && active !== pw) return { done: false };
      const t = document.querySelector("table.lab-sigkelly-wide-table");
      if (!t) return { done: false, hint: "no-table" };
      const rows = [...t.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((c) => c.textContent.replace(/\s+/g, " ").trim()));
      const g = rows.find((r) => r[0].startsWith("G"));
      const done = !!g && g[0].includes("P≤3d") && document.querySelectorAll(".lab-sigkelly-trade-row").length > 100;
      return { done, gFound: !!g, gName: g ? g[0] : null, tradeRows: document.querySelectorAll(".lab-sigkelly-trade-row").length };
    }, periodWanted);
    if (st.done) return st;
  }
  return { done: false };
};

// y1
snap.y1 = await waitFinal(null);
snap.y1.view = await page.evaluate(() => {
  const q = (s) => { const el = document.querySelector(s); return el ? el.textContent.replace(/\s+/g, " ").trim() : null; };
  const pa = document.querySelector(".lab-sigkelly-period-btn.active");
  const wide = document.querySelector("table.lab-sigkelly-wide-table");
  const rows = wide ? [...wide.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((c) => c.textContent.replace(/\s+/g, " ").trim())) : [];
  const g = rows.find((r) => r[0].startsWith("G")) || null;
  return {
    periodActive: pa ? pa.dataset.period : null,
    kActive: (() => { const b = document.querySelector(".lab-sigkelly-kbtn.active"); return b ? b.dataset.k : null; })(),
    feeActive: (() => { const b = document.querySelector(".lab-sigkelly-fee-btn.active"); return b ? b.dataset.fee : null; })(),
    buyBasisActive: (() => { const b = document.querySelector(".lab-sigkelly-buybasis-btn.active"); return b ? b.dataset.basis : null; })(),
    barSummary: q(".lab-sigkelly-bar-summary"),
    tRows: document.querySelectorAll(".lab-sigkelly-trade-row").length,
    gRow: g,
    wideHead: wide && wide.querySelector("thead") ? wide.querySelector("thead").textContent.replace(/\s+/g, " ").trim() : null,
  };
});
snap.y1.ghiTable = await page.evaluate(() => {
  const el = [...document.querySelectorAll("table")].find((t) => /真实权威数收益率/.test(t.textContent) && /所需本金/.test(t.textContent));
  if (!el) return null;
  return [...el.querySelectorAll("tbody tr, thead tr")].map((tr) => [...tr.querySelectorAll("th,td")].map((c) => c.textContent.replace(/\s+/g, " ").trim()));
});

// 切 all
await page.evaluate(() => {
  const btn = [...document.querySelectorAll(".lab-sigkelly-period-btn")].find((b) => b.dataset.period === "all");
  if (btn) btn.click();
});
snap.all = await waitFinal("all");
snap.all.view = await page.evaluate(() => {
  const wide = document.querySelector("table.lab-sigkelly-wide-table");
  const rows = wide ? [...wide.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((c) => c.textContent.replace(/\s+/g, " ").trim())) : [];
  const g = rows.find((r) => r[0].startsWith("G")) || null;
  return {
    periodActive: (() => { const b = document.querySelector(".lab-sigkelly-period-btn.active"); return b ? b.dataset.period : null; })(),
    gRow: g,
    allRowsSample: rows.slice(0, 4),
    tRows: document.querySelectorAll(".lab-sigkelly-trade-row").length,
  };
});
snap.all.ghiTable = await page.evaluate(() => {
  const el = [...document.querySelectorAll("table")].find((t) => /真实权威数收益率/.test(t.textContent) && /所需本金/.test(t.textContent));
  if (!el) return null;
  return [...el.querySelectorAll("tbody tr, thead tr")].map((tr) => [...tr.querySelectorAll("th,td")].map((c) => c.textContent.replace(/\s+/g, " ").trim()));
});

snap.pageErrors = pageErrors;
fs.writeFileSync(OUT, JSON.stringify(snap, null, 2));
console.log("WROTE", OUT);
console.log("y1 done:", snap.y1.done, "period:", snap.y1.view.periodActive, "tRows:", snap.y1.view.tRows);
console.log("y1 G row:", JSON.stringify(snap.y1.view.gRow));
console.log("all done:", snap.all.done, "period:", snap.all.view.periodActive, "tRows:", snap.all.view.tRows);
console.log("all G row:", JSON.stringify(snap.all.view.gRow));
console.log("GHI y1:", JSON.stringify((snap.y1.ghiTable || []).slice(0, 4)));
console.log("pageErrors:", snap.pageErrors.length > 0 ? snap.pageErrors.slice(0, 5) : "无");
await browser.close();
process.exit(0);