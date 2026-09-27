import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1600,height:3000} });
const fetches = {};
page.on('response', async r => {
  if (r.status() !== 200) return;
  const u = r.url();
  if (u.includes('signal_kelly_trades_parts/t') || u.includes('kelly_mode_s06_state') || u.includes('signal_kelly_backtest.json')) {
    try { const j = await r.json(); fetches[u.split('?')[0]] = { gen: j.generated_at, len: JSON.stringify(j).length }; } catch(e) {}
  }
});
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(15000);
console.log('=== 线上实际 fetch 的数据源(generated_at + 大小) ===');
for (const [url, info] of Object.entries(fetches)) {
  console.log(url);
  console.log('   gen:', info.gen, ' len:', info.len);
}
console.log('总 fetch 条数:', Object.keys(fetches).length);
await b.close();
