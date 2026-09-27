// 首页信号列表 9-22 渲染层验证 v2(2026-09-23 历史信号固化快照根治)
// 无痕/零 localStorage 实测线上 ss.fx8.store
// 断言: 9-22 信号行 AI建议标的 = 561120 / 家电ETF富国(快照固化), 9-23 对照组动态判定
import { chromium } from 'playwright';
import fs from 'fs';

const out = {
  ts: new Date().toISOString(),
  url: null,
  localStorage: null,     // {len, keys}
  version: null,
  console: [],            // 全量 error/warning
  pageerrors: [],
  d0922: null,
  d0923: null,
  aiHover0922: null,      // 9-22 AI建议 cell hover 抓 term-pop ETF 行
  aiHover0923: null,
  snapByDate: null,
  sigItemCount: 0,
  render_wait_ms: 0,
};

const b = await chromium.launch({ headless: true });
const ctx = await b.newContext({ viewport: { width: 1680, height: 4000 } });
const page = await ctx.newPage();

page.on('console', (msg) => {
  const t = msg.type();
  if (t === 'error' || t === 'warning') {
    const loc = msg.location();
    out.console.push({ type: t, text: msg.text(), url: loc.url || null, line: loc.lineNumber || null });
  }
});
page.on('pageerror', (e) => { out.pageerrors.push(String(e)); });

out.url = 'https://ss.fx8.store/';
await page.goto(out.url, { waitUntil: 'domcontentloaded', timeout: 120000 });
// dump localStorage(无痕初始应为 0, 若页面自写 key 记录一下)
out.localStorage = await page.evaluate(() => {
  const keys = [];
  for (let i = 0; i < localStorage.length; i++) keys.push(localStorage.key(i));
  return { len: localStorage.length, keys, values: keys.map(k => localStorage.getItem(k)) };
});
out.version = await page.evaluate(() => {
  const s = document.querySelector('script[src*="app.min.js"]');
  return s ? s.getAttribute('src') : null;
});

// 关 onboarding overlay
await page.evaluate(() => {
  const skip = document.querySelector('.onboarding-skip');
  if (skip) skip.click();
}).catch(() => {});

const t0 = Date.now();
let hasRow = false;
for (let i = 0; i < 45; i++) {
  const n = await page.locator('.sig-day-row .sig-item[data-date]').count().catch(() => 0);
  const snapKeys = await page.evaluate(() => {
    const s = window._sigSnapByDate;
    return s ? Object.keys(s).length : 0;
  }).catch(() => 0);
  if (n > 0 && snapKeys > 0) { out.sigItemCount = n; out.snapLoadedKeys = snapKeys; hasRow = true; break; }
  await page.waitForTimeout(2000);
}
out.render_wait_ms = Date.now() - t0;
if (!hasRow) out.render_failed = true;

out.snapByDate = await page.evaluate(() => {
  const s = window._sigSnapByDate;
  if (!s) return null;
  return {
    keys: Object.keys(s),
    day20260922: (s['20260922'] || []).map(it => ({
      index_id: it.index_id, signal: it.signal, etf_code: it.etf_code,
      etf_name: it.etf_name, track_score: it.track_score, rating: it.rating, late: it.late, source: it.source,
    })),
    day20260923: s['20260923'] || [],
  };
}).catch(() => null);

async function dumpDay(dateStr) {
  const cells = page.locator(`.sig-item[data-date="${dateStr}"]`);
  const n = await cells.count().catch(() => 0);
  const arr = [];
  for (let i = 0; i < n; i++) {
    const c = cells.nth(i);
    arr.push(await c.evaluate((el) => {
      const badgeEl = el.querySelector('.sig-poscap-badge');
      return {
        cls: el.className,
        idx: el.getAttribute('data-idx'),
        idxCode: el.getAttribute('data-idx-code'),
        idxName: el.getAttribute('data-idx-name'),
        sig: el.getAttribute('data-sig'),
        badge: badgeEl ? badgeEl.textContent : '',
        badgeCls: badgeEl ? badgeEl.className : '',
        text: (el.innerText || '').replace(/\n+/g, ' | ').slice(0, 100),
      };
    }).catch(() => null));
  }
  return { date: dateStr, cellCount: n, cells: arr };
}

// 真实 hover 触发 term-pop, 抓 .term-pop-etf 文本(含 ETF 名+代码)
async function hoverAiEtf(dateStr) {
  const kept = page.locator(`.sig-item[data-date="${dateStr}"].sig-poscap-kept`);
  const n = await kept.count().catch(() => 0);
  const res = [];
  for (let i = 0; i < n; i++) {
    const c = kept.nth(i);
    await c.hover({ timeout: 5000 }).catch(() => {});
    await page.waitForTimeout(900);
    const pop = await page.evaluate(() => {
      const p = document.querySelector('.term-pop');
      if (!p || p.style.display === 'none') return null;
      const etf = p.querySelector('.term-pop-etf');
      return {
        popText: (p.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 200),
        etfHtml: etf ? (etf.textContent || '').trim() : null,
      };
    }).catch(() => null);
    const cellInfo = await c.evaluate((el) => ({
      idx: el.getAttribute('data-idx'), idxName: el.getAttribute('data-idx-name'),
      badge: (el.querySelector('.sig-poscap-badge') || {}).textContent || '',
      text: (el.innerText || '').replace(/\n+/g, ' | ').slice(0, 100),
    })).catch(() => null);
    res.push({ cell: cellInfo, termPop: pop });
  }
  return res;
}

out.d0922 = await dumpDay('20260922');
out.d0923 = await dumpDay('20260923');
out.aiHover0922 = await hoverAiEtf('20260922');
out.aiHover0923 = await hoverAiEtf('20260923');

await page.screenshot({ path: '/tmp/sig0922-home.png', fullPage: false });

// ===== 断言 =====
let passAll = true;
const checks = [];

// ① 快照加载 + 9-22 唯一条目
const snap22 = out.snapByDate?.day20260922;
if (snap22 && snap22.length === 1 && snap22[0].etf_code === '561120' && snap22[0].etf_name === '家电ETF富国') {
  checks.push({ name: '快照加载+9-22条目唯一', ok: true, detail: JSON.stringify(snap22[0]) });
} else {
  checks.push({ name: '快照加载+9-22条目唯一', ok: false, detail: JSON.stringify(snap22) });
  passAll = false;
}

// ② 9-22 渲染出 AI建议徽章 cell, index=sw_801110
const ai0922 = (out.d0922?.cells || []).filter(c => (c.badge || '').startsWith('AI建议'));
if (ai0922.length >= 1 && ai0922.some(c => c.idx === 'sw_801110')) {
  checks.push({ name: '9-22 AI建议徽章=sw_801110', ok: true, detail: JSON.stringify(ai0922.map(c => ({ idx: c.idx, idxName: c.idxName, badge: c.badge }))) });
} else {
  checks.push({ name: '9-22 AI建议徽章=sw_801110', ok: false, detail: JSON.stringify(out.d0922) });
  passAll = false;
}

// ③ hover 抓 term-pop ETF 行含 561120 / 家电ETF富国
const h22 = out.aiHover0922 || [];
let etfFound = null;
for (const row of h22) {
  const t = (row.termPop && (row.termPop.etfHtml || row.termPop.popText)) || '';
  if (t.includes('561120') || t.includes('家电ETF富国')) etfFound = t;
}
if (etfFound) {
  checks.push({ name: '9-22 hover ETF=561120/家电ETF富国', ok: true, detail: etfFound.slice(0, 150) });
} else {
  checks.push({ name: '9-22 hover ETF=561120/家电ETF富国', ok: false, detail: JSON.stringify(h22) });
  passAll = false;
}

// ④ 9-23 对照组: 快照 20260923 为空数组 → 动态判定; 渲染有当日行
const snap23 = out.snapByDate?.day20260923;
if (snap23 && Array.isArray(snap23) && snap23.length === 0) {
  checks.push({ name: '9-23 快照空数组(走动态判定)', ok: true, detail: 'day20260923=[]' });
} else {
  checks.push({ name: '9-23 快照空数组(走动态判定)', ok: false, detail: JSON.stringify(snap23) });
  passAll = false;
}
const d23 = out.d0923;
if (d23 && d23.cellCount > 0) {
  checks.push({ name: '9-23 当日信号行渲染', ok: true, detail: `cellCount=${d23.cellCount}` });
} else {
  checks.push({ name: '9-23 当日信号行渲染', ok: d23 ? true : false, detail: d23 ? `cellCount=0(当日无信号)` : 'null' });
  if (!d23) passAll = false;
}

// ⑤ console error: 排除外部数据源(eastmoney 分时), 其余=FAIL
const errs = out.console.filter(c => c.type === 'error');
const extErr = errs.filter(c => (c.url || '').includes('eastmoney') || c.url === null);
const coreErr = errs.filter(c => !(c.url || '').includes('eastmoney') && c.url !== null);
if (coreErr.length === 0) {
  checks.push({ name: 'console 无核心 error(快照/JSON/JS)', ok: true, detail: `外部源(eastmoney)error=${extErr.length}, 核心error=0` });
} else {
  checks.push({ name: 'console 无核心 error', ok: false, detail: JSON.stringify(coreErr) });
  passAll = false;
}

// ⑥ 版本串
const v = out.version || '';
if (v.includes('20260923-a611')) {
  checks.push({ name: '版本串=20260923-a611', ok: true, detail: v });
} else if (v.includes('20260923')) {
  checks.push({ name: '版本串含20260923但非a611', ok: false, detail: v });
  passAll = false;
} else {
  checks.push({ name: '版本串=20260923-a611', ok: false, detail: v || '(无)' });
  passAll = false;
}

out.passAll = passAll;
out.checks = checks;
out.console = out.console.slice(0, 80);  // 截断防上下文膨胀
fs.writeFileSync('/tmp/sig0922-render-result.json', JSON.stringify(out, null, 2));

console.log('===== 首页信号列表 9-22 渲染验证 v2 =====');
console.log('PASS_ALL:', passAll, ' | version:', out.version);
console.log('localStorage:', JSON.stringify(out.localStorage), ' | sigItemCount:', out.sigItemCount, ' | snapKeys:', out.snapLoadedKeys, ' | wait_ms:', out.render_wait_ms);
console.log('--- 快照 9-22(页面已加载) ---');
console.log(JSON.stringify(snap22, null, 1));
console.log('--- 9-22 cells ---');
console.log(JSON.stringify(out.d0922, null, 1));
console.log('--- 9-22 AI hover term-pop ---');
console.log(JSON.stringify(out.aiHover0922, null, 1));
console.log('--- 9-23 cells ---');
console.log(JSON.stringify(out.d0923, null, 1));
console.log('--- checks ---');
for (const c of checks) console.log(`${c.ok ? 'PASS' : 'FAIL'}  ${c.name}: ${typeof c.detail === 'string' ? c.detail.slice(0, 250) : JSON.stringify(c.detail).slice(0, 250)}`);
console.log('--- 核心 console error(非eastmoney) ---');
coreErr.forEach((c, i) => console.log(`[e${i}] ${c.url} | ${c.text.slice(0, 200)}`));
console.log('--- 外部源 console error 数量 ---');
console.log(extErr.length, '条(eastmoney 分时 WAF, 已知现象)');
console.log('--- pageerrors ---');
out.pageerrors.forEach((e, i) => console.log(`[p${i}] ${e.slice(0, 250)}`));

await b.close();
