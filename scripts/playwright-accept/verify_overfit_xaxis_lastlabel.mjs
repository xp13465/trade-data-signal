#!/usr/bin/env node
// #147 过拟合卡 x 轴末点标签验收(2026-09-30, 右锚定采样 + 按实际刻度串量宽 step)
// 主证据(用户视角): lite SVG 两图最右可见标签 == 渲染层数据末点日期; hover 末点 tooltip 同日。
// 不重叠硬断言: DOM getBoundingClientRect 实测相邻日期标签矩形不相交(保守: 中心距 >= 文本实测宽)。
// 五窗口: 统计口径 roll 切 10/15/30/60/100 逐个验证(两图 xLabels 长度随窗口变化, xStep 自适应)。
// 双渲染路径: lite 自研引擎 + echarts fallback(⚡ 关闭)各验一次。
// 回归: 开关默认关时, 全站其他 lite 图 x 标签(位置+文本)与基线(main 未改版)逐个一致; 两图曲线/数据末点未被动。
import { chromium } from "playwright";
import fs from "fs";

const WT = "/Users/linhuichen/code/trade/.claude/worktrees/agent-a25e29c4db5dba109";
const BASE = "http://localhost:8127/static-site";
const SRC_NEW = fs.readFileSync(WT + "/static-site/app.js", "utf8");       // 改后(forceLastLabel 两图开启, 右锚定 + xStep 量宽)
const SRC_BASE = fs.readFileSync("/tmp/app_main_baseline.js", "utf8");     // 基线(main, 无 forceLastLabel)
const SRC_I18N = fs.readFileSync(WT + "/static-site/i18n.js", "utf8");
const readJ = (f) => fs.readFileSync("/tmp/" + f, "utf8");
const WINDOWS = [10, 15, 30, 60, 100];

let nPass = 0, nFail = 0;
function check(name, cond, detail = "") {
  if (cond) nPass++; else nFail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
}

// ---- 建页工具: 注入指定 app.js + 线上 overfit 数据, 无痕(localStorage 可选手动设) ----
async function openPage(browser, appSrc, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1400 } });
  await ctx.clearCookies();
  await ctx.addInitScript(() => {
    try {
      localStorage.setItem("onboarding_done", "1");   // 跳过首次访问引导弹窗(否则挡 roll 按钮点击)
      localStorage.setItem("nt_intro_done", "1");     // 跳过汪汪队首次解释弹窗(delay 2s, 同样挡点击)
    } catch (e) {}
  });
  if (opts.lightweight === false) {
    await ctx.addInitScript(() => { try { localStorage.setItem("sitecfg:charts.lightweight", "false"); } catch (e) {} });
  }
  const pageErrors = [];
  const page = await ctx.newPage();
  page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 200)));
  await ctx.route(/^(?!.*localhost)/, (r) => r.abort());
  await ctx.route(/app\.min\.js(\?.*)?$/, (r) => r.fulfill({ contentType: "application/javascript", body: appSrc }));
  await ctx.route(/i18n\.js(\?.*)?$/, (r) => r.fulfill({ contentType: "application/javascript", body: SRC_I18N }));
  await ctx.route(/overfit_monitor\.json(\?.*)?$/, (r) => r.fulfill({ contentType: "application/json", body: readJ("overfit_online.json") }));
  await ctx.route(/overfit_monitor_ext\.json(\?.*)?$/, (r) => r.fulfill({ contentType: "application/json", body: readJ("overfit_ext_online.json") }));
  await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded", timeout: 120000 });
  // 等两图渲染 + roll 按钮在位; 期间跳过首次访问/汪汪队引导弹窗(会挡按钮点击)
  for (let i = 0; i < 60; i++) {
    await page.evaluate(() => {
      try {
        localStorage.setItem("onboarding_done", "1");
        localStorage.setItem("nt_intro_done", "1");
        const m = document.querySelector(".onboarding-modal:not(.hidden)");
        if (m) { m.classList.add("hidden"); const s = m.querySelector(".onboarding-skip"); if (s) s.click(); document.body.style.overflow = ""; }
      } catch (e) {}
    }).catch(() => {});
    const r = await page.evaluate(() => !!(document.querySelector("#overfit-acc-chart svg") && document.querySelector("#overfit-risk-chart svg") && document.querySelector('[data-overfit-roll="10"]')));
    if (r) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return { ctx, page, pageErrors };
}

// ---- 采集: 每张 lite 图 DOM 实测日期标签(文本 + 中心x + 文本宽) + 两图 cfg ----
function collectLite(page) {
  return page.evaluate(() => {
    const out = { lites: [], acc: null, risk: null };
    const measure = (txt) => {
      const c = document.createElement("canvas").getContext("2d");
      c.font = "12px sans-serif";
      return c.measureText(txt).width;
    };
    const renderers = (typeof _lwRenderers !== "undefined") ? Array.from(_lwRenderers.keys()) : [];
    renderers.forEach((el) => {
      const svg = el.querySelector("svg.lw-svg");
      const lbls = [];
      if (svg) {
        Array.from(svg.querySelectorAll("text")).forEach((t) => {
          const txt = t.textContent;
          if (!/^\d{8}$/.test(txt)) return;
          const r = t.getBoundingClientRect();
          const cxp = (r.left + r.right) / 2;
          lbls.push({ txt, x: cxp, w: r.width || measure(txt), svgX: parseFloat(t.getAttribute("x")) });
        });
        lbls.sort((a, b) => a.x - b.x);
      }
      const isAcc = el.id === "overfit-acc-chart";
      const isRisk = el.id === "overfit-risk-chart";
      out.lites.push({ id: el.id || "", hasSvg: !!svg, lbls, isOverfit: isAcc || isRisk });
      if (isAcc && typeof _lwCfgMap !== "undefined") {
        const c = _lwCfgMap.get(el);
        out.acc = c ? { n: c.xLabels.length, last: c.xLabels[c.xLabels.length - 1], forceLastLabel: c.forceLastLabel, xStep: c.xStep, seriesLen: (c.series || []).map((s) => (s.data || []).length) } : null;
      }
      if (isRisk && typeof _lwCfgMap !== "undefined") {
        const c = _lwCfgMap.get(el);
        out.risk = c ? { n: c.xLabels.length, last: c.xLabels[c.xLabels.length - 1], forceLastLabel: c.forceLastLabel, xStep: c.xStep, seriesLen: (c.series || []).map((s) => (s.data || []).length) } : null;
      }
    });
    const find = (id) => out.lites.find((l) => l.id === id);
    out.accLbls = find("overfit-acc-chart") ? find("overfit-acc-chart").lbls : [];
    out.riskLbls = find("overfit-risk-chart") ? find("overfit-risk-chart").lbls : [];
    return out;
  });
}

// 不重叠断言: 相邻标签矩形不相交(保守: 中心距 >= 两标签文本宽中较大者)。
// 返回 {ok, worst, gaps, widths, n} 供报告(主控要每窗口实测间距 vs 文本宽 + 标签数)。
function overlapReport(lbls) {
  const report = { ok: true, worst: null, pairs: [], n: lbls.length };
  for (let i = 1; i < lbls.length; i++) {
    const gap = lbls[i].x - lbls[i - 1].x;
    const need = Math.max(lbls[i - 1].w, lbls[i].w);
    const ok = gap >= need;
    if (!ok) report.ok = false;
    report.pairs.push({ a: lbls[i - 1].txt, b: lbls[i].txt, gap: +gap.toFixed(1), need: +need.toFixed(1), ok });
    if (!report.worst || need - gap > report.worst.need - report.worst.gap) report.worst = { a: lbls[i - 1].txt, b: lbls[i].txt, gap: +gap.toFixed(1), need: +need.toFixed(1) };
  }
  return report;
}
function checkOverlap(rp, name, win) {
  check(`窗口${win}[${name}] 全部相邻标签矩形不相交`, rp.ok, rp.worst ? `最差: ${rp.worst.a}->${rp.worst.b} 间距${rp.worst.gap} 需≥${rp.worst.need} (n=${rp.n})` : `n=${rp.n} 全过`);
}

// ---- 悬停末点读 tooltip(用户视角) ----
async function hoverLastTooltip(page, id) {
  return page.evaluate(async (id) => {
    const svg = document.querySelector(id + " svg.lw-svg");
    if (!svg) return { found: false };
    svg.scrollIntoView({ block: "center" });
    const cfg = _lwCfgMap.get(document.querySelector(id));
    if (!cfg) return { found: false, cfgMissing: true };
    const rect = svg.getBoundingClientRect();
    const vbW = parseFloat(svg.getAttribute("viewBox").split(" ")[2]) || rect.width;
    const n = cfg.xLabels.length;
    const i1 = n - 1;
    const PL = cfg.pl != null ? cfg.pl : 55, PR = cfg.pr != null ? cfg.pr : 20;
    const bg = !!cfg.boundaryGap;
    const iw = vbW - PL - PR;
    const unitW = bg ? (iw / n) : (iw / Math.max(1, n - 1));
    const px = bg ? PL + (i1 + 0.5) * unitW : PL + i1 * unitW;
    const screenX = rect.left + px * (rect.width / vbW);
    const screenY = rect.top + rect.height / 2;
    return { found: true, screenX, screenY, last: cfg.xLabels[i1] };
  }, id);
}

const browser = await chromium.launch({ headless: true });

// ================= ① lite 路径(改后 app.js) · 五窗口逐个 =================
const lite = await openPage(browser, SRC_NEW);
const accWinN = {}, riskWinN = {}, accWinLast = {}, riskWinLast = {};
for (const win of WINDOWS) {
  // 切 roll 统计口径按钮(与用户点击同路径 → card click handler → syncOverfitCharts 重绘两图)
  await lite.page.click(`[data-overfit-roll="${win}"]`);
  await new Promise((r) => setTimeout(r, 400));
  const lit = await collectLite(lite.page);
  check(`窗口${win} acc 图 forceLastLabel 已开启`, lit.acc && lit.acc.forceLastLabel === true, `forceLastLabel=${lit.acc && lit.acc.forceLastLabel}`);
  check(`窗口${win} risk 图 forceLastLabel 已开启`, lit.risk && lit.risk.forceLastLabel === true, `forceLastLabel=${lit.risk && lit.risk.forceLastLabel}`);
  check(`窗口${win} acc 数据末点=最右标签`, lit.acc && lit.acc.last && lit.accLbls.length && lit.accLbls[lit.accLbls.length - 1].txt === lit.acc.last, `dataLast=${lit.acc && lit.acc.last} right=${lit.accLbls.length ? lit.accLbls[lit.accLbls.length - 1].txt : "-"} xLabelsN=${lit.acc && lit.acc.n}`);
  check(`窗口${win} risk 数据末点=最右标签`, lit.risk && lit.risk.last && lit.riskLbls.length && lit.riskLbls[lit.riskLbls.length - 1].txt === lit.risk.last, `dataLast=${lit.risk && lit.risk.last} right=${lit.riskLbls.length ? lit.riskLbls[lit.riskLbls.length - 1].txt : "-"} xLabelsN=${lit.risk && lit.risk.n}`);
  checkOverlap(overlapReport(lit.accLbls), "acc", win);
  checkOverlap(overlapReport(lit.riskLbls), "risk", win);
  accWinN[win] = { xN: lit.acc && lit.acc.n, lblN: lit.accLbls.length, xStep: lit.acc && lit.acc.xStep };
  riskWinN[win] = { xN: lit.risk && lit.risk.n, lblN: lit.riskLbls.length, xStep: lit.risk && lit.risk.xStep };
  accWinLast[win] = lit.accLbls.length ? lit.accLbls[lit.accLbls.length - 1].txt : "-";
  riskWinLast[win] = lit.riskLbls.length ? lit.riskLbls[lit.riskLbls.length - 1].txt : "-";
}
check("①lite 路径全程无 pageerror", lite.pageErrors.length === 0, lite.pageErrors.join(" / "));

// 截图留档(默认 60 窗口, 用户视角)
const accSvg = lite.page.locator("#overfit-acc-chart svg.lw-svg").first();
const riskSvg = lite.page.locator("#overfit-risk-chart svg.lw-svg").first();
await accSvg.screenshot({ path: "/tmp/xaxis147-acc-lite.png" });
await riskSvg.screenshot({ path: "/tmp/xaxis147-risk-lite.png" });

// hover 末点 tooltip 断言(默认 60 窗口)
for (const [id, label] of [["#overfit-acc-chart", "acc"], ["#overfit-risk-chart", "risk"]]) {
  const h = await hoverLastTooltip(lite.page, id);
  if (!h.found) { check(`①${label} hover 定位失败`, false, "no svg/cfg"); continue; }
  await lite.page.mouse.move(h.screenX, h.screenY);
  await new Promise((r) => setTimeout(r, 200));
  const tipText = await lite.page.evaluate((id) => {
    const tip = document.querySelector(id + " .lw-tip");
    return tip && tip.style.display !== "none" ? tip.textContent : null;
  }, id);
  const md = h.last.slice(4, 6) + "-" + h.last.slice(6, 8);
  check(`①${label} hover 末点 tooltip 同日(${md})`, tipText != null && (tipText.includes(md) || String(tipText).includes(h.last)) && h.last === "20260928", `tip=${String(tipText).slice(0, 30)} last=${h.last}`);
}
await lite.ctx.close();

// ================= ② 回归: 基线(main) vs 改后 其他 lite 图标签(位置+文本)逐个一致 =================
// 注意: 两图 xStep 只在 overfit 两图开启(forceLastLabel 关联), 其他图 forceLastLabel 默认关 → xStep 不生效,
// 走原 _etfXStep → 标签应与基线逐个一致。
const regBase = await openPage(browser, SRC_BASE);
const regNew = await openPage(browser, SRC_NEW);
const bas = await collectLite(regBase.page);
const newd = await collectLite(regNew.page);
const baseNon = bas.lites.filter((l) => !l.isOverfit && l.hasSvg);
const newNon = newd.lites.filter((l) => !l.isOverfit && l.hasSvg);
check(`②lite 图数量基线=改后`, baseNon.length === newNon.length && baseNon.length >= 3, `base=${baseNon.length} new=${newNon.length}`);
for (let i = 0; i < Math.max(baseNon.length, newNon.length); i++) {
  const b = baseNon[i], nw = newNon[i];
  if (!b || !nw) { check(`②第${i}张 lite 图存在`, false, `base=${!!b} new=${!!nw}`); continue; }
  const sig = (l) => l.lbls.map((x) => x.txt + "@" + x.svgX.toFixed(0));
  check(`②lite图[${i}] 日期标签(文本+位置)与基线逐个一致`, JSON.stringify(sig(b)) === JSON.stringify(sig(nw)), `id=${b.id} base=${JSON.stringify(sig(b).slice(-3))} new=${JSON.stringify(sig(nw).slice(-3))}`);
}
// 两图曲线与数据末点不被改动(默认 60 窗口, 基线=改后)
check("②acc 曲线数据末点基线=改后", bas.acc && newd.acc && bas.acc.last === newd.acc.last && JSON.stringify(bas.acc.seriesLen) === JSON.stringify(newd.acc.seriesLen), `base=${bas.acc && bas.acc.last} new=${newd.acc && newd.acc.last}`);
check("②risk 曲线数据末点基线=改后", bas.risk && newd.risk && bas.risk.last === newd.risk.last && JSON.stringify(bas.risk.seriesLen) === JSON.stringify(newd.risk.seriesLen), `base=${bas.risk && bas.risk.last} new=${newd.risk && newd.risk.last}`);
check("②基线路径无 pageerror", regBase.pageErrors.length === 0, regBase.pageErrors.join(" / "));
check("②改后路径无 pageerror(回归段)", regNew.pageErrors.length === 0, regNew.pageErrors.join(" / "));
await regBase.ctx.close();
await regNew.ctx.close();

// ================= ③ fallback 路径(⚡ 关闭 → echarts) =================
const fb = await openPage(browser, SRC_NEW, { lightweight: false });
await new Promise((r) => setTimeout(r, 1500));
const fbInfo = await fb.page.evaluate(() => {
  const out = { acc: null, risk: null };
  const getChart = (id) => {
    const el = document.querySelector(id);
    if (!el || typeof echarts === "undefined") return null;
    const inst = echarts.getInstanceByDom(el);
    if (!inst) return { noInst: true };
    const opt = inst.getOption();
    const x = opt.xAxis && opt.xAxis[0];
    return {
      showMaxLabel: !!(x && x.axisLabel && x.axisLabel.showMaxLabel),
      dataLast: x && x.data ? x.data[x.data.length - 1] : null,
      seriesCnt: (opt.series || []).length,
      canvas: !!el.querySelector("canvas"),
    };
  };
  out.acc = getChart("#overfit-acc-chart");
  out.risk = getChart("#overfit-risk-chart");
  return out;
});
check("③acc fallback 走 echarts 且 showMaxLabel 生效", fbInfo.acc && fbInfo.acc.canvas && fbInfo.acc.showMaxLabel === true && fbInfo.acc.dataLast === "20260928", JSON.stringify(fbInfo.acc));
check("③risk fallback 走 echarts 且 showMaxLabel 生效", fbInfo.risk && fbInfo.risk.canvas && fbInfo.risk.showMaxLabel === true && fbInfo.risk.dataLast === "20260928", JSON.stringify(fbInfo.risk));
check("③fallback 路径无 pageerror", fb.pageErrors.length === 0, fb.pageErrors.join(" / "));
const fbAcc = fb.page.locator("#overfit-acc-chart").first();
const fbRisk = fb.page.locator("#overfit-risk-chart").first();
await fbAcc.screenshot({ path: "/tmp/xaxis147-acc-fallback.png" });
await fbRisk.screenshot({ path: "/tmp/xaxis147-risk-fallback.png" });
await fb.ctx.close();

// ================= 报告五窗口标签数/末点 =================
for (const win of WINDOWS) {
  console.log(`窗口${win} acc: xLabels=${accWinN[win] && accWinN[win].xN} 实际标签=${accWinN[win] && accWinN[win].lblN} xStep=${accWinN[win] && accWinN[win].xStep} 最右=${accWinLast[win]}`);
  console.log(`窗口${win} risk: xLabels=${riskWinN[win] && riskWinN[win].xN} 实际标签=${riskWinN[win] && riskWinN[win].lblN} xStep=${riskWinN[win] && riskWinN[win].xStep} 最右=${riskWinLast[win]}`);
}

console.log(`\n结果: PASS=${nPass} FAIL=${nFail}`);
await browser.close();
process.exit(nFail ? 1 : 0);
