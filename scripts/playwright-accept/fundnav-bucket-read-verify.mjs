#!/usr/bin/env node
// 验收 fund-nav 桶化「前端读桶取数」页面实测(自测③/④, 2026-09-23 feat/fundnav-bucket)。
// 前置: 本仓库 static-site/app.min.js 已用 build_min.py 重建(含 _fundNavBucket Math.imul + 桶主路径)。
// 策略: 连线上 ss.fx8.store(数据层走线上), route 注入本地 app.min.js + mock R2 桶请求回本地桶文件。
//   - 自测③ 桶主路径: mock r2/nav_bucket/{xx}.json 返回本地全量桶(26370 只), 验弹窗净值走势渲染非空。
//   - 自测④ 旧 per-code 回退: mock r2/nav_bucket/* 404 + r2/fund_nav/{code}.json 返回本地旧 per-code, 验仍渲染。
// 用法: cd scripts/playwright-accept && node fundnav-bucket-read-verify.mjs
import { chromium } from "playwright";
import { readFileSync } from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SITE_ROOT = path.resolve(__dirname, "../../static-site");
const MIN_JS = path.join(SITE_ROOT, "app.min.js");
const FULL_BUCKETS = "/tmp/navbuckettest_full/nav_bucket";
const OLD_PERCODE = "/Users/linhuichen/code/trade-data/static-site/data/fund_nav";

// 基金 code 池: 覆盖 6 个不同桶(与 /tmp 全量桶实测桶名一致)
const TEST_CODES = ["000001", "000003", "000004", "510300", "159915", "005827"];
const BUCKET_RE = /r2\/nav_bucket\/([0-9a-f]{2})\.json/;
const PERCODE_RE = /r2\/fund_nav\/(\d{6})\.json/;

let nPass = 0, nFail = 0;
function check(name, cond, detail = "") {
  if (cond) nPass++; else nFail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
}

async function newCtx(mode /* "bucket" | "fallback" */) {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 960 } });
  await ctx.clearCookies();
  // auth mock 登录(fund_score 特权)
  await ctx.route("**/api/auth/me", (r) => r.fulfill({
    status: 200, contentType: "application/json",
    body: JSON.stringify({ logged_in: true, user: { name: "Verify", avatar: "" }, privileges: ["fund_score", "detailed_view"] }),
  }));
  // 注入本地 app.min.js
  await ctx.route(/app\.min\.js/, (r) => r.fulfill({ path: MIN_JS, contentType: "application/javascript" }));
  // mock R2 桶/旧 per-code
  const reqs = { bucket: 0, percode: 0 };
  await ctx.route(/https:\/\/ss\.fx8\.store\/r2\//, (r) => {
    const url = r.request().url();
    const bm = BUCKET_RE.exec(url);
    const pm = PERCODE_RE.exec(url);
    if (bm) {
      reqs.bucket++;
      if (mode === "fallback") { r.fulfill({ status: 404, body: "no bucket" }); return; }
      const f = path.join(FULL_BUCKETS, `${bm[1]}.json`);
      try { r.fulfill({ path: f, contentType: "application/json" }); }
      catch { r.fulfill({ status: 404, body: "no bucket file" }); }
      return;
    }
    if (pm) {
      reqs.percode++;
      if (mode === "bucket") { r.fulfill({ status: 404, body: "no percode" }); return; }
      const f = path.join(OLD_PERCODE, `${pm[1]}.json`);
      try { r.fulfill({ path: f, contentType: "application/json" }); }
      catch { r.fulfill({ status: 404, body: "no percode file" }); }
      return;
    }
    r.continue();
  });
  const page = await ctx.newPage();
  const pageErrors = [];
  page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 240)));
  await page.goto("https://ss.fx8.store/", { waitUntil: "domcontentloaded", timeout: 120000 });
  return { browser, ctx, page, pageErrors, reqs };
}

// 打开基金评分 tab -> 点击第一只基金行 -> 等净值走势区渲染
async function openFundNav(page) {
  // 用 Playwright 定位器点击「基金评分」主 tab(自动等可见性), 点击后断言 active
  const tabBtn = page.locator(".tabs button", { hasText: "基金评分" });
  let clicked = false;
  for (let i = 0; i < 20; i++) {
    try {
      if (await tabBtn.isVisible()) {
        await tabBtn.click({ timeout: 5000 });
        // 确认切换到基金评分 tab
        const isActive = await page.evaluate(() => {
          const b = [...document.querySelectorAll(".tabs button")].find((e) => (e.textContent || "").trim() === "基金评分");
          return !!(b && b.className.includes("active"));
        });
        if (isActive) { clicked = true; break; }
      }
    } catch (_e) { /* 未就绪, 重试 */ }
    await page.waitForTimeout(1000);
  }
  if (!clicked) return { ok: false, why: "「基金评分」tab 点击后未激活" };
  // 轮询等 subtab-bar 出现(点击后 ~1s 渲染; 冷加载最多 20s)
  let clicked2 = false;
  let lastSub = "";
  let lastDiag = "";
  for (let i = 0; i < 20; i++) {
    await page.waitForTimeout(1000);
    const st = await page.evaluate(() => {
      const sb = document.querySelector(".subtab-bar");
      const active = (document.querySelector("button.active") || {}).textContent || "";
      const nav = [...document.querySelectorAll(".tabs button")].map((b) => ({ t: (b.textContent || "").trim(), a: (b.className || "").includes("active") }));
      return { has: !!sb, txt: sb ? sb.textContent.replace(/\s+/g, " ") : "", active, nav };
    });
    lastSub = st.txt;
    lastDiag = `activeBtn=${st.active} nav=${JSON.stringify(st.nav)}`;
    if (st.has && st.txt.includes("场外基金")) {
      clicked2 = await page.evaluate(() => {
        const el = [...document.querySelectorAll(".subtab-bar *")].find((e) => (e.textContent || "").trim() === "场外基金");
        if (el) { el.click(); return true; }
        return false;
      });
      if (clicked2) break;
    }
  }
  if (!clicked2) return { ok: false, why: `未找到「场外基金」二级 tab 或点击未生效 [subtab='${lastSub}' ${lastDiag}]` };
  await page.waitForTimeout(2500);
  // 基金评分 tab 内第一只基金行(场外基金)
  const row = await page.waitForSelector(".fund-score-row[data-fund-code]", { timeout: 25000 }).catch(() => null);
  if (!row) return { ok: false, why: "未出现 .fund-score-row[data-fund-code]" };
  const code = await row.getAttribute("data-fund-code");
  await row.click();
  await page.waitForTimeout(2000);
  // 弹窗内净值走势区
  const sec = await page.waitForSelector("#fundNavTrendSection", { timeout: 20000 }).catch(() => null);
  return { ok: true, code, sec: !!sec, why: "" };
}

async function main() {
  // ---- 自测③: 桶主路径 ----
  console.log("== 自测③ 桶主路径(读 nav_bucket 渲染) ==");
  let { browser, page, pageErrors, reqs } = await newCtx("bucket");
  let r = await openFundNav(page);
  if (r.ok && r.sec) {
    await page.waitForTimeout(2000);
    const txt = await page.evaluate(() => {
      const sec = document.querySelector("#fundNavTrendSection");
      const lite = sec && sec.querySelector(".etf-trend-lite");
      return {
        htmlLen: sec ? sec.innerHTML.length : 0,
        hasLite: !!lite,
        hasText: sec ? (sec.textContent || "").includes("净值日") : false,
      };
    });
    check("弹窗打开 + 净值走势区渲染", txt.htmlLen > 200 && (txt.hasLite || txt.hasText),
      `code=${r.code} htmlLen=${txt.htmlLen} hasLite=${txt.hasLite} bucketReq=${reqs.bucket}`);
    check("读桶请求命中 nav_bucket/", reqs.bucket >= 1, `bucket reqs=${reqs.bucket}`);
    check("未读旧 per-code(桶主路径不该触发回退)", reqs.percode === 0, `percode reqs=${reqs.percode}`);
  } else {
    check("弹窗打开 + 净值走势区渲染", false, r.why);
  }
  if (pageErrors.length) check("无页面 JS 错误", false, pageErrors.join(" | "));
  else check("无页面 JS 错误", true);
  await browser.close();

  // ---- 自测④: 旧 per-code 回退 ----
  console.log("== 自测④ 旧 per-code 回退(桶 404 -> 回退 fund_nav/{code}.json) ==");
  ({ browser, page, pageErrors, reqs } = await newCtx("fallback"));
  r = await openFundNav(page);
  if (r.ok && r.sec) {
    await page.waitForTimeout(2000);
    const txt = await page.evaluate(() => {
      const sec = document.querySelector("#fundNavTrendSection");
      const lite = sec && sec.querySelector(".etf-trend-lite");
      return {
        htmlLen: sec ? sec.innerHTML.length : 0,
        hasLite: !!lite,
        hasText: sec ? (sec.textContent || "").includes("净值日") : false,
      };
    });
    check("桶 404 回退后仍渲染净值走势", txt.htmlLen > 200 && (txt.hasLite || txt.hasText),
      `code=${r.code} htmlLen=${txt.htmlLen} bucketReq=${reqs.bucket} percodeReq=${reqs.percode}`);
    check("回退确实读了旧 per-code", reqs.percode >= 1, `percode reqs=${reqs.percode}`);
    check("回退前曾尝试读桶", reqs.bucket >= 1, `bucket reqs=${reqs.bucket}`);
  } else {
    check("桶 404 回退后仍渲染净值走势", false, r.why);
  }
  if (pageErrors.length) check("无页面 JS 错误", false, pageErrors.join(" | "));
  else check("无页面 JS 错误", true);
  await browser.close();

  console.log(`\n=== 结果: ${nPass} PASS / ${nFail} FAIL ===`);
  process.exit(nFail ? 1 : 0);
}

main().catch((e) => { console.error("FATAL:", e); process.exit(2); });
