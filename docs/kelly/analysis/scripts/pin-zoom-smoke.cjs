// ETF pin 弹窗缩放/平移内核真实浏览器验证(smoke, untracked 临时文件)
// 用法: NODE_PATH=/Users/linhuichen/.npm/_npx/e41f203b7505f1fb/node_modules node smoke-pin-zoom.cjs
const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
  const ohlcAll = JSON.parse(fs.readFileSync('/Users/linhuichen/code/trade/static-site/data/etf/510300-all.json', 'utf8')).ohlc;
  // 模拟弹窗聚焦窗口(取全史中间 800 行, 跨十余年密集型)
  const mid = Math.floor(ohlcAll.length / 2);
  const ohlc = ohlcAll.slice(mid - 400, mid + 400);
  const ohlcJson = JSON.stringify(ohlc);

  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
  await page.goto('about:blank');
  await page.addScriptTag({ path: '/Users/linhuichen/code/trade/static-site/app.js' });

  // ---- evaluate 0: 初始化 + 内核断言(几何/缩放/事件/pinch 合成) ----
  const res0 = await page.evaluate((ohlcJson) => {
    const ohlc = JSON.parse(ohlcJson);
    const n = ohlc.length;
    const out = [];
    const check = (name, cond, extra) => out.push({ name, pass: !!cond, extra: extra == null ? null : extra });

    const div = document.createElement('div');
    div.style.width = '720px';
    document.body.appendChild(div);
    div.innerHTML = _etfTrendLiteHTML(ohlc);
    const svg = div.querySelector('svg');
    const wrap = div.querySelector('.etf-trend-wrap');
    const ctl = _etfTrendLiteBind(svg, ohlc, { panZoom: true });

    // ---- 1. 返回值 / 初始全览 ----
    check('ctl 返回 zoomIn/zoomOut/reset', ctl && typeof ctl.zoomIn === 'function' && typeof ctl.zoomOut === 'function' && typeof ctl.reset === 'function');
    const av0 = svg._etfTrendPan.get();
    check('初始 i0=0 / i1=n-1 (全览=scale=1)', av0 && av0.i0 === 0 && av0.i1 === n - 1, JSON.stringify({ i0: av0 && av0.i0, i1: av0 && av0.i1, n }));

    // ---- 2. scale=1 几何与既有 _etfTrendGeom 逐位一致(回归锚) ----
    const gRef = _etfTrendGeom(ohlc, av0.W);
    let bitEq = true;
    for (const k of ['W', 'H', 'PL', 'PR', 'PT', 'PB', '_n', '_iw', '_ih', '_unitW', '_yMin', '_yMax', '_step', '_prec', '_lastV']) {
      if (av0.geom[k] !== gRef[k]) bitEq = false;
    }
    for (const i of [0, 1, Math.floor(n / 2), n - 2]) {
      if (av0.geom._px(i) !== gRef._px(i) || av0.geom._py(av0.geom._vals[i]) !== gRef._py(gRef._vals[i])) bitEq = false;
    }
    check('scale=1 几何 15 字段+取样点逐位一致', bitEq);
    // 内容一致: 两侧同走浏览器 innerHTML 序列化(直接字符串比较会撞 <line/> vs <line></line> 序列化差异)
    // 只比内容部分(svg 根节点属性不属于曲线几何)
    const dRef = document.createElement('div');
    dRef.innerHTML = '<svg viewBox="0 0 ' + av0.W + ' 200">' + _etfTrendSVG(ohlc, av0.W) + '</svg>';
    const outRef = dRef.firstChild.outerHTML;
    const outSrc = '<svg viewBox="0 0 ' + av0.W + ' 200">' + svg.innerHTML + '</svg>';
    check('初始 innerHTML 内容与既有 _etfTrendSVG 一致(几何部分)', outRef === outSrc, outRef === outSrc ? null : JSON.stringify({ a: outSrc.length, b: outRef.length }));

    // ---- 3. zoomIn: 窗口变窄 + 相邻 x 间距拉开 + x 单调 ----
    ctl.zoomIn();
    const av1 = svg._etfTrendPan.get();
    check('zoomIn 后窗口变窄', (av1.i1 - av1.i0 + 1) < n, JSON.stringify({ w0: n, w1: av1.i1 - av1.i0 + 1 }));
    const g1 = av1.geom;
    check('放大后相邻 x 间距拉开', g1._unitW > av0.geom._unitW, JSON.stringify({ before: av0.geom._unitW, after: g1._unitW }));
    let mono = true;
    for (let i = 0; i < g1._n - 1; i++) { if (!(g1._px(i + 1) > g1._px(i))) { mono = false; break; } }
    check('x 映射单调递增', mono);

    // ---- 4. reset 回全览且几何一致 ----
    ctl.reset();
    const av2 = svg._etfTrendPan.get();
    check('reset 回全览且几何一致', av2.i0 === 0 && av2.i1 === n - 1 && av2.geom._px(10) === gRef._px(10));

    // ---- 5. wheel 缩放(与真实滚轮同一监听; ctrlKey 触控板 pinch 同路) ----
    const rect = svg.getBoundingClientRect();
    const cx = rect.left + rect.width / 2, cy = rect.top + rect.height / 2;
    const mkWheel = (dy, ctrl) => new WheelEvent('wheel', { deltaY: dy, deltaMode: 0, clientX: cx, clientY: cy, ctrlKey: !!ctrl, bubbles: true, cancelable: true });
    svg.dispatchEvent(mkWheel(-120, false));
    const av3 = svg._etfTrendPan.get();
    check('wheel 滚轮 zoom in 生效', (av3.i1 - av3.i0 + 1) < n, JSON.stringify({ w: av3.i1 - av3.i0 + 1 }));
    for (let i = 0; i < 10; i++) svg.dispatchEvent(mkWheel(120, false));
    const av4 = svg._etfTrendPan.get();
    check('wheel 连续 zoom out 回全览', av4.i0 === 0 && av4.i1 === n - 1);
    // 触控板 pinch(ctrlKey+wheel)
    svg.dispatchEvent(mkWheel(-40, true));
    const av3b = svg._etfTrendPan.get();
    check('触控板 pinch(ctrl+wheel) 生效', (av3b.i1 - av3b.i0 + 1) < n);
    ctl.reset();

    // ---- 6. pin 映射一致性: 全览时 lab svgPointToWrap 口径 == 旧几何 ----
    // 模拟 lab.js svgPointToWrap 逻辑: sl = ix - i0, y 锚 close
    const WPIN = av0.W;
    for (const ix of [0, 40, 399, 760]) {
      const sl = ix - av0.i0;
      const pxW = av0.geom._px(sl);
      if (!(pxW >= av0.geom.PL && pxW <= av0.geom.W - av0.geom.PR)) check('pin 映射在全览窗口内 ix=' + ix, false, String(pxW));
    }
    check('pin 映射全览窗口内(取样4点)', true);

    // ---- 7. 缩放后 hover/tooltip 仍工作 ----
    ctl.zoomIn();
    const cursorEl = svg.querySelector('.etf-trend-cursor');
    const tip = div.querySelector('.etf-trend-tip');
    svg.dispatchEvent(new MouseEvent('mousemove', { clientX: rect.left + rect.width / 2, clientY: cy, bubbles: true }));
    check('缩放后 hover 十字线显示', cursorEl && cursorEl.getAttribute('opacity') === '0.9');
    check('缩放后 tooltip 显示', tip && tip.style.display === 'block');

    // ---- 8. etf-trend-panzoom 事件派发(pin 重排驱动) ----
    let dispatched = 0;
    svg.addEventListener('etf-trend-panzoom', () => dispatched++);
    ctl.zoomIn(); ctl.reset(); ctl.zoomIn();
    check('etf-trend-panzoom 事件派发 ≥3', dispatched >= 3, String(dispatched));

    // ---- 9. 触摸 pinch(合成 TouchEvent; 与真实触摸同一监听) ----
    const T = (x, id, tgt) => new Touch({ identifier: id, target: tgt, clientX: x, clientY: cy });
    ctl.reset();
    const d0 = rect.left + 400;
    svg.dispatchEvent(new TouchEvent('touchstart', { touches: [T(rect.left + 200, 10, svg), T(rect.left + 400, 11, svg)], bubbles: true, cancelable: true }));
    svg.dispatchEvent(new TouchEvent('touchmove', { touches: [T(rect.left + 200, 10, svg), T(rect.left + 520, 11, svg)], bubbles: true, cancelable: true }));
    svg.dispatchEvent(new TouchEvent('touchmove', { touches: [T(rect.left + 200, 10, svg), T(rect.left + 540, 11, svg)], bubbles: true, cancelable: true }));
    svg.dispatchEvent(new TouchEvent('touchend', { touches: [], bubbles: true, cancelable: true }));
    const avd = svg._etfTrendPan.get();
    check('触摸 pinch zoom in 生效', (avd.i1 - avd.i0 + 1) < n, JSON.stringify({ w: avd.i1 - avd.i0 + 1 }));

    // 保存引用供后续真实鼠标拖拽测试
    window.__pinTest = { svg, wrap, ctl };
    return out;
  }, ohlcJson);

  // ---- 真实鼠标拖拽测试(使用 page.mouse 产生真实 PointerEvent) ----
  const box = await page.locator('svg.etf-trend-lite').boundingBox();
  const sy = box.y + box.height / 2;
  const readPan = () => page.evaluate(() => {
    const svg = window.__pinTest.svg;
    const p = svg._etfTrendPan.get();
    return { i0: p.i0, i1: p.i1 };
  });

  // A) scale=1 时拖拽不生效
  await page.evaluate(() => window.__pinTest.ctl.reset());
  const panA0 = await readPan();
  await page.mouse.move(box.x + 200, sy);
  await page.mouse.down();
  await page.mouse.move(box.x + 320, sy, { steps: 5 });
  await page.mouse.up();
  const panA1 = await readPan();
  const okA = panA1.i0 === panA0.i0 && panA1.i1 === panA0.i1;

  // B) scale>1 拖拽平移生效(窗口左移, 宽不变)
  await page.evaluate(() => window.__pinTest.ctl.zoomIn());
  const panB0 = await readPan();
  await page.mouse.move(box.x + 300, sy);
  await page.mouse.down();
  await page.mouse.move(box.x + 300 + 120, sy, { steps: 6 });
  await page.mouse.up();
  const panB1 = await readPan();
  const okB = panB1.i0 !== panB0.i0 && (panB1.i1 - panB1.i0) === (panB0.i1 - panB0.i0);

  // C) 真实鼠标滚轮(wheel)在 svg 上缩放生效
  await page.evaluate(() => window.__pinTest.ctl.reset());
  await page.mouse.move(box.x + box.width / 2, sy);
  await page.mouse.wheel(0, -120);
  const panC = await readPan();
  const okC = (panC.i1 - panC.i0 + 1) < ohlc.length;

  await browser.close();

  let fail = 0;
  const all = res0.concat([
    { name: '真实拖拽: scale=1 不生效(窗口不动)', pass: okA, extra: JSON.stringify({ before: panA0, after: panA1 }) },
    { name: '真实拖拽: scale>1 平移生效且窗口宽不变', pass: okB, extra: JSON.stringify({ before: panB0, after: panB1 }) },
    { name: '真实滚轮: svg 上 wheel 缩放生效', pass: okC, extra: JSON.stringify({ w: panC.i1 - panC.i0 + 1 }) },
  ]);
  for (const r of all) {
    console.log((r.pass ? 'PASS' : 'FAIL') + '  ' + r.name + (r.extra != null ? '  [' + r.extra + ']' : ''));
    if (!r.pass) fail++;
  }
  console.log('---');
  console.log(fail === 0 ? 'ALL PASS (' + all.length + ' checks)' : fail + ' FAILED');
  process.exit(fail === 0 ? 0 : 1);
})().catch(e => { console.error('SMOKE ERROR:', e.stack || e.message); process.exit(1); });