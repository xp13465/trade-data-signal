# 周例行 review 报告:memory 周 review + 告警 L5(2026-10-11)

> 执行:researcher 子 agent(只读;唯一写操作=本报告)。范围:memory 全库(索引 MEMORY.md + 全部 .md)+ 告警收敛 L5。
> 上次先例:memory-weekly-review-20260927.md / memory-orphan-audit-20260927.md(本轮到期间隔 14 天,含一周空缺)。
> 口径依据:CLAUDE.md §19 + §5.3 + docs/ops/alert-convergence-plan-20261010.md §7(L5:「连续 7 天 P50≤3 且 P90≤5;每周 review top-talkers + 被吞条目找回核对」)。

## 一、结论总览(先行)

### A. memory 周 review

| 维度 | 结果 |
|---|---|
| 过时(需修订) | **11 个文件 + 1 条索引行**:高 6(代理/模型端点簇)+ 中 1(alert-dedup-mechanism)+ 低 4(路径引用漂移);另 1 保留+加注;删除 0 |
| 索引双向机检 | 索引→文件链接 224 条 / **死链 0**;文件→索引孤儿 15(**全部=甲类设计**,与 09-27 审计逐字一致,未扩大);09-27 后新增/修改文件全部已登记(最新 5 个含 10-11 刷新件,**新增未登记 0**) |
| 合并候选 | **0**(agent 判活/状态簇等已由索引层一行多链接聚合;文件间触发场景不同,不建议文件级硬合) |
| 下沉候选 | 新增 0;上轮 4 条候选:1/2(§24、§8.1)**已落实为指针化**、3/4(§0 表、§5.5)维持保留;根 CLAUDE.md 现 51,989B/254 行(较 09-27 的 48,903B,+3,086B/14 天;增量来源=用户拍板 §25 删除前必备份铁律 + §18 防重犯滚动窗口 L36~L50 + §0.2 机检③/§8 CI 自查,**均为必留核心,属合规增长,不下沉**) |
| 本日新增登记 | 10-10~10-11 新增/刷新 5 文件(push-main-then-check-ci 等)全部已登记 ✓ |

### B. 告警 L5(对照 convergence-plan §7)

| 维度 | 结果 |
|---|---|
| top-talkers(监测面,本周) | ①**计划任务异常/unit 巡检族 ~26 条** ②**R2 族 ~7 条** ③**deploy 族 4 / 数据缺口族 4 条** |
| top-talkers(实际外发面) | 本周 24 条=告警 16 + 恢复 8;16 条告警**全部**=「[cloud] N项计划任务异常」(unit 巡检族) |
| 被吞条目找回核对 | 设计内抑制 593 条**均可经 last_alerted/任务名回溯找回,非丢失**;真吞(修复前)=恢复类被 6h 抑制窗吞 ≥5 个案(10-08~10-09)→ #245 批2 D5(10-10)已修,**修后 0 吞** |
| L5 正式判决 | **数据不足,未判决**——台账 10-10 08:27 起,连续 7 天 P50/P90 判决最早 ~10-17;替代基线(重建口径,非台账口径)粗算 P50=2 达标 / P90=19.4 超 5(拥堵主因 10-08/10-09) |
| 数据缺口 | 6 项如实标注(见 §四.3) |

## 二、memory 过时明细(改/删/保留 建议)

### 高(代理/模型端点簇,整体已再次过时)——建议:6 文件各加「状态注」+ 索引行改状态词

现网证据:本机 `~/.claude/settings.json`(mtime 10-10 07:56)ANTHROPIC_BASE_URL=`ws-46vmklrma92x8nkw.cn-beijing.maas.aliyuncs.com/apps/anthropic`(阿里 MaaS),全模型=deepseek-v4.1-flash;商汤 8899 轮换代理未加载/无监听/日志停于 10-05 11:58;memory 自身 mac-403-ipv6-direct-egress(10-08)亦记 MaaS 端点。

| # | 文件 | 漂移点 | 建议 |
|---|---|---|---|
| 1 | deepseek-thinking-perrole-proxy.md | 所述「商汤轮换」链路已停用 | 改:加状态注(10-05 起现网=Aliyun MaaS;商汤链路保留可回切) |
| 2 | thinking-proxy-config-sop.md | 同上(SOP 对象=已停链路) | 改:同上 |
| 3 | sensenova-linear-cool-cooldown-overkill.md | 冷却结论为历史实测 | 改:同上 |
| 4 | sensenova-rpm-rate-limit.md | 同上 | 改:同上 |
| 5 | openrouter-config-websearch-effort-keychain.md | 「已回切商汤8899」不再成立 | 改:同上 |
| 6 | opencode-cache-think-findings.md | 现网状态过时 + 文档路径已归档(见低危) | 改:同上 + 路径 |
| 7 | MEMORY.md L14 索引行 | 「(现网=商汤轮换8899)」「(已回切商汤8899)」 | 改:改「现网=Aliyun MaaS(10-05 起;商汤轮换停用)」 |

说明:此簇 6 文件为「按需再激活」类(触发=429/切端点/调 effort),**不建议删**(商汤链路保留可回切、429 处置知识仍有效),只改状态注防误判。

### 中——建议:改

| # | 文件 | 漂移点 | 证据 | 建议 |
|---|---|---|---|---|
| 8 | alert-dedup-mechanism.md | ①L10「launchd 每15min 触发」| 现状=云上 systemd timer(`schedule_monitor`;本机 mac 纯开发不跑定时任务,§14) | 改:调度器表述→云上 systemd |
| | | ②L16「逻辑 scripts/schedule_monitor.sh L209-279」行号漂移 | 现码:去重 key 构造 L832-835(`{task}|{keyword}|md5(line前80字符)[:8]`,与 memory 描述一致);24h stale 注释块 L489-500;状态文件注 L296 | 改:行号→按现码引用 |
| | | ③未涵盖 #245 批2 恢复吞没修复 | 恢复类被 6h 窗吞已由 D5 修复入 pending 桶重发(10-10) | 改:补注「恢复必达(批2 D5;恢复被吞并入 pending 重试)」 |

核心机制(状态文件路径/去重 key 格式/24h stale 降级)经现码核对**仍有效**。

### 低(路径引用漂移)——建议:改路径(3)/加注(2)

| # | 文件 | 引用路径 | 实物 | 建议 |
|---|---|---|---|---|
| 9 | ai-predict-self-growth-research.md | `docs/ai-predict-self-growth.md` | 已移入子目录:`docs/ai-predict/ai-predict-self-growth.md`(docs/research-index.md L48 权威) | 改路径 |
| 10 | daily-brief-deepseek.md | `docs/daily-brief-research.md` | 真身 `docs/ai-predict/daily-brief-research.md`(research-index L51) | 改路径 |
| 11 | opencode-cache-think-findings.md | `docs/thinking-off-opencodego-research-20260821.md` | 已归档 `docs/archive/thinking-off-opencodego-research-20260821.md` | 改路径(或注「已归档」) |
| 12 | new-feature-isolated-tab-first.md | `web/lab.js` | `web/` 目录已不存在;现前端=`static-site/lab.js`(同句已列) | 加注:历史路径 |
| 13 | open-source-dual-repos.md | `scripts/gen_data_manifest.py` / `scripts/release_db.sh` / `data/manifest.json` / `fetch_data.sh` | 均为**开源仓**产物(该 memory 自述「迁移到独立仓库,开发库只留代码」;本库已无,符合预期) | 保留+加注「(开源仓)」;本机无开源仓克隆,引用对象不可本机核验(如实标注) |

**删除:0。** 无「应删」项。

## 三、索引双向机检(复现见 §六)

- 索引→文件:224 条链接 / 死链 **0**。
- 文件→索引:孤儿 **15**,逐字=memory-orphan-audit-20260927.md 甲类 15 清单(甲类=已升格 CLAUDE.md 设计,如 [[self-growth-mechanism]],属设计保留,**非缺陷**)。
- 新增未登记:**0**(09-27 后新增/修改的 50+5 文件均已登记;含 10-11 01:37 刷新的 push-main-then-check-ci.md)。
- MEMORY.md 自身体积 28,089B(10-10 07:44)。

## 四、告警 L5 明细

### 4.1 top-talkers(按来源/关键词聚合)

**监测面**(运行树 `cloud_latest.md` severe 流水 50 条——正好 cap50 满,覆盖 10-05~10-11 完整一周;信号树 `cloud_latest_signal.md` 另 +1 条 10-09):

| 排名 | 族 | 条数 | 构成 |
|---|---|---|---|
| 1 | 计划任务异常/unit 巡检 | ~26 | 「云上 unit 巡检发现异常(1项)」×13 + 「N项计划任务异常」×13 |
| 2 | R2 族 | ~7 | R2上传失败×4 / fund-nav R2 异步×1 / R2 异步触发失败×1 / R2 末尾 purge×1 |
| 3 | deploy 族 | 4 | deploy 数据产物校验失败×3 + update_all 统一 deploy 失败×1 |
| 3 | 数据缺口族 | 4 | 公募基金全 NULL×2 + 交易记录落后×1 + 交易记录断档×1 |
| — | 单项 | 各1~2 | systemd 漂移×2 / 伪跳空×2 / kelly 盘中×1 / 心跳超时×1 / §22 三站一致性×1 |

**实际外发面**(云上 monitor.log「邮件已发送至」行,10-05~10-11):24 条 = 告警 16 + 恢复 8;告警 16 条**全部**为「[cloud] N项计划任务异常」(unit 巡检族,按天 10-05:4 / 10-07:2 / 10-08:6 / 10-09:4)。

两口径共同指向:**本周第一大来源=云上 failed unit 族**(与 #248「gap-check 连续 failed 告警深挖」立项一致;次生来源=R2/deploy/数据缺口)。

### 4.2 被吞条目找回核对(对照 §7)

- **设计内抑制(非丢失)**:本周 `[suppress]`/派生抑制行 **593 条**,每条含 `last_alerted`(首报时间)与任务名,**可回溯找回**;TOP:cloud_unit_patrol 192 / nextday_gap_check 188 / r2_consistency 96 / etf_national_team 91 / backfill_evening 18 / fetch_news 8。另有 `[recurrence-suppress]`(恢复后 <6h 复现不重发,etf_national_team 退出失败,本周 3 条)=设计行为。
- **真吞(修复前)**:恢复类邮件被 6h 抑制窗吞,≥5 个案——host_resource 10-08 19:23;fetch_news 10-09 00:00 / 02:00 / 23:00;backfill_evening 10-09 02:30。根因与处置见 #245 批2(schedule_monitor.sh L3000-3094 D5:被吞/失败的恢复并入 `monitor_recovery|pending` 桶重试)。
- **修复后验证**:10-10 21:58 之后恢复类抑制行 **0**;pending 桶空(10-11 05:00 补列 0);10-11 05:00 恢复实测外发(`[恢复] fetch_news r2_skip_continuous`,台账可查)——「恢复必达」不变式恢复成立。
- **被合并条目**:10-11 04:30 warning 聚合 1 条(merged_count=1),台账 `cloud_ledger.jsonl` 第 6 行 + `alert_daily.json`(merged_in_digest=1)双源可查;L2 摘要(23:25 flush)窗口本周吸收 0 条。

### 4.3 L5 判决与数据缺口(如实标注)

- §7 正式口径「连续 7 天 P50≤3 且 P90≤5」:**未判决**——台账 10-10 08:27(部署 10-10 01:18)起才有数据,**最早 ~10-17 可判**。当前台账 7 行:critical 3 / warning 1 / notice 2 / report 1(10-10:2 alert;10-11:4 alert)。
- 替代基线(**重建口径 ≠ 台账口径,仅趋势参考**):运行树 severe 按天 3/1/2/17/23/2/2 → P50=2.0(达标)/ P90=19.4(超 5;主因 10-08=17、10-09=23 的 gap-check 拥堵窗口)。
- 数据缺口 6 项:①台账起点晚(10-10),P50/P90 无 7 天窗口 ②运行树 latest.md cap50=满,10-05 前已滚出 ③信号树 latest.md 滚动慢(50 条覆盖 09-23 起)④本地台账含 19 条合成行污染(pytest 薄包装不隔离 REPO,245-batch2 §八.4 已载;生产数字须用云台账)⑤本地无 alert_daily.json ⑥info_log(自愈类)仅 70 行(09-25 起),覆盖面窄。

## 五、建议(优先级)

1. (高)代理簇修订:6 文件加状态注 + MEMORY.md L14 索引行改「现网=Aliyun MaaS」——A 级小改,建议派 implementer。
2. (中)alert-dedup-mechanism.md:调度器表述 + 行号 + 批2 恢复必达注记。
3. (低)4 处路径引用修订 + open-source-dual-repos 加「(开源仓)」注。
4. (告警跟进)failed unit 族=本周第一大来源,#248 深挖在跑,按要求继续跟踪;10-17 满 7 天后出 L5 正式判决(via alert_meter.py)。
5. (机制)恢复必达的日常复核:每周 review 抽查「恢复类抑制=0 + pending 桶空」两项,列入 L5 周 review 固定项。

## 六、复现段(命令与数据源)

- **索引机检**:脚本 `/tmp/mem-check-b1.py`(链接/死链/孤儿/未登记四项,复跑一次出结论);孤儿基准对照 `/Users/linhuichen/.claude/projects/-Users-linhuichen-code-trade/memory/memory-orphan-audit-20260927.md`。
- **代理簇现状**:`python3 -c "import json;print(json.load(open('/Users/linhuichen/.claude/settings.json'))['env']['ANTHROPIC_BASE_URL'])"`;`lsof -i :8899` 空 + 商汤日志止于 10-05 11:58。
- **alert-dedup 现码**:`grep -n "md5\|24h\|stale" /Users/linhuichen/code/trade/scripts/schedule_monitor.sh`(key 构造 L832-835;24h stale L489-500)。
- **告警聚合(本周)**:
  - 监测面:`grep -h "^## \[severe\]" /tmp/b1-alerts/cloud_latest.md /tmp/b1-alerts/cloud_latest_signal.md | sed -E 's/^## \[severe\] (2026-10-[0-9]{2}).*/\1/' | sort | uniq -c`
  - 外发面:`grep '邮件已发送至' /tmp/b1-alerts/cloud_monitor.log`(正则取行尾时间 10-05~10-11)。
  - 抑制面:`grep -c 'suppress' /tmp/b1-alerts/cloud_monitor.log`(593 条为本周;全历史 5206)。
  - 台账:`/tmp/b1-alerts/cloud_ledger.jsonl`(7 行)+ `cloud_daily.json`(10-11:total=4/merged_in_digest=1)+ `cloud_alert_state.json`(163 键)。
  - 百分比口径:线性插值(同 alert_meter.py `_percentile`)。
- **数据拉取(云上只读)**:`ssh -i ~/tdsignal.pem -4 ubuntu@122.51.111.173`(云上 ~/code/trade-data);台账/日志源路径 `data/alerts/alert_ledger.jsonl`、`data/alerts/alert_daily.json`、`data/logs/schedule_monitor*.log`、`data/monitor/latest.md`。
- **报告落盘**:本文件(唯一写操作;未 commit——在 feat/next-steps-b2-lowrisk 工作区,由主控处置)。
