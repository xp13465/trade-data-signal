# #12 首页新闻看板「消失 + 不自动更新」根治报告(2026-08-20)

> 老 bug 反复复发根治。用户已拍板(§23.7 例外可修)。本报告实证根因 → 最小根治 → 功能生效层验证 → §23.2③ 同类排查 → 复现。全文与验证脚本、运行结构咬合。

## 一、实证结论(先核根因,不硬套 prior plan)

**先决事实检查:线上已部署的 app.min.js(v=20260820)已含 08-19 的全部守卫**(`_homeNewsReset`/`_homeNewsWrap`/`isConnected`/`summary-news-row` 均 curl 在线确认)。所以"反复复发"**不是旧版部署导致**,是剩余结构性弱项仍存在。(对齐 memory `deploy-cdn-stale-snapshot-blue-screen` 的"部署才生效"排查:守卫已真上线,复发=代码仍有洞=L42 关心的"说着修好实则没修"的反面——本次确实找真正没补住的洞。)

### 用真实运行时(Playwright + 线上真实后端数据)实证 08-19 版已能处理的路径
`scripts/playwright-accept/news-lifecycle-facts.mjs`(线上旧版 min):
- 新闻行首次出现 ✓ / 切 tab 往返 6 次仍不消失 ✓ / 轮询体(force 重拉+原地渲染)自动更新到新数据 ✓ / 主源 500 时 R2 兜底返回真实数据、新闻不消失 ✓

**= 08-19 的 `_homeNewsReset` + `isConnected` 自愈在常用与压力场景已能兜住。剩余洞只有一个结构性弱项:**

### 真·剩余弱项(本次根治对象):无「代际 token」
- `renderOverview` 每次 `content.innerHTML=""` 重建 banner/清空内容区后,老一代 `_summaryP.then` 的异步新闻回调与 `_startHomeNewsPoll` 轮询**跨代共享模块级 `_homeNewsWrap`/`_homeNewsTimer`/`_homeNewsFallback`,没有代际判失效**。
- 一旦一次 async 新闻加载、或一次轮询等待,跨越了一次 renderOverview 重建,其闭包仍绑定旧 banner/content。`isConnected` 自愈能恢复(实测多数场景能自愈),但在极端交错下可能:
  - 旧代轮询 fire 后 `_renderHomeNewsRows` 走 `content.insertBefore(wrap, banner.nextSibling)`(banner 已死)→ 可能先写错位/多挂;虽后续自愈但会**瞬时错位**。
  - 旧代 `_startHomeNewsPoll` 若先持有了 `_homeNewsTimer`,新代的 `_startHomeNewsPoll` 因 `if(_homeNewsTimer)return` 被压掉 → 当前代失去自己的轮询(旧代绑死 banner,靠自愈勉强续,但不彻底)。
- 这正是"反复复发、时好时坏"的典型来源——**不是每次必现,而是取决于异步时序**,所以之前多次"修好"其实是守卫把必现路径堵了,剩余偶发弱项仍在。

## 二、最小根治方案(仅新闻域,先 commit 进 feat 分支)

**方案 = 引入「纪元(epoch)」token,让旧代异步/轮询在 DOM 写前判别自己过期而作废**(prior plan 第 1 点的实装)。加在 3 处:

1. **`_homeNewsReset()` 自增 `_homeNewsEpoch`**:每次 renderOverview 清空内容 = 新纪元,所有旧代异步/轮询据此判失效。
2. **renderOverview 的 `_loadNewsDigest().then`**:捕获本代纪元 `_hnLoadEpoch`,await 回来后若 `_homeNewsEpoch !== _hnLoadEpoch`(期间被更新的 renderOverview 重建)则整段作废,不写当前 DOM。
3. **`_startHomeNewsPoll(banner, content)` 按纪元单飞+接管**:
   - 同代轮询已存在 → 单飞不变动;
   - 旧代遗留轮询 → 新代 clearTimeout 杀旧 + 重建当前代(彻底替换,不残留死节点资源);
   - 轮询 fire 前后复核纪元:等待期间或 `_loadNewsDigest(true)` 重拉期间被重建 → 自弃,不碰当前 DOM。

**为什么用纪元而非继续加 isConnected**:isConnected 是"节点级"兜底(已在使用),纪元是"代际级"前提——先判代,后代内的节点必然属于最新 renderOverview,彻底消除"旧代闭包操作新代 DOM"这一类(不再靠自愈)。

**不 bump 版本串 / 不 commit 重建的 min**:按机制 C,版本串统一由主控 merge 走 `main-merge.sh` 重建+bump。本地仅用 `scripts/build_min.py` 生成验证用 min,不提交。

## 三、功能生效层验证(实跑,非"代码看起来对")

### V1 单元/生命周期仿真(跑真实源码函数,node):`docs/scripts/news-lifecycle-sim.js`
从 `static-site/app.js` 提取真实 `_renderHomeNewsRows/_startHomeNewsPoll/_homeNewsReset/_loadNewsDigest/_db*` 等 11 函数 + 最小 DOM stub,重放:
- A) 单挂载 + 轮询原地更新 → 断言新闻出现、不重复堆积、能更新
- B) 两次 renderOverview 交错(旧异步回调迟到)→ 断言仍存在、isConnected、不堆积、能更新
- C) 纪元硬化直接验证 → reset 自增纪元、新代 `_startHomeNewsPoll` 接管后新闻唯一且绑当前 banner

```
node docs/scripts/news-lifecycle-sim.js
===== 结果: 14 PASS / 0 FAIL =====   (C1/C2/C3 纪元硬化断言通过)
```

### V2 真实浏览器(线上真实后端数据 + 注入本地修改版 min):`scripts/playwright-accept/news-epoch-facts.mjs`
将本地 worktree 的 `app.min.js`(含纪元硬化)以 Playwright route 覆盖注入线上页面(`serviceWorkers:'block'` 禁 SW,保证用注入版),实测:
```
===== 7 PASS / 0 FAIL =====
[注入] 页面运行的是含纪元硬化的修改版 min  ✓
1 首次:新闻行出现+v1                          ✓
2 切tab往返6次新闻行仍在(不消失)              ✓
3 轮询体自动更新到 v2(不自动更新=FAIL)        ✓
4 完整重建后新闻行唯一且绑当前 banner          ✓
5 重建后当前 banner 唯一(不堆积)              ✓
6 fetch500后新闻行不消失                       ✓
```

### V3 同类(§23.2③)回归
纪元硬化后重跑 V2 套件(含同类 guard)不回归,7/7。

## 四、§23.2③ 同类错误面排查(与 _homeNewsWrap 同"renderOverview 重建后仍引用已脱离节点"反模式)

| 模块级 DOM 引用 | 是否守护 | 本次处置 |
|---|---|---|
| `_homeNewsWrap`/`_homeNewsFallback`(新闻行) | 08-19 isConnected + 本次纪元 | 已全面加固 ✓ |
| `_gtEl`/`_gtTrack`(全球跑马灯 ticker) | 已含 isConnected(2026-08-19) | 无洞,不动 ✓ |
| `_bannerRenderCtx.el`(横幅 chips/时间/收盘态) | **原本无 isConnected 守卫** | 本次补 3 消费者守卫(`_applyDynamicToChips`/`_applyDynamicToBannerTime`/`_onMarketClosed`)✓ |

`_bannerRenderCtx` 三个消费者原本对已脱离横幅操作是**静默 no-op(不崩但丢更新)**,加守卫后直接跳过,零行为变化——与新闻域同反模式,属同类必查面。

## 五、公示/一致性/数据
- **无算法/数值改动**:本次纯 DOM 生命周期 + fetch 防御加固,不涉及 track_score/评分/匹配/公示文案 → 无需改 `purpose-notes.js`(§21 已 grep 确认无对应文案依赖)。
- **无数据产物改动**:不改后端生成、不改 news_digest 结构,(§22)三展示位共用同一数据源不变,无需重跑/同步 static-site/R2。
- **已落档**:本报告 + `docs/scripts/news-lifecycle-sim.js`(复现脚本)+ `scripts/playwright-accept/news-epoch-facts.mjs`(真实浏览器验证)+ 配套 commit,均 git tracked。

## 六、影响面
仅 renderOverview 生命周期内新闻域 + 横幅 chips 守卫,不碰 valueChartWithSignals/信号弹窗/市场温度(#24)、冰点日(#19)、indexChart 四档(#73)、signalColor/freeze/费率。

## 复现
- 仿真:同目录 `docs/scripts/news-lifecycle-sim.js`(依赖 `../../static-site/app.js` 源码),`node docs/scripts/news-lifecycle-sim.js` → 14/14。
- 真实浏览器:主仓 `scripts/playwright-accept/`(依赖其 node_modules/playwright + chromium),改 `WORKTREE_MIN` 指向本 worktree 的 `static-site/app.min.js` 后 `node scripts/playwright-accept/news-epoch-facts.mjs` → 7/7(需线上可访问)。
- 数据:线上 `https://ss.fx8.store/data/news_digest.json`(真实数据,route 拦截可控)。
- 口径:新闻外露行「今日要闻+明日关键事件」由 `_loadNewsDigest` 读 news_digest.json 渲染,5min 轮询 force 重拉原地更新;纪元=renderOverview 重建代际。
