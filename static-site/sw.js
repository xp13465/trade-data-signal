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

const CACHE_VERSION = 'v6-20260814-a207';  // a206->a207 = 凯利降亏组合使用建议面板重构(2026-08-14, 纯前端lab.js+lab.css+purpose-notes+README): ①删除「4组合全开」折叠区(old fixed每笔1万口径过时)→标题去「4组合全开=可选」; ②总建议行G数字fixed错标改每日池口径(AI仓位建议K1主推 47.22%/+642,184, 按年2021 -23,500/2023 +60,645/2024 +225,894/2025 +151,405, 出处dailypool rerun §6) + 配套行「同口径可直接对比」矛盾句改口径差异说明; ③面板整体可收缩默认折叠(标题一行概览, open状态持久化state.labSigKellyAdviceOpen); ④G玩法三档标b0保守口径+口径说明去4组合全开残留; 布局复用现有advice/gmethod class样式美化; // a205->a206 = BC包 + 按年窗口口径归正(2026-08-14, 纯前端common.js+lab.js+app.js+purpose-notes+lab.css+README): ①B包 K评级佣金口径重算——静态快照 _AI_POSCAP_RATING 由比例法改费率重算扣最低佣金5元(每日池A模式 K1 86.60%/K2 67.61%/K3 66.24%/K4 63.17%, 消除12.67pt佣金低估§22, 与动态 _kellyApplyFeeRecompute 逐位一致); ②C包 默认K 3→1主推(_kellyDefaultFilters/_kellySharedPosCap/app.js _posCapK/重置/初始载入全链路, K按钮1342置顶+★主推高亮, tooltip/评级/对比/全信号/建议面板全同步); ③按年窗口口径归正: allYearly 仅累加 G 模式(原全9模式累加量级虚高, 对齐"总建议=遵守G模式卖出"语义, 表头标签标注G模式), 4组合全开静态按年表加口径标注; ④§21公示同步(purpose-notes.js)+README 同步; a204->a205 = 总建议板块融合 G 玩法完整交易方法(2026-08-14, 纯前端lab.js+lab.css): ②分投资习惯怎么用?总建议"②总建议"分节内新增 .lab-sigkelly-gmethod 教学区 G玩法三层流程: ①P≤3d"先卖年轻仓"最优仓位管理(白话说+12万持仓举例, 保老仓21-100天利润引擎砍新仓)②三档自选13万155.78%(净+202,508)/15万147.34%(净+221,016)/20万131.25%(净+262,509, 全部≤20倍本金可操作)③可信度=15起始年全超FIFO(均值98.9vs62.0)+随机30点0/30负+b0/b1区间窄(4-24pp)可信; with G分层流程; 与A/F维持默认7键并列清晰; lab.css加靛青左边框教学callout; a203->a204 = 凯利降亏过滤使用建议重写(2026-08-14, 纯前端lab.js+lab.css+purpose-notes): ①_fadeFlagGroups 31键 tip 改每日池口径白话+剔除fixed旧数字、"净增收+XX万"主口径清除, 加 advice(白话1句+ratio可见文本)/tip(ⓘ弹层完整detail)结构; ②4组合宏tip瘦身(去重复"可叠加OR幂等无害"+过期数字); ③_comboAdviceHtml 面板6.33pp改"与默认差异0.3-0.7pt"+加G模式分裂建议(A/F维持/A-F去g15等); ④布局重写=顶部"怎么用"三行汇总+默认推荐7键高亮独立块+非默认收"更多开关"折叠区, 星标+advice色块联动warn(绿推荐/黄监控/红慎用); ⑤purpose-notes 降亏段同步每日池口径+剔除过时口径; a202->a203 = 凯利AI报告区移页面尾部作历史留存(2026-08-14, 纯前端lab.js+lab.css): 用户定"AI报告版本已过时移页尾作历史留存"——整个 lab-sigkelly-ai-wrap(切换条+3AI新版[3ai-comparison+comprehensive+deepseek+claude-v4]+双AI历史[comparison+comprehensive+deepseek] 全部report块)从 wrapper 中部移到 host 之后页面最底, 加归档标注 .lab-sigkelly-ai-archive-title"📦历史AI报告存档(结论已过时·仅供回溯)"+灰虚边框弱化; 保留 3AI/双AI 切换/localStorage 记忆(lab_sigkelly_ai_mode)/KELLY_REVIEW_NOTES 内容原样; 全部版本无一遗漏俱移尾部; // a201->a202 = #25 bug修复(2026-08-14, 纯前端lab.js+lab.css+style.css): "ai长线开+淘汰文字看不清字"样式修复——①淘汰删除线行文字 var(--text-4)最淡灰改 var(--text-2)深灰可读+整行 opacity 0.55→0.85(不被压淡, 含红角标保持亮色); ②删 .lab-sigkelly-exec-badge 幽灵变量 var(--gih-el,未定义)用深红 #c62828+白字11px加粗+内白描边(原10px红底白字对比不足); ③水印 .lab-sigkelly-wm-cmp-noop 不再 opacity:0.5 整行压淡(会吞掉角标), 改只灰化文字色 var(--text-3), noop-badge 9px→10px 深红加粗; ④"AI长线·开" .lab-sigkelly-gih-badge 去 .lab-sigkelly-modelbl(display:block 致独占一行挤位), 独立 inline-block 11px加粗+紫底白字+白描边, dark/redgold 提亮紫#8b3ff0; ⑤GIH on cap 后记录不误标淘汰(已自测:GIH on G/H/I 行仅 AI长线·开 无删除线, GIH off 才标淘汰·无操作性) ; a200->a201 = #25 A包(2026-08-14, 纯前端lab.js+purpose-notes+lab.css): ①TOP1推荐算法修正——先可操作性(峰持仓≤20万)过滤再按收益率(return_pct_max_holding)排序, 不再按净盈亏(去F大净利压Abug, 新默认top1=A), GIH on读__gihb1; ②需求②GIH off不可操作(G/H/I未套20万硬控原始峰持仓>20倍)记录标"淘汰·无操作性"(删除线+角标+hoverpop+弹窗理由); ③需求D K档OFF(无仓位限制每笔1万全买峰持仓疯长)记录标"淘汰·无仓位限制·无法实操"; 统一_kellyOpElimination判据(峰持仓≤20万), 卡片行/全信号表/三玩法表/水印/弹窗同步(§23.3), purpose-notes §21公示同步, README同步; a199->a200 = docs路径整理(2026-08-14): docs/kelly-* 移入 docs/kelly/{mining,combo,position,backtest-ai,toggle,analysis}/, kelly-review-notes/lab/purpose-notes 内嵌文档链接路径同步, 仅注释/字符串变更无功能改动; a199 = #49 issue49 修复2用户反馈  // a198->a199 = #49 issue49 修复2用户反馈(2026-08-14, 纯前端lab.js): F1交互-对比表展开/收起独立于开关(_gihCompareOpen用户态, 开关change不再强制收起, 重渲染保开合); F2核心-开关无效修复(顶层缓存签名cacheKey拼入gih开关态, 7829, 否则短路径命中旧result无__gihb1→卡片恒显原始值); a198 = #49 ai长线仓位管理reviewer审查修复(2026-08-14, 纯前端): F1 _kellyMaxConcurrentCapital/_kellyMaxConcurrent 改【先减后加】(与仿真内核/后端_peak_capital同序, cap后峰值精确回20万/200.46%对齐报告§7.2, A-F基线从高估错误值收敛到后端口径如G 137万→136万, §22+§21); F2 水印/卡间对比过滤 mode+"__gihb0/b1/peak"伪模式键(防封面均值稀释排序错乱); F3 弹窗+三玩法表GIH ON加"未套硬控原始口径"诚实标注+CSS(gih-modal-note); a196->a197 = #49 ai长线模式(G/H/I)仓位管理(2026-08-14): 凯利回测区新增开关(长线族群总入口, 模式→策略映射 G/H/I v1 统一 fifo20w), G/H/I 套持仓≤20万+FIFO强制平最久持仓硬控, ON后卡片套乐观b1口径值+AI长线·开角标, 新增G/H/I对比表(关/开b0/开b1, 报告§7.2 K1参考口径), 前端FIFO仿真内核与报告逐位对齐§21, purpose-notes/README同步, style.css加角标徽标类; a195->a196 = #48 每日池口径重算页面(2026-08-14): _kellyFadeFlagGroups 31键 ratio 换每日池 ALL9 K1 + 组内重排 + tips 注明口径; _pcRating/_AI_POSCAP_RATING/首页 tooltip/purpose-notes/README A模式 K1-4 改每日池(86.60/74.93/78.91/79.96); common.js 回退+口径描述同步每日池; a194->a195 = 凯利回测金额口径恢复"每日资金池等分+top-K"(2026-08-13): 当日保留前K基笔每笔=10000/当日保留数, K档最大持仓恒定(~11万), 撤销fixed口径下K=3 33万异常; a193->a194 = AI降亏过滤详情默认收起(31个单标志toggle默认收起, 点按钮才展开); a192->a193 = 凯利降亏过滤 toggle 名称精简+去版本标识(#V4/A45/A5/J1/J2/R7/mid评级统一为白话名) + fix: _renderSigKellyCard 误删 periods 声明回归(#1); a191->a192 = 信号凯利回测页UI增强: 卡片置顶(全信号+16子域卡 localstorage 持久化, 已置顶区集中显示) + 默认推荐框内文字醒目(灰改金字加粗) + 默认推荐badge文案精简为"推荐"; a190->a191 = 首页实操验证与凯利回测 1:1 对齐(#60 方案A): 首页信号链路接入 #58 ETF 冻结表(queries.py 命中冻结标 _bk_top), 前端 _topEtfByScore 改纯 track_score 降序(去 stable_top1 滞回 + track_n>=90 启发), 首页 AI建议/标的 = 回测标的; a189->a190 = #54 hoverpop动态化(bug1总开关联动扩7键+badge降级+重置为AI默认推荐按钮) + 前端动态重算管线; a188->a189 = 凯利回测区AI仓位建议布局调整(删除第一行纯文字标题"AI仓位建议"去重 + AI降亏过滤总开关/详情按钮并入第一行跟在关OFF按钮后); a187->a188 = K档补文案(首页AI仓位建议K档 title 档位语义诚实标注, 默认K=3稳健档非收益率最优) + AI建议编号修复(序号改质量序=当日跟踪分降序第N, 不随K档跳变) 两分支合并(#48#49); a186->a187=AI建议编号改质量序; a185->a186=凯利AI降亏过滤区融合(#39/#45)+§22 K档口径同步; a184->a185=皮肤弹窗样式修复; 基底=a177
const CACHE_NAME = 'tdsignal-' + CACHE_VERSION;

// App Shell 关键资源预缓存(个别失败不阻塞整体)
const PRECACHE_URLS = [
  './',
  './index.html',
  './style.min.css',
  './app.min.js',
  './common.min.js',
  './purpose-notes.min.js',
  './kelly-review-notes.min.js',
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

  // 3) overview.json: networkOnly (盘中实时数据强制网络优先,不让SW缓存兜底)
  //    根因③修复: 旧版SW缓存兜底致用户看到昨日overview(a_amount=昨日全天值)而非今日实时值。
  //    改 networkOnly: 网络成功返最新overview,失败返 offline 占位(不回退缓存,避免盘中网络
  //    抖动时返旧缓存致误判)。fetchJSON 已加 ?_=Date.now() cache-busting + no-store。
  //    仍写入缓存(cache.put)供离线页重载兜底,但 fetch 时不读取(网络优先无回退)。
  if (url.pathname.endsWith('/overview.json')) {
    event.respondWith(
      fetch(req, { cache: 'no-store' })
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy)).catch(() => {});
          return res;
        })
        .catch(() => new Response('{"error":"offline"}', { headers: { 'Content-Type': 'application/json' } }))
    );
    return;
  }
  //    intraday_snapshot.json + notifications.json: NetworkFirst (盘中实时性优先,离线回退缓存)
  //    notifications.json 走 NetworkFirst（根因③修复）：原走 SWR 3min 缓存致前端读旧 notifications.json，
  //    真实信号触发后即使后端更新了前端也拿旧缓存不弹通知。改 NetworkFirst 每次走网络拿最新。
  //    overview.json 已拆出走 networkOnly（上方），此处仅处理 intraday_snapshot + notifications。
  //    fetch 加 cache:'no-store'（根因①修复）：避免命中浏览器 HTTP/CF 缓存拉旧数据。
  if (url.pathname.endsWith('/intraday_snapshot.json') || url.pathname.endsWith('/notifications.json')) {
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
