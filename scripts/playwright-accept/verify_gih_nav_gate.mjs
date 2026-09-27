#!/usr/bin/env node
// 验收: GIH nav 门控修复(46b65337b, 主站 a593)
// 场景1(正常网络): 演进弹窗最终出表, console 无 __gih_missing_px_
// 场景2(弱网模拟): hold accum_nav_map.json → 弹窗占位「净值加载中」不崩不刷警告 → release → 自动重建出表
import { chromium } from "playwright";

const BASE = "https://ss.fx8.store";
const NAV_RE = /accum_nav_map\.json/;

let nPass = 0, nFail = 0;
function check(name, cond, detail = "") {
  if (cond) nPass++; else nFail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
}
function sec(st) { return ((Date.now() - st) / 1000).toFixed(1); }

// 收集 console 与 pageerror, 分类统计
function makeRecorder() {
  const R = {
    allErrors: [], missingPx: 0, typeErrors: [], pageErrors: [],
    log(l) {
      let raw;
      try { raw = l.text(); } catch (e) { raw = "(text-fn)"; }
      const txt = String(raw).slice(0, 300);
      R.allErrors.push(txt);
      if (String(raw).includes("__gih_missing_px_")) R.missingPx++;
      if (/TypeError|undefined is not|Cannot read|null of|NaN/.test(txt)) R.typeErrors.push(txt);
    },
    summary() {
      return {
        totalErrorLines: R.allErrors.length,
        missingPxCount: R.missingPx,
        typeErrorCount: R.typeErrors.length,
        pageErrorCount: R.pageErrors.length,
        samples: R.allErrors.slice(0, 12),
        typeErrorSamples: R.typeErrors.slice(0, 8),
      };
    },
  };
  return R;
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// 打开 lab?sub=sigkelly 并等演进按钮
async function gotoAndWaitEvoBtn(page, tStart) {
  const rsp = await page.goto(BASE + "/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 120000 });
  console.log(`[${sec(tStart)}s] goto: HTTP ${rsp.status()}`);
  for (let i = 0; i < 120; i++) {
    const n = await page.evaluate(() => {
      const b = document.getElementById("lab-kelly-evo-btn");
      return b ? 1 : 0;
    });
    if (n) return true;
    await sleep(1000);
  }
  return false;
}

// 弹窗 host 状态读取
async function readEvoHost(page) {
  return page.evaluate(() => {
    const host = document.getElementById("lab-kelly-evo-table-host");
    const ov = document.getElementById("labKellyEvoOverlay");
    const t = host ? host.textContent.replace(/\s+/g, " ").slice(0, 160) : null;
    const tbl = host ? !!host.querySelector("table.lab-kelly-evo-table") : false;
    return { t, tbl, overlayShown: !!(ov && ov.classList.contains("show")) };
  });
}

async function readEvoTable(page) {
  return page.evaluate(() => {
    const tbl = document.querySelector("#lab-kelly-evo-table-host table.lab-kelly-evo-table");
    if (!tbl) return null;
    const ths = Array.from(tbl.querySelectorAll("thead th")).map((x) => x.textContent.trim());
    const pin = tbl.querySelector("tr.lab-kelly-evo-pin-row");
    const pinCells = pin ? pin.querySelectorAll("td").length : 0;
    const bodyRows = tbl.querySelectorAll("tbody tr").length;
    // G/H/I 列在列头位置
    const modeIdx = {};
    ths.forEach((t, i) => { if (/^[A-J]$/.test(t)) modeIdx[t] = i; });
    const sample = {};
    for (const m of ["G", "H", "I"]) {
      if (modeIdx[m] === undefined) continue;
      const row = tbl.querySelector("tbody tr.lab-kelly-evo-pin-row") || pin;
      const cell = row ? row.querySelector(`td:nth-child(${modeIdx[m] + 1})`) : null;
      sample[m] = cell ? cell.textContent.replace(/\s+/g, " ").slice(0, 60) : "(no-cell)";
    }
    return { ths, thCount: ths.length, pinCells, bodyRows, sample };
  });
}

const browser = await chromium.launch({ headless: true });

// ================= 场景1: 正常网络 =================
console.log("================ 场景1: 正常网络(无拦截)================");
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const R = makeRecorder();
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") R.log(m); });
  page.on("pageerror", (e) => R.pageErrors.push(String(e).slice(0, 200)));
  const t0 = Date.now();

  check("1.0 演进按钮出现", await gotoAndWaitEvoBtn(page, t0));
  await page.click("#lab-kelly-evo-btn");
  console.log(`[${sec(t0)}s] 已点击演进按钮`);

  let sawLoading = false;
  let finalTable = null;
  for (let i = 0; i < 150; i++) {
    const h = await readEvoHost(page);
    if (h.t && h.t.includes("净值加载中")) sawLoading = true;
    if (h.tbl) { finalTable = await readEvoTable(page); break; }
    await sleep(1000);
  }
  check("1.1 弹窗最终渲染出演进表格", !!finalTable, finalTable ? `${finalTable.bodyRows} 行` : "超时无表");
  if (finalTable) {
    check("1.2 列头含 G/H/I 档", ["G", "H", "I"].every((m) => finalTable.ths.includes(m)), `ths=${finalTable.ths.join(",")}`);
    const giSample = ["G", "H", "I"].map((m) => `${m}=${finalTable.sample[m] || "?"}`).join(" | ");
    check("1.3 G/H/I 档 pin 行有数值(非「—」)", /[0-9]/.test(giSample), giSample);
  }
  await page.screenshot({ path: "/tmp/gih-evo-normal.png", fullPage: false });
  const s1 = R.summary();
  check("1.4 console 无 __gih_missing_px_ 警告", s1.missingPxCount === 0, `计数=${s1.missingPxCount}`);
  check("1.5 无 TypeError/undefined/NaN 类报错", s1.typeErrorCount === 0, `计数=${s1.typeErrorCount}`);
  console.log(`[${sec(t0)}s] 场景1 正常路径观察: 弹窗曾显示「净值加载中」占位=${sawLoading}`);
  console.log("--- 场景1 console 错误样本(若有)---");
  s1.samples.forEach((x) => console.log("  E: " + x));
  await ctx.close();
}

// ================= 场景2: 弱网模拟(hold accum_nav_map.json)================
console.log("================ 场景2: 弱网模拟(hold accum_nav_map.json, 占位→释放→重建)================");
{
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: "block" });
  const page = await ctx.newPage();
  const R = makeRecorder();
  page.on("console", (m) => { if (m.type() === "error" || m.type() === "warning") R.log(m); });
  page.on("pageerror", (e) => R.pageErrors.push(String(e).slice(0, 200)));

  const held = []; let firstNavHoldAt = null;       // 被 hold 的 nav 请求
  let released = false;
  await ctx.route(NAV_RE, async (route) => {
    if (!released) { held.push(route); if (!firstNavHoldAt) firstNavHoldAt = Date.now(); return; }  // hold: 不 continue 不 abort
    try { await route.continue(); } catch (e) { /* release 前已被超时中止则忽略 */ }
  });

  const t0 = Date.now();
  check("2.0 演进按钮出现", await gotoAndWaitEvoBtn(page, t0));
  console.log(`[${sec(t0)}s] nav 请求被 hold 数=${held.length}`);
  await page.click("#lab-kelly-evo-btn");
  console.log(`[${sec(t0)}s] 已点击演进按钮(此时 nav 仍被 hold)`);

  // 等占位出现(「净值加载中」; 若分片也慢, 可先见「全量分片加载中」, 二者任一即门控生效)
  let placeholderSeen = null;
  for (let i = 0; i < 20; i++) {
    const h = await readEvoHost(page);
    if (h.t && h.t.includes("净值加载中")) { placeholderSeen = "净值加载中"; break; }
    if (h.t && h.t.includes("全量分片加载中")) { placeholderSeen = "全量分片加载中(分片未就绪,先行占位)"; }
    if (h.tbl) { placeholderSeen = "(表格已出: nav fetch 可能走通或分片先到位)"; break; }
    await sleep(500);
  }
  check("2.1 nav 被 hold 期间弹窗显示占位(净值加载中 或 全量分片加载中)", !!placeholderSeen && placeholderSeen.includes("加载中"), `状态=${placeholderSeen}`);
  const s2pre = R.summary();
  check("2.2 hold 期 console 无 __gih_missing_px_ 警告", s2pre.missingPxCount === 0, `计数=${s2pre.missingPxCount}`);

  // 释放 nav: 用本地真实全量 accum_nav_map.json(26MB, 已预检) fulfill, 浏览器侧毫秒级拿到
  released = true;
  console.log(`[${sec(t0)}s] 释放 nav: held=${held.length} 个, fulfill 本地真实 nav 文件`);
  for (const rt of held) {
    try { await rt.fulfill({ path: "/tmp/gih-accumnav.json", contentType: "application/json" }); }
    catch (e) { try { await rt.continue(); } catch (e2) {} }
  }
  held.length = 0;

  // 等重建出表
  let finalTable = null;
  for (let i = 0; i < 120; i++) {
    const h = await readEvoHost(page);
    if (h.tbl) { finalTable = await readEvoTable(page); break; }
    await sleep(1000);
  }
  check("2.3 nav 到位后表格自动重建出现", !!finalTable, finalTable ? `${finalTable.bodyRows} 行` : "超时无表");
  if (finalTable) {
    check("2.4 重建表列头含 G/H/I", ["G", "H", "I"].every((m) => finalTable.ths.includes(m)), `ths=${finalTable.ths.join(",")}`);
    const giSample = ["G", "H", "I"].map((m) => `${m}=${finalTable.sample[m] || "?"}`).join(" | ");
    check("2.5 重建表 G/H/I pin 行有数值", /[0-9]/.test(giSample), giSample);
    await page.screenshot({ path: "/tmp/gih-evo-weaknet-rebuilt.png", fullPage: false });
  }
  const s2post = R.summary();
  check("2.6 全链路 console 无 __gih_missing_px_ 警告", s2post.missingPxCount === 0, `计数=${s2post.missingPxCount}`);
  check("2.7 全链路无 TypeError/undefined/NaN 类报错", s2post.typeErrorCount === 0, `计数=${s2post.typeErrorCount}`);
  check("2.8 无未捕获 pageerror", s2post.pageErrorCount === 0, `计数=${s2post.pageErrorCount}`);
  console.log("--- 场景2 console 错误样本(若有)---");
  s2post.samples.forEach((x) => console.log("  E: " + x));
  await ctx.close();
}

await browser.close();
console.log(`\n==== 汇总: PASS=${nPass} FAIL=${nFail} ====`);
process.exit(nFail > 0 ? 1 : 0);
