"use strict";

// 执行生产函数；网络完全隔离，原生 AbortController/Response + 手动时钟。
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");
const { getEventListeners } = require("node:events");
const ROOT = path.resolve(__dirname, "../..");
const app = fs.readFileSync(path.join(ROOT, "static-site/app.js"), "utf8");
const lab = fs.readFileSync(path.join(ROOT, "static-site/lab.js"), "utf8");

function declaration(source, name) {
  const matches = [...source.matchAll(new RegExp("\\b(?:async\\s+)?function\\s+" + name + "\\s*\\(", "g"))];
  assert.equal(matches.length, 1, "唯一函数锚点: " + name);
  const start = matches[0].index;
  // 用 JS parser 确认完整声明，避免字符串/注释里的大括号截断函数。
  for (let end = source.indexOf("}", start); end >= 0; end = source.indexOf("}", end + 1)) {
    const code = source.slice(start, end + 1);
    try { new vm.Script(code); return code; } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
  }
  throw new Error("无法提取生产函数: " + name);
}
const sources = [
  ...["_labKellyFetchTrades", "_labKellyFetchTradesRetry", "_labKellyTradesUrl", "_labKellyTradesUrlCf", "fetchJSONProgress"]
    .map(name => declaration(lab, name)),
  ...["_fundScoreApiFetch", "_fundScreenerApiFetch", "_guardFxPayload", "fetchJSON"].map(name => declaration(app, name)),
].join("\n");

function clock() {
  let now = 1800000000000, next = 0;
  const timers = new Map(), created = [], cleared = [];
  return {
    timers, created, cleared, now: () => now,
    setTimeout(fn, ms) {
      const id = ++next;
      timers.set(id, { fn, ms, due: now + ms }); created.push({ id, ms }); return id;
    },
    clearTimeout(id) { cleared.push(id); timers.delete(id); },
    advance(ms) {
      now += ms;
      for (const [id, timer] of [...timers]) {
        if (timer.due <= now) { timers.delete(id); timer.fn(); }
      }
    },
  };
}
const turn = () => new Promise(resolve => setImmediate(resolve));
function observe(promise) {
  const state = { status: "pending" };
  promise.then(value => Object.assign(state, { status: "fulfilled", value }),
    error => Object.assign(state, { status: "rejected", error }));
  return state;
}
function abortError() { return new DOMException("Aborted", "AbortError"); }
function untilAbort(signal) {
  return new Promise((_, reject) => {
    if (signal.aborted) reject(abortError());
    else signal.addEventListener("abort", () => reject(abortError()), { once: true });
  });
}
function stalledBody(signal) {
  return new Response(new ReadableStream({ start(controller) {
    // 已收到部分正文，且没有 Content-Length；原生 json() 等剩余字节。
    controller.enqueue(new TextEncoder().encode('{"rows":['));
    if (signal.aborted) controller.error(abortError());
    else signal.addEventListener("abort", () => controller.error(abortError()), { once: true });
  } }));
}
const payload = { fields: ["code"], quadrants: { A: [["000001"]] }, data: [{ code: "000001" }], total: 1 };
const ok = () => new Response(JSON.stringify(payload));

function harness(plans, options = {}) {
  const timer = clock(), calls = [], cache = new Map(), inflight = new Map();
  const context = vm.createContext({
    AbortController, Blob, console: { error() {}, warn() {} },
    Date: class extends Date { static now() { return timer.now(); } },
    location: { hostname: "ss.fx8.store" },
    _isMainSite: () => options.main !== false,
    _authApiBase: () => options.main === false ? "https://ss.fx8.store" : "",
    _getAuthToken: () => options.token || null,
    _labCustomCacheBust: () => "test-version",
    _NO_CACHE_URLS: /^$/, _NO_R2_CACHE_URLS: /^$/, _CACHE_TTL: 300000,
    _resultCache: cache, _inflightFetch: inflight,
    _R2_FALLBACK_BASE: "https://ss.fx8.store/data/", _R2_ROOT_BASE: "https://ss.fx8.store/r2/",
    renderFailCard() {},
    window: { _tdsSsdUrlFor: () => options.ssd === false ? null : "https://ssd.fx8.store/data/sample.json",
      _tdsSsdPreferredUntil: options.preferred ? timer.now() + 90000 : 0 },
    setTimeout: timer.setTimeout, clearTimeout: timer.clearTimeout,
    async fetch(url, init = {}) {
      const index = calls.length, call = { url, ...init, bodyReads: 0, at: timer.now() };
      calls.push(call);
      assert.ok(init.signal instanceof AbortSignal, "生产请求必须使用原生 signal");
      if (init.signal.aborted) throw abortError();
      const plan = plans[index];
      assert.ok(plan, "意外的请求/重试: " + url);
      let response;
      if (plan === "headers") return untilAbort(init.signal);
      if (plan === "body") response = stalledBody(init.signal);
      else if (plan === "http") response = new Response("unread", { status: 503 });
      else if (plan === "json") response = new Response("{broken");
      else if (plan === "network") throw new TypeError("network unavailable");
      else response = ok();
      const json = response.json.bind(response);
      response.json = () => { call.bodyReads++; return json(); };
      return response;
    },
  });
  vm.runInContext(sources, context);
  return { context, timer, calls, cache, inflight };
}
function clean(h) {
  assert.equal(h.timer.timers.size, 0, "所有路径清理定时器");
  for (const timer of h.timer.created) assert.ok(h.timer.cleared.includes(timer.id), "finally 清理每个 timer");
  assert.equal(h.inflight.size, 0, "清理在途缓存");
}
function fulfilled(state) {
  assert.equal(state.status, "fulfilled"); assert.deepEqual(state.value, payload);
}
const kellyUrls = ["https://ss.fx8.store/data/sample.json?v=test-version", "./data/sample.json?v=test-version", "https://ssd.fx8.store/data/sample.json"];
function kellyOrder(h, count) {
  assert.deepEqual(h.calls.map(call => call.url), kellyUrls.slice(0, count));
  assert.ok(h.timer.created.every(timer => timer.ms === 60000), "各腿仍是 60 秒");
  assert.equal(new Set(h.calls.map(call => call.signal)).size, count, "各腿独立 controller");
}

for (let leg = 0; leg < 3; leg++) {
  const label = ["R2", "CF", "SSD"][leg];
  for (const kind of ["body", "headers"]) {
    test("Kelly " + label + ": " + kind + " 停滞在原 60000ms 预算内终止", async () => {
      const h = harness([...Array(leg).fill("http"), kind, "ok"]);
      const state = observe(h.context._labKellyFetchTrades("sample.json"));
      await turn();
      assert.equal(h.calls.length, leg + 1);
      assert.equal(state.status, "pending");
      h.timer.advance(59999); await turn();
      assert.equal(h.calls[leg].signal.aborted, false);
      h.timer.advance(1); await turn();
      assert.equal(h.calls[leg].signal.aborted, true, "正文/headers 停滞必须触发 abort");
      if (leg < 2) fulfilled(state);
      else { assert.equal(state.status, "rejected"); assert.equal(state.error.name, "AbortError"); }
      kellyOrder(h, leg < 2 ? leg + 2 : 3); clean(h);
    });
  }
  for (const kind of ["ok", "http", "json", "network"]) {
    test("Kelly " + label + ": " + kind + " 维持 payload/错误/回退顺序并清理", async () => {
      const h = harness([...Array(leg).fill("http"), kind, "ok"]);
      const state = observe(h.context._labKellyFetchTrades("sample.json")); await turn();
      if (kind === "ok" || leg < 2) fulfilled(state);
      else {
        assert.equal(state.status, "rejected");
        if (kind === "http") assert.equal(state.error.message, "SSD 503");
        if (kind === "json") assert.equal(state.error.name, "SyntaxError");
        if (kind === "network") assert.equal(state.error.message, "network unavailable");
      }
      kellyOrder(h, kind === "ok" || leg === 2 ? leg + 1 : leg + 2);
      h.calls.forEach((call, index) => {
        const outcome = index < leg ? "http" : index === leg ? kind : "ok";
        assert.equal(call.bodyReads, outcome === "ok" || outcome === "json" ? 1 : 0,
          "HTTP/传输失败不读正文，正常/坏 JSON 只读一次");
      });
      assert.ok(h.calls.every(call => !call.signal.aborted)); clean(h);
    });
  }
}
test("Kelly: 三腿正文依次停滞，总计 180000ms 后失败，无悬挂 timer", async () => {
  const h = harness(["body", "body", "body"]);
  const state = observe(h.context._labKellyFetchTrades("sample.json")); await turn();
  for (let leg = 0; leg < 3; leg++) {
    assert.equal(h.calls.length, leg + 1);
    assert.equal(h.timer.timers.size, 1);
    h.timer.advance(60000); await turn();
    assert.equal(h.calls[leg].signal.aborted, true);
  }
  assert.equal(state.status, "rejected"); assert.equal(state.error.name, "AbortError");
  assert.deepEqual(h.calls.map(call => call.at - h.calls[0].at), [0, 60000, 120000]);
  kellyOrder(h, 3); clean(h);
});
for (const kind of ["http", "json", "network", "body"]) {
  test("Kelly: 无 SSD 映射时保留 CF " + kind + " 错误", async () => {
    const h = harness(["http", kind], { ssd: false });
    const state = observe(h.context._labKellyFetchTrades("sample.json")); await turn();
    if (kind === "body") { h.timer.advance(60000); await turn(); }
    assert.equal(state.status, "rejected");
    if (kind === "http") assert.equal(state.error.message, "CF 503");
    if (kind === "json") assert.equal(state.error.name, "SyntaxError");
    if (kind === "body") assert.equal(state.error.name, "AbortError");
    kellyOrder(h, 2); clean(h);
  });
}
test("Kelly: 真实 Retry caller 在整链失败后保留原退避再重试", async () => {
  const h = harness(["http", "http", "body", "ok"]);
  const state = observe(h.context._labKellyFetchTradesRetry("sample.json", 2, [1000])); await turn();
  h.timer.advance(60000); await turn();
  assert.equal(state.status, "pending"); assert.equal(h.calls.length, 3);
  h.timer.advance(999); await turn(); assert.equal(h.calls.length, 3);
  h.timer.advance(1); await turn(); fulfilled(state);
  // 退避 timer 是 caller 自然执行完的，不是请求 timer。
  assert.equal(h.timer.timers.size, 0);
  assert.equal(h.calls[3].url, kellyUrls[0]);
});

for (const name of ["_fundScoreApiFetch", "_fundScreenerApiFetch"]) {
  for (const main of [true, false]) {
    test(name + ": 正常 payload、认证、cache 参数不变，main=" + main, async () => {
      const h = harness(["ok"], { main, token: main ? null : "fake-token" });
      const state = observe(h.context[name]("page=2&size=20")); await turn(); fulfilled(state);
      const call = h.calls[0];
      assert.equal(call.url, (main ? "" : "https://ss.fx8.store") + "/api/" + (name === "_fundScoreApiFetch" ? "fund_score" : "fund_screener") + "?page=2&size=20");
      assert.equal(call.credentials, main ? "include" : "omit"); assert.equal(call.cache, "no-cache");
      assert.equal(call.headers.Authorization, main ? undefined : "Bearer fake-token");
      assert.equal(call.bodyReads, 1); assert.equal(h.timer.created[0].ms, 15000); clean(h);
    });
  }
  for (const kind of ["body", "headers"]) {
    test(name + ": " + kind + " 停滞在原 15000ms 预算内终止且不重试", async () => {
      const h = harness([kind]);
      const state = observe(h.context[name]("page=1")); await turn();
      assert.equal(state.status, "pending"); h.timer.advance(14999); await turn();
      assert.equal(h.calls[0].signal.aborted, false);
      h.timer.advance(1); await turn();
      assert.equal(h.calls[0].signal.aborted, true); assert.equal(state.status, "rejected");
      assert.equal(state.error.name, "AbortError"); assert.equal(h.calls.length, 1); clean(h);
    });
  }
  for (const kind of ["http", "json", "network"]) {
    test(name + ": " + kind + " 原错误向上传递，不重试，清理 timer", async () => {
      const h = harness([kind]); const state = observe(h.context[name]("page=1")); await turn();
      assert.equal(state.status, "rejected");
      if (kind === "http") { assert.equal(state.error.message, "HTTP 503"); assert.equal(h.calls[0].bodyReads, 0); }
      if (kind === "json") assert.equal(state.error.name, "SyntaxError");
      if (kind === "network") assert.equal(state.error.message, "network unavailable");
      assert.equal(h.calls.length, 1); clean(h);
    });
  }
}

// 这三个辅助加载器没有外部 signal 入口；取消测试走真实可达的
// fetchJSONProgress -> fetchJSON（禁止用 stub 替换 callee 掩盖取消链缺陷）。
const fullUrl = "https://ss.fx8.store/r2/lab/full.json";
function trackedOuter() {
  const controller = new AbortController(), signal = controller.signal;
  return { controller, signal, get listeners() { return new Set(getEventListeners(signal, "abort")); } };
}
function cancelled(h, state, outer, count) {
  assert.equal(state.status, "rejected"); assert.equal(state.error.name, "AbortError");
  assert.equal(h.calls.length, count, "用户取消后不打后续腿/不重试");
  assert.equal(h.calls.at(-1).signal.aborted, true);
  assert.equal(outer.listeners.size, 0, "移除外部 abort 监听"); clean(h);
}
for (const timeout of [60000, undefined]) {
  test("可达取消: progress 正文中用户取消，不回退，timeout=" + timeout, async () => {
    const h = harness(["body"]), outer = trackedOuter();
    const state = observe(h.context.fetchJSONProgress(fullUrl, null, outer.signal, timeout)); await turn();
    outer.controller.abort(); await turn(); cancelled(h, state, outer, 1);
  });
}
for (const kind of ["http", "json", "body"]) {
  for (const ssd of [false, true]) {
    test("可达取消: progress " + kind + " 后真实 callee 的 " + (ssd ? "SSD" : "CF") + " 正文可取消", async () => {
      const h = harness(ssd ? [kind, "http", "body"] : [kind, "body"]), outer = trackedOuter();
      const state = observe(h.context.fetchJSONProgress(fullUrl, null, outer.signal, 60000)); await turn();
      if (kind === "body") { h.timer.advance(60000); await turn(); }
      assert.equal(h.calls.length, ssd ? 3 : 2);
      if (ssd) assert.match(h.calls.at(-1).url, /ssd\.fx8\.store/);
      outer.controller.abort(); await turn(); cancelled(h, state, outer, ssd ? 3 : 2);
    });
  }
}
test("可达取消: 已取消的 progress 不消费正文且不发起回退", async () => {
  const h = harness([]), outer = trackedOuter(); outer.controller.abort();
  const state = observe(h.context.fetchJSONProgress(fullUrl, null, outer.signal, 60000)); await turn();
  assert.equal(state.status, "rejected"); assert.equal(state.error.name, "AbortError");
  assert.equal(h.calls.length, 1); assert.equal(h.calls[0].bodyReads, 0); clean(h);
});
test("可达取消: 真实 fetchJSON 竞速两条正文均取消，不再串行重试", async () => {
  const h = harness(["body", "body"], { preferred: true }), outer = trackedOuter();
  const state = observe(h.context.fetchJSON(fullUrl, 60000, outer.signal)); await turn();
  outer.controller.abort(); await turn(); cancelled(h, state, outer, 2);
  assert.ok(h.calls.every(call => call.signal.aborted));
});
test("真实 callee: 正常 payload 仍缓存且在途去重，清理 timer/监听", async () => {
  const h = harness(["ok"]), outer = trackedOuter();
  const first = observe(h.context.fetchJSON(fullUrl, 60000, outer.signal));
  const second = observe(h.context.fetchJSON(fullUrl, 60000, outer.signal)); await turn();
  fulfilled(first); fulfilled(second); assert.equal(h.calls.length, 1);
  assert.equal(await h.context.fetchJSON(fullUrl, 60000, outer.signal), first.value);
  assert.equal(h.calls.length, 1); assert.equal(h.cache.size, 1); assert.equal(outer.listeners.size, 0); clean(h);
});
