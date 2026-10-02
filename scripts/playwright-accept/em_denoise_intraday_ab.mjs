// 盘中 A/B: 模拟交易日盘中(is_closed=false)改前 vs 改后 — 东财分时请求数与失败 console 条数
// 改前: 本地 app.min.js(main版, _EM_TRIP_THRESHOLD=3 无全局熔断)
// 改后: app.js 源码(_EM_TRIP_THRESHOLD=2 + 全局熔断 + 休市感知; 盘中不休市, A1.2不生效, 只测A1.1)
// 用法: MODE=before|after node scripts/playwright-accept/em_denoise_intraday_ab.mjs
import { createRequire } from "module";
import { readFileSync } from "fs";
const require = createRequire("/Users/linhuichen/code/trade/.claude/worktrees/agent-ae2f7cfb35006f345/scripts/playwright-accept/");
const { chromium } = require("playwright");
const MODE = process.env.MODE || "after";
const appSrc = readFileSync("/Users/linhuichen/code/trade/.claude/worktrees/agent-ae2f7cfb35006f345/static-site/app.js", "utf8");
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: "block" });
const page = await ctx.newPage();
let trends2 = 0, emFailConsole = 0, minute = 0;
page.on("request", (r) => {
  const u = r.url();
  if (u.includes("trends2")) trends2++;
  if (u.includes("minute/query")) minute++;
});
page.on("console", (m) => { if (/东财/.test(m.text())) emFailConsole++; });
// 注入盘中 snap: 拦截本地+线上 fallback 两个源的 snapshot, 改 is_closed=false + datetime 今日
await page.route("**/*.json*", async (route) => {
  const u = new URL(route.request().url());
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
if (MODE === "after") {
  await page.route("**/app.min.js*", async (route) => {
    await route.fulfill({ contentType: "application/javascript", body: appSrc });
  });
}
await page.goto("http://localhost:8099/#overview", { waitUntil: "domcontentloaded", timeout: 90000 });
await page.waitForTimeout(90000);
console.log(`[盘中-${MODE}] 东财trends2分时请求=${trends2} | 东财失败console=${emFailConsole} | 腾讯minute请求=${minute}`);
await b.close();
