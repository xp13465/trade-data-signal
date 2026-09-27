import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:6000} });
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(25000);

async function setPeriod(label) {
  const spans = await page.$$('.lab-sigkelly-periods span');
  for (const s of spans) {
    const t = (await s.innerText()).trim();
    if (t === label) { await s.click(); await page.waitForTimeout(6000); return true; }
  }
  return false;
}
async function setMode(val) {
  await page.selectOption('#lab-kelly-fade-mode-sel', val);
  await page.waitForTimeout(8000);
}
async function readTable() {
  return await page.evaluate(() => {
    const sel = document.getElementById('lab-kelly-fade-mode-caliber');
    const all = document.querySelector('.lab-sigkelly-all-group');
    const t = all ? all.innerText : '';
    // 提取 A 行和 G 行附近数字
    const grab = (line) => {
      const i = t.indexOf(line);
      if (i < 0) return '';
      return t.slice(i, i + 260).replace(/\n/g, ' | ');
    };
    return { mode: sel ? sel.innerText : '', A: grab('A固定10天'), G: grab('G卖出信号'), H: grab('H卖出+追止损') };
  });
}

await setPeriod('全部');
console.log('== 周期切到 全部 ==');
let r = await readTable();
console.log('【S06】模式:', r.mode);
console.log('  A行:', r.A);
console.log('  G行:', r.G);
console.log('  H行:', r.H);

// 切 NEW14
await setMode('new14');
console.log('\n== 切模式 new14 ==');
r = await readTable();
console.log('【NEW14】模式:', r.mode);
console.log('  A行:', r.A);
console.log('  G行:', r.G);
console.log('  H行:', r.H);

// 切回 S06
await setMode('s06');
console.log('\n== 切回 s06 ==');
r = await readTable();
console.log('【S06】模式:', r.mode);
console.log('  A行:', r.A.slice(0,200));
await b.close();
