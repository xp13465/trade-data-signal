// CF Workers OAuth 接口（2026-08-03）。
// 移植自 app/auth.py（FastAPI），生产 ss.fx8.store/api/auth/* 走此 Worker 不回源。
// 本地开发走 uvicorn app/auth.py（FastAPI + sentiment.db users 表），生产走此 Worker。
//
// 路由（7 个：gitee 完整 + github 完整 + google 占位）：
// - GET  /api/auth/login/gitee     生成 state（KV TTL 5min）+ 307 跳 Gitee 授权页 + Set-Cookie oauth_state
// - GET  /api/auth/callback/gitee  校验 state（KV + cookie 双校验）+ 换 token + 拉用户 + upsert KV users + 发 session cookie + 307 回 /
// - GET  /api/auth/login/github    生成 state + 307 跳 GitHub 授权页（scope=read:user）+ Set-Cookie oauth_state
// - GET  /api/auth/callback/github 校验 state + 换 token（POST github.com/login/oauth/access_token）+ 拉用户（GET api.github.com/user Bearer）+ upsert KV users + 发 session cookie + 307 回 /
// - GET  /api/auth/me              返回 {logged_in, user, privileges}
// - POST /api/auth/logout          清 session cookie
// - GET  /api/auth/login/google    占位 501
//
// session：Web Crypto HMAC-SHA256 签名 cookie，格式 base64url(payload).base64url(hmac)
//   payload={exp, provider, provider_uid, user_id}（字母序插入，对齐 Python sort_keys）
//   注：比 FastAPI 多存 provider_uid，因 KV 无按 user_id 查询，me 需 provider+provider_uid 直取 user record
// users：KV key=user:<provider>:<provider_uid>，value=JSON{id,provider,provider_uid,name,avatar,email,created_at,last_login_at}
//   id 用 crypto.randomUUID()（KV 无自增）；登录时 upsert：存在更新 last_login_at，不存在新建
// state：无状态校验 = HMAC 签名 + cookie 匹配（state=random.base64url(HMAC-SHA256(random, SESSION_SECRET))）防 CSRF/防伪造
//   KV 仅作防重放辅助：login put，callback get 到就 delete，get 不到不阻断（容忍 CF KV 最终一致性 up to 60s 跨边缘节点传播延迟）
//
// 多站点 OAuth 方案E+G（2026-08-04）：
//   备站(sss.sugas.site/s.sugas.site/localhost)无 Worker，/api/auth/* 走主站 ss.fx8.store 跨域 fetch。
//   登录流程：备站点登录按钮 -> 跳主站 /api/auth/login/{provider}?redirect=<备站URL>
//     -> OAuth 完成 callback -> 若 redirect 为备站白名单 -> 生成 Bearer token -> 307 跳 ${redirect}#auth_token=<token>
//     -> 备站 app.js 启动检测 #auth_token= -> 存 localStorage -> 清 hash -> 后续 fetch /api/auth/me 带 Authorization: Bearer
//   Bearer token：HMAC 签名 payload={exp,provider,provider_uid,user_id,type:'bearer'}，TTL 7 天，KV 存 auth_token:${token} -> payload（提供撤销能力，logout 时 delete）
//   /api/auth/token 路由：用 session cookie 换 Bearer token（主站用户/API 调用场景，备站场景由 callback 直接签发）
//   /api/auth/me 支持 Bearer：优先读 Authorization header，无则读 cookie
//   CORS：动态 Allow-Origin（备站白名单），Allow-Credentials true，Allow-Headers Authorization, Content-Type
//
// env 变量（wrangler secret put 配置，不进 wrangler.jsonc）：
//   GITEE_CLIENT_ID / GITEE_CLIENT_SECRET / GITEE_REDIRECT_URI（生产=https://ss.fx8.store/api/auth/callback/gitee）/ SESSION_SECRET
//   GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET / GITHUB_REDIRECT_URI（生产=https://ss.fx8.store/api/auth/callback/github）
//   Google 未实现，占位
// KV binding 复用 SUBSCRIBE_KV（见 wrangler.jsonc kv_namespaces）。

const SESSION_COOKIE_NAME = 'session';
const STATE_COOKIE_NAME = 'oauth_state';
const SESSION_MAX_AGE = 30 * 24 * 3600;  // 30 天
const STATE_TTL = 300;  // 5 分钟（KV expirationTtl 最小 60s）
const PRIVILEGES_LOGGED_IN = ['detailed_view', 'trade_sim', 'subscribe', 'compare', 'fund_score'];

// Bearer token（多站点方案G）：TTL 7 天，存 KV 提供撤销能力
const BEARER_TOKEN_TTL = 7 * 24 * 3600;  // 7 天
const BEARER_TOKEN_PREFIX = 'auth_token:';
const OAUTH_REDIRECT_PREFIX = 'oauth_redirect:';  // state -> redirect URL（TTL 同 state）

// 备站白名单：Allow-Origin 动态返回 + callback redirect 校验
// 主站 ss.fx8.store 自身也含（同源无需 CORS，但统一处理逻辑）
const ALLOWED_ORIGINS = new Set([
  'https://ss.fx8.store',
  'https://sss.sugas.site',
  'https://s.sugas.site',
  'http://localhost:8000',
  'http://127.0.0.1:8000',
]);

// 备站 hostname 白名单：callback redirect 校验（防开放重定向）
const ALLOWED_REDIRECT_HOSTS = new Set([
  'ss.fx8.store',
  'sss.sugas.site',
  's.sugas.site',
  'localhost',
  '127.0.0.1',
]);

function corsHeaders(request) {
  const origin = request ? (request.headers.get('Origin') || '') : '';
  const h = {
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Max-Age': '86400',
  };
  // 白名单 Origin：回显具体 Origin + Allow-Credentials（支持 cookie + Authorization）
  // 非白名单/无 Origin（同源/非浏览器）：Allow-Origin: *（不带 Allow-Credentials，因 * 和 credentials 不兼容）
  if (origin && ALLOWED_ORIGINS.has(origin)) {
    h['Access-Control-Allow-Origin'] = origin;
    h['Access-Control-Allow-Credentials'] = 'true';
    h['Vary'] = 'Origin';
  } else {
    h['Access-Control-Allow-Origin'] = '*';
  }
  return h;
}

// ============ helpers ============

function jsonResponse(body, status = 200, opts = {}) {
  const h = new Headers();
  h.set('Content-Type', 'application/json; charset=utf-8');
  const cors = corsHeaders(opts.request || null);
  for (const [k, v] of Object.entries(cors)) h.set(k, v);
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

// Bearer token（多站点方案G）：格式同 session = base64url(payload).base64url(hmac)
// payload={exp, provider, provider_uid, user_id, type:'bearer'}（type 字段区分 session cookie）
// TTL 7 天，存 KV auth_token:${token} -> payload JSON（提供撤销能力，logout delete KV）
async function signBearer(payload, sessionSecret) {
  if (!sessionSecret) return null;
  const body = b64urlStr(JSON.stringify(payload));
  const sig = await hmacSign(sessionSecret, body);
  return `${body}.${sig}`;
}

async function verifyBearer(token, sessionSecret) {
  if (!token || !sessionSecret || !token.includes('.')) return null;
  try {
    const idx = token.lastIndexOf('.');
    const body = token.slice(0, idx);
    const sig = token.slice(idx + 1);
    const ok = await hmacVerify(sessionSecret, body, sig);
    if (!ok) return null;
    const payload = JSON.parse(unb64urlStr(body));
    if (!payload || typeof payload !== 'object') return null;
    if (payload.type !== 'bearer') return null;  // 必须是 bearer 类型
    const exp = payload.exp || 0;
    if (exp && exp < Math.floor(Date.now() / 1000)) return null;
    return payload;
  } catch {
    return null;
  }
}

// 签发 Bearer token 并存 KV（TTL 7 天），返回 token 字符串
// 用于 callback 跳备站 + /api/auth/token 路由
async function issueBearerToken(env, provider, providerUid, userId) {
  const sessionSecret = env.SESSION_SECRET || '';
  if (!sessionSecret) return null;
  const payload = {
    exp: Math.floor(Date.now() / 1000) + BEARER_TOKEN_TTL,
    provider,
    provider_uid: providerUid,
    user_id: userId,
    type: 'bearer',
  };
  const token = await signBearer(payload, sessionSecret);
  if (!token) return null;
  await env.SUBSCRIBE_KV.put(
    BEARER_TOKEN_PREFIX + token,
    JSON.stringify(payload),
    { expirationTtl: BEARER_TOKEN_TTL },
  );
  return token;
}

// 从 request 提取 Bearer token（Authorization: Bearer xxx）
function getBearerToken(request) {
  const auth = request.headers.get('Authorization') || '';
  const m = auth.match(/^Bearer\s+(.+)$/i);
  return m ? m[1].trim() : '';
}

// redirect URL 安全校验：hostname 在白名单内（防开放重定向）
function isAllowedRedirect(redirectUrl) {
  if (!redirectUrl) return false;
  try {
    const u = new URL(redirectUrl);
    return ALLOWED_REDIRECT_HOSTS.has(u.hostname);
  } catch {
    return false;
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
  const sessionSecret = env.SESSION_SECRET || '';
  if (!sessionSecret) return jsonResponse({ detail: 'SESSION_SECRET 未配置' }, 503);
  const stateRandom = crypto.randomUUID();
  const stateSig = await hmacSign(sessionSecret, stateRandom);
  const state = `${stateRandom}.${stateSig}`;
  // state 存 KV 仅作防重放辅助（callback 容忍 get 不到，不依赖 KV 最终一致性）
  await env.SUBSCRIBE_KV.put(`oauth_state:${state}`, '1', { expirationTtl: STATE_TTL });
  // 多站点方案G：存 redirect 参数到 KV（callback 跳回备站用），白名单校验防开放重定向
  const url = new URL(request.url);
  const redirect = url.searchParams.get('redirect') || '';
  if (redirect && isAllowedRedirect(redirect)) {
    await env.SUBSCRIBE_KV.put(OAUTH_REDIRECT_PREFIX + state, redirect, { expirationTtl: STATE_TTL });
  }
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

  // state 校验：HMAC 签名 + cookie 匹配（无状态校验，不依赖 KV 最终一致性）
  const stateParts = state.split('.');
  if (stateParts.length !== 2) {
    return jsonResponse({ detail: 'state 格式无效' }, 400);
  }
  const [stateRandom, stateSig] = stateParts;
  if (!sessionSecret) return jsonResponse({ detail: 'SESSION_SECRET 未配置' }, 503);
  const sigOk = await hmacVerify(sessionSecret, stateRandom, stateSig);
  if (!sigOk) {
    return jsonResponse({ detail: 'state 签名校验失败（HMAC 不匹配，可能被篡改）' }, 400);
  }
  const cookies = getCookies(request);
  const cookieState = cookies[STATE_COOKIE_NAME] || '';
  if (!cookieState || cookieState !== state) {
    return jsonResponse({ detail: 'state 校验失败（cookie 不匹配，可能跨站请求伪造）' }, 400);
  }
  // KV 仅作防重放辅助：get 到就 delete（用完即废），get 不到不阻断（容忍 KV 最终一致性）
  try {
    const kvState = await env.SUBSCRIBE_KV.get(`oauth_state:${state}`);
    if (kvState) await env.SUBSCRIBE_KV.delete(`oauth_state:${state}`);
  } catch {}

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

  // 多站点方案G：读 redirect 参数，若备站白名单 -> 签发 Bearer token 跳 ${redirect}#auth_token=<token>
  // 否则正常跳主站首页（设 session cookie）
  let redirect;
  try {
    redirect = await env.SUBSCRIBE_KV.get(OAUTH_REDIRECT_PREFIX + state);
    if (redirect) await env.SUBSCRIBE_KV.delete(OAUTH_REDIRECT_PREFIX + state);
  } catch {}
  if (redirect && isAllowedRedirect(redirect)) {
    const bearer = await issueBearerToken(env, 'gitee', providerUid, user.id);
    if (bearer) {
      const sep = redirect.includes('#') ? '&' : '#';
      return redirect307(`${redirect}${sep}auth_token=${encodeURIComponent(bearer)}`, [clearState]);
    }
    // Bearer 签发失败，降级走主站 cookie 流程
  }
  return redirect307('/', [sessionCookie, clearState]);
}

async function loginGithub(request, env) {
  const clientId = env.GITHUB_CLIENT_ID || '';
  const clientSecret = env.GITHUB_CLIENT_SECRET || '';
  const redirectUri = env.GITHUB_REDIRECT_URI || '';
  if (!clientId || !clientSecret || !redirectUri) {
    return jsonResponse({ detail: 'GitHub OAuth 未配置（GITHUB_CLIENT_ID/SECRET/REDIRECT_URI 任一缺失）' }, 503);
  }
  const sessionSecret = env.SESSION_SECRET || '';
  if (!sessionSecret) return jsonResponse({ detail: 'SESSION_SECRET 未配置' }, 503);
  const stateRandom = crypto.randomUUID();
  const stateSig = await hmacSign(sessionSecret, stateRandom);
  const state = `${stateRandom}.${stateSig}`;
  // state 存 KV 仅作防重放辅助（callback 容忍 get 不到，不依赖 KV 最终一致性）
  await env.SUBSCRIBE_KV.put(`oauth_state:${state}`, '1', { expirationTtl: STATE_TTL });
  // 多站点方案G：存 redirect 参数到 KV（callback 跳回备站用），白名单校验防开放重定向
  const url = new URL(request.url);
  const redirect = url.searchParams.get('redirect') || '';
  if (redirect && isAllowedRedirect(redirect)) {
    await env.SUBSCRIBE_KV.put(OAUTH_REDIRECT_PREFIX + state, redirect, { expirationTtl: STATE_TTL });
  }
  const loginUrl = (
    'https://github.com/login/oauth/authorize'
    + `?client_id=${encodeURIComponent(clientId)}`
    + `&redirect_uri=${encodeURIComponent(redirectUri)}`
    + '&scope=read:user'
    + `&state=${encodeURIComponent(state)}`
  );
  const stateCookie = makeCookie(STATE_COOKIE_NAME, state, STATE_TTL);
  return redirect307(loginUrl, [stateCookie]);
}

async function callbackGithub(request, env, url) {
  const clientId = env.GITHUB_CLIENT_ID || '';
  const clientSecret = env.GITHUB_CLIENT_SECRET || '';
  const redirectUri = env.GITHUB_REDIRECT_URI || '';
  const sessionSecret = env.SESSION_SECRET || '';
  if (!clientId || !clientSecret || !redirectUri) {
    return jsonResponse({ detail: 'GitHub OAuth 未配置' }, 503);
  }
  const code = url.searchParams.get('code') || '';
  const state = url.searchParams.get('state') || '';
  if (!code || !state) return jsonResponse({ detail: '回调缺少 code/state 参数' }, 400);

  // state 校验：HMAC 签名 + cookie 匹配（无状态校验，不依赖 KV 最终一致性）
  const stateParts = state.split('.');
  if (stateParts.length !== 2) {
    return jsonResponse({ detail: 'state 格式无效' }, 400);
  }
  const [stateRandom, stateSig] = stateParts;
  if (!sessionSecret) return jsonResponse({ detail: 'SESSION_SECRET 未配置' }, 503);
  const sigOk = await hmacVerify(sessionSecret, stateRandom, stateSig);
  if (!sigOk) {
    return jsonResponse({ detail: 'state 签名校验失败（HMAC 不匹配，可能被篡改）' }, 400);
  }
  const cookies = getCookies(request);
  const cookieState = cookies[STATE_COOKIE_NAME] || '';
  if (!cookieState || cookieState !== state) {
    return jsonResponse({ detail: 'state 校验失败（cookie 不匹配，可能跨站请求伪造）' }, 400);
  }
  // KV 仅作防重放辅助：get 到就 delete（用完即废），get 不到不阻断（容忍 KV 最终一致性）
  try {
    const kvState = await env.SUBSCRIBE_KV.get(`oauth_state:${state}`);
    if (kvState) await env.SUBSCRIBE_KV.delete(`oauth_state:${state}`);
  } catch {}

  // 换 access_token（GitHub 必须带 Accept: application/json 否则返回 url-encoded string）
  // body JSON 含 client_id/client_secret/code/redirect_uri（GitHub 不需 grant_type，默认 authorization_code）
  const tokenBody = JSON.stringify({
    client_id: clientId,
    client_secret: clientSecret,
    code,
    redirect_uri: redirectUri,
  });
  let accessToken;
  try {
    const tokResp = await fetch('https://github.com/login/oauth/access_token', {
      method: 'POST',
      headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
      body: tokenBody,
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
  if (!accessToken) return jsonResponse({ detail: 'GitHub 未返回 access_token' }, 400);

  // 拉用户信息（GitHub 要求 Authorization: Bearer <token>；API 强制要求 User-Agent 否则 403）
  let u;
  try {
    const userResp = await fetch('https://api.github.com/user', {
      headers: {
        'Accept': 'application/json',
        'Authorization': `Bearer ${accessToken}`,
        'User-Agent': 'signal-lab-oauth',
      },
    });
    if (userResp.status !== 200) {
      return jsonResponse({ detail: `拉 GitHub 用户信息失败: ${userResp.status}` }, 400);
    }
    u = await userResp.json();
  } catch (e) {
    return jsonResponse({ detail: `拉用户信息异常: ${e.message || String(e)}` }, 500);
  }
  const providerUid = String(u.id || '');
  if (!providerUid) return jsonResponse({ detail: 'GitHub 用户信息缺 id 字段' }, 400);
  // GitHub name 字段可空（用户未设 profile name），login 一定有；优先 name 退化 login
  const name = u.name || u.login || '';
  const avatar = u.avatar_url || '';
  const email = u.email || '';

  // upsert users（KV）
  const user = await upsertUser(env, 'github', providerUid, name, avatar, email);

  // 签发 session cookie（payload 按字母序：exp, provider, provider_uid, user_id）
  const payload = {
    exp: Math.floor(Date.now() / 1000) + SESSION_MAX_AGE,
    provider: 'github',
    provider_uid: providerUid,
    user_id: user.id,
  };
  const token = await signSession(payload, sessionSecret);
  if (!token) return jsonResponse({ detail: 'SESSION_SECRET 未配置' }, 503);
  const sessionCookie = makeCookie(SESSION_COOKIE_NAME, token, SESSION_MAX_AGE);
  const clearState = clearCookie(STATE_COOKIE_NAME);

  // 多站点方案G：读 redirect 参数，若备站白名单 -> 签发 Bearer token 跳 ${redirect}#auth_token=<token>
  // 否则正常跳主站首页（设 session cookie）
  let redirect;
  try {
    redirect = await env.SUBSCRIBE_KV.get(OAUTH_REDIRECT_PREFIX + state);
    if (redirect) await env.SUBSCRIBE_KV.delete(OAUTH_REDIRECT_PREFIX + state);
  } catch {}
  if (redirect && isAllowedRedirect(redirect)) {
    const bearer = await issueBearerToken(env, 'github', providerUid, user.id);
    if (bearer) {
      const sep = redirect.includes('#') ? '&' : '#';
      return redirect307(`${redirect}${sep}auth_token=${encodeURIComponent(bearer)}`, [clearState]);
    }
    // Bearer 签发失败，降级走主站 cookie 流程
  }
  return redirect307('/', [sessionCookie, clearState]);
}

// me：优先 Authorization Bearer token（备站跨域场景），无则读 session cookie（主站同源场景）
async function me(request, env) {
  const sessionSecret = env.SESSION_SECRET || '';
  let provider = '';
  let providerUid = '';

  // 1) Bearer token 模式（备站跨域 fetch）
  const bearerToken = getBearerToken(request);
  if (bearerToken) {
    const payload = await verifyBearer(bearerToken, sessionSecret);
    if (payload) {
      // 查 KV 确认 token 未被撤销（logout 会 delete KV）
      let kvPayload = null;
      try {
        const raw = await env.SUBSCRIBE_KV.get(BEARER_TOKEN_PREFIX + bearerToken);
        if (raw) kvPayload = JSON.parse(raw);
      } catch {}
      if (kvPayload) {
        provider = kvPayload.provider || payload.provider || '';
        providerUid = kvPayload.provider_uid || payload.provider_uid || '';
      }
    }
    if (!provider || !providerUid) {
      return jsonResponse({ logged_in: false, user: null, privileges: [] }, 200, { request });
    }
  } else {
    // 2) session cookie 模式（主站同源）
    const cookies = getCookies(request);
    const token = cookies[SESSION_COOKIE_NAME] || '';
    if (!token) return jsonResponse({ logged_in: false, user: null, privileges: [] }, 200, { request });
    const payload = await verifySession(token, sessionSecret);
    if (!payload) {
      // cookie 无效/过期，清掉
      return jsonResponse(
        { logged_in: false, user: null, privileges: [] },
        200,
        { cookies: [clearCookie(SESSION_COOKIE_NAME)], request },
      );
    }
    provider = payload.provider || '';
    providerUid = payload.provider_uid || '';
    if (!provider || !providerUid) {
      return jsonResponse({ logged_in: false, user: null, privileges: [] }, 200, { request });
    }
  }
  const user = await getUserByProviderUid(env, provider, providerUid);
  if (!user) return jsonResponse({ logged_in: false, user: null, privileges: [] }, 200, { request });
  return jsonResponse({
    logged_in: true,
    user: {
      name: user.name,
      avatar: user.avatar,
      provider: user.provider,
    },
    privileges: PRIVILEGES_LOGGED_IN,
  }, 200, { request });
}

// token 路由（GET /api/auth/token）：用 session cookie 换 Bearer token
// 用途：主站用户/API 调用生成 Bearer token（备站场景由 callback 直接签发，不走此路由）
async function tokenRoute(request, env) {
  const sessionSecret = env.SESSION_SECRET || '';
  const cookies = getCookies(request);
  const token = cookies[SESSION_COOKIE_NAME] || '';
  if (!token) {
    return jsonResponse({ detail: '未登录（需 session cookie 认证）' }, 401, { request });
  }
  const payload = await verifySession(token, sessionSecret);
  if (!payload) {
    return jsonResponse(
      { detail: 'session 无效或过期' },
      401,
      { cookies: [clearCookie(SESSION_COOKIE_NAME)], request },
    );
  }
  const provider = payload.provider || '';
  const providerUid = payload.provider_uid || '';
  const userId = payload.user_id || '';
  if (!provider || !providerUid) {
    return jsonResponse({ detail: 'session 缺 provider/provider_uid' }, 400, { request });
  }
  const bearer = await issueBearerToken(env, provider, providerUid, userId);
  if (!bearer) {
    return jsonResponse({ detail: 'SESSION_SECRET 未配置或签发失败' }, 503, { request });
  }
  return jsonResponse({
    token: bearer,
    token_type: 'Bearer',
    expires_in: BEARER_TOKEN_TTL,
  }, 200, { request });
}

// logout：支持 Bearer token（备站）和 session cookie（主站）
// Bearer 模式 delete KV 撤销 token；cookie 模式清 cookie；两者皆有可能同时存在（主站用户也生成了 Bearer）
function logout(request, env) {
  const cookies = [];
  // 1) Bearer token：delete KV 撤销
  const bearerToken = getBearerToken(request);
  if (bearerToken) {
    try { env.SUBSCRIBE_KV.delete(BEARER_TOKEN_PREFIX + bearerToken); } catch {}
  }
  // 2) session cookie：清掉
  cookies.push(clearCookie(SESSION_COOKIE_NAME));
  return jsonResponse({ logged_out: true }, 200, { cookies, request });
}

function notImplemented(provider, request) {
  return jsonResponse({ detail: `${provider} 登录即将支持` }, 501, { request });
}

// ============ 留言箱 ============
// 复用 session cookie（主站）+ Bearer token（备站跨域）双模式认证，与 me 函数同模式，KV 存储：
//   key   = feedback:<provider>:<provider_uid>:<timestamp_ms>
//   value = JSON{id, user_id, provider, content, created_at, status, ip_hash}
// 用户身份主键用 provider+provider_uid（session/bearer payload 必带，稳定唯一），user_id 作冗余字段
// 防滥用四层：①频控(同IP 10min≤1, KV feedback:rate:<hash>:<window> TTL 600s)
//   ②honeypot(body.website 非空=机器人,返200假成功) ③内容约束 50-2000 字 ④审核闸门 status=pending
// 频控 key 前缀 feedback:rate: 与留言 key feedback:<provider>: 隔离，admin list 时排除 rate 前缀
// 路由：POST /api/feedback 提交留言；GET /api/feedback 列当前用户留言（倒序）
//   GET/POST /api/feedback/admin 管理端审核（X-Admin-Pwd + env.FEEDBACK_ADMIN_PASSWORD 认证）

async function getSessionUser(request, env) {
  const sessionSecret = env.SESSION_SECRET || '';
  if (!sessionSecret) return null;
  // 1) Bearer token 模式（备站跨域 fetch，与 me 同模式）
  const bearerToken = getBearerToken(request);
  if (bearerToken) {
    const payload = await verifyBearer(bearerToken, sessionSecret);
    if (!payload) return null;
    // 查 KV 确认 token 未被撤销（logout 会 delete KV）
    let kvPayload = null;
    try {
      const raw = await env.SUBSCRIBE_KV.get(BEARER_TOKEN_PREFIX + bearerToken);
      if (raw) kvPayload = JSON.parse(raw);
    } catch {}
    if (!kvPayload) return null;
    const provider = kvPayload.provider || payload.provider || '';
    const providerUid = kvPayload.provider_uid || payload.provider_uid || '';
    const userId = kvPayload.user_id || payload.user_id || '';
    if (!provider || !providerUid) return null;
    return { provider, providerUid, userId };
  }
  // 2) session cookie 模式（主站同源）
  const cookies = getCookies(request);
  const token = cookies[SESSION_COOKIE_NAME] || '';
  if (!token) return null;
  const payload = await verifySession(token, sessionSecret);
  if (!payload) return null;
  const provider = payload.provider || '';
  const providerUid = payload.provider_uid || '';
  const userId = payload.user_id || '';
  if (!provider || !providerUid) return null;
  return { provider, providerUid, userId };
}

async function submitFeedback(request, env) {
  const session = await getSessionUser(request, env);
  if (!session) {
    return jsonResponse({ detail: '未登录（需 session cookie 认证）' }, 401, { request });
  }
  let body;
  try { body = await request.json(); } catch {
    return jsonResponse({ detail: '请求体不是有效 JSON' }, 400, { request });
  }
  // ② honeypot：website 隐藏字段非空 = 机器人，返 200 假成功不报错（防探测）
  const website = body && typeof body.website === 'string' ? body.website.trim() : '';
  if (website) {
    return jsonResponse({ ok: true }, 200, { request });
  }
  const content = (body && typeof body.content === 'string') ? body.content.trim() : '';
  if (!content) {
    return jsonResponse({ detail: '留言内容不能为空' }, 400, { request });
  }
  // ③ 内容约束 50-2000 字（trim 后校验）
  if (content.length < 50) {
    return jsonResponse({ detail: '留言内容至少 50 字（请详细描述便于我们理解）' }, 400, { request });
  }
  if (content.length > 2000) {
    return jsonResponse({ detail: '留言内容不能超过 2000 字' }, 400, { request });
  }
  // ① 频控：同 IP 10min ≤1 条（固定窗口 bucket）
  const ipHash = await getIpHash(request);
  const windowBucket = Math.floor(Date.now() / 600000); // 10min 窗口
  const rateKey = `feedback:rate:${ipHash}:${windowBucket}`;
  try {
    const existing = await env.SUBSCRIBE_KV.get(rateKey);
    if (existing) {
      return jsonResponse({ detail: '提交过于频繁，请 10 分钟后再试' }, 429, { request });
    }
  } catch {}
  const userKey = `${session.provider}:${session.providerUid}`;
  const ts = Date.now();
  const id = crypto.randomUUID();
  const created_at = new Date(ts).toISOString();
  const feedback = {
    id,
    user_id: session.userId || userKey,
    provider: session.provider,
    content,
    created_at,
    // ④ 审核闸门：新留言 pending，管理端 approve 后 approved / reject 后 rejected
    status: 'pending',
    ip_hash: ipHash,
  };
  const kvKey = `feedback:${userKey}:${ts}`;
  try {
    await env.SUBSCRIBE_KV.put(kvKey, JSON.stringify(feedback));
    // 频控通过后写 rate key TTL 600s
    await env.SUBSCRIBE_KV.put(rateKey, String(ts), { expirationTtl: 600 });
  } catch (e) {
    return jsonResponse({ detail: '留言保存失败' }, 500, { request });
  }
  return jsonResponse({ ok: true, id, created_at }, 200, { request });
}

// IP hash（脱敏）：取 CF-Connecting-IP 或 x-forwarded-for 首段，SHA-256 取前 16 hex 字符
// 用于频控 key 隔离 + admin 列表展示（不存原始 IP，隐私保护）
async function getIpHash(request) {
  const ip = (request.headers.get('CF-Connecting-IP') || '')
    || ((request.headers.get('x-forwarded-for') || '').split(',')[0].trim())
    || 'unknown';
  const data = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(ip));
  const bytes = new Uint8Array(data);
  let hex = '';
  for (const b of bytes) hex += b.toString(16).padStart(2, '0');
  return hex.slice(0, 16);
}

async function listFeedback(request, env) {
  const session = await getSessionUser(request, env);
  if (!session) {
    return jsonResponse({ detail: '未登录（需 session cookie 认证）' }, 401, { request });
  }
  const userKey = `${session.provider}:${session.providerUid}`;
  const prefix = `feedback:${userKey}:`;
  const feedbacks = [];
  let cursor;
  try {
    do {
      const listOpts = { prefix, limit: 100 };
      if (cursor) listOpts.cursor = cursor;
      const result = await env.SUBSCRIBE_KV.list(listOpts);
      const keys = result.keys || [];
      const gets = keys.map((k) => env.SUBSCRIBE_KV.get(k.name).catch(() => null));
      const values = await Promise.all(gets);
      for (const raw of values) {
        if (!raw) continue;
        try {
          const fb = JSON.parse(raw);
          feedbacks.push({
            id: fb.id,
            content: fb.content,
            created_at: fb.created_at,
            status: fb.status || 'pending',
          });
        } catch {}
      }
      cursor = result.list_complete ? null : result.cursor;
      if (feedbacks.length >= 100) break;
    } while (cursor);
  } catch (e) {
    return jsonResponse({ detail: '读取留言失败' }, 500, { request });
  }
  feedbacks.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
  return jsonResponse({ feedbacks }, 200, { request });
}

// ============ 留言管理端（admin 审核） ============
// 认证：X-Admin-Pwd header 对比 Workers secret FEEDBACK_ADMIN_PASSWORD（仿 subscribe.js checkPwd 模式）
// 路由：GET /api/feedback/admin?status=pending|approved|rejected|all  列全部留言（跨用户）
//       POST /api/feedback/admin {action:"approve"|"reject"|"delete", key:"<kvKey>"}  改/删 KV

function checkAdminPwd(request, env) {
  const provided = request.headers.get('X-Admin-Pwd') || '';
  const expected = env.FEEDBACK_ADMIN_PASSWORD || '';
  if (!expected) {
    return { ok: false, resp: jsonResponse({ detail: '留言管理端未配置密码（FEEDBACK_ADMIN_PASSWORD secret 未设置）' }, 503, { request }) };
  }
  if (!provided || provided !== expected) {
    return { ok: false, resp: jsonResponse({ detail: '密码错误' }, 401, { request }) };
  }
  return { ok: true };
}

async function adminListFeedback(request, env, url) {
  const auth = checkAdminPwd(request, env);
  if (!auth.ok) return auth.resp;
  const statusFilter = (url.searchParams.get('status') || 'all').toLowerCase();
  const feedbacks = [];
  let cursor;
  try {
    do {
      const listOpts = { prefix: 'feedback:', limit: 1000 };
      if (cursor) listOpts.cursor = cursor;
      const result = await env.SUBSCRIBE_KV.list(listOpts);
      // 排除频控 key（feedback:rate: 前缀）
      const keys = (result.keys || []).filter((k) => !k.name.startsWith('feedback:rate:'));
      const gets = keys.map((k) => env.SUBSCRIBE_KV.get(k.name).then((v) => ({ k: k.name, v })).catch(() => null));
      const pairs = await Promise.all(gets);
      for (const p of pairs) {
        if (!p || !p.v) continue;
        try {
          const fb = JSON.parse(p.v);
          const st = fb.status || 'pending';
          if (statusFilter !== 'all' && st !== statusFilter) continue;
          feedbacks.push({
            id: fb.id,
            kv_key: p.k,
            user_id: fb.user_id || '',
            provider: fb.provider || '',
            content: fb.content || '',
            created_at: fb.created_at || '',
            status: st,
            ip_hash: fb.ip_hash || '',
          });
        } catch {}
      }
      cursor = result.list_complete ? null : result.cursor;
    } while (cursor);
  } catch (e) {
    return jsonResponse({ detail: '读取留言失败' }, 500, { request });
  }
  feedbacks.sort((a, b) => (a.created_at < b.created_at ? 1 : a.created_at > b.created_at ? -1 : 0));
  return jsonResponse({ feedbacks, total: feedbacks.length }, 200, { request });
}

async function adminActionFeedback(request, env) {
  const auth = checkAdminPwd(request, env);
  if (!auth.ok) return auth.resp;
  let body;
  try { body = await request.json(); } catch {
    return jsonResponse({ detail: '请求体不是有效 JSON' }, 400, { request });
  }
  const action = body && typeof body.action === 'string' ? body.action : '';
  const kvKey = body && typeof body.key === 'string' ? body.key : '';
  // key 安全校验：必须 feedback: 前缀且非 rate 前缀
  if (!kvKey || !kvKey.startsWith('feedback:') || kvKey.startsWith('feedback:rate:')) {
    return jsonResponse({ detail: '无效的留言 key' }, 400, { request });
  }
  if (!['approve', 'reject', 'delete'].includes(action)) {
    return jsonResponse({ detail: '无效操作（approve/reject/delete）' }, 400, { request });
  }
  let raw;
  try { raw = await env.SUBSCRIBE_KV.get(kvKey); } catch {}
  if (!raw) {
    return jsonResponse({ detail: '留言不存在或已删除' }, 404, { request });
  }
  if (action === 'delete') {
    try { await env.SUBSCRIBE_KV.delete(kvKey); } catch (e) {
      return jsonResponse({ detail: '删除失败' }, 500, { request });
    }
    return jsonResponse({ ok: true, action: 'delete' }, 200, { request });
  }
  let fb;
  try { fb = JSON.parse(raw); } catch {
    return jsonResponse({ detail: '留言数据损坏' }, 500, { request });
  }
  fb.status = action === 'approve' ? 'approved' : 'rejected';
  try {
    await env.SUBSCRIBE_KV.put(kvKey, JSON.stringify(fb));
  } catch (e) {
    return jsonResponse({ detail: '更新失败' }, 500, { request });
  }
  return jsonResponse({ ok: true, action, status: fb.status }, 200, { request });
}

// ============ 主 handler ============

export default async function authHandler(request, env) {
  // CORS preflight：动态 Allow-Origin（白名单回显 + Allow-Credentials）
  if (request.method === 'OPTIONS') {
    return new Response(null, { status: 204, headers: corsHeaders(request) });
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
  if (request.method === 'GET' && pathname === '/api/auth/token') {
    return tokenRoute(request, env);
  }
  if (request.method === 'POST' && pathname === '/api/auth/logout') {
    return logout(request, env);
  }
  if (request.method === 'GET' && pathname === '/api/auth/login/github') {
    return loginGithub(request, env);
  }
  if (request.method === 'GET' && pathname === '/api/auth/callback/github') {
    return callbackGithub(request, env, url);
  }
  if (request.method === 'GET' && pathname === '/api/auth/login/google') {
    return notImplemented('google', request);
  }
  if (request.method === 'POST' && pathname === '/api/feedback') {
    return submitFeedback(request, env);
  }
  if (request.method === 'GET' && pathname === '/api/feedback') {
    return listFeedback(request, env);
  }
  if (request.method === 'GET' && pathname === '/api/feedback/admin') {
    return adminListFeedback(request, env, url);
  }
  if (request.method === 'POST' && pathname === '/api/feedback/admin') {
    return adminActionFeedback(request, env);
  }
  return jsonResponse({ detail: 'Not Found' }, 404, { request });
}
