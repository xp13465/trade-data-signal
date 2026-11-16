# 修复落地报告:上传条件 PUT 有界重试 + 捕获一致性诊断(2026-11-17,续跑收尾)

> 落地来源: /tmp/fix-upload-capture-report.md; 落地时间 2026-11-17; 对应本次 commit: d1dc4af18

- 工作目录:`/Users/linhuichen/code/trade/.claude/worktrees/agent-adf470bb5b748779a`
- 分支:`feat/upload-retry-capture-fix-20261117`(原分支延续,未新建 worktree、未切分支)
- base commit:`26db7ea794d6e9b477ab0074fb9ccd2b1ec2832e`(`git merge-base --is-ancestor origin/main HEAD` = base-fresh)
- **本次 commit**:`d1dc4af1873c56f5f92c3e1e86b32d00c8cff06c`(4 files changed, +755/−50)
- 改动文件集(与任务书完全一致,无第 5 个路径):
  1. `scripts/r2_safe_write.py`(M,+143/− 区间)
  2. `scripts/backup_state_capture.py`(M)
  3. `docs/backup-restore.md`(M)
  4. `scripts/tests/test_upload_retry_capture_fix_20261117.py`(新增 475 行)

## 一、修法一:上传/备份写入的传输层有界重试(`scripts/r2_safe_write.py`)

- 依据注释与常量:`scripts/r2_safe_write.py:24-51`
  - `TRANSPORT_RETRIES = 2`(:40)、`retry_wait()`(:44,2s→8s ±20% 抖动)、`_permanent_http()`(:50,4xx 中排除 408/429)
- 观测日志:`_log_retry()`(`:236`),stderr 单行 `R2_WRITE_RETRY` JSON(key/attempt/error_kind/elapsed_ms/exhausted),不污染 stdout
- 备份桶不可变写入 `immutable()`:`:276` 起
  - 键内容寻址 ⇒ 重放同一 bytes 幂等;`if-none-match:'*'` 下 412 视为「同内容已存在」,读回 sha 校验通过即成功
  - 读回为空(404)或 GET 报错 ⇒ 可重试;读回字节不同(内容寻址路径上出现别的字节=真异常)⇒ 不重试不覆盖
  - 永久 4xx(412 除外)⇒ 直接 `UnsafeWrite`,不重试
  - 重试前过 `_work_budget_check` / `_work_sleep`(沿用 #364 工作预算约束)
- 主对象条件写入 `commit()`:`:494` 起(重试循环 `:509`)
  - 未取得确认(HTTP 0 连接断 / 5xx / 200 但 write-id+sha 读回确认不到)⇒ 有界重放
  - 412/409/403/400 ⇒ 不重试不覆盖;**唯一例外**:`st == 412 and transport_failures and self.confirm(row)` —— 前序尝试本身是传输层失败,本次 412 可能由「自己那次写入已落地」造成,按 write_id+sha 确认到自己的字节才算成功(`:520-524`)
  - multipart 中途未 complete 沿用既有语义直接判失败,不新开 upload-id 重放
  - 重试耗尽:与原实现同口径 `UnsafeWrite(f'write unconfirmed HTTP {st}; no fallback')`,不吞错

## 二、修法二:捕获一致性诊断/有界间隔/瞬态排除(`scripts/backup_state_capture.py`)

- 常量:`:118-120` — `RETRY_INTERVAL_SECONDS = 2.0`(原 0s)、`RETRY_TOTAL_WINDOW_SECONDS = 90.0`(总窗口上限)、`MAX_REPORTED_CHANGES = 20`(清单截断,另带总数)
- 瞬态中间件判定 `is_transient_intermediate()`:`:247`,只排 `.receipt-*` 与 `*.tmp[.\-_]`/`*.tmp`(宁窄勿宽:`.json.tmpl` 不匹配);展开时按设计排除并记 `skipped`(`transient_intermediate_by_design`,`:568`,登记于 `BY_DESIGN_SKIP_REASONS` `:105`)
- `SourceChanged` 携带 offender 清单:`:320`(`changed`/`vanished` 列表)
- finalize 复查不再「首个变化即抛」:枚举全部 changed/vanished 后再抛(改动点 `:613` 起)
- 每轮采样快照 + 两轮差异 `_sample_diff()`:`:717`(added/removed/changed,各截断带总数)
- 重试调度 `capture()`:`:728` — 正间隔 2s、受 90s 总窗口约束(`window_exhausted` 时不再等待),重试前 stderr 打 `STATE_CAPTURE_RETRY`(`:763`)含 offender 清单与采样规模
- 失败输出:manifest 增加 `changed_files`/`changed_total`/`vanished_files`/`vanished_total`/`sample_diff`/`retry_window_exhausted`,stderr 打 `STATE_CAPTURE_INCONSISTENT`(`:797`);`main()` 失败行把上述字段一并打给 stdout(`:1045` 起)
- 文档同步:`docs/backup-restore.md` 两处(一致性段 + 修复批清单),写明 2s 正间隔/90s 窗口/判死点名/中间件宁窄勿宽排除

## 三、测试逐项结果

### 针对性用例(本次收尾重跑,命令与会话记录一致)

```
/Users/linhuichen/code/trade/.venv/bin/python -m pytest -q \
  scripts/tests/test_upload_retry_capture_fix_20261117.py \
  scripts/tests/test_r2_protected_writes_20261111.py \
  scripts/tests/test_backup_state_capture.py
```

末行原样:
```
122 passed in 11.07s
```

### 全量用例(上一 agent 实跑,日志 `/tmp/full-pytest-20261117-final.log`)

汇总行原样:
```
5405 passed, 6 skipped, 176 subtests passed in 713.58s (0:11:53)
```

### 新增用例覆盖面(`scripts/tests/test_upload_retry_capture_fix_20261117.py`,16 个测试函数 / 参数化展开后计 22 用例)

上传重试侧:`test_first_put_connection_loss_then_success` / `test_persistent_connection_loss_three_attempts_then_fail` / `test_412_not_retried_and_never_overwrites` / `test_backup_readback_empty_twice_then_success` / `test_own_write_landed_then_412_confirms_own_bytes` / `test_permanent_403_not_retried` / `test_backup_corrupt_readback_not_retried` / `test_upload_path_end_to_end_still_succeeds`
捕获侧:`test_capture_stable_dir_consistent` / `test_capture_names_the_file_that_keeps_changing` / `test_capture_ignores_receipt_and_tmp_intermediates` / `test_capture_retry_interval_is_positive_and_used` / `test_capture_retry_total_window_bound` / `test_capture_main_stdout_names_offenders` / `test_is_transient_intermediate_unit`(参数化)

### 判别力自证(上一 agent 实跑,本收尾未重跑)

- 拿掉上传重试 ⇒ 4 红
- 拿掉捕获三项(有界间隔 / 瞬态排除 / 报文件名)⇒ 5 红

## 四、推送结果

- `git push -u origin feat/upload-retry-capture-fix-20261117` ⇒ `* [new branch]`,并已设 upstream
- 远端核对:`git ls-remote origin feat/upload-retry-capture-fix-20261117` = `d1dc4af1873c56f5f92c3e1e86b32d00c8cff06c`(与本地 `HEAD` 一致)
- **未 push main、未 merge、未 deploy、未碰云上、未发任何通知**
- 工作区:提交后 `git status --porcelain` 空

## 五、残留声明

- 残留后台任务:**无**。本次全程无 `moved to the background (ID:` 输出。
- 未在本 worktree 内读写任何 `.claude/` 路径;未写 `/Users/linhuichen/.claude/`。
- 未改任何代码逻辑:本次只做 add(4 路径)/ 测试 / commit / push feat。
- 待主控:走 `scripts/main-merge.sh feat/upload-retry-capture-fix-20261117` 合并上线(本 agent 不做)。
