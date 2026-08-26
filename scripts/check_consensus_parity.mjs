#!/usr/bin/env node
// check_consensus_parity.mjs — AI 信号认可度(X/Y)独立第二实现复算机检(与前端 app.js 实现互证)
//
// 【目的】用与本前端实现(app.js _consensusVotesOf/_fixedKeptSet/_consensusMap, 2026-08-26)不同写的
//   第二实现, 对真实 overview.json 全量买入信号逐条复算 Y/X 并输出分布, 供:
//   ① 前端改动后的回归互证(Playwright 冒烟抓 data-consensus 属性与本脚本输出逐条比对)
//   ② 调研报告 docs/kelly/toggle/ai-consensus-score-research-20260826.md 分布口径的可持续复现
//
// 【输入】static-site/data/{overview,signal_stats,market_tier_history,kelly_mode_s06_state}.json
//         + static-site/common.js(_KELLY_FADE_MODE_PRESETS 预设 keys, 正则提取)
// 【输出】stdout: Y 分布(全量买入/仅入样两口径)+X per-date top1+报告三处 1:1 例证核实
//         文件: 全量 (date|index_id|signal)->{y,x} JSON(默认 /tmp/consensus-expected.json,
//         Playwright 冒烟脚本比对用; --out 可改路径)
//
// 【关键口径】(与 app.js 注释块 L4779-4792 同源)
//   Y=8 预设计票: 7 静态预设(p8/p9/a9/b9/c9/new14/new15)各与 ai_macro.filters 求交一次,
//     交集空=该模式愿意留下计 1 票; bullAuxBackupStop 键=tier map 补判(buy_aux/buy_backup×"牛市·主升",
//     map 未命中=保守放行); S06 第 8 票按 it.date 读快照 effective_mode(仅 a9/new15), 不可用 fail-open 计 1。
//   X=K1★标准视角固化表: 人口=买入类 ∧ _bt_in_universe!==false ∧ 未命中 new14 键集;
//     组内排序 track_score DESC(topEtf=_bk_top 优先→track_score→similarity)→rating(high>mid>low,
//     signal_stats["10d"].score 分档 ≥0.75/≥0.55)→信号类型(buy_backup>buy>buy_aux>buy_special)→稳定序兜底;
//     per-date top1=X1。
//
// 【复现命令】node scripts/check_consensus_parity.mjs
//   (数据截止以 static-site/data/overview.json 的 signals_meta/generated_at 为准; 本脚本为只读校验,
//    不写任何业务数据目录)
//
// 【最近一次结果】2026-08-26: 入样196条 Y={8:6,5:33,4:1,3:20,2:112,1:2,0:22}(与调研报告
//   {…2:111,1:7,0:22} 总200 差异=数据窗口滚动); 例证①0723恒指Y=0 ②0824 证券公司78.2 X=1/
//   电力公用事业71.0 X=0 全部成立。
"use strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const D = path.join(ROOT, "static-site", "data");
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

function votesOf(it) {
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
// X 固化表: 人口=买入∧入样∧未命中 new14; per-date top1
const byDate = {};
for (const x of items) {
  if (!x || !CONS_BUY[x.signal] || x._bt_in_universe === false) continue;
  const fx = (x.ai_macro && Array.isArray(x.ai_macro.filters)) ? x.ai_macro.filters : [];
  if (fx.some((fk) => presets.new14.includes(fk))) continue;
  (byDate[x.date] = byDate[x.date] || []).push(x);
}
const keptKeys = new Set(); // date|index_id|signal
const keptDetail = [];
for (const dx of Object.keys(byDate)) {
  const arr = byDate[dx].slice().sort((a, b) => {
    const ta = (topEtf(a.etfs) || {}).track_score ?? -1;
    const tb = (topEtf(b.etfs) || {}).track_score ?? -1;
    if (tb !== ta) return tb - ta;
    const ra = RC[ratingOf(a)] ?? 3, rb = RC[ratingOf(b)] ?? 3;
    if (ra !== rb) return ra - rb;
    const sa = SC[a.signal || ""] ?? 9, sb = SC[b.signal || ""] ?? 9;
    if (sa !== sb) return sa - sb;
    return 0;
  });
  const t = arr[0];
  if (t) {
    keptKeys.add(t.date + "|" + t.index_id + "|" + t.signal);
    keptDetail.push({ date: dx, index_id: t.index_id, signal: t.signal,
      track_score: (topEtf(t.etfs) || {}).track_score, rating: ratingOf(t), n_pool: arr.length });
  }
}
keptDetail.sort((a, b) => b.date.localeCompare(a.date));

// 全量 (y,x)
const out = {};
const ydistAll = {}, ydistUni = {};
let nBuy = 0, nUniBuy = 0;
for (const it of items) {
  if (!CONS_BUY[it.signal]) continue;
  nBuy++;
  const inUni = it._bt_in_universe !== false;
  if (inUni) nUniBuy++;
  const f = (it.ai_macro && Array.isArray(it.ai_macro.filters)) ? it.ai_macro.filters : [];
  const blockedN14 = f.some((fk) => presets.new14.includes(fk));
  const y = votesOf(it);
  const x = !inUni ? "na" : (!blockedN14 && keptKeys.has(it.date + "|" + it.index_id + "|" + it.signal)) ? 1 : 0;
  out[it.date + "|" + it.index_id + "|" + it.signal] = { y, x };
  ydistAll[y] = (ydistAll[y] || 0) + 1;
  if (inUni) ydistUni[y] = (ydistUni[y] || 0) + 1;
}
console.log("\n=== Y 分布(全部买入类 n=" + nBuy + ") ===");
console.log(JSON.stringify(ydistAll));
console.log("=== Y 分布(仅入样 _bt_in_universe!=false n=" + nUniBuy + ") ===");
console.log(JSON.stringify(ydistUni));
console.log("调研报告口径(2026-08-25 数据快照): {8:6,5:33,4:1,3:20,2:111,1:7,0:22}(总200)");

console.log("\n=== X per-date top1(近8日) ===");
for (const k of keptDetail.slice(0, 8)) console.log(JSON.stringify(k));

console.log("\n=== 报告 1:1 例证核实 ===");
const hsi = items.find((x) => x.date === "20260723" && x.index_id === "hsi" && x.signal === "buy_special");
if (hsi) {
  const y = out["20260723|hsi|buy_special"].y;
  console.log("例① 0723 恒指·追关注 Y=" + y + (y === 0 ? "(8票全拦 ✓)" : "(✗ 与报告不符)"));
}
const pool = byDate["20260824"] || [];
for (const p of pool.map((p) => ({ id: p.index_id, ts: (topEtf(p.etfs) || {}).track_score,
  x: out[p.date + "|" + p.index_id + "|" + p.signal].x }))) console.log("例③ 0824 人口池:", JSON.stringify(p));

fs.writeFileSync(OUT_FILE, JSON.stringify(out));
console.log("\nwrote " + OUT_FILE + " (" + Object.keys(out).length + " entries)");
