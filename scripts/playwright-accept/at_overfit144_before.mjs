#!/usr/bin/env node
// #144 before 对照: 修复前产物(末点停在回测侧 0915)的页面渲染序列捕获, 报末3dates/末3scores 做前后对照
import { chromium } from "playwright";
import fs from "fs";
import path from "path";

const BASE = "http://localhost:8127/static-site";
const WT = "/Users/linhuichen/code/trade/.claude/worktrees/agent-a7cbb8af4e8d8d9f0";
let SRC_APP = fs.readFileSync(path.resolve(WT + "/static-site/app.js"), "utf8");
const SRC_I18N = fs.readFileSync(path.resolve(WT + "/static-site/i18n.js"), "utf8");
const readBefore = (f) => fs.readFileSync(path.join("/tmp/ovtest-before/static-site/data", f), "utf8");

const probe = `
(function(){
  window.__ovSeqs = [];
  var origRisk = window._renderOverfitRisk;
  window._renderOverfitRisk = function(data){
    try {
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
        len: daily.length,
        dates: daily.map(function(p){return p.date;}),
        scores: daily.map(function(p){return p.risk_score;}),
        nullIdxs: daily.map(function(p,i){return p.risk_score==null?i:-1;}).filter(function(i){return i>=0;})
      });
    } catch(e){ window.__ovSeqs.push({err:String(e)}); }
    return origRisk.apply(this, arguments);
  };
})();
`;
SRC_APP = probe + "\n" + SRC_APP;

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.clearCookies();
const pageErrors = [];
const page = await ctx.newPage();
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 300)));
await ctx.route(/^(?!.*localhost)/, (r) => r.abort());
await ctx.route(/app\.min\.js(\?.*)?$/, (r) => r.fulfill({ contentType: "application/javascript", body: SRC_APP }));
await ctx.route(/i18n\.js(\?.*)?$/, (r) => r.fulfill({ contentType: "application/javascript", body: SRC_I18N }));
await ctx.route(/overfit_monitor\.json(\?.*)?$/, (r) => r.fulfill({ contentType: "application/json", body: readBefore("overfit_monitor.json") }));
await ctx.route(/overfit_monitor_ext\.json(\?.*)?$/, (r) => r.fulfill({ contentType: "application/json", body: readBefore("overfit_monitor_ext.json") }));

await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded", timeout: 120000 });
let seqs = null;
for (let i = 0; i < 60; i++) {
  seqs = await page.evaluate(() => window.__ovSeqs);
  if (seqs && seqs.length) break;
  await new Promise((r) => setTimeout(r, 1000));
}
const last = (seqs || []).filter((x) => !x.err).pop();
if (last) {
  console.log("[BEFORE 渲染序列] len=" + last.len);
  console.log("末5dates=" + JSON.stringify(last.dates.slice(-5)));
  console.log("末5scores=" + JSON.stringify(last.scores.slice(-5)));
  console.log("null 索引=" + JSON.stringify(last.nullIdxs));
  console.log("pageErrors=" + (pageErrors.length === 0 ? "NONE" : pageErrors.join(" / ")));
} else {
  console.log("FAIL 无捕获", JSON.stringify(seqs));
}
await browser.close();
