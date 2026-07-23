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
  "Content-Security-Policy-Report-Only": "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://hm.baidu.com https://zz.bdstatic.com https://push.zhanzhang.baidu.com https://static.cloudflareinsights.com; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https://web.ifzq.gtimg.cn https://hm.baidu.com https://ssd.fx8.store; frame-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'",
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
      p === '/data/feed.xml',
    cc: 'no-store, max-age=0',
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
  // 4) 指数/行业拆分目录：10 分钟（对齐 GitHub Pages sss.sugas.site max-age=600）
  //    deploy 后 CF edge 缓存 1h 致数据滞后，改 600s 与 GH Pages 对齐根治滞后。
  {
    match: p => p.startsWith('/data/index/'),
    cc: 'public, max-age=600',
  },
  // 5) 历史 K线/全量/长周期 + 策略实验室 + 行业3y/5y/all-indices：1 小时
  //    这些每天收盘才更新一次，1h 缓存既省回源又保证当日数据最迟 1h 内刷到 CDN。
  {
    match: p =>
      p.startsWith('/data/lab/') ||
      p.startsWith('/data/industry-3y-indices/') ||
      p.startsWith('/data/industry-5y-indices/') ||
      p.startsWith('/data/industry-all-indices/') ||
      /-(3m|6m|1y|3y|5y|all)(-\w+)?\.json$/.test(p),
    cc: 'public, max-age=3600',
  },
  // 6) 兜底：private+每次验证（未知路径不应被 CF 边缘缓存）
  { match: () => true, cc: 'private, no-cache, must-revalidate' },
];

function cacheControlFor(pathname) {
  for (const r of CACHE_RULES) if (r.match(pathname)) return r.cc;
  return 'private, no-cache, must-revalidate';
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
