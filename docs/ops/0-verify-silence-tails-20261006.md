# #200 / #199 / #202「静默家族小尾巴三件」§0 上线验证报告

- 验证人:tester agent(任务:合并上线后的 §0 上线验证,云上全程只读)
- 验证时点:2026-10-06 01:01 ~ 01:16 CST(云上 CST,与本机同时区)
- 验证对象:main @ `0cbb7105129716e48d92ada669b3e55ae0731945`(短 hash `0cbb71051`)
  - 复核(验证后 main 前进):本机 main 于验证后前进至 `3d7dd42db`(docs 收口,仅改 TASKS.md 4 行);`git show main:scripts/*` 四文件 md5 仍与 §2 四值逐位相同 → 本次验证结论不受影响
  - `git merge-base --is-ancestor` 四连实测:功能 commit `7a3d21dcb`(#200)/`822480c9f`(#199)/`b20e99598`(#202)与 merge `0cbb71051` **均在 origin/main 链** ✓
  - merge 本体改动文件(`git show --stat 0cbb71051`):`scripts/update_all.sh`(+22)/`scripts/backup_claude_self.sh`/`scripts/notify.py`/`scripts/schedule_monitor.sh` + docs 实施报告(无前端文件、无数据产物 schema 变更)
- 云上布局(实测):代码仓 `/home/ubuntu/code/trade-data-signal`;生产执行树 `/home/ubuntu/code/trade-data`,其 `scripts` 为 **symlink** → `trade-data-signal/scripts`(`readlink -f` 双路径同为 `/home/ubuntu/code/trade-data-signal/scripts`),systemd unit 的 `ExecStart=/home/ubuntu/code/trade-data/scripts/*.sh` 即等价引用 git 树
- **总判:§0 PASS(8 项核对全过)**;2 项「字面期望 vs 实测」偏差如实标注(见 §4、§6);生产实跑缺口与观察点见 §8
- §8 三查口径说明:①「main 链含 commit」由 §1(云上 HEAD + reflog)+ §2(md5 逐位)双证覆盖;②数据层生效/③前端展示层在本批**无对象**(本批改动为运维脚本行为 + 告警链路,无 JSON 字段/前端文件改动),已核生产 alert_state.json 内容无新告警(§7)
- 全程只读:云上未启停任何 unit、未跑 `update_all.sh`/`backup_claude_self.sh`/`deploy.sh` 本体、未 PUT/DELETE 任何 R2 对象、未改云上/本机任何文件;本机测试在 `/tmp` 快照树(git archive 导出)跑并全程装载出网哨兵,实测零真实外发(§6/§7)

## 1. 代码落云(HEAD/工作树)— PASS

云上实测:
```
0cbb7105129716e48d92ada669b3e55ae0731945
0cbb71051 merge(feat/feat/silence-family-tails-20261006): 统一入口合并 feat/silence-family-tails-20261006 入 main
---status---
---status-end---        (git status --porcelain 空 = 工作树干净)
```
同步时点(reflog 实测):`0cbb71051 HEAD@{2026-10-06 00:59:28 +0800}: pull origin main: Fast-forward`,`.git/FETCH_HEAD` mtime 同秒 → 生产于 00:59:28 拿到本版。

## 2. 4 文件逐位一致 — PASS(四对全一致)

云上(trade-data-signal;生产执行树经 symlink 同一份文件,两条路径均实测)vs 本机 `git show main:<path> | md5`(本机工作树 md5 亦同值):
```
17d5665341d7c92e119ae1b04dbf1500  scripts/update_all.sh
ef1e49660f08791edd2cb5d5efc9cb8e  scripts/backup_claude_self.sh
4d244e8e715411205ba15fffdd6564c2  scripts/notify.py
845ea487a6af7d41006f55f958b29faa  scripts/schedule_monitor.sh
```
生产执行树脚本 mtime = `2026-10-06 00:59:28`(与 pull 同秒)。

## 3. #200 锚点在位 — PASS(云上行号与实施报告一致)

云上 `scripts/update_all.sh` 实测:
- L313-315 SEVERE 聚合三条 rsync:`[ "${FUND_NAV_RSYNC_RC:-0}" -ne 0 ] && SEVERE=1` / `SCORE_LIST_RSYNC_RC` / `FUND_SCORE_RSYNC_RC`
- L345-347 ISSUE 文案聚合:`ISSUE="${ISSUE}nav_bucket镜像rsync失败(rc=...,镜像未同步) "`(+etf_score_list / fund_score 同形两条)
- L354 notify 调用:`notify.py "[告警] update_all ${ISSUE} ..." --severe --alert-issue "$ISSUE" --dedup-key "update_all_severe:${ISSUE}" --dedup-window 1800`
- 退出码:`grep -n "exit "` 全量仅两处实退出 —— L75 非交易日分支 `exit 0`、L394 `exit "$RC_CORE"`(唯一主链退出码,L362 为注释)
- 配套采集点:L118-121 nav_bucket / L201-203 etf_score_list / L240-242 fund_score 三处 rsync rc 捕获在位

## 4. #199 锚点 — PASS(带字面偏差标注)

任务书期望 `grep -n 'signal-backup' scripts/backup_claude_self.sh` → **空**;实测**非空,1 行命中**:
```
47:    # #199(2026-10-06): 不再写死桶名(曾写死 signal-backup, 切 signal-backup2 后 10-06 起与实际不符)。
```
判定:**该唯一命中是 #199 的说明性注释本身,非桶名常量残留**;代码路径(上传调用 `upload_r2.py upload-claude-backup "$OUT"` + 成功回显 `claude-backup/claude-self-$TS.tar.gz`)不含桶名字符串,桶名单一事实源在 `upload_r2.py`(`BACKUP2_BUCKET=signal-backup2`,`_route_bucket` 按桶路由)→ **目标语义达成(写死常量=0),字面期望(全空)未达成,如实标注**。
同类检查:云上 `grep -n signal-backup` 于 `update_all.sh`/`schedule_monitor.sh`/`notify.py` 三文件 = **零命中**(exit 1)。

## 5. #202 锚点 — PASS

云上 `scripts/notify.py` L2287-2294:
```
_ESCALATE_CHANNELS = {
    adr.PATROL_DRIFT_DEDUP_KEY: (
        adr.PATROL_DRIFT_ESCALATED_DEDUP_KEY, "cloud_unit_patrol_drift_state.json",
        "#191 云上 unit 巡检漂移持续未清", adr.PATROL_DRIFT_ESCALATE_DAYS),
    adr.FAILED_UNITS_DEDUP_KEY: (
        adr.FAILED_UNITS_ESCALATED_DEDUP_KEY, "failed_units_patrol_state.json",
        "云上 failed unit 持续未清", adr.FAILED_UNITS_ESCALATE_DAYS),
}
```
- 结构为 dict(2 个通道),每通道 value = **4 元组**(准确口径:4 元组指通道元组),`PATROL_DRIFT_ESCALATE_DAYS` 在其内(L2290,`grep` 该常量命中 L2286 注释 + L2290 引用;悬空已消)
云上 `scripts/schedule_monitor.sh` L1531:`_cfu_key = "check_failed_units|self|dead"`(首段 = `check_failed_units`,不再是 `cloud_unit_patrol`)。
同类检查:`cloud_unit_patrol` 其余命中(L172-183 WATCH_UNITS 表 / L633-647 包装器通道 / L1528 注释)**均为另一真实巡检对象(云上 unit 漂移巡检,其 unit `trade-cloud-unit-patrol.timer` 真实存在)**,非 `_cfu_key` 误用。

## 6. 本机回归自测 — PASS(39 + 13;路径偏差标注)

**路径偏差**:任务书给 `scripts/tests/test_132_notify_tier_dedup.py` **不存在**;实际文件在 `scripts/test_132_notify_tier_dedup.py`(scripts/ 根下,unittest 风格)。按实际路径跑。

在 `/tmp` 快照树(`git archive main` 导出,1755 文件)跑,不在主仓树:
```
cd /tmp/verify-0-silence-tails-20261006 && PYTHONPATH=/tmp/verify-0-sentinel REPO=<快照树> \
  .venv/bin/python -m pytest scripts/tests/test_196_patrol_visibility_20261005.py scripts/test_132_notify_tier_dedup.py -q
→ 52 passed in 0.44s   (196=39 passed / 132=13 passed,均 exit 0)
```
- 196 单跑:`39 passed in 0.41s`(exit 0,与任务书期望一致)
- 132 单跑:`13 passed in 0.04s`(exit 0)

**出网哨兵(§18 L48,先证生效再跑)**:哨兵 = `PYTHONPATH=/tmp/verify-0-sentinel/sitecustomize.py`,替换 `smtplib.SMTP/SMTP_SSL` + `urllib.request.urlopen`(notify.py 全部外发出口仅此两类:`grep` 实测无 requests/subprocess/os.system 出口)。
- 生效证明:带哨兵时两原语已是 `_blocked` 且调用抛 `VerifyHardBlock`;无哨兵反向对照显示为真实原函数(证明拦截非天然坏)
- **红样本(真实发送路径被拦)**:造快照树 `config/email.json` 指向 `127.0.0.1:1`(即使哨兵失效也不外发),实调 `notify._send_email` 与 `notify._send_feishu_webhook` → 均被拦(stderr:`邮件发送失败(不阻塞):VERIFY-SENTINEL: 禁止真实外发...` / `Feishu webhook 发送失败(不阻塞):...`;blocked.log 记 2 行)
- **测试轮次零外发尝试**:带日志哨兵重跑 52 项期间 `blocked.log` **不存在**(= 测试全过程未触达任何发送出口)
- 主仓无污染:本机 `git status --porcelain` 空;4 脚本 mtime 仍为 00:58:34(本会话未改)

**语法层兜底(云上只读)**:`bash -n` 对 `update_all.sh`/`backup_claude_self.sh`/`schedule_monitor.sh` 三连 OK;`notify.py` 经 `ast.parse` OK(不写 pyc)。

## 7. 零真外发证据 — PASS(生产目录两次采样 + 跨时点对照)

⚠️ 采样目录口径修正:生产数据目录 = `/home/ubuntu/code/trade-data/data`(unit `Environment=REPO=/home/ubuntu/code/trade-data`);`trade-data-signal/data` 是另一份独立副本(非 symlink,内容不同步,如 notify_dedup.json mtime 10-04 04:07 vs 生产 10-05 18:10)。**本节判定以生产目录为准**(首次采样误在 signal 目录,已改在生产目录重采;signal 副本亦两次采样无核心文件新增,如实标注)。

生产目录两次采样(2026-10-06 01:07 与 01:09:25)逐位同值,且与先例报告(193-196 报告 00:2x 采样)读数一致(跨约 45 分钟对照):
- `notify_dedup.json` mtime = **2026-10-05 18:10:50**(采样 A/B 同值,且与先例报告同值)→ 自 10-05 18:10 起无新告警去重写入
- `alerts/latest.md`(severe 镜像)mtime = **2026-10-05 18:30:10**(未变);`find data/alerts -newermt "2026-10-06 01:00"` = **空**
- `alert_state.json` mtime = 2026-10-06 01:00:12(**生产 monitor 01:00 轮次自身簿记重写**,非本次产生);内容实测:`total_keys=154`,`active_keys=1`(唯一 active = `nextday_plan|exit!=0|1`,first_seen=2026-09-30 22:45 存量),`patrol 族 keys = []`
- `*_state.json` 仅 `alert_state.json` + `brief_push_state.json`(后者 mtime 09-30 20:45 未变);**升档状态 `failed_units_patrol_state.json` / `cloud_unit_patrol_drift_state.json` 均不存在**(零写入)
- 01:00 后新写文件仅:news_digest 三件(生产新闻采集)+ `data/logs/*.log`(monitor/heartbeat 自身日志)→ 与本批改动无关
- `journalctl -u trade-schedule-monitor --since "25 min ago"`(01:03 跑):窗口内仅 00:45:09 与 01:00:01 两轮 Start→`Finished`(均成功),**无任何告警行**
- `systemctl --failed`:空(无失败单元)

## 8. 生产实跑实证缺口(诚实标注)+ 下一步观察点

本批改动 = 失败路径 loud 化 + 文案/常量订正,**只在各自定时触发时才生效**;今天 10-06 国庆休市(权威日历 `data/trade_dates.txt`:10-01~10-07 均不在表内,**节后首个交易日 = 10-08 周四**)。

**已获得的生产实跑实证(唯一一项)**:
- `schedule_monitor.sh`(#202 所在):00:59:28 同步新码 → **01:00:01 生产轮次实跑新版成功**(journalctl Start 01:00:01 → Finished 01:00:12;unit 日志):
```
[196] CHECK_FAILED_UNITS_OK failed=0 watchman=7 个 timer 全部在跑
[2026-10-06 01:00:01] OK 所有任务按计划执行，无漏跑，无退出失败
```
  覆盖度:启动路径 + 健康路径 ✓;**#202 改动点(`_cfu_key` 文案 / 升档常量)只在失败路径可见,failed=0 未触达**(不人为制造故障)。

**未取得生产实跑的 3 个脚本 → 观察点**:
| 脚本 | 触发源(实测) | 下次触发 | 今日闸门 | 真实观察点 |
|---|---|---|---|---|
| `update_all.sh`(#200) | 云上 `trade-update-all.timer`(Mon..Sat 17:50 / Sun 22:30) | 10-06 17:50 | **今日非交易日 → 走 L67-76 非交易日分支(deploy 补推 + `exit 0`),不进入三条 rsync(交易日路径)** | **10-08(周四)17:50** 交易日轮次:三条 rsync rc 捕获 + SEVERE/ISSUE 聚合链路 |
| `backup_claude_self.sh`(#199) | **本机 mac launchd `com.claude.self-backup` 每天 03:17**(云上 systemd 无此 unit,grep 空) | 10-07 03:17 | 无闸门 | 10-07 03:17 后看 `~/code/trade-data/data/logs/claude_self_backup.log` 的「R2 云端备份成功: claude-backup/claude-self-20261007.tar.gz」新回显(活性已证:runs=69 / last exit 0 / 最近产物 claude-self-20261005.tar.gz) |
| `notify.py`(#202 同 commit) | 无独立 unit(被各调用方触发) | 随调用方 | - | 随 monitor(每 15 分钟)/update_all(17:50)/r2-consistency(23:20)等链路;改动仅升档失败路径可见 |

**其余相关 unit 时点(list-timers 实测,10-06 01:03 快照)**:
```
trade-schedule-monitor.timer          每 15 分钟        下次 01:15   (无交易日闸门;内部 trading_day_only 任务非交易日跳过漏跑检查)
trade-check-monitor-heartbeat.timer   每 15 分钟        下次 01:11
trade-cloud-unit-patrol.timer         每天 08:27        下次 10-06 08:27
trade-update-all.timer                Mon..Sat 17:50 / Sun 22:30   下次 10-06 17:50
trade-r2-consistency.timer            每天 23:20        下次 10-06 23:20 (脚本注释明确「每日跑(不限交易日)」,无闸门)
trade-backup-db.timer                 每天 21:00        下次 10-06 21:00 (与本次 4 脚本无直接关系)
(本机) com.claude.self-backup         每天 03:17        下次 10-07 03:17
```
**备注(非本次判定项)**:云上存在两份 data 目录(`trade-data/data` 生产 + `trade-data-signal/data` 独立副本),其中 signal 副本的告警类文件较旧且不同步(如 notify_dedup.json 10-04 vs 生产 10-05);若属冗余建议另立任务清理,本报告不作为 FAIL。

## 复现段(每条核对的确切命令 + 期望输出)

```bash
# 0 本机快照树(git archive 导出,不污染主仓)
SNAP=/tmp/verify-0-silence-tails-20261006; rm -rf $SNAP; mkdir -p $SNAP
git -C /Users/linhuichen/code/trade archive main | tar -x -C $SNAP      # 期望 1755 文件

# 1 云上 HEAD/工作树(期望 0cbb7105129716e48d92ada669b3e55ae0731945 / merge(feat...) / porcelain 空)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal && git rev-parse HEAD && git log --oneline -1 && git status --porcelain'
# 1b 链含 commit(本机,期望四个均「在 origin/main 链」)
for c in 7a3d21dcb 822480c9f b20e99598 0cbb71051; do git merge-base --is-ancestor $c origin/main && echo "$c 在链"; done

# 2 四文件 md5(本机 vs 云上,期望四对相同:17d566../ef1e49../4d244e../845ea4..)
for f in scripts/update_all.sh scripts/backup_claude_self.sh scripts/notify.py scripts/schedule_monitor.sh; do git show main:$f | md5; done
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal && md5sum scripts/update_all.sh scripts/backup_claude_self.sh scripts/notify.py scripts/schedule_monitor.sh'
# 2b 生产执行树 symlink 等价(期望两路径同为 trade-data-signal/scripts)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'readlink -f /home/ubuntu/code/trade-data/scripts; md5sum /home/ubuntu/code/trade-data/scripts/notify.py'

# 3 #200 锚点(期望 L313-315 / L345-347 / L354 dedup-key update_all_severe / exit 全量仅 L75 L394)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep -n "RSYNC_RC\|update_all_severe\|exit " /home/ubuntu/code/trade-data-signal/scripts/update_all.sh'

# 4 #199(期望仅 L47 注释命中;其余三脚本零命中 exit 1)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep -n "signal-backup" /home/ubuntu/code/trade-data-signal/scripts/backup_claude_self.sh; grep -n "signal-backup" /home/ubuntu/code/trade-data-signal/scripts/update_all.sh /home/ubuntu/code/trade-data-signal/scripts/schedule_monitor.sh /home/ubuntu/code/trade-data-signal/scripts/notify.py'

# 5 #202(期望 _ESCALATE_CHANNELS 两通道 4 元组含 PATROL_DRIFT_ESCALATE_DAYS; _cfu_key 首段 check_failed_units)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'grep -n -A8 "_ESCALATE_CHANNELS" /home/ubuntu/code/trade-data-signal/scripts/notify.py; grep -n "_cfu_key =" /home/ubuntu/code/trade-data-signal/scripts/schedule_monitor.sh'

# 6 本机回归(哨兵先证生效;期望 52 passed / exit 0 / blocked.log 不存在)
mkdir -p /tmp/verify-0-sentinel && cat > /tmp/verify-0-sentinel/sitecustomize.py <<'EOF'
import smtplib as _smtplib, urllib.request as _ur
def _blocked(*a, **k): raise RuntimeError("VERIFY-SENTINEL: 禁止真实外发")
_smtplib.SMTP = _smtplib.SMTP_SSL = _blocked; _ur.urlopen = _blocked
EOF
cd $SNAP && PYTHONPATH=/tmp/verify-0-sentinel REPO=$SNAP /Users/linhuichen/code/trade/.venv/bin/python -m pytest \
  scripts/tests/test_196_patrol_visibility_20261005.py scripts/test_132_notify_tier_dedup.py -q   # 52 passed
# 6b 云上语法兜底(期望 3 连 OK + ast OK)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'cd /home/ubuntu/code/trade-data-signal && for f in scripts/update_all.sh scripts/backup_claude_self.sh scripts/schedule_monitor.sh; do bash -n $f && echo "OK $f"; done; python3 -c "import ast; ast.parse(open(\"scripts/notify.py\",encoding=\"utf-8\").read()); print(\"ast OK\")"'

# 7 生产零外发采样(期望:01:00 后仅 news_digest+logs;notify_dedup 10-05 18:10:50 / latest.md 10-05 18:30:10 不变;alerts 无新写)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'find /home/ubuntu/code/trade-data/data -type f -newermt "2026-10-06 01:00" | head -20; ls -l --time-style=full-iso /home/ubuntu/code/trade-data/data/notify_dedup.json /home/ubuntu/code/trade-data/data/alerts/latest.md /home/ubuntu/code/trade-data/data/*_state.json; find /home/ubuntu/code/trade-data/data/alerts -newermt "2026-10-06 01:00"'

# 8 timer 时点 + 观察点(期望见 §8 表)
ssh -i ~/tdsignal.pem ubuntu@122.51.111.173 'systemctl list-timers --all --no-pager | grep -i "update\|r2\|monitor\|backup\|patrol"; systemctl --failed --no-legend'
```

结论:本批 3 任务合并上线 **§0 PASS**;生产实跑缺口(update_all 交易日轮次 / backup_claude 明晨 03:17)已给逐项观察点,均属「失败路径类改动等触发」的正常性质,不构成上线阻断。
