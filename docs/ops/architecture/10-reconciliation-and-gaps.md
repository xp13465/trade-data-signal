# 声明、部署与运行对账

本页基于本次固定代码基线和带时点的只读观察，列出已确认对齐与未知项，不把匹配成功解释为业务健康。机器结果见[inventory/reconciliation.json](inventory/reconciliation.json)。

## 一、已核对的范围

- 仓库声明的systemd业务任务 **44** 项，对应云端 **44 service + 44 timer**；精确单元名全部匹配。
- 安全提取的脚本入口basename全部匹配；参数、内层调用、锁、重试与每项业务结果不是本项匹配的结论。
- 44个timer共85个完整OnCalendar表达式已取证；43项字面集合一致，1项经显式日期通配符规范化一致。
- 运行侧同时可见8条cron外围记录，包含系统维护和非本项目归属未核项；不把它们当8个异常或擅自删除。
- 本机当前用户launchd可见3个com.trade标签（2个带PID，1个无PID）（launchd 已废弃/历史存档，生产定时任务已迁云上 systemd timer，本机 mac 纯开发不跑生产定时任务），仓内模板不等于这些机器上全部启用。
- 共有72条仓库声明记录（含44项cloud任务、launchd模板、CI、手动/条件入口及历史文档），与运行侧unit数量口径不同。

业务任务task:id、实际service执行单元cloud-service:id和timer触发器cloud-timer:id是不同对象，通过对账关系连接；不能把三行算三项独立业务任务。catalog对同id的多来源观察分隔保留，同名不静默覆盖。

## 二、已配对的cloud任务

| 业务任务 | service/timer | 日历对照 | 入口对照 |
| --- | --- | --- | --- |
| `task:ab-direction-anchor` | `trade-ab-direction-anchor.service` / `trade-ab-direction-anchor.timer` | 表达式集合一致 | same_script_basename |
| `task:alert-weekly-review` | `trade-alert-weekly-review.service` / `trade-alert-weekly-review.timer` | 表达式集合一致 | same_script_basename |
| `task:backfill-evening` | `trade-backfill-evening.service` / `trade-backfill-evening.timer` | 表达式集合一致 | same_script_basename |
| `task:backup-db` | `trade-backup-db.service` / `trade-backup-db.timer` | 表达式集合一致 | same_script_basename |
| `task:brief-push` | `trade-brief-push.service` / `trade-brief-push.timer` | 表达式集合一致 | same_script_basename |
| `task:check-data-gap` | `trade-check-data-gap.service` / `trade-check-data-gap.timer` | 表达式集合一致 | same_script_basename |
| `task:check-monitor-heartbeat` | `trade-check-monitor-heartbeat.service` / `trade-check-monitor-heartbeat.timer` | 表达式集合一致 | same_script_basename |
| `task:cloud-unit-patrol` | `trade-cloud-unit-patrol.service` / `trade-cloud-unit-patrol.timer` | 表达式集合一致 | same_script_basename |
| `task:daily-brief` | `trade-daily-brief.service` / `trade-daily-brief.timer` | 表达式集合一致 | same_script_basename |
| `task:daily-summary-supplement` | `trade-daily-summary-supplement.service` / `trade-daily-summary-supplement.timer` | 表达式集合一致 | same_script_basename |
| `task:etf-national-team` | `trade-etf-national-team.service` / `trade-etf-national-team.timer` | 表达式集合一致 | same_script_basename |
| `task:etf-track-index` | `trade-etf-track-index.service` / `trade-etf-track-index.timer` | 表达式集合一致 | same_script_basename |
| `task:fapi-daily` | `trade-fapi-daily.service` / `trade-fapi-daily.timer` | 表达式集合一致 | same_script_basename |
| `task:fetch-news` | `trade-fetch-news.service` / `trade-fetch-news.timer` | 表达式集合一致 | same_script_basename |
| `task:fof-nav-collect` | `trade-fof-nav-collect.service` / `trade-fof-nav-collect.timer` | 表达式集合一致 | same_script_basename |
| `task:freeze-orphan-cleanup` | `trade-freeze-orphan-cleanup.service` / `trade-freeze-orphan-cleanup.timer` | 表达式集合一致 | same_script_basename |
| `task:futures-backfill` | `trade-futures-backfill.service` / `trade-futures-backfill.timer` | 表达式集合一致 | same_script_basename |
| `task:gold-night` | `trade-gold-night.service` / `trade-gold-night.timer` | 表达式集合一致 | same_script_basename |
| `task:intraday-snapshot` | `trade-intraday-snapshot.service` / `trade-intraday-snapshot.timer` | 表达式集合一致 | same_script_basename |
| `task:kelly-intraday-rerun` | `trade-kelly-intraday-rerun.service` / `trade-kelly-intraday-rerun.timer` | 表达式集合一致 | same_script_basename |
| `task:lab-auto` | `trade-lab-auto.service` / `trade-lab-auto.timer` | 表达式集合一致 | same_script_basename |
| `task:lhb-backfill` | `trade-lhb-backfill.service` / `trade-lhb-backfill.timer` | 表达式集合一致 | same_script_basename |
| `task:lof-track-index` | `trade-lof-track-index.service` / `trade-lof-track-index.timer` | 表达式集合一致 | same_script_basename |
| `task:nextday-gap-check` | `trade-nextday-gap-check.service` / `trade-nextday-gap-check.timer` | 表达式集合一致 | same_script_basename |
| `task:nextday-plan` | `trade-nextday-plan.service` / `trade-nextday-plan.timer` | 表达式集合一致 | same_script_basename |
| `task:overfit-monitor` | `trade-overfit-monitor.service` / `trade-overfit-monitor.timer` | 表达式集合一致 | same_script_basename |
| `task:pf-score-daily` | `trade-pf-score-daily.service` / `trade-pf-score-daily.timer` | 表达式集合一致 | same_script_basename |
| `task:pf-score-weekly` | `trade-pf-score-weekly.service` / `trade-pf-score-weekly.timer` | 表达式集合一致 | same_script_basename |
| `task:pf-stage0-manager` | `trade-pf-stage0-manager.service` / `trade-pf-stage0-manager.timer` | 表达式集合一致 | same_script_basename |
| `task:pf-stage0-nav` | `trade-pf-stage0-nav.service` / `trade-pf-stage0-nav.timer` | 表达式集合一致 | same_script_basename |
| `task:pf-stage0-overview` | `trade-pf-stage0-overview.service` / `trade-pf-stage0-overview.timer` | 表达式集合一致 | same_script_basename |
| `task:pf-stage0-risk` | `trade-pf-stage0-risk.service` / `trade-pf-stage0-risk.timer` | 表达式集合一致 | same_script_basename |
| `task:public-fund-daily` | `trade-public-fund-daily.service` / `trade-public-fund-daily.timer` | 表达式集合一致 | same_script_basename |
| `task:public-fund-estimation` | `trade-public-fund-estimation.service` / `trade-public-fund-estimation.timer` | 表达式集合一致 | same_script_basename |
| `task:public-fund-full` | `trade-public-fund-full.service` / `trade-public-fund-full.timer` | 表达式集合一致 | same_script_basename |
| `task:public-fund-quarterly` | `trade-public-fund-quarterly.service` / `trade-public-fund-quarterly.timer` | 表达式集合一致 | same_script_basename |
| `task:r2-consistency` | `trade-r2-consistency.service` / `trade-r2-consistency.timer` | 表达式集合一致 | same_script_basename |
| `task:rzhb-backfill` | `trade-rzhb-backfill.service` / `trade-rzhb-backfill.timer` | 表达式集合一致 | same_script_basename |
| `task:s06-snapshot` | `trade-s06-snapshot.service` / `trade-s06-snapshot.timer` | 表达式集合一致 | same_script_basename |
| `task:schedule-monitor` | `trade-schedule-monitor.service` / `trade-schedule-monitor.timer` | 表达式集合一致 | same_script_basename |
| `task:self-heal` | `trade-self-heal.service` / `trade-self-heal.timer` | 表达式集合一致 | same_script_basename |
| `task:turnover-backfill` | `trade-turnover-backfill.service` / `trade-turnover-backfill.timer` | 表达式集合一致 | same_script_basename |
| `task:update-all` | `trade-update-all.service` / `trade-update-all.timer` | 显式日期通配符规范化后一致 | same_script_basename |
| `task:us-stock-morning` | `trade-us-stock-morning.service` / `trade-us-stock-morning.timer` | 表达式集合一致 | same_script_basename |

## 三、尚未验收的覆盖缺口

| 项目 | 当前证据与边界 | 下一步/责任 |
| --- | --- | --- |
| 业务正确性 | 本次是架构盘点；active/exit0/名称日历匹配不能代替业务必要条件 | Claude明确任务结果合同，Codex按具体范围独立验收 |
| 常驻/外部控制面 | 云端本范围44项均oneshot；CF Workers/Pages/R2/DNS等只读源码配置，未控制面核验 | 主控补实际部署资源/域名路由证据，分配稳定对象id |
| timer完整日历 | 初次解析重复TimersCalendar键会丢值；已用定向白名单补采全部85项 | 本次已修正盘点，不将初稿9项部分观察当配置漂移 |
| 运行层failed记录 | turnover-backfill服务观测为failed/exit124，业务影响未核；可能是已有失败状态 | 对照最近日志、该次run和数据结果后定影响，不能reset failed充当修复 |
| 任务内层门控/锁/重试 | 源清单记录候选；未逐入口全路径运行验证 | Claude给依赖与时间合同；按风险优先补证，避免只加超时 |
| 本机模板/实际注册 | current-user范围之外的LaunchDaemons、其他用户、disable override未核 | owner按实际运维职责补证；未观测不等失败 |
| 新鲜度/交易日规则 | 不同市场、节假日、晚到数据与截止时间需逐任务合同 | 面板按预期窗口与证据有效期，过期显示unknown |
| 发布可见性 | 本轮未访问三站/R2/CDN控制面、未重读所有远端产物 | 复用manifest/proof/消费者校验，分开上传/purge/站点生效 |
| 备份恢复 | 代码路径已登记，但本轮没执行恢复演练或重新解释107旧差额 | 将DB及冻结/映射等关键非DB输入覆盖纳入独立验收 |
| 历史事故根因与观察 | 18条台账范围内有旧证据未知；未开展新的自然周期观察 | 按11台账关闭条件补证，不用completed或静默自动根治 |
| 模板与说明口径 | fetch-news说明与配置文字口径、一份plist严格解析异常已在源清单注明；本机部署状态未由此判定 | 核清实际生效来源，避免把旧模板资料误差当线上故障 |

## 四、状态与安全约束

清单业务健康一律unknown或明确不适用，本次不是全站故障数或健康率统计。公开页面健康与私人运维明细分开设计；原始systemctl/launchd（launchd 已废弃/历史存档，生产定时任务已迁云上 systemd timer）/cron取证私有保存，仓内已脱敏，不含Environment、完整敏感argv、通知账户或凭证。

“完整”在本次指：在明确枚举边界内形成完整登记及未知清单。不是对尚未取证的账号控制面、其他用户任务或所有业务数据作全知声明。后续把新增证据更新到同id，并按09规则维护。
