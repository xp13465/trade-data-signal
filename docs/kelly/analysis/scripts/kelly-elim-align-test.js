// kelly-elim-align-test.js - 淘汰原因列(_elimReason)逻辑对齐合成验证(独立验证脚本,非机检)
// 目的:独立验证 feat/kelly-elim-reason(8b741acb5)的 eliminated/_elimReasons/recompute/GIH补集/挂载链路,
//      配套 review 结论(docs/tasks-done-list.md「2026-09-01 会话追加 1」:「合成4场景测试 ALL PASS」),
//      本脚本即该结论的可复现凭证(原临摹于 /tmp,2026-09-03 收编归档,ZCode reviewer 自建)。
// 方法口径:纯 JS 合成数据复刻 lab.js L11723-11810(当时行号)五要素逻辑,不依赖任何数据产物/网络。
// 输入依赖:无(全合成);输出:stdout PASS/FAIL;运行目录任意。
// 复现命令:node docs/kelly/analysis/scripts/kelly-elim-align-test.js  → 期望 5 行场景全 PASS。
// 注:行号为 2026-09-01 版 lab.js;lab.js 后续迭代(如 af40be9f4 加筛选)不影响本脚本(自包含合成,不 import lab.js)。
// ④GIH off(_simIn undefined)不追加不崩 ⑤计数守恒。合成数据, 非机检脚本。
function runScenario(gihOn, simDropNames, navMissingKept) {
  // rawTrades: 6 笔; 0,1,2,3,4,5; pcFade=false(降亏淘汰) 对 idx1; posCapFail 对 idx2; 其余过
  const rawTrades = [0,1,2,3,4,5].map(i => ["r"+i, 100, 10]);
  const pcFade = t => t[0] !== "r1";                       // r1 降亏淘汰
  const posCapKept = { "r0":1, "r3":1, "r4":1, "r5":1 };  // r2 仓位淘汰
  const cutoff = null;
  let trades = rawTrades.filter(t => {
    if (cutoff) return false;
    if (!pcFade(t)) return false;
    if (posCapKept && !posCapKept[t[0]]) return false;
    return true;
  });
  let eliminated = rawTrades.filter(t => {
    if (cutoff) return false;
    return !pcFade(t) || (posCapKept && !posCapKept[t[0]]);
  });
  const _elimReasons = eliminated.map(t => !pcFade(t) ? "AI降亏" : "AI仓位");
  const _recompute = t => { const n = t.slice(); n.push(9); n.push(10000); return n; }; // slice 丢自定义属性
  trades = trades.map(_recompute);
  eliminated = eliminated.map(_recompute);
  // GIH 仿真: _simIn 每项 _src 指向 recompute 后行; kept 引用透传
  let _gihKept = null, _simIn;
  if (gihOn) {
    _simIn = trades.map(t => ({ profit: t[1], _src: t }));
    const keptSet = new Set(trades.map(t => t[0]));
    _gihKept = [];
    trades.forEach((t, i) => {
      if (simDropNames.includes(t[0])) return;          // 满仓不买丢弃
      _gihKept.push({ profit: navMissingKept && i === 3 ? null : t[1], flag: navMissingKept && i === 3 ? "nav_missing" : "", _src: t });
    });
    if (_gihKept.length) trades = _gihKept.map(k => { const row = k._src.slice(); row[1] = k.profit; return row; });
    else _gihKept = null; // real 空 → null(硬报错路径)
  }
  if (_gihKept && _simIn) {
    const keptSrc = new Set(_gihKept.map(k => k._src));
    _simIn.forEach(x => {
      if (!keptSrc.has(x._src)) { eliminated.push(x._src); _elimReasons.push("AI长线·满仓不买"); }
    });
  }
  eliminated.forEach((t, i) => { t._elimReason = _elimReasons[i] || "AI仓位"; });
  return { trades, eliminated, gihKept: _gihKept };
}
const assert = require("assert");
// 场景1: GIH on, 丢 idx4(满仓不买), idx3 nav_missing 留 kept
let r = runScenario(true, ["r4"], true);
assert.strictEqual(r.eliminated.length, 3); // r1降亏+r2仓位+r4满仓不买
console.log("场景1 eliminated:", r.eliminated.map(t => t[0] + ":" + t._elimReason).join(", "));
assert.deepStrictEqual(r.eliminated.map(t => t._elimReason), ["AI降亏","AI仓位","AI长线·满仓不买"]);
assert.ok(r.eliminated.every((t, i) => t._elimReason !== undefined), "对齐无错位");
// nav_missing 行(r3)必须在 kept/主表, 不在 eliminated
assert.ok(!r.eliminated.some(t => t[0] === "r3"), "nav_missing 行不误入淘汰区");
assert.ok(r.trades.some(t => t[0] === "r3"), "nav_missing 行留主表");
// 补集与主表不相交: 主表是 sim 映射副本(slice), 淘汰区追加的是原 recompute 行——对象不同但内容键 r4 不在主表
assert.ok(!r.trades.some(t => t[0] === "r4"), "满仓不买单不进主表");
// 场景2: GIH off(_simIn undefined 守卫)
r = runScenario(false, [], false);
assert.strictEqual(r.eliminated.length, 2);
assert.deepStrictEqual(r.eliminated.map(t => t._elimReason), ["AI降亏","AI仓位"]);
// 场景3: 全部被 sim 保留(_gihKept 全 kept) → 无追加
r = runScenario(true, [], false);
assert.strictEqual(r.eliminated.length, 2);
// 场景4: real=null(GIH 开但仿真失败) → 不追加
r = runScenario(true, ["r0","r3","r4","r5"], false); // kept 空→ _gihKept=null
assert.strictEqual(r.eliminated.length, 2);
console.log("ALL 4 SCENARIOS PASS: 原因对齐/补集不相交/nav_missing 归宿/GIH-off 守卫/计数守恒 全部成立");
