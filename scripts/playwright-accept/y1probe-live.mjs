// #100 y1 先渲染复现探针(无痕零缓存, 聚焦 console error + 阶段1 完成瞬间 DOM)
import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1500, height: 3000 } });
const page = await ctx.newPage();
const T0 = Date.now();
const logs = [];
const parts = [];
page.on('console', m => logs.push({ t: Date.now() - T0, type: m.type(), text: m.text().slice(0, 400) }));
page.on('pageerror', e => logs.push({ t: Date.now() - T0, type: 'PAGEERROR', text: String(e).slice(0, 800) }));
page.on('response', r => {
  const u = r.url();
  if (u.includes('signal_kelly_trades_parts/')) parts.push({ t: Date.now() - T0, url: u.split('/').pop().split('?')[0], status: r.status() });
});
async function snap() {
  return await page.evaluate(() => {
    const out = { t: Date.now(), loading: 0, cards: 0, cardRows: 0, y1HasData: false, firstCell: null, hostLoading: null };
    out.loading = document.querySelectorAll('.lab-sigkelly-all-loading').length;
    out.cards = document.querySelectorAll('.lab-sigkelly-card').length;
    out.cardRows = document.querySelectorAll('.lab-sigkelly-card .lab-sigkelly-table tbody tr').length;
    out.hostLoading = document.querySelectorAll('.lab-sigkelly-host.lab-custom-host--loading').length;
    // 找 y1 周期下第一个卡表的第一个数据行
    const tr = document.querySelector('.lab-sigkelly-card .lab-sigkelly-table tbody tr');
    if (tr) { out.y1HasData = true; out.firstCell = tr.querySelector('td b') ? tr.querySelector('td b').textContent.trim().slice(0, 20) : null; }
    return out;
  });
}
console.log('goto...');
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil: 'domcontentloaded', timeout: 120000 });
await page.waitForTimeout(800);
const MAX = 120000;
const snapshots = [];
let lastCards = 0, stable = 0, s2done = 0;
while (Date.now() - T0 < MAX && !(s2done && Date.now() - stable > 3000)) {
  const s = await snap();
  if (parts.length >= 16 && s.loading === 0) { s2done = true; if (!stable) stable = Date.now(); }
  if (parts.length < 16) stable = 0;
  snapshots.push(s);
  await page.waitForTimeout(300);
}
console.log('--- 轮询结束 ---');
console.log('16片响应数:', parts.length);
console.log('分片响应前12:');
parts.slice(0, 12).forEach(p => console.log('  t=' + p.t + 'ms ' + p.url));
const s1 = parts.filter(p => p.url === 't2026.json' || p.url === 't2025.json');
if (s1.length >= 2) {
  const s1end = Math.max(s1[0].t, s1[1].t);
  console.log('阶段1两片完成@' + s1end + 'ms');
}
console.log('--- console 全部(前60条) ---');
logs.slice(0, 60).forEach(l => console.log('  t=' + l.t + 'ms [' + l.type + '] ' + l.text.slice(0, 240)));
console.log('--- console 含 error/pageerror(全部) ---');
logs.filter(l => /error|Error|undefined is not|Cannot read|TypeError|ReferenceError/i.test(l.text) || l.type === 'PAGEERROR')
  .forEach(l => console.log('  t=' + l.t + 'ms [' + l.type + '] ' + l.text.slice(0, 400)));
console.log('--- DOM 快照抽样(每8个取1) ---');
snapshots.forEach((s, i) => {
  if (i % 8 === 0 || i === snapshots.length - 1) {
    console.log('  t=' + (s.t - T0) + 'ms cards=' + s.cards + ' rows=' + s.cardRows + ' loading占位=' + s.loading + ' y1有数据=' + s.y1HasData + ' hostLoading=' + s.hostLoading);
  }
});
await page.screenshot({ path: '/tmp/y1probe-final.png', fullPage: false });
await b.close();
console.log('DONE');
