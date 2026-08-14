// ============================================================
// 用途: 最终核验(kelly-4combo-a45-backtest 输出的 pool vs fixed 全模式最终核对)
// 日期/来源: 2026-08-12 / tmp
// 结论: 4组合+a45 最终核验结果, 支撑组合结论
// 依赖: kelly-4combo-a45-backtest.js 输出 /tmp/kelly-4combo-a45-backtest.json
// 输入/输出: 读 /tmp/kelly-4combo-a45-backtest.json, 输出最终核验
// 复现: node kelly-final-check.js
// 注意: 原文件硬编码读 /tmp/kelly-4combo-a45-backtest.json, 需先运行 4combo 脚本
// ============================================================
const fs = require("fs");
const out = JSON.parse(fs.readFileSync("/tmp/kelly-4combo-a45-backtest.json", "utf8"));
const P = out.runs.pool, F = out.runs.fixed;
const MODES = ["A","B","C","D","E","F","G","H","I"];
// 1. 用户所见 B_full y1/all 全模式
console.log("=== 用户所见 B_full (pool) ===");
for (const p of ["y1","all"]) {
  const neg = MODES.filter(m=>P.B_full.all[p][m].total_profit<0);
  console.log("  "+p+": 负模式="+(neg.length?neg.join(","):"无(全9模式正向)"), " G="+Math.round(P.B_full.all[p].G.total_profit)+"元 rmh="+P.B_full.all[p].G.return_pct_max_holding.toFixed(2)+"%");
}
// 2. 关poscap后 4宏+A45
console.log("\n=== 关poscap: 4宏+A45 (B_combo4_a45, pool all) 负模式 ===");
console.log("  负模式:", MODES.filter(m=>P.B_combo4_a45.all.all[m].total_profit<0).join(","));
console.log("=== 默认推荐 C (pool) ===");
console.log("  y1 负模式:", MODES.filter(m=>P.C_defaultRec.all.y1[m].total_profit<0).join(",")||"无", "| all 负模式:", MODES.filter(m=>P.C_defaultRec.all.all[m].total_profit<0).join(",")||"无");
// 3. A45 用户上下文边际(两口径)
console.log("\n=== A45 用户上下文边际 G 模式 (B_full - A_combo4_poscap_sb_a5) ===");
for (const am of ["pool","fixed"]) {
  const r = out.runs[am];
  const a=r.B_full.all.all.G, b=r.A_combo4_poscap_sb_a5.all.all.G;
  console.log("  "+am+": d_profit="+(a.total_profit-b.total_profit).toFixed(0)+"元 d_rmh="+(a.return_pct_max_holding-b.return_pct_max_holding).toFixed(3)+"pp d_n="+(a.n-b.n)+" (y1 d_n="+(r.B_full.all.y1.G.n-r.A_combo4_poscap_sb_a5.all.y1.G.n)+")");
}
// 4. COMBO4 全开警告
console.log("\n=== COMBO4 全开警告核查 (G all, pool) ===");
console.log("  C_defaultRec: rmh="+P.C_defaultRec.all.all.G.return_pct_max_holding.toFixed(2)+"% profit="+Math.round(P.C_defaultRec.all.all.G.total_profit));
console.log("  B_full:       rmh="+P.B_full.all.all.G.return_pct_max_holding.toFixed(2)+"% profit="+Math.round(P.B_full.all.all.G.total_profit));
console.log("  Δrmh="+(P.B_full.all.all.G.return_pct_max_holding-P.C_defaultRec.all.all.G.return_pct_max_holding).toFixed(2)+"pp, Δprofit="+Math.round(P.B_full.all.all.G.total_profit-P.C_defaultRec.all.all.G.total_profit)+"元");
console.log("  greedy15 单独: T_def_mlc rmh="+P.T_def_mlc.all.all.G.return_pct_max_holding.toFixed(2)+"% profit="+Math.round(P.T_def_mlc.all.all.G.total_profit));
// 5. 1月调整边际
console.log("\n=== 默认推荐+1月调整(T_def_ja) vs 默认推荐(C) ===");
const jaSum={profit:0};
for (const m of MODES){const a=P.T_def_ja.all.all[m],b=P.C_defaultRec.all.all[m];jaSum[m]={d_profit:Math.round(a.total_profit-b.total_profit),d_rmh:+(a.return_pct_max_holding-b.return_pct_max_holding).toFixed(2)};jaSum.profit+=a.total_profit-b.total_profit;}
console.log("  G: d_profit=+"+jaSum.G.d_profit+"元 d_rmh=+"+jaSum.G.d_rmh+"pp | 9模式合计Δprofit=+"+Math.round(jaSum.profit)+"元");
console.log("  y1 G: d_profit=+"+Math.round(P.T_def_ja.all.y1.G.total_profit-P.C_defaultRec.all.y1.G.total_profit)+"元");
// 6. 固定口径关键结论一致
console.log("\n=== fixed 口径关键结论一致 ===");
console.log("  B_full fixed y1 负模式:", MODES.filter(m=>F.B_full.all.y1[m].total_profit<0).join(",")||"无", "| all 负模式:", MODES.filter(m=>F.B_full.all.all[m].total_profit<0).join(",")||"无");
console.log("  B_combo4_a45 fixed all 负模式:", MODES.filter(m=>F.B_combo4_a45.all.all[m].total_profit<0).join(","));
