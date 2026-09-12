#!/usr/bin/env node
/**
 * probe-intraday-fade0.mjs — 盘中表滚动条断言(演进快照三修复之任务 3)
 * 目的:验证盘中表 .kelly-intraday-view 改 max-height:none;flex-shrink:0 后,
 *       60 行注入数据下 wrapClientH==wrapScrollH(无内部滚动), 弹窗/容器链条不溢出。
 * 口径:localhost:8124 起本地服务; 注入 60 行 distinct etf_code 的 intraday JSON;
 *       手动调 _kellyIntradayRender(anchor, {mode:null, fadeOn:false, K:0}) 绕过过滤。
 * 输入:本地 static-site 服务(localhost:8124) + signal_kelly_trades_intraday.json 被路由 mock。
 * 输出:stdout PROBE JSON(wrapClientH/wrapScrollH/overflowY 链), pageErrors。
 * 复现:node docs/kelly/analysis/scripts/probe-intraday-fade0.mjs(先 python3 -m http.server 8124 -d static-site)
 * 配套报告:docs/kelly/analysis/sigkelly-snapshot-pollution-fix-20260910.md(复现段)
 */
import { createRequire } from "module";
const require = createRequire("/Users/linhuichen/code/trade/scripts/playwright-accept/");
const { chromium } = require("playwright");
const BASE = "http://localhost:8124";
const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.route(/^(?!.*localhost)/, (r) => r.abort());
const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 400)));
const FIELDS = ['signal_date','index_id','signal','buy_date','sell_date','etf_code','etf_name','track_tier','track_score','match_method','track_low_confidence','buy_price','sell_price','shares','profit','return_pct','hold_days','sell_reason','current_price','real_buy_price','real_current_price','market_state','market_tier','market_tier_all','market_tier_cyb','rating'];
const rows = [];
const etfPool = [];
for (let i = 1; i <= 60; i++) etfPool.push("51" + String(100 + i));
for (let i = 0; i < 60; i++) {
  const r = new Array(FIELDS.length);
  r[FIELDS.indexOf("signal_date")] = "20260909";
  r[FIELDS.indexOf("index_id")] = "sh00000" + (i % 9 + 1);
  r[FIELDS.indexOf("signal")] = "buy";
  r[FIELDS.indexOf("buy_date")] = "20260910";
  r[FIELDS.indexOf("etf_code")] = etfPool[i];
  r[FIELDS.indexOf("etf_name")] = "测试ETF" + i;
  r[FIELDS.indexOf("track_score")] = 90 - i;
  r[FIELDS.indexOf("buy_price")] = 4.0;
  r[FIELDS.indexOf("sell_price")] = 4.1;
  r[FIELDS.indexOf("shares")] = 1000;
  r[FIELDS.indexOf("profit")] = 100;
  r[FIELDS.indexOf("return_pct")] = 2.5;
  r[FIELDS.indexOf("hold_days")] = 1;
  r[FIELDS.indexOf("current_price")] = 4.1;
  r[FIELDS.indexOf("real_buy_price")] = 4.0;
  r[FIELDS.indexOf("real_current_price")] = 4.1;
  r[FIELDS.indexOf("rating")] = "mid";
  rows.push(r);
}
await ctx.route("**/*signal_kelly_trades_intraday.json*", (route) => {
  const payload = {
    generated_at: "2026-09-10 09:40", buy_amount: 10000, period_cutoffs: [], fields: FIELDS,
    quadrants: { sig_main: { A: rows }, mkt_concept: { A: rows }, rating_mid: { A: rows } },
    intraday: { mode: "intraday", rerun_date: "20260909", next_open_date: "20260910", price_basis: "test", main_pre_date_hash: "test", note: "test" }
  };
  route.fulfill({ contentType: "application/json", body: JSON.stringify(payload) });
});
await page.goto(BASE + "/index.html", { waitUntil: "domcontentloaded", timeout: 60000 });
await page.waitForTimeout(3500);
await page.evaluate(() => { const b = document.querySelector(".sig-kbtn-sim"); if (b) b.click(); });
await page.waitForTimeout(4000);
// 手动调 render 传 fadeOn:false 绕过降亏过滤, mode=null(全模式), K=0
const r2 = await page.evaluate(async () => {
  try {
    const modal = document.getElementById("simBacktestModal");
    const anchor = modal.querySelector(".rule-modal-header");
    if (typeof window._kellyIntradayRender !== "function") return "no-render";
    window._kellyIntradayRender(anchor, { mode: null, modeId: null, fadeOn: false, K: 0 });
    return "render-called";
  } catch (e) { return "err " + e.message; }
});
console.log("manual render:", r2);
await page.waitForTimeout(2500);
const probe = await page.evaluate(() => {
  const wrap = document.querySelector(".kelly-intraday-view");
  if (!wrap) return { found: false };
  const tbl = wrap.querySelector(".sim-intraday-tbl");
  const cs = getComputedStyle(wrap);
  const tbody = tbl ? tbl.querySelector("tbody") : null;
  const modal = document.getElementById("simBacktestModal");
  const body = modal ? modal.querySelector(".rule-modal-body") : null;
  const bs = body ? getComputedStyle(body) : null;
  const bodyWrap = wrap.parentElement;
  const bws = bodyWrap ? getComputedStyle(bodyWrap) : null;
  let chain = [];
  let n = wrap;
  for (let i = 0; i < 5 && n; i++) {
    const st = getComputedStyle(n);
    chain.push(`${n.tagName}.${String(n.className).slice(0,45)} | oy=${st.overflowY} mh=${st.maxHeight} ch=${n.clientHeight} sh=${n.scrollHeight} fs=${st.flexShrink} fl=${st.flex}`);
    n = n.parentElement;
  }
  return {
    found: true,
    tblRows: tbody ? tbody.children.length : 0,
    wrapClientH: wrap.clientHeight, wrapScrollH: wrap.scrollHeight,
    wrapOY: cs.overflowY, wrapOX: cs.overflowX, wrapMH: cs.maxHeight,
    modalBodyOY: bs ? bs.overflowY : null, modalBodyMH: bs ? bs.maxHeight : null, modalBodyCH: body ? body.clientHeight : 0,
    modalScrollH: modal ? modal.scrollHeight : 0, modalClientH: modal ? modal.clientHeight : 0,
    chain
  };
});
console.log("PROBE:", JSON.stringify(probe, null, 2));
console.log("pageErrors:", pageErrors.length ? pageErrors : "none");
await browser.close();
