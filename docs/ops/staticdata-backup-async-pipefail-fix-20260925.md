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

## 复验(2da9db159) · 静态层

独立 reviewer 静态复核(2026-09-25,只读代码,未跑测试脚本、未建临时仓库、无任何 .git 写操作)。

### 1. diff 洁净度:PASS

`git show 2da9db159 -- scripts/staticdata_backup_async.sh` = 仅在 `set -u` 下方新增 4 行注释 + `set -o pipefail`,共 5 行,无夹带。
`git diff b13c7853d 2da9db159 -- scripts/staticdata_backup_async.sh` 与上一命令同(只有这 5 行增量),确认 b13c7853d 的 C-1~C-5 既有整改(C-5 仓库缺失降级/C-3 心跳/_hb_write/C-2 add 退出码判定/PIPESTATUS 双保险)未被误改或回退。

### 2. 文档并入逐字节一致:PASS

- `git diff 2262ddf10 2da9db159 -- docs/ops/staticdata-backup-async-review-2026-09-25.md` → 无输出
- `git diff 3296c162f 2da9db159 -- docs/ops/staticdata-backup-async-review-tests-2026-09-25.md` → 无输出

两份 review 文档与来源 commit 完全一致,逐字节并入无漂移。

### 3. 27 处 | tee 管道审计复核:PASS

`git show 2da9db159:scripts/staticdata_backup_async.sh | grep -n "| tee"` 排除新增注释 3 行,实际 27 处,逐一核对:

- **20 处 echo 纯日志管道**(L66/67/88/103/111/119/122/132/138/141/157/160/181/183/192/207/223/229/247/250):echo 恒 0,pipefail 添加后管道退出码仍 0,无误伤。
- **3 处 notify `| tee ... || true`**(L107 仓库缺失降级/L187 超阈值跳过/L246 备份失败告警):notify 失败不置位、不中断主链是良性,`|| true` 语义在 pipefail 下仍兜底,语义不变。
- **2 处 rsync `| tee ... || { echo ...; STATICDATA_FAIL=1; }`**(L118 DB、L137 JSON):pipefail 让 rsync 失败正确进入 `||` 块置 FAIL。这正是本次修复目标(修复前管道退出码=tee 恒 0,`||` 永不触发,rsync 失败被静默吞掉)。这两个 `|| { STATICDATA_FAIL=1 }` 块在 b13c7853d 已存在(非本次新增),本次是把它们从"永不触发"变"真正生效"。
- **1 处 git add**(L151):pipefail 后 `git add ... | tee` 管道退出码=git add 的 rc;既有 L152 `if [ "${PIPESTATUS[0]:-0}" -ne 0 ]` 双保险保留且与 pipefail 取值一致不冲突(pipefail 改的是管道整体退出码,PIPESTATUS[0] 读首命令 rc,两者同时成立,行为正确)。
- **1 处 git commit**(L191): `if ! git -C ... commit ... 2>&1 | tee -a "$LOG"; then` → pipefail 下 commit 失败时管道非 0,`if !` 正确进 then 分支置 FAIL(best-effort)。

无"首命令非 0 退出属预期"的管道被误触发 `||` 处理器或 `if !` 分支。

### 4. 非 tee 管道审计:PASS

grep 全部 `|[^|]` 含"命令替换内管道"两处,pipefail 对它们无实质影响:

- **L163** `_N=$(printf '%s\n' "$_CHANGED" | grep -c . || true)`:命令替换在赋值上下文,内部管道末尾 `|| true` 兜底,且 grep -c 有匹配即 0,行为不变。
- **L190** `_BODY=$(printf '%s\n' "$_CHANGED" | sed ... | sort | uniq -c | sort -rn | head -5 | awk ...)`:命令替换内管道,赋值语句退出码=命令替换退出码(取最后命令 awk 的 rc,恒 0);pipefail 下中间命令失败也只影响该命令替换(不进 `if`/`||`,无 set -e),不中断脚本。行为不变。
- L130 `sed 's|/Users/linhuichen|...|'` 中的 `|` 是 sed 分隔符非管道,grep 误匹配,无影响。
- bg push 段 `wait "$_push_pid"` 单命令取 rc,非管道,pipefail 不涉及。

### 5. 行为变更影响面(§15 重点):PASS

加 pipefail 后:正常路径行为不变(echo 恒 0、rsync/add/commit 成功 rc=0);失败路径从"静默通过(tee 恒 0)"变"置 STATICDATA_FAIL=1 + --severe 告警 + 心跳 fail"。逐场景评估"会不会误报":

- **rsync 返回非 0 但无害**:唯一现实场景是 rsync code 23(partial transfer)或 24(vanish),多为源文件在备份期间被并发写/个别文件瞬时不可读。但:①备份为异步任务,deploy.lock 持锁等 deploy 退出后才 rsync,源码并发窗口极小;②即便偶发 code 23,备份确实不完整,触发告警+心跳 fail 符合 C-3 设计意图(宁可告警让 C-3 不重复炸,也不能静默写 ok)= **不算误报,性质是"该报的报"**。dedup 1h 限频。
- **git commit 无变更返回非 0**:**已有守卫**——L159 `elif git -C "$STATICDATA_REPO" diff --cached --quiet 2>/dev/null; then echo "✓ staticdata 无新变更,跳过 commit"`。无变更时走此 elif 分支,根本不进 commit(`if ! ... commit` 在 else 分支内)**不会出现"无变更→commit 返回 1→误置 FAIL"**。
- **git add 失败**:真实失败(索引写不了),置 FAIL 符合 C-2 整改目标,非误报。
- **push 失败/超时**:真实失败(远端不可达),且既有 900s 超时 kill 保护链路未受影响。
- **notify 失败**:`|| true` 兜底,不置 FAIL,不误报。

结论:**无实质误报场景**——正常路径不变,唯一"非 0 但可能无害"的 rsync code 23 属"备份不完整该看见",方向正确;commit 无变更场景已被 diff --cached --quiet 守卫挡在 commit 之前,不会误置 FAIL。

### 6. 注释准确性(小 nit,裁定)

新增注释第 4 行"其余均为 echo 纯日志管道, 无误伤"在字面上不准确:除 notify 3 处外,实际 27 处 | tee 里还有 2 处 rsync + 1 处 git add + 1 处 git commit 共 4 处非管道。但上下文本身已在前文(commit message 及实施文档审计表)把这 4 处单独点明,现在注释这行属于"审计结论压缩"时把非 echo 的四处误合并进"其余均为 echo"。**裁定:建议改,但不阻塞本 commit**(可下个 commit 顺手),理由:①注释是对代码读者的承诺,把 rsync/commit 说成"纯 echo"误导后来者以为这 4 处无需关注;改为"其余为 20 处 echo + 2 处 rsync + 1 处 git add + 1 处 git commit,均已核对"更严谨。②改动成本 1 行,零风险。按 §10.2 属 50 分 nit(不重要但表述真实可改),不进阻塞性 finding。

### 7. 语法:PASS

`git show 2da9db159:scripts/staticdata_backup_async.sh > /tmp/sdreview-pf.sh && bash -n /tmp/sdreview-pf.sh` → SYNTAX-OK

### 8. §24/§8 无关性:PASS

`git show 2da9db159 --stat` 文件清单仅 `scripts/staticdata_backup_async.sh`(5 行)+ 3 份 docs/ops/*.md(实施文档 96 行 + 并入 review 56 行 + 并入 tests 167 行)。**无任何前端文件**(app.js/lab.js/common.js/style.css/index.html 均不在 diff),无版本串/bump 的 concern。不需要 bump 版本串 / build_min。§22 数据一致性不涉及(本次无数据产物)。

## 复验结论

8 项全部 PASS;0 FAIL 0 存疑。唯一建议:第 6 项注释措辞可优化(不阻塞,实施侧下一步可顺手);§15 影响面已确认 OK(调用方 deploy.sh 异步触发、退出码不因本次改动产生误报;新增 FAIL 告警 → notify dedup 限频 + 心跳 fail 是修复目标本身)。
