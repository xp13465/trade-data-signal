// P0 补测探索5: 等数据完整后 抓 ①三玩法表全行 ②G/H/I对比表(.gihc)全行 ③全信号表 A/H 行 ④各展示位 182.25/142.68 命中
import { chromium } from 'playwright';
import fs from 'fs';
const out = { console_err: [], gih: [], hits: {} };
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1680, height: 4000 } });
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
// 触发数据完整: 先切近1年再切回全部(探索3发现这样能加载完整 540)
const btn1 = page.locator('.lab-sigkelly-bar button:has-text("近1年")').first();
if (await btn1.count()) { await btn1.click(); await page.waitForTimeout(2500); }
const btnall = page.locator('.lab-sigkelly-bar button:has-text("全部")').first();
if (await btnall.count()) { await btnall.click(); await page.waitForTimeout(5000); }

// 抓三玩法表全部行
const afgTable = page.locator('table.lab-sigkelly-afg-table');
if (await afgTable.count()) {
  out.afg_table = await afgTable.first().innerText();
}
// G/H/I 对比表(ai长线三档对比)
const gihcTable = page.locator('table.lab-sigkelly-advice-table');
if (await gihcTable.count()) {
  out.gihc_advice_table = await gihcTable.first().innerText();
}
// 全信号表 A/H 行
const aRow = page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').first();
const hRow = page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').first();
if (await aRow.count()) { out.a_row = (await aRow.innerText()).replace(/\n+/g,' | '); }
if (await hRow.count()) { out.h_row = (await hRow.innerText()).replace(/\n+/g,' | '); }

// 全页文本搜 182.25/142.68/163.25/224.92
for (const t of ['182.25','142.68','163.25','224.92']) {
  out.hits[t] = await page.evaluate((tt) => {
    const res = [];
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while (n = w.nextNode()) {
      if (n.textContent && n.textContent.includes(tt)) {
        const el = n.parentElement;
        let ctx=[]; let cur=el;
        for (let i=0;i<4&&cur;i++){ ctx.push(cur.tagName+(cur.className?'.'+String(cur.className).split(' ').slice(0,2).join('.'):'')); cur=cur.parentElement; }
        res.push({ text: n.textContent.trim().slice(0,60), ctx: ctx.join(' < ') });
      }
    }
    return res.slice(0,8);
  }, t);
}

out.gih_unique=[...out.gih];
fs.writeFileSync('/tmp/p0-console/p0-probe5.json', JSON.stringify(out, null, 2));
console.log('== 三玩法表 ==');
console.log(out.afg_table);
console.log('== G/H/I advice 表 ==');
console.log(out.gihc_advice_table);
console.log('== 全信号表 A 行 =='); console.log(out.a_row);
console.log('== 全信号表 H 行 =='); console.log(out.h_row);
console.log('== 文本命中 ==');
for (const t of Object.keys(out.hits)) {
  console.log('--', t, '--');
  out.hits[t].forEach(h => console.log(' ', h.text, '|', h.ctx));
}
console.log('== 缺价 ==', out.gih_unique.length, out.gih_unique);
console.log('== console error 条数 ==', out.console_err.filter(c=>c.t==='error').length, 'pageerror', out.console_err.filter(c=>c.t==='pageerror').length);
await b.close();
