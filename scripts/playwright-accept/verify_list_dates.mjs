import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1400,height:2200} });
await page.goto('https://ss.fx8.store', { waitUntil:'domcontentloaded', timeout:60000 });
await page.waitForTimeout(9000);
// find signal rows - check what class each sig-item has and date
const rows = await page.locator('.sig-item').count();
console.log('.sig-item 总数=', rows);
// get dates visible in signal list headers
const dates = await page.locator('.sig-day, .sig-date, [class*="sig-date"], [class*="sig-day"]').allTextContents().catch(()=>[]);
console.log('日期表头样例:', dates.slice(0,20));
// any AI建议N anywhere
const okBadge = await page.locator('.sig-poscap-ok').count();
console.log('AI建议N badges 全页=', okBadge);
// capture day labels counts
const dayLabs = await page.locator('[class*="sig-d"], [class*="day-label"], .date-label').allTextContents().catch(()=>[]);
console.log('day labels:', dayLabs.slice(0,30));
await page.screenshot({ path:'/Users/linhuichen/code/trade/scripts/playwright-accept/universe-home-scroll.png', fullPage:true });
await b.close();
