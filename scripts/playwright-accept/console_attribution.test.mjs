// 归因规则自动化测试(node 内置 test runner, 零依赖):
//   node --test scripts/playwright-accept/console_attribution.test.mjs
// 覆盖范围:
//   ① location/route 层归因: E2(第三方/srcdoc/同源非路由路径) · E3(我们的 document) ·
//      E4(挑战页) · E5(HTTP 状态/同文档跳转) · E6(退出码契约) · E7(导航落地校验)
//   ② 2026-10-27 第 3 轮「策略归属」: E7(我们自己的策略被违反⇒FAIL, 含 app.min.js 这类脚本 URL) ·
//      E8(外来注入策略⇒INFO) · E9(拿不到我们的策略⇒fail-closed) · E10(第三方恒 INFO)
//      + compareDirectiveToOurPolicy 三态与归一化
//   ③ 分组计数口径 + 空 location 兜底 + 非 CSP 文本不进违规通道
//   ④ 2026-10-27 #319: Chrome 141 的「内联脚本(单引号无冒号)」「eval(冒号后名字)」两种真实方言
//      (原文逐字取自 /tmp/probe-csp2/out.log) —— E2/E3 用例, 断言抽出 script-src 'self' 并按策略判 ours/foreign
// 变异判别力: 把 compareDirectiveToOurPolicy 改成恒 ours ⇒ E8 类必红; 恒 foreign ⇒ E7/E9 类必红。
// 放同目录顶层而非 tests/ 子目录: .gitignore 只 re-include `scripts/playwright-accept/*.mjs`。
import test from "node:test";
import assert from "node:assert/strict";
import {
  DEFAULT_ROUTE_TABS,
  OUR_DOCUMENT_PATHS,
  CHALLENGE_TITLE_RE,
  VERDICT_FAIL,
  VERDICT_INFO,
  ROUTE_OK,
  ROUTE_UNREACHABLE,
  isCspText,
  baseOriginOf,
  normalizeBase,
  evaluateNavigationTarget,
  documentUrlKind,
  isChallengePage,
  evaluateRoute,
  extractViolatedDirective,
  parsePolicyDirectives,
  compareDirectiveToOurPolicy,
  attributeCspMessage,
  attributePageError,
  groupByDocument,
  decideExitCode,
} from "./console_attribution.mjs";

const BASE = "https://ss.fx8.store";
const ORIGIN = baseOriginOf(BASE);

// 真实形态的 CSP 违规文本(含 directive 值 + blocked URL)。这是**外来注入策略**的典型:
// CF jsd 注入的 report-only 策略 connect-src 'none', 与我们文档自己声明的白名单不同。
const CSP_TEXT =
  "Refused to connect to 'https://push2.eastmoney.com/api/x' because it violates the following " +
  'Content Security Policy directive: "connect-src \'none\'".';

// 我们文档自己的 CSP 策略(取自线上真实响应头的形态: default-src + script-src + connect-src 白名单 + img-src)。
const OUR_POLICY =
  "default-src 'self'; script-src 'self' 'unsafe-inline'; " +
  "connect-src 'self' https://push2.eastmoney.com https://web.ifzq.gtimg.cn; img-src 'self' data:";
const OUR_POLICIES = [OUR_POLICY];

// 引用**我们自己策略**的违规文本(值与我们 connect-src 逐 token 相同) ⇒ 该判 FAIL。
const CSP_TEXT_OURS =
  "Refused to connect to 'https://web.ifzq.gtimg.cn/api/x' because it violates the following " +
  'Content Security Policy directive: "connect-src \'self\' https://push2.eastmoney.com https://web.ifzq.gtimg.cn".';

const OK_ROUTE = { tab: "#overview", url: `${BASE}/#overview`, state: ROUTE_OK, reason: null };
const CHALLENGE_ROUTE = { tab: "#market/a-stock", url: `${BASE}/#market/a-stock`, state: ROUTE_UNREACHABLE, reason: "challenge" };
const HTTP500_ROUTE = { tab: "#lab?sub=sigkelly", url: `${BASE}/#lab?sub=sigkelly`, state: ROUTE_UNREACHABLE, reason: "http-status" };

// 默认**不传 ourPolicies** = 模拟「拿不到我们文档自己的 CSP 策略」⇒ 归因侧 fail-closed(E9);
// 要验「策略归属」请用 attributeWithPolicies 显式传策略(见 E7/E8/E10 用例)。
const attribute = (locationUrl, route = OK_ROUTE, text = CSP_TEXT) =>
  attributeCspMessage({ text, locationUrl }, { baseOrigin: ORIGIN, route });

const attributeWithPolicies = (locationUrl, route, text, ourPolicies) =>
  attributeCspMessage({ text, locationUrl }, { baseOrigin: ORIGIN, route, ourPolicies });

// ── 基础口径 ───────────────────────────────────────────────────────────────
test("约定: 三个路由 tab / document 路径 / 挑战标题正则", () => {
  assert.deepEqual(DEFAULT_ROUTE_TABS, ["#overview", "#market/a-stock", "#lab?sub=sigkelly"]);
  assert.deepEqual(OUR_DOCUMENT_PATHS, ["/", "/index.html"]);
  assert.equal(baseOriginOf(BASE), "https://ss.fx8.store");
  assert.equal(baseOriginOf("not a url"), "");
  // BASE_URL 带尾斜杠会拼出 `//#overview` ⇒ document 路径 `//` 落到「同源非路由路径」⇒ 真违规被当噪音
  assert.equal(normalizeBase("https://ss.fx8.store/"), "https://ss.fx8.store");
  assert.equal(normalizeBase(" https://ss.fx8.store/// "), "https://ss.fx8.store");
  assert.equal(normalizeBase(""), "");
  assert.equal(normalizeBase(undefined), "");
  assert.match("Just a moment...", CHALLENGE_TITLE_RE);
  assert.match("Attention Required! | Cloudflare", CHALLENGE_TITLE_RE);
  assert.match("Checking your browser before accessing", CHALLENGE_TITLE_RE);
  assert.doesNotMatch("信号凯利 · 站点", CHALLENGE_TITLE_RE);
  assert.equal(isCspText(CSP_TEXT), true);
  assert.equal(isCspText("Content Security Policy: report-only"), true);
  assert.equal(isCspText("普通日志"), false);
});

// ── E3: 我们的路由 document + CSP 文本 → FAIL ──────────────────────────────
test("E3 我们的路由 document 的 CSP 违规 → FAIL(带 hash 与不带 hash 都算)", () => {
  for (const url of [`${BASE}/#/overview`, `${BASE}/`, `${BASE}/#/lab?sub=sigkelly`, `${BASE}/index.html`]) {
    // 拿不到我们的策略 ⇒ fail-closed 仍 FAIL(旧版 reason=our-route-document, 现按任务书细化成 unverifiable)
    const r = attribute(url);
    assert.equal(r.verdict, VERDICT_FAIL, url);
    assert.equal(r.reason, "our-policy-unverifiable", url);
    // 我们自己的策略被违反 ⇒ 同一 document 必定 FAIL(真违规不因归因改造而放宽)
    const ours = attributeWithPolicies(url, OK_ROUTE, CSP_TEXT_OURS, OUR_POLICIES);
    assert.equal(ours.verdict, VERDICT_FAIL, url);
    assert.equal(ours.reason, "our-policy-violated", url);
  }
});

// ── E2: 第三方 origin / about:* / data: → INFO ────────────────────────────
test("E2 第三方 origin 的 document → INFO(不阻断)", () => {
  const r = attribute("https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/orchestrate");
  assert.equal(r.verdict, VERDICT_INFO);
  assert.equal(r.reason, "third-party-origin");
});

test("E2 about:srcdoc / about:blank / data: / blob: → INFO(继承父策略, 拿不到父 frame)", () => {
  for (const url of ["about:srcdoc", "about:blank", "data:text/html,<p>x</p>", "blob:https://ss.fx8.store/abc"]) {
    const r = attribute(url);
    assert.equal(r.verdict, VERDICT_INFO, url);
    assert.match(r.reason, /inherited-frame/, url);
  }
});

test("E8 同源非路由 document 路径: 外来策略 → INFO; 拿不到我们的策略 → FAIL(fail-closed)", () => {
  const url = `${BASE}/cdn-cgi/challenge-platform/h/b/scripts/jsd/main.js`;
  // 外来注入策略(值不等于我们的 connect-src 白名单)⇒ INFO, 不阻断
  const foreign = attributeWithPolicies(url, OK_ROUTE, CSP_TEXT, OUR_POLICIES);
  assert.equal(foreign.verdict, VERDICT_INFO);
  assert.equal(foreign.reason, "foreign-policy(注入/挑战侧)");
  // 旧版这里是「同源非根路径 ⇒ 无条件 INFO」= 闸门变瞎(我们自己的 app.min.js 也在这条路径形态里);
  // 现在拿不到我们的策略时 fail-closed(宁可假红不假绿)
  const blind = attribute(url);
  assert.equal(blind.verdict, VERDICT_FAIL);
  assert.equal(blind.reason, "our-policy-unverifiable");
  assert.equal(documentUrlKind(`${BASE}/#/overview`, { baseOrigin: ORIGIN }), "our-document");
});

// ── E4: 挑战页识别 + 挑战侧同源 document 降级 ───────────────────────────────
test("E4 cf-mitigated 响应头 / 挑战标题 → 该路由 UNREACHABLE(challenge)", () => {
  assert.deepEqual(evaluateRoute({ status: 200, cfMitigated: "challenge" }), { state: ROUTE_UNREACHABLE, reason: "challenge" });
  assert.deepEqual(evaluateRoute({ status: 200, title: "Just a moment..." }), { state: ROUTE_UNREACHABLE, reason: "challenge" });
  assert.deepEqual(evaluateRoute({ status: 200, title: "Attention Required! | Cloudflare" }), {
    state: ROUTE_UNREACHABLE,
    reason: "challenge",
  });
  assert.equal(isChallengePage({}), false);
  assert.equal(isChallengePage({ title: "信号凯利", cfMitigated: null }), false);
  // cf-mitigated 头「存在即算」(调用方用 hasOwnProperty 判是否带头, 值一般是 "challenge")
  assert.equal(isChallengePage({ cfMitigated: "" }), true);
  // 正常 200 页面(标题含「检查」但不是挑战文案)不能被误判
  assert.deepEqual(evaluateRoute({ status: 200, title: "信号实验室 · 参数检查" }), { state: ROUTE_OK, reason: null });
});

test("E4 挑战侧同源 document 的 CSP 违规 → INFO(不算我们的 FAIL)", () => {
  // 关键场景: URL 仍是 ss.fx8.store(同源), 但这次导航被判成挑战页
  const r = attribute(`${BASE}/#market/a-stock`, CHALLENGE_ROUTE);
  assert.equal(r.verdict, VERDICT_INFO);
  assert.equal(r.reason, "challenge-document");
});

test("E4/E5 不可达路由(4xx/5xx)的 document 违规 → INFO", () => {
  const r = attribute(`${BASE}/#lab?sub=sigkelly`, HTTP500_ROUTE);
  assert.equal(r.verdict, VERDICT_INFO);
  assert.match(r.reason, /route-unreachable\(http-status\)/);
});

// ── E5: HTTP 状态码 ────────────────────────────────────────────────────────
test("E5 status>=400 → 路由加载失败(UNREACHABLE/http-status)", () => {
  for (const status of [400, 403, 404, 500, 503]) {
    assert.deepEqual(evaluateRoute({ status }), { state: ROUTE_UNREACHABLE, reason: "http-status" }, String(status));
  }
  assert.deepEqual(evaluateRoute({ status: 304 }), { state: ROUTE_OK, reason: null });
  assert.deepEqual(evaluateRoute({ status: 200 }), { state: ROUTE_OK, reason: null });
  assert.deepEqual(evaluateRoute({ gotoError: "net::ERR_NAME_NOT_RESOLVED" }), {
    state: ROUTE_UNREACHABLE,
    reason: "goto-error",
  });
});

test("E5 边界: hash 同文档跳转 status=null 且上一路由不可达 → 承接 UNREACHABLE", () => {
  assert.deepEqual(evaluateRoute({ status: null, prevRouteState: ROUTE_UNREACHABLE }), {
    state: ROUTE_UNREACHABLE,
    reason: "prev-route-unreachable",
  });
  assert.deepEqual(evaluateRoute({ status: null, prevRouteState: ROUTE_OK }), { state: ROUTE_OK, reason: null });
});

// ── E7(2026-10-27 补): 导航落地校验 —— 跨 origin / 同源异路径不能静默放行 ─────
test("E7 导航落地 URL: 我们的 document → OK; 跨 origin → UNREACHABLE(origin-mismatch)", () => {
  // 正常形态: 根 / 显式 index.html / hash 路由(document 仍是 /)都算我们的
  for (const url of [`${BASE}/`, `${BASE}/index.html`, `${BASE}/#overview`, `${BASE}/?tab=lab`]) {
    assert.deepEqual(evaluateNavigationTarget(url, { baseOrigin: ORIGIN }), { state: ROUTE_OK, reason: null }, url);
  }
  // 跨 origin 跳转(门户拦截页 / 登录页 / 别的站点): 根本没校验到目标页 ⇒ 不可达, 不能当 OK
  for (const url of ["https://sss.sugas.site/", "https://challenges.cloudflare.com/x", "http://ss.fx8.store/"]) {
    assert.deepEqual(
      evaluateNavigationTarget(url, { baseOrigin: ORIGIN }),
      { state: ROUTE_UNREACHABLE, reason: "origin-mismatch" },
      url,
    );
  }
});

test("E7 导航落地 URL: 同源但非我们的 document 路径 → UNREACHABLE(path-mismatch); 读不到 URL 不据此判死", () => {
  for (const url of [`${BASE}/cdn-cgi/challenge-platform/h/b`, `${BASE}/some/portal/page`]) {
    assert.deepEqual(
      evaluateNavigationTarget(url, { baseOrigin: ORIGIN }),
      { state: ROUTE_UNREACHABLE, reason: "path-mismatch" },
      url,
    );
  }
  // 空 / 非法 / 没给 baseOrigin: 不据此判不可达(避免把正常情况误判), 交给其它判据
  for (const url of ["", "   ", "::::not-a-url", null, undefined]) {
    assert.deepEqual(evaluateNavigationTarget(url, { baseOrigin: ORIGIN }), { state: ROUTE_OK, reason: null }, String(url));
  }
  assert.deepEqual(evaluateNavigationTarget(`${BASE}/`, { baseOrigin: "" }), { state: ROUTE_OK, reason: null });
});

test("E7 路由判定接线: finalUrl 跨 origin ⇒ 每个路由都 UNREACHABLE; 三例全不可达 ⇒ exit 2(绝非静默 exit 0)", () => {
  // 三种"看起来正常"的响应(200 + 正常标题 + 无挑战头)也不许把异 origin 判成 OK —— 三个路由逐个断言
  for (const tab of DEFAULT_ROUTE_TABS) {
    const verdict = evaluateRoute({ status: 200, title: "某个别家页面", finalUrl: "https://sss.sugas.site/", baseOrigin: ORIGIN });
    assert.deepEqual(verdict, { state: ROUTE_UNREACHABLE, reason: "origin-mismatch" }, tab);
  }
  // 三个路由全跨 origin ⇒ 不可达 3 ⇒ exit 2(旧版这里是 0 = 闸门变瞎)
  assert.equal(decideExitCode({ failCount: 0, unreachableRoutes: 3 }), 2);
  // 违规优先契约不变: 即便同时有不可达, 有真违规仍 exit 1
  assert.equal(decideExitCode({ failCount: 1, unreachableRoutes: 3 }), 1);
  // 老调用(不传 finalUrl)语义不变
  assert.deepEqual(evaluateRoute({ status: 200, title: "信号凯利" }), { state: ROUTE_OK, reason: null });
});

// ── 2026-10-27 第 3 轮: 按「被违反的策略是不是我们的」归因(E7–E10) ─────────────
test("compareDirectiveToOurPolicy: ours / foreign / unknown 三态 + 归一化(空白/顺序/大小写/尾分号)", () => {
  assert.equal(compareDirectiveToOurPolicy(CSP_TEXT_OURS, OUR_POLICIES).relation, "ours");
  // source-list 顺序无语义 ⇒ 排序后比
  assert.equal(
    compareDirectiveToOurPolicy(
      'x violates the following Content Security Policy directive: "connect-src https://web.ifzq.gtimg.cn   \'self\' https://push2.eastmoney.com".',
      OUR_POLICIES,
    ).relation,
    "ours",
  );
  // 大小写 + 结尾分号 + 多余空白: 归一化后仍相同
  assert.equal(
    compareDirectiveToOurPolicy(
      'x violates the following Content Security Policy directive: "CONNECT-SRC  \'self\' https://push2.eastmoney.com   https://web.ifzq.gtimg.cn ;"',
      OUR_POLICIES,
    ).relation,
    "ours",
  );
  // 外来注入策略: 同名 directive 存在但值不同
  assert.equal(compareDirectiveToOurPolicy(CSP_TEXT, OUR_POLICIES).relation, "foreign");
  // 我们策略里根本没有这个 directive ⇒ 不可能是我们的策略原文 ⇒ foreign
  assert.equal(
    compareDirectiveToOurPolicy('violates the following Content Security Policy directive: "frame-ancestors \'none\'"', OUR_POLICIES)
      .relation,
    "foreign",
  );
  // 抽不出 directive / 抽出的是裸 directive 名(没有值)/ 拿不到我们的策略 ⇒ unknown(fail-closed)
  assert.equal(compareDirectiveToOurPolicy("Content Security Policy: 别的东西", OUR_POLICIES).relation, "unknown");
  assert.equal(compareDirectiveToOurPolicy('Content Security Policy directive: "img-src"', OUR_POLICIES).relation, "unknown");
  assert.equal(compareDirectiveToOurPolicy(CSP_TEXT_OURS, []).relation, "unknown");
  assert.equal(compareDirectiveToOurPolicy(CSP_TEXT_OURS, undefined).relation, "unknown");
  // 抽出的 directive 名与值(排障用)
  const parsed = extractViolatedDirective(CSP_TEXT);
  assert.equal(parsed.directive, "connect-src");
  assert.equal(parsed.value, "'none'");
  // 我们的策略解析: 同名 directive 在多条 header(enforce + report-only)里都收
  const dirs = parsePolicyDirectives([OUR_POLICY, "connect-src 'none'"]);
  assert.equal(dirs.get("connect-src").size, 2);
  assert.equal(dirs.has("default-src"), true);
});

test("compareDirectiveToOurPolicy: 「Note that ... fallback」兜底句式 —— 引号里是实际生效的 fallback directive", () => {
  const fb =
    "Refused to connect to 'https://x/api' because it violates the following Content Security Policy directive: " +
    '"default-src \'self\'". Note that \'connect-src\' was not explicitly set, so \'default-src\' is used as a fallback.';
  const r = compareDirectiveToOurPolicy(fb, OUR_POLICIES);
  assert.equal(r.relation, "ours"); // 我们的 default-src 就是 'self'
  assert.equal(r.directive, "default-src");
  // 同一句式但值不同(注入策略的 default-src)⇒ foreign
  assert.equal(
    compareDirectiveToOurPolicy(fb.replace('"default-src \'self\'"', '"default-src \'none\'"'), OUR_POLICIES).relation,
    "foreign",
  );
});

// ── E2/E3(2026-10-27 #319): Chrome 141 的「内联脚本 / eval」两种真实报文方言 ──────
// 原文逐字取自 /tmp/probe-csp2/out.log(Chromium 141 实测记录), 不许自己编。
// 注意: 探针在 eval 报文前打了 "EVALERR " 标签, Chrome 原文从 "Evaluating" 起; 两种都测,
// 顺带证明前缀不影响抽取。
const INLINE_CSP_TEXT =
  "Executing inline script violates the following Content Security Policy directive 'script-src 'self''. " +
  "Either the 'unsafe-inline' keyword, a hash ('sha256-3ILSSvr4jUs5/OxJwOKm6BRvFZpGvkV4VBm6c61ib7k='), " +
  "or a nonce ('nonce-...') is required to enable inline execution. The action has been blocked.";
const INLINE_CSP_TEXT_REPORT_ONLY =
  INLINE_CSP_TEXT +
  " The policy is report-only, so the violation has been logged but no further action has been taken.";
const EVAL_CSP_TEXT =
  "EVALERR Evaluating a string as JavaScript violates the following Content Security Policy directive because " +
  "'unsafe-eval' is not an allowed source of script: script-src 'self'\".";
const EVAL_CSP_TEXT_REPORT_ONLY =
  "Evaluating a string as JavaScript violates the following Content Security Policy directive because " +
  "'unsafe-eval' is not an allowed source of script: \"script-src 'self'\".\n" +
  " The policy is report-only, so the violation has been logged but no further action has been taken.";

// 探针 /b 路由真实响应头(script-src 'self'), 与报文里引用的 directive 逐字一致 ⇒ 应判 ours。
const DIALECT_OUR_POLICY = "default-src 'self'; script-src 'self'; connect-src 'self'; img-src 'self'";
// 注入侧策略: 同名 directive 但值不同 ⇒ 应判 foreign(不阻断)。
const DIALECT_FOREIGN_POLICY = "default-src 'self'; script-src 'none'; connect-src 'none'; img-src 'self'";

test("E2 内联脚本方言(单引号 + 无冒号)⇒ 抽得出 script-src 'self', 不再落 unknown", () => {
  for (const text of [INLINE_CSP_TEXT, INLINE_CSP_TEXT_REPORT_ONLY]) {
    assert.deepEqual(extractViolatedDirective(text), { directive: "script-src", value: "'self'" }, text.slice(0, 40));
    // 配我们真实策略 ⇒ ours(FAIL 真违规), 不再是 unknown
    assert.equal(compareDirectiveToOurPolicy(text, [DIALECT_OUR_POLICY]).relation, "ours");
    const ours = attributeWithPolicies(`${BASE}/`, OK_ROUTE, text, [DIALECT_OUR_POLICY]);
    assert.equal(ours.verdict, VERDICT_FAIL);
    assert.equal(ours.reason, "our-policy-violated");
    // 配注入策略 ⇒ foreign(INFO 噪音), 不再假红
    assert.equal(compareDirectiveToOurPolicy(text, [DIALECT_FOREIGN_POLICY]).relation, "foreign");
    const foreign = attributeWithPolicies(`${BASE}/`, OK_ROUTE, text, [DIALECT_FOREIGN_POLICY]);
    assert.equal(foreign.verdict, VERDICT_INFO);
    assert.equal(foreign.reason, "foreign-policy(注入/挑战侧)");
    // 拿不到我们的策略 ⇒ 仍 fail-closed(不是 unknown 放行)
    assert.equal(attributeWithPolicies(`${BASE}/`, OK_ROUTE, text, []).reason, "our-policy-unverifiable");
  }
});

test("E3 eval 方言(冒号后名字 + 末尾值)⇒ 抽得出 script-src 'self', 不再落 unknown", () => {
  for (const text of [EVAL_CSP_TEXT, EVAL_CSP_TEXT_REPORT_ONLY]) {
    assert.deepEqual(extractViolatedDirective(text), { directive: "script-src", value: "'self'" }, text.slice(0, 40));
    assert.equal(compareDirectiveToOurPolicy(text, [DIALECT_OUR_POLICY]).relation, "ours");
    const ours = attributeWithPolicies(`${BASE}/`, OK_ROUTE, text, [DIALECT_OUR_POLICY]);
    assert.equal(ours.verdict, VERDICT_FAIL);
    assert.equal(ours.reason, "our-policy-violated");
    assert.equal(compareDirectiveToOurPolicy(text, [DIALECT_FOREIGN_POLICY]).relation, "foreign");
    const foreign = attributeWithPolicies(`${BASE}/`, OK_ROUTE, text, [DIALECT_FOREIGN_POLICY]);
    assert.equal(foreign.verdict, VERDICT_INFO);
    assert.equal(foreign.reason, "foreign-policy(注入/挑战侧)");
    assert.equal(attributeWithPolicies(`${BASE}/`, OK_ROUTE, text, []).reason, "our-policy-unverifiable");
  }
});

test("E7 我们自己的策略被违反 ⇒ FAIL —— 不论 location 是 document 还是我们自己的脚本(app.min.js)", () => {
  // 实测事实: 外部脚本发起的违规, location 报的是脚本 URL; 旧版按 location 归因会把它们当噪音
  for (const url of [
    `${BASE}/`,
    `${BASE}/index.html`,
    `${BASE}/#/overview`,
    `${BASE}/app.min.js`,
    `${BASE}/app.min.js?v=20261027-a1`,
    `${BASE}/common.js`, // 同源静态资源(不是 document 路径)
  ]) {
    const r = attributeWithPolicies(url, OK_ROUTE, CSP_TEXT_OURS, OUR_POLICIES);
    assert.equal(r.verdict, VERDICT_FAIL, url);
    assert.equal(r.reason, "our-policy-violated", url);
  }
});

test("E8 外来注入策略(CF jsd connect-src 'none')⇒ INFO 不阻断, 退出码仍 0", () => {
  for (const url of [`${BASE}/`, `${BASE}/app.min.js?v=20261027-a1`, `${BASE}/cdn-cgi/challenge-platform/h/b/scripts/jsd/main.js`]) {
    const r = attributeWithPolicies(url, OK_ROUTE, CSP_TEXT, OUR_POLICIES);
    assert.equal(r.verdict, VERDICT_INFO, url);
    assert.equal(r.reason, "foreign-policy(注入/挑战侧)", url);
  }
  // 全 INFO ⇒ 两个计数都不涨 ⇒ exit 0
  assert.equal(decideExitCode({ failCount: 0, unreachableRoutes: 0 }), 0);
});

test("E9 拿不到我们文档的策略 ⇒ 同源情形 fail-closed 判 FAIL; 第三方/继承 frame 仍 INFO", () => {
  const variants = [[], undefined, ["", "   "], null];
  for (const policies of variants) {
    for (const url of [
      `${BASE}/`,
      `${BASE}/app.min.js`,
      `${BASE}/cdn-cgi/challenge-platform/h/b/scripts/jsd/main.js`,
    ]) {
      const r = attributeWithPolicies(url, OK_ROUTE, CSP_TEXT_OURS, policies);
      assert.equal(r.verdict, VERDICT_FAIL, `${url} policies=${JSON.stringify(policies)}`);
      assert.equal(r.reason, "our-policy-unverifiable", `${url} policies=${JSON.stringify(policies)}`);
    }
    // 第三方 origin 与继承父策略的 frame 不受「拿不到策略」影响, 仍 INFO
    assert.equal(attributeWithPolicies("https://challenges.cloudflare.com/x", OK_ROUTE, CSP_TEXT_OURS, policies).verdict, VERDICT_INFO);
    assert.equal(attributeWithPolicies("about:srcdoc", OK_ROUTE, CSP_TEXT_OURS, policies).verdict, VERDICT_INFO);
  }
});

test("E10 第三方 origin + 与我们策略完全相同的 directive 文本 ⇒ 仍 INFO(不误判成我们的 FAIL)", () => {
  const r = attributeWithPolicies(
    "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/b/orchestrate",
    OK_ROUTE,
    CSP_TEXT_OURS,
    OUR_POLICIES,
  );
  assert.equal(r.verdict, VERDICT_INFO);
  assert.equal(r.reason, "third-party-origin");
});

test("优先级: 本次路由不可达(挑战/4xx) 优先于策略比对 —— 挑战侧同源 document 的违规一律 INFO", () => {
  // 即便引用的是我们自己的策略文本, 只要这次导航是挑战页/4xx, 也不算我们的(旧行为保持)
  for (const route of [CHALLENGE_ROUTE, HTTP500_ROUTE]) {
    const r = attributeWithPolicies(`${BASE}/`, route, CSP_TEXT_OURS, OUR_POLICIES);
    assert.equal(r.verdict, VERDICT_INFO, route.reason);
    assert.match(r.reason, route.reason === "challenge" ? /challenge-document/ : /route-unreachable\(http-status\)/);
  }
});

// ── E6: 退出码契约不变 + 违规优先于不可达 ──────────────────────────────────
test("E6 退出码: 0 洁净 / 1 真违规优先 / 2 不可达 / INFO 噪音不计", () => {
  assert.equal(decideExitCode({ failCount: 0, unreachableRoutes: 0 }), 0);
  assert.equal(decideExitCode({ failCount: 0, unreachableRoutes: 1 }), 2);
  assert.equal(decideExitCode({ failCount: 3, unreachableRoutes: 3 }), 1);
  // 部分路由被挑战、其余 0 违规 ⇒ 不可达(放行+提示)
  assert.equal(decideExitCode({ failCount: 0, unreachableRoutes: 2 }), 2);
});

// ── 分组计数口径 ──────────────────────────────────────────────────────────
test("分组计数: 累计条数 + 唯一文本去重 + 按条数倒序 + FAIL/INFO 分开", () => {
  const recs = [
    { ...attribute(`${BASE}/#/overview`), text: CSP_TEXT },
    { ...attribute(`${BASE}/#/overview`), text: CSP_TEXT }, // 同一文本重复上报
    { ...attribute(`${BASE}/#/overview`), text: "另一类违规文本 violates the following Content Security Policy directive: \"img-src\"" },
    { ...attribute("about:srcdoc"), text: "srcdoc 噪音" },
  ];
  const groups = groupByDocument(recs);
  assert.equal(groups.length, 2);
  assert.equal(groups[0].verdict, VERDICT_FAIL);
  assert.equal(groups[0].docUrl, `${BASE}/#/overview`);
  assert.equal(groups[0].count, 3);
  assert.equal(groups[0].uniqueCount, 2);
  assert.equal(groups[1].verdict, VERDICT_INFO);
  assert.equal(groups[1].docUrl, "about:srcdoc");
  assert.equal(groups[1].count, 1);
  assert.equal(groups[0].samples.length <= 3, true);
});

// ── pageerror 归因(同一降噪原则) ──────────────────────────────────────────
test("pageerror: 我们的路由 → FAIL; 挑战/不可达路由 → INFO", () => {
  assert.equal(attributePageError("TypeError: x is undefined", { route: OK_ROUTE }).verdict, VERDICT_FAIL);
  assert.equal(attributePageError("TypeError: x is undefined", { route: CHALLENGE_ROUTE }).verdict, VERDICT_INFO);
  assert.equal(attributePageError("TypeError: x is undefined", { route: HTTP500_ROUTE }).verdict, VERDICT_INFO);
});

// ── 兜底: 空/无法解析 location ─────────────────────────────────────────────
test("空 location: 我们路由正常加载 ⇒ 仍算 FAIL(不把真违规弄瞎); 挑战/未知窗口 ⇒ INFO", () => {
  for (const url of ["", "   ", "::::not-a-url"]) {
    const ours = attribute(url, OK_ROUTE);
    assert.equal(ours.verdict, VERDICT_FAIL, `url=${url}`);
    assert.equal(ours.reason, "unlocated-message-on-our-route", `url=${url}`);
    assert.equal(attribute(url, CHALLENGE_ROUTE).verdict, VERDICT_INFO, `url=${url}`);
  }
});

// ── 非 CSP 文本不进违规通道 ────────────────────────────────────────────────
test("非 CSP 文本 → INFO(不因归因改动把普通日志算成违规)", () => {
  assert.equal(attribute(`${BASE}/#/overview`, OK_ROUTE, "普通 console 日志").verdict, VERDICT_INFO);
});