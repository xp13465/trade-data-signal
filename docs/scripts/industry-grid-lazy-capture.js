// =============================================================================
// industry-grid-lazy-capture.js — 板块分化懒渲染(P2-11 延伸)自验捕获脚本
// 配套报告: docs/industry-grid-lazy-20260822.md
//
// 目的: 对「板块分化 subtab renderIndustryGrid 懒渲染」改动前后各跑一遍,采集:
//   1) 切板块分化 subtab 的 >50ms 长任务列表(改前 753ms 量级 → 改后首帧应无 >50ms)
//   2) 滚动全页后行业格 canvas 总数(懒渲染最终出图数必须与改前一致)
//   3) 搜索过滤路径(输入"银行"→局部重渲→清空→全量重渲)的 canvas 数与 JS 错误
//      (覆盖 _disposeContainerCharts 懒代理销毁链路)
//   4) 港股板块 subtab(同一 renderIndustryGrid 复用路径)同口径数据
//   5) 大盘 tab(a-stock subtab)回归: 首帧 early canvas 数 + 长任务 + 全页截图
//      (P2-11 已上线行为必须零变化)
//   6) 全程 pageerror/console.error 采集(零 JS 错误)
//   7) 各路径整页截图(供 industry-grid-lazy-pixdiff.js 做改前改后像素 diff)
//
// 用法(双站点对照,防工作区来回切;详见报告「复现」段):
//   cp -R static-site/ /tmp/site-lazy && cp -R static-site/ /tmp/site-base
//   git show 'HEAD~1':static-site/app.js > /tmp/site-base/app.js   # base 用改前源+改前 min
//   git show 'HEAD~1':static-site/app.min.js > /tmp/site-base/app.min.js
//   python3 -m http.server -d /tmp/site-lazy 8123 &  python3 -m http.server -d /tmp/site-base 8124 &
//   node docs/scripts/industry-grid-lazy-capture.js --label lazy --outdir /tmp/igcap/lazy --url http://localhost:8123/index.html
//   node docs/scripts/industry-grid-lazy-capture.js --label base --outdir /tmp/igcap/base --url http://localhost:8124/index.html
// 依赖: playwright(~ 本机 ~/node_modules 已装 1.59.1) + 本地 http server(python3 -m http.server
//       -d static-site 8123) + R2 线上数据(access-control-allow-origin: * 已验证可跨域)
// 口径: viewport 1440x900 dpr=1;动画/过渡全局禁用(像素 diff 确定性);真实数据(周末静态不变)。
// =============================================================================
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

function arg(name, dflt) {
  const i = process.argv.indexOf("--" + name);
  return i >= 0 ? process.argv[i + 1] : dflt;
}

(async () => {
  const label = arg("label", "run");
  const outdir = arg("outdir", "/tmp/igcap/" + label);
  const url = arg("url", "http://localhost:8123/index.html");
  fs.mkdirSync(outdir, { recursive: true });

  // 优先系统 Chrome(免下载 playwright 浏览器);失败回退内置 chromium
  let browser;
  try { browser = await chromium.launch({ channel: "chrome" }); }
  catch (e) { browser = await chromium.launch(); }
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage();
  // 本地跨域测试环境特有: r2/industry/industry-all-indices/*-detail.json 无 CORS 头(线上同源不存在)。
  // route mock 掉(detail 只影响 tooltip 降级,有静默 catch,不影响 canvas 渲染/像素),消掉 246 条噪声 error。
  await page.route("**/industry-all-indices/**", (route) => route.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  const errors = [];
  page.on("pageerror", (e) => errors.push("[pageerror] " + String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push("[console] " + m.text()); });

  // 长任务采集(>50ms, PerformanceObserver longtask)
  await page.addInitScript(() => {
    window.__longtasks = [];
    window.__ltMark = 0;
    try {
      new PerformanceObserver((l) => {
        for (const e of l.getEntries()) window.__longtasks.push({ s: Math.round(e.startTime), d: Math.round(e.duration) });
      }).observe({ entryTypes: ["longtask"] });
    } catch (e) { /* longtask 不支持环境忽略 */ }
  });

  const takeLongtasks = () => page.evaluate(() => window.__longtasks.filter((t) => t.s >= window.__ltMark).map((t) => t.d));
  const markLt = () => page.evaluate(() => { window.__ltMark = performance.now(); });
  const count = (sel) => page.evaluate((s) => document.querySelectorAll(s).length, sel);
  const missingCanvas = (sel) => page.evaluate((s) => [...document.querySelectorAll(s)].filter((d) => !d.querySelector("canvas")).length, sel);
  // 等 canvas 总数收敛(R2 fetch 时序抖动会让懒卡建卡时机漂移,不收敛就截图/计数会产生假 diff)
  async function waitCanvasStable(maxMs = 12000) {
    let prev = -1;
    for (let t = 0; t < maxMs; t += 800) {
      await page.waitForTimeout(800);
      const n = await count("canvas");
      if (n === prev && n > 0) return n;
      prev = n;
    }
    return prev;
  }

  // 渐进滚动全页(步长 < viewport,保证每个元素都进过 rootMargin 250px 预渲染带),结束后回顶。
  // ⚠️ 高度必须动态读: B2 IO 滚动中往格里插 chip-row/评分卡会持续撑高页面(实测 39.7k→45.2k),
  //    固定初始 scrollHeight 会漏滚底部 → 底部格永不进 IO 带 → 图缺失假阳性。
  async function scrollAll(step = 700, delay = 260) {
    await page.evaluate(async ({ step, delay }) => {
      let lastH = 0;
      for (let guard = 0; guard < 300; guard++) {
        const h = document.body.scrollHeight;
        if (window.scrollY + window.innerHeight >= h - 5 && h === lastH) break; // 到底且高度稳定
        lastH = h;
        window.scrollTo(0, window.scrollY + step);
        await new Promise((r) => setTimeout(r, delay));
      }
      window.scrollTo(0, document.body.scrollHeight);
      await new Promise((r) => setTimeout(r, delay));
      window.scrollTo(0, 0);
    }, { step, delay });
  }

  // ---- 0. 首页加载(overview 默认 tab),等数据+首屏稳定;冻结动画保证截图确定性 ----
  // 预置引导弹窗已读标记(onboarding_done=新手指引 / nt_intro_done=汪汪队首释,遮罩都会拦 tab 点击)
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.evaluate(() => {
    try {
      localStorage.setItem("onboarding_done", "1");
      localStorage.setItem("nt_intro_done", "1");
    } catch (e) {}
  });
  await page.reload({ waitUntil: "load", timeout: 60000 });
  await page.waitForTimeout(3000);
  await page.addStyleTag({ content: "*,*::before,*::after{animation:none !important;transition:none !important}" });

  const M = { label, errors };

  // ---- 1. 大盘 tab(a-stock subtab)回归: P2-11 已上线行为必须零变化 ----
  await markLt();
  await page.click('button[data-tab="market"]');
  await page.waitForTimeout(3500);
  M.ltMarketAstockFirst = await takeLongtasks();
  M.astockEarlyCanvas = await count("canvas"); // 首帧(未滚动)已 init 的 canvas 数(P2-11 懒生效指标)
  await page.screenshot({ path: path.join(outdir, "astock-firstframe.png") });
  await scrollAll();
  M.astockFullCanvas = await waitCanvasStable();
  await page.screenshot({ path: path.join(outdir, "astock-full.png"), fullPage: true });

  // ---- 2. 切板块分化 subtab: 核心测量(长任务 + 首帧 canvas) ----
  await markLt();
  await page.click('button[data-subtab="industry"]');
  await page.waitForTimeout(4000);
  M.ltIndustrySwitch = await takeLongtasks();
  M.industryEarlyCanvas = await count(".industry-cell canvas"); // 未滚动时已 init 的行业格图数
  M.industryEarlySparkCanvas = await count(".industry-cell .spark-chart canvas");
  M.industryCellsEarly = await count(".industry-cell");

  // ---- 3. 滚动全页 → 全部图应出齐(与改前一次性渲染同数量) ----
  await scrollAll();
  await waitCanvasStable();
  M.industryCells = await count(".industry-cell");
  M.industrySparkCanvas = await count(".industry-cell .spark-chart canvas");
  M.industryMetricCanvas = await count(".industry-cell .ind-metric-chart canvas");
  M.industryMissingSpark = await missingCanvas(".industry-cell .spark-chart");
  M.industryMissingMetric = await missingCanvas(".industry-cell .ind-metric-chart");
  await page.screenshot({ path: path.join(outdir, "industry-full.png"), fullPage: true });

  // ---- 4. 搜索过滤路径(_disposeContainerCharts 懒代理销毁 + 局部重渲) ----
  // 口径注: 重渲后未滚到视口的格不 init 是懒语义正确行为,故计数前先 scrollAll 触发全量
  await page.fill(".anchor-search", "银行");
  await page.waitForTimeout(1500); // 防抖 + 重渲 + 排水
  await scrollAll(500, 200);
  await page.waitForTimeout(1500);
  M.filteredCells = await count(".industry-cell");
  M.filteredSparkCanvas = await count(".industry-cell .spark-chart canvas");
  M.filteredMissingSpark = await missingCanvas(".industry-cell .spark-chart");
  const swWrap = await page.$("[data-spy-for='sw-industries']");
  if (swWrap) await swWrap.screenshot({ path: path.join(outdir, "industry-filtered.png") });
  // 清空搜索 → 全量重渲(119 格 dispose+重建压力路径)
  await page.fill(".anchor-search", "");
  await page.waitForTimeout(2500);
  await scrollAll(500, 200);
  await page.waitForTimeout(1500);
  M.restoredCells = await count(".industry-cell");
  M.restoredSparkCanvas = await count(".industry-cell .spark-chart canvas");
  M.restoredMissingSpark = await missingCanvas(".industry-cell .spark-chart");

  // ---- 5. 港股 subtab(同一 renderIndustryGrid 复用路径) ----
  await markLt();
  await page.click('button[data-subtab="hk"]');
  await page.waitForTimeout(4000);
  M.ltHkSwitch = await takeLongtasks();
  await scrollAll();
  await waitCanvasStable();
  M.hkCells = await count(".industry-cell");
  M.hkSparkCanvas = await count(".industry-cell .spark-chart canvas");
  M.hkMissingSpark = await missingCanvas(".industry-cell .spark-chart");
  await page.screenshot({ path: path.join(outdir, "hk-full.png"), fullPage: true });

  M.errorCount = errors.length;
  fs.writeFileSync(path.join(outdir, "metrics.json"), JSON.stringify(M, null, 2));
  console.log(JSON.stringify(M, null, 2));
  await browser.close();
})().catch((e) => { console.error("CAPTURE FAILED:", e); process.exit(1); });
