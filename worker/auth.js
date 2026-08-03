// CF Workers OAuth 接口（2026-08-03）。
// 移植自 app/auth.py（FastAPI），生产 ss.fx8.store/api/auth/* 走此 Worker 不回源。
// 本地开发走 uvicorn app/auth.py（FastAPI + sentiment.db users 表），生产走此 Worker。
//
// 路由（6 个，和 FastAPI 一致）：
// - GET  /api/auth/login/gitee    生成 state（KV TTL 5min）+ 307 跳 Gitee 授权页 + Set-Cookie oauth_state
// - GET  /api/auth/callback/gitee 校验 state（KV + cookie 双校验）+ 换 token + 拉用户 + upsert KV users + 发 session cookie + 307 回 /
// - GET  /api/auth/me             返回 {logged_in, user, privileges}
// - POST /api/auth/logout         清 session cookie
// - GET  /api/auth/login/github   占位 501
// - GET  /api/auth/login/google   占位 501
//
// session：Web Crypto HMAC-SHA256 签名 cookie，格式 base64url(payload).base64url(hmac)
//   payload={exp, provider, provider_uid, user_id}（字母序插入，对齐 Python sort_keys）
//   注：比 FastAPI 多存 provider_uid，因 KV 无按 user_id 查询，me 需 provider+provider_uid 直取 user record
// users：KV key=user:<provider>:<provider_uid>，value=JSON{id,provider,provider_uid,name,avatar,email,created_at,last_login_at}
//   id 用 crypto.randomUUID()（KV 无自增）；登录时 upsert：存在更新 last_login_at，不存在新建
// state：KV key=oauth_state:<state>，value=1，TTL 300s；callback 校验 KV 存在 + cookie 匹配（双校验防 CSRF）
//
// env 变量（wrangler secret put 配置，不进 wrangler.jsonc）：
//   GITEE_CLIENT_ID / GITEE_CLIENT_SECRET / GITEE_REDIRECT_URI（生产=https://ss.fx8.store/api/auth/callback/gitee）/ SESSION_SECRET
//   GitHub/Google 未实现，占位
// KV binding 复用 SUBSCRIBE_KV（见 wrangler.jsonc kv_namespaces）。

const SESSION_COOKIE_NAME = 'session';
const STATE_COOKIE_NAME = 'oauth_state';
const SESSION_MAX_AGE = 30 * 24 * 3600;  // 30 天
const STATE_TTL = 300;  // 5 分钟（KV expirationTtl 最小 60s）
const PRIVILEGES_LOGGED_IN = ['detailed_view'];

const CORS_HEADERS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Access-Control-Max-Age': '86400',
};

// ============ helpers ============

function jsonResponse(body, status = 200, opts = {}) {
  const h = new Headers();
  h.set('Content-Type', 'application/json; charset=utf-8');
  for (const [k, v] of Object.entries(CORS_HEADERS)) h.set(k, v);
  if (opts.cookies) {
    for (const c of opts.cookies) h.append('Set-Cookie', c);
  }
  return new Response(JSON.stringify(body), { status, headers: h });
}

function redirect307(url, cookies = []) {
  const h = new Headers();
  h.set('Location', url);
  for (const c of cookies) h.append('Set-Cookie', c);
  return new Response(null, { status: 307, headers: h });
}

function getCookies(request) {
  const header = request.headers.get('Cookie') || '';
  const cookies = {};
  for (const part of header.split(';')) {
    const idx = part.indexOf('=');
    if (idx === -1) continue;
    const k = part.slice(0, idx).trim();
    const v = part.slice(idx + 1).trim();
    if (k) cookies[k] = v;
  }
  return cookies;
}

function makeCookie(name, value, maxAge) {
  const parts = [`${name}=${value}`, 'Path=/', 'HttpOnly', 'Secure', 'SameSite=Lax'];
  if (maxAge !== undefined) parts.push(`Max-Age=${maxAge}`);
  return parts.join('; ');
}

function clearCookie(name) {
  return `${name}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0`;
}

// base64url 编码/解码（和 FastAPI urlsafe_b64encode 一致，去 padding）
function b64url(bytes) {
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function b64urlStr(str) {
  return b64url(new TextEncoder().encode(str));
}

function unb64urlStr(str) {
  let s = str.replace(/-/g, '+').replace(/_/g, '/');
  const pad = (4 - (s.length % 4)) % 4;
  s += '='.repeat(pad);
  const bin = atob(s);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

// Web Crypto HMAC-SHA256 签名
async function hmacSign(secret, data) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false, ['sign']
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(data));
  return b64url(new Uint8Array(sig));
}

// Web Crypto HMAC-SHA256 验签（constant-time 由 Web Crypto 保证）
async function hmacVerify(secret, data, expectedSigB64url) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw', enc.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false, ['verify']
  );
  let s = expectedSigB64url.replace(/-/g, '+').replace(/_/g, '/');
  const pad = (4 - (s.length % 4)) % 4;
  s += '='.repeat(pad);
  const bin = atob(s);
  const sigBytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) sigBytes[i] = bin.charCodeAt(i);
  return crypto.subtle.verify('HMAC', key, sigBytes, enc.encode(data));
}

// session 签名：base64url(payload).base64url(hmac)
// payload 按字母序插入（exp, provider, provider_uid, user_id），对齐 Python sort_keys
async function signSession(payload, sessionSecret) {
  if (!sessionSecret) return null;
  const body = b64urlStr(JSON.stringify(payload));
  const sig = await hmacSign(sessionSecret, body);
  return `${body}.${sig}`;
}

async function verifySession(token, sessionSecret) {
  if (!token || !sessionSecret || !token.includes('.')) return null;
  try {
    const idx = token.lastIndexOf('.');
    const body = token.slice(0, idx);
    const sig = token.slice(idx + 1);
    const ok = await hmacVerify(sessionSecret, body, sig);
    if (!ok) return null;
    const payload = JSON.parse(unb64urlStr(body));
    if (!payload || typeof payload !== 'object') return null;
    const exp = payload.exp || 0;
    if (exp && exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}

// ============ KV helpers ============

async function upsertUser(env, provider, providerUid, name, avatar, email) {
  const key = `user:${provider}:${providerUid}`;
  const now = new Date().toISOString();
  let user = null;
  const existing = await env.SUBSCRIBE_KV.get(key);
  if (existing) {
    try {
      user = JSON.parse(existing);
      user.name = name;
      user.avatar = avatar;
      user.email = email;
      user.last_login_at = now;
    } catch {
      user = null;
    }
  }
  if (!user) {
    user = {
      id: crypto.randomUUID(),
      provider,
      provider_uid: providerUid,
      name,
      avatar,
      email,
      created_at: now,
      last_login_at: now,
    };
  }
  await env.SUBSCRIBE_KV.put(key, JSON.stringify(user));
  return user;
}

async function getUserByProviderUid(env, provider, providerUid) {
  const key = `user:${provider}:${providerUid}`;
  const raw = await env.SUBSCRIBE_KV.get(key);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

// ============ 路由 ============

async function loginGitee(request, env) {
  const clientId = env.GITEE_CLIENT_ID || '';
  const redirectUri = env.GITEE_REDIRECT_URI || '';
  if (!clientId) return jsonResponse({ detail: 'Gitee OAuth 未配置（GITEE_CLIENT_ID 环境变量为空）' }, 503);
  if (!redirectUri) return jsonResponse({ detail: 'GITEE_REDIRECT_URI 未配置' }, 503);
  const state = crypto.randomUUID();
  // state 存 KV（TTL 5min）+ cookie，回调双校验
  await env.SUBSCRIBE_KV.put(`oauth_state:${state}`, '1', { expirationTtl: STATE_TTL });
  const loginUrl = (
    'https://gitee.com/oauth/authorize'
    + `?client_id=${encodeURIComponent(clientId)}`
    + `&redirect_uri=${encodeURIComponent(redirectUri)}`
    + '&response_type=code'
    + `&state=${encodeURIComponent(state)}`
    + '&scope=user_info'
  );
  const stateCookie = makeCookie(STATE_COOKIE_NAME, state, STATE_TTL);
  return redirect307(loginUrl, [stateCookie]);
}

async function callbackGitee(request, env, url) {
  const clientId = env.GITEE_CLIENT_ID || '';
  const clientSecret = env.GITEE_CLIENT_SECRET || '';
  const redirectUri = env.GITEE_REDIRECT_URI || '';
  const sessionSecret = env.SESSION_SECRET || '';
  if (!clientId || !clientSecret || !redirectUri) {
    return jsonResponse({ detail: 'Gitee OAuth 未配置' }, 503);
  }
  const code = url.searchParams.get('code') || '';
  const state = url.searchParams.get('state') || '';
  if (!code || !state) return jsonResponse({ detail: '回调缺少 code/state 参数' }, 400);

  // state 双校验：KV 存在 + cookie 匹配（防 CSRF）
  const kvState = await env.SUBSCRIBE_KV.get(`oauth_state:${state}`);
  if (!kvState) {
    return jsonResponse({ detail: 'state 校验失败（KV 中不存在，可能已过期或重放）' }, 400);
  }
  const cookies = getCookies(request);
  const cookieState = cookies[STATE_COOKIE_NAME] || '';
  if (!cookieState || cookieState !== state) {
    return jsonResponse({ detail: 'state 校验失败（cookie 不匹配，可能跨站请求伪造）' }, 400);
  }
  // 用完即删（防重放）
  await env.SUBSCRIBE_KV.delete(`oauth_state:${state}`);

  // 换 access_token（form-urlencoded，对齐 FastAPI httpx data=）
  const tokenBody = new URLSearchParams({
    grant_type: 'authorization_code',
    code,
    client_id: clientId,
    client_secret: clientSecret,
    redirect_uri: redirectUri,
  });
  let accessToken;
  try {
    const tokResp = await fetch('https://gitee.com/oauth/token', {
      method: 'POST',
      headers: { 'Accept': 'application/json', 'Content-Type': 'application/x-www-form-urlencoded' },
      body: tokenBody.toString(),
    });
    if (tokResp.status !== 200) {
      const text = await tokResp.text();
      return jsonResponse({ detail: `换 access_token 失败: ${tokResp.status} ${text}` }, 400);
    }
    const tokJson = await tokResp.json();
    accessToken = tokJson.access_token;
  } catch (e) {
    return jsonResponse({ detail: `换 access_token 异常: ${e.message || String(e)}` }, 500);
  }
  if (!accessToken) return jsonResponse({ detail: 'Gitee 未返回 access_token' }, 400);

  // 拉用户信息
  let u;
  try {
    const userResp = await fetch(
      `https://gitee.com/api/v5/user?access_token=${encodeURIComponent(accessToken)}`,
      { headers: { 'Accept': 'application/json' } },
    );
    if (userResp.status !== 200) {
      return jsonResponse({ detail: `拉 Gitee 用户信息失败: ${userResp.status}` }, 400);
    }
    u = await userResp.json();
  } catch (e) {
    return jsonResponse({ detail: `拉用户信息异常: ${e.message || String(e)}` }, 500);
  }
  const providerUid = String(u.id || '');
  if (!providerUid) return jsonResponse({ detail: 'Gitee 用户信息缺 id 字段' }, 400);
  const name = u.name || u.login || '';
  const avatar = u.avatar_url || '';
  const email = u.email || '';

  // upsert users（KV）
  const user = await upsertUser(env, 'gitee', providerUid, name, avatar, email);

  // 签发 session cookie（payload 按字母序：exp, provider, provider_uid, user_id）
  const payload = {
    exp: Math.floor(Date.now() / 1000) + SESSION_MAX_AGE,
    provider: 'gitee',
    provider_uid: providerUid,
    user_id: user.id,
  };
  const token = await signSession(payload, sessionSecret);
  if (!token) return jsonResponse({ detail: 'SESSION_SECRET 未配置' }, 503);
  const sessionCookie = makeCookie(SESSION_COOKIE_NAME, token, SESSION_MAX_AGE);
  const clearState = clearCookie(STATE_COOKIE_NAME);
  return redirect307('/', [sessionCookie, clearState]);
}

async function me(request, env) {
  const sessionSecret = env.SESSION_SECRET || '';
  const cookies = getCookies(request);
  const token = cookies[SESSION_COOKIE_NAME] || '';
  if (!token) return jsonResponse({ logged_in: false, user: null, privileges: [] });
  const payload = await verifySession(token, sessionSecret);
  if (!payload) {
    // cookie 无效/过期，清掉
    return jsonResponse(
      { logged_in: false, user: null, privileges: [] },
      200,
      { cookies: [clearCookie(SESSION_COOKIE_NAME)] },
    );
  }
  const provider = payload.provider || '';
  const providerUid = payload.provider_uid || '';
  if (!provider || !providerUid) {
    return jsonResponse({ logged_in: false, user: null, privileges: [] });
  }
  const user = await getUserByProviderUid(env, provider, providerUid);
  if (!user) return jsonResponse({ logged_in: false, user: null, privileges: [] });
  return jsonResponse({
    logged_in: true,
    user: {
      name: user.name,
      avatar: user.avatar,
      provider: user.provider,
    },
    privileges: PRIVILEGES_LOGGED_IN,
  });
}

function logout() {
  return jsonResponse(
    { logged_out: true },
    200,
    { cookies: [clearCookie(SESSION_COOKIE_NAME)] },
  );
}

function notImplemented(provider) {
  return jsonResponse({ detail: `${provider} 登录即将支持` }, 501);
}

// ============ 主 handler ============

export default async function authHandler(request, env) {
  // CORS preflight
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  const url = new URL(request.url);
  const pathname = url.pathname;

  if (request.method === 'GET' && pathname === '/api/auth/login/gitee') {
    return loginGitee(request, env);
  }
  if (request.method === 'GET' && pathname === '/api/auth/callback/gitee') {
    return callbackGitee(request, env, url);
  }
  if (request.method === 'GET' && pathname === '/api/auth/me') {
    return me(request, env);
  }
  if (request.method === 'POST' && pathname === '/api/auth/logout') {
    return logout();
  }
  if (request.method === 'GET' && pathname === '/api/auth/login/github') {
    return notImplemented('github');
  }
  if (request.method === 'GET' && pathname === '/api/auth/login/google') {
    return notImplemented('google');
  }
  return jsonResponse({ detail: 'Not Found' }, 404);
}
