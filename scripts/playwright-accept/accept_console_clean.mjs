#!/usr/bin/env node
// console 洁净度验收：断言无 CSP 违规、无 JS 崩溃（让真告警浮出来）
// 用法: BASE_URL=https://ss.fx8.store node scripts/playwright-accept/accept_console_clean.mjs
// 退出码语义(2026-10-03 加严, 供 main-merge.sh 7.7 哨兵消费):
//   0 = PASS(全部路由可校验且 0 CSP 违规 + 0 pageerror)
//   1 = FAIL(检测到 CSP 违规 / pageerror, 发版应阻断)
//   2 = UNREACHABLE(部分/全部路由加载失败, 未能完整校验 → 不可达, 发版放行但醒目提示)
// 违规优先: 若既不可达又测到违规, 按违规处理(exit 1 阻断)——已知违规不该被不可达掩盖。
import { createRequire } from "module";
// createRequire 相对本脚本所在目录解析 node_modules(playwright-accept 自带依赖),
// 不写死主树绝对路径, worktree/main 双树均可跑。
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const BASE = process.env.BASE_URL || "https://ss.fx8.store";
let pass = 0, fail = 0;
const ok = (n, c, d="") => { c ? pass++ : fail++; console.log(`${c?"PASS":"FAIL"}  ${n}${d?`  [${d}]`:""}`); };
// 跨视口汇总: 违规(阻断) / 未校验路由(不可达)
let cspTotal = 0, perrTotal = 0, gotoFailTotal = 0, gotoRoutesTotal = 0;

async function run(width, isMobile, tag) {
  const ctx = await (await chromium.launch({ headless: true })).newContext({ viewport:{width,height:844}, isMobile, hasTouch:isMobile });
  const page = await ctx.newPage();
  const csp = [], errors = [], pageerrors = [];
  let gotoFail = 0, gotoRoutes = 0;
  page.on("console", m => {
    const t = m.text();
    if (/Content Security Policy|violates the following/i.test(t)) csp.push(t.slice(0,160));
    else if (m.type() === "error") errors.push(t.slice(0,160));
  });
  page.on("pageerror", e => pageerrors.push(String(e).slice(0,160)));
  for (const tab of ["#overview","#market/a-stock","#lab?sub=sigkelly"]) {
    gotoRoutes++;
    try { await page.goto(BASE+"/"+tab, { waitUntil:"domcontentloaded", timeout:60000 }); } catch(e){ gotoFail++; errors.push("GOTO_FAIL "+String(e).slice(0,80)); }
    await page.waitForTimeout(5000);
  }
  cspTotal += csp.length; perrTotal += pageerrors.length;
  gotoFailTotal += gotoFail; gotoRoutesTotal += gotoRoutes;
  console.log(`\n[${tag} ${width}] CSP违规=${csp.length} console.error=${errors.length} pageerror=${pageerrors.length} 路由加载失败=${gotoFail}/${gotoRoutes}`);
  if (errors.length) console.log("  errors:", JSON.stringify([...new Set(errors)].slice(0,5)));
  if (csp.length) console.log("  csp样例:", csp[0]);
  ok(`${tag} 无 CSP 违规`, csp.length === 0, `n=${csp.length}`);
  ok(`${tag} 无 JS 崩溃(pageerror)`, pageerrors.length === 0, `n=${pageerrors.length}`);
  await ctx.close();
}
await run(390, true, "mobile");
await run(1280, false, "desktop");

console.log(`\n汇总: CSP违规=${cspTotal} pageerror=${perrTotal} 路由加载失败=${gotoFailTotal}/${gotoRoutesTotal}`);
if (fail > 0) {
  console.log("❌ console 不洁净(检测到 CSP 违规/pageerror), exit=1");
  process.exit(1);
}
if (gotoFailTotal > 0) {
  console.log("⚠️ [UNREACHABLE] 部分/全部路由加载失败, 未能完整校验 console 洁净度(线上不可达或网络问题), exit=2");
  process.exit(2);
}
console.log(`✅ console 洁净(0 CSP 违规 + 0 pageerror), exit=0`);
process.exit(0);
