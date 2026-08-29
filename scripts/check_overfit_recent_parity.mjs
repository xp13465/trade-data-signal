#!/usr/bin/env node
/**
 * AI 监控卡「7模式组集」一致性校验(T3-2 2026-08-23, §23.2 三铁律②自测完成)。
 *
 * 【目的】监控卡非 p8 模式走「后端 recent 明细打标 → 前端 _ovAggregateRecent 组集」新链路,
 *         本脚本把 app.js 里真实的组集函数切片提取进 vm 沙箱(与 check_fade_predicate_parity.mjs
 *         同方法: 验的就是上线代码本身, 不做影子实现), 对真实 recent 产物跑各模式组合,
 *         用一组独立复核断言验证聚合链正确性。
 * 【断言】A 结构同构: 输出含 accuracy.rolling.{backtest,actual,by_signal,by_grade}+overfit.daily_*
 *         B total 桶独立复核(fadeOn=false): backtest["100"] 末点 n/win_rate vs 从 rows 朴素直数
 *         C p9 模式过滤生效: kept 行不含成员键命中(t!=null 行); 人口 < 全量
 *         D bullstop AND 叠加: 开启后 kept 中 (辅买/备买 × tier===1) 行必不存在; 关闭时存在
 *         E K档: k=1 每日买类保留 ≤1; 卖类信号维度桶无点(kept 剔除非保留行含卖类)
 *         F derive 分段映射抽查: 构造已知 dev 输入逐点断言(40/22.5/30/60/85 五段+clamp)
 *         G trim 裁剪: 序列长度 >200 时截尾 200
 *         H 完整性(2026-08-23 补, 根治 new18 缺键类): 7 模式 keys ∪ bullAuxBackupStop ⊆ recent.keys,
 *           防后端 RECENT_KEYS 漏列致组集缺键(reviewer 终审 FAIL 单点的机器断言化)
 * 【输入】env RECENT_JSON(默认 /tmp/overfit_test3.json)。生成方式(只读生产源+输出独立,
 *         memory unreleased-feature-isolation; 特征文件已由 load_loss_rules_recent 显式走 REPO
 *         双路回退, worktree 直跑即可打全 T1 特征键, 无需再 monkeypatch):
 *   python3 - <<'EOF'
 *   import importlib.util, sys
 *   spec = importlib.util.spec_from_file_location("ovm", "scripts/overfit_monitor.py")
 *   m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
 *   m.OUT_JSON = "/tmp/overfit_test3.json"       # 输出指 /tmp, 不触生产产物
 *   sys.argv = ["overfit_monitor.py", "--dry-run"]  # ⚠必须 --dry-run, 漏加会真发告警邮件
 *   m.main()
 *   EOF
 * 【复现】node scripts/check_overfit_recent_parity.mjs          (默认路径)
 *         RECENT_JSON=/path/overfit.json node scripts/check_overfit_recent_parity.mjs
 */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const RECENT_JSON = process.env.RECENT_JSON || "/tmp/overfit_test3.json";

// --- 切片提取(同 check_fade_predicate_parity.mjs) ---
function sliceDecl(src, name) {
  const pats = [
    new RegExp(`(?:^|\\n)\\s*function\\s+${name}\\s*\\(`),
    new RegExp(`(?:^|\\n)\\s*(?:var|const|let)\\s+${name}\\s*=`),
  ];
  let start = -1, kind = null;
  for (let i = 0; i < pats.length; i++) {
    const m = src.match(pats[i]);
    if (m) { start = m.index + (/^\n/.test(m[0]) ? 1 : 0); kind = i === 0 ? "fn" : "decl"; break; }
  }
  if (start < 0) return null;
  let inS = null, esc = false;
  function scanBlock(from, openCh) {
    let depth = 0, j = from;
    for (; j < src.length; j++) {
      const c = src[j], n = src[j + 1];
      if (inS === "//") { if (c === "\n") inS = null; continue; }
      if (inS === "/*") { if (c === "*" && n === "/") { inS = null; j++; } continue; }
      if (inS === "'" || inS === '"' || inS === "`") { if (esc) { esc = false; continue; } if (c === "\\") { esc = true; continue; } if (c === inS) inS = null; continue; }
      if (c === "'" || c === '"' || c === "`") { inS = c; continue; }
      if (c === "/" && n === "/") { inS = "//"; j++; continue; }
      if (c === "/" && n === "*") { inS = "/*"; j++; continue; }
      if (c === openCh) depth++;
      else if (c === (openCh === "(" ? ")" : openCh === "{" ? "}" : "]")) { depth--; if (depth === 0) return j; }
    }
    return -1;
  }
  let bodyEnd = -1;
  if (kind === "fn") {
    let p = src.indexOf("(", start);
    if (p < 0) return null;
    const pEnd = scanBlock(p, "(");
    if (pEnd < 0) return null;
    let b = pEnd + 1;
    while (b < src.length && /\s/.test(src[b])) b++;
    if (src[b] !== "{") return null;
    bodyEnd = scanBlock(b, "{");
    if (bodyEnd < 0) return null;
    return src.slice(start, bodyEnd + 1);
  }
  let p = start;
  while (p < src.length && !"([{".includes(src[p])) p++;
  if (p >= src.length) return null;
  bodyEnd = scanBlock(p, src[p]);
  if (bodyEnd < 0) return null;
  let end = bodyEnd + 1;
  while (end < src.length && /\s/.test(src[end])) { if (src[end] === ";") { end++; break; } end++; }
  return src.slice(start, end);
}

const APP_SYMBOLS = [
  "_OV_WINDOWS", "_OV_SURFACE_DAYS", "_OV_BT_BUY4", "_OV_SELL2",
  "_ovRiskLevel", "_ovBucketNew", "_ovBucketAdd", "_ovRecentRowFiltered",
  "_ovRolling", "_ovRoundHalfEven", "_ovDeriveDaily", "_ovTrim", "_ovTrimObj", "_ovAggregateRecent",
];
const COMMON_SYMBOLS = ["_KELLY_FADE_MODE_PRESETS", "_tdsFadeModeById"];

const ctx = vm.createContext({ console, JSON, Math, Date, isFinite, parseFloat, parseInt, String, Number, Boolean, Array, Object, Map, Set });
let missing = [];
for (const [rel, syms] of [["static-site/common.js", COMMON_SYMBOLS], ["static-site/app.js", APP_SYMBOLS]]) {
  const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
  for (const n of syms) {
    let code = sliceDecl(src, n);
    if (code == null) { missing.push(`${rel}#${n}`); continue; }
    // 诊断辅助: 组集函数的静默 catch 改为回显异常(定位沙箱内失败原因; 正常跑通时无输出)
    if (n === "_ovAggregateRecent") {
      code = code.replace("catch (e) {", 'catch (e) { console.log("[agg-err] " + (e && e.message) + "\\n" + (e && e.stack));');
    }
    vm.runInContext(code, ctx, { filename: `${rel}::${n}` });
  }
}
if (missing.length) { console.error(`[ov-parity] 符号缺失: ${missing.join(", ")}`); process.exit(1); }

const doc = JSON.parse(fs.readFileSync(RECENT_JSON, "utf8"));
const recent = doc.recent;
if (!recent || !Array.isArray(recent.rows) || !recent.rows.length) {
  console.error("[ov-parity] recent 块缺失或空(老产物? 先按头部注释生成带 recent 的测试产物)");
  process.exit(1);
}
ctx.__RECENT__ = recent;
console.log(`[ov-parity] recent rows=${recent.rows.length} days=${recent.days} 打标键=${recent.keys ? recent.keys.length : "?"}`);

let fails = [];
function check(tag, cond, detail) {
  console.log(`${cond ? "PASS" : "FAIL"}  ${tag}${detail ? "  (" + detail + ")" : ""}`);
  if (!cond) fails.push(tag);
}
function agg(modeId, bullStopOn, fadeOn, k) {
  return JSON.parse(vm.runInContext(
    `JSON.stringify(_ovAggregateRecent(__RECENT__, ${JSON.stringify(modeId)}, ${!!bullStopOn}, ${!!fadeOn}, ${k == null ? "null" : k}))`, ctx));
}

// ---- A 结构同构(p9) ----
const a9 = agg("p9", false, true, null);
check("A 结构: accuracy.rolling 四子树",
  !!(a9 && a9.accuracy && a9.accuracy.rolling && a9.accuracy.rolling.backtest && a9.accuracy.rolling.actual
     && a9.accuracy.rolling.by_signal && a9.accuracy.rolling.by_grade));
check("A 结构: overfit.daily_by_win/daily_by_dim",
  !!(a9 && a9.overfit && a9.overfit.daily_by_win && a9.overfit.daily_by_dim && a9.overfit.daily_by_dim.grade && a9.overfit.daily_by_dim.sig_type));

// ---- B total 桶独立复核(a9, fadeOn=false → 人口=全 rows) ----
// 直数口径与后端 rolling_win_rates 逐位同构: ①滑窗按点索引回退(空桶点占位贡献0, 与
// overfit_monitor.py L1025-1032 一致); ②实盘侧纯卖类日也建点(bucket_actual L979 方案B 注释);
// ③展示序列 trim 到 SURFACE_DAYS=200。
{
  const raw = agg("a9", false, false, null);
  const dayMap = {};     // 回测: 有 w 非空元素的日
  const actDayMap = {};  // 实盘: 有 v!=null 行的日都建点(total 只累计买类, 卖类日=空桶占位)
  for (const r of recent.rows) {
    if (r.w) for (const wv of r.w) {
      if (wv == null) continue;
      const b = dayMap[r.d] || (dayMap[r.d] = { n: 0, win: 0 });
      b.n++; if (wv) b.win++;
    }
    if (r.v != null) {
      const sN = r.s === "buy_special_filtered" ? "buy_special" : r.s;
      const isSell = sN === "sell" || sN === "sell_stop_loss";
      const b = actDayMap[r.d] || (actDayMap[r.d] = { n: 0, win: 0 });
      if (!isSell) { b.n++; if (r.v) b.win++; }   // buckets.t 只含买类(方案A); 卖类日仍占位
    }
  }
  // 同构滑窗: 对齐 _ovRolling(app.js L1939-1957) 用数组索引;
  // 空桶点(n==0)占位参与窗口跨度但不计入 sum, 与 production 行为逐位一致
  const rollLast = (map, w) => {
    const pts = Object.keys(map).sort();
    let lastN = null, lastWr = null;
    for (let i = 0; i < pts.length; i++) {
      const b = map[pts[i]];
      if (!b.n) continue;   // _ovRolling: `if (!b || !b.n) continue` — 不建序列元素
      const start = Math.max(0, i - w + 1);
      let n = 0, win = 0;
      for (let j = start; j <= i; j++) { const v = map[pts[j]].n; if (v) { n += v; win += map[pts[j]].win; } }
      lastN = n; lastWr = n ? win / n * 100 : null;
    }
    return { n: lastN, wr: lastWr, nPoints: pts.length };
  };
  const eBt = rollLast(dayMap, 100), eAct = rollLast(actDayMap, 100);
  const seq = raw.accuracy.rolling.backtest["100"] || [];
  const last = seq[seq.length - 1];
  check("B backtest total 滑窗直数 n 一致", !!last && last.n === eBt.n, `agg=${last ? last.n : "none"} vs direct=${eBt.n}`);
  check("B backtest total 滑窗直数 win_rate 一致", !!last && Math.abs(last.win_rate - eBt.wr) < 1e-9,
    `agg=${last ? last.win_rate.toFixed(6) : "none"} vs direct=${eBt.wr.toFixed(6)}`);
  check("B backtest 点数=min(样本日,200)", seq.length === Math.min(eBt.nPoints, 200), `points=${seq.length} expect=${Math.min(eBt.nPoints, 200)}`);
  const seqA = raw.accuracy.rolling.actual["100"] || [];
  const lastA = seqA[seqA.length - 1];
  check("B actual total(含卖类日占位)滑窗直数一致", !!lastA && lastA.n === eAct.n && Math.abs(lastA.win_rate - eAct.wr) < 1e-9,
    `agg=${lastA ? lastA.n + "/" + lastA.win_rate.toFixed(4) : "none"} vs direct=${eAct.n}/${eAct.wr.toFixed(4)}`);
}

// ---- C p9 过滤生效 ----
{
  const memberSet = {};
  for (const k of vm.runInContext("_tdsFadeModeById('p9').keys", ctx)) memberSet[k] = true;
  const rawOff = agg("p9", false, false, null);
  const rawOn = agg("p9", false, true, null);
  const nOff = (() => { const s = rawOff.accuracy.rolling.backtest["15"]; return s.length ? s[s.length - 1].n : 0; })();
  const nOn = (() => { const s = rawOn.accuracy.rolling.backtest["15"]; return s.length ? s[s.length - 1].n : 0; })();
  check("C p9 fade 开启人口变小", nOn < nOff, `off=${nOff} on=${nOn}`);
}

// ---- D bullstop AND 叠加(p8): 两态独立复刻整条序列逐点对比 ----
// 最强口径: 不依赖增量推导(滑窗重叠会让 Σn 差≈delta×窗口长, 不能直减), 而是把
// 「p8 fade 开 + bullstop 关/开」两态各自从 rows 独立复刻过滤→日桶→滑窗15→trim200,
// 与组集输出逐点(date/n/win_rate)全等。
{
  const p8set = {};
  for (const k of vm.runInContext("_tdsFadeModeById('p8').keys", ctx)) p8set[k] = true;
  const BT5 = { buy: 1, buy_aux: 1, buy_special: 1, buy_special_filtered: 1, buy_backup: 1 };
  function directSeq(bullStopOn) {
    const dayMap = {};
    let deltaRows = 0;
    for (const r of recent.rows) {
      const sig = r.s || "";
      if (!BT5[sig]) continue;
      let filtered;
      if (r.t == null) filtered = true;   // 未入样/+1类两态都拦
      else {
        const kHit = !!(r.k && r.k.split("|").some((x) => p8set[x]));
        const bsHit = bullStopOn && (sig === "buy_aux" || sig === "buy_backup") && r.tier === 1;
        filtered = kHit || bsHit;
        if (!kHit && bsHit) deltaRows++;
      }
      if (filtered) continue;
      if (!r.w) continue;
      const b = dayMap[r.d] || (dayMap[r.d] = { n: 0, win: 0 });
      for (const wv of r.w) { if (wv == null) continue; b.n++; if (wv) b.win++; }
    }
    // 同构滑窗(w=15)+trim(尾部200); 点集合只含 n>0 的日(与 _ovRolling `!b.n continue` 同口径,
    // w 全 null 的零笔行不建点)
    const pts = Object.keys(dayMap).filter((d) => dayMap[d].n > 0).sort();
    const out = [];
    for (let i = 0; i < pts.length; i++) {
      const start = Math.max(0, i - 14);
      let n = 0, win = 0;
      for (let j = start; j <= i; j++) { n += dayMap[pts[j]].n; win += dayMap[pts[j]].win; }
      out.push({ date: pts[i], n, win_rate: n ? win / n * 100 : null });
    }
    return { seq: out.slice(-200), deltaRows };
  }
  const dOff = directSeq(false), dOn = directSeq(true);
  const gotOff = agg("p8", false, true, null).accuracy.rolling.backtest["15"] || [];
  const gotOn = agg("p8", true, true, null).accuracy.rolling.backtest["15"] || [];
  function pointEq(a, b) {
    if (!a || !b || a.date !== b.date || a.n !== b.n) return false;
    if ((a.win_rate == null) !== (b.win_rate == null)) return false;
    return a.win_rate == null || Math.abs(a.win_rate - b.win_rate) < 1e-9;
  }
  let okOff = gotOff.length === dOff.seq.length;
  if (okOff) for (let i = 0; i < gotOff.length; i++) if (!pointEq(gotOff[i], dOff.seq[i])) { okOff = false; break; }
  let okOn = gotOn.length === dOn.seq.length;
  if (okOn) for (let i = 0; i < gotOn.length; i++) if (!pointEq(gotOn[i], dOn.seq[i])) { okOn = false; break; }
  check("D p8+bullstop关 整序列逐点一致", okOff,
    `points agg=${gotOff.length} direct=${dOff.seq.length}`);
  check("D p8+bullstop开 整序列逐点一致(AND叠加收紧)", okOn,
    `points agg=${gotOn.length} direct=${dOn.seq.length} bullstop独拦行=${dOn.deltaRows}`);
  check("D bullstop 确实收紧人口(开启后点数/样本不增)",
    (() => { const ln = (s) => s.length ? s[s.length - 1].n : 0; return ln(gotOn) <= ln(gotOff); })(),
    `off末点n=${gotOff.length ? gotOff[gotOff.length - 1].n : "-"} on末点n=${gotOn.length ? gotOn[gotOn.length - 1].n : "-"}`);
}

// ---- E K档(k=1): 卖类桶空 + 独立重算 kept 后实盘活跃日数逐日一致 ----
// 独立重算须复刻完整人口链: 先过 fade 过滤层(模式成员键命中行被拦, t==null 行被拦),
// 再做每日 top-K 排序取 1。漏掉 fade 层会把成员键命中的行误当保留 → 活跃日集合偏大。
{
  const k1 = agg("a9", false, true, 1);
  const sellSeq = k1.accuracy.rolling.by_signal.sell.backtest["15"] || [];
  const sellSeqA = k1.accuracy.rolling.by_signal.sell.actual["15"] || [];
  check("E K1 下卖类回测桶为空(kept 剔除卖类)", sellSeq.length === 0, `len=${sellSeq.length}`);
  check("E K1 下卖类实盘桶为空", sellSeqA.length === 0, `len=${sellSeqA.length}`);
  // a9 成员集(bullstop=false): 成员键命中(t!=null)的行先被 fade 层拦
  const memberSet = {};
  for (const kk of vm.runInContext("_tdsFadeModeById('a9').keys", ctx)) memberSet[kk] = true;
  // 独立重算 top-K(每日取1)+v!=null 判定 → 期望活跃日集合, 与 actual["15"] 点日期集合全等
  const RC = { high: 0, mid: 1, low: 2, "": 3 };
  const SC = { buy_backup: 0, buy: 1, buy_aux: 2, buy_special: 3 };
  const byDate = {};
  let fadedRows = 0;
  for (const r of recent.rows) {
    if (r.t == null) continue;
    const sN = r.s === "buy_special_filtered" ? "buy_special" : r.s;
    if (!SC.hasOwnProperty(sN)) continue;
    const kHit = !!(r.k && r.k.split("|").some((x) => memberSet[x]));
    if (kHit) { fadedRows++; continue; }   // fade 过滤层(与 _ovRecentRowFiltered 同口径)
    (byDate[r.d] || (byDate[r.d] = [])).push(r);
  }
  const expectDays = new Set();
  for (const d in byDate) {
    const arr = byDate[d].slice().sort((a, b) => (Number(b.t) - Number(a.t))
      || ((RC[a.g == null ? "" : a.g] ?? 3) - (RC[b.g == null ? "" : b.g] ?? 3))
      || ((SC[a.s === "buy_special_filtered" ? "buy_special" : a.s] ?? 9) - (SC[b.s === "buy_special_filtered" ? "buy_special" : b.s] ?? 9)));
    const top = arr[0];
    if (top && top.v != null) expectDays.add(d);
  }
  const actSeq = k1.accuracy.rolling.actual["15"] || [];
  const gotDays = new Set(actSeq.map((p) => p.date));
  let same = gotDays.size === expectDays.size;
  if (same) for (const d of gotDays) if (!expectDays.has(d)) { same = false; break; }
  check("E K1 实盘活跃日集合=top1(v!=null,fade层后)独立重算", same,
    `agg=${gotDays.size} expect=${expectDays.size}(fade拦截行=${fadedRows})`);
}

// ---- F derive 分段映射抽查(期望值按 Python round=banker's half-even 口径) ----
{
  const out = vm.runInContext(`
    (function () {
      var bt = [{ date: "20260101", win_rate: 50 }, { date: "20260102", win_rate: 50 },
                { date: "20260103", win_rate: 50 }, { date: "20260104", win_rate: 50 },
                { date: "20260105", win_rate: 50 }, { date: "20260106", win_rate: 50 }];
      var act = [{ date: "20260101", win_rate: 45 },   // dev=-5  → 55+5=60
                 { date: "20260102", win_rate: 65 },   // dev=+15 → max(10, 25-2.5)=22.5 → half-even 22(Python round 对齐)
                 { date: "20260103", win_rate: 55 },   // dev=+5  → 30
                 { date: "20260104", win_rate: 30 },   // dev=-20 → min(95, 70+15)=85
                 { date: "20260105", win_rate: 90 },   // dev=+40 → max(10, 25-15)=10
                 { date: "20260106", win_rate: null }]; // act 缺失 → 40
      return _ovDeriveDaily(bt, act).map(function (p) { return p.risk_score; });
    })()
  `, ctx);
  const expect = [60, 22, 30, 85, 10, 40];
  check("F derive 六段映射逐点一致(half-even)", JSON.stringify(out) === JSON.stringify(expect), `got=${JSON.stringify(out)} expect=${JSON.stringify(expect)}`);
}

// ---- G trim 裁剪 ----
check("G daily_by_win 15 序列 ≤200 点", (a9.overfit.daily_by_win["15"] || []).length <= 200,
  `len=${(a9.overfit.daily_by_win["15"] || []).length}`);

// ---- H 完整性: 所有模式 keys ∪ 独立开关键 ⊆ recent.keys(2026-08-23 补, new18 缺键根治) ----
// 后端 RECENT_KEYS 漏列某键时 recent_hit_keys 双重门控静默不打标 → 该键组集恒 false,
// 组集人口偏松且无报错。本断言把「common.js 预设增改模式时 RECENT_KEYS 必须同步」纪律
// (overfit_monitor.py 同步纪律注释)机器化: 任一模式任一键缺失即 FAIL。
{
  const rk = new Set(recent.keys || []);
  const modes = vm.runInContext("_KELLY_FADE_MODE_PRESETS", ctx);
  const miss = [];
  for (const m of (Array.isArray(modes) ? modes : Object.values(modes))) {
    for (const k of (m.keys || [])) if (!rk.has(k)) miss.push(`${m.id || "?"}:${k}`);
  }
  if (!rk.has("bullAuxBackupStop")) miss.push("+1开关:bullAuxBackupStop");
  // v20260826: new18 已从 common.js 预设表移除 → 本断言自动只校验现存预设(遍历式, 无需改逻辑);
  // 后端 RECENT_KEYS 打标集保留 new18 键(组成对比区卡仍引用+自定义手勾键仍需打标), 不动。
  check("H 全部下拉预设 keys ∪ bullstop 全部 ⊆ recent.keys(缺键即组集恒 false)", miss.length === 0,
    miss.length ? "缺=" + miss.join(", ") : `全齐(recent.keys=${rk.size}键, 遍历现存预设=${(Array.isArray(modes) ? modes.length : Object.keys(modes).length)}个)`);
}

// ---- I FIELD 修复验证(2026-08-23 用户确认修): by_grade 回测桶出数 + gr 值域合法 ----
// 历史遗留=load_trades FIELD 21 项(rating 错读到 market_tier 字符串)→ by_grade 回测桶恒空。
// 修复后: ①recent 行 gr ∈ {high,mid,low,null} 且非 null 占比 >0; ②组集 by_grade 回测序列非空。
{
  const GR = new Set(["high", "mid", "low"]);
  let grN = 0, grBad = 0;
  for (const r of recent.rows) {
    if (r.gr == null) continue;
    if (GR.has(r.gr)) grN++; else grBad++;
  }
  check("I1 recent.gr 值域 ⊆ {high,mid,low}(无 market_tier 字符串混入)", grBad === 0 && grN > 0,
    `合法=${grN} 非法=${grBad}`);
  const bg = agg("p8", false, true, null).accuracy.rolling.by_grade || {};
  const btLens = ["high", "mid", "low"].map((g) => ((bg[g] || {}).backtest || {})["15"]?.length || 0);
  check("I2 组集 by_grade 回测桶出数(high/mid/low 序列非空)", btLens.every((l) => l > 0),
    `len high/mid/low=${btLens.join("/")}`);
}

console.log(`\n[ov-parity] 总结: ${fails.length === 0 ? "PASS ✅" : "FAIL ❌ " + fails.join(", ")}`);
process.exit(fails.length === 0 ? 0 : 1);
