// S06 生产事故修复验证(§23.15 根治, 2026-09-02)
// 目的: 用真实 trades 全量 + 「旧快照(new15 模拟)」+ 切片 common.js 真实 _tdsS06BaseForDate,
//   对比修复前(bad_mode → fail-open 裸放行)与修复后(bad_mode → bad_mode_fallback 真过滤)的计数。
// 期待: 修复前 OpenSet≈3972(用户报告数字); 修复后 OpenSet=0, bad_mode_fallback 吸收 3972。
// 复现命令: node /tmp/s06_fix_verify.mjs
import fs from "node:fs";
import vm from "node:vm";

import path from "node:path";
import { fileURLToPath } from "node:url";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "../../../..");  // 项目根(docs/kelly/analysis/scripts → 上溯 4 级)
const td = JSON.parse(fs.readFileSync(ROOT + "/static-site/data/signal_kelly_trades.json", "utf8"));
const s06 = JSON.parse(fs.readFileSync(ROOT + "/static-site/data/kelly_mode_s06_state.json", "utf8"));
const commonSrc = fs.readFileSync(ROOT + "/static-site/common.js", "utf8");

// ── 切片 common.js 声明(与 repro.mjs 同机制) ──
function sliceDecl(src, name) {
  const pats = [
    new RegExp("(?:^|\\n)\\s*function\\s+" + name + "\\s*\\("),
    new RegExp("(?:^|\\n)\\s*(?:var|const|let)\\s+" + name + "\\s*="),
  ];
  let start = -1, kind = null;
  for (let i = 0; i < pats.length; i++) {
    const m = src.match(pats[i]);
    if (m) { start = m.index + (/^\n/.test(m[0]) ? 1 : 0); kind = i === 0 ? "fn" : "decl"; break; }
  }
  if (start < 0) return null;
  let i = start, inS = null, esc = false;
  function scanBlock(from, openCh) {
    let depth = 0, j = from;
    for (; j < src.length; j++) {
      const c = src[j], n = src[j + 1];
      if (inS === "//") { if (c === "\n") inS = null; continue; }
      if (inS === "/*") { if (c === "*" && n === "/") { inS = null; j++; } continue; }
      if (inS === "'" || inS === '"' || inS === "`") { if (esc) { esc = false; continue; } if (c === "\\") { esc = false; continue; } if (c === inS) inS = null; continue; }
      if (c === "'" || c === '"' || c === "`") { inS = c; continue; }
      if (c === "/" && n === "/") { inS = "//"; j++; continue; }
      if (c === "/" && n === "*") { inS = "/*"; j++; continue; }
      if (c === openCh) depth++;
      else if (c === (openCh === "(" ? ")" : openCh === "{" ? "}" : "]")) { depth--; if (depth === 0) return j; }
    }
    return -1;
  }
  if (kind === "fn") {
    let p = src.indexOf("(", start);
    if (p < 0) return null;
    const pEnd = scanBlock(p, "(");
    if (pEnd < 0) return null;
    let b = pEnd + 1;
    while (b < src.length && /\s/.test(src[b])) b++;
    if (src[b] !== "{") return null;
    const bodyEnd = scanBlock(b, "{");
    if (bodyEnd < 0) return null;
    return src.slice(start, bodyEnd + 1);
  }
  let p = start;
  while (p < src.length && !"([{".includes(src[p])) p++;
  if (p >= src.length) return null;
  const openCh = src[p];
  const bodyEnd = scanBlock(p, openCh);
  if (bodyEnd < 0) return null;
  let end = bodyEnd + 1;
  while (end < src.length && /\s/.test(src[end])) { if (src[end] === ";") { end++; break; } end++; }
  return src.slice(start, end);
}

const COMMON_SYMBOLS = ["_KELLY_FADE_FRONT_KEY_ORDER", "_KELLY_FADE_GATE_KEY_ORDER", "_KELLY_FADE_T1_KEYS", "_KELLY_FADE_ALL_KEYS", "_KELLY_FADE_MODE_PRESETS", "_tdsFadeModeById", "_tdsS06NormalizeDate", "_tdsS06BaseForDate"];
const ctx = vm.createContext({ console, JSON, Math, Date, isFinite, parseFloat, parseInt, String, Number, Boolean, Array, Object, Map, Set, NaN });
vm.runInContext("var _tdsS06State = null, _tdsS06ByDate = null, _tdsS06LoadErr = null, _tdsS06FiltersCache = null;", ctx);
for (const name of COMMON_SYMBOLS) {
  const code = sliceDecl(commonSrc, name);
  if (code == null) { console.error("missing slice: " + name); process.exit(1); }
  vm.runInContext(code, ctx, { filename: name });
}

// 真实 trades 全量(quadrants.<象限>.<卖出模式> → rows), 按 _kellyBaseKey 去重
const fIdx = {}; (td.fields || []).forEach(function (f, i) { fIdx[f] = i; });
function rowToBaseKey(r) {
  return [r[fIdx.signal_date], r[fIdx.index_id], r[fIdx.signal], r[fIdx.buy_date], r[fIdx.etf_code]].join("|");
}
const allTrades = new Set();
for (const qk of Object.keys(td.quadrants || {})) {
  const q = td.quadrants[qk];
  if (!q || typeof q !== "object") continue;
  for (const mk of Object.keys(q)) {
    for (const r of q[mk]) allTrades.add(rowToBaseKey(r));
  }
}
console.log("真实 trades 去重唯一笔(base key) = " + allTrades.size);

// 预置两套快照: 现网(off_base=new14, modes∈{a9,new14}) 与 旧快照模拟(new14→new15, off_base=new15)
function buildCtx(snap) {
  const c = vm.createContext({ console, JSON, Math, Date, isFinite, parseFloat, parseInt, String, Number, Boolean, Array, Object, Map, Set, NaN });
  vm.runInContext("var _tdsS06State = null, _tdsS06ByDate = null, _tdsS06LoadErr = null, _tdsS06FiltersCache = null;", c);
  for (const name of COMMON_SYMBOLS) {
    const code = sliceDecl(commonSrc, name);
    vm.runInContext(code, c, { filename: name });
  }
  vm.runInContext("_tdsS06State = __S06__; _tdsS06ByDate = {}; for (var i=0;i<__S06__.daily.length;i++) _tdsS06ByDate[_tdsS06NormalizeDate(__S06__.daily[i].date)] = __S06__.daily[i];", Object.assign(c, { __S06__: snap }));
  return c;
}
const oldSnap = JSON.parse(JSON.stringify(s06));
oldSnap.off_base = "new15";
for (const r of oldSnap.daily) if (r.effective_mode === "new14") r.effective_mode = "new15";
const ctxNow = buildCtx(s06);
const ctxOld = buildCtx(oldSnap);

function classifyAll(c, simOldBadModeFailOpen) {
  // simOldBadModeFailOpen=true 时模拟修复前语义: bad_mode(基座非 a9/new14) 归入 fail-open(OpenSet)。
  // 修复后语义: bad_mode → bad_mode_fallback(真过滤, 只计轻标注)。
  const dist = { bad_mode_fallback: 0, out_of_range_fallback: 0, no_row: 0, not_loaded: 0, load_err: 0, normal: 0 };
  const keys = { open: [], bad: [], oor: [], normal: [] };
  for (const key of allTrades) {
    const d = key.split("|")[0];
    const r = vm.runInContext("_tdsS06BaseForDate(__D__)", Object.assign(c, { __D__: d }));
    const isBad = r && r.ok && r.reason === "bad_mode_fallback";
    if (simOldBadModeFailOpen && isBad) { dist.bad_mode_fallback++; keys.open.push(key); continue; }
    if (!r || !r.ok) {
      const reason = r ? r.reason : "not_loaded";
      dist[reason] = (dist[reason] || 0) + 1;
      keys.open.push(key);
    } else if (isBad) { dist.bad_mode_fallback++; keys.bad.push(key); }
    else if (r.reason === "out_of_range_fallback") { dist.out_of_range_fallback++; keys.oor.push(key); }
    else { dist.normal++; keys.normal.push(key); }
  }
  return { dist, keys };
}

const now = classifyAll(ctxNow, false);
const old = classifyAll(ctxOld, true);   // 修复前语义: bad_mode → fail-open
const oldFixed = classifyAll(ctxOld, false); // 修复后语义: bad_mode → fallback

function fmt(c) {
  const d = c.dist;
  return `Open(fail-open) = ${d.no_row + d.not_loaded + d.load_err} | bad_mode_fallback = ${d.bad_mode_fallback} | out_of_range_fallback = ${d.out_of_range_fallback} | normal = ${d.normal}`;
}
console.log("\n现网快照(new14):   " + fmt(now));
console.log("旧快照(new15)修复前语义: " + fmt(old));
console.log("旧快照(new15)修复后语义: " + fmt(oldFixed));

const oldOpen = old.dist.no_row + old.dist.not_loaded + old.dist.load_err + old.dist.bad_mode_fallback; // 修复前 bad_mode 也算 Open
const nowOpen = now.dist.no_row + now.dist.not_loaded + now.dist.load_err;
const fixedOpen = oldFixed.dist.no_row + oldFixed.dist.not_loaded + oldFixed.dist.load_err;
console.log("\n[修复有效性判定]");
console.log(" 修复前(旧快照+bad_mode fail-open): Open = " + oldOpen + "  →  应≈3972(用户报告)");
console.log(" 修复后(旧快照+bad_mode→fallback):  Open = " + fixedOpen + "  →  应=0");
console.log(" 旧快照下 bad_mode_fallback 吸收笔数 = " + oldFixed.dist.bad_mode_fallback + "  →  应≈3972");
const check3972 = Math.abs(oldOpen - 3972) <= 5;
const checkZero = fixedOpen === 0;
console.log(" ① 复现 3972: " + (check3972 ? "PASS" : "FAIL(差=" + (oldOpen - 3972) + ")"));
console.log(" ② 修复后 Open 归零: " + (checkZero ? "PASS" : "FAIL"));

// 修复后 FallbackSet 总量(轻标注)= bad_mode_fallback + out_of_range_fallback
console.log("\n 修复后 FallbackSet(轻标注) = " + (oldFixed.dist.bad_mode_fallback + oldFixed.dist.out_of_range_fallback) + " (bad_mode + out_of_range)");
console.log(" 现网下 FallbackSet = " + (now.dist.bad_mode_fallback + now.dist.out_of_range_fallback));
