import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1400,height:4000} });
// seed tds_poscap on:true k:1 before app loads (via addInitScript running before page scripts)
await page.addInitScript(() => {
  localStorage.setItem('tds_poscap', JSON.stringify({ on:true, k:1 }));
});
await page.goto('https://ss.fx8.store', { waitUntil:'domcontentloaded', timeout:60000 });
await page.waitForTimeout(10000);
const okB = await page.locator('.sig-poscap-ok').count();
const kept = await page.locator('.sig-poscap-kept').count();
const full = await page.locator('.sig-poscap-full').count();
console.log('.sig-poscap-ok(AI建议N)=', okB, '| .sig-poscap-kept=', kept, '| .sig-poscap-full(当日已满)=', full);
const okTexts = await page.locator('.sig-poscap-ok').allTextContents().catch(()=>[]);
console.log('AI建议N 文本样例:', okTexts.slice(0,10).join(' | '));
const fullTexts = await page.locator('.sig-poscap-full').allTextContents().catch(()=>[]);
console.log('当日已满 文本样例:', fullTexts.slice(0,5).join(' | '));
// capture kept badge context rows
const ctx = await page.evaluate(() => {
  const out=[];
  document.querySelectorAll('.sig-item.sig-poscap-kept').forEach(it=>{
    out.push((it.textContent||'').replace(/\s+/g,' ').trim().slice(0,60));
  });
  return out;
});
console.log('kept(AI建议) 标的:', ctx.slice(0,10));
await page.screenshot({ path:'/Users/linhuichen/code/trade/scripts/playwright-accept/universe-home-k1.png', fullPage:true });
await b.close();
