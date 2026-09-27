import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:4000} });
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(20000);
const dom = await page.evaluate(() => {
  const el = document.querySelector('.lab-sigkelly-periods');
  return el ? el.outerHTML.slice(0, 1200) : '(none)';
});
console.log(dom);
await b.close();
