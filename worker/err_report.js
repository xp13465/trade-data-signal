// #327 前端错误上报 handler（2026-10-31, 纯新增）。
//
// 路由（在 headers.js 通用 /api/* 兜底前判）:
//   POST /api/err        —— 前端 sendBeacon 上报错误样本（1% 采样, 见 inline-init.js）
//                          单 IP 限流 60/min, 解析 body → KV 计数 + R2 样本（保留最近一份明细）
//   GET  /api/err/stats  —— 管理员查询当日 top N 错误（复用 auth.js getSessionUser 鉴权）
//
// 存储（§22 单一事实源 = SUBSCRIBE_KV, R2 留存明细样本）:
//   KV key  fe-err:<build_id>:<md5(message+filename)>  value=JSON{message,filename,lineno,colno,
//          stack,ua,pathname,build_id,tab,first_ts,last_ts,count}
//     · count 用 read-modify-write 自增（站点 1% 采样量级小, 并发覆盖概率低; 上线后观察是否需
//       切到原子计数）。KV 写整对象, 读取时 list prefix 即可拿 top N。
//   R2 key  fe-err-samples/<YYYYMMDD>/<uuid>.json  value=完整单条样本（含 ts）
//     · 每条上报写一份（1% 采样后量级低, 单 PUT 计费可控; 提供完整明细便于排障）。
//
// 字段（前端 inline-init.js 上报口径, 隐私: 不采 cookie/输入/查询参数）:
//   message / filename / lineno / colno / stack（截断 2000）/ build_id / ua / pathname / tab / ts
//
// 红线: 纯新增不改现有 /api/* 行为（§23.7）; 不引第三方（不 Sentry）; POST 返回 204 不阻断页面;
//      任何异常 try/catch 静默（防上报本身循环报错）; GET stats 走鉴权（泄漏 build_id/UA 风险）。

import { getSessionUser, jsonResponse } from './auth.js';

const KV_PREFIX = 'fe-err:';
const R2_SAMPLE_PREFIX = 'fe-err-samples/';
const RATE_LIMIT_PER_MIN = 60;          // 单 IP 60/min（1% 采样下远够, 防恶意刷）
const RATE_WINDOW_SEC = 60;
const RATE_KEY_PREFIX = 'fe-err:rate:';
const STACK_MAX = 2000;
const SAMPLES_RETAIN_DAYS = 14;         // R2 样本保留 14 天（lifecycle 由人工/后续任务清理）

// SHA-256 取前 16 hex（与 auth.js getIpHash 同口径, 脱敏）
async function shaHex(data, len = 16) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(data));
  const bytes = new Uint8Array(buf);
  let hex = '';
  for (const b of bytes) hex += b.toString(16).padStart(2, '0');
  return hex.slice(0, len);
}

function getClientIp(request) {
  return (request.headers.get('CF-Connecting-IP') || '')
    || ((request.headers.get('x-forwarded-for') || '').split(',')[0].trim())
    || 'unknown';
}

function todayUTCDate() {
  return new Date().toISOString().slice(0, 10).replace(/-/g, '');
}

function truncate(s, max) {
  if (typeof s !== 'string') return '';
  return s.length > max ? s.slice(0, max) : s;
}

// 单 IP 限流: 同 IP 60s 内 ≤ RATE_LIMIT_PER_MIN 条。KV key fe-err:rate:<ipHash>:<windowBucket>
// 容忍 KV 最终一致性（不依赖强一致）: get 失败/未命中不阻断, 超阈值返回 429。
async function checkRateLimit(env, ipHash) {
  const bucket = Math.floor(Date.now() / (RATE_WINDOW_SEC * 1000));
  const key = `${RATE_KEY_PREFIX}${ipHash}:${bucket}`;
  try {
    const raw = await env.SUBSCRIBE_KV.get(key);
    const cur = raw ? parseInt(raw, 10) || 0 : 0;
    if (cur >= RATE_LIMIT_PER_MIN) return false;
    await env.SUBSCRIBE_KV.put(key, String(cur + 1), { expirationTtl: RATE_WINDOW_SEC * 2 });
    return true;
  } catch {
    return true;  // KV 异常不阻断上报（fail-open, 错误样本优先）
  }
}

// POST /api/err: 解析 body, KV incr + R2 样本
async function reportError(request, env, ctx) {
  if (request.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405 });
  }
  // CORS preflight 由 headers.js 统一处理; 这里只处理 POST
  // body 可能是 text/plain（sendBeacon 默认）或 application/json, 兼容两种
  let payload = null;
  try {
    const text = await request.text();
    payload = JSON.parse(text);
  } catch {
    return new Response(null, { status: 204 });  // 解析失败静默 204（不阻断页面）
  }
  if (!payload || typeof payload !== 'object') {
    return new Response(null, { status: 204 });
  }

  const message = truncate(String(payload.message || ''), 500);
  const filename = truncate(String(payload.filename || ''), 500);
  if (!message && !filename) {
    return new Response(null, { status: 204 });
  }
  const md5Input = message + '|' + filename;
  const msgHash = await shaHex(md5Input, 16);
  const buildId = truncate(String(payload.build_id || ''), 64);
  const kvKey = `${KV_PREFIX}${buildId}:${msgHash}`;

  // 限流（按 IP）
  const ip = getClientIp(request);
  const ipHash = await shaHex(ip, 16);
  const allowed = await checkRateLimit(env, ipHash);
  if (!allowed) {
    return new Response(null, { status: 429 });
  }

  // 读旧值 read-modify-write（站点量级小, 并发覆盖概率低）
  const now = Date.now();
  const nowIso = new Date(now).toISOString();
  let record = null;
  try {
    const raw = await env.SUBSCRIBE_KV.get(kvKey);
    if (raw) record = JSON.parse(raw);
  } catch {}
  if (!record || typeof record !== 'object') {
    record = {
      message, filename,
      lineno: payload.lineno || 0,
      colno: payload.colno || 0,
      stack: truncate(payload.stack || '', STACK_MAX),
      ua: truncate(payload.ua || '', 300),
      pathname: truncate(payload.pathname || '', 200),
      build_id: buildId,
      tab: truncate(payload.tab || '', 64),
      first_ts: nowIso,
      last_ts: nowIso,
      count: 0,
    };
  }
  record.count = (record.count || 0) + 1;
  record.last_ts = nowIso;
  // 字段补齐（旧记录可能缺字段, 不丢计数）
  if (!record.build_id) record.build_id = buildId;
  if (!record.tab) record.tab = truncate(payload.tab || '', 64);
  if (!record.ua) record.ua = truncate(payload.ua || '', 300);

  try {
    await env.SUBSCRIBE_KV.put(kvKey, JSON.stringify(record));
  } catch {
    return new Response(null, { status: 204 });  // 写失败静默（不阻断页面）
  }

  // R2 样本（每条一份, 含完整字段 + ts, 便于排障）
  const sample = {
    message, filename,
    lineno: payload.lineno || 0,
    colno: payload.colno || 0,
    stack: truncate(payload.stack || '', STACK_MAX),
    ua: truncate(payload.ua || '', 300),
    pathname: truncate(payload.pathname || '', 200),
    build_id: buildId,
    tab: truncate(payload.tab || '', 64),
    ts: nowIso,
  };
  const dateStr = todayUTCDate();
  const sampleKey = `${R2_SAMPLE_PREFIX}${dateStr}/${crypto.randomUUID()}.json`;
  try {
    if (env.R2_BUCKET) {
      ctx.waitUntil(env.R2_BUCKET.put(sampleKey, JSON.stringify(sample), {
        httpMetadata: { contentType: 'application/json' },
      }));
    }
  } catch {
    // R2 写失败不阻断（KV 已记计数, 上报主链路已完成）
  }

  return new Response(null, { status: 204 });
}

// GET /api/err/stats: 管理员查询 top N 错误（按 count 降序）
//   query: ?days=1（默认 1, 当日）&limit=50（默认 50, 最大 200）
//   返回 { errors: [{message, filename, lineno, build_id, count, first_ts, last_ts, ...}], generated_at }
async function getErrorStats(request, env, url) {
  if (request.method !== 'GET') {
    return new Response('Method Not Allowed', { status: 405 });
  }
  // 鉴权（双路径, 任一通过即可）:
  //   ① X-Admin-Pwd header 对比 env.FEEDBACK_ADMIN_PASSWORD（复用留言管理端 secret,
  //      供 schedule_monitor 云上脚本拉取 stats 用, 无需用户登录态; 同 auth.js adminListFeedback 模式）
  //   ② auth.js getSessionUser（Bearer token / session cookie, 供管理员浏览器查看用）
  const adminPwd = request.headers.get('X-Admin-Pwd') || '';
  const expectedPwd = env.FEEDBACK_ADMIN_PASSWORD || '';
  let authed = false;
  if (expectedPwd && adminPwd && adminPwd === expectedPwd) {
    authed = true;
  }
  if (!authed) {
    const session = await getSessionUser(request, env);
    if (session) authed = true;
  }
  if (!authed) {
    return jsonResponse({ detail: '未鉴权（需 X-Admin-Pwd 或登录态）' }, 401, { request });
  }
  const days = Math.max(1, Math.min(30, parseInt(url.searchParams.get('days') || '1', 10) || 1));
  const limit = Math.max(1, Math.min(200, parseInt(url.searchParams.get('limit') || '50', 10) || 50));

  // list KV fe-err: 前缀, 聚合（KV list 单次最多 1000 keys, 翻页）
  const errors = [];
  let cursor;
  try {
    do {
      const listOpts = { prefix: KV_PREFIX, limit: 1000 };
      if (cursor) listOpts.cursor = cursor;
      const result = await env.SUBSCRIBE_KV.list(listOpts);
      const keys = result.keys || [];
      const gets = keys.map((k) => env.SUBSCRIBE_KV.get(k.name).catch(() => null));
      const values = await Promise.all(gets);
      for (const raw of values) {
        if (!raw) continue;
        try {
          const rec = JSON.parse(raw);
          if (rec && typeof rec === 'object') {
            errors.push({
              message: rec.message || '',
              filename: rec.filename || '',
              lineno: rec.lineno || 0,
              build_id: rec.build_id || '',
              tab: rec.tab || '',
              count: rec.count || 1,
              first_ts: rec.first_ts || '',
              last_ts: rec.last_ts || '',
            });
          }
        } catch {}
      }
      cursor = result.list_complete ? null : result.cursor;
      if (errors.length >= limit * 4) break;  // 取够候选后停（top N 排序在内存）
    } while (cursor);
  } catch (e) {
    return jsonResponse({ detail: 'KV list 失败: ' + (e && e.message) }, 500, { request });
  }

  errors.sort((a, b) => (b.count || 0) - (a.count || 0));
  const top = errors.slice(0, limit);
  return jsonResponse({
    errors: top,
    total: errors.length,
    generated_at: new Date().toISOString(),
  }, 200, { request });
}

export default async function errReportHandler(request, env, ctx) {
  // CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: {
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type, Authorization',
      'Access-Control-Max-Age': '86400',
      'Access-Control-Allow-Origin': '*',
    }});
  }
  const url = new URL(request.url);
  if (url.pathname === '/api/err' && request.method === 'POST') {
    return reportError(request, env, ctx);
  }
  if (url.pathname === '/api/err/stats' && request.method === 'GET') {
    return getErrorStats(request, env, url);
  }
  return jsonResponse({ detail: 'Not Found' }, 404, { request });
}
