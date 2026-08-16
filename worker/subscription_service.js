// CF Workers AI 每日速递订阅服务（2026-08-17 新增，B/C 级新功能）。
// 为 UUMit 平台「AI 每日速递订阅推送服务」提供订阅者管理端点。
//
// 端点（4 个，路径前缀 /api/subscribe/*，需在 headers.js 中先于通用 /api/* 分发判）：
//   POST /api/subscribe/register    —— 管理员鉴权，body {email 或 webhook_url}，生成 sub_ 前缀订阅 key，
//                                      写 KV(sub:<key> = {email|webhook_url, created_at, status:"active"})，
//                                      返回 key（只打印一次，不落盘明文）。
//   POST /api/subscribe/unregister  —— 订阅者自鉴权（sub_key），置 status:"revoked"。
//   GET  /api/subscribe/status?key=<sub_key> —— 订阅者自鉴权，查 status(active/revoked)。
//   GET  /api/subscribe/recipients  —— 管理员鉴权，返回所有 active 订阅者列表（供本地 brief_push.py 拉取）。
//
// 鉴权模型（复用 dataQuery.js 的 api_key 体系 + 本服务子订阅 key 两级）：
//   - 管理员端点（register/recipients）：Authorization: Bearer <admin_key> 或 X-API-Key: <admin_key>，
//     key 只存 SHA-256 hash 于 KV(api_key:<hash>)，与 dataQuery.js / scripts/api_key_mgmt.py 同一 key 池。
//   - 订阅者端点（status/unregister）：?key=<sub_key> 或 X-Sub-Key 头，比对 KV 里 sub:<key> 是否存在于撤销。
//   - 错误统一格式 {error:{code,message}}，与 dataQuery.js 一致。
//
// 存储（SUBSCRIBE_KV namespace）：
//   sub:<key>                = {"email"|"webhook_url", "created_at", "status":"active|revoked", "type":"email|webhook"}
//   api_key:<hash>           = "1"（管理员 key，复用 api_key_mgmt.py）
//   KV list(prefix:"sub:") 枚举全部订阅，按 status 过滤出 active 列表。
//
// 合规（§23.7 只增不改）：本服务纯新增，不动既有 /api/subscribe（subscribe.js 信号订阅）与
//   daily_brief 公开展示/生成逻辑。推送/订阅是付费服务，本期不做自动扣费（状态手动管理，
//   上架后由 UUMit 平台计费回调对接，本地 brief_push.py 留计费 hook 注释）。
// 数据一致性（§22）：recipients 只回订阅者联系方式，推送内容由 brief_push.py 从 daily_brief.json
//   逐位读取，不在此加工，保证与公开免费展示逐位一致。

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, Authorization, X-API-Key, X-Sub-Key',
  'Access-Control-Max-Age': '86400',
};

function jsonError(code, message, status) {
  return new Response(JSON.stringify({ error: { code, message } }), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS_HEADERS },
  });
}

function jsonOk(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', ...CORS_HEADERS },
  });
}

// SHA-256 摘要（Web Crypto），管理员 key 只存 hash
async function hashKey(key) {
  const data = new TextEncoder().encode('api-key:' + key);
  const digest = await crypto.subtle.digest('SHA-256', data);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

// 管理员鉴权：取 Authorization: Bearer 或 X-API-Key，比对 KV api_key:<hash>
async function checkAdmin(request, env) {
  const auth = request.headers.get('Authorization') || '';
  let key = null;
  if (auth.startsWith('Bearer ')) {
    const k = auth.slice(7).trim();
    if (k) key = k;
  }
  if (!key) key = (request.headers.get('X-API-Key') || '').trim() || null;
  if (!key) {
    return { ok: false, resp: jsonError('unauthorized', '缺少管理员 API key（Authorization: Bearer <key> 或 X-API-Key: <key>）', 401) };
  }
  const hash = await hashKey(key);
  const stored = await env.SUBSCRIBE_KV.get(`api_key:${hash}`);
  if (!stored) {
    return { ok: false, resp: jsonError('unauthorized', '管理员 API key 无效', 401) };
  }
  return { ok: true, key };
}

// 订阅者 key 自鉴权：比对 KV sub:<key>
async function checkSubscriberKey(env, key) {
  if (!key) return { ok: false, resp: jsonError('unauthorized', '缺少订阅 key（?key=<sub_key> 或 X-Sub-Key 头）', 401) };
  const raw = await env.SUBSCRIBE_KV.get(`sub:${key}`);
  if (!raw) {
    return { ok: false, resp: jsonError('unauthorized', '订阅 key 无效', 401) };
  }
  let sub;
  try { sub = JSON.parse(raw); } catch (e) { return { ok: false, resp: jsonError('unauthorized', '订阅数据异常', 500) }; }
  return { ok: true, sub, key };
}

// 生成订阅 key：sub_ + 时间戳 + 随机 8 字节 hex
function genSubKey() {
  const rand = [...new Uint8Array(8)].map(b => b.toString(16).padStart(2, '0')).join('');
  return `sub_${Date.now()}_${rand}`;
}

// POST /api/subscribe/register
async function handleRegister(request, env) {
  const auth = await checkAdmin(request, env);
  if (!auth.ok) return auth.resp;

  let body;
  try { body = await request.json(); } catch (e) {
    return jsonError('bad_request', '请求体非合法 JSON', 400);
  }
  const email = (body.email || '').trim();
  const webhook_url = (body.webhook_url || '').trim();
  if (!email && !webhook_url) {
    return jsonError('bad_request', 'email 和 webhook_url 至少填一个', 400);
  }
  if (email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
    return jsonError('bad_request', 'email 格式无效', 400);
  }
  if (webhook_url && !/^https?:\/\//.test(webhook_url)) {
    return jsonError('bad_request', 'webhook_url 必须是 http(s) URL', 400);
  }

  const subKey = genSubKey();
  const sub = {
    type: email ? 'email' : 'webhook',
    ...(email ? { email } : { webhook_url }),
    created_at: new Date().toISOString(),
    status: 'active',
  };
  await env.SUBSCRIBE_KV.put(`sub:${subKey}`, JSON.stringify(sub));
  // key 只在此响应打印一次，前端/订阅者务必立即保存
  return jsonOk({ ok: true, key: subKey, type: sub.type, status: 'active' }, 201);
}

// POST /api/subscribe/unregister —— 订阅者自鉴权（sub_key），置 revoked
async function handleUnregister(request, env) {
  let subKey = (request.headers.get('X-Sub-Key') || '').trim() || null;
  if (!subKey) {
    try {
      const body = await request.json();
      subKey = (body.key || '').trim() || null;
    } catch (e) { /* 无 body 也允许，走 header */ }
  }
  const auth = await checkSubscriberKey(env, subKey);
  if (!auth.ok) return auth.resp;
  auth.sub.status = 'revoked';
  await env.SUBSCRIBE_KV.put(`sub:${auth.key}`, JSON.stringify(auth.sub));
  return jsonOk({ ok: true, key: auth.key, status: 'revoked' });
}

// GET /api/subscribe/status?key=<sub_key> —— 订阅者自鉴权
async function handleStatus(request, env, url) {
  const qKey = (url.searchParams.get('key') || '').trim();
  let subKey = qKey || (request.headers.get('X-Sub-Key') || '').trim() || null;
  const auth = await checkSubscriberKey(env, subKey);
  if (!auth.ok) return auth.resp;
  return jsonOk({
    key: auth.key,
    status: auth.sub.status,
    type: auth.sub.type,
    created_at: auth.sub.created_at,
  });
}

// GET /api/subscribe/recipients —— 管理员鉴权，返回所有 active 订阅者
async function handleRecipients(request, env) {
  const auth = await checkAdmin(request, env);
  if (!auth.ok) return auth.resp;

  const list = await env.SUBSCRIBE_KV.list({ prefix: 'sub:' });
  const recipients = [];
  for (const k of list.keys) {
    const subKey = k.name.slice('sub:'.length);
    let sub;
    try { sub = JSON.parse(await env.SUBSCRIBE_KV.get(k.name)); } catch (e) { continue; }
    if (!sub || sub.status !== 'active') continue;
    recipients.push({
      key: subKey,
      type: sub.type,
      ...(sub.email ? { email: sub.email } : { webhook_url: sub.webhook_url }),
      created_at: sub.created_at,
    });
  }
  return jsonOk({ ok: true, count: recipients.length, recipients });
}

// 入口：/api/subscribe/register|unregister|status|recipients
export default async function subscriptionServiceHandler(request, env) {
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  const url = new URL(request.url);
  const pathname = url.pathname;

  if (request.method === 'POST' && pathname === '/api/subscribe/register') {
    return handleRegister(request, env);
  }
  if (request.method === 'POST' && pathname === '/api/subscribe/unregister') {
    return handleUnregister(request, env);
  }
  if (request.method === 'GET' && pathname === '/api/subscribe/status') {
    return handleStatus(request, env, url);
  }
  if (request.method === 'GET' && pathname === '/api/subscribe/recipients') {
    return handleRecipients(request, env);
  }
  // 未匹配的本服务路由，交回 headers.js 通用 /api/* 分发（subscribe.js 兜底）
  return jsonError('not_found', '未知订阅服务端点', 404);
}
