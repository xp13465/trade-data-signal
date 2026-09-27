import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:5000} });
const page = await ctx.newPage();
await page.route('**/*kelly_mode_s06_state*', r => r.abort('failed'));
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(22000);
const t = await page.evaluate(() => {
  const all = document.querySelector('.lab-sigkelly-all-group');
  const x = all ? all.innerText : '';
  const a = x.indexOf('A固定10天');
  const g = x.indexOf('G卖出信号');
  return { A: a>=0 ? x.slice(a, a+300) : '', G: g>=0 ? x.slice(g, g+300) : '' };
});
console.log('快照全失效(全部fail-open) 近1年:');
console.log('A:', t.A.replace(/\n/g,' | '));
console.log('G:', t.G.replace(/\n/g,' | '));
await b.close();
