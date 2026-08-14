// ============================================================
// 用途: 按年回撤复算(演进版1/中间版, 以最新 kelly_yearly_dd3.js 为准)
// 日期/来源: 2026-08-14 / tmp
// 结论: 2011 A模式峰值→谷底回撤 14.01% (最终确认见 dd3)
// 依赖: 无
// 输入/输出: 读 signal_kelly_trades.json(绝对路径), 输出按年回撤
// 复现: node kelly_yearly_dd.js
// 注意: 演进版本, 以 kelly_yearly_dd3.js 为最终版; 含硬编码绝对路径
// ============================================================
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json', 'utf8'));
const F = data.fields;
const fIdx = {}; F.forEach((f, i) => fIdx[f] = i);
const quads = data.quadrants;
const KELLY_ORIG_SLIPPAGE = 0.001;
const FEE_DEF  = { commission_rate: 0.0003,  min_commission: 5,   slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };
function isShEtf(code){return code? (code.startsWith("51")||code.startsWith("58")):false;}
function recomputeTrade(t, fp, buyAmount) {
  const bp=t[fIdx.buy_price]||0, sp=t[fIdx.sell_price]||0, cp=t[fIdx.current_price]||0, ec=t[fIdx.etf_code]||"", sellDate=t[fIdx.sell_date]||"";
  if(bp<=0)return{profit:0};
  const closeBuy=bp/(1+KELLY_ORIG_SLIPPAGE);
  const closeSell=sellDate?(sp/(1-KELLY_ORIG_SLIPPAGE)):cp;
  const c=fp.commission_rate,s=fp.slippage,minC=fp.min_commission;
  const sh=isShEtf(ec)?fp.transfer_fee_rate_sh:0, stamp=fp.stamp_duty_rate;
  const buyPriceNew=closeBuy*(1+s);
  if(buyPriceNew<=0)return{profit:0};
  let sharesNew=buyAmount/(buyPriceNew*(1+c+sh));
  let grossNew=sharesNew*buyPriceNew; let commBuy=grossNew*c;
  if(commBuy<minC){sharesNew=(buyAmount-minC)/(buyPriceNew*(1+sh));grossNew=sharesNew*buyPriceNew;commBuy=minC;}
  const sellPriceNew=closeSell*(1-s);
  const sellAmountNew=sharesNew*sellPriceNew;
  const netNew=sellAmountNew-Math.max(sellAmountNew*c,minC)-sellAmountNew*sh-sellAmountNew*stamp;
  return{profit:Math.round((netNew-buyAmount)*10000)/10000};
}
function maxDD(trades){ // 按卖出日期序累计净盈亏峰谷差
  if(!trades.length)return{abs:0};
  const sorted=trades.slice().sort((a,b)=>{const da=a.sell_date||"99999999",db=b.sell_date||"99999999";return da<db?-1:da>db?1:0;});
  let cum=0,peak=0,maxDdAbs=0;
  for(const t of sorted){cum+=t.profit;if(cum>peak)peak=cum;const dd=peak-cum;if(dd>maxDdAbs)maxDdAbs=dd;}
  return{abs:Math.round(maxDdAbs*10000)/10000};
}
function maxConcCap(trades){
  if(!trades.length)return 0;
  const S="99999999",deltas={},dates=[];
  for(const t of trades){const bd=t.buy_date,sd=t.sell_date||S,amt=t.amount||0;
    if(!deltas[bd]){deltas[bd]={b:0,s:0};dates.push(bd);}deltas[bd].b+=amt;
    if(!deltas[sd]){deltas[sd]={b:0,s:0};dates.push(sd);}deltas[sd].s+=amt;}
  dates.sort();let cur=0,maxC=0;
  for(const d of dates){cur-=deltas[d].s;cur+=deltas[d].b;if(cur>maxC)maxC=cur;}
  return Math.round(maxC*10000)/10000;
}
// Reuse filtered G-mode trades: load same pipeline via re-running simplified default filter (AI宏7键 + K=1), only A mode
// (reuse the exact same approach as prior script by requiring the generated pool)
const { execSync } = require('child_process');
// Instead: recompute quickly using prior saved intermediate — just recompute here minimal: filter only, no position cap detail reuse from prior run
// To keep it correct, re-derive kept keys by importing prior script output is complex; approximate with a direct approach:
// Re-run the full pipeline via the previous script pattern (copy of filter logic) — skip, instead load from a precomputed kept set:
