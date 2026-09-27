import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:6000} });
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(25000);
// 找按年窗口增长表
const out = await page.evaluate(() => {
  const all = document.querySelector('.lab-sigkelly-all-group');
  const t = all ? all.innerText : '';
  return t;
});
const i1 = out.indexOf('按年窗口增长');
const i2 = out.indexOf('按年');
console.log('含"按年窗口增长"位置:', i1);
// 打印按年表区域
if (i1 >= 0) console.log(out.slice(i1, i1 + 2600));
await b.close();
