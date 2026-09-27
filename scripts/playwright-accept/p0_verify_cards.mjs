import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1600,height:4000} });
const errs=[];
page.on('pageerror', e => errs.push(String(e)));
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(26000);
// 全信号表卡 A 档数字
const allGroup = page.locator('.lab-sigkelly-all-group').first();
if (await allGroup.count() > 0) {
  const txt = await allGroup.innerText();
  // 打印 A 模式行附近
  const lines = txt.split('\n');
  console.log('===== 全信号表(前80行) =====');
  console.log(lines.slice(0, 80).join('\n'));
}
console.log('JS errors:', errs.length ? errs.slice(0,5) : '(无)');
await b.close();
