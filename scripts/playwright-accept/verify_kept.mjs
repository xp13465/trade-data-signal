import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1400,height:3000} });
await page.goto('https://ss.fx8.store', { waitUntil:'domcontentloaded', timeout:60000 });
await page.waitForTimeout(10000);
const kept = await page.locator('.sig-poscap-kept').count();
const excl = await page.locator('.sig-poscap-excluded').count();      // 当日已满
const okB = await page.locator('.sig-poscap-ok').count();              // AI建议N
const fullB = await page.locator('.sig-poscap-full').count();          // 当日已满 badge
console.log('.sig-poscap-kept(进K行) =', kept);
console.log('.sig-poscap-excluded(超K行) =', excl);
console.log('.sig-poscap-ok(AI建议N) =', okB);
console.log('.sig-poscap-full(当日已满) =', fullB);
// dump all rows with their texts+badges on first few dates
const items = await page.locator('.sig-item').count();
console.log('.sig-item total =', items);
// check if any sig-poscap scope wrapper shows kept rows
await b.close();
