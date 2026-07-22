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
  window._hmt = window._hmt || [];
  (function () {
    var hm = document.createElement('script');
    hm.src = 'https://hm.baidu.com/hm.js?e1d50bf3c782798dd0c0515a14b1a48c';
    var s = document.getElementsByTagName('script')[0];
    s.parentNode.insertBefore(hm, s);
  })();

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

  // ---- 3. 百度站长 (zz.bdstatic.com) ----
  // 原 index.html L168-175 内联块
  (function () {
    var bp = document.createElement('script');
    bp.src = 'https://zz.bdstatic.com/linksubmit/push.js';
    var s = document.getElementsByTagName('script')[0];
    s.parentNode.insertBefore(bp, s);
  })();
})();
