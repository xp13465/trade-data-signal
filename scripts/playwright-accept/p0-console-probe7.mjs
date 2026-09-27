// P0 补测探索7: ①切费率档看 A/H 行变化 ②H 模式在各费率/周期下找 182.25 ③G/H/I (ai长线)弹窗
import { chromium } from 'playwright';
import fs from 'fs';
const out = { console_err: [], gih: [], feeSnap: {} };
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
for (let i = 0; i < 60; i++) {
  if (await page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').count() > 0) break;
  await page.waitForTimeout(2000);
}
// 触发完整数据
for (const p of ['近1年', '近3年', '全部']) {
  const btn = page.locator('.lab-sigkelly-bar button:has-text("' + p + '")').first();
  if (await btn.count()) { await btn.click(); await page.waitForTimeout(3000); }
}
for (let i = 0; i < 30; i++) {
  const a = await page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').first().innerText().catch(() => '');
  if (a.includes('540')) break;
  await page.waitForTimeout(2000);
}

async function snapA(l) {
  const aRow = page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').first();
  const hRow = page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').first();
  return {
    label: l,
    a: (await aRow.count() ? (await aRow.innerText()).replace(/\n+/g,' | ') : null),
    h: (await hRow.count() ? (await hRow.innerText()).replace(/\n+/g,' | ') : null),
  };
}

// 默认费率
out.feeSnap['默认'] = await snapA('默认');

// 费率档按钮
const feeBtns = page.locator('.lab-sigkelly-fee-btn');
const fn = await feeBtns.count();
out.fee_btn_count = fn;
if (fn) {
  for (let i = 0; i < fn; i++) {
    const txt = (await feeBtns.nth(i).innerText()).trim();
    out.fee_btn_texts = out.fee_btn_texts || [];
    out.fee_btn_texts.push(txt);
  }
  // 逐个费率档点击测试
  for (let i = 0; i < fn && i < 6; i++) {
    const label = out.fee_btn_texts[i];
    await feeBtns.nth(i).click().catch(() => {});
    await page.waitForTimeout(4000);
    out.feeSnap[label] = await snapA(label);
  }
}

// G/H/I ai长线弹窗: 找"ai长线"开关
out.gih_on = await page.evaluate(() => !!document.querySelector('.lab-sigkelly-gih-toggle input, .lab-sigkelly-gih-toggle')).catch(() => false);
out.gihOnState = await page.evaluate(() => {
  const el = document.querySelector('.lab-sigkelly-gih-toggle input');
  return el ? el.checked : null;
}).catch(() => null);

fs.writeFileSync('/tmp/p0-console/p0-probe7.json', JSON.stringify(out, null, 2));
console.log('fee btn texts:', out.fee_btn_texts);
for (const k of Object.keys(out.feeSnap)) {
  console.log('== fee:', k, '==');
  console.log('  A:', out.feeSnap[k].a);
  console.log('  H:', out.feeSnap[k].h);
}
console.log('gih toggle count:', out.gih_on, 'state:', out.gihOnState);
console.log('缺价:', out.gih.length, out.gih);
console.log('console error:', out.console_err.filter(c=>c.t==='error').length);
await b.close();
