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
// 缓存分层原则：版本化 JS/CSS 1 年 immutable（靠 ?v= 换 URL 破缓存）；
//   HTML 入口 no-cache（每次验证）；实时数据 60s（分钟级刷新）；纯历史 1h（每天收盘才更新）。
const CACHE_RULES = [
  // 1) 版本化静态资源：1 年 immutable（改动靠 ?v= 换 URL 破缓存）
  {
    match: p => /^\/(style\.css|app\.min\.js|lab\.min\.js|lab\.css|qr\.js)$/.test(p) || p.startsWith('/vendor/'),
    cc: 'public, max-age=31536000, immutable',
  },
  // 2) HTML 入口 / feed / trade_sim：每次验证
  {
    match: p =>
      p === '/' || p === '/index.html' ||
      /^\/trade_sim_/.test(p) ||
      p === '/data/feed.xml',
    cc: 'no-cache, must-revalidate',
  },
  // 3) 实时数据 JSON（盘中/每日更新，需分钟级刷新）：60 秒
  //    global-extras-all 含 usdcnh 等实时指标，必须在历史规则前命中，否则会被 -all 匹配到 1h 致滞后。
  {
    match: p =>
      p === '/data/futures.json' || p === '/data/ad_line.json' ||
      p === '/data/summary.json' || p === '/data/overview.json' ||
      p === '/data/global-extras-all.json' || p === '/data/intraday_snapshot.json' ||
      p === '/data/new_high_low.json' || p === '/data/position.json' ||
      p === '/data/rotation.json' || p === '/data/volume_ratio.json' ||
      p === '/data/ma_alignment.json' || p === '/data/signal_freq.json' ||
      p === '/data/schedule_stats.json' || p === '/data/summary_history.json' ||
      p === '/data/etf_national_team_holders.json' || p === '/data/etf_national_team_quarterly.json' ||
      p.endsWith('-1m.json'),
    cc: 'public, max-age=60',
  },
  // 4) 历史 K线/全量/长周期 + 策略实验室 + 指数/行业拆分目录：1 小时
  //    这些每天收盘才更新一次，1h 缓存既省回源又保证当日数据最迟 1h 内刷到 CDN。
  {
    match: p =>
      p.startsWith('/data/lab/') ||
      p.startsWith('/data/index/') ||
      p.startsWith('/data/industry-3y-indices/') ||
      p.startsWith('/data/industry-5y-indices/') ||
      p.startsWith('/data/industry-all-indices/') ||
      /-(3m|6m|1y|3y|5y|all)(-\w+)?\.json$/.test(p),
    cc: 'public, max-age=3600',
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
