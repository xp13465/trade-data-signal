#!/usr/bin/env node
// Phase A 基线采集(最终态版, 2026-09-21): 等待页面全史加载完成并重渲染到最终态(G 行含「P≤3d」=GIH 管位计算完成)再录, 避免中间态。
// 固定口径: 模式=G、周期=y1/all、K=1、S06默认、费率默认(etf_main)。
import { createRequire } from "module";
import fs from "node:fs";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = "http://localhost:8231";
// OUT 默认=改造前基线(Phase A), 改造后重录用 BASELINE_OUT env 覆盖(如 Phase B 对比路径), 防覆盖改造前基线。
const OUT = process.env.BASELINE_OUT || "/tmp/kelly-unique-phasea-out/baseline-prebuild.json";

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 3000 } });
await ctx.clearCookies();
await ctx.route(/^(?!http:\/\/localhost:8231)/, (r) => r.abort());

const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 200)));

const snap = { sim: {}, lab: {} };

// ============ 1) sim 弹窗(首页) ============
await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded", timeout: 90000 });
let btn = null;
for (let i = 0; i < 60; i++) { btn = await page.$('.sig-kbtn-sim'); if (btn) break; await page.waitForTimeout(1000); }
await btn.click();
await page.waitForTimeout(2000);
await page.evaluate(() => {
  const modal = document.getElementById("simBacktestModal");
  const sel = modal.querySelector(".sim-mode-sel");
  if (sel) { sel.value = "G"; sel.dispatchEvent(new Event("change", { bubbles: true })); }
  const s = modal.querySelector(".sim-date-start");
  const e = modal.querySelector(".sim-date-end");
  const now = new Date();
  const pad = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");
  const oneY = new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());
  if (s && e) { s.value = pad(oneY); e.value = pad(now); s.dispatchEvent(new Event("change", { bubbles: true })); e.dispatchEvent(new Event("change", { bubbles: true })); }
});
for (let i = 0; i < 40; i++) {
  await page.waitForTimeout(1000);
  const done = await page.evaluate(() => {
    const modal = document.getElementById("simBacktestModal");
    const sum = modal.querySelector(".sim-summary");
    const rows = modal.querySelectorAll(".sim-tbl tbody tr").length;
    return { ready: !!sum && sum.textContent.includes("累积收益率") && rows > 0, rows };
  });
  if (done.ready) { snap.sim._rows = done.rows; break; }
}
snap.sim.g = await page.evaluate(() => {
  const modal = document.getElementById("simBacktestModal");
  const sum = modal.querySelector(".sim-summary");
  const head = modal.querySelector(".sim-tbl thead");
  const first = modal.querySelector(".sim-tbl tbody tr");
  const last = [...modal.querySelectorAll(".sim-tbl tbody tr")].pop();
  const fee = modal.querySelector(".simbt-fee-bar");
  const modeSel = modal.querySelector(".sim-mode-sel");
  const fadeSel = modal.querySelector(".sim-fade-mode-sel");
  const kBtn = modal.querySelector(".sim-kbtn.active");
  const netAssetNote = modal.querySelector(".sim-netasset-note");
  return {
    mode: modeSel ? modeSel.value : null,
    fadeMode: fadeSel ? fadeSel.value : null,
    K: kBtn ? kBtn.dataset.k : null,
    feeText: fee ? fee.textContent.trim().slice(0, 60) : null,
    dateStart: (modal.querySelector(".sim-date-start") || {}).value,
    dateEnd: (modal.querySelector(".sim-date-end") || {}).value,
    summary: sum ? sum.textContent.replace(/\s+/g, " ").trim() : null,
    tableHead: head ? head.textContent.replace(/\s+/g, " ").trim().slice(0, 220) : null,
    firstRow: first ? first.textContent.replace(/\s+/g, " ").trim().slice(0, 220) : null,
    lastRow: last ? last.textContent.replace(/\s+/g, " ").trim().slice(0, 220) : null,
    netassetHead: (modal.querySelector(".sim-netasset-head") || {}).textContent || null,
    netassetNote: netAssetNote ? netAssetNote.textContent.trim() : null,
    s06Note: (modal.querySelector(".sim-s06-note") || {}).textContent || null,
  };
});

// ============ 2) lab 凯利页(等待最终态) ============
const labPage = await ctx.newPage();
labPage.on("pageerror", (e) => pageErrors.push("[lab] " + String(e).slice(0, 200)));
await labPage.goto(BASE + "/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 90000 });
// 等待 G 行进入最终态(GIH 管位计算完成 = G 行含「P≤3d」), 最多 60s
let finalState = false;
for (let i = 0; i < 60; i++) {
  await labPage.waitForTimeout(1000);
  finalState = await labPage.evaluate(() => {
    const t = document.querySelector("table.lab-sigkelly-wide-table");
    if (!t) return false;
    const rows = [...t.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((c) => c.textContent.replace(/\s+/g, " ").trim()));
    const g = rows.find((r) => r[0].startsWith("G"));
    return !!g && g[0].includes("P≤3d") && document.querySelectorAll(".lab-sigkelly-trade-row").length > 100;
  });
  if (finalState) break;
}
snap.lab._finalStateReached = finalState;

snap.lab.toolbar = await labPage.evaluate(() => {
  const q = (s) => { const el = document.querySelector(s); return el ? el.textContent.replace(/\s+/g, " ").trim().slice(0, 160) : null; };
  const pa = document.querySelector(".lab-sigkelly-period-btn.active");
  return {
    periodActive: pa && pa.dataset ? pa.dataset.period : null,
    kActive: (() => { const b = document.querySelector(".lab-sigkelly-kbtn.active"); return b ? b.dataset.k : null; })(),
    feeActive: (() => { const b = document.querySelector(".lab-sigkelly-fee-btn.active"); return b ? b.dataset.fee : null; })(),
    buyBasisActive: (() => { const b = document.querySelector(".lab-sigkelly-buybasis-btn.active"); return b ? b.dataset.basis : null; })(),
    barSummary: q(".lab-sigkelly-bar-summary"),
    tRows: document.querySelectorAll(".lab-sigkelly-trade-row").length,
  };
});
snap.lab.ghiTable = await labPage.evaluate(() => {
  const el = [...document.querySelectorAll("table")].find((t) => /真实权威数收益率/.test(t.textContent) && /所需本金/.test(t.textContent));
  if (!el) return null;
  const trs = [...el.querySelectorAll("tbody tr, thead tr")].map((tr) => [...tr.querySelectorAll("th,td")].map((c) => c.textContent.replace(/\s+/g, " ").trim()));
  return trs;
});
snap.lab.advice = await labPage.evaluate(() => {
  const s = document.querySelector(".lab-sigkelly-advice-summary-short");
  return s ? s.textContent.trim().slice(0, 200) : null;
});
snap.lab.gFullY1 = await labPage.evaluate(() => {
  const t = document.querySelector("table.lab-sigkelly-wide-table");
  if (!t) return null;
  const rows = [...t.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((c) => c.textContent.replace(/\s+/g, " ").trim()));
  const g = rows.find((r) => r[0].startsWith("G"));
  const head = t.querySelector("thead");
  return {
    period: (() => { const b = document.querySelector(".lab-sigkelly-period-btn.active"); return b ? b.dataset.period : null; })(),
    head: head ? head.textContent.replace(/\s+/g, " ").trim() : null,
    gRow: g || null,
  };
});

// 切周期 all, 等最终态
await labPage.evaluate(() => {
  const btn = [...document.querySelectorAll(".lab-sigkelly-period-btn")].find((b) => b.dataset.period === "all");
  if (btn) btn.click();
});
let allFinal = false;
for (let i = 0; i < 60; i++) {
  await labPage.waitForTimeout(1000);
  allFinal = await labPage.evaluate(() => {
    const active = (() => { const b = document.querySelector(".lab-sigkelly-period-btn.active"); return b ? b.dataset.period : null; })();
    if (active !== "all") return false;
    const t = document.querySelector("table.lab-sigkelly-wide-table");
    if (!t) return false;
    const rows = [...t.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((c) => c.textContent.replace(/\s+/g, " ").trim()));
    const g = rows.find((r) => r[0].startsWith("G"));
    return !!g && g[0].includes("P≤3d");
  });
  if (allFinal) break;
}
snap.lab._allFinalReached = allFinal;
snap.lab.all = await labPage.evaluate(() => {
  const q = (s) => { const el = document.querySelector(s); return el ? el.textContent.replace(/\s+/g, " ").trim() : null; };
  const tables = [...document.querySelectorAll(".lab-sigkelly-table")];
  const finalT = tables.find((t) => /最后结果|全信号/.test(t.textContent || ""));
  const wide = document.querySelector("table.lab-sigkelly-wide-table");
  let gRow = null;
  if (wide) {
    const rows = [...wide.querySelectorAll("tbody tr")].map((tr) => [...tr.children].map((c) => c.textContent.replace(/\s+/g, " ").trim()));
    gRow = rows.find((r) => r[0].startsWith("G")) || null;
  }
  return {
    periodActive: (() => { const b = document.querySelector(".lab-sigkelly-period-btn.active"); return b ? b.dataset.period : null; })(),
    finalTableText: finalT ? finalT.textContent.replace(/\s+/g, " ").trim().slice(0, 2500) : null,
    finalTableHead: finalT && finalT.querySelector("thead") ? finalT.querySelector("thead").textContent.replace(/\s+/g, " ").trim().slice(0, 400) : null,
    finalTableFirstRow: finalT && finalT.querySelector("tbody tr") ? finalT.querySelector("tbody tr").textContent.replace(/\s+/g, " ").trim().slice(0, 400) : null,
    gFullRowAll: gRow,
    tradeRows: document.querySelectorAll(".lab-sigkelly-trade-row").length,
  };
});

snap.pageErrors = pageErrors;
fs.writeFileSync(OUT, JSON.stringify(snap, null, 2));
console.log("WROTE", OUT);
console.log("sim.summary:", snap.sim.g ? snap.sim.g.summary : null);
console.log("lab.ghiTable:", JSON.stringify(snap.lab.ghiTable));
console.log("lab.gFullY1:", JSON.stringify(snap.lab.gFullY1));
console.log("lab.all.gFullRowAll:", JSON.stringify(snap.lab.all.gFullRowAll));
console.log("_final:", snap.lab._finalStateReached, snap.lab._allFinalReached, "tRows:", snap.lab.toolbar.tRows);
await browser.close();
process.exit(0);
