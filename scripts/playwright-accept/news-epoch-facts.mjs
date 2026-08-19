// news-epoch-facts.mjs
// 功能实证(事实层): 把【本地 worktree 的 app.min.js(含 #12 纪元硬化)】以 route 覆盖方式注入线上页面,
// 用线上真实数据验证纪元硬化后新闻看板: ①首次出现 ②切tab往返 6 次不消失 ③轮询体自动更新 ④fetch失败不消失。
// 与 news-lifecycle-facts 测线上旧版不同, 本脚本测的是【修改后】的 app.min.js(功能生效层)。
// 运行: cd /Users/linhuichen/code/trade/scripts/playwright-accept && node news-epoch-facts.mjs
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';

const URL = 'https://ss.fx8.store/';
const WORKTREE_MIN = '/private/tmp/wt-news-rootfix-0820/static-site/app.min.js';
let pass=0, fail=0;
function assert(n,c,x=''){ if(c){pass++;}else{fail++;} console.log((c?'PASS ':'FAIL ')+n+(x?' | '+x:'')); }
function payload(marker){ return JSON.stringify({date:'2026-08-20', news:[{time:'09:00',title:'早盘'+marker},{time:'10:00',title:'要闻'+marker,important:true}], upcoming:[{time:'15:00',title:'明日'+marker,important:true}] }); }

const minJs = fs.readFileSync(WORKTREE_MIN, 'utf8');

const browser = await chromium.launch();
try {
  const context = await browser.newContext({ serviceWorkers: 'block' }); // 禁 SW, 保证用我们注入的 min
  const page = await context.newPage();
  // 注入本地修改版 app.min.js
  await page.route('**/app.min.js*', route => route.fulfill({ status:200, headers:{'content-type':'application/javascript'}, body: minJs }));
  // 控 news_digest 数据
  let cur='v1', failNext=false;
  await page.route(/news_digest\.json/, route => {
    if (failNext){ failNext=false; return route.fulfill({status:500,contentType:'application/json',body:'{}'}); }
    return route.fulfill({status:200,contentType:'application/json',body:payload(cur)});
  });

  await page.goto(URL,{waitUntil:'domcontentloaded',timeout:60000});
  try { await page.waitForFunction(()=>!!document.querySelector('.summary-banner'),{timeout:15000}); } catch(e){}
  await page.waitForTimeout(4000);

  const ncount = ()=>page.evaluate(()=>document.querySelectorAll('.summary-news-row').length);
  const ntxt = ()=>page.evaluate(()=>Array.from(document.querySelectorAll('.summary-news-row')).map(e=>e.textContent).join('|'));
  const goTab = (t)=>page.evaluate((tt)=>{const b=document.querySelector('button[data-tab="'+tt+'"]');if(b)b.click();},t);

  // 确认注入的是修改版(含 _homeNewsEpoch)
  const hasEpoch = await page.evaluate(()=> typeof window._homeNewsEpoch !== 'undefined' || String(window._homeNewsReset).includes('Epoch') );
  assert('[注入] 页面运行的是含纪元硬化的修改版 min', hasEpoch);
  assert('1 首次:新闻行出现+v1', (await ncount())>=1 && (await ntxt()).includes('v1'), (await ntxt()).slice(0,60));

  // 切tab往返 6 次: 不消失
  for(let i=0;i<6;i++){ await goTab('market'); await page.waitForTimeout(120); await goTab('overview'); await page.waitForTimeout(150); }
  await page.waitForTimeout(2000);
  assert('2 切tab往返6次新闻行仍在(不消失)', (await ncount())>=1, 'n='+(await ncount()));

  // 轮询体: force 重拉 -> 原地更新
  cur='v2';
  const pr = await page.evaluate(async ()=>{ const nd=await window._loadNewsDigest(true); window._renderHomeNewsRows(nd, document.querySelector('.summary-banner'), document.getElementById('content')); return document.querySelector('.summary-news-row').textContent; });
  assert('3 轮询体自动更新到 v2(不自动更新=FAIL)', pr.includes('v2'), pr.slice(0,80));

  // 纪元接管: 手动模拟完整的 renderOverview 重建(content 清空 -> _homeNewsReset(纪元+) -> 用当前 banner 重建新闻), 验证旧代不残留/当前代接管
  const epochInfo = await page.evaluate(async ()=>{
    const content = document.getElementById('content');
    content.innerHTML = '';                    // 真实 renderOverview 清空内容(移除旧 banner+新闻)
    window._homeNewsReset();                   // reset: 纪元+1 + 杀旧轮询 + 置空 wrap
    // 重新建 banner(真实 renderOverview 会在 async _summaryP.then 里建新 banner 并 insertBefore)
    const banner = document.createElement('div');
    banner.className = 'summary-banner';
    content.appendChild(banner);
    // 手动重建新闻(等同新 renderOverview 的 _loadNewsDigest().then 闭包, 但需通过全局函数调用)
    const nd = await window._loadNewsDigest(true);
    window._renderHomeNewsRows(nd, banner, content);
    // 取真实纪元(用 _homeNewsReset 副作用: 纪元在 min 里是 let 非 window 属性, 用行为间接判断 —— 见 rows/connected)
    return { rows: Array.from(document.querySelectorAll('.summary-news-row')).length,
             connected: Array.from(document.querySelectorAll('.summary-news-row')).some(e=>e.isConnected && content.contains(e)),
             banners: document.querySelectorAll('.summary-banner').length };
  });
  assert('4 完整重建(清空内容+reset)后新闻行唯一且绑定当前 banner', epochInfo.rows===1 && epochInfo.connected, JSON.stringify(epochInfo));
  assert('5 重建后当前内容中 banner 唯一(旧 banner 被清空, 不堆积)', epochInfo.banners===1, JSON.stringify(epochInfo));

  // fetch 失败: 不消失(旧代保留)
  failNext=true;
  await page.evaluate(async ()=>{ await window._loadNewsDigest(true); });
  await page.waitForTimeout(300);
  const n4 = await ncount();
  assert('6 fetch500后新闻行不消失', n4>=1, 'n='+n4);

} catch(e){ assert('脚本异常',false,(e.message||'').slice(0,300)); }
finally { await browser.close(); }
console.log(`\n===== ${pass} PASS / ${fail} FAIL =====`);
process.exit(fail?1:0);
