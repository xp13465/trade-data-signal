> 落档:2026-10-22(源报告由本批执行 agent 产出,原样归档)
> 相关合并:见 `docs/ops/batch-fix-20261022.md` 时间线

# 部署复核报告(2026-10-21 夜间,生产云上)

> 残留后台任务:本地 harness 任务 **bs84hrwe7**(命令=ssh 到云上触发 deploy 的会话,含 `nohup setsid bash scripts/deploy.sh all`);远端 deploy 已于 00:00:27 结束,该本地会话预期随远端通道关闭而退出;若仍显示 running 请 TaskStop。

## 结论
**阻断条件已消除,部署恢复成功**(exit=0)。唯一未闭环项 = 本次新 export 的 R2 异步上传被上一实例占锁跳过,已写 pending 标记由在跑实例收尾补跑(收尾时仍在跑);另有一次链自动 notice 外发(偏离"零外发",见 §5)。

## 1. 时点与触发方式
- 云上触发 **2026-10-21 23:49:57** → 结束 **2026-10-22 00:00:27**(约 10.5 分钟),exit=0。
- 前置:`systemctl list-timers` 最近槽 23:30/23:37/23:41/23:45 已过;避开 09:30-15:30 盘中;下一业务任务 02:00(backfill-evening),00:00 仅系统 logrotate/dpkg。
- 命令(与 `update_all.sh:152` 17:50 链路同一条,不发明新命令):
  `cd /home/ubuntu/code/trade-data && REPO=/home/ubuntu/code/trade-data GIT_REPO=/home/ubuntu/code/trade-data-signal MAIN_REPO=/home/ubuntu/code/trade-data nohup setsid bash scripts/deploy.sh all`
- 部署日志:`/home/ubuntu/code/trade-data/data/logs/deploy_20261021_2349.log`(段1)+ `deploy_20261022_0000.log`(段2);启动输出 `/tmp/deploy-recheck-run-20261021_2350.log`。

## 2. 阻断项前后对照(核心)
停摆期原文(多轮同因):`deploy_20261021_2155.log:581`
  `✗ nextday_plan: date=20261019 不是最近交易日/当前交易日/下一交易日 (允许=['20261020', '20261021', '20261022'])`
本次通过:
  - `deploy_20261021_2349.log:582` `✓ nextday_plan: 计划条目=1 date=20261021`
  - `deploy_20261021_2349.log:577` `✓ a_fund_north_quarterly: 最新季度行存在 date=20260930 value=-589.18 亿 (db=.../sentiment.db)`
只读前置核对(云上):
  - R2 `nextday_plan.json`(ss.fx8.store / ssd.fx8.store 均 200):date=20261021, plan 1 条(buy 560010)。
  - `sentiment.db` daily_metric 最新季度行 20260930,与 check 期望值一致。

## 3. 部署各段结果
- check_data_integrity:`=== 汇总: 44 ok / 0 warn / 0 fail ===`(log:597);`✓ 数据产物校验通过`。
- check_task_state:`2 ok / 1 warn / 0 fail`(warn=无 .claude/scheduled_tasks.json,跳过;非阻断)。
- build_min ✓;rsync 静态 JSON + 采集数据 ✓;check_version_progress A/B PASS(HEAD 808ec8a331)。
- 段2:`✓ 无新数据变更,跳过 commit` / `Everything up-to-date`(未产生新 commit、未推代码);`=== deploy.sh 结束 2026-10-22 00:00:27 退出码=0 ===`。

## 4. 线上 curl(浏览器 UA,禁 -v/-i)
- `https://ss.fx8.store/data/overview.json` HTTP 200,2,830,459B;date=20261021,signals_today=642,collected_at=20261021 21:37:55。
- `https://ss.fx8.store/r2/fund_score/fund_score.json` HTTP 200,2,244,911B;date=20261021,count=2000,md5=d72ede5fb91c… 与本机导出**逐位一致**;`fund_score_top.json` 200,date=20261021,count=100。
- 注:`https://ss.fx8.store/data/fund_score.json` 为旧路径(date=20260828),前端读 `/r2/fund_score/`,该旧路径非本次问题。
- 差异说明:live overview 仍是 22:00 生成版(本次 export 生成于 23:55),差异仅为重算噪声(stable_top1 排序、track_score ±0.1、generated_at),数据日期同为 20261021。

## 5. R2 异步上传与一次外发(如实上报)
- 本次 deploy 派生 `r2-upload-000021`(00:00:21 启动);因 23:22 的 `r2-upload-232250` 仍持 `/tmp/trade_r2_upload_async.lock`,600s 超时后于 **00:10:21** 跳过,已写 `/tmp/trade_r2_upload_async.pending`,由 232250 收尾增量补跑(00:34:50 时 232250 仍 active,pending 仍在)。
- ⚠ **偏离"零外发"**:跳过处理器 `r2_upload_skip_notify.sh` 于 00:10:25 自动发出 notice 级邮件+飞书《R2上传异步锁跳过 10-22 00:10》;台账 `data/alerts/alert_ledger.jsonl` 00:10:25 行 channels={email:true, feishu:true}。非我手动发送,属部署链既定降级告警。

## 6. 其他观察(非本次引入,未处置)
- `systemctl --failed` 残留 6 个 failed unit:etf-national-team / lhb-backfill / public-fund-daily / public-fund-quarterly / r2-consistency / fwupd-refresh。
- `data/alerts/latest.md` 显示 23:24:15 severe「§22 三站一致性校验失败(连续 2 天,升级 critical)」。

## 7. 纪律声明
- 未改任何文件、未动 systemd unit/定时任务、未做 git 写操作;未修任何失败项(仅记录)。
- 只触发一次 deploy,无重试。
