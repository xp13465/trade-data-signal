#!/usr/bin/env node
// 第四跑: 快速打法合并闭环 —— hold 活着时 fulfill, 一条日志同时拿到「占位+0警告+释放重建出表」完整证据链
// 要点: 点击弹窗后一旦「净值加载中…」占位出现且 nav fetch 已被 hold, 立即(≤3s) fulfill 本地真实 nav, 保 fetch 活着;
//       fulfillMode 兜底: 释放后新发起的 nav 请求也直接 fulfill 本地文件(防冷却期新 fetch 走真实网络再次超时)。
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

const R = { missingPx: 0, errors: [], typeErrors: [], pageErrors: [] };
page.on("console", (m) => {
  if (m.type() !== "error" && m.type() !== "warning") return;
  let raw; try { raw = m.text(); } catch (e) { raw = ""; }
  R.errors.push(String(raw).slice(0, 300));
  if (String(raw).includes("__gih_missing_px_")) R.missingPx++;
  if (/TypeError|undefined is not|Cannot read|null of|NaN/.test(String(raw))) R.typeErrors.push(String(raw));
});
page.on("pageerror", (e) => R.pageErrors.push(String(e).slice(0, 200)));

const held = [];
let released = false;
await ctx.route(/accum_nav_map\.json/, async (route) => {
  if (!released) { held.push(route); return; }
  try { await route.fulfill({ path: "/tmp/gih-accumnav.json", contentType: "application/json" }); }
  catch (e) { /* 已取消请求忽略 */ }
});

const rsp = await page.goto("https://ss.fx8.store/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 120000 });
console.log(`[${sec()}s] goto HTTP ${rsp.status()}`);
let btnAt = null;
for (let i = 0; i < 90; i++) {
  const ok = await page.evaluate(() => !!document.getElementById("lab-kelly-evo-btn"));
  if (ok) { btnAt = sec(); break; }
  await sleep(1000);
}
check("A0 演进按钮出现", btnAt !== null, `t=${btnAt}s`);
await page.click("#lab-kelly-evo-btn");
console.log(`[${sec()}s] 点击演进(nav held=${held.length})`);

let placeholderAt = null, seenFullWait = false;
for (let i = 0; i < 60; i++) {
  const h = await page.evaluate(() => {
    const host = document.getElementById("lab-kelly-evo-table-host");
    return host ? host.textContent.replace(/\s+/g, " ").slice(0, 120) : null;
  });
  if (h && h.includes("净值加载中")) { placeholderAt = sec(); break; }
  if (h && h.includes("全量分片加载中")) seenFullWait = true;
  if (h && h.includes("净值加载中") === false && i > 10 && seenFullWait) { /* 继续等 */ }
  await sleep(500);
}
check("B0 占位「净值加载中…」出现", placeholderAt !== null, `t=${placeholderAt}s${seenFullWait ? "(期间先见全量分片占位)" : ""}`);
const heldNow = held.length;
check("B1 nav fetch 被 hold(nav 未就绪是真实状态)", heldNow > 0, `held=${heldNow}`);
check("B2 占位出现时 console __gih_missing_px_ = 0", R.missingPx === 0, `计数=${R.missingPx}`);

await sleep(2000);
check("B3 占位观察 2s 后仍在「净值加载中」(未交替渲染失真数字)", await page.evaluate(() => {
  const host = document.getElementById("lab-kelly-evo-table-host");
  return !!(host && host.textContent.includes("净值加载中"));
}));

// 释放: 当前 held 全 fulfill + released=true 后新请求也 fulfill
released = true;
let fulfilled = 0;
for (const rt of held) { try { await rt.fulfill({ path: "/tmp/gih-accumnav.json", contentType: "application/json" }); fulfilled++; } catch (e) { try { await rt.continue(); } catch (e2) {} } }
held.length = 0;
console.log(`[${sec()}s] fulfill 本地真实 nav(${fulfilled} 个扣住的请求成功填充), 后续新请求走 fulfillMode`);

let tbl = null;
for (let i = 0; i < 90; i++) {
  tbl = await page.evaluate(() => {
    const t = document.querySelector("#lab-kelly-evo-table-host table.lab-kelly-evo-table");
    if (!t) return null;
    const ths = Array.from(t.querySelectorAll("thead th")).map((x) => x.textContent.trim());
    const pin = t.querySelector("tr.lab-kelly-evo-pin-row");
    return { rows: t.querySelectorAll("tbody tr").length, ths, pinText: pin ? pin.textContent.replace(/\s+/g, " ").slice(0, 160) : "" };
  });
  if (tbl) break;
  await sleep(1000);
}
check("B4 nav 到位后表格自动重建", !!tbl, tbl ? `${tbl.rows} 行` : "90s 内未出表");
if (tbl) {
  check("B5 重建表列头含 G/H/I", ["G", "H", "I"].every((m) => tbl.ths.includes(m)), `ths=${tbl.ths.join(",")}`);
  check("B6 重建表 G/H/I pin 行有数值", /[0-9]/.test(tbl.pinText), `pin=${tbl.pinText}`);
  await page.screenshot({ path: "/tmp/gih-evo-weaknet-rebuilt-v3.png" });
}
check("B7 全链路 __gih_missing_px_ = 0", R.missingPx === 0, `计数=${R.missingPx}`);
check("B8 无 TypeError/undefined/NaN", R.typeErrors.length === 0, `计数=${R.typeErrors.length}`);
check("B9 无 pageerror", R.pageErrors.length === 0, `计数=${R.pageErrors.length}`);
console.log("--- console error 样本 ---");
R.errors.slice(0, 15).forEach((x) => console.log("  E: " + x));

await browser.close();
console.log(`\n==== 第四跑汇总: PASS=${nPass} FAIL=${nFail} ====`);
process.exit(nFail > 0 ? 1 : 0);
