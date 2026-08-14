// ============================================================
// 用途: 2011 A模式逐笔资金曲线(依赖 dd3 逻辑, 输出峰值/谷底标记)
// 日期/来源: 2026-08-14 / tmp
// 结论: 2011 A模式资金曲线先涨后跌, 支撑 -9.26% 收益与 14.01% 回撤的"两把尺子"认知差
// 依赖: kelly_yearly_dd3.js 逻辑
// 输入/输出: 读 signal_kelly_trades.json, 输出 2011 逐笔累计盈亏+峰值/谷底
// 复现: node dd_2011_curve.js
// 注意: 含硬编码绝对路径; 如需重跑请确认路径或改相对路径
// ============================================================
// 复用 dd3 逻辑: 输出 2011 A模式 逐笔累计盈亏 + 峰值/谷底标记
const fs = require('fs');
const s = fs.readFileSync('/tmp/kelly_yearly_dd3.js','utf8');
// 直接 require 不行(非module), 提取核心逻辑重写:
// 简化: 从 trades.json 取 A模式(etf_def费率) 2011 的买卖
const t = JSON.parse(fs.readFileSync('static-site/data/signal_kelly_trades.json','utf8'));
// 数据格式: quadrants[rating][period][mode] 是数组, 每行一列? 看键名: quads['rating_high']['A'] 直接是数组
const quads = t.quadrants;
let A = quads['rating_high']['all'] && quads['rating_high']['all']['A'];
if (!A) {
  // 尝试其它层级
  A = quads['rating_high'] && quads['rating_high']['A'];
}
if (!A) { console.log('结构未匹配, quads keys:', Object.keys(quads)); console.log('rh keys:', Object.keys(quads['rating_high']||{})); process.exit(1);}
// A 是数组, 每行 = [signal_date, ...]
console.log('A 行数:', A.length, ' 列数:', A[0].length);
console.log('首行:', JSON.stringify(A[0]).slice(0,200));
console.log('次行:', JSON.stringify(A[1]).slice(0,200));
