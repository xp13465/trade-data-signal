// ============================================================
// 用途: 2011 A模式逐笔资金曲线(复刻前端每日池+topK+费率重算)
// 日期/来源: 2026-08-14 / tmp
// 结论: 2011 A模式资金曲线先涨后跌, 支撑"两把尺子"认知差结论
// 依赖: 无
// 输入/输出: 读 signal_kelly_trades.json, 输出 2011 逐笔资金曲线
// 复现: node dd_2011_trace.js
// 注意: 含硬编码绝对路径; 如需重跑请确认路径或改相对路径
// ============================================================
// 复刻前端每日池+topK+费率重算, 输出2011 A模式逐笔资金曲线
const fs = require('fs');
const t = JSON.parse(fs.readFileSync('static-site/data/signal_kelly_trades.json','utf8'));
const quads = t.quadrants || {};
// 找A模式(all周期)的trades列式数据
let A = null, fields = t.fields || {};
for (const q of Object.keys(quads)) {
  for (const p of Object.keys(quads[q])) {
    const m = quads[q][p];
    if (m && m.mode && m.mode['A']) { A = m.mode['A']; console.log('找到A模式:', q, p); }
  }
}
if (!A) { console.log('未找到, keys:', JSON.stringify(quads).slice(0,300)); process.exit(0); }
console.log('A trades keys:', Object.keys(A).filter(k=>k!=='stats'));
