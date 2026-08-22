// =============================================================================
// industry-grid-lazy-pixdiff.js — 改前/改后截图逐像素 diff(零第三方依赖,浏览器 canvas 比对)
// 配套报告: docs/industry-grid-lazy-20260822.md
//
// 用法: node docs/scripts/industry-grid-lazy-pixdiff.js <a.png> <b.png> [容差0-255 默认8]
// 输出: JSON { width,height,aSize,bSize,diffPixels,diffPct,maxDelta }
//       - 尺寸不一致 = 布局漂移红信号(diffPct=null)
//       - 容差 8 内的通道噪声忽略(抗锯齿级);超过容差的像素计入 diffPixels
// 口径: 两次捕获均由 industry-grid-lazy-capture.js 在同机同 viewport 同数据下产出,
//       动画已冻结,理论 diff 应≈0(懒渲染只延迟 init 不改渲染结果)。
// =============================================================================
const fs = require("fs");
const { chromium } = require("playwright");

(async () => {
  const [a, b] = process.argv.slice(2);
  const tol = Number(process.argv[4] ?? process.argv[3] ?? 8) || 8;
  if (!a || !b) { console.error("usage: node pixdiff.js <a.png> <b.png> [tol]"); process.exit(2); }
  const aB64 = fs.readFileSync(a).toString("base64");
  const bB64 = fs.readFileSync(b).toString("base64");

  // 优先系统 Chrome(免下载 playwright 浏览器);失败回退内置 chromium
  let browser;
  try { browser = await chromium.launch({ channel: "chrome" }); }
  catch (e) { browser = await chromium.launch(); }
  const page = await browser.newPage();
  const result = await page.evaluate(async ({ aB64, bB64, tol }) => {
    const load = (b64) => new Promise((res, rej) => {
      const img = new Image();
      img.onload = () => res(img);
      img.onerror = rej;
      img.src = "data:image/png;base64," + b64;
    });
    const [ia, ib] = await Promise.all([load(aB64), load(bB64)]);
    if (ia.width !== ib.width || ia.height !== ib.height) {
      return { width: ia.width, height: ia.height, aSize: ia.width + "x" + ia.height, bSize: ib.width + "x" + ib.height, diffPixels: null, diffPct: null, maxDelta: null };
    }
    const cv = document.createElement("canvas");
    cv.width = ia.width; cv.height = ia.height;
    const cx = cv.getContext("2d", { willReadFrequently: true });
    cx.drawImage(ia, 0, 0);
    const da = cx.getImageData(0, 0, cv.width, cv.height).data;
    cx.clearRect(0, 0, cv.width, cv.height);
    cx.drawImage(ib, 0, 0);
    const db = cx.getImageData(0, 0, cv.width, cv.height).data;
    let diff = 0, maxD = 0;
    for (let i = 0; i < da.length; i += 4) {
      const d = Math.max(Math.abs(da[i] - db[i]), Math.abs(da[i + 1] - db[i + 1]), Math.abs(da[i + 2] - db[i + 2]));
      if (d > tol) diff++;
      if (d > maxD) maxD = d;
    }
    const total = cv.width * cv.height;
    return { width: cv.width, height: cv.height, aSize: cv.width + "x" + cv.height, bSize: cv.width + "x" + cv.height, diffPixels: diff, diffPct: +(100 * diff / total).toFixed(5), maxDelta: maxD };
  }, { aB64, bB64, tol });
  console.log(JSON.stringify(result));
  await browser.close();
})().catch((e) => { console.error("PIXDIFF FAILED:", e); process.exit(1); });
