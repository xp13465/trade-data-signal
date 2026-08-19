# 根因:首页「📣今日要闻/📅明日关键事件」板块会消失+不自动更新(2026-08-19,第三次修,模式根治)

## 现象
首页 AI 预测卡下方「今日要闻 / 明日关键事件」两行外露,用户多次反馈"板块会消失 + 不自动更新"(历史上已修过几次,一直没好)。本次定位为**反复复发的结构反模式**,从模式层根治,而非再打当前位置补丁。

## 反模式(决定性根因)
**"插 banner 外独立节点 + 模块级缓存 + 轮询 `if(缓存) return` 只更新节点" 三合,遇到 renderOverview 重建时不重置**:

1. **模块级缓存不随页面重建重置**:`static-site/app.js:22558` `let _homeNewsWrap = null`(轮询原地更新缓存)、`22559` `_homeNewsFallback`(兜底历史入口行)均为**模块级**变量,只在原 `22566`(空 remove+null)/`22582`(赋值)出现,renderOverview 重建时无任何重置。
2. **renderOverview 每次重建 banner/content**:`10443` renderOverview 每次 `document.createElement("div")` 建新 banner;`10508` `content.innerHTML=""` 清空内容区(旧 wrap 一并移除);`10583` `content.insertBefore(banner, content.firstChild)`;`10594-10596` `.then(nd => { _renderHomeNewsRows(nd, banner, content); _startHomeNewsPoll(...) })`。
3. **致命分支只更新死节点并 return**:`22569-22572` `if (_homeNewsWrap) { _homeNewsWrap.innerHTML = ...; return; }` **不检查 isConnected、不重新挂到新 banner 后**。renderOverview 重建后 `_homeNewsWrap` 仍指向已分离旧节点 → 轮询只往死节点写,浏览器渲染不到 → 用户看到"板块消失/不更新"。
4. **重复堆积风险**:旧轮询闭包捕获旧 banner/content,重建后 `_homeNewsWrap` 非空且 isConnected 判 false 的话会走 `content.insertBefore(wrap, banner.nextSibling)`(banner 已分离,nextSibling=null → 往 content 末尾 append)→ 与新 render 的新节点**重复堆积**。

**renderOverview 重复调用入口(全部触发重建)**:tab 切换(110-130→6661)、定位滚动(3649)、公募基金(17885)、登录检查(21382)、模式切换(25940)。

## 叠加根因(空数据永久移除)
- `22531-22536` `_loadNewsDigest` 成功分支:news 空直接 `_newsDigestCache={news:[],...}` **覆盖旧缓存**(不像 catch 分支 `22545-22547` **保留旧缓存**)。
- `22563-22566` `if(!hasData && _homeNewsWrap){ _homeNewsWrap.remove(); _homeNewsWrap=null }` 空数据直接**移除板块**。
- 触发条件=fetch 返回 200+合法 JSON 但 news/upcoming 空(数据侧 `scripts/fetch_news.py:573-578` 三源失败返回空;launchd 每 30 分 00:01 首采新一天最危险 → 线上 news_digest 空 → 前端读到空 → 移除板块)。

## 同款反模式节点(排查同类 §23.2③ 结论)
- 确认为同款: `_homeNewsWrap`(22558)、`_homeNewsFallback`(22559/兜底入口)。
- **排除** `_gtEl` 跑马灯(L10619):`_gtEl/_gtTimer/_gtActive/_gtVisBound` 是 renderOverview **闭包内局部 let**(每次 renderOverview 重建都新建作用域),非模块级缓存 → 自愈不残留;且已有独立根因文档(`docs/rootcause-marquee-min-missing-20260819.md`,terser unused 误删,方案A `unused=false` 已落地)。
- 排除 `_badgeEl`(L11175)/`_resonanceEl`(L17854):均为**局部 const 元素查找**,非跨 renderOverview 持久缓存。

---

## 根治方案(2026-08-19 实施,feat/home-news-rootfix)

### 方案(4 招,模式层,非当前位置补丁)
1. **`_homeNewsReset()` 重置 helper**(新增):renderOverview 清空内容后调用(L10493 失败分支 / L10510 成功分支追加)。`clearTimeout(_homeNewsTimer)` 杀掉旧轮询 + 置空 `_homeNewsWrap/_homeNewsFallback` + `_homeNewsPolling=false`。新 render 的 `.then` 用**当前 banner** 重建节点 + 重启轮询,不重复堆积(旧轮询已 clearTimeout 死亡)。
2. **isConnected 守卫**:`_renderHomeNewsRows` 所有复用分支(正常两行 `if(_homeNewsWrap)`、兜底 `if(_homeNewsFallback)`、空数据 remove `if(_homeNewsWrap)`、兜底移除 `if(_homeNewsFallback)`)全部加 `&& .isConnected`——节点仍在 DOM 才复用原地更新;脱离 DOM(旧 banner 已重建)=当成不存在 → 走下方用**当前 banner** 重建新节点。
3. **空数据守卫**:`_loadNewsDigest` 成功分支,news 空**但已有旧缓存非空**→ 保留旧缓存(只更新 date/清 err),对齐 catch 分支"保留旧缓存避免外露行闪空/闪烁"意图。轮询虽拉回空,hasData 仍从旧缓存算真 → **板块不因一次空快照消失**;下轮采到新数据再刷新(陈旧≤5min 轮询窗口)。
4. **不破坏跑马灯可达性**:不挪 `_initGlobalTicker(banner)` 调用点(仍在 `_renderHomeNewsRows` 创建新节点分支),配合已落地的 build_min `unused=false`(方案A),跑马灯段不再被 terser 误删(见下复现验证)。

### 复现/验证(自测 §23.2②)
- 提交源码改动至 feat 分支(基 `afc92d6a7`),重跑 `python3 scripts/build_min.py`(从 git HEAD 读源):
  - min 体积 847,505B(-48.3%);
  - grep `static-site/app.min.js`:**今日要闻=1 / 明日关键事件=1 / 全球盘面跑马灯=1 / global-ticker=1 / gt-scroll=1 / summary-news-row=1 / _homeNewsReset=1**(三功能在 min 均>0,跑马灯未被误删)。
- 逻辑自测路径:
  - 首次渲染:reset 后 `_homeNewsWrap=null` → `.then` 走创建分支,isConnected 真 → `banner.after(wrap)` 挂到当前 banner 后。
  - 轮询刷新(页面未重建):`_homeNewsWrap.isConnected` 真 → `innerHTML` 原地更新,不改节点 → 位置不变。
  - renderOverview 重建(切 tab 返回):`content.innerHTML=""` 移除旧节点 → `_homeNewsReset()` 杀旧轮询+清缓存 → 新 `.then` 用**新 banner** 创建新节点挂新位置 → 不重复堆积、不消失。
  - 空快照(三源失败/首采空窗口):成功分支保留旧缓存 → hasData 仍真 → 不 remove 板块,轮询下一轮采到新数据更新。
  - 兜底行:hasData 假且无缓存 → 创建历史入口行;后续有数据且兜底行 isConnected → remove 兜底 + 建正常两行。

### 排查同类清单(§23.2③ 复盘)
| 节点 | 判定 | 处理 |
|---|---|---|
| `_homeNewsWrap`(模块级) | **同款**,有 bug | 已加 isConnected 守卫 + reset |
| `_homeNewsFallback`(模块级) | **同款**,有 bug | 已加 isConnected 守卫 + reset |
| `_gtEl` 跑马灯(闭包局部) | 不同款(每次 renderOverview 重建新作用域,自愈) | 未动调用点,可达性保持,min 验证保留 |
| `_badgeEl`(局部 const) | 不同款(元素查找非持久缓存) | 无 |
| `_resonanceEl`(局部 const) | 不同款 | 无 |

### 提交信息
- feat 分支 `feat/home-news-rootfix`,commit `e70ac8a0e`,基 `afc92d6a7`(origin/main,fresh)。改动仅 `static-site/app.js`(+30/-8)。版本串由主控 merge 走 `scripts/main-merge.sh` 统一 bump(agent 不自行 bump,机制 C)。
- Co-Authored-By: Claude

## 复现命令
```
cd /Users/linhuichen/code/trade
git checkout feat/home-news-rootfix
python3 scripts/build_min.py    # 从 git HEAD 读源(需 commit 后)重建
grep -c "今日要闻" static-site/app.min.js      # =1
grep -c "明日关键事件" static-site/app.min.js   # =1
grep -c "global-ticker" static-site/app.min.js  # =1(跑马灯保留)
grep -c "_homeNewsReset" static-site/app.min.js # =1
```
