import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:9000} });
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(25000);

async function setPeriod(per) {
  await page.click(`.lab-sigkelly-period-btn[data-period="${per}"]`);
  await page.waitForTimeout(15000);
}
async function setMode(val) {
  await page.selectOption('#lab-kelly-fade-mode-sel', val);
  await page.waitForTimeout(12000);
}
async function getTxt() {
  return await page.evaluate(() => {
    const all = document.querySelector('.lab-sigkelly-all-group');
    return all ? all.innerText : '(none)';
  });
}
function cut(t, w) {
  const i = t.indexOf('A固定10天');
  return (i >= 0 ? t.slice(i, i + w) : t.slice(0, w));
}

await setPeriod('all');
let t = await getTxt();
console.log('【S06 · 全部周期】');
console.log(cut(t, 1400));
console.log('...按年表位置:', t.indexOf('按年窗口增长'));

await setMode('new14');
t = await getTxt();
console.log('\n【NEW14 · 全部周期】');
console.log(cut(t, 1400));

await setMode('s06');
console.log('\n(已恢复 s06)');
await b.close();
