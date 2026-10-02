// §15 回归: 交易日盘中正常轮询不受影响 — 构造假 snap(is_closed=false, datetime=今日)模拟盘中
// 断言: ①_isMarketClosedToday 不短路盘中(分时 trends2/minute 请求仍发起)
//       ②_startIntradayRefresh 轮询活跃(_intradayActive=true, 有 1min 定时器), 多轮持续
// 用法: node scripts/playwright-accept/em_denoise_intraday_regress.mjs
import { createRequire } from "module";
import { readFileSync } from "fs";
const require = createRequire("/Users/linhuichen/code/trade/.claude/worktrees/agent-ae2f7cfb35006f345/scripts/playwright-accept/");
const { chromium } = require("playwright");
const appSrc = readFileSync("/Users/linhuichen/code/trade/.claude/worktrees/agent-ae2f7cfb35006f345/static-site/app.js", "utf8");
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: "block" });
const page = await ctx.newPage();
let reqs = { trends2: 0, minute: 0, snapHit: 0, snapClosed: null, all: [], jsonSeen: [], snapFull: [] };
page.on("request", (r) => {
  const u = r.url();
  if (u.includes("intraday_snapshot") || u.includes("boot.json") || u.includes("overview.json")) reqs.snapFull.push(u);
  if (reqs.all.length < 25) reqs.all.push(u.split("?")[0].split("/").slice(-2).join("/"));
  if (u.includes("trends2")) reqs.trends2++;
  if (u.includes("minute/query")) reqs.minute++;
});
await page.route("**/*.json*", async (route) => {
  const u = new URL(route.request().url());
  reqs.jsonSeen.push(u.pathname);
  if (u.pathname === "/data/intraday_snapshot.json") {
    try {
      const resp = await route.fetch({ url: "https://ss.fx8.store" + u.pathname });
      const snap = await resp.json();
      if (snap && snap.indices) {
        snap.is_closed = false;
        for (const i of snap.indices) {
          const base = (i.datetime && i.datetime.length >= 16) ? i.datetime.slice(11, 16) : "10:30:00";
          if (i.code === "sh000001") { i.datetime = "2026-10-02 " + base; i.last_date = "20261002"; }
          else if (i.datetime && /^\d{4}-\d{2}-\d{2}/.test(i.datetime)) { i.datetime = "2026-10-02 " + base; }
          else if (i.datetime && /^\d{8}/.test(i.datetime)) { i.datetime = "20261002 " + base; }
          if (i.last_date && /^\d{8}$/.test(i.last_date)) i.last_date = "20261002";
        }
        reqs.snapHit++;
        reqs.snapClosed = snap.is_closed;
        await route.fulfill({ contentType: "application/json", body: JSON.stringify(snap) });
        return;
      }
      await route.fulfill({ response: resp });
      return;
    } catch (e) { await route.abort(); return; }
  }
  if (u.pathname.startsWith("/data/")) {
    try {
      const resp = await route.fetch({ url: "https://ss.fx8.store" + u.pathname + (u.search || "") });
      await route.fulfill({ response: resp });
    } catch (e) { await route.abort(); }
    return;
  }
  await route.continue();
});
await page.route("**/app.min.js*", async (route) => {
  await route.fulfill({ contentType: "application/javascript", body: appSrc });
});
await page.goto("http://localhost:8099/#overview", { waitUntil: "domcontentloaded", timeout: 90000 });
await page.waitForTimeout(15000);
const st1 = await page.evaluate(() => ({
  dynPulse: !!document.querySelector(".dyn-pulse"),
  debugBar: (document.getElementById("refresh-debug") || {}).textContent || "",
  hasIntradayEl: !!document.querySelector(".spark-intraday"),
  getStateVal: (typeof getState === "function") ? getState(window.state && window.state.intradaySnapshot) : "no-getState",
  isClosed: window.state && window.state.intradaySnapshot ? window.state.intradaySnapshot.is_closed : "no-snap",
}));
console.log("=== §15 盘中回归 (观察1: 15s) ===");
console.log("snapshot route 命中:", reqs.snapHit, "| 返回 is_closed:", reqs.snapClosed);
console.log("请求URL样例:", JSON.stringify(reqs.all));
console.log("snapshot/boot/overview 完整URL:", JSON.stringify(reqs.snapFull));
console.log("json route 见到的 pathname:", JSON.stringify(reqs.jsonSeen));
console.log("东财 trends2 分时请求:", reqs.trends2, "(发起=未被休市短路)");
console.log("腾讯 minute/query 分时请求:", reqs.minute);
console.log("DOM .dyn-pulse(盘中1min标志):", st1.dynPulse, "| debug状态条:", st1.debugBar);
console.log("页面 state.is_closed:", st1.isClosed, "| getState:", st1.getStateVal, "| .spark-intraday 存在:", st1.hasIntradayEl);
// 等一轮 60s 验证轮询持续
await page.waitForTimeout(65000);
const st2 = await page.evaluate(() => ({ pct: Object.keys(window._intradayDynamicPct || {}).length, time: window._intradayDynamicTime || "" }));
console.log("=== 观察2 (再65s, 覆盖60s轮询一轮) ===");
console.log("trends2 累计:", reqs.trends2, "| minute 累计:", reqs.minute, "| _intradayDynamicPct 键数:", st2.pct, "| 动态时间:", st2.time);
await b.close();
