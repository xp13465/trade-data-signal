#!/usr/bin/env node
// 场景2 加强版(第三跑): 精确钉住「nav fetch 已被 hold 且 G/H/I 计算在跑」窗口, 验证占位+0警告+释放重建
// 与 verify_gih_nav_gate.mjs 差异: 点击前先等 state.labSigKellyAllReady(分片就绪), 弹窗 build 立即进 navPending 分支;
// release 钉在 held fetch 发出后 5s(15s JS abort 窗口内), fulfill 本地真实全量 nav 文件。
import { chromium } from "playwright";

let nPass = 0, nFail = 0;
function check(name, cond, detail = "") {
  if (cond) nPass++; else nFail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const t0 = Date.now();
const sec = () => ((Date.now() - t0) / 1000).toFixed(1);

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, serviceWorkers: "block" });
const page = await ctx.newPage();

const R = { missingPx: 0, errors: [], typeErrors: [], pageErrors: [], cumMissingAtRelease: 0 };
page.on("console", (m) => {
  if (m.type() !== "error" && m.type() !== "warning") return;
  let raw; try { raw = m.text(); } catch (e) { raw = ""; }
  const txt = String(raw).slice(0, 300);
  R.errors.push(txt);
  if (String(raw).includes("__gih_missing_px_")) R.missingPx++;
  if (/TypeError|undefined is not|Cannot read|null of|NaN/.test(txt)) R.typeErrors.push(txt);
});
page.on("pageerror", (e) => R.pageErrors.push(String(e).slice(0, 200)));

const held = [];
let firstNavHoldAt = null;
let released = false;
await ctx.route(/accum_nav_map\.json/, async (route) => {
  if (!released) { held.push(route); if (!firstNavHoldAt) firstNavHoldAt = Date.now(); return; }
  try { await route.continue(); } catch (e) {}
});

// 1. 进页面并等演进按钮 + 全量分片就绪
const rsp = await page.goto("https://ss.fx8.store/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 120000 });
console.log(`[${sec()}s] goto HTTP ${rsp.status()}`);
let btnOk = false, allReadyOk = false;
for (let i = 0; i < 120; i++) {
  const d = await page.evaluate(() => ({
    btn: !!document.getElementById("lab-kelly-evo-btn"),
    allReady: (typeof state !== "undefined" && state.labSigKellyAllReady === true),
  }));
  if (d.btn) btnOk = true;
  if (d.allReady) allReadyOk = true;
  if (btnOk && allReadyOk) break;
  await sleep(1000);
}
check("A0 演进按钮出现", btnOk);
check("A1 全量分片就绪(state.labSigKellyAllReady=true)", allReadyOk);
console.log(`[${sec()}s] 分片就绪, nav hold 数=${held.length}, 点击演进`);

// 2. 点击弹窗 → 立即构建(分片已就绪)→ navPending 占位 + warmup 发起 nav fetch(被 hold)
await page.click("#lab-kelly-evo-btn");
let placeholderAt = null, seenFullWait = false;
for (let i = 0; i < 40; i++) {
  const h = await page.evaluate(() => {
    const host = document.getElementById("lab-kelly-evo-table-host");
    return host ? host.textContent.replace(/\s+/g, " ").slice(0, 120) : null;
  });
  if (h && h.includes("净值加载中")) { placeholderAt = sec(); break; }
  if (h && h.includes("全量分片加载中")) seenFullWait = true;
  await sleep(500);
}
check("B0 点击弹窗后出现「净值加载中…」占位", placeholderAt !== null, `t=${placeholderAt}s${seenFullWait ? "(期间先见全量分片占位)" : ""}`);

// 3. nav fetch 已被 hold(证明「nav 未就绪」是真实网络状态, 非数据到达误判)
check("B1 nav 请求确实被 route hold 住", held.length > 0, `held=${held.length} firstHoldAt=${firstNavHoldAt ? ((firstNavHoldAt - t0) / 1000).toFixed(1) + "s" : "-"}`);

// 4. hold 观察窗口: 保持 5s(G/H/I 卡面 recompute 每轮强平都走门控; 用户报 9 条的窗口正如此), 查累计警告
await sleep(5000);
const wx = await page.evaluate(() => {
  const host = document.getElementById("lab-kelly-evo-table-host");
  return { stillPlaceholder: !!(host && host.textContent.includes("净值加载中")) };
});
check("B2 hold 观察 5s 后弹窗仍在占位(未渲染失真数字/未崩)", wx.stillPlaceholder);
check("B3 hold 期 console __gih_missing_px_ 累计 = 0(核心: 原 9 条警告窗口)", R.missingPx === 0, `计数=${R.missingPx}`);

// 5. 释放: fulfill 本地真实全量 nav(26MB 真数据)
released = true;
let fulfilled = 0;
for (const rt of held) { try { await rt.fulfill({ path: "/tmp/gih-accumnav.json", contentType: "application/json" }); fulfilled++; } catch (e) { try { await rt.continue(); } catch (e2) {} } }
held.length = 0;
console.log(`[${sec()}s] fulfill 本地真实 nav 文件 ${fulfilled} 个请求`);

// 6. 等表格自动重建
let tbl = null;
for (let i = 0; i < 60; i++) {
  tbl = await page.evaluate(() => {
    const t = document.querySelector("#lab-kelly-evo-table-host table.lab-kelly-evo-table");
    if (!t) return null;
    const ths = Array.from(t.querySelectorAll("thead th")).map((x) => x.textContent.trim());
    const pin = t.querySelector("tr.lab-kelly-evo-pin-row");
    return { rows: t.querySelectorAll("tbody tr").length, ths, pinText: pin ? pin.textContent.replace(/\s+/g, " ").slice(0, 120) : "" };
  });
  if (tbl) break;
  await sleep(1000);
}
check("B4 nav 到位后表格自动重建", !!tbl, tbl ? `${tbl.rows} 行` : "60s 内未出表");
if (tbl) {
  check("B5 重建表列头含 G/H/I", ["G", "H", "I"].every((m) => tbl.ths.includes(m)), `ths=${tbl.ths.join(",")}`);
  check("B6 重建表 pin 行有数值(非「—」)", /[0-9]/.test(tbl.pinText), `pin=${tbl.pinText.slice(0, 150)}`);
  await page.screenshot({ path: "/tmp/gih-evo-weaknet-rebuilt-v2.png" });
}
check("B7 全链路 console __gih_missing_px_ 累计 = 0", R.missingPx === 0, `计数=${R.missingPx}`);
check("B8 全链路无 TypeError/undefined/NaN 类报错", R.typeErrors.length === 0, `计数=${R.typeErrors.length}`);
check("B9 无未捕获 pageerror", R.pageErrors.length === 0, `计数=${R.pageErrors.length}`);
console.log("--- console error 样本 ---");
R.errors.slice(0, 15).forEach((x) => console.log("  E: " + x));

await browser.close();
console.log(`\n==== 场景2加强版汇总: PASS=${nPass} FAIL=${nFail} ====`);
process.exit(nFail > 0 ? 1 : 0);
