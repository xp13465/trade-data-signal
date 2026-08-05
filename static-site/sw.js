/*
 * tdsignal Service Worker - A6 PWA
 *
 * 缓存策略(任务约束):
 *  1. App Shell (HTML/CSS/JS/vendor/图标/manifest): CacheFirst
 *     - 关键静态资源预缓存,离线可用
 *     - 改 CACHE_VERSION 清旧缓存,skipWaiting+clients.claim 立即接管,提示用户刷新拿新版
 *  2. 数据 JSON (除 intraday_snapshot): network-first (正确性优先, 失败回退缓存)
 *     - 2026-08-02 改: 原走 SWR 先返旧缓存后台拉新版, 低频数据(季频 public_fund_* /etf_score_list)更新后用户仍拿旧缓存
 *     - 改 network-first 每次走网络拿最新, 离线/失败回退缓存(牺牲毫秒延迟换正确性)
 *  3. intraday_snapshot.json + notifications.json: NetworkFirst (盘中实时性优先,离线回退缓存)
 *  4. 第三方 (hm.baidu/zz.bdstatic/echarts CDN 等): 跨域不拦截,直接走网络,不缓存
 *
 * 版本号破缓存: 改 CACHE_VERSION 即可让所有客户端清旧缓存 + 提示刷新
 */
const CACHE_VERSION = 'v2-20260805p-spark-help-highlow';
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

  // 2) 其他数据 JSON (非 intraday): network-first (正确性优先, 失败回退缓存)
  //    2026-08-02 修复: 原走 SWR 3min 先返旧缓存后台拉新版, 低频数据(季频 public_fund_*/etf_score_list)
  //    更新后用户仍可能拿到旧缓存(SWR 后台 fetch 也可能命中 CF edge 旧版)。改 network-first 每次走网络拿最新,
  //    离线/网络失败才回退缓存。牺牲毫秒级延迟换数据正确性(数据更新第一时间反映)。
  if (url.pathname.startsWith('/data/') || url.pathname.endsWith('.json')) {
    event.respondWith(networkFirstJson(req));
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

// ============== networkFirstJson: 优先网络拿最新, 失败回退缓存(离线兜底) ==============
// 用于 /data/ JSON: 低频数据(季频/日频)正确性优先, 不返回旧缓存。
// fetch 加 cache:'no-store' 避免命中浏览器 HTTP/CF 缓存拉旧数据(与 intraday/overview 同模式)。
// 成功写入缓存供离线兜底; 失败回退缓存, 缓存也无则返 offline 占位。
function networkFirstJson(req) {
  return fetch(req, { cache: 'no-store' })
    .then((res) => {
      if (res && res.status === 200) {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
      }
      return res;
    })
    .catch(() => caches.match(req).then((cached) => cached ||
      new Response('{"error":"offline"}', { headers: { 'Content-Type': 'application/json' } })
    ));
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
    const { title, body, tag, data, failClearKeys } = event.data.payload || {};
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
        // 回传 NOTIFY_FAILED 到所有 client: 清除已弹标记+时间窗,下次轮询重试(防死锁漏通知)
        const keys = Array.isArray(failClearKeys) ? failClearKeys : [];
        self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
          clientList.forEach(c => c.postMessage({ type: 'NOTIFY_FAILED', tag, failClearKeys: keys }));
        });
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
