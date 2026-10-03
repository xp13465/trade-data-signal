#!/usr/bin/env node
// 子任务1自测(2026-10-03): _etfXStep 降级路径估宽同口径
//  场景A: 改前 app.js(HEAD), measureText 可用
//  场景B: 改后 app.js, measureText 可用 → 对比场景A逐位一致(正常路径零变化)
//  场景C: 改后 app.js, measureText 不可用 → 标签矩形严格不相交(降级路径修复)
//  两组 cfg: ①accnav 同款(xStep IIFE) ②不带 xStep(_etfXStep 兜底, label 参数生效)
import { chromium } from "playwright";
import fs from "fs";

const BASE = "http://localhost:8379/";
const NEW_APP = fs.readFileSync("/Users/linhuichen/code/trade/.claude/worktrees/agent-a8403e0209f37cbb5/static-site/app.js", "utf8");
const OLD_APP = fs.readFileSync("/tmp/app_old_head.js", "utf8");
if (!OLD_APP) { console.log("SKIP: 缺 /tmp/app_old_head.js"); process.exit(0); }
if (OLD_APP === NEW_APP) { console.log("SKIP: app.js 未变化"); process.exit(0); }

const textTags = (svg) => {
  const tags = [];
  const re = /<text\s+x="([0-9.]+)"[^>]*>([^<]*)<\/text>/g;
  let m;
  while ((m = re.exec(svg))) tags.push({ x: parseFloat(m[1]), t: m[2] });
  return tags;
};
const tagGaps = (tags) => { const g = []; for (let i = 1; i < tags.length; i++) g.push(tags[i].x - tags[i - 1].x); return g; };

const mkCfgIIFE = "(() => {\n    let _lw2 = (typeof _lblWEst === 'function') ? _lblWEst(\"20260928\", 12) : 33;\n    try { const _cx = document.createElement(\"canvas\").getContext(\"2d\"); if (_cx) { _cx.font = \"12px sans-serif\"; _lw2 = _cx.measureText(\"20260928\").width || _lw2; } } catch (_e) { _lw2 = (typeof _lblWEst === 'function') ? _lblWEst(\"20260928\", 12) : 33; }\n    const _cw = 640; const _iwEst = Math.max(120, _cw - 40 - 16);\n    return Math.max(1, Math.floor(Math.max(_lw2 * 1.3, 7) / (_iwEst / Math.max(__dates.length, 1))) + 1);\n  })()";

const evalBody = `(() => {
  const textTags = (svg) => {
    const tags = [];
    const re = /<text\\s+x="([0-9.]+)"[^>]*>([^<]*)<\\/text>/g;
    let m;
    while ((m = re.exec(svg))) { if (/^\\d{8}$/.test(m[2])) tags.push({ x: parseFloat(m[1]), t: m[2] }); }
    return tags;
  };
  const __dates = []; let y = 2026, m = 6, d0 = 1;
  for (let i = 0; i < 60; i++) { __dates.push(String(y) + String(m).padStart(2,"0") + String(d0).padStart(2,"0")); d0++; if (d0>28){d0=1;m++;if(m>12){m=1;y++;}} }
  const __vals = __dates.map((_,i)=> 30 + (i%7)*2);
  const base = { h: 180, pl: 40, pr: 16, pt: 30, pb: 44, boundaryGap: true, dataZoom: false, xLabels: __dates, xFmt: (v)=>v, forceLastLabel: true, ys: [{ splitLine: true, formatter: (v)=>v+"%", splitNumber: 5, min: 0, max: 100 }], legend: [], series: [{ type: "line", data: __vals, color: "#e6492e", width: 2, smooth: true }] };
  const cfg1 = Object.assign({}, base, { xStep: (${mkCfgIIFE}) });
  const cfg2 = Object.assign({}, base);
  let svg1="", svg2="", err="";
  try { svg1 = window._lwSVG(cfg1); } catch(e){ err += " cfg1:" + e; }
  try { svg2 = window._lwSVG(cfg2); } catch(e){ err += " cfg2:" + e; }
  return { svg1, svg2, tags1: textTags(svg1), tags2: textTags(svg2), err };
})()`;

let FAIL = 0;
const ok = (m) => console.log("  PASS  " + m);
const bad = (m) => { FAIL++; console.log("  FAIL  " + m); };

const b = await chromium.launch({ headless: true });

const mkPage = async (appBody, injectMeasureOff) => {
  const ctx = await b.newContext({ viewport: { width: 1400, height: 800 } });
  const page = await ctx.newPage();
  if (injectMeasureOff) await page.addInitScript(() => {
    Object.defineProperty(CanvasRenderingContext2D.prototype, "measureText", { value: undefined });
  });
  for (const p of ["**/data/overview.json*", "**/data/intraday_snapshot.json*"]) {
    await page.route(p, r => r.fulfill({ status: 200, contentType: "application/json", body: "{}" }));
  }
  await page.route("**/data/boot.json*", r => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ overview: {}, config: {} }) }));
  await page.route(/app\.min\.js(\?.*)?$/, r => r.fulfill({ status: 200, contentType: "application/javascript", body: appBody }));
  await page.goto(BASE, { waitUntil: "load", timeout: 90000 }).catch(() => {});
  await page.waitForTimeout(1200);
  return page;
};

console.log("--- A/B 正常路径(measureText 可用): 改前 vs 改后 逐位一致 ---");
const pageA = await mkPage(OLD_APP, false);
const outA = await pageA.evaluate(evalBody).catch(e => ({ err: "evaluate:" + e }));
const pageB = await mkPage(NEW_APP, false);
const outB = await pageB.evaluate(evalBody).catch(e => ({ err: "evaluate:" + e }));

if (outA.err || outB.err) bad("A/B evaluate err: " + outA.err + " | " + outB.err);
else {
  if (outA.svg1 === outB.svg1) ok("IIFE路径(xStep cfg) 正常渲染逐位一致 len=" + outA.svg1.length);
  else { bad("IIFE路径正常渲染漂移"); bad("  A=" + outA.svg1.slice(0,120)); bad("  B=" + outB.svg1.slice(0,120)); }
  if (outA.svg2 === outB.svg2) ok("_etfXStep兜底(无xStep) 正常渲染逐位一致 len=" + outA.svg2.length);
  else { bad("_etfXStep兜底正常渲染漂移"); bad("  A2=" + outA.svg2.slice(0,120)); bad("  B2=" + outB.svg2.slice(0,120)); }
  const g1 = tagGaps(outB.tags1), g2 = tagGaps(outB.tags2);
  if (g1.length) ok("正常路径 IIFE标签数=" + outB.tags1.length + " minGap=" + Math.min(...g1).toFixed(1) + "px");
  if (g2.length) ok("正常路径 兜底标签数=" + outB.tags2.length + " minGap=" + Math.min(...g2).toFixed(1) + "px");
}

console.log("--- C 降级路径(measureText 不可用): 标签严格不相交 ---");
const pageC = await mkPage(NEW_APP, true);
const outC = await pageC.evaluate(evalBody).catch(e => ({ err: "evaluate:" + e }));
if (outC.err) bad("C evaluate err: " + outC.err);
else {
  const labelW = 57.6; // _lblWEst("20260928",12)=8*0.6*12, 与 12px 实测逐位一致
  for (const [name, tags] of [["IIFE路径", outC.tags1], ["_etfXStep兜底", outC.tags2]]) {
    if (tags.length < 2) { bad(name + " 未解析出标签 tags=" + JSON.stringify(tags)); continue; }
    const gaps = tagGaps(tags);
    const minGap = Math.min(...gaps);
    const overlap = gaps.filter(g => g < labelW);
    if (overlap.length === 0) ok(name + " 降级标签不相交 minGap=" + minGap.toFixed(1) + "px >= 文本宽" + labelW + "px (" + tags.length + "标签)");
    else bad(name + " 降级仍重叠 " + overlap.length + " 对, 最差=" + overlap.sort((a, b) => a - b)[0].toFixed(1) + "px < " + labelW + "px");
  }
}

await b.close();
console.log(FAIL ? "FAILURES=" + FAIL : "ALL PASS");
process.exit(FAIL ? 1 : 0);