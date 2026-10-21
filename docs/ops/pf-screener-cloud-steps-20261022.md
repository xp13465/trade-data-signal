> 落档:2026-10-22(源报告由本批执行 agent 产出,原样归档)
> 相关合并:见 `docs/ops/batch-fix-20261022.md` 时间线

# #266 一期 云上三步 执行报告(2026-10-22)

执行人:实施 agent(worktree 隔离);授权:用户 2026-10-22「两个都授权,一次做完,顺序 258 → 266」。

## 结论速览
| 步 | 结果 | 关键证据 |
|---|---|---|
| 前置 | PASS | 云上 HEAD=`2b2841454`,工作区干净,脚本在位,wrangler 4.151.3,已登录 `sugas13465@gmail.com` |
| 1 DRY_RUN | PASS | exit=0,rows=28289,files=354,schema 含两张表,无 Traceback |
| 2 正式同步 | PASS | 日志 `D1 count=28289` = 独立复核 COUNT=28289,ERROR=0,耗时 37m22s |
| 3 worker 部署 | PASS(经项目正式路径 CI) | 云上手跑 `wrangler deploy` 被超大静态资产拦住(环境限制,非代码缺陷);线上 `/api/fund_screener`=401 且 `/api/unknown_xyz`=404;GH Actions `Deploy to Cloudflare Workers` 对 `2b2841454` = success |
| 附加 fund_score 断链 | PASS | rows=2000 = D1 COUNT 2000,ERROR=0,耗时 2m21s,sync_meta score_date=20261021 |

## 第 1 步 DRY_RUN
命令:`DRY_RUN=1 REPO=/home/ubuntu/code/trade-data bash scripts/sync_fund_screener_to_d1.sh`
输出要点:
- `[sync-screener-python] rows=28289 cols=80 files=354 batch=80 max_stmt_bytes=78483 coverage_cols=79`
- 生成目录 `/tmp/fund-screener-d1.3014378`(25M,357 文件)
- `000_schema.sql` 含 `CREATE TABLE IF NOT EXISTS fund_screener` 与 `CREATE TABLE IF NOT EXISTS screener_meta` 各 1 处;无 Traceback/Error
- exit=0。耗时 <5s。

## 第 2 步 正式全量同步(建表 + 全量写入 D1)
命令:`REPO=/home/ubuntu/code/trade-data nohup setsid bash scripts/sync_fund_screener_to_d1.sh > /tmp/266-sync-20261022_005857.log 2>&1 &`
- 起 00:58:57,止 01:36:19(**37m22s**,354 数据文件 + schema + meta,`wrangler d1 execute` 逐个执行)
- 收尾行:`[sync-screener] 本地 rows=28289 D1 count=28289` / `完成: 2026-10-22 01:36:19 同步成功且校验一致`
- 全文 `ERROR` 计数 = 0
- 独立复核(不采信脚本自报):
  - `SELECT COUNT(*) FROM fund_screener` ⇒ **28289**(与日志一致,≥27000)
  - `screener_meta` ⇒ `fund_total=28289`、`built_at=2026-10-22T00:59:20`、`built_date=2026-10-22`、`source_dates={basic/perf/score_latest/manager/rating/purchase=20261021, risk=20261015}`、`coverage={fund_name/type=28289, company/manager=28235, setup_date=27917, scale=27783 …}`
  - 抽样 `ORDER BY fund_code LIMIT 3`:000001 华夏成长混合(混合型-灵活,scale 39.38,composite 61.19,star 3,kelly 保守)、000002 华夏成长混合(后端)(composite 22.17,star 1)、000003 中海可转债债券A(债券型-混合二级,scale 0.45,composite 54.26,star 3)

## 第 3 步 worker 部署
- 部署前版本:最新 deployment = `e4b8eeca-9e41-4e44-8d58-2c738273d378`(2026-10-21T17:17:26Z)
- 云上手跑 `npx wrangler deploy` **失败(原样记录)**:
  `[ERROR] Asset too large. Cloudflare Workers supports assets with sizes of up to 25 MiB. We found a file /home/ubuntu/code/trade-data-signal/static-site/data/accum_nav_map.json with a size of 25.3 MiB.`
- 根因(已核实):云上工作区保留 R2-only 大产物(`static-site/data/*` 在 `.gitignore:208` 全局忽略,本机保留供 R2 上传),其中 4 个超 25MiB:`accum_nav_map.json 26,556,549 B`、`industry-all-concepts.json 32,732,202 B`、`signal_kelly_trades.json 89,344,290 B`、`signal_kelly_trades_sdc.json 90,554,558 B`。项目正式部署路径 = `.github/workflows/deploy-cf.yml`(push main 后 GH Actions 干净 checkout 跑 `wrangler deploy`,data 目录不在 checkout 内),故不会触发该限制。
- **未做**:不重试、不删/不移文件、不加 `.assetsignore`、不动 R2(均需主控/用户拍板)。
- 验收(线上实测,浏览器 UA,禁 -v/-i):
  - `https://ss.fx8.store/api/fund_screener` ⇒ **401**,响应体 `{"detail":"未登录（基金筛选为登录用户特权）"}`(鉴权在,未越权)
  - 对照 `/api/no_such_endpoint_266` ⇒ **404**(证 401 来自真实路由而非全站兜底)
  - `/api/fund_score` ⇒ **401**(既有端点行为不变);`/` ⇒ **200**
  - 备站:`sss.sugas.site/api/fund_screener` ⇒ 404(GH Pages 无 worker,预期);`s.sugas.site` ⇒ 302(预期)
  - GH Actions `Deploy to Cloudflare Workers` for `2b2841454`(及 `1d967b49b`)= **success** ⇒ 线上 worker 即 main HEAD 版本
- 主控 2026-10-22 独立核实后判第 3 步 PASS,并指示继续附加步。

## 附加步 D1 fund_score 断链修复
命令:`REPO=/home/ubuntu/code/trade-data nohup setsid bash scripts/sync_fund_score_to_d1.sh > /tmp/266-syncfund-20261022_014038.log 2>&1 &`
- 起 01:40:38,止 01:42:59(**2m21s**,本日最新分区为增量:25 数据文件)
- `[sync-d1-python] score_date=20261021 rows=2000 files=25`;收尾 `本地 rows=2000 D1 count=2000` / `同步成功且校验一致`;`[sync-d1] ERROR` 计数 = 0
- 独立复核:
  - `SELECT COUNT(*) FROM fund_score` ⇒ **2000**(与日志一致;脚本口径=只同步 **MAX(score_date) 一个分区**,当日该分区 2000 行,非全市场 27418 行)
  - `sync_meta` ⇒ `score_date=20261021`、`rows=2000`、`synced_at=2026-10-22T01:40:38`,与本地最新分区一致
  - `/api/fund_score` ⇒ 仍 **401**(未登录),`/` ⇒ 200
- 说明:该脚本自 2026-10-01 16:02 起因云上 wrangler 未登录连续失败 39 次,本次为凭据恢复后的首次成功补跑。

## 异常与处置
1. 云上手跑 `wrangler deploy` 因超大静态资产失败 —— 已定位为「云上工作区含 R2-only 大产物 × 项目正式部署走 CI」的环境错配,**不构成线上缺陷**;按要求未重试/未删文件/未改配置。
2. 云上系统时间 = UTC+8(wrangler 日志时间戳为 UTC),核对时点勿混用。

## 回滚(一行)
Worker 本单未产生新版本,回滚无需动作;若需回退既有线上版本,在**干净 checkout**(CI 或本机)执行 `npx wrangler deployments rollback e4b8eeca-9e41-4e44-8d58-2c738273d378`(云上工作区不可直接 deploy/rollback,受 25MiB 资产限制);D1 回滚:`DROP TABLE fund_screener; DROP TABLE screener_meta;`(新表,删后 `/api/fund_screener` 返回空/错误);`fund_score` 为同分区 DELETE+INSERT 全量替换,旧分区未留副本,回滚需重跑对应日期分区同步。

## 边界维度清单(七轴,供审查关独立复核对账)
| 轴 | 测/不测 | 说明/理由 |
|---|---|---|
| 输入域 | 测 | DB 源行数 28289 / 2000 与 D1 计数逐位对齐;抽样 3 行字段完整性 |
| 状态组合 | 部分测 | 测了「表不存在→建表」「表已存在→DELETE+INSERT 幂等」;未测「同步中并发第二个同步」(本次仅单实例,派单禁止并发) |
| 时序 | 测 | 数据日期与本地最新分区一致(20261021);未跨日验证(次日分区切换由定时任务承担) |
| 上下游依赖 | 测 | 上游 public_fund.db 最新分区;下游 `/api/fund_screener`、`/api/fund_score` 401 + `/` 200;CI 部署结论 |
| 极端值 | 不测 | 本单为数据搬运,无算法/阈值;极端值属源数据质量,非本次改动面 |
| 回退路径 | 测(纸面) | 已写明 worker deployment 回滚 ID + D1 DROP 语句;未实际执行回滚 |
| 并发与重入 | 部分测 | 脚本幂等(CREATE IF NOT EXISTS + DELETE+INSERT)已由二次设计保证;未做双进程并发压测(派单明确单实例、且云上定时任务时点外运行) |

## 未做(按任务书)
未跑 `scripts/deploy.sh`;未 push main;未 force;未碰 D1 其他表;未改/重启任何 systemd 单元;无任何通知外发。