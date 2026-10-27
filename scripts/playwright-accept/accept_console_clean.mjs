#!/usr/bin/env node
// console 洁净度验收：断言无 CSP 违规、无 JS 崩溃（让真告警浮出来）
// 用法: BASE_URL=https://ss.fx8.store node scripts/playwright-accept/accept_console_clean.mjs
// 退出码语义(2026-10-03 加严, 供 main-merge.sh 7.7 哨兵消费):
//   0 = PASS(全部路由可校验且 0 CSP 违规 + 0 pageerror)
//   1 = FAIL(检测到真 CSP 违规 / pageerror, 发版应阻断)
//   2 = UNREACHABLE(部分/全部路由加载失败或命中挑战页, 未能完整校验 → 不可达, 发版放行但醒目提示)
// 违规优先: 若既不可达又测到违规, 按违规处理(exit 1 阻断)——已知违规不该被不可达掩盖。
// INFO 噪音(来源不是我们路由 document 的违规)两项都不计, 只打印出来供归因。
//
// 2026-10-27 可归因化(治「136 条无来源、无法复现、白阻一次发版」):
//   旧版只留 160 字文本、不记来源 document URL, 出事无法归因。现在:
//   ① 每条 CSP 消息记 location(url/line/column) + 完整文本, 按「报告 document URL」分组计数;
//   ② 只有「我们三个路由的 document」产生的违规判 FAIL, 其它(第三方 origin / about:srcdoc /
//      data: / 挑战侧同源 document / 4xx 页)降级 INFO 不阻断;
//   ③ 加挑战页识别(cf-mitigated 头 / 挑战标题)判 UNREACHABLE, 并记录/断言 goto 的 HTTP 状态码;
//   ④ 导航落地后核「是不是我们的 document」(跨 origin / 同源异路径 ⇒ UNREACHABLE), 堵住
//      「跳转到别处 ⇒ 三个路由都算 OK ⇒ 静默 exit 0」的闸门变瞎路径。
//   归类规则是纯函数, 见同目录 console_attribution.mjs;
//   测试: node --test scripts/playwright-accept/console_attribution.test.mjs
import { createRequire } from "module";
import {
  DEFAULT_ROUTE_TABS,
  baseOriginOf,
  normalizeBase,
  isCspText,
  evaluateRoute,
  attributeCspMessage,
  attributePageError,
  groupByDocument,
  decideExitCode,
  ROUTE_OK,
  ROUTE_UNREACHABLE,
  VERDICT_FAIL,
  VERDICT_INFO,
} from "./console_attribution.mjs";
// createRequire 相对本脚本所在目录解析 node_modules(playwright-accept 自带依赖),
// 不写死主树绝对路径, worktree/main 双树均可跑。
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const BASE = normalizeBase(process.env.BASE_URL || "https://ss.fx8.store");
const BASE_ORIGIN = baseOriginOf(BASE);
// 线上经 Cloudflare,默认 Playwright UA 带 "HeadlessChrome" 字样会被判定为机器人,
// 踢到挑战页; 挑战页自身 fetch('data:,...') 会被它自己的 CSP 拦下, 产生与我们无关的
// "CSP 违规"噪音(2026-10-27 实测: 默认 UA 4 条违规/13 次挑战, 真实 UA 0 条/3 次)。
// 用真实 Chrome UA 规避; 如需覆盖可用 SENTINEL_UA 环境变量。
const SENTINEL_UA = process.env.SENTINEL_UA ||
  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36";
let pass = 0, fail = 0;
const ok = (n, c, d="") => { c ? pass++ : fail++; console.log(`${c?"PASS":"FAIL"}  ${n}${d?`  [${d}]`:""}`); };
// 跨视口汇总: 真违规(阻断) / 噪音(INFO) / 未校验路由(不可达+挑战)
let cspFailTotal = 0, cspInfoTotal = 0, perrFailTotal = 0, perrInfoTotal = 0;
let gotoFailTotal = 0, gotoRoutesTotal = 0;

// 单条记录的 location 安全读取(location() 极少数情况下不可读, 不让它打断整轮)
function safeLocation(msg) {
  try {
    const loc = msg.location() || {};
    return { url: loc.url || "", lineNumber: loc.lineNumber ?? 0, columnNumber: loc.columnNumber ?? 0 };
  } catch {
    return { url: "", lineNumber: 0, columnNumber: 0 };
  }
}

async function run(width, isMobile, tag) {
  const ctx = await (await chromium.launch({ headless: true })).newContext({ viewport:{width,height:844}, isMobile, hasTouch:isMobile, userAgent: SENTINEL_UA });
  const page = await ctx.newPage();
  // records: 原始消息(带「发生时的导航」引用; 导航结束后最终判定回填到 route 对象上)
  // routes:  每次导航的最终判定 {tab,url,status,cfMitigated,title,gotoError,state,reason}
  const records = [], routes = [];
  let activeRoute = null;
  page.on("console", m => {
    const t = m.text();
    const loc = safeLocation(m);
    if (isCspText(t)) {
      // CSP 违规: 留完整文本 + 来源 document URL(不再截断到 160 字, 否则无法归因)
      records.push({ type:"csp", text:t, docUrl:loc.url, lineNumber:loc.lineNumber, columnNumber:loc.columnNumber, route:activeRoute });
    } else if (m.type() === "error") {
      records.push({ type:"console-error", text:t.replace(/\s+/g, " ").slice(0,300), docUrl:loc.url, route:activeRoute });
    }
  });
  page.on("pageerror", e => records.push({ type:"pageerror", text:String(e), docUrl:"", route:activeRoute }));

  for (const tab of DEFAULT_ROUTE_TABS) {
    const route = { tab, url: BASE+"/"+tab, status:null, cfMitigated:null, title:"", gotoError:"", finalUrl:"", state:"PENDING", reason:null };
    routes.push(route);
    activeRoute = route; // 之后到达的 console/pageerror 归到这次导航(直到下一次导航开始)
    try {
      const resp = await page.goto(route.url, { waitUntil:"domcontentloaded", timeout:60000 });
      // hash 版路由间跳转是同文档导航, goto 返回 null 没有新响应; 状态码只对真响应有意义。
      if (resp) {
        route.status = resp.status();
        const h = resp.headers() || {};
        route.cfMitigated = Object.prototype.hasOwnProperty.call(h, "cf-mitigated") ? h["cf-mitigated"] : null;
      }
    } catch(e){
      route.gotoError = String(e).slice(0,200);
    }
    await page.waitForTimeout(5000);
    // 挑战页标题可能由脚本后置写入, 取等待后的最终标题再判一次
    try { route.title = await page.title(); } catch { route.title = ""; }
    // 导航落地 URL(含跳转后的最终地址): 跨 origin / 同源异路径 ⇒ 根本没校验到目标页,
    // 必须判 UNREACHABLE 留痕, 不能静默当 OK(否则三道全"通过"= 静默 exit 0)。
    try { route.finalUrl = page.url(); } catch { route.finalUrl = ""; }
    const prev = routes.length >= 2 ? routes[routes.length-2] : null;
    const verdict = evaluateRoute({
      status: route.status,
      title: route.title,
      cfMitigated: route.cfMitigated,
      gotoError: route.gotoError,
      prevRouteState: prev ? prev.state : null,
      finalUrl: route.finalUrl,
      baseOrigin: BASE_ORIGIN,
    });
    route.state = verdict.state;
    route.reason = verdict.reason;
  }

  // 归因(纯函数): 一条消息记在「发生时的导航」下, 用该导航的最终判定决定算不算我们的
  const cspRecords = records.filter(r => r.type === "csp").map(r => ({
    ...r,
    ...attributeCspMessage({ text:r.text, locationUrl:r.docUrl }, { baseOrigin:BASE_ORIGIN, route:r.route }),
  }));
  const perrRecords = records.filter(r => r.type === "pageerror").map(r => ({
    ...r,
    ...attributePageError(r.text, { route:r.route }),
  }));
  const consoleErrors = records.filter(r => r.type === "console-error");

  const cspFail = cspRecords.filter(r => r.verdict === VERDICT_FAIL);
  const cspInfo = cspRecords.filter(r => r.verdict === VERDICT_INFO);
  const perrFail = perrRecords.filter(r => r.verdict === VERDICT_FAIL);
  const perrInfo = perrRecords.filter(r => r.verdict === VERDICT_INFO);
  const unreachable = routes.filter(r => r.state !== ROUTE_OK);

  cspFailTotal += cspFail.length; cspInfoTotal += cspInfo.length;
  perrFailTotal += perrFail.length; perrInfoTotal += perrInfo.length;
  gotoFailTotal += unreachable.length; gotoRoutesTotal += routes.length;

  console.log(`\n[${tag} ${width}] CSP违规=${cspFail.length} CSP噪音(INFO)=${cspInfo.length} console.error=${consoleErrors.length} pageerror=${perrFail.length}(INFO ${perrInfo.length}) 路由加载失败/挑战=${unreachable.length}/${routes.length}`);
  for (const r of routes) {
    const http = r.status === null ? (r.gotoError ? "-" : "(same-document)") : String(r.status);
    const cf = r.cfMitigated ? `  cf-mitigated=${r.cfMitigated}` : "";
    const why = r.reason ? `  原因=${r.reason}` : "";
    // 落地地址与预期不符时把实际地址打出来(否则只有一句 origin-mismatch, 没法归因到跳去哪了)
    const landed = (r.reason === "origin-mismatch" || r.reason === "path-mismatch")
      ? `  落地=${r.finalUrl || "(读不到)"}`
      : "";
    console.log(`  路由 ${r.tab}: HTTP ${http} ${r.state}${why}${landed}${cf}`);
  }
  if (consoleErrors.length) console.log("  errors:", JSON.stringify([...new Set(consoleErrors.map(r => r.text))].slice(0,5)));

  // 按「报告 document URL」分组计数(任务书 E1/E2 的可观测输出)
  const groups = groupByDocument([...cspRecords, ...perrRecords]);
  // 分组表恒打(即使 0 条): 出事时能一眼看出「本次到底有没有可归因记录」, 也便于事后 grep
  console.log("  归因分组(按报告 document URL):");
  if (!groups.length) console.log("    (本视口无 CSP/pageerror 记录)");
  for (const g of groups) {
    console.log(`    [${g.verdict}] ${g.docUrl} × ${g.count}(唯一文本 ${g.uniqueCount})  原因=${g.reason}`);
    for (const s of g.samples) console.log(`      sample: ${s}`);
  }
  // 噪音必须看得见(否则「降级」会变成「吞掉」); 固定前缀 INFO noise: 便于 grep 统计
  for (const g of groups.filter(g => g.verdict === VERDICT_INFO)) {
    console.log(`  INFO noise: ${g.docUrl} × ${g.count}(${g.reason})`);
  }

  ok(`${tag} 无 CSP 违规`, cspFail.length === 0, `fail=${cspFail.length} info噪音=${cspInfo.length}`);
  ok(`${tag} 无 JS 崩溃(pageerror)`, perrFail.length === 0, `fail=${perrFail.length} info=${perrInfo.length}`);
  await ctx.close();
}
await run(390, true, "mobile");
await run(1280, false, "desktop");

console.log(`\n汇总: CSP违规=${cspFailTotal} CSP噪音(INFO)=${cspInfoTotal} pageerror=${perrFailTotal}(INFO ${perrInfoTotal}) 路由加载失败/挑战=${gotoFailTotal}/${gotoRoutesTotal}`);
const rc = decideExitCode({ failCount: fail, unreachableRoutes: gotoFailTotal });
if (rc === 1) {
  console.log("❌ console 不洁净(检测到真 CSP 违规/pageerror), exit=1");
  process.exit(1);
}
if (rc === 2) {
  console.log("⚠️ [UNREACHABLE] 部分/全部路由加载失败或命中挑战页, 未能完整校验 console 洁净度(线上不可达/被挑战/网络问题), exit=2");
  process.exit(2);
}
console.log(`✅ console 洁净(0 CSP 违规 + 0 pageerror, INFO 噪音 ${cspInfoTotal} 条不计), exit=0`);
process.exit(0);