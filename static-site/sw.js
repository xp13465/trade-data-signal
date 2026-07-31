/*
 * tdsignal Service Worker - A6 PWA
 *
 * 缓存策略(任务约束):
 *  1. App Shell (HTML/CSS/JS/vendor/图标/manifest): CacheFirst
 *     - 关键静态资源预缓存,离线可用
 *     - 改 CACHE_VERSION 清旧缓存,skipWaiting+clients.claim 立即接管,提示用户刷新拿新版
 *  2. 数据 JSON (除 intraday_snapshot): stale-while-revalidate (盘中 3 分钟刷)
 *     - 先返回缓存(毫秒级),后台拉新版更新缓存
 *     - 缓存 < 3 分钟直接返回缓存不发网络(省流量);>= 3 分钟后台拉新版
 *  3. intraday_snapshot.json + notifications.json: NetworkFirst (盘中实时性优先,离线回退缓存)
 *  4. 第三方 (hm.baidu/zz.bdstatic/echarts CDN 等): 跨域不拦截,直接走网络,不缓存
 *
 * 版本号破缓存: 改 CACHE_VERSION 即可让所有客户端清旧缓存 + 提示刷新
 */
const CACHE_VERSION = 'v2-20260731-sentiment-loading-ui16';
const CACHE_NAME = 'tdsignal-' + CACHE_VERSION;

// App Shell 关键资源预缓存(个别失败不阻塞整体)
const PRECACHE_URLS = [
  './',
  './index.html',
  './style.min.css',
  './app.min.js',
  './common.min.js',
  './purpose-notes.min.js',
  './qr.js',
  './manifest.json',
  './favicon.svg',
  './favicon.ico',
  './icon-192.png',
  './icon-512.png',
  './apple-touch-icon.png'
];

// App Shell 静态资源的文件扩展名(CacheFirst 适用)
const APP_SHELL_ASSET_PATTERN = /\.(?:css|js|svg|png|ico|woff2?|ttf|woff)$/i;

// 数据 JSON 缓存最大年龄(盘中 3 分钟刷)
const DATA_MAX_AGE_MS = 3 * 60 * 1000;

// ============== install: 预缓存 App Shell + skipWaiting ==============
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

// ============== activate: 清旧版本缓存 + clients.claim + 通知客户端刷新 ==============
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
      .then(() => self.clients.matchAll({ type: 'window', includeUncontrolled: true }))
      .then((clients) => {
        // 通知所有客户端: SW 已更新到新版本,可提示用户刷新
        clients.forEach((client) => {
          client.postMessage({ type: 'SW_UPDATED', version: CACHE_VERSION });
        });
      })
  );
});

// ============== fetch: 按资源类型路由 ==============
self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // 4) 跨域请求不拦截 (百度统计 hm.baidu / 百度站长 zz.bdstatic / echarts CDN 等)
  //    直接走浏览器默认网络栈,不缓存
  if (url.origin !== self.location.origin) return;

  // 3) intraday_snapshot.json + notifications.json + overview.json: NetworkFirst (盘中实时性优先,离线回退缓存)
  //    notifications.json 走 NetworkFirst（根因③修复）：原走 SWR 3min 缓存致前端读旧 notifications.json，
  //    真实信号触发后即使后端更新了前端也拿旧缓存不弹通知。改 NetworkFirst 每次走网络拿最新。
  //    overview.json 走 NetworkFirst（根因②修复）：原走 SWR 总先返旧缓存, 致盘中卡片等盘后才更新。
  //    改 NetworkFirst 确保每次拉最新 overview(卡片时间角标/collect_health 即时反映后端最新采集)。
  //    fetch 加 cache:'no-store'（根因①修复）：避免命中浏览器 HTTP/CF 缓存拉旧数据。
  if (url.pathname.endsWith('/intraday_snapshot.json') || url.pathname.endsWith('/notifications.json') || url.pathname.endsWith('/overview.json')) {
    event.respondWith(
      fetch(req, { cache: 'no-store' })
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(req).then((cached) => cached ||
          new Response('{"error":"offline"}', { headers: { 'Content-Type': 'application/json' } })
        ))
    );
    return;
  }

  // 2) 其他数据 JSON (非 intraday): stale-while-revalidate (盘中 3 分钟刷)
  if (url.pathname.startsWith('/data/') || url.pathname.endsWith('.json')) {
    event.respondWith(staleWhileRevalidate(req, DATA_MAX_AGE_MS));
    return;
  }

  // 1) App Shell 静态资源 (CSS/JS/vendor/图标): CacheFirst
  //    导航请求 (HTML) 也归入 CacheFirst (App Shell 模型);新版靠 CACHE_VERSION bump + 提示刷新
  if (req.mode === 'navigate' || APP_SHELL_ASSET_PATTERN.test(url.pathname)) {
    event.respondWith(cacheFirst(req));
    return;
  }

  // 其他同源 GET 请求: 默认走网络,失败回退缓存(兜底)
  event.respondWith(
    fetch(req, { cache: 'no-store' }).catch(() => caches.match(req).then((cached) => cached || Response.error()))
  );
});

// ============== CacheFirst: 缓存优先,无缓存才走网络 ==============
function cacheFirst(req) {
  return caches.match(req).then((cached) => {
    if (cached) return cached;
    return fetch(req, { cache: 'no-store' }).then((res) => {
      if (res && res.status === 200) {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
      }
      return res;
    });
  });
}

// ============== stale-while-revalidate: 先返回缓存,后台拉新版更新 ==============
// maxAgeMs: 缓存年龄 < maxAgeMs 直接返回缓存不发网络(省流量);>= maxAgeMs 返回缓存同时后台拉新版
function staleWhileRevalidate(req, maxAgeMs) {
  return caches.open(CACHE_NAME).then((cache) =>
    cache.match(req).then((cached) => {
      // 无缓存: 必须等网络
      if (!cached) {
        return fetch(req, { cache: 'no-store' }).then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            cache.put(req, copy).catch(() => {});
          }
          return res;
        }).catch(() =>
          new Response('{"error":"offline"}', { headers: { 'Content-Type': 'application/json' } })
        );
      }

      // 缓存年龄 < maxAgeMs: 直接返回缓存,不发网络(省流量)
      const cacheDate = cached.date || cached.headers.get('date');
      if (cacheDate) {
        const age = Date.now() - new Date(cacheDate).getTime();
        if (age < maxAgeMs) return cached;
      }

      // 缓存年龄 >= maxAgeMs 或无 date 头: 返回缓存同时后台拉新版更新(SWR)
      // 后台异步拉新版更新缓存(不阻塞返回)
      fetch(req, { cache: 'no-store' })
        .then((res) => {
          if (res && res.status === 200) {
            const copy = res.clone();
            cache.put(req, copy).catch(() => {});
          }
        })
        .catch(() => {});
      return cached;
    })
  );
}

// ============== message: 接收客户端消息 ==============
self.addEventListener('message', (event) => {
  // 客户端主动触发 skipWaiting (用户点击"立即刷新"按钮)
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
  // SHOW_NOTIFICATION: 客户端委托 SW 弹通知（Mac Chrome 下 SW showNotification 点击比页面 new Notification 可靠：
  // 页面失焦时 new Notification().onclick 链路丢失 -> 点击无响应；SW registration.showNotification + notificationclick 稳定）
  if (event.data && event.data.type === 'SHOW_NOTIFICATION') {
    const { title, body, tag, data } = event.data.payload || {};
    console.log('[sw] 收到SHOW_NOTIFICATION', title, '| tag=', tag);
    event.waitUntil(
      self.registration.showNotification(title || '', {
        body: body || '', tag: tag || undefined,
        icon: '/favicon.svg', badge: '/favicon.svg',
        requireInteraction: false, data: data || {},
      }).then(() => {
        console.log('[sw] showNotification 成功', title);
      }).catch((err) => {
        console.warn('[sw] showNotification 失败', err?.message || err, '| title=', title);
      })
    );
  }
});

// ============== notificationclick: 通知点击 -> 聚焦已有 tab + postMessage 触发页面 UI 反馈 ==============
self.addEventListener('notificationclick', (event) => {
  console.log('[sw] notificationclick 触发', '| data=', JSON.stringify(event.notification.data));
  event.notification.close();
  const notifData = event.notification.data || {};
  const msgType = notifData.msgType || 'NOTIFY_CLICK';
  const payload = notifData.payload || {};
  const hash = notifData.hash || '';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      console.log('[sw] matchAll 找到', clientList.length, '个client');
      let target = null;
      for (const c of clientList) {
        if (c.url.startsWith(self.location.origin)) {
          target = c;
          if (hash && c.url.includes(hash)) break;
        }
      }
      if (target) {
        console.log('[sw] focus+postMessage target', target.url);
        return target.focus().then(() => target.postMessage({ type: msgType, payload, hash }));
      }
      console.log('[sw] 无匹配client，openWindow', hash || '/');
      const openUrl = hash ? self.location.origin + '/' + hash : self.location.origin + '/';
      return self.clients.openWindow(openUrl);
    })
  );
});
