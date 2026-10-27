// 归因规则自动化测试(node 内置 test runner, 零依赖):
//   node --test scripts/playwright-accept/console_attribution.test.mjs
// 覆盖任务书 E2/E3/E4/E5/E6 五类判定 + 分组计数口径 + 变异判别力(改坏归因规则必须变红)。
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
  attributeCspMessage,
  attributePageError,
  groupByDocument,
  decideExitCode,
} from "./console_attribution.mjs";

const BASE = "https://ss.fx8.store";
const ORIGIN = baseOriginOf(BASE);

// 真实形态的 CSP 违规文本(含 directive 值 + blocked URL)。
const CSP_TEXT =
  "Refused to connect to 'https://push2.eastmoney.com/api/x' because it violates the following " +
  'Content Security Policy directive: "connect-src \'none\'".';

const OK_ROUTE = { tab: "#overview", url: `${BASE}/#overview`, state: ROUTE_OK, reason: null };
const CHALLENGE_ROUTE = { tab: "#market/a-stock", url: `${BASE}/#market/a-stock`, state: ROUTE_UNREACHABLE, reason: "challenge" };
const HTTP500_ROUTE = { tab: "#lab?sub=sigkelly", url: `${BASE}/#lab?sub=sigkelly`, state: ROUTE_UNREACHABLE, reason: "http-status" };

const attribute = (locationUrl, route = OK_ROUTE, text = CSP_TEXT) =>
  attributeCspMessage({ text, locationUrl }, { baseOrigin: ORIGIN, route });

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
    const r = attribute(url);
    assert.equal(r.verdict, VERDICT_FAIL, url);
    assert.equal(r.reason, "our-route-document", url);
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

test("E2 同源但不是我们路由 document 的路径 → INFO", () => {
  const r = attribute(`${BASE}/cdn-cgi/challenge-platform/h/b/scripts/jsd/main.js`);
  assert.equal(r.verdict, VERDICT_INFO);
  assert.equal(r.reason, "same-origin-non-route-document");
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

test("E7 路由判定接线: finalUrl 跨 origin ⇒ 该路由 UNREACHABLE, 三路由都如此 ⇒ exit 2(绝不静默 exit 0)", () => {
  // 三种"看起来正常"的响应(200 + 正常标题 + 无挑战头)也不许把异 origin 判成 OK
  const verdict = evaluateRoute({ status: 200, title: "某个别家页面", finalUrl: "https://sss.sugas.site/", baseOrigin: ORIGIN });
  assert.deepEqual(verdict, { state: ROUTE_UNREACHABLE, reason: "origin-mismatch" });
  // 三个路由全跨 origin ⇒ 不可达 3 ⇒ exit 2(旧版这里是 0 = 闸门变瞎)
  assert.equal(decideExitCode({ failCount: 0, unreachableRoutes: 3 }), 2);
  // 违规优先契约不变: 即便同时有不可达, 有真违规仍 exit 1
  assert.equal(decideExitCode({ failCount: 1, unreachableRoutes: 3 }), 1);
  // 老调用(不传 finalUrl)语义不变
  assert.deepEqual(evaluateRoute({ status: 200, title: "信号凯利" }), { state: ROUTE_OK, reason: null });
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