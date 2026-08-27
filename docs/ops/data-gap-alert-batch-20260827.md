# 采集异常告警兜底批(检测器上线报告)

> 2026-08-27 | implementer agent | 分支 `feat/alert-fallback-batch`(base=origin/main 0fe169f5b)
> 任务来源:pending #103 方案A(用户拍板先行告警兜底)+ S2(用户拍板并入本批)

## 一、做了什么

新增**采集数据缺口/停更告警检测器**,覆盖「上游源停发超窗口后数据洞不自愈,现链路只 print 进日志无人知」一类异常。含 4 个检查器 + 定时挂载 + 监控注册 + two-way 自测,纯监控层新增,不改任何业务采集逻辑。

| # | 检查器(key) | 触发条件 | 级别 | 通道 |
|---|---|---|---|---|
| 1 | `data_gap:north_hole` | a_fund_north 内部断档洞 >15 自然日。洞+无分轮 state=不自愈缺口;洞+有 state=分轮推进中观察;附日志尾部「已越过硬顶」实锤扫描 | SEVERE / WARN | severe→notify --severe(邮件+latest.md);warn→[告警]邮件 |
| 2 | `data_gap:north_stale` | a_fund_north 最新日期落后 >14 自然日(抓「任务 rc=0 但数据没进库」静默面) | SEVERE | 同上 |
| 3 | `data_gap:etf_accum_nav_gap` | etf_daily.accum_nav 窗口外 NULL(cutoff=today-6)超出存量基线 +10 行(warn)/+50 行(severe);首轮自动建档不发告警 | WARN/SEVERE | 同上 |
| 4 | `data_gap:width_gap` | 宽度族单指标 MAX 落后组内参考 >5 天(warn,聚合一条)/≥30 天(severe);GROUP_FULL 内部断档 >15 天;mootdx 源 vs 宽度参考日滞后 | WARN/SEVERE | 同上 |

配套机制:
- **dedup**:同 key 每自然日只发一次(state=data/alerts/data_gap_alert_state.json);转好后发一封 [恢复] 并清 key。
- **人工确认复用**:读 data/alert_state.json 的 acknowledged 字段(alert_ack.py <key> 确认后 24h 免打扰),与 schedule_monitor 维度⑨ 契约一致。
- **dry-run 零副作用**:--dry-run 不发邮件、不落盘 state。
- **环境异常降级**:库缺失时输出 warn 并继续其余检查,不崩。

## 二、阈值依据(全部实测/出处)

| 常量 | 值 | 依据 |
|---|---|---|
| NORTH_HOLE_DAYS=15 | 北向洞阈值 | 主库实测历史最大节假日断档 12 天(2016 国庆);15 留余量零误报 |
| NORTH_STALE_DAYS=14 | 北向停更阈值 | 长假断档 11 天 <14,不误报 |
| ACC_NAV_MAX_AGE=6 | accum NULL 计「窗口外」起始 | T+2 净值发布缓冲再富余 |
| ACC_NAV_NULL_GROW_ALERT=10 / GROW_SEVERE=50 | 基线增量告警线 | 生产实况全史窗口外存量≈376 行(2012 起,历史特性无害),按绝对值告警=永久噪音;故锚定基线只报扩容 |
| WIDTH_LAG_DAYS=5 / LAG_SEVERE_DAYS=30 | 宽度停更容忍 | 3交易日≈5自然日;30 天对齐「停机>30天」语义 |
| WIDTH_HOLE_DAYS=15 | 宽度洞阈值 | 三组 UNION 全史预扫无 >15 天断档 |

调度时点:工作日 22:35——当日晚链全部完成(backfill_evening 21:00/etf_team 21:30/overfit 21:40/信号邮件 22:00)后检测收盘定型数据,与相邻槽位错峰 ≥35min,23:00 安全窗前,秒级完成。

## 三、发现的同类面实例与裁决清单

**真实命中(检测器尚未上线已证实)**:`a_width_zb_count`/`a_width_seal_rate` 自 2026-07-21 停更 37 天(zt/dt/up/down 正常到当日,mootdx 源正常 84 只/日)——正是宽度停更检查器要抓的形态,待检测器上线首日会发第一封真告警。根因修复(疑似 compute_width 的 zb/seal 分支 NaN 全跳过)**不在本批范围**(动 width_history.py 业务逻辑,超任务边界),建议主控派单单独修。

纳入面裁决清单(S2/#103 外的举一反三评估):

| 同构场景 | 裁决 |
|---|---|
| 连续 N 天采集 rc!=0 / log 异常关键词 | 已有(schedule_monitor 维度②②b),不重复做 |
| 任务漏跑/进行中超时 | 已有(维度①+A1),新检测器自身漏跑也已注册进同一机制 |
| 北向内部洞+放弃(S2) | 本批纳入(north_hole,DB 推导为主+日志实锤为辅) |
| 北向整体停更(rc=0 静默失败堆积) | 本批纳入(north_stale) |
| etf accum_nav 窗外缺口(#103 一) | 本批纳入(基线增量口径) |
| width run_recent 限幅外缺口/单指标停更(#103 二+活体先例) | 本批纳入(width_freshness) |
| daily_metric 其余 ~200 个 metric_id 全量保鲜扫描 | **未纳入**(告警面扩张无差别扫会引入未知误报源),留待用户拍板是否列核心 id 白名单扩展 |
| seal_rate/zb_count 根因修复 | 未纳入(业务逻辑改动超边界),上报待派单 |
| mooddx/指数等行业类序列断档(industry_extras 等) | 未纳入(#103 两处之外的相邻实体,无用户拍板不夹带) |

## 四、文件清单

| 文件 | 说明 |
|---|---|
| scripts/check_data_gap_alerts.py | 检测器本体(四 checker+出口+two-way 自测) |
| scripts/check_data_gap_alerts.sh | bash 包装(交易日闸门 fail-open+标准开始/结束行+run_to 300s 防挂死) |
| launchd/com.trade.check-data-gap.plist | 工作日 22:35(plist 内注释含 merge 后 bootstrap 上线命令) |
| scripts/schedule_monitor.sh | TASKS 加 check_data_gap 漏跑/超时检查条目 |
| scripts/gen_schedule_stats.py | TASKS 注册 + LABEL_MAP 映射(stats 展示/launchctl 真实退出码) |
| docs/ops/data-gap-alert-batch-20260827.md | 本报告 |

## 五、上线前置(交主控闭环)

1. merge 后安装 plist:**未加载前检测器不上线**(L45 教训:定时挂载缺一不算 done):
   ```
   cp ~/code/trade/launchd/com.trade.check-data-gap.plist ~/Library/LaunchAgents/
   launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.trade.check-data-gap.plist
   ```
   (plist 若已存在先 bootout 再 bootstrap)
2. 次日 22:36 后验证:data/logs/check_data_gap_launchd.log 有标准行 + 收到 zb/seal 停更首封真告警 + accum 基线建档 info。
3. zb/seal 停更根因修复单独派单。

## 复现

- 脚本:scripts/check_data_gap_alerts.py(单文件自包含)
- 输入依赖:$REPO/data/{sentiment.db, etf_national_team.db, stock_daily.db}(只读)、data/logs/backfill_evening_launchd.log(尾部扫描)、data/north_fund_backfill_state.json
- two-way 自测:`.venv/bin/python scripts/check_data_gap_alerts.py --self-test`(临时库注入,必命中+必不命中各跑一轮,断言失败 exit 1)
- 生产只读冒烟:`.venv/bin/python scripts/check_data_gap_alerts.py --repo /Users/linhuichen/code/trade-data --dry-run`
- 数据截止:2026-08-27(冒烟时点;a_width_zb/seal 停更自 20260721、accum 存量基线 376 行均为当时实测值)
- 关键口径一句话:北向断档洞>15天判不自愈(历史长假最大12天);accum_null 只对超出存量基线+10行的增长告警(存量376行无害);宽度单指标落后参考日>5天告警、≥30天或落后指标语义升级按文案处理。
