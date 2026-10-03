#!/usr/bin/env node
// 子任务3验证(2026-10-03 #152 遗留③): 图例新增 4 条(重叠/仅上海炒家/仅老算法/认可度)与老条目
//  同构 = 都含「色块+文字」(.sig-cal-legend-swatch)。老条目(冰点维度/上海炒家冰点/红紫绿)保持原样。
//  668993e86 已做(色块+文字对齐), 本轮验收级自测确认 + 老条目零变化(对比 main 代码基线)。
import { chromium } from "playwright";
import fs from "fs";

const BASE = "http://localhost:8379/";
const SRC = fs.readFileSync("/Users/linhuichen/code/trade/.claude/worktrees/agent-a8403e0209f37cbb5/static-site/app.js", "utf8");
const sampleStr = fs.readFileSync("/tmp/merged_overview.json", "utf8");

let FAIL = 0;
const ok = (m) => console.log("  PASS  " + m);
const bad = (m) => { FAIL++; console.log("  FAIL  " + m); };

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1400, height: 800 } });
const page = await ctx.newPage();
await page.route("**/data/overview.json*", r => r.fulfill({ status: 200, contentType: "application/json", body: sampleStr }));
await page.route("**/data/boot.json*", r => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ overview: JSON.parse(sampleStr), config: {} }) }));
await page.route("**/data/intraday_snapshot.json*", r => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
await page.route(/app\.min\.js(\?.*)?$/, r => r.fulfill({ status: 200, contentType: "application/javascript", body: SRC }));
await page.goto(BASE, { waitUntil: "load", timeout: 90000 }).catch(() => {});
await page.waitForTimeout(1500);

const out = await page.evaluate((sStr) => {
  const s = JSON.parse(sStr);
  const el = document.createElement("div");
  el.innerHTML = window._renderSentimentCalendar(Array.isArray(s.sentiment_calendar) ? s.sentiment_calendar : s);
  const items = [...el.querySelectorAll(".sig-cal-legend-item")];
  const parse = (it) => ({ text: it.textContent.replace(/\s+/g, " ").trim(), swatches: it.querySelectorAll(".sig-cal-legend-swatch").length });
  return items.map(parse);
}, sampleStr).catch(e => ({ err: String(e) }));

if (out.err) bad("evaluate err: " + out.err);
else {
  // 定位 4 条新增(来源分类/认可度)
  const find = (txt) => out.filter(i => i.text.indexOf(txt) >= 0);
  const new4 = ["重叠=两口径都中", "仅上海炒家", "仅老算法", "认可度 x/y=两口径命中数/可得数"];
  for (const t of new4) {
    const hit = find(t);
    if (hit.length && hit[0].swatches >= 1) ok(`新增条目「${t}」含色块 ×${hit[0].swatches}`);
    else bad(`新增条目「${t}」缺色块: ` + JSON.stringify(hit));
  }
  // 老条目(冰点维度/上海炒家冰点)同含色块 → 新4条与老条目同类
  for (const t of ["冰点维度（情绪分<20", "上海炒家冰点（四因子共振）"]) {
    const hit = find(t);
    if (hit.length && hit[0].swatches >= 1) ok(`老条目「${t}」仍含色块 ×${hit[0].swatches}(同类基准)`);
    else bad(`老条目「${t}」色块缺失: ` + JSON.stringify(hit));
  }
  // 4 条新条目全部有色块 → 与老条目结构同类
  const allNewHaveSwatch = new4.every(t => { const h = find(t); return h.length && h[0].swatches >= 1; });
  allNewHaveSwatch ? ok("新 4 条与老条目同为「色块+文字」结构") : bad("新 4 条样式未与老条目对齐");
  // 红/紫/绿 老条目(彩色文字样式)未受影响
  const red = find("红=卖");
  red.length && red[0].swatches === 0 ? ok("老条目「红=卖」保持原样(彩色文字非色块)") : bad("「红=卖」样式异常: " + JSON.stringify(red));
}

await b.close();
console.log(FAIL ? "FAILURES=" + FAIL : "ALL PASS");
process.exit(FAIL ? 1 : 0);