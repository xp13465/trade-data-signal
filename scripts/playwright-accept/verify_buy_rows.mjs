import { chromium } from 'playwright';
const b = await chromium.launch({ headless: true });
const page = await b.newPage({ viewport:{width:1400,height:4000} });
await page.goto('https://ss.fx8.store', { waitUntil:'domcontentloaded', timeout:60000 });
await page.waitForTimeout(10000);
const data = await page.evaluate(() => {
  const rows=[]; 
  document.querySelectorAll('.sig-item').forEach(it => {
    const txt=(it.textContent||'').replace(/\s+/g,' ').trim();
    const badges=[];
    if(it.querySelector('.sig-poscap-ok'))badges.push('AI建议N');
    if(it.querySelector('.sig-poscap-full'))badges.push('当日已满');
    if(it.querySelector('.sig-poscap-warnbadge'))badges.push('AI警示');
    if(it.querySelector('.sig-poscap-notunibadge'))badges.push('未入样本');
    if(it.querySelector('.sig-ai-hit-badge'))badges.push('AI降亏');
    if(badges.length||/buy|买|买[辅]?|special|唐奇安|突破|买入/.test(txt)) rows.push((badges.join(',')||'-').padEnd(8)+' '+txt.slice(0,45));
  });
  return rows.slice(0,80);
});
console.log(data.join('\n') || '(无 buy 或带 badge 行)');
await b.close();
