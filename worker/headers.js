// Workers Static Assets: Worker 接管 response headers，实现 last-wins 覆盖 + 缓存分层。
// run_worker_first=true 时 _headers 文件不生效，所有 headers 在此统一设置。
// 部署：push main 后 Cloudflare Builds 跑 wrangler deploy，内置 esbuild 自动 bundle 本文件。

// 安全头（原 _headers /* 块内容，对非 HTML 响应浏览器自动忽略，无副作用）
// 订阅接口 handler（C 方案 2026-07-24：/api/* 路由分发到此，KV 存储+密码认证）
import subscribeHandler from './subscribe.js';
// OAuth 接口 handler（2026-08-03：/api/auth/* 分发到此，Web Crypto HMAC session + KV users）
import authHandler from './auth.js';

const SECURITY_HEADERS = {
  'Strict-Transport-Security': 'max-age=63072000; includeSubDomains; preload',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'SAMEORIGIN',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), accelerometer=(), gyroscope=()',
  "Content-Security-Policy-Report-Only": "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://hm.baidu.com https://zz.bdstatic.com https://push.zhanzhang.baidu.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https://web.ifzq.gtimg.cn https://hm.baidu.com; frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'",
};

// 有序规则：第一条匹配的生效（first-match-wins = 精确/具体优先，兜底放最后）。
// pathname 不含 query，故 ?v=xxxx 破缓存参数不影响匹配。
// 缓存分层原则：版本化 JS/CSS 1 年 immutable（靠 ?v= 换 URL 破缓存）；
//   HTML 入口 no-store（CF 边缘+浏览器均不缓存，每次回源拿最新；
//   2026-07-23 修：private/no-cache 实测对 CF Workers Static Assets 无效仍 HIT，
//   升级 no-store 彻底禁止缓存才能根治 index.html 被 CDN 缓存旧版）；
//   实时数据 60s（分钟级刷新）；纯历史 1h（每天收盘才更新）。
const CACHE_RULES = [
  // 1) 版本化静态资源：1 年 immutable（改动靠 ?v= 换 URL 破缓存）
  {
    match: p => /^\/(style\.css|app\.min\.js|lab\.min\.js|lab\.css|qr\.js)$/.test(p) || p.startsWith('/vendor/'),
    cc: 'public, max-age=31536000, immutable',
  },
  // 2) HTML 入口 / feed / trade_sim：no-store 彻底禁止缓存(CF 边缘+浏览器)
  //    private/no-cache 实测均无效(CF Workers Static Assets 仍 HIT 不重验)，
  //    2026-07-23 升级 no-store 根治。HTML 小文件每次回源成本可接受。
  {
    match: p =>
      p === '/' || p === '/index.html' ||
      /^\/trade_sim_/.test(p) ||
      p === '/data/feed.xml' || p === '/feed.xml',
    cc: 'no-store, max-age=0',
  },
  // 2.5) 盘中高频实时数据(overview/intraday_snapshot): no-store 彻底禁CF edge缓存
  //   根因: max-age=60 时 CF edge 60s窗口内用户命中旧版edge节点看到昨日overview(a_amount=昨日全天值)
  //   强刷Cmd+Shift+R无效(只清浏览器不清CF edge), fetchJSON加?_=Date.now()无效(CF忽略query string仍HIT)
  //   no-store让CF edge不缓存每次回源拿最新, overview 240KB(br后37KB)回源成本可接受(盘中用户量小)
  {
    match: p => p === '/data/overview.json' || p === '/data/intraday_snapshot.json',
    cc: 'no-store, max-age=0',
  },
  // 3) 实时数据 JSON（盘中/每日更新，需分钟级刷新）：60 秒
  //    global-extras-all 含 usdcnh 等实时指标，必须在历史规则前命中，否则会被 -all 匹配到 1h 致滞后。
  //    overview/intraday_snapshot 已拆到规则2.5 no-store（盘中高频更新根治看到旧版）。
  {
    match: p =>
      p === '/data/futures.json' || p === '/data/ad_line.json' ||
      p === '/data/summary.json' ||
      p === '/data/global-extras-all.json' ||
      p === '/data/new_high_low.json' || p === '/data/position.json' ||
      p === '/data/rotation.json' || p === '/data/volume_ratio.json' ||
      p === '/data/ma_alignment.json' || p === '/data/signal_freq.json' ||
      p === '/data/schedule_stats.json' || p === '/data/summary_history.json' ||
      p === '/data/etf_national_team_holders.json' || p === '/data/etf_national_team_quarterly.json' ||
      p.endsWith('-1m.json'),
    cc: 'public, max-age=60',
  },
  // 4) 指数/行业拆分目录：10 分钟（对齐 GitHub Pages sss.sugas.site max-age=600）
  //    deploy 后 CF edge 缓存 1h 致数据滞后，改 600s 与 GH Pages 对齐根治滞后。
  {
    match: p => p.startsWith('/data/index/'),
    cc: 'public, max-age=600',
  },
  // 5a) 盘中要快的小周期 K线(3m/6m/1y)：60 秒
  //     盘中每 15min 推新 a-stock/hk/global/sentiment-{3m,6m,1y}.json，
  //     原 1h 边缘缓存致盘中用户看到 1h 前数据；改 60s 根治盘中延迟。
  //     60s 多回源几次无害(CF 免费额度 100k/天够用)。
  //     注：-1m.json 已由规则3命中 max-age=60，此处不重复。
  {
    match: p => /-(3m|6m|1y)(-\w+)?\.json$/.test(p),
    cc: 'public, max-age=60',
  },
  // 5b) 历史 K线/全量/长周期(3y/5y/all) + 策略实验室 + 行业3y/5y/all-indices：1 小时
  //     这些每天收盘才更新一次，1h 缓存既省回源又保证当日数据最迟 1h 内刷到 CDN。
  {
    match: p =>
      p.startsWith('/data/lab/') ||
      p.startsWith('/data/industry-3y-indices/') ||
      p.startsWith('/data/industry-5y-indices/') ||
      p.startsWith('/data/industry-all-indices/') ||
      /-(3y|5y|all)(-\w+)?\.json$/.test(p),
    cc: 'public, max-age=3600',
  },
  // 6) 兜底：private+每次验证（未知路径不应被 CF 边缘缓存）
  { match: () => true, cc: 'private, no-cache, must-revalidate' },
];

function cacheControlFor(pathname) {
  for (const r of CACHE_RULES) if (r.match(pathname)) return r.cc;
  return 'private, no-cache, must-revalidate';
}

// /r2/* 代理路由（P0-4 2026-08-08）：R2 binding 直读 + Cache API 边缘缓存 1h。
// 原直链 ssd.fx8.store（R2 public bucket）cf-cache-status DYNAMIC 每次回源 ~1s；
// 改走 Worker 代理后二次请求边缘 HIT ~50ms。R2 key = pathname 去掉 /r2/ 前缀。
// 缓存 key 用 pathname（剥离 ?_=Date.now() cache-bust），让带 query 的请求也命中边缘缓存。
// 所有走 R2 的数据（大range 历史/etf_score/index/industry/lab/public_fund/fund_score/trade_sim）
// 均为收盘后低频更新，1h 边缘缓存安全。
async function r2ProxyHandler(request, env, ctx, url) {
  const key = decodeURIComponent(url.pathname.slice(4)); // 去掉 "/r2/"
  if (!key || key.endsWith('/')) {
    return new Response('Not Found', { status: 404 });
  }
  // 1. 边缘缓存命中（key 用 pathname 剥离 query，?_=Date.now() 不影响命中）
  const cacheKey = new Request(url.origin + url.pathname);
  const cached = await caches.default.match(cacheKey);
  if (cached) return cached;
  // 2. R2 读取
  let object;
  try {
    object = await env.R2_BUCKET.get(key);
  } catch (e) {
    return new Response('R2 read error: ' + (e && e.message), { status: 502 });
  }
  if (!object) return new Response('Not Found', { status: 404 });
  // 3. 构造响应（边缘缓存 1h）
  const headers = new Headers();
  object.writeHttpMetadata(headers);
  headers.set('etag', object.httpEtag);
  headers.set('Cache-Control', 'public, max-age=3600');
  for (const [k, v] of Object.entries(SECURITY_HEADERS)) headers.set(k, v);
  const response = new Response(object.body, { headers });
  // 4. 写边缘缓存（后台，不阻塞响应）
  ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
  return response;
}

// /data/*.json -> R2 rewrite（阶段2 2026-08-08）：数据层全走 R2 binding，前端 URL 0 改动。
// 截获 /data/*.json 请求，R2 key = pathname.slice(1)（如 "data/overview.json"）。
// R2 404 回退 ASSETS（静态文件兜底，如 fund_score_top.json R2 key 在 fund_score/ 前缀）。
// Cache API 边缘缓存 + 分层 TTL + /api/purge-cache 主动清除（上传新数据后调）。
// 和 /r2/ 代理区分：/data/ 是前端原生 URL rewrite（0 改动），/r2/ 保留给大 range 直链。
function dataCacheTtl(pathname) {
  // HIGH_FREQ 60s：盘中高频更新（overview/intraday_snapshot/boot/notifications/summary 等）
  if (/^\/data\/(?:overview|intraday_snapshot|boot|notifications|summary|summary_history|schedule_stats|alert)\.json$/.test(pathname)) return 60;
  // HIGH_FREQ 60s：盘中 15min 更新的 K 线小周期（-1m/-3m/-6m/-1y）
  if (/-(?:1m|3m|6m|1y)\.json$/.test(pathname)) return 60;
  // HIGH_FREQ 60s：其他盘中实时数据
  if (/^\/data\/(?:futures|ad_line|new_high_low|position|rotation|volume_ratio|ma_alignment|signal_freq|etf_national_team_holders|etf_national_team_quarterly|global-extras-all)\.json$/.test(pathname)) return 60;
  // MED_FREQ 600s：每日更新（signal_stats/futures_acc_*/fund_score_top/trade_sim_indices）
  if (/^\/data\/(?:signal_stats|futures_acc_trend|futures_acc_conclusion|fund_score_top|trade_sim_indices)\.json$/.test(pathname)) return 600;
  // LOW_FREQ 3600s：历史低频（收盘后更新一次）
  return 3600;
}

async function dataRewriteHandler(request, env, ctx, url) {
  const pathname = url.pathname;
  const key = decodeURIComponent(pathname.slice(1)); // "/data/overview.json" -> "data/overview.json"
  // 1. 边缘缓存命中（key 用 pathname 剥离 query，?_=Date.now() 不影响命中）
  const cacheKey = new Request(url.origin + pathname);
  const cached = await caches.default.match(cacheKey);
  if (cached) return cached;
  // 2. R2 读取，404/错误回退 ASSETS（静态文件兜底）
  let response;
  try {
    const object = await env.R2_BUCKET.get(key);
    if (object) {
      const headers = new Headers();
      object.writeHttpMetadata(headers);
      headers.set('etag', object.httpEtag);
      const ttl = dataCacheTtl(pathname);
      headers.set('Cache-Control', `public, max-age=${ttl}`);
      for (const [k, v] of Object.entries(SECURITY_HEADERS)) headers.set(k, v);
      response = new Response(object.body, { headers });
    }
  } catch (e) {
    // R2 错误，下面回退 ASSETS
  }
  if (!response) {
    // R2 404 或错误：回退 ASSETS 静态文件（如 fund_score_top.json R2 key 在 fund_score/ 前缀）
    const assetsResponse = await env.ASSETS.fetch(request);
    const headers = new Headers(assetsResponse.headers);
    const ttl = dataCacheTtl(pathname);
    headers.set('Cache-Control', `public, max-age=${ttl}`);
    for (const [k, v] of Object.entries(SECURITY_HEADERS)) headers.set(k, v);
    response = new Response(assetsResponse.body, {
      status: assetsResponse.status,
      statusText: assetsResponse.statusText,
      headers,
    });
  }
  // 3. 写边缘缓存（后台，不阻塞响应；只缓存 200 响应）
  if (response.status === 200) {
    ctx.waitUntil(caches.default.put(cacheKey, response.clone()));
  }
  return response;
}

// POST /api/purge-cache：主动清 CF 边缘缓存（upload_r2.py 上传新数据后调）。
// body: { secret: "xxx", keys: ["/data/overview.json", ...] }
// 遍历 keys 调 caches.default.delete，让前端下次请求回源 R2 拿最新数据。
async function purgeCacheHandler(request, env, url) {
  if (request.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405 });
  }
  let body;
  try {
    body = await request.json();
  } catch {
    return Response.json({ error: 'Invalid JSON' }, { status: 400 });
  }
  if (!body.secret || body.secret !== env.PURGE_SECRET) {
    return Response.json({ error: 'Forbidden' }, { status: 403 });
  }
  const keys = Array.isArray(body.keys) ? body.keys : [];
  let purged = 0;
  for (const keyPath of keys) {
    const cacheKey = new Request(url.origin + keyPath);
    await caches.default.delete(cacheKey);
    purged++;
  }
  return Response.json({ purged, total: keys.length });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    // /r2/* 路由：R2 对象代理 + Cache API 边缘缓存（P0-4）
    if (url.pathname.startsWith('/r2/')) {
      return r2ProxyHandler(request, env, ctx, url);
    }
    // /api/purge-cache：主动清边缘缓存（阶段2，上传新数据后调）
    if (url.pathname === '/api/purge-cache') {
      return purgeCacheHandler(request, env, url);
    }
    // /api/* 路由分发（生产无 FastAPI：/api/auth/* 与 /api/feedback* -> authHandler 复用 session 认证，其余 /api/* -> subscribeHandler）
    if (url.pathname.startsWith('/api/')) {
      if (url.pathname.startsWith('/api/auth/') || url.pathname.startsWith('/api/feedback')) {
        return authHandler(request, env);
      }
      return subscribeHandler(request, env);
    }
    // /data/*.json -> R2 rewrite（阶段2：数据层全走 R2 binding，前端 URL 0 改动）
    if (url.pathname.startsWith('/data/') && url.pathname.endsWith('.json')) {
      return dataRewriteHandler(request, env, ctx, url);
    }
    // /feed.xml -> /data/feed.xml 内部重写（RSS 阅读器兼容 /feed.xml 约定路径）
    // feed.xml 实际在 static-site/data/feed.xml，/feed.xml 不对应任何静态文件。
    // 内部重写（非 301 redirect）让 /feed.xml 直接返回 200 + feed 内容。
    let assetRequest = request;
    if (url.pathname === '/feed.xml') {
      assetRequest = new Request(new URL('/data/feed.xml', url), request);
    }
    const response = await env.ASSETS.fetch(assetRequest);
    // 复制原响应 headers（保留 ETag / Content-Type / CF-Cache-Status 等），覆盖 Cache-Control，附加安全头
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', cacheControlFor(url.pathname));
    for (const [k, v] of Object.entries(SECURITY_HEADERS)) headers.set(k, v);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};
