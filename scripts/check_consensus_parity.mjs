#!/usr/bin/env node
// check_consensus_parity.mjs — AI 信号认可度(X/Y)独立第二实现复算机检(与前端 app.js 实现互证)
//
// 【目的】用与本前端实现(app.js _consensusVotesOf/_fixedKeptMapByMode/_consensusMap+winner, 2026-08-27
//   计数口径)不同写的第二实现, 对真实 overview.json 全量买入信号逐条复算 Y/X/winner/标签并输出分布, 供:
//   ① 前端改动后的回归互证(Playwright 冒烟抓 data-consensus 属性与本脚本输出逐条比对)
//   ② 审计报告 docs/ops/homepage-ai-endorsement-semantic-audit-20260827.md 分布口径的可持续复现
//
// 【输入】static-site/data/{overview,signal_stats,market_tier_history,kelly_mode_s06_state}.json
//         + static-site/common.js(_KELLY_FADE_MODE_PRESETS 预设 keys, 正则提取)
// 【输出】stdout: Y 分布(全量买入/仅入样两口径)+ X 计数分布 + 当日唯一 winner 断言 + 标签映射抽样断言
//         + 例证核实(0826 恒生科技 / 0824 证券公司与电力公用事业)
//         文件: 全量 (date|index_id|signal)->{y,x,w,label} JSON(默认 /tmp/consensus-expected.json,
//         Playwright 冒烟脚本比对用; --out 可改路径)
//
// 【关键口径】(用户拍板 2026-08-27「保留 per-mode top-1 计数语义+主推=当日票数最多的唯一一支」;
//   与 app.js 注释块「X=AI 模式认可计数」同源)
//   Y=8 预设计票: 7 静态预设(p8/p9/a9/b9/c9/new14/new15)各与 ai_macro.filters 求交一次,
//     交集空=该模式愿意留下计 1 票; bullAuxBackupStop 键=tier map 补判(buy_aux/buy_backup×"牛市·主升",
//     map 未命中=保守放行); S06 第 8 票按 it.date 读快照 effective_mode(仅 a9/new15), 不可用 fail-open 计 1。
//   X=per-mode top-1 计数 0~8: 对 8 个降亏模式(7 静态+S06 动态基座)各问一遍「当天这笔是不是它视角下的
//     第一名」——per-mode per-date 人口=买入类 ∧ _bt_in_universe!==false ∧ 该模式投保留票(mode_votes
//     单源优先), 组内排序 track_score DESC(topEtf=_bk_top 优先→track_score→similarity)→rating(high>mid>low,
//     signal_stats["10d"].score 分档 ≥0.75/≥0.55)→信号类型(buy_backup>buy>buy_aux>buy_special)取 top1;
//     x=被几个模式选为当日第一名。
//   w(当日主推)=当日入样买入中票数最多者; 平票取跟踪分高者; 再按 index_id|signal 字典序兜底保唯一;
//     全零日无 winner(该日全部 0·非主推)。
//   标签(渲染映射, 与 hoverpop show() 同款): w=true → "{x}票·当日主推"; 其余有票 → "{x}·非主推";
//     0 → "0·非主推"; 未入样 → "—"。
//
// 【复现命令】node scripts/check_consensus_parity.mjs
//   (数据截止以 static-site/data/overview.json 的 signals_meta/generated_at 为准; 本脚本为只读校验,
//    不写任何业务数据目录)
//
// 【最近一次结果】2026-08-27(计数口径首跑, 数据窗口 date=20260826/入样196):
//   入样买入 196(0票172/有票24); 有 winner 日=24; 当日唯一 winner 断言 PASS;
//   标签抽样断言 PASS(x∈0..8 全覆盖); FAIL 复现场景(hstech x=5)修复后标签=「5票·当日主推」;
//   例证 ①0826 hstech buy_aux x=5 → 5票·当日主推 ②0824 csi_399975 证券公司(全指) x=8 → 8票·当日主推 /
//   csi_H30199 电力公用事业 x=0 → 0·非主推, 全部成立。
"use strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
// 数据目录: 默认 ROOT/static-site/data; worktree agent 无数据产物时可用
// CONS_DATA_DIR=/Users/linhuichen/code/trade/static-site/data 指向主树(只读)
const D = process.env.CONS_DATA_DIR || path.join(ROOT, "static-site", "data");
const outArgIdx = process.argv.indexOf("--out");
const OUT_FILE = outArgIdx > -1 ? process.argv[outArgIdx + 1] : "/tmp/consensus-expected.json";

const ov = JSON.parse(fs.readFileSync(path.join(D, "overview.json"), "utf8"));
const sigStats = JSON.parse(fs.readFileSync(path.join(D, "signal_stats.json"), "utf8"));
const tierArr = JSON.parse(fs.readFileSync(path.join(D, "market_tier_history.json"), "utf8"));
const s06 = JSON.parse(fs.readFileSync(path.join(D, "kelly_mode_s06_state.json"), "utf8"));

// 预设 keys 提取(与 scripts/check_fade_keys_alignment.py assertion7 同式正则)
const commonTxt = fs.readFileSync(path.join(ROOT, "static-site", "common.js"), "utf8");
const presets = {};
for (const m of commonTxt.matchAll(/\{ id:\s*"([A-Za-z0-9]+)"[\s\S]*?keys:\s*\[([\s\S]*?)\]\s*\}/g)) {
  presets[m[1]] = m[2].match(/"([A-Za-z0-9]+)"/g).map((s) => s.slice(1, -1));
}
console.log("presets found:", Object.keys(presets).join(","));
const STATIC7 = ["p8", "p9", "a9", "b9", "c9", "new14", "new15"];
for (const pid of STATIC7) if (!presets[pid]) throw new Error("missing preset " + pid);

// tier map + S06 byDate
const tierByDate = new Map(tierArr.map((r) => [String(r.date), r.tier]));
const s06ByDate = new Map((s06.daily || []).map((r) => [String(r.date).replace(/[^0-9]/g, ""), r]));
function s06BaseForDate(dateStr) {
  const nd = String(dateStr).replace(/[^0-9]/g, "");
  const row = s06ByDate.get(nd);
  if (!row) return { ok: false };
  const base = row.effective_mode;
  if (base !== "a9" && base !== "new15") return { ok: false };
  return { ok: true, base };
}
// _isBullStopHit 复刻: sig∈{buy_aux,buy_backup} && tier==="牛市·主升"(map 未命中=false 同前端降级)
function isBullStopHit(it) {
  const sig = it.signal || "";
  if (sig !== "buy_aux" && sig !== "buy_backup") return false;
  return tierByDate.get(String(it.date || "")) === "牛市·主升";
}
// mode_votes 单源优先; 缺失走前端表决器同构 fallback(_consensusFrontVotesOf 同构)
function mvOf(it) {
  if (it.ai_macro && it.ai_macro.mode_votes && typeof it.ai_macro.mode_votes === "object") {
    return it.ai_macro.mode_votes;
  }
  const f = (it.ai_macro && Array.isArray(it.ai_macro.filters)) ? it.ai_macro.filters : [];
  const v = {};
  for (const pid of STATIC7) {
    const keys = presets[pid];
    v[pid] = !(f.some((fk) => keys.includes(fk)) || (keys.includes("bullAuxBackupStop") && isBullStopHit(it)));
  }
  return v;
}
// rating 复刻(_getSignalScore→score 分档)
function ratingOf(x) {
  const sigKey = x.signal === "buy_special_filtered" ? "buy_special" : x.signal;
  const iid = sigStats[x.index_id];
  const d = iid && iid[sigKey] && iid[sigKey]["10d"];
  if (!d || d.score == null) return "";
  return d.score >= 0.75 ? "high" : d.score >= 0.55 ? "mid" : "low";
}
// _topEtfByScore 复刻: _bk_top 优先 → track_score 降序 → similarity 降序
function topEtf(etfs) {
  if (!etfs || !etfs.length) return null;
  for (const e of etfs) if (e && e._bk_top === true) return e;
  return etfs.slice().sort((a, b) => {
    const sa = a && typeof a.track_score === "number" ? a.track_score : -1;
    const sb = b && typeof b.track_score === "number" ? b.track_score : -1;
    if (sb !== sa) return sb - sa;
    const ia = a && typeof a.similarity === "number" ? a.similarity : -1;
    const ib = b && typeof b.similarity === "number" ? b.similarity : -1;
    return ib - ia;
  })[0];
}
const RC = { high: 0, mid: 1, low: 2, "": 3 };
const SC = { buy_backup: 0, buy: 1, buy_aux: 2, buy_special: 3, "": 9 };
const CONS_BUY = { buy: 1, buy_aux: 1, buy_special: 1, buy_backup: 1 };
const PIDS_ALL = [...STATIC7, "s06"];

function yOf(it) {
  const f = (it.ai_macro && Array.isArray(it.ai_macro.filters)) ? it.ai_macro.filters : [];
  let y = 0;
  for (const pid of STATIC7) {
    const keys = presets[pid];
    if (f.some((fk) => keys.includes(fk))) continue;
    if (keys.includes("bullAuxBackupStop") && isBullStopHit(it)) continue;
    y++;
  }
  const r = s06BaseForDate(it.date);
  if (r.ok) {
    const bk = presets[r.base] || [];
    if (!(f.some((fk) => bk.includes(fk)) || (bk.includes("bullAuxBackupStop") && isBullStopHit(it)))) y++;
  } else y++; // fail-open
  return y;
}

const items = ov.signals_today || [];
// ===== X 固化表: per-mode per-date top-1 kept sets(与 app.js _fixedKeptMapByMode 同构)=====
const keptMap = {};
for (const pid of PIDS_ALL) keptMap[pid] = {};
for (const x of items) {
  if (!x || !CONS_BUY[x.signal] || x._bt_in_universe === false) continue;
  const mv = mvOf(x);
  for (const pid of STATIC7) {
    if (!mv[pid]) continue; // 该模式没投保留票(falsy=拦)
    (keptMap[pid][x.date] = keptMap[pid][x.date] || []).push(x);
  }
  // S06 第 8 票(#96 fail-open: base 未知=不拦进候选)
  const r6 = s06BaseForDate(x.date);
  if (r6 && r6.ok && !mv[r6.base]) continue;
  (keptMap["s06"][x.date] = keptMap["s06"][x.date] || []).push(x);
}
const consSorted = (a, b) => {
  const ea = topEtf(a.etfs), eb = topEtf(b.etfs);
  const ta = (ea || {}).track_score ?? -1, tb = (eb || {}).track_score ?? -1;
  if (tb !== ta) return tb - ta;
  const ra = RC[ratingOf(a)] ?? 3, rb = RC[ratingOf(b)] ?? 3;
  if (ra !== rb) return ra - rb;
  const sa = SC[a.signal || ""] ?? 9, sb = SC[b.signal || ""] ?? 9;
  if (sa !== sb) return sa - sb;
  return 0;
};
for (const pid of PIDS_ALL) {
  for (const dx of Object.keys(keptMap[pid])) {
    const arr = keptMap[pid][dx].slice().sort(consSorted);
    keptMap[pid][dx] = new Set(arr.length ? [arr[0]] : []);
  }
}
// ===== x 计数 + y =====
const rows = [];
for (const it of items) {
  if (!it || !CONS_BUY[it.signal]) continue;
  const inUni = it._bt_in_universe !== false;
  let x = 0;
  if (inUni) for (const pid of PIDS_ALL) { const kp = keptMap[pid]?.[it.date]; if (kp && kp.has(it)) x++; }
  rows.push({ key: it.date + "|" + it.index_id + "|" + it.signal, date: it.date, id: it.index_id,
    sig: it.signal, x: inUni ? x : "na", y: yOf(it),
    track: ((topEtf(it.etfs) || {}).track_score ?? -1) });
}
// ===== winner(当日主推): 票数最多 → 平票跟踪分高者 → key 字典序兜底保唯一 =====
const byDatePos = {};
for (const r of rows) if (r.x !== "na" && r.x >= 1) (byDatePos[r.date] = byDatePos[r.date] || []).push(r);
const winnerByDate = {};
for (const [dx, arr] of Object.entries(byDatePos)) {
  arr.sort((a, b) => (b.x - a.x) || (b.track - a.track) || a.key.localeCompare(b.key));
  winnerByDate[dx] = arr[0].key;
}
// ===== 标签(渲染映射, 与 app.js hoverpop show() 同款; renderLabel 为纯映射便于抽样断言)=====
function renderLabel(xVal, isWin) {
  const n = Number(xVal);
  if (!Number.isFinite(n)) return "—";
  if (n >= 1 && isWin) return n + "票·当日主推";
  return n + "·非主推";
}
function labelOf(r) {
  if (r.x === "na") return "—";
  return renderLabel(r.x, winnerByDate[r.date] === r.key);
}
// ===== 断言 1: 当日唯一 winner(每日期恰 1 支, 且其 x==当日在样最大 x)=====
let maxFail = [];
{
  for (const dx of Object.keys(winnerByDate)) {
    const dayMax = Math.max(...byDatePos[dx].map((r) => r.x));
    const nWin = byDatePos[dx].filter((r) => r.key === winnerByDate[dx]).length;
    const wr = byDatePos[dx].find((r) => r.key === winnerByDate[dx]);
    if (nWin !== 1 || wr.x !== dayMax) maxFail.push(dx);
  }
}
console.log("\n=== 断言① 当日唯一 winner(winner.x==当日最大且恰1支) ===");
console.log(maxFail.length === 0 ? `PASS(${Object.keys(winnerByDate).length} 个有票日期)` :
  "FAIL: " + maxFail.join(","));

// ===== 断言 2: 标签映射抽样(x∈0..8 各值全覆盖 + winner/非winner 两分支)=====
let lblFail = 0, lblN = 0;
{
  const seenX = new Set();
  for (const r of rows) {
    if (r.x === "na") continue;
    seenX.add(r.x);
    const isW = winnerByDate[r.date] === r.key;
    const got = labelOf(r);
    let expect;
    if (r.x >= 1 && isW) expect = r.x + "票·当日主推";
    else expect = r.x + "·非主推";
    lblN++;
    if (got !== expect) { lblFail++; console.log(`  labelFAIL ${r.key} got=${got} expect=${expect}`); }
  }
  // 抽样表: x∈0..8 × winner/非winner 两分支构造期望(纯映射 renderLabel 验证, 不依赖数据恰好含该值)
  const W = [true, false];
  for (let xv = 0; xv <= 8; xv++) {
    for (const isw of W) {
      let expect;
      if (xv >= 1 && isw) expect = xv + "票·当日主推";
      else expect = xv + "·非主推";
      lblN++;
      if (renderLabel(xv, isw) !== expect) {
        lblFail++;
        console.log(`  labelFAIL synthetic x=${xv} win=${isw} got=${renderLabel(xv, isw)} expect=${expect}`);
      }
    }
  }
}
console.log("\n=== 断言② 标签映射期望(0→0·非主推/winner→N票·当日主推/其他→N·非主推, 含0..8构造抽样) ===");
console.log(lblFail === 0 ? `PASS(${lblN} 条数据全查 + 0..8 构造抽样)` : `FAIL ${lblFail} 条`);

// ===== 输出分布与明细 =====
const out = {};
const ydistAll = {}, ydistUni = {}, xdistUni = {};
let nBuy = 0, nUniBuy = 0;
for (const it of items) {
  if (!CONS_BUY[it.signal]) continue;
  nBuy++;
  const inUni = it._bt_in_universe !== false;
  if (inUni) nUniBuy++;
  const k = it.date + "|" + it.index_id + "|" + it.signal;
  const r = rows.find((rr) => rr.key === k);
  out[k] = { y: r.y, x: r.x, w: winnerByDate[r.date] === k, label: labelOf(r) };
  ydistAll[r.y] = (ydistAll[r.y] || 0) + 1;
  if (inUni) { ydistUni[r.y] = (ydistUni[r.y] || 0) + 1; xdistUni[r.x] = (xdistUni[r.x] || 0) + 1; }
}
console.log("\n=== Y 分布(全部买入类 n=" + nBuy + ") ===");
console.log(JSON.stringify(ydistAll));
console.log("=== Y 分布(仅入样 n=" + nUniBuy + ") ===");
console.log(JSON.stringify(ydistUni));
console.log("=== X 计数分布(仅入样) ===");
console.log(JSON.stringify(xdistUni));

console.log("\n=== X winner 明细(近10日) ===");
for (const dx of Object.keys(winnerByDate).sort().reverse().slice(0, 10)) {
  const w = rows.find((r) => r.key === winnerByDate[dx]);
  console.log(JSON.stringify({ date: dx, index_id: w.id, signal: w.sig, x: w.x, track_score: w.track,
    label: labelOf(w), n_pos_pool: byDatePos[dx].length }));
}

console.log("\n=== 例证核实(2026-08-27 拍板口径) ===");
const hs = items.find((x) => x.date === "20260826" && x.index_id === "hstech");
if (hs) {
  const k = "20260826|hstech|" + hs.signal;
  console.log("例① 0826 恒生科技 x=" + out[k].x + " label=" + out[k].label +
    (out[k].w && out[k].label === "5票·当日主推" ? "(5票公认第一 ✓)" : "(✗ 与预期不符)"));
}
const pool0824 = rows.filter((r) => r.date === "20260824" && r.x !== "na").sort((a, b) => b.x - a.x || b.track - a.track);
for (const p of pool0824) console.log("例② 0824 入样买入池:", JSON.stringify({ index_id: p.id, x: p.x,
  track_score: p.track, label: labelOf(p), is_winner: winnerByDate[p.date] === p.key }));

fs.writeFileSync(OUT_FILE, JSON.stringify(out));
console.log("\nwrote " + OUT_FILE + " (" + Object.keys(out).length + " entries)");

if (maxFail.length || lblFail) process.exit(1);
