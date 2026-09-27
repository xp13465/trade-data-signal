import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport:{width:1700,height:6000} });
const page = await ctx.newPage();
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(25000);
// 探索页面结构: 模式下拉、周期、按年窗口表
const info = await page.evaluate(() => {
  const out = {};
  const sel = document.getElementById('lab-kelly-fade-mode-sel');
  out.modeSelTag = sel ? sel.tagName : 'none';
  if (sel) out.modeSelHTML = sel.outerHTML.slice(0, 800);
  // 周期按钮
  const tabs = [...document.querySelectorAll('[class*="period"], [class*="tab"]')].map(e => ({cls: e.className, txt: (e.innerText||'').slice(0,30)}));
  out.tabs = tabs.slice(0, 20);
  // 全部 body 文本找「按年」
  const body = document.body.innerText;
  const k = body.indexOf('按年窗口');
  out.yearTableFound = k;
  out.ctx = k>=0 ? body.slice(k, k+400) : '';
  return out;
});
console.log(JSON.stringify(info, null, 1));
await b.close();
