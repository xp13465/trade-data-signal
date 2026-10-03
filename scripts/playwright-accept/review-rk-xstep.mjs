// reviewer 独立复现脚本
import pw from "/Users/linhuichen/node_modules/playwright/index.js";
const chromium = pw.chromium;

const BASE = "http://127.0.0.1:8934";
let failures = 0;
function assert(name, cond, detail){ if(!cond){failures++;console.log("FAIL "+name+" :: "+detail);}else console.log("PASS "+name+" :: "+detail); }
const browser = await chromium.launch();

const OLD = `function _etfXStep_OLD(n, iw, fs){let _labelW=28;try{const _c=document.createElement("canvas");const _ctx=_c.getContext&&_c.getContext("2d");if(_ctx&&_ctx.measureText){_ctx.font=(fs||10)+"px sans-serif";_labelW=_ctx.measureText("MM-DD").width||28;}}catch(_e){}const _unitW=iw/n;const _maxW=Math.max(_labelW*1.3,7);return Math.max(0,Math.floor(_maxW/_unitW))+1;}`;
const ctx = await browser.newContext({ viewport:{width:900,height:800} });
const page = await ctx.newPage();
await page.route("**/*", (route)=>{ const url=new URL(route.request().url());
  if(url.origin==="http://127.0.0.1:8934" && (url.pathname==="/"||url.pathname==="/index.html")){
    route.fulfill({status:200,contentType:"text/html",body:'<!DOCTYPE html><html><head><meta charset="utf-8"></head><body><div id="content"></div><script src="/common.js"></script><script src="/purpose-notes.js"></script><script src="/i18n.js"></script><script src="/app.js"></script></body></html>'});
  } else route.continue(); });
await page.goto(BASE+"/",{waitUntil:"load"});
const diag = await page.evaluate(()=>{
  return { hasLbl: typeof window._lblWEst, hasEtf: typeof window._etfXStep, hasSvg: typeof window._lwSVG,
    bodyLen: document.body ? document.body.innerHTML.length : -1,
    scripts: [...document.scripts].map(s=>s.src).join("|"),
    stateKeys: typeof window.state };
});
console.log("DIAG", JSON.stringify(diag));
for(let i=0;i<100;i++){ const rd=await page.evaluate(()=>typeof window._lblWEst==="function"&&typeof window._etfXStep==="function"&&typeof window._lwSVG==="function"); if(rd)break; await page.waitForTimeout(200); if(i===99){console.error("app.js not ready");process.exit(1);} }
await page.evaluate((src) => { window._etfXStep_OLD = (0, eval)("(" + src + ")"); }, OLD);

// T1 多形态估宽对比
const t1 = await page.evaluate(()=>{
  const forms=[["8位日期@12","20260928",12],["MM-DD@12","MM-DD",12],["10字符带年@12","2026-01-01",12],["中文@12","上涨家数",12],["负号百分比@12","-123.45%",12],["MM-DD@10","MM-DD",10],["8位日期@10","20260928",10],["年@10","2026",10]];
  const cx=document.createElement("canvas").getContext("2d"); const out=[];
  for(const [name,s,fs] of forms){ cx.font=fs+"px sans-serif"; const real=cx.measureText(s).width; const est=_lblWEst(s,fs); out.push({name,fs,real:+real.toFixed(2),est:+est.toFixed(2),diff:+(est-real).toFixed(2)}); }
  return out; });
console.log("T1 多形态估宽对比(est-real>0=高估安全/<0=低估)");
for(const r of t1) console.log("  "+r.name+" real="+r.real+" est="+r.est+" diff="+(r.diff>0?"+":"")+r.diff);
const under=t1.filter(r=>r.diff<0);
assert("T1 all forms not underestimated", under.length===0, under.length?"低估: "+under.map(r=>r.name+"("+r.diff+"px)").join(", "):"全部高估或相等");

// T2 正常路径逐位一致
const t2 = await page.evaluate(()=>{
  const out=[]; const cases=[[85,584,undefined],[85,584,12],[60,565,undefined],[120,565,12],[20,565,12],[240,565,12]];
  for(const [n,iw,fs] of cases){ const o=_etfXStep_OLD(n,iw,fs); const a=_etfXStep(n,iw,fs,"20260928"); const b=_etfXStep(n,iw,fs,"MM-DD"); out.push({n,iw,fs,o,a,b,same:o===a&&o===b}); }
  return out; });
for(const r of t2) assert("T2 same n="+r.n+" iw="+r.iw+" fs="+r.fs, r.same, "old="+r.o+" new8="+r.a+" new5="+r.b);

await page.evaluate(()=>{ window.__origCE = document.createElement.bind(document); });
// T3 降级路径标签不重叠(打掉 measureText)
const t3 = await page.evaluate(()=>{
  const oc=document.createElement.bind(document);
  const kill=()=>{ document.createElement=(t,o)=>{const el=oc(t,o); if(String(t).toLowerCase()==="canvas"){el.getContext=()=>null;} return el;}; };
  const mk=(dates)=>({h:180,pl:40,pr:16,pt:30,pb:44,boundaryGap:true,xLabels:dates,xFmt:(v)=>v,forceLastLabel:true,ys:[{splitLine:true}],series:[{type:"line",data:dates.map((_,i)=>50+Math.sin(i/5)*30),color:"#409eff"}]});
  const d8=Array.from({length:85},(_,i)=>String(20250310+i));
  const svgN=_lwSVG(mk(d8));
  kill();
  const svgD=_lwSVG(mk(d8));
  const meas=(s)=>{ const h=document.createElement("div"); h.style.cssText="position:absolute;left:-10000px;top:0;width:640px"; h.innerHTML='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="300">'+s+"</svg>"; document.body.appendChild(h);
    const svg=h.querySelector("svg");
    const boxes=[...svg.querySelectorAll("text")].filter(t=>+t.getAttribute("font-size")===12&&t.textContent.length>=4).map(t=>{const b=t.getBBox();return{text:t.textContent,x:b.x,w:b.width,y:b.y};});
    const xs=boxes.filter(b=>b.y>120); let ov=null;
    for(let i=0;i<xs.length-1;i++){ if(xs[i].x+xs[i].w>xs[i+1].x-0.1){ov={a:xs[i].text+"@"+xs[i].x.toFixed(1)+"+"+xs[i].w.toFixed(1),b:xs[i+1].text+"@"+xs[i+1].x.toFixed(1)};break;} }
    h.remove(); return {xCount:xs.length,ov}; };
  return {normal:meas(svgN),deg:meas(svgD),steps:{nw:_etfXStep(85,584,12,"20260928"),old:_etfXStep_OLD(85,584,12)}}; });
assert("T3 degrade no overlap (8位日期)", !t3.deg.ov, t3.deg.ov?("降级重叠 "+t3.deg.ov.a+" / "+t3.deg.ov.b):("降级x标签 "+t3.deg.xCount+" 无重叠; step new="+t3.steps.nw+" old="+t3.steps.old));
console.log("  正常路径 x 标签", t3.normal.xCount, "重叠:", t3.normal.ov||"无");

// T4 #152 判据边界
const t4 = await page.evaluate(()=>{
  const norm=(v,th,hit)=>({name:"地量",key:"f4",value:v,threshold:th,hit:hit});
  const dayFor=(factors)=>({date:"20261003",freeze:[{score_id:"s.ex",value:12.3}],sh_freeze:true,sh_level:"main",sh_hits:{n:2,total:4},consensus:{x:2,y:2},sh_factors:factors,signals:[]});
  const open=(day)=>{openSentimentDayDetailModal(day);return document.querySelector("#sentimentDayDetailModal .day-detail-content").innerHTML;};
  const c={};
  c.zero=open(dayFor([norm(0,30,false)]));
  c.null=open(dayFor([norm(null,30,false)]));
  c.undef=open(dayFor([{name:"地量",key:"f4",value:undefined,threshold:30,hit:false}]));
  c.nan=open(dayFor([norm(NaN,30,false)]));
  c.absent=open(dayFor([{name:"地量",key:"f4",threshold:30,hit:false}]));
  c.inf=open(dayFor([norm(Infinity,30,false)]));
  c.miss=open(dayFor([norm(45,30,false)]));
  c.hit=open(dayFor([norm(20,30,true)]));
  return c; });
const has=(s,sub)=>s.indexOf(sub)>=0;
assert("T4a value=0 -> 未中非缺失", has(t4.zero,"✗未中")&&has(t4.zero,"当前 0"), t4.zero.slice(0,300));
assert("T4b null -> 缺失", has(t4.null,"数据缺失,无法判定")&&has(t4.null,"—"),"null OK");
assert("T4c undefined -> 缺失", has(t4.undef,"数据缺失,无法判定")&&has(t4.undef,"—"),"undefined OK");
assert("T4d NaN -> 缺失", has(t4.nan,"数据缺失,无法判定"),"NaN OK");
assert("T4e 字段不存在 -> 缺失不抛错", has(t4.absent,"数据缺失,无法判定")&&has(t4.absent,"—"),"字段缺失 OK");
assert("T4f Infinity -> 缺失", has(t4.inf,"数据缺失,无法判定"),"Infinity OK");
assert("T4g 有值未达阈值 -> 未中(互斥)", has(t4.miss,"✗未中")&&!has(t4.miss,"数据缺失,无法判定")&&has(t4.miss,"当前 45"),"未中 OK");
assert("T4h 命中", has(t4.hit,"✓命中")&&!has(t4.hit,"数据缺失,无法判定"),"命中 OK");
assert("T4 文案互斥", ![t4.zero,t4.null,t4.nan,t4.miss,t4.hit].some(h=>has(h,"数据缺失,无法判定")&&has(h,"✗未中")),"互斥 OK");

// T5a 证伪: 系数调小 -> 重叠出现
const t5a = await page.evaluate(()=>{
  const oc=document.createElement.bind(document);
  document.createElement=(t,o)=>{const el=oc(t,o); if(String(t).toLowerCase()==="canvas") el.getContext=()=>null; return el;};
  const d8=Array.from({length:85},(_,i)=>String(20250310+i));
  const oL=_lblWEst; window._lblWEst=(label,fs)=>String(label==null?"":label).length*(fs||10)*0.01;
  const svg=_lwSVG({h:180,pl:40,pr:16,pt:30,pb:44,boundaryGap:true,xLabels:d8,xFmt:(v)=>v,forceLastLabel:true,ys:[{splitLine:true}],series:[{type:"line",data:d8.map((_,i)=>50+Math.sin(i/5)*30),color:"#409eff"}]});
  const h=document.createElement("div"); h.style.cssText="position:absolute;left:-10000px;top:0;width:640px"; h.innerHTML='<svg xmlns="http://www.w3.org/2000/svg" width="640" height="300">'+svg+"</svg>"; document.body.appendChild(h);
  const xs=[...h.querySelector("svg").querySelectorAll("text")].filter(t=>+t.getAttribute("font-size")===12&&t.textContent.length>=4).map(t=>{const b=t.getBBox();return{text:t.textContent,x:b.x,w:b.width,y:b.y};}).filter(b=>b.y>120);
  let ov=null; for(let i=0;i<xs.length-1;i++){ if(xs[i].x+xs[i].w>xs[i+1].x-0.1){ov={a:xs[i].text,b:xs[i+1].text};break;} }
  window._lblWEst=oL; document.createElement=oc; h.remove(); return {ov,xCount:xs.length}; });
assert("T5a 证伪: 系数调小后测试抓到重叠", !!t5a.ov, t5a.ov?("抓到 "+t5a.ov.a+" / "+t5a.ov.b+", x标签共"+t5a.xCount):"未抓到(测试不敏感)");

// T5b 证伪: 缺失在错误渲染下不显示
const t5b = await page.evaluate(()=>{
  const has2=(s,sub)=>s.indexOf(sub)>=0;
  const day={date:"20261003",freeze:[],sh_freeze:true,sh_level:"main",sh_hits:{n:2,total:4},consensus:{x:2,y:2},sh_factors:[{name:"地量",key:"f4"}],signals:[]};
  openSentimentDayDetailModal(day);
  const real=document.querySelector("#sentimentDayDetailModal .day-detail-content").innerHTML;
  const fake='<div class="dd-row sh-f-miss"><span class="dd-name">地量 <span class="sh-f-mark sh-f-mark-miss">✗未中</span></span><span class="dd-val">当前 — / 阈值 ≤30</span></div>';
  return {fakeNA:has2(fake,"数据缺失"),realNA:has2(real,"数据缺失"),realMiss:has2(real,"✗未中")}; });
assert("T5b 证伪: 测试对缺失敏感", !t5b.fakeNA&&t5b.realNA, "错误渲染含缺失="+t5b.fakeNA+"(应false) 真渲染含缺失="+t5b.realNA+"(应true) 真渲染误含未中="+t5b.realMiss);

// T6 各图正常路径 step 一致
const t6 = await page.evaluate(()=>{
  document.createElement = window.__origCE || document.createElement.bind(document);
  const forms=[["信号图(dataZoom)",250,{dataZoom:true}],["腾落线(120条)",120,{dataZoom:true}],["KPI图(dataZoom)",80,{dataZoom:true}],["市场宽度(20条)",20,{}],["分时(显式xStep)",52,{axisFontSize:10,xStep:13,boundaryGap:false}]];
  const out=[];
  for(const [name,n,opts] of forms){ const dates=Array.from({length:n},(_,i)=>String(20250901+i%89)); const iw=640-55-20;
    const o=_etfXStep_OLD(n,iw,opts.axisFontSize||12); const a=_etfXStep(n,iw,opts.axisFontSize||12,dates[0]); out.push({name,o,a,same:o===a}); }
  return out; });
for(const r of t6) assert("T6 "+r.name+" 正常路径 step 一致", r.same, "old="+r.o+" new="+r.a);


// T7 降级路径全谱扫描: _lblWEst 低估形态在真实图参数下是否产生重叠
const t7 = await page.evaluate(()=>{
  const meas = (label, fs) => { const c=document.createElement("canvas"); const k=c.getContext("2d"); k.font=fs+"px sans-serif"; return k.measureText(label).width; };
  const real = { mm12: meas("MM-DD",12), mm10: meas("MM-DD",10), cn12: meas("上海炒家",12), d8: meas("20260928",12) };
  const oc=document.createElement.bind(document);
  document.createElement=(t,o)=>{const el=oc(t,o); if(String(t).toLowerCase()==="canvas"){el.getContext=()=>null;} return el;};
  const stepFor=(iw,n,fs,label)=>{ const u=iw/n; const est=Math.max(label.length,5)*(fs||10)*0.6; const maxW=Math.max(est*1.3,7); return {step:Math.max(0,Math.floor(maxW/u))+1, u}; };
  const mk=(iw,n,fs,label,realW)=>{ const {step,u}=stepFor(iw,n,fs,label); const gap=step*u; return {iw,n,step,u:+u.toFixed(2),gap:+gap.toFixed(1),realW:+realW.toFixed(2),overlap:gap<realW}; };
  const cases=[
    ["净资产同年 MM-DD@12 n=60", mk(518,60,12,"MM-DD",real.mm12)],
    ["净资产同年 MM-DD@12 n=21", mk(518,21,12,"MM-DD",real.mm12)],
    ["ETF走势 MM-DD@10 n=60", mk(565,60,10,"MM-DD",real.mm10)],
    ["ETF走势 MM-DD@10 n=120", mk(565,120,10,"MM-DD",real.mm10)],
    ["中文标签@12 n=60", mk(518,60,12,"上海炒家",real.cn12)],
    ["8位日期@12 n=85", mk(584,85,12,"20260928",real.d8)],
  ];
  document.createElement=oc;
  return cases; });
for(const c of t7){
  console.log("  T7 "+c[0]+" step="+c[1].step+" u="+c[1].u+" gap="+c[1].gap+" realLabelW="+c[1].realW+" overlap="+c[1].overlap);
  assert("T7 "+c[0]+" 降级标签不重叠", !c[1].overlap, c[1].overlap?("gap "+c[1].gap+" < 真实标签宽 "+c[1].realW+" -> 重叠"):"安全");
}


// 收尾: 结果统计
console.log("FAILURES="+failures);
await browser.close();
process.exit(failures>0?1:0);
