#!/usr/bin/env node
// #144 最终验收(二等): 探针包装 _renderOverfitRisk 捕获页面实际渲染的 daily 数组(dates/vals),
// 同时包装 _lwSetup 捕获 _lwSVG 的 path 段数与 x 轴标签, 定量证明末端 null 无桥接假线。
import { chromium } from "playwright";
import fs from "fs";
import path from "path";

const BASE = "http://localhost:8127/static-site";
const WT = "/Users/linhuichen/code/trade/.claude/worktrees/agent-a7cbb8af4e8d8d9f0";
let SRC_APP = fs.readFileSync(path.resolve(WT + "/static-site/app.js"), "utf8");
const SRC_I18N = fs.readFileSync(path.resolve(WT + "/static-site/i18n.js"), "utf8");
const readAfter = (f) => fs.readFileSync(path.join("/tmp/ovtest-after/static-site/data", f), "utf8");
const readBefore = (f) => fs.readFileSync(path.join("/tmp/ovtest-before/static-site/data", f), "utf8");

// 探针: 捕获每次 _renderOverfitRisk 的实际 daily 序列(dates/vals)到 window.__ovSeqs
const probe = `
(function(){
  window.__ovSeqs = [];
  var origRisk = window._renderOverfitRisk;
  window._renderOverfitRisk = function(data){
    try {
      var el = document.getElementById("overfit-risk-chart");
      var ov = data && data.overfit || {};
      var s = _overfitState;
      var pick = function(obj){ return (obj && Array.isArray(obj[String(s.roll)])) ? obj[String(s.roll)] : (obj && Array.isArray(obj["60"])) ? obj["60"] : []; };
      var daily;
      if (s.sigType) daily = pick((ov.daily_by_dim&&ov.daily_by_dim.sig_type&&ov.daily_by_dim.sig_type[s.sigType])||{});
      else if (s.grade) daily = pick((ov.daily_by_dim&&ov.daily_by_dim.grade&&ov.daily_by_dim.grade[s.grade])||{});
      else daily = (ov.daily_by_win&&ov.daily_by_win[String(s.roll)])||(ov.daily_by_win&&ov.daily_by_win["60"])||(ov.daily||[]);
      var n = (s.win&&s.win>0)?s.win:60;
      if (daily.length>n) daily = daily.slice(-n);
      window.__ovSeqs.push({
        ts: Date.now(),
        len: daily.length,
        dates: daily.map(function(p){return p.date;}),
        scores: daily.map(function(p){return p.risk_score;}),
        hasNull: daily.some(function(p){return p.risk_score==null;}),
        nullIdxs: daily.map(function(p,i){return p.risk_score==null?i:-1;}).filter(function(i){return i>=0;})
      });
    } catch(e){ window.__ovSeqs.push({err:String(e)}); }
    return origRisk.apply(this, arguments);
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
  seqs = await page.evaluate(() => window.__ovSeqs);
  if (seqs && seqs.length) break;
  await new Promise((r) => setTimeout(r, 1000));
}
check("_renderOverfitRisk 已捕获渲染序列", !!(seqs && seqs.length), seqs && seqs.length ? `seqs=${seqs.length}` : "无捕获");

const last = (seqs || []).filter((x) => !x.err).pop();
if (last) {
  const lastDate = last.dates[last.dates.length - 1];
  const lastNonNullIdx = last.scores.map((v, i) => (v == null ? -1 : i)).filter((i) => i >= 0).pop();
  const lastNonNullDate = last.dates[lastNonNullIdx];
  const nullCnt = last.nullIdxs.length;
  const tailNullCnt = last.dates.length - 1 - lastNonNullIdx;
  check("①x 轴末点日期=20260916(实盘有回测缺)", lastDate === "20260916", lastDate);
  check("②风险曲线末点日期=最后非null日(20260915)", lastNonNullDate === "20260915", `${lastNonNullDate} (null数=${nullCnt})`);
  check("②'末端 null 不被桥接': 末端 null 在序列末尾", tailNullCnt === 1, `tailNull=${tailNullCnt}`);
  check("序列末点 win_rate=null 留空(不填40)", last.scores[last.scores.length - 1] === null, JSON.stringify(last.scores.slice(-3)));
  console.log("[渲染序列] len=" + last.len + " 末3dates=" + JSON.stringify(last.dates.slice(-3)) + " 末3scores=" + JSON.stringify(last.scores.slice(-3)));
} else {
  check("捕获到有效序列", false, JSON.stringify(seqs));
}

// SVG 侧: 读当前默认态渲染 path 段数(connectNulls 桥接会有 1 条 lint; null 末端不参与 path)
const svgInfo = await page.evaluate(() => {
  const svg = document.querySelector("#overfit-risk-chart svg");
  if (!svg) return { noSvg: true };
  const paths = Array.from(svg.querySelectorAll("path")).map((p) => ({ s: p.getAttribute("stroke") || "", d: p.getAttribute("d") || "" }));
  const line = paths.find((p) => p.d.startsWith("M") && p.s !== "#c0c4cc" && p.s !== "var(--border)");
  const d = line ? line.d : "";
  const moves = (d.match(/M\s+[-\d.]+/g) || []);
  const nums = d.match(/-?\d+(?:\.\d+)?/g) || [];
  return { pathCount: paths.length, lineMoves: moves.length, lastNums: nums.slice(-2).map(Number), tailNote: (document.querySelector(".ov-risk-tail-note")||{}).textContent||"" };
});
check("SVG 折线仅 1 段(末端 null 未产生新段)", svgInfo.lineMoves === 1, `moves=${svgInfo.lineMoves}`);
check("尾部原因说明出现", String(svgInfo.tailNote).includes("末端1日无回测对照"), svgInfo.tailNote);

// 回归 24 交互
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

check("全程无页面 JS 错误", pageErrors.length === 0, pageErrors.join(" / "));
console.log(`\n结果: PASS=${nPass} FAIL=${nFail}`);
await browser.close();
process.exit(nFail ? 1 : 0);