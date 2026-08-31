// _smoke_pin_xn_aggregate.cjs — 卖点×N聚合标注冒烟(临时, untracked)
// 用法: NODE_PATH=/Users/linhuichen/.npm/_npx/e41f203b7505f1fb/node_modules node scripts/_smoke_pin_xn_aggregate.cjs
// 验证: ①卖点 pin txt「卖 ×8」 ②hover卖点 info条 detail态列8笔buy明细+合计清仓本金8万
//       ③竖叠/定位/连线未被新代码打回
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const ROOT = '/Users/linhuichen/code/trade/static-site';
const css = fs.readFileSync(path.join(ROOT, 'lab.css'), 'utf8');
const appJs = fs.readFileSync(path.join(ROOT, 'app.js'), 'utf8');
const labJs = fs.readFileSync(path.join(ROOT, 'lab.js'), 'utf8');

// 构造 562870 G 模式真实交易行: fields 尾部追加 fee_cost+amount(与 _renderSigKellyTradesModal extFields 同)
const tradesJson = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/signal_kelly_trades.json'), 'utf8'));
const tFields = tradesJson.fields;
const fIdxFind = {};
tFields.forEach((f, i) => { fIdxFind[f] = i; });
const seenBuy = new Set();
const rawRows = [];
for (const qk of Object.keys(tradesJson.quadrants)) {
  const q = tradesJson.quadrants[qk];
  for (const mk of Object.keys(q)) {
    if (mk !== 'G') continue;
    for (const r of q[mk]) {
      if (String(r[fIdxFind.etf_code]) !== '562870') continue;
      if (String(r[fIdxFind.sell_date]) !== '20260710') continue;
      const bd = String(r[fIdxFind.buy_date]);
      if (seenBuy.has(bd)) continue;
      seenBuy.add(bd);
      rawRows.push(r);
    }
  }
}
console.log('562870 卖20260710 去重买点 =', rawRows.length, '(应为8)');
const extFields = tFields.concat(['fee_cost', 'amount']);
const trades = rawRows.map((r) => { const c = r.slice(); c.push(0); c.push(10000); return c; });

const hist = JSON.parse(fs.readFileSync(path.join(ROOT, 'data/etf/562870-all.json'), 'utf8'));
const ohlc = hist.ohlc || [];

(async () => {
  const res = [];
  const check = (name, cond, extra) => res.push({ name, pass: !!cond, extra });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  page.on('pageerror', () => {}); // 顶层渲染报错不影响函数可用性, 静默
  await page.setContent('<!doctype html><html><head></head><body></body></html>');
  await page.addStyleTag({ content: `:root { --bg-card:#fff; --border-strong:#ddd; --border:#eee; --text-1:#111; --text-2:#333; --text-3:#888; --text-4:#999; --shadow-strong:rgba(0,0,0,0.35); }` });
  await page.addStyleTag({ content: css });
  // 注入源码: 顶层 FunctionDeclaration 会整体 hoist, 后续立即执行代码报错不影响函数可用
  await page.addScriptTag({ content: appJs });
  await page.addScriptTag({ content: labJs });
  // 覆盖 fetchJSON 走本地 ohlc(离线可控)
  await page.evaluate((ohlcRows) => {
    window.fetchJSON = async (url) => {
      if (String(url).indexOf('562870') !== -1) return { ohlc: ohlcRows };
      throw new Error('stub fetchJSON: ' + url);
    };
  }, ohlc);

  // 确认全局函数可用
  const fnReady = await page.evaluate(() => ({
    open: typeof window._openEtfTrendPinModal,
    lite: typeof window._etfTrendLiteHTML,
    bind: typeof window._etfTrendLiteBind,
    fetch: typeof window.fetchJSON,
    esc: typeof window._esc,
    sig: typeof window.signalLabel,
  }));
  check('前置: 弹窗依赖全局函数可用', fnReady.open === 'function' && fnReady.lite === 'function' && fnReady.bind === 'function' && fnReady.fetch === 'function' && fnReady.esc === 'function' && fnReady.sig === 'function', JSON.stringify(fnReady));
  if (fnReady.open !== 'function') {
    await browser.close();
    for (const r of res) console.log((r.pass ? 'PASS' : 'FAIL') + '  ' + r.name + (r.extra ? '  [' + r.extra + ']' : ''));
    return;
  }

  // 打开真实弹窗(562870, 8笔buy+sell都在 formal 区)
  await page.evaluate(({ tr, ef }) => {
    window._openEtfTrendPinModal('562870', '证券ETF嘉实', tr, [], ef, null, null);
  }, { tr: trades, ef: extFields });
  await page.waitForSelector('.lab-etf-pin-sell .lab-etf-pin-txt', { timeout: 8000 });
  await page.waitForTimeout(300);

  const r1 = await page.evaluate(() => {
    const out = [];
    const f = (x) => Math.round(x * 10) / 10;
    const wrap = document.querySelector('.lab-etf-pin-wrap');
    const wr = wrap.getBoundingClientRect();

    // ① 卖点 pin txt 应显示「卖 ×8」(8 笔买同日被清)
    const sellTxts = Array.from(document.querySelectorAll('.lab-etf-pin-sell .lab-etf-pin-txt')).map((e) => e.textContent.trim());
    const buyTxts = Array.from(document.querySelectorAll('.lab-etf-pin-buy .lab-etf-pin-txt')).map((e) => e.textContent.trim());
    out.push({ k: '卖点txt含×8', ok: sellTxts.length === 8 && sellTxts.every((t) => t.indexOf('×8') !== -1), extra: JSON.stringify(sellTxts.slice(0, 3)) });
    out.push({ k: '买点txt=8个(十进位未被打乱)', ok: buyTxts.length === 8, extra: 'buy=' + buyTxts.length });

    // ③ 竖叠/定位/连线: 同日多 sell pin dot x 重合, dots 不横排
    const sellDots = Array.from(document.querySelectorAll('.lab-etf-pin-sell .lab-etf-pin-dot')).map((d) => {
      const r = d.getBoundingClientRect(); return { cx: r.left + r.width / 2 - wr.left, cy: r.top + r.height / 2 - wr.top };
    });
    if (sellDots.length > 1) {
      const xs = sellDots.map((p) => p.cx);
      out.push({ k: '同日8卖pin dot x 重合(<1.5px)', ok: Math.max(...xs) - Math.min(...xs) < 1.5, extra: 'xs=' + xs.map(f).slice(0, 4).join(',') });
    } else {
      out.push({ k: '同日8卖pin dot x 重合(<1.5px)', ok: false, extra: 'sellDots=' + sellDots.length });
    }
    const sellTops = Array.from(document.querySelectorAll('.lab-etf-pin-sell .lab-etf-pin-txt')).map((e) => e.getBoundingClientRect().top - wr.top);
    if (sellTops.length > 1) {
      const asc = sellTops.slice().sort((a, b) => a - b);
      const gaps = asc.slice(1).map((v, i) => v - asc[i]);
      out.push({ k: '同日卖txt竖向错开(逐差≥10px)', ok: gaps.every((g) => g >= 10), extra: 'tops=' + asc.slice(0, 4).map(f).join(',') });
    } else {
      out.push({ k: '同日卖txt竖向错开(逐差≥10px)', ok: false, extra: 'sellTops=' + sellTops.length });
    }
    // 连线: 8 配对 → 8 根线
    const lines = document.querySelectorAll('.lab-etf-pin-line').length;
    out.push({ k: '连线8根(8配对)', ok: lines === 8, extra: 'lines=' + lines });

    // ② hover 第一个卖点 → info 条 detail 态列明细
    const firstSellHot = document.querySelector('.lab-etf-pin-sell .lab-etf-pin-hotzone');
    firstSellHot.dispatchEvent(new MouseEvent('mouseenter', { bubbles: true }));
    return out;
  });
  await page.waitForTimeout(100);
  const r2 = await page.evaluate(() => {
    const bar = document.querySelector('.lab-etf-pin-infobar');
    const txt = bar ? bar.textContent.replace(/\s+/g, ' ').trim() : '';
    const rows = Array.from(document.querySelectorAll('.lab-etf-pin-infobar .lab-etf-pin-pop-subbuy')).length;
    return { txt, rows };
  });

  for (const x of r1) check(x.k, x.ok, x.extra);
  check('② hover卖点 detail态含「同日被清 8 笔买」', r2.txt.indexOf('同日被清 8 笔买') !== -1 || r2.txt.indexOf('被清') !== -1 && r2.txt.indexOf('8') !== -1, r2.txt.slice(0, 80));
  check('② 明细列8行buy', r2.rows === 8, 'rows=' + r2.rows);
  check('② 明细含合计清仓本金 8万 元', r2.txt.indexOf('合计清仓本金') !== -1 && r2.txt.indexOf('8万') !== -1, (r2.txt.match(/合计清仓本金[^·]*(?:万|元)[^·]*/) || ['-'])[0]);
  check('② 明细含各买点买入日期(8行各有真实日期)', (r2.txt.match(/买 20\d{6}/g) || []).length === 8 && (r2.txt.match(/买 2025/g) || []).length === 2, 'buyDates=' + (r2.txt.match(/买 20\d{6}/g) || []).length);

  await browser.close();
  let fail = 0;
  for (const r of res) {
    console.log((r.pass ? 'PASS' : 'FAIL') + '  ' + r.name + (r.extra != null ? '  [' + r.extra + ']' : ''));
    if (!r.pass) fail++;
  }
  console.log('---');
  console.log(fail === 0 ? 'ALL PASS (' + res.length + ' checks)' : fail + ' FAILED');
  process.exit(fail === 0 ? 0 : 1);
})().catch((e) => { console.error('SMOKE ERROR:', e.stack || e.message); process.exit(1); });