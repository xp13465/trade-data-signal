#!/usr/bin/env node
// 2026-09-22 验收「实操步骤弹窗 第一列 日期+时间 + D+10 hoverpop 交易日链」
// 无痕浏览器 + 零 localStorage, 拦截 lab.min.js 注入本 worktree 源文件_lab.js(未 build 也能测);
// data JSON 从主库 trade-data/static-site/data/ 读真实产物(数据一致性: 展示=产物, 不 mock)。
// 断言事实层(结构/日期文本), 观感用户拍板。
// 用法: cd scripts/playwright-accept && node at_dt_d10_verify.mjs
import { chromium } from "playwright";
import fs from "fs";
import path from "path";

const BASE = "http://localhost:8123/static-site";
const SRC_LAB = fs.readFileSync(path.resolve("../../static-site/lab.js"), "utf8");
const SRC_LAB_CSS = fs.readFileSync(path.resolve("../../static-site/lab.css"), "utf8");
const DATA_DIR = "/Users/linhuichen/code/trade-data/static-site/data";
const readData = (f) => fs.readFileSync(path.join(DATA_DIR, f), "utf8");

let nPass = 0, nFail = 0;
function check(name, cond, detail = "") {
  if (cond) nPass++; else nFail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${name}${detail ? `  [${detail}]` : ""}`);
}

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await ctx.clearCookies();
await ctx.route(/^(?!.*localhost)/, (r) => r.abort());
await ctx.route(/lab.min.js(\?.*)?$/, (r) => r.fulfill({ contentType: "application/javascript", body: SRC_LAB }));
await ctx.route(/lab.min.css(\?.*)?$/, (r) => r.fulfill({ contentType: "text/css", body: SRC_LAB_CSS }));
await ctx.route(/auto_trade_steps\.json(\?.*)?$/, (r) => r.fulfill({ contentType: "application/json", body: readData("auto_trade_steps.json") }));
await ctx.route(/nextday_plan\.json(\?.*)?$/, (r) => r.fulfill({ contentType: "application/json", body: readData("nextday_plan.json") }));

const page = await ctx.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 300)));

await page.goto(BASE + "/index.html#lab?sub=sigkelly", { waitUntil: "domcontentloaded", timeout: 120000 });
const t0 = Date.now();

// 等实操步骤模块出现(主表提醒视图)
let atSteps = null;
for (let i = 0; i < 60; i++) {
  atSteps = await page.evaluate(() => {
    const s = document.querySelector(".auto-trade-steps");
    return s ? s.textContent.slice(0, 120) : null;
  });
  if (atSteps) break;
  await new Promise((r) => setTimeout(r, 1000));
}
check("实操步骤主表已渲染", !!atSteps, atSteps ? atSteps.replace(/\s+/g, " ") : "未找到 .auto-trade-steps");

// 打开「全时间线」弹窗: 点击主表最近一行(带 data-open-date 或 data-date)
const opened = await page.evaluate(() => {
  const row = document.querySelector(".auto-trade-steps-row");
  if (!row) return null;
  row.click();
  return new Promise((res) => setTimeout(() => {
    const ov = document.getElementById("lab-autotrade-steps-overlay");
    const tbl = ov ? ov.querySelector(".auto-trade-steps-modal-table") : null;
    if (!tbl) return res(null);
    const rows = Array.from(tbl.querySelectorAll("tbody tr"));
    return res({
      hasOverlay: !!ov,
      rowCount: rows.length,
      head1: tbl.querySelector("thead th").textContent,
      firstCells: rows.map((r) => r.cells[0] && r.cells[0].textContent.replace(/\s+/g, " ").trim()),
      d10Wraps: ov.querySelectorAll(".auto-trade-steps-d10-wrap").length
    });
  }, 300));
}, 300);
check("全时间线弹窗已打开", !!(opened && opened.hasOverlay), opened ? `rows=${opened.rowCount}` : "未打开");
if (opened && opened.hasOverlay) {
  check("表头第一列=日期+时间", String(opened.head1).includes("日期+时间"), opened.head1);
  const hasDtFormat = opened.firstCells.every((c) => /\d\d-\d\d/.test(c));
  check("第一列均为 MM-DD 日期前缀(日期+时间)", hasDtFormat, JSON.stringify(opened.firstCells.slice(0, 6)));
  const sellCell = opened.firstCells.find((c) => /D\+10/.test(c));
  check("卖出行第一列含卖出日日期+D+10", !!sellCell, sellCell || "无 D+10 行(本日无卖出则忽略, 需换日验证)");
}

// D+10 pop: hover 触发(桌面)断言链路文本
const popInfo = opened && opened.hasOverlay ? await page.evaluate(async () => {
  const ov = document.getElementById("lab-autotrade-steps-overlay");
  const wrap = ov.querySelector(".auto-trade-steps-d10-wrap");
  if (!wrap) return { triggerFound: false };
  wrap.dispatchEvent(new MouseEvent("mouseenter", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 120));
  const pop = ov.querySelector(".auto-trade-steps-d10-pop");
  const txt = pop ? pop.textContent.replace(/\s+/g, " ").trim() : "";
  const style = pop ? getComputedStyle(ov.querySelector(".auto-trade-steps-d10-pop-wrap")).display : "";
  wrap.dispatchEvent(new MouseEvent("mouseleave", { bubbles: true }));
  return { triggerFound: true, shown: style, txt: txt.slice(0, 200) };
}, 300) : null;

if (popInfo && popInfo.triggerFound) {
  check("D+10 触发器存在", true);
  check("hover 后 pop 可见(display!=none)", popInfo.shown !== "none", popInfo.shown);
  check("pop 含交易日链口径(信号日→买入日→卖出日·D+10)", /信号日.*买入日.*卖出日.*D\+10/.test(popInfo.txt), popInfo.txt);
  check("pop 含「信号日后第 10 个交易日」口径(非买入日后)", popInfo.txt.includes("信号日后第 10 个交易日"), popInfo.txt.slice(0, 80));
  check("pop 无「买入日后第 10」误口径", !/买入日后第 ?10/.test(popInfo.txt), "");
} else {
  check("D+10 触发器存在(本弹窗有 sell 行时)", !!(popInfo && popInfo.triggerFound), "当前日期全时间线可能无 sell 行(仅 buy)");
}

// 「查看全部计划」弹窗: 卖出行应有 D+10 徽标(举一反三覆盖)
const allInfo = await page.evaluate(() => {
  const ov = document.getElementById("lab-autotrade-steps-overlay");
  if (ov) { ov.style.display = "none"; ov.innerHTML = ""; }
  const more = document.querySelector(".auto-trade-steps-more-btn");
  if (!more) return null;
  more.click();
  return new Promise((res) => setTimeout(() => {
    const ov2 = document.getElementById("lab-autotrade-steps-overlay");
    const wraps = ov2 ? ov2.querySelectorAll(".auto-trade-steps-d10-wrap").length : 0;
    res({ modalOpen: !!ov2, d10Wraps: wraps });
  }, 300));
}, 300);
if (allInfo) {
  check("「查看全部计划」弹窗打开", allInfo.modalOpen);
  check("全部计划卖出行带 D+10 徽标", allInfo.d10Wraps > 0, `d10Wraps=${allInfo.d10Wraps}`);
}

check("无页面 JS 错误", pageErrors.length === 0, pageErrors.join(" / "));

console.log(`\n结果: PASS=${nPass} FAIL=${nFail}`);
await browser.close();
process.exit(nFail ? 1 : 0);