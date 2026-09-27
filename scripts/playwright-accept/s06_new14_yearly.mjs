import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:9000} });
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(25000);
await page.click('.lab-sigkelly-period-btn[data-period="all"]');
await page.waitForTimeout(15000);
await page.selectOption('#lab-kelly-fade-mode-sel', 'new14');
await page.waitForTimeout(15000);
const t = await page.evaluate(() => {
  const all = document.querySelector('.lab-sigkelly-all-group');
  return all ? all.innerText : '';
});
// 按年表(全部周期下 G 模式)
const y = t.indexOf('按年窗口增长');
const tail = t.slice(y, y + 2600);
const iStart = tail.indexOf('当前[');
console.log('【NEW14 · G模式按年表】');
console.log(iStart >= 0 ? tail.slice(iStart, iStart + 1800) : tail.slice(0, 1500));
// 主表 A 行
const a0 = t.indexOf('A固定10天');
console.log('\n【NEW14 · A行(全部)】', t.slice(a0, a0 + 330).replace(/\n/g,' | '));
await b.close();
