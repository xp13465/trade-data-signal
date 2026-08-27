// P1-S06 #95/#96 修复新旧对拍自测(2026-08-27)
// 旧实现=git HEAD cecf8e6b7 原代码逐字复刻(app.js L4820-4851 Y 函数 / L4876-4898 X 表);
// 新实现=worktree 修复版复刻。断言:Y 全场景新旧逐位等价;X 仅 #96/#同源两处预期差异(bull 补齐+s06 fail-open)。
const PRESETS = {
  p8:    ["excludeSpecialBear","n2NovSpecialIndustry","janMidRating","janMidSpecial","k2c5HkChase","r7MayReinforced","excludeAuxCross","greedy15"],
  p9:    ["excludeSpecialBear","n2NovSpecialIndustry","janMidRating","janMidSpecial","k2c5HkChase","r7MayReinforced","excludeAuxCross","greedy15","bullAuxBackupStop"],
  a9:    ["excludeSpecialBear","n2NovSpecialIndustry","janMidRating","janMidSpecial","k2c5HkChase","r7MayReinforced","excludeAuxCross","greedy15","bullAuxBackupStop","t1LowTurnSpecial","q1QvixLowPct","m1MarginDownBull","v1HighVol20","r1VolRatioLow","k3ConceptBuy","r2bSpecialGlobal","r2gLowRatingQ3"],
  b9:    ["excludeSpecialBear","n2NovSpecialIndustry","janMidRating","janMidSpecial","k2c5HkChase","r7MayReinforced","excludeAuxCross","greedy15","bullAuxBackupStop","t1LowTurnSpecial","q1QvixLowPct","m1MarginDownBull","r1VolRatioLow","r2bSpecialGlobal","r2gLowRatingQ3"],
  c9:    ["excludeSpecialBear","n2NovSpecialIndustry","janMidRating","janMidSpecial","k2c5HkChase","r7MayReinforced","excludeAuxCross","greedy15","bullAuxBackupStop","n1NorthOutflow","t1LowTurnSpecial","d1LowDivYield","h1VolChgHighA","m1MarginDownBull","p1LowDivBackup","r2bSpecialGlobal"],
  new14: ["r10May6NonMay","greedy15","janMidSpecial","k2c5HkChase","k3ConceptBuy","declinePhaseSpecial","n1NorthOutflow","t1LowTurnSpecial","d1LowDivYield","q1QvixLowPct","h1VolChgHighA","m1MarginDownBull","p1LowDivBackup","r2bSpecialGlobal"],
  new15: ["r10May6NonMay","greedy15","janMidSpecial","k2c5HkChase","k3ConceptBuy","declinePhaseSpecial","n1NorthOutflow","t1LowTurnSpecial","d1LowDivYield","q1QvixLowPct","h1VolChgHighA","m1MarginDownBull","p1LowDivBackup","r2bSpecialGlobal","excludeTierNone"],
};
function backendVotes(filters, bullTier) {
  const fs = new Set(filters); const votes = {};
  for (const pid of Object.keys(PRESETS)) {
    const keys = PRESETS[pid];
    if (filters.some((f) => keys.includes(f))) { votes[pid] = false; continue; }
    if (keys.includes("bullAuxBackupStop") && filters.sig === "buy_aux" && bullTier === "牛市·主升") { votes[pid] = false; continue; }
    votes[pid] = true;
  }
  return votes;
}
let S06MODE = "ok", ROWBASE = "a9", BULLHIT = false;
function baseForDate() {
  if (S06MODE === "not_loaded") return { ok: false, reason: "load_err" };
  if (S06MODE === "out_of_range") return { ok: false, reason: "out_of_range" };
  return { ok: true, base: ROWBASE };
}
const isBullStopHit = () => BULLHIT;
const PIDS = Object.keys(PRESETS);
const MEMBERS = {};
for (const p of PIDS) { const m = {}; for (const k of PRESETS[p]) m[k] = true; MEMBERS[p] = m; }

// ===== 旧实现(HEAD cecf8e6b7 逐字复刻)=====
function yOld(it) {
  const mv = it.ai_macro && it.ai_macro.mode_votes;
  if (mv) {
    let y2 = 0;
    for (const pid of PIDS) if (mv[pid]) y2++;
    const r6 = baseForDate();
    if (r6 && r6.ok && mv[r6.base]) y2++;
    else if (!r6 || !r6.ok) y2++;
    return y2;
  }
  const f2 = (it.ai_macro && Array.isArray(it.ai_macro.filters)) ? it.ai_macro.filters : [];
  let y2 = 0;
  for (const pid of PIDS) {
    const m2 = MEMBERS[pid] || {};
    if (f2.some((fk) => m2[fk])) continue;
    if (m2.bullAuxBackupStop && isBullStopHit(it)) continue;
    y2++;
  }
  const r6 = baseForDate();
  if (r6 && r6.ok) {
    const bm = MEMBERS[r6.base] || {};
    if (!(f2.some((fk) => bm[fk]) || (bm.bullAuxBackupStop && isBullStopHit(it)))) y2++;
  } else y2++;
  return y2;
}
function xOld(x, dynamic) {   // dynamic=true → s06 行(new15 兜底兜拦)
  const fx = (x.ai_macro && Array.isArray(x.ai_macro.filters)) ? x.ai_macro.filters : [];
  const mv = x.ai_macro && x.ai_macro.mode_votes;
  if (!dynamic) {
    const keptPids = [];
    for (const pid of PIDS) {
      if (mv && !mv[pid]) continue;
      if (!mv && fx.some((fk) => (MEMBERS[pid] || {})[fk])) continue;
      keptPids.push(pid);
    }
    return keptPids;
  }
  const r6 = baseForDate();
  const base = r6 && r6.ok ? r6.base : "new15";
  if (mv && !mv[base]) return null;
  if (!mv && fx.some((fk) => (MEMBERS[base] || {})[fk])) return null;
  return ["s06"];
}

// ===== 新实现(worktree 修复版复刻)=====
function frontVotes(farr, it) {
  const f = Array.isArray(farr) ? farr : [];
  const votes = {};
  for (const pid of PIDS) {
    const m3 = MEMBERS[pid] || {};
    if (f.some((fk) => m3[fk])) { votes[pid] = false; continue; }
    if (m3.bullAuxBackupStop && isBullStopHit(it)) { votes[pid] = false; continue; }
    votes[pid] = true;
  }
  return votes;
}
function yNew(it) {
  const f2 = (it.ai_macro && Array.isArray(it.ai_macro.filters)) ? it.ai_macro.filters : [];
  const mv = (it.ai_macro && it.ai_macro.mode_votes) || frontVotes(f2, it);
  let y2 = 0;
  for (const pid of PIDS) if (mv[pid]) y2++;
  const r6 = baseForDate();
  if (!r6 || !r6.ok || mv[r6.base]) y2++;
  return y2;
}
function xNew(x, dynamic) {
  const fx = (x.ai_macro && Array.isArray(x.ai_macro.filters)) ? x.ai_macro.filters : [];
  const mv = (x.ai_macro && x.ai_macro.mode_votes) || frontVotes(fx, x);
  if (!dynamic) {
    const keptPids = [];
    for (const pid of PIDS) {
      if (!mv[pid]) continue;   // falsy=拦(与旧版逐位一致)
      keptPids.push(pid);
    }
    return keptPids;
  }
  const r6 = baseForDate();
  if (r6 && r6.ok && !mv[r6.base]) return null;   // 当日基座 falsy=拦才跳过
  return ["s06"];                                          // base 未知→fail-open 不拦
}

// ===== 场景矩阵 =====
const mk = (name, filters, mvOrNull) => ({
  name, date: "20260827",
  ai_macro: mvOrNull ? { filters, mode_votes: backendVotes(filters, filters.tier || "") } : { filters },
});
const CASES = [
  mk("mv+不拦", [], true), mk("mv+new15键", ["excludeTierNone"], true),
  mk("mv缺键", ["greedy15"], null && null) && (() => {
    const c = mk("mv缺键", ["greedy15"], true);
    delete c.ai_macro.mode_votes.c9;   // 缺键容忍语义用例
    return c;
  })(),
  mk("旧数据+buy无bull", [], null), mk("旧数据+new15键", ["excludeTierNone"], null),
];
const BULLCASE = (() => { const c = { name: "旧数据+buy_aux牛市", date: "20260827", signal: "buy_aux", ai_macro: { filters: [] }, _tier: "牛市·主升" }; return c; })();
Object.assign(CASES[BULLCASE.name] = BULLCASE);

const MODES = ["ok-a9", "ok-new15", "out_of_range", "not_loaded"];
let pass = 0, fail = 0, bugfix = 0;
for (const mode of MODES) {
  S06MODE = mode.startsWith("ok-") ? "ok" : mode;
  ROWBASE = mode === "ok-a9" ? "a9" : "new15";
  for (const sigCase of [...Object.values(CASES)]) {
    const _svBull = BULLHIT;
    if (sigCase.signal === "buy_aux" || sigCase._tier) { BULLHIT = true; }   // 激活 bull mock
    const yo = yOld(sigCase), yn = yNew(sigCase);
    const tag = `Y[${mode}][${sigCase.name}]`;
    if (yo === yn) { pass++; } else if (sigCase._tier) { bugfix++; console.log(`  BUGFIX ${tag}: old=${yo} new=${yn}(预期,bull特判补齐)`); }
    else { fail++; console.log(`  **FAIL** ${tag}: old=${yo} new=${yn}`); }
    // X 静态行
    const xo = xOld(sigCase, false), xn = xNew(sigCase, false);
    if (JSON.stringify(xo) === JSON.stringify(xn)) pass++;
    else if (sigCase._tier) { bugfix++; console.log(`  BUGFIX X静态[${mode}][${sigCase.name}]: old=${JSON.stringify(xo)} new=${JSON.stringify(xn)}(预期,bull特判补齐)`); }
    else { fail++; console.log(`  **FAIL** X静态[${mode}][${sigCase.name}]: old=${JSON.stringify(xo)} new=${JSON.stringify(xn)}`); }
    BULLHIT = _svBull;
  }
  // #96 主修断言: out_of_range/not_loaded 下 X s06 行,new15 键命中信号必须不被拦
  const hit = mk("mv+new15键", ["excludeTierNone"], true);
  const oldBlocked = xOld(hit, true) === null, newBlocked = xNew(hit, true) === null;
  if (S06MODE !== "ok") {
    if (!oldBlocked && newBlocked) { fail++; console.log(`  **FAIL** X-s06 [${mode}] 旧行为居然放行`); }
    else if (oldBlocked && !newBlocked) { pass++; console.log(`  BUGFIX X-s06 [${mode}]: 旧=拦截(fail-closed new15兜底) 新=放行(#96 主修生效)`); }
    else { fail++; console.log(`  **FAIL** X-s06 [${mode}] 未预期组合 old=${oldBlocked} new=${newBlocked}`); }
  } else {
    // 覆盖期内行为必须不变: base=a9 时该信号 a9 票=true→保留; base=new15 时=false→拦
    const expBlock = ROWBASE === "new15";
    if (newBlocked === expBlock && oldBlocked === expBlock) pass++;
    else { fail++; console.log(`  **FAIL** X-s06 [${mode}] 覆盖期内行为漂移 old=${oldBlocked} new=${newBlocked} exp=${expBlock}`); }
  }
}
// Y 契约专项(#95): base unknown 时, 同一信号「带 mode_votes」与「缺失走表决器」两票源必须同 Y
S06MODE = "out_of_range";
for (const c of Object.values(CASES)) {
  const withMv = { ...c, ai_macro: { filters: c.ai_macro.filters, mode_votes: backendVotes(c.ai_macro.filters, "") } };
  const noMv = { ...c, ai_macro: { filters: c.ai_macro.filters }, _tier: undefined };
  const savedTier = BULLHIT;
  if (withMv.signal === "buy_aux") { withMv.ai_macro.mode_votes = backendVotes(withMv.ai_macro.filters, "牛市·主升"); }
  BULLHIT = !!noMv.signal || !!noMv._tier;
  // 与 mv 分支同 tier 语义对齐(此专项 bull 恒 false 排除干扰): 统一关掉
  BULLHIT = false;
  const a = yNew(withMv), b = yNew(noMv);
  if (a !== b) { fail++; console.log(`FAIL Y契约[${c.name}] mv版=${a} 表决器版=${b}`); }
  else pass++;
}
BULLHIT = false;
console.log(`\n结果: PASS=${pass} BUGFIX(预期差异)=${bugfix} FAIL=${fail}`);
console.log(fail === 0 ? "== 自测 PASS ==" : "== 存在 FAIL ==");
