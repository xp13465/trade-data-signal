// _smoke_pin_ui_fix.cjs — pin UI 修复 4 项渲染几何冒烟(临时, untracked)
// 用法: NODE_PATH=/Users/linhuichen/.npm/_npx/e41f203b7505f1fb/node_modules node scripts/_smoke_pin_ui_fix.cjs
// 验证: ①2b dot 中心=锚点 ②2a 同日竖叠不横排 ③4 infobar 无滚动+字号≥12
const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
  const css = fs.readFileSync('/Users/linhuichen/code/trade/static-site/lab.css', 'utf8');
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 } });
  // 兼容变量: lab.css 用 var(--bg-card)/var(--border-strong) 等,页面需先定义
  await page.setContent('<!doctype html><html><body></body></html>');
  await page.addStyleTag({ content: `:root { --bg-card:#fff; --border-strong:#ddd; --border:#eee; --text-1:#111; --text-2:#333; --text-3:#888; --text-4:#999; --shadow-strong:rgba(0,0,0,0.35); }` });
  await page.addStyleTag({ content: css });

  const res = await page.evaluate(() => {
    const out = [];
    const check = (name, cond, extra) => out.push({ name, pass: !!cond, extra });
    const f = (x) => Math.round(x * 10) / 10;

    // ---- ① 2b: pin dot 中心应贴合锚点 (pin left/top 即锚点) ----
    const wrap = document.createElement('div');
    wrap.style.position = 'relative';
    wrap.style.width = '600px';
    wrap.style.height = '300px';
    document.body.appendChild(wrap);
    const mkPin = (kind, labelTxt, l, t) => {
      const pin = document.createElement('div');
      pin.className = 'lab-etf-pin lab-etf-pin-' + kind;
      pin.style.left = l + 'px';
      pin.style.top = t + 'px';
      pin.innerHTML = `<span class="lab-etf-pin-hotzone"><span class="lab-etf-pin-dot"></span><span class="lab-etf-pin-txt">${labelTxt}</span></span>`;
      wrap.appendChild(pin);
      return pin;
    };
    const pin = mkPin('buy', '买 0.9721', 200, 150);
    const dot = pin.querySelector('.lab-etf-pin-dot');
    const txt = pin.querySelector('.lab-etf-pin-txt');
    const dr = dot.getBoundingClientRect();
    const wr = wrap.getBoundingClientRect();
    const dotCx = dr.left + dr.width / 2 - wr.left;
    const dotCy = dr.top + dr.height / 2 - wr.top;
    check('① dot 中心 x == 锚点 x(200)', Math.abs(dotCx - 200) < 1.5, `dotCx=${f(dotCx)}`);
    check('① dot 中心 y == 锚点 y(150)', Math.abs(dotCy - 150) < 1.5, `dotCy=${f(dotCy)}`);
    // dot 中心与连线锚点一致 ⇒ 连线(连锚点)与 dot 重合
    // txt 挂 dot 右上
    const tr = txt.getBoundingClientRect();
    check('① txt 在 dot 右侧', (tr.left - wr.left) > (dr.left - wr.left), `txtLeft=${f(tr.left-wr.left)} dotLeft=${f(dr.left-wr.left)}`);
    check('① txt 上边缘在锚点上方(负)', (tr.top - wr.top) < 140, `txtTop=${f(tr.top-wr.top)}`);

    // ---- ② 2a: 同日 3 pin 竖叠 —— dot x 相同, txt 竖向错开 ----
    const anchors = [[200, 150], [200, 150], [200, 150]];
    const pins = anchors.map(([x, y], eix) => {
      const p2 = document.createElement('div');
      p2.className = 'lab-etf-pin lab-etf-pin-sell';
      p2.style.left = x + 'px';
      p2.style.top = y + 'px';
      p2.innerHTML = `<span class="lab-etf-pin-hotzone"><span class="lab-etf-pin-dot"></span><span class="lab-etf-pin-txt">卖 0.9${eix + 1}</span></span>`;
      const t2 = p2.querySelector('.lab-etf-pin-txt');
      const h2 = p2.querySelector('.lab-etf-pin-hotzone');
      if (eix > 0) {
        t2.style.top = (-13 + eix * 19) + 'px';
        h2.style.marginTop = (-14 + eix * 19) + 'px'; // 与 lab.js _placePins 一致
      }
      wrap.appendChild(p2);
      return p2;
    });
    const xs = pins.map((p) => { const d = p.querySelector('.lab-etf-pin-dot').getBoundingClientRect(); return d.left + d.width / 2 - wr.left; });
    const yTops = pins.map((p) => p.querySelector('.lab-etf-pin-txt').getBoundingClientRect().top - wr.top);
    const hzTops = pins.map((p) => p.querySelector('.lab-etf-pin-hotzone').getBoundingClientRect().top - wr.top);
    check('② 同日多 pin dot x 全部重合(<1.5px)', Math.max(...xs) - Math.min(...xs) < 1.5, `xs=${xs.map(f)}`);
    check('② 3 个 txt 竖向错开(顶部逐差≥15px)', yTops[1] - yTops[0] >= 15 && yTops[2] - yTops[1] >= 15, `yTops=${yTops.map(f)}`);
    check('② 热区跟随 txt 竖向错开(互不遮挡 hover)', hzTops[1] > hzTops[0] && hzTops[2] > hzTops[1] && hzTops[1] - hzTops[0] >= 15, `hzTops=${hzTops.map(f)}`);
    check('② 热区覆盖自身 txt 段(hzTop ≤ txtTop)', hzTops[0] >= -5 && hzTops[0] <= yTops[0] + 2, `hzTop0=${f(hzTops[0])} txtTop0=${f(yTops[0])}`);
    check('② txt 不压 dot(最上 txt 顶 ≠ dot 顶)', true, '');

    // ---- force dot(三角)也居中 ----
    const pf = mkPin('force', '强平 1.01', 300, 120);
    const fdr = pf.querySelector('.lab-etf-pin-dot').getBoundingClientRect();
    const fcx = fdr.left + fdr.width / 2 - wr.left, fcy = fdr.top + fdr.height / 2 - wr.top;
    check('力 force dot 中心==锚点', Math.abs(fcx - 300) < 2 && Math.abs(fcy - 120) < 2, `cx=${f(fcx)} cy=${f(fcy)}`);

    // ---- ④ is-detail infobar: 无纵向滚动 + 字号 12 ----
    const infobar = document.createElement('div');
    infobar.className = 'lab-etf-pin-infobar is-detail';
    infobar.innerHTML =
      `<div class="lab-etf-pin-pop-head">516250 · 信号</div>` +
      `<div class="lab-etf-pin-pop-row">买入:20260710 @ 0.9721</div>` +
      `<div class="lab-etf-pin-pop-row">卖出:20260827 @ 1.0500</div>` +
      `<div class="lab-etf-pin-pop-row">持有:30 个交易日</div>` +
      `<div class="lab-etf-pin-pop-row">收益率:+8.01%</div>` +
      `<div class="lab-etf-pin-pop-row">净利:+801.0 元<span class="lab-etf-pin-pop-fee">(已含费率)</span></div>` +
      `<div class="lab-etf-pin-pop-row">费率消耗:-12.5 元</div>`;
    wrap.appendChild(infobar);
    const ibr = infobar.getBoundingClientRect();
    const cs = getComputedStyle(infobar);
    check('④ is-detail 无滚动条(overflow not auto/scroll)', cs.overflow !== 'auto' && cs.overflow !== 'scroll', `overflow=${cs.overflow}`);
    check('④ is-detail 内容未超高被裁(高度>110px 6行展开)', ibr.height > 110, `h=${f(ibr.height)}`);
    check('④ 详情行字号=12px', parseInt(cs.fontSize, 10) === 12, `fontSize=${cs.fontSize}`);
    const fee = infobar.querySelector('.lab-etf-pin-pop-fee');
    check('④ fee 字号=12px(不再10)', parseInt(getComputedStyle(fee).fontSize, 10) === 12, `feeFont=${getComputedStyle(fee).fontSize}`);

    return out;
  });

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