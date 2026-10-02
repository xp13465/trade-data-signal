// A/B 降噪实测: 改前(app.min.js main版) vs 改后(app.js源码) — 国庆休市 console 东财失败条数
// 用法: MODE=before node scripts/playwright-accept/em_denoise_ab.mjs
//      MODE=after  node scripts/playwright-accept/em_denoise_ab.mjs
// 前置: python3 -m http.server 8099 -d static-site(worktree内)
import { createRequire } from "module";
import { readFileSync } from "fs";
const require = createRequire("/Users/linhuichen/code/trade/.claude/worktrees/agent-ae2f7cfb35006f345/scripts/playwright-accept/");
const { chromium } = require("playwright");
const MODE = process.env.MODE || "after";
const BASE = "http://localhost:8099";
const LOCAL_APP_SRC = "/Users/linhuichen/code/trade/.claude/worktrees/agent-ae2f7cfb35006f345/static-site/app.js";
const appSrc = readFileSync(LOCAL_APP_SRC, "utf8");
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1280, height: 900 } });
const page = await ctx.newPage();
let emFails = [], emWarns = [], reqs = { em: 0, qq: 0, emUrls: [], qqUrls: [] };
page.on("console", (m) => {
  const t = m.text();
  if (/东财/.test(t)) emFails.push(t.slice(0, 200));
  if (m.type() === "warn" && /intraday/.test(t)) emWarns.push(t.slice(0, 160));
});
page.on("request", (r) => {
  const u = r.url();
  if (u.includes("push2") || u.includes("eastmoney")) { reqs.em++; reqs.emUrls.push(u.split("?")[0].split("/").slice(-2).join("/")); }
  if (u.includes("gtimg") || u.includes("ifzq")) { reqs.qq++; reqs.qqUrls.push(u.split("?")[0].split("/").slice(-2).join("/")); }
});
await page.route("**/*.json", async (route) => {
  const u = new URL(route.request().url());
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
await page.goto(BASE + "/#overview", { waitUntil: "domcontentloaded", timeout: 90000 });
await page.waitForTimeout(95000);
const emFailKinds = [...new Set(emFails.map((s) => s.slice(0, 60)))];
console.log(`[${MODE}] 东财失败console条数=${emFails.length} | 东财请求=${reqs.em} | 腾讯请求=${reqs.qq} | intraday-warn=${emWarns.length}`);
console.log("  东财失败样例:", JSON.stringify(emFailKinds.slice(0, 4)));
console.log("  东财URL去重:", JSON.stringify([...new Set(reqs.emUrls)].slice(0, 12)));
console.log("  腾讯URL去重:", JSON.stringify([...new Set(reqs.qqUrls)].slice(0, 12)));
await b.close();
