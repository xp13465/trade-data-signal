# 状态集「完整可恢复集合」成套捕获·云上试跑记录(2026-11-14)

任务:备份工作包二(C 批)/ 分支 `feat/standby-capture-20261114`。
目的:证据用例 5——真实云上**试跑一次到临时目录**(只读源、不接 R2、不发通知、不动生产业务
数据),验证集合大小/耗时/manifest 完整性与报告一致。

## 试跑环境与方法

- 云上生产数据仓库 `/home/ubuntu/code/trade-data`(只读源:其 `data/` 全部 sidecar +
  `data/backups/` 同轮热备产物);写入仅限 `/tmp/standby-capture-trial/`。
- 脚本 = feat 分支 `scripts/backup_state_capture.py`(scp 到 `/tmp/backup_state_capture_trial.py`
  运行,不改云上任何生产文件);`--scripts-dir` 指生产 `scripts/`(复用 backup_source_proof 的
  行数/integrity 尺子);stamp=20261113_2100(三库同轮热备)。
- 不接 R2(未跑 upload-state-capture)、不发通知(脚本本身无通知链路)。

## 两轮试跑结果(改进前后对照)

| 轮次 | 集合原始大小 | 文件数 | 耗时 | missing | skipped | complete |
|---|---|---|---|---|---|---|
| 第 1 轮(payloads 全量进集合) | 1,221,803,217 B(1.21GB) | 1779 | 67.96s | 0 | 292 | false |
| 第 2 轮(payloads 声明排除后,**终版**) | 15,158,474 B(15.2MB) | 1257 | 13.53s | 0 | 292 | **true** |

第 1 轮暴露:`.r2-protected/payloads/` 内容寻址载荷 1737 个共 1.21GB(confirmed 载荷与 R2
当前对象同内容、nav_bucket 旧版可由 public_fund.db 再生),全量进每日集合违反任务「预算」条
⇒ 落为 `DECLARED_EXCLUDES` **声明排除**(捕获前声明、随清单同写 manifest,非发现缺文件后
缩表);第 2 轮为终版口径。

## 终版 manifest 实测要点

- `verification`=pass / `uploadable`=true / **`complete`=true**(missing=0;skipped 292 全为
  `transient_lock_by_design`——ops_delivery 出版目录 `.lock` 事务锁按设计排除,不算缺口)
- `sidecar_consistency`={checks: [read_pre_post_stat, finalize_stat_and_sha256], retries: 0,
  status: consistent}
- `db_leg`:sentiment/etf_national_team/stock_daily 均 ok+integrity ok(max_date 20261113/
  20261113/20261112);public_fund=reference_only(大库归档走既有 upload-db R2 链,不重复复制)
- `common_business_cutoff`=20261113, 证据=signal_kelly_etf_freeze.json(文件内业务日期优先,
  methods_seen 含 json_field/json_freeze_key_prefix/mtime_fallback,兜底项逐文件可见)
- `declared_excludes`=['.r2-protected/payloads'](带理由原文,见脚本 `DECLARED_EXCLUDES`)
- files_by_category:不可重建历史 6 / 采集进度 4 / 发布状态 1215 / 通知状态 28 / proof台账 4

## 口径说明(审查二轮 #6 补注,2026-11-14)

本节以上数字是 **pre-F5 历史证据**(当时分支代码的云上实测),按「历史记录不追改」原样保留;
当前代码口径示例:

- `common_business_cutoff` 现统一归一成 ISO `YYYY-MM-DD`:同一次试跑在
  `normalize_business_date` 之后会写 **`2026-11-13`**(上面表格里的 `20261113` 是 F5 归一前的
  历史值——8 位与 10 位混排直接字典序比较会让 8 位恒赢,`('-'(45) < 数字)`,F5 即修此)。
- 声明清单/排除项随审查二轮更新(新增 `audit/frozen_missing` 纳入捕获;`news_digest` /
  `d1_metrics_evidence` / `d1_sync_state` 显式声明排除),故下一次真实试跑的
  `files_by_category` / `declared_excludes` 计数与本表不再逐位相同;机制口径以
  `scripts/backup_state_capture.py` + `docs/backup-restore.md` §九为准。

## 预算结论

捕获 13.53s + tar.gz+上传预估秒级~分钟级(15MB 原始、gzip 后更小),远小于
trade-backup-db.service `TimeoutStartSec=12600` 看门狗预算;大文件 public_fund 复用既有
R2 备份产物未重复复制。

## 残留清理

试跑后已删 `/tmp/standby-capture-trial/`、`/tmp/backup_state_capture_trial.py`、
`/tmp/analyze*.py` 并核验 `/tmp` 无 standby/analyze/backup_state 残留(ssh 实测
`no_residual`);云上生产目录全程零写入。
