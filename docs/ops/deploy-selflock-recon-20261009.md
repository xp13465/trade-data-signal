# deploy 校验自锁(#236) + 自然日口径(#235) 只读核查报告(2026-10-09)

> 调研 agent 落档,2026-10-09 ~14:50。全程只读:云上仅 ls/tail/grep/cat/journalctl/stat,本机仅 curl;未跑 deploy、零 R2 写、零告警外发;未切分支/未 commit。
> 前序:`docs/ops/deploy-integrity-selflock-20261008.md`(170 行)/ `deploy-integrity-fail-20261008-0206.md`(131 行)/ `mail-alert-handling-20261008.md`(88 行,解锁留痕)。
> 任务:①今日实况 ②死锁链路行号 ③#235 口径与 6 项现状 ④修法方向 ⑤未取到项。

## 0. 结论摘要

| 项 | 结论 |
|---|---|
| 今日 deploy 轮数/成败 | **4 轮(00:13 / 00:28 / 02:06 / 05:00),全部成功(退出码=0,check 40 ok / 2 warn / 0 fail)** |
| 是否仍在自锁 | **否**。10-08 22:4x 手动解锁已生效,今日零阻塞;结构性死锁**代码未修,仍在位**,待下次 ≥7 自然日长假或 alert 真停更 >7 自然日触发 |
| r2_upload_async | 今日 **3 跑 3 成**(00:22→01:13 / 02:16→02:32 / 05:11→05:22,均退出码=0);另 00:49 一次锁跳过(正常并发机制) |
| 58 用户可见项 | **不卡了**:线上 alert_analyze 抽样 4 个全 = 10-08 版;alert.json / boot.alert = 10-08 版 |
| 站点数据 | **已恢复更新**:overview date=20261009(13:55)、notifications 20261009(13:57)、ad_line 末条=20261009 |
| #235 口径 | `check_data_integrity._days_ago` L156-162 纯自然日;阈值 L57-58(WARN=3 / FAIL=7);10-08 拦 6 项(全 20260930,自然日差 8 / 交易日差 0) |
| 两件事关系 | 两处代码(check_data_integrity.py 口径 vs update_all.sh 上传链),同一闸门区;建议一并修 |

## 1. 今日(10-09)实况 — 硬证据

- **4 轮 deploy**(每轮 = 段1 大日志 + 段2 小日志,共 8 文件):
  - 00:13 轮(`deploy_20261009_0013.log` 100KB):触发者 = self-heal(00:07 HEAL 触发 backfill_evening 重跑,`self_heal_launchd.log` L13513);段2 `deploy_20261009_0022.log` 退出码=0。
  - 00:28 轮(`deploy_20261009_0028.log`):self-heal 00:22 再触发(同 log L13519);段2 `_0039.log` 退出码=0。
  - 02:06 轮(`deploy_20261009_0206.log`):trade-backfill-evening 02:00 档(journal 02:17:55 Finished);段2 `_0216.log` 退出码=0。
  - 05:00 轮(`deploy_20261009_0500.log`):trade-us-stock-morning 单元(journal 05:00:00 Starting);段2 `_0511.log` 退出码=0。
  - **四轮 check 汇总全同:`=== 汇总: 40 ok / 2 warn / 0 fail ===`**(另 check_task_state 汇总 2 ok / 1 warn / 0 fail)。
- **2 warn(不阻断,四轮同)**:`fapi_mutex 两源最新日不一致 mootdx=20261008 fapi=20260930(观察期时序)` + `etf_since_return 93.6% (2833/3028) < 95%`。
- **R2 异步链**:`r2_upload_async_20261009_{002208,021655,051106}.log` 均 `=== r2_upload_async 结束 ... 退出码=0 ===`,`[verify-r2] 对账完成, 自动补传 0`;00:49 一次锁跳过(写 `r2_upload_async_skip.log`,在跑实例收尾补跑,正常)。
- **台账**:`.r2_all_data_state.json` mtime=10-09 05:21:25;alert 条目 `md5=65c60ad5378e4179a40bfacb69c08352`(源侧 10-08 版 md5,与被拦期不同)。
- **用户可见层实测**(本机 curl + 浏览器 UA + cache-buster):
  - `ss.fx8.store/data/alert.json` → date=**20261008**,generated_at 10-08 19:29:45;
  - `alert_analyze_{hs300,510300,159915,588000}.json` → alert.date 全 = **20261008**;
  - `boot.json` → alert.date=20261008;
  - `overview.json` → date=**20261009** collected_at 13:55:53;`notifications.json` → date=**20261009** gen 13:57:17;`ad_line.json` → 末条 **20261009**。
- **R2 直连(ssd)HEAD**:alert etag=65c60ad5…,LM=**10-09 01:08:04 北京**(=今日 00:22 异步链真 PUT);alert_analyze_hs300 etag=3d495923…,LM=10-09 01:08:08。⇒ 解锁版 + 今日通道复传,对象级逐位对上。
- **58 项**:GIT_REPO `static-site/data/alert_analyze_*.json` = **70 个文件**(mtime 10-08 19:29/19:30);standalone 登记 **71 项**(alert.json + 70 analyze,=`upload-data-files` 解锁命令的 71/71)。注:索引自述「58 用户可见项」与磁盘 70 文件的口径差异**未深究**(见 §6-1)。
- 残留观察(非本任务修复):10-08 23:20 `trade-r2-consistency`(§22 三站一致性)**FAIL 并发出一条 severe**(23:23 邮件/飞书);其差异文件清单未取(见 §6-2)。

## 2. 死锁链路确认(行号) — 结构成立且未修

- **校验读 R2**:`check_data_integrity.py` `check_alert` L410-436 → `_fetch_r2_json("alert.json")`(L417;`R2_DATA_BASE=https://ss.fx8.store/data` L110)→ 读到 09-30 版 `days=8 > 7`(L428 判 / L431 fail;阈值 L57-58)→ FAIL(10-08 实测消息 `✗ alert: alert.json date=20260930 滞后 8 天 > 7 天`)。
- **拦截点**:`deploy.sh` **L323-324** 跑 check;**L326-331** rc≠0 → `notify.py --severe`(L329)+ **`exit 1`(L330,硬终止)**。
- **写入点在拦截点之后**:`deploy.sh` **L582** 触发 R2 上传异步(L583-604);alert 的唯一上传通道 = `r2_upload_async.sh` **L223** `upload-all-data`。其余线上写(L523/529 静态 JSON rsync、L543 DB rsync、L656 段2 git push)全在 L326 之后。
- ⇒ **同一脚本内 拦截(L324) < 写入触发(L582),且 alert 无其它通道**(10-08 报告 §3 五通道穷举;当时 `.r2_standalone_keys.json` 无 alert)⇒ **结构性死锁确认**。
- **旁路开关复核**:deploy.sh 仅有 FORCE(时段闸门 L145-153)/ SKIP_MAP_SYNC(L219)/ EXPORT_SKIP_R2(L20-22),**无 check_data_integrity 跳过开关**(grep 复核,与 10-08 报告 §10 一致)。

## 3. #235 口径与 6 项现状

- **判定代码**:`_days_ago` **L156-162** = `(datetime.now() - d).days`(**纯自然日**);阈值 **L57-58**(`STALE_DAYS_WARN=3` / `STALE_DAYS_FAIL=7`)。
- **10-08 02:06 被拦 6 项**(日志原文 6 条 ✗,实际值全=20260930,自然日差 8 / 交易日差 0):

| # | 项 | 判定位置 | 10-08 fail 原文 | 今日值(05:00 轮) |
|---|---|---|---|---|
| 1 | alert | L410-436(`_days_ago` L428 / fail L431) | date=20260930 滞后 8 天 | ✓ date=20261008(滞后 1) |
| 2 | notifications | L439-464(L456/L459) | date=20260930 滞后 8 天 | ✓ date=20261008(滞后 1) |
| 3 | ad_line | L522-549(L541/L544) | 最后日期=20260930 滞后 8 天 | ✓ 末=20261008(滞后 1) |
| 4 | a_stock | L552-579(L573/L574) | a_amount 最后日期=20260930 滞后 8 天 | ✓ ok |
| 5 | accum_nav_map_fresh | L979-1003(L996/L999) | nav 日期=20260930 滞后 8 天 | ✓ nav=20261008(滞后 1) |
| 6 | s06_state | L2114-2220;触发分支=② R2 降级(L2210 判 / L2214 fail;因本地也不新鲜 L2141/L2144) | 线上 coverage_end=20260930 滞后 8 天 | ✓ R2 副本 coverage_end=20261008 与本地一致 |

- **全量自然日面(修口径需扫的清单)**:**`_days_ago` 共 9 处调用点** = L267 overview / L428 / L456 / L507 fund_score / L541 / L573 / L996 / L2141 / L2210;另 **mtime 版 1 处** = `check_trade_sim_indices` L736-747(`days=(now-mtime).days`,10-08 19:38 那轮也真 fail 过,同族;见 mail-alert 文档 §二)。
- **改交易日口径怎么算(可复用工具)**:`app/calendar.py` — `is_trading_day` L66 / `last_trading_day` L78(含 max_lookback=15)/ `trading_days_between` L90;同脚本内**现成先例**:`signal_accum_nav_lag` L899-906(`trading_days_between` 差-1)、`nextday_plan` L1966-1973(`last_trading_day`+`is_trading_day`)。建议批量公式 `lag = len(trading_days_between(date, last_trading_day(now))) - 1`(长假期间天然≈1,不会放大);云上 `trade_dates.txt` 存在(10-08 报告实测 L8736=20260930/L8737=20261008),`app.calendar` 自带周末降级。
- **同脚本内自我矛盾旁证**:另两项(`signal_accum_nav_lag` / `fapi_mutex`)本就交易历/最新共同日口径。

## 4. 两件事:同一处还是两处?

- **两处代码、同一闸门区**:#236 = `deploy.sh` 的「拦截先于唯一通道」结构(修在 update_all.sh/上传链,可不动 deploy.sh);#235 = `check_data_integrity.py` 的日历口径。**文件不相交,可一次派单一并实施,互不冲突**。
- **修复互补性(重要)**:#235 单独修 → 10-08 事件**完整消除**(02:06 交易历差≈1 ⇒ 放行 ⇒ 当天 deploy 自身就把 alert 传上线);#236 单独修 → 10-08 02:06 仍会被拦(假期中本地也旧,6 项照样 fail),只能把「永久锁」降级为「当天 17:50 数据刷新后自解锁」;**两者叠加 = 事件不发生 + 结构死锁消除**。⇒ 建议 F1+F2 一套呈拍板。

## 5. 建议修法方向(分步 + 风险)

- **F1(#235,交易历口径;改已上线校验行为 ── §23.7 须用户拍板)**
  - 改动点:`check_data_integrity.py` `_days_ago` 改交易历(或新增 `_trading_days_ago` 逐点切换),覆盖 §3 清单 9 个 `_days_ago` 点 + 1 个 mtime 点(逐点评估:overview/fund_score/alert/notifications/ad_line/a_stock/accum_nav/trade_sim/s06 两处)。阈值 3/7 语义保留(按交易日计)。
  - 回归样例(建议 tester 出对照):①10-08 02:06 场景 ⇒ 应 PASS;②真停更 ≥8 交易日 ⇒ 应 FAIL(防口径放宽误伤判别力);③周末/长假首日凌晨/跨日盘中各一;④trade_dates.txt 缺失时的降级路径。
  - 风险:口径语义变更波及 10 个判定点(需逐点过);日历依赖 trade_dates.txt 新鲜度(该文件由链内 refresh 维护)。
- **F2(#236,上传链解耦 = 结构根治;新增为主 ── §23.7 风险低,但索引标注待拍板)**
  - 改动点:`update_all.sh` **L174-184**(export_alert / export_alert_analyze 两 export 之后)追加 `REPO=... upload_r2.py upload-data-files alert.json <alert_analyze_*.json>`。先例 = `s06_snapshot.sh` L133;机制 = `upload_r2.py` 分发 L4059-4065 + 独立链登记 L2248-2257(#188);**生产实测已存在**(10-08 22:4x 解锁即用此命令,71/71 上传 + purge 3 批全成功;登记数现 = 71)。登记后 `verify-r2` 的独立链 stale 检测/补传亦会覆盖(注意:verify-r2 触发仍在 deploy 链内,只作兜底不作唯一救主)。
  - 细节:必须带 `REPO=`(guard_repo_default 拒裸跑,mail-alert 文档 §三);失败策略建议「留痕 + 不阻塞主流程」(同 C6/C7 风格),另由独立链告警兜底;R2 写入量 ~71 文件/日(与现状同量级,非新增总量)。
  - 同步:原注释「alert.json 本地更新,下次 pipeline deploy 推上线」(L175)需改为解耦后口径;§21 公示/README 如涉「预警数据更新链」表述同步(实施时核对)。
- **F3(可选硬化,建议后续)**:①`check_alert` 对称化 s06 式分级(#188 先例 L2168-2187 注释明说「FAIL 会 abort deploy → 死锁」;但注意它**救不了** 10-08 02:06 场景——当时本地也旧,只有 F1 能救;它防的是「R2 旧但本地新」类);②自锁检测:连续 N 轮同项 fail 且本地新鲜 ⇒ 告警文案区分「自锁」+ 附修复指引(现 dedup 6h 窗只压噪音);③机制设计规约入档:「读 R2 的闸门不得拦其自身输入文件的唯一运输通道」。

## 6. 未取到 / 未深究(诚实标注)

1. 「58 用户可见项」口径出处 vs 磁盘 70 个 alert_analyze 文件:差异未深究(未定位 58 的来源定义);不影响「已恢复」判定(抽样 4 + boot + alert.json 全 10-08)。
2. 10-08 23:20 `r2-consistency` FAIL 的具体差异文件清单未取(仅读到告警行);今日 23:20 档未到观察时点。
3. `overview.date` 的字段语义(10-08 时为 20261001、今日为 20261009)未深究,不影响本核查。
4. 未验证 F1/F2 实施细节(改动点行号已给,实施与回归归 implementer/tester);未测任何修复后行为。
5. `/tmp/trade_deploy.lock` 等锁文件状态本次未查(10-08 报告有 1 个未归因观察项,零影响)。
6. 云上 VM 未做任何写操作;「今日 4 轮」= deploy 日志文件枚举(段1 4 个 + 段2 4 个),未再枚举非 deploy 链。

## 7. 证据索引(可复核)

- 代码:`scripts/deploy.sh` L20-22/L145-153/L219/L323-331/L523-567/L582-604/L656;`scripts/check_data_integrity.py` L57-58/L110/L156-162/L253-283/L410-436/L439-464/L522-549/L552-579/L719-747/L899-906/L979-1003/L1966-1973/L2114-2220(L2141/L2144/L2168-2187/L2210/L2214);`scripts/r2_upload_async.sh` L200-226/L223/L250-257;`scripts/upload_r2.py` L2248-2257/L4055-4065;`scripts/update_all.sh` L174-184;`scripts/s06_snapshot.sh` L133;`app/calendar.py` L66/L78/L90。
- 云上日志:`data/logs/deploy_20261009_{0013,0022,0028,0039,0206,0216,0500,0511}.log`(四轮 40/2/0 + 退出码=0);`r2_upload_async_20261009_{002208,021655,051106}.log`(退出码=0)+ `r2_upload_async_skip.log`(00:49);`self_heal_launchd.log` L13509-13531;`deploy_20261008_0206.log`(6 条 ✗ 原文)。
- 云上台账:`.r2_all_data_state.json`(mtime 10-09 05:21;alert md5=65c60ad5…)、`.r2_standalone_keys.json`(alert 系 71 项)、`journalctl -u trade-r2-consistency`(10-08 23:20 fail 行)。
- 线上实测(本机 curl,UA+cache-buster / HEAD):alert.json(10-08,LM 10-09 01:08 北京,etag 65c60ad5…)/ alert_analyze_{hs300,510300,159915,588000}(10-08)/ boot.alert(10-08)/ overview(10-09 13:55)/ notifications(10-09)/ ad_line(末=10-09)。

---
*只读查证报告;未 commit(主控收口)。*
