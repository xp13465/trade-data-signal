// CF Workers 信号订阅接口（C 方案，2026-07-24）。
// run_worker_first=true 时 Worker 先跑，拦截 /api/* 路由到此 handler。
// 生产环境无 FastAPI，订阅 CRUD 走 KV；本地开发走 uvicorn main.py 读写 config/subscriptions.json。
// sync_subscriptions_from_cf.py 跑前拉 /api/subscribe/export 回流本地 config/subscriptions.json，
// 供 check_signals.py 推送邮件/Telegram 使用。
//
// 认证：单用户密码（A1 方案），X-Sub-Pwd header 对比 Workers secret SUBSCRIBE_PASSWORD。
// 存储：KV 单 key subscriptions:v1，整存整取 {subscriptions: [...]}。
// CORS：Access-Control-Allow-Origin: *（静态站跨域，dev 本地 uvicorn 8000 也可调生产）。

const SUBSCRIBE_KV_KEY = 'subscriptions:v1';
const VALID_SIGNAL_TYPES = new Set(['buy', 'buy_aux', 'buy_special', 'buy_backup', 'sell', 'sell_stop_loss']);

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, DELETE, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type, X-Sub-Pwd',
  'Access-Control-Max-Age': '86400',
};

function jsonResponse(body, status = 200, extraHeaders = {}) {
  const headers = { 'Content-Type': 'application/json; charset=utf-8', ...CORS_HEADERS, ...extraHeaders };
  return new Response(JSON.stringify(body), { status, headers });
}

function checkPwd(request, env) {
  const provided = request.headers.get('X-Sub-Pwd') || '';
  const expected = env.SUBSCRIBE_PASSWORD || '';
  if (!expected) {
    // 未配置密码 secret，拒绝（避免无认证裸奔）
    return { ok: false, resp: jsonResponse({ detail: '订阅接口未配置密码（SUBSCRIBE_PASSWORD secret 未设置）' }, 503) };
  }
  if (!provided || provided !== expected) {
    return { ok: false, resp: jsonResponse({ detail: '密码错误' }, 401) };
  }
  return { ok: true };
}

async function loadSubsFromKV(env) {
  const raw = await env.SUBSCRIBE_KV.get(SUBSCRIBE_KV_KEY);
  if (!raw) return { subscriptions: [] };
  try {
    const data = JSON.parse(raw);
    if (!data || !Array.isArray(data.subscriptions)) return { subscriptions: [] };
    return data;
  } catch {
    return { subscriptions: [] };
  }
}

async function saveSubsToKV(env, data) {
  await env.SUBSCRIBE_KV.put(SUBSCRIBE_KV_KEY, JSON.stringify(data));
}

function maskEmail(email) {
  if (!email || !email.includes('@')) return '';
  const [local, domain] = email.split('@', 2);
  if (local.length <= 1) return `${local}***@${domain}`;
  return `${local[0]}***@${domain}`;
}

function maskChatId(chatId) {
  if (!chatId) return '';
  if (chatId.length <= 4) return '****';
  return '****' + chatId.slice(-4);
}

function maskSubscription(s) {
  return {
    id: s.id || '',
    name: s.name || '',
    email_masked: maskEmail(s.email || ''),
    telegram_chat_id_masked: maskChatId(s.telegram_chat_id || ''),
    has_email: Boolean(s.email),
    has_telegram: Boolean(s.telegram_chat_id),
    targets: s.targets || [],
    signals: s.signals || [],
    enabled: s.enabled !== false,
    created_at: s.created_at || '',
  };
}

function validateSubscription(body) {
  const id = (body.id || '').trim();
  const name = (body.name || '').trim();
  const email = (body.email || '').trim();
  const telegram_chat_id = (body.telegram_chat_id || '').trim();
  const targets = Array.isArray(body.targets) ? body.targets.filter(t => t) : [];
  const signals = Array.isArray(body.signals) ? body.signals : [];
  const enabled = body.enabled !== false;
  if (!targets.length) return { ok: false, resp: jsonResponse({ detail: 'targets 不能为空（至少订阅一个标的）' }, 400) };
  if (!email && !telegram_chat_id) return { ok: false, resp: jsonResponse({ detail: 'email 和 telegram_chat_id 至少填一个' }, 400) };
  for (const sig of signals) {
    if (!VALID_SIGNAL_TYPES.has(sig)) {
      return { ok: false, resp: jsonResponse({ detail: `无效的信号类型: ${sig}，可选 ${[...VALID_SIGNAL_TYPES].sort().join(',')}` }, 400) };
    }
  }
  return { ok: true, data: { id, name, email, telegram_chat_id, targets, signals, enabled } };
}

export default async function subscribeHandler(request, env) {
  // CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const url = new URL(request.url);
  const pathname = url.pathname;

  // 路由分发
  // GET /api/subscribe/export 必须在 /api/subscribe 前判（否则被 GET /api/subscribe 吞）
  if (request.method === 'GET' && pathname === '/api/subscribe/export') {
    const auth = checkPwd(request, env);
    if (!auth.ok) return auth.resp;
    const data = await loadSubsFromKV(env);
    return jsonResponse(data);  // 不脱敏，供本地回流
  }

  if (request.method === 'GET' && pathname === '/api/subscribe') {
    const auth = checkPwd(request, env);
    if (!auth.ok) return auth.resp;
    const data = await loadSubsFromKV(env);
    return jsonResponse({ subscriptions: (data.subscriptions || []).map(maskSubscription) });
  }

  if (request.method === 'POST' && pathname === '/api/subscribe') {
    const auth = checkPwd(request, env);
    if (!auth.ok) return auth.resp;
    let body;
    try { body = await request.json(); } catch { return jsonResponse({ detail: '请求体非合法 JSON' }, 400); }
    const v = validateSubscription(body);
    if (!v.ok) return v.resp;
    const data = await loadSubsFromKV(env);
    const subs = data.subscriptions || [];
    let subId, action;
    if (v.data.id) {
      const idx = subs.findIndex(s => s.id === v.data.id);
      if (idx === -1) return jsonResponse({ detail: `订阅 ${v.data.id} 不存在` }, 404);
      subs[idx] = { ...subs[idx], ...v.data };
      subId = v.data.id;
      action = 'updated';
    } else {
      subId = `sub_${Date.now()}`;
      subs.push({
        id: subId,
        name: v.data.name || `订阅-${subs.length + 1}`,
        email: v.data.email,
        telegram_chat_id: v.data.telegram_chat_id,
        targets: v.data.targets,
        signals: v.data.signals,
        enabled: v.data.enabled,
        created_at: new Date().toISOString(),
      });
      action = 'created';
    }
    data.subscriptions = subs;
    await saveSubsToKV(env, data);
    return jsonResponse({ ok: true, id: subId, action });
  }

  if (request.method === 'DELETE' && pathname.startsWith('/api/subscribe/')) {
    const auth = checkPwd(request, env);
    if (!auth.ok) return auth.resp;
    const subId = decodeURIComponent(pathname.slice('/api/subscribe/'.length));
    if (!subId) return jsonResponse({ detail: '缺少订阅 id' }, 400);
    const data = await loadSubsFromKV(env);
    const subs = data.subscriptions || [];
    const newSubs = subs.filter(s => s.id !== subId);
    if (newSubs.length === subs.length) return jsonResponse({ detail: `订阅 ${subId} 不存在` }, 404);
    data.subscriptions = newSubs;
    await saveSubsToKV(env, data);
    return jsonResponse({ ok: true, deleted: subId });
  }

  // 未匹配的 /api/* 路由
  return jsonResponse({ detail: 'Not Found' }, 404);
}
