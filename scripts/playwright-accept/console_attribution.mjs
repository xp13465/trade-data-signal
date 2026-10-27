#!/usr/bin/env node
// console 哨兵的「归因」纯函数模块(2026-10-27)。
//
// 为什么单独成模块: 哨兵要能自动化测试 + 变异判别力验证(把归因规则改坏, 用例必须变红),
// 而 Playwright 驱动逻辑无法离线测。本模块零依赖、不 import playwright, 可单跑 node --test。
//
// 要解决的病: 2026-10-27 13:35 哨兵报 desktop CSP 违规=136, 但只有截断到 160 字的文本、
// 没有来源 document URL ⇒ 无法归因、无法复现, 白阻了一次纯文档发版。13 次复跑全 0 违规后
// 只能推断是临时抖动(疑为 Cloudflare 挑战页/子 frame 噪音)。所以本模块的职责是:
//   一条 CSP 消息 + 它发生在哪次导航  ⇒  判「算我们的真违规(FAIL)」还是「别人的噪音(INFO)」。

// 哨兵要走的三个路由(与改前逐字一致)。hash 路由: 真实 document 恒为站点根 /。
export const DEFAULT_ROUTE_TABS = ["#overview", "#market/a-stock", "#lab?sub=sigkelly"];

// 「我们的 document」的路径形态。hash 路由下 document 只会落在 / 或显式 /index.html。
export const OUR_DOCUMENT_PATHS = ["/", "/index.html"];

// CSP 违规消息识别: 与改前判据逐字一致(Content Security Policy / violates the following)。
export const CSP_TEXT_RE = /Content Security Policy|violates the following/i;

// Cloudflare 挑战/拦截页标题特征(任务书点名的四类 + 常见变体)。
export const CHALLENGE_TITLE_RE =
  /just a moment|checking your browser|attention required|verify you are human|enable javascript and cookies/i;

export const VERDICT_FAIL = "FAIL";
export const VERDICT_INFO = "INFO";

export const ROUTE_OK = "OK";
export const ROUTE_UNREACHABLE = "UNREACHABLE";

export function isCspText(text) {
  return typeof text === "string" && CSP_TEXT_RE.test(text);
}

export function baseOriginOf(baseUrl) {
  try {
    return new URL(String(baseUrl)).origin;
  } catch {
    return "";
  }
}

/**
 * 归一化 BASE_URL: 去掉尾部斜杠。
 * 不改的话 BASE_URL 带尾斜杠会拼出 `https://x//#overview`(document 路径变成 `//`),
 * 归类会落到「同源非路由路径」⇒ 真违规被当噪音, 哨兵自己把自己弄瞎。
 */
export function normalizeBase(baseUrl) {
  return String(baseUrl || "").trim().replace(/\/+$/, "");
}

/**
 * 判定一条消息的「报告 document URL」属于哪一类(只看 URL, 不看导航上下文):
 *  - our-document            我们的路由 document(同源 + 根路径 / 或 /index.html)
 *  - same-origin-other-path  同源, 但不是我们的路由 document(如挑战侧的 /cdn-cgi/... 页面)
 *  - third-party-origin      其它 origin
 *  - inherited-frame         about:blank / about:srcdoc / data: / blob:(继承父 document 的策略)
 *  - unknown                 空 / 不是字符串 / 无法解析
 */
export function documentUrlKind(rawUrl, { baseOrigin, ourDocumentPaths = OUR_DOCUMENT_PATHS } = {}) {
  if (typeof rawUrl !== "string") return "unknown";
  const u = rawUrl.trim();
  if (!u) return "unknown";
  const lower = u.toLowerCase();
  if (lower.startsWith("about:") || lower.startsWith("data:") || lower.startsWith("blob:")) return "inherited-frame";
  let parsed;
  try {
    parsed = new URL(u);
  } catch {
    return "unknown";
  }
  if (!baseOrigin || parsed.origin !== baseOrigin) return "third-party-origin";
  const path = parsed.pathname || "/";
  return ourDocumentPaths.includes(path) ? "our-document" : "same-origin-other-path";
}

/**
 * 挑战页识别: cf-mitigated 响应头(CF 挑战标志, **头存在即算**, 值为 "challenge")
 * 或 document.title 命中挑战标题。
 * 注意 cfMitigated 传 null/undefined = 没有这个头(调用方用 hasOwnProperty 判定)。
 */
export function isChallengePage({ title, cfMitigated } = {}) {
  if (cfMitigated !== undefined && cfMitigated !== null) return true;
  return typeof title === "string" && CHALLENGE_TITLE_RE.test(title);
}

/**
 * 判定一次路由导航的结果。判定顺序即优先级:
 *   1. goto 抛错                          → UNREACHABLE(goto-error)
 *   2. cf-mitigated 头 / 挑战标题          → UNREACHABLE(challenge)
 *   3. HTTP 状态码 >= 400                 → UNREACHABLE(http-status)
 *   4. 状态码 null 且上一条路由已不可达      → UNREACHABLE(prev-route-unreachable)
 *      (hash 同文档跳转 page.goto 返回 null 没有新响应; 上一页就是挑战页时不能当成功)
 *   5. 其它                               → OK
 */
export function evaluateRoute({
  status = null,
  title = "",
  cfMitigated = null,
  gotoError = "",
  prevRouteState = null,
} = {}) {
  if (gotoError) return { state: ROUTE_UNREACHABLE, reason: "goto-error" };
  if (isChallengePage({ title, cfMitigated })) return { state: ROUTE_UNREACHABLE, reason: "challenge" };
  if (typeof status === "number" && status >= 400) return { state: ROUTE_UNREACHABLE, reason: "http-status" };
  if (status === null && prevRouteState === ROUTE_UNREACHABLE) {
    return { state: ROUTE_UNREACHABLE, reason: "prev-route-unreachable" };
  }
  return { state: ROUTE_OK, reason: null };
}

function routeInfo(route) {
  return {
    state: route && route.state ? route.state : "PENDING",
    reason: route && route.reason ? route.reason : "",
    url: (route && route.url) || "",
  };
}

/**
 * 归因一条 CSP 消息(纯函数)。
 * @param {{text?:string, locationUrl?:string}} msg
 *        locationUrl = msg.location().url —— Chromium 报的是**发出这条消息的 document/frame** 的 URL
 *        (子 frame 的 console 也会被 page.on('console') 收到, 此时 url 是子 frame 的 URL)。
 * @param {{baseOrigin?:string, route?:object}} ctx
 *        route = 这条消息发生时正在校验的那次导航(最终判定在导航结束后回填, 见 accept_console_clean.mjs)
 * @returns {{verdict:string, docUrl:string, reason:string}}
 *
 * 规则要点:
 *  ① 「同源」不等于「我们的」: Cloudflare 挑战页也可能是同源 document(URL 仍是 ss.fx8.store)。
 *     所以同源还必须叠加 route 判定 —— 判成挑战/加载失败的那次导航, 其 document 的违规降级 INFO。
 *  ② about: / data: / blob: 这类继承父策略的 frame: 拿不到父 frame(Playwright ConsoleMessage 不暴露
 *     所属 Frame), 保守降级 INFO。取舍代价见 README「已知取舍」: 万一我们自己页面里的 srcdoc
 *     iframe 触发违规会被当噪音; 目前站点无 srcdoc 用法(grep static-site 零命中), 风险可接受。
 *  ③ 空/无法解析的 location(浏览器自产消息常见): 用「这次导航是谁」兜底 —— 正在校验的路由
 *     加载正常 ⇒ 算我们的(不把真违规弄瞎); 挑战/失败/未在导航窗口 ⇒ INFO。
 */
export function attributeCspMessage(msg = {}, ctx = {}) {
  const text = typeof msg.text === "string" ? msg.text : "";
  const docUrl = typeof msg.locationUrl === "string" ? msg.locationUrl : "";
  if (!isCspText(text)) return { verdict: VERDICT_INFO, docUrl, reason: "not-csp" };

  const { baseOrigin = "", route = null } = ctx;
  const r = routeInfo(route);
  const kind = documentUrlKind(docUrl, { baseOrigin });

  if (kind === "unknown") {
    if (r.state === ROUTE_OK) {
      return { verdict: VERDICT_FAIL, docUrl: docUrl || r.url, reason: "unlocated-message-on-our-route" };
    }
    return { verdict: VERDICT_INFO, docUrl, reason: "unattributable-url" };
  }
  if (kind === "inherited-frame") {
    return { verdict: VERDICT_INFO, docUrl, reason: "inherited-frame(about:/data:/blob: 无法定位父 document)" };
  }
  if (kind === "third-party-origin") {
    return { verdict: VERDICT_INFO, docUrl, reason: "third-party-origin" };
  }
  if (kind === "same-origin-other-path") {
    return { verdict: VERDICT_INFO, docUrl, reason: "same-origin-non-route-document" };
  }

  // 到这里 = our-document。若这次导航本身没校验成(挑战页 / 4xx / 加载失败), 违规不属于我们。
  if (r.state === ROUTE_UNREACHABLE) {
    return {
      verdict: VERDICT_INFO,
      docUrl,
      reason: r.reason === "challenge" ? "challenge-document" : `route-unreachable(${r.reason})`,
    };
  }
  return { verdict: VERDICT_FAIL, docUrl, reason: "our-route-document" };
}

/**
 * 归因一条 pageerror: 只有「我们的路由正常加载」时的崩溃才算我们的 FAIL。
 * 挑战页/加载失败路由抛的错是对方页面带来的(与 CSP 同一降噪原则, 否则挑战页照样假红阻断发版)。
 * 说明: pageerror 拿不到来源 document URL, 只能按「这次导航是谁」归因。
 */
export function attributePageError(errorText, ctx = {}) {
  const r = routeInfo(ctx.route || null);
  if (r.state === ROUTE_UNREACHABLE) {
    return {
      verdict: VERDICT_INFO,
      docUrl: r.url,
      reason: r.reason === "challenge" ? "challenge-page-error" : `route-unreachable(${r.reason})`,
    };
  }
  return { verdict: VERDICT_FAIL, docUrl: r.url, reason: "our-route-pageerror" };
}

/**
 * 按「判定 + 报告 document URL + 原因」分组计数。
 * 计数口径: count = 累计条数(浏览器每报一次记 1, 不去重);
 *           uniqueCount = 同一完整文本只算 1(看「一类问题刷了多少条」)。
 * 单帧/多帧重复上报都能被这两列同时表达, 不丢信息。
 */
export function groupByDocument(records = []) {
  const map = new Map();
  for (const r of records) {
    const verdict = r.verdict || VERDICT_INFO;
    const docUrl = r.docUrl || "(未知)";
    const reason = r.reason || "";
    const key = JSON.stringify([verdict, docUrl, reason]);
    let g = map.get(key);
    if (!g) {
      g = { verdict, docUrl, reason, count: 0, texts: new Set() };
      map.set(key, g);
    }
    g.count += 1;
    if (r.text) g.texts.add(r.text);
  }
  return [...map.values()]
    .map((g) => ({ ...g, uniqueCount: g.texts.size, samples: [...g.texts].slice(0, 3) }))
    .sort((a, b) => b.count - a.count);
}

/**
 * 退出码契约(2026-10-03 加严版, 本次保持不变): 0 洁净 / 1 真违规 / 2 不可达。
 * 违规优先于不可达(已知违规不该被不可达掩盖)。INFO 噪音两项都不计。
 */
export function decideExitCode({ failCount = 0, unreachableRoutes = 0 } = {}) {
  if (failCount > 0) return 1;
  if (unreachableRoutes > 0) return 2;
  return 0;
}