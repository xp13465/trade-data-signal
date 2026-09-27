// P0 补测: 无痕浏览器(零localStorage) 打开线上 ss.fx8.store 信号凯利回测页
// 抓取: ①console 完整报错清单(含 __gih_missing_px_) ②全信号表 A/H 档实际渲染数字 ③hoverpop K档评级表
import { chromium } from 'playwright';

const out = {
  ts: new Date().toISOString(),
  url: null,
  localStorageLen: null,
  console: [],
  pageerrors: [],
  allGroup: null,
  a_rmh: null, h_rmh: null,
  a_row: null, h_row: null,
  posrate_table: null,
  gih_missing: [],      // 解析后的 __gih_missing_px_ 参数
};

const b = await chromium.launch({ headless: true });
// 无痕: 不传 storageState/persistent context = 全新干净 profile, 零 localStorage
const ctx = await b.newContext({ viewport: { width: 1680, height: 4000 } });
const page = await ctx.newPage();

// 全程监听 console(所有类型) + pageerror
page.on('console', (msg) => {
  const t = msg.type();
  if (t === 'error' || t === 'warning') {
    const loc = msg.location();
    out.console.push({
      type: t,
      text: msg.text(),
      url: loc.url || null,
      line: loc.lineNumber || null,
    });
    // 解析 __gih_missing_px_ 参数
    if (msg.text().includes('__gih_missing_px_')) {
      const m = msg.text().match(/etf_code=(\S+)\s+buy_date=(\S+)\s+force_date=(\S+)/);
      out.gih_missing.push({
        raw: msg.text(),
        etf_code: m ? m[1] : null,
        buy_date: m ? m[2] : null,
        force_date: m ? m[3] : null,
      });
    }
  }
});
page.on('pageerror', (e) => {
  out.pageerrors.push(String(e));
});

// 打开线上页面
out.url = 'https://ss.fx8.store/#lab?sub=sigkelly';
await page.goto(out.url, { waitUntil: 'domcontentloaded', timeout: 120000 });
// 验证零 localStorage
out.localStorageLen = await page.evaluate(() => localStorage.length);

// 等待全信号表 A/H 行渲染出来(初次渲染可能需要数据加载)
let aFound = false, hFound = false;
const t0 = Date.now();
for (let i = 0; i < 60; i++) {
  if (aFound && hFound) break;
  if (!aFound) {
    aFound = await page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').count() > 0;
  }
  if (!hFound) {
    hFound = await page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').count() > 0;
  }
  if (!(aFound && hFound)) await page.waitForTimeout(2000);
}
out.render_wait_ms = Date.now() - t0;

// 抓全信号表 A/H 行完整文本
const aRow = page.locator('.lab-sigkelly-all-group tr[data-mode="A"]').first();
const hRow = page.locator('.lab-sigkelly-all-group tr[data-mode="H"]').first();
if (await aRow.count()) {
  out.a_row = (await aRow.innerText()).replace(/\n+/g, ' | ');
  out.a_rmh = await aRow.locator('.lab-sigkelly-rmh').first().innerText().catch(() => null);
}
if (await hRow.count()) {
  out.h_row = (await hRow.innerText()).replace(/\n+/g, ' | ');
  out.h_rmh = await hRow.locator('.lab-sigkelly-rmh').first().innerText().catch(() => null);
}

// 抓全信号表卡片整体文本(前2000字, 含卡头/说明)
const allCard = page.locator('.lab-sigkelly-all-group .lab-sigkelly-card[data-quad="all"]').first();
if (await allCard.count()) {
  const txt = await allCard.innerText();
  out.allGroup = txt.slice(0, 4000);
}

// hover 触发 K 档评级 hoverpop(桌面 mouseenter 显示), 抓评级表
const posTrig = page.locator('.lab-sigkelly-posrate').first();
if (await posTrig.count()) {
  await posTrig.hover({ timeout: 5000 }).catch(() => {});
  await page.waitForTimeout(800);
  const pop = page.locator('.lab-sigkelly-posrate-pop-wrap').first();
  const popDisplay = await pop.evaluate((el) => el.style.display).catch(() => 'ERR');
  const table = pop.locator('.lab-sigkelly-posrate-table');
  if (await table.count()) {
    out.posrate_table = await table.innerText();
  }
  out.posrate_display = popDisplay;
  // 记录动态源(若有)
  out.AI_POSCAP_RATING_DYNAMIC = await page.evaluate(() => {
    const d = window._AI_POSCAP_RATING_DYNAMIC;
    return d ? { computed: !!d.computed, date: d.date || null, fee: d.fee || null, values: d.values || null } : null;
  }).catch(() => null);
  out.AI_POSCAP_RATING = await page.evaluate(() => {
    const s = window._AI_POSCAP_RATING;
    return s ? { date: s.date || null, fee: s.fee || null, values: s.values || null } : null;
  }).catch(() => null);
  // __gih_missing_px_ 计数挂载点
  out.gih_missing_count_global = await page.evaluate(() => window.__gih_missing_px_ || 0).catch(() => null);
}

// 截图留证
await page.screenshot({ path: '/tmp/p0-console/p0-console-top.png', fullPage: false });

// 统计
out.console_error_count = out.console.filter(c => c.type === 'error').length;
out.console_warn_count = out.console.filter(c => c.type === 'warning').length;
out.gih_missing_unique = {};
for (const g of out.gih_missing) {
  const k = g.etf_code + '|' + g.buy_date + '|' + g.force_date;
  out.gih_missing_unique[k] = (out.gih_missing_unique[k] || 0) + 1;
}
out.gih_missing_unique_keys = Object.keys(out.gih_missing_unique).length;

import fs from 'fs';
fs.writeFileSync('/tmp/p0-console/p0-console-result.json', JSON.stringify(out, null, 2));
console.log('== 关键结果 ==');
console.log('localStorageLen:', out.localStorageLen, ' render_wait_ms:', out.render_wait_ms);
console.log('A row:', out.a_row);
console.log('A rmh:', out.a_rmh);
console.log('H row:', out.h_row);
console.log('H rmh:', out.h_rmh);
console.log('console.error:', out.console_error_count, ' console.warn:', out.console_warn_count);
console.log('gih_missing total:', out.gih_missing.length, ' unique:', out.gih_missing_unique_keys);
console.log('gih_missing_count_global:', out.gih_missing_count_global);
console.log('posrate_display:', out.posrate_display);
console.log('pageerrors:', out.pageerrors.length);
console.log('== console 错误明细(全部) ==');
out.console.forEach((c, i) => console.log(`[${i}] ${c.type} ${c.url ? c.url.split('/').pop() : ''}: ${c.text.slice(0, 200)}`));
console.log('== pageerrors ==');
out.pageerrors.forEach((e, i) => console.log(`[${i}] ${e.slice(0, 300)}`));

await b.close();
