# staticdata 备份异步化 b13c7853d 动态测试(临时 /tmp 环境,2026-09-25)

- 被测 commit: `b13c7853d`(scripts/staticdata_backup_async.sh + scripts/schedule_monitor.sh C-3)
- 测试环境: 全部在 /tmp 临时 git 仓库(/tmp/sdtA /tmp/sdtB + 裸仓库 /tmp/sdtB-bare.git),**未触碰生产**,未 push main
- 测试方式: 逐条动态实测(非静态读码),命令一次一条、字面量路径
- 测试 agent 验证方法: 尺子先验(坏样本确认能抓)+ 四步门(指认命令→真跑→读全输出→对账)

## 必要测试环境修正(默认值在 /tmp 不成立,不改则测不到被测逻辑)
1. `PY=/usr/bin/python3`:脚本默认 `PY=$REPO/.venv/bin/python`(/tmp 不存在)。已实测 bash `exec` 失败会**整脚本退出**(exit 126,不再往下跑),不指定有效 PY 则脚本死在 with_lock 重入处,测不到 git add 判定。
2. 测试③额外:给 /tmp/sdtB 持久配置 `git config user.email/user.name`(脚本自身 commit 不带 `-c`,无配置会失败)+ 建裸仓库作 origin(脚本 push origin main,无 origin 会失败 → 心跳 fail,测不出 ok 路径)。

---

## 测试⓪:PIPESTATUS 机制证明 → **PASS**
被测脚本核心修复依赖「无 pipefail 下取 `PIPESTATUS[0]` 拿到管道首命令真实退出码」这个前提。先证前提。

命令:
```
printf 'false | tee /tmp/sdt-tee.txt; echo "PIPESTATUS0=${PIPESTATUS[0]}"\n' > /tmp/sdt-mech.sh
bash /tmp/sdt-mech.sh
```
实际输出:
```
PIPESTATUS0=1
```
对账:管道首命令 `false` 退出码 1 被正确取出。前提成立。

---

## 测试①:C-2「git add 失败不再被吞」→ **PASS**
注入 `GIT_INDEX_FILE=/nonexistent-dir/gitindex` 让 git 无法写索引(模拟 add 失败),验证脚本不再误走「无新变更」分支、且心跳记 fail。

命令:
```
STATICDATA_REPO=/tmp/sdtA REPO=/tmp/sdtAruns GIT_INDEX_FILE=/nonexistent-dir/gitindex STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 PY=/usr/bin/python3 bash /tmp/sdt-async.sh test > /tmp/sdt-out1.log 2>&1 </dev/null
```
日志关键行(原始输出):
```
fatal: Unable to create '/nonexistent-dir/gitindex.lock': No such file or directory
⚠ git add 失败(staticdata 仓库 /tmp/sdtA), 置 STATICDATA_FAIL=1, 跳过 commit(git 历史缺口, 需人工排查)
✗ staticdata 备份完成但部分失败(已告警)
```
心跳(原始输出):
```
{"ts":"2026-09-25 16:57:29","result":"fail","files":0,"bytes":0,"duration_s":0}
```
辅助确认:
- `grep -c "无新变更" /tmp/sdt-out1.log` → `0`(误判分支未进入)
- `git -C /tmp/sdtA log --oneline` → 仍只有 `f458ae2 init`(add 确实失败,无 commit 产生)

逐条对账:
- [PASS] 日志出现「⚠ git add 失败」
- [PASS] 日志**不**出现「✓ staticdata 无新变更,跳过 commit」
- [PASS] 心跳 `result=fail`
- 说明: 日志中 `notify.py: can't open file '/tmp/sdtAruns/scripts/notify.py'` 是测试环境无该脚本所致(`|| true` 兜底吞掉,不影响判定),生产环境 PY/scripts/notify.py 在。

---

## 测试③:端到端正常路径 → **PASS**
新变更(git add 成功 → commit → push)时心跳 ok、出现新 commit。

准备(命令从略,均为逐条字面量):
- /tmp/sdtB: init + `a.txt` commit init(分支名为 `main`)
- 持久 user 配置 + `git init --bare /tmp/sdtB-bare.git` + `remote add origin /tmp/sdtB-bare.git`
- 写入 `b.txt` 作为新变更

运行命令:
```
STATICDATA_REPO=/tmp/sdtB REPO=/tmp/sdtBruns STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 PY=/usr/bin/python3 bash /tmp/sdt-async.sh test > /tmp/sdt-out3.log 2>&1 </dev/null
```
日志关键行(原始输出):
```
  [变更量] 文件数=41 字节=85407 超阈值=0
[main 7229135] data backup [test] 2026-09-25_16:58 - 41 files
  [step4 git add+commit+push] 5s
✓ staticdata 备份完成 2026-09-25 16:58:47
```
心跳(原始输出):
```
{"ts":"2026-09-25 16:58:47","result":"ok","files":41,"bytes":85407,"duration_s":5}
```
提交记录:
```
git -C /tmp/sdtB log --oneline
7229135 data backup [test] 2026-09-25_16:58 - 41 files
797b6f0 init

git -C /tmp/sdtB-bare.git log --oneline
7229135 data backup [test] 2026-09-25_16:58 - 41 files
797b6f0 init
```
逐条对账:
- [PASS] 心跳是合法 JSON 且 `result=ok`
- [PASS] /tmp/sdtB 出现新 commit `7229135`
- [PASS] push 已到达裸仓库(push 非跳过)
- 说明: commit 含 41 文件是 step2 配置备份把 ~/Library/LaunchAgents/com.trade.*.plist(40 个)同步进 config/launchd 所致,属脚本既有设计行为,非本次 C-2 改动相关。

---

## 测试②:C-3 心跳新鲜度检查 → **PASS**(标注:等价复刻,非原脚本全量跑)
- 判定块 **逐字切出** 原脚本 L1058-1099(`STATICDATA_HB_FILE = ...` 至 `else:` 分支),非手写重打,保证口径一致;外加最小运行壳提供 `NOW/REPO/alert_state/alerts/seen_keys_this_run`(原脚本内由 launchd 上下文/告警态持久化提供)。
- 判定逻辑原文要点: 只看 `result in ("ok","skip_oversize")` 且 `NOW - ts > 36h` 才发 SEVERE;文件不存在不告警;`fail` 不重复告警(已有脚本内 --severe)。
- 运行壳: `/tmp/sdt-c3-run.py <REPO>`(无状态,4 场景)+ `/tmp/sdt-c3-run2.py <REPO>`(持久化状态,测抑制)

### 场景 (a) 文件不存在 → 不告警 **PASS**
命令: `rm /tmp/sdtAruns/data/staticdata_backup_heartbeat.json` + `python3 /tmp/sdt-c3-run.py /tmp/sdtAruns`
输出:
```
[info] staticdata 备份心跳文件不存在, 跳过停摆检查(仓库缺失/首跑前, C-5 降级 notify 覆盖)
NO_ALERT
```

### 场景 (b) ts=2026-09-23 16:00:00、result=ok → **应报 SEVERE** **PASS**
命令: 写入过期心跳 + `python3 /tmp/sdt-c3-run.py /tmp/sdtAruns`
输出:
```
ALERT: SEVERE: staticdata_backup staticdata 异步备份停摆 最近完成<ok> 距今49h (>36h 阈值) 备份时间<2026-09-23 16:00:00>
```
对账: 距今 49h > 36h 阈值,触发。坏样本能抓(尺子先验: 该判定块在坏样本上报 FAIL/告警,判定逻辑确实活着)。

### 场景 (c) ts=2026-09-25 16:00:00、result=ok → 不告警 **PASS**
命令: 写入新鲜 ok 心跳 + `python3 /tmp/sdt-c3-run.py /tmp/sdtAruns`
输出:
```
NO_ALERT
```

### 场景 (d) ts=2026-09-25 16:00:00、result=fail → 不告警 **PASS**
命令: 写入新鲜 fail 心跳 + `python3 /tmp/sdt-c3-run.py /tmp/sdtAruns`
输出:
```
NO_ALERT
```
对账: fail 已有脚本内 --severe notify,C-3 不重复告警(注释明示),符合预期。

### 补充:已 active 抑制不重发 **PASS**(任务外低成本边界,防重复轰炸)
命令: 过期 ok 心跳 + `python3 /tmp/sdt-c3-run2.py /tmp/sdtAruns` 连跑两轮(状态持久化)
第 1 轮输出:
```
ALERT: SEVERE: ... 距今49h (>36h 阈值) ...
```
第 2 轮输出:
```
[suppress] staticdata_backup 异步备份停摆持续中, last_alerted=2026-09-25 17:01:15, 不重发
NO_ALERT
```

---

## 未验证项与范围说明
- 测试②为**等价复刻**(原脚本全量跑需 launchd 上下文 + alert_state 持久化 + 恢复检测循环,无法在单命令环境抽 L1049-1099 单独执行);判定块代码逐字取自原脚本,非手写。
- 恢复检测路径(active 状态心跳恢复 fresh 后自动发恢复邮件,原脚本 L1101+)不在本任务 4 场景范围,未测。
- `skip_oversize` 分支新鲜度逻辑与 ok 同路径(代码共用 `in ("ok","skip_oversize")`),本次仅实测 ok 场景,(b) 已覆盖过期告警判定。
- 积压超阈值(>5000 文件 / >300MB 跳过 commit)与 push 900s 超时看护未做动态实测(需构造 5000+ 文件或网络级阻塞,超出本任务最小充分范围)。
- 生产部署联动(systemd transient 触发/锁排队)未测(仅本机无 systemd 场景)。

## 结论汇总
| 项 | 结果 | 关键证据 |
|---|---|---|
| 测试⓪ PIPESTATUS 前提 | PASS | `PIPESTATUS0=1` |
| 测试① C-2 add 失败不被吞 | PASS | 「⚠ git add 失败」出现 / 无「无新变更」/ 心跳 fail |
| 测试③ 端到端 ok 路径 | PASS | 心跳 `result=ok` / 新 commit 7229135 / push 到达裸仓库 |
| 测试②(a) 文件缺失不告警 | PASS | `[info] ... 跳过停摆检查` + NO_ALERT |
| 测试②(b) 过期 ok 告警 | PASS | `SEVERE ... 距今49h (>36h 阈值)` |
| 测试②(c) 新鲜 ok 不告警 | PASS | NO_ALERT |
| 测试②(d) fail 不告警 | PASS | NO_ALERT |
| 补充: active 抑制不重发 | PASS | 第 2 轮 `[suppress] ... 不重发` |
