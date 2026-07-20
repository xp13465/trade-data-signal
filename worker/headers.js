// Workers Static Assets: Worker 接管 response headers，实现 last-wins 覆盖 + 缓存分层。
// run_worker_first=true 时 _headers 文件不生效，所有 headers 在此统一设置。
// 部署：push main 后 Cloudflare Builds 跑 wrangler deploy，内置 esbuild 自动 bundle 本文件。

// 安全头（原 _headers /* 块内容，对非 HTML 响应浏览器自动忽略，无副作用）
const SECURITY_HEADERS = {
  'Strict-Transport-Security': 'max-age=63072000; includeSubDomains; preload',
  'X-Content-Type-Options': 'nosniff',
  'X-Frame-Options': 'SAMEORIGIN',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=(), payment=(), usb=(), accelerometer=(), gyroscope=()',
  "Content-Security-Policy-Report-Only": "default-src 'self'; script-src 'self' 'unsafe-inline' https://hm.baidu.com https://zz.bdstatic.com https://push.zhanzhang.baidu.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https://web.ifzq.gtimg.cn https://hm.baidu.com; frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'",
};

// 有序规则：第一条匹配的生效（first-match-wins = 精确/具体优先，兜底放最后）。
// pathname 不含 query，故 ?v=xxxx 破缓存参数不影响匹配。
const CACHE_RULES = [
  // 1) 版本化静态资源：1 年 immutable（改动靠 ?v= 换 URL 破缓存）
  {
    match: p => /^\/(style\.css|app\.min\.js|lab\.min\.js|lab\.css|qr\.js)$/.test(p) || p.startsWith('/vendor/'),
    cc: 'public, max-age=31536000, immutable',
  },
  // 2) 实时数据 / HTML 入口：每次验证
  {
    match: p =>
      p === '/' || p === '/index.html' ||
      /^\/trade_sim_/.test(p) ||
      p === '/data/futures.json' || p === '/data/ad_line.json' || p === '/data/feed.xml' ||
      p.startsWith('/data/index/') || p.endsWith('-1m.json'),
    cc: 'no-cache, must-revalidate',
  },
  // 3) 历史 K 线(3m/6m/1y/3y)：1 小时
  {
    match: p => /-(3m|6m|1y|3y)\.json$/.test(p),
    cc: 'public, max-age=3600',
  },
  // 4) 全量 / 长周期(5y / all) + 策略实验室 + 行业拆分目录：6 小时
  {
    match: p =>
      p.startsWith('/data/lab/') ||
      p.startsWith('/data/industry-all-indices/') ||
      p.startsWith('/data/industry-5y-indices/') ||
      /-(5y|all)(-\w+)?\.json$/.test(p),
    cc: 'public, max-age=21600',
  },
  // 5) 兜底：每次验证
  { match: () => true, cc: 'no-cache, must-revalidate' },
];

function cacheControlFor(pathname) {
  for (const r of CACHE_RULES) if (r.match(pathname)) return r.cc;
  return 'no-cache, must-revalidate';
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const response = await env.ASSETS.fetch(request);
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
