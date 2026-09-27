import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:9000} });
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(25000);

async function getY1Main() {
  return await page.evaluate(() => {
    const all = document.querySelector('.lab-sigkelly-all-group');
    const t = all ? all.innerText : '';
    const a = t.indexOf('A固定10天');
    const g = t.indexOf('G卖出信号');
    return { A: t.slice(a, a+300), G: t.slice(g, g+300) };
  });
}
async function setMode(val) {
  await page.selectOption('#lab-kelly-fade-mode-sel', val);
  await page.waitForTimeout(12000);
}
let r = await getY1Main();
console.log('【S06 近1年】');
console.log('A:', r.A.replace(/\n/g,' | ').slice(0,300));
console.log('G:', r.G.replace(/\n/g,' | ').slice(0,300));
await setMode('new14');
r = await getY1Main();
console.log('\n【NEW14 近1年】');
console.log('A:', r.A.replace(/\n/g,' | ').slice(0,300));
console.log('G:', r.G.replace(/\n/g,' | ').slice(0,300));
await setMode('s06');
console.log('\n(已恢复 s06)');
await b.close();
