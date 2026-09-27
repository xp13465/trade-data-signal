// P0 补测探索4: ①无痕 localStorage 键是什么 ②切 K=3 后全信号表 A/H 行 + 三玩法表 A 行 ③K档评级表
import { chromium } from 'playwright';
import fs from 'fs';

const out = { ls: null, k1: {}, k3: {}, k2: {}, k4: {}, console_err: [], gih: [] };
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1680, height: 4000 } });
const page = await ctx.newPage();

page.on('console', (msg) => {
  if (msg.type() === 'error' || msg.type() === 'warning') {
    const t = msg.text();
    if (t.includes('__gih_missing_px_')) {
      const mm = t.match(/etf_code=(\S+)\s+buy_date=(\S+)\s+force_date=(\S+)/);
      const key = mm ? `${mm[1]}|${mm[2]}|${mm[3]}` : t;
      if (!out.gih.includes(key)) out.gih.push(key);
    }
    out.console_err.push({ t: msg.type(), text: t });
  }
});
page.on('pageerror', (e) => out.console_err.push({ t: 'pageerror', text: String(e) }));

await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });

// ① localStorage 键值(未注入任何存储, 页面自己写的)
out.ls = await page.evaluate(() => {
  const o = {};
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i);
    o[k] = localStorage.getItem(k);
  }
  return o;
});

// ② 等全信号表渲染(数据完整 = n>100 才算加载完)
async function waitFull() {
  for (let i = 0; i < 90; i++) {
    const aRow = page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').first();
    if (await aRow.count()) {
      const txt = await aRow.innerText();
      if (txt.includes('540') || txt.includes('317')) return true;
    }
    await page.waitForTimeout(2000);
  }
  return false;
}
const full = await waitFull();
out.full_loaded = full;

async function snap(kname) {
  const aRow = page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').first();
  const hRow = page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').first();
  const a = await aRow.count() ? (await aRow.innerText()).replace(/\n+/g, ' | ') : null;
  const h = await hRow.count() ? (await hRow.innerText()).replace(/\n+/g, ' | ') : null;
  // 三玩法表 A 行
  let afgA = null;
  const afgRows = page.locator('table.lab-sigkelly-afg-table tr.lab-sigkelly-trade-row');
  for (let i = 0; i < await afgRows.count(); i++) {
    if ((await afgRows.nth(i).getAttribute('data-mode')) === 'A') {
      afgA = (await afgRows.nth(i).innerText()).replace(/\n+/g, ' | ');
      break;
    }
  }
  out[kname] = { a, h, afgA };
  console.log(`== ${kname} ==`);
  console.log('A:', a);
  console.log('H:', h);
  console.log('afg A:', afgA);
}

// K=1 初始
await snap('k1_初始');

// 切换 K 档: 找 K 档按钮(lab-sigkelly-kbtn 带 data-k?)
const kbtns = page.locator('.lab-sigkelly-kbtn');
const kn = await kbtns.count();
console.log('kbtn count:', kn);
if (kn) {
  for (let i = 0; i < kn; i++) {
    const k = await kbtns.nth(i).getAttribute('data-k');
    console.log('  kbtn', i, 'data-k=', k, 'text=', (await kbtns.nth(i).innerText()).trim());
  }
  // 点 K=3
  const btn3 = page.locator('.lab-sigkelly-kbtn[data-k="3"]').first();
  if (await btn3.count()) {
    await btn3.click();
    await page.waitForTimeout(3500);
    await snap('k3');
  }
  // 点 K=2
  const btn2 = page.locator('.lab-sigkelly-kbtn[data-k="2"]').first();
  if (await btn2.count()) {
    await btn2.click();
    await page.waitForTimeout(3500);
    await snap('k2');
  }
  // 点 K=4
  const btn4 = page.locator('.lab-sigkelly-kbtn[data-k="4"]').first();
  if (await btn4.count()) {
    await btn4.click();
    await page.waitForTimeout(3500);
    await snap('k4');
  }
  // 回 K=1
  const btn1 = page.locator('.lab-sigkelly-kbtn[data-k="1"]').first();
  if (await btn1.count()) { await btn1.click(); await page.waitForTimeout(3500); await snap('k1_还原'); }
}

// K 评级表 hoverpop
const posTrig = page.locator('.lab-sigkelly-posrate').first();
if (await posTrig.count()) {
  await posTrig.hover().catch(() => {});
  await page.waitForTimeout(800);
  const pop = page.locator('.lab-sigkelly-posrate-pop-wrap').first();
  const table = pop.locator('.lab-sigkelly-posrate-table');
  if (await table.count()) out.krating = await table.innerText();
}

out.gih_unique = [...out.gih];
out.console_err_unique = [...new Set(out.console_err.map(c => c.t + '|' + c.text))];
fs.writeFileSync('/tmp/p0-console/p0-probe4.json', JSON.stringify(out, null, 2));
console.log('== localStorage ==', JSON.stringify(out.ls, null, 1));
console.log('== full_loaded ==', full);
console.log('== K 评级表 ==');
console.log(out.krating);
console.log('== 缺价笔数 ==', out.gih_unique.length, out.gih_unique);
console.log('== console 错误去重 ==');
out.console_err_unique.forEach(c => console.log(c.slice(0, 160)));
await b.close();
