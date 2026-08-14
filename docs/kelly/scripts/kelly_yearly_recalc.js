// ============================================================
// 用途: 认知差复算: 按年表 -9.26% 来源(etf_main 费率 A 模式 2011 单年收益率)
// 日期/来源: 2026-08-14 / tmp
// 结论: -9.26% = 2011 年 A 模式全年最终净收益率(净利/峰值资金), 非年内回撤
// 依赖: 无
// 输入/输出: 读 /Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json, 输出按年收益率
// 复现: node kelly_yearly_recalc.js
// 注意: 原文件用绝对路径读 trades.json, 如需重跑请确认路径或改相对路径
// ============================================================
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json', 'utf8'));
const F = data.fields;
const fIdx = {};
F.forEach((f, i) => fIdx[f] = i);
const quads = data.quadrants;

// constants
const KELLY_ORIG_SLIPPAGE = 0.001;
const SELL_MODES = data.quadrants.rating_high && Object.keys(data.quadrants.rating_high);
// fee params: try etf_main then etf_def
const FEE_MAIN = { commission_rate: 0.00005, min_commission: 0.1, slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };
const FEE_DEF  = { commission_rate: 0.0003,  min_commission: 5,   slippage: 0.001, transfer_fee_rate_sh: 0.00001, stamp_duty_rate: 0 };

function isShEtf(code) { return !code ? false : (code.startsWith("51") || code.startsWith("58")); }
function recomputeTrade(t, fp, buyAmount) {
  const bp = t[fIdx.buy_price] || 0, sp = t[fIdx.sell_price] || 0, cp = t[fIdx.current_price] || 0;
  const ec = t[fIdx.etf_code] || "", sellDate = t[fIdx.sell_date] || "";
  if (bp <= 0) return { profit: 0, return_pct: 0, fee_cost: 0 };
  const closeBuy = bp / (1 + KELLY_ORIG_SLIPPAGE);
  const closeSell = sellDate ? (sp / (1 - KELLY_ORIG_SLIPPAGE)) : cp;
  const c = fp.commission_rate, s = fp.slippage, minC = fp.min_commission;
  const sh = isShEtf(ec) ? fp.transfer_fee_rate_sh : 0;
  const stamp = fp.stamp_duty_rate;
  const buyPriceNew = closeBuy * (1 + s);
  if (buyPriceNew <= 0) return { profit: 0, return_pct: 0, fee_cost: 0 };
  let sharesNew = buyAmount / (buyPriceNew * (1 + c + sh));
  let grossNew = sharesNew * buyPriceNew;
  let commBuy = grossNew * c;
  if (commBuy < minC) { sharesNew = (buyAmount - minC) / (buyPriceNew * (1 + sh)); grossNew = sharesNew * buyPriceNew; commBuy = minC; }
  const sellPriceNew = closeSell * (1 - s);
  const sellAmountNew = sharesNew * sellPriceNew;
  const commSell = Math.max(sellAmountNew * c, minC);
  const transferFeeSell = sellAmountNew * sh;
  const stampDuty = sellAmountNew * stamp;
  const netNew = sellAmountNew - commSell - transferFeeSell - stampDuty;
  const profitNew = netNew - buyAmount;
  const shares0 = buyAmount / closeBuy;
  const profit0 = shares0 * closeSell - buyAmount;
  return { profit: Math.round(profitNew * 10000) / 10000, return_pct: Math.round(profitNew / buyAmount * 100 * 10000) / 10000, fee_cost: Math.round((profit0 - profitNew) * 10000) / 10000 };
}
function baseKey(t) { return [t[fIdx.signal_date], t[fIdx.index_id], t[fIdx.signal], t[fIdx.buy_date], t[fIdx.etf_code]].join("|"); }
function buyWeekday(bd) {
  const y = parseInt(bd.substring(0,4),10), m = parseInt(bd.substring(4,6),10), d = parseInt(bd.substring(6,8),10);
  const jsDay = new Date(y, m-1, d).getDay();
  return (jsDay + 6) % 7;
}
function buypriceBin(p) { if (p==null) return ""; if (p<=0.841441) return "vlow"; if (p<=1.015314) return "low"; if (p<=1.194593) return "mid"; if (p<=1.446645) return "high"; return "vhigh"; }
function buildTradeDims(td) {
  const dims = {};
  for (const qk in td.quadrants) {
    const parts = qk.split('_');
    const dimType = parts[0];
    const dimVal = parts.slice(1).join('_');
    for (const mk in td.quadrants[qk]) {
      for (const t of td.quadrants[qk][mk]) {
        const key = [t[fIdx.signal_date], t[fIdx.index_id], t[fIdx.signal], t[fIdx.buy_date], t[fIdx.etf_code], t[fIdx.sell_date]].join("|");
        if (!dims[key]) dims[key] = {};
        dims[key][dimType] = dimVal;
      }
    }
  }
  return dims;
}
const _dims = buildTradeDims(data);

// default filters (AI宏7键)
const filters = {
  a5NovMidSpecial:false,a45NovMidLateSpecial:false,n1MarTueHigh:false,n2NovSpecialIndustry:true,r8PureNonMay:false,
  n3NovSpecialMon:false,n4AMay:false,r7MayReinforced:true,n5MayVlow:false,n6MidMay:false,r10May6NonMay:false,
  excludeAuxCross:true,excludeSpecialBear:true,excludeMonth:false,excludeAux:false,marketTiming:false,excludeRatingLow:false,
  greedy7:false,v4cSimple:false,v4b:false,greedy10:false,v4d:false,v4j:false,v4i:false,
  greedy15:true,v4f:false,v4g:false,v4m:false,v4k:false,janMidRating:true,janMidSpecial:true,positionCap:true,positionCapK:1
};
const MONTH_MASK = {
  n2NovSpecialIndustry:1<<10, r7MayReinforced:(1<<4)|(1<<2)|(1<<10), greedy15:(1<<0)|(1<<1)|(1<<2)|(1<<3)|(1<<4)|(1<<5)|(1<<8)|(1<<10)|(1<<11),
  excludeAuxCross:0, excludeSpecialBear:0, janMidRating:1<<0, janMidSpecial:1<<0
};
let mask = 0;
for (const k in MONTH_MASK) if (filters[k]) mask |= MONTH_MASK[k];

function tradeFeatures(t) {
  const bd = String(t[fIdx.buy_date] || "");
  const mm = bd.substring(4,6), dd = parseInt(bd.substring(6,8),10) || 0;
  const sig = String(t[fIdx.signal] || "");
  const wd = buyWeekday(bd);
  const bpb = buypriceBin(t[fIdx.buy_price]);
  const dk = [t[fIdx.signal_date],t[fIdx.index_id],sig,bd,t[fIdx.etf_code],t[fIdx.sell_date]].join("|");
  const dims = _dims[dk] || {};
  const mktD = dims.mkt || "", ratD = dims.rating || "";
  const ts = t[fIdx.track_score] != null ? Number(t[fIdx.track_score]) : 999;
  const etfD = String(t[fIdx.track_tier] || "");
  const q = mm ? Math.ceil(parseInt(mm,10)/3) : 0;
  return { mm, dd, sig, wd, bpb, mktD, ratD, ts, etfD, q };
}
const featCache = new Map();
function passesFade(t) {
  if (filters.excludeAux && (t[fIdx.signal]||"")==="buy_aux") return false;
  if (filters.marketTiming && t[fIdx.market_state] !== true) return false;
  if (filters.excludeMonth) { const m=(t[fIdx.buy_date]||"").substring(4,6); if (m==="03"||m==="05") return false; }
  if (filters.excludeRatingLow && t[fIdx.rating]==="low") return false;
  if (filters.excludeAuxCross && (t[fIdx.signal]||"")==="buy_aux") { const m=(t[fIdx.buy_date]||"").substring(4,6); if (m==="03"||m==="05") return false; }
  if (filters.excludeSpecialBear && (t[fIdx.signal]||"")==="buy_special" && t[fIdx.market_state]===false) return false;
  const v3On = filters.n1MarTueHigh||filters.n2NovSpecialIndustry||filters.r8PureNonMay||filters.n3NovSpecialMon||filters.n4AMay||filters.r7MayReinforced||filters.n5MayVlow||filters.n6MidMay||filters.r10May6NonMay;
  const v4On = filters.greedy7||filters.greedy10||filters.greedy15||filters.v4cSimple||filters.v4b||filters.v4d||filters.v4j||filters.v4i||filters.v4f||filters.v4g||filters.v4m||filters.v4k;
  const janOn = filters.janMidRating||filters.janMidSpecial;
  if (v3On || v4On || janOn) {
    const mmInt = parseInt((t[fIdx.buy_date]||"").substring(4,6),10)||0;
    if (mmInt && !(mask & (1<<(mmInt-1)))) return true;
    let feats = featCache.get(t);
    if (!feats) { feats = tradeFeatures(t); featCache.set(t, feats); }
    const mm3=feats.mm,dd3=feats.dd,sig3=feats.sig,wd3=feats.wd,bpb3=feats.bpb,mktD3=feats.mktD,ratD3=feats.ratD,ts3=feats.ts,etfD3=feats.etfD,q3=feats.q;
    if (v3On) {
      if (filters.n2NovSpecialIndustry && sig3==="buy_special" && mm3==="11" && mktD3==="industry") return false;
      if (filters.r7MayReinforced && ((mktD3==="a"&&mm3==="05")||(ratD3==="mid"&&mm3==="05")||(mm3==="05"&&bpb3==="vlow")||(mm3==="03"&&wd3===2&&bpb3==="high")||(sig3==="buy_special"&&mm3==="11"&&mktD3==="industry")||(sig3==="buy_special"&&mm3==="11"&&wd3===0))) return false;
    }
    if (v4On && filters.greedy15 && (
      (sig3==="buy_special"&&mm3==="05")||(sig3==="buy_special"&&mm3==="11"&&mktD3==="concept")||(sig3==="buy_special"&&mm3==="03")||
      (sig3==="buy_aux"&&mm3==="01")||(q3===2&&bpb3==="vlow"&&sig3==="buy_aux"&&mktD3==="concept")||(sig3==="buy"&&mm3==="01")||
      (mm3==="03"&&wd3===2&&mktD3==="concept"&&ratD3==="low")||(sig3==="buy_aux"&&mm3==="12"&&ts3<50)||(mm3==="06"&&bpb3==="vlow"&&ratD3==="low")||
      (sig3==="buy_aux"&&mm3==="05")||(sig3==="buy_special"&&mm3==="11"&&mktD3==="industry")||(mm3==="04"&&wd3===1&&mktD3==="concept"&&ts3<50)||
      (mktD3==="global"&&q3===1&&sig3==="buy_aux"&&ratD3==="low")||(mm3==="01"&&bpb3==="low"&&sig3==="buy_special"&&mktD3==="concept")||(sig3==="buy_special"&&mm3==="09"&&wd3===2)
    )) return false;
    if (janOn) {
      if (filters.janMidRating && mm3==="01"&&dd3>=11&&dd3<=20&&ratD3==="mid") return false;
      if (filters.janMidSpecial && sig3==="buy_special"&&mm3==="01"&&dd3>=11&&dd3<=20) return false;
    }
  }
  return true;
}
const RATING_RANK = { high:0, mid:1, low:2, "":3 };
const SIG_RANK = { buy_backup:0, buy:1, buy_aux:2, buy_special:3, "":9 };
function posCapKeptKeys(pool, K) {
  const kept = {};
  if (!K || K<=0 || !pool.length) return kept;
  const byDate = {};
  for (const t of pool) {
    const sd = String(t[fIdx.signal_date]||"");
    if (!sd) continue;
    (byDate[sd]||(byDate[sd]=[])).push(t);
  }
  for (const sd in byDate) {
    const rows = byDate[sd];
    rows.sort((a,b) => {
      const tsA = a[fIdx.track_score]!=null?Number(a[fIdx.track_score]):-1;
      const tsB = b[fIdx.track_score]!=null?Number(b[fIdx.track_score]):-1;
      if (tsA !== tsB) return tsB - tsA;
      const rA = RATING_RANK[a[fIdx.rating]] ?? 3, rB = RATING_RANK[b[fIdx.rating]] ?? 3;
      if (rA !== rB) return rA - rB;
      const sA = SIG_RANK[a[fIdx.signal]] ?? 9, sB = SIG_RANK[b[fIdx.signal]] ?? 9;
      if (sA !== sB) return sA - sB;
      return (a[fIdx.buy_date]||"") < (b[fIdx.buy_date]||"") ? -1 : 1;
    });
    const top = rows.slice(0, K);
    for (const t of top) kept[baseKey(t)] = 1;
  }
  return kept;
}
// basePool
const pool = [], seen = {};
for (const rk of ["rating_high","rating_mid","rating_low"]) {
  for (const mk of Object.keys(quads[rk]||{})) {
    for (const t of (quads[rk][mk]||[])) {
      if (!passesFade(t)) continue;
      const bk = baseKey(t);
      if (!seen[bk]) { seen[bk]=1; pool.push(t); }
    }
  }
}
const K = 1;
const posKept = posCapKeptKeys(pool, K);
// day counts for kept (cross mode)
const dayCounts = {};
for (const k in posKept) { const sd = String(k).split("|")[0]; if (sd) dayCounts[sd] = (dayCounts[sd]||0)+1; }
// G mode trades = rating_high/mid/low G union, filtered
function collectModeTrades(modeKey, feeParams) {
  const raw = [];
  for (const rk of ["rating_high","rating_mid","rating_low"]) {
    for (const t of (quads[rk]?.[modeKey]||[])) {
      if (!passesFade(t)) continue;
      if (!posKept[baseKey(t)]) continue;
      raw.push(t);
    }
  }
  // yearly agg
  const ymap = {};
  for (const t of raw) {
    const yr = (t[fIdx.buy_date]||"").substring(0,4);
    if (!yr) continue;
    const dayKept = dayCounts[t[fIdx.signal_date]] || 0;
    const amt = dayKept>0 ? 10000/dayKept : 10000;
    const r = recomputeTrade(t, feeParams, amt);
    if (!ymap[yr]) ymap[yr] = { profit:0, n:0, wins:0, loss:0, _trades:[] };
    const k = ymap[yr];
    k.profit += r.profit; k.n++;
    if (r.profit>0) k.wins++; else k.loss++;
    k._trades.push({ buy_date: t[fIdx.buy_date]||"", sell_date: t[fIdx.sell_date]||"", amount: amt });
  }
  for (const yr in ymap) {
    const v = ymap[yr];
    const mcc = maxConcurrentCapital(v._trades);
    v.peak_capital = mcc;
    v.peak_return_pct = mcc>0 ? Math.round(v.profit/mcc*100*10000)/10000 : 0;
    delete v._trades;
  }
  return ymap;
}
function maxConcurrentCapital(trades) {
  if (!trades.length) return 0;
  const SENTINEL="99999999", deltas={}, dates=[];
  for (const t of trades) {
    const bd=t.buy_date, sd=t.sell_date||SENTINEL, amt=t.amount||0;
    if(!deltas[bd]){deltas[bd]={b:0,s:0};dates.push(bd);} deltas[bd].b+=amt;
    if(!deltas[sd]){deltas[sd]={b:0,s:0};dates.push(sd);} deltas[sd].s+=amt;
  }
  dates.sort();
  let cur=0,maxC=0;
  for (const d of dates) { cur-=deltas[d].s; cur+=deltas[d].b; if(cur>maxC)maxC=cur; }
  return Math.round(maxC*10000)/10000;
}

for (const [fn, fp] of [["etf_main",FEE_MAIN],["etf_def",FEE_DEF]]) {
  console.log("==== fee preset:", fn, "====");
  for (const mk of ["A","F","G"]) {
    const ym = collectModeTrades(mk, fp);
    const yrs = Object.keys(ym).sort();
    console.log(`--- mode ${mk} (n years ${yrs.length}) ---`);
    let cum = 0;
    for (const y of yrs) {
      const v = ym[y];
      cum += v.profit;
      console.log(`  ${y}: n=${v.n} profit=${Math.round(v.profit)} cum=${Math.round(cum)} wins=${v.wins} peakCap=${Math.round(v.peak_capital)} peakRet=${v.peak_return_pct.toFixed(2)}%`);
    }
  }
}
