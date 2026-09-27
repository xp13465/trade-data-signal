// P0 补测探索3: 三玩法表(lab-sigkelly-afg-table)全量 + G/H/I对比表(.gihc-val) + 逐周期 A/H 行 rmh 对账
import { chromium } from 'playwright';
import fs from 'fs';

const out = { periods: {}, console_err: [], gih: [] };
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
// 等渲染完成
for (let i = 0; i < 60; i++) {
  if (await page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').count() > 0) break;
  await page.waitForTimeout(2000);
}
await page.waitForTimeout(3000); // 等 K 评级动态重算完成

async function snap(periodName) {
  // 三玩法表 A/F/J/G 行
  const afg = page.locator('.lab-sigkelly-afg-table tr.lab-sigkelly-trade-row').first().locator('xpath=ancestor::table[@class="lab-sigkelly-table lab-sigkelly-afg-table"]');
  let afgRows = {};
  const rows = page.locator('table.lab-sigkelly-afg-table tr.lab-sigkelly-trade-row');
  const n = await rows.count();
  for (let i = 0; i < n; i++) {
    const m = await rows.nth(i).getAttribute('data-mode');
    const txt = (await rows.nth(i).innerText()).replace(/\n+/g, ' | ');
    afgRows[m] = txt;
  }
  // 全信号表 all 卡 A/H 行
  const aRow = page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').first();
  const hRow = page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').first();
  const a = await aRow.count() ? (await aRow.innerText()).replace(/\n+/g, ' | ') : null;
  const h = await hRow.count() ? (await hRow.innerText()).replace(/\n+/g, ' | ') : null;
  // G/H/I 对比表(ai长线对比表): .lab-sigkelly-gihc-* 行
  let gihc = {};
  const gtrs = page.locator('tr.lab-sigkelly-gihc-tr');
  const gn = await gtrs.count();
  for (let i = 0; i < gn; i++) {
    const txt = (await gtrs.nth(i).innerText()).replace(/\n+/g, ' | ');
    const m = (await gtrs.nth(i).getAttribute('data-mode')) || ('row' + i);
    gihc[m] = txt;
  }
  out.periods[periodName] = { afgRows, a, h, gihc };
}

await snap('all_初始');
// 切 近1年
const btn1 = page.locator('.lab-sigkelly-bar button:has-text("近1年")').first();
if (await btn1.count()) { await btn1.click(); await page.waitForTimeout(3000); await snap('y1'); }
// 切 近3年
const btn3 = page.locator('.lab-sigkelly-bar button:has-text("近3年")').first();
if (await btn3.count()) { await btn3.click(); await page.waitForTimeout(3000); await snap('y3'); }
// 还原全部
const btna = page.locator('.lab-sigkelly-bar button:has-text("全部")').first();
if (await btna.count()) { await btna.click(); await page.waitForTimeout(3000); await snap('all_还原'); }

out.gih_unique = [...out.gih];
out.console_err_unique = [...new Set(out.console_err.map(c => c.t + '|' + c.text))];
fs.writeFileSync('/tmp/p0-console/p0-probe3.json', JSON.stringify(out, null, 2));
console.log('=== 三玩法表(all初始) ===');
console.log(JSON.stringify(out.periods['all_初始'].afgRows, null, 1));
console.log('=== G/H/I 对比表(all初始) ===');
console.log(JSON.stringify(out.periods['all_初始'].gihc, null, 1));
console.log('=== 全信号表 A/H 行各周期 ===');
for (const p of ['all_初始','y1','y3','all_还原']) {
  if (!out.periods[p]) continue;
  console.log('--', p, '--');
  const t = out.periods[p];
  // 提取数字
  const join = (s) => s ? s.split('\t').join(' | ') : null;
  console.log('A:', join(t.a));
  console.log('H:', join(t.h));
}
console.log('=== 缺价笔数 ===', out.gih_unique.length, out.gih_unique);
console.log('=== console 错误去重 ===');
out.console_err_unique.forEach(c => console.log(c.slice(0, 200)));
await b.close();
