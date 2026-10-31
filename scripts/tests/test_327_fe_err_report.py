#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#327 前端错误上报+BUILD_ID收敛+每日汇总 单测（V2/V3/V4）。

V2: worker/err_report.js POST /api/err 逻辑（mock KV incr + R2 PUT）+ inline-init.js 1% 采样逻辑
V3: inline-init.js BUILD_ID reload 逻辑（mock 不一致 + 探活 isCoreShellReady）
V4: scripts/check_fe_err_stats.py 拉 stats ≥20 → notify severe + alert_ledger fe-err| 行（--dry-run）

V2/V3 通过 node 子进程跑 JS harness（mock KV/R2/DOM），断言行为。V4 纯 Python monkeypatch。
禁发通知（L48）: 全程 --dry-run / monkeypatch subprocess, 零真实外发。
"""
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
SCRIPTS = REPO / "scripts"
WORKER = REPO / "worker"
SS = REPO / "static-site"

NODE_BIN = os.environ.get("NODE_BIN", "node")


def _node_available() -> bool:
    try:
        subprocess.run([NODE_BIN, "--version"], capture_output=True, timeout=5, check=False)
        return True
    except Exception:
        return False


# ---------- V4: check_fe_err_stats.py 拉 stats ≥20 → severe + ledger（dry-run） ----------

def test_v4_fe_err_stats_below_threshold_dry_run():
    """count < 20 → 不告警, 不写台账, exit 0。"""
    from check_fe_err_stats import run as fe_run
    fake_stats = {"errors": [{"message": "minor", "filename": "app.js", "count": 5,
                              "build_id": "x", "first_ts": "", "last_ts": ""}],
                  "total": 1, "generated_at": "2026-10-31T00:00:00Z"}
    with mock.patch("check_fe_err_stats.fetch_stats", return_value=fake_stats):
        rc = fe_run(["--admin-pwd", "t", "--dry-run", "1"])
    assert rc == 0


def test_v4_fe_err_stats_above_threshold_dry_run():
    """count ≥ 20 → dry-run 模式打印 dedup_key, 不真调 notify / 不写台账。"""
    import check_fe_err_stats as mod
    fake_stats = {"errors": [{"message": "boom", "filename": "app.js", "count": 25,
                              "build_id": "b1", "first_ts": "t1", "last_ts": "t2"}],
                  "total": 1, "generated_at": "2026-10-31T00:00:00Z"}
    ledger_calls = []
    with mock.patch.object(mod, "fetch_stats", return_value=fake_stats), \
         mock.patch.object(mod, "_write_ledger", side_effect=lambda *a, **k: ledger_calls.append((a, k))):
        rc = mod.run(["--admin-pwd", "t", "--dry-run", "1"])
    assert rc == 0
    # dry-run 模式不应真写台账
    assert ledger_calls == []


def test_v4_fe_err_stats_above_threshold_writes_ledger_and_notifies():
    """count ≥ 20 + 非 dry-run → 真调 notify（打桩 subprocess）+ 写台账（打桩 _write_ledger）。"""
    import check_fe_err_stats as mod
    fake_stats = {"errors": [{"message": "boom", "filename": "app.js", "count": 30,
                              "build_id": "b1", "first_ts": "t1", "last_ts": "t2"}],
                  "total": 1, "generated_at": "2026-10-31T00:00:00Z"}
    notify_calls = []
    ledger_writes = []
    with mock.patch.object(mod, "fetch_stats", return_value=fake_stats), \
         mock.patch.object(mod.subprocess, "run", side_effect=lambda *a, **k: notify_calls.append((a, k)) or 0), \
         mock.patch.object(mod, "_write_ledger", side_effect=lambda *a, **k: ledger_writes.append(a)):
        rc = mod.run(["--admin-pwd", "t", "--dry-run", "0", "--notify-bin", "/bin/true"])
    assert rc == 0
    # 真调 notify 一次（severe + dedup-key fe-err|...）
    assert len(notify_calls) == 1
    args = notify_calls[0][0]
    cmd = args[0]
    assert "--severe" in cmd
    assert any("fe-err|" in c for c in cmd)
    # 写台账一次
    assert len(ledger_writes) == 1
    md5, count, date_str = ledger_writes[0]
    assert count == 30
    assert len(date_str) == 8  # YYYYMMDD


def test_v4_fe_err_stats_no_admin_pwd_skips():
    """无 admin pwd → 跳过本轮, exit 0（不阻塞）。"""
    from check_fe_err_stats import run as fe_run
    rc = fe_run(["--admin-pwd", ""])  # 空 pwd
    assert rc == 0


def test_v4_fe_err_stats_fetch_failure_does_not_block():
    """拉 stats 失败 → 不阻塞, exit 0。"""
    import check_fe_err_stats as mod
    with mock.patch.object(mod, "fetch_stats", side_effect=Exception("net")):
        rc = mod.run(["--admin-pwd", "t"])
    assert rc == 0


def test_v4_fe_err_dedup_key_uses_alert_denoise_prefix():
    """dedup_key 使用 alert_denoise_rules.FE_ERR_DEDUP_KEY_PREFIX（单一事实源）。"""
    import check_fe_err_stats as mod
    import alert_denoise_rules as adr
    key = mod.build_dedup_key("20261031", "abc123")
    assert key.startswith(adr.FE_ERR_DEDUP_KEY_PREFIX)
    assert "20261031" in key and "abc123" in key


def test_v4_fe_err_threshold_constant_matches():
    """alert_denoise_rules.FE_ERR_SEVERE_THRESHOLD = 20（D5 拍板）。"""
    import alert_denoise_rules as adr
    assert adr.FE_ERR_SEVERE_THRESHOLD == 20
    assert adr.FE_ERR_DEDUP_KEY_PREFIX == "fe-err|"


# ---------- V2/V3: node harness 跑 inline-init.js + err_report.js ----------

NODE_HARNESS_V2 = r"""
// V2: 测试 err_report.js POST /api/err 逻辑（mock KV incr + R2 PUT）
// err_report.js 用 ESM export 语法, 无 package.json type:module 时 Node 当 CJS 解析报错;
// 改为读源码 → 字符串变换(strip import/export default)→ new Function 注入 mock getSessionUser/jsonResponse。
const fs = require('fs');
let _src = fs.readFileSync(process.env.ERR_REPORT_PATH, 'utf8');
_src = _src.replace(/^import\s*\{[^}]*\}\s*from\s*['"][^'"]+['"];?\s*$/m, '');
_src = _src.replace(/export\s+default\s+async\s+function\s+errReportHandler/, 'async function errReportHandler');
// mock: getSessionUser 返回 null（测 no-auth 分支）, jsonResponse 造标准 JSON Response
const _mockGetSessionUser = async () => null;
function _mockJsonResponse(body, status, opts) {
  return new Response(JSON.stringify(body), { status: status || 200, headers: { 'content-type': 'application/json' } });
}
const _factory = new Function('getSessionUser', 'jsonResponse', _src + '\n; return errReportHandler;');
const errReport = _factory(_mockGetSessionUser, _mockJsonResponse);
class FakeKV {
  constructor() { this.store = {}; this.lists = 0; }
  async get(k) { return this.store[k] || null; }
  async put(k, v, opts) { this.store[k] = v; }
  async list(opts) { this.lists++; return { keys: Object.keys(this.store).filter(x=>x.startsWith(opts.prefix||'')).map(name=>({name})), list_complete: true }; }
  async delete(k) { delete this.store[k]; }
}
class FakeR2 {
  constructor() { this.puts = []; }
  async put(k, body, opts) { this.puts.push({k, body, opts}); }
  async get(k) { return null; }
}
const env = { SUBSCRIBE_KV: new FakeKV(), R2_BUCKET: new FakeR2(), FEEDBACK_ADMIN_PASSWORD: 'pwd' };
const ctx = { waitUntil: (p) => { try { p && p.then && p.then(()=>{}, ()=>{}); } catch(e){} } };

(async () => {
  // 1) POST /api/err 上报一条错误 → KV incr (count=1) + R2 样本写入
  const req1 = new Request('https://x/api/err', {
    method: 'POST',
    body: JSON.stringify({ message: 'probe-327', filename: 'app.js', lineno: 10, build_id: 'b1', ua: 'ua', pathname: '/', tab: 't1' }),
  });
  const r1 = await errReport(req1, env, ctx);
  console.log('R1_STATUS=' + r1.status);
  const kvKey = Object.keys(env.SUBSCRIBE_KV.store).find(k => k.startsWith('fe-err:b1:'));
  console.log('R1_KV_KEY=' + (kvKey ? 'YES' : 'NO'));
  const rec = JSON.parse(env.SUBSCRIBE_KV.store[kvKey]);
  console.log('R1_COUNT=' + rec.count);
  console.log('R1_MSG=' + rec.message);
  console.log('R1_R2_PUTS=' + env.R2_BUCKET.puts.length);

  // 2) 再次上报同 message+filename → count 自增到 2
  const req2 = new Request('https://x/api/err', {
    method: 'POST',
    body: JSON.stringify({ message: 'probe-327', filename: 'app.js', build_id: 'b1' }),
  });
  await errReport(req2, env, ctx);
  const rec2 = JSON.parse(env.SUBSCRIBE_KV.store[kvKey]);
  console.log('R2_COUNT=' + rec2.count);

  // 3) 限流: 同 IP 60/min（构造 61 次后第 61 次 429）
  let lastStatus = 204;
  for (let i = 0; i < 65; i++) {
    const rq = new Request('https://x/api/err', { method: 'POST', body: JSON.stringify({message:'m'+i, filename:'f'+i, build_id:'b1'}) });
    const rr = await errReport(rq, env, ctx);
    lastStatus = rr.status;
  }
  console.log('R3_LAST_STATUS=' + lastStatus);

  // 4) GET /api/err/stats 鉴权: 无 X-Admin-Pwd 无 Authorization → 401
  const reqStatsNoAuth = new Request('https://x/api/err/stats', { method: 'GET' });
  const rStatsNoAuth = await errReport(reqStatsNoAuth, env, ctx);
  console.log('R4_NOAUTH_STATUS=' + rStatsNoAuth.status);

  // 5) GET /api/err/stats 带 X-Admin-Pwd → 200 + errors 数组
  const reqStatsAuth = new Request('https://x/api/err/stats?limit=10', {
    method: 'GET', headers: { 'X-Admin-Pwd': 'pwd' }
  });
  const rStatsAuth = await errReport(reqStatsAuth, env, ctx);
  console.log('R5_AUTH_STATUS=' + rStatsAuth.status);
  const statsJson = await rStatsAuth.json();
  console.log('R5_TOTAL=' + statsJson.total);
  console.log('R5_TOP_COUNT=' + statsJson.errors[0].count);
  // errors 按 count 降序
  const counts = statsJson.errors.map(e => e.count);
  const sorted = [...counts].sort((a,b)=>b-a);
  console.log('R5_SORTED=' + (JSON.stringify(counts) === JSON.stringify(sorted) ? 'YES' : 'NO'));

  // 6) GET /api/err/stats 错误 X-Admin-Pwd → 401
  const reqStatsBad = new Request('https://x/api/err/stats', { method: 'GET', headers: { 'X-Admin-Pwd': 'wrong' } });
  const rStatsBad = await errReport(reqStatsBad, env, ctx);
  console.log('R6_BADPWD_STATUS=' + rStatsBad.status);

  // 7) POST body 非 JSON → 204 不崩
  const reqBad = new Request('https://x/api/err', { method: 'POST', body: 'not-json{{' });
  const rBad = await errReport(reqBad, env, ctx);
  console.log('R7_BADJSON_STATUS=' + rBad.status);
})();
"""

NODE_HARNESS_V3 = r"""
// V3: 测试 inline-init.js BUILD_ID 收敛 + 采样 + 去重逻辑（mock DOM + fetch + Math.random + Date）
// inline-init.js 是 IIFE 包裹, 用 new Function 注入 mock globals 执行;
//   Date.now() mock 成递增值(每次+6000), 让 _idleEnough (需>=5000ms) 第二次调用通过;
//   Math.random 不在 finally 还原(listener 触发时仍需 mock 值生效)。
const fs = require('fs');
const code = fs.readFileSync(process.env.INLINE_INIT_PATH, 'utf8');

function makeEnv(opts) {
  const calls = { reload: 0, fetches: [], beacon: null };
  const ss = { _d: {}, tabId: 't1', getItem(k){return this._d[k]||null;}, setItem(k,v){this._d[k]=String(v);}, removeItem(k){delete this._d[k];} };
  const ls = { _d: {}, getItem(k){return this._d[k]||null;}, setItem(k,v){this._d[k]=String(v);}, removeItem(k){delete this._d[k];} };
  const meta = { content: opts.metaBid || '' };
  const document = {
    querySelector: (sel) => sel === 'meta[name="build-id"]' ? meta : null,
    addEventListener: () => {},
    readyState: 'complete',
    documentElement: { classList: { add: () => {} } },
    createElement: () => ({ src: '', parentNode: { insertBefore: () => {} } }),
    getElementsByTagName: () => [{ parentNode: { insertBefore: () => {} } }],
  };
  const listeners = {};
  const window = {
    _hmt: [],
    addEventListener: (ev, cb) => { if (!listeners[ev]) listeners[ev]=[]; listeners[ev].push(cb); },
    attachEvent: () => {},
  };
  const navigator = {
    userAgent: 'test-ua',
    sendBeacon: (url, body) => { calls.beacon = {url, body}; return true; },
  };
  const location = { pathname: '/', reload: () => { calls.reload++; } };
  const fetch = (url, init) => {
    calls.fetches.push({url, init});
    return Promise.resolve({
      status: opts.fetchStatus || 200,
      headers: { get: (h) => h === 'content-type' ? 'application/javascript' : '' },
      json: () => Promise.resolve({ build_id: opts.fetchBid || '' }),
    });
  };
  const requestIdleCallback = (cb) => { cb(); };
  const _realSetTimeout = globalThis.setTimeout.bind(globalThis);
  const setTimeout = (cb, ms) => { _realSetTimeout(cb, 0); return 0; };
  const clearTimeout = () => {};
  let _dateCalls = 0;
  const _RealDate = globalThis.Date;
  class MockDate extends _RealDate {
    static now() { _dateCalls++; return 1000 + _dateCalls * 6000; }
  }
  const _Math = globalThis.Math;
  _Math.random = () => opts.randomVal !== undefined ? opts.randomVal : 0;
  const g = {
    window, document, navigator, location, fetch, requestIdleCallback,
    setTimeout, clearTimeout, sessionStorage: ss, localStorage: ls,
    Date: MockDate, JSON: globalThis.JSON, Math: _Math,
    TextEncoder: globalThis.TextEncoder, Promise: globalThis.Promise,
    console, Error: globalThis.Error, parseInt: globalThis.parseInt, String: globalThis.String,
  };
  g.self = g; g.globalThis = g;
  const fn = new Function(...Object.keys(g), code);
  fn(...Object.values(g));
  return { calls, listeners, g };
}

(async () => {
  const e1 = makeEnv({ metaBid: 'v1', fetchBid: 'v1', fetchStatus: 200 });
  await new Promise(r => setTimeout(r, 50));
  console.log('T1_RELOAD=' + e1.calls.reload);
  const e2 = makeEnv({ metaBid: 'v1', fetchBid: 'v2', fetchStatus: 200 });
  await new Promise(r => setTimeout(r, 50));
  console.log('T2_RELOAD=' + e2.calls.reload);
  const e3 = makeEnv({ metaBid: 'v1', fetchBid: 'v2', fetchStatus: 404 });
  await new Promise(r => setTimeout(r, 50));
  console.log('T3_RELOAD=' + e3.calls.reload);
  const e4 = makeEnv({ metaBid: 'v1', fetchBid: 'v1', randomVal: 0.5 });
  if (e4.listeners['error']) { e4.listeners['error'].forEach(cb => cb('test-err', 'app.js', 1, 1, {stack:'s'})); }
  console.log('T4_BEACON=' + (e4.calls.beacon ? 'SENT' : 'NOT_SENT'));
  const e5 = makeEnv({ metaBid: 'v1', fetchBid: 'v1', randomVal: 0 });
  if (e5.listeners['error']) { e5.listeners['error'].forEach(cb => cb('test-err-beacon', 'app.js', 1, 1, {stack:'s'})); }
  console.log('T5_BEACON=' + (e5.calls.beacon ? 'SENT' : 'NOT_SENT'));
  if (e5.calls.beacon) {
    const body = JSON.parse(e5.calls.beacon.body);
    console.log('T5_BEACON_MSG=' + body.message);
    console.log('T5_BEACON_BID=' + body.build_id);
  }
  const e6 = makeEnv({ metaBid: 'v1', fetchBid: 'v1', randomVal: 0 });
  let bc6 = 0;
  e6.g.navigator.sendBeacon = () => { bc6++; return true; };
  if (e6.listeners['error']) {
    for (let i = 0; i < 6; i++) { e6.listeners['error'].forEach(cb => cb('dup-msg', 'app.js', 1, 1, {stack:'s'})); }
  }
  console.log('T6_BEACON_COUNT=' + bc6);
  const e7 = makeEnv({ metaBid: 'v1', fetchBid: 'v1', randomVal: 0 });
  let bc7 = 0;
  e7.g.navigator.sendBeacon = () => { bc7++; return true; };
  if (e7.listeners['error']) {
    for (let i = 0; i < 6; i++) { e7.listeners['error'].forEach(cb => cb('distinct-msg-' + i, 'app.js', 1, 1, {stack:'s'})); }
  }
  console.log('T7_BEACON_COUNT=' + bc7);
})().catch(e => { console.error('HARNESS_ERR:', e && e.stack || e); process.exit(1); });
"""


@pytest.mark.skipif(not _node_available(), reason="node 不可用")
def test_v2_worker_err_report_js_logic():
    """V2: err_report.js POST /api/err KV incr + R2 样本 + 限流 + stats 鉴权。"""
    proc = subprocess.run(
        [NODE_BIN, "-e", NODE_HARNESS_V2],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "ERR_REPORT_PATH": str(WORKER / "err_report.js")},
        check=False,
    )
    out = proc.stdout
    assert proc.returncode == 0, f"node harness 失败:\nstdout={out}\nstderr={proc.stderr}"
    assert "R1_STATUS=204" in out
    assert "R1_KV_KEY=YES" in out
    assert "R1_COUNT=1" in out
    assert "R1_R2_PUTS=1" in out
    assert "R2_COUNT=2" in out  # 第二次上报同源 → count 自增
    assert "R3_LAST_STATUS=429" in out  # 限流 60/min 触发
    assert "R4_NOAUTH_STATUS=401" in out
    assert "R5_AUTH_STATUS=200" in out
    assert "R5_SORTED=YES" in out  # errors 按 count 降序
    assert "R6_BADPWD_STATUS=401" in out
    assert "R7_BADJSON_STATUS=204" in out


@pytest.mark.skipif(not _node_available(), reason="node 不可用")
def test_v3_inline_init_build_id_and_sampling_js_logic():
    """V3: inline-init.js BUILD_ID 收敛 + 1% 采样 + 单 tab 去重上限 5。"""
    proc = subprocess.run(
        [NODE_BIN, "-e", NODE_HARNESS_V3],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "INLINE_INIT_PATH": str(SS / "inline-init.js")},
        check=False,
    )
    out = proc.stdout
    assert proc.returncode == 0, f"node harness 失败:\nstdout={out}\nstderr={proc.stderr}"
    assert "T1_RELOAD=0" in out  # 一致不 reload
    assert "T2_RELOAD=1" in out  # 不一致+探活200 → reload
    assert "T3_RELOAD=0" in out  # 不一致+探活404 → 不 reload（防白屏）
    assert "T4_BEACON=NOT_SENT" in out  # 采样未通过不上报
    assert "T5_BEACON=SENT" in out  # 采样通过上报
    assert "T5_BEACON_MSG=test-err-beacon" in out
    assert "T5_BEACON_BID=v1" in out  # build_id 从 meta 读取
    assert "T6_BEACON_COUNT=1" in out  # 同源去重: 6 次同 message 只发 1 次
    assert "T7_BEACON_COUNT=6" in out  # 不同源各发 1 次: 6 条不同错误全发
