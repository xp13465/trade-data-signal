/*
 * tdsignal Service Worker — A6 PWA
 * 策略:
 *  - 静态资源 (CSS/JS/图标/manifest): stale-while-revalidate (缓存优先, 后台更新)
 *  - 导航请求 (index.html): network-first (保证 HTML 最新, 离线回退缓存)
 *  - 动态数据 JSON (/data/*.json): network-first (保证用户看到最新数据, 离线回退缓存)
 * 版本号破缓存: 改 CACHE_VERSION 即可让所有客户端清旧缓存
 */
const CACHE_VERSION = 'v1-20260720-a6';
const CACHE_NAME = 'tdsignal-' + CACHE_VERSION;
const PRECACHE_URLS = [
  './',
  './index.html',
  './style.min.css',
  './app.min.js',
  './common.min.js',
  './manifest.json',
  './favicon.svg',
  './icon-192.png',
  './icon-512.png',
  './apple-touch-icon.png'
];

// install: 预缓存关键静态资源 (个别失败不阻塞整体)
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      Promise.all(
        PRECACHE_URLS.map((url) =>
          cache.add(url).catch((err) => {
            console.warn('[sw] precache miss:', url, err.message);
          })
        )
      )
    ).then(() => self.skipWaiting())
  );
});

// activate: 清旧版本缓存, 接管客户端
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

// fetch: 按资源类型路由
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // 跨域请求不拦截 (百度统计 / echarts CDN / og 图等)
  if (url.origin !== self.location.origin) return;

  // 1) 动态数据 JSON: network-first (最新数据优先, 离线回退缓存)
  if (url.pathname.startsWith('/data/') || url.pathname.endsWith('.json')) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() =>
          caches.match(req).then(
            (cached) =>
              cached ||
              new Response('{"error":"offline"}', {
                headers: { 'Content-Type': 'application/json' }
              })
          )
        )
    );
    return;
  }

  // 2) 导航请求 (HTML): network-first (保证 HTML 最新, 离线回退缓存的 index.html)
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match('./index.html').then((cached) => cached || caches.match(req)))
    );
    return;
  }

  // 3) 静态资源 (CSS/JS/图标): stale-while-revalidate (缓存优先, 后台拉新版更新)
  event.respondWith(
    caches.match(req).then((cached) => {
      const fetchPromise = fetch(req)
        .then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
          }
          return res;
        })
        .catch(() => cached);
      return cached || fetchPromise;
    })
  );
});
