"use strict";

// Execute the real loaders with native AbortController and a manual timer clock.
// Fetch is isolated: no real requests, production data, or wall-clock deadlines.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

const ROOT = path.resolve(__dirname, "../..");
const lab = fs.readFileSync(path.join(ROOT, "static-site/lab.js"), "utf8");
const app = fs.readFileSync(path.join(ROOT, "static-site/app.js"), "utf8");
const html = fs.readFileSync(path.join(ROOT, "static-site/index.html"), "utf8");

function declaration(source, name) {
  const matches = [...source.matchAll(new RegExp("\\b(?:async\\s+)?function\\s+" + name + "\\s*\\(", "g"))];
  assert.equal(matches.length, 1, "unique function anchor: " + name);
  const start = matches[0].index;
  // Let the JavaScript parser find the complete declaration; braces in strings
  // or comments must not truncate the extracted production function.
  for (let end = source.indexOf("}", start); end >= 0 && end - start < 16384; end = source.indexOf("}", end + 1)) {
    const code = source.slice(start, end + 1);
    try { new vm.Script(code); return code; } catch (error) {
      if (!(error instanceof SyntaxError)) throw error;
    }
  }
  throw new Error("cannot extract function: " + name);
}

const progressSource = declaration(lab, "fetchJSONProgress");
const guardSource = declaration(app, "_guardFxPayload");
const fetchSource = guardSource + "\n" + declaration(app, "fetchJSON");
const bootConsumer = declaration(app, "_bootJSON");
const bootScripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)]
  .map(match => match[1]).filter(source => source.includes("__bootPrefetch") && source.includes("firstMs"));
assert.equal(bootScripts.length, 1, "unique boot prefetch script, independent of script order");

function clock() {
  let next = 0;
  const timers = new Map();
  return {
    timers,
    setTimeout(fn, ms) { const id = ++next; timers.set(id, { fn, ms }); return id; },
    clearTimeout(id) { timers.delete(id); },
    fire() {
      assert.ok(timers.size, "request must still have an active deadline");
      const [id, timer] = timers.entries().next().value;
      timers.delete(id);
      timer.fn();
      return timer.ms;
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
function untilAbort(signal) {
  return new Promise((_, reject) => {
    const abort = () => { const error = new Error("aborted"); error.name = "AbortError"; reject(error); };
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });
  });
}
const quiet = { error() {}, warn() {} };

function progressHarness(makeResponse) {
  const timer = clock(), calls = [], fallback = [];
  const context = vm.createContext({
    AbortController, Blob, console: quiet,
    setTimeout: timer.setTimeout, clearTimeout: timer.clearTimeout,
    async fetch(url, options = {}) {
      calls.push({ url, signal: options.signal });
      if (options.signal?.aborted) return untilAbort(options.signal);
      return makeResponse(options.signal);
    },
    async fetchJSON(...args) { fallback.push(args); return { fallback: true }; },
  });
  vm.runInContext(progressSource, context);
  return { context, timer, calls, fallback };
}
function jsonResponse(json) { return { ok: true, headers: { get: () => null }, json }; }

test("F05: no-length body remains timed until timeout hands off to fallback", async () => {
  const h = progressHarness(signal => jsonResponse(() => untilAbort(signal)));
  const outer = new AbortController();
  const state = observe(h.context.fetchJSONProgress("/full.json", null, outer.signal, 60000));
  await turn();
  assert.equal(h.timer.fire(), 60000);
  await turn();
  assert.equal(state.status, "fulfilled");
  assert.equal(state.value.fallback, true);
  assert.equal(h.calls[0].signal.aborted, true);
  assert.deepEqual(h.fallback[0], ["/full.json", 60000, outer.signal]);
  assert.equal(h.fallback.length, 1);
  assert.equal(h.timer.timers.size, 0);
});

for (const timeout of [60000, undefined]) {
  test("F05: user cancellation aborts body without retry, timeout=" + timeout, async () => {
    const h = progressHarness(signal => jsonResponse(() => untilAbort(signal)));
    const outer = new AbortController();
    const state = observe(h.context.fetchJSONProgress("/full.json", null, outer.signal, timeout));
    await turn(); outer.abort(); await turn();
    assert.equal(state.status, "rejected");
    assert.equal(state.error.name, "AbortError");
    assert.equal(h.calls[0].signal.aborted, true);
    assert.equal(h.fallback.length, 0);
    assert.equal(h.timer.timers.size, 0);
  });
}

test("F05: already cancelled request rejects without fallback", async () => {
  const h = progressHarness(() => { throw new Error("body must not be read"); });
  const outer = new AbortController(); outer.abort();
  const state = observe(h.context.fetchJSONProgress("/full.json", null, outer.signal, 60000));
  await turn();
  assert.equal(state.status, "rejected");
  assert.equal(state.error.name, "AbortError");
  assert.equal(h.fallback.length, 0);
  assert.equal(h.timer.timers.size, 0);
});

test("F05: normal no-length JSON finishes and clears its deadline", async () => {
  const payload = { rows: [1, 2] };
  const h = progressHarness(() => jsonResponse(async () => payload));
  assert.equal(await h.context.fetchJSONProgress("/full.json", null, null, 60000), payload);
  assert.equal(h.calls.length, 1);
  assert.equal(h.fallback.length, 0);
  assert.equal(h.timer.timers.size, 0);
});

test("F05: invalid no-length JSON enters the existing fallback", async () => {
  const h = progressHarness(() => jsonResponse(async () => { throw new SyntaxError("bad JSON"); }));
  const state = observe(h.context.fetchJSONProgress("/full.json", null, null, 60000));
  await turn();
  assert.equal(state.status, "fulfilled");
  assert.equal(state.value.fallback, true);
  assert.equal(h.fallback.length, 1);
  assert.equal(h.timer.timers.size, 0);
});

test("F05: length-bearing streamed JSON and progress remain valid", { timeout: 3000 }, async () => {
  const payload = { rows: [1, 2] }, bytes = new TextEncoder().encode(JSON.stringify(payload));
  const chunks = [bytes.slice(0, 5), bytes.slice(5)];
  const h = progressHarness(() => ({ ok: true, headers: { get: () => String(bytes.length) },
    body: { getReader: () => ({ read: async () => chunks.length ? { value: chunks.shift(), done: false } : { done: true } }) } }));
  const progress = [];
  const value = await h.context.fetchJSONProgress("/full.json", (...args) => progress.push(args), null, 60000);
  assert.deepEqual(JSON.parse(JSON.stringify(value)), payload);
  assert.deepEqual(progress.at(-1), [bytes.length, bytes.length]);
  assert.equal(h.fallback.length, 0);
  assert.equal(h.timer.timers.size, 0);
});

function realFallbackHarness(makeResponse, preferred = false) {
  const timer = clock(), calls = [], inflight = new Map();
  const context = vm.createContext({
    AbortController, Blob, console: quiet, location: { hostname: "ss.fx8.store" },
    _isMainSite: () => true, _NO_CACHE_URLS: /^$/, _NO_R2_CACHE_URLS: /^$/,
    _resultCache: new Map(), _inflightFetch: inflight, _CACHE_TTL: 300000,
    _R2_FALLBACK_BASE: "https://ss.fx8.store/data/", _R2_ROOT_BASE: "https://ss.fx8.store/r2/",
    window: { _tdsSsdUrlFor: () => "https://ssd.fx8.store/lab/full.json",
      _tdsSsdPreferredUntil: preferred ? Date.now() + 90000 : 0 },
    setTimeout: timer.setTimeout, clearTimeout: timer.clearTimeout,
    async fetch(url, options = {}) {
      calls.push({ url, signal: options.signal });
      if (options.signal?.aborted) return untilAbort(options.signal);
      return makeResponse(url, options.signal, calls.length);
    },
  });
  vm.runInContext(fetchSource + "\n" + progressSource, context);
  return { context, timer, calls, inflight };
}

test("F05: cancellation survives bad JSON and the real SSD fallback body", async () => {
  const h = realFallbackHarness((url, signal, n) => {
    if (n === 1) return jsonResponse(async () => { throw new SyntaxError("bad JSON"); });
    if (n === 2) return { ok: false, status: 503 };
    return jsonResponse(() => untilAbort(signal));
  });
  const outer = new AbortController();
  const state = observe(h.context.fetchJSONProgress("https://ss.fx8.store/r2/lab/full.json", null, outer.signal, 60000));
  await turn();
  assert.equal(h.calls.length, 3);
  assert.match(h.calls[2].url, /ssd\.fx8\.store/);
  outer.abort(); await turn();
  assert.equal(state.status, "rejected");
  assert.equal(state.error.name, "AbortError");
  assert.equal(h.calls[2].signal.aborted, true);
  assert.equal(h.timer.timers.size, 0);
  assert.equal(h.inflight.size, 0);
});

test("fetchJSON: cancelled relative fallback stops before later legs", async () => {
  const h = realFallbackHarness((url, signal, n) => n === 1
    ? { ok: false, status: 503 } : jsonResponse(() => untilAbort(signal)));
  const outer = new AbortController();
  const state = observe(h.context.fetchJSON("./data/sample.json", 15000, outer.signal));
  await turn();
  assert.equal(h.calls.length, 2);
  outer.abort(); await turn();
  assert.equal(state.status, "rejected");
  assert.equal(state.error.name, "AbortError");
  assert.equal(h.calls.length, 2, "no R2 or SSD attempt after cancellation");
  assert.equal(h.calls[1].signal.aborted, true);
  assert.equal(h.timer.timers.size, 0);
  assert.equal(h.inflight.size, 0);
});

test("fetchJSON: cancellation aborts both preferred-race bodies", async () => {
  const h = realFallbackHarness((url, signal) => jsonResponse(() => untilAbort(signal)), true);
  const outer = new AbortController();
  const state = observe(h.context.fetchJSON("https://ss.fx8.store/r2/lab/full.json", 60000, outer.signal));
  await turn();
  assert.equal(h.calls.length, 2);
  outer.abort(); await turn();
  assert.equal(state.status, "rejected");
  assert.equal(state.error.name, "AbortError");
  assert.ok(h.calls.every(call => call.signal.aborted));
  assert.equal(h.calls.length, 2, "no regular request after a cancelled race");
  assert.equal(h.timer.timers.size, 0);
  assert.equal(h.inflight.size, 0);
});

test("fetchJSON: primary timeout still permits a fresh SSD controller", async () => {
  const payload = { source: "ssd" };
  const h = realFallbackHarness((url, signal, n) => n === 1
    ? untilAbort(signal) : jsonResponse(async () => payload));
  const state = observe(h.context.fetchJSON("https://ss.fx8.store/r2/lab/full.json", 60000));
  await turn();
  assert.equal(h.timer.fire(), 60000);
  await turn();
  assert.equal(state.status, "fulfilled");
  assert.equal(state.value, payload);
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[1].signal.aborted, false, "primary timeout is not user cancellation");
  assert.equal(h.timer.timers.size, 0);
  assert.equal(h.inflight.size, 0);
});

test("fetchJSON: successful preferred race clears loser without cancelling result", async () => {
  const payload = { source: "main" };
  const h = realFallbackHarness((url, signal) => url.includes("ssd.fx8.store")
    ? jsonResponse(() => untilAbort(signal)) : jsonResponse(async () => payload), true);
  assert.equal(await h.context.fetchJSON("https://ss.fx8.store/r2/lab/full.json", 60000), payload);
  assert.equal(h.calls.length, 2);
  assert.ok(h.calls.every(call => call.signal.aborted));
  assert.equal(h.timer.timers.size, 0);
  assert.equal(h.inflight.size, 0);
});

function bootHarness(host, mode) {
  const timer = clock(), calls = [], fallback = [], payload = { overview: { date: "fixture" } };
  const context = vm.createContext({
    location: { hostname: host }, window: {}, AbortController, console: quiet,
    setTimeout: timer.setTimeout, clearTimeout: timer.clearTimeout,
    fetch(url, options = {}) {
      calls.push({ url, signal: options.signal });
      const secondary = url.includes("ssd.fx8.store");
      if (mode === "normal" || (secondary && !mode.startsWith("all-"))) {
        return Promise.resolve(jsonResponse(async () => payload));
      }
      return mode.endsWith("headers") ? untilAbort(options.signal)
        : Promise.resolve(jsonResponse(() => untilAbort(options.signal)));
    },
    async fetchJSON(...args) { fallback.push(args); throw new Error("visible fetchJSON failure"); },
  });
  vm.runInContext(bootScripts[0] + "\n" + guardSource + "\n" + bootConsumer, context);
  return { context, timer, calls, fallback, payload };
}

for (const host of ["ss.fx8.store", "localhost", "sss.sugas.site"]) {
  for (const phase of ["headers", "body"]) {
    test("F06: " + host + " stalled " + phase + " reaches SSD within its deadline", async () => {
      const h = bootHarness(host, "primary-" + phase);
      const state = observe(h.context._bootJSON());
      await turn();
      assert.equal(h.timer.fire(), host === "sss.sugas.site" ? 8000 : 15000);
      await turn();
      assert.equal(state.status, "fulfilled");
      assert.equal(state.value, h.payload);
      assert.equal(h.calls.length, 2);
      assert.equal(h.calls[0].signal.aborted, true);
      assert.equal(h.fallback.length, 0);
      assert.equal(h.timer.timers.size, 0);
    });
    test("F06: " + host + " both legs stall at " + phase + " then expose fallback failure", async () => {
      const h = bootHarness(host, "all-" + phase);
      const state = observe(h.context._bootJSON());
      await turn(); h.timer.fire(); await turn();
      assert.equal(h.timer.fire(), 6000);
      await turn();
      assert.equal(state.status, "rejected");
      assert.equal(state.error.message, "visible fetchJSON failure");
      assert.equal(h.fallback.length, 1);
      assert.equal(h.timer.timers.size, 0);
    });
  }
  test("F06: " + host + " normal boot consumes one shared request", async () => {
    const h = bootHarness(host, "normal");
    assert.equal(await h.context._bootJSON(), h.payload);
    assert.equal(h.calls.length, 1);
    assert.equal(h.fallback.length, 0);
    assert.equal(h.timer.timers.size, 0);
  });
}
