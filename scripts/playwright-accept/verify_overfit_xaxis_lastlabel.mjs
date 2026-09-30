#!/usr/bin/env node
// #147 过拟合卡 x 轴末点标签验收(2026-09-30)
// 主证据(用户视角): lite SVG 两图最右可见标签 == 渲染层数据末点日期; hover 末点 tooltip 同日。
// 双渲染路径: lite 自研引擎 + echarts fallback(⚡ 关闭)各验一次。
// 回归: 开关默认关时, 全站其他 lite 图 x 标签与基线(main 未改版)逐个一致; 两图曲线/数据末点未被动。
import { chromium } from "playwright";
import fs from "fs";
import path from "path";

const WT = "/Users/linhuichen/code/trade/.claude/worktrees/agent-a25e29c4db5dba109";
const BASE = "http://localhost:8127/static-site";
const SRC_NEW = fs.readFileSync(WT + "/static-site/app.js", "utf8");       // 改后(forceLastLabel 两图开启)
const SRC_BASE = fs.readFileSync("/tmp/app_main_baseline.js", "utf8");     // 基线(main, 无 forceLastLabel)
const SRC_I18N = fs.readFileSync(WT + "/static-site/i18n.js", "utf8");
const readJ = (f) => fs.readFileSync("/tmp/" + f, "utf8");

let nPass = 0, nFail = 0;
function check(name, cond, detail = "") {
  if (cond) nPass++; else nFail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
}

// ---- 建页工具: 注入指定 app.js + 线上 overfit 数据, 无痕(localStorage 可选手动设) ----
async function openPage(browser, appSrc, opts = {}) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 1400 } });
  await ctx.clearCookies();
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
  // 等两图渲染
  for (let i = 0; i < 60; i++) {
    const r = await page.evaluate(() => !!(document.querySelector("#overfit-acc-chart svg") && document.querySelector("#overfit-risk-chart svg")));
    if (r) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  return { ctx, page, pageErrors };
}

// ---- 采集函数: 每张 lite 图的日期类 x 标签数组 + 两图 cfg ----
function collectLite(page) {
  return page.evaluate(() => {
    const out = { lites: [], acc: null, risk: null };
    const renderers = (typeof _lwRenderers !== "undefined") ? Array.from(_lwRenderers.keys()) : [];
    renderers.forEach((el) => {
      const svg = el.querySelector("svg.lw-svg");
      const dates = [];
      if (svg) {
        Array.from(svg.querySelectorAll("text")).forEach((t) => {
          const txt = t.textContent;
          if (/^\d{8}$/.test(txt)) dates.push(txt);
        });
      }
      const isAcc = el.id === "overfit-acc-chart";
      const isRisk = el.id === "overfit-risk-chart";
      out.lites.push({ id: el.id || "", hasSvg: !!svg, dates, isOverfit: isAcc || isRisk });
      if (isAcc && typeof _lwCfgMap !== "undefined") {
        const c = _lwCfgMap.get(el);
        out.acc = c ? { n: c.xLabels.length, last: c.xLabels[c.xLabels.length - 1], forceLastLabel: c.forceLastLabel, seriesLen: (c.series || []).map((s) => (s.data || []).length) } : null;
      }
      if (isRisk && typeof _lwCfgMap !== "undefined") {
        const c = _lwCfgMap.get(el);
        out.risk = c ? { n: c.xLabels.length, last: c.xLabels[c.xLabels.length - 1], forceLastLabel: c.forceLastLabel, seriesLen: (c.series || []).map((s) => (s.data || []).length) } : null;
      }
    });
    // 每图 svg 最右可见日期标签(用户视角: 读 x 属性最大的日期文本)
    const rightMost = (id) => {
      const svg = document.querySelector(id + " svg.lw-svg");
      if (!svg) return null;
      let best = null;
      Array.from(svg.querySelectorAll("text")).forEach((t) => {
        const txt = t.textContent;
        if (!/^\d{8}$/.test(txt)) return;
        const x = parseFloat(t.getAttribute("x"));
        if (!best || x > best.x) best = { x, txt };
      });
      return best ? best.txt : null;
    };
    out.accRight = rightMost("#overfit-acc-chart");
    out.riskRight = rightMost("#overfit-risk-chart");
    return out;
  });
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

// ================= ① lite 路径(改后 app.js) =================
const lite = await openPage(browser, SRC_NEW);
const lit = await collectLite(lite.page);
check("①acc 图 forceLastLabel 已开启", lit.acc && lit.acc.forceLastLabel === true, `forceLastLabel=${lit.acc && lit.acc.forceLastLabel}`);
check("①risk 图 forceLastLabel 已开启", lit.risk && lit.risk.forceLastLabel === true, `forceLastLabel=${lit.risk && lit.risk.forceLastLabel}`);
check("①acc 数据末点=最右标签 20260928", lit.acc && lit.acc.last === "20260928" && lit.accRight === "20260928", `dataLast=${lit.acc && lit.acc.last} rightLabel=${lit.accRight}`);
check("①risk 数据末点=最右标签 20260928", lit.risk && lit.risk.last === "20260928" && lit.riskRight === "20260928", `dataLast=${lit.risk && lit.risk.last} rightLabel=${lit.riskRight}`);
check("①lite 路径全程无 pageerror", lite.pageErrors.length === 0, lite.pageErrors.join(" / "));

// 截图留档(用户视角)
const accSvg = lite.page.locator("#overfit-acc-chart svg.lw-svg").first();
const riskSvg = lite.page.locator("#overfit-risk-chart svg.lw-svg").first();
await accSvg.screenshot({ path: "/tmp/xaxis147-acc-lite.png" });
await riskSvg.screenshot({ path: "/tmp/xaxis147-risk-lite.png" });

// hover 末点 tooltip 断言
for (const [id, label] of [["#overfit-acc-chart", "acc"], ["#overfit-risk-chart", "risk"]]) {
  const h = await hoverLastTooltip(lite.page, id);
  if (!h.found) { check(`①${label} hover 定位失败`, false, "no svg/cfg"); continue; }
  await lite.page.mouse.move(h.screenX, h.screenY);
  await new Promise((r) => setTimeout(r, 200));
  const tipText = await lite.page.evaluate((id) => {
    const tip = document.querySelector(id + " .lw-tip");
    return tip && tip.style.display !== "none" ? tip.textContent : null;
  }, id);
  // 末点 tooltip 同日判定: 文本含 MM-DD("09-28") 或 原始 8 位日期("20260928")(risk 末点 null 时 tipFn 返回原始日期, #144 语义)
  const md = h.last.slice(4, 6) + "-" + h.last.slice(6, 8);
  check(`①${label} hover 末点 tooltip 同日(${md})`, tipText != null && (tipText.includes(md) || String(tipText).includes(h.last)) && h.last === "20260928", `tip=${String(tipText).slice(0, 30)} last=${h.last}`);
}
await lite.ctx.close();

// ================= ② 回归: 基线(main) vs 改后 其他 lite 图 x 标签逐个一致 =================
const base = await openPage(browser, SRC_BASE);
const bas = await collectLite(base.page);
const baseNon = bas.lites.filter((l) => !l.isOverfit && l.hasSvg);
const newNon = lit.lites.filter((l) => !l.isOverfit && l.hasSvg);
check(`②lite 图数量基线=改后`, baseNon.length === newNon.length && baseNon.length >= 3, `base=${baseNon.length} new=${newNon.length}`);
for (let i = 0; i < Math.max(baseNon.length, newNon.length); i++) {
  const b = baseNon[i], nw = newNon[i];
  if (!b || !nw) { check(`②第${i}张 lite 图存在`, false, `base=${!!b} new=${!!nw}`); continue; }
  check(`②lite图[${i}] 日期标签与基线逐个一致`, JSON.stringify(b.dates) === JSON.stringify(nw.dates), `id=${b.id} base=${JSON.stringify(b.dates.slice(-4))} new=${JSON.stringify(nw.dates.slice(-4))}`);
}
// 两图曲线与数据末点不被改动: cfg.xLabels 末点 + series 长度 基线=改后
check("②acc 曲线数据末点基线=改后", bas.acc && lit.acc && bas.acc.last === lit.acc.last && JSON.stringify(bas.acc.seriesLen) === JSON.stringify(lit.acc.seriesLen), `base=${bas.acc && bas.acc.last} new=${lit.acc && lit.acc.last}`);
check("②risk 曲线数据末点基线=改后", bas.risk && lit.risk && bas.risk.last === lit.risk.last && JSON.stringify(bas.risk.seriesLen) === JSON.stringify(lit.risk.seriesLen), `base=${bas.risk && bas.risk.last} new=${lit.risk && lit.risk.last}`);
check("②基线路径无 pageerror", base.pageErrors.length === 0, base.pageErrors.join(" / "));
await base.ctx.close();

// ================= ③ fallback 路径(⚡ 关闭 → echarts) =================
const fb = await openPage(browser, SRC_NEW, { lightweight: false });
// echarts fallback 是 canvas, 无 text DOM; 读 echarts 实例配置断言 showMaxLabel 生效 + 截图留档
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

console.log(`\n结果: PASS=${nPass} FAIL=${nFail}`);
await browser.close();
process.exit(nFail ? 1 : 0);