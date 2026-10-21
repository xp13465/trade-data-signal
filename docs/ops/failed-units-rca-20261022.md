> 落档:2026-10-22(只读根因调查,原样归档)
> 关联:`docs/ops/batch-fix-20261022.md`、`docs/ops/alert-week-review-20261021.md`

# 云上 6 个 failed unit 根因定位报告（只读，2026-10-22）

调查方式：ssh ubuntu@122.51.111.173（只读命令）+ 云上日志原文 + 本地源码 `文件:行`。全程未重启服务、未改 unit、未跑业务脚本主体、零外发。
数据截点：2026-10-22 02:05 CST；失败天数窗口 = journal `--since "7 days ago"`（约 10-15~10-21）。

## 一、汇总表

| unit | 根因一句 | 首失败(窗口内) | 近7天失败天数 | 优先级 | 需拍板 |
|---|---|---|---|---|---|
| trade-etf-national-team.service | 采集/导出全部成功，死在 deploy 段1 数据闸门：nextday_plan 读到 R2 旧副本 date=20261019 | 10-15（R2 平台故障波；当前形态 10-20 起） | 4 天（15/16/20/21） | B | 否 |
| trade-lhb-backfill.service | 同一闸门（10-15/16 R2 404 → 10-20 a_fund_north → 10-21 nextday_plan），自身采集 exit 0 | 10-15 | 4 天（15/16/20/21） | B | 否 |
| trade-public-fund-daily.service | 结构性：16:20/17:00 跑闸门，而 nav_bucket 只在 17:50 全量链重出 → fund_nav「同日不同值」必阻断；自愈探针只认「DB 领先产物」不认该形态 | 10-15（R2 波；结构根因自 10-19 每天复现） | 5 天（15/16/19/20/21） | B | 是（时点/自愈口径） |
| trade-public-fund-quarterly.service | 同一闸门：10-16 R2 404 波 → 10-20 a_fund_north 季度行滞后 → 10-21 nextday_plan | 10-16 | 3 天（16/20/21） | B | 否 |
| trade-r2-consistency.service | 三站 R2=CF=MAIN 完全一致；是「local 源树 vs 三站」漂移（deploy 闸门阻断跳过 rsync），巡检把 local 当第 4 源对比 → 用户侧零漂移、巡检口径误报；10-15~17 另有 R2/CF/MAIN 平台级故障 | 10-15（当前波次自 10-20，脚本判 critical 2 天） | 5 天（15/16/17/20/21） | B | 是（巡检口径） |
| fwupd-refresh.service | OS 级 LVFS 元数据刷新 exit 1（Downloading 0% → Idle），与本项目无关 | 10-21 | 1 天（当日 2 次） | C | 否（mask 属系统动作，建议前先点头） |

## 二、共同失败链（4 个 trade unit 为什么一起 failed）

`scripts/deploy.sh` 段1 顺序：export → **check_data_integrity 闸门（deploy.sh:359 / 362-385）** → build_min+rsync signal 树（:604 / :622）→ R2 上传（:675）→ 段2 git commit/push（:762）。
闸门退出码 1 ⇒ 整链终止，**rsync 与 R2 上传都在闸门之后，全部跳过**；unit 以 exit 1 结束。
日志统一形态（etf_nt/lhb/daily/quarterly 相同）：
```
✗ 数据产物校验失败(退出码 1)，终止部署（4 类事故拦截）
✗ deploy 失败 (rc=1)
```

## 三、逐 unit 详证

### 1) trade-etf-national-team.service（最后失败 10-21 22:02:54）
采集与导出成功：
```
accum_nav 补齐退出码=0
export_etf_hist 退出码=0
```
当轮闸门明细（22:01:51 轮）：
```
✓ fund_nav: 256 桶/26683 只基金全史净值，抽样 30 只结构+DB逐位一致，覆盖率 ≥95%
✗ nextday_plan: date=20261019 不是最近交易日/当前交易日/下一交易日 (允许=['20261020', '20261021', '20261022'])
=== 汇总: 43 ok / 0 warn / 1 fail ===
✗ 数据产物校验失败(退出码 1)，终止部署（4 类事故拦截）
[etf_nt] daily 完成 151.0s exit=1
```
nextday_plan 旧副本的成因（10-20 22:30 轮）：
```
[nextday_plan] ⚠ R2 上传超时(480s, 将告警)
=== nextday_plan.sh 结束 2026-10-20 22:38:12 退出码=1 ===
```
→ R2 停在 date=20261019，而本地副本已是 20261020；旧校验只读 R2 ⇒ 自锁。10-21 22:30 轮已修复：`R2 退出码=0 / 共上传 3/3`，本地两树 `nextday_plan.json` 均 `"date": "20261021"`。
历史波次：10-15/16 R2 404（alert/notifications/nextday_plan/signal_kelly_day_snapshot）；10-20 a_fund_north_quarterly 季度行 20260630 != 20260930（10-21 已自愈，后续轮不再报）。
优先级 B（数据滞后可补，10-22 00:42 闸门已 44 ok/0 fail，R2 已补 20261021）。

### 2) trade-lhb-backfill.service（最后失败 10-21 19:38:15）
```
龙虎榜采集退出码=0(0=有新数据,非0=源未发布/为空)
✗ nextday_plan: date=20261019 不是最近交易日/当前交易日/下一交易日 (允许=['20261020', '20261021', '20261022'])
✗ 数据产物校验失败(退出码 1)，终止部署（4 类事故拦截）
```
历史波次：10-15/16 R2 404 ×4 项；10-20 `a_fund_north_quarterly` 滞后 + `trade_sim_indices.json mtime 滞后 8 天`；10-21 nextday_plan。
**外部源未失败**（采集 exit 0，失败发生在其后的部署闸门）⇒ 不涉及外部源社区佐证；未做外部检索。
优先级 B（同上，闸门修复后自动恢复）。

### 3) trade-public-fund-daily.service（最后失败 10-21 17:07:06）
运行两轮：16:20 / 17:00（timer 实查：上次 17:00、下次 16:20）。两轮均阻断，且**自愈不认该形态**：
```
✗ fund_nav: DB↔产物不一致: 015854: [最新日期相同但数值不一致(疑似净值修正)] ...   (10-21 16:31 轮)
✗ fund_nav: DB↔产物不一致: 005343: [最新日期相同但数值不一致(疑似净值修正)] ...   (10-21 17:00 轮)
[fundnav-stale-probe] rc=0 未命中 DB 领先产物(抽样 0 只, 不一致 0 只且方向非 DB 领先)
→ fund_nav 自愈未命中(非「DB 领先产物」方向), 走原终止逻辑
```
同类历史：10-19 17:00（019597）、10-20 17:00（007441）；10-20 另叠加 a_fund_north，10-21 叠加 nextday_plan。
结构性原因：nav_bucket 只在 17:50 全量链刷新（`scripts/update_all.sh:101-120` export_fund_nav → nav_bucket rsync）；daily 16:20/17:00 早于它，当日新净值已入库、产物还是旧值 ⇒ 必然「同日不同值」。自愈脚本只命中「DB 领先产物」方向（`scripts/fund_nav_selfheal.sh` 探针 exit 0/3/10 路由），该形态 rc=0 直接走终止。
#266 影响：**未影响数据新鲜度**。fund_score.json 已于 10-21 18:56 更新（17:50 全量链）；持仓估算产物 10-22 00:26 重生成，`report_date=20261020`。daily 失败只延迟 16:20/17:00 两轮增量上线，17:50 全量兜底。
优先级 B；需拍板：① daily 时点是否挪到 17:50 之后（或 deploy 前先刷新 nav_bucket）② 自愈是否扩「同日不同值」方向。注意 fund_nav 是用户 10-13 拍板必须保持阻断级，**不能降 Alert**。

### 4) trade-public-fund-quarterly.service（最后失败 10-21 07:12:46）
```
✗ nextday_plan: date=20261019 不是最近交易日/当前交易日/下一交易日 (允许=['20261020', '20261021', '20261022'])
✗ 数据产物校验失败(退出码 1)，终止部署（4 类事故拦截）
✗ deploy 失败 (rc=1)
```
历史波次（按出现次数）：R2 404 ×5（10-16 波）、`a_fund_north_quarterly` 季度行滞后 ×3（10-20 波，10-21 已自愈）、nextday_plan ×3（10-21 波）。
与 #266 同域但未见 266 新鲜度受损（季度产物最终由 17:50 全量链/次日重算覆盖）。
优先级 B；闸门修复后自动恢复，无需单独拍板。

### 5) trade-r2-consistency.service（最后失败 10-21 23:24:15）
**具体不一致项（10-21 23:20 轮原文）**：
```
✗ [overview] date: {'R2':'20261021','CF':'20261021','MAIN':'20261021','local':'20261019'};
             sig_159739: {'R2':87.4,'CF':87.4,'MAIN':87.4,'local':87.0}
✗ [concepts] thsc_300816_159258: {'R2':36.6,'CF':36.6,'local':35.7};
             thsc_308700_512480: {'R2':30.3,'CF':30.3,'local':30.4};
             thsc_309119_560770: {'R2':35.8,'CF':35.8,'local':37.5}
```
10-20 五项：overview / nextday_plan / auto_trade_steps / signal_kelly_day_snapshot / accum_nav_map（local 有领先也有落后）。
10-15~17 波次为平台级故障：
```
✗ [signal_kelly_day_snapshot] R2 拉取失败: HTTP Error 403: Forbidden
✗ [signal_kelly_day_snapshot] CF 拉取失败: HTTP Error 502: Bad Gateway
✗ [signal_kelly_day_snapshot] MAIN 拉取失败: HTTP Error 404: Not Found
```
**判定（真漂移 vs 巡检误报）**：
- 三站 R2=CF=MAIN **完全一致** ⇒ 用户侧零展示不一致（§22 目标未被破坏）。
- `local` = `/home/ubuntu/code/trade-data-signal/static-site/data`（`scripts/check_r2_consistency.py:4`，经 trade-data/scripts symlink 实指向 signal 树），是 deploy 段1 rsync 的目标；闸门阻断跳过 rsync（deploy.sh:622 在闸门之后），而 R2 已由其它上传路径更新 ⇒ local 滞后/领先。
- 所以：**不是「三站互漂移」；是「部署链被闸门掐断」的真实症状 + 「巡检把 local 当第 4 源直接比」的口径误报**。脚本设计本意（:337-345）是用 local 抓 R2 被旧库覆盖，方向定义合理，但当前场景方向相反（local 旧、线上新），报「不一致」但用户无损。
- 社区核查：对 R2 `403 NotEntitled`/CF 502 做过一轮 WebSearch，未命中同源社区帖 ⇒ 该波次**仅日志证据**，不冒充外部佐证。
优先级 B；需拍板：巡检是否改为「三站互比为主 + local 单独提示」，或把 local 落后方向降级。
今日 00:42 起 rsync 已恢复（nextday_plan/公募产物两树已对齐），23:20 轮复验。

### 6) fwupd-refresh.service（最后失败 10-21 23:02:54）
```
fwupdmgr[...]: Updating lvfs
fwupdmgr[...]: Downloading…: 0%
fwupdmgr[...]: Idle…: 100%
systemd[1]: fwupd-refresh.service: Failed with result 'exit-code'.
```
OS 级 LVFS 元数据刷新失败，与本项目无关。但它会污染 failed-unit 通道：`scripts/alert_denoise_rules.py:373-385 parse_failed_units` 只按 `.service/.timer/.socket` 收名，`check_failed_units.py` 无项目白名单 ⇒ fwupd 也会进告警签名。优先级 C；建议 mask（系统动作，执行前点头）或加非项目白名单。

## 四、与 10-15 后代码改动相关性（结论：无因果，另有「解药」）

- **点名 4 个提交全部晚于最后一批计划性失败（10-21 23:24:15），时间上不能是致因**：
  - `808ec8a33`（10-21 23:35）只改 `app/collector/cov_value.py`/`fetchers.py`（cov 采集），不触 deploy 闸门；且四 unit 采集本身 exit 0。
  - `c79bd21e8`（10-22 00:23）改 `alert_denoise_rules.py`/`check_failed_units.py`/unit 文档，只影响告警可见性，不影响 unit 执行。
  - `2b2841454`（00:52）统一 bump + min/index 版本串，晚于 00:42 的 §24⑤ 失败，不是该次致因；列为观察项（若后续 min 校验复现，需查 build_min 与 HEAD 一致性）。
  - `1d967b49b`（01:13）是告警黑洞修复的合并提交，属解药不是致因。
- **真正相关的是 `431b10818`（10-21 23:56）**：`check_data_integrity.py` 分级（alert-only 非阻断）+ nextday_plan 改本地副本优先 + deploy 失败追踪。它是修复，不是致因；证据：10-22 00:42 轮 `=== 汇总: 44 ok / 0 warn / 0 fail ===`、`✓ 数据产物校验通过`。
- **10-15 之前的直接致因**（与上述提交无关）：①10-15~17 R2/CF/MAIN 平台故障（403/502/404）；②10-20 a_fund_north_quarterly 季度行滞后；③10-20 22:30 nextday_plan R2 上传超时 480s → R2 旧副本 → 10-21 各轮自锁；④daily 的 16:20/17:00 vs 17:50 nav_bucket 时点矛盾（结构性问题，非本批改动引入）。
- **新观察（待复验）**：10-22 00:42 轮数据闸门已过，但 §24⑤ 版本一致性失败：
```
min 内容与 git HEAD 源重建不一致: purpose-notes.min.js(当前 22306377 ≠ HEAD重建 e44dbcbe)
min 内容与 git HEAD 源重建不一致: app.min.js(当前 87dbf668 ≠ HEAD重建 0f658507)
✗ 版本一致性校验失败(退出码 1)，终止部署(§24⑤ FAIL 阻断上线)
```
云上当前 HEAD=dc242231d（01:50:39）、工作区 clean；此失败仅在 00:42 轮出现一次，其它近期日志未见 ⇒ 大概率合并窗口瞬态，待 02:00 后轮次复验；若复现则按真问题查。

## 五、修法建议（三组）

**立即修（需拍板）**
1. daily 的 fund_nav 时点/自愈口径：方案 A「daily 在 deploy 前先刷新 nav_bucket（复用 export_fund_nav + rsync）」；方案 B「自愈探针新增『同日不同值（疑似净值修正）』方向，重出产物后再检」。两者都不降 fund_nav 阻断级（守 10-13 拍板）。推荐 A（治因，16:20 前产物即最新），B 作兜底。
2. r2-consistency 口径：改为「三站互比为主」+「local vs 三站」单独提示（不参与 FAIL 判据），或 local 落后方向降级为 warn。修好 deploy 链后 local 会自然追平。

**观察（不额外动手）**
- etf_nt / lhb / quarterly：闸门已修，等各自下一轮（今日 20:07/21:30、18:30/19:30、07:00 附近）复验 `systemctl --failed` 是否清空。
- §24⑤ 版本一致性：看 02:00 后轮次是否复现。
- 10-22 23:20 r2 巡检：local 已由 00:42 rsync 追平，预期仅剩真实差异项。

**降噪不修**
- fwupd-refresh：与本项目无关。建议 `systemctl mask fwupd-refresh.timer`（系统动作，先点头）；或给 failed-unit 巡检加非项目白名单（代码改动，另派）。

## 六、安全声明
本单全程只读：未重启/停止任何服务、未改 unit/timer、未执行业务脚本主体、未触发任何通知外发。仅有的写操作 = `/tmp/agent-progress-failed-units-rca.md` 进度与本报告。curl 均为 GET、无 `-v/-i`。后台残留任务：无。
