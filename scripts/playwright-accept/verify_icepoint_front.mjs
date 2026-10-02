import { chromium } from 'playwright';
import fs from 'fs';

// 样本数据(后端 overview() 真实导出, 24 天近 90 日日历)
const sample = JSON.parse(fs.readFileSync('/tmp/merged_overview.json', 'utf8'));
const sampleStr = JSON.stringify(sample);

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1400, height: 5000 } }); // 无痕=全新 context, 零 localStorage
const page = await ctx.newPage();
const failures = [];
const ok = (msg) => console.log('  PASS  ' + msg);
const bad = (msg) => { failures.push(msg); console.log('  FAIL  ' + msg); };

// 拦截 overview.json 返回真实样本; boot.json 合并返回 {overview, config} 让整页可渲染
const emptyJson = JSON.stringify({});
// 注意: fetchJSON 请求带 ?_= 时间戳 query, glob 需用 ** 后缀覆盖全 URL(Path+Query)
await page.route('**/data/overview.json*', (route) => {
  route.fulfill({ status: 200, contentType: 'application/json', body: sampleStr }).catch(() => {});
});
await page.route('**/data/boot.json*', (route) => {
  const body = JSON.stringify({ overview: sample, config: {} });
  route.fulfill({ status: 200, contentType: 'application/json', body }).catch(() => {});
});
// intraday_snapshot 等其他 json 返回空对象, 减少 404 噪音
await page.route('**/data/intraday_snapshot.json*', (route) => {
  route.fulfill({ status: 200, contentType: 'application/json', body: emptyJson }).catch(() => {});
});

page.on('pageerror', (e) => { console.log('  [pageerror] ' + e.message.slice(0, 120)); });

await page.goto('http://127.0.0.1:8379/', { waitUntil: 'domcontentloaded', timeout: 60000 });
await page.waitForTimeout(2500);

// ---- A. 纯函数验证(核心, 不受页面其他数据缺失影响) ----
const A = await page.evaluate(() => {
  const out = {};
  // A1: 真实样本渲染 → 有 sh 格
  const el = document.createElement('div');
  el.innerHTML = window._renderSentimentCalendar(window.__sample_for_test || []);
  out.shCount = el.querySelectorAll('.sig-sh-ice').length;
  out.hasLegend = (el.innerHTML.indexOf('sig-cal-legend') >= 0);
  out.legendHasSh = (el.innerHTML.indexOf('上海炒家冰点') >= 0);
  out.hasOverlap = (el.innerHTML.indexOf('重叠') >= 0);
  out.hasOnlyOld = (el.innerHTML.indexOf('仅老算法') >= 0);
  out.hasConsTxt = (el.innerHTML.indexOf('2/2') >= 0);
  // A2: 容错=完全无 sh_* 字段的日期, 不渲染 sh 格不报错
  const el2 = document.createElement('div');
  el2.innerHTML = window._renderSentimentCalendar([
    { date: '20260101', freeze: [], signals: [] },
    { date: '20260102', freeze: [{ score_id: 'a_sentiment', value: 18.5 }], signals: [] },
  ]);
  out.noShNoRender = (el2.querySelectorAll('.sig-sh-ice').length === 0);
  out.noShOldAloneNoRender = (el2.querySelectorAll('.sig-sh-ice').length === 0); // 缺 sh 字段时不显示"仅老算法"标记
  // A3: x=0 的日期不渲染认可度徽标
  const el3 = document.createElement('div');
  el3.innerHTML = window._renderSentimentCalendar([
    { date: '20260103', freeze: [], signals: [], sh_freeze: false, consensus: { x: 0, y: 2 }, sh_hits: { n: 0, total: 4 }, sh_level: '', sh_factors: [] },
  ]);
  out.x0NoSh = (el3.querySelectorAll('.sig-sh-ice').length === 0);
  return out;
});

// 在页面注入样本后再跑 A(页面级真实数据源)
await page.evaluate((s) => { window.__sample_for_test = s.sentiment_calendar; }, sample);

console.log('--- A 纯函数验证 ---');
const A2 = await page.evaluate(() => {
  const out = {};
  const el = document.createElement('div');
  el.innerHTML = window._renderSentimentCalendar(window.__sample_for_test);
  out.shCount = el.querySelectorAll('.sig-sh-ice').length;
  out.overlapText = [...el.querySelectorAll('.sig-sh-ice')].map(x => x.textContent.trim()).filter(t => t.indexOf('重叠') >= 0).slice(0, 5);
  out.onlyOldText = [...el.querySelectorAll('.sig-sh-ice')].map(x => x.textContent.trim()).filter(t => t.indexOf('仅老算法') >= 0).slice(0, 5);
  out.cons2 = [...el.querySelectorAll('.sig-sh-cons')].map(x => x.textContent.trim()).slice(0, 8);
  return out;
});
A2.shCount >= 1 ? ok('A1 真实样本渲染出 sh 格 count=' + A2.shCount) : bad('A1 sh 格未渲染');
A2.overlapText.length >= 1 ? ok('A1b 重叠格: ' + A2.overlapText.join(' | ')) : bad('A1b 无重叠格');
A2.onlyOldText.length >= 1 ? ok('A1c 仅老算法格: ' + A2.onlyOldText.join(' | ')) : bad('A1c 无仅老算法格');
A2.cons2.some(c => c.indexOf('2/2') >= 0) ? ok('A1d 认可度 2/2 出现: ' + A2.cons2.join(' ')) : bad('A1d 无 2/2');
A.noShNoRender ? ok('A2 容错: 无 sh 字段日期不渲染 sh 格') : bad('A2 容错失败');
A.x0NoSh ? ok('A3 x=0 不渲染认可度徽标') : bad('A3 x=0 渲染了 sh 格(应不渲染)');

// ---- B 页面级: 图例存在性 ----
console.log('--- B 页面级(尽力而为, 其他数据 404 可能影响整页) ---');
const B = await page.evaluate(() => {
  const out = { legend: '', shCells: 0, freezeRows: 0, calExists: false, daysInfo: '' };
  const lg = document.querySelector('.sig-cal-legend');
  out.legend = lg ? lg.textContent.replace(/\s+/g, ' ').trim().slice(0, 200) : '';
  out.shCells = document.querySelectorAll('.sig-sh-ice').length;
  out.hasShCell = document.querySelectorAll('.sig-sh-ice').length > 0;
  out.freezeRows = document.querySelectorAll('.sig-day-row').length;
  // dump: 页面真实 sentiment_calendar 数据是否有 sh 字段
  const w = window;
  out.calExists = !!w.__sentimentCalendar;
  if (w.__sentimentCalendar) {
    const arr = w.__sentimentCalendar;
    out.daysInfo = 'len=' + arr.length + ' shKeys=' + arr.filter(d => 'sh_freeze' in d).length + ' shTrue=' + arr.filter(d => d.sh_freeze === true).length;
  }
  // 找页面全局缓存变量名
  out.globals = Object.keys(w).filter(k => /sentiment|calendar|overview|cal/i.test(k)).slice(0, 20);
  return out;
});
if (B.legend.indexOf('上海炒家冰点') >= 0) ok('B1 图例含上海炒家冰点: ' + B.legend.slice(0, 80));
else bad('B1 图例未见上海炒家冰点(可能整页未渲染) legend=[' + B.legend + '] freezeRows=' + B.freezeRows + ' cal=' + B.daysInfo + ' globals=' + B.globals.join(','));

// ---- C 下钻弹窗验证(纯函数: 直接调 openSentimentDayDetailModal 需要一个真实 day) ----
console.log('--- C 下钻弹窗验证 ---');
const C = await page.evaluate(() => {
  const out = { modalTxt: '', hasBlock: false };
  const hitDay = (window.__sample_for_test || []).find(d => d.sh_freeze === true);
  if (!hitDay) { out.err = 'sample 无 sh_freeze=true 日'; return out; }
  if (typeof window.openSentimentDayDetailModal !== 'function') { out.err = '函数不可用'; return out; }
  window.openSentimentDayDetailModal(hitDay);
  const m = document.getElementById('sentimentDayDetailModal');
  if (!m) { out.err = 'modal 未创建'; return out; }
  out.modalTxt = m.textContent.replace(/\s+/g, ' ').trim();
  out.hasBlock = out.modalTxt.indexOf('上海炒家冰点认可度') >= 0;
  out.hasLevel = out.modalTxt.indexOf('档位') >= 0 && out.modalTxt.indexOf('硬冰点') >= 0;
  out.hasCons = out.modalTxt.indexOf('认可度') >= 0 && out.modalTxt.indexOf('2/2') >= 0;
  out.hasHits = out.modalTxt.indexOf('四因子共振') >= 0;
  out.hasFx = out.modalTxt.indexOf('阈值') >= 0;
  out.hasHitMark = out.modalTxt.indexOf('✓命中') >= 0;
  out.hasMissMark = out.modalTxt.indexOf('✗未中') >= 0;
  out.sampleDate = hitDay.date;
  return out;
});
if (C.err) bad('C err: ' + C.err);
else {
  C.hasBlock ? ok('C1 弹窗含上海炒家冰点认可度块(' + C.sampleDate + ')') : bad('C1 缺认可度块');
  C.hasLevel ? ok('C2 档位显示(硬冰点)') : bad('C2 档位未显示');
  C.hasCons ? ok('C3 认可度 2/2 显示') : bad('C3 认可度未显示');
  C.hasHits ? ok('C4 四因子共振 n/total') : bad('C4 四因子共振未显示');
  C.hasFx ? ok('C5 四因子明细阈值') : bad('C5 四因子阈值未显示');
  C.hasHitMark ? ok('C6 命中 ✓标记') : bad('C6 命中标记未显示');
  // 未命中标记: 找一个 sh_freeze=false 且有 sh 信息的 day 测
}
// C7: 未命中档位 + ✗标记: 用 only_old 日(sh_freeze=false, freeze 非空)开弹窗
const C7 = await page.evaluate(() => {
  const out = { txt: '', hasMiss: false, hasLevelFalse: false };
  const day = (window.__sample_for_test || []).find(d => d.sh_freeze === false && d.sh_level === '' && d.sh_factors && d.sh_factors.length);
  if (!day) { out.err = 'sample 无 sh_freeze=false 且有 sh_factors 日'; return out; }
  if (typeof window.openSentimentDayDetailModal !== 'function') { out.err = '函数不可用'; return out; }
  window.openSentimentDayDetailModal(day);
  const m = document.getElementById('sentimentDayDetailModal');
  if (!m) { out.err = 'modal 未创建'; return out; }
  out.txt = m.textContent.replace(/\s+/g, ' ').trim();
  out.hasMiss = out.txt.indexOf('✗未中') >= 0;
  out.hasLevelFalse = out.txt.indexOf('未命中') >= 0;
  out.date = day.date;
  return out;
});
if (C7.err) bad('C7 ' + C7.err);
else { C7.hasMiss ? ok('C7 未命中 ✗标记(' + C7.date + ')') : bad('C7 未命中标记未显示'); C7.hasLevelFalse ? ok('C7b 档位=未命中') : bad('C7b 档位未命中未显示'); }

// ---- D 页面级: 若 freezeCard 渲染出日历, 点 sh 格开弹窗(真实交互链) ----
console.log('--- D 页面级交互(条件) ---');
const D = await page.evaluate(() => {
  const sh = document.querySelector('.sig-sh-ice');
  if (!sh) return { hasShCell: false };
  // 关键修正(2026-10-02): C/C7 段已调 openSentimentDayDetailModal 把弹窗打开(非 hidden)。
  // 若不复位, 点 sh 格后读 modalOpen = C 段残留打开状态(假阳性 PASS)。
  // 先关闭重置, 使 D 段只检验本次点击的真实结果。
  if (typeof window.closeSentimentDayDetailModal === 'function') window.closeSentimentDayDetailModal();
  const calDate = sh.dataset.calDate || '';
  sh.scrollIntoView();
  sh.click();
  const m = document.getElementById('sentimentDayDetailModal');
  const open = !!(m && !m.classList.contains('hidden'));
  const txt = m ? m.textContent.replace(/\s+/g, ' ').trim() : '';
  // 断言弹窗内容含本次点击格对应日期(标题 YYYY-MM-DD)——只断言"有个打开的弹窗"无效(残留打开态也满足)
  const dateTxt = calDate && calDate.length >= 8 ? `${calDate.slice(0,4)}-${calDate.slice(4,6)}-${calDate.slice(6,8)}` : '';
  return { hasShCell: true, calDate, modalOpen: open, containsDate: open && dateTxt && txt.indexOf(dateTxt) >= 0, modalTxt: txt.slice(0, 160) };
});
if (D.hasShCell) {
  (D.modalOpen && D.containsDate) ? ok(`D 点击 sh 格打开含本次日期(${D.calDate})的下钻弹窗: ${D.modalTxt.slice(0, 60)}`) : bad(`D 点击 sh 格弹窗失败 modalOpen=${D.modalOpen} containsDate=${D.containsDate}`);
} else {
  console.log('  (skip) 页面级未渲染 sh 格, 跳过 D(其他数据 404 影响整页属预期)');
}

console.log('--- 冒烟结束 ---');
if (failures.length) { console.log('FAILURES=' + failures.length); process.exit(1); }
console.log('ALL PASS');
await b.close();
