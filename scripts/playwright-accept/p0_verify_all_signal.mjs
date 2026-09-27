import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1600,height:3000} });
const fetched = {};
page.on('response', r => { if (r.status()===200){ const u=r.url(); if(u.includes('signal_kelly_trades.json')) fetched['trades_full']=true; if(u.includes('signal_kelly_trades_parts/t')) fetched['t_shard']=(fetched['t_shard']||0)+1; if(u.includes('kelly_mode_s06_state.json')) fetched['s06']=true; if(u.includes('signal_kelly_backtest.json')) fetched['backtest']=true; } });
const errs=[];
page.on('pageerror', e => errs.push(String(e)));
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(22000);
console.log('fetch trades_full:', !!fetched['trades_full'], ' t_shard:', fetched['t_shard'], ' s06:', !!fetched['s06'], ' backtest:', !!fetched['backtest']);
// 等待全信号表渲染
await page.waitForTimeout(5000);
// 抓全信号表区块文字
const sel = '.lab-sigkelly-all-group';
const cnt = await page.locator(sel).count();
console.log('all-group count:', cnt);
if (cnt > 0) {
  const txt = await page.locator(sel).first().innerText();
  console.log('===== 全信号表区块文字 =====');
  console.log(txt.slice(0, 3000));
}
console.log('JS errors:', errs.length ? errs.slice(0,5) : '(无)');
await page.screenshot({ path:'/tmp/p0_all_signal.png', fullPage:false });
await b.close();
