// ============================================================
// 用途: 按年回撤复算(演进版2/中间版, 以最新 kelly_yearly_dd3.js 为准)
// 日期/来源: 2026-08-14 / tmp
// 结论: 2011 A模式峰值→谷底回撤 14.01% (最终确认见 dd3)
// 依赖: 无
// 输入/输出: 读 signal_kelly_trades.json(绝对路径), 输出按年回撤
// 复现: node kelly_yearly_dd2.js
// 注意: 演进版本, 以 kelly_yearly_dd3.js 为最终版; 含硬编码绝对路径
// ============================================================
const fs = require('fs');
const data = JSON.parse(fs.readFileSync('/Users/linhuichen/code/trade/static-site/data/signal_kelly_trades.json', 'utf8'));
const F = data.fields; const fIdx = {}; F.forEach((f,i)=>fIdx[f]=i);
const quads = data.quadrants;
const KELLY_ORIG_SLIPPAGE = 0.001;
const FEE_DEF = { commission_rate:0.0003, min_commission:5, slippage:0.001, transfer_fee_rate_sh:0.00001, stamp_duty_rate:0 };
function isShEtf(c){return c?(c.startsWith("51")||c.startsWith("58")):false;}
function rt(t,fp,amt){
  const bp=t[fIdx.buy_price]||0,sp=t[fIdx.sell_price]||0,cp=t[fIdx.current_price]||0,ec=t[fIdx.etf_code]||"",sd=t[fIdx.sell_date]||"";
  if(bp<=0)return{profit:0};
  const cb=bp/(1+KELLY_ORIG_SLIPPAGE), cs=sd?(sp/(1-KELLY_ORIG_SLIPPAGE)):cp;
  const c=fp.commission_rate,s=fp.slippage,minC=fp.min_commission,sh=isShEtf(ec)?fp.transfer_fee_rate_sh:0,st=fp.stamp_duty_rate;
  const bpn=cb*(1+s); if(bpn<=0)return{profit:0};
  let sn=amt/(bpn*(1+c+sh)); let gn=sn*bpn; let cb2=gn*c;
  if(cb2<minC){sn=(amt-minC)/(bpn*(1+sh));gn=sn*bpn;cb2=minC;}
  const spn=cs*(1-s), sam=sn*spn;
  const net=sam-Math.max(sam*c,minC)-sam*sh-sam*st;
  return{profit:Math.round((net-amt)*10000)/10000};
}
function baseKey(t){return[t[fIdx.signal_date],t[fIdx.index_id],t[fIdx.signal],t[fIdx.buy_date],t[fIdx.etf_code]].join("|");}
function buyWeekday(bd){const y=+bd.substring(0,4),m=+bd.substring(4,6),d=+bd.substring(6,8);return(new Date(y,m-1,d).getDay()+6)%7;}
function bpb(p){if(p==null)return"";if(p<=0.841441)return"vlow";if(p<=1.015314)return"low";if(p<=1.194593)return"mid";if(p<=1.446645)return"high";return"vhigh";}
const dims={};
for(const qk in quads){const parts=qk.split('_'),dt=parts[0],dv=parts.slice(1).join('_');
  for(const mk in quads[qk])for(const t of quads[qk][mk]){const key=[t[fIdx.signal_date],t[fIdx.index_id],t[fIdx.signal],t[fIdx.buy_date],t[fIdx.etf_code],t[fIdx.sell_date]].join("|");
    if(!dims[key])dims[key]={};dims[key][dt]=dv;}}
const filters={n2NovSpecialIndustry:true,r7MayReinforced:true,excludeAuxCross:true,excludeSpecialBear:true,greedy15:true,janMidRating:true,janMidSpecial:true};
const mask=(1<<10)|((1<<4)|(1<<2)|(1<<10))|((1<<0)|(1<<1)|(1<<2)|(1<<3)|(1<<4)|(1<<5)|(1<<8)|(1<<10)|(1<<11))|(1<<0);
const fc=new Map();
function feats(t){
  const bd=String(t[fIdx.buy_date]||""),mm=bd.substring(4,6),dd=+bd.substring(6,8)||0,sig=String(t[fIdx.signal]||""),wd=buyWeekday(bd),p=bpb(t[fIdx.buy_price]);
  const dk=[t[fIdx.signal_date],t[fIdx.index_id],sig,bd,t[fIdx.etf_code],t[fIdx.sell_date]].join("|"),ds=dims[dk]||{};
  const ts=t[fIdx.track_score]!=null?+t[fIdx.track_score]:999,etfD=String(t[fIdx.track_tier]||""),q=mm?Math.ceil(+mm/3):0;
  return{mm,dd,sig,wd,p,mktD:ds.mkt||"",ratD:ds.rating||"",ts,etfD,q};
}
function passes(t){
  if((t[fIdx.signal]||"")==="buy_aux"){const m=(t[fIdx.buy_date]||"").substring(4,6);if(m==="03"||m==="05")return false;}
  if((t[fIdx.signal]||"")==="buy_special"&&t[fIdx.market_state]===false)return false;
  const mmInt=parseInt((t[fIdx.buy_date]||"").substring(4,6),10)||0;
  if(mmInt&&!(mask&(1<<(mmInt-1))))return true;
  let f=fc.get(t);if(!f){f=feats(t);fc.set(t,f);}
  if(filters.n2NovSpecialIndustry&&f.sig==="buy_special"&&f.mm==="11"&&f.mktD==="industry")return false;
  if(filters.r7MayReinforced&&((f.mktD==="a"&&f.mm==="05")||(f.ratD==="mid"&&f.mm==="05")||(f.mm==="05"&&f.p==="vlow")||(f.mm==="03"&&f.wd===2&&f.p==="high")||(f.sig==="buy_special"&&f.mm==="11"&&f.mktD==="industry")||(f.sig==="buy_special"&&f.mm==="11"&&f.wd===0)))return false;
  if(filters.greedy15&&((f.sig==="buy_special"&&f.mm==="05")||(f.sig==="buy_special"&&f.mm==="11"&&f.mktD==="concept")||(f.sig==="buy_special"&&f.mm==="03")||(f.sig==="buy_aux"&&f.mm==="01")||(f.q===2&&f.p==="vlow"&&f.sig==="buy_aux"&&f.mktD==="concept")||(f.sig==="buy"&&f.mm==="01")||(f.mm==="03"&&f.wd===2&&f.mktD==="concept"&&f.ratD==="low")||(f.sig==="buy_aux"&&f.mm==="12"&&f.ts<50)||(f.mm==="06"&&f.p==="vlow"&&f.ratD==="low")||(f.sig==="buy_aux"&&f.mm==="05")||(f.sig==="buy_special"&&f.mm==="11"&&f.mktD==="industry")||(f.mm==="04"&&f.wd===1&&f.mktD==="concept"&&f.ts<50)||(f.mktD==="global"&&f.q===1&&f.sig==="buy_aux"&&f.ratD==="low")||(f.mm==="01"&&f.p==="low"&&f.sig==="buy_special"&&f.mktD==="concept")||(f.sig==="buy_special"&&f.mm==="09"&&f.wd===2)))return false;
  if(filters.janMidRating&&f.mm==="01"&&f.dd>=11&&f.dd<=20&&f.ratD==="mid")return false;
  if(filters.janMidSpecial&&f.sig==="buy_special"&&f.mm==="01"&&f.dd>=11&&f.dd<=20)return false;
  return true;
}
const RANK={high:0,mid:1,low:2,"":3},SRANK={buy_backup:0,buy:1,buy_aux:2,buy_special:3,"":9};
const pool=[],seen={};
for(const rk of ["rating_high","rating_mid","rating_low"])for(const mk in (quads[rk]||{}))for(const t of (quads[rk][mk]||[])){
  if(!passes(t))continue;const bk=baseKey(t);if(!seen[bk]){seen[bk]=1;pool.push(t);}}
const K=1,kept={},byDate={};
for(const t of pool){const sd=String(t[fIdx.signal_date]||"");if(!sd)continue;(byDate[sd]||(byDate[sd]=[])).push(t);}
for(const sd in byDate){const rows=byDate[sd].sort((a,b)=>{
  const ta=a[fIdx.track_score]!=null?+a[fIdx.track_score]:-1,tb=b[fIdx.track_score]!=null?+b[fIdx.track_score]:-1;
  if(ta!==tb)return tb-ta;
  const ra=(RANK[a[fIdx.rating]]??3),rb=(RANK[b[fIdx.rating]]??3);if(ra!==rb)return ra-rb;
  const sa=(SRANK[a[fIdx.signal]]??9),sb=(SRANK[b[fIdx.signal]]??9);if(sa!==sb)return sa-sb;
  return(a[fIdx.buy_date]||"")<(b[fIdx.buy_date]||"")?-1:1;});
  for(const t of rows.slice(0,K))kept[baseKey(t)]=1;}
const dayCounts={};for(const k in kept){const sd=String(k).split("|")[0];if(sd)dayCounts[sd]=(dayCounts[sd]||0)+1;}
function yearlyDD(mk){
  const raw=[];
  for(const rk of ["rating_high","rating_mid","rating_low"])for(const t of (quads[rk]?.[mk]||[])){
    if(!passes(t)||!kept[baseKey(t)])continue;raw.push(t);}
  const ym={};
  for(const t of raw){
    const yr=(t[fIdx.buy_date]||"").substring(0,4);if(!yr)continue;
    const dk=dayCounts[t[fIdx.signal_date]]||0,amt=dk>0?10000/dk:10000;
    const r=rt(t,FEE_DEF,amt);
    if(!ym[yr])ym[yr]={profit:0,totalInv:0,_trades:[]};
    ym[yr].profit+=r.profit;ym[yr].totalInv+=amt;
    ym[yr]._trades.push({buy_date:t[fIdx.buy_date]||"",sell_date:t[fIdx.sell_date]||"",amount:amt,profit:r.profit});}
  for(const yr in ym){const v=ym[yr];const dd=maxDD(v._trades);const pcc=maxConcCap(v._trades);
    const peakDdPct=pcc>0?Math.round(dd.abs/pcc*100*10000)/10000:0;
    const invDdPct=v.totalInv>0?Math.round(dd.abs/v.totalInv*100*10000)/10000:0;
    v.peak_dd_pct=peakDdPct;v.inv_dd_pct=invDdPct;v.dd_abs=dd.abs;delete v._trades;}
  return ym;
}
function maxDD(trades){if(!trades.length)return{abs:0};
  const s=trades.slice().sort((a,b)=>{const da=a.sell_date||"99999999",db=b.sell_date||"99999999";return da<db?-1:da>db?1:0;});
  let cum=0,peak=0,mx=0;for(const t of s){cum+=t.profit;if(cum>peak)peak=cum;const d=peak-cum;if(d>mx)mx=d;}
  return{abs:Math.round(mx*10000)/10000};}
function maxConcCap(trades){if(!trades.length)return 0;const S="99999999",d={},ds=[];
  for(const t of trades){const bd=t.buy_date,sd=t.sell_date||S,amt=t.amount||0;
    if(!d[bd]){d[bd]={b:0,s:0};ds.push(bd);}d[bd].b+=amt;if(!d[sd]){d[sd]={b:0,s:0};ds.push(sd);}d[sd].s+=amt;}
  ds.sort();let cur=0,mx=0;for(const x of ds){cur-=d[x].s;cur+=d[x].b;if(cur>mx)mx=cur;}return Math.round(mx*10000)/10000;}
console.log("A 模式 · etf_def(ETF默认 万3最低5) · K=1 · AI宏7键 · 按年两种回撤口径:");
console.log("年份 | 净盈亏 | 峰值持仓(元) | 峰值资金收益率% | 峰值资金回撤%(=回撤/峰值持仓) | 回撤/总投入% | 回撤绝对额");
let cum=0;
for(const yr of Object.keys(yearlyDD("A")).sort()){const v=yearlyDD("A")[yr];cum+=v.profit;
  console.log(`${yr} | ${Math.round(v.profit)} | ${Math.round(v._trades?0:0)} ${yr} | ${Math.round(v.profit)} | peakRet=${Math.round(v.profit/(v.peak_capital||1)*100*10000)/10000}%?`);}
