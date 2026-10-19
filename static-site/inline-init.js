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
})();
