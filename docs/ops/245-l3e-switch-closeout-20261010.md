# #245 L3e 切换后收尾 —— 云上核对与终态报告

- 日期:2026-10-10 14:05(+0800)
- 执行:测试 agent(role-tester)
- 依据:实施报告 `docs/ops/245-l3e-dual-tree-20261010.md` §3/§7;审查报告 `docs/ops/245-l3e-dual-tree-review-20261010.md` 点 9(收尾必要,低危瞬态)
- 性质:生产数据收尾(只读核对;未触发任何告警/邮件/飞书,零写盘)

## 结论

**收尾完成,无需 apply,零写操作。** 窗口期(10-10 13:25 apply → 13:52 云上 `e18174caa` 生效)内**无任何新键**写入代码树;dry-run `added=0 updated=0`(幂等);两树终态 = **运行树完整保守覆盖代码树**:代码树 52 键全部在运行树中,且无一键的 `last_alerted` 比运行树新。

## 1. 云上版本核(PASS)

命令:`ssh … git -C /home/ubuntu/code/trade-data-signal log -1 --format=%H`(timeout 60 包裹)

- HEAD = `e18174caae82bbfabdfe8cab98e8d1cc95f05175`(2026-10-10 13:52:06 +0800)——前 9 位 `e18174caa` 与任务要求一致
- `notify.py` 单树化行在位:`/home/ubuntu/code/trade-data-signal/scripts/notify.py:97` →
  `REPO = Path(os.environ.get("REPO") or Path(__file__).absolute().parent.parent)`
  (env 覆盖先例推广处同在:L113/L127/L172/L2415/L2455/L2505)
- 合并脚本在位:`/home/ubuntu/code/trade-data-signal/scripts/merge_notify_dedup_trees.py`(6766B,mtime 13:52)
- 注:notify.py 实际路径为代码树 `scripts/notify.py`(非顶层;运行树 `scripts/` 是指回代码树的 symlink)

## 2. 收尾 dry-run(PASS,只读)

命令(按任务给定形式,cwd=运行树):
```
cd /home/ubuntu/code/trade-data && timeout 120 python3 scripts/merge_notify_dedup_trees.py
```
输出(原文):
```
[merge-dedup] run_tree=/home/ubuntu/code/trade-data
[merge-dedup] code_tree=/home/ubuntu/code/trade-data-signal
[merge-dedup] run_keys=64 code_keys=52 merged_keys=64 added=0 updated=0 skipped=0
[merge-dedup] 无变化(幂等: 两树 max 已一致), 不写盘
dryrun_exit=0
```

与 13:25 那次数对比:

| 项 | 13:25(apply 前 dry-run) | 本次 14:05(dry-run) | 说明 |
|---|---|---|---|
| run_keys | 51 | 64 | 已含 13:25 合并并入的 13 键 |
| code_keys | 52 | 52 | 代码树未被写过 |
| added | 13 | 0 | 窗口期零新键 |
| updated | 0 | 0 | — |

## 3. 决策(added==0 分支 ⇒ 不写任何东西)

按任务第 3 步:窗口期无新键 ⇒ 收尾完成,**未执行 `--apply`**(不制造无谓写)。

- 老备份在位(供记录;本次未新增备份):`/home/ubuntu/code/trade-data/data/notify_dedup.json.bak-20261010-132530`(4958B)
- 窗口期无写入的文件系统级证据(直接证据):
  - 代码树 `trade-data-signal/data/notify_dedup.json` mtime = **Oct 9 22:30**(早于 13:25 那次 apply)⇒ 13:25 至今该文件从未被写(任何写入都会更新 mtime;merge 脚本对代码树为只读)
  - 运行树 `trade-data/data/notify_dedup.json` mtime = Oct 10 13:25(13:25 apply 那次)⇒ 13:25 后至今 dedup 体系无新活动

## 4. 两树终态核(PASS)

只读逐 key 比对(本地脚本经 `ssh … 'timeout 60 python3 -' < /tmp/l3e_cmp.py` 送入,零写):
```
[cmp] run_keys=64 code_keys=52
[cmp] code_only_keys=0 []
[cmp] run_only_keys=12 ['cloud_unit_patrol_drift', 'deploy_check_data_integrity_fail',
      'deploy_purge_low_freq_fail', 'failed_units_patrol', 'failed_units_patrol_escalated',
      'fund_nav_async_upload_fail', 'host_resource_warn_主机磁盘__home_ubuntu_code_trade-data',
      'r2_consistency_fail', 'r2_upload_async_skip:/tmp/trade_r2_upload_async.lock',
      'r2_upload_trigger_fail', 'schedule_monitor_heartbeat', 'staticdata_backup_fail']
[cmp] code_behind(run<code)=0 (0=达标) []
[cmp] last_alerted: equal=44 run_ahead=8
```
判定:
- `code_only = 0`:代码树不存在运行树没有的键 ⇒ 无「遗漏的抑制记录」
- `code_behind = 0`:不存在「代码树比运行树更新」的键 ⇒ 不存在会导致重复告警的缺口
- `run_only = 12`:运行树独有 12 键(13:25 合并前运行树本有,51 − 39 重叠 = 12,自洽)
- 守恒:`equal 44 + run_ahead 8 = 52 = code_keys` ✓

⇒ 运行树为唯一权威;代码树残留已被完全保守(取较晚时刻)覆盖。

## 5. 备查

- 恢复路径(如需回滚 13:25 合并):`cp /home/ubuntu/code/trade-data/data/notify_dedup.json.bak-20261010-132530 /home/ubuntu/code/trade-data/data/notify_dedup.json`
- 本次只执行:只读 grep/ls/git log + 一次 `--apply` 缺省的 dry-run + 一次只读 python 比对;云上数据文件零改动;未产生任何外发。
