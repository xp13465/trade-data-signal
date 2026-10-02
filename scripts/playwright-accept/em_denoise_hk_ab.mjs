// Finding1(港股错位日放行) + Finding2(applyMode stale snap) 浏览器实测
// 前置: python3 -m http.server 8099 -d static-site(worktree内)
// 用法: APP_SRC=<改前或改后 app.js 路径> node scripts/playwright-accept/em_denoise_hk_ab.mjs
//   before 用 git show df024ea5f:static-site/app.js > /tmp/app_before.js 生成改前源码
// A股分时实时主路径=同花顺批量(d.10jqka.com.cn/v6/time/*/last.js), 港股=腾讯 minute/query; 东财 trends2 只兜底。
// 判定"点仅分时后新拉实时": 点击前取一次请求快照, 点击后统计新增请求(差量), 排除点击前已发生的。
import { createRequire } from "module";
import { readFileSync } from "fs";
const require = createRequire("/Users/linhuichen/code/trade/.claude/worktrees/agent-ae2f7cfb35006f345/scripts/playwright-accept/");
const { chromium } = require("playwright");
const APP_SRC = process.env.APP_SRC || "/Users/linhuichen/code/trade/.claude/worktrees/agent-ae2f7cfb35006f345/static-site/app.js";
const TAG = process.env.TAG || "after";
const appSrc = readFileSync(APP_SRC, "utf8");
const b = await chromium.launch({ headless: true });

function classifyUrls(urls) {
  const em = new Set(urls.em.map(u => { const m = u.match(/secid=([\d.]+)/); return m ? m[1] : "?"; }));
  const qq = new Set(urls.qq.map(u => { const m = u.match(/code=([^&]+)/); return m ? m[1] : "?"; }));
  const hkEm = ["100.HSI","124.HSTECH","100.HSCEI"].filter(c => em.has(c));
  const hkQq = ["hkHSI","hkHSTECH","hkHSCEI"].filter(c => qq.has(c));
  const aEm = ["1.000001","0.399001","1.000300","1.000016","0.399006","1.000688","0.899050","1.000905","1.000852"].filter(c => em.has(c));
  return { hkEm, hkQq, aEm, aThs: urls.ths.length, emCount: urls.em.length, qqCount: urls.qq.length };
}

async function setupRoutes(page) {
  await page.route("**/*.json*", async (route) => {
    const u = new URL(route.request().url());
    if (u.pathname.startsWith("/data/")) {
      try {
        const resp = await route.fetch({ url: "https://ss.fx8.store" + u.pathname + (u.search || "") });
        await route.fulfill({ response: resp });
      } catch (e) { await route.abort(); }
      return;
    }
    await route.continue();
  });
  await page.route("**/app.min.js*", async (route) => {
    await route.fulfill({ contentType: "application/javascript", body: appSrc });
  });
}

// 首次解释/新手引导弹窗会拦截 segment 点击,先关掉任何可见 rule-modal
async function dismissModals(page) {
  await page.evaluate(() => {
    const m = document.querySelector(".rule-modal:not(.hidden)");
    if (!m) return;
    const skip = m.querySelector(".onboarding-skip");
    if (skip) skip.click();
    else {
      const close = m.querySelector(".rule-modal-close");
      if (close) close.click();
      else {
        const ov = m.querySelector(".rule-modal-overlay");
        if (ov) ov.click();
      }
    }
  });
  await page.waitForTimeout(300);
}

// ========== Finding1: 真实今日(A股休市 snap=9-30, 默认collapsed)点"仅分时" ==========
// 改前行为: 顶层休市短路所有code -> 港股也冻结(FAIL); 改后: 港股放行实时, A股仍拦(不拉实时)
{
  const ctx2 = await b.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: "block" });
  const page2 = await ctx2.newPage();
  const urls = { em: [], qq: [], ths: [] };
  page2.on("request", (r) => {
    const u = r.url();
    if (u.includes("trends2")) urls.em.push(u);
    if (u.includes("minute/query")) urls.qq.push(u);
    if (u.includes("10jqka") || u.includes("last.js")) urls.ths.push(u);
  });
  await setupRoutes(page2);
  await page2.goto("http://localhost:8099/#overview", { waitUntil: "domcontentloaded", timeout: 90000 });
  await page2.waitForTimeout(12000);
  const bootSnap = await page2.evaluate(() => {
    const s = state && state.intradaySnapshot;
    if (!s || !s.indices) return null;
    const sh = s.indices.find(i => i.code === "sh000001");
    const hk = s.indices.find(i => i.code === "hkHSI");
    return { is_closed: s.is_closed, shDate: sh ? sh.datetime.slice(0, 10) : "", hkDate: hk ? hk.datetime.slice(0, 10) : "" };
  });
  const defaultMode = await page2.evaluate(() => {
    const seg = document.querySelector(".intraday-seg-group");
    const a = seg && seg.querySelector(".intraday-seg.active");
    return a ? a.getAttribute("data-mode") : "no-seg";
  });
  console.log(`[${TAG}·F1] boot snap: is_closed=${bootSnap && bootSnap.is_closed} sh=${bootSnap && bootSnap.shDate} hkHSI=${bootSnap && bootSnap.hkDate} | 默认mode=${defaultMode}`);
  const before1 = { em: urls.em.slice(), qq: urls.qq.slice(), ths: urls.ths.slice() };
  await dismissModals(page2);
  await page2.click('.intraday-seg[data-mode="intraday-only"]', { force: true });
  await page2.waitForTimeout(7000);
  const new1 = { em: urls.em.filter(u => !before1.em.includes(u)), qq: urls.qq.filter(u => !before1.qq.includes(u)), ths: urls.ths.filter(u => !before1.ths.includes(u)) };
  const c1 = classifyUrls(new1);
  console.log(`[${TAG}·F1] 点仅分时后新增: A股-THS=${c1.aThs} A股-EM=${JSON.stringify(c1.aEm)} HK-EM=${JSON.stringify(c1.hkEm)} HK-QQ=${JSON.stringify(c1.hkQq)}`);
  console.log(`[${TAG}·F1] 判定: 港股放行实时=${(c1.hkEm.length + c1.hkQq.length) > 0 ? "YES(有实时请求)" : "NO(被短路冻结)"} | A股休市不拉实时=${(c1.aThs === 0 && c1.aEm.length === 0) ? "YES(0请求)" : "NO(有THS" + c1.aThs + "/EM" + c1.aEm.length + "请求)"}`);
  await page2.close();
}

// ========== Finding2: boot snap=昨日(9-30), 注入盘中 snap 到 state 同帧点"仅分时" ==========
// 改前: applyMode 闭包引用 boot snap(9-30休市) -> A股仍拦(FAIL); 改后: 用 state.intradaySnapshot 最新盘中 -> A股放行
{
  const ctx3 = await b.newContext({ viewport: { width: 1280, height: 900 }, serviceWorkers: "block" });
  const page3 = await ctx3.newPage();
  const urls = { em: [], qq: [], ths: [] };
  page3.on("request", (r) => {
    const u = r.url();
    if (u.includes("trends2")) urls.em.push(u);
    if (u.includes("minute/query")) urls.qq.push(u);
    if (u.includes("10jqka") || u.includes("last.js")) urls.ths.push(u);
  });
  await setupRoutes(page3);
  await page3.goto("http://localhost:8099/#overview", { waitUntil: "domcontentloaded", timeout: 90000 });
  await page3.waitForTimeout(12000);
  await dismissModals(page3);
  const before2 = { em: urls.em.slice(), qq: urls.qq.slice(), ths: urls.ths.slice() };
  // 点击前容器应为空(休市 collapsed 不渲染),探针确认
  const preClickProbe = await page3.evaluate(() => {
    const sparkEls = document.querySelectorAll(".spark-intraday[data-intraday-code]");
    const withChild = Array.from(sparkEls).filter((el) => el.querySelector("div") || el.querySelector("canvas")).length;
    const sh = document.querySelector('.spark-intraday[data-intraday-code="sh"]');
    return {
      sparkCount: sparkEls.length,
      withChild,
      snapClosed: state.intradaySnapshot ? state.intradaySnapshot.is_closed : "no-snap",
      shHtml: sh ? sh.innerHTML.slice(0, 200) : "no-sh",
      shClass: sh ? sh.className : "no-sh",
    };
  });
  console.log(`[${TAG}·F2] 点击前探针: spark容器=${preClickProbe.sparkCount} 已有子节点=${preClickProbe.withChild} state.is_closed=${preClickProbe.snapClosed} | sh.class=${preClickProbe.shClass} shHtml=${preClickProbe.shHtml}`);
  // 注入"今日盘中"snap 到 state(模拟 9:15 后 overview 刷新拉到新快照)并**同帧点击**: applyMode 读 state.intradaySnapshot=最新盘中snap
  const fresh = await page3.evaluate(() => {
    // 先等 seg 出现(改前/改后 boot 渲染时点可能有差异, 最多等 8s)
    return (async () => {
      const waitSeg = async () => {
        for (let i = 0; i < 80; i++) {
          const s = document.querySelector('.intraday-seg[data-mode="intraday-only"]');
          if (s) return s;
          await new Promise((res) => setTimeout(res, 100));
        }
        return null;
      };
      const snap = await fetch("https://ss.fx8.store/data/intraday_snapshot.json").then(r => r.json());
      const d = new Date(Date.now() + 8 * 3600000);
      const todayStr = d.getUTCFullYear() + String(d.getUTCMonth() + 1).padStart(2, "0") + String(d.getUTCDate()).padStart(2, "0");
      snap.is_closed = false;
      for (const i of snap.indices || []) {
        const base = (i.datetime && i.datetime.length >= 16) ? i.datetime.slice(11, 16) : "10:30:00";
        if (/^\d{4}-\d{2}-\d{2}/.test(i.datetime)) i.datetime = todayStr + " " + base;
        else i.datetime = todayStr + base;
        if (i.last_date && /^\d{8}$/.test(i.last_date)) i.last_date = todayStr;
      }
      state.intradaySnapshot = snap;
      const seg = await waitSeg();
      if (seg) seg.click();
      return {
        is_closed: snap.is_closed,
        shDate: (snap.indices || []).find(i => i.code === "sh000001").datetime.slice(0, 10),
        stateAtClick: state.intradaySnapshot.is_closed,
        clicked: !!seg,
      };
    })();
  });
  console.log(`[${TAG}·F2] 注入盘中snap+同帧点击: fresh.is_closed=${fresh.is_closed} sh=${fresh.shDate} stateAtClick=${fresh.stateAtClick} clicked=${fresh.clicked}`);
  await page3.waitForTimeout(7000);
  const new2 = { em: urls.em.filter(u => !before2.em.includes(u)), qq: urls.qq.filter(u => !before2.qq.includes(u)), ths: urls.ths.filter(u => !before2.ths.includes(u)) };
  const c2 = classifyUrls(new2);
  const domProbe = await page3.evaluate(() => {
    const segs = document.querySelectorAll(".intraday-seg-group");
    const actives = [];
    segs.forEach((sg) => {
      const a = sg.querySelector(".intraday-seg.active");
      if (a) actives.push(a.getAttribute("data-mode"));
    });
    const sparkEls = document.querySelectorAll(".spark-intraday[data-intraday-code]");
    const withChild = Array.from(sparkEls).filter((el) => el.querySelector("div") || el.querySelector("canvas")).length;
    return {
      segGroups: segs.length,
      activeModes: actives,
      sparkCount: sparkEls.length,
      sparkWithChild: withChild,
      batchCacheKeys: Object.keys(window._batchMinuteCache || {}).length,
    };
  });
  console.log(`[${TAG}·F2] DOM探针: seg组数=${domProbe.segGroups} active=${JSON.stringify(domProbe.activeModes)} spark容器=${domProbe.sparkCount} 已渲染子节点=${domProbe.sparkWithChild} batchCache键=${domProbe.batchCacheKeys}`);
  console.log(`[${TAG}·F2] 点仅分时后新增: A股-THS=${c2.aThs} A股-EM=${JSON.stringify(c2.aEm)} HK-EM=${JSON.stringify(c2.hkEm)} HK-QQ=${JSON.stringify(c2.hkQq)}`);
  console.log(`[${TAG}·F2] 判定: applyMode用最新snap(A股放行盘中)=${(c2.aThs > 0 || c2.aEm.length > 0) ? "YES" : "NO(仍用旧snap被休市拦)"}`);
  await page3.close();
}

await b.close();
