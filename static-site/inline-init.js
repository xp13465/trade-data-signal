/*!
 * inline-init.js - 外部化的原 index.html 内联初始化脚本
 * 包含三段（按执行顺序）：
 *   1. 百度统计（hm.baidu.com） - 第三方统计，可延后加载
 *   2. 导航吸顶状态（navSticky） - 读 localStorage 给 <html> 加 class
 *   3. 百度站长（zz.bdstatic.com） - 第三方收录推送，可延后加载
 *
 * 原内联位置：index.html <head> 中（hm.baidu、navSticky）+ </body> 前（zz.bdstatic）
 * 现统一抽到外部文件，用 <script defer> 引用。
 * 注意：theme 防闪烁脚本仍保留内联（对时序敏感，外部化有 FOUC 风险）。
 */
(function () {
  'use strict';

  // ---- 1. 百度统计 (hm.baidu.com) ----
  // 原 index.html L32-40 内联块
  // C8③: 空队列初始化保留在立即段(零网络开销的 canonical 契约,防早期 _hmt.push 丢失);
  //       真正注入 hm.js 的 IIFE 已延后到 load/idle(见文件末 _injectStats)
  window._hmt = window._hmt || [];

  // ---- 2. 导航吸顶开关状态（防闪烁） ----
  // 原 index.html L55-66 内联块
  // body 渲染前读 localStorage 提前加 class 避免闪烁
  // 注：外部化后由 <script defer> 在 HTML 解析完成后、DOMContentLoaded 前执行
  //     仍早于首屏可见渲染，flash 风险低
  (function () {
    try {
      var ts = parseInt(localStorage.getItem('navStickyOff_ts'), 10);
      if (ts && Date.now() - ts < 24 * 3600 * 1000) {
        document.documentElement.classList.add('nav-no-sticky');
      } else if (ts) {
        localStorage.removeItem('navStickyOff_ts');
      }
    } catch (e) {}
  })();

  // ---- 3. 第三方统计/收录脚本延后注入（C8③） ----
  // ① 百度统计 (hm.baidu.com) + ③ 百度站长 (zz.bdstatic.com)
  // 目的:两段均为第三方网络请求,延后到 load 之后 + 浏览器空闲时执行,
  //       不抢占首屏解析/渲染资源。src 与参数与改前逐字相同,仅改注入时机。
  // 策略:load 触发后走 requestIdleCallback(timeout=2000) 空闲执行;
  //       执行时若 load 已触发(readyState==='complete',如缓存/极快场景)直接调度不等待事件;
  //       无 rIC 时由 setTimeout 兜底。
  function _injectStats() {
    // 原 index.html L32-40 内联块的 script 注入部分
    (function () {
      var hm = document.createElement('script');
      hm.src = 'https://hm.baidu.com/hm.js?e1d50bf3c782798dd0c0515a14b1a48c';
      var s = document.getElementsByTagName('script')[0];
      s.parentNode.insertBefore(hm, s);
    })();
    // 原 index.html L168-175 内联块
    (function () {
      var bp = document.createElement('script');
      bp.src = 'https://zz.bdstatic.com/linksubmit/push.js';
      var s = document.getElementsByTagName('script')[0];
      s.parentNode.insertBefore(bp, s);
    })();
  }

  function _scheduleStats() {
    if (typeof requestIdleCallback === 'function') {
      requestIdleCallback(_injectStats, { timeout: 2000 });
    } else {
      setTimeout(_injectStats, 0);
    }
  }

  if (document.readyState === 'complete') {
    _scheduleStats();
  } else {
    window.addEventListener('load', _scheduleStats, { once: true });
  }

  // ============================================================
  // #327 前端错误上报（2026-10-31, 纯新增）
  //   1% 采样 → navigator.sendBeacon('/api/err', ...) 异步不阻塞首屏
  //   单 tab 去重上限 5 条（sessionStorage 记已报 key, 防刷屏）
  //   字段: message/filename/lineno/colno/stack(截断2000)/build_id/UA/pathname/tab/ts
  //   防循环: 上报本身 try/catch, 出错静默不再报
  //   隐私: 不采 cookie/输入/查询参数
  //   Worker 端 /api/err: KV 计数 + R2 样本（详见 worker/err_report.js）
  // ============================================================
  (function () {
    var SAMPLE_RATE = 0.01;            // 1% 采样（D2 拍板）
    var DEDUP_MAX = 5;                  // 单 tab 同 (message+filename) 去重上限
    var STACK_MAX = 2000;
    var _inFlight = false;              // 防循环: 上报进行中再抛错不再报
    var _dedupKey = 'feErrSentKeys';

    function _buildId() {
      try {
        var meta = document.querySelector('meta[name="build-id"]');
        if (meta && meta.content) return String(meta.content);
      } catch (e) {}
      return '';
    }

    function _loadDedupSet() {
      try {
        var raw = sessionStorage.getItem(_dedupKey);
        if (!raw) return { keys: [], set: {} };
        var arr = JSON.parse(raw);
        if (!Array.isArray(arr)) return { keys: [], set: {} };
        var s = {};
        for (var i = 0; i < arr.length; i++) s[arr[i]] = true;
        return { keys: arr, set: s };
      } catch (e) {
        return { keys: [], set: {} };
      }
    }

    function _markDedup(dedup, key) {
      try {
        dedup.set[key] = true;
        dedup.keys.push(key);
        while (dedup.keys.length > DEDUP_MAX) {
          var old = dedup.keys.shift();
          delete dedup.set[old];
        }
        sessionStorage.setItem(_dedupKey, JSON.stringify(dedup.keys));
      } catch (e) {}
    }

    function _trunc(s, max) {
      if (typeof s !== 'string') return '';
      return s.length > max ? s.slice(0, max) : s;
    }

    function _send(payload) {
      if (_inFlight) return;            // 防循环
      try {
        _inFlight = true;
        var body = JSON.stringify(payload);
        if (navigator && typeof navigator.sendBeacon === 'function') {
          navigator.sendBeacon('/api/err', body);
        }
      } catch (e) {
        // 上报本身出错: 静默, 不再抛
      } finally {
        _inFlight = false;
      }
    }

    function _report(kind, ev) {
      try {
        // 1% 采样（一次性判定, 同 tab 内每条独立采样）
        if (Math.random() >= SAMPLE_RATE) return;
        var message = '';
        var filename = '';
        var lineno = 0;
        var colno = 0;
        var stack = '';
        if (kind === 'error') {
          // window.onerror: ev = (msg, src, lineno, colno, err)
          message = String(ev && ev[0] || '');
          filename = String(ev && ev[1] || '');
          lineno = (ev && ev[2]) || 0;
          colno = (ev && ev[3]) || 0;
          var errObj = ev && ev[4];
          if (errObj && errObj.stack) stack = String(errObj.stack);
        } else if (kind === 'unhandledrejection') {
          // ev = PromiseRejectionEvent, ev.reason
          var reason = ev && ev.reason;
          message = (reason && (reason.message || String(reason))) || 'unhandledrejection';
          stack = (reason && reason.stack) ? String(reason.stack) : '';
          filename = (reason && reason.fileName) ? String(reason.fileName) : '';
          lineno = (reason && reason.lineNumber) || 0;
        }
        if (!message) return;
        var key = String(message).slice(0, 100) + '|' + String(filename).slice(0, 100);
        var dedup = _loadDedupSet();
        if (dedup.set[key]) return;     // 单 tab 同源已报过, 不刷屏
        _markDedup(dedup, key);
        _send({
          message: _trunc(message, 500),
          filename: _trunc(filename, 500),
          lineno: lineno,
          colno: colno,
          stack: _trunc(stack, STACK_MAX),
          build_id: _buildId(),
          ua: _trunc(navigator.userAgent || '', 300),
          pathname: _trunc(location.pathname || '', 200),
          tab: _trunc((sessionStorage.tabId || ''), 64),
          ts: new Date().toISOString(),
        });
      } catch (e) {
        // 兜底防循环
      }
    }

    try {
      if (window.addEventListener) {
        window.addEventListener('error', function () {
          _report('error', arguments);
        });
        window.addEventListener('unhandledrejection', function (ev) {
          _report('unhandledrejection', ev);
        });
      } else if (window.attachEvent) {
        // IE 兜底（项目实际不需, 留作纯新增防御）
        window.attachEvent('onerror', function () { _report('error', arguments); });
      }
    } catch (e) {}
  })();

  // ============================================================
  // #327 BUILD_ID 收敛（2026-10-31, 纯新增, 双路径）
  //   构建期 bump_asset_version.py 写两处同值: index.html <meta name="build-id"> + __build.json
  //   本段: 空闲时 fetch('/__build.json', {cache:'no-store'}) 比对 meta build-id,
  //         不一致 + 用户空闲 5s 无交互 + 探活 app.min.js 就绪 → location.reload()
  //   SW_UPDATED 提示（app.js + #sw-update-toast）保留不变, 本段是兜底（用户不点）
  //   红线: 禁裸 reload（必须探活核心 JS 就绪, 防 8-14 白屏 §24 防撕裂）
  // ============================================================
  (function () {
    var IDLE_DELAY_MS = 5000;           // 用户空闲 5s 才考虑 reload
    var PROBE_TIMEOUT_MS = 8000;        // 探活单次 fetch 上限
    var CHECK_DELAY_MS = 5000;          // 启动后首次比对延后 5s（不抢首屏）
    var autoReloadOff = false;
    try {
      autoReloadOff = localStorage.getItem('feAutoReloadOff') === '1';
    } catch (e) {}

    function _metaBuildId() {
      try {
        var m = document.querySelector('meta[name="build-id"]');
        return m && m.content ? String(m.content) : '';
      } catch (e) { return ''; }
    }

    // 探活核心 JS: HEAD no-store, 复用 sw.js:124 isCoreShellReady 思路（核心壳就绪才接管）
    //   返 true 表示核心 JS 可达（status 200 且 Content-Type 为 JS）, 才允许 reload。
    //   返 false / 失败 / 超时 → 不 reload（避免 reload 后拿不到核心 JS 致白屏）。
    function _probeCoreReady() {
      return new Promise(function (resolve) {
        var done = false;
        var timer = setTimeout(function () {
          if (done) return; done = true; resolve(false);
        }, PROBE_TIMEOUT_MS);
        try {
          // 探活 app.min.js（首屏渲染 JS, 缺=全白; 与 sw.js CORE_SHELL_URLS 同口径）
          fetch('./app.min.js', { method: 'HEAD', cache: 'no-store' }).then(function (res) {
            if (done) return; done = true;
            clearTimeout(timer);
            var ok = !!(res && res.status === 200);
            var ct = (res && res.headers && res.headers.get('content-type')) || '';
            if (ok && /javascript/i.test(ct)) resolve(true);
            else resolve(false);
          }).catch(function () {
            if (done) return; done = true; clearTimeout(timer); resolve(false);
          });
        } catch (e) {
          if (done) return; done = true; clearTimeout(timer); resolve(false);
        }
      });
    }

    function _reload() {
      try { location.reload(); } catch (e) {}
    }

    // 空闲判定: requestIdleCallback(timeout) 或 setTimeout 兜底 + 最近交互重置
    //   用户最近 5s 内有交互（pointerdown/keydown）则不 reload（不打断）
    var _lastInteractTs = Date.now();
    function _markInteract() { _lastInteractTs = Date.now(); }
    try {
      ['pointerdown', 'keydown', 'touchstart'].forEach(function (ev) {
        document.addEventListener(ev, _markInteract, { passive: true });
      });
    } catch (e) {}

    function _idleEnough() {
      return (Date.now() - _lastInteractTs) >= IDLE_DELAY_MS;
    }

    function _scheduleIdle(cb) {
      if (typeof requestIdleCallback === 'function') {
        requestIdleCallback(function () { cb(); }, { timeout: IDLE_DELAY_MS + PROBE_TIMEOUT_MS + 5000 });
      } else {
        setTimeout(cb, IDLE_DELAY_MS);
      }
    }

    function _check() {
      if (autoReloadOff) return;
      var metaBid = _metaBuildId();
      if (!metaBid) return;              // meta 未注入（旧版部署/构建期未写）→ 不比对, 不 reload
      var fetchBid = '';
      try {
        fetch('/__build.json', { cache: 'no-store' }).then(function (res) {
          if (!res || res.status !== 200) return null;
          return res.json();
        }).then(function (data) {
          if (!data || typeof data !== 'object') return;
          fetchBid = String(data.build_id || '');
          if (!fetchBid) return;
          if (fetchBid === metaBid) return;   // 一致, 无操作
          // 不一致 → 空闲 + 探活就绪才 reload
          _scheduleIdle(function () {
            if (autoReloadOff) return;
            if (!_idleEnough()) return;       // 用户刚交互过, 等下次空闲（不 reload）
            _probeCoreReady().then(function (ok) {
              if (ok) _reload();
              // 探活未就绪 → 不 reload（避免白屏）, 等下次空闲重试
            });
          });
        }).catch(function () {
          // __build.json fetch 失败（断网/部署中）→ 无操作（不 reload 不报错）
        });
      } catch (e) {}
    }

    // 启动后延后比对（不抢首屏）
    try {
      setTimeout(_check, CHECK_DELAY_MS);
    } catch (e) {}
  })();
})();
