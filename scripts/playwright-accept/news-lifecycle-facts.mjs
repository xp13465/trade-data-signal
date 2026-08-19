// news-lifecycle-facts.mjs
// 功能实证脚本(事实层断言,不判断观感): 线上首页新闻看板三个反复复发症状的实证验证。
// 因全局函数(window._loadNewsDigest/_renderHomeNewsRows/_startHomeNewsPoll/_homeNewsReset)在线上可用,
// 可精确驱动"轮询体"与"重建竞争"做功能生效层断言,不依赖 5min 轮询等久。
// 运行: cd /Users/linhuichen/code/trade/scripts/playwright-accept && node news-lifecycle-facts.mjs
import { chromium } from 'playwright';

const URL = 'https://ss.fx8.store/';
let pass = 0, fail = 0;
function assert(name, cond, extra='') { if(cond){pass++;} else {fail++;} console.log((cond?'PASS ':'FAIL ')+name+(extra?' | '+extra:'')); }

function newsPayload(date, marker) {
  return JSON.stringify({ date, news:[{time:'09:00',title:'早盘'+marker},{time:'10:00',title:'盘中要闻'+marker,important:true}], upcoming:[{time:'15:00',title:'明日'+marker,important:true}] });
}

const browser = await chromium.launch();
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  let cur = { marker:'v1', date:'2026-08-20' };
  let failNext = false;
  await page.route(/news_digest\.json/, route => {
    console.log('[route] URL=', route.request().url());
    if (failNext) { failNext = false; console.log('[route] -> 500'); return route.fulfill({status:500, contentType:'application/json', body:'{}'}); }
    console.log('[route] -> ', cur.marker);
    return route.fulfill({status:200, contentType:'application/json', body:newsPayload(cur.date, cur.marker)});
  });

  await page.goto(URL, { waitUntil:'domcontentloaded', timeout:60000 });
  await page.waitForTimeout(4000);

  const newsText = () => page.evaluate(() => Array.from(document.querySelectorAll('.summary-news-row')).map(e=>e.textContent).join('|'));
  const newsCount = () => page.evaluate(() => document.querySelectorAll('.summary-news-row').length);
  const goTab = (tab) => page.evaluate((t)=>{const b=document.querySelector('button[data-tab="'+t+'"]'); if(b) b.click();}, tab);

  assert('语义:首页在 overview', await page.evaluate(()=>!!document.querySelector('.summary-banner')));
  let n = await newsCount();
  let t = await newsText();
  assert('首次:新闻行出现+v1', n>=1 && t.includes('v1'), 'n='+n+' '+t.slice(0,60));

  // ===== 测试P: 轮询体(force重拉+原地渲染)不重建 → 验证"自动更新" =====
  cur.marker='v2';
  const pollResult = await page.evaluate(async () => {
    const nd = await window._loadNewsDigest(true);          // 轮询体第一步: 强破缓存重拉
    window._renderHomeNewsRows(nd, document.querySelector('.summary-banner'), document.getElementById('content')); // 轮询体第二步: 原地更新
    return { text: document.querySelector('.summary-news-row').textContent };
  });
  console.log('[P] poll inline update text:', (pollResult.text||'').slice(0,80));
  assert('P1 轮询原地更新到 v2(看板不刷新路径)', (pollResult.text||'').includes('v2'), pollResult.text.slice(0,80));

  // ===== 测试S: 快速连切 tab×6 压力(重建竞争) → 验"消失" =====
  for (let i=0;i<6;i++){ await goTab('market'); await page.waitForTimeout(120); await goTab('overview'); await page.waitForTimeout(150); }
  await page.waitForTimeout(2500);
  n = await newsCount(); t = await newsText();
  console.log('[S] after 6x rapid tab-switch news rows=', n, 'text=', t.slice(0,80));
  assert('S1 快速连切6次后新闻行仍在(不消失)', n>=1, 'n='+n);
  assert('S2 快速连切后仍能显示最新数据(仍 v2)', t.includes('v2'), t.slice(0,80));

  // ===== 测试D: 采集一瞬失败(500)→ 新闻不应消失; 恢复后自动更新 =====
  failNext = true;
  let before = await newsText();
  cur.marker='v3';
  const ndRun = await page.evaluate(async ()=> { const a = await window._loadNewsDigest(true); return {a0:a.news&&a.news[0]&&a.news[0].title, aerr:a.err, len:a.news&&a.news.length}; });
  console.log('[D] after 500, _loadNewsDigest(true) returned:', JSON.stringify(ndRun));
  await page.evaluate(async ()=> window._renderHomeNewsRows((await window._loadNewsDigest(true)), document.querySelector('.summary-banner'), document.getElementById('content')) );
  await page.waitForTimeout(400);
  n = await newsCount(); t = await newsText();
  assert('D1 fetch 失败后新闻行不消失(保留旧内容)', n>=1 && t.includes('v2'), 'n='+n+' '+t.slice(0,60));
  // 恢复 v3
  cur.marker='v3';
  await page.evaluate(async ()=> { const nd = await window._loadNewsDigest(true); window._renderHomeNewsRows(nd, document.querySelector('.summary-banner'), document.getElementById('content')); });
  await page.waitForTimeout(400);
  t = await newsText();
  assert('D2 恢复后自动更新到 v3', t.includes('v3'), t.slice(0,80));

} catch (e) {
  assert('脚本异常', false, (e.message||'').slice(0,300));
} finally {
  await browser.close();
}
console.log(`\n===== ${pass} PASS / ${fail} FAIL =====`);
process.exit(fail?1:0);
