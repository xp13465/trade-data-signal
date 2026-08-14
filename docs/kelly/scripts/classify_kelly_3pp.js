// ============================================================
// 用途: 3pp 组合分类分析(读 lab.js 提取纯函数 + VM 执行, 按组合分类输出命中)
// 日期/来源: 2026-08-13 / tmp
// 结论: 3pp 组合分类结果, 用于组合/减亏分析
// 依赖: 无(VM 加载 static-site/lab.js)
// 输入/输出: 读 lab.js + signal_kelly_backtest.json, 输出 3pp 分类结果
// 复现: node classify_kelly_3pp.js
// 注意: 含硬编码绝对路径; 如需重跑请确认路径或改相对路径
// ============================================================
const fs = require('fs');
const vm = require('vm');

const LAB_PATH = 'static-site/lab.js';
const ALL_KEYS=['a5NovMidSpecial','a45NovMidLateSpecial','n1MarTueHigh','n2NovSpecialIndustry','r8PureNonMay','n3NovSpecialMon','n4AMay','r7MayReinforced','n5MayVlow','n6MidMay','r10May6NonMay','excludeAuxCross','excludeSpecialBear','excludeMonth','excludeAux','marketTiming','excludeRatingLow','greedy7','v4cSimple','v4b','greedy10','v4d','v4j','v4i','greedy15','v4f','v4g','v4m','v4k','janMidRating','janMidSpecial'];
const DEFAULT_ON=['n2NovSpecialIndustry','excludeSpecialBear','janMidRating','janMidSpecial'];
const keyBit={}; ALL_KEYS.forEach((k,i)=>{keyBit[k]=1<<i;});
const ADD=['r7MayReinforced','excludeAuxCross','greedy15'];
const POSK=1;

function buildEnv(labPath, tradesPath, backtestPath){
  const lines=fs.readFileSync(labPath,'utf8').split('\n');
  let start=-1,end=-1;
  for(let i=0;i<lines.length;i++){
    if(start<0&&lines[i].includes('function _kellyIsShEtf'))start=i;
    if(start>=0&&(lines[i].includes('async function _kellyRunRecompute')||lines[i].includes('function _kellyRunRecompute('))){end=i;break;}
  }
  let s2=start;
  for(let i=start-1;i>=0;i--){ if(lines[i].includes('KELLY_ORIG_SLIPPAGE')){s2=i;break;} }
  const block=lines.slice(s2,end).join('\n');
  global.localStorage={getItem:()=>null,setItem:()=>{}};
  global.requestAnimationFrame=(cb)=>cb();
  global.fetch=async()=>{throw new Error('fetch stub');};
  global._labCustomCacheBust=()=>'x';
  global.state={};
  const ctx={console,JSON,Math,Date,Number,String,Object,Array,Map,Promise,parseInt,parseFloat,isNaN,localStorage:global.localStorage,requestAnimationFrame:global.requestAnimationFrame,fetch:global.fetch,_labCustomCacheBust:global._labCustomCacheBust,state:global.state,module:{exports:{}},exports:{}};
  ctx.globalThis=ctx;
  vm.createContext(ctx); vm.runInContext(block,ctx);
  const td=JSON.parse(fs.readFileSync(tradesPath,'utf8'));
  const bd=JSON.parse(fs.readFileSync(backtestPath,'utf8'));
  ctx.state.labSigKellyData=bd; ctx.state.labSigKellyTradesData=td;
  ctx.state.labSigKellyFeeParams={commission_rate:0.0003,min_commission:5,slippage:0.001,transfer_fee_rate_sh:0.00001,stamp_duty_rate:0};
  ctx.state.labSigKellyFeePreset='etf_def';
  const fIdx={}; td.fields.forEach((f,i)=>{fIdx[f]=i;});
  const buyAmount=td.buy_amount||10000;
  const sellModes=bd.config.sell_modes||{};
  const quads=td.quadrants||{};
  const tradeDims=ctx._kellyBuildTradeDims(td,fIdx);
  return {ctx,td,bd,fIdx,buyAmount,sellModes,quads,tradeDims};
}

function bkof(t,fIdx){return (t[fIdx.signal_date]??'')+'|'+(t[fIdx.index_id]??'')+'|'+(t[fIdx.signal]??'')+'|'+(t[fIdx.buy_date]??'')+'|'+(t[fIdx.etf_code]??'');}

function getHits(env){
  const {ctx,fIdx,sellModes,quads,tradeDims}=env;
  let keyMask=0;
  for(const k of DEFAULT_ON) keyMask|=keyBit[k];
  for(const k of ADD) keyMask|=keyBit[k];
  const singleKeyFilters={},singleKeyMM={};
  for(const k of ALL_KEYS){
    const f={}; ALL_KEYS.forEach(kk=>{f[kk]=false;}); f[k]=true; f.positionCap=false; f.positionCapK=0;
    singleKeyFilters[k]=f; singleKeyMM[k]=ctx._kellyActiveMonthMask(f);
  }
  const hitsByBK={};
  for(const rk of ['rating_high','rating_mid','rating_low']){
    for(const mk in sellModes){
      for(const t of (quads[rk]||{})[mk]||[]){
        const bk=bkof(t,fIdx);
        if(hitsByBK[bk]!==undefined){t._hitsMask=hitsByBK[bk];continue;}
        let mask=0; const fc=new Map();
        for(const k of ALL_KEYS){ if(!ctx._kellyPassesFadeFilters(t,fIdx,singleKeyFilters[k],fc,tradeDims,singleKeyMM[k])) mask|=keyBit[k]; }
        t._hitsMask=mask; hitsByBK[bk]=mask;
      }
    }
  }
  // byDate sort for posCap
  const byDate={};
  for(const rk of ['rating_high','rating_mid','rating_low']){
    for(const mk in sellModes){
      const rows=(quads[rk]||{})[mk]||[];
      for(const t of rows){
        const sd=String(t[fIdx.signal_date]||""); if(!sd)continue;
        (byDate[sd]||(byDate[sd]=[])).push(t);
      }
    }
  }
  for(const sd in byDate) byDate[sd].sort((a,b)=>{
    var sa=Number(a[fIdx.track_score])||-1, sb=Number(b[fIdx.track_score])||-1;
    if(sb!==sa)return sb-sa;
    var da=String(a[fIdx.buy_date]||""),db=String(b[fIdx.buy_date]||"");
    return da<db?-1:1;
  });
  const posCapKept={};
  if(POSK>0){
    for(const sd in byDate){
      let cnt=0;
      for(const t of byDate[sd]){
        if((t._hitsMask&keyMask)===0){ posCapKept[bkof(t,fIdx)]=true; if(++cnt>=POSK)break; }
      }
    }
  }
  const collected=[];
  for(const rk of ['rating_high','rating_mid','rating_low']){
    for(const t of (quads[rk]||{})['A']||[]){
      if((t._hitsMask&keyMask)===0 && (!posCapKept||posCapKept[bkof(t,fIdx)])) collected.push(t);
    }
  }
  return {collected,keyMask};
}

// Load both datasets
const envo = buildEnv(LAB_PATH, '/tmp/kelly_trades_dc59898.json', 'static-site/data/signal_kelly_backtest.json');
const envn = buildEnv(LAB_PATH, 'static-site/data/signal_kelly_trades.json', 'static-site/data/signal_kelly_backtest.json');

const oldHits = getHits(envo).collected;
const newHits = getHits(envn).collected;
console.log(`OLD K1 hits (A-mode): ${oldHits.length}   NEW K1 hits (A-mode): ${newHits.length}`);

// verify totals
let op=0,np=0;
for(const t of oldHits) op+=Number(t[envo.fIdx.profit]);
for(const t of newHits) np+=Number(t[envn.fIdx.profit]);
console.log(`OLD total profit=${Math.round(op)}  NEW total profit=${Math.round(np)}  diff=${Math.round(np-op)}`);

// Build maps keyed by (signal_date|index_id|signal|buy_date|etf_code)
function mapByBK(hits,fIdx){
  const m=new Map();
  for(const t of hits){ const k=bkof(t,fIdx); m.set(k,t); }
  return m;
}
const mo=mapByBK(oldHits,envo.fIdx);
const mn=mapByBK(newHits,envn.fIdx);

function rec(f){
  return {sd:f[envo.fIdx.signal_date]||'', ix:f[envo.fIdx.index_id]||'',
    bd:f[envo.fIdx.buy_date]||'', code:f[envo.fIdx.etf_code]||'',
    name:f[envo.fIdx.etf_name]||'', bp:Number(f[envo.fIdx.buy_price]), sp:Number(f[envo.fIdx.sell_price]),
    p:Number(f[envo.fIdx.profit]), rp:Number(f[envo.fIdx.return_pct]), mm:f[envo.fIdx.match_method]||''};
}

// Classify
const cat={swapped:0,recomputed:0,flagOnly:0,netNew:0,netRemoved:0,identical:0};
let dSwapped=0,dRecomputed=0,dFlag=0,dNetNew=0,dNetRemoved=0;
const samples={swapped:[],recomputed:[],flagOnly:[],netNew:[],netRemoved:[]};

// 1) common exact bkeys
for(const [bk,t] of mo){
  if(mn.has(bk)){
    const o=rec(t), n=rec(mn.get(bk));
    if(Math.abs(o.p-n.p)<0.001 && o.bp===n.bp){ cat.identical++; }
    else if(o.code===n.code && o.bd===n.bd && o.sd===n.sd && (o.bp!==n.bp||o.p!==n.p)){
      cat.recomputed++; dRecomputed+=(n.p-o.p);
      if(samples.recomputed.length<5) samples.recomputed.push({sd:o.sd,code:o.code,bd:o.bd,old:{bp:o.bp,p:o.p},nw:{bp:n.bp,p:n.p}});
    } else if(o.code!==n.code){
      cat.swapped++; dSwapped+=(n.p-o.p);
      if(samples.swapped.length<5) samples.swapped.push({sd:o.sd,bd:o.bd,old:{code:o.code,name:o.name,p:o.p},nw:{code:n.code,name:n.name,p:n.p}});
    } else {
      cat.flagOnly++; dFlag+=(n.p-o.p);
    }
  } else {
    const r_=rec(t); cat.netRemoved++; dNetRemoved+=(-r_.p);
    if(samples.netRemoved.length<5) samples.netRemoved.push(r_);
  }
}
// 2) only in new
for(const [bk,t] of mn){
  if(!mo.has(bk)){
    cat.netNew++; dNetNew+=rec(t).p;
    if(samples.netNew.length<5) samples.netNew.push(rec(t));
  }
}

console.log("\n===== 4类归因 =====");
const tot={...cat};
console.log("类别分布(笔数):", JSON.stringify(tot));
console.log("profit贡献元:", JSON.stringify({swapped:Math.round(dSwapped),recomputed:Math.round(dRecomputed),flag:Math.round(dFlag),netNew:Math.round(dNetNew),netRemoved:Math.round(dNetRemoved)}));
const sumDiff=Math.round(dSwapped+dRecomputed+dFlag+dNetNew+dNetRemoved);
console.log("四类合计 diff =", sumDiff, "  实际np-op =", Math.round(np-op), "  一致?", sumDiff===Math.round(np-op));
console.log("\n--- 代表性样本 ---");
for(const k of ['swapped','recomputed','netNew','netRemoved']){
  console.log(`\n[${k}] (${samples[k].length} shown of ${samples[k].length})`);
  for(const s of samples[k]) console.log("  ", JSON.stringify(s, (key,val)=>val&&val.toFixed?+val.toFixed(2):val));
}
