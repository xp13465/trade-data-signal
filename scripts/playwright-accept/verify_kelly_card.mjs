import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1500,height:3000} });
const fetched = {};
page.on('response', r => { if (r.status()===200){ const u=r.url(); ['signal_kelly_trades.json','signal_kelly_backtest.json'].forEach(f=>{ if(u.includes(f)) fetched[f]=true; }); } });
const errs=[];
page.on('pageerror', e => errs.push(String(e)));
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(14000);
console.log('signal_kelly_trades.json fetched200:', !!fetched['signal_kelly_trades.json']);
console.log('signal_kelly_backtest.json fetched200:', !!fetched['signal_kelly_backtest.json']);
// kelly section root
const kellyRoot = await page.locator('.lab-sigkelly, .lab-sigkelly-quadrants, [class*="sigkelly"]').count();
console.log('[class*=sigkelly] 节点数:', kellyRoot);
// 凯利卡文字
const bodyText = await page.evaluate(()=>document.body.innerText.slice(0,4000));
const hasKellyWord = bodyText.includes('信号凯利回测') || bodyText.includes('半凯利') || bodyText.includes('凯利');
console.log('页面含凯利文案:', hasKellyWord);
// capture
await page.screenshot({ path:'/Users/linhuichen/code/trade/scripts/playwright-accept/kelly-card.png', fullPage:false });
console.log('JS errors:', errs.length ? errs : '(无)');
await b.close();
