// 真实日期(现在=9/10早上)打开线上页面,检查盘中增量表格板块是否存在
import { chromium } from 'playwright';
const url = process.argv[2] || 'https://ss.fx8.store/lab.html';
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
const pageErrors = [];
page.on('pageerror', e => pageErrors.push(String(e)));
await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
await page.waitForTimeout(1500);
// 打开信号凯利回测tab → 全信号卡
const res = await page.evaluate(() => {
  const out = { dateStr: new Date().toString(), hasView: false };
  const v = document.getElementById('kelly-intraday-view');
  if (v) { out.hasView = true; out.inner = v.innerText.slice(0, 120); out.rect = v.getBoundingClientRect().toJSON(); }
  // 顺便看整个文档里有没有相关文字
  out.docHasIntradayText = document.body.innerText.includes('盘中增量回测') || document.body.innerText.includes('盘中价');
  out.labErr = null;
  return out;
});
console.log(JSON.stringify({ ...res, pageErrors }, null, 2));
await browser.close();
