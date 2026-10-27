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
//
// 2026-10-28 补: 同名响应头被 Playwright 用 "\n" 拼成一串 ⇒ 必须先把「策略」这一层切开
// (见 splitPolicies / isThirdPartyPolicy), 否则 Cloudflare Script Monitor 注入的 report-only
// 策略会被当成我们的, 它自己拦下的 58 条请求全报 FAIL(详见下方「策略列表切分」段的注释)。

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
 * 校验一次导航「最终落地的 URL」是否仍是我们的 document(2026-10-27 补, 治闸门变瞎)。
 * 病: BASE_URL 指向的站点若发生跨 origin 跳转(CDN/Worker/门户拦截页/登录页), 或落地到同源
 * 但非我们的 document 路径, 旧版照样判 OK ⇒ 三个路由全"正常" ⇒ 静默 exit 0, 等于没校验却报洁净。
 * 所以导航落地后必须再核一次「这是不是我们的页面」, 不是就判 UNREACHABLE(放行+醒目提示)。
 *
 * 返回值与 evaluateRoute 同形: {state, reason}。
 *   跨 origin                    → UNREACHABLE(origin-mismatch)
 *   同源但路径不在 OUR_DOCUMENT_PATHS → UNREACHABLE(path-mismatch)
 *   其它(含拿不到/无法解析的 URL)→ OK(不据此判死, 交给其它判据, 避免把正常情况误判成不可达)
 */
export function evaluateNavigationTarget(
  finalUrl,
  { baseOrigin = "", ourDocumentPaths = OUR_DOCUMENT_PATHS } = {},
) {
  // baseOrigin 缺失(调用方没给 / BASE_URL 非法)时无从判断, 不据此判不可达
  if (!baseOrigin) return { state: ROUTE_OK, reason: null };
  let parsed;
  try {
    parsed = new URL(String(finalUrl == null ? "" : finalUrl).trim());
  } catch {
    return { state: ROUTE_OK, reason: null };
  }
  if (parsed.origin !== baseOrigin) return { state: ROUTE_UNREACHABLE, reason: "origin-mismatch" };
  const path = parsed.pathname || "/";
  if (!ourDocumentPaths.includes(path)) return { state: ROUTE_UNREACHABLE, reason: "path-mismatch" };
  return { state: ROUTE_OK, reason: null };
}

/**
 * 判定一次路由导航的结果。判定顺序即优先级:
 *   1. goto 抛错                          → UNREACHABLE(goto-error)
 *   2. 落地 URL 不是我们的 document        → UNREACHABLE(origin-mismatch / path-mismatch)
 *      (跨 origin / 同源异路径跳转 = 根本没校验到目标页, 必须留痕不可静默放行;
 *       只在调用方传了 finalUrl 时才判, 不传 = 跳过这条, 保持老调用语义不变)
 *   3. cf-mitigated 头 / 挑战标题          → UNREACHABLE(challenge)
 *   4. HTTP 状态码 >= 400                 → UNREACHABLE(http-status)
 *   5. 状态码 null 且上一条路由已不可达      → UNREACHABLE(prev-route-unreachable)
 *      (hash 同文档跳转 page.goto 返回 null 没有新响应; 上一页就是挑战页时不能当成功)
 *   6. 其它                               → OK
 */
export function evaluateRoute({
  status = null,
  title = "",
  cfMitigated = null,
  gotoError = "",
  prevRouteState = null,
  finalUrl = "",
  baseOrigin = "",
} = {}) {
  if (gotoError) return { state: ROUTE_UNREACHABLE, reason: "goto-error" };
  if (finalUrl) {
    const target = evaluateNavigationTarget(finalUrl, { baseOrigin });
    if (target.state === ROUTE_UNREACHABLE) return target;
  }
  if (isChallengePage({ title, cfMitigated })) return { state: ROUTE_UNREACHABLE, reason: "challenge" };
  if (typeof status === "number" && status >= 400) return { state: ROUTE_UNREACHABLE, reason: "http-status" };
  if (status === null && prevRouteState === ROUTE_UNREACHABLE) {
    return { state: ROUTE_UNREACHABLE, reason: "prev-route-unreachable" };
  }
  return { state: ROUTE_OK, reason: null };
}

// ── 策略归属比对(2026-10-27 第 3 轮: 从「看 location 是谁」升级为「看被违反的策略是不是我们的」) ──
//
// 为什么必须改: Chromium 的 msg.location().url 对**内联脚本 / Document** 报的是 document URL,
// 但对外部脚本报的是**脚本自己的 URL**(实测: 我们自己的 app.min.js 发起的违规, location 是 /app.min.js)。
// 旧规则「同源非根路径 ⇒ 一律 INFO」于是把我们自己 bundle 的真违规全降成噪音 ⇒ 闸门变瞎。
// 新规则: 从消息文本里抽出「被违反的 directive 原文」, 与我们文档自己的 CSP 响应头逐 token 比对——
//   等于我们的策略 ⇒ 我们的真违规(FAIL); 不等于(注入/挑战侧, 如 CF jsd 的 connect-src 'none')⇒ INFO。

// 消息里「被违反的 directive 原文」句式(Chromium/Edge 引号包裹; 含
// `Note that 'x' was not explicitly set, so 'default-src' is used as a fallback.` 兜底句式——
// 那种情况引号里写的就是实际生效的那条 fallback directive, 同一个正则直接命中)。
const VIOLATED_DIRECTIVE_RES = [
  /Content Security Policy directive:\s*"([^"]*)"/i,
  /Content Security Policy directive:\s*'([^']*)'/i,
];

// ── Chrome 141 实测的两种方言(2026-10-27 #319, 原文见 /tmp/probe-csp2/out.log) ──
//  ① 内联脚本: ...Content Security Policy directive 'script-src 'self''. Either the 'unsafe-inline' keyword, ...
//     单引号包裹且**没有冒号**, 而且值本身又含单引号 ⇒ 上面两条正则都抽不出(落 unknown ⇒
//     外来注入策略被内联脚本违反时会假红)。
//  ② eval: ...Content Security Policy directive because 'unsafe-eval' is not an allowed source of script: script-src 'self'".
//     名字在冒号后、值在末尾、句号在外; 外层双引号「有的版本带、有的不带」(同批实测两种都有)。
// 这两种不能靠「引号配对」抓(值里的引号会把配对抓歪), 改按 CSP 文法 tokenize:
//   <directive-name> <source>...; 其中带引号的 source 是**封闭关键字集合**,
//   所以单引号包裹的 `'script-src 'self''` 里, 结尾那个包裹引号不会被误吃成一个 source。
const INLINE_DIRECTIVE_MARKER_RE = /Content Security Policy directive\s+'/i;
const EVAL_SOURCE_MARKER_RE = /allowed source of script:\s*/i;
const DIRECTIVE_NAME_RE = /^[A-Za-z][A-Za-z0-9-]*/;
const QUOTED_SOURCE_RE =
  /^'(?:self|none|unsafe-inline|unsafe-eval|unsafe-hashes|strict-dynamic|report-sample|wasm-unsafe-eval|inline-speculation-rules|sha256-[^']*|sha384-[^']*|sha512-[^']*|nonce-[^']*)'/i;
// 裸 source: URL / 主机 / scheme / `*` 等; 遇引号、分号、逗号、空白即停
// (逗号之后是 Chrome 的散文「Either the …」, 不能当成 source 的一部分)。
const BARE_SOURCE_RE = /^[^\s'";,]+/;

/**
 * 从「directive 名 + source-list」片段按 CSP 文法取 token(上面两种新方言专用)。
 * @returns {{directive:string, value:string}|null} null = 片段开头不是合法 directive 名
 */
function tokenizeDirective(segment) {
  let rest = String(segment == null ? "" : segment)
    .replace(/^\s+/, "")
    .replace(/^["']/, ""); // eval 方言的外层双引号时有时无
  const name = DIRECTIVE_NAME_RE.exec(rest);
  if (!name) return null;
  const directive = name[0].toLowerCase();
  rest = rest.slice(name[0].length);
  const values = [];
  for (;;) {
    const ws = /^\s+/.exec(rest);
    if (ws) {
      rest = rest.slice(ws[0].length);
      continue;
    }
    if (!rest) break;
    const quoted = QUOTED_SOURCE_RE.exec(rest);
    if (quoted) {
      values.push(quoted[0]);
      rest = rest.slice(quoted[0].length);
      continue;
    }
    // 包裹引号收尾 / 句子结束 / 引号外的散文: 都表示 directive 到此为止
    if (rest[0] === "'" || rest[0] === '"' || rest[0] === "." || rest[0] === ",") break;
    const bare = BARE_SOURCE_RE.exec(rest);
    if (!bare) break;
    values.push(bare[0]);
    rest = rest.slice(bare[0].length);
  }
  return { directive, value: values.join(" ") };
}

/**
 * source-list 归一化(用于逐 token 比较):
 *  - 小写: CSP 关键字('self'/'none')、scheme、主机名都是 ASCII 大小写不敏感;
 *  - 去多余空白; 去掉每个 token 尾部的 `;`(消息偶尔把结尾分号一起引进来);
 *  - 排序: CSP source-list **顺序无语义**(任一 token 命中即放行), 排序后才比得准。
 * 诚实标注的取舍: URL **路径**部分理论上大小写敏感, 小写化可能把 `/A` 与 `/a` 判成同一值 ⇒ 判 ours(FAIL)。
 * 方向是「宁可假红不假绿」, 可接受。
 */
function canonicalSourceList(tokens) {
  return [...tokens].sort().join(" ");
}

function normalizeDirectiveTokens(raw) {
  return String(raw == null ? "" : raw)
    .trim()
    .split(/\s+/)
    .map((t) => t.replace(/;+$/, "").toLowerCase())
    .filter(Boolean); // 去空白 + 去掉「只剩分号」的 token
}

/**
 * 从一条 CSP 违规消息里抽出被违反的 directive 名与值(纯函数)。
 * @returns {{directive:string, value:string}|null} null = 抽不出(调用方按 unknown fail-closed)
 */
export function extractViolatedDirective(text) {
  const s = typeof text === "string" ? text : "";
  for (const re of VIOLATED_DIRECTIVE_RES) {
    const m = re.exec(s);
    if (!m) continue;
    const tokens = normalizeDirectiveTokens(m[1]).filter(Boolean);
    if (!tokens.length) continue;
    return { directive: tokens[0], value: tokens.slice(1).join(" ") };
  }
  // 新方言: 内联脚本(单引号无冒号) / eval(冒号后名字、末尾值)
  for (const marker of [INLINE_DIRECTIVE_MARKER_RE, EVAL_SOURCE_MARKER_RE]) {
    const m = marker.exec(s);
    if (!m) continue;
    const parsed = tokenizeDirective(s.slice(m.index + m[0].length));
    if (parsed) return parsed;
  }
  return null;
}

// ── 策略列表切分 + 第三方注入策略识别(2026-10-28: 治同名头拼接造成的 58 条假违规) ──
//
// 病(2026-10-28 00:34 实测, 证据 /tmp/main-merge-hardening.log): HTTP 允许同名响应头重复出现
// (CSP 多策略的标准投递方式), 而 Playwright 的 response.headers() 把同名头**用 "\n" 拼成一串**
// (本机双同名头实验实证)。旧版 parsePolicyDirectives 只按 ";" 切 directive, 不认 "\n" / ","
// 这一层「策略」分隔 ⇒ 第二条策略(Cloudflare Script Monitor / Page Shield 注入的 report-only)的
// directive 被并进「我们的策略」表 ⇒ 它自己拦下的请求全被判 our-policy-violated。
// 那次样本: 头声明 1319 字 = 我们的 907 字 + 拼接换行 1 字 + 注入 411 字, 58 条 FAIL 全是误报。
//
// 修法: ① 先切策略(CSP 文法: 策略由 "," 分隔, directive 由 ";" 分隔), ② 正面识别第三方注入策略
// 并排除出 ours, ③ 判定顺序把「directive 比对」提到未知 location 的 fail-closed 之前(仍保住 fail-closed)。

// CSP 规范里的 directive 名(含 CSP2/CSP3 与已废弃项)。用途: 校验「逗号切出来的每段」到底是不是一条策略。
export const KNOWN_CSP_DIRECTIVES = new Set([
  "default-src",
  "script-src",
  "script-src-elem",
  "script-src-attr",
  "style-src",
  "style-src-elem",
  "style-src-attr",
  "img-src",
  "font-src",
  "connect-src",
  "media-src",
  "object-src",
  "frame-src",
  "child-src",
  "worker-src",
  "manifest-src",
  "prefetch-src",
  "fenced-frame-src",
  "navigate-to",
  "form-action",
  "frame-ancestors",
  "base-uri",
  "sandbox",
  "report-uri",
  "report-to",
  "require-trusted-types-for",
  "trusted-types",
  "upgrade-insecure-requests",
  "block-all-mixed-content",
  "plugin-types",
  "require-sri-for",
]);

function policyHasKnownDirective(segment) {
  for (const part of String(segment == null ? "" : segment).split(";")) {
    const tokens = normalizeDirectiveTokens(part);
    if (tokens.length && KNOWN_CSP_DIRECTIVES.has(tokens[0])) return true;
  }
  return false;
}

/**
 * 把一条响应头值切成**独立策略串**列表(纯函数)。
 *  - 先按 "\n" 切: Playwright 对同名头就是这样拼接的(实证);
 *  - 再按 "," 切: CSP 规范的多策略分隔符。**不能无脑全局切** —— 逗号也可能出现在 directive 的
 *    值里(如 report-uri 的 URL)。所以逗号切分必须逐段校验: 每一段都必须含一个已知 directive 名,
 *    否则视为切错 ⇒ 该段**退回不切**(fail-safe: 宁可少切一条策略, 也不能把一条策略切坏)。
 *  - 校验失败会打一行日志说明原因(降噪过程必须可追, 不许静默)。
 * 注: 切成多条策略本身只会让「ours 集合」更准确(每条独立判断归属), 不会放宽 FAIL 红线。
 */
export function splitPolicies(raw) {
  if (typeof raw !== "string") return [];
  const out = [];
  for (const line of raw.split(/\r?\n/)) {
    const seg = line.trim();
    if (!seg) continue;
    if (!policyHasKnownDirective(seg)) {
      // 整行都认不出 directive: 原样保留交下游(绝不因认不出就当它不存在)
      console.warn(`[console-attribution] CSP 政策片段认不出已知 directive, 原样保留: ${seg.slice(0, 80)}…`);
      out.push(seg);
      continue;
    }
    const parts = seg.split(",").map((p) => p.trim()).filter(Boolean);
    if (parts.length <= 1) {
      out.push(seg);
      continue;
    }
    if (parts.every(policyHasKnownDirective)) {
      out.push(...parts);
      continue;
    }
    console.warn(`[console-attribution] CSP 头按逗号切分后有不合法策略, 退回整段不切: ${seg.slice(0, 80)}…`);
    out.push(seg);
  }
  return out;
}

const REPORT_DIRECTIVE_NAMES = new Set(["report-uri", "report-to"]);
// Cloudflare Script Monitor / Page Shield 注入策略的已知报告端点(强签名, 与本站 origin 无关也能认)
export const THIRD_PARTY_REPORT_HOSTS = new Set(["csp-reporting.cloudflare.com"]);
const THIRD_PARTY_REPORT_PATH_RE = /cdn-cgi\/script_monitor/i;

function directiveList(policy) {
  const list = [];
  for (const part of String(policy == null ? "" : policy).split(";")) {
    const tokens = normalizeDirectiveTokens(part);
    if (!tokens.length) continue;
    list.push({ name: tokens[0], values: tokens.slice(1) });
  }
  return list;
}

function hostOfValue(value) {
  const v = String(value == null ? "" : value).trim();
  if (!v) return "";
  for (const candidate of [v, v.replace(/^["']|["']$/g, "")]) {
    try {
      return new URL(candidate).host.toLowerCase();
    } catch {
      // 不是绝对 URL(report-to 的端点名就是这样): 换下一种写法
    }
  }
  return "";
}

/**
 * 判断**一条** CSP 策略是不是第三方注入的(纯函数)。
 * 判据: 含 report-uri / report-to, 且报告目标不是本站(尤其 csp-reporting.cloudflare.com /
 * 路径 cdn-cgi/script_monitor = Cloudflare Script Monitor / Page Shield 注入)。
 *
 * 为什么这条判据安全: **我们自己的策略里没有任何 report-uri / report-to**(2026-10-28 已核线上
 * content-security-policy 与 content-security-policy-report-only 两条, 只含 default/script/style/
 * img/font/connect/frame/object/base-uri/form-action/frame-ancestors), 所以「带报告指令 +
 * 报告目标不是本站」只可能来自边缘注入。
 * 反向保守: 报告目标恰好是本站(host 相同)时**不算**第三方 —— 宁可假红(fail-closed)也不假绿。
 * 这个函数只用于「把外来策略排除出 ours 集合」, 不参与任何 FAIL→INFO 的降级决策。
 */
export function isThirdPartyPolicy(policy, { baseOrigin = "" } = {}) {
  if (typeof policy !== "string" || !policy.trim()) return false;
  const reports = directiveList(policy).filter((d) => REPORT_DIRECTIVE_NAMES.has(d.name));
  if (!reports.length) return false; // 我们从不声明报告指令 ⇒ 没有它就不可能被判成第三方
  // ① 强签名: CF Script Monitor / Page Shield(与本机 origin 无关也能认)
  for (const d of reports) {
    for (const v of d.values) {
      if (THIRD_PARTY_REPORT_PATH_RE.test(v)) return true;
      const host = hostOfValue(v);
      if (host && THIRD_PARTY_REPORT_HOSTS.has(host)) return true;
    }
  }
  // ② report-to 的值是端点名(不是 URL、不含 host), 无从比对 host; 我们从不声明 report-to ⇒ 带它的策略是外来的
  if (reports.some((d) => d.name === "report-to")) return true;
  // ③ report-uri 指向的 host 不是本站 ⇒ 第三方(host 相同则保守认定为我们的, 交给 fail-closed)
  const ourHost = hostOfValue(baseOrigin);
  for (const d of reports) {
    if (d.name !== "report-uri") continue;
    for (const v of d.values) {
      const host = hostOfValue(v);
      if (host && ourHost && host !== ourHost) return true;
    }
  }
  return false;
}

/**
 * 把我们的 CSP 策略字符串(可多条: enforce + report-only, 见 driver; 每条还可能是同名头拼接串)
 * 解析成 directive → 值集合。
 *  ① 每串先 splitPolicies 切成独立策略(治 2026-10-28 同名头 "\n" 拼接根因);
 *  ② 第三方注入策略(CF Script Monitor 等)排除出 ours —— 它们不是我们声明的, 其违规不该判 FAIL;
 *  ③ 同名 directive 出现在多条策略里时全部收进集合(任一命中即算我们的)。
 * @param {{baseOrigin?:string}} [opts] baseOrigin 用于判断报告端点是否本站(缺省 = 只认强签名)
 */
export function parsePolicyDirectives(ourPolicies = [], { baseOrigin = "" } = {}) {
  const map = new Map();
  const list = Array.isArray(ourPolicies) ? ourPolicies : [];
  for (const raw of list) {
    if (typeof raw !== "string") continue;
    for (const policy of splitPolicies(raw)) {
      if (isThirdPartyPolicy(policy, { baseOrigin })) continue;
      for (const part of policy.split(";")) {
        const tokens = normalizeDirectiveTokens(part);
        const [name, ...rest] = tokens;
        if (!name) continue;
        if (!map.has(name)) map.set(name, new Set());
        map.get(name).add(canonicalSourceList(rest));
      }
    }
  }
  return map;
}

/**
 * 比对「消息引用的 directive」与我们自己的策略(纯函数, 可单测)。
 * @returns {{relation:"ours"|"foreign"|"unknown", directive:string, value:string}}
 *   ours    = 我们策略里有同名 directive 且值逐 token 相同 ⇒ 这条违规是我们自己的策略造成的
 *   foreign = 同名 directive 存在但值不同, 或我们策略里根本没有这个 directive(不可能是我们的策略原文)
 *   unknown = 消息里抽不出 directive / 抽出来没有值 / 拿不到我们的策略(空) ⇒ 调用方 fail-closed
 */
export function compareDirectiveToOurPolicy(text, ourPolicies = [], { baseOrigin = "" } = {}) {
  const parsed = extractViolatedDirective(text);
  if (!parsed || !parsed.value) {
    return { relation: "unknown", directive: parsed ? parsed.directive : "", value: parsed ? parsed.value : "" };
  }
  const ours = parsePolicyDirectives(ourPolicies, { baseOrigin });
  if (!ours.size) return { relation: "unknown", directive: parsed.directive, value: parsed.value };
  const values = ours.get(parsed.directive);
  if (!values) return { relation: "foreign", directive: parsed.directive, value: parsed.value };
  const want = canonicalSourceList(parsed.value.split(/\s+/).filter(Boolean));
  for (const v of values) {
    if (v === want) return { relation: "ours", directive: parsed.directive, value: parsed.value };
  }
  return { relation: "foreign", directive: parsed.directive, value: parsed.value };
}

function routeInfo(route) {
  return {
    state: route && route.state ? route.state : "PENDING",
    reason: route && route.reason ? route.reason : "",
    url: (route && route.url) || "",
  };
}

/**
 * 归因一条 CSP 消息(纯函数)。判定顺序即优先级:
 *   1. 不是 CSP 违规文本                → INFO(not-csp)
 *   2. about:/data:/blob: 继承父策略 frame → INFO(inherited-frame)
 *   3. 第三方 origin                    → INFO(third-party-origin, 无条件: 第三方 iframe 自带策略)
 *   4. 同源但这次导航不可达(挑战/4xx/加载失败) → INFO(challenge-document / route-unreachable)
 *   5. location 空/无法解析 + 这次导航不是 OK → INFO(unattributable-url)
 *   6. 其余(我们的 document / 我们自己的静态资源如 app.min.js / location 空但我们这次导航正常)
 *      → 走「策略归属比对」(⚠️ 2026-10-28 起这条**提前**到未知 location 的 fail-closed 之前):
 *        ours    ⇒ FAIL(our-policy-violated)
 *        foreign ⇒ INFO(foreign-policy(注入/挑战侧))
 *        unknown ⇒ FAIL(fail-closed: 我们路由正常且 location 空 ⇒ unlocated-message-on-our-route,
 *                   其余 ⇒ our-policy-unverifiable)
 *
 * @param {{text?:string, locationUrl?:string}} msg
 *        locationUrl = msg.location().url。**实测口径(2026-10-27)**:
 *        内联脚本 / Document 发起的违规 ⇒ 报的是 document 的 URL;
 *        外部脚本(如我们自己的 app.min.js / common.js)发起的违规 ⇒ 报的是**脚本自己的 URL**。
 *        所以「location 是同源非根路径」并不等于「不是我们的违规」—— 归属必须看被违反的是谁家策略。
 * @param {{baseOrigin?:string, route?:object, ourPolicies?:string[]}} ctx
 *        route        = 这条消息发生时正在校验的那次导航(最终判定在导航结束后回填, 见 accept_console_clean.mjs)
 *        ourPolicies  = 我们文档自己的 CSP 策略头原文(enforce + report-only 两条都收, 见 driver)
 * @returns {{verdict:string, docUrl:string, reason:string}}
 *
 * 其余规则要点:
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

  const { baseOrigin = "", route = null, ourPolicies = [] } = ctx;
  const r = routeInfo(route);
  const kind = documentUrlKind(docUrl, { baseOrigin });

  if (kind === "inherited-frame") {
    return { verdict: VERDICT_INFO, docUrl, reason: "inherited-frame(about:/data:/blob: 无法定位父 document)" };
  }
  if (kind === "third-party-origin") {
    // E10: 恒 INFO —— 第三方 iframe 自己的策略即使文本与我们的完全相同, 也不能误判成我们的 FAIL
    return { verdict: VERDICT_INFO, docUrl, reason: "third-party-origin" };
  }

  // 到这里 = 同源(我们的 document, 或我们自己的静态资源 / 同源子页面), 或 location 空/无法解析。
  // 若这次导航本身没校验成(挑战页 / 4xx / 加载失败), 这条违规不属于我们的策略。
  if (kind !== "unknown" && r.state === ROUTE_UNREACHABLE) {
    return {
      verdict: VERDICT_INFO,
      docUrl,
      reason: r.reason === "challenge" ? "challenge-document" : `route-unreachable(${r.reason})`,
    };
  }
  // location 空/无法解析 且 这次导航不是正常加载完的: 无从归因(旧口径不变)
  if (kind === "unknown" && r.state !== ROUTE_OK) {
    return { verdict: VERDICT_INFO, docUrl, reason: "unattributable-url" };
  }

  // 归属靠「被违反的 directive 是不是我们文档自己的策略」——不看 location 是谁(外部脚本报的是脚本 URL)。
  // ⚠️ 2026-10-28 判定顺序调整: 这一步必须在「未知 location ⇒ fail-closed」之前, 否则 location 空、
  //    但文本明确引用外来注入策略(CF jsd 的 script-src 'unsafe-inline' 'unsafe-eval')的那条仍会假红。
  const cmp = compareDirectiveToOurPolicy(text, ourPolicies, { baseOrigin });
  if (cmp.relation === "ours") return { verdict: VERDICT_FAIL, docUrl, reason: "our-policy-violated" };
  if (cmp.relation === "foreign") return { verdict: VERDICT_INFO, docUrl, reason: "foreign-policy(注入/挑战侧)" };
  // 拿不到我们的策略 / 抽不出 directive: fail-closed(保持旧版严格度, 宁可假红不假绿)
  if (kind === "unknown") {
    return { verdict: VERDICT_FAIL, docUrl: docUrl || r.url, reason: "unlocated-message-on-our-route" };
  }
  return { verdict: VERDICT_FAIL, docUrl, reason: "our-policy-unverifiable" };
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
 * 按「判定 + 报告来源 location + 原因」分组计数。
 * 计数口径: count = 累计条数(浏览器每报一次记 1, 不去重);
 *           uniqueCount = 同一完整文本只算 1(看「一类问题刷了多少条」)。
 * 单帧/多帧重复上报都能被这两列同时表达, 不丢信息。
 * 注意 docUrl 字段 = msg.location().url: 内联脚本/Document 报 document URL, 外部脚本报**脚本 URL**;
 * 它只用于分组排障, 不参与「算不算我们的违规」判定(判定看 compareDirectiveToOurPolicy)。
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