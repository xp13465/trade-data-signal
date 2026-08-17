#!/usr/bin/env node
/**
 * accept.js — Playwright 前端验收主入口(通用脚手架)
 *
 * 目的:把「看图验收」变成「程序化断言」——抓 console 报错、网络请求、DOM 断言、
 *       accessibility snapshot,输出全是文本,主控/ reviewer/tester 可直接读。
 *
 * 用法:
 *   node accept.js <URL> [options]
 *
 *   URL           必填。本地静态站(如 http://localhost:8000)或线上三站
 *                 (https://ss.fx8.store / https://sss.sugas.site / https://s.sugas.site)
 *
 *   options:
 *     --expect-request <子串>  断言某个请求确实发出且 HTTP 200(可多次,子串匹配 URL)
 *     --block <子串>           屏蔽匹配该子串的请求(模拟源故障,验证降级;可多次)
 *     --assert <选择器|期望>   DOM 断言,格式 `选择器|期望文本/存在/属性`(可多次)
 *                              期望值写法:
 *                                `#title|text=跑马灯`    文本包含
 *                                `#container|exists`     元素存在
 *                                `#el|attr=src=xxx`      属性值(等号后为值,子串)
 *                                `#el|count=8`           匹配元素数量
 *     --assert-file <路径>     从文件读断言列表(每行一条,格式同 --assert)
 *     --block-on-error         有 error 级 console 或 pageerror 时进程 exit 非 0
 *     --expect-request-missing <子串>  断言某请求未发出(用于验证降级后旧源已停)
 *     --wait <ms>              页面加载后额外等待毫秒(默认 0,给前端渲染/网络留时间)
 *     --help                   显示本帮助
 *
 * 退出码:
 *   0 = 全部 PASS;1 = 有 FAIL / 有 error 级 console 且 --block-on-error / 参数错误
 *
 * 复现:
 *   python3 -m http.server 8000 -d /Users/linhuichen/code/trade/static-site
 *   node accept.js http://localhost:8000 \
 *     --expect-request news_digest.json \
 *     --assert '#app|exists'
 */
'use strict';

const { chromium } = require('playwright');

// ---------- 参数解析 ----------
const args = process.argv.slice(2);
const opts = { expectRequest: [], block: [], assert: [], expectMissing: [] };

function parseArgs() {
  if (args.length === 0 || args[0] === '--help' || args[0] === '-h') {
    printHelp();
    process.exit(args.length === 0 ? 1 : 0);
  }
  opts.url = args[0];
  for (let i = 1; i < args.length; i++) {
    const a = args[i];
    if (a === '--expect-request') { opts.expectRequest.push(args[++i]); }
    else if (a === '--block') { opts.block.push(args[++i]); }
    else if (a === '--assert') { opts.assert.push(args[++i]); }
    else if (a === '--expect-request-missing') { opts.expectMissing.push(args[++i]); }
    else if (a === '--assert-file') { opts.assertFile = args[++i]; }
    else if (a === '--block-on-error') { opts.blockOnError = true; }
    else if (a === '--wait') { opts.wait = parseInt(args[++i], 10) || 0; }
    else if (a.startsWith('--')) { console.error(`[参数错误] 未知选项: ${a}`); process.exit(1); }
  }
}

function printHelp() {
  console.log(`Playwright 前端验收脚手架 accept.js

用法:
  node accept.js <URL> [options]

必填 URL: 本地静态站或线上三站。

选项:
  --expect-request <子串>      断言某请求发出且 200(可多次)
  --expect-request-missing <子串> 断言某请求未发出(验证降级后旧源已停)
  --block <子串>               屏蔽匹配请求,模拟源故障(可多次)
  --assert <选择器|期望>        DOM 断言,格式见文件头 docstring
  --assert-file <路径>          从文件读断言列表(每行一条)
  --block-on-error             有 error 级 console/pageerror 则 exit 1
  --wait <ms>                  加载后额外等待毫秒
  --help                       本帮助`);
}

// ---------- 工具 ----------
function parseAssertion(spec) {
  // 格式: `选择器|期望`  |  期望可为 text=xxx / exists / attr=key=value / count=N
  const pipe = spec.indexOf('|');
  if (pipe < 0) {
    return { raw: spec, error: `断言格式错误(缺 |): ${spec}` };
  }
  const selector = spec.slice(0, pipe).trim();
  const expect = spec.slice(pipe + 1).trim();
  return { selector, expect, raw: spec };
}

// ---------- 主流程 ----------
(async () => {
  parseArgs();

  const results = { console: [], pageErrors: [], requests: [], failures: [], passes: [] };

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  // a. console 抓取
  page.on('console', (msg) => {
    const level = msg.type();
    if (level === 'error' || level === 'warning') {
      results.console.push({ level, text: msg.text(), location: msg.location() });
    }
  });
  page.on('pageerror', (err) => {
    results.pageErrors.push(String(err));
  });

  // b. 网络记录 + 屏蔽
  const seenRequests = new Set();       // 全部已发出请求 url
  const responses = new Map();          // url -> 最终状态码(含重定向链末)
  page.on('request', (req) => {
    seenRequests.add(req.url());
  });
  page.on('response', (resp) => {
    const url = resp.url();
    // 跟随重定向,记录最终状态
    let status = resp.status();
    let u = url;
    if (resp.request().redirectedFrom()) {
      // 若为最终响应,把中间重定向也映射到最终状态(简单处理:记录实际响应)
      u = url;
    }
    responses.set(u, status);
  });
  if (opts.block.length > 0) {
    await page.route('**/*', (route) => {
      const url = route.request().url();
      const blocked = opts.block.some((b) => url.includes(b));
      if (blocked) {
        console.log(`[BLOCK] ${url}`);
        route.abort();
      } else {
        route.continue();
      }
    });
  }

  try {
    const response = await page.goto(opts.url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    if (response) results.requests.push({ url: opts.url, status: response.status() });
  } catch (e) {
    results.failures.push(`页面加载失败: ${e.message}`);
  }

  if (opts.wait) await page.waitForTimeout(opts.wait);

  // --expect-request 断言:先从已记录响应集合查(含 goto 前已完成的请求),
  // 再给后续动态请求留时间(前端懒加载/轮询可能在 --wait 后才发)。
  const waitExtra = opts.wait || 5000;
  for (const exp of opts.expectRequest) {
    let hit = [...responses.entries()].find(([u]) => u.includes(exp));
    if (!hit && waitExtra > 0) {
      // 再等一次动态请求
      try {
        const resp = await page.waitForResponse(
          (r) => r.url().includes(exp) && r.status() < 400,
          { timeout: waitExtra }
        );
        hit = [resp.url(), resp.status()];
      } catch (e) { /* 仍未等到 */ }
    }
    if (hit) {
      const [u, status] = hit;
      results.requests.push({ url: exp, status });
      if (status >= 400) {
        results.failures.push(`[断言 FAIL] 请求 ${exp} 返回错误状态码 ${status}`);
      } else {
        results.passes.push(`[断言 PASS] 请求发出且 ${status}: ${exp} -> ${u.slice(0, 120)}`);
      }
    } else {
      results.failures.push(`[断言 FAIL] 未发现发出请求: ${exp}`);
    }
  }
  // 未发出断言:判断「该源是否还有有效(非被屏蔽)响应」。block 会 abort 请求但仍算
  // 发起过,故用 responses(有 2xx 响应)判断旧源是否仍在被有效使用,而非 seenRequests。
  for (const miss of opts.expectMissing) {
    const hit = [...responses.entries()].filter(([u]) => u.includes(miss));
    if (hit.length > 0) {
      results.failures.push(`[断言 FAIL] 期望失效的请求源仍有响应: ${miss} -> ${hit[0][0].slice(0, 120)} (${hit[0][1]})`);
    } else {
      results.passes.push(`[断言 PASS] 请求源已失效(无有效响应): ${miss}`);
    }
  }

  // c. DOM 断言
  const assertSpecs = [];
  for (const a of opts.assert) assertSpecs.push(parseAssertion(a));
  if (opts.assertFile) {
    const fs = require('fs');
    const lines = fs.readFileSync(opts.assertFile, 'utf8').split('\n');
    for (const line of lines) {
      const t = line.trim();
      if (t && !t.startsWith('#')) assertSpecs.push(parseAssertion(t));
    }
  }
  for (const spec of assertSpecs) {
    if (spec.error) { results.failures.push(`[断言 FAIL] ${spec.error}`); continue; }
    try {
      const { selector, expect } = spec;
      let ok = false;
      let detail = '';
      if (expect === 'exists') {
        ok = await page.locator(selector).count() > 0;
        detail = `元素 ${ok ? '存在' : '不存在'}: ${selector}`;
      } else if (expect.startsWith('count=')) {
        const want = parseInt(expect.slice(6), 10);
        const got = await page.locator(selector).count();
        ok = got === want;
        detail = `${selector} 数量期望 ${want} 实际 ${got}`;
      } else if (expect.startsWith('text=')) {
        const want = expect.slice(5);
        const got = await page.locator(selector).first().textContent().catch(() => null);
        ok = !!got && got.includes(want);
        detail = `${selector} 文本${ok ? '包含' : '不包含'} "${want}" 实际="${(got || '').slice(0, 80)}"`;
      } else if (expect.startsWith('attr=')) {
        const rest = expect.slice(5);
        const eq = rest.indexOf('=');
        const key = rest.slice(0, eq);
        const want = rest.slice(eq + 1);
        const got = await page.locator(selector).first().getAttribute(key).catch(() => null);
        ok = !!got && got.includes(want);
        detail = `${selector} 属性 ${key}${ok ? '包含' : '不包含'} "${want}" 实际="${got || ''}"`;
      } else {
        results.failures.push(`[断言 FAIL] 未知期望类型: ${expect}`);
        continue;
      }
      if (ok) results.passes.push(`[断言 PASS] ${detail}`);
      else results.failures.push(`[断言 FAIL] ${detail}`);
    } catch (e) {
      results.failures.push(`[断言 FAIL] ${spec.selector}: 断言执行异常 ${e.message}`);
    }
  }

  await browser.close();

  // ---------- 汇总输出 ----------
  console.log('\n==================== console 抓取 ====================');
  if (results.console.length === 0) console.log('(无 error/warning 级 console 输出)');
  for (const c of results.console) {
    console.log(`[${c.level.toUpperCase()}] ${c.text}${c.location && c.location.url ? `  @ ${c.location.url}:${c.location.lineNumber}` : ''}`);
  }
  if (results.pageErrors.length === 0) {
    console.log('(无未捕获页面异常 pageerror)');
  } else {
    for (const e of results.pageErrors) console.log(`[PAGEERROR] ${e}`);
  }

  console.log('\n==================== 网络请求 ====================');
  if (seenRequests.size === 0) console.log('(无网络请求被记录)');
  for (const u of seenRequests) console.log(`  ${u}`);
  console.log('\n==================== 断言结果 ====================');
  for (const p of results.passes) console.log(p);
  for (const f of results.failures) console.log(f);

  let fail = results.failures.length > 0;
  if (opts.blockOnError && (results.console.some(c => c.level === 'error') || results.pageErrors.length > 0)) {
    fail = true;
    console.log('\n[error 级 console 或 pageerror 存在且 --block-on-error 开启 → FAIL]');
  }
  console.log(`\n=========== 结果: ${fail ? 'FAIL' : 'PASS'} (${results.passes.length} PASS / ${results.failures.length} FAIL) ===========`);
  process.exit(fail ? 1 : 0);
})();
