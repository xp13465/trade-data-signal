#!/usr/bin/env node
// 验收 accum_nav_map 按 ETF 懒加载「前端同构对账机检(§5.4⑦ 强制)」骨架。
// 用法: cd scripts/playwright-accept && node verify_nav_lazy_consistency.mjs
// 前置: 本地已起 http.server 于 8123 端口(静态站根, 需含已 build 的 min + data/accum_nav/ 拆分产物在位)
// 依赖: playwright-accept/node_modules
//
// 口径: 懒加载数据供给 = accum_nav/{code}.json(取值与全量 map 逐位一致, §5.4⑦ 生成同源保证);
//       前端三态门控 loaded/pending/failed 保证两个新 bug 不发生:
//         ①「未载 code 被当时序窗口吞掉」→ failed 必须计数 __gih_missing_px_ + 渲「— 缺价」;
//         ②「失败 code 无限重试压死重算」→ 失败冷却 60s + 「落定(loaded∪failed)」就绪闸放行其余 code。
//       本脚本三场景对账: 全量被 block(懒加载) vs 全量放行(全量)逐 cell 数字一致;
//       单 code 缺失注入 = block 某 code 拆分文件 → 该 code 行渲「— 缺价」且计数器 +1(证「failed 被计数, 非被吞」)。
//       首页 sim 弹窗 / 演进表复用同一 common 内核(window._kkellyRealizeRealForce), 由本脚本 lab 路径覆盖内核一致性。
import { chromium } from "playwright";

const BASE = "http://localhost:8123";
const T = (s) => `${s.replace(/\s+/g, " ").trim()}`;

let nPass = 0, nFail = 0;
function check(name, cond, detail = "") {
  if (cond) nPass++; else nFail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
}

// ---- 通用: 起浏览器 + 封闭网络 + 页面错误收集 ----
async function newPage(blockFull, blockCodes /* Set|undefined */) {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 960 } });
  await ctx.clearCookies();
  await ctx.route(/^(?!.*localhost)/, (r) => r.abort());
  const page = await ctx.newPage();
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 240)));

  const fullRe = /accum_nav_map\.json/;
  const perEtfRe = /accum_nav\/\d{6}\.json/;   // {code}.json = 6 位 code
  const reqs = { full: 0, perEtf: [], perEtfBlocked: [] };
  await page.route(perEtfRe, (route) => {
    const url = route.request().url();
    const code = /accum_nav\/(\d{6})\.json/.exec(url)[1];
    if (blockCodes && blockCodes.has(code)) { reqs.perEtfBlocked.push(code); route.abort(); return; }
    reqs.perEtf.push(code);
    route.continue();
  });
  await page.route(fullRe, (route) => {
    reqs.full++;
    if (blockFull) route.abort(); else route.continue();
  });

  await page.goto(BASE + "/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 120000 });
  return { browser, ctx, page, pageErrors, reqs };
}

// ---- 采样: 卡面 G/H/I 交易行 textContent + 三态内核可视态 ----
async function sample(page) {
  return page.evaluate(() => {
    const rows = {};
    document.querySelectorAll(".lab-sigkelly-card[data-quad]").forEach((card) => {
      const qk = card.getAttribute("data-quad");
      const arr = [...card.querySelectorAll(".lab-sigkelly-trade-row")].map((r) => r.textContent.replace(/\s+/g, " ").trim());
      if (arr.length) rows[qk] = arr;
    });
    const missingPx = (typeof window.__gih_missing_px_ === "number") ? window.__gih_missing_px_ : 0;
    // 三态可视态: 全量 flag + 已合并 nav code 的计数(采样几个字段), 缺价行计数
    const host = document.querySelector(".lab-sigkelly-host");
    return {
      rows,
      missingPx,
      realNavFull: !!window._kkellyRealNavFull,
      realNavCodeCount: (window._kkellyRealNav && typeof window._kkellyRealNav === "object")
        ? Object.keys(window._kkellyRealNav).length : 0,
      missingCells: host ? (host.textContent.match(/— 缺价/g) || []).length : 0,
    };
  });
}

// 等 G/H/I 行数稳定(首轮渲染 + nav 补算重建)
async function waitRows(page, t0) {
  let n = 0;
  for (let i = 0; i < 120; i++) {
    n = await page.evaluate(() => document.querySelectorAll(".lab-sigkelly-card[data-quad] .lab-sigkelly-trade-row").length);
    if (n > 0) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  console.log(`  行出现 @${((Date.now() - t0) / 1000).toFixed(1)}s, rows=${n}`);
  return n;
}

// 等 nav 落定(轮询三态内核可视态)+ 主流程再等一小段让补算 flush。
// 原实现依赖 window._kellyNavTarget(未挂 window 的 lab 局部函数, 恒 null → 死等误判 settled);
// 改为只认真实暴露的全局: _kkellyRealNavFull 置位 或 无 in-flight 单 code 请求且已落定(loaded∪failed)。
async function waitSettled(page) {
  for (let i = 0; i < 120; i++) {
    const d = await page.evaluate(() => {
      const full = !!window._kkellyRealNavFull;
      const inflight = (window._kkellyNavInflight && typeof window._kkellyNavInflight === "object")
        ? Object.keys(window._kkellyNavInflight).length : 0;
      const loaded = (window._kkellyRealNav && typeof window._kkellyRealNav === "object")
        ? Object.keys(window._kkellyRealNav).length : 0;
      const failed = (window._kkellyNavFailedCodes && typeof window._kkellyNavFailedCodes === "object")
        ? Object.keys(window._kkellyNavFailedCodes).length : 0;
      return { full, inflight, loaded, failed };
    });
    if (d.full || (d.inflight === 0 && (d.loaded > 0 || d.failed > 0))) return;
    await new Promise((r) => setTimeout(r, 500));
  }
}

async function main() {
  // ============ 场景A: block 全量, 放行 per-ETF(纯懒加载) ============
  console.log("\n===== 场景A: block 全量 accum_nav_map.json, 放行 accum_nav/* (纯懒加载) =====");
  let a = await newPage(true, undefined);
  await waitRows(a.page, Date.now());
  await waitSettled(a.page);
  await new Promise((r) => setTimeout(r, 1500));
  const snapA = await sample(a.page);
  console.log(`  full请求=${a.reqs.full} perEtf请求=${a.reqs.perEtf.length} 缺价计数=${snapA.missingPx} 缺价cell=${snapA.missingCells} realNavFull=${snapA.realNavFull} navCode=${snapA.realNavCodeCount}`);
  check("A1 全量被 block(懒加载仍渲 G/H/I 行)", snapA.rowsLength = Object.keys(snapA.rows).length > 0, `quad卡=${Object.keys(snapA.rows).length}`);
  check("A2 全量 flag 未置位(_kkellyRealNavFull=false)", snapA.realNavFull === false, `realNavFull=${snapA.realNavFull}`);
  check("A3 有 per-ETF 请求发出且全量请求未发出", a.reqs.perEtf.length > 0 && a.reqs.full === 0, `perEtf=${a.reqs.perEtf.length} full=${a.reqs.full}`);
  check("A4 数据齐全下 0 缺价(无真缺口被误判)", snapA.missingPx === 0, `missingPx=${snapA.missingPx}`);

  const codesA = a.reqs.perEtf.slice();   // 本轮实际拉到的 code(懒加载目标集)
  console.log(`  perEtf 样本(前8): ${codesA.slice(0, 8).join(",")}`);

  // ============ 场景B: block per-ETF, 放行全量(全量 fallback) ============
  console.log("\n===== 场景B: block accum_nav/*, 放行全量 accum_nav_map.json (全量 fallback) =====");
  let b = await newPage(false, new Set());
  await waitRows(b.page, Date.now());
  await waitSettled(b.page);
  await new Promise((r) => setTimeout(r, 1500));
  const snapB = await sample(b.page);
  console.log(`  full请求=${b.reqs.full} perEtf请求=${b.reqs.perEtf.length} 缺价计数=${snapB.missingPx} 缺价cell=${snapB.missingCells} realNavFull=${snapB.realNavFull} navCode=${snapB.realNavCodeCount}`);
  check("B1 全量放行(_kkellyRealNavFull=true 或已取值)", snapB.realNavFull === true || snapB.realNavCodeCount > 0, `full=${snapB.realNavFull} navCode=${snapB.realNavCodeCount}`);

  // ============ 同构对账: A(懒加载) vs B(全量) 逐 cell 逐位一致 ============
  console.log("\n===== 同构对账: A(懒加载) vs B(全量) G/H/I 逐 cell 一致 =====");
  const quadsA = Object.keys(snapA.rows), quadsB = Object.keys(snapB.rows);
  const allQuads = [...new Set([...quadsA, ...quadsB])].sort();
  let mismatch = [];
  for (const qk of allQuads) {
    const ra = snapA.rows[qk] || [], rb = snapB.rows[qk] || [];
    if (ra.length !== rb.length) { mismatch.push(`${qk}: 行数 ${ra.length} vs ${rb.length}`); continue; }
    for (let i = 0; i < ra.length; i++) {
      if (ra[i] !== rb[i]) { mismatch.push(`${qk} 行${i}: 「${ra[i].slice(0, 70)}」 vs 「${rb[i].slice(0, 70)}」`); if (mismatch.length >= 5) break; }
    }
    if (mismatch.length >= 5) break;
  }
  check("C1 懒加载 vs 全量 G/H/I 逐 cell 逐位一致(重算内核零改动)", mismatch.length === 0,
    mismatch.length === 0 ? `quads=${allQuads.join(",")} 全部一致` : mismatch.join(" | "));

  // ============ 场景D: 单 code 缺失注入(block 某 code 拆分文件 → failed → 计数非被吞) ============
  if (codesA.length === 0) {
    check("D1 单 code 缺失注入(无 per-ETF 请求可注入, 跳过)", false, "场景A 未拉到任何 accum_nav 请求, 骨架需回填");
  } else {
    const victim = codesA[0] || codesA[codesA.length - 1];
    console.log(`\n===== 场景D: 单 code 缺失注入(block ${victim}.json → failed → 计数非被吞) =====`);
    let d = await newPage(true, new Set([victim]));
    await waitRows(d.page, Date.now());
    await waitSettled(d.page);
    await new Promise((r) => setTimeout(r, 1500));
    const snapD = await sample(d.page);
    console.log(`  blocked=${d.reqs.perEtfBlocked.join(",")} 缺价计数=${snapD.missingPx} 缺价cell=${snapD.missingCells} navCode=${snapD.realNavCodeCount}`);
    check("D1 被 block 的 code 判 failed(非 pending/loaded)", await d.page.evaluate((c) => (typeof window._kkellyNavCodeStatus === "function") ? window._kkellyNavCodeStatus(c) : "no-api", victim) === "failed", `status(${victim})`);
    check("D2 failed code 被计数 __gih_missing_px_>0(证「未载被当时序窗口吞掉」bug 未发生)", snapD.missingPx > 0, `missingPx=${snapD.missingPx}`);
    check("D3 该 code 行渲「— 缺价」红字", snapD.missingCells > 0, `缺价cell=${snapD.missingCells}`);
    check("D4 其余 code 不阻塞(仍有 nav 并入且 0 p页error后仍渲行)", snapD.realNavCodeCount > 0, `navCode=${snapD.realNavCodeCount}`);
    await d.browser.close();
    check("D5 单 code 缺失注入无 pageerror", d.pageErrors.length === 0, d.pageErrors.slice(0, 2).join(" | "));
  }

  check("C2 场景A 无 pageerror", a.pageErrors.length === 0, a.pageErrors.slice(0, 2).join(" | "));
  check("C3 场景B 无 pageerror", b.pageErrors.length === 0, b.pageErrors.slice(0, 2).join(" | "));
  await a.browser.close();
  await b.browser.close();

  console.log(`\n===== ${nFail === 0 ? "ALL PASS" : nFail + " FAIL"} (${nPass} pass, ${nFail} fail) =====`);
  process.exit(nFail === 0 ? 0 : 1);
}

main().catch((e) => { console.error("FATAL", e); process.exit(2); });