#!/usr/bin/env node
// 验收 #100 sigkelly 渐进加载「y1 先渲染」生效(§5.4⑦ 同构对账: 无痕实测断言 y1 先渲染 + 数字与全量逐位一致)
// 用法: cd scripts/playwright-accept && node verify_sigkelly_y1_render.mjs
// 前置: 本地已起 http.server 于 8123 端口(静态站根目录, 需含已 build 的 min)
// 依赖: playwright-accept/node_modules
//
// 口径: 阶段1(y1 两片)重算完成 → 窗口期(_labKellyY1Ready && !_labKellyAllReady)立即就地渲染 y1 卡+全信号表,
//        推荐区(全周期 all 口径)因 all 未就绪显示「全量分片加载中」占位(不消费残缺数据 §23.15);
//        阶段2(其余14片)hold, 验证 y1 先渲染后再释放 → 全量重算覆盖 → y1 数字与阶段1 渲染逐 cell 一致。
//        DOM 文本一律用 textContent(卡内字体图标包 in li 会导致 innerText 计算为空)。
import { chromium } from "playwright";

const BASE = "http://localhost:8123";
const SLACK_MS = 800; // y1StatsReady 到抓 DOM 快照的余量(窗口期 onDone 为同步执行, 余量只防渲染批边界)

let nPass = 0, nFail = 0;
function check(name, cond, detail = "") {
  if (cond) nPass++; else nFail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
}

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.clearCookies(); // 无痕: 新 context 本无 localStorage, 再显式兜底

// 封闭网络: 只放行 localhost
await ctx.route(/^(?!.*localhost)/, (r) => r.abort());

const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 240)));

// 分片拦截: y1 两片(t2026/t2025)放行, 其余 14 片 hold 至 release
let released = false;
const releaseWaiters = [];
await page.route(/signal_kelly_trades_parts/, async (route) => {
  const m = /t(\d{4})\.json/.exec(route.request().url());
  const year = m ? m[1] : "";
  if (year === "2026" || year === "2025") { route.continue(); return; }
  if (released) { route.continue(); return; }
  await new Promise((r) => releaseWaiters.push(r));
  route.continue();
});

await page.goto(BASE + "/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 120000 });
const t0 = Date.now();
const sec = () => ((Date.now() - t0) / 1000).toFixed(1);

// ---- 阶段0: 静态 backtest 渲染回归(C3)----
let tStatic = 0;
for (let i = 0; i < 40; i++) {
  tStatic = await page.evaluate(() => document.querySelectorAll('.lab-sigkelly-card[data-quad="sig_main"] .lab-sigkelly-trade-row').length);
  if (tStatic > 0) break;
  await new Promise((r) => setTimeout(r, 500));
}
check("C3 阶段1 前静态 backtest 卡有交易行(回归)", tStatic > 0, `sig_main rows=${tStatic}`);

// ---- 阶段1: 等 y1 stats 就绪 + 窗口期渲染(先渲染)----
let t_y1stats = null, t_y1render = null;
let snapY1 = null;
while (Date.now() - t0 < 120000) {
  const d = await page.evaluate(() => {
    const fs = state.labSigKellyFeeStats;
    const y1StatsReady = !!(fs && fs.rating_high && fs.rating_high.y1);
    // 窗口期占位信号: 推荐区(全周期 all 口径)在阶段1 窗口期显示「全量分片加载中, 完成后自动补齐」(L11079)
    const afg = document.querySelector(".lab-sigkelly-afg-realtime");
    const afgText = afg ? afg.textContent.replace(/\s+/g, " ") : "";
    const windowed = afgText.includes("全量分片加载中");
    return { y1StatsReady, windowed };
  });
  if (d.y1StatsReady && t_y1stats === null) t_y1stats = sec();
  if (d.windowed && t_y1render === null) t_y1render = sec();
  if (t_y1render !== null) break;
  await new Promise((r) => setTimeout(r, 1000));
}
check("A0 y1 stats 阶段1 就绪", t_y1stats !== null, `t=${t_y1stats ?? "?"}s`);
check("A1 阶段1 完成后窗口期就地渲染触发(y1 先渲染)", t_y1render !== null,
  t_y1render !== null ? `t=${t_y1render}s 推荐区已切「全量分片加载中」占位(= 窗口期 onDone 已就地刷新 y1 卡+全信号表)` : `hold 超时, 未观察到窗口期渲染`);

if (t_y1render !== null) {
  await new Promise((r) => setTimeout(r, SLACK_MS));
  // 抓 y1 阶段渲染快照: 各 quad 卡的 y1 行 textContent
  snapY1 = await page.evaluate(() => {
    const out = {};
    document.querySelectorAll(".lab-sigkelly-card[data-quad]").forEach((card) => {
      const qk = card.getAttribute("data-quad");
      const rows = [...card.querySelectorAll(".lab-sigkelly-trade-row")];
      if (rows.length === 0) return;
      out[qk] = rows.map((r) => r.textContent.replace(/\s+/g, " ").trim());
    });
    return out;
  });
  const y1RowCount = Object.values(snapY1 || {}).reduce((a, v) => a + v.length, 0);
  check("A1b y1 阶段渲染各卡有交易行(非占位)", y1RowCount > 0, `quad 卡数=${Object.keys(snapY1 || {}).length}, 总行数=${y1RowCount}`);
}

// ---- 释放阶段2, 等全量重算覆盖 ----
let t_allstats = null;
if (t_y1render !== null) {
  released = true;
  releaseWaiters.forEach((r) => r());
  while (Date.now() - t0 < 360000) {
    const d = await page.evaluate(() => {
      const fs = state.labSigKellyFeeStats;
      const allStats = !!(window._labKellyAllReady && fs && fs.all && fs.all.all && fs.all.all.A && fs.all.all.A.n);
      return { allStats };
    });
    if (d.allStats && t_allstats === null) {
      t_allstats = sec();
      await new Promise((r) => setTimeout(r, SLACK_MS));
      break;
    }
    await new Promise((r) => setTimeout(r, 3000));
  }
  check("B0 全量重算覆盖完成", t_allstats !== null, `t=${t_allstats ?? "?"}s`);
  check("A2 y1 渲染早于全量完成(先渲染)", t_allstats !== null && Number(t_y1render) < Number(t_allstats), `y1@${t_y1render}s < all@${t_allstats ?? "?"}s`);
}

// ---- 断言 B: y1 阶段渲染 vs 全量后逐 cell 一致(同构对账)----
if (t_allstats !== null && snapY1) {
  const snapAll = await page.evaluate(() => {
    const out = {};
    document.querySelectorAll(".lab-sigkelly-card[data-quad]").forEach((card) => {
      const qk = card.getAttribute("data-quad");
      const rows = [...card.querySelectorAll(".lab-sigkelly-trade-row")];
      if (rows.length === 0) return;
      out[qk] = rows.map((r) => r.textContent.replace(/\s+/g, " ").trim());
    });
    return out;
  });
  const quads = new Set([...Object.keys(snapY1), ...Object.keys(snapAll)]);
  let mismatches = [];
  for (const qk of quads) {
    const a = snapY1[qk] || [], b = snapAll[qk] || [];
    if (a.length !== b.length) { mismatches.push(`${qk}: 行数 ${a.length} vs ${b.length}`); continue; }
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) {
        mismatches.push(`${qk} 行${i}: y1「${a[i].slice(0, 80)}」 vs all「${b[i].slice(0, 80)}」`);
        if (mismatches.length >= 5) break;
      }
    }
    if (mismatches.length >= 5) break;
  }
  check("B1 y1 阶段渲染 vs 全量后逐 cell 一致(同构对账)", mismatches.length === 0,
    mismatches.length === 0 ? `quads=${[...quads].join(",")} 逐行逐列逐位一致` : mismatches.join(" | "));
}

// ---- 回归 C: 全量完成后无占位残留 ----
if (t_allstats !== null) {
  const residue = await page.evaluate(() => {
    const host = document.querySelector(".lab-sigkelly-host");
    const txt = host ? host.textContent : "";
    return {
      afgPlaceholder: !!document.querySelector(".lab-sigkelly-afg-realtime .lab-custom-loading"),
      cardPlaceholder: [...document.querySelectorAll(".lab-sigkelly-card")].filter((c) => c.textContent.includes("⏳") && c.textContent.includes("分片")).length,
      anyCalc: txt.includes("计算中"),
      anyLoading: txt.includes("全量分片加载中"),
    };
  });
  check("C1 全量完成后无占位残留(afg/卡/计算中/全量加载中)", !residue.afgPlaceholder && residue.cardPlaceholder === 0 && !residue.anyCalc && !residue.anyLoading,
    JSON.stringify(residue));
}
check("C2 无 pageerror", pageErrors.length === 0, pageErrors.slice(0, 2).join(" | "));

await browser.close();
console.log(`\n===== ${nFail === 0 ? "ALL PASS" : nFail + " FAIL"} (${nPass} pass, ${nFail} fail) =====`);
process.exit(nFail === 0 ? 0 : 1);