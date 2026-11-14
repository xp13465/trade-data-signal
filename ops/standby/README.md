# 备用机凌晨同步:安装与运维说明(工作包三/D 批,2026-11-14)

工具:`scripts/standby_sync.py`(子命令 `sync` / `verify` / `status` / `retention`,
全子命令支持 `--dry-run`)。执行方案出处:`/tmp/codex-reports/claude-cloud-primary-local-backup-20261114-execution-plan.md` 工作包三。

> **本任务只交模板+说明,不 load 任何 plist**(部署另派,任务书「不做的」明令)。
> 首个自然轮留证、真实 R2 凭据配置、恢复演练均属后续批次(E 批)。

## 一、目录布局(与开发树硬隔离)

默认根 `~/trade-standby`(全部可用 CLI 参数改写):

```
~/trade-standby/
├── work/      staging 下载区(只清本工具登记的 staging-* 目录)
├── data/      解压校验暂存(校验完即清)
├── archive/
│   ├── versions/<version_id>/   已验证的固化版本(带 .standby-managed 标记)
│   └── latest_verified -> versions/<version_id>   原子 symlink
├── state/     standby_sync_state.json + standby_sync.lock(flock 单实例)
└── logs/      每日日志 + launchd 输出
```

启动时自校验:目录不许指进开发树(`/Users/linhuichen/code/trade`、
`/Users/linhuichen/code/trade-data`,可用 `STANDBY_SYNC_DENY_PATHS` 追加,冒号分隔),
撞上直接拒绝执行。

## 二、安装步骤(部署批次执行)

1. **建独立工作根**(勿复用开发树):`git clone` 仓库到如 `~/trade-standby-repo`,
   checkout 已验证 HEAD;建 venv 装 `requirements.txt`。
2. **R2 凭据**:`<工作根>/.env` 写 `R2_BACKUP2_ENDPOINT / R2_BACKUP2_BUCKET /
   R2_BACKUP2_ACCESS_KEY_ID / R2_BACKUP2_SECRET_ACCESS_KEY`(与 upload_r2.py 同键名;
   该文件 `.gitignore`,禁 commit)。manifest key 当前缺省
   `standby/manifest_latest.json` 为**占位**——待 C 批(feat/standby-capture-20261114)
   契约定案后在 `--manifest-key` 对齐,首次真实同步前必须核。
3. **改模板占位符**:把两个 plist 里 `__STANDBY_PYTHON__`、`__STANDBY_REPO__`
   换成真实绝对路径。
4. **先手动演练**(D 批完成条件「先手动在隔离环境跑通」):
   ```bash
   # dry-run:只下载+校验,不固化不切链不写状态零外发
   ~/trade-standby-repo/.venv/bin/python ~/trade-standby-repo/scripts/standby_sync.py \
     --source r2 sync --dry-run
   # 真跑一次(固化+切 latest_verified),之后 status 看恢复点真实年龄
   ... sync ; ... status
   ```
5. **装载**(部署批次,本任务不做):
   ```bash
   mkdir -p ~/Library/LaunchAgents
   cp com.trade.standby-sync.plist com.trade.standby-sync-catchup.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.trade.standby-sync.plist
   launchctl load ~/Library/LaunchAgents/com.trade.standby-sync-catchup.plist
   ```
   卸载 = 反向 `launchctl unload` + `rm`(停用同步不影响云端主生产与已存版本)。

## 三、调度设计(为什么是 00:30)

- 云上备份链 21:00 起,public_fund 上传实测最晚 22:24 完成 ⇒ 之后才开始拉;
- 避开本机 03:17 claude 自备份与云上 05:0x staticdata 备份高峰(错开 ≥30min);
- 主 plist `StartCalendarInterval` 00:30 Asia/Shanghai;**launchd 对睡眠/关机漏跑的
  StartCalendarInterval 不补跑**,故配套 catchup plist(`RunAtLoad`+每小时
  `sync --only-if-missed`)做启动补偿:今日已成功恒静默,漏跑只补**一次**有效同步
  (`missed_runs` 入账,不重写时间戳)。两个 plist 撞车由脚本内 flock 兜底。

## 四、重试与通知语义

- 每窗口最多 3 次总尝试,指数退避(120s/240s),共享总截止 120 分钟
  (`--deadline-minutes`),不跨窗口重试;
- **静默**(只写状态,零外发):成功、无变化、窗口内重试后成功;
- **事件**(notify.py,四元组 critical/604800s/backup 域/首报必达):
  新集合损坏、超窗口失败、恢复点过期(>2 天,`--stale-days`)、空间不足;
  同一事件 7 天去重窗内不重复(不按尝试次数/日期刷屏);
- 保留策略:默认日保 7 天+周保 4 周,空间不足自动降级(报告说明),永远保
  `latest_verified`+至少 2 份已验证版本,只删本工具登记目录,不碰未登记目录。

## 五、日常核查

```bash
python scripts/standby_sync.py status                    # 恢复点真实年龄/版本清单
python scripts/standby_sync.py verify                    # 复验 latest_verified(只读)
python scripts/standby_sync.py retention --dry-run       # 保留计划预览
```

状态文件字段:`latest_downloadable / latest_verified / business_date /
source_run / manifest_sha256 / last_success_ts(_utc) / missed_runs_last /
latest_recovery_point_age_days / last_failure / history[]`(本地+UTC 双时区)。

## 六、空间预算(盘点实测)

完整集合 gzip ≈0.996GiB、解压 ≈3.61GiB;归档根建议 ≥64GiB 可用
(7 日+4 周 ≈10.95GiB + staging 1.0GiB + 单份解压 3.61GiB + 旧版共存峰值
≈16.6~19.2GiB,64GiB 含月备扩展余量)。空间不足时本工具**拒绝下载并报事件**,
不删唯一可用版本换空间。备用机磁盘身份/清理由用户拍板(见盘点报告第六节)。

## 七、退出码速查

0 成功/无变化/补偿未到期;1 超窗口失败;3 已有实例在跑;4 空间不足;5 新集合损坏。
