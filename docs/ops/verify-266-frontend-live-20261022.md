> 落档:2026-10-22(原样归档)
> 关联:`docs/ops/batch-fix-20261022.md`、`docs/ops/version-consistency-rca-20261022.md`

# #266 前端上线事实层验证(只读)— 2026-10-22 02:2x

## 结论
**已上线。** 三站线上 app.min.js 与 main commit `2b2841454` 的本地产物**逐字节一致**(md5 87dbf668fa654f28b3cbf1860fcc3412 / 1,090,838B),5/5 新增锚点全部命中;版本串三站一致。

## 1. 字符串锚点(取自 feat c3196f401 + 返修 50ee07dff/30f7b4583 对 static-site/app.js 的 diff)
基线 `c3196f401^:static-site/app.js` 对以下 5 条均 0 命中 ⇒ 确属新增:
| # | 锚点 | 类型 |
|---|---|---|
| 1 | `fund-screener-chipline` | class |
| 2 | `fund-screener-toggle` | id/class |
| 3 | `基金评分筛选` | 中文字符串(登录提示 feature 名) |
| 4 | `经理历史最佳回报` | 中文字段标签 |
| 5 | `索提诺比率（3 年）` | 中文字段标签 |

## 2. 三站抓取(浏览器 UA,curl 未带 -v/-i)
| 站点 | http | size | md5 | 锚点命中 |
|---|---|---|---|---|
| ss.fx8.store | 200 | 1,090,838 | 87dbf668fa654f28b3cbf1860fcc3412 | 5/5(每条 1) |
| sss.sugas.site | 200 | 1,090,838 | 87dbf668fa654f28b3cbf1860fcc3412 | 5/5(每条 1) |
| s.sugas.site | 200 | 1,090,838 | 87dbf668fa654f28b3cbf1860fcc3412 | 5/5(每条 1) |
本地对照 `git show 2b2841454:static-site/app.min.js` = 同 md5/同 size,锚点 5/5。

## 3. 尺子先验(red 先验)
feat 前旧 min(`c3196f401^:static-site/app.min.js`,1,072,220B)对 5 条锚点 **0 命中** ⇒ grep 具备判别力,线上 5/5 非假绿。

## 4. 版本串一致性(§24⑤)
| 项 | ss.fx8.store | sss.sugas.site | s.sugas.site | commit 2b2841454 |
|---|---|---|---|---|
| index.html 引用 | app.min.js?v=20261022 | 同 | 同 | app.min.js?v=20261022 |
| sw.js CACHE_VERSION | v6-20261022-a649 | 同 | 同 | v6-20261022-a649 |
(app.min.js 内部不落日期版本串,版本由 index 查询串 + sw CACHE_VERSION 承载;三站+仓库三方一致)

## 5. 链与后续改动
- `2b2841454` 在 origin/main 与 HEAD(`git merge-base --is-ancestor` PASS)。
- `2b2841454..HEAD` 对 static-site/app.js、app.min.js **无新 commit** ⇒ 线上即该版本。

## 6. 数据层(顺带)
- overview.json: http 200, **date=20261021**, signals_today 条数 **642**(字段 date/index_id/signal/... 齐全)。
- fund_score.json(ss.fx8.store/r2/fund_score/): http 200, **date=20261021**, **count=2000**, data len=2000。
- ssd.fx8.store/data/fund_score/fund_score.json → 404(该前缀不经此路径,非异常)。
- 今日 10-22 凌晨尚未开盘,date=20261021 = 最近交易日,符合预期。

## 7. 备注
- `ss.fx8.store/index.html` 直连返回 307 → `/`;加 -L 后 200(39,507B),属既有跳转行为,不影响结论。
- 本次全只读:未 deploy、未改文件、未重启、零外发。
