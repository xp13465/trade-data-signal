// P0 补测: 首页(ss.fx8.store 根路径) K 档评级 hoverpop + 全信号/凯利区 展示, 找 182.25/142.68
import { chromium } from 'playwright';
import fs from 'fs';
const out = { console_err: [], hits: {}, posrate: null };
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1680, height: 4000 } });
const page = await ctx.newPage();
page.on('console', (msg) => { if (msg.type() === 'error' || msg.type() === 'warning') out.console_err.push({ t: msg.type(), text: msg.text() }); });
page.on('pageerror', (e) => out.console_err.push({ t: 'pageerror', text: String(e) }));

await page.goto('https://ss.fx8.store/', { waitUntil: 'domcontentloaded', timeout: 120000 });
// 等页面加载(数据加载可能需要时间)
await page.waitForTimeout(15000);

// K 档评级 hoverpop: 首页 .sig-kbtns.lab-sigkelly-posrate
const posTrig = page.locator('.sig-kbtns.lab-sigkelly-posrate, .lab-sigkelly-posrate').first();
if (await posTrig.count()) {
  await posTrig.hover().catch(() => {});
  await page.waitForTimeout(800);
  const pop = page.locator('.lab-sigkelly-posrate-pop-wrap').first();
  const table = pop.locator('.lab-sigkelly-posrate-table');
  if (await table.count()) out.posrate = await table.innerText();
}

// 全局文本搜 182.25 / 142.68 / 163.25 / 224.92
for (const t of ['182.25', '142.68', '163.25', '224.92']) {
  out.hits[t] = await page.evaluate((tt) => {
    const res = [];
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let n;
    while (n = w.nextNode()) {
      if (n.textContent && n.textContent.includes(tt)) {
        const el = n.parentElement;
        let ctx = []; let cur = el;
        for (let i = 0; i < 4 && cur; i++) { ctx.push(cur.tagName + (cur.className ? '.' + String(cur.className).split(' ').slice(0,2).join('.') : '')); cur = cur.parentElement; }
        res.push({ text: n.textContent.trim().slice(0, 80), ctx: ctx.join(' < ') });
      }
    }
    return res.slice(0, 10);
  }, t);
}

// 抓首页信号卡/凯利区几个 key 数值区域(截图)
await page.screenshot({ path: '/tmp/p0-console/home-top.png', fullPage: false });

fs.writeFileSync('/tmp/p0-console/p0-home.json', JSON.stringify(out, null, 2));
console.log('== 首页 K 档评级表 ==');
console.log(out.posrate);
console.log('== 文本命中 ==');
for (const t of Object.keys(out.hits)) {
  if (out.hits[t].length) console.log(t, '=>', JSON.stringify(out.hits[t], null, 1).slice(0, 500));
}
console.log('== console 错误 ==');
out.console_err.forEach(c => console.log(c.t, c.text.slice(0, 160)));
await b.close();
