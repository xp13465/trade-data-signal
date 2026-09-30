#!/usr/bin/env node
// 北证50分时加固 Playwright 验收(2026-09-30 feat/bj50-intraday):
//   ①采集侧盘中注入 minute_series(实时源全挂时前端降级画当日曲线)
//   ②前端: 东财熔断短路 + 腾讯 day/query 备用腿(不动成功路径)
// 断言矩阵:
//   A  成功路径零变化: EM mock 合法 -> 图渲染、无熔断、无东财失败告警
//   A2 腾讯腿成功: EM 失败 + QQ minute mock 合法 -> 图渲染
//   B  降级链端到端: EM+QQ+THS 全失败 + 快照带 minute_series -> 画出曲线(非 .intraday-fail)
//   C1 熔断生效: EM 全 host 确定性拒绝(500) -> console 含「熔断短路(前」, 且 QQ day 兜底取到数据图仍渲染
//   C2 偶发失败不误熔断: EM 前2 host 500 后3 mock 成功 -> 无「熔断短路」+ 图渲染
import { createRequire } from "module";
const require = createRequire("/Users/linhuichen/code/trade/scripts/playwright-accept/");
const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://localhost:8160";
let pass = 0, fail = 0;
const ok = (n, c, d = "") => { c ? pass++ : fail++; console.log(`${c ? "PASS" : "FAIL"}  ${n}${d ? `  [${d}]` : ""}`); };

// ---- mock 数据构造 ----
function genPoints(t0 = "0930", n = 60, base = 3910.92) {
  const out = [];
  for (let i = 0; i < n; i++) {
    const m = 9 * 60 + 30 + i;
    const hh = String(Math.floor(m / 60)).padStart(2, "0");
    const mm = String(m % 60).padStart(2, "0");
    out.push({ t: hh + mm, time: hh + ":" + mm, c: base + Math.sin(i / 5) * 10, o: base, h: base + 12, l: base - 12, date: "2026-09-30" });
  }
  return out;
}
function mockEM(points, preClose = 3934.4, name = "上证指数") {
  const trends = points.map((p) => `${p.date} ${p.time},${p.o.toFixed(2)},${p.h.toFixed(2)},${p.l.toFixed(2)},${p.c.toFixed(2)},100,100000,${p.c.toFixed(2)}`);
  return { rc: 0, data: { trends, preClose, name } };
}
function mockQQMinute(code, points) {
  return { code: 0, data: { [code]: { data: { data: points.map((p) => `${p.t} ${p.c.toFixed(2)} 100 100000`), date: "2026-09-30" }, title: "test" } } };
}
function mockQQDay(code, points) {
  return { code: 0, data: { [code]: { data: [{ date: "2026-09-30", data: points.map((p) => `${p.t} ${p.c.toFixed(2)} 100 100000`) }], title: "test" } } };
}
const SNAP_CODES = ["sh000001", "sz399001", "sh000300", "sh000016", "sz399006", "sh000688", "bj899050", "sh000905", "sh000852", "hkHSI", "hkHSTECH", "hkHSCEI"];
function mockSnap(isClosed = false) {
  const indices = SNAP_CODES.map((code, i) => {
    const pts = genPoints("0930", 60, 3800 + i * 10);
    return {
      code, pre_close: 3800 + i * 10,
      minute_series: pts.map((p) => ({ time: p.time, price: p.c })),
    };
  });
  return {
    collected_at: "2026-09-30T10:30:00", is_closed: isClosed, label: isClosed ? "收盘快照" : "盘中实时小结",
    prev_trading_day: "20260929", indices, industries: [], concepts: [], us_futures: {}, global_realtime: {},
  };
}

const _JSONHDR = { "content-type": "application/json; charset=utf-8", "access-control-allow-origin": "*" };
const _corsfulfill = (page, route, body) => route.fulfill({ status: 200, headers: _JSONHDR, body: JSON.stringify(body) });

async function newPage(browser, routeSetup) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const errs = [], warns = []; // errs 只收 pageerror(JS 未捕获异常); resource 404/500 是 mock 环境噪音不计
  page.on("pageerror", (e) => errs.push(String(e)));
  page.on("console", (m) => {
    const t = m.text();
    if (m.type() === "warning" && /熔断|东财分时失败|day\/query备用腿/.test(t)) warns.push(t);
  });
  if (routeSetup) await routeSetup(page);
  await page.goto(BASE + "/#overview", { waitUntil: "domcontentloaded", timeout: 60000 });
  return { ctx, page, errs, warns };
}

async function waitSparkChart(page, code = "sh") {
  await page.waitForSelector(`.spark-intraday[data-intraday-code="${code}"]`, { timeout: 20000 });
  await page.waitForFunction((cd) => {
    const el = document.querySelector(`.spark-intraday[data-intraday-code="${cd}"]`);
    if (!el) return false;
    return !!el.querySelector("svg.lw-svg, canvas") || !!el.querySelector(".intraday-fail");
  }, code, { timeout: 25000 });
  return page.evaluate((cd) => {
    const el = document.querySelector(`.spark-intraday[data-intraday-code="${cd}"]`);
    return {
      hasSvg: !!el.querySelector("svg.lw-svg"),
      hasCanvas: !!el.querySelector("canvas"),
      hasFail: !!el.querySelector(".intraday-fail"),
      hasSnapLabel: !!el.querySelector(".intraday-snap-label"),
      snapLabelText: el.querySelector(".intraday-snap-label") ? el.querySelector(".intraday-snap-label").textContent : "",
    };
  }, code);
}

const browser = await chromium.launch({ headless: true });

// ---- Test A: 成功路径零变化(EM mock 合法) ----
{
  const { ctx, page, errs, warns } = await newPage(browser, (p) =>
    p.route("**/*", (route) => {
      const u = route.request().url();
      if (u.includes("eastmoney.com")) return _corsfulfill(p, route, mockEM(genPoints(), 3934.4, "上证指数"));
      if (u.includes("10jqka.com.cn")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" }); // 隔离 EM 腿
      return route.continue();
    }));
  try {
    const st = await waitSparkChart(page, "sh");
    console.log("[Test A 成功路径] spark-intraday sh:", JSON.stringify(st));
    ok("A1 EM mock 合法 -> 图渲染(有 svg/canvas)", st.hasSvg || st.hasCanvas, `svg=${st.hasSvg} canvas=${st.hasCanvas}`);
    ok("A2 无 .intraday-fail", !st.hasFail);
    ok("A3 无熔断告警", warns.filter((w) => w.includes("熔断")).length === 0, warns.slice(0, 1).join(" | "));
    ok("A4 无东财分时失败告警(EM 成功腿)", warns.filter((w) => w.includes("东财分时失败")).length === 0);
    ok("A5 无页面脚本错误", errs.length === 0, errs.slice(0, 2).join(" | "));
  } catch (e) {
    ok("Test A 渲染(异常): " + e.message, false);
  }
  await ctx.close();
}

// ---- Test A2: 腾讯腿成功(EM 失败 + QQ minute mock 合法) ----
{
  const { ctx, page, errs, warns } = await newPage(browser, (p) =>
    p.route("**/*", (route) => {
      const u = route.request().url();
      if (u.includes("eastmoney.com")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" });
      if (u.includes("10jqka.com.cn")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" });
      if (u.includes("/appstock/app/minute/query")) return _corsfulfill(p, route, mockQQMinute("sh000001", genPoints("0930", 60, 3910.92)));
      if (u.includes("/appstock/app/day/query")) return _corsfulfill(p, route, mockQQDay("sh000001", genPoints("0930", 60, 3910.92)));
      return route.continue();
    }));
  try {
    const st = await waitSparkChart(page, "sh");
    console.log("[Test A2 腾讯腿] spark-intraday sh:", JSON.stringify(st));
    ok("A2-1 EM 失败 + QQ minute 合法 -> 图渲染", st.hasSvg || st.hasCanvas, `svg=${st.hasSvg} canvas=${st.hasCanvas}`);
    ok("A2-2 无 .intraday-fail", !st.hasFail);
    ok("A2-3 无页面脚本错误", errs.length === 0, errs.slice(0, 2).join(" | "));
  } catch (e) {
    ok("Test A2 渲染(异常): " + e.message, false);
  }
  await ctx.close();
}

// ---- Test B: 降级链端到端(实时源全失败 + 快照带 minute_series -> 画曲线) ----
{
  const { ctx, page, errs, warns } = await newPage(browser, async (p) => {
    await p.route("**/*", (route) => {
      const u = route.request().url();
      if (u.includes("eastmoney.com")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" });
      if (u.includes("/appstock/app/") || u.includes("finance.qq.com/ifzq/appstock/app/")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" });
      if (u.includes("10jqka.com.cn")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" });
      if (u.includes("/data/intraday_snapshot.json")) return _corsfulfill(p, route, mockSnap(false));
      return route.continue();
    });
  });
  try {
    const st = await waitSparkChart(page, "sh");
    console.log("[Test B 降级链] spark-intraday sh:", JSON.stringify(st));
    ok("B1 实时源全失败 + 快照带 minute_series -> 画出曲线(svg/canvas)", st.hasSvg || st.hasCanvas, `svg=${st.hasSvg} canvas=${st.hasCanvas}`);
    ok("B2 非 .intraday-fail 文字降级", !st.hasFail);
    ok("B3 出现「快照」标签(降级来源=快照)", st.hasSnapLabel, st.snapLabelText);
    ok("B4 无页面脚本错误", errs.length === 0, errs.slice(0, 2).join(" | "));
  } catch (e) {
    ok("Test B 渲染(异常): " + e.message, false);
  }
  await ctx.close();
}

// ---- Test C1: 熔断生效 + day/query 兜底 ----
{
  const { ctx, page, errs, warns } = await newPage(browser, (p) =>
    p.route("**/*", (route) => {
      const u = route.request().url();
      if (u.includes("eastmoney.com")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" }); // 全 host 确定性拒绝
      if (u.includes("10jqka.com.cn")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" });
      if (u.includes("/appstock/app/minute/query")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" });
      if (u.includes("/appstock/app/day/query")) return _corsfulfill(p, route, mockQQDay("sh000001", genPoints("0930", 60, 3910.92))); // day 兜底腿成功
      return route.continue();
    }));
  try {
    const st = await waitSparkChart(page, "sh");
    console.log("[Test C1 熔断+day兜底] spark-intraday sh:", JSON.stringify(st));
    console.log("[Test C1] console warns:", JSON.stringify(warns.slice(0, 4)));
    ok("C1-1 console 含「熔断短路(前」(确定性拒绝累计达阈值触发)", warns.some((w) => w.includes("熔断短路(前")), warns.slice(0, 2).join(" | "));
    ok("C1-2 熔断不影响最终取数: QQ day 兜底 -> 图渲染", st.hasSvg || st.hasCanvas, `svg=${st.hasSvg} canvas=${st.hasCanvas}`);
    ok("C1-3 非 .intraday-fail", !st.hasFail);
    ok("C1-4 无页面脚本错误", errs.length === 0, errs.slice(0, 2).join(" | "));
  } catch (e) {
    ok("Test C1 渲染(异常): " + e.message, false);
  }
  await ctx.close();
}

// ---- Test C2: 偶发失败不误熔断(EM 前2 host 500 后3 host 成功) ----
{
  const { ctx, page, errs, warns } = await newPage(browser, (p) =>
    p.route("**/*", (route) => {
      const u = route.request().url();
      if (u.includes("10jqka.com.cn")) return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" });
      if (u.includes("eastmoney.com")) {
        const host = new URL(u).hostname;
        // host 列表前2: push2delay / push2(含 push2.eastmoney.com) -> 500; 其余(2./10./20.push2) -> mock 成功
        if (host === "push2delay.eastmoney.com" || host === "push2.eastmoney.com") return route.fulfill({ status: 500, headers: _JSONHDR, body: "{}" });
        return _corsfulfill(p, route, mockEM(genPoints(), 3934.4, "上证指数"));
      }
      return route.continue();
    }));
  try {
    const st = await waitSparkChart(page, "sh");
    console.log("[Test C2 偶发失败] spark-intraday sh:", JSON.stringify(st));
    console.log("[Test C2] console warns:", JSON.stringify(warns.slice(0, 4)));
    ok("C2-1 偶发失败(2/5 host)不触发熔断", warns.filter((w) => w.includes("熔断短路(前")).length === 0, warns.slice(0, 2).join(" | "));
    ok("C2-2 偶发失败后 EM 剩余 host 成功 -> 图渲染", st.hasSvg || st.hasCanvas, `svg=${st.hasSvg} canvas=${st.hasCanvas}`);
    ok("C2-3 非 .intraday-fail", !st.hasFail);
    ok("C2-4 无页面脚本错误", errs.length === 0, errs.slice(0, 2).join(" | "));
  } catch (e) {
    ok("Test C2 渲染(异常): " + e.message, false);
  }
  await ctx.close();
}

await browser.close();
console.log(`\n=== 汇总: PASS ${pass} / FAIL ${fail} ===`);
process.exit(fail ? 1 : 0);
