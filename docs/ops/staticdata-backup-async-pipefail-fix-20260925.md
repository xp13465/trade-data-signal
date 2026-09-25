# staticdata_backup_async.sh pipefail 漏网修复(2026-09-25)

## 改了什么

`scripts/staticdata_backup_async.sh` 原只 `set -u`,导致 `cmd | tee` 管道退出码取 `tee`(恒 0),**首命令失败被静默吞掉**。本次在 `set -u` 下方新增:

```bash
# pipefail(2026-09-25 审查整改补): 管道退出码取首命令而非 `| tee` 的 tee(恒 0),
# 防 `cmd | tee` 首命令失败(rsync DB/JSON、git commit)被静默吞掉 → 心跳照写 ok,
# 新加的 C-3「36h 无 ok 告警」永不触发。审计全部 | tee 管道: notify 三处带 `|| true`
# (notify 失败不置位是良性, 语义不变); 其余均为 echo 纯日志管道, 无误伤。
set -o pipefail
```

改动后 L151(现 L156)已有的 `if [ "${PIPESTATUS[0]:-0}" -ne 0 ]` git add 双保险**原样保留**。

## 为什么必须修

三处 `cmd | tee` 漏网,失败被静默吞掉后心跳照写 `ok`:

| 位置 | 管道 | 修复前后果 |
|---|---|---|
| L118 rsync DB | `rsync ... 2>&1 \| tee -a "$LOG" \|\| { ... }` | rsync 失败不置 `STATICDATA_FAIL=1`,心跳写 `ok` |
| L137 rsync JSON | 同上 | 同上 |
| L191 git commit | `if ! git commit ... 2>&1 \| tee -a "$LOG"; then` | commit 失败被吞,永远走 else 去 push,心跳写 `ok` |

最致命是 L191:commit 失败 → `STATICDATA_FAIL` 保持 0 → 心跳写 `ok` → 本次新加的 C-3「36h 无 ok 告警」**永不触发**。心跳会说谎,新加的监控被老漏网废掉。

## 29 处(实际 27 处)| tee 管道审计结论

grep 全部 `| tee` 管道逐个核对(排除新增注释 3 行,实际 27 处):

- **20 处 echo 纯日志管道**(L66/67/88/103/111/119/122/132/138/141/157/160/181/183/192/207/223/229/247/250):echo 恒退出 0,pipefail 无误伤。
- **2 处 rsync 失败需置位**(L118 DB、L137 JSON):带 `|| { echo "⚠ ..."; STATICDATA_FAIL=1 }` 块,pipefail 让 rsync 失败正确进块置 FAIL。实测通过(见测试④)。
- **1 处 git add**(L151):pipefail 后管道退出码=git add 退出码;既有 `PIPESTATUS[0]` 检查双保险保留。实测通过(见测试①)。
- **1 处 git commit**(L191):pipefail 后 `if ! git commit ... | tee` 正确捕获 commit 失败进 then 分支置 FAIL。实测通过(见测试③)。
- **3 处 notify 带 `|| true`**(L107 仓库缺失降级/L187 超阈值跳过/L246 备份失败告警):notify 失败不置位是良性,`|| true` 语义不变,pipefail 不误伤。

**无"首命令非 0 退出属预期"的管道被误伤**。补充核对非 tee 管道:L130 sed 重定向 `|| true`、L163 `grep -c . || true`、L190 纯文本处理管道(命令替换内 `head -5` 正常退出,赋值本身返回 0)、L220 tail `|| true`——均无误伤。

## 自测命令与原始输出

全部在 /tmp 临时仓库,`STATICDATA_REPO` 只指 /tmp,notify 走 `STATICDATA_BACKUP_NOTIFY_DRY_RUN=1`,不碰生产。

### 测试⓪ 机制:pipefail/PIPESTATUS

```bash
printf 'false | tee /tmp/sdfix-tee.txt; echo "P0=${PIPESTATUS[0]}"\n' > /tmp/sdfix-mech.sh
bash /tmp/sdfix-mech.sh
```

输出:`P0=1`(false 的退出码被管道保留)

### 测试① add 失败注入(GIT_INDEX_FILE 指向不存在路径)

```bash
STATICDATA_REPO=/tmp/sdfixC REPO=/tmp/sdfixCruns PY=/Users/linhuichen/code/trade/.venv/bin/python GIT_INDEX_FILE=/nonexistent-dir/gitindex STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 bash scripts/staticdata_backup_async.sh test
```

日志关键行:`fatal: Unable to create '/nonexistent-dir/gitindex.lock'` → `⚠ git add 失败(staticdata 仓库 /tmp/sdfixC), 置 STATICDATA_FAIL=1, 跳过 commit(git 历史缺口, 需人工排查)`;**无** `✓ staticdata 无新变更`;心跳 `{"ts":"2026-09-25 17:24:04","result":"fail",...}`;退出码 1。

### 测试② 端到端(正常仓库 + 新变更,无注入)

```bash
STATICDATA_REPO=/tmp/sdfixE REPO=/tmp/sdfixEruns PY=/Users/linhuichen/code/trade/.venv/bin/python STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 bash scripts/staticdata_backup_async.sh test
```

心跳 `{"ts":"2026-09-25 17:25:10","result":"ok","files":43,"bytes":85412,"duration_s":5}`;`git -C /tmp/sdfixE log` 见新 commit `78bfa00 data backup [test]`;push 到本地 bare remote 成功(remote log 同 hash);退出码 0。

### 测试③ L191 commit 失败注入(纯 env:GIT_AUTHOR_DATE=invalid,不碰 .git)

```bash
STATICDATA_REPO=/tmp/sdfixD REPO=/tmp/sdfixDruns PY=/Users/linhuichen/code/trade/.venv/bin/python GIT_AUTHOR_DATE=invalid STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 bash scripts/staticdata_backup_async.sh test
```

日志:`fatal: invalid date format: invalid` → `⚠ staticdata commit 失败(best-effort)`;心跳 `result=fail`;**无** `✓ staticdata 备份完成`;退出码 1。**pipefail 修复前此场景走 else push 且心跳写 ok。**

### 测试④ L118/L137 rsync 失败注入(源目录留空,不碰 .git)

```bash
STATICDATA_REPO=/tmp/sdfixC REPO=/tmp/sdfixFempty PY=/Users/linhuichen/code/trade/.venv/bin/python STATICDATA_BACKUP_NOTIFY_DRY_RUN=1 bash scripts/staticdata_backup_async.sh test
```

日志:DB rsync `rsync error ... (code 23)` → `⚠ staticdata DB rsync 失败,不阻塞`;JSON rsync 同样失败;心跳 `result=fail`;退出码 1。**pipefail 修复前两处 rsync 失败被 tee 恒 0 吞掉,心跳写 ok。**

> 注:notify 行报 `can't open file '/tmp/.../scripts/notify.py'`(REPO 指向 /tmp 无 scripts/)是预期——正是 notify `|| true` 语义:notify 失败不置位、不中断主链。dry-run 下未真发邮件/飞书。

## 未实测项

无。L113/L132(rsync DB/JSON)原本计划"造不出不碰 .git 场景就记未实测",实测发现 rsync 失败只需留空源目录即可、不碰 .git,已直接实测通过(测试④)。

## 复现

- 复现测试需:本地 `/Users/linhuichen/code/trade/.venv/bin/python`(with_lock.py re-exec 用),四个 /tmp 临时 git 仓库(sdfixC/sdfixD/sdfixE 均 init+commit 一次),REPO 侧 runs 目录按需 seed 或留空。
- 测试命令与断言见上文「自测命令与原始输出」。全部命令不改生产静态数据仓库,`STATICDATA_REPO` 只指 /tmp;生产部署由 `deploy.sh` 触发,不受本测试影响。
- 配套 commit 含本实施文档 + 脚本 pipefail 改动 + 两份 review 文档并入(feat/staticdata-backup-async 分支)。
