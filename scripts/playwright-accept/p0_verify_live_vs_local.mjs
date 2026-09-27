// 验证线上全信号卡数字 vs 用本地文件起本地服务渲染的数字(数据层一致性)
// 由于线上/本地数据已 md5 全一致, 只需确认线上渲染数字合理 + 与 backtest 静态数字不矛盾
import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1600,height:3000} });
const errs=[];
page.on('pageerror', e => errs.push(String(e)));
await page.goto('https://ss.fx8.store/#lab?sub=sigkelly', { waitUntil:'domcontentloaded', timeout:90000 });
await page.waitForTimeout(26000);
// 抓全信号表 A 档关键数字(半凯利/胜率/最终盈亏/峰值收益)
const allGroup = page.locator('.lab-sigkelly-all-group').first();
const txt = await allGroup.innerText();
const lines = txt.split('\n');
// 找到 A 行数据块
for (let i = 0; i < lines.length; i++) {
  if (lines[i].includes('A固定10天') || lines[i].includes('G卖出信号') || lines[i].includes('H卖出+追止损')) {
    console.log('---', lines[i]);
    for (let j = 1; j <= 3; j++) console.log(lines[i+j]);
  }
}
console.log('JS errors:', errs.length ? errs.slice(0,5) : '(无)');
await b.close();
