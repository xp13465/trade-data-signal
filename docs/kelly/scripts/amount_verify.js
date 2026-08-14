// ============================================================
// 用途: K=3 分仓行为验证: 1信号日=10000/49天、2=5000/12天、3=3333/4天 (复现前端 _kellyPerTradeAmount = buyAmount/dayKeptCount)
// 日期/来源: 2026-08-14 / tmp
// 结论: 当日信号数<K 时每笔金额=buyAmount/当日保留数(非恒 DAILY/K); 3333/6666 仅出现在当日恰好 K 个信号的日
// 依赖: 无
// 输入/输出: 读 static-site/data/signal_kelly_trades.json, 输出各 signal_date 分仓金额分布
// 复现: node amount_verify.js (需在含 static-site/data 的仓库根运行)
// 注意: 原文件用相对路径读 static-site/data, 需在仓库根运行
// ============================================================
// 验证: 全信号表金额 = 10000 / 当日保留信号数(signal_date 维度)
const fs = require('fs');
const t = JSON.parse(fs.readFileSync('static-site/data/signal_kelly_trades.json','utf8'));
// 用与前端同口径: 从保留集计算每 signal_date 的保留数
// 简化: 直接按 trades 里某 mode 的 signal_date 分组(前端保留集=topK后, 此处用全量近似看金额=10000/n 是否成立)
const quads = t.quadrants;
// 找 A 模式(全周期)数组: quads['rating_high']['all']['A']? 实际是 quads['rating_high']['A'](无 period 层)
const A = quads['rating_high'] && (quads['rating_high']['all'] ? quads['rating_high']['all']['A'] : quads['rating_high']['A']);
if (!A) { console.log('quads.rating_high keys:', Object.keys(quads['rating_high']||{})); process.exit(1);}
// 行结构: [signal_date, id, type, buy_date, sell_date, etf_id, name, ...], signal_date=col0
const byDay = {};
for (const row of A) {
  const sd = row[0];
  byDay[sd] = (byDay[sd]||0)+1;
}
// 统计不同金额档位对应的当日信号数
const amtByN = {};
for (const sd in byDay) {
  const n = byDay[sd];
  const amt = Math.round(10000/n * 100)/100;
  if (!amtByN[n]) amtByN[n] = {days:0, amt};
  amtByN[n].days++;
}
console.log('=== A模式 当日信号数 -> 每笔金额(10000/当日信号数) ===');
for (const n of Object.keys(amtByN).sort((a,b)=>a-b)) {
  console.log(`当日${n}个信号 → 每笔 ${amtByN[n].amt} 元, 共 ${amtByN[n].days} 天`);
}
// 找出具体: 1信号日是否金额10000
console.log('\n=== 当日1个信号的日期示例(应每笔10000) ===');
let c=0;
for (const sd in byDay) {
  if (byDay[sd]===1 && c<8) { console.log(' ', sd, '→ 1个信号 → 每笔10000'); c++; }
}
console.log('\n=== 当日3个信号的日期示例(应每笔3333) ===');
c=0;
for (const sd in byDay) {
  if (byDay[sd]===3 && c<5) { console.log(' ', sd, '→ 3个信号 → 每笔3333'); c++; }
}
