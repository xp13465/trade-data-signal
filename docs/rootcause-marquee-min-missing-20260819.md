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
