# 修复审查 FAIL 四条 — 完成报告（2026-11-17）

> 落地来源: /tmp/fix-review-fail-report.md; 落地时间 2026-11-17; 对应本次 commit: 61d8b6f6c

- 分支：`feat/upload-retry-capture-fix-20261117`（续改同一分支，未新建 worktree、未切分支）
- base commit：`d1dc4af18`，本次 commit：`61d8b6f6c`
- 已推送：`d1dc4af18..61d8b6f6c feat/upload-retry-capture-fix-20261117 -> origin/feat/upload-retry-capture-fix-20261117`
- 残留后台任务：**无**（全量 pytest 用 nohup 启动，已自然退出，未出现 `moved to the background (ID:`）

## 四条修法（文件:行号）

1. **永久 4xx 不重试（A2）** — `scripts/r2_safe_write.py:541-546`
   `commit()` 在 412/409/403/400 分支之后接入 `_permanent_http(st)`：404/405/422 等其余永久 4xx 一律
   `state=failed` + `UnsafeWrite('write rejected HTTP {st}')`，恰好 1 次 PUT；408/429 不在判据内，仍走确认/重放。
   412 例外（`st == 412 and transport_failures and self.confirm(row)`）原样保留。
2. **用例⑤假覆盖（C7）** — `scripts/tests/test_upload_retry_capture_fix_20261117.py:103-106,257-276`
   fake transport 新增 `landed_raise`：**先 `self.put(...)` 真落地字节，再抛 `OSError`**（模拟「自己写入已落地、
   响应丢失」）⇒ 第 2 次 PUT 因旧 `if-match` 收到 412，真进入例外分支。新增 ⑪（`:355-368` + intruder hook
   `:111-115`）：自己落地后他人抢先覆盖 ⇒ 412 ⇒ 确认不到自己的 write_id ⇒ 如实失败、对象保持他人字节。
3. **备份读回 404 空 body（A3）** — `scripts/r2_safe_write.py:297-307`
   `immutable()` 读回 GET 抛 `HTTP 404`（无论 body 是否 NoSuchKey）统一归 `readback_empty` 可重试；
   其余永久 4xx（如 403）仍直接抛；读回**非空但字节不同**仍 `raise('backup readback SHA256 mismatch')` 不重试不覆盖。
   用例⑩ `:341-350` + fake 计数器 `:63,83-85`。
4. **诊断字段两处错记（配套）** — `scripts/backup_state_capture.py:774`（`retries` 移到窗口检查之后，窗口耗尽记 0）、
   `:634`（`changed_total=len(set(exc.changed))`，不再并 vanished）。**顺带根因修复**：`:330-331` `SourceChanged`
   传空列表 `[]` 时旧写 `list(changed or [rel])` 会回退成 `[rel]`，导致「只有 vanished」场景被错记成 changed
   （新用例⑦ `:524-548` 抓出来的真实第三个病灶）。
   用例：窗口耗尽 `retries==0`（`:519`）、只有 vanished 时 `changed_total==0`（`:544-546`）。

文档：`docs/backup-restore.md:393-401` 与实现对齐（404+空 body 按空重试、408/429 可重试、其余永久 4xx 只 1 次 PUT、
412 例外保留、retries=0/changed_total=0 语义），去掉过头表述。

## 判别力自证（实跑，改动前先 cp 备份、跑完 cp 还原，`md5` 校验一致）

| # | 实验 | 结果 |
|---|---|---|
| ① | 412 例外短路成 `if False and ...` | **1 failed, 29 passed** — 用例⑤红（判别力成立） |
| ② | 去掉 `commit()` 里的 `_permanent_http(st)` 接入 | **3 failed, 27 passed** — 404/405/422 三参数全红 |
| ③ | `TRANSPORT_RETRIES = 2 → 0` | **8 failed, 22 passed** — ①首断次成/②持续断/④读回404/⑤412/⑨408/⑨429/⑩404空body/⑪他人覆盖 全红 |
| ④ | 回退「404 空 body 按空重试」这段 | **1 failed** — 用例⑩红（修3 非假覆盖） |

## 测试末行（原样）

- 定向：`python -m pytest -q scripts/tests/test_upload_retry_capture_fix_20261117.py scripts/tests/test_r2_protected_writes_20261111.py scripts/tests/test_backup_state_capture.py`
  → `130 passed in 11.51s`
- 全量（L52）：`python -m pytest -q scripts/tests/`
  → `5413 passed, 6 skipped, 176 subtests passed in 712.53s (0:11:52)`
  （日志 `/tmp/full-pytest-fix-review-fail.log`，0 failed；较上轮 5405 多 8 个 = 新增/参数化用例）

## 同类错误面清单（§23.2）

- 永久 4xx 判据其他消费点：`immutable()` 已有同判据（未动）；`recover()` 的 PUT 语义本轮未改（审查 D10-18 已声明）；无第三处写路径。
- `_permanent_http` 只此一处接入新增，未改成集合字面量（根因修，非逐状态码补丁）。
- 备份读回：`get()` 已有 404+NoSuchKey→None；`immutable` 读回分支是唯一消费者。
- 计数类字段：`sample_diff.changed_total` 由实际 diff 计算（独立且正确）；`vanished_total` 已分开；`SourceChanged` 空名单回退是同类第三处，已一并修。
- 文档：仅 `docs/backup-restore.md` 提及该测试文件（grep 确认），已对齐。

## 举一反三（§23.3）

- 同模式：永久 4xx 判据复用 `_permanent_http`；412 例外只加「真落地字节」测试动作，不改生产逻辑。
- 同数据源：备份桶「NoSuchKey 空」与「404 空 body」两形态共用同一重试循环，共用同一 `readback_empty` 日志口径。
- 相关展示位：机制说明（文件头注释）+ 测试清单（`docs/backup-restore.md`）+ stdout/stderr 诊断字段三处一致。

## 边界维度清单（§5.8① 七轴，供 reviewer §10.8 独立复核对账）

| 轴 | 结论 | 测/不测 + 理由 | 来源 |
|---|---|---|---|
| 输入域（HTTP 状态码） | 覆盖 412/400/403/409/404/405/422/408/429 | 测；451/418 等其余永久码由同一 `_permanent_http` 单点判据覆盖（400≤st<500 且非 408/429），不为每码造用例 | A2 |
| 状态组合（备份读回四态） | NoSuchKey 空 / 404 空 body / 200 同字节 / 200 不同字节 | 全测 | A3 |
| 时序（重试次数与窗口） | 1/2/3 次尝试、窗口耗尽不睡不重试、retries 计数 | 测；真实 90s 窗口不实跑（monkeypatch 常量，生产常量数值另有断言） | B5/修4 |
| 上下游依赖（调用方/锁/预算） | commit 唯一生产调用点在按 key 锁内，重试前 `_work_budget_check`/`_work_sleep` 未动 | 不测 + 理由：审查 D10/D11 已核代码路径，既有 `test_r2_protected_writes` 覆盖 | review D10/D11 |
| 极端值（multipart ≥100MB / 空 payload） | multipart guard 在本次改动前分支，未动 | 不测 + 理由：100MB 造样本成本高，孤儿分片由既有 lifecycle 兜底（审查 D10-5 已声明） | review D10-5 |
| 回退路径（412 例外确认失败 / 重试耗尽） | ⑤认自己字节成功、⑪他人覆盖如实失败不覆盖、②耗尽 rc=1 且 state=unknown | 全测 | A1/A2 |
| 并发与重入（他人抢先写 / 同 key 锁 / 续跑 recover） | ⑪他人抢先覆盖已测；recover() 跨进程续跑本轮未改语义 | 部分测；recover 不测+理由（非本次改动面，审查 D10-18 已声明） | A1/审查 D10 |

## 残留声明

- 后台任务：无。
- 临时探针文件仅落 `/tmp`：`/tmp/r2_safe_write.fixed.py`（判别力实验用的备份副本，已还原，md5 与工作区一致）。
- 未 push main、未 merge、未 deploy、未发通知、未碰云上；未写 `/Users/linhuichen/.claude/`；未碰 worktree 内 `.claude/` 路径。
- 工作区干净（commit 后 `git status --porcelain` 空），改动仅 4 个文件。
