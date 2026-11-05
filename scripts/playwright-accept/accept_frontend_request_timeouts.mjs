#!/usr/bin/env node
// 实施自验 #369/#370 及三个辅助加载器；不替代 Claude 独立审查。仅访问自己的本地 HTTP 服务。
// NODE_PATH=<已有 node_modules> node scripts/playwright-accept/accept_frontend_request_timeouts.mjs
// 或 PLAYWRIGHT_MODULE_PATH=<playwright 包路径>；不下载浏览器。
// FRONTEND_SOURCE_REF=<git ref> 可只读验证旧代码，FRONTEND_EVIDENCE_DIR 可隔离证据。
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const require = createRequire(import.meta.url);
const { chromium, webkit } = require(process.env.PLAYWRIGHT_MODULE_PATH || 'playwright');
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const evidence = process.env.FRONTEND_EVIDENCE_DIR || '/tmp/codex-reports/night-20261105/browser';
const scale = Number(process.env.FRONTEND_TIMEOUT_SCALE || 0.02);
assert.ok(scale > 0 && scale <= 1, 'FRONTEND_TIMEOUT_SCALE 必须在 (0,1]');
fs.mkdirSync(evidence, { recursive: true });
const progressFile = path.join(evidence, 'progress.log');
function progress(message) { fs.appendFileSync(progressFile, `${new Date().toISOString()} ${message}\n`); }
function source(file) {
  return process.env.FRONTEND_SOURCE_REF
    ? execFileSync('git', ['show', `${process.env.FRONTEND_SOURCE_REF}:${file}`], { cwd: root, timeout: 10000, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 })
    : fs.readFileSync(path.join(root, file), 'utf8');
}
// 与 Node 回归相同：唯一声明锚点 + JS 解析器确定完整声明，不复制业务实现。
function declaration(text, name) {
  const matches = [...text.matchAll(new RegExp('\\b(?:async\\s+)?function\\s+' + name + '\\s*\\(', 'g'))];
  assert.equal(matches.length, 1, `唯一函数 ${name}`);
  const start = matches[0].index;
  for (let end = text.indexOf('}', start); end >= 0 && end - start < 32768; end = text.indexOf('}', end + 1)) {
    const code = text.slice(start, end + 1);
    try { new vm.Script(code); return code; } catch (error) { if (!(error instanceof SyntaxError)) throw error; }
  }
  throw new Error(`无法提取 ${name}`);
}
const lab = source('static-site/lab.js'), app = source('static-site/app.js'), html = source('static-site/index.html');
const common = source('static-site/common.js');
const boots = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)]
  .map(match => match[1]).filter(code => code.includes('__bootPrefetch') && code.includes('firstMs'));
assert.equal(boots.length, 1, '唯一 boot 预取脚本');
const globalsAnchor = 'const _inflightFetch = new Map();';
assert.equal(app.split(globalsAnchor).length, 2, '唯一 fetchJSON 依赖区起点');
const fetchSource = declaration(app, 'fetchJSON');
const globals = app.slice(app.indexOf(globalsAnchor), app.indexOf(fetchSource));
assert.ok(globals.length > 0 && globals.length < 10000, 'fetchJSON 依赖区范围');
// SSD 地址映射也从 common.js 原文提取，不能在测试里复制业务映射规则。
const mappingStart = 'window._TDS_SSD_BASE =', mappingEnd = 'window._tdsSsdPreferredUntil = window._tdsSsdPreferredUntil || 0;';
assert.equal(common.split(mappingStart).length, 2, '唯一 SSD 映射区起点');
assert.equal(common.split(mappingEnd).length, 2, '唯一 SSD 映射区终点');
const mapping = common.slice(common.indexOf(mappingStart), common.indexOf(mappingEnd) + mappingEnd.length);
assert.ok(mapping.length > 0 && mapping.length < 10000, 'SSD 映射区范围');
const extracted = {
  fetchJSON: fetchSource,
  fetchJSONProgress: declaration(lab, 'fetchJSONProgress'),
  _bootJSON: declaration(app, '_bootJSON'),
  _isMainSite: declaration(app, '_isMainSite'),
  _labKellyFetchTrades: declaration(lab, '_labKellyFetchTrades'),
  _labKellyTradesUrl: declaration(lab, '_labKellyTradesUrl'),
  _labKellyTradesUrlCf: declaration(lab, '_labKellyTradesUrlCf'),
  _fundScoreApiFetch: declaration(app, '_fundScoreApiFetch'),
  _fundScreenerApiFetch: declaration(app, '_fundScreenerApiFetch'),
};
const production = [mapping, globals, ...Object.values(extracted)].join('\n');
new vm.Script(production);

const cases = [
  { id: 'f05-timeout-body', family: 'F05', mode: 'body', expected: 'fallback' },
  { id: 'f05-user-cancel', family: 'F05', mode: 'body', expected: 'cancelled' },
  { id: 'f05-ssd-body-user-cancel', family: 'F05', mode: 'ssd-body', expected: 'cancelled', ssdCancel: true },
  { id: 'f05-normal-json', family: 'F05', mode: 'normal', expected: 'primary' },
  { id: 'f06-timeout-headers', family: 'F06', mode: 'headers', expected: 'ssd' },
  { id: 'f06-timeout-body', family: 'F06', mode: 'body', expected: 'ssd' },
  { id: 'f06-normal-shared', family: 'F06', mode: 'normal', expected: 'primary' },
];
for (const [name, func] of [['fund-score', '_fundScoreApiFetch'], ['fund-screener', '_fundScreenerApiFetch']]) {
  for (const mode of ['body', 'headers', 'normal']) {
    cases.push({ id: `${name}-${mode}`, family: 'FUND', aux: true, func, mode, plan: [mode], budget: 15000, expected: mode === 'normal' ? 'primary' : 'aborted' });
  }
}
for (const [leg, name] of ['r2', 'cf', 'ssd'].entries()) {
  for (const mode of ['body', 'headers', 'normal']) {
    const plan = [...Array(leg).fill('http'), mode];
    if (mode !== 'normal' && leg < 2) plan.push('normal');
    cases.push({ id: `kelly-${name}-${mode}`, family: 'KELLY', aux: true, mode, plan, budget: 60000,
      expected: mode === 'normal' ? name : leg < 2 ? ['r2', 'cf', 'ssd'][leg + 1] : 'aborted' });
  }
}
cases.push({ id: 'kelly-all-body', family: 'KELLY', aux: true, mode: 'body', plan: ['body', 'body', 'body'], budget: 60000, expected: 'aborted' });
const states = new Map(), sockets = new Set(), pendingResponses = new Set();
const results = [], blocked = [], browserRuns = [];
let origin, activeBrowser, activeContext, activePage;
const report = {
  kind: 'implementation-self-check', independentReview: false,
  sourceRef: process.env.FRONTEND_SOURCE_REF || 'worktree', scale,
  sourceSha256: Object.fromEntries([['lab.js', lab], ['app.js', app], ['index.html', html], ['common.js', common]]
    .map(([name, code]) => [name, createHash('sha256').update(code).digest('hex')])),
  functionSha256: Object.fromEntries(Object.entries(extracted).map(([name, code]) => [name, createHash('sha256').update(code).digest('hex')])),
  timingNote: '应用 setTimeout 按比例缩放；fetch/响应正文/AbortController 均为浏览器原生。手机 viewport 为模拟视口；未验真机及实际 15/60 秒 SLA。',
  authNote: '全新无痕上下文，固定假 token browser-test-fake-token；auth/cache-bust 环境函数为桩，不读用户 token。',
  originalBudgetsMs: { F05: 60000, F06LocalPrimary: 15000, F06BackupPrimary: 8000, F06Ssd: 6000, fundScore: 15000, fundScreener: 15000, kellyEachLeg: 60000 },
  results, browserRuns, blocked,
};

// 只改测试的传输目的地和时钟；真实函数/boot 原文直接装载。
function harness(config, token) {
  const setup = `
    const config = ${JSON.stringify(config)}, token = ${JSON.stringify(token)};
    const nativeFetch = window.fetch.bind(window), nativeSetTimeout = window.setTimeout.bind(window);
    const nativeClearTimeout = window.clearTimeout.bind(window);
    const trace = window.trace = { calls: [], timers: [], progress: [], errors: [] };
    // 只提供加载器依赖的环境；业务加载器及凯利 URL helper 均加载生产原文。
    window._authApiBase = () => 'https://ss.fx8.store';
    window._getAuthToken = () => 'browser-test-fake-token';
    window._labCustomCacheBust = () => 'browser-fixture';
    const fetchSignals = window.fetchSignals = [];
    const activeTimers = new Map(), recordedTimers = new Map();
    window.setTimeout = (fn, ms, ...args) => {
      const item = { originalMs: ms, scaledMs: Math.max(1, Math.round(ms * ${scale})), fired: false, cleared: false, createdAt: performance.now() };
      trace.timers.push(item);
      const id = nativeSetTimeout(() => { item.fired = true; item.firedAt = performance.now(); activeTimers.delete(id); fn(...args); }, item.scaledMs);
      activeTimers.set(id, item); recordedTimers.set(id, item); return id;
    };
    window.clearTimeout = id => { const item = recordedTimers.get(id); if (item) item.cleared = true; activeTimers.delete(id); nativeClearTimeout(id); };
    window.fetch = async (input, options = {}) => {
      const requested = new URL(input, location.href);
      if (![location.origin, 'https://ss.fx8.store', 'https://ssd.fx8.store'].includes(requested.origin)) throw new Error('禁止外网: ' + requested);
      const ssd = requested.hostname === 'ssd.fx8.store';
      const local = new URL(ssd ? '/fixture/ssd.json' : requested.pathname, location.origin);
      local.search = requested.search;
      local.searchParams.set('case', token);
      const authorization = new Headers(options.headers).get('authorization');
      if (authorization && authorization !== 'Bearer browser-test-fake-token') throw new Error('只允许固定假 token');
      const item = { original: String(input), local: local.href, ssd, aborted: false, started: performance.now(), authorization, credentials: options.credentials, cache: options.cache };
      trace.calls.push(item);
      fetchSignals.push(options.signal);
      options.signal?.addEventListener('abort', () => { item.aborted = true; item.abortAt = performance.now(); }, { once: true });
      try {
        const response = await nativeFetch(local.href, options);
        item.headersAt = performance.now(); item.contentLength = response.headers.get('content-length'); item.status = response.status;
        document.querySelector('#phase').textContent = '已收到响应头，等待正文';
        return response;
      } catch (error) { item.error = error.name; throw error; }
    };
    window.addEventListener('error', event => trace.errors.push(event.message));
    window.addEventListener('unhandledrejection', event => trace.errors.push(String(event.reason)));
    document.querySelector('#scenario').textContent = config.id + ' / ' + location.hostname;
    document.querySelector('#budget').textContent = '原预算 F05/凯利每腿=60000ms；基金/boot 本地=15000ms，boot 备站=8000ms，SSD=6000ms；时钟比例=${scale}，未验真机或实际秒数SLA';
  `;
  const runner = `
    const controller = new AbortController();
    document.querySelector('#cancel').onclick = event => {
      trace.cancel = { at: performance.now(), callCount: trace.calls.length, trusted: event.isTrusted };
      controller.abort();
      trace.cancel.nativeSignalAbortedAfterClick = fetchSignals.at(-1)?.aborted;
      document.querySelector('#phase').textContent = '用户点击取消';
    };
    document.querySelector('#start').onclick = async () => {
      document.querySelector('#start').disabled = true;
      const started = performance.now();
      try {
        const pre = window.__bootPrefetch;
        const promise = config.family === 'FUND' ? window[config.func]('page=1&size=1&source=browser-fixture')
          : config.family === 'KELLY' ? _labKellyFetchTrades('browser-kelly.json')
          : config.family === 'F05'
          ? fetchJSONProgress(config.ssdCancel ? 'https://ss.fx8.store/r2/lab/lab-test.json' : './data/lab-test.json', (...args) => trace.progress.push(args), controller.signal, 60000)
          : _bootJSON();
        const data = await promise;
        // 正常预取的生产消费者与预取观察者使用同一对象，且消费后清空。
        trace.shared = config.family === 'F06' ? data === await pre : null;
        window.outcome = { status: data.via, data, elapsedMs: performance.now() - started };
      } catch (error) { window.outcome = { status: error.name === 'AbortError' ? (config.expected === 'aborted' ? 'aborted' : 'cancelled') : 'error', error: String(error), errorName: error.name, elapsedMs: performance.now() - started }; }
      trace.activeTimers = activeTimers.size;
      document.querySelector('#phase').textContent = window.outcome.status === 'cancelled' ? '用户已取消，请求已中止' : '请求已结束';
      document.querySelector('#status').textContent = window.outcome.status;
      document.querySelector('#details').textContent = JSON.stringify({ outcome: window.outcome, trace }, null, 2);
    };
  `;
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>前端请求超时本地自验</title>
    <style>body{font:16px system-ui;margin:20px;max-width:1000px;overflow-wrap:anywhere}button{font:inherit;padding:12px;margin:6px}pre{white-space:pre-wrap;font-size:12px}#status{font-weight:bold;color:#075b37}</style></head><body>
    <h1>真实浏览器请求自验</h1><p id="scenario"></p><p id="budget"></p><button id="start">开始请求</button><button id="cancel">取消请求</button>
    <p id="phase">等待开始</p><p>状态：<span id="status">pending</span></p><pre id="details"></pre>
    <script>${setup}</script><script src="/source/production.js"></script>
    ${config.family === 'F06' ? '<script src="/source/boot.js"></script>' : ''}<script>${runner}</script></body></html>`;
}
const server = http.createServer((req, res) => {
  const url = new URL(req.url, 'http://127.0.0.1');
  res.setHeader('Cache-Control', 'no-store');
  if (url.pathname === '/source/production.js' || url.pathname === '/source/boot.js') {
    res.setHeader('Content-Type', 'text/javascript; charset=utf-8');
    res.end(url.pathname.endsWith('/boot.js') ? boots[0] : production); return;
  }
  const token = url.searchParams.get('case'), state = states.get(token);
  if (!state) { res.writeHead(404); res.end('unknown fixture'); return; }
  if (url.pathname === '/') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8'); res.end(harness(state.config, token)); return;
  }
  if (!['/data/boot.json', '/data/lab-test.json', '/r2/lab/lab-test.json', '/fixture/ssd.json', '/data/browser-kelly.json', '/api/fund_score', '/api/fund_screener'].includes(url.pathname)) {
    res.writeHead(404); res.end('unexpected path'); return;
  }
  const ssd = url.pathname === '/fixture/ssd.json';
  const nth = state.requests.filter(item => !item.ssd).length + 1;
  const ssdCancel = !!state.config.ssdCancel;
  const stall = ssdCancel ? ssd : !ssd && state.config.mode !== 'normal' && nth === 1;
  const item = { path: url.pathname, ssd, nth, stall, phase: stall ? state.config.mode : 'normal', closed: false, finished: false };
  state.requests.push(item);
  pendingResponses.add(res);
  res.on('finish', () => { item.finished = true; });
  res.on('close', () => { item.closed = true; pendingResponses.delete(res); });
  res.setHeader('Content-Type', 'application/json');
  if (state.config.aux) {
    const index = state.requests.length - 1, fixture = state.config.plan[index];
    Object.assign(item, { fixture, stall: fixture === 'body' || fixture === 'headers', phase: fixture, authorization: req.headers.authorization || null, status: fixture === 'http' ? 503 : 200 });
    if (!fixture) { res.writeHead(500); res.end('unexpected request'); return; }
    if (fixture === 'headers') return;
    res.writeHead(item.status); res.flushHeaders();
    if (fixture === 'body') { res.write('{"stalled":'); return; }
    if (fixture === 'http') { res.end('{"fixture":"503"}'); return; }
    res.end(JSON.stringify({ via: state.config.family === 'KELLY' ? ['r2', 'cf', 'ssd'][index] : 'primary', fields: ['code'], quadrants: { A: [['fixture']] }, data: [{ code: 'fixture' }], total: 1 }));
    return;
  }
  if (ssdCancel && !ssd) {
    // 真实 fetchJSONProgress JSON 解析失败 → 真实 fetchJSON 同主源 503 → 真实 SSD 腿。
    item.status = nth === 1 ? 200 : 503;
    item.fixture = nth === 1 ? 'invalid-json' : 'primary-503';
    res.writeHead(item.status); res.flushHeaders(); res.end(nth === 1 ? '{invalid-json' : '{"error":"fixture unavailable"}'); return;
  }
  // 不发 Content-Length：body 场景 flush 真响应头 + 部分 JSON，故意不 end。
  if (stall) {
    if (state.config.mode === 'body' || ssdCancel) { res.flushHeaders(); res.write('{"stalled":'); }
    return; // headers 场景连响应头也不发送
  }
  res.flushHeaders();
  res.end(JSON.stringify({ via: ssd ? 'ssd' : nth > 1 ? 'fallback' : 'primary', rows: [1, 2], overview: { date: 'local-fixture' } }));
});
server.on('connection', socket => { sockets.add(socket); socket.on('close', () => sockets.delete(socket)); });

function checkAux(config, snapshot, requests) {
  const { calls, timers } = snapshot.trace;
  assert.equal(calls.length, config.plan.length, '实际请求数等于计划腿数，没有隐藏重试');
  assert.equal(timers.length, calls.length, '各腿独立定时器');
  assert.equal(timers.every(timer => timer.originalMs === config.budget), true, '原始每腿预算保持 15000/60000ms');
  assert.equal(timers.every(timer => timer.cleared), true, '每条已结算腿均执行清理');
  if (config.expected === 'aborted') assert.equal(snapshot.outcome.errorName, 'AbortError');
  else {
    assert.deepEqual(snapshot.outcome.data.data, [{ code: 'fixture' }]);
    if (config.family === 'KELLY') assert.deepEqual(snapshot.outcome.data.quadrants, { A: [['fixture']] });
  }
  for (const [index, fixture] of config.plan.entries()) {
    const call = calls[index], timer = timers[index], serverRequest = requests[index];
    assert.equal(snapshot.nativeSignals[index].native, true, '每腿使用原生 AbortSignal');
    assert.equal(serverRequest.fixture, fixture);
    if (fixture === 'headers' || fixture === 'body') {
      assert.equal(timer.fired, true, '停滞正文/响应头受原应用预算约束');
      assert.equal(call.aborted, true);
      assert.equal(snapshot.nativeSignals[index].aborted, true);
      assert.ok(call.abortAt >= timer.createdAt + timer.scaledMs - 2, '未提前中止正常预算');
      assert.equal(serverRequest.finished, false, '停滞响应从未完成');
      assert.equal(serverRequest.closed, true, '浏览器关闭页面前已中止停滞响应');
      if (fixture === 'body') {
        assert.equal(call.contentLength, null, '真实无 Content-Length 停滞正文');
        assert.equal(call.status, 200);
        assert.ok(call.headersAt < call.abortAt, '收到响应头后保持超时直到正文中止');
      } else assert.equal(call.headersAt, undefined, '响应头场景未发送 headers');
    } else {
      assert.equal(timer.fired, false);
      assert.equal(call.aborted, false, '成功/HTTP 失败腿清掉定时器，没有遗留 abort');
      assert.equal(call.status, fixture === 'http' ? 503 : 200);
    }
    if (config.family === 'FUND') {
      assert.equal(call.authorization, 'Bearer browser-test-fake-token');
      assert.equal(serverRequest.authorization, 'Bearer browser-test-fake-token', '本地服务只收到假 token');
      assert.equal(call.credentials, 'omit'); assert.equal(call.cache, 'no-cache');
      assert.ok(call.original.startsWith('https://ss.fx8.store/api/' + (config.func === '_fundScoreApiFetch' ? 'fund_score' : 'fund_screener') + '?page=1&size=1&source=browser-fixture'));
    } else {
      assert.equal(call.original, [
        'https://ss.fx8.store/data/browser-kelly.json?v=browser-fixture',
        './data/browser-kelly.json?v=browser-fixture',
        'https://ssd.fx8.store/data/browser-kelly.json?v=browser-fixture',
      ][index], '凯利原生产 URL helper 与 SSD 映射决定顺序');
      assert.equal(call.ssd, index === 2);
      if (index) {
        const previous = calls[index - 1];
        assert.ok(call.started >= (previous.abortAt ?? previous.headersAt), '前腿失败后才进入下一腿');
      }
    }
  }
}

async function runCase(browser, browserName, profile, config) {
  const token = `${browserName}-${profile.name}-${config.id}`;
  const state = { config, requests: [] }; states.set(token, state);
  let page, context, result = { browser: browserName, viewport: profile.name, case: config.id };
  const pageErrors = [], consoles = [];
  try {
    context = activeContext = await browser.newContext({ viewport: profile.viewport, ...(profile.mobile ? { isMobile: true, hasTouch: true } : {}), serviceWorkers: 'block' });
    context.setDefaultTimeout(5000);
    await context.route('**/*', route => {
      if (new URL(route.request().url()).origin === origin) return route.continue();
      blocked.push(route.request().url()); return route.abort('blockedbyclient');
    });
    page = activePage = await context.newPage();
    page.on('pageerror', error => pageErrors.push(String(error)));
    page.on('console', message => consoles.push({ type: message.type(), text: message.text() }));
    await page.goto(`${origin}/?case=${token}`, { waitUntil: 'load', timeout: 5000 });
    assert.equal(await page.evaluate(() => location.hostname), '127.0.0.1');
    await page.locator('#start').click();
    if (config.expected === 'cancelled') {
      if (config.ssdCancel) {
        await page.waitForFunction(() => trace.calls.some(call => call.ssd && call.headersAt !== undefined));
        assert.equal(state.requests.at(-1).stall, true, '点击前服务端 SSD 正文确实悬挂');
        assert.equal(state.requests.at(-1).finished, false);
      } else await page.waitForFunction(() => trace.calls[0]?.headersAt !== undefined);
      await page.locator('#cancel').click(); // 真实 DOM 按钮触发真实 AbortController
    }
    await page.waitForFunction(() => !!window.outcome, { }, { timeout: Math.max(4000, config.aux ? config.budget * config.plan.length * scale + 1500 : 65000 * scale * 2) });
    if (config.expected === 'cancelled') {
      // 取消后跨过原超时点，确认没有延迟重试。
      await new Promise(resolve => setTimeout(resolve, Math.ceil(60000 * scale) + 60));
    }
    const snapshot = await page.evaluate(() => ({ outcome, trace, nativeSignals: fetchSignals.map(signal => ({ native: signal instanceof AbortSignal, aborted: !!signal?.aborted })), prefetchConsumed: window.__bootPrefetch === null, ssdPreferred: window._tdsSsdPreferredUntil || 0 }));
    Object.assign(result, snapshot, { serverRequests: state.requests, pageErrors, consoles });
    assert.equal(snapshot.outcome.status, config.expected);
    assert.deepEqual(pageErrors, []); assert.deepEqual(snapshot.trace.errors, []);
    assert.equal(snapshot.trace.activeTimers, 0, '业务定时器全部释放');
    assert.equal(blocked.length, 0, '无外部网络请求');
    const calls = snapshot.trace.calls, timers = snapshot.trace.timers;
    if (config.expected === 'cancelled') {
      assert.equal(snapshot.trace.cancel.trusted, true, '真实 DOM 点击');
      assert.equal(snapshot.trace.cancel.nativeSignalAbortedAfterClick, true, '点击同步中止传给原生 fetch 的信号');
      assert.equal(calls.length, snapshot.trace.cancel.callCount, '取消后跨超时点没有新增请求');
      assert.equal(await page.locator('#status').textContent(), 'cancelled', 'DOM 呈现取消结果');
    }
    assert.equal(calls[0].ssd, false);
    if (config.mode !== 'headers') assert.equal(calls[0].contentLength, null, '真实无 Content-Length 响应');
    if (config.aux) {
      for (let retry = 0; state.requests.some(item => item.stall && !item.closed) && retry < 20; retry++) await new Promise(resolve => setTimeout(resolve, 25));
      checkAux(config, snapshot, state.requests);
    } else if (config.family === 'F05') {
      assert.equal(timers[0].originalMs, 60000);
      assert.equal(calls.length, config.ssdCancel ? 3 : config.expected === 'fallback' ? 2 : 1);
      assert.equal(calls[0].aborted, config.mode === 'body');
      assert.equal(timers[0].fired, config.expected === 'fallback');
      if (config.expected === 'cancelled') assert.equal(snapshot.outcome.data, undefined);
      if (config.ssdCancel) {
        assert.deepEqual(calls.map(call => call.status), [200, 503, 200]);
        assert.deepEqual(state.requests.map(item => item.fixture || 'ssd-body-stall'), ['invalid-json', 'primary-503', 'ssd-body-stall']);
        assert.equal(calls[2].ssd, true);
        assert.equal(calls[2].contentLength, null);
        assert.deepEqual(snapshot.nativeSignals[2], { native: true, aborted: true }, '真实 SSD 原生 signal 已取消');
        assert.equal(calls[2].aborted, true);
        assert.ok(calls[2].headersAt <= snapshot.trace.cancel.at, '收到 SSD 响应头后才点击取消');
        assert.equal(timers.at(-1).fired, false, 'SSD 中止由用户触发，未等自身超时');
        assert.equal(timers.at(-1).cleared, true);
        assert.equal(state.requests[2].closed, true, '页面关闭前，服务端已看到 SSD 连接中止');
        assert.equal(state.requests[2].finished, false);
      }
    } else {
      assert.ok(timers[0], 'boot 本地预取必须有应用级超时定时器');
      assert.equal(timers[0].originalMs, 15000, '本地 hostname 原始首腿预算');
      assert.equal(snapshot.prefetchConsumed, true);
      assert.equal(snapshot.trace.shared, true, '生产消费者与预取 Promise 共享同一对象');
      assert.equal(snapshot.ssdPreferred, 0, '本地不置备源优先闩');
      assert.equal(calls.length, config.expected === 'ssd' ? 2 : 1);
      assert.equal(calls[0].aborted, config.expected === 'ssd');
      if (config.expected === 'ssd') { assert.equal(calls[1].ssd, true); assert.equal(timers[1].originalMs, 6000); }
      else assert.equal(timers[0].cleared, true);
    }
    assert.equal(state.requests.length, calls.length, '请求计数有真实服务端证据');
    if (!config.aux && config.mode !== 'normal' && !config.ssdCancel) {
      await page.waitForFunction(() => trace.calls[0].aborted);
      assert.equal(state.requests[0].finished, false, '停滞响应没有伪造完成');
    }
    result.passed = true;
  } catch (error) {
    result.passed = false; result.error = error.stack;
    if (page) result.observed = await page.evaluate(() => ({ outcome: window.outcome, trace: window.trace })).catch(() => null);
  } finally {
    if (page) {
      const screenshot = path.join(evidence, `${token}.png`);
      await page.screenshot({ path: screenshot, fullPage: true, timeout: 5000 }).then(() => { result.screenshot = screenshot; }).catch(error => { result.screenshotError = String(error); });
      await page.close().catch(() => {}); activePage = null;
    }
    if (context) await context.close().catch(() => {}); activeContext = null;
    // 关闭该用例所有悬挂响应，保持其他用例隔离。
    for (const res of pendingResponses) if (res.req.url.includes(`case=${token}`)) res.destroy();
    result.serverRequests = state.requests;
    fs.writeFileSync(path.join(evidence, `${token}.json`), JSON.stringify(result, null, 2));
    results.push(result);
    console.log(`${result.passed ? '通过' : '失败'} ${token}${result.error ? ': ' + result.error.split('\n')[0] : ''}`);
    progress(`${result.passed ? '通过' : '失败'} ${token}`);
  }
}

async function cleanup() {
  if (activePage) await activePage.close().catch(() => {});
  if (activeContext) await activeContext.close().catch(() => {});
  if (activeBrowser) await activeBrowser.close().catch(() => {});
  for (const res of pendingResponses) res.destroy();
  for (const socket of sockets) socket.destroy();
  await new Promise(resolve => server.close(resolve));
  report.cleanup = { serverListening: server.listening, pendingResponses: pendingResponses.size, sockets: sockets.size };
}
try {
  await new Promise((resolve, reject) => { server.once('error', reject); server.listen(0, '127.0.0.1', resolve); });
  origin = `http://127.0.0.1:${server.address().port}`; report.origin = origin;
  progress(`本地服务 ${origin}；真实函数/唯一 boot 原文装载；时钟比例 ${scale}`);
  for (const [name, type] of [['chromium', chromium], ['webkit', webkit]]) {
    if (name === 'webkit' && !fs.existsSync(type.executablePath())) {
      browserRuns.push({ browser: name, status: '未验', reason: '未安装，按要求不安装' }); continue;
    }
    try { activeBrowser = await type.launch({ headless: true, timeout: 10000 }); }
    catch (error) {
      browserRuns.push({ browser: name, status: '启动失败', error: String(error) });
      if (name === 'chromium') throw error;
      continue;
    }
    browserRuns.push({ browser: name, status: '已运行', version: activeBrowser.version() });
    try {
      for (const profile of [{ name: 'desktop', viewport: { width: 1440, height: 900 } }, { name: 'mobile', viewport: { width: 390, height: 844 }, mobile: true }]) {
        for (const config of cases) await runCase(activeBrowser, name, profile, config);
      }
    } finally { await activeBrowser.close(); activeBrowser = null; }
  }
} catch (error) { report.fatal = error.stack; }
finally {
  await cleanup();
  // 若运行中另一个 worker 改过来源，证据判无效，不能把混合版本算作成功。
  report.sourcesUnchangedAtEnd = process.env.FRONTEND_SOURCE_REF ? true : Object.entries(report.sourceSha256)
    .every(([name, hash]) => createHash('sha256').update(fs.readFileSync(path.join(root, 'static-site', name))).digest('hex') === hash);
  report.passed = results.filter(item => item.passed).length;
  report.failed = results.filter(item => !item.passed).length;
  fs.writeFileSync(path.join(evidence, 'summary.json'), JSON.stringify(report, null, 2));
  progress(`完成：${report.passed} 通过 / ${report.failed} 失败；证据 ${evidence}；服务已关闭`);
}
console.log(JSON.stringify({ passed: report.passed, failed: report.failed, fatal: report.fatal, browserRuns, cleanup: report.cleanup, evidence }));
if (report.fatal || report.failed || !report.sourcesUnchangedAtEnd || report.passed < cases.length * 2 || report.cleanup.serverListening || report.cleanup.pendingResponses || report.cleanup.sockets) process.exitCode = 1;
