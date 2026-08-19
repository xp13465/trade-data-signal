import { chromium } from 'playwright';
const URL='https://ss.fx8.store/';
const browser = await chromium.launch();
const context = await browser.newContext();
const page = await context.newPage();
let cur={marker:'v1',date:'2026-08-20'};
function payload(){ return JSON.stringify({date:cur.date, news:[{time:'09:00',title:'早盘'+cur.marker},{time:'10:00',title:'要闻'+cur.marker}], upcoming:[]}); }
// 拦截 news + 记录所有 #content 相关
await page.route(/news_digest\.json/, r=>{ console.log('[route]', r.request().url(), '->', cur.marker); return r.fulfill({status:200,contentType:'application/json',body:payload()}); });
// 在页面内挂钩 window.fetch 打印所有含 news 的请求
await page.addInitScript(() => {
  const _f = window.fetch.bind(window);
  window.fetch = (u, o) => { const s=String(u); if(/news|digest/.test(s)) console.log('[fetch]', s); return _f(u,o); };
});
await page.goto(URL,{waitUntil:'domcontentloaded',timeout:60000});
await page.waitForTimeout(4000);
// 第一次 force → v2
cur.marker='v2';
const r1 = await page.evaluate(async()=>{ const nd=await window._loadNewsDigest(true); return {t:nd.news&&nd.news[0]&&nd.news[0].title||'', err:nd.err, len:nd.news&&nd.news.length}; });
console.log('r1(force v2):', JSON.stringify(r1));
// 第二次 force(不应命中 new fetch if cache? no force 必 fetch) → 保持 v2
const r2 = await page.evaluate(async()=>{ const nd=await window._loadNewsDigest(true); return {t:nd.news&&nd.news[0]&&nd.news[0].title||'', err:nd.err, len:nd.news&&nd.news.length}; });
console.log('r2(force again v2):', JSON.stringify(r2));
await browser.close();
