# 根因:首页全球盘面跑马灯在线上 app.min.js 丢失(2026-08-19)

## 现象
- 源 static-site/app.js(HEAD 与工作区一致)含完整跑马灯段(L10598-10853):`GLOBAL_TICKER_ITEMS`/`_gtRender`/`_gtRefreshMarquee`/`_initGlobalTicker` 全在,调用点 L22585/L22597。
- 线上 `https://ss.fx8.store/app.min.js` 与 `HEAD:static-site/app.min.js` grep 跑马灯(`global-ticker`/`GLOBAL_TICKER`/`全球盘面`/`gt-sort-body`/`global_ticker_order_v1`/`现货黄金`)= 0 → 页面无跑马灯。

## 决定性根因复现(非构建时点遗留)
1. 在 `feat/marquee-min-rebuild` 分支(HEAD=dc3670a80),**重跑 `python3 scripts/build_min.py`**(从 git HEAD 读源,全量 8 对无增量):
   - 重建后 `static-site/app.min.js` 的 **md5 = `b47199e87c0e9f1dff356774a3e48bb1`,与现 HEAD:app.min.js 逐字节一致**(832533B),仍缺跑马灯。
   - → 不是"旧构建时点未带跑马灯"的漏 build;而是**每次 build_min 重建都确定性删除跑马灯段**。
2. 全文件 terser 实验复现(含跑马灯的完整 HEAD 源 → terser):
   - 当前参数 `--compress --mangle keep_fnames` → 输出 gt-sort-body=0 / global_ticker_order_v1=0 / GLOBAL_TICKER 残留=0(删)。
   - 逐项关闭 compress 选项定位:**唯一让跑马灯段复活的是 `unused=false`**(gt-sort-body=1, global_ticker_order_v1=1)。`dead_code=false`、`side_effects=false`、`passes=1`、`evaluate=false`、`sequences=false`、`--toplevel` 均无效(仍删);只 `--compress`(无 mangle)也删。
   - → 真根因 = **terser 的 `unused`(未使用变量/函数消除)compress 优化,把整个跑马灯段判定为 unused 而删除**,仅保留 keep_fnames 函数名外壳(`_initGlobalTicker` 函数名残留 2 次),整个函数体全部被 tree-shake 掉。
   - 最小骨架(`GT_ITEMS` + `_gtRender` + `_initGlobalTicker` + caller 调用)独立跑 terser → **保留**(正常)。说明非段内结构问题,是**全文件上下文中 e3fa985c3 引入的某段新代码破坏 terser 对跑马灯调用链的静态可达性判断**。

## 何时开始缺(上线时空演化)
- 跑马灯首次引入 `127c3e7b3`(2026-08-17 20:40)时,它的 `app.min.js` **含**跑马灯(gt-sort-body=1, global_ticker_order_v1=1)→ 当时上线是成功的。
- `git log -S "gt-sort-body" -- static-site/app.min.js` 仅 2 个 commit:`127c3e7b3`(引入)+ **`e3fa985c3`(feat(首页要闻):今日要闻/明日关键事件外露两行加定时自动刷新 5分钟轮询)**。
- → 跑马灯在 **e3fa985c3 重建 min 时被 terser 误删**,之后所有 build_min 重建(news-sync merge 1494ee965 等)都基于含 e3fa985c3 代码的 HEAD,持续误删,线上跑马灯丢失至今。
- 注:e3fa985c3 恰好是 §23.11 背景里出过"四档收窄被旧 base 静默覆盖"的 commit,本次又发现它在 min 侧误删跑马灯,是同 commit 的第二处问题。

## 为什么不是构建时点问题(排除项)
- 不在"news-sync 合并中间态无跑马灯"时构建:127c3e7b3 引入跑马灯时 min 已含它,e3fa985c3 是唯一让 min 缺失的 commit,而 e3fa985c3 的 app.js 源**有**跑马灯段(它只是改了新闻轮询调用结构,把调用点移进 `_renderHomeNewsRows` + `_loadNewsDigest().then` async 链)。
- build_min 读源已证实从 git HEAD(打印 `git HEAD (/Users/linhuichen/code/trade)`),sed/log 无删除跑马灯段的 commit(`git log -S` 无)。

## 修复方案(待用户/主控拍板,§23.7 冻结契约 + §15 回归)
### 方案A:改 build_min.py 加 `--compress unused=false`(已验证可行,止血级)
- 验证:`terser full.js --compress unused=false --mangle keep_fnames` → 跑马灯复活(gt-sort-body=1, global_ticker_order_v1=1)。
- 体积:832,533B → 847,037B,**+14,504B(+1.7%)**,压缩仍有效(原始 1.63MB → 847KB)。
- 风险:影响整个 app.js 的 unused 消除行为,可能保留 e3fa985c3 之后本应删的其他未用代码(体积证明额外保留很少)。属生产构建行为改动。
### 方案B:精准定位 e3fa985c3 引入的触发点(零全局影响,需再挖轮次)
- window 锚点实验失败(window.__gtRef 引用加调用点前,调用路径整体被判 dead,锚点连坐被删)→ 说明 terser 判定的是**整个 `_renderHomeNewsRows` → `_initGlobalTicker(banner)` 调用路径 unreachable**,而非仅函数未引用。
- 待挖:e3fa985c3 新增的 `_startHomeNewsPoll`(setTimeout 闭包递归)或 `_loadNewsDigest().then` async 链中哪一处结构让 terser 全局 mis-analyze。定位后改该处写法可让跑马灯零体积/零全局影响复活,但改的是**已上线功能代码**,同样需用户确认。

## 未上线(卡决策)
按 §23.7 冻结契约 + §23.11 不静默:此为生产构建行为级 bug 修复,方案 A 改 build_min 全局压缩行为、方案 B 改已上线功能代码,均需主控/用户确认方向后实施上线。本轮已完整定性根因并提供已验证数据,卡在此处等拍板。

## 复现命令
```
cd /Users/linhuichen/code/trade
python3 scripts/build_min.py   # 从 git HEAD 读源重建
md5 static-site/app.min.js     # b47199e8... = 现 HEAD 一致(仍缺跑马灯)
# terser 定向实验:
git show HEAD:static-site/app.js > /tmp/marq/full.js
npx terser full.js --compress --mangle keep_fnames   # gt-sort-body=0(删)
npx terser full.js --compress unused=false --mangle keep_fnames  # gt-sort-body=1(复活)
git log -S "gt-sort-body" -- static-site/app.min.js  # 127c3e7b3(引入) + e3fa985c3(误删)
```

## 更新(2026-08-19 用户拍板 A+B 后补充)

### 方案A 已落地(止血,已在 feat/marquee-min-rebuild 分支改 build_min.py)
- 改动:`scripts/build_min.py` `_minify_js_content` 对 `app.js` 把 terser 参数从 `--compress` 改为两独立 argv `--compress unused=false`(说明:subprocess list 不走 shell,含空格合并串如 `"--compress unused=false"` 当单 argv 传会被 terser 误当作字面 flag 而**实际未关闭 unused**——第一次实测产物 875,670B 大于预期即此;必须拆成 `"--compress","unused=false"` 两个元素)。
- 只对 app.js 生效,lab.js/common.js 等其余 JS 的 unused 行为不变(实测 lab.min.js/common.min.js/style.min.css 体积与修复前逐字节一致)。
- 重建后 app.min.js:体积 847,037B(默认 832,533B,+14,504B/+1.7%),跑马灯复活(gt-sort-body=1 / global_ticker_order_v1=1 / 现货黄金=1 / global-ticker=1)。
- §15 回归:`scripts/check_data_integrity.py` = 28 ok / 1 warn(etf_since_return 91.1%<95%,与本次改动无关的数据层告警)/ 0 fail;app/lab/关键 class(今日要闻/明日关键事件/kst-comp-fill/AI 预测/凯利/回测)均保留。

### 方案B 挖根结论(为什么 terser 误删)
**根因(决定性)**:terser 的 `--compress unused`(变量/函数未使用消除)对 app.js 全部顶层功能段做全局可达性裁剪。跑马灯段(`GLOBAL_TICKER_ITEMS` + `_gtRender/_gtRefreshMarquee/_gtTick/_gtSchedule/_initGlobalTicker` 等)是**纯客户端副作用段**,启动入口是 `renderOverview → _loadNewsDigest().then((nd)=>{ _renderHomeNewsRows(...) }) → _startHomeNewsPoll(setTimeout async 闭包递归) → _initGlobalTicker(banner)`,全部在 **async/Promise 回调 + 闭包递归链**里被启动,不挂任何全局对象、无 DOMContentLoaded 直接同步引用。terser 对该异步链的可达性做**保守判定**,认为不可达 → 将整段判未使用而删。
关键佐证:
- 跑马灯首次引入 `127c3e7b3` 时,调用点寄生于 `async function renderOverview`(reachable 顶层主函数)**直接路径**,默认 terser **保留**(gt-sort-body=1)。
- `e3fa985c3` 把调用点挪进新函数 `_renderHomeNewsRows`(仅在 `_loadNewsDigest().then` 回调 + `_startHomeNewsPoll` 闭包里调用),默认 terser 从此**删除**跑马灯段,每次 build 都删 → 线上丢失至今。
- 隔离实验确认:**单纯打断 `_renderHomeNewsRows` 的 unused(index 引用 window.__gtchain)无效**(还删)→ 裁剪发生在更内层(跑马灯段整体);**段内加 window 强锚 `window.__gtAnchor = { GT: GLOBAL_TICKER_ITEMS, init: _initGlobalTicker, render: _gtRender }` 后默认 terser 复活**(gt-sort-body=1)→ 证因:"整段被判 unused",任何能被外部 case 引用到的锚即可拉活。
- 去 `_startHomeNewsPoll`、`.then` 改同步均**无效**(仍删)→ 不是单一孤立函数/语法触发,是 e3fa985c3 整体改变调用链写法的全局可达性影响。

### 排查同类(§23.2③):有没有其他同款被静默误删
- 方法:对比 `default(min,删跑马灯)` vs `unused=false(救回)` 产物的 class 集合差。
- 结论:**被 unused=false 额外救回的 class 全部是跑马灯自身**(gt-scroll/gt-track/gt-item/gt-name/gt-price/gt-pct/gt-gear/gt-sign/global-ticker/gt-sort-*/gt-degraded + 品种键 a50/cnh/goldapi/erapi/wti/silver/usd/jpy/ndx100/hf/wh/us/east/tx),**没有发现任何其他独立功能段被静默误删**。同款隐患仅跑马灯这一处。
- 通用结论沉淀:凡"纯客户端副作用、只在 async/闭包回调链启动、不挂全局对象"的顶层功能段,若用 terser 默认 `unused` 压缩,都有被整体剪除风险;新增此类功能应显式挂一个 `window.x` 锚或确认 build 后 grep 关键 class 在 min 里。

### 备选精准修法(方案B落地选项,若未来想省掉全局 unused 关闭)
在跑马灯段 END 处加一行 `window.__gtAnchor = { GT: GLOBAL_TICKER_ITEMS, init: _initGlobalTicker };`,即可在**保持默认 unused** 下让 terser 保留该段(已验证)。体积/行为影响更小(不动全局压缩),但需改 app.js 源码 + 重 build + bump 上线,属"改已上线功能源码",按 §23.7 需用户确认。当前以方案A(build_min 侧,不改业务源码)先止血上线。
