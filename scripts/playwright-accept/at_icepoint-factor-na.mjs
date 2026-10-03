#!/usr/bin/env node
// 子任务2自测(2026-10-03 #152 遗留②): 上海炒家冰点下钻弹层四因子明细——
//  缺数据因子(value 为 null/NaN, 后端 nav 缺数据)显示「数据缺失,无法判定」
//  评估过未命中因子(value 有值但未达阈值)保持「✗未中 当前 X / 阈值 Y」
//  两场景文案可区分, DOM class 区分(sh-f-na vs sh-f-miss)
import { chromium } from "playwright";

const BASE = "http://localhost:8379/";
const NEW_APP = "/Users/linhuichen/code/trade/.claude/worktrees/agent-a8403e0209f37cbb5/static-site/app.js";
const SRC = (await import("fs")).readFileSync(NEW_APP, "utf8");

let FAIL = 0;
const ok = (m) => console.log("  PASS  " + m);
const bad = (m) => { FAIL++; console.log("  FAIL  " + m); };

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1400, height: 800 } });
const page = await ctx.newPage();
for (const p of ["**/data/overview.json*", "**/data/intraday_snapshot.json*"]) {
  await page.route(p, r => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
}
await page.route("**/data/boot.json*", r => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ overview: {}, config: {} }) }));
await page.route(/app\.min\.js(\?.*)?$/, r => r.fulfill({ status: 200, contentType: "application/javascript", body: SRC }));
await page.goto(BASE, { waitUntil: "load", timeout: 90000 }).catch(() => {});
await page.waitForTimeout(1200);

// 场景① 缺数据日: sh_hits.total<4(某因子 value 缺失, 如历史缺楼层数据段), 但其余因子有值评估
const out1 = await page.evaluate(() => {
  const day = {
    date: "20260721", freeze: [], signals: [],
    sh_freeze: false, sh_level: "", sh_hits: { n: 1, total: 3 },
    sh_factors: [
      { name: "楼层", key: "f1", value: null, threshold: 4, hit: false },
      { name: "涨停", key: "f2", value: 28, threshold: 40, hit: true },
      { name: "跌停", key: "f3", value: 9, threshold: 15, hit: false },
      { name: "地量", key: "f4", value: 0.22, threshold: 30, hit: true },
    ],
  };
  window.openSentimentDayDetailModal(day);
  const m = document.getElementById("sentimentDayDetailModal");
  const txt = m.textContent.replace(/\s+/g, " ").trim();
  const rows = [...m.querySelectorAll(".dd-row.sh-f-na")];
  const missRows = [...m.querySelectorAll(".dd-row.sh-f-miss")];
  const marks = [...m.querySelectorAll(".sh-f-mark")].map(x => x.textContent.trim());
  return {
    txt,
    hasMissingTxt: txt.indexOf("数据缺失,无法判定") >= 0,
    naRows: rows.length, naNames: rows.map(r => r.querySelector(".dd-name").textContent.trim()),
    missRows: missRows.length,
    hasMissOld: txt.indexOf("✗未中") >= 0,
    marks,
  };
}).catch(e => ({ err: String(e) }));

// 场景② 评估未命中日: 四因子 value 全可得(total=4), 未达阈值 → 保持 ✗未中 当前 X / 阈值 Y
const out2 = await page.evaluate(() => {
  const day = {
    date: "20260722", freeze: [], signals: [],
    sh_freeze: false, sh_level: "", sh_hits: { n: 2, total: 4 },
    sh_factors: [
      { name: "楼层", key: "f1", value: 11, threshold: 4, hit: false },
      { name: "涨停", key: "f2", value: 28, threshold: 40, hit: true },
      { name: "跌停", key: "f3", value: 9, threshold: 15, hit: false },
      { name: "地量", key: "f4", value: 0.22, threshold: 30, hit: true },
    ],
  };
  window.openSentimentDayDetailModal(day);
  const m = document.getElementById("sentimentDayDetailModal");
  const txt = m.textContent.replace(/\s+/g, " ").trim();
  return {
    txt,
    hasMissMark: txt.indexOf("✗未中") >= 0,
    hasCurrentThreshold: txt.indexOf("当前 11 / 阈值 ≤4") >= 0,
    hasMissingTxt: txt.indexOf("数据缺失,无法判定") >= 0,
    naRows: m.querySelectorAll(".dd-row.sh-f-na").length,
    missRows: m.querySelectorAll(".dd-row.sh-f-miss").length,
  };
}).catch(e => ({ err: String(e) }));

if (out1.err || out2.err) { bad("evaluate err: " + out1.err + " | " + out2.err); }
else {
  // 场景①: 缺数据因子被标「数据缺失,无法判定」, 与「✗未中」并存且可区分
  out1.hasMissingTxt ? ok("场景①(缺数据日) 明细含「数据缺失,无法判定」") : bad("场景①缺数据日未标缺失");
  out1.naRows === 1 && out1.naNames.some(n => n.indexOf("楼层") >= 0) ? ok("场景① 缺数据因子楼层挂 sh-f-na 行") : bad("场景① sh-f-na 行错误: " + JSON.stringify(out1.naNames));
  out1.hasMissOld ? ok("场景① 评估过未中因子(跌停 value=9)仍保持「✗未中」") : bad("场景① 未中标记缺失");
  out1.missRows >= 1 ? ok("场景① 评估未中行仍挂 sh-f-miss") : bad("场景① sh-f-miss 行缺失");
  // 场景① 与 场景② 文案互斥可区分: 缺数据日无「当前 X / 阈值」样式(缺数据因子显示 — / —)
  if (out1.txt.indexOf("数据缺失,无法判定") >= 0 && out1.txt.indexOf("✗未中") >= 0)
    ok("场景① 两种状态并存, 文案可区分");
  else bad("场景① 文案未并存区分");

  // 场景②: 评估过未命中因子保持「✗未中 当前 11 / 阈值 ≤4」, 且全可得无「数据缺失」
  out2.hasMissMark ? ok("场景②(评估未中) 明细含「✗未中」") : bad("场景② 未中标记缺失");
  out2.hasCurrentThreshold ? ok("场景② 保持「当前 11 / 阈值 ≤4」样式") : bad("场景② 当前/阈值样式缺失: " + out2.txt.slice(0, 200));
  out2.hasMissingTxt ? bad("场景② 误标「数据缺失」(应无缺失因子)") : ok("场景② 无「数据缺失」误标");
  out2.naRows === 0 ? ok("场景② 无 sh-f-na 行") : bad("场景② 出现 sh-f-na 行");

  // 反向证伪: 若旧代码(f.hit?"✓命中":"✗未中"), 场景①缺数据因子也会显示 ✗未中 → 与场景②无区分
  // 我们用 marks 对比两场景中「楼层」的标记: 场景①=数据缺失, 场景②=✗未中
  const mark1 = (out1.marks && out1.marks[0]) || "";
  if (mark1 === "数据缺失,无法判定") ok("场景① 楼层标记=" + mark1 + " (与场景②区分)");
  else bad("场景① 楼层标记=" + mark1);
}

await b.close();
console.log(FAIL ? "FAILURES=" + FAIL : "ALL PASS");
process.exit(FAIL ? 1 : 0);