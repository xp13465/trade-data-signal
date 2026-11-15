# 备用机凌晨同步:安装与运维说明(工作包三/D 批,2026-11-14)

工具:`scripts/standby_sync.py`(子命令 `sync` / `verify` / `status` / `retention`,
全子命令支持 `--dry-run`)。执行方案出处:`/tmp/codex-reports/claude-cloud-primary-local-backup-20261114-execution-plan.md` 工作包三。

> **2026-11-15 已在本机实际安装**(用户拍板每日 **01:00**):两份 plist 的路径已写死为
> 本机实际值并 `launchctl bootstrap` 装入 `~/Library/LaunchAgents/`,首次真实同步已于
> 2026-11-15 手动 kickstart 验证(no-change 静默)。**首个 01:00 自然轮已于 2026-11-16 01:00:05
> 实际触发**,结果 `outcome=no-change`(无新数据可同步,链路正常)。
> 换机器/换路径时改两份模板前两行与 `--repo-dir`,再按第二节重装。

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

1. **工作根**:本机现装 = **直接使用本机开发仓** `/Users/linhuichen/code/trade`(**不要另
   clone 到 `~/trade-standby-repo`——该目录不存在,照旧命令做会失败**)。只有**换机器/换到
   另一台机器正式接管**时才 `git clone` 到独立目录(如 `~/trade-standby`),checkout 已验证
   HEAD,建 venv 装 `requirements.txt`,并把两份模板里的 python/repo 路径改成新机实值。
   - **⚠ 交易日历要单独同步(2026-11-15 补)**:判龄读的是**备用机工作根自己**的
     `data/trade_dates.txt`,clone 后**不会自动更新**(生产每日刷新只写云上 trade-data 树)。
     启用前把主仓最新文件拷过来,之后**定期更新**(建议随每次同步批次或至少每月一次;
     **跨年前必须更新**)。缺失/陈旧/不可读时判龄诚实降级为自然日,告警文案标注
     「天(日历不可用回退自然日)」= 偏响(可能误报)而非静默漏报;看到该标注先补日历。
2. **R2 凭据**:`<工作根>/.env` 写 `R2_BACKUP2_ENDPOINT / R2_BACKUP2_BUCKET /
   R2_BACKUP2_ACCESS_KEY_ID / R2_BACKUP2_SECRET_ACCESS_KEY`(与 upload_r2.py 同键名;
   该文件 `.gitignore`,禁 commit)。manifest key 缺省
   `standby/manifest_latest.json`:云上既有备份链在 `STANDBY_MANIFEST_ENABLED=1` 时由
   `backup_db.sh → upload_r2.py standby-manifest` 生成(G3/G4, 契约见
   `scripts/standby_manifest.py`);**未开启开关前 R2 上无此对象**,首次真实同步前必须确认
   云上开关已开且该 key 存在(用 `standby_sync.py verify` 或 `list standby/` 核)。
   - **⚠ 双开关依赖(启用前必读,2026-11-15)**:清单生产者硬依赖状态集捕获产物目录,云上必须
     **同时**开 `STATE_CAPTURE_ENABLED=1`（产出 `CAPTURE_SET_DIR`/state receipt）和
     `STANDBY_MANIFEST_ENABLED=1`（生成发布清单）。**只开清单开关** ⇒ `backup_db.sh`
     每晚打印「⚠ 备用机同步清单跳过(缺捕获集合或本轮 receipt)」静默跳过（只进备份日志、
     不发通知、不改退出码）⇒ R2 永远没有 `standby/manifest_latest.json`,备用机 `sync`
     一直 404;**只开捕获开关** ⇒ 状态集归档有了但清单仍不生成。启用前置:确认判龄口径为交易日
     （本分支默认 `--stale-mode trading`;旧版会每周一误报 severe）。
3. **路径**:两份模板已把本机真实绝对路径写死
   (python=`/Users/linhuichen/code/trade/.venv/bin/python3`,repo=`/Users/linhuichen/code/trade`)。
   换机器才需要改(改完 `plutil -lint` 验证)。
4. **先手动演练**(D 批完成条件「先手动在隔离环境跑通」):
   ```bash
   # dry-run:只下载+校验,不固化不切链不写状态零外发(本机路径;换机改成新机工作根)
   /Users/linhuichen/code/trade/.venv/bin/python /Users/linhuichen/code/trade/scripts/standby_sync.py \
     --source r2 sync --dry-run
   # 真跑一次(固化+切 latest_verified),之后 status 看恢复点真实年龄
   ... sync ; ... status
   ```
5. **装载/卸载**(本机 2026-11-15 已执行;换机器照此):
   ```bash
   # 装(先备份同名 plist,若有)
   mkdir -p ~/Library/LaunchAgents
   for f in com.trade.standby-sync com.trade.standby-sync-catchup; do
     [ -f ~/Library/LaunchAgents/$f.plist ] && cp ~/Library/LaunchAgents/$f.plist /tmp/$f.plist.bak-$(date +%Y%m%d%H%M%S)
     cp ops/standby/$f.plist ~/Library/LaunchAgents/$f.plist
     launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/$f.plist
   done
   # 卸载(可逆: 停调度, 不动已存版本, 不影响云端生产)
   launchctl bootout gui/$(id -u)/com.trade.standby-sync-catchup
   launchctl bootout gui/$(id -u)/com.trade.standby-sync
   ```
   卸载后如需彻底清除:`rm ~/Library/LaunchAgents/com.trade.standby-sync{,-catchup}.plist`
   (需要时从 `/tmp/*.plist.bak-*` 或本仓库模板恢复)。

## 三、调度设计(为什么是 01:00)

> **01:00 已装并已实测生效(2026-11-16)**:仓库模板与 `~/Library/LaunchAgents/` 安装副本
> 一致;`launchctl print gui/$UID/com.trade.standby-sync` 输出 `"Hour" => 1` / `"Minute" => 0`。
> 首个 01:00 自然轮已于 2026-11-16 `01:00:05` 实际触发(`last_success_ts = 2026-11-16 01:00:05`,
> `outcome=no-change`,日志同日 `01:00:05` 有真实同步记录)。
> 接管全流程见 `docs/ops/standby-takeover-runbook.md`。

- 用户 2026-11-15 拍板:每日 **01:00(Asia/Shanghai)**,替代早期模板示例 00:30;
- 云上备份链 21:00 起,public_fund 上传实测最晚 22:24 完成 ⇒ 之后才开始拉;留到凌晨 1 点还有余量;
- 避开本机 03:17 claude 自备份与云上 05:0x staticdata 备份高峰(错开 ≥30min);
- 主 plist `StartCalendarInterval` 01:00 Asia/Shanghai;**launchd 对睡眠/关机漏跑的
  StartCalendarInterval 不补跑**,故配套 catchup plist(`RunAtLoad`+每小时
  `sync --only-if-missed`)做启动补偿:今日已成功恒静默,漏跑只补**一次**有效同步
  (`missed_runs` 入账,不重写时间戳)。两个 plist 撞车由脚本内 flock 兜底。
- **合盖 = 睡眠**:合上笔记本盖子期间 01:00 不会触发,靠开盖/唤醒时 catchup 的
  `RunAtLoad` 立即补跑,之后每小时再检查一次;因此合盖过夜不需额外操作,开盖后会自愈。
- 两份 plist 都显式写死保护参数:`--min-free-gb 5`(空间不足自动不动手 + 告警)、
  `--stale-days 2 --stale-mode trading`(恢复点过期按交易日判)、
  `ThrottleInterval`(每日 300s / 补偿 60s)。

## 四、重试与通知语义

- 每窗口最多 3 次总尝试,指数退避(120s/240s),共享总截止 120 分钟
  (`--deadline-minutes`),不跨窗口重试;
- **静默**(只写状态,零外发):成功、无变化、窗口内重试后成功;
- **事件**(notify.py,四元组 critical/604800s/backup 域/首报必达):
  新集合损坏、超窗口失败、恢复点过期(>2 个交易日,`--stale-days`;
  默认 `--stale-mode trading`,自然日口径需显式 `--stale-mode natural`)、空间不足;
  同一事件 7 天去重窗内不重复(不按尝试次数/日期刷屏);
- **日历不可用降级**:备用机仓库日历缺失/陈旧/不可读时,恢复点判龄回退自然日并标注
  「天(日历不可用回退自然日)」——偏响(可能误报)而非静默漏报;先按安装步骤补
  `data/trade_dates.txt`,不要把该标注当真实交易日滞后;
- **故障恢复通知**:上述故障事件**真发出过**的,真正恢复后对每个事件发一次
  恢复通知(`<事件键>_recovered`,同 7 天去重窗),发出成功即清账;从未通知过
  的故障不发恢复(不会出现「没收到告警却收到恢复」);`pending_recovery` 记在状态文件;
- **dry-run 严格零副作用**:成功/失败任何分支都不写状态、不注册去重、不外发
  (也不会吞掉当日真实告警),只在屏幕/日志打印演练结论;
- 保留策略:默认日保 7 天+周保 4 周,空间不足自动降级(报告说明),永远保
  `latest_verified`+至少 2 份已验证版本,只删本工具登记目录,不碰未登记目录。

## 五、日常核查

> 停机演练 / 真正接管 / 回切 / 回滚的完整操作步骤,见 `docs/ops/standby-takeover-runbook.md`
> (其中每条命令都标了实测方式与实测结果)。本章只讲"平时怎么看一眼"。

```bash
python scripts/standby_sync.py status                    # 恢复点真实年龄/版本清单
python scripts/standby_sync.py verify                    # 复验 latest_verified(只读)
python scripts/standby_sync.py retention --dry-run       # 保留计划预览
```

状态文件字段:`latest_downloadable / latest_verified / business_date /
source_run / manifest_sha256 / last_success_ts(_utc) / missed_runs_last /
latest_recovery_point_age_days / last_failure / pending_recovery[] / history[]`
(本地+UTC 双时区)。

## 六、空间预算(盘点实测)

完整集合 gzip ≈0.996GiB、解压 ≈3.61GiB;归档根建议 ≥64GiB 可用
(7 日+4 周 ≈10.95GiB + staging 1.0GiB + 单份解压 3.61GiB + 旧版共存峰值
≈16.6~19.2GiB,64GiB 含月备扩展余量)。下载前空间检查按「staging gz 合计 +
最大对象**解压后**大小 × 1.1 + `--min-free-gb` 保底」算峰值;解压后大小取
manifest 的 `size_uncompressed`,缺省按实测解压比 3.6 估算——不会用压缩大小
低估需求而击穿 `--min-free-gb`。下载/解压/写盘中途磁盘满同样归
`space_insufficient`(不会误报成 `window_fail`)。空间不足时本工具**拒绝下载
并报事件**,不删唯一可用版本换空间。备用机磁盘身份/清理由用户拍板(见盘点报告第六节)。

**launchd 日志会长期增长**:`~/trade-standby/logs/` 下 stdout/stderr 按日累积、无自动轮转,
建议每月看一眼 `du -sh ~/trade-standby/logs/`,按需清理旧日志(只删日志,不动
`archive/` 与 `state/`)。

## 七、退出码速查

0 成功/无变化/补偿未到期;1 超窗口失败;3 已有实例在跑;4 空间不足;5 新集合损坏。
