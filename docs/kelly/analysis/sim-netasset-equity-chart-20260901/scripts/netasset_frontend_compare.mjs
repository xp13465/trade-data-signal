#!/usr/bin/env node
// 净资产走势图·前端实现提取与跑数(2026-09-04 #51 实施自测配套, 与 netasset_frontend_compare.py 咬合)
// 目的: 从 static-site/app.js 源码 vm 提取线上真实三个函数(_simBuyWithFees/_simSellWithFees/_simNetassetCurve),
//       喂与 Python 权威复刻相同的 kept rows + initCapital + accum_nav_map, 输出逐日曲线供逐位对账。
// 用法: node netasset_frontend_compare.mjs <kept.json> <accum_nav_map.json> <out.json> <app.js>
import fs from 'fs';
import vm from 'vm';

const [keptF, navF, outF, appF] = process.argv.slice(2);
const src = fs.readFileSync(appF || '/Users/linhuichen/code/trade/static-site/app.js', 'utf8');

function extractFunc(name) {
  const re = new RegExp('function\\s+' + name + '\\s*\\(', 'i');
  const m = re.exec(src);
  if (!m) throw new Error('function not found: ' + name);
  const start = m.index;
  const openParen = src.indexOf('(', start);
  const openBrace = src.indexOf('{', openParen);
  let depth = 0;
  for (let i = openBrace; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error('unbalanced braces: ' + name);
}

const code = ['_simBuyWithFees', '_simSellWithFees', '_simNetassetCurve']
  .map(extractFunc)
  .join('\n') +
  '\n;globalThis.__X = { _simBuyWithFees, _simSellWithFees, _simNetassetCurve };';
const sandbox = { console };
vm.createContext(sandbox);
vm.runInContext(code, sandbox);
sandbox.__X = sandbox.__X || sandbox.globalThis.__X;

const kept = JSON.parse(fs.readFileSync(keptF, 'utf8'));
const nav = JSON.parse(fs.readFileSync(navF, 'utf8'));
const t0 = Date.now();
const { curve, navFF } = sandbox.__X._simNetassetCurve(kept.rows, kept.fIdx, kept.fp, kept.initCapital, nav);
fs.writeFileSync(outF, JSON.stringify({ curve, navFF, ms: Date.now() - t0 }, null, 1));
console.log('js curve points=' + curve.length + ' navFF=' + navFF + ' last=' + JSON.stringify(curve[curve.length - 1]) + ' ms=' + (Date.now() - t0));