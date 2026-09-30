#!/usr/bin/env node
// #144 举一反三验收: accuracy 图同根因修复 —— 探针包装 _overfitAccSeries 捕获 dates/actual/backtest,
// 断言: ①dates 末点=20260916(实盘有、回测缺并入) ②actual 末点有值 ③backtest 末端 null(回测缺, 不桥接)
// ④interactive win/roll/grade/sig/k 无 pageerror ⑤全程无 JS 错误
import { chromium } from "playwright";
import fs from "fs";
import path from "path";

const BASE = "http://localhost:8127/static-site";
const WT = "/Users/linhuichen/code/trade/.claude/worktrees/agent-a7cbb8af4e8d8d9f0";
let SRC_APP = fs.readFileSync(path.resolve(WT + "/static-site/app.js"), "utf8");
const SRC_I18N = fs.readFileSync(path.resolve(WT + "/static-site/i18n.js"), "utf8");
const readAfter = (f) => fs.readFileSync(path.join("/tmp/ovtest-after/static-site/data", f), "utf8");

const probe = `
(function(){
  window.__ovAccSeqs = [];
  var orig = window._overfitAccSeries;
  window._overfitAccSeries = function(data, w){
    var r = orig.apply(this, arguments);
    try {
      window.__ovAccSeqs.push({ w: w, dates: r.dates.slice(), actual: r.actual.slice(), backtest: r.backtest.slice() });
    } catch(e){ window.__ovAccSeqs.push({ err: String(e) }); }
    return r;
  };
})();
`;
SRC_APP = probe + "\n" + SRC_APP;

let nPass = 0, nFail = 0;
function check(name, cond, detail = "") {
  if (cond) nPass++; else nFail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
}

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.clearCookies();
const pageErrors = [];
const page = await ctx.newPage();
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 300)));
await ctx.route(/^(?!.*localhost)/, (r) => r.abort());
await ctx.route(/app\.min\.js(\?.*)?$/, (r) => r.fulfill({ contentType: "application/javascript", body: SRC_APP }));
await ctx.route(/i18n\.js(\?.*)?$/, (r) => r.fulfill({ contentType: "application/javascript", body: SRC_I18N }));
await ctx.route(/overfit_monitor\.json(\?.*)?$/, (r) => r.fulfill({ contentType: "application/json", body: readAfter("overfit_monitor.json") }));
await ctx.route(/overfit_monitor_ext\.json(\?.*)?$/, (r) => r.fulfill({ contentType: "application/json", body: readAfter("overfit_monitor_ext.json") }));

await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded", timeout: 120000 });
let seqs = null;
for (let i = 0; i < 60; i++) {
  seqs = await page.evaluate(() => window.__ovAccSeqs);
  if (seqs && seqs.length) break;
  await new Promise((r) => setTimeout(r, 1000));
}
check("_overfitAccSeries 已捕获序列", !!(seqs && seqs.length), seqs && seqs.length ? `seqs=${seqs.length}` : "无捕获");

// 默认态: win=60? 实际 _overfitState.win=60, roll=15 → w=60, backtest/actual 取 roll=15 窗口
const last = (seqs || []).filter((x) => !x.err).pop();
if (last) {
  const lastDate = last.dates[last.dates.length - 1];
  const actualLastNonNull = last.actual.map((v, i) => (v == null ? -1 : i)).filter((i) => i >= 0).pop();
  const actualLastNonNullDate = last.dates[actualLastNonNull];
  const btLastNonNull = last.backtest.map((v, i) => (v == null ? -1 : i)).filter((i) => i >= 0).pop();
  const btLastNonNullDate = last.dates[btLastNonNull];
  const btTailNull = last.dates.length - 1 - btLastNonNull;
  check("①accuracy dates 末点=20260916(实盘有、回测缺并入)", lastDate === "20260916", lastDate);
  check("②actual 曲线末点=20260916(有值)", actualLastNonNullDate === "20260916", `${actualLastNonNullDate} (actual末值=${last.actual[last.actual.length - 1]})`);
  check("②'backtest 末端 null 不桥接': 回测缺日留在末尾", btTailNull >= 1, `btTailNull=${btTailNull}, bt末非null=${btLastNonNullDate}`);
  check("实盘独有日 backtest=null(留空不造假)", last.backtest[last.backtest.length - 1] === null, JSON.stringify({ bt: last.backtest.slice(-3), act: last.actual.slice(-3) }));
  console.log("[ACC 默认态] dates末3=" + JSON.stringify(last.dates.slice(-3)) + " actual末3=" + JSON.stringify(last.actual.slice(-3)) + " backtest末3=" + JSON.stringify(last.backtest.slice(-3)));
} else {
  check("捕获到有效序列", false, JSON.stringify(seqs));
}

// 交互回归: win/roll/grade/sig/k
const clicks = [
  ["win", 30], ["win", 90], ["win", 180],
  ["roll", 10], ["roll", 30], ["roll", 60], ["roll", 100],
  ["grade", "high"], ["grade", "mid"], ["grade", "low"],
  ["sig", "buy"], ["sig", "buy_aux"], ["sig", "sell"], ["sig", "sell_stop_loss"],
  ["k", 1], ["k", 2], ["k", 3], ["k", 4], ["k", "off"],
];
for (const [kind, val] of clicks) {
  const before = pageErrors.length;
  const r = await page.evaluate(([kind, val]) => {
    const btn = document.querySelector(`[data-overfit-${kind}="${val}"]`);
    if (!btn) return { found: false };
    btn.click();
    return { found: true };
  }, [kind, val]);
  await new Promise((r) => setTimeout(r, 300));
  check(`交互 ${kind}=${val} 无 pageerror`, r.found && pageErrors.length === before, pageErrors.slice(before).join(" / "));
}

// 每个交互后 accuracy dates 末点都应 ≥ 20260915(并集驱动不丢实盘末点); 抽样断言 win=180 后末点
const afterSeq = await page.evaluate(() => {
  const s = window.__ovAccSeqs;
  return s && s.length ? s[s.length - 1] : null;
});
if (afterSeq && afterSeq.dates) {
  check("交互后 accuracy dates 末点仍并集(不丢实盘末点)", afterSeq.dates[afterSeq.dates.length - 1] === "20260916", afterSeq.dates[afterSeq.dates.length - 1]);
}

check("全程无页面 JS 错误", pageErrors.length === 0, pageErrors.join(" / "));
console.log(`\n结果: PASS=${nPass} FAIL=${nFail}`);
await browser.close();
process.exit(nFail ? 1 : 0);
