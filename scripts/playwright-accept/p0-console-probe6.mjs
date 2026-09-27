// P0 补测探索6: 触发完整数据后 逐 K 档抓 全信号表 A/H 行 + 三玩法表 + 总建议行, 找 H=182.25
import { chromium } from 'playwright';
import fs from 'fs';
const out = { console_err: [], gih: [], ksnap: {} };
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1680, height: 5000 } });
const page = await ctx.newPage();
page.on('console', (msg) => { if (msg.type() === 'error' || msg.type() === 'warning') {
  const t = msg.text();
  if (t.includes('__gih_missing_px_')) {
    const mm = t.match(/etf_code=(\S+)\s+buy_date=(\S+)\s+force_date=(\S+)/);
    const key = mm ? `${mm[1]}|${mm[2]}|${mm[3]}` : t;
    if (!out.gih.includes(key)) out.gih.push(key);
  }
  out.console_err.push({ t: msg.type(), text: t });
}});
page.on('pageerror', (e) => out.console_err.push({ t: 'pageerror', text: String(e) }));
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
// 等初次渲染
for (let i = 0; i < 60; i++) {
  if (await page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').count() > 0) break;
  await page.waitForTimeout(2000);
}
// 切周期触发完整数据
for (const p of ['近1年', '近3年', '全部']) {
  const btn = page.locator('.lab-sigkelly-bar button:has-text("' + p + '")').first();
  if (await btn.count()) { await btn.click(); await page.waitForTimeout(4000); }
}
// 等 A 行 n=540
for (let i = 0; i < 30; i++) {
  const a = await page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').first().innerText().catch(() => '');
  if (a.includes('540')) break;
  await page.waitForTimeout(2000);
}

async function snapK(kname) {
  const aRow = page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').first();
  const hRow = page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').first();
  const a = await aRow.count() ? (await aRow.innerText()).replace(/\n+/g,' | ') : null;
  const h = await hRow.count() ? (await hRow.innerText()).replace(/\n+/g,' | ') : null;
  // 三玩法表全部文本
  const afg = page.locator('.lab-sigkelly-afg-realtime').first();
  const afgText = await afg.count() ? (await afg.innerText()).replace(/\n+/g,' | ').slice(0, 1500) : null;
  // 总建议行(.lab-sigkelly-advice-hl 里的"总建议")
  let advice = null;
  const adv = page.locator('tr.lab-sigkelly-advice-hl').first();
  if (await adv.count()) advice = (await adv.innerText()).replace(/\n+/g,' | ').slice(0, 1200);
  out.ksnap[kname] = { a, h, afgText, advice };
  console.log(`== ${kname} ==`);
  console.log('A:', a);
  console.log('H:', h);
  console.log('afg:', afgText);
  console.log('advice:', advice);
}

// K=1 初始(完整数据)
await snapK('k1_full');

// 逐 K 档
for (const k of ['3','2','4']) {
  const btn = page.locator(`.lab-sigkelly-kbtn[data-k="${k}"]`).first();
  if (await btn.count()) { await btn.click(); await page.waitForTimeout(4000); await snapK('k'+k); }
}
// 回 K=1
const btn1 = page.locator('.lab-sigkelly-kbtn[data-k="1"]').first();
if (await btn1.count()) { await btn1.click(); await page.waitForTimeout(3000); }

// K 评级表 hoverpop(完整数据下)
const posTrig = page.locator('.lab-sigkelly-posrate').first();
if (await posTrig.count()) {
  await posTrig.hover().catch(() => {});
  await page.waitForTimeout(800);
  const table = page.locator('.lab-sigkelly-posrate-table');
  if (await table.count()) out.krating = await table.innerText();
}

out.gih_unique=[...out.gih];
fs.writeFileSync('/tmp/p0-console/p0-probe6.json', JSON.stringify(out, null, 2));
console.log('== K 评级表(完整) ==');
console.log(out.krating);
console.log('== 缺价 ==', out.gih_unique.length, out.gih_unique);
console.log('== console err 总数 ==', out.console_err.filter(c=>c.t==='error').length);
await b.close();
