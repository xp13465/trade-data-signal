import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:9000} });
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(25000);
await page.click('.lab-sigkelly-period-btn[data-period="all"]');
await page.waitForTimeout(15000);

async function readAll() {
  return await page.evaluate(() => {
    const all = document.querySelector('.lab-sigkelly-all-group');
    const t = all ? all.innerText : '';
    const y = t.indexOf('按年窗口增长');
    return { main: t.slice(0, y>0?y:t.length), yearly: y>0 ? t.slice(y, y+3000) : '(no yearly table)' };
  });
}

async function setMode(val) {
  await page.selectOption('#lab-kelly-fade-mode-sel', val);
  await page.waitForTimeout(12000);
}

let r = await readAll();
console.log('===== S06 全部周期 主表(A/F/G行) =====');
console.log(r.main.slice(0, 700));
let y0 = r.yearly;
console.log('\n===== S06 按年窗口表(前2200字) =====');
console.log(y0.slice(0, 2200));

await setMode('new14');
r = await readAll();
console.log('\n\n===== NEW14 全部周期 主表(A/F/G行) =====');
console.log(r.main.slice(0, 700));
console.log('\n===== NEW14 按年窗口表(前1800字) =====');
console.log(r.yearly.slice(0, 1800));

await setMode('s06');
console.log('\n(已恢复 s06)');
await b.close();
